"""Brutal Momentum (Tianxia Insight): after a qualifying
completed event, the user may step up to 10 feet without
provoking Opportunity Attacks.

The printed trigger names six completed events. Two are
driven here through the real table, because each is the
one a reader would try first:

* "reduce a hostile creature to 0 Hit Points" -- a
  strike that drops a frail hostile to 0 Hit Points.
* "knock a hostile creature Prone" -- a Shove that
  drops a hostile Prone, whose reach the step then
  leaves without an Opportunity Attack.

The other triggers (pushing a hostile 10 feet, breaking
an object or barrier, escaping a Grapple or Restrained
effect) are read from the same receipts the engine
already posts, so they need no seam of their own.
"""
from types import SimpleNamespace

import pytest

from combat.ext.brutal_momentum import INSIGHT
from combat.ext import brutal_momentum
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import (
    candidate, fixture, FOE, OWNER, reload, settle,
)


def kit(*items):
    return {'starting_kit': {'items': [
        {'item_id': 'tianxia.mortal.weapon.' + item,
         'name': item, 'quantity': 1} for item in items]}}


def _felled_foe():
    """A hostile so frail that any hit drops it to 0 Hit Points."""
    foe = sheet([], cl=15)
    foe['ability_scores_and_statistics']['armor_class']['base_value'] = 1
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 1
    return foe


def _strong_owner():
    """The owner: strong enough that a Shove always lands."""
    document = sheet([], cl=15, score=30)
    document.setdefault('spheres_and_talents', {})[
        'cultivation_insight_record_ids'] = [INSIGHT]
    return compile_character(document, actor_id=OWNER,
                             reaction_plan={'ask': True})


def _weak_foe():
    """A hostile too weak to save against the Shove."""
    return sheet([], cl=15, score=3)


def test_a_strike_that_fells_a_hostile_offers_the_step(tmp_path):
    # "reduce a hostile creature to 0 Hit Points": the
    # strike that drops a hostile creature to 0 Hit
    # Points offers the step, and the owner takes it.
    combat, table, mid = fixture(
        tmp_path, [], owner_insights=[INSIGHT],
        foe_sheet=_felled_foe(), foe_position={'x': 2, 'y': 6})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert brutal_momentum.owned(engine, owner)
    start = (owner.position.x, owner.position.y)
    row = candidate(combat, mid, 'Unarmed Strike', target=FOE)
    settle(table, mid, row.candidate_id)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    foe = engine.state.actors[FOE]
    assert foe.current_hp == 0
    assert (owner.position.x, owner.position.y) != start


@pytest.mark.parametrize("action", ["Unarmed Strike", "Shove: Prone"])
def test_non_owner_gets_no_brutal_momentum_after_a_qualifying_event(tmp_path, action):
    # Global event receipts also include actors without the Insight. Neither a
    # kill nor a successful Shove may grant them its free movement or prompt.
    document = sheet([], cl=15, score=30)
    bundle = compile_character(document, actor_id=OWNER, reaction_plan={'ask': True})
    combat, table, mid = fixture(
        tmp_path, [], owner_bundle=bundle,
        foe_sheet=_felled_foe() if action == "Unarmed Strike" else _weak_foe(),
        foe_position={'x': 2, 'y': 6})
    start = reload(tmp_path, mid).state.actors[OWNER].position
    row = candidate(combat, mid, action, target=FOE)
    prompts = settle(table, mid, row.candidate_id)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert not brutal_momentum.owned(engine, owner)
    if action == "Unarmed Strike":
        assert foe.current_hp == 0
    else:
        assert any(c.condition_id in brutal_momentum.PRONE for c in foe.conditions.values())
    assert owner.position == start
    assert not owner.turn_flags.get(brutal_momentum.TURN_FLAG)
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.brutal_momentum'
                   for p in prompts)


def test_the_step_leaves_a_hostiles_reach_without_an_opportunity_attack(tmp_path):
    # "move up to 10 feet without provoking Opportunity
    # Attacks": the step leaves the hostile's reach -- a
    # move that leaves reach normally provokes an
    # Opportunity Attack, because the hostile is armed --
    # and does not.
    combat, table, mid = fixture(
        tmp_path, [], owner_bundle=_strong_owner(),
        foe_sheet=_weak_foe(), foe_kit=kit('duan_jian'),
        foe_position={'x': 2, 'y': 6})
    engine = reload(tmp_path, mid)
    row = candidate(combat, mid, 'Shove: Prone', target=FOE)
    # The Shove knocks the hostile Prone, which offers the
    # step; the step is taken to a square that leaves the
    # hostile's reach.
    prompts = settle(
        table, mid, row.candidate_id,
        picks={'choice:needle.brutal_momentum': 'step:3,8,0'})
    # Only the step was asked: leaving the hostile's reach
    # raised no Opportunity Attack of its own.
    assert [p['context']['reaction_source_id']
            for p in prompts] == ['choice:needle.brutal_momentum']
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    foe = engine.state.actors[FOE]
    assert (owner.position.x, owner.position.y) == (3, 8)
    assert foe.current_hp > 0


def test_object_trigger_requires_a_recorded_object_or_scene_objective(monkeypatch):
    # The printed trigger requires a complete AC/Hit Point record or an
    # object controlling a current scene objective; breaking a trivial map
    # decoration alone must not offer the once-per-turn movement.
    actor = SimpleNamespace(entity_id=OWNER)
    engine = SimpleNamespace(state=SimpleNamespace(actors={OWNER: actor}))
    offered = []
    monkeypatch.setattr(brutal_momentum, "offer", lambda *args: offered.append(args))
    def event(record):
        brutal_momentum.qualifying(engine, "OBJECT_UPDATED", {
            "actor_id": OWNER, "target_ids": ("object:fixture",),
            "payload": {"object": record}})

    event({"object_id": "object:fixture", "destroyed": True, "current_hp": 0})
    assert not offered
    event({"object_id": "object:fixture", "destroyed": True,
           "ac": 12, "current_hp": 0, "maximum_hp": 10})
    assert len(offered) == 1
    event({"object_id": "object:objective", "destroyed": True,
           "current_hp": 0, "component": {"controls_current_scene_objective": 1}})
    assert len(offered) == 2
