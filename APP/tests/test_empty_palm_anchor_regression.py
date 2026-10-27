"""Regression for an Unravel condition that is the sole anchor of an area."""
from combat.ext import area_suppression
from combat.ext import void_touched_empty_palm as palm
from combat.gate2_runtime_models import ZoneState
from tests import worker2_support as W
from tests.test_mgr_empty_palm import acquired, _context, _fight, _hex, _turn, palm_action


def test_suppression_cascades_to_sole_anchor_area_and_restores(acquired, tmp_path):
    service, project = acquired
    _, _, mid = _fight(tmp_path, service, project, name="anchor")
    engine = W.reload(tmp_path / "anchor", mid)
    owner, foe = engine.state.actors[W.OWNER], engine.state.actors[W.FOE]
    source = _hex(engine, 4)
    engine._apply_condition(foe, "condition:typed.poisoned", source.source_definition_id,
                            source.owner_id, expires_on="UNTIL_REMOVED", data={"label": "Anchor"})
    key, condition = next((key, value) for key, value in foe.conditions.items()
                          if value.condition_id == "condition:typed.poisoned")
    zone = ZoneState(zone_id="zone:test:anchor", source_definition_id=source.source_definition_id,
                     owner_id=source.owner_id, center=foe.position, radius_cells=0,
                     affected_cells=(foe.position,), concentration_link=False, created_round=1,
                     trigger_profile={"anchor_id": foe.entity_id})
    engine.state.zones[zone.zone_id] = zone
    ctx = _context(engine, owner, palm_action(engine, "Unravel Manifestation"), foe)
    palm._apply(ctx, foe, "condition", key, condition, until="start", label="Anchor")
    assert condition.condition_id == "condition:typed.suppressed.poisoned"
    assert area_suppression.suppressed(zone) and not zone.affected_cells
    _turn(engine, W.OWNER)
    assert condition.condition_id == "condition:typed.poisoned"
    assert not area_suppression.suppressed(zone) and zone.affected_cells
