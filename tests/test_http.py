"""``sillo_graphql.transport.http`` — framing, negotiation and status codes."""

from __future__ import annotations

import json

import pytest

from sillo_graphql import IDE, Transport, Uploads
from sillo_graphql.testing import GraphClient
from sillo_graphql.transport.http import (
    APPLICATION_JSON,
    GRAPHQL_RESPONSE_JSON,
    negotiate,
)

SPEC = {"accept": GRAPHQL_RESPONSE_JSON}


class TestNegotiation:
    @pytest.mark.parametrize(
        ("accept", "expected"),
        [
            (None, APPLICATION_JSON),
            ("", APPLICATION_JSON),
            ("*/*", APPLICATION_JSON),
            ("application/json", APPLICATION_JSON),
            ("text/html", APPLICATION_JSON),
            (GRAPHQL_RESPONSE_JSON, GRAPHQL_RESPONSE_JSON),
            (f"{GRAPHQL_RESPONSE_JSON};charset=utf-8", GRAPHQL_RESPONSE_JSON),
            (f"{GRAPHQL_RESPONSE_JSON}, application/json", GRAPHQL_RESPONSE_JSON),
            (f"application/json, {GRAPHQL_RESPONSE_JSON}", APPLICATION_JSON),
        ],
    )
    def test_the_legacy_type_wins_ties_and_defaults(self, accept, expected):
        assert negotiate(accept, enabled=True) == expected

    def test_it_can_be_switched_off_entirely(self):
        assert negotiate(GRAPHQL_RESPONSE_JSON, enabled=False) == APPLICATION_JSON
