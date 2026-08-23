"""Errors, and the free builders that raise them.

``sillo`` builds responses with free functions — ``json()``, ``text()``,
``redirect()`` — rather than with methods on a response class. Errors here
follow the same shape: a resolver raises ``not_found("No such post")`` and the
transport turns it into a GraphQL error with a stable machine-readable code.

The codes are the ones clients actually branch on, so they are a closed set
rather than free text. A client that sees ``FORBIDDEN`` can offer a login;
one that sees ``INTERNAL_SERVER_ERROR`` can only apologise.
"""

from __future__ import annotations

import typing

__all__ = [
    "ErrorCode",
    "GraphQLDenied",
    "GraphQLError",
    "SilloGraphQLError",
    "bad_input",
    "conflict",
    "forbidden",
    "internal",
    "not_found",
    "too_many_requests",
    "unauthenticated",
]


class SilloGraphQLError(Exception):
    """Base for everything this package raises.

    One base means ``except SilloGraphQLError`` catches package failures
    without also swallowing the application's own exceptions.
    """


class ErrorCode:
    """The machine-readable values that appear in ``extensions.code``.

    Plain string constants rather than an ``Enum``: they are written straight
    into a JSON payload, compared against by clients as strings, and an enum
    member would only have to be unwrapped again at every boundary.
    """

    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    BAD_USER_INPUT = "BAD_USER_INPUT"
    CONFLICT = "CONFLICT"
    TOO_MANY_REQUESTS = "TOO_MANY_REQUESTS"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"
    OPERATION_TOO_COMPLEX = "OPERATION_TOO_COMPLEX"
    PERSISTED_QUERY_NOT_FOUND = "PERSISTED_QUERY_NOT_FOUND"
    PERSISTED_QUERY_NOT_SUPPORTED = "PERSISTED_QUERY_NOT_SUPPORTED"
    OPERATION_NOT_PERMITTED = "OPERATION_NOT_PERMITTED"


class GraphQLError(SilloGraphQLError):
    """An error a resolver means the client to see.

    Errors of this class are never masked: raising one is a deliberate
    statement about what went wrong, unlike a ``KeyError`` escaping a
    resolver. See :class:`sillo_graphql.policy.ErrorPolicy`.

    Args:
        message: What the client is shown.
        code: One of :class:`ErrorCode`, written to ``extensions.code``.
        extensions: Extra keys merged into the error's ``extensions``.
    """

    #: Errors raised deliberately are shown; unexpected ones are masked.
    expected = True

    def __init__(
        self,
        message: str,
        *,
        code: str = ErrorCode.INTERNAL_SERVER_ERROR,
        extensions: dict[str, typing.Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.extensions = dict(extensions or {})

    def as_extensions(self) -> dict[str, typing.Any]:
        """The ``extensions`` object for this error, code included."""
        return {"code": self.code, **self.extensions}

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.message!r}, code={self.code!r})"


class GraphQLDenied(GraphQLError):
    """Raised when a gate refuses an operation before it executes.

    Separated from :class:`GraphQLError` so a transport can answer with an
    HTTP status — 401 or 403 — instead of a 200 carrying a field error.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = ErrorCode.FORBIDDEN,
        status_code: int = 403,
        extensions: dict[str, typing.Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, extensions=extensions)
        self.status_code = status_code


def unauthenticated(
    message: str = "Not authenticated",
    **extensions: typing.Any,
) -> GraphQLDenied:
    """The caller has no identity. Answers 401."""
    return GraphQLDenied(
        message,
        code=ErrorCode.UNAUTHENTICATED,
        status_code=401,
        extensions=extensions,
    )


def forbidden(
    message: str = "Not permitted",
    **extensions: typing.Any,
) -> GraphQLDenied:
    """The caller has an identity, and it is not allowed. Answers 403."""
    return GraphQLDenied(
        message,
        code=ErrorCode.FORBIDDEN,
        status_code=403,
        extensions=extensions,
    )


def not_found(message: str = "Not found", **extensions: typing.Any) -> GraphQLError:
    """The named object does not exist, or is not visible to this caller."""
    return GraphQLError(message, code=ErrorCode.NOT_FOUND, extensions=extensions)


def bad_input(message: str, **extensions: typing.Any) -> GraphQLError:
    """The arguments parsed, and mean something the resolver cannot accept."""
    return GraphQLError(message, code=ErrorCode.BAD_USER_INPUT, extensions=extensions)
