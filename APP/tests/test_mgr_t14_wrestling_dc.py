"""Whole-row native delivery evidence for Wrestling's default DC definition.

Use learned sphere records and actual table actions, never injected DC metadata.
The unrelated Cultivation DC and other actors' Strength must not set this DC.
"""

import pytest

from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.hunt51_grapple_support import IDS, fight, grapple, on_turn, send, verify_reloaded
from tests.test_mmx115_grapple_escape_dc import fail_every_save


@pytest.mark.parametrize("strength,expected", [(8, 11), (18, 16), (30, 22)])
def test_learned_wrestling_uses_owner_strength_for_slam_and_persisted_hold(tmp_path, monkeypatch, strength, expected):
    owner, victim = IDS[0], IDS[2]
    doc = sheet(["TAL_WRESTLING_HEEL_TACTICS"], cl=18, dc=30, primary="Stamina", score=10)
    for ability in doc["ability_scores_and_statistics"]["abilities"]:
        if ability["ability"] == "STR":
            ability.update(score=strength, modifier=(strength - 10) // 2)
    # Learning the sphere supplies its base definition through the normal build path.
    assert "WRESTLING_BASE_WRESTLING_SAVE_DC_AND_ESCAPE_DC" in doc["spheres_and_talents"]["automatic_sphere_component_record_ids"]
    bundle = compile_character(doc, actor_id=owner, reaction_plan={"ask": True})
    rows = {row["display_name"]: row for row in bundle["action_catalog"]}
    assert rows["Grapple"]["parameters"]["typed"]["numbers"]["save_dc"] == expected
    assert rows["Apply a Slam: Heel Tactics"]["parameters"]["typed"]["numbers"]["save_dc"] == expected

    fail_every_save(monkeypatch)
    user, service, table, match, _ = fight(tmp_path, f"wrestling-dc-{strength}", saved_bundle=bundle)
    on_turn(table, match, owner)
    send(table, match, grapple(victim))
    session = service._load_session(match)
    holds = [c for c in session.engine.state.actors[victim].conditions.values()
             if c.condition_id == "condition:typed.grappled"]
    assert len(holds) == 1
    assert holds[0].source_actor_id == owner
    assert holds[0].data["escape_dc"] == expected
    assert not session.engine.state.actors[IDS[1]].conditions
    verify_reloaded(user, service, match)

    before = len(session.engine.events)
    send(table, match, lambda option: "Apply a Slam: Heel Tactics" in option.get("label", "")
         and option.get("target_ids") == [victim])
    events = service._load_session(match).engine.events[before:]
    saves = [e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == victim]
    assert saves, "The learned Slam must actually roll its saving throw at the table"
    assert all(e.payload["dc"] == expected for e in saves)
    verify_reloaded(user, service, match)
