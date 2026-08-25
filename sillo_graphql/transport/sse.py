"""Subscriptions over ``text/event-stream``.

A WebSocket is the right transport for subscriptions and is not always
available: corporate proxies drop them, some serverless platforms do not offer
them at all, and a plain ``fetch`` with an ``EventSource`` fallback is far less
to carry in a client. Server-sent events give the same one-way stream over an
ordinary HTTP response.

The framing is the GraphQL-over-SSE specification's *distinct connections
mode*: one request opens one stream for one operation, ``next`` events carry
each result, and a ``complete`` event ends it. There is no ``connection_init``
handshake, because the request is an ordinary HTTP request and carries its own
headers — which is the other reason to reach for this transport.
"""

from __future__ import annotations

import json as jsonlib
import typing

from sillo.responses import stream

from sillo_graphql.errors import GraphQLError

if typing.TYPE_CHECKING:
    from sillo.core.http import HttpContext

    from sillo_graphql.graph import Graph

__all__ = ["MEDIA_TYPE", "SseTransport"]

MEDIA_TYPE = "text/event-stream"
