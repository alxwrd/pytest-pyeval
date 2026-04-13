"""Regression test: pytestmark skipif must not cause INTERNALERROR."""

import pytest

from pyeval import Case, dataset, execute

pytestmark = pytest.mark.skipif(True, reason="always skipped — tests that EvalItem handles pytestmark skipif without INTERNALERROR")


@dataset(
    Case(name="skipped_case", inputs="hello", expected_output="hello"),
)
def eval_skipif_regression(case):
    result = execute(lambda x: x, case)
