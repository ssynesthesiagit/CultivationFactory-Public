"""Printed Hidden Strike: 'After applying damage, choose one' of five riders; Misleading Impact: 'Push or pull 5 feet'."""
import pytest
from tests.hunt36_support import HIDDEN, LEFT, RIGHT, act, reload, send, setup_hidden, weapon

OPTIONS = {"withdraw", "sever", "vanish", "mislead", "smoke"}


@pytest.mark.parametrize("choice", ["withdraw", "sever", "vanish", "mislead", "smoke"])
def test_manual_hidden_strike_asks_after_hit_and_persists_rider(tmp_path, choice):
    combat, table, mid = setup_hidden(tmp_path, smoke=True)
    before = reload(combat, mid).state.model_dump(mode="json")
    candidate = weapon(combat, mid)
    state = table.state(mid)
    menu = state["menu"]
    result = table.act(mid, candidate.candidate_id, menu["decision_id"], menu["state_version"], state["last_sequence"], [])
    assert result["status"] == "REACTION_REQUIRED", "Printed: after applying Hidden Strike damage, choose one rider"
    prompt = result["reaction"]
    assert {o["id"] for o in prompt["choice"]["options"]} == OPTIONS
    assert not prompt["choice"]["allow_decline"]
    assert prompt["context"]["reactor_id"] == LEFT
    for text in ("Hidden Strike", candidate.display_name, "Visiting Fighter", "no resource cost"):
        assert text in prompt["moment"]
    assert before == reload(combat, mid).state.model_dump(mode="json"), "choice pause must roll back the damage and gate"
    again = table.act(mid, candidate.candidate_id, menu["decision_id"], menu["state_version"], state["last_sequence"], [])
    assert again["reaction"] == prompt
    prompts = send(combat, table, mid, candidate.candidate_id, pick=lambda o: o["id"] == choice or o["id"] == "toward" or o["id"] == "cell:2,6")
    engine = reload(combat, mid)
    actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    assert actor.resources == before["actors"][LEFT]["resources"] and actor.reaction_available
    bonuses = [e for e in engine.events if e.event_type == "DAMAGE_ROLLED" and e.payload.get("damage_label") == "Hidden Strike"]
    assert len(bonuses) == 1
    if choice == "withdraw":
        assert (actor.position.x, actor.position.y) == (2, 6)
        assert any("Silent Withdrawal" in p["moment"] for p in prompts[1:])
    elif choice == "mislead":
        assert {o["id"] for o in prompts[1]["choice"]["options"]} == {"away", "toward"}
        assert not any(c.condition_id == "condition:typed.reaction_denied" for c in target.conditions.values())
    else:
        expected = {"sever": "reaction_denied", "vanish": "hidden_strike_stealth", "smoke": "hidden_strike_smoke_mark"}[choice]
        holder = actor if choice == "vanish" else target
        assert any(c.condition_id == f"condition:typed.{expected}" for c in holder.conditions.values())
        act(combat, table, mid, "end")
        if choice != "vanish":
            act(combat, table, mid, "end")
        engine = reload(combat, mid)
        holder = engine.state.actors[holder.entity_id]
        assert not any(c.condition_id == f"condition:typed.{expected}" for c in holder.conditions.values())


def test_ai_hidden_strike_owner_chooses_without_prompt(tmp_path):
    combat, table, mid = setup_hidden(tmp_path, smoke=True)
    prompts = send(combat, table, mid, weapon(combat, mid).candidate_id, ai=True)
    assert prompts == []
    engine = reload(combat, mid)
    assert any(c.condition_id == "condition:typed.reaction_denied" for c in engine.state.actors[RIGHT].conditions.values())


def test_vanishing_posture_is_consumed_by_only_the_next_stealth_check(tmp_path):
    combat, table, mid = setup_hidden(tmp_path, smoke=True, checks=True, kit={"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.bi_shou", "quantity": 1}]}})
    send(combat, table, mid, weapon(combat, mid).candidate_id, pick=lambda o: o["id"] == "vanish")
    act(combat, table, mid, "Test Stealth check")
    engine = reload(combat, mid)
    checks = [e for e in engine.events if e.event_type == "CHECK_ROLLED"]
    roll = checks[-1].payload["actor"]
    assert roll["mode"] == "ADVANTAGE"
    assert not any(c.condition_id == "condition:typed.hidden_strike_stealth" for c in engine.state.actors[LEFT].conditions.values())
    act(combat, table, mid, "Test Stealth check")
    checks = [e for e in reload(combat, mid).events if e.event_type == "CHECK_ROLLED"]
    assert checks[-1].payload["actor"]["mode"] == "NORMAL"


@pytest.mark.parametrize("direction", ["away", "toward"])
def test_misleading_impact_push_and_pull_move_five_feet(tmp_path, direction):
    combat, table, mid = setup_hidden(tmp_path, positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 5, "y": 6}})
    candidate = next(c for c in combat._load_session(mid).engine.legal_candidates() if ".weapon." in c.source_definition_id and c.source_definition_id.endswith("#thrown") and tuple(c.target_ids) == (RIGHT,))
    send(combat, table, mid, candidate.candidate_id, pick=lambda o: o["id"] in ("mislead", direction))
    target = reload(combat, mid).state.actors[RIGHT]
    assert (target.position.x, target.position.y) == (6 if direction == "away" else 4, 6)


@pytest.mark.parametrize("also_hidden", [False, True])
def test_smoke_mark_masks_only_invisible_against_its_owner_and_shows_direction(tmp_path, also_hidden):
    from combat import ext, senses
    from combat.ext.tabik_ninpo import SMOKE_MARK

    combat, table, mid = setup_hidden(tmp_path, smoke=True, right_effects=[
        {"type": "condition", "condition": "invisible", "applies_to": "self", "expires_on": "UNTIL_REMOVED"},
        *([{"type": "condition", "condition": "hidden", "applies_to": "self", "expires_on": "UNTIL_REMOVED"}] if also_hidden else [])])
    send(combat, table, mid, weapon(combat, mid).candidate_id, pick=lambda o: o["id"] == "smoke")
    act(combat, table, mid, "end")
    act(combat, table, mid, "Test setup")
    engine = reload(combat, mid)
    owner, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    invisible = {iid for iid, c in target.conditions.items() if c.condition_id == "condition:typed.invisible"}
    hidden = {iid for iid, c in target.conditions.items() if c.condition_id == "condition:typed.hidden"}
    masked = senses.masked_conditions(engine, owner, target).get(RIGHT, set())
    assert invisible and invisible <= masked and not hidden & masked
    assert senses.masked_conditions(engine, target, owner).get(RIGHT, set()) == masked
    mark = next(c for c in target.conditions.values() if c.condition_id == SMOKE_MARK)
    text = ext.query("status_description", engine, target, {"condition_id": SMOKE_MARK}, dict(mark.data))[0]["text"]
    assert "east" in text and "River Keeper" in text and "inside its Smoke Veil" in text
    assert not senses.masked_conditions(engine, target, target).get(RIGHT, set())
    from combat.target_knowledge import can_see
    assert can_see(engine, owner, target) == (not also_hidden), "Smoke Mark: target cannot benefit from Invisible against you, but Hidden remains a separate concealment state"


def test_off_turn_vanishing_posture_ends_with_the_triggering_turn(tmp_path):
    from combat.tabletop import ButtonStore
    combat, table, mid = setup_hidden(tmp_path, smoke=True)
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions("36000001", {"mode": "ask"}, {"opportunity_attack"})
    act(combat, table, mid, "end")
    menu = table.state(mid)["menu"]
    cid = next(m["candidate_id"] for m in menu["moves"] if m["destination"] == {"x": 5, "y": 6})
    send(combat, table, mid, cid, ai=True, pick=lambda o: o["id"] == "vanish")
    engine = reload(combat, mid)
    assert any(c.condition_id == "condition:typed.hidden_strike_stealth" for c in engine.state.actors[LEFT].conditions.values())
    act(combat, table, mid, "end")
    engine = reload(combat, mid)
    assert engine.state.current_actor_id == LEFT
    assert not any(c.condition_id == "condition:typed.hidden_strike_stealth" for c in engine.state.actors[LEFT].conditions.values())
