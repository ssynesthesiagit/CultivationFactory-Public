"""Native, transactional outcome seams shared by roll-intervention abilities.

Producers call resolved only after floors, defenses and forced outcomes settle,
before dependent effects. Natural death-save exceptions belong to the producer.
Automatic results carry their actual condition/source, never a guessed label.
"""
from . import ext

# Transactional combat calls may reconstruct engine wrappers during one roll's
# event delivery. Scope receipts by stable match and roll ids, not Python object.
_DELIVERED_ROLLS: dict[str, set[str]] = {}


def resolved(engine, roll, success, *, dc=None, ac=None, fixed=False, context=None):
    """Notify strict observers once per roll across transactional engine reloads."""
    roll_id = getattr(roll, 'roll_id', None)
    if roll_id is not None:
        match_id = str(getattr(engine.state, 'match_id', 'unknown'))
        delivered = _DELIVERED_ROLLS.setdefault(match_id, set())
        if roll_id in delivered:
            return
        delivered.add(roll_id)
        # Old matches cannot emit new rolls; bound process-local receipts.
        if len(_DELIVERED_ROLLS) > 256:
            oldest = next(iter(_DELIVERED_ROLLS))
            if oldest != match_id:
                _DELIVERED_ROLLS.pop(oldest, None)
    frame = dict(context or engine.d20_context(roll) or {})
    frame.update(dc=dc if dc is not None else frame.get('dc'),
                 ac=ac if ac is not None else frame.get('ac'), fixed=bool(fixed))
    ext.run_strict('roll_resolved', engine, roll, bool(success), frame, engine._active_intent)


def automatic(engine, target, outcome, *, source_id, source_actor_id=None, source_cl=None,
              authority=None, context=None):
    """Return whether a source-owned automatic result still applies.

    Unknown source authority/CL stays unknown. A subscriber may return False to
    require the normal roll. Every forcing source is considered independently.
    """
    if source_cl is None:
        from .feature_access import source_level
        source_cl = source_level(engine, engine.state.actors.get(source_actor_id), source_id)
    if type(source_cl) is not int or source_cl < 1:
        source_cl = None
    frame = {**(context or engine.d20_context() or {}), 'outcome': outcome,
             'source_id': source_id, 'source_actor_id': source_actor_id,
             'source_cl': source_cl, 'authority': authority, 'actor_id': target.entity_id}
    answers = ext.run_strict('automatic_result', engine, target, frame, engine._active_intent)
    if any(type(answer) is not bool for answer in answers):
        raise ValueError('automatic_result must return bool or None')
    return not any(answer is False for answer in answers)


def defer_save(engine, roll, *, fixed=False):
    """Retain native metadata until the typed save's final consumer settles."""
    from .paid_relocation import preserve_pending
    preserve_pending(engine, '_native_resolved_saves')
    engine.__dict__.setdefault('_native_resolved_saves', {})[roll.roll_id] = {
        'context': engine.d20_context(roll), 'fixed': bool(fixed)}


def complete_save(engine, roll, success, *, dc, fixed=False):
    from .paid_relocation import preserve_pending
    preserve_pending(engine, '_native_resolved_saves')
    pending = engine.__dict__.setdefault('_native_resolved_saves', {}).pop(roll.roll_id, {})
    resolved(engine, roll, success, dc=dc, fixed=bool(fixed or pending.get('fixed')), context=pending.get('context'))


def check_receipt(engine, event):
    """Native CHECK_ROLLED consumers publish their final totals and outcome.

    Covers auxiliary check producers without moving their draw/consumption order.
    No inference of DC for unknown-DC events or a non-rolled opposing DC record.
    """
    if event.event_type != 'CHECK_ROLLED' or type(event.payload.get('success')) is not bool:
        return
    from .gate2_runtime_models import RollRecord
    payload = event.payload
    actor = payload.get('actor') or {}
    target = payload.get('target') or {}
    fixed = bool(payload.get('forced_result'))
    actor_dc = payload.get('dc')
    if actor_dc is None and target.get('total') is not None:
        actor_dc = target['total'] + 1
    for row, success, dc in ((actor, payload['success'], actor_dc),
                             (target, not payload['success'], actor.get('total'))):
        if row.get('natural_result') is None or dc is None:
            continue
        record = RollRecord.model_validate({key: value for key, value in row.items() if key in RollRecord.model_fields})
        resolved(engine, record, success, dc=dc, fixed=fixed,
                 context={'kind': 'check', 'actor_id': record.actor_id, 'source_id': event.source_definition_id})
