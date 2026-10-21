"""Public, synthetic table replays for the failed SUMMONAI1 review scripts.

Ritual undead start on the table; Bone Guard and paintings use the actual
offered creation labels. No historical repository or live service is needed.
Carry this file unchanged into a baseline evidence commit: failures must name
DODGE versus INSTINCT, never a missing menu option or an unplaced creature.
"""
import pytest

from combat import summons
from combat.gate5_service import CombatService
from tests.test_h47_summon_table import (
    BONE, OWNER, table_fixture, verify_reload,
)

PAINTING = "tianxia.subpath.qi.painting_cultivator.feature.living_painting"


@pytest.mark.parametrize("source,group,creation", [
    (BONE, "bone_guard", "Bone Guard Manifestation"),
    ("TAL_DEATH_ROUSE_LESSER_DEAD", "lesser_corpse_servant", None),
    ("TAL_DEATH_CORPSE_SERVANT", "corpse_servant", None),
    *[(PAINTING, "living_painting_" + form, "Living Painting: " + form.title())
      for form in ("tiger", "crane", "tortoise", "serpent")],
])
def test_manual_owner_uncommanded_turn_on_the_offered_table(tmp_path, source, group, creation):
    combat, table, mid, _, commit = table_fixture(
        tmp_path, wide=True, owner_talents=[source],
        owner_primary="Qi" if source == PAINTING else "Stamina")
    if creation:
        # Public exports translate prose labels. Find the actual offered action
        # from its stable summon-group metadata, never a guessed display name.
        engine = combat._load_session(mid).engine
        actions = {aid for aid, action in engine.action_catalog.items()
                   if action.parameters.get("summon_group") == group}
        legal = next(c for c in engine.legal_candidates() if c.source_definition_id in actions)
        offered = next(option for action in table.state(mid)["menu"]["actions"]
                       for option in action["options"] if option["candidate_id"] == legal.candidate_id)
        commit(offered["candidate_id"])
    before = combat._load_session(mid).engine
    creatures = summons.owned_by(before, OWNER, group)
    assert creatures and all(c.active and c.summon["status"] == "present" for c in creatures)
    ids = {c.entity_id for c in creatures}
    sequence = before.state.event_sequence
    assert table.state(mid)["menu"]["actor_id"] == OWNER
    assert all(not c.summon["commanded"] for c in creatures)
    commit(table.state(mid)["menu"]["end_turn"])

    # Read the committed fight from a fresh service, not the creation objects.
    fresh = CombatService(combat.source_root, tmp_path)._load_session(mid).engine
    events = [e for e in fresh.events if e.sequence > sequence]
    defaults = [e for e in events if e.event_type == "COMPANION_DEFAULT_APPLIED" and e.actor_id in ids]
    assert {e.actor_id for e in defaults} == ids
    turns = [e for e in events if e.event_type == "SUMMON_TURN" and e.actor_id in ids]
    attacks = [e for e in events if e.event_type == "INTENT_ACCEPTED" and e.actor_id in ids and e.target_ids]
    verify_reload(combat, table, mid)
    capture = {"default": [e.payload["behavior"] for e in defaults],
               "turns": [e.payload["text"] for e in turns],
               "attacks": [(e.actor_id, e.source_definition_id, e.target_ids) for e in attacks]}
    assert {e.payload["behavior"] for e in defaults} == {"INSTINCT"}, capture
    assert fresh.state.current_actor_id not in ids, "a manual owner must not have to drive an uncommanded summon"
    assert {e.actor_id for e in turns} == ids, capture
    assert all("acts on instinct:" in e.payload["text"] for e in turns), capture
    assert attacks, ("the visible nearby enemy must be attacked by at least one uncommanded creature", capture)
    assert all(not any(c.condition_id == "condition:core.dodge" for c in fresh.state.actors[cid].conditions.values())
               for cid in ids), capture
