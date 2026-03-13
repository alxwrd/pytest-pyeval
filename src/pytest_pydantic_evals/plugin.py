def pytest_configure(config) -> None:
    """Register eval_*.py discovery and markers."""
    config.addinivalue_line("python_files", "eval_*.py")


def pytest_pycollect_makeitem(collector, name: str, obj: object):
    """Collect locally-defined eval_* functions; support __eval__ = False opt-out."""

    # Only collect functions that start with "eval_"
    if not (callable(obj) and name.startswith("eval_")):
        return None

    # Skip pytest fixtures silently — they can legitimately be named eval_*.
    if getattr(obj, "_pytestfixturefunction", None) is not None:
        return None

    # Opt-out: __eval__ = False
    if getattr(obj, "__eval__", True) is False:
        return None

    # Only collect functions defined locally in this file
    if (collector_path := getattr(collector, "path", None)) is None:
        return None

    if not str(collector_path.name).startswith("eval_"):
        return None

    return  # TODO: return a pytest item
