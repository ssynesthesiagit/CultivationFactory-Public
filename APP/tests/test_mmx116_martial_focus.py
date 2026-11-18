"""MMX116 / HUNT114 finding #5: the "Martial Focus never comes back for compiled fighters" suspicion.

Measured here rather than assumed, because HUNT114 could not confirm it. The printed rule
(authority/typed_mechanics/rules_text.json, ATHLETICS_BASE_COORDINATED_MOVEMENT):

    "Coordinated Movement -- Whenever you take the Dash or Disengage Action as your Action, regain
     Martial Focus. This does not trigger when taking Dash or Disengage as a Bonus Action."

Verdict: NOT a bug. The feature compiles and works on the compiled-fighter path, which is the path
the table uses; HUNT114's audit simply never saw a hand fighter take Dash or Disengage as their
Action, so Martial Focus correctly stayed 0. Two of its premises were wrong: there is no
"coordinated_movement" row (the row is block "motion", kind "regain_focus"), and the only regain is
not the C3AR quick-build one in character_runtime_adapter.py.

This file locks the correct behaviour in place, including the exclusion the text spells out, so a
later change cannot quietly make a Bonus Action Dash regain Martial Focus.
"""

from pathlib import Path

from combat import typed_reactions
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate4_engine import Gate4ControllerEngine
from tests.h1_support import sheet

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.mmx116_mf"
FOCUS = "resource:core.martial_focus"


def _fighter():
    """A compiled fighter owning Coordinated Movement, with Martial Focus spent."""
    bundle = compile_character(sheet(["ATHLETICS_BASE_COORDINATED_MOVEMENT"], primary="Stamina", cl=10),
                               actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed="MMX116-MF", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN],
                                                 "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6},
                                                                       AN: {"x": 4, "y": 6}}})
    actor = engine.state.actors[ME]
    assert FOCUS in actor.resources, "a compiled fighter owns a Martial Focus pool"
    actor.resources[FOCUS] = 0
    engine.state.current_actor_id = ME
    return engine, actor


def test_coordinated_movement_compiles_onto_the_compiled_fighter():
    bundle = compile_character(sheet(["ATHLETICS_BASE_COORDINATED_MOVEMENT"], primary="Stamina", cl=10),
                               actor_id=ME)
    row = next(r for r in bundle["typed_passives"] if r.get("block") == "motion")
    assert (row["kind"], row["actions"]) == ("regain_focus", ["dash", "disengage"])
    assert "Coordinated Movement" not in bundle["diagnostics"]["skipped"].get("passive", [])


def test_an_action_dash_or_disengage_regains_martial_focus():
    for source in ("system:combat.dash", "system:combat.disengage"):
        engine, actor = _fighter()
        typed_reactions.on_action_completed(engine, actor, "ACTION", source)
        assert actor.resources[FOCUS] == 1, f"{source} taken as the Action did not regain Martial Focus"


def test_a_bonus_action_dash_does_not_regain_martial_focus():
    """The printed exclusion: "This does not trigger when taking Dash or Disengage as a Bonus Action"."""
    for source in ("system:combat.dash", "system:combat.disengage"):
        engine, actor = _fighter()
        typed_reactions.on_action_completed(engine, actor, "BONUS_ACTION", source)
        assert actor.resources[FOCUS] == 0, f"{source} taken as a Bonus Action wrongly regained Martial Focus"


def test_another_action_does_not_regain_martial_focus():
    engine, actor = _fighter()
    typed_reactions.on_action_completed(engine, actor, "ACTION", "system:combat.dodge")
    assert actor.resources[FOCUS] == 0, "Dodge is not one of Coordinated Movement's actions"


def test_a_fighter_without_the_feature_regains_nothing():
    bundle = compile_character(sheet([], primary="Stamina", cl=10), actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed="MMX116-MF-NONE", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN],
                                                 "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6},
                                                                       AN: {"x": 4, "y": 6}}})
    actor = engine.state.actors[ME]
    actor.resources[FOCUS] = 0
    engine.state.current_actor_id = ME
    typed_reactions.on_action_completed(engine, actor, "ACTION", "system:combat.dash")
    assert actor.resources[FOCUS] == 0
