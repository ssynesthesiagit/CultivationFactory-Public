"""Review interactions through saved table transactions; no browser or live data."""
import pytest

from combat.gate2_runtime_models import Position
from combat.typed_executor import Context, run_effects
from tests.test_hunt32_edge import OWNER, act, match, reload
from tests.test_hunt32_hours import BORROW, DEBT, PAYMENT, borrow

AFTERIMAGE = "tianxia.subpath.body.shinobi.feature.shadow_afterimage"
LONG_ROAD = "TAL_SHADOW_LONG_ROAD_BETWEEN_LANTERNS"
WELL = "tianxia.tradition.spirit.well_of_hours.feature.the_well_has_no_bottom"
SMOKE = "tianxia.subpath.qi.ninpo_adept.feature.smoke_veil"


def at_cell(combat, table, mid, label, cell, answers=()):
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates()
                     if engine.action_catalog.get(c.source_definition_id)
                     and engine.action_catalog[c.source_definition_id].display_name == label
                     and c.destination == Position(x=cell[0], y=cell[1]))
    state = table.state(mid)
    menu = state["menu"]
    return table.act(mid, candidate.candidate_id, menu["decision_id"], menu["state_version"],
                     state["last_sequence"], list(answers))


def enter_payment(combat, table, mid, tmp_path, mode, selection):
    assert borrow(table, mid, combat, "MANUAL", stay=True)["status"] == "COMMITTED"
    assert act(table, mid)["status"] == "COMMITTED"
    if mode == "LOCAL_AUTO":
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=mode)
    result = act(table, mid)
    if mode == "MANUAL":
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        answer = {**prompt["context"], "selection": selection,
                  **({"option_ids": ["pay"]} if selection == "USE" else {})}
        result = act(table, mid, answers=[answer])
    assert result["status"] == "COMMITTED"
    engine = reload(combat, tmp_path, mid)
    assert any(c.condition_id == PAYMENT for c in engine.state.actors[OWNER].conditions.values()) == (selection == "USE")
    return engine


@pytest.mark.parametrize("source,label,effect_type", [
    (AFTERIMAGE, "Shadow Exchange", "shadow_exchange"),
    (LONG_ROAD, "Long Road Between Lanterns", "shadow_long_road"),
    (SMOKE, "Veil Escape", "veil_escape_move"),
])
@pytest.mark.parametrize("mode,selection", [("MANUAL", "USE"), ("MANUAL", "DECLINE"), ("LOCAL_AUTO", "USE")])
def test_custom_travel_activation_and_execution(tmp_path, source, label, effect_type, mode, selection):
    setup = ([{"name": "Setup afterimage", "target": "CELL",
               "effects": [{"type": "summon", "group": "shadow_afterimage"}]}]
             if source == AFTERIMAGE else
             [{"name": "Setup anchor", "target": "CELL", "effects": [{"type": "shadow_anchor"}]}])
    if source == SMOKE:
        setup = [{"name": "Setup smoke", "target": "CELL", "effects": [{"type": "zone"}],
                  "typed": {"zone_spec": {"name": "Smoke Veil", "shape": "sphere", "size_ft": 10,
                                         "duration": {"kind": "minutes", "amount": 1}}}}]
    combat, table, mid = match(tmp_path, [BORROW, source], primary="Resonance",
                               owner_resources={"resource:core.stamina": 30, "resource:core.qi": 30}, setup_actions=setup)
    assert at_cell(combat, table, mid, setup[0]["name"], (3, 7))["status"] == "COMMITTED"
    if source == LONG_ROAD:
        assert at_cell(combat, table, mid, setup[0]["name"], (3, 10))["status"] == "COMMITTED"
    baseline = reload(combat, tmp_path, mid)
    assert any(c.display_name == label or c.display_name.startswith(label + " at ")
               for c in baseline.legal_candidates()), "Fixture must make travel legal before repayment"
    engine = enter_payment(combat, table, mid, tmp_path, mode, selection)
    paid = selection == "USE"
    candidates = [c for c in engine.legal_candidates()
                  if c.display_name == label or c.display_name.startswith(label + " at ")]
    assert bool(candidates) == (not paid)
    actor = engine.state.actors[OWNER]
    before = actor.position.model_copy()
    before_move = actor.movement_remaining_ft
    pools = dict(actor.resources)
    action = next(a for a in engine.action_catalog.values() if a.display_name == label)
    if paid:
        assert actor.action_available and actor.bonus_action_available
        # Supplementary actual executor check on the reloaded table. Raw custom
        # rows (without metadata) also cannot bypass the registered effect gate.
        ctx = Context(engine, actor, action, None, action.parameters["typed"], [actor], actor,
                      {"_checkpoint_aim": Position(x=3, y=10)})
        events = len(engine.events)
        run_effects(ctx, [{"type": effect_type}])
        assert actor.position == before and actor.resources == pools
        assert not any(e.event_type in ("MOVEMENT_COMMITTED", "MOVEMENT_GRANTED") for e in engine.events[events:])
    else:
        # Decline executes the actual custom action, including its printed cost.
        if source in (AFTERIMAGE, SMOKE):
            result = act(table, mid, label)
        else:
            result = at_cell(combat, table, mid, label, (3, 10))
            answers = []
            while result["status"] == "REACTION_REQUIRED":
                answers.append({**result["reaction"]["context"], "selection": "DECLINE"})
                result = at_cell(combat, table, mid, label, (3, 10), answers)
        assert result["status"] == "COMMITTED"
        engine = reload(combat, tmp_path, mid)
        if source == SMOKE:
            assert engine.state.actors[OWNER].movement_remaining_ft == before_move + 5
        else:
            assert engine.state.actors[OWNER].position != before
            pool, cost = action.costs[0]
            assert engine.state.actors[OWNER].resources[pool] == pools[pool] - cost


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
def test_field_activation_survives_repayment_but_movement_rider_does_not(tmp_path, mode, monkeypatch):
    combat, table, mid = match(tmp_path, [BORROW, WELL], primary="Resonance")
    engine = enter_payment(combat, table, mid, tmp_path, mode, "USE")
    actor = engine.state.actors[OWNER]
    before_position = actor.position.model_copy()
    before_move = actor.movement_remaining_ft
    candidates = [c for c in engine.legal_candidates() if "The Well Has No Bottom" in c.display_name]
    assert candidates, "An optional movement benefit must not hide the field activation"
    if mode == "LOCAL_AUTO":
        # Exercise this exact field through the table with an AI owner, so
        # its creature selections are automatic. Spending an unrelated Attack
        # is not evidence of the field's repayment compatibility.
        original = combat.controller.choose_primary_action
        selected = candidates[0]
        def choose(context):
            available = tuple(
                c for c in context.legal_candidates
                if c.source_definition_id == selected.source_definition_id)
            assert available, "The AI's tactical representative must retain the legal field activation"
            return original(context.model_copy(update={"legal_candidates": available}))
        monkeypatch.setattr(combat.controller, "choose_primary_action", choose)
        try:
            result = table.auto_step(mid, table.state(mid)["last_sequence"])
            assert result["status"] == "COMMITTED"
        finally:
            monkeypatch.setattr(combat.controller, "choose_primary_action", original)
    else:
        answers = []
        for _ in range(8):
            result = act(table, mid, "The Well Has No Bottom", answers=answers)
            if result["status"] != "REACTION_REQUIRED":
                break
            prompt = result["reaction"]
            assert "The Well Has No Bottom" in str(prompt)
            # C8 adds the field's optional creature selection. Decline it;
            # field activation itself must still commit during repayment.
            answers.append({**prompt["context"], "selection": "DECLINE"})
        assert result["status"] == "COMMITTED"
    engine = reload(combat, tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert any(e.event_type == "RESOURCE_SPENT" and WELL in e.source_definition_id
               and e.payload.get("amount") == 10 for e in engine.events)
    assert any(WELL in z.source_definition_id for z in engine.state.zones.values())
    assert actor.position == before_position and actor.movement_remaining_ft == before_move
    assert any(c.condition_id == PAYMENT for c in actor.conditions.values())


@pytest.mark.parametrize("foe_mode", ["MANUAL", "LOCAL_AUTO"])
def test_stand_option_table_grants_ordinary_movement_and_debt(tmp_path, foe_mode):
    from tests.test_hunt32_edge import FOE
    setup = [{"name": "Setup Prone", "effects": [
        {"type": "condition", "applies_to": "self", "condition": "prone"}]}]
    combat, table, mid = match(tmp_path, [BORROW], primary="Resonance", setup_actions=setup)
    assert act(table, mid, "Setup Prone")["status"] == "COMMITTED"
    engine = reload(combat, tmp_path, mid)
    before = engine.state.actors[OWNER].movement_remaining_ft
    assert any(c.condition_id == "condition:typed.prone" for c in engine.state.actors[OWNER].conditions.values())
    # The reviewed C8 UI asks this decision through a named action.
    assert any(g["label"] == "Borrowed Second: Rise and Step" for g in table.state(mid)["menu"]["actions"])
    assert act(table, mid, "Borrowed Second: Rise and Step")["status"] == "COMMITTED"
    engine = reload(combat, tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert not any(c.condition_id == "condition:typed.prone" for c in actor.conditions.values())
    assert actor.movement_remaining_ft == before + 10 and actor.resources[DEBT] == 1
    assert not actor.turn_flags.get("oa_free_ft"), "Stand option preserves ordinary opportunity attacks"
    # Move out of the adjacent foe's reach via the table; it must get its normal
    # reaction prompt. Choosing it establishes actual ordinary OA execution.
    candidate = next(c for c in engine.legal_candidates()
                     if c.destination == Position(x=2, y=6) and c.kind.value == "MOVE")
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode=foe_mode)
    state = table.state(mid)
    def move(answers=()):
        return table.act(mid, candidate.candidate_id, state["menu"]["decision_id"],
                         state["menu"]["state_version"], state["last_sequence"], list(answers))
    result = move()
    if foe_mode == "MANUAL":
        assert result["status"] == "REACTION_REQUIRED"
        reaction = result["reaction"]
        result = move([{**reaction["context"], "selection": "USE"}])
    assert result["status"] == "COMMITTED"
    engine = reload(combat, tmp_path, mid)
    assert any(e.event_type == "REACTION_RESOLVED" and e.actor_id == FOE for e in engine.events)
    assert engine.state.actors[OWNER].resources[DEBT] == 1


def test_ai_prone_borrower_selects_stand_and_persists_ordinary_movement(tmp_path):
    setup = [{"name": "Setup Prone", "effects": [
        {"type": "condition", "applies_to": "self", "condition": "prone"}]}]
    combat, table, mid = match(tmp_path, [BORROW], primary="Resonance", setup_actions=setup)
    assert act(table, mid, "Setup Prone")["status"] == "COMMITTED"
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    for _ in range(12):
        previous = reload(combat, tmp_path, mid).state.actors[OWNER]
        assert table.auto_step(mid, table.state(mid)["last_sequence"])["status"] == "COMMITTED"
        if reload(combat, tmp_path, mid).state.actors[OWNER].resources.get(DEBT, 0):
            break
    else:
        pytest.fail("AI did not borrow")
    # The new movement-only Stand Up is preferred before Borrowed Motion.
    assert not any(c.condition_id == "condition:typed.prone" for c in previous.conditions.values())
    assert any(e.event_type == "CONDITION_REMOVED" and e.source_definition_id == "system:combat.stand_up"
               for e in reload(combat, tmp_path, mid).events)
    before = previous.movement_remaining_ft
    actor = reload(combat, tmp_path, mid).state.actors[OWNER]
    assert not any(c.condition_id == "condition:typed.prone" for c in actor.conditions.values())
    # Rise is no longer legal after standing. The AI borrows Disengage instead,
    # which grants no movement and pays the same one Time Debt.
    assert actor.movement_remaining_ft == before and actor.resources[DEBT] == 1
    assert actor.turn_flags.get("disengaged")
    assert not actor.turn_flags.get("oa_free_ft")
