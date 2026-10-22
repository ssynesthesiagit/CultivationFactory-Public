"""Dream Qi: native source acquisition, elapsed rituals and table cold replay.

The installed documents have no Dream Qi feature IDs. Only the accepted native
acquisition publishes them. No live model transport or browser is used.
"""
import json
from types import SimpleNamespace
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import candidate, settle, turn

P = 'tianxia.subpath.qi.dream_qi_cultivator'
A, B = 'actor:factory.dreamer', 'actor:factory.sleeper'
C = 'actor:factory.other-dreamer'
QI = 'resource:core.qi'


def game(tmp_path, monkeypatch, cl=18, acquire=True, dc=100, extra=False, clever=False, target_cl=None):
    # A stable native journey ID fixes the real roll-authority seed. These
    # scenarios exercise ordinary hits; critical/miss rules are unchanged.
    monkeypatch.setattr('combat.journey.secrets', SimpleNamespace(token_hex=lambda n: '00000000000000000000000f'))
    docs = {'dreamer': sheet([], cl=cl, name='Wren', dc=dc), 'sleeper': sheet([], cl=cl, name='Mara')}
    if extra:
        docs['other-dreamer'] = sheet([], cl=cl, name='Sable')
    for key, doc in docs.items():
        if key != 'dreamer':
            if target_cl is not None:
                doc['identity']['cultivation_level'] = target_cl
            if clever:
                for ability in doc['ability_scores_and_statistics']['abilities']:
                    if ability['ability'] == 'WIS':
                        ability.update(score=1, modifier=-5)
                    if ability['ability'] == 'INT':
                        ability.update(score=80, modifier=35)
    for doc in docs.values():
        doc['path_and_subpath'] = {'path_record_ids': ['tianxia.path.qi_cultivation'],
            'paths': [{'path_id': 'tianxia.path.qi_cultivation', 'attainment': doc['identity']['cultivation_level']}]}
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 500
        doc['ability_scores_and_statistics']['technique_attack_bonus'] = 100
    monkeypatch.setattr(CombatService, '_factory_owner_sheet', lambda self, pid: docs[pid])
    arena = {'display_name': 'Dream courtyard', 'stable_id': 'battlefield:dream-test', 'width_squares': 14,
             'height_squares': 14, 'square_size_ft': 5, 'starting_positions': {}, 'terrain_regions': []}
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self, **kw: {'scene': arena})
    def cold():
        return CombatService(ROOT, tmp_path)
    positions = {A: {'x': 3, 'y': 3}, B: {'x': 4, 'y': 3}, **({C: {'x': 5, 'y': 3}} if extra else {})}
    state = cold().create_journey(project_ids=list(docs), arena_id='scene',
        positions=positions, base_paces={aid: 100 for aid in positions})
    jid = state['journey_id']
    def act(kind, payload=None, actor=A):
        old = cold().journey_state(jid)
        result = cold().journey_act(jid, old['revision'], actor, kind, payload)
        assert cold().journey_state(jid) == result
        return result
    def fact(subject, kind, scope, value, world=False, readers=None):
        old = cold().journey_state(jid)
        payload = {'source': P, 'subject': subject, 'kind': kind, 'scope': scope,
                   'value': value, 'expires_at': old['seconds'] + 28000, 'readers': readers if readers is not None else [A, B]}
        return cold().journey_world_fact(jid, old['revision'], payload) if world else act('declare_fact', payload, subject)
    if acquire:
        fact(A, 'source_access', 'scripture', {'scripture': P, 'source_rule': 'Restricted Scripture granted by the native world owner under Dream Qi R19.'}, world=True)
        old = cold().journey_state(jid)
        state = cold().journey_acquire_source(jid, old['revision'], A, P, {'access_scope': 'scripture'})
        assert any(e['kind'] == 'DREAM_QI_ACQUIRED' for e in state['events'])
        assert not any('dream_qi' in str(doc) for doc in docs.values())
    return cold, jid, act, fact


def fight(cold, jid, tmp_path):
    old = cold().journey_state(jid)
    mid = cold().journey_start_combat(jid, old['revision'], {aid: 'team:a' if aid == A else 'team:b' for aid in old['actors']})['match_id']
    service = cold()
    table = TabletopService(service, tmp_path)
    turn(table, mid, A)
    return service, table, mid


def loaded(cold, mid):
    saved = cold()._load_session(mid)
    assert saved.mechanical.replay()['status'] == 'PASS'
    return saved.engine


def data(engine, aid=A):
    return json.loads(next(c.data['state'] for c in engine.state.actors[aid].conditions.values()
                          if c.condition_id == 'condition:typed.dream_qi_ledger'))


@pytest.mark.parametrize('cl,expected', [(3, 1), (6, 2), (10, 3), (14, 4), (18, 5)])
def test_acquisition_native_progression_and_wrong_owner(tmp_path, monkeypatch, cl, expected):
    cold, jid, act, fact = game(tmp_path, monkeypatch, cl=cl)
    state = cold().journey_state(jid)
    rows = state['actors'][A]['bundle']['typed_passives']
    assert len([r for r in rows if r.get('block') == 'dream_qi_native']) == expected
    assert not any(r.get('block') == 'dream_qi_native' for r in state['actors'][B]['bundle']['typed_passives'])
    with pytest.raises(ValueError, match='already|coexist|reset|occupies'):
        cold().journey_acquire_source(jid, state['revision'], A, P, {'access_scope': 'scripture'})
    with pytest.raises(ValueError):
        act('dream_rest_mode', {'mode': 'sleeping'}, B)
    assert cold().journey_state(jid) == state


def harvest_inputs(fact, *, mode='cultivation', recursive=0, created_by='', fail_save=1):
    fact(B, 'inner_state', 'mind', {'genuine_consciousness': 1, 'genuine_dreams': 1,
         'created_by': created_by, 'recursive': recursive, 'mindless': 0, 'equivalent_source': ''}, world=True)
    fact(B, 'harvest_consent', 'donor', {'harvester': A, 'willing': 1, 'fail_save': fail_save})
    fact(B, 'dream_content', 'dream', {'association': 'the courtyard', 'fragment': 'Moonlight at the courtyard gate',
         'emotion': 'hope', 'protected_kind': '', 'protection_dc': 0}, readers=[A])
    if mode == 'memory':
        fact(B, 'memory_authority', 'dream', {'kind': 'surface', 'dc': 0, 'source_rule': 'The world owner confirms this is an unsealed brief surface association.'}, world=True)
    return {'target': B, 'mode': mode, 'inner_scope': 'mind', 'consent_scope': 'donor',
            'content_scope': 'dream', 'association': 'the courtyard', 'resource': QI}


def seed_native_snapshot(cold, jid, aid, *, conditions):
    """Write a persisted encounter snapshot the way journey_resume produces it.

    This is a real native snapshot (the same integer/string shape
    journey_setup.encounter_snapshot writes), not a fabricated trigger receipt:
    the following Harvest still runs through the service, saves, and replays.
    """
    session = cold().journeys.load(jid)
    session.state['actors'][aid]['encounter_snapshot'] = {
        'current_hp': 500, 'maximum_hp': 500, 'temporary_hp': 0, 'active': 1,
        'life_state': '', 'conditions': conditions,
        'death_saves': {'ok': 0, 'bad': 0}}
    with cold().journeys.locked(jid):
        cold().journeys.save(session)
    from combat.journey_replay import initialize
    session = cold().journeys.load(jid)
    initialize(session)
    with cold().journeys.locked(jid):
        cold().journeys.save(session)


@pytest.mark.parametrize('rule,expected', [
    ({'damage_resistances': ['PSYCHIC']}, 'half'),
    ({'damage_immunities': ['PSYCHIC']}, 'none')])
def test_harvest_defended_target_uses_native_damage_settlement_and_cold_reload(tmp_path, monkeypatch, rule, expected):
    from combat.gate2_runtime_models import ConditionInstance
    cold, jid, act, fact = game(tmp_path, monkeypatch, dc=1)
    payload = harvest_inputs(fact, mode='emotion', fail_save=0)
    defense = ConditionInstance(instance_id='journey:test_psychic_defense',
        condition_id='condition:typed.test_psychic_defense', source_definition_id='test:defense',
        source_actor_id=B, target_id=B, stacks=1, applied_sequence=0, expires_on='UNTIL_REMOVED',
        data={'label': 'Native Psychic defense', 'rule': rule})
    seed_native_snapshot(cold, jid, B, conditions={'journey:test_psychic_defense': defense.model_dump_json()})
    state = act('dream_harvest', payload)
    packets = [event for event in state['events'] if event['kind'] == 'DAMAGE_COMMITTED'
               and event['source_definition_id'] == P + '.feature.dream_refinement']
    assert len(packets) == 1
    packet = packets[0]
    assert packet['damage_type'] == 'PSYCHIC' and packet['rolled_or_pending_damage'] > 0
    assert packet['reduced_to'] == (0 if expected == 'none' else packet['rolled_or_pending_damage'] // 2)
    assert packet['hp_damage'] == packet['reduced_to'] and packet['temporary_hp_absorbed'] == 0
    assert state['actors'][B]['encounter_snapshot']['current_hp'] == 500 - packet['hp_damage']
    assert cold().journey_state(jid) == state
    assert cold().journey_verify(jid)['status'] == 'PASS'


@pytest.mark.parametrize('mode', ['cultivation', 'memory', 'emotion'])
def test_harvest_paid_ten_minutes_private_result_repetition_cold_state(tmp_path, monkeypatch, mode):
    cold, jid, act, fact = game(tmp_path, monkeypatch)
    payload = harvest_inputs(fact, mode=mode)
    state = act('dream_harvest', payload)
    assert state['seconds'] == 600
    own = state['actors'][A]['source_states'][P]
    other = state['actors'][B]['source_states'][P]
    assert other['harvests'] == 1 and other['successes'] == 1
    if mode == 'cultivation':
        assert state['actors'][B]['resources'][QI] == 26
        assert other['drained'][QI] == 4 and state['actors'][B]['exhaustion'] == 1
    elif mode == 'memory':
        assert json.loads(own['memory'])['fragment'] == 'Moonlight at the courtyard gate'
        assert other['blurred_association'] == 'the courtyard'
    else:
        assert own['resonance'] == 1 and own['emotion'] == 'hope'
    state = act('dream_harvest', payload)
    assert state['seconds'] == 1200 and state['actors'][B]['exhaustion'] == (3 if mode == 'cultivation' else 1)
    assert state['actors'][B]['encounter_snapshot']['current_hp'] < 500
    assert cold().journey_verify(jid)['status'] == 'PASS'
    service, table, mid = fight(cold, jid, tmp_path)
    engine = loaded(cold, mid)
    assert data(engine, B)['harvests'] == 2
    assert engine.state.actors[B].current_hp == state['actors'][B]['encounter_snapshot']['current_hp']


@pytest.mark.parametrize('guard', ['recursive', 'own_creation', 'privacy', 'no_consent'])
def test_harvest_admission_atomic_guards(tmp_path, monkeypatch, guard):
    cold, jid, act, fact = game(tmp_path, monkeypatch)
    payload = harvest_inputs(fact, recursive=int(guard == 'recursive'), created_by=A if guard == 'own_creation' else '')
    if guard == 'privacy':
        fact(B, 'inner_state', 'mind', {'genuine_consciousness': 1, 'genuine_dreams': 1,
             'created_by': '', 'recursive': 0, 'mindless': 0, 'equivalent_source': ''}, world=True, readers=[])
    if guard == 'no_consent':
        fact(B, 'harvest_consent', 'donor', {'harvester': A, 'willing': 0, 'fail_save': 0})
    before = cold().journey_state(jid)
    with pytest.raises(ValueError):
        act('dream_harvest', payload)
    assert cold().journey_state(jid) == before


def test_rest_normal_recovery_then_extra_and_cap_without_maximum_change(tmp_path, monkeypatch):
    cold, jid, act, fact = game(tmp_path, monkeypatch)
    payload = harvest_inputs(fact, mode='emotion')
    # Real paid starts and native cancellations leave 14 Qi. Normal Long Rest
    # recovery reaches only 29, so the additional recovery changes the result.
    act('dream_harvest', payload)
    for _ in range(7):
        act('activity_start', {'source': P + '.feature.dream_refinement', 'parameters': payload})
        act('activity_cancel')
    assert cold().journey_state(jid)['actors'][A]['resources'][QI] == 14
    state = act('long_rest')
    assert state['actors'][A]['resources'][QI] == 30
    assert 'resonance' not in state['actors'][A]['source_states'][P]
    kinds = [e['kind'] for e in state['events']]
    assert kinds.index('DREAM_NORMAL_QI_RECOVERY') < kinds.index('DREAM_ONEIRIC_RECOVERY')
    gains = [e['amount'] for e in state['events'] if e['kind'] == 'DREAM_RESOURCE_RECOVERED' and e['actor_id'] == A]
    assert gains[-2:] == [15, 1]
    assert next(r['maximum'] for r in state['actors'][A]['bundle']['actor_template']['resources'] if r['resource_id'] == QI) == 30
    assert cold().journey_verify(jid)['status'] == 'PASS'


def test_concordance_native_target_consent_anchor_bound_cold_replay(tmp_path, monkeypatch):
    cold, jid, act, fact = game(tmp_path, monkeypatch)
    service, table, mid = fight(cold, jid, tmp_path)
    rows = [a.display_name for a in service._load_session(mid).engine.action_catalog.values() if a.owner_id == A]
    assert 'Shared Dream Concordance' in rows
    prompts = settle(table, mid, candidate(service, mid, 'Shared Dream Concordance').candidate_id,
        choices={'choice:needle.dream_qi.concord_targets': [A, B], 'choice:needle.dream_qi.link_consent': ('link', 'resist')})
    assert any('Mara' in p.get('prompt', p.get('text', '')) or p.get('context') for p in prompts)
    engine = loaded(cold, mid)
    assert any(c.condition_id == 'condition:typed.dream_qi_link' for c in engine.state.actors[A].conditions.values())
    assert any(c.condition_id == 'condition:typed.dream_qi_bound' for c in engine.state.actors[B].conditions.values())
    anchor = engine.state.objects[data(engine)['concord']['anchor']]
    assert anchor.ac == 100 and anchor.maximum_hp == 72 and set(anchor.damage_immunities) == {'PSYCHIC', 'POISON'}
    assert engine.state.actors[A].resources[QI] == 25
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    before = engine.state.actors[A].movement_remaining_ft
    settle(table, mid, candidate(service, mid, 'Walk the Shared Dream').candidate_id,
        choices={'choice:needle.dream_qi.walk_target': A, 'choice:needle.dream_qi.walk_result': 'self_move',
                 'choice:needle.dream_qi.walk_move': cell_id(Position(x=3, y=4))})
    engine = loaded(cold, mid)
    assert engine.state.actors[A].position == Position(x=3, y=4)
    assert engine.state.actors[A].movement_remaining_ft == before


def test_ascension_native_field_concentration_discount_bonus_options_and_replay(tmp_path, monkeypatch):
    cold, jid, act, fact = game(tmp_path, monkeypatch)
    service, table, mid = fight(cold, jid, tmp_path)
    settle(table, mid, candidate(service, mid, 'Dream Ascension', at=(3, 3)).candidate_id, choices={})
    engine = loaded(cold, mid)
    assert engine.state.actors[A].resources[QI] == 22
    zones = [z for z in engine.state.zones.values() if z.active and z.owner_id == A]
    assert len(zones) == 1 and zones[0].trigger_profile['height_ft'] == 30
    assert data(engine)['ascension_used'] == 1
    candidates = engine.legal_candidates()
    assert any('Ascendant Bonus Action' in c.display_name for c in candidates)
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
    turn(table, mid, A)
    # Refine a Waking Dream is printed as an Action, and the free Ascension use
    # replaces only its Qi cost. The Ascension itself already spent this turn's
    # Action, so the free use is offered from the dreamer's next turn onward.
    assert any('free Ascension use' in c.display_name for c in loaded(cold, mid).legal_candidates())
    settle(table, mid, candidate(service, mid, 'Lucid Strike: Stolen Reaction (Ascendant Bonus Action)', target=B).candidate_id, choices={})
    before = loaded(cold, mid).state.actors[A].resources[QI]
    settle(table, mid, candidate(service, mid, 'Refine a Waking Dream: free Ascension use', target=B).candidate_id,
        choices={'choice:needle.dream_qi.refinement_result': 'temp_hp'})
    engine = loaded(cold, mid)
    assert engine.state.actors[A].resources[QI] == before
    assert engine.state.actors[A].temporary_hp == 12
    assert data(engine)['free_refine_used'] == 1


def test_lucid_strike_native_damage_distortion_payment_and_expiry(tmp_path, monkeypatch):
    cold, jid, act, fact = game(tmp_path, monkeypatch)
    service, table, mid = fight(cold, jid, tmp_path)
    settle(table, mid, candidate(service, mid, 'Lucid Strike: Stolen Reaction', target=B).candidate_id)
    engine = loaded(cold, mid)
    assert any(c.condition_id.endswith('.reaction_denied') for c in engine.state.actors[B].conditions.values())
    assert engine.state.actors[A].resources[QI] == 28
    # Refinement's target is eligible through a committed condition. The same
    # owner turn cannot take a second Action; spend the next turn's Action before
    # its own new Lucid Distortion expires by acquiring an independent one first.
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, A)
    # Once the next turn begins, Lucid's source-start expiry must remove it.
    engine = loaded(cold, mid)
    assert not any('lucid_strike' in c.source_definition_id for c in engine.state.actors[B].conditions.values())


@pytest.mark.parametrize('cl,dice', [(6, 3), (11, 4), (17, 5)])
@pytest.mark.parametrize('option,condition', [('Stolen Reaction', 'reaction_denied'), ('Endless Corridor', 'speed'),
    ('False Opening', 'attack_mode'), ('Fractured Concentration', 'concentration_mode'), ('Shifting Horizon', 'lucid_horizon')])
def test_all_lucid_distortions_from_native_acquisition_scale_pay_and_expire(tmp_path, monkeypatch, cl, dice, option, condition):
    cold, jid, act, fact = game(tmp_path, monkeypatch, cl=cl)
    service, table, mid = fight(cold, jid, tmp_path)
    settle(table, mid, candidate(service, mid, 'Lucid Strike: ' + option, target=B).candidate_id, choices={})
    engine = loaded(cold, mid)
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_ROLLED' and e.actor_id == A]
    assert damage and damage[-1].payload['expression'].startswith(str(dice) + 'd8')
    assert engine.state.actors[A].resources[QI] == 28
    if condition == 'speed':
        assert any(m.target_field == 'speed_ft' and m.value == -10 for m in engine.state.actors[B].modifiers.values())
    elif condition == 'attack_mode':
        assert any(m.target_field == 'attack_mode' and m.value == 'DISADVANTAGE' for m in engine.state.actors[B].modifiers.values())
    else:
        assert any(condition in c.condition_id for c in engine.state.actors[B].conditions.values())
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
    turn(table, mid, A)
    engine = loaded(cold, mid)
    assert not any('lucid_strike' in c.source_definition_id for c in engine.state.actors[B].conditions.values())
    assert not any('lucid_strike' in m.source_definition_id for m in engine.state.actors[B].modifiers.values())


@pytest.mark.parametrize('distortion,field', [('Endless Corridor', 'speed_ft'), ('False Opening', 'attack_mode')])
def test_modifier_distortion_allows_native_waking_refinement_outside_ascension(tmp_path, monkeypatch, distortion, field):
    cold, jid, act, fact = game(tmp_path, monkeypatch)
    act('move', {'path': [{'x': x, 'y': 3} for x in range(5, 11)]}, B)
    service, table, mid = fight(cold, jid, tmp_path)
    # Ascension gives the caster a Bonus Action Lucid Strike. The recipient is
    # outside its field, so only the actual Distortion can admit Refinement.
    settle(table, mid, candidate(service, mid, 'Dream Ascension', at=(0, 3)).candidate_id, choices={})
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
    turn(table, mid, A)
    settle(table, mid, candidate(service, mid, f'Lucid Strike: {distortion} (Ascendant Bonus Action)', target=B).candidate_id, choices={})
    engine = loaded(cold, mid)
    from combat.ext.dream_qi import dreaming
    assert dreaming(engine, engine.state.actors[A], engine.state.actors[B])
    assert any(m.target_field == field for m in engine.state.actors[B].modifiers.values())
    before = engine.state.actors[A].resources[QI]
    settle(table, mid, candidate(service, mid, 'Refine a Waking Dream: Temporary Hit Points', target=B).candidate_id,
           choices={'choice:needle.dream_qi.refinement_result': 'remove'})
    engine = loaded(cold, mid)
    assert engine.state.actors[A].resources[QI] == before - 2
    assert not any(m.target_field == field and 'lucid_strike' in m.source_definition_id
                   for m in engine.state.actors[B].modifiers.values())


def test_dream_ward_against_native_other_dreamer_and_cold_replay(tmp_path, monkeypatch):
    cold, jid, act, fact = game(tmp_path, monkeypatch, dc=16)
    fact(B, 'source_access', 'scripture-b', {'scripture': P, 'source_rule': 'The world owner grants this second creature the Restricted Scripture.'}, world=True)
    state = cold().journey_state(jid)
    cold().journey_acquire_source(jid, state['revision'], B, P, {'access_scope': 'scripture-b'})
    service, table, mid = fight(cold, jid, tmp_path)
    turn(table, mid, B)
    settle(table, mid, candidate(service, mid, 'Lucid Strike: Stolen Reaction', target=A).candidate_id, choices={})
    engine = loaded(cold, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == A]
    assert saves and saves[-1].payload['mode'] == 'ADVANTAGE'


def test_awareness_native_world_threat_awakens_without_actions_and_sleep_blocks_move(tmp_path, monkeypatch):
    cold, jid, act, fact = game(tmp_path, monkeypatch, cl=3)
    state = act('dream_rest_mode', {'mode': 'sleeping'})
    assert state['actors'][A]['source_states'][P]['rest_mode'] == 'sleeping'
    with pytest.raises(ValueError, match='Awaken'):
        act('move', {'path': [{'x': 3, 'y': 4}]})
    with pytest.raises(ValueError, match='Awaken'):
        act('dream_harvest', harvest_inputs(fact))
    fact(A, 'rest_threat', 'footsteps', {'perception_dc': 1, 'source_rule': '', 'sealed_sleep_cl': 0}, world=True)
    state = act('dream_notice_threat', {'scope': 'footsteps'})
    assert state['seconds'] == 0 and state['actors'][A]['source_states'][P]['rest_mode'] == 'awake'
    assert state['events'][-1]['awakened'] == 1
    assert cold().journey_verify(jid)['status'] == 'PASS'


def test_harvest_target_without_dream_qi_can_finish_native_full_cultivation(tmp_path, monkeypatch):
    cold, jid, act, fact = game(tmp_path, monkeypatch)
    act('dream_harvest', harvest_inputs(fact))
    fact(B, 'cultivation_environment', 'calm', 1)
    state = act('dream_cultivation', {'environment_scope': 'calm'}, B)
    assert state['seconds'] == 7800
    assert state['actors'][B]['source_states'][P]['drained'] == {}
    assert state['actors'][B]['resources'][QI] == 30
    assert state['actors'][B]['source_states'][P]['harvests'] == 0


def test_ascension_native_ground_trigger_then_wake_by_force(tmp_path, monkeypatch):
    cold, jid, act, fact = game(tmp_path, monkeypatch, dc=1)
    service, table, mid = fight(cold, jid, tmp_path)
    settle(table, mid, candidate(service, mid, 'Dream Ascension', at=(3, 3)).candidate_id, choices={})
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
    turn(table, mid, B)
    engine = loaded(cold, mid)
    assert engine.state.actors[B].current_hp < 500
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == B for e in engine.events)
    settle(table, mid, candidate(service, mid, 'Wake by Force').candidate_id,
           choices={'choice:needle.dream_qi.wake_check': 'wis'})
    engine = loaded(cold, mid)
    assert any(c.condition_id == 'condition:typed.dream_qi_force' for c in engine.state.actors[B].conditions.values())
    from combat import zones
    assert (engine.state.actors[B].position.x, engine.state.actors[B].position.y) not in zones.difficult_cells(engine, engine.state.actors[B])


def test_wake_actions_are_installed_again_on_a_cold_reload_and_offered_as_catalog_ids(tmp_path, monkeypatch):
    """The field/link Actions are engine-local, so every reload must install them.

    match_start runs before a reloaded fight replaces its saved state, so the
    installation may only read compiled passive rows and never engine.state.actors.
    additional_actions also takes catalog ids, not definitions.
    """
    cold, jid, act, fact = game(tmp_path, monkeypatch, dc=1)
    service, table, mid = fight(cold, jid, tmp_path)
    settle(table, mid, candidate(service, mid, 'Dream Ascension', at=(3, 3)).candidate_id, choices={})
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
    turn(table, mid, B)
    engine = loaded(cold, mid)  # a cold reload is where a state-dependent gate lost the install
    from combat.ext.dream_qi import offer_wake
    offered = offer_wake(engine, engine.state.actors[B])
    assert 'system:dream_qi.wake.force' in offered
    assert all(isinstance(source, str) and source in engine.action_catalog for source in offered)


def test_native_harvest_activity_charges_once_interrupts_without_reward_and_replays(tmp_path, monkeypatch):
    cold, jid, act, fact = game(tmp_path, monkeypatch)
    payload = harvest_inputs(fact, mode='emotion')
    state = act('activity_start', {'source': P + '.feature.dream_refinement', 'parameters': payload})
    assert state['actors'][A]['resources'][QI] == 28
    state = act('activity_work', {'seconds': 300})
    assert state['seconds'] == 300 and not state['actors'][A]['source_states'][P].get('resonance')
    state = act('move', {'path': [{'x': 5, 'y': 3}]}, B)
    assert 'journey:activity' not in state['actors'][A]['source_states']
    assert state['actors'][A]['resources'][QI] == 28
    assert not state['actors'][A]['source_states'][P].get('resonance')
    act('move', {'path': [{'x': 4, 'y': 3}]}, B)
    act('activity_start', {'source': P + '.feature.dream_refinement', 'parameters': payload})
    state = act('activity_work', {'seconds': 600})
    assert state['actors'][A]['resources'][QI] == 26
    assert state['actors'][A]['source_states'][P]['resonance'] == 1
    assert cold().journey_verify(jid)['status'] == 'PASS'


def test_surface_blur_consumes_on_actual_relevant_native_check_and_replays(tmp_path, monkeypatch):
    cold, jid, act, fact = game(tmp_path, monkeypatch)
    act('dream_harvest', harvest_inputs(fact, mode='memory'))
    fact(B, 'surface_check', 'recall', {'association': 'the courtyard', 'ability': 'INT', 'skill': '', 'dc': 12}, world=True)
    state = act('dream_surface_check', {'scope': 'recall'}, B)
    assert 'blurred_association' not in state['actors'][B]['source_states'][P]
    rolled = [e for e in state['events'] if e['kind'] == 'DREAM_ROLLED' and e.get('reason') == 'BLURRED_SURFACE_ASSOCIATION']
    assert len(rolled) == 1 and rolled[0]['roll']['mode'] == 'DISADVANTAGE'
    assert cold().journey_verify(jid)['status'] == 'PASS'


def test_harvest_dream_ward_asks_after_failed_native_save_and_blocks_time_until_answer(tmp_path, monkeypatch):
    cold, jid, act, fact = game(tmp_path, monkeypatch)
    fact(B, 'source_access', 'scripture-b', {'scripture': P, 'source_rule': 'The world owner grants this second creature the Restricted Scripture.'}, world=True)
    state = cold().journey_state(jid)
    cold().journey_acquire_source(jid, state['revision'], B, P, {'access_scope': 'scripture-b'})
    payload = harvest_inputs(fact)
    fact(B, 'harvest_consent', 'donor', {'harvester': A, 'willing': 1, 'fail_save': 0})
    state = act('dream_harvest', payload)
    assert state['seconds'] == 600 and state['actors'][A]['resources'][QI] == 28
    assert state['actors'][B]['resources'][QI] == 30
    assert state['actors'][B]['source_states'][P]['harvest_save']['total'] < 100
    options = cold().journey_menu(jid, B)['options']
    assert {o['payload']['use_ward'] for o in options if o['kind'] == 'dream_harvest_save'} == {0, 1}
    with pytest.raises(ValueError, match='pending Dream Ward'):
        act('wait', {'seconds': 1})
    assert cold().journey_state(jid) == state
    state = act('dream_harvest_save', {'use_ward': 1}, B)
    assert state['actors'][B]['source_states'][P]['ward_used'] == 1
    assert state['actors'][B]['resources'][QI] == 26
    assert 'harvest_save' not in state['actors'][B]['source_states'][P]
    assert cold().journey_verify(jid)['status'] == 'PASS'


def test_native_external_restoration_is_source_cl_gated_and_cannot_reuse_an_old_event(tmp_path, monkeypatch):
    cold, jid, act, fact = game(tmp_path, monkeypatch)
    payload = harvest_inputs(fact)
    act('dream_harvest', payload)
    fact(B, 'dream_restoration', 'lower', {'source_rule': 'Explicit external dream-restoration authority', 'source_cl': 17}, world=True)
    before = cold().journey_state(jid)
    with pytest.raises(ValueError):
        act('dream_receive_restoration', {'scope': 'lower'}, B)
    assert cold().journey_state(jid) == before
    fact(B, 'dream_restoration', 'equal', {'source_rule': 'Explicit external dream-restoration authority', 'source_cl': 18}, world=True)
    state = act('dream_receive_restoration', {'scope': 'equal'}, B)
    assert state['actors'][B]['source_states'][P]['drained'] == {}
    assert state['actors'][B]['resources'][QI] == 26  # admission grants no points
    act('dream_harvest', payload)
    with pytest.raises(ValueError, match='committed native'):
        act('dream_receive_restoration', {'scope': 'equal'}, B)
    assert cold().journey_verify(jid)['status'] == 'PASS'


def test_native_wake_by_insight_uses_real_intelligence_and_frees_another_on_margin_five(tmp_path, monkeypatch):
    cold, jid, act, fact = game(tmp_path, monkeypatch, extra=True, clever=True, dc=30)
    service, table, mid = fight(cold, jid, tmp_path)
    settle(table, mid, candidate(service, mid, 'Shared Dream Concordance').candidate_id,
        choices={'choice:needle.dream_qi.concord_targets': [B, C], 'choice:needle.dream_qi.link_consent': 'resist'})
    turn(table, mid, B)
    assert all(any(c.condition_id == 'condition:typed.dream_qi_bound' for c in loaded(cold, mid).state.actors[aid].conditions.values()) for aid in (B, C))
    settle(table, mid, candidate(service, mid, 'Wake by Insight').candidate_id,
        choices={'choice:needle.dream_qi.wake_check': 'int', 'choice:needle.dream_qi.wake_other': C})
    engine = loaded(cold, mid)
    assert all(not any(c.condition_id in ('condition:typed.dream_qi_bound', 'condition:typed.restrained')
                       for c in engine.state.actors[aid].conditions.values()) for aid in (B, C))


@pytest.mark.parametrize('target_cl,after_first,after_second', [(18, 2, 3), (15, 1, 2), (13, 1, 2), (12, 1, 1)])
def test_native_bound_repeat_frequency_uses_recipient_cl(tmp_path, monkeypatch, target_cl, after_first, after_second):
    cold, jid, act, fact = game(tmp_path, monkeypatch, clever=True, dc=30, target_cl=target_cl)
    service, table, mid = fight(cold, jid, tmp_path)
    settle(table, mid, candidate(service, mid, 'Shared Dream Concordance').candidate_id,
        choices={'choice:needle.dream_qi.concord_targets': B, 'choice:needle.dream_qi.link_consent': 'resist'})
    turn(table, mid, B)
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
    engine = loaded(cold, mid)
    assert len([e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == B]) == after_first
    turn(table, mid, B)
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
    engine = loaded(cold, mid)
    assert len([e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == B]) == after_second


def test_branch_does_not_gate_an_unrelated_records_min_cl():
    """Dream Qi's own records change; another Subpath's review stays as reviewed.

    The published authority is generated by tools/build_typed_mechanics_authority.py.
    A Dream Qi edit that also raises Sound Cultivator's Healing Melody gate would
    silently change gating for every character holding that feature while the
    record still claims its old review: the reviewed row keeps its stamp, so the
    source row is checked as well as the generated record.
    """
    source = json.loads((ROOT / 'authority/typed_mechanics/reviewed_final.d/zz_a2_qi_subpaths_5.json').read_text())
    reviewed = source['mechanics']['tianxia.subpath.qi.sound_cultivator.feature.healing_melody']
    assert reviewed.get('min_cl') is None
    assert reviewed.get('reviewed_by') == 'Codex A2GQISUB5 2026-10-11'
    authority = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())
    melody = authority['mechanics']['tianxia.subpath.qi.sound_cultivator.feature.healing_melody']
    assert melody.get('min_cl') is None
    assert melody.get('typing_status') == 'reviewed_final'
    # The Dream Qi rows are still the reviewed ones (numbers, not prose: the public
    # mirror substitutes printed text, so a prose assertion would not be public-safe).
    rest = authority['mechanics'][P + '.feature.dreamer_s_rest']
    assert rest.get('typing_status') == 'reviewed_final'
