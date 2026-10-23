"""Public synthetic regressions for the stock AI-versus-rules distinction."""
from copy import deepcopy

import pytest

from tests.ai_stock_audit import compare_capture, journal_decisions

SEEDS = ("LOCK5-A", "LOCK5-B", "LOCK5-C", "GATE4-TEST", "GATE4-AN-1", "GATE4-LEE")


def fixture(*, lazy=False):
    destination = {"x": 6, "y": 4, "z": 0}
    intent = {"intent_id": "intent:root" if lazy else "intent:cell", "decision_id": "decision:1",
              "candidate_id": "candidate:root" if lazy else "candidate:cell", "state_version": 0,
              "actor_id": "actor:a", "target_ids": [], "option_ids": [], "reaction_decisions": [],
              "destination": None if lazy else destination}
    if lazy:
        intent["placement_destination"] = destination
    binding = {"kind": "ACTION", "source_definition_id": "test:area"}
    mechanical = [
        {"record_type": "PREPARE", "transaction_id": "tx:1", "intent": intent, "candidate_binding": binding},
        {"record_type": "COMMIT", "transaction_id": "tx:1"}]
    controller = [{"record_type": "CONTROLLER_COMMIT", "transaction_id": "tx:1", "reaction_decision_records": []}]
    accepted = {"sequence": 1, "state_version": 1, "event_type": "INTENT_ACCEPTED",
        "actor_id": "actor:a", "source_definition_id": "test:area", "target_ids": [],
        "payload": {"candidate_id": intent["candidate_id"], "kind": "ACTION", "option_ids": []}}
    damage = {**accepted, "sequence": 2, "event_type": "DAMAGE_COMMITTED", "target_ids": ["actor:b"],
              "payload": {"hp_damage": 6, "remaining_hp": 14}}
    capture = {"steps": 1, "events": [[accepted, damage]], "rolls": [[{"total": 6, "dice": [6]}]],
        "choices": [[[intent["candidate_id"], "Example area"]]], "zones": 0, "summons": 0,
        "state": {"terminal_result": {"kind": "DURATION_LIMIT"}}}
    return capture, mechanical, controller


def compare(seed, left, right):
    return compare_capture(seed, left[0], right[0],
                           journal_decisions(*left[1:]), journal_decisions(*right[1:]))


@pytest.mark.parametrize("seed", SEEDS)
def test_receipt_only_change_never_excuses_a_rules_difference(seed):
    before, after = fixture(), fixture(lazy=True)
    report = compare(seed, before, after)
    assert report["first_choice_step"] is None  # same chosen square, despite different receipt IDs
    assert report["first_menu_step"] == 1
    assert report["first_outcome_step"] is None
    assert report["rules_equal_before_choice"]
    # The old inspector called the receipt a changed decision and allowed this
    # same-step damage defect in every one of the six reported stock controls.
    after[0]["events"][0][1]["payload"]["hp_damage"] = 7
    report = compare(seed, before, after)
    assert report["first_choice_step"] is None
    assert report["first_outcome_step"] == 1
    assert not report["rules_equal_before_choice"]


@pytest.mark.parametrize("change", ("destination", "movement_path", "movement_mode", "option_ids", "target_ids"))
def test_actual_intent_changes_are_not_normalized_away(change):
    before = fixture()
    after = deepcopy(before)
    after[1][0]["intent"][change] = {
        "destination": {"x": 7, "y": 4, "z": 0},
        "movement_path": [{"x": 5, "y": 4, "z": 0}, {"x": 6, "y": 4, "z": 0}],
        "movement_mode": "FLY", "option_ids": ["test:augment"], "target_ids": ["actor:c"],
    }[change]
    assert compare("synthetic", before, after)["first_choice_step"] == 1


def test_reaction_selections_not_explanation_text_are_compared():
    before = fixture()
    reaction = {"selected_reaction": {"checkpoint": "DAMAGE_APPLICATION", "reactor_id": "actor:b",
        "reaction_source_id": "test:guard", "selection": "USE", "spend": 1, "option_ids": []},
        "selected_option_ids": [], "explanation": "Old explanation"}
    before[2][0]["reaction_decision_records"] = [reaction]
    after = deepcopy(before)
    after[2][0]["reaction_decision_records"][0]["explanation"] = "New plain explanation"
    assert compare("synthetic", before, after)["first_choice_step"] is None
    after[2][0]["reaction_decision_records"][0]["selected_reaction"]["selection"] = "DECLINE"
    assert compare("synthetic", before, after)["first_choice_step"] == 1


@pytest.mark.parametrize("change", ("roll", "new_event_kind"))
def test_all_rule_events_and_rolls_remain_checked(change):
    before = fixture()
    after = deepcopy(before)
    if change == "roll":
        after[0]["rolls"][0][0]["total"] += 1
    else:
        # The old whitelist ignored e.g. removal/expiry and new effect events.
        after[0]["events"][0].append({**after[0]["events"][0][1], "sequence": 3,
                                     "event_type": "CONDITION_REMOVED", "payload": {"condition_id": "test:guard"}})
    report = compare("synthetic", before, after)
    assert report["first_choice_step"] is None
    assert report["first_outcome_step"] == 1
    assert not report["rules_equal_before_choice"]


def test_a_later_choice_does_not_excuse_an_earlier_rules_change():
    before = fixture()
    after = deepcopy(before)
    for capture, mechanical, controller in (before, after):
        capture["steps"] = 2
        for key in ("events", "rolls", "choices"):
            capture[key].append(deepcopy(capture[key][0]))
        mechanical.extend([{**deepcopy(r), "transaction_id": "tx:2"} for r in mechanical[:2]])
        controller.append({**deepcopy(controller[0]), "transaction_id": "tx:2"})
    after[0]["events"][0][1]["payload"]["remaining_hp"] -= 1
    after[1][2]["intent"]["destination"]["x"] += 1
    report = compare("synthetic", before, after)
    assert report["first_choice_step"] == 2
    assert report["first_outcome_step"] == 1
    assert not report["rules_equal_before_choice"]


def test_unmatched_trailing_transactions_are_not_lost_to_zip():
    before = fixture()
    after = deepcopy(before)
    after[0]["steps"] = 0
    for key in ("events", "rolls", "choices"):
        after[0][key].clear()
    after[1].clear()
    after[2].clear()
    report = compare("synthetic", before, after)
    assert report["first_choice_step"] == report["first_outcome_step"] == 1
    assert report["head_choice"] is None


def test_incomplete_journal_evidence_fails_closed():
    capture, mechanical, controller = fixture()
    with pytest.raises(KeyError):
        journal_decisions(mechanical, [])  # no durable reaction-decision evidence
    with pytest.raises(AssertionError):
        compare_capture("synthetic", capture, capture, [], [])
