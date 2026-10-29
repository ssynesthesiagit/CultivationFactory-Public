"""Consume Fear, Refine Command resolves on Dread Appetite's failed-save path."""
import json
from pathlib import Path

from tests.cw2_service_support import add_action, seal
from tests.test_r9i_karma_persistence import end_turn
from combat.ext.scoundrel_riders import held_possessions, possessions
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, settle, turn

DREAD = "TAL_DAEMONIC_CULTIVATION_DREAD_APPETITE"
CONSUME = "TAL_DAEMONIC_CULTIVATION_CONSUME_FEAR_REFINE_COMMAND"
ESSENCE = "resource:named.devoured_essence"
CHOICE = "choice:needle.consume_fear"


def _prepare(bundles):
    add_action(bundles[0], "Start Fear", [
        {"type": "condition", "applies_to": "target", "condition": "frightened",
         "expires_on": "UNTIL_REMOVED"}
    ])
    seal(bundles[0])


def _assert_rebuilt_authority():
    authority = json.loads((Path(__file__).parents[1] / "authority/typed_mechanics/reviewed_final.d/martial.json").read_text())
    record = authority["mechanics"][CONSUME]
    assert record["text_sha256"] == "3bc927c349ca80abd334bce4792de127487a09f34109e6a652e82999b557774d"
    assert record["min_cl"] == 5
    assert record["riders"] == []
    assert record["modifier"]["when"] == "failed_save"
    assert record["modifier"]["effects"] == [{"type": "rider_consume_fear"}]


def _dread(combat, mid):
    return candidate(combat, mid, "Dread Appetite: Frighten", target=FOE).candidate_id


def test_failed_dread_appetite_grants_essence_and_only_prior_fear_opens_choice(tmp_path):
    _assert_rebuilt_authority()
    combat, table, mid = fixture(tmp_path, [DREAD, CONSUME], cl=15, owner_dc=30, bundle_transform=_prepare)
    before = reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE]
    settle(table, mid, candidate(combat, mid, "Start Fear", target=FOE).candidate_id)
    assert any(c.condition_id == "condition:typed.frightened"
               for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())
    prompts = settle(table, mid, _dread(combat, mid), {CHOICE: "deny_reactions"})
    assert any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[ESSENCE] == before + 2
    denied = [c for c in engine.state.actors[FOE].conditions.values()
              if c.condition_id == "condition:typed.reaction_denied"]
    assert denied and denied[0].expires_on == f"END_OF_SOURCE_TURN_AT:{engine.state.actors[OWNER].turns_started + 1}"
    save = next(e for e in reversed(engine.events) if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE)
    assert save.payload["total"] < save.payload["dc"]
    end_turn(table, mid)
    turn(table, mid, OWNER)
    assert any(c.condition_id == "condition:typed.reaction_denied"
               for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())
    end_turn(table, mid)
    assert not any(c.condition_id == "condition:typed.reaction_denied"
                   for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())


def test_unfrightened_failed_save_gains_essence_without_additional_choice(tmp_path):
    combat, table, mid = fixture(tmp_path, [DREAD, CONSUME], cl=15, owner_dc=30)
    before = reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE]
    prompts = settle(table, mid, _dread(combat, mid))
    assert not any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE] == before + 2


def test_frightened_target_can_decline_the_additional_effect(tmp_path):
    combat, table, mid = fixture(tmp_path, [DREAD, CONSUME], cl=15, owner_dc=30, bundle_transform=_prepare)
    settle(table, mid, candidate(combat, mid, "Start Fear", target=FOE).candidate_id)
    prompts = settle(table, mid, _dread(combat, mid), decline_after=0)
    assert any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == "condition:typed.reaction_denied"
                   for c in engine.state.actors[FOE].conditions.values())


def _mire_cells(*cells):
    """Difficult ground (2 feet of movement per foot) on exactly these squares; it blocks nothing."""
    def edit(arena):
        arena.setdefault("terrain_regions", []).append(
            {"region_id": "approach_mire", "terrain_type": "OPEN", "movement_cost": 2, "description": "mire",
             "cells": [{"x": x, "y": y} for x, y in cells]})
    return edit


OA_SOURCES = ("reaction:typed.opportunity_attack", "system:combat.opportunity_attack")


def test_caster_can_take_the_ten_foot_approach_step_without_target_opportunity_attack(tmp_path):
    # Caster (1,2) starts in the target's reach at (2,3). Mire on (1,3) makes the straight route to (1,4) cost 15 feet,
    # so the only 10-foot route is (1,2)->(0,3)->(1,4), and its first square leaves the target's reach. The target's
    # Opportunity Attack is the one exempted by Consume Fear, so it must not be offered and its Reaction must stay unspent.
    positions = {OWNER: {"x": 1, "y": 2}, ALLY: {"x": 1, "y": 13}, FOE: {"x": 2, "y": 3}}
    combat, table, mid = fixture(tmp_path, [DREAD, CONSUME], cl=15, owner_dc=30, bundle_transform=_prepare,
                                 positions=positions, battlefield_transform=_mire_cells((1, 3)))
    settle(table, mid, candidate(combat, mid, "Start Fear", target=FOE).candidate_id)
    prompts = settle(table, mid, _dread(combat, mid), {
        CHOICE: "move_toward", "choice:needle.consume_fear_step": "cell:1,4"
    })
    assert "cell:1,4" in [option["id"] for option in _steps(prompts)[0]["choice"]["options"]]
    assert not any(p["context"]["reactor_id"] == FOE and p["context"]["reaction_source_id"] in OA_SOURCES
                   for p in prompts), prompts
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].reaction_available
    assert (engine.state.actors[OWNER].position.x, engine.state.actors[OWNER].position.y) == (1, 4)


def _prepare_flier(bundles):
    _prepare(bundles)
    bundles[0]['actor_template']['fly_speed_ft'] = 60


def _steps(engine_prompts):
    return [p for p in engine_prompts if p["context"]["reaction_source_id"] == "choice:needle.consume_fear_step"]


def test_approach_is_a_separate_ten_foot_grant_and_keeps_the_ordinary_walking_allowance(tmp_path):
    # Walking 30, flying 60, target 5 squares away. The flight counter must not price any endpoint past 10 feet.
    positions = {OWNER: {"x": 3, "y": 6}, ALLY: {"x": 1, "y": 13}, FOE: {"x": 8, "y": 6}}
    combat, table, mid = fixture(tmp_path, [DREAD, CONSUME], cl=15, owner_dc=30,
                                 bundle_transform=_prepare_flier, positions=positions)
    settle(table, mid, candidate(combat, mid, "Start Fear", target=FOE).candidate_id)
    ordinary_before = reload(tmp_path, mid).state.actors[OWNER].movement_remaining_ft
    prompts = settle(table, mid, _dread(combat, mid), {
        CHOICE: "move_toward", "choice:needle.consume_fear_step": "cell:5,6"
    })
    step = _steps(prompts)
    assert step, prompts
    for option in step[0]["choice"]["options"]:
        # Flying options carry altitude too ("cell:x,y,z"); the 10-foot cap is about the ground square.
        x, y = (int(v) for v in option["id"].removeprefix("cell:").split(",")[:2])
        assert max(abs(x - 3), abs(y - 6)) * 5 <= 10, option["id"]
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert (owner.position.x, owner.position.y) == (5, 6)
    # A granted route's receipt carries granted_cost_ft (the engine adds it only when a grant is spent).
    granted = [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED"
               and e.actor_id == OWNER and "granted_cost_ft" in e.payload]
    assert granted and all(e.payload["granted_cost_ft"] <= 10 for e in granted)
    assert owner.movement_remaining_ft == ordinary_before


def test_approach_exits_only_the_frightened_targets_reach_and_other_enemies_still_provoke(tmp_path):
    # Same route as above, with bystander foe1 at (0,1) in reach of the caster's start square (1,2). The first step to
    # (0,3) leaves the reach of both the target and the bystander. The target is exempt; the bystander must still provoke
    # (the positive control that shows this fixture does surface Opportunity Attacks).
    positions = {OWNER: {"x": 1, "y": 2}, ALLY: {"x": 1, "y": 13}, FOE: {"x": 2, "y": 3},
                 "actor:factory.worker2-foe1": {"x": 0, "y": 1}}
    combat, table, mid = fixture(tmp_path, [DREAD, CONSUME], cl=15, owner_dc=30, extra_foes=1,
                                 bundle_transform=_prepare, positions=positions,
                                 battlefield_transform=_mire_cells((1, 3)))
    settle(table, mid, candidate(combat, mid, "Start Fear", target=FOE).candidate_id)
    prompts = settle(table, mid, _dread(combat, mid), {
        CHOICE: "move_toward", "choice:needle.consume_fear_step": "cell:1,4"
    })
    assert "cell:1,4" in [option["id"] for option in _steps(prompts)[0]["choice"]["options"]]
    oa = [p for p in prompts if p["context"]["reaction_source_id"] in OA_SOURCES]
    assert not any(p["context"]["reactor_id"] == FOE for p in oa), oa
    assert any(p["context"]["reactor_id"] == "actor:factory.worker2-foe1" for p in oa), oa
    engine = reload(tmp_path, mid)
    assert (engine.state.actors[OWNER].position.x, engine.state.actors[OWNER].position.y) == (1, 4)


def test_dread_appetite_without_consume_fear_does_not_gain_essence(tmp_path):
    combat, table, mid = fixture(tmp_path, [DREAD], cl=15, owner_dc=30)
    before = reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE]
    settle(table, mid, _dread(combat, mid))
    assert reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE] == before + 1


def _prepare_approach(bundles):
    add_action(bundles[1], "Start Fear", [
        {"type": "condition", "applies_to": "target", "condition": "frightened",
         "expires_on": "UNTIL_REMOVED"}
    ])
    add_action(bundles[0], "Push Toward Ally", [
        {"type": "forced_movement", "applies_to": "target", "distance_ft": 5,
         "direction": "away", "evidence": "Push it 5 feet away from you."}
    ])
    add_action(bundles[2], "Self Teleport", [
        {"type": "teleport", "applies_to": "self", "distance_ft": 20,
         "evidence": "Teleport up to 20 feet to an unoccupied space."}
    ], target="SELF")
    seal(bundles[0]); seal(bundles[1]); seal(bundles[2])


def test_selected_ally_approach_bar_covers_paths_and_teleports_but_not_forced_movement(tmp_path):
    positions = {OWNER: {"x": 3, "y": 6}, ALLY: {"x": 8, "y": 6}, FOE: {"x": 6, "y": 6}}
    combat, table, mid = fixture(tmp_path, [DREAD, CONSUME], cl=15, owner_dc=30,
                                 bundle_transform=_prepare_approach, positions=positions)
    turn(table, mid, ALLY)
    ally_engine = reload(tmp_path, mid)
    fear = next(c for c in ally_engine.legal_candidates()
                if c.actor_id == ALLY
                and getattr(ally_engine.action_catalog.get(c.source_definition_id), "display_name", None) == "Start Fear"
                and c.target_ids == (FOE,))
    settle(table, mid, fear.candidate_id)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    press = next(c for c in engine.legal_candidates()
                 if c.target_ids == (FOE,)
                 and "Press the Fear" in engine.action_catalog[c.source_definition_id].display_name)
    settle(table, mid, press.candidate_id, {
        CHOICE: "no_approach", "choice:needle.consume_fear_ally": ALLY
    })
    engine = reload(tmp_path, mid)
    target = engine.state.actors[FOE]
    bar = next(c for c in target.conditions.values() if c.condition_id == "condition:typed.no_approach")
    assert bar.data["avoid"] == ALLY
    assert bar.expires_on == "END_OF_HOLDER_NEXT_TURN"

    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    target = engine.state.actors[FOE]
    moves = engine._movement_candidates(target)
    ally = engine.state.actors[ALLY]
    caster = engine.state.actors[OWNER]
    toward_ally = [c for c in moves if engine._distance_actor_to_actor(
        target, ally, actor_position=c.destination) < engine._distance_actor_to_actor(target, ally)]
    toward_caster = [c for c in moves if engine._distance_actor_to_actor(
        target, caster, actor_position=c.destination) < engine._distance_actor_to_actor(target, caster)]
    assert not toward_ally, f"voluntary path can approach selected ally: {toward_ally}"
    assert toward_caster, "the selected-ally bar also blocked retreating from that ally toward the caster"

    # An own teleport toward the selected ally fails; the same actor can teleport toward the caster.
    toward_ally = candidate(combat, mid, "Self Teleport", target=None, at=(7, 6))
    settle(table, mid, toward_ally.candidate_id,
           choices={"choice:needle.teleport_destination": "cell:7,6"})
    assert (reload(tmp_path, mid).state.actors[FOE].position.x,
            reload(tmp_path, mid).state.actors[FOE].position.y) == (6, 6)
    toward_caster = candidate(combat, mid, "Self Teleport", target=None, at=(5, 6))
    settle(table, mid, toward_caster.candidate_id,
           choices={"choice:needle.teleport_destination": "cell:5,6"})
    assert (reload(tmp_path, mid).state.actors[FOE].position.x,
            reload(tmp_path, mid).state.actors[FOE].position.y) == (5, 6)

    # Forced movement keeps its separate rule and is not blocked by the voluntary bar.
    turn(table, mid, OWNER)
    push = candidate(combat, mid, "Push Toward Ally", target=FOE)
    before_push = reload(tmp_path, mid).state.actors[FOE].position
    settle(table, mid, push.candidate_id)
    moved = reload(tmp_path, mid).state.actors[FOE].position
    assert moved != before_push, "the voluntary approach bar blocked forced movement"


MUNDANE_DAGGER = {"starting_kit": {"items": [
    {"item_id": "tianxia.mortal.weapon.bi_shou", "name": "Bi Shou (Dagger)", "quantity": 1}]}}


def _held_identities(engine):
    return [row["object"] for row in held_possessions(engine, engine.state.actors[FOE])]


def _possessed_identities(engine):
    return [row["object"] for row in possessions(engine, engine.state.actors[FOE])]


def _drop_setup(tmp_path, owner_dc):
    combat, table, mid = fixture(tmp_path, [DREAD, CONSUME], cl=15, owner_dc=owner_dc,
                                 foe_kit=MUNDANE_DAGGER, bundle_transform=_prepare)
    held = _held_identities(reload(tmp_path, mid))
    assert len(held) == 1
    settle(table, mid, candidate(combat, mid, "Start Fear", target=FOE).candidate_id)
    return combat, table, mid, held[0]


def _last_str_save(engine):
    return next(e for e in reversed(engine.events) if e.event_type == "SAVE_ROLLED"
                and e.actor_id == FOE and str((e.payload or {}).get("reason", "")).endswith(":STR"))


def test_failed_strength_save_drops_one_exact_held_mundane_object(tmp_path):
    combat, table, mid, identity = _drop_setup(tmp_path, owner_dc=100)
    prompts = settle(table, mid, _dread(combat, mid), {
        CHOICE: "drop_object", "choice:needle.consume_fear_drop": "first"
    })
    drop_prompt = next(p for p in prompts
                       if p["context"]["reaction_source_id"] == "choice:needle.consume_fear_drop")
    assert identity in [row["id"] for row in drop_prompt["choice"]["options"]]
    engine = reload(tmp_path, mid)
    save = _last_str_save(engine)
    assert save.payload["total"] < save.payload["dc"]
    assert identity not in _possessed_identities(engine)
    assert identity not in _held_identities(engine)


def test_drop_follows_the_strength_save_outcome_at_a_realistic_dc(tmp_path):
    combat, table, mid, identity = _drop_setup(tmp_path, owner_dc=30)
    settle(table, mid, _dread(combat, mid), {
        CHOICE: "drop_object", "choice:needle.consume_fear_drop": "first"
    })
    engine = reload(tmp_path, mid)
    save = _last_str_save(engine)
    still_held = identity in _possessed_identities(engine)
    assert still_held == (save.payload["total"] >= save.payload["dc"])


def _carried_row(key, name, item_id="tianxia.mortal.weapon.bi_shou", **flags):
    # Shaped like a combat/factory_compiler.py _carrying item (plus the scoundrel possession identity).
    return {"key": key, "item_id": item_id, "name": name, "quantity": 1, "weight_lb": "1",
            "kind": "item", "worn": False, "object": f"object:OWNER:{key}", **flags}


def test_magic_held_objects_are_never_offered_as_the_mundane_drop(monkeypatch):
    from types import SimpleNamespace
    from combat.ext import daemonic_riders, scoundrel_riders

    held = [_carried_row("bi_shou", "Bi Shou (Dagger)"),
            _carried_row("jian", "Treasure Jian", treasure=True, combat_weapon_key="copy1"),
            _carried_row("crown", "Heavy Crown", attunement_slots=2),
            _carried_row("ring", "Lotus Ring", magical=True),
            _carried_row("relic", "Relic", artifact=True),
            _carried_row("unlisted", "Unlisted trinket", item_id="tianxia.test.unlisted"),
            {"key": "sack", "name": "Received sack", "kind": "item", "object": "object:OWNER:sack"}]
    monkeypatch.setattr(scoundrel_riders, "held_possessions", lambda engine, holder: held)
    offered = [row["key"] for row in daemonic_riders._mundane_held(SimpleNamespace(), SimpleNamespace())]
    # Fail closed: only a catalog-proven mundane object with no magic marker is offered. A row with no
    # catalog identity (the handover fallback "sack", an unlisted id) is never offered as the mundane drop.
    assert offered == ["bi_shou"]


def test_prior_frightened_mark_is_consumed_even_below_cl5():
    from types import SimpleNamespace
    from combat.ext import daemonic_riders

    cache = {daemonic_riders.consume_fear_mark("foe"): True}
    ctx = SimpleNamespace(target=SimpleNamespace(entity_id="foe"), numbers={"cl": 4}, damage_cache=cache,
                          engine=SimpleNamespace(state=SimpleNamespace(actors={})), actor=SimpleNamespace())
    daemonic_riders.consume_fear(ctx, {})
    assert daemonic_riders.consume_fear_mark("foe") not in cache


def test_prior_frightened_mark_is_kept_per_subject_across_two_targets():
    # Dread Appetite can save two targets in one activation. Frightened on the first must not be overwritten by
    # the second target's snapshot, and each target's mark is consumed by that target alone.
    from types import SimpleNamespace as NS
    from combat.ext import daemonic_riders as dr

    cache = {}
    ctx = NS(typed={"source": DREAD}, damage_cache=cache)
    fails = [{"type": "rider_consume_fear"}]
    frightened = NS(entity_id="a", conditions={"c": NS(condition_id="condition:typed.frightened")})
    calm = NS(entity_id="b", conditions={})
    dr.consume_fear_snapshot(ctx, frightened, "str", fails, [], [])
    dr.consume_fear_snapshot(ctx, calm, "str", fails, [], [])
    assert cache[dr.consume_fear_mark("a")] is True
    assert cache[dr.consume_fear_mark("b")] is False
    below_cl5 = NS(numbers={"cl": 4}, damage_cache=cache, engine=NS(state=NS(actors={})), actor=NS(),
                   target=NS(entity_id="b"))
    dr.consume_fear(below_cl5, {})
    assert dr.consume_fear_mark("b") not in cache
    assert cache[dr.consume_fear_mark("a")] is True
