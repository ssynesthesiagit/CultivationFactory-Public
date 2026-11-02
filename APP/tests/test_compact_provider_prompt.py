from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

import character_creation.service as creation_service
from ai_provider.service import AIProviderService
from app.core import FoundryError, canonical_json
from character_creation.service import (
    CHARACTER_CREATION_PROVIDER_SYSTEM_MESSAGE,
    CharacterCreationExecutionService,
    PROVIDER_PROMPT_HARD_CAP_BYTES,
    PROVIDER_PROMPT_TARGET_BYTES,
    PROVIDER_REQUEST_HARD_CAP_BYTES,
)
from character_creation.manual_ai_choice import build_compact_choice_model
from character_creation.response_materialization import CanonicalSelectionIntent


def _authority(*, owner: str, minimum_cl: int = 1) -> dict:
    return {
        "authority_complete": True,
        "allowed_kinds": ["level_talent_acquisition"],
        "allowed_channels": ["level-choice"],
        "owning_canonical_sphere_id": owner,
        "minimum_cl": minimum_cl,
    }


def _choice(choice_id: str, *, category: str, owner: str | None = None, minimum_cl: int = 1) -> dict:
    return {
        "choice_id": choice_id,
        "name": f"Display {choice_id}",
        "description": f"A short semantic cue for {choice_id}.",
        "content_type": category,
        "availability": {"minimum_cl": minimum_cl},
        "prerequisites": [],
        "incompatibilities": [],
        **({"owner": owner} if owner else {}),
    }


def _request(*, target_cl: int = 1, with_free_grant: bool = False) -> dict:
    ordinary = {
        f"talent.{sphere}.{index}": _choice(
            f"talent.{sphere}.{index}",
            category="talent",
            owner=f"sphere.{sphere}",
        )
        for sphere in ("fire", "water")
        for index in range(1, 4)
    }
    choices = {
        "path_choice": {"path.qi": _choice("path.qi", category="path")},
        "method_choice": {"method.internal": _choice("method.internal", category="method")},
        "foundation_choice": {"foundation.meridian": _choice("foundation.meridian", category="foundation")},
        "subpath_choice": {"subpath.stillness": _choice("subpath.stillness", category="subpath")},
        "background_choice": {"background.scholar": _choice("background.scholar", category="background")},
        "background_sphere_choice": {"sphere.fire": _choice("sphere.fire", category="sphere", owner="sphere.fire")},
        "background_talent_choice": {"talent.fire.1": _choice("talent.fire.1", category="talent", owner="sphere.fire")},
        "origin_insight_choice": {"insight.origin": _choice("insight.origin", category="insight")},
        "sphere_priorities": {
            "sphere.fire": _choice("sphere.fire", category="sphere", owner="sphere.fire"),
            "sphere.water": _choice("sphere.water", category="sphere", owner="sphere.water"),
        },
        "insight_priorities": {
            "insight.meditation": _choice("insight.meditation", category="insight"),
        },
        "item_priorities": {
            "item.focus": _choice("item.focus", category="item"),
        },
        "advancement_skeleton": ordinary,
    }
    choices["path_choice"]["path.qi"]["prerequisites"] = [{"target_id": "method.internal"}]
    choices["subpath_choice"]["subpath.stillness"]["owning_path_id"] = "path.qi"
    allowed = {slot: sorted(rows) for slot, rows in choices.items()}
    authorities = {
        choice_id: _authority(owner=row.get("owner") or "sphere.fire")
        for choice_id, row in ordinary.items()
    }
    authorities["talent.fire.3"]["minimum_cl"] = 2
    sphere_authorities = {
        sphere_id: {
            "authority_complete": True,
            "allowed_kinds": ["level_sphere_acquisition"],
            "allowed_channels": ["level-choice"],
            "minimum_cl": 1,
        }
        for sphere_id in ("sphere.fire", "sphere.water")
    }
    request = {
        "schema": "TianxiaFoundry.CharacterCreationCompleteRequest.v1",
        "project_id": "project.compact-provider",
        "project_revision": 12,
        "request_sha256": "a" * 64,
        "content_lock_hash": "b" * 64,
        "bounded_choice_contract": {
            "schema": "TianxiaFoundry.BoundedChoiceContract.v1",
            "fields": {
                "background_ability": "only when the frozen Background authority publishes an allowed ability choice",
            },
        },
        "stage1_prompt": {
            "prompt_id": "must-not-be-forwarded",
            "payload": "archival",
            "envelope": {
                "decision_slots": [{
                    "slot_id": "subpath_choice",
                    "min_selections": 1 if target_cl >= 3 else 0,
                }],
            },
        },
        "typed_choice_snapshot": {"payload": "archival"},
        "delegated_choice_envelope": {
            "frozen_owner_target_cl": {"value": target_cl},
            "allowed_choice_ids_by_slot": allowed,
            "choices_by_slot": choices,
            "typed_choice_authority_by_slot": {
                "advancement_skeleton": {"stage2_authority_by_choice": authorities},
                "sphere_priorities": {"stage2_authority_by_choice": sphere_authorities},
                "background_choice": {
                    "ability_adjustment_by_choice": {
                        "background.scholar": {
                            "allowed_abilities": ["INT", "WIS"],
                            "allowed_amounts": [1, 2],
                        },
                    },
                "background_package_linkage": {
                    "background.scholar": [{
                            "package_index": 0,
                            "sphere_record_id": "sphere.fire",
                            "talent_record_id": "talent.fire.1",
                            "background_sphere_choice_id": "sphere.fire",
                            "background_talent_choice_id": "talent.fire.1",
                        }],
                    },
                },
                "insight_priorities": {
                    "stage2_authority_by_choice": {
                        "insight.meditation": {
                            "authority_complete": True,
                            "allowed_channels": ["cultivation-insight-selection"],
                            "allowed_cls": [1, 2, 3, 4],
                            "allowed_kinds": ["cultivation_insight_acquisition"],
                            "ability_change": {
                                "allowed_abilities": ["WIS", "INT"],
                                "allowed_cls": [1, 2, 3, 4],
                                "amount": 1,
                            },
                        },
                    },
                },
            },
            "selection_limits_by_slot": {
                slot: {
                    "final_min": 1 if slot != "subpath_choice" or target_cl >= 3 else 0,
                    "final_max": 1,
                    "allow_none": slot == "subpath_choice",
                }
                for slot in allowed
            },
            "delegated_fields": {
                "identity.name": {"state": "delegated", "owner_value": None},
                "concept": {"state": "delegated", "owner_value": None},
            },
            "delegated_name_contract": {"state": "delegated", "owner_locked_value": None},
            "advancement_choice_milestones": [{
                "milestone_id": "feature.qi.cl1",
                "path_id": "path.qi",
                "feature_record_id": "feature.qi",
                "cl": 1,
                "allowed_kinds": ["cultivation_insight_acquisition"],
            }],
            "path_progression_choices": [{
                "cl": 1,
                "path_ids": ["path.qi"],
                "description": "Initial Path progression cue.",
            }],
        },
    }
    if with_free_grant:
        sphere_authorities["sphere.fire"].update({
            "allowed_kinds": ["level_sphere_acquisition", "ai_bootstrap_sphere_acquisition"],
            "allowed_channels": ["level-choice", "ai-bootstrap-free-cl1-sphere"],
        })
        authorities["talent.fire.1"].update({
            "allowed_kinds": ["level_talent_acquisition", "ai_bootstrap_talent_acquisition"],
            "free_sphere_talent_eligible": True,
        })
        request["stage1_prompt"]["envelope"]["user_locks"] = [
            {"field": "character_sheet.generation_route", "value": "ai_bootstrap"},
            {
                "field": "character_sheet.canonical_grant_plan",
                "value": {
                    "grant_accounting": {
                        "free_sphere_talent_grant_count": 1,
                        "free_sphere_talent_grants": [
                            {"sphere_id": "sphere.fire", "talent_id": "talent.fire.1"},
                        ],
                    },
                },
            },
        ]
    return request


def _request_with_complete_routes(
    *,
    route_spheres: tuple[str, ...] | None = None,
    free_pair_count: int = 1,
) -> dict:
    """Build complete production-shaped CL15 routes without a catalogue dump."""
    request = _request(target_cl=15, with_free_grant=True)
    envelope = request["delegated_choice_envelope"]
    ordinary = envelope["choices_by_slot"]["advancement_skeleton"]
    authorities = envelope["typed_choice_authority_by_slot"]["advancement_skeleton"]["stage2_authority_by_choice"]
    sphere_authorities = envelope["typed_choice_authority_by_slot"]["sphere_priorities"]["stage2_authority_by_choice"]
    route_spheres = route_spheres or ("fire", "water", "earth", "metal", "wood", "void")
    for sphere in route_spheres:
        sphere_id = f"sphere.{sphere}"
        if sphere_id not in envelope["choices_by_slot"]["sphere_priorities"]:
            envelope["choices_by_slot"]["sphere_priorities"][sphere_id] = _choice(
                sphere_id,
                category="sphere",
                owner=sphere_id,
            )
            sphere_authorities[sphere_id] = {
                "authority_complete": True,
                "allowed_kinds": ["level_sphere_acquisition"],
                "allowed_channels": ["level-choice"],
                "minimum_cl": 1,
            }
        first_index = 4 if sphere in {"fire", "water"} else 1
        for index in range(first_index, 17):
            choice_id = f"talent.{sphere}.{index}"
            ordinary[choice_id] = _choice(
                choice_id,
                category="talent",
                owner=sphere_id,
            )
            authorities[choice_id] = _authority(owner=sphere_id)
        sphere_authorities[sphere_id].update({
            "allowed_kinds": ["level_sphere_acquisition", "ai_bootstrap_sphere_acquisition"],
            "allowed_channels": ["level-choice", "ai-bootstrap-free-cl1-sphere"],
        })
        authorities[f"talent.{sphere}.1"].update({
            "allowed_kinds": ["level_talent_acquisition", "ai_bootstrap_talent_acquisition"],
            "free_sphere_talent_eligible": True,
        })
    # All route pairs are independently authenticated as the explicit
    # ai-bootstrap acquisition kind; the existing fire rows are retained.
    grant_accounting = request["stage1_prompt"]["envelope"]["user_locks"][-1]["value"][
        "grant_accounting"
    ]
    grant_accounting["free_sphere_talent_grant_count"] = free_pair_count
    grant_accounting["free_sphere_talent_grants"] = [
        {"sphere_id": f"sphere.{sphere}", "talent_id": f"talent.{sphere}.1"}
        for sphere in route_spheres[:free_pair_count]
    ]
    envelope["allowed_choice_ids_by_slot"]["advancement_skeleton"] = sorted(ordinary)
    envelope["allowed_choice_ids_by_slot"]["sphere_priorities"] = sorted(
        envelope["choices_by_slot"]["sphere_priorities"]
    )
    return request


def _bind_typed_talent_disposition(
    request: dict,
    talent_id: str,
    *,
    full_description: str,
    combat_ready: bool,
) -> dict:
    """Attach one source-bound typed Talent for the combat route tests."""

    envelope = request["delegated_choice_envelope"]
    row = envelope["choices_by_slot"]["advancement_skeleton"][talent_id]
    source = {
        "anchor": f"test:{talent_id}",
        "path": "tests/frozen-talents.json",
        "source_hash": "c" * 64,
    }
    row["source"] = source
    owner = row["owner"]
    request["server_owned_authority"] = {
        "output_profile": {
            "schema": creation_service.SERVER_OUTPUT_PROFILE_SCHEMA,
            "profile": creation_service.SERVER_OUTPUT_PROFILE_NAME,
            "combat_ready": combat_ready,
        },
    }
    request["typed_choice_snapshot"] = {
        "schema": "TianxiaFoundry.TypedProjectChoiceSnapshot.v1",
        "typed_locks": [{
            "field": "character_sheet.canonical_grant_plan",
            "value": {
                "talent_dispositions": [{
                    "canonical_talent_id": talent_id,
                    "display_name": row["name"],
                    "owning_canonical_sphere_id": owner,
                    "full_description": full_description,
                    "source_reference": {
                        "source_anchor": source["anchor"],
                        "source_path": source["path"],
                        "source_file_sha256": source["source_hash"],
                    },
                }],
            },
        }],
    }
    return request


def _request_with_high_cardinality_complete_routes() -> dict:
    """Build six complete routes beside an unselected catalogue projection."""
    request = _request_with_complete_routes()
    envelope = request["delegated_choice_envelope"]
    choices = envelope["choices_by_slot"]
    ordinary = choices["advancement_skeleton"]
    talent_authorities = envelope["typed_choice_authority_by_slot"]["advancement_skeleton"]["stage2_authority_by_choice"]
    sphere_authorities = envelope["typed_choice_authority_by_slot"]["sphere_priorities"]["stage2_authority_by_choice"]
    # These rows resemble the full catalogue size but cannot become free-pair
    # routes because their frozen authority is level-only.
    for sphere_index in range(79):
        sphere_id = f"sphere.catalog.{sphere_index:02d}"
        choices["sphere_priorities"][sphere_id] = _choice(
            sphere_id,
            category="sphere",
            owner=sphere_id,
        )
        sphere_authorities[sphere_id] = {
            "authority_complete": True,
            "allowed_kinds": ["level_sphere_acquisition"],
            "allowed_channels": ["level-choice"],
            "minimum_cl": 1,
        }
        for talent_index in range(1, 6):
            talent_id = f"talent.catalog.{sphere_index:02d}.{talent_index}"
            ordinary[talent_id] = _choice(
                talent_id,
                category="talent",
                owner=sphere_id,
            )
            talent_authorities[talent_id] = _authority(owner=sphere_id)
    for insight_index in range(400):
        insight_id = f"insight.scale.{insight_index:04d}"
        choices["origin_insight_choice"][insight_id] = _choice(
            insight_id,
            category="insight",
        )
    envelope["allowed_choice_ids_by_slot"]["sphere_priorities"] = sorted(
        choices["sphere_priorities"]
    )
    envelope["allowed_choice_ids_by_slot"]["advancement_skeleton"] = sorted(ordinary)
    envelope["allowed_choice_ids_by_slot"]["origin_insight_choice"] = sorted(
        choices["origin_insight_choice"]
    )
    return request


def test_app_api_import_remains_free_of_factory_authoring_cycle():
    from app.api import create_app

    assert callable(create_app)


def test_provider_prompt_is_compact_deterministic_and_frozen_id_bound():
    request = _request()
    original = deepcopy(request)
    run = {"request": request}
    first = CharacterCreationExecutionService._provider_prompt(run)
    second = CharacterCreationExecutionService._provider_prompt(run)
    assert first == second
    assert request == original
    assert len(first.encode("utf-8")) <= PROVIDER_PROMPT_TARGET_BYTES
    assert len(first.encode("utf-8")) <= PROVIDER_PROMPT_HARD_CAP_BYTES

    payload = json.loads(first)
    assert payload["binding"] == {
        "project_id": request["project_id"],
        "project_revision": request["project_revision"],
        "target_cl": 1,
        "request_sha256": request["request_sha256"],
    }
    assert payload["response_contract"]["schema"] == "TianxiaFoundry.DelegatedSelectionIntentResponse.v1"
    assert payload["response_contract"]["presented_legal_path_progression_ids_by_cl"] == {
        "1": ["path.qi"],
    }
    assert "every ambiguous CL" in payload["response_contract"]["path_progression_representation"]
    assert "presented_legal_path_progression_ids_by_cl" in " ".join(payload["instructions"])
    assert payload["response_contract"]["response_template"]["request_sha256"] == request["request_sha256"]
    template = payload["response_contract"]["response_template"]
    assert set(template) == {
        "schema", "request_sha256", "selection_intent", "acquisition_intent",
        "bounded_choices", "owner_descriptive_fields",
    }
    assert set(template) == set(creation_service.PREFERRED_RESPONSE_KEYS)
    template_by_slot = template["selection_intent"]["by_slot"]
    assert all(value == [] for value in template_by_slot.values())
    assert template["acquisition_intent"] == {
        "sphere_free_talent_pairs": [],
        "ordinary_talent_ids": [],
        "insight_occurrences": [],
    }
    assert template["owner_descriptive_fields"] == {
        "identity": {"name": None},
        "concept": None,
    }
    assert not any(
        text in first
        for text in ("Provider supplied nonblank name", "Provider supplied concise concept")
    )
    assert set(payload["response_contract"]["forbidden_top_level_response_keys"]) >= {
        "project_id", "project_revision", "target_cl", "content_lock_hash", "advancement_skeleton",
    }
    assert template_by_slot["subpath_choice"] == []
    assert "method_choice" in payload["response_contract"]["required_selection_slots"]
    assert "foundation_choice" in payload["response_contract"]["required_selection_slots"]
    assert {
        "sphere_priorities", "insight_priorities", "item_priorities",
    } <= set(payload["response_contract"]["required_selection_slots"])
    assert "planning-only" in payload["response_contract"]["planning_priority_representation"]
    assert payload["response_contract"]["background_package_representation"]
    assert payload["response_contract"]["origin_insight_representation"]
    assert payload["response_contract"]["subpath_choice_representation"]
    background_ability_candidates = payload["bounded_choice_summary"]["background_ability_candidates"]
    assert background_ability_candidates["background.scholar"]["allowed_abilities"] == ["INT", "WIS"]
    assert payload["response_contract"]["background_ability_representation"]
    assert payload["response_contract"]["response_template"]["bounded_choices"]["background_ability"] is None
    assert payload["descriptive_context"]["identity.name"]["state"] == "delegated"
    assert "nonblank" in payload["descriptive_context"]["identity.name"]["provider_action"]
    assert payload["descriptive_context"]["concept"]["state"] == "delegated"
    assert "concept" in payload["descriptive_context"]["concept"]["provider_action"]
    for archival_key in ("complete_request", "stage1_prompt", "typed_choice_snapshot", "source_payloads"):
        assert archival_key not in payload
        assert archival_key not in first

    allowed = request["delegated_choice_envelope"]["allowed_choice_ids_by_slot"]
    for slot_id, rows in payload["allowed_choices_by_slot"].items():
        assert {row["id"] for row in rows} <= set(allowed[slot_id])
    for slot_id in (
        "background_choice",
        "background_sphere_choice",
        "background_talent_choice",
        "origin_insight_choice",
    ):
        assert template_by_slot[slot_id] == []
    assert payload["response_contract"]["subpath_choice_required"] is False
    assert payload["response_contract"]["subpath_choice_minimum"] == 0
    assert "explicit empty array" in payload["response_contract"]["subpath_choice_representation"]
    subpath_row = next(row for row in payload["allowed_choices_by_slot"]["subpath_choice"] if row["id"] == "subpath.stillness")
    assert subpath_row["owner"] == "path.qi"
    linked_package = payload["background_package_linkage"]["background.scholar"][0]
    assert linked_package["background_sphere_choice_id"] == "sphere.fire"
    assert linked_package["background_talent_choice_id"] == "talent.fire.1"
    for slot_id in ("sphere_priorities", "insight_priorities", "item_priorities"):
        assert slot_id in payload["allowed_choices_by_slot"]
        assert {row["id"] for row in payload["allowed_choices_by_slot"][slot_id]} == set(allowed[slot_id])
    path_row = next(row for row in payload["allowed_choices_by_slot"]["path_choice"] if row["id"] == "path.qi")
    assert path_row["requires"] == ["method.internal"]
    assert {"id", "name", "cue"} <= set(path_row)
    assert "category" not in path_row
    assert "minimum_cl" not in path_row
    ordinary_allowed = set(allowed["advancement_skeleton"])
    slots = {
        row["cl"]: set(row["eligible_choice_ids"])
        for row in build_compact_choice_model(request)["ordinary_talent_slots"]
    }
    for rows in payload["ordinary_talent_shortlist_by_sphere"].values():
        for row in rows:
            assert row["id"] in ordinary_allowed
            assert {"id", "name", "cue", "eligible_cl"} <= set(row)
            assert "owner" not in row
            assert "category" not in row
            assert "minimum_cl" not in row
            assert all(row["id"] in slots[cl] for cl in row["eligible_cl"])


def _synthetic_wire_payload() -> dict[str, object]:
    """Build a public-safe nine-milestone projection for wire testing."""

    paths = ("body", "qi", "spirit")
    milestones: dict[str, dict[str, object]] = {}
    insight_profile = {
        "allowed_insight_ids": ["insight.tool", "insight.core"],
        "parameters_by_insight_id": {
            "insight.tool": {"allowed_abilities": ["INT", "WIS"], "amount": 1},
            "insight.core": {"allowed_abilities": ["STR", "CON"], "amount": 1},
        },
    }
    for path in paths:
        rule = {
            "allowed_abilities": ["STR", "WIS"],
            "allowed_deltas": [1, 2],
            "budget": 2,
            "cap": 20,
            "allowed_cls": [4, 8, 12],
            "source": {
                "authority": "authenticated_non_sphere_path_feature",
                "rule_id": f"rule.path.{path}",
                "source": {
                    "path": f"rules/path_{path}.json",
                    "source_hash": (path[0] * 64),
                },
            },
        }
        for cl in (4, 8, 12):
            options: dict[str, object] = {
                "ability_score_change": {
                    "destination": (
                        "bounded_choices.ability_score_changes_by_milestone_id."
                        f"milestone.{path}.{cl}"
                    ),
                    "constraints": deepcopy(rule),
                },
            }
            if cl in (8, 12):
                options["cultivation_insight_acquisition"] = {
                    "destination": "acquisition_intent.insight_occurrences[]",
                    **deepcopy(insight_profile),
                }
            milestones[f"milestone.{path}.{cl}"] = {
                "milestone_id": f"milestone.{path}.{cl}",
                "path_id": f"path.{path}",
                "cl": cl,
                "allowed_kinds": [
                    "ability_score_change",
                    *( ["cultivation_insight_acquisition"] if cl in (8, 12) else []),
                ],
                "resolution_options": options,
            }

    routes: list[dict[str, object]] = []
    shortlist: dict[str, list[dict[str, object]]] = {}
    for sphere in ("fire", "water", "earth", "metal", "wood", "void"):
        sphere_id = f"sphere.{sphere}"
        ordinary_by_cl = {
            str(cl): f"talent.{sphere}.{cl}"
            for cl in range(1, 16)
        }
        free_id = f"talent.{sphere}.free"
        routes.append({
            "route_id": f"route.{sphere}",
            "sphere_id": sphere_id,
            "free_talent_pair": {"sphere_id": sphere_id, "talent_id": free_id},
            "ordinary_talent_ids_by_cl": ordinary_by_cl,
            "ordinary_talent_ids": list(ordinary_by_cl.values()),
            "cross_route_mixing_forbidden": True,
        })
        rows: list[dict[str, object]] = [{
            "id": free_id,
            "owner": sphere_id,
            "eligible_cl": [1],
            "name": "Free display " + "n" * 420,
            "cue": "Free cue " + "c" * 300,
        }]
        rows.extend({
            "id": talent_id,
            "owner": sphere_id,
            "eligible_cl": [cl],
            "name": "Display " + "n" * 420,
            "cue": "Cue " + "c" * 300,
        } for cl, talent_id in enumerate(ordinary_by_cl.values(), start=1))
        shortlist[sphere_id] = rows

    return {
        "schema": "TianxiaFoundry.CharacterCreationProviderPrompt.v2",
        "binding": {
            "project_id": "project.synthetic-wire",
            "project_revision": 1,
            "target_cl": 15,
            "request_sha256": "a" * 64,
        },
        "response_contract": {
            "schema": "TianxiaFoundry.DelegatedSelectionIntentResponse.v1",
            "presented_legal_method_path_pairs": [
                {"method_id": "method.core", "path_id": f"path.{path}"}
                for path in paths
            ],
            "presented_method_allocation_by_id": {
                "method.core": {"path_ids": [f"path.{path}" for path in paths]},
            },
            "required_milestone_resolutions": milestones,
        },
        "allowed_choices_by_slot": {
            "method_choice": [{"id": "method.core"}],
            "foundation_choice": [{"id": "foundation.core"}],
        },
        "ordinary_talent_shortlist_by_sphere": shortlist,
        "sphere_route_modules": routes,
        "choice_row_contract": {},
        "instructions": ["Return one JSON object."],
    }


def _synthetic_wire_bytes(prompt: str) -> bytes:
    payload: dict[str, object] = {
        "model": "synthetic-local-model",
        "messages": [
            {"role": "system", "content": CHARACTER_CREATION_PROVIDER_SYSTEM_MESSAGE},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 6144,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    return canonical_json(payload).encode("utf-8")


def test_synthetic_wire_compaction_is_deterministic_and_preserves_authority():
    raw_payload = _synthetic_wire_payload()
    raw_prompt = canonical_json(raw_payload)
    compacted = creation_service._provider_wire_compact_payload(raw_payload)
    repeated = creation_service._provider_wire_compact_payload(deepcopy(raw_payload))
    prompt = canonical_json(compacted)
    assert compacted == repeated
    assert len(raw_prompt.encode("utf-8")) == 91_456
    assert len(prompt.encode("utf-8")) == 15_042
    assert len(_synthetic_wire_bytes(raw_prompt)) == 96_300
    assert len(_synthetic_wire_bytes(prompt)) == 18_280
    assert len(raw_prompt.encode("utf-8")) > creation_service._PROVIDER_WIRE_COMPACT_TARGET_BYTES
    # The character-creation wire ceiling is intentionally wider than the
    # unchanged model-facing prompt cap: this CL15-sized envelope now fits
    # under the bounded 96 KiB transport limit, while the semantic compactor
    # still removes the archival route growth deterministically.
    assert len(_synthetic_wire_bytes(raw_prompt)) <= PROVIDER_REQUEST_HARD_CAP_BYTES
    assert len(prompt.encode("utf-8")) < len(raw_prompt.encode("utf-8"))
    assert len(_synthetic_wire_bytes(prompt)) < PROVIDER_REQUEST_HARD_CAP_BYTES

    raw_contract = raw_payload["response_contract"]
    contract = compacted["response_contract"]
    assert compacted["binding"] == raw_payload["binding"]
    assert compacted["allowed_choices_by_slot"] == raw_payload["allowed_choices_by_slot"]
    for field in (
        "presented_legal_method_path_pairs",
        "presented_method_allocation_by_id",
    ):
        assert contract[field] == raw_contract[field]

    raw_milestones = raw_contract["required_milestone_resolutions"]
    milestones = contract["required_milestone_resolutions"]
    assert len(milestones) == 9
    assert set(milestones) == set(raw_milestones)
    authority = compacted["milestone_resolution_authority"]
    assert authority["request_sha256"] == raw_payload["binding"]["request_sha256"]
    assert len(authority["ability_score_change_rules"]) == 3
    assert len(authority["cultivation_insight_profiles"]) == 1
    asi_count = 0
    insight_count = 0
    for milestone_id, raw_milestone in raw_milestones.items():
        milestone = milestones[milestone_id]
        assert milestone["path_id"] == raw_milestone["path_id"]
        assert milestone["cl"] == raw_milestone["cl"]
        raw_options = raw_milestone["resolution_options"]
        options = milestone["resolution_options"]
        raw_asi = raw_options["ability_score_change"]
        compact_asi = options["ability_score_change"]
        ref = compact_asi["constraints_ref"]
        prefix = "milestone_resolution_authority.ability_score_change_rules."
        assert ref.startswith(prefix)
        assert authority["ability_score_change_rules"][ref[len(prefix):]] == raw_asi["constraints"]
        assert "constraints" not in compact_asi
        asi_count += 1
        if "cultivation_insight_acquisition" in raw_options:
            raw_insight = raw_options["cultivation_insight_acquisition"]
            compact_insight = options["cultivation_insight_acquisition"]
            ref = compact_insight["authority_ref"]
            prefix = "milestone_resolution_authority.cultivation_insight_profiles."
            assert ref.startswith(prefix)
            assert authority["cultivation_insight_profiles"][ref[len(prefix):]] == {
                "allowed_insight_ids": raw_insight["allowed_insight_ids"],
                "parameters_by_insight_id": raw_insight["parameters_by_insight_id"],
            }
            assert "allowed_insight_ids" not in compact_insight
            assert "parameters_by_insight_id" not in compact_insight
            insight_count += 1
    assert asi_count == 9
    assert insight_count == 6

    raw_routes = raw_payload["sphere_route_modules"]
    routes = compacted["sphere_route_modules"]
    assert len(routes) == len(raw_routes) == 6
    for raw_route, route in zip(raw_routes, routes):
        for field in (
            "route_id", "sphere_id", "free_talent_pair",
            "ordinary_talent_ids_by_cl", "cross_route_mixing_forbidden",
        ):
            assert route[field] == raw_route[field]
        assert "ordinary_talent_ids" not in route
    raw_shortlist = raw_payload["ordinary_talent_shortlist_by_sphere"]
    shortlist = compacted["ordinary_talent_shortlist_by_sphere"]
    assert set(shortlist) == set(raw_shortlist)
    for owner, raw_rows in raw_shortlist.items():
        rows = shortlist[owner]
        assert all(set(row) == {"id", "eligible_cl"} for row in rows)
        assert [
            (row["id"], row["eligible_cl"])
            for row in rows
        ] == [
            (row["id"], row["eligible_cl"])
            for row in raw_rows
        ]
    assert "ordinary_talent_shortlist_by_sphere_ref" not in compacted


def test_cl15_compact_wire_is_within_character_creation_request_cap():
    payload = creation_service._provider_wire_compact_payload(_synthetic_wire_payload())
    prompt = canonical_json(payload)
    wire = _synthetic_wire_bytes(prompt)

    # The default request ceiling is sized for a 64K-token model and may be
    # lowered through the environment; the compact wire must fit either way.
    assert PROVIDER_REQUEST_HARD_CAP_BYTES >= 96 * 1024
    assert len(wire) == 18_280
    assert len(wire) <= PROVIDER_REQUEST_HARD_CAP_BYTES


def _route_compaction_fixture(
    *,
    shortlist: dict[str, list[dict[str, object]]] | None = None,
    routes: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "binding": {"request_sha256": "a" * 64},
        "response_contract": {
            "required_milestone_resolutions": {
                "milestone.1": {
                    "milestone_id": "milestone.1",
                    "path_id": "path.qi",
                    "cl": 1,
                    "resolution_options": {
                        "ability_score_change": {
                            "destination": "bounded_choices.ability_score_changes_by_milestone_id.milestone.1",
                            "constraints": {
                                "allowed_abilities": ["STR"],
                                "allowed_deltas": [1],
                                "budget": 1,
                                "cap": 20,
                                "source": {
                                    "authority": "authenticated_non_sphere_path_feature",
                                    "rule_id": "rule.milestone.1",
                                    "source": {
                                        "path": "rules/path.json",
                                        "source_hash": "b" * 64,
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
        "ordinary_talent_shortlist_by_sphere": (
            shortlist
            if shortlist is not None
            else {"sphere.fire": [{"id": "talent.fire.1", "eligible_cl": [1]}]}
        ),
        "sphere_route_modules": (
            routes
            if routes is not None
            else [{
                "route_id": "route.fire",
                "sphere_id": "sphere.fire",
                "ordinary_talent_ids_by_cl": {"1": "talent.fire.1"},
                "ordinary_talent_ids": ["talent.fire.1"],
            }]
        ),
        "choice_row_contract": {},
        "instructions": [],
        # Force the >60k compact-shortlist branch so owner evidence is removed
        # only after the proof has consumed the untouched rows.
        "fixture_padding": "x" * 61_000,
    }


def test_route_shortlist_elision_requires_exact_owner_and_cl_proof():
    coherent = creation_service._provider_wire_compact_payload(_route_compaction_fixture())
    assert coherent["ordinary_talent_shortlist_by_sphere"] == {}
    assert coherent["ordinary_talent_shortlist_by_sphere_ref"] == (
        "sphere_route_modules[].ordinary_talent_ids_by_cl"
    )

    empty = creation_service._provider_wire_compact_payload(
        _route_compaction_fixture(shortlist={})
    )
    assert empty["ordinary_talent_shortlist_by_sphere"] == {}
    assert "ordinary_talent_shortlist_by_sphere_ref" not in empty

    empty_routes = creation_service._provider_wire_compact_payload(
        _route_compaction_fixture(routes=[])
    )
    assert empty_routes["ordinary_talent_shortlist_by_sphere"]

    duplicate_eligible_cl = _route_compaction_fixture(shortlist={
        "sphere.fire": [{"id": "talent.fire.1", "eligible_cl": [1, 1]}],
    })
    duplicate_eligible_result = creation_service._provider_wire_compact_payload(duplicate_eligible_cl)
    assert duplicate_eligible_result["ordinary_talent_shortlist_by_sphere"]

    duplicate_row = _route_compaction_fixture(shortlist={
        "sphere.fire": [
            {"id": "talent.fire.1", "eligible_cl": [1]},
            {"id": "talent.fire.1", "eligible_cl": [1]},
        ],
    })
    duplicate_row_result = creation_service._provider_wire_compact_payload(duplicate_row)
    assert duplicate_row_result["ordinary_talent_shortlist_by_sphere"]

    missing_route_id = _route_compaction_fixture(routes=[{
        "sphere_id": "sphere.fire",
        "ordinary_talent_ids_by_cl": {"1": "talent.fire.1"},
        "ordinary_talent_ids": ["talent.fire.1"],
    }])
    missing_route_id_result = creation_service._provider_wire_compact_payload(missing_route_id)
    assert missing_route_id_result["ordinary_talent_shortlist_by_sphere"]

    blank_route_id = _route_compaction_fixture(routes=[{
        "route_id": "   ",
        "sphere_id": "sphere.fire",
        "ordinary_talent_ids_by_cl": {"1": "talent.fire.1"},
        "ordinary_talent_ids": ["talent.fire.1"],
    }])
    blank_route_id_result = creation_service._provider_wire_compact_payload(blank_route_id)
    assert blank_route_id_result["ordinary_talent_shortlist_by_sphere"]

    duplicate_route_id = _route_compaction_fixture(routes=[
        {
            "route_id": "route.duplicate",
            "sphere_id": "sphere.fire",
            "ordinary_talent_ids_by_cl": {"1": "talent.fire.1"},
            "ordinary_talent_ids": ["talent.fire.1"],
        },
        {
            "route_id": "route.duplicate",
            "sphere_id": "sphere.water",
            "ordinary_talent_ids_by_cl": {"1": "talent.water.1"},
            "ordinary_talent_ids": ["talent.water.1"],
        },
    ])
    duplicate_route_id_result = creation_service._provider_wire_compact_payload(duplicate_route_id)
    assert duplicate_route_id_result["ordinary_talent_shortlist_by_sphere"]

    duplicate_talent_across_owners = _route_compaction_fixture(
        shortlist={
            "sphere.fire": [{"id": "talent.shared", "eligible_cl": [1]}],
            "sphere.water": [{"id": "talent.shared", "eligible_cl": [1]}],
        },
        routes=[
            {
                "route_id": "route.fire",
                "sphere_id": "sphere.fire",
                "ordinary_talent_ids_by_cl": {"1": "talent.shared"},
                "ordinary_talent_ids": ["talent.shared"],
            },
            {
                "route_id": "route.water",
                "sphere_id": "sphere.water",
                "ordinary_talent_ids_by_cl": {"1": "talent.shared"},
                "ordinary_talent_ids": ["talent.shared"],
            },
        ],
    )
    duplicate_talent_result = creation_service._provider_wire_compact_payload(
        duplicate_talent_across_owners
    )
    assert duplicate_talent_result["ordinary_talent_shortlist_by_sphere"]

    wrong_owner = _route_compaction_fixture(shortlist={
        "sphere.water": [{"id": "talent.fire.1", "eligible_cl": [1]}],
    })
    wrong_owner_result = creation_service._provider_wire_compact_payload(wrong_owner)
    assert wrong_owner_result["ordinary_talent_shortlist_by_sphere"]

    explicit_row_owner = _route_compaction_fixture(shortlist={
        "sphere.fire": [{
            "id": "talent.fire.1",
            "owner": "sphere.water",
            "eligible_cl": [1],
        }],
    })
    explicit_row_owner_result = creation_service._provider_wire_compact_payload(explicit_row_owner)
    assert explicit_row_owner_result["ordinary_talent_shortlist_by_sphere"]

    wrong_cl = _route_compaction_fixture(shortlist={
        "sphere.fire": [{"id": "talent.fire.1", "eligible_cl": [2]}],
    })
    wrong_cl_result = creation_service._provider_wire_compact_payload(wrong_cl)
    assert wrong_cl_result["ordinary_talent_shortlist_by_sphere"]

    wrong_assignment = _route_compaction_fixture(shortlist={
        "sphere.fire": [{"id": "talent.fire.2", "eligible_cl": [1]}],
    })
    wrong_assignment_result = creation_service._provider_wire_compact_payload(wrong_assignment)
    assert wrong_assignment_result["ordinary_talent_shortlist_by_sphere"]

    malformed_route = _route_compaction_fixture(routes=[{
        "route_id": "route.fire",
        "sphere_id": "sphere.fire",
        "ordinary_talent_ids_by_cl": {"1": "talent.fire.1"},
        "ordinary_talent_ids": "not-a-list",
    }])
    malformed_result = creation_service._provider_wire_compact_payload(malformed_route)
    assert malformed_result["ordinary_talent_shortlist_by_sphere"]

    duplicate_owner = _route_compaction_fixture(routes=[
        {
            "route_id": "route.fire.1",
            "sphere_id": "sphere.fire",
            "ordinary_talent_ids_by_cl": {"1": "talent.fire.1"},
            "ordinary_talent_ids": ["talent.fire.1"],
        },
        {
            "route_id": "route.fire.2",
            "sphere_id": "sphere.fire",
            "ordinary_talent_ids_by_cl": {"1": "talent.fire.1"},
            "ordinary_talent_ids": ["talent.fire.1"],
        },
    ])
    duplicate_result = creation_service._provider_wire_compact_payload(duplicate_owner)
    assert duplicate_result["ordinary_talent_shortlist_by_sphere"]


def test_provider_prompt_presents_all_selected_path_milestones_and_no_filled_answer():
    request = _request(target_cl=3)
    envelope = request["delegated_choice_envelope"]
    envelope["advancement_choice_milestones"].append({
        "milestone_id": "feature.qi.cl3",
        "path_id": "path.qi",
        "feature_record_id": "feature.qi.cl3",
        "cl": 3,
        "allowed_kinds": ["ability_score_change", "cultivation_insight_acquisition"],
        "ability_change": {
            "allowed_abilities": ["STR", "WIS"],
            "allowed_deltas": [1, 2],
            "budget": 2,
            "cap": 20,
        },
        "ability_change_source": {
            "authority": "authenticated_non_sphere_path_feature",
            "rule_id": "ns1r.path.qi.feature.cl3.v1",
            "source": {
                "path": "non_sphere_authority/authority/qi_cultivation.path_index.p2a.json",
                "source_hash": "a" * 64,
            },
        },
    })
    request["bounded_choice_contract"]["fields"]["ability_score_changes_by_milestone_id"] = (
        "typed ASI deltas keyed by advertised source milestone ID"
    )

    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    contract = payload["response_contract"]
    milestones = contract["required_milestone_resolutions"]
    assert set(milestones) == {"feature.qi.cl1", "feature.qi.cl3"}
    assert milestones["feature.qi.cl1"]["response_destinations"] == {
        "cultivation_insight_acquisition": "acquisition_intent.insight_occurrences[]",
    }
    assert milestones["feature.qi.cl3"]["response_destinations"] == {
        "ability_score_change": "bounded_choices.ability_score_changes_by_milestone_id.feature.qi.cl3",
        "cultivation_insight_acquisition": "acquisition_intent.insight_occurrences[]",
    }
    template = contract["response_template"]
    assert set(template) == set(creation_service.PREFERRED_RESPONSE_KEYS)
    assert all(value == [] for value in template["selection_intent"]["by_slot"].values())
    assert template["acquisition_intent"] == {
        "sphere_free_talent_pairs": [],
        "ordinary_talent_ids": [],
        "insight_occurrences": [],
    }
    assert template["bounded_choices"]["ability_score_changes_by_milestone_id"] == {
        "feature.qi.cl1": None,
        "feature.qi.cl3": None,
    }
    summary = payload["bounded_choice_summary"]["milestone_and_path_progression_cues"]
    assert summary["advancement_choice_milestones_ref"] == (
        "response_contract.required_milestone_resolutions"
    )
    assert summary["resolution_rule"].startswith("Resolve exactly one listed ASI or Insight")
    assert milestones["feature.qi.cl3"]["resolution_options"]["ability_score_change"]["constraints"] == {
        "allowed_abilities": ["STR", "WIS"],
        "allowed_deltas": [1, 2],
        "budget": 2,
        "cap": 20,
        "source": {
            "authority": "authenticated_non_sphere_path_feature",
            "rule_id": "ns1r.path.qi.feature.cl3.v1",
            "source": {
                "path": "non_sphere_authority/authority/qi_cultivation.path_index.p2a.json",
                "source_hash": "a" * 64,
            },
        },
    }
    assert template["owner_descriptive_fields"] == {
        "identity": {"name": None},
        "concept": None,
    }
    assert "Provider supplied" not in json.dumps(payload)
    assert "fully filled" not in json.dumps(payload).lower()


def test_provider_prompt_makes_cl4_resolution_unavoidable_when_insight_is_not_legal():
    request = _request(target_cl=4)
    envelope = request["delegated_choice_envelope"]
    envelope["typed_choice_authority_by_slot"]["insight_priorities"] = {
        "stage2_authority_by_choice": {
            "insight.meditation": {
                "authority_complete": True,
                "allowed_channels": ["cultivation-insight-selection"],
                "allowed_cls": [8],
                "allowed_kinds": ["cultivation_insight_acquisition"],
            },
        },
    }
    envelope["advancement_choice_milestones"].append({
        "milestone_id": "feature.qi.cl4",
        "path_id": "path.qi",
        "feature_record_id": "feature.qi.cl4",
        "cl": 4,
        "allowed_kinds": ["ability_score_change", "cultivation_insight_acquisition"],
        "ability_change": {
            "allowed_cls": [4],
            "allowed_deltas": [1, 2],
            "budget": 2,
            "cap": 20,
        },
        "ability_change_source": {
            "authority": "authenticated_non_sphere_path_feature",
            "rule_id": "ns1r.path.qi.feature.cl4.v1",
            "source": {
                "path": "non_sphere_authority/authority/qi_cultivation.path_index.p2a.json",
                "source_hash": "a" * 64,
            },
        },
    })
    request["bounded_choice_contract"]["fields"]["ability_score_changes_by_milestone_id"] = (
        "typed ASI deltas keyed by advertised source milestone ID"
    )

    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    milestone = payload["response_contract"]["required_milestone_resolutions"]["feature.qi.cl4"]
    options = milestone["resolution_options"]
    assert options["ability_score_change"]["destination"].endswith("feature.qi.cl4")
    assert options["ability_score_change"]["constraints"] == {
        "allowed_cls": [4],
        "allowed_deltas": [1, 2],
        "budget": 2,
        "cap": 20,
        "source": {
            "authority": "authenticated_non_sphere_path_feature",
            "rule_id": "ns1r.path.qi.feature.cl4.v1",
            "source": {
                "path": "non_sphere_authority/authority/qi_cultivation.path_index.p2a.json",
                "source_hash": "a" * 64,
            },
        },
    }
    assert "cultivation_insight_acquisition" not in options
    assert payload["response_contract"]["response_template"]["bounded_choices"][
        "ability_score_changes_by_milestone_id"
    ]["feature.qi.cl4"] is None
    instructions = " ".join(payload["instructions"])
    assert "an empty/null placeholder is not a resolution" in instructions
    # 80fee3e0 (2026-09-13) reworded the rule to one milestone per CL, taken
    # from the Path named for that CL in path_progression_by_cl.
    assert "resolve exactly one advancement milestone per CL" in instructions


def test_provider_prompt_omits_insight_when_typed_authority_is_incomplete():
    request = _request(target_cl=1)
    request["delegated_choice_envelope"]["typed_choice_authority_by_slot"][
        "insight_priorities"
    ]["stage2_authority_by_choice"]["insight.meditation"] = {
        "authority_complete": False,
        "allowed_kinds": ["cultivation_insight_acquisition"],
        "allowed_channels": ["cultivation-insight-selection"],
        "allowed_cls": [1],
    }

    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    milestone = payload["response_contract"]["required_milestone_resolutions"]["feature.qi.cl1"]
    assert milestone["resolution_options"] == {
        "blocked": {"reason": "NO_SOURCE_BACKED_RESOLUTION"},
    }
    assert milestone["response_destinations"] == {}
    assert milestone["allowed_kinds"] == []


def test_provider_prompt_blocks_asi_without_a_frozen_path_rule():
    request = _request(target_cl=4)
    envelope = request["delegated_choice_envelope"]
    envelope["advancement_choice_milestones"].append({
        "milestone_id": "feature.qi.cl4.unbound",
        "path_id": "path.qi",
        "feature_record_id": "feature.qi.cl4.unbound",
        "cl": 4,
        "allowed_kinds": ["ability_score_change"],
    })
    request["bounded_choice_contract"]["fields"]["ability_score_changes_by_milestone_id"] = (
        "typed ASI deltas keyed by advertised source milestone ID"
    )

    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    milestone = payload["response_contract"]["required_milestone_resolutions"]["feature.qi.cl4.unbound"]
    assert milestone["resolution_options"] == {
        "blocked": {"reason": "NO_SOURCE_BACKED_RESOLUTION"},
    }
    assert milestone["response_destinations"] == {}
    assert milestone["allowed_kinds"] == []


def test_production_materializer_requires_and_accepts_source_backed_cl4_asi(monkeypatch):
    """The real Stage 2 derivation must not accept an omitted or forged ASI."""
    from test_empty_subpath_materialization import PATH_ID, _materializer

    service, run, project, intent = _materializer(
        monkeypatch,
        target_cl=4,
        select_subpath=False,
    )
    records = service._locked_records_for_project(project["project_id"])
    feature_id = f"{PATH_ID}.feature.cl4"
    feature = records[feature_id]
    feature_authority = feature["compatibility"]["factory"]["stage2_authority"]
    feature_authority.update({
        "authority_complete": True,
        "allowed_kinds": ["level_advance", "ability_score_change"],
        "allowed_channels": ["level-advance", "level-choice"],
        "feature_kind": "advancement_choice",
        "path_id": PATH_ID,
        "feature_record_id": feature_id,
        "rule_id": f"{feature_id}.v1",
        "ability_change": {
            "allowed_cls": [4],
            "allowed_deltas": [1, 2],
            "budget": 2,
            "cap": 20,
        },
    })
    feature["source"] = {
        "path": "non_sphere_authority/authority/qi_cultivation.path_index.p2a.json",
        "source_hash": "a" * 64,
    }
    service._locked_records_for_project = lambda _project_id: records

    with pytest.raises(FoundryError) as missing:
        service._derive_stage2_rows_from_frozen_authority(run, project, intent)
    assert missing.value.code == "CG1_BOUNDED_DECISION_REQUIRED"
    assert missing.value.details["milestone_id"] == f"{feature_id}.cl4"

    corrected_document = intent.as_dict()
    corrected_document.setdefault("bounded_choices", {})[
        "ability_score_changes_by_milestone_id"
    ] = {
        f"{feature_id}.cl4": {"deltas": {"STR": 2}},
    }
    corrected = CanonicalSelectionIntent.from_document(corrected_document)
    rows = service._derive_stage2_rows_from_frozen_authority(run, project, corrected)
    asi_rows = [row for row in rows if row["kind"] == "ability_score_change"]
    assert asi_rows == [{
        "kind": "ability_score_change",
        "effective_cl": 4,
        "record_id": feature_id,
        "acquisition_channel": "level-choice",
        "parameters": {"deltas": {"STR": 2}},
    }]

    over_cap_document = deepcopy(corrected_document)
    over_cap_document["bounded_choices"]["ability_scores"]["STR"] = 19
    over_cap = CanonicalSelectionIntent.from_document(over_cap_document)
    with pytest.raises(FoundryError) as over_cap_error:
        service._derive_stage2_rows_from_frozen_authority(run, project, over_cap)
    assert over_cap_error.value.code == "CG1_BOUNDED_DECISION_REQUIRED"
    assert over_cap_error.value.details == {
        "field": f"bounded_choices.ability_score_changes_by_milestone_id.{feature_id}.cl4",
        "milestone_id": f"{feature_id}.cl4",
        "effective_cl": 4,
        "ability": "STR",
        "current_score": 19,
        "delta": 2,
        "resulting_score": 21,
        "cap": 20,
    }

    at_cap_document = deepcopy(corrected_document)
    at_cap_document["bounded_choices"]["ability_scores"]["STR"] = 18
    at_cap = CanonicalSelectionIntent.from_document(at_cap_document)
    at_cap_rows = service._derive_stage2_rows_from_frozen_authority(run, project, at_cap)
    assert [
        row for row in at_cap_rows
        if row["kind"] == "ability_score_change"
    ] == [{
        "kind": "ability_score_change",
        "effective_cl": 4,
        "record_id": feature_id,
        "acquisition_channel": "level-choice",
        "parameters": {"deltas": {"STR": 2}},
    }]


def test_production_materializer_counts_background_and_prior_asi_before_cap(monkeypatch):
    """Cap checks use the score state at each milestone, not the starting map."""
    from test_empty_subpath_materialization import BACKGROUND_ID, PATH_ID, _materializer

    service, run, project, intent = _materializer(
        monkeypatch,
        target_cl=8,
        select_subpath=False,
    )
    records = service._locked_records_for_project(project["project_id"])
    background_authority = records[BACKGROUND_ID]["compatibility"]["factory"]["stage2_authority"]
    background_authority["ability_adjustment"] = {
        "allowed_abilities": ["STR"],
        "amount": 1,
        "cap": 20,
    }
    for cl in (4, 8):
        feature_id = f"{PATH_ID}.feature.cl{cl}"
        feature = records[feature_id]
        feature_authority = feature["compatibility"]["factory"]["stage2_authority"]
        feature_authority.update({
            "authority_complete": True,
            "allowed_kinds": ["level_advance", "ability_score_change"],
            "allowed_channels": ["level-advance", "level-choice"],
            "feature_kind": "advancement_choice",
            "path_id": PATH_ID,
            "feature_record_id": feature_id,
            "rule_id": f"{feature_id}.v1",
            "ability_change": {
                "allowed_cls": [4, 8],
                "allowed_deltas": [1, 2],
                "budget": 2,
                "cap": 20,
            },
        })
        feature["source"] = {
            "path": "non_sphere_authority/authority/qi_cultivation.path_index.p2a.json",
            "source_hash": "a" * 64,
        }
    service._locked_records_for_project = lambda _project_id: records

    valid_document = intent.as_dict()
    valid_document["bounded_choices"]["ability_scores"]["STR"] = 15
    valid_document["bounded_choices"]["background_ability"] = "STR"
    valid_document["bounded_choices"]["ability_score_changes_by_milestone_id"] = {
        f"{PATH_ID}.feature.cl4.cl4": {"deltas": {"STR": 2}},
        f"{PATH_ID}.feature.cl8.cl8": {"deltas": {"STR": 2}},
    }
    valid = CanonicalSelectionIntent.from_document(valid_document)
    rows = service._derive_stage2_rows_from_frozen_authority(run, project, valid)
    assert [
        row["parameters"]["deltas"]
        for row in rows
        if row["kind"] == "ability_score_change"
    ] == [{"STR": 2}, {"STR": 2}]

    over_cap_document = deepcopy(valid_document)
    over_cap_document["bounded_choices"]["ability_scores"]["STR"] = 16
    over_cap = CanonicalSelectionIntent.from_document(over_cap_document)
    with pytest.raises(FoundryError) as over_cap_error:
        service._derive_stage2_rows_from_frozen_authority(run, project, over_cap)
    assert over_cap_error.value.code == "CG1_BOUNDED_DECISION_REQUIRED"
    assert over_cap_error.value.details["milestone_id"] == f"{PATH_ID}.feature.cl8.cl8"
    assert over_cap_error.value.details["current_score"] == 19
    assert over_cap_error.value.details["resulting_score"] == 21
    assert over_cap_error.value.details["cap"] == 20


def _insight_materializer(monkeypatch, *, target_cl: int, milestone_cls: tuple[int, ...], score: int):
    from test_empty_subpath_materialization import PATH_ID, _materializer, _record

    service, run, project, intent = _materializer(
        monkeypatch,
        target_cl=target_cl,
        select_subpath=False,
    )
    records = service._locked_records_for_project(project["project_id"])
    insight_id = "tianxia.insight.test"
    for cl in milestone_cls:
        feature_id = f"{PATH_ID}.feature.cl{cl}"
        feature = records[feature_id]
        feature_authority = feature["compatibility"]["factory"]["stage2_authority"]
        feature_authority.update({
            "authority_complete": True,
            "allowed_kinds": ["level_advance", "ability_score_change"],
            "allowed_channels": ["level-advance", "level-choice"],
            "feature_kind": "advancement_choice",
            "path_id": PATH_ID,
            "feature_record_id": feature_id,
            "rule_id": f"{feature_id}.v1",
            "ability_change": {
                "allowed_cls": list(milestone_cls),
                "allowed_deltas": [1, 2],
                "budget": 2,
                "cap": 20,
            },
        })
        feature["source"] = {
            "path": "non_sphere_authority/authority/qi_cultivation.path_index.p2a.json",
            "source_hash": "a" * 64,
        }
    records[insight_id] = _record(
        insight_id,
        "cultivation_insight",
        ["cultivation_insight_acquisition"],
        ["cultivation-insight-selection"],
        allowed_cls=list(milestone_cls),
        ability_change={
            "allowed_abilities": ["STR"],
            "amount": 2,
            "cap": 20,
        },
    )
    service._locked_records_for_project = lambda _project_id: records
    document = intent.as_dict()
    document["bounded_choices"]["ability_scores"]["STR"] = score
    document["acquisition_intent"]["insight_occurrences"] = [
        {
            "insight_id": insight_id,
            "milestone_id": f"{PATH_ID}.feature.cl{cl}.cl{cl}",
            "parameters": {"ability": "STR"},
        }
        for cl in milestone_cls
    ]
    return service, run, project, records, document


@pytest.mark.parametrize(
    "adjustment",
    [
        {"allowed_abilities": ["STR"], "amount": 1},
        {"allowed_abilities": ["STR"], "amount": 1, "cap": "20"},
    ],
    ids=["missing-cap", "malformed-cap"],
)
def test_production_materializer_rejects_incomplete_background_cap(monkeypatch, adjustment):
    from test_empty_subpath_materialization import BACKGROUND_ID, _materializer

    service, run, project, intent = _materializer(
        monkeypatch,
        target_cl=1,
        select_subpath=False,
    )
    records = service._locked_records_for_project(project["project_id"])
    records[BACKGROUND_ID]["compatibility"]["factory"]["stage2_authority"]["ability_adjustment"] = adjustment
    service._locked_records_for_project = lambda _project_id: records
    document = intent.as_dict()
    document["bounded_choices"]["background_ability"] = "STR"
    candidate = CanonicalSelectionIntent.from_document(document)

    with pytest.raises(FoundryError) as raised:
        service._derive_stage2_rows_from_frozen_authority(run, project, candidate)
    assert raised.value.code == "CG1_BOUNDED_DECISION_REQUIRED"


@pytest.mark.parametrize("mutation", ["missing-rule", "missing-cap", "incomplete-authority"])
def test_production_materializer_rejects_incomplete_insight_authority(monkeypatch, mutation):
    service, run, project, records, document = _insight_materializer(
        monkeypatch,
        target_cl=4,
        milestone_cls=(4,),
        score=18,
    )
    insight_authority = records["tianxia.insight.test"]["compatibility"]["factory"]["stage2_authority"]
    if mutation == "missing-rule":
        insight_authority.pop("ability_change")
    elif mutation == "missing-cap":
        insight_authority["ability_change"].pop("cap")
    else:
        insight_authority["authority_complete"] = False
    candidate = CanonicalSelectionIntent.from_document(document)

    with pytest.raises(FoundryError) as raised:
        service._derive_stage2_rows_from_frozen_authority(run, project, candidate)
    assert raised.value.code == "CG1_BOUNDED_DECISION_REQUIRED"
    assert raised.value.details["milestone_id"] == "tianxia.path.qi_cultivation.feature.cl4.cl4"


def test_production_materializer_accepts_insight_at_cap_and_rejects_later_cumulative_change(monkeypatch):
    service, run, project, _records, document = _insight_materializer(
        monkeypatch,
        target_cl=8,
        milestone_cls=(4, 8),
        score=16,
    )
    candidate = CanonicalSelectionIntent.from_document(document)
    rows = service._derive_stage2_rows_from_frozen_authority(run, project, candidate)
    insight_rows = [row for row in rows if row["kind"] == "cultivation_insight_acquisition"]
    assert [row["parameters"] for row in insight_rows] == [
        {"ability": "STR", "amount": 2, "repeat_index": 1},
        {"ability": "STR", "amount": 2, "repeat_index": 2},
    ]

    over_cap_document = deepcopy(document)
    over_cap_document["bounded_choices"]["ability_scores"]["STR"] = 18
    over_cap = CanonicalSelectionIntent.from_document(over_cap_document)
    with pytest.raises(FoundryError) as raised:
        service._derive_stage2_rows_from_frozen_authority(run, project, over_cap)
    assert raised.value.code == "CG1_BOUNDED_DECISION_REQUIRED"
    assert raised.value.details["milestone_id"] == "tianxia.path.qi_cultivation.feature.cl8.cl8"
    assert raised.value.details["current_score"] == 20
    assert raised.value.details["resulting_score"] == 22
    assert raised.value.details["cap"] == 20


def test_provider_prompt_builds_complete_distinct_route_modules_and_is_reorder_stable():
    request = _request_with_complete_routes()
    first = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    routes = first["sphere_route_modules"]
    assert len(routes) >= 2
    assert {row["sphere_id"] for row in routes} >= {"sphere.fire", "sphere.water"}
    for route in routes:
        pair = route["free_talent_pair"]
        by_cl = route["ordinary_talent_ids_by_cl"]
        assert pair["sphere_id"] == route["sphere_id"]
        assert set(by_cl) == {str(cl) for cl in range(1, 16)}
        assert len(set(by_cl.values())) == 15
        assert route["ordinary_talent_ids"] == [by_cl[str(cl)] for cl in range(1, 16)]
        assert route["cross_route_mixing_forbidden"] is True
    contract = first["response_contract"]
    assert contract["sphere_route_modules_ref"] == "sphere_route_modules"
    route_map = {
        route["route_id"]: {
            str(cl): [route["ordinary_talent_ids_by_cl"][str(cl)]]
            for cl in range(1, 16)
        }
        for route in routes
    }
    assert set(route_map) == {route["route_id"] for route in routes}
    for route in routes:
        assert route_map[route["route_id"]] == {
            str(cl): [route["ordinary_talent_ids_by_cl"][str(cl)]]
            for cl in range(1, 16)
        }
    for cl in range(1, 16):
        assert set(
            talent_id
            for route in routes
            for talent_id in route_map[route["route_id"]][str(cl)]
        ) == {
            route["ordinary_talent_ids_by_cl"][str(cl)] for route in routes
        }
    assert first["choice_row_contract"]["ordinary_shortlist_per_route"] == 15
    assert len(first["ordinary_talent_shortlist_by_sphere"]["sphere.fire"]) >= 15
    assert len(first["ordinary_talent_shortlist_by_sphere"]["sphere.water"]) >= 15
    assert len(canonical_json(first).encode("utf-8")) <= PROVIDER_PROMPT_TARGET_BYTES

    reordered = deepcopy(request)
    envelope = reordered["delegated_choice_envelope"]
    for slot_id in ("sphere_priorities", "advancement_skeleton"):
        rows = envelope["choices_by_slot"][slot_id]
        envelope["choices_by_slot"][slot_id] = dict(reversed(list(rows.items())))
        envelope["allowed_choice_ids_by_slot"][slot_id] = list(
            reversed(envelope["allowed_choice_ids_by_slot"][slot_id])
        )
        authorities = envelope["typed_choice_authority_by_slot"][slot_id]["stage2_authority_by_choice"]
        envelope["typed_choice_authority_by_slot"][slot_id]["stage2_authority_by_choice"] = dict(
            reversed(list(authorities.items()))
        )
    second = json.loads(CharacterCreationExecutionService._provider_prompt({"request": reordered}))
    assert first["sphere_route_modules"] == second["sphere_route_modules"]
    assert first["response_contract"] == second["response_contract"]


def test_provider_prompt_keeps_one_bootstrap_pair_for_a_long_route():
    request = _request_with_complete_routes(
        route_spheres=("fire", "water", "earth", "metal", "wood", "void", "air", "ice"),
        free_pair_count=1,
    )

    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    routes = payload["sphere_route_modules"]
    contract = payload["response_contract"]

    assert contract["expected_acquisition_counts"]["sphere_free_talent_pairs"] == 1
    assert routes
    assert len({route["route_id"] for route in routes}) == len(routes)
    pairs = [route["free_talent_pair"] for route in routes]
    assert len({(pair["sphere_id"], pair["talent_id"]) for pair in pairs}) == len(pairs)
    assert contract["presented_legal_first_cycle_pairs"] == pairs
    for route in routes:
        assignments = route["ordinary_talent_ids_by_cl"]
        assert set(assignments) == {str(cl) for cl in range(1, 16)}
        assert len(set(assignments.values())) == 15
    assert len(payload["ordinary_talent_shortlist_by_sphere"]) == 6
    assert len(canonical_json(payload).encode("utf-8")) <= PROVIDER_PROMPT_HARD_CAP_BYTES


def test_combat_ready_filters_action_declared_free_talent_without_cost_and_keeps_alternative():
    request = _bind_typed_talent_disposition(
        _request_with_complete_routes(),
        "talent.fire.1",
        full_description=(
            "Action Type: Action\n"
            "Canonical Action Type: Action\n"
            "Factory Combat Bucket: action\n"
            "A joint maneuver with no standalone activation cost."
        ),
        combat_ready=True,
    )

    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    routes = payload["sphere_route_modules"]
    pairs = [route["free_talent_pair"] for route in routes]

    assert pairs
    assert all(pair["talent_id"] != "talent.fire.1" for pair in pairs)
    assert any(pair["sphere_id"] != "sphere.fire" for pair in pairs)
    assert len({(pair["sphere_id"], pair["talent_id"]) for pair in pairs}) == len(pairs)
    assert len(canonical_json(payload).encode("utf-8")) <= PROVIDER_PROMPT_HARD_CAP_BYTES


def test_combat_ready_filter_preserves_required_pair_count_with_distinct_alternatives():
    request = _bind_typed_talent_disposition(
        _request_with_complete_routes(free_pair_count=1),
        "talent.fire.1",
        full_description="Action Type: Action\nCanonical Action Type: Action\nNo Cost line.",
        combat_ready=True,
    )

    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    contract = payload["response_contract"]
    pairs = [route["free_talent_pair"] for route in payload["sphere_route_modules"]]

    assert contract["expected_acquisition_counts"]["sphere_free_talent_pairs"] == 1
    assert len(pairs) >= 1
    assert all(pair["talent_id"] != "talent.fire.1" for pair in pairs)
    assert len({(pair["sphere_id"], pair["talent_id"]) for pair in pairs}) == len(pairs)
    assert len(canonical_json(payload).encode("utf-8")) <= PROVIDER_PROMPT_HARD_CAP_BYTES


def test_non_combat_ready_retains_action_declared_free_talent_presentation():
    request = _bind_typed_talent_disposition(
        _request_with_complete_routes(),
        "talent.fire.1",
        full_description="Action Type: Action\nCanonical Action Type: Action\nNo Cost line.",
        combat_ready=False,
    )

    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    pairs = [route["free_talent_pair"] for route in payload["sphere_route_modules"]]

    assert any(pair["talent_id"] == "talent.fire.1" for pair in pairs)


def test_provider_prompt_fails_before_provider_when_frozen_pair_count_exceeds_complete_routes():
    request = _request_with_complete_routes(free_pair_count=8)

    with pytest.raises(FoundryError) as raised:
        CharacterCreationExecutionService._provider_prompt({"request": request})

    error = raised.value
    assert error.code == "CG1_PROVIDER_ACQUISITION_CONTRACT_UNSATISFIABLE"
    assert error.status_code == 422
    assert error.details == {
        "expected_pair_count": 8,
        "presented_pair_count": 6,
        "request_binding": {
            "request_sha256": "a" * 64,
            "content_lock_hash": "b" * 64,
        },
    }


def test_provider_prompt_high_cardinality_routes_stay_compact_and_closed_world():
    request = _request_with_high_cardinality_complete_routes()
    prompt = CharacterCreationExecutionService._provider_prompt({"request": request})
    assert len(prompt.encode("utf-8")) <= PROVIDER_PROMPT_TARGET_BYTES
    assert len(prompt.encode("utf-8")) <= PROVIDER_PROMPT_HARD_CAP_BYTES

    payload = json.loads(prompt)
    routes = payload["sphere_route_modules"]
    contract = payload["response_contract"]
    assert len(routes) == 6
    assert contract["sphere_route_modules_ref"] == "sphere_route_modules"
    assert "sphere_route_modules" not in contract
    assert "presented_legal_ordinary_talent_ids_by_cl" not in contract
    assert len(payload["sphere_comparability_index"]["profiles"]) == len(routes)
    assert set(payload["ordinary_talent_shortlist_by_sphere"]) == {
        route["sphere_id"] for route in routes
    }
    for cl in range(1, 16):
        union = {
            route["ordinary_talent_ids_by_cl"][str(cl)]
            for route in routes
        }
        assert union
        assert all(
            choice_id not in {
                f"talent.catalog.{index:02d}.{talent_index}"
                for index in range(79)
                for talent_index in range(1, 6)
            }
            for choice_id in union
        )


def test_post_cl12_wire_growth_compacts_lossless_route_position_map():
    """The CL15-sized route map must not push an otherwise valid request over cap."""
    request = _request_with_complete_routes()
    raw_payload = creation_service._provider_payload(
        {"request": request},
        cue_limit=0,
        display_limit=0,
    )
    # Drive the same late wire-size branch as a post-CL12 replay without
    # changing any route IDs, eligible CLs, or milestone authority.  The
    # padding stands in for already-frozen descriptive/projection growth; it
    # is retained, while the duplicate route position data is compacted.
    raw_payload["wire_growth_context"] = "x" * 28_000

    raw_map = deepcopy(raw_payload["response_contract"]["ordinary_talent_position_map"])
    raw_size = len(canonical_json(raw_payload).encode("utf-8"))
    compacted = creation_service._provider_wire_compact_payload(raw_payload)
    compact_prompt = canonical_json(compacted)
    compact_size = len(compact_prompt.encode("utf-8"))
    contract = compacted["response_contract"]
    position_map = contract["ordinary_talent_position_map"]

    assert raw_size > PROVIDER_PROMPT_TARGET_BYTES
    assert compact_size <= creation_service._PROVIDER_WIRE_COMPACT_TARGET_BYTES
    assert len(_synthetic_wire_bytes(compact_prompt)) <= PROVIDER_REQUEST_HARD_CAP_BYTES
    assert contract["ordinary_talent_position_map_route_bound_ids_ref"] == (
        "sphere_route_modules[].ordinary_talent_ids_by_cl"
    )
    assert all(
        "route_bound_ids" not in row
        and row["route_bound_ids_ref"] == "sphere_route_modules[].ordinary_talent_ids_by_cl"
        for row in position_map.values()
    )
    assert raw_payload["response_contract"]["ordinary_talent_position_map"] == raw_map

    for effective_cl, raw_row in raw_map.items():
        expected = raw_row["route_bound_ids"]
        actual = {
            route["route_id"]: route["ordinary_talent_ids_by_cl"][effective_cl]
            for route in compacted["sphere_route_modules"]
        }
        assert actual == expected


def test_sphere_comparability_index_is_deterministic_and_frozen_authority_bound():
    request = _request(target_cl=3)
    first_payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))

    reordered = deepcopy(request)
    envelope = reordered["delegated_choice_envelope"]
    for slot_id in ("sphere_priorities", "advancement_skeleton"):
        rows = envelope["choices_by_slot"][slot_id]
        envelope["choices_by_slot"][slot_id] = dict(reversed(list(rows.items())))
        envelope["allowed_choice_ids_by_slot"][slot_id] = list(reversed(envelope["allowed_choice_ids_by_slot"][slot_id]))
        authorities = envelope["typed_choice_authority_by_slot"][slot_id]["stage2_authority_by_choice"]
        envelope["typed_choice_authority_by_slot"][slot_id]["stage2_authority_by_choice"] = dict(reversed(list(authorities.items())))
    second_payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": reordered}))

    first_index = first_payload["sphere_comparability_index"]
    second_index = second_payload["sphere_comparability_index"]
    assert first_index == second_index
    assert first_index["schema"] == "TianxiaFoundry.SphereComparabilityIndex.v1"
    assert first_index["version"] == 1
    assert first_index["origin"] == "frozen_delegated_choice_envelope"
    assert first_index["mechanical_authority"] is False
    assert "comparative flavor" in first_payload["response_contract"]["sphere_comparability_representation"]
    assert first_payload["response_contract"] == second_payload["response_contract"]

    allowed_spheres = set(request["delegated_choice_envelope"]["allowed_choice_ids_by_slot"]["sphere_priorities"])
    allowed_talents = set(request["delegated_choice_envelope"]["allowed_choice_ids_by_slot"]["advancement_skeleton"])
    active_talents = {
        talent_id
        for row in build_compact_choice_model(request)["ordinary_talent_slots"]
        if row["active_for_request"] is True and row["cl"] <= 3
        for talent_id in row["eligible_choice_ids"]
    }
    authorities = request["delegated_choice_envelope"]["typed_choice_authority_by_slot"]["advancement_skeleton"]["stage2_authority_by_choice"]
    assert {profile["sphere_id"] for profile in first_index["profiles"]} <= allowed_spheres
    for profile in first_index["profiles"]:
        assert len(profile["signature_talents"]) <= 3
        for signature in profile["signature_talents"]:
            assert set(signature) == {"id", "name", "cue"}
            assert signature["id"] in allowed_talents
            assert signature["id"] in active_talents
            assert authorities[signature["id"]]["owning_canonical_sphere_id"] == profile["sphere_id"]


def test_sphere_comparability_index_is_modular_and_sanitizes_profile_overrides():
    request = _request(target_cl=3)
    envelope = request["delegated_choice_envelope"]
    sphere_id = "sphere.synthetic.ember"
    sphere_row = _choice(sphere_id, category="sphere", owner=sphere_id)
    sphere_row["semantic_cue"] = "A mobile defensive control tradition with range and support."
    sphere_row["ai_comparability_profile"] = {
        "flavor_cue": "A bounded ember tradition for patient tactical planning. " * 40,
        "capability_tags": [
            "mobility", "defense", "control", "offense", "range", "area", "support", "stealth", "damage_dice",
        ],
        "preferred_signature_talent_ids": [
            "talent.synthetic.late", "talent.synthetic.cross_owner", "talent.synthetic.middle",
            {"mechanics": "must-not-leak"},
        ],
        "mechanical_rules": {"damage": "1d8", "action": "free"},
    }
    envelope["choices_by_slot"]["sphere_priorities"][sphere_id] = sphere_row
    envelope["allowed_choice_ids_by_slot"]["sphere_priorities"].append(sphere_id)
    envelope["typed_choice_authority_by_slot"]["sphere_priorities"]["stage2_authority_by_choice"][sphere_id] = {
        "authority_complete": True,
        "allowed_kinds": ["level_sphere_acquisition"],
        "allowed_channels": ["level-choice"],
        "owning_canonical_sphere_id": sphere_id,
        "minimum_cl": 1,
    }
    talent_authorities = envelope["typed_choice_authority_by_slot"]["advancement_skeleton"]["stage2_authority_by_choice"]
    for talent_id, minimum_cl, owner in (
        ("talent.synthetic.early", 1, sphere_id),
        ("talent.synthetic.middle", 2, sphere_id),
        ("talent.synthetic.late", 3, sphere_id),
        ("talent.synthetic.cross_owner", 1, "sphere.fire"),
    ):
        row = _choice(talent_id, category="talent", owner=sphere_id, minimum_cl=minimum_cl)
        row["semantic_cue"] = f"{talent_id} offers mobility defense and control."
        envelope["choices_by_slot"]["advancement_skeleton"][talent_id] = row
        talent_authorities[talent_id] = _authority(owner=owner, minimum_cl=minimum_cl)
        envelope["allowed_choice_ids_by_slot"]["advancement_skeleton"].append(talent_id)
    # This row is frozen but not currently presented/allowed; it must not
    # become planning context merely because its source record exists.
    envelope["choices_by_slot"]["sphere_priorities"]["sphere.unallowed"] = _choice(
        "sphere.unallowed", category="sphere", owner="sphere.unallowed"
    )

    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    index = payload["sphere_comparability_index"]
    profile = next(row for row in index["profiles"] if row["sphere_id"] == sphere_id)
    assert len(profile["flavor_cue"]) <= 180
    assert profile["capability_tags"] == [
        "mobility", "defense", "control", "offense", "range", "area",
    ]
    signature_ids = {row["id"] for row in profile["signature_talents"]}
    assert signature_ids == {
        "talent.synthetic.early", "talent.synthetic.middle", "talent.synthetic.late",
    }
    assert "talent.synthetic.cross_owner" not in signature_ids
    assert "mechanical_rules" not in profile
    assert "damage_dice" not in json.dumps(profile)
    assert "sphere.unallowed" not in {row["sphere_id"] for row in index["profiles"]}
    assert len(profile["signature_talents"]) <= 3
    assert len(json.dumps(index).encode("utf-8")) < 16_000


def test_sphere_comparability_index_accepts_legacy_sphere_authority_and_names_sparse_flavor():
    request = _request(target_cl=3)
    envelope = request["delegated_choice_envelope"]
    talent_authorities = envelope["typed_choice_authority_by_slot"]["advancement_skeleton"]["stage2_authority_by_choice"]
    for talent_id, authority in talent_authorities.items():
        owner = authority.pop("owning_canonical_sphere_id")
        authority["sphere_id"] = owner
        talent_row = envelope["choices_by_slot"]["advancement_skeleton"][talent_id]
        talent_row["description"] = "Prerequisite: none; Cost: 1; Action Type: passive."
    sphere_row = envelope["choices_by_slot"]["sphere_priorities"]["sphere.fire"]
    sphere_row["description"] = sphere_row["name"]

    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    profile = next(
        row for row in payload["sphere_comparability_index"]["profiles"]
        if row["sphere_id"] == "sphere.fire"
    )
    assert profile["signature_talents"]
    assert profile["flavor_cue"].startswith("Representative arts: ")
    assert all(signature["name"] in profile["flavor_cue"] for signature in profile["signature_talents"])

    # Conflicting aliases and a missing compact owner are fail-closed rather
    # than allowing a display row to manufacture a planning profile.
    talent_id = profile["signature_talents"][0]["id"]
    talent_authorities[talent_id]["owning_sphere_id"] = "sphere.water"
    rejected = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    fire_profile = next(row for row in rejected["sphere_comparability_index"]["profiles"] if row["sphere_id"] == "sphere.fire")
    assert talent_id not in {signature["id"] for signature in fire_profile["signature_talents"]}


def test_sphere_comparability_rejects_conflicting_frozen_source_owner_alias():
    request = _request()
    envelope = request["delegated_choice_envelope"]
    talent_id = "talent.fire.1"
    source_talent = envelope["choices_by_slot"]["advancement_skeleton"][talent_id]
    # The typed authority still names the correct Sphere, but a second
    # recognized alias in the frozen source row disagrees.  Planning context
    # must fail closed instead of allowing the typed alias to win.
    source_talent["sphere_id"] = "sphere.water"

    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    fire_profile = next(
        row for row in payload["sphere_comparability_index"]["profiles"]
        if row["sphere_id"] == "sphere.fire"
    )
    assert talent_id not in {signature["id"] for signature in fire_profile["signature_talents"]}


def test_provider_prompt_exposes_exact_point_buy_cost_table_and_verified_presets():
    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": _request()}))
    summary = payload["bounded_choice_summary"]["ability_scores"]

    assert summary["exact_budget"] == 27
    assert summary["cost_by_score"] == {
        "8": 0,
        "9": 1,
        "10": 2,
        "11": 3,
        "12": 4,
        "13": 5,
        "14": 7,
        "15": 9,
    }
    assert len(summary["legal_score_presets"]) == 4
    assert [15, 15, 15, 8, 8, 8] in [preset["scores"] for preset in summary["legal_score_presets"]]
    for preset in summary["legal_score_presets"]:
        assert preset["cost"] == sum(summary["cost_by_score"][str(score)] for score in preset["scores"])
        assert preset["cost"] == summary["exact_budget"]
        assert preset["permutable_across_abilities"] is True


def test_manual_ai_instructions_bind_positions_to_frozen_target_cl_not_cl20():
    request = _request(target_cl=10)
    model = build_compact_choice_model(request)
    instructions = CharacterCreationExecutionService._manual_ai_instructions(request, model).decode("utf-8")

    assert "index 19 at CL20" not in instructions
    assert "final active position is determined by the frozen request target CL" in instructions
    assert "exactly one distinct stable Talent ID" in instructions
    assert "frozen server-owned legal plan authority" in instructions
    assert "closed-world compiler-backed legal choices from the exact pinned compiler corpus" in instructions
    assert "Nonselectable IDs and response prose never grant mechanics or authority" in instructions


def test_provider_prompt_discovers_replacement_content_pack_ids_from_frozen_authority():
    request = _request(with_free_grant=True)
    replacement_ids = {
        "path.qi": "path.synthetic.lattice",
        "method.internal": "method.synthetic.resonance",
        "sphere.fire": "sphere.synthetic.ember",
        "sphere.water": "sphere.synthetic.tide",
        "talent.fire.1": "talent.synthetic.free.ember",
        "talent.fire.2": "talent.synthetic.ordinary.ember",
        "talent.fire.3": "talent.synthetic.ordinary.ember.late",
        "talent.water.1": "talent.synthetic.ordinary.tide",
        "talent.water.2": "talent.synthetic.ordinary.tide.late",
        "talent.water.3": "talent.synthetic.ordinary.tide.extra",
        "subpath.stillness": "subpath.synthetic.stillness",
        "foundation.meridian": "foundation.synthetic.channel",
        "background.scholar": "background.synthetic.wanderer",
        "insight.origin": "insight.synthetic.origin",
        "insight.meditation": "insight.synthetic.meditation",
        "item.focus": "item.synthetic.focus",
        "feature.qi": "feature.synthetic.lattice",
    }

    def replace_exact_ids(value):
        if isinstance(value, dict):
            return {
                replacement_ids.get(key, key) if isinstance(key, str) else key: replace_exact_ids(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [replace_exact_ids(item) for item in value]
        if isinstance(value, str):
            for old_id, new_id in replacement_ids.items():
                value = value.replace(old_id, new_id)
        return value

    request = replace_exact_ids(deepcopy(request))
    envelope = request["delegated_choice_envelope"]
    method_id = replacement_ids["method.internal"]
    path_id = replacement_ids["path.qi"]
    sphere_id = replacement_ids["sphere.fire"]
    free_talent_id = replacement_ids["talent.fire.1"]
    ordinary_talent_id = replacement_ids["talent.fire.2"]
    # Publish the same typed Method-to-Path relation a real pack can provide;
    # the fixture's prerequisite remains present as an independent fallback.
    envelope["path_method_authority"] = {
        "method_granted_path_ids": {method_id: [path_id]},
    }

    frozen_authorities = envelope["typed_choice_authority_by_slot"]
    talent_authorities = frozen_authorities["advancement_skeleton"]["stage2_authority_by_choice"]
    assert talent_authorities[free_talent_id]["owning_canonical_sphere_id"] == sphere_id
    assert talent_authorities[ordinary_talent_id]["owning_canonical_sphere_id"] == sphere_id
    assert talent_authorities[free_talent_id]["free_sphere_talent_eligible"] is True
    assert envelope["path_method_authority"]["method_granted_path_ids"] == {
        method_id: [path_id],
    }

    prompt = CharacterCreationExecutionService._provider_prompt({"request": request})
    payload = json.loads(prompt)
    contract = payload["response_contract"]
    template = contract["response_template"]
    template_slots = template["selection_intent"]["by_slot"]
    free_pair = {"sphere_id": sphere_id, "talent_id": free_talent_id}

    assert contract["presented_legal_method_path_pairs"] == [
        {"method_id": method_id, "path_id": path_id},
    ]
    assert template_slots["method_choice"] == []
    assert template_slots["path_choice"] == []
    assert contract["presented_legal_first_cycle_pairs"] == [free_pair]
    assert template["acquisition_intent"] == {
        "sphere_free_talent_pairs": [],
        "ordinary_talent_ids": [],
        "insight_occurrences": [],
    }
    assert contract["expected_acquisition_counts"]["sphere_free_talent_pairs"] == 1
    assert contract["expected_acquisition_counts"]["ordinary_talent_ids"] == 1
    assert {
        route["ordinary_talent_ids_by_cl"]["1"]
        for route in payload["sphere_route_modules"]
    } == {ordinary_talent_id}
    assert set(payload["ordinary_talent_shortlist_by_sphere"]) == {sphere_id}
    assert {
        row["id"] for row in payload["ordinary_talent_shortlist_by_sphere"][sphere_id]
    } == {free_talent_id, ordinary_talent_id}
    assert template_slots["sphere_priorities"] == []

    synthetic_ids = set(replacement_ids.values())
    for rows in payload["allowed_choices_by_slot"].values():
        assert {row["id"] for row in rows} <= synthetic_ids
    for rows in payload["ordinary_talent_shortlist_by_sphere"].values():
        assert {row["id"] for row in rows} <= synthetic_ids
    remaining_fixture_ids = [old_id for old_id in replacement_ids if old_id in prompt]
    remaining_context = {
        old_id: prompt[max(0, prompt.index(old_id) - 32):prompt.index(old_id) + len(old_id) + 32]
        for old_id in remaining_fixture_ids
    }
    assert not remaining_fixture_ids, remaining_context




def test_provider_planning_priorities_exclude_choices_unavailable_at_target_cl():
    request = _request(target_cl=1)
    envelope = request["delegated_choice_envelope"]
    envelope["choices_by_slot"]["insight_priorities"]["insight.advanced"] = _choice(
        "insight.advanced", category="insight", minimum_cl=8
    )
    envelope["choices_by_slot"]["insight_priorities"]["insight.route_bound"] = _choice(
        "insight.route_bound", category="insight", minimum_cl=1
    )
    envelope["choices_by_slot"]["insight_priorities"]["insight.route_bound"]["prerequisites"] = [
        {"target_id": "sphere.unselected"},
    ]
    envelope["allowed_choice_ids_by_slot"]["insight_priorities"] = [
        "insight.advanced", "insight.meditation", "insight.route_bound",
    ]

    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    presented_ids = {
        row["id"] for row in payload["allowed_choices_by_slot"]["insight_priorities"]
    }
    assert presented_ids == {"insight.meditation"}
    assert payload["response_contract"]["response_template"]["selection_intent"]["by_slot"]["insight_priorities"] == []

def test_provider_template_uses_frozen_legal_method_path_pair_instead_of_independent_first_ids():
    request = _request()
    envelope = request["delegated_choice_envelope"]
    envelope["choices_by_slot"]["path_choice"]["path.body"] = _choice(
        "path.body", category="path"
    )
    envelope["choices_by_slot"]["path_choice"]["path.qi"]["prerequisites"] = []
    envelope["choices_by_slot"]["method_choice"]["method.zzz.body"] = _choice(
        "method.zzz.body", category="method"
    )
    envelope["allowed_choice_ids_by_slot"]["path_choice"] = ["path.body", "path.qi"]
    envelope["allowed_choice_ids_by_slot"]["method_choice"] = [
        "method.internal", "method.zzz.body",
    ]
    envelope["path_method_authority"] = {
        "method_granted_path_ids": {
            "method.internal": ["path.qi"],
            "method.zzz.body": ["path.body"],
        },
    }

    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    contract = payload["response_contract"]
    assert contract["presented_legal_method_path_pairs"] == [
        {"method_id": "method.internal", "path_id": "path.qi"},
        {"method_id": "method.zzz.body", "path_id": "path.body"},
    ]
    template_slots = contract["response_template"]["selection_intent"]["by_slot"]
    assert template_slots["path_choice"] == []
    assert template_slots["method_choice"] == []
    assert any(
        "presented_legal_method_path_pairs" in instruction
        for instruction in payload["instructions"]
    )

def test_provider_ordinary_talents_are_closed_to_presented_first_cycle_sphere_route():
    request = _request(with_free_grant=True)
    # An unrelated Sphere remains in the frozen envelope and would be a valid
    # standalone catalog row, but it is not acquired by the exact presented
    # first-cycle pair.
    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    contract = payload["response_contract"]

    assert set(payload["ordinary_talent_shortlist_by_sphere"]) == {"sphere.fire"}
    assert {
        route["ordinary_talent_ids_by_cl"]["1"]
        for route in payload["sphere_route_modules"]
    } == {"talent.fire.2"}
    assert contract["response_template"]["acquisition_intent"] == {
        "sphere_free_talent_pairs": [],
        "ordinary_talent_ids": [],
        "insight_occurrences": [],
    }
    assert all(
        route["sphere_id"] == "sphere.fire"
        for route in payload["sphere_route_modules"]
    )
    assert any("closed-world legal choices" in instruction for instruction in payload["instructions"])

def test_preflight_rejects_missing_pair_and_cross_sphere_ordinary_before_materialization():
    request = _request(with_free_grant=True)
    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    plan = deepcopy(payload["response_contract"]["response_template"])
    # This focused unit fixture omits the production bounded-field contract;
    # leave that independently tested surface out of this acquisition check.
    plan["bounded_choices"] = {}
    plan["acquisition_intent"]["sphere_free_talent_pairs"] = []
    plan["acquisition_intent"]["ordinary_talent_ids"] = ["talent.water.1"]
    plan["selection_intent"]["by_slot"]["advancement_skeleton"] = ["talent.water.1"]

    try:
        CharacterCreationExecutionService._validate_preferred_bounded_fields(
            {"request": request},
            plan,
        )
    except FoundryError as exc:
        assert exc.code == "CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID"
        issues = exc.details["issues"]
        assert any(
            issue["field"] == "acquisition_intent.sphere_free_talent_pairs"
            and issue["reason"] == "COUNT_MISMATCH"
            for issue in issues
        )
        ordinary_issue = next(
            issue for issue in issues
            if issue["field"] == "acquisition_intent.ordinary_talent_ids.0"
        )
        assert ordinary_issue["reason"] == "NOT_PRESENTED_LEGAL_ORDINARY_TALENT"
        assert ordinary_issue["allowed_choice_ids"] == ["talent.fire.2"]
    else:
        raise AssertionError("Cross-Sphere ordinary Talent reached materialization preflight.")


def test_acquisition_correction_is_target_scoped_and_preserves_method_path_and_identity():
    request = _request(with_free_grant=True)
    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    prior = deepcopy(payload["response_contract"]["response_template"])
    prior["bounded_choices"] = {}
    prior["selection_intent"]["by_slot"]["method_choice"] = ["method.keep"]
    prior["selection_intent"]["by_slot"]["path_choice"] = ["path.keep"]
    prior["owner_descriptive_fields"] = {
        "concept": "Keep this concept exactly.",
        "identity": {"name": "Keep This Name"},
    }
    prior["acquisition_intent"]["sphere_free_talent_pairs"] = []
    prior["acquisition_intent"]["ordinary_talent_ids"] = ["talent.water.1"]
    prior["selection_intent"]["by_slot"]["advancement_skeleton"] = ["talent.water.1"]
    prior_text = canonical_json(prior)
    try:
        CharacterCreationExecutionService._validate_preferred_bounded_fields(
            {"request": request}, prior
        )
    except FoundryError as exc:
        diagnostic = {"code": exc.code, "message": exc.message, "details": exc.details}
    else:
        raise AssertionError("Expected the acquisition preflight diagnostic.")

    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run={"request": request},
        prior_response=prior_text,
    )
    assert target is not None
    assert target["target_kind"] == "acquisition_contract"
    assert target["option_ids"]
    selected_option_id = target["option_ids"][0]
    merged_text, evidence = CharacterCreationExecutionService._merge_target_scoped_correction_response(
        prior_text,
        canonical_json({"option_id": selected_option_id}),
        diagnostic,
        run={"request": request},
        repair_target=target,
    )
    merged = json.loads(merged_text)
    assert merged["acquisition_intent"]["sphere_free_talent_pairs"] == [
        {"sphere_id": "sphere.fire", "talent_id": "talent.fire.1"}
    ]
    assert merged["acquisition_intent"]["ordinary_talent_ids"] == ["talent.fire.2"]
    assert merged["selection_intent"]["by_slot"]["advancement_skeleton"] == ["talent.fire.2"]
    assert merged["selection_intent"]["by_slot"]["method_choice"] == ["method.keep"]
    assert merged["selection_intent"]["by_slot"]["path_choice"] == ["path.keep"]
    assert merged["owner_descriptive_fields"] == prior["owner_descriptive_fields"]
    assert evidence["target_kind"] == "acquisition_contract"
    assert evidence["target_scoped_merge"] is True


def test_provider_response_template_uses_distinct_ordinary_ids_per_active_cl():
    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": _request(target_cl=2)}))
    template = payload["response_contract"]["response_template"]
    ordinary_ids = template["acquisition_intent"]["ordinary_talent_ids"]
    skeleton_ids = template["selection_intent"]["by_slot"]["advancement_skeleton"]
    assert ordinary_ids == []
    assert skeleton_ids == []


def test_provider_contract_exposes_mandatory_acquisition_counts_and_legal_first_cycle_pair():
    request = _request(with_free_grant=True)
    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    contract = payload["response_contract"]
    assert contract["acquisition_intent_required_keys"] == [
        "insight_occurrences",
        "ordinary_talent_ids",
        "sphere_free_talent_pairs",
    ]
    assert contract["expected_acquisition_counts"] == {
        "insight_occurrences": 1,
        "ordinary_talent_ids": 1,
        "sphere_free_talent_pairs": 1,
    }
    pair = {"sphere_id": "sphere.fire", "talent_id": "talent.fire.1"}
    assert contract["presented_legal_first_cycle_pairs"] == [pair]
    template = contract["response_template"]
    assert set(template["acquisition_intent"]) == set(contract["acquisition_intent_required_keys"])
    assert template["acquisition_intent"]["sphere_free_talent_pairs"] == []
    assert template["acquisition_intent"]["ordinary_talent_ids"] == []
    assert "never a source for sphere_free_talent_pairs" in contract["ordinary_talent_source"]
    assert "Copy each whole {sphere_id, talent_id} object exactly" in contract["first_cycle_pair_source"]
    assert any(
        "copy whole pair objects exactly" in instruction
        and "Never substitute a background Sphere" in instruction
        for instruction in payload["instructions"]
    )
    assert any(
        "no other pair is legal for this frozen route" in instruction
        for instruction in payload["instructions"]
    )
    assert not any(
        instruction.startswith("Use only IDs presented in allowed_choices_by_slot or ordinary_talent_shortlist_by_sphere")
        for instruction in payload["instructions"]
    )


def test_provider_pair_count_uses_semantic_frozen_lock_not_unrelated_zero_lock():
    request = _request(with_free_grant=True)
    # Make a different legal pair the committed plan.  The plan establishes
    # capacity/count, but it is not an owner-forced provider selection.
    authorities = request["delegated_choice_envelope"]["typed_choice_authority_by_slot"]["advancement_skeleton"]["stage2_authority_by_choice"]
    authorities["talent.fire.2"].update({
        "allowed_kinds": ["level_talent_acquisition", "ai_bootstrap_talent_acquisition"],
        "free_sphere_talent_eligible": True,
    })
    locked_pair = {"sphere_id": "sphere.fire", "talent_id": "talent.fire.2"}
    presented_example = {"sphere_id": "sphere.fire", "talent_id": "talent.fire.1"}
    accounting_zero = {
        "free_sphere_talent_grant_count": 0,
        "free_sphere_talent_grants": [],
    }
    accounting_first_cycle = {
        "free_sphere_talent_grant_count": 1,
        "free_sphere_talent_grants": [locked_pair],
    }
    # The project/snapshot can carry older compatibility accounting before
    # the committed first-cycle catalog plan.  Resolve by semantic lock field,
    # never by the typed_locks list position.
    request["stage1_prompt"]["envelope"]["user_locks"] = [
        {"field": "character_sheet.generation_route", "value": "ai_bootstrap"},
        {
            "field": "character_sheet.canonical_grant_plan",
            "value": {"grant_accounting": deepcopy(accounting_zero)},
        },
    ]
    request["typed_choice_snapshot"] = {
        "schema": "TianxiaFoundry.TypedProjectChoiceSnapshot.v1",
        "typed_locks": [
            {
                "field": "character_sheet.canonical_grant_plan",
                "value": {"grant_accounting": deepcopy(accounting_zero)},
            },
            {
                "field": "character_creation.committed_catalog_choice_plan",
                "value": {"grant_accounting": deepcopy(accounting_first_cycle)},
            },
        ],
    }

    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    contract = payload["response_contract"]
    assert contract["expected_acquisition_counts"]["sphere_free_talent_pairs"] == 1
    assert contract["presented_legal_first_cycle_pairs"] == [
        {"sphere_id": "sphere.fire", "talent_id": "talent.fire.1"},
        {"sphere_id": "sphere.fire", "talent_id": "talent.fire.2"},
    ]
    assert contract["response_template"]["acquisition_intent"]["sphere_free_talent_pairs"] == []
    assert contract["expected_acquisition_counts"]["ordinary_talent_ids"] == 1


def test_provider_zero_pair_count_suppresses_presented_and_template_pairs():
    request = _request(with_free_grant=True)
    pair = {"sphere_id": "sphere.fire", "talent_id": "talent.fire.1"}
    request["stage1_prompt"]["envelope"]["user_locks"] = [
        {"field": "character_sheet.generation_route", "value": "ai_bootstrap"},
        {
            "field": "character_sheet.canonical_grant_plan",
            "value": {
                "grant_accounting": {
                    "free_sphere_talent_grant_count": 0,
                    # A stale row must not contradict the explicit count.
                    "free_sphere_talent_grants": [pair],
                },
            },
        },
    ]
    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    contract = payload["response_contract"]
    assert contract["expected_acquisition_counts"]["sphere_free_talent_pairs"] == 0
    assert contract["presented_legal_first_cycle_pairs"] == []
    assert contract["response_template"]["acquisition_intent"]["sphere_free_talent_pairs"] == []


def test_provider_empty_ai_bootstrap_accounting_derives_usable_pairs_from_frozen_authority():
    request = _request_with_complete_routes()
    envelope = request["delegated_choice_envelope"]
    sphere_authorities = envelope["typed_choice_authority_by_slot"]["sphere_priorities"]["stage2_authority_by_choice"]
    talent_authorities = envelope["typed_choice_authority_by_slot"]["advancement_skeleton"]["stage2_authority_by_choice"]
    sphere_authorities["sphere.water"].update({
        "allowed_kinds": ["level_sphere_acquisition", "ai_bootstrap_sphere_acquisition"],
        "allowed_channels": ["level-choice", "ai-bootstrap-free-cl1-sphere"],
    })
    talent_authorities["talent.water.1"].update({
        "allowed_kinds": ["level_talent_acquisition", "ai_bootstrap_talent_acquisition"],
        "free_sphere_talent_eligible": True,
    })
    request["stage1_prompt"]["envelope"]["user_locks"] = [
        {"field": "character_sheet.generation_route", "value": "ai_bootstrap"},
        {
            "field": "character_sheet.canonical_grant_plan_origin",
            "value": "compatibility_projection",
        },
        {
            "field": "character_sheet.canonical_grant_plan",
            "value": {
                "grant_accounting": {
                    "free_sphere_talent_grant_count": 0,
                    "free_sphere_talent_grants": [],
                },
            },
        },
    ]

    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    contract = payload["response_contract"]
    assert contract["expected_acquisition_counts"]["sphere_free_talent_pairs"] == 1
    routes = payload["sphere_route_modules"]
    assert routes
    assert any(
        set(route["ordinary_talent_ids_by_cl"]) == {str(cl) for cl in range(1, 16)}
        and len(set(route["ordinary_talent_ids_by_cl"].values())) == 15
        for route in routes
    )
    assert contract["response_template"]["acquisition_intent"] == {
        "sphere_free_talent_pairs": [],
        "ordinary_talent_ids": [],
        "insight_occurrences": [],
    }
    assert contract["expected_acquisition_counts"]["ordinary_talent_ids"] == 15
    assert contract["sphere_route_modules_ref"] == "sphere_route_modules"


def test_provider_deliberate_empty_ai_bootstrap_zero_remains_authoritative():
    request = _request(target_cl=2, with_free_grant=True)
    request["stage1_prompt"]["envelope"]["user_locks"] = [
        {"field": "character_sheet.generation_route", "value": "ai_bootstrap"},
        {
            "field": "character_sheet.canonical_grant_plan_origin",
            "value": "explicit_submission",
        },
        {
            "field": "character_sheet.canonical_grant_plan",
            "value": {
                "grant_accounting": {
                    "free_sphere_talent_grant_count": 0,
                    "free_sphere_talent_grants": [],
                },
            },
        },
    ]

    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    contract = payload["response_contract"]
    assert contract["expected_acquisition_counts"]["sphere_free_talent_pairs"] == 0
    assert contract["presented_legal_first_cycle_pairs"] == []
    assert contract["response_template"]["acquisition_intent"]["sphere_free_talent_pairs"] == []


def test_provider_exposes_method_allocation_rules_for_path_progression():
    request = _request(target_cl=2)
    request["delegated_choice_envelope"]["path_method_authority"] = {
        "method_granted_path_ids": {
            "method.internal": ["path.qi"],
        },
        "method_allocation_by_id": {
            "method.internal": {
                "schema": "TianxiaFoundry.MethodAllocationProjection.v1",
                "name": "Internal Method",
                "allocation_rule": "OWNER_DISTRIBUTED",
                "granted_path_ids": ["path.qi"],
                "minimum_commitments": ["At least 1 AP to each Path per Realm."],
                "realm_boundaries": [5, 10, 15, 20],
                "ap_route_summary": "Distribute attainment across every granted Path.",
            },
        },
    }

    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    contract = payload["response_contract"]
    assert contract["presented_method_allocation_by_id"]["method.internal"] == {
        "schema": "TianxiaFoundry.MethodAllocationProjection.v1",
        "name": "Internal Method",
        "allocation_rule": "OWNER_DISTRIBUTED",
        "granted_path_ids": ["path.qi"],
        "minimum_commitments": ["At least 1 AP to each Path per Realm."],
        "realm_boundaries": [5, 10, 15, 20],
        "ap_route_summary": "Distribute attainment across every granted Path.",
    }
    assert any(
        "presented_method_allocation_by_id" in instruction
        and "path_progression_by_cl" in instruction
        for instruction in payload["instructions"]
    )


def test_provider_free_pair_requires_route_kind_on_presented_sphere_authority():
    request = _request(with_free_grant=True)
    envelope = request["delegated_choice_envelope"]
    sphere_authorities = envelope["typed_choice_authority_by_slot"]["sphere_priorities"]["stage2_authority_by_choice"]
    talent_authorities = envelope["typed_choice_authority_by_slot"]["advancement_skeleton"]["stage2_authority_by_choice"]
    sphere_authorities["sphere.fire"]["allowed_kinds"] = ["background_sphere_acquisition"]
    sphere_authorities["sphere.water"].update({
        "allowed_kinds": ["ai_bootstrap_sphere_acquisition"],
        "allowed_channels": ["ai-bootstrap-free-cl1-sphere"],
    })
    talent_authorities["talent.water.1"].update({
        "allowed_kinds": ["level_talent_acquisition", "ai_bootstrap_talent_acquisition"],
        "free_sphere_talent_eligible": True,
    })
    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    pairs = payload["response_contract"]["presented_legal_first_cycle_pairs"]
    assert {tuple(sorted(pair.items())) for pair in pairs} == {
        tuple(sorted({"sphere_id": "sphere.water", "talent_id": "talent.water.1"}.items()))
    }
    assert {pair["sphere_id"] for pair in pairs} != {"sphere.fire"}


def test_provider_prompt_scales_with_two_sparse_candidates_per_sphere():
    request = _request()
    envelope = request["delegated_choice_envelope"]
    ordinary = envelope["choices_by_slot"]["advancement_skeleton"]
    authorities = envelope["typed_choice_authority_by_slot"]["advancement_skeleton"]["stage2_authority_by_choice"]
    for sphere_index in range(85):
        owner = f"sphere.scale.{sphere_index:02d}"
        for talent_index in range(5):
            choice_id = f"talent.scale.{sphere_index:02d}.{talent_index}"
            ordinary[choice_id] = _choice(choice_id, category="talent", owner=owner)
            authorities[choice_id] = _authority(owner=owner)
    envelope["allowed_choice_ids_by_slot"]["advancement_skeleton"] = sorted(ordinary)
    insight_rows = {}
    for insight_index in range(400):
        choice_id = f"insight.scale.{insight_index:04d}"
        insight_rows[choice_id] = _choice(choice_id, category="insight")
    envelope["choices_by_slot"]["origin_insight_choice"] = insight_rows
    envelope["allowed_choice_ids_by_slot"]["origin_insight_choice"] = sorted(insight_rows)

    prompt = CharacterCreationExecutionService._provider_prompt({"request": request})
    assert len(prompt.encode("utf-8")) <= PROVIDER_PROMPT_TARGET_BYTES
    payload = json.loads(prompt)
    shortlist = payload["ordinary_talent_shortlist_by_sphere"]
    assert len(shortlist) == 87  # 85 synthetic spheres plus the two fixture spheres.
    assert all(len(rows) <= 2 for rows in shortlist.values())
    assert len(payload["allowed_choices_by_slot"]["sphere_priorities"]) == 2
    assert len(payload["allowed_choices_by_slot"]["origin_insight_choice"]) == 12
    for rows in payload["allowed_choices_by_slot"].values():
        for row in rows:
            assert all(value is not None and value != [] and value != {} and value != "" for value in row.values())
    assert payload["choice_row_contract"]["ordinary_shortlist_per_sphere"] == 2


def test_provider_prompt_scale_legacy_sphere_authority_keeps_names_and_signatures():
    request = _request(target_cl=3)
    envelope = request["delegated_choice_envelope"]
    spheres = envelope["choices_by_slot"]["sphere_priorities"]
    sphere_authorities = envelope["typed_choice_authority_by_slot"]["sphere_priorities"]["stage2_authority_by_choice"]
    ordinary = envelope["choices_by_slot"]["advancement_skeleton"]
    talent_authorities = envelope["typed_choice_authority_by_slot"]["advancement_skeleton"]["stage2_authority_by_choice"]

    for sphere_index in range(85):
        sphere_id = f"sphere.legacy.{sphere_index:02d}"
        sphere_row = _choice(sphere_id, category="sphere", owner=sphere_id)
        sphere_row["name"] = f"Legacy Sphere {sphere_index:02d}"
        sphere_row["description"] = sphere_row["name"]
        spheres[sphere_id] = sphere_row
        sphere_authorities[sphere_id] = {
            "authority_complete": True,
            "allowed_kinds": ["level_sphere_acquisition"],
            "allowed_channels": ["level-choice"],
            "sphere_id": sphere_id,
            "minimum_cl": 1,
        }
        for talent_index in range(2):
            talent_id = f"talent.legacy.{sphere_index:02d}.{talent_index}"
            talent_row = _choice(talent_id, category="talent", owner=sphere_id)
            talent_row["name"] = f"Legacy Art {sphere_index:02d}-{talent_index}"
            talent_row["description"] = "Prerequisite: none; Cost: 1; Action Type: passive."
            ordinary[talent_id] = talent_row
            talent_authorities[talent_id] = {
                "authority_complete": True,
                "allowed_kinds": ["level_talent_acquisition"],
                "allowed_channels": ["level-choice"],
                "sphere_id": sphere_id,
                "minimum_cl": 1,
            }
    envelope["allowed_choice_ids_by_slot"]["sphere_priorities"] = sorted(spheres)
    envelope["allowed_choice_ids_by_slot"]["advancement_skeleton"] = sorted(ordinary)

    prompt = CharacterCreationExecutionService._provider_prompt({"request": request})
    selected_size = len(prompt.encode("utf-8"))
    assert selected_size <= PROVIDER_PROMPT_HARD_CAP_BYTES
    assert selected_size > PROVIDER_PROMPT_TARGET_BYTES
    payload = json.loads(prompt)
    profiles = payload["sphere_comparability_index"]["profiles"]
    assert len(profiles) >= 85
    for profile in profiles:
        assert profile["name"]
        assert profile["signature_talents"]
        for signature in profile["signature_talents"]:
            assert signature["id"]
            assert signature["name"]
            if "cue" in signature:
                assert signature["cue"]
        if "flavor_cue" in profile:
            assert profile["flavor_cue"]


def test_provider_due_level_requires_a_presented_path_owned_subpath():
    request = _request(target_cl=3)
    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    contract = payload["response_contract"]
    template_by_slot = contract["response_template"]["selection_intent"]["by_slot"]
    assert contract["subpath_choice_required"] is True
    assert contract["subpath_choice_minimum"] == 1
    assert template_by_slot["subpath_choice"] == []
    subpath_row = next(
        row for row in payload["allowed_choices_by_slot"]["subpath_choice"]
        if row["id"] == "subpath.stillness"
    )
    assert subpath_row["owner"] == "path.qi"
    assert "frozen Stage 1 slot requires one" in contract["subpath_choice_representation"]


def test_provider_prompt_keeps_degrading_until_target_size(monkeypatch):
    calls = []
    sizes = {
        180: 70_000,
        120: 60_000,
        80: 55_000,
        48: 52_000,
        32: 50_000,
        24: 49_000,
        16: 48_500,
        8: 48_100,
        6: 47_688,
        0: 64_572,
    }

    def fake_payload(_run, *, cue_limit, display_limit):
        calls.append((cue_limit, display_limit))
        return {"cue_limit": cue_limit}

    def fake_canonical_json(payload):
        return "x" * sizes[payload["cue_limit"]]

    monkeypatch.setattr(creation_service, "_provider_payload", fake_payload)
    monkeypatch.setattr(creation_service, "canonical_json", fake_canonical_json)
    text = CharacterCreationExecutionService._provider_prompt({"request": {}})
    assert len(text.encode("utf-8")) == 47_688
    assert calls == [
        (180, 180),
        (120, 180),
        (80, 180),
        (48, 180),
        (32, 180),
        (24, 180),
        (16, 180),
        (8, 180),
        (6, 180),
    ]


def test_provider_prompt_uses_smallest_hard_fallback_when_target_unreachable(monkeypatch):
    calls = []
    sizes = {
        180: 65_000,
        120: 64_900,
        80: 64_800,
        48: 64_700,
        32: 64_600,
        24: 64_500,
        16: 64_400,
        8: 64_300,
        6: 64_200,
        0: 64_025,
    }

    def fake_payload(_run, *, cue_limit, display_limit):
        calls.append((cue_limit, display_limit))
        return {"cue_limit": cue_limit}

    def fake_canonical_json(payload):
        return "x" * sizes[payload["cue_limit"]]

    monkeypatch.setattr(creation_service, "_provider_payload", fake_payload)
    monkeypatch.setattr(creation_service, "canonical_json", fake_canonical_json)
    text = CharacterCreationExecutionService._provider_prompt({"request": {}})
    assert len(text.encode("utf-8")) == 64_025
    assert calls == [
        (180, 180),
        (120, 180),
        (80, 180),
        (48, 180),
        (32, 180),
        (24, 180),
        (16, 180),
        (8, 180),
        (6, 180),
        (0, 180),
        (0, 160),
        (0, 128),
        (0, 96),
        (0, 72),
        (0, 64),
        (0, 48),
        (0, 32),
        (0, 24),
        (0, 0),
    ]


def test_provider_payload_caps_local_and_cloud_tokens():
    base = {"model": "model", "max_output_tokens": 16384, "thinking_mode": "disabled"}
    local = AIProviderService._request_payload("prompt", {**base, "provider_id": "local"})
    cloud = AIProviderService._request_payload("prompt", {**base, "provider_id": "custom"})
    assert local["max_tokens"] == 6144
    assert local["chat_template_kwargs"] == {"enable_thinking": False}
    assert cloud["max_tokens"] == 8192
    assert "chat_template_kwargs" not in cloud


def test_character_timing_receipt_is_numeric_and_allowlisted():
    receipt = creation_service._timing_receipt(
        phases_ms={
            "factory_compile_1": 12.5,
            "factory_prompt_construction": True,
            "secret": 99,
        },
        provider_reported={
            "prompt_ms": 4.25,
            "predicted_n": 3,
            "prompt": "do-not-copy",
            "negative_ms": -1,
        },
    )
    assert receipt == {
        "schema": "TianxiaFoundry.CharacterCreationTimingReceipt.v1",
        "phases_ms": {"factory_compile_1": 12.5},
        "provider_reported": {"predicted_n": 3, "prompt_ms": 4.25},
    }


def test_compile_timing_subphases_are_private_and_identity_neutral():
    service = object.__new__(CharacterCreationExecutionService)
    service._plan_with_accepted_final_target = lambda _run, value, _accepted: deepcopy(value)
    # _compile_twice resolves the approved candidate GM authority first
    # (80fee3e0); a run with no approved candidate capsule resolves to None.
    service.candidate_gm_authoring = SimpleNamespace(
        candidate_compilation_authority=lambda _run, **_kwargs: None,
    )

    def fake_compile_once(_run, _plan, _index, **_kwargs):
        return {
            "schema": "TianxiaFoundry.CompiledCharacterCandidate.v3",
            "candidate_identity": "candidate-id",
            "identities": {"ledger": "ledger-id"},
            "artifacts": {"ledger": {"record": "same"}},
            "_timings": creation_service._compile_timing_receipt({
                "snapshot_copy_hash": 3,
                "scratch_db_migrate_service_creation": 4,
                "unallowlisted": 99,
            }),
        }

    service._compile_once = fake_compile_once
    result = service._compile_twice(
        {
            "created_at": "2026-08-28T00:00:00Z",
            "request": {"request_sha256": "a" * 64},
        },
        {"target_cl": 1},
    )

    phases = result["_timings"]["phases_ms"]
    assert phases["factory_compile_1"] >= 0
    assert phases["factory_compile_2"] >= 0
    assert phases["factory_compile_1.snapshot_copy_hash"] == 3
    assert phases["factory_compile_2.scratch_db_migrate_service_creation"] == 4
    assert "factory_compile_1.unallowlisted" not in phases
    assert result["candidate_identity"] == "candidate-id"
    assert result["identities"] == {"ledger": "ledger-id"}
    public_candidate = deepcopy(result)
    public_candidate.pop("_timings")
    assert public_candidate["candidate_identity"] == "candidate-id"
    assert public_candidate["identities"] == {"ledger": "ledger-id"}


def _background_linkage_compaction_fixture() -> tuple[dict[str, object], dict[str, list[dict[str, object]]]]:
    payload = _route_compaction_fixture()
    linkage = {
        "background.scholar": [{
            "package_index": 0,
            "background_sphere_choice_id": "sphere.fire",
            "background_talent_choice_id": "talent.fire.1",
            "sphere_record_id": "sphere.fire",
            "talent_record_id": "talent.fire.1",
            "source": {
                "path": "authority/background-scholar.json",
                "source_hash": "b" * 64,
            },
            "eligibility": {"minimum_cl": 1, "allowed_channels": ["background"]},
        }],
    }
    payload["bounded_choice_summary"] = {
        "background_package_linkage": deepcopy(linkage),
    }
    payload["background_package_linkage"] = deepcopy(linkage)
    return payload, linkage


def test_wire_compaction_deduplicates_only_identical_background_linkage() -> None:
    payload, linkage = _background_linkage_compaction_fixture()
    original = deepcopy(payload)

    compacted = creation_service._provider_wire_compact_payload(payload)
    repeated = creation_service._provider_wire_compact_payload(deepcopy(payload))

    assert payload == original
    assert compacted == repeated
    assert compacted["background_package_linkage"] == linkage
    summary = compacted["bounded_choice_summary"]
    assert "background_package_linkage" not in summary
    assert summary["background_package_linkage_ref"] == "background_package_linkage"
    assert any(
        "background_package_linkage_ref" in instruction
        and "top-level background_package_linkage" in instruction
        for instruction in compacted["instructions"]
    )
    # The retained table reconstructs the exact nested authority projection.
    assert compacted["background_package_linkage"] == linkage


def test_wire_compaction_preserves_divergent_or_malformed_background_linkage() -> None:
    divergent, linkage = _background_linkage_compaction_fixture()
    divergent_nested = deepcopy(linkage)
    divergent_nested["background.scholar"][0]["talent_record_id"] = "talent.fire.2"
    divergent["bounded_choice_summary"]["background_package_linkage"] = divergent_nested
    divergent_result = creation_service._provider_wire_compact_payload(divergent)
    assert divergent_result["background_package_linkage"] == linkage
    assert divergent_result["bounded_choice_summary"]["background_package_linkage"] == divergent_nested
    assert "background_package_linkage_ref" not in divergent_result["bounded_choice_summary"]

    malformed, _ = _background_linkage_compaction_fixture()
    malformed["bounded_choice_summary"]["background_package_linkage"] = ["not a linkage table"]
    malformed_result = creation_service._provider_wire_compact_payload(malformed)
    assert malformed_result["background_package_linkage"] == linkage
    assert malformed_result["bounded_choice_summary"]["background_package_linkage"] == [
        "not a linkage table"
    ]
    assert "background_package_linkage_ref" not in malformed_result["bounded_choice_summary"]
