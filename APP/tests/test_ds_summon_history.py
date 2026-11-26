"""Recorded summon/passive outcomes use names and actual amounts."""
from combat.history_feed import format_history_feed
from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, ALLY, HOLD
from tests.test_lock2_persistence import act
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService


def test_recorded_summon_and_save_bonus_text():
    events = [
        {"event_type": "SUMMON_APPEARED", "payload": {"group": "living_plague"}},
        {"event_type": "SUMMONS_COMMANDED", "payload": {"group": "corpse_servant"}},
        {"event_type": "PASSIVE_TRIGGERED", "payload": {"ability": "DEX", "save_bonus": 3, "feature_id": "TAL_AIR_BREATH_BRACED_BODY"}},
    ]
    for i, event in enumerate(events):
        event.update(sequence=i + 1, actor_id="actor:mei", target_ids=["actor:mei" if i == 2 else "actor:summon"], source_definition_id=f"ability:test.{i}")
    lines = format_history_feed(events, [], pre_state=None, post_state={},
        actor_names={"actor:mei": "Mei", "actor:summon": "Corpse Servant"},
        definition_names={"ability:test.0": "Living Plague", "ability:test.1": "Command Corpse Servants",
                          "ability:test.2": "Breath-Braced Body"})
    assert [r["summary"] for r in lines] == [
        "Corpse Servant appeared, summoned by Mei with Living Plague.",
        "Mei commanded Corpse Servant with Command Corpse Servants.",
        "Mei's Breath-Braced Body: +3 to this Dexterity saving throw.",
    ]


def test_saved_summon_events_render_through_table_after_commit_and_reload(tmp_path, monkeypatch):
    combat, table, mid = table_fight(tmp_path, [], ally_talents=[])
    def record(engine):
        for kind, payload in [("SUMMON_APPEARED", {"group": "living_plague", "position": engine.state.actors[ALLY].position.model_dump(mode="json")}),
                              ("SUMMONS_COMMANDED", {"group": "corpse_servant"}),
                              ("PASSIVE_TRIGGERED", {"ability": "DEX", "save_bonus": 3})]:
            engine._append_event(kind, "ability:test", actor_id=LEFT, target_ids=(ALLY,), payload=payload)
    on_hold(monkeypatch, record)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    fresh = TabletopService(CombatService(combat.source_root, tmp_path), tmp_path)
    lines = [r["summary"] for r in fresh.events(mid, 0)["events"]
             if r["event_type"] in {"SUMMON_APPEARED", "SUMMONS_COMMANDED", "PASSIVE_TRIGGERED"}]
    assert lines == ["Ally appeared, summoned by Left with Test.", "Left commanded Ally with Test.",
                     "Left's Test: +3 to this Dexterity saving throw for Ally."]
