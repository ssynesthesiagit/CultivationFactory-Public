"""Exactly one shared kind bonus on each committed Resonant Note creature hit."""

import pytest

from tests.h1_support import sheet
from tests.test_a2r04_smoke_sound import NOTE, _candidate, _sure_hit
from tests.worker2_support import OWNER, FOE, fixture, reload, settle


@pytest.mark.parametrize("rider", ["Deafen", "Concentration Disadvantage", "Sound Hiding"])
@pytest.mark.parametrize("construct", [False, True])
def test_note_creature_riders_consume_one_kind_bonus_after_commit_reload(tmp_path, rider, construct):
    foe = sheet([], cl=15)
    foe["identity"]["creature_type"] = "Construct" if construct else "Humanoid"
    _, table, mid = fixture(
        tmp_path, [NOTE], foe_sheet=foe, foe_position={"x": 3, "y": 3},
        seed="A2R04NOTE", bundle_transform=_sure_hit,
    )
    before = reload(tmp_path, mid)
    assert ("construct" in {kind.casefold() for kind in before.state.actors[FOE].creature_types}) is construct
    candidate = _candidate(before, "Resonant Note: " + rider, target=FOE)
    settle(table, mid, candidate.candidate_id)
    after = reload(tmp_path, mid)
    hits = [event for event in after.events if event.sequence > before.state.event_sequence
            and event.event_type == "ATTACK_ROLLED" and event.actor_id == OWNER]
    assert len(hits) == 1 and hits[0].payload["provisional_hit"]
    rolls = [roll for roll in after.rolls if roll.actor_id == OWNER and roll.reason.startswith("DAMAGE")]
    assert len(rolls) == 1
    assert rolls[0].modifier == (4 if construct else 0)
    assert after.state.actors[FOE].current_hp < before.state.actors[FOE].current_hp
