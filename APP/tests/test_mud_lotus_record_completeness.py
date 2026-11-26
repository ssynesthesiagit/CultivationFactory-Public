"""Mud-Lotus reviewed records carry every printed clause the engine does not run (CLOUDBASE1F9R findings 1, 2, 5).

Each test reads the committed authority file, so it fails on the branch before the record fix.
"""
import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
PRE = 'foundation.mud_lotus_dantian_v0_2A.'
AUTHORITY = APP / 'authority' / 'Tianxia_Typed_Mechanics_Authority_R1.json'
REVIEWED = APP / 'authority' / 'typed_mechanics' / 'reviewed_final.d' / 'base1_mud_lotus.json'


def _built(key):
    return json.loads(AUTHORITY.read_text())['mechanics'][PRE + key]


def _riders(key):
    return ' '.join(_built(key).get('riders') or [])


def test_refined_lotus_recovery_keeps_its_printed_no_extra_cost_rider():
    # Finding 1: main prints "This does not require an additional action, Reaction, or Lotus Dew."; the record dropped it.
    assert 'This does not require an additional action, Reaction, or Lotus Dew.' in (_built('refined_lotus_recovery').get('riders') or [])


def test_refined_lotus_recovery_lists_the_unautomated_guard_bonus_and_scene_precondition():
    # Finding 2: Mud-Lotus Guard +PB and the scene precondition lived only in prose.
    riders = _riders('refined_lotus_recovery')
    assert 'Mud-Lotus Guard spend is not added by the engine' in riders
    assert 'Scene precondition not checked by the engine' in riders


def test_witness_lists_the_triggers_the_engine_does_not_wire():
    # Finding 2: herbalism, Water, Life, Flowers, Alchemy, Protection, Disease-/Poison-treatment and Cultivation.
    riders = _riders('humble_medicine_witness')
    for trigger in ('herbalism', 'Water', 'Life', 'Flowers', 'Alchemy', 'Protection', 'Disease-treatment', 'Poison-treatment', 'Cultivation'):
        assert trigger in riders, trigger


def test_witness_lists_the_gm_minor_consequence_step():
    # Finding 2: the GM may reduce one Minor poison/disease/rot/contamination consequence by one step.
    assert 'reduce one Minor poison, disease, rot or contamination consequence by one step' in _riders('humble_medicine_witness')


def test_pond_shelter_aura_does_not_claim_an_engine_effect_it_lacks():
    # Finding 2: the shared-shelter temporary HP was typed as an effect the engine never applies.
    built = _built('refined_pond_shelter_aura')
    assert not built.get('effects')
    assert 'Not automated' in _riders('refined_pond_shelter_aura')


def test_muddy_filter_lists_the_gm_scale_ruling():
    # Finding 2: the Minor-consequence reduction is GM-ruled, and the record now says so.
    assert 'The GM rules the scale.' in _riders('refined_muddy_filter_dantian')


def test_lotus_recovery_field_lists_its_minor_hidden_injury_clause():
    # Finding 2: the Minor Hidden Injury to Strain reduction is in the reviewed record, not only the generated one.
    reviewed = json.loads(REVIEWED.read_text())['mechanics'][PRE + 'lotus_recovery_field']
    assert any('reduced to Strain instead' in rider for rider in reviewed['riders'])


def test_built_authority_matches_each_reviewed_rider_list():
    # Finding 5: the generated file must carry the reviewed riders exactly (rebuild with tools/build_typed_mechanics_authority.py).
    reviewed = json.loads(REVIEWED.read_text())['mechanics']
    for key, final in reviewed.items():
        assert _built(key.removeprefix(PRE)).get('riders') == final['riders'], key
