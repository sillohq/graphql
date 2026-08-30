# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0]

First release. Extracted from the framework's `sillo.graphql` module, and
rebuilt around it rather than moved.

### Added

- `Graph`, built and then mounted, matching how every other subsystem attaches
  to an application. Mounts on a `SilloApp` or a `Router`.
- `field`, `mutation` and `subscription` decorators that adapt `sillo`'s
  handler convention onto Strawberry resolvers: `ctx` and `Depend` parameters
  are injected and stripped from the schema; everything else is a GraphQL
  argument. Dependencies are resolved through the framework's own solver, so
  one operation shares one dependency cache.
- `GraphContext`, a typed context carrying the connection, a response handle
  for setting status, headers and cookies from a resolver, the loader registry
  and the authenticated user. Also a `Mapping`, so `info.context["ctx"]` keeps
  working.
- Static cost analysis before execution: depth, aliases, breadth, document
  tokens, and a weighted cost with list multipliers derived from `first`,
  `last`, `limit` and friends. `@field(cost=...)` prices a field.
- Error policy: free builders (`not_found`, `forbidden`, `unauthenticated`,
  `bad_input`, `conflict`, `too_many_requests`, `internal`) with stable
  `extensions.code`, masking of unexpected exceptions, `@graph.on_error`
  mapping, and a correlation id on every error.
- Request-scoped `DataLoader` batching via `@graph.loader`, with cache
  priming, `load_many`, batch-size chunking and per-key error results.
- Subscriptions over `graphql-transport-ws`, with an initialisation timeout,
  ping/pong, duplicate-id detection and cancellation of every operation when
  the socket closes. `@graph.on_connect` authenticates from the
  `connection_init` payload.
- Subscriptions over `text/event-stream` (`sse=True`) for clients that cannot
  hold a socket open.
- GraphQL-over-HTTP: content negotiation between
  `application/graphql-response+json` and legacy `application/json`, correct
  status codes, `GET` queries with mutations refused, `application/graphql`
  bodies, form bodies, capped sequential batching, and body size limits.
- File uploads per the GraphQL multipart request spec, with per-file, per-count
  and per-request size limits and a content-type allow-list. Off by default.
- Persisted operations: APQ with hash verification, and a trusted-document
  manifest that refuses everything not in it.
- A bundled explorer with no external requests, so it works offline and under
  a strict CSP. GraphiQL from a CDN remains available with `IDE(assets="cdn")`.
- `Metrics`, `OperationLog` and an OpenTelemetry hook, all through
  `@graph.on_operation`.
- `GraphClient` and `SubscriptionStream` test helpers.
- `sillo.graphql` as an import alias for `sillo_graphql`, via a `.pth`-loaded
  meta-path finder and PEP 561 partial stubs. Nothing is written into the
  framework's package directory, and the alias refuses rather than shadows a
  framework that still ships its own `sillo.graphql`.

### Changed from the framework's `sillo.graphql`

- The explorer is **off** by default, and introspection with it.
- Resolver exceptions are **masked** by default.
- Depth and cost limits are **enforced** by default.
- A request with no document is a 400, not a 500.
- The endpoint is excluded from the OpenAPI document, which described it
  incorrectly.

[Unreleased]: https://github.com/sillohq/graphql/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/sillohq/graphql/releases/tag/v0.1.0
