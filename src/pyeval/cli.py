from __future__ import annotations

import sys

import pytest


def main() -> None:
    sys.exit(pytest.main(["--evals"] + sys.argv[1:]))
