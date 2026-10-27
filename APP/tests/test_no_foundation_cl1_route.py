"""NOFOUNDCL1: the Foundation select route refuses a Foundation below the acquisition CL.

These are the public-CI tests for the rule behind ``NonSphereAuthorityService.select_foundation``
and ``set_target_cl``: they exercise the shared gate in ``app.foundation_cl_gate`` with
synthetic state, so they touch no owner authority data. The service wiring lives in
``test_no_foundation_cl1_integration.py``, whose imports are local-only in the public export.
"""
import pytest

from app.core import FoundryError
from app.foundation_cl_gate import (
    FOUNDATION_CL_TOO_LOW,
    foundation_below_acquisition_cl,
    foundation_cl_too_low_error,
    refuse_foundation_below_acquisition_cl,
)

# The published acquisition CL (non_sphere_authority.foundation_mechanics
# INITIAL_FOUNDATION_MECHANICS_POLICY["acquisition_cl"]); the integration test
# pins the policy to this value.
ACQUISITION_CL = 5
FOUNDATION = "FOUNDATION_TEST_ONLY"


@pytest.mark.parametrize("target_cl", [1, ACQUISITION_CL - 1])
def test_select_foundation_refused_below_acquisition_cl(target_cl):
    assert foundation_below_acquisition_cl(
        target_cl=target_cl, acquisition_cl=ACQUISITION_CL, foundation_ids=[FOUNDATION],
    )
    with pytest.raises(FoundryError) as exc:
        refuse_foundation_below_acquisition_cl(
            target_cl=target_cl,
            acquisition_cl=ACQUISITION_CL,
            foundation_ids=[FOUNDATION],
            details={"foundation_id": FOUNDATION},
        )
    assert exc.value.code == "CHARACTER_FOUNDATION_CL_TOO_LOW"
    assert exc.value.code == FOUNDATION_CL_TOO_LOW
    assert "Foundations open at level %d" % ACQUISITION_CL in str(exc.value)
    assert exc.value.details["target_cl"] == target_cl
    assert exc.value.details["foundation_id"] == FOUNDATION


def test_select_foundation_allowed_at_acquisition_cl():
    assert not foundation_below_acquisition_cl(
        target_cl=ACQUISITION_CL, acquisition_cl=ACQUISITION_CL, foundation_ids=[FOUNDATION],
    )
    assert refuse_foundation_below_acquisition_cl(
        target_cl=ACQUISITION_CL, acquisition_cl=ACQUISITION_CL, foundation_ids=[FOUNDATION],
    ) is None


@pytest.mark.parametrize("target_cl", [None, "1", 1.5])
def test_missing_or_malformed_target_level_is_left_to_the_normal_validation(target_cl):
    # The gate only says "below" for a real integer level; bad input is not a CL refusal.
    assert not foundation_below_acquisition_cl(
        target_cl=target_cl, acquisition_cl=ACQUISITION_CL, foundation_ids=[FOUNDATION],
    )


def test_clearing_foundation_is_allowed_below_acquisition_cl():
    assert refuse_foundation_below_acquisition_cl(
        target_cl=1, acquisition_cl=ACQUISITION_CL, foundation_ids=[], details={"foundation_id": None},
    ) is None
    assert refuse_foundation_below_acquisition_cl(
        target_cl=1, acquisition_cl=ACQUISITION_CL, foundation_ids=None,
    ) is None


def test_set_target_cl_refused_below_acquisition_cl_with_foundation():
    """Lowering the target CL while a Foundation is held would leave the Foundation below its acquisition CL."""
    with pytest.raises(FoundryError) as exc:
        refuse_foundation_below_acquisition_cl(
            target_cl=1,
            acquisition_cl=ACQUISITION_CL,
            foundation_ids=[FOUNDATION],
            keeps_foundation=True,
            details={"foundation_id": FOUNDATION},
        )
    assert exc.value.code == FOUNDATION_CL_TOO_LOW
    assert "Foundations open at level %d" % ACQUISITION_CL in str(exc.value)
    assert "clear the Foundation first" in str(exc.value)


def test_set_target_cl_allowed_at_acquisition_cl_with_foundation():
    assert refuse_foundation_below_acquisition_cl(
        target_cl=ACQUISITION_CL,
        acquisition_cl=ACQUISITION_CL,
        foundation_ids=[FOUNDATION],
        keeps_foundation=True,
        details={"foundation_id": FOUNDATION},
    ) is None


def test_set_target_cl_below_acquisition_cl_without_foundation_is_allowed():
    # Inert for characters without a Foundation: the CL gate must not fire.
    assert refuse_foundation_below_acquisition_cl(
        target_cl=1, acquisition_cl=ACQUISITION_CL, foundation_ids=[], keeps_foundation=True,
    ) is None
    assert not foundation_below_acquisition_cl(
        target_cl=1, acquisition_cl=ACQUISITION_CL, foundation_ids=None,
    )


def test_player_text_names_the_level_the_action_and_the_cost_of_keeping_the_foundation():
    select_error = foundation_cl_too_low_error(target_cl=1, acquisition_cl=ACQUISITION_CL)
    assert str(select_error) == (
        "Foundations open at level 5. Raise the intended level to 5 or higher, or leave the Foundation unset."
    )
    keep_error = foundation_cl_too_low_error(target_cl=1, acquisition_cl=ACQUISITION_CL, keeps_foundation=True)
    assert str(keep_error) == (
        "Foundations open at level 5. This character keeps a Foundation, so the target level cannot go below 5. "
        "Raise the target level to 5 or higher, or clear the Foundation first."
    )
