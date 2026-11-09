"""The accepted plan's Foundation reaches the builder state like the Method does."""
from __future__ import annotations

import pytest

from app.core import FoundryError
from character_creation.service import CharacterCreationExecutionService


class _Authority:
    def __init__(self, foundation_id=None, *, accept=True):
        self.state = {"foundation_id": foundation_id}
        self.accept = accept
        self.calls = []

    def get_state(self, project_id):
        return dict(self.state)

    def select_foundation(self, project_id, foundation_id):
        self.calls.append((project_id, foundation_id))
        if self.accept:
            self.state["foundation_id"] = foundation_id
        return dict(self.state)


RUN = {"project_id": "project.test", "run_id": "run.test"}
PLAN = {"resolution": {"method_id": "METHOD-082", "foundation_id": "FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR"}}


def test_accepted_foundation_id_reads_resolution_then_selection_intent():
    read = CharacterCreationExecutionService._accepted_foundation_id
    assert read(PLAN) == "FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR"
    assert read({"canonical_selection_intent": {"selected_by_slot": {"foundation_choice": ["FOUNDATION_01"]}}}) == "FOUNDATION_01"
    assert read({"resolution": {"method_id": "METHOD-082"}}) is None
    assert read(None) is None


def test_sync_selects_the_foundation_once_and_is_idempotent():
    service = CharacterCreationExecutionService.__new__(CharacterCreationExecutionService)
    authority = _Authority()
    assert service._sync_accepted_foundation(RUN, authority, PLAN) == "FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR"
    assert authority.calls == [("project.test", "FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR")]
    assert service._sync_accepted_foundation(RUN, authority, PLAN) == "FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR"
    assert len(authority.calls) == 1
    assert service._sync_accepted_foundation(RUN, _Authority(), {"resolution": {}}) is None


def test_sync_fails_closed_when_the_builder_state_does_not_take_the_foundation():
    service = CharacterCreationExecutionService.__new__(CharacterCreationExecutionService)
    with pytest.raises(FoundryError) as err:
        service._sync_accepted_foundation(RUN, _Authority(accept=False), PLAN)
    assert err.value.code == "CG1_FOUNDATION_COMMIT_FAILED"
