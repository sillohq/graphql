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


class TestPing:
    def test_a_ping_is_answered_with_a_pong(self, raw):
        with raw() as session:
            session.init()
            session.send(type="ping", payload={"n": 1})
            answer = session.recv()
        assert answer == {"type": "pong", "payload": {"n": 1}}

    def test_an_unsolicited_pong_is_accepted(self, raw):
        with raw() as session:
            session.init()
            session.send(type="pong")
            session.send(type="ping")
            assert session.recv()["type"] == "pong"


class TestSubscribe:
    def test_values_arrive_as_next_and_end_with_complete(self, raw):
        with raw() as session:
            session.init()
            session.subscribe("subscription { ticks(count: 2) }")
            first, second, done = session.recv(), session.recv(), session.recv()
        assert first["payload"]["data"] == {"ticks": 0}
        assert second["payload"]["data"] == {"ticks": 1}
        assert done == {"type": "complete", "id": "1"}

    def test_an_id_already_in_use_closes_the_connection(self, raw):
        with pytest.raises(Exception), raw() as session:
            session.init()
            session.subscribe("subscription { ticks(count: 100) }")
            session.subscribe("subscription { ticks(count: 100) }")
            for _ in range(5):
                session.recv()

    def test_a_non_string_id_closes_the_connection(self, raw):
        with pytest.raises(Exception), raw() as session:
            session.init()
            session.send(type="subscribe", id=7, payload={"query": "{ hello }"})
            session.recv()

    def test_a_missing_payload_closes_the_connection(self, raw):
        with pytest.raises(Exception), raw() as session:
            session.init()
            session.send(type="subscribe", id="1")
            session.recv()

    def test_a_query_over_the_socket_answers_once(self, raw):
        with raw() as session:
            session.init()
            session.subscribe("{ hello }")
            first, done = session.recv(), session.recv()
        assert first["payload"]["data"] == {"hello": "world"}
        assert done["type"] == "complete"

    def test_a_refused_operation_arrives_as_an_error(self, raw):
        with raw() as session:
            session.init()
            session.subscribe("{ __schema { types { name } } }")
            message = session.recv()
        assert message["type"] == "error"
        assert message["payload"][0]["extensions"]["code"] == "OPERATION_NOT_PERMITTED"

    def test_a_failing_subscription_reports_the_error(self, raw):
        with raw() as session:
            session.init()
            session.subscribe("subscription { failing }")
            first = session.recv()
            second = session.recv()
        assert first["payload"]["data"] == {"failing": 1}
        assert second["payload"]["errors"]

    def test_completing_stops_the_stream(self, raw):
        with raw() as session:
            session.init()
            session.subscribe("subscription { ticks(count: 100) }")
            session.recv()
            session.send(type="complete", id="1")
            session.send(type="ping")
            # The ping is answered, so the connection survived the cancel.
            while True:
                message = session.recv()
                if message["type"] == "pong":
                    break

    def test_completing_an_unknown_id_is_harmless(self, raw):
        with raw() as session:
            session.init()
            session.send(type="complete", id="never-started")
            session.send(type="ping")
            assert session.recv()["type"] == "pong"


class TestConnectHook:
    def test_a_hook_can_refuse_the_connection(self, schema):
        app = SilloApp(debug=False)
        graph = Graph(schema)

        @graph.on_connect
        async def authenticate(socket, params):
            if params.get("token") != "good":
                raise unauthenticated("bad token")
            return {}

        graph.mount(app)

        from sillo.testclient import TestClient

        with (
            TestClient(app) as client,
            pytest.raises(Exception),
            Session(client) as session,
        ):
            session.init({"token": "bad"})
            session.recv()

    def test_a_hook_can_admit_the_connection(self, schema):
        app = SilloApp(debug=False)
        graph = Graph(schema)

        @graph.on_connect
        async def authenticate(socket, params):
            return {"user": params.get("token")}

        graph.mount(app)

        from sillo.testclient import TestClient

        with TestClient(app) as client, Session(client) as session:
            assert session.init({"token": "good"})["type"] == "connection_ack"


class TestHelperStream:
    async def test_it_handshakes_and_reads(self, app):
        with GraphClient(app) as gql:
            async with gql.subscribe("subscription { ticks(count: 2) }") as stream:
                results = await stream.collect(2)
        assert [result.data for result in results] == [
            {"ticks": 0},
            {"ticks": 1},
        ]

    async def test_running_past_the_end_is_a_clear_failure(self, app):
        with GraphClient(app) as gql:
            async with gql.subscribe("subscription { ticks(count: 1) }") as stream:
                await stream.next()
                with pytest.raises(StreamEnded):
                    await stream.next()

    async def test_variables_can_be_passed_as_keywords(self, app):
        with GraphClient(app) as gql:
            document = "subscription ($n: Int!) { ticks(count: $n) }"
            async with gql.subscribe(document, n=1) as stream:
                assert (await stream.next()).data == {"ticks": 0}

    async def test_an_error_message_becomes_a_result(self, app):
        with GraphClient(app) as gql:
            async with gql.subscribe("{ __schema { types { name } } }") as stream:
                result = await stream.next()
        assert result.codes == ["OPERATION_NOT_PERMITTED"]

    async def test_completing_early_is_allowed(self, app):
        with GraphClient(app) as gql:
            async with gql.subscribe("subscription { ticks(count: 50) }") as stream:
                await stream.next()
                await stream.complete()


class TestCloseCodes:
    def test_they_are_the_protocol_s_own(self):
        assert CLOSE_BAD_MESSAGE == 4400
        assert CLOSE_UNAUTHORIZED == 4401
        assert CLOSE_ALREADY_INITIALISED == 4429
        assert CLOSE_SUBSCRIBER_EXISTS == 4409


class FakeSocket:
    """A socket for the paths a real client cannot drive."""

    def __init__(self, incoming=(), *, fail_send=False, hang=False):
        self.incoming = list(incoming)
        self.fail_send = fail_send
        self.hang = hang
        self.sent = []
        self.closed = None
        self.accepted = None

    async def accept(self, subprotocol=None):
        self.accepted = subprotocol

    async def receive_text(self):
        if self.hang:
            import asyncio

            await asyncio.sleep(3600)
        if not self.incoming:
            raise RuntimeError("client gone")
        return self.incoming.pop(0)

    async def send_text(self, text):
        if self.fail_send:
            raise RuntimeError("socket closed")
        self.sent.append(json.loads(text))

    async def close(self, code=1000, reason=None):
        self.closed = (code, reason)
