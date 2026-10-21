"""Exhaustion defeat commits as a terminal table result and survives reload."""

from combat.ext.forged_exhaustion import set_level
from combat.gate5_service import CombatService
from tests.test_tabletop_hunt6 import HOLD, RIGHT, ROOT, act, on_hold, table_fight


def test_last_opponent_exhaustion_death_commits_and_reloads(monkeypatch, tmp_path):
    _, table, match_id = table_fight(tmp_path, [], ally_talents=[])

    def exhaust_last_opponent(engine):
        set_level(engine, engine.state.actors[RIGHT], 6, "test:exhaustion")

    on_hold(monkeypatch, exhaust_last_opponent)
    result = act(table, match_id, HOLD)
    assert result["status"] == "COMMITTED"

    reloaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert not reloaded.engine.state.actors[RIGHT].active
    assert reloaded.engine.state.terminal_result is not None
    assert reloaded.engine.state.terminal_result.kind.value == "VICTORY"
    assert reloaded.mechanical.replay()["status"] == "PASS"

    reloaded_table = CombatService(ROOT, tmp_path)
    from combat.tabletop_service import TabletopService

    assert TabletopService(reloaded_table, tmp_path).state(match_id)["presentation"]["terminal"]
