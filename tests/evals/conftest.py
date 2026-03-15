import pytest


@pytest.fixture
def prefix():
    return "HELLO"


@pytest.fixture
def greeting(prefix):
    return f"{prefix} WORLD"
