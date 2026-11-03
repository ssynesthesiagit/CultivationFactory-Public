"""C16 clause contracts on the reviewed native movement checkpoints."""
import pytest

from combat import ext
from combat.ext import needle
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.movement_steps import context
from tests import lock8_support as S
from tests.h1_support import ROOT
from tests.test_lock_choices import install
from tests.test_lock8_movement_steps import portable, candidate, use
from tests.r10_fixup_support import answer

ROOT_SNARE = "TAL_VERDANT_GROWTH_ROOT_SNARE_STEP"
DEEP_ROOT = "TAL_VERDANT_GROWTH_DEEP_ROOT_HOLDS_THE_GATE"
PATROL = "GUARDIAN_BASE_PATROL_PRACTICE"


@pytest.mark.parametrize("feature,point,x,cost", [(ROOT_SNARE, "movement_step", 4, 5), (DEEP_ROOT, "movement_attempt", 3, 0)])
def test_printed_stop_timing_pauses_then_reloads(monkeypatch, tmp_path, feature, point, x, cost):
    service, table, mid, left, right = portable(tmp_path, "SAND_BASE_SCOURING_HAND", feature)
    label = "Root-Snare Step" if feature == ROOT_SNARE else "Deep Root Holds the Gate"
    seen = []
    def respond(engine, mover, previous, nxt, intent):
        if mover.entity_id != left:
            return None
        owner = engine.state.actors[right]
        seen.append((mover.position.x, context(engine, mover)["travelled_ft"]))
        picked = needle.ask(engine, intent, "C16_MOVEMENT", owner, "choice:needle.c16_step", ["stop"],
                            labels={"stop": "Stop this movement"}, name=label, feature_id=feature,
                            prompt=f"Use your Reaction for {label} to stop {mover.display_name}'s movement?",
                            target_id=mover.entity_id, automatic=False, allow_decline=True)
        if not picked:
            return None
        owner.reaction_available = False
        engine._append_event("REACTION_RESOLVED", feature, actor_id=right, target_ids=(left,))
        return {"stop": True, "source_id": feature, "label": f"{label} stops this movement."}
    install(monkeypatch, point, respond)
    state = table.state(mid)
    e = service._load_session(mid).engine
    c = candidate(e, 6)
    before = e.state.model_dump(mode="json")
    def send(answers=()):
        return table.act(mid, c.candidate_id, c.decision_id, c.state_version, state["last_sequence"], list(answers))
    paused = send()
    assert paused["status"] == "REACTION_REQUIRED"
    assert service._load_session(mid).engine.state.model_dump(mode="json") == before
    assert send([answer(paused["reaction"])])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[left].position == Position(x=x, y=6)
    assert not loaded.engine.state.actors[right].reaction_available
    event = next(ev for ev in reversed(loaded.engine.events) if ev.event_type == "MOVEMENT_COMMITTED")
    assert event.payload["cost_ft"] == cost and event.payload["interrupted"]
    assert all(actual == (x, cost) for actual in seen)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_patrol_sees_entry_through_and_exit_when_both_endpoints_are_outside(monkeypatch, tmp_path):
    service, table, mid, left, right = portable(tmp_path, "SAND_BASE_SCOURING_HAND", PATROL)
    pairs = []
    def patrol(engine, mover, previous, nxt, intent):
        if mover.entity_id != left:
            return
        old, new = previous.x in (4, 5), nxt.x in (4, 5)
        if old or new:
            word = "crosses" if old and new else "leaves" if old else "enters"
            pairs.append((old, new))
            ext.note(engine, PATROL, engine.state.actors[right], f"{mover.display_name} {word} the Patrol Zone.")
    install(monkeypatch, "movement_step", patrol)
    e = service._load_session(mid).engine
    c = candidate(e, 7)
    assert table.act(mid, c.candidate_id, c.decision_id, c.state_version, table.state(mid)["last_sequence"])["status"] == "COMMITTED"
    expected = [(False, True), (True, True), (True, False)]
    assert pairs and all(pairs[i:i + 3] == expected for i in range(0, len(pairs), 3))
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    notices = [ev.payload["log"] for ev in loaded.engine.events
               if ev.event_type == "PASSIVE_TRIGGERED" and ev.source_definition_id == PATROL and "Patrol Zone" in ev.payload.get("log", "")]
    assert len(notices) == 3
    assert all(word in text for word, text in zip(("enters", "crosses", "leaves"), notices))
    assert loaded.engine.state.actors[left].position == Position(x=7, y=6)
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("condition", ["prone", "unconscious"])
def test_attempt_reaction_disables_move_before_oa_or_payment(monkeypatch, condition):
    e = S.fight(S.bundle("SAND_BASE_SCOURING_HAND"), foe_at=(10, 6))
    def respond(engine, mover, *args):
        engine._apply_condition(mover, "condition:typed." + condition, DEEP_ROOT, S.FOE, expires_on="UNTIL_REMOVED")
    install(monkeypatch, "movement_attempt", respond)
    calls = []
    monkeypatch.setattr(e, "_resolve_leave_reach", lambda *a, **k: calls.append(True))
    use(e, candidate(e, 6))
    assert e.state.actors[S.ME].position == Position(x=3, y=6) and calls == []
    event = next(ev for ev in reversed(e.events) if ev.event_type == "MOVEMENT_COMMITTED")
    assert event.payload["cost_ft"] == 0 and event.payload["interrupted"]
