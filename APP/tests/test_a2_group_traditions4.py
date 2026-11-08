"""A2GTRA4 service previews, committed intents and cold persistence regressions."""
import copy

import pytest

from combat import flight, object_rules, senses, typed_executor
from combat.gate5_service import CombatService
from test_riders_c8 import (
    ROOT, ME, MIND_SPIKE, SPIRITUAL_SENSE, MK_ALL, MD_ALL, MS_ALL, SM_ALL,
    PT_ALL, SW_ALL, MW_ALL, bundle, held,
)
from test_riders_c8_review import service_commit

ENEMY = 'actor:factory.a2gtra4_enemy'
ALLY = 'actor:factory.a2gtra4_ally'
SECOND = 'actor:factory.a2gtra4_second'


def setup(tmp_path, ids, *, control='MANUAL', enemy_kind='humanoid', dc=40, second_at=(9, 7)):
    service = CombatService(ROOT, tmp_path)
    owner = bundle([*ids, SPIRITUAL_SENSE], dc=dc, resonance=100)
    for resource in owner['actor_template']['resources']:
        if resource['resource_id'] == 'resource:named.soul_fragment':
            resource['initial'] = 1
    enemy = bundle([MIND_SPIKE], actor_id=ENEMY, dc=40, cl=5)
    ally = bundle([MIND_SPIKE], actor_id=ALLY)
    second = bundle([MIND_SPIKE], actor_id=SECOND, cl=5)
    for doc in (owner, enemy, ally, second):
        doc['actor_template']['maximum_hp'] = 1000
    enemy['actor_template']['creature_types'] = [enemy_kind]
    # A real typed object packet lets each newly created Asset demonstrate its
    # Resistance through the same service commit pipeline as player techniques.
    probe = copy.deepcopy(next(a for a in enemy['action_catalog'] if a['display_name'] == 'Mind Spike'))
    probe.update(source_definition_id=probe['source_definition_id'] + '.object_probe', display_name='Asset damage probe',
                 target_kind='OBJECT', range_ft=120, costs=[])
    probe['parameters']['typed']['effects'] = [{'type': 'object_damage', 'flat': 10, 'damage_types': ['psychic']}]
    enemy['action_catalog'].append(probe)
    enemy['actor_template']['action_ids'].append(probe['source_definition_id'])
    strike = copy.deepcopy(probe)
    strike.update(source_definition_id=probe['source_definition_id'] + '.strike', display_name='Test paired strike',
                  target_kind='HOSTILE_ENTITY', range_ft=30)
    strike['parameters']['typed']['effects'] = [{'type': 'attack', 'attack_kind': 'cultivation_ranged', 'count': 2,
        'applies_to': 'target', 'on_hit': [{'type': 'damage', 'flat': 1, 'damage_types': ['bludgeoning'], 'applies_to': 'target'}]}]
    enemy['action_catalog'].append(strike)
    enemy['actor_template']['action_ids'].append(strike['source_definition_id'])
    seed = copy.deepcopy(next(a for a in owner['action_catalog'] if a['display_name'] == 'Mind Spike'))
    seed.update(source_definition_id=seed['source_definition_id'] + '.seed_spores', display_name='Plant test spores', costs=[])
    seed['parameters']['typed']['effects'] = [{'type': 'mark', 'mark': 'Dream-Spore Mark', 'extra': True,
        'applies_to': 'target', 'duration': {'kind': 'until_removed'}} for _ in range(3)]
    owner['action_catalog'].append(seed)
    owner['actor_template']['action_ids'].append(seed['source_definition_id'])
    session = service.persistence.create_match(
        match_seed='A2GTRA4-SERVICE', maximum_rounds=30,
        typed_bundles=(owner, enemy, ally, second),
        roster_setup={'primary_actor_ids': [ME, ENEMY, ALLY, SECOND],
                      'team_by_actor': {ME: 'team:a', ALLY: 'team:a', ENEMY: 'team:b', SECOND: 'team:b'},
                      'starting_positions': {ME: {'x': 6, 'y': 6}, ENEMY: {'x': 8, 'y': 6},
                                             ALLY: {'x': 7, 'y': 8}, SECOND: {'x': second_at[0], 'y': second_at[1]}}})
    metadata = {'participant_control_modes': {ME: control, ENEMY: 'MANUAL', ALLY: 'MANUAL', SECOND: 'MANUAL'}}
    return service, session, metadata


def act(service, session, metadata, name, target=None, choose=None, destination=None):
    from combat.gate2_runtime_models import ActionIntent, ReactionDecision
    from combat.gate5_service import _ReactionRequired
    # Match the control modes installed by CombatService._load_session.
    session.engine.typed_control_modes = dict(metadata['participant_control_modes'])
    candidates = [c for c in session.engine.legal_candidates() if (c.display_name == name or c.display_name.startswith(name + ' at ') or c.display_name.startswith(name + ' to '))
                  and (target is None or target in c.target_ids)
                  and (destination is None or c.destination == destination)]
    assert candidates, f"No legal {name}: {[c.display_name for c in session.engine.legal_candidates()][:30]}"
    owner = session.engine.state.actors[session.engine.state.current_actor_id]
    candidate = min(candidates, key=lambda c: session.engine.grid.distance_ft(owner.position, c.destination)
                    if c.destination is not None else 0)
    intent = ActionIntent(intent_id=f'a2gtra4-{candidate.state_version}', decision_id=candidate.decision_id,
                          candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                          actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination)
    decisions, prompts = [], []
    for _ in range(32):
        try:
            preview = service._run_preview(session, metadata, intent, tuple(decisions))
            break
        except _ReactionRequired as paused:
            context = paused.context
            prompts.append(context)
            spec = context.extension_choice
            options = choose(context) if choose else (spec.option_ids[:spec.minimum_selections]
                         if spec and not spec.allow_decline else ())
            decisions.append(ReactionDecision(checkpoint=context.checkpoint, reactor_id=context.reactor_id,
                reaction_source_id=context.reaction_source_id, selection='USE' if options else 'DECLINE', option_ids=options))
    else:
        pytest.fail('Too many service choices')
    before = len(session.engine.events)
    session.mechanical.execute_intent(ActionIntent.model_validate(preview['intent']))
    events = session.engine.events[before:]
    assert [e.model_dump(mode='json') for e in events] == preview['events']
    return events, prompts, preview['resolved_reactions']


def advance(service, session, metadata, actor):
    for _ in range(12):
        if session.engine.state.current_actor_id == actor:
            return
        act(service, session, metadata, 'End turn')
    pytest.fail('Actor never received its turn')


def reload(service, session):
    loaded = CombatService(ROOT, service.persistence.userdata_root).persistence.load_match(session.match_id)
    assert loaded.verify()['status'] == 'PASS'
    return loaded


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
def test_heavenly_flight_is_native_hover_and_walk_is_preserved(tmp_path, control):
    service, session, metadata = setup(tmp_path, MK_ALL, control=control)
    advance(service, session, metadata, ME)
    act(service, session, metadata, 'Choose Descent Movement: Heavenly Flight')
    act(service, session, metadata, 'Kami Descent: Descent of Protection')
    session = reload(service, session)
    me = session.engine.state.actors[ME]
    assert flight.profile(session.engine, me).speed_ft == 60
    assert flight.profile(session.engine, me).hover
    assert session.engine._effective_speed(me) == 30
    candidate = next(c for c in session.engine.legal_candidates() if c.destination is not None
                     and c.destination.z > 0 and (c.metadata or {}).get('movement_mode') == 'fly')
    act(service, session, metadata, candidate.display_name)
    session = reload(service, session)
    assert session.engine.state.actors[ME].position.z > 0
    assert any(e.event_type == 'MOVEMENT_COMMITTED' for e in session.engine.events)


def test_throne_wings_native_flight_after_anatomy_choice(tmp_path):
    service, session, metadata = setup(tmp_path, SM_ALL)
    advance(service, session, metadata, ME)
    def choose(context):
        if context.reaction_source_id.endswith('seraphic.anatomies'):
            return ('throne_wings', 'burning_name')
        spec = context.extension_choice
        return spec.option_ids[:spec.minimum_selections] if spec and not spec.allow_decline else ()
    _, prompts, _ = act(service, session, metadata, 'Molt the Mortal Name', choose=choose)
    assert any('throne_wings' in p.extension_choice.option_ids for p in prompts if p.extension_choice)
    session = reload(service, session)
    me = session.engine.state.actors[ME]
    assert flight.profile(session.engine, me).speed_ft == 60
    assert flight.profile(session.engine, me).hover
    assert me.resources['resource:named.molt_debt'] == 1


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
def test_watchful_guest_spiritual_sense_survives_reload(tmp_path, control):
    service, session, metadata = setup(tmp_path, MD_ALL, control=control)
    advance(service, session, metadata, ME)
    before = senses.of(session.engine, session.engine.state.actors[ME])['spiritual_sense']['range_ft']
    # Gain the printed Rhythm by moving in Spirit Dance, then invite the Guest.
    act(service, session, metadata, 'Spirit Dance: Warding Step')
    candidate = next(c for c in session.engine.legal_candidates() if c.destination is not None
                     and c.display_name.startswith('Move to') and session.engine.grid.distance_ft(
                         c.destination, session.engine.state.actors[ME].position) >= 10)
    act(service, session, metadata, candidate.display_name)
    act(service, session, metadata, 'End turn')
    advance(service, session, metadata, ME)
    act(service, session, metadata, 'Possession Trance: Watchful Guest')
    session = reload(service, session)
    assert senses.of(session.engine, session.engine.state.actors[ME])['spiritual_sense']['range_ft'] == before + 10


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
@pytest.mark.parametrize('kind', ['undead', 'fiend', 'demon', 'intruder', 'humanoid'])
def test_purifying_ground_enemy_first_attack_only(tmp_path, control, kind):
    service, session, metadata = setup(tmp_path, MK_ALL, control=control, enemy_kind=kind)
    advance(service, session, metadata, ME)
    act(service, session, metadata, 'Sacred Ground: Purifying Ground')
    session = reload(service, session)
    advance(service, session, metadata, ENEMY)
    enemy = session.engine.state.actors[ENEMY]
    events, _, _ = act(service, session, metadata, 'Test paired strike', ME)
    rolls = [e.payload for e in events if e.event_type == 'ATTACK_ROLLED']
    assert rolls
    assert bool(enemy.turn_flags.get('miko_first_attack')) == (kind != 'humanoid')
    session = reload(service, session)
    assert (session.engine.state.actors[ENEMY].turn_flags.get('miko_first_attack') is not None) == (kind != 'humanoid')
    assert len(rolls) == 2
    assert rolls[0]['mode'] == ('DISADVANTAGE' if kind != 'humanoid' else 'NORMAL')
    assert rolls[1]['mode'] == 'NORMAL'


@pytest.mark.parametrize('ids,name,prefix,resists', [
    (MS_ALL, 'Borrowed Reflection', 'object:typed.reflection_double:', ['PSYCHIC']),
    (MD_ALL, 'Grand Mudang Procession', 'object:typed.grand_procession:', ['PSYCHIC', 'NECROTIC', 'RADIANT']),
    (PT_ALL, 'Hall of Spoken Deeds', 'object:typed.witness_stone:', ['PSYCHIC']),
    (SW_ALL, 'Lord of the Dead', 'object:typed.warden_wraith:', ['PSYCHIC', 'NECROTIC', 'RADIANT']),
])
def test_asset_printed_resistance_through_object_packet_commit_reload(tmp_path, ids, name, prefix, resists):
    service, session, metadata = setup(tmp_path, ids)
    advance(service, session, metadata, ME)
    act(service, session, metadata, name)
    session = reload(service, session)
    obj = next(o for o in session.engine.state.objects.values() if o.object_id.startswith(prefix) and not o.destroyed)
    assert obj.component['resist'] == resists
    hp = obj.current_hp
    advance(service, session, metadata, ENEMY)
    act(service, session, metadata, 'Asset damage probe', obj.object_id)
    session = reload(service, session)
    assert session.engine.state.objects[obj.object_id].current_hp == hp - 5


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
def test_bloom_mark_spread_harmful_recipient_side_and_lost_trail(tmp_path, control):
    from combat.ext.mushroom_dreamwalker import spores
    service, session, metadata = setup(tmp_path, MW_ALL, control=control)
    advance(service, session, metadata, ME)
    act(service, session, metadata, 'Plant test spores', ENEMY)
    act(service, session, metadata, 'End turn')
    advance(service, session, metadata, ME)
    act(service, session, metadata, 'Hallucinogenic Bloom')
    seen = []
    def choose(context):
        spec = context.extension_choice
        if context.reaction_source_id.endswith('dreamwalker.bloom'):
            return ('lost_trail',)
        if context.reaction_source_id.endswith('dreamwalker.bloom_spread'):
            seen.append(spec.option_ids)
            assert ALLY not in spec.preferred_option_ids and ME not in spec.preferred_option_ids
            return (SECOND,)
        if context.reaction_source_id.endswith('dreamwalker.lost_trail_subject'):
            return (ME,)
        return spec.option_ids[:spec.minimum_selections] if spec and not spec.allow_decline else ()
    # Beginning the enemy turn resolves the real area's save and caster choices.
    while session.engine.state.current_actor_id != ENEMY:
        act(service, session, metadata, 'End turn', choose=choose)
    session = reload(service, session)
    me = session.engine.state.actors[ME]
    assert spores(session.engine, me, session.engine.state.actors[ALLY]) == 0
    assert spores(session.engine, me, session.engine.state.actors[SECOND]) == 1
    assert spores(session.engine, me, session.engine.state.actors[ENEMY]) == 2
    if control == 'MANUAL':
        assert seen
        [bar] = held(session.engine.state.actors[ENEMY], 'condition:typed.no_approach')
        # "until the start of its next turn" is the target's own turn counter. START_OF_TARGET_NEXT_TURN looked
        # right and was not: the engine sweeps it at the walker's next turn too, ending the bar before the
        # target's own next turn came round (bug 3, tests/test_expiry_names.py).
        target = session.engine.state.actors[ENEMY]
        assert bar.data['avoid'] == ME
        assert bar.expires_on == f'START_OF_TURN_AT:{target.entity_id}:{int(target.turns_started) + 1}'


@pytest.mark.parametrize('kind', ['spirit', 'undead', 'humanoid'])
def test_wardens_scythe_hit_denies_only_printed_creature_kinds(tmp_path, kind):
    service, session, metadata = setup(tmp_path, SW_ALL, enemy_kind=kind)
    advance(service, session, metadata, ME)
    act(service, session, metadata, 'Lord of the Dead')
    session = reload(service, session)
    events, _, _ = act(service, session, metadata, "Warden-Wraith: Warden's Scythe", ENEMY)
    assert any(e.event_type == 'DAMAGE_COMMITTED' for e in events)
    session = reload(service, session)
    denied = held(session.engine.state.actors[ENEMY], 'condition:typed.reaction_denied')
    assert bool(denied) == (kind != 'humanoid')
    if denied:
        assert denied[0].expires_on == 'START_OF_SOURCE_NEXT_TURN'


def test_automatic_bloom_spread_declines_when_only_allies_are_near(tmp_path):
    from combat.ext.mushroom_dreamwalker import spores
    service, session, metadata = setup(tmp_path, MW_ALL, control='LOCAL_AUTO', second_at=(0, 0))
    advance(service, session, metadata, ME)
    act(service, session, metadata, 'Plant test spores', ENEMY)
    act(service, session, metadata, 'End turn')
    advance(service, session, metadata, ME)
    act(service, session, metadata, 'Hallucinogenic Bloom')
    while session.engine.state.current_actor_id != ENEMY:
        act(service, session, metadata, 'End turn')
    session = reload(service, session)
    me = session.engine.state.actors[ME]
    assert spores(session.engine, me, session.engine.state.actors[ALLY]) == 0
    assert spores(session.engine, me, session.engine.state.actors[ENEMY]) == 3


@pytest.mark.parametrize('near_enemy', [False, True])
def test_hyphal_spread_automatic_harmful_recipient_side(tmp_path, near_enemy):
    from combat.ext.mushroom_dreamwalker import spores
    service, session, metadata = setup(tmp_path, MW_ALL, control='LOCAL_AUTO',
                                       second_at=(9, 7) if near_enemy else (0, 0))
    advance(service, session, metadata, ME)
    act(service, session, metadata, 'Plant test spores', ENEMY)
    act(service, session, metadata, 'End turn')
    advance(service, session, metadata, ME)
    ally_hp = session.engine.state.actors[ALLY].current_hp
    second_hp = session.engine.state.actors[SECOND].current_hp
    act(service, session, metadata, 'Spore Murmur: Psychic', ENEMY)
    session = reload(service, session)
    me = session.engine.state.actors[ME]
    assert session.engine.state.actors[ALLY].current_hp == ally_hp
    assert spores(session.engine, me, session.engine.state.actors[ALLY]) == 0
    assert spores(session.engine, me, session.engine.state.actors[SECOND]) == int(near_enemy)
    assert session.engine.state.actors[SECOND].current_hp == second_hp - (12 if near_enemy else 0)
