"""Foundation combat boons and objective completed-event resource triggers.

Scope tags name this save's printed consequence, never an affinity sphere or
an action-name guess. Fresh reviewed effects opt in; frozen catalogs remain
unchanged. Native pressure owns generation, cap, round allowance and expiry.
Outward support is credited from its committed healing/temp-HP event so the
actual provider receives the trigger even when it resolves as a reaction
during another creature's turn.
"""
from . import effect, hook, note

BOON = 'condition:typed.foundations3_boon.'


def _hostile(a, b):
    return a is not None and b is not None and a.team_id != b.team_id


def _threat(action):
    """Require a sealed harmful outcome; a bare/staged roll is not pressure."""
    if action is None:
        return False
    damage = action.damage
    if damage is not None and damage.count * damage.sides + damage.modifier > 0:
        return True
    typed = action.parameters.get('typed') or {}
    if typed.get('weapon'):
        return True
    def harmful(value):
        if isinstance(value, dict):
            kind = value.get('type')
            if kind in {'damage', 'extra_damage'} and (value.get('dice') or int(value.get('flat') or 0) > 0
                    or value.get('formula') not in (None, '', 'none')):
                return True
            if kind == 'condition' and value.get('condition') in {
                    'poisoned','frightened','charmed','prone','grappled','restrained',
                    'stunned','paralyzed','incapacitated','blinded','deafened','exhaustion'}:
                return True
            if kind == 'forced_movement' and int(value.get('distance_ft') or 0) > 0:
                return True
            return any(harmful(v) for v in value.values() if isinstance(v, (dict,list)))
        return isinstance(value, list) and any(harmful(v) for v in value)
    return harmful(typed.get('effects') or [])


def _boons(subject):
    return [c for c in subject.conditions.values() if c.condition_id.startswith(BOON)]


def _boon_label(kind, grantor):
    """Name the roll that spends a boon and the deadline that ends it."""
    deadline = f"expires at the start of {grantor}'s next turn"
    return {
        'mirror': f'Advantage on your next save against fear, charm, illusions, dreams, curses, or forced spiritual movement; {deadline}.',
        'lotus': f'Advantage on your next save against poison, disease, rot, polluted water, sickness exhaustion, failed medicine backlash, or terrain contamination; {deadline}.',
        'ash': f'Advantage on your next save against fear, poison, disease, fire, necrotic harm, blood-loss, despair, or corpse/battlefield contamination; {deadline}.',
        'bitter': 'Advantage on your next attack, save, or ability check against a hostile creature; expires at the end of this turn.',
    }[kind]


def _matches(condition, source, subject, named):
    data = condition.data or {}
    if data.get('kind') == 'bitter':
        return _hostile(source, subject)
    tags = {str(t).lower() for t in named or ()}
    # Save dispatch names printed consequence categories as damage:fire,
    # while reviewed boon scopes store the underlying category (fire).
    tags.update(t.removeprefix('damage:') for t in tuple(tags) if t.startswith('damage:'))
    tags = {t.removeprefix('category:') for t in tags}
    return bool(tags.intersection(data.get('scope') or []))


@effect('foundations3_boon', harmful=False)
def boon(ctx, eff):
    from .. import typed_executor as te
    kind = eff['kind']
    subjects = [ctx.actor] if kind in ('bitter', 'ash') else (ctx.targets or [ctx.actor])
    subject = subjects[0]
    amount = (2 if kind == 'bitter' else 1) * int(ctx.numbers['pb']) + int(ctx.numbers['key_mod'])
    sub = te.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [subject], subject)
    te.run_effects(sub, [{'type': 'temp_hp', 'flat': max(0, amount), 'applies_to': 'target'}])
    duration = {'kind': 'until_end_of_turn' if kind == 'bitter' else 'until_start_of_your_next_turn'}
    expiry = te.effect_expiry(ctx, {'duration': duration}, subject, condition=True)
    cid = BOON + kind
    ctx.engine._remove_condition(subject, cid, ctx.source)
    ctx.engine._apply_condition(subject, cid, ctx.source, ctx.actor.entity_id, expires_on=expiry,
        data={'kind': kind, 'scope': list(eff.get('scope') or []), 'label': ctx.action.display_name + ': ' + _boon_label(kind, ctx.actor.display_name)})


@hook('save_roll_tags')
def boon_tags(ctx, subject, ability, named):
    # The native save dispatcher then sees exactly the same explicit tags as
    # the typed save reader. Absent boons leave its context unchanged.
    if _boons(subject) or _vessels(ctx.engine, subject):
        return sorted(named)
    return None


@hook('save_mode')
def boon_save(engine, subject, ability, dc, source_id, context):
    source = engine.state.actors.get(context.get('source_actor_id'))
    named = context.get('named') or context.get('conditions') or []
    tags = {str(t).lower() for t in named}
    tags.update(t.removeprefix('damage:') for t in tuple(tags) if t.startswith('damage:'))
    tags = {t.removeprefix('category:') for t in tags}
    vessel = any((not row['abilities'] or ability.upper()[:3] in row['abilities'])
                 and tags.intersection(row['against']) and _hostile(source, subject)
                 for row in _vessels(engine, subject))
    if vessel or any(_matches(c, source, subject, named) for c in _boons(subject)):
        return 'ADVANTAGE'
    return None


@hook('attack_roll_modes')
def surge_attacks(engine, actor, target):
    if _hostile(actor, target) and any((c.data or {}).get('kind') == 'bitter' for c in _boons(actor)):
        return ['ADVANTAGE']
    return None


@hook('ability_check_mode')
def surge_check(engine, actor, ability, skill, against):
    if _hostile(actor, against) and any((c.data or {}).get('kind') == 'bitter' for c in _boons(actor)):
        return 'ADVANTAGE'
    return None


@hook('event', nested=True)
def consume_boon(engine, event_type, kwargs):
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    if actor is None:
        return
    if event_type == 'SAVE_ROLLED':
        context = engine.d20_context() or {}
        source = engine.state.actors.get(context.get('source_actor_id'))
        for c in list(_boons(actor)):
            if _matches(c, source, actor, context.get('named') or context.get('conditions')):
                engine._remove_condition(actor, c.condition_id, c.source_definition_id)
    elif event_type == 'ATTACK_ROLLED':
        if any(_hostile(actor, engine.state.actors.get(t)) for t in kwargs.get('target_ids') or ()):
            engine._remove_condition(actor, BOON + 'bitter', kwargs.get('source_definition_id') or 'Heartfire Surge')
    elif event_type == 'CHECK_ROLLED':
        from .roll_context import check_receipts
        for aid, roll in check_receipts(kwargs):
            subject = engine.state.actors.get(aid)
            others = [engine.state.actors.get(t) for t in kwargs.get('target_ids') or ()]
            source = engine.state.actors.get(kwargs.get('actor_id'))
            if subject and (any(_hostile(subject, t) for t in others) or _hostile(subject, source)):
                engine._remove_condition(subject, BOON + 'bitter', kwargs.get('source_definition_id') or 'Heartfire Surge')


def _owns_generation(engine, actor, kind):
    return actor is not None and any(row.get('block') == 'generate'
        and 'foundations3_' + kind in row.get('on', [])
        for row in engine.typed_passive_rows.get(actor.entity_id, []))


def _generate(engine, actor, kind, source):
    from .. import pressure
    if pressure.generate(engine, actor, 'foundations3_' + kind):
        names = {'mirror':'Mirror Stillness', 'lotus':'Lotus Dew', 'bitter':'Bitter Heartfire', 'spirit':'Spirit-Source Dew', 'ash':'Funeral Ash'}
        note(engine, source, actor, actor.display_name + ' gains 1 ' + names[kind] + '. It expires at the end of their next turn and can be spent on a later event.')


def _perceives(engine, observer, source):
    from ..senses import perceives
    return perceives(engine, observer, source)


@hook('attack_completed')
def generate_after_attack(engine, notice, intent):
    source = engine.state.actors.get(notice.attacker_id)
    target = engine.state.actors.get(notice.target_id)
    owners = [a for a in engine.state.actors.values() if _owns_generation(engine, a, 'mirror')]
    if not _owns_generation(engine, source, 'bitter') and not owners:
        return
    if notice.hit or not _hostile(source, target) or not _threat(engine.action_catalog.get(notice.source_id)):
        return
    # A genuine attack against a perceived enemy with a possible hit, rather
    # than an impossible roll or self-created/friendly obstacle.
    roll = next((e for e in reversed(engine.events) if e.event_type == 'ATTACK_ROLLED'
                 and e.actor_id == source.entity_id and target.entity_id in e.target_ids), None)
    payload = roll.payload if roll else {}
    # Admission uses the accepted choice receipt, even when opposing modes
    # cancel. Imposed penalties do not identify attacker intention.
    if 'DISADVANTAGE' not in payload.get('chosen_attack_modes', []) and _perceives(engine, source, target):
        _generate(engine, source, 'bitter', notice.source_id)
    for owner in engine.state.actors.values():
        if owner.team_id == target.team_id and engine._distance_actor_to_actor(owner, target) <= 30 and _perceives(engine, owner, source):
            _generate(engine, owner, 'mirror', notice.source_id)


@hook('save_final')
def generate_after_save(ctx, subject, ability, named, failed):
    owners = [a for a in ctx.engine.state.actors.values() if _owns_generation(ctx.engine, a, 'mirror') or _owns_generation(ctx.engine, a, 'lotus')]
    if not _owns_generation(ctx.engine, subject, 'bitter') and not owners:
        return
    if not _hostile(ctx.actor, subject) or not _threat(ctx.action):
        return
    if failed:
        _pending(ctx.engine, subject, 'bitter', ctx.source)
    else:
        for owner in ctx.engine.state.actors.values():
            if owner.team_id == subject.team_id and ctx.engine._distance_actor_to_actor(owner, subject) <= 30 and _perceives(ctx.engine, owner, ctx.actor):
                _pending(ctx.engine, owner, 'mirror', ctx.source)
        tags = {str(t).lower() for t in named or ()}
        tags.update(t.removeprefix('damage:') for t in tuple(tags) if t.startswith('damage:'))
        tags = {t.removeprefix('category:') for t in tags}
        if tags.intersection({'poison','poisoned','disease','rot','polluted_water','sickness_exhaustion','terrain_contamination'}):
            for owner in ctx.engine.state.actors.values():
                if owner.team_id == subject.team_id and ctx.engine._distance_actor_to_actor(owner, subject) <= 30:
                    _pending(ctx.engine, owner, 'lotus', ctx.source)


@hook('action_completed')
def generate_after_support(engine, actor, economy, source):
    _flush(engine)
    _attrition(engine, source)


@hook('event', nested=True)
def generate_spirit_from_support(engine, event_type, kwargs):
    """Credit the actual healer on the committed support event, including reactions."""
    if event_type not in ('HEALING_APPLIED', 'TEMP_HP_GRANTED'):
        return
    payload = kwargs.get('payload') or {}
    if int(payload.get('after', 0)) <= int(payload.get('before', 0)):
        return
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    if not _owns_generation(engine, actor, 'spirit'):
        return
    for target_id in kwargs.get('target_ids') or ():
        target = engine.state.actors.get(target_id)
        if target is not None and target.entity_id != actor.entity_id \
                and engine._distance_actor_to_actor(actor, target) <= 30:
            _generate(engine, actor, 'spirit', kwargs.get('source_definition_id') or 'support')
            return


def _vessels(engine, subject):
    return [row for row in engine.typed_passive_rows.get(subject.entity_id, [])
            if row.get('block') == 'foundations3_vessel']


@hook('compile_block')
def compile_vessel(block, spec, row, numbers):
    if block != 'foundations3_vessel':
        return None
    return [{**row, 'abilities': list(spec['abilities']), 'against': list(spec['against'])}]


def _pending(engine, actor, kind, source):
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, '_foundations3_pending')
    pending = engine.__dict__.setdefault('_foundations3_pending', [])
    receipt = (actor.entity_id, kind, source)
    if receipt not in pending:
        pending.append(receipt)


def _flush(engine):
    if not engine.__dict__.get('_foundations3_pending'):
        return
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, '_foundations3_pending')
    for actor_id, kind, source in engine.__dict__.pop('_foundations3_pending', []):
        actor = engine.state.actors.get(actor_id)
        if actor is not None:
            _generate(engine, actor, kind, source)


@hook('technique_used')
def completed_saves(ctx):
    # Save outcomes are known before their consequences; generation waits
    # until the complete technique so a creature defeated by it gains nothing.
    _flush(ctx.engine)
    _attrition(ctx.engine, ctx.source)


def _attrition(engine, source):
    if not any(_owns_generation(engine, a, 'ash') for a in engine.state.actors.values()):
        return
    for event in reversed(engine.events):
        if event.event_type == 'INTENT_ACCEPTED':
            break
        if event.event_type != 'DAMAGE_COMMITTED':
            continue
        payload = event.payload or {}
        if str(payload.get('damage_type') or '').lower() not in {'fire','poison','necrotic'}:
            continue
        if int(payload.get('hp_damage') or 0) + int(payload.get('temporary_hp_absorbed') or 0) <= 0:
            continue
        attacker = engine.state.actors.get(event.actor_id)
        for target_id in event.target_ids:
            target = engine.state.actors.get(target_id)
            if _hostile(attacker, target) and target.current_hp < target.maximum_hp:
                _generate(engine, target, 'ash', source)
