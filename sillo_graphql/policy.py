"""The policy objects a :class:`~sillo_graphql.graph.Graph` is configured with.

Common knobs are plain keyword arguments on ``Graph``; the deeper ones are
grouped here, the same split ``sillo`` makes between arguments on ``SilloApp``
and objects like ``CSRFConfig``. Grouping matters more than usual in a GraphQL
endpoint, because "how large may a query be" is four numbers that only make
sense read together.

Every default is chosen for a public endpoint. A framework whose defaults are
safe only on a private network is a framework that ships incidents.
"""

from __future__ import annotations

import dataclasses
import re
import typing

__all__ = [
    "IDE",
    "ErrorPolicy",
    "Limits",
    "Persisted",
    "Transport",
    "Uploads",
    "parse_size",
]

_SIZE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([KMG]?B?)\s*$", re.IGNORECASE)
_UNITS = {"": 1, "B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}


def parse_size(value: int | str) -> int:
    """Bytes from ``10485760`` or from ``"10MB"``.

    Upload limits are read far more often than they are written, and a reader
    should not have to divide by 1024 twice to check one.
    """
    if isinstance(value, int):
        if value < 0:
            raise ValueError(f"size cannot be negative: {value}")
        return value

    match = _SIZE.match(value)
    if match is None:
        raise ValueError(f"cannot read {value!r} as a size, try '10MB'")

    amount, unit = match.groups()
    unit = unit.upper()
    if unit in ("K", "M", "G"):
        unit += "B"
    return int(float(amount) * _UNITS[unit])


@dataclasses.dataclass(frozen=True, slots=True)
class Limits:
    """How large an operation may be before it is refused.

    Checked statically, before execution: a query that would be too expensive
    is rejected without a single resolver running, which is the only point at
    which rejecting it still saves anything.

    Attributes:
        depth: Maximum nesting. A recursive type with no depth limit is an
            unbounded amount of work behind one small request.
        cost: Maximum weighted complexity. ``None`` disables cost analysis
            while leaving the structural limits in force.
        aliases: Maximum aliases of one field. Aliasing multiplies work
            without adding depth, so a depth limit alone does not cover it.
        breadth: Maximum selections in any one selection set.
        list_multiplier: Default multiplier for a list field with no explicit
            page argument, used when costing.
        max_tokens: Maximum document tokens, applied before parsing.
        default_field_cost: What a field costs when nothing says otherwise.
    """

    depth: int = 10
    cost: int | None = 1_000
    aliases: int = 15
    breadth: int = 100
    list_multiplier: int = 10
    max_tokens: int = 5_000
    default_field_cost: int = 1

    def __post_init__(self) -> None:
        for name in ("depth", "aliases", "breadth", "list_multiplier", "max_tokens"):
            if getattr(self, name) < 1:
                raise ValueError(f"Limits.{name} must be at least 1")
        if self.cost is not None and self.cost < 1:
            raise ValueError("Limits.cost must be at least 1, or None to disable")
        if self.default_field_cost < 0:
            raise ValueError("Limits.default_field_cost cannot be negative")

    @classmethod
    def none(cls) -> Limits:
        """Every limit relaxed. For a trusted internal endpoint, and only one."""
        return cls(
            depth=1_000,
            cost=None,
            aliases=1_000,
            breadth=10_000,
            max_tokens=1_000_000,
        )


@dataclasses.dataclass(frozen=True, slots=True)
class ErrorPolicy:
    """What a client is told when something goes wrong.

    Attributes:
        mask: Replace unexpected exceptions with ``mask_message``. Errors
            raised through :mod:`sillo_graphql.errors` are deliberate and pass
            through regardless — masking those would hide "not found" behind
            "unexpected error" and make the API unusable.
        mask_message: What a masked error says.
        include_stacktrace: Attach the traceback to ``extensions.stacktrace``.
            Development only; the guard is that it is off here and ``Graph``
            only turns it on when the application is in debug.
        correlation_key: Extension key carrying the request id, so a client
            report maps to a log line. ``None`` omits it.
        log_masked: Log the original exception when one is masked. Off means
            the failure is invisible in both directions, which is worse than
            noisy.
    """

    mask: bool = True
    mask_message: str = "Unexpected error"
    include_stacktrace: bool = False
    correlation_key: str | None = "requestId"
    log_masked: bool = True
