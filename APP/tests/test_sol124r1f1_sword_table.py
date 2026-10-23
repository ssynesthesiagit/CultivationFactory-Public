"""Life-Severing payment follows the compiled use gate across table reloads."""
from combat.ext import reaction_economy, sword_core
from combat.gate4_adapters import ManualControllerAdapter
from combat.typed_executor import bears_mark
from tests import test_ocf8_sword_core as S
from tests import test_sol124f1_sword_table as F


def test_unmarked_opportunity_rider_is_paid_once_per_creature_turn_after_reload(tmp_path):
    combat, table, mid, owners, target = F.fixture(
        tmp_path, "R1F1-REPEAT", two_owners=False, extra_reaction=True)
    owner = owners[0]
    for _ in range(20):
        state = table.state(mid)
        if state["menu"]["actor_id"] == owner:
            # The real bonus-action incarnation supplies an unrestricted extra
            # Reaction; no injected flags, marks or resource resets.
            result = S._press(table, mid, state["menu"], state, label="Adamant Guardian Incarnation")
            assert result["status"] == "COMMITTED"
            break
        F.advance(table, mid, state)
    else:
        raise AssertionError("swordsman's turn not reached")

    production = combat.controller

    class DepartingAI:
        def choose_primary_action(self, context):
            actor = next(a for a in context.actors if a.entity_id == context.active_actor_id)
            # Leave the enlarged 10-foot reach, return, then leave again:
            # three 10-foot moves in the same AI turn, on distinct triggers.
            x = 1 if actor.position.x == 3 else 3
            selected = next((c for c in context.legal_candidates if c.kind == "MOVE"
                             and c.destination and c.destination.x == x and c.destination.y == 3), None)
            if selected is None:
                selected = next(c for c in context.legal_candidates if c.kind == "END_TURN")
            return ManualControllerAdapter(lambda _: (selected.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(production, name)

    combat.controller = DepartingAI()
    for _ in range(20):
        state = table.state(mid)
        if state["menu"]["actor_id"] == target:
            break
        F.advance(table, mid, state)
    else:
        raise AssertionError("AI turn not reached")

    engine = F.reload(combat, tmp_path, mid)
    assert not bears_mark(engine.state.actors[target], owner, sword_core.SWORD_INTENT)
    before = dict(engine.state.actors[owner].resources)
    start_events = len(engine.events)
    prompts = []
    F.advance(table, mid, state, asked=prompts)
    engine = F.reload(combat, tmp_path, mid)
    payments = [p for p in prompts if p["reaction"] == "Life-Severing Sword"]
    assert len(payments) == 1, prompts
    assert all("Opportunity Attack" in o["label"] for o in payments[0]["choice"]["options"])
    after_first = dict(engine.state.actors[owner].resources)
    assert sum(before.values()) - sum(after_first.values()) == 2
    assert len(F.reductions(engine, target)) == 1
    assert not bears_mark(engine.state.actors[target], owner, sword_core.SWORD_INTENT)
    assert sword_core.TURN_KEY not in engine.state.actors[owner].turn_flags
    assert sword_core.PAID_HIT_KEY not in engine.state.actors[owner].turn_flags
    flags = dict(engine.state.actors[owner].turn_flags)
    assert any(k.startswith("typed_once_turn:modifier:") for k in flags)

    # Return without a reaction, then leave again after a fresh table load.
    F.advance(table, mid, table.state(mid))
    prompts = []
    F.advance(table, mid, table.state(mid), asked=prompts)
    engine = F.reload(combat, tmp_path, mid)
    assert any(p["reaction"] == "Opportunity Attack" for p in prompts), prompts
    assert not any(p["reaction"] == "Life-Severing Sword" for p in prompts), prompts
    assert engine.state.actors[owner].resources == after_first
    assert len(F.reductions(engine, target)) == 1
    assert sword_core.PAID_HIT_KEY not in engine.state.actors[owner].turn_flags
    assert sword_core.TURN_KEY not in engine.state.actors[owner].turn_flags
    assert reaction_economy.FLAG + "TAL_GUARDIAN_ADAMANT_GUARDIAN_INCARNATION" in engine.state.actors[owner].turn_flags
    attacks = [e for e in engine.events[start_events:] if e.event_type == "ATTACK_ROLLED"
               and e.source_definition_id.endswith(".opportunity_attack")]
    assert len(attacks) == 2 and all(e.payload["provisional_hit"] for e in attacks)

    # A different creature's turn resets the printed once-per-turn gate; on
    # the next AI turn the same unmarked departure is payable again.
    for _ in range(20):
        state = table.state(mid)
        if state["menu"]["actor_id"] == target and state["menu"]["state_version"] > engine.state.state_version:
            break
        F.advance(table, mid, state)
    else:
        raise AssertionError("next AI turn not reached")
    engine = F.reload(combat, tmp_path, mid)
    before_next = dict(engine.state.actors[owner].resources)
    # The previous turn ended outside reach: return first, then depart.
    F.advance(table, mid, state)
    prompts = []
    F.advance(table, mid, table.state(mid), asked=prompts)
    engine = F.reload(combat, tmp_path, mid)
    assert any(p["reaction"] == "Life-Severing Sword" for p in prompts), prompts
    assert sum(before_next.values()) - sum(engine.state.actors[owner].resources.values()) == 2
