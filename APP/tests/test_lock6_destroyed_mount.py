"""HUNT12-35: an inactive 2x2 Warhorse at (6,4) overlaps wall (7,5).

Use public synthetic sheets and the retained seed/geometry. The setup hook
recreates the captured destroyed actor; the table then advances an AI turn.
The hunt's private character documents are not fixtures in the repository.
"""
import copy
import json
import zipfile

import pytest

from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_factory_live_match import ROOT, _install
from tests.test_lock2_persistence import act
from tests.test_lock_choices import install
from tests.test_mounts import bm


def mounted_table(tmp_path):
    document = copy.deepcopy(bm.SHEET)
    document['equipment'] = []
    document['spheres_and_talents'] = {
        'sphere_record_ids': [bm.BEASTMASTERY], 'learned_talent_record_ids': [],
        'automatic_sphere_component_record_ids': ['BEASTMASTERY_BASE_RIDER_PACKAGE']}
    path = tmp_path / 'portable_characters' / 'left'
    path.mkdir(parents=True)
    with zipfile.ZipFile(path / 'current.zip', 'w') as archive:
        archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    _install(tmp_path, 'right')
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({'display_name': 'Retained mount yard', 'width_squares': 12, 'height_squares': 10,
        'walls': [{'shape': 'rect', 'points': [[7, 5], [8, 6]]}],
        'starts': {'team1': [[5, 4]], 'team2': [[3, 4]]}})
    mid = service.create_factory_match(project_ids=['left'], opponent_actor_ids=['actor:factory.right'],
        control_modes={'actor:factory.left': 'MANUAL', 'actor:factory.right': 'MANUAL'},
        match_seed='HUNT12-35', arena_id='battlefield:map.retained-mount-yard')['match_id']
    return service, TabletopService(service, tmp_path), mid


def mount(engine):
    return next(a for a in engine.state.actors.values() if a.summon and a.summon.get('mountable'))


def test_destroyed_mount_geometry_survives_table_ai_transition_reload_and_replay(monkeypatch, tmp_path):
    def retained_state(engine, kind, kwargs):
        if kind != 'HOLD_POSITION_COMMITTED':
            return
        actor = mount(engine)
        engine._defeat(actor, 'test:retained-mount')
        actor.position = Position(x=6, y=4)
        engine._append_event('MOVEMENT_COMMITTED', 'test:retained-mount', actor_id=actor.entity_id,
            payload={'destination': actor.position.model_dump(mode='json'), 'movement_remaining_ft': 0,
                     'movement_cost_ft': 0, 'path': []})
    install(monkeypatch, 'event', retained_state)
    service, table, mid = mounted_table(tmp_path)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    fresh = CombatService(ROOT, tmp_path)
    session = fresh._load_session(mid)
    destroyed = mount(session.engine)
    assert not destroyed.active and destroyed.current_hp == 0
    assert destroyed.summon['status'] == 'destroyed'
    assert (7, 5) in set(session.engine._actor_cells(destroyed)) & session.engine.grid.blocked
    actor_id = session.engine.state.current_actor_id
    fresh.set_controller_mode(mid, actor_id=actor_id, controller_mode='LOCAL_AUTO')
    table = TabletopService(fresh, tmp_path)
    for _ in range(12):
        state = table.state(mid)
        assert table.auto_step(mid, state['last_sequence'])['status'] == 'COMMITTED'
        if fresh._load_session(mid).engine.state.current_actor_id != actor_id:
            break
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert reloaded.engine.state.current_actor_id != actor_id
    assert not mount(reloaded.engine).active
    reloaded.engine._assert_invariants()
    assert reloaded.verify()['status'] == reloaded.mechanical.replay()['status'] == 'PASS'


def test_active_mount_still_must_fit_the_map(tmp_path):
    service, _, mid = mounted_table(tmp_path)
    engine = service._load_session(mid).engine
    mount(engine).position = Position(x=6, y=4)
    with pytest.raises(ValueError, match='footprint position invariant'):
        engine._assert_invariants()


def test_inactive_creature_still_obeys_resource_and_economy_invariants(tmp_path):
    service, _, mid = mounted_table(tmp_path)
    engine = service._load_session(mid).engine
    actor = mount(engine)
    engine._defeat(actor, 'test:destroy')
    actor.position = Position(x=6, y=4)
    actor.action_available = True
    with pytest.raises(ValueError, match='inactive economy invariant'):
        engine._assert_invariants()
