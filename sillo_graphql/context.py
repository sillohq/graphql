"""What a resolver sees.

``sillo``'s pitch is one typed context object per connection, and this package
keeps that promise inside GraphQL: a resolver declares ``ctx: HttpContext`` and
gets the same object an HTTP handler would, not a dictionary lookup.

:class:`GraphContext` is what Strawberry is handed as ``context_value``. It
carries the connection's own context, a handle for influencing the response,
the request-scoped loader registry, and whatever a ``@graph.context`` hook
added. It is also a ``Mapping``, so ``info.context["ctx"]`` — the shape the
old ``sillo.graphql`` handler had — keeps working while a codebase migrates.
"""

from __future__ import annotations

import contextvars
import dataclasses
import time
import typing

if typing.TYPE_CHECKING:
    from sillo.core.http import HttpContext
    from sillo.websockets import WebSocketContext

    from sillo_graphql.loaders import LoaderRegistry

__all__ = ["GraphContext", "ResponseHandle", "current_context"]

#: The context of the operation being resolved, for code that cannot be
#: handed one. Loaders use it to find their per-request batch; nothing else
#: should need it, and a resolver never does — it declares ``ctx`` instead.
current_context: contextvars.ContextVar[GraphContext] = contextvars.ContextVar(
    "sillo_graphql_context"
)


@dataclasses.dataclass(slots=True)
class ResponseHandle:
    """A resolver's influence over the HTTP response.

    Strawberry executes the whole document before this package builds a
    response, so a resolver cannot return one. It can record intent here, and
    the transport applies it afterwards.

    Later writes win, and a resolver only ever raises the status: two
    resolvers disagreeing about whether the answer is 200 or 404 should not
    depend on which the executor reached first.

    Over a subscription there is no response to influence, and the recorded
    calls are simply never applied.
    """

    status_code: int | None = None
    _headers: dict[str, str] = dataclasses.field(default_factory=dict)
    _cookies: list[tuple[tuple[typing.Any, ...], dict[str, typing.Any]]] = (
        dataclasses.field(default_factory=list)
    )
    _deleted: list[tuple[tuple[typing.Any, ...], dict[str, typing.Any]]] = (
        dataclasses.field(default_factory=list)
    )

    def set_status(self, status_code: int) -> None:
        """Ask for this status, unless something already asked for a higher one."""
        if self.status_code is None or status_code > self.status_code:
            self.status_code = status_code

    def set_header(self, name: str, value: str) -> None:
        """Set a response header."""
        self._headers[name] = value

    def set_cookie(self, *args: typing.Any, **kwargs: typing.Any) -> None:
        """Record a cookie, with the arguments of ``BaseResponse.set_cookie``."""
        self._cookies.append((args, kwargs))

    def delete_cookie(self, *args: typing.Any, **kwargs: typing.Any) -> None:
        """Record a cookie deletion, with ``BaseResponse.delete_cookie``'s arguments."""
        self._deleted.append((args, kwargs))

    @property
    def headers(self) -> dict[str, str]:
        """The headers recorded so far."""
        return dict(self._headers)

    def apply(self, response: typing.Any) -> typing.Any:
        """Replay everything recorded onto a built response."""
        for name, value in self._headers.items():
            response.set_header(name, value)
        for args, kwargs in self._cookies:
            response.set_cookie(*args, **kwargs)
        for args, kwargs in self._deleted:
            response.delete_cookie(*args, **kwargs)
        return response

    def __bool__(self) -> bool:
        """Whether any resolver asked for anything."""
        return bool(
            self.status_code is not None
            or self._headers
            or self._cookies
            or self._deleted
        )


class GraphContext(typing.Mapping[str, typing.Any]):
    """The ``context_value`` every resolver is executed with.

    Attributes:
        http: The HTTP context, or ``None`` during a subscription.
        socket: The WebSocket context, or ``None`` over HTTP.
        response: What this operation wants done to the response.
        loaders: The request-scoped loader registry.
        user: The authenticated user, read from the connection.
        extra: Whatever a ``@graph.context`` hook returned.
        operation_name: The operation being executed, when it is named.
    """

    __slots__ = (
        "cost",
        "dependency_cache",
        "extra",
        "http",
        "loaders",
        "operation_name",
        "response",
        "socket",
        "started",
    )

    def __init__(
        self,
        *,
        http: HttpContext | None = None,
        socket: WebSocketContext | None = None,
        loaders: LoaderRegistry | None = None,
        extra: dict[str, typing.Any] | None = None,
        operation_name: str | None = None,
    ) -> None:
        from sillo_graphql.loaders import LoaderRegistry

        self.http = http
        self.socket = socket
        self.response = ResponseHandle()
        self.loaders = loaders if loaders is not None else LoaderRegistry()
        self.extra: dict[str, typing.Any] = dict(extra or {})
        self.operation_name = operation_name
        #: Filled in by cost analysis, and reported in ``extensions``.
        self.cost: int | None = None
        #: Shared by every ``Depend`` in this operation, so two resolvers that
        #: both ask for ``Depend(get_db)`` are handed one session rather than
        #: opening two against the same request.
        self.dependency_cache: dict[typing.Any, typing.Any] = {}
        #: When this operation began, on the monotonic clock. Read by the
        #: `on_operation` hooks, which are called after the fact and would
        #: otherwise have nothing to measure against.
        self.started = time.perf_counter()

    @property
    def connection(self) -> typing.Any:
        """Whichever context this operation actually arrived on.

        A resolver that only wants headers or the user does not care which
        transport it is on, and both contexts derive from ``BaseContext``.
        """
        return self.http if self.http is not None else self.socket

    @property
    def user(self) -> typing.Any:
        """The authenticated user, or ``None``.

        Read through rather than copied, because authentication middleware may
        resolve the user lazily and a snapshot taken at context-build time
        would be ``None`` for the whole operation.
        """
        connection = self.connection
        if connection is None:
            return None
        try:
            return connection.user
        except (ValueError, AttributeError):
            # `ctx.user` raises rather than returning None when no
            # authentication middleware is mounted. From a resolver's point of
            # view that is the same answer — nobody is signed in — and a field
            # gated on `auth=` should say "not authenticated", not 500.
            return None

    def __getitem__(self, key: str) -> typing.Any:
        """Mapping access, for the ``info.context["ctx"]`` shape.

        The old handler passed a bare ``{"ctx": ctx}`` dict. Supporting the
        same subscript means a schema can migrate one resolver at a time
        rather than all at once.
        """
        if key == "ctx":
            return self.connection
        if key in self.__slots__:
            return getattr(self, key)
        if key in self.extra:
            return self.extra[key]
        raise KeyError(key)

    def _keys(self) -> list[str]:
        """Every readable key, in order, with no repeats.

        A ``Mapping`` whose ``len`` disagrees with its iteration order breaks
        ``dict(context)``, and ``extra`` is caller-supplied — nothing stops it
        holding a key an attribute already uses.
        """
        keys = ["ctx", *self.__slots__]
        keys += [key for key in self.extra if key not in keys]
        return keys

    def __iter__(self) -> typing.Iterator[str]:
        return iter(self._keys())

    def __len__(self) -> int:
        return len(self._keys())

    def __repr__(self) -> str:
        transport = "ws" if self.socket is not None else "http"
        return f"GraphContext({transport}, operation={self.operation_name!r})"
