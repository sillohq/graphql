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


class TestBuilders:
    @pytest.mark.parametrize(
        ("builder", "code"),
        [
            (not_found, ErrorCode.NOT_FOUND),
            (bad_input, ErrorCode.BAD_USER_INPUT),
            (conflict, ErrorCode.CONFLICT),
            (internal, ErrorCode.INTERNAL_SERVER_ERROR),
            (too_many_requests, ErrorCode.TOO_MANY_REQUESTS),
        ],
    )
    def test_each_carries_its_own_code(self, builder, code):
        assert builder("message").code == code

    def test_keyword_arguments_become_extensions(self):
        error = not_found("gone", id=7)
        assert error.as_extensions() == {"code": "NOT_FOUND", "id": 7}

    def test_retry_after_is_named_for_the_client(self):
        error = too_many_requests(retry_after=2.5)
        assert error.as_extensions()["retryAfter"] == 2.5

    def test_retry_after_is_omitted_when_unknown(self):
        assert "retryAfter" not in too_many_requests().as_extensions()

    def test_every_builder_has_a_usable_default_message(self):
        assert not_found().message
        assert forbidden().message
        assert unauthenticated().message
        assert internal().message
        assert too_many_requests().message


class TestDenied:
    def test_unauthenticated_is_a_401(self):
        error = unauthenticated()
        assert isinstance(error, GraphQLDenied)
        assert error.status_code == 401
        assert error.code == ErrorCode.UNAUTHENTICATED

    def test_forbidden_is_a_403(self):
        error = forbidden()
        assert error.status_code == 403
        assert error.code == ErrorCode.FORBIDDEN

    def test_is_still_a_graphql_error(self):
        assert isinstance(forbidden(), GraphQLError)

    def test_status_can_be_chosen(self):
        assert GraphQLDenied("x", status_code=418).status_code == 418
