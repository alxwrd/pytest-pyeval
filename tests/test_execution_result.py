from pydantic_evals import Case

from pyeval import execute


def _identity(x):
    return x


def test_output_returns_task_return_value():
    case = Case(name="test", inputs="hello")
    result = execute(_identity, case)
    assert result.output == "hello"


def test_inputs_returns_case_inputs():
    case = Case(name="test", inputs="hello")
    result = execute(_identity, case)
    assert result.inputs == "hello"


def test_expected_output_returns_case_expected_output():
    case = Case(name="test", inputs="hello", expected_output="world")
    result = execute(_identity, case)
    assert result.expected_output == "world"


def test_expected_output_is_none_when_not_set():
    case = Case(name="test", inputs="hello")
    result = execute(_identity, case)
    assert result.expected_output is None


def test_duration_is_a_float():
    case = Case(name="test", inputs="hello")
    result = execute(_identity, case)
    assert isinstance(result.duration, float)
    assert result.duration > 0
