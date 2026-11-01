"""Printed Concentration headers agree with the typed mechanics authority (public CI; committed files only).

A record whose printed header says "**Concentration:** Required" or "Yes" must have duration.concentration true, and
"None" or "No" must be false. Records whose Concentration line sits on a sub-option (one Great Character, one Guardian
mode, one Masterpiece activation) are listed in SUB_OPTION_GAPS with the reason: the record carries one record-level
flag, so setting it would make the whole record concentrate. New drift outside that list fails.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = ROOT / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json"
RULES_TEXT = ROOT / "authority" / "typed_mechanics" / "rules_text.json"
HEADER = re.compile(r"^\*\*Concentration:\*\*\s*(.+?)\s*$", re.M)

SUB_OPTION_GAPS = {
    "tianxia.subpath.qi.calligraphy_cultivator.feature.great_character": "Concentration-requiring Great Characters, chosen per write",
    "tianxia.subpath.qi.calligraphy_cultivator.feature.heaven_s_script": "Concentration on one sub-option, not the record",
    "tianxia.subpath.qi.mountain_core_cultivator.feature.mountain_s_aegis": "Concentration on Stone Guardian mode only",
    "tianxia.subpath.qi.painting_cultivator.feature.masterpiece_scroll": "Concentration on the Activate Masterpiece sub-action only",
    "tianxia.subpath.qi.soul_collateral_contract_cultivator.feature.sovereign_soul_contract": "Concentration on a sub-clause, not the record",
}


def _text(value):
    return value if isinstance(value, str) else (value or {}).get("text", "")


def _rows():
    mechanics = json.loads(AUTHORITY.read_text(encoding="utf-8"))["mechanics"]
    rules = json.loads(RULES_TEXT.read_text(encoding="utf-8"))
    return mechanics, rules


def _printed(text):
    match = HEADER.search(text)
    return None if match is None else match.group(1).strip().lower()


def test_printed_concentration_headers_match_authority_concentration():
    mechanics, rules = _rows()
    drift = []
    for mid, value in rules.items():
        printed = _printed(_text(value))
        if printed is None or mid not in mechanics or mid in SUB_OPTION_GAPS:
            continue
        if printed.startswith(("required", "yes")):
            want = True
        elif printed.startswith(("none", "no")):
            want = False
        else:
            drift.append((mid, printed, "unrecognized"))
            continue
        got = bool((mechanics[mid].get("duration") or {}).get("concentration"))
        if got != want:
            drift.append((mid, printed, got))
    assert drift == [], drift


def test_burial_drum_and_its_siblings_are_concentration():
    mechanics, _ = _rows()
    for mid in ("tianxia.tradition.spirit.thrum_of_the_grave.feature.burial_drum",
                "tianxia.subpath.qi.paper_cultivator.feature.paper_heaven",
                "insight.elemental-dominion"):
        assert (mechanics[mid].get("duration") or {}).get("concentration") is True, mid


def test_sub_option_gaps_are_still_real_and_listed():
    mechanics, rules = _rows()
    for mid in SUB_OPTION_GAPS:
        assert mid in rules and mid in mechanics, mid
        assert _printed(_text(rules[mid])) is not None, mid
