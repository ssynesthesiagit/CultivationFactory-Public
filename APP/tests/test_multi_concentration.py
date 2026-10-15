"""Unlimited new-bundle admission and the explicitly configured legacy CL ceiling.

A failed save ends only the newest; legacy capped overflow ends the oldest.
combat/concentration.py, gate2_engine._start_concentration/_end_concentration.
"""

import pytest

from combat import concentration, senses
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_auto_docket import DARK, ME, ROOT, _my_turn, _sheet


@pytest.fixture
def capped_capacity(monkeypatch):
    """Retain the old overflow regressions for the explicitly configured legacy mode."""
    monkeypatch.setitem(concentration.rules(), "capacity", "cultivation_level")


def _engine(cl: int, talents=()):
    sheet = _sheet([*DARK, "TAL_DARK_DARKVISION", "TAL_DARK_CLEARSIGHT", *talents])
    sheet = {**sheet, "identity": {**sheet["identity"], "cultivation_level": cl}}
    engine = Gate4ControllerEngine(ROOT, match_seed="CONC", typed_bundles=(compile_character(sheet, actor_id=ME),),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 10, "y": 6}}})
    _my_turn(engine)
    return engine, engine.state.actors[ME]


@pytest.mark.parametrize("cl, holds", [(1, 1), (4, 1), (5, 2), (9, 2), (10, 3), (14, 3), (15, 4), (19, 4), (20, 5)])
def test_how_many_by_cultivation_level(cl, holds, capped_capacity):
    assert concentration.limit_for_cl(cl) == holds


def test_at_cl10_three_are_held_and_a_fourth_ends_the_oldest(capped_capacity):
    engine, me = _engine(10)
    for source in ("action:a", "action:b", "action:c"):
        engine._start_concentration(me, source)
    assert concentration.sources(me) == ["action:a", "action:b", "action:c"] and me.concentration.source_definition_id == "action:c"
    engine._start_concentration(me, "action:d")
    assert concentration.sources(me) == ["action:b", "action:c", "action:d"]  # the one held longest ended
    assert any(e.event_type == "CONCENTRATION_ENDED" and e.source_definition_id == "action:a"
               and (e.payload or {}).get("held") is True and (e.payload or {}).get("reason") == "REPLACED"
               for e in engine.events)
    assert me.concentration.source_definition_id == "action:d"


def test_a_failed_save_ends_only_the_most_recent_and_the_next_carries_on():
    engine, me = _engine(5)
    engine._start_concentration(me, "action:a")
    engine._start_concentration(me, "action:b")
    engine._end_concentration(me, "FAILED_DAMAGE_CHECK")  # what _concentration_check does on a failure
    assert me.concentration.source_definition_id == "action:a" and concentration.held(me) == []
    assert concentration.concentrating_on(me, "action:a") and not concentration.concentrating_on(me, "action:b")


def test_defeat_ends_every_one_and_cl1_still_holds_one(capped_capacity):
    engine, me = _engine(10)
    engine._start_concentration(me, "action:a")
    engine._start_concentration(me, "action:b")
    engine._end_concentration(me, "ENTITY_DEFEATED")
    assert concentration.sources(me) == []
    engine, me = _engine(1)
    engine._start_concentration(me, "action:a")
    engine._start_concentration(me, "action:b")
    assert concentration.sources(me) == ["action:b"]  # one at a time below CL5, as before


def test_a_meld_on_concentration_lasts_while_it_is_held(capped_capacity):
    engine, me = _engine(5)
    meld = next(a for a in engine.action_catalog.values() if a.display_name == "Meld: Darkvision" and a.owner_id == ME)
    engine._start_concentration(me, meld.source_definition_id)
    engine._apply_condition(me, senses.MELD, meld.source_definition_id, ME, expires_on="UNTIL_REMOVED",
                            data={"talent": "TAL_DARK_DARKVISION", "concentration": True, "source": meld.source_definition_id})
    engine._start_concentration(me, "action:another")  # the Meld is held now, not ended
    assert "TAL_DARK_DARKVISION" in senses.melds_of(engine, me)
    engine._start_concentration(me, "action:a third")  # at CL5 two are held: the Meld, the oldest, ends
    assert "TAL_DARK_DARKVISION" not in senses.melds_of(engine, me)


@pytest.mark.parametrize("cl", [1, 4, 5, 10, 15, 20])
@pytest.mark.parametrize("same_technique", [False, True])
def test_unlimited_admissions_keep_every_copy(cl, same_technique):
    engine, me = _engine(cl)
    assert concentration.limit_for_cl(cl) is None
    expected = ["action:same" if same_technique else f"action:{i}" for i in range(32)]
    for source in expected:
        assert concentration.free_slot(engine, me)
        engine._start_concentration(me, source)
    assert concentration.sources(me) == expected
    assert len(concentration.held(me)) == 31
    assert not any(e.event_type == "CONCENTRATION_ENDED" for e in engine.events)
    engine._end_concentration(me, "FAILED_DAMAGE_CHECK")
    assert concentration.sources(me) == expected[:-1]
    engine._end_concentration(me, "ENTITY_DEFEATED")
    assert concentration.sources(me) == []


def test_uncompiled_legacy_creature_retains_its_saved_contract():
    engine, _me = _engine(1)
    # A genuinely legacy fight predates sealed rules for every participant.
    for bundle in engine.typed_bundle_documents:
        bundle.pop("concentration_rules", None)
    actor = engine.state.actors[AN]
    for i in range(8):
        engine._start_concentration(actor, f"action:{i}")
    assert concentration.sources(actor) == ["action:7"]


def test_old_bundle_without_capacity_snapshot_keeps_cl_limit():
    engine, me = _engine(5)
    for bundle in engine.typed_bundle_documents:
        bundle.pop("concentration_rules", None)
    for i in range(8):
        engine._start_concentration(me, f"action:{i}")
    assert concentration.sources(me) == ["action:6", "action:7"]


def test_companion_uses_its_owners_capacity_snapshot():
    engine, me = _engine(1)
    companion = engine.state.actors[AN]
    companion.owner_id = me.entity_id
    for i in range(8):
        engine._start_concentration(companion, f"action:{i}")
    assert len(concentration.sources(companion)) == 8


def test_legacy_companion_does_not_inherit_its_owners_old_cl_ceiling():
    engine, me = _engine(20)
    for bundle in engine.typed_bundle_documents:
        bundle.pop("concentration_rules", None)
    companion = engine.state.actors[AN]
    companion.owner_id = me.entity_id
    for i in range(8):
        engine._start_concentration(companion, f"action:{i}")
    assert concentration.sources(companion) == ["action:7"]


def test_unlimited_prefight_allowance_obeys_the_menus_own_bound():
    assert concentration.selection_limit(1, 2) == 2
    assert concentration.selection_limit(20, 7) == 7
