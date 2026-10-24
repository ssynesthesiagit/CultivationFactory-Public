"""Regressions for Finding 4 (Sol's round-2 review): d1_validate.py must
catch a label whose bound payload disagrees with chosen, a teacher_label
whose chosen doesn't begin with built_in_pick, and a literal teacher-hint
name leaking into state -- none of this had a dedicated test before."""
from tools import d1_validate as d1v
import pytest


def _turn_record(**overrides):
    record = {
        "record_id": "r", "lineage_id": "l", "match_id": "m", "decision_id": "d", "kind": "TURN",
        "engine_revision": "x", "menu_hash": "h" * 16, "original_menu_hash": "h" * 16,
        "state": "You see a foe.\nReply A-B\nA) Move to (3, 4)\nB) End turn here",
        "options": {"A": "Move to (3, 4)", "B": "End turn here"},
        "alias_payload": {"A": {"plan": ["move", "end"]}, "B": {"plan": ["end"]}},
        "label": "A", "teacher_label": "A", "chosen": ["move", "end"], "built_in_pick": "move",
        "fallback": False, "origin": "contemporaneous",
    }
    record.update(overrides)
    return record


def _reaction_record(**overrides):
    record = {
        "record_id": "r", "lineage_id": "l", "match_id": "m", "decision_id": "d", "kind": "REACTION",
        "engine_revision": "x", "menu_hash": "h" * 16, "original_menu_hash": "h" * 16,
        "state": "A foe attacks. Reply A-B\nA) Use your shield\nB) Decline",
        "options": {"A": "Use your shield", "B": "Decline"},
        "alias_payload": {"A": {"selection": "USE", "option_ids": ["shield"], "spend": 0},
                          "B": {"selection": "DECLINE", "option_ids": [], "spend": 0}},
        "label": "A", "teacher_label": "A",
        "chosen": {"selection": "USE", "option_ids": ["shield"], "spend": 0},
        "built_in_pick": {"selection": "USE", "option_ids": ["shield"], "spend": 0},
        "fallback": False, "origin": "contemporaneous",
    }
    record.update(overrides)
    return record


# ---- a correct record of each kind must validate clean ----

def test_validate_record_accepts_a_consistent_turn_record():
    assert d1v.validate_record(_turn_record()) == []


def test_validate_record_accepts_a_consistent_reaction_record():
    assert d1v.validate_record(_reaction_record()) == []


def test_validate_record_accepts_a_null_teacher_label_regardless_of_chosen():
    # teacher_label is None means the built-in's own pick was never offered
    # (budget packing dropped it) -- chosen is then free to disagree with
    # built_in_pick, and that must not be flagged. Label's own payload must
    # still agree with chosen (a separate, always-required invariant).
    record = _turn_record(teacher_label=None, chosen=["other", "end"], built_in_pick="move",
                          alias_payload={"A": {"plan": ["other", "end"]}, "B": {"plan": ["end"]}})
    assert d1v.validate_record(record) == []


# ---- Finding 4a: label's bound payload must equal chosen ----

def test_validate_record_rejects_a_label_whose_payload_disagrees_with_chosen_turn():
    record = _turn_record(chosen=["something-else", "end"])
    problems = d1v.validate_record(record)
    assert any("does not match chosen" in p for p in problems)


def test_validate_record_rejects_a_label_whose_payload_disagrees_with_chosen_reaction():
    record = _reaction_record(chosen={"selection": "DECLINE", "option_ids": [], "spend": 0})
    problems = d1v.validate_record(record)
    assert any("does not match chosen" in p for p in problems)


# ---- Finding 4b: teacher_label set implies chosen begins with built_in_pick ----

def test_validate_record_rejects_a_teacher_label_whose_chosen_does_not_begin_with_built_in_pick_turn():
    record = _turn_record(built_in_pick="something-else")
    problems = d1v.validate_record(record)
    assert any("does not begin with built_in_pick" in p for p in problems)


def test_validate_record_rejects_a_teacher_label_whose_chosen_does_not_match_built_in_pick_reaction():
    record = _reaction_record(built_in_pick={"selection": "DECLINE", "option_ids": [], "spend": 0})
    problems = d1v.validate_record(record)
    assert any("does not begin with built_in_pick" in p for p in problems)


# ---- Finding 4c: explicit teacher hints of any length must be rejected ----

def test_validate_record_rejects_a_literal_built_in_pick_hint_in_state_regardless_of_length():
    record = _turn_record(state=_turn_record()["state"] + "\n(debug: built_in_pick=move)")
    problems = d1v.validate_record(record)
    assert any("built_in_pick" in p and "literal teacher-hint name" in p for p in problems)


def test_validate_record_rejects_a_literal_teacher_label_hint_in_state_regardless_of_length():
    record = _turn_record(state=_turn_record()["state"] + "\n(debug: teacher_label=A)")
    problems = d1v.validate_record(record)
    assert any("teacher_label" in p and "literal teacher-hint name" in p for p in problems)


def test_validate_record_still_rejects_a_short_raw_secret_value_once_it_is_a_hint_name():
    # A raw chosen/built_in_pick *value* like "USE" (below MIN_SECRET_LENGTH)
    # is legitimately allowed as menu/enum text (see the chosen/built_in_pick
    # leak check); but the hint-name check has no length threshold, so a
    # leaked field *name* must still be caught even though "USE" alone is fine.
    record = _reaction_record()
    assert d1v.validate_record(record) == []  # the "USE" selection text alone is fine
    record["state"] += "\nteacher_label"
    problems = d1v.validate_record(record)
    assert any("literal teacher-hint name" in p for p in problems)


@pytest.mark.parametrize("builder", [_turn_record, _reaction_record])
def test_teacher_alias_itself_must_bind_to_the_teacher_pick(builder):
    problems = d1v.validate_record(builder(teacher_label="B"))
    assert any("teacher_label's bound payload" in p for p in problems)


@pytest.mark.parametrize("builder", [_turn_record, _reaction_record])
def test_null_executed_label_is_not_a_trainable_record(builder):
    assert any("label must name" in p for p in d1v.validate_record(builder(label=None)))


@pytest.mark.parametrize("hint", ["built_in_pick: B", "teacher_label=A", "BUILT_IN_PICK: A"])
def test_explicit_teacher_hints_in_option_text_are_rejected(hint):
    assert any("hint" in p for p in d1v.validate_record(_turn_record(options={"A": hint, "B": "End"})))
