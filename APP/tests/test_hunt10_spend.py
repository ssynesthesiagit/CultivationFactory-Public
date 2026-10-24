"""Variable reaction payment through preview, table commit and replay.

Use the explicit primary-pool fixture argument added by fix/h44-devour
(b042ed56), approved by the lead in fix/QUEUE.md (LUNA23) and integrated
with both fixture contracts in fix/R23b.report.md, Devour continuation.
"""
import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, RIGHT, HOLD
from tests.test_lock2_persistence import act

GUARD = "tianxia.path.body_refining.feature.stamina_guard"


@pytest.mark.parametrize("ai_turn", [False, True])
@pytest.mark.parametrize("amount,affordable", [(None, 4), (1, 4), (4, 4), (2, 2), (1, 1)])
@pytest.mark.parametrize("pending_damage", [2, 16])
def test_player_chooses_guard_payment(monkeypatch, tmp_path, ai_turn, amount, affordable, pending_damage):
    combat, table, mid = table_fight(tmp_path, [GUARD], ask=True, ally_talents=[], primary="Stamina")

    def damage(engine):
        target = engine.state.actors[LEFT]
        # Limit the affordable amount inside the evented accepted action.
        engine._spend_resource(target, "resource:core.stamina", target.resources["resource:core.stamina"] - affordable, HOLD)
        from combat.typed_reactions import on_damage
        pending = on_damage(engine, target, pending_damage, 0, HOLD, RIGHT)
        engine._commit_damage(target, pending, "FORCE", HOLD, RIGHT, None, reaction_depth=0)

    on_hold(monkeypatch, damage)
    if ai_turn:
        from combat.gate4_adapters import ManualControllerAdapter
        # AI owns the triggering turn; Left retains manual Ask me priority.
        while table.state(mid)["menu"]["actor_id"] != RIGHT:
            act(table, mid, "end")
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
        real = combat.controller
        class Scripted:
            def choose_primary_action(self, context):
                cid = next(c.candidate_id for c in context.legal_candidates if c.source_definition_id == HOLD)
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        combat.controller = Scripted()
        send = lambda answers: table.auto_step(mid, 0, answers)
    else:
        state = table.state(mid)
        menu = state["menu"]
        cid = next(g["options"][0]["candidate_id"] for g in menu["actions"] if g["source_definition_id"] == HOLD)
        send = lambda answers: table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, answers)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send([])
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert [o["id"] for o in prompt["choice"]["options"]] == [str(n) for n in range(1, affordable + 1)]
    assert "Stamina Guard" in prompt["reaction"] and "Left" in prompt["trigger"]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    if amount == 1 and affordable == 4 and not ai_turn:
        with pytest.raises(Exception):
            send([{**prompt["context"], "selection": "USE", "option_ids": ["5"]}])
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    answer = {**prompt["context"], "selection": "USE" if amount else "DECLINE", "option_ids": [str(amount)] if amount else []}
    assert send([answer])["status"] == "COMMITTED"
    loaded = CombatService(combat.source_root, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[LEFT]
    assert actor.resources["resource:core.stamina"] == affordable - (amount or 0)
    events = [e for e in loaded.engine.events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == GUARD]
    assert len(events) == bool(amount)
    if amount:
        assert events[-1].payload["spend"] == amount
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("ai_reactor", [False, True])
def test_automatic_guard_keeps_automatic_amount(monkeypatch, tmp_path, ai_reactor):
    combat, table, mid = table_fight(tmp_path, [GUARD], ask=ai_reactor, ally_talents=[], primary="Stamina")
    if ai_reactor:
        while table.state(mid)["menu"]["actor_id"] != RIGHT:
            act(table, mid, "end")
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
    def damage(engine):
        target = engine.state.actors[LEFT]
        engine._spend_resource(target, "resource:core.stamina", target.resources["resource:core.stamina"] - 4, HOLD)
        from combat.typed_reactions import on_damage
        pending = on_damage(engine, target, 16, 0, HOLD, RIGHT)
        engine._commit_damage(target, pending, "FORCE", HOLD, RIGHT, None, reaction_depth=0)
    on_hold(monkeypatch, damage)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = CombatService(combat.source_root, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[LEFT].resources["resource:core.stamina"] == 1
    assert loaded.mechanical.replay()["status"] == "PASS"
