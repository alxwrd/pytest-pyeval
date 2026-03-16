"""Eval functions that load their cases from a file."""

from pathlib import Path

from pyeval import Case, dataset, execute
from pyeval.evaluators import EqualsExpected

CASES_FILE = Path(__file__).parent / "eval_from_file_cases.yaml"


@dataset(CASES_FILE)
def eval_uppercase_from_file(case: Case) -> None:
    result = execute(str.upper, case)
    result.evaluate(EqualsExpected())


@dataset(str(CASES_FILE))
def eval_uppercase_from_file_str_path(case: Case) -> None:
    result = execute(str.upper, case)
    result.evaluate(EqualsExpected())
