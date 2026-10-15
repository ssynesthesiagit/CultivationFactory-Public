"""Drunken Fist's native posture, hit, roll and timed-state consumers.

All declarations come from owned compiled source rows. Posture is committed by
native condition/stand transitions, steps use native separate-budget movement,
and frequency receipts live in replayable conditions rather than engine scratch.
No owned row/state means no changed rolls, movement, prompts or events.
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
CROSS = ContextVar('drunken_cup_crossing', default=None)
GRANTED = ContextVar('drunken_granted_attack', default=None)
AC_QUERY = ContextVar('drunken_cup_ac_query', default=False)


def heavenly(engine, actor):
    from .states import active
    return actor.active and active(engine, actor, STATE)


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
    else:
        row['bonus'] = int(row['bonus']) + int(info['pb'])
        row['proficiency_multiplier'] = 1
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
            run_effects(ctx, [{'type':'general_rider_step', 'distance_ft':int(row['move_ft']),
                              'no_oa':True, 'label':'Swaying Step'}])


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
        expires_on='START_OF_SELF_NEXT_TURN', data={'source_cl':int(ctx.numbers.get('cl') or 1), 'label': 'Swaying Step: Advantage on next ' +
            ('Dexterity saving throw' if row['roll'] == 'save' else 'Acrobatics check') + ' before your next turn'})


@hook('save')
def next_dex(ctx, actor, ability, named):
    if ctx is not None and str(ability).upper()[:3] == 'DEX' and any(c.condition_id == NEXT+'save' for c in actor.conditions.values()):
        ctx.engine._remove_condition(actor, NEXT+'save', SWAY)
        return {'bonus': 0, 'modes': ['ADVANTAGE']}
    return None


@hook('ability_check_mode')
def next_acrobatics(engine, actor, ability, skill, against):
    if str(skill).casefold() == 'acrobatics' and any(c.condition_id == NEXT+'acrobatics' for c in actor.conditions.values()):
        return 'ADVANTAGE'
    return None


@hook('event', nested=True)
def consume_check(engine, event_type, kwargs):
    from .roll_context import check_skill_receipts
    for aid, roll, skill in check_skill_receipts(kwargs) if event_type == 'CHECK_ROLLED' else ():
        actor = engine.state.actors.get(aid)
        if actor is not None and str(skill).casefold() == 'acrobatics' and any(c.condition_id == NEXT+'acrobatics' for c in actor.conditions.values()):
            engine._remove_condition(actor, NEXT+'acrobatics', SWAY)


@effect('drunken_speed')
def slow(ctx, row):
    from .owned_effects import remove_conditions
    remove_conditions(ctx.engine, ctx.target, BLOW, ctx.actor.entity_id, SLOW)
    ctx.engine._apply_condition(ctx.target, SLOW, BLOW, ctx.actor.entity_id,
        expires_on='START_OF_SOURCE_NEXT_TURN', data={'source_cl':int(ctx.numbers.get('cl') or 1), 'feet': int(row['feet']),
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
    engine._apply_condition(defender, cid, HEAVEN, defender.entity_id, expires_on='UNTIL_REMOVED',
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
    if frame is not None:
        cover, current_ac = engine._attack_defense(rc.roller, actor, rc.spec or {}, rc.source_id)
        frame['drunken_fist_cup'] = {'target':actor.entity_id, 'origin':rc.roller.model_copy(deep=True),
                                    'bare_ac':int(rc.ac if rc.ac is not None else current_ac)-cover,
                                    'spec':rc.spec or {}, 'source':rc.source_id}
    sub = feature_context(engine, actor, holder.feature_id, rc.roller, getattr(engine, '_active_intent', None))
    token = CROSS.set({'engine': engine, 'actor': actor.entity_id, 'crossed': None, 'permitted': None})
    remaining = 10
    try:
        for segment in range(3):
            prone = bool(native.prone_conditions(actor))
            options = ['stay', 'stand' if prone else 'fall_prone']
            picked = ask(engine, sub.intent, checkpoint_id(engine, 'empty_cup_posture', actor.entity_id, segment), actor,
                'choice:needle.empty_cup_posture', options, preferred=['stay'], allow_decline=True,
                labels={'stay': 'Keep your posture', 'stand': 'Stand from Prone without movement cost', 'fall_prone': 'Intentionally fall Prone'},
                prompt=f'Empty Cup: during {rc.roller.display_name}’s rerolled attack, {actor.display_name} may change posture; {remaining} feet of granted movement remain.',
                target_id=actor.entity_id)
            if picked == ['fall_prone']:
                posture(sub, {'posture': 'fall'})
            elif picked == ['stand']:
                posture(sub, {'posture': 'stand'})
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
                target_id=actor.entity_id)
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
        expires_on='START_OF_SELF_NEXT_TURN', data={'source_cl':int(ctx.numbers.get('cl') or 1), 'label': 'Heavenly Drunk: +2 AC after intentionally falling Prone'})


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
    return [ActionDefinition(source_definition_id=FIST+'#intentional_fall',
        display_name='Fall Prone intentionally', owner_id=info['actor_id'], economy=EconomyKind.NONE,
        resolution_kind='TYPED', target_kind='SELF', parameters={'typed': {
            'source': FIST+'#intentional_fall', 'effects': [{'type':'drunken_posture','posture':'fall'}],
            'duration':{'kind':'instant'}, 'numbers':dict(info['numbers']), 'riders':[]}})]


@hook('candidate_allowed')
def fall_only_while_upright(engine, actor, candidate, action):
    if getattr(action, 'source_definition_id', '') == FIST+'#intentional_fall':
        from ..posture import prone_conditions
        return False if prone_conditions(actor) else None
    from .ability_source import mechanic_of
    from .passive_rows import row_of
    if (action is not None and mechanic_of(action) == 'tianxia.path.body_refining.feature.stomping_step'
            and row_of(engine, actor.entity_id, 'drunken_fist_source', SWAY)):
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
    if candidate.source_definition_id != FIST+'#intentional_fall':
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
                   'source_cl':int(info['numbers']['cl'])}]


def journey_heaven_action(session, aid):
    """Read the acquired ability from this journey's sealed combat bundle."""
    from .activation_requirements import min_cl_ready
    return next((a for a in session.state['actors'][aid]['bundle']['action_catalog']
                 if (a.get('parameters', {}).get('typed') or {}).get('source') == HEAVEN
                 and min_cl_ready(None, a['parameters']['typed']) is not False), None)


@hook('journey_options')
def heavenly_journey_options(session, aid):
    actor = session.state['actors'][aid]
    if (session.state['phase'] != 'travel' or actor['incapacitated'] or not journey_heaven_action(session, aid)
            or actor['travel_uses'].get(HEAVEN) == session.state['journey_id']
            or actor['resources'].get('resource:core.stamina', 0) < 6):
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
    actor['resources']['resource:core.stamina'] -= 6
    actor['travel_uses'][HEAVEN] = session.state['journey_id']
    for resource, amount in journey_heaven_action(session, aid).get('costs', ()):
        if resource.startswith('resource:uses.'):
            actor['resources'][resource] = 0
    deadline = session.clock() + 60
    actor['travel_effects'][HEAVEN] = {'expiry_num': deadline.numerator, 'expiry_den': deadline.denominator,
        'source_cl': int(actor['bundle']['cl']), 'paid_stamina': 6}
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
    actor['bundle']['drunken_fist_journey'] = {'remaining_num': remaining.numerator, 'remaining_den': remaining.denominator,
        'scene_used': int(actor['travel_uses'].get(HEAVEN) == session.state['journey_id']),
        'source_cl': int(actor['bundle']['cl'])}
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
        effects = copy.deepcopy(sub.typed['effects'])
        for row in effects:
            row['duration'] = {'kind': 'rounds', 'amount': rounds}
        run_effects(sub, effects)
        applied = True
    return True if applied else None


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
