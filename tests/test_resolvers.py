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
