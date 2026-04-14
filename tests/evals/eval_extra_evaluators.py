"""Regression test: case.evaluators can be unpacked into result.evaluate()."""

from pyeval import Case, dataset, execute
from pyeval.evaluators import EqualsExpected, IsInstance, MaxDuration


@dataset(
    Case(name="basic", inputs="hello", expected_output="hello"),
    Case(
        name="with_extra_evaluators",
        inputs="hello",
        expected_output="hello",
        evaluators=[MaxDuration(seconds=1)],
    ),
)
def eval_case_evaluators(case: Case):
    result = execute(lambda x: x, case)
    result.evaluate(EqualsExpected())
    result.evaluate(IsInstance(type_name="str"))
    result.evaluate(*case.evaluators)
