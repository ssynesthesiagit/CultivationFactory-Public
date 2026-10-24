"""The Sword Bones Refined expressions as authored in combat/rules/feature_blocks.d/bone_perfected.json.

tests/test_bone_perfected_parent.py proves the transport with rows injected by the test; this file runs the same table
flow on the shipped rows: a Refined owner is offered the three expressions, the chosen one adds one PB to its own
conversion only, and nothing is added to the other two.
"""
import pytest

from combat.ext.foundation_conversion_bonus import conversion_bonus
from tests.test_a2_foundations4 import setup, attack_owner
from tests.worker2_support import ALLY, FOE, OWNER, candidate, reload, settle, turn

PREFIX = 'foundation.sword_bones_v0_2B.'
KINDS = ('cut', 'sheath', 'severing_clarity')


@pytest.mark.parametrize('conversion,leaf', [
    ('cut', 'refined_tempered_severance'), ('sheath', 'refined_bone_sheath_guard'),
    ('severing_clarity', 'refined_marrow_decision')])
def test_shipped_refined_expression_adds_one_pb_to_its_conversion_only(tmp_path, conversion, leaf):
    combat, table, mid = setup(tmp_path, stage='Refined', held=1, ask=True, prepare=True)
    engine = reload(tmp_path, mid)
    settings = [c for c in engine.legal_candidates() if 'conversion_expression' in c.source_definition_id]
    assert len(settings) == 3
    settle(table, mid, next(c for c in settings if c.source_definition_id.endswith(leaf)).candidate_id)
    engine = reload(tmp_path, mid)
    assert not [c for c in engine.legal_candidates() if 'conversion_expression' in c.source_definition_id]
    assert {k: conversion_bonus(engine, engine.state.actors[OWNER], k) for k in KINDS} == {k: 4 if k == conversion else 0 for k in KINDS}
    if conversion == 'cut':
        settle(table, mid, candidate(combat, mid, 'Owner hit', target=FOE).candidate_id,
               choices={'reaction:typed.' + PREFIX + 'sword_bone_cut': 'USE'})
        damage = [e for e in reload(tmp_path, mid).events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER]
        assert len(damage) == 2 and damage[-1].payload['hp_damage'] == 8
    elif conversion == 'sheath':
        turn(table, mid, ALLY)
        settle(table, mid, candidate(combat, mid, 'Friendly large damage', target=OWNER).candidate_id,
               choices={'reaction:typed.' + PREFIX + 'sheath_bone_guard': 'USE'})
        assert next(e for e in reload(tmp_path, mid).events
                    if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == ALLY).payload['hp_damage'] == 10
    else:
        turn(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, 'Prone pressure', target=OWNER).candidate_id,
               choices={'reaction:typed.' + PREFIX + 'severing_clarity': 'USE'})
        save = next(e for e in reversed(reload(tmp_path, mid).events) if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER)
        assert save.payload['modifier'] == 10


def test_a_refined_owner_without_a_choice_gets_nothing_extra(tmp_path):
    combat, table, mid = setup(tmp_path, stage='Refined', held=1, ask=True, prepare=True)
    engine = reload(tmp_path, mid)
    assert all(conversion_bonus(engine, engine.state.actors[OWNER], k) == 0 for k in KINDS)
