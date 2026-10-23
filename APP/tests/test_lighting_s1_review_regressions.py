"""Regressions for the three blocking findings in the LIGHTS1F5 review."""
from combat import lighting, senses, zones
from combat.ext import radiance
from combat.gate2_runtime_models import Position, ZoneState
from combat.footprints import native_actor_footprint
from combat.typed_executor import check_mode
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, light, map_document
from tests.worker2_support import reload

NIGHT = ambient_light("night")
POSITIONS = {OWNER: {"x": 2, "y": 2}, ALLY: {"x": 3, "y": 2}, FOE: {"x": 4, "y": 2}}


def test_large_target_is_visible_when_any_occupied_square_is_lit(tmp_path):
    document = map_document(20, 12, ambient=NIGHT, lights=[light(5, 2, bright_ft=1, dim_ft=1)])
    combat, table, mid = fight(tmp_path, document, senses=[], positions=POSITIONS)
    engine = reload(tmp_path, mid)
    viewer, target = engine.state.actors[OWNER], engine.state.actors[FOE]
    engine.actor_footprints[target.entity_id] = native_actor_footprint(target.entity_id, "Large")

    assert lighting.seen_level(engine, viewer, target.position) == lighting.DARK
    assert lighting.seen_level(engine, viewer, (5, 2)) == lighting.BRIGHT
    assert senses.perceives(engine, viewer, target)
    assert "DISADVANTAGE" not in zones.attack_modes(engine, viewer, target)


def test_radiance_piercing_target_keeps_ordinary_darkness_exemption(tmp_path, monkeypatch):
    document = map_document(20, 14, ambient=ambient_light("day"))
    combat, table, mid = fight(tmp_path, document, senses=[],
                               positions={OWNER: {"x": 2, "y": 2}, ALLY: {"x": 5, "y": 2},
                                          FOE: {"x": 6, "y": 2}})
    engine = reload(tmp_path, mid)
    attacker, target, control = (engine.state.actors[actor_id] for actor_id in (OWNER, ALLY, FOE))
    zone = ZoneState(zone_id="test:ordinary-darkness", source_definition_id="test:ordinary-darkness",
                     owner_id=FOE, center=Position(x=5, y=2), radius_cells=3,
                     affected_cells=tuple(Position(x=x, y=y) for y in range(1, 5) for x in range(4, 8)),
                     concentration_link=False, created_round=0,
                     trigger_profile={"name": "Darkness", "visual": {"darkness": True, "ordinary": True,
                                                                          "magical": False}})
    monkeypatch.setattr(zones, "heavy_zones", lambda _engine: (zone,))
    monkeypatch.setattr(zones, "_heavy", lambda _engine: [zone])
    engine._apply_condition(target, radiance.PIERCING, "test:sun-white-judgment-spear",
                            attacker.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN")

    assert lighting.seen_level(engine, attacker, target.position) == lighting.DARK
    assert not lighting.creature_heavily_obscured(engine, attacker, target)
    assert not zones.hidden_from(engine, attacker, target)
    assert "DISADVANTAGE" not in zones.attack_modes(engine, attacker, target)

    # The exemption belongs to the marked creature and attacker, not to the square.
    assert lighting.heavily_obscured(engine, attacker, target.position)
    assert lighting.creature_heavily_obscured(engine, attacker, control)
    assert "DISADVANTAGE" in zones.attack_modes(engine, attacker, control)


def test_dim_light_does_not_penalize_an_explicit_hearing_only_check(tmp_path):
    document = map_document(20, 12, ambient=NIGHT, lights=[light(5, 2, bright_ft=5, dim_ft=20)])
    combat, table, mid = fight(tmp_path, document, senses=[], positions=POSITIONS)
    engine = reload(tmp_path, mid)
    actor, target = engine.state.actors[OWNER], engine.state.actors[FOE]

    assert check_mode(actor, "WIS", "Perception", engine=engine, against_creature=target,
                      metadata={"senses": ["hearing"], "purpose": "contest"}) == "NORMAL"
    assert check_mode(actor, "WIS", "Perception", engine=engine, against_creature=target,
                      metadata={"senses": ["sight"], "purpose": "contest"}) == "DISADVANTAGE"
