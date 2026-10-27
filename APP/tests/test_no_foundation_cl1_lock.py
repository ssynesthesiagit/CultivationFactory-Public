"""NOFOUNDCL1: a Foundation lock below the published acquisition CL is refused before any freeze.

These are the public-CI tests for the lock rule: they exercise the shared gate in
``app.foundation_cl_gate`` with synthetic lock dictionaries, so they touch no
owner authority data. The service-level wiring (ProjectStore writes nothing on
refusal) lives in ``test_no_foundation_cl1_integration.py``, whose imports are
local-only in the public export.
"""
import pytest

from app.core import FoundryError
from app.foundation_cl_gate import (
    FOUNDATION_CL_TOO_LOW,
    refuse_early_foundation_locks,
)

# The published acquisition CL (non_sphere_authority.foundation_mechanics
# INITIAL_FOUNDATION_MECHANICS_POLICY["acquisition_cl"]); the integration test
# pins the policy to this value.
ACQUISITION_CL = 5


def _foundation_lock(foundation_id):
    return [{"field": "character_sheet.locked_choices", "value": {"foundation_choice": [foundation_id]}}]


def _target(target_cl):
    return [{"field": "target_cl", "value": target_cl}]


def test_foundation_lock_is_refused_at_cl1_before_freezing():
    # The project already stores target CL1; the new call adds the Foundation lock.
    with pytest.raises(FoundryError) as exc:
        refuse_early_foundation_locks(
            old_locks=_target(1),
            new_locks=_foundation_lock("FOUNDATION_TEST_ONLY"),
            acquisition_cl=ACQUISITION_CL,
        )
    assert exc.value.code == "CHARACTER_FOUNDATION_CL_TOO_LOW"
    assert exc.value.code == FOUNDATION_CL_TOO_LOW
    assert str(ACQUISITION_CL) in str(exc.value)
    assert "Foundations open at level" in str(exc.value)
    assert exc.value.details["target_cl"] == 1
    assert exc.value.details["acquisition_cl"] == ACQUISITION_CL


def test_foundation_lock_is_refused_when_the_target_is_written_first():
    # append_user_locks stores target_cl and the Foundation choice in one call.
    locks = _target(1) + _foundation_lock("FOUNDATION_TEST_ONLY")
    with pytest.raises(FoundryError) as exc:
        refuse_early_foundation_locks(old_locks=[], new_locks=locks, acquisition_cl=ACQUISITION_CL)
    assert exc.value.code == FOUNDATION_CL_TOO_LOW


def test_foundation_lock_passes_the_cl_gate_at_acquisition_cl():
    locks = _target(ACQUISITION_CL) + _foundation_lock("FOUNDATION_TEST_ONLY")
    assert refuse_early_foundation_locks(old_locks=[], new_locks=locks, acquisition_cl=ACQUISITION_CL) is None


def test_foundation_lock_passes_the_cl_gate_above_acquisition_cl():
    locks = _target(ACQUISITION_CL + 3) + _foundation_lock("FOUNDATION_TEST_ONLY")
    assert refuse_early_foundation_locks(old_locks=[], new_locks=locks, acquisition_cl=ACQUISITION_CL) is None


def test_stored_target_cl_is_used_when_the_new_locks_do_not_repeat_it():
    # A project already at CL1 keeps that level; the new call only adds the Foundation.
    with pytest.raises(FoundryError) as exc:
        refuse_early_foundation_locks(
            old_locks=_target(1),
            new_locks=_foundation_lock("FOUNDATION_TEST_ONLY"),
            acquisition_cl=ACQUISITION_CL,
        )
    assert exc.value.details["target_cl"] == 1
    assert refuse_early_foundation_locks(
        old_locks=_target(ACQUISITION_CL),
        new_locks=_foundation_lock("FOUNDATION_TEST_ONLY"),
        acquisition_cl=ACQUISITION_CL,
    ) is None


def test_new_target_cl_overrides_the_stored_one():
    locks = _target(ACQUISITION_CL) + _foundation_lock("FOUNDATION_TEST_ONLY")
    assert refuse_early_foundation_locks(old_locks=_target(1), new_locks=locks, acquisition_cl=ACQUISITION_CL) is None


def test_lock_without_a_foundation_is_allowed_below_acquisition_cl():
    locks = _target(1) + [{"field": "character_sheet.locked_choices", "value": {"path_choice": ["PATH_TEST_ONLY"]}}]
    assert refuse_early_foundation_locks(old_locks=[], new_locks=locks, acquisition_cl=ACQUISITION_CL) is None


def test_clearing_a_foundation_is_allowed_below_acquisition_cl():
    locks = _target(1) + [{"field": "character_sheet.locked_choices", "value": {"foundation_choice": []}}]
    assert refuse_early_foundation_locks(old_locks=[], new_locks=locks, acquisition_cl=ACQUISITION_CL) is None


@pytest.mark.parametrize("value", [["X"], "X", 7, None, [], {"foundation_choice": 3}])
def test_malformed_locked_choices_value_is_not_a_crash(value):
    # A non-object lock value used to raise AttributeError (HTTP 500) before validation.
    locks = [{"field": "character_sheet.locked_choices", "value": value}]
    assert refuse_early_foundation_locks(old_locks=[], new_locks=locks, acquisition_cl=ACQUISITION_CL) is None


@pytest.mark.parametrize("target", ["1", 1.5, None, [1]])
def test_malformed_target_cl_is_left_to_target_validation(target):
    locks = _target(target) + _foundation_lock("FOUNDATION_TEST_ONLY")
    assert refuse_early_foundation_locks(old_locks=[], new_locks=locks, acquisition_cl=ACQUISITION_CL) is None


def test_malformed_lock_next_to_valid_cl1_foundation_is_still_refused():
    locks = _target(1) + [
        {"field": "character_sheet.locked_choices", "value": ["X"]},
        {"field": "character_sheet.locked_choices", "value": {"foundation_choice": ["FOUNDATION_TEST_ONLY"]}},
    ]
    with pytest.raises(FoundryError) as exc:
        refuse_early_foundation_locks(old_locks=[], new_locks=locks, acquisition_cl=ACQUISITION_CL)
    assert exc.value.code == FOUNDATION_CL_TOO_LOW
