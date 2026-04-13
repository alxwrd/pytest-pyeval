from __future__ import annotations

import sys

import pytest


class _EvalOnlyPlugin:
    def pytest_ignore_collect(self, collection_path, config):
        if collection_path.is_file() and collection_path.suffix == ".py":
            if not collection_path.name.startswith("eval_"):
                return True
        return None


def main() -> None:
    sys.exit(pytest.main(sys.argv[1:], plugins=[_EvalOnlyPlugin()]))
