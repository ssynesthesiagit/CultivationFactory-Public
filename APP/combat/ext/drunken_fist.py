"""Drunken Fist's native posture, hit, roll and timed-state consumers.

All declarations come from owned compiled source rows. Posture is committed by
native condition/stand transitions, steps use native separate-budget movement,
and frequency receipts live in replayable conditions rather than engine scratch.
No owned row/state means no changed rolls, movement, prompts or events.

Shared helper module. Consumers: combat/ext/d20_rewrite_rules.py (Empty Cup reroll
rule: empty_cup_movement, available, CUP).
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from . import effect, hook

PREFIX = 'tianxia.subpath.body.drunken_fist.feature.'
SWAY, FIST, BLOW, CUP, HEAVEN = [PREFIX + s for s in
    ('swaying_step', 'falling_fist', 'staggering_blow', 'empty_cup', 'heavenly_drunk')]
STATE = 'heavenly_drunk'
NEXT = 'condition:typed.drunken_next_'
SLOW = 'condition:typed.drunken_slow'
AC = 'condition:typed.drunken_ac'
CLOCK = 'condition:typed.drunken_heaven_clock'
CROSS = ContextVar('drunken_cup_crossing', default=None)
GRANTED = ContextVar('drunken_granted_attack', default=None)
AC_QUERY = ContextVar('drunken_cup_ac_query', default=False)


BODY = 'tianxia.path.body_refining'
LEVELS = {SWAY:3, FIST:6, BLOW:10, CUP:14, HEAVEN:18}


def body_cl(engine, actor):
    from .ability_source import numbers_of
    from .path_authority import effective_cl
    return effective_cl(engine, actor, BODY, int(numbers_of(engine, actor).get('cl') or 1))


def available(engine, actor, source):
    return body_cl(engine, actor) >= LEVELS[source]


def heavenly(engine, actor):
    from .states import active
    state = active(engine, actor, STATE)
    return state if actor.active and state is not None and available(engine, actor, HEAVEN) else None


@hook('candidate_allowed')
def family_level(engine, actor, candidate, action):
    from .ability_source import mechanic_of
    source = mechanic_of(action) if action is not None else ''
    if source == 'tianxia.path.body_refining.feature.stomping_step':
        from .rider_helpers import effect_rows
        if any(r.get('source_modifier') == SWAY for r in effect_rows(action.parameters['typed'].get('effects'))):
            source = SWAY
    if source == FIST+'#intentional_fall':
        source = FIST
    return False if source in LEVELS and not available(engine, actor, source) else None


@hook('row_allowed')
def family_row_level(engine, actor, row):
    source = row.get('feature_id')
    return False if source in LEVELS and not available(engine, actor, source) else None



@hook('choice_reactors')
def heavenly_movement_choosers(engine):
    """The existing service filters manual seats; AI seats keep their controller."""
    return tuple(a.entity_id for a in engine.state.actors.values() if heavenly(engine,a))


@hook('walking_cost')
def normal_crawl(engine: Any, actor: Any, normal_extra: int) -> int | None:
    return 0 if heavenly(engine, actor) else None


@hook('stand_cost')
def free_stand(engine: Any, actor: Any, normal_cost: int) -> int | None:
    return 0 if heavenly(engine, actor) else None


@hook('compile_skill_bonuses')
def acrobatics(info):
    if SWAY not in info['owned_ids']:
        return None
    from ..ability_checks import proficiency_rank
    row = next((copy.deepcopy(r) for r in info['skills']
                if str(r.get('skill', '')).casefold() == 'acrobatics'), None)
    row = row or {'skill': 'Acrobatics', 'bonus': int(info['mods'].get('DEX', 0)), 'proficiency_multiplier': 0}
    rank = proficiency_rank(row)
    if rank is None:
        return {'skills': [], 'notes': ['Swaying Step needs the recorded Acrobatics proficiency rank; enter it on the character sheet.']}
    if rank:
        row['bonus'] = int(row['bonus']) + 2
        row['source_bonuses'] = {**row.get('source_bonuses', {}), SWAY:2}
    else:
        row['bonus'] = int(row['bonus']) + int(info['pb'])
        row['proficiency_multiplier'] = 1
        row['source_bonuses'] = {**row.get('source_bonuses', {}), SWAY:int(info['pb'])}
    return {'skills': [row]}


@effect('drunken_posture')
def posture(ctx, row):
    from .. import posture as native
    from ..typed_executor import run_effects
    if row['posture'] == 'stand':
        native.stand_up(ctx.engine, ctx.actor, source_id=ctx.source, cost=0, ignore_speed=True)
    elif not native.prone_conditions(ctx.actor):
        before = len(ctx.engine.events)
        run_effects(ctx, [{'type': 'condition', 'applies_to': 'self', 'condition': 'prone',
                           'intentional_posture': True}])
        fell = any(e.event_type == 'CONDITION_APPLIED' and ctx.actor.entity_id in e.target_ids
                   and e.payload.get('condition_id') == 'condition:typed.prone'
                   for e in ctx.engine.events[before:])
        if fell and row.get('move_ft'):
            # Falling does not grant the separate Move option's OA exemption.
            # Native movement still honors an independently chosen Disengage.
            run_effects(ctx, [{'type':'general_rider_step', 'distance_ft':int(row['move_ft']),
                              'label':'Swaying Step'}])


@hook('ac')
def falling_ac(engine, actor):
    if heavenly(engine, actor) and any(c.condition_id == AC for c in actor.conditions.values()):
        return 2
    return None


@effect('drunken_next_roll')
def next_roll(ctx, row):
    cid = NEXT + row['roll']
    ctx.engine._remove_condition(ctx.actor, cid, SWAY)
    ctx.engine._apply_condition(ctx.actor, cid, SWAY, ctx.actor.entity_id,
        expires_on='START_OF_SELF_NEXT_TURN', data={'source_cl':body_cl(ctx.engine, ctx.actor),
        **({'rule':{'check_mode':{'Acrobatics':'ADVANTAGE'}}} if row['roll']=='acrobatics' else {}),
        'label': 'Swaying Step: Advantage on next ' +
            ('Dexterity saving throw' if row['roll'] == 'save' else 'Acrobatics check') + ' before your next turn'})


@hook('save_mode')
def next_dex(engine, actor, ability, dc, source, context):
    if str(ability).upper()[:3] == 'DEX' and (heavenly(engine, actor) or (available(engine, actor, SWAY) and any(c.condition_id == NEXT+'save' for c in actor.conditions.values()))):
        return 'ADVANTAGE'
    return None


@hook('event', nested=True)
def consume_check(engine, event_type, kwargs):
    if event_type == 'SAVE_ROLLED':
        actor = engine.state.actors.get(kwargs.get('actor_id'))
        if actor is not None and available(engine, actor, SWAY) and any(c.condition_id == NEXT+'save' for c in actor.conditions.values()):
            from ..gate2_runtime_models import RollRecord
            payload = kwargs.get('payload') or {}
            if 'roll_id' in payload and type(payload.get('natural_result')) is int:
                consume_next_roll(engine, RollRecord.model_validate({key:value for key,value in payload.items()
                    if key in RollRecord.model_fields}))
    from .roll_context import check_skill_receipts
    for aid, roll, skill in check_skill_receipts(kwargs) if event_type == 'CHECK_ROLLED' else ():
        actor = engine.state.actors.get(aid)
        if actor is not None and available(engine, actor, SWAY) and str(skill).casefold() == 'acrobatics' and any(c.condition_id == NEXT+'acrobatics' for c in actor.conditions.values()):
            engine._remove_condition(actor, NEXT+'acrobatics', SWAY)


@hook('d20_result', priority=-1000)
def consume_next_roll(engine, roll, intent=None):
    """Consume on the actual initial draw, before a rewrite can nest a roll.

    Saved save/check receipts remain a fallback for suppressed rewrite scopes.
    Native metadata must identify the qualifying roll; no preview consumes it.
    """
    actor = engine.state.actors.get(roll.actor_id)
    if actor is None or not any(c.condition_id in (NEXT+'save',NEXT+'acrobatics') for c in actor.conditions.values()):
        return
    context = engine.d20_context(roll) or {}
    suffix = ('save' if context.get('kind') == 'save' and context.get('ability') == 'DEX' else
              'acrobatics' if context.get('kind') == 'check' and str(context.get('skill') or '').casefold() == 'acrobatics' else None)
    if suffix and available(engine, actor, SWAY) and any(c.condition_id == NEXT+suffix for c in actor.conditions.values()):
        engine._remove_condition(actor, NEXT+suffix, SWAY)


@effect('drunken_speed')
def slow(ctx, row):
    from .owned_effects import remove_conditions
    remove_conditions(ctx.engine, ctx.target, BLOW, ctx.actor.entity_id, SLOW)
    ctx.engine._apply_condition(ctx.target, SLOW, BLOW, ctx.actor.entity_id,
        expires_on='START_OF_SOURCE_NEXT_TURN', data={'source_cl':body_cl(ctx.engine, ctx.actor), 'feet': int(row['feet']),
        'fly_speed_reduction_ft': int(row['feet']), 'fly_speed_reduction_key': 'staggering_blow',
        'climb_speed_reduction_ft': int(row['feet']), 'climb_speed_reduction_key': 'staggering_blow',
        'label': 'Staggering Blow: each Speed reduced by 10 feet until the attacker’s next turn'})


@hook('speed')
def slow_walk(engine, actor):
    amounts = [int(c.data['feet']) for c in actor.conditions.values() if c.condition_id == SLOW]
    return -max(amounts) if amounts else None


@hook('reaction_spend')
def free_fist(engine, actor, row, commit):
    if row.get('feature_id') == FIST and heavenly(engine, actor):
        return 'free'
    return None


@hook('row_allowed')
def fist_no_recursion(engine, actor, row):
    if row.get('feature_id') != FIST:
        return None
    from .attack_scope import current
    frame = current(engine)
    if GRANTED.get() == id(engine) or (frame and frame['context'].typed.get('granted_attack')):
        return False
    return None


@hook('effect_resolution_scope')
def granted_fist(ctx, row):
    if row.get('type') != 'attack' or (ctx.source != FIST and not ctx.typed.get('granted_attack')):
        return None
    @contextmanager
    def scope():
        old = ctx.typed
        ctx.typed = {**old, 'granted_attack': True}
        token = GRANTED.set(id(ctx.engine))
        try:
            yield
        finally:
            ctx.typed = old
            GRANTED.reset(token)
    return scope()


@hook('pass_through')
def drunken_passage(engine, mover, occupant):
    from ..relations import relation, ENEMY
    if relation(engine, mover, occupant) != ENEMY:
        return None
    cup = CROSS.get()
    if heavenly(engine, mover) or (cup is not None and cup['engine'] is engine and cup['actor'] == mover.entity_id
                                  and cup.get('permitted') == occupant.entity_id and cup['crossed'] in (None, occupant.entity_id)):
        return 'difficult'
    return None


@hook('pass_through_entered')
def cup_entered(engine, mover, occupant, intent):
    from ..relations import relation, ENEMY
    cup = CROSS.get()
    if cup is not None and cup['engine'] is engine and cup['actor'] == mover.entity_id and relation(engine, mover, occupant) == ENEMY and cup.get('permitted') == occupant.entity_id:
        cup['crossed'] = occupant.entity_id


@hook('attack_completed')
def heavenly_miss(engine, notice, intent):
    from ..relations import relation, ENEMY
    from .effect_durations import SLOT_AT
    attacker = engine.state.actors.get(notice.attacker_id)
    defender = engine.state.actors.get(notice.target_id)
    if notice.hit or attacker is None or defender is None or relation(engine, attacker, defender) != ENEMY or not heavenly(engine, defender):
        return
    cid = 'condition:typed.drunken_miss_round'
    if any(c.condition_id == cid and c.data.get('round') == engine.state.round_number for c in defender.conditions.values()):
        return
    from ..typed_executor import run_effects
    # Reserve once for the actual settled miss, before entry hazards can nest.
    engine._remove_condition(defender, cid, HEAVEN)
    engine._apply_condition(defender, cid, HEAVEN, defender.entity_id,
        expires_on=f'{SLOT_AT}:{engine.state.round_number+1}:0',
        data={'round': int(engine.state.round_number), 'label': 'Heavenly Drunk: miss movement used this round'})
    sub = feature_context(engine, defender, HEAVEN, attacker, intent)
    run_effects(sub, [{'type': 'general_rider_step', 'distance_ft': 10, 'no_oa': True, 'label': 'Heavenly Drunk'}])


def empty_cup_movement(engine, holder, rc, result):
    """Choose posture and native movement segments inside the rerolled attack.

    The ten-foot budget is shared by every segment. Native terrain, crawling,
    occupancy, hazards and passage entry receipts price each segment. A player
    can change posture before, during or after it; no ordinary feet are banked.
    """
    from .needle import ask, checkpoint_id
    from .. import posture as native, granted_movement
    from ..target_knowledge import actors_for, knowledge
    from ..relations import relation, ENEMY
    actor = holder.actor
    from .attack_scope import current
    frame = current(engine)
    if frame and (frame['actor_id'] != rc.roller.entity_id or frame['source'] != rc.source_id):
        frame = None
    if frame is not None:
        cover, current_ac = engine._attack_defense(rc.roller, actor, rc.spec or {}, rc.source_id)
        frame['drunken_fist_cup'] = {'target':actor.entity_id, 'origin':rc.roller.model_copy(deep=True),
                                    'bare_ac':int(rc.ac if rc.ac is not None else current_ac)-cover,
                                    'spec':rc.spec or {}, 'source':rc.source_id}
    sub = feature_context(engine, actor, holder.feature_id, rc.roller, getattr(engine, '_active_intent', None))
    token = CROSS.set({'engine': engine, 'actor': actor.entity_id, 'crossed': None, 'permitted': None})
    remaining = 10
    try:
        segment = 0
        while True:
            segment += 1
            prone = bool(native.prone_conditions(actor))
            stand_cost = native.standing_cost(engine, actor, check_budget=False) if prone else None
            options = ['stay']
            if prone:
                if stand_cost is not None and stand_cost <= remaining:
                    options.append('stand')
            else:
                options.append('fall_prone')
            picked = ask(engine, sub.intent, checkpoint_id(engine, 'empty_cup_posture', actor.entity_id, segment), actor,
                'choice:needle.empty_cup_posture', options, preferred=['stay'], allow_decline=True,
                labels={'stay': 'Keep your posture', 'stand': f'Stand from Prone ({stand_cost} feet of this granted movement)', 'fall_prone': 'Intentionally fall Prone'},
                prompt=f'Empty Cup: during {rc.roller.display_name}’s rerolled attack, {actor.display_name} may change posture; {remaining} feet of granted movement remain.',
                target_id=actor.entity_id, name='Empty Cup: posture', feature_id=CUP,
                prompt_context={'cost':'Included in Empty Cup; no additional action, Reaction or Stamina.'})
            if picked == ['fall_prone']:
                posture(sub, {'posture': 'fall'})
                continue
            elif picked == ['stand']:
                before_stand = len(engine.events)
                if native.stand_up(engine, actor, source_id=holder.feature_id, granted_ft=remaining):
                    stood = next(e for e in engine.events[before_stand:] if e.event_type == 'STOOD_UP'
                                 and e.actor_id == actor.entity_id and e.source_definition_id == holder.feature_id)
                    remaining -= int(stood.payload['granted_cost_ft'])
                continue
            if remaining <= 0 or sub.intent is None:
                break
            # Search with each allowed hostile separately. Filtering a single
            # shortest path could hide a destination whose alternate route is
            # legal. Independent passage providers keep their own permissions.
            cup = CROSS.get()
            permits = [None] if heavenly(engine, actor) else ([cup['crossed']] if cup['crossed'] else [None, *sorted(
                other.entity_id for other in actors_for(engine, actor) if relation(engine, actor, other) == ENEMY
                and (known := knowledge(engine, actor, engine.state.actors[other.entity_id])) is not None
                and known.mode == 'DIRECT')])
            paths, passage_for = {}, {}
            for permitted in permits:
                cup['permitted'] = permitted
                candidates = granted_movement.candidates(engine, actor, remaining, sub.intent, holder.feature_id)
                for key, candidate in candidates.items():
                    key = key.replace('step:', 'cell:', 1)
                    if key not in paths or candidate.movement_cost_ft < paths[key].movement_cost_ft:
                        paths[key] = candidate
                        passage_for[key] = permitted
            if not paths:
                break
            far = sorted(paths, key=lambda key: (-engine.grid.distance_ft(paths[key].destination, rc.roller.position), key))
            picked = ask(engine, sub.intent, checkpoint_id(engine, 'empty_cup_move', actor.entity_id, segment), actor,
                'choice:needle.empty_cup_move', [*far, 'stay'], preferred=far[:1], allow_decline=True,
                labels={**{key: f'Move to {c.destination.x},{c.destination.y} ({c.movement_cost_ft} feet)' for key,c in paths.items()},
                        'stay': 'Finish this movement here'},
                prompt=f'Empty Cup: {actor.display_name} may move up to {remaining} feet without Opportunity Attacks before {rc.roller.display_name}’s attack resolves.',
                target_id=actor.entity_id, name='Empty Cup: movement', feature_id=CUP,
                prompt_context={'cost':'Included in Empty Cup; no additional action, Reaction or Stamina.'})
            if not picked or picked[0] not in paths:
                break
            c = paths[picked[0]]
            cup['permitted'] = passage_for[picked[0]]
            spent = granted_movement.resolve_path(engine, actor, c.canonical_path, holder.feature_id,
                feet=remaining, intent=sub.intent, provokes=False, mode=c.metadata.get('movement_mode', 'walk'))
            remaining -= spent
            if not spent:
                break
    finally:
        CROSS.reset(token)


@hook('condition_state')
def intentional_posture_state(ctx, subject, row):
    if row.get('intentional_posture') and subject is ctx.actor:
        return {'data': {'intentional_posture': 1}}
    return None


@hook('condition_applied', priority=-100)
def intentional_fall_ac(ctx, name, subject):
    if name != 'prone' or subject is not ctx.actor or not heavenly(ctx.engine, subject):
        return
    if not any(c.condition_id == 'condition:typed.prone' and c.source_definition_id == ctx.source
               and c.data.get('intentional_posture') for c in subject.conditions.values()):
        return
    ctx.engine._remove_condition(subject, AC, HEAVEN)
    ctx.engine._apply_condition(subject, AC, HEAVEN, subject.entity_id,
        expires_on='START_OF_SELF_NEXT_TURN', data={'source_cl':body_cl(ctx.engine, ctx.actor), 'label': 'Heavenly Drunk: +2 AC after intentionally falling Prone'})


def feature_context(engine, actor, source, target, intent):
    """Exact family source outside its own action; use the public trigger context."""
    from ..typed_reactions import triggered_context
    from .ability_source import numbers_of
    return triggered_context(engine, actor, target, {'feature_id': source,
        'name': {CUP: 'Empty Cup', HEAVEN: 'Heavenly Drunk'}[source],
        'effects': [], 'numbers': numbers_of(engine, actor)}, intent)


@hook('compile_actions')
def intentional_fall_action(info):
    """Family posture input, derived from acquired source rows, with no new cost."""
    cl = int(info['numbers'].get('cl') or 1)
    if not ((FIST in info['owned_ids'] and cl >= 6)
            or (HEAVEN in info['owned_ids'] and cl >= 18)):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.drunken_intentional_fall",
        display_name='Fall Prone intentionally', owner_id=info['actor_id'], economy=EconomyKind.NONE,
        resolution_kind='TYPED', target_kind='SELF', parameters={'typed': {
            'source': FIST+'#intentional_fall', 'effects': [{'type':'drunken_posture','posture':'fall'}],
            'duration':{'kind':'instant'}, 'numbers':dict(info['numbers']), 'riders':[]}})]


@hook('candidate_allowed')
def fall_only_while_upright(engine, actor, candidate, action):
    if ((getattr(action, 'parameters', None) or {}).get('typed') or {}).get('source') == FIST+'#intentional_fall':
        from ..posture import prone_conditions
        return False if prone_conditions(actor) else None
    from .ability_source import mechanic_of
    from .passive_rows import row_of
    if (action is not None and mechanic_of(action) == 'tianxia.path.body_refining.feature.stomping_step'
            and row_of(engine, actor.entity_id, 'drunken_fist_source', SWAY) and available(engine, actor, SWAY)):
        from .rider_helpers import effect_rows
        if not any(row.get('source_modifier') == SWAY for row in effect_rows(action.parameters['typed'].get('effects'))):
            return False  # Exactly one printed Swaying Step option belongs to this activation.
    return None


@hook('ai_score_components')
def deliberate_fall_value(context, candidate, option_ids):
    """Keep free falling/standing from becoming an automatic preparation loop.

    This is a preference, never an admission filter. Only the acting creature's
    own Reaction and own visible conditions are read; human/API choices remain
    legal, and the AI can still take the fall when it can gain a printed benefit.
    """
    if candidate.source_definition_id != FIST+'#intentional_fall' and not candidate.source_definition_id.endswith('.drunken_intentional_fall'):
        return None
    actor = next(a for a in context.actors if a.entity_id == context.active_actor_id)
    new_heavenly_ac = 'condition:typed.state.'+STATE in actor.conditions and AC not in actor.conditions
    if new_heavenly_ac or (actor.reaction_available and AC not in actor.conditions):
        return None
    from ..gate4_models import ComponentScore
    return (ComponentScore(component='drunken_posture', value=-5000,
        explanation='Keep your footing after gaining the fall’s defense or spending your Reaction.'),)


@hook('compile_passives')
def native_sway_source(rows, info):
    if SWAY not in info['owned_ids'] or int(info['numbers'].get('cl') or 1) < 3:
        return None
    return [*rows, {'block':'drunken_fist_source', 'feature_id':SWAY, 'kind':SWAY,
                   'source_cl':int(info['numbers']['cl']),
                   'skill_check_choices':['Acrobatics'],
                   'acrobatics_bonus':next((int(r.get('source_bonuses',{}).get(SWAY,0)) for r in
                       info.get('owner_sheet',{}).get('ability_scores_and_statistics',{}).get('skills',[])
                       if str(r.get('skill','')).casefold()=='acrobatics'),0)}]


def journey_heaven_action(session, aid):
    """Read the acquired ability from this journey's sealed combat bundle."""
    return next((a for a in session.state['actors'][aid]['bundle']['action_catalog']
                 if (a.get('parameters', {}).get('typed') or {}).get('source') == HEAVEN), None)


def journey_body_cl(session, aid):
    from .path_authority import journey_cl
    return journey_cl(session, aid, BODY, int(session.state['actors'][aid]['bundle']['cl']))


def heaven_use_pools(actor, action):
    return [(resource,int(amount)) for resource,amount in action.get('costs', ())
            if resource.startswith('resource:uses.')]


@hook('journey_options')
def heavenly_journey_options(session, aid):
    actor = session.state['actors'][aid]
    action = journey_heaven_action(session, aid)
    if (session.state['phase'] != 'travel' or actor['incapacitated'] or action is None
            or actor['travel_uses'].get(HEAVEN) == session.state.get('scene_id', session.state['journey_id'])
            or any(actor['resources'].get(resource,0) < amount for resource,amount in heaven_use_pools(actor,action))
            or actor['resources'].get('resource:core.stamina', 0) < 6
            or journey_body_cl(session, aid) < 18):
        return None
    return [{'id': HEAVEN, 'kind': 'activate', 'payload': {'source': HEAVEN}, 'auto_select': 0,
        'label': f"{actor['name']}: Heavenly Drunk — Bonus Action, 6 Stamina, once this scene; lasts 1 minute. Advantage on Dexterity saves, evasive movement and Falling Fist without a Reaction."}]


@hook('journey_command')
def heavenly_journey_activate(session, aid, kind, payload):
    if kind != 'activate' or payload.get('source') != HEAVEN:
        return None
    from ..journey import require
    require(set(payload) == {'source'} and heavenly_journey_options(session, aid),
            'Heavenly Drunk requires its acquired CL18 feature, 6 Stamina and an unused scene use.')
    actor = session.state['actors'][aid]
    session.spend_resource(aid, 'resource:core.stamina', 6, HEAVEN)
    actor['travel_uses'][HEAVEN] = session.state.get('scene_id', session.state['journey_id'])
    for resource, amount in journey_heaven_action(session, aid).get('costs', ()):
        if resource.startswith('resource:uses.'):
            actor['resources'][resource] = 0
    deadline = session.clock() + 60
    actor['travel_effects'][HEAVEN] = {'expiry_num': deadline.numerator, 'expiry_den': deadline.denominator,
        'source_cl': journey_body_cl(session, aid), 'paid_stamina': 6}
    sync_journey_heaven(session, aid)
    session.emit('DRUNKEN_FIST_ACTIVATED', aid, source=HEAVEN, economy='BONUS_ACTION', stamina_cost=6,
        text=f"{actor['name']} spends 6 Stamina and a Bonus Action: Heavenly Drunk lasts 1 minute; its scene use is spent.")
    return True


def sync_journey_heaven(session, aid):
    """Family-owned source clock copied into its sealed encounter input."""
    from fractions import Fraction
    from ..canonical import canonical_sha256
    actor = session.state['actors'][aid]
    held = actor['travel_effects'].get(HEAVEN)
    remaining = max(Fraction(0), Fraction(held['expiry_num'], held['expiry_den']) - session.clock()) if held else Fraction(0)
    if not remaining and held:
        del actor['travel_effects'][HEAVEN]
        session.emit('DRUNKEN_FIST_ENDED', aid, source=HEAVEN, text=f"{actor['name']}’s Heavenly Drunk ends after 1 minute.")
    action = journey_heaven_action(session, aid)
    prior = actor.get('source_states', {}).get(HEAVEN, {})
    snapshot = {'remaining_num': remaining.numerator, 'remaining_den': remaining.denominator,
        'scene_used': int(actor['travel_uses'].get(HEAVEN) == session.state.get('scene_id', session.state['journey_id'])
            or (action is not None and any(actor['resources'].get(resource,0) < amount
                for resource,amount in heaven_use_pools(actor,action)))),
        'source_cl': int((held or prior).get('source_cl', actor['bundle']['cl'])),
        'ac_pending': int(bool(remaining and held and held.get('ac_pending')))}
    actor.setdefault('source_states', {})[HEAVEN] = copy.deepcopy(snapshot)
    actor['bundle']['drunken_fist_journey'] = snapshot
    actor['bundle'].pop('bundle_sha256', None)
    actor['bundle']['bundle_sha256'] = canonical_sha256(actor['bundle'])


@hook('journey_elapsed')
def heavenly_elapsed(session, aid, before, seconds, moving):
    if HEAVEN in session.state['actors'][aid]['travel_effects']:
        sync_journey_heaven(session, aid)


@hook('match_initialize')
def heavenly_from_journey(engine):
    from fractions import Fraction
    from ..typed_executor import run_effects
    applied = False
    for bundle in engine.typed_bundle_documents:
        snapshot = bundle.get('drunken_fist_journey')
        if not snapshot or not snapshot['remaining_num']:
            continue
        actor = engine.state.actors.get(bundle['actor_id'])
        action = next((a for a in engine.action_catalog.values() if a.owner_id == bundle['actor_id']
                       and (a.parameters.get('typed') or {}).get('source') == HEAVEN), None)
        if actor is None or action is None:
            continue
        remaining = Fraction(snapshot['remaining_num'], snapshot['remaining_den'])
        rounds = (remaining.numerator + 6 * remaining.denominator - 1) // (6 * remaining.denominator)
        sub = feature_context(engine, actor, HEAVEN, actor, None)
        sub.typed = copy.deepcopy(action.parameters['typed'])
        sub.typed['numbers'] = {**sub.typed['numbers'],'cl':int(snapshot['source_cl'])}
        sub.typed['retained_source_cl'] = int(snapshot['source_cl'])
        effects = copy.deepcopy(sub.typed['effects'])
        for row in effects:
            row['duration'] = {'kind': 'rounds', 'amount': rounds}
        run_effects(sub, effects)
        remember_heaven_clock(engine, actor, remaining, int(snapshot['source_cl']))
        if snapshot.get('ac_pending'):
            engine._apply_condition(actor, AC, HEAVEN, actor.entity_id, expires_on='START_OF_SELF_NEXT_TURN',
                data={'source_cl':int(snapshot['source_cl']), 'label':'Heavenly Drunk: +2 AC until your next turn starts'})
        applied = True
    return True if applied else None


def remember_heaven_clock(engine, actor, remaining, source_cl):
    """Source-owned exact remaining seconds beside the native round deadline."""
    from .states import active
    state = active(engine, actor, STATE)
    if state is None:
        return
    engine._remove_condition(actor, CLOCK, HEAVEN)
    engine._apply_condition(actor, CLOCK, HEAVEN, actor.entity_id, expires_on=state.expires_on,
        data={'remaining_num':remaining.numerator,'remaining_den':remaining.denominator,
              'start_round':int(engine.state.round_number),'start_slot':int(engine.state.current_slot_index),
              'source_cl':source_cl, 'label':'Heavenly Drunk: one-minute duration clock'})


@hook('technique_used')
def heavenly_activation_clock(ctx):
    from .ability_source import mechanic_of
    if mechanic_of(ctx.action) == HEAVEN:
        from fractions import Fraction
        remember_heaven_clock(ctx.engine, ctx.actor, Fraction(60), body_cl(ctx.engine, ctx.actor))


def heaven_seconds(engine, actor):
    from fractions import Fraction
    from .states import active
    from .effect_durations import parse_round
    state = active(engine, actor, STATE)
    if state is None:
        return Fraction(0)
    clock = next((c for c in actor.conditions.values() if c.condition_id == CLOCK), None)
    if clock is not None:
        data = clock.data
        cycles = int(engine.state.round_number) - int(data['start_round'])
        cycles -= int(engine.state.current_slot_index < int(data['start_slot']))
        return max(Fraction(0), Fraction(data['remaining_num'],data['remaining_den']) - 6*max(0,cycles))
    deadline = parse_round(state.expires_on)
    if deadline is None:
        raise ValueError('Heavenly Drunk has no supported native duration clock.')
    # Historical one-minute states still have their actual native slot deadline.
    return Fraction(max(0, deadline[0]-engine.state.round_number-
                        int(engine.state.current_slot_index > deadline[1]))*6)


def heaven_source(engine, source):
    from .ability_source import mechanic_at
    return source == HEAVEN or mechanic_at(engine, source) == HEAVEN


@hook('journey_snapshot_actor')
def heavenly_snapshot(actor, session, aid, engine):
    if journey_heaven_action(session, aid) is None:
        return None
    # Strip only this source's managed effects from the health snapshot. The
    # settled callback exports their real clocks; unrelated effects still reject.
    result = actor.model_copy(deep=True)
    result.conditions = {key:c for key,c in result.conditions.items()
                         if not (c.source_actor_id == aid and heaven_source(engine,c.source_definition_id))}
    result.modifiers = {key:m for key,m in result.modifiers.items()
                        if not (m.source_actor_id == aid and heaven_source(engine,m.source_definition_id))}
    return result if len(result.conditions)!=len(actor.conditions) or len(result.modifiers)!=len(actor.modifiers) else None


@hook('journey_encounter_settled')
def heavenly_settled(session, aid, engine, creature):
    action = journey_heaven_action(session, aid)
    if action is None:
        return
    from .states import active
    state = active(engine, creature, STATE)
    actor = session.state['actors'][aid]
    if (state is None and HEAVEN not in actor.get('source_states',{})
            and all(actor['resources'].get(resource,0)>=amount for resource,amount in heaven_use_pools(actor,action))):
        return
    remaining = heaven_seconds(engine, creature)
    source_cl = int((state.data.get('numbers') or {}).get('cl') or session.state['actors'][aid]['bundle']['cl']) if state else int(session.state['actors'][aid]['bundle']['cl'])
    if remaining:
        deadline = session.clock()+remaining
        actor['travel_effects'][HEAVEN] = {'expiry_num':deadline.numerator,'expiry_den':deadline.denominator,
            'source_cl':source_cl,'paid_stamina':6,'ac_pending':int(any(c.condition_id==AC for c in creature.conditions.values()))}
    else:
        actor['travel_effects'].pop(HEAVEN,None)
    sync_journey_heaven(session,aid)
    session.emit('DRUNKEN_FIST_CONTINUED',aid,source=HEAVEN,remaining_num=remaining.numerator,
        remaining_den=remaining.denominator,text=f'{actor["name"]} retains Heavenly Drunk’s remaining time and spent scene use; no Stamina is restored.')


@hook('journey_initialize')
def heavenly_initialize(session, aid):
    from fractions import Fraction
    actor = session.state['actors'][aid]
    held = actor.get('source_states',{}).get(HEAVEN)
    if held is None or journey_heaven_action(session,aid) is None:
        return
    remaining = Fraction(held['remaining_num'],held['remaining_den'])
    if remaining:
        deadline = session.clock()+remaining
        actor['travel_effects'][HEAVEN] = {'expiry_num':deadline.numerator,'expiry_den':deadline.denominator,
            'source_cl':int(held['source_cl']),'paid_stamina':6,'ac_pending':int(held.get('ac_pending',0))}
    sync_journey_heaven(session,aid)


@hook('journey_scene_end')
def heavenly_scene_end(session, previous, current):
    for aid,actor in session.state['actors'].items():
        action = journey_heaven_action(session,aid)
        if action is None:
            continue
        actor['travel_uses'].pop(HEAVEN,None)
        for resource,_ in heaven_use_pools(actor,action):
            pool = next(p for p in actor['bundle']['actor_template']['resources'] if p['resource_id']==resource)
            actor['resources'][resource] = int(pool['maximum'])
        sync_journey_heaven(session,aid)


@hook('attack_mode')
def heavenly_opportunity_mode(ctx, target):
    return 'DISADVANTAGE' if ctx.typed.get('opportunity_of') and heavenly(ctx.engine, target) else None


@hook('native_reaction_roll_mode')
def heavenly_native_opportunity_mode(engine, context):
    target = engine.state.actors.get(context.get('target_id'))
    if context.get('source_id') == 'system:combat.opportunity_attack' and target is not None and heavenly(engine, target):
        return 'DISADVANTAGE'
    return None


@hook('ac')
def empty_cup_frozen_defense(engine, actor):
    """The replacement roll tests pre-movement AC; cover uses the new space
    and the attack's unchanged origin. The nested pure quote excludes itself.
    """
    if AC_QUERY.get():
        return None
    from .attack_scope import current
    frame = current(engine)
    snapshot = frame.get('drunken_fist_cup') if frame else None
    if snapshot is None or snapshot['target'] != actor.entity_id:
        return None
    attacker = engine.state.actors.get(frame['actor_id'])
    if attacker is None:
        return None
    token = AC_QUERY.set(True)
    try:
        original_cover, _ = engine._attack_defense(snapshot['origin'], actor, snapshot['spec'], snapshot['source'])
        _, current_ac = engine._attack_defense(attacker, actor, snapshot['spec'], snapshot['source'])
        return snapshot['bare_ac'] + original_cover - current_ac
    finally:
        AC_QUERY.reset(token)


@hook('skill_bonus_adjustment')
def dormant_acrobatics(engine, actor, name, total):
    if str(name).casefold() != 'acrobatics' or available(engine,actor,SWAY):
        return None
    from .passive_rows import row_of
    row = row_of(engine,actor.entity_id,'drunken_fist_source',SWAY)
    return -int(row.get('acrobatics_bonus',0)) if row else None


@hook('effect_resolution_scope')
def source_cl_scope(ctx, row):
    from .ability_source import mechanic_of
    source = row.get('source_modifier') or ctx.source
    if source not in LEVELS:
        source = mechanic_of(ctx.action)
    if source not in LEVELS or ctx.typed.get('retained_source_cl') is not None:
        return None
    @contextmanager
    def scope():
        old = ctx.typed
        ctx.typed = {**old, 'numbers':{**ctx.numbers,'cl':body_cl(ctx.engine,ctx.actor)}}
        try:
            yield
        finally:
            ctx.typed = old
    return scope()


@hook('condition_excluded')
def dormant_next_check(engine, actor, condition):
    if condition.condition_id==NEXT+'acrobatics' and condition.source_definition_id==SWAY:
        return True if not available(engine,actor,SWAY) else None
    return None
