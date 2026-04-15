from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import logfire_api
from pydantic import TypeAdapter
from pydantic_evals.evaluators import EvaluationResult
from pydantic_evals.reporting import EvaluationReport, ReportCase, ReportCaseAggregate

_logfire = logfire_api.Logfire(otel_scope="pytest-pyeval")

_evaluation_results_adapter: TypeAdapter[Mapping[str, EvaluationResult]] = TypeAdapter(
    Mapping[str, EvaluationResult]
)


def send_report(report: EvaluationReport) -> None:
    """Send an EvaluationReport to Logfire as a span hierarchy.

    Creates an experiment-level span containing a child span per case,
    mirroring the span structure produced by pydantic-evals' ``Dataset.evaluate()``.

    Spans are no-ops when Logfire is not configured.
    """
    if not report.cases and not report.failures:
        return

    n_cases = len(report.cases) + len(report.failures)

    with _logfire.span(
        "evaluate {name}",
        name=report.name,
        n_cases=n_cases,
    ) as experiment_span:
        experiment_span.set_attribute("gen_ai.operation.name", "experiment")
        for case in report.cases:
            _send_case(case)

        averages = ReportCaseAggregate.average(report.cases)
        if averages.assertions is not None:
            experiment_span.set_attribute("assertion_pass_rate", averages.assertions)

        full_metadata: dict[str, Any] = {
            "n_cases": n_cases,
            "averages": averages.model_dump(),
        }
        experiment_span.set_attribute("logfire.experiment.metadata", full_metadata)


def _send_case(case: ReportCase) -> None:
    case_attrs: dict[str, Any] = {"inputs": case.inputs}
    if case.metadata is not None:
        case_attrs["metadata"] = case.metadata
    if case.expected_output is not None:
        case_attrs["expected_output"] = case.expected_output

    with _logfire.span(
        "case: {case_name}", case_name=case.name, **case_attrs
    ) as case_span:
        if case.output is not None:
            case_span.set_attribute("output", case.output)
        case_span.set_attribute("task_duration", case.task_duration)
        if case.metrics:
            case_span.set_attribute("metrics", case.metrics)
        if case.attributes:
            case_span.set_attribute("attributes", case.attributes)
        if case.assertions:
            case_span.set_attribute(
                "assertions",
                _evaluation_results_adapter.dump_python(case.assertions),
            )
        if case.scores:
            case_span.set_attribute(
                "scores",
                _evaluation_results_adapter.dump_python(case.scores),
            )
        if case.labels:
            case_span.set_attribute(
                "labels",
                _evaluation_results_adapter.dump_python(case.labels),
            )
