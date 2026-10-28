"""Beauty in Motion: optional 1 CP after 10 feet of own-turn movement.

The first accepted Factory opportunity attack consumes the trail and rolls the
printed Wisdom save. Failure uses the existing attack-negation state; success
puts Disadvantage on that attack. Querying OA eligibility or declining an OA
does not consume the trail. Accepted native Opportunity Attacks use the existing native reaction scope too.
"""
from typing import Any

from . import effect, hook

TALENT = "tianxia.talent.beauty.beauty_in_motion"
TRAIL = "condition:typed.beauty_motion"


@hook("compile_actions")
def activation(info: dict[str, Any]) -> list[Any] | None:
    if TALENT not in info["owned_ids"]:
        return None
    row = info["mechanics"][TALENT]
    if not any(e.get("type") == "beauty_motion" for e in row.get("effects") or []):
        return None
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.beauty_motion",
        display_name="Beauty in Motion", owner_id=info['actor_id'], economy=EconomyKind.NONE,
        resolution_kind="TYPED", target_kind="SELF", costs=((RESOURCE_IDS[info['primary']], 1),),
        parameters={"typed": {"effects": row['effects'], "riders": row['riders'],
            "numbers": info['numbers'], "duration": row['duration'], "source": TALENT},
            "expected_damage": 0, "player_only": True})]


def moved_this_turn(engine: Any, actor: Any) -> int:
    from ..gate2_runtime_models import Position

    feet = 0
    for event in reversed(engine.events):
        if event.actor_id != actor.entity_id:
            continue
        if event.event_type == "TURN_STARTED":
            break
        payload = event.payload or {}
        if event.event_type != "MOVEMENT_COMMITTED" or payload.get("forced") or payload.get("teleport"):
            continue
        path = [Position(**cell) for cell in payload.get("path") or []]
        feet += sum(engine.grid.distance_ft(a, b) for a, b in zip(path, path[1:]))
    return feet


@hook("candidate_allowed")
def allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if typed.get("source") == TALENT:
        return None if moved_this_turn(engine, actor) >= 10 else False
    return None


@effect("beauty_motion")
def trail(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import effect_expiry

    ctx.engine._remove_condition(ctx.actor, TRAIL, ctx.source)
    ctx.engine._apply_condition(ctx.actor, TRAIL, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, row, ctx.actor, condition=True),
        data={"dc": int(ctx.numbers['save_dc']), "label": "Beauty in Motion: first Opportunity Attack"})


@hook("opportunity_attempt")
def first_opportunity(ctx: Any, mover: Any) -> None:
    held = next((c for c in mover.conditions.values() if c.condition_id == TRAIL), None)
    if held is None:
        return
    engine, reactor = ctx.engine, ctx.actor
    dc = int(held.data["dc"])
    engine._remove_condition(mover, TRAIL, held.source_definition_id)
    saved = engine._roll_save(reactor, "WIS", dc, held.source_definition_id).total >= dc
    if saved:
        modifier_id = engine._add_modifier(reactor, held.source_definition_id, "attack_mode", "SET",
                             "DISADVANTAGE", "NEXT_ATTACK", expires_on="CONSUMED")
        from .beauty_insights import record_penalty
        record_penalty(engine, mover, reactor, held.source_definition_id, modifier_id)
    else:
        engine._typed_negated = {*getattr(engine, "_typed_negated", set()), (reactor.entity_id, mover.entity_id)}
    engine._append_event("PASSIVE_TRIGGERED", held.source_definition_id, actor_id=mover.entity_id,
        target_ids=(reactor.entity_id,), payload={"beauty_motion": True, "automatic_miss": not saved,
                                                "attack_disadvantage": bool(saved)})


@hook('native_attack_scope')
def native_opportunity(engine, frame):
    """Accepted native OA only; a scoped reply cannot leak to another strike."""
    if frame.get('source_id') != 'system:combat.opportunity_attack':
        return None
    mover = engine.state.actors.get(frame.get('target_id'))
    reactor = engine.state.actors.get(frame.get('actor_id'))
    held = next((c for c in mover.conditions.values() if c.condition_id == TRAIL), None) if mover else None
    if held is None:
        return None
    from contextlib import contextmanager

    @contextmanager
    def scope():
        engine._remove_condition(mover, TRAIL, held.source_definition_id)
        dc = int(held.data['dc'])
        saved = engine._roll_save(reactor, 'WIS', dc, held.source_definition_id).total >= dc
        engine._append_event('PASSIVE_TRIGGERED', held.source_definition_id, actor_id=mover.entity_id,
            target_ids=(reactor.entity_id,), payload={'beauty_motion': True, 'automatic_miss': not saved,
                                                     'attack_disadvantage': bool(saved)})
        if saved:
            from .beauty_insights import record_penalty
            record_penalty(engine, mover, reactor, held.source_definition_id, attack_source=frame['source_id'])
        previous = getattr(engine, '_beauty_native_opportunity', None)
        engine._beauty_native_opportunity = (reactor.entity_id, mover.entity_id, saved, held.source_definition_id)
        try:
            yield
        finally:
            engine._beauty_native_opportunity = previous
    return scope()


@hook('before_attack')
def native_outcome(engine, attacker, defender, intent, context):
    receipt = getattr(engine, '_beauty_native_opportunity', None)
    if receipt is None or receipt[:2] != (attacker.entity_id, defender.entity_id):
        return None
    return {'mode': 'DISADVANTAGE'} if receipt[2] else {'force_miss': True, 'source_id': receipt[3], 'label': 'Beauty in Motion'}
