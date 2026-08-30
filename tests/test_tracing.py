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
