from __future__ import annotations

from character_creation.creative_controller.linear_menus import MAX_WALK_STEPS
from character_creation.creative_controller.linear_prompt import walk_steps_estimate


def _request(target_cl):
    return {"delegated_choice_envelope": {"binding": {"target_cl": target_cl}}}


def test_walk_steps_estimate_scales_with_the_frozen_target_level() -> None:
    # A finished CL 20 walk publishes 144-150 menus (five owner-facing trials).
    assert walk_steps_estimate(_request(20)) == 150
    assert walk_steps_estimate(_request(1)) == 36
    assert walk_steps_estimate(_request(5)) == 60
    assert walk_steps_estimate(_request(99)) == MAX_WALK_STEPS


def test_walk_steps_estimate_falls_back_without_a_target_level() -> None:
    assert walk_steps_estimate(None) == 22
    assert walk_steps_estimate({}) == 22
    assert walk_steps_estimate(_request("20")) == 22
    assert walk_steps_estimate(_request(0)) == 22
