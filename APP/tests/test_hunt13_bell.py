"""Bell eligibility at table preview, manual/AI commit, and journal reload."""
import pytest

from combat import typed_reactions
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_lock2_persistence import act
from tests.test_r10_integration import sender
from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, ALLY, RIGHT, HOLD, PROJECTS

BELL = "tianxia.talent.music.bell_of_warning"


def decline_initiative(combat, table, mid):
    """Complete the real setup transaction before isolating attack eligibility.

    fix/h37-bell d3b03b12 intentionally queues Ask-me Initiative before turn
    one (approved by Sol re-review in fix/QUEUE.md, LUNA5; integration in
    R23.report.md). Declining preserves the Reaction and round allowance.
    """
    state = table.state(mid)
    menu = state["menu"]
    candidate = next(option["candidate_id"] for group in menu["actions"]
                     for option in group["options"])
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    answers = []
    for _ in range(12):
        result = table.act(mid, candidate, menu["decision_id"], menu["state_version"],
                           state["last_sequence"], answers)
        if result["status"] != "REACTION_REQUIRED":
            break
        prompt = result["reaction"]
        assert prompt["reaction"] == "Bell of Warning"
        assert "initiative" in prompt["moment"].lower()
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        answers.append({**prompt["context"], "selection": "DECLINE"})
    assert result["status"] == "COMMITTED" and answers
    engine = combat._load_session(mid).engine
    assert not engine.state.setup_tasks
    assert engine.state.actors[LEFT].reaction_available
    assert not any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == BELL
                   for e in engine.events)


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("reason", ["eligible", "acted", "deafened", "blocked_hearing"])
def test_bell_only_protects_an_unacted_hearing_creature(monkeypatch, tmp_path, auto, reason):
    combat, table, _ = table_fight(tmp_path, [BELL], ask=True, ally_talents=[])
    # Fresh history: no fighter has completed a turn in this match.
    mid = combat.create_factory_match(project_ids=[PROJECTS["left"], PROJECTS["ally"]],
        opponent_actor_ids=[RIGHT], control_modes={a: "MANUAL" for a in (LEFT, ALLY, RIGHT)},
        arena_id="battlefield:map.hunt6-yard", match_seed="HUNT13-BELL")["match_id"]
    decline_initiative(combat, table, mid)
    if reason == "acted":
        while table.state(mid)["menu"]["actor_id"] != ALLY:
            assert act(table, mid, "end")["status"] == "COMMITTED"
        assert act(table, mid, HOLD)["status"] == "COMMITTED"
        assert act(table, mid, "end")["status"] == "COMMITTED"
    def attack(engine):
        owner, subject, foe = (engine.state.actors[a] for a in (LEFT, ALLY, RIGHT))
        # Initiative's separate compiled benefit can spend Bell before turn one.
        # Isolate this attack checkpoint with an available Reaction.
        owner.reaction_available = True
        if reason in ("deafened", "blocked_hearing"):
            engine._apply_condition(subject, "condition:typed." + reason, "test:hearing", RIGHT,
                                    expires_on="END_OF_CURRENT_TURN",
                                    data={"rule": {"cant_hear": True}} if reason == "blocked_hearing" else {})
        typed_reactions.on_attacked(engine, foe, subject,
            {"source_definition_id": HOLD, "attack_kind": "weapon"}, engine._active_intent)
    on_hold(monkeypatch, attack)
    active = table.state(mid)["menu"]["actor_id"]
    send = sender(combat, table, mid, active, auto)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    engine = combat._load_session(mid).engine
    row = next(r for r in engine.typed_reaction_rows[LEFT] if r["feature_id"] == BELL)
    resource = row["costs"][0]["resource_id"]
    resonance = before["actors"][LEFT]["resources"][resource]
    result = send()
    if reason == "eligible" and not auto:
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        assert prompt["reaction"] == "Bell of Warning"
        assert send()["reaction"] == prompt
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        result = send([{**prompt["context"], "selection": "USE"}])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    owner = loaded.engine.state.actors[LEFT]
    resolved = [e for e in loaded.engine.events if e.event_type == "REACTION_RESOLVED"
                and e.source_definition_id == BELL and e.payload.get("checkpoint") == "ATTACK_DECLARED"]
    assert len(resolved) == int(reason == "eligible")
    assert owner.resources[resource] == resonance - int(reason == "eligible")
    assert owner.reaction_available == (reason != "eligible")
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("activity", ["action", "move", "selector"])
def test_bell_first_turn_activity_without_turn_end(monkeypatch, tmp_path, auto, activity):
    """An accepted action/move counts immediately; a free setting does not."""
    from combat.ext.setting_choices import is_setting_action
    from tests.r10_fixup_support import cast_sender
    from combat.ext.bodyb_choices import RETURN_THE_GRIP

    combat, table, setup_mid = table_fight(tmp_path, [BELL], ask=True, ally_talents=[RETURN_THE_GRIP])
    # Owning this selector also grants Flowing River Response. Turn that
    # separate defense off so it cannot pre-empt the Bell checkpoint.
    from combat.tabletop import ButtonStore
    other_reactions = {r["feature_id"] for r in combat._load_session(setup_mid).engine.typed_reaction_rows[ALLY]}
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions(PROJECTS["ally"],
        {"mode": "custom", "off": sorted(other_reactions)}, other_reactions)
    mid = combat.create_factory_match(project_ids=[PROJECTS["left"], PROJECTS["ally"]],
        opponent_actor_ids=[RIGHT], control_modes={a: "MANUAL" for a in (LEFT, ALLY, RIGHT)},
        arena_id="battlefield:map.hunt6-yard", match_seed="HUNT13-FIRST-ACTION")["match_id"]
    decline_initiative(combat, table, mid)
    while table.state(mid)["menu"]["actor_id"] != ALLY:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    if activity == "selector":
        result = cast_sender(combat, table, mid, "Return the Grip: Push 10 feet")()
    elif activity == "action":
        result = act(table, mid, "system:combat.dodge")
    else:
        state = table.state(mid)
        candidate = next(c for c in combat._load_session(mid).engine.legal_candidates()
                         if c.kind.value == "MOVE")
        result = table.act(mid, candidate.candidate_id, candidate.decision_id,
                           candidate.state_version, state["last_sequence"])
    assert result["status"] == "COMMITTED"
    # Reload before the attack and prove TURN_ENDED cannot mask this assertion.
    combat = CombatService(ROOT, tmp_path)
    from combat.tabletop_service import TabletopService
    table = TabletopService(combat, tmp_path)
    engine = combat._load_session(mid).engine
    assert engine.state.current_actor_id == ALLY
    assert not any(e.actor_id == ALLY and e.event_type == "TURN_ENDED" for e in engine.events)
    accepted = [e for e in engine.events if e.actor_id == ALLY and e.event_type == "INTENT_ACCEPTED"]
    assert len(accepted) == 1
    assert accepted[0].payload["kind"] == {"move": "MOVE", "action": "ACTION", "selector": "BONUS_ACTION"}[activity]
    assert is_setting_action(engine.action_catalog.get(accepted[0].source_definition_id)) == (activity == "selector")

    def attack(engine):
        owner, subject, foe = (engine.state.actors[a] for a in (LEFT, ALLY, RIGHT))
        owner.reaction_available = True  # Isolate the attack benefit from initiative.
        typed_reactions.on_attacked(engine, foe, subject,
            {"source_definition_id": HOLD, "attack_kind": "weapon"}, engine._active_intent)
    # Trigger during another free selector, so the checkpoint itself does not
    # add a normal action that would invalidate the eligible control.
    from combat.gate4_engine import Gate4ControllerEngine
    candidate = next(c for c in engine.legal_candidates()
                     if "Return the Grip: Knock Prone" in c.display_name)
    original = Gate4ControllerEngine._append_event
    checkpoints = []
    def checkpoint(engine, event_type, *args, **kwargs):
        result = original(engine, event_type, *args, **kwargs)
        if event_type == "INTENT_ACCEPTED" and args[0] == candidate.source_definition_id:
            checkpoints.append(event_type)
            attack(engine)
        return result
    monkeypatch.setattr(Gate4ControllerEngine, "_append_event", checkpoint)
    state = table.state(mid)
    if auto:
        # Settings are player-only primary choices. Test an automatic Bell
        # reactor while the subject commits its setting through the table.
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
    def send(answers=()):
        return table.act(
            mid, candidate.candidate_id, candidate.decision_id, candidate.state_version,
            state["last_sequence"], list(answers))
    row = next(r for r in engine.typed_reaction_rows[LEFT] if r["feature_id"] == BELL)
    resource = row["costs"][0]["resource_id"]
    before = engine.state.actors[LEFT].resources[resource]
    result = send()
    assert checkpoints, "synthetic attack checkpoint did not run"
    eligible = activity == "selector"
    if eligible and not auto:
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        assert prompt["reaction"] == "Bell of Warning"
        result = send([{**prompt["context"], "selection": "USE"}])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    resolved = [e for e in loaded.engine.events if e.event_type == "REACTION_RESOLVED"
                and e.source_definition_id == BELL and e.payload.get("checkpoint") == "ATTACK_DECLARED"]
    assert len(resolved) == int(eligible)
    assert loaded.engine.state.actors[LEFT].resources[resource] == before - int(eligible)
    assert loaded.mechanical.replay()["status"] == "PASS"
