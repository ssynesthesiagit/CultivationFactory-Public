"""Revealing Ember's printed Dim Light is a plug-in row, not a per-ability branch in the adapter (LIGHTING_SPEC §8.2).

The review of feat/lighting-s3 found the ember's light keyed on passive:cinder.revealing_ember inside
combat/character_runtime_adapter.py. The light now comes from the curated row in combat/rules/light_sources.json through
the printed-light plug-in's "ember_marked" hook, so the table decides the radii and the core file names no light.
"""
from pathlib import Path

from combat import light_sources
from combat.lighting import LIGHT
from tests.test_c3ar_runtime_executability import bundle, event_types, req, runtime_engine  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parents[1]
CINDER_TOUCH = "tianxia.subpath.qi.cinder_heart_cultivator.feature.cinder_touch"


def _ember_hit(bundle, monkeypatch=None):
    """A Flame Lash with Cinder Touch that hits and marks the dummy with Revealing Ember (a deterministic seed search)."""
    for index in range(200):
        engine = runtime_engine(bundle, seed=f"ember-table:{index}")
        result = engine.execute_action(req(
            "action:fire.flame_lash", target_id="dummy:target",
            option_ids=("PUSH_10_FT", "USE_CINDER_TOUCH"),
        ))
        target = engine.state.actors["dummy:target"]
        if any(row.condition_id == "condition:fire.revealing_ember" for row in target.conditions.values()):
            return engine, target, result
    raise AssertionError("no seed in 200 marked the target with Revealing Ember")


def _lights(target):
    return [row for row in target.conditions.values() if row.condition_id == LIGHT]


def test_revealing_ember_light_is_the_curated_row(bundle):
    """"It sheds Dim Light in a 5-foot radius": the carried light is the table's Cinder Touch row, bright 0 / dim 5."""
    engine, target, result = _ember_hit(bundle)
    lights = _lights(target)
    assert len(lights) == 1
    assert (lights[0].data["bright_ft"], lights[0].data["dim_ft"]) == (0, 5)
    assert lights[0].data["source_id"] == CINDER_TOUCH
    assert lights[0].data["magical"] is True


def test_revealing_ember_radii_are_read_from_the_table(bundle, monkeypatch):
    """Table-level: the adapter no longer restates the radii, so a table change reaches the field. It fails on the old
    adapter, which hard-coded dim 5 beside the ember and ignored the row."""
    real_row = light_sources.row

    def tweaked(mechanic):
        found = real_row(mechanic)
        return {**found, "dim_ft": 9} if found and mechanic == CINDER_TOUCH else found

    monkeypatch.setattr(light_sources, "row", tweaked)
    engine, target, result = _ember_hit(bundle)
    (light,) = _lights(target)
    assert (light.data["bright_ft"], light.data["dim_ft"]) == (0, 9)


def test_the_core_adapter_names_no_ember_light():
    """Rule 1: no per-ability light in the core adapter, and no dead dim_light_radius_ft key anywhere in the code."""
    adapter = (ROOT / "combat" / "character_runtime_adapter.py").read_text(encoding="utf-8")
    assert "typed.light" not in adapter
    assert "dim_ft" not in adapter
    assert "dim_light_radius_ft" not in adapter
    for path in (ROOT / "combat").rglob("*.py"):
        assert "dim_light_radius_ft" not in path.read_text(encoding="utf-8"), path


def test_the_ember_light_ends_with_the_ember(bundle):
    """The light rides the ember's own clock: it is filed to expire where the ember does."""
    engine, target, result = _ember_hit(bundle)
    ember = next(row for row in target.conditions.values() if row.condition_id == "condition:fire.revealing_ember")
    (light,) = _lights(target)
    assert light.expires_on == ember.expires_on == "START_OF_SELF_NEXT_TURN"
