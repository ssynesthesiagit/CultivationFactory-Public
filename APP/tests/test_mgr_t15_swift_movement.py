"""Swift acquired at the table, source import, native moves and cold replay.

Independent Speeds are explicit facts in imported source character sheets,
not patched runtime capabilities. Derived flight is the printed Heaven-Treading
Body provider. All actions, Focus costs and recovery use native source records.
"""
import json
import zipfile
from fractions import Fraction
from functools import lru_cache
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
SURE = 'TAL_ATHLETICS_SURE_GRIP'
FOCUS = 'resource:core.martial_focus'
A, B = [FACTORY_ACTOR_PREFIX + p for p in ('5a1f7001', '5a1f7002')]
PROJECT_IDS = {'swift-owner': '5a1f7001', 'swift-peer': '5a1f7002'}
OWNER, PEER = PROJECT_IDS['swift-owner'], PROJECT_IDS['swift-peer']


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    from combat import menu_rank
    monkeypatch.setattr(menu_rank, '_CLIENT', SimpleNamespace(
        embed=lambda texts: [[1.0, 0.0] for _ in texts], prefetch=lambda *a, **k: None))


@lru_cache(maxsize=1)
def catalog():
    from canonical_catalog.service import CanonicalCatalogAuthorityService
    return CanonicalCatalogAuthorityService(ROOT)


def build(tmp_path, monkeypatch, *, native=True, derived=False, learn=True, encumbered=False,
          native_feet=30, derived_climb=False, sure_grip=False, hands_full=False, encumbered_peer=False):
    # Literal source reads preserve real compiler inputs in the safe CI export.
    json.loads((ROOT / 'authority/typed_mechanics/reviewed_final.d/auto8-athletics.json').read_text())
    json.loads((ROOT / 'combat/rules/feature_blocks.d/auto8-athletics.json').read_text())
    json.loads((ROOT / 'combat/rules/feature_blocks.d/walkable-roofs.json').read_text())
    for label, pid in PROJECT_IDS.items():
        document = sheet([BODY, *([HEAVEN] if derived else []), *([SPIDER] if derived_climb else []),
                          *([SURE] if sure_grip and label == 'swift-owner' else [])],
                         cl=15, primary='Stamina', name=label)
        if native:
            document['ability_scores_and_statistics']['speed'].update(
                flying_ft=native_feet, climbing_ft=native_feet,
                swimming_ft=native_feet, burrowing_ft=native_feet)
        if encumbered and label == 'swift-owner':
            # Five 70-lb barrels exceed the 210-lb capacity of a Strength 14
            # Medium creature without expanding into a thousand weapon rows.
            document['equipment'] = [{'starting_kit': {'items': [
                {'item_id': 'tianxia.mortal.gear.barrel', 'name': 'Barrel', 'quantity': 5}]}}]
        if encumbered_peer and label == 'swift-peer':
            document['equipment'] = [{'starting_kit': {'items': [
                {'item_id': 'tianxia.mortal.gear.barrel', 'name': 'Barrel', 'quantity': 5}]}}]
        if hands_full and label == 'swift-owner':
            # Two readied one-hand weapons occupy both hands; Sure Grip's
            # climbing arms have no free hand to take a physical grip.
            document['equipment'] = [{'starting_kit': {'items': [
                {'item_id': 'tianxia.mortal.weapon.fu', 'name': 'Fu (Short Axe)', 'quantity': 1},
                {'item_id': 'tianxia.mortal.weapon.bi_shou', 'name': 'Bi Shou (Dagger)', 'quantity': 1}]}}]
        package = tmp_path / 'portable_characters' / pid / 'current.zip'
        package.parent.mkdir(parents=True)
        with zipfile.ZipFile(package, 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    battlefield = to_battlefield(normalize_map({
        'display_name': 'Swift source movement yard', 'width_squares': 24, 'height_squares': 12,
        'walls': [{'shape': 'rect', 'points': [[4, 3], [12, 8]], 'filled': False, 'height_ft': 30}],
        'roofs': {'height_ft': 30, 'climb_check': 'none'},
        'travel_regions': [*({'kind': kind, 'cells': [[x, y] for x in range(24) for y in (0, 1, 2)],
                            'movement_cost': 1} for kind in ('water', 'burrowable')),
                           {'kind': 'vertical_surface', 'cells': [[3, 3]], 'movement_cost': 1,
                            'requires_support': True, 'max_z': 6}],
    }))
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self, **kw: {'swift-yard': battlefield})
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    table.canonical_catalog = catalog()
    if learn:
        legal = next(row for row in table.advancement(OWNER)['talents'] if row['id'] == SWIFT)
        assert legal['legal'] and not legal['gm']
        table.add_advancement(OWNER, 'talent', SWIFT)
        assert SWIFT in service._factory_owner_sheet(OWNER)['spheres_and_talents']['learned_talent_record_ids']
    return service, table, battlefield


def encounter(service, table):
    result = service.create_journey(project_ids=[OWNER, PEER], arena_id='swift-yard',
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


@pytest.mark.parametrize('mode', ('walk', 'fly', 'climb'))
def test_independent_modes_spend_bonus_once_through_table_and_replay(tmp_path, monkeypatch, mode):
    """Combat routes exist for walk, fly and climb; swim/burrow are mapped only.

    A native Swim or Burrow Speed does not itself supply a material-traversal
    route in a fight, so the mapped journey regressions below exercise those
    modes through their real caller. Their Speed compositions are still the
    same all-mode query checked here and in the journey parametrizations.
    """
    service, table, battlefield = build(tmp_path, monkeypatch)
    mid = encounter(service, table)
    engine = cold(service, mid)
    actor = engine.state.actors[A]
    assert all(movement_speeds.speed(engine, actor, m) == 40 for m in movement_speeds.MODES)
    assert all(movement_speeds.speed(engine, engine.state.actors[B], m) == 30
               for m in movement_speeds.MODES)
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
    state = service.create_journey(project_ids=[OWNER, PEER], arena_id='swift-yard',
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


def test_real_overload_in_fight_refuses_the_thirty_five_foot_route_after_reload(tmp_path, monkeypatch):
    """Review F17R finding 1: a real over-capacity owner cannot take the 35 ft route in a fight.

    The bdiff that suggested otherwise attached a synthetic Encumbered condition after turn start,
    which skips carry.refresh (the path real loads take through typed_executor._reweigh). This test
    uses the real barrel fixture: the turn-start pool reads _effective_speed, which carry.speed_limit
    caps at 5 ft, so the 35 ft route is unavailable both live and after a cold reload.
    """
    service, table, _ = build(tmp_path, monkeypatch, encumbered=True)
    mid = encounter(service, table)
    engine = cold(service, mid)
    actor = engine.state.actors[A]
    from combat.carry import status
    assert status(engine, actor)['over']
    assert flight.remaining(engine, actor, 'walk') <= 5
    start = actor.position
    state = table.state(mid)
    menu = state['menu']
    assert menu['actor_id'] == A
    path = [{'x': x, 'y': 1} for x in range(3, 11)]
    quote = table.preview_move_path(mid, menu['decision_id'], menu['state_version'], A, path, movement_mode='walk')
    candidate = quote.get('candidate') or {}
    assert candidate.get('movement_cost_ft', 0) <= 5
    engine = cold(service, mid)
    assert engine.state.actors[A].position == start
    assert flight.remaining(engine, engine.state.actors[A], 'walk') <= 5


def test_general_encumbrance_cap_governs_non_swift_native_flight(tmp_path, monkeypatch):
    """The governing carrying rule caps any over-capacity flier, not only Swift.

    Companion to the stock replays: a creature under capacity keeps its sourced
    Fly Speed, while the same creature over capacity is at the ordinary 5-foot
    cap before any Swift bonus. Nothing here reads the talent id.
    """
    service, table, _ = build(tmp_path, monkeypatch, encumbered_peer=True)
    mid = encounter(service, table)
    engine = cold(service, mid)
    peer = engine.state.actors[B]
    from combat.carry import status
    assert status(engine, peer)['over']
    assert not any(row.get('feature_id') == SWIFT
                   for row in engine.typed_passive_rows.get(B, ()))
    assert movement_speeds.speed(engine, peer, 'walk') == 5
    assert movement_speeds.speed(engine, peer, 'fly') == 5


def test_speed_providers_cannot_recurse_through_flight_or_climb_profiles(tmp_path, monkeypatch):
    """A Speed provider that queries a movement profile must terminate.

    Composition asks the ``speed`` hooks for walking's live contribution. A
    provider that re-reads flight or climb would otherwise loop through
    ``walking_bonus`` without bound. The bounded call count is the regression:
    without the re-entry guard the looping hook runs to the recursion limit.
    """
    from combat import ext, roof_movement
    from combat.gate2_runtime_models import ConditionInstance
    service, table, _ = build(tmp_path, monkeypatch)
    mid = encounter(service, table)
    engine = cold(service, mid)
    actor = engine.state.actors[A]
    for mode in ('fly', 'climb'):
        grant = movement_speeds.land_speed_grant(engine, actor, mode)
        iid = 'test:walk_basis:' + mode
        actor.conditions[iid] = ConditionInstance(instance_id=iid,
            condition_id='condition:typed.test_walk_basis_' + mode,
            source_definition_id='test:walk_basis', source_actor_id=actor.entity_id,
            target_id=actor.entity_id, applied_sequence=0, data=grant,
            expires_on='END_OF_CURRENT_TURN')
    calls = []

    def looping_provider(engine, actor):
        calls.append(1)
        flight.profile(engine, actor)
        roof_movement.profile(engine, actor)
        return 0

    monkeypatch.setitem(ext._HOOKS, 'speed', [*ext._HOOKS['speed'], looping_provider])
    assert movement_speeds.speed(engine, actor, 'fly') == 40
    assert movement_speeds.speed(engine, actor, 'climb') == 40
    assert len(calls) <= 8


def test_journey_imported_overload_reduces_actual_elapsed_budget(tmp_path, monkeypatch):
    service, table, _ = build(tmp_path, monkeypatch, encumbered=True)
    state = service.create_journey(project_ids=[OWNER, PEER], arena_id='swift-yard',
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
    state = service.create_journey(project_ids=[OWNER, PEER], arena_id='swift-yard',
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


def test_journey_climb_shares_combat_grip_restriction_across_cold_reload(tmp_path, monkeypatch):
    """Service-level rejected route: Spider's Touch with Sure Grip and no free hand.

    Combat withdraws physical grips (roof movement admission); mapped travel
    used to climb the same authored surface through the Speed number alone.
    The journey menu and validation must reject the route, keep the ordinary
    walking option, and reject it again after a cold reload.
    """
    service, table, _ = build(tmp_path, monkeypatch, derived_climb=True, sure_grip=True, hands_full=True)
    state = service.create_journey(project_ids=[OWNER, PEER], arena_id='swift-yard',
        positions={A: {'x': 3, 'y': 3}, B: {'x': 20, 'y': 2}}, base_paces={A: 300, B: 300})
    jid = state['journey_id']
    from combat.ext import hand_occupancy
    from combat import roof_movement
    session = service.journeys.load(jid)
    engine = session.movement_projection()
    assert hand_occupancy.free_hands(engine, engine.state.actors[A]) == ()
    assert roof_movement.profile(engine, engine.state.actors[A]).physical_disabled
    # The Speed number is not the blocker: the capability restriction is.
    assert session.movement_speed(A, 'climb') == 40
    climbed = {'path': [{'x': 3, 'y': 3, 'z': 1}], 'mode': 'climb'}
    with pytest.raises(ValueError, match='free hand'):
        service.journey_act(jid, 0, A, 'move', climbed)
    assert not any(o['kind'] == 'move' and o['payload'].get('mode') == 'climb'
                   for o in service.journey_menu(jid, A)['options'])
    fresh = CombatService(ROOT, tmp_path)
    # Compare the two services' public projections (replay genesis and the command
    # journal stay redacted), and prove the rejected attempts wrote nothing.
    assert fresh.journey_state(jid) == service.journey_state(jid)
    assert fresh.journey_state(jid)['revision'] == state['revision']
    assert fresh.journey_state(jid)['actors'][A]['position'] == {'x': 3, 'y': 3}
    assert not any(o['payload'].get('mode') == 'climb'
                   for o in fresh.journey_menu(jid, A)['options'])
    with pytest.raises(ValueError, match='free hand'):
        fresh.journey_act(jid, state['revision'], A, 'move', climbed)
    # The ordinary walking route stays legal: no legal option was cut.
    walk = next(o for o in fresh.journey_menu(jid, A)['options']
                if o['kind'] == 'move' and 'mode' not in o['payload']
                and o['payload']['path'] == [{'x': 3, 'y': 2}])
    moved = fresh.journey_act(jid, state['revision'], A, walk['kind'], walk['payload'])
    assert moved['actors'][A]['position'] == {'x': 3, 'y': 2}


def test_journey_fly_ascent_shares_combat_altitude_restriction(tmp_path, monkeypatch):
    """A retained cannot-gain-altitude condition also governs mapped ascent.

    The synthetic fixture activation applies the printed restriction as a
    native permanent condition in a real fight. The journey resume imports
    that condition with the encounter snapshot, and mapped travel must keep
    refusing every ascent (hostile and cold reload included) while horizontal
    flight and the peer's unaffected ascent stay legal.
    """
    from combat.factory_compiler import compile_character
    from tests.cw2_service_support import add_action, seal
    documents = {}
    for pid in (OWNER, PEER):
        document = sheet([], cl=15, primary='Stamina', name=pid)
        document['ability_scores_and_statistics']['speed'].update(flying_ft=30)
        documents[pid] = document
    bundles = [compile_character(documents[pid], actor_id=f'{FACTORY_ACTOR_PREFIX}{pid}')
               for pid in (OWNER, PEER)]
    add_action(bundles[0], 'Fixture flight cannot ascend', [
        {'type': 'condition', 'condition': 'flight_limited', 'applies_to': 'self',
         'condition_data': {'cannot_gain_altitude': 1}, 'expires_on': 'UNTIL_REMOVED'}], target='SELF')
    seal(bundles[0])
    battlefield = to_battlefield(normalize_map({
        'display_name': 'Swift source movement yard', 'width_squares': 24, 'height_squares': 12,
        'walls': [{'shape': 'rect', 'points': [[4, 3], [12, 8]], 'filled': False}],
        'roofs': {'height_ft': 30, 'climb_check': 'none'},
        'travel_regions': [*({'kind': kind, 'cells': [[x, y] for x in range(24) for y in (0, 1, 2)],
                              'movement_cost': 1} for kind in ('water', 'burrowable')),
                           {'kind': 'vertical_surface', 'cells': [[3, 3]], 'movement_cost': 1,
                            'requires_support': True, 'max_z': 6}],
    }))
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    state = service.journeys.create(bundles, battlefield,
        positions={A: {'x': 0, 'y': 1}, B: {'x': 20, 'y': 2}}, base_paces={A: 300, B: 300})
    jid = state['journey_id']
    match = service.journey_start_combat(jid, 0, {A: 'team:a', B: 'team:b'}, maximum_rounds=5)
    mid = match['match_id']
    cast = False
    for _ in range(30):
        engine = cold(service, mid)
        if engine.state.terminal_result is not None:
            break
        menu = table.state(mid)['menu']
        if menu['actor_id'] == A and not cast:
            table.act(mid, candidate_id(menu, 'Fixture flight cannot ascend'),
                      menu['decision_id'], menu['state_version'], 0)
            cast = True
        else:
            table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], 0)
    assert cast
    revision = service.journey_state(jid)['revision']
    state = service.journey_resume(jid, revision)
    snapshot_conditions = {key: json.loads(row)
                           for key, row in state['actors'][A]['encounter_snapshot']['conditions'].items()}
    retained = [row for row in snapshot_conditions.values()
                if row['condition_id'] == 'condition:typed.flight_limited']
    assert len(retained) == 1 and retained[0]['data']['cannot_gain_altitude'] == 1
    assert retained[0]['expires_on'] in (None, 'UNTIL_REMOVED')
    ascent = {'path': [{'x': 1, 'y': 1, 'z': 1}], 'mode': 'fly'}
    with pytest.raises(ValueError, match='gain altitude'):
        service.journeys.act(jid, state['revision'], A, 'move', ascent)
    assert not any(o['kind'] == 'move' and o['payload'].get('mode') == 'fly'
                   and o['payload']['path'][0].get('z')
                   for o in service.journey_menu(jid, A)['options'])
    # Horizontal flight and the unrestricted peer's ascent stay legal.
    level = service.journeys.act(jid, state['revision'], A, 'move', {'path': [{'x': 1, 'y': 1}], 'mode': 'fly'})
    assert level['actors'][A]['position'] == {'x': 1, 'y': 1}
    fresh = CombatService(ROOT, tmp_path)
    # A cold service reproduces the last committed public view, not the raw session
    # (whose replay genesis and command journal the public projection redacts).
    assert fresh.journey_state(jid) == level
    assert fresh.journey_state(jid)['actors'][A]['position'] == {'x': 1, 'y': 1}
    with pytest.raises(ValueError, match='gain altitude'):
        fresh.journeys.act(jid, fresh.journey_state(jid)['revision'], A, 'move', ascent)
    peer = {'path': [{'x': 21, 'y': 2, 'z': 1}], 'mode': 'fly'}
    assert fresh.journeys.act(jid, fresh.journey_state(jid)['revision'], B, 'move', peer)[
        'actors'][B]['position'] == {'x': 21, 'y': 2, 'z': 1}


def test_journey_fly_cannot_cross_a_sealed_roof_slab(tmp_path, monkeypatch):
    """Mapped flight uses combat's sealed-slab rule, not just terrain tags.

    Combat flight refuses a step that crosses a solid roof slab
    (volume_step_legal -> roof_step_blocked). Mapped travel must refuse the
    same step, before and after a cold reload, while the legal rise below the
    slab stays offered.
    """
    service, table, _ = build(tmp_path, monkeypatch)
    roofed = to_battlefield(normalize_map({
        'display_name': 'Swift sealed roof yard', 'width_squares': 18, 'height_squares': 12,
        'background': {'style': 'wood'},
        'walls': [{'shape': 'rect', 'points': [[4, 3], [9, 8]], 'filled': False}],
        'roofs': {'height_ft': 10, 'climb_check': 'none'},
    }))
    assert roofed['roof_surfaces']
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self, **kw: {'roof-yard': roofed})
    state = service.create_journey(project_ids=[OWNER, PEER], arena_id='roof-yard',
        positions={A: {'x': 5, 'y': 5}, B: {'x': 12, 'y': 2}}, base_paces={A: 300, B: 300})
    jid = state['journey_id']
    # The floor below the 10-ft slab is open: a 5-ft rise is legal.
    state = service.journey_act(jid, 0, A, 'move', {'path': [{'x': 5, 'y': 5, 'z': 1}], 'mode': 'fly'})
    assert state['actors'][A]['position'] == {'x': 5, 'y': 5, 'z': 1}
    projection = service.journeys.load(jid).movement_projection()
    assert not flight.step_allowed(projection, projection.state.actors[A],
        Position(x=5, y=5, z=1), Position(x=5, y=5, z=2), mode='fly')
    through = {'path': [{'x': 5, 'y': 5, 'z': 2}], 'mode': 'fly'}
    with pytest.raises(ValueError, match='roof slab'):
        service.journey_act(jid, state['revision'], A, 'move', through)
    assert not any(option['kind'] == 'move' and option['payload'].get('mode') == 'fly'
                   and option['payload']['path'][0].get('z') == 2
                   for option in service.journey_menu(jid, A)['options'])
    fresh = CombatService(ROOT, tmp_path)
    with pytest.raises(ValueError, match='roof slab'):
        fresh.journey_act(jid, fresh.journey_state(jid)['revision'], A, 'move', through)


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


def test_overload_that_arrives_mid_turn_caps_the_walking_pool(tmp_path, monkeypatch):
    """Review F20R finding 1: an overload that lands during the owner's turn ends the 35 ft route.

    The real load path is typed_executor._reweigh -> carry.refresh. Refresh priced the Speed
    before the change with the live load, which already read over capacity, so the change was
    zero and the walking pool kept the Swift-enlarged allowance. Here the load is raised in
    the engine after turn start and refresh runs exactly as _reweigh runs it.
    """
    from combat import carry
    service, table, _ = build(tmp_path, monkeypatch)
    mid = encounter(service, table)
    engine = cold(service, mid)
    actor = engine.state.actors[A]
    assert engine.state.current_actor_id == A
    assert flight.remaining(engine, actor, 'walk') >= 35
    carrying = carry.carrying_of(engine, A)
    carrying['weight_lb'] = int(carrying['capacity_lb']) + 1
    carry.refresh(engine, actor, 'test:mid_turn_load')
    assert carry.status(engine, actor)['over']
    assert movement_speeds.speed(engine, actor, 'walk') == 5
    assert flight.remaining(engine, actor, 'walk') <= 5
    assert actor.movement_remaining_ft <= 5
