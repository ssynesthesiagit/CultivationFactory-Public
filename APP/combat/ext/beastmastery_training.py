"""Beastmastery Training's printed skill proficiency (T14 base row, 2026-10-15).

Owner rules text (authority/typed_mechanics/rules_text.json,
``BEASTMASTERY_BASE_BEASTMASTERY_TRAINING``, "#### Beastmastery Training"):

  "When you learn Beastmastery:
   gain proficiency in Wisdom (Animal Handling);
   if already proficient, choose one Beastmastery talent for which you meet the
   prerequisites as a bonus talent;
   choose one Beastmastery Package: Rider or Tamer. You may later gain the other
   Package through Extra Beastmastery Package."

This plug-in implements the first printed clause and nothing else: a character
whose sheet lists the Beastmastery Training automatic component (what acquiring
the Sphere puts on the sheet, combat/table_advance.base_abilities and
sphere_component_authority.attach_sphere_automatic_component_receipt) rolls
Wisdom (Animal Handling) with proficiency. It runs only through the documented
``compile_skill_bonuses`` hook (combat/ext/__init__.py, "General opt-in skill
projections before every compiler skill consumer"), so it changes new bundle
compiles only: characters without the row, and fights saved before this change,
compile byte-for-byte as they did.

Proficiency never stacks. A sheet that already records Animal Handling as
proficient or Expertise keeps exactly that rank (the printed "gain proficiency"
cannot raise Expertise, and cannot add a second Proficiency Bonus), and a sheet
with no explicit proficiency rank at all is left alone with a diagnostic note,
the same rule the Expertise projection follows -- an unrelated total may already
contain the Proficiency Bonus, and that component is unknowable from the total.

When another owned record prints Expertise in this very skill
(combat/ext/general_flight_skills, general_skill_expertise), this provider
defers to it entirely: Expertise already contains proficiency, and only that
projection can preserve the character's independent adjustments. The deferral
makes the compile result identical whichever of the two providers the hook list
registers first.

The row's other two clauses are character-build grants and are NOT delivered
here: the acquisition pipeline has a new-sphere bonus-talent entitlement
(stage2/service.py "new_sphere_bonus_talent_acquisition"), but this packet does
not verify its printed "already proficient" condition, and the Rider/Tamer
Package choice has no recorded producer yet (both packages arrive as automatic
components). This plug-in claims neither, so it never marks the row automated.
"""

from __future__ import annotations

from typing import Any

from . import hook

TRAINING = "BEASTMASTERY_BASE_BEASTMASTERY_TRAINING"
SKILL = "Animal Handling"
ABILITY = "WIS"
SOURCE_LABEL = "Beastmastery Training"


@hook("compile_skill_bonuses")
def beastmastery_training_proficiency(info: dict[str, Any]) -> dict[str, Any] | None:
    """Add the printed Wisdom (Animal Handling) proficiency to a new bundle.

    Returns None for a character that does not own the row, and for a sheet
    that already records Animal Handling proficient or better, so unrelated
    characters, sheets and saved fights are untouched. No feature is claimed as
    handled: this row's bonus-talent and Package clauses are build grants this
    module does not implement.
    """
    owned = tuple(info.get("owned_ids") or ())
    if TRAINING not in owned:
        return None
    mechanics = info.get("mechanics") or {}
    if any(effect.get("type") == "general_skill_expertise" and str(effect.get("skill")).casefold() == SKILL.casefold()
           for source in owned for effect in ((mechanics.get(source) or {}).get("effects") or [])
           if isinstance(effect, dict)):
        # Another registered projection (combat/ext/general_flight_skills,
        # compile_skill_bonuses) prints Expertise in this very skill for this
        # character. Expertise already contains proficiency, and that provider
        # preserves independent adjustments this one cannot see; its reply owns
        # the row whichever registration order the hook list ends up in.
        return None
    rows = list(info.get("skills") or [])
    by_name = {str(row.get("skill")).casefold(): row for row in rows
               if isinstance(row, dict) and row.get("skill")}
    existing = by_name.get(SKILL.casefold())
    pb = int(info.get("pb") or 0)
    if existing is None:
        # A sheet that lists no Animal Handling row at all: the printed grant is
        # the ability modifier plus the Proficiency Bonus, nothing inferred.
        return {"skills": [{"skill": SKILL, "ability": ABILITY,
                     "bonus": int((info.get("mods") or {}).get(ABILITY, 0)) + pb,
                     "proficiency": "proficient", "proficiency_multiplier": 1,
                     "sources": [SOURCE_LABEL]}], "notes": []}
    from ..ability_checks import proficiency_rank

    rank = proficiency_rank(existing)
    if rank is None or rank >= 1:
        # Proficient or Expertise already: "gain proficiency" adds nothing and
        # never lowers a higher rank. Unknown legacy totals stay unknown.
        notes = [] if (rank or 0) >= 1 else [
            f"{SOURCE_LABEL} grants {SKILL} proficiency, but this sheet records no explicit "
            f"proficiency rank for {SKILL}; the printed total is left unchanged."]
        return {"notes": notes} if notes else None
    sources = sorted({*(str(value) for value in existing.get("sources") or []), SOURCE_LABEL})
    # The strict projection contract accepts only changed rows, and skill rolls
    # use the canonical name as their bundle lookup key.
    return {"skills": [{**existing, "skill": SKILL, "bonus": int(existing.get("bonus") or 0) + pb,
                                             "proficiency": "proficient",
                                             "proficiency_multiplier": 1,
                                             "sources": sources}], "notes": []}
