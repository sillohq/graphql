"""Type stubs for ``sillo.graphql``.

The runtime alias is installed by ``_sillo_graphql_bootstrap`` via a ``.pth``,
and a type checker never runs import hooks — so without this file
``from sillo.graphql import Graph`` type-checks as a missing module even though
it imports fine.

``py.typed`` next to this file contains the word ``partial`` (PEP 561), which
is what keeps these stubs additive: a checker uses them for ``sillo.graphql``
and falls back to the framework's own inline types for the rest of ``sillo``.
Without it, this directory would claim to describe all of ``sillo`` and hide
the types the framework ships.

Nothing is declared here. Everything is re-exported from ``sillo_graphql``,
whose inline annotations are the single source of truth.
"""

from sillo_graphql import Analysis as Analysis
from sillo_graphql import ErrorCode as ErrorCode
from sillo_graphql import ErrorPolicy as ErrorPolicy
from sillo_graphql import Graph as Graph
from sillo_graphql import GraphContext as GraphContext
from sillo_graphql import GraphQLDenied as GraphQLDenied
from sillo_graphql import GraphQLError as GraphQLError
from sillo_graphql import IDE as IDE
from sillo_graphql import Limits as Limits
from sillo_graphql import Loader as Loader
from sillo_graphql import LoaderError as LoaderError
from sillo_graphql import LoaderRegistry as LoaderRegistry
from sillo_graphql import MemoryStore as MemoryStore
from sillo_graphql import Metrics as Metrics
from sillo_graphql import OperationLog as OperationLog
from sillo_graphql import Persisted as Persisted
from sillo_graphql import PersistedStore as PersistedStore
from sillo_graphql import ResolverError as ResolverError
from sillo_graphql import ResponseHandle as ResponseHandle
from sillo_graphql import Result as Result
from sillo_graphql import SilloGraphQLError as SilloGraphQLError
from sillo_graphql import Transport as Transport
from sillo_graphql import TrustedDocuments as TrustedDocuments
from sillo_graphql import Uploads as Uploads
from sillo_graphql import analyze as analyze
from sillo_graphql import bad_input as bad_input
from sillo_graphql import conflict as conflict
from sillo_graphql import current_context as current_context
from sillo_graphql import field as field
from sillo_graphql import forbidden as forbidden
from sillo_graphql import hash_document as hash_document
from sillo_graphql import internal as internal
from sillo_graphql import loader as loader
from sillo_graphql import mutation as mutation
from sillo_graphql import not_found as not_found
from sillo_graphql import subscription as subscription
from sillo_graphql import too_many_requests as too_many_requests
from sillo_graphql import unauthenticated as unauthenticated

__version__: str

__all__ = [
    "Analysis",
    "ErrorCode",
    "ErrorPolicy",
    "Graph",
    "GraphContext",
    "GraphQLDenied",
    "GraphQLError",
    "IDE",
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
