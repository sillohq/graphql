"""The endpoint: configuration, mounting, and one execution pipeline.

``Graph`` is built and then mounted, which is how every other ``sillo``
subsystem is put together — ``AdminSite(...)`` then ``admin.mount(app)``. The
previous integration took the application in its constructor and registered a
route as a side effect of ``__init__``, which is why it read as foreign::

    graph = Graph(schema, ide=True)
    graph.mount(app)

Everything a request passes through lives here rather than in a transport:
persisted-document resolution, the introspection guard, cost analysis, context
building and error policy. The three transports frame and answer; they do not
decide. That is what keeps a query over ``GET`` subject to the same limits as
one over a WebSocket.
"""

from __future__ import annotations

import dataclasses
import inspect
import logging
import traceback
import typing

from graphql import parse
from graphql.error import GraphQLSyntaxError
from graphql.language import (
    DocumentNode,
    FieldNode,
    OperationDefinitionNode,
    OperationType,
)

from sillo_graphql import ide as ide_module
from sillo_graphql.context import GraphContext, current_context
from sillo_graphql.errors import ErrorCode, GraphQLDenied, GraphQLError
from sillo_graphql.limits import Analysis, enforce
from sillo_graphql.loaders import loader as make_loader
from sillo_graphql.persisted import (
    MemoryStore,
    PersistedStore,
    TrustedDocuments,
    resolve_document,
)
from sillo_graphql.policy import (
    IDE,
    ErrorPolicy,
    Limits,
    Persisted,
    Transport,
    Uploads,
)
from sillo_graphql.resolvers import resolver_costs
from sillo_graphql.transport.http import HttpTransport
from sillo_graphql.transport.sse import SseTransport
from sillo_graphql.transport.ws import WebSocketTransport

if typing.TYPE_CHECKING:
    import strawberry

__all__ = ["Graph", "Result"]

LOGGER = logging.getLogger("sillo.graphql")

#: Meta-fields that expose the schema. ``__typename`` is not one of them: it
#: answers about the object in hand, not about the schema, and clients need it.
INTROSPECTION_FIELDS = frozenset({"__schema", "__type"})


@dataclasses.dataclass(frozen=True, slots=True)
class _Prepared:
    """A document that has passed every gate and is ready to execute."""

    source: str
    document: DocumentNode
    variables: dict[str, typing.Any] | None
    operation_name: str | None
    analysis: Analysis


@dataclasses.dataclass(slots=True)
class Result:
    """One operation's answer, before a transport frames it.

    Attributes:
        data: The ``data`` field, or ``None`` when execution did not begin.
        errors: Already-formatted error objects.
        extensions: Merged extensions, cost included when it was measured.
        status_code: What the spec's media type should answer with. Ignored
            under the legacy ``application/json``, which is always 200.
        response: What resolvers asked to do to the response, if anything.
    """

    data: typing.Any = None
    errors: list[dict[str, typing.Any]] = dataclasses.field(default_factory=list)
    extensions: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    status_code: int = 200
    response: typing.Any = None

    def body(self) -> dict[str, typing.Any]:
        """The JSON object to send.

        ``data`` is present whenever execution began — including as ``null``,
        which is how a client tells a failed operation from one that was never
        run at all.
        """
        body: dict[str, typing.Any] = {}
        if self.errors:
            body["errors"] = self.errors
        if self.data is not None or not self.errors:
            body["data"] = self.data
        if self.extensions:
            body["extensions"] = self.extensions
        return body

    @property
    def ok(self) -> bool:
        """Whether the operation produced no errors."""
        return not self.errors
