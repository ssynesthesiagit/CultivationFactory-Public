"""Checks for the terminology pass over pinned and structured source text."""
from pathlib import Path

from tools.aspect_term_values import json_values
from tools.aspect_terms import aspect_terms


def test_final_bible_lines_are_already_in_final_terminology():
    bible = Path(__file__).resolve().parents[1] / "authority/bible"
    books = sorted(bible.rglob("*.md"))
    assert books
    old = [
        f"{path.relative_to(bible)}:{line_no}: {line}"
        for path in books
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if aspect_terms(line) != line
    ]
    assert not old, "\n".join(old)


def test_json_wording_preserves_keys_ids_enum_values_and_escapes():
    before = ('{ "Fire Sphere": "a Fire Sphere talent", "id": "tianxia.sphere.fire",\n'
              r'  "rows": [{"source_kind": "Sphere", "note": "an Equipment Sphere \u2014 unchanged"}] }' "\n")
    after = json_values(before, lambda value, _path, _offset: aspect_terms(value) if " " in value else value)
    assert after == ('{ "Fire Sphere": "a Way of Fire talent", "id": "tianxia.sphere.fire",\n'
                     r'  "rows": [{"source_kind": "Sphere", "note": "a Way of Armaments \u2014 unchanged"}] }' "\n")
