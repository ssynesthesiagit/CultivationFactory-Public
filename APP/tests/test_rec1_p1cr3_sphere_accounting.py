from __future__ import annotations

import copy

import pytest

from app.core import FoundryError
from tests.rec1_p1cr3_real_acceptance import (
    BACKGROUND_CANONICAL_SPHERE_ID,
    BACKGROUND_SPHERE_ID,
    _sphere_acquisition_evidence,
)


def _fixture(*, semantic_count: int = 11) -> tuple[list[dict], list[dict], list[str], list[str], list[str], list[str]]:
    semantic = [f"tianxia.sphere.semantic_{index:02d}" for index in range(semantic_count)]
    free = [f"TAL_SEMANTIC_{index:02d}" for index in range(semantic_count)]
    ordinary = [f"TAL_ORDINARY_{index:02d}" for index in range(20)]
    choices = [
        {"kind": "background_sphere_acquisition", "record_id": BACKGROUND_SPHERE_ID},
        *[
            {"kind": "ai_bootstrap_sphere_acquisition", "record_id": sphere_id}
            for sphere_id in semantic
        ],
        *[
            {"kind": "ai_bootstrap_talent_acquisition", "record_id": talent_id}
            for talent_id in free
        ],
        *[
            {"kind": "level_talent_acquisition", "record_id": talent_id, "effective_cl": index + 1}
            for index, talent_id in enumerate(ordinary)
        ],
    ]
    pairs = [
        {"sphere_id": sphere_id, "talent_id": talent_id}
        for sphere_id, talent_id in zip(semantic, free)
    ]
    priorities = [*semantic, "tianxia.sphere.planning_12", "tianxia.sphere.planning_13", "tianxia.sphere.planning_14", "tianxia.sphere.planning_15"]
    return choices, pairs, semantic, free, ordinary, priorities


def test_rec1_p1cr3_sphere_accounting_counts_background_and_semantic_layers() -> None:
    choices, pairs, semantic, free, ordinary, priorities = _fixture()
    evidence = _sphere_acquisition_evidence(
        choices=choices,
        response_pairs=pairs,
        accepted_spheres=semantic,
        accepted_free=free,
        accepted_ordinary=ordinary,
        accepted_background_spheres=[BACKGROUND_SPHERE_ID],
        planning_priorities=priorities,
    )

    assert evidence["valid"] is True
    assert evidence["sphere_acquisition_event_count"] == 12
    assert evidence["background_sphere_acquisition_event_count"] == 1
    assert evidence["semantic_sphere_acquisition_event_count"] == 11
    assert evidence["semantic_free_talent_pair_count"] == 11
    assert evidence["ordinary_talent_acquisition_event_count"] == 20
    assert evidence["known_sphere_ids"] == [BACKGROUND_CANONICAL_SPHERE_ID, *semantic]


def test_rec1_p1cr3_twelfth_semantic_sphere_cannot_hide_background_event() -> None:
    choices, pairs, semantic, free, ordinary, priorities = _fixture()
    mutated_choices, mutated_pairs = copy.deepcopy(choices), copy.deepcopy(pairs)
    twelfth = "tianxia.sphere.semantic_12"
    twelfth_talent = "TAL_SEMANTIC_12"
    mutated_choices.insert(2, {"kind": "ai_bootstrap_sphere_acquisition", "record_id": twelfth})
    mutated_choices.insert(14, {"kind": "ai_bootstrap_talent_acquisition", "record_id": twelfth_talent})
    mutated_pairs.append({"sphere_id": twelfth, "talent_id": twelfth_talent})

    with pytest.raises(FoundryError) as exc:
        _sphere_acquisition_evidence(
            choices=mutated_choices,
            response_pairs=mutated_pairs,
            accepted_spheres=[*semantic, twelfth],
            accepted_free=[*free, twelfth_talent],
            accepted_ordinary=ordinary,
            accepted_background_spheres=[BACKGROUND_SPHERE_ID],
            planning_priorities=[*priorities, twelfth],
        )

    assert exc.value.code == "REC1_P1CR3_ACCEPTANCE_SPHERE_ACCOUNTING_INVALID"
    assert exc.value.details["background_sphere_acquisition_event_count"] == 1
    assert exc.value.details["semantic_sphere_acquisition_event_count"] == 12
    assert exc.value.details["sphere_acquisition_event_count"] == 13
