"""A pin change only advances explicit reviews of certified wording pairs."""
import json

from tools import rebind_aspect_bible as rebind
from tools import typed_mechanics_helpers as typed


def test_bible_rebind_keeps_effects_and_rejects_uncertified_lines(tmp_path, monkeypatch):
    path = tmp_path / "reviewed_final.json"
    rel = "book/chapter.md"
    old = "#### First\nUse a Fire Sphere talent.\nGain 2 AC."
    new = "#### First\nUse a Way of Fire talent.\nGain 2 AC."
    changed_rule = new.replace("2 AC", "3 AC")
    unchanged_review = {
        "text_sha256": rebind.text_sha(old),
        "effects": [{"type": "ac_bonus", "flat": 2, "applies_to": "self", "evidence": "Use a Fire Sphere talent."}],
    }
    path.write_text(json.dumps({"mechanics": {"certified": unchanged_review, "uncertified": unchanged_review}}))
    pairs = tmp_path / "pairs.txt"
    # The pair's position is not the line position in either match.
    pairs.write_text(f"@@ {rel}:100\n- Use a Fire Sphere talent.\n+ Use a Way of Fire talent.\n")

    class Index:
        def __init__(self, entries):
            self.entries = entries

        def resolve_key(self, key, text):
            return (rel, 5, 7, self.entries[key]), None

    monkeypatch.setattr(typed, "REVIEWED_FINAL", path)
    monkeypatch.setattr(typed, "_gather_sources", lambda: [
        {"id": "certified", "text": "Catalog copy."}, {"id": "uncertified", "text": "Another catalog copy."},
    ])
    monkeypatch.setattr(rebind, "_index", lambda _root: Index({"certified": old, "uncertified": old}))
    monkeypatch.setattr(typed, "_bible_index", lambda _root: Index({"certified": new, "uncertified": changed_rule}))
    result = rebind.rebind(tmp_path, pairs)
    assert result["rebound"] == ["certified"]
    assert set(result["kept"]) == {"uncertified"}
    assert result["mapped_before"] == result["mapped_after"] == 2
    assert result["switched_before"] == 2 and result["switched_after"] == 1
    actual = json.loads(path.read_text())["mechanics"]
    assert actual["uncertified"] == unchanged_review
    assert actual["certified"]["text_sha256"] == rebind.text_sha(new)
    assert actual["certified"]["effects"] == [
        {"type": "ac_bonus", "flat": 2, "applies_to": "self", "evidence": "Use a Way of Fire talent."}
    ]
