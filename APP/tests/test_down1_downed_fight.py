"""DOWNED1: a downed fighter finishes its death saves and the fight ends.

Table-level regressions through the real CombatService and TabletopService:
an AI-controlled factory character rolls at the start of its dying turns, three
failures kill it (and end the fight when it was the last of its side), three
successes make it Stable, and damage at 0 Hit Points adds a failure. Every case
is read back from a cold CombatService so the counts survive a table commit.

Local-only: the factory table fixture (tests/test_sol113_dying_table.py) needs
the private authority files and repository history, like test_sol113 itself.
"""
import pytest

from combat.ext import life_state
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from tests.test_sol113_dying_table import ROOT, advance, fight, until_turn


def cold(tmp_path, mid):
    return CombatService(ROOT, tmp_path)._load_session(mid)


def test_ai_controlled_downed_factory_character_rolls_at_the_start_of_its_turn(tmp_path, monkeypatch):
    service, table, mid, target_id = fight(tmp_path, monkeypatch, rolls=(12, 12, 12))
    until_turn(service, table, mid, target_id, 2)
    service.set_controller_mode(mid, actor_id=target_id, controller_mode="LOCAL_AUTO")
    state = until_turn(service, table, mid, target_id, 3)
    loaded = cold(tmp_path, mid)
    actor = loaded.engine.state.actors[target_id]
    check = next(e for e in loaded.engine.events
                 if e.event_type == "CHECK_ROLLED" and e.source_definition_id == "system:death_save"
                 and e.actor_id == target_id)
    assert check.payload["actor"]["natural_result"] == 12
    assert check.payload["success"] is True
    assert life_state.encounter_death_saves(actor) == {"ok": 1, "bad": 0}
    row = next(a for a in state["presentation"]["actors"] if a["entity_id"] == target_id)
    assert row["death_saves"] == {"ok": 1, "bad": 0}
    assert any("death saving throw 1d20 [12]" in e["summary"] for e in table.events(mid, 0)["events"])
    assert loaded.verify()["status"] == "PASS"


def test_last_combatant_with_no_way_back_is_defeated_at_zero_hp(tmp_path, monkeypatch):
    # Owner 2026-10-21: a dying creature with no in-combat way back is defeated;
    # its side does not wait for death saving throws (a natural 20 is not a way
    # back, because an enemy would finish it off).
    service, table, mid, target_id = fight(tmp_path, monkeypatch, defeated_side=True)
    until_turn(service, table, mid, target_id, 2)
    if cold(tmp_path, mid).engine.state.terminal_result is None:
        advance(table, mid)  # end the doomed fighter's turn; the boundary decides
    loaded = cold(tmp_path, mid)
    actor = loaded.engine.state.actors[target_id]
    assert actor.active and actor.life_state == "DYING"
    result = loaded.engine.state.terminal_result
    assert result is not None and result.kind.value == "VICTORY"
    assert result.winning_team_id == loaded.engine.state.actors[FACTORY_ACTOR_PREFIX + "sol113-right"].team_id
    saves = [e for e in loaded.engine.events
             if e.event_type == "CHECK_ROLLED" and e.source_definition_id == "system:death_save"
             and e.actor_id == target_id]
    assert saves == []
    assert not any(e.event_type == "ENTITY_DEFEATED" and e.actor_id == target_id for e in loaded.engine.events)
    assert loaded.verify()["status"] == "PASS"


def test_damage_at_zero_adds_a_failure_for_the_last_combatant(tmp_path, monkeypatch):
    service, table, mid, target_id = fight(tmp_path, monkeypatch, defeated_side=True, followup="damage",
                                           rolls=(12, 12, 12))
    # The target owns an in-combat way back, so its side is not defeated while
    # the follow-up hit and its death-save failure are recorded.
    from tests.test_lock_choices import install
    install(monkeypatch, "self_recovery", lambda engine, actor: True if actor.entity_id == target_id else None)
    for _ in range(12):
        engine = cold(tmp_path, mid).engine
        if any(e.source_definition_id == "test:followup" for e in engine.events):
            break
        advance(table, mid)
    loaded = cold(tmp_path, mid)
    actor = loaded.engine.state.actors[target_id]
    assert actor.life_state == "DYING"
    assert life_state.encounter_death_saves(actor)["bad"] == 1
    assert any(e.event_type == "PASSIVE_TRIGGERED"
               and (e.payload or {}).get("log", "").endswith("a failed death save (1/3).")
               for e in loaded.engine.events)
    assert loaded.verify()["status"] == "PASS"
