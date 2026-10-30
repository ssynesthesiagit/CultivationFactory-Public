"""Typed duration ownership must survive prose rewording and public export."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from combat import typed_executor as executor
from tools.generate_duration_anchors import anchor_duration, apply_anchors

APP = Path(__file__).resolve().parents[1]


def _authority():
    return json.loads((APP / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())


def _durations(node):
    if isinstance(node, dict):
        if "duration" in node:
            yield node
        for key, value in node.items():
            if key == "duration_by_cl":
                for low, high, duration in value:
                    yield {**node, "duration": duration}
            else:
                yield from _durations(value)
    elif isinstance(node, list):
        for value in node:
            yield from _durations(value)


def _context(current="source", concentration=False):
    source = SimpleNamespace(entity_id="source", turns_started=3, team_id="friends")
    holder = SimpleNamespace(entity_id="holder", turns_started=6, team_id="foes")
    engine = SimpleNamespace(state=SimpleNamespace(current_actor_id=current, round_number=9, current_slot_index=1))
    ctx = SimpleNamespace(actor=source, engine=engine, numbers={"cl": 5},
                          typed={"duration": {"kind": "instant"}},
                          expires_on=lambda: "CONCENTRATION_END" if concentration else None)
    return ctx, holder


def test_every_duration_has_an_explicit_anchor():
    rows = list(_durations(_authority()["mechanics"]))
    assert len(rows) >= 12000
    for effect in rows:
        assert effect["duration"]["anchor"] in {"source", "holder", "current", "kind"}


def test_all_duration_expiries_ignore_presentation_text(monkeypatch):
    monkeypatch.setattr(executor, "counted_turns", lambda ctx, effect, expiry: expiry)

    def no_prose(*args, **kwargs):
        raise AssertionError("Typed authority duration read printed turn wording")

    monkeypatch.setattr(executor, "_turn_phrase", no_prose)
    monkeypatch.setattr(executor, "_own_words_state_one_lifetime", no_prose)
    for current in ("source", "holder"):
        for concentration in (False, True):
            ctx, holder = _context(current, concentration)
            for effect in _durations(_authority()["mechanics"]):
                scrambled = {**effect, "evidence": "Unrelated presentation.", "on": "Unrelated presentation."}
                for condition in (False, True):
                    expected = executor.effect_expiry(ctx, effect, holder, condition=condition)
                    assert executor.effect_expiry(ctx, scrambled, holder, condition=condition) == expected


def test_normal_authority_matches_previous_expiries(monkeypatch):
    """On the normal copy, compare all emitted tokens with the former prose path.

    Public exports deliberately scramble that oracle's prose; the invariant
    test above covers those copies without pretending the old oracle is valid.
    """
    if (APP.parent / "PUBLIC_TEST_MANIFEST.json").is_file():
        pytest.skip("Normal-copy oracle; scrambled export uses the no-prose invariant")
    monkeypatch.setattr(executor, "counted_turns", lambda ctx, effect, expiry: expiry)

    def legacy(node):
        if isinstance(node, dict):
            return {key: legacy(value) for key, value in node.items()
                    if key not in {"anchor", "edge", "overrides_clock"}}
        if isinstance(node, list):
            return [legacy(value) for value in node]
        return node

    effects = list(_durations(_authority()["mechanics"]))
    for current in ("source", "holder"):
        for concentration in (False, True):
            ctx, holder = _context(current, concentration)
            for effect in effects:
                previous = legacy(effect)
                for condition in (False, True):
                    assert executor.effect_expiry(ctx, effect, holder, condition=condition) == executor.effect_expiry(
                        ctx, previous, holder, condition=condition), effect.get("evidence")


def test_missing_anchor_is_a_build_error():
    with pytest.raises(ValueError, match="Missing typed duration anchor"):
        apply_anchors({"mechanics": {"synthetic": {"effects": [
            {"type": "speed", "duration": {"kind": "until_start_of_next_turn"}}
        ]}}}, {})


@pytest.mark.parametrize("kind,text", [
    ("until_start_of_next_turn", "until the end of its next turn"),
    ("until_start_of_next_turn", "until the end of your next turn"),
    ("until_end_of_next_turn", "until your next turn"),
    ("until_end_of_turn", "for the rest of the turn"),
    ("one_minute", "for the rest of the turn"),
    ("one_minute", "until its next turn"),
    ("one_minute", "Deafened for 1 minute; until its next turn"),
    ("special", "the triggering attack"),
    ("until_start_of_next_turn", ""),
])
def test_migration_preserves_previous_expiry_decisions(kind, text, monkeypatch):
    """Independent old dynamic-effect path is the migration's normal-copy oracle."""
    monkeypatch.setattr(executor, "counted_turns", lambda ctx, effect, expiry: expiry)
    effect = {"duration": kind, "evidence": text}
    typed = {**effect, "duration": anchor_duration(effect)}
    for current in ("source", "holder"):
        for concentration in (False, True):
            ctx, holder = _context(current, concentration)
            for condition in (False, True):
                assert executor.effect_expiry(ctx, typed, holder, condition=condition) == executor.effect_expiry(
                    ctx, effect, holder, condition=condition)


def test_typed_anchor_changes_neither_edge_nor_owner_when_words_change():
    ctx, holder = _context()
    row = {"duration": {"kind": "until_start_of_next_turn", "anchor": "holder", "edge": "end"},
           "evidence": "until the start of your next turn"}
    assert executor.stated_expiry(ctx, row, holder, condition=True) == "END_OF_TURN_AT:holder:7"
    row["evidence"] = ""
    assert executor.stated_expiry(ctx, row, holder, condition=True) == "END_OF_TURN_AT:holder:7"
