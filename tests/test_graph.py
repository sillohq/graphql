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


class TestMounting:
    def test_it_registers_on_an_application(self, schema):
        app = SilloApp()
        Graph(schema).mount(app)
        assert any(route.name == "graphql" for route in app.get_all_routes())

    def test_mount_returns_the_graph(self, schema):
        assert isinstance(Graph(schema).mount(SilloApp()), Graph)

    def test_it_registers_on_a_router(self, schema):
        router = Router()
        Graph(schema).mount(router)
        assert router is not None

    def test_it_is_kept_out_of_the_openapi_document(self, schema):
        app = SilloApp()
        Graph(schema).mount(app)
        with GraphClient(app) as client:
            document = client._client.get("/openapi.json")
        assert "/graphql" not in document.json().get("paths", {})


class TestErrorPolicy:
    def test_an_unexpected_exception_is_masked(self, gql):
        result = gql.query("{ boom }")
        assert result.messages == ["Unexpected error"]
        assert result.codes == ["INTERNAL_SERVER_ERROR"]

    def test_the_original_message_never_reaches_the_client(self, gql):
        assert "secret" not in str(gql.query("{ boom }").body)

    def test_masking_can_be_turned_off(self, build):
        with GraphClient(build(errors=ErrorPolicy(mask=False))) as gql:
            assert "dsn=postgres" in gql.query("{ boom }").messages[0]

    def test_a_deliberate_error_is_never_masked(self, gql):
        result = gql.query("{ me(id: 99) }")
        assert result.messages == ["no user 99"]
        assert result.codes == ["NOT_FOUND"]

    def test_a_validation_error_is_passed_on_verbatim(self, gql):
        result = gql.query("{ nope }")
        assert "Cannot query field" in result.messages[0]
        assert result.codes == ["BAD_USER_INPUT"]

    def test_a_masked_error_is_logged_with_its_traceback(self, build, caplog):
        with (
            caplog.at_level(logging.ERROR, logger="sillo.graphql"),
            GraphClient(build()) as gql,
        ):
            gql.query("{ boom }")
        assert "dsn=postgres" in _ours(caplog)

    def test_logging_can_be_turned_off(self, build, caplog):
        # Scoped to this package's logger: Strawberry reports the error on its
        # own logger too, which is not what this option governs.
        policy = ErrorPolicy(log_masked=False)
        with (
            caplog.at_level(logging.ERROR, logger="sillo.graphql"),
            GraphClient(build(errors=policy)) as gql,
        ):
            gql.query("{ boom }")
        assert _ours(caplog) == ""

    def test_a_stacktrace_can_be_attached_for_development(self, build):
        policy = ErrorPolicy(mask=False, include_stacktrace=True)
        with GraphClient(build(errors=policy)) as gql:
            trace = gql.query("{ boom }").errors[0]["extensions"]["stacktrace"]
        assert any("RuntimeError" in line for line in trace)

    def test_a_registered_mapping_replaces_the_error(self, schema):
        app = SilloApp(debug=False)
        graph = Graph(schema)

        @graph.on_error(RuntimeError)
        def _(exc):
            return not_found(f"mapped: {exc}")

        graph.mount(app)
        with GraphClient(app) as gql:
            result = gql.query("{ boom }")
        assert result.codes == ["NOT_FOUND"]
        assert result.messages[0].startswith("mapped:")

    def test_a_mapping_that_returns_nothing_is_ignored(self, schema):
        app = SilloApp(debug=False)
        graph = Graph(schema)

        @graph.on_error(RuntimeError)
        def _(exc):
            return None

        graph.mount(app)
        with GraphClient(app) as gql:
            assert gql.query("{ boom }").messages == ["Unexpected error"]

    def test_a_mapping_for_another_exception_does_not_fire(self, schema):
        app = SilloApp(debug=False)
        graph = Graph(schema)

        @graph.on_error(KeyError)
        def _(exc):
            return not_found("wrong one")

        graph.mount(app)
        with GraphClient(app) as gql:
            assert gql.query("{ boom }").messages == ["Unexpected error"]

    def test_a_request_id_header_is_echoed_into_errors(self, gql):
        result = gql.query("{ boom }", headers={"x-request-id": "abc-123"})
        assert result.errors[0]["extensions"]["requestId"] == "abc-123"

    def test_the_correlation_key_can_be_switched_off(self, build):
        policy = ErrorPolicy(correlation_key=None)
        with GraphClient(build(errors=policy)) as gql:
            result = gql.query("{ boom }", headers={"x-request-id": "abc"})
        assert "requestId" not in result.errors[0]["extensions"]


class TestGuards:
    def test_introspection_is_refused_by_default(self, gql):
        result = gql.query("{ __schema { types { name } } }")
        assert result.status_code == 403
        assert result.codes == ["OPERATION_NOT_PERMITTED"]

    def test_introspection_can_be_allowed(self, build):
        with GraphClient(build(introspection=True)) as gql:
            assert gql.query("{ __schema { types { name } } }").ok

    def test_typename_is_not_introspection(self, gql):
        assert gql.query("{ __typename }").ok

    def test_introspection_nested_in_a_query_is_still_caught(self, gql):
        assert gql.query("{ hello __schema { types { name } } }").status_code == 403

    def test_an_operation_over_budget_is_refused(self, build):
        with GraphClient(build(limits=Limits(depth=2))) as gql:
            result = gql.query("{ tree { child { child { name } } } }")
        assert result.codes == ["OPERATION_TOO_COMPLEX"]

    def test_the_refusal_names_the_limit(self, build):
        with GraphClient(build(limits=Limits(depth=2))) as gql:
            result = gql.query("{ tree { child { name } } }")
        assert result.errors[0]["extensions"]["limit"] == 2

    def test_a_syntax_error_is_a_400(self, gql):
        result = gql.query("{ this is not graphql")
        assert result.status_code == 400
        assert result.codes == ["BAD_USER_INPUT"]

    def test_cost_is_reported_in_extensions(self, gql):
        assert gql.query("{ hello }").extensions["cost"]["fields"] == 1

    def test_cost_is_not_reported_when_analysis_is_off(self, build):
        with GraphClient(build(limits=Limits(cost=None))) as gql:
            assert "cost" not in gql.query("{ hello }").extensions
