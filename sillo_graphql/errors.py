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
