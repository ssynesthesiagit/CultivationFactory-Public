"""Hunt DS12 #1-#2: reroll/retry prompts say what failed, and no dead log placeholders.

Both regressions are about the *text the table shows a player*, so these tests
call the two generators that build it: ``combat/decision_text.trigger_text`` for the
Ask-me prompt and ``combat/history_feed.format_history_feed`` for the battle log.

Evidence (live build 65cf60c9, hunt-ds12 ``m1-manual-09``): three Ask-me prompts with
checkpoint ``TYPED:D20_REROLL_SAVE`` and reaction Indomitable Body read
"Zeng Jingxing has made a saving throw for He Zhenbo." -- no failure stated, and no
ability at all for the Concentration save they answered.
"""
from combat.decision_text import trigger_text
from combat.history_feed import format_history_feed

ACTORS = {"actor:mei": "Zeng Jingxing", "actor:foe": "He Zhenbo"}
ME, FOE = "actor:mei", "actor:foe"
PLACEHOLDER = "Detailed breakdown was not recorded"

# A Concentration save is rolled by the holder, against the source that broke it.
CONCENTRATION = {
    "checkpoint": "TYPED:D20_REROLL_SAVE@399",
    "choice_trigger": {"roll_kind": "save", "source_definition_id": "system:combat.concentration",
                       "action_actor_id": FOE, "affected_id": ME},
    "recent_events": [{"event_type": "SAVE_ROLLED", "actor_id": ME,
                       "source_definition_id": "system:combat.concentration", "target_ids": [ME],
                       "payload": {"ability": "CON", "dc": 16, "success": False, "roll_id": "r-9"}}],
}
PROMPT = {"reactor": ME, "reaction": "Indomitable Body", "trigger_actor": "He Zhenbo", "by": "He Zhenbo",
          "moment": "fails a saving throw (may reroll it)"}


def _feed(events):
    return format_history_feed(events, [], pre_state=None, post_state={"round_number": 1},
                               actor_names=ACTORS, definition_names={})


def test_concentration_reroll_prompt_says_the_save_failed_and_names_the_ability():
    text = trigger_text(CONCENTRATION, PROMPT, ACTORS, {})
    # The printed rule is "when you fail a saving throw": the prompt must say it failed.
    assert "failed" in text
    assert "has made" not in text
    # A Concentration save is a Constitution save; the prompt must say which one and what for.
    assert "Constitution" in text and "keep concentrating" in text
    assert "DC 16" in text and "He Zhenbo" in text
    # Newcomer-readable: no ids, no namespaces, no raw tokens.
    assert "actor:" not in text and "system:" not in text and "TYPED" not in text
    assert text.startswith("Zeng Jingxing ") and text.endswith(".")


def test_reroll_prompt_uses_the_recorded_ability_and_dc():
    context = {"checkpoint": "TYPED:D20_REROLL_SAVE@1",
               "choice_trigger": {"roll_kind": "save", "source_definition_id": "typed:some.hazard",
                                  "action_actor_id": FOE, "affected_id": ME},
               "recent_events": [{"event_type": "SAVE_ROLLED", "actor_id": ME, "target_ids": [ME],
                                  "source_definition_id": "typed:some.hazard",
                                  "payload": {"ability": "DEX", "dc": 13, "success": False}}]}
    text = trigger_text(context, PROMPT, ACTORS, {})
    assert "failed a Dexterity saving throw" in text and "DC 13" in text


def _roll_prompt(roll_kind, moment, **carried):
    """The reroll/rewrite prompt as the consent transport builds it (``ext/d20_rewrite.roll_scope``).

    ``target_id`` is the creature whose roll it is -- the transport deliberately puts the roller there --
    and the roll's own identity and result travel beside it.
    """
    roller = carried.pop("roller", ME)
    trigger = {"roll_kind": roll_kind, "target_id": roller, "roll_record_id": "roll:00000009",
               "roll_roller_id": roller, "roll_outcome": "unknown", "roll_guarantee": "unknown", **carried}
    return ({"checkpoint": f"TYPED:{moment}@9", "choice_trigger": trigger, "recent_events": []},
            {"reactor": ME, "reaction": "R"})


def test_the_roll_the_prompt_carries_wins_over_an_earlier_one_in_the_journal():
    """The journal's newest save may be a different roll; the prompt describes the one it carries."""
    context = {"checkpoint": "TYPED:D20_REROLL_SAVE@2",
               "choice_trigger": {"roll_kind": "save", "target_id": ME, "roll_record_id": "roll:00000009",
                                  "roll_roller_id": ME, "roll_ability": "DEX", "roll_dc": 60,
                                  "roll_outcome": "failure", "roll_guarantee": "failure"},
               "recent_events": [{"event_type": "SAVE_ROLLED", "actor_id": ME, "target_ids": [ME],
                                  "source_definition_id": "typed:other.hazard",
                                  "payload": {"ability": "WIS", "dc": 5, "success": True}}]}
    text = trigger_text(context, {"reactor": ME, "reaction": "R"}, ACTORS, {})
    assert text == "Zeng Jingxing failed a Dexterity saving throw (DC 60)."
    assert "Wisdom" not in text and "DC 5" not in text


def test_a_successful_roll_is_reported_as_a_success_and_never_as_a_failure():
    context, prompt = _roll_prompt("save", "D20_REWRITE_ROLL", roll_ability="CON", roll_dc=16,
                                   roll_outcome="success", source_definition_id="system:combat.concentration")
    text = trigger_text(context, prompt, ACTORS, {})
    assert text == "Zeng Jingxing succeeded at a Constitution saving throw to keep concentrating (DC 16)."
    assert "failed" not in text


def test_a_roll_the_table_cannot_read_is_never_guessed_at():
    """Nothing is said about how a roll went unless the table can read it or the rule promises it."""
    context, prompt = _roll_prompt("save", "D20_REWRITE_ROLL", roll_ability="CON", roll_dc=16,
                                   source_definition_id="system:combat.concentration")
    text = trigger_text(context, prompt, ACTORS, {})
    assert "failed" not in text and "succeeded" not in text
    assert text == "Zeng Jingxing made a Constitution saving throw to keep concentrating (DC 16); this prompt is about that roll."

    # A rule that fires on a failed save says so even with an unreadable result; one that fires on any roll promises nothing.
    promised, promised_prompt = _roll_prompt("save", "D20_REROLL_SAVE", roll_guarantee="failure")
    assert "failed" in trigger_text(promised, promised_prompt, ACTORS, {})
    any_roll, any_prompt = _roll_prompt("save", "D20_REWRITE_ROLL", roll_guarantee="unknown")
    assert "failed" not in trigger_text(any_roll, any_prompt, ACTORS, {})


def test_an_attack_prompt_names_the_attacker_and_the_creature_it_was_rolled_against():
    """The transport's target is the roller, so the creature that was hit comes from the roll itself."""
    context, prompt = _roll_prompt("attack", "D20_REROLL_ATTACK", roller=FOE, roll_victim_id=ME,
                                   roll_outcome="success", roll_guarantee="success")
    said = trigger_text(context, prompt, ACTORS, {})
    assert said == "He Zhenbo's attack roll against Zeng Jingxing hit."
    assert "was hit" not in said and "missed" not in said
    # A missed attack roll is a miss, not a hit on the attacker.
    missed, missed_prompt = _roll_prompt("attack", "D20_REROLL_ATTACK", roller=FOE, roll_victim_id=ME,
                                         roll_outcome="failure")
    assert trigger_text(missed, missed_prompt, ACTORS, {}) == "He Zhenbo's attack roll against Zeng Jingxing missed."


def test_a_check_prompt_reports_its_own_result():
    context, prompt = _roll_prompt("check", "D20_REROLL_CHECK", roll_ability="WIS", roll_dc=15,
                                   roll_outcome="failure")
    assert trigger_text(context, prompt, ACTORS, {}) == "Zeng Jingxing failed a Wisdom ability check (DC 15)."


def test_a_pending_roll_is_still_announced_before_it_is_rolled():
    """The reroll fix must not turn a before-the-roll prompt into a result."""
    pending = {"checkpoint": "TYPED:D20_PENDING@5",
               "choice_trigger": {"roll_kind": "save", "save_ability": "WIS", "action_actor_id": FOE, "affected_id": ME},
               "recent_events": []}
    text = trigger_text(pending, PROMPT, ACTORS, {})
    assert "is about to make" in text and "Wisdom saving throw" in text
    assert "failed" not in text


def test_a_scope_that_carries_no_roll_at_all_says_the_roll_and_nothing_more():
    """With neither a carried roll nor a rule promise, the prompt states the roll and stops."""
    bare = {"checkpoint": "TYPED:D20_REROLL_SAVE@1",
            "choice_trigger": {"roll_kind": "save", "affected_id": ME}, "recent_events": []}
    text = trigger_text(bare, {"reactor": ME, "reaction": "R"}, ACTORS, {})
    assert "Zeng Jingxing made a saving throw" in text
    assert "failed" not in text and "succeeded" not in text
    assert "DC" not in text  # nothing invented


def test_a_source_mismatched_history_roll_cannot_supply_a_concentration_result():
    """A metadata-free scope must not borrow another source's ability, DC or outcome."""
    context = {"checkpoint": "TYPED:D20_REROLL_SAVE@2",
               "choice_trigger": {"roll_kind": "save", "affected_id": ME,
                                  "source_definition_id": "system:combat.concentration"},
               "recent_events": [{"event_type": "SAVE_ROLLED", "actor_id": ME,
                                  "target_ids": [ME], "source_definition_id": "typed:other.hazard",
                                  "payload": {"ability": "DEX", "dc": 13, "success": True}}]}
    said = trigger_text(context, {"reactor": ME, "reaction": "R"}, ACTORS, {})
    assert said == ("Zeng Jingxing made a Constitution saving throw to keep concentrating; "
                    "this prompt is about that roll.")
    assert "Dexterity" not in said and "DC" not in said
    assert "failed" not in said and "succeeded" not in said


def test_log_has_no_dead_placeholder_for_the_two_reported_event_types():
    rows = _feed([
        {"event_type": "ONCE_PER_TURN_CLAIMED", "source_definition_id": "system:combat.initiative",
         "actor_id": ME, "target_ids": [], "sequence": 1,
         "payload": {"scope": "_round_initiative_checkpoint_handled", "turns_started": 0}},
        {"event_type": "ONCE_PER_TURN_CLAIMED", "source_definition_id": "passive:cinder.touch_damage",
         "actor_id": ME, "target_ids": [], "sequence": 2,
         "payload": {"scope": "passive:cinder.touch_damage", "turns_started": 3}},
        {"event_type": "FIGHT_SETUP_COMPLETED", "source_definition_id": "system:combat.fight_setup",
         "actor_id": None, "target_ids": [], "sequence": 3,
         "payload": {"log": "Fight setup is complete. The first turn begins."}},
    ])
    assert not [row for row in rows if PLACEHOLDER in row["summary"]]
    # An internal once-per-turn guard changes nothing a player can see, so it is hidden: the
    # only ONCE_PER_TURN_CLAIMED line left is the ability's own claim.
    claimed = [row for row in rows if row["event_type"] == "ONCE_PER_TURN_CLAIMED"]
    assert len(claimed) == 1 and "this turn" in claimed[0]["summary"]
    setup = [row for row in rows if row["event_type"] == "FIGHT_SETUP_COMPLETED"]
    assert len(setup) == 1
    assert setup[0]["summary"] == "Fight setup is complete. The first turn begins."


def test_an_ability_claiming_its_once_per_turn_is_said_plainly():
    rows = _feed([{"event_type": "ONCE_PER_TURN_CLAIMED", "source_definition_id": "passive:cinder.touch_damage",
                   "actor_id": ME, "target_ids": [], "sequence": 1,
                   "payload": {"scope": "passive:cinder.touch_damage", "turns_started": 2}}])
    summary = rows[0]["summary"]
    assert summary.startswith("Zeng Jingxing used ") and "this turn" in summary
    assert rows[0]["detailed_breakdown_recorded"] is True
    # No code names, namespaces or raw ids reach the log line.
    assert "passive:" not in summary and "actor:" not in summary and "cinder.touch" not in summary


def test_fight_setup_uses_its_recorded_line_and_never_a_placeholder():
    rows = _feed([{"event_type": "FIGHT_SETUP_COMPLETED", "source_definition_id": "system:combat.fight_setup",
                   "actor_id": None, "target_ids": [], "sequence": 1, "payload": {}}])
    assert rows[0]["summary"] == "Fight setup is complete; the first turn begins."


def test_a_genuinely_unknown_event_still_reports_that_it_has_no_breakdown():
    """The fix must not paper over the honest placeholder for a record we cannot read."""
    rows = _feed([{"event_type": "SOME_FUTURE_ENGINE_EVENT", "source_definition_id": "typed:x",
                   "actor_id": ME, "target_ids": [], "sequence": 1, "payload": {}}])
    assert rows[0]["summary"] == f"{PLACEHOLDER} for this event."
    assert rows[0]["detailed_breakdown_recorded"] is False
