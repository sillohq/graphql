"""Batching, so a graph query is not a table scan per node.

N+1 is GraphQL's defining failure: ``{ posts { author { name } } }`` asks for
one author per post, and a resolver written the obvious way issues one query
per post. A loader collects the keys its siblings asked for during the same
tick of the event loop and answers them all with one call.

Registration is a decorator, like everything else a ``Graph`` is configured
with::

    @graph.loader
    async def load_author(keys: list[int]) -> list[User]:
        rows = await User.objects.filter(id__in=keys).all()
        return align(rows, keys)

and a resolver simply calls it::

    @field
    async def author(ctx: HttpContext, root: Post) -> User:
        return await load_author(root.author_id)

There is no registry to thread through. The batch a call joins is found from
the context variable the transport sets, so state is per operation and two
concurrent requests never share a cache.
"""

from __future__ import annotations

import asyncio
import typing

from sillo_graphql.errors import SilloGraphQLError

__all__ = ["Loader", "LoaderError", "LoaderRegistry", "loader"]

K = typing.TypeVar("K")
V = typing.TypeVar("V")

BatchFn = typing.Callable[
    [list[typing.Any]], typing.Awaitable[typing.Sequence[typing.Any]]
]


class LoaderError(SilloGraphQLError):
    """A batch function broke its contract."""


class _Batch:
    """One loader's pending keys, for one operation.

    Kept separate from :class:`Loader` because the loader is defined once at
    import time and shared by every request, while this is per operation and
    dies with it.
    """

    __slots__ = ("cache", "loader", "queue", "scheduled")

    def __init__(self, loader: Loader) -> None:
        self.loader = loader
        self.queue: list[tuple[typing.Any, asyncio.Future]] = []
        self.cache: dict[typing.Any, asyncio.Future] = {}
        self.scheduled = False

    def load(self, key: typing.Any) -> asyncio.Future:
        """A future for *key*, joining the pending batch."""
        cacheable = self.loader.cache and _hashable(key)
        if cacheable and key in self.cache:
            return self.cache[key]

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self.queue.append((key, future))
        if cacheable:
            self.cache[key] = future

        if not self.scheduled:
            self.scheduled = True
            # `call_soon` rather than awaiting here: the executor resolves the
            # siblings of this field in the same tick, so deferring to the next
            # one is exactly what turns n calls into one.
            asyncio.get_running_loop().call_soon(self._start)
        return future

    def prime(self, key: typing.Any, value: typing.Any) -> None:
        """Seed the cache, for a value already in hand."""
        if not _hashable(key):
            raise LoaderError(
                f"cannot prime {self.loader.name} with unhashable {key!r}"
            )
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        future.set_result(value)
        self.cache[key] = future

    def forget(self, key: typing.Any) -> None:
        """Drop a cached key, so the next load reaches the batch function."""
        self.cache.pop(key, None)

    def _start(self) -> None:
        """Hand the queue to the batch function.

        The task is kept only so it is not garbage collected mid-flight; its
        result reaches callers through the futures, not through the task.
        """
        pending, self.queue = self.queue, []
        self.scheduled = False
        if not pending:  # pragma: no cover - only reachable if a caller drains it
            return
        task = asyncio.ensure_future(self._run(pending))
        self.loader._tasks.add(task)
        task.add_done_callback(self.loader._tasks.discard)

    async def _run(self, pending: list[tuple[typing.Any, asyncio.Future]]) -> None:
        size = self.loader.max_batch_size or len(pending)
        for start in range(0, len(pending), size):
            await self._run_chunk(pending[start : start + size])

    async def _run_chunk(self, chunk: list[tuple[typing.Any, asyncio.Future]]) -> None:
        keys = [key for key, _ in chunk]
        try:
            values = await self.loader.batch_fn(keys)
        except Exception as exc:
            for _, future in chunk:
                if not future.done():
                    future.set_exception(exc)
            return

        if len(values) != len(keys):
            error = LoaderError(
                f"{self.loader.name} was given {len(keys)} keys and returned "
                f"{len(values)} values; a batch function must return one value "
                f"per key, in order"
            )
            for _, future in chunk:
                if not future.done():
                    future.set_exception(error)
            return

        # Lengths were checked above, so `strict` only documents that.
        for (_, future), value in zip(chunk, values, strict=True):
            if future.done():  # pragma: no cover - a cancelled operation
                continue
            # An exception in the list is that one key's failure, not the
            # batch's: one missing row should not fail every sibling field.
            if isinstance(value, Exception):
                future.set_exception(value)
            else:
                future.set_result(value)


class Loader(typing.Generic[K, V]):
    """A batch function, plus the per-operation plumbing around it.

    Instances are callable: ``await load_author(1)``. They are created by the
    :func:`loader` decorator or by ``@graph.loader``, and are safe to define
    at module scope — no request state lives on them.

    Attributes:
        name: Used in error messages; defaults to the function's name.
        max_batch_size: Largest number of keys handed over at once. ``None``
            passes the whole batch, which is right until a database refuses a
            ten-thousand-item ``IN`` clause.
        cache: Whether repeated keys within one operation are answered once.
    """

    def __init__(
        self,
        batch_fn: BatchFn,
        *,
        name: str | None = None,
        max_batch_size: int | None = None,
        cache: bool = True,
    ) -> None:
        if max_batch_size is not None and max_batch_size < 1:
            raise ValueError("max_batch_size must be at least 1, or None")
        self.batch_fn = batch_fn
        self.name = name or getattr(batch_fn, "__name__", "loader")
        self.max_batch_size = max_batch_size
        self.cache = cache
        self.__doc__ = getattr(batch_fn, "__doc__", None)
        # Strong references to in-flight dispatches. Without these the event
        # loop may collect a task nobody is awaiting, and the futures it was
        # going to resolve hang forever.
        self._tasks: set[asyncio.Task] = set()

    def _batch(self) -> _Batch:
        from sillo_graphql.context import current_context

        try:
            context = current_context.get()
        except LookupError:
            raise LoaderError(
                f"{self.name} was called outside a GraphQL operation. Loaders "
                f"batch per request, so they need one to belong to; in a test, "
                f"use `LoaderRegistry().scope()`."
            ) from None
        return context.loaders.batch(self)

    async def __call__(self, key: K) -> V:
        """Load one key."""
        return typing.cast(V, await self._batch().load(key))

    async def load(self, key: K) -> V:
        """Load one key. The same as calling the loader."""
        return typing.cast(V, await self._batch().load(key))

    async def load_many(self, keys: typing.Iterable[K]) -> list[V]:
        """Load several keys as one batch, in the order given."""
        batch = self._batch()
        futures = [batch.load(key) for key in keys]
        return typing.cast("list[V]", await asyncio.gather(*futures))

    def prime(self, key: K, value: V) -> None:
        """Seed this operation's cache with a value already in hand."""
        self._batch().prime(key, value)

    def forget(self, key: K) -> None:
        """Drop *key* from this operation's cache."""
        self._batch().forget(key)

    def __repr__(self) -> str:
        return f"Loader({self.name!r})"


class LoaderRegistry:
    """Every loader's state for one operation.

    Lives on the :class:`~sillo_graphql.context.GraphContext`, is built when
    the operation starts, and is dropped with it. Nothing is shared between
    requests, which is the property that makes loader caching safe at all.
    """

    __slots__ = ("_batches",)

    def __init__(self) -> None:
        self._batches: dict[int, _Batch] = {}

    def batch(self, loader: Loader) -> _Batch:
        """This operation's batch for *loader*, created on first use.

        Keyed by identity rather than by name, so two loaders that happen to
        wrap functions of the same name stay apart.
        """
        key = id(loader)
        batch = self._batches.get(key)
        if batch is None:
            batch = _Batch(loader)
            self._batches[key] = batch
        return batch

    def scope(self) -> typing.Any:
        """Make this registry current, for code outside an operation.

        Tests and background jobs want loaders without a request::

            async with LoaderRegistry().scope():
                await load_author(1)
        """
        return _Scope(self)

    def __len__(self) -> int:
        """How many distinct loaders this operation has touched."""
        return len(self._batches)


class _Scope:
    """Async context manager returned by :meth:`LoaderRegistry.scope`."""

    __slots__ = ("_context", "_token", "registry")

    def __init__(self, registry: LoaderRegistry) -> None:
        self.registry = registry
        self._token: typing.Any = None
        self._context: typing.Any = None

    async def __aenter__(self) -> LoaderRegistry:
        from sillo_graphql.context import GraphContext, current_context

        self._context = GraphContext(loaders=self.registry)
        self._token = current_context.set(self._context)
        return self.registry

    async def __aexit__(self, *exc_info: typing.Any) -> None:
        from sillo_graphql.context import current_context

        current_context.reset(self._token)
