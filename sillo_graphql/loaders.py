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
