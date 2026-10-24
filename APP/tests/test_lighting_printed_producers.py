"""Printed ability lights that reach the field through their own producer (lighting spec §8.2).

The review of feat/lighting-s3 found six §8.2 rows with no emitter: two are carried by the zone the compiler builds
from the reviewed typed data, and four print the light on a creature at a trigger. Each test below drives the real
ability and reads the light the table resolves, so the row is proven to reach the field, not merely listed.
"""
import pytest

from combat import lighting, zones
from combat.gate2_runtime_models import ActionIntent
from tests.worker2_support import OWNER, candidate, fixture, reload, settle, turn


def _shed(engine):
    return {(source.following, source.bright_ft, source.dim_ft, source.magical) for source in lighting.sources(engine)}


def _zone_light(engine, source):
    """The zone profile's light entry: the curated table's numbers carry no ``provenance`` guess."""
    zone = next(zone for zone in zones.typed_zones(engine) if f"zone:{zone.zone_id}" == source.entity_id)
    return zone.trigger_profile["visual"]["light"]


def test_completing_flame_mantle_zone_carries_the_printed_bright_and_dim_radii(tmp_path):
    """"For the duration ... you emit bright light in a 10-foot radius and dim light for an additional 10 feet":
    the reviewed zone effect compiles and carries the curated radii (bright 10 / dim 20) after a table reload."""
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_COMPLETING_FLAME_MANTLE"], seed="LIGHT-S3-MANTLE")
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Completing Flame Mantle").candidate_id)
    engine = reload(tmp_path, mid)
    zone = next(source for source in lighting.sources(engine) if source.entity_id.startswith("zone:"))
    assert (zone.bright_ft, zone.dim_ft) == (10, 20)
    assert "provenance" not in _zone_light(engine, zone)          # the curated row, never the prose guess


def test_sovereign_yang_incarnation_emit_light_option_lights_the_printed_radius(tmp_path):
    """"... emit bright light in a 20-foot radius until the start of your next turn": the chosen option's zone is
    bright 20 with no separate dim ring, and it survives the table commit."""
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_SOVEREIGN_YANG_INCARNATION"], seed="LIGHT-S3-SOVEREIGN")
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Sovereign Yang Incarnation: Emit Bright Light").candidate_id)
    engine = reload(tmp_path, mid)
    zone = next(source for source in lighting.sources(engine) if source.entity_id.startswith("zone:"))
    assert (zone.bright_ft, zone.dim_ft) == (20, 20)
    assert "provenance" not in _zone_light(engine, zone)          # the curated row, never the prose guess


def test_guiding_candle_lights_its_printed_radii(tmp_path):
    """"The candle burns for 1 hour, sheds bright light in a 10-foot radius and dim light for another 10 feet":
    using the talent files the printed light on its holder, and the table reload keeps it."""
    combat, table, mid = fixture(tmp_path, ["TAL_WAX_GUIDING_CANDLE"], seed="LIGHT-S3-GUIDING")
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Guiding Candle").candidate_id)
    engine = reload(tmp_path, mid)
    assert _shed(engine) == {(OWNER, 10, 20, False)}


def test_radiant_fist_dim_light_option_lights_the_target():
    """"Cause the target to shed Dim Light in a 10-foot radius until the start of your next turn": the fourth
    reviewed option (no longer a GM rider) lights the target it hit."""
    from tests import test_riders_c7 as c7

    engine = c7.fight(c7.bundle([c7.GOLD + "radiant_fist"]))
    foe = engine.state.actors[c7.foe_id(engine)]
    foe.armor_class = -50
    c7.answers(engine, {"path_hit." + c7.GOLD + "radiant_fist": ["Dim Light"]})
    c7.use(engine, c7.unarmed(engine), target=foe.entity_id)
    assert _shed(engine) == {(foe.entity_id, 0, 10, True)}
    held = next(condition for condition in foe.conditions.values() if condition.condition_id == lighting.LIGHT)
    assert held.expires_on == "START_OF_SOURCE_NEXT_TURN"


def test_summer_pressure_lights_the_owner_when_a_kindled_mark_is_spent_on_itself():
    """"When you spend a Kindled Mark on yourself, you may choose to emit bright light in a 10-foot radius and dim
    light for an additional 10 feet until the start of your next turn": spending the mark asks, then lights."""
    from tests import test_riders_lane2 as yang

    engine = yang._duel(["TAL_YANG_SUMMER_PRESSURE"], sphere=yang.YANG)
    yang._mark(engine, yang.KINDLED, yang.ME)
    yang._complete_force_hit(engine)
    assert not yang._bears(engine, yang.ME, yang.KINDLED)          # Complete Force really spent the mark
    assert _shed(engine) == {(yang.ME, 10, 20, True)}              # ... and the printed light is on its holder
    held = next(condition for condition in engine.state.actors[yang.ME].conditions.values()
                if condition.condition_id == lighting.LIGHT)
    assert held.expires_on == "START_OF_SELF_NEXT_TURN"


def test_the_action_cannot_stay_small_overcomplete_light_lights_the_creature_that_acted():
    """An unwilling marked creature that fails its Constitution save gets the printed overcomplete light result:
    "one created ... effect from the action emits bright light in a 20-foot radius". The engine models no created-effect
    object, so the light rides the creature whose completed action was overcompleted."""
    from tests import test_riders_lane2 as yang

    engine = yang._duel(["TAL_YANG_THE_ACTION_CANNOT_STAY_SMALL"], sphere=yang.YANG, dc=50)
    if not any(row.get("feature_id") == "TAL_YANG_THE_ACTION_CANNOT_STAY_SMALL"
               for row in (getattr(engine, "typed_reaction_rows", {}) or {}).get(yang.ME, ())):
        pytest.skip("the public snapshot omits authority/typed_mechanics/trigger_readings.jsonl, so this "
                    "generically compiled reaction does not exist there; the local run exercises it")
    yang._mark(engine, yang.KINDLED, yang.FOE)
    yang._foe_turn(engine)
    dodge = next(candidate for candidate in engine.legal_candidates()
                 if candidate.actor_id == yang.FOE and candidate.display_name == "Dodge")
    engine.execute_intent(ActionIntent(intent_id="action-small-dodge", decision_id=dodge.decision_id,
                                       candidate_id=dodge.candidate_id, state_version=dodge.state_version,
                                       actor_id=yang.FOE, target_ids=dodge.target_ids, destination=dodge.destination))
    assert any(event.event_type == "SAVE_ROLLED" and event.source_definition_id == "TAL_YANG_THE_ACTION_CANNOT_STAY_SMALL"
               and (event.payload or {}).get("success") is False for event in engine.events)
    assert _shed(engine) == {(yang.FOE, 20, 20, True)}
