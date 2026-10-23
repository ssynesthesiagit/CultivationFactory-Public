"""Whole Borrowed Breath row through real compilation, table commits and journeys.

Synthetic setup actions produce injuries/other HP pools only; all Life ability
acquisition, effects, choices, payment, clocks and replay are production code.
"""
import hashlib
import json
import zipfile
from fractions import Fraction

import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext.life_borrowed_breath import SOURCE, POOL
from tests.cw2_service_support import add_action, seal
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn

QI = 'resource:core.qi'
ESOTERIC = 'tianxia.talent.life.esoteric_vitality'


def setup(bundles):
    for bundle in bundles:
        for amount in (1, 3, 10, 30, 60):
            add_action(bundle, f'Injury {amount}', [{'type': 'damage', 'flat': amount,
                'damage_types': ['force'], 'applies_to': 'target'}])
        add_action(bundle, 'Other protection', [{'type': 'temp_hp', 'flat': 9, 'applies_to': 'target'}])


def offered(engine, name, target):
    return [c for c in engine.legal_candidates() if c.display_name == name and c.target_ids == (target,)]


def select(combat, mid, prefix, target):
    return next(c for c in combat._load_session(mid).engine.legal_candidates()
                if c.display_name.startswith(prefix) and c.target_ids == (target,))


def marker(engine, aid):
    return next(c for c in engine.state.actors[aid].conditions.values() if c.condition_id == POOL)


def test_source_pin_and_automatic_sphere_acquisition(tmp_path):
    text = json.loads((ROOT/'authority/typed_mechanics/rules_text.json').read_text())[SOURCE]
    assert hashlib.sha256(text.encode()).hexdigest() == '424979133f44cee17c90f8885fdcae3fbfb704dca2a4cd1f8f6414b223cb270b'
    from combat.factory_compiler import compile_character
    pids = [f'bb000000-0000-4000-8000-{i:012d}' for i in (1, 2, 3)]
    ids = [f'actor:factory.{pid}' for pid in pids]
    owner, patient, foe = ids
    for aid in ids:
        document = sheet([])
        document['identity']['path_ids'] = ['tianxia.path.qi_cultivation']
        folder = tmp_path/'portable_characters'/aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    from canonical_catalog.service import CanonicalCatalogAuthorityService
    table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    table.add_advancement(pids[0], 'sphere', 'tianxia.sphere.life')
    # This cold read applies the real persisted table learning operation; the
    # combat compiler consumes the automatic component receipts it produces.
    combat = CombatService(ROOT, tmp_path)
    acquired = combat._factory_owner_sheet(pids[0])
    fields = acquired['spheres_and_talents']
    assert SOURCE in fields['automatic_sphere_component_record_ids']
    assert fields['learned_talent_record_ids'] == []
    bundles = [compile_character(combat._factory_owner_sheet(aid.removeprefix('actor:factory.')), actor_id=aid)
               for aid in ids]
    assert not any('Borrowed Breath' in action['display_name'] or 'Lasting Breath' in action['display_name']
                   for action in bundles[1]['action_catalog'])
    setup(bundles)
    mid = combat._finish_factory_match(bundles, ids,
        {owner: 'team:a', patient: 'team:a', foe: 'team:b'},
        {owner: {'x': 3, 'y': 6}, patient: {'x': 4, 'y': 6}, foe: {'x': 6, 'y': 6}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        [owner, patient], [foe], control_modes={aid: 'MANUAL' for aid in ids},
        match_seed='BORROWED-BREATH-ACQUISITION', display_name='Borrowed Breath acquisition',
        maximum_rounds=15)['match_id']
    table = TabletopService(combat, tmp_path)
    turn(table, mid, owner)
    settle(table, mid, candidate(combat, mid, 'Injury 10', target=patient).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Borrowed Breath', target=patient).candidate_id)
    assert reload(tmp_path, mid).state.actors[patient].temporary_hp == 4


@pytest.mark.parametrize('missing,pb', [(1, 4), (10, 2), (10, 6)])
def test_base_injury_cap_proficiency_action_zero_cost_and_cold_receipt(tmp_path, missing, pb):
    combat, table, mid = fixture(tmp_path, [SOURCE], owner_pb=pb, bundle_transform=setup)
    assert not offered(reload(tmp_path, mid), 'Borrowed Breath', ALLY)
    settle(table, mid, candidate(combat, mid, f'Injury {missing}', target=ALLY).candidate_id)
    before = reload(tmp_path, mid)
    cast = candidate(combat, mid, 'Borrowed Breath', target=ALLY)
    assert before.action_catalog[cast.source_definition_id].range_ft == 5
    settle(table, mid, cast.candidate_id)
    cold = reload(tmp_path, mid)
    assert cold.state.actors[ALLY].current_hp == 60-missing
    assert cold.state.actors[ALLY].temporary_hp == min(pb, missing)
    assert cold.state.actors[OWNER].resources[QI] == before.state.actors[OWNER].resources[QI]
    assert not cold.state.actors[OWNER].action_available
    receipt = marker(cold, ALLY)
    assert receipt.source_actor_id == OWNER and receipt.data['lasting'] == 0
    assert receipt.data['end_clock'].startswith('START_OF_SLOT_AT:')
    assert all(type(v) in (int, str) for v in receipt.data.values())
    assert not getattr(cold, '_ext_failures_logged', set())


def test_zero_hp_stable_before_temp_hp_and_still_unconscious(tmp_path):
    combat, table, mid = fixture(tmp_path, [SOURCE], bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, 'Injury 60', target=ALLY).candidate_id)
    before = reload(tmp_path, mid)
    assert before.state.actors[ALLY].life_state == 'DYING'
    settle(table, mid, candidate(combat, mid, 'Borrowed Breath', target=ALLY).candidate_id)
    cold = reload(tmp_path, mid)
    patient = cold.state.actors[ALLY]
    assert patient.current_hp == 0 and patient.temporary_hp == 4 and patient.life_state == 'STABLE'
    assert any('unconscious' in c.condition_id for c in patient.conditions.values())
    events = cold.events[len(before.events):]
    stable = next(i for i, e in enumerate(events) if e.event_type == 'LIFE_STATE_CHANGED')
    grant = next(i for i, e in enumerate(events) if e.event_type == 'TEMP_HP_GRANTED')
    assert stable < grant


@pytest.mark.parametrize('kind,esoteric', [('Undead', False), ('Construct', False), ('Undead', True), ('Construct', True)])
def test_living_domain_and_existing_talent_exception(tmp_path, kind, esoteric):
    def prepare(bundles):
        setup(bundles)
        bundles[1]['actor_template']['creature_types'] = [kind]
        seal(bundles[1])
    combat, table, mid = fixture(tmp_path, [SOURCE, *([ESOTERIC] if esoteric else [])], bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Injury 10', target=ALLY).candidate_id)
    assert bool(offered(reload(tmp_path, mid), 'Borrowed Breath', ALLY)) == esoteric
    if esoteric:
        settle(table, mid, candidate(combat, mid, 'Borrowed Breath', target=ALLY).candidate_id)
        assert reload(tmp_path, mid).state.actors[ALLY].temporary_hp == 4


def test_touch_and_opponent_recipient_do_not_change_ownership(tmp_path):
    combat, table, mid = fixture(tmp_path, [SOURCE], bundle_transform=setup,
        ally_position={'x': 10, 'y': 10}, foe_position={'x': 4, 'y': 6})
    for aid in (ALLY, FOE):
        settle(table, mid, candidate(combat, mid, 'Injury 10', target=aid).candidate_id)
    assert not offered(reload(tmp_path, mid), 'Borrowed Breath', ALLY)
    settle(table, mid, candidate(combat, mid, 'Borrowed Breath', target=FOE).candidate_id)
    cold = reload(tmp_path, mid)
    assert cold.state.actors[FOE].temporary_hp == 4
    assert marker(cold, FOE).source_actor_id == OWNER
    turn(table, mid, FOE)
    assert not any('Lasting Breath' in c.display_name for c in reload(tmp_path, mid).legal_candidates())


@pytest.mark.parametrize('at_cast', [False, True])
def test_lasting_cost_choice_and_no_second_action(tmp_path, at_cast):
    combat, table, mid = fixture(tmp_path, [SOURCE], bundle_transform=setup, named=True)
    settle(table, mid, candidate(combat, mid, 'Injury 10', target=ALLY).candidate_id)
    before = reload(tmp_path, mid).state.actors[OWNER].resources[QI]
    cast = select(combat, mid, 'Borrowed Breath + Lasting Breath', ALLY) if at_cast else candidate(combat, mid, 'Borrowed Breath', target=ALLY)
    settle(table, mid, cast.candidate_id)
    if not at_cast:
        assert not reload(tmp_path, mid).state.actors[OWNER].action_available
        prompts = settle(table, mid, select(combat, mid, 'Lasting Breath: extend', OWNER).candidate_id,
                         {'choice:needle.lasting_breath': ALLY})
        prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.lasting_breath')
        assert prompt['context']['reactor_id'] == OWNER
        assert 'Tobin' in str(prompt) and 'Lasting Breath' in str(prompt) and 'Long Rest' in str(prompt)
    cold = reload(tmp_path, mid)
    assert cold.state.actors[OWNER].resources[QI] == before-1
    assert cold.state.actors[ALLY].temporary_hp == 4 and marker(cold, ALLY).data['lasting'] == 1
    assert not any(c.display_name.startswith('Lasting Breath: extend') for c in cold.legal_candidates())


@pytest.mark.parametrize('mode', ['MANUAL', 'LOCAL_AUTO'])
def test_last_breath_choice_follows_caster_control_on_auto_step(tmp_path, mode):
    from combat.gate4_adapters import ManualControllerAdapter
    combat, table, mid = fixture(tmp_path, [SOURCE], bundle_transform=setup, named=True)
    settle(table, mid, candidate(combat, mid, 'Injury 10', target=ALLY).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Borrowed Breath', target=ALLY).candidate_id)
    cast = select(combat, mid, 'Lasting Breath: extend', OWNER)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=mode)
    real = combat.controller
    combat.controller = ManualControllerAdapter(lambda context: (cast.candidate_id, ()),
        reaction_chooser=lambda context: real.choose_reaction(context).decision)
    prompts = settle(table, mid, cast.candidate_id,
                     {'choice:needle.lasting_breath': ALLY}, auto=(mode == 'LOCAL_AUTO'))
    choices = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.lasting_breath']
    assert bool(choices) == (mode == 'MANUAL')
    assert all(p['context']['reactor_id'] == OWNER for p in choices)
    assert marker(reload(tmp_path, mid), ALLY).data['lasting'] == 1


def test_cannot_spend_missing_cp_or_extend_another_sources_larger_pool(tmp_path):
    def prepare(bundles):
        setup(bundles)
        for resource in bundles[0]['actor_template']['resources']:
            if resource['resource_id'] == QI:
                resource['initial'] = 0
        seal(bundles[0])
    combat, table, mid = fixture(tmp_path, [SOURCE], bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Injury 10', target=ALLY).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Other protection', target=ALLY).candidate_id)
    assert not any('Lasting Breath' in c.display_name for c in reload(tmp_path, mid).legal_candidates())
    settle(table, mid, candidate(combat, mid, 'Borrowed Breath', target=ALLY).candidate_id)
    cold = reload(tmp_path, mid)
    assert cold.state.actors[ALLY].temporary_hp == 9
    assert not any(c.condition_id == POOL for c in cold.state.actors[ALLY].conditions.values())


def journey_game(tmp_path, monkeypatch):
    import combat.factory_compiler as compiler
    original = compiler.compile_character
    def compile_with_scene_injuries(*args, **kwargs):
        bundle = original(*args, **kwargs)
        setup([bundle])
        return bundle
    monkeypatch.setattr(compiler, 'compile_character', compile_with_scene_injuries)
    monkeypatch.setattr(CombatService, '_factory_owner_sheet', lambda self, pid:
        sheet([SOURCE] if pid == 'breath-owner' else [], cl=15, name=pid))
    arena = CombatService(ROOT, tmp_path).factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self: {'scene': arena})
    a, b = 'actor:factory.breath-owner', 'actor:factory.breath-patient'
    cold = lambda: CombatService(ROOT, tmp_path)
    state = cold().create_journey(project_ids=['breath-owner', 'breath-patient'], arena_id='scene',
        positions={a: {'x': 3, 'y': 6}, b: {'x': 4, 'y': 6}}, base_paces={a: 5, b: 5},
        control_modes={a: 'MANUAL', b: 'MANUAL'})
    jid = state['journey_id']
    def start():
        state = cold().journey_state(jid)
        return cold().journey_start_combat(jid, state['revision'], {a: 'team:a', b: 'team:b'}, maximum_rounds=3)['match_id']
    def act(kind, payload=None, aid=a):
        state = cold().journey_state(jid)
        result = cold().journey_act(jid, state['revision'], aid, kind, payload)
        assert cold().journey_state(jid) == result
        return result
    def finish(mid):
        table = TabletopService(cold(), tmp_path)
        for _ in range(20):
            if cold()._load_session(mid).engine.state.terminal_result is not None:
                state = cold().journey_state(jid)
                return cold().journey_resume(jid, state['revision'])
            menu = table.state(mid)['menu']
            settle(table, mid, menu['end_turn'])
        pytest.fail('Round-capped combat did not finish')
    return cold, jid, start, act, finish, a, b


@pytest.mark.parametrize('lasting', ['none', 'reentry', 'cast', 'after', 'replacement', 'depleted'])
def test_native_journey_clock_rest_source_replacement_and_reentry(tmp_path, monkeypatch, lasting):
    cold, jid, start, act, finish, a, b = journey_game(tmp_path, monkeypatch)
    mid = start()
    combat = cold()
    table = TabletopService(combat, tmp_path)
    turn(table, mid, a)
    settle(table, mid, candidate(combat, mid, 'Injury 30', target=b).candidate_id)
    cast = select(combat, mid, 'Borrowed Breath + Lasting Breath', b) if lasting == 'cast' else candidate(combat, mid, 'Borrowed Breath', target=b)
    settle(table, mid, cast.candidate_id)
    if lasting == 'after':
        settle(table, mid, select(combat, mid, 'Lasting Breath: extend', a).candidate_id,
               {'choice:needle.lasting_breath': b})
    elif lasting == 'replacement':
        settle(table, mid, candidate(combat, mid, 'Other protection', target=b).candidate_id)
    elif lasting == 'depleted':
        settle(table, mid, candidate(combat, mid, 'Injury 10', target=b).candidate_id)
    state = finish(mid)
    snapshot = state['actors'][b]['encounter_snapshot']
    if lasting in ('none', 'reentry'):
        if lasting == 'reentry':
            second = start()
            engine = reload(tmp_path, second)
            assert engine.state.actors[b].temporary_hp == 4
            assert marker(engine, b).data['lasting'] == 0
            state = finish(second)
            snapshot = state['actors'][b]['encounter_snapshot']
        data = next(json.loads(c)['data'] for c in snapshot['conditions'].values()
                    if json.loads(c)['condition_id'] == POOL)
        remaining = Fraction(data['remaining_num'], data['remaining_den'])
        assert 3500 < remaining < 3600
        act('wait', {'seconds': int(remaining)-1})
        assert cold().journey_state(jid)['actors'][b]['encounter_snapshot']['temporary_hp'] == 4
        act('wait', {'seconds': 2})
        assert cold().journey_state(jid)['actors'][b]['encounter_snapshot']['temporary_hp'] == 0
    elif lasting in ('replacement', 'depleted'):
        act('wait', {'seconds': 3601})
        assert cold().journey_state(jid)['actors'][b]['encounter_snapshot']['temporary_hp'] == (9 if lasting == 'replacement' else 0)
        assert not any(json.loads(c)['condition_id'] == POOL for c in snapshot['conditions'].values())
    else:
        act('wait', {'seconds': 3601})
        act('long_rest', aid=b)
        assert cold().journey_state(jid)['actors'][b]['encounter_snapshot']['temporary_hp'] == 4
        second = start()
        engine = reload(tmp_path, second)
        assert engine.state.actors[b].temporary_hp == 4 and marker(engine, b).data['lasting'] == 1
        finish(second)
        act('long_rest', aid=a)
        assert cold().journey_state(jid)['actors'][b]['encounter_snapshot']['temporary_hp'] == 0
