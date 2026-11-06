"""Native Weather base-row checks; ambient/forecast/object coverage stays open.

Every commit helper cold-loads the actual saved table and verifies native replay.
Weather facts below come from acquired and cast abilities, never injected flags.
"""
import pytest

from combat.ext import weather_reading as reading
from tests.test_auto13_weather import (
    ALLY, FOE, FOE2, ME, SPHERE, SHROUD_TALENTS, action, arena, choose_shroud,
    commit, mantle_chooser, next_owner_turn, owner_turn, shroud_of,
)


def readings(combat, mid, actor=ME):
    return [e for e in combat._load_session(mid).engine.events
            if e.source_definition_id == reading.BASE and e.actor_id == actor
            and e.payload.get("reading") == "battle"]


def reading_prompts(prompts):
    return [p for p in prompts if p["context"]["reaction_source_id"] == reading.CHOICE_ID]


@pytest.mark.parametrize("decline", [False, True])
def test_shroud_cast_offers_optional_free_battle_reading_and_reloads(tmp_path, decline):
    combat, table, mid = arena(tmp_path, SPHERE, "battle-shroud" + str(decline), dc=40,
                               ask_actors=(ALLY, FOE, FOE2))
    owner_turn(combat, table, mid, tmp_path, idle=True)
    e = combat._load_session(mid).engine
    # Native sphere acquisition grants both base abilities, only to the owner.
    for source in (reading.BASE, "WEATHER_BASE_CLOUD_SHROUD"):
        assert any((e.action_catalog[aid].parameters.get("typed") or {}).get("source") == source
                   for aid in e.state.actors[ME].action_ids)
        assert not any((e.action_catalog[aid].parameters.get("typed") or {}).get("source") == source
                       for aid in e.state.actors[FOE].action_ids)
    before = e.state.actors[ME].resources["resource:core.qi"]
    prompts = []

    def choose(prompt):
        if prompt["context"]["reaction_source_id"] == reading.CHOICE_ID:
            return None if decline else ["heat"]
        return choose_shroud("heat")(prompt)

    commit(combat, table, mid, tmp_path,
           action(combat, mid, "Cloud Shroud (any creature)", FOE), choose=choose, prompts=prompts)
    e = combat._load_session(mid).engine
    offered = reading_prompts(prompts)
    assert len(offered) == 1
    assert [o["id"] for o in offered[0]["choice"]["options"]] == ["heat"]
    assert "Cloud Shroud" in str(offered[0]) and "You" in str(offered[0])
    assert "No additional action or Cultivation Points" in str(offered[0])
    assert e.state.actors[ME].resources["resource:core.qi"] == before - 1
    assert shroud_of(e)[0].data["sign"] == "heat"
    assert len(readings(combat, mid)) == (0 if decline else 1)
    if not decline:
        assert readings(combat, mid)[0].payload["sign"] == "heat"
    # The spent Action cannot be used again by the no-action reading.
    assert not any(c.display_name == "Cloud Shroud (any creature)" for c in e.legal_candidates())


def test_mantle_and_persistent_shroud_keep_every_owned_sign_reachable(tmp_path):
    combat, table, mid = arena(tmp_path, SHROUD_TALENTS, "battle-multiple", dc=40,
                               ask_actors=(ALLY, FOE, FOE2))
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path,
           action(combat, mid, "Cloud Shroud (any creature) + Persistent Shroud", FOE),
           choose=choose_shroud("heat"))
    next_owner_turn(combat, table, mid, tmp_path)
    prompts = []
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ME),
           choose=mantle_chooser("wind"), prompts=prompts)
    offered = reading_prompts(prompts)
    assert len(offered) == 1
    assert {o["id"] for o in offered[0]["choice"]["options"]} == {"wind", "heat"}
    assert readings(combat, mid)[-1].payload["sign"] == "wind"


def test_gather_is_a_real_battle_reading_fact_and_reading_does_not_retrigger(tmp_path):
    from tests.test_a2_weather import choices

    combat, table, mid = arena(tmp_path, SPHERE, "battle-gather", dc=40,
                               ask_actors=(ALLY, FOE, FOE2))
    owner_turn(combat, table, mid, tmp_path, idle=True)
    e = combat._load_session(mid).engine
    cid = next(c.candidate_id for c in e.legal_candidates()
               if c.display_name.startswith("Gather Weather at") and c.destination is not None
               and (c.destination.x, c.destination.y) == (4, 6))
    prompts = []
    commit(combat, table, mid, tmp_path, cid, choose=choices("cold"), prompts=prompts)
    assert [o["id"] for o in reading_prompts(prompts)[0]["choice"]["options"]] == ["cold"]
    assert readings(combat, mid)[-1].payload["sign"] == "cold"
    count = len(readings(combat, mid))
    next_owner_turn(combat, table, mid, tmp_path)
    prompts = []
    commit(combat, table, mid, tmp_path, action(combat, mid, "Read the Sky", ME), prompts=prompts)
    assert not reading_prompts(prompts)
    assert len(readings(combat, mid)) == count


def test_opponents_placements_are_not_borrowed_as_personal_weather_facts(tmp_path):
    combat, table, mid = arena(tmp_path, SPHERE, "battle-boundary", dc=40,
                               ask_actors=(ALLY, FOE, FOE2), foe_talents=SPHERE)
    # Reach the foe's own turn and cast through the table as that real owner.
    for _ in range(8):
        e = combat._load_session(mid).engine
        if e.state.current_actor_id == FOE:
            break
        commit(combat, table, mid, tmp_path,
               next(c.candidate_id for c in e.legal_candidates() if c.kind.value == "END_TURN"))
    assert combat._load_session(mid).engine.state.current_actor_id == FOE
    commit(combat, table, mid, tmp_path, action(combat, mid, "Cloud Shroud (any creature)", ALLY),
           choose=choose_shroud("heat"))
    assert readings(combat, mid, FOE)[-1].payload["sign"] == "heat"
    owner_turn(combat, table, mid, tmp_path, idle=True)
    prompts = []
    commit(combat, table, mid, tmp_path, action(combat, mid, "Cloud Shroud (any creature)", FOE2),
           choose=choose_shroud("cold"), prompts=prompts)
    assert [o["id"] for o in reading_prompts(prompts)[0]["choice"]["options"]] == ["cold"]
    assert readings(combat, mid)[-1].payload["sign"] == "cold"
