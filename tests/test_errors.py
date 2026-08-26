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
