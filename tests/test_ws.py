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


class TestHandshake:
    def test_init_is_acknowledged(self, raw):
        with raw() as session:
            assert session.init()["type"] == "connection_ack"

    def test_a_second_init_closes_the_connection(self, raw):
        with pytest.raises(Exception), raw() as session:
            session.init()
            session.init()
            session.recv()

    def test_subscribing_before_init_is_refused(self, raw):
        with pytest.raises(Exception), raw() as session:
            session.subscribe("subscription { ticks }")
            session.recv()

    def test_an_unparseable_message_closes_the_connection(self, raw):
        with pytest.raises(Exception), raw() as session:
            session.socket.send_text("not json")
            session.recv()

    def test_a_message_that_is_not_an_object_closes_it(self, raw):
        with pytest.raises(Exception), raw() as session:
            session.socket.send_text("[1, 2]")
            session.recv()

    def test_an_unknown_message_type_closes_it(self, raw):
        with pytest.raises(Exception), raw() as session:
            session.init()
            session.send(type="nonsense")
            session.recv()
