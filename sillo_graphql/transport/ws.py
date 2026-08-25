"""Subscriptions over ``graphql-transport-ws``.

The protocol in one paragraph: the client connects with the subprotocol
``graphql-transport-ws``, sends ``connection_init`` and waits for
``connection_ack``; then each operation is a ``subscribe`` carrying an id, the
server answers with ``next`` messages and ends with ``complete`` or ``error``;
either side may ``ping`` and must answer ``pong``; the client can ``complete``
an operation to unsubscribe.

Three rules do most of the work of keeping it well behaved:

* a connection that never sends ``connection_init`` is closed after
  ``init_timeout`` seconds, so an idle socket cannot be held open for free;
* an id already in use is a protocol error and closes the connection, because
  the alternative is two operations racing over one channel;
* every operation is cancelled when its socket closes, in a ``finally`` — a
  subscription that outlives its client is a leak that compounds.

``connection_init``'s payload is where authentication belongs. There are no
headers on a browser WebSocket handshake, so a token arrives here, and the
``@graph.on_connect`` hook is given it before any operation runs.
"""

from __future__ import annotations

import asyncio
import contextlib
import json as jsonlib
import typing

from sillo_graphql.errors import GraphQLDenied, GraphQLError

if typing.TYPE_CHECKING:
    from sillo.websockets import WebSocketContext

    from sillo_graphql.graph import Graph

__all__ = ["PROTOCOL", "WebSocketTransport"]

#: The subprotocol this transport speaks.
PROTOCOL = "graphql-transport-ws"

#: The older protocol, named here only so a client asking for it is told
#: plainly rather than left waiting for messages that never come.
LEGACY_PROTOCOL = "graphql-ws"

# Close codes from the protocol.
CLOSE_BAD_MESSAGE = 4400
CLOSE_UNAUTHORIZED = 4401
CLOSE_INIT_TIMEOUT = 4408
CLOSE_ALREADY_INITIALISED = 4429
CLOSE_SUBSCRIBER_EXISTS = 4409
