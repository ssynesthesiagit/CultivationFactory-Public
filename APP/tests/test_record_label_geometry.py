"""Public rename regressions through real candidates, zones and table persistence."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from combat import factory_compiler, zones
from combat.ext import tabik_dark
from factory_authoring.record_links import project_authority
from tests import hunt36_support as support
from tests.lighting_darkness_support import darkness_rules

DARK = "DARK_BASE_DARKNESS"
ROLLING = "TAL_DARK_ROLLING_BLACKOUT"
SMOKE = "SMOKE_BASE_SMOKE_VEIL"
SMOKE_WALL = "TAL_SMOKE_WALL_OF_SMOKE"


@pytest.mark.parametrize("ai", [False, True])
def test_renamed_darkness_keeps_rolling_blackout_candidates_and_moves_after_reload(
        tmp_path, monkeypatch, darkness_rules, ai):
    authority = json.loads(factory_compiler.TYPED_AUTHORITY.read_text())
    renamed = project_authority(authority, {}, {DARK: "Evening Veil"})
    original = support.compile_character
    monkeypatch.setattr(support, "compile_character",
                        lambda *args, **kwargs: original(*args, typed_authority=renamed, **kwargs))
    combat, table, mid = support.fight(tmp_path, [DARK, ROLLING])
    support.turn(combat, table, mid)
    engine = support.reload(combat, mid)
    cast = next(c for c in engine.legal_candidates()
                if c.destination and (c.destination.x, c.destination.y) == (3, 6)
                and engine.action_catalog[c.source_definition_id].display_name == "Evening Veil")
    support.send(combat, table, mid, cast.candidate_id)
    engine = support.reload(combat, mid)
    move = next(c for c in engine.legal_candidates()
                if c.destination and (c.destination.x, c.destination.y) == (4, 6)
                and engine.action_catalog[c.source_definition_id].parameters.get("rolling_blackout")
                and engine.action_catalog[c.source_definition_id].economy.value == "BONUS_ACTION")
    support.send(combat, table, mid, move.candidate_id, ai=ai)
    engine = support.reload(combat, mid)
    [zone] = [z for z in zones.typed_zones(engine) if z.owner_id == support.LEFT]
    assert zone.trigger_profile["name"] == "Evening Veil"
    assert zone.trigger_profile["source_profile"]["mechanic_id"] == DARK
    assert (zone.center.x, zone.center.y) == (4, 6)


def test_movable_areas_cannot_be_impersonated_by_a_display_label(monkeypatch):
    actor = SimpleNamespace(entity_id="owner")
    def area(rid, name):
        return SimpleNamespace(owner_id="owner", duration_rounds=10, concentration_link=None,
                               trigger_profile={"name": name, "source_profile": {"mechanic_id": rid}})
    own = area(DARK, "Evening Veil")
    impostor = area("OTHER_AREA", "Darkness")
    monkeypatch.setattr(zones, "typed_zones", lambda _: [own, impostor])
    assert tabik_dark.movable(None, actor) == [own]
    own.trigger_profile["anchor_id"] = "creature"
    assert tabik_dark.movable(None, actor) == []


def test_renamed_wall_shaping_talent_keeps_candidates_geometry_and_table_reload(tmp_path, monkeypatch):
    authority = json.loads(factory_compiler.TYPED_AUTHORITY.read_text())
    sheet = support.sheet([SMOKE, SMOKE_WALL])
    baseline = factory_compiler.compile_character(sheet, actor_id=support.LEFT, typed_authority=authority)
    original_wall = next(a for a in baseline["action_catalog"]
                         if a["display_name"] == "Smoke Veil + Wall of Smoke")
    renamed = project_authority(authority, {}, {SMOKE_WALL: "Drifting Screen"})
    original = support.compile_character
    monkeypatch.setattr(support, "compile_character",
                        lambda *args, **kwargs: original(*args, typed_authority=renamed, **kwargs))
    combat, table, mid = support.fight(tmp_path, [SMOKE, SMOKE_WALL])
    support.turn(combat, table, mid)
    engine = support.reload(combat, mid)
    wall = next(a for a in engine.action_catalog.values()
                if a.display_name == "Smoke Veil + Drifting Screen")
    assert wall.parameters["typed"]["zone_spec"] == original_wall["parameters"]["typed"]["zone_spec"]
    cast = next(c for c in engine.legal_candidates()
                if c.source_definition_id == wall.source_definition_id and c.destination
                and (c.destination.x, c.destination.y) == (6, 6))
    support.send(combat, table, mid, cast.candidate_id)
    engine = support.reload(combat, mid)
    [zone] = [z for z in zones.typed_zones(engine) if z.owner_id == support.LEFT]
    assert zone.trigger_profile["wall"] == original_wall["parameters"]["typed"]["zone_spec"]["wall"]
    assert len(zone.affected_cells) > 1
    assert zone.trigger_profile["visual"]["material"] == "smoke"


@pytest.mark.parametrize("rid", ["TAL_MAGMA_LAVA_WALL", "TAL_DARK_WALL_OF_DARKNESS", "TAL_WAX_WAX_RAMPART"])
def test_direct_and_modifier_wall_geometry_survive_duplicate_display_names(rid, darkness_rules):
    authority = json.loads(factory_compiler.TYPED_AUTHORITY.read_text())
    parents = {"TAL_MAGMA_LAVA_WALL": [], "TAL_DARK_WALL_OF_DARKNESS": [DARK],
               "TAL_WAX_WAX_RAMPART": ["TAL_WAX_MOLD_WAX"]}
    sheet = support.sheet([rid, *parents[rid]])
    before = factory_compiler.compile_character(sheet, actor_id=support.LEFT, typed_authority=authority)
    renamed = deepcopy(authority)
    renamed["mechanics"][rid]["name"] = "Unrelated display label"
    # A different record may use the former name without borrowing its geometry.
    renamed["mechanics"]["SMOKE_BASE_SMOKE_VEIL"]["name"] = authority["mechanics"][rid]["name"]
    if rid == "TAL_WAX_WAX_RAMPART":
        for option in renamed["mechanics"][rid]["modifier"]["options"]:
            option["label"] = "Same visible choice"
    after = factory_compiler.compile_character(sheet, actor_id=support.LEFT, typed_authority=renamed)
    def wall_specs(bundle):
        return {a["source_definition_id"]: a["parameters"]["typed"]["zone_spec"]
                for a in bundle["action_catalog"] if (a["parameters"].get("typed") or {}).get("zone_spec", {}).get("wall")}
    expected = wall_specs(before)
    assert expected, "the real compiler must exercise wall geometry"
    assert wall_specs(after) == expected
    assert {a["source_definition_id"] for a in before["action_catalog"] if a["parameters"].get("wall_plan")} == {
        a["source_definition_id"] for a in after["action_catalog"] if a["parameters"].get("wall_plan")}
