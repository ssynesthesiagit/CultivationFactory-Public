"""River Breaks the Charge stays a complete GM rider, not an endpoint reaction.

The former positive/menu tests asserted automation that contradicted the printed
rule. These regressions enforce the authorized GM fallback through real movement
and table commit/reload, including Ask-me owners on manual and AI mover turns.
"""
import pytest

from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import Position, ReactionDecision
from tests.test_riders_c10 import authority, bundle, fight, turn, use, ME, ALLY
from tests.auto_worker1_support import LEFT, RIGHT, fight as table_fight, reload
from tests.test_auto42_stars import turn as table_turn
from tests.test_auto45_metal import settle

RESPONSE = "TAL_FLOWING_RIVER_FLOWING_RESPONSE"
CHARGE = "TAL_FLOWING_RIVER_RIVER_BREAKS_THE_CHARGE"


def assert_no_charge(engine):
    assert not any(e.event_type == "REACTION_WINDOW_OPENED"
                   and e.payload.get("checkpoint") == "RIVER_BREAKS"
                   for e in engine.events)
    assert not any(e.event_type == "SAVE_ROLLED" and RESPONSE in str(e.payload)
                   for e in engine.events)


def test_charge_has_only_complete_plain_gm_riders_and_no_compiled_effects():
    row = authority()["mechanics"][CHARGE]
    assert row["coverage"] == "RIDERS_ONLY"
    assert row["effects"] == []
    assert not row.get("modifier")
    text = " ".join(row["riders"])
    for phrase in ("resolved by the GM", "20 feet", "mostly direct", "Dexterity",
                   "falls Prone", "movement ends immediately", "legal space adjacent",
                   "Other enemies", "until the current turn ends", "separately for each fighter"):
        assert phrase in text
    compiled = bundle([RESPONSE, CHARGE])
    assert not any(r.get("kind") == "river_breaks_the_charge"
                   for r in compiled["typed_passives"])
    response = [r for r in compiled["typed_reactions"] if r.get("feature_id") == RESPONSE]
    assert response
    assert CHARGE not in str(response), "charge must not ride ordinary attack/control saves"


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("destination", ["Move to 4,6", "Move to 5,6"])
def test_real_approaches_do_not_spend_a_reaction_or_apply_charge_effects(legacy, destination):
    engine = fight([RESPONSE, CHARGE], foe_at=(9, 6))
    if legacy:
        # Old sealed bundles may still carry the block; they must stay safe too.
        engine.typed_passive_rows[ME].append({"feature_id": CHARGE,
            "block": "flowing_river", "kind": "river_breaks_the_charge"})
    turn(engine, AN)
    requested = []
    def accept(request):
        requested.append(request)
        options = tuple((request.get("extension_choice") or {}).get("option_ids") or ())[:1]
        return ReactionDecision(**{k: request[k] for k in
            ("checkpoint", "reactor_id", "reaction_source_id")}, selection="USE", option_ids=options), None
    engine.set_reaction_provider(accept)
    use(engine, destination, actor_id=AN)
    assert requested == []
    assert engine.state.actors[ME].reaction_available
    assert engine._effective_speed(engine.state.actors[AN]) == 30
    assert_no_charge(engine)


def test_forced_twenty_five_foot_entry_with_legacy_row_stays_inert():
    engine = fight([RESPONSE, CHARGE], foe_at=(9, 6))
    engine.typed_passive_rows[ME].append({"feature_id": CHARGE,
        "block": "flowing_river", "kind": "river_breaks_the_charge"})
    turn(engine, AN)
    engine.state.actors[AN].position = Position(x=4, y=6)
    engine._append_event("MOVEMENT_COMMITTED", "test.shove", actor_id=AN,
        payload={"path": [{"x": x, "y": 6, "z": 0} for x in range(9, 3, -1)],
                 "cost_ft": 25, "forced": True})
    assert engine._distance_actor_to_actor(engine.state.actors[ME], engine.state.actors[AN]) == 5
    assert engine.state.actors[ME].reaction_available
    assert_no_charge(engine)


def test_two_legacy_owners_both_keep_their_reactions_after_reach_entry():
    engine = fight([RESPONSE, CHARGE], foe_at=(9, 6), ally=True,
                   ally_ids=[RESPONSE, CHARGE])
    engine.state.actors[ALLY].position = Position(x=3, y=7)
    for actor_id in (ME, ALLY):
        engine.typed_passive_rows[actor_id].append({"feature_id": CHARGE,
            "block": "flowing_river", "kind": "river_breaks_the_charge"})
    turn(engine, AN)
    use(engine, "Move to 4,6", actor_id=AN)
    assert all(engine.state.actors[a].reaction_available for a in (ME, ALLY))
    assert_no_charge(engine)


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("owned", [False, True])
def test_charge_gm_fallback_survives_table_commit_and_fresh_reload(tmp_path, ai, owned):
    combat, table, mid = table_fight(tmp_path, [RESPONSE] + ([CHARGE] if owned else []),
        positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 9, "y": 6}},
        # The default arena has a pillar at 9,6. Use a clear synthetic lane.
        arena_edit=lambda arena: arena.update(terrain_regions=[]))
    table_turn(table, mid, RIGHT)
    state = table.state(mid)
    menu = state["menu"]
    cid = next(m["candidate_id"] for m in menu["moves"]
               if m["destination"] == {"x": 4, "y": 6})
    if ai:
        from combat.gate4_adapters import ManualControllerAdapter
        real = combat.controller
        class Controller:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        combat.controller = Controller()
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
        send = lambda answers: table.auto_step(mid, table.state(mid)["last_sequence"], answers)
    else:
        send = lambda answers: table.act(mid, cid, menu["decision_id"], menu["state_version"],
                                        state["last_sequence"], answers)
    result, prompts = settle(send)
    assert result["status"] == "COMMITTED"
    assert prompts == [], "GM-only charge must not open an unsupported Ask-me choice"
    engine = reload(combat, mid)
    assert engine.state.actors[RIGHT].position == Position(x=4, y=6)
    assert engine.state.actors[LEFT].reaction_available
    assert engine._effective_speed(engine.state.actors[RIGHT]) == 30
    assert not engine.state.actors[RIGHT].modifiers
    assert_no_charge(engine)
