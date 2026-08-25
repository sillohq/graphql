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


def _event(name: str, data: typing.Any) -> str:
    """One SSE frame.

    JSON is serialised without newlines so a payload can never be mistaken for
    the blank line that terminates an event.
    """
    body = jsonlib.dumps(data, separators=(",", ":"))
    return f"event: {name}\ndata: {body}\n\n"


class SseTransport:
    """Streams one operation over an HTTP response."""

    def __init__(self, graph: Graph, *, keepalive: float = 15.0) -> None:
        self.graph = graph
        self.keepalive = keepalive

    async def handle(
        self, ctx: HttpContext, payload: dict[str, typing.Any]
    ) -> typing.Any:
        """Answer with an event stream for *payload*."""
        return stream(
            self._events(ctx, payload),
            content_type=MEDIA_TYPE,
            headers={
                "cache-control": "no-cache, no-transform",
                # Proxies that buffer a response defeat the point of streaming
                # it; nginx reads this one.
                "x-accel-buffering": "no",
                "connection": "keep-alive",
            },
        )

    async def _events(
        self, ctx: HttpContext, payload: dict[str, typing.Any]
    ) -> typing.AsyncIterator[str]:
        try:
            async for result in self.graph.stream(payload, http=ctx):
                yield _event("next", result.body())
        except GraphQLError as error:
            # An error before or during execution is still delivered on the
            # stream: the response headers went out with the first byte, so
            # there is no status code left to change.
            yield _event(
                "next",
                {
                    "errors": [
                        {"message": error.message, "extensions": error.as_extensions()}
                    ]
                },
            )
        yield _event("complete", {})
