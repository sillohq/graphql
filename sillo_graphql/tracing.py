"""Knowing what the endpoint is doing.

One GraphQL path carries every operation an application performs, so the usual
HTTP signals say almost nothing: p99 on ``POST /graphql`` is an average over
work that has nothing in common. What is worth measuring is per *operation* —
which one ran, how long it took, what it cost, whether it failed.

Everything here is a hook for ``@graph.on_operation``, so none of it is on by
default and none of it is in the request path unless it was asked for::

    graph.on_operation(OperationLog(slower_than=0.5))
    metrics = Metrics()
    graph.on_operation(metrics)
"""

from __future__ import annotations

import dataclasses
import logging
import time
import typing

if typing.TYPE_CHECKING:
    from sillo_graphql.context import GraphContext
    from sillo_graphql.graph import Result

__all__ = ["Metrics", "OperationLog", "OperationStats", "opentelemetry"]

LOGGER = logging.getLogger("sillo.graphql.operations")

#: What an unnamed operation is filed under. Anonymous operations are common
#: in development and rare in a client that has been through a build step, so
#: they are worth being able to see as a group.
ANONYMOUS = "anonymous"


def _name(context: GraphContext) -> str:
    return context.operation_name or ANONYMOUS


def _elapsed(context: GraphContext) -> float:
    return time.perf_counter() - context.started


class OperationLog:
    """Log operations, or only the slow ones.

    Args:
        logger: Where to write. Defaults to ``sillo.graphql.operations``.
        slower_than: Only log operations taking at least this many seconds.
            ``0`` logs everything, which is what a development log wants and a
            production one does not.
        errors: Always log an operation that produced errors, however fast.
    """

    def __init__(
        self,
        logger: logging.Logger | None = None,
        *,
        slower_than: float = 0.0,
        errors: bool = True,
    ) -> None:
        self.logger = logger or LOGGER
        self.slower_than = slower_than
        self.errors = errors

    def __call__(self, result: Result, context: GraphContext) -> None:
        elapsed = _elapsed(context)
        failed = bool(result.errors)
        if elapsed < self.slower_than and not (failed and self.errors):
            return
        self.logger.log(
            logging.WARNING if failed else logging.INFO,
            "graphql %s %.1fms cost=%s errors=%d",
            _name(context),
            elapsed * 1000,
            context.cost if context.cost is not None else "-",
            len(result.errors),
        )


@dataclasses.dataclass
class OperationStats:
    """What has been seen of one operation.

    Durations are kept as a running total rather than a list: an endpoint
    serving a few hundred operations a second would otherwise accumulate an
    unbounded amount of memory in the name of observing itself.
    """

    count: int = 0
    errors: int = 0
    total_seconds: float = 0.0
    slowest: float = 0.0
    total_cost: int = 0

    @property
    def average(self) -> float:
        """Mean duration in seconds, or ``0.0`` before anything has run."""
        return self.total_seconds / self.count if self.count else 0.0

    def as_dict(self) -> dict[str, float]:
        """A plain mapping, for whatever this is being exported into."""
        return {
            "count": self.count,
            "errors": self.errors,
            "average_seconds": self.average,
            "slowest_seconds": self.slowest,
            "average_cost": self.total_cost / self.count if self.count else 0.0,
        }


class Metrics:
    """Per-operation counters, held in memory.

    Deliberately not a Prometheus client, a StatsD client, or anything else
    with a wire format: this collects, and an application exports it however
    it already exports things::

        @app.get("/metrics")
        async def show(ctx):
            return json(metrics.snapshot())
    """

    def __init__(self) -> None:
        self.operations: dict[str, OperationStats] = {}

    def __call__(self, result: Result, context: GraphContext) -> None:
        stats = self.operations.setdefault(_name(context), OperationStats())
        elapsed = _elapsed(context)
        stats.count += 1
        stats.total_seconds += elapsed
        stats.slowest = max(stats.slowest, elapsed)
        stats.total_cost += context.cost or 0
        if result.errors:
            stats.errors += 1

    def snapshot(self) -> dict[str, dict[str, float]]:
        """Everything counted so far."""
        return {name: stats.as_dict() for name, stats in self.operations.items()}

    def reset(self) -> None:
        """Forget everything counted so far."""
        self.operations.clear()


def opentelemetry(tracer: typing.Any) -> typing.Callable[..., None]:
    """A hook that records each operation as a span.

    The span is created after the fact, with an explicit start time taken from
    the context — the hook runs when the operation finishes, and back-dating
    the span is what keeps its duration honest rather than zero.

    Args:
        tracer: An OpenTelemetry ``Tracer``. Not imported here; this package
            does not depend on OpenTelemetry, and an application that uses it
            already has one to hand.
    """

    def observe(result: Result, context: GraphContext) -> None:
        elapsed = _elapsed(context)
        end = time.time_ns()
        span = tracer.start_span(
            f"graphql {_name(context)}",
            start_time=end - int(elapsed * 1_000_000_000),
        )
        span.set_attribute("graphql.operation.name", _name(context))
        span.set_attribute("graphql.errors", len(result.errors))
        if context.cost is not None:
            span.set_attribute("graphql.cost", context.cost)
        span.end(end_time=end)

    return observe
