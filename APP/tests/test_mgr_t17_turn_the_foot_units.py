"""MGR-T17 Turn the Foot Opportunity-Attack choice: data-free regression checks.

These run on the public route, with no typed authority and no fight. They pin two things:

* the one seam that says an attack is an Opportunity Attack while it is rolled is the documented accessor
  combat/typed_reactions.current_opportunity_attacker, and the plug-in does not read the private provenance marker;
* the condition the Opportunity-Attack choice creates has a tooltip that says what it does.
"""

from types import SimpleNamespace

from combat import typed_executor, typed_reactions
from combat.ext import generated_status_text
from combat.ext import opportunity_attack_mode as plugin
from combat.gate2_runtime_content import AN
from tests.test_auto_wenxue import ME, _bundle
from tests.test_auto_wenxue import _engine as _wenxue_engine

ACTOR = "entity:striker"


def _engine(**attrs):
    return SimpleNamespace(**attrs)


def test_accessor_reads_the_rolling_attack_marker_only():
    # The attack-completion provenance names the same creature, but it is not the rolling-attack marker.
    provenance_only = _engine(_opportunity_attack_provenance=(ACTOR, "entity:foe", "movement", "src"))
    assert typed_reactions.current_opportunity_attacker(provenance_only) is None
    assert plugin._in_opportunity_attack_window(provenance_only, ACTOR) is False

    rolling = _engine(_typed_oa_attacker=ACTOR)
    assert typed_reactions.current_opportunity_attacker(rolling) == ACTOR
    assert plugin._in_opportunity_attack_window(rolling, ACTOR) is True
    assert plugin._in_opportunity_attack_window(rolling, "entity:other") is False


def test_plugin_window_is_false_without_an_actor():
    assert plugin._in_opportunity_attack_window(_engine(_typed_oa_attacker=None), None) is False


def test_tooltip_says_what_the_opportunity_attack_condition_does():
    row = {"condition_id": "condition:typed.opportunity_attack_mode", "source_definition_id": None}
    data = {"rule": {"opportunity_attack_mode": {"mode": "DISADVANTAGE", "next": True}}}
    engine = _engine(action_catalog={}, state=SimpleNamespace(actors={}))
    reading = generated_status_text.describe(engine, None, row, data)
    assert reading is not None, "the Opportunity-Attack condition has no tooltip"
    assert reading["text"].startswith("Disadvantage on its next Opportunity Attack"), reading["text"]
    assert "uses this up when it is rolled" in reading["text"]

    every = {"rule": {"opportunity_attack_mode": {"mode": "ADVANTAGE", "next": False}}}
    assert generated_status_text.describe(engine, None, row, every)["text"].startswith("Advantage on each Opportunity Attack")


# Review F2R1: the Opportunity-Attack branch of block_advantage must not take other "opportunity attack" wording.
OA_CONDITION = "condition:typed.opportunity_attack_mode"


def _block(engine, actor_id, target_id, effect):
    """Run typed_executor.block_advantage for one printed row, as the executor does for a failed save's effect."""
    action = next(iter(engine.action_catalog.values()))
    actor, target = engine.state.actors[actor_id], engine.state.actors[target_id]
    ctx = typed_executor.Context(engine, actor, action, None, {"numbers": {"pb": 4, "save_dc": 15}}, [target], target, {})
    typed_executor.block_advantage(ctx, effect)


def _oa_conditions(actor):
    return [held for held in actor.conditions.values() if held.condition_id == OA_CONDITION]


def test_opportunity_attacks_made_against_you_do_not_give_you_the_oa_condition():
    # "opportunity attacks against you have Disadvantage" (Monkey Style, Shi, Life rows): the holder is attacked, so the
    # condition must not appear on the holder as "its next Opportunity Attack it makes".
    engine = _wenxue_engine(_bundle())
    me = engine.state.actors[ME]
    _block(engine, ME, ME, {"type": "disadvantage", "applies_to": "self", "expires_on": "UNTIL_REMOVED",
                            "on": "opportunity attacks against you"})
    assert _oa_conditions(me) == [], "an Opportunity Attack made against the holder got the holder's own OA choice"
    assert _oa_conditions(engine.state.actors[AN]) == []


def test_the_turn_the_foot_wording_still_gives_the_creature_the_oa_condition():
    engine = _wenxue_engine(_bundle())
    me = engine.state.actors[ME]
    _block(engine, AN, ME, {"type": "disadvantage", "applies_to": "target", "on": "the next Opportunity Attack it makes",
                            "expires_on": "START_OF_TARGET_NEXT_TURN"})
    assert [held.data["rule"]["opportunity_attack_mode"] for held in _oa_conditions(me)] == [{"mode": "DISADVANTAGE", "next": True}]


# Review F2R2: the printed Prone clause is "if it moved at least 10 feet immediately before triggering Flowing Response".
def test_turn_the_foot_prone_branch_needs_ten_feet_of_movement():
    from combat.ext import bodyb_choices

    def prone_rows(moved):
        return [row for row in bodyb_choices.branch_effects("turn_the_foot", "prone", moved) if row.get("condition") == "prone"]

    assert prone_rows(0) == [] and prone_rows(5) == [] and prone_rows(9) == [], "under 10 feet is not Prone"
    assert len(prone_rows(10)) == 1 and len(prone_rows(15)) == 1, "10 feet or more is Prone"
    assert [row["type"] for row in bodyb_choices.branch_effects("turn_the_foot", "slow", 0)] == ["speed"], \
        "the Speed choice does not depend on movement"
