"""Read Foe (The Piercing Needle; needle-riders-1 2026-10-21). Rules text: the owner's Sphere Compendium,
"authority/typed_mechanics/rules_text.json":

  "Gain proficiency in Insight. If you already have proficiency in Insight, gain Expertise in Insight instead.
   You may take this talent twice. If you already have Expertise in Insight, you cannot take this talent again."

The skill grant is resolved when the character is compiled, before every skill read: the ``compile_skill_bonuses``
hook (combat/ext/__init__.py, "General rider flight and skill projections") sees the owned ids, the parsed skill rows
and the ability modifiers, and returns Insight's new total and rank. Each owned copy of the talent upgrades the skill
one step (untrained -> proficient -> Expertise), so a character that is already proficient gains Expertise from its
first copy and a second copy never goes past Expertise. Input is never mutated; other skills keep their rows, and a
character that does not own Read Foe gets no projection at all.

The second printed clause (may be taken twice, not again once Expert) is an acquisition rule the character builder
does not model: every talent is offered once, so the GM records the second copy. Typed data carries that clause as
the record's rider, and the fight side reads whatever copies the sheet holds.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

READ_FOE = "TAL_FENCING_READ_FOE"
SKILL = "Insight"
LABELS = {0: ("untrained", 0), 1: ("proficient", 1), 2: ("expertise", 2)}


@effect("needle_read_foe")
def read_foe(ctx: Any, eff: dict[str, Any]) -> None:
    """A compile-time projection only: the skill is already on the sealed character (compile_skill_bonuses)."""


def _copies(info: dict[str, Any]) -> int:
    return sum(1 for mid in (info["owner_sheet"].get("spheres_and_talents") or {}).get("learned_talent_record_ids", ()) if mid == READ_FOE)


@hook("compile_skill_bonuses")
def compile_read_foe(info: dict[str, Any]) -> dict[str, Any] | None:
    """Insight's printed proficiency, or Expertise when the character already has proficiency."""
    copies = _copies(info)
    if not copies:
        return None
    listed = info["skill_rows"].get(SKILL)
    rank = listed.rank if listed is not None else 0
    if rank is None:
        return {"skills": [], "notes": [f"{SKILL}: Read Foe needs the skill's recorded proficiency rank to keep its other "
                                        f"bonuses. Ask the table to record Insight's proficiency; the listed total is unchanged."]}
    wanted = min(2, rank + copies)
    if wanted == rank:
        return {"skills": [], "handled_features": [READ_FOE]}
    old = listed.total if listed is not None else info["mods"].get("WIS", 0)
    label, multiplier = LABELS[wanted]
    return {"skills": [{**(listed.source if listed is not None else {}), "skill": SKILL,
                        "bonus": old + (wanted - rank) * int(info["pb"]), "proficiency": label,
                        "proficiency_multiplier": multiplier, "expertise": wanted == 2}],
            "handled_features": [READ_FOE]}
