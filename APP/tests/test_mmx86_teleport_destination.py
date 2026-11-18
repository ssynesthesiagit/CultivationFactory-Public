"""MMX86 (owner playtest, round 24): a human who used Empty Step was never asked where to land.

Pinned here, at the level the bug showed:

- the destination of a self-teleport is the user's to choose, so a human who has no square bound to the action
  is asked for one through the bounded choice transport (combat/ext/teleport_steps.ask_destination, called by
  combat/typed_executor.py block_movement). Only a person answers: an AI combatant keeps its existing automatic
  behaviour so AI fights replay unchanged. A reaction that interrupts between paying the cost and choosing does
  not lose the answer, because the answer rides the intent. tests/test_mmx86_paid_teleport_variant.py carries the
  table-level pause/answer/commit/reload and the paid-economy half of this.
- only a SELF teleport is answered for the caster: a row that teleports another creature (Moonlit Ferry's ally row)
  is not the caster's square to pick, so it keeps its old GM instruction and the caster never moves.
- one hop is asked once, however many rows spell it out: several abilities carry both a ``teleport`` row and the
  parser's ``movement(mode=teleport)`` row for the same hop, and asking per row paid for two hops.
- an ability spends only the action-economy slot its printed text names: Empty Step is a Bonus Action, so the
  Action is still available afterwards. The teleport log line no longer reports a meaningless "(0 ft)".
"""
from pathlib import Path

import json
import pytest

from combat.ext.teleport_steps import destinations
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, EconomyKind, Position
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.stepper"
STEP = "action:typed.mmx86.self_teleport"
ALLY_STEP = "action:typed.mmx86.ally_teleport"
TWICE = "action:typed.mmx86.teleport_spelled_twice"


def _engine(talents=("TAL_VOID_EMPTY_STEP",), mode="MANUAL"):
    sheet = {**SHEET, "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.void", "tianxia.sphere.dream",
                                                                      "tianxia.sphere.sand"],
                                              "learned_talent_record_ids": list(talents)}}
    bundle = compile_character(sheet, actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed="MMX86", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 14, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    engine.typed_control_modes = {ME: mode}  # who answers for this creature
    return engine


def _unbound_teleport(engine, effects=None, source_definition_id=STEP, display_name="Unbound Step"):
    """A self-teleport whose action carries no square.

    Compiled self-teleports are aimed by combat/gate4_engine.py _action_candidates, which binds one legal square
    per candidate. An action that declares a zero-size area is not a self-teleport candidate to that helper
    (combat/typed_executor.py teleport_reach declines it), so the square is left unbound -- the shape that used to
    print "place the creature on the map" and let the engine decide. The destination is now asked for.
    """
    action = ActionDefinition(source_definition_id=source_definition_id, display_name=display_name, owner_id=ME,
                              economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF",
                              range_ft=20,
                              parameters={"options": ("SELF",),
                                          "typed": {"effects": effects if effects is not None else
                                                    [{"type": "teleport", "applies_to": "self", "distance_ft": 20,
                                                      "evidence": "Teleport to an unoccupied space you can see."}],
                                                   "area": {"size_ft": 0},
                                                   "numbers": {"pb": 4, "cl": 10, "save_dc": 12, "attack_bonus": 5},
                                                   "duration": {"kind": "instant"}, "weapon": None, "riders": []}})
    engine.action_catalog[source_definition_id] = action
    actor = engine.state.actors[ME]
    actor.action_ids = (*actor.action_ids, source_definition_id)
    return action


def _use(engine, action, destination=None, **extra):
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id)
    engine.execute_intent(ActionIntent(intent_id="mmx86", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=ME, target_ids=candidate.target_ids, destination=destination,
                                       option_ids=extra.get("option_ids", candidate.option_ids)))
    return candidate


def _intent(engine):
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == STEP)
    return ActionIntent(intent_id="mmx86", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                        state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                        option_ids=candidate.option_ids)


# ------------------------------------------------------------------ the destination is asked for
def test_a_self_teleport_with_no_bound_square_asks_the_user_where_to_land():
    engine = _engine()
    action = _unbound_teleport(engine)
    calls = []

    def choose(request):
        calls.append(request)
        from combat.gate2_runtime_models import ReactionDecision
        wanted = next(o for o in request["legal_option_ids"] if o.endswith("5,6"))
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE",
                                option_ids=(wanted,)), None

    engine.set_reaction_provider(choose)
    _use(engine, action)
    actor = engine.state.actors[ME]
    assert (actor.position.x, actor.position.y) == (5, 6)  # the square the user picked, not one the engine picked
    assert calls, "the user was never asked where to teleport"
    asked = calls[0]["legal_option_ids"]
    # Every offered square is one the creature can see, unoccupied, and inside the printed 20-foot range of
    # where it stood when it was asked (3,6).
    for option in asked:
        assert option.startswith("cell:")
        x, y = (int(part) for part in option.removeprefix("cell:").split(","))
        assert engine.grid.distance_ft(Position(x=3, y=6), Position(x=x, y=y)) <= 20
        assert engine.grid.placement_legal(Position(x=x, y=y), footprint=engine._footprint(engine.state.actors[ME]),
                                           occupied_cells=engine._occupied_cells_except(ME))
    assert "cell:3,6" not in asked, "the square it already stands on is not a teleport destination"


def test_the_question_is_a_choice_a_player_can_decline_by_staying_put():
    engine = _engine()
    action = _unbound_teleport(engine)
    seen = {}

    def choose(request):
        from combat.gate2_runtime_models import ReactionDecision
        seen["trigger"] = (request.get("choice_trigger") or {})
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="DECLINE"), None

    engine.set_reaction_provider(choose)
    _use(engine, action)
    assert (engine.state.actors[ME].position.x, engine.state.actors[ME].position.y) == (3, 6), "declining must stay put"
    prompt = str(seen["trigger"].get("prompt") or "")
    assert "Unbound Step" in prompt and ME not in prompt  # names the ability, in plain words, for the table
    assert "unoccupied square" in prompt and "stays where it is" in prompt
    assert "the Bonus Action remains spent either way" in prompt
    declined = [line for line in _riders(engine) if "stays where it is" in line]
    assert declined and "the Bonus Action remains spent either way" in declined[0]
    assert not any("place the creature on the map" in line for line in _riders(engine))


@pytest.mark.parametrize("costs", [(), (("resource:core.qi", 1),), (("resource:core.stamina", 2),)])
def test_destination_payment_text_uses_metadata_even_without_cost_in_name(costs):
    from combat.ext.teleport_steps import payment_text
    from combat.typed_executor import Context

    engine = _engine()
    action = _unbound_teleport(engine).model_copy(update={"costs": costs})
    actor = engine.state.actors[ME]
    ctx = Context(engine, actor, action, None, action.parameters["typed"], [actor])
    text = payment_text(ctx)
    assert "the Bonus Action" in text and "the Action" not in text
    if costs:
        resource, amount = costs[0]
        assert f"{amount} {resource.rsplit('.', 1)[-1].title()} from its resource pool" in text
    else:
        assert "resource pool" not in text


def test_range_only_duplicate_identity_preserves_explicit_and_ambiguous_hops():
    from types import SimpleNamespace
    from combat.ext.teleport_steps import hop_reach, teleport_requirement

    duplicate = {"type": "movement", "mode": "teleport", "distance_ft": None, "within_range": True}
    teleport = {"type": "teleport", "applies_to": "self", "distance_ft": 20}
    ctx = SimpleNamespace(typed={"effects": [teleport, duplicate]})
    assert hop_reach(ctx, duplicate, 0) == 20
    assert hop_reach(ctx, {**duplicate, "distance_ft": 10}, 10) == 10
    assert hop_reach(ctx, {**duplicate, "within_range": False}, 0) == 0
    assert hop_reach(ctx, {**duplicate, "type": "teleport"}, 0) == 0
    ctx.typed["effects"].append({**teleport, "distance_ft": 30})
    assert hop_reach(ctx, duplicate, 0) == 0  # two genuinely different explicit reaches cannot be guessed
    assert teleport_requirement({"teleport_where": "visible", "effects": [{**teleport, "where": "darkness"}]}) == "visible"
    assert teleport_requirement({"effects": [{**teleport, "where": "darkness"}]}) == "darkness"


@pytest.mark.parametrize("mode", ["LOCAL_AUTO", "API_AUTO", None])
def test_an_ai_combatant_keeps_its_own_behaviour_and_is_never_asked(mode):
    """The owner ruling: AI combatants keep the current automatic choice. Asking them is a human-only question,
    so an AI fight (and any engine with no recorded control mode) is untouched and replays byte-identically."""
    from combat.gate2_runtime_models import ReactionDecision

    engine = _engine(mode=mode) if mode else _engine()
    if mode is None:
        engine.typed_control_modes = {}
    action = _unbound_teleport(engine)
    asked = []

    def choose(request):
        asked.append(request["legal_option_ids"])
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE"), None

    engine.set_reaction_provider(choose)
    _use(engine, action)
    assert not asked, f"an AI combatant ({mode}) was asked to pick its own teleport destination"
    assert (engine.state.actors[ME].position.x, engine.state.actors[ME].position.y) == (3, 6)


def _riders(engine):
    return [str((event.payload or {}).get("rider") or "") for event in engine.events
            if event.event_type == "GM_RIDER"]


def _teleport_events(engine):
    return [event for event in engine.events
            if event.event_type == "MOVEMENT_COMMITTED" and (event.payload or {}).get("teleport")]


def test_a_teleport_of_another_creature_is_never_asked_on_the_caster():
    """Only a SELF teleport is the caster's own square to pick.

    Moonlit Ferry (authority/typed_mechanics/reviewed_final.d/riders_lane11.json) declares a non-deferred teleport row
    with ``applies_to: "ally"``. The caster is not the creature that moves there, so the caster must never be asked to
    pick that square: the row keeps its GM instruction and the caster stays where it is.
    """
    from combat.gate2_runtime_models import ReactionDecision

    data = json.loads((ROOT / "authority/typed_mechanics/reviewed_final.d/riders_lane11.json").read_text())
    moonlit = data["mechanics"]["tianxia.subpath.qi.riverway_cultivator.feature.moonlit_ferry"]
    assert [e for e in moonlit["effects"] if e.get("type") == "teleport" and e.get("applies_to") == "ally"], (
        "Moonlit Ferry no longer carries the ally-scoped teleport row this test is about")

    engine = _engine()
    action = _unbound_teleport(engine, source_definition_id=ALLY_STEP, display_name="Ferry an Ally",
                               effects=[{"type": "teleport", "applies_to": "ally", "distance_ft": 120,
                                         "evidence": "Teleport an ally to an unoccupied space you can see."}])
    asked = []

    def choose(request):
        asked.append(request["legal_option_ids"])
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE"), None

    engine.set_reaction_provider(choose)
    _use(engine, action)
    assert not asked, "the caster was asked to pick the square for a teleport meant for another creature"
    actor = engine.state.actors[ME]
    assert (actor.position.x, actor.position.y) == (3, 6), "the caster moved for a teleport that was not its own"
    assert not _teleport_events(engine)
    assert any("place the creature on the map" in line for line in _riders(engine)), (
        "an ally-scoped teleport must keep its GM instruction unchanged")


def test_one_hop_spelled_out_by_two_rows_is_asked_once_and_moves_once():
    """Several abilities carry a ``teleport`` row AND the parser's ``movement(mode=teleport)`` row for the same hop.

    The compiler copies both and the executor runs both, so a question per row asked twice and paid for two hops for
    one payment. Sand Burrow Step really does carry both rows; this reproduces that shape exactly.
    """
    from combat.gate2_runtime_models import ReactionDecision

    engine = _engine()
    action = _unbound_teleport(engine, source_definition_id=TWICE, display_name="Twice Spelled Step", effects=[
        {"type": "teleport", "applies_to": "self", "distance_ft": 20,
         "evidence": "Teleport up to 20 feet to an unoccupied space you can see"},
        {"type": "movement", "mode": "teleport", "distance_ft": 20, "evidence": "Teleport up to 20 feet"}])
    asked = []

    def choose(request):
        asked.append(list(request["legal_option_ids"]))
        wanted = next(o for o in request["legal_option_ids"] if o.endswith("5,6"))
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE",
                                option_ids=(wanted,)), None

    engine.set_reaction_provider(choose)
    _use(engine, action)
    assert len(asked) == 1, f"one hop was asked {len(asked)} times, once per effect row"
    actor = engine.state.actors[ME]
    assert (actor.position.x, actor.position.y) == (5, 6)
    hops = _teleport_events(engine)
    assert len(hops) == 1, f"one payment moved the creature {len(hops)} times"


def test_duplicate_rows_do_not_retry_a_failed_sealing_gate_save():
    """A real Sealing Gate blocks the entire represented hop, with one save and one payment."""
    from combat.gate2_runtime_models import ReactionDecision
    from tests.test_formations import _engine as formation_engine, _do, _array, SEALING

    engine, _ = formation_engine(SEALING)
    _do(engine, "Combat Array: Sealing Gate", at=(5, 6))
    actor_id = engine.state.current_actor_id
    actor = engine.state.actors[actor_id]
    actor.bonus_action_available = True
    actor.saving_throws["CHA"] = -100
    engine.typed_control_modes = {actor_id: "MANUAL"}
    zone = _array(engine)[0]
    zone.trigger_profile["formation"]["numbers"]["save_dc"] = 99
    action = ActionDefinition(source_definition_id=TWICE, display_name="Twice Spelled Step", owner_id=actor_id,
                             economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF",
                             costs=(("resource:core.qi", 1),), range_ft=60,
                             parameters={"options": ["SELF"], "typed": {"area": {"size_ft": 0}, "effects": [
                                 {"type": "teleport", "applies_to": "self", "distance_ft": 60},
                                 {"type": "movement", "mode": "teleport", "distance_ft": 60}]}})
    engine.action_catalog[TWICE] = action
    actor.action_ids = (*actor.action_ids, TWICE)
    start, qi = actor.position, actor.resources["resource:core.qi"]
    engine.set_reaction_provider(lambda request: (ReactionDecision(
        checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
        reaction_source_id=request["reaction_source_id"], selection="USE", option_ids=("cell:15,6",)), None))
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == TWICE)
    engine.execute_intent(ActionIntent(intent_id="sealing-duplicate", decision_id=candidate.decision_id,
                                      candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                      actor_id=actor_id, target_ids=candidate.target_ids, option_ids=candidate.option_ids))
    assert actor.position == start and actor.resources["resource:core.qi"] == qi - 1
    assert not _teleport_events(engine)
    assert len([e for e in engine.events if e.event_type == "SAVE_ROLLED"
                and e.source_definition_id.startswith("formation:sealing_gate:")]) == 1


def test_a_manual_fight_nobody_is_answering_leaves_the_creature_where_it_is():
    """No transport and no answer is the rider-only outcome it always was, not an engine-chosen square.

    The bounded choice transport hands back its default when nobody is answering, which used to mean "move the caster
    to the first square": a headless manual execution teleported the creature nobody had picked. Staying put is the
    contract, and the unchanged GM instruction is what a fight with nobody at the table still gets.
    """
    engine = _engine()
    action = _unbound_teleport(engine)
    _use(engine, action)  # a manual fight with no reaction provider installed at all
    actor = engine.state.actors[ME]
    assert (actor.position.x, actor.position.y) == (3, 6), "the engine moved a creature nobody chose a square for"
    assert not _teleport_events(engine)
    assert any("place the creature on the map" in line for line in _riders(engine)), (
        "a fight nobody is answering must still print the GM instruction it always printed")


def test_a_pause_before_any_answer_leaves_the_creature_put_and_the_replay_lands_where_the_player_picks():
    """A pause with nothing chosen yet moves nobody, and the replayed intent lands on the square the player then picks.

    This covers the pause-and-replay path only: the provider raises ChoicePause before any square is chosen, so
    nothing is carried across the pause here. The durable case -- a chosen answer crossing a real reaction and a
    real table commit and reload, with the paid economy applied once -- is
    tests/test_mmx86_paid_teleport_variant.py::test_destination_then_grave_reaction_resumes_and_reloads.
    """
    from combat.choice_checkpoints import ChoicePause
    from combat.gate2_runtime_models import ReactionDecision

    engine = _engine()
    _unbound_teleport(engine)
    asked = []

    def choose(request):
        if request["reaction_source_id"].startswith("choice:needle.teleport_destination"):
            asked.append(request["legal_option_ids"])
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=request["reaction_source_id"], selection="USE",
                                    option_ids=("cell:5,6",)), None
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE"), None

    def interrupting(request):
        """Something interrupts before the player answers, exactly as a reaction pauses the fight."""
        raise ChoicePause("a reaction is resolving")

    engine.set_reaction_provider(interrupting)
    intent = _intent(engine)
    with pytest.raises(ChoicePause):
        engine.execute_intent(intent)
    assert (engine.state.actors[ME].position.x, engine.state.actors[ME].position.y) == (3, 6), "the pause moved nobody"

    # The table answers, and the same intent is replayed with the answer on it.
    engine.set_reaction_provider(choose)
    engine.state.current_actor_id = ME
    engine._active_intent = None
    engine._gate4_reaction_cache = {}
    engine.execute_intent(intent)
    assert asked, "the destination question was never asked"
    assert (engine.state.actors[ME].position.x, engine.state.actors[ME].position.y) == (5, 6)


@pytest.mark.parametrize("talent", ["TAL_VOID_EMPTY_STEP", "TAL_DREAM_WAKING_DREAM_PASSAGE", "TAL_SAND_SAND_BURROW_STEP"])
def test_every_self_teleport_asks_where_to_land_not_only_empty_step(talent):
    """The question is raised by the printed teleport effect, so it covers Empty Step and every other."""
    from combat.gate2_runtime_models import ReactionDecision

    engine = _engine([talent, "DREAMS_BASE_DREAMSCAPE"] if talent == "TAL_DREAM_WAKING_DREAM_PASSAGE" else [talent])
    if talent == "TAL_DREAM_WAKING_DREAM_PASSAGE":
        # Printed rule: land inside your Dreamscape (or another printed dream
        # anchor). The old zero-area fixture bypassed that destination check.
        dream = next(c for c in engine.legal_candidates() if c.display_name.startswith("Dreamscape")
                     and c.destination == Position(x=4, y=6))
        engine.execute_intent(ActionIntent(intent_id="prepare-dream", decision_id=dream.decision_id,
            candidate_id=dream.candidate_id, state_version=dream.state_version, actor_id=ME,
            target_ids=dream.target_ids, destination=dream.destination, option_ids=dream.option_ids))
    teleports = [a for a in engine.action_catalog.values()
                 if a.owner_id == ME and a.resolution_kind == "TYPED" and a.display_name
                 and any(isinstance(e, dict) and (e.get("type") == "teleport" or e.get("mode") == "teleport")
                         for e in ((a.parameters or {}).get("typed") or {}).get("effects") or [])]
    assert teleports, f"{talent} compiled no teleport"
    action = teleports[0]
    action.parameters["typed"]["area"] = {"size_ft": 0}  # no square bound to the action (see _unbound_teleport)
    asked = []

    def choose(request):
        asked.append(request["legal_option_ids"])
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE",
                                option_ids=(request["legal_option_ids"][0],)), None

    engine.set_reaction_provider(choose)
    start = engine.state.actors[ME].position
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id)
    engine.execute_intent(ActionIntent(intent_id="mmx86", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=ME, target_ids=candidate.target_ids,
                                       option_ids=candidate.option_ids))
    assert asked, f"{action.display_name} never asked where to go"
    assert asked[0], "the destination question offered no squares"
    landed = f"cell:{engine.state.actors[ME].position.x},{engine.state.actors[ME].position.y}"
    assert landed in asked[0], f"it landed on {landed}, a square that was not one it was offered"


# ------------------------------------------------------------------ the action economy
def test_empty_step_spends_the_bonus_action_and_leaves_the_action():
    """Empty Step is "Action Type: Bonus Action" (TAL_VOID_EMPTY_STEP): only the Bonus Action is spent."""
    engine = _engine()
    steps = [c for c in engine.legal_candidates() if c.display_name.startswith("Empty Step")]
    pick = next(c for c in steps if c.destination == Position(x=7, y=6))
    actor = engine.state.actors[ME]
    assert actor.action_available and actor.bonus_action_available
    engine.execute_intent(ActionIntent(intent_id="step", decision_id=pick.decision_id, candidate_id=pick.candidate_id,
                                       state_version=pick.state_version, actor_id=ME, target_ids=pick.target_ids,
                                       destination=pick.destination))
    assert actor.position == Position(x=7, y=6)
    assert actor.bonus_action_available is False, "a Bonus Action ability must spend the Bonus Action"
    assert actor.action_available is True, "a Bonus Action ability must not also spend the Action"
    assert actor.reaction_available is True


# ------------------------------------------------------------------ the log line
def test_a_teleport_is_not_reported_as_moving_zero_feet():
    """combat/typed_executor.py _teleport records cost_ft 0 (a teleport spends no movement), so the feed used to
    print "(0 ft)", which reads as "it did not move"."""
    from combat.history_feed import format_history_feed

    event = {"event_type": "MOVEMENT_COMMITTED", "actor_id": "a", "source_definition_id": "teleport",
             "target_ids": [], "payload": {"destination": {"x": 12, "y": 8}, "path": [{"x": 3, "y": 6}, {"x": 12, "y": 8}],
                                           "cost_ft": 0, "teleport": True}}
    pre = {"actors": {"a": {"position": {"x": 3, "y": 6}}}}
    post = {"actors": {"a": {"position": {"x": 12, "y": 8}}}}
    row = format_history_feed([event], [], pre_state=pre, post_state=post, actor_names={"a": "Tabik Damu"},
                              definition_names={})[0]
    assert "0 ft" not in row["summary"] and "teleport" in row["summary"].lower()
