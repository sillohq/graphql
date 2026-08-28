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
