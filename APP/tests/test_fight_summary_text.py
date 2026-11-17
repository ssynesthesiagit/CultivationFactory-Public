"""The fight summary's notes about incomplete older logs are shown to players (owner rule: newcomer-readable text)."""
import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "combat" / "fight_summary.py"
JARGON = ("packet", "lower bound", "pre-reduction", "structured", "unattributed", "before/after", "relation change", "reconstructed")


def _notes():
    tree = ast.parse(SOURCE.read_text())
    return [node.args[0].value for node in ast.walk(tree)
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add"
            and getattr(node.func.value, "id", "") == "limitations" and isinstance(node.args[0], ast.Constant)]


def test_every_limitation_note_is_plain_words():
    notes = _notes()
    assert len(notes) >= 9
    for note in notes:
        assert not any(term in note.lower() for term in JARGON), note
        assert note.endswith(".") and note[0].isupper(), note
