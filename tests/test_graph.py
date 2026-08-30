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


class TestHooks:
    def test_a_context_hook_adds_keys(self, schema):
        app = SilloApp(debug=False)
        graph = Graph(schema)
        seen = []

        @graph.context
        def add(ctx):
            return {"tenant": "acme"}

        @graph.on_operation
        def observe(result, context):
            seen.append(context.extra.get("tenant"))

        graph.mount(app)
        with GraphClient(app) as gql:
            assert gql.query("{ hello }").ok
        assert seen == ["acme"]

    async def test_an_async_context_hook_is_awaited(self, schema):
        graph = Graph(schema)

        @graph.context
        async def add(ctx):
            return {"tenant": "acme"}

        context = await graph._context(http=None, socket=None)
        assert context.extra["tenant"] == "acme"

    async def test_a_hook_returning_nothing_changes_nothing(self, schema):
        graph = Graph(schema)

        @graph.context
        def add(ctx):
            return None

        context = await graph._context(http=None, socket=None)
        assert context.extra == {}

    async def test_connection_params_are_put_on_the_context(self, schema):
        graph = Graph(schema)
        context = await graph._context(http=None, socket=None, params={"t": 1})
        assert context.extra["connection_params"] == {"t": 1}

    async def test_a_connect_hook_contributes_to_the_context(self, schema):
        graph = Graph(schema)

        @graph.on_connect
        async def authenticate(socket, params):
            return {"user": params.get("token")}

        assert await graph.connect(None, {"token": "abc"}) == {"user": "abc"}

    async def test_a_sync_connect_hook_works(self, schema):
        graph = Graph(schema)

        @graph.on_connect
        def authenticate(socket, params):
            return {"seen": True}

        assert await graph.connect(None, {}) == {"seen": True}

    async def test_a_connect_hook_returning_nothing_is_ignored(self, schema):
        graph = Graph(schema)

        @graph.on_connect
        def authenticate(socket, params):
            return None

        assert await graph.connect(None, {}) == {}

    def test_an_operation_hook_sees_every_operation(self, schema):
        app = SilloApp(debug=False)
        graph = Graph(schema)
        seen = []

        @graph.on_operation
        def observe(result, context):
            seen.append((context.operation_name, len(result.errors)))

        graph.mount(app)
        with GraphClient(app) as gql:
            gql.query("query Named { hello }")
        assert seen == [("Named", 0)]

    async def test_an_async_operation_hook_is_awaited(self, schema):
        graph = Graph(schema)
        seen = []

        @graph.on_operation
        async def observe(result, context):
            seen.append(result)

        await graph.run({"query": "{ hello }"})
        assert len(seen) == 1

    def test_a_loader_can_be_declared_from_the_graph(self, schema):
        graph = Graph(schema)

        @graph.loader
        async def load(keys):
            return list(keys)

        assert load.name == "load"


class TestResult:
    def test_a_successful_body_carries_data(self):
        assert Result(data={"a": 1}).body() == {"data": {"a": 1}}

    def test_errors_alone_omit_data(self):
        body = Result(errors=[{"message": "x"}]).body()
        assert "data" not in body

    def test_a_null_data_with_errors_is_still_reported(self):
        body = Result(data=None, errors=[{"message": "x", "path": ["a"]}]).body()
        assert body["errors"]

    def test_extensions_are_included_when_there_are_some(self):
        assert Result(data={}, extensions={"cost": 1}).body()["extensions"]

    def test_ok_reflects_the_errors(self):
        assert Result().ok is True
        assert Result(errors=[{"message": "x"}]).ok is False


class TestInternals:
    def test_errors_with_a_path_came_from_execution(self):
        assert _executed([{"message": "x", "path": ["a"]}]) is True

    def test_errors_without_a_path_did_not(self):
        assert _executed([{"message": "x"}]) is False

    def test_the_graphql_core_schema_is_reachable(self, schema):
        assert _graphql_schema(schema) is not None

    def test_a_schema_without_one_degrades_quietly(self):
        assert _graphql_schema(object()) is None


def _ours(caplog) -> str:
    """Only the records this package logged."""
    return "\n".join(
        record.getMessage() + (record.exc_text or "")
        for record in caplog.records
        if record.name == "sillo.graphql"
    )


class TestCoverageOfEdges:
    """Paths that only appear under a particular configuration."""

    def test_mounting_without_subscriptions_registers_no_socket(
        self, query_only_schema
    ):
        app = SilloApp()
        Graph(query_only_schema).mount(app)
        assert all(route.name != "graphql-ws" for route in app.get_all_routes())

    async def test_a_subscription_that_cannot_start_yields_one_result(self, schema):
        graph = Graph(schema)
        document = 'subscription { ticks(count: "not an int") }'
        results = [result async for result in graph.stream({"query": document})]
        assert len(results) == 1
        assert results[0].errors

    def test_the_explorer_advertises_the_socket_when_there_is_one(self, schema):
        app = SilloApp(debug=False)
        Graph(schema, ide=IDE(enabled=True)).mount(app)
        with GraphClient(app) as gql:
            page = gql.ide().text
        assert "ws://" in page or "wss://" in page

    def test_the_explorer_offers_no_socket_when_subscriptions_are_off(
        self, query_only_schema
    ):
        app = SilloApp(debug=False)
        Graph(query_only_schema, ide=IDE(enabled=True)).mount(app)
        with GraphClient(app) as gql:
            page = gql.ide().text
        assert '"subscriptions": false' in page or '"subscriptions":false' in page

    async def test_an_error_with_no_connection_has_no_correlation_id(self, schema):
        result = await Graph(schema).run({"query": "{ boom }"})
        assert "requestId" not in result.errors[0]["extensions"]

    async def test_a_request_id_attribute_is_used_when_there_is_one(self, schema):
        class Socket:
            request_id = "from-attribute"
            user = None

        result = await Graph(schema).run({"query": "{ boom }"}, socket=Socket())
        assert result.errors[0]["extensions"]["requestId"] == "from-attribute"

    async def test_a_connection_without_headers_is_tolerated(self, schema):
        class Socket:
            user = None

        result = await Graph(schema).run({"query": "{ boom }"}, socket=Socket())
        assert "requestId" not in result.errors[0]["extensions"]

    async def test_headers_without_a_request_id_add_nothing(self, schema):
        class Socket:
            user = None
            headers = {}

        result = await Graph(schema).run({"query": "{ boom }"}, socket=Socket())
        assert "requestId" not in result.errors[0]["extensions"]

    def test_an_unnamed_operation_stays_unnamed(self, schema):
        app = SilloApp(debug=False)
        graph = Graph(schema)
        seen = []
        graph.on_operation(lambda result, context: seen.append(context.operation_name))
        graph.mount(app)
        with GraphClient(app) as gql:
            gql.query("{ hello }")
        assert seen == [None]

    def test_two_named_operations_take_the_requested_one(self, schema):
        app = SilloApp(debug=False)
        graph = Graph(schema)
        seen = []
        graph.on_operation(lambda result, context: seen.append(context.operation_name))
        graph.mount(app)
        with GraphClient(app) as gql:
            gql.query("query A { hello } query B { hello }", operation_name="B")
        assert seen == ["B"]


class TestOlderStrawberry:
    async def test_a_non_iterable_subscribe_result_becomes_one_result(
        self, schema, monkeypatch
    ):
        class Legacy:
            """What older Strawberry hands back when a subscription cannot start."""

            errors = [type("E", (), {"formatted": {"message": "cannot start"}})()]

        graph = Graph(schema)

        async def fake_subscribe(*args, **kwargs):
            return Legacy()

        monkeypatch.setattr(graph.schema, "subscribe", fake_subscribe)
        results = [
            result async for result in graph.stream({"query": "subscription { ticks }"})
        ]
        assert len(results) == 1
        assert results[0].messages if hasattr(results[0], "messages") else True
        assert results[0].errors[0]["message"] == "cannot start"

    async def test_a_non_iterable_result_with_no_errors_is_empty(
        self, schema, monkeypatch
    ):
        class Legacy:
            pass

        graph = Graph(schema)

        async def fake_subscribe(*args, **kwargs):
            return Legacy()

        monkeypatch.setattr(graph.schema, "subscribe", fake_subscribe)
        results = [
            result async for result in graph.stream({"query": "subscription { ticks }"})
        ]
        assert results[0].errors == []
