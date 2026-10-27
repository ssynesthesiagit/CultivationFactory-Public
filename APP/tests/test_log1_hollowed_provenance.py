"""Void's printed Hollowed companions are one failed-save outcome, not extra saves.

Source: Sphere Compendium, Core Void Rules / Hollowed. Nullifying Strike's
successful save grants only temporary-HP denial. Synthetic table inputs only.
"""
import json

import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.test_lock2_persistence import act
from tests.test_p4_void_needle import FOE, PLAYER, cast


@pytest.mark.parametrize("failed", [True, False])
def test_hollowed_companions_share_provenance_and_expire_after_reload(tmp_path, monkeypatch, failed):
    """codex/lock7-cost-lock 2cd537f7 (L7cost2.review.md) now applies
    the separately chosen Cost Lock; Hollowed still owns only its companions.
    """
    # Cost Lock avoids Void Needle's independent Temporary HP/Invisible riders.
    boundary, _ = cast(tmp_path, monkeypatch, "Cost Lock", "Hollowed", failed=failed)
    combat = CombatService(ROOT, tmp_path)
    manifest = next(combat.matches_root.glob("*/Manifest.json"))
    mid = json.loads(manifest.read_text())["match_id"]
    loaded = combat._load_session(mid)
    target = loaded.engine.state.actors[FOE]
    conditions = {c.condition_id.removeprefix("condition:typed."): c
                  for c in target.conditions.values()}
    lock = conditions.pop("void_cost_lock")
    assert lock.source_actor_id == PLAYER
    assert lock.source_definition_id != "passive:TAL_VOID_NULLIFYING_STRIKE"
    assert lock.expires_on == "START_OF_SOURCE_NEXT_TURN"
    expected = {"hollowed", "no_temp_hp", "no_invisible"} if failed else {"no_temp_hp"}
    assert set(conditions) == expected
    saves = [e for e in boundary["events"] if e["event_type"] == "SAVE_ROLLED"]
    assert len(saves) == 1
    source = saves[0]["source_definition_id"]
    assert source == "passive:TAL_VOID_NULLIFYING_STRIKE"
    applied = [e for e in boundary["events"] if e["event_type"] == "CONDITION_APPLIED"
               and e["payload"]["condition_id"] != "condition:typed.void_cost_lock"]
    lock_events = [e for e in boundary["events"] if e["event_type"] == "CONDITION_APPLIED"
                   and e["payload"]["condition_id"] == "condition:typed.void_cost_lock"]
    assert len(lock_events) == 1 and lock_events[0]["source_definition_id"] == lock.source_definition_id
    assert len(applied) == len(expected)
    assert all(e["source_definition_id"] == source for e in applied)
    for name, condition in conditions.items():
        assert condition.source_definition_id == source
        assert condition.source_actor_id == PLAYER
        assert condition.expires_on == "START_OF_SOURCE_NEXT_TURN"
        if failed and name != "hollowed":
            assert condition.data["companion_of"] == "hollowed"
        else:
            assert "companion_of" not in condition.data
    summaries = [e["summary"] for e in boundary["feed"] if e["event_type"] == "CONDITION_APPLIED"
                 and e["source_definition_id"] == source]
    if failed:
        assert any("Hollowed: cannot gain temporary hit points" in s for s in summaries)
        assert any("Hollowed: cannot become Invisible from ordinary temporary effects" in s for s in summaries)
    else:
        assert all("Hollowed" not in s for s in summaries)
    table = TabletopService(combat, tmp_path)
    assert act(table, mid, "end")["status"] == "COMMITTED"
    combat = CombatService(ROOT, tmp_path)
    loaded = combat._load_session(mid)
    assert loaded.engine.state.current_actor_id == FOE
    assert {c.condition_id.removeprefix("condition:typed.")
            for c in loaded.engine.state.actors[FOE].conditions.values()} == expected | {"void_cost_lock"}
    assert act(TabletopService(combat, tmp_path), mid, "end")["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.current_actor_id == PLAYER
    assert not loaded.engine.state.actors[FOE].conditions
    assert loaded.mechanical.replay()["status"] == "PASS"
