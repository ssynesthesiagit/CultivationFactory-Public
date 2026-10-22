"""Spatial Edge's printed level table through table commit, reload and replay."""
import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

EDGE = "TAL_SPACE_SPATIAL_EDGE"
OWNER, FOE = "actor:factory.h32-owner", "actor:factory.h32-foe"


def match(tmp_path, mids, *, cl=20, primary="Qi", mode="MANUAL", allies=False, ally_mode="MANUAL", ally_mids=None, map_terrain=None, owner_resources=None, setup_actions=(), extra_foes=(), ally_attack_bonus=None, foe_mids=None, positions=None, foe_setup_actions=(), ally_setup_actions=(), battlefield=None):
    """Synthetic saved table; no live characters, dice replacement or GUI."""
    doc = sheet(mids, cl=cl, primary=primary, key="WIS", score=18, dc=40)
    doc["ability_scores_and_statistics"]["technique_attack_bonus"] = 100
    doc["ability_scores_and_statistics"]["primary_resource"]["maximum"] = 0 if mids == [EDGE] else 30
    docs = [doc, sheet(foe_mids or [], cl=20)]
    ids = [OWNER, FOE]
    if allies:
        ids.insert(1, "actor:factory.h32-ally")
        docs.insert(1, sheet([EDGE] if ally_mids is None else ally_mids, cl=20))
        if ally_attack_bonus is not None:
            docs[1]["ability_scores_and_statistics"]["technique_attack_bonus"] = ally_attack_bonus
    for actor_id, hp in extra_foes:
        foe_doc = sheet([], cl=20)
        foe_doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = hp
        ids.append(actor_id)
        docs.append(foe_doc)
    bundles = [compile_character(d, actor_id=a, reaction_plan={"ask": True}) for a, d in zip(ids, docs)]
    # Optional synthetic fixture packets are sealed before match creation; their
    # effects still pass through real table commits, journal replay and reload.
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    fixture_actions = [*( (0, spec) for spec in setup_actions),
                        *( (ids.index(FOE), spec) for spec in foe_setup_actions)]
    if ally_setup_actions:
        fixture_actions.extend((ids.index("actor:factory.h32-ally"), spec) for spec in ally_setup_actions)
    for index, (bundle_index, spec) in enumerate(fixture_actions):
        action = ActionDefinition(
            source_definition_id=f"action:test.h32.setup.{index}", display_name=spec["name"],
            owner_id=ids[bundle_index], economy=EconomyKind(spec.get("economy", "NONE")), resolution_kind="TYPED",
            target_kind=spec.get("target", "SELF"), range_ft=60, radius_ft=spec.get("radius_ft"),
            parameters={"typed": {"source": "test:h32.setup", "effects": spec["effects"],
                                  "numbers": {}, "duration": {"kind": "instant"}, "riders": [],
                                  **spec.get("typed", {})},
                        "any_cell": spec.get("any_cell", True), "player_only": spec.get("player_only", True),
                        # Explicit free activation for this synthetic setup packet (ad49b65f: NONE economy alone
                        # is not a turn intent). Packets that print an economy spend it through that economy.
                        "free_primary": spec.get("economy", "NONE") == "NONE",
                        "expected_damage": spec.get("expected_damage", 0)})
        bundles[bundle_index]["action_catalog"].append(action.model_dump(mode="json"))
        bundles[bundle_index]["actor_template"]["action_ids"].append(action.source_definition_id)
    # Optional starting pools belong only to this synthetic table's saved template.
    for resource_id, amount in (owner_resources or {}).items():
        resources = bundles[0]["actor_template"]["resources"]
        existing = next((r for r in resources if r["resource_id"] == resource_id), None)
        if existing is None:
            resources.append({"resource_id": resource_id, "initial": amount, "maximum": amount})
        else:
            existing["initial"] = amount
            existing["maximum"] = max(existing["maximum"], amount)
    # Find an ordinary seeded initiative with the caster and ally before the victim.
    from combat.gate2_rolls import DeterministicRollAuthority
    for n in range(1000):
        seed = f"H32-regression-{n}"
        roller = DeterministicRollAuthority(seed)
        rolls = []
        for bundle in bundles:
            actor = bundle["actor_template"]
            roll = roller.d20(modifier=actor["initiative_bonus"], actor_id=actor["entity_id"], reason="INITIATIVE")
            rolls.append((roll.total, actor["initiative_bonus"], actor["dexterity_score"], actor["entity_id"]))
        if [r[3] for r in sorted(rolls, key=lambda r: (-r[0], -r[1], -r[2], r[3]))] == ids:
            break
    combat = CombatService(ROOT, tmp_path)
    friendly = [a for a in ids if a != FOE and a not in {f[0] for f in extra_foes}]
    hostile = [a for a in ids if a not in friendly]
    arena = battlefield if battlefield is not None else combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    if map_terrain is not None:
        import copy
        arena = copy.deepcopy(arena)
        arena["map_terrain"] = map_terrain
    mid = combat._finish_factory_match(
        bundles, ids, {a: "team:factory" if a in friendly else "team:opponents" for a in ids},
        positions or {a: {"x": 3 + i, "y": 6} for i, a in enumerate(ids)},
        arena, friendly, hostile,
        control_modes={a: mode if a == OWNER else ally_mode if a.endswith("-ally") else "MANUAL" for a in ids},
        match_seed=seed, maximum_rounds=10, display_name="Hunt 32 regression")["match_id"]
    return combat, TabletopService(combat, tmp_path), mid


def act(table, mid, label=None, target=None, answers=()):
    state = table.state(mid)
    menu = state["menu"]
    if label:
        group = next(g for g in menu["actions"] if g["label"] == label)
        option = next(o for o in group["options"] if target is None or target in o.get("target_ids", []))
        cid = option["candidate_id"]
    else:
        cid = menu["end_turn"]
    return table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))


def reload(combat, tmp_path, mid):
    old = combat._load_session(mid)
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert fresh.engine.state.model_dump(mode="json") == old.engine.state.model_dump(mode="json")
    assert fresh.mechanical.replay()["status"] == "PASS"
    return fresh.engine


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
@pytest.mark.parametrize("cl,count", [(1, 1), (4, 1), (5, 2), (10, 2), (11, 3), (16, 3), (17, 4), (20, 4)])
def test_edge_table_level_dice_keep_modifier_at_zero_qi(tmp_path, cl, count, mode):
    combat, table, mid = match(tmp_path, [EDGE], cl=cl, mode=mode)
    if mode == "MANUAL":
        result = act(table, mid, "Spatial Edge", FOE)
    else:
        for _ in range(12):
            result = table.auto_step(mid, table.state(mid)["last_sequence"])
            assert result["status"] == "COMMITTED"
            if any(e.event_type == "DAMAGE_ROLLED" and EDGE in e.source_definition_id
                   for e in combat._load_session(mid).engine.events):
                break
    assert result["status"] == "COMMITTED"
    engine = reload(combat, tmp_path, mid)
    rolls = [e.payload for e in engine.events if e.event_type == "DAMAGE_ROLLED" and EDGE in e.source_definition_id]
    assert rolls
    for roll in rolls:
        assert roll["expression"] == f"{count * (2 if roll.get('critical') else 1)}d8+4"
    assert not any(e.event_type == "RESOURCE_SPENT" and EDGE in e.source_definition_id for e in engine.events)
