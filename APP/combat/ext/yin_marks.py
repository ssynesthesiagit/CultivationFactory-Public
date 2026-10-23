"""Reviewed Yin mark choices; old sealed rows remain inert.

Twofold tracks its two original targets for the printed first-spend trigger;
refreshing a target's mark does not lose the entitlement. Transfers move only
the owner's currently held other mark and retain its deadline. Patient
Moon's expiration choice replaces the due instance through ordinary events and
can extend it only once; its move reapplies the normal next-owner-turn mark.
All choices use the existing transactional transport, including off-turn owners.
"""
from dataclasses import replace
from typing import Any
from . import effect, hook

TWO = 'TAL_YIN_TWOFOLD_WANING'
PATIENT = 'TAL_YIN_PATIENT_MOON_METHOD'
PAIR = 'condition:typed.yin_twofold_pair'
WATCH = 'condition:typed.yin_patient_watch'
ONCE = 'once_per_round:yin_patient'
MARK = 'Waning Mark'


def held(subject, owner):
    from ..typed_executor import mark_condition_id
    cid = mark_condition_id(MARK, owner.entity_id)
    return next((c for c in subject.conditions.values() if c.condition_id == cid), None)


def patient_row(engine, owner):
    return next((r for r in (getattr(engine, 'typed_passive_rows', {}) or {}).get(owner.entity_id, [])
                 if r.get('block') == 'yin_patient_moon'), None)


@hook('status_description')
def status(engine, holder, row, data):
    cid = (row or {}).get('condition_id')
    if cid == PAIR:
        return {'text': 'Twofold Waning: spending the first paired mark lets you move the other within 30 feet. '
                        'This opportunity ends at the end of your next turn.'}
    if cid == WATCH:
        target = engine.state.actors.get((data or {}).get('target'))
        return {'text': f'Patient Moon Method: keep the mark on {target.display_name if target else "the marked creature"} '
                        'unspent through the end of your next turn to choose a move or extension. Once per round; no action or CP.'}
    return None


@hook('compile_block')
def compile_patient(block, spec, row, numbers):
    if block == 'yin_patient_moon':
        return [{**row, 'block': block}]
    return None


def reachable(engine, owner, origin, reach, *, exclude=()):
    from ..senses import perceives
    from ..targeting import line_of_effect
    return sorted((s for s in engine.state.actors.values()
                   if s.active and s.entity_id not in exclude
                   and engine._distance_actor_to_actor(origin, s) <= reach
                   and (s is owner or perceives(engine, owner, s))
                   and line_of_effect(engine, owner, target=s)), key=lambda s: s.entity_id)


def consent(engine, owner, subject, name):
    if subject.team_id != owner.team_id or subject is owner:
        return True
    from .willing_targets import asks_consent
    return asks_consent(engine, getattr(engine, '_active_intent', None), subject, name,
                       f'{name}: {owner.display_name} offers you a preserving Waning Mark. Accept?',
                       prefer_accept=True, asker=owner)


def choose(engine, owner, key, subjects, prompt, *, target=None, count=1, optional=True, prompt_context=None):
    from .needle import ask, checkpoint_id
    return ask(engine, getattr(engine, '_active_intent', None), checkpoint_id(engine, key, target or owner.entity_id),
               owner, 'choice:needle.' + key, [s.entity_id for s in subjects],
               labels={s.entity_id: s.display_name for s in subjects}, minimum=count, maximum=count,
               allow_decline=optional, name='Twofold Waning' if 'twofold' in key else 'Patient Moon Method',
               feature_id=TWO if 'twofold' in key else PATIENT, target_id=target,
               preferred=[s.entity_id for s in subjects if s.team_id != owner.team_id][:count], prompt=prompt,
               prompt_context=prompt_context)


@hook('candidate_allowed')
def twofold_candidate(engine, actor, candidate, action):
    if action is None:
        return None
    rows = ((action.parameters or {}).get('typed') or {}).get('effects') or []
    if any(r.get('type') == 'yin_twofold' for r in rows):
        return len(reachable(engine, actor, actor, int(action.range_ft or 60))) >= 2
    return None


@effect('yin_twofold')
def twofold(ctx: Any, row: dict):
    from ..typed_executor import block_mark
    subjects = reachable(ctx.engine, ctx.actor, ctx.actor, int(ctx.action.range_ft or 60))
    picks = choose(ctx.engine, ctx.actor, 'yin_twofold_targets', subjects,
                   'Twofold Waning: choose two different creatures within 60 feet that you can perceive. '
                   'Each gains a Waning Mark until the end of your next turn (2 CP; Bonus Action).',
                   count=2, optional=False)
    if len(picks) != 2:
        raise ValueError('Twofold Waning requires two distinct creatures')
    accepted = [ctx.engine.state.actors[p] for p in picks
                if consent(ctx.engine, ctx.actor, ctx.engine.state.actors[p], 'Twofold Waning')]
    # Keep earlier activations' independent pairs; native expiry removes each.
    pairs = []
    for subject in accepted:
        block_mark(replace(ctx, target=subject, targets=[subject]),
                   {'mark': MARK, 'applies_to': 'target', 'duration': {'kind': 'until_end_of_your_next_turn'}})
        mark = held(subject, ctx.actor)
        if mark:
            pairs.append({'actor': subject.entity_id, 'instance': mark.instance_id})
    if len(pairs) == 2:
        ctx.engine._apply_condition(ctx.actor, PAIR, TWO, ctx.actor.entity_id,
                                    expires_on=f'END_OF_SOURCE_TURN_AT:{ctx.actor.turns_started + 1}',
                                    data={'pairs': pairs})


@hook('mark_spent')
def move_pair(ctx, name, subject):
    if name.lower() != MARK.lower():
        return
    from .condition_ownership import remove_instance
    for pair in list(ctx.actor.conditions.values()):
        if pair.condition_id != PAIR:
            continue
        entries = (pair.data or {}).get('pairs') or []
        spent = next((p for p in entries if p['actor'] == subject.entity_id), None)
        if spent is None:
            continue
        other = next((p for p in entries if p is not spent), None)
        bearer = ctx.engine.state.actors.get(other['actor']) if other else None
        mark = held(bearer, ctx.actor) if bearer else None
        remove_instance(ctx.engine, ctx.actor, pair.instance_id, TWO)
        if mark is None:
            continue
        pool = reachable(ctx.engine, ctx.actor, bearer, 30, exclude=(bearer.entity_id,))
        from .attack_scope import current
        from .choice_prompt import action_context
        # The live strike shadows its parent during nested reactions. Outside a
        # strike, use the accepted action rather than guessing from old events.
        strike = current(ctx.engine)
        source = (strike['source'] if strike else
                  getattr(ctx.engine, '_active_action_source_id', None) or ctx.action.source_definition_id)
        action = ctx.engine.action_catalog.get(source)
        actor_id = strike['actor_id'] if strike else (action.owner_id if action else ctx.actor.entity_id)
        actor = ctx.engine.state.actors.get(actor_id)
        affected = (ctx.engine.state.actors.get(strike['target_id']) if strike else
                    subject if actor is ctx.actor else ctx.actor)
        presentation = action_context(ctx.engine, actor, source, affected)
        if strike:
            presentation['action_name'] = strike['context'].action.display_name
        presentation['cost'] = 'No action or additional resource cost'
        picks = choose(ctx.engine, ctx.actor, 'yin_twofold_move', pool,
                       f'Twofold Waning: you spent the mark on {subject.display_name}. '
                       f'You may move the other mark from {bearer.display_name} to a creature within 30 feet of it. '
                       'Its deadline stays the end of your next turn; no action or extra CP.', target=bearer.entity_id,
                       prompt_context=presentation)
        if picks:
            recipient = ctx.engine.state.actors[picks[0]]
            if consent(ctx.engine, ctx.actor, recipient, 'Twofold Waning'):
                transfer(ctx.engine, ctx.actor, bearer, mark, recipient, TWO)


def held_id(owner):
    from ..typed_executor import mark_condition_id
    return mark_condition_id(MARK, owner.entity_id)


def transfer(engine, owner, bearer, mark, recipient, source):
    from .condition_ownership import remove_instance, refresh_owned
    data = dict(mark.data or {})
    remove_instance(engine, bearer, mark.instance_id, source)
    refresh_owned(engine, recipient, mark.condition_id, owner.entity_id, source)
    engine._apply_condition(recipient, mark.condition_id, source, owner.entity_id,
                            expires_on=mark.expires_on, data=data)
    moved = held(recipient, owner)
    # Moving an existing mark preserves its original Patient eligibility clock.
    # Updating exact references uses ordinary remove/apply receipts for replay.
    for watch in list(owner.conditions.values()):
        if (watch.condition_id == WATCH and (watch.data or {}).get('instance') == mark.instance_id
                and (watch.data or {}).get('target') == bearer.entity_id):
            watch_data = {**watch.data, 'target': recipient.entity_id, 'instance': moved.instance_id}
            remove_instance(engine, owner, watch.instance_id, PATIENT)
            engine._apply_condition(owner, WATCH, watch.source_definition_id, owner.entity_id,
                                    expires_on=watch.expires_on, data=watch_data)


@hook('mark_applied')
def remember_patient(ctx, name, subject):
    if name.lower() != MARK.lower() or patient_row(ctx.engine, ctx.actor) is None:
        return
    mark = held(subject, ctx.actor)
    if mark is None:
        return
    from .effect_durations import token
    ctx.engine._apply_condition(ctx.actor, WATCH, PATIENT, ctx.actor.entity_id,
                               expires_on=token('end', ctx.actor.entity_id, ctx.actor.turns_started + 1),
                               data={'target': subject.entity_id, 'instance': mark.instance_id})


@hook('effect_expiring_choice')
def patient_expiring(engine, owner, watch):
    if getattr(watch, 'condition_id', None) != WATCH:
        return
    data = watch.data or {}
    bearer = engine.state.actors.get(data.get('target'))
    mark = bearer.conditions.get(data.get('instance')) if bearer else None
    if (mark is None or not owner.active or mark.condition_id != held_id(owner) or patient_row(engine, owner) is None
            or owner.turn_flags.get(ONCE) == engine.state.round_number):
        return
    from .needle import ask, checkpoint_id, incapacitated
    if incapacitated(owner):
        return
    pool = reachable(engine, owner, bearer, 30, exclude=(bearer.entity_id,))
    longer = str(mark.expires_on).startswith('START_OF_SLOT_AT:') or mark.expires_on == 'UNTIL_REMOVED'
    labels = {'extend': (f'Keep the later existing deadline on {bearer.display_name} (already beyond your following turn)'
                         if longer else f'Keep the mark on {bearer.display_name} until the end of your following turn')}
    labels.update({s.entity_id: f'Move the mark to {s.display_name} (within 30 feet of {bearer.display_name})'
                   for s in pool})
    picks = ask(engine, getattr(engine, '_active_intent', None), checkpoint_id(engine, 'yin_patient', mark.instance_id),
                owner, 'choice:needle.yin_patient', list(labels), labels=labels, allow_decline=True,
                name='Patient Moon Method', feature_id=PATIENT, target_id=bearer.entity_id,
                preferred=['extend'],
                prompt=f'Patient Moon Method: you have kept your Waning Mark on {bearer.display_name} unspent through the end of your next turn. '
                       'Move it to another creature within 30 feet, or extend it until the end of your following turn? '
                       'Once per round; no action or CP. Declining keeps its existing deadline.')
    if not picks:
        return
    recipient = bearer if picks[0] == 'extend' else engine.state.actors[picks[0]]
    if recipient is not bearer and not consent(engine, owner, recipient, 'Patient Moon Method'):
        return
    owner.turn_flags[ONCE] = int(engine.state.round_number)
    if picks[0] == 'extend':
        # Extending never shortens an already minute-long mark.
        if longer:
            return
        from .condition_ownership import remove_instance
        remove_instance(engine, bearer, mark.instance_id, PATIENT)
        engine._apply_condition(bearer, mark.condition_id, PATIENT, owner.entity_id,
                                expires_on='END_OF_MARKER_NEXT_TURN',
                                data={'marker_turn': int(owner.turns_started)})
    else:
        from ..typed_executor import block_mark
        from .states import context
        from .condition_ownership import remove_instance
        remove_instance(engine, bearer, mark.instance_id, PATIENT)
        ctx = context(engine, owner, PATIENT, [recipient]).with_source(PATIENT)
        # Reapply the normal mark on its new subject; its next eligible deadline
        # belongs to the new application, not to the original watch.
        block_mark(ctx, {'mark': MARK, 'applies_to': 'target',
                         'duration': {'kind': 'until_end_of_your_next_turn'}})
