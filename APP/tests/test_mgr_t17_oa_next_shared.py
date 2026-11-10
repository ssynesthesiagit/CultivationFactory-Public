"""MGR-T17 review F6R1: one mechanism for "Disadvantage on the next Opportunity Attack".

Turn the Foot (the attacker holds the condition) and Storm-Heart Engine (the attacked creature holds it) share one plug-in,
combat/ext/opportunity_attack_mode.py. These checks use plain stand-ins for the engine and creatures, so they run on the
public route with no fight and no typed authority.
"""

from types import SimpleNamespace

from combat.ext import generated_status_text
from combat.ext import opportunity_attack_mode as plugin

ATTACKER = "entity:attacker"
HOLDER = "entity:holder"
CONDITION = "condition:typed.opportunity_attack_mode"


class _Engine:
    def __init__(self, rolling):
        self._typed_oa_attacker = rolling
        self.removed = []
        self.state = SimpleNamespace(actors={})

    def _remove_condition(self, creature, condition_id, source_definition_id):
        self.removed.append((creature.entity_id, condition_id, source_definition_id))
        creature.conditions = {k: v for k, v in creature.conditions.items() if v is not held_for(creature, source_definition_id)}


def held_for(creature, source):
    return next((c for c in creature.conditions.values() if c.source_definition_id == source), None)


def _creature(entity_id, *rules):
    creature = SimpleNamespace(entity_id=entity_id, conditions={})
    for side, mode, source in rules:
        held = SimpleNamespace(condition_id=CONDITION, source_definition_id=source, data={"rule": {"opportunity_attack_mode": {
            "mode": mode, "next": True, **({"side": side} if side else {})}}})
        creature.conditions[source] = held
    return creature


def _ctx(engine, actor):
    return SimpleNamespace(engine=engine, actor=actor)


def test_turn_the_foot_condition_changes_only_the_attack_its_holder_makes():
    maker = _creature(ATTACKER, (None, "DISADVANTAGE", "ability:turn_the_foot"))
    holder = _creature(HOLDER)
    engine = _Engine(rolling=ATTACKER)
    assert plugin.opportunity_attack_mode(_ctx(engine, maker), holder) == "DISADVANTAGE"
    assert plugin.opportunity_attack_mode_against_target(_ctx(engine, maker), holder) is None
    engine = _Engine(rolling=HOLDER)
    assert plugin.opportunity_attack_mode(_ctx(engine, maker), holder) is None, "not the holder's own Opportunity Attack"


def test_storm_heart_condition_changes_only_the_attack_made_against_its_holder():
    holder = _creature(HOLDER, ("target", "DISADVANTAGE", "TAL_LIGHTNING_STORM_HEART_ENGINE"))
    attacker = _creature(ATTACKER)
    engine = _Engine(rolling=ATTACKER)
    assert plugin.opportunity_attack_mode_against_target(_ctx(engine, attacker), holder) == "DISADVANTAGE"
    assert plugin.opportunity_attack_mode(_ctx(engine, holder), attacker) is None, "the holder's own attacks are not changed"
    engine = _Engine(rolling=None)
    assert plugin.opportunity_attack_mode_against_target(_ctx(engine, attacker), holder) is None


def test_the_attack_that_uses_a_next_condition_up_spends_only_the_matching_side():
    attacker = _creature(ATTACKER, (None, "DISADVANTAGE", "ability:turn_the_foot"))
    holder = _creature(HOLDER, ("target", "DISADVANTAGE", "TAL_LIGHTNING_STORM_HEART_ENGINE"))
    engine = _Engine(rolling=ATTACKER)
    engine.state.actors = {ATTACKER: attacker, HOLDER: holder}
    plugin.opportunity_attack_spent(engine, "ATTACK_ROLLED", {"actor_id": ATTACKER, "target_ids": (HOLDER,)})
    assert engine.removed == [(ATTACKER, CONDITION, "ability:turn_the_foot"), (HOLDER, CONDITION, "TAL_LIGHTNING_STORM_HEART_ENGINE")]


def test_a_non_opportunity_attack_spends_nothing():
    holder = _creature(HOLDER, ("target", "DISADVANTAGE", "TAL_LIGHTNING_STORM_HEART_ENGINE"))
    engine = _Engine(rolling=None)
    engine.state.actors = {HOLDER: holder}
    plugin.opportunity_attack_spent(engine, "ATTACK_ROLLED", {"actor_id": ATTACKER, "target_ids": (HOLDER,)})
    assert engine.removed == []


def test_target_side_tooltip_says_the_attack_is_made_against_the_creature():
    row = {"condition_id": CONDITION, "source_definition_id": "TAL_LIGHTNING_STORM_HEART_ENGINE"}
    data = {"rule": {"opportunity_attack_mode": {"mode": "DISADVANTAGE", "next": True, "side": "target",
                                                  "source_ability": "Storm-Heart Engine"}}}
    reading = generated_status_text.describe(SimpleNamespace(action_catalog={}, state=SimpleNamespace(actors={})), None, row, data)
    assert reading["text"].startswith("Disadvantage on the next Opportunity Attack made against it"), reading["text"]
    assert reading["source_ability"] == "Storm-Heart Engine"
