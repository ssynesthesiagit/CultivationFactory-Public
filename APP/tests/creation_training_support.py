"""Synthetic creation-training builders shared by focused tests."""

from __future__ import annotations

from creation_training_authority import (
    CREATION_TRAINING_CONTRACT_SCHEMA,
    CREATION_TRAINING_MAX_PER_CL,
    CREATION_TRAINING_SPHERE_KIND,
    CREATION_TRAINING_TALENT_KIND,
)


def _route(
    record_id: str,
    *,
    content_type: str,
    choice_type: str,
    owning_sphere_id: str | None = None,
    minimum_cl: int = 1,
    prerequisites: list[dict] | None = None,
    bonus_talent_eligible: bool = True,
) -> dict:
    return {
        "record_id": record_id,
        "content_type": content_type,
        "choice_type": choice_type,
        "source_route": "published_legal_teaching_route" if content_type == "sphere" else "recorded_self_training",
        "source_record_id": owning_sphere_id or record_id,
        "source_provenance": {
            "record_id": record_id,
            "source_id": f"source.{record_id}",
            "source_hash": "a" * 64,
            "source_anchor": f"rules:{record_id}",
            "source_path": "synthetic_rules.md",
        },
        "owning_sphere_id": owning_sphere_id,
        "bonus_talent_eligible": bonus_talent_eligible,
        "minimum_cl": minimum_cl,
        "realm_rules": {},
        "prerequisites": prerequisites or [],
        "incompatibilities": [],
        "access_category": "Open",
    }


def _contract(*, target_cl: int = 3, required: int | None = None, routes: dict | None = None) -> dict:
    return {
        "schema": CREATION_TRAINING_CONTRACT_SCHEMA,
        "version": 1,
        "target_cl": target_cl,
        "power_band": "rival/boss" if required == 3 else "standard",
        "max_choices_per_cl": CREATION_TRAINING_MAX_PER_CL,
        "required_choices_per_cl": required,
        "bonus_rule": "new_sphere_one_same_sphere_talent_without_slot_cost",
        "construction_mode": "published_route_success_without_rolls",
        "records": routes or {},
        "rule_ids": ["Q06", "RAW-079", "RAW-081"],
    }


def _menu_fixture(*, target_cl: int = 3, required: int | None = None) -> tuple[dict, dict, dict]:
    routes = {
        "sphere.a": _route("sphere.a", content_type="sphere", choice_type="new_sphere"),
        "sphere.z": _route("sphere.z", content_type="sphere", choice_type="new_sphere"),
        "sphere.future": _route("sphere.future", content_type="sphere", choice_type="new_sphere", minimum_cl=5),
        "talent.a": _route("talent.a", content_type="talent", choice_type="known_sphere_talent", owning_sphere_id="sphere.a"),
        "talent.zbonus": _route("talent.zbonus", content_type="talent", choice_type="known_sphere_talent", owning_sphere_id="sphere.z"),
        "talent.chain": _route(
            "talent.chain",
            content_type="talent",
            choice_type="known_sphere_talent",
            owning_sphere_id="sphere.z",
            prerequisites=[{"operator": "requires", "target_id": "talent.zbonus"}],
        ),
        "talent.future": _route("talent.future", content_type="talent", choice_type="known_sphere_talent", owning_sphere_id="sphere.z", minimum_cl=5),
    }
    rows = {
        record_id: {"choice_id": record_id, "name": record_id}
        for record_id in routes
    }
    typed_authority = {
        "sphere_priorities": {
            "stage2_authority_by_choice": {
                record_id: {
                    "authority_complete": True,
                    "allowed_kinds": [CREATION_TRAINING_SPHERE_KIND],
                    "allowed_channels": ["creation-training-published-sphere"],
                }
                for record_id in routes
                if record_id.startswith("sphere.")
            }
        },
        "advancement_skeleton": {
            "stage2_authority_by_choice": {
                record_id: {
                    "authority_complete": True,
                    "allowed_kinds": [
                        CREATION_TRAINING_TALENT_KIND,
                        *(["new_sphere_bonus_talent_acquisition"] if record_id in {"talent.a", "talent.zbonus"} else []),
                    ],
                    "allowed_channels": [
                        "creation-training-known-sphere-talent",
                        *(["new-sphere-bonus"] if record_id in {"talent.a", "talent.zbonus"} else []),
                    ],
                }
                for record_id in routes
                if record_id.startswith("talent.")
            }
        },
    }
    envelope = {
        "creation_training_contract": _contract(target_cl=target_cl, required=required, routes=routes),
        "choices_by_slot": {
            "sphere_priorities": {key: rows[key] for key in routes if key.startswith("sphere.")},
            "advancement_skeleton": {key: rows[key] for key in routes if key.startswith("talent.")},
        },
        "allowed_choices_by_slot": {
            "sphere_priorities": [key for key in routes if key.startswith("sphere.")],
            "advancement_skeleton": [key for key in routes if key.startswith("talent.")],
        },
        "typed_choice_authority_by_slot": typed_authority,
    }
    request = {
        "request_sha256": "b" * 64,
        "owner_planning_preferences": {
            "sphere_priority_ids": ["sphere.z"],
            "talent_priority_ids": ["talent.chain"],
        },
    }
    return request, envelope, routes


