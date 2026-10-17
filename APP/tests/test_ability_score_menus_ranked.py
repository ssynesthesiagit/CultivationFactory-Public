"""Ability-score menus rank by Path priority and show the scores (smoke test 2026-09-23)."""

from __future__ import annotations

from character_creation.creative_controller.linear_menus import CommittedState, _assignment_candidates


def test_body_refining_assignment_puts_the_top_score_in_con_and_labels_scores() -> None:
    preset = {"abilities": ["STR", "DEX", "CON", "INT", "WIS", "CHA"], "scores": [15, 15, 15, 8, 8, 8]}
    state = CommittedState(by_slot={"path_choice": ["tianxia.path.body_refining"]})
    first = _assignment_candidates(preset, state)[0]
    scores = {token.split(":")[1]: int(token.split(":")[2]) for token in first.choice_ids}
    assert scores["CON"] == 15 and scores["STR"] == 15 and scores["DEX"] == 15
    assert first.cue.startswith("CON 15, STR 15, DEX 15")


def test_qi_cultivation_prefers_int() -> None:
    preset = {"abilities": ["STR", "DEX", "CON", "INT", "WIS", "CHA"], "scores": [15, 14, 13, 12, 10, 8]}
    state = CommittedState(by_slot={"path_choice": ["tianxia.path.qi_cultivation"]})
    first = _assignment_candidates(preset, state)[0]
    scores = {token.split(":")[1]: int(token.split(":")[2]) for token in first.choice_ids}
    assert scores["INT"] == 15 and scores["CON"] == 14
