"""Swift acquired at the table, source import, native moves and cold replay.

Independent Speeds are explicit facts in imported source character sheets,
not patched runtime capabilities. Derived flight is the printed Heaven-Treading
Body provider. All actions, Focus costs and recovery use native source records.
"""
import hashlib
import json
import zipfile
from fractions import Fraction
from types import SimpleNamespace

import pytest

from combat import flight, movement_speeds
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from combat.tabletop import normalize_map, to_battlefield
from tests.h1_support import ROOT, sheet
from tests.auto8f1_table_support import candidate_id

SWIFT = 'TAL_ATHLETICS_SWIFT_MOVEMENT'
BODY = 'TAL_ATHLETICS_BODY_BEYOND_DISTANCE'
HEAVEN = 'TAL_ATHLETICS_HEAVEN_TREADING_BODY'
SPIDER = 'TAL_ATHLETICS_SPIDER_S_TOUCH'
FOCUS = 'resource:core.martial_focus'
A, B = [FACTORY_ACTOR_PREFIX + p for p in ('swift-owner', 'swift-peer')]
SOURCE_HASH = 'b86068e8d978c534796d2924a0bbfe74f63500abf1130f77788b2cc8127a422f'


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    from combat import menu_rank
    monkeypatch.setattr(menu_rank, '_CLIENT', SimpleNamespace(
        embed=lambda texts: [[1.0, 0.0] for _ in texts], prefetch=lambda *a, **k: None))


def build(tmp_path, monkeypatch, *, native=True, derived=False, learn=True, encumbered=False,
          native_feet=30, derived_climb=False):
    # Literal source reads preserve real compiler inputs in the safe CI export.
    printed = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())[SWIFT]
    assert hashlib.sha256(printed.encode()).hexdigest() == SOURCE_HASH
    json.loads((ROOT / 'authority/typed_mechanics/reviewed_final.d/auto8-athletics.json').read_text())
    json.loads((ROOT / 'combat/rules/feature_blocks.d/auto8-athletics.json').read_text())
    json.loads((ROOT / 'combat/rules/feature_blocks.d/walkable-roofs.json').read_text())
    for pid in ('swift-owner', 'swift-peer'):
        document = sheet([BODY, *([HEAVEN] if derived else []), *([SPIDER] if derived_climb else [])],
                         cl=15, primary='Stamina', name=pid)
        if native:
            document['ability_scores_and_statistics']['speed'].update(
                flying_ft=native_feet, climbing_ft=native_feet,
                swimming_ft=native_feet, burrowing_ft=native_feet)
        if encumbered and pid == 'swift-owner':
            document['equipment'] = [{'starting_kit': {'items': [
                {'item_id': 'tianxia.mortal.weapon.fu', 'name': 'Fu (Short Axe)', 'quantity': 1000}]}}]
        package = tmp_path / 'portable_characters' / pid / 'current.zip'
        package.parent.mkdir(parents=True)
        with zipfile.ZipFile(package, 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    battlefield = to_battlefield(normalize_map({
        'display_name': 'Swift source movement yard', 'width_squares': 24, 'height_squares': 12,
        'walls': [{'shape': 'rect', 'points': [[4, 3], [12, 8]], 'filled': False}],
        'roofs': {'height_ft': 30, 'climb_check': 'none'},
        'travel_regions': [*({'kind': kind, 'cells': [[x, y] for x in range(24) for y in (0, 1, 2)],
                            'movement_cost': 1} for kind in ('water', 'burrowable')),
                           {'kind': 'vertical_surface', 'cells': [[3, 3]], 'movement_cost': 1,
                            'requires_support': True, 'max_z': 6}],
    }))
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self, **kw: {'swift-yard': battlefield})
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    if learn:
        legal = next(row for row in table.advancement('swift-owner')['talents'] if row['id'] == SWIFT)
        assert legal['legal'] and not legal['gm']
        table.add_advancement('swift-owner', 'talent', SWIFT)
        assert SWIFT in service._factory_owner_sheet('swift-owner')['spheres_and_talents']['learned_talent_record_ids']
    return service, table, battlefield


def encounter(service, table):
    result = service.create_journey(project_ids=['swift-owner', 'swift-peer'], arena_id='swift-yard',
        positions={A: {'x': 0, 'y': 1}, B: {'x': 20, 'y': 2}}, base_paces={A: 300, B: 300})
    match = service.journey_start_combat(result['journey_id'], 0, {A: 'team:a', B: 'team:b'},
        positions={A: {'x': 3, 'y': 1}, B: {'x': 20, 'y': 2}}, maximum_rounds=5)
    mid = match['match_id']
    for _ in range(4):
        state = table.state(mid)
        menu = state['menu']
        if menu['actor_id'] == A:
            break
        table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], state['last_sequence'])
    return mid


def cold(service, mid):
    fresh = CombatService(ROOT, service.userdata_root)
    session = fresh._load_session(mid)
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine


@pytest.mark.parametrize('mode', movement_speeds.MODES)
def test_independent_modes_spend_bonus_once_through_table_and_replay(tmp_path, monkeypatch, mode):
    service, table, battlefield = build(tmp_path, monkeypatch)
    mid = encounter(service, table)
    engine = cold(service, mid)
    actor = engine.state.actors[A]
    assert movement_speeds.speed(engine, actor, mode) == 40
    assert movement_speeds.speed(engine, engine.state.actors[B], mode) == 30
    if mode == 'climb':
        # Approach along the ground, then climb the actual authored wall.
        path = [{'x': 3, 'y': y} for y in (1, 2, 3)]
        path += [{'x': 3, 'y': 3, 'z': z} for z in range(1, 6)]
    else:
        path = [{'x': x, 'y': 1} for x in range(3, 11)]
    state = table.state(mid)
    menu = state['menu']
    quote = table.preview_move_path(mid, menu['decision_id'], menu['state_version'], A, path, movement_mode=mode)
    assert quote['candidate']['movement_cost_ft'] == 35
    answer = table.commit_move_path(mid, quote['candidate']['candidate_id'], menu['decision_id'],
        menu['state_version'], A, path, movement_mode=mode, after=state['last_sequence'])
    assert answer['status'] == 'COMMITTED'
    engine = cold(service, mid)
    assert engine.state.actors[A].position == Position.model_validate(path[-1])
    assert flight.remaining(engine, engine.state.actors[A], mode) == 5
    receipt = next(e for e in reversed(engine.events) if e.event_type == 'MOVEMENT_COMMITTED')
    assert receipt.payload['cost_ft'] == 35


@pytest.mark.parametrize('derived,native', [(False, True), (True, False), (True, True)])
def test_journey_live_focus_spend_restore_and_combat_replay(tmp_path, monkeypatch, derived, native):
    service, table, battlefield = build(tmp_path, monkeypatch, derived=derived, native=native)
    state = service.create_journey(project_ids=['swift-owner', 'swift-peer'], arena_id='swift-yard',
        positions={A: {'x': 0, 'y': 1}, B: {'x': 20, 'y': 2}}, base_paces={A: 300, B: 300})
    jid = state['journey_id']
    def act(kind, payload=None):
        fresh = CombatService(ROOT, tmp_path)
        before = fresh.journey_state(jid)
        result = fresh.journey_act(jid, before['revision'], A, kind, payload)
        assert CombatService(ROOT, tmp_path).journey_state(jid) == result
        return result
    modes = movement_speeds.MODES if native else ('walk', 'fly')
    x = 0
    for mode in modes:
        session = service.journeys.load(jid)
        assert session.movement_speed(A, mode) == 40
        # Use the actually offered mode/destination, preserving the full menu.
        option = next(o for o in service.journey_menu(jid, A)['options'] if o['kind'] == 'move'
                      and o['payload'].get('mode', 'walk') == mode
                      and o['payload']['path'] == [{'x': x + 1, 'y': 1}])
        before = session.clock()
        state = act(option['kind'], option['payload'])
        assert service.journeys.load(jid).clock() - before == 45
        x += 1
    state = act('activate', {'source': BODY})  # printed Focus cost
    assert state['actors'][A]['resources'][FOCUS] == 0
    assert all(service.journeys.load(jid).movement_speed(A, mode) == 30 for mode in modes)
    before = service.journeys.load(jid).clock()
    state = act('move', {'path': [{'x': x + 1, 'y': 1}]})
    assert service.journeys.load(jid).clock() - before == 6  # sourced 300 * tenfold / no Swift
    match = service.journey_start_combat(jid, state['revision'], {A: 'team:a', B: 'team:b'}, maximum_rounds=1,
        positions={A: {'x': 0, 'y': 1}, B: {'x': 20, 'y': 2}})
    mid = match['match_id']
    for _ in range(8):
        engine = cold(service, mid)
        if engine.state.terminal_result:
            break
        menu = table.state(mid)['menu']
        if menu['actor_id'] == A and engine.state.actors[A].resources[FOCUS] == 0:
            table.act(mid, candidate_id(menu, 'Dash'), menu['decision_id'], menu['state_version'], 0)
            assert cold(service, mid).state.actors[A].resources[FOCUS] == 1
            menu = table.state(mid)['menu']
        table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], 0)
    state = service.journey_resume(jid, service.journey_state(jid)['revision'])
    assert state['actors'][A]['resources'][FOCUS] == 1
    assert all(service.journeys.load(jid).movement_speed(A, mode) == 40 for mode in modes)
    before = service.journeys.load(jid).clock()
    act('move', {'path': [{'x': 1, 'y': 1}], 'mode': 'fly'})
    assert service.journeys.load(jid).clock() - before == 45


def test_absent_modes_and_teleport_never_created(tmp_path, monkeypatch):
    service, table, _ = build(tmp_path, monkeypatch, native=False)
    mid = encounter(service, table)
    engine = cold(service, mid)
    actor = engine.state.actors[A]
    for mode in movement_speeds.MODES[1:]:
        assert movement_speeds.speed(engine, actor, mode) == 0
    assert not any(c.metadata.get('movement_mode') in ('fly', 'swim', 'burrow') for c in engine.legal_candidates())
    with pytest.raises(ValueError, match='Unknown'):
        movement_speeds.speed(engine, actor, 'teleport')


def test_faster_independent_flight_wins_after_composition_and_uses_shared_pool(tmp_path, monkeypatch):
    service, table, _ = build(tmp_path, monkeypatch, native_feet=50, derived=True)
    mid = encounter(service, table)
    engine = cold(service, mid)
    assert movement_speeds.speed(engine, engine.state.actors[A], 'walk') == 40
    assert movement_speeds.speed(engine, engine.state.actors[A], 'fly') == 60
    assert movement_speeds.speed(engine, engine.state.actors[B], 'fly') == 50
    state = table.state(mid)
    menu = state['menu']
    path = [{'x': x, 'y': 1} for x in range(3, 15)]
    quote = table.preview_move_path(mid, menu['decision_id'], menu['state_version'], A, path, movement_mode='fly')
    assert quote['candidate']['movement_cost_ft'] == 55
    result = table.commit_move_path(mid, quote['candidate']['candidate_id'], menu['decision_id'],
        menu['state_version'], A, path, movement_mode='fly', after=state['last_sequence'])
    assert result['status'] == 'COMMITTED'
    engine = cold(service, mid)
    assert flight.remaining(engine, engine.state.actors[A], 'fly') == 5
    assert flight.remaining(engine, engine.state.actors[A], 'walk') == 0


def test_encumbrance_preserves_five_foot_cap_for_all_native_modes(tmp_path, monkeypatch):
    service, table, _ = build(tmp_path, monkeypatch, encumbered=True)
    mid = encounter(service, table)
    engine = cold(service, mid)
    from combat.carry import status
    assert status(engine, engine.state.actors[A])['over']
    assert all(movement_speeds.speed(engine, engine.state.actors[A], mode) <= 5
               for mode in movement_speeds.MODES)


def test_journey_imported_overload_reduces_actual_elapsed_budget(tmp_path, monkeypatch):
    service, table, _ = build(tmp_path, monkeypatch, encumbered=True)
    state = service.create_journey(project_ids=['swift-owner', 'swift-peer'], arena_id='swift-yard',
        positions={A: {'x': 0, 'y': 1}, B: {'x': 20, 'y': 2}}, base_paces={A: 300, B: 300})
    jid = state['journey_id']
    assert state['actors'][A]['resources'][FOCUS] == 1
    assert service.journeys.load(jid).movement_speed(A, 'walk') == 5
    result = service.journey_act(jid, 0, A, 'move', {'path': [{'x': 1, 'y': 1}]})
    assert result['seconds'] == 360  # 300 ft/hour at ordinary 30 ft; cap scales it to 50 ft/hour.
    assert CombatService(ROOT, tmp_path).journey_state(jid) == result


@pytest.mark.parametrize('native,expected_speed,seconds', [(True, 60, 30), (False, 40, 45)])
def test_journey_actual_vertical_climb_uses_independent_or_derived_speed_once(
        tmp_path, monkeypatch, native, expected_speed, seconds):
    service, table, _ = build(tmp_path, monkeypatch, native=native, native_feet=50, derived_climb=True)
    state = service.create_journey(project_ids=['swift-owner', 'swift-peer'], arena_id='swift-yard',
        positions={A: {'x': 3, 'y': 3}, B: {'x': 20, 'y': 2}}, base_paces={A: 300, B: 300})
    jid = state['journey_id']
    assert service.journeys.load(jid).movement_speed(A, 'climb') == expected_speed
    option = next(o for o in service.journey_menu(jid, A)['options'] if o['kind'] == 'move'
                  and o['payload'].get('mode') == 'climb'
                  and o['payload']['path'] == [{'x': 3, 'y': 3, 'z': 1}])
    result = service.journey_act(jid, 0, A, 'move', option['payload'])
    reopened = CombatService(ROOT, tmp_path).journey_state(jid)
    assert reopened == result
    assert result['seconds'] == seconds
    assert result['actors'][A]['position'] == {'x': 3, 'y': 3, 'z': 1}


@pytest.mark.parametrize('mode', movement_speeds.MODES[1:])
def test_recorded_walk_basis_tracks_focus_under_final_halving(mode):
    """Additional public-contract unit regression; no whole-play credit.

    A declared walking-derived capability must retain the source's live basis
    after it is recorded. A raw ten-foot subtraction from a halved snapshot
    would produce 10 instead of 15 feet when Focus is spent.
    """
    from combat.gate2_runtime_models import ModifierInstance
    from tests.test_auto_athletics import _engine, _me
    engine = _engine([SWIFT])
    actor = _me(engine)
    actor.modifiers['half'] = ModifierInstance(modifier_id='half', source_definition_id='test:half',
        source_actor_id=actor.entity_id, target_id=actor.entity_id, target_field='speed_halved',
        operation='SET', value=1, applies_to='speed', expires_on='END_OF_CURRENT_TURN')
    grant = movement_speeds.land_speed_grant(engine, actor, mode)
    engine._apply_condition(actor, 'condition:typed.test_walk_basis', 'test:walk_basis', actor.entity_id,
        expires_on='END_OF_CURRENT_TURN', data=grant)
    assert movement_speeds.speed(engine, actor, mode) == 20
    actor.resources[FOCUS] = 0
    assert movement_speeds.speed(engine, actor, mode) == 15
    actor.resources[FOCUS] = 1
    assert movement_speeds.speed(engine, actor, mode) == 20
