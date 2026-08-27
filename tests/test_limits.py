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


class TestAliases:
    def test_the_same_field_selected_twice_counts_twice(self):
        assert measure("{ a: name b: name }").aliases == 2

    def test_over_the_limit_names_the_field(self):
        document = "{ " + " ".join(f"a{i}: name" for i in range(6)) + " }"
        with pytest.raises(GraphQLError, match="'name'"):
            enforce(parse(document), limits=Limits(aliases=5))

    def test_aliases_are_counted_per_selection_set(self, gql_schema):
        # Three here and three there is not the same as six of one field.
        document = "{ a: tree { x: name y: name } b: tree { x: name y: name } }"
        assert measure(document, schema=gql_schema).aliases == 2


class TestBreadth:
    def test_it_is_the_largest_selection_set(self):
        assert measure("{ a b c }").breadth == 3

    def test_over_the_limit_is_refused(self):
        document = "{ " + " ".join(f"f{i}: name" for i in range(12)) + " }"
        with pytest.raises(GraphQLError, match="over the limit"):
            enforce(parse(document), limits=Limits(breadth=10, aliases=100))


class TestCost:
    def test_a_flat_query_costs_one_per_field(self):
        assert measure("{ a b c }", limits=Limits(cost=None)).cost == 3

    def test_a_list_multiplies_what_is_under_it(self, gql_schema):
        result = measure(
            "{ nodes { name } }", schema=gql_schema, limits=Limits(list_multiplier=10)
        )
        # 1 for `nodes`, then 10 for the `name` under it.
        assert result.cost == 11

    def test_a_page_argument_is_used_instead_of_the_guess(self, gql_schema):
        result = measure("{ nodes(limit: 3) { name } }", schema=gql_schema)
        assert result.cost == 4

    def test_a_page_argument_from_a_variable_is_used(self, gql_schema):
        result = measure(
            "query ($n: Int) { nodes(limit: $n) { name } }",
            schema=gql_schema,
            variables={"n": 2},
        )
        assert result.cost == 3

    def test_a_boolean_variable_is_not_a_page_size(self, gql_schema):
        result = measure(
            "query ($n: Int) { nodes(limit: $n) { name } }",
            schema=gql_schema,
            variables={"n": True},
            limits=Limits(list_multiplier=10),
        )
        assert result.cost == 11

    def test_an_unknown_variable_falls_back_to_the_multiplier(self, gql_schema):
        result = measure(
            "query ($n: Int) { nodes(limit: $n) { name } }",
            schema=gql_schema,
            limits=Limits(list_multiplier=7),
        )
        assert result.cost == 8

    def test_a_non_list_field_does_not_multiply(self, gql_schema):
        assert measure("{ tree { name } }", schema=gql_schema).cost == 2

    def test_without_a_schema_every_nested_field_is_treated_as_a_list(self):
        # Erring towards refusing large queries rather than allowing them.
        assert (
            measure("{ tree { name } }", limits=Limits(list_multiplier=10)).cost == 11
        )

    def test_a_field_can_be_priced_by_name(self):
        assert measure("{ search }", costs={"search": 25}).cost == 25

    def test_a_field_can_be_priced_per_type(self, gql_schema):
        result = measure(
            "{ tree { name } }", schema=gql_schema, costs={"Node.name": 50}
        )
        assert result.cost == 51

    def test_the_qualified_price_wins_over_the_bare_one(self, gql_schema):
        result = measure(
            "{ tree { name } }",
            schema=gql_schema,
            costs={"name": 5, "Node.name": 50},
        )
        assert result.cost == 51

    def test_over_budget_is_refused_with_the_cost_reported(self):
        with pytest.raises(GraphQLError) as caught:
            enforce(parse("{ a b c }"), limits=Limits(cost=2, default_field_cost=1))
        assert caught.value.as_extensions()["limit"] == 2

    def test_cost_analysis_can_be_switched_off(self):
        document = "{ " + " ".join(f"f{i}: name" for i in range(10)) + " }"
        assert enforce(parse(document), limits=Limits(cost=None, aliases=100))

    def test_introspection_fields_are_free(self):
        assert measure("{ __typename }").cost == 0
        assert measure("{ __schema { types { name } } }").cost == 0


class TestFragments:
    def test_a_cyclic_fragment_does_not_hang(self):
        document = "{ ...a } fragment a on Query { ...a }"
        assert measure(document).depth >= 1

    def test_an_unknown_fragment_is_left_to_validation(self):
        assert measure("{ ...missing }").fields == 0

    def test_an_inline_fragment_narrows_the_parent_type(self, gql_schema):
        result = measure(
            "{ tree { ... on Node { name } } }",
            schema=gql_schema,
            costs={"Node.name": 9},
        )
        assert result.cost == 10

    def test_a_condition_naming_an_unknown_type_keeps_the_parent(self, gql_schema):
        result = measure("{ tree { ... on Ghost { name } } }", schema=gql_schema)
        assert result.fields == 2
