from __future__ import annotations

import time
import traceback
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from pydantic import TypeAdapter
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import (
    EvaluationReason,
    EvaluationResult,
    Evaluator,
    EvaluatorContext,
    EvaluatorFailure,
    EvaluatorOutput,
)
from pydantic_evals.otel._errors import SpanTreeRecordingError

_EVALUATOR_OUTPUT_ADAPTER: TypeAdapter[EvaluatorOutput] = TypeAdapter(EvaluatorOutput)

_CURRENT_EVAL_RESULTS: ContextVar[list[EvaluationResult] | None] = ContextVar(
    "current_eval_results", default=None
)

# Stores the most recent ExecutionResult so EvalItem can read output/task_duration
_CURRENT_EXECUTION_RESULT: ContextVar[ExecutionResult | None] = ContextVar(
    "current_execution_result", default=None
)


@dataclass
class ExecutionResult:
    """The result of running a task via :func:`execute`.

    Provides direct access to the task's output and the case inputs for use
    in assertions or additional evaluations::

        result = execute(my_func, case)

        assert "expected substring" in result.output

        result.evaluate(EqualsExpected())
    """

    ctx: EvaluatorContext
    failures: list[EvaluatorFailure] = field(default_factory=list)

    @property
    def output(self) -> Any:
        """The value returned by the task function."""
        return self.ctx.output

    @property
    def inputs(self) -> Any:
        """The inputs passed to the task function, taken from the case."""
        return self.ctx.inputs

    @property
    def expected_output(self) -> Any:
        """The expected output from the case, or ``None`` if not set."""
        return self.ctx.expected_output

    @property
    def duration(self) -> float:
        """How long the task took to run, in seconds."""
        return self.ctx.duration

    def evaluate(self, *evaluators: Evaluator) -> None:
        results = _CURRENT_EVAL_RESULTS.get()
        if results is None:
            raise RuntimeError(
                "result.evaluate() called outside of an eval context. "
                "Did you call this eval function directly instead of running it via pytest?"
            )
        for evaluator in evaluators:
            try:
                raw = evaluator.evaluate_sync(self.ctx)
                normalized = _EVALUATOR_OUTPUT_ADAPTER.validate_python(raw)
                default_name = evaluator.get_default_evaluation_name()
                mapping = (
                    normalized
                    if isinstance(normalized, Mapping)
                    else {default_name: normalized}
                )
                for name, result in mapping.items():
                    if not isinstance(name, str):
                        name = str(name)
                    if not isinstance(result, EvaluationReason):
                        result = EvaluationReason(
                            value=result
                            if isinstance(result, bool | int | float | str)
                            else str(result)
                        )
                    results.append(
                        EvaluationResult(
                            name=name,
                            value=result.value,
                            reason=result.reason,
                            source=evaluator.as_spec(),
                        )
                    )
            except Exception as e:
                self.failures.append(
                    EvaluatorFailure(
                        name=evaluator.get_default_evaluation_name(),
                        error_message=f"{type(e).__name__}: {e}",
                        error_stacktrace=traceback.format_exc(),
                        source=evaluator.as_spec(),
                    )
                )


def _group_by_type(
    evaluation_results: list[EvaluationResult],
) -> tuple[
    dict[str, EvaluationResult[bool]],
    dict[str, EvaluationResult[int | float]],
    dict[str, EvaluationResult[str]],
]:
    """Split evaluation results into assertions (bool), scores (int/float), labels (str)."""
    assertions: dict[str, EvaluationResult[bool]] = {}
    scores: dict[str, EvaluationResult[int | float]] = {}
    labels: dict[str, EvaluationResult[str]] = {}
    seen: set[str] = set()

    for result in evaluation_results:
        name = result.name
        if name in seen:
            suffix = 2
            while f"{name}_{suffix}" in seen:
                suffix += 1
            name = f"{name}_{suffix}"
        seen.add(name)

        if (assertion := result.downcast(bool)) is not None:
            assertions[name] = assertion
        elif (score := result.downcast(int, float)) is not None:
            scores[name] = score
        elif (label := result.downcast(str)) is not None:
            labels[name] = label

    return assertions, scores, labels


def execute(task: Callable[..., Any], case: Case) -> ExecutionResult:
    t0 = time.perf_counter()
    output = task(case.inputs)
    duration = time.perf_counter() - t0

    ctx = EvaluatorContext(
        name=case.name,
        inputs=case.inputs,
        metadata=case.metadata,
        expected_output=case.expected_output,
        output=output,
        duration=duration,
        _span_tree=SpanTreeRecordingError(
            "Span tree not available outside of a Logfire-instrumented context."
        ),
        attributes={},
        metrics={},
    )
    result = ExecutionResult(ctx=ctx)
    _CURRENT_EXECUTION_RESULT.set(result)
    return result


Func = TypeVar("Func", bound=Callable[..., Any])


def dataset(*args: Case | str | Path) -> Callable[[Func], Func]:
    """Register evaluation cases for an eval function.

    Accepts either a file path (str or :class:`~pathlib.Path`) to load cases from,
    or one or more :class:`~pydantic_evals.Case` instances directly.

    When given a file path, the dataset is loaded via
    :meth:`~pydantic_evals.Dataset.from_file`, which supports YAML and JSON formats.

    Args:
        *args: Either a single file path (str or Path) or one or more
            :class:`~pydantic_evals.Case` instances.

    Example — inline cases::

        @dataset(
            Case(name="basic", inputs="hello", expected_output="HELLO"),
            Case(name="numbers", inputs="abc123", expected_output="ABC123"),
        )
        def eval_uppercase(case: Case) -> None:
            result = execute(str.upper, case)
            result.evaluate(EqualsExpected())

    Example — from file::

        @dataset("cases.yaml")
        def eval_uppercase(case: Case) -> None:
            result = execute(str.upper, case)
            result.evaluate(EqualsExpected())
    """
    if len(args) == 1 and isinstance(args[0], (str, Path)):
        cases: tuple[Case, ...] = tuple(Dataset[Any, Any, Any].from_file(args[0]).cases)
    else:
        cases = args  # type: ignore[assignment]

    def decorator(fn: Func) -> Func:
        fn.__eval_cases__ = cases
        return fn

    return decorator
