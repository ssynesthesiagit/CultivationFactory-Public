"""Public-input regressions: real compiler, survival prompt, commit and cold reload."""
import json
import pytest

from combat import factory_compiler
from combat.ext.yang_sun_marks import LIFE, DAWN, MANTLE, EXCEPTION
from combat.typed_executor import bears_mark
from tests.worker2_support import (
    OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload, sealed_native_attack,
)
from tests.yang_marks_support import synthetic_yang_inputs


@pytest.mark.parametrize("source", [LIFE, DAWN])
def test_compiled_protection_reaches_the_table_without_private_trigger_prose(
        tmp_path, monkeypatch, source):
    # Unlike protection_setup, this never installs a preclassified reaction row.
    # Keep the complete shipped effects, payment and per-creature use limits.
    def strike(bundles):
        sealed_native_attack(bundles[2], "Synthetic lethal strike", count=1, sides=2,
                             modifier=65, attack_bonus=100)

    with synthetic_yang_inputs(tmp_path, monkeypatch):
        combat, table, mid = fixture(
            tmp_path, [source], named=True, bundle_transform=strike,
            positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 5, "y": 6}})
    engine = reload(tmp_path, mid)
    rows = [row for row in engine.typed_reaction_rows[OWNER] if row["feature_id"] == source]
    assert any(row["kind"] == "ally_drop_to_zero" for row in rows)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, "Synthetic lethal strike", target=ALLY).candidate_id)
    assert any(prompt["context"]["reaction_source_id"].startswith("choice:life.survive:")
               for prompt in prompts)
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    assert ally.current_hp == 1
    assert bears_mark(ally, OWNER, "Kindled Mark")
    assert any(condition.condition_id == EXCEPTION for condition in ally.conditions.values())
    receipt = next(event for event in engine.events if event.event_type == "DAMAGE_COMMITTED"
                   and event.target_ids == (ALLY,))
    assert receipt.payload["hp_damage"] == receipt.payload["hp_before"] - 1
    # GM_RIDER also carries inherited rule reminders. This diagnostic guards
    # execution exceptions, not unrelated reminder coverage; the protection,
    # mark and continuation are asserted above as committed state.
    errors = [event.payload.get("rider") for event in engine.events
              if event.event_type == "GM_RIDER" and event.source_definition_id == source
              and "could not run:" in str(event.payload.get("rider") or "")]
    assert not errors, errors


def test_mantle_light_profile_survives_table_reload_without_source_prose(tmp_path, monkeypatch):
    # Force the public-export condition even on a private runner. The missing
    # value was visual.light, not zone_spec: area/triggers are already typed.
    authority = json.loads(factory_compiler.TYPED_AUTHORITY.read_text())
    mantle = authority["mechanics"][MANTLE]
    mantle["description"], mantle["riders"] = [], []
    for effect in mantle["effects"]:
        effect["evidence"] = "Synthetic source label."
    source = tmp_path / "unlit-authority.json"
    source.write_text(json.dumps(authority))
    monkeypatch.setattr(factory_compiler, "TYPED_AUTHORITY", source)
    with synthetic_yang_inputs(tmp_path, monkeypatch):
        combat, table, mid = fixture(tmp_path, [MANTLE])
    settle(table, mid, candidate(combat, mid, "Completing Flame Mantle").candidate_id)
    engine = reload(tmp_path, mid)
    zone = next(zone for zone in engine.state.zones.values()
                if zone.active and zone.owner_id == OWNER)
    profile = zone.trigger_profile
    assert profile["visual"]["light"]["radius_ft"] == 10
    assert profile["visual"]["light"]["level"] == "bright"
    assert profile["profile"]["grappling_owner"] == 1
    trigger = profile["triggers"][0]
    assert trigger["on"] == ["grappler_start"]
    assert trigger["effects"][0]["damage_types"] == ["fire", "radiant"]
