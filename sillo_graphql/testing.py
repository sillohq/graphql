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
