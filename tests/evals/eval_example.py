"""Example eval file — used both as a standalone example and in plugin tests."""

from pytest_pydantic_eval import (
    dataset,
    execute,
    Case,
    EqualsExpected,
    Contains,
    IsInstance,
    MaxDuration,
)


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
