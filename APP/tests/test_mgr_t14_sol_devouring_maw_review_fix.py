"""Regression tests for the Sol review of the Heaven-Devouring Maw body lane (review 024216).

Each test fails on the pre-fix code:
- timed Temporary HP keeps its printed clock with no Feast owner in the fight (Blocking 1);
- a CP-spent activation that dealt only non-storable types stores Force, not nothing (Optional 1);
- stale attack-response scratch is swept once no damage context is active (Optional 5);
- a bad resonant medium reaching to_battlefield without the editor save path is a map error (Optional 4).
"""
import types

import pytest

from combat.ext.devouring_maw import _devour_cp_types, _sweep_attack_responses
from combat.ext.temp_hp_grants import held_grant, lifetime_for
from tests.test_mgr_maw_native import acquired, scenario, play  # noqa: F401 (pytest fixture)
from tests.worker2_support import FOE, reload, settle, turn
from combat.tabletop import TabletopError, TabletopMapStore, to_battlefield


def test_timed_temp_hp_keeps_its_printed_clock_without_a_feast_owner(tmp_path, acquired):
    # cl=10 is below the Feast tier, so no actor in this fight owns Feast upon Protection.
    combat, table, mid = scenario(tmp_path, acquired, cl=10, foe_talents=['HUNGER_BASE_DIGESTIVE_MANTLE'],
                                  foe_satiety=1, seed='MGR-MAW-NATIVE-2')
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, FOE)
    play(combat, table, mid, 'Digestive Mantle: Thick Hide')
    after = reload(tmp_path, mid)
    grant = held_grant(after.events, FOE)
    assert grant is not None, 'the real Mantle must grant Temporary HP'
    assert lifetime_for(after.state.actors[FOE], grant[2]) is not None, \
        'a timed grant must carry its printed expiry even when no Maw Feast owner is present'


def test_devour_cp_type_falls_back_to_force_when_dealt_types_are_not_storable():
    # A mundane Bludgeoning strike: the physical type is not storable, so the printed "else Force" applies.
    assert _devour_cp_types(['BLUDGEONING'], {}) == ['FORCE']
    assert _devour_cp_types([], {}) == ['FORCE']
    assert _devour_cp_types(['FIRE'], {}) == ['FIRE']
    assert _devour_cp_types(['BLUDGEONING'], {'supernatural': True}) == ['BLUDGEONING']


def test_stale_attack_responses_are_swept_when_no_damage_context_is_active():
    engine = types.SimpleNamespace(damage_context=lambda: None)
    engine.__dict__['_maw_attack_responses'] = {'attacker:target:roll': {}}
    _sweep_attack_responses(engine)
    assert '_maw_attack_responses' not in engine.__dict__


def test_attack_responses_survive_while_their_damage_context_is_active():
    engine = types.SimpleNamespace(damage_context=lambda: object())
    engine.__dict__['_maw_attack_responses'] = {'attacker:target:roll': {}}
    _sweep_attack_responses(engine)
    assert engine.__dict__['_maw_attack_responses'] == {'attacker:target:roll': {}}


def test_bad_resonant_media_is_a_map_error_on_the_battlefield_path(tmp_path):
    store = TabletopMapStore(tmp_path / 'maps')
    store.save({'map_id': 'bad-media-test', 'display_name': 'Bad media', 'width_squares': 20,
                'height_squares': 14, 'resonant_media': []})
    document = store.get('bad-media-test')
    document['resonant_media'] = [{'id': 'gas', 'material': 'gas', 'cells': [{'x': 1, 'y': 1, 'z': 0}]}]
    with pytest.raises(TabletopError) as caught:
        to_battlefield(document)
    assert caught.value.code == 'MAP_RESONANCE_INVALID'
