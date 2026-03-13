# Exploration: pytest-pydantic-evals

## The Idea

Combine pytest's fixture injection and test collection with Pydantic Evals' evaluation
framework and reporting. The proposed API looks like:

```python
@dataset(
    Case(name="basic", inputs="hello world", expected_output="Hello World"),
    Case(name="empty", inputs="", expected_output=""),
)
def eval_title_case(case):
    def to_title_case(text: str) -> str:
        return text.title()

    result = execute(to_title_case, case)

    result.evaluate(IsInstance(type_name="str"))
    result.evaluate(EqualsExpected())
    result.evaluate(Contains(value="H", evaluation_name="has_capitals"))
    result.evaluate(MaxDuration(seconds=0.001))
```

Each case becomes a pytest item, reported as `eval_title_case.py:basic`, `eval_title_case.py:empty`,
etc. The pydantic-evals ✔/✗ notation maps naturally to pytest's pass/fail per evaluation.

The value over raw pydantic-evals: **fixtures**. The function body gains access to any pytest
fixture — database connections, mock clients, LLM instances, etc. — which are injected alongside
`case`.

---

## How Pydantic Evals Actually Works

The flow in `pydantic_evals` is:

```
Dataset.evaluate(task)
  └─ for each Case:
       ├─ _run_task(task, case) → EvaluatorContext
       └─ for each Evaluator:
            └─ run_evaluator(evaluator, ctx) → list[EvaluationResult]
  └─ assemble EvaluationReport
```

Key types:

- **`Case`**: holds `inputs`, `expected_output`, `metadata`, and per-case `evaluators`
- **`EvaluatorContext`**: the snapshot after running the task — `inputs`, `output`,
  `expected_output`, `duration`, `attributes`, `metrics`, `span_tree`
- **`Evaluator.evaluate(ctx)`**: pure function, takes context, returns `bool | int | float | str |
  EvaluationReason | dict[str, ...]`
- **`EvaluationReport`**: assembled from `ReportCase` objects, with rich terminal rendering and
  Logfire integration

The task execution and evaluation **are logically separate** — `_run_task` produces the context,
then evaluators are run against it. They're only coupled inside `Dataset.evaluate()`.

---

## The Coupling Problem (and Why It's Actually Fine)

You noted that `Dataset.evaluate()` bundles everything. Looking at the source, the coupling is
only at the orchestration layer, not the data model layer. The key insight:

```python
# From dataset.py ~line 969
async def _run_task(task, case, retry=None) -> EvaluatorContext:
    ...  # runs task, captures timing + OTEL spans
    return EvaluatorContext(name=case.name, inputs=case.inputs, output=task_output, ...)

# From _run_evaluator.py
async def run_evaluator(evaluator, ctx) -> list[EvaluationResult] | EvaluatorFailure:
    raw = await evaluator.evaluate_async(ctx)
    ...  # normalize to list[EvaluationResult]
    return details
```

We don't need to call `Dataset.evaluate()` at all. We can:

1. Run the task ourselves and build an `EvaluatorContext`
2. Run evaluators individually via `evaluator.evaluate_sync(ctx)`
3. Accumulate `EvaluationResult`s
4. Build a `ReportCase` and eventually an `EvaluationReport` for the full-dataset summary

`EvaluatorContext` is **public** (`pydantic_evals.evaluators.EvaluatorContext`). The evaluators
themselves are pure and stateless. `ReportCase` and `EvaluationReport` are also public via
`pydantic_evals.reporting`.

---

## Design: The `execute()` Function

```python
def execute(task: Callable[[InputsT], OutputT], case: Case) -> ExecutionResult:
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
        _span_tree=...,   # SpanTreeRecordingError initially; add Logfire later
        attributes={},
        metrics={},
    )
    return ExecutionResult(ctx=ctx)
```

`ExecutionResult` accumulates evaluations:

```python
@dataclass
class ExecutionResult:
    ctx: EvaluatorContext
    _results: list[EvaluationResult] = field(default_factory=list)
    _failures: list[EvaluatorFailure] = field(default_factory=list)

    def evaluate(self, evaluator: Evaluator) -> None:
        result = evaluator.evaluate_sync(self.ctx)
        # normalize result to list[EvaluationResult] (same logic as run_evaluator)
        self._results.extend(...)
```

The pytest Item calls the user's function, then reads `result._results` to determine pass/fail.

One note on the example syntax `result.evaluate(IsInstance(...), result)` — the second `result`
arg appears to be a design note/typo. The clean API is just `result.evaluate(evaluator)`.

---

## Design: The `@dataset` Decorator

```python
def dataset(*cases: Case):
    def decorator(fn):
        fn.__eval_cases__ = cases
        return fn
    return decorator
```

The plugin's `pytest_pycollect_makeitem` already detects `eval_*` functions. It would check for
`__eval_cases__` and, if present, return one `EvalItem` per case instead of a single item.

---

## Design: The pytest Item

```python
class EvalItem(pytest.Item):
    def __init__(self, name, parent, func, case):
        super().__init__(name, parent)
        self.func = func
        self.case = case

    def runtest(self):
        # resolve fixtures for self.func (minus 'case')
        # call self.func(case=self.case, **fixtures)
        # check self.func's return / result._results for failures

    def repr_failure(self, excinfo):
        # format pydantic-evals-style: ✔✔✗✗

    def reportinfo(self):
        return self.fspath, None, f"{self.parent.name}:{self.case.name}"
```

---

## Fixture Integration

Fixtures are the main motivation. Here's how pytest's fixture machinery works and how to hook in:

### `FixtureRequest` on the item

`pytest.Item` can declare fixtures via `fixturenames`. pytest's fixture manager will then inject
them. The item's `runtest()` uses `self._request.getfixturevalue("my_fixture")` to get resolved
values.

The catch: the item needs to know which fixtures the function needs. We introspect the function
signature, exclude `case`, and register the rest as `fixturenames`.

```python
class EvalItem(pytest.Item):
    def setup(self):
        sig = inspect.signature(self.func)
        self.fixturenames = [p for p in sig.parameters if p != "case"]

    def runtest(self):
        kwargs = {name: self._request.getfixturevalue(name) for name in self.fixturenames}
        self.func(case=self.case, **kwargs)
```

This is the same mechanism pytest uses internally for regular test functions. It's well-supported.

---

## Surfacing Results from `result.evaluate()` to `EvalItem`

The user's function body calls `result.evaluate()` imperatively. The `EvalItem` needs to collect
those results after the function returns. The clean mechanism is a `ContextVar` — the same
pattern pydantic-evals already uses internally for `set_eval_attribute` / `increment_eval_metric`
via `_CURRENT_TASK_RUN`.

```python
_CURRENT_EVAL_RESULTS: ContextVar[list[EvaluationResult] | None] = ContextVar(
    "current_eval_results", default=None
)

# In EvalItem.runtest():
token = _CURRENT_EVAL_RESULTS.set([])
try:
    self.func(case=self.case, **fixtures)
finally:
    self.results = _CURRENT_EVAL_RESULTS.get()
    _CURRENT_EVAL_RESULTS.reset(token)

# In ExecutionResult.evaluate():
def evaluate(self, evaluator: Evaluator) -> None:
    results = _CURRENT_EVAL_RESULTS.get()
    if results is None:
        raise RuntimeError(
            "result.evaluate() called outside of an eval context. "
            "Did you call this function directly instead of via pytest?"
        )
    result = evaluator.evaluate_sync(self.ctx)
    results.extend(...)  # normalize and push
```

Benefits:
- **Isolation**: each `EvalItem` sets its own list via `set()`/`reset()`, so parallel runs don't
  bleed into each other
- **No coupling**: `ExecutionResult` doesn't need a back-reference to its `EvalItem`
- **Works at any call depth**: `evaluate()` can be called from helper functions the user writes

The `default=None` on the `ContextVar` means calling `result.evaluate()` outside of a pytest run
(e.g. in a script or REPL) gives a clear `RuntimeError` rather than a `LookupError`.

---

## Report Aggregation

Building an `EvaluationReport` per `EvalCollector` is the core of what makes this integration
valuable — without it we're just running pytest tests with a pydantic-evals aesthetic, and lose
the main advantages: pass-rate averages across cases, score/label aggregation, rich terminal
tables, and Logfire experiment tracking.

The mapping is: one `eval_*` function → one `EvalCollector` → one `EvaluationReport`. This
mirrors pydantic-evals' own model where one `Dataset` produces one `EvaluationReport`.

Each `EvalItem` stores its `ReportCase` on itself after `runtest()`. The `EvalCollector`'s
`teardown()` fires after all its child `EvalItem`s have run, gathers those `ReportCase` objects,
constructs an `EvaluationReport`, and calls `report.print()`. This is also where Logfire
experiment tracking would be activated — the report carries trace/span IDs for the full
experiment, not just individual cases.

---

## What's Public vs. Private

| Symbol | Access | Notes |
|---|---|---|
| `pydantic_evals.Case` | Public | Fine to use |
| `pydantic_evals.evaluators.EvaluatorContext` | Public | Fine to use |
| `pydantic_evals.evaluators.Evaluator` | Public | Fine to use |
| `pydantic_evals.evaluators.EvaluationResult` | Public | Fine to use |
| `pydantic_evals.reporting.ReportCase` | Public | Fine to use |
| `pydantic_evals.reporting.EvaluationReport` | Public | Fine to use |
| `pydantic_evals.dataset._run_task` | **Private** | Don't use; replicate ~40 lines |
| `pydantic_evals.dataset._run_task_and_evaluators` | **Private** | Don't use |
| `pydantic_evals.evaluators._run_evaluator.run_evaluator` | Private module | Could use, but replicate is safer |

We need only ~40 lines of `_run_task` to replicate (the timing + async bridge). For sync tasks
(which covers the main use case), it's even simpler.

---

## The Async Question

`_run_task` is `async def`. All of pydantic-evals is async-first. Our `execute()` function
needs to work synchronously (it's called from within a regular pytest test body).

Options:

1. **`anyio.from_thread.run_sync` / `asyncio.run()`**: Run the async task in a new event loop.
   Works but adds overhead. Fine for LLM eval use cases where tasks are slow anyway.

2. **Sync-first with async wrapper**: If task is sync, just call it directly and skip the OTEL
   span tree. Add an `async_execute()` variant later. The `EvaluatorContext._span_tree` field
   can be a `SpanTreeRecordingError` (which is what pydantic-evals does when logfire isn't
   configured).

3. **Make `eval_*` functions `async`**: pytest-anyio style. But this breaks the simple fixture
   story and adds another dependency.

**Recommendation: start sync-only.** Pydantic evals' core evaluators (`EqualsExpected`,
`Contains`, `IsInstance`, `MaxDuration`) are all sync. The span_tree functionality can be
added later once the basic integration works.

---

## Feasibility Verdict

**This is feasible.** The key points:

✅ Task execution and evaluation are logically decoupled in pydantic-evals — we just need to
   call them in the right order.

✅ All the types we need (`EvaluatorContext`, `EvaluationResult`, `ReportCase`,
   `EvaluationReport`) are public.

✅ Evaluators are pure functions against `EvaluatorContext` — trivial to call outside
   `Dataset.evaluate()`.

✅ pytest's fixture machinery supports custom `Item` types with `fixturenames` injection.

✅ We replicate ~40 lines of private `_run_task` logic to avoid depending on private API.

⚠️ Async support requires either `asyncio.run()` bridging or making eval functions async.
   Start sync-only.

⚠️ The collector-level aggregate report requires `EvalCollector` teardown to gather
   `ReportCase` objects from its child `EvalItem`s after they run.

---

## Next Steps (Proposed)

1. **`execute()` + `ExecutionResult`** — sync-only, no OTEL, just timing + evaluator accumulation
2. **`EvalItem`** — pytest Item that handles fixture injection and per-case reporting
3. **`pytest_pycollect_makeitem`** — detect `__eval_cases__`, yield one `EvalItem` per case
4. **Basic reporting** — `repr_failure` showing ✔/✗ per evaluation name
5. **`EvalCollector` teardown** — gather `ReportCase`s from child items, render `EvaluationReport`
6. **Async support** — `execute()` bridging for async tasks
7. **Logfire/OTEL** — replicate span_tree capture in `execute()`
