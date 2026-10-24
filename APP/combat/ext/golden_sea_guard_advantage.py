"""Refined Golden Blood Root -- Golden Sea Guard's next-save Advantage (RW172 review finding 1).

Printed (authority/typed_mechanics/rules_text.json, ...golden_sea_guard rider): "When Golden Sea Guard reduces damage from
poison, necrotic damage, curse-pressure, possession-pressure, demonic pressure, hostile body suppression, or a comparable
corruptive/suppressive source, you have Advantage on the next eligible saving throw against that same source before the
start of your next turn."

The reduction itself is the typed damage_modifier in tabik.json. This plug-in is the follow-up: it observes the
Guard's own accepted REACTION_RESOLVED (the damage reduction was applied to the owner), and only then records a
source-keyed condition. The owner's next save against that same attacker consumes it (Advantage), and it expires at the
start of the owner's next turn. Same shape as Saint-Body Frame (foundation_sacred_body.py).

Gates: the owner must hold the Refined Golden Blood Root row; the reduced packet must be hostile and aimed at the owner;
its damage type or pressure kind must be one of the printed corruptive/suppressive sources; and the source must be a
creature (the save key). Other owners and other reactions are inert.
"""

from __future__ import annotations

from typing import Any

from . import hook

GUARD = "foundation.ancient_desolate_sacred_body_v0_2C.golden_sea_guard"
REFINED = "foundation.ancient_desolate_sacred_body_v0_2C.refined_golden_blood_root"
FOLLOW = "condition:typed.golden_sea_guard_next_save"
_SOURCES = {"poison", "necrotic", "curse", "possession", "demonic", "body_suppression", "drain", "source_corruption"}


def _refined(engine: Any, owner_id: str) -> bool:
    return any(row.get("feature_id") == REFINED for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(owner_id, []))


@hook("event", nested=True)
def guard_next_save(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "REACTION_RESOLVED" or kwargs.get("source_definition_id") != GUARD:
        return
    owner_id = kwargs.get("actor_id")
    payload = kwargs.get("payload") or {}
    if not owner_id or not _refined(engine, owner_id) or type(payload.get("reduction")) is not int or payload["reduction"] <= 0:
        return
    from ..pending_damage import current

    packet = current(engine)
    if not packet or not packet.hostile or packet.target_id != owner_id or not packet.source_actor_id:
        return
    kinds = {str(packet.damage_type or "").lower(), str(packet.pressure_kind or "").lower()}
    if not kinds & _SOURCES:
        return
    owner = engine.state.actors.get(owner_id)
    if owner is None or not owner.active:
        return
    source = engine.state.actors.get(packet.source_actor_id)
    name = source.display_name if source is not None else "that source"
    engine._apply_condition(owner, FOLLOW, GUARD, owner_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"against": packet.source_actor_id,
                                  "label": f"Advantage on the next eligible saving throw against {name}"})


@hook("save")
def next_save_advantage(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    held = [iid for iid, c in subject.conditions.items() if c.condition_id == FOLLOW and (c.data or {}).get("against") == ctx.actor.entity_id]
    if not held:
        return None
    condition = subject.conditions.pop(held[0])
    ctx.engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=subject.entity_id, target_ids=(subject.entity_id,),
                             payload={"condition_id": FOLLOW, "instance_id": held[0], "reason": "CONSUMED"})
    return {"bonus": 0, "modes": ["ADVANTAGE"]}
