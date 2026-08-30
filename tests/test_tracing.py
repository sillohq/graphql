"""``sillo_graphql.tracing`` — the observation hooks."""

from __future__ import annotations

import logging
import time

from sillo_graphql.context import GraphContext
from sillo_graphql.graph import Result
from sillo_graphql.tracing import ANONYMOUS, Metrics, OperationLog, opentelemetry


def context(name="Read", cost=12, age=0.0):
    ctx = GraphContext(operation_name=name)
    ctx.cost = cost
    ctx.started = time.perf_counter() - age
    return ctx
