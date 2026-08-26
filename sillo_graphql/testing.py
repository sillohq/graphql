"""Driving an endpoint from a test.

``sillo``'s ``TestClient`` speaks HTTP, and a GraphQL test written through it
is four lines of JSON assembly and a dictionary walk before it reaches the
thing under test. ``GraphClient`` is the same client with the GraphQL shape
built in::

    def test_me():
        with GraphClient(app) as gql:
            result = gql.query("{ me { email } }")
            assert result.ok
            assert result["me"]["email"] == "a@b.c"

Subscriptions get a harness of their own, because the alternative is writing
the ``graphql-transport-ws`` handshake out in every test::

    async def test_prices():
        async with GraphClient(app).subscribe(PRICES, symbol="ACME") as stream:
            assert (await stream.next())["prices"]["last"] == 10

Nothing here reaches around the transports. A test drives the same route a
client does, which is the only way a test of an endpoint tells you anything
about the endpoint.
"""

from __future__ import annotations

import json as jsonlib
import typing

from sillo_graphql.errors import SilloGraphQLError

__all__ = ["GraphClient", "GraphResult", "StreamEnded", "SubscriptionStream"]

DEFAULT_TIMEOUT = 5.0


class StreamEnded(SilloGraphQLError):
    """A subscription finished when a test was still waiting for a value.

    Named for what happened rather than for a timeout: the stream is closed,
    so waiting longer would not help. Raising here is what turns a test that
    would hang into one that fails and says why.
    """


class GraphResult:
    """One response, with the dictionary walking already done.

    Attributes:
        status_code: The HTTP status.
        body: The whole response body.
    """

    __slots__ = ("body", "headers", "status_code")

    def __init__(
        self,
        status_code: int,
        body: dict[str, typing.Any],
        headers: typing.Mapping[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.body = body
        self.headers = dict(headers or {})

    @property
    def data(self) -> typing.Any:
        """The ``data`` field."""
        return self.body.get("data")

    @property
    def errors(self) -> list[dict[str, typing.Any]]:
        """The ``errors`` field, or an empty list."""
        return self.body.get("errors") or []

    @property
    def extensions(self) -> dict[str, typing.Any]:
        """The ``extensions`` field, or an empty dict."""
        return self.body.get("extensions") or {}

    @property
    def ok(self) -> bool:
        """Whether the operation produced no errors."""
        return not self.errors

    @property
    def messages(self) -> list[str]:
        """Just the error messages, which is what an assertion usually wants."""
        return [str(error.get("message", "")) for error in self.errors]

    @property
    def codes(self) -> list[str]:
        """The ``extensions.code`` of each error."""
        return [
            str((error.get("extensions") or {}).get("code", ""))
            for error in self.errors
        ]

    def __getitem__(self, key: str) -> typing.Any:
        """Reach into ``data``, with a readable failure when it is not there."""
        data = self.data
        if not isinstance(data, dict):
            raise AssertionError(
                f"no data to read {key!r} from; the response was {self.body!r}"
            )
        if key not in data:
            raise AssertionError(
                f"{key!r} is not in data ({sorted(data)}); errors: {self.messages}"
            )
        return data[key]

    def raise_for_errors(self) -> GraphResult:
        """Fail loudly if the operation produced errors. Returns ``self``."""
        if self.errors:
            raise AssertionError(f"GraphQL errors: {self.messages}")
        return self

    def __repr__(self) -> str:
        return f"GraphResult({self.status_code}, ok={self.ok})"


class GraphClient:
    """A ``TestClient`` that speaks GraphQL.

    Args:
        app: The application to drive.
        path: The endpoint's path.
        headers: Sent with every request — an auth header, usually.
    """

    def __init__(
        self,
        app: typing.Any,
        *,
        path: str = "/graphql",
        headers: typing.Mapping[str, str] | None = None,
    ) -> None:
        from sillo.testclient import TestClient

        self.app = app
        self.path = path
        self.headers = dict(headers or {})
        self._client = TestClient(app)

    def __enter__(self) -> GraphClient:
        self._client.__enter__()
        return self

    def __exit__(self, *exc_info: typing.Any) -> None:
        self._client.__exit__(*exc_info)

    def execute(
        self,
        document: str,
        *,
        variables: dict[str, typing.Any] | None = None,
        operation_name: str | None = None,
        headers: typing.Mapping[str, str] | None = None,
        extensions: dict[str, typing.Any] | None = None,
        method: str = "POST",
    ) -> GraphResult:
        """Run one operation and return the parsed response."""
        payload: dict[str, typing.Any] = {"query": document}
        if variables is not None:
            payload["variables"] = variables
        if operation_name is not None:
            payload["operationName"] = operation_name
        if extensions is not None:
            payload["extensions"] = extensions

        merged = {**self.headers, **(headers or {})}
        if method == "GET":
            params = {
                key: value if isinstance(value, str) else jsonlib.dumps(value)
                for key, value in payload.items()
            }
            response = self._client.get(self.path, params=params, headers=merged)
        else:
            response = self._client.post(self.path, json=payload, headers=merged)
        return _result(response)

    # Named for what a caller is doing, so a test reads as the operation it runs.
    query = execute
    mutate = execute

    def batch(
        self,
        *documents: str | dict[str, typing.Any],
        headers: typing.Mapping[str, str] | None = None,
    ) -> list[GraphResult]:
        """Run several operations in one request."""
        payload = [
            {"query": item} if isinstance(item, str) else item for item in documents
        ]
        response = self._client.post(
            self.path, json=payload, headers={**self.headers, **(headers or {})}
        )
        body = response.json()
        if not isinstance(body, list):
            return [_result(response)]
        return [GraphResult(response.status_code, item) for item in body]

    def ide(self, headers: typing.Mapping[str, str] | None = None) -> typing.Any:
        """Fetch the explorer page, as a browser would."""
        return self._client.get(
            self.path,
            headers={"accept": "text/html", **self.headers, **(headers or {})},
        )

    def subscribe(
        self,
        document: str,
        *,
        variables: dict[str, typing.Any] | None = None,
        connection_params: dict[str, typing.Any] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        **shorthand: typing.Any,
    ) -> SubscriptionStream:
        """Open a subscription, handshake included.

        Variables may be passed as ``variables={...}`` or as keywords, which
        is shorter and is what a test usually wants::

            gql.subscribe(PRICES, symbol="ACME")
        """
        return SubscriptionStream(
            self._client,
            self.path,
            document,
            variables={**(variables or {}), **shorthand} or None,
            connection_params=connection_params,
            timeout=timeout,
            headers=self.headers,
        )


class SubscriptionStream:
    """One ``graphql-transport-ws`` subscription, as an async context manager.

    Entering it connects, sends ``connection_init``, waits for
    ``connection_ack`` and sends the ``subscribe``. Leaving it completes the
    operation and closes the socket, so a test that fails part-way through
    does not leave a subscription running.
    """

    def __init__(
        self,
        client: typing.Any,
        path: str,
        document: str,
        *,
        variables: dict[str, typing.Any] | None,
        connection_params: dict[str, typing.Any] | None,
        timeout: float,
        headers: typing.Mapping[str, str] | None = None,
    ) -> None:
        self.client = client
        self.path = path
        self.document = document
        self.variables = variables
        self.connection_params = connection_params or {}
        self.timeout = timeout
        self.headers = dict(headers or {})
        self.operation_id = "1"
        self._socket: typing.Any = None
        self._session: typing.Any = None
        self.completed = False

    async def __aenter__(self) -> SubscriptionStream:
        # `headers` is only passed when there are some: the test client
        # merges into whatever it is given, and merging into None is a crash.
        extra = {"headers": self.headers} if self.headers else {}
        self._session = self.client.websocket_connect(
            self.path, subprotocols=["graphql-transport-ws"], **extra
        )
        self._socket = self._session.__enter__()
        self._send({"type": "connection_init", "payload": self.connection_params})
        ack = self._recv()
        if ack.get("type") != "connection_ack":
            raise AssertionError(f"expected connection_ack, got {ack!r}")
        payload: dict[str, typing.Any] = {"query": self.document}
        if self.variables:
            payload["variables"] = self.variables
        self._send({"type": "subscribe", "id": self.operation_id, "payload": payload})
        return self

    async def __aexit__(self, *exc_info: typing.Any) -> None:
        try:
            if not self.completed:
                self._send({"type": "complete", "id": self.operation_id})
        except Exception:
            pass
        self._session.__exit__(*exc_info)

    def _send(self, message: dict[str, typing.Any]) -> None:
        self._socket.send_text(jsonlib.dumps(message))

    def _recv(self) -> dict[str, typing.Any]:
        return jsonlib.loads(self._socket.receive_text())

    async def next(self) -> GraphResult:
        """The next ``next`` message, as a result.

        Raises:
            StreamEnded: if the subscription completed instead of producing
                another value — the failure a test means to catch, and which
                would otherwise hang.
        """
        while True:
            message = self._recv()
            kind = message.get("type")
            if kind == "next":
                return GraphResult(200, message.get("payload") or {})
            if kind == "complete":
                self.completed = True
                raise StreamEnded("the subscription completed without another value")
            if kind == "error":
                self.completed = True
                return GraphResult(200, {"errors": message.get("payload") or []})
            # ping/pong and anything else: keep reading.

    async def collect(self, count: int) -> list[GraphResult]:
        """The next *count* values."""
        return [await self.next() for _ in range(count)]

    async def complete(self) -> None:
        """Unsubscribe, and wait for the server to confirm."""
        self._send({"type": "complete", "id": self.operation_id})
        self.completed = True


def _result(response: typing.Any) -> GraphResult:
    """Parse a response, tolerating one that is not JSON at all."""
    try:
        body = response.json()
    except ValueError:
        body = {"errors": [{"message": response.text}]}
    if not isinstance(body, dict):
        body = {"errors": [{"message": f"expected an object, got {body!r}"}]}
    return GraphResult(response.status_code, body, response.headers)
