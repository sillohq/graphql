"""Static analysis of a document, before a resolver runs.

A GraphQL endpoint publishes a graph, and a graph with a cycle in it publishes
unbounded work behind a very small request. ``{ post { author { posts {
author { ... } } } } }`` is a handful of bytes and can be a table scan per
level. Rate limiting by request count does not help: the expensive request and
the cheap one both count as one.

So the document is measured first, and refused before execution if it is too
large. Refusing afterwards would mean having already done the work.

Four structural measures — depth, aliases of one field, breadth of a selection
set, and document size — plus a weighted cost that understands lists: a field
returning a list multiplies the cost of everything under it, by the page size
the caller asked for when that is knowable and by
:attr:`~sillo_graphql.policy.Limits.list_multiplier` when it is not.
"""

from __future__ import annotations

import dataclasses
import typing

from graphql import GraphQLList, GraphQLNonNull
from graphql.language import (
    DocumentNode,
    FieldNode,
    FragmentDefinitionNode,
    FragmentSpreadNode,
    InlineFragmentNode,
    IntValueNode,
    OperationDefinitionNode,
    SelectionSetNode,
    VariableNode,
)

from sillo_graphql.errors import ErrorCode, GraphQLError
from sillo_graphql.policy import Limits

if typing.TYPE_CHECKING:
    from graphql import GraphQLSchema

__all__ = ["Analysis", "analyze", "enforce"]

#: Arguments that name a page size. A field taking one of these is being asked
#: for that many rows, which is a far better multiplier than a guess.
PAGE_ARGS = ("first", "last", "limit", "take", "page_size", "pageSize")


@dataclasses.dataclass(frozen=True, slots=True)
class Analysis:
    """What a document was measured to be.

    Attributes:
        depth: Deepest field nesting; a root field alone is depth 1.
        cost: Weighted complexity, list multipliers applied.
        aliases: Most aliases of any single field.
        breadth: Largest selection set.
        fields: Total field selections, fragments expanded.
    """

    depth: int = 0
    cost: int = 0
    aliases: int = 0
    breadth: int = 0
    fields: int = 0

    def as_extensions(self) -> dict[str, int]:
        """The shape reported under ``extensions.cost``."""
        return {
            "depth": self.depth,
            "cost": self.cost,
            "aliases": self.aliases,
            "breadth": self.breadth,
            "fields": self.fields,
        }


class _TooLarge(GraphQLError):
    """Internal: raised the moment a limit is passed, to stop walking."""

    def __init__(self, message: str, **extensions: typing.Any) -> None:
        super().__init__(
            message, code=ErrorCode.OPERATION_TOO_COMPLEX, extensions=extensions
        )


class _Analyzer:
    """One walk of one operation.

    Recursive rather than a graphql-core visitor because depth, list
    multipliers and fragment expansion all need the path down from the root,
    and a flat visitor would have to rebuild it at every node.
    """

    def __init__(
        self,
        document: DocumentNode,
        *,
        limits: Limits,
        schema: GraphQLSchema | None = None,
        variables: dict[str, typing.Any] | None = None,
        costs: dict[str, int] | None = None,
    ) -> None:
        self.limits = limits
        self.schema = schema
        self.variables = variables or {}
        self.costs = costs or {}
        self.fragments: dict[str, FragmentDefinitionNode] = {
            definition.name.value: definition
            for definition in document.definitions
            if isinstance(definition, FragmentDefinitionNode)
        }
        self.depth = 0
        self.cost = 0
        self.aliases = 0
        self.breadth = 0
        self.fields = 0

    def run(self, operation: OperationDefinitionNode) -> Analysis:
        root = self._root_type(operation)
        self._walk(operation.selection_set, depth=0, multiplier=1, parent=root, seen=())
        return Analysis(
            depth=self.depth,
            cost=self.cost,
            aliases=self.aliases,
            breadth=self.breadth,
            fields=self.fields,
        )

    def _root_type(self, operation: OperationDefinitionNode) -> typing.Any:
        if self.schema is None:
            return None
        return {
            "query": self.schema.query_type,
            "mutation": self.schema.mutation_type,
            "subscription": self.schema.subscription_type,
        }.get(operation.operation.value)

    def _walk(
        self,
        selection_set: SelectionSetNode,
        *,
        depth: int,
        multiplier: int,
        parent: typing.Any,
        seen: tuple[str, ...],
    ) -> None:
        """Measure one selection set and everything beneath it.

        *seen* carries the fragment names already expanded on this path.
        graphql-core rejects fragment cycles, but its validation runs after
        this does — a cyclic document must not be able to hang the analyzer
        that exists to stop expensive documents.
        """
        if depth >= self.limits.depth:
            raise _TooLarge(
                f"Operation is deeper than the limit of {self.limits.depth}",
                limit=self.limits.depth,
            )

        here = depth + 1
        self.depth = max(self.depth, here)

        selections = list(selection_set.selections)
        width = sum(1 for node in selections if isinstance(node, FieldNode))
        if width > self.limits.breadth:
            raise _TooLarge(
                f"A selection set asks for {width} fields, over the limit of "
                f"{self.limits.breadth}",
                limit=self.limits.breadth,
            )
        self.breadth = max(self.breadth, width)

        # Aliasing multiplies work without adding depth, so it is counted per
        # selection set rather than per document: ten aliases here and ten
        # there is not the same thing as twenty of one field.
        by_name: dict[str, int] = {}

        for node in selections:
            if isinstance(node, FieldNode):
                name = node.name.value
                by_name[name] = by_name.get(name, 0) + 1
                self._field(
                    node, depth=here, multiplier=multiplier, parent=parent, seen=seen
                )
            elif isinstance(node, InlineFragmentNode):
                self._walk(
                    node.selection_set,
                    depth=depth,
                    multiplier=multiplier,
                    parent=self._condition_type(node, parent),
                    seen=seen,
                )
            elif isinstance(node, FragmentSpreadNode):
                self._spread(
                    node, depth=depth, multiplier=multiplier, parent=parent, seen=seen
                )

        for name, count in by_name.items():
            if count > self.limits.aliases:
                raise _TooLarge(
                    f"Field '{name}' is selected {count} times, over the alias "
                    f"limit of {self.limits.aliases}",
                    limit=self.limits.aliases,
                    field=name,
                )
            self.aliases = max(self.aliases, count)

    def _spread(
        self,
        node: FragmentSpreadNode,
        *,
        depth: int,
        multiplier: int,
        parent: typing.Any,
        seen: tuple[str, ...],
    ) -> None:
        name = node.name.value
        if name in seen:
            # A cycle. Stop rather than raise: the document is invalid and
            # graphql-core will say so precisely, in its own words.
            return
        fragment = self.fragments.get(name)
        if fragment is None:
            return
        self._walk(
            fragment.selection_set,
            depth=depth,
            multiplier=multiplier,
            parent=self._condition_type(fragment, parent),
            seen=(*seen, name),
        )

    def _field(
        self,
        node: FieldNode,
        *,
        depth: int,
        multiplier: int,
        parent: typing.Any,
        seen: tuple[str, ...],
    ) -> None:
        name = node.name.value
        self.fields += 1

        # Introspection meta-fields are answered from the schema in memory and
        # cost nothing worth counting.
        if name.startswith("__"):
            return

        definition = self._field_def(parent, name)
        self.cost += multiplier * self._field_cost(parent, name)
        if self.cost > (self.limits.cost or self.cost):
            raise _TooLarge(
                f"Operation costs at least {self.cost}, over the limit of "
                f"{self.limits.cost}",
                limit=self.limits.cost,
                cost=self.cost,
            )

        if node.selection_set is None:
            return

        child_multiplier = multiplier
        if definition is None or _is_list(definition.type):
            child_multiplier = multiplier * self._page_size(node)

        self._walk(
            node.selection_set,
            depth=depth,
            multiplier=child_multiplier,
            parent=_named_type(definition.type) if definition is not None else None,
            seen=seen,
        )

    def _field_cost(self, parent: typing.Any, name: str) -> int:
        """What one selection of this field costs.

        Looked up by ``Type.field`` first so two types can price a field of
        the same name differently, then by bare name, then the default.
        """
        if parent is not None:
            qualified = f"{parent.name}.{name}"
            if qualified in self.costs:
                return self.costs[qualified]
        if name in self.costs:
            return self.costs[name]
        return self.limits.default_field_cost

    def _page_size(self, node: FieldNode) -> int:
        """How many rows this field was asked for.

        A caller asking for 5 should not be charged for 100. Only integer
        literals and integer variables count; anything else falls back to the
        configured multiplier, which is the safe direction to be wrong in.
        """
        for argument in node.arguments:
            if argument.name.value not in PAGE_ARGS:
                continue
            value = argument.value
            if isinstance(value, IntValueNode):
                return max(1, int(value.value))
            if isinstance(value, VariableNode):
                supplied = self.variables.get(value.name.value)
                if isinstance(supplied, int) and not isinstance(supplied, bool):
                    return max(1, supplied)
        return self.limits.list_multiplier

    def _field_def(self, parent: typing.Any, name: str) -> typing.Any:
        if parent is None:
            return None
        fields = getattr(parent, "fields", None)
        if not fields:
            return None
        return fields.get(name)

    def _condition_type(self, node: typing.Any, parent: typing.Any) -> typing.Any:
        """The type a fragment narrows to, or *parent* when it does not."""
        if self.schema is None or node.type_condition is None:
            return parent
        return self.schema.get_type(node.type_condition.name.value) or parent


def _is_list(type_: typing.Any) -> bool:
    """Whether a field's type is a list, through any non-null wrappers."""
    while isinstance(type_, GraphQLNonNull):
        type_ = type_.of_type
    return isinstance(type_, GraphQLList)


def _named_type(type_: typing.Any) -> typing.Any:
    """Unwrap list and non-null wrappers down to the named type."""
    while isinstance(type_, GraphQLList | GraphQLNonNull):
        type_ = type_.of_type
    return type_


def analyze(
    document: DocumentNode,
    *,
    limits: Limits,
    schema: GraphQLSchema | None = None,
    operation_name: str | None = None,
    variables: dict[str, typing.Any] | None = None,
    costs: dict[str, int] | None = None,
) -> Analysis:
    """Measure a document without enforcing anything.

    Every operation in the document is measured and the largest of each
    measure returned, unless *operation_name* names one.

    Passing *schema* buys accuracy: without it, every field with a selection
    set is treated as a list, because the analyzer cannot tell.
    """
    analyzer = _Analyzer(
        document, limits=limits, schema=schema, variables=variables, costs=costs
    )
    worst = Analysis()
    for definition in document.definitions:
        if not isinstance(definition, OperationDefinitionNode):
            continue
        if operation_name is not None and (
            definition.name is None or definition.name.value != operation_name
        ):
            continue
        analyzer.depth = analyzer.cost = 0
        analyzer.aliases = analyzer.breadth = analyzer.fields = 0
        result = analyzer.run(definition)
        worst = Analysis(
            depth=max(worst.depth, result.depth),
            cost=max(worst.cost, result.cost),
            aliases=max(worst.aliases, result.aliases),
            breadth=max(worst.breadth, result.breadth),
            fields=max(worst.fields, result.fields),
        )
    return worst


def enforce(
    document: DocumentNode,
    *,
    limits: Limits,
    schema: GraphQLSchema | None = None,
    operation_name: str | None = None,
    variables: dict[str, typing.Any] | None = None,
    costs: dict[str, int] | None = None,
) -> Analysis:
    """Measure a document and raise if it is over any limit.

    Raises:
        GraphQLError: with code ``OPERATION_TOO_COMPLEX``, naming the limit
            that was passed and what it is — a client that is refused should
            be able to fix its query without guessing.
    """
    return analyze(
        document,
        limits=limits,
        schema=schema,
        operation_name=operation_name,
        variables=variables,
        costs=costs,
    )
