import pytest

from combat.gate2_runtime_models import ZoneState
from tests.test_auto_tabik import _engine, ME, AN


@pytest.mark.parametrize("kind", ["TYPED", "OBJECT", "BLACKWATER", "SEA_RISEN"])
def test_map_zones_do_not_enter_actor_owned_legacy_handlers(kind):
    e, _ = _engine([])
    actor = e.state.actors[ME]
    zone = ZoneState(zone_id="zone:test", source_definition_id="test:zone", owner_id="map",
                     center=actor.position, radius_cells=0, affected_cells=(actor.position,),
                     concentration_link=False, created_round=e.state.round_number, trigger_profile={"kind": kind})
    e.state.zones[zone.zone_id] = zone
    hp, count = actor.current_hp, len(e.events)
    e._resolve_zone_triggers(actor, checkpoint="AT_TURN_START")
    e._resolve_zone_entry_triggers(actor)
    assert actor.current_hp == hp
    assert len(e.events) == count
    e._hostile_difficult_cells(actor)


def test_known_hostile_zones_still_dispatch(monkeypatch):
    e, _ = _engine([])
    actor = e.state.actors[ME]
    zone = ZoneState(zone_id="zone:test", source_definition_id="test:zone", owner_id=AN,
                     center=actor.position, radius_cells=0, affected_cells=(actor.position,),
                     concentration_link=False, created_round=e.state.round_number, trigger_profile={"kind": "BLACKWATER"})
    e.state.zones[zone.zone_id] = zone
    calls = []
    monkeypatch.setattr(e, "_resolve_zone_effect", lambda z, a, checkpoint: calls.append(checkpoint))
    e._resolve_zone_triggers(actor, checkpoint="AT_TURN_START")
    e._resolve_zone_entry_triggers(actor)
    assert calls == ["AT_TURN_START", "ON_ENTER_ZONE"]
