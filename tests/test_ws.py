"""``sillo_graphql.transport.ws`` — the graphql-transport-ws protocol."""

from __future__ import annotations

import json

import pytest
from sillo import SilloApp

from sillo_graphql import Graph, unauthenticated
from sillo_graphql.testing import GraphClient, StreamEnded
from sillo_graphql.transport.ws import (
    CLOSE_ALREADY_INITIALISED,
    CLOSE_BAD_MESSAGE,
    CLOSE_SUBSCRIBER_EXISTS,
    CLOSE_UNAUTHORIZED,
    PROTOCOL,
)


class Session:
    """A raw socket, for the protocol-level tests."""

    def __init__(self, client, path="/graphql"):
        self._session = client.websocket_connect(path, subprotocols=[PROTOCOL])
        self.socket = None

    def __enter__(self):
        self.socket = self._session.__enter__()
        return self

    def __exit__(self, *exc):
        self._session.__exit__(*exc)

    def send(self, **message):
        self.socket.send_text(json.dumps(message))

    def recv(self):
        return json.loads(self.socket.receive_text())

    def init(self, payload=None):
        self.send(type="connection_init", payload=payload or {})
        return self.recv()

    def subscribe(self, document, operation_id="1", **variables):
        payload = {"query": document}
        if variables:
            payload["variables"] = variables
        self.send(type="subscribe", id=operation_id, payload=payload)


@pytest.fixture
def raw(app):
    from sillo.testclient import TestClient

    with TestClient(app) as client:
        yield lambda: Session(client)
