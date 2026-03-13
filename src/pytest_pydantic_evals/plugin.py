from __future__ import annotations

import inspect
import time
import traceback
from typing import Any

import pytest
from pydantic_evals import Case
from pydantic_evals.evaluators import EvaluationResult, EvaluatorFailure
from pydantic_evals.reporting import EvaluationReport, ReportCase, ReportCaseFailure

from ._core import (
    _CURRENT_EVAL_RESULTS,
    _CURRENT_EXECUTION_RESULT,
    _group_by_type,
)


def pytest_configure(config) -> None:
    config.addinivalue_line("python_files", "eval_*.py")


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
            if hasattr(item, "_report_case") and item._report_case is not None:
                report_cases.append(item._report_case)
            elif hasattr(item, "_report_failure") and item._report_failure is not None:
                report_failures.append(item._report_failure)

        if not report_cases and not report_failures:
            return

        report = EvaluationReport(
            name=self.func.__name__,
            cases=report_cases,
            failures=report_failures,
        )
        report.print()


class EvalAssertionError(Exception):
    def __init__(self, results: list[EvaluationResult]):
        self.results = results
        super().__init__()


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

        results: list[EvaluationResult] = []
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

        # Gather evaluator failures from the ExecutionResult if one was produced
        evaluator_failures: list[EvaluatorFailure] = (
            execution_result.failures if execution_result is not None else []
        )

        self._report_case = ReportCase(
            name=self.name,
            inputs=self.case.inputs,
            metadata=self.case.metadata,
            expected_output=self.case.expected_output,
            output=execution_result.ctx.output
            if execution_result is not None
            else None,
            metrics=execution_result.ctx.metrics
            if execution_result is not None
            else {},
            attributes=execution_result.ctx.attributes
            if execution_result is not None
            else {},
            assertions=assertions,
            scores=scores,
            labels=labels,
            task_duration=execution_result.ctx.duration
            if execution_result is not None
            else 0.0,
            total_duration=total_duration,
            evaluator_failures=evaluator_failures,
        )

        failed_assertions = [r for r in assertions.values() if r.value is False]
        if failed_assertions or evaluator_failures:
            raise EvalAssertionError(results)

    def repr_failure(self, excinfo: Any) -> str:
        if isinstance(excinfo.value, EvalAssertionError):
            lines = []
            for r in excinfo.value.results:
                icon = "✔" if r.value is True else ("✗" if r.value is False else "~")
                line = f"  {icon} {r.name}"
                if r.reason:
                    line += f": {r.reason}"
                lines.append(line)
            return "\n".join(lines)
        return str(excinfo.value)

    def reportinfo(self):
        return self.fspath, None, f"{self.parent.name}:{self.name}"
