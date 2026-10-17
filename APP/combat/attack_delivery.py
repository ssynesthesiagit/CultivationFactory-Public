"""Shared classification for a strike's melee or ranged delivery profile."""


def is_ranged(profile, range_ft=None, weapon=None):
    """Return whether a strike uses ranged-attack rules.

    The printed attack profile takes precedence over target-selection range:
    unarmed and melee weapon strikes can still have a numeric reach. Generic
    ``weapon`` profiles use the per-variant ``weapon.attack_delivery`` value
    from the compiler when available; this distinguishes a melee weapon's
    ordinary strike from its thrown variant. Older sealed profiles may use
    ``kind``/``attack_kind`` and otherwise default to melee. Open-ended profiles
    retain their numeric-range fallback.
    """
    kind = str(profile or "").strip().lower().replace("-", "_").replace(" ", "_")
    if kind.endswith("ranged") or kind == "ranged":
        return True
    if (kind.endswith("melee") or kind in {"melee", "unarmed", "weapon", "melee_weapon"}
            or kind.endswith("_unarmed")):
        if kind == "weapon" and isinstance(weapon, dict):
            # Compiled attacks carry this explicit delivery because a weapon's
            # equipment kind (bow, dagger, etc.) does not identify the selected
            # variant: a thrown dagger has both melee and ranged attacks.
            weapon_kind = str(weapon.get("attack_delivery") or weapon.get("kind") or weapon.get("attack_kind") or "").lower()
            return weapon_kind in {"ranged", "weapon_ranged"}
        return False
    return range_ft is not None and int(range_ft or 0) > 5


# Native and typed delivery observers share the actual resolving spec. The
# owning subscriber enters this scope through attack_resolution_scope; without
# a subscriber no frame is installed and all queries return None.
from contextlib import contextmanager
from contextvars import ContextVar
_CURRENT = ContextVar('native_attack_delivery', default=None)


@contextmanager
def resolving(engine, actor, target, spec, *, buffer_attached=False):
    frame = (engine, actor.entity_id, target.entity_id, spec,
             {'enabled': bool(buffer_attached), 'queue': [], 'flushing': False, 'prepared': False})
    token = _CURRENT.set(frame)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def current(engine, source_actor_id, target_id, source_id=None, *, pending=False):
    """Authoritative resolving delivery; unknown source metadata stays unknown.

    The pending query additionally requires this confirmed primary damage
    packet. Standalone or attached after-impact damage cannot borrow a frame.
    No range/name/damage-type inference supplies a weapon or material tag.
    """
    frame = _CURRENT.get()
    if frame is None or frame[0] is not engine or frame[1] != source_actor_id:
        return None
    spec = frame[3]
    source = spec.get('resolution_source_id') or spec.get('source_definition_id')
    if source_id is not None and source != source_id:
        return None
    resolved_target = spec.get('resolved_target_id') or frame[2]
    if pending:
        packet = engine.damage_context()
        if (packet is None or packet.component not in ('primary', 'payload')
                or (packet.source_id, packet.attacker_id, packet.target_id) != (source, source_actor_id, target_id)):
            return None
        resolved_target = packet.target_id
    if resolved_target != target_id:
        return None
    actor = engine.state.actors.get(source_actor_id)
    if actor is None:
        return None
    from .attack_provenance import describe
    descriptor = describe(engine, actor, spec, source)
    effect = (spec.get('checkpoint_context') or {}).get('effect') or {}
    parameters = spec.get('parameters') or {}
    physical = effect.get('physical_projectile', parameters.get('physical_projectile')) is True
    from .observer_information import attack_effect_index
    action = engine.action_catalog.get(source)
    effect_index = attack_effect_index(action, effect) if action is not None else None
    return {'source': source, 'actor': source_actor_id, 'target': target_id,
            'weapon': descriptor['delivery'] == 'weapon', 'kind': 'weapon' if descriptor['delivery'] == 'weapon' else descriptor['delivery'],
            'ranged': bool(descriptor['ranged']), 'physical_projectile': physical, 'effect_index': effect_index,
            'source_cl': frame[4].get('source_cl'),
            'interceptable': effect.get('interceptable', parameters.get('interceptable', True)) is not False}



def bind_payload_context(engine, ctx):
    """Bind a confirmed typed hit to an opted-in native packet plan only."""
    frame = _CURRENT.get()
    provenance = ctx.attack_damage_context
    if (frame is not None and frame[0] is engine and frame[4]['enabled'] and provenance is not None
            and (provenance.attacker_id, provenance.target_id) == (frame[1], frame[3].get('resolved_target_id') or frame[2])):
        from .ext import run_strict
        allowed = run_strict('attack_packet_buffer_enabled', ctx.engine, ctx.actor, ctx.target, frame[3])
        if any(type(v) is not bool for v in allowed):
            raise ValueError('Attack packet buffer admission requires bool or None')
        frame[4]['enabled'] = any(v is True for v in allowed)
        if frame[4]['enabled']:
            frame[4]['context'] = ctx
            frame[4]['source_cl'] = int(ctx.numbers['cl']) if type(ctx.numbers.get('cl')) is int else None


def defer_attached(engine, ctx, callback):
    """Retain an actual pre-primary attached delivery until all packet dice exist."""
    frame = _CURRENT.get(); provenance = ctx.attack_damage_context
    if (frame is None or frame[0] is not engine or not frame[4]['enabled'] or frame[4]['flushing']
            or not ctx.defer_damage_notifications or provenance is None
            or (provenance.attacker_id, provenance.target_id) != (frame[1], frame[3].get('resolved_target_id') or frame[2])):
        return False
    frame[4]['queue'].append(callback)
    return True


def flushing_payload(engine, provenance):
    frame = _CURRENT.get()
    return bool(frame and frame[0] is engine and frame[4]['flushing'] and provenance is not None
                and (provenance.attacker_id, provenance.target_id) == (frame[1], frame[3].get('resolved_target_id') or frame[2]))


def flush_before_primary(engine, provenance):
    """Root dice have rolled; prepare ordinary attached damage, then commit it.

    No opt-in frame means no callback, allocation, event or changed ordering.
    Native typed delivery is still the sole producer of the component rolls.
    """
    frame = _CURRENT.get()
    if (frame is None or frame[0] is not engine or not frame[4]['enabled'] or provenance is None
            or provenance.component != 'primary'
            or (provenance.attacker_id, provenance.target_id) != (frame[1], frame[3].get('resolved_target_id') or frame[2])):
        return
    plan = frame[4]
    if plan['flushing'] or plan['prepared']:
        return
    plan['prepared'] = True
    ctx = plan.get('context')
    if ctx is not None:
        from .ext import run_strict
        run_strict('attack_payload_prepare', ctx)
    plan['flushing'] = True
    try:
        for callback in plan['queue']:
            callback()
    finally:
        plan['flushing'] = False
    plan['queue'].clear()


def primary_resolved(engine, target, provenance, intent):
    frame = _CURRENT.get()
    if (frame is not None and frame[0] is engine and frame[4]['enabled'] and provenance is not None
            and provenance.component == 'primary'
            and (provenance.attacker_id, provenance.target_id) == (frame[1], frame[3].get('resolved_target_id') or frame[2])):
        from .ext import run_strict
        run_strict('attack_packet_resolved', engine, target, provenance, intent)


def native_strike(engine):
    """Actual native single-weapon delivery adapter, or None for unknown metadata.

    This is an event adapter for ammunition and released-item producers. It
    grants no ownership, roll, attack, item or stock. Producers must still match
    the committed ATTACK_ROLLED identity before spending or publishing a unit.
    """
    frame = _CURRENT.get()
    if frame is None or frame[0] is not engine:
        return None
    spec = frame[3]; source = spec.get('resolution_source_id') or spec.get('source_definition_id')
    actor = engine.state.actors.get(frame[1]); action = engine.action_catalog.get(source)
    typed = spec.get('typed') or ((action.parameters or {}).get('typed') if action else {}) or {}
    attacks = [e for e in typed.get('effects', []) if e.get('type') == 'attack']
    if actor is None or action is None or action.owner_id != actor.entity_id or not typed.get('weapon') or len(attacks) != 1:
        return None
    target = engine.state.actors.get(spec.get('resolved_target_id') or frame[2])
    if target is None:
        return None
    if 'native_strike' not in frame[4]:
        from .typed_executor import Context
        ctx = Context(engine=engine, actor=actor, action=action, intent=getattr(engine, '_active_intent', None),
                      typed=typed, targets=[target], target=target, weapon_damage_dice=True)
        frame[4]['native_strike'] = {'engine': engine, 'actor_id': actor.entity_id, 'target_id': target.entity_id,
                                    'source': source, 'effect': attacks[0], 'roll_id': '', 'context': ctx}
    return frame[4]['native_strike']
