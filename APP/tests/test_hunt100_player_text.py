"""HUNT100 (round 24, 42e43e14): player text must not carry build detail.

A playtest read the player's own screens and found eight ways build machinery
leaked into them: a Python file path in a condition hover, an internal
factory-composition field in a button hover, a button label ending in the word
"rider", a fight log that spoke to the player as the GM and quoted a raw damage
table, developer notes in a hover, "Cost: None" and glued words, "CP" worded one
way in a hover and another way in a prompt, and a doubled word in the damage
roll line.

Two levels of test live here:

* ``test_*_at_the_table`` drive the real ``TabletopService`` projection, so a
  fix that only helps a unit call cannot pass.
* ``test_*_guard`` sweep every generated hover and log string, so the *next*
  plug-in that prints build detail fails here instead of in a playtest.

What is deliberately NOT guarded, and why: the owner's printed rules may say
"according to GM adjudication" and "choose one rider" in their own words, and
this lane does not rewrite the owner's rules. So the guard checks the strings
the *builders* author, and checks "rider" on button labels (where a dangling
internal noun is the defect) rather than on every rule sentence.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from combat import player_text
from combat.condition_text import all_conditions
from combat.history_text import rider_text
from combat.status_text import printed_excerpt, printed_rules
from combat.tabletop import engine_button_description
from tests.test_status_text import _tooltip_table

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json"

# A source file, an internal build field, a Python literal, a glued field label,
# a developer note, a bare "CP", and a doubled word.
PATH = re.compile(r"\b(?:combat|APP|tools|authority|tests|static)/[\w/]+\.\w+")
FACTORY_FIELD = re.compile(r"Split Review Decision|Recommended Factory Realization|Factory Routing|"
                           r"Factory Metadata|Source Record ID|Typed Record ID")
PY_LITERAL_COST = re.compile(r"\b(?:Cost|Duration):\s*(?:None|True|False|null)\b")
GLUED_LABEL = re.compile(r"[a-z0-9](?:Concentration|Action Type|Timing Detail|Range|Target|Area|"
                         r"Duration|Cost|Use Limit|Tags):")
DEV_NOTE = re.compile(r"no generic .+ on this table|subpaths worker|GM line:|not automated", re.I)
BARE_CP = re.compile(r"\bCP\b")
# The same scoping the cleaner uses: a compound name is not a doubled word
# ("Five-Venom Venom Effects"), and "had had" is correct English.
DOUBLED_WORD = re.compile(r"(?<![\w/-])(?!had\b)([A-Za-z]{2,})(?:\s+\1\b)+", re.I)
INTERNAL_NAME = re.compile(r"\b(?:hook speed|row_allowed|candidate_allowed|block_save|block_movement|"
                           r"block_condition|ignores_difficult|masked_conditions|teleport_check)\b")
BUILD_DATE = re.compile(r"\b(?:worker\s+)?20\d\d-\d\d-\d\d\b")
LOOKUP_TABLE = re.compile(r"(?:CL\s*)?\d+\s*[-–]\s*\d+\s*:\s*[^\n.;]*\d+\s*[-–]\s*\d+\s*:")


def _hover(key: str, label: str = "") -> str:
    """The string a player reads when hovering a button for a printed record."""
    return engine_button_description({"display_name": label, "parameters": {"typed": {"source": key}}})


def _hover_from_action(action) -> str:
    """The same hover, for an ActionDefinition the plug-in compiled."""
    return engine_button_description({"display_name": action.display_name,
                                      "parameters": dict(action.parameters or {})})


def _complain(label: str, text: str, pattern: re.Pattern[str]) -> str:
    match = pattern.search(text)
    where = f" ...{text[max(0, match.start() - 40):match.end() + 40]}..." if match else ""
    return f"{label} shows {pattern.pattern!r}: {text[:200]!r}{where}"


# --------------------------------------------------------------------------
# 1: the condition-pill hover is player prose, not a source citation
# --------------------------------------------------------------------------

def test_condition_hover_reading_has_no_source_path_at_the_table(tmp_path, monkeypatch):
    """A condition whose reading comes from the engine's raw evidence sentence."""
    table, mid, engine = _tooltip_table(tmp_path, monkeypatch)
    actor = next(iter(engine.state.actors.values()))
    # bound_footwork and bleeding fall back to the engine's evidence sentence,
    # which names the file that typed the condition.
    for cid in ("bound_footwork", "bleeding"):
        engine._apply_condition(actor, "condition:typed." + cid, "action:typed.old.internal_id",
                                actor.entity_id, expires_on="UNTIL_REMOVED")
    rows = {r["condition_id"]: r for a in table.state(mid)["presentation"]["actors"] for r in a["conditions"]}
    assert rows, "the table projected no conditions to check"
    for cid, row in rows.items():
        for field in ("rule_text", "detail", "handling", "source_ability"):
            text = str(row.get(field) or "")
            for pattern in (PATH, INTERNAL_NAME, BUILD_DATE, DOUBLED_WORD):
                assert not pattern.search(text), f"{cid}.{field}" + _complain(cid, text, pattern)
        # The other half of the card: the client resolver falls back to the
        # conditions catalog for a row without its own detail, and that catalog
        # is what the raw evidence sentence used to leak through.
        key = cid.split(".").pop()
        reading = str((all_conditions().get(key) or {}).get("reading") or "")
        for pattern in (PATH, INTERNAL_NAME, BUILD_DATE, DOUBLED_WORD):
            assert not pattern.search(reading), f"catalog[{key}].reading" + _complain(key, reading, pattern)


def test_condition_hover_still_explains_the_condition(tmp_path, monkeypatch):
    """The cleaner removes build detail; it must not empty the explanation."""
    table, mid, engine = _tooltip_table(tmp_path, monkeypatch)
    actor = next(iter(engine.state.actors.values()))
    engine._apply_condition(actor, "condition:typed.bound_footwork", "action:typed.old.internal_id",
                            actor.entity_id, expires_on="UNTIL_REMOVED")
    row = next(r for a in table.state(mid)["presentation"]["actors"] for r in a["conditions"]
               if r["condition_id"] == "condition:typed.bound_footwork")
    assert len(row["rule_text"]) > 20, "the hover lost its explanation"
    assert re.search(r"[Ss]peed|feet", row["rule_text"]), row["rule_text"]


def test_condition_catalog_reading_is_clean_for_every_key():
    """The catalog the client resolver reads (tabletop.js conditionText)."""
    from combat.condition_text import READING

    had_text = 0
    for key, entry in all_conditions().items():
        text = str(entry.get("reading") or "")
        for pattern in (PATH, INTERNAL_NAME, BUILD_DATE, FACTORY_FIELD, DOUBLED_WORD, BARE_CP):
            assert not pattern.search(text), f"conditions[{key}].reading" + _complain(key, text, pattern)
        # Cleaning must never empty a reading the data had something to say.
        if str(READING.get(key) or (entry.get("rule") or {}).get("_rule") or "").strip():
            had_text += 1
            assert text.strip(), f"conditions[{key}].reading was emptied by the cleaner"
    assert had_text > 100, f"only {had_text} readings had any text to keep"


# --------------------------------------------------------------------------
# 2 + 5 + 6 + 7: one button hover, one plain wording for the printed record
# --------------------------------------------------------------------------

@pytest.mark.parametrize("key", [
    "BLACKSMITH_BASE_READ_THE_FLAW", "HARVESTING_GATHERING_BASE_READ_THE_SIGN",
    "IMBUEMENT_BASE_READ_THE_VESSEL", "HUNGER_BASE_DIGESTIVE_MANTLE", "ALCHEMY_BASE_FIELD_FORMULA",
])
def test_button_hover_drops_internal_factory_fields_and_says_what_cp_is(key):
    text = _hover(key)
    assert text, f"{key} has no hover text at all"
    for pattern in (FACTORY_FIELD, PATH, BARE_CP, PY_LITERAL_COST, GLUED_LABEL, DEV_NOTE, DOUBLED_WORD):
        assert not pattern.search(text), _complain(key, text, pattern)


def test_button_hover_keeps_the_printed_rule_it_cleans():
    """A hover is one paragraph, but it is still the rule, not a label."""
    text = _hover("BLACKSMITH_BASE_READ_THE_FLAW")
    assert "Read the Flaw" in text
    assert len(text) > 80, "the hover lost the rule it was showing"


def test_every_printed_record_hover_is_clean():
    """Sweep every printed record through the real hover path."""
    checked = 0
    for key in sorted(printed_rules()):
        text = printed_excerpt(key)
        if not text.strip():
            continue
        checked += 1
        for pattern in (PATH, FACTORY_FIELD, PY_LITERAL_COST, GLUED_LABEL, DOUBLED_WORD, DEV_NOTE):
            assert not pattern.search(text), _complain(key, text, pattern)
    assert checked > 3000, f"only {checked} printed records were swept"


def test_table_menu_buttons_carry_clean_labels_and_hovers(tmp_path):
    """The real menu a player clicks: labels and hovers, from the service."""
    from tests.hunt15_support import fight

    _combat, table, mid = fight(tmp_path)
    groups = table.state(mid)["menu"]["actions"]
    assert groups, "the table offered no buttons to check"
    for group in groups:
        label = str(group.get("label") or "")
        assert not re.search(r"\brider\b", label), f"button label uses the internal word: {label!r}"
        assert not PATH.search(label), f"button label shows a source path: {label!r}"
        for option in group.get("options") or []:
            assert option.get("label"), "a button option has no label"
            assert not re.search(r"\brider\b", str(option["label"])), option["label"]
        for field in ("description",):
            text = str(group.get(field) or "")
            for pattern in (PATH, FACTORY_FIELD, BARE_CP, PY_LITERAL_COST, GLUED_LABEL, DOUBLED_WORD):
                assert not pattern.search(text), f"{label}.{field}" + _complain(label, text, pattern)


def test_cp_reads_the_same_way_in_a_hover_and_in_an_ask_me_prompt():
    """Finding 7: one plain wording for CP on every surface (HUNT100 #7)."""
    from combat.decision_text import build_decision_text

    hover = _hover("ALCHEMY_BASE_FIELD_FORMULA")
    # The card builder uses the singular for a one-point cost and capitalises the glossary sentence
    # (factory_authoring/player_rules.py, clarity 2026-10-17/18); the requirement is that CP is spelled
    # out, never a bare abbreviation.
    assert re.search(r"cultivation points?", hover, re.I), hover
    assert not BARE_CP.search(hover), _complain("hover", hover, BARE_CP)

    engine = SimpleNamespace(typed_reaction_rows={}, typed_passive_rows={}, action_catalog={},
                             state=SimpleNamespace(actors={}))
    context = {"reactor_id": "actor:factory.left", "reaction_source_id": "reaction:typed.probe",
               "checkpoint": "TYPED:ATTACK_DECLARED@1",
               "choice_trigger": {"actor_id": "actor:factory.right", "target_id": "actor:factory.left",
                                  "cost": "2 CP or 2 Stamina"}}
    prompt = build_decision_text(engine, context,
                                 {"reactor": "Player", "reaction": "Probe", "moment": "is attacked"},
                                 {"actor:factory.left": "Wen Xue", "actor:factory.right": "Mei Jiang"}, {}, {})
    body = " ".join(str(prompt.get(field) or "") for field in ("cost", "summary", "rules", "trigger"))
    assert not BARE_CP.search(body), _complain("ask-me prompt", body, BARE_CP)
    assert "cultivation points" in body, body


# --------------------------------------------------------------------------
# 9: cleaning must not take the rule with the build detail (MMX99r1)
# --------------------------------------------------------------------------

def test_damage_bands_survive_on_the_hover_and_not_in_the_log():
    """MMX99r1 P1: a card keeps the Cultivation Level table; the log drops it.

    Starbolt says "deal the damage below + your Path key ability modifier", so
    a hover that loses the four bands is left pointing at nothing.
    """
    hover = _hover("STARS_BASE_STARBOLT")
    # The card explains the abbreviation at its first use ("CL 1-4 (Cultivation Level)", clarity
    # 2026-10-17/18), so the band is asserted with that gloss optional: what must survive is every
    # band and its dice.
    for band in ("CL 1-4", "CL 5-10", "CL 11-16", "CL 17-20"):
        assert re.search(re.escape(band) + r"(?: \(Cultivation Level\))?: \d+d8", hover), \
            f"the hover lost the {band!r} band: {hover!r}"
    assert "Path key ability modifier" in hover, hover

    log = rider_text({"rider": "Damage: CL 1-4: 1d8. CL 5-10: 2d8. CL 11-16: 3d8. CL 17-20: 4d8.",
                      "automated": False}, "Nixian Weave", "Starbolt", "Mei Jiang")
    assert log is None  # The lookup was the entire payload; LIVE suppresses the empty reminder.
    # No row also means no dangling pointer to the removed lookup table.


def test_ordinary_wording_is_not_mistaken_for_a_code_name():
    """MMX99r1 P2: "pinpoints" is the owner's own printed rule, not a row name."""
    text = _hover("TAL_THE_HIDDEN_EYE_SIGHT_BEYOND_SIGHT")
    assert "Tremorsense pinpoints eligible creatures and moving objects" in text, text
    assert "does not count as sight" in text, text
    assert "Blindsight counts as sight within its range" in text, text


def test_a_rule_printed_beside_a_citation_is_kept():
    """MMX99r1 P2: the Stone Womb ending rule shares a bracket with its file."""
    reading = all_conditions()["stone_shell"]["reading"]
    for fragment in ("ends early on healing", "dismissal",
                     "damage equal to 10", "Proficiency Bonus"):
        assert fragment in reading, f"stone_shell lost {fragment!r}: {reading!r}"
    for pattern in (PATH, INTERNAL_NAME, BUILD_DATE):
        assert not pattern.search(reading), f"stone_shell" + _complain("stone_shell", reading, pattern)


@pytest.mark.parametrize("note", [
    "ends when healed; not modeled: the table has no healing handler",
    "not modeled: the table has no healing handler; ends when healed",
    "ends when healed, not implemented on this table",
])
def test_mechanical_fragment_beside_developer_note_survives(note, monkeypatch):
    """SOLFMMX99r2: implementation evidence cannot erase an ending rule."""
    from combat import condition_text

    raw = f"Cannot move ({note})."
    monkeypatch.setitem(condition_text.READING, "review_mixed_note", raw)
    assert condition_text.all_conditions()["review_mixed_note"]["reading"] == \
        "Cannot move (ends when healed)."
    assert player_text.plain(raw) == "Cannot move (ends when healed)."
    assert player_text.plain("Cannot move (not modeled on this table).") == "Cannot move."


def test_condition_delta_uses_original_inputs_for_both_cleaners(monkeypatch, capsys):
    """SOLFMMX99r2: pre-cleaning would hide exactly the deletion being measured."""
    from tools import mmx99r1_text_delta as delta

    raw = "Cannot move (ends when healed; not modeled on this table)."
    monkeypatch.setattr(delta, "READING", {"handwritten": raw})
    monkeypatch.setattr(delta, "condition_rules", lambda: {"conditions": {
        "fallback": {"_rule": raw}, "handwritten": {"_rule": "unused evidence"}}})
    seen = []

    def before(text):
        seen.append(text)
        return "Cannot move."

    monkeypatch.setattr(delta, "_load_base_cleaner", lambda: SimpleNamespace(
        plain=player_text.plain, reading=before))
    assert delta.raw_condition_readings() == {"fallback": raw, "handwritten": raw}
    assert delta.main() == 0
    output = capsys.readouterr().out
    assert seen == [raw, raw]
    assert "condition reading: fallback" in output
    assert "condition reading: handwritten" in output
    assert "HEAD: 'Cannot move (ends when healed).'" in output


def test_ability_names_survive_alongside_a_citation():
    """Dropping the file must not take the ability that explains the rule.

    rest_hold has no hand-written reading, so the catalogue shows the cleaned
    evidence sentence. no_dash does have one, so its cleaned evidence is
    checked on the surface that shows it.
    """
    from combat.condition_text import READING

    assert READING.get("rest_hold") is None, "rest_hold now has a hand-written reading"
    reading = str(all_conditions()["rest_hold"]["reading"])
    assert "Rest Hold" in reading, f"rest_hold lost the ability name: {reading!r}"

    conditions = json.loads((ROOT / "combat/rules/typed_conditions.json").read_text(encoding="utf-8"))["conditions"]
    cleaned = player_text.plain(conditions["no_dash"]["_rule"])
    assert "Clinging Seal" in cleaned, cleaned
    for key in ("no_dash", "rest_hold"):
        text = str(all_conditions()[key]["reading"])
        assert not PATH.search(text), key + _complain(key, text, PATH)


# --------------------------------------------------------------------------
# 3: a button label must not end in the internal word
# --------------------------------------------------------------------------

def test_printed_labels_do_not_end_in_the_internal_rider_word():
    for key, text in ((key, printed_rules()[key]) for key in sorted(printed_rules())):
        cleaned = player_text.clean(text)
        labels = re.findall(r"(?m)^#{2,}\s+(.+)$", cleaned) or [cleaned.splitlines()[0] if cleaned else ""]
        for label in labels:
            assert not re.search(r"\brider\b\s*$", label), f"{key} label ends in 'rider': {label!r}"


def test_formation_master_element_choice_is_named_without_rider(tmp_path):
    """The Next Killing Line buttons, built by the plug-in and read off the table.

    MMX99r1: this used to construct "Next Killing Line: {name}" inside the test
    and assert on its own string, so it passed even with the plug-in reverted.
    The labels and descriptions below are read back from a real compiled
    character, and each element is checked against the owner's own printed rule
    so a plug-in that drifts from the sheet is caught here too.
    """
    from tests.hunt15_support import fight
    from combat.ext.formation_masters import ELEMENTS

    # The owner's printed rule, read from the authority rather than from the
    # plug-in: "Fire or Ash: the target cannot regain Hit Points ...". The
    # plug-in's own effect is a shortened wording of this same rule.
    printed = printed_rules()["tianxia.talent.formations.elemental_killing_array"]
    owner_rules = {}
    for element, (name, _effect) in ELEMENTS.items():
        match = re.search(rf"^{re.escape(name)}:\s*(.+)$", printed, re.M)
        assert match, f"{element} has no printed rule line for {name}"
        # The owner's sheet uses a typographic apostrophe; the description is
        # built with a plain one. Compare the rule, not the keyboard.
        owner_rules[element] = match[1].strip().replace("\u2019", "'")

    combat, table, mid = fight(tmp_path, left=["tianxia.talent.formations.elemental_killing_array"])
    catalog = combat._load_session(mid).engine.action_catalog
    compiled = {a.display_name: dict(a.parameters or {}).get("description", "")
                for a in catalog.values() if "Killing Line" in a.display_name
                and a.display_name.startswith("Next ")}

    assert compiled, "the compiled character offered no Next Killing Line choice"
    for element, (name, _effect) in ELEMENTS.items():
        label = f"Next Killing Line: {name}"
        assert label in compiled, f"{element}: the plug-in compiled {sorted(compiled)}"
        # The label names the sphere, never the internal word.
        assert not re.search(r"\brider\b", label, re.I), label
        description = str(compiled[label])
        assert name in description, f"{label} does not name its sphere: {description!r}"
        # The hover says what the extra effect actually does: the effect is read
        # from the plug-in's own table, so reverting the description to the old
        # wording drops it and this fails.
        effect = _effect.strip()
        assert effect in description, \
            f"{label} does not state its own effect: {description!r} != {effect!r}"
        # The plug-in may word the effect more briefly than the owner's sheet,
        # but it may not name a different mechanic: the rule and the button have
        # to be talking about the same thing.
        mechanics = [word for word in ("Hit Points", "Speed", "Dash", "Reactions",
                                       "Invisible", "Perception", "Constitution", "push")
                     if word in owner_rules[element]]
        assert mechanics, f"{element} has no recognised mechanic in the owner's rule"
        assert any(word in description for word in mechanics), \
            f"{label} contradicts the owner's rule {owner_rules[element]!r}: {description!r}"
        assert not re.search(r"\brider\b", description, re.I), description


def test_formation_element_hover_reads_as_a_rule_at_the_table(tmp_path):
    """Every element choice, through the real hover builder the table uses.

    The compiled action carries the sphere's name and its effect; this is the
    string a player actually reads on the button, so it is checked there too.
    """
    from tests.hunt15_support import fight
    from combat.ext.formation_masters import ELEMENTS

    combat, _table, mid = fight(tmp_path, left=["tianxia.talent.formations.elemental_killing_array"])
    catalog = combat._load_session(mid).engine.action_catalog
    for element, (name, _effect) in ELEMENTS.items():
        row = next((a for a in catalog.values() if a.display_name == f"Next Killing Line: {name}"), None)
        assert row is not None, f"{element} was not compiled for an owner of Elemental Killing Array"
        hover = _hover_from_action(row)
        assert name in hover, f"{element}: {hover!r}"
        assert "extra effect" in hover, f"{element}: {hover!r}"
        for pattern in (PATH, FACTORY_FIELD, DOUBLED_WORD):
            assert not pattern.search(hover), f"{element}" + _complain("formation hover", hover, pattern)


# --------------------------------------------------------------------------
# 4: the fight log speaks to the player, and quotes no lookup table
# --------------------------------------------------------------------------

def test_rider_log_line_does_not_address_the_player_as_the_gm():
    """The live line: a Spatial Edge rider printed a CL band damage table."""
    payload = {"rider": "Cost: 0 cultivation points. Rule reminder: Damage: CL 1-4: 1d8. CL 5-10: 2d8. "
                        "CL 11-16: 3d8. CL 17-20: 4d8. / the GM must resolve this additional effect; "
                        "the table has not applied it.",
               "automated": False}
    text = rider_text(payload, "Nixian Weave", "Spatial Edge", "Mei Jiang")
    assert not re.search(r"\bGM\b", text), text
    assert "the table has not applied it" not in text, text
    assert not LOOKUP_TABLE.search(text), f"the log quotes a lookup table: {text}"
    assert not DOUBLED_WORD.search(text), _complain("rider log", text, DOUBLED_WORD)
    assert not PATH.search(text), _complain("rider log", text, PATH)
    # The player still learns the one thing they must act on, and who it is for.
    assert "Game Master" not in text, text  # Newer policy: only a printed rule may require the GM.
    assert "recorded outcomes have not already applied" in text, text
    assert "Nixian Weave" in text and "Mei Jiang" in text, text
    assert text.count("Rule reminder") == 1, text


def test_every_rider_reminder_is_clean():
    """Sweep every rider string the authority can put in the log."""
    authority = json.loads(AUTHORITY.read_text(encoding="utf-8"))
    riders = set()
    for record in (authority.get("mechanics") or {}).values():
        for rider in record.get("riders") or []:
            if isinstance(rider, str):
                riders.add(rider)
            elif isinstance(rider, dict):
                riders.update(str(value) for value in rider.values() if isinstance(value, str))
    for entry in all_conditions().values():
        rule = str((entry.get("rule") or {}).get("_rule") or "")
        if rule:
            riders.add(rule)
    assert riders, "no rider text found to sweep"
    for rider in riders:
        text = rider_text({"rider": rider, "automated": False}, "A Fighter", "A Talent", "An Ally")
        if text is None:
            continue  # LIVE omits commentary-only rows; their raw evidence remains recorded.
        for pattern in (PATH, FACTORY_FIELD, DOUBLED_WORD, PY_LITERAL_COST):
            assert not pattern.search(text), _complain(f"rider {rider[:60]!r}", text, pattern)


# --------------------------------------------------------------------------
# 8: the damage roll line
# --------------------------------------------------------------------------

def test_damage_roll_line_does_not_repeat_the_word_damage():
    from combat.history_feed import format_history_feed

    names = {"factory-actor-left": "Wen Xue", "factory-actor-right": "Mei Jiang"}

    def line(source: str) -> str:
        event = {"round": 3, "actor_id": "factory-actor-left", "event_type": "DAMAGE_ROLLED",
                 "target_ids": ["factory-actor-right"],
                 "payload": {"display_name": source, "expression": "3d6+0"}}
        return str(format_history_feed([event], [], pre_state=None, post_state={},
                                       actor_names=names, definition_names={}))

    doubled = line("Daemonic Augment: Bonus Damage")
    assert "damage damage" not in doubled.casefold(), doubled
    assert not DOUBLED_WORD.search(doubled), _complain("damage roll line", doubled, DOUBLED_WORD)
    assert "Bonus Damage against Mei Jiang" in doubled, doubled
    # A source whose name does not end in "Damage" still reads correctly.
    assert "Void Needle damage against Mei Jiang" in line("Void Needle")


# --------------------------------------------------------------------------
# The shared cleaner itself
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("Cost: None", "Cost: no cost"),
    ("Duration: None", "Duration: unlimited"),
    ("**Cost:** None", "Cost: no cost"),
    ("Duration: 1 minuteConcentration: Required", "Duration: 1 minute. Concentration: Required"),
    ("Cost: NoneConcentration: Not required", "Cost: no cost. Concentration: Not required"),
    ("Speed reduced by 15 feet (combat/ext/thread_lines.py, hook speed).",
     "Speed reduced by 15 feet."),
    ("Bleeding (combat/ext/black_thorn_demon_body.py, subpaths worker 2026-09-28).", "Bleeding."),
    ("Read the Flaw Split Review Decision: single_combat_action_plus_procedure_variant Range: Touch",
     "Read the Flaw Range: Touch"),
    ("Extra damage damage against the target.", "Extra damage against the target."),
    ("Five-Venom Venom Effects: halve healing.", "Five-Venom Venom Effects: halve healing."),
    ("You gain CL 11 or higher: nothing is lost.", "You gain CL 11 or higher: nothing is lost."),
])
def test_cleaner_turns_build_detail_into_plain_wording(text, expected):
    assert player_text.plain(text) == expected


@pytest.mark.parametrize("surface, keeps_the_table", [
    (player_text.plain, True),      # a card, a hover, a reference entry
    (player_text.clean, True),
    (player_text.log_plain, False),  # the fight log, where a table is a lookup
    (player_text.log_text, False),
])
def test_the_damage_table_is_kept_except_in_the_log(surface, keeps_the_table):
    """MMX99r1: the review rejected a global "delete the damage table" rule.

    The suppression belongs to the one surface where a Cultivation Level table
    is a lookup rather than the rule the ability deals, so this pins which
    surface drops it and which must not.
    """
    text = "Damage: CL 1-4: 1d8. CL 5-10: 2d8. CL 11-16: 3d8."
    out = surface(text)
    assert ("CL 5-10: 2d8" in out) is keeps_the_table, f"{surface.__name__}: {out!r}"
    # Even where the table goes, the rule that referred to it is left readable.
    assert "below" not in player_text.log_plain("deal the damage below: CL 1-4: 1d8. CL 5-10: 2d8.")


def test_cleaner_explains_cp_in_one_wording_everywhere():
    """CP stays CP in the data; every surface spells it out the same way."""
    assert player_text.explain_cp("Cost: 2 CP or 2 Stamina") == \
        "Cost: 2 cultivation points (your Path resource) or 2 Stamina"
    assert player_text.explain_cp("Cost: 2 CP", "Stamina") == "Cost: 2 Stamina"
    assert player_text.reading("no_cp_regain: (combat/gate4_engine.py) 2 CP") == \
        "no_cp_regain: 2 cultivation points (your Path resource)"


def test_newcomer_catalogue_builder_uses_the_same_cleaner():
    """One implementation: the static catalogue and the in-fight hover agree."""
    from tools import newcomer_text_data

    for key, text in list(printed_rules().items())[:400]:
        built = newcomer_text_data.plain(text)
        for pattern in (FACTORY_FIELD, PATH, DOUBLED_WORD):
            assert not pattern.search(built), _complain(key, built, pattern)
