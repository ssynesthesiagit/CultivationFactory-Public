from __future__ import annotations

import os
import sys
from pathlib import Path

from app.core import FoundryError

PRIVATE_PYTHON_ENV = "TIANXIA_PRIVATE_PYTHON"


def helper_python_executable() -> Path:
    """Return the private helper interpreter selected by the packaged launcher.

    Development runs continue to use the current interpreter. A frozen launcher
    must set ``TIANXIA_PRIVATE_PYTHON`` to the bundled private runtime; a
    caller-supplied missing path fails closed instead of falling back to the EXE.
    """
    configured = os.getenv(PRIVATE_PYTHON_ENV)
    if configured:
        candidate = Path(configured).expanduser().resolve()
        if not candidate.is_file():
            raise FoundryError(
                "PRIVATE_PYTHON_RUNTIME_MISSING",
                "The packaged private Python runtime is missing or unavailable.",
                details={"path": str(candidate)},
                status_code=500,
            )
        return candidate
    return Path(sys.executable).resolve()
