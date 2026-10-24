"""Synthetic Active Defense inputs for public native-journey regressions.

Consumers: test_journey_activities_native (Shield only),
test_mgr_t14_active_defense_window (through that module's game helper), and
test_mgr_t14_active_defense_reading. Public exports may replace printed prose;
these tests must not depend on that prose to classify their synthetic creature's
reaction. Only test data paths are replaced, never engine/compiler functions.
"""
import copy
import hashlib
import json
from pathlib import Path

from combat import factory_compiler, reaction_triggers

DEFENSE = "SHIELD_BASE_ACTIVE_DEFENSE"
TRIGGER = "A creature you are aware of makes an attack roll against you"


def fixture_authority(authority):
    """Return a copy with the single tested ability's explicit synthetic profile."""
    result = copy.deepcopy(authority)
    mechanic = result["mechanics"][DEFENSE]
    mechanic.update(mechanic_id=DEFENSE, name="Active Defense", kind="base_ability",
                    sphere_id="tianxia.sphere.shield",
                    activation={"economy": "reaction", "trigger": TRIGGER,
                                "requirement": "Wielding a Shield"},
                    cost=[], duration={"kind": "instant"}, riders=[], options=[])
    mechanic["effects"] = [{"type": "ac_bonus", "applies_to": "self", "flat": 2,
                            "formula": "none", "duration": "triggering_attack"}]
    return result


def install(tmp_path, monkeypatch):
    """Seal synthetic data for the real compiler/acquisition/replay boundaries."""
    original = factory_compiler.TYPED_AUTHORITY
    authority = fixture_authority(json.loads(original.read_text()))
    directory = tmp_path / "synthetic_shield_authority"
    directory.mkdir()
    path = directory / original.name
    path.write_text(json.dumps(authority))
    # Advancement help reads beside the injected authority; its public input
    # remains available without importing any private fixture or owner package.
    text_directory = directory / "typed_mechanics"
    text_directory.mkdir()
    public_texts = json.loads((Path(__file__).resolve().parents[1] /
                              "authority/typed_mechanics/rules_text.json").read_text())
    (text_directory / "rules_text.json").write_text(json.dumps(public_texts))
    readings = [json.loads(line) for line in reaction_triggers.READINGS_PATH.read_text().splitlines()
                if line.strip()]
    readings = [r for r in readings if r["mechanic_id"] != DEFENSE]
    readings.append({"schema": "TianxiaFoundry.TriggerReading.v1", "mechanic_id": DEFENSE,
                     "text_sha256": hashlib.sha256(TRIGGER.encode()).hexdigest(),
                     "events": [{"kind": "attacked"}], "status": "auto",
                     "reading": "An aware attacker makes an attack roll against you."})
    reading_path = directory / "trigger_readings.jsonl"
    reading_path.write_text("\n".join(json.dumps(row) for row in readings) + "\n")
    monkeypatch.setattr(factory_compiler, "TYPED_AUTHORITY", path)
    monkeypatch.setattr(reaction_triggers, "READINGS_PATH", reading_path)
    return authority
