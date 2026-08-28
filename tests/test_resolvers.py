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


class TestSignature:
    def test_ctx_is_injected_and_hidden_from_the_schema(self, http_context):
        @strawberry.type
        class Query:
            @field
            def who(ctx: HttpContext) -> str:
                return ctx.method

        schema = strawberry.Schema(query=Query)
        assert "who: String!" in schema.as_str()
        assert "ctx" not in schema.as_str()

    def test_a_depend_default_is_injected_and_hidden(self):
        async def dependency():
            return "injected"

        @strawberry.type
        class Query:
            @field
            def who(value=Depend(dependency)) -> str:
                return value

        assert "who: String!" in strawberry.Schema(query=Query).as_str()

    def test_other_parameters_become_arguments(self):
        @strawberry.type
        class Query:
            @field
            def echo(text: str, times: int = 2) -> str:
                return text * times

        sdl = strawberry.Schema(query=Query).as_str()
        assert "echo(text: String!, times: Int! = 2): String!" in sdl

    def test_a_root_parameter_is_the_parent_and_is_hidden(self):
        @strawberry.type
        class Child:
            @field
            def loud(root: typing.Any) -> str:
                return str(root.name).upper()

            name: str = "x"

        assert "loud: String!" in strawberry.Schema(query=Child).as_str()

    def test_an_info_parameter_is_hidden(self):
        @strawberry.type
        class Query:
            @field
            def named(info: strawberry.Info) -> str:
                return info.field_name

        assert "named: String!" in strawberry.Schema(query=Query).as_str()

    def test_the_whole_graph_context_can_be_asked_for(self):
        @strawberry.type
        class Query:
            @field
            def op(context: GraphContext) -> str:
                return str(context.operation_name)

        assert "op: String!" in strawberry.Schema(query=Query).as_str()

    def test_an_unannotated_argument_is_refused_with_advice(self):
        with pytest.raises(ResolverError, match="no annotation"):

            @field
            def bad(thing) -> str:
                return "x"

    def test_varargs_are_refused(self):
        with pytest.raises(ResolverError, match="fixed list"):

            @field
            def bad(*things: int) -> str:
                return "x"

    def test_kwargs_are_refused(self):
        with pytest.raises(ResolverError, match="fixed list"):

            @field
            def bad(**things: int) -> str:
                return "x"


class TestAnnotationName:
    @pytest.mark.parametrize(
        ("annotation", "expected"),
        [
            (HttpContext, "HttpContext"),
            ("HttpContext", "HttpContext"),
            ("sillo.core.http.HttpContext", "HttpContext"),
            ("HttpContext | None", "HttpContext"),
            ("Optional[HttpContext]", "HttpContext"),
            (int, "int"),
        ],
    )
    def test_it_reduces_to_the_bare_name(self, annotation, expected):
        assert _annotation_name(annotation) == expected

    def test_an_empty_annotation_is_empty(self):
        import inspect

        assert _annotation_name(inspect.Parameter.empty) == ""


class TestExecution:
    async def test_ctx_reaches_the_resolver(self, http_context):
        @strawberry.type
        class Query:
            @field
            def method(ctx: HttpContext) -> str:
                return ctx.method

        schema = strawberry.Schema(query=Query)
        result = await run(schema, "{ method }", GraphContext(http=http_context))
        assert result.data == {"method": "POST"}

    async def test_a_dependency_is_resolved(self, http_context):
        async def dependency():
            return "from di"

        @strawberry.type
        class Query:
            @field
            def value(thing=Depend(dependency)) -> str:
                return thing

        schema = strawberry.Schema(query=Query)
        result = await run(schema, "{ value }", GraphContext(http=http_context))
        assert result.data == {"value": "from di"}

    async def test_two_resolvers_share_one_dependency_value(self, http_context):
        calls = []

        async def dependency():
            calls.append(1)
            return len(calls)

        @strawberry.type
        class Query:
            @field
            def a(thing=Depend(dependency)) -> int:
                return thing

            @field
            def b(thing=Depend(dependency)) -> int:
                return thing

        schema = strawberry.Schema(query=Query)
        result = await run(schema, "{ a b }", GraphContext(http=http_context))
        assert result.data == {"a": 1, "b": 1}
        assert len(calls) == 1

    async def test_a_generator_dependency_is_closed_afterwards(self, http_context):
        closed = []

        async def dependency():
            # `finally`, because teardown runs through `aclose()`, which
            # raises GeneratorExit at the yield — bare code after it never
            # runs, here or in a route.
            try:
                yield "open"
            finally:
                closed.append(True)

        @strawberry.type
        class Query:
            @field
            def value(thing=Depend(dependency)) -> str:
                return thing

        schema = strawberry.Schema(query=Query)
        await run(schema, "{ value }", GraphContext(http=http_context))
        assert closed == [True]

    async def test_a_sync_resolver_works(self):
        @strawberry.type
        class Query:
            @field
            def plain(x: int) -> int:
                return x + 1

        result = await run(strawberry.Schema(query=Query), "{ plain(x: 1) }")
        assert result.data == {"plain": 2}

    async def test_arguments_arrive_by_name(self):
        @strawberry.type
        class Query:
            @field
            def join(left: str, right: str = "!") -> str:
                return left + right

        schema = strawberry.Schema(query=Query)
        assert (await run(schema, '{ join(left: "a") }')).data == {"join": "a!"}

    async def test_asking_for_ctx_without_a_connection_says_so(self):
        @strawberry.type
        class Query:
            @field
            def needs(ctx: HttpContext) -> str:
                return "x"

        result = await run(strawberry.Schema(query=Query), "{ needs }")
        assert "no connection context" in result.errors[0].message


class TestAuth:
    async def test_a_gated_field_refuses_an_anonymous_caller(self):
        @strawberry.type
        class Query:
            @field(auth=True)
            def secret() -> str:
                return "x"

        result = await run(strawberry.Schema(query=Query), "{ secret }")
        assert "Not authenticated" in result.errors[0].message

    async def test_a_gated_field_admits_a_signed_in_caller(self):
        class Socket:
            user = "ada"

        @strawberry.type
        class Query:
            @field(auth=True)
            def secret() -> str:
                return "top"

        context = GraphContext(socket=Socket())
        result = await run(strawberry.Schema(query=Query), "{ secret }", context)
        assert result.data == {"secret": "top"}

    async def test_a_predicate_can_refuse(self):
        class Socket:
            user = "guest"

        @strawberry.type
        class Query:
            @field(auth=lambda user: user == "ada")
            def secret() -> str:
                return "top"

        context = GraphContext(socket=Socket())
        result = await run(strawberry.Schema(query=Query), "{ secret }", context)
        assert "Not permitted" in result.errors[0].message

    async def test_an_async_predicate_is_awaited(self):
        class Socket:
            user = "ada"

        async def allow(user):
            return user == "ada"

        @strawberry.type
        class Query:
            @field(auth=allow)
            def secret() -> str:
                return "top"

        context = GraphContext(socket=Socket())
        result = await run(strawberry.Schema(query=Query), "{ secret }", context)
        assert result.data == {"secret": "top"}


class TestMutation:
    async def test_it_reads_like_a_field(self):
        @strawberry.type
        class Query:
            @field
            def ping() -> str:
                return "pong"

        @strawberry.type
        class Mutation:
            @mutation
            async def shout(text: str) -> str:
                return text.upper()

        schema = strawberry.Schema(query=Query, mutation=Mutation)
        result = await run(schema, 'mutation { shout(text: "hi") }')
        assert result.data == {"shout": "HI"}

    def test_it_can_be_called_with_options(self):
        @strawberry.type
        class Mutation:
            @mutation(description="Renames a thing.")
            async def rename(name: str) -> str:
                return name

        @strawberry.type
        class Query:
            @field
            def ping() -> str:
                return "pong"

        sdl = strawberry.Schema(query=Query, mutation=Mutation).as_str()
        assert "Renames a thing." in sdl


class TestSubscription:
    async def test_a_generator_streams(self):
        @strawberry.type
        class Query:
            @field
            def ping() -> str:
                return "pong"

        @strawberry.type
        class Subscription:
            @subscription
            async def counter(to: int = 2) -> typing.AsyncGenerator[int, None]:
                for index in range(to):
                    yield index

        schema = strawberry.Schema(query=Query, subscription=Subscription)
        stream = await schema.subscribe(
            "subscription { counter(to: 2) }", context_value=GraphContext()
        )
        got = [result.data["counter"] async for result in stream]
        assert got == [0, 1]

    def test_a_plain_function_is_refused(self):
        with pytest.raises(ResolverError, match="async generator"):

            @subscription
            async def not_a_generator() -> int:
                return 1

    def test_it_can_be_called_with_options(self):
        @strawberry.type
        class Subscription:
            @subscription(description="Ticks.")
            async def ticks() -> typing.AsyncGenerator[int, None]:
                yield 1

        @strawberry.type
        class Query:
            @field
            def ping() -> str:
                return "pong"

        sdl = strawberry.Schema(query=Query, subscription=Subscription).as_str()
        assert "Ticks." in sdl

    async def test_a_dependency_is_closed_when_the_stream_ends(self):
        closed = []

        async def dependency():
            try:
                yield "open"
            finally:
                closed.append(True)

        @strawberry.type
        class Query:
            @field
            def ping() -> str:
                return "pong"

        @strawberry.type
        class Subscription:
            @subscription
            async def one(thing=Depend(dependency)) -> typing.AsyncGenerator[str, None]:
                yield thing

        schema = strawberry.Schema(query=Query, subscription=Subscription)
        stream = await schema.subscribe(
            "subscription { one }", context_value=GraphContext()
        )
        assert [r.data["one"] async for r in stream] == ["open"]
        assert closed == [True]


class TestCosts:
    def test_a_declared_cost_is_registered(self):
        @field(cost=42)
        def expensive() -> str:
            return "x"

        assert resolver_costs()["expensive"] == 42

    def test_a_renamed_field_registers_under_its_schema_name(self):
        @field(cost=7, name="cheap")
        def internal_name() -> str:
            return "x"

        assert resolver_costs()["cheap"] == 7

    def test_a_mutation_can_declare_a_cost(self):
        @mutation(cost=9)
        async def costly(x: int) -> int:
            return x

        assert resolver_costs()["costly"] == 9

    def test_the_table_is_a_copy(self):
        resolver_costs()["injected"] = 1
        assert "injected" not in resolver_costs()


class TestSyncDependencies:
    async def test_a_sync_generator_dependency_is_closed(self, http_context):
        closed = []

        def dependency():
            try:
                yield "open"
            finally:
                closed.append(True)

        @strawberry.type
        class Query:
            @field
            def value(thing=Depend(dependency)) -> str:
                return thing

        schema = strawberry.Schema(query=Query)
        result = await run(schema, "{ value }", GraphContext(http=http_context))
        assert result.data == {"value": "open"}
        # `close()` on a sync generator returns None, not an awaitable.
        assert closed == [True]
