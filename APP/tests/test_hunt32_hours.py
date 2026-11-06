"""Borrowing and repayment are separate saved table transactions."""
import pytest

from tests.test_hunt32_edge import FOE, OWNER, act, match, reload

BORROW = "tianxia.tradition.spirit.well_of_hours.feature.borrowed_second"
DEBT = "resource:named.time_debt"
PAYMENT = "condition:typed.paying_the_second_back"

DESCENTS = [
    ("tianxia.subpath.body.nine_star_meridian_body.feature.falling_star_descent",
     "Falling-Star Descent", "resource:named.celestial_mark"),
    ("tianxia.subpath.body.adamant_thunderbolt_body.feature.adamantine_descent",
     "Adamantine Descent", "resource:named.thunder_charge"),
]


@pytest.mark.parametrize("source,label,pool", DESCENTS)
@pytest.mark.parametrize("owner_mode,selection", [("MANUAL", "USE"), ("MANUAL", "DECLINE"), ("LOCAL_AUTO", "USE")])
def test_repayment_forbids_descent_powers_before_their_costs(tmp_path, source, label, pool, owner_mode, selection):
    combat, table, mid = match(tmp_path, [BORROW, source], primary="Resonance",
                               owner_resources={pool: 3, "resource:core.stamina": 30})
    assert any(g["label"] == label for g in table.state(mid)["menu"]["actions"])
    assert borrow(table, mid, combat, "MANUAL")["status"] == "COMMITTED"
    assert act(table, mid)["status"] == "COMMITTED"
    before_payment = reload(combat, tmp_path, mid).state.actors[OWNER]
    starting_pools = {p: before_payment.resources[p] for p in (pool, "resource:core.stamina")}
    if owner_mode == "LOCAL_AUTO":
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=owner_mode)
        result = act(table, mid)
    else:
        result = act(table, mid)
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        answer = {**prompt["context"], "selection": selection,
                  **({"option_ids": [prompt["choice"]["options"][0]["id"]]} if selection == "USE" else {})}
        result = act(table, mid, answers=[answer])
    assert result["status"] == "COMMITTED"
    engine = reload(combat, tmp_path, mid)
    actor = engine.state.actors[OWNER]
    paid = selection == "USE"
    assert any(c.condition_id == PAYMENT for c in actor.conditions.values()) == paid
    offered = any(c.display_name.startswith(label + " at ") for c in engine.legal_candidates())
    assert offered == (not paid), "Payment forbids activating a power whose primary effect moves you"
    if owner_mode == "MANUAL":
        assert any(g["label"] == label for g in table.state(mid)["menu"]["actions"]) == (not paid)
    assert {p: actor.resources[p] for p in starting_pools} == starting_pools
    # Free/nested packets use the same rule, independently of candidate menus.
    from combat.ext.borrowed_second import payment_effects
    from combat.typed_executor import Context
    action = next(a for a in engine.action_catalog.values() if (a.parameters.get("typed") or {}).get("source") == source)
    ctx = Context(engine, actor, action, None, action.parameters["typed"], [actor], actor, {})
    row = next(r for r in ctx.typed["effects"] if r["type"] == "move_to_aim")
    assert payment_effects(ctx, row) == (False if paid else None)


def borrow(table, mid, combat, mode, *, stay=False):
    if mode == "LOCAL_AUTO":
        for _ in range(12):
            result = table.auto_step(mid, table.state(mid)["last_sequence"])
            assert result["status"] == "COMMITTED"
            if any(e.event_type == "RESOURCE_GAINED" and e.payload.get("resource_id") == DEBT
                   for e in combat._load_session(mid).engine.events):
                return result
        pytest.fail("AI did not use Borrowed Second")
    answers = []
    for _ in range(5):
        # C8 exposes the printed options as named actions. Disengage borrows
        # the same one-debt second without moving the repayment fixture.
        result = act(table, mid, "Borrowed Second: Disengage", answers=answers)
        if result["status"] == "COMMITTED":
            return result
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        if stay and all(o["id"].startswith("cell:") for o in prompt["choice"]["options"]):
            answers.append({**prompt["context"], "selection": "DECLINE"})
            continue
        option = next((o for o in prompt["choice"]["options"] if o["id"] == "move"), prompt["choice"]["options"][0])
        answers.append({**prompt["context"], "selection": "USE", "option_ids": [option["id"]]})
    pytest.fail("Borrowed Second choice did not settle")


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
def test_borrowing_creates_debt_without_paying_or_losing_reactions(tmp_path, mode):
    combat, table, mid = match(tmp_path, [BORROW], primary="Resonance", mode=mode)
    assert borrow(table, mid, combat, mode)["status"] == "COMMITTED"
    engine = reload(combat, tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.resources[DEBT] == 1
    assert actor.reaction_available
    assert actor.resources["resource:core.resonance"] == 27
    assert not any(c.condition_id == PAYMENT for c in actor.conditions.values())


@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
@pytest.mark.parametrize("foe_mode", ["MANUAL", "LOCAL_AUTO"])
def test_manual_owner_is_asked_on_next_turn_even_during_ai_end_turn(tmp_path, selection, foe_mode):
    combat, table, mid = match(tmp_path, [BORROW], primary="Resonance")
    assert borrow(table, mid, combat, "MANUAL")["status"] == "COMMITTED"
    assert act(table, mid)["status"] == "COMMITTED"
    # Switch only the scratch opponent's service control setting, never mechanical state.
    if foe_mode == "LOCAL_AUTO":
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode=foe_mode)
    before = reload(combat, tmp_path, mid).state.model_dump(mode="json")
    if foe_mode == "MANUAL":
        result = act(table, mid)
    else:
        for _ in range(12):
            before = reload(combat, tmp_path, mid).state.model_dump(mode="json")
            result = table.auto_step(mid, table.state(mid)["last_sequence"])
            if result["status"] == "REACTION_REQUIRED":
                break
    assert result["status"] == "REACTION_REQUIRED", "Repayment is optional and must ask the manual owner"
    assert reload(combat, tmp_path, mid).state.model_dump(mode="json") == before
    prompt = result["reaction"]
    text = str(prompt)
    assert "Pay the Second Back" in text and "Borrowed Second" in text
    assert "Speed" in text and "Reaction" in text and "2 Time Debt" in text
    answer = {**prompt["context"], "selection": selection,
              **({"option_ids": [prompt["choice"]["options"][0]["id"]]} if selection == "USE" else {})}
    result = act(table, mid, answers=[answer]) if foe_mode == "MANUAL" else table.auto_step(mid, table.state(mid)["last_sequence"], [answer])
    assert result["status"] == "COMMITTED"
    engine = reload(combat, tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.resources[DEBT] == (0 if selection == "USE" else 1)
    assert actor.reaction_available == (selection == "DECLINE")
    if selection == "USE":
        assert engine._effective_speed(actor) == 0
        assert not any(c.display_name == "Borrowed Second" or c.destination is not None for c in engine.legal_candidates())
        assert any(c.condition_id == PAYMENT for c in actor.conditions.values())
    else:
        assert engine._effective_speed(actor) == 30
    # Forgo borrowing next round, then reach the next turn: all payment restrictions expire.
    assert act(table, mid)["status"] == "COMMITTED"
    if foe_mode == "MANUAL":
        result = act(table, mid)
        if selection == "DECLINE":
            # C8 adds the printed end-of-turn debt decay: this quiet turn
            # neither gained debt nor activated a Well of Hours feature.
            assert result["status"] == "COMMITTED"
            assert reload(combat, tmp_path, mid).state.actors[OWNER].resources[DEBT] == 0
        assert result["status"] == "COMMITTED"
    else:
        for _ in range(12):
            result = table.auto_step(mid, table.state(mid)["last_sequence"])
            if result["status"] == "REACTION_REQUIRED" or result["state"]["menu"]["actor_id"] == OWNER:
                break
        if selection == "DECLINE":
            assert result["status"] == "COMMITTED"
            assert reload(combat, tmp_path, mid).state.actors[OWNER].resources[DEBT] == 0
    engine = reload(combat, tmp_path, mid)
    assert not any(c.condition_id == PAYMENT for c in engine.state.actors[OWNER].conditions.values())
    assert engine._effective_speed(engine.state.actors[OWNER]) == 30


def test_ai_owner_repays_automatically_and_payment_expires_on_its_next_turn(tmp_path):
    combat, table, mid = match(tmp_path, [BORROW], primary="Resonance", mode="LOCAL_AUTO")
    assert borrow(table, mid, combat, "LOCAL_AUTO")["status"] == "COMMITTED"
    for _ in range(12):
        if table.state(mid)["menu"]["actor_id"] == FOE:
            break
        assert table.auto_step(mid, table.state(mid)["last_sequence"])["status"] == "COMMITTED"
    assert act(table, mid)["status"] == "COMMITTED"  # entering the AI owner's turn never asks a player
    engine = reload(combat, tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.resources[DEBT] == 0
    assert not actor.reaction_available and engine._effective_speed(actor) == 0
    assert any(c.condition_id == PAYMENT for c in actor.conditions.values())
    assert not any(c.display_name == "Borrowed Second" for c in engine.legal_candidates())
    for _ in range(12):
        if table.state(mid)["menu"]["actor_id"] == FOE:
            break
        assert table.auto_step(mid, table.state(mid)["last_sequence"])["status"] == "COMMITTED"
    assert act(table, mid)["status"] == "COMMITTED"
    engine = reload(combat, tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.reaction_available and engine._effective_speed(actor) == 30
    assert not any(c.condition_id == PAYMENT for c in actor.conditions.values())


def test_payment_blocks_free_steps_and_teleports_but_survives_forced_movement(tmp_path):
    from combat.ext.borrowed_second import payment_effects, payment_teleport
    from combat.ext.rider_movement import forced_route
    from combat.typed_executor import Context

    combat, table, mid = match(tmp_path, [BORROW, "TAL_SPACE_FOLD_STEP"], primary="Resonance")
    assert borrow(table, mid, combat, "MANUAL")["status"] == "COMMITTED"
    assert act(table, mid)["status"] == "COMMITTED"
    pause = act(table, mid)
    assert pause["status"] == "REACTION_REQUIRED"
    prompt = pause["reaction"]
    answer = {**prompt["context"], "selection": "USE", "option_ids": [prompt["choice"]["options"][0]["id"]]}
    assert act(table, mid, answers=[answer])["status"] == "COMMITTED"
    engine = reload(combat, tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert not any(c.display_name == "Fold Step" for c in engine.legal_candidates())
    action = next(a for a in engine.action_catalog.values() if str((a.parameters.get("typed") or {}).get("source") or "").startswith(BORROW))
    ctx = Context(engine, actor, action, None, action.parameters["typed"], [actor], actor, {})
    assert payment_effects(ctx, {"type": "gain_resource", "applies_to": "self"}) is False
    # Unrelated source effects retain their independent forced-movement path.
    ctx.typed = {"source": "test:other", "numbers": ctx.numbers}
    assert payment_effects(ctx, {"type": "movement", "applies_to": "self"}) is False
    assert payment_effects(ctx, {"type": "teleport", "applies_to": "self"}) is False
    assert payment_teleport(ctx, actor.position, actor.position) is False
    assert payment_effects(ctx, {"type": "forced_movement", "applies_to": "target"}) is None
    # Supplementary engine check on the reloaded scratch fight: an involuntary step keeps the payment.
    from combat.gate2_runtime_models import Position
    destination = Position(x=actor.position.x, y=actor.position.y + 1)
    forced_route(engine, actor, [actor.position, destination], "test:forced", engine.state.actors[FOE])
    assert actor.position == destination
    assert engine._effective_speed(actor) == 0 and not actor.reaction_available
    assert any(c.condition_id == PAYMENT for c in actor.conditions.values())
