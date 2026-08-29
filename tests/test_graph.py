"""``sillo_graphql.graph`` — configuration, the pipeline, and error policy."""

from __future__ import annotations

import logging

from sillo import SilloApp
from sillo.core.routing import Router

from sillo_graphql import (
    IDE,
    ErrorPolicy,
    Graph,
    Limits,
    Persisted,
    Result,
    not_found,
)
from sillo_graphql.graph import _executed, _graphql_schema
from sillo_graphql.testing import GraphClient


class TestConstruction:
    def test_the_path_is_normalised(self, schema):
        assert Graph(schema, path="api/graph/").path == "/api/graph"
        assert Graph(schema, path="/graphql").path == "/graphql"

    def test_a_bare_slash_survives(self, schema):
        assert Graph(schema, path="/").path == "/"

    def test_ide_true_is_shorthand_for_an_enabled_one(self, schema):
        assert Graph(schema, ide=True).ide.enabled is True

    def test_an_ide_object_is_taken_as_given(self, schema):
        graph = Graph(schema, ide=IDE(enabled=True, title="Acme"))
        assert graph.ide.title == "Acme"

    def test_the_ide_is_off_by_default(self, schema):
        assert Graph(schema).ide.enabled is False

    def test_introspection_is_off_by_default(self, schema):
        assert Graph(schema).introspection is False

    def test_subscriptions_are_mounted_when_the_schema_has_them(self, schema):
        assert Graph(schema).subscriptions is True

    def test_subscriptions_are_not_claimed_when_the_schema_lacks_them(
        self, query_only_schema
    ):
        assert Graph(query_only_schema).subscriptions is False

    def test_asking_for_absent_subscriptions_is_only_a_debug_note(
        self, query_only_schema, caplog
    ):
        with caplog.at_level(logging.DEBUG, logger="sillo.graphql"):
            Graph(query_only_schema, subscriptions=True)
        assert "no subscription type" in caplog.text

    def test_a_manifest_is_loaded_at_construction(self, schema):
        graph = Graph(schema, persisted=Persisted(trusted={"abc": "{ hello }"}))
        assert graph.trusted is not None
        assert len(graph.trusted) == 1

    def test_no_manifest_means_none(self, schema):
        assert Graph(schema).trusted is None

    def test_an_empty_store_is_not_replaced(self, schema):
        from sillo_graphql.persisted import MemoryStore

        store = MemoryStore()
        assert Graph(schema, store=store).store is store

    def test_repr_says_where_it_is(self, schema):
        assert "/graphql" in repr(Graph(schema))

    def test_declared_costs_are_collected(self, schema):
        graph = Graph(schema, costs={"Query.hello": 5})
        assert graph._costs["Query.hello"] == 5
        # `@field(cost=25)` on `search` in the shared schema.
        assert graph._costs["search"] == 25

    def test_a_cost_can_be_added_afterwards(self, schema):
        graph = Graph(schema).cost("hello", 3)
        assert graph._costs["hello"] == 3
