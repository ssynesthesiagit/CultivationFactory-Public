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
from tests.lighting_support import ambient_light, map_arena, map_document, payload, torch
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
    """The four rows whose light rides a lasting condition/modifier say which one; nothing else is guessed."""
    rows = {row["mechanic"]: row for row in inventory()}
    carriers = {mechanic: row.get("state") for mechanic, row in rows.items() if row.get("state")}
    assert carriers == {
        "tianxia.talent.radiance.heavenly_radiance": "condition:typed.radiance_heavenly_flight",
        "tianxia.talent.radiance.solar_radiance_form": "condition:typed.radiance_state",
        "tianxia.talent.radiance.halo_of_the_merciful_sovereign": "condition:typed.radiance_state",
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


@pytest.mark.parametrize("foe_x,wall_x,other_light,active,lit", [
    (22, None, False, True, True),    # inside the owner's 120-foot bright radius
    (28, None, False, True, False),   # only its dim ring reaches the creature
    (22, 12, False, True, False),     # opaque wall stops this owner's light
    (28, None, True, True, False),    # another emitter's Bright Light cannot suppress Invisible
    (22, None, True, False, False),   # no active owner: unrelated Bright Light is insufficient
])
def test_heavenly_radiance_bright_light_is_the_printed_radius_and_stops_at_walls(
        tmp_path, foe_x, wall_x, other_light, active, lit):
    """Heavenly Radiance sheds Bright Light in a 120-foot radius. Committed through the table, cold-reloaded, and read
    back from the light sources the table resolves: no monkeypatched geometry."""
    walls = [{"shape": "line", "points": [[wall_x, 0], [wall_x, 5]], "blocks": "sight"}] if wall_x is not None else []
    document = map_document(32, 6, ambient=ambient_light("night"), walls=walls,
                            lights=[torch(foe_x, 2)] if other_light else [])
    combat, table, mid = fixture(tmp_path, [HEAVENLY_TALENT],
                                 foe_sheet=sheet(["tianxia.subpath.qi.ninpo_adept.feature.vanishing_technique"], cl=15),
                                 battlefield=map_arena(tmp_path, document),
                                 positions={OWNER: {"x": 2, "y": 2}, ALLY: {"x": 2, "y": 3},
                                            FOE: {"x": foe_x, "y": 2}},
                                 seed=f"LIGHT-S3-HEAVENLY-{foe_x}-{wall_x}-{other_light}-{active}")
    if active:
        settle(table, mid, candidate(combat, mid, "Heavenly Radiance").candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, "Vanishing Technique").candidate_id)
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    assert foe.position.x == foe_x
    owned = [s for s in lighting.sources(engine) if s.entity_id == f"printed:{HEAVENLY}:{OWNER}"]
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
    shed = {source.following: (source.bright_ft, source.dim_ft) for source in lighting.sources(engine)}
    assert shed == {ALLY: (10, 10)}


def test_blazing_armor_bearer_sheds_the_printed_bright_and_dim_light(tmp_path):
    """Blazing Armor: "the bearer sheds Bright Light in a 10-foot radius and Dim Light for another 10 feet"."""
    combat, table, mid = fixture(tmp_path, ["tianxia.talent.fire.blazing_armor"], seed="LIGHT-S3-BLAZING")
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Blazing Armor", target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    shed = {source.following: (source.bright_ft, source.dim_ft) for source in lighting.sources(engine)}
    assert shed == {ALLY: (10, 20)}


def test_candle_procession_lights_the_printed_dim_radius_on_a_night_map(tmp_path):
    """Candle Procession: "They shed dim light in a 10-foot radius" -- every square its candles cover, no dim ring further."""
    combat, table, mid = lighting_fight(tmp_path, map_document(14, 12, ambient=ambient_light("night")),
                                        talents=["TAL_WAX_CANDLE_PROCESSION"], senses=[], seed="LIGHT-S3-CANDLES")
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Candle Procession").candidate_id)
    engine = reload(tmp_path, mid)
    candles = next(source for source in lighting.sources(engine) if source.entity_id.startswith("zone:"))
    assert (candles.bright_ft, candles.dim_ft) == (0, 10)
    assert len(candles.cells) > 1                                    # a multi-square source, not one creature
    covered = sorted(candles.cells)[0]
    assert lighting.base(engine, *covered) == lighting.DIM
    assert lighting.base(engine, 12, 10) == lighting.DARK             # far outside the candles
    owner = engine.state.actors[OWNER]
    assert lighting.seen_level(engine, owner, lighting._position_of(covered)) == lighting.DIM
    assert payload(table, mid, OWNER)["ambient"]["level"] == lighting.DARK


def test_radiant_overpressure_exposure_carries_its_printed_light_on_the_marked_creature(tmp_path):
    """"The marked creature emits bright light in a 10-foot radius and dim light for an additional 10 feet": spending the
    Overkindled Mark with Radiant Overpressure exposes the marked creature and files its curated light on the creature,
    committed through the table and read back after a cold reload."""
    foe_sheet = sheet([])
    foe_sheet["ability_scores_and_statistics"]["armor_class"]["base_value"] = 1
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_RADIANT_OVERPRESSURE"],
                                 seed="LIGHT-S3-OVERPRESSURE", owner_dc=100, foe_sheet=foe_sheet,
                                 foe_position={"x": 3, "y": 5})
    settle(table, mid, candidate(combat, mid, "Rising Thread", target=FOE).candidate_id)
    marked = reload(tmp_path, mid).state.actors[FOE]
    assert bears_mark(marked, OWNER, "Overkindled Mark"), [(c.condition_id, c.data) for c in marked.conditions.values()]
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    before = engine.state.actors[OWNER].resources["resource:core.qi"]
    move = next(c for c in engine.legal_candidates() if c.destination and c.destination.x == 3
                and c.destination.y == 3 and c.display_name.startswith("Move"))
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
