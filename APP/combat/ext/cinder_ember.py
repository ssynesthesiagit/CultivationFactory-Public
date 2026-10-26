"""Portable Cinder Touch / Revealing Ember (rules_text.json, CL3 Cinder Heart).

The legacy character adapter reports generic damage preparation and commitment;
this owner applies the selected Cinder Touch once per activation/turn, then its
ember and curated light only to the creature that actually received that bonus.
The ordinary factory compiler's Cinder Touch damage remains in its typed data.
"""

from __future__ import annotations

from typing import Any

from . import hook
from .printed_light import shed

EMBER = "passive:cinder.revealing_ember"
DAMAGE = "passive:cinder.touch_damage"
MARK = "condition:fire.revealing_ember"
CINDER_TOUCH = "tianxia.subpath.qi.cinder_heart_cultivator.feature.cinder_touch"
EXPIRES_ON = "START_OF_SOURCE_NEXT_TURN"


@hook("character_damage_amount", priority=100)
def cinder_damage(amount: int, engine: Any, actor: Any, target: Any, source: str, intent: Any,
                  context: dict[str, Any]) -> int | None:
    """One selected, damaging Qi activation adds PB Fire to one damaged creature."""
    if (DAMAGE not in actor.passive_ids or not context.get("qi_powered") or amount <= 0
            or intent is None or "USE_CINDER_TOUCH" not in intent.option_ids or context.get(DAMAGE)):
        return None
    engine._claim_once_per_turn(actor, DAMAGE)
    context[DAMAGE] = target.entity_id
    engine._append_event("PASSIVE_TRIGGERED", DAMAGE, actor_id=actor.entity_id, target_ids=(target.entity_id,),
                         payload={"added_damage": actor.proficiency_bonus, "damage_type": "FIRE"})
    return amount + actor.proficiency_bonus


@hook("character_damage_committed")
def revealing_ember(engine: Any, target: Any, actor: Any, damage_type: str, hp_damage: int, source_id: str,
                    context: dict[str, Any]) -> None:
    """The creature damaged by Cinder Touch bears one ember and its printed Dim Light."""
    if hp_damage <= 0 or EMBER not in actor.passive_ids or not target.active or context.get(DAMAGE) != target.entity_id:
        return
    for iid, held in list(target.conditions.items()):
        if held.condition_id == MARK and held.source_actor_id == actor.entity_id:
            engine._remove_condition_instance(target, iid, EMBER)
    engine._apply_condition(target, MARK, EMBER, actor.entity_id, expires_on=EXPIRES_ON,
                            data={"revealed_to": actor.entity_id, "range_ft": 60})
    shed(engine, target, CINDER_TOUCH, EMBER, actor.entity_id, EXPIRES_ON)
    engine._append_event("PASSIVE_TRIGGERED", EMBER, actor_id=actor.entity_id, target_ids=(target.entity_id,))
