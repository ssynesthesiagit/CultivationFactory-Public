"""Revealing Ember's printed Dim Light is a plug-in row, not a per-ability branch in the adapter (LIGHTING_SPEC §8.2).

The review of feat/lighting-s3 found Revealing Ember keyed on passive:cinder.revealing_ember inside
combat/character_runtime_adapter.py. The core now reports only the generic "character_damage_committed" seam; the ember
rule lives in combat/ext/cinder_ember.py and sheds the curated row in combat/rules/light_sources.json through
combat/ext/printed_light.py::shed, so the table decides the radii and core names no ability.
"""
from pathlib import Path

import pytest

from combat import light_sources
from combat.lighting import LIGHT
from tests.test_c3ar_runtime_executability import (  # noqa: F401  (fixtures)
    adapter,
    bundle,
    event_types,
    req,
    runtime_engine,
    runtime_package,
)

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


def test_core_names_no_revealing_ember_ability():
    """Owner rule: the core never names an ability. Revealing Ember's passive, mark and light live only in its plug-in."""
    core = ROOT / "combat"
    for name in ("character_runtime_adapter.py", "typed_executor.py", "factory_compiler.py", "gate5_service.py"):
        text = (core / name).read_text(encoding="utf-8")
        assert "revealing_ember" not in text, name
        assert "ember_marked" not in text, name
        if name == "character_runtime_adapter.py":
            assert "passive:cinder." not in text
            assert "USE_CINDER_TOUCH" not in text
            assert "cinder_touch" not in text
    owners = [path.name for path in core.rglob("*.py") if "fire.revealing_ember" in path.read_text(encoding="utf-8")]
    assert owners == ["cinder_ember.py"], owners


def test_the_ember_plugin_is_the_only_mark_and_light_emitter():
    """The mark and its Dim Light are filed only by the plug-in that owns the rule, through the generic committed-attack seam."""
    from combat.ext import cinder_ember

    assert cinder_ember.EMBER == "passive:cinder.revealing_ember"
    assert cinder_ember.MARK == "condition:fire.revealing_ember"
    assert cinder_ember.CINDER_TOUCH == CINDER_TOUCH
    text = (ROOT / "combat" / "ext" / "cinder_ember.py").read_text(encoding="utf-8")
    assert '@hook("character_damage_committed")' in text
    assert "shed(engine, target, CINDER_TOUCH" in text


def test_committed_damage_checkpoint_failure_unwinds_state_events_and_dice(bundle, monkeypatch):
    from combat import ext

    engine = runtime_engine(bundle, seed="seed-8")
    before = engine.state.model_dump(mode="json")
    events, rolls, counter = list(engine.events), list(engine.rolls), engine.roller.counter
    ext.effects()  # load ordinary providers before injecting the failing subscriber

    def fail_after_damage(*args):
        raise RuntimeError("unwind after committed damage")

    monkeypatch.setitem(ext._HOOKS, "character_damage_committed",
                        [*ext._HOOKS["character_damage_committed"], fail_after_damage])
    with pytest.raises(ext.CheckpointError, match="unwind after committed damage"):
        engine.execute_action(req("action:fire.flame_lash", target_id="dummy:target",
                                  option_ids=("PUSH_10_FT", "USE_CINDER_TOUCH")))
    assert engine.state.model_dump(mode="json") == before
    assert engine.events == events and engine.rolls == rolls
    assert engine.roller.counter == counter


def test_fire_hit_without_cinder_touch_adds_neither_ember_nor_light(bundle):
    engine = runtime_engine(bundle, seed="seed-8")
    engine.execute_action(req("action:fire.flame_lash", target_id="dummy:target", option_ids=("PUSH_10_FT",)))
    target = engine.state.actors["dummy:target"]
    assert not any(c.condition_id == "condition:fire.revealing_ember" for c in target.conditions.values())
    assert not _lights(target)


def test_area_cinder_touch_marks_and_lights_only_its_one_bonus_recipient(bundle):
    from combat.character_runtime_adapter import CharacterCombatRuntimeEngine, SOURCE_ACTOR_ID, dummy_actor_template
    from combat.gate2_runtime_models import Position

    targets = tuple(dummy_actor_template(aid, team_id="team:dummy", armor_class=1, maximum_hp=1000)
                    .model_copy(update={"saving_throws": {"DEX": -100}})
                    for aid in ("dummy:area-a", "dummy:area-b"))
    engine = CharacterCombatRuntimeEngine(
        ROOT, bundle, match_seed="EMBER-AREA", additional_actors=targets,
        positions={SOURCE_ACTOR_ID: Position(x=2, y=2), "dummy:area-a": Position(x=3, y=2),
                   "dummy:area-b": Position(x=4, y=2)})
    engine.execute_action(req("action:fire.fireball_art", destination=Position(x=3, y=2),
                              option_ids=("USE_CINDER_TOUCH",)))
    assert all(engine.state.actors[t.entity_id].current_hp < 1000 for t in targets)
    marked = [a for a in engine.state.actors.values()
              if any(c.condition_id == "condition:fire.revealing_ember" for c in a.conditions.values())]
    assert [a.entity_id for a in marked] == ["dummy:area-a"]
    assert len(_lights(marked[0])) == 1
    assert not _lights(engine.state.actors["dummy:area-b"])
    bonuses = [e for e in engine.events if e.event_type == "PASSIVE_TRIGGERED"
               and e.source_definition_id == "passive:cinder.touch_damage"]
    assert len(bonuses) == 1


def test_cinder_bonus_uses_its_owners_proficiency_bonus(bundle):
    actor = bundle.actor_template.model_copy(update={"proficiency_bonus": 5})
    engine, target, result = _ember_hit(bundle.model_copy(update={"actor_template": actor}))
    bonuses = [e for e in engine.events if e.event_type == "PASSIVE_TRIGGERED"
               and e.source_definition_id == "passive:cinder.touch_damage"]
    assert len(bonuses) == 1
    assert bonuses[0].payload["added_damage"] == 5


def test_generic_resistance_does_not_claim_an_unowned_cinder_passive(bundle):
    engine = runtime_engine(bundle, seed="COLD-RESISTANCE")
    target = engine.state.actors["dummy:target"]
    target.damage_resistances = ("COLD",)
    assert engine._apply_damage_resistance(target, 9, "COLD", "test:cold") == 4
    assert engine.events[-1].source_definition_id == "rule:damage_resistance.cold"
    assert "passive:cinder.fire_resistance" not in target.passive_ids


def test_the_ember_light_ends_with_the_ember(bundle):
    """The light rides the ember's own clock: it is filed to expire where the ember does."""
    engine, target, result = _ember_hit(bundle)
    ember = next(row for row in target.conditions.values() if row.condition_id == "condition:fire.revealing_ember")
    (light,) = _lights(target)
    assert light.expires_on == ember.expires_on == "START_OF_SOURCE_NEXT_TURN"
    engine._expire_typed_for_checkpoint("START_OF_TURN", target.entity_id)
    assert _lights(engine.state.actors[target.entity_id])
    engine._expire_typed_for_checkpoint("START_OF_TURN", ember.source_actor_id)
    target = engine.state.actors[target.entity_id]
    assert not _lights(target)
    assert not any(c.condition_id == "condition:fire.revealing_ember" for c in target.conditions.values())
