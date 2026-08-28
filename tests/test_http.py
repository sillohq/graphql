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


class TestPost:
    def test_a_query_is_answered(self, gql):
        result = gql.query("{ hello }")
        assert result.status_code == 200
        assert result.data == {"hello": "world"}

    def test_variables_and_operation_name_are_forwarded(self, gql):
        result = gql.execute(
            "query A($t: String!) { search(term: $t) } query B { hello }",
            variables={"t": "abc"},
            operation_name="A",
        )
        assert result.data == {"search": "cba"}

    def test_a_body_that_is_not_json_is_a_400(self, gql):
        response = gql._client.post(
            "/graphql",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 400
        assert "not valid JSON" in response.json()["errors"][0]["message"]

    def test_a_body_that_is_not_an_object_is_a_400(self, gql):
        response = gql._client.post("/graphql", json="a string")
        assert response.status_code == 400

    def test_a_missing_query_is_a_400_not_a_500(self, gql):
        response = gql._client.post("/graphql", json={})
        assert response.status_code == 400
        assert response.json()["errors"][0]["extensions"]["code"] == "BAD_USER_INPUT"

    def test_an_unknown_content_type_is_a_415(self, gql):
        response = gql._client.post(
            "/graphql", content=b"x", headers={"content-type": "text/csv"}
        )
        assert response.status_code == 415

    def test_a_body_with_no_content_type_is_read_as_json(self, gql):
        response = gql._client.post(
            "/graphql", content=json.dumps({"query": "{ hello }"}).encode()
        )
        assert response.json()["data"] == {"hello": "world"}

    def test_a_graphql_body_is_the_document(self, gql):
        response = gql._client.post(
            "/graphql",
            content=b"{ hello }",
            headers={"content-type": "application/graphql"},
        )
        assert response.json()["data"] == {"hello": "world"}

    def test_graphql_bodies_can_be_refused(self, build):
        app = build(transport=Transport(graphql_content_type=False))
        with GraphClient(app) as gql:
            response = gql._client.post(
                "/graphql",
                content=b"{ hello }",
                headers={"content-type": "application/graphql"},
            )
        assert response.status_code == 415

    def test_a_form_body_is_accepted(self, gql):
        response = gql._client.post("/graphql", data={"query": "{ hello }"})
        assert response.json()["data"] == {"hello": "world"}

    def test_a_form_body_with_bad_variables_is_a_400(self, gql):
        response = gql._client.post(
            "/graphql", data={"query": "{ hello }", "variables": "{oops"}
        )
        assert response.status_code == 400

    def test_a_body_over_the_limit_is_a_413(self, build):
        with GraphClient(build(transport=Transport(max_body=64))) as gql:
            response = gql._client.post(
                "/graphql", json={"query": "{ hello }" + " " * 200}
            )
        assert response.status_code == 413

    def test_another_method_is_a_405(self, gql):
        assert gql._client.request("PUT", "/graphql").status_code == 405


class TestGet:
    def test_a_query_over_get_works(self, gql):
        assert gql.execute("{ hello }", method="GET").data == {"hello": "world"}

    def test_a_mutation_over_get_is_a_405(self, gql):
        result = gql.execute('mutation { rename(name: "x") }', method="GET")
        assert result.status_code == 405

    def test_get_queries_can_be_refused(self, build):
        with GraphClient(build(transport=Transport(get_queries=False))) as gql:
            assert gql.execute("{ hello }", method="GET").status_code == 405

    def test_a_get_with_no_query_and_no_ide_is_a_400(self, gql):
        assert gql._client.get("/graphql").status_code == 400

    def test_a_browser_gets_the_explorer_when_it_is_on(self, build):
        with GraphClient(build(ide=IDE(enabled=True))) as gql:
            response = gql.ide()
        assert response.status_code == 200
        assert "<!doctype html>" in response.text

    def test_a_browser_gets_a_400_when_the_explorer_is_off(self, gql):
        assert gql.ide().status_code == 400

    def test_a_non_browser_get_is_never_the_explorer(self, build):
        with GraphClient(build(ide=IDE(enabled=True))) as gql:
            response = gql._client.get(
                "/graphql", headers={"accept": "application/json"}
            )
        assert response.status_code == 400

    def test_variables_arrive_as_json_text(self, gql):
        result = gql.execute(
            "query ($t: String!) { search(term: $t) }",
            variables={"t": "abc"},
            method="GET",
        )
        assert result.data == {"search": "cba"}

    def test_an_extensions_only_get_is_treated_as_an_operation(self, gql):
        response = gql._client.get("/graphql", params={"extensions": "{}"})
        assert response.status_code == 400
        assert "No query" in response.json()["errors"][0]["message"]
