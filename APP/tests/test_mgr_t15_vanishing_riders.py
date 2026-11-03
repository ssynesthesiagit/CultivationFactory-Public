"""Vanishing's automated effects must not also be assigned to the GM."""
import json
from pathlib import Path

from combat.typed_executor import check_mode
from tests.worker2_support import OWNER, candidate, fixture, reload, settle

VANISH = "tianxia.subpath.qi.ninpo_adept.feature.vanishing_technique"


def test_activation_has_no_manual_riders_and_applies_effects(tmp_path):
    root = Path(__file__).resolve().parents[1]
    authority = json.loads((root / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    assert authority["mechanics"][VANISH]["riders"] == []

    combat, table, mid = fixture(tmp_path, [], cl=14, owner_features=[VANISH], owner_path="Qi Cultivation")
    engine = reload(tmp_path, mid)
    activation = candidate(combat, mid, "Vanishing Technique")
    action = engine.action_catalog[activation.source_definition_id]
    assert not (action.parameters.get("typed") or {}).get("riders")
    qi = engine.state.actors[OWNER].resources["resource:core.qi"]
    mark = len(engine.events)
    settle(table, mid, activation.candidate_id)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.resources["resource:core.qi"] == qi - 5
    assert any(c.condition_id == "condition:typed.invisible" for c in actor.conditions.values())
    assert any(c.condition_id == "condition:typed.vanishing_state" for c in actor.conditions.values())
    assert check_mode(actor, "DEX", "Stealth", engine=engine) == "ADVANTAGE"
    assert not any(e.event_type == "GM_RIDER" for e in engine.events[mark:])
