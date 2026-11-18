"""Mud-Lotus Refined Lotus Recovery: +PB Temporary Hit Points on one paid Lotus-Root Recovery."""
import pytest

from tests.test_a2_foundations3 import setup, use, pool
from tests.worker2_support import OWNER, ALLY, turn, reload

EXPRESSION = 'Foundation expression: Refined — Lotus Recovery'


def _recover(tmp_path, stage, *, choose):
    combat, table, mid = setup(tmp_path, 'lotus', initial=1, stage=stage)
    turn(table, mid, OWNER)
    if choose:
        use(combat, table, mid, EXPRESSION, OWNER)
    use(combat, table, mid, 'Lotus-Root Recovery', ALLY)
    return reload(tmp_path, mid)


def test_refined_expression_adds_proficiency_bonus_to_the_temporary_hit_points(tmp_path):
    engine = _recover(tmp_path, 'Refined', choose=True)
    assert engine.state.actors[ALLY].temporary_hp == 10
    assert engine.state.actors[OWNER].resources[pool('lotus')] == 0


def test_unchosen_expression_changes_nothing(tmp_path):
    engine = _recover(tmp_path, 'Refined', choose=False)
    assert engine.state.actors[ALLY].temporary_hp == 6


def test_awakened_foundation_has_no_refined_bonus(tmp_path):
    engine = _recover(tmp_path, 'Awakened', choose=False)
    assert engine.state.actors[ALLY].temporary_hp == 6
