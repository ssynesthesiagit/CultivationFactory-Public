"""Synthetic Space regressions: real compiled actions, table commits and replay."""
import pytest

from combat.gate2_runtime_models import CandidateKind
from tests.test_hunt32_edge import OWNER, FOE, match, reload

PREFIX = "tianxia.talent.space."
REACH, LINE, DISPLACE, BLADES = [PREFIX + name for name in (
    "folded_reach", "folded_weapon_line", "spatial_displacement", "space_between_blades")]


def candidates(combat, mid, source):
    engine = combat._load_session(mid).engine
    return [c for c in engine.legal_candidates()
            if c.source_definition_id in engine.action_catalog
            and ((engine.action_catalog[c.source_definition_id].parameters or {}).get("typed") or {}).get("source") == source
            ]


def commit(table, mid, candidate, pick=None):
    state = table.state(mid)
    menu = state["menu"]
    args = candidate.candidate_id, menu["decision_id"], menu["state_version"], state["last_sequence"]
    answers, prompts = [], []
    result = table.act(mid, *args, answers)
    while result["status"] == "REACTION_REQUIRED":
        prompt = result["reaction"]
        prompts.append(prompt)
        assert len(prompts) < 12
        ids = pick(prompt) if pick else []
        answers.append({**prompt["context"], "selection": "USE" if ids else "DECLINE",
                        **({"option_ids": ids} if ids else {})})
        result = table.act(mid, *args, answers)
    assert result["status"] == "COMMITTED"
    return prompts


def use(combat, table, mid, source, pick=None, target=None):
    choices = candidates(combat, mid, source)
    return commit(table, mid, next(c for c in choices if target is None or target in c.target_ids), pick)


PERMISSION = "choice:needle.hazard_permission"   # the printed GM's choice of permitted hazard squares
DESTINATION = "choice:needle.subject_destination"  # the owner's own landing square


def permission_prompts(prompts):
    """The prompts the table returns for the printed GM's terrain permission."""
    return [p for p in prompts if p["context"].get("reaction_source_id") == PERMISSION]


def destination_prompts(prompts):
    """The prompts the table returns for the owner's landing square."""
    return [p for p in prompts if p["context"].get("reaction_source_id") == DESTINATION]


def strikes(engine):
    return [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == OWNER]


def test_folded_reach_offers_real_origins_and_consumes_only_next_strike(tmp_path):
    combat, table, mid = match(tmp_path, [REACH, "tianxia.path.body_refining.feature.extra_attack"], positions={
        OWNER: {"x": 3, "y": 6}, FOE: {"x": 7, "y": 6}})
    use(combat, table, mid, REACH)
    engine = reload(combat, tmp_path, mid)
    folded = [c for c in engine.legal_candidates()
              if FOE in c.target_ids and str((c.metadata.get("effect_origin") or {}).get("id", "")).startswith("fold:")]
    assert folded
    selected = next(c for c in folded if c.metadata["effect_origin"]["position"] == {"x": 6, "y": 6, "z": 0})
    before = engine.state.actors[OWNER].position
    commit(table, mid, selected)
    engine = reload(combat, tmp_path, mid)
    assert engine.state.actors[OWNER].position == before
    assert len(strikes(engine)) == 1
    removed = next(e for e in engine.events if e.event_type == "CONDITION_REMOVED"
                   and e.payload.get("condition_id") == "condition:typed.folded_reach")
    damage = next((e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"
                   and e.actor_id == OWNER), None)
    if damage is not None:
        assert removed.sequence < damage.sequence
    assert not any(c.condition_id == "condition:typed.folded_reach"
                   for c in engine.state.actors[OWNER].conditions.values())


def test_folded_reach_preserves_touch_treatment_and_replay(tmp_path):
    ally = "actor:factory.h32-ally"
    mend = "LIFE_BASE_MEND_THE_PULSE"
    combat, table, mid = match(tmp_path, [REACH, mend], allies=True, positions={
        OWNER: {"x": 3, "y": 6}, ally: {"x": 7, "y": 6}, FOE: {"x": 12, "y": 6}},
        setup_actions=[{"name": "Injury", "target": "ANY_CREATURE",
            "effects": [{"type": "damage", "flat": 30, "damage_types": ["force"], "applies_to": "target"}]}])
    use(combat, table, mid, "test:h32.setup", target=ally)
    use(combat, table, mid, REACH)
    engine = reload(combat, tmp_path, mid)
    hp = engine.state.actors[ally].current_hp
    treatment = next(c for c in candidates(combat, mid, mend) if ally in c.target_ids
                     and (c.metadata.get("effect_origin") or {}).get("position") == {"x": 6, "y": 6, "z": 0})
    commit(table, mid, treatment, lambda p: [p["choice"]["options"][0]["id"]] if p.get("choice") else [])
    engine = reload(combat, tmp_path, mid)
    assert engine.state.actors[ally].current_hp > hp
    assert not any(c.condition_id == "condition:typed.folded_reach"
                   for c in engine.state.actors[OWNER].conditions.values())
    assert engine.state.actors[OWNER].position.x == 3


def test_unused_fold_expires_and_solid_boundary_cannot_be_a_remote_origin(tmp_path):
    def solid_wall(arena):
        # A solid stone wall across the map: no folded point may sit behind it.
        arena["terrain_regions"] = [
            *[r for r in arena.get("terrain_regions", []) if r["terrain_type"] != "BLOCKED"],
            {"region_id": "test:solid_wall", "terrain_type": "BLOCKED", "movement_cost": 0,
             "description": "Solid stone wall.",
             "cells": [{"x": 5, "y": y} for y in range(14)]}]
    combat, table, mid = match(tmp_path, [REACH], arena_edit=solid_wall,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 7, "y": 6}})
    use(combat, table, mid, REACH)
    engine = reload(combat, tmp_path, mid)
    from combat.action_geometry import origins
    owner = engine.state.actors[OWNER]
    action = next(a for a in engine.action_catalog.values() if a.owner_id == OWNER
                  and any(e.get("attack_kind") == "unarmed"
                          for e in (a.parameters.get("typed") or {}).get("effects") or []))
    assert all(p["position"]["x"] < 5 for p in origins(engine, owner, action))
    commit(table, mid, next(c for c in engine.legal_candidates() if c.kind == CandidateKind.END_TURN))
    engine = reload(combat, tmp_path, mid)
    assert not any(c.condition_id == "condition:typed.folded_reach"
                   for c in engine.state.actors[OWNER].conditions.values())


def test_folded_weapon_line_adds_ten_feet_and_hit_denies_reactions(tmp_path):
    combat, table, mid = match(tmp_path, [REACH, LINE], positions={
        OWNER: {"x": 3, "y": 6}, FOE: {"x": 9, "y": 6}}, setup_actions=[{
            "name": "Lower AC", "target": "ANY_CREATURE",
            "effects": [{"type": "ac_bonus", "flat": -100, "applies_to": "target",
                         "expires_on": "UNTIL_REMOVED"}]}])
    use(combat, table, mid, "test:h32.setup", target=FOE)
    # The optional printed extra CP is represented by a distinct compiled variant.
    choices = candidates(combat, mid, REACH)
    engine = combat._load_session(mid).engine
    enhanced = next(c for c in choices if
                    (engine.action_catalog[c.source_definition_id].parameters.get("typed", {}).get("modifier") or {}).get("id") == LINE)
    commit(table, mid, enhanced)
    engine = reload(combat, tmp_path, mid)
    held = next(c for c in engine.state.actors[OWNER].conditions.values()
                if c.condition_id == "condition:typed.folded_reach")
    assert held.data["extra_ft"] == 30  # CL20: 20 + 10
    attack = next(c for c in engine.legal_candidates() if FOE in c.target_ids
                  and str((c.metadata.get("effect_origin") or {}).get("id", "")).startswith("fold:"))
    commit(table, mid, attack)
    engine = reload(combat, tmp_path, mid)
    assert any(c.condition_id == "condition:typed.reaction_denied"
               for c in engine.state.actors[FOE].conditions.values())
    assert sum(e.payload.get("amount", 0) for e in engine.events
               if e.event_type == "RESOURCE_SPENT" and e.actor_id == OWNER) == 2


def test_nested_attack_does_not_inherit_folded_weapon_outcome(tmp_path):
    followup = {"type": "attack", "attack_kind": "unarmed", "count": 1, "on_hit": [], "on_miss": []}
    combat, table, mid = match(tmp_path, [REACH, LINE], setup_actions=[{
        "name": "Nested attacks", "target": "HOSTILE_ENTITY",
        "typed": {"numbers": {"attack_bonus": 100},
                  "weapon": {"damage": {"count": 1, "sides": 2, "modifier": 0}, "damage_type": "FORCE"}},
        "effects": [{"type": "attack", "attack_kind": "unarmed", "count": 1,
                     "on_hit": [followup], "on_miss": [followup]}]}])
    engine = reload(combat, tmp_path, mid)
    enhanced = next(c for c in candidates(combat, mid, REACH)
                    if (engine.action_catalog[c.source_definition_id].parameters["typed"].get("modifier") or {}).get("id") == LINE)
    commit(table, mid, enhanced)
    engine = reload(combat, tmp_path, mid)
    attack = next(c for c in candidates(combat, mid, "test:h32.setup") if FOE in c.target_ids
                  and (c.metadata.get("effect_origin") or {}).get("position") == {"x": 3, "y": 6, "z": 0})
    commit(table, mid, attack)
    engine = reload(combat, tmp_path, mid)
    assert len(strikes(engine)) == 2
    outcomes = [e for e in engine.events if e.event_type == "CONDITION_APPLIED" and FOE in e.target_ids
                and e.payload.get("condition_id") in {"condition:typed.reaction_denied", "condition:typed.attack_direction"}]
    assert len(outcomes) == 1


def test_displacement_large_failed_margin_allows_immediate_hazard(tmp_path):
    combat, table, mid = match(tmp_path, [DISPLACE], map_terrain=[
        {"terrain": "fire terrain", "cells": [[7, 6]], "pb": 3, "save_dc": 1000}])
    prompts = use(combat, table, mid, DISPLACE,
                  lambda p: ["cell:7,6"] if any(o["id"] == "cell:7,6"
                    for o in (p.get("choice") or {}).get("options", [])) else [])
    engine = reload(combat, tmp_path, mid)
    assert prompts
    saves = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE
             and "spatial_displacement" in e.source_definition_id]
    assert saves[-1].payload["dc"] - saves[-1].payload["total"] >= 5
    assert engine.state.actors[FOE].position.x == 7
    assert any(e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids for e in engine.events)
    assert permission_prompts(prompts)


def test_displacement_does_not_invent_the_printed_gms_permission(tmp_path):
    combat, table, mid = match(tmp_path, [DISPLACE], map_terrain=[
        {"terrain": "fire terrain", "cells": [[7, 6]], "pb": 3, "save_dc": 1000}])
    prompts = use(combat, table, mid, DISPLACE)  # decline permission and landing
    engine = reload(combat, tmp_path, mid)
    assert permission_prompts(prompts)
    destinations = [o["id"] for p in destination_prompts(prompts)
                    for o in (p.get("choice") or {}).get("options", [])]
    assert "cell:7,6" not in destinations
    assert engine.state.actors[FOE].position.x == 4


def test_hazard_permission_batches_preserve_more_than_64_destinations(tmp_path):
    cells = [(x, y) for y in range(13) for x in range(11) if (x, y) not in {(3, 6), (4, 6)}]
    combat, table, mid = match(tmp_path, [DISPLACE], map_terrain=[
        {"terrain": "fire terrain", "cells": [[x, y]], "pb": 3, "save_dc": 1000} for x, y in cells])
    engine = reload(combat, tmp_path, mid)
    from combat import zones
    from combat.ext.teleport_steps import destinations
    from combat.ext.needle import cell_id
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    hazard = zones.hazard_test(engine, foe, movement_mode="teleport", immediate_only=True)
    expected = {cell_id(cell) for cell in destinations(engine, foe, 30, viewer=owner) if hazard(cell)}
    assert len(expected) > 64
    prompts = use(combat, table, mid, DISPLACE)
    batches = [p["choice"]["options"] for p in permission_prompts(prompts)]
    assert len(batches) > 1
    assert all(len(batch) <= 64 for batch in batches)
    assert {option["id"] for batch in batches for option in batch} == expected
    engine = reload(combat, tmp_path, mid)
    assert engine.state.actors[FOE].position.x == 4


def test_space_between_blades_is_full_without_a_narrative_gm_rider():
    import json
    from combat.factory_compiler import TYPED_AUTHORITY
    row = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"][BLADES]
    assert row["riders"] == []
    assert row["coverage"] == "FULL"


@pytest.mark.parametrize("cl,feet", [(9, 10), (10, 15), (15, 20)])
def test_folded_points_use_printed_cl_distance_in_three_dimensions(tmp_path, cl, feet):
    combat, table, mid = match(tmp_path, [REACH], cl=cl)
    use(combat, table, mid, REACH)
    engine = reload(combat, tmp_path, mid)
    from combat.action_geometry import origins
    owner = engine.state.actors[OWNER]
    action = next(a for a in engine.action_catalog.values() if a.owner_id == OWNER
                  and any(e.get("attack_kind") == "unarmed"
                          for e in (a.parameters.get("typed") or {}).get("effects") or []))
    points = origins(engine, owner, action)
    assert points
    from combat.gate2_runtime_models import Position
    assert max(engine.grid.distance_ft(owner.position, Position(**p["position"])) for p in points) == feet
    assert any(p["position"]["z"] > 0 for p in points)


def test_folded_point_not_body_supplies_cover(tmp_path):
    def half_cover(arena):
        arena["terrain_regions"] = [
            *arena.get("terrain_regions", []),
            {"region_id": "test:half_cover", "terrain_type": "SIMPLE_COVER", "movement_cost": 0,
             "description": "Low stone wall.", "cells": [{"x": 5, "y": 6}]}]
    combat, table, mid = match(tmp_path, [REACH], arena_edit=half_cover,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 7, "y": 6}})
    use(combat, table, mid, REACH)
    engine = reload(combat, tmp_path, mid)
    from combat.action_geometry import activate
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    attack = next(c for c in engine.legal_candidates() if FOE in c.target_ids
                  and (c.metadata.get("effect_origin") or {}).get("position") == {"x": 6, "y": 6, "z": 0})
    assert engine._cover_bonus_actor_to_actor(owner, foe) == 2
    with activate(engine, owner, attack.source_definition_id, attack.metadata["effect_origin"]):
        assert engine._cover_bonus_actor_to_actor(owner, foe) == 0
    commit(table, mid, attack)
    reload(combat, tmp_path, mid)


def test_folded_weapon_miss_records_only_direction_and_not_a_hidden_location(tmp_path):
    combat, table, mid = match(tmp_path, [REACH, LINE], positions={
        OWNER: {"x": 3, "y": 6}, FOE: {"x": 9, "y": 6}}, setup_actions=[{
            "name": "High AC", "target": "ANY_CREATURE",
            "effects": [{"type": "ac_bonus", "flat": 100, "applies_to": "target",
                         "expires_on": "UNTIL_REMOVED"}]}])
    use(combat, table, mid, "test:h32.setup", target=FOE)
    engine = reload(combat, tmp_path, mid)
    enhanced = next(c for c in candidates(combat, mid, REACH)
                    if (engine.action_catalog[c.source_definition_id].parameters["typed"].get("modifier") or {}).get("id") == LINE)
    commit(table, mid, enhanced)
    engine = reload(combat, tmp_path, mid)
    attack = next(c for c in engine.legal_candidates() if FOE in c.target_ids
                  and (c.metadata.get("effect_origin") or {}).get("position") == {"x": 8, "y": 6, "z": 0})
    commit(table, mid, attack)
    engine = reload(combat, tmp_path, mid)
    assert not any(c.condition_id == "condition:typed.reaction_denied"
                   for c in engine.state.actors[FOE].conditions.values())
    fact = next(c for c in engine.state.actors[FOE].conditions.values()
                if c.condition_id == "condition:typed.attack_direction")
    assert [fact.data[k] for k in ("dx", "dy", "dz")] == [-1, 0, 0]
    assert not {"position", "x", "y", "z"} & fact.data.keys()


@pytest.mark.parametrize("threshold,allowed", [(5, True), (100, False)])
def test_destination_safety_uses_its_own_settled_parent_save(tmp_path, threshold, allowed):
    # The intervening save is unrelated to the displacement. Its total must
    # not replace the parent save's margin when the destination is offered.
    teleport = {"type": "teleport", "applies_to": "target",
                "choose_subject_destination": True, "distance_ft": 20,
                "destination_must_be_safe": True, "unsafe_on_failure_margin": threshold}
    combat, table, mid = match(tmp_path, [DISPLACE], map_terrain=[{
        "terrain": "fire terrain", "cells": [[7, 6]], "pb": 3, "save_dc": 1000}],
        setup_actions=[{"name": "Strong nested save", "target": "ANY_CREATURE",
            "effects": [{"type": "save_bonus", "amount": 1000, "abilities": ["WIS"],
                         "applies_to": "target", "expires_on": "UNTIL_REMOVED"}]},
            {"name": "Nested saves and displacement", "target": "ANY_CREATURE",
            "typed": {"numbers": {"save_dc": 100}},
            "effects": [{"type": "save", "ability": "cha", "on_fail": [
                {"type": "save", "ability": "wis", "dc": "technique_save_dc",
                 "on_fail": [], "on_success": []}, teleport]}]}])
    seen = []
    def choose(prompt):
        ids = [o["id"] for o in (prompt.get("choice") or {}).get("options", [])]
        seen.extend(ids)
        return ["cell:7,6"] if "cell:7,6" in ids else []
    engine = reload(combat, tmp_path, mid)
    # The WIS bonus must be in place before the nested save is rolled, so the
    # fixture picks that action by its own effect, not by menu order.
    bonus = next(c for c in candidates(combat, mid, "test:h32.setup") if FOE in c.target_ids
                 and engine.action_catalog[c.source_definition_id].parameters["typed"]["effects"][0]["type"] == "save_bonus")
    commit(table, mid, bonus)
    engine = reload(combat, tmp_path, mid)
    action = next(c for c in candidates(combat, mid, "test:h32.setup") if FOE in c.target_ids
                  and engine.action_catalog[c.source_definition_id].parameters["typed"]["effects"][0]["type"] == "save")
    commit(table, mid, action, choose)
    engine = reload(combat, tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE]
    assert saves[0].payload["success"] is False and saves[1].payload["success"] is True
    assert ("cell:7,6" in seen) == allowed
    assert (engine.state.actors[FOE].position.x == 7) == allowed


def test_fold_grant_expires_at_current_turn_end_and_reaction_denial_at_targets_start(tmp_path):
    combat, table, mid = match(tmp_path, [REACH, LINE], setup_actions=[{
        "name": "Low AC", "target": "ANY_CREATURE",
        "effects": [{"type": "ac_bonus", "flat": -100, "applies_to": "target",
                     "expires_on": "UNTIL_REMOVED"}]}])
    use(combat, table, mid, "test:h32.setup", target=FOE)
    engine = reload(combat, tmp_path, mid)
    enhanced = next(c for c in candidates(combat, mid, REACH)
                    if (engine.action_catalog[c.source_definition_id].parameters["typed"].get("modifier") or {}).get("id") == LINE)
    commit(table, mid, enhanced)
    engine = reload(combat, tmp_path, mid)
    attack = next(c for c in engine.legal_candidates() if FOE in c.target_ids
                  and c.source_definition_id in engine.action_catalog
                  and any(e.get("attack_kind") == "unarmed" for e in
                          (engine.action_catalog[c.source_definition_id].parameters.get("typed") or {}).get("effects") or []))
    commit(table, mid, attack)
    engine = reload(combat, tmp_path, mid)
    assert any(c.condition_id == "condition:typed.reaction_denied"
               for c in engine.state.actors[FOE].conditions.values())
    end = next(c for c in engine.legal_candidates() if c.kind == CandidateKind.END_TURN)
    commit(table, mid, end)
    engine = reload(combat, tmp_path, mid)
    assert not any(c.condition_id == "condition:typed.reaction_denied"
                   for c in engine.state.actors[FOE].conditions.values())
    assert not any(c.condition_id == "condition:typed.folded_reach"
                   for c in engine.state.actors[OWNER].conditions.values())
