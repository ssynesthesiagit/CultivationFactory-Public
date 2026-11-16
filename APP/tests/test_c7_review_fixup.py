"""C7 review regressions: legal reach, activation lifetimes and real table pauses/reloads.

Synthetic triggering effects run inside accepted table actions; no live data or GUI.
"""
import copy

import pytest

from combat import typed_executor as te
from combat.ext import white_heron
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_riders_c7 import (ROOT, ME, FOE, HERON, JI, STAMINA, MOMENTUM,
                                 bundle, sheet, fight, turn, answers, use, unarmed,
                                 _heron, _momentum, _steel, _typed_foe)
from tests.test_tabletop_hunt6 import on_hold
from tests.h1_support import script

MOMENTUM_PREFIX = "tianxia.subpath.body.returning_heaven_momentum_body.feature."
STEEL = "tianxia.subpath.body.thousand_fold_steel_body.feature."
HOLD = "system:combat.hold_position"
CHARGE = "_round_edge_quench_charge"


def context(engine, actor, target, *, effects=(), targets=None):
    action = next(a for a in engine.action_catalog.values() if a.owner_id == actor.entity_id
                  and (a.parameters.get("typed") or {}).get("effects"))
    return te.Context(engine, actor, action, engine._active_intent, {**action.parameters["typed"], "effects": list(effects)},
                      targets or [target], target, {})


def prone(actor):
    return any(c.condition_id.endswith("prone") for c in actor.conditions.values())


@pytest.mark.parametrize("own_turn,stance,reach", [(True, False, 20), (False, False, 10),
                                                  (True, True, 25), (False, True, 15)])
def test_heron_reach_boundary_and_guard_gates(own_turn, stance, reach):
    engine, me, foe = _heron(["white_wing_crosses_the_reed_field", "one_legged_guard", "moon_over_the_reed_sea"])
    turn(engine, ME if own_turn else FOE)
    if stance:
        engine._apply_condition(me, "condition:typed.state.moon_reed_stance", HERON + "moon_over_the_reed_sea", ME,
                                expires_on="START_OF_SOURCE_NEXT_TURN", data={"name": "moon_reed_stance"})
    for distance, allowed in ((reach, True), (reach + 5, False)):
        foe.position = Position(x=3 + distance // 5, y=6)
        assert bool(white_heron._polearm_attacks(engine, me, foe)) == allowed
        engine._typed_pending_attack = {"attacker": FOE}
        guard_reach = 15 if stance else 10  # One-Legged Guard explicitly uses off-turn reach
        assert (white_heron.guard_needs_reach(engine, me, {"feature_id": HERON + "one_legged_guard"}) is not False) == (distance <= guard_reach)


@pytest.mark.parametrize("distance,damaged", [(20, True), (25, False), (30, False)])
def test_reaping_circle_uses_current_reach_once(distance, damaged):
    engine, me, foe = _heron(["white_wing_crosses_the_reed_field", "crescent_reaping_circle"],
                             foe_at=(3 + distance // 5, 6), picks={"reaping_circle_move": None})
    before = foe.current_hp
    # A saved/generated sweep row can already contain the increased reach.
    # Runtime resolution must use the weapon's base and gates, not add again.
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME
                  and a.display_name.startswith("Crescent Reaping Circle"))
    row = {**action.parameters["typed"]["effects"][0], "reach_ft": 20}
    te.run_effects(te.Context(engine, me, action, None, action.parameters["typed"], [me], me, {}),
                   [row])
    assert (foe.current_hp < before) == damaged


def test_moon_does_not_sweep_a_creature_outside_legal_reach():
    engine, me, foe = _heron(["white_wing_crosses_the_reed_field", "moon_over_the_reed_sea"], foe_at=(3, 11))
    before = foe.current_hp
    use(engine, "Moon over the Reed Sea", at=(4, 6))
    assert foe.current_hp == before  # 25 feet from every route cell, legal reach 20


def test_each_forced_movement_subject_starts_with_base_distance():
    engine, me, foe = _momentum(["gather_and_return"], foe_at=(5, 6))
    other = foe.model_copy(deep=True, update={"entity_id": "actor:test.second", "position": Position(x=5, y=8)})
    engine.state.actors[other.entity_id] = other
    from combat.ext.momentum_body import NEXT_PUSH
    engine._apply_condition(me, NEXT_PUSH, MOMENTUM_PREFIX + "gather_and_return", ME, expires_on="END_OF_CURRENT_TURN")
    ctx = context(engine, me, foe, targets=[foe, other])
    ctx.target = None
    te.run_effects(ctx, [{"type": "forced_movement", "applies_to": "targets", "distance_ft": 5, "direction": "away"}])
    assert foe.position == Position(x=7, y=6)
    assert other.position == Position(x=6, y=9)  # only first subject received consumable +5 feet


def test_store_protection_does_not_leak_to_later_same_source_in_one_engine():
    engine, me, foe = _momentum(["store_the_collision"], picks={"store_the_collision_move": ["store"]}, foe=_typed_foe())
    turn(engine, FOE)
    rows = [{"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away"},
            {"type": "condition", "applies_to": "target", "condition": "prone"}]
    first = context(engine, foe, me, effects=rows)
    te.run_effects(first, rows)
    assert not prone(me) and me.resources[MOMENTUM] == 1
    later = context(engine, foe, me, effects=rows)
    assert later.source == first.source
    te.run_effects(later, rows)
    assert prone(me)


def test_store_protection_is_replaced_by_a_later_movement_of_the_same_activation():
    engine, me, foe = _momentum(["store_the_collision"], picks={"store_the_collision_move": ["store"]}, foe=_typed_foe())
    turn(engine, FOE)
    move = {"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away"}
    rows = [move, move, {"type": "condition", "applies_to": "target", "condition": "prone"}]
    te.run_effects(context(engine, foe, me, effects=rows), rows)
    assert prone(me) and me.resources[MOMENTUM] == 1  # second movement was not stopped


def table_fight(tmp_path, ids, *, items=(), player_mode="MANUAL", ask=True):
    from combat.factory_compiler import compile_character
    mine = compile_character(sheet(ids, items=items, name="Player"), actor_id=ME, reaction_plan={"ask": ask})
    theirs = bundle([], actor_id=FOE, name="Enemy")
    combat = CombatService(ROOT, tmp_path)
    mid = combat._finish_factory_match(
        [mine, theirs], [ME, FOE], {ME: "team:a", FOE: "team:b"},
        {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME], [FOE],
        control_modes={ME: player_mode, FOE: "MANUAL"}, match_seed="C7-FIXUP", display_name="C7 fixup", maximum_rounds=5)["match_id"]
    return combat, TabletopService(combat, tmp_path), mid


def send(table, mid, *, label=None, at=None, answers_=(), auto=False):
    state = table.state(mid)
    if auto:
        return table.auto_step(mid, state["last_sequence"], list(answers_))
    menu = state["menu"]
    cid = menu["end_turn"] if label == "end" else next(o["candidate_id"] for g in menu["actions"]
                  if (g["label"].startswith(label) if label else g["source_definition_id"] == HOLD)
                  for o in g["options"] if at is None or o.get("destination") == {"x": at[0], "y": at[1]})
    return table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers_))


def to_turn(table, mid, actor):
    for _ in range(3):
        if table.state(mid)["menu"]["actor_id"] == actor:
            return
        assert send(table, mid, label="end")["status"] == "COMMITTED"
    raise AssertionError("actor did not get a turn")


def settle(table, mid, *, picks=None, label=None, at=None, auto=False):
    responses, prompts = [], []
    for _ in range(20):
        result = send(table, mid, label=label, at=at, answers_=responses, auto=auto)
        if result["status"] == "COMMITTED":
            return result, prompts
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        prompts.append(prompt)
        choice = prompt.get("choice")
        pick = next((v for k, v in (picks or {}).items() if prompt["context"]["reaction_source_id"].endswith(k)), "first")
        answer = {**prompt["context"], "selection": "DECLINE" if pick is None else "USE"}
        if choice and pick is not None:
            answer["option_ids"] = [choice["options"][0]["id"] if pick == "first" else pick]
        responses.append(answer)
    raise AssertionError("too many pauses")


def load(tmp_path, mid):
    return CombatService(ROOT, tmp_path)._load_session(mid)


@pytest.mark.parametrize("distance,stopped", [(10, True), (20, False)])
def test_store_movement_actual_branch_activation_and_reload(monkeypatch, tmp_path, distance, stopped):
    combat, table, mid = table_fight(tmp_path, [MOMENTUM_PREFIX + "store_the_collision"])
    to_turn(table, mid, FOE)
    def push(engine):
        actor, target = engine.state.actors[FOE], engine.state.actors[ME]
        rows = [{"type": "forced_movement", "distance_ft": distance, "direction": "away", "applies_to": "target"},
                {"type": "condition", "condition": "prone", "applies_to": "target"}]
        # Unrelated branch must not determine the triggering movement distance.
        ctx = context(engine, actor, target, effects=[*rows, {"type": "save", "on_success": [{"type": "forced_movement", "distance_ft": 40}]}])
        te.run_effects(ctx, rows)
    callbacks = [push]
    on_hold(monkeypatch, lambda engine: callbacks[0](engine))
    result, prompts = settle(table, mid, picks={"store_the_collision_move": "store"})
    assert any(p["reaction"] == "Store the Collision" for p in prompts)
    first = load(tmp_path, mid)
    me = first.engine.state.actors[ME]
    assert prone(me) != stopped
    assert me.resources[MOMENTUM] == (1 if stopped else 0)
    assert me.position == Position(x=3 if stopped else 2, y=6)
    assert first.mechanical.replay()["status"] == "PASS"
    # Fresh service and another same-source activation, without another Reaction.
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    to_turn(table, mid, ME)
    settle(table, mid, picks={"store_the_collision_move": None})
    later = load(tmp_path, mid)
    assert prone(later.engine.state.actors[ME])
    assert later.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("outcome", ["hit", "miss", "expire"])
def test_enemy_turn_edge_quench_survives_table_reload_and_next_turn(monkeypatch, tmp_path, outcome):
    combat, table, mid = table_fight(tmp_path, [STEEL + "body_forged_in_three_forms", STEEL + "quench_the_impact"])
    to_turn(table, mid, FOE)
    def damage(engine):
        engine._commit_damage(engine.state.actors[ME], 8, "FORCE", "test:hostile", FOE, engine._active_intent, reaction_depth=0)
    callbacks = [damage]
    on_hold(monkeypatch, lambda engine: callbacks[0](engine))
    settle(table, mid, picks={"quench_the_impact": "edge"})
    loaded = load(tmp_path, mid)
    assert CHARGE in loaded.engine.state.actors[ME].turn_flags
    assert loaded.mechanical.replay()["status"] == "PASS"
    # Stop the synthetic trigger, then cross the real turn-start/commit boundary.
    callbacks[0] = lambda engine: None
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    settle(table, mid, label="end", picks={"tempering_form": "edge"})
    assert CHARGE in load(tmp_path, mid).engine.state.actors[ME].turn_flags
    if outcome == "expire":
        settle(table, mid, label="end")
    else:
        def attack(engine):
            me, target = engine.state.actors[ME], engine.state.actors[FOE]
            script(engine, [19 if outcome == "hit" else 1, *([1] * 40)])
            te.run_effects(context(engine, me, target), [{"type": "attack", "attack_kind": "unarmed", "count": 1,
                                                       "on_hit": [{"type": "damage", "dice": {"count": 1, "sides": 4}, "damage_types": ["bludgeoning"]}]}])
        callbacks[0] = attack
        settle(table, mid)
    after = load(tmp_path, mid)
    assert CHARGE not in after.engine.state.actors[ME].turn_flags
    quench_rolls = [r for r in after.engine.rolls if r.expression.startswith("2d8")]
    assert bool(quench_rolls) == (outcome == "hit")
    assert after.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("outcome", ["hit", "miss", "expire"])
@pytest.mark.parametrize("cross_turn,dual", [(False, False), (True, False), (True, True)])
def test_pre_fix_edge_quench_save_consumption_and_expiry(monkeypatch, tmp_path, outcome, cross_turn, dual):
    combat, table, mid = table_fight(tmp_path, [STEEL + "body_forged_in_three_forms", STEEL + "quench_the_impact"])
    def advance_to_owner():
        if table.state(mid)["menu"]["actor_id"] != ME:
            settle(table, mid, label="end", picks={"tempering_form": "edge"})
        assert table.state(mid)["menu"]["actor_id"] == ME
    if cross_turn:
        to_turn(table, mid, FOE)
    else:
        advance_to_owner()
    def legacy_damage(engine):
        me = engine.state.actors[ME]
        engine._commit_damage(me, 8, "FORCE", "test:hostile", FOE, engine._active_intent, reaction_depth=0)
        # Persist the exact pre-1328c97 producer's record after the real paid
        # reaction. Do not migrate it in the fixture or edit a snapshot/lock.
        me.turn_flags["_edge_quench"] = me.turn_flags.pop(CHARGE)
        if dual:
            me.turn_flags[CHARGE] = dict(me.turn_flags["_edge_quench"])
            # A stale legacy record must not extend the refreshed deadline.
            me.turn_flags["_edge_quench"]["until"] += 10
    callbacks = [legacy_damage]
    on_hold(monkeypatch, lambda engine: callbacks[0](engine))
    settle(table, mid, picks={"quench_the_impact": "edge"})
    saved = load(tmp_path, mid)
    flags = saved.engine.state.actors[ME].turn_flags
    assert "_edge_quench" in flags and (CHARGE in flags) == dual
    assert type(flags["_edge_quench"]["until"]) is int
    assert saved.engine.state.actors[ME].resources[STAMINA] == 59
    assert saved.mechanical.replay()["status"] == "PASS"
    callbacks[0] = lambda engine: None
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    if cross_turn:
        settle(table, mid, label="end", picks={"tempering_form": "edge"})
        restored = load(tmp_path, mid)
        assert CHARGE in restored.engine.state.actors[ME].turn_flags
        assert "_edge_quench" not in restored.engine.state.actors[ME].turn_flags
        assert restored.mechanical.replay()["status"] == "PASS"
    if outcome == "expire":
        if not cross_turn:
            # Same-turn activation lasts through the owner's NEXT turn end.
            settle(table, mid, label="end")
            assert CHARGE in load(tmp_path, mid).engine.state.actors[ME].turn_flags
            advance_to_owner()
        settle(table, mid, label="end")
    else:
        def attack(engine):
            me, foe = engine.state.actors[ME], engine.state.actors[FOE]
            script(engine, [19 if outcome == "hit" else 1, *([1] * 40)])
            te.run_effects(context(engine, me, foe), [{"type": "attack", "attack_kind": "unarmed", "count": 1,
                          "on_hit": [{"type": "damage", "dice": {"count": 1, "sides": 4}, "damage_types": ["bludgeoning"]}]}])
        callbacks[0] = attack
        settle(table, mid)
    restored = load(tmp_path, mid)
    assert not {CHARGE, "_edge_quench"}.intersection(restored.engine.state.actors[ME].turn_flags)
    rolls = [r for r in restored.engine.rolls if r.expression.startswith("2d8")]
    assert len(rolls) == (1 if outcome == "hit" else 0)
    assert restored.mechanical.replay()["status"] == "PASS"
    # A later hit cannot spend either representation a second time.
    advance_to_owner()
    def later_hit(engine):
        me, foe = engine.state.actors[ME], engine.state.actors[FOE]
        script(engine, [19, *([1] * 40)])
        te.run_effects(context(engine, me, foe), [{"type": "attack", "attack_kind": "unarmed", "count": 1}])
    callbacks[0] = later_hit
    settle(table, mid)
    final = load(tmp_path, mid)
    assert len([r for r in final.engine.rolls if r.expression.startswith("2d8")]) == len(rolls)
    assert final.mechanical.replay()["status"] == "PASS"


def hold_ai(combat, mid, actor):
    """Drive the real AI transport with a deterministic accepted action."""
    from combat.gate4_adapters import ManualControllerAdapter
    combat.set_controller_mode(mid, actor_id=actor, controller_mode="LOCAL_AUTO")
    original = combat.controller
    class HoldController:
        def choose_primary_action(self, ctx):
            candidate = next(c for c in ctx.legal_candidates if c.source_definition_id == HOLD)
            return ManualControllerAdapter(lambda _: (candidate.candidate_id, ())).choose_primary_action(ctx)
        def __getattr__(self, key):
            return getattr(original, key)
    combat.controller = HoldController()


@pytest.mark.parametrize("player_mode,selection", [("MANUAL", "USE"), ("MANUAL", "DECLINE"), ("LOCAL_AUTO", "USE")])
def test_moon_optional_strike_on_ai_turn_pauses_commits_and_reloads(monkeypatch, tmp_path, player_mode, selection):
    combat, table, mid = table_fight(tmp_path, [HERON + "crescent_body_integration", HERON + "moon_over_the_reed_sea"],
                                   items=(JI,))
    to_turn(table, mid, ME)
    from combat.ext.rider_movement import step
    def stage(engine):
        me, foe = engine.state.actors[ME], engine.state.actors[FOE]
        if engine.state.current_actor_id == ME:
            step(engine, foe, [foe.position, Position(x=8, y=6)], "test:stage")
        else:
            step(engine, foe, [foe.position, Position(x=7, y=6), Position(x=6, y=6)], "test:enemy_advance")
    on_hold(monkeypatch, stage)
    settle(table, mid)
    settle(table, mid, label="Moon over the Reed Sea", at=(3, 7))
    held = load(tmp_path, mid)
    assert held.engine.state.actors[ME].turn_flags["_round_moon_free_strike"]
    assert held.engine.state.actors[ME].resources[STAMINA] == 53
    assert held.mechanical.replay()["status"] == "PASS"
    to_turn(table, mid, FOE)
    if player_mode == "LOCAL_AUTO":
        combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    hold_ai(combat, mid, FOE)
    before = load(tmp_path, mid).engine.state.model_dump(mode="json")
    first = send(table, mid, auto=True)
    responses = []
    if player_mode == "MANUAL":
        assert first["status"] == "REACTION_REQUIRED"
        prompt = first["reaction"]
        assert prompt["reaction"] == "Moon over the Reed Sea"
        assert "Enemy" in prompt["moment"] and "entered your reach" in prompt["moment"]
        assert prompt["choice"]["allow_decline"]
        assert load(tmp_path, mid).engine.state.model_dump(mode="json") == before
        assert send(table, mid, auto=True)["reaction"] == prompt
        answer = {**prompt["context"], "selection": selection}
        if selection == "USE":
            answer["option_ids"] = [prompt["choice"]["options"][0]["id"]]
        responses.append(answer)
        result = send(table, mid, auto=True, answers_=responses)
    else:
        assert first["status"] == "COMMITTED"  # AI chooses automatically
        result = first
    assert result["status"] == "COMMITTED", result
    after = load(tmp_path, mid)
    me = after.engine.state.actors[ME]
    strikes = [e for e in after.engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == ME]
    assert bool(strikes) == (selection == "USE")
    assert me.reaction_available and "_round_moon_free_strike" not in me.turn_flags
    assert after.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("distance", ["0", "15"])
def test_moon_failed_save_push_choice_through_table_reload(monkeypatch, tmp_path, distance):
    combat, table, mid = table_fight(tmp_path, [HERON + "crescent_body_integration", HERON + "moon_over_the_reed_sea"], items=(JI,))
    to_turn(table, mid, ME)
    result, prompts = settle(table, mid, label="Moon over the Reed Sea", at=(3, 7),
                             picks={"moon_over_the_reed_sea": FOE, "moon_push_distance": distance})
    prompt = next(p for p in prompts if p["context"]["reaction_source_id"].endswith("moon_push_distance"))
    assert {o["id"] for o in prompt["choice"]["options"]} == {"0", "5", "10", "15"}
    assert "Enemy" in prompt["moment"] and "failed its save" in prompt["moment"]
    loaded = load(tmp_path, mid)
    foe = loaded.engine.state.actors[FOE]
    assert loaded.engine.state.actors[ME].resources[STAMINA] == 53
    assert foe.position == Position(x=4 if distance == "0" else 5, y=6 if distance == "0" else 5)  # pillar stops the longer push
    assert any(c.condition_id.endswith("reaction_denied") for c in foe.conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_moon_single_attack_still_asks_and_can_be_declined():
    engine, me, foe = _heron(["moon_over_the_reed_sea"])
    attack = next(a for a in engine.action_catalog.values() if a.owner_id == ME
                  and a.display_name.startswith("Ji (Halberd) attack") and not a.parameters.get("reach_bonus"))
    engine.action_catalog = {attack.source_definition_id: attack}
    requests = []
    from combat.gate2_runtime_models import ActionIntent, ReactionDecision
    def decline(request):
        requests.append(request)
        return ReactionDecision(**{k: request[k] for k in ("checkpoint", "reactor_id", "reaction_source_id")}, selection="DECLINE"), None
    engine.set_reaction_provider(decline)
    intent = ActionIntent(intent_id="single-moon-strike", decision_id="test", candidate_id="test", state_version=0, actor_id=FOE)
    engine._active_intent = intent
    engine._apply_condition(me, "condition:typed.state.moon_reed_stance", HERON + "moon_over_the_reed_sea", ME,
                            expires_on="START_OF_SOURCE_NEXT_TURN", data={"name": "moon_reed_stance"})
    me.turn_flags["_round_moon_free_strike"] = True
    foe.position = Position(x=5, y=6)
    white_heron.moon_free_strike(engine, "MOVEMENT_COMMITTED", {"actor_id": FOE,
                               "payload": {"path": [{"x": 6, "y": 6}, {"x": 5, "y": 6}]}})
    assert len(requests) == 1 and len(requests[0]["extension_choice"]["option_ids"]) == 1
    assert requests[0]["extension_choice"]["allow_decline"]
    assert not any(e.event_type == "ATTACK_ROLLED" and e.actor_id == ME for e in engine.events)
