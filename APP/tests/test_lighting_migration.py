"""Printed ability light inventory and S3 source-shape regression.

Every assertion below runs on a fight that was committed through the table and cold-reloaded, so it reads the answer
the table actually resolves -- not a hand-built field (lighting spec §8.2, §10 S3).
"""
import json
from pathlib import Path

import pytest

from combat import lighting, senses
from combat.typed_executor import bears_mark
from tests.h1_support import sheet
from combat.ext.radiance import HEAVENLY
from tests.lighting_support import ambient_light, fight as lighting_fight, map_arena, map_document, payload, torch
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle, turn

ROOT = Path(__file__).resolve().parents[1]


def inventory():
    return json.loads((ROOT / "combat/rules/light_sources.json").read_text())["sources"]


def test_light_source_inventory_matches_printed_authority_and_has_valid_radii():
    rows = inventory()
    # Public CI redacts record prose, so this contract uses stable exported mechanic
    # identifiers and the structured radii rather than asserting private text fragments.
    authority = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())
    assert len(rows) == 17
    assert len({row["mechanic"] for row in rows}) == len(rows)
    for row in rows:
        assert row["mechanic"] in authority
        assert type(row["bright_ft"]) is int and type(row["dim_ft"]) is int
        assert 0 <= row["bright_ft"] <= row["dim_ft"]
        assert row["follows"] in {"self", "zone", "target", "targets", "summon"}
        assert row["evidence"].strip()          # each row names the printed clause it comes from
        assert type(row["magical"]) is bool
    assert {row["mechanic"]: (row["bright_ft"], row["dim_ft"]) for row in rows}[
        "tianxia.talent.radiance.heavenly_radiance"] == (120, 240)


def test_every_state_carried_light_names_the_state_its_ability_files():
    """Only lights without their own producer name a state for the generic scanner."""
    rows = {row["mechanic"]: row for row in inventory()}
    carriers = {mechanic: row.get("state") for mechanic, row in rows.items() if row.get("state")}
    assert carriers == {
        "tianxia.talent.fire.blazing_armor": "modifier",
        "tianxia.tradition.spirit.halo_eater.feature.crown_of_borrowed_light": "condition:typed.crown_of_borrowed_light",
    }


def test_heavenly_radiance_printed_bright_radius_is_120():
    rows = {row["mechanic"]: row for row in inventory()}
    assert rows["tianxia.talent.radiance.heavenly_radiance"]["bright_ft"] == 120
    assert rows["tianxia.talent.radiance.heavenly_radiance"]["dim_ft"] == 240


def test_wick_body_light_has_no_dim_ring():
    source = (ROOT / "combat/ext/wax_reactions.py").read_text()
    assert '"bright_ft": LIGHT_RADIUS_FT, "dim_ft": LIGHT_RADIUS_FT' in source


HEAVENLY_TALENT = "tianxia.talent.radiance.heavenly_radiance"


@pytest.mark.parametrize("foe_x,foe_y,wall_x,other_light,active,lit", [
    (22, 2, None, False, True, True),    # inside the owner's 120-foot bright radius
    (28, 2, None, False, True, False),   # only its dim ring reaches the creature
    (22, 2, 12, False, True, False),     # opaque wall stops this owner's light
    (28, 2, None, True, True, False),    # another emitter's Bright Light cannot suppress Invisible
    (22, 2, None, True, False, False),   # no active owner: unrelated Bright Light is insufficient
    (26, 26, None, False, True, True),   # diagonal edge of the painted bright footprint
    (27, 27, None, False, True, False),  # just outside that footprint
])
def test_heavenly_radiance_bright_light_is_the_printed_radius_and_stops_at_walls(
        tmp_path, foe_x, foe_y, wall_x, other_light, active, lit):
    """Heavenly Radiance sheds Bright Light in a 120-foot radius. Committed through the table, cold-reloaded, and read
    back from the light sources the table resolves: no monkeypatched geometry."""
    walls = [{"shape": "line", "points": [[wall_x, 0], [wall_x, 5]], "blocks": "sight"}] if wall_x is not None else []
    document = map_document(32, 30, ambient=ambient_light("night"), walls=walls,
                            lights=[torch(foe_x, foe_y)] if other_light else [])
    combat, table, mid = fixture(tmp_path, [HEAVENLY_TALENT],
                                 foe_sheet=sheet(["tianxia.subpath.qi.ninpo_adept.feature.vanishing_technique"], cl=15),
                                 battlefield=map_arena(tmp_path, document),
                                 positions={OWNER: {"x": 2, "y": 2}, ALLY: {"x": 2, "y": 3},
                                            FOE: {"x": foe_x, "y": foe_y}},
                                 seed=f"LIGHT-S3-HEAVENLY-{foe_x}-{foe_y}-{wall_x}-{other_light}-{active}")
    if active:
        settle(table, mid, candidate(combat, mid, "Heavenly Radiance").candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, "Vanishing Technique").candidate_id)
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    assert foe.position.x == foe_x
    owned = [s for s in lighting.sources(engine) if s.following == OWNER]
    assert [(s.following, s.bright_ft, s.dim_ft) for s in owned] == ([(OWNER, 120, 240)] if active else [])
    assert (lighting.base(engine, foe.position.x, foe.position.y) == lighting.BRIGHT) is (lit or other_light)
    invisible = {iid for iid, c in foe.conditions.items() if c.condition_id.endswith(".invisible")}
    assert invisible, "Vanishing Technique must really be active in the cold-reloaded fight"
    masked = senses.masked_conditions(engine, engine.state.actors[OWNER], foe).get(FOE, set())
    assert (invisible <= masked) is lit


def test_banked_ember_create_light_carries_the_printed_bright_and_dim_radii(tmp_path):
    """The chosen flare prints Bright 20 and Dim *another* 20, so its zone is bright 20 / dim 40 (a max, not a sum)."""
    combat, table, mid = fixture(tmp_path, ["tianxia.talent.fire.banked_ember"], seed="LIGHT-S3-BANKED")
    turn(table, mid, OWNER)
    flare = next(row for row in combat._load_session(mid).engine.legal_candidates()
                 if row.display_name.startswith("Banked Ember: Create Light"))
    assert flare.target_ids == ()
    settle(table, mid, flare.candidate_id)
    engine = reload(tmp_path, mid)
    zone = next(source for source in lighting.sources(engine) if source.entity_id.startswith("zone:"))
    assert (zone.bright_ft, zone.dim_ft) == (20, 40)


def test_halo_target_sheds_the_printed_bright_light_and_its_caster_does_not(tmp_path):
    """Halo of the Merciful Sovereign: "the target sheds Bright Light in a 10-foot radius" -- the state is on the target."""
    combat, table, mid = fixture(tmp_path, ["tianxia.talent.radiance.halo_of_the_merciful_sovereign"], seed="LIGHT-S3-HALO")
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Halo of the Merciful Sovereign", target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    shed = [(source.following, source.bright_ft, source.dim_ft) for source in lighting.sources(engine)]
    assert shed == [(ALLY, 10, 10)]


def test_blazing_armor_bearer_sheds_the_printed_bright_and_dim_light(tmp_path):
    """Blazing Armor: "the bearer sheds Bright Light in a 10-foot radius and Dim Light for another 10 feet"."""
    combat, table, mid = fixture(tmp_path, ["tianxia.talent.fire.blazing_armor"], seed="LIGHT-S3-BLAZING")
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Blazing Armor", target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    shed = {source.following: (source.bright_ft, source.dim_ft) for source in lighting.sources(engine)}
    assert shed == {ALLY: (10, 20)}


def test_radiant_overpressure_exposure_carries_its_printed_light_on_the_marked_creature(tmp_path):
    """"The marked creature emits bright light in a 10-foot radius and dim light for an additional 10 feet": spending the
    Overkindled Mark with Radiant Overpressure exposes the marked creature and files its curated light on the creature,
    committed through the table and read back after a cold reload."""
    foe_sheet = sheet([])
    foe_sheet["ability_scores_and_statistics"]["armor_class"]["base_value"] = 1
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_RADIANT_OVERPRESSURE"],
                                 seed="WORKER2", owner_dc=100, foe_sheet=foe_sheet,
                                 foe_position={"x": 3, "y": 3})
    settle(table, mid, candidate(combat, mid, "Rising Thread", target=FOE).candidate_id)
    marked_engine = reload(tmp_path, mid)
    marked = marked_engine.state.actors[FOE]
    rolls = [(e.payload or {}) for e in marked_engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == OWNER]
    assert bears_mark(marked, OWNER, "Overkindled Mark"), (rolls, [(c.condition_id, c.data) for c in marked.conditions.values()])
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    before = engine.state.actors[OWNER].resources["resource:core.qi"]
    move = next(c for c in engine.legal_candidates() if c.destination and c.destination.x == 3
                and c.destination.y == 1 and c.display_name.startswith("Move"))
    prompts = settle(table, mid, move.candidate_id,
                     {"choice:paid_option.TAL_YANG_RADIANT_OVERPRESSURE": "0"})
    payment = next(p for p in prompts if p["context"]["reaction_source_id"] ==
                   "choice:paid_option.TAL_YANG_RADIANT_OVERPRESSURE")
    assert payment["choice"]["options"][0]["id"] == "0"
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == before - 2
    assert not bears_mark(engine.state.actors[FOE], OWNER, "Overkindled Mark")
    foe = engine.state.actors[FOE]
    light = [c for c in foe.conditions.values() if c.condition_id == lighting.LIGHT]
    assert light, "the marked creature carries no printed light after Radiant Overpressure"
    assert (light[0].data["bright_ft"], light[0].data["dim_ft"]) == (10, 20)
    assert light[0].data["source_id"] == "TAL_YANG_RADIANT_OVERPRESSURE"
    assert any(c.condition_id.startswith("condition:typed.exposed") and c.data["benefits"] == "invisible"
               for c in foe.conditions.values())


def test_candle_procession_separated_origins_survive_saved_table(tmp_path):
    """Two chosen candles illuminate independently, not the generic area footprint."""
    document = map_document(20, 12, ambient=ambient_light("night"))
    combat, table, mid = lighting_fight(
        tmp_path, document, talents=["TAL_WAX_CANDLE_PROCESSION"],
        senses=[{"sense": "darkvision", "range_ft": 60}],
        positions={OWNER: {"x": 4, "y": 4}, ALLY: {"x": 4, "y": 5}, FOE: {"x": 14, "y": 8}},
        seed="LIGHT-S3-CANDLE-ORIGINS")
    settle(table, mid, candidate(combat, mid, "Candle Procession").candidate_id,
           {"choice:needle.candle_procession": ["cell:2,2", "cell:10,2"]})
    engine = reload(tmp_path, mid)
    lights = [source for source in lighting.sources(engine) if source.entity_id.startswith("candle-procession:")]
    assert len(lights) == 1
    assert lights[0].cells == {(2, 2), (10, 2)}
    assert (lights[0].bright_ft, lights[0].dim_ft) == (0, 10)
    assert lighting.base(engine, 4, 2) == lighting.DIM
    assert lighting.base(engine, 8, 2) == lighting.DIM
    assert lighting.base(engine, 6, 2) == lighting.DARK
    assert lighting.base(engine, 13, 2) == lighting.DARK

    from combat.ext.area_suppression import suppress
    from combat.gate2_runtime_models import Position

    zone = next(zone for zone in engine.state.zones.values()
                if zone.source_definition_id.endswith("TAL_WAX_CANDLE_PROCESSION"))
    suppress(engine, engine.state.actors[OWNER], zone, until="start:test", source="test",
             cells=[Position(x=2, y=2)])
    lights = [source for source in lighting.sources(engine) if source.entity_id.startswith("candle-procession:")]
    assert len(lights) == 1
    assert lights[0].cells == {(10, 2)}
    assert lighting.base(engine, 4, 2) == lighting.DARK
    assert lighting.base(engine, 12, 2) == lighting.DIM
