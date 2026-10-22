"""Living Painting native surface swimming and lifetime acceptance."""
import pytest
from tests.test_mgr_t14_sol_subpath_living_painting import FEATURE, create
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn


def setup_water(tmp_path, talents=()):
    return fixture(tmp_path, talents, cl=6, named=True, owner_features=[FEATURE],
        seed="LIVING-PAINTING-SWIM", positions={OWNER: {"x": 3, "y": 6},
        ALLY: {"x": 4, "y": 5}, FOE: {"x": 11, "y": 9}},
        battlefield_transform=lambda arena: arena.update(terrain_regions=[],
            map_terrain=[{"terrain": "water", "cells": [[x, y] for x in range(2, 11) for y in range(3, 10)]}]))


def test_serpent_native_swim_commit_payment_and_replay(tmp_path):
    from combat.swimming import speed
    combat, table, mid = setup_water(tmp_path)
    aid = create(combat, table, mid, "serpent", "FORCE")
    settle(table, mid, candidate(combat, mid, "Command Living Painting").candidate_id)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    engine = reload(tmp_path, mid)
    assert engine.state.current_actor_id == aid and speed(engine, engine.state.actors[aid]) == 40
    assert speed(engine, engine.state.actors[OWNER]) == 0
    row = next(c for c in engine.legal_candidates() if c.metadata.get("movement_mode") == "swim"
               and c.destination and (c.destination.x, c.destination.y) == (7, 6))
    before = engine.state.actors[aid].movement_remaining_ft
    settle(table, mid, row.candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[aid].position == row.destination
    assert engine.state.actors[aid].movement_remaining_ft == before - row.movement_cost_ft
    assert any(e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == aid
               and e.payload.get("movement_mode") == "swim" for e in engine.events)


def test_one_minute_expires_on_natural_owner_turns_and_cold_replays(tmp_path):
    combat, table, mid = setup_water(tmp_path)
    aid = create(combat, table, mid, "serpent", "PIERCING")
    engine = reload(tmp_path, mid)
    assert engine.state.actors[aid].summon.get("expires_on")
    for _ in range(10):
        settle(table, mid, table.state(mid)["menu"]["end_turn"])
        turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert not engine.state.actors[aid].active
    assert engine.state.actors[aid].summon["status"] != "present"


def test_nonwater_map_never_offers_swimming(tmp_path):
    from tests.test_mgr_t14_sol_subpath_living_painting import setup
    combat, table, mid = setup(tmp_path)
    aid = create(combat, table, mid, "serpent", "FORCE")
    settle(table, mid, candidate(combat, mid, "Command Living Painting").candidate_id)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    engine = reload(tmp_path, mid)
    assert engine.state.current_actor_id == aid
    assert not any(c.metadata.get("movement_mode") == "swim" for c in engine.legal_candidates())


def test_new_concentration_keeps_painting_under_unlimited_capacity_after_commit_and_reload(tmp_path):
    # Owner ruling (combat/concentration.py): a creature may hold any number of Concentration techniques, so a second
    # technique does not displace the Living Painting. Only the painting's own form action ending dismisses it.
    combat, table, mid = setup_water(tmp_path, ["FIRE_TAL_BURNING_WEAPON"])
    aid = create(combat, table, mid, "tiger", "FORCE")
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Burning Weapon", target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].concentration is not None
    assert engine.state.actors[aid].active
    assert not any(e.event_type == "SUMMON_DISMISSED" and e.actor_id == aid for e in engine.events)


def test_character_sheet_subpath_grant_field_reaches_native_creation(tmp_path):
    """Public compiler interface regression, not full acquisition certification.

    CharacterSheetService emits this field for authenticated ledger grants.
    Source ownership is supplied here as compiler input to isolate its consumer.
    """
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet
    document = sheet([], cl=6)
    document.setdefault("path_and_subpath", {})["source_granted_subpath_feature_record_ids"] = [FEATURE]
    bundle = compile_character(document, actor_id=OWNER, reaction_plan={"ask": True})
    combat, table, mid = fixture(tmp_path, [], cl=6, owner_bundle=bundle,
        battlefield_transform=lambda arena: arena.update(terrain_regions=[]))
    aid = create(combat, table, mid, "serpent", "FORCE")
    engine = reload(tmp_path, mid)
    assert engine.state.actors[aid].active
    assert engine.state.actors[aid].summon["command_range_ft"] is None


@pytest.mark.parametrize("native", [False, True])
def test_shell_ward_native_attack_reaction_saves_round_usage_and_cover(tmp_path, native):
    from combat.ext import painting_forms
    from tests.worker2_support import sealed_native_attack
    def attack_catalog(bundles):
        if native:
            sealed_native_attack(bundles[2], "Ward native pressure", damage_type="FORCE", count=1,
                                 sides=4, modifier=6, attack_bonus=100, range_ft=30)
    combat, table, mid = fixture(tmp_path, [], cl=6, owner_features=[FEATURE], owner_ac=0,
        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 5}, FOE: {"x": 4, "y": 6}},
        battlefield_transform=lambda arena: arena.update(terrain_regions=[]), bundle_transform=attack_catalog,
        seed="PAINTED-SHELL-WARD")
    aid = create(combat, table, mid, "tortoise", "BLUDGEONING")
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, FOE)
    engine = combat._load_session(mid).engine
    assert engine._distance_actor_to_actor(engine.state.actors[aid], engine.state.actors[OWNER]) <= 5
    attack = (candidate(combat, mid, "Ward native pressure", target=OWNER) if native else
              next(c for c in engine.legal_candidates() if OWNER in c.target_ids
                   and ((engine.action_catalog.get(c.source_definition_id).parameters or {}).get("typed") or {}).get("weapon")))
    feature = "summon.living_painting_tortoise.innate_reaction"
    reaction = "reaction:typed." + feature  # prompt ids carry the typed prefix (factory_compiler / typed_reactions)
    prompts = settle(table, mid, attack.candidate_id, {reaction: "first"})
    assert any(p["context"]["reaction_source_id"] == reaction for p in prompts)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[aid].turn_flags["once_per_round:typed." + feature] == engine.state.round_number
    assert any(c.condition_id == painting_forms.SHELL_WARD for c in engine.state.actors[OWNER].conditions.values())


def test_commanded_help_is_real_next_attack_advantage_and_no_unprinted_reactions(tmp_path):
    from tests.test_mgr_t14_sol_subpath_living_painting import setup
    combat, table, mid = setup(tmp_path)
    aid = create(combat, table, mid, "tiger", "FORCE")
    settle(table, mid, candidate(combat, mid, "Command Living Painting").candidate_id)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    engine = reload(tmp_path, mid)
    assert not any(r.get("block") == "opportunity" for r in engine.typed_reaction_rows[aid])
    move = next(c for c in engine.legal_candidates() if c.kind == "MOVE"
                and c.destination and (c.destination.x, c.destination.y) == (8, 6))
    settle(table, mid, move.candidate_id)
    settle(table, mid, candidate(combat, mid, "Help", target=FOE).candidate_id,
           {"choice:needle.painted_help": ALLY})
    engine = reload(tmp_path, mid)
    assert any(m.target_field == "attack_mode_vs" and m.value == "ADVANTAGE:" + FOE
               and not m.consumed for m in engine.state.actors[ALLY].modifiers.values())
    turn(table, mid, ALLY)
    engine = combat._load_session(mid).engine
    move = next(c for c in engine.legal_candidates() if c.kind == "MOVE"
                and c.destination and (c.destination.x, c.destination.y) == (8, 5))
    settle(table, mid, move.candidate_id)
    engine = combat._load_session(mid).engine
    strike = next(c for c in engine.legal_candidates() if FOE in c.target_ids
                  and ((engine.action_catalog[c.source_definition_id].parameters or {}).get("typed") or {}).get("weapon"))
    settle(table, mid, strike.candidate_id)
    engine = reload(tmp_path, mid)
    attacks = [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == ALLY]
    assert attacks, [e.event_type for e in engine.events if e.actor_id == ALLY][-12:]
    attack = attacks[-1]
    assert attack.payload["mode"] == "ADVANTAGE"
    assert not any(m.target_field == "attack_mode_vs" and m.value == "ADVANTAGE:" + FOE
                   and not m.consumed for m in engine.state.actors[ALLY].modifiers.values())
