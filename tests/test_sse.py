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


class TestStreaming:
    def test_a_subscription_arrives_as_next_events(self, sse_app):
        from sillo.testclient import TestClient

        with TestClient(sse_app) as client:
            response = client.post(
                "/stream", json={"query": "subscription { ticks(count: 2) }"}
            )

        assert response.headers["content-type"].startswith(MEDIA_TYPE)
        events = parse_events(response.text)
        assert [name for name, _ in events] == ["next", "next", "complete"]
        assert events[0][1]["data"] == {"ticks": 0}

    def test_a_query_arrives_as_a_single_event(self, sse_app):
        from sillo.testclient import TestClient

        with TestClient(sse_app) as client:
            response = client.post("/stream", json={"query": "{ hello }"})

        events = parse_events(response.text)
        assert [name for name, _ in events] == ["next", "complete"]
        assert events[0][1]["data"] == {"hello": "world"}

    def test_a_refusal_is_delivered_on_the_stream(self, sse_app):
        from sillo.testclient import TestClient

        with TestClient(sse_app) as client:
            response = client.post(
                "/stream", json={"query": "{ __schema { types { name } } }"}
            )

        events = parse_events(response.text)
        assert events[0][1]["errors"][0]["extensions"]["code"] == (
            "OPERATION_NOT_PERMITTED"
        )
        assert events[-1][0] == "complete"

    def test_buffering_proxies_are_told_not_to(self, sse_app):
        from sillo.testclient import TestClient

        with TestClient(sse_app) as client:
            response = client.post("/stream", json={"query": "{ hello }"})

        assert response.headers["cache-control"].startswith("no-cache")
        assert response.headers["x-accel-buffering"] == "no"
