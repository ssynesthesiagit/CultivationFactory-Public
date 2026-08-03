"""Narrow process-adapter shims for immutable vendor Python tools.

The pinned Factory's browser probe searches Linux executable aliases even on
Windows.  The Foundry supplies an explicitly resolved local browser through an
environment variable and maps only those aliases.  No vendor file is changed.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


_original_which = shutil.which


def _foundry_which(command: str, mode: int = os.F_OK | os.X_OK, path: str | None = None) -> str | None:
    browser = os.environ.get("TIANXIA_BROWSER_EXECUTABLE")
    if command in {"chromium", "chromium-browser", "google-chrome", "google-chrome-stable"} and browser:
        candidate = Path(browser)
        if candidate.is_file():
            return str(candidate)
    return _original_which(command, mode=mode, path=path)


shutil.which = _foundry_which
