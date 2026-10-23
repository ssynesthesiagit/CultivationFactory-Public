"""Hunt 79 #4 (MMX57): the player battle log must state a duration once, in plain words.

The bug: a poison-resistance modifier whose record carried no expiry clock fell through to the
developer's own fallback strings, so the player log read

    "Peng Xilan: resistance to POISON from Poison Burst; duration not recorded."
    "Peng Xilan applied Save Against to Peng Xilan (Poison Burst); until Peng Xilan's next turn ends."

Two adjacent lines contradicting each other, with bookkeeping ("duration not recorded") in the
middle. The real duration was on the second line the whole time.

These tests drive the shipped rendering path (``format_history_feed``, the same function the
tabletop service uses for the player-visible feed) and a real table fight.
"""

from __future__ import annotations

from combat.history_feed import format_history_feed
from combat.history_text import duration_clause, expiry_text

BOOKKEEPING = ("duration not recorded", "expiry not described in this record", "not described in this record")

PENG = "actor:factory.peng"
FOE = "actor:factory.foe"
SOURCE = "action:typed.aa.forged.bb"


def _row(event_type, payload, *, source=SOURCE, actor=PENG, targets=(FOE,)):
    return {
        "sequence": 1,
        "event_type": event_type,
        "source_definition_id": source,
        "trigger_or_intent_id": source,
        "transaction_id": "tx",
        "actor_id": actor,
        "target_ids": list(targets),
        "payload": payload,
    }


def _modifier(field, value, expires_on, operation="ADD"):
    """A MODIFIER_APPLIED record shaped exactly like the ones the engine writes.

    The affected creature is the caster, as in H79-P03 (a self-granted resistance).
    """
    return _row("MODIFIER_APPLIED", {
        "expires_on": expires_on,
        "gate3_modifier_after": {
            "modifier_id": "modifier:action:typed.aa.forged.bb:1",
            "target_field": field,
            "value": value,
            "operation": operation,
            "expires_on": expires_on,
        },
    }, targets=(PENG,))


def _summaries(rows):
    return [item["summary"] for item in format_history_feed(
        rows,
        [],
        pre_state=None,
        post_state={"actors": {}},
        actor_names={PENG: "Peng Xilan", FOE: "Lingfeng Frostblade"},
        definition_names={SOURCE: "Poison Burst"},
    )]


def test_unrecorded_expiry_renders_as_no_duration_clause_at_all():
    """An expiry the engine never recorded must not be described as bookkeeping."""
    assert expiry_text(None, {}, "Peng Xilan", "Peng Xilan") is None
    assert expiry_text("", {}, "Peng Xilan", "Peng Xilan") is None
    assert expiry_text("SOME_TOKEN_THIS_BUILD_DOES_NOT_USE", {}, "Peng Xilan", "Peng Xilan") is None
    assert duration_clause(None) == ""
    # A recorded clock still reads plainly.
    assert expiry_text("END_OF_HOLDER_NEXT_TURN", {}, "Peng Xilan", "Peng Xilan") == "until Peng Xilan's next turn ends"


def test_poison_resistance_without_a_clock_does_not_contradict_the_condition_line():
    """The exact pair from H79-P03: a modifier with no clock, then a condition with one."""
    condition = _row("CONDITION_APPLIED", {
        "condition_id": "condition:typed.save_against",
        "expires_on": "END_OF_HOLDER_NEXT_TURN",
        "gate3_condition_after": {
            "condition_id": "condition:typed.save_against",
            "expires_on": "END_OF_HOLDER_NEXT_TURN",
            "data": {"label": "Advantage on saving throws against Poisoned and ordinary poison"},
        },
    }, targets=(PENG,))
    lines = _summaries([_modifier("damage_resistance", "POISON", None), condition])

    assert lines[0] == "Peng Xilan: resistance to POISON from Poison Burst."
    assert lines[1].endswith("until Peng Xilan's next turn ends.")
    # The real duration is stated exactly once, on the line that recorded it.
    assert [line for line in lines if "next turn ends" in line] == [lines[1]]
    for line in lines:
        for phrase in BOOKKEEPING:
            assert phrase not in line


def test_unreadable_modifier_field_is_still_plain_player_text():
    """A modifier this build cannot classify must not leak 'this record' wording either."""
    lines = _summaries([_modifier("some_future_field", 3, None)])
    assert lines == ["Poison Burst affects Peng Xilan."]
    for phrase in BOOKKEEPING:
        assert phrase not in lines[0]


def test_a_recorded_clock_is_still_shown_on_the_modifier_line():
    """Guarding against over-correcting: a known duration must still be printed."""
    lines = _summaries([_modifier("damage_resistance", "POISON", "CONCENTRATION_END")])
    assert lines[0] == "Peng Xilan: resistance to POISON from Poison Burst; until concentration ends."


def test_no_battle_log_line_leaks_duration_bookkeeping(tmp_path):
    """Table level: play a real fight and read the player-visible feed the players read."""
    from tests.test_tabletop_hunt8 import cast_lava, fight

    combat, table, mid = fight(tmp_path, [], caster_talents=["TAL_MAGMA_LAVA_FLOW"])
    cast_lava(combat, table, mid)
    state = table.state(mid)
    assert state['menu']['decision_id'] == combat.decision(mid)['context']['decision_id'], \
        'reading live defenses must not append events and invalidate the displayed menu'
    table.act(mid, state["menu"]["end_turn"], state["menu"]["decision_id"],
              state["menu"]["state_version"], state["last_sequence"], [])
    rows = table.events(mid, 0)["events"]
    assert rows
    assert not any('combat.ext.banner' in row['summary'] for row in rows), \
        'a scalar placement stamp must not produce Banner errors on a character without its ability'
    for row in rows:
        for phrase in BOOKKEEPING:
            assert phrase not in row["summary"], row["summary"]
    # Every printed line is a finished sentence a newcomer can read.
    assert all(row["summary"].endswith(".") for row in rows)
