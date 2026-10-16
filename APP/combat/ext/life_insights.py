"""Life-path Insights riding the Life sphere's own abilities (OPUS1 batch 4).

Iron Mercy   when the owner uses Empathic Transfer and takes an affliction onto itself (life_riders'
             ``life_take_affliction``), it gains a bodily buffer of Temporary Hit Points equal to Constitution modifier
             + Proficiency Bonus, recorded against that one affliction. The buffer is not ordinary Temporary Hit Points:
             it can absorb only damage or Hit Point loss caused directly by the recorded affliction, so it is kept as its
             own condition (amount, affliction instance) and never enters ``temporary_hp``. It ends when the recorded
             affliction ends. Of the afflictions Empathic Transfer can move (life_riders.CONDITIONS) none deals damage
             at this table, so the buffer is shown and expires correctly but has nothing to absorb today. A future damaging
             affliction needs a delivery seam naming its instance before the buffer can be drawn on.

The row is sealed into block ``life_insights`` (kind = Insight id); every hook returns at once without it. Integers
and strings only are stored.
"""
from __future__ import annotations

from typing import Any

from . import hook, note
from .passive_rows import row_of

BLOCK = "life_insights"
IRON_MERCY = "insight.iron-mercy"
BUFFER = "condition:typed.iron_mercy_buffer"
OUTCOMES = {
    IRON_MERCY: "When you take an affliction with Empathic Transfer, you gain Temporary Hit Points equal to your Constitution "
                "modifier + Proficiency Bonus that protect only against damage from that affliction and last as long as it does",
}


@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    feature = row["feature_id"]
    return [{**row, "kind": feature, "player_outcome": OUTCOMES[feature], "pb": int(numbers["pb"]), "cl": int(numbers["cl"])}]


def _transferring(engine: Any) -> bool:
    """The action now resolving (the last accepted intent) carries Empathic Transfer's ``life_take_affliction``."""
    accepted = next((e for e in reversed(engine.events) if e.event_type == "INTENT_ACCEPTED"), None)
    action = (getattr(engine, "action_catalog", None) or {}).get(accepted.source_definition_id) if accepted is not None else None
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    return any(isinstance(row, dict) and row.get("type") == "life_take_affliction" for row in typed.get("effects") or [])


@hook("event")
def iron_mercy_buffer(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type == "CONDITION_REMOVED":
        _release(engine, kwargs)
        return
    if event_type != "CONDITION_APPLIED":
        return
    payload = kwargs.get("payload") or {}
    actor = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    row = row_of(engine, actor.entity_id, BLOCK, IRON_MERCY) if actor is not None else None
    if row is None or tuple(kwargs.get("target_ids") or ()) != (actor.entity_id,):
        return
    from .life_riders import CONDITIONS

    condition_id = str(payload.get("condition_id") or "")
    name = condition_id.removeprefix("condition:typed.")
    instance_id = str(payload.get("instance_id") or "")
    if name not in CONDITIONS or instance_id not in actor.conditions or not _transferring(engine):
        return
    from ..ability_checks import ability_modifier

    amount = max(0, ability_modifier(actor, "CON") + int(row["pb"]))
    label = name.replace("_", " ").title()
    engine._apply_condition(actor, BUFFER, IRON_MERCY, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"amount": amount, "affliction_instance_id": instance_id, "affliction": name,
                                  "label": f"Iron Mercy: {amount} Temporary Hit Points against {label} damage only"})
    note(engine, f"passive:{IRON_MERCY}", actor,
         f"Iron Mercy: {actor.display_name} takes {label} with Empathic Transfer and gains {amount} Temporary Hit Points "
         f"that protect only against damage from that {label}; they end when it ends.")


def _release(engine: Any, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    ended = str(payload.get("instance_id") or "")
    for target_id in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(target_id)
        if actor is None:
            continue
        for iid, condition in list(actor.conditions.items()):
            if condition.condition_id == BUFFER and condition.data.get("affliction_instance_id") == ended:
                actor.conditions.pop(iid)
                engine._append_event("CONDITION_REMOVED", IRON_MERCY, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                     payload={"instance_id": iid, "condition_id": BUFFER, "reason": "AFFLICTION_ENDED"})
