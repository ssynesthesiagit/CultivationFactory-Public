"""Mirror Trail review regressions through table commits and cold mechanical replay.

Condition/movement producers are exercised inside an accepted Hold transaction;
native Hide is called rather than fabricating its CHECK_ROLLED payload.
"""
import pytest

from combat.stealth import hide
from combat.typed_executor import bears_mark, mark_condition_id
from tests.worker2_support import OWNER, ALLY, FOE, fixture, reload, settle, turn
from tests.test_a2r04_smoke_sound import (
    VEIL, TRACE, MIRROR, _smoke_fixture, _resonance_on_hold,
)

CHOICE = "choice:needle.mirror_trail"
DIRECTION = "condition:typed.mirror_trail"
DENSE = "TAL_SMOKE_DENSE_VEIL"


def hold(table, mid, root, picks=None):
    engine = reload(root, mid)
    candidate = next(c for c in engine.legal_candidates() if c.display_name == "Hold position")
    return settle(table, mid, candidate.candidate_id, picks=picks)


def directions(engine):
    return [c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == DIRECTION]


@pytest.mark.parametrize("decline", [False, True])
def test_native_hide_off_turn_owner_can_accept_or_decline(tmp_path, monkeypatch, decline):
    from tests.h1_support import sheet

    foe_sheet = sheet([])
    foe_sheet["ability_scores_and_statistics"]["skills"] = [{"skill": "Stealth", "bonus": 50}]
    _, table, mid = fixture(tmp_path, [VEIL, TRACE, MIRROR, DENSE], foe_sheet=foe_sheet,
                            foe_position={"x": 3, "y": 5}, seed="NATIVE-HIDE")
    engine = reload(tmp_path, mid)
    veil = next(c for c in engine.legal_candidates() if c.display_name.startswith("Smoke Veil")
                and c.destination is not None and (c.destination.x, c.destination.y) == (3, 5))
    settle(table, mid, veil.candidate_id)
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    action = next(c for c in engine.legal_candidates() if c.display_name == "Hide")
    prompts = settle(table, mid, action.candidate_id, picks={CHOICE: None if decline else "first"})
    choices = [p for p in prompts if p["context"]["reaction_source_id"] == CHOICE]
    assert len(choices) == 1
    assert choices[0]["context"]["reactor_id"] == OWNER
    engine = reload(tmp_path, mid)
    assert bears_mark(engine.state.actors[FOE], OWNER, "Smoke Trace") is (not decline)
    assert bool(directions(engine)) is (not decline)


def test_unrelated_stealth_success_does_not_trace(tmp_path, monkeypatch):
    _, table, mid = _smoke_fixture(tmp_path)

    def trigger(engine):
        engine._append_event("CHECK_ROLLED", "test:soot_escape", actor_id=FOE,
                             payload={"check": "Stealth", "success": True, "total": 30})

    _resonance_on_hold(monkeypatch)(trigger)
    assert not any(p["context"]["reaction_source_id"] == CHOICE for p in hold(table, mid, tmp_path))
    assert not bears_mark(reload(tmp_path, mid).state.actors[FOE], OWNER, "Smoke Trace")


def test_native_soot_scent_escape_inside_veil_does_not_count_as_hide(tmp_path):
    """Use the actual producer named by review finding 3, not a Hide-like receipt."""
    from tests.h1_support import sheet
    from combat.ext.ironclad_smoke import TRACE_CONDITION

    foe_sheet = sheet([])
    foe_sheet["ability_scores_and_statistics"]["skills"] = [{"skill": "Stealth", "bonus": 50}]
    _, table, mid = fixture(tmp_path, [VEIL, TRACE, MIRROR,
                                      "SMOKE_BASE_SMOKE_RESPONSES", "TAL_SMOKE_SOOT_SCENT_TRAIL"],
                            foe_sheet=foe_sheet, owner_dc=1,
                            foe_position={"x": 3, "y": 5}, seed="NATIVE-SOOT-ESCAPE")
    engine = reload(tmp_path, mid)
    veil = next(c for c in engine.legal_candidates() if c.display_name.startswith("Smoke Veil")
                and c.destination is not None and (c.destination.x, c.destination.y) == (3, 5))
    settle(table, mid, veil.candidate_id)
    engine = reload(tmp_path, mid)
    placed = next(c for c in engine.legal_candidates() if c.display_name == "Place Smoke Trace"
                  and FOE in c.target_ids)
    settle(table, mid, placed.candidate_id)
    engine = reload(tmp_path, mid)
    assert bears_mark(engine.state.actors[FOE], OWNER, "Smoke Trace")
    follow = next(c for c in engine.legal_candidates() if c.display_name == "Follow the Soot"
                  and FOE in c.target_ids)
    settle(table, mid, follow.candidate_id)
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == TRACE_CONDITION for c in engine.state.actors[OWNER].conditions.values())
    sequence = engine.state.event_sequence
    prompts = settle(table, mid, table.state(mid)["menu"]["end_turn"],
                     picks={"choice:needle.soot_scent_escape": "first"})
    engine = reload(tmp_path, mid)
    assert any(e.sequence > sequence and e.event_type == "CHECK_ROLLED"
               and e.payload.get("check") == "Stealth" and e.payload.get("success")
               for e in engine.events)
    assert not any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    assert not bears_mark(engine.state.actors[FOE], OWNER, "Smoke Trace")
    assert not any(c.condition_id == TRACE_CONDITION for c in engine.state.actors[OWNER].conditions.values())


def test_the_promised_direction_is_shown_and_follows_the_traced_creature(tmp_path, monkeypatch):
    """Review finding 2: "you know the direction to the target" is actually told to the owner.

    The card the table shows for the owner's record must carry the real bearing (the foe stands five squares
    north of the owner when it vanishes), the owner's own view (the player's and the model seat's) must
    carry the same fact, and the printed 120-foot reach must gate it: beyond that distance the clause
    supplies no direction, and it comes back when the creature is inside again. The record grants the
    direction only, so neither the card nor the owner's fact states the traced creature's distance, inside
    the reach or beyond it. The trace itself is untouched either way, and an ally never receives the
    owner's private direction.
    """
    from combat import information_results, status_text
    from combat.gate2_runtime_models import Position

    _, table, mid = _smoke_fixture(tmp_path)

    def vanish(engine):
        engine._apply_condition(engine.state.actors[FOE], "condition:typed.invisible", "test:vanish", FOE,
                                expires_on="UNTIL_REMOVED")

    _resonance_on_hold(monkeypatch)(vanish)
    hold(table, mid, tmp_path)
    engine = reload(tmp_path, mid)
    holder = engine.state.actors[OWNER]
    record = next(c for c in directions(engine) if c.data["target_id"] == FOE)
    name = engine.state.actors[FOE].display_name

    card = status_text.describe(engine, holder, record.model_dump(mode="json"), dict(record.data), {}, {})
    written = " ".join(str(value) for value in card.values())
    assert name in written and "north" in written, written
    assert "feet away" not in written, f"the record grants the direction, never the distance: {written}"
    assert "120" in written, f"the card states the reach it works within: {written}"

    own_view = table.state(mid, fog=True, fog_view="own", fog_actor_ids=(OWNER,))
    lines = own_view["fog_perception"][OWNER].get("information_text", [])
    trail_facts = [line for line in lines if line.startswith("Smoke Mirror Trail:")]
    assert trail_facts and all("north" in line for line in trail_facts), lines
    assert not any("feet away" in line for line in trail_facts), trail_facts
    ally_view = table.state(mid, fog=True, fog_view="own", fog_actor_ids=(ALLY,))
    assert not any("Smoke Mirror Trail" in str(line)
                   for line in ally_view["fog_perception"][ALLY].get("information_text", []))

    # Beyond the printed reach no direction and no distance are supplied; the trace and its record are untouched.
    far = Position(x=engine.state.actors[FOE].position.x, y=engine.state.actors[OWNER].position.y + 25)
    engine.state.actors[FOE].position = far
    far_card = status_text.describe(engine, holder, record.model_dump(mode="json"), dict(record.data), {}, {})
    far_written = " ".join(str(value) for value in far_card.values())
    assert "beyond" in far_written and "north" not in far_written, far_written
    assert "feet away" not in far_written and "125" not in far_written, \
        f"out of reach still discloses the tracking distance: {far_written}"
    far_facts = [row["text"] for row in information_results.for_observer(engine, holder)
                 if row.get("ability") == "Smoke Mirror Trail"]
    assert far_facts and "north" not in " ".join(far_facts), far_facts
    assert not any("feet away" in text or "125" in text for text in far_facts), far_facts
    assert directions(engine), "being out of reach does not end the trace"
    # Back inside the reach the direction is supplied again.
    engine.state.actors[FOE].position = Position(x=3, y=5)
    back_card = status_text.describe(engine, holder, record.model_dump(mode="json"), dict(record.data), {}, {})
    assert "north" in " ".join(str(value) for value in back_card.values())


def test_multiple_targets_replacement_and_exact_trace_end(tmp_path, monkeypatch):
    _, table, mid = _smoke_fixture(tmp_path, dense=False, extra=["SMOKE_BASE_SMOKE_RESPONSES"])
    phase = ["place"]

    def trigger(engine):
        if phase[0] == "place":
            for aid in (FOE, ALLY):
                engine._apply_condition(engine.state.actors[aid], "condition:typed.invisible",
                                        "test:vanish", aid, expires_on="UNTIL_REMOVED")
                engine._remove_condition(engine.state.actors[aid], "condition:typed.invisible", "test:visible")
        elif phase[0] == "replace":
            engine._apply_condition(engine.state.actors[FOE], "condition:typed.invisible",
                                    "test:vanish", FOE, expires_on="UNTIL_REMOVED")
            engine._remove_condition(engine.state.actors[FOE], "condition:typed.invisible", "test:visible")

    _resonance_on_hold(monkeypatch)(trigger)
    hold(table, mid, tmp_path)
    engine = reload(tmp_path, mid)
    assert {c.data["target_id"] for c in directions(engine)} == {FOE, ALLY}
    assert all(c.expires_on == "UNTIL_REMOVED" for c in directions(engine))
    prior = next(c.data["trace_instance_id"] for c in directions(engine) if c.data["target_id"] == FOE)
    phase[0] = "replace"
    turn(table, mid, ALLY)  # a fresh Hold; the owner's first Hold spent movement
    hold(table, mid, tmp_path)
    engine = reload(tmp_path, mid)
    assert len(directions(engine)) == 2
    assert next(c.data["trace_instance_id"] for c in directions(engine) if c.data["target_id"] == FOE) != prior
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert len(directions(engine)) == 2  # survives the marker's next turn start
    follow = next(c for c in engine.legal_candidates() if c.display_name == "Follow the Soot"
                  and FOE in c.target_ids)
    settle(table, mid, follow.candidate_id)
    engine = reload(tmp_path, mid)
    assert {c.data["target_id"] for c in directions(engine)} == {ALLY}
    assert bears_mark(engine.state.actors[ALLY], OWNER, "Smoke Trace")
    # The other target's trace reaches its actual marker-next-turn end. Its
    # direction has no independent deadline: the trace removal must clean it.
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    engine = reload(tmp_path, mid)
    assert not bears_mark(engine.state.actors[ALLY], OWNER, "Smoke Trace")
    assert not directions(engine)


def test_overlapping_veil_owners_are_asked_independently(tmp_path, monkeypatch):
    from tests.h1_support import sheet

    foe_sheet = sheet([])
    foe_sheet["ability_scores_and_statistics"]["skills"] = [{"skill": "Stealth", "bonus": 50}]
    # Both light veils can be placed with line of sight. Making the first veil
    # Dense would correctly prevent the second caster from seeing this square.
    _, table, mid = fixture(tmp_path, [VEIL, TRACE, MIRROR],
                            ally_talents=[VEIL, TRACE, MIRROR],
                            foe_sheet=foe_sheet, foe_position={"x": 3, "y": 5}, seed="MIRROR-OWNERS")
    for aid in (OWNER, ALLY):
        turn(table, mid, aid)
        engine = reload(tmp_path, mid)
        candidate = next(c for c in engine.legal_candidates()
                         if c.actor_id == aid and c.display_name.startswith("Smoke Veil")
                         and c.destination is not None and (c.destination.x, c.destination.y) == (3, 5))
        settle(table, mid, candidate.candidate_id)
    turn(table, mid, FOE)

    def vanish(engine):
        engine._apply_condition(engine.state.actors[FOE], "condition:typed.invisible", "test:vanish", FOE,
                                expires_on="UNTIL_REMOVED")

    _resonance_on_hold(monkeypatch)(vanish)
    prompts = hold(table, mid, tmp_path, picks={CHOICE: (None, "first")})
    owners = [p["context"]["reactor_id"] for p in prompts if p["context"]["reaction_source_id"] == CHOICE]
    assert len(owners) == 2 and set(owners) == {OWNER, ALLY}
    engine = reload(tmp_path, mid)
    assert not bears_mark(engine.state.actors[FOE], owners[0], "Smoke Trace")
    assert bears_mark(engine.state.actors[FOE], owners[1], "Smoke Trace")


def test_no_owned_mirror_is_default_inert(tmp_path, monkeypatch):
    _, table, mid = fixture(tmp_path, [VEIL, TRACE, DENSE], foe_position={"x": 3, "y": 5})
    engine = reload(tmp_path, mid)
    candidate = next(c for c in engine.legal_candidates() if c.display_name.startswith("Smoke Veil")
                     and c.destination is not None and (c.destination.x, c.destination.y) == (3, 5))
    settle(table, mid, candidate.candidate_id)

    def trigger(engine):
        assert hide(engine, engine.state.actors[FOE], 50, "test:native_hide")

    _resonance_on_hold(monkeypatch)(trigger)
    assert not any(p["context"]["reaction_source_id"] == CHOICE for p in hold(table, mid, tmp_path))
    assert not bears_mark(reload(tmp_path, mid).state.actors[FOE], OWNER, "Smoke Trace")


def test_soot_scent_minute_expires_after_commits_and_reload(tmp_path):
    """Follow the Soot's printed minute ends on the real tenth owner turn."""
    from combat.ext.ironclad_smoke import TRACE_CONDITION

    _, table, mid = fixture(tmp_path, [TRACE, "SMOKE_BASE_SMOKE_RESPONSES",
                                      "TAL_SMOKE_SOOT_SCENT_TRAIL"], owner_dc=50,
                            foe_position={"x": 4, "y": 5}, seed="SOOT-MINUTE")
    engine = reload(tmp_path, mid)
    trace = next(c for c in engine.legal_candidates() if c.display_name == "Place Smoke Trace"
                 and FOE in c.target_ids)
    settle(table, mid, trace.candidate_id)
    engine = reload(tmp_path, mid)
    follow = next(c for c in engine.legal_candidates() if c.display_name == "Follow the Soot"
                  and FOE in c.target_ids)
    settle(table, mid, follow.candidate_id)
    start = reload(tmp_path, mid).state.actors[OWNER].turns_started
    for elapsed in range(1, 11):
        settle(table, mid, table.state(mid)["menu"]["end_turn"])
        turn(table, mid, OWNER)
        engine = reload(tmp_path, mid)
        assert engine.state.actors[OWNER].turns_started == start + elapsed
        assert any(c.condition_id == TRACE_CONDITION
                   for c in engine.state.actors[OWNER].conditions.values()) is (elapsed < 10)
