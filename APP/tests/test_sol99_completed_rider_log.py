"""Completed and mixed riders must not invite the GM to apply an effect twice."""
import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.hunt15_support import LEFT, RIGHT, act, fight, reload, turn


PARRY = "tianxia.talent.sabers.guard_cutting_parry"


def test_table_parry_spend_and_mark_are_not_reported_as_unapplied_after_reload(tmp_path, monkeypatch):
    from tests import hunt15_support

    monkeypatch.setattr(hunt15_support, "KIT", {"items": [
        {"item_id": "tianxia.mortal.weapon.dao", "name": "Dao", "quantity": 1}]})
    combat, table, mid = fight(tmp_path, right=[PARRY], seed="SOL99-PARRY")
    turn(table, mid, LEFT)
    for _ in range(8):
        state = table.state(mid)
        attacks = [g for g in state["menu"]["actions"] if g["label"].endswith(" attack")]
        assert attacks, [g["label"] for g in state["menu"]["actions"]]
        answers = []
        for _ in range(8):
            result = act(table, mid, attacks[0]["label"], answers, target_id=RIGHT)
            if result["status"] != "REACTION_REQUIRED":
                break
            prompt = result["reaction"]
            options = (prompt.get("choice") or {}).get("options") or []
            answers.append({**prompt["context"], "selection": "USE",
                            **({"option_ids": [options[0]["id"]]} if options else {})})
        assert result["status"] == "COMMITTED"
        engine = reload(combat, mid)
        riders = [e for e in engine.events if e.event_type == "GM_RIDER" and e.source_definition_id == PARRY]
        if riders:
            break
        assert act(table, mid, "end")["status"] == "COMMITTED"
        turn(table, mid, LEFT)
    assert riders, "seed must exercise the real Guard-Cutting Parry reaction"
    rider = riders[-1]
    preceding = [e for e in engine.events if e.sequence < rider.sequence and e.source_definition_id == PARRY]
    assert any(e.event_type == "RESOURCE_SPENT" for e in preceding)
    assert any(e.event_type == "CONDITION_APPLIED" for e in preceding)
    assert any("guard_pressured" in c.condition_id for c in engine.state.actors[LEFT].conditions.values())
    fresh = CombatService(combat.source_root, combat.userdata_root)
    fresh_table = TabletopService(fresh, combat.userdata_root)
    lines = [r["summary"] for r in fresh_table.events(mid, 0)["events"]
             if r["event_type"] == "GM_RIDER" and r["source_definition_id"] == PARRY]
    assert lines
    assert all("the table has not applied it" not in line for line in lines)
    assert any("Guard Pressured" in line and "spent" in line for line in lines)
    assert fresh._load_session(mid).verify()["status"] == "PASS"


def test_table_unseen_contact_announcement_is_not_an_unapplied_effect_after_reload(tmp_path, monkeypatch):
    from tests.test_hidden_targeting import LEFT as VIEWER, RIGHT as UNSEEN, hidden_fight, move_to

    combat, table, mid = hidden_fight(tmp_path, monkeypatch, move=True, left_at=(13, 11))
    move_to(table, mid, (16, 11))
    engine = reload(combat, mid)
    observer = engine.state.actors[VIEWER]
    assert engine.state.observations[observer.team_id][UNSEEN].model_dump() == {"x": 16, "y": 11}
    fresh_table = TabletopService(CombatService(combat.source_root, combat.userdata_root), combat.userdata_root)
    line = next(r["summary"] for r in fresh_table.events(mid, 0)["events"]
                if "Movement stopped on contact" in r["summary"])
    assert "You now know the occupied space" in line
    assert "the table has not applied it" not in line


@pytest.mark.parametrize("reminder", [
    pytest.param("Reflexive Stealth: the Hide attempt failed.", id="failed-check"),
    pytest.param("Wall: 4 slashing damage; 6 of 10 hit points left.", id="completed-wall-damage"),
    pytest.param("Iron Marrow: Mira stays in place after winning the check.", id="prevented-movement"),
    pytest.param("Ren acts against its Intent and suffers Contradiction.", id="completed-trigger"),
    pytest.param("The defender moved out of the attack's reach or sight; the attack misses.", id="legacy-locked-attack-miss"),
    pytest.param("The defender left the effect before the Dexterity save; it is no longer affected.", id="legacy-locked-save-cancelled"),
    pytest.param("Ren is marked. Choose one learned characteristic.", id="mixed-outcome-and-manual-choice"),
    pytest.param("Choose one learned characteristic.", id="manual-only"),
])
def test_table_legacy_unflagged_riders_keep_their_text_without_claiming_nonapplication(tmp_path, reminder):
    combat, table, mid = fight(tmp_path, effects=[{"type": "rider", "evidence": reminder}])
    turn(table, mid, LEFT)
    assert act(table, mid, "Test setup")["status"] == "COMMITTED"
    engine = reload(combat, mid)
    raw = next(e.payload for e in engine.events if e.event_type == "GM_RIDER")
    assert raw["rider"] == reminder
    assert "automated" not in raw  # old saves remain unclassified, not rewritten
    fresh_table = TabletopService(CombatService(combat.source_root, combat.userdata_root), combat.userdata_root)
    line = next(r["summary"] for r in fresh_table.events(mid, 0)["events"] if r["event_type"] == "GM_RIDER")
    assert reminder in line
    assert "Resolve only effects that the recorded outcomes have not already applied." in line
    assert "the table has not applied it" not in line
