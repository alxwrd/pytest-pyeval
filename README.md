<div align="center">
    <h1><code>pytest-pyeval</code></h1>
    <p align="center"><i>
        A <code>pytest</code> plugin integrating <code>pydantic-evals</code>
    </i></p>
    <img width="256px" src="https://raw.githubusercontent.com/alxwrd/pytest-pyeval/refs/heads/main/.github/assets/wizard-768.png">
    <div align="center">
        <a href="https://github.com/alxwrd/pytest-pyeval/actions/workflows/test.yml"><img src="https://img.shields.io/github/actions/workflow/status/alxwrd/pytest-pyeval/test.yml?branch=main&label=main"></a>
        <a href="https://pypi.python.org/pypi/pytest-pyeval"><img src="https://img.shields.io/pypi/v/pytest-pyeval.svg"></a>
        <a href="https://github.com/alxwrd/pytest-pyeval/blob/main/LICENCE"><img src="https://img.shields.io/pypi/l/pytest-pyeval.svg?"></a>
    </div>

Run [evals](https://ai.pydantic.dev/evals/) via
[pytest](https://docs.pytest.org/en/stable/) with the power of fixtures and
using a familiar Arrange, Act, Evaluate pattern.
</div>


## Example

```python
from pyeval import dataset, execute, Case, EqualsExpected, Contains


def uppercase_text(text: str) -> str:
    return text.upper()


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
)
def eval_uppercase(case: Case):
    result = execute(uppercase_text, case)

    result.evaluate(EqualsExpected())
    result.evaluate(Contains(value="HELLO", case_sensitive=True))
```

```plain
$ uv run pyeval

============================== test session starts ==============================
platform darwin -- Python 3.13.1, pytest-9.0.2, pluggy-1.6.0
plugins: anyio-4.12.1, pyeval-0.1.0
collected 2 items

tests/evals/eval_example.py ●●                                                                         [100%]

============================= 2 evaluated in 0.02s ==============================
```


## Installation

```shell
uv add --dev pytest-pyeval
```

## Running evals

`pytest-pyeval` keeps evals separate from your regular test suite. Evals are
excluded from `pytest` by default, since they are typically slower, hit live
APIs, and run on a different cadence to unit tests.

| Command | What runs |
|---|---|
| `pytest` | Regular tests only (`test_*.py`) |
| `pytest --evals` | Eval tests only (`eval_*.py`) |
| `pyeval` | Shorthand for `pytest --evals` |

```shell
pyeval                     # discover and run all evals in the project
pyeval evals/              # run evals under a specific path
pyeval evals/eval_foo.py   # run a single eval file
```

## Logfire integration

`pytest-pyeval` automatically sends evaluation results to [Logfire](https://logfire.pydantic.dev/)
as experiment traces when Logfire is configured.

Configure Logfire before your evals run using a session-scoped autouse fixture
in your `conftest.py`:

```python
# tests/evals/conftest.py
import logfire
import pytest


@pytest.fixture(scope="session", autouse=True)
def configure_logfire():
    logfire.configure(
        send_to_logfire="if-token-present",
    )
```

That's it! With `LOGFIRE_TOKEN` set in your environment, evaluation traces will
appear in the Logfire web UI under the **Evals** view.

To install Logfire:

```shell
uv add --dev logfire
```
