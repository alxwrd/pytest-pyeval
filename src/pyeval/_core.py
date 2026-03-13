from __future__ import annotations

import time
import traceback
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from pydantic import TypeAdapter
from pydantic_evals import Case
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
    ctx: EvaluatorContext
    failures: list[EvaluatorFailure] = field(default_factory=list)

    def evaluate(self, evaluator: Evaluator) -> None:
        results = _CURRENT_EVAL_RESULTS.get()
        if results is None:
            raise RuntimeError(
                "result.evaluate() called outside of an eval context. "
                "Did you call this eval function directly instead of running it via pytest?"
            )
        try:
            raw = evaluator.evaluate_sync(self.ctx)
            normalized = _EVALUATOR_OUTPUT_ADAPTER.validate_python(raw)
            for name, result in _to_mapping(
                normalized, evaluator.get_default_evaluation_name()
            ).items():
                if not isinstance(result, EvaluationReason):
                    result = EvaluationReason(value=result)
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


def _to_mapping(
    result: EvaluatorOutput, scalar_name: str
) -> Mapping[str, EvaluationReason | Any]:
    if isinstance(result, Mapping):
        return result
    return {scalar_name: result}


def _group_by_type(
    evaluation_results: list[EvaluationResult],
) -> tuple[
    dict[str, EvaluationResult],
    dict[str, EvaluationResult],
    dict[str, EvaluationResult],
]:
    """Split evaluation results into assertions (bool), scores (int/float), labels (str)."""
    assertions: dict[str, EvaluationResult] = {}
    scores: dict[str, EvaluationResult] = {}
    labels: dict[str, EvaluationResult] = {}
    seen: set[str] = set()

    for er in evaluation_results:
        name = er.name
        if name in seen:
            suffix = 2
            while f"{name}_{suffix}" in seen:
                suffix += 1
            name = f"{name}_{suffix}"
        seen.add(name)

        if (a := er.downcast(bool)) is not None:
            assertions[name] = a
        elif (s := er.downcast(int, float)) is not None:
            scores[name] = s
        elif (l := er.downcast(str)) is not None:
            labels[name] = l

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


def dataset(*cases: Case) -> Callable:
    def decorator(fn: Callable) -> Callable:
        fn.__eval_cases__ = cases
        return fn

    return decorator
