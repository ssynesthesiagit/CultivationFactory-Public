"""Comma-separated damage permissions survive table commit and cold reload."""
import pytest

from combat.area_recipients import harmful_effect_scope, scoped_area
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_friendly_fire_area_table import _commit_area_action
from tests.test_lock_choices import install
from tests.test_tabletop_hunt6 import ALLY, LEFT, RIGHT, table_fight


@pytest.mark.parametrize("shape", ["sphere", "cone", "line"])
def test_comma_damage_clauses_keep_separate_recipients_after_reload(tmp_path, monkeypatch, shape):
    source, name = "test:selfhit-f7-clauses", "Mixed fire breath" if shape != "sphere" else "Mixed fire burst"

    def compile_area(info):
        if info["actor_id"] != LEFT:
            return []
        effects = [
            {"type": "damage", "flat": 5, "damage_types": ["fire"],
             "applies_to": "creatures_in_area", "evidence": "Each creature in the area takes 5 fire damage."},
            {"type": "damage", "dice": {"count": 1, "sides": 6}, "damage_types": ["fire"],
             "applies_to": "enemies_in_area", "evidence": "Creatures in the area take 1d6 fire damage."},
        ]
        area = {"shape": shape, "size_ft": 30, "include_origin": True}
        if shape == "sphere":
            area["centered_on_self"] = True
        typed = {"numbers": info["numbers"], "effects": effects}
        typed["area"] = scoped_area(area, effects,
            "Each creature in the area takes 5 fire damage, and creatures in the area take 1d6 fire damage.",
            typed=typed)
        return [ActionDefinition(source_definition_id=source, display_name=name, owner_id=LEFT,
            economy=EconomyKind.ACTION, resolution_kind="TYPED",
            target_kind="SELF" if shape == "sphere" else "CELL", range_ft=30, radius_ft=30,
            parameters={"typed": typed})]

    install(monkeypatch, "compile_actions", compile_area)
    _, table, mid = table_fight(tmp_path, [], ally_talents=[],
        starts={"team1": [[3, 4], [4, 4]], "team2": [[5, 4]]})
    result, _ = _commit_area_action(table, mid, name, None if shape == "sphere" else {"x": 5, "y": 4})
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    typed = loaded.engine.action_catalog[source].parameters["typed"]
    assert [harmful_effect_scope(typed["area"], e) for e in typed["effects"]] == ["all", "hostile"]
    assert "harmful_recipient_override" not in typed["area"]
    assert all(isinstance(k, str) and isinstance(v, str)
               for k, v in typed["area"]["harmful_payload_scopes"].items())
    assert loaded.engine.state.actors[ALLY].current_hp == 55
    assert loaded.engine.state.actors[LEFT].current_hp == (55 if shape == "sphere" else 60)
    assert loaded.engine.state.actors[RIGHT].current_hp < 55
    packets = [e for e in loaded.engine.events
               if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == source]
    assert sum(ALLY in e.target_ids for e in packets) == 1
    assert sum(RIGHT in e.target_ids for e in packets) == 2
    # Owner addendum: emitted breath/cone/line NEVER damages its caster,
    # including the explicitly inclusive packet. The sphere is the control.
    assert sum(LEFT in e.target_ids for e in packets) == int(shape == "sphere")
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
