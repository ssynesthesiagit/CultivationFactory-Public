"""DS10 #2: every GM line in the fight log names the effect it is about.

The bug: `combat/history_text.rider_text` dropped a whole ``" / "`` clause when any
part of it matched the typing-commentary filter, so a rule sentence that shared a
bracket with a note about the table lost its text and the log printed the bare
"the GM must resolve this additional effect" preamble, naming no effect at all.

The second bug: judging that fix by recovered length threw genuine reminders away.
A rider made of several short rules crosses the old 480-character card cutoff once
the filter recovers them, and the whole line was dropped, so the GM lost a real
expiry or saving-throw instruction. The third: a rule linked to another by a
semicolon lost the linked half to a typing note at its end.

These go through a committed table and a fresh saved-fight reload, the level the
bug showed, and use real shapes from the round-23 playtest: a rule whose bracket
mentions the table (Follow the Soot), a rider that is nothing but a typing note
(Place Smoke Trace), a clause where the commentary sits at the end, and the three
recorded long/linked riders from the review of this lane.
"""
from tests.hunt15_support import LEFT, act, fight, reload, turn

PREAMBLE = ("additional effect reminder. Resolve only effects that the recorded "
            "outcomes have not already applied.")

# Real wording from the round-23 playtest, trimmed only where it named a file.
FOLLOW_THE_SOOT = (
    "Until the start of your next turn, you know the direction to the traced target "
    "while it remains within 120 feet (no compass-direction readout on this table; "
    "the GM decides it).")
PLACE_TRACE = "Simplified from the printed once-per-round environmental triggers."
MIXED_CLAUSE = ("You know its square the moment it moves next to you "
                "(the table records the contact; the GM calls the rest). "
                "/ The creature no longer has cover against you.")
DAMAGE_RULE = "Choose one object or structure section within 60 feet; it takes 4d6 fire damage."

# Recorded verbatim: manual-03.json sequence 56, Court of the Four Winds. Six short
# rules, each with a typing note in brackets, and a court-expiry rule at the end.
# Recovering the notes' rules pushes the text past 480 characters.
COURT_OF_THE_FOUR_WINDS = (
    "Choose four winds when the court appears: North, South, East, and West. Each wind is "
    "assigned one Vector: Lift, Press, Cut, Carry, Turn, or Scatter. You cannot assign the "
    "same Vector to more than two winds (the GM's). / You may maintain up to four Air "
    "Currents without counting them against your Air Control Limit (the table does not count "
    "the limit). / When a creature starts its turn inside the court, you may move one active "
    "Current up to 20 feet (the GM's: the table cannot move an area). / Your Wind Lash may "
    "originate from any active Current inside the court (the GM's). / Allied creatures inside "
    "one of your Currents gain +10 feet to Speed while moving in the direction you choose; "
    "hostile creatures moving against one of your Currents treat the space as Difficult Terrain "
    "(the GM's: the table has no wind direction). / The court also ends if you enter an "
    "airless sealed region that prevents currents from existing.")

# Recorded verbatim: ai-07.json sequence 150, Storm Without Direction. The last two
# clauses are a real saving-throw instruction the GM has to apply by hand.
STORM_WITHOUT_DIRECTION = (
    "Hostile creatures in the area cannot benefit from Advantage on ranged attack rolls: the "
    "table removes it, except an Advantage already stored on the attacker as a lasting benefit "
    "(\"Advantage on its next attack roll\") -- that one is the GM's to remove; a Secret "
    "Inheritance, artifact or higher authority's Advantage still counts. / Flying hostile "
    "creatures treat the area as Difficult Terrain (no flight on the table; the ground is not "
    "difficult). / Ordinary fog, smoke, dust, ash, leaves, cloth, and unsecured Tiny objects "
    "whirl through the area. / At the start of each of your turns, choose one additional effect "
    "until the start of your next turn: / No Steady Foot: Hostile creatures that move more than "
    "half their Speed must succeed on a Dexterity saving throw or fall Prone at the end of that "
    "movement.")

# Recorded verbatim: manual-03.json sequence 129, Name What Is Near. The willing and
# unwilling halves of one rule are joined by a semicolon, and the second half is
# qualified by a dash note; a further sentence is UI commentary about a button.
NAME_WHAT_IS_NEAR = (
    "A willing subject can end a relation as an Action; an unwilling one makes a Charisma save "
    "as an Action to end it -- the GM's. Equal or higher Boundary, Space, Seal, Formation, "
    "Thread, Void or conceptual effects can contest a relation. / Far Relation also answers a "
    "creature moving toward you (its movement toward you costs double, or on a success 5 feet "
    "less Speed) -- the GM's: the table moves a creature along its whole path at once. Against "
    "a melee attack it is a button.")


def _gm_lines(table, mid):
    return [row["summary"] for row in table.events(mid, 0)["events"]
            if row["event_type"] == "GM_RIDER"]


def _fight(tmp_path, seed, *riders):
    combat, table, mid = fight(tmp_path, ["POISON_BASE_DELIVER_THE_DOSE"], seed=seed,
                               effects=[{"type": "rider", "evidence": text} for text in riders])
    turn(table, mid, LEFT)
    assert act(table, mid, "Test setup")["status"] == "COMMITTED"
    reload(combat, mid)  # the reminder must survive a table commit and a fresh load
    return table, mid


def test_rule_sharing_a_bracket_with_a_table_note_still_names_the_effect(tmp_path):
    table, mid = _fight(tmp_path, "DS10-SOOT", FOLLOW_THE_SOOT)
    lines = _gm_lines(table, mid)
    assert len(lines) == 1
    assert "Rule reminder:" in lines[0], lines[0]
    # the rule itself survives; only the bracket about the table is gone
    assert "you know the direction to the traced target" in lines[0]
    assert "120 feet" in lines[0]
    assert "this table" not in lines[0]
    assert "the GM decides it" not in lines[0]


def test_commentary_at_the_end_of_a_clause_does_not_cost_the_clause_its_text(tmp_path):
    table, mid = _fight(tmp_path, "DS10-MIXED", MIXED_CLAUSE)
    lines = _gm_lines(table, mid)
    assert len(lines) == 1
    assert "You know its square the moment it moves next to you." in lines[0]
    assert "The creature no longer has cover against you." in lines[0]
    assert "the GM calls the rest" not in lines[0]
    assert "the table records the contact" not in lines[0]


def test_rider_that_is_only_a_typing_note_leaves_no_gm_line(tmp_path):
    table, mid = _fight(tmp_path, "DS10-TYPING", PLACE_TRACE)
    assert _gm_lines(table, mid) == []


def test_typing_note_alongside_a_real_rule_drops_only_the_note(tmp_path):
    table, mid = _fight(tmp_path, "DS10-MIXED2", PLACE_TRACE, DAMAGE_RULE)
    lines = _gm_lines(table, mid)
    assert len(lines) == 1
    assert "4d6 fire damage" in lines[0]


def test_every_gm_line_names_an_effect_and_reads_for_a_newcomer(tmp_path):
    table, mid = _fight(tmp_path, "DS10-ALL", FOLLOW_THE_SOOT, PLACE_TRACE, MIXED_CLAUSE,
                        DAMAGE_RULE, "Until the end of your next turn, it cannot be Hidden from you.")
    lines = _gm_lines(table, mid)
    assert len(lines) == 4  # the typing note is gone, every real rule is named
    for line in lines:
        assert line.startswith("River Keeper's Test setup"), line
        assert PREAMBLE in line
        reminder = line.split("Rule reminder:", 1)[1].strip()
        assert len(reminder) > 10, line  # a reminder, not a stub
        # checklist 13: nothing about the typing reaches the player
        for jargon in ("this table", "Simplified", "the GM decides", "coordinator",
                       ".py", "Action Type:", "adjudicat", "is a button"):
            assert jargon not in line, line


def test_a_long_recalled_reminder_is_not_thrown_away_for_its_length(tmp_path):
    """Court of the Four Winds: several short rules with a note in each bracket.

    Before the length cutoff was removed, recovering the rules pushed the text past
    480 characters and the whole line was dropped, so the GM lost the instruction
    that ends the court.
    """
    table, mid = _fight(tmp_path, "DS10-COURT", COURT_OF_THE_FOUR_WINDS)
    lines = _gm_lines(table, mid)
    assert len(lines) == 1, lines
    line = lines[0]
    assert "Rule reminder:" in line, line
    for rule in ("Choose four winds when the court appears",
                 "up to four Air Currents without counting them against your Air Control Limit",
                 "move one active Current up to 20 feet",
                 "Your Wind Lash may originate from any active Current",
                 "gain +10 feet to Speed",
                 "The court also ends if you enter an airless sealed region"):
        assert rule in line, rule
    assert "the GM's" not in line
    assert "does not count the limit" not in line  # the bracket about the table is gone


def test_a_long_recalled_reminder_keeps_its_saving_throw_instruction(tmp_path):
    """Storm Without Direction: the Dex-save-or-fall-Prone line is the whole point."""
    table, mid = _fight(tmp_path, "DS10-STORM", STORM_WITHOUT_DIRECTION)
    lines = _gm_lines(table, mid)
    assert len(lines) == 1, lines
    line = lines[0]
    assert "must succeed on a Dexterity saving throw or fall Prone" in line, line
    assert "Flying hostile creatures treat the area as Difficult Terrain" in line
    # the qualification that shares a semicolon with a note is still there
    assert "a Secret Inheritance, artifact or higher authority's Advantage still counts" in line
    assert "no flight on the table" not in line  # bracket commentary dropped


def test_a_rule_linked_by_a_semicolon_keeps_both_halves(tmp_path):
    """Name What Is Near: the unwilling half is qualified by a dash note.

    Dropping the note must not cost the rule the Charisma save, and the UI
    commentary about a button must not reach the log.
    """
    table, mid = _fight(tmp_path, "DS10-NEAR", NAME_WHAT_IS_NEAR)
    lines = _gm_lines(table, mid)
    assert len(lines) == 1, lines
    line = lines[0]
    assert "A willing subject can end a relation as an Action;" in line
    assert "an unwilling one makes a Charisma save as an Action to end it." in line
    # the two halves read as two sentences, not run together
    assert "to end it Equal" not in line
    assert "can contest a relation." in line
    assert "its movement toward you costs double" in line  # the rule behind the note
    assert "the GM's" not in line
    assert "the table moves a creature along its whole path" not in line
    assert "is a button" not in line  # screen commentary, checklist 13


def test_a_dash_note_is_cut_off_without_costing_the_rule_its_text(tmp_path):
    table, mid = _fight(tmp_path, "DS10-NOTE", "The Hide attempt failed -- the GM's.")
    lines = _gm_lines(table, mid)
    assert len(lines) == 1, lines
    assert "The Hide attempt failed." in lines[0]
    assert "the GM's" not in lines[0]


def test_a_line_of_only_a_dash_note_never_reaches_the_log(tmp_path):
    table, mid = _fight(tmp_path, "DS10-NOTE2", "-- the GM's -- the table does it.")
    assert _gm_lines(table, mid) == []


def test_a_semicolon_linked_rule_survives_a_note_between_two_branches(tmp_path):
    table, mid = _fight(tmp_path, "DS10-LINK",
                        "The first half is real -- the table does it -- and the second half is real.")
    lines = _gm_lines(table, mid)
    assert len(lines) == 1, lines
    assert "The first half is real" in lines[0]
    assert "and the second half is real." in lines[0]
    assert "the table does it" not in lines[0]
