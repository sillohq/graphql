"""``sillo_graphql.limits`` — measuring a document before it runs."""

from __future__ import annotations

import pytest
from graphql import build_schema, parse

from sillo_graphql.errors import ErrorCode, GraphQLError
from sillo_graphql.limits import analyze, enforce
from sillo_graphql.policy import Limits

SDL = """
type Node { name: String, child: Node, children(first: Int): [Node] }
type Query {
  tree: Node
  name: String
  nodes(limit: Int): [Node]
  tagged(kind: String, limit: Int): [Node]
}
type Mutation { touch: String }
"""


@pytest.fixture(scope="module")
def gql_schema():
    return build_schema(SDL)


def measure(document: str, *, limits=None, schema=None, **kwargs):
    return analyze(parse(document), limits=limits or Limits(), schema=schema, **kwargs)
