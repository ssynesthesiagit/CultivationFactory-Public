"""Sealed synthetic prefight buffs isolate the real World-Nerve table action.

The buffs supply two held effects and a save-mode fixture, without modifying
the production rules or injecting state after a match is sealed.
"""
import copy
import pytest
from combat import concentration
from combat.gate2_engine import SYSTEM_CONCENTRATION
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r1i_service_support import fixture, candidate, OWNER, FOE
from combat.canonical import canonical_sha256


@pytest.mark.parametrize("next_only", [True, False])
def test_world_nerve_recomputes_each_held_save_table_reload(tmp_path, next_only):
    def prepare(bundles):
        bundle = next(b for b in bundles if b["actor_id"] == FOE)
        original = next(a for a in bundle["action_catalog"] if a.get("parameters", {}).get("typed"))
        options = []
        for index in range(2):
            action = copy.deepcopy(original)
            source = f"test:world_nerve_held_{index}"
            action.update(source_definition_id=source, display_name=f"Held fixture {index}")
            effects = [] if index else [
                # Reviewed temporary-HP damage now triggers Concentration too.
                # Immunity isolates World-Nerve's explicit held-effect checks.
                {"type": "immunity", "applies_to": "self", "damage_types": ["LIGHTNING"]},
                {"type": "advantage", "applies_to": "self", "on": "next Concentration save" if next_only else "Concentration saves",
                 "expires_on": "UNTIL_REMOVED" if next_only else "CONCENTRATION_END"},
            ]
            action["parameters"] = {"typed": {"numbers": {"pb": 4, "cl": 17}, "effects": effects,
                                               "duration": {"kind": "minutes", "amount": 10}, "concentration": True}}
            bundle["action_catalog"].append(action)
            options.append({"action_id": source, "name": action["display_name"], "costs": [], "concentration": True})
        bundle["prefight"] = {"options": options, "picks": [o["action_id"] for o in options]}
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)

    combat, table, mid, send, commit = fixture(tmp_path, ["TAL_LIGHTNING_WORLD_NERVE_JUDGMENT"],
        foe_talents=["WATER_BASE_SHAPE_CURRENT"], bundle_transform=prepare)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    subject = combat._load_session(mid).engine.state.actors[FOE]
    assert len(concentration.held(subject)) == 1 and subject.concentration
    assert any(c.condition_id == concentration.MODE for c in subject.conditions.values())
    commit(candidate(table, mid, "World-Nerve Judgment", FOE))
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    saves = [e for e in loaded.engine.events if e.sequence > before["event_sequence"]
             and e.event_type == "SAVE_ROLLED" and e.source_definition_id == SYSTEM_CONCENTRATION]
    assert [e.payload["mode"] for e in saves] == ["NORMAL", "DISADVANTAGE"]
    assert loaded.engine.state.actors[FOE].current_hp == before["actors"][FOE]["current_hp"]
    assert not any(c.condition_id == concentration.MODE for c in loaded.engine.state.actors[FOE].conditions.values())
    assert not concentration.sources(loaded.engine.state.actors[FOE])
    assert loaded.mechanical.replay()["status"] == "PASS"
