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


@dataclasses.dataclass(frozen=True, slots=True)
class Transport:
    """Which parts of the GraphQL-over-HTTP surface are served.

    Attributes:
        get_queries: Accept queries over ``GET``. Mutations are refused on
            ``GET`` whatever this says — the method is meant to be safe.
        batch: Maximum operations in a batched request; ``0`` refuses batches.
            A batch is a work multiplier that skips per-request limits, so it
            is capped rather than merely allowed.
        graphql_content_type: Accept ``application/graphql`` bodies, where the
            whole body is the document.
        response_content_type: Answer with ``application/graphql-response+json``
            when the client asks for it, which also selects the spec's status
            codes rather than the legacy always-200 behaviour.
        max_body: Largest accepted request body.
    """

    get_queries: bool = True
    batch: int = 10
    graphql_content_type: bool = True
    response_content_type: bool = True
    max_body: int | str = "1MB"

    def __post_init__(self) -> None:
        if self.batch < 0:
            raise ValueError("Transport.batch cannot be negative")
        # Validate eagerly, so a typo is a configuration error at import time
        # rather than a 500 on the first large upload.
        parse_size(self.max_body)

    @property
    def max_body_bytes(self) -> int:
        """``max_body`` in bytes."""
        return parse_size(self.max_body)


@dataclasses.dataclass(frozen=True, slots=True)
class Uploads:
    """Multipart file uploads, per the GraphQL multipart request spec.

    Disabled unless ``enabled`` is set: an endpoint that accepts files has a
    materially larger attack surface than one that does not, and that should
    be a decision rather than a default.

    Attributes:
        enabled: Whether ``multipart/form-data`` is accepted at all.
        max_size: Largest single file.
        max_files: Most files in one request.
        max_total: Largest total across all files in one request.
        content_types: Allowed media types; ``None`` allows any. Globs of the
            form ``image/*`` are understood.
        storage: Name of the ``sillo.storage`` disk to stream into. ``None``
            hands the resolver the stream and stores nothing.
    """

    enabled: bool = False
    max_size: int | str = "10MB"
    max_files: int = 10
    max_total: int | str = "50MB"
    content_types: tuple[str, ...] | None = None
    storage: str | None = None

    def __post_init__(self) -> None:
        if self.max_files < 1:
            raise ValueError("Uploads.max_files must be at least 1")
        parse_size(self.max_size)
        parse_size(self.max_total)

    @property
    def max_size_bytes(self) -> int:
        """``max_size`` in bytes."""
        return parse_size(self.max_size)

    @property
    def max_total_bytes(self) -> int:
        """``max_total`` in bytes."""
        return parse_size(self.max_total)

    def allows(self, content_type: str | None) -> bool:
        """Whether a file of this media type may be accepted."""
        if self.content_types is None:
            return True
        if content_type is None:
            return False
        # Parameters are not part of the match: `image/png; charset=binary`
        # is an image/png.
        media = content_type.split(";", 1)[0].strip().lower()
        for allowed in self.content_types:
            allowed = allowed.strip().lower()
            if allowed.endswith("/*"):
                if media.startswith(allowed[:-1]):
                    return True
            elif media == allowed:
                return True
        return False


@dataclasses.dataclass(frozen=True, slots=True)
class Persisted:
    """Persisted operations: APQ, and the stronger trusted-document mode.

    Attributes:
        apq: Automatic persisted queries. A client sends a hash; on a miss it
            is told to send the document once, and the hash works from then
            on. Saves bandwidth, and nothing else — any document is still
            accepted.
        trusted: Path to a manifest of allowed documents, keyed by hash. When
            set, *only* those documents execute and arbitrary queries are
            refused. This is what makes a public endpoint's workload finite,
            and it is what makes GET responses safe to cache.
        cache: Name of the ``sillo.cache`` store holding APQ entries.
        ttl: Seconds an APQ entry is kept.
    """

    apq: bool = False
    trusted: str | dict[str, str] | None = None
    cache: str | None = None
    ttl: int = 60 * 60 * 24

    def __post_init__(self) -> None:
        if self.ttl < 1:
            raise ValueError("Persisted.ttl must be at least 1 second")

    @property
    def enabled(self) -> bool:
        """Whether either mode is in use."""
        return self.apq or self.trusted is not None
