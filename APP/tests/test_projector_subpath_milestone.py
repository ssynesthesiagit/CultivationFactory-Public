from __future__ import annotations

import pytest

from app.core import FoundryError
from projector.service import _paths_subpaths_semantic_node_proven
from projector.v3_bridge import _validated_cl4_selection_authority, _validated_subpath_events


def _event(sequence: int, record_id: str = "tianxia.subpath.qi.stillness") -> dict:
    return {
        "sequence": sequence,
        "subject": {"record_id": record_id},
    }


def test_generic_cl1_projection_accepts_empty_subpath_without_placeholder() -> None:
    assert _validated_subpath_events(
        [],
        generic_project=True,
        milestone_target_cl=1,
    ) == []


def test_generic_projection_requires_subpath_at_milestone() -> None:
    with pytest.raises(FoundryError) as exc:
        _validated_subpath_events(
            [],
            generic_project=True,
            milestone_target_cl=3,
        )
    assert exc.value.code == "PROJECTION_REQUIRED_EVENT_COUNT_INVALID"
    assert exc.value.details == {"kind": "subpath_acquisition", "count": 0, "target_cl": 3}


def test_fixture_projection_keeps_strict_subpath_requirement_before_milestone() -> None:
    with pytest.raises(FoundryError) as exc:
        _validated_subpath_events(
            [],
            generic_project=False,
            milestone_target_cl=1,
        )
    assert exc.value.code == "PROJECTION_REQUIRED_EVENT_COUNT_INVALID"


def test_presented_subpath_events_remain_source_ordered() -> None:
    events = [_event(3, "tianxia.subpath.qi.second"), _event(2)]
    assert _validated_subpath_events(
        events,
        generic_project=True,
        milestone_target_cl=3,
    ) == [_event(2), _event(3, "tianxia.subpath.qi.second")]


def test_generic_cl1_projection_accepts_no_cl4_selection_event() -> None:
    _validated_cl4_selection_authority(
        [],
        [],
        generic_project=True,
        target_cl=1,
    )


def test_generic_cl4_projection_still_requires_selection_authority() -> None:
    with pytest.raises(FoundryError) as exc:
        _validated_cl4_selection_authority(
            [],
            [],
            generic_project=True,
            target_cl=4,
        )
    assert exc.value.code == "PROJECTION_REQUIRED_EVENT_COUNT_INVALID"
    assert exc.value.details == {
        "ability_score_change_count": 0,
        "cultivation_insight_count": 0,
    }


def test_fixture_projection_keeps_cl4_selection_authority_strict() -> None:
    with pytest.raises(FoundryError) as exc:
        _validated_cl4_selection_authority(
            [],
            [],
            generic_project=False,
            target_cl=1,
        )
    assert exc.value.code == "PROJECTION_REQUIRED_EVENT_COUNT_INVALID"


def test_generic_cl1_path_without_subpath_proves_paths_subpaths_node() -> None:
    ledger = {
        "character": {"cl": 1},
        "path_selections": [{"path_id": "tianxia.path.qi_cultivation"}],
        "subpaths": [],
        "subpath_authority": {
            "status": "NOT_YET_DUE",
            "first_selection_cl": 3,
            "selected_path_ids": ["tianxia.path.qi_cultivation"],
        },
    }
    assert _paths_subpaths_semantic_node_proven(ledger) is True


def test_cl3_without_authenticated_subpath_does_not_prove_paths_subpaths_node() -> None:
    ledger = {
        "character": {"cl": 3},
        "path_selections": [{"path_id": "tianxia.path.qi_cultivation"}],
        "subpaths": [],
        "subpath_authority": {
            "status": "NOT_YET_DUE",
            "first_selection_cl": 3,
            "selected_path_ids": ["tianxia.path.qi_cultivation"],
        },
    }
    assert _paths_subpaths_semantic_node_proven(ledger) is False
