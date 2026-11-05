"""Reviewer evidence never reaches player text through paid_hit.effect_text.

effect_text is the one shared formatter for option labels, descriptions and
prompts. Reviewed evidence is routed through display_text there, so a rider
whose evidence is reviewer commentary reads as its plain rule.
"""
import glob
import json
import re
from pathlib import Path

from combat.ext.paid_hit import effect_text

ROOT = Path(__file__).resolve().parents[1]
REVIEWED = sorted(glob.glob(str(ROOT / "authority/typed_mechanics/reviewed_final.d/*.json")))
REVIEWER_NOTE = "this table defines neither"
MARKERS = re.compile(r"this table|GM-only|GM adjudicates|\.json\b|\.py\b|\b\w+/[\w/]+\.\w+")


def _evidence_strings(node, out):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "evidence" and isinstance(value, str):
                out.append(value)
            else:
                _evidence_strings(value, out)
    elif isinstance(node, list):
        for value in node:
            _evidence_strings(value, out)
    return out


def test_plague_rider_label_reads_plainly_without_reviewer_note():
    record = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    effects = record["mechanics"]["tianxia.talent.disease.plague_bearing_body"]["effects"]
    text = effect_text(effects)
    assert REVIEWER_NOTE not in text
    assert "You are immune to ordinary disease and to Sickened." in text


def test_reviewer_evidence_strings_are_not_emitted_raw_as_player_text():
    raw = []
    for path in REVIEWED:
        _evidence_strings(json.loads(Path(path).read_text(encoding="utf-8")), raw)
    leaked = [e for e in set(raw) if REVIEWER_NOTE in e and effect_text([{"type": "rider", "evidence": e}]) == e]
    assert leaked == []


def test_compiled_rider_labels_have_no_file_or_reviewer_markers():
    raw = []
    for path in REVIEWED:
        _evidence_strings(json.loads(Path(path).read_text(encoding="utf-8")), raw)
    for evidence in sorted(set(raw)):
        if not MARKERS.search(evidence):
            continue
        text = effect_text([{"type": "rider", "evidence": evidence}])
        assert not MARKERS.search(text), (evidence[:80], text[:120])
