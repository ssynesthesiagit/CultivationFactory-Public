"""Appraise reach through acquired Poison base rows and the native table."""
import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.r1i_service_support import OWNER, FOE, SECOND, candidate, fixture

APPRAISE = "POISON_BASE_APPRAISE_THE_VENOM"


def appraisal_options(table, mid):
    return [o for g in table.state(mid)["menu"]["actions"]
            if g["label"] == "Appraise the Venom" for o in g["options"]]


@pytest.mark.parametrize("feet,offered", [(5, True), (30, True), (35, False)])
def test_acquired_base_reach_and_cold_table_commit(tmp_path, feet, offered):
    # Learning a Poison talent grants the sphere's base rows through the real
    # compiler. No action definitions, conditions or fact receipts are injected.
    combat, table, mid, _, commit = fixture(tmp_path,
        ["tianxia.talent.poison.antidote_art"], wide=True,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 3 + feet // 5, "y": 6},
                   SECOND: {"x": 15, "y": 12}}, seed=f"APPRAISE-{feet}")
    options = appraisal_options(table, mid)
    assert any(FOE in o.get("target_ids", []) for o in options) is offered
    session = combat._load_session(mid)
    action = next(a for a in session.engine.action_catalog.values()
                  if a.owner_id == OWNER and a.display_name == "Appraise the Venom")
    assert action.range_ft == 30
    if not offered:
        return
    before = dict(session.engine.state.actors[OWNER].resources)
    commit(candidate(table, mid, "Appraise the Venom", FOE))
    cold = CombatService(combat.source_root, tmp_path)
    fresh = cold._load_session(mid)
    assert fresh.engine.state.actors[OWNER].resources == before
    assert next(a for a in fresh.engine.action_catalog.values()
                if a.owner_id == OWNER and a.display_name == "Appraise the Venom").range_ft == 30
    # Use a fresh table as well as a cold engine load, without synthesizing state.
    assert TabletopService(cold, tmp_path).state(mid)["match_id"] == mid
    assert fresh.mechanical.replay()["status"] == "PASS"


def test_no_poison_sphere_does_not_gain_appraisal(tmp_path):
    _, table, mid, _, _ = fixture(tmp_path, [], wide=True, seed="APPRAISE-NONOWNER")
    assert not appraisal_options(table, mid)


@pytest.mark.parametrize("feet,offered", [(5, True), (30, False)])
def test_native_blindfold_preserves_touch_but_not_longer_reach(tmp_path, feet, offered):
    combat, table, mid, _, commit = fixture(tmp_path,
        ["tianxia.talent.poison.antidote_art", "TAL_DARK_BLINDFOLD"],
        owner_dc=100, wide=True,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 3 + feet // 5, "y": 6},
                   SECOND: {"x": 15, "y": 12}}, seed=f"APPRAISE-BLINDFOLD-{feet}")
    commit(candidate(table, mid, "Meld: Blindfold", OWNER))
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    cold = CombatService(combat.source_root, tmp_path)
    actor = cold._load_session(mid).engine.state.actors[OWNER]
    assert any(c.condition_id == "condition:typed.blinded" for c in actor.conditions.values())
    table = TabletopService(cold, tmp_path)
    assert any(FOE in o.get("target_ids", []) for o in appraisal_options(table, mid)) is offered
