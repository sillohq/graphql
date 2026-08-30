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


class TestOperationLog:
    def test_it_logs_every_operation_by_default(self, caplog):
        with caplog.at_level(logging.INFO, logger="sillo.graphql.operations"):
            OperationLog()(Result(data={}), context())
        assert "graphql Read" in caplog.text

    def test_a_fast_operation_is_skipped_when_a_threshold_is_set(self, caplog):
        with caplog.at_level(logging.INFO, logger="sillo.graphql.operations"):
            OperationLog(slower_than=10)(Result(data={}), context())
        assert caplog.text == ""

    def test_a_slow_operation_is_logged(self, caplog):
        with caplog.at_level(logging.INFO, logger="sillo.graphql.operations"):
            OperationLog(slower_than=0.01)(Result(data={}), context(age=1.0))
        assert "graphql Read" in caplog.text

    def test_a_failure_is_logged_however_fast_it_was(self, caplog):
        with caplog.at_level(logging.INFO, logger="sillo.graphql.operations"):
            OperationLog(slower_than=10)(Result(errors=[{"message": "x"}]), context())
        assert "errors=1" in caplog.text

    def test_that_can_be_switched_off(self, caplog):
        log = OperationLog(slower_than=10, errors=False)
        with caplog.at_level(logging.INFO, logger="sillo.graphql.operations"):
            log(Result(errors=[{"message": "x"}]), context())
        assert caplog.text == ""

    def test_a_failure_is_logged_as_a_warning(self, caplog):
        with caplog.at_level(logging.INFO, logger="sillo.graphql.operations"):
            OperationLog()(Result(errors=[{"message": "x"}]), context())
        assert caplog.records[0].levelno == logging.WARNING

    def test_an_unnamed_operation_is_filed_under_anonymous(self, caplog):
        with caplog.at_level(logging.INFO, logger="sillo.graphql.operations"):
            OperationLog()(Result(data={}), context(name=None))
        assert ANONYMOUS in caplog.text

    def test_an_unmeasured_cost_is_shown_as_a_dash(self, caplog):
        with caplog.at_level(logging.INFO, logger="sillo.graphql.operations"):
            OperationLog()(Result(data={}), context(cost=None))
        assert "cost=-" in caplog.text

    def test_a_logger_can_be_given(self, caplog):
        logger = logging.getLogger("my.app")
        with caplog.at_level(logging.INFO, logger="my.app"):
            OperationLog(logger)(Result(data={}), context())
        assert any(record.name == "my.app" for record in caplog.records)


class TestMetrics:
    def test_it_counts_per_operation(self):
        metrics = Metrics()
        metrics(Result(data={}), context("Read"))
        metrics(Result(data={}), context("Read"))
        metrics(Result(data={}), context("Write"))

        snapshot = metrics.snapshot()
        assert snapshot["Read"]["count"] == 2
        assert snapshot["Write"]["count"] == 1

    def test_errors_are_counted_separately(self):
        metrics = Metrics()
        metrics(Result(errors=[{"message": "x"}]), context())
        assert metrics.snapshot()["Read"]["errors"] == 1

    def test_the_slowest_is_remembered(self):
        metrics = Metrics()
        metrics(Result(data={}), context(age=0.5))
        metrics(Result(data={}), context(age=0.01))
        assert metrics.snapshot()["Read"]["slowest_seconds"] >= 0.5

    def test_the_average_cost_is_reported(self):
        metrics = Metrics()
        metrics(Result(data={}), context(cost=10))
        metrics(Result(data={}), context(cost=20))
        assert metrics.snapshot()["Read"]["average_cost"] == 15

    def test_an_unmeasured_cost_counts_as_nothing(self):
        metrics = Metrics()
        metrics(Result(data={}), context(cost=None))
        assert metrics.snapshot()["Read"]["average_cost"] == 0

    def test_an_empty_snapshot_is_empty(self):
        assert Metrics().snapshot() == {}

    def test_it_can_be_reset(self):
        metrics = Metrics()
        metrics(Result(data={}), context())
        metrics.reset()
        assert metrics.snapshot() == {}

    def test_a_stats_object_averages_nothing_before_anything_runs(self):
        from sillo_graphql.tracing import OperationStats

        assert OperationStats().average == 0.0
        assert OperationStats().as_dict()["average_cost"] == 0.0


class TestOpenTelemetry:
    def test_the_span_is_back_dated_so_its_duration_is_honest(self):
        spans = []

        class Span:
            def __init__(self, name, start_time):
                self.name, self.start_time = name, start_time
                self.attributes, self.end_time = {}, None

            def set_attribute(self, key, value):
                self.attributes[key] = value

            def end(self, end_time):
                self.end_time = end_time
                spans.append(self)

        class Tracer:
            def start_span(self, name, start_time):
                return Span(name, start_time)

        opentelemetry(Tracer())(Result(data={}), context(age=0.25))

        span = spans[0]
        assert span.name == "graphql Read"
        assert span.attributes["graphql.cost"] == 12
        assert span.attributes["graphql.errors"] == 0
        # A quarter of a second, in nanoseconds, allowing for scheduling.
        assert span.end_time - span.start_time >= 200_000_000

    def test_an_unmeasured_cost_is_left_off_the_span(self):
        spans = []

        class Span:
            def __init__(self):
                self.attributes = {}

            def set_attribute(self, key, value):
                self.attributes[key] = value

            def end(self, end_time):
                spans.append(self)

        class Tracer:
            def start_span(self, name, start_time):
                return Span()

        opentelemetry(Tracer())(Result(data={}), context(cost=None))
        assert "graphql.cost" not in spans[0].attributes
