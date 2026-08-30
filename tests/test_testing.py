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
