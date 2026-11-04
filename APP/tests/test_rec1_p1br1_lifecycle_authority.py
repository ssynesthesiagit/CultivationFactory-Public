from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core import FoundryError
from character_creation.delegated_choice_authority import _canonical_stage2_kind
from gm2_contract.adapter import _automatic_component_projection, _insight_projection
from sphere_component_authority import (
    attach_sphere_automatic_component_receipt,
    build_sphere_automatic_component_authority,
)
from stage2.insight_authority import compile_insight_stage2_authority


ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "catalog_authority" / "cat3" / "generated" / "catalog_authority.v1.json"


def _catalog() -> dict:
    return json.loads(GENERATED.read_text(encoding="utf-8"))


def test_all_sphere_packets_have_exact_non_consuming_authority() -> None:
    source = _catalog()
    packets = []
    for sphere in source["spheres"]:
        packet = build_sphere_automatic_component_authority(
            sphere["canonical_sphere_id"],
            sphere["resolved_automatic_base_abilities"],
            source_identity={"source_record_commitment_sha256": sphere["record_commitment_sha256"]},
        )
        packets.append(packet)
        for component in packet["components"]:
            assert component["automatic_grant"] is True
            assert component["owner_removable"] is False
            assert component["counts_as_talent_choice"] is False
            assert component["counts_as_advancement_talent"] is False
            assert component["counts_as_training_talent"] is False
    assert len(packets) == 85
    assert sum(len(packet["components"]) for packet in packets) == 291
    by_parent = {packet["parent_sphere_id"]: packet for packet in packets}
    assert len(by_parent["tianxia.sphere.air"]["components"]) == 3
    assert len(by_parent["tianxia.sphere.retribution"]["components"]) == 2


def test_insight_authority_and_legacy_mapper_are_canonical() -> None:
    source = _catalog()
    raw = next(row for row in source["insights"] if row["record_id"] == "insight.legacy-qi-efficiency")
    authority = compile_insight_stage2_authority(raw, raw["record_id"])
    assert authority["authority_complete"] is True
    assert authority["allowed_kinds"] == ["cultivation_insight_acquisition"]
    assert authority["allowed_channels"] == ["cultivation-insight-selection"]
    assert authority["minimum_cl"] == 4
    assert authority["ability_change"]["allowed_abilities"] == ["DEX", "CON", "INT", "CHA"]
    assert authority["typed_prerequisites"]
    assert authority["repeatability"]["maximum"] == 1
    assert _canonical_stage2_kind("insight_acquisition") == "cultivation_insight_acquisition"


def test_sphere_receipt_is_idempotent_and_conflict_closed() -> None:
    sphere = next(row for row in _catalog()["spheres"] if row["canonical_sphere_id"] == "tianxia.sphere.air")
    packet = build_sphere_automatic_component_authority(
        sphere["canonical_sphere_id"], sphere["resolved_automatic_base_abilities"]
    )
    record = {
        "record_id": sphere["canonical_sphere_id"],
        "record_hash": sphere["record_commitment_sha256"],
        "automatic_component_authority": packet,
    }
    event = {
        "event_id": "event.rec1.p1br1.air",
        "advancement": {"target_cl": 1},
        "legal_channel": "ai-bootstrap-free-cl1-sphere",
        "content_binding": {"record_hash": sphere["record_commitment_sha256"]},
    }
    state: dict = {}
    attach_sphere_automatic_component_receipt(state, record, event)
    attach_sphere_automatic_component_receipt(state, record, event)
    assert len(state["automatic_sphere_component_receipts"]) == 1
    assert len(state["automatic_sphere_components"]) == 3

    conflicting = json.loads(json.dumps(record))
    conflicting["automatic_component_authority"]["components"][0]["player_rules_text"] += " altered"
    with pytest.raises(FoundryError) as caught:
        attach_sphere_automatic_component_receipt(state, conflicting, event)
    assert caught.value.code == "SPHERE_AUTOMATIC_COMPONENT_PACKET_HASH_INVALID"


def test_gm2_projection_preserves_sphere_components_and_insight_occurrences() -> None:
    source = _catalog()
    sphere_rows = []
    for sphere in source["spheres"]:
        if sphere["canonical_sphere_id"] in {"tianxia.sphere.air", "tianxia.sphere.fire"}:
            packet = build_sphere_automatic_component_authority(
                sphere["canonical_sphere_id"], sphere["resolved_automatic_base_abilities"]
            )
            sphere_rows.append({"stable_id": sphere["canonical_sphere_id"], "automatic_component_authority": packet})
    occurrences = [
        {"record_id": "insight.legacy-qi-efficiency", "repeat_index": 1},
        {"record_id": "insight.expanded-dantian", "repeat_index": 1},
    ]
    model = {
        "spheres_talents": {"spheres": sphere_rows},
        "paths_subpaths_insights": {
            "cultivation_insight_record_ids": [row["record_id"] for row in occurrences],
            "cultivation_insight_occurrences": occurrences,
        },
    }
    packets, components = _automatic_component_projection(model, sphere_rows)
    insights, projected_occurrences = _insight_projection(model, "package", "model", "model-hash")
    assert len(packets) == 2
    assert len(components) == 5
    assert len(insights) == 2
    assert projected_occurrences == occurrences
