"""Regressions for the three blocking findings in the LIGHTS1F5 review."""
from combat import lighting, senses, zones
from combat.ext import radiance
from combat.footprints import native_actor_footprint
from combat.check_context import checking
from combat.typed_executor import check_mode
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, light, map_document
from tests.worker2_support import candidate, reload, settle

NIGHT = ambient_light("night")
POSITIONS = {OWNER: {"x": 2, "y": 2}, ALLY: {"x": 3, "y": 2}, FOE: {"x": 4, "y": 2}}


def test_large_target_is_visible_when_any_occupied_square_is_lit(tmp_path):
    document = map_document(20, 12, ambient=NIGHT, lights=[light(5, 2, bright_ft=0, dim_ft=0)])
    combat, table, mid = fight(tmp_path, document, senses=[], positions=POSITIONS)
    engine = reload(tmp_path, mid)
    viewer, target = engine.state.actors[OWNER], engine.state.actors[FOE]
    engine.actor_footprints[target.entity_id] = native_actor_footprint(target.entity_id, "Large")

    assert lighting.seen_level(engine, viewer, target.position) == lighting.DARK
    assert lighting.seen_level(engine, viewer, (5, 2)) == lighting.BRIGHT
    assert senses.perceives(engine, viewer, target)
    assert "DISADVANTAGE" not in zones.attack_modes(engine, viewer, target)


def test_radiance_piercing_target_keeps_ordinary_darkness_exemption(tmp_path):
    document = map_document(20, 14, ambient=NIGHT, lights=[light(8, 6)])
    combat, table, mid = fight(tmp_path, document, senses=[], talents=["DARK_BASE_DARKNESS"],
                               positions={OWNER: {"x": 6, "y": 6}, ALLY: {"x": 8, "y": 6},
                                          FOE: {"x": 2, "y": 2}})
    settle(table, mid, candidate(combat, mid, "Darkness", at=(8, 6)).candidate_id)
    engine = reload(tmp_path, mid)
    attacker, target = engine.state.actors[OWNER], engine.state.actors[ALLY]
    engine._apply_condition(target, radiance.PIERCING, "test:sun-white-judgment-spear",
                            attacker.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN")

    assert lighting.seen_level(engine, attacker, target.position) == lighting.DARK
    assert not lighting.creature_heavily_obscured(engine, attacker, target)
    assert not zones.hidden_from(engine, attacker, target)
    assert "DISADVANTAGE" not in zones.attack_modes(engine, attacker, target)

    # The exemption belongs to the marked creature and attacker, not to the square.
    assert lighting.heavily_obscured(engine, attacker, target.position)


def test_dim_light_does_not_penalize_an_explicit_hearing_only_check(tmp_path):
    document = map_document(20, 12, ambient=NIGHT)
    combat, table, mid = fight(tmp_path, document, senses=[], positions=POSITIONS)
    engine = reload(tmp_path, mid)
    actor, target = engine.state.actors[OWNER], engine.state.actors[FOE]

    with checking(engine, actor, {"senses": ["hearing"], "purpose": "contest"}):
        assert check_mode(actor, "WIS", "Perception", engine=engine, against_creature=target) == "NORMAL"
    with checking(engine, actor, {"senses": ["sight"], "purpose": "contest"}):
        assert check_mode(actor, "WIS", "Perception", engine=engine, against_creature=target) == "DISADVANTAGE"
