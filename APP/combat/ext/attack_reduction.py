"""Attack budgets shared by typed self/ally reductions, hit guards and soaks.

The reaction caller supplies its already rolled flat amounts after consent/payment.
Only explicit AttackDamage provenance joins packets: standalone, nested non-attack
damage and a different roll never borrow surplus. Type-limited portions retain
their own allowed types. Saved values contain only integer/string containers.
"""
from contextlib import contextmanager

from . import hook

RECORD = 'attack_reduction_budgets'


def key_for(provenance):
    return f'{provenance.attacker_id}:{provenance.target_id}:{provenance.roll_id}'


def current_key(engine, target):
    context = engine.damage_context()
    return key_for(context) if context is not None and context.target_id == target.entity_id else None


def consume(portions, pending, damage_type):
    for portion in portions:
        if portion['types'] and damage_type not in portion['types']:
            continue
        absorbed = min(pending, portion['remaining'])
        portion['remaining'] -= absorbed
        pending -= absorbed
    return pending


def packet_sequence(engine, target):
    """The existing damage-window event identifies a packet, including nesting."""
    return next((event.sequence for event in reversed(engine.events)
                 if event.event_type == 'REACTION_WINDOW_OPENED' and target.entity_id in event.target_ids
                 and event.payload.get('checkpoint') == 'DAMAGE_APPLICATION'), 0)


def remember(engine, target, pending, reduced, amounts, *, feature='', delivery='', source='', reactor_id='', infer_window=True):
    """Return the caller's reduction; keep unused flat portions for this hit only.

    amounts is [(integer amount, allowed uppercase damage-type strings)]. Empty
    types means all types. With no confirmed attack, preserve packet semantics.
    This is called only after a reaction has been accepted and paid for.

    feature is the accounting token: it may carry an owner and condition instance
    that the reaction_reduction_carried callback needs. source is the player-facing
    ability ID that a carried receipt names in the log; it defaults to feature.
    reactor_id is the creature that spent the Reaction (an ally's protection budget
    sits on the protected target); carried receipts name it as the actor.
    infer_window=False is for callers with no accepted damage window of their own
    (a parked pre-damage guard): such budgets get no feature rather than the
    incoming attack's DAMAGE_APPLICATION window.
    """
    key = current_key(engine, target)
    if key is None or not amounts:
        return reduced
    if not feature and infer_window:
        # Reduction budgets are created only inside an accepted damage reaction;
        # retain its event source even when no accounting callback is registered.
        feature = next((event.source_definition_id for event in reversed(engine.events)
                        if event.event_type == 'REACTION_WINDOW_OPENED'
                        and event.payload.get('checkpoint') == 'DAMAGE_APPLICATION'), '')
    source = source or feature
    portions = [{'remaining': max(0, int(amount)), 'types': list(types), 'packet': packet_sequence(engine, target),
                 'feature': feature, 'source': source, 'delivery': delivery, 'reactor': str(reactor_id or '')}
                for amount, types in amounts]
    consume(portions, pending, str(getattr(engine, '_typed_pending_damage_type', '') or '').upper())
    portions = [p for p in portions if p['remaining'] or feature]
    if portions:
        from ..paid_relocation import capture, retain_effect
        owner = capture(engine)
        for portion in portions:
            retain_effect(engine, portion, owner)
        records = target.turn_flags.setdefault(RECORD, {})
        records.setdefault(key, []).extend(portions)
    return reduced


def used(engine, target, feature):
    """An effect-wide interceptor must not regrant its budget on a later packet."""
    key = current_key(engine, target)
    return bool(key and any(p.get('feature') == feature
                           for p in (target.turn_flags.get(RECORD) or {}).get(key, [])))


def carry(engine, target, pending):
    """Apply surplus before offering another reaction for this damage packet."""
    key = current_key(engine, target)
    if key is None:
        return pending
    records = target.turn_flags.get(RECORD) or {}
    portions = records.get(key) or []
    packet = packet_sequence(engine, target)
    delivery = getattr(engine, '_typed_damage_packet', None) or {}
    interceptable = (delivery.get('weapon') and delivery.get('ranged') and delivery.get('kind') == 'weapon'
                     and delivery.get('interceptable', True))
    eligible = [portion for portion in portions if portion['packet'] != packet
                and (portion.get('delivery') != 'interceptable_weapon' or interceptable)]
    before = [(portion, portion['remaining']) for portion in eligible]
    reduced = consume(eligible, pending, str(getattr(engine, '_typed_pending_damage_type', '') or '').upper())
    for portion in eligible:
        portion['packet'] = packet
    from . import run_strict
    for portion, remaining in before:
        taken = remaining - portion['remaining']
        if taken and (portion.get('source') or portion.get('feature')):
            # Surplus belongs to the accepted defense that created this budget.
            # Publish its actual later consumption as a damage-checkpoint receipt;
            # the original reaction event describes only its first packet.
            engine._append_event('DAMAGE_REDUCTION_APPLIED', portion.get('source') or portion['feature'], actor_id=portion.get('reactor') or target.entity_id,
                target_ids=(target.entity_id,), payload={'checkpoint': 'DAMAGE_APPLICATION',
                    'reduction': taken, 'carried_budget': True,
                    'attack_roll_id': getattr(engine.damage_context(), 'roll_id', None)})
            from ..paid_relocation import causal_scope, effect_owner
            with causal_scope(engine, effect_owner(engine, portion)):
                if portion.get('feature'):
                    run_strict('reaction_reduction_carried', engine, target, portion['feature'], taken)
    return reduced


def apply_parked(engine, target, pending, parked, parts, reduced_by, reactor_id=''):
    """Subtract parked hit guards; each portion is named for its own guard (never the incoming attack).

    parts is [[feature, amount]] recorded by park(). Saved records from before parts existed fall back
    to the last guard's name, the only one they could name.
    """
    if not parts:
        parts = [[reduced_by[-1] if reduced_by else '', int(parked)]]
    for feature, amount in parts:
        before = pending
        pending = max(0, pending - int(amount))
        pending = remember(engine, target, before, pending, [(int(amount), ())], feature=str(feature), reactor_id=reactor_id, infer_window=False)
    return pending


def park(target, attacker_id, reduction, feature, *, engine=None, reactor_id=''):
    """Shared pre-damage hit guard receipt; the damage seam later binds the roll.

    Runtime callers pass engine so delayed hit_reduced/hit_absorbed consumers
    can resume the accepted guard's owner through follow_up_scope. The optional
    argument preserves existing pure fixture callers and saved flag bytes.
    """
    if reduction > 0:
        key = f'typed_hit_reduction:{attacker_id}'
        target.turn_flags[key] = int(target.turn_flags.get(key) or 0) + int(reduction)
        key = f'typed_hit_reduced_by:{attacker_id}'
        target.turn_flags[key] = [*(target.turn_flags.get(key) or []), str(feature)]
        # Each guard keeps its own amount so the receipt names the guard that actually reduced the hit.
        key = f'typed_hit_reduction_parts:{attacker_id}'
        target.turn_flags[key] = [*(target.turn_flags.get(key) or []), [str(feature), int(reduction), str(reactor_id or '')]]
        if engine is not None:
            from ..paid_relocation import capture, retain
            retain(engine, ('parked_reduction', id(target), attacker_id, str(feature)), capture(engine))


@contextmanager
def follow_up_scope(engine, target, attacker_id, feature):
    """Resume one guard's paid activation for its named delayed follow-up.

    Shared by Iron Empty Palm, Pressure Points, Needle and Fencing's aftermath.
    The hook's aggregate reducer list may contain several independent guards;
    each consumer selects its exact originating feature, retaining caller order
    and the existing aggregate before/after damage values. Missing receipts are
    unowned and never borrow the attacking foreground activation.
    """
    from ..paid_relocation import causal_scope, retained_owner
    receipt = retained_owner(engine, ('parked_reduction', id(target), attacker_id, str(feature)))
    with causal_scope(engine, receipt):
        yield


@hook('event')
def native_reduction(engine, event_type, kwargs):
    """Native numeric reactions publish the same paid budget in their receipt.

    This consumes an existing event contract without changing saved-fight code.
    Typed targets already use the quote seam, which also preserves type limits.
    """
    payload = kwargs.get('payload') or {}
    targets = kwargs.get('target_ids') or ()
    if (event_type != 'REACTION_RESOLVED' or payload.get('checkpoint') != 'DAMAGE_APPLICATION'
            or type(payload.get('reduction')) is not int or len(targets) != 1):
        return
    target = engine.state.actors.get(targets[0])
    reactor = engine.state.actors.get(kwargs.get('actor_id'))
    source = kwargs.get('source_definition_id') or next((event.source_definition_id for event in reversed(engine.events)
        if event.event_type == event_type and event.actor_id == kwargs.get('actor_id')
        and event.target_ids == tuple(targets) and event.payload == payload), '')
    if (target is None or reactor is None or target.entity_id in getattr(engine, 'typed_actor_ids', set())
            or source not in reactor.reaction_ids):
        return
    before, after = payload.get('pending_before'), payload.get('pending_after')
    if type(before) is int and type(after) is int:
        remember(engine, target, before, after, [(payload['reduction'], ())],
                 feature=source, source=source)


@hook('final_damage')
def native_carry(engine, target, amount, damage_type, source_id, source_actor_id, intent):
    if target.entity_id in getattr(engine, 'typed_actor_ids', set()):
        return None
    reduced = carry(engine, target, amount)
    return {'amount': reduced} if reduced < amount else None


@hook('attack_damage_final')
def finish(engine, attacker, target, provenance, intent):
    records = target.turn_flags.get(RECORD)
    if records is not None:
        records.pop(key_for(provenance), None)
        if not records:
            target.turn_flags.pop(RECORD, None)
