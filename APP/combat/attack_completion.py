"""Transactional reactions after one attack and all of its typed hit/miss riders."""
from contextlib import contextmanager
from .attack_notifications import AttackNotice


def can_continue(engine, actor):
    """New strikes require an able attacker after a completion response.

    Shared by native sequences, separate typed blocks and portable attacks.
    Non-attack effects already triggered still finish. No subscribers is inert.
    """
    from . import ext
    if not ext.has('attack_completed'):
        return True
    from .attack_notifications import can_strike
    return (can_strike(actor)
            and (engine.state.terminal_result is None or getattr(engine, '_final_rider_active', False)))


@contextmanager
def deferred(engine, *, enabled=True):
    """Deliver after a compound effect succeeds, never from an unfinished pause.

    Nested boundaries share the outer queue; immutable notices retain the target
    and outcome at each attack. Restoration happens before response dispatch.
    """
    from . import ext
    if not enabled or not ext.has('attack_completed') or getattr(engine, '_attack_completion_queue', None) is not None:
        yield
        return
    queue = []
    engine._attack_completion_queue = queue
    try:
        yield
    finally:
        engine.__dict__.pop('_attack_completion_queue', None)
    for notice, intent in queue:
        _deliver(engine, notice, intent)


def notify(engine, actor, target, spec, intent, source, hit, attack_index=1, *, kind=None):
    """Notify once at the settled boundary; callbacks may make a legal new attack.

    Reactions produced here do not recursively reopen this same checkpoint.
    A declared terminal result is never reopened. Each consumer owns eligibility,
    consent, costs, reach, weapon choice and its per-turn limit. The immutable
    notice names the actual redirected target and cannot rewrite the original hit.
    Return whether at least one subscriber ran, for the typed sequence recheck.
    """
    from . import ext
    if (not ext.has('attack_completed') or getattr(engine, '_attack_completion_active', False)
            or getattr(engine, '_final_rider_active', False) or engine.state.terminal_result is not None):
        return False
    target = engine.state.actors.get(spec.get('resolved_target_id'), target)
    if kind is None:
        action = engine.action_catalog.get(source)
        parameters = spec.get('parameters') or (action.parameters if action else {})
        typed = parameters.get('typed') or {}
        kind = parameters.get('attack_kind') or ('weapon' if typed.get('weapon') else 'other')
    kind = kind if kind in ('weapon', 'unarmed') else 'other'
    melee = spec.get('reach_ft') is not None or spec.get('range_ft') is None
    provenance = getattr(engine, "_opportunity_attack_provenance", None)
    opportunity = bool(provenance and provenance[:2] == (actor.entity_id, target.entity_id)
                       and provenance[3] == source)
    notice = AttackNotice(source, actor.entity_id, target.entity_id, attack_index, bool(hit), melee, kind,
                          opportunity=opportunity, opportunity_trigger=provenance[2] if opportunity else "")
    queue = getattr(engine, '_attack_completion_queue', None)
    if queue is not None:
        queue.append((notice, intent))
        return False
    return _deliver(engine, notice, intent)


def _deliver(engine, notice, intent):
    from . import ext
    if (getattr(engine, '_attack_completion_active', False)
            or getattr(engine, '_final_rider_active', False) or engine.state.terminal_result is not None):
        return False
    old = getattr(engine, '_attack_completion_active', False)
    engine._attack_completion_active = True
    called = False
    try:
        for subscriber in ext.subscribers('attack_completed'):
            if engine.state.terminal_result is not None:
                break
            called = True
            if subscriber(engine, notice, intent) is not None:
                raise ValueError('attack_completed observers must return None')
        return called
    finally:
        engine._attack_completion_active = old
