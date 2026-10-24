"""DEFDISC1 saved fights (F6R finding 4): a fight saved by the old build may still hold a
condition:typed.defensive_discipline:* instance. The Discipline is no longer a fight condition, so that instance must be
inert: the rule table has no row for it, so it grants nothing and the reads do not fail.

Limit: an instance cannot be written into a journal by hand, so this test injects it into a loaded fight. It covers the
read path a saved instance would take; it does not prove a file written by the old build reloads byte-for-byte."""
from combat.gate2_runtime_models import ConditionInstance
from combat.typed_executor import condition_rule_instances
from tests.hunt15_support import LEFT, fight

ORPHAN = "condition:typed.defensive_discipline:tempered_response"


def test_an_orphaned_discipline_condition_in_a_saved_fight_grants_no_rule(tmp_path):
    combat, table, mid = fight(tmp_path)
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[LEFT]
    actor.conditions["condition-instance:orphan:old-build"] = ConditionInstance(
        instance_id="condition-instance:orphan:old-build", condition_id=ORPHAN,
        source_definition_id="action:old.defensive_discipline", source_actor_id=LEFT, target_id=LEFT,
        applied_sequence=1, expires_on=None, data={})
    rows = [row for condition, row in condition_rule_instances(actor, engine=engine) if condition.condition_id == ORPHAN]
    assert rows == [{}]
