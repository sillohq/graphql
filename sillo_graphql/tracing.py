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
