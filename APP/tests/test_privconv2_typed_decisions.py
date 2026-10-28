"""The four decisions the fight used to read off the printed prose are typed data (PRIVCONV2).

The public copy of the rules scrambles every printed sentence -- a run of eight or more words becomes pseudo-words
and a capitalised word keeps only its first letter -- so any decision the engine re-derives from that text stops
being decided there, silently and only on the public tests. PRIVCONV1's bisects named four such decisions:

  * Defensive Discipline menus (combat/ext/defensive_disciplines.py, printed_options),
  * the end-of-turn anchor of a printed condition duration (combat/typed_executor.py, _turn_phrase),
  * the pool a printed cost is charged in (combat/decision_text.py, cost_as_charged),
  * which abilities are Special Attacks (combat/ext/special_attacks.py, special_ids).

Each one now reads a typed field on the reviewed record (authority/typed_mechanics/reviewed_final.d/*.json,
carried into authority/Tianxia_Typed_Mechanics_Authority_R1.json by tools/build_typed_mechanics_authority.py).
These tests fail the old prose reader at the reader -- the module that used to be consulted is patched to raise --
so a decision that quietly starts reading the printed text again cannot pass here on a readable copy.

Behaviour on the readable copy is unchanged: the typed values are the printed values (asserted too), and an
effect or a record that states no typed value keeps the wording path it had.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text(encoding="utf-8"))
MECHANICS = AUTHORITY["mechanics"]

TEMPERED = "tianxia.path.body_refining.feature.tempered_response"
CULTIVATED = "tianxia.path.qi_cultivation.feature.cultivated_response"
BEAST = "tianxia.talent.ink.painted_beast"
BEAUTY = "BEAUTY_BASE_CATCH_THE_EYE"


def _scrambled_prose(*_args, **_kwargs):
    raise AssertionError("this decision read the printed rules text, which the public copy scrambles (PRIVCONV2)")


def test_defensive_discipline_menu_is_typed_data(monkeypatch):
    """AUTO1's "Choose one Defensive Discipline" menu comes from the record, not from the printed headings."""
    import combat.factory_compiler as compiler
    from combat.ext import defensive_disciplines as disc

    monkeypatch.setattr(compiler, "_rules_text", _scrambled_prose)
    disc._menu.cache_clear()
    try:
        for feature_id in (TEMPERED, CULTIVATED):
            typed = [(row["name"], row["ability"]) for row in MECHANICS[feature_id]["disciplines"]]
            assert len(typed) >= 3, f"{feature_id} lost its Disciplines"
            assert disc.printed_options(feature_id) == typed
        # The printed Discipline name rides along, so the button reads as the rules do.
        assert disc._label(TEMPERED, "STR") == "Tempered Response: Strength (Rooted Frame)"
    finally:
        disc._menu.cache_clear()


def test_special_attack_ids_are_typed_data(monkeypatch):
    """Special Attacks are the records marked special_attack; no printed phrase decides it."""
    from combat.ext import special_attacks

    original_read_text = Path.read_text

    def reject_rules_text(path, *args, **kwargs):
        if Path(path).name == "rules_text.json":
            raise AssertionError("Special Attack discovery read printed rules text")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", reject_rules_text)
    special_attacks.special_ids.cache_clear()
    try:
        typed = {key for key, row in MECHANICS.items()
                 if isinstance(row, dict) and row.get("special_attack") is True}
        assert typed, "no record is marked as a Special Attack"
        assert special_attacks.special_ids() == typed
    finally:
        special_attacks.special_ids.cache_clear()
    # The slot suite's own abilities are among them (their printed text says "Special Attack").
    for mechanic_id in ("BRUTE_BASE_BRUTAL_SHOVE", "WATER_BASE_WATER_LASH"):
        assert mechanic_id in typed, f"{mechanic_id} lost its Special Attack marker"


def test_printed_summon_cost_is_typed_data():
    """HUNT 114 finding 3: the button states the pool the fight charges, from the record's printed_cost."""
    from combat.decision_text import cost_as_charged, reviewed_printed_cost

    record = MECHANICS[BEAST]
    assert record["printed_cost"] == {"amount": 4, "pool": "cultivation points"}
    costs = [{"resource_id": "resource:core.qi", "amount": 4}]
    row = {"source_definition_id": "action:typed.tianxia.talent.ink.painted_beast.attack", "parameters": {}}
    printed = reviewed_printed_cost(row)
    assert printed == record["printed_cost"]

    # The readable copy prints "Cost: 4 cultivation points" and is restated as the pool charged, exactly as before.
    text = "Painted Beast\n**Cost:** 4 cultivation points\nMake one attack."
    readable = cost_as_charged(text, costs)
    assert readable == "Painted Beast\n**Cost:** 4 Qi\nMake one attack."
    assert cost_as_charged(text, costs, printed) == readable
    # The scrambled copy prints no cost line at all; the record's own figure still reaches the button.
    scrambled = cost_as_charged("Painted Beast\nA Vbggq wwqz nrrf mmm.", costs, printed)
    assert "Cost: 4 Qi." in scrambled and "cultivation points" not in scrambled
    # A record that states no printed cost keeps the old handling: no cost line is invented for it.
    assert reviewed_printed_cost({"source_definition_id": "action:typed.some.other", "parameters": {}}) is None
    assert cost_as_charged("Slash\nMake one attack.", costs) == "Slash\nMake one attack."


def _captivated():
    for effect in MECHANICS[BEAUTY]["effects"]:
        for on_fail in effect.get("on_fail") or ():
            if on_fail.get("condition") == "captivated":
                return on_fail
    raise AssertionError("Catch the Eye no longer states its Captivated condition")


def test_printed_condition_duration_anchor_is_typed_data(monkeypatch):
    """The end of your next turn is a typed duration on the record; the printed words are prose."""
    from combat import typed_executor

    effect = _captivated()
    assert effect["duration"] == {"kind": "until_end_of_your_next_turn", "anchor": "source"}
    assert typed_executor.stated_turn_anchor(effect["duration"]) == ("end", "source")
    # A duration that states no anchor keeps the wording path (its table anchor already says the same).
    assert typed_executor.stated_turn_anchor({"kind": "until_end_of_your_next_turn"}) is None
    assert typed_executor.stated_turn_anchor({"kind": "lasts_the_fight"}) is None

    ctx = SimpleNamespace(actor=SimpleNamespace(entity_id="actor:you", turns_started=3),
                          engine=SimpleNamespace(state=SimpleNamespace(current_actor_id="actor:you")))
    monkeypatch.setattr(typed_executor, "_turn_phrase", _scrambled_prose)
    assert typed_executor.stated_expiry(ctx, effect, None) == "END_OF_SOURCE_TURN_AT:4"
    # A duration that states no anchor still reads its wording, because no record's lifetime may move because of
    # this: with unreadable words there is nothing to read and no other source is invented.
    monkeypatch.setattr(typed_executor, "_turn_phrase", lambda *_args, **_kwargs: None)
    plain = dict(effect, duration={"kind": "until_end_of_your_next_turn"})
    assert typed_executor.stated_expiry(ctx, plain, None) is None
