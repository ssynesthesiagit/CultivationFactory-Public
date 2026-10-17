"""Qiweaving Insight combat clauses, owned by hash-gated compiled rows.

Circuit Scholar:
- Prerequisite: Qiweaving sphere
- Ability Increase (Level Selection): Increase Int, Cha, or Wis by 1 (sheet-only)
- Intelligence check bonus for identifying spells, sphere techniques, talisman effects, or Active Qi Patterns:
  - Not proficient: add Proficiency Bonus
  - Proficient: add double Proficiency Bonus
"""
from __future__ import annotations

from . import hook
from .passive_rows import row_of
from ..ability_checks import skill_bonus, ability_modifier

BLOCK = "insights_qiweaving"
CIRCUIT_SCHOLAR = "insight.circuit-scholar"

IDENTIFICATION_SKILLS = {"Arcana", "Investigation", "Calligrapher's Supplies"}

OUTCOMES = {
    CIRCUIT_SCHOLAR: 'When you make an Intelligence check to identify a spell, sphere technique, talisman effect, or Active Qi Pattern, add your Proficiency Bonus if you are not already proficient. If you are proficient, add double your Proficiency Bonus.',
}


def owns(engine, actor, feature):
    return row_of(engine, actor.entity_id, BLOCK, feature) if actor is not None else None


@hook("compile_block")
def compile_rows(block, spec, row, numbers):
    if block != BLOCK:
        return None
    return [{**row, "kind": row["feature_id"], "pb": int(numbers["pb"]),
             "cl": int(numbers["cl"]), "choice_owner": 1,
             "player_outcome": OUTCOMES[row["feature_id"]]}]


def _is_identification_check(ctx, skill):
    """An identification check must be declared explicitly by its producer.

    A skill name alone is not enough: Arcana/Investigation/Calligrapher's
    Supplies are used for many unrelated checks. Producers set
    ``ctx.typed["identification"] = True`` (or ``check_purpose == "identification"``)
    when the check is genuinely an identification of a spell, sphere technique,
    talisman effect, or Active Qi Pattern.
    """
    typed = getattr(ctx, "typed", None) or {}
    if typed.get("identification") is True:
        return True
    if typed.get("check_purpose") == "identification":
        return True
    return False


def _proficiency_rank(engine, actor, skill, typed=None):
    """Authoritative proficiency rank for the skill at this check boundary.

    Read first from an explicit rank carried by the check context
    (``typed["skill_proficiency_rank"]``), then from the actor's typed bundle.
    The total skill bonus is never used to infer proficiency.
    """
    typed = typed or {}
    explicit = typed.get("skill_proficiency_rank")
    if isinstance(explicit, int) and explicit in (0, 1, 2):
        return explicit
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or ()
                   if row.get("actor_id") == actor.entity_id), {})
    ranks = bundle.get("skill_proficiency") or {}
    normalized = str(skill or "").replace("_", " ").casefold()
    for name, rank in ranks.items():
        if name.casefold() == normalized:
            if isinstance(rank, int) and rank in (0, 1, 2):
                return rank
            return None
    return None


@hook("check_bonus")
def circuit_scholar_check_bonus(ctx, actor):
    row = owns(ctx.engine, actor, CIRCUIT_SCHOLAR)
    if not row:
        return None

    typed = ctx.typed or {}
    ability = str(typed.get("ability") or "").upper()

    # Must be an Intelligence check
    if ability != "INT":
        return None

    # Must be an actual identification check, declared by the producer.
    if not _is_identification_check(ctx, typed.get("skill")):
        return None

    pb = int(row.get("pb") or 0)
    if pb == 0:
        return None

    skill = typed.get("skill")
    rank = _proficiency_rank(ctx.engine, actor, skill, typed)
    # Unknown rank is treated as not proficient (never double PB on a guess).
    is_proficient = rank is not None and rank >= 1

    # Not proficient: +PB, Proficient: +2*PB
    return pb if not is_proficient else 2 * pb


@hook("compile_passives")
def seal_existing(passives, info):
    numbers = info["numbers"]
    owned = info.get("owned_ids") or ()
    # Only add insights that are not already compiled via compile_block
    existing_feature_ids = {p.get("feature_id") for p in passives}
    additions = []
    for fid in (CIRCUIT_SCHOLAR,):
        if fid in owned and fid not in existing_feature_ids:
            additions.append({"block": BLOCK, "feature_id": fid,
                          "kind": fid, "player_outcome": OUTCOMES[fid],
                          "pb": int(numbers["pb"]), "cl": int(numbers["cl"]), "choice_owner": 1})
    return [*passives, *additions]