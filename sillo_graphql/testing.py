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
