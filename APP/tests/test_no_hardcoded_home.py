"""Guard: no tracked APP/ file may hardcode a machine-specific home directory.

A path such as /home/<user>/ or /Users/<user>/ ties the code to one machine. Use
`$HOME`/`~`, `Path.home()`, `os.homedir()`, an environment variable with a
home-relative default, or Playwright's own discovery instead.

The check walks `git ls-files` for APP/ and reads each file as UTF-8 text.
Binary files are skipped. There is deliberately no allow-list.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
# Written as a pattern over the file text, so this file does not match itself.
HOME_PATH = re.compile(r"/home/[A-Za-z0-9_.-]+/|/Users/[A-Za-z0-9_.-]+/")


def _tracked_app_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", "."],
        cwd=APP,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")
    return [APP / name for name in listed.split("\0") if name]


def _hardcoded_home_hits() -> list[str]:
    hits: list[str] = []
    for path in _tracked_app_files():
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if HOME_PATH.search(line):
                rel = path.relative_to(APP).as_posix()
                hits.append(f"APP/{rel}:{number}: {line.strip()}")
    return hits


def test_no_tracked_app_file_hardcodes_a_home_directory() -> None:
    hits = _hardcoded_home_hits()
    assert not hits, (
        "hardcoded machine-specific home path(s) found; use $HOME, ~, Path.home(), "
        "an env var with a home-relative default, or Playwright discovery:\n"
        + "\n".join(hits)
    )
