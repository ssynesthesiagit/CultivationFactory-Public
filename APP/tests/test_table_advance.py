"""Growing a finished character at the table (owner 2026-09-27: "the character sheets be updated with new spheres etc so
when the player is playing theres a way to interact with the sheets"; "composite techniques ... created and added";
ruling: rules-checked with a GM override). combat/table_advance.py, combat/forged.py, TabletopService.forge."""

import json
from pathlib import Path

import pytest

from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat import table_advance
from combat.factory_compiler import TYPED_AUTHORITY, compile_character
from combat.tabletop import TabletopError
from combat.tabletop_service import TabletopService
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
PID = "0badc0de-0000-4000-8000-000000000001"
BASE = {**SHEET, "identity": {**SHEET["identity"], "path_ids": ["tianxia.path.qi_cultivation"]},
        "path_and_subpath": {"path_record_id": "tianxia.path.qi_cultivation", "path_record_ids": ["tianxia.path.qi_cultivation"]},
        "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.magma", "tianxia.sphere.stars"],
                                "learned_talent_record_ids": ["TAL_MAGMA_LAVA_SPIT", "STARS_TAL_FALLING_STAR"]}}


@pytest.fixture(scope="module")
def catalog():
    return CanonicalCatalogAuthorityService(ROOT)


def _service(tmp_path, catalog):
    mechanics = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]
    service = TabletopService(None, tmp_path)

    class Combat:
        userdata_root = tmp_path

        def _factory_owner_sheet(self, project_id, *, apply_table=True):
            if apply_table:
                return table_advance.apply(BASE, service.buttons.get(project_id).get("advancement"), mechanics)
            return BASE

    service.combat = Combat()
    service.canonical_catalog = catalog
    return service


def test_a_talent_is_legal_only_when_its_prerequisites_hold():
    record = {"typed_constraints": [{"kind": "minimum_cl", "value": 5, "scope": "acquisition"},
                                    {"kind": "owning_sphere", "target_id": "tianxia.sphere.stars", "scope": "acquisition"},
                                    {"kind": "talent", "target_id": "TAL_X", "alternative_id": "a1", "scope": "acquisition", "display_name": "X"}],
              "prerequisite_clauses": [{"alternatives": [{"alternative_id": "a1"}], "body": "X, CL 5+", "scope": "acquisition"}]}
    have = table_advance.known(BASE)
    assert table_advance.talent_status(record, have) == {"legal": False, "gm": False, "reasons": ["X, CL 5+"]}
    have["talents"].add("TAL_X")
    assert table_advance.talent_status(record, have)["legal"]
    have["cl"] = 4
    assert table_advance.talent_status(record, have)["reasons"] == ["needs CL 5"]
    record["typed_constraints"].append({"kind": "structural_authority", "scope": "acquisition", "raw_text": "a Sect's permission"})
    have["cl"] = 10
    assert table_advance.talent_status(record, have) == {"legal": False, "gm": True, "reasons": ["GM: a Sect's permission"]}


def test_learning_at_the_table_is_rules_checked_and_the_gm_can_grant_past_them(tmp_path, catalog):
    service = _service(tmp_path, catalog)
    options = service.advancement(PID)
    legal = next(row for row in options["talents"] if row["legal"] and row["sphere_id"] == "tianxia.sphere.stars")
    blocked = next(row for row in options["talents"] if not row["legal"] and not row["gm"])
    service.add_advancement(PID, "talent", legal["id"])
    with pytest.raises(TabletopError) as refused:
        service.add_advancement(PID, "talent", blocked["id"])
    assert refused.value.code == "TABLETOP_ADVANCE_NOT_LEGAL"
    added = service.add_advancement(PID, "talent", blocked["id"], gm=True)["added"]["talents"]
    assert [(row["id"], row["gm"]) for row in added] == [(legal["id"], False), (blocked["id"], True)]
    sheet = service.combat._factory_owner_sheet(PID)
    assert {legal["id"], blocked["id"]} <= set(sheet["spheres_and_talents"]["learned_talent_record_ids"])
    service.add_advancement(PID, "sphere", "tianxia.sphere.air")
    sheet = service.combat._factory_owner_sheet(PID)
    assert "tianxia.sphere.air" in sheet["spheres_and_talents"]["sphere_record_ids"]
    assert "AIR_BASE_WIND_LASH" in sheet["spheres_and_talents"]["automatic_sphere_component_record_ids"]
    service.remove_advancement(PID, "talent", blocked["id"])
    assert blocked["id"] not in service.combat._factory_owner_sheet(PID)["spheres_and_talents"]["learned_talent_record_ids"]


def test_a_forged_burst_is_built_by_the_rules_and_fights_as_an_area_save(tmp_path, catalog):
    service = _service(tmp_path, catalog)
    design = {"name": "Meteor Spit", "base_form": "burst", "primary_talent_id": "TAL_MAGMA_LAVA_SPIT",
              "secondary_talent_ids": ["STARS_TAL_FALLING_STAR"], "augment_ids": ["increased_damage", "major_condition"],
              "drawback_ids": [], "choices": {"major_condition": "blinded"}}
    preview = service.forge(PID, design)
    technique = preview["technique"]
    assert technique["complexity"]["final"] == 6 and technique["cp_cost"]["final"] == 5  # Burst 2 + Stars 1 + 1 + 2; CP 2 + 1 + 2
    assert preview["combat"]["area"] == "15-ft sphere" and preview["combat"]["effects"][0].startswith("DEX save")
    with pytest.raises(TabletopError) as over:  # Core Formation's Complexity 6: one more Augment is too much
        service.forge(PID, {**design, "augment_ids": [*design["augment_ids"], "expanded_area"]})
    assert over.value.code == "FORGING_COMPLEXITY_EXCEEDED"
    service.forge(PID, design, save=True)
    bundle = compile_character(service.combat._factory_owner_sheet(PID), actor_id="actor:factory." + PID)
    rows = bundle["action_catalog"].values() if isinstance(bundle["action_catalog"], dict) else bundle["action_catalog"]
    [action] = [row if isinstance(row, dict) else row.model_dump() for row in rows
                if (row if isinstance(row, dict) else row.model_dump())["display_name"] == "Meteor Spit"]
    save = action["parameters"]["typed"]["effects"][0]
    damage = next(effect for effect in save["on_fail"] if effect.get("type") == "damage")
    assert action["target_kind"] == "CELL" and action["radius_ft"] == 15 and action["costs"][0][1] == 5
    # Lava Spit prints 2d8 / 3d8 / 5d8 / 7d8 by Cultivation Level (a CL-scaled row: dice_by_cl is what the executor rolls, "dice" is its
    # CL 1-4 tier); Increased Damage adds one die to each.  The sheet is CL 10: 3d8 printed, so 4d8 rolled.  Falling Star's element joins.
    from factory_authoring.typed_mechanics import dice_for_cl
    cl = action["parameters"]["typed"]["numbers"]["cl"]
    assert damage["dice_by_cl"] == [[1, 4, 3, 8], [5, 10, 4, 8], [11, 16, 6, 8], [17, 20, 8, 8]] and damage["dice"] == {"count": 3, "sides": 8}
    assert dice_for_cl(damage["dice_by_cl"], cl) == {"count": 4, "sides": 8}
    assert set(damage["damage_types"]) >= {"fire", "radiant"}
    # Owner 2026-10-15 (f4bf1c9f): one initial resolution buys the payoff, so the Augment's blinded save joins the area save
    # instead of standing as a second roll; its repeat save is kept.
    assert len(action["parameters"]["typed"]["effects"]) == 1
    [blinded] = [effect for effect in save["on_fail"] if effect.get("type") == "condition" and effect.get("condition") == "blinded"]
    assert blinded["repeat_save"]


def test_a_forged_zone_is_laid_on_the_map_in_a_fight():
    from combat import zones
    from combat.gate2_engine import Gate2Engine
    from combat.gate2_runtime_content import AN
    from combat.gate2_runtime_models import ActionIntent

    owner = "actor:factory.forger"
    technique = {"technique_id": "tianxia.constructed.forged_technique.test-zone", "name": "Magma Court", "action_type": "action",
                 "base_form": {"form_id": "zone", "display_name": "Zone"}, "cp_cost": {"final": 3}, "limits": [],
                 "primary_sphere_effect": {"talent_id": "TAL_MAGMA_LAVA_SPIT"}, "augments": [], "drawbacks": []}
    bundle = compile_character({**BASE, "forged_techniques": [technique]}, actor_id=owner)
    engine = Gate2Engine(ROOT, match_seed="FORGED", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [owner, AN], "team_by_actor": {owner: "team:a", AN: "team:b"},
                                       "starting_positions": {owner: {"x": 3, "y": 6}, AN: {"x": 12, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(owner)
    engine.state.current_actor_id = owner
    engine._system_start_turn()
    foe = engine.state.actors[AN]
    before = foe.current_hp
    candidate = next(c for c in engine.legal_candidates() if c.display_name.startswith("Magma Court") and c.destination is not None
                     and (c.destination.x, c.destination.y) == (12, 6))
    engine.execute_intent(ActionIntent(intent_id="forge", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=owner, target_ids=candidate.target_ids,
                                       destination=candidate.destination))
    [zone] = zones.typed_zones(engine)
    assert zone.trigger_profile["name"] == "Magma Court" and zone.concentration_link and zone.trigger_profile["triggers"]
    assert foe.current_hp < before  # DC 30: the Lava Spit effect lands
