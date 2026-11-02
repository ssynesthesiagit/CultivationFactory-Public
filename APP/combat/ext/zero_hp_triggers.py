"""Printed zero-HP notifications, independent of dying, death or map removal.

Uses pending_damage's immutable HP-before receipt and the executor's existing
chain deduplication. No owned watch/reaction means no events or state changes.
"""
from . import hook, run_checkpoint


@hook("state_event")
def fresh_zero(engine, event):
    if event.event_type == "HEALING_APPLIED":
        # Healing can enable another genuine transition even within one chain.
        # The ability's own turn/round clocks still govern its reward.
        scope = getattr(engine, "_typed_defeat_chain", None)
        if scope is not None:
            for target_id in event.target_ids:
                target = engine.state.actors.get(target_id)
                if target is not None and target.current_hp > 0:
                    scope["drop"].discard(target_id)
                    scope["own_kill"].discard(target_id)
        return
    if event.event_type != "DAMAGE_COMMITTED":
        return
    from ..pending_damage import current
    packet = current(engine)
    if packet is None or packet.hp_before <= 0 or packet.target_id not in event.target_ids:
        return
    target = engine.state.actors.get(packet.target_id)
    if target is None or target.current_hp != 0:
        return
    scope = getattr(engine, "_typed_defeat_chain", None)
    if scope is not None and target.entity_id in scope["drop"]:
        return
    run_checkpoint("fresh_zero_hp", engine, target, event.actor_id, event.source_definition_id)


@hook("fresh_zero_hp")
def notify(engine, target, attacker_id, source):
    from .. import typed_executor as te, typed_reactions as tr
    scope = getattr(engine, "_typed_defeat_chain", None) or {"drop": set(), "own_kill": set()}
    if target.entity_id not in scope["drop"]:
        scope["drop"].add(target.entity_id)
        te.run_kill_watches(engine, target)
        tr.on_creature_event(engine, target, "any_drop_to_zero")
    attacker = engine.state.actors.get(attacker_id)
    if attacker is not None and attacker.team_id != target.team_id and target.entity_id not in scope["own_kill"]:
        scope["own_kill"].add(target.entity_id)
        action = engine.action_catalog.get(source)
        # Triggered actions can be compiled only as reaction/passive rows, so
        # they have no catalog entry. Preserve their owned name in the prompt.
        rows = [*(getattr(engine, "typed_reaction_rows", {}) or {}).get(attacker.entity_id, []),
                *(getattr(engine, "typed_passive_rows", {}) or {}).get(attacker.entity_id, [])]
        name = action.display_name if action else next(
            (row.get("name") or row.get("source_name") for row in rows
             if row.get("feature_id") == source), None)
        tr.on_own_event(engine, attacker, target, "own_kill", source_id=source,
                        action_name=name or "Damage")
