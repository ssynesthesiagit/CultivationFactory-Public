"""Unified capacity contracts: sealed new fights and explicit legacy fixtures."""

import pytest

from combat import concentration, factory_compiler
from combat.gate2_runtime_content import AN
from combat.gate5_service import CombatService
from tests.test_auto_docket import ROOT
from tests.test_multi_concentration import _engine


def test_builtin_sample_fight_keeps_one_slot():
    # The owner's unlimited-concentration ruling is for Factory characters. A built-in fight has no Factory bundles: its sealed
    # sample fighters keep their original one slot, so the sealed Gate 2 / Gate 5.1 replays stay byte-identical (round 18
    # reconcile; this test previously asserted the opposite, which is what broke those replays).
    engine, _ = _engine(1)
    engine.typed_bundle_documents = ()
    actor = engine.state.actors[AN]
    for i in range(7):
        engine._start_concentration(actor, f"action:{i}")
    assert concentration.sources(actor) == ["action:6"]


@pytest.mark.parametrize("same_technique", [False, True])
def test_one_damaging_hit_rolls_once_and_ends_only_newest(same_technique):
    engine, actor = _engine(1)
    expected = ["action:same" if same_technique else f"action:{i}" for i in range(7)]
    for source in expected:
        engine._start_concentration(actor, source)
    actor.saving_throws["CON"] = -100
    mark = len(engine.events)
    assert engine._commit_damage(actor, 1, "BLUDGEONING", "test:hit", AN, None, reaction_depth=0) == 1
    events = engine.events[mark:]
    assert sum(e.event_type == "SAVE_ROLLED" for e in events) == 1
    ended = [e for e in events if e.event_type == "CONCENTRATION_ENDED"]
    assert len(ended) == 1 and ended[0].payload["reason"] == "FAILED_DAMAGE_CHECK"
    assert concentration.sources(actor) == expected[:-1]


# A fighter without a Factory bundle (sample / roster opponent) keeps one slot whatever the fight's sealed rules say: the owner's
# unlimited ruling is for Factory characters (round 18 reconcile; the first case used to expect 7).
@pytest.mark.parametrize("sealed,current,count", [
    ("unlimited", "cultivation_level", 1),
    ("cultivation_level", "unlimited", 1),
])
def test_unbundled_fighter_keeps_one_slot_whatever_the_sealed_rules(monkeypatch, sealed, current, count):
    monkeypatch.setitem(concentration.rules(), "capacity", sealed)
    engine, _ = _engine(20)
    monkeypatch.setitem(concentration.rules(), "capacity", current)
    actor = engine.state.actors[AN]
    for i in range(7):
        engine._start_concentration(actor, f"action:{i}")
    assert len(concentration.sources(actor)) == count
    engine._end_concentration(actor, "FAILED_DAMAGE_CHECK")
    assert len(concentration.sources(actor)) == count - 1


@pytest.mark.parametrize("other", [None, {"capacity": "cultivation_level", "limits_by_cl": [[1, 1]]}])
def test_mixed_fight_does_not_upgrade_unbundled_legacy_actor(other):
    engine, _ = _engine(1)
    engine.typed_bundle_documents = (*engine.typed_bundle_documents,
                                    {"actor_id": "test:other", "concentration_rules": other})
    actor = engine.state.actors[AN]
    for i in range(7):
        engine._start_concentration(actor, f"action:{i}")
    assert concentration.sources(actor) == ["action:6"]


@pytest.mark.parametrize("sealed,current,maximum", [
    ("unlimited", "cultivation_level", 2),
    ("cultivation_level", "unlimited", 1),
])
def test_prefight_preview_and_admission_share_snapshot(tmp_path, monkeypatch, sealed, current, maximum):
    monkeypatch.setitem(concentration.rules(), "capacity", sealed)
    engine, _ = _engine(1)
    bundle = engine.typed_bundle_documents[0]
    monkeypatch.setitem(concentration.rules(), "capacity", current)
    combat = CombatService(ROOT, tmp_path)
    monkeypatch.setattr(combat, "_factory_owner_sheet", lambda *args: {})
    monkeypatch.setattr(factory_compiler, "compile_character", lambda *args, **kwargs: bundle)
    options = combat.factory_prefight_options("test")
    assert options["max_concentration"] == maximum
    assert concentration.selection_limit(1, options["max"], concentration.rules_for_bundle(bundle)) == maximum
