"""Reviewed final typings (owner 2026-09-28) and the exact-text admission test that lets one replace carried typing (no model logs named here)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]

REVIEWED_FINAL = APP / "authority/typed_mechanics/reviewed_final.json"

# "weapon_delivery": a reviewed entry may null the text-derived delivery (weapon_delivery below) when only one printed option is an
# attack, so the rest of the ability is not made a weapon attack (rider lane C8: Ancestral Ascension's Warrior Authority).
# "min_cl": a printed "Prerequisite: CL N+" gate. It is character construction, not a fight rule, so it is
# enforced at admission (combat/ext/activation_requirements.py) instead of staying a GM rider.
_FINAL_FIELDS = ("effects", "options", "modifier", "activation", "riders", "range", "area", "cost", "use_limit", "duration", "target", "after", "min_cp_cost",
                 "min_cl", "weapon_delivery")
# Reviewed metadata that is copied when present and never required, so every existing
# reviewed_final row stays complete. ``notes`` holds what the reviewer wants recorded
# about the record rather than a rule the Game Master still has to rule on: a sentence
# saying the fight already applies the benefit, or why a printed line is out of scope.
# It never becomes a rider, so it can never contradict the manual clauses, and coverage
# counts riders only -- an annotation is not an unapplied rule.
_FINAL_OPTIONAL_FIELDS = ("reaction_target", "range_scale", "subject_relation", "allow_self_source", "notes", "description")
_OPTIONAL_SEAMS = ("weapon_delivery", "min_cl")


def load_finals() -> dict[str, dict]:
    """Every reviewed_final typing: reviewed_final.json, then one file per reviewer in reviewed_final.d/ (owner 2026-09-28)."""
    finals = json.loads(REVIEWED_FINAL.read_text(encoding="utf-8")).get("mechanics", {}) if REVIEWED_FINAL.is_file() else {}
    for extra in sorted((REVIEWED_FINAL.parent / "reviewed_final.d").glob("*.json")):
        for key, final in (json.loads(extra.read_text(encoding="utf-8")).get("mechanics") or {}).items():
            if key in finals:
                print(f"reviewed_final: {key} reviewed twice ({extra.name} wins)", file=sys.stderr)
            finals[key] = final
    return finals


def _typed_for_text(key: str, text_sha: str, finals: dict[str, dict]) -> bool:
    """Only a complete reviewed_final can replace carried typing for edited text.

    Proposals are unapproved and reviews/options passes replace only some fields.
    Selecting their new hash would exclude the earlier reviewed core, costs and
    modifier before carry runs. Keep typing the earlier text unless the final
    explicitly supplies every required override field (including None for absent
    fields). New optional delivery metadata does not invalidate older reviews.
    The final application in build() then owns the entire replacement.
    """
    final = finals.get(key) or {}
    # Weapon delivery and min_cl are default-inert optional seams. Reviews made
    # before a field was added remain complete; absence means no override.
    # Keep exact-text admission and every previously required field unchanged.
    return final.get("text_sha256") == text_sha and all(
        field in final for field in _FINAL_FIELDS if field not in _OPTIONAL_SEAMS)
