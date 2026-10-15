"""Overlapping invisibility grants must retain their separate ownership."""
from combat.ext import tabik_ninpo as ninpo
from tests.test_a2r09_round3 import held
from tests.test_a2r09_review_fixes import add_fixture_action, NINPO
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, ALLY, FOE


def test_thousand_mile_jump_keeps_main_receipt_as_a_separate_fixed_bonus():
    from combat import flight
    from combat.ext.next_jump import RECEIPT
    from combat.gate2_runtime_models import Position
    from tests.test_auto_a2r11_residual import _sky

    engine, actor, _ = _sky(["thousand_mile_legs"])
    engine._apply_condition(actor, RECEIPT, "test:lift", actor.entity_id,
                            expires_on="START_OF_SOURCE_NEXT_TURN", data={"feet": 5})
    # STR 14: 5 feet tripled, then the separate fixed 5 feet; no run-up.
    assert flight.jump_steps(engine, actor, (Position(x=3, y=6),)) == 4


def test_vanishing_attack_suspends_only_its_own_invisible_table_reload(tmp_path):
    def setup(bundles):
        add_fixture_action(bundles[1], "Older invisibility", [
            {"type": "condition", "condition": "invisible", "applies_to": "target",
             "expires_on": "UNTIL_REMOVED"}], target="ANY_CREATURE")
        add_fixture_action(bundles[0], "Probe attack", [
            {"type": "attack", "attack_kind": "melee", "no_damage": True,
             "on_hit": []}], target="HOSTILE_ENTITY")

    combat, table, mid = fixture(
        tmp_path, [], owner_path="Qi Cultivation", seed="A2R09FX-OVERLAP",
        owner_features=[NINPO + "vanishing_technique"], bundle_transform=setup,
        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 2, "y": 6}, FOE: {"x": 4, "y": 6}},
        battlefield_transform=lambda arena: arena.update(terrain_regions=[]))
    # No-action fixture grants are committed through the table before Vanishing.
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, "Older invisibility", target=OWNER).candidate_id)
    older = held(reload(tmp_path, mid).state.actors[OWNER], "invisible")[0]
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Vanishing Technique").candidate_id)
    actor = reload(tmp_path, mid).state.actors[OWNER]
    state = held(actor, "vanishing_state")[0]
    own = next(c for c in held(actor, "invisible") if c.source_definition_id == state.source_definition_id)
    assert len(held(actor, "invisible")) == 2
    settle(table, mid, candidate(combat, mid, "Probe attack", target=FOE).candidate_id)
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert [c.instance_id for c in held(actor, "invisible")] == [older.instance_id]
    assert actor.conditions[older.instance_id] == older
    assert actor.turn_flags[ninpo.VANISH_REVEAL].endswith("|" + state.instance_id)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    actor = reload(tmp_path, mid).state.actors[OWNER]
    restored = next(c for c in held(actor, "invisible") if c.instance_id != older.instance_id)
    assert actor.conditions[older.instance_id] == older
    assert restored.source_definition_id == own.source_definition_id
    assert restored.source_actor_id == own.source_actor_id
    assert restored.data["concentration_started_sequence"] == state.data["concentration_started_sequence"]
    assert restored.expires_on == own.expires_on
    assert ninpo.VANISH_REVEAL not in actor.turn_flags
