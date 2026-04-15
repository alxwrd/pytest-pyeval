from __future__ import annotations

import itertools
import time
import traceback
from collections.abc import Callable
from typing import Any, cast

import pytest
from _pytest.fixtures import TopRequest
from _pytest.nodes import Node
from _pytest.python import Function
from pydantic_evals import Case
from pydantic_evals.evaluators import EvaluatorFailure
from pydantic_evals.reporting import EvaluationReport, ReportCase, ReportCaseFailure


from pyeval._logfire import send_report

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
    raise ValueError(
        f"Score {score!r} did not match any band (expected a value >= 0.0)"
    )


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--evals",
        action="store_true",
        default=False,
        help="Run only eval tests (@dataset-decorated functions in eval_*.py files).",
    )


def pytest_configure(config) -> None:
    config.addinivalue_line("python_files", "eval_*.py")


def pytest_ignore_collect(collection_path, config) -> bool | None:
    if not collection_path.is_file() or collection_path.suffix != ".py":
        return None

    is_eval_file = collection_path.name.startswith("eval_")
    run_evals = config.getoption("--evals", default=False)

    if run_evals and not is_eval_file:
        return True
    if not run_evals and is_eval_file:
        return True
    return None


def pytest_report_teststatus(
    report: pytest.TestReport, config: pytest.Config
) -> tuple[str, str, str] | None:
    if report.when != "call":
        return None
    for key, value in report.user_properties:
        if key == "eval_status":
            symbol, color, icons = value
            return ("evaluated", f"{color}{symbol}{_RESET}", icons)
    return None


def pytest_pycollect_makeitem(collector, name: str, obj: object):
    """Collect eval functions and return EvalCollector instances."""
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
            yield EvalItem.from_parent(
                self,
                name=case.name or f"case_{i}",
                func=self.func,
                case=case,
            )

    def teardown(self):
        report_cases: list[ReportCase] = []
        report_failures: list[ReportCaseFailure] = []

        for item in cast(list[EvalItem], self.session.items):
            if item.parent is not self:
                continue

            if report_case := item._report_case:
                report_cases.append(report_case)
            elif report_failure := item._report_failure:
                report_failures.append(report_failure)

        if not report_cases and not report_failures:
            return

        report = EvaluationReport(
            name=self.func.__name__,
            cases=report_cases,
            failures=report_failures,
        )
        report.print()

        send_report(report)


class EvalItem(pytest.Item):
    def __init__(self, name: str, parent: Node, func: Callable[..., Any], case: Case):
        super().__init__(name, parent)
        self.obj = func
        self.case = case
        self._report_case: ReportCase | None = None
        self._report_failure: ReportCaseFailure | None = None

        self._fixtureinfo = self.session._fixturemanager.getfixtureinfo(
            node=self,
            func=func,
            cls=None,
        )

        self.funcargs: dict[str, object] = {}
        self.fixturenames = self._fixtureinfo.names_closure
        self._request = TopRequest(cast(Function, self), _ispytest=True)

    @property
    def func(self) -> Callable[..., Any]:
        """Alias for :attr:`obj` using the domain name ``func``.

        pytest uses ``obj`` as the conventional attribute name for the underlying
        Python object a node wraps. We store the eval function there to satisfy
        that convention, and expose it here as ``func`` for readability.
        """
        return self.obj

    def setup(self):
        self.funcargs["case"] = self.case
        self._request._fillfixtures()

    def runtest(self):
        kwargs = {name: self.funcargs[name] for name in self._fixtureinfo.argnames}

        results: list = []
        results_token = _CURRENT_EVAL_RESULTS.set(results)
        execution_token = _CURRENT_EXECUTION_RESULT.set(None)

        t0 = time.perf_counter()
        try:
            self.func(**kwargs)
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

        all_values = [
            min(1.0, max(0.0, float(r.value)))
            for r in itertools.chain(assertions.values(), scores.values())
        ]
        score = sum(all_values) / len(all_values) if all_values else 1.0

        bool_icons = "".join(
            "✔" if r.value is True else "✗" for r in assertions.values()
        )
        score_icons = "".join(
            _score_symbol(min(1.0, max(0.0, float(result.value))))[0]
            for result in scores.values()
        )
        icons = bool_icons + score_icons
        self.user_properties.append(("eval_status", (*_score_symbol(score), icons)))

    def reportinfo(self):
        parent_name = f"{self.parent.name}:" if self.parent is not None else ""

        # 0 is the pytest convention for synthetic items with no source line —
        # see https://docs.pytest.org/en/stable/example/nonpython.html
        return self.fspath, 0, f"{parent_name}{self.name}"
