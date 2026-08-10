"""Runtime safety checks that must run before importing native dependencies."""

from __future__ import annotations

import importlib
from collections.abc import Callable

InterpreterIds = Callable[[], tuple[object, object] | None]


def _interpreter_ids() -> tuple[object, object] | None:
    """Return current/main interpreter IDs when the Python runtime exposes them."""
    for module_name in ("_interpreters", "_xxsubinterpreters"):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        get_current = getattr(module, "get_current", None)
        get_main = getattr(module, "get_main", None)
        if callable(get_current) and callable(get_main):
            return get_current(), get_main()
    return None


def require_main_interpreter(*, interpreter_ids: InterpreterIds | None = None) -> None:
    """Reject sub-interpreters before NumPy/SciPy can terminate their host process."""
    ids = (interpreter_ids or _interpreter_ids)()
    if ids is None or ids[0] == ids[1]:
        return
    raise RuntimeError(
        "multi-cam-sync cannot run inside a Python sub-interpreter. DaVinci Resolve's "
        "built-in Py3 console uses a sub-interpreter, where the native NumPy/SciPy "
        "dependencies can crash Resolve. Run the CLI from an external main-interpreter "
        "process with Resolve external scripting enabled."
    )


# Import this sentinel before any application module that can load native analysis code.
MAIN_INTERPRETER_RUNTIME = require_main_interpreter()
