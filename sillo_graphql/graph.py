"""The endpoint: configuration, mounting, and one execution pipeline.

``Graph`` is built and then mounted, which is how every other ``sillo``
subsystem is put together — ``AdminSite(...)`` then ``admin.mount(app)``. The
previous integration took the application in its constructor and registered a
route as a side effect of ``__init__``, which is why it read as foreign::

    graph = Graph(schema, ide=True)
    graph.mount(app)

Everything a request passes through lives here rather than in a transport:
persisted-document resolution, the introspection guard, cost analysis, context
building and error policy. The three transports frame and answer; they do not
decide. That is what keeps a query over ``GET`` subject to the same limits as
one over a WebSocket.
"""

from __future__ import annotations

import dataclasses
import inspect
import logging
import traceback
import typing

from graphql import parse
from graphql.error import GraphQLSyntaxError
from graphql.language import (
    DocumentNode,
    FieldNode,
    OperationDefinitionNode,
    OperationType,
)

from sillo_graphql import ide as ide_module
from sillo_graphql.context import GraphContext, current_context
from sillo_graphql.errors import ErrorCode, GraphQLDenied, GraphQLError
from sillo_graphql.limits import Analysis, enforce
from sillo_graphql.loaders import loader as make_loader
from sillo_graphql.persisted import (
    MemoryStore,
    PersistedStore,
    TrustedDocuments,
    resolve_document,
)
from sillo_graphql.policy import (
    IDE,
    ErrorPolicy,
    Limits,
    Persisted,
    Transport,
    Uploads,
)
from sillo_graphql.resolvers import resolver_costs
from sillo_graphql.transport.http import HttpTransport
from sillo_graphql.transport.sse import SseTransport
from sillo_graphql.transport.ws import WebSocketTransport

if typing.TYPE_CHECKING:
    import strawberry

__all__ = ["Graph", "Result"]

LOGGER = logging.getLogger("sillo.graphql")

#: Meta-fields that expose the schema. ``__typename`` is not one of them: it
#: answers about the object in hand, not about the schema, and clients need it.
INTROSPECTION_FIELDS = frozenset({"__schema", "__type"})


@dataclasses.dataclass(frozen=True, slots=True)
class _Prepared:
    """A document that has passed every gate and is ready to execute."""

    source: str
    document: DocumentNode
    variables: dict[str, typing.Any] | None
    operation_name: str | None
    analysis: Analysis


@dataclasses.dataclass(slots=True)
class Result:
    """One operation's answer, before a transport frames it.

    Attributes:
        data: The ``data`` field, or ``None`` when execution did not begin.
        errors: Already-formatted error objects.
        extensions: Merged extensions, cost included when it was measured.
        status_code: What the spec's media type should answer with. Ignored
            under the legacy ``application/json``, which is always 200.
        response: What resolvers asked to do to the response, if anything.
    """

    data: typing.Any = None
    errors: list[dict[str, typing.Any]] = dataclasses.field(default_factory=list)
    extensions: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    status_code: int = 200
    response: typing.Any = None

    def body(self) -> dict[str, typing.Any]:
        """The JSON object to send.

        ``data`` is present whenever execution began — including as ``null``,
        which is how a client tells a failed operation from one that was never
        run at all.
        """
        body: dict[str, typing.Any] = {}
        if self.errors:
            body["errors"] = self.errors
        if self.data is not None or not self.errors:
            body["data"] = self.data
        if self.extensions:
            body["extensions"] = self.extensions
        return body

    @property
    def ok(self) -> bool:
        """Whether the operation produced no errors."""
        return not self.errors


class Graph:
    """A GraphQL endpoint.

    Args:
        schema: The Strawberry schema to serve. This package owns the
            transport, the safety and the observability around a schema; the
            schema itself stays Strawberry's.
        path: Where the endpoint is mounted.
        name: Route name, for ``url_for``.
        ide: ``True``, or an :class:`~sillo_graphql.policy.IDE` for the
            details. Off by default.
        introspection: Whether ``__schema`` and ``__type`` may be queried. Off
            by default: an endpoint that publishes its own schema publishes
            every field an attacker might try.
        subscriptions: Mount the WebSocket transport. Ignored, with a warning,
            when the schema declares no subscription type — a page that offers
            a socket the server does not serve is worse than no page.
        sse: Also serve subscriptions over ``text/event-stream``.
        auth: Passed to the route's ``auth=`` gate.
        middleware: Passed to the route's ``middleware=``.
        limits: How large an operation may be.
        errors: What a client is told when something fails.
        transport: Which parts of the HTTP surface are served.
        uploads: Multipart file uploads.
        persisted: APQ and trusted documents.
        costs: Extra per-field costs, as ``{"Type.field": 25}`` or
            ``{"field": 25}``. Merged with everything ``@field(cost=...)``
            declared.
        store: Where APQ documents are kept between requests.
        root_value: Passed to every execution.
        logger: Where masked errors are reported.
    """

    def __init__(
        self,
        schema: strawberry.Schema,
        *,
        path: str = "/graphql",
        name: str | None = "graphql",
        ide: bool | IDE = False,
        introspection: bool = False,
        subscriptions: bool = True,
        sse: bool = False,
        auth: typing.Any = None,
        middleware: list[typing.Any] | None = None,
        limits: Limits | None = None,
        errors: ErrorPolicy | None = None,
        transport: Transport | None = None,
        uploads: Uploads | None = None,
        persisted: Persisted | None = None,
        costs: dict[str, int] | None = None,
        store: PersistedStore | None = None,
        root_value: typing.Any = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.schema = schema
        self.path = "/" + path.strip("/") if path.strip("/") else "/"
        self.name = name
        self.ide = IDE(enabled=True) if ide is True else (ide or IDE())
        self.introspection = introspection
        self.sse = sse
        self.auth = auth
        self.middleware = middleware
        self.limits = limits or Limits()
        self.errors = errors or ErrorPolicy()
        self.transport = transport or Transport()
        self.uploads = uploads or Uploads()
        self.persisted = persisted or Persisted()
        self.root_value = root_value
        self.logger = logger or LOGGER
        # `is not None`, not `or`: a store defines __len__, so an empty one
        # a caller passed in is falsy and would be silently replaced.
        self.store: PersistedStore = store if store is not None else MemoryStore()

        self.trusted: TrustedDocuments | None = (
            TrustedDocuments(self.persisted.trusted)
            if self.persisted.trusted is not None
            else None
        )

        self.subscriptions = subscriptions and self._has_subscriptions()
        if subscriptions and not self.subscriptions:
            self.logger.debug(
                "%s declares no subscription type; not mounting a socket", self.path
            )

        self._costs: dict[str, int] = {**resolver_costs(), **(costs or {})}
        self._context_hooks: list[typing.Callable[..., typing.Any]] = []
        self._connect_hooks: list[typing.Callable[..., typing.Any]] = []
        self._error_hooks: list[
            tuple[type[BaseException], typing.Callable[..., typing.Any]]
        ] = []
        self._operation_hooks: list[typing.Callable[..., typing.Any]] = []

        self.http = HttpTransport(self)
        self.ws = WebSocketTransport(self)
        self.events = SseTransport(self)

    # ------------------------------------------------------------------ setup

    def mount(self, app: typing.Any) -> Graph:
        """Register this endpoint on an application or a router.

        Returns ``self``, so a one-liner is available where the object is not
        needed afterwards::

            Graph(schema).mount(app)
        """
        from sillo.core.routing import Route

        app.add_route(
            Route(
                self.path,
                self.http.handle,
                methods=["GET", "POST"],
                name=self.name,
                auth=self.auth,
                middleware=self.middleware,
                # A GraphQL endpoint is one path with one body shape. Listing
                # it as an ordinary operation says nothing true about it, and
                # the schema is the documentation.
                exclude_from_schema=True,
            )
        )
        if self.subscriptions:
            app.add_ws_route(path=self.path, handler=self.ws.handle)
        return self

    def context(
        self, fn: typing.Callable[..., typing.Any]
    ) -> typing.Callable[..., typing.Any]:
        """Add keys to every resolver's context.

        The hook is given the connection's context and returns a mapping,
        which is merged into :attr:`GraphContext.extra`::

            @graph.context
            async def tenant(ctx: HttpContext) -> dict:
                return {"tenant": await tenant_for(ctx)}
        """
        self._context_hooks.append(fn)
        return fn

    def on_connect(
        self, fn: typing.Callable[..., typing.Any]
    ) -> typing.Callable[..., typing.Any]:
        """Authenticate a WebSocket, from its ``connection_init`` payload.

        A browser cannot set headers on a WebSocket handshake, so a token
        arrives in that payload instead. Raise
        :func:`~sillo_graphql.errors.unauthenticated` to refuse the
        connection; whatever is returned is merged into the context.
        """
        self._connect_hooks.append(fn)
        return fn

    def on_error(
        self, exception: type[BaseException]
    ) -> typing.Callable[
        [typing.Callable[..., typing.Any]], typing.Callable[..., typing.Any]
    ]:
        """Map an application exception onto a GraphQL error::

            @graph.on_error(RecordNotFound)
            def _(exc): return not_found(str(exc))

        Without a mapping, an unexpected exception is masked — which is the
        right default and a poor experience for exceptions the application
        raises on purpose.
        """

        def decorate(
            fn: typing.Callable[..., typing.Any],
        ) -> typing.Callable[..., typing.Any]:
            self._error_hooks.append((exception, fn))
            return fn

        return decorate

    def on_operation(
        self, fn: typing.Callable[..., typing.Any]
    ) -> typing.Callable[..., typing.Any]:
        """Observe every operation after it completes.

        The hook is given the :class:`Result` and the
        :class:`~sillo_graphql.context.GraphContext`, and its return value is
        ignored. Used for metrics and slow-operation logs; see
        :mod:`sillo_graphql.tracing`.
        """
        self._operation_hooks.append(fn)
        return fn

    def loader(self, fn: typing.Any = None, **options: typing.Any) -> typing.Any:
        """Declare a batching loader. See :mod:`sillo_graphql.loaders`."""
        return make_loader(fn, **options)

    def cost(self, field: str, value: int) -> Graph:
        """Price one field, by ``Type.field`` or by bare field name."""
        self._costs[field] = value
        return self

    # -------------------------------------------------------------- execution

    async def run(
        self,
        payload: dict[str, typing.Any],
        *,
        http: typing.Any = None,
        socket: typing.Any = None,
        allow_mutations: bool = True,
        connection_params: dict[str, typing.Any] | None = None,
    ) -> Result:
        """Execute one operation and return its result.

        Never raises for anything a client did: a refusal is a
        :class:`Result` with ``errors`` and a status, so every transport
        answers the same way.
        """
        context = await self._context(
            http=http, socket=socket, params=connection_params
        )
        token = current_context.set(context)
        try:
            prepared = await self._prepare(payload, context, allow_mutations)
        except GraphQLError as error:
            current_context.reset(token)
            return self._refused(error, context)

        try:
            execution = await self.schema.execute(
                prepared.source,
                variable_values=prepared.variables,
                context_value=context,
                root_value=self.root_value,
                operation_name=prepared.operation_name,
            )
        finally:
            current_context.reset(token)

        result = Result(
            data=execution.data,
            errors=self._format(execution.errors or [], context),
            extensions=self._extensions(execution, prepared.analysis),
            response=context.response,
        )
        if result.errors and execution.data is None and not _executed(result.errors):
            # Nothing ran: a syntax or validation failure. Errors from an
            # operation that did run stay 200 even when `data` is null,
            # because null there is the schema's non-null propagation and not
            # a statement about the request.
            result.status_code = 400
        await self._observe(result, context)
        return result

    async def stream(
        self,
        payload: dict[str, typing.Any],
        *,
        http: typing.Any = None,
        socket: typing.Any = None,
        connection_params: dict[str, typing.Any] | None = None,
    ) -> typing.AsyncIterator[Result]:
        """Execute an operation and yield each result it produces.

        A subscription yields many; a query or mutation yields exactly one, so
        a client may use one transport for all three.
        """
        context = await self._context(
            http=http, socket=socket, params=connection_params
        )
        token = current_context.set(context)
        try:
            prepared = await self._prepare(payload, context, True)

            if not _is_subscription(prepared.document, prepared.operation_name):
                yield await self._one(prepared, context)
                return

            subscription = await self.schema.subscribe(
                prepared.source,
                variable_values=prepared.variables,
                context_value=context,
                root_value=self.root_value,
                operation_name=prepared.operation_name,
            )
            # Current Strawberry answers `subscribe` with an async generator
            # even for a document that cannot start, and reports the failure on
            # the stream. Older ones hand back a bare ExecutionResult instead,
            # which is not iterable — so it is turned into the one result it
            # represents rather than raising a TypeError at the `async for`.
            if not hasattr(subscription, "__aiter__"):
                errors = getattr(subscription, "errors", None) or []
                yield Result(errors=self._format(errors, context))
                return

            async for execution in subscription:
                yield Result(
                    data=execution.data,
                    errors=self._format(execution.errors or [], context),
                    extensions=self._extensions(execution, prepared.analysis),
                )
        finally:
            current_context.reset(token)

    async def connect(
        self, socket: typing.Any, params: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        """Run the ``on_connect`` hooks for a new WebSocket."""
        extra: dict[str, typing.Any] = {}
        for hook in self._connect_hooks:
            value = hook(socket, params)
            if inspect.isawaitable(value):
                value = await value
            if isinstance(value, dict):
                extra.update(value)
        return extra

    def render_ide(self, ctx: typing.Any) -> str:
        """The explorer page for this endpoint."""
        socket = None
        if self.subscriptions:
            url = str(getattr(ctx, "url", "") or "")
            socket = (
                url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
                or None
            )
        return ide_module.render(self.ide, endpoint=self.path, socket=socket)

    # --------------------------------------------------------------- internals

    async def _one(self, prepared: _Prepared, context: GraphContext) -> Result:
        """A query or mutation asked for through a streaming transport."""
        execution = await self.schema.execute(
            prepared.source,
            variable_values=prepared.variables,
            context_value=context,
            root_value=self.root_value,
            operation_name=prepared.operation_name,
        )
        return Result(
            data=execution.data,
            errors=self._format(execution.errors or [], context),
            extensions=self._extensions(execution, prepared.analysis),
            response=context.response,
        )

    async def _context(
        self,
        *,
        http: typing.Any,
        socket: typing.Any,
        params: dict[str, typing.Any] | None = None,
    ) -> GraphContext:
        context = GraphContext(http=http, socket=socket)
        if params:
            context.extra["connection_params"] = params
        for hook in self._context_hooks:
            value = hook(context.connection)
            if inspect.isawaitable(value):
                value = await value
            if isinstance(value, dict):
                context.extra.update(value)
        return context

    async def _prepare(
        self,
        payload: dict[str, typing.Any],
        context: GraphContext,
        allow_mutations: bool,
    ) -> _Prepared:
        """Everything that must be true before a resolver runs."""
        source = await resolve_document(
            payload,
            policy=self.persisted,
            store=self.store,
            trusted=self.trusted,
        )

        variables = payload.get("variables")
        variables = variables if isinstance(variables, dict) else None
        operation_name = payload.get("operationName")
        operation_name = operation_name if isinstance(operation_name, str) else None

        try:
            document = parse(source, max_tokens=self.limits.max_tokens)
        except GraphQLSyntaxError as exc:
            raise GraphQLError(str(exc.message), code=ErrorCode.BAD_USER_INPUT) from exc

        # A client that sends one named operation rarely names it again in
        # `operationName`. Reading it off the document is what makes
        # per-operation metrics and logs say something.
        context.operation_name = operation_name or _sole_operation_name(document)

        if not allow_mutations and _has_mutation(document):
            raise GraphQLDenied(
                "Mutations are not allowed over GET",
                code=ErrorCode.BAD_USER_INPUT,
                status_code=405,
            )

        if not self.introspection and _has_introspection(document):
            raise GraphQLDenied(
                "Introspection is disabled on this endpoint",
                code=ErrorCode.OPERATION_NOT_PERMITTED,
            )

        analysis = enforce(
            document,
            limits=self.limits,
            schema=_graphql_schema(self.schema),
            operation_name=operation_name,
            variables=variables,
            costs=self._costs,
        )
        context.cost = analysis.cost
        # The source rather than the parsed document: Strawberry's `execute`
        # takes a string and parses it itself. Parsing twice costs microseconds
        # against an operation that is about to touch a database, and handing
        # it an AST it does not accept costs correctness.
        return _Prepared(source, document, variables, operation_name, analysis)

    def _refused(self, error: GraphQLError, context: GraphContext) -> Result:
        """A result for an operation that never reached execution."""
        status = getattr(error, "status_code", 400)
        return Result(
            errors=[{"message": error.message, "extensions": error.as_extensions()}],
            status_code=status,
            response=context.response,
        )

    def _format(
        self, errors: typing.Sequence[typing.Any], context: GraphContext
    ) -> list[dict[str, typing.Any]]:
        """Turn execution errors into what the client is allowed to see."""
        return [self._one_error(error, context) for error in errors]

    def _one_error(
        self, error: typing.Any, context: GraphContext
    ) -> dict[str, typing.Any]:
        original = getattr(error, "original_error", None)
        formatted = dict(error.formatted)
        extensions = dict(formatted.get("extensions") or {})

        mapped = self._map(original) if original is not None else None
        if mapped is not None:
            formatted["message"] = mapped.message
            extensions.update(mapped.as_extensions())
        elif isinstance(original, GraphQLError):
            extensions.update(original.as_extensions())
        elif original is not None and self.errors.mask:
            # An exception the application did not mean to expose. What it
            # said may name a host, a table or a credential.
            if self.errors.log_masked:
                self.logger.exception(
                    "masked error in %s",
                    context.operation_name or "operation",
                    exc_info=original,
                )
            formatted["message"] = self.errors.mask_message
            extensions.setdefault("code", ErrorCode.INTERNAL_SERVER_ERROR)
        elif original is not None:
            extensions.setdefault("code", ErrorCode.INTERNAL_SERVER_ERROR)
        else:
            # No original error means graphql-core produced it: a syntax or
            # validation failure, which is about the client's document and is
            # safe to pass on verbatim.
            extensions.setdefault("code", ErrorCode.BAD_USER_INPUT)

        if self.errors.include_stacktrace and original is not None:
            extensions["stacktrace"] = traceback.format_exception(
                type(original), original, original.__traceback__
            )

        request_id = self._request_id(context)
        if request_id is not None and self.errors.correlation_key:
            extensions[self.errors.correlation_key] = request_id

        formatted["extensions"] = extensions
        return formatted

    def _map(self, original: BaseException) -> GraphQLError | None:
        """The registered mapping for this exception, if there is one."""
        for kind, hook in self._error_hooks:
            if isinstance(original, kind):
                mapped = hook(original)
                if isinstance(mapped, GraphQLError):
                    return mapped
        return None

    @staticmethod
    def _request_id(context: GraphContext) -> str | None:
        connection = context.connection
        if connection is None:
            return None
        for attribute in ("request_id", "correlation_id"):
            value = getattr(connection, attribute, None)
            if isinstance(value, str):
                return value
        headers = getattr(connection, "headers", None)
        if headers is not None:
            value = headers.get("x-request-id")
            if isinstance(value, str):
                return value
        return None

    def _extensions(
        self, execution: typing.Any, analysis: Analysis | None
    ) -> dict[str, typing.Any]:
        extensions = dict(getattr(execution, "extensions", None) or {})
        if analysis is not None and self.limits.cost is not None:
            extensions["cost"] = analysis.as_extensions()
        return extensions

    async def _observe(self, result: Result, context: GraphContext) -> None:
        for hook in self._operation_hooks:
            outcome = hook(result, context)
            if inspect.isawaitable(outcome):
                await outcome

    def _has_subscriptions(self) -> bool:
        schema = _graphql_schema(self.schema)
        return schema is not None and schema.subscription_type is not None

    def __repr__(self) -> str:
        return f"Graph({self.path!r}, subscriptions={self.subscriptions})"
