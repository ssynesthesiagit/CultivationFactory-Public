"""Ability-check modifiers shared by restraint, skill, Hidden Eye and mount checks.

Summons persist their own score modifiers separately from saves, which may use
their owner's statistics. Older compiled checks and roster templates retain
their historical numbers when no separate modifier source is available.
"""
from typing import Any


def ordinary_check_bonus(engine: Any, actor: Any, ability: str, skill: str, *,
                         numbers: dict[str, Any] | None = None) -> int | None:
    """Recorded skill or ordinary modifier; None means the check is unsupported.

    Used by optional Study actions, including native and older catalogues.
    Saving-throw proficiency cannot reveal an ordinary ability modifier.
    No missing statistic is invented and existing legacy callers stay unchanged.
    """
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or ()
                   if row.get("actor_id") == actor.entity_id), {})
    value = (bundle.get("skills") or {}).get(skill, (actor.skills or {}).get(skill))
    if value is not None:
        return int(value)
    for modifiers in ((getattr(actor, "summon", None) or {}).get("ability_mods") or {},
                      (numbers or {}).get("ability_mods") or {}):
        if ability.upper() in modifiers:
            return int(modifiers[ability.upper()])
    return None


def proficiency_rank(row: dict[str, Any]) -> int | None:
    """Explicit skill proficiency for the compiler, Expertise grants and roll exclusions.

    Totals cannot distinguish proficiency from unrelated bonuses. Unknown legacy
    ranks remain unknown; no caller may infer Expertise from a large modifier.
    """
    rank = row.get("proficiency_multiplier")
    if type(rank) is int and rank in (0, 1, 2):
        return rank
    label = str(row.get("proficiency") or "").lower()
    if label in {"expertise", "proficient", "untrained", "none"}:
        return {"expertise": 2, "proficient": 1, "untrained": 0, "none": 0}[label]
    if row.get("expertise") is True:
        return 2
    if row.get("proficient") is False:
        return 0
    return None


def skill_proficiency_ranks(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Persist only explicit ranks alongside skill totals in new typed bundles."""
    return {str(row["skill"]): rank for row in rows if isinstance(row, dict) and row.get("skill") and type(row.get("bonus")) is int
            and (rank := proficiency_rank(row)) is not None}


def roll_skill_proficiency(engine: Any, actor: Any, roll: Any) -> int | None:
    """Read the rolled skill's provenance, for Fate and other PB stacking exclusions.

    Scoped opposed checks name their skill; native Hide/Search encode it in the
    reason. Old bundles without ranks and unnamed reaction checks stay unknown.
    """
    context = engine.d20_context(roll) or {}
    skill = context.get("skill")
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or ()
                   if row.get("actor_id") == actor.entity_id), {})
    ranks = bundle.get("skill_proficiency") or {}
    if not skill and str(roll.reason).startswith("CHECK:"):
        skill = str(roll.reason).rpartition(":")[2]
    normalized = str(skill or "").replace("_", " ").casefold()
    return next((rank for name, rank in ranks.items() if name.casefold() == normalized), None)


def skill_bonus(engine: Any, actor: Any, name: str, fallback: int) -> int:
    """Sheet skill total shared by Scoundrel and general opposed checks.

    Compiled bundle skills precede native actor skills; neither adds proficiency
    twice. The supplied ability modifier is used only when no skill is recorded.
    """
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or ()
                   if row.get("actor_id") == actor.entity_id), {})
    value = (bundle.get("skills") or {}).get(name, (actor.skills or {}).get(name))
    return int(value) if value is not None else int(fallback)


def key_modifier(engine: Any, actor: Any, *, numbers: dict[str, Any] | None = None) -> int:
    """The creature's own Key Ability modifier, the spellcasting ability this system casts from.

    Owner text, Minor Qi Arts: "Use your Key Ability as the spellcasting ability". Used by
    combat/typed_executor.resolve_opposed_check's ``kind: "key_ability"`` target check (a
    printed "its spellcasting ability check") and by combat/ext/contests.py, which ranks the
    printed alternatives a defender may choose between. A creature that compiled no numbers
    falls back to +2, the same default combat/ext/needle.py uses. Read-only.
    """
    if numbers is None:
        from .ext.needle import numbers_of

        numbers = numbers_of(engine, actor)
    value = (numbers or {}).get("key_mod")
    return int(value) if value is not None else 2


def ability_modifier(actor: Any, ability: str, *, numbers: dict[str, Any] | None = None,
                     fallback: int | None = None) -> int:
    """Own persisted modifier, then old compiled ability_mods, then legacy fallback.

    Callers may provide their existing fallback (e.g. a Dexterity score). This
    helper never changes saving throws or adds skill proficiency/check bonuses.
    """
    ability = ability.upper()
    for modifiers in ((getattr(actor, "summon", None) or {}).get("ability_mods") or {},
                      (numbers or {}).get("ability_mods") or {}):
        if ability in modifiers:
            return int(modifiers[ability])
    return int(actor.saving_throws.get(ability, 0) if fallback is None else fallback)


VISUAL_CONCEALMENT = "visual_concealment"
# The hazard a check carries when its outcome turns on sound: a Stealth check made
# to avoid being heard, a Perception check made by hearing. The engine's own
# checks declare it (combat/stealth.py: the Hide check avoids detection, which
# this engine models by sight and sound -- its detection counterpart, the Search
# check, is hearing-sensitive, since muffled sound gives it Disadvantage), so a
# scoped check mode (a check_against rule, or a check_mode rule's "hazards" list,
# typed_executor.check_modes) reaches exactly the checks that rely on sound and
# never an unrelated one. Any printed hazard name may be used; this one is the
# shared spelling for Sound-sphere abilities.
SOUND_RELIANCE = "sound_reliance"


def hide_check_mode(engine: Any, actor: Any) -> str:
    """The mode for a Dexterity (Stealth) check made to hide, from every source, including the scoped ones.

    Used by combat/stealth.py ``hide`` and by the two Hide attempts that roll their own die
    (combat/ext/eye_reflexive_stealth.py, combat/ext/riders14_eye.py ``vanish``). A Hide check is by its nature
    a check that relies on visual concealment, so it is the one Stealth check that carries the
    ``visual_concealment`` hazard: a printed "Disadvantage on Dexterity (Stealth) checks relying on visual
    concealment" (Radiance's Expose False Form) is filed as a ``check_against`` condition naming that hazard, and
    a Stealth check made for any other reason -- sneaking past on sound, or scent -- never names it and is left
    alone. ``check_mode`` itself is unchanged, so every other check and every existing saved fight is.
    """
    from .typed_executor import check_mode

    return check_mode(actor, "DEX", "Stealth", engine=engine, hazards=(VISUAL_CONCEALMENT,))
