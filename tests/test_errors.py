"""``sillo_graphql.errors`` — the builders and the codes they carry."""

from __future__ import annotations

import pytest

from sillo_graphql.errors import (
    ErrorCode,
    GraphQLDenied,
    GraphQLError,
    SilloGraphQLError,
    bad_input,
    conflict,
    forbidden,
    internal,
    not_found,
    too_many_requests,
    unauthenticated,
)


class TestGraphQLError:
    def test_carries_its_message_and_code(self):
        error = GraphQLError("nope", code=ErrorCode.CONFLICT)
        assert str(error) == "nope"
        assert error.message == "nope"
        assert error.as_extensions() == {"code": "CONFLICT"}

    def test_extra_extensions_are_merged_under_the_code(self):
        error = GraphQLError("nope", code="X", extensions={"field": "email"})
        assert error.as_extensions() == {"code": "X", "field": "email"}

    def test_defaults_to_an_internal_code(self):
        assert GraphQLError("x").code == ErrorCode.INTERNAL_SERVER_ERROR

    def test_is_catchable_as_the_package_base(self):
        with pytest.raises(SilloGraphQLError):
            raise GraphQLError("x")

    def test_repr_names_the_code(self):
        assert "CONFLICT" in repr(GraphQLError("x", code="CONFLICT"))

    def test_is_expected_so_it_is_never_masked(self):
        assert GraphQLError("x").expected is True
