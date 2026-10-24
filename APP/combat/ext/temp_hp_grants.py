"""Recorded Temporary HP identity for Bark-Back and other hit-triggered guards.

Queries use the settled attack's exact roll and existing grant/damage receipts.
No extra fight state, expiry tokens, engine patching or guessed grant identity.
Shared grant_at_hit helper is used by verdant_chassis.py for Bark-Back's guard.

advance_grant() is this module's one reader of *whose* Temporary Hit Points a pool
is: Temporary Hit Points do not stack, so a smaller or equal offer is rejected and
the creature keeps the grant it already held. held_grant() answers the same
question for a whole fight's receipts and is used by wax_footing.py and
refined_golden_bell.py (ending only its activation's remaining pool), so an older
saved fight and a hit-triggered guard can never disagree about which ability put
a pool there.
"""


def advance_grant(current, payload, source, sequence):
    """The grant identity ``current`` becomes after one recorded ``TEMP_HP_GRANTED``.

    ``current`` is ``None`` or a ``(source_definition_id, pool it put there, sequence)`` triple, and the
    return value is the same shape. Only a receipt that actually raised the pool (``after > before``)
    establishes a new identity -- the engine keeps the larger pool (combat/gate2_engine.py
    ``_grant_temp_hp`` writes ``temporary_hp = max(before, offered)``), so a smaller or equal offer is
    rejected and the creature is still holding the grant it had. A receipt that emptied the pool leaves
    no grant at all; every other receipt leaves ``current`` exactly as it was.
    """
    payload = payload or {}
    before, after = int(payload.get("before") or 0), int(payload.get("after") or 0)
    if after > before:
        return (str(source or ""), after, int(sequence))
    if after < before and after == 0:
        return None
    return current


def held_grant(events, entity_id):
    """(source_definition_id, pool it put there, sequence) of the grant ``entity_id`` holds, or None.

    One pass over the fight's own receipts, reading identity only: whose Temporary Hit Points a creature
    is holding is decided by ``advance_grant`` and nothing else. Used by wax_footing to recover a
    Living Wax Form grant from a fight saved before that lane's own record existed.
    """
    held = None
    for event in events:
        if event.event_type != "TEMP_HP_GRANTED" or entity_id not in (event.target_ids or ()):
            continue
        held = advance_grant(held, event.payload, event.source_definition_id, event.sequence)
    return held


def grant_at_hit(ctx, target):
    """Return (source, grant sequence, remaining at hit), or None if unproven.

    Call only from a confirmed after_hit notification. Damage from this attack
    may consume the last Temporary HP before notification; earlier damage may
    not. A later accepted replacement invalidates the old grant. Rejected/equal
    offers retain the existing grant, matching the engine's max(before, offered).
    Typed Context.attack_result and native/portable AttackNotice carry roll_id.
    """
    notice = getattr(ctx, "attack_notice", None)
    roll_id = notice.roll_id if notice else (getattr(ctx, "attack_result", None) or {}).get("roll_id")
    if not roll_id:
        return None
    held = None  # (source, pool it put there, sequence), the same shape advance_grant reads and writes
    remaining = 0
    at_hit = None
    for event in ctx.engine.events:
        if target.entity_id not in event.target_ids:
            continue
        payload = event.payload or {}
        if event.event_type == "ATTACK_ROLLED" and payload.get("roll_id") == roll_id:
            at_hit = (event.sequence, held, remaining)
        elif event.event_type == "TEMP_HP_GRANTED":
            held = advance_grant(held, payload, event.source_definition_id, event.sequence)
            remaining = int((payload or {}).get("after") or 0)
        elif event.event_type == "DAMAGE_COMMITTED":
            remaining = max(0, remaining - int(payload.get("temporary_hp_absorbed") or 0))
    if at_hit is None or at_hit[1] is None or at_hit[2] <= 0 or held != at_hit[1]:
        return None
    # The caller wants the grant's sequence to file the round it answered on, and how many points were left at the hit.
    return (at_hit[1][0], at_hit[1][2], at_hit[2])


LIFETIME = 'condition:typed.temp_hp_lifetime'


def lifetime_for(actor, grant_sequence):
    """Exact accepted grant's optional native lifetime, never a later offer's."""
    return next((c for c in actor.conditions.values() if c.condition_id == LIFETIME
                 and c.data.get('grant_sequence') == grant_sequence), None)


def rebind_lifetime(engine, actor, marker, *, after_sequence):
    """Retain the original deadline when an explicitly suppressed pool returns."""
    grant = held_grant(engine.events, actor.entity_id)
    if grant is None or grant[0] != marker.source_definition_id or grant[2] <= after_sequence:
        return
    from .retained_updates import record_instance_update
    marker.data = {**marker.data, 'grant_sequence': grant[2]}
    record_instance_update(engine, actor, 'condition', marker.instance_id, marker)


def _capture_lifetime(ctx, row):
    from contextlib import contextmanager
    @contextmanager
    def capture():
        first = len(ctx.engine.events)
        yield
        from ..typed_executor import effect_expiry
        grants = [e for e in ctx.engine.events[first:] if e.event_type == 'TEMP_HP_GRANTED'
                  and e.source_definition_id == ctx.source and e.actor_id == ctx.actor.entity_id
                  and int(e.payload.get('after') or 0) > int(e.payload.get('before') or 0)]
        for grant in grants:
            for aid in grant.target_ids:
                actor = ctx.engine.state.actors[aid]
                expires = effect_expiry(ctx, row, actor, condition=True, fallback=None)
                if expires in (None, '', 'UNTIL_REMOVED'):
                    continue
                ctx.engine._apply_condition(actor, LIFETIME, ctx.source, ctx.actor.entity_id,
                    expires_on=expires, data={'grant_sequence': grant.sequence,
                    'source_cl': int(ctx.numbers.get('cl') or 0),
                    'label': 'Temporary Hit Points retain their original source duration'})
    return capture()


from . import hook


@hook('effect_resolution_scope')
def capture_timed_grant(ctx, row):
    """Opt-in exact grant lifetime; unrelated fights keep their event bytes."""
    if row.get('type') != 'temp_hp' or not (row.get('expires_on') or row.get('duration')):
        return None
    from . import run_strict
    replies = run_strict('temp_hp_lifetime_required', ctx, row)
    if any(type(r) is not bool for r in replies):
        raise ValueError('temp_hp_lifetime_required must return a boolean or None')
    return _capture_lifetime(ctx, row) if any(replies) else None


@hook('event', nested=True)
def end_timed_grant(engine, event_type, kwargs):
    ended = kwargs.get('ended_effect') or {}
    if event_type != 'CONDITION_REMOVED' or ended.get('condition_id') != LIFETIME:
        return
    for aid in kwargs.get('target_ids') or ():
        actor = engine.state.actors[aid]
        grant = held_grant(engine.events, aid)
        if grant is None or grant[2] != ended['data']['grant_sequence'] or actor.temporary_hp <= 0:
            continue
        before = actor.temporary_hp
        actor.temporary_hp = 0
        engine._append_event('TEMP_HP_GRANTED', ended['source_definition_id'],
            actor_id=ended['source_actor_id'], target_ids=(aid,),
            payload={'offered': 0, 'before': before, 'after': 0, 'removed_by': 'Its original duration ended'})
