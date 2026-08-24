"""Resolvers that read like ``sillo`` handlers.

A route handler in ``sillo`` takes the context first and declares whatever else
it needs::

    @app.get("/me")
    async def me(ctx: HttpContext, db=Depend(get_db)):
        ...

A resolver here is the same thing::

    @strawberry.type
    class Query:
        @field
        async def me(ctx: HttpContext, db=Depend(get_db)) -> User:
            ...

The rule is one sentence: **``ctx`` and anything defaulted to ``Depend`` are
injected and do not appear in the schema; every other parameter is a GraphQL
argument.**

Strawberry derives a field's arguments from its resolver's signature, so the
injected parameters have to be gone by the time it looks. The decorator builds
a wrapper carrying a synthesized ``__signature__`` with only the exposed
arguments, plus ``root`` and ``info`` — which Strawberry recognises and keeps
out of the schema — and fills the rest in at call time. That is the same trick
``sillo``'s own router plays when it inspects a handler before dispatch.
"""

from __future__ import annotations

import functools
import inspect
import typing

import strawberry

from sillo_graphql.errors import ErrorCode, GraphQLDenied, SilloGraphQLError

if typing.TYPE_CHECKING:
    from sillo_graphql.context import GraphContext

__all__ = ["ResolverError", "field", "mutation", "resolver_costs", "subscription"]

#: Parameter names Strawberry already treats as the parent object.
ROOT_NAMES = frozenset({"root", "self", "parent"})

#: Annotations that mean "the connection's own context". Compared as strings
#: because ``from __future__ import annotations`` makes every annotation one,
#: and because importing them here would drag the framework into this module.
CONTEXT_ANNOTATIONS = frozenset(
    {
        "HttpContext",
        "WebSocketContext",
        "BaseContext",
        "Context",
    }
)

#: Annotations that mean the whole :class:`~sillo_graphql.context.GraphContext`.
GRAPH_CONTEXT_ANNOTATIONS = frozenset({"GraphContext"})

#: Parameter names that mean the context when nothing is annotated.
CONTEXT_NAMES = frozenset({"ctx", "context"})

#: Per-field costs registered by ``@field(cost=...)``, keyed by field name.
#: Read by :class:`~sillo_graphql.graph.Graph` when it builds its cost table.
_COSTS: dict[str, int] = {}


class ResolverError(SilloGraphQLError):
    """A resolver could not be adapted."""
