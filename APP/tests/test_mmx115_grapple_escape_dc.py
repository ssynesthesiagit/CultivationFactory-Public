"""MMX115: the escape DC a creature must beat is the owner's printed one, and it is shown.

HUNT113 #1 reported the 2024 book value (DC 5 + Strength) as the expected escape DC.
The owner's printed text overrides that: authority/typed_mechanics/rules_text.json
WRESTLING_BASE_WRESTLING_SAVE_DC_AND_ESCAPE_DC sets "8 + Strength modifier + Proficiency
Bonus" as the *default* grapple escape DC and lets a feature replace it, and
WRESTLING_BASE_GRAPPLING_REMINDER has a Grappled creature make the check "against the
grapple's escape DC". So the stored number is right, and the defect this lane fixes is that
the table never showed it.

MMX115f1 review fixes, covered here:

* one escape roll covers a *set* of holds -- every Pin if there is one, otherwise every
  grapple -- and compares against the highest DC in that set, so a hold's own number is not
  always the number the creature must reach (``test_two_holding_creatures_beat_the_highest``,
  ``test_a_pin_is_broken_before_the_grapple``);
* the printed formula is the ordinary default, not every hold's number, and a hold may instead
  ask for a saved throw (``test_a_hold_with_its_own_dc_shows_that_number_not_the_formula``,
  ``test_save_style_hold_descriptor_names_the_stored_save``);
* the advice is inert for a creature with no hold (``test_unrelated_status_never_offers_an_escape``).

Most are table-level tests: a real Grapple is pressed through the real TabletopService
against real compiled characters, and the assertions are on what the table hands a player.
The Serpent descriptor test uses the real compiled Living Painting and the real ``coiling_grip``
effect, because that is the only shipped hold whose rules repeat a saving throw and it needs
a summon; they still render through the real ``status_description`` hook.
"""

from __future__ import annotations

import re

import pytest

from tests.hunt51_grapple_support import IDS, fight, grapple, on_turn, send, verify_reloaded

PB = 4  # the test harness sheets compile at proficiency bonus 4
GRAPPLER, VICTIM = IDS[0], IDS[2]
SIX_IDS = [*IDS[:2], "actor:factory.luna38-e", *IDS[2:]]  # the harness's six-actor roster
ALLY_STEP = {"x": 5, "y": 3}  # a free square next to the held creature, five squares from the ally
PINNED = "condition:typed.pinned"
GRAPPLED = "condition:typed.grappled"


def printed_escape_dc(str_score: int, pb: int = PB) -> int:
    """The owner's printed grapple escape DC: 8 + Strength modifier + Proficiency Bonus."""
    return 8 + pb + (str_score - 10) // 2


def fail_every_save(monkeypatch):
    """Script each saving throw to 1 on the engine that actually rolls it.

    The grapple must land for every DC under test, and the DC under test must never be
    changed to achieve that, so the target's save is forced to fail instead.
    """
    from combat.gate2_engine import Gate2Engine
    from tests.h1_support import script

    original = Gate2Engine._roll_save

    def failing(engine, *args, **kwargs):
        script(engine, [1, *([1] * 40)])
        return original(engine, *args, **kwargs)

    monkeypatch.setattr(Gate2Engine, "_roll_save", failing)


def script_check(monkeypatch, face: int):
    """Roll exactly ``face`` on the d20 for the escape check, leaving every other roll alone.

    The escape is the only check on this path (``combat/ext/escape_checks.py`` draws
    ``engine.roller.d20(reason="CHECK:...")``), so scripting that one die scripts the escape.
    This is a dice fixture for the test, not a change to shipped resolution: the recorded
    total is still read back from the table's own CHECK_ROLLED event in each test.
    """
    from combat.gate2_rolls import DeterministicRollAuthority

    original = DeterministicRollAuthority.d20

    def checked(self, *, modifier, actor_id, reason, mode="NORMAL"):
        if str(reason).startswith("CHECK:"):
            queue, die = [face] * (2 if mode in {"ADVANTAGE", "DISADVANTAGE"} else 1), self._die

            def scripted(sides, _die=die, _queue=queue):
                if not _queue:
                    return _die(sides)
                counter = self.counter
                self.counter += 1
                return min(_queue.pop(0), sides), counter

            self._die = scripted
        return original(self, modifier=modifier, actor_id=actor_id, reason=reason, mode=mode)

    monkeypatch.setattr(DeterministicRollAuthority, "d20", checked)


def escape_button():
    return lambda option: str(option.get("label", "")).startswith("Escape grapple")


def approach_and_grapple(table, match, ally: str, victim: str, destination: dict):
    """Walk the ally next to the victim with the free part of its turn, then Grapple with the Action.

    The harness's second ally is set down across the map, so it has to close the distance
    first; moving costs no Action, so the Grapple still fits in the same turn.
    """
    on_turn(table, match, ally)
    send(table, match, lambda option: option.get("destination") == destination)
    send(table, match, grapple(victim))


def condition_details(table, match, victim: str, condition_id: str = GRAPPLED) -> list[str]:
    """Every text the table shows for one of a creature's conditions, via the real state path."""
    presentation = table.state(match)["presentation"]
    row = next(actor for actor in presentation["actors"] if actor.get("entity_id") == victim)
    return [condition.get("detail", "") for condition in row.get("conditions") or []
            if condition.get("condition_id") == condition_id]


def held_conditions(service, match, victim: str) -> list:
    return [condition for condition in service._load_session(match).engine.state.actors[victim].conditions.values()
            if condition.condition_id in (GRAPPLED, PINNED)]


def escape_rolls(service, match, victim: str) -> list[dict]:
    """The escape checks the table actually rolled for ``victim``, newest last."""
    engine = service._load_session(match).engine
    return [event.payload for event in engine.events
            if event.event_type == "CHECK_ROLLED" and event.actor_id == victim]


def land_grapple(tmp_path, monkeypatch, name: str, str_score: int, *, grappler: str = GRAPPLER):
    """Press the real Grapple button and return the service, match and the stored hold."""
    fail_every_save(monkeypatch)
    user, service, table, match, ids = fight(tmp_path, name, actor_scores={grappler: str_score})
    victim = VICTIM
    on_turn(table, match, grappler)
    send(table, match, grapple(victim))
    hold = next(c for c in service._load_session(match).engine.state.actors[victim].conditions.values()
                if c.condition_id == GRAPPLED)
    return user, service, table, match, ids, grappler, victim, hold


@pytest.mark.parametrize("str_score", [10, 18, 30])
def test_escape_dc_is_the_owners_printed_number_and_is_shown(tmp_path, monkeypatch, str_score):
    """The stored DC follows the owner's formula, and the player's status names that number."""
    user, service, table, match, ids, grappler, victim, hold = land_grapple(tmp_path, monkeypatch, f"escape-dc-{str_score}", str_score)
    expected = printed_escape_dc(str_score)

    assert hold.data["escape_dc"] == expected, (
        f"stored escape DC {hold.data['escape_dc']} is not the owner's printed {expected} "
        f"(8 + STR modifier {(str_score - 10) // 2} + PB {PB})")

    detail = condition_details(table, match, victim)[0]
    assert f"DC {expected}" in detail, f"the number the roll must reach is not shown: {detail!r}"
    assert "Athletics" in detail and "Acrobatics" in detail
    assert str(hold.data["escape_dc"]) in detail
    assert "this hold" in detail, f"the number must be named as this hold's, not the one to reach: {detail!r}"

    # A creature held once needs no advice about sets, so the pill stays one plain sentence.
    assert "Note:" not in detail, f"a single hold grew combined-hold advice it cannot act on: {detail!r}"

    # Inert for a fight whose creatures own no such ability: no unrelated creature gained a hold.
    held = [a.entity_id for a in service._load_session(match).engine.state.actors.values() if a.conditions]
    assert held == [victim], f"an unrelated creature gained a hold: {held}"
    verify_reloaded(user, service, match)


def test_escape_dc_tracks_the_grappler_not_the_escaping_creature(tmp_path, monkeypatch):
    """A weak grappler sets the number; the strong creature's own Strength does not."""
    _user, _service, _table, _match, _ids, _grappler, _victim, weak = land_grapple(tmp_path, monkeypatch, "escape-dc-weak", 10)
    _user2, _service2, _table2, _match2, _ids2, _grappler2, _victim2, strong = land_grapple(tmp_path, monkeypatch, "escape-dc-strong", 30)
    assert weak.data["escape_dc"] == 8 + PB + 0
    assert strong.data["escape_dc"] == 8 + PB + 10
    assert strong.data["escape_dc"] - weak.data["escape_dc"] == 10, "the number must follow the grappler's Strength"


def test_escape_button_qualifies_the_printed_formula(tmp_path, monkeypatch):
    """The button cannot see who holds the reader, so it states a default and its exceptions."""
    _user, _service, table, match, ids, _grappler, _victim, _hold = land_grapple(tmp_path, monkeypatch, "escape-button", 18)
    on_turn(table, match, VICTIM)
    menu = table.state(match)["menu"]
    group = next(group for group in menu.get("actions", []) if "Escape grapple" in str(group.get("label", "")))
    text = f"{group.get('label', '')} {group.get('description', '')}"
    # The formula is the owner's printed one, marked as the ordinary case rather than universal.
    assert "8 + their Strength modifier + their proficiency bonus" in text
    assert "An ordinary grapple uses" in text, f"the formula is advertised as universal: {text!r}"
    # Some holds print their own DC, and some repeat a saved throw instead of asking a check.
    assert "may set its own DC" in text and "repeat a saving throw" in text, (
        f"the button hides the save-style and own-DC holds: {text!r}")
    # It must not promise the pill is the exact number when a Pin or a second hold governs it.
    assert "The exact DC you must reach" not in text, f"the button still promises one exact DC: {text!r}"
    assert "highest DC among your pins, or among your grapples if you are not pinned" in text, (
        f"the button does not scope the number to the holds this Action can end: {text!r}")
    assert "Pinned creature breaks the pin first" in text, f"the button hides the pin rule: {text!r}"


def double_grapple(tmp_path, monkeypatch, name: str):
    """Two allies of different Strength hold one creature, so its two holds set two DCs.

    Six actors: the harness splits them into the two players' teams, so two allies can reach
    the held creature. The strong ally's grapple is DC 16 and the weak ally's is DC 12, and
    the escape check carries no bonus, so a d20 of 14 sits between them and 18 clears both.
    """
    fail_every_save(monkeypatch)
    wide = SIX_IDS
    _user, service, table, match, ids = fight(tmp_path, name, six=True,
                                              actor_scores={wide[0]: 18, wide[2]: 10})
    first, second, victim = ids[0], ids[2], ids[3]
    on_turn(table, match, first)
    send(table, match, grapple(victim))
    approach_and_grapple(table, match, second, victim, ALLY_STEP)
    holds = held_conditions(service, match, victim)
    dcs = sorted(condition.data["escape_dc"] for condition in holds)
    assert len(holds) == 2, f"the victim must be held twice for this test: {holds}"
    assert dcs == [printed_escape_dc(10), printed_escape_dc(18)] == [12, 16], (
        f"the two holds must set two different DCs: {dcs}")
    return service, table, match, victim, dcs


def test_each_hold_names_its_own_dc_and_says_which_to_reach(tmp_path, monkeypatch):
    """MMX115f1: every pill says what one escape roll must really beat.

    The easier hold's pill names the easier number, and used to promise that reaching it was
    all that was needed. It must name its own number *and* say that one roll has to reach the
    highest of the holds and frees the creature from all of them.
    """
    _service, table, match, victim, dcs = double_grapple(tmp_path, monkeypatch, "combined-advice")
    details = condition_details(table, match, victim)
    assert len(details) == 2, f"both holds must show their own status: {details}"
    for detail in details:
        assert "Several creatures are holding" in detail, f"no combined-hold advice: {detail!r}"
        assert "highest of those DCs" in detail, f"the number to reach is not named: {detail!r}"
        assert "all of them at once" in detail, f"a success covering every hold is not stated: {detail!r}"
    shown = sorted(int(re.search(r"against DC (\d+)", detail).group(1)) for detail in details)
    assert shown == dcs, f"each pill must name its own hold's number: {shown} vs {dcs}"


def test_reaching_the_easier_holds_dc_does_not_get_free(tmp_path, monkeypatch):
    """MMX115f1: one roll covers both holds and is compared against the higher DC.

    A total of 14 clears the DC-12 hold and is still a failure, because the single roll the
    table makes is compared against the DC-16 hold; nothing is removed.
    """
    service, table, match, victim, dcs = double_grapple(tmp_path, monkeypatch, "combined-fail")
    script_check(monkeypatch, 14)
    on_turn(table, match, victim)
    send(table, match, escape_button())
    roll = escape_rolls(service, match, victim)[-1]
    assert roll["actor"]["dice"] == [14] and roll["actor"]["modifier"] == 0
    assert dcs[0] < roll["actor"]["total"] < dcs[1], (
        f"the scripted total must sit between the two DCs: {roll['actor']}")
    assert roll["dc"] == dcs[1], f"one roll must be compared against the highest DC in the set: {roll}"
    assert roll["success"] is False, "reaching the easier hold's DC freed the creature"
    assert len(held_conditions(service, match, victim)) == 2, "a failed escape removed a hold"


def test_reaching_the_higher_dc_frees_the_creature_from_both_holds(tmp_path, monkeypatch):
    """MMX115f1: a success ends every hold in the set, not just the one whose DC was shown.

    A separate fight from the failing roll because the escape costs 1 Stamina, so this sheet
    affords one attempt.
    """
    service, table, match, victim, dcs = double_grapple(tmp_path, monkeypatch, "combined-free")
    script_check(monkeypatch, 18)
    on_turn(table, match, victim)
    send(table, match, escape_button())
    roll = escape_rolls(service, match, victim)[-1]
    assert roll["dc"] == dcs[1] and roll["success"] is True
    assert held_conditions(service, match, victim) == [], "a success must free every hold in the set"


def test_a_pin_is_broken_before_the_grapple(tmp_path, monkeypatch):
    """MMX115f1: a Pin is its own set, so the roll is compared against the Pin's DC.

    The harness's fixture Pin is created through the shipped typed-condition pipeline with a
    DC of 30; the grapple's own DC is 12. A total of 19 clears the grapple's number and
    still fails, because the single roll must reach the Pin's.
    """
    fail_every_save(monkeypatch)
    # The harness's fixture Pin is created through the shipped typed-condition pipeline
    # with a DC of 30; a weak ally's grapple sets 12. Six actors so a second ally can reach.
    wide = SIX_IDS
    _user, service, table, match, ids = fight(tmp_path, "pin-first", six=True, fixture_conditions=("pinned",),
                                              actor_scores={wide[0]: 10, wide[2]: 10})
    pinner, ally, victim = ids[0], ids[2], ids[3]
    on_turn(table, match, pinner)
    send(table, match, lambda option: "Fixture: Pinned" in str(option.get("label", ""))
         and option.get("target_ids") == [victim])
    approach_and_grapple(table, match, ally, victim, ALLY_STEP)

    pin = next(c for c in held_conditions(service, match, victim) if c.condition_id == PINNED)
    grip = next(c for c in held_conditions(service, match, victim) if c.condition_id == GRAPPLED)
    assert pin.data["escape_dc"] == 30 and grip.data["escape_dc"] == printed_escape_dc(10) == 12

    for detail in condition_details(table, match, victim) + condition_details(table, match, victim, PINNED):
        assert "a Pin is broken first" in detail, f"the pin rule is not stated on the pill: {detail!r}"
        assert "still needs its own escape" in detail, f"the second escape is not stated: {detail!r}"

    script_check(monkeypatch, 19)
    on_turn(table, match, victim)
    send(table, match, escape_button())
    roll = escape_rolls(service, match, victim)[-1]
    assert roll["actor"]["total"] == 19 > 12, "the scripted total must clear the grapple's own DC"
    assert roll["dc"] == 30, f"the Pin's DC must govern the single roll: {roll}"
    assert roll["success"] is False, "a total under the Pin's DC must not free the creature"
    assert len(held_conditions(service, match, victim)) == 2, "a failed escape removed a hold"


def test_a_hold_with_its_own_dc_shows_that_number_not_the_formula(tmp_path, monkeypatch):
    """MMX115f1: the printed formula is the ordinary default, so the pill shows what is stored.

    A Talent may set its own escape DC. The button may only quote the owner's default, so the
    two must not be confused: the status names the stored number, and the button says plainly
    that a default is not every hold's number.
    """
    fail_every_save(monkeypatch)
    user, service, table, match, _ids = fight(tmp_path, "own-dc", actor_scores={GRAPPLER: 10},
        talents=("tianxia.talent.gravity.black_star_grip",))
    victim = VICTIM
    on_turn(table, match, GRAPPLER)
    send(table, match, lambda option: option.get("label") == "Black-Star Grip"
         and option.get("target_ids") == [victim])
    hold = held_conditions(service, match, victim)[0]
    assert hold.data["escape_dc"] == 30 != printed_escape_dc(10)
    detail = condition_details(table, match, victim)[0]
    assert "DC 30" in detail and "this hold sets" in detail
    on_turn(table, match, victim)
    menu = table.state(match)["menu"]
    group = next(group for group in menu.get("actions", []) if "Escape grapple" in str(group.get("label", "")))
    button = f"{group.get('label', '')} {group.get('description', '')}"
    assert "An ordinary grapple uses 8 + their Strength modifier + their proficiency bonus" in button
    assert "the hold's own rule wins" in button, f"an ability's own DC must be acknowledged: {button!r}"
    verify_reloaded(user, service, match)


def test_save_style_hold_descriptor_names_the_stored_save():
    """Descriptor-only coverage: a save-style hold names its stored save and default set advice.

    The Living Painting's Serpent is the only shipped hold that asks for a saved throw
    (``combat/ext/painting_forms.coiling_grip`` stores ``escape_save``), and creating one
    needs a summon, so this renders the real stored hold through the real hook rather than
    pressing it through a table or testing resolution. A creature held twice -- once by a grapple that asks for a
    check, once by the Serpent -- is told the roll is a saved throw, which is what
    ``typed_executor.block_escape_grapple`` does for the whole set.
    """
    from tests import test_sys_menus_forms as forms  # the real compiled Living Painting

    engine, serpent, foe, _events = forms._serpent_grip()
    grip = forms._held(foe, "condition:typed.grappled")[0]
    assert grip.data["escape_save"] == "STR", f"the shipped hold must store the save: {grip.data}"
    row = {"condition_id": grip.condition_id}

    from combat import ext
    from combat.ext.escape_dc_text import escape_dc_description

    alone = escape_dc_description(engine, foe, row, dict(grip.data))["text"]
    assert f"repeat the Strength saving throw against DC {grip.data['escape_dc']}" in alone, (
        f"a save-style hold must name its saved throw: {alone!r}")
    assert "Athletics" not in alone, f"a save-style hold must not promise a check: {alone!r}"

    engine._apply_condition(foe, "condition:typed.grappled", "test:grapple", serpent.entity_id,
                            expires_on="UNTIL_REMOVED", data={"escape_dc": 12, "reach_ft": 5})
    mixed = escape_dc_description(engine, foe, row, {"escape_dc": 12, "reach_ft": 5})["text"]
    assert "make a Strength (Athletics) or Dexterity (Acrobatics) check" in mixed, (
        f"the grapple's own hold still asks for a check: {mixed!r}")
    assert "Several creatures are holding" in mixed, f"the second hold is not named: {mixed!r}"
    assert "repeat the Strength saving throw instead" in mixed, (
        f"a set containing a save-style hold must say the roll is a save: {mixed!r}")


def test_unrelated_status_never_offers_an_escape(tmp_path, monkeypatch):
    """Inertness is about text as well as state: an unrelated status gains no escape advice."""
    fail_every_save(monkeypatch)
    _user, service, table, match, _ids = fight(tmp_path, "unrelated-status", fixture_conditions=("blinded",))
    on_turn(table, match, GRAPPLER)
    send(table, match, lambda option: "Fixture: Blinded" in str(option.get("label", ""))
         and option.get("target_ids") == [VICTIM])

    blinded = condition_details(table, match, VICTIM, "condition:typed.blinded")
    assert blinded, "the blinded creature must show its own status for this test"
    for detail in blinded:
        assert "To get free" not in detail, f"an unrelated status offered an escape: {detail!r}"
        assert "escape DC" not in detail and "saved throw" not in detail, (
            f"an unrelated status offered an escape Difficulty Class: {detail!r}")
    assert held_conditions(service, match, VICTIM) == [], "the blinded creature is not held"


def test_escape_sentence_only_appears_for_a_hold_with_a_dc():
    """The plug-in says nothing for state that stores no escape DC."""
    from combat.ext.escape_dc_text import escape_dc_description, escape_sentence

    assert escape_sentence({}) == ""
    assert escape_sentence({"escape_dc": None}) == ""
    assert escape_dc_description(None, None, {"condition_id": "condition:typed.mark.blinded"}, {"talent": "x"}) is None
    sentence = escape_sentence({"escape_dc": 12})
    assert "DC 12" in sentence and "Action" in sentence
    # A hold whose own rule repeats a saving throw says so instead of naming a check.
    saved = escape_sentence({"escape_dc": 14, "escape_save": "STR"})
    assert "saving throw" in saved and "Strength" in saved
