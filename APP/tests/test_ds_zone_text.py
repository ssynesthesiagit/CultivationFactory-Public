"""Cover labels through the table's shared zone hover builder."""
from combat.gate2_runtime_models import ZoneState
from combat.gate5_service import FACTORY_ACTOR_PREFIX
from tests.test_status_text import _tooltip_table


def test_zone_hover_uses_player_cover_name(tmp_path, monkeypatch):
    table, mid, engine = _tooltip_table(tmp_path, monkeypatch)
    actor = engine.state.actors[FACTORY_ACTOR_PREFIX + "left"]
    engine.state.zones["zone:test.wall"] = ZoneState(zone_id="zone:test.wall", source_definition_id="action:old.wall",
        owner_id=actor.entity_id, center=actor.position, radius_cells=1, affected_cells=(actor.position,),
        concentration_link=False, created_round=engine.state.round_number,
        trigger_profile={"name": "Dune Wall", "wall": {"cover": "three_quarters"}})
    row = next(z for z in table.state(mid)["presentation"]["zones"] if z["zone_id"] == "zone:test.wall")
    assert row["rule_text"] == "Grants three-quarters cover."
    assert "Grants three-quarters cover." in row["detail"]
    assert "three_quarters" not in row["detail"]
