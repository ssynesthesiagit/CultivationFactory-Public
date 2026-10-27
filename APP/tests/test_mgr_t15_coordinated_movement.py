"""Coordinated Movement through native learning, mapped actions and table replay.

The installed starting characters are deterministic, source-backed fixtures;
Athletics and Body Beyond Distance are learned through table advancement. No
owned passive, success receipt or initial Focus deficit is installed by a test.
"""
import copy
import json
import zipfile

import pytest

from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.auto8f1_table_support import candidate_id, reload_identical

SOURCE = 'ATHLETICS_BASE_COORDINATED_MOVEMENT'
TRAVEL = 'TAL_ATHLETICS_BODY_BEYOND_DISTANCE'
MERIDIAN = 'TAL_ATHLETICS_MERIDIAN_THREADING_DASH'
FOCUS = 'resource:core.martial_focus'
P, O = 'a1150031', 'a1150032'
A, B = FACTORY_ACTOR_PREFIX + P, FACTORY_ACTOR_PREFIX + O
BODY = 'tianxia.path.body_refining'
STOMP = 'tianxia.path.body_refining.feature.stomping_step'
ARENA = 'battlefield:map.coordinated-movement-scene'

# Explicit compiler inputs for the public export's static dependency closure.
INPUTS = ('combat/rules/feature_blocks.d/bodyb.json',
          'combat/rules/feature_blocks.d/auto8-athletics.json',
          'combat/rules/feature_blocks.d/mgr-t16-athletics-travel.json')


def table_for(combat, tmp_path):
    """A table with the real catalog the advancement APIs require."""
    table = TabletopService(combat, tmp_path)
    table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    return table


def scene(tmp_path, terrain=None):
    """Public synthetic battlefield built through the real owner map store.

    Earlier rounds used the retired owner arena battlefield:factory_pillar_arena,
    which new-fight creation no longer lists (it was a private fixture and the
    whole file failed at setup on public CI). The scene below is ordinary
    editor-map data saved through TabletopMapStore, so it needs no owner files.
    """
    maps = CombatService(ROOT, tmp_path).tabletop_maps
    maps.save({'display_name': 'Coordinated Movement scene', 'width_squares': 20,
               'height_squares': 12, 'terrain': list(terrain or [])})
    return ARENA


def setup(tmp_path, *, owner=True, mode='MANUAL', meridian=False, companion_traveller=False,
          positions=None, terrain=None):
    scene(tmp_path, terrain)
    for pid in (P, O):
        doc = sheet([STOMP], cl=15, name='Runner' if pid == P else 'Observer')
        doc['identity']['path_ids'] = [BODY]
        doc['path_and_subpath'] = {'path_record_id': BODY, 'path_record_ids': [BODY],
                                  'path_feature_record_ids': [STOMP]}
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    table = table_for(combat, tmp_path)
    table.add_advancement(P, 'sphere', 'tianxia.sphere.athletics')
    table.add_advancement(P, 'talent', TRAVEL)
    if companion_traveller:
        # The carried passenger owns the same printed travel talent, so its
        # own one-hour effect is active while it rides.
        table.add_advancement(O, 'sphere', 'tianxia.sphere.athletics')
        table.add_advancement(O, 'talent', TRAVEL)
    if meridian:
        table.add_advancement(P, 'talent', MERIDIAN)
    if not owner:
        # Remove the Sphere through the real durable learning API, after the
        # talent is learned. Its invalid dependent talent is not used below.
        table.remove_advancement(P, 'sphere', 'tianxia.sphere.athletics')
    cold = lambda: CombatService(ROOT, tmp_path)
    doc = cold()._factory_owner_sheet(P)
    assert (SOURCE in doc['spheres_and_talents']['automatic_sphere_component_record_ids']) == owner
    state = combat.create_journey(
        project_ids=[P, O], arena_id=ARENA,
        positions=positions or {A: {'x': 3, 'y': 6}, B: {'x': 10, 'y': 6}},
        base_paces={A: 3000, B: 3000}, control_modes={A: mode})
    jid = state['journey_id']

    def act(kind, payload=None, aid=A):
        service = cold()
        before = service.journey_state(jid)
        after = service.journey_act(jid, before['revision'], aid, kind, payload)
        assert cold().journey_state(jid) == after
        return after

    return cold, jid, act


def spend(cold, jid, act):
    state = act('activate', {'source': TRAVEL})
    assert state['actors'][A]['resources'][FOCUS] == 0
    # Its own printed clock ends the travel effect, without recovering Focus.
    state = act('wait', {'seconds': 3600})
    assert not state['actors'][A]['travel_effects']
    assert cold().journey_state(jid)['actors'][A]['resources'][FOCUS] == 0
    return state


def declare(act, source, path=()):
    return act('map_action_declare', {'source': source, 'economy': 'ACTION', 'path': list(path)})


def complete(act, state):
    return act('map_action_complete', {'id': state['actors'][A]['map_action']['id']})


@pytest.mark.parametrize('source', ['system:combat.dash', 'system:combat.disengage'])
@pytest.mark.parametrize('mode', ['MANUAL', 'LOCAL_AUTO'])
def test_native_map_action_restores_one_focus_only_on_completion(tmp_path, source, mode):
    cold, jid, act = setup(tmp_path, mode=mode)
    start = spend(cold, jid, act)
    pending = declare(act, source, [{'x': 4, 'y': 6}])
    assert pending['seconds'] == start['seconds']
    assert pending['actors'][A]['resources'][FOCUS] == 0
    assert pending['actors'][A]['position'] == start['actors'][A]['position']
    before = copy.deepcopy(cold().journey_state(jid))
    for _ in range(2):
        menu = cold().journey_menu(jid, A)
        assert any(o['kind'] == 'map_action_complete' for o in menu['options'])
    assert cold().journey_state(jid) == before
    if mode == 'LOCAL_AUTO':
        offered = next(o for o in menu['options'] if o['kind'] == 'map_action_complete')
        after = cold().journey_auto_step(jid, pending['revision'], A, offered['id'])
    else:
        after = complete(act, pending)
    reloaded = cold().journey_state(jid)
    assert reloaded == after
    assert after['seconds'] == start['seconds'] + 6
    assert after['actors'][A]['position'] == {'x': 4, 'y': 6}
    assert after['actors'][A]['resources'][FOCUS] == 1
    receipts = [e for e in after['events'] if e['kind'] == 'RESOURCE_GAINED']
    assert len(receipts) == 1
    receipt = receipts[0]
    action = next(e for e in after['events'] if e['kind'] == 'MAP_ACTION_COMPLETED')
    assert receipt['source'] == 'passive:' + SOURCE
    assert receipt['action_id'] == action['id'] and receipt['action_source'] == source
    assert (receipt['before'], receipt['gained'], receipt['after']) == (0, 1, 1)
    assert action['economy'] == 'ACTION' and action['movement_cost_ft'] == 5
    with pytest.raises(ValueError):
        complete(act, pending)  # the receipt cannot be claimed a second time
    assert cold().journey_state(jid) == after
    # A second real Action takes another six seconds, but held Focus is capped.
    again = complete(act, declare(act, source))
    assert again['seconds'] == after['seconds'] + 6
    assert [e for e in again['events'] if e['kind'] == 'RESOURCE_GAINED'] == receipts


def test_receipt_reports_charged_movement_not_geometric_distance(tmp_path):
    """The completion receipt names what it holds: a difficult square costs
    10 ft of movement for a 5 ft step, so the field is movement_cost_ft."""
    cold, jid, act = setup(tmp_path, terrain=[{'type': 'DIFFICULT', 'cells': [[4, 6]]}])
    spend(cold, jid, act)
    after = complete(act, declare(act, 'system:combat.dash', [{'x': 4, 'y': 6}]))
    action = next(e for e in after['events'] if e['kind'] == 'MAP_ACTION_COMPLETED')
    assert action['position'] == {'x': 4, 'y': 6}
    assert action['movement_cost_ft'] == 10  # charged cost, not the 5 ft step
    assert 'distance_ft' not in action
    assert after['actors'][A]['resources'][FOCUS] == 1


@pytest.mark.parametrize('source', ['system:combat.dash', 'system:combat.disengage'])
def test_cancellation_bonus_declaration_and_invalid_route_never_gain(tmp_path, source):
    cold, jid, act = setup(tmp_path)
    before = spend(cold, jid, act)
    with pytest.raises(ValueError):
        act('map_action_declare', {'source': source, 'economy': 'BONUS_ACTION', 'path': []})
    assert cold().journey_state(jid) == before
    pending = declare(act, source)
    after = act('map_action_cancel', {'id': pending['actors'][A]['map_action']['id']})
    assert after['seconds'] == before['seconds']
    assert after['actors'][A]['resources'][FOCUS] == 0
    assert not [e for e in after['events'] if e['kind'] in ('RESOURCE_GAINED', 'MAP_ACTION_COMPLETED')]
    with pytest.raises(ValueError):
        complete(act, pending)
    with pytest.raises(ValueError):
        declare(act, source, [{'x': 8, 'y': 6}])  # nonadjacent route, not a success flag
    assert cold().journey_state(jid) == after


@pytest.mark.parametrize('source', ['system:combat.dash', 'system:combat.disengage'])
def test_native_nonowner_and_held_focus_controls(tmp_path, source):
    cold, jid, act = setup(tmp_path)
    # Both the owner at full Focus and the genuinely nonowning second character
    # complete real Actions. Neither gains a resource or an owned receipt.
    for aid in (A, B):
        state = act('map_action_declare', {'source': source, 'economy': 'ACTION', 'path': []}, aid)
        act('map_action_complete', {'id': state['actors'][aid]['map_action']['id']}, aid)
    state = cold().journey_state(jid)
    assert state['actors'][A]['resources'][FOCUS] > 0
    assert not [e for e in state['events'] if e['kind'] == 'RESOURCE_GAINED']


@pytest.mark.parametrize('source', ['system:combat.dash', 'system:combat.disengage'])
def test_missing_focus_nonowner_after_native_unlearning_cannot_regain(tmp_path, source):
    cold, jid, act = setup(tmp_path)
    spend(cold, jid, act)
    act('finish')
    combat = cold()
    table_for(combat, tmp_path).remove_advancement(P, 'sphere', 'tianxia.sphere.athletics')
    doc = cold()._factory_owner_sheet(P)
    assert SOURCE not in doc['spheres_and_talents']['automatic_sphere_component_record_ids']
    state = cold().create_journey(
        project_ids=[P, O], arena_id=ARENA,
        positions={A: {'x': 3, 'y': 6}, B: {'x': 10, 'y': 6}},
        base_paces={A: 3000, B: 3000})
    jid = state['journey_id']
    assert state['actors'][A]['resources'][FOCUS] == 0
    state = cold().journey_act(jid, state['revision'], A, 'map_action_declare',
                               {'source': source, 'economy': 'ACTION', 'path': []})
    state = cold().journey_act(jid, state['revision'], A, 'map_action_complete',
                               {'id': state['actors'][A]['map_action']['id']})
    assert cold().journey_state(jid) == state
    assert state['actors'][A]['resources'][FOCUS] == 0
    assert not [e for e in state['events'] if e['kind'] == 'RESOURCE_GAINED']


def enter_combat(cold, jid):
    state = cold().journey_state(jid)
    return cold().journey_start_combat(jid, state['revision'], {A: 'team:a', B: 'team:b'})['match_id']


def take(cold, mid, *, label=None, option=None):
    for _ in range(10):
        service = cold()
        table = TabletopService(service, service.userdata_root)
        menu = table.state(mid)['menu']
        if menu['actor_id'] == A:
            break
        result = table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], 0, [])
        assert result['status'] == 'COMMITTED', result
    else:
        raise AssertionError('Runner never received a turn')
    cid = candidate_id(menu, label, exact=True)
    answers = []
    for _ in range(8):
        result = table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, answers)
        if result['status'] == 'COMMITTED':
            return result
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        answer = {**prompt['context'], 'selection': 'DECLINE', 'option_ids': []}
        choice = prompt.get('choice')
        if choice:
            ids = [str(o['id']) for o in choice['options']]
            answer.update(selection='USE', option_ids=[option if option in ids else ids[0]])
        answers.append(answer)
    raise AssertionError('Action did not settle')


@pytest.mark.parametrize('label', ['Dash', 'Disengage'])
def test_native_combat_gain_and_map_resource_replay(tmp_path, label):
    cold, jid, act = setup(tmp_path)
    spend(cold, jid, act)
    mid = enter_combat(cold, jid)
    assert cold()._load_session(mid).engine.state.actors[A].resources[FOCUS] == 0
    take(cold, mid, label=label)
    engine = cold()._load_session(mid).engine
    assert engine.state.actors[A].resources[FOCUS] == 1
    receipts = [e for e in engine.events if e.event_type == 'RESOURCE_GAINED'
                and e.source_definition_id == 'passive:' + SOURCE]
    assert len(receipts) == 1 and receipts[0].payload['gained'] == 1
    reload_identical(cold(), mid, cold().userdata_root)


@pytest.mark.parametrize('source', ['system:combat.dash', 'system:combat.disengage'])
def test_map_gain_is_real_encounter_genesis_and_replays(tmp_path, source):
    cold, jid, act = setup(tmp_path)
    spend(cold, jid, act)
    complete(act, declare(act, source))
    mid = enter_combat(cold, jid)
    assert cold()._load_session(mid).engine.state.actors[A].resources[FOCUS] == 1
    reload_identical(cold(), mid, cold().userdata_root)


@pytest.mark.parametrize('option', ['dash', 'disengage'])
def test_native_bonus_stomping_step_does_not_restore_focus(tmp_path, option):
    cold, jid, act = setup(tmp_path)
    spend(cold, jid, act)
    mid = enter_combat(cold, jid)
    take(cold, mid, label='Stomping Step', option=option)
    engine = cold()._load_session(mid).engine
    assert engine.state.actors[A].resources[FOCUS] == 0
    if option == 'dash':
        assert any(e.event_type == 'MOVEMENT_GRANTED' and e.actor_id == A for e in engine.events)
    else:
        assert engine.state.actors[A].turn_flags.get('disengaged')
    assert not [e for e in engine.events if e.event_type == 'RESOURCE_GAINED'
                and e.source_definition_id == 'passive:' + SOURCE]
    reload_identical(cold(), mid, cold().userdata_root)


def test_explicit_auto_step_option_is_not_overridden_by_regain_policy(tmp_path):
    """An explicit legal menu id takes precedence over automatic regain policy."""
    cold, jid, act = setup(tmp_path, mode='LOCAL_AUTO')
    spend(cold, jid, act)
    state = cold().journey_state(jid)
    menu = cold().journey_menu(jid, A)
    move = next(row for row in menu['options'] if row['kind'] == 'move')
    assert move['payload']['path']
    after = cold().journey_auto_step(jid, menu['revision'], A, move['id'])
    assert after['actors'][A]['position'] != state['actors'][A]['position']
    assert not any(event['kind'] == 'MAP_ACTION_COMPLETED' for event in after['events'])
    assert after['actors'][A]['resources'][FOCUS] == 0


@pytest.mark.parametrize('source', ['system:combat.dash', 'system:combat.disengage'])
def test_default_auto_step_settles_a_declared_action_without_external_option(tmp_path, source):
    """Finding 1: the default automatic caller settles a pending mapped Action."""
    cold, jid, act = setup(tmp_path, mode='LOCAL_AUTO')
    start = spend(cold, jid, act)
    pending = declare(act, source, [{'x': 4, 'y': 6}])
    after = cold().journey_auto_step(jid, pending['revision'], A)
    assert cold().journey_state(jid) == after
    assert after['seconds'] == start['seconds'] + 6
    assert after['actors'][A]['position'] == {'x': 4, 'y': 6}
    assert after['actors'][A]['resources'][FOCUS] == 1
    receipts = [e for e in after['events'] if e['kind'] == 'RESOURCE_GAINED']
    assert len(receipts) == 1 and receipts[0]['action_source'] == source


def test_default_auto_step_chooses_a_regain_action_and_never_loops(tmp_path):
    """Finding 1: an automatic Athletics owner with missing Focus chooses and
    completes a regain Action by itself, then returns to ordinary travel."""
    cold, jid, act = setup(tmp_path, mode='LOCAL_AUTO')
    start = spend(cold, jid, act)
    assert start['actors'][A]['resources'][FOCUS] == 0
    declared = cold().journey_auto_step(jid, start['revision'], A)
    action = declared['actors'][A]['map_action']
    assert action['economy'] == 'ACTION'
    assert action['source'] in ('system:combat.dash', 'system:combat.disengage')
    assert declared['seconds'] == start['seconds']
    assert declared['actors'][A]['resources'][FOCUS] == 0  # a declaration gains nothing
    done = cold().journey_auto_step(jid, declared['revision'], A)
    assert done['seconds'] == declared['seconds'] + 6
    assert done['actors'][A]['resources'][FOCUS] == 1
    assert 'map_action' not in done['actors'][A]
    assert len([e for e in done['events'] if e['kind'] == 'RESOURCE_GAINED']) == 1
    # With Focus restored the automatic seat keeps ordinary travel: no further
    # declaration and no second receipt, so mapped Actions never loop.
    later = cold().journey_auto_step(jid, done['revision'], A)
    later2 = cold().journey_auto_step(jid, later['revision'], A)
    for state in (later, later2):
        assert 'map_action' not in state['actors'][A]
        assert len([e for e in state['events'] if e['kind'] == 'RESOURCE_GAINED']) == 1
    assert cold().journey_state(jid) == later2


def test_default_auto_step_nonowner_keeps_ordinary_travel(tmp_path):
    """Finding 1 control: a genuine nonowner with missing Focus never declares
    a mapped Action through the default automatic caller."""
    cold, jid, act = setup(tmp_path)
    spend(cold, jid, act)
    act('finish')
    combat = cold()
    table_for(combat, tmp_path).remove_advancement(P, 'sphere', 'tianxia.sphere.athletics')
    state = cold().create_journey(
        project_ids=[P, O], arena_id=ARENA,
        positions={A: {'x': 3, 'y': 6}, B: {'x': 10, 'y': 6}},
        base_paces={A: 3000, B: 3000}, control_modes={A: 'LOCAL_AUTO'})
    jid = state['journey_id']
    assert state['actors'][A]['resources'][FOCUS] == 0
    after = cold().journey_auto_step(jid, state['revision'], A)
    later = cold().journey_auto_step(jid, after['revision'], A)
    for step in (after, later):
        assert 'map_action' not in step['actors'][A]
        assert not [e for e in step['events'] if e['kind'] in ('RESOURCE_GAINED', 'MAP_ACTION_COMPLETED')]
    assert cold().journey_state(jid) == later


def test_mapped_action_interval_moves_carried_traveller_clock(tmp_path):
    """Finding 2: a carried passenger's own one-hour travel effect must count a
    mapped Action's six-second interval as moving, exactly like ordinary
    movement; eleven mapped movements must not stop it for "more than one
    minute"."""
    cold, jid, act = setup(tmp_path, companion_traveller=True,
                           positions={A: {'x': 3, 'y': 6}, B: {'x': 4, 'y': 6}})
    state = act('activate', {'source': TRAVEL})
    state = act('activate', {'source': TRAVEL}, B)
    state = act('request_carry', {'target_id': B})
    state = act('carry_reply', {'accept': True}, B)
    assert state['actors'][B]['carried_by'] == A
    for step in range(11):
        path = [{'x': 4, 'y': 6}] if step % 2 == 0 else [{'x': 3, 'y': 6}]
        state = complete(act, declare(act, 'system:combat.dash', path))
    assert state['seconds'] == 66
    assert state['actors'][B]['position'] == state['actors'][A]['position']
    for rider in (A, B):
        effect = state['actors'][rider]['travel_effects'][TRAVEL]
        assert effect['stopped_seconds'] == 0
    assert not [e for e in state['events'] if e['kind'] == 'TRAVEL_EFFECT_ENDED']


def test_new_file_imports_no_private_test_modules():
    """Public-CI rule: this file must not import another test module (its helpers may be private)."""
    import ast
    from pathlib import Path
    tree = ast.parse(Path(__file__).read_text())
    private = [node.module for node in ast.walk(tree)
               if isinstance(node, ast.ImportFrom) and (node.module or '').startswith('tests.test_')]
    assert private == []
