"""GraphQL over HTTP.

Implements the GraphQL-over-HTTP specification, which is mostly a set of rules
about when the answer is 200 and when it is 400 — and which the previous
integration answered with "always 200", including for a document that failed
to parse.

Two response media types, negotiated from ``Accept``:

``application/graphql-response+json``
    The spec's own. A request that never reaches execution — malformed JSON, a
    missing document, a validation failure — is a 4xx. A request that executes
    and produces field errors is a 200 with ``errors`` in the body, because
    the operation did run.

``application/json``
    The legacy shape every existing client understands: 200 for everything
    except a body that could not be read at all. Chosen when the client does
    not ask for the other, so nothing that works today stops working.
"""

from __future__ import annotations

import json as jsonlib
import typing

from sillo.responses import html, json

from sillo_graphql.errors import ErrorCode, GraphQLError

if typing.TYPE_CHECKING:
    from sillo.core.http import HttpContext

    from sillo_graphql.graph import Graph

__all__ = ["HttpTransport", "negotiate"]

#: The spec's media type. A client sending this in `Accept` is asking to be
#: told about failures with status codes rather than only in the body.
GRAPHQL_RESPONSE_JSON = "application/graphql-response+json"
APPLICATION_JSON = "application/json"
APPLICATION_GRAPHQL = "application/graphql"
MULTIPART_FORM = "multipart/form-data"
FORM_URLENCODED = "application/x-www-form-urlencoded"


def negotiate(accept: str | None, *, enabled: bool) -> str:
    """Which response media type to answer with.

    The legacy type wins ties and wins by default: a client that says nothing,
    or says ``*/*``, is a client that has not thought about this, and the
    always-200 shape is what its library expects.
    """
    if not enabled or not accept:
        return APPLICATION_JSON
    for part in accept.split(","):
        media = part.split(";", 1)[0].strip().lower()
        if media == GRAPHQL_RESPONSE_JSON:
            return GRAPHQL_RESPONSE_JSON
        if media in (APPLICATION_JSON, "*/*", "application/*"):
            return APPLICATION_JSON
    return APPLICATION_JSON


class HttpTransport:
    """Serves one :class:`~sillo_graphql.graph.Graph` over HTTP."""

    def __init__(self, graph: Graph) -> None:
        self.graph = graph

    async def handle(self, ctx: HttpContext) -> typing.Any:
        """Answer one request.

        Never raises: a transport that raises turns a client's malformed body
        into a 500 and an entry in the error budget.
        """
        media = negotiate(
            ctx.headers.get("accept"),
            enabled=self.graph.transport.response_content_type,
        )
        try:
            if ctx.method == "GET":
                return await self._get(ctx, media)
            if ctx.method == "POST":
                return await self._post(ctx, media)
        except GraphQLError as error:
            # `GraphQLDenied` carries its own status; anything else is a 400.
            return self._error(error, media, status=getattr(error, "status_code", 400))
        return self._message(
            "Method Not Allowed", ErrorCode.BAD_USER_INPUT, media, status=405
        )

    async def _get(self, ctx: HttpContext, media: str) -> typing.Any:
        """``GET`` is either the explorer or a query, decided by ``Accept``."""
        params = ctx.query_params
        wants_html = "text/html" in (ctx.headers.get("accept") or "")

        if "query" not in params and "extensions" not in params:
            if self.graph.ide.enabled and wants_html:
                return html(self.graph.render_ide(ctx))
            return self._message(
                "No query in the request", ErrorCode.BAD_USER_INPUT, media, status=400
            )

        if not self.graph.transport.get_queries:
            return self._message(
                "Queries over GET are disabled on this endpoint",
                ErrorCode.BAD_USER_INPUT,
                media,
                status=405,
            )

        payload = _from_params(params)
        # A mutation must not be reachable by following a link, prefetching a
        # URL, or replaying a cache entry. The method is defined as safe.
        result = await self.graph.run(payload, http=ctx, allow_mutations=False)
        return self._result(result, media)

    async def _post(self, ctx: HttpContext, media: str) -> typing.Any:
        content_type = (ctx.headers.get("content-type") or "").split(";", 1)[0].strip()

        if content_type.startswith(MULTIPART_FORM):
            return await self._multipart(ctx, media)

        body = await ctx.body
        limit = self.graph.transport.max_body_bytes
        if len(body) > limit:
            return self._message(
                f"Request body is larger than the limit of {limit} bytes",
                ErrorCode.BAD_USER_INPUT,
                media,
                status=413,
            )

        if content_type == APPLICATION_GRAPHQL:
            if not self.graph.transport.graphql_content_type:
                return self._unsupported(content_type, media)
            payload: typing.Any = {"query": body.decode("utf-8", "replace")}
        elif content_type in ("", APPLICATION_JSON) or content_type.endswith("+json"):
            try:
                payload = jsonlib.loads(body)
            except ValueError:
                return self._message(
                    "Request body is not valid JSON",
                    ErrorCode.BAD_USER_INPUT,
                    media,
                    status=400,
                )
        elif content_type == FORM_URLENCODED:
            payload = _from_params(await ctx.form)
        else:
            return self._unsupported(content_type, media)

        if isinstance(payload, list):
            return await self._batch(payload, ctx, media)
        if not isinstance(payload, dict):
            return self._message(
                "Request body must be an object, or an array for a batch",
                ErrorCode.BAD_USER_INPUT,
                media,
                status=400,
            )

        result = await self.graph.run(payload, http=ctx)
        return self._result(result, media)

    async def _batch(
        self, payloads: list[typing.Any], ctx: HttpContext, media: str
    ) -> typing.Any:
        """Execute an array of operations, in order.

        Capped, and sequential. A batch is a work multiplier that arrives as
        one request, so running it concurrently would let a client turn one
        connection into as many as it likes.
        """
        allowed = self.graph.transport.batch
        if allowed == 0:
            return self._message(
                "Batched requests are not accepted on this endpoint",
                ErrorCode.BAD_USER_INPUT,
                media,
                status=400,
            )
        if not payloads:
            return self._message(
                "A batch must hold at least one operation",
                ErrorCode.BAD_USER_INPUT,
                media,
                status=400,
            )
        if len(payloads) > allowed:
            return self._message(
                f"A batch may hold at most {allowed} operations, not {len(payloads)}",
                ErrorCode.BAD_USER_INPUT,
                media,
                status=400,
            )

        bodies = []
        status = 200
        for payload in payloads:
            if not isinstance(payload, dict):
                bodies.append(
                    {
                        "errors": [
                            {
                                "message": "Each operation in a batch must be "
                                "an object",
                                "extensions": {"code": ErrorCode.BAD_USER_INPUT},
                            }
                        ]
                    }
                )
                continue
            result = await self.graph.run(payload, http=ctx)
            bodies.append(result.body())
            # One status for the whole batch, and the worst one in it: a
            # transport cannot answer two.
            status = max(status, result.status_code)

        return self._respond(bodies, media, status, ctx)

    async def _multipart(self, ctx: HttpContext, media: str) -> typing.Any:
        """The GraphQL multipart request spec: ``operations``, ``map``, files."""
        uploads = self.graph.uploads
        if not uploads.enabled:
            return self._message(
                "File uploads are not enabled on this endpoint",
                ErrorCode.BAD_USER_INPUT,
                media,
                status=415,
            )

        form = await ctx.form
        raw = form.get("operations")
        mapping = form.get("map")
        # Both are text fields per the spec. A client that sends them as file
        # parts instead is malformed, and `map` would otherwise be walked as
        # if it were JSON.
        if not isinstance(raw, str) or not isinstance(mapping, str):
            return self._message(
                "A multipart request needs `operations` and `map` fields",
                ErrorCode.BAD_USER_INPUT,
                media,
                status=400,
            )
        try:
            payload = jsonlib.loads(raw)
            paths = jsonlib.loads(mapping)
        except ValueError:
            return self._message(
                "`operations` and `map` must both be JSON",
                ErrorCode.BAD_USER_INPUT,
                media,
                status=400,
            )
        if not isinstance(payload, dict) or not isinstance(paths, dict):
            return self._message(
                "`operations` must be an object and `map` a mapping of file "
                "name to variable paths",
                ErrorCode.BAD_USER_INPUT,
                media,
                status=400,
            )

        files = await ctx.files
        try:
            _attach(payload, paths, files, uploads)
        except GraphQLError as error:
            return self._error(error, media, status=400)

        result = await self.graph.run(payload, http=ctx)
        return self._result(result, media)

    def _result(self, result: typing.Any, media: str) -> typing.Any:
        """Frame an execution result.

        The status is honoured under both media types. The spec's legacy mode
        is nominally always-200, but a request that never reached execution —
        a syntax error, a refused method, an operation over budget — is not a
        GraphQL response, and answering 200 for it means every client has to
        inspect the body to find out whether its request was even understood.
        Errors produced by an operation that *did* run stay 200, which is the
        part clients actually depend on.
        """
        return self._respond(
            result.body(), media, result.status_code, None, result=result
        )

    def _respond(
        self,
        body: typing.Any,
        media: str,
        status: int,
        ctx: typing.Any,
        result: typing.Any = None,
    ) -> typing.Any:
        response = json(body, status_code=status, headers={"content-type": media})
        if result is not None and result.response is not None:
            # Whatever the resolvers asked for: a status, headers, cookies.
            if result.response.status_code is not None:
                response.status_code = result.response.status_code
            result.response.apply(response)
        return response

    def _error(self, error: GraphQLError, media: str, *, status: int) -> typing.Any:
        return self._message(
            error.message, error.code, media, status=status, extra=error.extensions
        )

    def _message(
        self,
        message: str,
        code: str,
        media: str,
        *,
        status: int,
        extra: dict[str, typing.Any] | None = None,
    ) -> typing.Any:
        """A request-level failure, in the shape a GraphQL client expects.

        These are the failures that happen *before* execution — an unreadable
        body, a refused method, a body over the size limit — so they carry a
        4xx under both media types. Only errors produced by an operation that
        actually ran are folded into a 200, and those come through
        :meth:`_result` instead.
        """
        body = {
            "errors": [
                {"message": message, "extensions": {"code": code, **(extra or {})}}
            ]
        }
        return json(body, status_code=status, headers={"content-type": media})

    def _unsupported(self, content_type: str, media: str) -> typing.Any:
        return self._message(
            f"Unsupported content type {content_type!r}. Send application/json.",
            ErrorCode.BAD_USER_INPUT,
            media,
            status=415,
        )


def _from_params(params: typing.Mapping[str, typing.Any]) -> dict[str, typing.Any]:
    """A payload from query-string or form fields.

    ``variables`` and ``extensions`` arrive as JSON text in these transports,
    and are decoded here so the rest of the pipeline sees one payload shape.
    """
    payload: dict[str, typing.Any] = {}
    for key in ("query", "operationName", "documentId"):
        value = params.get(key)
        if isinstance(value, str):
            payload[key] = value
    for key in ("variables", "extensions"):
        value = params.get(key)
        if isinstance(value, str) and value:
            try:
                payload[key] = jsonlib.loads(value)
            except ValueError as exc:
                raise GraphQLError(
                    f"`{key}` is not valid JSON", code=ErrorCode.BAD_USER_INPUT
                ) from exc
        elif isinstance(value, dict):
            payload[key] = value
    return payload


def _attach(
    payload: dict[str, typing.Any],
    paths: dict[str, typing.Any],
    files: typing.Mapping[str, typing.Any],
    uploads: typing.Any,
) -> None:
    """Put uploaded files where ``map`` says they belong in the variables.

    Limits are checked here rather than after: a request over the file count
    should be refused before its contents are walked.
    """
    if len(paths) > uploads.max_files:
        raise GraphQLError(
            f"{len(paths)} files, over the limit of {uploads.max_files}",
            code=ErrorCode.BAD_USER_INPUT,
        )

    total = 0
    for name, targets in paths.items():
        upload = files.get(name)
        if upload is None:
            raise GraphQLError(
                f"`map` refers to file {name!r}, which the request does not carry",
                code=ErrorCode.BAD_USER_INPUT,
            )

        size = _size_of(upload)
        if size > uploads.max_size_bytes:
            raise GraphQLError(
                f"File {name!r} is larger than the limit of "
                f"{uploads.max_size_bytes} bytes",
                code=ErrorCode.BAD_USER_INPUT,
            )
        total += size
        if total > uploads.max_total_bytes:
            raise GraphQLError(
                f"Uploads total more than the limit of {uploads.max_total_bytes} bytes",
                code=ErrorCode.BAD_USER_INPUT,
            )

        content_type = getattr(upload, "content_type", None)
        if not uploads.allows(content_type):
            raise GraphQLError(
                f"File {name!r} is {content_type or 'of unknown type'}, which "
                f"this endpoint does not accept",
                code=ErrorCode.BAD_USER_INPUT,
            )

        if not isinstance(targets, list):
            raise GraphQLError(
                f"`map` entry {name!r} must be a list of variable paths",
                code=ErrorCode.BAD_USER_INPUT,
            )
        for path in targets:
            _place(payload, str(path), upload)


def _place(payload: dict[str, typing.Any], path: str, value: typing.Any) -> None:
    """Set ``variables.input.file`` — a dotted path, list indices included."""
    parts = path.split(".")
    cursor: typing.Any = payload
    for part in parts[:-1]:
        try:
            cursor = cursor[int(part)] if part.isdigit() else cursor[part]
        except (KeyError, IndexError, TypeError) as exc:
            raise GraphQLError(
                f"`map` points at {path!r}, which the operation does not have",
                code=ErrorCode.BAD_USER_INPUT,
            ) from exc
    last = parts[-1]
    try:
        if last.isdigit() and isinstance(cursor, list):
            cursor[int(last)] = value
        else:
            cursor[last] = value
    except (IndexError, TypeError) as exc:
        raise GraphQLError(
            f"`map` points at {path!r}, which the operation does not have",
            code=ErrorCode.BAD_USER_INPUT,
        ) from exc
