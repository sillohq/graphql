"""Fixtures shared by the suite.

One schema serves nearly every test. It is deliberately small and deliberately
awkward in the places that matter — a recursive type for depth tests, a
resolver that raises for masking tests, a subscription that ends on its own —
so the tests exercise behaviour rather than set up a new schema each time.
"""

from __future__ import annotations

import asyncio
import typing

import pytest
import strawberry
from sillo import Depend, HttpContext, SilloApp

from sillo_graphql import Graph, field, mutation, not_found, subscription
from sillo_graphql.context import GraphContext

pytest_plugins: list[str] = []


async def get_db() -> dict[str, dict[int, str]]:
    """A stand-in dependency, so `Depend` is exercised for real."""
    return {"users": {1: "Ada", 2: "Grace"}}


@strawberry.type
class Node:
    """A type that contains itself, for depth and cost tests."""

    name: str

    @strawberry.field
    def child(self) -> Node:
        return Node(name=self.name + "'")

    @strawberry.field
    def children(self, first: int = 10) -> list[Node]:
        return [Node(name=f"{self.name}-{i}") for i in range(first)]


@strawberry.type
class Query:
    @field
    async def me(ctx: HttpContext, db=Depend(get_db), id: int = 1) -> str:
        name = db["users"].get(id)
        if name is None:
            raise not_found(f"no user {id}")
        return f"{name} via {ctx.method}"

    @field
    def hello() -> str:
        return "world"

    @field(cost=25)
    def search(term: str) -> str:
        return term[::-1]

    @field
    def boom() -> str:
        raise RuntimeError("dsn=postgres://user:secret@10.0.0.5/db")

    @field
    def tree() -> Node:
        return Node(name="root")

    @field(auth=True)
    def gated() -> str:
        return "members only"

    @field
    def stamp(context: GraphContext) -> str:
        """Exercises a resolver influencing the HTTP response."""
        context.response.set_status(418)
        context.response.set_header("x-stamped", "yes")
        context.response.set_cookie("seen", "1")
        return "stamped"


@strawberry.type
class Mutation:
    @mutation
    async def rename(name: str) -> str:
        return name.upper()


@strawberry.type
class Subscription:
    @subscription
    async def ticks(count: int = 3) -> typing.AsyncGenerator[int, None]:
        for index in range(count):
            yield index

    @subscription
    async def failing() -> typing.AsyncGenerator[int, None]:
        yield 1
        raise RuntimeError("subscription broke")

    @subscription
    async def slow(delay: float = 0.05) -> typing.AsyncGenerator[int, None]:
        """Never ends, and waits between values.

        `ticks` yields without ever awaiting, so on a fast machine the whole
        stream can finish before an unsubscribe arrives — and the cancellation
        paths that unsubscribe exists to exercise are never reached. This one
        is always mid-await when the message lands.
        """
        index = 0
        while True:
            await asyncio.sleep(delay)
            yield index
            index += 1


@pytest.fixture(scope="session")
def schema() -> strawberry.Schema:
    """The shared schema. Session-scoped: building one is not free."""
    return strawberry.Schema(query=Query, mutation=Mutation, subscription=Subscription)


@pytest.fixture(scope="session")
def query_only_schema() -> strawberry.Schema:
    """A schema with no subscription type, for the mounting tests."""
    return strawberry.Schema(query=Query)


@pytest.fixture
def build(schema):
    """Build an app with a `Graph` mounted, configured however a test likes."""

    def make(**kwargs) -> SilloApp:
        app = SilloApp(debug=False)
        Graph(kwargs.pop("schema", schema), **kwargs).mount(app)
        return app

    return make


@pytest.fixture
def app(build) -> SilloApp:
    """An application with a default `Graph` on it."""
    return build()


@pytest.fixture
def gql(app):
    """A `GraphClient` against the default application."""
    from sillo_graphql.testing import GraphClient

    with GraphClient(app) as client:
        yield client


@pytest.fixture
def http_context() -> HttpContext:
    """A bare HTTP context, for tests that do not need an application."""
    return HttpContext(
        {
            "type": "http",
            "method": "POST",
            "path": "/graphql",
            "headers": [(b"host", b"testserver")],
            "query_string": b"",
        },
        receive=None,
        send=None,
    )
