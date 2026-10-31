from __future__ import annotations

import json
import hashlib

# SHA-256 of the CL3 Qi subpath selection and CL4 ASI schedule excerpts.
QI_SUBPATH_CL3_SHA256 = "147c40568e8a323912a2a1e12089e946df1c1b0fdf420d246f0695f6b0bfa7e0"
QI_ASI_CL4_SHA256 = "f924a403515bd8ecfbd3d35a1c3daa1d93397de14f9e7cf211c470c983b248c2"
import os
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import pytest

from app.core import Database, FoundryError, Settings
import factory_authoring.final_character_materializer as materializer
from factory_authoring.starting_kits import printed_background_items
from factory_authoring.final_character_materializer import (
    FinalCharacterReviewAuthority,
    FinalCharacterReviewIssuer,
    FinalCharacterMaterializer,
)
from security.approval_challenges import ApprovalChallengeService
from security.integrity import create_test_integrity_service
from security.local_identity import DeterministicTestPrincipalProvider


def _optional_fixture(env_name: str) -> Path:
    value = os.environ.get(env_name)
    if value and value.strip():
        return Path(value).expanduser()
    return Path("__missing_final_character_fixture__") / env_name.lower()


SOURCE = _optional_fixture("CULTIVATION_FACTORY_FINAL_SOURCE_FIXTURE")
ORIGIN_INSIGHT_SOURCE = _optional_fixture("CULTIVATION_FACTORY_FINAL_ORIGIN_INSIGHT_FIXTURE")
COMPOSITE = _optional_fixture("CULTIVATION_FACTORY_FINAL_COMPOSITE_FIXTURE")
COMPILER = materializer.FINAL_CHARACTER_DEFAULT_COMPILER
CORPUS = materializer.FINAL_CHARACTER_DEFAULT_CORPUS


_REQUIRES_ACCEPTED_FIXTURE = pytest.mark.skipif(
    not all(path.exists() for path in (SOURCE, COMPOSITE, COMPILER, CORPUS)),
    reason="The immutable accepted overlay fixture is not present on this host",
)
_REQUIRES_ORIGIN_INSIGHT_FIXTURE = pytest.mark.skipif(
    not ORIGIN_INSIGHT_SOURCE.exists(),
    reason="The immutable Origin Insight fixture is not present on this host",
)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _assert_only_safe_empty_residue(root: Path) -> None:
    """Bounded cleanup may retain empty owned names, never bytes or links."""

    assert root.is_dir()
    for path in root.rglob("*"):
        assert not path.is_symlink(), path
        if path.is_file():
            assert path.read_bytes() == b"", path


VENDOR_ACCEPTANCE_FIXTURE = COMPILER.parent.parent / "08_FIXTURES/GOOD_CL13_Immortal_Art"
_REQUIRES_VENDOR_FIXTURE = pytest.mark.skipif(
    not all(path.exists() for path in (COMPILER, CORPUS, VENDOR_ACCEPTANCE_FIXTURE)),
    reason="The immutable compiler acceptance fixture is not present on this host",
)


@_REQUIRES_VENDOR_FIXTURE
def test_real_pinned_compiler_accepts_vendor_fixture_without_test_hook(tmp_path: Path) -> None:
    """The exact compiler subprocess, not a test callable, proves a valid fixture."""

    workspace = tmp_path / "vendor-fixture"
    materializer._copy_tree_no_symlinks(VENDOR_ACCEPTANCE_FIXTURE, workspace)
    result = materializer._run_pinned_compiler(COMPILER, CORPUS, workspace)
    assert result["returncode"] == 0
    assert result["execution_mode"] == "pinned_subprocess"
    assert (workspace / materializer.FINAL_CHARACTER_COMPILER_OUTPUT_DIRNAME / "Complete_Action_Surface.json").is_file()


@_REQUIRES_VENDOR_FIXTURE
def test_real_pinned_compiler_inherits_held_workspace_descriptor(tmp_path: Path) -> None:
    """A held /proc/self/fd workspace remains readable in the compiler child."""

    workspace = tmp_path / "held-vendor-fixture"
    materializer._copy_tree_no_symlinks(VENDOR_ACCEPTANCE_FIXTURE, workspace)
    descriptor = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    held_workspace = materializer._BoundDirectoryPath(f"/proc/self/fd/{descriptor}")
    try:
        result = materializer._run_pinned_compiler(COMPILER, CORPUS, held_workspace)
        assert result["returncode"] == 0
        assert result["execution_mode"] == "pinned_subprocess"
        assert (held_workspace / materializer.FINAL_CHARACTER_COMPILER_OUTPUT_DIRNAME / "Complete_Action_Surface.json").is_file()
    finally:
        os.close(descriptor)


def _minimal_packet_bridge_workspace(tmp_path: Path, packet_index: int = 1) -> tuple[Path, bytes, str]:
    workspace = tmp_path / "workspace"
    (workspace / "Build").mkdir(parents=True)
    (workspace / "Command_2").mkdir()
    (workspace / "Command_4").mkdir()
    raw = (SOURCE / "Command_2/Rules_Selection_Packets.json").read_bytes()
    registry = json.loads(raw)
    packet_id = registry["packets"][packet_index]["packet_id"]
    (workspace / "Command_2/Rules_Selection_Packets.json").write_bytes(raw)
    for relative in ("Build/Character_Master_Ledger.json", "Build/Complete_Action_Surface.json", "Command_4/Complete_Action_Surface.json"):
        (workspace / relative).write_text(json.dumps({"source_packet_ids": [packet_id]}) + "\n", encoding="utf-8")
    return workspace, raw, packet_id


@_REQUIRES_ACCEPTED_FIXTURE
def test_packet_bridge_preserves_raw_registry_and_prunes_unreferenced_packets(tmp_path: Path) -> None:
    workspace, raw, packet_id = _minimal_packet_bridge_workspace(tmp_path)
    projection = materializer._bridge_rules_packet_registry(workspace, CORPUS)
    provenance = workspace / projection["modern_provenance_path"]
    assert provenance.read_bytes() == raw
    assert projection["modern_provenance_sha256"] == materializer.sha256_file(provenance)
    assert projection["native_registry_packet_ids"] == [packet_id]
    assert projection["native_registry_packet_count"] == 1
    assert len(projection["pruned_packet_ids"]) == 46
    native = json.loads((workspace / "Command_2/Rules_Selection_Packets.json").read_text(encoding="utf-8"))
    assert len(native["packets"]) == 1
    assert native["packets"][0]["authority"] == "tianxia_rules"
    assert native["packets"][0]["source_path"] == "Needed/Tianxia_PHB_Backgrounds_v2_BOOK_CLEAN_ORIGIN_RECONCILED_v0_6.md"
    assert native["packets"][0]["source_text"] == "## Abandoned Orphan"


@_REQUIRES_ACCEPTED_FIXTURE
def test_packet_bridge_retains_background_origin_insight_classification(tmp_path: Path) -> None:
    workspace, _raw, packet_id = _minimal_packet_bridge_workspace(tmp_path, packet_index=4)
    projection = materializer._bridge_rules_packet_registry(workspace, CORPUS)
    assert projection["native_registry_packet_ids"] == [packet_id]
    native = json.loads((workspace / "Command_2/Rules_Selection_Packets.json").read_text(encoding="utf-8"))
    assert native["packets"][0]["source_classification"] == "Background-Origin Insight"
    assert native["packets"][0]["source_path"] == "Needed/Tianxia_PHB_Origin_Insights_v0_4_READABILITY_SELF_CONTAINED.md"
    assert native["packets"][0]["source_text"] == "## 14. Beast Sign"


@_REQUIRES_ACCEPTED_FIXTURE
def test_packet_bridge_projects_build_registry_and_retains_both_modern_inputs(
    tmp_path: Path,
) -> None:
    """Every copied packet-registry consumer receives the same native bytes."""

    workspace, raw, _packet_id = _minimal_packet_bridge_workspace(tmp_path)
    build_registry = workspace / "Build/Rules_Selection_Packets.json"
    build_registry.write_bytes(raw)
    projection = materializer._bridge_rules_packet_registry(workspace, CORPUS)

    command2_provenance = workspace / projection["modern_provenance_path"]
    build_provenance = workspace / projection["build_modern_provenance_path"]
    command2_native = workspace / "Command_2/Rules_Selection_Packets.json"
    build_native = workspace / projection["build_native_registry_path"]
    assert command2_provenance.read_bytes() == raw
    assert build_provenance.read_bytes() == raw
    assert projection["build_modern_provenance_sha256"] == materializer.sha256_file(build_provenance)
    assert projection["build_native_registry_sha256"] == materializer.sha256_file(build_native)
    assert build_native.read_bytes() == command2_native.read_bytes()


@_REQUIRES_VENDOR_FIXTURE
def test_packet_bridge_rejects_referenced_starting_state_manifest_packet_without_native_proof(
    tmp_path: Path,
) -> None:
    """The reference-only packet 001 cannot be blanket-labelled as rules."""

    source_manifest = materializer.FINAL_CHARACTER_DEFAULT_FACTORY_ROOT / "09_RULES/RULES_SOURCE_MANIFEST.json"
    packet = _public_packet(
        "packet.stage2.001.eccc4d33ace2de0d",
        "tianxia.source.canon.authority.manifest.p2a.json",
        "CANON_AUTHORITY_MANIFEST_P2A.json",
        "09_RULES/RULES_SOURCE_MANIFEST.json",
        materializer.sha256_file(source_manifest),
        "record:tianxia.source.canon.authority.manifest.p2a.json:index:0",
        target_cl=0,
    )
    workspace = _public_packet_bridge_workspace(tmp_path, [packet])
    with pytest.raises(FoundryError) as error:
        materializer._bridge_rules_packet_registry(workspace, CORPUS)
    assert error.value.code == "FINAL_CHARACTER_PACKET_BRIDGE_UNRESOLVED"
    assert packet["packet_id"] in str(error.value.details)


@pytest.mark.parametrize("field,value", [("authority", "original_design"), ("source_text", "forged excerpt")])
@_REQUIRES_ACCEPTED_FIXTURE
def test_packet_bridge_rejects_forged_authority_or_excerpt(tmp_path: Path, field: str, value: str) -> None:
    workspace, raw, _packet_id = _minimal_packet_bridge_workspace(tmp_path)
    registry = json.loads(raw)
    registry["packets"][1][field] = value
    (workspace / "Command_2/Rules_Selection_Packets.json").write_text(json.dumps(registry) + "\n", encoding="utf-8")
    with pytest.raises(FoundryError) as error:
        materializer._bridge_rules_packet_registry(workspace, CORPUS)
    assert error.value.code == "FINAL_CHARACTER_PACKET_BRIDGE_UNRESOLVED"
    assert "forged" in str(error.value.details) or "conflicts" in str(error.value.details)


def _public_user_directive_packet(*, source_text: str = "Owner-authorized custom training source.") -> dict[str, Any]:
    return {
        "packet_id": "packet.public.user-directive",
        "record_id": "custom.training.source",
        "kind": "rule_selection",
        "name": "Owner Custom Training Source",
        "authority": "user_directive",
        "source_path": materializer._USER_DIRECTIVE_SOURCE_PATH,
        "source_anchor": "manual-lineage.custom-training-source",
        "source_text": source_text,
        "source_text_sha256": materializer._sha256_text(source_text),
    }


def _mark_user_directive_rows_custom(workspace: Path) -> None:
    for relative in (
        "Build/Character_Master_Ledger.json",
        "Build/Complete_Action_Surface.json",
        "Command_4/Complete_Action_Surface.json",
    ):
        path = workspace / relative
        value = json.loads(path.read_text(encoding="utf-8"))
        value["custom_design"] = True
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _user_directive_bridge_input_bytes(workspace: Path) -> dict[Path, bytes]:
    return {
        workspace / relative: (workspace / relative).read_bytes()
        for relative in (
            "Command_2/Rules_Selection_Packets.json",
            "Build/Character_Master_Ledger.json",
            "Build/Complete_Action_Surface.json",
            "Command_4/Complete_Action_Surface.json",
        )
    }


@_REQUIRES_VENDOR_FIXTURE
def test_packet_bridge_user_directive_preserves_exact_native_authority_and_source_bytes(
    tmp_path: Path,
) -> None:
    packet = _public_user_directive_packet()
    workspace = _public_packet_bridge_workspace(tmp_path, [packet])
    _mark_user_directive_rows_custom(workspace)
    raw_bytes = (workspace / "Command_2/Rules_Selection_Packets.json").read_bytes()

    projection = materializer._bridge_rules_packet_registry(workspace, CORPUS)

    provenance = workspace / projection["modern_provenance_path"]
    native = json.loads((workspace / "Command_2/Rules_Selection_Packets.json").read_text(encoding="utf-8"))
    assert provenance.read_bytes() == raw_bytes
    assert projection["native_registry_packet_ids"] == [packet["packet_id"]]
    assert native["packets"] == [{
        "authority": "user_directive",
        "modern_record_id": packet["record_id"],
        "modern_source_path": packet["source_path"],
        "modern_source_sha256": packet["source_text_sha256"],
        "name": packet["name"],
        "packet_id": packet["packet_id"],
        "source_classification": "user_directive",
        "source_evidence_verified": False,
        "source_path": packet["source_path"],
        "source_section": packet["source_anchor"],
        "source_text": packet["source_text"],
        "source_text_sha256": packet["source_text_sha256"],
    }]
    assert native["packets"][0]["authority"] != "tianxia_rules"


@pytest.mark.parametrize("mutation", [
    "missing_custom_design",
    "malformed_mixed_refs",
    "duplicate_refs",
    "blank_ref",
    "whitespace_ref",
    "tampered_source_text",
    "tampered_source_hash",
    "unsupported_source_path",
    "unsupported_authority",
    "conflicting_corpus_evidence",
    "recognized_canonical_family",
    "malformed_anchor_control",
    "untrimmed_anchor",
    "untrimmed_source_text",
    "oversize_source_text",
    "malformed_source_text",
])
@_REQUIRES_VENDOR_FIXTURE
def test_packet_bridge_user_directive_rejects_invalid_input_without_source_mutation(
    tmp_path: Path,
    mutation: str,
) -> None:
    packet = _public_user_directive_packet()
    workspace = _public_packet_bridge_workspace(tmp_path / mutation, [packet])
    if mutation != "missing_custom_design":
        _mark_user_directive_rows_custom(workspace)
    if mutation in {"malformed_mixed_refs", "duplicate_refs", "blank_ref", "whitespace_ref"}:
        reference_value: Any = {
            "malformed_mixed_refs": [packet["packet_id"], 7],
            "duplicate_refs": [packet["packet_id"], packet["packet_id"]],
            "blank_ref": [""],
            "whitespace_ref": [f" {packet['packet_id']}"],
        }[mutation]
        for relative in (
            "Build/Character_Master_Ledger.json",
            "Build/Complete_Action_Surface.json",
            "Command_4/Complete_Action_Surface.json",
        ):
            path = workspace / relative
            value = json.loads(path.read_text(encoding="utf-8"))
            value["source_packet_ids"] = reference_value
            path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    elif mutation == "tampered_source_text":
        packet["source_text"] += " Forged."
    elif mutation == "tampered_source_hash":
        packet["source_text_sha256"] = "0" * 64
    elif mutation == "unsupported_source_path":
        packet["source_path"] = "CURRENT_CONVERSATION"
    elif mutation == "unsupported_authority":
        packet["authority"] = "original_design"
    elif mutation == "conflicting_corpus_evidence":
        packet["source_evidence"] = [{
            "source_path": "Needed/Tianxia_Methods_Master_v0_1.md",
            "source_hash": materializer._PACKET_METHOD_SOURCE_SHA256,
            "source_anchor": "method:METHOD-001",
        }]
    elif mutation == "recognized_canonical_family":
        packet["record_id"] = "METHOD-001"
    elif mutation == "malformed_anchor_control":
        packet["source_anchor"] = "manual\x00lineage"
    elif mutation == "untrimmed_anchor":
        packet["source_anchor"] = " manual-lineage.custom-training-source"
    elif mutation == "untrimmed_source_text":
        packet["source_text"] = " " + packet["source_text"]
    elif mutation == "oversize_source_text":
        packet["source_text"] = "x" * (materializer._USER_DIRECTIVE_SOURCE_TEXT_MAX_BYTES + 1)
    elif mutation == "malformed_source_text":
        packet["source_text"] = None
    (workspace / "Command_2/Rules_Selection_Packets.json").write_text(
        json.dumps({"packets": [packet]}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    before = _user_directive_bridge_input_bytes(workspace)

    with pytest.raises(FoundryError) as error:
        materializer._bridge_rules_packet_registry(workspace, CORPUS)

    expected_code = (
        "FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID"
        if mutation in {"malformed_mixed_refs", "duplicate_refs", "blank_ref", "whitespace_ref"}
        else "FINAL_CHARACTER_PACKET_BRIDGE_UNRESOLVED"
    )
    assert error.value.code == expected_code
    assert _user_directive_bridge_input_bytes(workspace) == before
    assert not (workspace / "Command_2/Rules_Selection_Packets.json").read_bytes().startswith(b'{"schema_version": "HF05ZVK-R1H')


@_REQUIRES_VENDOR_FIXTURE
def test_packet_bridge_user_directive_rejects_mixed_directive_and_corpus_row_without_mutation(
    tmp_path: Path,
) -> None:
    user_packet = _public_user_directive_packet()
    canonical_packet = _public_packet(
        "packet.public.canonical",
        "tianxia.background.abandoned_orphan",
        "Abandoned Orphan",
        materializer._ABILITY_BACKGROUND_SOURCE_PATH,
        materializer._ABILITY_BACKGROUND_SOURCE_SHA256,
        "heading:abandoned_orphan",
    )
    workspace = _public_packet_bridge_workspace(tmp_path, [user_packet, canonical_packet])
    _mark_user_directive_rows_custom(workspace)
    before = _user_directive_bridge_input_bytes(workspace)

    with pytest.raises(FoundryError) as error:
        materializer._bridge_rules_packet_registry(workspace, CORPUS)

    assert error.value.code == "FINAL_CHARACTER_PACKET_BRIDGE_UNRESOLVED"
    assert "another packet authority" in str(error.value.details)
    assert _user_directive_bridge_input_bytes(workspace) == before


def _public_packet_bridge_workspace(tmp_path: Path, packets: list[dict[str, Any]]) -> Path:
    """Build a small public-safe executable registry for bridge tests."""

    workspace = tmp_path / "public-bridge-workspace"
    (workspace / "Build").mkdir(parents=True)
    (workspace / "Command_2").mkdir()
    (workspace / "Command_4").mkdir()
    (workspace / "Command_2/Rules_Selection_Packets.json").write_text(
        json.dumps({"packets": packets}, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for relative in (
        "Build/Character_Master_Ledger.json",
        "Build/Complete_Action_Surface.json",
        "Command_4/Complete_Action_Surface.json",
    ):
        (workspace / relative).write_text(
            json.dumps({"source_packet_ids": [packet["packet_id"] for packet in packets]}) + "\n",
            encoding="utf-8",
        )
    return workspace


def _write_core_stats_packet_maps(
    workspace: Path,
    *,
    skills: Any,
    skill_source_packet_ids: Any,
    saving_throw_adjustment_source_packet_ids: Any,
) -> None:
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["core_stats"] = {
        "skills": skills,
        "skill_source_packet_ids": skill_source_packet_ids,
        "saving_throw_adjustment_source_packet_ids": saving_throw_adjustment_source_packet_ids,
    }
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")


@_REQUIRES_ACCEPTED_FIXTURE
def test_packet_bridge_accepts_empty_core_saving_adjustment_map(tmp_path: Path) -> None:
    workspace, _raw, packet_id = _minimal_packet_bridge_workspace(tmp_path)
    _write_core_stats_packet_maps(
        workspace,
        skills={},
        skill_source_packet_ids={},
        saving_throw_adjustment_source_packet_ids={},
    )

    projection = materializer._bridge_rules_packet_registry(workspace, CORPUS)

    assert projection["native_registry_packet_ids"] == [packet_id]


@_REQUIRES_ACCEPTED_FIXTURE
def test_packet_bridge_collects_repeated_canonical_skill_map_refs(tmp_path: Path) -> None:
    workspace, _raw, packet_id = _minimal_packet_bridge_workspace(tmp_path)
    _write_core_stats_packet_maps(
        workspace,
        skills={"Arcana": {}, "Medicine": {}},
        skill_source_packet_ids={"Arcana": [packet_id], "Medicine": [packet_id]},
        saving_throw_adjustment_source_packet_ids={},
    )

    refs, locations, contexts = materializer._modern_packet_reference_contexts(workspace)

    assert refs == {packet_id}
    assert locations[packet_id].count(
        "Build/Character_Master_Ledger.json.core_stats.skill_source_packet_ids.Arcana"
    ) == 1
    assert locations[packet_id].count(
        "Build/Character_Master_Ledger.json.core_stats.skill_source_packet_ids.Medicine"
    ) == 1
    structured_contexts = [
        row_context
        for row_context in contexts[packet_id]
        if ".core_stats.skill_source_packet_ids." in row_context[1]
    ]
    assert len(structured_contexts) == 2
    assert all(row_context[3] is True for row_context in structured_contexts)
    projection = materializer._bridge_rules_packet_registry(workspace, CORPUS)
    assert projection["native_registry_packet_ids"] == [packet_id]


@_REQUIRES_ACCEPTED_FIXTURE
def test_packet_bridge_rejects_arbitrary_object_valued_packet_suffix(tmp_path: Path) -> None:
    workspace, _raw, packet_id = _minimal_packet_bridge_workspace(tmp_path)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["forged_source_packet_ids"] = {"Arcana": [packet_id]}
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    before = _user_directive_bridge_input_bytes(workspace)

    with pytest.raises(FoundryError) as error:
        materializer._bridge_rules_packet_registry(workspace, CORPUS)

    assert error.value.code == "FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID"
    assert _user_directive_bridge_input_bytes(workspace) == before


@pytest.mark.parametrize(
    "mutation",
    [
        "saving_nonempty",
        "saving_null",
        "saving_list",
        "skill_list",
        "skill_missing_key",
        "skill_blank_key",
        "skill_untrimmed_key",
        "skill_scalar_value",
        "skill_mixed_value",
        "skill_blank_value",
        "skill_whitespace_value",
        "skill_duplicate_value",
        "skill_wrong_location",
    ],
)
@_REQUIRES_ACCEPTED_FIXTURE
def test_packet_bridge_rejects_malformed_core_structured_packet_maps(
    tmp_path: Path,
    mutation: str,
) -> None:
    workspace, _raw, packet_id = _minimal_packet_bridge_workspace(tmp_path / mutation)
    skills: Any = {"Arcana": {}}
    skill_source_packet_ids: Any = {"Arcana": [packet_id]}
    saving_throw_adjustment_source_packet_ids: Any = {}
    if mutation == "saving_nonempty":
        saving_throw_adjustment_source_packet_ids = {"INT": [packet_id]}
    elif mutation == "saving_null":
        saving_throw_adjustment_source_packet_ids = None
    elif mutation == "saving_list":
        saving_throw_adjustment_source_packet_ids = [packet_id]
    elif mutation == "skill_list":
        skill_source_packet_ids = [packet_id]
    elif mutation == "skill_missing_key":
        skill_source_packet_ids = {"Medicine": [packet_id]}
    elif mutation == "skill_blank_key":
        skill_source_packet_ids = {"": [packet_id]}
    elif mutation == "skill_untrimmed_key":
        skill_source_packet_ids = {" Arcana": [packet_id]}
    elif mutation == "skill_scalar_value":
        skill_source_packet_ids = {"Arcana": packet_id}
    elif mutation == "skill_mixed_value":
        skill_source_packet_ids = {"Arcana": [packet_id, 7]}
    elif mutation == "skill_blank_value":
        skill_source_packet_ids = {"Arcana": [""]}
    elif mutation == "skill_whitespace_value":
        skill_source_packet_ids = {"Arcana": [f" {packet_id}"]}
    elif mutation == "skill_duplicate_value":
        skill_source_packet_ids = {"Arcana": [packet_id, packet_id]}
    elif mutation == "skill_wrong_location":
        skill_source_packet_ids = {"Arcana": [packet_id]}
    _write_core_stats_packet_maps(
        workspace,
        skills=skills,
        skill_source_packet_ids=skill_source_packet_ids,
        saving_throw_adjustment_source_packet_ids=saving_throw_adjustment_source_packet_ids,
    )
    if mutation == "skill_wrong_location":
        ledger_path = workspace / "Build/Character_Master_Ledger.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        ledger["skill_source_packet_ids"] = [packet_id]
        ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    before = _user_directive_bridge_input_bytes(workspace)

    with pytest.raises(FoundryError) as error:
        materializer._bridge_rules_packet_registry(workspace, CORPUS)

    assert error.value.code == "FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID"
    assert _user_directive_bridge_input_bytes(workspace) == before


@_REQUIRES_ACCEPTED_FIXTURE
def test_packet_bridge_user_directive_cannot_bypass_structured_skill_provenance_guard(
    tmp_path: Path,
) -> None:
    packet = _public_user_directive_packet()
    workspace = _public_packet_bridge_workspace(tmp_path, [packet])
    _mark_user_directive_rows_custom(workspace)
    _write_core_stats_packet_maps(
        workspace,
        skills={"Arcana": {}},
        skill_source_packet_ids={"Arcana": [packet["packet_id"]]},
        saving_throw_adjustment_source_packet_ids={},
    )
    before = _user_directive_bridge_input_bytes(workspace)

    with pytest.raises(FoundryError) as error:
        materializer._bridge_rules_packet_registry(workspace, CORPUS)

    assert error.value.code == "FINAL_CHARACTER_PACKET_BRIDGE_UNRESOLVED"
    assert "compiler provenance maps" in str(error.value.details)
    assert _user_directive_bridge_input_bytes(workspace) == before


def _public_packet(
    packet_id: str,
    record_id: str,
    display_name: str,
    source_path: str,
    source_hash: str,
    source_anchor: str,
    *,
    target_cl: int = 1,
) -> dict[str, Any]:
    return {
        "packet_id": packet_id,
        "record_id": record_id,
        "display_name": display_name,
        "target_cl": target_cl,
        "source_evidence": [
            {
                "source_path": source_path,
                "source_hash": source_hash,
                "source_anchor": source_anchor,
            }
        ],
    }


def _public_background_origin_grant_workspace(tmp_path: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Build a small native-packet workspace for CL1 grant projection tests."""

    workspace = tmp_path / "background-origin-grant-workspace"
    (workspace / "Build").mkdir(parents=True)
    (workspace / "Command_2").mkdir()
    background_id = "tianxia.background.abandoned_orphan"
    origin_id = "tianxia.origin_insight.born_under_suspicion"
    background_packet_id = "packet.public.background"
    origin_packet_id = "packet.public.origin"
    asi_packet_id = "packet.public.asi"
    background_source_path = materializer._ABILITY_BACKGROUND_SOURCE_PATH
    background_source_hash = materializer._ABILITY_BACKGROUND_SOURCE_SHA256
    origin_source_path = "09_RULES/Source_Text/Tianxia_PHB_Origin_Insights_v0_4_READABILITY_SELF_CONTAINED.md"
    origin_source_hash = "fcbbee35265279b58b7b43b74416de633d66eea144ccd90c9785a46ac38f1946"
    background = {
        "background_id": background_id,
        "background_sphere": "Scoundrel",
        "background_talent": "HIDDEN TOOL CACHE",
        "name": "Abandoned Orphan",
        "source_packet_ids": [background_packet_id],
    }
    origin = {
        "origin_insight_id": origin_id,
        "name": "Born Under Suspicion",
        "source_packet_ids": [origin_packet_id],
    }
    raw_ledger = {
        "schema_version": "HF05ZVK-R1F",
        "equipment": {
            "reason": "No equipment was selected.",
            "reason_code": "not_selected_for_c1a_proof",
            "source_backed": True,
            "state": "none",
        },
        "typed_none": {
            "equipment": {
                "reason": "No equipment was selected.",
                "reason_code": "not_selected_for_c1a_proof",
                "source_backed": True,
                "state": "none",
            },
        },
        "character": {
            "cl": 2,
            "path": "Qi Cultivation",
            "path_id": "tianxia.path.qi_cultivation",
        },
        "background_origin": {
            "background": deepcopy(background),
            "origin_insight": deepcopy(origin),
        },
        "advancement": {"levels": [{"cl": 1}, {"cl": 2}]},
    }
    ledger = deepcopy(raw_ledger)
    asi = {
        "allocation_id": "ability-score-change.packet.public.asi",
        "channel": "event",
        "grant_type": "event",
        "grant_id": "ability-score-change.packet.public.asi",
        "name": "Ability Score Improvement or Cultivation Insight: Intelligence +2",
        "slot_cost": 0,
        "ability_score_adjustments": {"INT": 2},
        "source_packet_ids": [asi_packet_id],
        "source_event_id": "event.public.asi",
        "event_type": "ability_score_change",
        "target_cl": 1,
    }
    ledger["advancement"]["levels"][1]["allocations"] = [deepcopy(asi)]
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    (workspace / "Build/Background_Origin_Ledger.json").write_text(
        json.dumps(
            {
                "schema_version": "TianxiaFoundry.CharacterGMBackgroundOrigin.v1",
                "background_origin": {"background": deepcopy(background), "origin_insight": deepcopy(origin)},
            },
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    raw_bytes = (json.dumps(raw_ledger, sort_keys=True) + "\n").encode("utf-8")
    (workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE).write_bytes(raw_bytes)
    explicit_none = raw_ledger["equipment"]
    (workspace / "Build/Equipment_Ledger.json").write_text(
        json.dumps({
            "equipment": [],
            "none_state": deepcopy(explicit_none),
            "schema_version": "TianxiaFoundry.CharacterGMEquipment.v1",
            "source": "Character_Master_Ledger.json",
        }, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (workspace / "Build/Equipment_Ledger_Legacy.json").write_text(
        json.dumps({
            "equipment": [],
            "none_state": deepcopy(explicit_none),
            "schema_version": "TianxiaFoundry.CharacterGMEquipmentLegacy.v1",
            "source": "Character_Master_Ledger.json",
        }, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (workspace / "Build/Item_Execution_Coverage.json").write_text(
        json.dumps({
            "coverage": [],
            "items": [],
            "schema_version": "TianxiaFoundry.ItemExecutionCoverage.v1",
            "status": "SOURCE_EXPLICIT_NONE",
        }, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (workspace / "Build/Selected_Item_GM_Projection.json").write_text(
        json.dumps({
            "items": [],
            "schema_version": "TianxiaFoundry.ItemGMScreenSelectedProjection.v1",
            "status": "SOURCE_EXPLICIT_NONE",
        }, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    modern_packets = [
        {
            "packet_id": background_packet_id,
            "record_id": background_id,
            "display_name": background["name"],
            "target_cl": 1,
            "advancement_kind": "background_acquisition",
            "event_id": "event.public.background",
            "source_evidence": [{
                "source_path": background_source_path,
                "source_hash": background_source_hash,
                "source_anchor": "heading:abandoned_orphan",
            }],
        },
        {
            "packet_id": origin_packet_id,
            "record_id": origin_id,
            "display_name": origin["name"],
            "target_cl": 1,
            "advancement_kind": "origin_insight_acquisition",
            "event_id": "event.public.origin",
            "source_evidence": [{
                "source_path": origin_source_path,
                "source_hash": origin_source_hash,
                "source_anchor": "heading:9-born_under_suspicion",
            }],
        },
        {
            "packet_id": asi_packet_id,
            "record_id": "tianxia.path.qi_cultivation.feature.ability_score_improvement_or_cultivation_insight",
            "display_name": "Ability Score Improvement or Cultivation Insight",
            "target_cl": 1,
            "advancement_kind": "ability_score_change",
            "event_id": "event.public.asi",
            "source_evidence": [{
                "source_path": materializer._PACKET_PATH_PROOFS["tianxia.path.qi_cultivation"]["index_path"],
                "source_hash": materializer._PACKET_PATH_PROOFS["tianxia.path.qi_cultivation"]["index_sha256"],
                "source_anchor": "path-feature:tianxia.path.qi_cultivation.feature.ability_score_improvement_or_cultivation_insight",
            }],
        },
    ]
    modern_registry = {
        "schema_version": "TianxiaFoundry.RulesSelectionPackets.v2",
        "packets": modern_packets,
    }
    modern_registry_bytes = (json.dumps(modern_registry, sort_keys=True) + "\n").encode("utf-8")
    (workspace / "Command_2/Rules_Selection_Packets.Modern_Provenance.json").write_bytes(modern_registry_bytes)

    native_source = {
        background_packet_id: ("Needed/Tianxia_PHB_Backgrounds_v2_BOOK_CLEAN_ORIGIN_RECONCILED_v0_6.md", "## Abandoned Orphan"),
        origin_packet_id: ("Needed/Tianxia_PHB_Origin_Insights_v0_4_READABILITY_SELF_CONTAINED.md", "## 9. Born Under Suspicion"),
        asi_packet_id: ("Needed/Public ASI", "Ability Score Improvement or Cultivation Insight"),
    }
    native_packets = []
    for packet in modern_packets:
        evidence = packet["source_evidence"][0]
        source_path, source_text = native_source[packet["packet_id"]]
        native_packets.append({
            "packet_id": packet["packet_id"],
            "name": packet["display_name"],
            "authority": "tianxia_rules",
            "source_path": source_path,
            "source_text": source_text,
            "source_text_sha256": materializer._sha256_text(source_text),
            "source_section": evidence["source_anchor"],
            "source_classification": packet["advancement_kind"],
            "modern_record_id": packet["record_id"],
            "modern_source_path": evidence["source_path"],
            "modern_source_sha256": evidence["source_hash"],
            "source_evidence_verified": True,
        })
    native_registry = {
        "schema_version": "HF05ZVK-R1H.CompilerRulesSelectionPackets.v1",
        "packets": native_packets,
    }
    (workspace / "Command_2/Rules_Selection_Packets.json").write_text(
        json.dumps(native_registry, sort_keys=True) + "\n", encoding="utf-8"
    )
    ability_projection = {
        "schema_version": "TianxiaFoundry.FinalCharacterAbilityProjectionProvenance.v1",
        "background_id": background_id,
        "background_packet_id": background_packet_id,
        "allocations_by_cl": {"1": [], "2": [deepcopy(asi)]},
    }
    return workspace, ledger, ability_projection


def _public_origin_insight_projection_workspace(tmp_path: Path) -> tuple[Path, bytes]:
    """Build a sealed Born Under Suspicion row for compiler projection tests."""

    workspace, _original, _ability_projection = _public_background_origin_grant_workspace(tmp_path)
    selection = {
        "selected_skill": "Deception",
        "result": "expertise",
        "initiative_effect": "situational_advantage",
        "summary": "You gain proficiency in Deception or Insight. If you already have proficiency in the chosen skill, gain expertise in it.",
    }
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    for relative in (
        materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "Build/Character_Master_Ledger.json",
        "Build/Background_Origin_Ledger.json",
    ):
        path = workspace / relative
        value = json.loads(path.read_text(encoding="utf-8"))
        value["background_origin"]["origin_insight"].update(selection)
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    modern_registry = workspace / "Command_2/Rules_Selection_Packets.Modern_Provenance.json"
    (workspace / "Command_2/Rules_Selection_Packets.json").write_bytes(modern_registry.read_bytes())
    return workspace, raw_path.read_bytes()


def test_origin_insight_compiler_projection_synthetic_success(tmp_path: Path) -> None:
    workspace, raw_before = _public_origin_insight_projection_workspace(tmp_path)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    mirror_path = workspace / "Build/Background_Origin_Ledger.json"

    projection = materializer._project_background_origin_insight_for_compiler(workspace)

    projected = json.loads(ledger_path.read_text(encoding="utf-8"))
    mirrored = json.loads(mirror_path.read_text(encoding="utf-8"))
    origin = projected["background_origin"]["origin_insight"]
    benefit = "You gain proficiency in Deception or Insight. If you already have proficiency in the chosen skill, gain expertise in it."
    assert origin["origin_insight_id"] == materializer._ORIGIN_INSIGHT_ID
    assert origin["selected_skill"] == "Deception"
    assert origin["result"] == "expertise"
    assert origin["allocation_id"] == "allocation.origin.packet.public.origin"
    assert origin["benefit"] == benefit
    assert origin["restrictions"] == []
    assert [row["effect_id"] for row in origin["effect_records"]] == [
        "ORI_BORN_UNDER_SUSPICION_PROFICIENCY",
        "ORI_BORN_UNDER_SUSPICION_JUDGMENT_ADVANTAGE",
        "ORI_BORN_UNDER_SUSPICION_FALSE_BLAME_REROLL",
    ]
    assert origin["effect_records"][0]["source_claim_text"] == benefit
    assert mirrored["background_origin"]["origin_insight"] == origin
    assert (workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE).read_bytes() == raw_before
    assert projection["benefit"] == benefit
    assert projection["details_sha256"] == materializer.sha256_file(
        workspace / projection["details_path"]
    )


@_REQUIRES_ORIGIN_INSIGHT_FIXTURE
def test_origin_insight_compiler_projection_exact_real_source_without_mutating_source(tmp_path: Path) -> None:
    source_before = materializer._workspace_sha256(ORIGIN_INSIGHT_SOURCE)
    workspace = tmp_path / "real-source-origin-insight"
    materializer._copy_tree_no_symlinks(ORIGIN_INSIGHT_SOURCE, workspace)
    source_ledger = json.loads((workspace / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8"))
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    raw_path.write_text(json.dumps(source_ledger, sort_keys=True) + "\n", encoding="utf-8")
    raw_before = raw_path.read_bytes()

    projection = materializer._project_background_origin_insight_for_compiler(workspace)

    projected = json.loads((workspace / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8"))
    mirrored = json.loads((workspace / "Build/Background_Origin_Ledger.json").read_text(encoding="utf-8"))
    origin = projected["background_origin"]["origin_insight"]
    assert origin["origin_insight_id"] == materializer._ORIGIN_INSIGHT_ID
    assert origin["name"] == materializer._ORIGIN_INSIGHT_NAME
    assert origin["selected_skill"] == materializer._ORIGIN_INSIGHT_SELECTED_SKILL
    assert origin["result"] == materializer._ORIGIN_INSIGHT_RESULT
    assert origin["benefit"].startswith("You gain proficiency in Deception or Insight.")
    assert len(origin["effect_records"]) == 3
    assert mirrored["background_origin"]["origin_insight"] == origin
    assert raw_path.read_bytes() == raw_before
    assert materializer._workspace_sha256(ORIGIN_INSIGHT_SOURCE) == source_before
    assert projection["origin_source_sha256"] == materializer._ORIGIN_INSIGHT_SOURCE_SHA256


@pytest.mark.parametrize("mutation", ("mirror_benefit", "raw_selection", "null_mirror", "missing_mirror"))
def test_origin_insight_compiler_projection_rejects_conflicts_without_mutation(tmp_path: Path, mutation: str) -> None:
    workspace, _raw_before = _public_origin_insight_projection_workspace(tmp_path / mutation)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    mirror_path = workspace / "Build/Background_Origin_Ledger.json"
    if mutation == "mirror_benefit":
        value = json.loads(mirror_path.read_text(encoding="utf-8"))
        value["background_origin"]["origin_insight"]["benefit"] = "forged"
        mirror_path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    elif mutation == "raw_selection":
        value = json.loads(raw_path.read_text(encoding="utf-8"))
        value["background_origin"]["origin_insight"]["selected_skill"] = "Insight"
        raw_path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    elif mutation == "null_mirror":
        mirror_path.write_bytes(b"null\n")
    else:
        mirror_path.unlink()
    before = {
        path: path.read_bytes()
        for path in (ledger_path, raw_path)
        if path.exists()
    }

    with pytest.raises(FoundryError) as error:
        materializer._project_background_origin_insight_for_compiler(workspace)

    assert error.value.code == "FINAL_CHARACTER_ORIGIN_INSIGHT_PROJECTION_INVALID"
    assert {path: path.read_bytes() for path in before} == before
    if mutation == "null_mirror":
        assert mirror_path.read_bytes() == b"null\n"
    elif mutation == "missing_mirror":
        assert not mirror_path.exists()
    else:
        assert mirror_path.is_file()
    assert not (workspace / materializer._ORIGIN_INSIGHT_PROJECTION_DETAILS_RELATIVE).exists()


def test_origin_insight_compiler_projection_rejects_missing_initiative_effect_without_mutation(tmp_path: Path) -> None:
    workspace, _raw_before = _public_origin_insight_projection_workspace(tmp_path / "missing-initiative-effect")
    paths = (
        workspace / "Build/Character_Master_Ledger.json",
        workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        workspace / "Build/Background_Origin_Ledger.json",
    )
    for path in paths:
        value = json.loads(path.read_text(encoding="utf-8"))
        value["background_origin"]["origin_insight"].pop("initiative_effect")
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    before = {path: path.read_bytes() for path in paths}

    with pytest.raises(FoundryError) as error:
        materializer._project_background_origin_insight_for_compiler(workspace)

    assert error.value.code == "FINAL_CHARACTER_ORIGIN_INSIGHT_PROJECTION_INVALID"
    assert {path: path.read_bytes() for path in paths} == before
    assert not (workspace / materializer._ORIGIN_INSIGHT_PROJECTION_DETAILS_RELATIVE).exists()


def test_background_authority_pin_matches_the_installed_authority() -> None:
    """58c2a039 (owner ruling 2026-09-28) edited Background_Core_Authority_v1
    and missed this pin, so _bridge_fixed_json refused the file and every
    Background projection failed with 'lacks the fixed canonical ... authority'."""

    installed = materializer._FINAL_CHARACTER_APP_ROOT / materializer._ABILITY_BACKGROUND_AUTHORITY_PATH
    assert materializer.sha256_file(installed) == materializer._ABILITY_BACKGROUND_AUTHORITY_SHA256
    assert materializer._bridge_fixed_json(
        materializer._ABILITY_BACKGROUND_AUTHORITY_PATH,
        materializer._ABILITY_BACKGROUND_AUTHORITY_SHA256,
    ) is not None


def test_background_origin_grant_projection_assigns_cl1_rows_and_preserves_asi(tmp_path: Path) -> None:
    workspace, original, ability_projection = _public_background_origin_grant_workspace(tmp_path)
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    raw_before = raw_path.read_bytes()
    projection = materializer._project_background_origin_allocations_for_compiler(
        workspace,
        ability_projection=ability_projection,
    )
    projected = json.loads((workspace / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8"))
    background_packet_id = original["background_origin"]["background"]["source_packet_ids"][0]
    origin_packet_id = original["background_origin"]["origin_insight"]["source_packet_ids"][0]
    assert projected["background_origin"]["background"]["allocation_id"] == f"allocation.background.{background_packet_id}"
    assert projected["background_origin"]["background"]["grant_mode"] == "sphere_and_talent"
    assert projected["background_origin"]["origin_insight"]["allocation_id"] == f"allocation.origin.{origin_packet_id}"
    cl1 = projected["advancement"]["levels"][0]["allocations"]
    assert cl1 == [
        {
            "allocation_id": f"allocation.background.{background_packet_id}",
            "channel": "background",
            "grant_type": "background",
            "grant_id": "tianxia.background.abandoned_orphan",
            "name": "Abandoned Orphan",
            "slot_cost": 0,
            "source_packet_ids": [background_packet_id],
        },
        {
            "allocation_id": f"allocation.origin.{origin_packet_id}",
            "channel": "origin",
            "grant_type": "origin_insight",
            "grant_id": "tianxia.origin_insight.born_under_suspicion",
            "name": "Born Under Suspicion",
            "slot_cost": 0,
            "source_packet_ids": [origin_packet_id],
        },
    ]
    assert projected["advancement"]["levels"][1]["allocations"] == ability_projection["allocations_by_cl"]["2"]
    assert raw_path.read_bytes() == raw_before
    assert projection["background_origin_allocations_by_cl"]["1"] == cl1
    assert projection["background_grant_mode"] == "sphere_and_talent"
    assert projection["details_sha256"] == materializer.sha256_file(workspace / projection["details_path"])


def test_background_origin_grant_projection_preserves_valid_grant_mode_and_mirrors_surface(tmp_path: Path) -> None:
    workspace, _original, ability_projection = _public_background_origin_grant_workspace(tmp_path)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    mirror_path = workspace / "Build/Background_Origin_Ledger.json"
    for path in (ledger_path, raw_path, mirror_path):
        value = json.loads(path.read_text(encoding="utf-8"))
        value["background_origin"]["background"]["grant_mode"] = "sphere_and_talent"
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")

    projection = materializer._project_background_origin_allocations_for_compiler(
        workspace,
        ability_projection=ability_projection,
    )
    projected = json.loads(ledger_path.read_text(encoding="utf-8"))
    mirrored = json.loads(mirror_path.read_text(encoding="utf-8"))
    assert projection["background_grant_mode"] == "sphere_and_talent"
    assert projected["background_origin"]["background"]["grant_mode"] == "sphere_and_talent"
    assert mirrored["background_origin"]["background"]["grant_mode"] == "sphere_and_talent"
    assert mirrored["background_origin"]["background"] == projected["background_origin"]["background"]
    assert mirrored["background_origin"]["origin_insight"] == projected["background_origin"]["origin_insight"]


def test_background_origin_grant_projection_rejects_missing_sealed_route_without_mutation(tmp_path: Path) -> None:
    workspace, _original, ability_projection = _public_background_origin_grant_workspace(tmp_path)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    mirror_path = workspace / "Build/Background_Origin_Ledger.json"
    for path in (ledger_path, raw_path):
        value = json.loads(path.read_text(encoding="utf-8"))
        value["background_origin"]["background"].pop("background_talent")
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    before = {path: path.read_bytes() for path in (ledger_path, raw_path, mirror_path)}
    with pytest.raises(FoundryError) as error:
        materializer._project_background_origin_allocations_for_compiler(
            workspace,
            ability_projection=ability_projection,
        )
    assert error.value.code == "FINAL_CHARACTER_GRANT_ALLOCATION_PROJECTION_INVALID"
    assert {path: path.read_bytes() for path in (ledger_path, raw_path, mirror_path)} == before
    assert not (workspace / materializer._GRANT_PROJECTION_DETAILS_RELATIVE).exists()


def test_background_origin_grant_projection_rejects_conflicting_mirror_grant_mode_without_mutation(tmp_path: Path) -> None:
    workspace, _original, ability_projection = _public_background_origin_grant_workspace(tmp_path)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    mirror_path = workspace / "Build/Background_Origin_Ledger.json"
    mirror = json.loads(mirror_path.read_text(encoding="utf-8"))
    mirror["background_origin"]["background"]["grant_mode"] = "compensation"
    mirror_path.write_text(json.dumps(mirror, sort_keys=True) + "\n", encoding="utf-8")
    before = {path: path.read_bytes() for path in (ledger_path, raw_path, mirror_path)}
    with pytest.raises(FoundryError) as error:
        materializer._project_background_origin_allocations_for_compiler(
            workspace,
            ability_projection=ability_projection,
        )
    assert error.value.code == "FINAL_CHARACTER_GRANT_ALLOCATION_PROJECTION_INVALID"
    assert {path: path.read_bytes() for path in (ledger_path, raw_path, mirror_path)} == before
    assert not (workspace / materializer._GRANT_PROJECTION_DETAILS_RELATIVE).exists()


@_REQUIRES_ACCEPTED_FIXTURE
def test_background_origin_grant_projection_populates_real_source_shape_without_mutating_source(tmp_path: Path) -> None:
    source_before = materializer._workspace_sha256(SOURCE)
    workspace = tmp_path / "real-source"
    materializer._copy_tree_no_symlinks(SOURCE, workspace)
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    source_ledger = json.loads((workspace / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8"))
    raw_path.write_text(json.dumps(source_ledger, sort_keys=True) + "\n", encoding="utf-8")
    target_cl = source_ledger["character"]["cl"]
    ability_projection = {
        "schema_version": "TianxiaFoundry.FinalCharacterAbilityProjectionProvenance.v1",
        "background_id": "tianxia.background.abandoned_orphan",
        "background_packet_id": source_ledger["background_origin"]["background"]["source_packet_ids"][0],
        "allocations_by_cl": {str(cl): [] for cl in range(1, target_cl + 1)},
    }
    projection = materializer._project_background_origin_allocations_for_compiler(
        workspace,
        ability_projection=ability_projection,
    )
    projected = json.loads((workspace / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8"))
    mirrored = json.loads((workspace / "Build/Background_Origin_Ledger.json").read_text(encoding="utf-8"))
    assert projected["background_origin"]["background"]["grant_mode"] == "sphere_and_talent"
    assert mirrored["background_origin"]["background"]["grant_mode"] == "sphere_and_talent"
    assert mirrored["background_origin"]["background"] == projected["background_origin"]["background"]
    assert mirrored["background_origin"]["origin_insight"] == projected["background_origin"]["origin_insight"]
    assert projection["background_grant_mode"] == "sphere_and_talent"
    assert materializer._workspace_sha256(SOURCE) == source_before
    assert raw_path.is_file()


def test_background_equipment_projection_renders_fixed_authority_and_mirrors_surface(tmp_path: Path) -> None:
    workspace, _original, _ability_projection = _public_background_origin_grant_workspace(tmp_path)
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    mirror_path = workspace / "Build/Background_Origin_Ledger.json"
    inventory_paths = (
        workspace / "Build/Equipment_Ledger.json",
        workspace / "Build/Equipment_Ledger_Legacy.json",
        workspace / "Build/Item_Execution_Coverage.json",
        workspace / "Build/Selected_Item_GM_Projection.json",
    )
    before = {
        path: path.read_bytes()
        for path in (
            raw_path,
            *inventory_paths,
        )
    }

    projection = materializer._project_background_equipment_for_compiler(workspace)

    expected = printed_background_items("tianxia.background.abandoned_orphan")
    explicit_none = {
        "reason": "No equipment was selected.",
        "reason_code": "not_selected_for_c1a_proof",
        "source_backed": True,
        "state": "none",
    }
    projected = json.loads(ledger_path.read_text(encoding="utf-8"))
    mirrored = json.loads(mirror_path.read_text(encoding="utf-8"))
    assert projected["equipment"] == []
    assert projected["typed_none"]["equipment"] == explicit_none
    assert projected["background_origin"]["background"]["equipment"] == expected
    assert projected["background_origin"]["background"]["equipment_reconciliation"] == {
        "printed_items": expected,
        "ledger_equipment_ids": [],
        "bundled_items": [],
        "missing_items": [],
        "note": (
            "Every printed starting-equipment entry is retained from the fixed Background authority; "
            "the candidate's optional equipment inventory is explicitly none."
        ),
    }
    assert mirrored["background_origin"]["background"] == projected["background_origin"]["background"]
    assert projection["inventory_state"] == "SOURCE_EXPLICIT_NONE"
    assert projection["legacy_top_level_equipment"] == []
    assert projection["typed_none_equipment"] == explicit_none
    assert projection["authority_sha256"] == materializer._ABILITY_BACKGROUND_AUTHORITY_SHA256
    for path, value in before.items():
        assert path.read_bytes() == value


@_REQUIRES_ACCEPTED_FIXTURE
def test_background_equipment_projection_populates_real_source_shape_without_mutating_source(tmp_path: Path) -> None:
    source_before = materializer._workspace_sha256(SOURCE)
    workspace = tmp_path / "real-source-equipment"
    materializer._copy_tree_no_symlinks(SOURCE, workspace)
    source_ledger = json.loads((workspace / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8"))
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    raw_path.write_text(json.dumps(source_ledger, sort_keys=True) + "\n", encoding="utf-8")

    projection = materializer._project_background_equipment_for_compiler(workspace)

    projected = json.loads((workspace / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8"))
    mirrored = json.loads((workspace / "Build/Background_Origin_Ledger.json").read_text(encoding="utf-8"))
    assert projected["equipment"] == []
    assert projected["typed_none"]["equipment"] == source_ledger["typed_none"]["equipment"]
    assert projected["background_origin"]["background"]["equipment"] == printed_background_items("tianxia.background.abandoned_orphan")
    assert projected["background_origin"]["background"]["equipment_reconciliation"]["missing_items"] == []
    assert mirrored["background_origin"]["background"] == projected["background_origin"]["background"]
    assert projection["background_id"] == "tianxia.background.abandoned_orphan"
    assert materializer._workspace_sha256(SOURCE) == source_before


@pytest.mark.parametrize("mutation", ("inventory", "mirror", "partial", "top_level", "typed_none"))
def test_background_equipment_projection_rejects_ambiguous_inputs_without_mutation(tmp_path: Path, mutation: str) -> None:
    workspace, _original, _ability_projection = _public_background_origin_grant_workspace(tmp_path / mutation)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    mirror_path = workspace / "Build/Background_Origin_Ledger.json"
    if mutation == "inventory":
        path = workspace / "Build/Equipment_Ledger.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["equipment"] = [{"equipment_id": "EQ_FORGED", "name": "forged item"}]
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    elif mutation == "mirror":
        value = json.loads(mirror_path.read_text(encoding="utf-8"))
        value["background_origin"]["background"]["equipment"] = ["forged item"]
        value["background_origin"]["background"]["equipment_reconciliation"] = {
            "printed_items": ["forged item"],
            "ledger_equipment_ids": [],
            "bundled_items": [],
            "missing_items": [],
            "note": "forged",
        }
        mirror_path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    else:
        value = json.loads(ledger_path.read_text(encoding="utf-8"))
        if mutation == "partial":
            value["background_origin"]["background"]["equipment"] = []
        elif mutation == "top_level":
            value["equipment"] = []
        else:
            value["typed_none"]["equipment"]["state"] = "forged"
        ledger_path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    inventory_paths = (
        workspace / "Build/Equipment_Ledger.json",
        workspace / "Build/Equipment_Ledger_Legacy.json",
        workspace / "Build/Item_Execution_Coverage.json",
        workspace / "Build/Selected_Item_GM_Projection.json",
    )
    before = {
        path: path.read_bytes()
        for path in (ledger_path, raw_path, mirror_path, *inventory_paths)
    }
    with pytest.raises(FoundryError) as error:
        materializer._project_background_equipment_for_compiler(workspace)
    assert error.value.code == "FINAL_CHARACTER_BACKGROUND_EQUIPMENT_PROJECTION_INVALID"
    assert {path: path.read_bytes() for path in before} == before


def test_background_equipment_projection_rejects_missing_mirror_without_mutation(tmp_path: Path) -> None:
    workspace, _original, _ability_projection = _public_background_origin_grant_workspace(tmp_path / "missing-mirror")
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    mirror_path = workspace / "Build/Background_Origin_Ledger.json"
    inventory_paths = (
        workspace / "Build/Equipment_Ledger.json",
        workspace / "Build/Equipment_Ledger_Legacy.json",
        workspace / "Build/Item_Execution_Coverage.json",
        workspace / "Build/Selected_Item_GM_Projection.json",
    )
    before = {path: path.read_bytes() for path in (ledger_path, raw_path, *inventory_paths)}
    mirror_path.unlink()

    with pytest.raises(FoundryError) as error:
        materializer._project_background_equipment_for_compiler(workspace)

    assert error.value.code == "FINAL_CHARACTER_BACKGROUND_EQUIPMENT_PROJECTION_INVALID"
    assert {path: path.read_bytes() for path in before} == before
    assert not mirror_path.exists()


def test_background_equipment_projection_rejects_null_mirror_without_mutation(tmp_path: Path) -> None:
    workspace, _original, _ability_projection = _public_background_origin_grant_workspace(tmp_path / "null-mirror")
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    mirror_path = workspace / "Build/Background_Origin_Ledger.json"
    inventory_paths = (
        workspace / "Build/Equipment_Ledger.json",
        workspace / "Build/Equipment_Ledger_Legacy.json",
        workspace / "Build/Item_Execution_Coverage.json",
        workspace / "Build/Selected_Item_GM_Projection.json",
    )
    before = {path: path.read_bytes() for path in (ledger_path, raw_path, *inventory_paths)}
    mirror_path.write_bytes(b"null\n")

    with pytest.raises(FoundryError) as error:
        materializer._project_background_equipment_for_compiler(workspace)

    assert error.value.code == "FINAL_CHARACTER_BACKGROUND_EQUIPMENT_PROJECTION_INVALID"
    assert {path: path.read_bytes() for path in before} == before
    assert mirror_path.read_bytes() == b"null\n"


@pytest.mark.parametrize("mutation", ("record", "name", "native", "missing_source", "conflicting_allocation", "collision"))
def test_background_origin_grant_projection_rejects_conflicting_inputs(tmp_path: Path, mutation: str) -> None:
    workspace, original, ability_projection = _public_background_origin_grant_workspace(tmp_path / mutation)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    if mutation in {"record", "name"}:
        path = workspace / "Command_2/Rules_Selection_Packets.Modern_Provenance.json"
        registry = json.loads(path.read_text(encoding="utf-8"))
        if mutation == "record":
            registry["packets"][0]["record_id"] = "tianxia.background.forged"
        else:
            registry["packets"][1]["display_name"] = "Forged Origin"
        path.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")
    elif mutation == "native":
        path = workspace / "Command_2/Rules_Selection_Packets.json"
        registry = json.loads(path.read_text(encoding="utf-8"))
        registry["packets"][0]["authority"] = "user_directive"
        path.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")
    else:
        raw = deepcopy(original)
        if mutation == "missing_source":
            raw["background_origin"]["background"]["source_packet_ids"] = ["packet.public.missing"]
            current = deepcopy(raw)
        elif mutation == "conflicting_allocation":
            current = json.loads(ledger_path.read_text(encoding="utf-8"))
            current["advancement"]["levels"][0].setdefault("allocations", []).append({
                "allocation_id": "allocation.forged",
                "channel": "background",
                "grant_type": "background",
                "grant_id": "forged",
                "name": "Forged",
                "slot_cost": 0,
                "source_packet_ids": ["packet.public.background"],
            })
            raw = original
        else:
            raw = deepcopy(original)
            raw["background_origin"]["background"]["allocation_id"] = "allocation.origin.packet.public.origin"
            current = deepcopy(raw)
        if mutation == "missing_source":
            current = deepcopy(raw)
        if mutation == "collision":
            current = deepcopy(raw)
        raw_path.write_text(json.dumps(raw, sort_keys=True) + "\n", encoding="utf-8")
        ledger_path.write_text(json.dumps(current, sort_keys=True) + "\n", encoding="utf-8")
    before = ledger_path.read_bytes()
    with pytest.raises(FoundryError) as error:
        materializer._project_background_origin_allocations_for_compiler(
            workspace,
            ability_projection=ability_projection,
        )
    assert error.value.code == "FINAL_CHARACTER_GRANT_ALLOCATION_PROJECTION_INVALID"
    assert ledger_path.read_bytes() == before
    assert not (workspace / materializer._GRANT_PROJECTION_DETAILS_RELATIVE).exists()


def _public_path_projection_workspace(tmp_path: Path) -> tuple[Path, bytes, dict[str, Any]]:
    """Build a public-safe modern Path ledger with repeated milestone rows."""

    path_id = "tianxia.path.qi_cultivation"
    path_name = "Qi Cultivation"
    proof = materializer._PACKET_PATH_PROOFS[path_id]
    path_row = {
        "display_name": path_name,
        "effective_cl": 15,
        "key_ability": "INT",
        "path_id": path_id,
        "selected_skills": [],
        "source_packet_ids": ["packet.public.path"],
    }
    asi_id = f"{path_id}.feature.ability_score_improvement_or_cultivation_insight"
    subpath_id = f"{path_id}.feature.subpath_feature"
    features = [
        {
            "category": "path_feature",
            "feature_id": asi_id,
            "name": "Ability Score Improvement or Cultivation Insight",
            "gained_at_cl": 4,
            "allocation_id": "allocation.public.asi.4",
            "source_packet_ids": ["packet.public.asi.4"],
        },
        {
            "category": "path_feature",
            "feature_id": subpath_id,
            "name": "Subpath Feature",
            "gained_at_cl": 6,
            "allocation_id": "allocation.public.subpath.6",
            "source_packet_ids": ["packet.public.subpath.6"],
        },
        {
            "category": "path_feature",
            "feature_id": asi_id,
            "name": "Ability Score Improvement or Cultivation Insight",
            "gained_at_cl": 8,
            "allocation_id": "allocation.public.asi.8",
            "source_packet_ids": ["packet.public.asi.8"],
        },
        {
            "category": "talent",
            "feature_id": "tianxia.talent.public.synthetic",
            "name": "Synthetic Talent",
            "source_packet_ids": ["packet.public.talent"],
        },
    ]
    packets = [
        _public_packet(
            "packet.public.path",
            path_id,
            path_name,
            proof["index_path"],
            proof["index_sha256"],
            f"path:{path_id}",
            target_cl=1,
        ),
        _public_packet(
            "packet.public.asi.4",
            asi_id,
            "Ability Score Improvement or Cultivation Insight",
            proof["index_path"],
            proof["index_sha256"],
            f"path-feature:{path_id}:{asi_id}",
            target_cl=4,
        ),
        _public_packet(
            "packet.public.subpath.6",
            subpath_id,
            "Subpath Feature",
            proof["index_path"],
            proof["index_sha256"],
            f"path-feature:{path_id}:{subpath_id}",
            target_cl=6,
        ),
        _public_packet(
            "packet.public.asi.8",
            asi_id,
            "Ability Score Improvement or Cultivation Insight",
            proof["index_path"],
            proof["index_sha256"],
            f"path-feature:{path_id}:{asi_id}",
            target_cl=8,
        ),
        _public_packet(
            "packet.public.talent",
            "tianxia.talent.public.synthetic",
            "Synthetic Talent",
            proof["index_path"],
            proof["index_sha256"],
            "path-feature:tianxia.path.qi_cultivation:tianxia.talent.public.synthetic",
            target_cl=1,
        ),
        _public_packet(
            "packet.public.background",
            "tianxia.background.abandoned_orphan",
            "Abandoned Orphan",
            proof["index_path"],
            proof["index_sha256"],
            "record:tianxia.background.abandoned_orphan",
            target_cl=1,
        ),
        _public_packet(
            "packet.public.origin",
            "tianxia.origin_insight.born_under_suspicion",
            "Born Under Suspicion",
            proof["index_path"],
            proof["index_sha256"],
            "record:tianxia.origin_insight.born_under_suspicion",
            target_cl=1,
        ),
    ]
    packets[0]["advancement_kind"] = "path_acquisition"
    packets[-2]["advancement_kind"] = "background_acquisition"
    packets[-1]["advancement_kind"] = "origin_insight_acquisition"
    workspace = tmp_path / "public-path-projection-workspace"
    (workspace / "Build").mkdir(parents=True)
    (workspace / "Command_2").mkdir()
    ledger = {
        "schema_version": "HF05ZVK-R1F",
        "character": {
            "path": path_name,
            "path_id": path_id,
            "key_ability": "INT",
            "cl": 15,
            "paths": [deepcopy(path_row)],
        },
        "path_selections": [deepcopy(path_row)],
        "core_stats": {
            "ability_scores": {
                "STR": 10,
                "DEX": 14,
                "CON": 13,
                "INT": 18,
                "WIS": 12,
                "CHA": 8,
            },
            "ability_modifiers": {
                "STR": 0,
                "DEX": 2,
                "CON": 1,
                "INT": 4,
                "WIS": 1,
                "CHA": -1,
            },
        },
        "features": features,
    }
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    raw = ledger_path.read_bytes()
    (workspace / "Command_2/Rules_Selection_Packets.json").write_text(
        json.dumps({"packets": packets}, sort_keys=True) + "\n", encoding="utf-8"
    )
    return workspace, raw, ledger


def _public_multi_path_projection_workspace(
    tmp_path: Path,
    pair: tuple[str, str],
) -> tuple[Path, bytes, dict[str, Any]]:
    """Build two source-backed Paths with independent targets and milestones."""

    workspace = tmp_path / "public-multi-path-projection-workspace"
    (workspace / "Build").mkdir(parents=True)
    (workspace / "Command_2").mkdir()
    key_abilities = {
        "body_refining": "CON",
        "qi_cultivation": "INT",
        "spirit_awakening": "WIS",
    }
    paths: list[dict[str, Any]] = []
    features: list[dict[str, Any]] = []
    packets: list[dict[str, Any]] = []
    for position, short_name in enumerate(pair):
        path_id = f"tianxia.path.{short_name}"
        proof = materializer._PACKET_PATH_PROOFS[path_id]
        index = materializer._bridge_fixed_json(proof["index_path"], proof["index_sha256"])
        assert isinstance(index, Mapping)
        path_name = index["display_name"]
        target_cl = 8 if position == 0 else 15
        path_packet_id = f"packet.public.{short_name}.path"
        path_row = {
            "display_name": path_name,
            "effective_cl": target_cl,
            "key_ability": key_abilities[short_name],
            "path_id": path_id,
            "selected_skills": [],
            "source_packet_ids": [path_packet_id],
        }
        paths.append(path_row)
        path_packet = _public_packet(
            path_packet_id,
            path_id,
            path_name,
            proof["index_path"],
            proof["index_sha256"],
            f"path:{path_id}",
        )
        path_packet["advancement_kind"] = "path_acquisition"
        packets.append(path_packet)
        authority = next(
            feature
            for feature in index["features"]
            if isinstance(feature, Mapping)
            and 4 in feature.get("granted_at_cl", [])
            and 8 in feature.get("granted_at_cl", [])
        )
        feature_id = authority["canonical_id"]
        feature_name = authority["display_name"]
        for gained_at_cl in (4, 8):
            packet_id = f"packet.public.{short_name}.milestone.{gained_at_cl}"
            features.append(
                {
                    "category": "path_feature",
                    "feature_id": feature_id,
                    "name": feature_name,
                    "gained_at_cl": gained_at_cl,
                    "allocation_id": f"allocation.public.{short_name}.{gained_at_cl}",
                    "source_packet_ids": [packet_id],
                }
            )
            feature_packet = _public_packet(
                packet_id,
                feature_id,
                feature_name,
                proof["index_path"],
                proof["index_sha256"],
                f"path-feature:{path_id}:{feature_id}",
                target_cl=gained_at_cl,
            )
            feature_packet["advancement_kind"] = "path_feature_acquisition"
            packets.append(feature_packet)
    features.append(
        {
            "category": "talent",
            "feature_id": "tianxia.talent.public.synthetic",
            "name": "Synthetic Talent",
            "source_packet_ids": ["packet.public.talent"],
        }
    )
    primary = paths[0]
    ledger = {
        "schema_version": "HF05ZVK-R1F",
        "character": {
            "path": primary["display_name"],
            "path_id": primary["path_id"],
            "key_ability": primary["key_ability"],
            "cl": 15,
            "paths": deepcopy(paths),
        },
        "path_selections": deepcopy(paths),
        "core_stats": {"untouched": "No calculations belong to this adapter."},
        "features": features,
    }
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    raw = ledger_path.read_bytes()
    (workspace / "Command_2/Rules_Selection_Packets.json").write_text(
        json.dumps({"packets": packets}, sort_keys=True) + "\n", encoding="utf-8"
    )
    return workspace, raw, ledger


def _public_realm_projection_workspace(tmp_path: Path) -> tuple[Path, bytes, dict[str, Any], dict[str, Any]]:
    """Build a public-safe, source-bound CL15 progression for realm tests."""

    workspace, _raw, ledger = _public_path_projection_workspace(tmp_path)
    path_id = "tianxia.path.qi_cultivation"
    proof = materializer._PACKET_PATH_PROOFS[path_id]
    fixed_index = materializer._bridge_fixed_json(proof["index_path"], proof["index_sha256"])
    assert isinstance(fixed_index, Mapping)
    fixed_features = {
        row["canonical_id"]: row
        for row in fixed_index["features"]
        if isinstance(row, Mapping)
    }
    feature_ids_by_cl = [
        "tianxia.path.qi_cultivation.feature.cultivated_response",
        "tianxia.path.qi_cultivation.feature.meridian_regulation",
        "tianxia.path.qi_cultivation.feature.qi_cultivation_subpath",
        "tianxia.path.qi_cultivation.feature.ability_score_improvement_or_cultivation_insight",
        "tianxia.path.qi_cultivation.feature.qi_armor",
        "tianxia.path.qi_cultivation.feature.subpath_feature",
        "tianxia.path.qi_cultivation.feature.featherfall",
        "tianxia.path.qi_cultivation.feature.ability_score_improvement_or_cultivation_insight",
        "tianxia.path.qi_cultivation.feature.domain_armament",
        "tianxia.path.qi_cultivation.feature.golden_core_form",
        "tianxia.path.qi_cultivation.feature.golden_core_efficiency",
        "tianxia.path.qi_cultivation.feature.ability_score_improvement_or_cultivation_insight",
        "tianxia.path.qi_cultivation.feature.domain_armament_link",
        "tianxia.path.qi_cultivation.feature.subpath_feature",
        "tianxia.path.qi_cultivation.feature.nascent_soul",
    ]
    path_packet = "packet.public.realm.path"
    path_row = {
        "display_name": "Qi Cultivation",
        "effective_cl": 15,
        "key_ability": "INT",
        "path_id": path_id,
        "selected_skills": [],
        "source_packet_ids": [path_packet],
    }
    events: list[dict[str, Any]] = []
    packets: list[dict[str, Any]] = [
        _public_packet(
            path_packet,
            path_id,
            "Qi Cultivation",
            proof["index_path"],
            proof["index_sha256"],
            f"path:{path_id}",
        )
    ]
    for cl, feature_id in enumerate(feature_ids_by_cl, start=1):
        fixed = fixed_features[feature_id]
        event_id = f"event.public.realm.{cl}"
        packet_id = f"packet.public.realm.feature.{cl}"
        name = fixed["display_name"]
        events.append({
            "category": "path_feature",
            "feature_id": feature_id,
            "name": name,
            "gained_at_cl": cl,
            "allocation_id": f"allocation.public.realm.{cl}",
            "source_packet_ids": [packet_id],
        })
        packet = _public_packet(
            packet_id,
            feature_id,
            name,
            proof["index_path"],
            proof["index_sha256"],
            f"path-feature:{path_id}:{feature_id}",
            target_cl=cl,
        )
        packet.update({"advancement_kind": "level_advance", "event_id": event_id})
        packets.append(packet)

    levels = [
        {
            "cl": cl,
            "event_id": f"event.public.realm.{cl}",
            "feature_record_id": feature_id,
            "realm": "Mortal",
        }
        for cl, feature_id in enumerate(feature_ids_by_cl, start=1)
    ]
    ledger["character"].update({"path": "Qi Cultivation", "path_id": path_id, "key_ability": "INT", "cl": 15, "realm": "Mortal", "paths": [deepcopy(path_row)]})
    ledger["path_selections"] = [deepcopy(path_row)]
    ledger["features"] = events
    ledger["advancement"] = {"levels": levels}
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    raw = ledger_path.read_bytes()
    (workspace / "Command_2/Rules_Selection_Packets.json").write_text(
        json.dumps({"packets": packets}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return workspace, raw, ledger, _public_translation()


def _public_translation(*levels: int) -> dict[str, Any]:
    """A translator result for controller-built Arts gained at ``levels``."""

    arts = []
    allocations: dict[str, list[dict[str, Any]]] = {}
    for level in levels or (15,):
        art_id = f"tianxia.constructed.immortal_art.public.{level}"
        realm = "Immortal" if level >= 20 else "Nascent Soul"
        arts.append({"immortal_art_id": art_id, "gained_at_cl": level, "realm": realm})
        allocations[str(level)] = [{
            "allocation_id": f"allocation.immortal_art.public.{level}",
            "channel": "immortal_art",
            "grant_type": "immortal_art",
            "grant_id": art_id,
            "name": f"Public Art {level}",
            "cl": level,
            "at_cl": level,
            "realm": realm,
            "slot_cost": 0,
        }]
    return {"arts": arts, "allocations_by_cl": allocations}


def _apply_public_translation(workspace: Path, translation: dict[str, Any]) -> None:
    """Append the translator's allocations as ``translate_constructed_immortal_arts`` would."""

    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    for level in ledger["advancement"]["levels"]:
        rows = translation["allocations_by_cl"].get(str(level["cl"]), [])
        if rows:
            level["allocations"] = [*level.get("allocations", []), *deepcopy(rows)]
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")


@_REQUIRES_VENDOR_FIXTURE
def test_modern_realm_projection_derives_compiler_bands_and_preserves_raw_ledger(
    tmp_path: Path,
) -> None:
    workspace, raw, _ledger, artifact = _public_realm_projection_workspace(tmp_path)
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    raw_provenance = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    raw_bytes = raw_provenance.read_bytes()
    _apply_public_translation(workspace, artifact)
    realm_projection = materializer._project_modern_realm_for_compiler(
        workspace,
        path_projection=path_projection,
        immortal_translation=artifact,
    )
    projected = json.loads((workspace / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8"))
    assert projected["character"]["realm"] == "Nascent Soul"
    assert [row["realm"] for row in projected["advancement"]["levels"]] == (
        ["Mortal"] * 4
        + ["Foundation"] * 5
        + ["Core Formation"] * 5
        + ["Nascent Soul"]
    )
    assert raw_provenance.read_bytes() == raw_bytes == raw
    assert realm_projection["current_realm"] == "Nascent Soul"
    assert realm_projection["target_cl"] == 15
    assert realm_projection["level_count"] == 15
    details = json.loads(
        (workspace / realm_projection["details_path"]).read_text(encoding="utf-8")
    )
    assert details["source_ledger_sha256"] == materializer.sha256_file(raw_provenance)
    assert details["realm_by_cl"]["15"] == "Nascent Soul"
    assert details["immortal_acquisitions"] == [
        {"immortal_art_id": "tianxia.constructed.immortal_art.public.15", "gained_at_cl": 15, "realm": "Nascent Soul"}
    ]


def test_modern_realm_projection_accepts_exact_translated_allocation(
    tmp_path: Path,
) -> None:
    workspace, _raw, _ledger, artifact = _public_realm_projection_workspace(tmp_path)
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    _apply_public_translation(workspace, artifact)
    projection = materializer._project_modern_realm_for_compiler(
        workspace,
        path_projection=path_projection,
        immortal_translation=artifact,
    )
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    projected = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert projected["advancement"]["levels"][-1]["allocations"] == artifact["allocations_by_cl"]["15"]
    assert projected["advancement"]["levels"][-1]["realm"] == "Nascent Soul"
    assert projection["immortal_acquired_at_cls"] == [15]


def test_modern_realm_projection_rejects_forged_translated_allocation(
    tmp_path: Path,
) -> None:
    workspace, _raw, _ledger, artifact = _public_realm_projection_workspace(tmp_path)
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    forged = deepcopy(artifact)
    forged["allocations_by_cl"]["15"][0]["allocation_id"] = "allocation.public.forged"
    _apply_public_translation(workspace, forged)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    before = ledger_path.read_bytes()
    with pytest.raises(FoundryError) as error:
        materializer._project_modern_realm_for_compiler(
            workspace,
            path_projection=path_projection,
            immortal_translation=artifact,
        )
    assert error.value.code == "FINAL_CHARACTER_REALM_PROJECTION_INVALID"
    assert ledger_path.read_bytes() == before
    assert not (workspace / materializer._REALM_PROJECTION_DETAILS_RELATIVE).exists()


def test_modern_realm_projection_rejects_two_arts_at_one_cl(
    tmp_path: Path,
) -> None:
    """RAW-183: at most one new Immortal Art is gained at each CL."""

    workspace, _raw, _ledger, artifact = _public_realm_projection_workspace(tmp_path)
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    second = deepcopy(artifact["allocations_by_cl"]["15"][0])
    second.update(allocation_id="allocation.immortal_art.public.second", grant_id="tianxia.constructed.immortal_art.second")
    artifact["allocations_by_cl"]["15"].append(second)
    artifact["arts"].append({"immortal_art_id": "tianxia.constructed.immortal_art.second", "gained_at_cl": 15, "realm": "Nascent Soul"})
    _apply_public_translation(workspace, artifact)
    with pytest.raises(FoundryError) as error:
        materializer._project_modern_realm_for_compiler(
            workspace,
            path_projection=path_projection,
            immortal_translation=artifact,
        )
    assert error.value.code == "FINAL_CHARACTER_REALM_PROJECTION_INVALID"


def test_modern_realm_projection_rejects_missing_immortal_proof_without_mutation(
    tmp_path: Path,
) -> None:
    workspace, _raw, _ledger, artifact = _public_realm_projection_workspace(tmp_path)
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    before = (workspace / "Build/Character_Master_Ledger.json").read_bytes()
    # RAW-182: a CL15+ character without an Immortal Art has no realm proof.
    artifact = {"arts": [], "allocations_by_cl": {}}
    with pytest.raises(FoundryError) as error:
        materializer._project_modern_realm_for_compiler(
            workspace,
            path_projection=path_projection,
            immortal_translation=artifact,
        )
    assert error.value.code == "FINAL_CHARACTER_REALM_PROJECTION_INVALID"
    assert (workspace / "Build/Character_Master_Ledger.json").read_bytes() == before
    assert not (workspace / materializer._REALM_PROJECTION_DETAILS_RELATIVE).exists()


@pytest.mark.parametrize(
    "mutator",
    [
        lambda ledger: ledger["advancement"]["levels"].pop(7),
        lambda ledger: ledger["advancement"]["levels"][-1].update(realm="Foundation"),
    ],
)
def test_modern_realm_projection_rejects_gaps_or_conflicting_realms(
    tmp_path: Path,
    mutator: Any,
) -> None:
    workspace, _raw, ledger, artifact = _public_realm_projection_workspace(tmp_path)
    mutator(ledger)
    (workspace / "Build/Character_Master_Ledger.json").write_text(
        json.dumps(ledger, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    before = (workspace / "Build/Character_Master_Ledger.json").read_bytes()
    with pytest.raises(FoundryError) as error:
        materializer._project_modern_realm_for_compiler(
            workspace,
            path_projection=path_projection,
            immortal_translation=artifact,
        )
    assert error.value.code == "FINAL_CHARACTER_REALM_PROJECTION_INVALID"
    assert (workspace / "Build/Character_Master_Ledger.json").read_bytes() == before
    assert not (workspace / materializer._REALM_PROJECTION_DETAILS_RELATIVE).exists()


def _public_hp_projection_workspace(
    tmp_path: Path,
) -> tuple[Path, bytes, dict[str, Any], dict[str, Any], str]:
    """Build a public-safe Qi HP progression with one authenticated ASI change."""

    workspace, _raw, ledger, artifact = _public_realm_projection_workspace(tmp_path)
    path_id = "tianxia.path.qi_cultivation"
    proof = materializer._PACKET_PATH_PROOFS[path_id]
    final_scores = {
        "STR": 10,
        "DEX": 14,
        "CON": 15,
        "INT": 18,
        "WIS": 12,
        "CHA": 8,
    }
    ledger["core_stats"]["ability_scores"] = deepcopy(final_scores)
    ledger["core_stats"]["ability_modifiers"] = {
        "STR": 0,
        "DEX": 2,
        "CON": 2,
        "INT": 4,
        "WIS": 1,
        "CHA": -1,
    }
    maximum = 0
    generation_levels: list[dict[str, Any]] = []
    for cl, level in enumerate(ledger["advancement"]["levels"], start=1):
        scores_after = deepcopy(final_scores)
        scores_after["CON"] = 13 if cl < 9 else 15
        level["ability_scores_after"] = scores_after
        base_gain = 8 if cl == 1 else 5
        constitution_delta = 1 if cl < 9 else 2
        gain = base_gain + constitution_delta
        other_delta = 8 if cl == 9 else 0
        maximum += gain + other_delta
        formula_id = f"ns1r.{path_id}.hp.cl1" if cl == 1 else f"ns1r.{path_id}.hp.later"
        level["hp"] = {
            "formula_id": formula_id,
            "gain": gain,
            "max_after_level": maximum,
        }
        generation_levels.append({
            "cl": cl,
            "formula_id": formula_id,
            "gain": gain,
            "maximum": maximum,
        })
    ledger["core_stats"]["hp_max"] = maximum
    ledger["core_stats"]["hp_current"] = maximum
    ledger["core_stats"]["hp_generation"] = {"levels": generation_levels}
    asi_id = f"{path_id}.feature.ability_score_improvement_or_cultivation_insight"
    change_packet_id = "packet.public.hp.asi-change"
    change_packet = _public_packet(
        change_packet_id,
        asi_id,
        "Ability Score Improvement or Cultivation Insight",
        proof["index_path"],
        proof["index_sha256"],
        f"path-feature:{path_id}:{asi_id}",
        target_cl=8,
    )
    change_packet.update({
        "advancement_kind": "ability_score_change",
        "event_id": "event.public.hp.asi-change",
    })
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    packets_path = workspace / "Command_2/Rules_Selection_Packets.json"
    packets = json.loads(packets_path.read_text(encoding="utf-8"))
    packets["packets"].append(change_packet)
    packets_path.write_text(json.dumps(packets, sort_keys=True) + "\n", encoding="utf-8")
    return workspace, ledger_path.read_bytes(), ledger, artifact, change_packet_id


def _public_hp_foundation_projection_workspace(
    tmp_path: Path,
) -> tuple[Path, bytes, str, str]:
    """Add an authenticated initial Heaven Foundation to the HP timeline."""

    from non_sphere_authority.foundation_mechanics import (
        installed_foundation_state,
        resolve_initial_foundation_mechanics,
        verified_foundation_records,
    )

    workspace, _raw, ledger, _artifact, change_packet_id = _public_hp_projection_workspace(tmp_path)
    foundation_id = "heaven_devouring_shedding_womb_v0_2B"
    foundation_packet_id = "packet.public.hp.foundation"
    event_id = "event.public.hp.foundation"
    record_hash = "d" * 64
    source_record = verified_foundation_records()[foundation_id]
    selected_path_ids = [row["path_id"] for row in ledger["character"]["paths"]]
    mechanics = resolve_initial_foundation_mechanics(
        source_record,
        selected_path_ids,
        stage="Awakened",
    )
    foundation = installed_foundation_state(mechanics, foundation_id, event_id)
    foundation.update(
        {
            "display_name": source_record["display_name"],
            "record_hash": record_hash,
            "source_packet_ids": [foundation_packet_id],
            "mechanical_projection": True,
            "acquisition_event_id": event_id,
            "mechanics_schema": mechanics["schema"],
            "stage": "Awakened",
            "mechanics": mechanics,
        }
    )
    foundation["resource"]["current"] = 1
    ledger["foundation"] = deepcopy(foundation)

    # The Foundation's +PB maximum is a cumulative flat contribution.  It
    # changes only at acquisition and proficiency-bonus thresholds; the CL8
    # Constitution ASI remains a separate retroactive contribution.
    for cl, level in enumerate(ledger["advancement"]["levels"], start=1):
        hp = level["hp"]
        foundation_total = 2 + (cl - 1) // 4 if cl >= 5 else 0
        hp["max_after_level"] += foundation_total
        ledger["core_stats"]["hp_generation"]["levels"][cl - 1]["maximum"] = hp["max_after_level"]
    maximum = ledger["advancement"]["levels"][-1]["hp"]["max_after_level"]
    ledger["core_stats"]["hp_max"] = maximum
    ledger["core_stats"]["hp_current"] = maximum

    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    raw = ledger_path.read_bytes()
    (workspace / "Build/Foundation_Detail_Ledger.json").write_text(
        json.dumps(
            {
                "schema_version": "TianxiaFoundry.CharacterGMFoundation.v1",
                "foundation": deepcopy(foundation),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    registry_path = workspace / "Command_2/Rules_Selection_Packets.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["schema_version"] = "TianxiaFoundry.RulesSelectionPackets.v2"
    source = source_record["source"]
    registry["packets"].append(
        {
            "packet_id": foundation_packet_id,
            "record_id": foundation_id,
            "display_name": source_record["display_name"],
            "target_cl": 5,
            "advancement_kind": "foundation_acquisition",
            "event_id": event_id,
            "record_hash": record_hash,
            "content_binding": {
                "pack_id": "tianxia.non_sphere.authority",
                "pack_version": "0.4C-mechanics.1",
                "record_hash": record_hash,
            },
            "full_description": source_record["summary"],
            "short_description": source_record["summary"][:500],
            "source_evidence": [
                {
                    "source_id": f"source.{source['artifact_sha256'][:24]}",
                    "source_path": source["artifact"],
                    "source_hash": source["artifact_sha256"],
                    "source_anchor": f"foundation:{foundation_id}",
                }
            ],
        }
    )
    registry_path.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")
    return workspace, raw, foundation_packet_id, change_packet_id


def test_modern_hp_projection_derives_fixed_average_and_authenticated_retroactive_delta(
    tmp_path: Path,
) -> None:
    workspace, raw, original, _artifact, change_packet_id = _public_hp_projection_workspace(tmp_path)
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    raw_provenance = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    projection = materializer._project_modern_hp_for_compiler(
        workspace,
        path_projection=path_projection,
    )
    projected = json.loads((workspace / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8"))
    assert projected["core_stats"]["hp_generation"] == {
        "hit_die": "d8",
        "mode": "fixed_average",
    }
    assert projected["core_stats"]["hp_generation_provenance"] == original["core_stats"]["hp_generation"]
    assert projected["core_stats"]["hp_max"] == 108
    assert projected["advancement"]["levels"][0]["hp"] == {
        "base_gain": 8,
        "constitution_delta": 1,
        "gain": 9,
        "max_after_level": 9,
        "formula_id": "ns1r.tianxia.path.qi_cultivation.hp.cl1",
        "other_delta": 0,
    }
    assert projected["advancement"]["levels"][8]["hp"] == {
        "base_gain": 5,
        "constitution_delta": 2,
        "gain": 7,
        "max_after_level": 66,
        "formula_id": "ns1r.tianxia.path.qi_cultivation.hp.later",
        "other_delta": 8,
        "source_packet_ids": [change_packet_id],
    }
    assert projection["retroactive_packet_id"] == change_packet_id
    assert projection["retroactive_allocation_id"] == "allocation.public.realm.8"
    assert raw_provenance.read_bytes() == raw
    details = json.loads((workspace / projection["details_path"]).read_text(encoding="utf-8"))
    assert details["other_delta_by_cl"]["9"] == 8
    assert details["retroactive_authority"]["source_target_cl"] == 8
    assert projection["details_sha256"] == materializer.sha256_file(workspace / projection["details_path"])


def test_modern_hp_projection_applies_foundation_flat_maximum_once(
    tmp_path: Path,
) -> None:
    """A source-bound Foundation HP bonus follows PB thresholds without stacking per level."""

    workspace, raw, foundation_packet_id, change_packet_id = _public_hp_foundation_projection_workspace(tmp_path)
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    foundation_projection = materializer._project_foundation_for_compiler(workspace)
    projection = materializer._project_modern_hp_for_compiler(
        workspace,
        path_projection=path_projection,
        foundation_projection=foundation_projection,
    )
    projected = json.loads((workspace / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8"))
    levels = projected["advancement"]["levels"]
    assert [levels[index - 1]["hp"]["other_delta"] for index in (5, 9, 13)] == [3, 9, 1]
    assert levels[4]["hp"]["source_packet_ids"] == [foundation_packet_id]
    assert levels[8]["hp"]["source_packet_ids"] == [foundation_packet_id, change_packet_id]
    assert projected["core_stats"]["hp_max"] == 113
    assert (workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE).read_bytes() == raw
    assert projection["foundation_adjustment_by_cl"] == {
        "5": 3,
        "9": 1,
        "13": 1,
    }


def test_modern_realm_projection_accepts_raw_secondary_hp_after_compiler_projection(
    tmp_path: Path,
) -> None:
    """Secondary advancement corroboration remains raw while the master HP is projected."""

    workspace, _raw, original, artifact, _change_packet_id = _public_hp_projection_workspace(tmp_path)
    (workspace / "Command_2/Canonical_Advancement_Ledger.json").write_text(
        json.dumps({"levels": deepcopy(original["advancement"]["levels"])}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    hp_projection = materializer._project_modern_hp_for_compiler(
        workspace,
        path_projection=path_projection,
    )
    _apply_public_translation(workspace, artifact)
    realm_projection = materializer._project_modern_realm_for_compiler(
        workspace,
        path_projection=path_projection,
        immortal_translation=artifact,
        hp_projection=hp_projection,
    )
    assert realm_projection["current_realm"] == "Nascent Soul"
    secondary = json.loads(
        (workspace / "Command_2/Canonical_Advancement_Ledger.json").read_text(encoding="utf-8")
    )
    assert "base_gain" not in secondary["levels"][0]["hp"]


def test_modern_hp_projection_preserves_existing_exact_compiler_shape(
    tmp_path: Path,
) -> None:
    workspace, _raw, _original, _artifact, change_packet_id = _public_hp_projection_workspace(tmp_path)
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["core_stats"]["hp_generation"] = {
        "hit_die": "d8",
        "mode": "fixed_average",
    }
    for index, level in enumerate(ledger["advancement"]["levels"], start=1):
        hp = level["hp"]
        hp.update({
            "base_gain": 8 if index == 1 else 5,
            "constitution_delta": 1 if index < 9 else 2,
            "other_delta": 8 if index == 9 else 0,
        })
        if index == 9:
            hp["source_packet_ids"] = [change_packet_id]
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    projection = materializer._project_modern_hp_for_compiler(
        workspace,
        path_projection=path_projection,
    )
    projected = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert projected["core_stats"]["hp_generation"] == {"hit_die": "d8", "mode": "fixed_average"}
    assert "hp_generation_provenance" not in projected["core_stats"]
    assert projection["compiler_levels"][8]["other_delta"] == 8


@pytest.mark.parametrize(
    "mutator",
    [
        lambda ledger, _packets: ledger["advancement"]["levels"][8]["ability_scores_after"].update(CON=14),
        lambda ledger, _packets: ledger["advancement"]["levels"][8]["hp"].update(max_after_level=67),
        lambda ledger, _packets: ledger["advancement"]["levels"].pop(7),
        lambda _ledger, packets: packets["packets"].pop(),
    ],
)
def test_modern_hp_projection_rejects_tampered_or_incomplete_progression(
    tmp_path: Path,
    mutator: Any,
) -> None:
    workspace, _raw, ledger, _artifact, _change_packet_id = _public_hp_projection_workspace(tmp_path)
    packets_path = workspace / "Command_2/Rules_Selection_Packets.json"
    packets = json.loads(packets_path.read_text(encoding="utf-8"))
    mutator(ledger, packets)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    packets_path.write_text(json.dumps(packets, sort_keys=True) + "\n", encoding="utf-8")
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    before = ledger_path.read_bytes()
    with pytest.raises(FoundryError) as error:
        materializer._project_modern_hp_for_compiler(
            workspace,
            path_projection=path_projection,
        )
    assert error.value.code == "FINAL_CHARACTER_HP_PROJECTION_INVALID"
    assert ledger_path.read_bytes() == before
    assert not (workspace / materializer._HP_PROJECTION_DETAILS_RELATIVE).exists()


@pytest.mark.parametrize(
    ("label", "current_value"),
    (("negative", -1), ("above_maximum", 109), ("boolean", True)),
)
def test_modern_hp_projection_rejects_invalid_current_without_mutation(
    tmp_path: Path,
    label: str,
    current_value: Any,
) -> None:
    workspace, _raw, ledger, _artifact, _change_packet_id = _public_hp_projection_workspace(tmp_path / label)
    ledger["core_stats"]["hp_current"] = current_value
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    before = {path: path.read_bytes() for path in (ledger_path, raw_path)}
    with pytest.raises(FoundryError) as error:
        materializer._project_modern_hp_for_compiler(
            workspace,
            path_projection=path_projection,
        )
    assert error.value.code == "FINAL_CHARACTER_HP_PROJECTION_INVALID"
    assert {path: path.read_bytes() for path in (ledger_path, raw_path)} == before
    assert not (workspace / materializer._HP_PROJECTION_DETAILS_RELATIVE).exists()


def test_modern_hp_projection_preserves_valid_spent_current(tmp_path: Path) -> None:
    workspace, _raw, ledger, _artifact, _change_packet_id = _public_hp_projection_workspace(tmp_path)
    ledger["core_stats"]["hp_current"] = 42
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    raw_before = raw_path.read_bytes()
    materializer._project_modern_hp_for_compiler(
        workspace,
        path_projection=path_projection,
    )
    projected = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert projected["core_stats"]["hp_current"] == 42
    assert raw_path.read_bytes() == raw_before


def _add_public_skill_projection(ledger: dict[str, Any], *, adjustments: Mapping[str, Any] | None = None) -> None:
    ledger["character"]["pb"] = 5
    ledger["core_stats"].update(
        {
            "skills": {
                "Arcana": 9,
                "Deception": 9,
                "Medicine": 6,
                "Sleight of Hand": 7,
            },
            "skill_ability_map": {
                "Arcana": "INT",
                "Deception": "CHA",
                "Medicine": "WIS",
                "Sleight of Hand": "DEX",
            },
            "skill_proficiency_multipliers": {
                "Arcana": 1,
                "Deception": 2,
                "Medicine": 1,
                "Sleight of Hand": 1,
            },
            "skill_sources": {
                "Arcana": ["tianxia.path.qi_cultivation"],
                "Deception": [
                    "tianxia.background.abandoned_orphan",
                    "tianxia.origin_insight.born_under_suspicion",
                ],
                "Medicine": ["tianxia.path.qi_cultivation"],
                "Sleight of Hand": ["tianxia.background.abandoned_orphan"],
            },
        }
    )
    if adjustments is not None:
        ledger["core_stats"]["skill_adjustments"] = dict(adjustments)


def _add_public_ac_generation(
    ledger: dict[str, Any],
    *,
    dex_score: int = 14,
    dexterity_modifier: int = 2,
    pending: list[str] | None = None,
) -> None:
    """Add the source-shaped unarmored AC trace used by the AC projection tests."""

    ac_total = 10 + dexterity_modifier
    ledger["core_stats"]["ability_scores"]["DEX"] = dex_score
    ledger["core_stats"]["ability_modifiers"]["DEX"] = dexterity_modifier
    ledger["core_stats"].update(
        {
            "ac_base": ac_total,
            "ac_active": ac_total,
            "ac_generation": {
                "calculation": "unarmored_base",
                "conditional_bonuses_pending_execution": (
                    ["tianxia.path.qi_cultivation.feature.qi_armor"]
                    if pending is None
                    else list(pending)
                ),
                "formula_id": "tianxia.core.baseline.unarmored_ac.owner_r1",
                "trace": {
                    "node_count": 3,
                    "root": {
                        "op": "add",
                        "terms": [
                            {"op": "constant", "value": 10},
                            {
                                "ability": "DEX",
                                "op": "ability_modifier",
                                "value": dexterity_modifier,
                            },
                        ],
                        "value": ac_total,
                    },
                    "schema_version": "TianxiaFoundry.SafeFormulaTrace.v1",
                },
            },
        }
    )


def _add_public_speed_generation(
    ledger: dict[str, Any],
    workspace: Path,
    *,
    speed_ft: int = 30,
    generation: Mapping[str, Any] | None = None,
) -> None:
    """Add the fixed source-shaped walking-speed trace and provenance row."""

    ledger["core_stats"].update(
        {
            "speed_ft": speed_ft,
            "speed_generation": dict(
                generation
                if generation is not None
                else {"mode": "walking", "rule_id": materializer._SPEED_RULE_ID}
            ),
        }
    )
    map_path = workspace / "Build/Projection_Provenance_Map.json"
    projection_map = (
        json.loads(map_path.read_text(encoding="utf-8"))
        if map_path.exists()
        else {"mappings": {}}
    )
    projection_map.setdefault("mappings", {})[
        f"baseline:{materializer._SPEED_RULE_ID}"
    ] = deepcopy(materializer._SPEED_PROVENANCE_MAPPING)
    map_path.write_text(
        json.dumps(projection_map, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _mutate_public_speed_provenance(workspace: Path) -> None:
    path = workspace / "Build/Projection_Provenance_Map.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["mappings"][f"baseline:{materializer._SPEED_RULE_ID}"]["transformation_kind"] = "INDIRECT"
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _add_public_initiative_generation(
    ledger: dict[str, Any],
    workspace: Path,
    *,
    initiative_bonus: int = 2,
    generation: Mapping[str, Any] | None = None,
) -> None:
    ledger["core_stats"].update(
        {
            "initiative_bonus": initiative_bonus,
            "initiative_generation": dict(
                generation
                if generation is not None
                else {
                    "ability": "DEX",
                    "check": "1d20",
                    "formula_id": materializer._INITIATIVE_FORMULA_ID,
                    "situational_advantage_sources": [
                        materializer._INITIATIVE_ADVANTAGE_SOURCE
                    ],
                    "trace": {
                        "node_count": 1,
                        "root": {
                            "ability": "DEX",
                            "op": "ability_modifier",
                            "value": 2,
                        },
                        "schema_version": "TianxiaFoundry.SafeFormulaTrace.v1",
                    },
                }
            ),
        }
    )
    map_path = workspace / "Build/Projection_Provenance_Map.json"
    projection_map = (
        json.loads(map_path.read_text(encoding="utf-8"))
        if map_path.exists()
        else {"mappings": {}}
    )
    projection_map.setdefault("mappings", {})[
        f"baseline:{materializer._INITIATIVE_RULE_ID}"
    ] = deepcopy(materializer._INITIATIVE_PROVENANCE_MAPPING)
    map_path.write_text(json.dumps(projection_map, sort_keys=True) + "\n", encoding="utf-8")


def _mutate_public_initiative_provenance(workspace: Path) -> None:
    path = workspace / "Build/Projection_Provenance_Map.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["mappings"][f"baseline:{materializer._INITIATIVE_RULE_ID}"]["formula_trace"]["root"]["value"] = 3
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def test_modern_ac_projection_derives_compiler_components_and_preserves_trace(
    tmp_path: Path,
) -> None:
    workspace, raw, ledger = _public_path_projection_workspace(tmp_path)
    _add_public_ac_generation(ledger)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    source_bytes = ledger_path.read_bytes()
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    projection = materializer._project_modern_ac_for_compiler(
        workspace,
        path_projection=path_projection,
    )
    projected = json.loads(ledger_path.read_text(encoding="utf-8"))
    generation = projected["core_stats"]["ac_generation"]
    assert generation == {
        "base_ac": 10,
        "dexterity_modifier_applied": 2,
        "shield_adjustment": 0,
        "foundation_adjustment": 0,
        "method_adjustment": 0,
        "item_adjustment": 0,
        "other_adjustment": 0,
        "total": 12,
        "source_grant_ids": [],
    }
    assert projected["core_stats"]["ac_generation_provenance"]["trace"]["root"]["value"] == 12
    assert source_bytes != raw
    assert (workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE).read_bytes() == source_bytes
    assert projection["compiler_generation_mode"] == "source_backed_unarmored_projection"
    details = json.loads(
        (workspace / projection["details_path"]).read_text(encoding="utf-8")
    )
    assert details["compiler_generation"] == generation
    assert details["source_ac_generation"]["conditional_bonuses_pending_execution"] == [
        "tianxia.path.qi_cultivation.feature.qi_armor"
    ]
    assert projection["details_sha256"] == materializer.sha256_file(
        workspace / projection["details_path"]
    )


def test_modern_ac_projection_preserves_existing_exact_compiler_map(
    tmp_path: Path,
) -> None:
    workspace, _raw, ledger = _public_path_projection_workspace(tmp_path)
    _add_public_ac_generation(ledger)
    source_generation = deepcopy(ledger["core_stats"]["ac_generation"])
    ledger["core_stats"]["ac_generation"].update(
        {
            "base_ac": 10,
            "dexterity_modifier_applied": 2,
            "shield_adjustment": 0,
            "foundation_adjustment": 0,
            "method_adjustment": 0,
            "item_adjustment": 0,
            "other_adjustment": 0,
            "total": 12,
            "source_grant_ids": [],
        }
    )
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    projection = materializer._project_modern_ac_for_compiler(
        workspace,
        path_projection=path_projection,
    )
    projected = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert projection["compiler_generation_mode"] == "preserved_existing"
    assert projected["core_stats"]["ac_generation"]["trace"] == source_generation["trace"]
    assert projected["core_stats"]["ac_generation"]["source_grant_ids"] == []


@pytest.mark.parametrize(
    "mutator",
    [
        lambda ledger: ledger["core_stats"].update(ac_base=13),
        lambda ledger: ledger["core_stats"]["ability_modifiers"].update(DEX=3),
        lambda ledger: ledger["core_stats"]["ac_generation"]["trace"]["root"].update(value=13),
        lambda ledger: ledger["core_stats"]["ac_generation"].update(
            conditional_bonuses_pending_execution=["Qi Armor", "Qi Armor"]
        ),
    ],
)
def test_modern_ac_projection_rejects_forged_or_ambiguous_source_trace(
    tmp_path: Path,
    mutator: Any,
) -> None:
    workspace, _raw, ledger = _public_path_projection_workspace(tmp_path)
    _add_public_ac_generation(ledger)
    mutator(ledger)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    before = ledger_path.read_bytes()
    with pytest.raises(FoundryError) as error:
        materializer._project_modern_ac_for_compiler(
            workspace,
            path_projection=path_projection,
        )
    assert error.value.code == "FINAL_CHARACTER_AC_PROJECTION_INVALID"
    assert ledger_path.read_bytes() == before
    assert not (workspace / materializer._AC_PROJECTION_DETAILS_RELATIVE).exists()


def test_modern_ac_projection_rejects_nonzero_existing_unsupported_adjustment(
    tmp_path: Path,
) -> None:
    workspace, _raw, ledger = _public_path_projection_workspace(tmp_path)
    _add_public_ac_generation(ledger)
    ledger["core_stats"]["ac_generation"].update(
        {
            "base_ac": 10,
            "dexterity_modifier_applied": 2,
            "shield_adjustment": 1,
            "foundation_adjustment": 0,
            "method_adjustment": 0,
            "item_adjustment": 0,
            "other_adjustment": 0,
            "total": 13,
            "source_grant_ids": [],
        }
    )
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    with pytest.raises(FoundryError) as error:
        materializer._project_modern_ac_for_compiler(
            workspace,
            path_projection=path_projection,
        )
    assert error.value.code == "FINAL_CHARACTER_AC_PROJECTION_INVALID"


def test_modern_speed_projection_derives_compiler_components_and_preserves_trace(
    tmp_path: Path,
) -> None:
    workspace, _raw, ledger = _public_path_projection_workspace(tmp_path)
    _add_public_speed_generation(ledger, workspace)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    source_bytes = ledger_path.read_bytes()
    projection_map_path = workspace / "Build/Projection_Provenance_Map.json"
    projection_map_bytes = projection_map_path.read_bytes()
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    projection = materializer._project_modern_speed_for_compiler(
        workspace,
        path_projection=path_projection,
    )
    projected = json.loads(ledger_path.read_text(encoding="utf-8"))
    expected_generation = {
        "base_speed": 30,
        "path_adjustment": 0,
        "sphere_adjustment": 0,
        "foundation_adjustment": 0,
        "method_adjustment": 0,
        "equipment_adjustment": 0,
        "other_adjustment": 0,
        "total": 30,
        "source_grant_ids": [],
    }
    assert projected["core_stats"]["speed_ft"] == 30
    assert projected["core_stats"]["speed_generation"] == expected_generation
    assert projected["core_stats"]["speed_generation_provenance"] == {
        "mode": "walking",
        "rule_id": materializer._SPEED_RULE_ID,
    }
    assert source_bytes != ledger_path.read_bytes()
    assert (
        workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    ).read_bytes() == source_bytes
    assert projection_map_path.read_bytes() == projection_map_bytes
    assert projection["compiler_generation_mode"] == "source_backed_walking_speed_projection"
    details = json.loads(
        (workspace / projection["details_path"]).read_text(encoding="utf-8")
    )
    assert details["compiler_generation"] == expected_generation
    assert details["source_speed_generation"] == {
        "mode": "walking",
        "rule_id": materializer._SPEED_RULE_ID,
    }
    assert projection["details_sha256"] == materializer.sha256_file(
        workspace / projection["details_path"]
    )


def test_modern_speed_projection_preserves_existing_exact_compiler_map(
    tmp_path: Path,
) -> None:
    workspace, _raw, ledger = _public_path_projection_workspace(tmp_path)
    compiler_generation = {
        "base_speed": 30,
        "path_adjustment": 0,
        "sphere_adjustment": 0,
        "foundation_adjustment": 0,
        "method_adjustment": 0,
        "equipment_adjustment": 0,
        "other_adjustment": 0,
        "total": 30,
        "source_grant_ids": [],
    }
    _add_public_speed_generation(ledger, workspace, generation=compiler_generation)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    projection = materializer._project_modern_speed_for_compiler(
        workspace,
        path_projection=path_projection,
    )
    projected = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert projection["compiler_generation_mode"] == "preserved_existing"
    assert projected["core_stats"]["speed_generation"] == compiler_generation
    assert "speed_generation_provenance" not in projected["core_stats"]


@pytest.mark.parametrize(
    "mutator",
    [
        lambda ledger, _workspace: ledger["core_stats"].update(speed_ft=31),
        lambda ledger, _workspace: ledger["core_stats"]["speed_generation"].update(mode="flying"),
        lambda ledger, _workspace: ledger["core_stats"]["speed_generation"].update(
            base_speed=30,
            path_adjustment=1,
            sphere_adjustment=0,
            foundation_adjustment=0,
            method_adjustment=0,
            equipment_adjustment=0,
            other_adjustment=0,
            total=31,
            source_grant_ids=[],
        ),
        lambda _ledger, workspace: _mutate_public_speed_provenance(workspace),
    ],
)
def test_modern_speed_projection_rejects_forged_or_unsupported_source(
    tmp_path: Path,
    mutator: Any,
) -> None:
    workspace, _raw, ledger = _public_path_projection_workspace(tmp_path)
    _add_public_speed_generation(ledger, workspace)
    mutator(ledger, workspace)
    (workspace / "Build/Character_Master_Ledger.json").write_text(
        json.dumps(ledger, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    before = (workspace / "Build/Character_Master_Ledger.json").read_bytes()
    with pytest.raises(FoundryError) as error:
        materializer._project_modern_speed_for_compiler(
            workspace,
            path_projection=path_projection,
        )
    assert error.value.code == "FINAL_CHARACTER_SPEED_PROJECTION_INVALID"
    assert (workspace / "Build/Character_Master_Ledger.json").read_bytes() == before
    assert not (workspace / materializer._SPEED_PROJECTION_DETAILS_RELATIVE).exists()


def test_modern_initiative_projection_derives_compiler_components_and_preserves_trace(
    tmp_path: Path,
) -> None:
    workspace, _raw, ledger = _public_path_projection_workspace(tmp_path)
    _add_public_initiative_generation(ledger, workspace)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    source_bytes = ledger_path.read_bytes()
    projection_map_path = workspace / "Build/Projection_Provenance_Map.json"
    projection_map_bytes = projection_map_path.read_bytes()
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    projection = materializer._project_modern_initiative_for_compiler(
        workspace,
        path_projection=path_projection,
    )
    projected = json.loads(ledger_path.read_text(encoding="utf-8"))
    expected_generation = {
        "ability": "DEX",
        "proficiency_multiplier": 0,
        "adjustment": 0,
        "total": 2,
        "source_grant_ids": [],
    }
    assert projected["core_stats"]["initiative_bonus"] == 2
    assert projected["core_stats"]["initiative_generation"] == expected_generation
    assert projected["core_stats"]["initiative_generation_provenance"] == {
        "ability": "DEX",
        "check": "1d20",
        "formula_id": materializer._INITIATIVE_FORMULA_ID,
        "situational_advantage_sources": [materializer._INITIATIVE_ADVANTAGE_SOURCE],
        "trace": {
            "node_count": 1,
            "root": {"ability": "DEX", "op": "ability_modifier", "value": 2},
            "schema_version": "TianxiaFoundry.SafeFormulaTrace.v1",
        },
    }
    assert source_bytes != ledger_path.read_bytes()
    assert (
        workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    ).read_bytes() == source_bytes
    assert projection_map_path.read_bytes() == projection_map_bytes
    assert projection["compiler_generation_mode"] == "source_backed_dex_projection"
    details = json.loads(
        (workspace / projection["details_path"]).read_text(encoding="utf-8")
    )
    assert details["compiler_generation"] == expected_generation
    assert details["source_initiative_generation"]["situational_advantage_sources"] == [
        materializer._INITIATIVE_ADVANTAGE_SOURCE
    ]
    assert projection["details_sha256"] == materializer.sha256_file(
        workspace / projection["details_path"]
    )


def test_modern_initiative_projection_preserves_existing_exact_compiler_map(
    tmp_path: Path,
) -> None:
    workspace, _raw, ledger = _public_path_projection_workspace(tmp_path)
    compiler_generation = {
        "ability": "DEX",
        "proficiency_multiplier": 0,
        "adjustment": 0,
        "total": 2,
        "source_grant_ids": [],
    }
    _add_public_initiative_generation(ledger, workspace, generation=compiler_generation)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    projection = materializer._project_modern_initiative_for_compiler(
        workspace,
        path_projection=path_projection,
    )
    projected = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert projection["compiler_generation_mode"] == "preserved_existing"
    assert projected["core_stats"]["initiative_generation"] == compiler_generation
    assert "initiative_generation_provenance" not in projected["core_stats"]


@pytest.mark.parametrize(
    "mutator",
    [
        lambda ledger, _workspace: ledger["core_stats"].update(initiative_bonus=3),
        lambda ledger, _workspace: ledger["core_stats"]["initiative_generation"].update(
            situational_advantage_sources=[1]
        ),
        lambda ledger, _workspace: ledger["core_stats"]["initiative_generation"].update(
            trace={"node_count": 1, "root": {"ability": "DEX", "op": "ability_modifier", "value": 3}, "schema_version": "TianxiaFoundry.SafeFormulaTrace.v1"}
        ),
        lambda _ledger, workspace: _mutate_public_initiative_provenance(workspace),
    ],
)
def test_modern_initiative_projection_rejects_forged_or_numeric_advantage(
    tmp_path: Path,
    mutator: Any,
) -> None:
    workspace, _raw, ledger = _public_path_projection_workspace(tmp_path)
    _add_public_initiative_generation(ledger, workspace)
    mutator(ledger, workspace)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    before = ledger_path.read_bytes()
    with pytest.raises(FoundryError) as error:
        materializer._project_modern_initiative_for_compiler(
            workspace,
            path_projection=path_projection,
        )
    assert error.value.code == "FINAL_CHARACTER_INITIATIVE_PROJECTION_INVALID"
    assert ledger_path.read_bytes() == before
    assert not (workspace / materializer._INITIATIVE_PROJECTION_DETAILS_RELATIVE).exists()


def test_modern_core_skill_projection_derives_missing_zero_adjustments(
    tmp_path: Path,
) -> None:
    workspace, _raw, ledger = _public_path_projection_workspace(tmp_path)
    _add_public_skill_projection(ledger)
    (workspace / "Build/Character_Master_Ledger.json").write_text(
        json.dumps(ledger, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    projection = materializer._project_modern_core_saves_for_compiler(
        workspace,
        path_projection=path_projection,
    )
    projected = json.loads(
        (workspace / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8")
    )
    expected = {name: 0 for name in ledger["core_stats"]["skills"]}
    assert projected["core_stats"]["skill_adjustments"] == expected
    assert projection["skill_adjustments"] == expected
    assert projection["skill_adjustments_mode"] == "source_backed_explicit_none"
    assert projected["core_stats"]["skill_sources"] == {
        "Arcana": "tianxia.path.qi_cultivation",
        "Deception": "tianxia.background.abandoned_orphan; tianxia.origin_insight.born_under_suspicion",
        "Medicine": "tianxia.path.qi_cultivation",
        "Sleight of Hand": "tianxia.background.abandoned_orphan",
    }
    assert projected["core_stats"]["skill_source_provenance"] == ledger["core_stats"]["skill_sources"]
    assert projection["skill_sources_mode"] == "source_backed_identifier_projection"
    expected_packet_sources = {
        "Arcana": ["packet.public.path"],
        "Deception": ["packet.public.background", "packet.public.origin"],
        "Medicine": ["packet.public.path"],
        "Sleight of Hand": ["packet.public.background"],
    }
    assert projected["core_stats"]["skill_source_packet_ids"] == expected_packet_sources
    assert projection["skill_source_packet_ids_mode"] == "derived_from_source_record_ids"
    details = json.loads(
        (workspace / projection["details_path"]).read_text(encoding="utf-8")
    )
    assert details["skill_adjustments"] == expected
    assert details["skill_adjustments_mode"] == "source_backed_explicit_none"
    assert details["skill_sources"] == projected["core_stats"]["skill_sources"]
    assert details["skill_source_provenance"] == ledger["core_stats"]["skill_sources"]
    assert details["skill_source_packet_ids"] == expected_packet_sources


def test_modern_core_skill_projection_preserves_existing_valid_adjustments(
    tmp_path: Path,
) -> None:
    workspace, _raw, ledger = _public_path_projection_workspace(tmp_path)
    expected = {"Arcana": 0, "Deception": 0, "Medicine": 0, "Sleight of Hand": 0}
    _add_public_skill_projection(ledger, adjustments=expected)
    ledger["core_stats"]["skill_sources"] = {
        "Arcana": "tianxia.path.qi_cultivation",
        "Deception": "tianxia.background.abandoned_orphan; tianxia.origin_insight.born_under_suspicion",
        "Medicine": "tianxia.path.qi_cultivation",
        "Sleight of Hand": "tianxia.background.abandoned_orphan",
    }
    ledger["core_stats"]["skill_source_packet_ids"] = {
        "Arcana": ["packet.public.path"],
        "Deception": ["packet.public.background", "packet.public.origin"],
        "Medicine": ["packet.public.path"],
        "Sleight of Hand": ["packet.public.background"],
    }
    (workspace / "Build/Character_Master_Ledger.json").write_text(
        json.dumps(ledger, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    projection = materializer._project_modern_core_saves_for_compiler(
        workspace,
        path_projection=path_projection,
    )
    projected = json.loads(
        (workspace / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8")
    )
    assert projected["core_stats"]["skill_adjustments"] == expected
    assert projection["skill_adjustments_mode"] == "preserved_existing"
    assert projection["skill_sources_mode"] == "preserved_text"
    assert projection["skill_source_packet_ids_mode"] == "preserved_existing_packet_ids"
    assert projected["core_stats"]["skill_sources"] == ledger["core_stats"]["skill_sources"]
    assert projected["core_stats"]["skill_source_packet_ids"] == ledger["core_stats"]["skill_source_packet_ids"]


@pytest.mark.parametrize("registry_mutator", [
    lambda packets: packets.__setitem__(
        "packets",
        [row for row in packets["packets"] if row.get("record_id") != "tianxia.background.abandoned_orphan"],
    ),
    lambda packets: packets["packets"].append({
        "packet_id": "packet.public.background.duplicate",
        "record_id": "tianxia.background.abandoned_orphan",
        "display_name": "Abandoned Orphan",
        "source_evidence": [{
            "source_path": "public/source.md",
            "source_hash": "a" * 64,
            "source_anchor": "record:tianxia.background.abandoned_orphan",
        }],
    }),
])
def test_modern_core_skill_projection_requires_unique_sealed_source_packets(
    tmp_path: Path,
    registry_mutator: Any,
) -> None:
    workspace, _raw, ledger = _public_path_projection_workspace(tmp_path)
    _add_public_skill_projection(ledger)
    (workspace / "Build/Character_Master_Ledger.json").write_text(
        json.dumps(ledger, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    packets_path = workspace / "Command_2/Rules_Selection_Packets.json"
    packets = json.loads(packets_path.read_text(encoding="utf-8"))
    registry_mutator(packets)
    packets_path.write_text(json.dumps(packets, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(FoundryError) as error:
        materializer._project_modern_core_saves_for_compiler(
            workspace,
            path_projection=path_projection,
        )
    assert error.value.code == "FINAL_CHARACTER_CORE_SAVE_PROJECTION_INVALID"
    assert not (workspace / materializer._CORE_SAVE_PROJECTION_DETAILS_RELATIVE).exists()


def test_modern_core_skill_projection_rejects_forged_existing_source_packet_binding(
    tmp_path: Path,
) -> None:
    workspace, _raw, ledger = _public_path_projection_workspace(tmp_path)
    _add_public_skill_projection(ledger)
    ledger["core_stats"]["skill_source_packet_ids"] = {
        "Arcana": ["packet.public.background"],
        "Deception": ["packet.public.background", "packet.public.origin"],
        "Medicine": ["packet.public.path"],
        "Sleight of Hand": ["packet.public.background"],
    }
    (workspace / "Build/Character_Master_Ledger.json").write_text(
        json.dumps(ledger, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    with pytest.raises(FoundryError) as error:
        materializer._project_modern_core_saves_for_compiler(
            workspace,
            path_projection=path_projection,
        )
    assert error.value.code == "FINAL_CHARACTER_CORE_SAVE_PROJECTION_INVALID"


@pytest.mark.parametrize(
    "adjustments",
    [
        {"Arcana": 0},
        {"Arcana": 0, "Deception": "0", "Medicine": 0, "Sleight of Hand": 0},
        {"Arcana": 0, "Deception": 1, "Medicine": 0, "Sleight of Hand": 0},
    ],
)
def test_modern_core_skill_projection_rejects_malformed_or_inconsistent_adjustments(
    tmp_path: Path,
    adjustments: Mapping[str, Any],
) -> None:
    workspace, _raw, ledger = _public_path_projection_workspace(tmp_path)
    _add_public_skill_projection(ledger, adjustments=adjustments)
    (workspace / "Build/Character_Master_Ledger.json").write_text(
        json.dumps(ledger, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    before = (workspace / "Build/Character_Master_Ledger.json").read_bytes()
    with pytest.raises(FoundryError) as error:
        materializer._project_modern_core_saves_for_compiler(
            workspace,
            path_projection=path_projection,
        )
    assert error.value.code == "FINAL_CHARACTER_CORE_SAVE_PROJECTION_INVALID"
    assert (workspace / "Build/Character_Master_Ledger.json").read_bytes() == before


@pytest.mark.parametrize(
    "source_mutator",
    [
        lambda core: core["skill_sources"].update(Arcana=[]),
        lambda core: core["skill_sources"].update(Arcana=["tianxia.path.qi_cultivation "]),
        lambda core: core["skill_sources"].update(Arcana={"record_id": "tianxia.path.qi_cultivation"}),
        lambda core: core["skill_sources"].pop("Medicine"),
    ],
)
def test_modern_core_skill_projection_rejects_malformed_or_incomplete_sources(
    tmp_path: Path,
    source_mutator: Any,
) -> None:
    workspace, _raw, ledger = _public_path_projection_workspace(tmp_path)
    _add_public_skill_projection(ledger)
    source_mutator(ledger["core_stats"])
    (workspace / "Build/Character_Master_Ledger.json").write_text(
        json.dumps(ledger, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    before = (workspace / "Build/Character_Master_Ledger.json").read_bytes()
    with pytest.raises(FoundryError) as error:
        materializer._project_modern_core_saves_for_compiler(
            workspace,
            path_projection=path_projection,
        )
    assert error.value.code == "FINAL_CHARACTER_CORE_SAVE_PROJECTION_INVALID"
    assert (workspace / "Build/Character_Master_Ledger.json").read_bytes() == before


_PUBLIC_MULTI_PATH_PAIRS = (
    ("body_refining", "spirit_awakening"),
    ("qi_cultivation", "body_refining"),
    ("spirit_awakening", "qi_cultivation"),
)


@pytest.mark.parametrize(
    "change",
    [
        "secondary_source_hash",
        "secondary_key_ability",
        "secondary_selection",
        "primary_level_below_event",
        "character_level_mismatch",
        "duplicate_path",
        "secondary_packet_reuse",
        "secondary_feature_name",
        "secondary_primary_source",
        "unselected_feature",
        "missing_secondary_features",
        "duplicate_feature_level",
    ],
)
def test_modern_multi_path_projection_rejects_secondary_tampering(
    tmp_path: Path,
    change: str,
) -> None:
    workspace, _raw, ledger = _public_multi_path_projection_workspace(
        tmp_path,
        _PUBLIC_MULTI_PATH_PAIRS[0],
    )
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    registry_path = workspace / "Command_2/Rules_Selection_Packets.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    pair = _PUBLIC_MULTI_PATH_PAIRS[0]
    primary_id = f"tianxia.path.{pair[0]}"
    secondary_id = f"tianxia.path.{pair[1]}"
    paths = ledger["character"]["paths"]
    selections = ledger["path_selections"]
    secondary = paths[1]
    if change == "secondary_source_hash":
        packet = next(
            packet for packet in registry["packets"]
            if packet["packet_id"] == secondary["source_packet_ids"][0]
        )
        packet["source_evidence"][0]["source_hash"] = "0" * 64
    elif change == "secondary_key_ability":
        secondary["key_ability"] = "STR"
        selections[1]["key_ability"] = "STR"
    elif change == "secondary_selection":
        selections[1]["display_name"] = "Unproven Path Name"
    elif change == "primary_level_below_event":
        paths[0]["effective_cl"] = 7
        selections[0]["effective_cl"] = 7
    elif change == "character_level_mismatch":
        ledger["character"]["cl"] = 14
    elif change == "duplicate_path":
        paths[1] = deepcopy(paths[0])
        selections[1] = deepcopy(selections[0])
    elif change == "secondary_packet_reuse":
        secondary["source_packet_ids"] = deepcopy(paths[0]["source_packet_ids"])
        selections[1]["source_packet_ids"] = deepcopy(secondary["source_packet_ids"])
    elif change == "secondary_feature_name":
        next(
            row for row in ledger["features"]
            if row.get("feature_id", "").startswith(secondary_id + ".feature.")
        )["name"] = "Invented Secondary Feature"
    elif change == "secondary_primary_source":
        secondary_row = next(
            row for row in ledger["features"]
            if row.get("feature_id", "").startswith(secondary_id + ".feature.")
        )
        secondary_packet = next(
            packet for packet in registry["packets"]
            if packet["packet_id"] == secondary_row["source_packet_ids"][0]
        )
        primary_row = next(
            row for row in ledger["features"]
            if row.get("feature_id", "").startswith(primary_id + ".feature.")
        )
        primary_packet = next(
            packet for packet in registry["packets"]
            if packet["packet_id"] == primary_row["source_packet_ids"][0]
        )
        secondary_packet["source_evidence"] = deepcopy(primary_packet["source_evidence"])
    elif change == "unselected_feature":
        secondary_row = next(
            row for row in ledger["features"]
            if row.get("feature_id", "").startswith(secondary_id + ".feature.")
        )
        secondary_row["feature_id"] = "tianxia.path.qi_cultivation.feature.unselected"
    elif change == "missing_secondary_features":
        ledger["features"] = [
            row for row in ledger["features"]
            if not row.get("feature_id", "").startswith(secondary_id + ".feature.")
        ]
    elif change == "duplicate_feature_level":
        secondary_row = next(
            row for row in ledger["features"]
            if row.get("feature_id", "").startswith(secondary_id + ".feature.")
        )
        duplicate = deepcopy(secondary_row)
        duplicate["allocation_id"] += ".duplicate"
        original_packet_id = duplicate["source_packet_ids"][0]
        duplicate_packet_id = original_packet_id + ".duplicate"
        duplicate["source_packet_ids"] = [duplicate_packet_id]
        ledger["features"].append(duplicate)
        original_packet = next(
            packet for packet in registry["packets"]
            if packet["packet_id"] == original_packet_id
        )
        duplicate_packet = deepcopy(original_packet)
        duplicate_packet["packet_id"] = duplicate_packet_id
        registry["packets"].append(duplicate_packet)
    else:
        raise AssertionError(change)
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    registry_path.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")
    before = _snapshot(workspace)
    with pytest.raises(FoundryError) as error:
        materializer._project_modern_path_fields_for_compiler(workspace)
    assert error.value.code == "FINAL_CHARACTER_PATH_PROJECTION_INVALID"
    assert _snapshot(workspace) == before


@pytest.mark.parametrize("change", ["secondary_path_packet_reuse", "secondary_feature_packet_reuse"])
def test_modern_multi_path_projection_rejects_duplicate_packet_bindings(
    tmp_path: Path,
    change: str,
) -> None:
    workspace, _raw, ledger = _public_multi_path_projection_workspace(
        tmp_path,
        _PUBLIC_MULTI_PATH_PAIRS[0],
    )
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    registry_path = workspace / "Command_2/Rules_Selection_Packets.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    primary_id = "tianxia.path.body_refining"
    secondary_id = "tianxia.path.spirit_awakening"
    if change == "secondary_path_packet_reuse":
        reused = ledger["character"]["paths"][0]["source_packet_ids"]
        ledger["character"]["paths"][1]["source_packet_ids"] = deepcopy(reused)
        ledger["path_selections"][1]["source_packet_ids"] = deepcopy(reused)
    else:
        primary_feature = next(
            row for row in ledger["features"]
            if row.get("feature_id", "").startswith(primary_id + ".feature.")
        )
        secondary_feature = next(
            row for row in ledger["features"]
            if row.get("feature_id", "").startswith(secondary_id + ".feature.")
        )
        secondary_feature["source_packet_ids"] = deepcopy(primary_feature["source_packet_ids"])
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    registry_path.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")
    before = _snapshot(workspace)
    with pytest.raises(FoundryError) as error:
        materializer._project_modern_path_fields_for_compiler(workspace)
    assert error.value.code == "FINAL_CHARACTER_PATH_PROJECTION_INVALID"
    assert _snapshot(workspace) == before


@pytest.mark.parametrize("pair", _PUBLIC_MULTI_PATH_PAIRS)
def test_modern_multi_path_projection_retains_union_and_provenance(
    tmp_path: Path,
    pair: tuple[str, str],
) -> None:
    workspace, raw, original = _public_multi_path_projection_workspace(tmp_path, pair)
    registry_path = workspace / "Command_2/Rules_Selection_Packets.json"
    registry_before = registry_path.read_bytes()
    projection = materializer._project_modern_path_fields_for_compiler(workspace)
    ledger = json.loads(
        (workspace / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8")
    )
    path_ids = [f"tianxia.path.{short_name}" for short_name in pair]
    expected_ids = [
        row["feature_id"]
        for row in original["features"]
        if row.get("category") == "path_feature" and row["gained_at_cl"] == 4
    ]
    assert ledger["character"]["cl"] == 15
    assert ledger["character"]["paths"] == original["character"]["paths"]
    assert ledger["path_selections"] == original["path_selections"]
    assert ledger["character"]["path_source_packet_ids"] == [
        row["source_packet_ids"][0] for row in original["path_selections"]
    ]
    assert ledger["character"]["path_feature_ids_expected"] == expected_ids
    assert [
        row["feature_id"] for row in ledger["features"]
        if row.get("category") == "path_feature"
    ] == expected_ids
    assert ledger["features"][-1] == original["features"][-1]
    assert projection["path_ids"] == path_ids
    assert projection["path_target_cls"] == {path_ids[0]: 8, path_ids[1]: 15}
    assert projection["path_feature_ids_by_path"] == {
        path_id: [feature_id] for path_id, feature_id in zip(path_ids, expected_ids)
    }
    assert projection["path_feature_occurrence_count"] == 4
    raw_provenance = workspace / projection["modern_provenance_path"]
    assert raw_provenance.read_bytes() == raw
    details = json.loads(
        (workspace / projection["details_path"]).read_text(encoding="utf-8")
    )
    assert details["path_ids"] == path_ids
    assert details["path_target_cls"] == {path_ids[0]: 8, path_ids[1]: 15}
    assert [row["gained_at_cl"] for row in details["retained_occurrences"]] == [4, 4]
    assert [row["gained_at_cl"] for row in details["removed_occurrences"]] == [8, 8]
    assert [item["path_id"] for item in details["path_feature_occurrences"]] == [
        path_ids[0], path_ids[0], path_ids[1], path_ids[1]
    ]
    assert registry_path.read_bytes() == registry_before


def test_modern_multi_path_projection_rejects_missing_recorded_occurrence_with_packet(
    tmp_path: Path,
) -> None:
    workspace, _raw, ledger = _public_multi_path_projection_workspace(
        tmp_path,
        _PUBLIC_MULTI_PATH_PAIRS[0],
    )
    secondary_id = "tianxia.path.spirit_awakening"
    ledger["features"] = [
        row
        for row in ledger["features"]
        if not (
            row.get("feature_id", "").startswith(secondary_id + ".feature.")
            and row.get("gained_at_cl") == 8
        )
    ]
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    before = _snapshot(workspace)
    with pytest.raises(FoundryError) as error:
        materializer._project_modern_path_fields_for_compiler(workspace)
    assert error.value.code == "FINAL_CHARACTER_PATH_PROJECTION_INVALID"
    assert _snapshot(workspace) == before


def test_modern_path_projection_deduplicates_permanent_features_and_preserves_lineage(
    tmp_path: Path,
) -> None:
    workspace, raw, original = _public_path_projection_workspace(tmp_path)
    projection = materializer._project_modern_path_fields_for_compiler(workspace)
    ledger = json.loads(
        (workspace / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8")
    )
    character = ledger["character"]
    asi_id = "tianxia.path.qi_cultivation.feature.ability_score_improvement_or_cultivation_insight"
    subpath_id = "tianxia.path.qi_cultivation.feature.subpath_feature"
    assert character["path_source_packet_ids"] == ["packet.public.path"]
    assert character["path_feature_ids_expected"] == [asi_id, subpath_id]
    assert [row["feature_id"] for row in ledger["features"] if row.get("category") == "path_feature"] == [asi_id, subpath_id]
    assert ledger["features"][-1] == original["features"][-1]
    raw_provenance = workspace / projection["modern_provenance_path"]
    assert raw_provenance.read_bytes() == raw
    assert projection["modern_provenance_sha256"] == materializer.sha256_file(raw_provenance)
    details = json.loads(
        (workspace / projection["details_path"]).read_text(encoding="utf-8")
    )
    assert details["source_ledger_sha256"] == materializer.sha256_file(raw_provenance)
    assert details["original_ledger_sha256"] == details["source_ledger_sha256"]
    assert [row["gained_at_cl"] for row in details["deduplicated_occurrences"]] == [8]
    assert details["removed_occurrences"] == details["deduplicated_occurrences"]
    assert details["projected_path_feature_ids"] == [asi_id, subpath_id]


@pytest.mark.parametrize(
    "mutator",
    [
        lambda ledger: ledger["path_selections"][0].update(key_ability="CHA"),
        lambda ledger: ledger["character"]["paths"][0].update(path_id="tianxia.path.body_refining"),
        lambda ledger: ledger["features"][0].update(name="Forged Feature"),
        lambda ledger: ledger["features"][0].update(gained_at_cl=5),
        lambda ledger: ledger["features"][0].update(source_packet_ids=["packet.public.path"]),
        lambda ledger: ledger["features"][2].update(allocation_id="allocation.public.asi.4"),
    ],
)
def test_modern_path_projection_rejects_forged_or_duplicate_event_binding(
    tmp_path: Path,
    mutator: Any,
) -> None:
    workspace, _raw, ledger = _public_path_projection_workspace(tmp_path)
    mutator(ledger)
    (workspace / "Build/Character_Master_Ledger.json").write_text(
        json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8"
    )
    before = (workspace / "Build/Character_Master_Ledger.json").read_bytes()
    with pytest.raises(FoundryError) as error:
        materializer._project_modern_path_fields_for_compiler(workspace)
    assert error.value.code == "FINAL_CHARACTER_PATH_PROJECTION_INVALID"
    assert (workspace / "Build/Character_Master_Ledger.json").read_bytes() == before
    assert not (workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE).exists()


def test_modern_path_projection_rejects_path_packet_and_feature_packet_tampering(
    tmp_path: Path,
) -> None:
    workspace, _raw, _ledger = _public_path_projection_workspace(tmp_path)
    packets_path = workspace / "Command_2/Rules_Selection_Packets.json"
    packets = json.loads(packets_path.read_text(encoding="utf-8"))
    packets["packets"][1]["source_evidence"][0]["source_hash"] = "0" * 64
    packets_path.write_text(json.dumps(packets, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(FoundryError) as error:
        materializer._project_modern_path_fields_for_compiler(workspace)
    assert error.value.code == "FINAL_CHARACTER_PATH_PROJECTION_INVALID"
    assert not (workspace / materializer._PATH_PROJECTION_DETAILS_RELATIVE).exists()


def test_modern_core_save_projection_derives_saves_from_authenticated_none_path(
    tmp_path: Path,
) -> None:
    workspace, raw, original = _public_path_projection_workspace(tmp_path)
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    raw_provenance = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    raw_provenance_bytes = raw_provenance.read_bytes()
    projection = materializer._project_modern_core_saves_for_compiler(
        workspace,
        path_projection=path_projection,
    )
    ledger = json.loads((workspace / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8"))
    core_stats = ledger["core_stats"]
    assert core_stats["ability_scores"] == original["core_stats"]["ability_scores"]
    assert core_stats["ability_modifiers"] == original["core_stats"]["ability_modifiers"]
    assert core_stats["saving_throws"] == original["core_stats"]["ability_modifiers"]
    assert core_stats["saving_throw_adjustments"] == {ability: 0 for ability in materializer._CORE_SAVE_ABILITIES}
    assert core_stats["saving_throw_adjustment_source_packet_ids"] == {}
    assert raw_provenance.read_bytes() == raw_provenance_bytes == raw
    details_path = workspace / projection["details_path"]
    details = json.loads(details_path.read_text(encoding="utf-8"))
    assert details["saving_throw_proficiencies"] == "None"
    assert details["source_ledger_sha256"] == materializer.sha256_file(raw_provenance)
    assert projection["details_sha256"] == materializer.sha256_file(details_path)
    assert set(core_stats) == {
        "ability_scores",
        "ability_modifiers",
        "saving_throws",
        "saving_throw_adjustments",
        "saving_throw_adjustment_source_packet_ids",
    }


def test_modern_core_save_projection_accepts_existing_exact_maps(tmp_path: Path) -> None:
    workspace, _raw, ledger = _public_path_projection_workspace(tmp_path)
    ledger["core_stats"].update({
        "saving_throws": deepcopy(ledger["core_stats"]["ability_modifiers"]),
        "saving_throw_adjustments": {ability: 0 for ability in materializer._CORE_SAVE_ABILITIES},
        "saving_throw_adjustment_source_packet_ids": {},
    })
    (workspace / "Build/Character_Master_Ledger.json").write_text(
        json.dumps(ledger, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    projection = materializer._project_modern_core_saves_for_compiler(
        workspace,
        path_projection=path_projection,
    )
    assert projection["saving_throws"] == ledger["core_stats"]["ability_modifiers"]


@pytest.mark.parametrize(
    "mutator",
    [
        lambda core: core["ability_modifiers"].update(INT=3),
        lambda core: core["ability_scores"].update(INT=True),
        lambda core: core["ability_scores"].pop("CHA"),
        lambda core: core["ability_modifiers"].update(DEX=99),
    ],
)
def test_modern_core_save_projection_rejects_forged_ability_maps(
    tmp_path: Path,
    mutator: Any,
) -> None:
    workspace, _raw, ledger = _public_path_projection_workspace(tmp_path)
    mutator(ledger["core_stats"])
    (workspace / "Build/Character_Master_Ledger.json").write_text(
        json.dumps(ledger, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    before = (workspace / "Build/Character_Master_Ledger.json").read_bytes()
    with pytest.raises(FoundryError) as error:
        materializer._project_modern_core_saves_for_compiler(
            workspace,
            path_projection=path_projection,
        )
    assert error.value.code == "FINAL_CHARACTER_CORE_SAVE_PROJECTION_INVALID"
    assert (workspace / "Build/Character_Master_Ledger.json").read_bytes() == before
    assert not (workspace / materializer._CORE_SAVE_PROJECTION_DETAILS_RELATIVE).exists()


def test_modern_core_save_projection_rejects_non_none_path_proficiency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, _raw, _ledger = _public_path_projection_workspace(tmp_path)
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    real_fixed_json = materializer._bridge_fixed_json
    path_index_path = materializer._PACKET_PATH_PROOFS["tianxia.path.qi_cultivation"]["index_path"]

    def forged_fixed_json(relative_path: str, expected_sha256: str) -> Mapping[str, Any] | None:
        value = real_fixed_json(relative_path, expected_sha256)
        if relative_path == path_index_path and isinstance(value, Mapping):
            value = deepcopy(dict(value))
            value["path_profile"] = deepcopy(value["path_profile"])
            value["path_profile"]["saving_throw_proficiencies"] = "Strength"
        return value

    monkeypatch.setattr(materializer, "_bridge_fixed_json", forged_fixed_json)
    with pytest.raises(FoundryError) as error:
        materializer._project_modern_core_saves_for_compiler(
            workspace,
            path_projection=path_projection,
        )
    assert error.value.code == "FINAL_CHARACTER_CORE_SAVE_PROJECTION_INVALID"


@pytest.mark.parametrize(
    "field,value",
    [
        ("saving_throws", {"STR": 1, "DEX": 2, "CON": 1, "INT": 4, "WIS": 1, "CHA": -1}),
        ("saving_throw_adjustments", {ability: 0 for ability in materializer._CORE_SAVE_ABILITIES} | {"INT": 1}),
        ("saving_throw_adjustment_source_packet_ids", {"INT": ["packet.public.adjustment"]}),
    ],
)
def test_modern_core_save_projection_rejects_conflicting_existing_fields(
    tmp_path: Path,
    field: str,
    value: Any,
) -> None:
    workspace, _raw, ledger = _public_path_projection_workspace(tmp_path)
    ledger["core_stats"][field] = value
    (workspace / "Build/Character_Master_Ledger.json").write_text(
        json.dumps(ledger, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    before = (workspace / "Build/Character_Master_Ledger.json").read_bytes()
    with pytest.raises(FoundryError) as error:
        materializer._project_modern_core_saves_for_compiler(
            workspace,
            path_projection=path_projection,
        )
    assert error.value.code == "FINAL_CHARACTER_CORE_SAVE_PROJECTION_INVALID"
    assert (workspace / "Build/Character_Master_Ledger.json").read_bytes() == before
    assert not (workspace / materializer._CORE_SAVE_PROJECTION_DETAILS_RELATIVE).exists()


@_REQUIRES_VENDOR_FIXTURE
def test_packet_bridge_public_method_foundation_and_qi_path_proofs(tmp_path: Path) -> None:
    packets = [
        _public_packet(
            "packet.public.method",
            "METHOD-001",
            "Outer Gate Root Method",
            materializer._PACKET_METHOD_SOURCE_PATH,
            materializer._PACKET_METHOD_SOURCE_SHA256,
            "method:METHOD-001",
        ),
        _public_packet(
            "packet.public.foundation",
            "furnace_heart_record_v0_2B",
            "Furnace Heart Record",
            materializer._PACKET_FOUNDATION_SOURCE_PATH,
            materializer._PACKET_FOUNDATION_SOURCE_SHA256,
            "foundation:furnace_heart_record_v0_2B",
        ),
        _public_packet(
            "packet.public.qi",
            "tianxia.path.qi_cultivation",
            "Qi Cultivation",
            materializer._PACKET_PATH_PROOFS["tianxia.path.qi_cultivation"]["index_path"],
            materializer._PACKET_PATH_PROOFS["tianxia.path.qi_cultivation"]["index_sha256"],
            "path:tianxia.path.qi_cultivation",
        ),
        _public_packet(
            "packet.public.qi-feature",
            "tianxia.path.qi_cultivation.feature.qi_sensing",
            "Qi Sensing",
            materializer._PACKET_PATH_PROOFS["tianxia.path.qi_cultivation"]["index_path"],
            materializer._PACKET_PATH_PROOFS["tianxia.path.qi_cultivation"]["index_sha256"],
            "path-feature:tianxia.path.qi_cultivation:tianxia.path.qi_cultivation.feature.qi_sensing",
        ),
    ]
    workspace = _public_packet_bridge_workspace(tmp_path, packets)
    projection = materializer._bridge_rules_packet_registry(workspace, CORPUS)
    native = json.loads((workspace / "Command_2/Rules_Selection_Packets.json").read_text(encoding="utf-8"))
    # The compiler-native packet schema carries the modern record identity in
    # ``modern_record_id``; ``record_id`` is intentionally not invented as a
    # second compiler authority field.
    by_id = {row["modern_record_id"]: row for row in native["packets"]}
    assert projection["native_registry_packet_count"] == 4
    assert by_id["METHOD-001"]["authority"] == "tianxia_rules"
    assert by_id["METHOD-001"]["source_text"] == "## 1. Outer Gate Root Method"
    assert by_id["furnace_heart_record_v0_2B"]["source_text"] == "# 10. Furnace Heart Record"
    assert by_id["tianxia.path.qi_cultivation"]["source_path"] == materializer._PACKET_PATH_PROOFS["tianxia.path.qi_cultivation"]["corpus_path"]
    assert "Qi Cultivation" in by_id["tianxia.path.qi_cultivation"]["source_text"]
    assert "CL1" in by_id["tianxia.path.qi_cultivation"]["source_text"]
    assert by_id["tianxia.path.qi_cultivation.feature.qi_sensing"]["source_text"] == "## CL1 — Qi Sensing"


@_REQUIRES_VENDOR_FIXTURE
def test_packet_bridge_qi_subpath_binds_cl3_line_inside_authenticated_section(tmp_path: Path) -> None:
    packet = _public_packet(
        "packet.public.qi-subpath",
        "tianxia.path.qi_cultivation.feature.qi_cultivation_subpath",
        "Qi Cultivation Subpath",
        materializer._PACKET_PATH_PROOFS["tianxia.path.qi_cultivation"]["index_path"],
        materializer._PACKET_PATH_PROOFS["tianxia.path.qi_cultivation"]["index_sha256"],
        "path-feature:tianxia.path.qi_cultivation:tianxia.path.qi_cultivation.feature.qi_cultivation_subpath",
        target_cl=3,
    )
    workspace = _public_packet_bridge_workspace(tmp_path, [packet])
    projection = materializer._bridge_rules_packet_registry(workspace, CORPUS)
    native = json.loads((workspace / "Command_2/Rules_Selection_Packets.json").read_text(encoding="utf-8"))
    assert projection["native_registry_packet_count"] == 1
    assert hashlib.sha256(native["packets"][0]["source_text"].encode()).hexdigest() == QI_SUBPATH_CL3_SHA256


@_REQUIRES_VENDOR_FIXTURE
def test_packet_bridge_qi_shared_subpath_feature_binds_fixed_cl6_schedule(
    tmp_path: Path,
) -> None:
    packet = _public_packet(
        "packet.public.qi-shared-subpath-feature",
        "tianxia.path.qi_cultivation.feature.subpath_feature",
        "Subpath Feature",
        materializer._PACKET_PATH_PROOFS["tianxia.path.qi_cultivation"]["index_path"],
        materializer._PACKET_PATH_PROOFS["tianxia.path.qi_cultivation"]["index_sha256"],
        "path-feature:tianxia.path.qi_cultivation:tianxia.path.qi_cultivation.feature.subpath_feature",
        target_cl=6,
    )
    workspace = _public_packet_bridge_workspace(tmp_path, [packet])
    projection = materializer._bridge_rules_packet_registry(workspace, CORPUS)
    native = json.loads(
        (workspace / "Command_2/Rules_Selection_Packets.json").read_text(encoding="utf-8")
    )
    assert projection["native_registry_packet_count"] == 1
    assert native["packets"][0]["modern_record_id"] == (
        "tianxia.path.qi_cultivation.feature.subpath_feature"
    )
    assert hashlib.sha256(native["packets"][0]["source_text"].encode()).hexdigest() == QI_SUBPATH_CL3_SHA256


@pytest.mark.parametrize(
    "mutator",
    [
        lambda row: row.update(target_cl=5),
        lambda row: row.update(display_name="Qi Sensing"),
        lambda row: row["source_evidence"][0].update(
            source_anchor="path-feature:tianxia.path.qi_cultivation:tianxia.path.qi_cultivation.feature.qi_sensing",
        ),
    ],
)
@_REQUIRES_VENDOR_FIXTURE
def test_packet_bridge_qi_shared_subpath_feature_rejects_unproven_aliases(
    tmp_path: Path,
    mutator: Any,
) -> None:
    packet = _public_packet(
        "packet.public.qi-shared-subpath-feature-forged",
        "tianxia.path.qi_cultivation.feature.subpath_feature",
        "Subpath Feature",
        materializer._PACKET_PATH_PROOFS["tianxia.path.qi_cultivation"]["index_path"],
        materializer._PACKET_PATH_PROOFS["tianxia.path.qi_cultivation"]["index_sha256"],
        "path-feature:tianxia.path.qi_cultivation:tianxia.path.qi_cultivation.feature.subpath_feature",
        target_cl=6,
    )
    mutator(packet)
    workspace = _public_packet_bridge_workspace(tmp_path, [packet])
    with pytest.raises(FoundryError) as error:
        materializer._bridge_rules_packet_registry(workspace, CORPUS)
    assert error.value.code == "FINAL_CHARACTER_PACKET_BRIDGE_UNRESOLVED"


def _public_alchemical_insight_packet() -> dict[str, Any]:
    registry = materializer._bridge_fixed_json(
        materializer._PACKET_INSIGHT_SOURCE_PATH,
        materializer._PACKET_INSIGHT_SOURCE_SHA256,
    )
    assert registry is not None
    records = [
        row
        for row in registry["records"]
        if row.get("canonical_id") == "insight.alchemical-prodigy"
    ]
    assert len(records) == 1
    record = records[0]
    return _public_packet(
        "packet.public.alchemical-insight",
        record["canonical_id"],
        record["display_name"],
        materializer._PACKET_INSIGHT_SOURCE_PATH,
        materializer._PACKET_INSIGHT_SOURCE_SHA256,
        f"record:{record['record_id']}",
        target_cl=record["minimum_cl"],
    )


@_REQUIRES_VENDOR_FIXTURE
def test_packet_bridge_alchemical_insight_uses_fixed_record_and_active_corpus_heading(
    tmp_path: Path,
) -> None:
    packet = _public_alchemical_insight_packet()
    workspace = _public_packet_bridge_workspace(tmp_path, [packet])
    projection = materializer._bridge_rules_packet_registry(workspace, CORPUS)
    native = json.loads(
        (workspace / "Command_2/Rules_Selection_Packets.json").read_text(encoding="utf-8")
    )
    assert projection["native_registry_packet_count"] == 1
    assert native["packets"][0]["authority"] == "tianxia_rules"
    assert native["packets"][0]["modern_record_id"] == "insight.alchemical-prodigy"
    assert native["packets"][0]["source_path"] == materializer._PACKET_INSIGHT_CORPUS_PATH
    assert native["packets"][0]["source_text"] == "### Alchemical Prodigy"
    assert native["packets"][0]["source_text_sha256"] == materializer._sha256_text(
        "### Alchemical Prodigy"
    )
    assert native["packets"][0]["source_section"] == (
        "record:sphere-compendium.alchemy.alchemical-prodigy"
    )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda row: row.update(record_id="insight.alchemical-prodigy-forged"),
        lambda row: row.update(display_name="Alchemical Constitution"),
        lambda row: row["source_evidence"][0].update(
            source_path=materializer._PACKET_INSIGHT_CORPUS_PATH,
        ),
        lambda row: row["source_evidence"][0].update(source_hash="0" * 64),
        lambda row: row["source_evidence"][0].update(
            source_anchor="record:sphere-compendium.alchemy.alchemical-constitution",
        ),
        lambda row: row.update(target_cl=5),
        lambda row: row.update(target_cl=4.0),
        lambda row: row["source_evidence"][0].update(
            source_path="09_RULES/Source_Text/Tianxia_Sphere_Compendium_Latest_R0I_85Spheres.md",
        ),
    ],
)
@_REQUIRES_VENDOR_FIXTURE
def test_packet_bridge_alchemical_insight_forgery_and_legacy_fallback_reject(
    tmp_path: Path,
    mutator: Any,
) -> None:
    packet = _public_alchemical_insight_packet()
    mutator(packet)
    workspace = _public_packet_bridge_workspace(tmp_path, [packet])
    with pytest.raises(FoundryError) as error:
        materializer._bridge_rules_packet_registry(workspace, CORPUS)
    assert error.value.code == "FINAL_CHARACTER_PACKET_BRIDGE_UNRESOLVED"
    assert packet["packet_id"] in str(error.value.details)


@_REQUIRES_VENDOR_FIXTURE
def test_packet_bridge_alchemical_insight_rejects_tampered_active_corpus_bytes() -> None:
    packet = _public_alchemical_insight_packet()
    active, texts = materializer._corpus_active_texts(CORPUS)
    texts[materializer._PACKET_INSIGHT_CORPUS_PATH] += "\nforged"
    family, proof = materializer._bridge_modern_packet_source(
        packet,
        corpus=CORPUS,
        active=active,
        corpus_texts=texts,
    )
    assert family is True
    assert proof is None


def _public_alchemical_subpath_packet() -> dict[str, Any]:
    master = materializer._bridge_fixed_json(
        materializer._PACKET_SUBPATH_MASTER_PATH,
        materializer._PACKET_SUBPATH_MASTER_SHA256,
    )
    assert master is not None
    entry = next(row for row in master["entries"] if row["canonical_id"] == "tianxia.subpath.qi.alchemical_cultivator")
    source = entry["source"]
    return _public_packet(
        "packet.public.alchemical-subpath",
        entry["canonical_id"],
        entry["display_name"],
        source["factory_source_path"],
        source["source_file_sha256"],
        "subpath:tianxia.subpath.qi.alchemical_cultivator",
        target_cl=entry["prerequisites"]["selection_level"],
    )


@_REQUIRES_VENDOR_FIXTURE
def test_packet_bridge_alchemical_subpath_uses_fixed_master_and_corpus_heading(tmp_path: Path) -> None:
    packet = _public_alchemical_subpath_packet()
    workspace = _public_packet_bridge_workspace(tmp_path, [packet])
    projection = materializer._bridge_rules_packet_registry(workspace, CORPUS)
    native = json.loads((workspace / "Command_2/Rules_Selection_Packets.json").read_text(encoding="utf-8"))
    assert projection["native_registry_packet_count"] == 1
    assert native["packets"][0]["source_path"] == "Canonical/Paths/Qi/Tianxia_Qi_Cultivation_Subpath_Compendium_R19.md"
    assert native["packets"][0]["source_text"] == "## Alchemical Cultivator"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda row: row.update(record_id="tianxia.subpath.qi.forged"),
        lambda row: row.update(display_name="Furnace Heart Record"),
        lambda row: row["source_evidence"][0].update(source_path="Canonical/Paths/Qi/Tianxia_Qi_Cultivation_Subpath_Compendium_R19.md"),
        lambda row: row["source_evidence"][0].update(source_hash="0" * 64),
        lambda row: row["source_evidence"][0].update(source_anchor="subpath:tianxia.subpath.qi.other"),
        lambda row: row.update(target_cl=3.0),
        lambda row: row.update(target_cl=4),
        lambda row: row["source_evidence"][0].update(
            source_path=materializer._PACKET_PATH_PROOFS["tianxia.path.qi_cultivation"]["index_path"],
            source_hash=materializer._PACKET_PATH_PROOFS["tianxia.path.qi_cultivation"]["index_sha256"],
        ),
    ],
)
@_REQUIRES_VENDOR_FIXTURE
def test_packet_bridge_alchemical_subpath_forgery_and_cross_family_reject(
    tmp_path: Path,
    mutator: Any,
) -> None:
    packet = _public_alchemical_subpath_packet()
    mutator(packet)
    workspace = _public_packet_bridge_workspace(tmp_path, [packet])
    with pytest.raises(FoundryError) as error:
        materializer._bridge_rules_packet_registry(workspace, CORPUS)
    assert error.value.code == "FINAL_CHARACTER_PACKET_BRIDGE_UNRESOLVED"
    assert packet["packet_id"] in str(error.value.details)


def _qi_asi_excerpt_inputs() -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]:
    _active, corpus_texts = materializer._corpus_active_texts(CORPUS)
    proof = materializer._PACKET_PATH_PROOFS["tianxia.path.qi_cultivation"]
    index = materializer._bridge_fixed_json(proof["index_path"], proof["index_sha256"])
    assert index is not None
    feature = next(
        row
        for row in index["features"]
        if row["canonical_id"] == "tianxia.path.qi_cultivation.feature.ability_score_improvement_or_cultivation_insight"
    )
    packet = _public_packet(
        "packet.public.qi-asi",
        feature["canonical_id"],
        feature["display_name"],
        proof["index_path"],
        proof["index_sha256"],
        "path-feature:tianxia.path.qi_cultivation:tianxia.path.qi_cultivation.feature.ability_score_improvement_or_cultivation_insight",
        target_cl=4,
    )
    return corpus_texts[proof["corpus_path"]], index, deepcopy(feature), packet


@_REQUIRES_VENDOR_FIXTURE
def test_packet_bridge_qi_asi_split_heading_binds_exact_cl4_excerpt(tmp_path: Path) -> None:
    text, index, feature, packet = _qi_asi_excerpt_inputs()
    workspace = _public_packet_bridge_workspace(tmp_path, [packet])
    projection = materializer._bridge_rules_packet_registry(workspace, CORPUS)
    native = json.loads((workspace / "Command_2/Rules_Selection_Packets.json").read_text(encoding="utf-8"))
    assert projection["native_registry_packet_count"] == 1
    assert hashlib.sha256(native["packets"][0]["source_text"].encode()).hexdigest() == QI_ASI_CL4_SHA256
    assert text
    assert index["canonical_id"] == "tianxia.path.qi_cultivation"
    assert feature["display_name"] == packet["display_name"]


@pytest.mark.parametrize("case", ["trailing_space", "trailing_content", "multiple_cl_lines"])
@_REQUIRES_VENDOR_FIXTURE
def test_packet_bridge_qi_asi_split_heading_rejects_section_or_cl_tampering(case: str) -> None:
    text, index, feature, packet = _qi_asi_excerpt_inputs()
    section = feature["source_sections"][0]
    if case == "trailing_space":
        section["source_markdown"] = section["source_markdown"].rstrip("\n") + " \n"
    elif case == "trailing_content":
        section["source_markdown"] = section["source_markdown"].rstrip("\n") + "\nForged trailing content\n"
    else:
        original_section = "".join(
            text.splitlines(keepends=True)[section["source_line_start"] - 1 : section["source_line_end"]]
        )
        matching_line = "At CL4, CL8, CL12, CL16, and CL19, choose one of the following:\n"
        duplicated_section = original_section.replace(matching_line, matching_line + matching_line, 1)
        text = duplicated_section
        section.update(
            source_line_start=1,
            source_line_end=len(text.splitlines(keepends=True)),
            source_markdown=text,
        )
    assert materializer._bridge_exact_path_excerpt(
        text,
        path_record=index,
        packet=packet,
        feature_record=feature,
    ) is None


@_REQUIRES_VENDOR_FIXTURE
def test_packet_bridge_missing_subpath_master_cannot_use_legacy_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packet = _public_alchemical_subpath_packet()
    original = materializer._bridge_fixed_json

    def missing_subpath_master(relative_path: str, expected_sha256: str) -> Mapping[str, Any] | None:
        if relative_path == materializer._PACKET_SUBPATH_MASTER_PATH:
            return None
        return original(relative_path, expected_sha256)

    monkeypatch.setattr(materializer, "_bridge_fixed_json", missing_subpath_master)
    workspace = _public_packet_bridge_workspace(tmp_path, [packet])
    with pytest.raises(FoundryError) as error:
        materializer._bridge_rules_packet_registry(workspace, CORPUS)
    assert error.value.code == "FINAL_CHARACTER_PACKET_BRIDGE_UNRESOLVED"


@_REQUIRES_VENDOR_FIXTURE
def test_packet_bridge_nonexact_subpath_status_is_not_active(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packet = _public_alchemical_subpath_packet()
    original = materializer._bridge_fixed_json

    def forged_status(relative_path: str, expected_sha256: str) -> Mapping[str, Any] | None:
        value = original(relative_path, expected_sha256)
        if relative_path == materializer._PACKET_SUBPATH_MASTER_PATH and value is not None:
            value = deepcopy(value)
            row = next(item for item in value["entries"] if item["canonical_id"] == packet["record_id"])
            row["status"] = "PASS_FORGED"
        return value

    monkeypatch.setattr(materializer, "_bridge_fixed_json", forged_status)
    workspace = _public_packet_bridge_workspace(tmp_path, [packet])
    with pytest.raises(FoundryError) as error:
        materializer._bridge_rules_packet_registry(workspace, CORPUS)
    assert error.value.code == "FINAL_CHARACTER_PACKET_BRIDGE_UNRESOLVED"


def _qi_subpath_excerpt_inputs() -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]:
    _active, corpus_texts = materializer._corpus_active_texts(CORPUS)
    proof = materializer._PACKET_PATH_PROOFS["tianxia.path.qi_cultivation"]
    index = materializer._bridge_fixed_json(proof["index_path"], proof["index_sha256"])
    assert index is not None
    feature = next(
        row
        for row in index["features"]
        if row["canonical_id"] == "tianxia.path.qi_cultivation.feature.qi_cultivation_subpath"
    )
    packet = _public_packet(
        "packet.public.qi-subpath-direct",
        "tianxia.path.qi_cultivation.feature.qi_cultivation_subpath",
        "Qi Cultivation Subpath",
        proof["index_path"],
        proof["index_sha256"],
        "path-feature:tianxia.path.qi_cultivation:tianxia.path.qi_cultivation.feature.qi_cultivation_subpath",
        target_cl=3,
    )
    return corpus_texts[proof["corpus_path"]], index, deepcopy(feature), packet


@pytest.mark.parametrize("case", ["prefix", "heading", "zero", "multiple", "superset"])
@_REQUIRES_VENDOR_FIXTURE
def test_packet_bridge_qi_subpath_excerpt_rejects_section_or_line_tampering(
    case: str,
) -> None:
    text, index, feature, packet = _qi_subpath_excerpt_inputs()
    section = feature["source_sections"][0]
    if case == "prefix":
        section["source_markdown"] = section["source_markdown"].splitlines(keepends=True)[0]
    elif case == "heading":
        section["source_heading"] = "Qi Cultivation Rules"
    elif case == "zero":
        packet["display_name"] = "Unpublished Qi Subpath"
    elif case == "multiple":
        original_section = "".join(
            text.splitlines(keepends=True)[section["source_line_start"] - 1 : section["source_line_end"]]
        )
        matching_line = next(line for line in original_section.splitlines(keepends=True)
                             if hashlib.sha256(line.rstrip("\n").encode()).hexdigest()
                             == QI_SUBPATH_CL3_SHA256)
        duplicated_section = original_section.replace(matching_line, matching_line + matching_line, 1)
        text = duplicated_section
        section.update(
            source_line_start=1,
            source_line_end=len(text.splitlines(keepends=True)),
            source_markdown=text,
        )
    elif case == "superset":
        text = "## Qi Cultivation Subpaths\nAt CL3, choose one Qi Cultivation Subpaths.\n"
        section.update(
            source_line_start=1,
            source_line_end=2,
            source_markdown=text,
        )
    assert materializer._bridge_exact_path_excerpt(
        text,
        path_record=index,
        packet=packet,
        feature_record=feature,
    ) is None


@_REQUIRES_VENDOR_FIXTURE
def test_packet_bridge_known_modern_id_cannot_fall_through_legacy_evidence(tmp_path: Path) -> None:
    """Known modern IDs remain blocked when both modern markers are replaced."""

    _active, corpus_texts = materializer._corpus_active_texts(CORPUS)
    legacy_path = "Needed/Tianxia_Methods_Master_v0_1.md"
    legacy_text = corpus_texts[legacy_path]
    packet = _public_packet(
        "packet.public.known-modern-legacy-tuple",
        "METHOD-001",
        "Outer Gate Root Method",
        legacy_path,
        materializer._sha256_text(legacy_text),
        "heading:Outer Gate Root Method",
    )
    workspace = _public_packet_bridge_workspace(tmp_path, [packet])
    with pytest.raises(FoundryError) as error:
        materializer._bridge_rules_packet_registry(workspace, CORPUS)
    assert error.value.code == "FINAL_CHARACTER_PACKET_BRIDGE_UNRESOLVED"
    assert "METHOD-001" in str(error.value.details)


@_REQUIRES_VENDOR_FIXTURE
def test_packet_bridge_rejects_wrong_feature_target_cl(tmp_path: Path) -> None:
    packet = _public_packet(
        "packet.public.qi-feature-wrong-cl",
        "tianxia.path.qi_cultivation.feature.qi_sensing",
        "Qi Sensing",
        materializer._PACKET_PATH_PROOFS["tianxia.path.qi_cultivation"]["index_path"],
        materializer._PACKET_PATH_PROOFS["tianxia.path.qi_cultivation"]["index_sha256"],
        "path-feature:tianxia.path.qi_cultivation:tianxia.path.qi_cultivation.feature.qi_sensing",
        target_cl=2,
    )
    workspace = _public_packet_bridge_workspace(tmp_path, [packet])
    with pytest.raises(FoundryError) as error:
        materializer._bridge_rules_packet_registry(workspace, CORPUS)
    assert error.value.code == "FINAL_CHARACTER_PACKET_BRIDGE_UNRESOLVED"
    assert "packet.public.qi-feature-wrong-cl" in str(error.value.details)


@_REQUIRES_VENDOR_FIXTURE
def test_packet_bridge_rejects_fixed_method_registry_symlink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app_root = tmp_path / "fake-app-root"
    registry = fake_app_root / materializer._PACKET_METHOD_SOURCE_PATH
    registry.parent.mkdir(parents=True)
    installed_registry = Path(materializer.__file__).resolve().parents[1] / materializer._PACKET_METHOD_SOURCE_PATH
    registry.symlink_to(installed_registry)
    monkeypatch.setattr(materializer, "_FINAL_CHARACTER_APP_ROOT", fake_app_root)
    packet = _public_packet(
        "packet.public.method-registry-symlink",
        "METHOD-001",
        "Outer Gate Root Method",
        materializer._PACKET_METHOD_SOURCE_PATH,
        materializer._PACKET_METHOD_SOURCE_SHA256,
        "method:METHOD-001",
    )
    workspace = _public_packet_bridge_workspace(tmp_path, [packet])
    with pytest.raises(FoundryError) as error:
        materializer._bridge_rules_packet_registry(workspace, CORPUS)
    assert error.value.code == "FINAL_CHARACTER_PACKET_BRIDGE_UNRESOLVED"


@_REQUIRES_VENDOR_FIXTURE
def test_packet_bridge_unavailable_foundation_registry_blocks_nonprefixed_known_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lower-case known Foundation ID cannot use legacy fallback on registry loss."""

    _active, corpus_texts = materializer._corpus_active_texts(CORPUS)
    legacy_path = "Needed/Tianxia_Methods_Master_v0_1.md"
    packet = _public_packet(
        "packet.public.foundation-registry-unavailable",
        "ancient_desolate_sacred_body_v0_2C",
        "Ancient Desolate Sacred Body",
        legacy_path,
        materializer._sha256_text(corpus_texts[legacy_path]),
        "heading:Outer Gate Root Method",
    )
    monkeypatch.setattr(materializer, "_bridge_fixed_factory_json", lambda *_args: None)
    workspace = _public_packet_bridge_workspace(tmp_path, [packet])
    with pytest.raises(FoundryError) as error:
        materializer._bridge_rules_packet_registry(workspace, CORPUS)
    assert error.value.code == "FINAL_CHARACTER_PACKET_BRIDGE_UNRESOLVED"
    assert "ancient_desolate_sacred_body_v0_2C" in str(error.value.details)


@pytest.mark.parametrize(
    ("family", "mutator"),
    [
        ("method", lambda row: row.update(record_id="METHOD-001-FORGED")),
        ("method", lambda row: row["source_evidence"][0].update(source_anchor="method:METHOD-002")),
        ("method", lambda row: row["source_evidence"][0].update(source_hash="0" * 64)),
        ("method", lambda row: row.update(display_name="Ash-Breath Furnace Method")),
        ("foundation", lambda row: row.update(record_id="FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR")),
        ("foundation", lambda row: row["source_evidence"][0].update(source_anchor="foundation:other")),
        ("path", lambda row: row["source_evidence"][0].update(source_path=materializer._PACKET_PATH_PROOFS["tianxia.path.body_refining"]["index_path"], source_hash=materializer._PACKET_PATH_PROOFS["tianxia.path.body_refining"]["index_sha256"])),
        ("path", lambda row: row.update(record_id="tianxia.path.qi_cultivation.feature.not_published", display_name="Not Published")),
    ],
)
@_REQUIRES_VENDOR_FIXTURE
def test_packet_bridge_public_authority_forgery_and_cross_path_reject(
    tmp_path: Path,
    family: str,
    mutator: Any,
) -> None:
    if family == "method":
        packet = _public_packet(
            "packet.public.forged-method",
            "METHOD-001",
            "Outer Gate Root Method",
            materializer._PACKET_METHOD_SOURCE_PATH,
            materializer._PACKET_METHOD_SOURCE_SHA256,
            "method:METHOD-001",
        )
    elif family == "foundation":
        packet = _public_packet(
            "packet.public.forged-foundation",
            "furnace_heart_record_v0_2B",
            "Furnace Heart Record",
            materializer._PACKET_FOUNDATION_SOURCE_PATH,
            materializer._PACKET_FOUNDATION_SOURCE_SHA256,
            "foundation:furnace_heart_record_v0_2B",
        )
    else:
        packet = _public_packet(
            "packet.public.forged-path",
            "tianxia.path.qi_cultivation",
            "Qi Cultivation",
            materializer._PACKET_PATH_PROOFS["tianxia.path.qi_cultivation"]["index_path"],
            materializer._PACKET_PATH_PROOFS["tianxia.path.qi_cultivation"]["index_sha256"],
            "path:tianxia.path.qi_cultivation",
        )
    mutator(packet)
    workspace = _public_packet_bridge_workspace(tmp_path, [packet])
    with pytest.raises(FoundryError) as error:
        materializer._bridge_rules_packet_registry(workspace, CORPUS)
    assert error.value.code == "FINAL_CHARACTER_PACKET_BRIDGE_UNRESOLVED"
    assert packet["packet_id"] in str(error.value.details)


@_REQUIRES_ACCEPTED_FIXTURE
def test_real_pinned_compiler_retains_the_known_registry_blocker(tmp_path: Path) -> None:
    (tmp_path / "Build").mkdir()
    (tmp_path / "Command_2").mkdir()
    (tmp_path / "Build/Character_Master_Ledger.json").write_bytes((SOURCE / "Build/Character_Master_Ledger.json").read_bytes())
    (tmp_path / "Command_2/Rules_Selection_Packets.json").write_bytes((SOURCE / "Command_2/Rules_Selection_Packets.json").read_bytes())
    with pytest.raises(FoundryError) as error:
        materializer._run_pinned_compiler(COMPILER, CORPUS, tmp_path)
    assert error.value.code == "FINAL_CHARACTER_COMPILER_REJECTED"
    assert "MISSING_REQUIRED:packet.packet.stage2.001.37ef6150f35e6238.authority" in str(error.value.details)
    assert not list(tmp_path.glob(materializer.FINAL_CHARACTER_COMPILER_OUTPUT_DIRNAME + "/**/*"))


def test_compiler_and_corpus_paths_are_not_publicly_configurable() -> None:
    with pytest.raises(TypeError):
        FinalCharacterMaterializer(compiler_path=COMPILER, corpus_path=CORPUS)  # type: ignore[call-arg]


def test_partial_stage_write_failure_is_cleaned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stage = tmp_path / ".final-character-materializer-stage"
    stage.mkdir()

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("injected partial write")

    monkeypatch.setattr(materializer.os, "fsync", fail_fsync)
    with pytest.raises(OSError):
        materializer._atomic_write_bytes(stage / "receipt.json", b"partial-stage-receipt")
    assert not (stage / "receipt.json").exists()
    assert not list(stage.glob("*.tmp"))


def test_existing_content_addressed_collision_is_fail_closed(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "workspace").mkdir()
    final = tmp_path / "content-addressed-final"
    final.mkdir()
    (final / "preexisting").write_text("keep", encoding="utf-8")
    with pytest.raises(FoundryError) as error:
        materializer._atomic_publish_noreplace(stage, final)
    assert error.value.code == "FINAL_CHARACTER_COLLISION"
    assert (final / "preexisting").read_text(encoding="utf-8") == "keep"
    assert stage.is_dir()


def test_bound_cleanup_removes_normal_copied_source_tree(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "nested").mkdir(parents=True)
    (source / "nested/secret.json").write_text("sealed source bytes", encoding="utf-8")
    output_root = tmp_path / "output"
    output_root.mkdir(mode=0o700)
    bound = materializer._ensure_private_output_root(output_root)
    stage = bound.create_bound_temp_dir(".stage-")
    workspace = stage.create_bound_child("workspace")
    materializer._copy_tree_no_symlinks(source, workspace)
    stage_name = stage.name
    try:
        raise FoundryError("FINAL_CHARACTER_BAD_STAMINA_MAPPING", "synthetic semantic blocker")
    except FoundryError:
        stage.cleanup()
    finally:
        workspace.close()
        bound.close()
    assert not (output_root / stage_name).exists()
    assert (source / "nested/secret.json").read_text(encoding="utf-8") == "sealed source bytes"


def test_bound_cleanup_reopens_poisoned_directory_enumeration(tmp_path: Path) -> None:
    """Cleanup must not inherit an exhausted directory-stream cursor."""

    output_root = tmp_path / "poisoned-cleanup-output"
    output_root.mkdir(mode=0o700)
    bound = materializer._ensure_private_output_root(output_root)
    child = bound.create_bound_temp_dir(".child-")
    nested = child.fd_path / "nested"
    nested.mkdir()
    (nested / "sealed.json").write_bytes(b"copied sealed bytes")
    child_name = child.name
    # Exercise the exact failure mode: consume the held descriptor's
    # directory enumeration before cleanup gets its own fresh descriptor.
    os.listdir(child.fd)
    os.listdir(child.fd)
    try:
        child.cleanup()
    finally:
        bound.close()
    assert not (output_root / child_name).exists()


def _hidden_tool_cache_action() -> dict[str, Any]:
    return {
        "action_id": "action.synthetic.hidden_tool_cache",
        "record_id": "tianxia.background_talent.scoundrel.hidden_tool_cache",
        "economy": "bonus_action",
        "cost": "None",
        "resource_costs": [],
        "resource_requirements": [],
        "state_arrays": [],
    }


def test_runtime_controller_preconditions_keep_hidden_tool_cache_notes_advisory() -> None:
    """Provider planning notes cannot become executable runtime authority."""

    action = _hidden_tool_cache_action()
    step = {
        "cost": "None",
        "resource_costs": [],
        "resource_requirements": [],
        "requires_states": [],
        "external_preconditions": [
            "Use only a mundane object already prepared before combat.",
            "Do not activate or consume the revealed object.",
        ],
    }
    metadata = materializer._runtime_step_metadata(action, step, field="sequence.synthetic")
    assert metadata["external_preconditions"] == []
    assert metadata["advisory_external_preconditions"] == {
        "execution_authority": False,
        "values": step["external_preconditions"],
    }
    runtime_ref = materializer._runtime_action_ref(
        action,
        economy="bonus_action",
        round_offset=0,
        costs=metadata["resource_costs"],
        requires_states=metadata["requires_states"],
        external_preconditions=metadata["external_preconditions"],
        advisory_external_preconditions=metadata["advisory_external_preconditions"],
    )
    assert runtime_ref["external_preconditions"] == []
    assert runtime_ref["advisory_external_preconditions"]["execution_authority"] is False


@pytest.mark.parametrize(
    "notes",
    [
        [""],
        ["valid", 1],
        ["x" * 513],
        ["x"] * 17,
        ["x" * 512] * 9,
    ],
)
def test_runtime_controller_rejects_malformed_or_oversized_advisory_notes(notes: Any) -> None:
    with pytest.raises(FoundryError) as error:
        materializer._runtime_step_metadata(
            _hidden_tool_cache_action(),
            {"external_preconditions": notes},
            field="sequence.synthetic",
        )
    assert error.value.code == "FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE"


def test_runtime_controller_rejects_provider_resource_state_precondition_forgery() -> None:
    action = _hidden_tool_cache_action()
    with pytest.raises(FoundryError) as error:
        materializer._runtime_step_metadata(
            action,
            {
                "resource_requirements": [{"resource_id": "RES_CP", "minimum": 1}],
                "requires_states": ["prepared_object"],
                "external_preconditions": ["Qi >= 1"],
            },
            field="sequence.synthetic",
        )
    assert error.value.code == "FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE"


def _successful_runtime_controller_fixture(
    tmp_path: Path,
    *,
    resource_id: str = "tianxia.resource.stamina",
    resource_name: str = "Stamina",
    path_id: str = "tianxia.path.body_refining",
    path_name: str = "Body Refining",
    current: int = 1,
    maximum: int = 45,
) -> tuple[Path, dict[str, Any]]:
    """Build a public-safe canonical surface and reviewed controller shape."""

    workspace = tmp_path / "runtime-controller-workspace"
    surface_dir = workspace / "Command_4"
    surface_dir.mkdir(parents=True)
    character = {
        "path_id": path_id,
        "path": path_name,
        "paths": [{"path_id": path_id, "display_name": path_name}],
    }
    resource_row = {
        "resource_id": resource_id,
        "name": resource_name,
        "current": current,
        "max": maximum,
    }
    ledger = {"character": character, "resources": [resource_row]}
    (workspace / "Build").mkdir()
    (workspace / "Command_2").mkdir()
    (workspace / "Build/Character_Master_Ledger.json").write_text(
        json.dumps(ledger, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (workspace / "Command_2/Canonical_Stats_Resource_Block.json").write_text(
        json.dumps(ledger, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    actions = [
        _hidden_tool_cache_action(),
        {
            "action_id": "action.synthetic.dirty_trick",
            "record_id": "tianxia.background_talent.scoundrel.dirty_trick",
            "name": "Dirty Trick",
            "economy": "action",
            "cost": "None",
            "resource_costs": [],
            "resource_requirements": [{"resource_id": resource_id, "minimum": 1}],
            "state_arrays": [],
        },
        {
            "action_id": "action.synthetic.steal",
            "record_id": "tianxia.background_talent.scoundrel.steal",
            "name": "Steal",
            "economy": "action",
            "cost": "None",
            "resource_costs": [],
            "resource_requirements": [{"resource_id": resource_id, "minimum": 1}],
            "state_arrays": [],
        },
    ]
    (surface_dir / "Complete_Action_Surface.json").write_text(
        json.dumps({"actions": actions}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    note_by_action = {
        actions[0]["action_id"]: ["Reveal only a previously prepared mundane object."],
        actions[1]["action_id"]: ["Use a plausible opening created by the revealed object."],
        actions[2]["action_id"]: ["Attempt this only when one accessible object is exposed."],
    }

    def step(action: dict[str, Any], *, offset: int = 0) -> dict[str, Any]:
        return {
            "action": deepcopy(action),
            "round_offset": offset,
            "external_preconditions": note_by_action[action["action_id"]],
        }

    artifact = {
        "source_workspace_sha256": "a" * 64,
        "resource_authority": {
            "alias": "RES_CP",
            "resource_id": resource_id,
            "name": resource_name,
            "current": current,
            "maximum": maximum,
            "source_backed": True,
        },
        "linked_actions": deepcopy(actions),
        "composite_controller": {
            "composite_id": "composite_controller",
            "name": "Synthetic bounded controller",
            "sequence": [step(actions[0]), step(actions[1])],
            "fallback": step(actions[2]),
            "conditional_options": [step(actions[2])],
            "resource_budget": {
                "alias": "RES_CP",
                "resource_id": resource_id,
                "max_spend": maximum,
                "total_sequence_cost": 0,
            },
            "when_to_use": ["A bounded synthetic combat opening exists."],
            "do_not_use_when": ["No valid action opportunity exists."],
            "temporal_feasibility": {"same_turn_legal": True, "round_span": 1, "notes": []},
            "execution_role": "composite_controller",
            "dao_hook": "synthetic",
            "i_ching_hook": "synthetic",
        },
    }
    return workspace, artifact


def test_runtime_controller_successfully_projects_sequence_fallback_and_conditional_notes(tmp_path: Path) -> None:
    workspace, artifact = _successful_runtime_controller_fixture(tmp_path)
    runtime = materializer._build_runtime_controller(
        workspace,
        artifact,
        {},
        overlay_id="synthetic-overlay",
        overlay_tree_sha256="b" * 64,
    )

    projected = [*runtime["sequence"], runtime["fallback"], *runtime["conditional_options"]]
    assert len(runtime["sequence"]) == 2
    assert runtime["fallback"]["fallback"] is True
    assert len(runtime["conditional_options"]) == 1
    assert [ref["external_preconditions"] for ref in projected] == [
        [],
        ["Stamina >= 1"],
        ["Stamina >= 1"],
        ["Stamina >= 1"],
    ]
    assert all(ref["advisory_external_preconditions"]["execution_authority"] is False for ref in projected)
    assert [
        ref["advisory_external_preconditions"]["values"][0]
        for ref in projected
    ] == [
        "Reveal only a previously prepared mundane object.",
        "Use a plausible opening created by the revealed object.",
        "Attempt this only when one accessible object is exposed.",
        "Attempt this only when one accessible object is exposed.",
    ]
    assert runtime["resource_authority"] == {
        "alias": "RES_CP",
        "resource_id": "tianxia.resource.stamina",
        "name": "Stamina",
        "current": 1,
        "maximum": 45,
        "source_backed": True,
    }
    assert runtime["resource_budget"]["resource_id"] == "tianxia.resource.stamina"
    assert runtime["resource_budget"]["max_spend"] == 45


def _command4_promotion_fixture(
    tmp_path: Path,
    *,
    gained_at_cl: int = 15,
) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Build a public-safe, already assembled Command 4 staging shape."""

    workspace = tmp_path / "command4-promotion-workspace"
    for relative in ("Build", "Command_4", "Validation"):
        (workspace / relative).mkdir(parents=True)
    linked = {
        "action_id": "action.synthetic.immortal",
        "record_id": "talent.synthetic.source",
        "immortal_art_id": "immortal.synthetic",
        "classification": materializer.IMMORTAL_ART_CLASSIFICATION,
        "action_type": "action",
        "economy": "action",
    }
    synthetic_composite_artifact_sha256 = materializer.sha256_json({"artifact_id": "composite.synthetic"})
    art_row = {
        "immortal_art_id": linked["immortal_art_id"],
        "name": "Synthetic Art",
        "gained_at_cl": gained_at_cl,
        "action_ids": [linked["action_id"]],
    }
    ledger = {
        "schema_version": "HF05ZVK-R1F",
        "status": "COMMAND_2_ADVANCEMENT_LEDGER_SEALED",
        "build_mode": "production",
        "character": {"cl": gained_at_cl, "realm": "Nascent Soul"},
        "actions": [deepcopy(linked)],
        "immortal_arts": [deepcopy(art_row)],
    }
    for relative in ("Build/Complete_Action_Surface.json", "Command_4/Complete_Action_Surface.json"):
        (workspace / relative).write_text(
            json.dumps({"actions": [deepcopy(linked)]}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    (workspace / "Build/Character_Master_Ledger.json").write_text(
        json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8"
    )
    runtime = {
        "schema_version": materializer.FINAL_CHARACTER_RUNTIME_CONTROLLER_SCHEMA,
        "controller_id": materializer.FINAL_CHARACTER_CONTROLLER_ID,
        "execution_authority": True,
        "controller_policy_registered": True,
        "sequence": [{"action_id": linked["action_id"], "record_id": linked["record_id"]}],
        "fallback": {"action_id": linked["action_id"], "record_id": linked["record_id"]},
        "canonical_action_bindings": [{
            "action_id": linked["action_id"],
            "record_id": linked["record_id"],
            "action_sha256": materializer.sha256_json(linked),
        }],
        "linked_actions": [{
            "action_id": linked["action_id"],
            "record_id": linked["record_id"],
            "action_sha256": materializer.sha256_json(linked),
        }],
        "resource_authority": {
            "alias": "RES_CP",
            "resource_id": "tianxia.resource.qi",
            "name": "Qi",
            "current": 2,
            "maximum": 60,
            "source_backed": True,
        },
        "resource_budget": {
            "alias": "RES_CP",
            "resource_id": "tianxia.resource.qi",
            "max_spend": 0,
            "total_sequence_cost": 0,
        },
        "overlay_lineage": {
            "overlay_id": "composite.synthetic",
            "artifact_sha256": synthetic_composite_artifact_sha256,
            "overlay_tree_sha256": "a" * 64,
            "source_workspace_sha256": "b" * 64,
            "display_only_provenance_retained": True,
        },
    }
    for relative in ("Build/Composite_Controller.json", "Command_4/Composite_Controller.json"):
        (workspace / relative).write_text(json.dumps(runtime, sort_keys=True) + "\n", encoding="utf-8")
    (workspace / "Validation/Composite_Controller.validation.json").write_text(
        json.dumps({
            "schema_version": "TianxiaFoundry.CompositeControllerValidation.v1",
            "valid": True,
            "execution_authority": True,
            "controller_policy_registered": True,
            "artifact_sha256": synthetic_composite_artifact_sha256,
        }, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    artifact = {
        "arts": [deepcopy(art_row)],
        "action_ids": [linked["action_id"]],
        "actions": [deepcopy(linked)],
    }
    projection = {
        "equal": True,
        "immortal_action_ids": [linked["action_id"]],
        "ledger_action_sha256": materializer.sha256_json([linked]),
        "complete_action_surface_sha256": materializer.sha256_json([linked]),
        "command4_action_surface_sha256": materializer.sha256_json([linked]),
    }
    return workspace, linked, runtime, artifact, projection


def test_command4_promotion_is_copy_only_and_requires_complete_assembly(tmp_path: Path) -> None:
    workspace, linked, runtime, artifact, projection = _command4_promotion_fixture(tmp_path)
    source_snapshot = _snapshot(workspace)
    staged = tmp_path / "staged-command4-promotion"
    shutil.copytree(workspace, staged)
    evidence = materializer._promote_materialized_command4_ledger(
        staged,
        runtime_controller=runtime,
        action_projection=projection,
        immortal_translation=artifact,
    )
    promoted = json.loads((staged / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8"))
    source_ledger = json.loads((workspace / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8"))
    assert source_ledger["status"] == "COMMAND_2_ADVANCEMENT_LEDGER_SEALED"
    assert source_snapshot == _snapshot(workspace)
    assert promoted["status"] == "COMMAND_4_EXECUTABLE_CHARACTER_COMPLETE"
    assert set(promoted) == {"schema_version", "status", "build_mode", "character", "actions", "immortal_arts"}
    assert evidence["validated"] is True
    assert evidence["immortal_action_ids"] == [linked["action_id"]]


def test_command4_promotion_accepts_later_nascent_soul_acquisition(tmp_path: Path) -> None:
    workspace, _linked, runtime, artifact, projection = _command4_promotion_fixture(
        tmp_path,
        gained_at_cl=16,
    )
    evidence = materializer._promote_materialized_command4_ledger(
        workspace,
        runtime_controller=runtime,
        action_projection=projection,
        immortal_translation=artifact,
    )
    assert evidence["immortal_acquired_at_cls"] == [16]
    assert json.loads((workspace / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8"))["status"] == "COMMAND_4_EXECUTABLE_CHARACTER_COMPLETE"


@pytest.mark.parametrize(
    "forgery",
    ("status", "surface", "projection", "runtime", "immortal", "lineage", "missing_lineage", "cl_binding", "missing_art"),
)
def test_command4_promotion_rejects_incomplete_or_unvalidated_assembly(tmp_path: Path, forgery: str) -> None:
    workspace, _linked, runtime, artifact, projection = _command4_promotion_fixture(tmp_path / forgery)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    if forgery == "status":
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        ledger["status"] = "COMMAND_4_EXECUTABLE_CHARACTER_COMPLETE"
        ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    elif forgery == "surface":
        (workspace / "Command_4/Complete_Action_Surface.json").write_text(
            json.dumps({"actions": []}) + "\n", encoding="utf-8"
        )
    elif forgery == "projection":
        projection["equal"] = False
    elif forgery == "runtime":
        (workspace / "Build/Composite_Controller.json").unlink()
    elif forgery == "lineage":
        runtime["overlay_lineage"]["artifact_sha256"] = "f" * 64
        for relative in ("Build/Composite_Controller.json", "Command_4/Composite_Controller.json"):
            (workspace / relative).write_text(json.dumps(runtime, sort_keys=True) + "\n", encoding="utf-8")
    elif forgery == "missing_lineage":
        runtime.pop("overlay_lineage")
        for relative in ("Build/Composite_Controller.json", "Command_4/Composite_Controller.json"):
            (workspace / relative).write_text(json.dumps(runtime, sort_keys=True) + "\n", encoding="utf-8")
    elif forgery == "cl_binding":
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        ledger["character"]["realm"] = "True Immortality"
        ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    elif forgery == "missing_art":
        # RAW-182: a CL15+ character must carry its Immortal Art.
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        ledger["immortal_arts"] = []
        ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
        artifact["arts"] = []
    else:
        artifact["arts"][0]["name"] = "Forged Art"
    with pytest.raises(FoundryError) as error:
        materializer._promote_materialized_command4_ledger(
            workspace,
            runtime_controller=runtime,
            action_projection=projection,
            immortal_translation=artifact,
        )
    assert error.value.code == "FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID"
    current = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert current["status"] == (
        "COMMAND_4_EXECUTABLE_CHARACTER_COMPLETE"
        if forgery == "status"
        else "COMMAND_2_ADVANCEMENT_LEDGER_SEALED"
    )


@pytest.mark.parametrize(
    ("resource_id", "resource_name", "path_id", "path_name", "current", "maximum"),
    [
        ("tianxia.resource.stamina", "Stamina", "tianxia.path.body_refining", "Body Refining", 1, 45),
        ("tianxia.resource.qi", "Qi", "tianxia.path.qi_cultivation", "Qi Cultivation", 2, 60),
        ("tianxia.resource.resonance", "Resonance", "tianxia.path.spirit_awakening", "Spirit Awakening", 3, 72),
    ],
)
def test_runtime_controller_binds_all_active_path_resources_and_dynamic_maxima(
    tmp_path: Path,
    resource_id: str,
    resource_name: str,
    path_id: str,
    path_name: str,
    current: int,
    maximum: int,
) -> None:
    workspace, artifact = _successful_runtime_controller_fixture(
        tmp_path,
        resource_id=resource_id,
        resource_name=resource_name,
        path_id=path_id,
        path_name=path_name,
        current=current,
        maximum=maximum,
    )
    runtime = materializer._build_runtime_controller(
        workspace,
        artifact,
        {},
        overlay_id="synthetic-overlay",
        overlay_tree_sha256="c" * 64,
    )
    assert runtime["resource_authority"]["resource_id"] == resource_id
    assert runtime["resource_authority"]["name"] == resource_name
    assert runtime["resource_authority"]["current"] == current
    assert runtime["resource_authority"]["maximum"] == maximum
    assert runtime["resource_budget"]["resource_id"] == resource_id
    assert runtime["resource_budget"]["max_spend"] == maximum
    assert runtime["resource_budget"]["total_sequence_cost"] == 0
    assert runtime["sequence"][0]["external_preconditions"] == []
    expected_requirement = [{"resource_id": resource_id, "minimum": 1}]
    assert runtime["sequence"][1]["resource_requirements"] == expected_requirement
    assert runtime["sequence"][1]["external_preconditions"] == [f"{resource_name} >= 1"]
    assert runtime["fallback"]["resource_requirements"] == expected_requirement
    assert runtime["fallback"]["external_preconditions"] == [f"{resource_name} >= 1"]
    assert runtime["conditional_options"][0]["resource_requirements"] == expected_requirement
    assert runtime["conditional_options"][0]["external_preconditions"] == [f"{resource_name} >= 1"]


def test_runtime_controller_rejects_cross_path_budget_and_forged_artifact_authority(tmp_path: Path) -> None:
    workspace, artifact = _successful_runtime_controller_fixture(
        tmp_path,
        resource_id="tianxia.resource.qi",
        resource_name="Qi",
        path_id="tianxia.path.qi_cultivation",
        path_name="Qi Cultivation",
        current=2,
        maximum=60,
    )
    artifact["composite_controller"]["resource_budget"]["resource_id"] = "tianxia.resource.stamina"
    with pytest.raises(FoundryError) as error:
        materializer._build_runtime_controller(
            workspace,
            artifact,
            {},
            overlay_id="synthetic-overlay",
            overlay_tree_sha256="d" * 64,
        )
    assert error.value.code == "FINAL_CHARACTER_CONTROLLER_RESOURCE_AUTHORITY_INVALID"

    workspace, artifact = _successful_runtime_controller_fixture(
        tmp_path / "source-mismatch",
        resource_id="tianxia.resource.qi",
        resource_name="Qi",
        path_id="tianxia.path.qi_cultivation",
        path_name="Qi Cultivation",
        current=2,
        maximum=60,
    )
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["resources"][0]["resource_id"] = "tianxia.resource.stamina"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(FoundryError) as error:
        materializer._build_runtime_controller(
            workspace,
            artifact,
            {},
            overlay_id="synthetic-overlay",
            overlay_tree_sha256="s" * 64,
        )
    assert error.value.code == "FINAL_CHARACTER_CONTROLLER_RESOURCE_AUTHORITY_INVALID"

    workspace, artifact = _successful_runtime_controller_fixture(
        tmp_path / "forged-authority",
        resource_id="tianxia.resource.qi",
        resource_name="Qi",
        path_id="tianxia.path.qi_cultivation",
        path_name="Qi Cultivation",
        current=2,
        maximum=60,
    )
    artifact["resource_authority"]["maximum"] = 45
    with pytest.raises(FoundryError) as error:
        materializer._build_runtime_controller(
            workspace,
            artifact,
            {},
            overlay_id="synthetic-overlay",
            overlay_tree_sha256="e" * 64,
        )
    assert error.value.code == "FINAL_CHARACTER_CONTROLLER_RESOURCE_AUTHORITY_INVALID"


@pytest.mark.parametrize("field", ("resource_costs", "resource_requirements"))
def test_runtime_controller_rejects_cross_path_action_rows(tmp_path: Path, field: str) -> None:
    workspace, artifact = _successful_runtime_controller_fixture(
        tmp_path,
        resource_id="tianxia.resource.qi",
        resource_name="Qi",
        path_id="tianxia.path.qi_cultivation",
        path_name="Qi Cultivation",
        current=2,
        maximum=60,
    )
    surface_path = workspace / "Command_4/Complete_Action_Surface.json"
    surface = json.loads(surface_path.read_text(encoding="utf-8"))
    forged_rows = (
        [{"resource_id": "tianxia.resource.stamina", "amount": 1}]
        if field == "resource_costs"
        else [{"resource_id": "tianxia.resource.stamina", "minimum": 1}]
    )
    surface["actions"][1][field] = forged_rows
    surface_path.write_text(json.dumps(surface, sort_keys=True) + "\n", encoding="utf-8")
    artifact["linked_actions"][1][field] = deepcopy(forged_rows)
    artifact["composite_controller"]["sequence"][1]["action"][field] = deepcopy(forged_rows)
    with pytest.raises(FoundryError) as error:
        materializer._build_runtime_controller(
            workspace,
            artifact,
            {},
            overlay_id="synthetic-overlay",
            overlay_tree_sha256="f" * 64,
        )
    assert error.value.code in {
        "FINAL_CHARACTER_UNKNOWN_RUNTIME_RESOURCE",
        "FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE",
    }


@_REQUIRES_ACCEPTED_FIXTURE
def test_composite_action_divergence_is_not_promoted_to_runtime(tmp_path: Path) -> None:
    from factory_authoring.composite_controller import CompositeControllerAuthoring

    composite_validated = CompositeControllerAuthoring.validate_overlay(COMPOSITE, source_workspace=SOURCE)
    forged = deepcopy(composite_validated)
    forged["artifact"]["linked_actions"][0]["effect"] = "forged runtime effect"
    workspace = tmp_path / "workspace"
    materializer._copy_tree_no_symlinks(SOURCE, workspace)
    with pytest.raises(FoundryError) as error:
        materializer._build_runtime_controller(
            workspace,
            forged["artifact"],
            forged["manifest"],
            overlay_id=str(forged["overlay_id"]),
            overlay_tree_sha256=materializer._tree_hash(COMPOSITE),
        )
    assert error.value.code == "FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE"


@pytest.mark.parametrize("field,value", [("economy", "action"), ("cost", "forged cost"), ("resource_costs", [{"resource_id": "tianxia.resource.stamina", "amount": 2}])])
@_REQUIRES_ACCEPTED_FIXTURE
def test_conditional_option_must_match_canonical_mechanics(tmp_path: Path, field: str, value: Any) -> None:
    composite_validated = materializer.CompositeControllerAuthoring.validate_overlay(COMPOSITE, source_workspace=SOURCE)
    forged = deepcopy(composite_validated)
    canonical = deepcopy(forged["artifact"]["linked_actions"][1])
    option = {
        "action": canonical,
        "action_id": canonical["action_id"],
        "record_id": canonical["record_id"],
        "economy": canonical["economy"],
        "resource_costs": [{"resource_id": "tianxia.resource.stamina", "amount": 1}],
        "requires_states": [],
        "external_preconditions": ["stamina >= 1"],
        "round_offset": 0,
    }
    option[field] = value
    forged["artifact"]["composite_controller"]["conditional_options"] = [option]
    workspace = tmp_path / "workspace"
    materializer._copy_tree_no_symlinks(SOURCE, workspace)
    with pytest.raises(FoundryError) as error:
        materializer._build_runtime_controller(
            workspace,
            forged["artifact"],
            forged["manifest"],
            overlay_id=str(forged["overlay_id"]),
            overlay_tree_sha256=materializer._tree_hash(COMPOSITE),
        )
    assert error.value.code == "FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE"


def test_bundle_rename_failure_publishes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    final = tmp_path / "final"

    def fail_publish(stage: Path, target: Path) -> None:
        del stage, target
        raise OSError("injected rename failure")

    monkeypatch.setattr(materializer, "_atomic_publish_noreplace", fail_publish)
    with pytest.raises(OSError):
        materializer._atomic_publish_noreplace(stage, final)
    assert stage.is_dir()
    assert not final.exists()


def test_atomic_publish_race_preserves_preexisting_bundle_and_cleans_stage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = materializer._atomic_publish_noreplace
    raced: dict[str, Path] = {}
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "workspace").mkdir()
    final = tmp_path / "final"

    def occupy_then_publish(stage: Path, final: Path) -> None:
        raced["final"] = final
        final.mkdir()
        (final / "racer-sentinel").write_text("preexisting", encoding="utf-8")
        original(stage, final)

    monkeypatch.setattr(materializer, "_atomic_publish_noreplace", occupy_then_publish)
    with pytest.raises(FoundryError) as error:
        materializer._atomic_publish_noreplace(stage, final)
    assert error.value.code == "FINAL_CHARACTER_COLLISION"
    final = raced["final"]
    assert (final / "racer-sentinel").read_text(encoding="utf-8") == "preexisting"
    assert stage.is_dir()


def test_bound_output_root_publication_collision_preserves_stage_and_final(tmp_path: Path) -> None:
    output_root = tmp_path / "bound-output"
    output_root.mkdir(mode=0o700)
    bound = materializer._ensure_private_output_root(output_root)
    stage, stage_name = bound.create_temp_dir(".stage-")
    (stage / "workspace").mkdir()
    final_name = "final-bound"
    final = bound.child_path(final_name)
    final.mkdir()
    (final / "sentinel").write_text("keep", encoding="utf-8")
    try:
        with pytest.raises(FoundryError) as error:
            materializer._atomic_publish_noreplace(stage, final, root_fd=bound.fd)
        assert error.value.code == "FINAL_CHARACTER_COLLISION"
        assert (final / "sentinel").read_text(encoding="utf-8") == "keep"
        assert stage.is_dir()
        assert bound.child_exists(stage_name)
    finally:
        materializer._best_effort_remove_bound_child(bound, stage_name)
        materializer._best_effort_remove_bound_child(bound, final_name)
        bound.close()


def test_bound_stage_child_rejects_name_swap_before_publish(tmp_path: Path) -> None:
    output_root = tmp_path / "bound-stage-output"
    output_root.mkdir(mode=0o700)
    external = tmp_path / "stage-external"
    external.mkdir(mode=0o700)
    bound = materializer._ensure_private_output_root(output_root)
    stage = bound.create_bound_temp_dir(".stage-")
    (stage.fd_path / "source-bytes.json").write_text('{"sealed":true}\n', encoding="utf-8")
    renamed = output_root / "stage-renamed"
    original_name = output_root / stage.name
    original_name.rename(renamed)
    original_name.symlink_to(external, target_is_directory=True)
    final = bound.child_path("final-stage")
    try:
        with pytest.raises(FoundryError) as error:
            materializer._atomic_publish_noreplace(
                stage.fd_path,
                final,
                root_fd=bound.fd,
                stage_binding=stage,
            )
        assert error.value.code == "FINAL_CHARACTER_OUTPUT_CHILD_CHANGED"
        assert not list(external.rglob("*"))
        assert (renamed / "source-bytes.json").is_file()
    finally:
        stage.cleanup()
        if original_name.is_symlink():
            original_name.unlink()
        if renamed.exists():
            shutil.rmtree(renamed)
        bound.close()


def test_bound_review_snapshot_child_rejects_name_swap_without_external_bytes(tmp_path: Path) -> None:
    output_root = tmp_path / "bound-snapshot-output"
    output_root.mkdir(mode=0o700)
    external = tmp_path / "snapshot-external"
    external.mkdir(mode=0o700)
    source_overlay = tmp_path / "overlay-source"
    source_overlay.mkdir()
    (source_overlay / "evidence.json").write_text('{"sealed":true}\n', encoding="utf-8")
    bound = materializer._ensure_private_output_root(output_root)
    snapshot = bound.create_bound_temp_dir(".snapshot-")
    snapshot_target = snapshot.fd_path / "composite"
    materializer._copy_overlay_snapshot(
        source_overlay,
        snapshot_target,
        code="FINAL_CHARACTER_COMPOSITE_OVERLAY_INVALID",
        label="Composite",
    )
    renamed = output_root / "snapshot-renamed"
    original_name = output_root / snapshot.name
    original_name.rename(renamed)
    original_name.symlink_to(external, target_is_directory=True)
    try:
        with pytest.raises(FoundryError) as error:
            snapshot.assert_current()
        assert error.value.code == "FINAL_CHARACTER_OUTPUT_CHILD_CHANGED"
        assert not list(external.rglob("*"))
        assert (renamed / "composite/evidence.json").is_file()
    finally:
        snapshot.cleanup()
        if original_name.is_symlink():
            original_name.unlink()
        if renamed.exists():
            shutil.rmtree(renamed)
        bound.close()


def test_nested_workspace_copy_uses_held_component_inode_after_name_swap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_root = tmp_path / "nested-workspace-output"
    output_root.mkdir(mode=0o700)
    external = tmp_path / "nested-workspace-external"
    external.mkdir(mode=0o700)
    source = tmp_path / "nested-workspace-source"
    source.mkdir()
    (source / "nested").mkdir()
    (source / "nested/data.json").write_text('{"sealed":true}\n', encoding="utf-8")
    bound = materializer._ensure_private_output_root(output_root)
    stage = bound.create_bound_temp_dir(".stage-")
    workspace = stage.create_bound_child("workspace")
    stage_path = output_root / stage.name
    workspace_name = stage_path / workspace.name
    renamed = stage_path / "workspace-renamed"
    original_copy = materializer._copy_directory_fd
    swapped = {"value": False}

    def swap_before_recursive_copy(*args: Any, **kwargs: Any) -> None:
        if not swapped["value"]:
            workspace_name.rename(renamed)
            workspace_name.symlink_to(external, target_is_directory=True)
            swapped["value"] = True
        original_copy(*args, **kwargs)

    monkeypatch.setattr(materializer, "_copy_directory_fd", swap_before_recursive_copy)
    try:
        with pytest.raises(FoundryError) as error:
            materializer._copy_tree_no_symlinks(source, workspace)
        assert error.value.code == "FINAL_CHARACTER_OUTPUT_CHILD_CHANGED"
        assert not list(external.rglob("*"))
        assert (renamed / "nested/data.json").read_text(encoding="utf-8") == '{"sealed":true}\n'
    finally:
        workspace.cleanup()
        if workspace_name.is_symlink():
            workspace_name.unlink()
        if renamed.exists():
            shutil.rmtree(renamed)
        stage.cleanup()
        bound.close()


def test_nested_snapshot_component_copy_uses_held_inode_after_name_swap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_root = tmp_path / "nested-snapshot-output"
    output_root.mkdir(mode=0o700)
    external = tmp_path / "nested-snapshot-external"
    external.mkdir(mode=0o700)
    source = tmp_path / "nested-snapshot-source"
    source.mkdir()
    (source / "evidence").mkdir()
    (source / "evidence.json").write_text('{"sealed":true}\n', encoding="utf-8")
    bound = materializer._ensure_private_output_root(output_root)
    snapshot = bound.create_bound_temp_dir(".snapshot-")
    component = snapshot.create_bound_child("composite")
    snapshot_path = output_root / snapshot.name
    component_name = snapshot_path / component.name
    renamed = snapshot_path / "composite-renamed"
    original_copy = materializer._copy_directory_fd
    swapped = {"value": False}

    def swap_before_recursive_copy(*args: Any, **kwargs: Any) -> None:
        if not swapped["value"]:
            component_name.rename(renamed)
            component_name.symlink_to(external, target_is_directory=True)
            swapped["value"] = True
        original_copy(*args, **kwargs)

    monkeypatch.setattr(materializer, "_copy_directory_fd", swap_before_recursive_copy)
    try:
        with pytest.raises(FoundryError) as error:
            materializer._copy_overlay_snapshot(
                source,
                component,
                code="FINAL_CHARACTER_COMPOSITE_OVERLAY_INVALID",
                label="Composite",
            )
        assert error.value.code == "FINAL_CHARACTER_COMPOSITE_OVERLAY_INVALID"
        assert error.value.details.get("cause") == "FINAL_CHARACTER_OUTPUT_CHILD_CHANGED"
        assert not list(external.rglob("*"))
        assert (renamed / "evidence.json").read_text(encoding="utf-8") == '{"sealed":true}\n'
    finally:
        component.cleanup()
        snapshot.cleanup()
        if component_name.is_symlink():
            component_name.unlink()
        if renamed.exists():
            shutil.rmtree(renamed)
        bound.close()


def test_bound_child_cleanup_clears_held_inode_and_never_raced_replacement(tmp_path: Path) -> None:
    output_root = tmp_path / "cleanup-race-output"
    output_root.mkdir(mode=0o700)
    external = tmp_path / "cleanup-race-external"
    external.mkdir(mode=0o700)
    (external / "keep.txt").write_text("attacker-bytes", encoding="utf-8")
    bound = materializer._ensure_private_output_root(output_root)
    child = bound.create_bound_temp_dir(".child-")
    (child.fd_path / "owned.txt").write_text("owned-bytes", encoding="utf-8")
    original_name = output_root / child.name
    renamed = output_root / "child-renamed"
    original_name.rename(renamed)
    original_name.symlink_to(external, target_is_directory=True)
    try:
        child.cleanup()
        assert original_name.is_symlink()
        assert (external / "keep.txt").read_text(encoding="utf-8") == "attacker-bytes"
        assert (renamed / "owned.txt").read_bytes() == b""
    finally:
        if original_name.is_symlink():
            original_name.unlink()
        if renamed.exists():
            shutil.rmtree(renamed)
        bound.close()


def test_materialize_outer_closes_private_published_binding_after_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The outer snapshot boundary closes, but does not clean, a good bundle."""

    source = tmp_path / "source"
    source.mkdir()
    (source / "source.txt").write_text("sealed-source\n", encoding="utf-8")
    composite = tmp_path / "composite"
    composite.mkdir()
    output_root = tmp_path / "output"
    seen: dict[str, int] = {}
    composite_files_tree = "e" * 64
    source_hash = materializer._workspace_sha256(source)
    composite_validated = {
        "overlay_id": "composite.outer.synthetic",
        "artifact_sha256": "c" * 64,
        "overlay_tree_sha256": "d" * 64,
        "artifact": {
            "project_id": "project.outer.synthetic",
            "base_candidate_sha256": "a" * 64,
            "projection_id": "projection.outer.synthetic",
            "source_workspace_sha256": source_hash,
        },
    }
    binding = materializer._reviewed_binding_from_evidence(
        project_id="project.outer.synthetic",
        candidate_sha256="a" * 64,
        projection_id="projection.outer.synthetic",
        source_workspace_sha256=source_hash,
        composite_validated=composite_validated,
        composite_overlay_files_tree_sha256=composite_files_tree,
        composite_overlay_root=composite,
        constructed_immortal_arts=_synthetic_immortal_binding(),
    )
    authority, _issuer, record, _evidence = _issue_review_record(tmp_path / "review", binding)

    def snapshot_stub(
        _source: Path,
        target: materializer._BoundChildDirectory,
        *,
        code: str,
        label: str,
    ) -> None:
        (target.fd_path / "composite.marker").write_text("snapshot\n", encoding="utf-8")

    original_tree_hash = materializer._tree_hash

    def snapshot_hash(root: Path, *, include_checksums: bool = True) -> str:
        root_path = Path(root)
        if "composite.marker" in {entry.name for entry in root_path.iterdir()}:
            return composite_files_tree
        return original_tree_hash(root_path, include_checksums=include_checksums)

    def successful_inner(
        _self: FinalCharacterMaterializer,
        _source: Path,
        _composite: Path,
        output: Path,
        **kwargs: Any,
    ) -> dict[str, Any]:
        output_binding = kwargs["output_binding"]
        stage = output_binding.create_bound_temp_dir(".test-materializer-")
        workspace = stage.create_bound_child("workspace")
        (workspace.fd_path / "answer.txt").write_text("published\n", encoding="utf-8")
        workspace.close()
        (stage.fd_path / materializer.FINAL_CHARACTER_RECEIPT_NAME).write_bytes(b"receipt\n")
        bundle_name = "synthetic-success"
        final = output_binding.child_path(bundle_name)
        materializer._atomic_publish_noreplace(
            stage.fd_path,
            final,
            root_fd=output_binding.fd,
            stage_binding=stage,
        )
        published = stage.duplicate_for_name(output_binding, bundle_name)
        seen["published_fd"] = published.fd
        stage.close()
        bundle = Path(output) / bundle_name
        return {
            "output_path": str(bundle / "workspace"),
            "bundle_path": str(bundle),
            "receipt_path": str(bundle / materializer.FINAL_CHARACTER_RECEIPT_NAME),
            "materialization_id": bundle_name,
            "receipt": {"synthetic": True},
            "idempotent": False,
            "_published_binding": published,
        }

    monkeypatch.setattr(materializer, "_copy_overlay_snapshot", snapshot_stub)
    monkeypatch.setattr(materializer, "_tree_hash", snapshot_hash)
    monkeypatch.setattr(materializer, "_verify_workspace_checksums", lambda _workspace: None)
    monkeypatch.setattr(materializer.CompositeControllerAuthoring, "validate_overlay", lambda *args, **kwargs: deepcopy(composite_validated))
    monkeypatch.setattr(materializer, "constructed_immortal_art_binding", lambda _source: _synthetic_immortal_binding())
    monkeypatch.setattr(FinalCharacterMaterializer, "_materialize_legacy", successful_inner)

    result = FinalCharacterMaterializer(authority).materialize(source, composite, output_root, review_record_id=record["record_id"])

    assert "_published_binding" not in result
    bundle = output_root / "synthetic-success"
    assert bundle.is_dir()
    assert (bundle / "workspace/answer.txt").read_text(encoding="utf-8") == "published\n"
    assert (bundle / materializer.FINAL_CHARACTER_RECEIPT_NAME).read_bytes() == b"receipt\n"
    with pytest.raises(OSError):
        os.fstat(seen["published_fd"])


def test_materialize_requires_a_persisted_review_record(tmp_path: Path) -> None:
    """The retired pinned Luna pair cannot authorize an unreviewed materialization."""

    with pytest.raises(FoundryError) as error:
        FinalCharacterMaterializer().materialize(Path("source-not-read"), Path("composite-not-read"), tmp_path / "out")
    assert error.value.code == "FINAL_CHARACTER_REVIEW_RECORD_REQUIRED"
    assert not (tmp_path / "out").exists()


def _synthetic_immortal_binding(*names: str) -> dict[str, Any]:
    arts = {
        "schema_version": "TianxiaFoundry.ConstructedImmortalArtBinding.v1",
        "arts": [
            {
                "immortal_art_id": f"tianxia.constructed.immortal_art.synthetic.{index}",
                "name": name,
                "cl_created": 15 + index,
                "action_id": f"action.synthetic.immortal.{index}",
                "art_sha256": "1" * 64,
                "action_sha256": "2" * 64,
            }
            for index, name in enumerate(names or ("Synthetic Art",))
        ],
    }
    return {**arts, "binding_sha256": materializer.sha256_json(arts)}


def _reviewed_binding_evidence() -> dict[str, Any]:
    """A public-safe synthetic evidence set for envelope-only tests."""

    project_id = "project.reviewed.synthetic"
    candidate_sha256 = "a" * 64
    projection_id = "projection.reviewed.synthetic"
    source_workspace_sha256 = "b" * 64
    composite = {
        "overlay_id": "composite.reviewed.synthetic",
        "artifact_sha256": "c" * 64,
        "overlay_tree_sha256": "d" * 64,
        "files_tree_sha256": "e" * 64,
    }
    composite_validated = {
        **{key: composite[key] for key in ("overlay_id", "artifact_sha256", "overlay_tree_sha256")},
        "artifact": {
            "project_id": project_id,
            "base_candidate_sha256": candidate_sha256,
            "projection_id": projection_id,
            "source_workspace_sha256": source_workspace_sha256,
        },
    }
    evidence = {
        "project_id": project_id,
        "candidate_sha256": candidate_sha256,
        "projection_id": projection_id,
        "source_workspace_sha256": source_workspace_sha256,
        "composite_validated": composite_validated,
        "composite_overlay_files_tree_sha256": composite["files_tree_sha256"],
        "composite_overlay_root": Path("synthetic-composite-overlay"),
        "constructed_immortal_arts": _synthetic_immortal_binding(),
    }
    return {
        "binding": materializer._reviewed_binding_from_evidence(**evidence),
        "evidence": evidence,
    }


def test_reviewed_binding_envelope_is_committed_and_exact() -> None:
    fixture = _reviewed_binding_evidence()
    binding = fixture["binding"]
    assert materializer._validate_reviewed_binding_envelope(binding) == binding
    assert binding["binding_sha256"] == materializer.sha256_json({key: binding[key] for key in binding if key != "binding_sha256"})
    assert materializer._validate_reviewed_binding_against_evidence(binding, **fixture["evidence"]) == binding


@pytest.mark.parametrize(
    "mutation",
    [
        "project_id",
        "candidate_sha256",
        "projection_id",
        "source_workspace_sha256",
        "composite_overlay",
        "constructed_immortal_arts",
    ],
)
def test_reviewed_binding_self_consistent_forgery_does_not_authorize(mutation: str) -> None:
    fixture = _reviewed_binding_evidence()
    binding = deepcopy(fixture["binding"])
    if mutation in {"project_id", "projection_id"}:
        binding[mutation] = f"forged.{mutation}"
    elif mutation in {"candidate_sha256", "source_workspace_sha256"}:
        binding[mutation] = "9" * 64
    elif mutation == "composite_overlay":
        binding[mutation]["files_tree_sha256"] = "8" * 64
    else:
        binding[mutation] = _synthetic_immortal_binding("Forged Art")
    binding["binding_sha256"] = materializer.sha256_json({key: binding[key] for key in binding if key != "binding_sha256"})
    # A recomputed commitment proves only internal consistency, never
    # authorization against the independently validated evidence.
    assert materializer._validate_reviewed_binding_envelope(binding)["binding_sha256"] == binding["binding_sha256"]
    with pytest.raises(FoundryError) as error:
        materializer._validate_reviewed_binding_against_evidence(binding, **fixture["evidence"])
    assert error.value.code == "FINAL_CHARACTER_OVERLAY_BINDING_MISMATCH"


@pytest.mark.parametrize("missing", ["projection_id", "composite_overlay", "constructed_immortal_arts", "binding_sha256"])
def test_reviewed_binding_partial_is_rejected_before_materialization(missing: str) -> None:
    binding = deepcopy(_reviewed_binding_evidence()["binding"])
    binding.pop(missing)
    with pytest.raises(FoundryError) as error:
        materializer._validate_reviewed_binding_envelope(binding)
    assert error.value.code == "FINAL_CHARACTER_REVIEWED_BINDING_INVALID"


def test_reviewed_binding_partial_is_rejected_before_output_root_creation(tmp_path: Path) -> None:
    binding = deepcopy(_reviewed_binding_evidence()["binding"])
    binding["unexpected"] = True
    output_root = tmp_path / "out"
    with pytest.raises(FoundryError) as error:
        FinalCharacterMaterializer().materialize(SOURCE, COMPOSITE, output_root, reviewed_binding=binding)
    assert error.value.code == "FINAL_CHARACTER_REVIEW_RECORD_REQUIRED"
    assert not output_root.exists()


def test_reviewed_binding_files_tree_cannot_be_substituted_for_internal_tree() -> None:
    fixture = _reviewed_binding_evidence()
    for overlay_name in ("composite_overlay",):
        binding = deepcopy(fixture["binding"])
        binding[overlay_name]["overlay_tree_sha256"] = binding[overlay_name]["files_tree_sha256"]
        binding["binding_sha256"] = materializer.sha256_json({key: binding[key] for key in binding if key != "binding_sha256"})
        with pytest.raises(FoundryError) as error:
            materializer._validate_reviewed_binding_against_evidence(binding, **fixture["evidence"])
        assert error.value.code == "FINAL_CHARACTER_OVERLAY_BINDING_MISMATCH"


def _review_authority(tmp_path: Path, key: bytes = b"final-character-review-tests") -> FinalCharacterReviewAuthority:
    return FinalCharacterReviewAuthority(tmp_path / "review-store", create_test_integrity_service(key))


def _consume_review_evidence(
    tmp_path: Path,
    binding: dict[str, Any],
    *,
    key: bytes = b"final-character-review-tests",
) -> tuple[Database, Any, dict[str, Any]]:
    integrity = create_test_integrity_service(key)
    settings = Settings.from_env(Path(__file__).resolve().parents[1], tmp_path / "approval-data")
    db = Database(settings)
    db.migrate()
    challenges = ApprovalChallengeService(
        db,
        principal_provider=DeterministicTestPrincipalProvider(),
        integrity=integrity,
    )
    approval_parameters = materializer._review_approval_parameters(binding)
    issued = challenges.issue(**{
        key: value for key, value in approval_parameters.items() if key != "evidence_context"
    })
    challenge = issued["challenge"]
    evidence = challenges.consume(
        challenge_id=challenge["challenge_id"],
        nonce=challenge["nonce"],
        **approval_parameters,
    )
    return db, integrity, evidence


def _issue_review_record(
    tmp_path: Path,
    binding: dict[str, Any],
    *,
    key: bytes = b"final-character-review-tests",
) -> tuple[FinalCharacterReviewAuthority, FinalCharacterReviewIssuer, dict[str, Any], dict[str, Any]]:
    db, integrity, evidence = _consume_review_evidence(tmp_path, binding, key=key)
    issuer = FinalCharacterReviewIssuer(tmp_path / "review-store", db, integrity, binding)
    record = issuer.issue_from_evidence(evidence["evidence_id"])
    return issuer.review_authority, issuer, record, evidence


def _persisted_review_record(tmp_path: Path) -> tuple[FinalCharacterReviewAuthority, FinalCharacterReviewIssuer, dict[str, Any], dict[str, Any]]:
    return _issue_review_record(tmp_path, deepcopy(_reviewed_binding_evidence()["binding"]))


def test_review_issuer_persists_and_loader_verifies_explicit_approval(tmp_path: Path) -> None:
    authority, _issuer, record, evidence = _persisted_review_record(tmp_path)
    assert record["record_id"].startswith(materializer.FINAL_CHARACTER_REVIEW_RECORD_PREFIX)
    assert authority.load_record(record["record_id"]) == record
    path = authority.review_root / f"{record['record_id']}.json"
    assert path.is_file() and not path.is_symlink()
    assert set(record["integrity"]) == materializer._INTEGRITY_ENVELOPE_KEYS
    assert record["approval"] == {
        "decision": "approved",
        "reviewer_id": evidence["principal"]["principal_id"],
        "evidence_id": evidence["evidence_id"],
    }


def test_review_loader_has_no_issuance_surface_and_issuer_accepts_only_evidence_id(tmp_path: Path) -> None:
    authority, issuer, _record, evidence = _persisted_review_record(tmp_path)
    assert not hasattr(authority, "persist_approved_record")
    with pytest.raises(TypeError):
        issuer.issue_from_evidence(evidence["evidence_id"], reviewer_id="caller-authored")  # type: ignore[call-arg]


def test_review_issuer_rejects_absent_and_replayed_other_binding_evidence(tmp_path: Path) -> None:
    binding = deepcopy(_reviewed_binding_evidence()["binding"])
    db, integrity, evidence = _consume_review_evidence(tmp_path, binding)
    issuer = FinalCharacterReviewIssuer(tmp_path / "review-store", db, integrity, binding)
    with pytest.raises(FoundryError) as missing:
        issuer.issue_from_evidence("approval.evidence.v2." + "0" * 64)
    assert missing.value.code == "APPROVAL_EVIDENCE_NOT_FOUND"

    alternate = deepcopy(binding)
    alternate["project_id"] = "project.other.synthetic"
    alternate["binding_sha256"] = materializer.sha256_json({
        key: alternate[key] for key in alternate if key != "binding_sha256"
    })
    other_issuer = FinalCharacterReviewIssuer(tmp_path / "other-review-store", db, integrity, alternate)
    with pytest.raises(FoundryError) as replay:
        other_issuer.issue_from_evidence(evidence["evidence_id"])
    assert replay.value.code == "APPROVAL_EVIDENCE_BINDING_MISMATCH"
    assert not (tmp_path / "other-review-store").exists()


def test_review_issuer_rejects_forged_evidence_integrity_key(tmp_path: Path) -> None:
    binding = deepcopy(_reviewed_binding_evidence()["binding"])
    db, _integrity, evidence = _consume_review_evidence(tmp_path, binding)
    issuer = FinalCharacterReviewIssuer(
        tmp_path / "forged-review-store",
        db,
        create_test_integrity_service(b"different-review-key"),
        binding,
    )
    with pytest.raises(FoundryError) as error:
        issuer.issue_from_evidence(evidence["evidence_id"])
    assert error.value.code == "INTEGRITY_KEY_ID_UNKNOWN"
    assert not (tmp_path / "forged-review-store").exists()


def test_review_issuer_rejects_evidence_with_wrong_approval_context(tmp_path: Path) -> None:
    binding = deepcopy(_reviewed_binding_evidence()["binding"])
    db, integrity, _original_evidence = _consume_review_evidence(tmp_path, binding)
    challenges = ApprovalChallengeService(
        db,
        principal_provider=DeterministicTestPrincipalProvider(),
        integrity=integrity,
    )
    parameters = materializer._review_approval_parameters(binding)
    issued = challenges.issue(**{
        key: value for key, value in parameters.items() if key != "evidence_context"
    })
    challenge = issued["challenge"]
    wrong_context = deepcopy(parameters["evidence_context"])
    wrong_context["binding_sha256"] = "f" * 64
    forged = challenges.consume(
        challenge_id=challenge["challenge_id"],
        nonce=challenge["nonce"],
        **{**parameters, "evidence_context": wrong_context},
    )
    issuer = FinalCharacterReviewIssuer(tmp_path / "wrong-context-store", db, integrity, binding)
    with pytest.raises(FoundryError) as error:
        issuer.issue_from_evidence(forged["evidence_id"])
    assert error.value.code == "APPROVAL_EVIDENCE_CANONICAL_BYTES_MISMATCH"
    assert not (tmp_path / "wrong-context-store").exists()


def test_missing_review_store_does_not_get_created_by_load(tmp_path: Path) -> None:
    authority = _review_authority(tmp_path)
    with pytest.raises(FoundryError) as error:
        authority.load_record("final-review." + "0" * 64)
    assert error.value.code == "FINAL_CHARACTER_REVIEW_RECORD_NOT_FOUND"
    assert not authority.review_root.exists()


@pytest.mark.parametrize("mutation", ["mac", "domain", "key_id", "projection_hash", "binding"])
def test_review_record_tampering_fails_integrity_closed(tmp_path: Path, mutation: str) -> None:
    authority, _issuer, record, _evidence = _persisted_review_record(tmp_path)
    path = authority.review_root / f"{record['record_id']}.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "binding":
        forged_binding = deepcopy(value["binding"])
        forged_binding["project_id"] = "project.forged.synthetic"
        forged_binding["binding_sha256"] = materializer.sha256_json({key: forged_binding[key] for key in forged_binding if key != "binding_sha256"})
        value["binding"] = forged_binding
        value["binding_sha256"] = forged_binding["binding_sha256"]
    else:
        value["integrity"][mutation] = "f" * 64 if mutation != "domain" else "tianxia.foundry.other.domain"
    value["record_sha256"] = materializer.sha256_json({key: value[key] for key in value if key != "record_sha256"})
    path.write_text(materializer.canonical_json(value) + "\n", encoding="utf-8")
    with pytest.raises(FoundryError) as error:
        authority.load_record(record["record_id"])
    assert error.value.code == "FINAL_CHARACTER_REVIEW_RECORD_INVALID"


def test_review_record_non_mapping_integrity_fails_typed(tmp_path: Path) -> None:
    authority, _issuer, record, _evidence = _persisted_review_record(tmp_path)
    path = authority.review_root / f"{record['record_id']}.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["integrity"] = [{"forged": True}]
    with pytest.raises(FoundryError) as error:
        path.write_text(materializer.canonical_json(value) + "\n", encoding="utf-8")
        authority.load_record(record["record_id"])
    assert error.value.code == "FINAL_CHARACTER_REVIEW_RECORD_INVALID"


def test_review_record_wrong_integrity_key_fails_closed(tmp_path: Path) -> None:
    _authority, _issuer, record, _evidence = _persisted_review_record(tmp_path)
    wrong = FinalCharacterReviewAuthority(tmp_path / "review-store", create_test_integrity_service(b"different-review-key"))
    with pytest.raises(FoundryError) as error:
        wrong.load_record(record["record_id"])
    assert error.value.code == "FINAL_CHARACTER_REVIEW_RECORD_INVALID"


def test_review_record_id_path_escape_and_symlink_fail_closed(tmp_path: Path) -> None:
    authority, _issuer, record, _evidence = _persisted_review_record(tmp_path)
    with pytest.raises(FoundryError) as traversal:
        authority.load_record("../final-review." + "0" * 64)
    assert traversal.value.code == "FINAL_CHARACTER_REVIEW_RECORD_INVALID"
    path = authority.review_root / f"{record['record_id']}.json"
    target = tmp_path / "redirected-record.json"
    target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(FoundryError) as symlink:
        authority.load_record(record["record_id"])
    assert symlink.value.code == "FINAL_CHARACTER_REVIEW_RECORD_INVALID"


def test_review_record_collision_does_not_replace_existing_content(tmp_path: Path) -> None:
    authority, issuer, record, _evidence = _persisted_review_record(tmp_path)
    path = authority.review_root / f"{record['record_id']}.json"
    path.write_text("not-a-review-record\n", encoding="utf-8")
    with pytest.raises(FoundryError) as error:
        issuer.issue_from_evidence(record["approval"]["evidence_id"])
    assert error.value.code == "FINAL_CHARACTER_REVIEW_RECORD_COLLISION"
    assert path.read_text(encoding="utf-8") == "not-a-review-record\n"


def test_invalid_review_record_is_rejected_before_output_root_creation(tmp_path: Path) -> None:
    authority, _issuer, record, _evidence = _persisted_review_record(tmp_path)
    path = authority.review_root / f"{record['record_id']}.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["integrity"]["domain"] = "tianxia.foundry.forged.review"
    value["record_sha256"] = materializer.sha256_json({key: value[key] for key in value if key != "record_sha256"})
    path.write_text(materializer.canonical_json(value) + "\n", encoding="utf-8")
    output_root = tmp_path / "output"
    with pytest.raises(FoundryError) as error:
        FinalCharacterMaterializer(authority).materialize(
            Path("source-not-read"),
            Path("composite-not-read"),
            output_root,
            review_record_id=record["record_id"],
        )
    assert error.value.code == "FINAL_CHARACTER_REVIEW_RECORD_INVALID"
    assert not output_root.exists()


def test_materialization_rejects_caller_binding_without_review_record(tmp_path: Path) -> None:
    binding = deepcopy(_reviewed_binding_evidence()["binding"])
    with pytest.raises(FoundryError) as error:
        FinalCharacterMaterializer().materialize(
            Path("source-not-authorized"),
            Path("composite-not-authorized"),
            tmp_path / "out",
            reviewed_binding=binding,
        )
    assert error.value.code == "FINAL_CHARACTER_REVIEW_RECORD_REQUIRED"
    assert not (tmp_path / "out").exists()


def test_materialization_requires_injected_review_authority_for_record_id(tmp_path: Path) -> None:
    record_id = "final-review." + "1" * 64
    with pytest.raises(FoundryError) as error:
        FinalCharacterMaterializer().materialize(
            Path("source-not-authorized"),
            Path("composite-not-authorized"),
            tmp_path / "out",
            review_record_id=record_id,
        )
    assert error.value.code == "FINAL_CHARACTER_REVIEW_AUTHORITY_REQUIRED"
    assert not (tmp_path / "out").exists()


def test_approved_record_reaches_materialization_semantic_gate_before_output_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    composite = tmp_path / "composite"
    source.mkdir()
    composite.mkdir()
    (source / "source.json").write_text("{}\n", encoding="utf-8")
    (composite / "artifact.json").write_text("composite\n", encoding="utf-8")
    source_hash = materializer._workspace_sha256(source)
    project_id = "project.reviewed.integration.synthetic"
    candidate_sha256 = "a" * 64
    projection_id = "projection.reviewed.integration.synthetic"
    composite_validated = {
        "overlay_id": "composite.reviewed.integration.synthetic",
        "artifact_sha256": "c" * 64,
        "overlay_tree_sha256": "d" * 64,
        "artifact": {
            "project_id": project_id,
            "base_candidate_sha256": candidate_sha256,
            "projection_id": projection_id,
            "source_workspace_sha256": source_hash,
        },
    }
    composite_files_tree = materializer._tree_hash(composite)
    binding = materializer._reviewed_binding_from_evidence(
        project_id=project_id,
        candidate_sha256=candidate_sha256,
        projection_id=projection_id,
        source_workspace_sha256=source_hash,
        composite_validated=composite_validated,
        composite_overlay_files_tree_sha256=composite_files_tree,
        composite_overlay_root=composite,
        constructed_immortal_arts=_synthetic_immortal_binding(),
    )
    authority, _issuer, record, _evidence = _issue_review_record(tmp_path, binding)
    monkeypatch.setattr(materializer, "_verify_workspace_checksums", lambda _workspace: None)
    monkeypatch.setattr(materializer.CompositeControllerAuthoring, "validate_overlay", lambda *args, **kwargs: deepcopy(composite_validated))
    monkeypatch.setattr(materializer, "constructed_immortal_art_binding", lambda _source: _synthetic_immortal_binding())

    def semantic_blocker(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        raise FoundryError("FINAL_CHARACTER_BAD_STAMINA_MAPPING", "synthetic downstream semantic blocker")

    monkeypatch.setattr(FinalCharacterMaterializer, "_materialize_legacy", semantic_blocker)
    output_root = tmp_path / "output"
    with pytest.raises(FoundryError) as error:
        FinalCharacterMaterializer(authority).materialize(
            source,
            composite,
            output_root,
            review_record_id=record["record_id"],
        )
    assert error.value.code == "FINAL_CHARACTER_BAD_STAMINA_MAPPING"
    _assert_only_safe_empty_residue(output_root)


def test_bound_output_root_rejects_rename_symlink_race_before_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A root swap at the binding seam cannot redirect any staged bytes."""

    source = tmp_path / "source"
    composite = tmp_path / "composite"
    source.mkdir()
    composite.mkdir()
    (source / "source.json").write_text('{"sealed":true}\n', encoding="utf-8")
    (composite / "artifact.json").write_text("composite\n", encoding="utf-8")
    source_hash = materializer._workspace_sha256(source)
    project_id = "project.reviewed.race.synthetic"
    candidate_sha256 = "a" * 64
    projection_id = "projection.reviewed.race.synthetic"
    composite_validated = {
        "overlay_id": "composite.reviewed.race.synthetic",
        "artifact_sha256": "c" * 64,
        "overlay_tree_sha256": "d" * 64,
        "artifact": {
            "project_id": project_id,
            "base_candidate_sha256": candidate_sha256,
            "projection_id": projection_id,
            "source_workspace_sha256": source_hash,
        },
    }
    binding = materializer._reviewed_binding_from_evidence(
        project_id=project_id,
        candidate_sha256=candidate_sha256,
        projection_id=projection_id,
        source_workspace_sha256=source_hash,
        composite_validated=composite_validated,
        composite_overlay_files_tree_sha256=materializer._tree_hash(composite),
        composite_overlay_root=composite,
        constructed_immortal_arts=_synthetic_immortal_binding(),
    )
    authority, _issuer, record, _evidence = _issue_review_record(tmp_path / "review", binding)
    monkeypatch.setattr(materializer, "_verify_workspace_checksums", lambda _workspace: None)
    monkeypatch.setattr(materializer.CompositeControllerAuthoring, "validate_overlay", lambda *args, **kwargs: deepcopy(composite_validated))
    monkeypatch.setattr(materializer, "constructed_immortal_art_binding", lambda _source: _synthetic_immortal_binding())

    output_root = tmp_path / "output"
    output_root.mkdir(mode=0o700)
    renamed_root = tmp_path / "output-renamed"
    external_root = tmp_path / "external"
    external_root.mkdir(mode=0o700)
    original_bind = materializer._ensure_private_output_root

    def bind_then_swap(path: Path) -> Any:
        bound = original_bind(path)
        path.rename(renamed_root)
        path.symlink_to(external_root, target_is_directory=True)
        return bound

    monkeypatch.setattr(materializer, "_ensure_private_output_root", bind_then_swap)
    with pytest.raises(FoundryError) as error:
        FinalCharacterMaterializer(authority).materialize(
            source,
            composite,
            output_root,
            review_record_id=record["record_id"],
        )
    assert error.value.code == "FINAL_CHARACTER_OUTPUT_ROOT_CHANGED"
    assert not list(external_root.rglob("*"))
    assert not list(renamed_root.rglob("*"))


def _public_ability_projection_workspace(
    tmp_path: Path,
) -> tuple[Path, bytes, dict[str, Any]]:
    """Build a public-safe Qi point-buy/ASI progression for ability tests."""

    workspace, _raw, ledger, _artifact = _public_realm_projection_workspace(tmp_path)
    path_id = "tianxia.path.qi_cultivation"
    proof = materializer._PACKET_PATH_PROOFS[path_id]
    base_scores = {"STR": 10, "DEX": 12, "CON": 13, "INT": 15, "WIS": 14, "CHA": 8}
    final_scores = {"STR": 10, "DEX": 14, "CON": 15, "INT": 17, "WIS": 16, "CHA": 8}
    ledger["core_stats"].update(
        {
            "ability_scores": deepcopy(final_scores),
            "ability_modifiers": {ability: (score - 10) // 2 for ability, score in final_scores.items()},
            "ability_generation": {
                "formula": None,
                "inputs": {
                    "ability_scores": deepcopy(base_scores),
                    "generation_rule": {"budget": 27, "maximum": 15, "method": "point_buy", "minimum": 8},
                },
                "outputs": {
                    "ability_modifiers": {ability: (score - 10) // 2 for ability, score in base_scores.items()},
                    "ability_scores": deepcopy(base_scores),
                    "point_buy_cost": 27,
                },
                "rule_id": materializer._ABILITY_GENERATION_RULE_ID,
                "trace": {},
            },
        }
    )
    for row in ledger["advancement"]["levels"]:
        cl = row["cl"]
        scores_after = deepcopy(base_scores)
        scores_after["DEX"] = 14
        if cl >= 5:
            scores_after["INT"] = 17
        if cl >= 9:
            scores_after["CON"] = 15
        if cl >= 13:
            scores_after["WIS"] = 16
        row["ability_scores_after"] = scores_after
    for row in ledger["features"]:
        if row.get("feature_id", "").endswith("ability_score_improvement_or_cultivation_insight"):
            cl = row["gained_at_cl"]
            row["allocation_id"] = f"event.public.realm.{cl}"

    source_path = materializer.FINAL_CHARACTER_DEFAULT_FACTORY_ROOT / materializer._ABILITY_BACKGROUND_SOURCE_PATH
    source_lines = source_path.read_text(encoding="utf-8").splitlines()
    heading = "## Abandoned Orphan"
    heading_index = next(index for index, line in enumerate(source_lines) if line.strip() == heading)
    section_end = next(
        (index for index in range(heading_index + 1, len(source_lines)) if source_lines[index].startswith("## ")),
        len(source_lines),
    )
    background_description = "\n".join(source_lines[heading_index:section_end])
    background_packet_id = "packet.public.background.ability"
    ledger["background_origin"] = {
        "background": {
            "ability_score_change": {"DEX": 2},
            "background_id": "tianxia.background.abandoned_orphan",
            "background_sphere": "Scoundrel",
            "background_talent": "HIDDEN TOOL CACHE",
            "languages": ["Classical"],
            "name": "Abandoned Orphan",
            "skill_proficiencies": ["Deception", "Sleight of Hand"],
            "source_packet_ids": [background_packet_id],
            "summary": background_description,
            "tool_proficiencies": ["thieves' tools"],
        }
    }
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    packets_path = workspace / "Command_2/Rules_Selection_Packets.json"
    packets = json.loads(packets_path.read_text(encoding="utf-8"))
    packets["packets"][0]["advancement_kind"] = "path_acquisition"
    packets["packets"].append(
        {
            "packet_id": background_packet_id,
            "record_id": "tianxia.background.abandoned_orphan",
            "display_name": "Abandoned Orphan",
            "target_cl": 1,
            "advancement_kind": "background_acquisition",
            "full_description": background_description,
            "source_evidence": [
                {
                    "source_path": materializer._ABILITY_BACKGROUND_SOURCE_PATH,
                    "source_hash": materializer._ABILITY_BACKGROUND_SOURCE_SHA256,
                    "source_anchor": "heading:abandoned_orphan",
                }
            ],
        }
    )
    asi_id = f"{path_id}.feature.ability_score_improvement_or_cultivation_insight"
    for target_cl in (4, 8, 12):
        packet_id = f"packet.public.asi-change.{target_cl}"
        packet = _public_packet(
            packet_id,
            asi_id,
            "Ability Score Improvement or Cultivation Insight",
            proof["index_path"],
            proof["index_sha256"],
            f"path-feature:{path_id}:{asi_id}",
            target_cl=target_cl,
        )
        packet.update(
            {
                "advancement_kind": "ability_score_change",
                "event_id": f"event.public.asi-change.{target_cl}",
            }
        )
        packets["packets"].append(packet)
    packets_path.write_text(json.dumps(packets, sort_keys=True) + "\n", encoding="utf-8")
    return workspace, ledger_path.read_bytes(), ledger


def _public_resource_projection_workspace(
    tmp_path: Path,
) -> tuple[Path, bytes, dict[str, Any]]:
    """Build a public-safe Qi resource progression with source rows."""

    workspace, _raw, ledger, _artifact = _public_realm_projection_workspace(tmp_path)
    packets_path = workspace / "Command_2/Rules_Selection_Packets.json"
    packets = json.loads(packets_path.read_text(encoding="utf-8"))
    packets["packets"][0]["advancement_kind"] = "path_acquisition"
    packets_path.write_text(json.dumps(packets, sort_keys=True) + "\n", encoding="utf-8")
    base_scores = {"STR": 10, "DEX": 14, "CON": 13, "INT": 15, "WIS": 12, "CHA": 8}
    final_scores = {"STR": 10, "DEX": 14, "CON": 13, "INT": 17, "WIS": 12, "CHA": 8}
    ledger["core_stats"].update(
        {
            "ability_scores": deepcopy(final_scores),
            "ability_modifiers": {
                ability: (score - 10) // 2
                for ability, score in final_scores.items()
            },
            "primary_resource_name": "Qi",
            "primary_resource_current": 2,
            "primary_resource_max": 45,
        }
    )
    formula_id = "ns1r.tianxia.path.qi_cultivation.resource.maximum"
    ledger["resources"] = [
        {
            "authority_components": [
                {
                    "formula_id": formula_id,
                    "record_hash": "a" * 64,
                    "record_id": "tianxia.path.qi_cultivation",
                    "role": "path_base",
                    "source_anchor": "path:tianxia.path.qi_cultivation",
                    "value": 45,
                }
            ],
            "current": 2,
            "formula_id": formula_id,
            "max": 45,
            "name": "Qi",
            "resource_id": "tianxia.resource.qi",
        }
    ]
    for cl, row in enumerate(ledger["advancement"]["levels"], start=1):
        scores_after = deepcopy(base_scores)
        if cl >= 5:
            scores_after["INT"] = 17
        row["ability_scores_after"] = scores_after
        row["resource"] = {
            "current_after_event": 2,
            "formula_id": formula_id,
            "maximum": max(0, cl * ((scores_after["INT"] - 10) // 2)),
            "resource_id": "tianxia.resource.qi",
        }
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    return workspace, ledger_path.read_bytes(), ledger


def _public_resource_method_projection(
    workspace: Path,
    path_projection: Mapping[str, Any],
) -> dict[str, Any]:
    """Install the smallest bound Method detail surface for resource tests."""

    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    raw_sha256 = materializer.sha256_file(raw_path)
    formula = "Qi Cultivation CL × chosen key ability modifier"
    projected_method = {
        "method_id": materializer._METHOD_ID,
        "name": materializer._METHOD_NAME,
        "resource_name": "Qi",
        "resource_formula": formula,
    }
    details = {
        "schema_version": "TianxiaFoundry.FinalCharacterMethodProjectionProvenance.v1",
        "source_ledger_sha256": raw_sha256,
        "modern_provenance_sha256": raw_sha256,
        "method_id": materializer._METHOD_ID,
        "method_name": materializer._METHOD_NAME,
        "path_id": path_projection["path_id"],
        "path_name": "Qi Cultivation",
        "resource_name": "Qi",
        "resource_formula": formula,
        "projected_method": projected_method,
    }
    details_path = workspace / materializer._METHOD_PROJECTION_DETAILS_RELATIVE
    details_path.write_text(json.dumps(details, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "schema_version": details["schema_version"],
        "source_ledger_sha256": raw_sha256,
        "modern_provenance_sha256": raw_sha256,
        "details_path": materializer._METHOD_PROJECTION_DETAILS_RELATIVE,
        "details_sha256": materializer.sha256_file(details_path),
        "method_id": materializer._METHOD_ID,
        "method_name": materializer._METHOD_NAME,
        "method_packet_id": "packet.public.method",
        "path_id": path_projection["path_id"],
        "resource_name": "Qi",
        "resource_formula": formula,
        "projected_method": projected_method,
    }


def _public_multi_path_resource_workspace(tmp_path: Path) -> tuple[Path, bytes]:
    """Extend the source-backed Qi resource fixture with a Body Path."""

    workspace, _raw, ledger = _public_resource_projection_workspace(tmp_path)
    body_id = "tianxia.path.body_refining"
    body_proof = materializer._PACKET_PATH_PROOFS[body_id]
    body_index = materializer._bridge_fixed_json(body_proof["index_path"], body_proof["index_sha256"])
    assert isinstance(body_index, Mapping)
    body_name = body_index["display_name"]
    body_packet_id = "packet.public.body.secondary.path"
    body_row = {
        "display_name": body_name,
        "effective_cl": 8,
        "key_ability": "CON",
        "path_id": body_id,
        "selected_skills": [],
        "source_packet_ids": [body_packet_id],
    }
    ledger["character"]["paths"].append(deepcopy(body_row))
    ledger["path_selections"].append(deepcopy(body_row))
    feature = next(
        row
        for row in body_index["features"]
        if isinstance(row, Mapping)
        and 4 in row.get("granted_at_cl", [])
        and 8 in row.get("granted_at_cl", [])
    )
    for gained_at_cl in (4, 8):
        feature_id = feature["canonical_id"]
        feature_name = feature["display_name"]
        packet_id = f"packet.public.body.secondary.feature.{gained_at_cl}"
        ledger["features"].append(
            {
                "category": "path_feature",
                "feature_id": feature_id,
                "name": feature_name,
                "gained_at_cl": gained_at_cl,
                "allocation_id": f"allocation.public.body.secondary.{gained_at_cl}",
                "source_packet_ids": [packet_id],
            }
        )
        packet = _public_packet(
            packet_id,
            feature_id,
            feature_name,
            body_proof["index_path"],
            body_proof["index_sha256"],
            f"path-feature:{body_id}:{feature_id}",
            target_cl=gained_at_cl,
        )
        packet["advancement_kind"] = "path_feature_acquisition"
        packets_path = workspace / "Command_2/Rules_Selection_Packets.json"
        packets = json.loads(packets_path.read_text(encoding="utf-8"))
        packets["packets"].append(packet)
        packets_path.write_text(json.dumps(packets, sort_keys=True) + "\n", encoding="utf-8")
    packets_path = workspace / "Command_2/Rules_Selection_Packets.json"
    packets = json.loads(packets_path.read_text(encoding="utf-8"))
    path_packet = _public_packet(
        body_packet_id,
        body_id,
        body_name,
        body_proof["index_path"],
        body_proof["index_sha256"],
        f"path:{body_id}",
    )
    path_packet["advancement_kind"] = "path_acquisition"
    packets["packets"].append(path_packet)
    packets_path.write_text(json.dumps(packets, sort_keys=True) + "\n", encoding="utf-8")
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    return workspace, ledger_path.read_bytes()


def _public_method_resource_projection_workspace(tmp_path: Path) -> tuple[Path, bytes]:
    """Build a source-backed Body/Spirit resource route for METHOD-083."""

    from non_sphere_authority.method_mechanics import compile_method_mechanics

    workspace, _raw, ledger = _public_multi_path_projection_workspace(
        tmp_path,
        ("body_refining", "spirit_awakening"),
    )
    final_scores = {"STR": 10, "DEX": 14, "CON": 15, "INT": 10, "WIS": 14, "CHA": 8}
    ledger["core_stats"] = {
        "ability_scores": deepcopy(final_scores),
        "ability_modifiers": {
            ability: (score - 10) // 2
            for ability, score in final_scores.items()
        },
        "primary_resource_name": "Stamina",
        "primary_resource_current": 0,
        "primary_resource_max": 25,
    }
    ledger["advancement"] = {"levels": []}
    formula_id = "ns1r.tianxia.path.body_refining.resource.maximum"
    for cl in range(1, 16):
        scores_after = deepcopy(final_scores)
        base = cl * ((scores_after["CON"] - 10) // 2)
        proficiency_bonus = 2 + (cl - 1) // 4
        ledger["advancement"]["levels"].append(
            {
                "cl": cl,
                "ability_scores_after": scores_after,
                "resource": {
                    "current_after_event": 0,
                    "formula_id": formula_id,
                    "maximum": base - proficiency_bonus,
                    "resource_id": "tianxia.resource.stamina",
                },
            }
        )
    ledger["resources"] = [
        {
            "authority_components": [
                {
                    "formula_id": formula_id,
                    "record_hash": "b" * 64,
                    "record_id": "tianxia.path.body_refining",
                    "role": "path_base",
                    "source_anchor": "path:tianxia.path.body_refining",
                    "value": 30,
                }
            ],
            "current": 0,
            "formula_id": formula_id,
            "max": 25,
            "name": "Stamina",
            "resource_id": "tianxia.resource.stamina",
        }
    ]
    fixed_registry = materializer._bridge_fixed_json(
        materializer._PACKET_METHOD_SOURCE_PATH,
        materializer._PACKET_METHOD_SOURCE_SHA256,
    )
    assert isinstance(fixed_registry, Mapping)
    fixed_method = next(row for row in fixed_registry["methods"] if row["method_id"] == "METHOD-083")
    method_id = fixed_method["method_id"]
    method_name = fixed_method["name"]
    method_record_hash = "c" * 64
    acquisition_packet_id = "packet.public.method083.acquisition"
    activation_packet_id = "packet.public.method083.activation"
    method = {
        "activation_event_id": "event.public.method083.activation",
        "display_name": method_name,
        "event_id": "event.public.method083.acquisition",
        "mechanical_projection": True,
        "mechanics": compile_method_mechanics(dict(fixed_method), materializer._PACKET_METHOD_SOURCE_SHA256),
        "record_hash": method_record_hash,
        "record_id": method_id,
        "source_packet_ids": [acquisition_packet_id, activation_packet_id],
        "state": "active",
        "status": "active",
    }
    ledger["method"] = deepcopy(method)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    raw_before = ledger_path.read_bytes()
    (workspace / "Build/Cultivation_Method_Profile.json").write_text(
        json.dumps(
            {"schema_version": "TianxiaFoundry.CharacterGMMethod.v1", "method": deepcopy(method)},
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    packets_path = workspace / "Command_2/Rules_Selection_Packets.json"
    registry = json.loads(packets_path.read_text(encoding="utf-8"))
    registry["schema_version"] = "TianxiaFoundry.RulesSelectionPackets.v2"
    description = fixed_method["source_text"]["description"]
    source_id = f"source.{materializer._PACKET_METHOD_SOURCE_SHA256[:24]}"
    for packet_id, advancement_kind, event_id in (
        (acquisition_packet_id, "method_acquisition", method["event_id"]),
        (activation_packet_id, "method_activation", method["activation_event_id"]),
    ):
        registry["packets"].append(
            {
                "packet_id": packet_id,
                "record_id": method_id,
                "display_name": method_name,
                "target_cl": 1,
                "advancement_kind": advancement_kind,
                "event_id": event_id,
                "record_hash": method_record_hash,
                "content_binding": {
                    "pack_id": "tianxia.non_sphere.authority",
                    "pack_version": "0.6.0-mechanics.1",
                    "record_hash": method_record_hash,
                },
                "full_description": description,
                "short_description": description,
                "source_evidence": [{
                    "source_id": source_id,
                    "source_path": materializer._PACKET_METHOD_SOURCE_PATH,
                    "source_hash": materializer._PACKET_METHOD_SOURCE_SHA256,
                    "source_anchor": f"method:{method_id}",
                }],
            }
        )
    packets_path.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")
    return workspace, raw_before


@_REQUIRES_VENDOR_FIXTURE
def test_modern_resource_projection_applies_source_bound_method_modifier_across_paths(
    tmp_path: Path,
) -> None:
    workspace, raw_before = _public_method_resource_projection_workspace(tmp_path)
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    method_projection = materializer._project_method_for_compiler(
        workspace,
        path_projection=path_projection,
    )

    projection = materializer._project_modern_resource_for_compiler(
        workspace,
        path_projection=path_projection,
        method_projection=method_projection,
    )

    levels = projection["compiler_levels"]
    assert projection["resource_id"] == "tianxia.resource.stamina"
    assert projection["path_ids"] == [
        "tianxia.path.body_refining",
        "tianxia.path.spirit_awakening",
    ]
    assert levels[0]["base_after_level"] == 2
    assert levels[0]["method_delta"] == -2
    assert levels[-1]["base_after_level"] == 30
    assert levels[-1]["method_delta"] == -5
    assert levels[-1]["max_after_level"] == 25
    assert (workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE).read_bytes() == raw_before


@_REQUIRES_VENDOR_FIXTURE
def test_modern_resource_projection_rejects_method_omitting_secondary_path(
    tmp_path: Path,
) -> None:
    """A legacy Method surface cannot silently omit a selected secondary Path."""

    workspace, raw_before = _public_multi_path_resource_workspace(tmp_path)
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    method_projection = _public_resource_method_projection(workspace, path_projection)

    with pytest.raises(FoundryError) as error:
        materializer._project_modern_resource_for_compiler(
            workspace,
            path_projection=path_projection,
            method_projection=method_projection,
        )

    assert error.value.code == "FINAL_CHARACTER_RESOURCE_PROJECTION_INVALID"
    assert (workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE).read_bytes() == raw_before
    assert not (workspace / materializer._RESOURCE_PROJECTION_DETAILS_RELATIVE).exists()


@_REQUIRES_VENDOR_FIXTURE
def test_modern_resource_projection_derives_qi_timeline_and_preserves_source_rows(
    tmp_path: Path,
) -> None:
    workspace, raw, _ledger = _public_resource_projection_workspace(tmp_path)
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    method_projection = _public_resource_method_projection(workspace, path_projection)
    projection = materializer._project_modern_resource_for_compiler(
        workspace,
        path_projection=path_projection,
        method_projection=method_projection,
    )
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    projected = json.loads(ledger_path.read_text(encoding="utf-8"))
    resource_rows = [row["resource"] for row in projected["advancement"]["levels"]]
    assert [row["base_after_level"] for row in resource_rows] == [2, 4, 6, 8, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45]
    assert all(row["max_after_level"] == row["base_after_level"] for row in resource_rows)
    assert all(row["method_delta"] == row["foundation_delta"] == row["item_delta"] == 0 for row in resource_rows)
    assert all(row["resource_id"] == "tianxia.resource.qi" and row["formula_id"].endswith("resource.maximum") for row in resource_rows)
    assert projected["core_stats"]["primary_resource_max"] == 45
    assert projection["resource_id"] == "tianxia.resource.qi"
    assert projection["primary_resource_max"] == 45
    expected_recovery = (
        "Short Rest: Qi equal to Qi Cultivation CL (once per long rest); "
        "Long Rest: half maximum Qi, rounded down (none beyond completing the rest); "
        "Full Cultivation Session: all missing Qi (2 uninterrupted hours; once per long rest)"
    )
    expected_top_level = {
        "authority_components": [
            {
                "formula_id": "ns1r.tianxia.path.qi_cultivation.resource.maximum",
                "record_hash": "a" * 64,
                "record_id": "tianxia.path.qi_cultivation",
                "role": "path_base",
                "source_anchor": "path:tianxia.path.qi_cultivation",
                "value": 45,
            }
        ],
        "current": 2,
        "formula_id": "ns1r.tianxia.path.qi_cultivation.resource.maximum",
        "max": 45,
        "name": "Qi",
        "resource_id": "tianxia.resource.qi",
        "formula": "Qi Cultivation CL × chosen key ability modifier",
        "recovery": expected_recovery,
        "source_grant_ids": ["METHOD-001"],
    }
    assert projected["resources"] == [expected_top_level]
    assert projection["formula"] == expected_top_level["formula"]
    assert projection["recovery"] == expected_recovery
    assert projection["source_grant_ids"] == ["METHOD-001"]
    assert projection["method_details_sha256"] == method_projection["details_sha256"]
    assert (workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE).read_bytes() == raw
    details = json.loads(
        (workspace / materializer._RESOURCE_PROJECTION_DETAILS_RELATIVE).read_text(encoding="utf-8")
    )
    assert details["source_resource_rows"][0]["resource"]["maximum"] == 2
    assert details["source_resource_rows"][-1]["resource"]["maximum"] == 45


@_REQUIRES_VENDOR_FIXTURE
def test_modern_resource_projection_preserves_exact_existing_compiler_rows(
    tmp_path: Path,
) -> None:
    workspace, _raw, _ledger = _public_resource_projection_workspace(tmp_path)
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    method_projection = _public_resource_method_projection(workspace, path_projection)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    for cl, row in enumerate(ledger["advancement"]["levels"], start=1):
        expected = max(0, cl * (2 if cl < 5 else 3))
        row["resource"].update(
            {
                "name": "Qi",
                "base_after_level": expected,
                "method_delta": 0,
                "foundation_delta": 0,
                "item_delta": 0,
                "max_after_level": expected,
            }
        )
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    projection = materializer._project_modern_resource_for_compiler(
        workspace,
        path_projection=path_projection,
        method_projection=method_projection,
    )
    projected = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert all(row["resource"]["name"] == "Qi" for row in projected["advancement"]["levels"])
    assert projection["details_path"] == materializer._RESOURCE_PROJECTION_DETAILS_RELATIVE


@pytest.mark.parametrize(
    "mutator",
    [
        lambda ledger: ledger["advancement"]["levels"][0]["resource"].update(
            formula_id="forged.resource.formula"
        ),
        lambda ledger: ledger["advancement"]["levels"][0]["resource"].update(
            resource_id="tianxia.resource.stamina"
        ),
        lambda ledger: ledger["advancement"]["levels"][0]["resource"].update(
            current_after_event=3
        ),
        lambda ledger: ledger["advancement"]["levels"][-1]["resource"].update(
            maximum=44
        ),
        lambda ledger: ledger["advancement"]["levels"][0]["ability_scores_after"].update(
            INT=16
        ),
        lambda ledger: ledger["advancement"]["levels"][0]["resource"].update(
            name="Qi"
        ),
        lambda ledger: ledger["advancement"]["levels"][0]["resource"].update(
            name="Qi",
            base_after_level=2,
            method_delta=1,
            foundation_delta=0,
            item_delta=0,
            max_after_level=3,
        ),
        lambda ledger: ledger["resources"][0].update(formula="Qi Cultivation CL × chosen key ability modifier"),
        lambda ledger: ledger["resources"][0].update(
            formula="forged formula",
            recovery="forged recovery",
            source_grant_ids=["METHOD-001"],
        ),
    ],
)
@_REQUIRES_VENDOR_FIXTURE
def test_modern_resource_projection_rejects_forged_rows_and_timeline(
    tmp_path: Path,
    mutator: Any,
) -> None:
    workspace, _raw, ledger = _public_resource_projection_workspace(tmp_path)
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    method_projection = _public_resource_method_projection(workspace, path_projection)
    mutator(ledger)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    before = ledger_path.read_bytes()
    with pytest.raises(FoundryError) as error:
        materializer._project_modern_resource_for_compiler(
            workspace,
            path_projection=path_projection,
            method_projection=method_projection,
        )
    assert error.value.code == "FINAL_CHARACTER_RESOURCE_PROJECTION_INVALID"
    assert ledger_path.read_bytes() == before
    assert not (workspace / materializer._RESOURCE_PROJECTION_DETAILS_RELATIVE).exists()


@_REQUIRES_VENDOR_FIXTURE
def test_modern_realm_projection_accepts_canonical_projected_resource_secondary(
    tmp_path: Path,
) -> None:
    """Canonical corroboration may carry the separately authenticated resource projection."""

    workspace, _raw, _ledger = _public_resource_projection_workspace(tmp_path)
    artifact = _public_translation()
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    method_projection = _public_resource_method_projection(workspace, path_projection)
    resource_projection = materializer._project_modern_resource_for_compiler(
        workspace,
        path_projection=path_projection,
        method_projection=method_projection,
    )
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    projected = json.loads(ledger_path.read_text(encoding="utf-8"))
    canonical_path = workspace / "Command_2/Canonical_Advancement_Ledger.json"
    canonical_path.write_text(
        json.dumps({"levels": deepcopy(projected["advancement"]["levels"])}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert "base_after_level" in projected["advancement"]["levels"][0]["resource"]
    _apply_public_translation(workspace, artifact)
    realm_projection = materializer._project_modern_realm_for_compiler(
        workspace,
        path_projection=path_projection,
        immortal_translation=artifact,
        resource_projection=resource_projection,
    )
    assert realm_projection["current_realm"] == "Nascent Soul"
    canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    assert canonical["levels"][0]["resource"]["base_after_level"] == 2


@_REQUIRES_VENDOR_FIXTURE
def test_modern_ability_projection_derives_point_buy_and_event_allocations(
    tmp_path: Path,
) -> None:
    workspace, raw_bytes, _ledger = _public_ability_projection_workspace(tmp_path)
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    projection = materializer._project_modern_ability_generation_for_compiler(
        workspace,
        path_projection=path_projection,
    )
    projected = json.loads((workspace / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8"))
    generation = projected["core_stats"]["ability_generation"]
    assert generation == {
        "method": "27_point_buy",
        "base_scores": {"STR": 10, "DEX": 12, "CON": 13, "INT": 15, "WIS": 14, "CHA": 8},
        "points_spent": 27,
        "background_adjustments": {"STR": 0, "DEX": 2, "CON": 0, "INT": 0, "WIS": 0, "CHA": 0},
        "species_adjustments": {ability: 0 for ability in materializer._CORE_SAVE_ABILITIES},
        "other_adjustments": {"STR": 0, "DEX": 0, "CON": 2, "INT": 2, "WIS": 2, "CHA": 0},
    }
    assert projected["core_stats"]["ability_generation_provenance"]["inputs"]["generation_rule"]["budget"] == 27
    assert projected["advancement"]["levels"][4]["allocations"][0]["channel"] == "event"
    assert projected["advancement"]["levels"][4]["allocations"][0]["ability_score_adjustments"] == {"INT": 2}
    assert projected["advancement"]["levels"][8]["allocations"][0]["ability_score_adjustments"] == {"CON": 2}
    assert projected["advancement"]["levels"][12]["allocations"][0]["ability_score_adjustments"] == {"WIS": 2}
    for level, ability in ((4, "Intelligence"), (8, "Constitution"), (12, "Wisdom")):
        allocation = projected["advancement"]["levels"][level]["allocations"][0]
        assert allocation["grant_type"] == "event"
        assert allocation["grant_id"] == allocation["allocation_id"]
        assert allocation["name"] == f"Ability Score Improvement or Cultivation Insight: {ability} +2"
        assert allocation["slot_cost"] == 0
        assert allocation["grant_id"].endswith(allocation["source_packet_ids"][0])
    assert projection["asi_targets"] == [4, 8, 12]
    assert (workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE).read_bytes() == raw_bytes


@_REQUIRES_VENDOR_FIXTURE
def test_modern_ability_projection_preserves_exact_existing_compiler_shape(
    tmp_path: Path,
) -> None:
    workspace, _raw_bytes, _ledger = _public_ability_projection_workspace(tmp_path)
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    raw_provenance = json.loads(
        (workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE).read_text(encoding="utf-8")
    )
    raw_generation = raw_provenance["core_stats"]["ability_generation"]
    compiler_generation = {
        "method": "27_point_buy",
        "base_scores": {"STR": 10, "DEX": 12, "CON": 13, "INT": 15, "WIS": 14, "CHA": 8},
        "points_spent": 27,
        "background_adjustments": {"STR": 0, "DEX": 2, "CON": 0, "INT": 0, "WIS": 0, "CHA": 0},
        "species_adjustments": {ability: 0 for ability in materializer._CORE_SAVE_ABILITIES},
        "other_adjustments": {"STR": 0, "DEX": 0, "CON": 2, "INT": 2, "WIS": 2, "CHA": 0},
    }
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["core_stats"]["ability_generation"] = compiler_generation
    ledger["core_stats"]["ability_generation_provenance"] = raw_generation
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    projection = materializer._project_modern_ability_generation_for_compiler(
        workspace,
        path_projection=path_projection,
    )
    assert projection["generation_mode"] == "preserved_existing"
    assert json.loads(ledger_path.read_text(encoding="utf-8"))["core_stats"]["ability_generation"] == compiler_generation


def _forge_public_ability_change_packet(_ledger: dict[str, Any], workspace: Path) -> None:
    packet_path = workspace / "Command_2/Rules_Selection_Packets.json"
    packets = json.loads(packet_path.read_text(encoding="utf-8"))
    packets["packets"][-1]["source_evidence"][0]["source_anchor"] = (
        "path-feature:tianxia.path.qi_cultivation:forged"
    )
    packet_path.write_text(json.dumps(packets, sort_keys=True) + "\n", encoding="utf-8")


@pytest.mark.parametrize(
    "mutator",
    [
        lambda ledger, _workspace: ledger["core_stats"]["ability_generation"]["inputs"]["ability_scores"].update(STR=11),
        lambda ledger, _workspace: ledger["background_origin"]["background"].update(ability_score_change={"DEX": 1}),
        lambda ledger, _workspace: ledger["advancement"]["levels"][4]["ability_scores_after"].update(INT=16),
        lambda ledger, _workspace: ledger["advancement"]["levels"][4].update(
            allocations=[{"allocation_id": "allocation.forged", "channel": "event", "ability_score_adjustments": {"INT": 2}}]
        ),
        _forge_public_ability_change_packet,
    ],
)
@_REQUIRES_VENDOR_FIXTURE
def test_modern_ability_projection_rejects_forged_or_ambiguous_source(
    tmp_path: Path,
    mutator: Any,
) -> None:
    workspace, _raw_bytes, ledger = _public_ability_projection_workspace(tmp_path)
    mutator(ledger, workspace)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    before = ledger_path.read_bytes()
    with pytest.raises(FoundryError) as error:
        materializer._project_modern_ability_generation_for_compiler(
            workspace,
            path_projection=path_projection,
        )
    assert error.value.code == "FINAL_CHARACTER_ABILITY_PROJECTION_INVALID"
    assert ledger_path.read_bytes() == before
    assert not (workspace / materializer._ABILITY_PROJECTION_DETAILS_RELATIVE).exists()


def _foundation_compiler_projection_workspace(tmp_path: Path) -> tuple[Path, bytes]:
    """Build a small sealed Foundation selection with the fixed packet shape."""

    workspace, _raw, ledger = _public_path_projection_workspace(tmp_path)
    foundation_packet_id = materializer._FOUNDATION_PACKET_ID
    foundation = {
        "display_name": "Furnace Heart Record",
        "event_id": "event.public.foundation",
        "mechanical_projection": False,
        "record_hash": "a" * 64,
        "record_id": "furnace_heart_record_v0_2B",
        "source_packet_ids": [foundation_packet_id],
        "state": "acquired",
        "status": "acquired",
    }
    ledger["foundation"] = deepcopy(foundation)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    raw_bytes = ledger_path.read_bytes()
    (workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE).write_bytes(raw_bytes)
    (workspace / "Build/Foundation_Detail_Ledger.json").write_text(
        json.dumps(
            {
                "schema_version": "TianxiaFoundry.CharacterGMFoundation.v1",
                "foundation": deepcopy(foundation),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    registry_path = workspace / "Command_2/Rules_Selection_Packets.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["schema_version"] = "TianxiaFoundry.RulesSelectionPackets.v2"
    fixed = materializer._bridge_fixed_factory_json(
        materializer._PACKET_FOUNDATION_SOURCE_PATH,
        materializer._PACKET_FOUNDATION_SOURCE_SHA256,
    )
    assert isinstance(fixed, Mapping)
    fixed_row = next(row for row in fixed["foundations"] if row["foundation_id"] == foundation["record_id"])
    description = materializer.canonical_json(fixed_row["overview"])
    registry["packets"].append(
        {
            "packet_id": foundation_packet_id,
            "record_id": foundation["record_id"],
            "display_name": foundation["display_name"],
            "target_cl": 1,
            "advancement_kind": "foundation_acquisition",
            "event_id": foundation["event_id"],
            "record_hash": foundation["record_hash"],
            "content_binding": {"record_hash": foundation["record_hash"]},
            "full_description": description,
            "short_description": description[:500],
            "source_evidence": [
                {
                    "source_id": f"source.{materializer._PACKET_FOUNDATION_SOURCE_SHA256[:24]}",
                    "source_path": materializer._PACKET_FOUNDATION_SOURCE_PATH,
                    "source_hash": materializer._PACKET_FOUNDATION_SOURCE_SHA256,
                    "source_anchor": f"foundation:{foundation['record_id']}",
                }
            ],
        }
    )
    registry_path.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")
    return workspace, raw_bytes


def test_foundation_compiler_projection_synthetic_success(tmp_path: Path) -> None:
    workspace, raw_before = _foundation_compiler_projection_workspace(tmp_path)

    projection = materializer._project_foundation_for_compiler(workspace)

    ledger = json.loads((workspace / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8"))
    mirror = json.loads((workspace / "Build/Foundation_Detail_Ledger.json").read_text(encoding="utf-8"))
    foundation = ledger["foundation"]
    assert foundation == mirror["foundation"]
    assert foundation["foundation_id"] == "furnace_heart_record_v0_2B"
    assert foundation["chosen_foundation"] == "Furnace Heart Record"
    assert foundation["grade"] == "Major"
    assert foundation["stage"] == "Awakened"
    assert len(foundation["benefits"]) >= 3
    assert foundation["foundation_resource"] == {
        "name": "Furnace Heat",
        "current": 0,
        "max": 1,
        "generation": "After qualifying body-furnace event resolves",
    }
    assert foundation["mortal_exception_source_packet_id"] == materializer._FOUNDATION_PACKET_ID
    assert {row["stage"] for row in foundation["stage_benefit_map"]} == {
        "Awakened",
        "Refined",
        "Perfected",
        "Integrated",
    }
    assert set(foundation["lifecycle_coverage"]) == {
        "passive_chassis",
        "resources",
        "actions_reactions",
        "states",
        "burdens",
        "hidden_injuries",
        "strains",
        "deviations",
        "integration",
        "repair",
        "treatment",
        "temptations",
        "failure_consequences",
    }
    assert (workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE).read_bytes() == raw_before
    assert projection["foundation_authority_sha256"] == materializer._PACKET_FOUNDATION_SOURCE_SHA256
    assert projection["details_sha256"] == materializer.sha256_file(workspace / projection["details_path"])


def test_foundation_compiler_projection_rejects_shape_valid_alternate_packet_id_without_mutation(
    tmp_path: Path,
) -> None:
    workspace, _raw_before = _foundation_compiler_projection_workspace(tmp_path)
    alternate_packet_id = "packet.public.foundation.alternate"
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    mirror_path = workspace / "Build/Foundation_Detail_Ledger.json"
    registry_path = workspace / "Command_2/Rules_Selection_Packets.json"

    for path in (ledger_path, raw_path, mirror_path):
        value = json.loads(path.read_text(encoding="utf-8"))
        value["foundation"]["source_packet_ids"] = [alternate_packet_id]
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    packet = next(packet for packet in registry["packets"] if packet["packet_id"] == materializer._FOUNDATION_PACKET_ID)
    packet["packet_id"] = alternate_packet_id
    registry_path.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")

    paths = (ledger_path, raw_path, mirror_path, registry_path)
    before = {path: path.read_bytes() for path in paths}
    with pytest.raises(FoundryError) as error:
        materializer._project_foundation_for_compiler(workspace)

    assert error.value.code == "FINAL_CHARACTER_FOUNDATION_PROJECTION_INVALID"
    assert {path: path.read_bytes() for path in paths} == before
    assert not (workspace / materializer._FOUNDATION_PROJECTION_DETAILS_RELATIVE).exists()


@_REQUIRES_ORIGIN_INSIGHT_FIXTURE
def test_foundation_compiler_projection_exact_real_source_without_mutating_source(tmp_path: Path) -> None:
    source_before = materializer._workspace_sha256(ORIGIN_INSIGHT_SOURCE)
    workspace = tmp_path / "real-foundation-source"
    materializer._copy_tree_no_symlinks(ORIGIN_INSIGHT_SOURCE, workspace)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    raw_before = ledger_path.read_bytes()
    raw_path.write_bytes(raw_before)

    projection = materializer._project_foundation_for_compiler(workspace)

    foundation = json.loads(ledger_path.read_text(encoding="utf-8"))["foundation"]
    mirrored = json.loads((workspace / "Build/Foundation_Detail_Ledger.json").read_text(encoding="utf-8"))["foundation"]
    assert foundation == mirrored
    assert foundation["foundation_id"] == "furnace_heart_record_v0_2B"
    assert foundation["name"] == "Furnace Heart Record"
    assert foundation["source_packet_ids"] == ["packet.stage2.008.79561d39f58da1d2"]
    assert raw_path.read_bytes() == raw_before
    assert materializer._workspace_sha256(ORIGIN_INSIGHT_SOURCE) == source_before
    assert projection["foundation_authority_path"] == materializer._PACKET_FOUNDATION_SOURCE_PATH


@pytest.mark.parametrize("mutation", ("missing", "null", "conflict", "partial", "mirror", "source"))
def test_foundation_compiler_projection_rejects_missing_null_conflicting_or_partial_without_mutation(
    tmp_path: Path,
    mutation: str,
) -> None:
    workspace, _raw_before = _foundation_compiler_projection_workspace(tmp_path / mutation)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    mirror_path = workspace / "Build/Foundation_Detail_Ledger.json"
    registry_path = workspace / "Command_2/Rules_Selection_Packets.json"
    if mutation in {"missing", "conflict", "partial"}:
        value = json.loads(ledger_path.read_text(encoding="utf-8"))
        if mutation == "missing":
            value["foundation"].pop("record_id")
        elif mutation == "conflict":
            value["foundation"]["display_name"] = "Forged Foundation"
        else:
            value["foundation"]["foundation_id"] = "furnace_heart_record_v0_2B"
        ledger_path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    elif mutation == "null":
        mirror_path.write_bytes(b"null\n")
    elif mutation == "mirror":
        value = json.loads(mirror_path.read_text(encoding="utf-8"))
        value["foundation"]["record_id"] = "forged-foundation"
        mirror_path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    else:
        value = json.loads(raw_path.read_text(encoding="utf-8"))
        value["foundation"]["record_id"] = "forged-foundation"
        raw_path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    paths = (ledger_path, raw_path, mirror_path, registry_path)
    before = {path: path.read_bytes() for path in paths}

    with pytest.raises(FoundryError) as error:
        materializer._project_foundation_for_compiler(workspace)

    assert error.value.code == "FINAL_CHARACTER_FOUNDATION_PROJECTION_INVALID"
    assert {path: path.read_bytes() for path in paths} == before
    assert not (workspace / materializer._FOUNDATION_PROJECTION_DETAILS_RELATIVE).exists()


def _method_compiler_projection_workspace(tmp_path: Path) -> tuple[Path, bytes]:
    """Build a small Qi workspace with one sealed modern Method selection."""

    workspace, _raw, ledger = _public_path_projection_workspace(tmp_path)
    method_packet_id = "packet.public.method"
    method_record_hash = "a" * 64
    method = {
        "display_name": materializer._METHOD_NAME,
        "event_id": "event.public.method",
        "mechanical_projection": False,
        "record_hash": method_record_hash,
        "record_id": materializer._METHOD_ID,
        "source_packet_ids": [method_packet_id],
        "state": "acquired",
        "status": "acquired",
    }
    ledger["method"] = deepcopy(method)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    raw_bytes = ledger_path.read_bytes()
    (workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE).write_bytes(raw_bytes)
    (workspace / "Build/Cultivation_Method_Profile.json").write_text(
        json.dumps({"schema_version": "TianxiaFoundry.CharacterGMMethod.v1", "method": deepcopy(method)}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    packet_registry_path = workspace / "Command_2/Rules_Selection_Packets.json"
    registry = json.loads(packet_registry_path.read_text(encoding="utf-8"))
    registry["schema_version"] = "TianxiaFoundry.RulesSelectionPackets.v2"
    fixed_method = materializer._bridge_fixed_json(
        materializer._PACKET_METHOD_SOURCE_PATH,
        materializer._PACKET_METHOD_SOURCE_SHA256,
    )
    assert isinstance(fixed_method, Mapping)
    fixed_row = next(row for row in fixed_method["methods"] if row["method_id"] == materializer._METHOD_ID)
    description = fixed_row["source_text"]["description"]
    registry["packets"].append({
        "packet_id": method_packet_id,
        "record_id": materializer._METHOD_ID,
        "display_name": materializer._METHOD_NAME,
        "target_cl": 1,
        "advancement_kind": "method_acquisition",
        "event_id": method["event_id"],
        "record_hash": method_record_hash,
        "content_binding": {"record_hash": method_record_hash},
        "full_description": description,
        "short_description": description,
        "source_evidence": [{
            "source_path": materializer._PACKET_METHOD_SOURCE_PATH,
            "source_hash": materializer._PACKET_METHOD_SOURCE_SHA256,
            "source_anchor": f"method:{materializer._METHOD_ID}",
        }],
    })
    packet_registry_path.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")
    return workspace, raw_bytes


def test_method_compiler_projection_synthetic_success(tmp_path: Path) -> None:
    workspace, raw_bytes = _method_compiler_projection_workspace(tmp_path)

    projection = materializer._project_method_for_compiler(workspace)

    ledger = json.loads((workspace / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8"))
    profile = json.loads((workspace / "Build/Cultivation_Method_Profile.json").read_text(encoding="utf-8"))
    method = ledger["method"]
    assert method == profile["method"]
    assert method["method_id"] == materializer._METHOD_ID
    assert method["allocation_id"] == "allocation.method.packet.public.method"
    assert method["resource_name"] == "Qi"
    assert method["resource_formula"] == "Qi Cultivation CL × chosen key ability modifier"
    assert method["gained_at_cl"] == 1
    assert method["benefits"]
    assert method["applied_math"]
    assert method["foundation_compatibility"] == ["Open — no specific Foundation theme"]
    assert method["incompatibilities"]
    assert (workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE).read_bytes() == raw_bytes
    assert projection["method_authority_anchor"] == "method:METHOD-001"
    assert projection["method_source_master_sha256"] == materializer._METHOD_SOURCE_MASTER_SHA256
    assert materializer.sha256_file(workspace / projection["details_path"]) == projection["details_sha256"]


@_REQUIRES_ORIGIN_INSIGHT_FIXTURE
def test_method_compiler_projection_exact_real_source_without_mutating_source(tmp_path: Path) -> None:
    source_before = materializer._workspace_sha256(ORIGIN_INSIGHT_SOURCE)
    workspace = tmp_path / "real-method-source"
    materializer._copy_tree_no_symlinks(ORIGIN_INSIGHT_SOURCE, workspace)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    raw_bytes = ledger_path.read_bytes()
    raw_path.write_bytes(raw_bytes)

    projection = materializer._project_method_for_compiler(workspace)

    method = json.loads(ledger_path.read_text(encoding="utf-8"))["method"]
    profile_method = json.loads((workspace / "Build/Cultivation_Method_Profile.json").read_text(encoding="utf-8"))["method"]
    assert method == profile_method
    assert method["method_id"] == materializer._METHOD_ID
    assert method["name"] == materializer._METHOD_NAME
    assert method["source_packet_ids"] == ["packet.stage2.007.16c26483a053a8e0"]
    assert projection["method_packet_id"] == method["source_packet_ids"][0]
    assert raw_path.read_bytes() == raw_bytes
    assert materializer._workspace_sha256(ORIGIN_INSIGHT_SOURCE) == source_before


@pytest.mark.parametrize("mutation", ("missing", "null", "conflict", "mirror", "source"))
def test_method_compiler_projection_rejects_missing_null_conflicting_or_partial_without_mutation(
    tmp_path: Path,
    mutation: str,
) -> None:
    workspace, _raw_bytes = _method_compiler_projection_workspace(tmp_path / mutation)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    profile_path = workspace / "Build/Cultivation_Method_Profile.json"
    registry_path = workspace / "Command_2/Rules_Selection_Packets.json"
    if mutation in {"missing", "conflict"}:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        ledger["method"]["method_id"] = None if mutation == "missing" else "METHOD-FORGED"
        ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    elif mutation == "null":
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile["method"]["name"] = None
        profile_path.write_text(json.dumps(profile, sort_keys=True) + "\n", encoding="utf-8")
    elif mutation == "mirror":
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile["method"]["source_packet_ids"] = ["packet.forged"]
        profile_path.write_text(json.dumps(profile, sort_keys=True) + "\n", encoding="utf-8")
    else:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        raw["method"]["record_id"] = "METHOD-FORGED"
        raw_path.write_text(json.dumps(raw, sort_keys=True) + "\n", encoding="utf-8")
    before = {path: path.read_bytes() for path in (ledger_path, raw_path, profile_path, registry_path)}

    with pytest.raises(FoundryError) as error:
        materializer._project_method_for_compiler(workspace)

    assert error.value.code == "FINAL_CHARACTER_METHOD_PROJECTION_INVALID"
    assert {path: path.read_bytes() for path in before} == before
    assert not (workspace / materializer._METHOD_PROJECTION_DETAILS_RELATIVE).exists()


def test_method_compiler_projection_rejects_genuine_partial_existing_surface_without_mutation(
    tmp_path: Path,
) -> None:
    workspace, _raw_bytes = _method_compiler_projection_workspace(tmp_path)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    profile_path = workspace / "Build/Cultivation_Method_Profile.json"
    registry_path = workspace / "Command_2/Rules_Selection_Packets.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    # These are compiler fields from the otherwise-empty source row, but not
    # the complete projected set.  A subset must not be mistaken for a valid
    # already-materialized Method surface.
    ledger["method"].update({
        "method_id": materializer._METHOD_ID,
        "name": materializer._METHOD_NAME,
    })
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    before = {path: path.read_bytes() for path in (ledger_path, raw_path, profile_path, registry_path)}

    with pytest.raises(FoundryError) as error:
        materializer._project_method_for_compiler(workspace)

    assert error.value.code == "FINAL_CHARACTER_METHOD_PROJECTION_INVALID"
    assert {path: path.read_bytes() for path in before} == before
    assert not (workspace / materializer._METHOD_PROJECTION_DETAILS_RELATIVE).exists()


def test_method_compiler_projection_accepts_source_bound_non_default_method(tmp_path: Path) -> None:
    """A selected Method is resolved from its recorded source identity."""

    workspace, _raw_before = _method_compiler_projection_workspace(tmp_path)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    profile_path = workspace / "Build/Cultivation_Method_Profile.json"
    registry_path = workspace / "Command_2/Rules_Selection_Packets.json"
    fixed = materializer._bridge_fixed_json(
        materializer._PACKET_METHOD_SOURCE_PATH,
        materializer._PACKET_METHOD_SOURCE_SHA256,
    )
    method_row = next(row for row in fixed["methods"] if row["method_id"] == "METHOD-005")
    method = {
        "display_name": method_row["name"],
        "event_id": "event.public.method.non-default",
        "mechanical_projection": False,
        "record_hash": "b" * 64,
        "record_id": method_row["method_id"],
        "source_packet_ids": ["packet.public.method"],
        "state": "acquired",
        "status": "acquired",
    }
    for path in (ledger_path, raw_path):
        value = json.loads(path.read_text(encoding="utf-8"))
        value["method"] = deepcopy(method)
        value["character"].update(
            path="Spirit Awakening", path_id="tianxia.path.spirit_awakening", key_ability="WIS"
        )
        value["character"]["paths"][0].update(
            display_name="Spirit Awakening", path_id="tianxia.path.spirit_awakening", key_ability="WIS"
        )
        value["path_selections"][0].update(
            display_name="Spirit Awakening", path_id="tianxia.path.spirit_awakening", key_ability="WIS"
        )
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    profile_path.write_text(
        json.dumps(
            {"schema_version": "TianxiaFoundry.CharacterGMMethod.v1", "method": deepcopy(method)},
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    path_packet = next(row for row in registry["packets"] if row["packet_id"] == "packet.public.path")
    path_proof = materializer._PACKET_PATH_PROOFS["tianxia.path.spirit_awakening"]
    path_packet.update(
        record_id="tianxia.path.spirit_awakening",
        display_name="Spirit Awakening",
        source_evidence=[
            {
                "source_path": path_proof["index_path"],
                "source_hash": path_proof["index_sha256"],
                "source_anchor": "path:tianxia.path.spirit_awakening",
            }
        ],
    )
    packet = next(row for row in registry["packets"] if row["packet_id"] == "packet.public.method")
    packet.update(
        record_id=method["record_id"],
        display_name=method["display_name"],
        event_id=method["event_id"],
        record_hash=method["record_hash"],
        content_binding={"record_hash": method["record_hash"]},
        full_description=method_row["source_text"]["description"],
        short_description=method_row["source_text"]["description"],
        source_evidence=[
            {
                "source_path": materializer._PACKET_METHOD_SOURCE_PATH,
                "source_hash": materializer._PACKET_METHOD_SOURCE_SHA256,
                "source_anchor": "method:" + method["record_id"],
            }
        ],
    )
    registry_path.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")

    projection = materializer._project_method_for_compiler(workspace)

    projected = json.loads(ledger_path.read_text(encoding="utf-8"))["method"]
    assert projected["method_id"] == "METHOD-005"
    assert projected["name"] == method_row["name"]
    assert projected["resource_name"] == "Resonance"
    assert projected["resource_modifiers"] == []
    assert projection["method_authority_anchor"] == "method:METHOD-005"


def test_method_compiler_projection_accepts_modern_activation_binding(tmp_path: Path) -> None:
    """The installed Method consumes both its acquisition and activation packets."""

    from non_sphere_authority.method_mechanics import compile_method_mechanics

    workspace, _raw_before = _method_compiler_projection_workspace(tmp_path)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    profile_path = workspace / "Build/Cultivation_Method_Profile.json"
    registry_path = workspace / "Command_2/Rules_Selection_Packets.json"
    fixed = materializer._bridge_fixed_json(
        materializer._PACKET_METHOD_SOURCE_PATH,
        materializer._PACKET_METHOD_SOURCE_SHA256,
    )
    method_row = next(row for row in fixed["methods"] if row["method_id"] == "METHOD-005")
    method_id = method_row["method_id"]
    acquisition_event_id = "event.public.method.activation-acquisition"
    activation_event_id = "event.public.method.activation"
    record_hash = "f" * 64
    source_packet_ids = ["packet.public.method", "packet.public.method.activation"]
    mechanics = compile_method_mechanics(method_row, materializer._PACKET_METHOD_SOURCE_SHA256)
    method = {
        "display_name": method_row["name"],
        "event_id": acquisition_event_id,
        "activation_event_id": activation_event_id,
        "acquisition_event_id": acquisition_event_id,
        "mechanical_projection": True,
        "mechanics": mechanics,
        "record_hash": record_hash,
        "record_id": method_id,
        "source_packet_ids": source_packet_ids,
        "state": "active",
        "status": "active",
    }
    for path in (ledger_path, raw_path):
        value = json.loads(path.read_text(encoding="utf-8"))
        value["method"] = deepcopy(method)
        value["character"].update(
            path="Spirit Awakening", path_id="tianxia.path.spirit_awakening", key_ability="WIS"
        )
        value["character"]["paths"][0].update(
            display_name="Spirit Awakening", path_id="tianxia.path.spirit_awakening", key_ability="WIS"
        )
        value["path_selections"][0].update(
            display_name="Spirit Awakening", path_id="tianxia.path.spirit_awakening", key_ability="WIS"
        )
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    profile_path.write_text(
        json.dumps(
            {"schema_version": "TianxiaFoundry.CharacterGMMethod.v1", "method": deepcopy(method)},
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    path_packet = next(row for row in registry["packets"] if row["packet_id"] == "packet.public.path")
    path_proof = materializer._PACKET_PATH_PROOFS["tianxia.path.spirit_awakening"]
    path_packet.update(
        record_id="tianxia.path.spirit_awakening",
        display_name="Spirit Awakening",
        source_evidence=[
            {
                "source_id": f"source.{path_proof['index_sha256'][:24]}",
                "source_path": path_proof["index_path"],
                "source_hash": path_proof["index_sha256"],
                "source_anchor": "path:tianxia.path.spirit_awakening",
            }
        ],
    )
    method_packet = next(row for row in registry["packets"] if row["packet_id"] == source_packet_ids[0])
    method_packet.update(
        record_id=method_id,
        display_name=method_row["name"],
        event_id=acquisition_event_id,
        record_hash=record_hash,
        content_binding={
            "pack_id": "tianxia.non_sphere.authority",
            "pack_version": "0.6.0-mechanics.1",
            "record_hash": record_hash,
        },
        full_description=method_row["source_text"]["description"],
        short_description=method_row["source_text"]["description"],
        source_evidence=[
            {
                "source_id": f"source.{materializer._PACKET_METHOD_SOURCE_SHA256[:24]}",
                "source_path": materializer._PACKET_METHOD_SOURCE_PATH,
                "source_hash": materializer._PACKET_METHOD_SOURCE_SHA256,
                "source_anchor": f"method:{method_id}",
            }
        ],
    )
    registry["packets"].append(
        {
            "packet_id": source_packet_ids[1],
            "record_id": method_id,
            "display_name": method_row["name"],
            "target_cl": 1,
            "advancement_kind": "method_activation",
            "event_id": activation_event_id,
            "record_hash": record_hash,
            "content_binding": {
                "pack_id": "tianxia.non_sphere.authority",
                "pack_version": "0.6.0-mechanics.1",
                "record_hash": record_hash,
            },
            "full_description": method_row["source_text"]["description"],
            "short_description": method_row["source_text"]["description"],
            "source_evidence": [
                {
                    "source_id": f"source.{materializer._PACKET_METHOD_SOURCE_SHA256[:24]}",
                    "source_path": materializer._PACKET_METHOD_SOURCE_PATH,
                    "source_hash": materializer._PACKET_METHOD_SOURCE_SHA256,
                    "source_anchor": f"method:{method_id}",
                }
            ],
        }
    )
    registry_path.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")

    projection = materializer._project_method_for_compiler(workspace)

    projected = json.loads(ledger_path.read_text(encoding="utf-8"))["method"]
    assert projected["method_id"] == method_id
    assert projected["name"] == method_row["name"]
    assert projected["resource_name"] == "Resonance"
    assert projected["source_packet_ids"] == source_packet_ids
    assert projected["mechanics_version"] == "0.6.0-mechanics.1"
    assert projection["method_packet_ids"] == source_packet_ids


def test_foundation_compiler_projection_accepts_non_furnace_source_challenges(tmp_path: Path) -> None:
    """Foundation lifecycle rendering follows the selected source row."""

    workspace, _raw_before = _foundation_compiler_projection_workspace(tmp_path)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    mirror_path = workspace / "Build/Foundation_Detail_Ledger.json"
    registry_path = workspace / "Command_2/Rules_Selection_Packets.json"
    foundation_id = "heaven_devouring_shedding_womb_v0_2B"
    fixed = materializer._bridge_fixed_factory_json(
        materializer._PACKET_FOUNDATION_SOURCE_PATH,
        materializer._PACKET_FOUNDATION_SOURCE_SHA256,
    )
    foundation_row = next(row for row in fixed["foundations"] if row["foundation_id"] == foundation_id)
    foundation = {
        "display_name": foundation_row["name"],
        "event_id": "event.public.foundation.non-furnace",
        "mechanical_projection": False,
        "record_hash": "c" * 64,
        "record_id": foundation_id,
        "source_packet_ids": [materializer._FOUNDATION_PACKET_ID],
        "state": "acquired",
        "status": "acquired",
    }
    for path in (ledger_path, raw_path, mirror_path):
        value = json.loads(path.read_text(encoding="utf-8"))
        value["foundation"] = deepcopy(foundation)
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    packet = next(
        row for row in registry["packets"] if row["packet_id"] == materializer._FOUNDATION_PACKET_ID
    )
    overview = materializer.canonical_json(foundation_row["overview"])
    packet.update(
        record_id=foundation_id,
        display_name=foundation_row["name"],
        event_id=foundation["event_id"],
        record_hash=foundation["record_hash"],
        content_binding={"record_hash": foundation["record_hash"]},
        full_description=overview,
        short_description=overview[:500],
        source_evidence=[
            {
                "source_id": f"source.{materializer._PACKET_FOUNDATION_SOURCE_SHA256[:24]}",
                "source_path": materializer._PACKET_FOUNDATION_SOURCE_PATH,
                "source_hash": materializer._PACKET_FOUNDATION_SOURCE_SHA256,
                "source_anchor": f"foundation:{foundation_id}",
            }
        ],
    )
    registry_path.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")

    projection = materializer._project_foundation_for_compiler(workspace)

    projected = json.loads(ledger_path.read_text(encoding="utf-8"))["foundation"]
    assert projected["foundation_id"] == foundation_id
    assert projected["name"] == foundation_row["name"]
    assert projected["lifecycle_coverage"]["integration"]["entries"] == foundation_row["foundation_challenges"]
    assert projection["foundation_authority_anchor"] == f"foundation:{foundation_id}"


def _modern_foundation_compiler_projection_workspace(tmp_path: Path) -> tuple[Path, bytes, str]:
    """Build an installed Foundation row from the pinned v0.4C mechanics."""

    from non_sphere_authority.foundation_mechanics import (
        installed_foundation_state,
        resolve_initial_foundation_mechanics,
        verified_foundation_records,
    )

    workspace, _raw, ledger = _public_path_projection_workspace(tmp_path)
    foundation_id = "heaven_devouring_shedding_womb_v0_2B"
    stage = "Awakened"
    event_id = "event.public.foundation.mechanical"
    packet_id = "packet.public.foundation.mechanical"
    record_hash = "d" * 64
    source_record = verified_foundation_records()[foundation_id]
    selected_path_ids = [row["path_id"] for row in ledger["character"]["paths"]]
    mechanics = resolve_initial_foundation_mechanics(source_record, selected_path_ids, stage=stage)
    foundation = installed_foundation_state(mechanics, foundation_id, event_id)
    foundation.update(
        {
            "display_name": source_record["display_name"],
            "record_hash": record_hash,
            "source_packet_ids": [packet_id],
            "mechanical_projection": True,
            "acquisition_event_id": event_id,
            "mechanics_schema": mechanics["schema"],
            "stage": stage,
            "mechanics": mechanics,
        }
    )
    # Preserve a non-zero current pool from the installed state. Projection
    # must carry this value through; it must not refill from source defaults.
    foundation["resource"]["current"] = 1
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    value = json.loads(ledger_path.read_text(encoding="utf-8"))
    value["foundation"] = deepcopy(foundation)
    ledger_path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    (workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE).write_bytes(ledger_path.read_bytes())
    (workspace / "Build/Foundation_Detail_Ledger.json").write_text(
        json.dumps(
            {
                "schema_version": "TianxiaFoundry.CharacterGMFoundation.v1",
                "foundation": deepcopy(foundation),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    registry_path = workspace / "Command_2/Rules_Selection_Packets.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["schema_version"] = "TianxiaFoundry.RulesSelectionPackets.v2"
    source = source_record["source"]
    registry["packets"].append(
        {
            "packet_id": packet_id,
            "record_id": foundation_id,
            "display_name": source_record["display_name"],
            "target_cl": 5,
            "advancement_kind": "foundation_acquisition",
            "event_id": event_id,
            "record_hash": record_hash,
            "content_binding": {
                "pack_id": "tianxia.non_sphere.authority",
                "pack_version": "0.4C-mechanics.1",
                "record_hash": record_hash,
            },
            "full_description": source_record["summary"],
            "short_description": source_record["summary"][:500],
            "source_evidence": [
                {
                    "source_id": f"source.{source['artifact_sha256'][:24]}",
                    "source_path": source["artifact"],
                    "source_hash": source["artifact_sha256"],
                    "source_anchor": f"foundation:{foundation_id}",
                }
            ],
        }
    )
    registry_path.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")
    return workspace, (workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE).read_bytes(), packet_id


def test_foundation_compiler_projection_accepts_modern_source_binding_without_refill(tmp_path: Path) -> None:
    workspace, raw_before, _packet_id = _modern_foundation_compiler_projection_workspace(tmp_path)

    projection = materializer._project_foundation_for_compiler(workspace)

    ledger = json.loads((workspace / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8"))
    foundation = ledger["foundation"]
    assert foundation["foundation_id"] == "heaven_devouring_shedding_womb_v0_2B"
    assert foundation["name"] == "Heaven-Devouring Shedding-Womb"
    assert foundation["gained_at_cl"] == 5
    assert foundation["foundation_resource"]["current"] == 1
    assert foundation["foundation_resource"]["max"] == 1
    assert foundation["mechanics"]["initial_state"]["resource"]["initial_current"] == 0
    assert foundation["stage"] == "Awakened"
    assert projection["mechanics_version"] == "0.4C-mechanics.1"
    assert projection["foundation_authority_sha256"] == materializer._PACKET_FOUNDATION_SOURCE_SHA256
    assert (workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE).read_bytes() == raw_before


def test_foundation_compiler_projection_rejects_modern_forged_resource_cap_without_mutation(tmp_path: Path) -> None:
    """A copied current pool cannot authorize a new Foundation resource cap."""

    workspace, _raw_before, _packet_id = _modern_foundation_compiler_projection_workspace(tmp_path)
    paths = (
        workspace / "Build/Character_Master_Ledger.json",
        workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        workspace / "Build/Foundation_Detail_Ledger.json",
    )
    for path in paths:
        value = json.loads(path.read_text(encoding="utf-8"))
        value["foundation"]["resource"]["maximum"] = 7456
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    before = {path: path.read_bytes() for path in paths}

    with pytest.raises(FoundryError) as error:
        materializer._project_foundation_for_compiler(workspace)

    assert error.value.code == "FINAL_CHARACTER_FOUNDATION_PROJECTION_INVALID"
    assert {path: path.read_bytes() for path in paths} == before
    assert not (workspace / materializer._FOUNDATION_PROJECTION_DETAILS_RELATIVE).exists()


@pytest.mark.parametrize("mutation", ("missing_current", "missing_resource"))
def test_foundation_compiler_projection_rejects_modern_missing_resource_state_without_mutation(
    tmp_path: Path,
    mutation: str,
) -> None:
    """Modern Foundation projection must not recreate an omitted resource pool."""

    workspace, _raw_before, _packet_id = _modern_foundation_compiler_projection_workspace(tmp_path / mutation)
    paths = (
        workspace / "Build/Character_Master_Ledger.json",
        workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        workspace / "Build/Foundation_Detail_Ledger.json",
    )
    for path in paths:
        value = json.loads(path.read_text(encoding="utf-8"))
        resource = value["foundation"]["resource"]
        if mutation == "missing_current":
            resource.pop("current")
        else:
            value["foundation"].pop("resource")
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    before = {path: path.read_bytes() for path in paths}

    with pytest.raises(FoundryError) as error:
        materializer._project_foundation_for_compiler(workspace)

    assert error.value.code == "FINAL_CHARACTER_FOUNDATION_PROJECTION_INVALID"
    assert {path: path.read_bytes() for path in paths} == before
    assert not (workspace / materializer._FOUNDATION_PROJECTION_DETAILS_RELATIVE).exists()


@pytest.mark.parametrize("mutation", ("source_path", "source_hash", "pack_version", "description"))
def test_foundation_compiler_projection_rejects_modern_packet_tampering_without_mutation(
    tmp_path: Path,
    mutation: str,
) -> None:
    workspace, _raw_before, packet_id = _modern_foundation_compiler_projection_workspace(tmp_path / mutation)
    registry_path = workspace / "Command_2/Rules_Selection_Packets.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    packet = next(row for row in registry["packets"] if row["packet_id"] == packet_id)
    if mutation == "source_path":
        packet["source_evidence"][0]["source_path"] = "forged-foundation-source.md"
    elif mutation == "source_hash":
        packet["source_evidence"][0]["source_hash"] = "e" * 64
    elif mutation == "pack_version":
        packet["content_binding"]["pack_version"] = "P2A"
    else:
        packet["full_description"] = "forged Foundation description"
    registry_path.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")
    paths = (
        workspace / "Build/Character_Master_Ledger.json",
        workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        workspace / "Build/Foundation_Detail_Ledger.json",
        registry_path,
    )
    before = {path: path.read_bytes() for path in paths}

    with pytest.raises(FoundryError) as error:
        materializer._project_foundation_for_compiler(workspace)

    assert error.value.code == "FINAL_CHARACTER_FOUNDATION_PROJECTION_INVALID"
    assert {path: path.read_bytes() for path in paths} == before
    assert not (workspace / materializer._FOUNDATION_PROJECTION_DETAILS_RELATIVE).exists()


@_REQUIRES_VENDOR_FIXTURE
@_REQUIRES_ORIGIN_INSIGHT_FIXTURE
def test_method_compiler_projection_pinned_compiler_advances_past_method_blocker(
    tmp_path: Path,
) -> None:
    """The pinned compiler reaches the next known gap after Method projection.

    The accepted source is copied to a private temporary workspace.  The
    existing deterministic projections needed to get through compiler
    preconditions are applied, while realm/status/checkpoint values are set
    only as bounded compiler setup.  No overlay or provider path is used.
    """

    source_before = materializer._workspace_sha256(ORIGIN_INSIGHT_SOURCE)
    workspace = tmp_path / "method-pinned-compiler"
    materializer._copy_tree_no_symlinks(ORIGIN_INSIGHT_SOURCE, workspace)
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    method_projection = materializer._project_method_for_compiler(
        workspace,
        path_projection=path_projection,
    )
    ability_projection = materializer._project_modern_ability_generation_for_compiler(
        workspace,
        path_projection=path_projection,
    )
    grant_projection = materializer._project_background_origin_allocations_for_compiler(
        workspace,
        ability_projection=ability_projection,
    )
    materializer._project_background_origin_insight_for_compiler(workspace)
    materializer._project_background_equipment_for_compiler(workspace)
    resource_projection = materializer._project_modern_resource_for_compiler(
        workspace,
        path_projection=path_projection,
        ability_projection=ability_projection,
        method_projection=method_projection,
    )
    hp_projection = materializer._project_modern_hp_for_compiler(
        workspace,
        path_projection=path_projection,
    )
    materializer._project_modern_core_saves_for_compiler(workspace, path_projection=path_projection)
    materializer._project_modern_ac_for_compiler(workspace, path_projection=path_projection)
    materializer._project_modern_speed_for_compiler(workspace, path_projection=path_projection)
    materializer._project_modern_initiative_for_compiler(workspace, path_projection=path_projection)

    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["character"]["realm"] = "Nascent Soul"
    for level in ledger["advancement"]["levels"]:
        cl = level["cl"]
        level["realm"] = "Mortal" if cl <= 4 else "Foundation" if cl <= 9 else "Core Formation" if cl <= 14 else "Nascent Soul"
    ledger["status"] = "COMMAND_4_EXECUTABLE_CHARACTER_COMPLETE"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    materializer._recompute_checkpoints(
        workspace,
        materializer._load_compiler_module(materializer.FINAL_CHARACTER_DEFAULT_COMPILER),
    )
    materializer._bridge_rules_packet_registry(workspace, materializer.FINAL_CHARACTER_DEFAULT_CORPUS)

    with pytest.raises(FoundryError) as error:
        materializer._run_pinned_compiler(
            materializer.FINAL_CHARACTER_DEFAULT_COMPILER,
            materializer.FINAL_CHARACTER_DEFAULT_CORPUS,
            workspace,
        )

    assert error.value.code == "FINAL_CHARACTER_COMPILER_REJECTED"
    compiler_stdout = error.value.details["stdout"]
    assert "MISSING_REQUIRED:method.method_id" not in compiler_stdout
    assert '"blocker": "MISSING_REQUIRED:foundation.foundation_id"' in compiler_stdout
    assert method_projection["method_id"] == materializer._METHOD_ID
    assert materializer._workspace_sha256(ORIGIN_INSIGHT_SOURCE) == source_before


@_REQUIRES_VENDOR_FIXTURE
@_REQUIRES_ORIGIN_INSIGHT_FIXTURE
def test_foundation_compiler_projection_pinned_compiler_advances_past_foundation_blocker(
    tmp_path: Path,
) -> None:
    """The pinned compiler advances past the Foundation identity blocker."""

    source_before = materializer._workspace_sha256(ORIGIN_INSIGHT_SOURCE)
    workspace = tmp_path / "foundation-pinned-compiler"
    materializer._copy_tree_no_symlinks(ORIGIN_INSIGHT_SOURCE, workspace)
    path_projection = materializer._project_modern_path_fields_for_compiler(workspace)
    method_projection = materializer._project_method_for_compiler(workspace, path_projection=path_projection)
    foundation_projection = materializer._project_foundation_for_compiler(workspace)
    ability_projection = materializer._project_modern_ability_generation_for_compiler(
        workspace,
        path_projection=path_projection,
    )
    grant_projection = materializer._project_background_origin_allocations_for_compiler(
        workspace,
        ability_projection=ability_projection,
    )
    materializer._project_background_origin_insight_for_compiler(workspace)
    materializer._project_background_equipment_for_compiler(workspace)
    resource_projection = materializer._project_modern_resource_for_compiler(
        workspace,
        path_projection=path_projection,
        ability_projection=ability_projection,
        method_projection=method_projection,
    )
    hp_projection = materializer._project_modern_hp_for_compiler(
        workspace,
        path_projection=path_projection,
    )
    materializer._project_modern_core_saves_for_compiler(workspace, path_projection=path_projection)
    materializer._project_modern_ac_for_compiler(workspace, path_projection=path_projection)
    materializer._project_modern_speed_for_compiler(workspace, path_projection=path_projection)
    materializer._project_modern_initiative_for_compiler(workspace, path_projection=path_projection)

    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["character"]["realm"] = "Nascent Soul"
    for level in ledger["advancement"]["levels"]:
        cl = level["cl"]
        level["realm"] = "Mortal" if cl <= 4 else "Foundation" if cl <= 9 else "Core Formation" if cl <= 14 else "Nascent Soul"
    ledger["status"] = "COMMAND_4_EXECUTABLE_CHARACTER_COMPLETE"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    materializer._recompute_checkpoints(
        workspace,
        materializer._load_compiler_module(materializer.FINAL_CHARACTER_DEFAULT_COMPILER),
    )
    materializer._bridge_rules_packet_registry(workspace, materializer.FINAL_CHARACTER_DEFAULT_CORPUS)

    with pytest.raises(FoundryError) as error:
        materializer._run_pinned_compiler(
            materializer.FINAL_CHARACTER_DEFAULT_COMPILER,
            materializer.FINAL_CHARACTER_DEFAULT_CORPUS,
            workspace,
        )

    assert error.value.code == "FINAL_CHARACTER_COMPILER_REJECTED"
    compiler_stdout = error.value.details["stdout"]
    assert "MISSING_REQUIRED:foundation.foundation_id" not in compiler_stdout
    assert '"blocker": "MANUAL_LINEAGE_SOURCE_REQUIRED_FOR_COMPLETE_CHARACTER"' in compiler_stdout
    assert foundation_projection["foundation_id"] == "furnace_heart_record_v0_2B"
    assert materializer._workspace_sha256(ORIGIN_INSIGHT_SOURCE) == source_before


def _manual_lineage_bounded_choice_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "manual-lineage-bounded-choice"
    (workspace / "Build").mkdir(parents=True)
    (workspace / "Command_2").mkdir()
    ledger = {
        "schema_version": "TianxiaFoundry.FinalCharacterManualLineageTest.v1",
        "typed_none": {"manuals": deepcopy(materializer._MANUAL_LINEAGE_NONE_STATE)},
        "recorded_arts": deepcopy(materializer._MANUAL_LINEAGE_NONE_STATE),
    }
    ledger_bytes = (json.dumps(ledger, sort_keys=True) + "\n").encode("utf-8")
    (workspace / "Build/Character_Master_Ledger.json").write_bytes(ledger_bytes)
    (workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE).write_bytes(ledger_bytes)
    (workspace / "Build/Manual_Lineage_Record.json").write_text(
        json.dumps(
            {
                "schema_version": "TianxiaFoundry.CharacterGMTrainingSources.v1",
                "training_sources": [],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (workspace / "Build/Martial_Arts_and_Manuals.json").write_text(
        json.dumps(
            {
                "schema_version": "TianxiaFoundry.CharacterGMManuals.v1",
                "manuals": [],
                "none_state": deepcopy(materializer._MANUAL_LINEAGE_NONE_STATE),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (workspace / "Command_2/Rules_Selection_Packets.json").write_text(
        json.dumps(
            {
                "schema_version": "TianxiaFoundry.RulesSelectionPackets.v2",
                "packets": [deepcopy(materializer._MANUAL_LINEAGE_NONE_PACKET_COMMITMENT)],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return workspace


def _manual_lineage_source_present_workspace(tmp_path: Path) -> Path:
    workspace = _manual_lineage_bounded_choice_workspace(tmp_path)
    source_id = "source.training.alpha"
    record_hash = "b" * 64
    event_hash = "a" * 64
    packet_id = f"packet.stage2.046.{event_hash[:16]}"
    source_path = "Needed/Tianxia_Methods_Master_v0_1.md"
    source_text = materializer._corpus_entry_text(CORPUS, source_path)
    assert source_text is not None
    source_hash = materializer._sha256_text(source_text)
    source_excerpt = source_text.splitlines()[0].strip()
    source_row = {
        "source_id": source_id,
        "allocation_id": "training_source_access:event.training.alpha",
        "name": "Alpha Manual",
        "type": "manual",
        "gained_at_cl": 15,
        "contents": {
            "recorded_arts": [],
            "methods": [],
            "warnings": [],
            "recipes": [],
            "theory": [],
            "false_routes": [],
        },
        "restrictions": [],
        "risks": [],
        "mechanics_granted": [],
        "source_packet_ids": [packet_id],
        "record_hash": record_hash,
    }
    ledger = {
        "schema_version": "TianxiaFoundry.FinalCharacterManualLineageTest.v1",
        "typed_none": {},
        "recorded_arts": [],
        "training_sources": [source_row],
    }
    ledger_bytes = (json.dumps(ledger, sort_keys=True) + "\n").encode("utf-8")
    (workspace / "Build/Character_Master_Ledger.json").write_bytes(ledger_bytes)
    (workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE).write_bytes(ledger_bytes)
    (workspace / "Build/Manual_Lineage_Record.json").write_text(
        json.dumps(
            {
                "schema_version": "TianxiaFoundry.CharacterGMTrainingSources.v1",
                "training_sources": [{
                    "source_id": source_id,
                    "allocation_id": source_row["allocation_id"],
                    "name": source_row["name"],
                    "type": "other",
                    "classification": "GM_GUIDANCE_ONLY",
                    "source_category": "PROJECT_SELECTED_RECORD_TRAINING",
                    "authority": {
                        "classification": "GM_GUIDANCE_ONLY",
                        "profile_id": "manual-lineage-test-profile",
                        "profile_sha256": "f" * 64,
                    },
                    "factory_source_type": "other",
                    "gained_at_cl": source_row["gained_at_cl"],
                    "mechanics_granted": [],
                    "record_ids": [source_id],
                    "restrictions": [],
                    "risks": [],
                    "source": "Alpha Manual selected-record training source.",
                    "source_packet_ids": [packet_id],
                    "summary": "Display-only selected-record training mirror.",
                    "contents": {
                        "recorded_arts": [],
                        "methods": [],
                        "warnings": [],
                        "recipes": [],
                        "theory": [],
                        "false_routes": [],
                        "record_bindings": [],
                    },
                }],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (workspace / "Build/Martial_Arts_and_Manuals.json").write_text(
        json.dumps(
            {
                "schema_version": "TianxiaFoundry.CharacterGMManuals.v1",
                "manuals": [],
                "recorded_arts": [],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    packet = {
        "packet_id": packet_id,
        "event_id": "event.training.alpha",
        "event_hash": event_hash,
        "sequence": 46,
        "target_cl": 15,
        "advancement_kind": "training_source_access",
        "record_id": source_id,
        "record_hash": record_hash,
        "display_name": "Alpha Manual",
        "short_description": "Alpha Manual",
        "full_description": "Alpha Manual",
        "stage2_rule_id": "training-source.alpha.v1",
        "source_evidence": [{
            "source_id": "source.tianxia.methods.master.v1",
            "source_hash": source_hash,
            "source_anchor": "line:1",
            "source_path": source_path,
        }],
        "content_binding": {
            "pack_id": "training-source.pack",
            "pack_version": "1",
            "pack_hash": "d" * 64,
            "record_hash": record_hash,
            "catalog_build_id": "e" * 64,
        },
    }
    registry = {
        "schema_version": "TianxiaFoundry.RulesSelectionPackets.v2",
        "packets": [packet],
    }
    modern_bytes = (json.dumps(registry, sort_keys=True) + "\n").encode("utf-8")
    native_registry = {
        "schema_version": "HF05ZVK-R1H.CompilerRulesSelectionPackets.v1",
        "packets": [{
            "packet_id": packet_id,
            "name": packet["display_name"],
            "authority": "tianxia_rules",
            "source_path": source_path,
            "source_text": source_excerpt,
            "source_text_sha256": materializer._sha256_text(source_excerpt),
            "source_section": "line:1",
            "source_classification": "training_source_access",
            "modern_record_id": source_id,
            "modern_source_path": source_path,
            "modern_source_sha256": source_hash,
            "source_evidence_verified": True,
        }],
    }
    native_bytes = (json.dumps(native_registry, sort_keys=True) + "\n").encode("utf-8")
    (workspace / "Command_2/Rules_Selection_Packets.json").write_bytes(native_bytes)
    (workspace / "Command_2/Rules_Selection_Packets.Modern_Provenance.json").write_bytes(modern_bytes)
    return workspace


def _source_present_workspace_files(workspace: Path) -> tuple[Path, ...]:
    return (
        workspace / "Build/Character_Master_Ledger.json",
        workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        workspace / "Build/Manual_Lineage_Record.json",
        workspace / "Build/Martial_Arts_and_Manuals.json",
        workspace / "Command_2/Rules_Selection_Packets.json",
        workspace / "Command_2/Rules_Selection_Packets.Modern_Provenance.json",
    )


def test_manual_lineage_bounded_choice_source_present_is_deterministic_and_read_only(tmp_path: Path) -> None:
    workspace = _manual_lineage_source_present_workspace(tmp_path)
    paths = _source_present_workspace_files(workspace)
    before = {path: path.read_bytes() for path in paths}
    first = materializer._require_manual_lineage_source_or_bounded_choice(workspace)
    second = materializer._require_manual_lineage_source_or_bounded_choice(workspace)
    assert first == second
    assert first["status"] == "source_present"
    assert first["source_ids"] == ["source.training.alpha"]
    assert first["packet_ids"] == ["packet.stage2.046.aaaaaaaaaaaaaaaa"]
    assert {path: path.read_bytes() for path in paths} == before


def test_manual_lineage_bounded_choice_source_present_accepts_earlier_historical_none(tmp_path: Path) -> None:
    workspace = _manual_lineage_source_present_workspace(tmp_path)
    packet_paths = (
        workspace / "Command_2/Rules_Selection_Packets.json",
        workspace / "Command_2/Rules_Selection_Packets.Modern_Provenance.json",
    )
    for path in packet_paths:
        registry = json.loads(path.read_text(encoding="utf-8"))
        registry["packets"].append(deepcopy(materializer._MANUAL_LINEAGE_NONE_PACKET_COMMITMENT))
        path.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")
    paths = _source_present_workspace_files(workspace)
    before = {path: path.read_bytes() for path in paths}

    result = materializer._require_manual_lineage_source_or_bounded_choice(workspace)

    assert result["status"] == "source_present"
    assert result["source_ids"] == ["source.training.alpha"]
    assert result["packet_ids"] == ["packet.stage2.046.aaaaaaaaaaaaaaaa"]
    assert {path: path.read_bytes() for path in paths} == before


def test_manual_lineage_bounded_choice_rejects_forged_native_excerpt_before_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _manual_lineage_source_present_workspace(tmp_path)
    compiler_packets_path = workspace / "Command_2/Rules_Selection_Packets.json"
    registry = json.loads(compiler_packets_path.read_text(encoding="utf-8"))
    native = registry["packets"][0]
    forged_path = "Needed/Tianxia_Sample_Martial_Arts_Manuals_DM_Facing_Audited_v0_2.md"
    forged_text = materializer._corpus_entry_text(CORPUS, forged_path)
    assert forged_text is not None
    native["source_path"] = forged_path
    native["source_text"] = forged_text.splitlines()[0].strip()
    native["source_text_sha256"] = materializer._sha256_text(native["source_text"])
    native["source_evidence_verified"] = True
    compiler_packets_path.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")
    paths = _source_present_workspace_files(workspace)
    before = {path: path.read_bytes() for path in paths}

    with pytest.raises(FoundryError) as direct_error:
        materializer._require_manual_lineage_source_or_bounded_choice(workspace)
    assert direct_error.value.code == "FINAL_CHARACTER_MANUAL_LINEAGE_GATE_INVALID"
    assert {path: path.read_bytes() for path in paths} == before

    calls = {"count": 0}

    def unexpected_runner(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        calls["count"] += 1
        raise AssertionError("the pinned compiler runner must not run after source authentication fails")

    monkeypatch.setattr(materializer, "_run_pinned_compiler", unexpected_runner)
    with pytest.raises(FoundryError) as runner_error:
        materializer._run_pinned_compiler_after_manual_lineage_gate(
            Path("unused-compiler"),
            Path("unused-corpus"),
            workspace,
        )
    assert runner_error.value.code == "FINAL_CHARACTER_MANUAL_LINEAGE_GATE_INVALID"
    assert calls["count"] == 0
    assert {path: path.read_bytes() for path in paths} == before


def test_manual_lineage_bounded_choice_rejects_unbridged_modern_packet_before_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _manual_lineage_source_present_workspace(tmp_path)
    compiler_packets_path = workspace / "Command_2/Rules_Selection_Packets.json"
    modern_packets_path = workspace / "Command_2/Rules_Selection_Packets.Modern_Provenance.json"
    compiler_packets_path.write_bytes(modern_packets_path.read_bytes())
    paths = _source_present_workspace_files(workspace)
    before = {path: path.read_bytes() for path in paths}

    with pytest.raises(FoundryError) as direct_error:
        materializer._require_manual_lineage_source_or_bounded_choice(workspace)
    assert direct_error.value.code == "FINAL_CHARACTER_MANUAL_LINEAGE_GATE_INVALID"
    assert {path: path.read_bytes() for path in paths} == before

    calls = {"count": 0}

    def unexpected_runner(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        calls["count"] += 1
        raise AssertionError("the pinned compiler runner must not run for an unbridged modern packet")

    monkeypatch.setattr(materializer, "_run_pinned_compiler", unexpected_runner)
    with pytest.raises(FoundryError) as runner_error:
        materializer._run_pinned_compiler_after_manual_lineage_gate(
            Path("unused-compiler"),
            Path("unused-corpus"),
            workspace,
        )
    assert runner_error.value.code == "FINAL_CHARACTER_MANUAL_LINEAGE_GATE_INVALID"
    assert calls["count"] == 0
    assert {path: path.read_bytes() for path in paths} == before


@pytest.mark.parametrize(
    "mutation",
    (
        "raw_mismatch",
        "ledger_recorded_arts",
        "raw_recorded_arts",
        "typed_none",
        "row_extra",
        "duplicate_list",
        "fabricated_list",
        "bad_type",
        "bad_hash",
        "packet_mismatch",
        "packet_extra",
        "compiler_registry",
        "later_none",
        "manuals_none_state",
        "mirror_extra",
        "mirror_authority",
        "mirror_identity",
        "executable_mirror",
    ),
)
def test_manual_lineage_bounded_choice_source_present_rejects_tampering_without_mutation(tmp_path: Path, mutation: str) -> None:
    workspace = _manual_lineage_source_present_workspace(tmp_path / mutation)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    manual_lineage_path = workspace / "Build/Manual_Lineage_Record.json"
    manuals_path = workspace / "Build/Martial_Arts_and_Manuals.json"
    packet_paths = (
        workspace / "Command_2/Rules_Selection_Packets.json",
        workspace / "Command_2/Rules_Selection_Packets.Modern_Provenance.json",
    )

    def read(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    def write(path: Path, value: Any) -> None:
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")

    if mutation == "raw_mismatch":
        raw = read(raw_path)
        raw["training_sources"][0]["name"] = "Mismatched Alpha Manual"
        write(raw_path, raw)
    elif mutation in {"ledger_recorded_arts", "raw_recorded_arts"}:
        path = ledger_path if mutation == "ledger_recorded_arts" else raw_path
        value = read(path)
        value["recorded_arts"] = ["forged.recorded.art"]
        write(path, value)
    elif mutation == "typed_none":
        for path in (ledger_path, raw_path):
            value = read(path)
            value["typed_none"] = {"manuals": deepcopy(materializer._MANUAL_LINEAGE_NONE_STATE)}
            write(path, value)
    elif mutation == "row_extra":
        for path in (ledger_path, raw_path):
            value = read(path)
            value["training_sources"][0]["custom_design"] = True
            write(path, value)
    elif mutation in {"duplicate_list", "fabricated_list"}:
        for path in (ledger_path, raw_path):
            value = read(path)
            field = "methods"
            values = ["forged.training.record"] * 2 if mutation == "duplicate_list" else ["forged.training.record"]
            value["training_sources"][0]["contents"][field] = values
            write(path, value)
    elif mutation in {"bad_type", "bad_hash"}:
        for path in (ledger_path, raw_path):
            value = read(path)
            if mutation == "bad_type":
                value["training_sources"][0]["type"] = "teacher"
            else:
                value["training_sources"][0]["record_hash"] = "G" * 64
            write(path, value)
    elif mutation == "packet_mismatch":
        for path in (ledger_path, raw_path):
            value = read(path)
            value["training_sources"][0]["source_packet_ids"] = ["packet.stage2.046.unknown"]
            write(path, value)
    elif mutation == "packet_extra":
        for path in packet_paths:
            value = read(path)
            value["packets"][0]["unexpected"] = True
            write(path, value)
    elif mutation == "compiler_registry":
        value = read(packet_paths[0])
        value["packets"][0]["unexpected"] = True
        write(packet_paths[0], value)
    elif mutation == "later_none":
        old_packet_id = "packet.stage2.046.aaaaaaaaaaaaaaaa"
        new_packet_id = "packet.stage2.044.aaaaaaaaaaaaaaaa"
        for path in (ledger_path, raw_path):
            value = read(path)
            value["training_sources"][0]["source_packet_ids"] = [new_packet_id]
            write(path, value)
        for path in packet_paths:
            value = read(path)
            value["packets"][0]["packet_id"] = new_packet_id
            value["packets"][0]["sequence"] = 44
            value["packets"].append(deepcopy(materializer._MANUAL_LINEAGE_NONE_PACKET_COMMITMENT))
            write(path, value)
        assert old_packet_id not in {read(path)["packets"][0]["packet_id"] for path in packet_paths}
    elif mutation == "manuals_none_state":
        value = read(manuals_path)
        value["none_state"] = deepcopy(materializer._MANUAL_LINEAGE_NONE_STATE)
        write(manuals_path, value)
    elif mutation == "mirror_extra":
        value = read(manual_lineage_path)
        value["training_sources"][0]["mechanical_projection"] = 1
        write(manual_lineage_path, value)
    elif mutation == "mirror_authority":
        value = read(manual_lineage_path)
        value["training_sources"][0]["authority"] = 1
        write(manual_lineage_path, value)
    elif mutation == "mirror_identity":
        value = read(manual_lineage_path)
        value["training_sources"][0]["source_packet_ids"] = ["packet.stage2.046.forged"]
        write(manual_lineage_path, value)
    elif mutation == "executable_mirror":
        value = read(manual_lineage_path)
        value["training_sources"][0]["contents"]["recorded_arts"] = ["forged.recorded.art"]
        write(manual_lineage_path, value)

    paths = _source_present_workspace_files(workspace)
    before = {path: path.read_bytes() for path in paths}
    with pytest.raises(FoundryError) as error:
        materializer._require_manual_lineage_source_or_bounded_choice(workspace)
    assert error.value.code == "FINAL_CHARACTER_MANUAL_LINEAGE_GATE_INVALID"
    assert {path: path.read_bytes() for path in paths} == before


def test_manual_lineage_bounded_choice_synthetic_shape_order_and_determinism(tmp_path: Path) -> None:
    workspace = _manual_lineage_bounded_choice_workspace(tmp_path)
    with pytest.raises(FoundryError) as first:
        materializer._require_manual_lineage_source_or_bounded_choice(workspace)
    with pytest.raises(FoundryError) as second:
        materializer._require_manual_lineage_source_or_bounded_choice(workspace)

    details = first.value.details
    assert first.value.code == "FINAL_CHARACTER_BOUNDED_CHOICE_REQUIRED"
    assert details == second.value.details
    assert details["schema_version"] == materializer._MANUAL_LINEAGE_BOUNDED_CHOICE_SCHEMA
    assert details["slot_id"] == "manual_lineage_training_source"
    assert details["current_commitments"]["typed_none"] == materializer._MANUAL_LINEAGE_NONE_STATE
    assert details["current_commitments"]["recorded_arts"] == materializer._MANUAL_LINEAGE_NONE_STATE
    assert details["current_commitments"]["packet"]["packet_id"] == materializer._MANUAL_LINEAGE_NONE_PACKET_ID
    assert details["current_commitments"]["source"] == materializer._MANUAL_LINEAGE_NONE_SOURCE
    assert details["requirement"] == "one source-backed training source"
    routes = details["resolution_routes"]
    assert [route["route_id"] for route in routes] == [
        "selected_ai_custom_training_source",
        "owner_supplied_custom_training_source",
        "locked_canonical_training_source",
    ]
    assert len(routes) == 3
    assert all(route["selection"] == "Not auto-selected." for route in routes)
    assert all(route["review"] == "Candidate/binding review must be regenerated." for route in routes)
    assert all(route["candidate_revision"] == "A new candidate revision is required." for route in routes)
    selected_ai = routes[0]
    assert selected_ai["available"] is True
    assert selected_ai["actionable_now"] is False
    assert selected_ai["availability_status"] == "requires_explicit_ai_proposal"
    assert selected_ai["proposal_requirement"] == "A server-owned generated-proposal identifier and exact proposal-to-bytes/project/review binding are required."
    assert "Not actionable now." in selected_ai["requirements"]


def _manual_lineage_bounded_choice_post_bridge_workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    workspace = _manual_lineage_bounded_choice_workspace(tmp_path)
    compiler_packets_path = workspace / "Command_2/Rules_Selection_Packets.json"
    modern_packets_path = workspace / "Command_2/Rules_Selection_Packets.Modern_Provenance.json"
    modern_packets_path.write_bytes(compiler_packets_path.read_bytes())
    compiler_packets_path.write_text(
        json.dumps(
            {
                "schema_version": "TianxiaFoundry.CompilerRulesSelectionPackets.v1",
                "packets": [],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return workspace, compiler_packets_path, modern_packets_path


def test_manual_lineage_bounded_choice_uses_preserved_modern_packet_after_bridge(tmp_path: Path) -> None:
    workspace, _compiler_packets_path, modern_packets_path = _manual_lineage_bounded_choice_post_bridge_workspace(tmp_path)

    with pytest.raises(FoundryError) as error:
        materializer._require_manual_lineage_source_or_bounded_choice(workspace)

    assert error.value.code == "FINAL_CHARACTER_BOUNDED_CHOICE_REQUIRED"
    assert error.value.details["current_commitments"]["packet"]["packet_id"] == materializer._MANUAL_LINEAGE_NONE_PACKET_ID
    assert modern_packets_path.is_file()


@pytest.mark.parametrize("mutation", ("missing", "null", "partial", "duplicate", "tamper"))
def test_manual_lineage_bounded_choice_rejects_invalid_preserved_modern_packet_without_mutation(
    tmp_path: Path,
    mutation: str,
) -> None:
    workspace, compiler_packets_path, modern_packets_path = _manual_lineage_bounded_choice_post_bridge_workspace(tmp_path / mutation)
    if mutation == "missing":
        modern_packets_path.unlink()
    elif mutation == "null":
        modern_packets_path.write_text("null\n", encoding="utf-8")
    else:
        registry = json.loads(modern_packets_path.read_text(encoding="utf-8"))
        packet = registry["packets"][0]
        if mutation == "partial":
            registry["packets"] = [{"packet_id": materializer._MANUAL_LINEAGE_NONE_PACKET_ID}]
        elif mutation == "duplicate":
            registry["packets"].append(deepcopy(packet))
        else:
            packet["source_evidence"][0]["source_hash"] = "0" * 64
        modern_packets_path.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")
    paths = (workspace / "Build/Character_Master_Ledger.json", modern_packets_path, compiler_packets_path)
    before = {path: path.read_bytes() for path in paths if path.exists()}

    with pytest.raises(FoundryError) as error:
        materializer._require_manual_lineage_source_or_bounded_choice(workspace)

    assert error.value.code == "FINAL_CHARACTER_MANUAL_LINEAGE_GATE_INVALID"
    assert {path: path.read_bytes() for path in paths if path.exists()} == before


@_REQUIRES_ORIGIN_INSIGHT_FIXTURE
def test_manual_lineage_bounded_choice_exact_real_source_preserves_source(tmp_path: Path) -> None:
    source_before = materializer._workspace_sha256(ORIGIN_INSIGHT_SOURCE)
    workspace = tmp_path / "real-manual-lineage-source"
    materializer._copy_tree_no_symlinks(ORIGIN_INSIGHT_SOURCE, workspace)
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    raw_path.write_bytes((workspace / "Build/Character_Master_Ledger.json").read_bytes())

    with pytest.raises(FoundryError) as error:
        materializer._require_manual_lineage_source_or_bounded_choice(workspace)

    assert error.value.code == "FINAL_CHARACTER_BOUNDED_CHOICE_REQUIRED"
    assert error.value.details["current_commitments"]["packet"]["packet_id"] == "packet.stage2.045.b47f0bef64e2f842"
    assert error.value.details["current_commitments"]["packet"]["record_id"] == "tianxia.c1a.none.manuals"
    assert error.value.details["current_commitments"]["source"]["source_hash"] == "01231a53308e4f007549f4f70ce21d51ec89f2f2d9ba3ad08efa1896e266bc86"
    assert materializer._workspace_sha256(ORIGIN_INSIGHT_SOURCE) == source_before


@pytest.mark.parametrize("mutation", ("forged", "missing", "null", "partial", "alternate_packet", "alternate_source", "contradictory"))
def test_manual_lineage_bounded_choice_rejects_invalid_commitments_without_mutation(
    tmp_path: Path,
    mutation: str,
) -> None:
    workspace = _manual_lineage_bounded_choice_workspace(tmp_path / mutation)
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    raw_path = workspace / materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    packet_path = workspace / "Command_2/Rules_Selection_Packets.json"
    if mutation in {"forged", "missing", "null", "partial"}:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        if mutation == "forged":
            ledger["typed_none"]["manuals"]["reason"] = "Forged none state"
        elif mutation == "missing":
            ledger["typed_none"].pop("manuals")
        elif mutation == "null":
            ledger["typed_none"]["manuals"] = None
        else:
            ledger["typed_none"]["manuals"].pop("state")
        ledger_path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    elif mutation == "alternate_packet":
        registry = json.loads(packet_path.read_text(encoding="utf-8"))
        registry["packets"][0]["packet_id"] = "packet.stage2.045.alternate"
        packet_path.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")
    elif mutation == "alternate_source":
        registry = json.loads(packet_path.read_text(encoding="utf-8"))
        registry["packets"][0]["source_evidence"][0]["source_anchor"] = "record:forged-manuals"
        packet_path.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")
    else:
        for path in (ledger_path, raw_path):
            ledger = json.loads(path.read_text(encoding="utf-8"))
            ledger["training_sources"] = [{"source_id": "forged.training.source"}]
            path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    paths = (ledger_path, raw_path, packet_path)
    before = {path: path.read_bytes() for path in paths}

    with pytest.raises(FoundryError) as error:
        materializer._require_manual_lineage_source_or_bounded_choice(workspace)

    assert error.value.code == "FINAL_CHARACTER_MANUAL_LINEAGE_GATE_INVALID"
    assert {path: path.read_bytes() for path in paths} == before


def test_manual_lineage_bounded_choice_materialization_path_blocks_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _manual_lineage_bounded_choice_workspace(tmp_path)
    calls = {"count": 0}

    def unexpected_runner(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        calls["count"] += 1
        raise AssertionError("the pinned compiler runner must not be invoked after a bounded-choice gate")

    monkeypatch.setattr(materializer, "_run_pinned_compiler", unexpected_runner)
    with pytest.raises(FoundryError) as error:
        materializer._run_pinned_compiler_after_manual_lineage_gate(
            Path("unused-compiler"),
            Path("unused-corpus"),
            workspace,
        )

    assert error.value.code == "FINAL_CHARACTER_BOUNDED_CHOICE_REQUIRED"
    assert calls["count"] == 0
