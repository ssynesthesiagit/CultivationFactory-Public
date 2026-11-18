"""A condition or modifier left by one operation keeps the built-in AI from starting that technique again.

A technique can expose several operations through one record (augmented variants, a free and a paid use, a command for a
persistent object). What the actor is still carrying from it -- a condition or an unconsumed modifier -- is the technique
still doing its work, so the AI does not spend another activation while one is up (combat/ext/ai_restraint.py _allowed;
fight audit 2026-09-29 "the built-in AI stops casting again what is still up"). Zones are the deliberate exception: a
later operation that directs the existing object is not a second activation, so only that check compares the two
operations' effects.

MGR-T14 review 2026-10-14 (RB1R blocking 1): the Dust branch had widened the condition and modifier checks to compare
effect lists too, so a sibling operation could refresh while the technique was still running. These tests pin the
technique-wide restraint and its other-technique control."""

from combat.ext import ai_restraint
from combat.gate2_runtime_models import ActionDefinition, ModifierInstance
from tests.test_auto_docket import DARK, ME, _fight, _sheet

TECHNIQUE = "tianxia.test.ai_restraint.technique"
BUFF = "action:test.ai_restraint.buff"
OTHER = "action:test.ai_restraint.other"


class Candidate:
    def __init__(self, source):
        self.source_definition_id = source
        self.metadata = {}


def _engine_with_two_operations():
    """One self-only buff and one area operation of the same technique, as the compiler writes an augmented record."""
    engine = _fight(_sheet([*DARK]))
    engine.action_catalog[BUFF] = ActionDefinition(
        source_definition_id=BUFF, display_name="Test Buff", owner_id=ME, economy="ACTION",
        resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"source": TECHNIQUE, "duration": {"kind": "instant"},
                              "effects": [{"type": "temp_hp", "applies_to": "self"}]}})
    engine.action_catalog[OTHER] = ActionDefinition(
        source_definition_id=OTHER, display_name="Test Other", owner_id=ME, economy="ACTION",
        resolution_kind="TYPED", target_kind="CELL",
        parameters={"typed": {"source": TECHNIQUE, "duration": {"kind": "instant"},
                              "effects": [{"type": "damage", "applies_to": "enemies_in_area"}]}})
    return engine, engine.state.actors[ME]


def test_a_live_condition_from_a_sibling_operation_blocks_recasting_the_technique():
    engine, me = _engine_with_two_operations()
    engine._apply_condition(me, "condition:typed.test_ai_restraint", OTHER, ME,
                            expires_on="UNTIL_REMOVED", data={})
    buff = engine.action_catalog[BUFF]
    assert ai_restraint.restraint(engine, me, Candidate(BUFF), buff) is False


def test_an_unconsumed_modifier_from_a_sibling_operation_blocks_recasting_the_technique():
    engine, me = _engine_with_two_operations()
    me.modifiers["test:ai-restraint:other"] = ModifierInstance(
        modifier_id="test:ai-restraint:other", source_definition_id=OTHER, source_actor_id=ME, target_id=ME,
        target_field="armor_class", operation="add", value=1, applies_to="self",
        expires_on="UNTIL_REMOVED", consumed=False)
    buff = engine.action_catalog[BUFF]
    assert ai_restraint.restraint(engine, me, Candidate(BUFF), buff) is False


def test_a_condition_from_another_technique_leaves_the_buff_alone():
    engine, me = _engine_with_two_operations()
    engine._apply_condition(me, "condition:typed.test_ai_restraint", "action:test.other_technique", ME,
                            expires_on="UNTIL_REMOVED", data={})
    buff = engine.action_catalog[BUFF]
    assert ai_restraint.restraint(engine, me, Candidate(BUFF), buff) is None
