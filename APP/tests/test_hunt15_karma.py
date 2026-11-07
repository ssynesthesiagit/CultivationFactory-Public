"""Record the Deed names its cause, action and actual payment at the table."""
import pytest
from tests.hunt15_support import LEFT, RIGHT, act, fight, reload, turn


@pytest.mark.parametrize("ai", [False, True])
def test_record_prompt_and_payment_survive_reload(tmp_path, ai):
    combat, table, mid = fight(tmp_path, ["TAL_KARMA_RECORD_THE_DEED"], effects=[
        {"type": "damage", "damage_type": "PSYCHIC", "flat": 2, "applies_to": "target"}], target="HOSTILE_ENTITY")
    turn(table, mid, RIGHT)
    if ai:
        # Use the accepted test action through the service's normal controller adapter.
        from combat.gate4_adapters import ManualControllerAdapter
        cid = next(g["options"][0]["candidate_id"] for g in table.state(mid)["menu"]["actions"] if g["label"] == "Test setup")
        real = combat.controller
        class Controller:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        combat.controller = Controller()
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
    send = lambda answers: table.auto_step(mid, table.state(mid)["last_sequence"], answers) if ai else act(table, mid, "Test setup", answers)
    result = send([])
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["reaction"] == "Record the Deed"
    assert prompt["cost"] == "Reaction; no resource cost"
    assert "meaningful damage to River Keeper" in prompt["trigger"]
    assert "Test setup" in prompt["trigger"] and "Visiting Fighter" in prompt["trigger"]
    assert send([{**prompt["context"], "selection": "USE"}])["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert not engine.state.actors[LEFT].reaction_available
    from combat.ext.karma_imprints import held
    assert held(engine.state.actors[RIGHT], LEFT, "debt")


def test_protective_reaction_cause_names_the_reaction_action(tmp_path):
    from tests.hunt15_support import ALLY
    from combat.ext.karma_imprints import held

    combat, table, mid = fight(tmp_path, ["TAL_KARMA_RECORD_THE_DEED"], ally=["TAL_GUARDIAN_TAKE_THE_BLOW"],
        effects=[{"type": "damage", "damage_type": "PSYCHIC", "flat": 10, "applies_to": "target"}], target="HOSTILE_ENTITY")
    turn(table, mid, RIGHT)
    answers, prompts = [], []
    for _ in range(12):
        result = act(table, mid, "Test setup", answers, target_id=LEFT)
        if result["status"] != "REACTION_REQUIRED":
            break
        p = result["reaction"]
        prompts.append(p)
        answers.append({**p["context"], "selection": "USE" if "took damage for River Keeper" in p["trigger"] else "DECLINE"})
    assert result["status"] == "COMMITTED"
    prompt = next(p for p in prompts if "took damage for River Keeper" in p["trigger"])
    assert "Take the Blow" in prompt["trigger"] and "Guarding Friend" in prompt["trigger"]
    assert prompt["reaction"] == "Record the Deed" and prompt["cost"] == "Reaction; no resource cost"
    engine = reload(combat, mid)
    assert held(engine.state.actors[ALLY], LEFT, "grace")


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_ledger_payment_prompt_after_spending_reaction(tmp_path, ai, selection):
    """A real protective Reaction exhausts the Reaction before the witnessed deed.

    The player's paid Ledger choice must still pause an AI turn and persist
    exactly one CP payment when accepted, or none when declined.

    fix/hunt23 (19d4a6eb, wording approved by FIX23r2.review.md, item 13;
    final approval FIX23r3.review.md; integrated head
    247d3b85 in R23.report.md) intentionally explains the Cultivation Point
    payment using its actual pool. Keep that reviewed player-facing wording.
    """
    from tests.hunt15_support import ALLY, action_sender
    from combat.ext.karma_imprints import SEAL, held

    combat, table, mid = fight(tmp_path,
        ["TAL_KARMA_RECORD_THE_DEED", SEAL, "TAL_GUARDIAN_TAKE_THE_BLOW"], ally=[],
        effects=[{"type": "damage", "damage_type": "PSYCHIC", "flat": 10,
                  "applies_to": "target"}], target="HOSTILE_ENTITY")
    turn(table, mid, RIGHT)
    before = reload(combat, mid).state.actors[LEFT].resources["resource:core.qi"]
    send = action_sender(combat, table, mid, "Test setup", ai=ai, target_id=ALLY)
    answers, prompts = [], []
    for _ in range(12):
        result = send(answers)
        if result["status"] != "REACTION_REQUIRED":
            break
        p = result["reaction"]
        prompts.append(p)
        answer = selection if p["reaction"] == "Record the Deed" else "USE"
        if p["context"]["reaction_source_id"] == "choice:needle.held_harm":
            # Rider lane C16's Held Harm asks the Guardian taking its Take the Blow portion; held damage is not "taken" for triggers,
            # so the Guardian takes it now here, as the table did before Held Harm existed.
            answer = "DECLINE"
        picked = {"option_ids": (p["choice"].get("preferred") or [p["choice"]["options"][0]["id"]])[:1]} \
            if answer == "USE" and p.get("choice") else {}
        answers.append({**p["context"], "selection": answer, **picked})
    assert result["status"] == "COMMITTED"
    prompt = next(p for p in prompts if p["reaction"] == "Record the Deed")
    assert prompt["cost"] == "1 Cultivation Point from your Qi pool; no Reaction"
    assert "Test setup" in prompt["trigger"] and "Visiting Fighter" in prompt["trigger"]
    assert "meaningful damage to River Keeper" in prompt["trigger"]
    engine = reload(combat, mid)
    keeper = engine.state.actors[LEFT]
    assert not keeper.reaction_available
    payments = [e for e in engine.events if e.event_type == "RESOURCE_SPENT"
                and e.source_definition_id == SEAL and e.actor_id == LEFT]
    assert len(payments) == (1 if selection == "USE" else 0)
    assert keeper.resources["resource:core.qi"] == before - (1 if selection == "USE" else 0)
    assert bool(held(engine.state.actors[RIGHT], LEFT, "debt")) is (selection == "USE")
