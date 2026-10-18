"""Small native guards for lethal journey consequences and bounded route work."""
import json
import zipfile

import pytest

from combat.ext.cloud_walker import WIND
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, sheet


def test_wind_targets_do_not_add_an_unprinted_sight_requirement(tmp_path):
    """Retained walker regression, isolated for a lean whole-file CI rerun.

    Filled rectangles cover cell centers: a zero-width rectangle paints no
    cells. The screen must have real width to exercise an unseen recipient.
    """
    from tests.test_mgr_t14_cloud_walker import journey_game
    cold, jid, act, aid, bid = journey_game(tmp_path, companion_position={'x': 5, 'y': 6},
        map_walls=[{'shape': 'rect', 'points': [[4, 5], [5, 8]], 'blocks': 'sight', 'filled': True}])
    scene = cold().journeys.load(jid)
    assert not scene.grid.line_of_sight(Position(x=3, y=6), Position(x=5, y=6))
    act('cloud_wind_begin')
    act('wait', {'seconds': 600})
    act('cloud_wind_invite', {'target_id': bid})
    act('cloud_wind_reply', {'caster_id': aid, 'accept': True}, bid)
    state = act('cloud_wind_finish')
    assert WIND in state['actors'][bid]['travel_effects']


@pytest.fixture(scope='module', autouse=True)
def tested_source_identity(tmp_path_factory):
    """The terminal test log identifies the exact implementation it exercised."""
    import hashlib
    files = ['combat/flight.py', 'combat/granted_movement.py', 'combat/journey_falling.py',
             'combat/ext/journey_setup.py', 'tests/test_mgr_t14_cloud_review_f7.py',
             'tests/test_mgr_t14_cloud_review_f6.py',
             'authority/Tianxia_Typed_Mechanics_Authority_R1.json']
    receipt = {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in files}
    (tmp_path_factory.getbasetemp() / 'cloud-f7-source.json').write_text(json.dumps(receipt, sort_keys=True) + '\n')


def test_journey_fall_without_progress_fails_on_its_first_checkpoint(monkeypatch):
    """A no-progress provider cannot send the journey into an unbounded loop."""
    from types import SimpleNamespace
    from combat import falling, journey_falling
    from tests.h1_support import duel, ME
    engine = duel([])
    engine.state.actors[ME].position = Position(x=3, y=6, z=2)
    assert falling.required(engine, engine.state.actors[ME])
    monkeypatch.setattr(journey_falling, 'engine_for', lambda state: engine)
    calls = []
    def no_progress(*args):
        calls.append(1)
        assert len(calls) == 1, 'Journey repeated a fall checkpoint that cannot progress'
    monkeypatch.setattr(falling, 'settle', no_progress)
    genesis = {'seconds': 0, 'actors': {ME: {}}, 'journey_falls_due': {ME: 'test:withdrawn'}}
    with pytest.raises(ValueError, match='legal supporting space'):
        journey_falling.resolve(SimpleNamespace(state=genesis), genesis, [])
    assert len(calls) == 1


def test_native_zero_hp_condition_snapshot_keeps_flags_without_relaxing_clocks():
    from combat.ext.journey_setup import encounter_snapshot, encounter_incapacitated
    from combat.ext.life_state import UNCONSCIOUS
    from tests.h1_support import duel, ME
    engine = duel([])
    actor = engine.state.actors[ME]
    engine.state.rules['zero_hp'] = 'dying_2024'
    actor.current_hp = 0
    engine._defeat(actor, 'system:combat.falling')
    condition = next(c for c in actor.conditions.values() if c.condition_id == UNCONSCIOUS)
    prone = next(c for c in actor.conditions.values() if c.condition_id == 'condition:typed.prone')
    assert prone.expires_on == 'STAND_UP'
    # Genuine native rule flags use bools; the snapshot has an integer-only
    # persistence boundary. Even a false flag must survive without mutation.
    condition.data.update(rule={'no_actions': True, 'no_reactions': True},
                          nested=[False, {'enabled': True}])
    original = actor.model_dump(mode='json')
    try:
        saved = encounter_snapshot(actor)
    except ValueError as error:
        pytest.fail('Native zero-HP snapshot rejected: ' + json.dumps(
            {key: c.model_dump(mode='json') for key, c in actor.conditions.items()}, sort_keys=True)
            + '; ' + str(error))
    held = json.loads(saved['conditions'][condition.instance_id])
    assert held['data']['rule'] == {'no_actions': 1, 'no_reactions': 1}
    assert type(held['data']['rule']['no_actions']) is int
    assert held['data']['nested'] == [0, {'enabled': 1}]
    assert saved['current_hp'] == 0 and saved['life_state'] == 'DYING'
    assert json.loads(saved['conditions'][prone.instance_id])['expires_on'] == 'STAND_UP'
    assert prone.instance_id in encounter_snapshot(actor, effects_ended=True)['conditions']
    assert encounter_incapacitated(saved)
    assert actor.model_dump(mode='json') == original
    prone.condition_id = 'condition:typed.unknown_condition'
    with pytest.raises(ValueError, match='timed or unsupported'):
        encounter_snapshot(actor)
    prone.condition_id = 'condition:typed.prone'
    condition.expires_on = 'END_OF_CURRENT_TURN'
    with pytest.raises(ValueError, match='timed or unsupported'):
        encounter_snapshot(actor)
    condition.expires_on = 'UNTIL_REMOVED'
    condition.data['invalid'] = 0.5
    with pytest.raises(ValueError, match='timed or unsupported'):
        encounter_snapshot(actor)
    condition.data['invalid'] = object()
    with pytest.raises((ValueError, TypeError)):
        encounter_snapshot(actor)


def test_impulse_search_derives_observed_occupancy_once_and_keeps_all_endpoints(monkeypatch):
    """Bound work by graph edges, not repeated scene/perception derivations."""
    from combat import creature_passage
    from combat.flight import reachable
    from tests.h1_support import duel, ME, FOE
    from tests.test_lock_choices import install
    engine = duel([])
    actor = engine.state.actors[ME]
    before = engine.state.model_dump(mode='json'), len(engine.events), engine.roller.counter
    assert reachable(engine, actor, mode='impulse', grant_ft=15) == {}
    calls = []
    native = creature_passage.volume_geometry
    def observed_geometry(*args, **kwargs):
        calls.append(1)
        return native(*args, **kwargs)
    monkeypatch.setattr(creature_passage, 'volume_geometry', observed_geometry)
    install(monkeypatch, 'movement_step_capability',
            lambda engine, actor, old, new, mode: True if mode == 'impulse' else None)
    routes = reachable(engine, actor, mode='impulse', grant_ft=15)
    assert len(calls) == 1
    assert len(routes) > 30
    assert actor.position.model_copy(update={'z': 3}) in routes
    assert engine.state.actors[FOE].position not in routes
    target = actor.position.model_copy(update={'y': actor.position.y - 1})
    assert reachable(engine, actor, mode='impulse', grant_ft=15, target=target) == {target: routes[target]}
    assert (engine.state.model_dump(mode='json'), len(engine.events), engine.roller.counter) == before
    with monkeypatch.context() as scoped:
        install(scoped, 'movement_step_capability',
                lambda engine, actor, old, new, mode: False if new.z else None)
        assert all(not p.z for p in reachable(engine, actor, mode='impulse', grant_ft=15))


def test_lethal_borrowed_mist_fall_commits_cold_life_state(tmp_path):
    """No acquisition/replay batch is needed to reproduce the native boundary."""
    caster, target = 'actor:factory.donor', 'actor:factory.traveller'
    for pid, doc in [('donor', sheet([WIND], cl=10, name='Mist donor')),
                     ('traveller', sheet([], cl=1, name='Mortal traveller'))]:
        if pid == 'traveller':
            doc['ability_scores_and_statistics']['hit_points']['maximum'] = 1
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({'display_name': 'Lethal withdrawal', 'width_squares': 12,
        'height_squares': 14, 'walls': [], 'starts': {'team1': [[3, 6]], 'team2': [[4, 6]]}})
    state = service.create_journey(project_ids=['donor', 'traveller'],
        arena_id='battlefield:map.lethal-withdrawal',
        positions={caster: {'x': 3, 'y': 6}, target: {'x': 4, 'y': 6}},
        base_paces={caster: 18000, target: 18000},
        control_modes={caster: 'LOCAL_AUTO', target: 'MANUAL'})
    jid = state['journey_id']
    def act(aid, kind, payload=None):
        cold = CombatService(ROOT, tmp_path)
        before = cold.journey_state(jid)
        after = cold.journey_act(jid, before['revision'], aid, kind, payload or {})
        assert CombatService(ROOT, tmp_path).journey_state(jid) == after
        assert cold.journey_verify(jid)['status'] == 'PASS'
        return after
    act(caster, 'cloud_wind_begin')
    act(caster, 'wait', {'seconds': 600})
    act(caster, 'cloud_wind_invite', {'target_id': target})
    act(target, 'cloud_wind_reply', {'caster_id': caster, 'accept': True})
    act(caster, 'cloud_wind_finish')
    act(target, 'move', {'path': [{'x': 4, 'y': 6, 'z': 1}, {'x': 4, 'y': 6, 'z': 2}]})
    state = act(target, 'cloud_wind_end')
    actor = state['actors'][target]
    saved = actor['encounter_snapshot']
    assert saved['current_hp'] == 0 and actor['incapacitated'] == 1
    assert Position.model_validate(actor['position']) == Position(x=4, y=6)
    assert WIND not in actor['travel_effects']
    assert saved['life_state'] == 'DYING' or not saved['active']
    assert any(json.loads(c)['condition_id'] in {
        'condition:typed.life_unconscious', 'condition:typed.death_finalized'}
        for c in saved['conditions'].values())
    assert any(json.loads(c)['condition_id'] == 'condition:typed.prone'
               and json.loads(c)['expires_on'] == 'STAND_UP' for c in saved['conditions'].values())
    with pytest.raises(ValueError, match='incapacitated'):
        act(target, 'incapacitated', {'value': False})
