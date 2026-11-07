"""Review regressions through committed table actions and cold mechanical reloads."""
import pytest

from combat import ext
from tests.test_auto105_puppetry_movement import (
    LEFT, RIGHT, OWNED, KNEE, STEP, NO_OA, KNEE_ASK, STEP_ASK,
    scene, turn_to, far_move, move_sender, asked_about, is_prone,
)
from tests.auto28_puppetry_support import resolve
from tests.auto_worker1_support import reload
from tests.test_auto105_puppetry_movement import _raise, first_step_cell, STEP_SQUARE, has_mark


def vessel_send(combat, table, mid, suffix, xy, *, ai=False):
    engine = reload(combat, mid)
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id.endswith(suffix)
                     and c.destination and (c.destination.x, c.destination.y) == xy)
    return move_sender(table, mid, candidate, ai=ai)


def add_hook(monkeypatch, name, fn):
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, name, [*ext._HOOKS.get(name, []), fn])


@pytest.mark.parametrize("raw_success,settled_success", [(False, True), (True, False)])
def test_knee_uses_settled_save_and_preserves_prone_defense_metadata(tmp_path, monkeypatch, raw_success, settled_success):
    from tests.test_lock_choices import install

    if raw_success:
        install(monkeypatch, "d20_bonus", lambda *a: {"source_id": "test:knee", "bonus": 200})
    named = []
    def defense(ctx, subject, ability, conditions):
        if ctx.source == KNEE:
            named.append(conditions)
    def settle(ctx, subject, ability, conditions, failed):
        if ctx.source == KNEE:
            ctx.engine.__dict__.setdefault("_typed_roll_outcome", {})[subject.entity_id] = (
                "success" if settled_success else "failure")
    add_hook(monkeypatch, "save", defense)
    add_hook(monkeypatch, "after_save", settle)
    combat, table, mid, _ = scene(tmp_path, [*OWNED, KNEE])
    turn_to(table, mid, RIGHT)
    engine = reload(combat, mid)
    before = engine.state.actors[RIGHT].position
    resolve(move_sender(table, mid, far_move(engine, engine.state.actors[RIGHT], 10)), NO_OA)
    after = reload(combat, mid)
    assert named and all("prone" in n for n in named)
    assert is_prone(after.state.actors[RIGHT]) is not settled_success
    if not settled_success:
        assert after.grid.distance_ft(before, after.state.actors[RIGHT].position) == 5


def test_knee_falls_at_completed_step_even_when_no_second_attempt(tmp_path, monkeypatch):
    def end_step(engine, mover, previous, nxt, intent):
        if mover.entity_id == RIGHT:
            return {"stop": True, "source_id": "test:entry-stop", "label": "The entry hazard stops the move."}
    add_hook(monkeypatch, "movement_step", end_step)
    combat, table, mid, _ = scene(tmp_path, [*OWNED, KNEE])
    turn_to(table, mid, RIGHT)
    engine = reload(combat, mid)
    resolve(move_sender(table, mid, far_move(engine, engine.state.actors[RIGHT], 10)), NO_OA)
    after = reload(combat, mid)
    assert is_prone(after.state.actors[RIGHT])
    assert not any("pending_knee" in c.condition_id for c in after.state.actors[RIGHT].conditions.values())


def test_threaded_step_offered_without_any_mark(tmp_path):
    from combat.ext import placed
    from tests.auto_worker1_support import act

    combat, table, mid, ally = scene(tmp_path, [*OWNED, STEP], ally=True, marked=False)
    engine = reload(combat, mid)
    assert not any("tension_mark" in c.condition_id for c in engine.state.actors[RIGHT].conditions.values())
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id.endswith("vessel.move")
                     and c.destination and engine.grid.distance_ft(placed.of(engine, "vessel")[0].center, c.destination) > 0
                     and engine.grid.distance_ft(engine.state.actors[ally].position, c.destination) <= 5)
    _, prompts = resolve(move_sender(table, mid, candidate), {STEP_ASK: []})
    assert asked_about(prompts, STEP_ASK)


def test_raise_completed_movement_grants_one_step_and_second_receipt_is_inert(tmp_path):
    from combat.ext import vessel
    combat, table, mid, ally = scene(tmp_path, [*OWNED, STEP, vessel.TWO_BODY], ally=True, marked=False)
    turn_to(table, mid, RIGHT)
    turn_to(table, mid, LEFT)
    before = reload(combat, mid)
    # The raised vessel really walks to a square adjacent to the ally.
    _, prompts = resolve(vessel_send(combat, table, mid, "vessel.raise", (5, 8)), {
        "choice:needle.vessel_raise_move": ["cell:4,8"], STEP_ASK: [ally],
        STEP_SQUARE: [first_step_cell(before, ally)],
    })
    assert asked_about(prompts, STEP_ASK)
    after = reload(combat, mid)
    assert after.grid.distance_ft(before.state.actors[ally].position, after.state.actors[ally].position) == 5
    # A second completed vessel movement this turn must not grant another step.
    ally_cell = after.state.actors[ally].position
    destination = (ally_cell.x, ally_cell.y + 1)
    _, prompts = resolve(vessel_send(combat, table, mid, "vessel.move", destination), {
        "choice:needle.vessel_group_move": [], STEP_ASK: [ally],
    })
    assert not asked_about(prompts, STEP_ASK)
    final = reload(combat, mid)
    from combat.ext import placed
    arrived = next(z for z in placed.of(final, "vessel") if (z.center.x, z.center.y) == destination)
    assert final.grid.distance_ft(final.state.actors[ally].position, arrived.center) == 5
    assert final.state.actors[ally].position == after.state.actors[ally].position


@pytest.mark.parametrize("group_moves", [False, True])
def test_step_is_bound_to_the_vessel_that_actually_moved(tmp_path, group_moves):
    from combat.ext import vessel, placed
    combat, table, mid, ally = scene(tmp_path, [*OWNED, STEP, vessel.TWO_BODY], ally=True)
    turn_to(table, mid, RIGHT)
    turn_to(table, mid, LEFT)
    _raise(table, combat, mid, 3, 8)
    before = reload(combat, mid)
    assert len(placed.of(before, "vessel")) == 2
    _, prompts = resolve(vessel_send(combat, table, mid, "vessel.move", (7, 6)), {
        "choice:needle.vessel_group_move": ["cell:4,8"] if group_moves else [], STEP_ASK: [],
    })
    asked = asked_about(prompts, STEP_ASK)
    assert bool(asked) is group_moves
    if group_moves:
        assert "(4, 8)" in str(asked[0]), "the prompt must name the moved group vessel"
    after = reload(combat, mid)
    assert after.state.actors[ally].position == before.state.actors[ally].position


@pytest.mark.parametrize("first_can_react", [False, True])
def test_each_eligible_mark_owner_gets_one_pre_step_choice(tmp_path, first_can_react):
    from tests.auto_worker1_support import act
    combat, table, mid, second = scene(tmp_path, [*OWNED, KNEE], ally=True, second_puppeteer=True)
    turn_to(table, mid, second)
    _raise(table, combat, mid, 5, 7)
    assert act(table, mid, "Thread the Mark", target_id=RIGHT)["status"] == "COMMITTED"
    turn_to(table, mid, RIGHT)
    # A cold reload canonicalizes actor order; spend the first actual marked
    # owner's Reaction rather than assuming the fixture's creation order.
    engine = reload(combat, mid)
    first = next(a.entity_id for a in engine.state.actors.values() if a.entity_id in {LEFT, second})
    if not first_can_react:
        short = next(c for c in engine.legal_candidates() if c.source_definition_id == "system:combat.movement"
                     and c.destination and (c.destination.x, c.destination.y) == (5, 6))
        # A real leave-reach attack spends the first owner's Reaction before the longer move.
        send = move_sender(table, mid, short)
        answers = []
        for _ in range(12):
            result = send(answers)
            if result["status"] == "COMMITTED":
                break
            assert result["status"] == "REACTION_REQUIRED", result
            prompt = result["reaction"]
            first_owner = prompt["context"]["reactor_id"] == first
            options = [o["id"] for o in (prompt.get("choice") or {}).get("options", [])]
            answers.append({**prompt["context"], "selection": "USE" if first_owner else "DECLINE",
                            "option_ids": options[:1] if first_owner else []})
        else:
            raise AssertionError("too many short-move reaction choices")
        prepared = reload(combat, mid)
        assert not prepared.state.actors[first].reaction_available
        assert prepared.state.actors[next(a for a in (LEFT, second) if a != first)].reaction_available
    engine = reload(combat, mid)
    _, prompts = resolve(move_sender(table, mid, far_move(engine, engine.state.actors[RIGHT], 10)),
                         {**NO_OA, KNEE_ASK: []})
    asked = asked_about(prompts, KNEE_ASK)
    assert {p["context"]["reactor_id"] for p in asked} == ({LEFT, second} if first_can_react else {LEFT, second} - {first})
    assert len(asked) == (2 if first_can_react else 1)
    assert all("KNOT_THE_KNEE" in p["context"]["checkpoint"] for p in asked)
    after = reload(combat, mid)
    assert has_mark(after.state.actors[RIGHT], second)
    assert has_mark(after.state.actors[RIGHT], LEFT)


def test_old_sealed_knee_owner_keeps_legacy_completed_move_timing(tmp_path):
    combat, table, mid, _ = scene(tmp_path, [*OWNED, KNEE], legacy=True)
    turn_to(table, mid, RIGHT)
    engine = reload(combat, mid)
    before = engine.state.actors[RIGHT].position
    _, prompts = resolve(move_sender(table, mid, far_move(engine, engine.state.actors[RIGHT], 10)), NO_OA)
    assert not asked_about(prompts, KNEE_ASK)
    after = reload(combat, mid)
    assert after.grid.distance_ft(before, after.state.actors[RIGHT].position) > 5


@pytest.mark.parametrize("marked", [False, True])
def test_step_really_leaves_reach_and_exempts_only_the_selected_enemy(tmp_path, marked):
    combat, table, mid, ally = scene(tmp_path, [*OWNED, STEP], ally=True, marked=marked, extra_enemy=True)
    before = reload(combat, mid)
    _, prompts = resolve(vessel_send(combat, table, mid, "vessel.move", (4, 7)), {
        STEP_ASK: [ally], "choice:needle.threaded_step_exempt": [RIGHT], STEP_SQUARE: ["cell:2,7"],
    })
    assert asked_about(prompts, STEP_SQUARE)
    after = reload(combat, mid)
    assert after.grid.distance_ft(before.state.actors[ally].position, after.state.actors[ally].position) == 5
    attackers = {e.actor_id for e in after.events[len(before.events):] if e.event_type == "REACTION_RESOLVED"
                 and e.source_definition_id == "system:combat.opportunity_attack" and ally in e.target_ids}
    assert attackers == ({"actor:factory.auto105-enemy2"} if marked else {RIGHT, "actor:factory.auto105-enemy2"})
    assert after.state.actors[RIGHT].reaction_available is marked
    assert not after.state.actors["actor:factory.auto105-enemy2"].reaction_available


def test_ai_puppeteer_answers_knee_automatically(tmp_path):
    combat, table, mid, _ = scene(tmp_path, [*OWNED, KNEE])
    turn_to(table, mid, RIGHT)
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
    engine = reload(combat, mid)
    _, prompts = resolve(move_sender(table, mid, far_move(engine, engine.state.actors[RIGHT], 10)), NO_OA)
    assert not asked_about(prompts, KNEE_ASK)
    after = reload(combat, mid)
    assert is_prone(after.state.actors[RIGHT])
    assert not has_mark(after.state.actors[RIGHT], LEFT)


def test_knee_cancels_unwalked_fall_on_blocked_entry_and_pending_data_is_portable(tmp_path, monkeypatch):
    captured = []
    def blocked(engine, mover, previous, nxt, intent):
        if mover.entity_id == RIGHT:
            pending = [c for c in mover.conditions.values() if "pending_knee" in c.condition_id]
            captured.extend(pending)
            return {"stop": True, "source_id": "test:blocked-entry", "label": "The first square is blocked."}
    add_hook(monkeypatch, "movement_attempt", blocked)
    combat, table, mid, _ = scene(tmp_path, [*OWNED, KNEE])
    turn_to(table, mid, RIGHT)
    engine = reload(combat, mid)
    start = engine.state.actors[RIGHT].position
    resolve(move_sender(table, mid, far_move(engine, engine.state.actors[RIGHT], 10)), NO_OA)
    assert captured and all(type(v) in (int, str) for c in captured for v in c.data.values())
    after = reload(combat, mid)
    assert after.state.actors[RIGHT].position == start
    assert not is_prone(after.state.actors[RIGHT])
    assert not any("pending_knee" in c.condition_id for c in after.state.actors[RIGHT].conditions.values())


def test_one_canonical_native_feature_declaration():
    import json
    from tests.h1_support import ROOT
    for feature in ("PUPPETRY_BASE_RAISE_THE_VESSEL", "tianxia.talent.puppetry.little_servant_s_errand"):
        sources = [p.name for p in (ROOT / "combat/rules/feature_blocks.d").glob("*.json")
                   if feature in json.loads(p.read_text()).get("features", {})]
        assert sources == ["auto28_second_pass.json"], sources


def test_manual_ally_chooses_threaded_step_on_ai_puppeteer_turn(tmp_path, monkeypatch):
    from dataclasses import replace
    from combat.gate2_runtime_models import Position

    def vessel_walk(ctx, effect):
        # Prepared-object actions intentionally remain player_only (AUTO28 P1).
        # An AI-safe fixture action grants the real vessel movement, testing
        # its receipt/ally choice without claiming automatic object preparation.
        intent = ctx.intent.model_copy(update={"destination": Position(x=4, y=7)})
        ext.effects()["vessel_move"](replace(ctx, intent=intent), {"type": "vessel_move"})
    monkeypatch.setitem(ext.effects(), "test_puppetry_vessel_walk", vessel_walk)
    combat, table, mid, ally = scene(tmp_path, [*OWNED, STEP], ally=True,
        left_effects=[{"type": "test_puppetry_vessel_walk"}])
    before = reload(combat, mid)
    candidate = next(c for c in before.legal_candidates() if c.display_name == "Two Walks")
    _, prompts = resolve(move_sender(table, mid, candidate, ai=True), {
        STEP_SQUARE: ["cell:2,7"],
    })
    assert not asked_about(prompts, STEP_ASK), "the AI owner chooses its ally automatically"
    asked = asked_about(prompts, STEP_SQUARE)
    assert asked and all(p["context"]["reactor_id"] == ally for p in asked)
    assert "Threaded Step Formation" in str(asked[0]) and "5" in str(asked[0])
    after = reload(combat, mid)
    assert after.grid.distance_ft(before.state.actors[ally].position, after.state.actors[ally].position) == 5


def test_separate_walks_in_one_action_each_offer_a_declined_knee(tmp_path, monkeypatch):
    from combat.ext.granted_movement import choices, move
    from tests.auto_worker1_support import act

    def walks(ctx, effect):
        for _ in range(2):
            candidate = next(c for c in choices(ctx.engine, ctx.actor, 10)
                             if c.movement_cost_ft == 10
                             and ctx.engine.grid.distance_ft(ctx.engine.state.actors[LEFT].position,
                                                             c.destination) <= 5)
            move(ctx.engine, ctx.actor, candidate, ctx.intent, 10, [], name="Test walk")
    monkeypatch.setitem(ext.effects(), "test_puppetry_walks", walks)
    combat, table, mid, _ = scene(tmp_path, [*OWNED, KNEE], right_effects=[{"type": "test_puppetry_walks"}])
    turn_to(table, mid, RIGHT)
    before = reload(combat, mid)
    _, prompts = resolve(lambda answers: act(table, mid, "Two Walks", answers), {**NO_OA, KNEE_ASK: []})
    assert len(asked_about(prompts, KNEE_ASK)) == 2
    after = reload(combat, mid)
    walked = [e for e in after.events[len(before.events):]
              if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == RIGHT]
    assert len(walked) == 2 and all(len(e.payload["path"]) == 3 for e in walked)
    assert has_mark(after.state.actors[RIGHT], LEFT)
    assert after.state.actors[LEFT].reaction_available


def test_prone_defense_is_resolved_at_the_fall_and_can_prevent_it(tmp_path, monkeypatch):
    distances = []
    def prevent(ctx, subject, effect):
        if ctx.source == KNEE and effect.get("condition") == "prone":
            from combat.movement_steps import context
            distances.append(context(ctx.engine, subject).get("travelled_ft"))
            return False
    add_hook(monkeypatch, "condition_attempt", prevent)
    combat, table, mid, _ = scene(tmp_path, [*OWNED, KNEE])
    turn_to(table, mid, RIGHT)
    engine = reload(combat, mid)
    before = engine.state.actors[RIGHT].position
    resolve(move_sender(table, mid, far_move(engine, engine.state.actors[RIGHT], 10)), NO_OA)
    assert distances and all(n == 5 for n in distances)
    after = reload(combat, mid)
    assert not is_prone(after.state.actors[RIGHT])
    assert after.grid.distance_ft(before, after.state.actors[RIGHT].position) > 5


@pytest.mark.parametrize("marked", [False, True])
def test_old_sealed_step_owner_keeps_its_owned_movement_grant(tmp_path, marked):
    combat, table, mid, ally = scene(tmp_path, [*OWNED, STEP], ally=True, legacy=True, marked=marked)
    before = reload(combat, mid)
    _, prompts = resolve(vessel_send(combat, table, mid, "vessel.move", (4, 7)), {
        STEP_ASK: [ally], STEP_SQUARE: ["cell:2,7"],
    })
    assert len(asked_about(prompts, STEP_ASK)) == 1
    after = reload(combat, mid)
    assert after.grid.distance_ft(before.state.actors[ally].position, after.state.actors[ally].position) == 5
