"""Example eval file — used both as a standalone example and in plugin tests."""

from pyeval import Case, dataset, execute
from pyeval.evaluators import (
    Contains,
    EqualsExpected,
    Evaluator,
    IsInstance,
    MaxDuration,
)


class CustomEvaluator(Evaluator):
    def evaluate(self, ctx) -> float:
        return 0.5


@dataset(
    Case(
        name="basic_lowercase",
        inputs="hello world",
        expected_output="Hello World",
    ),
    Case(
        name="basic_uppercase",
        inputs="HELLO WORLD",
        expected_output="Hello World",
    ),
    Case(
        name="mixed_case",
        inputs="HeLLo WoRLd",
        expected_output="Hello World",
    ),
    Case(
        name="empty_string",
        inputs="",
        expected_output="",
    ),
    Case(
        name="single_word",
        inputs="hello",
        expected_output="Hello",
    ),
    Case(
        name="with_punctuation",
        inputs="hello, world!",
        expected_output="Hello, World!",
    ),
    Case(
        name="with_numbers",
        inputs="hello 123 world",
        expected_output="Hello 123 World",
    ),
    Case(
        name="apostrophes",
        inputs="don't stop believin'",
        expected_output="Don'T Stop Believin'",
    ),
)
def eval_title_case_validation(case):
    # Arrange
    def to_title_case(text: str) -> str:
        """Convert text to title case."""
        return text.title()

    # Act
    result = execute(to_title_case, case)

    # Evaluate
    result.evaluate(IsInstance(type_name="str"))
    result.evaluate(EqualsExpected())
    result.evaluate(Contains(value="H", evaluation_name="has_capitals"))
    result.evaluate(MaxDuration(seconds=0.001))
    result.evaluate(CustomEvaluator())


@dataset(
    Case(
        name="uppercase_basic",
        inputs="hello world",
        expected_output="HELLO WORLD",
    ),
    Case(
        name="uppercase_with_numbers",
        inputs="hello 123",
        expected_output="HELLO 123",
    ),
    Case(
        name="uppercase_bye",
        inputs="bye 123",
        expected_output="BYE 123",
    ),
)
def eval_uppercase(case: Case, request):
    def uppercase_text(text: str) -> str:
        return text.upper()

    result = execute(uppercase_text, case)

    result.evaluate(EqualsExpected())
    result.evaluate(Contains(value="HELLO", case_sensitive=True))


@dataset(
    Case(
        name="uses_greeting_fixture",
        inputs="hello world",
        expected_output="HELLO WORLD",
    ),
)
def eval_fixture_with_dependency(case: Case, greeting):
    """Regression test: fixtures with their own dependencies should not cause TypeError.

    The `greeting` fixture depends on `prefix`. Previously, names_closure included
    transitive dependencies (prefix), which were incorrectly passed as kwargs to
    the eval function.
    """

    def uppercase_text(text: str) -> str:
        return text.upper()

    result = execute(uppercase_text, case)

    result.evaluate(EqualsExpected())
    result.evaluate(Contains(value=greeting, case_sensitive=True))


# $ uv run pytest tests/evals/eval_example.py
# ==== test session starts ====
# platform linux -- Python 3.12.7, pytest-8.3.5, pluggy-1.3.0
# rootdir: /Users/alxwrd/repos/pytest-evals
# collected 8 items
#
# tests/evals/eval_example.py:basic_lowercase ✔✔✔✗
# tests/evals/eval_example.py:basic_uppercase ✔✔✔✗
# tests/evals/eval_example.py:mixed_case ✔✔✔✗
# tests/evals/eval_example.py:empty_string ✔✔✗✗
# tests/evals/eval_example.py:single_word ✔✔✔✗
# tests/evals/eval_example.py:with_punctuation ✔✔✔✗
# tests/evals/eval_example.py:with_numbers ✔✔✔✗
# tests/evals/eval_example.py:apostrophes ✔✔✗✗
#
#  Averages: 68.8% ✔
#
# ==== 8 cases, 32 evaluations ====
