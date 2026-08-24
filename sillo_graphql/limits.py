"""Static analysis of a document, before a resolver runs.

A GraphQL endpoint publishes a graph, and a graph with a cycle in it publishes
unbounded work behind a very small request. ``{ post { author { posts {
author { ... } } } } }`` is a handful of bytes and can be a table scan per
level. Rate limiting by request count does not help: the expensive request and
the cheap one both count as one.

So the document is measured first, and refused before execution if it is too
large. Refusing afterwards would mean having already done the work.

Four structural measures — depth, aliases of one field, breadth of a selection
set, and document size — plus a weighted cost that understands lists: a field
returning a list multiplies the cost of everything under it, by the page size
the caller asked for when that is knowable and by
:attr:`~sillo_graphql.policy.Limits.list_multiplier` when it is not.
"""

from __future__ import annotations

import dataclasses
import typing

from graphql import GraphQLList, GraphQLNonNull
from graphql.language import (
    DocumentNode,
    FieldNode,
    FragmentDefinitionNode,
    FragmentSpreadNode,
    InlineFragmentNode,
    IntValueNode,
    OperationDefinitionNode,
    SelectionSetNode,
    VariableNode,
)

from sillo_graphql.errors import ErrorCode, GraphQLError
from sillo_graphql.policy import Limits

if typing.TYPE_CHECKING:
    from graphql import GraphQLSchema

__all__ = ["Analysis", "analyze", "enforce"]

#: Arguments that name a page size. A field taking one of these is being asked
#: for that many rows, which is a far better multiplier than a guess.
PAGE_ARGS = ("first", "last", "limit", "take", "page_size", "pageSize")
