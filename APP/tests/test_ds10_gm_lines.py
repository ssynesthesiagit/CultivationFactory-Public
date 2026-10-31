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

These go through a committed table and a fresh saved-fight reload, and use
synthetic riders for a bracket note, a typing-only note, a trailing comment, and
long or linked clauses.
"""
from tests.hunt15_support import LEFT, act, fight, reload, turn

PREAMBLE = "additional effect reminder. Resolve only effects that the recorded outcomes have not already applied."

FOLLOW_THE_SOOT = "You sense the marked target within 120 feet (this table does not track direction; the GM decides direction)."
PLACE_TRACE = "Simplified from the printed once-per-round reminder; Action Type: coordinator.py leaves adjudication to the GM."
MIXED_CLAUSE = ("You sense the marked target when it moves beside you "
                "(the table notes contact; the GM decides direction). "
                "/ The target loses cover against you.")
DAMAGE_RULE = "Choose one object nearby; it suffers 4d6 fire damage."

COURT_OF_THE_FOUR_WINDS = " / ".join((
    "Select four markers when the field appears (the GM's).",
    "Keep four active zones outside your ordinary zone limit (the table does not count the limit).",
    "At turn start, move one zone up to 20 feet (the GM's: the table cannot move an area).",
    "Your lash may start from an active zone (the GM's).",
    "Allies gain +10 feet while moving with a zone; enemies moving against it treat spaces as Difficult Terrain "
    "(the GM's: the table has no direction).",
    "The field ends if you enter a sealed region with no air.",
    "When the field is active, its four winds shape the space around each marker. " +
    "A creature crossing between markers follows the path of the wind, and each marker " +
    "continues to affect the surrounding area until the field ends. The Keeper can move " +
    "one marker at the start of each turn, choosing a new location within twenty feet. " +
    "The four active markers remain in place even when another ordinary zone is created."
))

STORM_WITHOUT_DIRECTION = (
    "Enemies in the area cannot benefit from Advantage on ranged attacks: the table removes it, except lasting "
    "benefits (\"Advantage on its next attack\") -- that one is the GM's; a higher authority's Advantage still counts. / "
    "Flying enemies treat the area as Difficult Terrain (no flight on the table; ground is clear). / "
    "Loose objects whirl through the area. / Choose an extra effect until your next turn: / "
    "Unsteady Ground: Enemies moving more than half Speed must pass a Dexterity save or fall Prone."
)

NAME_WHAT_IS_NEAR = (
    "A willing subject may end the link as an Action; an unwilling one makes a Charisma save "
    "as an Action -- the GM's. Equal or stronger effects can contest the link. / "
    "A creature moving toward you spends double movement, or 5 fewer feet on a success -- "
    "the GM's: the table moves along the whole path at once. Against a melee attack it is a button."
)


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
    assert "sense the marked target" in lines[0]
    assert "120 feet" in lines[0]
    assert "this table" not in lines[0]
    assert "the GM decides direction" not in lines[0]


def test_commentary_at_the_end_of_a_clause_does_not_cost_the_clause_its_text(tmp_path):
    table, mid = _fight(tmp_path, "DS10-MIXED", MIXED_CLAUSE)
    lines = _gm_lines(table, mid)
    assert len(lines) == 1
    assert "You sense the marked target when it moves beside you." in lines[0]
    assert "The target loses cover against you." in lines[0]
    assert "the GM decides direction" not in lines[0]
    assert "the table notes contact" not in lines[0]


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
                        DAMAGE_RULE, "Until next turn, the target remains visible to you.")
    lines = _gm_lines(table, mid)
    assert len(lines) == 4  # the typing note is gone, every real rule is named
    for line in lines:
        assert line.startswith("River Keeper's Test setup"), line
        assert PREAMBLE in line
        reminder = line.split("Rule reminder:", 1)[1].strip()
        assert len(reminder) > 10, line  # a reminder, not a stub
        # Nothing about the table notes reaches the player.
        for jargon in ("this table", "Simplified", "the GM decides", "coordinator",
                       ".py", "Action Type:", "adjudicat", "is a button"):
            assert jargon not in line, line


def test_a_long_recalled_reminder_is_not_thrown_away_for_its_length(tmp_path):
    """A long synthetic reminder with several notes keeps its final instruction."""
    table, mid = _fight(tmp_path, "DS10-COURT", COURT_OF_THE_FOUR_WINDS)
    lines = _gm_lines(table, mid)
    assert len(lines) == 1, lines
    line = lines[0]
    assert "Rule reminder:" in line, line
    for rule in ("Select four markers", "four active zones", "move one zone up to 20 feet",
                 "lash may start from an active zone", "gain +10 feet",
                 "field ends if you enter a sealed region"):
        assert rule in line, rule
    assert len(line) > 480, line
    assert "the GM's" not in line
    assert "does not count the limit" not in line  # the bracket about the table is gone


def test_a_long_recalled_reminder_keeps_its_saving_throw_instruction(tmp_path):
    """A synthetic save instruction survives along with its surrounding clauses."""
    table, mid = _fight(tmp_path, "DS10-STORM", STORM_WITHOUT_DIRECTION)
    lines = _gm_lines(table, mid)
    assert len(lines) == 1, lines
    line = lines[0]
    assert "must pass a Dexterity save or fall Prone" in line, line
    assert "Flying enemies treat the area as Difficult Terrain" in line
    # the qualification that shares a semicolon with a note is still there
    assert "a higher authority's Advantage still counts" in line
    assert "no flight on the table" not in line  # bracket commentary dropped


def test_a_rule_linked_by_a_semicolon_keeps_both_halves(tmp_path):
    """A dash note does not discard the linked clause or UI commentary."""
    table, mid = _fight(tmp_path, "DS10-NEAR", NAME_WHAT_IS_NEAR)
    lines = _gm_lines(table, mid)
    assert len(lines) == 1, lines
    line = lines[0]
    assert "A willing subject may end the link as an Action;" in line
    assert "an unwilling one makes a Charisma save as an Action." in line
    # the two halves read as two sentences, not run together
    assert "to end it Equal" not in line
    assert "can contest the link." in line
    assert "spends double movement" in line  # the rule behind the note
    assert "the GM's" not in line
    assert "the table moves a creature along its whole path" not in line
    assert "is a button" not in line  # screen commentary, checklist 13


def test_a_dash_note_is_cut_off_without_costing_the_rule_its_text(tmp_path):
    table, mid = _fight(tmp_path, "DS10-NOTE", "The test failed -- the GM's.")
    lines = _gm_lines(table, mid)
    assert len(lines) == 1, lines
    assert "The test failed." in lines[0]
    assert "the GM's" not in lines[0]


def test_a_line_of_only_a_dash_note_never_reaches_the_log(tmp_path):
    table, mid = _fight(tmp_path, "DS10-NOTE2", "-- the GM's -- the table does it.")
    assert _gm_lines(table, mid) == []


def test_a_semicolon_linked_rule_survives_a_note_between_two_branches(tmp_path):
    table, mid = _fight(tmp_path, "DS10-LINK",
                        "The first marker stays -- the table records it -- and the second marker stays.")
    lines = _gm_lines(table, mid)
    assert len(lines) == 1, lines
    assert "The first marker stays" in lines[0]
    assert "and the second marker stays." in lines[0]
    assert "the table does it" not in lines[0]
