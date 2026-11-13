"""Beauty combat Insights and scene-entry marks, using sealed owned rows.

Ability Increase remains a level selection. Save triggers read final outcomes,
not preliminary rolls. Unbroken Grace intercepts an actual mark expenditure;
Blade-Hesitation tracks an actual Beauty penalty on the corresponding roll.
Perfect Entrance is offered on the fighter's first turn (battlefield arrival).
Later narrative entrances and peaceful interactions stay outside combat.
Shared record_penalty is used by beauty_motion for its directly imposed mode.
"""
from typing import Any
from . import effect, hook

BLOCK = 'beauty_insights'
BLADE = 'insight.blade-hesitation-adept'
POISE = 'insight.poise-tempered-presence'
GRACE = 'insight.unbroken-grace'
ENTRANCE = 'tianxia.talent.beauty.perfect_entrance'


def beauty(source):
    return 'BEAUTY_BASE_' in str(source) or 'tianxia.talent.beauty.' in str(source)


def owned(engine, actor, mid):
    from .passive_rows import row_of
    return row_of(engine, actor.entity_id, BLOCK, mid) if actor else None


@hook('compile_block')
def compile_insights(block, spec, row, numbers):
    if block != BLOCK:
        return None
    return [{**row, 'kind': row['feature_id'], 'numbers': {key: int(numbers[key]) for key in ('pb', 'key_mod', 'cl')}, 'choice_owner': 1}]


def context(engine, actor, target, mid, name, numbers, intent=None):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..typed_executor import Context
    action = ActionDefinition(source_definition_id=mid, display_name=name, owner_id=actor.entity_id,
                              economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF')
    typed = {'source': mid, 'numbers': {key: int(numbers[key]) for key in ('pb', 'key_mod', 'cl')}, 'duration': {'kind': 'instant'}, 'effects': [], 'riders': []}
    return Context(engine, actor, action, intent or getattr(engine, '_active_intent', None), typed,
                   [target] if target else [], target)


def optional(ctx, target, mid, name, text):
    from . import needle
    action = getattr(ctx, 'action', None)
    action_name = getattr(action, 'display_name', None) or 'the triggering action'
    source_id = getattr(action, 'source_definition_id', None)
    return bool(needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, name, target.entity_id),
        ctx.actor, 'choice:needle.' + mid, ['use'], labels={'use': text},
        prompt=f'{name}: after {action_name}, {text}', name=name, feature_id=mid,
        target_id=target.entity_id, allow_decline=True,
        prompt_context={'source_definition_id': source_id or mid, 'action_name': action_name,
                        'action_actor_id': ctx.actor.entity_id, 'affected_id': target.entity_id}))


@hook('mark_consume')
def preserve(ctx, effect, subject):
    if str(effect.get('mark')).lower() != 'beauty mark' or not beauty(ctx.typed.get('source')):
        return None
    row = owned(ctx.engine, ctx.actor, GRACE)
    # A spend in the success branch of an actual final Beauty save only.
    if not row or ctx.failed_save is not False:
        return None
    flag = 'beauty_grace_round_used'
    if ctx.actor.turn_flags.get(flag) == ctx.engine.state.round_number:
        return None
    from ..typed_executor import bears_mark, block_mark
    if not bears_mark(subject, ctx.actor.entity_id, 'Beauty Mark'):
        return None
    if not optional(ctx, subject, GRACE, 'Unbroken Grace',
                    f'Keep your existing Beauty Mark on {subject.display_name} until the end of your next turn. No action or CP cost; once per round.'):
        return None
    ctx.actor.turn_flags[flag] = int(ctx.engine.state.round_number)
    block_mark(ctx, {'mark': 'Beauty Mark', 'applies_to': 'target',
                     'duration': {'kind': 'until_end_of_your_next_turn'}})
    return True


@hook('save_final')
def poised(ctx, subject, ability, named, failed):
    row = owned(ctx.engine, subject, POISE)
    if failed or not row or not subject.active:
        return
    qualifying = {'charmed', 'frightened', 'category:humiliated', 'category:lose_face',
                  'category:forced_kneel', 'category:forced_bow', 'category:forced_grovel', 'category:forced_flee'}
    if not qualifying.intersection(named):
        return
    source = ctx.actor
    from ..senses import perceives
    if (source is subject or not source.active or ctx.engine._distance_actor_to_actor(subject, source) > 60
            or not perceives(ctx.engine, source, subject) or any(c.condition_id == 'condition:typed.beauty_poise_used' for c in subject.conditions.values())):
        return
    from . import ai_controlled
    from ..relations import relation, ENEMY
    if ai_controlled(ctx.engine, subject) and (relation(ctx.engine, subject, source) != ENEMY
                                              or not perceives(ctx.engine, subject, source)):
        return
    inner = context(ctx.engine, subject, source, POISE,
                   getattr(getattr(ctx, 'action', None), 'display_name', None) or 'saving throw',
                   row['numbers'], ctx.intent)
    if optional(inner, source, POISE, 'Poise-Tempered Presence',
                f'Place your Beauty Mark on {source.display_name} until the end of your next turn. No action or CP cost; once per scene.'):
        from ..typed_executor import block_mark
        # Durable scene token: ordinary turn flags are reset each turn.
        ctx.engine._apply_condition(subject, 'condition:typed.beauty_poise_used', POISE,
                                    subject.entity_id, expires_on='UNTIL_REMOVED', data={'hidden': True})
        block_mark(inner, {'mark': 'Beauty Mark', 'applies_to': 'target',
                           'duration': {'kind': 'until_end_of_your_next_turn'}})


@hook('attack_completed')
def hesitation(engine, notice, intent):
    attacker = engine.state.actors.get(notice.attacker_id)
    if attacker is None:
        return
    rolled = next((e for e in reversed(engine.events) if e.event_type == 'ATTACK_ROLLED'
                   and e.actor_id == attacker.entity_id and e.source_definition_id == notice.source_id
                   and notice.target_id in e.target_ids), None)
    if rolled is None:
        return
    previous = max((e.sequence for e in engine.events if e.event_type == 'ATTACK_ROLLED'
                    and e.actor_id == attacker.entity_id and e.sequence < rolled.sequence), default=0)
    for actor in list(engine.state.actors.values()):
        receipts = [c for c in actor.conditions.values() if c.condition_id == 'condition:typed.beauty_hesitation'
                    and c.data.get('attacker') == attacker.entity_id]
        offer_step = False
        for receipt in receipts:
            # A post-hit penalty belongs to the NEXT roll, not the creating hit.
            if receipt.data['created_sequence'] >= rolled.sequence:
                continue
            modifier = receipt.data.get('modifier_id')
            imposed = (receipt.data.get('attack_source') == notice.source_id if modifier is None else
                       any(e.event_type == 'MODIFIER_REMOVED' and previous < e.sequence < rolled.sequence
                           and e.payload.get('modifier_id') == modifier and e.payload.get('reason') == 'CONSUMED'
                           for e in engine.events))
            # An expired/dispelled modifier cannot qualify. A first roll against
            # someone else consumes the receipt too. Cancellation by Advantage
            # does not undo the printed fact that Beauty imposed Disadvantage.
            # Receipts are independent: preserve every other attacker's pending penalty.
            del actor.conditions[receipt.instance_id]
            engine._append_event('CONDITION_REMOVED', BLADE, actor_id=actor.entity_id,
                target_ids=(actor.entity_id,), payload={'condition_id': receipt.condition_id,
                    'instance_id': receipt.instance_id})
            row = owned(engine, actor, BLADE)
            from ..typed_executor import bears_mark
            if (not imposed or not row or not actor.active or notice.target_id != actor.entity_id
                    or notice.hit or not bears_mark(attacker, actor.entity_id, 'Beauty Mark')):
                continue
            offer_step = True
        # Several Beauty penalties can be consumed by one completed attack;
        # the printed rider grants one step per miss for this owner.
        if offer_step:
            from .rider_step import step
            inner = context(engine, actor, attacker, BLADE, 'Blade-Hesitation Adept', row['numbers'], intent)
            step(inner, {'distance_ft': 5, 'label': 'Blade-Hesitation Adept',
                         'trigger': 'a marked creature missed after your Beauty talent imposed Disadvantage',
                         'no_oa_from_target': True})


@hook('compile_actions')
def entrance_action(info):
    row = info['mechanics'].get(ENTRANCE) or {}
    if ENTRANCE not in info['owned_ids'] or not any(e.get('type') == 'beauty_entrance' for e in row.get('effects', [])):
        return None
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.beauty_entrance", display_name='Perfect Entrance',
        owner_id=info['actor_id'], economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF',
        costs=((RESOURCE_IDS[info['primary']], 1),),
        parameters={'typed': {'source': ENTRANCE, 'effects': row['effects'], 'numbers': info['numbers'],
                             'duration': {'kind': 'instant'}, 'riders': []},
                    'description': 'On entering the battlefield, spend 1 CP with no action to place Beauty Marks on up to your Proficiency Bonus creatures that can perceive you, until the end of your next turn.',
                    'expected_damage': 0})]


@hook('candidate_allowed')
def arrival_only(engine, actor, candidate, action):
    if ((getattr(action, 'parameters', None) or {}).get('typed') or {}).get('source') != ENTRANCE:
        return None
    return False if actor.turns_started > 1 or any(c.condition_id == 'condition:typed.beauty_entrance_used' for c in actor.conditions.values()) else None


@effect('beauty_entrance')
def entrance(ctx, effect):
    from . import needle
    from ..senses import perceives
    from ..relations import relation, ENEMY
    from ..typed_executor import block_mark
    options = sorted(a.entity_id for a in ctx.engine.state.actors.values() if a.active and a is not ctx.actor
                     and perceives(ctx.engine, a, ctx.actor))
    automatic = [aid for aid in options if relation(ctx.engine, ctx.actor, ctx.engine.state.actors[aid]) == ENEMY
                 and perceives(ctx.engine, ctx.actor, ctx.engine.state.actors[aid])]
    maximum = int(ctx.numbers['pb'])
    ids = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'BEAUTY_ENTRANCE', ctx.source),
        ctx.actor, 'choice:needle.beauty_entrance', options, automatic_options=automatic,
        labels={aid: ctx.engine.state.actors[aid].display_name for aid in options}, maximum=maximum, minimum=1,
        default_count=maximum, allow_decline=True, name='Perfect Entrance', feature_id=ENTRANCE,
        prompt=f'Perfect Entrance: choose up to {maximum} creatures that can perceive you. Spend 1 CP; no action. Their Beauty Marks last until the end of your next turn.')
    ctx.engine._apply_condition(ctx.actor, 'condition:typed.beauty_entrance_used', ctx.source,
                                ctx.actor.entity_id, expires_on='UNTIL_REMOVED', data={'hidden': True})
    from dataclasses import replace
    if ids:
        block_mark(replace(ctx, targets=[ctx.engine.state.actors[aid] for aid in ids], target=None),
                   {'mark': 'Beauty Mark', 'applies_to': 'target', 'duration': {'kind': 'until_end_of_your_next_turn'}})


@hook('effect_resolution_scope')
def hesitation_penalty(ctx, effect):
    if effect.get('type') != 'disadvantage' or not beauty(ctx.typed.get('source')) or not owned(ctx.engine, ctx.actor, BLADE):
        return None
    from contextlib import contextmanager
    from .effect_durations import token

    @contextmanager
    def scope():
        start = len(ctx.engine.events)
        yield
        for event in ctx.engine.events[start:]:
            if (event.event_type != 'MODIFIER_APPLIED' or event.source_definition_id != ctx.source
                    or event.payload.get('target_field') != 'attack_mode'
                    or event.payload.get('value') != 'DISADVANTAGE'):
                continue
            for aid in event.target_ids:
                subject = ctx.engine.state.actors.get(aid)
                if subject is None or subject is ctx.actor:
                    continue
                record_penalty(ctx.engine, ctx.actor, subject, ctx.source, event.payload['modifier_id'])
    return scope()


@hook('repeat_save_scope')
def poised_repeat(engine, resolution):
    subject = engine.state.actors.get(resolution['holder_id'])
    row = owned(engine, subject, POISE)
    if not row:
        return None
    from contextlib import contextmanager

    @contextmanager
    def scope():
        source = engine.state.actors.get(resolution['source_actor_id'])
        yield
        if resolution.get('success') and source:
            triggering = engine.action_catalog.get(resolution['source_definition_id'])
            inner = context(engine, source, subject, resolution['source_definition_id'],
                            triggering.display_name if triggering else 'Repeated saving throw', row['numbers'])
            poised(inner, subject, resolution['ability'], set(resolution['named']), False)
    return scope()


def record_penalty(engine, owner, subject, source, modifier_id=None, *, attack_source=None):
    """Shared durable receipt for an actually imposed Beauty attack penalty."""
    if not owned(engine, owner, BLADE):
        return
    from .effect_durations import token
    engine._apply_condition(owner, 'condition:typed.beauty_hesitation', BLADE, owner.entity_id,
        expires_on=token('end', subject.entity_id, subject.turns_started + 1),
        data={'attacker': subject.entity_id, 'penalty_source': source, 'modifier_id': modifier_id,
              'attack_source': attack_source, 'created_sequence': engine.events[-1].sequence if engine.events else 0,
              'hidden': True})
