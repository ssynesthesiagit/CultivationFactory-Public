"""Grounding Breath - Lightning Body (lane 5, 2026-09-29): "When you make a saving throw against lightning damage, thunder
damage, paralysis, being knocked Prone, or being forcibly moved by a lightning or thunder effect, you may add your
Proficiency Bonus if you are not already adding it. Once you use this benefit, you cannot use it again until the start of
your next turn."

A ``save`` hook (documented in combat/ext/__init__.py) adds the Proficiency Bonus to a typed save when the save's failure
names one of those things. Its owner may decline the benefit through the normal choice transport. The used flag is a plain
turn flag on the creature, which the engine clears when that creature's own next turn starts.

How each clause is read:
- lightning / thunder damage: the failed-save damage row names exactly that one type ("damage:lightning" is offered to the
  hook by typed_executor.block_save); a row that still chooses its type at the damage roll is not counted.
- paralysis, being knocked Prone: the failed branch imposes the Paralyzed or Prone condition, whatever the source.
- forcibly moved by a lightning or thunder effect: the failed branch moves the creature and the technique it comes from
  deals lightning or thunder damage.
- Recorded proficient saves are sealed during compilation; their bonus is not doubled.

Ownership at fight time is the "grounding_breath" passive row (combat/rules/feature_blocks.d/auto_lane5.json).
"""

from __future__ import annotations

from typing import Any

from . import hook

FLAG = "grounding_breath_used"
ELEMENTS = frozenset({"lightning", "thunder"})


@hook("compile_block")
def grounding_breath_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    return [{**row, "block": "grounding_breath"}] if block == "grounding_breath" else None


def _owns(engine: Any, actor_id: str) -> bool:
    return any(row.get("block") == "grounding_breath" for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor_id, []))


def _technique_is_elemental(ctx: Any) -> bool:
    from ..typed_executor import _walk_rows

    return any(row.get("type") == "damage" and len({str(kind).lower() for kind in row.get("damage_types") or []}) == 1
               and str(row["damage_types"][0]).lower() in ELEMENTS for row in _walk_rows((getattr(ctx, "typed", None) or {}).get("effects")))


@hook("save")
def grounding_breath(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if subject.turn_flags.get(FLAG) or not _owns(ctx.engine, subject.entity_id):
        return None
    wanted = {str(value).lower() for value in named or ()}
    qualifies = bool(wanted & {"damage:lightning", "damage:thunder", "paralyzed", "prone"}) \
        or ("forced_movement" in wanted and _technique_is_elemental(ctx))
    if not qualifies:
        return None
    rows = (getattr(ctx.engine, "typed_passive_rows", {}) or {}).get(subject.entity_id, [])
    if any(str(ability).upper() in row.get("proficient_saves", [])
           for row in rows if row.get("block") == "grounding_breath"):
        return None
    from . import needle
    source = "TAL_LIGHTNING_GROUNDING_BREATH"
    chosen = needle.ask(ctx.engine, ctx.intent,
                        needle.checkpoint_id(ctx.engine, "grounding_breath", subject.entity_id, str(ability)),
                        subject, needle.CHOICE + "grounding_breath", ["add_proficiency"],
                        labels={"add_proficiency": f"Add +{subject.proficiency_bonus} to this saving throw"},
                        allow_decline=True, prompt=f"Grounding Breath: add +{subject.proficiency_bonus} to {subject.display_name}'s "
                        f"{str(ability).upper()} saving throw? Once used, this benefit returns at the start of your next turn.",
                        name="Grounding Breath", feature_id=source, target_id=subject.entity_id)
    if not chosen:
        return None
    subject.turn_flags[FLAG] = True
    ctx.engine._append_event("PASSIVE_TRIGGERED", f"ext:{__name__}.grounding_breath", actor_id=subject.entity_id, target_ids=(subject.entity_id,),
                             payload={"trigger": f"Grounding Breath: {subject.display_name} adds its Proficiency Bonus (+{subject.proficiency_bonus}) "
                                                 f"to the {str(ability).upper()} save; not again until its next turn starts."})
    return {"bonus": int(subject.proficiency_bonus), "modes": []}


@hook("compile_actions")
def grounding_save_proficiency(info: dict[str, Any]) -> None:
    """Seal explicit compiler proficiency provenance alongside the passive.

    The final recorded save total is left intact, including unrelated bonuses
    and penalties. Its magnitude cannot tell us whether proficiency is present.
    """
    for row in info["passives"]:
        if row.get("block") == "grounding_breath":
            row["proficient_saves"] = list(info["save_proficiencies"])
