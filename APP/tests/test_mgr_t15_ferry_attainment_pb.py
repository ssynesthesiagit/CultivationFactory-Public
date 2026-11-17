"""Ferry pays "your Proficiency Bonus", not the Proficiency Bonus of a lower Subpath.

A CL11 character (PB 4) whose Riverway Cultivator is only attained to CL6 still
owns Ferry the Wounded (a CL6 feature) and still reads "your Proficiency Bonus"
on its card, so the arrival reward is 4 Temporary Hit Points. The CL6 attainment
only supplies the numbers a record states as CL tiers.
"""
from copy import deepcopy

from combat.factory_compiler import compile_character
from combat.subpath_acquisition import acquired_features
from tests.h1_support import ROOT
from tests.test_mgr_t14_sol_subpath_ferry_wounded import (
    FERRY, REACTION, acquired, create_passage, damage_ally, wounded_table,
)
from tests.worker2_support import ALLY, OWNER, reload


def mixed_attainment(acquired):
    """The same CL11 / PB 4 / CL6 Riverway sheet the passive regression builds."""
    doc = deepcopy(acquired)
    doc["identity"].update(cultivation_level=11, proficiency_bonus=4)
    path = next(p for p in doc["path_and_subpath"]["paths"]
                if p["path_id"] == "tianxia.path.qi_cultivation")
    path.update(attainment=6, effective_cl=6)
    return doc


def test_ferry_arrival_reward_is_the_characters_pb_below_full_attainment(tmp_path, acquired):
    doc = mixed_attainment(acquired)
    assert acquired_features(doc, ROOT)[FERRY] == {"cl": 6, "min_cl": 6}
    combat, table, mid = wounded_table(tmp_path, acquired=doc)
    create_passage(combat, table, mid)
    engine, events, prompts = damage_ally(combat, table, mid, tmp_path,
                                         choices={REACTION: ["cell:4,7"]})
    assert any(p["context"]["reaction_source_id"] == REACTION for p in prompts)
    ally = engine.state.actors[ALLY]
    assert (ally.position.x, ally.position.y) == (4, 7)
    assert engine.state.actors[OWNER].proficiency_bonus == 4
    reward = next(e for e in events if e.event_type == "TEMP_HP_GRANTED"
                  and e.source_definition_id == FERRY)
    assert reward.payload["after"] == 4
    assert ally.temporary_hp == 4
    # The granted number is stored in the fight, so it survives a cold reload.
    assert reload(tmp_path, mid).state.actors[ALLY].temporary_hp == 4

    # The bundle the fight was built from: the attainment level still drives the
    # numbers a record states as CL tiers, and only those.
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={"ask": True})
    row = next(r for r in bundle["typed_reactions"] if r["feature_id"] == FERRY)
    assert bundle["actor_template"]["proficiency_bonus"] == 4
    assert row["numbers"]["cl"] == 6, "the attainment level still drives CL tiers"
    assert row["numbers"]["pb"] == 4, "the card reads 'your Proficiency Bonus'"
