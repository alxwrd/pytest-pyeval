from __future__ import annotations

import inspect
import time
import traceback

import pytest
from pydantic_evals import Case
from pydantic_evals.evaluators import EvaluatorFailure
from pydantic_evals.reporting import EvaluationReport, ReportCase, ReportCaseFailure

from ._core import (
    _CURRENT_EVAL_RESULTS,
    _CURRENT_EXECUTION_RESULT,
    _group_by_type,
)

_RESET = "\033[0m"

_SCORE_BANDS: list[tuple[float, str, str]] = [
    (0.9, "●", "\033[92m"),  # bright green
    (0.7, "◕", "\033[32m"),  # green
    (0.5, "◑", "\033[33m"),  # yellow
    (0.3, "◔", "\033[31m"),  # red
    (0.0, "○", "\033[91m"),  # bright red
]


def _score_symbol(score: float) -> tuple[str, str]:
    for threshold, symbol, color in _SCORE_BANDS:
        if score >= threshold:
            return symbol, color
    raise ValueError(f"Score {score!r} did not match any band (expected a value >= 0.0)")


def pytest_configure(config) -> None:
    config.addinivalue_line("python_files", "eval_*.py")


def pytest_report_teststatus(report, config):
    if report.when != "call":
        return None
    for key, value in report.user_properties:
        if key == "eval_status":
            symbol, color, icons = value
            return ("evaluated", f"{color}{symbol}{_RESET}", icons)
    return None


def pytest_pycollect_makeitem(collector, name: str, obj: object):
    if not (callable(obj) and name.startswith("eval_")):
        return None

    if getattr(obj, "_pytestfixturefunction", None) is not None:
        return None

    if getattr(obj, "__eval__", True) is False:
        return None

    if (collector_path := getattr(collector, "path", None)) is None:
        return None

    if not str(collector_path.name).startswith("eval_"):
        return None

    cases = getattr(obj, "__eval_cases__", None)
    if cases is None:
        return None

    return EvalCollector.from_parent(collector, name=name, func=obj, cases=cases)


class EvalCollector(pytest.Collector):
    def __init__(self, name: str, parent, func, cases: tuple[Case, ...]):
        super().__init__(name, parent)
        self.func = func
        self.cases = cases

    def collect(self):
        for i, case in enumerate(self.cases, 1):
            item_name = case.name or f"case_{i}"
            yield EvalItem.from_parent(self, name=item_name, func=self.func, case=case)

    def teardown(self):
        report_cases: list[ReportCase] = []
        report_failures: list[ReportCaseFailure] = []

        for item in self.session.items:
            if item.parent is not self:
                continue
            if item._report_case is not None:
                report_cases.append(item._report_case)
            elif item._report_failure is not None:
                report_failures.append(item._report_failure)

        if not report_cases and not report_failures:
            return

        report = EvaluationReport(
            name=self.func.__name__,
            cases=report_cases,
            failures=report_failures,
        )
        report.print()


class EvalItem(pytest.Item):
    def __init__(self, name: str, parent, func, case: Case):
        super().__init__(name, parent)
        self.func = func
        self.case = case
        self._report_case: ReportCase | None = None
        self._report_failure: ReportCaseFailure | None = None

        sig = inspect.signature(func)
        self.fixturenames = [p for p in sig.parameters if p != "case"]

    def runtest(self):
        fixtures = {
            name: self._request.getfixturevalue(name) for name in self.fixturenames
        }

        results: list = []
        results_token = _CURRENT_EVAL_RESULTS.set(results)
        execution_token = _CURRENT_EXECUTION_RESULT.set(None)

        t0 = time.perf_counter()
        try:
            self.func(case=self.case, **fixtures)
        except Exception as exc:
            self._report_failure = ReportCaseFailure(
                name=self.name,
                inputs=self.case.inputs,
                metadata=self.case.metadata,
                expected_output=self.case.expected_output,
                error_message=f"{type(exc).__name__}: {exc}",
                error_stacktrace=traceback.format_exc(),
            )
            raise
        finally:
            results = _CURRENT_EVAL_RESULTS.get() or []
            execution_result = _CURRENT_EXECUTION_RESULT.get()
            _CURRENT_EVAL_RESULTS.reset(results_token)
            _CURRENT_EXECUTION_RESULT.reset(execution_token)

        total_duration = time.perf_counter() - t0
        assertions, scores, labels = _group_by_type(results)

        ctx = execution_result.ctx if execution_result is not None else None
        evaluator_failures: list[EvaluatorFailure] = (
            execution_result.failures if execution_result is not None else []
        )

        self._report_case = ReportCase(
            name=self.name,
            inputs=self.case.inputs,
            metadata=self.case.metadata,
            expected_output=self.case.expected_output,
            output=ctx.output if ctx else None,
            metrics=ctx.metrics if ctx else {},
            attributes=ctx.attributes if ctx else {},
            assertions=assertions,
            scores=scores,
            labels=labels,
            task_duration=ctx.duration if ctx else 0.0,
            total_duration=total_duration,
            evaluator_failures=evaluator_failures,
        )

        bool_results = list(assertions.values())
        score = (
            sum(1 for r in bool_results if r.value is True) / len(bool_results)
            if bool_results
            else 1.0
        )
        icons = "".join("✔" if r.value is True else "✗" for r in bool_results)
        symbol, color = _score_symbol(score)
        self.user_properties.append(("eval_status", (symbol, color, icons)))

    def reportinfo(self):
        return self.fspath, None, f"{self.parent.name}:{self.name}"
