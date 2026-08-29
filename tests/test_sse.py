"""``sillo_graphql.transport.sse`` — subscriptions over an HTTP response."""

from __future__ import annotations

import json

import pytest
from sillo import SilloApp

from sillo_graphql import Graph
from sillo_graphql.transport.sse import MEDIA_TYPE, SseTransport, _event


def parse_events(text: str) -> list[tuple[str, dict]]:
    """Read an SSE body into (event, data) pairs."""
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            events.append((lines["event"], json.loads(lines["data"])))
    return events


@pytest.fixture
def sse_app(schema):
    """An app exposing the SSE transport on its own path."""
    app = SilloApp(debug=False)
    graph = Graph(schema)
    graph.mount(app)
    events = SseTransport(graph)

    @app.post("/stream")
    async def stream(ctx):
        return await events.handle(ctx, await ctx.json)

    return app
