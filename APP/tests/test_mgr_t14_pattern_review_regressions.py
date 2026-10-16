"""Service-level regressions for placement review findings 1–5.

No browser or model transport. All writes use isolated journey/table registries.
"""
from hashlib import sha256
import json

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext import pattern_construction as construction
from combat.ext.consumable_payloads import journey_available
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, FOE, settle


ITEM = 'item:alchemy.private_test_batch'
RECIPE_MARKER = 'source-private-orange-recipe'


def setup(tmp_path, mode='MANUAL', *, array_talents=()):
    kit = {'starting_kit': {'items': [
        {'item_id': 'tianxia.mortal.tool.thieves_tools', 'name': 'Thieves tools', 'quantity': 1},
        {'item_id': 'tianxia.mortal.gear.chalk', 'name': 'Chalk', 'quantity': 1},
        {'item_id': ITEM, 'name': 'Ordinary batch', 'quantity': 4}]}}
    doc = sheet(['TRAP_BASE_ACTIVATION_TRAP', 'FORMATIONS_BASE_SET_ARRAY', *array_talents], cl=5, kit=kit)
    doc['spheres_and_talents']['formation_patterns'] = ['locking_gate', 'killing_line']
    # Both party members own real construction sources, so elapsed-time tests
    # distinguish a shared tick from advancing just the device owner.
    foe = sheet(['FORMATIONS_BASE_SET_ARRAY'], cl=5, kit={'starting_kit': {'items': [
        {'item_id': 'tianxia.mortal.gear.chalk', 'name': 'Chalk', 'quantity': 1}]}})
    foe['spheres_and_talents']['formation_patterns'] = ['locking_gate']
    bundles = [compile_character(doc, actor_id=OWNER), compile_character(foe, actor_id=FOE)]
    arena = {'stable_id': 'review:patterns', 'width_squares': 14, 'height_squares': 12,
             'square_size_ft': 5, 'starting_positions': {}, 'terrain_regions': []}
    positions = {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 10, 'y': 6}}
    service = CombatService(ROOT, tmp_path)
    s = service.journeys.create(bundles, arena, positions, {OWNER: 30, FOE: 30}, {OWNER: mode, FOE: 'MANUAL'})
    return service, s['journey_id'], doc, foe


def act(service, jid, kind, payload, aid=OWNER):
    return service.journey_act(jid, service.journey_state(jid)['revision'], aid, kind, payload)


def admit(service, jid, kind, payload, aid=OWNER):
    return service.journey_admit(jid, service.journey_state(jid)['revision'], aid, kind, payload,
                                 gm=True, reason='Actual recorded source for this test scene')


def recipe(service, jid):
    return admit(service, jid, 'ordinary_consumable_definition', {
        'item_id': ITEM, 'nature': 'ordinary_consumable', 'source_text': RECIPE_MARKER,
        'source_sha256': sha256(RECIPE_MARKER.encode()).hexdigest(),
        'spec': {'name': RECIPE_MARKER, 'fragile': 1,
                 'effects': [{'type': 'physical_payload_fact', 'text': RECIPE_MARKER}]}})


def item_key(service, jid, item=ITEM):
    bundle = service.journeys.load(jid).state['actors'][OWNER]['bundle']
    return next(i['key'] for i in bundle['carrying']['items'] if i['item_id'] == item)


def trap(service, jid, **extra):
    return act(service, jid, 'construct_trap', {
        'form': 'activation', 'cells': [{'x': 4, 'y': 6}], 'aim': 'w',
        'payload_key': item_key(service, jid), 'payload_count': 1, 'origin': {'x': 4, 'y': 6}, **extra})


def end_scene(service, jid, *, drop=()):
    state = service.journey_state(jid)
    result = service.journey_start_scene(jid, state['revision'], {OWNER: 'party', FOE: 'party'})
    mid = result['match_id']
    table = TabletopService(service, service.userdata_root)
    while service._load_session(mid).engine.state.terminal_result is None:
        engine = service._load_session(mid).engine
        if engine.state.current_actor_id == OWNER:
            for name in drop:
                row = next(c for c in engine.legal_candidates() if c.display_name == 'Drop ' + name)
                settle(table, mid, row.candidate_id)
                engine = service._load_session(mid).engine
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    # Native persistence and mechanical replay, before returning to a cold service.
    assert CombatService(ROOT, service.userdata_root)._load_session(mid).mechanical.replay()['status'] == 'PASS'
    return mid


def test_foreign_history_and_mutation_returns_hide_entire_device_and_recipe(tmp_path):
    service, jid, _, _ = setup(tmp_path)
    recipe(service, jid)
    state = trap(service, jid)
    device = state['actors'][OWNER]['constructed_patterns'][0]
    assert RECIPE_MARKER in json.dumps(service.journey_state(jid, viewer_id=OWNER))
    foreign = service.journey_state(jid, viewer_id=FOE)
    assert RECIPE_MARKER not in json.dumps(foreign)
    assert device['id'] not in json.dumps(foreign)
    # Admission must apply the caller's projection, including existing history.
    admitted = admit(service, jid, 'construction_site', {'id': 'foe-site', 'name': 'Other bridge', 'kind': 'bridge',
        'cells': [{'x': x, 'y': 6} for x in (9, 10, 11)], 'known_to': [FOE]}, aid=FOE)
    assert RECIPE_MARKER not in json.dumps(admitted)
    assert device['id'] not in json.dumps(admitted)
    end_scene(service, jid)
    resumed = service.journey_resume(jid, service.journey_state(jid)['revision'])
    assert RECIPE_MARKER not in json.dumps(resumed)
    assert device['id'] not in json.dumps(resumed)
    assert RECIPE_MARKER in json.dumps(service.journey_state(jid, viewer_id=OWNER))


def test_native_pattern_actions_compile_with_frozen_definitions_and_shared_radius(tmp_path):
    service, jid, _, _ = setup(tmp_path)
    bundle = service.journeys.load(jid).state['actors'][OWNER]['bundle']
    rows = {row['display_name']: row for row in bundle['action_catalog']}
    assert 'Set Trap: choose footprint' in rows
    assert 'Trap form: Tripwire' in rows
    assert 'Combat Array: Locking Gate' in rows
    assert rows['Set Trap: choose footprint']['parameters']['trap_footprint'] == 1


def test_scene_ticks_shared_time_once_for_every_actor_and_elapsed_provider(tmp_path, monkeypatch):
    from combat import ext
    service, jid, _, _ = setup(tmp_path)
    observations = []
    def elapsed(session, aid, before, seconds, moving):
        observations.append((aid, int(before), seconds, moving))
    monkeypatch.setitem(ext._HOOKS, 'journey_elapsed', [*ext._HOOKS['journey_elapsed'], elapsed])
    before = service.journeys.load(jid)
    clocks = {aid: construction.source_clock(before, aid) for aid in (OWNER, FOE)}
    for n in (1, 2):
        end_scene(service, jid)
        s = service.journey_resume(jid, service.journey_state(jid)['revision'])
        assert s['seconds'] == n * 6
        cold = CombatService(ROOT, tmp_path).journeys.load(jid)
        assert all(construction.source_clock(cold, aid) == clocks[aid] + n * 6 for aid in clocks)
        with pytest.raises(ValueError):
            service.journey_resume(jid, s['revision'])
    assert observations == [(aid, before, 6, ()) for before in (0, 6) for aid in (OWNER, FOE)]


def test_paused_automatic_response_uses_its_own_private_projection(tmp_path, monkeypatch):
    from combat import ext
    service, jid, _, _ = setup(tmp_path)
    recipe(service, jid)
    state = trap(service, jid)
    session = service.journeys.load(jid)
    session.state['actors'][FOE]['control_mode'] = 'LOCAL_AUTO'
    service.journeys.save(session)
    monkeypatch.setitem(ext._HOOKS, 'journey_auto_blocked', [lambda session, aid: True])
    paused = service.journey_auto_step(jid, state['revision'], FOE)
    assert paused['revision'] == state['revision']
    assert RECIPE_MARKER not in json.dumps(paused)
    assert 'constructed_patterns' not in paused['actors'][OWNER]


def test_persisted_definitions_construct_after_finish_and_actual_fresh_compile(tmp_path):
    service, jid, doc, foe = setup(tmp_path)
    recipe(service, jid)
    admit(service, jid, 'formation_damage_type', {'damage_type': 'cold', 'source_logic': 'An actual cold source'})
    state = act(service, jid, 'finish', {})
    bundles = [compile_character(doc, actor_id=OWNER), compile_character(foe, actor_id=FOE)]
    assert ITEM not in bundles[0].get('ordinary_item_specs', {})
    assert not bundles[0]['construction_contract']['damage_types']
    created = service.journeys.create(bundles, state['battlefield'],
        {a: row['position'] for a, row in state['actors'].items()}, {OWNER: 30, FOE: 30})
    jid = created['journey_id']
    trap(service, jid)
    state = act(service, jid, 'prepare_array', {
        'pattern': 'killing_line', 'center': {'x': 3, 'y': 6}, 'site': '', 'damage_type': 'cold'})
    records = state['actors'][OWNER]['constructed_patterns']
    assert records[-2]['payload']['spec']['name'] == RECIPE_MARKER
    assert records[-1]['damage_type'] == 'cold'
    assert CombatService(ROOT, tmp_path).journeys.replay(jid)['status'] == 'PASS'


def test_node_picker_coordinate_normalization_keeps_three_distinct_physical_nodes(tmp_path):
    service, jid, _, _ = setup(tmp_path)
    before = service.journeys.load(jid).state
    with pytest.raises(ValueError, match='distinct'):
        act(service, jid, 'prepare_array', {'pattern': 'locking_gate', 'center': {'x': 3, 'y': 6},
            'site': '', 'damage_type': 'force',
            'nodes': [{'x': 3, 'y': 6}, {'x': 3, 'y': 6, 'z': 0}, {'x': 4, 'y': 6}]})
    assert service.journeys.load(jid).state == before


def choose(service, jid, field, value):
    rows = service.journey_menu(jid, OWNER)['options']
    row = next(r for r in rows if r['kind'] == 'construction_choice'
               and r['payload'] == {'field': field, 'value': value})
    mode = service.journeys.load(jid).state['actors'][OWNER]['control_mode']
    if mode == 'LOCAL_AUTO':
        return service.journey_auto_step(jid, service.journey_state(jid)['revision'], OWNER, row['id'])
    return act(service, jid, row['kind'], row['payload'])


def build(service, jid):
    row = next(r for r in service.journey_menu(jid, OWNER)['options'] if r['id'] == 'construction:build')
    if service.journeys.load(jid).state['actors'][OWNER]['control_mode'] == 'LOCAL_AUTO':
        return service.journey_auto_step(jid, service.journey_state(jid)['revision'], OWNER, row['id'])
    return act(service, jid, row['kind'], row['payload'])


@pytest.mark.parametrize('mode', ['MANUAL', 'LOCAL_AUTO'])
def test_menu_can_build_activation_multispace_direction_stock_origin_and_replacement(tmp_path, mode):
    service, jid, _, _ = setup(tmp_path, mode)
    recipe(service, jid)
    # Reach the actual printed active-trap limit using separate, nonoverlapping devices.
    pb = service.journeys.load(jid).state['actors'][OWNER]['bundle']['construction_contract']['numbers']['pb']
    cells = [{'x': 2, 'y': 5}, {'x': 2, 'y': 6}, {'x': 2, 'y': 7}, {'x': 3, 'y': 5}]
    for cell in cells[:pb]:
        act(service, jid, 'construct_trap', {'form': 'tripwire', 'cells': [cell], 'aim': 'e'})
    old = service.journeys.load(jid).state['actors'][OWNER]['constructed_patterns'][0]['id']
    choose(service, jid, 'family', 'trap')
    choose(service, jid, 'form', 'activation')
    choose(service, jid, 'cell', {'x': 4, 'y': 6})
    choose(service, jid, 'cell', {'x': 4, 'y': 7})
    choose(service, jid, 'footprint_done', 1)
    aims = [r['payload']['value'] for r in service.journey_menu(jid, OWNER)['options']
            if r['kind'] == 'construction_choice' and r['payload']['field'] == 'aim']
    assert set(aims) == {'n', 'ne', 'e', 'se', 's', 'sw', 'w', 'nw'}
    choose(service, jid, 'aim', 'sw')
    choose(service, jid, 'payload_key', item_key(service, jid))
    choose(service, jid, 'payload_count', 2)
    choose(service, jid, 'origin', {'x': 4, 'y': 7})
    choose(service, jid, 'replace', old)
    state = build(service, jid)
    record = state['actors'][OWNER]['constructed_patterns'][-1]
    assert record['aim'] == 'sw' and len(record['cells']) == 2
    assert record['payload']['remaining'] == 2 and record['payload_origin'] == {'x': 4, 'y': 7}
    assert 'construction_draft' not in state['actors'][OWNER]
    assert service.journeys.replay(jid)['status'] == 'PASS'


@pytest.mark.parametrize('mode', ['MANUAL', 'LOCAL_AUTO'])
def test_menu_can_build_touched_bounded_layered_array_with_declared_damage_nodes_and_replacement(tmp_path, mode):
    service, jid, _, _ = setup(tmp_path, mode, array_talents=['tianxia.talent.formations.layered_pattern'])
    admit(service, jid, 'formation_damage_type', {'damage_type': 'cold', 'source_logic': 'Actual cold source'})
    site = [{'x': x, 'y': 6} for x in range(3, 9)]
    admit(service, jid, 'construction_site', {'id': 'known-bridge', 'name': 'Known bridge', 'kind': 'bridge',
        'cells': site, 'known_to': [OWNER]})
    initial = act(service, jid, 'prepare_array', {
        'pattern': 'locking_gate', 'center': {'x': 3, 'y': 6}, 'site': '', 'damage_type': 'force'})
    old = initial['actors'][OWNER]['constructed_patterns'][0]['id']
    choose(service, jid, 'family', 'array')
    choose(service, jid, 'pattern', 'locking_gate')
    choose(service, jid, 'layers', ['locking_gate', 'killing_line'])
    choose(service, jid, 'damage_type', 'cold')
    choose(service, jid, 'center', {'x': 4, 'y': 6})
    choose(service, jid, 'site', 'known-bridge')
    for raw in site[-3:]:
        choose(service, jid, 'node', raw)
    choose(service, jid, 'replace', old)
    state = build(service, jid)
    record = state['actors'][OWNER]['constructed_patterns'][-1]
    assert record['cells'] == site and record['nodes'] == site[-3:]
    assert record['damage_type'] == 'cold' and record['layers'] == ['locking_gate', 'killing_line']
    assert state['actors'][OWNER]['resources']['resource:core.qi'] == 22
    assert service.journeys.replay(jid)['status'] == 'PASS'


@pytest.mark.parametrize('item,name,command,payload', [
    ('tianxia.mortal.tool.thieves_tools', 'Thieves tools', 'construct_trap',
     {'form': 'tripwire', 'cells': [{'x': 4, 'y': 6}], 'aim': 'e'}),
    ('tianxia.mortal.gear.chalk', 'Chalk', 'prepare_array',
     {'pattern': 'locking_gate', 'center': {'x': 3, 'y': 6}, 'site': '', 'damage_type': 'force'}),
    (ITEM, 'Ordinary batch', 'construct_trap', None),
])
def test_drop_commit_reload_resume_rejects_absent_components_and_payload(tmp_path, item, name, command, payload):
    service, jid, _, _ = setup(tmp_path)
    recipe(service, jid)
    key = item_key(service, jid, item)
    end_scene(service, jid, drop=[name])
    cold = CombatService(ROOT, tmp_path)
    cold.journey_resume(jid, cold.journey_state(jid)['revision'])
    before = cold.journeys.load(jid).state
    from combat import carry
    assert not carry.journey_holds(before['actors'][OWNER], key)
    with pytest.raises(ValueError, match='tools|markers|stock'):
        if payload is None:
            trap(cold, jid)
        else:
            act(cold, jid, command, payload)
    assert cold.journeys.load(jid).state == before
    if item == ITEM:
        assert not any(r[0]['key'] == key for r in journey_available(before['actors'][OWNER]))
