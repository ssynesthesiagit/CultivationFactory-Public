"""NOFOUNDCL1 service-level regressions: creation, lock freeze and the Foundation route.

These tests drive the real services, whose imports reach the owner authority data
the public export withholds, so this file is local-only in the public export and
is documented under "Stays private" in the lane report. The shared rule itself
is covered on the public CI by test_no_foundation_cl1_lock.py and
test_no_foundation_cl1_route.py, which pin the same CL5.

Run with the creation fixtures (see the other service-level tests in APP/tests).
"""
import pytest

from app.core import FoundryError
from character_builder import CharacterBuilderService
from non_sphere_authority.foundation_mechanics import INITIAL_FOUNDATION_MECHANICS_POLICY
from non_sphere_authority.service import NonSphereAuthorityService
from project_store.service import ProjectStore

ACQUISITION_CL = INITIAL_FOUNDATION_MECHANICS_POLICY["acquisition_cl"]
FOUNDATION = "FOUNDATION_TEST_ONLY"


def test_published_acquisition_cl_matches_the_public_gate_tests():
    # The public-CI gate tests cannot import owner authority data; they pin CL5.
    # If the published rule changes, this fails so both places move together.
    assert ACQUISITION_CL == 5


def _foundation_id(db):
    options = CharacterBuilderService(db).options()
    category = next(row for row in options["categories"] if row["slot_id"] == "foundation_choice")
    assert category["choices"], "catalog must offer at least one Foundation"
    return category["choices"][0]["choice_id"]


def _project_at(db, target_cl):
    return CharacterBuilderService(db).create_project(
        working_name=f"NOFOUNDCL1 CL{target_cl}", concept="A quiet test guardian", target_cl=target_cl,
        power_band="standard", source_reference=None, creation_mode="detailed",
        ability_scores={}, selections={}, autogen_seed=f"NOFOUNDCL1-{target_cl}",
    )["project_id"]


def _foundation_lock(foundation_id):
    return [{"field": "character_sheet.locked_choices", "value": {"foundation_choice": [foundation_id]}}]


def _service(target_cl, foundation_id=None):
    """The real select_foundation/set_target_cl with the state and persistence stubbed out (no catalog needed)."""
    service = NonSphereAuthorityService.__new__(NonSphereAuthorityService)
    service.foundations = {FOUNDATION: {}}
    service.theoretical_foundations = []
    state = {
        "target_cl": target_cl, "foundation_id": foundation_id,
        "paths": [{"path_id": "PATH_TEST_ONLY", "attainment": 1}],
    }
    service.get_state = lambda project_id, **kwargs: dict(state)
    saved = []

    def save_state(project_id, new_state, *args, **kwargs):
        saved.append(new_state)
        return new_state

    service.save_state = save_state
    service.saved = saved
    return service


def test_foundation_lock_is_refused_at_cl1_before_freezing(catalog_environment):
    db = catalog_environment["db"]
    foundation_id = _foundation_id(db)
    pid = _project_at(db, 1)
    store = ProjectStore(db)
    before = store.get_project(pid)
    try:
        store.append_user_locks(pid, _foundation_lock(foundation_id))
    except FoundryError as exc:
        assert exc.code == "CHARACTER_FOUNDATION_CL_TOO_LOW"
        assert str(ACQUISITION_CL) in str(exc)
        assert "Foundations open at level" in str(exc)
    else:
        raise AssertionError("CL1 Foundation lock must be refused")
    after = store.get_project(pid)
    assert after["project"]["revision"] == before["project"]["revision"]
    # create_project always writes character_sheet.locked_choices (immutable); the refused lock must not be in it.
    locks = {lock["field"]: lock["value"] for lock in after["project"].get("user_locks", [])}
    assert not (locks.get("character_sheet.locked_choices") or {}).get("foundation_choice")


def test_foundation_lock_passes_the_cl_gate_at_acquisition_cl(catalog_environment):
    # The gate itself must let a CL5 Foundation lock through: the direct check does not raise.
    locks = _foundation_lock("FOUNDATION_X")
    locks.append({"field": "target_cl", "value": ACQUISITION_CL})
    assert ProjectStore._refuse_early_foundation_locks(old_locks=[], new_locks=locks) is None
    # Creation always freezes character_sheet.locked_choices, so the append path is refused as immutable
    # at CL5 too; that refusal is what the append path reports, not the CL gate.
    db = catalog_environment["db"]
    foundation_id = _foundation_id(db)
    pid = _project_at(db, ACQUISITION_CL)
    with pytest.raises(FoundryError) as exc:
        ProjectStore(db).append_user_locks(pid, _foundation_lock(foundation_id))
    # The refusal is the frozen locked_choices immutability, raised after the CL gate passed.
    assert exc.value.code == "USER_LOCK_FIELD_IMMUTABLE"


def test_creation_request_refuses_foundation_below_acquisition_cl(catalog_environment):
    db = catalog_environment["db"]
    foundation_id = _foundation_id(db)
    try:
        CharacterBuilderService(db).create_project(
            working_name="NOFOUNDCL1 creation", concept="A quiet test guardian", target_cl=1,
            power_band="standard", source_reference=None, creation_mode="detailed",
            ability_scores={}, selections={"foundation_choice": [foundation_id]}, autogen_seed="NOFOUNDCL1-create",
        )
    except FoundryError as exc:
        assert exc.code == "CHARACTER_FOUNDATION_CL_TOO_LOW"
    else:
        raise AssertionError("CL1 creation with a Foundation must be refused")


@pytest.mark.parametrize("target_cl", [1, ACQUISITION_CL - 1])
def test_select_foundation_refused_below_acquisition_cl(target_cl):
    service = _service(target_cl)
    with pytest.raises(FoundryError) as exc:
        service.select_foundation("project.cl-low", FOUNDATION)
    assert exc.value.code == "CHARACTER_FOUNDATION_CL_TOO_LOW"
    assert "Foundations open at level %d" % ACQUISITION_CL in str(exc.value)
    assert service.saved == []


def test_select_foundation_allowed_at_acquisition_cl():
    service = _service(ACQUISITION_CL)
    result = service.select_foundation("project.cl-ok", FOUNDATION)
    assert result["foundation_id"] == FOUNDATION


def test_clearing_foundation_is_allowed_below_acquisition_cl():
    service = _service(1)
    result = service.select_foundation("project.cl-clear", None)
    assert result["foundation_id"] is None


def test_set_target_cl_refused_below_acquisition_cl_with_foundation():
    """Lowering the target CL while a Foundation is held would leave the Foundation below its acquisition CL."""
    service = _service(ACQUISITION_CL, foundation_id=FOUNDATION)
    with pytest.raises(FoundryError) as exc:
        service.set_target_cl("project.cl-lower", 1)
    assert exc.value.code == "CHARACTER_FOUNDATION_CL_TOO_LOW"
    assert "Foundations open at level %d" % ACQUISITION_CL in str(exc.value)
    assert service.saved == []


def test_set_target_cl_allowed_at_acquisition_cl_with_foundation():
    service = _service(ACQUISITION_CL + 1, foundation_id=FOUNDATION)
    result = service.set_target_cl("project.cl-lower-ok", ACQUISITION_CL)
    assert result["target_cl"] == ACQUISITION_CL


def test_set_target_cl_below_acquisition_cl_without_foundation_is_allowed():
    # Inert for characters without a Foundation: the CL gate must not fire.
    service = _service(ACQUISITION_CL)
    result = service.set_target_cl("project.cl-lower-nofoundation", 1)
    assert result["target_cl"] == 1
