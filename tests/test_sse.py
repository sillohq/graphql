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


class TestFraming:
    def test_an_event_is_named_and_carries_json(self):
        assert _event("next", {"a": 1}) == 'event: next\ndata: {"a":1}\n\n'

    def test_json_is_written_without_newlines(self):
        # A newline inside the payload would end the event early.
        frame = _event("next", {"a": "x\ny"})
        assert frame.count("\n\n") == 1
