# sillo-graphql

Production GraphQL for [Sillo](https://sillo.build). Installs as
`sillo-graphql`, imports as `sillo.graphql`.

Strawberry owns the schema. This package owns everything around it — the
transports, the safety, and the observability.

```bash
pip install sillo-graphql
```

```python
import strawberry
from sillo import Depend, HttpContext, SilloApp
from sillo.graphql import Graph, Limits, field

@strawberry.type
class Query:
    @field
    async def me(ctx: HttpContext, db=Depend(get_db)) -> User:
        return await db.users.get(ctx.user.id)

app = SilloApp()
Graph(strawberry.Schema(query=Query), limits=Limits(depth=8)).mount(app)
```

## Resolvers that read like handlers

A `sillo` route handler takes the context first and declares what else it
needs. So does a resolver here:

```python
@field
async def posts(ctx: HttpContext, db=Depend(get_db), limit: int = 10) -> list[Post]:
    return await db.posts.recent(limit)
```

One rule: **`ctx` and anything defaulted to `Depend` are injected and never
appear in the schema; every other parameter is a GraphQL argument.** So this
field takes exactly one argument, `limit`.

Dependencies are resolved by the framework's own solver, with the framework's
own pre-flattened execution plan — two resolvers in one operation that both
ask for `Depend(get_db)` are handed the same session.

## Configuration

```python
graph = Graph(
    schema,
    path="/graphql",
    ide=False,                                       # explorer, off by default
    introspection=False,                             # off by default
    subscriptions=True,
    auth=Bearer(),                                   # the route's auth= gate
    limits=Limits(depth=10, cost=1_000, aliases=15),
    errors=ErrorPolicy(mask=True),
    transport=Transport(get_queries=True, batch=10),
    uploads=Uploads(enabled=True, max_size="10MB"),
    persisted=Persisted(apq=True, trusted="operations.json"),
)
graph.mount(app)
```

Common knobs are keyword arguments; the deeper ones are policy objects, the
same split the framework makes between arguments on `SilloApp` and objects
like `CSRFConfig`.

Every default is chosen for a public endpoint.

## What it does

### Cost limits, enforced before execution

Depth, aliases, breadth and document size, plus a weighted cost that
understands lists — a field returning a list multiplies everything under it, by
the page size the caller asked for when that is knowable.

```python
@field(cost=25)
async def search(ctx: HttpContext, term: str) -> list[Hit]: ...
```

An operation over budget is refused with `OPERATION_TOO_COMPLEX` and the limit
it passed, before a single resolver runs. Refusing afterwards would mean having
already done the work.

### Errors that say what happened, and no more

```python
from sillo.graphql import forbidden, not_found

@field
async def post(ctx: HttpContext, id: int) -> Post:
    found = await Post.objects.get_or_none(id=id)
    if found is None:
        raise not_found("No such post")     # extensions.code == "NOT_FOUND"
    return found
```

Free builders, like the framework's `json()` and `text()`. Errors raised this
way are deliberate and reach the client. An exception that escapes a resolver
is masked, logged with its traceback, and reported as `INTERNAL_SERVER_ERROR` —
because what it said may name a host, a table or a credential.

Map your own:

```python
@graph.on_error(RecordNotFound)
def _(exc): return not_found(str(exc))
```

### Batching, so a graph query is not a table scan per node

```python
@graph.loader
async def load_author(keys: list[int]) -> list[User]:
    rows = await User.objects.filter(id__in=keys).all()
    return align(rows, keys)

@field
async def author(ctx: HttpContext, root: Post) -> User:
    return await load_author(root.author_id)
```

Keys asked for by sibling fields in the same tick become one call. State is per
operation, so two concurrent requests never share a cache.

### Subscriptions that exist

`graphql-transport-ws` over the framework's own WebSocket layer, with an
initialisation timeout, ping/pong keepalive, and cancellation in a `finally` so
an operation cannot outlive its socket. Authentication belongs in
`connection_init`, because a browser cannot set headers on a WebSocket
handshake:

```python
@graph.on_connect
async def authenticate(socket, params):
    token = params.get("authorization")
    if not token:
        raise unauthenticated("A token is required")
    return {"user": await user_for(token)}
```

The same subscriptions are available over `text/event-stream` with `sse=True`,
for clients that cannot hold a socket open.

### The rest of the HTTP surface

Batched operations (capped, sequential), `GET` for queries with mutations
refused, `application/graphql` bodies, file uploads per the multipart request
spec, and content negotiation between `application/graphql-response+json` — the
spec's status codes — and legacy `application/json`, which stays always-200 for
the clients that expect it.

### Persisted operations

APQ saves bandwidth. A trusted-document manifest is the one that matters: with
`Persisted(trusted="operations.json")` the endpoint executes nothing else, so
the workload becomes finite and known.

### Knowing what it is doing

```python
graph.on_operation(OperationLog(slower_than=0.5))

metrics = Metrics()
graph.on_operation(metrics)
```

Per operation, not per path: `p99` on `POST /graphql` averages over work that
has nothing in common.

## Testing

```python
from sillo.graphql.testing import GraphClient

def test_me():
    with GraphClient(app) as gql:
        result = gql.query("{ me { email } }")
        assert result.ok
        assert result["me"]["email"] == "a@b.c"

async def test_prices():
    async with GraphClient(app).subscribe(PRICES, symbol="ACME") as stream:
        assert (await stream.next())["prices"]["last"] == 10
```

## The two import paths

`sillo.graphql` and `sillo_graphql` are the same module object, not two copies.

The code lives in the top-level `sillo_graphql` package. A `.pth` shipped with
the distribution registers a meta-path finder at interpreter startup, which is
the only hook that runs before an `import sillo.graphql` could fail. Nothing is
imported by it, and nothing is ever written into the framework's own `sillo/`
directory — two distributions writing into one package directory goes wrong in
both directions.

Type checkers do not run import hooks, so they are served separately by the
PEP 561 **partial** stubs in `sillo-stubs/`. The `partial` marker is what keeps
them additive: a checker resolves `sillo.graphql` from them and still uses the
framework's own inline types for the rest of `sillo`.

Versions of `sillo-framework` before 1.0 shipped a `sillo.graphql` of their
own. Rather than silently shadow it, the alias refuses and says so.

## Migrating from `sillo.graphql` in the framework

| before | now |
| --- | --- |
| `GraphQL(app, schema, path=, graphiql=True)` | `Graph(schema, path=, ide=False).mount(app)` |
| `info.context["ctx"]` | a `ctx: HttpContext` parameter |
| `self` / `info` resolver convention | `ctx` first, like every handler |
| — | `Depend(...)`, `@graph.loader`, `@graph.on_error` |
| errors leaked, IDE on, no limits | masked, IDE off, depth and cost enforced |

`info.context["ctx"]` still works — the context is a `Mapping` — so a schema
can migrate one resolver at a time.

## Requirements

Python 3.10+, `sillo-framework` 1.0 or newer, `strawberry-graphql`.

1.0 is the floor for two reasons: the resolver bridge is built on the
context-handler API, and `sillo.graphql` was the framework's own import path
until then. Against an older framework the alias refuses to load rather than
shadowing it — but the version pin is what stops you getting that far.

## License

BSD-3-Clause.
