"""Native AI tier regressions; synthetic fixtures, export-held combat runtime.

See tests/test_ai_tiers_public.py for the independently public tier/fixture
coverage. These tests retain native legality, execution and saved replay checks.
"""
from combat.gate2_runtime_models import Position
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_models import LocalControllerPolicy
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from factory_authoring.sphere_dao import character_dao, controller_policy
from tests.ai_tiers_native_support import ROOT, OWNER, FOE, fight, context_for, selected


def test_sheet_label_setup_and_fight_override_survive_commit_reload(tmp_path):
    combat, mid, session = fight(tmp_path, band="rival/boss")
    assert session.engine.state.actors[OWNER].ai_tier == "MASTERMIND"
    table = TabletopService(combat, tmp_path)
    assert table.sheet(OWNER.removeprefix("actor:factory."))["summary"]["ai_label"] == "AI: Mastermind"
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    assert combat.ai_decision_context(combat._load_session(mid)).tactics["tier"] == "MASTERMIND"
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO", ai_tier="TRICKY")
    assert combat.ai_decision_context(combat._load_session(mid)).tactics["tier"] == "TRICKY", "a tier-only change must invalidate the cached AI context"
    assert combat.local_step(mid)["status"] == "COMMITTED"
    fresh = CombatService(ROOT, tmp_path)
    loaded = fresh._load_session(mid)
    assert loaded.engine.state.actors[OWNER].ai_tier == "MASTERMIND", "creation default is not rewritten"
    assert loaded.engine.ai_tier_overrides[OWNER] == "TRICKY"
    row = next(a for a in TabletopService(fresh, tmp_path).state(mid, include_menu=False)["presentation"]["actors"]
               if a["entity_id"] == OWNER)
    assert row["ai_label"] == "AI: Tricky"
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_uses_strongest_affordable_talent_and_commits(tmp_path):
    combat, mid, session = fight(tmp_path, ["FIRE_TAL_FIREBALL_ART"], foe_at={"x": 10, "y": 5})
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    session = combat._load_session(mid)
    context = combat.ai_decision_context(session, progress_guard=True)
    choice, candidate = selected(context)
    assert "Fireball" in candidate.display_name
    assert "Dao: Fire" in choice.record.explanation
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    result = combat.local_step(mid)
    assert result["status"] == "COMMITTED"
    assert "Fireball" in result["record"]["explanation"]
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[OWNER].resources["resource:core.qi"] < session.engine.state.actors[OWNER].resources["resource:core.qi"]


def test_closes_to_best_owned_attack_not_one_square_shuffling(tmp_path):
    combat, mid, session = fight(tmp_path, melee=True)
    actor = session.engine.state.actors[OWNER]
    actor.action_available = actor.bonus_action_available = False
    context = context_for(combat, session)
    choice, candidate = selected(context)
    from combat.ai_tactics import TurnPlan
    plan = TurnPlan(context)
    attacks = [(i["damage"], i["range"]) for i in plan.actions.values() if i["damage"]]
    moves = sum(c.kind == "MOVE" for c in context.legal_candidates)
    details = f"range={plan.attack_range}; foes={len(plan.foes)}; attacks={attacks}; moves={moves}"
    assert candidate.kind == "MOVE", details
    assert candidate.movement_cost_ft >= 25
    assert session.engine._distance_actor_to_actor(actor, session.engine.state.actors[FOE], actor_position=candidate.destination) <= 5
    # Every legal move remains scored, not a hash/top-N subset.
    assert {c.candidate_id for c in context.legal_candidates if c.kind == "MOVE"} <= {
        s.candidate_id for s in choice.record.scored_alternatives}
    session.engine.execute_intent(choice.intent)
    _, next_candidate = selected(context_for(combat, session))
    assert next_candidate.kind == "END_TURN", "already in range: do not pace"


def test_unmet_owned_weapon_prerequisite_does_not_set_attack_range(tmp_path):
    from combat.ai_tactics import TurnPlan
    combat, _, session = fight(tmp_path)
    actor = session.engine.state.actors[OWNER]
    actor.action_available = actor.bonus_action_available = False
    context = context_for(combat, session)
    plan = TurnPlan(context)
    assert any(i["range"] > 5 and not i["ready"] for i in plan.actions.values())
    assert plan.attack_range == 5
    _, candidate = selected(context)
    assert candidate.kind == "MOVE"


def test_uses_native_flight_to_close_on_perceived_airborne_enemy(tmp_path):
    combat, _, session = fight(tmp_path, flight=True, melee=True, foe_at={"x": 4, "y": 6, "z": 4})
    actor = session.engine.state.actors[OWNER]
    actor.action_available = actor.bonus_action_available = False
    context = context_for(combat, session)
    choice, candidate = selected(context)
    assert candidate.kind == "MOVE" and candidate.metadata["movement_mode"] == "fly"
    assert candidate.destination.z > 0
    session.engine.execute_intent(choice.intent)
    assert actor.position == candidate.destination


def test_two_dao_combinations_choose_different_positions_in_same_situation(tmp_path):
    combat, _, session = fight(tmp_path, ["FIRE_BASE_IGNITE"])
    actor = session.engine.state.actors[OWNER]
    actor.action_available = actor.bonus_action_available = False
    context = context_for(combat, session)
    picks = []
    for spheres in ({"tianxia.sphere.air": 42, "tianxia.sphere.berserker": 12},
                    {"tianxia.sphere.dark": 8, "tianxia.sphere.scoundrel": 5}):
        dao = character_dao(spheres)
        policy = LocalControllerPolicy.model_validate(controller_policy(dao, OWNER))
        choice, candidate = selected(context.model_copy(update={"policy": policy}))
        assert "Dao: " + dao["primary_sphere"] in choice.record.explanation
        picks.append((candidate.kind, candidate.destination))
    assert picks[0] != picks[1]


def test_hidden_truth_does_not_change_tricky_plan(tmp_path):
    combat, _, session = fight(tmp_path, ["FIRE_BASE_IGNITE"])
    engine = session.engine
    foe = engine.state.actors[FOE]
    engine._apply_condition(foe, "condition:typed.invisible", "test:concealment", FOE, expires_on=None)
    first = context_for(combat, session)
    choice, _ = selected(first)
    foe.position = Position(x=15, y=5)
    foe.current_hp = 1
    foe.armor_class = 99
    second = context_for(combat, session)
    again, _ = selected(second)
    assert first.actors == second.actors
    assert first.tactics == second.tactics
    assert choice.intent.candidate_id == again.intent.candidate_id


def test_repeated_self_buff_loses_to_followup_and_resource_budget_is_soft(tmp_path):
    from combat.ai_tactics import TurnPlan
    combat, _, session = fight(tmp_path)
    context = context_for(combat, session)
    context.tactics["actions"]["buff"] = {"damage": 0, "control": 8, "range": 5,
        "attack_bonus": None, "costs": [["resource:core.qi", 1]], "economy": "BONUS_ACTION",
        "setup": True, "conditions": []}
    context.tactics["active_sources"].append("buff")
    source = next(c for c in context.legal_candidates if c.kind == "END_TURN")
    buff = source.model_copy(update={"source_definition_id": "buff", "kind": "BONUS_ACTION"})
    legacy = LocalDeterministicController()._score_candidate(context, buff, ())
    assert TurnPlan(context).score(buff, legacy).total < 0
    plan = TurnPlan(context)
    expensive = {"costs": [["resource:core.qi", 20]]}
    assert plan.resource_price(expensive) > plan.resource_price({"costs": [["resource:core.qi", 2]]}) > 0


def test_unusable_stowed_ranged_weapon_does_not_set_planned_range(tmp_path):
    from combat.ai_tactics import TurnPlan
    from combat.ext.hand_occupancy import weapon_allowed
    combat, _, session = fight(tmp_path, melee=True, extra_items=("tianxia.mortal.weapon.nu_gong",))
    engine = session.engine
    actor = engine.state.actors[OWNER]
    from combat.catalog_queries import owned_actions
    # Attacks that swing the crossbow itself, from the actor's owned actions (not only its offered ids).
    ranged = [action.source_definition_id for action in owned_actions(engine, OWNER)
              if action.source_definition_id.endswith(".weapon.nu_gong") and not action.source_definition_id.endswith(".pickup")]
    assert ranged, "the fixture must grant the crossbow attack"
    # Stow the physical crossbow through the same actor-state mutation as Stow.
    from combat.ext.equipment_hands import set_weapon_readiness
    for weapon in ranged:
        set_weapon_readiness(engine, actor, weapon, False, source="test:stow", source_actor_id=OWNER)
    # Precondition: native legality cannot use the stowed crossbow this turn.
    assert all(weapon_allowed(engine, actor, engine.action_catalog[aid]) is False for aid in ranged)
    context = context_for(combat, session)
    for aid in ranged:
        assert context.tactics["actions"].get(aid, {}).get("ready", False) is False
    assert TurnPlan(context).attack_range <= 5, "range must come from the usable melee attack, not the stowed weapon"


def test_move_into_best_owned_range_is_credited_when_a_strike_is_offered(tmp_path):
    from combat.ai_tactics import TurnPlan
    combat, _, session = fight(tmp_path, melee=True)
    context = context_for(combat, session)
    plan = TurnPlan(context)
    plan.bands = ((5, 5),)
    plan.attack_range = 5
    plan.best_attack_value = 1000
    focus = plan.focus.position
    move = next(c for c in context.legal_candidates if c.kind == "MOVE")
    arrive = move.model_copy(update={"destination": Position(x=focus.x - 1, y=focus.y)})
    plan.best_attack_id, plan.offered_strikes = "owned:melee", {"owned:ranged"}
    plan.has_strike = True
    assert plan.movement_value(arrive) >= plan.best_attack_value, "arrival enables the owned melee strike"
    plan.offered_strikes = {"owned:melee"}
    assert plan.movement_value(arrive) < plan.best_attack_value, "a square already offering the best strike earns no arrival credit"


def test_action_and_bonus_strikes_sharing_resources_are_scored_jointly(tmp_path):
    from combat.ai_tactics import TurnPlan
    combat, _, session = fight(tmp_path, ["FIRE_TAL_FIREBALL_ART"], foe_at={"x": 10, "y": 5})
    context = context_for(combat, session)
    strike = next(c for c in context.legal_candidates if c.kind == "ACTION"
                  and context.tactics["actions"].get(c.source_definition_id, {}).get("damage"))
    info = context.tactics["actions"][strike.source_definition_id]
    (resource, cost), = info["costs"]
    owner = next(a for a in context.actors if a.entity_id == OWNER)
    owner.resources[resource] = int(cost)  # enough for one strike, not both
    context.tactics["actions"]["rival"] = {**info, "economy": "BONUS_ACTION", "damage": 1}
    rival = strike.model_copy(update={"candidate_id": strike.candidate_id + ":rival",
                                      "kind": "BONUS_ACTION", "source_definition_id": "rival"})
    context = context.model_copy(update={"legal_candidates": (*context.legal_candidates, rival)})
    plan = TurnPlan(context)
    for candidate in (strike, rival):
        legacy = LocalDeterministicController()._score_candidate(context, candidate, ())
        scored = plan.score(candidate, legacy)
        conflicts = [c for c in scored.components if c.component == "joint_turn_conflict"]
        assert conflicts and conflicts[0].value < 0, "competing strikes on one resource pool must be jointly priced"


def test_offered_strike_outranks_dodge_guard_priority(tmp_path):
    """Round-1 bench: Tricky Dodged (64) every turn over its adjacent jian strike (59-60), then ended the turn."""
    from combat.ai_tactics import TurnPlan
    combat, _, session = fight(tmp_path, melee=True, foe_at={"x": 4, "y": 6})
    context = context_for(combat, session)
    plan = TurnPlan(context)
    assert plan.has_strike
    controller = LocalDeterministicController()
    dodge = next(c for c in context.legal_candidates if c.kind == "ACTION" and plan.actions.get(
        c.source_definition_id, {}).get("defense"))
    strike = next(c for c in context.legal_candidates if c.kind == "ACTION" and plan.actions.get(
        c.source_definition_id, {}).get("damage") and c.target_ids)
    guard = plan.score(dodge, controller._score_candidate(context, dodge, ()))
    attack = plan.score(strike, controller._score_candidate(context, strike, ()))
    assert "character_policy" not in {c.component for c in guard.components}, "guard priority must not outrank an offered strike"
    assert attack.total > guard.total
    choice, candidate = selected(context)
    assert candidate.kind != "END_TURN" and candidate.source_definition_id != dodge.source_definition_id


def test_critical_creature_alone_presses_offered_strike(tmp_path):
    """Round-4 bench: a lone Tricky that guarded from ~40% HP lost every melee/flier fight.

    With no standing ally, guarding cannot win the fight: nobody else will land
    the killing blow, so the surviving option is to keep attacking. This replaces
    the earlier doctrine test that kept guard priority at critical HP for a
    creature alone on its side (the exact behaviour that lost the 2026-10-20
    bench); guard priority is still kept when an ally is standing.
    """
    from combat.ai_tactics import TurnPlan
    combat, _, session = fight(tmp_path, melee=True, foe_at={"x": 4, "y": 6})
    session.engine.state.actors[OWNER].current_hp = 1
    context = context_for(combat, session)
    plan = TurnPlan(context)
    assert plan.low and plan.has_strike and not plan.allies
    controller = LocalDeterministicController()
    dodge = next(c for c in context.legal_candidates if c.kind == "ACTION" and plan.actions.get(
        c.source_definition_id, {}).get("defense"))
    strike = next(c for c in context.legal_candidates if c.kind == "ACTION" and plan.actions.get(
        c.source_definition_id, {}).get("damage") and c.target_ids)
    guard = plan.score(dodge, controller._score_candidate(context, dodge, ()))
    attack = plan.score(strike, controller._score_candidate(context, strike, ()))
    assert "survival" not in {c.component for c in guard.components}, "a lone critical creature must not guard"
    assert "character_policy" not in {c.component for c in guard.components}
    assert attack.total > guard.total


def test_critical_creature_with_a_standing_ally_keeps_guard_priority(tmp_path):
    from combat.ai_tactics import TurnPlan
    combat, _, session = fight(tmp_path, melee=True, foe_at={"x": 4, "y": 6})
    session.engine.state.actors[OWNER].current_hp = 1
    context = context_for(combat, session)
    ally = context.actors[0].model_copy(update={"entity_id": OWNER + "a103", "display_name": "Ally"})
    context = context.model_copy(update={"actors": (*context.actors, ally)})
    plan = TurnPlan(context)
    assert plan.allies
    dodge = next(c for c in context.legal_candidates if c.kind == "ACTION" and plan.actions.get(
        c.source_definition_id, {}).get("defense"))
    scored = plan.score(dodge, LocalDeterministicController()._score_candidate(context, dodge, ()))
    assert "survival" in {c.component for c in scored.components}


def test_flight_hop_with_no_range_gain_does_not_beat_ending_the_turn(tmp_path):
    """Round-4 flier shuffle: a hop that earns closing credit but no range-band gain must not score.

    The receipt is rebuilt on a real legal flight move: the engine's
    flight_tactics facts are replaced with a one-square hop whose nearest
    hostile improves by 5 ft while the plan's range error to the focus is
    unchanged. That is the shape the round-4 bench saw as a flier shuffling in
    place for a whole turn, and the fixture policy does not otherwise offer it.
    The controller's own legacy score and the real selection still run.
    """
    from combat.ai_tactics import TurnPlan
    combat, _, session = fight(tmp_path, flight=True, melee=True, foe_at={"x": 9, "y": 5})
    context = context_for(combat, session)
    plan = TurnPlan(context)
    assert not plan.has_strike, "precondition: no strike is offered at this range"
    base = plan.range_error(plan.actor.position)
    real = next(c for c in context.legal_candidates if c.kind == "MOVE"
                and c.metadata.get("flight_tactics") and not c.metadata.get("cover_from_nearest_hostile")
                and base - plan.range_error(c.destination) == 0 and c.movement_cost_ft <= 5)
    facts = {**real.metadata["flight_tactics"]}
    facts["current"] = {**facts.get("current", {}), "nearest_hostile_ft": 10,
                        "attack_target_ids": [], "melee_threat_ids": []}
    facts["destination"] = {**facts.get("destination", {}), "nearest_hostile_ft": 5,
                            "attack_target_ids": [], "melee_threat_ids": [], "evaluated": False,
                            "supported": True, "expiry_risk": False,
                            "altitude_ft": facts["current"].get("altitude_ft", 0)}
    shuffle = real.model_copy(update={"candidate_id": real.candidate_id + ":no-progress",
                                      "metadata": {**real.metadata, "flight_tactics": facts}})
    assert plan.range_error(shuffle.destination) == base, "the receipt must model no range-band gain"
    controller = LocalDeterministicController()
    scored = plan.score(shuffle, controller._score_candidate(context, shuffle, shuffle.option_ids))
    assert scored.total <= 0, f"a hop with no range gain must not score above zero: {scored.total}"
    end = next(c for c in context.legal_candidates if c.kind == "END_TURN")
    end_score = plan.score(end, controller._score_candidate(context, end, end.option_ids))
    assert scored.total <= end_score.total, "ending the turn is at least as good as a no-progress hop"
    extended = context.model_copy(update={"legal_candidates": (*context.legal_candidates, shuffle)})
    choice = controller.choose_primary_action(extended)
    assert choice.intent.candidate_id != shuffle.candidate_id, "a no-progress hop must not be chosen"


def test_reachable_closing_yields_guard_priority_when_the_creature_is_not_ahead(tmp_path):
    """Closing rule, yielding side: out of range, a legal move reaches this turn, and the creature is not ahead."""
    from combat.ai_tactics import TurnPlan
    combat, _, session = fight(tmp_path, melee=True, foe_at={"x": 9, "y": 5})
    context = context_for(combat, session)
    plan = TurnPlan(context)
    actor = session.engine.state.actors[OWNER]
    assert not plan.has_strike and not plan.allies
    assert plan.range_error(actor.position) > 0 and plan.reaches_this_turn
    assert actor.current_hp * 4 < plan.focus.current_hp * 5, "precondition: not >=125% of the foe's HP"
    controller = LocalDeterministicController()
    dodge = next(c for c in context.legal_candidates if c.source_definition_id == "system:combat.dodge")
    scored = plan.score(dodge, controller._score_candidate(context, dodge, dodge.option_ids))
    names = {c.component for c in scored.components}
    assert "character_policy" not in names and "survival" not in names, "the guard must yield to a reachable close"
    choice, candidate = selected(context)
    assert candidate.kind == "MOVE" and plan.range_error(candidate.destination) == 0


def test_unreachable_guard_keeps_its_priority(tmp_path):
    """Closing rule, staying side: no legal move reaches this turn, so the guard keeps its policy value."""
    from combat.ai_tactics import TurnPlan
    combat, _, session = fight(tmp_path, melee=True, foe_at={"x": 13, "y": 5})
    context = context_for(combat, session)
    plan = TurnPlan(context)
    actor = session.engine.state.actors[OWNER]
    assert not plan.has_strike and not plan.allies
    assert plan.range_error(actor.position) > 0 and not plan.reaches_this_turn
    controller = LocalDeterministicController()
    dodge = next(c for c in context.legal_candidates if c.source_definition_id == "system:combat.dodge")
    scored = plan.score(dodge, controller._score_candidate(context, dodge, dodge.option_ids))
    assert "character_policy" in {c.component for c in scored.components}, "an unreachable foe keeps the guard"


def test_guard_keeps_its_priority_when_the_creature_is_ahead(tmp_path):
    """Closing rule, staying side: even a reachable close is refused while the creature leads on HP."""
    from combat.ai_tactics import TurnPlan
    combat, _, session = fight(tmp_path, melee=True, foe_at={"x": 9, "y": 5})
    session.engine.state.actors[FOE].current_hp = 20
    context = context_for(combat, session)
    plan = TurnPlan(context)
    actor = session.engine.state.actors[OWNER]
    assert not plan.has_strike and not plan.allies and plan.reaches_this_turn
    assert actor.current_hp * 4 >= plan.focus.current_hp * 5, "precondition: >=125% of the foe's HP"
    controller = LocalDeterministicController()
    dodge = next(c for c in context.legal_candidates if c.source_definition_id == "system:combat.dodge")
    scored = plan.score(dodge, controller._score_candidate(context, dodge, dodge.option_ids))
    assert "character_policy" in {c.component for c in scored.components}, "a leading creature may keep the guard"


def test_disengage_counts_as_a_guard_and_yields_to_an_offered_strike(tmp_path):
    """Round-4 fix 6d6d1235: Disengage is keyed on resolution_kind, not only the Dodge id."""
    from combat.ai_tactics import TurnPlan
    combat, _, session = fight(tmp_path, melee=True, foe_at={"x": 4, "y": 6})
    context = context_for(combat, session)
    plan = TurnPlan(context)
    assert plan.has_strike and not plan.allies
    info = plan.actions["system:combat.disengage"]
    assert info["guard"] is True and info["defense"] is False, "DISENGAGE must be a guard without being a Dodge"
    controller = LocalDeterministicController()
    disengage = next(c for c in context.legal_candidates if c.source_definition_id == "system:combat.disengage")
    guard = plan.score(disengage, controller._score_candidate(context, disengage, disengage.option_ids))
    assert "character_policy" not in {c.component for c in guard.components}, (
        "a lone creature with a strike offered must not give Disengage its policy priority")
    strikes = [plan.score(c, controller._score_candidate(context, c, c.option_ids))
               for c in context.legal_candidates if c.kind == "ACTION"
               and plan.actions.get(c.source_definition_id, {}).get("damage") and c.target_ids]
    assert max(s.total for s in strikes) > guard.total, "an offered strike must outrank Disengage"
    choice, chosen = selected(context)
    assert chosen.source_definition_id != "system:combat.disengage"


def test_non_tricky_profile_returns_the_legacy_scores_unchanged(tmp_path):
    """A seat without the Tricky profile (the old AI) gets its own scores back object-for-object.

    TRICKYTUNE4R finding 4: the tactics plug-in sits on the shared controller seam, so a non-TRICKY
    profile must be completely inert. This is the non-TRICKY half of the stock-replay check: every
    legal candidate's legacy score is returned unchanged (same object, same components, same total),
    for the same reason no stock capture can move.
    """
    from combat.ai_tactics import TurnPlan
    combat, _, session = fight(tmp_path, melee=True)
    context = context_for(combat, session)
    old_ai = context.model_copy(update={"tactics": {}})
    plan = TurnPlan(old_ai)
    assert plan.enabled is False, "a profile without tactics data must switch the plug-in off"
    controller = LocalDeterministicController()
    checked = 0
    for candidate in old_ai.legal_candidates:
        legacy = controller._score_candidate(old_ai, candidate, candidate.option_ids)
        returned = plan.score(candidate, legacy)
        assert returned is legacy, "the legacy score object must be returned unchanged"
        checked += 1
    assert checked > 0
