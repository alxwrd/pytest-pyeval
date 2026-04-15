import logfire
import pytest


@pytest.fixture(scope="session", autouse=True)
def configure_logfire():
    logfire.configure(
        send_to_logfire="if-token-present",
    )


@pytest.fixture
def prefix():
    return "HELLO"


@pytest.fixture
def greeting(prefix):
    return f"{prefix} WORLD"
