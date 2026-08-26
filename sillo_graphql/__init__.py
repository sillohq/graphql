"""Production GraphQL for Sillo.

Installs as ``sillo-graphql`` and imports either way::

    from sillo.graphql import Graph, field    # reads as part of the framework
    from sillo_graphql import Graph, field    # where the code actually is

Strawberry owns the schema. This package owns everything around it: the
transports, the safety, and the observability.

    from sillo import Depend, HttpContext, SilloApp
    from sillo.graphql import Graph, Limits, field

    @strawberry.type
    class Query:
        @field
        async def me(ctx: HttpContext, db=Depend(get_db)) -> User:
            return await db.users.get(ctx.user.id)

    app = SilloApp()
    Graph(strawberry.Schema(query=Query), limits=Limits(depth=8)).mount(app)

``ctx`` and anything defaulted to ``Depend`` are injected and never appear in
the schema; every other parameter is a GraphQL argument.
"""

from sillo_graphql.context import GraphContext, ResponseHandle, current_context
from sillo_graphql.errors import (
    ErrorCode,
    GraphQLDenied,
    GraphQLError,
    SilloGraphQLError,
    bad_input,
    conflict,
    forbidden,
    internal,
    not_found,
    too_many_requests,
    unauthenticated,
)
from sillo_graphql.graph import Graph, Result
from sillo_graphql.limits import Analysis, analyze
from sillo_graphql.loaders import Loader, LoaderError, LoaderRegistry, loader
from sillo_graphql.persisted import (
    MemoryStore,
    PersistedStore,
    TrustedDocuments,
    hash_document,
)
from sillo_graphql.policy import (
    IDE,
    ErrorPolicy,
    Limits,
    Persisted,
    Transport,
    Uploads,
)
from sillo_graphql.resolvers import ResolverError, field, mutation, subscription
from sillo_graphql.tracing import Metrics, OperationLog

__version__ = "0.1.0"

__all__ = [
    "IDE",
    "Analysis",
    "ErrorCode",
    "ErrorPolicy",
    "Graph",
    "GraphContext",
    "GraphQLDenied",
    "GraphQLError",
    "Limits",
    "Loader",
    "LoaderError",
    "LoaderRegistry",
    "MemoryStore",
    "Metrics",
    "OperationLog",
    "Persisted",
    "PersistedStore",
    "ResolverError",
    "ResponseHandle",
    "Result",
    "SilloGraphQLError",
    "Transport",
    "TrustedDocuments",
    "Uploads",
    "__version__",
    "analyze",
    "bad_input",
    "conflict",
    "current_context",
    "field",
    "forbidden",
    "hash_document",
    "internal",
    "loader",
    "mutation",
    "not_found",
    "subscription",
    "too_many_requests",
    "unauthenticated",
]
