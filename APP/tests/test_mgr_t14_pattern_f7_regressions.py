"""Native elevated geometry and component installation from the F6 review."""
from copy import deepcopy
import os

import pytest

from combat.ext import formations, placed
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY, FOE, settle, turn


def game(tmp_path, *, roof=False, wall=None, mode='MANUAL', small=False):
    kit = {'starting_kit': {'items': [
        {'item_id': 'tianxia.mortal.tool.thieves_tools', 'quantity': 1, 'name': 'Thieves tools'},
        {'item_id': 'tianxia.mortal.gear.chalk', 'quantity': 1, 'name': 'Chalk'}]}}
    doc = sheet(['TRAP_BASE_DART_MECHANISM', 'FORMATIONS_BASE_SET_ARRAY'], cl=5, kit=kit)
    doc['spheres_and_talents']['formation_patterns'] = ['locking_gate']
    bundles = [compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True}),
               compile_character(sheet([], cl=5), actor_id=ALLY),
               compile_character(sheet([], cl=5), actor_id=FOE)]
    arena = {'display_name': 'Physical construction yard', 'stable_id': 'construction:f7',
             'width_squares': 12, 'height_squares': 12, 'square_size_ft': 5,
             'starting_positions': {}, 'terrain_regions': []}
    if roof:
        cells = ([{'x': 3, 'y': 6}, {'x': 4, 'y': 6}] if small else
                 [{'x': x, 'y': y} for x in range(3, 10) for y in range(5, 8)])
        arena['roof_surfaces'] = [{'id': 'partial-roof', 'height_ft': 10, 'cells': cells}]
    if wall:
        arena['terrain_regions'] = [{'region_id': 'solid', 'terrain_type': 'BLOCKED',
            'cells': [wall], 'movement_cost': 1, 'description': 'Solid stone obstruction',
            'base_altitude_ft': 10 if roof else 0, 'height_ft': 5 if roof else 10}]
    z = 2 if roof else 0
    positions = {OWNER: {'x': 3, 'y': 6, 'z': z}, ALLY: {'x': 4, 'y': 5, 'z': z},
                 FOE: {'x': 8, 'y': 6, 'z': z}}
    if small:
        positions[ALLY] = {'x': 8, 'y': 5}
        positions[FOE] = {'x': 8, 'y': 6}
    service = CombatService(ROOT, tmp_path)
    state = service.journeys.create(bundles, arena, {a: {**p, 'z': 0} for a, p in positions.items()}, {a: 30 for a in positions},
                                    {OWNER: mode, ALLY: 'MANUAL', FOE: 'MANUAL'})
    if roof:
        # Travel creation starts on the ground. Establish roof positions through
        # the native scene/settlement path, never by rewriting journey state.
        from tests.test_mgr_t14_pattern_f6_regressions import finish
        mid = service.journey_start_scene(state['journey_id'], state['revision'],
            {a: 'party' for a in positions}, positions=positions)['match_id']
        # End this setup-only window manually; the journey keeps its own
        # LOCAL_AUTO seat for the actual construction-choice assertions.
        if mode == 'LOCAL_AUTO':
            service.set_controller_mode(mid, actor_id=OWNER, controller_mode='MANUAL')
        finish(service, TabletopService(service, tmp_path), mid, state['journey_id'])
    return service, state['journey_id']


def act(service, jid, kind, payload):
    state = service.journey_act(jid, service.journey_state(jid)['revision'], OWNER, kind, payload)
    if not state.get('match_id'):
        assert CombatService(ROOT, service.userdata_root).journeys.replay(jid)['status'] == 'PASS'
    return state


@pytest.mark.parametrize('blocked', [False, True])
def test_ritual_roof_dart_hits_elevated_ray_and_stops_at_raised_solid(tmp_path, blocked):
    service, jid = game(tmp_path, roof=True, wall={'x': 6, 'y': 6} if blocked else None)
    # A separate real creature below the ray must never replace the roof victim.
    state = act(service, jid, 'construct_trap',
                {'form': 'dart', 'cells': [{'x': 4, 'y': 6, 'z': 2}], 'aim': 'e'})
    positions = {a: v['position'] for a, v in state['actors'].items()}
    positions[OWNER] = {'x': 5, 'y': 6}  # ground-level decoy, below the roof
    mid = service.journey_start_scene(jid, state['revision'], {OWNER: 'party', ALLY: 'party', FOE: 'enemy'},
                                       maximum_rounds=3, positions=positions)['match_id']
    table = TabletopService(service, tmp_path)
    turn(table, mid, ALLY)
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    move = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE'
                and c.destination == Position(x=4, y=6, z=2))
    settle(table, mid, move.candidate_id)
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    attacks = [e for e in session.engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]
    assert not any(OWNER in e.target_ids for e in attacks)
    assert any(FOE in e.target_ids for e in attacks) == (not blocked)
    assert any(e.event_type == 'PASSIVE_TRIGGERED' and e.payload.get('effect_origin', {}).get('id', '').startswith('trap:')
               for e in session.engine.events)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('roof', [False, True])
@pytest.mark.parametrize('mode', ['MANUAL', 'LOCAL_AUTO'])
def test_default_and_offered_nodes_use_every_supported_unblocked_space(tmp_path, roof, mode):
    service, jid = game(tmp_path, roof=roof, wall={'x': 3 if roof else 0, 'y': 5 if roof else 2}, mode=mode)
    z = 2 if roof else 0
    center = Position(x=3, y=6, z=z).model_dump(mode='json')
    data = {'pattern': 'locking_gate', 'center': center, 'site': '', 'damage_type': 'force'}
    state = act(service, jid, 'prepare_array', data)
    record = state['actors'][OWNER]['constructed_patterns'][0]
    journey = service.journeys.load(jid)
    footprint = [Position.model_validate(c) for c in record['cells']]
    legal = [p for p in footprint if journey.grid.volume_legal(p)
             and (p.z == 0 or journey.grid.roof_supported(p))]
    assert len(legal) < len(footprint), 'Fixture includes blocked or unsupported effect spaces'
    assert len(record['nodes']) == 3
    assert all(Position.model_validate(n) in legal for n in record['nodes'])
    for field, value in [('family', 'array'), ('pattern', 'locking_gate'), ('layers', ['locking_gate']),
                         ('damage_type', 'force'), ('center', center), ('site', '')]:
        act(service, jid, 'construction_choice', {'field': field, 'value': value})
    # Compare the complete offered set, rather than just one acceptable choice.
    options = service.journeys.load(jid).menu(OWNER)['options']
    offered = [r for r in options if r.get('payload', {}).get('field') == 'node']
    assert [Position.model_validate(r['payload']['value']) for r in offered] == legal
    chosen = []
    for _ in range(3):
        options = service.journeys.load(jid).menu(OWNER)['options']
        row = next(r for r in reversed(options) if r.get('payload', {}).get('field') == 'node')
        chosen.append(row['payload']['value'])
        if mode == 'LOCAL_AUTO':
            service.journey_auto_step(jid, service.journey_state(jid)['revision'], OWNER, option_id=row['id'])
        else:
            act(service, jid, row['kind'], row['payload'])
    # Explicit execution rejects the same invalid footprint cells atomically.
    invalid = next(p for p in footprint if p not in legal).model_dump(mode='json')
    before = deepcopy(service.journey_state(jid))
    with pytest.raises(ValueError):
        act(service, jid, 'prepare_array', {**data, 'nodes': [invalid, *chosen[:2]]})
    assert service.journey_state(jid) == before
    if not before.get('match_id'):
        assert CombatService(ROOT, tmp_path).journeys.replay(jid)['status'] == 'PASS'
    assert {Position.model_validate(n) for n in chosen} != {Position.model_validate(n) for n in record['nodes']}
    # Complete the offered draft, including the load replacement decision,
    # through the same API that selected the Nodes for this seat.
    options = service.journeys.load(jid).menu(OWNER)['options']
    replacement, = [r for r in options if r.get('payload', {}).get('field') == 'replace']
    assert replacement['payload']['value'] == record['id']
    def submit(row):
        if mode == 'LOCAL_AUTO':
            return service.journey_auto_step(jid, service.journey_state(jid)['revision'], OWNER, option_id=row['id'])
        return act(service, jid, row['kind'], row['payload'])
    submit(replacement)
    options = service.journeys.load(jid).menu(OWNER)['options']
    build, = [r for r in options if r['kind'] == 'prepare_array']
    assert build['payload']['nodes'] == chosen
    submit(build)
    # The owner reads their own private construction record; the public view hides it.
    state = CombatService(ROOT, tmp_path).journey_state(jid, viewer_id=OWNER)
    installed = state['actors'][OWNER]['constructed_patterns'][-1]
    assert installed['nodes'] == chosen
    assert installed['id'] != record['id']
    cold = CombatService(ROOT, tmp_path)
    if roof:
        # The setup encounter remains bound after settlement. Verify its own
        # immutable replay before continuing; journey-only replay must still
        # refuse this history rather than silently discard the encounter.
        setup_mid = state['match_id']
        with pytest.raises(ValueError, match='Verify the bound encounter'):
            cold.journeys.replay(jid)
        setup_session = cold._load_session(setup_mid)
        assert setup_session.verify()['status'] == 'PASS'
        assert setup_session.mechanical.replay()['status'] == 'PASS'
        assert cold.journey_state(jid)['match_id'] == setup_mid
    else:
        assert cold.journeys.replay(jid)['status'] == 'PASS'
    mid = service.journey_start_scene(jid, state['revision'], {OWNER: 'party', ALLY: 'party', FOE: 'party'})['match_id']
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    array, = formations.arrays(session.engine, OWNER)
    nodes = [o for o in formations.objects_of(session.engine, array) if o.component['role'] == 'node']
    assert array.zone_id == installed['id']
    assert len(nodes) == 3
    assert {o.position for o in nodes} == {Position.model_validate(n) for n in chosen}
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'


def test_default_nodes_require_three_legal_spaces_before_time_or_cp(tmp_path):
    service, jid = game(tmp_path, roof=True, small=True)
    data = {'pattern': 'locking_gate', 'center': {'x': 3, 'y': 6, 'z': 2}, 'site': '', 'damage_type': 'force'}
    before = deepcopy(service.journey_state(jid))
    with pytest.raises(ValueError, match='three supported'):
        act(service, jid, 'prepare_array', data)
    assert service.journey_state(jid) == before
    for field, value in [('family', 'array'), ('pattern', 'locking_gate'), ('layers', ['locking_gate']),
                         ('damage_type', 'force'), ('center', data['center']), ('site', '')]:
        act(service, jid, 'construction_choice', {'field': field, 'value': value})
    options = service.journeys.load(jid).menu(OWNER)['options']
    assert not any(r['kind'] == 'prepare_array' or r.get('payload', {}).get('field') == 'node' for r in options)


def test_stock_wrapper_uses_supported_environment_and_pytest_storage(tmp_path, monkeypatch):
    from tests import test_mgr_t14_patterns_stock as wrapper
    calls = []
    def capture(path, seed):
        assert os.environ['CF_STOCK_EVIDENCE'] == str(tmp_path / 'evidence')
        calls.append((path, seed))
    monkeypatch.setattr(wrapper, 'capture', capture)
    wrapper.test_exact_base_stock(tmp_path, monkeypatch, 'fixture-seed')
    assert calls == [(tmp_path, 'fixture-seed')]
