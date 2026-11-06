"""Save-scope comparison in the single-resolution forging policy.

A save that names no ``applies_to`` is rolled against the creature it was
delivered to, exactly like an explicit ``"target"``. Validation must compare
those two the way the engine reads them, so a printed single roll whose nested
rider simply spells out ``"target"`` under a parent that omits the field is not
reported as a second gate. A nested save that names a *different* recipient
(a different scope, a different DC, a success branch, or a source-specific
predicate) is still a separate roll and must stay one.

Public CI: synthetic fixtures only; no private data or history reads.
"""
import pytest

from character_creation.constructed_arts.forge_design import (
    DEFAULT_SAVE_SCOPE, collapse_repeated_saves, design_issues, restructure)


def _save(rows, ability="dex", scope="__omitted__", dc="technique_save_dc", **extra):
    row = {"type": "save", "ability": ability, "dc": dc, "on_fail": rows, "on_success": []}
    if scope != "__omitted__":
        row["applies_to"] = scope
    row.update(extra)
    return row


DAMAGE = {"type": "damage", "applies_to": "target", "dice": {"count": 3, "sides": 8}}
SLOW = {"type": "condition", "condition": "slowed", "applies_to": "target",
        "duration": "until_start_of_next_turn"}
HALF = [{"type": "half_damage", "applies_to": "target"}]


def _wrap(enclosing, rider):
    """A hostile delivery save whose failure branch holds one nested save."""
    return {"effects": [{**enclosing, "on_fail": [DAMAGE, rider], "on_success": list(HALF)}],
            "cost": [[{"amount": 2}]]}


def test_default_save_scope_is_the_target():
    assert DEFAULT_SAVE_SCOPE == "target"


@pytest.mark.parametrize("parent_scope,rider_scope", [
    ("__omitted__", "target"),   # the reviewed case: parent omits, rider spells the default out
    ("target", "target"),        # both spell it out
    ("__omitted__", "__omitted__"),  # neither spells it out
    ("__omitted__", None),       # rider carries an explicit null scope
])
def test_one_printed_roll_is_not_reported_as_a_second_gate(parent_scope, rider_scope):
    parent = _save([SLOW], scope=parent_scope)
    rider = _save([SLOW], scope=rider_scope)
    mechanic = _wrap(parent, rider)
    # Without the fix the parent scope stayed None, so "target" != None and
    # design_issues reported stacked_gates for a single printed roll.
    assert design_issues(mechanic) == []
    after = restructure(mechanic)
    assert [row["type"] for row in after["effects"]] == ["save"]
    assert [row["type"] for row in after["effects"][0]["on_fail"]] == ["damage", "condition"]
    assert collapse_repeated_saves([{**parent, "on_fail": [DAMAGE, rider]}])[0]["on_fail"] == [DAMAGE, SLOW]


@pytest.mark.parametrize("rider", [
    _save([{"type": "healing", "flat": 5, "applies_to": "ally"}], scope="ally"),
    _save([DAMAGE], scope="enemies_in_area"),
    _save([DAMAGE], dc=15),
    _save([DAMAGE], scope="target", requires_mark=True),
    {"type": "save", "ability": "con", "dc": "technique_save_dc", "applies_to": "target",
     "on_fail": [DAMAGE], "on_success": []},
], ids=["ally_scope", "area_scope", "different_dc", "source_predicate", "different_ability"])
def test_a_genuinely_second_roll_stays_a_second_gate(rider):
    """Only an ordinary same-ability/same-DC rider of the same recipient folds.

    A rider that changes the recipient, the difficulty, the ability, or carries a
    source-specific predicate is a genuinely second roll: validation reports the
    stacked gate, and the fold never swallows it (which would drop its contract
    and make its failure effects unconditional).
    """
    mechanic = _wrap(_save([SLOW]), rider)
    assert "stacked_gates" in design_issues(mechanic)
    folded = collapse_repeated_saves([{**_save([SLOW]), "on_fail": [DAMAGE, rider]}])
    assert folded[0]["on_fail"] == [DAMAGE, rider]


def test_a_rider_with_a_success_branch_stays_a_second_gate():
    success_rider = {"type": "save", "ability": "dex", "dc": "technique_save_dc", "applies_to": "target",
                     "on_fail": [SLOW], "on_success": [DAMAGE]}
    mechanic = _wrap(_save([SLOW]), success_rider)
    assert "stacked_gates" in design_issues(mechanic)


def test_default_scope_normalization_does_not_reach_outside_a_save():
    """The default applies to a save's own scope only: the ordinary rows in the
    failure branch keep their own recipients untouched."""
    mechanic = _wrap(_save([SLOW]), _save([SLOW], scope="target"))
    [save] = collapse_repeated_saves(mechanic["effects"])
    assert save["on_fail"] == [DAMAGE, SLOW]
    assert save["on_success"] == HALF
    assert restructure(mechanic)["effects"][0]["on_fail"] == [DAMAGE, SLOW]
    assert design_issues(restructure(mechanic)) == []
