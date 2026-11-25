"""Read the plug-in hook and effect contract catalogue."""

import ast
from pathlib import Path

import combat.ext


def catalogue() -> str:
    """Return the contracts in their original catalogue order."""
    directory = Path(combat.ext.__file__).parent / "hook_docs"
    if not directory.is_dir():
        raise FileNotFoundError(f"Hook catalogue directory missing: {directory}")
    paths = sorted(directory.glob("s[0-9][0-9][0-9]_*.py"))
    if not paths:
        raise ValueError(f"Hook catalogue has no sections: {directory}")
    return "\n\n".join(ast.parse(path.read_text(encoding="utf-8")).body[0].value.value for path in paths)
