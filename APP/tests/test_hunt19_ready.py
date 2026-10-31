"""Two distinct treasure bows must survive table menus and Ready persistence."""
import pytest

from combat import ext
from combat.gate5_service import CombatService
from combat.prepared_actions import SOURCE, CONDITION
from tests.test_tabletop_hunt6 import table_fight, LEFT
from tests.test_lock2_persistence import act
from tests.test_carry import KIT
from tests.test_lock_choices import install


@pytest.mark.parametrize("bow", ["59dde6c6f2", "b463411f53"])
def test_collision_bows_can_each_be_readied_and_reloaded(tmp_path, monkeypatch, bow):
    # crash-40 / ready_collision: equal last 24 characters, different stable identities.
    ext.effects()
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    hooks = list(ext._HOOKS["compile_actions"])
    def collision(info):
        return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.weapon.held.{identity}_weapon_gong_jian_treasure",
            display_name=f"Treasure bow {index} attack", owner_id=info['actor_id'], economy=EconomyKind.ACTION,
            resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=150,
            parameters={"typed": {"weapon": {"damage": {"count": 1, "sides": 8}}, "range_ft": 150,
                                  "effects": [{"type": "attack", "count": 1}]}})
            for index, identity in enumerate(("59dde6c6f2", "b463411f53"), 1)]
    monkeypatch.setitem(ext._HOOKS, "compile_actions", [*hooks, collision])
    combat, table, mid = table_fight(tmp_path, ["TAL_SNIPER_INTERCEPTING_SHOT"],
                                     kit={"starting_kit": KIT}, ally_talents=[])
    state = table.state(mid)
    groups = [g for g in state["menu"]["actions"] if g["source_definition_id"].startswith(SOURCE)]
    picked = next(g for g in groups if bow in g["source_definition_id"])
    assert len({g["source_definition_id"] for g in groups}) == len(groups)
    assert act(table, mid, picked["source_definition_id"])["status"] == "COMMITTED"
    loaded = CombatService(combat.source_root, tmp_path)._load_session(mid)
    held = next(c for c in loaded.engine.state.actors[LEFT].conditions.values() if c.condition_id == CONDITION)
    assert bow in held.data["data"]["weapon"]
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_duplicate_prepared_presentation_logs_and_skips_without_mutating_table(tmp_path, monkeypatch, caplog):
    row = {"option_id": "same", "source_id": "test:ready", "label": "Test preparation", "trigger": "INTENT_ACCEPTED"}
    install(monkeypatch, "prepare_options", lambda *args: [row, row])
    combat, table, mid = table_fight(tmp_path, [], ally_talents=[])
    before = combat._load_session(mid).engine.state.event_sequence
    state = table.state(mid)
    assert sum(g["source_definition_id"] == SOURCE + ":same" for g in state["menu"]["actions"]) == 1
    assert combat._load_session(mid).engine.state.event_sequence == before
    assert "duplicate prepared option" in caplog.text
    assert act(table, mid, SOURCE)["status"] == "COMMITTED"
    assert CombatService(combat.source_root, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"
