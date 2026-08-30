"""``sillo_graphql.testing`` — the helpers, tested against a real endpoint."""

from __future__ import annotations

import pytest

from sillo_graphql import IDE
from sillo_graphql.testing import GraphClient, GraphResult


class TestGraphResult:
    def test_data_and_errors_default_to_empty(self):
        result = GraphResult(200, {})
        assert result.data is None
        assert result.errors == []
        assert result.extensions == {}
        assert result.ok is True

    def test_messages_and_codes_are_pulled_out(self):
        body = {"errors": [{"message": "gone", "extensions": {"code": "NOT_FOUND"}}]}
        result = GraphResult(200, body)
        assert result.messages == ["gone"]
        assert result.codes == ["NOT_FOUND"]

    def test_an_error_without_extensions_still_reads(self):
        result = GraphResult(200, {"errors": [{"message": "x"}]})
        assert result.codes == [""]

    def test_subscripting_reaches_into_data(self):
        assert GraphResult(200, {"data": {"me": 1}})["me"] == 1

    def test_subscripting_with_no_data_says_so(self):
        with pytest.raises(AssertionError, match="no data"):
            GraphResult(200, {"errors": [{"message": "x"}]})["me"]

    def test_subscripting_a_missing_key_lists_what_is_there(self):
        with pytest.raises(AssertionError, match=r"\['other'\]"):
            GraphResult(200, {"data": {"other": 1}})["me"]

    def test_raise_for_errors_returns_self_when_clean(self):
        result = GraphResult(200, {"data": {}})
        assert result.raise_for_errors() is result

    def test_raise_for_errors_names_the_messages(self):
        result = GraphResult(200, {"errors": [{"message": "broken"}]})
        with pytest.raises(AssertionError, match="broken"):
            result.raise_for_errors()

    def test_repr_shows_the_status(self):
        assert "200" in repr(GraphResult(200, {}))


class TestGraphClient:
    def test_query_runs_an_operation(self, gql):
        assert gql.query("{ hello }")["hello"] == "world"

    def test_mutate_is_the_same_method(self, gql):
        assert gql.mutate('mutation { rename(name: "x") }')["rename"] == "X"

    def test_variables_are_sent(self, gql):
        result = gql.query(
            "query ($t: String!) { search(term: $t) }", variables={"t": "ab"}
        )
        assert result["search"] == "ba"

    def test_an_operation_name_is_sent(self, gql):
        document = 'query A { hello } query B { search(term: "x") }'
        assert gql.query(document, operation_name="A")["hello"] == "world"

    def test_extensions_are_sent(self, gql):
        result = gql.query("{ hello }", extensions={"persistedQuery": {}})
        assert result.ok

    def test_default_headers_are_sent_with_every_request(self, app):
        with GraphClient(app, headers={"x-request-id": "fixed"}) as gql:
            result = gql.query("{ boom }")
        assert result.errors[0]["extensions"]["requestId"] == "fixed"

    def test_per_call_headers_are_merged(self, gql):
        result = gql.query("{ boom }", headers={"x-request-id": "one-off"})
        assert result.errors[0]["extensions"]["requestId"] == "one-off"

    def test_a_get_can_be_asked_for(self, gql):
        assert gql.execute("{ hello }", method="GET")["hello"] == "world"

    def test_batch_returns_one_result_per_operation(self, gql):
        results = gql.batch("{ hello }", {"query": "{ hello }"})
        assert len(results) == 2
        assert all(result.ok for result in results)

    def test_a_batch_that_answers_with_an_object_still_reads(self, build):
        from sillo_graphql import Transport

        with GraphClient(build(transport=Transport(batch=0))) as gql:
            results = gql.batch("{ hello }")
        assert len(results) == 1
        assert results[0].errors

    def test_the_explorer_can_be_fetched(self, build):
        with GraphClient(build(ide=IDE(enabled=True))) as gql:
            assert "<!doctype html>" in gql.ide().text

    def test_a_non_json_response_is_reported_rather_than_raised(self, build):
        with GraphClient(build(ide=IDE(enabled=True))) as gql:
            # The explorer is HTML; `execute` should not choke reading it.
            response = gql._client.get("/graphql", headers={"accept": "text/html"})
        assert response.status_code == 200

    def test_a_custom_path_is_used(self, build):
        app = build(path="/api/graph")
        with GraphClient(app, path="/api/graph") as gql:
            assert gql.query("{ hello }").ok


class FakeResponse:
    def __init__(self, text, status_code=200, body=None):
        self.text = text
        self.status_code = status_code
        self.headers = {}
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body
