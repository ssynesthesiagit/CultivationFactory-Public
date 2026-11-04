"""Assigned Athletics contracts through real table commits and cold reload."""
import pytest
from combat.ext import effect
from combat.flight import profile
from tests.auto8f1_table_support import fixture, OWNER, candidate_id, reload_identical

WINGS = 'TAL_ATHLETICS_POWERFUL_WINGS'
SPARROW = 'TAL_ATHLETICS_SPARROW_S_PATH'
LUNGS = 'TAL_ATHLETICS_STRONG_LUNGS'
SHARK = 'TAL_ATHLETICS_SHARK_SWIM'


@effect('mgr_t16_test_wing_flight')
def wing_flight(ctx, eff):
    ctx.engine._apply_condition(ctx.actor, 'condition:typed.test_wing_flight', 'test:physical_flight', ctx.actor.entity_id,
        expires_on='END_OF_CURRENT_TURN', data={'fly_speed_ft': 15, 'physical_wings': eff['wings'],
                                               'label': 'Temporary test flight through explicitly recorded wings.'})


@effect('mgr_t16_test_fly_speed_zero')
def fly_speed_zero(ctx, eff):
    ctx.engine._apply_condition(ctx.actor, 'condition:typed.test_fly_speed_zero', 'test:fly_speed_zero', ctx.actor.entity_id,
        expires_on='END_OF_CURRENT_TURN', data={'fly_speed_zero': 1,
                                               'label': 'Test impairment: Fly Speed 0 until the end of the turn.'})


@pytest.mark.parametrize('wings', [0, 1])
def test_temporary_wing_flight_qualifies_hover_and_expires_at_table(tmp_path, wings):
    from tests.test_a2_athletics_second_pass import add_action
    def prepare(bundles):
        b = next(b for b in bundles if b['actor_id'] == OWNER)
        add_action(b, 'Gain test flight', [{'type': 'mgr_t16_test_wing_flight', 'wings': wings}])
    g = fixture(tmp_path, [WINGS], bundle_transform=prepare, seed='MGR-WING-GRANT-'+tmp_path.name)
    g['commit'](candidate_id(g['menu'](), 'Gain test flight'))
    engine = g['stored_engine']()
    assert profile(engine, engine.state.actors[OWNER]).hover is bool(wings)
    g['commit'](g['menu']()['end_turn'])
    engine = g['stored_engine']()
    assert profile(engine, engine.state.actors[OWNER]).hover is False
    reload_identical(g['combat'], g['match_id'], tmp_path)


@pytest.mark.parametrize('talents,wings,speed,hover', [
    ([WINGS], True, 30, True), ([WINGS], False, 30, False),
    ([WINGS, SPARROW], False, 0, False), ([], True, 30, False),
    ([WINGS], True, 0, False),
])
def test_physical_wing_hover_at_table_survives_reload(tmp_path, talents, wings, speed, hover):
    def prepare(bundles):
        b = next(b for b in bundles if b['actor_id'] == OWNER)
        b['actor_template']['fly_speed_ft'] = speed
        b['actor_template']['creature_types'] = [f'physiology:physical_wings:{int(wings)}']
    g = fixture(tmp_path, talents, bundle_transform=prepare, seed='MGR-T16-WINGS-' + tmp_path.name)
    g['commit'](candidate_id(g['menu'](), 'Hold position'))
    engine = g['stored_engine']()
    assert profile(engine, engine.state.actors[OWNER]).hover is hover
    reload_identical(g['combat'], g['match_id'], tmp_path)


def test_physical_wing_hover_lapses_when_its_speed_becomes_zero(tmp_path):
    """Powerful Wings hovers only while the fighter has a Fly Speed; a zeroed Speed drops it."""
    from tests.test_a2_athletics_second_pass import add_action
    def prepare(bundles):
        b = next(b for b in bundles if b['actor_id'] == OWNER)
        b['actor_template']['fly_speed_ft'] = 30
        b['actor_template']['creature_types'] = ['physiology:physical_wings:1']
        add_action(b, 'Restrained test flyer', [{'type': 'condition', 'condition': 'restrained', 'applies_to': 'self'}])
    g = fixture(tmp_path, [WINGS], bundle_transform=prepare, seed='MGR-WING-HOVER-ZERO')
    row = next(m for m in g['menu']()['moves'] if m['destination'].get('z', 0) == 1)
    g['commit'](row['candidate_id'])
    assert g['reload_owner']().position.z == 1
    g['commit'](candidate_id(g['menu'](), 'Restrained test flyer'))
    engine = g['stored_engine']()
    actor = engine.state.actors[OWNER]
    assert profile(engine, actor).speed_ft == 0 and profile(engine, actor).hover is False
    assert actor.position.z == 0
    reload_identical(g['combat'], g['match_id'], tmp_path)


def test_powerful_wings_hover_lapses_when_a_row_zeroes_the_fly_speed(tmp_path):
    """A recorded "your Fly Speed becomes 0" row removes the Fly Speed the printed Hover needs."""
    from tests.test_a2_athletics_second_pass import add_action
    def prepare(bundles):
        b = next(b for b in bundles if b['actor_id'] == OWNER)
        b['actor_template']['fly_speed_ft'] = 30
        b['actor_template']['creature_types'] = ['physiology:physical_wings:1']
        add_action(b, 'Zero the test flyer', [{'type': 'mgr_t16_test_fly_speed_zero'}])
    g = fixture(tmp_path, [WINGS], bundle_transform=prepare, seed='MGR-WING-ZERO-ROW')
    row = next(m for m in g['menu']()['moves'] if m['destination'].get('z', 0) == 1
               and m.get('movement_mode') == 'fly')
    g['commit'](row['candidate_id'])
    assert g['reload_owner']().position.z == 1
    engine = g['stored_engine']()
    assert profile(engine, engine.state.actors[OWNER]).hover is True
    g['commit'](candidate_id(g['menu'](), 'Zero the test flyer'))
    engine = g['stored_engine']()
    actor = engine.state.actors[OWNER]
    assert profile(engine, actor).speed_ft == 0 and profile(engine, actor).hover is False
    assert actor.position.z == 0
    reload_identical(g['combat'], g['match_id'], tmp_path)


@pytest.mark.parametrize('wings', [1, 0])
def test_powerful_wings_hover_follows_its_fly_speed_at_the_table_and_after_cold_reload(tmp_path, wings):
    """The menu's flying option, then zero Speed, at the table and after a cold reload.

    Powerful Wings says Hover needs a Fly Speed from the fighter's own physical wings. The
    player-facing proof is the menu's own flying move (``movement_mode`` "fly", the entry a
    player clicks to leave the ground), not a direct query: with wings the fighter hovers
    while it has that Fly Speed, and once its Speed reaches 0 (wings or not) the same move
    and the same table action drop it to the ground. Both sides reload the fight from disk
    before and after the Speed loss."""
    from tests.test_a2_athletics_second_pass import add_action
    def prepare(bundles):
        b = next(b for b in bundles if b['actor_id'] == OWNER)
        b['actor_template']['fly_speed_ft'] = 30
        b['actor_template']['creature_types'] = [f'physiology:physical_wings:{wings}']
        add_action(b, 'Restrained test flyer', [{'type': 'condition', 'condition': 'restrained', 'applies_to': 'self'}])
    g = fixture(tmp_path, [WINGS], bundle_transform=prepare, seed='MGR-WING-MENU-' + tmp_path.name)
    aerial = next(m for m in g['menu']()['moves'] if m['destination'].get('z', 0) == 1
                  and m.get('movement_mode') == 'fly')
    g['commit'](aerial['candidate_id'])
    assert g['reload_owner']().position.z == 1
    engine = g['stored_engine']()
    owner = engine.state.actors[OWNER]
    assert profile(engine, owner).hover is bool(wings)
    reload_identical(g['combat'], g['match_id'], tmp_path)
    g['commit'](candidate_id(g['menu'](), 'Restrained test flyer'))
    engine = g['stored_engine']()
    owner = engine.state.actors[OWNER]
    assert profile(engine, owner).speed_ft == 0
    assert owner.position.z == 0
    assert profile(engine, owner).hover is False
    reload_identical(g['combat'], g['match_id'], tmp_path)


@pytest.mark.parametrize('shark,con,expected', [(False, 2, 720), (True, 2, 7200), (True, -2, 3600)])
def test_owned_breath_duration_ticks_through_table_and_cold_reload(tmp_path, shark, con, expected):
    from combat.breath_clock import CLOCK
    def prepare(bundles):
        b = next(b for b in bundles if b['actor_id'] == OWNER)
        for action in b['action_catalog']:
            typed = action.get('parameters', {}).get('typed', {})
            if any(e.get('type') == 'athletics_breath' for e in typed.get('effects', ())):
                typed['numbers']['con_mod'] = con
        b['actor_template']['proficiency_bonus'] = 4
    g = fixture(tmp_path, [LUNGS] + ([SHARK] if shark else []), bundle_transform=prepare,
                seed='MGR-T16-BREATH-' + tmp_path.name)
    g['commit'](candidate_id(g['menu'](), 'hold your breath'))
    clock = next(c for c in g['reload_owner']().conditions.values() if c.condition_id == CLOCK)
    assert clock.data['remaining_seconds'] == expected
    g['commit'](g['menu']()['end_turn'])
    clock = next(c for c in g['reload_owner']().conditions.values() if c.condition_id == CLOCK)
    assert clock.data['remaining_seconds'] == expected - 6
    g['to_owner']()
    g['commit'](candidate_id(g['menu'](), 'breathe again'))
    assert not any(c.condition_id == CLOCK for c in g['reload_owner']().conditions.values())
    reload_identical(g['combat'], g['match_id'], tmp_path)


@pytest.mark.parametrize('owned,cost', [(True, 5), (False, 10)])
def test_shark_swim_prices_real_water_movement_and_reload(tmp_path, owned, cost):
    from combat.tabletop import normalize_map, to_battlefield
    from tests.test_walkable_roofs import roof_fight, OWNER as WALKER, perform, cold
    # Reuse the real match factory, replacing only this fixture's map document.
    from tests import test_walkable_roofs as support
    original = support.roof_document
    def water_document(**kwargs):
        doc = original(**kwargs)
        doc.update(walls=[], objects=[], roofs={'enabled': False}, terrain=[
            {'type': 'WATER', 'cells': [[4, 3], [5, 3]]}])
        return doc
    from unittest.mock import patch
    with patch.object(support, 'roof_document', water_document):
        combat, table, mid = roof_fight(tmp_path, owner_talents=[SHARK] if owned else [])
    session, candidate = perform(combat, mid, lambda c: c.destination is not None
                                 and (c.destination.x, c.destination.y, c.destination.z) == (4, 3, 0))
    assert candidate.movement_cost_ft == cost
    from combat.swimming import speed
    actor = session.engine.state.actors[WALKER]
    assert speed(session.engine, actor) == (session.engine._effective_speed(actor) if owned else 0)
    cold(combat, tmp_path, mid)


def test_breath_clock_runs_out_after_its_last_complete_turn(tmp_path):
    from combat.breath_clock import CLOCK
    def prepare(bundles):
        b = next(b for b in bundles if b['actor_id'] == OWNER)
        b['actor_template']['proficiency_bonus'] = 1
        for action in b['action_catalog']:
            typed = action.get('parameters', {}).get('typed', {})
            if any(e.get('type') == 'athletics_breath' for e in typed.get('effects', ())):
                typed['numbers']['con_mod'] = -4
    g = fixture(tmp_path, [LUNGS], seed='MGR-BREATH-EXPIRY', bundle_transform=prepare)
    g['commit'](candidate_id(g['menu'](), 'hold your breath'))
    for _ in range(5):
        g['to_owner']()
        g['commit'](g['menu']()['end_turn'])
    actor = g['reload_owner']()
    assert not any(c.condition_id == CLOCK for c in actor.conditions.values())
    assert any(e.payload.get('breath_expired') == 1 for e in g['stored_engine']().events)
    reload_identical(g['combat'], g['match_id'], tmp_path)


def test_water_keeps_full_land_swim_options_with_a_slower_fly_speed(tmp_path):
    from combat.tabletop import normalize_map, to_battlefield
    from combat.gate2_runtime_models import CandidateKind
    from tests.worker2_support import fixture as make, OWNER as WALKER, FOE as ENEMY, ALLY, settle, reload
    arena = to_battlefield(normalize_map({'display_name': 'Mixed movement water yard',
        'width_squares': 12, 'height_squares': 8, 'terrain': [{'type': 'WATER', 'cells': [[4, 3], [5, 3]]}]}))
    def prepare(bundles):
        next(b for b in bundles if b['actor_id'] == WALKER)['actor_template']['fly_speed_ft'] = 15
    combat, table, mid = make(tmp_path, [SHARK], battlefield=arena, bundle_transform=prepare,
        positions={WALKER: {'x': 3, 'y': 3}, ENEMY: {'x': 9, 'y': 6}, ALLY: {'x': 10, 'y': 6}},
        seed='MGR-WATER-MIXED-MODES')
    engine = combat._load_session(mid).engine
    c = next(c for c in engine.legal_candidates() if c.kind == CandidateKind.MOVE and c.destination
             and (c.destination.x, c.destination.y, c.destination.z) == (9, 3, 0)
             and c.metadata.get('movement_mode', 'walk') == 'walk')
    assert c.movement_cost_ft == 30
    settle(table, mid, c.candidate_id)
    assert reload(tmp_path, mid).state.actors[WALKER].position.x == 9


def test_sparrow_half_base_land_speed_at_table(tmp_path):
    g = fixture(tmp_path, [SPARROW], seed='MGR-T16-SPARROW')
    engine = g['stored_engine']()
    actor = engine.state.actors[OWNER]
    assert profile(engine, actor).speed_ft == actor.speed_ft // 2
    destination = next(m for m in g['menu']()['moves'] if m['destination'].get('z', 0) > 0)
    g['commit'](destination['candidate_id'])
    assert g['stored_engine']().state.actors[OWNER].position.z > 0
    reload_identical(g['combat'], g['match_id'], tmp_path)
