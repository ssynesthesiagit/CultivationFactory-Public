"""Regression tests for the journey host seams (Sol review F12RSC).

Each test fails without the matching host fix: spend_resource, short_rest,
before-command dispatch, check_mods initialization, GM routes, ability
modifiers, persisted source state, and the rebuilt Active Defense authority.
"""
import json

import pytest
from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.journey import JourneySession, ability_modifiers
from tests.h1_support import ROOT
from tests.test_journey_activities_native import (
    A, B, ARENA, CHECK, LEARN, PIDS, game, request, work, ledger, SECT, inst)


@pytest.fixture(scope='module')
def catalog():
    return CanonicalCatalogAuthorityService(ROOT)


def test_host_spend_resource_debits_actor_pool(tmp_path, monkeypatch, catalog):
    # F1: native consumers call session.spend_resource; the host must provide it.
    cold, jid, act, world = game(tmp_path, monkeypatch, catalog)
    state = cold().journey_state(jid)
    session = JourneySession(state)
    before = session.state['actors'][A]['resources']['resource:core.qi']
    session.spend_resource(A, 'resource:core.qi', 1, 'regression')
    assert session.state['actors'][A]['resources']['resource:core.qi'] == before - 1


def test_short_rest_is_delivered_and_counted(tmp_path, monkeypatch, catalog):
    # F1: short_rest was never implemented; restful_dream_journey.py depends on it.
    cold, jid, act, world = game(tmp_path, monkeypatch, catalog)
    before = cold().journey_state(jid)
    after = act('short_rest')
    assert after['actors'][A]['short_rests'] == 1
    assert after['seconds'] == before['seconds'] + 3600


def test_pending_check_blocks_finish(tmp_path, monkeypatch, catalog):
    # F1: finish bypassed pending player checks; journey_before_command gates it.
    cold, jid, act, world = game(tmp_path, monkeypatch, catalog)
    inst(world)
    request(world, 'history')
    act('check_start', {'scope': 'history', 'merit': 0})
    with pytest.raises(ValueError):
        act('finish')


def test_new_actors_have_initialized_check_mods(tmp_path, monkeypatch, catalog):
    # F1: journey_checks.py reads actor['check_mods']; create must initialize it.
    cold, jid, act, world = game(tmp_path, monkeypatch, catalog)
    state = cold().journey_state(jid)
    assert isinstance(state['actors'][A].get('check_mods'), dict)
    assert state['actors'][A]['check_mods'] == ability_modifiers(cold()._factory_owner_sheet(PIDS[0]))


def test_ability_modifiers_read_admitted_rows():
    # F1 helper: journey_institutions imports ability_modifiers from journey.py.
    sheet = {'ability_scores_and_statistics': {'abilities': [
        {'ability': 'INT', 'modifier': 3}, {'ability': 'WIS', 'modifier': -1}, {'ability': 'XYZ', 'modifier': 9}]}}
    assert ability_modifiers(sheet) == {'INT': 3, 'WIS': -1}


def test_gm_routes_resolve_on_service(tmp_path, monkeypatch, catalog):
    # F2: the API routes call CombatService methods that must exist and work.
    cold, jid, act, world = game(tmp_path, monkeypatch, catalog)
    for name in ('journey_world_fact', 'journey_end_scene', 'journey_verify'):
        assert callable(getattr(CombatService, name)), name
    state = cold().journey_state(jid)
    after = cold().journey_end_scene(jid, state['revision'], 'regression')
    assert after['scene_number'] == state.get('scene_number', 0) + 1


def test_world_fact_is_not_actor_writable(tmp_path, monkeypatch, catalog):
    # F2: table-owner GM commands are journaled under GM_ID; no actor may invoke them.
    cold, jid, act, world = game(tmp_path, monkeypatch, catalog)
    with pytest.raises(ValueError):
        act('world_fact', {'source': CHECK})


def test_learning_survives_finish_and_new_journey(tmp_path, monkeypatch, catalog):
    # F3: source_states must persist across journeys.
    cold, jid, act, world = game(tmp_path, monkeypatch, catalog)
    act('sect_learn', {'ability': 'WIS', 'proficiency': 'History', 'approval': ''})
    learned = ledger(cold().journey_state(jid))
    act('finish')
    state = cold().create_journey(project_ids=PIDS, arena_id=ARENA,
        positions={A: {'x': 2, 'y': 2}, B: {'x': 2, 'y': 3}}, base_paces={A: 1800, B: 1800})
    assert learned, 'learning must be recorded in the first journey'
    assert ledger(state) == learned


def test_source_projection_reaches_new_native_sheet(tmp_path, monkeypatch, catalog):
    # F3: the character_source_projection consumer must be dispatched at create.
    cold, jid, act, world = game(tmp_path, monkeypatch, catalog)
    act('sect_learn', {'ability': 'WIS', 'proficiency': 'History', 'approval': ''})
    act('finish')
    cold().create_journey(project_ids=PIDS, arena_id=ARENA,
        positions={A: {'x': 2, 'y': 2}, B: {'x': 2, 'y': 3}}, base_paces={A: 1800, B: 1800})
    projected = cold()._factory_owner_sheet(PIDS[0])
    skill = next(r for r in projected['ability_scores_and_statistics']['skills'] if r['skill'] == 'History')
    assert skill['proficiency'] == 'Proficient'


def test_active_defense_authority_uses_triggering_attack_duration():
    # F4: the generated authority must match the reviewed input (triggering_attack).
    path = ROOT / 'authority' / 'Tianxia_Typed_Mechanics_Authority_R1.json'
    doc = json.loads(path.read_text())
    mechanics = doc['mechanics']
    if isinstance(mechanics, list):
        record = next(m for m in mechanics if m.get('mechanic_id') == 'SHIELD_BASE_ACTIVE_DEFENSE')
    else:
        record = mechanics['SHIELD_BASE_ACTIVE_DEFENSE']
    effects = record['effects']
    effect = effects[0] if isinstance(effects, list) else effects
    assert effect['duration'] == 'triggering_attack'
    assert effect['flat'] == 2 and effect['type'] == 'ac_bonus'
