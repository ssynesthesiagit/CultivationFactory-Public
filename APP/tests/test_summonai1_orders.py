"""Public synthetic table orders and native-controller safety regressions."""
import pytest

from combat import summons
from combat.ext import summon_instinct
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from test_summons import _engine, _turn_of, OWNER, AN
from test_h47_summon_table import table_fixture, candidate, guard, OWNER as TABLE_OWNER


@pytest.mark.parametrize("kind", ["attack", "hold", "guard", "use", "hide", "follow"])
def test_manual_table_order_survives_command_commit_reload_and_automatic_turn(tmp_path, kind):
    combat, table, mid, send, commit = table_fixture(tmp_path)
    commit(candidate(table, mid, "Bone Guard Manifestation"))
    while table.state(mid)["menu"]["actor_id"] != TABLE_OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    cid = candidate(table, mid, "Command")
    answers = []
    offered = set()
    for _ in range(12):
        result = send(cid, answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        choice = prompt.get("choice")
        answer = {**prompt["context"], "selection": "DECLINE"}
        if choice:
            ids = [o["id"] for o in choice["options"]]
            if "hold" in ids:
                offered.update(ids)
                selected = kind
            elif kind == "guard" and TABLE_OWNER in ids:
                selected = TABLE_OWNER
            else:
                selected = ids[0]
            answer.update(selection="USE", option_ids=[selected])
        answers.append(answer)
    else:
        pytest.fail("Command did not finish")
    assert set(summon_instinct.DIRECTIVE_KINDS) <= offered
    assert result["status"] == "COMMITTED"
    creature = guard(combat, mid)
    fresh = CombatService(combat.source_root, tmp_path)
    reloaded = fresh._load_session(mid).engine.state.actors[creature.entity_id]
    order = dict(reloaded.summon["directive"])
    before_position = reloaded.position
    before_sequence = fresh._load_session(mid).engine.state.event_sequence
    assert order["kind"] == kind
    assert not fresh._load_session(mid).engine.state.actors[TABLE_OWNER].bonus_action_available
    fresh_table = TabletopService(fresh, tmp_path)
    menu = fresh_table.state(mid)["menu"]
    assert fresh_table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0, [])["status"] == "COMMITTED"
    latest = CombatService(combat.source_root, tmp_path)._load_session(mid).engine
    assert "directive" not in latest.state.actors[creature.entity_id].summon
    assert any(e.event_type == "SUMMON_TURN" and e.actor_id == creature.entity_id
               and "follows its order: " + kind in e.payload["text"] for e in latest.events)
    history = fresh_table.events(mid, 0)["events"]
    defaults = [row for row in history if row["event_type"] == "COMPANION_DEFAULT_APPLIED"
                and row["actor_id"] == creature.entity_id]
    assert defaults[-1]["summary"] == f"{creature.display_name} follows its order for this turn, then returns to its own instincts."
    acted = latest.state.actors[creature.entity_id]
    turn_events = [e for e in latest.events if e.sequence > before_sequence and e.actor_id == creature.entity_id]
    if kind == "hold":
        assert acted.position == before_position
        assert any(c.condition_id == "condition:core.dodge" for c in acted.conditions.values())
    elif kind == "guard":
        assert latest._distance_actor_to_actor(acted, latest.state.actors[TABLE_OWNER]) <= 5
        assert any(c.condition_id == "condition:core.dodge" for c in acted.conditions.values())
        assert acted.reaction_available
    elif kind == "attack":
        assert any(e.event_type == "INTENT_ACCEPTED" and order["target_id"] in e.target_ids for e in turn_events)
    elif kind == "use":
        assert any(e.event_type == "INTENT_ACCEPTED" and e.source_definition_id == order["action_id"] for e in turn_events)


def test_instinct_calls_existing_controller_and_keeps_the_full_context(monkeypatch):
    from combat.gate4_controller import LocalDeterministicController
    calls = []
    original = LocalDeterministicController.choose_primary_action
    def choose(self, context):
        calls.append(context)
        return original(self, context)
    monkeypatch.setattr(LocalDeterministicController, "choose_primary_action", choose)
    engine = _engine(["TAL_DEATH_CORPSE_SERVANT"], corpse_servant=1)
    creature = summons.owned_by(engine, OWNER)[0]
    engine.state.actors[AN].position = Position(x=creature.position.x + 1, y=creature.position.y)
    _turn_of(engine, OWNER)
    engine.end_turn()
    assert calls
    assert any(c.kind == "END_TURN" for c in calls[0].legal_candidates)
    assert any(e.event_type == "INTENT_ACCEPTED" and e.actor_id == creature.entity_id for e in engine.events)
    assert any(e.event_type == "SUMMON_TURN" and "attacks" in e.payload["text"] for e in engine.events)


def test_a_blocked_move_is_logged_as_not_moving_and_says_why(monkeypatch):
    """A stopped move must never read as a completed one (owner 2026-10-21)."""
    from tests.test_lock_choices import install

    engine = _engine(["TAL_DEATH_CORPSE_SERVANT"], corpse_servant=1)
    creature = summons.owned_by(engine, OWNER)[0]
    engine.state.actors[AN].active = False
    engine.state.actors[OWNER].position = Position(x=18, y=6)
    creature.position = Position(x=3, y=6)
    calls = []

    def blocked(engine, mover, previous, nxt, intent):
        if mover.entity_id != creature.entity_id:
            return None
        calls.append((previous, nxt))
        return {"stop": True, "source_id": "test:summon_blocked_way",
                "label": "The doorway is blocked by a fallen pillar."}

    install(monkeypatch, "movement_attempt", blocked)
    _turn_of(engine, OWNER)
    summon_instinct.set_directive(creature.summon, "follow")
    engine.end_turn()
    assert calls, "the ordered move never left its square"
    assert creature.position == Position(x=3, y=6)
    lines = [e.payload["text"] for e in engine.events
             if e.event_type == "SUMMON_TURN" and e.actor_id == creature.entity_id]
    assert lines == [f"{creature.display_name} follows its order: follow: "
                     "could not move: The doorway is blocked by a fallen pillar."], lines
    assert all("moves toward" not in line for line in lines)


def test_follow_rejects_dangerous_shortest_route_but_keeps_safe_alternatives(monkeypatch):
    from combat.ext import ai_movement
    engine = _engine(["TAL_DEATH_CORPSE_SERVANT"], corpse_servant=1)
    creature = summons.owned_by(engine, OWNER)[0]
    engine.state.actors[AN].active = False
    engine.state.actors[OWNER].position = Position(x=18, y=6)
    creature.position = Position(x=3, y=6)
    real = ai_movement.perceived_movement_hazards
    safe = set()
    def risks(eng, actor, candidates, frame):
        result = real(eng, actor, candidates, frame)
        moves = [c for c in candidates if c.kind == "MOVE" and c.destination]
        for c in moves:
            if c.destination.y == 6:
                result[c.candidate_id]["hazard_exposure"] = True
        safe.update((c.destination.x, c.destination.y) for c in moves if c.destination.y != 6)
        return result
    monkeypatch.setattr(ai_movement, "perceived_movement_hazards", risks)
    _turn_of(engine, OWNER)
    engine.end_turn()
    assert (creature.position.x, creature.position.y) in safe
    assert creature.position.y != 6


def test_guard_order_uses_the_creatures_own_guard_action_to_enable_its_reaction():
    engine = _engine(["TAL_DEATH_CORPSE_SERVANT", "TAL_DEATH_DEATHLESS_GUARD"], corpse_servant=1)
    creature = summons.owned_by(engine, OWNER)[0]
    _turn_of(engine, OWNER)
    summon_instinct.set_directive(creature.summon, "guard", target_id=OWNER)
    engine.end_turn()
    assert any(c.condition_id == "condition:typed.guarding" for c in creature.conditions.values())
    assert creature.reaction_available


def test_follow_order_never_leaves_a_perceived_enemys_reach():
    engine = _engine(["TAL_DEATH_CORPSE_SERVANT"], corpse_servant=1)
    creature = summons.owned_by(engine, OWNER)[0]
    creature.position = Position(x=3, y=6)
    engine.state.actors[AN].position = Position(x=4, y=6)
    engine.state.actors[OWNER].position = Position(x=18, y=6)
    _turn_of(engine, OWNER)
    summon_instinct.set_directive(creature.summon, "follow")
    engine.end_turn()
    assert engine._distance_actor_to_actor(creature, engine.state.actors[AN]) <= 5
    assert not any(e.event_type == "REACTION_RESOLVED" and e.actor_id == AN for e in engine.events)


def test_hide_order_takes_the_native_hide_action_when_concealed(monkeypatch):
    from combat import stealth
    engine = _engine(["TAL_DEATH_CORPSE_SERVANT"], corpse_servant=1)
    creature = summons.owned_by(engine, OWNER)[0]
    calls = []
    native = stealth.hide
    monkeypatch.setattr(stealth, "can_hide", lambda *args, **kwargs: True)
    def hide(*args, **kwargs):
        calls.append(args[1].entity_id)
        return native(*args, **kwargs)
    monkeypatch.setattr(stealth, "hide", hide)
    _turn_of(engine, OWNER)
    summon_instinct.set_directive(creature.summon, "hide")
    engine.end_turn()
    assert calls == [creature.entity_id]
    assert not creature.action_available
    assert any(e.event_type == "SUMMON_TURN" and "takes the Hide action" in e.payload["text"]
               for e in engine.events)


def _summon_lines(engine, creature):
    return [e.payload["text"] for e in engine.events
            if e.event_type == "SUMMON_TURN" and e.actor_id == creature.entity_id]


def test_instinct_without_a_known_owner_position_does_not_claim_proximity():
    """The summary must describe where the summon actually is (owner 2026-10-21)."""
    engine = _engine(["TAL_DEATH_CORPSE_SERVANT"], corpse_servant=1)
    creature = summons.owned_by(engine, OWNER)[0]
    engine.state.actors[AN].active = False
    engine.state.actors[OWNER].position = Position(x=17, y=6)
    creature.position = Position(x=3, y=6)
    creature.owner_id = "actor:not_in_this_fight"
    _turn_of(engine, OWNER)
    engine.end_turn()
    assert creature.position == Position(x=3, y=6)
    assert _summon_lines(engine, creature) == [
        f"{creature.display_name} acts on instinct: has no enemy in sight and holds position."]


def test_instinct_beyond_thirty_feet_without_a_safe_route_says_it_holds(monkeypatch):
    """Beyond 30 ft it cannot close safely, so the summary says it held, not that it stayed near."""
    from combat.ext import ai_movement
    engine = _engine(["TAL_DEATH_CORPSE_SERVANT"], corpse_servant=1)
    creature = summons.owned_by(engine, OWNER)[0]
    engine.state.actors[AN].active = False
    engine.state.actors[OWNER].position = Position(x=17, y=6)
    creature.position = Position(x=3, y=6)
    real = ai_movement.perceived_movement_hazards
    def risks(eng, actor, candidates, frame):
        result = real(eng, actor, candidates, frame)
        for c in candidates:
            if c.kind == "MOVE" and c.destination is not None:
                result[c.candidate_id]["hazard_exposure"] = True
        return result
    monkeypatch.setattr(ai_movement, "perceived_movement_hazards", risks)
    _turn_of(engine, OWNER)
    engine.end_turn()
    assert creature.position == Position(x=3, y=6)
    lines = _summon_lines(engine, creature)
    assert lines == [f"{creature.display_name} acts on instinct: has no enemy in sight and "
                     "cannot get closer to its owner safely, so it holds position."], lines
    assert all("stays near its owner" not in line for line in lines)


def test_instinct_far_from_its_owner_says_it_moves_back_toward_it():
    engine = _engine(["TAL_DEATH_CORPSE_SERVANT"], corpse_servant=1)
    creature = summons.owned_by(engine, OWNER)[0]
    engine.state.actors[AN].active = False
    engine.state.actors[OWNER].position = Position(x=17, y=6)
    creature.position = Position(x=3, y=6)
    _turn_of(engine, OWNER)
    engine.end_turn()
    assert creature.position != Position(x=3, y=6)
    assert _summon_lines(engine, creature) == [
        f"{creature.display_name} acts on instinct: moves back toward its owner."]
