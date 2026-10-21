"""Earth-Shattering Fist's printed activation, at the native persisted table.

Rules: authority/typed_mechanics/rules_text.json, earth_shattering_fist.
Decoded record SHA256: 30744bf7a91615e312a598847fce603f7d11ebd654248f0decbb096fb4a1730c.
Adapted from the four Stone Fist review-1F20 cases; no archive fixtures.
"""
from collections import Counter

import pytest

from non_sphere_authority import NonSphereAuthorityService
from tests.h1_support import sheet
from tests.test_ns1r_non_sphere_authority import authority, insert_project
from tests.worker2_support import ALLY, FOE, OWNER, fixture, reload, settle

BODY = "tianxia.path.body_refining"
PARENT = "tianxia.subpath.body.stone_fist"
QUAKE = PARENT + ".feature.earth_shattering_fist"
CHOICE = "choice:needle.stone_fist_damage"
STAMINA = "resource:core.stamina"


def game(tmp_path, authority, dc):
    service, db = authority
    insert_project(db, "stone-cone", 14)
    service.initialize_for_project(
        "stone-cone", target_cl=14, path_ids=[BODY], path_attainment_by_id={BODY: 14}
    )
    service.select_subpath("stone-cone", BODY, PARENT)
    # Read the earned progression through the actual Open School producer.
    source = NonSphereAuthorityService(db)
    track, = source.export_state("stone-cone")["state"]["paths"]
    assert track["subpath_or_tradition_acquisition_provenance"]["recorded"]
    progression = source.project_locked_subpath_catalog_record(PARENT)["compatibility"]["factory"]["stage2_authority"]["feature_progression"]
    ids = [r["canonical_id"] for r in progression if r["granted_at_cl"] <= 14]
    assert QUAKE in ids
    foe = sheet([], cl=14, name="Mara")
    foe["ability_scores_and_statistics"]["hit_points"]["maximum"] = 5000

    def arena(doc):
        from combat.tabletop import normalize_map, to_battlefield
        authored = normalize_map({
            "display_name": "Stone Fist practice yard", "width_squares": 20,
            "height_squares": 14, "starts": {"team1": [[3, 6]], "team2": [[4, 6]]},
            "objects": [{"id": 1, "x": 5, "y": 5, "kind": "custom",
                         "name": "Practice section", "material": "stone", "size": "medium",
                         "hp": 5000, "ac": 1, "blocks": False, "unattended": True}],
        })
        doc["map_objects"] = to_battlefield(authored)["map_objects"]

    return fixture(
        tmp_path, ids, cl=14, primary="Stamina", owner_path="Body Refining",
        owner_dc=dc, foe_sheet=foe, foe_position={"x": 4, "y": 6},
        ally_position={"x": 5, "y": 6}, named=True, battlefield_transform=arena,
    )


def cone_action(table, mid):
    """Expand the real table header; retain the original eastward cone aim."""
    state = table.state(mid)
    menu = state["menu"]
    group, = [a for a in menu["actions"] if a["label"] == "Earth-Shattering Fist"]
    if group.get("lazy"):
        expanded = table.expand_action(
            mid, group["source_definition_id"], menu["decision_id"], menu["state_version"]
        )
        group, = expanded["actions"]
    return next(c["candidate_id"] for c in group["options"]
                if c.get("destination") and (c["destination"]["x"], c["destination"]["y"]) == (6, 6))


@pytest.mark.parametrize("damage_type", ["BLUDGEONING", "FORCE"])
@pytest.mark.parametrize("dc", [-100, 100])
def test_cone_commits_one_choice_before_each_recipients_save(tmp_path, authority, damage_type, dc):
    combat, table, mid = game(tmp_path, authority, dc)
    before = reload(tmp_path, mid)
    # Pin the original geometry separately from the incorrect side filter.
    from combat.gate2_runtime_models import Position
    from combat.spatial_areas import actor_in_area
    action, = [a for a in before.action_catalog.values()
               if a.owner_id == OWNER and a.display_name == "Earth-Shattering Fist"]
    area = action.parameters["typed"]["area"]
    assert area["shape"] == "cone" and area["size_ft"] == 20
    origin = before.state.actors[OWNER].position
    aim = Position(x=6, y=6)
    assert all(actor_in_area(before, before.state.actors[aid], origin, aim, area)
               for aid in (ALLY, FOE))
    cid = cone_action(table, mid)
    prompts = settle(table, mid, cid, {CHOICE: damage_type})
    engine = reload(tmp_path, mid)  # includes mechanical replay verification
    events = [e for e in engine.events if e.sequence > before.events[-1].sequence]
    saves = [e for e in events if e.event_type == "SAVE_ROLLED"]
    # Keep this first: the original four regressions missed the same ally.
    assert Counter(e.actor_id for e in saves) == Counter({ALLY: 1, FOE: 1})
    declarations = [p for p in prompts if p["context"]["reaction_source_id"] == CHOICE]
    declaration, = declarations
    assert {o["id"] for o in declaration["choice"]["options"]} == {"BLUDGEONING", "FORCE"}
    assert declaration["context"]["reactor_id"] == OWNER
    prompt = declaration["context"]["choice_trigger"]["prompt"]
    assert all(name in prompt for name in ("Earth-Shattering Fist", "Tobin", "Mara", "4 Stamina", "Action"))
    activation, = [e for e in events if e.event_type == "PASSIVE_TRIGGERED" and e.source_definition_id == QUAKE]
    assert activation.actor_id == OWNER and activation.payload["damage_type"] == damage_type
    assert all(activation.sequence < e.sequence for e in saves)
    assert all(e.source_definition_id == QUAKE and e.payload["reason"] == f"SAVE:{QUAKE}:DEX" for e in saves)
    damage = [e for e in events if e.event_type == "DAMAGE_COMMITTED"]
    assert Counter(t for e in damage for t in e.target_ids) == Counter({ALLY: 1, FOE: 1})
    assert all(e.payload["damage_type"] == damage_type for e in damage)
    roll, = [r for r in engine.rolls if r.reason == f"DAMAGE:{QUAKE}"]
    assert roll.expression.startswith("6d8")
    for actor_id in (ALLY, FOE):
        target = engine.state.actors[actor_id]
        expected = roll.total if dc == 100 else roll.total // 2
        assert before.state.actors[actor_id].current_hp - target.current_hp == expected
        assert any(c.condition_id.endswith("prone") for c in target.conditions.values()) == (dc == 100)
    updates = [e for e in events if e.event_type == "OBJECT_UPDATED" and "damage" in e.payload]
    update, = updates
    assert update.payload["damage"]["taken"] == 2 * roll.total
    assert engine.state.actors[OWNER].current_hp == before.state.actors[OWNER].current_hp
    assert engine.state.actors[OWNER].resources[STAMINA] == 96
    assert not engine.state.actors[OWNER].action_available
    zone, = [z for z in engine.state.zones.values() if z.source_definition_id == QUAKE and z.active]
    assert not zone.duration_rounds
    # A second cold table/service instance retains the same history and state.
    cold = reload(tmp_path, mid)
    assert cold.state.actors[ALLY].current_hp == engine.state.actors[ALLY].current_hp
    assert cold.state.zones[zone.zone_id].affected_cells == zone.affected_cells
