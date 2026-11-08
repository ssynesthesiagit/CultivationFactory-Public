"""Read the plug-in hook and effect contract catalogue."""

from pathlib import Path


def catalogue() -> str:
    """Return the contracts in their original catalogue order."""
    directory = Path(__file__).resolve().parents[1] / "combat/ext/hook_docs"
    return "\n\n".join(path.read_text(encoding="utf-8") for path in sorted(directory.glob("*.md")))
