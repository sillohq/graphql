"""``sillo_graphql.resolvers`` — the bridge from handler style to Strawberry."""

from __future__ import annotations

import typing

import pytest
import strawberry
from sillo import Depend, HttpContext

from sillo_graphql.context import GraphContext
from sillo_graphql.resolvers import (
    ResolverError,
    _annotation_name,
    field,
    mutation,
    resolver_costs,
    subscription,
)


def sdl_of(**fields) -> str:
    """Build a one-type schema and return its SDL."""
    Query = strawberry.type(type("Query", (), {"__annotations__": {}, **fields}))
    return strawberry.Schema(query=Query).as_str()


async def run(schema, document, context=None, **kwargs):
    return await schema.execute(
        document, context_value=context or GraphContext(), **kwargs
    )
