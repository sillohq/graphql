"""How an operation reaches the schema.

Three transports, sharing one execution pipeline on
:class:`~sillo_graphql.graph.Graph`:

- :mod:`~sillo_graphql.transport.http` — GraphQL over HTTP, the spec's status
  codes and content negotiation included.
- :mod:`~sillo_graphql.transport.ws` — ``graphql-transport-ws``, for
  subscriptions.
- :mod:`~sillo_graphql.transport.sse` — the same subscriptions over
  ``text/event-stream``, for clients that cannot hold a socket open.

Each one parses, frames and answers. None of them decides what is allowed:
limits, persisted documents, context building and error policy all live on the
``Graph``, so the three cannot drift apart on the questions that matter.
"""

from sillo_graphql.transport.http import HttpTransport
from sillo_graphql.transport.sse import SseTransport
from sillo_graphql.transport.ws import WebSocketTransport

__all__ = ["HttpTransport", "SseTransport", "WebSocketTransport"]
