import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]


def _condition_keys_from_typed_authority() -> set[str]:
    """Every condition key the typed authority can hand the table, from the zone payloads and the
    ordinary ability effect lists alike."""
    keys: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "condition" and node.get("condition"):
                keys.add(str(node["condition"]).split(".")[-1])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    sources = list((APP / "authority" / "typed_mechanics" / "reviewed_final.d").rglob("*.json"))
    sources += list((APP / "combat" / "rules").rglob("*.json"))
    for path in sources:
        walk(json.loads(path.read_text(encoding="utf-8")))
    return keys


def _keys_in_zone_text_conditions() -> set[str]:
    """The keys the area reader actually shows, read from the generated presentation module rather
    than a copy (static/tabletop/zone-text-data.js CONDITION_READINGS, which zone-text.js re-exports)."""
    script = (
        "import('./static/tabletop/zone-text-data.js')"
        ".then(m => console.log(JSON.stringify(Object.keys(m.CONDITION_READINGS))))"
    )
    done = subprocess.run(["node", "--input-type=module", "-e", script], cwd=APP,
                          capture_output=True, text=True, check=True)
    return set(json.loads(done.stdout.strip().splitlines()[-1]))


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_zone_condition_text():
    """The area reader describes a condition instead of showing its key, says the mechanics the
    engine applies, and the paying-pool toast names the sheet control
    (node --test tests/zone_condition_text.test.mjs)."""
    result = subprocess.run(["node", "--test", "--test-reporter=tap",
                             str(Path(__file__).with_name("zone_condition_text.test.mjs"))],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_typed_condition_has_a_plain_reading():
    """A new condition key must arrive with its own wording, or the area reader would show it raw.
    This is the general guard behind the AUDIT6 fix, so a later key cannot silently leak."""
    missing = sorted(_condition_keys_from_typed_authority() - _keys_in_zone_text_conditions())
    assert not missing, f"zone-text-data.js has no plain reading for: {missing}"


def test_zone_readings_match_the_sheet_authority():
    """The area reader and the sheet's condition hover are one authority (MMX9r finding 3): a second
    hand-written dictionary is what let the two disagree about Stunned and Muffle. Regenerate with
    `python -m tools.newcomer_text_data` after changing a reading in combat/condition_text.py."""
    from tools.newcomer_text_data import build_condition_readings

    script = (
        "import {CONDITION_READINGS} from './static/tabletop/zone-text-data.js';"
        "console.log(JSON.stringify(CONDITION_READINGS));"
    )
    shown = subprocess.run(["node", "--input-type=module", "-e", script], cwd=APP,
                           capture_output=True, text=True, check=True)
    assert json.loads(shown.stdout) == build_condition_readings()


@pytest.mark.parametrize("source, expected", [
    (
        "It lasts while held (combat/ext/pin.py; until the GM ends it). "
        "The table does not apply damage; your Game Master rolls its damage.",
        ("Until the Game Master ends it.", "Your Game Master rolls its damage."),
    ),
    (
        "Your Game Master decides who is affected. "
        "It lasts while held (combat/ext/pin.py; until the GM ends it; "
        "the GM rolls its damage).",
        ("Your Game Master decides who is affected.", "Until the Game Master ends it.",
         "The Game Master rolls its damage."),
    ),
    (
        "The table does not apply these effects; your Game Master rolls its damage; "
        "your Game Master ends it.",
        ("Your Game Master rolls its damage.", "Your Game Master ends it."),
    ),
])
def test_plain_reading_keeps_distinct_manual_responsibilities(source, expected):
    """A manual expiry, damage roll and decision are separate player instructions (SOL83)."""
    from combat.condition_text import plain_reading

    shown = plain_reading(source)
    for instruction in expected:
        assert instruction in shown, shown
    assert "combat/" not in shown and "The table" not in shown, shown


def test_plain_reading_deduplicates_only_equivalent_manual_instructions():
    from combat.condition_text import MANUAL_NOTE, plain_reading

    shown = plain_reading(
        "Your Game Master rolls its damage. "
        "It lasts while held (combat/ext/pin.py; the GM rolls its damage; "
        "until the GM ends it; GM reminder). "
        "The table does not enforce these effects; your Game Master rolls its damage.")
    assert shown.count("rolls its damage") == 1, shown
    assert "Until the Game Master ends it." in shown, shown
    assert MANUAL_NOTE not in shown, shown
    generic = plain_reading("It lasts (combat/ext/pin.py; GM reminder; GM reminder).")
    assert generic.count(MANUAL_NOTE) == 1, generic
    assert plain_reading("It lasts (GM call; nothing on this table ends it).") == (
        "It lasts. " + MANUAL_NOTE)


# The three ways a Stone Womb shell ends early, which the engine enforces in
# combat/ext/stone_womb.py stone_shell_end and a player has to be able to plan around.
SHELL_ENDING_RULES = ("on healing", "a dismissal", "damage equal to 10 + the Source key ability modifier + Proficiency Bonus")


def test_plain_reading_keeps_the_rule_printed_beside_a_citation():
    """A note whose written subject was the build's file keeps what it said.

    Evidence reads "combat/ext/stone_womb.py ends it early on healing, a dismissal, or damage
    equal to 10 + the Source key modifier + PB": the file is the build naming its subject, and the
    predicate after it is the rule. Dropping the whole parenthetical took all three early-ending
    rules off the sheet, so the file goes and the rule stays (SOL123f1 review finding). The same
    judgement is the one ``player_text.plain()`` already made, so both cleaners now agree.
    """
    from combat.condition_text import plain_reading

    shown = plain_reading(
        "Stone Womb Preservation: the target cannot move or take actions while the shell stands"
        " (combat/ext/stone_womb.py ends it early on healing, a dismissal, or damage equal to"
        " 10 + the Source key modifier + PB).")
    # The engine's own shorthand: player_text.plain() is what spells "PB" and "Source key
    # modifier" out, so at this level the predicate is still the evidence sentence's wording. The
    # build wrote the file as the subject, so the rule reads as a sentence of its own.
    assert "It ends early on healing, a dismissal, or damage equal to 10 + the Source key modifier + PB" in shown, shown
    assert ".py" not in shown and "combat/" not in shown, shown
    # The ability name in the same note is kept too: the file is not what tells a player which
    # ability leaves them at Speed 0 (also asserted on the catalogue by HUNT100's own test).
    assert plain_reading("Speed 0 until the start of the holder's next turn (Rest Hold,"
                         " combat/ext/hold_still.py, which also carries its cover).") == (
        "Speed 0 until the start of the holder's next turn (Rest Hold).")
    # A rule in a sentence rather than a note is the same loss: the clause naming the file was cut,
    # and the rule written after it went with it.
    assert plain_reading("Silken Whip: the infused cloth is a Silken Whip until it is dismissed or"
                         " the fight ends; combat/ext/silken_whip.py offers its attack while it"
                         " stands.") == ("Silken Whip: the infused cloth is a Silken Whip until it is"
                                         " dismissed or the fight ends. It offers attack while it"
                                         " stands.")
    # A note that only mentions a file beside a Sphere or a build stamp is still provenance, so the
    # general fix cannot be "keep every parenthetical that names a file".
    assert plain_reading("Buried (Sphere of Sand)") == "Buried"
    assert plain_reading("It cannot breathe while held (combat/ext/gu_wrestling.py; GM call;"
                         " no Verbal-component-denial system on this table)") == (
        "It cannot breathe while held Your Game Master resolves it.")


def test_plain_reading_keeps_what_the_fight_already_does_for_you():
    """A sentence about the workshop acting on the creature is about the creature, not the build.

    Exhaustion's evidence ends "The table applies the penalties and defeat at level 6": the owner
    telling the player the fight tracks both, so they have nothing to adjudicate. "the table" is the
    workshop's word for the fight and goes; what the fight does is the part a player plans around
    and stays (SOL123f1 review finding).
    """
    from combat.condition_text import plain_reading

    shown = plain_reading("Exhaustion: each level reduces d20 Tests (attacks, ability checks and"
                          " saves) by 2 and Speed by 5 feet. At level 6 the creature dies."
                          " The table applies the penalties and defeat at level 6.")
    assert shown.endswith("The fight applies the penalties and defeat at level 6."), shown
    assert "the table" not in shown.casefold(), shown
    # What the workshop cannot do is the other way a sentence can open with its name, and a player
    # is never shown that: it is a limit of the build, not something that happens to them.
    assert plain_reading("The table cannot distinguish hands, so it applies Disadvantage to every"
                         " attack roll.") == ""
    assert plain_reading("The table blocks its own self-teleport abilities; the Game Master handles"
                         " portals.") == "The Game Master handles portals."


def test_stone_shell_zone_reading_says_how_the_protection_ends():
    """The area reader's generated copy, which is what a player hovers inside a lasting area.

    ``test_zone_readings_match_the_sheet_authority`` only proves the two copies agree, so it passes
    happily when both omit a rule; this asserts the rules themselves in the generated asset.
    """
    from combat.condition_text import zone_readings

    script = ("import {CONDITION_READINGS} from './static/tabletop/zone-text-data.js';"
              "console.log(JSON.stringify(CONDITION_READINGS.stone_shell));")
    done = subprocess.run(["node", "--input-type=module", "-e", script], cwd=APP,
                          capture_output=True, text=True, check=True)
    generated = json.loads(done.stdout.strip().splitlines()[-1])
    for rule in SHELL_ENDING_RULES:
        assert rule in generated, f"{rule} missing from the generated zone reading: {generated!r}"
        assert rule in zone_readings()["stone_shell"], rule
    # The engine mechanics are still stated after the reading, not instead of it.
    assert "It can't take actions" in generated and "Its Speed is 0" in generated, generated


def test_plain_reading_keeps_who_resolves_an_effect():
    """plain_reading() removes the workshop's own bookkeeping, but never who resolves an effect
    (MMX41 finding 1). Bleeding deals its damage only when the Game Master applies it, and the
    Thorn-Flesh Armory still sends that damage as a GM instruction, so a reading that dropped the
    clause would promise a roll the fight never makes."""
    from combat.condition_text import MANUAL_NOTE, READING, plain_reading, zone_readings

    # A whole sentence about the implementation still hands its decision to the Game Master.
    assert "Your Game Master decides." in plain_reading(
        "The table does not enforce these effects; your Game Master decides.")
    # So does a source that only names the Game Master as a workshop word.
    assert plain_reading(
        "It deals 2 damage after the first 10 feet moved, which this table has no trigger for"
        " -- GM-adjudicated.").endswith(MANUAL_NOTE)
    # Bookkeeping with no Game Master in it still goes: a player is not told what the engine lacks.
    assert "cannot distinguish hands" not in plain_reading(
        "The table cannot distinguish hands, so it applies Disadvantage to every attack roll.")
    # So does a note that only says the workshop's own word for it: the parenthetical goes, the
    # restatement stands.
    assert plain_reading(
        "It is immune until a short or long rest (combat/ext/gu_wrestling.py checks it;"
        " nothing clears it on rest yet -- GM reminder).").endswith(MANUAL_NOTE)
    # A manual expiry stated inside the same parenthetical as a file is lifted out, not dropped
    # with it: the reading still has to say who ends the effect.
    assert "Until the Game Master ends it" in plain_reading(
        "It lasts while it is held (combat/ext/pin.py stores it; until the GM ends it).")
    # The name is spelled out and the parenthetical's file is not.
    lifted = plain_reading("It lasts while it is held (combat/ext/pin.py; until the GM ends it).")
    assert ".py" not in lifted and "combat/ext" not in lifted, lifted
    # The reading says who resolves it once, not once per dropped clause.
    once = plain_reading("Your Game Master decides. The table does not enforce these effects;"
                         " your Game Master decides.")
    assert once.count("Game Master") == 1, once
    # The generated Bleeding reading a player hovers keeps the qualification, and it comes from the
    # rules row's own "GM-adjudicated" rather than from a hand-written copy that could drift.
    bleeding = zone_readings()["bleeding"]
    assert bleeding.endswith(MANUAL_NOTE), bleeding
    assert "deals Proficiency Bonus damage" in bleeding, bleeding
    assert "bleeding" not in READING, "Bleeding's reading is the rules authority's, not a copy of it"
    # The same, for the reading whose qualification sat inside a source-bearing parenthetical: the
    # immunity is stored as UNTIL_REMOVED and checked on later saves, so a player must not expect
    # resting to end it by itself.
    immunity = zone_readings()["grandstanding_slam_immune"]
    assert immunity.endswith(MANUAL_NOTE), immunity
    assert "immune to it until a short or long rest" in immunity, immunity
    assert "reminder" not in immunity, immunity
    # Every reading stays a player sentence: no file, lane or lock-round note survives either.
    for key, text in zone_readings().items():
        assert "combat/" not in text and "lock round" not in text, f"{key} leaks a workshop note: {text}"
