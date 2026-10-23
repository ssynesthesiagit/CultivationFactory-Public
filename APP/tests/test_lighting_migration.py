"""Printed ability light inventory and S3 source-shape regression.

Every assertion below runs on a fight that was committed through the table and cold-reloaded, so it reads the answer
the table actually resolves -- not a hand-built field (lighting spec §8.2, §10 S3).
"""
import json
from pathlib import Path
from types import SimpleNamespace

from combat import lighting
from combat.ext.radiance import HEAVENLY, _bright
from tests.lighting_support import ambient_light, fight as lighting_fight, map_document, payload
from tests.worker2_support import ALLY, OWNER, candidate, fixture, reload, settle, turn

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
    }


def test_heavenly_radiance_printed_bright_radius_is_120():
    rows = {row["mechanic"]: row for row in inventory()}
    assert rows["tianxia.talent.radiance.heavenly_radiance"]["bright_ft"] == 120
    assert rows["tianxia.talent.radiance.heavenly_radiance"]["dim_ft"] == 240


def test_wick_body_light_has_no_dim_ring():
    source = (ROOT / "combat/ext/wax_reactions.py").read_text()
    assert '"bright_ft": LIGHT_RADIUS_FT, "dim_ft": LIGHT_RADIUS_FT' in source


def test_heavenly_suppression_requires_owners_bright_radius(monkeypatch):
    from combat.lighting import LightSource

    monkeypatch.setattr(lighting, "_square", lambda engine: 5)
    monkeypatch.setattr(lighting, "_Rays", lambda engine: SimpleNamespace(
        disc=lambda sx, sy, radius: SimpleNamespace(
            clear=lambda x, y: True, reach=lambda ux, uy, limit: limit)))
    target = SimpleNamespace(active=True, entity_id="target", conditions={}, modifiers={}, concentration=None)
    ownerless = SimpleNamespace(active=True, actors={}, state=SimpleNamespace(actors={}),
                                grid=SimpleNamespace(width=40, height=40))
    ownerless._actor_cells = lambda actor: [(30, 30)]
    assert _bright(ownerless, target) is False

    owner = SimpleNamespace(active=True, entity_id="sun", conditions={}, modifiers={}, concentration=None)
    owner.conditions = {"radiance": SimpleNamespace(source_definition_id=HEAVENLY, source_actor_id="sun")}
    source = LightSource(f"printed:{HEAVENLY}:sun", "Heavenly Radiance", frozenset({(0, 0)}), 120, 240,
                         following="sun")
    monkeypatch.setattr(lighting, "sources", lambda engine: (source,))
    outside = SimpleNamespace(active=True, actors={"sun": owner}, state=SimpleNamespace(actors={"sun": owner}),
                              grid=SimpleNamespace(width=40, height=40))
    outside._actor_cells = lambda actor: [(0, 0)] if actor is owner else [(30, 30)]
    assert _bright(outside, target) is False

    inside = SimpleNamespace(active=True, actors={"sun": owner}, state=SimpleNamespace(actors={"sun": owner}),
                             grid=SimpleNamespace(width=40, height=40))
    inside._actor_cells = lambda actor: [(0, 0)] if actor is owner else [(24, 0)]
    assert _bright(inside, target) is True


def test_radiant_overpressure_lights_the_marked_creature_while_the_exposure_stands():
    """"The marked creature emits bright light in a 10-foot radius and dim light for an additional 10 feet until the
    start of your next turn": the exposure that pays for it carries the printed light on its own clock."""
    from tests.test_riders_lane2 import FOE as MARKED, ME as MARKER, OVERKINDLED, YANG, _duel, _mark

    engine = _duel(["TAL_YANG_RADIANT_OVERPRESSURE"], sphere=YANG)
    engine.state.actors[MARKER].reaction_available = False
    _mark(engine, OVERKINDLED, MARKED)
    assert [source for source in lighting.sources(engine) if source.following == MARKED] == []   # the mark alone sheds nothing
    engine._apply_condition(engine.state.actors[MARKED], "condition:typed.hidden", "test:hidden", MARKED, expires_on="UNTIL_REMOVED")
    shed = {source.following: (source.bright_ft, source.dim_ft) for source in lighting.sources(engine)}
    assert shed == {MARKED: (10, 20)}


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
