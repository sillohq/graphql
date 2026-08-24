"""Resolvers that read like ``sillo`` handlers.

A route handler in ``sillo`` takes the context first and declares whatever else
it needs::

    @app.get("/me")
    async def me(ctx: HttpContext, db=Depend(get_db)):
        ...

A resolver here is the same thing::

    @strawberry.type
    class Query:
        @field
        async def me(ctx: HttpContext, db=Depend(get_db)) -> User:
            ...

The rule is one sentence: **``ctx`` and anything defaulted to ``Depend`` are
injected and do not appear in the schema; every other parameter is a GraphQL
argument.**

Strawberry derives a field's arguments from its resolver's signature, so the
injected parameters have to be gone by the time it looks. The decorator builds
a wrapper carrying a synthesized ``__signature__`` with only the exposed
arguments, plus ``root`` and ``info`` — which Strawberry recognises and keeps
out of the schema — and fills the rest in at call time. That is the same trick
``sillo``'s own router plays when it inspects a handler before dispatch.
"""

from __future__ import annotations

import functools
import inspect
import typing

import strawberry

from sillo_graphql.errors import ErrorCode, GraphQLDenied, SilloGraphQLError

if typing.TYPE_CHECKING:
    from sillo_graphql.context import GraphContext

__all__ = ["ResolverError", "field", "mutation", "resolver_costs", "subscription"]

#: Parameter names Strawberry already treats as the parent object.
ROOT_NAMES = frozenset({"root", "self", "parent"})

#: Annotations that mean "the connection's own context". Compared as strings
#: because ``from __future__ import annotations`` makes every annotation one,
#: and because importing them here would drag the framework into this module.
CONTEXT_ANNOTATIONS = frozenset(
    {
        "HttpContext",
        "WebSocketContext",
        "BaseContext",
        "Context",
    }
)

#: Annotations that mean the whole :class:`~sillo_graphql.context.GraphContext`.
GRAPH_CONTEXT_ANNOTATIONS = frozenset({"GraphContext"})

#: Parameter names that mean the context when nothing is annotated.
CONTEXT_NAMES = frozenset({"ctx", "context"})

#: Per-field costs registered by ``@field(cost=...)``, keyed by field name.
#: Read by :class:`~sillo_graphql.graph.Graph` when it builds its cost table.
_COSTS: dict[str, int] = {}


class ResolverError(SilloGraphQLError):
    """A resolver could not be adapted."""


def resolver_costs() -> dict[str, int]:
    """Every cost declared with ``@field(cost=...)`` so far."""
    return dict(_COSTS)


class _Injection(typing.NamedTuple):
    """One parameter this package fills in rather than the client."""

    name: str
    kind: str  # "ctx" | "graph" | "root" | "info" | "depend"


def _annotation_name(annotation: typing.Any) -> str:
    """The bare name of an annotation, however it was written.

    ``HttpContext``, ``"HttpContext"``, ``sillo.core.http.HttpContext`` and
    ``HttpContext | None`` all have to answer the same, because a resolver
    author writes whichever of those reads best.
    """
    if annotation is inspect.Parameter.empty:
        return ""
    if isinstance(annotation, str):
        text = annotation
    else:
        text = getattr(annotation, "__name__", None) or str(annotation)
    # Strip a module path, optional wrapper and subscript: the last identifier
    # is the one that names the type.
    text = text.replace("Optional[", "").rstrip("]")
    text = text.split("|")[0].strip()
    return text.rsplit(".", 1)[-1].strip("\"' ")


def _split(
    fn: typing.Callable[..., typing.Any],
) -> tuple[list[_Injection], list[inspect.Parameter], dict[str, typing.Any]]:
    """Sort a resolver's parameters into injected and exposed.

    Returns the injections, the parameters Strawberry should see, and the
    ``Depend`` markers keyed by parameter name.
    """
    from sillo import Depend

    signature = inspect.signature(fn)
    injections: list[_Injection] = []
    exposed: list[inspect.Parameter] = []
    depends: dict[str, typing.Any] = {}

    for parameter in signature.parameters.values():
        name = parameter.name
        annotation = _annotation_name(parameter.annotation)

        if isinstance(parameter.default, Depend):
            injections.append(_Injection(name, "depend"))
            depends[name] = parameter.default
        elif name in ROOT_NAMES:
            injections.append(_Injection(name, "root"))
        elif annotation == "Info":
            injections.append(_Injection(name, "info"))
        elif annotation in GRAPH_CONTEXT_ANNOTATIONS:
            injections.append(_Injection(name, "graph"))
        elif annotation in CONTEXT_ANNOTATIONS or (
            not annotation and name in CONTEXT_NAMES
        ):
            injections.append(_Injection(name, "ctx"))
        elif parameter.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            raise ResolverError(
                f"{fn.__name__} declares {parameter}, and GraphQL arguments are "
                f"a fixed list — name each argument the field accepts."
            )
        else:
            if parameter.annotation is inspect.Parameter.empty:
                raise ResolverError(
                    f"argument '{name}' of {fn.__name__} has no annotation. "
                    f"GraphQL needs a type for every argument; annotate it, or "
                    f"give it a Depend default if it is not one."
                )
            exposed.append(parameter)

    return injections, exposed, depends
