"""Sight effects reach the actual table state without changing combat state."""
import pytest

from combat.canonical import canonical_sha256
from combat.gate2_runtime_models import ZoneState
from combat.gate5_service import FACTORY_ACTOR_PREFIX
from combat import targeting, target_knowledge, zones, senses
from tests.test_status_text import _tooltip_table


@pytest.mark.parametrize("level,material,key,label", [
    ("light", "fog", "concealment_miss_percent", "concealment"),
    ("heavy", "smoke", "total_concealment_miss_percent", "total concealment"),
])
def test_table_state_carries_obscuring_zone_hover(tmp_path, monkeypatch, level, material, key, label):
    table, mid, engine = _tooltip_table(tmp_path, monkeypatch)
    actor = engine.state.actors[FACTORY_ACTOR_PREFIX + "left"]
    for name, visual in [("Cloud", {"material": material, "obscured": level}),
                         ("Darkness", {"material": "darkness", "darkness": True})]:
        zone = ZoneState(zone_id=f"zone:sol144.{name}", source_definition_id="action:old.area",
            owner_id=actor.entity_id, center=actor.position, radius_cells=1, affected_cells=(actor.position,),
            concentration_link=True, created_round=engine.state.round_number, duration_rounds=10,
            trigger_profile={"kind": "TYPED", "name": name, "visual": visual,
                             **({"obscured": level} if name == "Cloud" else {})})
        engine.state.zones[zone.zone_id] = zone
    before = canonical_sha256(engine.state.model_dump(mode="json"))
    state = table.state(mid)
    rows = {row["display_name"]: row for row in state["presentation"]["zones"]}
    cloud = rows["Cloud"]
    expected = "can't see have Disadvantage"
    assert all('miss chance' not in cloud[k] and '%' not in cloud[k]
               for k in ('sight_text', 'rule_text', 'detail'))
    assert expected in cloud["sight_text"]
    assert expected in cloud["rule_text"] and expected in cloud["detail"]
    assert cloud["applied_by"] == actor.display_name
    assert cloud["concentration_link"] and "concentrating" in cloud["duration"]
    assert cloud["duration_rounds"] == 10 and cloud["created_round"] == engine.state.round_number
    assert cloud["affected_cells"] == rows["Darkness"]["affected_cells"]
    assert cloud["trigger_profile"]["visual"] == {"material": material, "obscured": level}
    assert cloud["active"] and rows["Darkness"]["active"]
    assert canonical_sha256(engine.state.model_dump(mode="json")) == before


@pytest.mark.parametrize("profile,percent_key,hidden", [
    ({"visual": {"material": "fog", "obscured": "heavy"}}, None, False),
    ({"obscured": "light"}, "concealment_miss_percent", False),
    ({"lightly_obscured": True}, "concealment_miss_percent", False),
    ({"visual": {"light": "dim"}}, "concealment_miss_percent", False),
    ({"obscured": "heavy"}, "total_concealment_miss_percent", True),
    ({"obscured": "heavy", "owner_sees": True}, None, False),
    ({"obscured": "heavy", "owner_sees": True, "team_sees": True}, "concealment_miss_percent", False),
])
@pytest.mark.parametrize("nonvisual", [False, True])
@pytest.mark.parametrize("zero_policy", [False, True])
def test_table_sight_text_matches_targeting(tmp_path, monkeypatch, profile, percent_key, hidden, nonvisual, zero_policy):
    # Bind a real alternate policy before creation; existing fights do not change
    # policy when the owner's configuration is later edited.
    configured = {k: (0 if zero_policy else targeting.LEGACY_POLICY[k]) for k in targeting.POLICY_KEYS}
    monkeypatch.setattr(targeting, 'rules', lambda: dict(configured))
    table, mid, engine = _tooltip_table(tmp_path, monkeypatch)
    viewer = engine.state.actors[FACTORY_ACTOR_PREFIX + "left"]
    target = viewer.model_copy(deep=True, update={"entity_id": "test:target", "team_id": "test:foes"})
    engine.state.actors[target.entity_id] = target
    target.conditions.clear()
    owner = viewer
    if profile.get("team_sees"):
        owner = viewer.model_copy(deep=True, update={"entity_id": "test:creator"})
        engine.state.actors[owner.entity_id] = owner
    # Target is close enough for ordinary sight and Blindsight; the zone covers it only.
    target.position = viewer.position.model_copy(update={"x": viewer.position.x + 1})
    zone = ZoneState(zone_id="zone:sol144.policy", source_definition_id="action:old.area",
        owner_id=owner.entity_id, center=target.position, radius_cells=0, affected_cells=(target.position,),
        concentration_link=False, created_round=engine.state.round_number,
        trigger_profile={"kind": "TYPED", "name": "Test cloud", **profile})
    engine.state.zones = {zone.zone_id: zone}
    if nonvisual:
        engine._apply_condition(viewer, senses.SENSE, "test:blindsight", viewer.entity_id,
                               expires_on="UNTIL_REMOVED", data={"sense": "blindsight", "range_ft": 30})
    policy = targeting.policy(engine)
    expected = 0 if nonvisual or not percent_key else policy[percent_key]
    assert targeting.concealment_percent(engine, viewer, target) == expected
    assert target_knowledge.can_see(engine, viewer, target) == (not hidden or nonvisual)
    assert ("DISADVANTAGE" in zones.attack_modes(engine, viewer, target)) == (hidden and not nonvisual)
    before = canonical_sha256(engine.state.model_dump(mode="json"))
    row = next(z for z in table.state(mid)["presentation"]["zones"] if z["zone_id"] == zone.zone_id)
    text = row["sight_text"]
    if profile.get("visual", {}).get("obscured"):
        assert text == "Visual cloud only: this area adds no concealment."
        assert "miss chance" not in row["rule_text"]
    else:
        assert "can't see have Disadvantage" in text
        assert "without sight" in text and "within their range" in text
        if profile.get("owner_sees"):
            assert "creator sees through it normally" in text
        if profile.get("team_sees"):
            assert "teammates see creatures inside as lightly obscured" in text
        if expected:
            assert f"{expected}% miss chance" in text
        if zero_policy:
            assert "miss chance" not in text and "%" not in text
    assert row["sight_rules"] == {k: policy[k] for k in ("concealment_miss_percent", "total_concealment_miss_percent")}
    assert text in row["rule_text"] and text in row["detail"]
    assert canonical_sha256(engine.state.model_dump(mode="json")) == before


def test_absent_percentages_do_not_print_zero_percent_chances():
    from combat.status_text import zone_sight_text
    text = zone_sight_text({"obscured": "heavy", "owner_sees": True, "team_sees": True}, {})
    assert "can't see have Disadvantage" in text
    assert "%" not in text and "miss chance" not in text
