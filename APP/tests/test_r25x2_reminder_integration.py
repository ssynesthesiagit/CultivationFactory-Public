"""Shared reminder policy through a committed table and a fresh service reload."""
from tests.hunt15_support import LEFT, fight, act, turn
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT


def fresh_table(tmp_path):
    combat = CombatService(ROOT, tmp_path)
    return combat, TabletopService(combat, tmp_path)


def test_printed_gm_rule_and_complete_reminder_survive_player_cleanup_and_reload(tmp_path):
    # Synthetic presentation evidence exercises the shared builder without granting
    # any new ability or changing the engine's execution of the printed rules.
    first = "Make a saving throw against a DC set by the GM; spend 1 CP."
    last = "The final printed exception still applies."
    raw = "#### Extra effect\n" + first + " " + "Keep the whole printed instruction. " * 25 + last
    note = "Simplified from the printed triggers; coordinator audit 2026-09-28"
    combat, table, mid = fight(tmp_path, ["POISON_BASE_DELIVER_THE_DOSE"],
        effects=[{"type": "rider", "evidence": raw}, {"type": "rider", "evidence": note}])
    turn(table, mid, LEFT)
    act(table, mid, "Test setup")

    def check(service_table):
        rows = [r["summary"] for r in service_table.events(mid, 0)["events"] if r["event_type"] == "GM_RIDER"]
        assert len(rows) == 1
        assert "against a DC set by the GM" in rows[0]
        assert " CP" not in rows[0]
        assert last in rows[0]
        assert "coordinator" not in rows[0]
        assert "the GM must resolve this additional effect" not in rows[0]
        assert "recorded outcomes have not already applied" in rows[0]

    check(table)
    fresh, loaded_table = fresh_table(tmp_path)
    check(loaded_table)
    engine = fresh._load_session(mid).engine
    assert [e.payload["rider"] for e in engine.events if e.event_type == "GM_RIDER"] == [raw, note]
    assert fresh._load_session(mid).verify()["status"] == "PASS"


def test_workshop_notes_drop_without_losing_the_adjacent_rule_after_reload(tmp_path):
    printed = "Until the end of your next turn, the target cannot gain temporary cultivation points."
    raw = printed + " (blocked: temporary cultivation points provenance/benefit hook). / " + (
        "GM: once-per-turn discount requires a pre-cost seam in the locked engine. / The GM applies it.")
    combat, table, mid = fight(tmp_path, ["POISON_BASE_DELIVER_THE_DOSE"],
        effects=[{"type": "rider", "evidence": raw}])
    turn(table, mid, LEFT)
    act(table, mid, "Test setup")
    for service_table in (table, fresh_table(tmp_path)[1]):
        rows = [r["summary"] for r in service_table.events(mid, 0)["events"] if r["event_type"] == "GM_RIDER"]
        assert len(rows) == 1
        assert printed in rows[0]
        assert not any(word in rows[0] for word in ("hook", "engine", "seam", "provenance"))
