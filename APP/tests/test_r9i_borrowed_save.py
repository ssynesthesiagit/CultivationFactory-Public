"""Borrowed Tomorrow's failed-save use survives the real table boundary."""
import pytest

from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, script
from tests.test_r9i_karma_persistence import fixture, PLAYER, FOE, BORROWED_ID, BORROWED_SPENT, act, end_turn, attack_id, settle_record_the_deed
from tests.test_tabletop_hunt6 import on_hold


@pytest.mark.parametrize("auto_turn", [False, True])
def test_failed_save_commit_reload_prevents_second_drop_rescue(tmp_path, monkeypatch, auto_turn):
    combat, table, mid = fixture(tmp_path, BORROWED_ID)
    cid = next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"]
               if g["label"] == "Hold position" for o in g["options"])

    def save(engine):
        script(engine, [2])
        engine._roll_save(engine.state.actors[PLAYER], "DEX", 16, "test:borrowed_save")

    on_hold(monkeypatch, save)
    if auto_turn:
        real = combat.controller

        class Controller:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(real, name)

        combat.controller = Controller()
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    send = lambda answers: table.auto_step(mid, 0, answers) if auto_turn else act(table, mid, cid, answers)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send([])
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert prompt["context"]["reaction_source_id"] == "reaction:typed." + BORROWED_ID
    assert send([])["reaction"] == prompt
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert send([{**prompt["context"], "selection": "USE"}])["status"] == "COMMITTED"
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    loaded = combat._load_session(mid)
    actor = loaded.engine.state.actors[PLAYER]
    assert actor.turn_flags[BORROWED_SPENT] == 1
    assert actor.resources["resource:core.qi"] == 72
    rewritten = [e for e in loaded.engine.events if e.event_type == "D20_REWRITTEN" and e.source_definition_id == BORROWED_ID]
    assert len(rewritten) == 1 and rewritten[0].payload["original"]["natural_result"] == 2
    assert loaded.mechanical.replay()["status"] == "PASS"
    if auto_turn:
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="MANUAL")
    end_turn(table, mid)
    while table.state(mid)["menu"]["actor_id"] != FOE:
        end_turn(table, mid)
    assert settle_record_the_deed(lambda answers: act(table, mid, attack_id(table, mid), answers))["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[PLAYER].current_hp == 0
    assert loaded.engine.state.actors[PLAYER].turn_flags[BORROWED_SPENT] == 1
    assert loaded.mechanical.replay()["status"] == "PASS"
