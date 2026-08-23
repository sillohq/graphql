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
