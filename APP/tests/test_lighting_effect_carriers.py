"""Public, saved-table regressions for LIGHTS3F20R's two wrong carriers."""
import pytest

from combat import lighting, motion
from combat.canonical import canonical_sha256
from combat.ext import placed
from combat.typed_executor import bears_mark
from tests.h1_support import sheet
from tests.lighting_support import map_arena, map_document, ambient_light
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle, turn

SMALL = "TAL_YANG_THE_ACTION_CANNOT_STAY_SMALL"
CANDLE = "TAL_WAX_GUIDING_CANDLE"
SPIRIT = "tianxia.talent.talismans.talisman_spirit"


def _arena(tmp_path, *, footing=False):
    document = map_document(28, 10, ambient=ambient_light("day"))
    if footing:
        document["terrain"] = [{"type": "DIFFICULT", "cells": [[9, 3], [3, 3], [11, 3]]}]
    return map_arena(tmp_path, document)


def _move(combat, table, mid, at):
    engine = combat._load_session(mid).engine
    rows = [c for c in engine.legal_candidates() if c.kind.value == "MOVE"
            and c.destination and (c.destination.x, c.destination.y) == at]
    actor = engine.state.actors[engine.state.current_actor_id]
    assert rows, (at, actor.entity_id, actor.position, actor.movement_remaining_ft,
                  [(c.display_name, c.destination) for c in engine.legal_candidates() if c.kind.value == "MOVE"])
    settle(table, mid, rows[0].candidate_id)


@pytest.mark.parametrize("parent,at", [("Mold Wax: Soft Spread", (8, 3)), ("Press Seal", None)])
def test_candle_creation_location_lifetime_and_remote_flare_commit_reload(tmp_path, parent, at):
    combat, table, mid = fixture(tmp_path, [CANDLE], owner_dc=100,
        battlefield=_arena(tmp_path, footing=True), foe_position={"x": 8, "y": 3}, seed="LIGHT-CANDLE-CARRIER",
        bundle_transform=lambda bundles: _blind(bundles[1]))
    assert not any(c.display_name == "Guiding Candle" for c in combat._load_session(mid).engine.legal_candidates())
    base = candidate(combat, mid, parent, at=at, target=FOE if at is None else None)
    prompts = settle(table, mid, base.candidate_id, {"choice:needle.guiding_candle_create": "create"})
    assert any(p["context"]["reaction_source_id"] == "choice:needle.guiding_candle_create" for p in prompts)
    engine = reload(tmp_path, mid)
    candle, = placed.of(engine, "guiding_candle")
    original = candle.model_dump(mode="json")
    assert (candle.center.x, candle.center.y) == (8, 3)
    assert candle.duration_rounds == 600 and not candle.concentration_link
    light, = [s for s in lighting.sources(engine) if s.name == "Guiding Candle"]
    assert (light.following, light.cells, light.bright_ft, light.dim_ft, light.magical) == (
        None, frozenset({(8, 3)}), 10, 20, False)

    _move(combat, table, mid, (3, 3))
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].position != candle.center
    assert engine.grid.base_movement_cost[(9, 3)] == 2
    assert (9, 3) not in motion.exempt_cells(engine, engine.state.actors[ALLY])
    prompts = settle(table, mid, candidate(combat, mid, "Guiding Candle").candidate_id,
        {"choice:needle.guiding_candle_flare": candle.zone_id})
    assert any(p["context"]["reaction_source_id"] == "choice:needle.guiding_candle_flare" for p in prompts)
    engine = reload(tmp_path, mid)
    assert engine.state.zones[candle.zone_id].model_dump(mode="json") == original, "flare must not move or renew the candle"
    light, = [s for s in lighting.sources(engine) if s.name == "Guiding Candle"]
    assert light.cells == frozenset({(8, 3)}) and light.following is None
    assert not any(c.condition_id == lighting.LIGHT for c in engine.state.actors[OWNER].conditions.values())
    flare, = [c for c in engine.state.actors[OWNER].conditions.values()
              if c.condition_id == "condition:typed.guiding_candle_flare"]
    assert flare.data["candle_id"] == candle.zone_id
    for actor_id in (OWNER, ALLY):
        waived = motion.exempt_cells(engine, engine.state.actors[actor_id])
        assert (9, 3) in waived, "the flare helps at the candle, not at the caster"
        assert not {(3, 3), (11, 3)} & waived, "outside the candle radius stays difficult"
    assert (9, 3) not in motion.exempt_cells(engine, engine.state.actors[FOE]), "enemies receive no footing"
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, "Close sight").candidate_id)
    engine = reload(tmp_path, mid)
    assert (9, 3) not in motion.exempt_cells(engine, engine.state.actors[ALLY]), "an ally that cannot see the candle gets no footing"
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == flare.condition_id for c in engine.state.actors[OWNER].conditions.values())
    assert engine.state.zones[candle.zone_id].active, "flare expiry must not extinguish the hour-long candle"
    assert (9, 3) not in motion.exempt_cells(engine, engine.state.actors[ALLY])


def test_declining_candle_creation_does_not_enable_a_flare_or_light_the_caster(tmp_path):
    combat, table, mid = fixture(tmp_path, [CANDLE], seed="LIGHT-CANDLE-DECLINE")
    settle(table, mid, candidate(combat, mid, "Mold Wax: Soft Spread").candidate_id,
           {"choice:needle.guiding_candle_create": None})
    engine = reload(tmp_path, mid)
    assert not placed.of(engine, "guiding_candle")
    assert not [s for s in lighting.sources(engine) if s.name == "Guiding Candle"]
    assert not any(c.display_name == "Guiding Candle" for c in engine.legal_candidates())


def _blind(bundle):
    source = "action:test.lighting.close_sight"
    row = {"source_definition_id": source, "display_name": "Close sight", "owner_id": bundle["actor_id"],
        "economy": "BONUS_ACTION", "resolution_kind": "TYPED", "target_kind": "SELF", "costs": [],
        "parameters": {"typed": {"effects": [{"type": "condition", "applies_to": "self", "condition": "blinded",
        "expires_on": "START_OF_SOURCE_NEXT_TURN"}], "numbers": {"cl": 15, "pb": 4},
        "duration": {"kind": "instant"}, "riders": []}}}
    bundle["action_catalog"].append(row)
    bundle["actor_template"]["action_ids"].append(source)
    bundle.pop("bundle_sha256", None)
    bundle["bundle_sha256"] = canonical_sha256(bundle)


def _probe(bundle):
    source = "action:test.lighting.damage_probe"
    action = {"source_definition_id": source, "display_name": "Damage probe", "owner_id": bundle["actor_id"],
        "economy": "BONUS_ACTION", "resolution_kind": "TYPED", "target_kind": "ANY_CREATURE", "range_ft": 120,
        "costs": [], "parameters": {"typed": {"effects": [{"type": "damage", "applies_to": "target",
        "dice": {"count": 1, "sides": 1}, "flat": 1, "damage_types": ["force"]}] * 2,
        "numbers": {"cl": 15, "pb": 4, "save_dc": 100}, "duration": {"kind": "instant"}, "riders": []}}}
    bundle["action_catalog"].append(action)
    bundle["actor_template"]["action_ids"].append(source)
    bundle.pop("bundle_sha256", None)
    bundle["bundle_sha256"] = canonical_sha256(bundle)


@pytest.mark.parametrize("selected", ["light", "damage"])
def test_overcomplete_selected_result_uses_the_created_summon_not_its_summoner(tmp_path, selected):
    foe_sheet = sheet([SPIRIT])
    foe_sheet["ability_scores_and_statistics"]["hit_points"]["maximum"] = 400
    foe_sheet["ability_scores_and_statistics"]["armor_class"]["base_value"] = 1
    combat, table, mid = fixture(tmp_path, [SMALL], owner_dc=100, foe_sheet=foe_sheet,
        foe_position={"x": 3, "y": 3}, seed="WORKER2",
        bundle_transform=lambda bundles: _probe(bundles[2]))
    settle(table, mid, candidate(combat, mid, "Rising Thread", target=FOE).candidate_id)
    assert bears_mark(reload(tmp_path, mid).state.actors[FOE], OWNER, "Overkindled Mark")
    turn(table, mid, FOE)
    marked = reload(tmp_path, mid)
    assert bears_mark(marked.state.actors[FOE], OWNER, "Overkindled Mark"), f"mark ended before the triggering action;owner_turns={marked.state.actors[OWNER].turns_started}"
    before = marked.state.actors[FOE].current_hp
    clock = [(c.expires_on, c.data) for c in marked.state.actors[FOE].conditions.values()
             if "mark.overkindled" in c.condition_id]
    source_turn = marked.state.actors[OWNER].turns_started
    prompts = settle(table, mid, candidate(combat, mid, "Talisman Spirit").candidate_id, {
        "reaction:typed." + SMALL: "first",
        "choice:willing.consent": "refuse",
        "choice:needle.overcomplete_result": selected,
        "choice:needle.overcomplete_damage_type": "force",
        "choice:needle.overcomplete_recipient": "first"})
    engine = reload(tmp_path, mid)
    spirit, = [a for a in engine.state.actors.values()
               if a.active and a.owner_id == FOE and a.summon and a.summon["group"] == "talisman_spirit"]
    choices = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.overcomplete_result"]
    assert choices, ("prompts=" + ",".join(p["context"]["reaction_source_id"] for p in prompts)
                     + f";reaction={engine.state.actors[OWNER].reaction_available};mark={bears_mark(engine.state.actors[FOE], OWNER, 'Overkindled Mark')}"
                     + f";pre_turn={source_turn};pre_clock={clock};post_turn={engine.state.actors[OWNER].turns_started}"
                     + ";removed=" + "|".join(e.source_definition_id + ":" + str(e.payload.get("condition_id"))
                                               for e in engine.events if e.event_type == "CONDITION_REMOVED"
                                               and "mark.overkindled" in str(e.payload.get("condition_id"))))
    choice = choices[0]
    assert {o["id"] for o in choice["choice"]["options"]} == {"damage", "expose", "reactions", "light"}
    surplus_light = [s for s in lighting.sources(engine) if s.name == "The Action Cannot Stay Small"]
    assert not bears_mark(engine.state.actors[FOE], OWNER, "Overkindled Mark")
    if selected == "damage":
        assert not surplus_light
        assert engine.state.actors[FOE].current_hp < before
        assert not any(c.condition_id == "condition:typed.overcomplete_effect"
                       for c in engine.state.actors[OWNER].conditions.values())
        return

    assert engine.state.actors[FOE].current_hp == before
    light, = surplus_light
    assert (light.following, light.cells, light.bright_ft, light.dim_ft) == (
        spirit.entity_id, frozenset(engine._actor_cells(spirit)), 20, 20)
    foe = engine.state.actors[FOE]
    moves = [c for c in engine.legal_candidates() if c.kind.value == "MOVE" and c.destination
             and (c.destination.x, c.destination.y) not in light.cells
             and engine._distance_actor_to_cell(foe, c.destination) <= 5]
    assert moves, "the summoner needs one legal adjacent step away from its summon"
    settle(table, mid, moves[0].candidate_id)
    engine = reload(tmp_path, mid)
    light, = [s for s in lighting.sources(engine) if s.name == "The Action Cannot Stay Small"]
    assert light.following == spirit.entity_id and light.cells == frozenset(engine._actor_cells(engine.state.actors[spirit.entity_id]))
    assert light.cells != frozenset(engine._actor_cells(engine.state.actors[FOE]))

    # Two deterministic damage rolls, delivered in a real committed Bonus Action before the source deadline.
    since = len(engine.events)
    settle(table, mid, candidate(combat, mid, "Damage probe", target=spirit.entity_id).candidate_id)
    engine = reload(tmp_path, mid)
    damage = [e.payload["hp_damage"] for e in engine.events[since:]
              if e.event_type == "DAMAGE_COMMITTED" and e.target_ids == (spirit.entity_id,)]
    assert damage == [4, 2], "only the next damage roll gains Vulnerability"
    held, = [c for c in engine.state.actors[OWNER].conditions.values()
             if c.condition_id == "condition:typed.overcomplete_effect"]
    assert held.data["vulnerable"] == 0
    assert any(s.name == "The Action Cannot Stay Small" for s in lighting.sources(engine)), "the hit spends Vulnerability, not light"
    # Deadline independently removes the light.
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert not [s for s in lighting.sources(engine) if s.name == "The Action Cannot Stay Small"]
