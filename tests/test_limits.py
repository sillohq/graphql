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


class TestDepth:
    def test_a_flat_query_is_depth_one(self):
        assert measure("{ name }").depth == 1

    def test_nesting_counts(self, gql_schema):
        assert measure("{ tree { child { name } } }", schema=gql_schema).depth == 3

    def test_over_the_limit_is_refused_with_the_limit_named(self):
        with pytest.raises(GraphQLError) as caught:
            enforce(parse("{ a { b { c { d } } } }"), limits=Limits(depth=3))
        assert caught.value.code == ErrorCode.OPERATION_TOO_COMPLEX
        assert caught.value.as_extensions()["limit"] == 3

    def test_a_fragment_adds_the_depth_it_expands_to(self, gql_schema):
        document = "{ tree { ...deep } } fragment deep on Node { child { name } }"
        assert measure(document, schema=gql_schema).depth == 3

    def test_an_inline_fragment_does_not_add_a_level(self, gql_schema):
        plain = measure("{ tree { name } }", schema=gql_schema).depth
        inline = measure("{ tree { ... on Node { name } } }", schema=gql_schema).depth
        assert plain == inline
