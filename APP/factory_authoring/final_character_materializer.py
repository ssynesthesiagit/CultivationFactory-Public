"""Fail-closed materialization of the accepted Command 4 overlays.

The authoring controllers deliberately stop at detached overlays.  This
module is the small, provider-free boundary which may consume those overlays.
It always copies the sealed source workspace to a private staging directory,
applies only the operations encoded by the Immortal Art manifest, registers a
runtime-safe Composite controller by resolving its action identities against
the canonical action surface, and invokes the pinned compiler before a final
directory is published.

There is intentionally no fallback to a provider, no in-place mode, and no
best-effort mutation.  Any lineage, operation, hash, compiler, or publication
failure removes the owned staging directory and raises a typed ``FoundryError``.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import importlib.util
import io
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, NoReturn

from app.core import Database, FoundryError, canonical_json, sha256_file, sha256_json
from character_creation.compiler_selection_authority import (
    _foundation_excerpt as _compiler_foundation_excerpt,
    _method_excerpt as _compiler_method_excerpt,
)
from security.approval_challenges import ApprovalChallengeService
from security.integrity import IntegrityService
from factory_authoring.composite_controller import (
    COMPOSITE_CONTROLLER_ID,
    COMPOSITE_CONTROLLER_RESOURCE_ALIAS,
    COMPOSITE_CONTROLLER_RESOURCE_ID,
    CompositeControllerAuthoring,
    _action_packet,
    _canonical_resource_id,
    _reject_recursive_symlinks,
    _tree_hashes,
    _verify_workspace_checksums,
    _workspace_sha256 as _path_workspace_sha256,
)
from factory_authoring.starting_kits import background_kit
from factory_authoring.constructed_immortal_arts import (
    IMMORTAL_ART_CLASSIFICATION,
    constructed_immortal_art_binding,
    translate_constructed_immortal_arts,
)
from factory_authoring.path_resources import active_resource_authority as _active_resource_authority


FINAL_CHARACTER_MATERIALIZER_SCHEMA = "TianxiaFoundry.FinalCharacterMaterialization.v1"
FINAL_CHARACTER_RECEIPT_SCHEMA = "TianxiaFoundry.FinalCharacterMaterializationReceipt.v1"
FINAL_CHARACTER_RUNTIME_CONTROLLER_SCHEMA = "TianxiaFoundry.CompositeControllerRuntime.v1"
FINAL_CHARACTER_CONTROLLER_ID = COMPOSITE_CONTROLLER_ID
FINAL_CHARACTER_RECEIPT_NAME = "Final_Character_Materialization_Receipt.json"
FINAL_CHARACTER_COMPILER_OUTPUT_DIRNAME = "Compiler_Output"
FINAL_CHARACTER_STATE_ROOT_ENV = "CULTIVATION_FACTORY_STATE_ROOT"


def _default_state_root() -> Path:
    """Resolve the publication-safe state root without embedding a host path."""

    override = os.environ.get(FINAL_CHARACTER_STATE_ROOT_ENV)
    if override and override.strip():
        return Path(override).expanduser()
    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    if xdg_state_home and xdg_state_home.strip():
        return Path(xdg_state_home).expanduser() / "cultivation-factory"
    return Path.home() / ".local" / "state" / "cultivation-factory"


FINAL_CHARACTER_DEFAULT_STATE_ROOT = _default_state_root()
_FINAL_CHARACTER_PINNED_FACTORY_BUNDLE = "4daf167cf634f27efef4dd2f1c8700bb4b7037cc6234c32be1af90aea5916385"
_FINAL_CHARACTER_PINNED_FACTORY_DIR = "HF05ZVK_R1H_Phase2I_HF2"
from factory_authoring import final_compiler_release as _final_compiler_release

# The final stage runs the rulebook-aligned compiler v2 from an additive,
# pinned derivation of the HF05ZVK Factory tree.  The rules corpus still comes
# from the original, unmodified tree.
_FINAL_CHARACTER_BASE_FACTORY_ROOT = (
    FINAL_CHARACTER_DEFAULT_STATE_ROOT
    / "vendor"
    / "extracted"
    / _FINAL_CHARACTER_PINNED_FACTORY_BUNDLE
    / _FINAL_CHARACTER_PINNED_FACTORY_DIR
)
FINAL_CHARACTER_DEFAULT_COMPILER = _final_compiler_release.release_compiler(FINAL_CHARACTER_DEFAULT_STATE_ROOT)
FINAL_CHARACTER_DEFAULT_CORPUS = _FINAL_CHARACTER_BASE_FACTORY_ROOT / "09_RULES/Tianxia_Canonical_Rules_Corpus_P2A.zip"
FINAL_CHARACTER_DEFAULT_FACTORY_ROOT = FINAL_CHARACTER_DEFAULT_COMPILER.parent.parent
# Fixed data files (packet indexes, Method/Background/Origin sources) are read
# from the original tree; each read is checked against its own content pin.
FINAL_CHARACTER_COMPILER_SHA256 = _final_compiler_release.COMPILER_SHA256
FINAL_CHARACTER_CORPUS_SHA256 = "12ffcacf2dbf955c24c56eb711634c7c1ebe4f639e1c51681f5aaef1b1388c19"
from character_creation import method_corpus_release as _method_release
# The extracted factory root is immutable source/dependency material.  Python
# creates bytecode caches while loading the pinned compiler's validators; those
# generated ``__pycache__`` files are not dependency inputs and must not make
# the trust aggregate change between otherwise identical runs.
FINAL_CHARACTER_FACTORY_ROOT_SHA256 = _final_compiler_release.FACTORY_ROOT_SHA256
FINAL_CHARACTER_REVIEWED_BINDING_SCHEMA = "TianxiaFoundry.FinalCharacterReviewedBinding.v2"
FINAL_CHARACTER_REVIEW_RECORD_SCHEMA = "TianxiaFoundry.FinalCharacterReviewRecord.v1"
FINAL_CHARACTER_REVIEW_RECORD_DOMAIN = "tianxia.foundry.final_character.review.v1"
FINAL_CHARACTER_REVIEW_RECORD_PREFIX = "final-review."
FINAL_CHARACTER_REVIEW_APPROVAL_OPERATION = "final_character_reviewed_overlay_pair.approve"
FINAL_CHARACTER_REVIEW_APPROVAL_SUBJECT_TYPE = "final_character_reviewed_overlay_pair"
FINAL_CHARACTER_REVIEW_APPROVAL_CONTEXT_SCHEMA = "TianxiaFoundry.FinalCharacterReviewApprovalContext.v1"

_REVIEWED_BINDING_KEYS = frozenset({
    "schema_version",
    "project_id",
    "candidate_sha256",
    "projection_id",
    "source_workspace_sha256",
    "composite_overlay",
    "constructed_immortal_arts",
    "binding_sha256",
})
_REVIEWED_OVERLAY_BINDING_KEYS = frozenset({
    "overlay_id",
    "artifact_sha256",
    "overlay_tree_sha256",
    "files_tree_sha256",
})
_REVIEW_RECORD_KEYS = frozenset({
    "schema_version",
    "record_id",
    "binding",
    "binding_sha256",
    "approval",
    "integrity",
    "record_sha256",
})
_REVIEW_APPROVAL_KEYS = frozenset({"decision", "reviewer_id", "evidence_id"})
_INTEGRITY_ENVELOPE_KEYS = frozenset({
    "integrity_version",
    "algorithm",
    "key_id",
    "domain",
    "projection_hash",
    "mac",
})

_RUNTIME_RESOURCE_NAMES = {
    "tianxia.resource.stamina": "Stamina",
    "tianxia.resource.qi": "Qi",
    "tianxia.resource.resonance": "Resonance",
}
_RUNTIME_RESOURCE_KEYS = frozenset(_RUNTIME_RESOURCE_NAMES)

# Stage-2's modern authority files are not compiler authority by themselves.
# These fixed identities are the only records which may be used to bridge a
# modern packet into the pinned compiler corpus.  They are intentionally kept
# here, next to the bridge, rather than accepted from a packet or request.
_FINAL_CHARACTER_APP_ROOT = Path(__file__).resolve().parents[1]
_PACKET_METHOD_SOURCE_PATH = "non_sphere_authority/authority/Tianxia_Methods_Typed_Registry_v0_6.json"
_PACKET_METHOD_SOURCE_SHA256 = "42dcf28fceff3f18120940f4f427be36bdcfaab0d40415e098899a313c2df503"
_PACKET_FOUNDATION_SOURCE_PATH = "09_RULES/Foundation_Runtime/Authoritative_Foundations_v0_4B.json"
_PACKET_FOUNDATION_SOURCE_SHA256 = "6cd5986426a121ca4b171a0b3415067319063388d6f90d33b4e9b23fe600210f"
_FOUNDATION_PACKET_ID = "packet.stage2.008.79561d39f58da1d2"
_USER_DIRECTIVE_SOURCE_PATH = "USER_DIRECTIVE_CURRENT_CONVERSATION"
_USER_DIRECTIVE_SOURCE_TEXT_MAX_BYTES = 65536
_USER_DIRECTIVE_SOURCE_ANCHOR_MAX_LENGTH = 512
_MANUAL_LINEAGE_BOUNDED_CHOICE_SCHEMA = "TianxiaFoundry.FinalCharacterManualLineageBoundedChoice.v1"
_MANUAL_LINEAGE_BOUNDED_CHOICE_SLOT_ID = "manual_lineage_training_source"
_MANUAL_LINEAGE_NONE_PACKET_ID = "packet.stage2.045.b47f0bef64e2f842"
_MANUAL_LINEAGE_NONE_RECORD_ID = "tianxia.c1a.none.manuals"
_MANUAL_LINEAGE_NONE_EVENT_ID = "11305d9c-b076-51b7-9c5c-d778bb6e407d"
_MANUAL_LINEAGE_NONE_RECORD_HASH = "d1cc20028365c03eb1acdbe3e3c90ef0612cd4d9bdefe247b372f9a16a0b3e48"
_MANUAL_LINEAGE_NONE_STATE = {
    "reason": "No manuals was selected.",
    "reason_code": "not_selected_for_c1a_proof",
    "source_backed": True,
    "state": "none",
}
_MANUAL_LINEAGE_NONE_SOURCE = {
    "source_id": "source.01231a53308e4f007549f4f7",
    "source_path": "09_RULES/RULES_SOURCE_MANIFEST.json",
    "source_hash": "01231a53308e4f007549f4f70ce21d51ec89f2f2d9ba3ad08efa1896e266bc86",
    "source_anchor": "record:tianxia.source.canon.authority.manifest.p2a.json:index:0",
}
_MANUAL_LINEAGE_NONE_PACKET_COMMITMENT = {
    "packet_id": _MANUAL_LINEAGE_NONE_PACKET_ID,
    "record_id": _MANUAL_LINEAGE_NONE_RECORD_ID,
    "display_name": "C1A explicit no-manuals authority",
    "target_cl": 15,
    "advancement_kind": "typed_none",
    "event_id": _MANUAL_LINEAGE_NONE_EVENT_ID,
    "event_hash": "b47f0bef64e2f842c30263922943a2e804e5911c188bef0abecef131e05422a1",
    "record_hash": _MANUAL_LINEAGE_NONE_RECORD_HASH,
    "sequence": 45,
    "stage2_rule_id": "c1a.none.manuals.v1",
    "full_description": "Bounded C1A source-backed typed-none authority for manuals.",
    "short_description": "Bounded C1A source-backed typed-none authority for manuals.",
    "content_binding": {
        "catalog_build_id": "f65b50c2e229c558bab4173a056076d68ccd043649524079ffccb37a4bff3a23",
        "pack_hash": "16f8af8d28cade3004a6e3f674043babc7322afebbb05f5ded65dbd1f3a33c5b",
        "pack_id": "tianxia.core.factory.hf05zvk.r1h.phase2i.hf2",
        "pack_version": "2.9.3",
        "record_hash": _MANUAL_LINEAGE_NONE_RECORD_HASH,
    },
    "source_evidence": [_MANUAL_LINEAGE_NONE_SOURCE],
}
_MANUAL_LINEAGE_BOUNDED_CHOICE_ROUTES = (
    {
        "route_id": "selected_ai_custom_training_source",
        "requirements": "Not actionable now. Requires a server-owned generated-proposal identifier and exact proposal-to-bytes/project/review binding before this route can become actionable.",
        "available": True,
        "actionable_now": False,
        "availability_status": "requires_explicit_ai_proposal",
        "proposal_requirement": "A server-owned generated-proposal identifier and exact proposal-to-bytes/project/review binding are required.",
        "selection": "Not auto-selected.",
        "review": "Candidate/binding review must be regenerated.",
        "candidate_revision": "A new candidate revision is required.",
    },
    {
        "route_id": "owner_supplied_custom_training_source",
        "requirements": "Requires explicit owner-supplied source fields and a user directive; creates a new sealed acquisition revision.",
        "selection": "Not auto-selected.",
        "review": "Candidate/binding review must be regenerated.",
        "candidate_revision": "A new candidate revision is required.",
    },
    {
        "route_id": "locked_canonical_training_source",
        "requirements": "Requires an installed and project-locked canonical training-source/manual record and exact packet; currently no sealed candidate choice exists.",
        "selection": "Not auto-selected.",
        "review": "Candidate/binding review must be regenerated.",
        "candidate_revision": "A new candidate revision is required.",
    },
)
_PACKET_INSIGHT_SOURCE_PATH = "catalog_authority/cat3/source/Tianxia_Central_Cultivation_Insights_AI_Reference_R5_Legacy_Restored.json"
_PACKET_INSIGHT_SOURCE_SHA256 = "4618d6f5d777affc94be5564384ec6adf88e09ddead300b6f7423668f1f21580"
_PACKET_INSIGHT_CORPUS_PATH = "Needed/Tianxia_Sphere_Compendium_Latest_R0I_85Spheres.md"
_PACKET_INSIGHT_CORPUS_SHA256 = "67f67275889467d43605debaa0c05dc5ddde9ba079222819aabea27c66167775"
_PACKET_SUBPATH_MASTER_PATH = "non_sphere_authority/authority/Tianxia_Subpath_Tradition_Index_Master_P2B.json"
_PACKET_SUBPATH_MASTER_SHA256 = "dde2abe61b4f2078da2bd24a33cdfdf5c8d52d9e119c91f0efea8b15ca86f50b"
_PACKET_PATH_MASTER_PATH = "non_sphere_authority/authority/Tianxia_Path_Index_Master_P2A.json"
_PACKET_PATH_MASTER_SHA256 = "e34d9e411df73bb0c30d89bdc21cf48bf870f3fc4e9ef81785b9a1717e7e6d80"
_PACKET_PATH_PROOFS: dict[str, dict[str, str]] = {
    "tianxia.path.body_refining": {
        "index_path": "non_sphere_authority/authority/body_refining.path_index.p2a.json",
        "index_sha256": "b674e2e563b83f5f3bebe42e5345bb1e3b2fb01651c851a30a1d149c2dd76690",
        "corpus_path": "Canonical/Paths/Body/Tianxia_Body_Refining_Player_Path_Chapter_R8.md",
        "corpus_sha256": "774213817c938f9eb00a58e432b85feb32872a12b723b60ea1a77cefedc12186",
        "index_file": "body_refining.path_index.p2a.json",
    },
    "tianxia.path.qi_cultivation": {
        "index_path": "non_sphere_authority/authority/qi_cultivation.path_index.p2a.json",
        "index_sha256": "686855dc1fc1e1981688b207e1e0e29d1c17968391b67a974ad1e973d7b2cc58",
        "corpus_path": "Canonical/Paths/Qi/Tianxia_Qi_Cultivation_Player_Path_Chapter_R19.md",
        "corpus_sha256": "81a025df185c416a4d4774b781a2b6f2970af06903f44e4fccbe6818d23a7799",
        "index_file": "qi_cultivation.path_index.p2a.json",
    },
    "tianxia.path.spirit_awakening": {
        "index_path": "non_sphere_authority/authority/spirit_awakening.path_index.p2a.json",
        "index_sha256": "86cf9a282e4af1ebbb137eccf97a4f768b6e9182c634ea4a7f994a75f4a2b7af",
        "corpus_path": "Canonical/Paths/Spirit/Tianxia_Spirit_Awakening_Player_Path_Chapter_R7.md",
        "corpus_sha256": "2653393b9260eba31f6f685b46e48035671322f6f1f1a14e60c470de96537a81",
        "index_file": "spirit_awakening.path_index.p2a.json",
    },
}
_PACKET_PATH_RECORD_PREFIXES = tuple(_PACKET_PATH_PROOFS)
_PATH_PROJECTION_RAW_PROVENANCE_RELATIVE = "Build/Character_Master_Ledger.Modern_Provenance.json"
_PATH_PROJECTION_DETAILS_RELATIVE = "Build/Character_Master_Ledger.Path_Projection_Provenance.json"
_CORE_SAVE_PROJECTION_DETAILS_RELATIVE = "Build/Character_Master_Ledger.Core_Save_Projection_Provenance.json"
_AC_PROJECTION_DETAILS_RELATIVE = "Build/Character_Master_Ledger.AC_Projection_Provenance.json"
_REALM_PROJECTION_DETAILS_RELATIVE = "Build/Character_Master_Ledger.Realm_Projection_Provenance.json"
_SPEED_PROJECTION_DETAILS_RELATIVE = "Build/Character_Master_Ledger.Speed_Projection_Provenance.json"
_INITIATIVE_PROJECTION_DETAILS_RELATIVE = "Build/Character_Master_Ledger.Initiative_Projection_Provenance.json"
_HP_PROJECTION_DETAILS_RELATIVE = "Build/Character_Master_Ledger.HP_Projection_Provenance.json"
_ABILITY_PROJECTION_DETAILS_RELATIVE = "Build/Character_Master_Ledger.Ability_Projection_Provenance.json"
_RESOURCE_PROJECTION_DETAILS_RELATIVE = "Build/Character_Master_Ledger.Resource_Projection_Provenance.json"
_GRANT_PROJECTION_DETAILS_RELATIVE = "Build/Character_Master_Ledger.Grant_Allocation_Projection_Provenance.json"
_FOUNDATION_PROJECTION_DETAILS_RELATIVE = "Build/Character_Master_Ledger.Foundation_Projection_Provenance.json"
_CORE_SAVE_ABILITIES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")
# ASI and level-selected Cultivation Insight milestone ability events (RAW-017).
_ABILITY_MILESTONE_EVENT_TYPES = frozenset({"ability_score_change", "cultivation_insight_ability_increase"})
_ABILITY_GENERATION_RULE_ID = "c1a.tianxia.source.canon.authority.manifest.p2a.json.v1"
_ABILITY_BACKGROUND_AUTHORITY_PATH = "non_sphere_authority/authority/Background_Core_Authority_v1.json"
_ABILITY_BACKGROUND_AUTHORITY_SHA256 = "58dce7a049a379d01ac268a9e08085af8a62a1a4ba1376dbfc7a2f9c14993774"
_ABILITY_BACKGROUND_SOURCE_PATH = "09_RULES/Source_Text/Tianxia_PHB_Backgrounds_v2_BOOK_CLEAN_ORIGIN_RECONCILED_v0_6.md"
_ABILITY_BACKGROUND_SOURCE_SHA256 = "e5e8203907dbded3303f197ff86579e82ec4d08df1fdbbcd51b03af5a98edf1c"
_ORIGIN_INSIGHT_PROJECTION_DETAILS_RELATIVE = "Build/Character_Master_Ledger.Origin_Insight_Projection_Provenance.json"
_ORIGIN_INSIGHT_SOURCE_PATH = "09_RULES/Source_Text/Tianxia_PHB_Origin_Insights_v0_4_READABILITY_SELF_CONTAINED.md"
_ORIGIN_INSIGHT_SOURCE_SHA256 = "fcbbee35265279b58b7b43b74416de633d66eea144ccd90c9785a46ac38f1946"
_ORIGIN_INSIGHT_SOURCE_ANCHOR = "heading:9-born_under_suspicion"
_ORIGIN_INSIGHT_ID = "tianxia.origin_insight.born_under_suspicion"
_ORIGIN_INSIGHT_NAME = "Born Under Suspicion"
_ORIGIN_INSIGHT_SELECTED_SKILL = "Deception"
_ORIGIN_INSIGHT_RESULT = "expertise"
_ORIGIN_INSIGHT_INITIATIVE_EFFECT = "situational_advantage"
_METHOD_PROJECTION_DETAILS_RELATIVE = "Build/Character_Master_Ledger.Method_Projection_Provenance.json"
_METHOD_SOURCE_MASTER_PATH = "09_RULES/Source_Text/Tianxia_Methods_Master_v0_1.md"
_METHOD_SOURCE_MASTER_SHA256 = "6f92480cd46a906dd6f963187a2679ccb1a339ff64cd00b4c97ca62732227b91"
_METHOD_SOURCE_MASTER_ANCHOR = "heading:1-outer-gate-root-method"
_METHOD_ID = "METHOD-001"
_METHOD_NAME = "Outer Gate Root Method"
_ABILITY_POINT_BUY_COST = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}
_AC_COMPILER_COMPONENTS = (
    "base_ac",
    "dexterity_modifier_applied",
    "shield_adjustment",
    "foundation_adjustment",
    "method_adjustment",
    "item_adjustment",
    "other_adjustment",
)
_AC_COMPILER_FIELDS = _AC_COMPILER_COMPONENTS + ("total", "source_grant_ids")
_AC_FORMULA_ID = "tianxia.core.baseline.unarmored_ac.owner_r1"
_SPEED_AUTHORITY_PATH = "authority/Tianxia_Core_Character_Baseline_Authority_Pack_R1.json"
_SPEED_AUTHORITY_SHA256 = "993630c640415acdec4570c78db000c3a6fba5697282d51c8af87be5e9370d6a"
_SPEED_RULE_ID = "tianxia.core.human.walking_speed.v1"
_SPEED_SOURCE = {
    "anchor": "lines:247,272-274,329-332",
    "path": "09_RULES/Source_Text/PHB/Tianxia_PHB_Manuscript_v0_7_Subpaths_Inserted.md",
    "source_sha256": "f2bb2eeba55a4b8b8630e02fbcb35d21ac80d2efb7ad4a9e91642522f82d7fe7",
}
_SPEED_PROVENANCE_MAPPING = {
    "authority_classification": "AUTHENTICATED_CANONICAL_SOURCE",
    "baseline_pack_id": "tianxia.core.character_baseline.owner_r1",
    "baseline_pack_sha256": _SPEED_AUTHORITY_SHA256,
    "baseline_pack_version": "1.0.0",
    "destination_pointers": ["/ledger/core_stats/speed_ft", "/ledger/core_stats/speed_generation"],
    "provenance_unit": "core_character_baseline_rule",
    "rule_id": _SPEED_RULE_ID,
    "source": _SPEED_SOURCE,
    "transformation_kind": "DIRECT_TYPED_VALUE",
}
_SPEED_COMPILER_COMPONENTS = (
    "base_speed",
    "path_adjustment",
    "sphere_adjustment",
    "foundation_adjustment",
    "method_adjustment",
    "equipment_adjustment",
    "other_adjustment",
)
_SPEED_COMPILER_FIELDS = _SPEED_COMPILER_COMPONENTS + ("total", "source_grant_ids")
_INITIATIVE_AUTHORITY_PATH = "authority/Tianxia_Core_Character_Baseline_Owner_Amendment_R1.json"
_INITIATIVE_AUTHORITY_SHA256 = "2dec95e9b8087adf5fe9de4fa13a15c7c8e83ea12130549589ea1519db5290e0"
_INITIATIVE_RULE_ID = "tianxia.core.initiative.owner_r1"
_INITIATIVE_AUTHORITY_RULE_ID = "tianxia.core.baseline.initiative_bonus.owner_r1"
_INITIATIVE_FORMULA_ID = "tianxia.core.baseline.initiative_bonus.owner_r1"
_INITIATIVE_ADVANTAGE_SOURCE = "tianxia.origin_insight.street_hardened"
_INITIATIVE_PROVENANCE_MAPPING = {
    "authority_classification": "OWNER_RATIFIED_RULE_AMENDMENT",
    "baseline_pack_id": "tianxia.core.character_baseline.owner_r1",
    "baseline_pack_sha256": _SPEED_AUTHORITY_SHA256,
    "baseline_pack_version": "1.0.0",
    "destination_pointers": ["/ledger/core_stats/initiative_bonus", "/ledger/core_stats/initiative_generation"],
    "formula_trace": {
        "node_count": 1,
        "root": {"ability": "DEX", "op": "ability_modifier", "value": 2},
        "schema_version": "TianxiaFoundry.SafeFormulaTrace.v1",
    },
    "provenance_unit": "core_character_baseline_rule",
    "rule_id": _INITIATIVE_RULE_ID,
    "source": {
        "amendment_id": "Tianxia_Core_Character_Baseline_Owner_Amendment_R1",
        "amendment_sha256": _INITIATIVE_AUTHORITY_SHA256,
        "anchor": "/rules/1",
    },
    "transformation_kind": "SAFE_FORMULA_EVALUATION",
}
_INITIATIVE_COMPILER_FIELDS = (
    "ability",
    "proficiency_multiplier",
    "adjustment",
    "total",
    "source_grant_ids",
)
_INITIATIVE_COMPILER_EXTRA_FIELDS = _INITIATIVE_COMPILER_FIELDS[1:]
# Mirrors compiler v2's ``realm_for_cl``: CL 20 is the Immortal Realm (Q15).
_COMPILER_REALM_BANDS = (
    (1, 4, "Mortal"),
    (5, 9, "Foundation"),
    (10, 14, "Core Formation"),
    (15, 19, "Nascent Soul"),
    (20, 20, "Immortal"),
)


def _error(code: str, message: str, *, details: Any = None, status_code: int = 400) -> FoundryError:
    return FoundryError(code, message, details=details, status_code=status_code)


def _runtime_resource_context(
    active_resource_id: str | None = None,
    active_resource_name: str | None = None,
) -> tuple[str, str]:
    """Return one canonical Path resource for runtime normalization.

    Direct helper callers retain the historical Stamina default.  Production
    controller materialization passes the source-derived active resource and
    name explicitly, so a generic ``RES_CP`` alias can never establish its
    own runtime authority.
    """

    resource_id = COMPOSITE_CONTROLLER_RESOURCE_ID if active_resource_id is None else active_resource_id
    resource_name = _RUNTIME_RESOURCE_NAMES.get(resource_id)
    if resource_name is None:
        raise _error(
            "FINAL_CHARACTER_UNKNOWN_RUNTIME_RESOURCE",
            "The runtime resource context is not one canonical active Path resource.",
            details={"resource_id": resource_id},
        )
    if active_resource_name is not None and active_resource_name != resource_name:
        raise _error(
            "FINAL_CHARACTER_UNKNOWN_RUNTIME_RESOURCE",
            "The runtime resource context name does not match its canonical resource.",
            details={"resource_id": resource_id, "name": active_resource_name},
        )
    return resource_id, resource_name


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _reviewed_binding_identifier(value: Any, *, field: str) -> str:
    """Validate a bounded non-path identity used by the reviewed binding."""

    if (
        not isinstance(value, str)
        or not value
        or len(value) > 256
        or "\x00" in value
        or "\n" in value
        or "\r" in value
        or "/" in value
        or "\\" in value
    ):
        raise _error(
            "FINAL_CHARACTER_REVIEWED_BINDING_INVALID",
            f"The reviewed binding {field} is not a safe bounded identity.",
            details={"field": field},
        )
    return value


def _validate_reviewed_binding_envelope(value: Any) -> dict[str, Any]:
    """Validate the shape and self-commitment of a server-owned pair binding.

    The commitment is deliberately not treated as authority by itself.  The
    materializer must compare this normalized envelope with freshly validated
    source/overlay evidence via ``_validate_reviewed_binding_against_evidence``.
    Keeping the two checks separate makes a recomputed, attacker-authored
    envelope fail closed instead of becoming a caller-supplied allow-list.
    """

    if not isinstance(value, Mapping) or set(value) != _REVIEWED_BINDING_KEYS:
        raise _error(
            "FINAL_CHARACTER_REVIEWED_BINDING_INVALID",
            "The reviewed overlay binding envelope is incomplete or contains unsupported fields.",
        )
    if value.get("schema_version") != FINAL_CHARACTER_REVIEWED_BINDING_SCHEMA:
        raise _error(
            "FINAL_CHARACTER_REVIEWED_BINDING_INVALID",
            "The reviewed overlay binding envelope schema is unsupported.",
        )
    for field in ("project_id", "projection_id"):
        _reviewed_binding_identifier(value.get(field), field=field)
    for field in ("candidate_sha256", "source_workspace_sha256"):
        if not _is_hash(value.get(field)):
            raise _error(
                "FINAL_CHARACTER_REVIEWED_BINDING_INVALID",
                f"The reviewed binding {field} is not a lowercase SHA-256 digest.",
                details={"field": field},
            )
    overlays: dict[str, dict[str, Any]] = {}
    for overlay_name in ("composite_overlay",):
        overlay = value.get(overlay_name)
        if not isinstance(overlay, Mapping) or set(overlay) != _REVIEWED_OVERLAY_BINDING_KEYS:
            raise _error(
                "FINAL_CHARACTER_REVIEWED_BINDING_INVALID",
                f"The reviewed {overlay_name} binding is incomplete or contains unsupported fields.",
                details={"field": overlay_name},
            )
        _reviewed_binding_identifier(overlay.get("overlay_id"), field=f"{overlay_name}.overlay_id")
        for field in ("artifact_sha256", "overlay_tree_sha256", "files_tree_sha256"):
            if not _is_hash(overlay.get(field)):
                raise _error(
                    "FINAL_CHARACTER_REVIEWED_BINDING_INVALID",
                    f"The reviewed {overlay_name} {field} is not a lowercase SHA-256 digest.",
                    details={"field": f"{overlay_name}.{field}"},
                )
        overlays[overlay_name] = dict(overlay)
    arts = value.get("constructed_immortal_arts")
    if (
        not isinstance(arts, Mapping)
        or set(arts) != {"schema_version", "arts", "binding_sha256"}
        or not isinstance(arts.get("arts"), list)
        or not _is_hash(arts.get("binding_sha256"))
        or arts.get("binding_sha256") != sha256_json({key: arts[key] for key in ("schema_version", "arts")})
    ):
        raise _error(
            "FINAL_CHARACTER_REVIEWED_BINDING_INVALID",
            "The reviewed constructed Immortal Art binding is incomplete or not self-consistent.",
            details={"field": "constructed_immortal_arts"},
        )
    payload = {
        key: deepcopy(value[key])
        for key in sorted(_REVIEWED_BINDING_KEYS - {"binding_sha256"})
    }
    expected_binding_sha256 = sha256_json(payload)
    if value.get("binding_sha256") != expected_binding_sha256:
        raise _error(
            "FINAL_CHARACTER_REVIEWED_BINDING_INVALID",
            "The reviewed overlay binding commitment is invalid.",
            details={"expected": expected_binding_sha256, "actual": value.get("binding_sha256")},
        )
    normalized = deepcopy(dict(value))
    normalized["composite_overlay"] = overlays["composite_overlay"]
    normalized["constructed_immortal_arts"] = deepcopy(dict(arts))
    return normalized


def _validated_overlay_internal_tree_hash(root: Path, validated: Mapping[str, Any], *, label: str) -> str:
    """Return the semantic overlay-tree commitment exposed by a validator.

    The legacy Composite overlay predates an explicit internal tree hash, so
    its validator's exact
    no-checksum content tree is the only deterministic internal-tree
    commitment available; its checksum-inclusive tree remains separately
    bound as ``files_tree_sha256``.
    """

    explicit = validated.get("overlay_tree_sha256")
    if explicit is not None:
        if not _is_hash(explicit):
            raise _error(
                "FINAL_CHARACTER_REVIEWED_BINDING_INVALID",
                f"The validated {label} overlay has an invalid internal tree hash.",
            )
        return explicit
    try:
        return _tree_hash(Path(root), include_checksums=False)
    except FoundryError as exc:
        raise _error(
            "FINAL_CHARACTER_OVERLAY_REJECTED",
            f"The validated {label} overlay has no usable internal tree commitment.",
            details={"cause": exc.code},
        ) from exc


def _reviewed_binding_from_evidence(
    *,
    project_id: str,
    candidate_sha256: str,
    projection_id: str,
    source_workspace_sha256: str,
    composite_validated: Mapping[str, Any],
    composite_overlay_files_tree_sha256: str,
    composite_overlay_root: Path,
    constructed_immortal_arts: Mapping[str, Any],
) -> dict[str, Any]:
    """Construct the immutable envelope only from independently checked evidence."""

    composite_artifact = composite_validated.get("artifact")
    if not isinstance(composite_artifact, Mapping):
        raise _error("FINAL_CHARACTER_OVERLAY_BINDING_MISMATCH", "The validated Composite overlay does not expose a bound artifact.")
    values = {
        "project_id": project_id,
        "candidate_sha256": candidate_sha256,
        "projection_id": projection_id,
        "source_workspace_sha256": source_workspace_sha256,
    }
    for field, value in values.items():
        if field in {"candidate_sha256", "source_workspace_sha256"}:
            if not _is_hash(value):
                raise _error("FINAL_CHARACTER_OVERLAY_BINDING_MISMATCH", "Reviewed binding evidence has an invalid hash.", details={"field": field})
        else:
            _reviewed_binding_identifier(value, field=field)
    if (
        composite_artifact.get("project_id") != project_id
        or composite_artifact.get("base_candidate_sha256") != candidate_sha256
        or composite_artifact.get("source_workspace_sha256") != source_workspace_sha256
    ):
        raise _error(
            "FINAL_CHARACTER_OVERLAY_BINDING_MISMATCH",
            "The reviewed binding Composite artifact does not match the bound source context.",
            details={"field": "composite"},
        )
    if composite_artifact.get("projection_id") != projection_id:
        raise _error(
            "FINAL_CHARACTER_OVERLAY_BINDING_MISMATCH",
            "The reviewed binding projection does not match the validated Composite artifact.",
            details={"field": "projection_id"},
        )
    if not _reviewed_binding_identifier(composite_validated.get("overlay_id"), field="Composite.overlay_id") or not _is_hash(composite_validated.get("artifact_sha256")):
        raise _error(
            "FINAL_CHARACTER_OVERLAY_BINDING_MISMATCH",
            "The validated Composite overlay has incomplete identity/hash evidence.",
        )
    if not _is_hash(composite_overlay_files_tree_sha256):
        raise _error("FINAL_CHARACTER_OVERLAY_BINDING_MISMATCH", "Reviewed binding overlay file-tree evidence is not hashed.")
    composite = {
        "overlay_id": composite_validated.get("overlay_id"),
        "artifact_sha256": composite_validated.get("artifact_sha256"),
        "overlay_tree_sha256": _validated_overlay_internal_tree_hash(composite_overlay_root, composite_validated, label="Composite"),
        "files_tree_sha256": composite_overlay_files_tree_sha256,
    }
    envelope = {
        "schema_version": FINAL_CHARACTER_REVIEWED_BINDING_SCHEMA,
        **values,
        "composite_overlay": composite,
        "constructed_immortal_arts": deepcopy(dict(constructed_immortal_arts)),
    }
    envelope["binding_sha256"] = sha256_json(envelope)
    return _validate_reviewed_binding_envelope(envelope)


def _validate_reviewed_binding_against_evidence(
    binding: Mapping[str, Any],
    *,
    project_id: str,
    candidate_sha256: str,
    projection_id: str,
    source_workspace_sha256: str,
    composite_validated: Mapping[str, Any],
    composite_overlay_files_tree_sha256: str,
    composite_overlay_root: Path,
    constructed_immortal_arts: Mapping[str, Any],
) -> dict[str, Any]:
    """Reject self-consistent but unauthorized envelopes after fresh validation."""

    normalized = _validate_reviewed_binding_envelope(binding)
    expected = _reviewed_binding_from_evidence(
        project_id=project_id,
        candidate_sha256=candidate_sha256,
        projection_id=projection_id,
        source_workspace_sha256=source_workspace_sha256,
        composite_validated=composite_validated,
        composite_overlay_files_tree_sha256=composite_overlay_files_tree_sha256,
        composite_overlay_root=composite_overlay_root,
        constructed_immortal_arts=constructed_immortal_arts,
    )
    if canonical_json(normalized) != canonical_json(expected):
        mismatches: list[str] = []
        for field in ("project_id", "candidate_sha256", "projection_id", "source_workspace_sha256", "composite_overlay", "constructed_immortal_arts"):
            if normalized.get(field) != expected.get(field):
                mismatches.append(field)
        raise _error(
            "FINAL_CHARACTER_OVERLAY_BINDING_MISMATCH",
            "The reviewed binding envelope does not match freshly validated source and overlay evidence.",
            details={"fields": mismatches},
        )
    return expected


def _review_approval_parameters(binding: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the one server-owned ApprovalChallenge binding for a pair.

    The review issuer and the caller which obtains the owner's challenge must
    use the same canonical bytes and context.  Keeping this derivation in one
    pure helper prevents an evidence ID from being replayed for a different
    pair, while the review record itself still stores only the verified
    principal and evidence identity.
    """

    normalized = _validate_reviewed_binding_envelope(binding)
    exact_bytes = canonical_json(normalized).encode("utf-8")
    context = {
        "schema_version": FINAL_CHARACTER_REVIEW_APPROVAL_CONTEXT_SCHEMA,
        "operation": FINAL_CHARACTER_REVIEW_APPROVAL_OPERATION,
        "subject_type": FINAL_CHARACTER_REVIEW_APPROVAL_SUBJECT_TYPE,
        "subject_id": normalized["binding_sha256"],
        "project_id": normalized["project_id"],
        "candidate_sha256": normalized["candidate_sha256"],
        "projection_id": normalized["projection_id"],
        "source_workspace_sha256": normalized["source_workspace_sha256"],
        "binding_sha256": normalized["binding_sha256"],
    }
    return {
        "operation": FINAL_CHARACTER_REVIEW_APPROVAL_OPERATION,
        "subject_type": FINAL_CHARACTER_REVIEW_APPROVAL_SUBJECT_TYPE,
        "subject_id": normalized["binding_sha256"],
        "exact_bytes": exact_bytes,
        "binding": normalized,
        "project_lock_hash": normalized["source_workspace_sha256"],
        "evidence_context": context,
    }


def _assert_trusted_file(path: Path, expected_path: Path, expected_sha256: str, *, label: str) -> None:
    """Require one exact production file, never a caller-selected substitute."""

    path = Path(path)
    expected_path = Path(expected_path)
    # ``resolve`` would make a symlink appear equivalent to the pinned path;
    # trust is bound to the literal absolute identity and the bytes at it.
    if path.absolute() != expected_path.absolute() or path.is_symlink() or not path.is_file():
        raise _error(
            "FINAL_CHARACTER_TRUST_PIN_MISMATCH",
            f"The {label} is not the exact pinned production file.",
            details={"expected": str(expected_path), "actual": str(path)},
        )
    try:
        actual_sha256 = sha256_file(path)
    except OSError as exc:
        raise _error("FINAL_CHARACTER_TRUST_PIN_INVALID", f"The pinned {label} could not be hashed.", details={"path": str(path)}) from exc
    if actual_sha256 != expected_sha256:
        raise _error(
            "FINAL_CHARACTER_TRUST_PIN_MISMATCH",
            f"The pinned {label} bytes do not match the expected production hash.",
            details={"expected": expected_sha256, "actual": actual_sha256, "path": str(path)},
        )


def _corpus_pin(corpus_path: Path) -> str:
    if Path(corpus_path).absolute() == FINAL_CHARACTER_DEFAULT_CORPUS.absolute():
        return FINAL_CHARACTER_CORPUS_SHA256
    if Path(corpus_path).absolute() == _method_release.release_path(FINAL_CHARACTER_DEFAULT_STATE_ROOT / "vendor"):
        return _method_release.CORPUS_SHA256
    raise _error("FINAL_CHARACTER_TRUST_PIN_MISMATCH", "The rules corpus is not an exact production corpus location.")


def _assert_production_pins(compiler_path: Path, corpus_path: Path) -> None:
    _assert_trusted_file(
        compiler_path,
        FINAL_CHARACTER_DEFAULT_COMPILER,
        FINAL_CHARACTER_COMPILER_SHA256,
        label="compiler",
    )
    _assert_trusted_factory_root()
    _assert_trusted_file(
        corpus_path,
        FINAL_CHARACTER_DEFAULT_CORPUS if _corpus_pin(corpus_path) == FINAL_CHARACTER_CORPUS_SHA256 else _method_release.release_path(FINAL_CHARACTER_DEFAULT_STATE_ROOT / "vendor"),
        _corpus_pin(corpus_path),
        label="rules corpus",
    )
    if _corpus_pin(corpus_path) == _method_release.CORPUS_SHA256:
        _method_release._regular_path(corpus_path)
        _method_release.verified_source()


def _dependency_tree_hash(root: Path) -> str:
    """Hash every regular dependency file by its relative POSIX path."""

    root = Path(root)
    _ensure_regular_tree(root, code="FINAL_CHARACTER_DEPENDENCY_INVALID", message="The pinned compiler dependency root must be a regular tree.")
    files = {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }
    return sha256_json(files)


def _assert_trusted_factory_root() -> None:
    root = FINAL_CHARACTER_DEFAULT_FACTORY_ROOT
    if root.absolute() != FINAL_CHARACTER_DEFAULT_FACTORY_ROOT.absolute() or root.is_symlink() or not root.is_dir():
        raise _error(
            "FINAL_CHARACTER_DEPENDENCY_TRUST_MISMATCH",
            "The pinned compiler dependency root is not the exact production root.",
            details={"expected": str(FINAL_CHARACTER_DEFAULT_FACTORY_ROOT), "actual": str(root)},
        )
    try:
        actual = _dependency_tree_hash(root)
    except FoundryError:
        raise
    except OSError as exc:
        raise _error(
            "FINAL_CHARACTER_DEPENDENCY_TRUST_MISMATCH",
            "The pinned compiler dependency tree could not be hashed atomically.",
            details={"root": str(root), "error": str(exc)},
        ) from exc
    if actual != FINAL_CHARACTER_FACTORY_ROOT_SHA256:
        raise _error(
            "FINAL_CHARACTER_DEPENDENCY_TRUST_MISMATCH",
            "The pinned compiler dependency tree does not match the production trust root.",
            details={"expected": FINAL_CHARACTER_FACTORY_ROOT_SHA256, "actual": actual, "root": str(root)},
        )


def _safe_relative(value: Any, *, field: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise _error("FINAL_CHARACTER_PATH_INVALID", f"The {field} path is not a safe relative POSIX path.", details={"path": value})
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or value != path.as_posix() or path.as_posix().startswith("./"):
        raise _error("FINAL_CHARACTER_PATH_ESCAPE", f"The {field} path escapes its workspace.", details={"path": value})
    return path


def _safe_workspace_path(root: Path, relative: str, *, field: str) -> Path:
    path = _safe_relative(relative, field=field)
    candidate = root.joinpath(path)
    try:
        resolved_root = root.resolve()
        resolved_candidate = candidate.resolve(strict=False)
        resolved_candidate.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise _error("FINAL_CHARACTER_PATH_ESCAPE", f"The {field} path escapes its workspace.", details={"path": relative}) from exc
    return candidate


class _FixedDirectoryAuthority:
    """Hold one absolute directory and every ancestor used to reach it.

    A no-follow check on the final component does not protect a path whose
    parent can be renamed and replaced between checks.  This authority walks
    from the filesystem root with ``openat`` and retains the identity of every
    component.  Callers perform mutations relative to ``fd``; ``assert_current``
    is only a fail-closed diagnostic that detects a pathname replacement.
    """

    def __init__(self, path: Path, descriptor: int, identities: tuple[tuple[int, int], ...]) -> None:
        self.path = Path(path)
        self.fd = descriptor
        self._parts = tuple(self.path.parts[1:])
        self._identities = identities
        self._closed = False

    @property
    def fd_path(self) -> Path:
        if self._closed:
            raise _error("FINAL_CHARACTER_DIRECTORY_AUTHORITY_INVALID", "The fixed directory authority is closed.")
        return Path(f"/proc/self/fd/{self.fd}")

    @property
    def identity(self) -> tuple[int, int]:
        return self._identities[-1]

    def assert_current(self) -> None:
        if self._closed:
            raise _error("FINAL_CHARACTER_DIRECTORY_AUTHORITY_INVALID", "The fixed directory authority is closed.")
        current = os.open("/", os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
        try:
            root_stat = os.fstat(current)
            if (root_stat.st_dev, root_stat.st_ino) != self._identities[0]:
                raise OSError(errno.EAGAIN, "filesystem root changed")
            for index, part in enumerate(self._parts, start=1):
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=current,
                )
                os.close(current)
                current = child
                child_stat = os.fstat(current)
                if (child_stat.st_dev, child_stat.st_ino) != self._identities[index]:
                    raise OSError(errno.EAGAIN, "fixed directory ancestor changed")
        except OSError as exc:
            raise _error(
                "FINAL_CHARACTER_DIRECTORY_AUTHORITY_CHANGED",
                "A fixed directory authority changed while it was in use.",
                details={"path": str(self.path)},
            ) from exc
        finally:
            os.close(current)

    def close(self) -> None:
        if not self._closed:
            os.close(self.fd)
            self._closed = True


def _open_fixed_directory(path: Path | str, *, create: bool, mode: int = 0o700) -> _FixedDirectoryAuthority:
    """Open an absolute directory by descriptor-relative no-follow traversal."""

    requested = Path(os.path.abspath(os.fspath(path)))
    if not requested.is_absolute() or any(part in {"", ".", ".."} for part in requested.parts[1:]):
        raise OSError(errno.EINVAL, "directory authority path is not normalized and absolute")
    current = os.open("/", os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    identities: list[tuple[int, int]] = []
    try:
        root_stat = os.fstat(current)
        identities.append((root_stat.st_dev, root_stat.st_ino))
        for part in requested.parts[1:]:
            if create:
                try:
                    os.mkdir(part, mode, dir_fd=current)
                except FileExistsError:
                    pass
            child = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                dir_fd=current,
            )
            os.close(current)
            current = child
            child_stat = os.fstat(current)
            identities.append((child_stat.st_dev, child_stat.st_ino))
        return _FixedDirectoryAuthority(requested, current, tuple(identities))
    except Exception:
        os.close(current)
        raise


def _ensure_regular_tree(root: Path, *, code: str, message: str) -> None:
    root = Path(root)
    descriptor = _proc_fd_number(root)
    if descriptor is not None:
        try:
            descriptor_stat = os.fstat(descriptor)
        except OSError as exc:
            raise _error(code, message) from exc
        if not stat.S_ISDIR(descriptor_stat.st_mode):
            raise _error(code, message)
        _validate_regular_tree_fd(descriptor, code=code, message=message)
        return
    if root.is_symlink() or not root.is_dir():
        raise _error(code, message)
    _reject_recursive_symlinks(root, code=code, message=message)
    # The controller helper catches descendant symlinks.  This explicit walk
    # also makes the path-escape invariant visible at this boundary and catches
    # a malicious replacement between the two checks.
    root_resolved = root.resolve()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise _error(code, message, details={"path": path.relative_to(root).as_posix()})
        try:
            path.resolve(strict=False).relative_to(root_resolved)
        except (OSError, ValueError) as exc:
            raise _error(code, message, details={"path": path.relative_to(root).as_posix()}) from exc


def _read_json(path: Path, *, code: str = "FINAL_CHARACTER_JSON_INVALID") -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _error(code, f"Unable to read JSON file {path.name}.", details={"path": str(path)}) from exc
    return value


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write one stage file without exposing a partially written destination."""

    path = Path(path)
    if path.exists() and path.is_symlink():
        raise _error("FINAL_CHARACTER_OUTPUT_SYMLINK", "A materialization destination is a symlink.", details={"path": str(path)})
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _write_json(path: Path, value: Any) -> None:
    _atomic_write_bytes(path, (canonical_json(value) + "\n").encode("utf-8"))


def _exclusive_write_json(path: Path, value: Any) -> None:
    """Create an append-only JSON record without replacing a raced path."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (canonical_json(value) + "\n").encode("utf-8")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise _error("FINAL_CHARACTER_COLLISION", "The append-only materialization receipt path is already occupied.", details={"path": str(path)}) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _tree_hash(root: Path, *, include_checksums: bool = True) -> str:
    _ensure_regular_tree(root, code="FINAL_CHARACTER_TREE_INVALID", message="The materialized tree must contain regular files only.")
    descriptor = _proc_fd_number(Path(root))
    if descriptor is not None:
        return sha256_json(_tree_hashes_fd(descriptor, include_checksums=include_checksums))
    return sha256_json(_tree_hashes(root, include_checksums=include_checksums))


def _proc_fd_number(path: Path) -> int | None:
    match = re.fullmatch(r"/proc/self/fd/([0-9]+)", str(Path(path)))
    return int(match.group(1)) if match is not None else None


class _BoundDirectoryPath(type(Path())):
    """Path facade for a held descriptor, hiding procfs' link presentation."""

    def is_symlink(self) -> bool:
        # ``/proc/self/fd/N`` is itself a procfs symlink, but the kernel
        # resolves it to the already-held directory inode for every child
        # operation.  Existing validators reject a root symlink before they
        # inspect children, so only this synthetic presentation is masked.
        if _proc_fd_number(self) is not None:
            return False
        return super().is_symlink()


def _hash_file_fd(file_fd: int) -> str:
    digest = hashlib.sha256()
    while True:
        chunk = os.read(file_fd, 1024 * 1024)
        if not chunk:
            return digest.hexdigest()
        digest.update(chunk)


def _tree_hashes_fd(directory_fd: int, *, include_checksums: bool) -> dict[str, str]:
    """Hash a regular tree from a held directory descriptor."""

    result: dict[str, str] = {}

    def visit(fd: int, prefix: tuple[str, ...]) -> None:
        try:
            names = sorted(os.listdir(fd))
        except OSError as exc:
            raise _error("FINAL_CHARACTER_TREE_INVALID", "The materialized tree cannot be listed through its bound descriptor.", details={"path": _relative_entry(prefix)}) from exc
        for name in names:
            try:
                _safe_output_component(name)
                entry_stat = os.lstat(name, dir_fd=fd)
            except (FoundryError, OSError) as exc:
                raise _error("FINAL_CHARACTER_TREE_INVALID", "The materialized tree contains an invalid path entry.", details={"path": _relative_entry((*prefix, name))}) from exc
            entry_path = (*prefix, name)
            if stat.S_ISLNK(entry_stat.st_mode) or not (stat.S_ISREG(entry_stat.st_mode) or stat.S_ISDIR(entry_stat.st_mode)):
                raise _error("FINAL_CHARACTER_TREE_INVALID", "The materialized tree must contain regular files only.", details={"path": _relative_entry(entry_path)})
            if stat.S_ISDIR(entry_stat.st_mode):
                child_fd: int | None = None
                try:
                    child_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    child_stat = os.fstat(child_fd)
                    if (entry_stat.st_dev, entry_stat.st_ino) != (child_stat.st_dev, child_stat.st_ino):
                        raise _error("FINAL_CHARACTER_TREE_INVALID", "The materialized tree changed while it was being hashed.", details={"path": _relative_entry(entry_path)})
                    visit(child_fd, entry_path)
                except FoundryError:
                    raise
                except OSError as exc:
                    raise _error("FINAL_CHARACTER_TREE_INVALID", "The materialized tree changed while it was being hashed.", details={"path": _relative_entry(entry_path)}) from exc
                finally:
                    if child_fd is not None:
                        try:
                            os.close(child_fd)
                        except OSError:
                            pass
                continue
            if not include_checksums and name == "SHA256SUMS.txt":
                continue
            file_fd: int | None = None
            try:
                file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
                file_stat = os.fstat(file_fd)
                if (entry_stat.st_dev, entry_stat.st_ino) != (file_stat.st_dev, file_stat.st_ino):
                    raise _error("FINAL_CHARACTER_TREE_INVALID", "The materialized tree changed while it was being hashed.", details={"path": _relative_entry(entry_path)})
                result["/".join(entry_path)] = _hash_file_fd(file_fd)
            except FoundryError:
                raise
            except OSError as exc:
                raise _error("FINAL_CHARACTER_TREE_INVALID", "The materialized tree file cannot be hashed safely.", details={"path": _relative_entry(entry_path)}) from exc
            finally:
                if file_fd is not None:
                    try:
                        os.close(file_fd)
                    except OSError:
                        pass

    visit(directory_fd, ())
    return result


def _workspace_sha256(root: Path) -> str:
    descriptor = _proc_fd_number(Path(root))
    if descriptor is not None:
        _ensure_regular_tree(root, code="FINAL_CHARACTER_TREE_INVALID", message="The workspace must contain regular files only.")
        return sha256_json(_tree_hashes_fd(descriptor, include_checksums=True))
    return _path_workspace_sha256(Path(root))


def _safe_output_component(name: str) -> str:
    if not isinstance(name, str) or not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise _error("FINAL_CHARACTER_PATH_INVALID", "The materialization child name is not a safe relative component.")
    return name


def _assert_bound_parent_current(parent: Any) -> None:
    """Check a root or already-held parent without re-resolving its child."""

    checker = getattr(parent, "assert_current_path", None)
    if callable(checker):
        checker()
        return
    checker = getattr(parent, "assert_current", None)
    if not callable(checker):
        raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", "The materialization parent descriptor is not bound.")
    checker()


def _clear_directory_entries_fd(directory_fd: int, *, remove_entries: bool = False) -> None:
    """Clear regular files through a held directory descriptor only.

    There is no descriptor form of unlink/rmdir on Linux.  The default mode
    therefore never deletes a re-resolved name after an identity check: it
    opens each regular file or directory with ``O_NOFOLLOW``, verifies the
    inode, and truncates/recurses through that held descriptor.  Names
    (including a raced replacement) remain in place unless ``remove_entries``
    is requested by a still-bound invocation-owned child.  That bounded mode
    lets ordinary same-process failure cleanup remove copied source/overlay
    bytes without making an unbound path a deletion authority.
    """

    try:
        names = sorted(os.listdir(directory_fd))
    except OSError:
        return
    for name in names:
        try:
            _safe_output_component(name)
            entry_stat = os.lstat(name, dir_fd=directory_fd)
        except (FoundryError, OSError):
            continue
        if stat.S_ISLNK(entry_stat.st_mode):
            continue
        if stat.S_ISDIR(entry_stat.st_mode):
            child_fd: int | None = None
            try:
                child_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                held_stat = os.fstat(child_fd)
                if (entry_stat.st_dev, entry_stat.st_ino) != (held_stat.st_dev, held_stat.st_ino):
                    continue
                _clear_directory_fd(child_fd, remove_entries=remove_entries)
                if remove_entries:
                    try:
                        current_stat = os.lstat(name, dir_fd=directory_fd)
                        if (current_stat.st_dev, current_stat.st_ino) == (held_stat.st_dev, held_stat.st_ino):
                            os.rmdir(name, dir_fd=directory_fd)
                    except OSError:
                        pass
            except OSError:
                continue
            finally:
                if child_fd is not None:
                    try:
                        os.close(child_fd)
                    except OSError:
                        pass
            continue
        if not stat.S_ISREG(entry_stat.st_mode):
            continue
        file_fd: int | None = None
        try:
            file_fd = os.open(name, os.O_RDWR | os.O_NOFOLLOW, dir_fd=directory_fd)
            held_stat = os.fstat(file_fd)
            if (entry_stat.st_dev, entry_stat.st_ino) != (held_stat.st_dev, held_stat.st_ino):
                continue
            os.ftruncate(file_fd, 0)
            os.fsync(file_fd)
            if remove_entries:
                try:
                    current_stat = os.lstat(name, dir_fd=directory_fd)
                    if (current_stat.st_dev, current_stat.st_ino) == (held_stat.st_dev, held_stat.st_ino):
                        os.unlink(name, dir_fd=directory_fd)
                except OSError:
                    pass
        except OSError:
            continue
        finally:
                if file_fd is not None:
                    try:
                        os.close(file_fd)
                    except OSError:
                        pass


def _clear_directory_fd(directory_fd: int, *, remove_entries: bool = False) -> None:
    """Enumerate cleanup through a fresh descriptor at every directory level."""

    fresh_fd: int | None = None
    try:
        # A caller may have consumed the directory stream associated with its
        # held FD.  Opening ``.`` relative to it gives cleanup an independent
        # enumeration cursor while O_NOFOLLOW and inode equality retain the
        # descriptor boundary.
        fresh_fd = os.open(".", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
        held_stat = os.fstat(directory_fd)
        fresh_stat = os.fstat(fresh_fd)
        if (
            not stat.S_ISDIR(held_stat.st_mode)
            or not stat.S_ISDIR(fresh_stat.st_mode)
            or (held_stat.st_dev, held_stat.st_ino) != (fresh_stat.st_dev, fresh_stat.st_ino)
        ):
            return
        _clear_directory_entries_fd(fresh_fd, remove_entries=remove_entries)
    except OSError:
        return
    finally:
        if fresh_fd is not None:
            try:
                os.close(fresh_fd)
            except OSError:
                pass


def _clear_bound_child(parent: Any, name: str) -> None:
    """Leave an unbound name untouched; cleanup needs a held inode.

    A parent/name lookup cannot prove that the current entry is the child
    created by this invocation.  In particular, even an ``lstat``/``open``
    pair can bind an attacker-replaced directory before the caller has an
    original inode to compare against.  The only safe cleanup primitive is
    ``_BoundChildDirectory.cleanup`` on the descriptor retained at creation;
    path-only cleanup therefore deliberately does nothing and leaves the
    (normally empty) owned residue for the caller to remove out of band.
    """

    del parent, name


def _reserve_bound_child(parent: Any, name: str, *, mode: int = 0o700) -> "_BoundChildDirectory":
    """Reserve and hold one direct child using mkdirat/openat semantics."""

    name = _safe_output_component(name)
    _assert_bound_parent_current(parent)
    try:
        os.mkdir(name, mode, dir_fd=parent.fd)
    except FileExistsError as exc:
        raise _error("FINAL_CHARACTER_STAGING_COLLISION", "A reserved materialization child is already occupied.", details={"name": name}) from exc
    except OSError as exc:
        raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", "A materialization child cannot be created relative to its bound directory.", details={"name": name}) from exc
    descriptor: int | None = None
    try:
        _assert_bound_parent_current(parent)
        descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent.fd)
        descriptor_stat = os.fstat(descriptor)
        created_stat = os.lstat(name, dir_fd=parent.fd)
        if (
            not stat.S_ISDIR(descriptor_stat.st_mode)
            or not stat.S_ISDIR(created_stat.st_mode)
            or (descriptor_stat.st_dev, descriptor_stat.st_ino) != (created_stat.st_dev, created_stat.st_ino)
        ):
            raise _error("FINAL_CHARACTER_OUTPUT_CHILD_CHANGED", "The reserved materialization child changed while it was being opened.", details={"name": name})
        child = _BoundChildDirectory(parent, name, descriptor, descriptor_stat)
        child.assert_current()
        return child
    except Exception:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        _clear_bound_child(parent, name)
        raise


def _best_effort_remove_bound_child(binding: Any, name: str) -> None:
    """Clear one invocation-owned child without masking its primary error."""

    try:
        binding.remove_child(name)
    except (FoundryError, OSError):
        pass


class _BoundChildDirectory:
    """One reserved output-root child held by its own no-follow descriptor."""

    def __init__(self, parent: Any, name: str, descriptor: int, descriptor_stat: os.stat_result) -> None:
        self.parent = parent
        self.name = _safe_output_component(name)
        self.fd = descriptor
        self._identity = (descriptor_stat.st_dev, descriptor_stat.st_ino)
        self._closed = False

    @property
    def fd_path(self) -> Path:
        if self._closed:
            raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", "The materialization child descriptor is closed.")
        proc_path = _BoundDirectoryPath(f"/proc/self/fd/{self.fd}")
        if not proc_path.is_dir():
            raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", "The platform cannot expose the bound materialization child safely.")
        return proc_path

    def __truediv__(self, value: str) -> Path:
        """Keep narrow path-helper compatibility while retaining fd backing."""

        return self.fd_path / value

    @property
    def bound_path(self) -> Path:
        """A validator-compatible path rooted at the held parent descriptor."""

        return self.parent.fd_path / self.name

    def _name_matches_held_inode(self) -> bool:
        if self._closed:
            return False
        try:
            child_stat = os.lstat(self.name, dir_fd=self.parent.fd)
            held_stat = os.fstat(self.fd)
        except OSError:
            return False
        return (
            stat.S_ISDIR(child_stat.st_mode)
            and stat.S_ISDIR(held_stat.st_mode)
            and (child_stat.st_dev, child_stat.st_ino) == self._identity
            and (held_stat.st_dev, held_stat.st_ino) == self._identity
        )

    def assert_current(self) -> None:
        _assert_bound_parent_current(self.parent)
        if not self._name_matches_held_inode():
            raise _error(
                "FINAL_CHARACTER_OUTPUT_CHILD_CHANGED",
                "A reserved materialization output child changed before use.",
                details={"name": self.name},
            )

    def assert_current_path(self) -> None:
        """Allow this child to serve as the parent of another bound child."""

        self.assert_current()

    def create_bound_child(self, name: str, *, mode: int = 0o700) -> "_BoundChildDirectory":
        return _reserve_bound_child(self, name, mode=mode)

    def duplicate_for_name(self, parent: Any, name: str) -> "_BoundChildDirectory":
        """Bind this held inode to a freshly published parent/name pair."""

        name = _safe_output_component(name)
        _assert_bound_parent_current(parent)
        descriptor: int | None = None
        keep_descriptor = False
        try:
            descriptor = os.dup(self.fd)
            held_stat = os.fstat(descriptor)
            direct_stat = os.lstat(name, dir_fd=parent.fd)
            if (
                not stat.S_ISDIR(held_stat.st_mode)
                or not stat.S_ISDIR(direct_stat.st_mode)
                or (held_stat.st_dev, held_stat.st_ino) != (direct_stat.st_dev, direct_stat.st_ino)
            ):
                raise _error("FINAL_CHARACTER_OUTPUT_CHILD_CHANGED", "The published materialization child changed before it could be bound.", details={"name": name})
            keep_descriptor = True
            return _BoundChildDirectory(parent, name, descriptor, held_stat)
        except FileNotFoundError as exc:
            raise _error("FINAL_CHARACTER_OUTPUT_CHILD_CHANGED", "The published materialization child disappeared before it could be bound.", details={"name": name}) from exc
        except OSError as exc:
            raise _error("FINAL_CHARACTER_OUTPUT_CHILD_CHANGED", "The published materialization child cannot be bound without following links.", details={"name": name}) from exc
        finally:
            if descriptor is not None and not keep_descriptor:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def create_named_child(self, name: str) -> Path:
        """Reserve one direct child and return its fd-backed path."""

        name = _safe_output_component(name)
        self.assert_current()
        try:
            os.mkdir(name, 0o700, dir_fd=self.fd)
        except FileExistsError as exc:
            raise _error("FINAL_CHARACTER_STAGING_COLLISION", "A reserved materialization child is already occupied.", details={"name": name}) from exc
        except OSError as exc:
            raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", "A materialization child cannot be created relative to its bound directory.", details={"name": name}) from exc
        return self.fd_path / name

    def _clear_contents(self, *, remove_entries: bool = False) -> None:
        if self._closed:
            return
        _clear_directory_fd(self.fd, remove_entries=remove_entries)

    def cleanup(self) -> None:
        """Clear and remove this invocation-owned child when still bound.

        If the parent/name no longer resolves to the inode retained by this
        child, only the held inode is cleared.  That preserves the race-safe
        behavior of the descriptor boundary and leaves any replacement
        untouched.  For the normal same-process failure path, removing the
        exact empty tree prevents copied source/overlay bytes from surviving
        as staging residue.
        """

        if self._closed:
            return
        bound_name = self._name_matches_held_inode()
        try:
            self._clear_contents(remove_entries=bound_name)
            if bound_name and self._name_matches_held_inode():
                try:
                    os.rmdir(self.name, dir_fd=self.parent.fd)
                except OSError:
                    # A malformed/raced descendant is never removed by name;
                    # the held contents have already been cleared safely.
                    pass
        finally:
            self.close()

    def remove_child(self, name: str) -> None:
        _clear_bound_child(self, name)

    def close(self) -> None:
        if not self._closed:
            try:
                os.close(self.fd)
            finally:
                self._closed = True


class _BoundOutputRoot:
    """A private publication root held by inode, not by a mutable path."""

    def __init__(
        self,
        path: Path,
        descriptor: int,
        descriptor_stat: os.stat_result,
        *,
        authority: _FixedDirectoryAuthority | None = None,
    ) -> None:
        self.requested_path = Path(path).absolute()
        self.display_path = Path(path).absolute()
        self.fd = descriptor
        self._identity = (descriptor_stat.st_dev, descriptor_stat.st_ino)
        self._authority = authority
        self._closed = False

    @property
    def fd_path(self) -> Path:
        if self._closed:
            raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", "The materialization output-root descriptor is closed.")
        proc_path = _BoundDirectoryPath(f"/proc/self/fd/{self.fd}")
        if not proc_path.is_dir():
            raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", "The platform cannot expose the bound output-root descriptor safely.")
        return proc_path

    def assert_current_path(self) -> None:
        """Reject a root pathname swap while retaining the safe fd fallback."""

        if self._closed:
            raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", "The materialization output-root descriptor is closed.")
        try:
            if self._authority is not None:
                self._authority.assert_current()
            current_fd = os.fstat(self.fd)
            if not stat.S_ISDIR(current_fd.st_mode):
                raise OSError(errno.ENOTDIR, "bound output root is no longer a directory")
            current_path = os.lstat(self.requested_path)
        except (FoundryError, OSError) as exc:
            raise _error(
                "FINAL_CHARACTER_OUTPUT_ROOT_CHANGED",
                "The materialization output root changed after its descriptor was bound.",
                details={"path": str(self.requested_path)},
            ) from exc
        if (current_fd.st_dev, current_fd.st_ino) != self._identity or (current_path.st_dev, current_path.st_ino) != self._identity:
            raise _error(
                "FINAL_CHARACTER_OUTPUT_ROOT_CHANGED",
                "The materialization output root changed after its descriptor was bound.",
                details={"path": str(self.requested_path)},
            )
        if current_fd.st_uid != os.getuid() or stat.S_IMODE(current_fd.st_mode) & 0o077:
            raise _error(
                "FINAL_CHARACTER_OUTPUT_ROOT_CHANGED",
                "The bound materialization output root is no longer private to the current user.",
                details={"path": str(self.requested_path)},
            )

    def child_path(self, name: str) -> Path:
        return self.fd_path / _safe_output_component(name)

    def child_exists(self, name: str) -> bool:
        try:
            os.lstat(name, dir_fd=self.fd)
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", "The materialization child cannot be inspected safely.", details={"name": name}) from exc

    def create_temp_dir(self, prefix: str) -> tuple[Path, str]:
        """Compatibility path helper; new materialization uses bound children."""

        self.assert_current_path()
        for _ in range(128):
            name = f"{prefix}{secrets.token_hex(12)}"
            try:
                os.mkdir(name, 0o700, dir_fd=self.fd)
            except FileExistsError:
                continue
            except OSError as exc:
                raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", "The materialization staging directory cannot be created relative to the bound output root.", details={"name": name}) from exc
            try:
                self.assert_current_path()
            except Exception:
                _best_effort_remove_bound_child(self, name)
                raise
            return self.child_path(name), name
        raise _error("FINAL_CHARACTER_STAGING_COLLISION", "The materialization staging directory could not be reserved without a collision.")

    def create_bound_temp_dir(self, prefix: str) -> _BoundChildDirectory:
        self.assert_current_path()
        for _ in range(128):
            name = f"{prefix}{secrets.token_hex(12)}"
            try:
                return _reserve_bound_child(self, name)
            except FileExistsError:
                continue
            except FoundryError as exc:
                if exc.code == "FINAL_CHARACTER_STAGING_COLLISION":
                    continue
                raise
        raise _error("FINAL_CHARACTER_STAGING_COLLISION", "The materialization staging directory could not be reserved without a collision.")

    def remove_child(self, name: str) -> None:
        _clear_bound_child(self, name)

    def close(self) -> None:
        if not self._closed:
            try:
                if self._authority is not None:
                    self._authority.close()
                else:
                    os.close(self.fd)
            finally:
                self._closed = True


def _ensure_private_output_root(
    path: Path,
    *,
    expected_identity: tuple[int, int] | None = None,
    expected_present: bool | None = None,
) -> _BoundOutputRoot:
    """Create/check and retain the caller-provided publication boundary."""

    path = Path(path)
    # A workflow handoff has already created the root through a held
    # descriptor.  Reopen read-only at this seam so a replaced ancestor cannot
    # cause mkdirat to create a new leaf outside that original inode.
    open_create = expected_present is None
    try:
        authority = _open_fixed_directory(path, create=open_create, mode=0o700)
    except OSError as exc:
        raise _error(
            "FINAL_CHARACTER_OUTPUT_ROOT_INVALID",
            "The materialization output root cannot be created or inspected safely.",
            details={"path": str(path)},
        ) from exc
    descriptor = authority.fd
    try:
        if expected_present is False or (expected_identity is not None and authority.identity != expected_identity):
            raise _error(
                "FINAL_CHARACTER_OUTPUT_ROOT_CHANGED",
                "The materialization output root changed before its descriptor was bound.",
                details={"path": str(path)},
            )
        descriptor_stat = os.fstat(descriptor)
        if not stat.S_ISDIR(descriptor_stat.st_mode):
            raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", "The materialization output root must be a regular directory.")
        if descriptor_stat.st_uid != os.getuid() or stat.S_IMODE(descriptor_stat.st_mode) & 0o077:
            raise _error(
                "FINAL_CHARACTER_OUTPUT_ROOT_INVALID",
                "The materialization output root must be a private directory owned by the current user.",
                details={"path": str(path), "owner_uid": descriptor_stat.st_uid, "mode": oct(stat.S_IMODE(descriptor_stat.st_mode))},
            )
        bound = _BoundOutputRoot(authority.path, descriptor, descriptor_stat, authority=authority)
        bound.assert_current_path()
        return bound
    except FoundryError:
        authority.close()
        raise
    except OSError as exc:
        authority.close()
        raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", "The materialization output root cannot be resolved.", details={"path": str(path)}) from exc


def _atomic_publish_noreplace(
    stage: Path,
    final: Path,
    *,
    root_fd: int | None = None,
    stage_binding: _BoundChildDirectory | None = None,
) -> None:
    """Atomically rename a bundle without ever replacing an existing path.

    The optional descriptor is used by the real materializer.  Keeping the
    two direct-child names relative to that already-bound descriptor prevents
    an output-root pathname swap from redirecting publication.  The path-only
    form remains for the small pure atomic-publication tests and legacy
    callers; it performs its historical no-follow parent check.
    """

    stage = Path(stage)
    final = Path(final)
    if stage_binding is not None:
        if root_fd is None:
            raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", "The staged bundle is not bound to its reserved output child.")
        stage_binding.assert_current()
    if root_fd is None:
        if stage.parent.resolve(strict=True) != final.parent.resolve(strict=True):
            raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", "The staged bundle and final bundle do not share one output boundary.")
        try:
            descriptor = os.open(stage.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as exc:
            raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", "The materialization output root failed its no-follow publication check.") from exc
        stage_name = stage_binding.name if stage_binding is not None else stage.name
        final_name = final.name
        close_descriptor = True
    else:
        if not isinstance(root_fd, int) or root_fd < 0:
            raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", "The bound materialization output-root descriptor is invalid.")
        try:
            descriptor = os.dup(root_fd)
            descriptor_stat = os.fstat(descriptor)
        except OSError as exc:
            raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", "The bound materialization output-root descriptor cannot be duplicated safely.") from exc
        if not stat.S_ISDIR(descriptor_stat.st_mode):
            os.close(descriptor)
            raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", "The bound materialization output-root descriptor is not a directory.")
        stage_name = stage_binding.name if stage_binding is not None else stage.name
        final_name = final.name
        close_descriptor = True
    if not isinstance(stage_name, str) or not stage_name or stage_name in {".", ".."} or "/" in stage_name or "\\" in stage_name:
        if close_descriptor:
            os.close(descriptor)
        raise _error("FINAL_CHARACTER_PATH_INVALID", "The staged bundle name is not a safe relative component.")
    if not isinstance(final_name, str) or not final_name or final_name in {".", ".."} or "/" in final_name or "\\" in final_name:
        if close_descriptor:
            os.close(descriptor)
        raise _error("FINAL_CHARACTER_PATH_INVALID", "The final bundle name is not a safe relative component.")
    try:
        try:
            stage_stat = os.lstat(stage_name, dir_fd=descriptor)
        except FileNotFoundError as exc:
            raise _error("FINAL_CHARACTER_STAGING_COLLISION", "The reserved materialization staging directory disappeared before publication.", details={"path": str(stage)}) from exc
        if stat.S_ISLNK(stage_stat.st_mode) or not stat.S_ISDIR(stage_stat.st_mode):
            raise _error("FINAL_CHARACTER_STAGING_COLLISION", "The reserved materialization staging path is not a regular directory.", details={"path": str(stage)})
        if stage_binding is not None:
            held_stat = os.fstat(stage_binding.fd)
            if (stage_stat.st_dev, stage_stat.st_ino) != stage_binding._identity or (held_stat.st_dev, held_stat.st_ino) != stage_binding._identity:
                raise _error("FINAL_CHARACTER_OUTPUT_CHILD_CHANGED", "The reserved staging directory changed before publication.", details={"name": stage_name})
        try:
            os.lstat(final_name, dir_fd=descriptor)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise _error("FINAL_CHARACTER_COLLISION", "The final bundle path cannot be inspected without following links.", details={"path": str(final)}) from exc
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            renameat2 = getattr(libc, "renameat2")
        except (AttributeError, OSError) as exc:
            raise _error("FINAL_CHARACTER_PUBLISH_UNSUPPORTED", "Atomic no-replace directory publication is unavailable on this platform.") from exc
        renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        renameat2.restype = ctypes.c_int
        result = renameat2(descriptor, stage_name.encode("utf-8"), descriptor, final_name.encode("utf-8"), 1)
        if result != 0:
            error_number = ctypes.get_errno()
            if error_number == errno.EEXIST:
                raise _error("FINAL_CHARACTER_COLLISION", "The final bundle path was occupied before atomic publication.", details={"path": str(final)})
            if error_number in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:
                raise _error("FINAL_CHARACTER_PUBLISH_UNSUPPORTED", "The platform does not support atomic no-replace publication.", details={"errno": error_number})
            raise _error("FINAL_CHARACTER_PUBLISH_FAILED", "Atomic no-replace bundle publication failed.", details={"errno": error_number})
    finally:
        if close_descriptor:
            os.close(descriptor)


def _relative_entry(path_parts: tuple[str, ...]) -> str:
    return "/".join(path_parts) if path_parts else "."


def _copy_directory_fd(source_fd: int, destination_fd: int, *, relative: tuple[str, ...] = (), code: str, label: str) -> None:
    """Recursively copy one regular tree using only descriptor-relative I/O."""

    try:
        names = sorted(os.listdir(source_fd))
    except OSError as exc:
        raise _error(code, f"The {label} source directory cannot be listed safely.", details={"path": _relative_entry(relative)}) from exc
    for name in names:
        try:
            _safe_output_component(name)
            source_stat = os.lstat(name, dir_fd=source_fd)
        except (FoundryError, OSError) as exc:
            raise _error(code, f"The {label} source contains an invalid path entry.", details={"path": _relative_entry((*relative, name))}) from exc
        entry_relative = (*relative, name)
        if stat.S_ISLNK(source_stat.st_mode):
            raise _error(code, f"The {label} source contains a symlink.", details={"path": _relative_entry(entry_relative)})
        if stat.S_ISDIR(source_stat.st_mode):
            source_child_fd: int | None = None
            destination_child_fd: int | None = None
            try:
                source_child_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=source_fd)
                source_child_stat = os.fstat(source_child_fd)
                if (source_child_stat.st_dev, source_child_stat.st_ino) != (source_stat.st_dev, source_stat.st_ino):
                    raise _error(code, f"The {label} source directory changed while it was being copied.", details={"path": _relative_entry(entry_relative)})
                os.mkdir(name, 0o700, dir_fd=destination_fd)
                created_stat = os.lstat(name, dir_fd=destination_fd)
                destination_child_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=destination_fd)
                destination_child_stat = os.fstat(destination_child_fd)
                if (
                    not stat.S_ISDIR(created_stat.st_mode)
                    or (created_stat.st_dev, created_stat.st_ino) != (destination_child_stat.st_dev, destination_child_stat.st_ino)
                ):
                    raise _error(code, f"The {label} destination directory changed while it was being created.", details={"path": _relative_entry(entry_relative)})
                _copy_directory_fd(source_child_fd, destination_child_fd, relative=entry_relative, code=code, label=label)
            except FileExistsError as exc:
                raise _error("FINAL_CHARACTER_STAGING_COLLISION", f"The {label} destination contains a colliding directory.", details={"path": _relative_entry(entry_relative)}) from exc
            except FoundryError:
                raise
            except OSError as exc:
                raise _error(code, f"The {label} directory could not be copied without following links.", details={"path": _relative_entry(entry_relative)}) from exc
            finally:
                if destination_child_fd is not None:
                    try:
                        os.close(destination_child_fd)
                    except OSError:
                        pass
                if source_child_fd is not None:
                    try:
                        os.close(source_child_fd)
                    except OSError:
                        pass
            continue
        if not stat.S_ISREG(source_stat.st_mode):
            raise _error(code, f"The {label} source contains a non-regular entry.", details={"path": _relative_entry(entry_relative)})
        source_file_fd: int | None = None
        destination_file_fd: int | None = None
        try:
            source_file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=source_fd)
            source_file_stat = os.fstat(source_file_fd)
            if (source_file_stat.st_dev, source_file_stat.st_ino) != (source_stat.st_dev, source_stat.st_ino):
                raise _error(code, f"The {label} source file changed while it was being copied.", details={"path": _relative_entry(entry_relative)})
            destination_file_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=destination_fd)
            while True:
                chunk = os.read(source_file_fd, 1024 * 1024)
                if not chunk:
                    break
                view = memoryview(chunk)
                while view:
                    written = os.write(destination_file_fd, view)
                    if written <= 0:
                        raise OSError(errno.EIO, "destination write made no progress")
                    view = view[written:]
            os.fsync(destination_file_fd)
        except FileExistsError as exc:
            raise _error("FINAL_CHARACTER_STAGING_COLLISION", f"The {label} destination contains a colliding file.", details={"path": _relative_entry(entry_relative)}) from exc
        except FoundryError:
            raise
        except OSError as exc:
            raise _error(code, f"The {label} file could not be copied without following links.", details={"path": _relative_entry(entry_relative)}) from exc
        finally:
            if destination_file_fd is not None:
                try:
                    os.close(destination_file_fd)
                except OSError:
                    pass
            if source_file_fd is not None:
                try:
                    os.close(source_file_fd)
                except OSError:
                    pass


def _validate_regular_tree_fd(directory_fd: int, *, code: str, message: str, relative: tuple[str, ...] = ()) -> None:
    """Verify a directory descriptor tree without resolving descendant names."""

    try:
        names = sorted(os.listdir(directory_fd))
    except OSError as exc:
        raise _error(code, message, details={"path": _relative_entry(relative)}) from exc
    for name in names:
        try:
            _safe_output_component(name)
            entry_stat = os.lstat(name, dir_fd=directory_fd)
        except (FoundryError, OSError) as exc:
            raise _error(code, message, details={"path": _relative_entry((*relative, name))}) from exc
        if stat.S_ISLNK(entry_stat.st_mode) or not (stat.S_ISREG(entry_stat.st_mode) or stat.S_ISDIR(entry_stat.st_mode)):
            raise _error(code, message, details={"path": _relative_entry((*relative, name))})
        if stat.S_ISDIR(entry_stat.st_mode):
            child_fd: int | None = None
            try:
                child_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                child_stat = os.fstat(child_fd)
                if (entry_stat.st_dev, entry_stat.st_ino) != (child_stat.st_dev, child_stat.st_ino):
                    raise _error(code, message, details={"path": _relative_entry((*relative, name))})
                _validate_regular_tree_fd(child_fd, code=code, message=message, relative=(*relative, name))
            except FoundryError:
                raise
            except OSError as exc:
                raise _error(code, message, details={"path": _relative_entry((*relative, name))}) from exc
            finally:
                if child_fd is not None:
                    try:
                        os.close(child_fd)
                    except OSError:
                        pass


def _copy_tree_into_bound_directory(source: Path, destination: _BoundChildDirectory, *, code: str, label: str) -> None:
    """Copy a source tree into an already-held destination child directory."""

    destination.assert_current()
    source_fd: int | None = None
    try:
        source_fd = os.open(Path(source), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        source_stat = os.fstat(source_fd)
        if not stat.S_ISDIR(source_stat.st_mode):
            raise _error(code, f"The {label} source must be a directory.")
        _copy_directory_fd(source_fd, destination.fd, code=code, label=label)
        _validate_regular_tree_fd(destination.fd, code=code, message=f"The copied {label} tree contains a link or non-regular entry.")
        destination.assert_current()
    except FoundryError:
        raise
    except OSError as exc:
        raise _error(code, f"The {label} source cannot be opened without following links.", details={"path": str(source)}) from exc
    finally:
        if source_fd is not None:
            try:
                os.close(source_fd)
            except OSError:
                pass


def _copy_tree_no_symlinks(source: Path, target: Path | _BoundChildDirectory) -> None:
    """Compatibility wrapper using descriptor-relative recursive copying."""

    source = Path(source)
    if isinstance(target, _BoundChildDirectory):
        _copy_tree_into_bound_directory(source, target, code="FINAL_CHARACTER_SOURCE_SYMLINK", label="source workspace")
        return
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise _error("FINAL_CHARACTER_STAGING_COLLISION", "The reserved materialization staging directory is occupied.")
    try:
        target.mkdir(parents=True, mode=0o700)
        destination_fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise _error("FINAL_CHARACTER_STAGING_COLLISION", "The reserved materialization staging directory cannot be opened safely.", details={"path": str(target)}) from exc
    source_fd: int | None = None
    try:
        source_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        source_stat = os.fstat(source_fd)
        if not stat.S_ISDIR(source_stat.st_mode):
            raise _error("FINAL_CHARACTER_SOURCE_INVALID", "The source workspace must be a directory.")
        _copy_directory_fd(source_fd, destination_fd, code="FINAL_CHARACTER_SOURCE_SYMLINK", label="source workspace")
        _validate_regular_tree_fd(destination_fd, code="FINAL_CHARACTER_STAGING_INVALID", message="The copied workspace contains a symlink or path escape.")
    except FoundryError:
        raise
    except OSError as exc:
        raise _error("FINAL_CHARACTER_SOURCE_INVALID", "The source workspace cannot be copied safely.", details={"path": str(source)}) from exc
    finally:
        if source_fd is not None:
            try:
                os.close(source_fd)
            except OSError:
                pass
        os.close(destination_fd)


def _verify_copied_workspace(workspace: Path, expected_source_hash: str) -> None:
    """Close the copy/apply boundary before any overlay operation runs."""

    try:
        _verify_workspace_checksums(workspace)
        copied_hash = _workspace_sha256(workspace)
    except FoundryError as exc:
        raise _error(
            "FINAL_CHARACTER_SOURCE_COPY_MISMATCH",
            "The copied workspace checksum ledgers could not be verified before applying overlays.",
            details={"cause": exc.code, "message": exc.message},
        ) from exc
    if copied_hash != expected_source_hash:
        raise _error(
            "FINAL_CHARACTER_SOURCE_COPY_MISMATCH",
            "The copied workspace does not match the sealed source workspace hash.",
            details={"expected": expected_source_hash, "actual": copied_hash},
        )


def _copy_overlay_snapshot(source: Path, target: Path | _BoundChildDirectory, *, code: str, label: str) -> None:
    """Copy an accepted overlay once, then consume only that private copy."""

    try:
        _ensure_regular_tree(
            source,
            code=code,
            message=f"The {label} overlay must be a regular tree without links.",
        )
        if isinstance(target, _BoundChildDirectory):
            _copy_tree_into_bound_directory(source, target, code=code, label=label)
        else:
            _copy_tree_no_symlinks(source, target)
    except FoundryError as exc:
        raise _error(code, f"The {label} overlay could not be snapshotted without following links.", details={"cause": exc.code, "message": exc.message}) from exc


def _load_compiler_module(compiler_path: Path) -> Any:
    _assert_trusted_file(compiler_path, FINAL_CHARACTER_DEFAULT_COMPILER, FINAL_CHARACTER_COMPILER_SHA256, label="compiler")
    _assert_trusted_factory_root()
    module_name = f"final_character_pinned_compiler_{sha256_file(compiler_path)[:16]}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, compiler_path)
        if spec is None or spec.loader is None:
            raise ImportError("compiler module spec unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:
        raise _error("FINAL_CHARACTER_COMPILER_PRECONDITION", "The pinned compiler could not be loaded for checkpoint semantics.", details={"compiler": str(compiler_path), "error": str(exc)}) from exc
    if not callable(getattr(module, "checkpoint_hash", None)):
        raise _error("FINAL_CHARACTER_CHECKPOINT_PRECONDITION", "The pinned compiler exposes no checkpoint_hash function.")
    return module


class _Missing:
    pass


_MISSING = _Missing()


def _normalise_resource_rows(
    value: Any,
    *,
    field: str,
    active_resource_id: str | None = None,
) -> list[dict[str, Any]]:
    active_resource_id, _active_resource_name = _runtime_resource_context(active_resource_id)
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise _error("FINAL_CHARACTER_RESOURCE_MAPPING_INVALID", f"The {field} resource rows are not a list.")
    rows: list[dict[str, Any]] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise _error("FINAL_CHARACTER_RESOURCE_MAPPING_INVALID", f"The {field} resource row is not an object.")
        resource = _canonical_resource_id(
            row.get("resource_id") or row.get("id") or row.get("resource"),
            active_resource_id=active_resource_id,
        )
        if resource != active_resource_id:
            raise _error("FINAL_CHARACTER_UNKNOWN_RUNTIME_RESOURCE", "A controller action references an unrecognized runtime resource.", details={"field": field, "resource_id": row.get("resource_id")})
        normal = deepcopy(dict(row))
        normal["resource_id"] = active_resource_id
        rows.append(normal)
    return rows


def _normalise_step_costs(
    value: Any,
    *,
    field: str,
    active_resource_id: str | None = None,
) -> list[dict[str, Any]]:
    active_resource_id, _active_resource_name = _runtime_resource_context(active_resource_id)
    rows = _normalise_resource_rows(value, field=field, active_resource_id=active_resource_id)
    result = []
    for row in rows:
        result.append({"resource_id": active_resource_id, "amount": row.get("amount", row.get("cost"))})
    return result


def _server_owned_preconditions(
    action: Mapping[str, Any],
    *,
    field: str,
    active_resource_id: str | None = None,
    active_resource_name: str | None = None,
) -> list[str]:
    """Derive controller preconditions from canonical resource requirements."""

    active_resource_id, canonical_name = _runtime_resource_context(active_resource_id, active_resource_name)
    requirements = _normalise_resource_rows(
        action.get("resource_requirements"),
        field=f"{field}.resource_requirements",
        active_resource_id=active_resource_id,
    )
    result: list[str] = []
    for row in requirements:
        minimum = row.get("minimum")
        if type(minimum) is not int or minimum < 0:
            raise _error("FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE", "A canonical resource requirement has no valid minimum.", details={"field": field})
        resource_id = row.get("resource_id")
        if resource_id != active_resource_id:
            raise _error("FINAL_CHARACTER_UNKNOWN_RUNTIME_RESOURCE", "A canonical requirement uses an unrecognized runtime resource.", details={"resource_id": resource_id, "field": field})
        result.append(f"{canonical_name} >= {minimum}")
    return result


def _advisory_external_preconditions(value: Any, *, field: str) -> dict[str, Any]:
    """Bound provider planning notes without promoting them to rules."""

    if not isinstance(value, list) or len(value) > 16:
        raise _error(
            "FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE",
            "A controller advisory precondition projection must be a bounded list.",
            details={"field": field},
        )
    notes: list[str] = []
    total_bytes = 0
    for note in value:
        if not isinstance(note, str) or not note.strip() or len(note) > 512:
            raise _error(
                "FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE",
                "A controller advisory precondition must be a bounded non-empty string.",
                details={"field": field},
            )
        total_bytes += len(note.encode("utf-8"))
        if total_bytes > 4096:
            raise _error(
                "FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE",
                "A controller advisory precondition projection exceeds its bounded size.",
                details={"field": field},
            )
        notes.append(note)
    return {"execution_authority": False, "values": notes}


def _runtime_step_metadata(
    action: Mapping[str, Any],
    step: Mapping[str, Any],
    *,
    field: str,
    active_resource_id: str | None = None,
    active_resource_name: str | None = None,
) -> dict[str, Any]:
    """Validate supplied policy metadata, then return only canonical projections."""

    active_resource_id, active_resource_name = _runtime_resource_context(active_resource_id, active_resource_name)
    canonical_costs = _normalise_step_costs(
        action.get("resource_costs"),
        field=f"{field}.canonical_resource_costs",
        active_resource_id=active_resource_id,
    )
    canonical_requirements = _normalise_resource_rows(
        action.get("resource_requirements"),
        field=f"{field}.canonical_resource_requirements",
        active_resource_id=active_resource_id,
    )
    canonical_states = deepcopy(action.get("state_arrays") if action.get("state_arrays") is not None else [])
    if not isinstance(canonical_states, list):
        raise _error("FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE", "A canonical action state projection is not a list.", details={"field": field})
    canonical_preconditions = _server_owned_preconditions(
        action,
        field=field,
        active_resource_id=active_resource_id,
        active_resource_name=active_resource_name,
    )

    if "cost" in step and step.get("cost") != action.get("cost"):
        raise _error("FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE", "A controller step cost text diverges from canonical mechanics.", details={"field": field})
    if "resource_costs" in step:
        supplied_costs = _normalise_step_costs(
            step.get("resource_costs"),
            field=f"{field}.resource_costs",
            active_resource_id=active_resource_id,
        )
        if supplied_costs != canonical_costs:
            raise _error("FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE", "A controller step cost projection diverges from canonical mechanics.", details={"field": field})
    if "resource_requirements" in step:
        supplied_requirements = _normalise_resource_rows(
            step.get("resource_requirements"),
            field=f"{field}.resource_requirements",
            active_resource_id=active_resource_id,
        )
        if supplied_requirements != canonical_requirements:
            raise _error("FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE", "A controller step requirement projection diverges from canonical mechanics.", details={"field": field})
    if "requires_states" in step and step.get("requires_states") != canonical_states:
        raise _error("FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE", "A controller step state projection diverges from canonical mechanics.", details={"field": field})
    if "state_arrays" in step and step.get("state_arrays") != canonical_states:
        raise _error("FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE", "A controller step state array diverges from canonical mechanics.", details={"field": field})
    metadata = {
        "resource_costs": canonical_costs,
        "resource_requirements": canonical_requirements,
        "requires_states": canonical_states,
        "external_preconditions": canonical_preconditions,
    }
    if "external_preconditions" in step:
        # The field is accepted only as bounded presentation/planning notes.
        # It is deliberately kept out of the executable authority projection;
        # the canonical requirements above remain the sole source of runtime
        # preconditions.
        metadata["advisory_external_preconditions"] = _advisory_external_preconditions(
            step.get("external_preconditions"),
            field=f"{field}.external_preconditions",
        )
    return metadata


def _runtime_cost_total(rows: Any, *, field: str, maximum: int) -> int:
    """Validate and total one source-bound active-resource cost projection."""

    if not isinstance(rows, list):
        raise _error(
            "FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE",
            "A controller cost projection is not a list.",
            details={"field": field},
        )
    total = 0
    for row in rows:
        if not isinstance(row, Mapping):
            raise _error(
                "FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE",
                "A controller cost projection contains a malformed row.",
                details={"field": field},
            )
        amount = row.get("amount")
        if type(amount) is not int or amount < 0 or amount > maximum:
            raise _error(
                "FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE",
                "A controller cost amount is outside the active Path resource bounds.",
                details={"field": field, "amount": amount, "maximum": maximum},
            )
        total += amount
        if total > maximum:
            raise _error(
                "FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE",
                "A controller cost projection exceeds the active Path resource maximum.",
                details={"field": field, "maximum": maximum},
            )
    return total


def _canonical_action_index(root: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    surface_path = root / "Command_4/Complete_Action_Surface.json"
    surface = _read_json(surface_path, code="FINAL_CHARACTER_ACTION_SURFACE_INVALID")
    rows = surface.get("actions") if isinstance(surface, Mapping) else None
    if not isinstance(rows, list):
        raise _error("FINAL_CHARACTER_ACTION_SURFACE_INVALID", "The canonical Complete Action Surface has no actions list.")
    packets: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise _error("FINAL_CHARACTER_ACTION_SURFACE_INVALID", "The canonical action surface contains a non-object row.")
        packet = _action_packet(row)
        # Immortal Art intentionally introduces a new action ID while
        # retaining the original Ash talent record ID as source lineage.  A
        # duplicate record ID is therefore legal here; action IDs remain the
        # executable identity and must be unique.
        if packet["action_id"] in by_id:
            raise _error("FINAL_CHARACTER_ACTION_SURFACE_DIVERGENCE", "The canonical action surface contains duplicate action identities.")
        by_id[packet["action_id"]] = packet
        packets.append(packet)
    if not packets:
        raise _error("FINAL_CHARACTER_ACTION_SURFACE_INVALID", "The canonical Complete Action Surface is empty.")
    return by_id, packets


def _runtime_action_ref(
    action: Mapping[str, Any],
    *,
    economy: str | None = None,
    round_offset: int | None = None,
    costs: Any = None,
    requires_states: Any = None,
    external_preconditions: Any = None,
    advisory_external_preconditions: Any = None,
    active_resource_id: str | None = None,
    active_resource_name: str | None = None,
) -> dict[str, Any]:
    active_resource_id, _active_resource_name = _runtime_resource_context(active_resource_id, active_resource_name)
    ref: dict[str, Any] = {
        "action_id": action["action_id"],
        "record_id": action["record_id"],
        "economy": economy or action["economy"],
        "source_action_sha256": sha256_json(dict(action)),
        "resource_costs": _normalise_step_costs(
            action.get("resource_costs"),
            field=f"action.{action['action_id']}.resource_costs",
            active_resource_id=active_resource_id,
        ),
        "resource_requirements": _normalise_resource_rows(
            action.get("resource_requirements"),
            field=f"action.{action['action_id']}.resource_requirements",
            active_resource_id=active_resource_id,
        ),
    }
    if round_offset is not None:
        ref["round_offset"] = round_offset
    if costs is not None:
        ref["sequence_resource_costs"] = _normalise_step_costs(
            costs,
            field=f"sequence.{action['action_id']}.resource_costs",
            active_resource_id=active_resource_id,
        )
    if requires_states is not None:
        ref["requires_states"] = deepcopy(requires_states)
    if external_preconditions is not None:
        ref["external_preconditions"] = deepcopy(external_preconditions)
    if advisory_external_preconditions is not None:
        ref["advisory_external_preconditions"] = deepcopy(advisory_external_preconditions)
    return ref


def _resolve_artifact_action(
    artifact_action: Mapping[str, Any],
    by_id: Mapping[str, dict[str, Any]],
    *,
    active_resource_id: str | None = None,
    active_resource_name: str | None = None,
) -> dict[str, Any]:
    active_resource_id, _active_resource_name = _runtime_resource_context(active_resource_id, active_resource_name)
    action_id = artifact_action.get("action_id")
    record_id = artifact_action.get("record_id")
    if not isinstance(action_id, str) or not isinstance(record_id, str):
        raise _error("FINAL_CHARACTER_CONTROLLER_ACTION_UNRESOLVED", "A Composite controller step lacks action or record identity.")
    canonical = by_id.get(action_id)
    if canonical is None or canonical.get("record_id") != record_id:
        raise _error("FINAL_CHARACTER_CONTROLLER_ACTION_UNRESOLVED", "A Composite controller action does not resolve to the canonical action surface.", details={"action_id": action_id, "record_id": record_id})
    try:
        artifact_packet = _action_packet(artifact_action)
    except FoundryError as exc:
        raise _error("FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE", "A Composite controller action packet is malformed.", details={"action_id": action_id}) from exc
    if artifact_packet != canonical:
        raise _error("FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE", "A Composite controller action packet diverges from canonical mechanics.", details={"action_id": action_id, "record_id": record_id})
    # A runtime controller may only expose the canonical resource namespace.
    _normalise_resource_rows(
        canonical.get("resource_costs"),
        field=f"action.{action_id}.resource_costs",
        active_resource_id=active_resource_id,
    )
    _normalise_resource_rows(
        canonical.get("resource_requirements"),
        field=f"action.{action_id}.resource_requirements",
        active_resource_id=active_resource_id,
    )
    return canonical


def _build_runtime_controller(root: Path, artifact: Mapping[str, Any], manifest: Mapping[str, Any], *, overlay_id: str, overlay_tree_sha256: str) -> dict[str, Any]:
    controller = artifact.get("composite_controller")
    if not isinstance(controller, Mapping):
        raise _error("FINAL_CHARACTER_CONTROLLER_INVALID", "The accepted Composite artifact has no controller policy.")
    source_root = Path(root)
    try:
        ledger = _read_json(
            source_root / "Build/Character_Master_Ledger.json",
            code="FINAL_CHARACTER_CONTROLLER_RESOURCE_AUTHORITY_INVALID",
        )
        if not isinstance(ledger, Mapping) or not isinstance(ledger.get("character"), Mapping):
            raise _error(
                "FINAL_CHARACTER_CONTROLLER_RESOURCE_AUTHORITY_INVALID",
                "The copied workspace has no typed active Path resource authority.",
            )
        active_resource = _active_resource_authority(source_root, ledger, ledger["character"])
    except FoundryError as exc:
        if exc.code == "FINAL_CHARACTER_CONTROLLER_RESOURCE_AUTHORITY_INVALID":
            raise
        raise _error(
            "FINAL_CHARACTER_CONTROLLER_RESOURCE_AUTHORITY_INVALID",
            "The copied workspace active Path resource authority could not be verified.",
            details={"cause": exc.code},
        ) from exc
    active_resource_id, active_resource_name = _runtime_resource_context(
        active_resource.get("resource_id"),
        active_resource.get("resource_name"),
    )
    active_current = active_resource.get("current")
    active_maximum = active_resource.get("maximum")
    if (
        type(active_current) is not int
        or type(active_maximum) is not int
        or active_current < 0
        or active_maximum < 1
        or active_current > active_maximum
    ):
        raise _error(
            "FINAL_CHARACTER_CONTROLLER_RESOURCE_AUTHORITY_INVALID",
            "The copied workspace active Path resource bounds are invalid.",
            details={"resource_id": active_resource_id, "current": active_current, "maximum": active_maximum},
        )
    artifact_resource = artifact.get("resource_authority")
    expected_artifact_resource = {
        "alias": COMPOSITE_CONTROLLER_RESOURCE_ALIAS,
        "resource_id": active_resource_id,
        "name": active_resource_name,
        "current": active_current,
        "maximum": active_maximum,
    }
    if (
        not isinstance(artifact_resource, Mapping)
        or artifact_resource.get("source_backed") is not True
        or any(artifact_resource.get(field) != expected for field, expected in expected_artifact_resource.items())
    ):
        raise _error(
            "FINAL_CHARACTER_CONTROLLER_RESOURCE_AUTHORITY_INVALID",
            "The Composite artifact resource authority does not match the copied workspace active Path resource.",
            details={"expected": expected_artifact_resource},
        )
    by_id, _packets = _canonical_action_index(root)
    linked_by_id: dict[str, Mapping[str, Any]] = {}
    linked = artifact.get("linked_actions")
    if not isinstance(linked, list):
        raise _error("FINAL_CHARACTER_CONTROLLER_INVALID", "The accepted Composite artifact has no linked action packets.")
    for row in linked:
        if not isinstance(row, Mapping):
            raise _error("FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE", "The accepted Composite artifact has a non-object linked action.")
        canonical = _resolve_artifact_action(
            row,
            by_id,
            active_resource_id=active_resource_id,
            active_resource_name=active_resource_name,
        )
        if canonical["action_id"] in linked_by_id:
            raise _error("FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE", "The accepted Composite artifact repeats a linked action identity.", details={"action_id": canonical["action_id"]})
        linked_by_id[canonical["action_id"]] = canonical

    sequence_total_cost = 0

    def resolve_step(step: Mapping[str, Any], *, fallback: bool = False) -> dict[str, Any]:
        nonlocal sequence_total_cost
        nested = step.get("action") if isinstance(step.get("action"), Mapping) else step
        canonical = _resolve_artifact_action(
            nested,
            by_id,
            active_resource_id=active_resource_id,
            active_resource_name=active_resource_name,
        )
        if canonical["action_id"] not in linked_by_id:
            raise _error("FINAL_CHARACTER_CONTROLLER_ACTION_UNRESOLVED", "A Composite sequence references an action absent from linked_actions.", details={"action_id": canonical["action_id"]})
        for identity in ("action_id", "record_id"):
            if identity in step and step.get(identity) != canonical[identity]:
                raise _error("FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE", "A Composite sequence identity diverges from its canonical action.", details={"action_id": canonical["action_id"], "field": identity})
        if "economy" in step and step.get("economy") != canonical["economy"]:
            raise _error(
                "FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE",
                "A Composite sequence economy diverges from its canonical action.",
                details={"action_id": canonical["action_id"], "expected": canonical["economy"], "actual": step.get("economy")},
            )
        economy = canonical["economy"]
        offset = step.get("round_offset", 0)
        if type(offset) is not int or offset < 0 or offset > 20:
            raise _error("FINAL_CHARACTER_CONTROLLER_SEQUENCE_INVALID", "A Composite sequence round offset is invalid.")
        metadata = _runtime_step_metadata(
            canonical,
            step,
            field=f"sequence.{canonical['action_id']}",
            active_resource_id=active_resource_id,
            active_resource_name=active_resource_name,
        )
        if not fallback:
            sequence_total_cost += _runtime_cost_total(
                metadata["resource_costs"],
                field=f"sequence.{canonical['action_id']}.resource_costs",
                maximum=active_maximum,
            )
        ref = _runtime_action_ref(
            canonical,
            economy=economy,
            round_offset=offset,
            costs=metadata["resource_costs"],
            requires_states=metadata["requires_states"],
            external_preconditions=metadata["external_preconditions"],
            advisory_external_preconditions=metadata.get("advisory_external_preconditions"),
            active_resource_id=active_resource_id,
            active_resource_name=active_resource_name,
        )
        if fallback:
            ref["fallback"] = True
        return ref

    sequence_value = controller.get("sequence")
    if not isinstance(sequence_value, list) or not sequence_value:
        raise _error("FINAL_CHARACTER_CONTROLLER_SEQUENCE_INVALID", "The accepted Composite controller has no sequence.")
    sequence = [resolve_step(step) for step in sequence_value if isinstance(step, Mapping)]
    if len(sequence) != len(sequence_value):
        raise _error("FINAL_CHARACTER_CONTROLLER_SEQUENCE_INVALID", "The accepted Composite sequence contains a non-object step.")
    fallback = controller.get("fallback")
    if not isinstance(fallback, Mapping):
        raise _error("FINAL_CHARACTER_CONTROLLER_FALLBACK_INVALID", "The accepted Composite controller has no fallback action.")
    fallback_ref = resolve_step(fallback, fallback=True)
    budget = controller.get("resource_budget")
    if not isinstance(budget, Mapping):
        raise _error("FINAL_CHARACTER_CONTROLLER_RESOURCE_INVALID", "The accepted Composite controller has no resource budget.")
    budget_resource = _canonical_resource_id(
        budget.get("resource_id"),
        active_resource_id=active_resource_id,
    )
    if (
        budget.get("alias") != COMPOSITE_CONTROLLER_RESOURCE_ALIAS
        or budget.get("resource_id") != active_resource_id
        or budget_resource != active_resource_id
    ):
        raise _error(
            "FINAL_CHARACTER_CONTROLLER_RESOURCE_AUTHORITY_INVALID",
            "The Composite controller budget is not bound to the copied workspace active Path resource.",
            details={"expected_resource_id": active_resource_id, "actual_resource_id": budget.get("resource_id")},
        )
    max_spend = budget.get("max_spend")
    declared_total = budget.get("total_sequence_cost")
    if (
        type(max_spend) is not int
        or max_spend < 0
        or max_spend > active_maximum
        or type(declared_total) is not int
        or declared_total < 0
        or declared_total != sequence_total_cost
        or declared_total > max_spend
        or declared_total > active_current
    ):
        raise _error(
            "FINAL_CHARACTER_CONTROLLER_RESOURCE_AUTHORITY_INVALID",
            "The Composite controller budget is outside the active Path resource authority.",
            details={
                "max_spend": max_spend,
                "total_sequence_cost": declared_total,
                "sequence_total_cost": sequence_total_cost,
                "current": active_current,
                "maximum": active_maximum,
            },
        )
    runtime_budget = deepcopy(dict(budget))
    runtime_budget["alias"] = COMPOSITE_CONTROLLER_RESOURCE_ALIAS
    runtime_budget["resource_id"] = active_resource_id
    canonical_bindings = [
        {"action_id": action["action_id"], "record_id": action["record_id"], "action_sha256": sha256_json(action)}
        for action in sorted(linked_by_id.values(), key=lambda value: (value["action_id"], value["record_id"]))
    ]
    runtime = {
        "schema_version": FINAL_CHARACTER_RUNTIME_CONTROLLER_SCHEMA,
        "controller_id": FINAL_CHARACTER_CONTROLLER_ID,
        "composite_id": controller.get("composite_id"),
        "name": controller.get("name"),
        "default": True,
        "execution_authority": True,
        "controller_policy_registered": True,
        "resource_authority": {
            "alias": COMPOSITE_CONTROLLER_RESOURCE_ALIAS,
            "resource_id": active_resource_id,
            "name": active_resource_name,
            "current": active_current,
            "maximum": active_maximum,
            "source_backed": True,
        },
        "resource_budget": runtime_budget,
        "sequence": sequence,
        "fallback": fallback_ref,
        "conditional_options": [],
        "when_to_use": deepcopy(controller.get("when_to_use")),
        "do_not_use_when": deepcopy(controller.get("do_not_use_when")),
        "temporal_feasibility": deepcopy(controller.get("temporal_feasibility")),
        "execution_role": deepcopy(controller.get("execution_role")),
        "dao_hook": deepcopy(controller.get("dao_hook")),
        "i_ching_hook": deepcopy(controller.get("i_ching_hook")),
        "canonical_action_bindings": canonical_bindings,
        "linked_actions": deepcopy(canonical_bindings),
        "overlay_lineage": {
            "overlay_id": overlay_id,
            "artifact_sha256": sha256_json(artifact),
            "overlay_tree_sha256": overlay_tree_sha256,
            "source_workspace_sha256": artifact.get("source_workspace_sha256"),
            "display_only_provenance_retained": True,
        },
    }
    conditional_options = controller.get("conditional_options", [])
    if not isinstance(conditional_options, list):
        raise _error("FINAL_CHARACTER_CONTROLLER_SEQUENCE_INVALID", "The accepted Composite conditional options are not a list.")
    for option in conditional_options:
        if not isinstance(option, Mapping):
            raise _error("FINAL_CHARACTER_CONTROLLER_SEQUENCE_INVALID", "A Composite conditional option is not an object.")
        nested = option.get("action") if isinstance(option.get("action"), Mapping) else option
        canonical = _resolve_artifact_action(
            nested,
            by_id,
            active_resource_id=active_resource_id,
            active_resource_name=active_resource_name,
        )
        if canonical["action_id"] not in linked_by_id:
            raise _error("FINAL_CHARACTER_CONTROLLER_ACTION_UNRESOLVED", "A Composite conditional option references an action absent from linked_actions.", details={"action_id": canonical["action_id"]})
        for identity in ("action_id", "record_id"):
            if identity in option and option.get(identity) != canonical[identity]:
                raise _error("FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE", "A Composite conditional option identity diverges from its canonical action.", details={"action_id": canonical["action_id"], "field": identity})
        if "economy" in option and option.get("economy") != canonical["economy"]:
            raise _error("FINAL_CHARACTER_CONTROLLER_ACTION_DIVERGENCE", "A Composite conditional option economy diverges from canonical mechanics.", details={"action_id": canonical["action_id"]})
        metadata = _runtime_step_metadata(
            canonical,
            option,
            field=f"option.{canonical['action_id']}",
            active_resource_id=active_resource_id,
            active_resource_name=active_resource_name,
        )
        offset = option.get("round_offset", 0)
        if type(offset) is not int or offset < 0 or offset > 20:
            raise _error("FINAL_CHARACTER_CONTROLLER_SEQUENCE_INVALID", "A Composite conditional option round offset is invalid.")
        conditional_runtime = {
            "action_id": canonical["action_id"],
            "record_id": canonical["record_id"],
            "economy": canonical["economy"],
            "round_offset": offset,
            "resource_costs": metadata["resource_costs"],
            "resource_requirements": metadata["resource_requirements"],
            "requires_states": metadata["requires_states"],
            "external_preconditions": metadata["external_preconditions"],
            "action_sha256": sha256_json(canonical),
        }
        if metadata.get("advisory_external_preconditions") is not None:
            conditional_runtime["advisory_external_preconditions"] = deepcopy(metadata["advisory_external_preconditions"])
        runtime["conditional_options"].append(conditional_runtime)
    return runtime


def _verify_immortal_action_projection(workspace: Path, translation: Mapping[str, Any]) -> dict[str, Any]:
    """Attest that the ledger and both surfaces carry the same tagged Art Actions."""

    root = Path(workspace)
    expected = {row["action_id"]: row for row in translation.get("actions", []) if isinstance(row, Mapping)}
    ledger = _read_json(root / "Build/Character_Master_Ledger.json", code="FINAL_CHARACTER_LEDGER_INVALID")
    ledger_actions = ledger.get("actions") if isinstance(ledger, Mapping) else None
    if not isinstance(ledger_actions, list):
        raise _error("FINAL_CHARACTER_ACTION_SURFACE_DIVERGENCE", "The translated ledger has no actions list.")
    surfaces = []
    for relative in ("Build/Complete_Action_Surface.json", "Command_4/Complete_Action_Surface.json"):
        document = _read_json(root / relative, code="FINAL_CHARACTER_ACTION_SURFACE_INVALID")
        actions = document.get("actions") if isinstance(document, Mapping) else None
        if not isinstance(actions, list):
            raise _error("FINAL_CHARACTER_ACTION_SURFACE_INVALID", "An action surface has no actions list.", details={"path": relative})
        surfaces.append(actions)
    if surfaces[0] != surfaces[1]:
        raise _error("FINAL_CHARACTER_ACTION_SURFACE_DIVERGENCE", "The Build and Command 4 action surfaces diverge after translation.")
    for action_id, action in expected.items():
        for label, rows in (("ledger", ledger_actions), ("surface", surfaces[0])):
            matches = [row for row in rows if isinstance(row, Mapping) and row.get("action_id") == action_id]
            if len(matches) != 1 or dict(matches[0]) != dict(action):
                raise _error("FINAL_CHARACTER_ACTION_SURFACE_DIVERGENCE", "A translated Immortal Art Action diverges.", details={"action_id": action_id, "where": label})
    return {
        "ledger_action_sha256": sha256_json([expected[action_id] for action_id in sorted(expected)]),
        "complete_action_surface_sha256": sha256_json(surfaces[0]),
        "command4_action_surface_sha256": sha256_json(surfaces[1]),
        "equal": True,
        "immortal_action_ids": sorted(expected),
    }


def _promote_materialized_command4_ledger(
    workspace: Path,
    *,
    runtime_controller: Mapping[str, Any],
    action_projection: Mapping[str, Any],
    immortal_translation: Mapping[str, Any],
) -> dict[str, Any]:
    """Record the narrow C2-to-C4 transition only after assembly is proven.

    The pinned compiler intentionally distinguishes an advancement ledger from
    an executable character with the ledger ``status`` field.  A materialized
    copy may make that transition, but only after this read-back gate proves
    that the translated Immortal Arts, both action surfaces, and the runtime
    Composite controller are the exact values produced by this invocation.
    No source workspace or detached evidence is touched here; the only write
    is the status field in the copied ledger.
    """

    root = Path(workspace)
    ledger_path = root / "Build/Character_Master_Ledger.json"
    if ledger_path.is_symlink() or not ledger_path.is_file():
        raise _error(
            "FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID",
            "The copied master ledger is missing or unsafe for the Command 4 transition.",
        )
    ledger = _read_json(ledger_path, code="FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID")
    if not isinstance(ledger, Mapping):
        raise _error(
            "FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID",
            "The copied master ledger is not a mapping.",
        )
    if ledger.get("schema_version") != "HF05ZVK-R1F":
        raise _error(
            "FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID",
            "The copied ledger schema is not the pinned HF05 production schema.",
            details={"schema_version": ledger.get("schema_version")},
        )
    if ledger.get("status") != "COMMAND_2_ADVANCEMENT_LEDGER_SEALED":
        raise _error(
            "FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID",
            "Command 4 promotion requires the exact sealed Command 2 ledger status.",
            details={"status": ledger.get("status")},
        )
    if ledger.get("build_mode") != "production":
        raise _error(
            "FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID",
            "Command 4 promotion is limited to a production ledger copy.",
            details={"build_mode": ledger.get("build_mode")},
        )

    character = ledger.get("character")
    character_cl = character.get("cl") if isinstance(character, Mapping) else None
    expected_realm = next(
        (realm for lower, upper, realm in _COMPILER_REALM_BANDS if type(character_cl) is int and lower <= character_cl <= upper),
        None,
    )
    if expected_realm is None or character.get("realm") != expected_realm:
        raise _error(
            "FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID",
            "Command 4 promotion requires the projected compiler realm for the character's CL.",
            details={"cl": character_cl, "realm": character.get("realm") if isinstance(character, Mapping) else None},
        )

    arts = ledger.get("immortal_arts")
    translated_arts = immortal_translation.get("arts") if isinstance(immortal_translation, Mapping) else None
    if not isinstance(arts, list) or arts != translated_arts:
        raise _error(
            "FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID",
            "The copied ledger Immortal Arts are not exactly the translated controller-built Arts.",
        )
    if character_cl >= 15 and not arts:
        raise _error(
            "FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID",
            "Command 4 promotion requires the character's CL15+ Immortal Art (RAW-182).",
        )
    expected_action_ids = sorted(action_id for art in arts for action_id in art.get("action_ids", []))
    if (
        not isinstance(action_projection, Mapping)
        or action_projection.get("equal") is not True
        or action_projection.get("immortal_action_ids") != expected_action_ids
        or immortal_translation.get("action_ids") != expected_action_ids
    ):
        raise _error(
            "FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID",
            "The Immortal Art action projection did not attest the translated Actions.",
        )
    ledger_actions = ledger.get("actions")
    if not isinstance(ledger_actions, list):
        raise _error("FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID", "The copied ledger has no actions list.")
    tagged = [row for row in ledger_actions if isinstance(row, Mapping) and row.get("classification") == IMMORTAL_ART_CLASSIFICATION]
    if sorted(row.get("action_id") for row in tagged) != expected_action_ids:
        raise _error(
            "FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID",
            "The copied ledger Immortal Art Actions are not exactly the translated Actions.",
        )
    surface_actions: list[list[Mapping[str, Any]]] = []
    for relative in ("Build/Complete_Action_Surface.json", "Command_4/Complete_Action_Surface.json"):
        surface_path = root / relative
        if surface_path.is_symlink() or not surface_path.is_file():
            raise _error(
                "FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID",
                "A complete action surface is missing or unsafe.",
                details={"path": relative},
            )
        surface = _read_json(surface_path, code="FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID")
        actions = surface.get("actions") if isinstance(surface, Mapping) else None
        if not isinstance(actions, list):
            raise _error(
                "FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID",
                "A complete action surface has no action list.",
                details={"path": relative},
            )
        surface_actions.append(actions)
    if surface_actions[0] != surface_actions[1]:
        raise _error(
            "FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID",
            "The Build and Command 4 action surfaces are not exactly equal.",
        )
    if (
        action_projection.get("complete_action_surface_sha256") != sha256_json(surface_actions[0])
        or action_projection.get("command4_action_surface_sha256") != sha256_json(surface_actions[1])
    ):
        raise _error(
            "FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID",
            "The action-surface projection hashes do not match the copied bytes.",
        )

    if not isinstance(runtime_controller, Mapping):
        raise _error(
            "FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID",
            "The runtime Composite controller is missing.",
        )
    if (
        runtime_controller.get("schema_version") != FINAL_CHARACTER_RUNTIME_CONTROLLER_SCHEMA
        or runtime_controller.get("controller_id") != FINAL_CHARACTER_CONTROLLER_ID
        or runtime_controller.get("execution_authority") is not True
        or runtime_controller.get("controller_policy_registered") is not True
        or not isinstance(runtime_controller.get("sequence"), list)
        or not runtime_controller.get("sequence")
        or not isinstance(runtime_controller.get("fallback"), Mapping)
        or not isinstance(runtime_controller.get("canonical_action_bindings"), list)
        or not runtime_controller.get("canonical_action_bindings")
        or runtime_controller.get("linked_actions") != runtime_controller.get("canonical_action_bindings")
    ):
        raise _error(
            "FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID",
            "The runtime Composite controller is incomplete or not execution-authoritative.",
        )
    runtime_resource = runtime_controller.get("resource_authority")
    runtime_budget = runtime_controller.get("resource_budget")
    if (
        not isinstance(runtime_resource, Mapping)
        or runtime_resource.get("source_backed") is not True
        or runtime_resource.get("alias") != COMPOSITE_CONTROLLER_RESOURCE_ALIAS
        or runtime_resource.get("resource_id") not in _RUNTIME_RESOURCE_KEYS
        or runtime_resource.get("name") != _RUNTIME_RESOURCE_NAMES.get(runtime_resource.get("resource_id"))
        or type(runtime_resource.get("current")) is not int
        or type(runtime_resource.get("maximum")) is not int
        or runtime_resource.get("current") < 0
        or runtime_resource.get("maximum") < 1
        or runtime_resource.get("current") > runtime_resource.get("maximum")
        or not isinstance(runtime_budget, Mapping)
        or runtime_budget.get("alias") != COMPOSITE_CONTROLLER_RESOURCE_ALIAS
        or runtime_budget.get("resource_id") != runtime_resource.get("resource_id")
        or type(runtime_budget.get("max_spend")) is not int
        or runtime_budget.get("max_spend") < 0
        or runtime_budget.get("max_spend") > runtime_resource.get("maximum")
        or type(runtime_budget.get("total_sequence_cost")) is not int
        or runtime_budget.get("total_sequence_cost") < 0
        or runtime_budget.get("total_sequence_cost") > runtime_budget.get("max_spend")
    ):
        raise _error(
            "FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID",
            "The runtime Composite controller has incomplete active-resource authority.",
        )
    runtime_lineage = runtime_controller.get("overlay_lineage")
    if (
        not isinstance(runtime_lineage, Mapping)
        or not isinstance(runtime_lineage.get("overlay_id"), str)
        or not runtime_lineage.get("overlay_id")
        or len(runtime_lineage["overlay_id"]) > 256
        or any(marker in runtime_lineage["overlay_id"] for marker in ("\x00", "\n", "\r", "/", "\\"))
        or not _is_hash(runtime_lineage.get("artifact_sha256"))
        or not _is_hash(runtime_lineage.get("overlay_tree_sha256"))
        or not _is_hash(runtime_lineage.get("source_workspace_sha256"))
        or runtime_lineage.get("display_only_provenance_retained") is not True
    ):
        raise _error(
            "FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID",
            "The runtime Composite controller overlay lineage is incomplete or unsafe.",
        )
    runtime_lineage_artifact_sha256 = runtime_lineage["artifact_sha256"]
    for relative in ("Command_4/Composite_Controller.json", "Build/Composite_Controller.json"):
        controller_path = root / relative
        if controller_path.is_symlink() or not controller_path.is_file():
            raise _error(
                "FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID",
                "A runtime Composite controller file is missing or unsafe.",
                details={"path": relative},
            )
        if _read_json(controller_path, code="FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID") != dict(runtime_controller):
            raise _error(
                "FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID",
                "A runtime Composite controller file diverges from the server-owned projection.",
                details={"path": relative},
            )
    validation_path = root / "Validation/Composite_Controller.validation.json"
    if validation_path.is_symlink() or not validation_path.is_file():
        raise _error(
            "FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID",
            "The Composite controller validation receipt is missing or unsafe.",
        )
    validation = _read_json(validation_path, code="FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID")
    if (
        not isinstance(validation, Mapping)
        or validation.get("schema_version") != "TianxiaFoundry.CompositeControllerValidation.v1"
        or validation.get("valid") is not True
        or validation.get("execution_authority") is not True
        or validation.get("controller_policy_registered") is not True
        or validation.get("artifact_sha256") != runtime_lineage_artifact_sha256
    ):
        raise _error(
            "FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID",
            "The Composite controller validation receipt is incomplete, not authoritative, or not bound to runtime lineage.",
        )

    promoted = deepcopy(dict(ledger))
    promoted["status"] = "COMMAND_4_EXECUTABLE_CHARACTER_COMPLETE"
    _write_json(ledger_path, promoted)
    reread = _read_json(ledger_path, code="FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID")
    if reread != promoted:
        raise _error(
            "FINAL_CHARACTER_COMMAND4_PROMOTION_INVALID",
            "The copied ledger status transition could not be read back exactly.",
        )
    return {
        "schema_version": "HF05ZVK-R1F",
        "previous_status": "COMMAND_2_ADVANCEMENT_LEDGER_SEALED",
        "status": "COMMAND_4_EXECUTABLE_CHARACTER_COMPLETE",
        "build_mode": "production",
        "immortal_action_ids": expected_action_ids,
        "immortal_art_ids": [art.get("immortal_art_id") for art in arts],
        "immortal_acquired_at_cls": [art.get("gained_at_cl") for art in arts],
        "action_surface_equal": True,
        "runtime_controller_id": FINAL_CHARACTER_CONTROLLER_ID,
        "validated": True,
    }


def _recompute_checkpoints(workspace: Path, compiler_module: Any) -> int:
    ledger_path = workspace / "Build/Character_Master_Ledger.json"
    ledger = _read_json(ledger_path, code="FINAL_CHARACTER_LEDGER_INVALID")
    if not isinstance(ledger, Mapping) or not isinstance(ledger.get("advancement"), Mapping) or not isinstance(ledger["advancement"].get("levels"), list):
        raise _error("FINAL_CHARACTER_CHECKPOINT_PRECONDITION", "The master ledger has no advancement level list.")
    levels = deepcopy(ledger["advancement"]["levels"])
    hashes: list[str] = []
    try:
        for index, row in enumerate(levels, start=1):
            if not isinstance(row, dict):
                raise ValueError(f"level {index} is not an object")
            value = compiler_module.checkpoint_hash(levels, index)
            if not _is_hash(value):
                raise ValueError(f"invalid checkpoint hash at {index}")
            row["state_after_hash"] = value
            hashes.append(value)
        for index, row in enumerate(levels, start=1):
            if row.get("state_after_hash") != compiler_module.checkpoint_hash(levels, index):
                raise ValueError(f"checkpoint mismatch at {index}")
    except Exception as exc:
        raise _error("FINAL_CHARACTER_CHECKPOINT_RECOMPUTE_FAILED", "The pinned compiler checkpoint_hash semantics could not be applied exactly.", details={"error": str(exc)}) from exc
    ledger_value = deepcopy(dict(ledger))
    advancement = deepcopy(dict(ledger_value["advancement"]))
    advancement["levels"] = levels
    ledger_value["advancement"] = advancement
    _write_json(ledger_path, ledger_value)
    canonical_path = workspace / "Command_2/Canonical_Advancement_Ledger.json"
    if canonical_path.is_file() and not canonical_path.is_symlink():
        canonical = _read_json(canonical_path, code="FINAL_CHARACTER_CHECKPOINT_PRECONDITION")
        if isinstance(canonical, Mapping) and isinstance(canonical.get("levels"), list) and len(canonical["levels"]) == len(levels):
            canonical_value = deepcopy(dict(canonical))
            canonical_value["levels"] = deepcopy(levels)
            _write_json(canonical_path, canonical_value)
    return len(hashes)


def _recompute_workspace_receipts(workspace: Path) -> None:
    build = workspace / "Build"
    if not build.is_dir() or build.is_symlink():
        raise _error("FINAL_CHARACTER_BUILD_INVALID", "The materialized workspace has no regular Build directory.")
    package_path = build / "PACKAGE_MANIFEST.json"
    if package_path.is_file() and not package_path.is_symlink():
        package = _read_json(package_path, code="FINAL_CHARACTER_MANIFEST_INVALID")
        if not isinstance(package, Mapping):
            raise _error("FINAL_CHARACTER_MANIFEST_INVALID", "The Build package manifest is not an object.")
        package_value = deepcopy(dict(package))
        files = []
        for path in sorted(build.rglob("*")):
            if not path.is_file() or path.is_symlink() or path.name in {"PACKAGE_MANIFEST.json", "SHA256SUMS.txt"}:
                continue
            files.append({"path": path.relative_to(build).as_posix(), "sha256": sha256_file(path), "bytes": path.stat().st_size})
        package_value["files"] = files
        _write_json(package_path, package_value)
    build_files = {
        path.relative_to(build).as_posix(): sha256_file(path)
        for path in sorted(build.rglob("*"))
        if path.is_file() and not path.is_symlink() and path.name != "SHA256SUMS.txt"
    }
    _atomic_write_bytes(
        build / "SHA256SUMS.txt",
        ("\n".join(f"{digest}  {name}" for name, digest in sorted(build_files.items())) + "\n").encode("utf-8"),
    )
    root_files = {
        path.relative_to(workspace).as_posix(): sha256_file(path)
        for path in sorted(workspace.rglob("*"))
        if path.is_file() and not path.is_symlink() and path.name != "SHA256SUMS.txt" and not path.relative_to(workspace).as_posix().startswith("Build/")
    }
    _atomic_write_bytes(
        workspace / "SHA256SUMS.txt",
        ("\n".join(f"{digest}  {name}" for name, digest in sorted(root_files.items())) + "\n").encode("utf-8"),
    )
    try:
        _verify_workspace_checksums(workspace)
    except FoundryError as exc:
        raise _error("FINAL_CHARACTER_CHECKSUM_RECOMPUTE_FAILED", "The materialized workspace checksum ledgers do not verify.", details={"cause": exc.code, "message": exc.message}) from exc


def _manual_lineage_bounded_choice_details() -> dict[str, Any]:
    return {
        "schema_version": _MANUAL_LINEAGE_BOUNDED_CHOICE_SCHEMA,
        "slot_id": _MANUAL_LINEAGE_BOUNDED_CHOICE_SLOT_ID,
        "current_commitments": {
            "typed_none": deepcopy(_MANUAL_LINEAGE_NONE_STATE),
            "recorded_arts": deepcopy(_MANUAL_LINEAGE_NONE_STATE),
            "packet": deepcopy(_MANUAL_LINEAGE_NONE_PACKET_COMMITMENT),
            "source": deepcopy(_MANUAL_LINEAGE_NONE_SOURCE),
        },
        "requirement": "one source-backed training source",
        "resolution_routes": deepcopy(list(_MANUAL_LINEAGE_BOUNDED_CHOICE_ROUTES)),
    }


def _validate_manual_lineage_source_present(
    *,
    raw_ledger: Mapping[str, Any],
    ledger: Mapping[str, Any],
    manual_lineage: Mapping[str, Any],
    manuals: Mapping[str, Any],
    packet_registry: Mapping[str, Any],
    compiler_packet_registry: Mapping[str, Any],
    training_values: list[tuple[str, Any]],
) -> dict[str, Any]:
    """Validate the access-only v3 training-source projection.

    A non-empty ``training_sources`` list is compiler authority, not merely a
    display hint.  Keep this validation read-only and bind each row to its
    preserved modern Stage-2 access packet before allowing the compiler to run.
    """

    def invalid(message: str, *, details: Any = None) -> NoReturn:
        raise _error("FINAL_CHARACTER_MANUAL_LINEAGE_GATE_INVALID", message, details=details)

    source_by_surface = {label: rows for label, rows in training_values}
    if set(source_by_surface) != {"raw", "current"}:
        invalid(
            "A source-present candidate must carry the same training-source list in raw and current ledgers.",
            details={"surfaces": sorted(source_by_surface)},
        )
    raw_training = source_by_surface["raw"]
    current_training = source_by_surface["current"]
    if not isinstance(raw_training, list) or not isinstance(current_training, list) or not raw_training or raw_training != current_training:
        invalid("The raw and current training-source projections diverge or are empty.")

    for label, value in (("raw", raw_ledger), ("current", ledger)):
        typed_none = value.get("typed_none", _MISSING)
        if typed_none is not _MISSING and (not isinstance(typed_none, Mapping) or "manuals" in typed_none):
            invalid("A source-present ledger retains an invalid manuals typed-none field.", details={"surface": label})
        if value.get("recorded_arts") != []:
            invalid("A source-present ledger must expose recorded_arts as an empty list.", details={"surface": label})

    def clean_text(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value or value != value.strip() or any(ord(char) < 32 for char in value):
            invalid("A source-present compiler field is not a clean string.", details={"field": field, "value": value})
        return value

    def clean_source_text(value: Any, field: str) -> str:
        # Canonical corpus excerpts may contain line breaks.  Preserve that
        # source text exactly while rejecting ambiguity/control characters and
        # binding the compiler-facing digest to the bytes being consumed.
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or any(ord(char) < 32 and char not in "\n\r\t" for char in value)
        ):
            invalid("A compiler source excerpt is not clean source text.", details={"field": field, "value": value})
        return value

    def clean_list(value: Any, field: str) -> list[str]:
        if not isinstance(value, list) or any(
            not isinstance(item, str)
            or not item
            or item != item.strip()
            or any(ord(char) < 32 for char in item)
            for item in value
        ) or len(value) != len(set(value)):
            invalid("A source-present compiler list is malformed.", details={"field": field, "value": value})
        return list(value)

    source_fields = frozenset({
        "source_id", "allocation_id", "name", "type", "gained_at_cl",
        "contents", "restrictions", "risks", "mechanics_granted",
        "source_packet_ids", "record_hash",
    })
    contents_fields = frozenset({"recorded_arts", "methods", "warnings", "recipes", "theory", "false_routes"})
    source_types = frozenset({"other", "sect_lineage", "item_source", "spirit_relation", "manual"})
    source_rows: list[Mapping[str, Any]] = []
    source_ids: list[str] = []
    for index, row in enumerate(raw_training):
        if not isinstance(row, Mapping) or set(row) != source_fields:
            invalid("A training-source row is not the exact v3 compiler projection shape.", details={"index": index})
        source_id = clean_text(row.get("source_id"), f"training_sources[{index}].source_id")
        if source_id in source_ids:
            invalid("The source-present projection repeats a source identity.", details={"source_id": source_id})
        source_ids.append(source_id)
        clean_text(row.get("allocation_id"), f"training_sources[{index}].allocation_id")
        clean_text(row.get("name"), f"training_sources[{index}].name")
        if row.get("type") not in source_types:
            invalid("A training-source row uses an unsupported compiler source type.", details={"source_id": source_id, "type": row.get("type")})
        gained_at_cl = row.get("gained_at_cl")
        if not isinstance(gained_at_cl, int) or isinstance(gained_at_cl, bool) or gained_at_cl < 1:
            invalid("A training-source row has an invalid gained_at_cl.", details={"source_id": source_id, "gained_at_cl": gained_at_cl})
        contents = row.get("contents")
        if not isinstance(contents, Mapping) or set(contents) != contents_fields:
            invalid("A training-source contents object is not the exact compiler shape.", details={"source_id": source_id})
        for field in sorted(contents_fields):
            values = clean_list(contents.get(field), f"training_sources[{index}].contents.{field}")
            if values != []:
                invalid("An access-only training-source row cannot fabricate compiler content.", details={"source_id": source_id, "field": field})
        for field in ("restrictions", "risks", "mechanics_granted"):
            values = clean_list(row.get(field), f"training_sources[{index}].{field}")
            if values != []:
                invalid("An access-only training-source row cannot fabricate compiler capabilities.", details={"source_id": source_id, "field": field})
        packet_ids = clean_list(row.get("source_packet_ids"), f"training_sources[{index}].source_packet_ids")
        if len(packet_ids) != 1:
            invalid("A training-source row must bind exactly one packet.", details={"source_id": source_id, "packet_ids": packet_ids})
        if not _is_hash(row.get("record_hash")):
            invalid("A training-source row has an invalid lowercase SHA-256 record hash.", details={"source_id": source_id})
        source_rows.append(row)

    packet_rows = packet_registry.get("packets")
    if not isinstance(packet_rows, list):
        invalid("The preserved modern packet registry has no packet list.")
    packet_by_id: dict[str, Mapping[str, Any]] = {}
    for index, packet in enumerate(packet_rows):
        if not isinstance(packet, Mapping):
            invalid("The preserved modern packet registry contains a non-object row.", details={"index": index})
        packet_id = packet.get("packet_id")
        if not isinstance(packet_id, str) or not packet_id or packet_id != packet_id.strip() or packet_id in packet_by_id:
            invalid("The preserved modern packet registry has an invalid or duplicate packet ID.", details={"index": index, "packet_id": packet_id})
        packet_by_id[packet_id] = packet

    compiler_packet_rows = compiler_packet_registry.get("packets")
    if not isinstance(compiler_packet_rows, list):
        invalid("The compiler-facing packet registry has no packet list.")
    compiler_packets_by_id: dict[str, Mapping[str, Any]] = {}
    for index, packet in enumerate(compiler_packet_rows):
        if not isinstance(packet, Mapping):
            invalid("The compiler-facing packet registry contains a non-object row.", details={"index": index})
        packet_id = packet.get("packet_id")
        if not isinstance(packet_id, str) or not packet_id or packet_id != packet_id.strip() or packet_id in compiler_packets_by_id:
            invalid("The compiler-facing packet registry has an invalid or duplicate packet ID.", details={"index": index, "packet_id": packet_id})
        compiler_packets_by_id[packet_id] = packet

    source_bindings: list[dict[str, Any]] = []
    used_packet_ids: set[str] = set()
    pinned_corpus_loaded = False
    pinned_corpus_active: set[str] = set()
    pinned_corpus_texts: dict[str, str] = {}
    required_packet_fields = frozenset({
        "packet_id", "event_id", "event_hash", "sequence", "target_cl", "advancement_kind",
        "record_id", "record_hash", "display_name", "short_description", "full_description",
        "stage2_rule_id", "source_evidence", "content_binding",
    })
    for row in source_rows:
        source_id = row["source_id"]
        packet_id = row["source_packet_ids"][0]
        if packet_id in used_packet_ids or packet_id not in packet_by_id:
            invalid("A training-source row does not resolve one unique preserved modern packet.", details={"source_id": source_id, "packet_id": packet_id})
        used_packet_ids.add(packet_id)
        packet = packet_by_id[packet_id]
        if set(packet) != required_packet_fields:
            invalid("The preserved modern source packet is partial.", details={"packet_id": packet_id})
        compiler_packet = compiler_packets_by_id.get(packet_id)
        if compiler_packet is None:
            invalid("The compiler-facing packet registry omits an authenticated source packet.", details={"packet_id": packet_id})
        if set(compiler_packet) == required_packet_fields:
            invalid(
                "The compiler-facing registry contains an unbridged modern source packet.",
                details={"packet_id": packet_id},
            )
        else:
            native_packet_fields = frozenset({
                "packet_id", "name", "authority", "source_path", "source_text", "source_text_sha256",
                "source_section", "source_classification", "modern_record_id", "modern_source_path",
                "modern_source_sha256", "source_evidence_verified",
            })
            if set(compiler_packet) != native_packet_fields:
                invalid("The compiler-facing source packet has an unknown or partial native shape.", details={"packet_id": packet_id})
            evidence = packet.get("source_evidence")
            if not isinstance(evidence, list) or len(evidence) != 1 or not isinstance(evidence[0], Mapping):
                invalid("A source packet has no independently verifiable source evidence.", details={"packet_id": packet_id})
            evidence_row = evidence[0]
            if not pinned_corpus_loaded:
                try:
                    _assert_trusted_file(
                        FINAL_CHARACTER_DEFAULT_CORPUS,
                        FINAL_CHARACTER_DEFAULT_CORPUS,
                        FINAL_CHARACTER_CORPUS_SHA256,
                        label="rules corpus",
                    )
                    pinned_corpus_active, pinned_corpus_texts = _corpus_active_texts(FINAL_CHARACTER_DEFAULT_CORPUS)
                except FoundryError as exc:
                    invalid("The pinned corpus authority could not be loaded for source-packet verification.", details={"cause": exc.code})
                pinned_corpus_loaded = True
            source_hash = evidence_row.get("source_hash")
            corpus_matches = [
                path
                for path, text in pinned_corpus_texts.items()
                if _sha256_text(text) == source_hash
            ]
            expected_source_path = corpus_matches[0] if len(corpus_matches) == 1 else None
            expected_source_text = (
                _source_excerpt(pinned_corpus_texts[expected_source_path], packet)
                if expected_source_path is not None
                else None
            )
            if (
                compiler_packet.get("packet_id") != packet_id
                or compiler_packet.get("authority") != "tianxia_rules"
                or compiler_packet.get("name") != packet.get("display_name")
                or compiler_packet.get("source_path") != expected_source_path
                or compiler_packet.get("source_text") != expected_source_text
                or compiler_packet.get("modern_record_id") != packet.get("record_id")
                or compiler_packet.get("modern_source_path") != evidence_row.get("source_path")
                or compiler_packet.get("modern_source_sha256") != source_hash
                or compiler_packet.get("source_section") != evidence_row.get("source_anchor")
                or compiler_packet.get("source_classification") != packet.get("advancement_kind")
                or compiler_packet.get("source_evidence_verified") is not True
                or not _is_hash(compiler_packet.get("source_text_sha256"))
                or not isinstance(compiler_packet.get("source_text"), str)
                or not compiler_packet["source_text"].strip()
                or _sha256_text(compiler_packet["source_text"]) != compiler_packet.get("source_text_sha256")
            ):
                invalid("The compiler-facing native source packet is not bound to preserved provenance.", details={"packet_id": packet_id})
            clean_text(compiler_packet.get("name"), f"packets[{packet_id}].name")
            clean_text(compiler_packet.get("source_path"), f"packets[{packet_id}].source_path")
            clean_text(compiler_packet.get("source_section"), f"packets[{packet_id}].source_section")
            clean_source_text(compiler_packet.get("source_text"), f"packets[{packet_id}].source_text")
        event_id = clean_text(packet.get("event_id"), f"packets[{packet_id}].event_id")
        event_hash = packet.get("event_hash")
        sequence = packet.get("sequence")
        if (
            not _is_hash(event_hash)
            or not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence < 1
            or packet_id != f"packet.stage2.{sequence:03d}.{event_hash[:16]}"
            or packet.get("advancement_kind") != "training_source_access"
            or packet.get("record_id") != source_id
            or packet.get("display_name") != row.get("name")
            or packet.get("target_cl") != row.get("gained_at_cl")
            or packet.get("record_hash") != row.get("record_hash")
            or row.get("allocation_id") != f"training_source_access:{event_id}"
        ):
            invalid("A source packet does not match its projected training-source row.", details={"packet_id": packet_id, "source_id": source_id})
        clean_text(packet.get("short_description"), f"packets[{packet_id}].short_description")
        clean_text(packet.get("full_description"), f"packets[{packet_id}].full_description")
        clean_text(packet.get("stage2_rule_id"), f"packets[{packet_id}].stage2_rule_id")
        evidence = packet.get("source_evidence")
        if not isinstance(evidence, list) or len(evidence) != 1 or not isinstance(evidence[0], Mapping) or set(evidence[0]) != {"source_id", "source_hash", "source_anchor", "source_path"}:
            invalid("A source packet has incomplete source evidence.", details={"packet_id": packet_id})
        evidence_row = evidence[0]
        clean_text(evidence_row.get("source_id"), f"packets[{packet_id}].source_evidence.source_id")
        if not _is_hash(evidence_row.get("source_hash")):
            invalid("A source packet has an invalid source evidence hash.", details={"packet_id": packet_id})
        clean_text(evidence_row.get("source_anchor"), f"packets[{packet_id}].source_evidence.source_anchor")
        clean_text(evidence_row.get("source_path"), f"packets[{packet_id}].source_evidence.source_path")
        binding = packet.get("content_binding")
        if (
            not isinstance(binding, Mapping)
            or set(binding) != {"pack_id", "pack_version", "pack_hash", "record_hash", "catalog_build_id"}
            or binding.get("record_hash") != row.get("record_hash")
            or not _is_hash(binding.get("pack_hash"))
            or not _is_hash(binding.get("catalog_build_id"))
        ):
            invalid("A source packet has an invalid content binding.", details={"packet_id": packet_id})
        clean_text(binding.get("pack_id"), f"packets[{packet_id}].content_binding.pack_id")
        clean_text(binding.get("pack_version"), f"packets[{packet_id}].content_binding.pack_version")
        source_bindings.append({
            "source_id": source_id,
            "allocation_id": row["allocation_id"],
            "packet_id": packet_id,
            "event_id": event_id,
            "event_hash": event_hash,
            "sequence": sequence,
            "target_cl": row["gained_at_cl"],
            "record_hash": row["record_hash"],
            "stage2_rule_id": packet["stage2_rule_id"],
        })

    manual_none_packets = [
        packet
        for packet in packet_rows
        if isinstance(packet, Mapping)
        and (
            packet.get("record_id") == _MANUAL_LINEAGE_NONE_RECORD_ID
            or packet.get("stage2_rule_id") == "c1a.none.manuals.v1"
            or packet.get("display_name") == _MANUAL_LINEAGE_NONE_PACKET_COMMITMENT["display_name"]
        )
    ]
    if len(manual_none_packets) > 1:
        invalid("The preserved packet registry repeats the sealed manuals typed-none packet.")
    if manual_none_packets:
        manual_none = manual_none_packets[0]
        if set(manual_none) != set(_MANUAL_LINEAGE_NONE_PACKET_COMMITMENT) or any(manual_none.get(field) != expected for field, expected in _MANUAL_LINEAGE_NONE_PACKET_COMMITMENT.items()):
            invalid("The preserved manuals typed-none packet is alternate or forged.")
        if any(manual_none["sequence"] >= binding["sequence"] for binding in source_bindings):
            invalid("A manuals typed-none packet occurs after a training-source access packet.")

    if (
        set(manuals) not in (
            {"schema_version", "manuals"},
            {"schema_version", "manuals", "recorded_arts"},
        )
        or manuals.get("schema_version") != "TianxiaFoundry.CharacterGMManuals.v1"
        or manuals.get("manuals") != []
        or ("recorded_arts" in manuals and manuals.get("recorded_arts") != [])
    ):
        invalid("The Martial Arts and Manuals mirror retains executable or typed-none state.")

    mirror_training = manual_lineage.get("training_sources")
    if (
        set(manual_lineage) != {"schema_version", "training_sources"}
        or
        manual_lineage.get("schema_version") != "TianxiaFoundry.CharacterGMTrainingSources.v1"
        or not isinstance(mirror_training, list)
        or len(mirror_training) != len(source_rows)
    ):
        invalid("The Manual Lineage mirror has no valid display-only training-source rows.")
    mirror_fields = frozenset({
        "source_id", "allocation_id", "name", "type", "classification", "source_category", "contents",
        "authority", "factory_source_type", "gained_at_cl", "mechanics_granted", "record_ids",
        "restrictions", "risks", "source", "source_packet_ids", "summary",
    })
    mirror_content_fields = frozenset({"recorded_arts", "methods", "warnings", "recipes", "theory", "false_routes", "record_bindings"})
    for index, row in enumerate(mirror_training):
        expected_source = source_rows[index]
        if not isinstance(row, Mapping) or set(row) != mirror_fields:
            invalid("The Manual Lineage mirror contains a non-object training row.", details={"index": index})
        contents = row.get("contents")
        if (
            row.get("classification") != "GM_GUIDANCE_ONLY"
            or row.get("source_category") != "PROJECT_SELECTED_RECORD_TRAINING"
            or row.get("type") != "other"
            or not isinstance(contents, Mapping)
            or set(contents) != mirror_content_fields
            or contents.get("recorded_arts") != []
            or any(contents.get(field) != [] for field in set(contents) - {"recorded_arts"})
            or row.get("source_id") != expected_source.get("source_id")
            or row.get("allocation_id") != expected_source.get("allocation_id")
            or row.get("name") != expected_source.get("name")
            or row.get("gained_at_cl") != expected_source.get("gained_at_cl")
            or row.get("record_ids") != [expected_source.get("source_id")]
            or row.get("source_packet_ids") != expected_source.get("source_packet_ids")
            or row.get("execution_authority") is True
            or row.get("mechanical_projection") is True
            or row.get("display_only_not_execution_authority") is False
        ):
            invalid("The Manual Lineage mirror contains a purported executable training source.", details={"index": index})
        if clean_list(row["record_ids"], f"manual_lineage.training_sources[{index}].record_ids") != [expected_source["source_id"]]:
            invalid("The Manual Lineage mirror record identity diverges from its source row.", details={"index": index})
        for field in ("mechanics_granted", "restrictions", "risks"):
            if clean_list(row[field], f"manual_lineage.training_sources[{index}].{field}") != []:
                invalid("The Manual Lineage mirror contains executable capability claims.", details={"index": index, "field": field})
        if row["factory_source_type"] != "other":
            invalid("The Manual Lineage mirror has an executable source type.", details={"index": index})
        authority = row["authority"]
        if (
            not isinstance(authority, Mapping)
            or set(authority) != {"classification", "profile_id", "profile_sha256"}
            or authority.get("classification") != "GM_GUIDANCE_ONLY"
            or not isinstance(authority.get("profile_id"), str)
            or not authority["profile_id"].strip()
            or not _is_hash(authority.get("profile_sha256"))
        ):
            invalid("The Manual Lineage mirror authority binding is malformed.", details={"index": index})
        clean_text(row["source"], f"manual_lineage.training_sources[{index}].source")
        clean_text(row["summary"], f"manual_lineage.training_sources[{index}].summary")

    return {
        "schema_version": _MANUAL_LINEAGE_BOUNDED_CHOICE_SCHEMA,
        "slot_id": _MANUAL_LINEAGE_BOUNDED_CHOICE_SLOT_ID,
        "status": "source_present",
        "source_ids": [binding["source_id"] for binding in source_bindings],
        "packet_ids": [binding["packet_id"] for binding in source_bindings],
        "source_bindings": source_bindings,
    }


def _require_manual_lineage_source_or_bounded_choice(workspace: Path) -> dict[str, Any]:
    """Require a lawful manual lineage or expose the sealed typed-none choice.

    The accepted C1A candidate explicitly chose no manuals.  That state is
    valid source provenance but cannot satisfy the pinned compiler's required
    ``training_sources`` field.  This boundary therefore emits a deterministic
    choice request without inventing a teacher, manual, or acquisition.
    """

    def invalid(message: str, *, details: Any = None) -> FoundryError:
        return _error("FINAL_CHARACTER_MANUAL_LINEAGE_GATE_INVALID", message, details=details)

    root = Path(workspace)
    compiler_packets_path = root / "Command_2/Rules_Selection_Packets.json"
    modern_packets_path = root / "Command_2/Rules_Selection_Packets.Modern_Provenance.json"
    paths = {
        "ledger": root / "Build/Character_Master_Ledger.json",
        "raw_provenance": root / _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "manual_lineage": root / "Build/Manual_Lineage_Record.json",
        "manuals": root / "Build/Martial_Arts_and_Manuals.json",
        "packets": compiler_packets_path,
    }
    for label, path in paths.items():
        if path.is_symlink() or not path.is_file():
            raise invalid("The manual-lineage gate inputs are missing or unsafe.", details={"label": label, "path": str(path)})
    modern_packets_present = modern_packets_path.exists() or modern_packets_path.is_symlink()
    if modern_packets_present and (modern_packets_path.is_symlink() or not modern_packets_path.is_file()):
        raise invalid("The preserved modern packet provenance is missing or unsafe.", details={"path": str(modern_packets_path)})
    try:
        values = {
            label: _read_json(path, code="FINAL_CHARACTER_MANUAL_LINEAGE_GATE_INVALID")
            for label, path in paths.items()
        }
        if modern_packets_present:
            values["modern_packets"] = _read_json(modern_packets_path, code="FINAL_CHARACTER_MANUAL_LINEAGE_GATE_INVALID")
    except FoundryError as exc:
        raise invalid("The manual-lineage gate inputs could not be read.", details={"cause": exc.code}) from exc

    ledger = values["ledger"]
    raw_ledger = values["raw_provenance"]
    manual_lineage = values["manual_lineage"]
    manuals = values["manuals"]
    compiler_packet_registry = values["packets"]
    packet_registry = values.get("modern_packets", compiler_packet_registry)
    if not isinstance(ledger, Mapping) or not isinstance(raw_ledger, Mapping):
        raise invalid("The manual-lineage master and raw ledgers must be mappings.")
    if not isinstance(manual_lineage, Mapping) or not isinstance(manuals, Mapping):
        raise invalid("The manual-lineage mirrors and packet registry must be mappings.")
    if not isinstance(compiler_packet_registry, Mapping) or not isinstance(compiler_packet_registry.get("packets"), list):
        raise invalid("The compiler-facing packet registry is missing or malformed.")
    if not isinstance(packet_registry, Mapping):
        raise invalid("The preserved modern packet registry is missing or malformed.")

    expected_none = _MANUAL_LINEAGE_NONE_STATE
    training_values: list[tuple[str, Any]] = []
    for label, value in (("raw", raw_ledger), ("current", ledger)):
        if "training_sources" in value:
            training = value["training_sources"]
            if not isinstance(training, list):
                raise invalid("The manual-lineage training source field is not a list.", details={"surface": label})
            training_values.append((label, training))
    contradictory_none = [
        label
        for label, value in (("raw", raw_ledger), ("current", ledger))
        if (
            isinstance(value.get("typed_none"), Mapping)
            and value["typed_none"].get("manuals") == expected_none
        )
        or value.get("recorded_arts") == expected_none
    ]
    contradictory = [(label, rows) for label, rows in training_values if rows]
    if contradictory:
        return _validate_manual_lineage_source_present(
            raw_ledger=raw_ledger,
            ledger=ledger,
            manual_lineage=manual_lineage,
            manuals=manuals,
            packet_registry=packet_registry,
            compiler_packet_registry=compiler_packet_registry,
            training_values=training_values,
        )

    for label, value in (("raw", raw_ledger), ("current", ledger)):
        typed_none = value.get("typed_none")
        if not isinstance(typed_none, Mapping) or typed_none.get("manuals") != expected_none:
            raise invalid(
                "The sealed typed-none manuals commitment is missing, null, partial, or forged.",
                details={"surface": label, "field": "typed_none.manuals"},
            )
        if value.get("recorded_arts") != expected_none:
            raise invalid(
                "The sealed recorded-arts none commitment is missing, null, partial, or forged.",
                details={"surface": label, "field": "recorded_arts"},
            )
    if ledger.get("typed_none", {}).get("manuals") != raw_ledger.get("typed_none", {}).get("manuals") or ledger.get("recorded_arts") != raw_ledger.get("recorded_arts"):
        raise invalid("The current and raw manual-lineage none commitments diverge.")

    if manuals.get("schema_version") != "TianxiaFoundry.CharacterGMManuals.v1" or manuals.get("manuals") != [] or manuals.get("none_state") != expected_none:
        raise invalid("The Martial Arts and Manuals mirror does not preserve the exact sealed none state.")
    if "recorded_arts" in manuals and manuals.get("recorded_arts") != []:
        raise invalid("The Martial Arts and Manuals mirror contains unsealed recorded arts.")

    mirror_training = manual_lineage.get("training_sources")
    if manual_lineage.get("schema_version") != "TianxiaFoundry.CharacterGMTrainingSources.v1" or not isinstance(mirror_training, list):
        raise invalid("The Manual Lineage mirror has no valid training-source list.")
    for index, row in enumerate(mirror_training):
        if not isinstance(row, Mapping):
            raise invalid("The Manual Lineage mirror contains a non-object training row.", details={"index": index})
        contents = row.get("contents")
        if (
            row.get("classification") != "GM_GUIDANCE_ONLY"
            or row.get("source_category") != "PROJECT_SELECTED_RECORD_TRAINING"
            or row.get("type") != "other"
            or not isinstance(contents, Mapping)
            or contents.get("recorded_arts") != []
        ):
            raise invalid("The Manual Lineage mirror contains a purported executable training source.", details={"index": index})

    packet_rows = packet_registry.get("packets")
    if not isinstance(packet_rows, list):
        raise invalid("The manual-lineage packet registry has no packet list.")
    packet_matches = [
        row
        for row in packet_rows
        if isinstance(row, Mapping) and row.get("packet_id") == _MANUAL_LINEAGE_NONE_PACKET_ID
    ]
    if len(packet_matches) != 1:
        raise invalid(
            "The exact sealed no-manuals packet commitment is missing or duplicated.",
            details={"packet_id": _MANUAL_LINEAGE_NONE_PACKET_ID, "match_count": len(packet_matches)},
        )
    packet = packet_matches[0]
    for field, expected in _MANUAL_LINEAGE_NONE_PACKET_COMMITMENT.items():
        if packet.get(field) != expected:
            raise invalid(
                "The sealed no-manuals packet commitment is missing, alternate, or forged.",
                details={"field": field, "expected": expected, "actual": packet.get(field)},
            )

    raise _error(
        "FINAL_CHARACTER_BOUNDED_CHOICE_REQUIRED",
        "The accepted candidate has no sealed training source; an owner choice is required before compiler execution.",
        details=_manual_lineage_bounded_choice_details(),
    )


def _run_pinned_compiler_after_manual_lineage_gate(
    compiler_path: Path,
    corpus: Path,
    workspace: Path,
) -> dict[str, Any]:
    _require_manual_lineage_source_or_bounded_choice(workspace)
    return _run_pinned_compiler(compiler_path=compiler_path, corpus=corpus, workspace=workspace)


def _run_pinned_compiler(compiler_path: Path, corpus: Path, workspace: Path) -> dict[str, Any]:
    """Run only the exact production compiler/corpus pair."""

    _assert_production_pins(compiler_path, corpus)
    output = workspace / FINAL_CHARACTER_COMPILER_OUTPUT_DIRNAME
    ledger = workspace / "Build/Character_Master_Ledger.json"
    packets = workspace / "Command_2/Rules_Selection_Packets.json"
    if not ledger.is_file() or ledger.is_symlink() or not packets.is_file() or packets.is_symlink():
        raise _error("FINAL_CHARACTER_COMPILER_PRECONDITION", "The compiler inputs are not regular files.", details={"ledger": str(ledger), "rules_packets": str(packets), "corpus": str(corpus)})
    if output.exists():
        raise _error("FINAL_CHARACTER_COMPILER_OUTPUT_COLLISION", "The isolated compiler output directory is already occupied.")
    run_kwargs: dict[str, Any] = {
        "cwd": str(compiler_path.parent),
        "capture_output": True,
        "text": True,
        "check": False,
        "timeout": 180,
    }
    # A held workspace is intentionally exposed to the compiler only through
    # the exact descriptor facade recognized by _proc_fd_number.  subprocess
    # closes unrelated descriptors by default; pass this one descriptor on
    # POSIX so the child can resolve /proc/self/fd/N/Build/... safely.
    workspace_fd = _proc_fd_number(Path(workspace))
    if workspace_fd is not None and os.name == "posix":
        try:
            workspace_stat = os.fstat(workspace_fd)
        except OSError as exc:
            raise _error(
                "FINAL_CHARACTER_COMPILER_PRECONDITION",
                "The held compiler workspace descriptor is no longer valid.",
            ) from exc
        if not stat.S_ISDIR(workspace_stat.st_mode):
            raise _error(
                "FINAL_CHARACTER_COMPILER_PRECONDITION",
                "The held compiler workspace descriptor is not a directory.",
            )
        run_kwargs["pass_fds"] = (workspace_fd,)
    try:
        completed = subprocess.run(
            [sys.executable, str(compiler_path), "--ledger", str(ledger), "--rules-packets", str(packets), "--corpus", str(corpus), "--output", str(output)],
            **run_kwargs,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _error("FINAL_CHARACTER_COMPILER_REJECTED", "The pinned compiler could not be executed.", details={"error": str(exc)}) from exc
    result = {"returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}
    if int(result.get("returncode", 2)) != 0:
        raise _error(
            "FINAL_CHARACTER_COMPILER_REJECTED",
            "The pinned compiler rejected the materialized canonical inputs.",
            details={"returncode": result.get("returncode"), "stdout": str(result.get("stdout", ""))[-4000:], "stderr": str(result.get("stderr", ""))[-4000:]},
        )
    _validate_compiler_output(workspace)
    stdout = str(result.get("stdout", ""))[-4000:].replace(str(output), "<isolated-compiler-output>")
    stderr = str(result.get("stderr", ""))[-4000:].replace(str(output), "<isolated-compiler-output>")
    return {"returncode": 0, "stdout": stdout, "stderr": stderr, "output": str(output), "execution_mode": "pinned_subprocess", "corpus_sha256": _corpus_pin(corpus)}


def _validate_compiler_output(workspace: Path) -> None:
    output = workspace / FINAL_CHARACTER_COMPILER_OUTPUT_DIRNAME
    _ensure_regular_tree(output, code="FINAL_CHARACTER_COMPILER_OUTPUT_INVALID", message="The compiler output must contain regular files only.")
    action_path = output / "Complete_Action_Surface.json"
    if not action_path.is_file():
        raise _error("FINAL_CHARACTER_COMPILER_OUTPUT_INVALID", "The compiler output has no Complete_Action_Surface.json.")
    compiled_actions = _read_json(action_path, code="FINAL_CHARACTER_COMPILER_OUTPUT_INVALID")
    action_rows = compiled_actions.get("actions") if isinstance(compiled_actions, Mapping) else None
    expected_action = _read_json(workspace / "Build/Character_Master_Ledger.json", code="FINAL_CHARACTER_LEDGER_INVALID").get("actions", [])
    immortal_ids = {row.get("action_id") for row in expected_action if isinstance(row, Mapping) and row.get("classification") == IMMORTAL_ART_CLASSIFICATION}
    compiled_ids = {row.get("action_id") for row in action_rows if isinstance(row, Mapping)} if isinstance(action_rows, list) else set()
    expected_arts = _read_json(workspace / "Build/Character_Master_Ledger.json", code="FINAL_CHARACTER_LEDGER_INVALID").get("immortal_arts") or []
    if (expected_arts and not immortal_ids) or not immortal_ids.issubset(compiled_ids):
        raise _error("FINAL_CHARACTER_COMPILER_ACTION_UNRESOLVED", "The compiled action surface does not resolve the Immortal Art action.", details={"expected": sorted(x for x in immortal_ids if x), "compiled": sorted(x for x in compiled_ids if x)[:32]})


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _corpus_entry_text(corpus: Path, source_path: str) -> str | None:
    """Read one exact UTF-8 corpus member, including nested zip members."""

    data: bytes | None = None
    try:
        with zipfile.ZipFile(corpus) as root_zip:
            parts = source_path.split("::")
            data = root_zip.read(parts[0])
            for nested_name in parts[1:]:
                with zipfile.ZipFile(io.BytesIO(data)) as nested_zip:
                    data = nested_zip.read(nested_name)
    except (KeyError, OSError, UnicodeDecodeError, zipfile.BadZipFile):
        return None
    return data.decode("utf-8") if data is not None else None


def _corpus_active_texts(corpus: Path) -> tuple[set[str], dict[str, str]]:
    """Load active corpus text members and their exact source bytes once."""

    try:
        with zipfile.ZipFile(corpus) as root_zip:
            manifest = json.loads(root_zip.read("_CANON_AUTHORITY_MANIFEST.json").decode("utf-8"))
    except (KeyError, OSError, UnicodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise _error("FINAL_CHARACTER_PACKET_BRIDGE_CORPUS_INVALID", "The pinned rules corpus authority manifest is unavailable.", details={"path": str(corpus), "error": str(exc)}) from exc
    active = manifest.get("active_packet_sources")
    if not isinstance(active, list) or not all(isinstance(path, str) and path for path in active):
        raise _error("FINAL_CHARACTER_PACKET_BRIDGE_CORPUS_INVALID", "The pinned rules corpus active source list is invalid.")
    texts: dict[str, str] = {}
    for source_path in sorted(set(active)):
        text = _corpus_entry_text(corpus, source_path)
        if text is not None:
            texts[source_path] = text
    return set(active), texts


def _verify_modern_source_evidence(source_path: Any, source_hash: Any) -> bool:
    """Verify a modern record's legacy source hash against the pinned root.

    This check is only provenance evidence for compatibility selection.  The
    emitted compiler packet still points at an active member of the pinned
    corpus; a caller cannot forge a path/anchor and thereby obtain authority.
    """

    if not isinstance(source_path, str) or not isinstance(source_hash, str) or not _is_hash(source_hash):
        return False
    relative = source_path
    if source_path.startswith("non_sphere_authority/authority/"):
        relative = "09_RULES/Indexes/Paths/" + source_path.rsplit("/", 1)[-1]
    elif not source_path.startswith("09_RULES/"):
        return False
    candidate = _FINAL_CHARACTER_BASE_FACTORY_ROOT / relative
    try:
        return not candidate.is_symlink() and candidate.is_file() and sha256_file(candidate) == source_hash
    except OSError:
        return False


def _bridge_fixed_json(relative_path: str, expected_sha256: str) -> Mapping[str, Any] | None:
    """Read one server-owned modern authority file at its fixed identity.

    A modern packet may name this file, but neither its path nor its bytes are
    trusted from the copied workspace.  The bridge proves the installed APP
    (or pinned Factory) file first, then uses only the record selected by the
    packet's exact ID/name/anchor tuple.
    """

    path = _FINAL_CHARACTER_APP_ROOT / relative_path
    try:
        if path.is_symlink() or not path.is_file() or sha256_file(path) != expected_sha256:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _bridge_fixed_factory_json(relative_path: str, expected_sha256: str) -> Mapping[str, Any] | None:
    """Read a fixed pinned-Factory JSON registry without accepting packet paths."""

    path = _FINAL_CHARACTER_BASE_FACTORY_ROOT / relative_path
    try:
        if path.is_symlink() or not path.is_file() or sha256_file(path) != expected_sha256:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _bridge_name(value: Any) -> str:
    """Use a conservative name normalization for exact source headings."""

    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _bridge_contains_name_phrase(candidate: Any, target: Any) -> bool:
    """Match a canonical name as a complete consecutive token phrase."""

    candidate_tokens = _bridge_name(candidate).split()
    target_tokens = _bridge_name(target).split()
    if not target_tokens or len(target_tokens) > len(candidate_tokens):
        return False
    width = len(target_tokens)
    return any(candidate_tokens[index : index + width] == target_tokens for index in range(len(candidate_tokens) - width + 1))


def _bridge_heading_name(value: Any) -> str:
    """Normalize a Markdown heading without accepting heading/body prose."""

    text = str(value or "").strip()
    text = re.sub(r"^#+\s*", "", text)
    return _bridge_name(text)


def _bridge_has_target_cl(value: str, target_cl: int) -> bool:
    """Match an explicit CL marker or a printed CL range containing target_cl."""

    explicit = re.search(rf"(?i)\bCL\s*[-:]?\s*{target_cl}(?!\d)", value)
    if explicit:
        return True
    for start, end in re.findall(r"(?i)\bCL\s*(\d+)\s*[\-–—]\s*(\d+)", value):
        if int(start) <= target_cl <= int(end):
            return True
    return False


def _bridge_exact_path_excerpt(
    text: str,
    *,
    path_record: Mapping[str, Any],
    packet: Mapping[str, Any],
    feature_record: Mapping[str, Any] | None,
) -> str | None:
    """Derive one exact active Player Path heading/line from a fixed index.

    The index is authenticated separately.  The output is still taken from
    the pinned corpus bytes, never from the index's copied prose.  Feature
    records use their authenticated source section start; path records use
    the chapter's own name-bearing CL1–20 line.
    """

    name = packet.get("display_name")
    target_cl = packet.get("target_cl")
    if not isinstance(name, str) or not name.strip() or isinstance(target_cl, bool) or not isinstance(target_cl, int) or not 1 <= target_cl <= 20:
        return None
    lines = text.splitlines(keepends=True)
    if not lines:
        return None

    if feature_record is not None:
        sections = feature_record.get("source_sections")
        if not isinstance(sections, list):
            return None
        candidates: list[str] = []
        for section in sections:
            if not isinstance(section, Mapping):
                continue
            heading = section.get("source_heading")
            start = section.get("source_line_start")
            end = section.get("source_line_end")
            markdown = section.get("source_markdown")
            if (
                not isinstance(heading, str)
                or not isinstance(start, int)
                or not isinstance(end, int)
                or not isinstance(markdown, str)
                or start < 1
                or end < start
                or end > len(lines)
            ):
                continue
            indexed_section = "".join(lines[start - 1 : end])
            # The authenticated index carries the complete bounded source
            # slice.  Permit only the observed one-terminal-newline spelling
            # difference; prefix matching would allow an attacker to replace
            # the section body while retaining a trusted heading.
            # Only the count of terminal LF characters is normalized.  Any
            # trailing spaces/tabs or body-content change remains a mismatch.
            section_matches = indexed_section.rstrip("\n") == markdown.rstrip("\n")
            section_header = lines[start - 1].strip()
            if (
                not section_matches
                or not isinstance(heading, str)
                or not heading.strip()
                or not section_header.startswith("#")
                or _bridge_heading_name(section_header) != _bridge_heading_name(heading)
            ):
                continue
            bounded_lines = lines[start - 1 : end]
            bounded_matches = [
                line.strip()
                for line in bounded_lines
                if _bridge_contains_name_phrase(line, name) and _bridge_has_target_cl(line, target_cl)
            ]
            if len(bounded_matches) == 1:
                candidates.extend(bounded_matches)
                continue
            # Some canonical rules name the feature in the section heading
            # and place the CL schedule on the next line.  This fallback is
            # intentionally narrower than a generic heading/body search: the
            # authenticated heading must equal both the fixed source heading
            # and the packet display name, and exactly one line in the bound
            # section must carry the requested CL marker.
            if (
                _bridge_heading_name(section_header) == _bridge_heading_name(name)
                and _bridge_heading_name(section_header) == _bridge_heading_name(heading)
            ):
                cl_matches = [
                    (index, line.strip())
                    for index, line in enumerate(bounded_lines)
                    if _bridge_has_target_cl(line, target_cl)
                ]
                if len(cl_matches) == 1:
                    relative_index, _line = cl_matches[0]
                    candidates.append("".join(bounded_lines[: relative_index + 1]).strip())
            # ``Subpath Feature`` is a shared progression slot rather than a
            # printed heading/name in the path chapter.  The fixed index binds
            # this exact feature identity to the authenticated Subpaths
            # section, whose single schedule line is the compiler excerpt.
            # Keep this projection deliberately structural so another packet
            # cannot turn a display-name coincidence into authority.
            if (
                isinstance(feature_record, Mapping)
                and feature_record.get("feature_kind") == "subpath_feature_slot"
                and feature_record.get("canonical_id")
                == f"{path_record.get('canonical_id')}.feature.subpath_feature"
                and feature_record.get("display_name") == name
            ):
                granted_at_cl = feature_record.get("granted_at_cl")
                if isinstance(granted_at_cl, list) and target_cl in granted_at_cl:
                    schedule_matches = [
                        line.strip()
                        for line in bounded_lines
                        if "gain its features" in line.casefold()
                        and _bridge_has_target_cl(line, target_cl)
                    ]
                    if len(schedule_matches) == 1:
                        candidates.append(schedule_matches[0])
        return candidates[0] if len(candidates) == 1 else None

    # A path packet has no feature source section.  Bind its excerpt to the
    # chapter's own printed name and CL range, rather than accepting a generic
    # occurrence from an arbitrary chapter line.
    candidates = [
        line.strip()
        for line in lines[: min(len(lines), 64)]
        if _bridge_contains_name_phrase(line, name) and _bridge_has_target_cl(line, target_cl)
    ]
    # The authenticated chapter has several later CL references to the Path;
    # bind to its first introductory name/range line deterministically.  The
    # complete pinned corpus hash and authenticated index make this ordering
    # a source fact, not a packet-supplied choice.
    return candidates[0] if candidates else None


def _modern_packet_authority_family(packet: Mapping[str, Any]) -> str | None:
    """Classify modern packets before any legacy compatibility projection.

    Evidence markers are caller-controlled, so they cannot be the only way
    to recognize a modern record.  Resolve known IDs from the fixed,
    hash-verified registries first; conservative modern ID prefixes remain a
    fail-closed guard when a fixed registry is missing or unsafe.  A record
    which is recognized by more than one family is deliberately unresolved.
    """

    evidence = packet.get("source_evidence")
    row = evidence[0] if isinstance(evidence, list) and len(evidence) == 1 and isinstance(evidence[0], Mapping) else {}
    source_path = row.get("source_path")
    anchor = row.get("source_anchor")
    record_id = packet.get("record_id")
    families: set[str] = set()
    if source_path == _PACKET_METHOD_SOURCE_PATH or (isinstance(anchor, str) and anchor.startswith("method:")):
        families.add("method")
    if source_path == _PACKET_FOUNDATION_SOURCE_PATH or (isinstance(anchor, str) and anchor.startswith("foundation:")):
        families.add("foundation")
    if source_path == _PACKET_INSIGHT_SOURCE_PATH or (
        isinstance(anchor, str) and anchor.startswith("record:sphere-compendium.")
    ):
        families.add("insight")
    if isinstance(anchor, str) and anchor.startswith("subpath:"):
        families.add("subpath")
    if source_path in {proof["index_path"] for proof in _PACKET_PATH_PROOFS.values()} or (
        isinstance(anchor, str) and (anchor.startswith("path:") or anchor.startswith("path-feature:"))
    ):
        families.add("path")

    # A model may retain a known record ID while replacing both modern
    # evidence markers with an otherwise valid legacy tuple.  Read only the
    # fixed registries to recover the family in that case; no packet field is
    # used to choose the registry path or its bytes.
    method_registry = _bridge_fixed_json(_PACKET_METHOD_SOURCE_PATH, _PACKET_METHOD_SOURCE_SHA256)
    method_rows = method_registry.get("methods") if isinstance(method_registry, Mapping) else None
    foundation_registry = _bridge_fixed_factory_json(_PACKET_FOUNDATION_SOURCE_PATH, _PACKET_FOUNDATION_SOURCE_SHA256)
    foundation_rows = foundation_registry.get("foundations") if isinstance(foundation_registry, Mapping) else None
    insight_registry = _bridge_fixed_json(_PACKET_INSIGHT_SOURCE_PATH, _PACKET_INSIGHT_SOURCE_SHA256)
    insight_rows = insight_registry.get("records") if isinstance(insight_registry, Mapping) else None
    subpath_master = _bridge_fixed_json(_PACKET_SUBPATH_MASTER_PATH, _PACKET_SUBPATH_MASTER_SHA256)
    subpath_rows = subpath_master.get("entries") if isinstance(subpath_master, Mapping) else None
    path_master = _bridge_fixed_json(_PACKET_PATH_MASTER_PATH, _PACKET_PATH_MASTER_SHA256)
    path_rows = path_master.get("paths") if isinstance(path_master, Mapping) else None
    path_indexes = [_bridge_fixed_json(proof["index_path"], proof["index_sha256"]) for proof in _PACKET_PATH_PROOFS.values()]

    # The entire closed modern record space must be available before a packet
    # is allowed to use the legacy compatibility branch.  This matters most
    # for Foundation IDs whose names have no stable prefix (for example
    # ``ancient_desolate_sacred_body_v0_2C``).  Treat malformed, duplicate, or
    # unsafe fixed registries as an unavailable authority, not as an empty
    # registry which could accidentally hide a known ID.
    required_rows = (
        (method_rows, "method_id"),
        (foundation_rows, "foundation_id"),
        (insight_rows, "record_id"),
        (subpath_rows, "canonical_id"),
        (path_rows, "canonical_id"),
    )
    if any(
        not isinstance(rows, list)
        or any(not isinstance(item, Mapping) or not isinstance(item.get(key), str) or not item.get(key).strip() for item in rows)
        or len({item.get(key) for item in rows}) != len(rows)
        for rows, key in required_rows
    ):
        return "unavailable"
    if any(
        not isinstance(item, Mapping)
        or not isinstance(item.get("canonical_id"), str)
        or not item.get("canonical_id").strip()
        for item in insight_rows
    ):
        return "unavailable"
    if any(
        not isinstance(index, Mapping)
        or not isinstance(index.get("canonical_id"), str)
        or not index.get("canonical_id").strip()
        or not isinstance(index.get("features"), list)
        or any(
            not isinstance(item, Mapping)
            or not isinstance(item.get("canonical_id"), str)
            or not item.get("canonical_id").strip()
            for item in index.get("features", [])
        )
        or len({item.get("canonical_id") for item in index.get("features", [])}) != len(index.get("features", []))
        for index in path_indexes
    ):
        return "unavailable"

    if any(isinstance(item, Mapping) and item.get("method_id") == record_id for item in method_rows):
        families.add("method")
    if any(isinstance(item, Mapping) and item.get("foundation_id") == record_id for item in foundation_rows):
        families.add("foundation")
    if any(isinstance(item, Mapping) and item.get("canonical_id") == record_id for item in insight_rows):
        families.add("insight")
    if any(isinstance(item, Mapping) and item.get("canonical_id") == record_id for item in subpath_rows):
        families.add("subpath")
    if any(isinstance(item, Mapping) and item.get("canonical_id") == record_id for item in path_rows):
        families.add("path")
    for path_index in path_indexes:
        if path_index.get("canonical_id") == record_id:
            families.add("path")
        feature_rows = path_index.get("features")
        if any(isinstance(item, Mapping) and item.get("canonical_id") == record_id for item in feature_rows):
            families.add("path")

    # These prefixes are the closed-world identity grammar of the modern
    # records.  They intentionally do not authorize anything; they only
    # prevent a known/plausible modern identity from falling through to the
    # older source-hash compatibility path when a fixed file is unavailable.
    if isinstance(record_id, str):
        if record_id.startswith("METHOD-"):
            families.add("method")
        if record_id.startswith("FOUNDATION_") or record_id.startswith("furnace_heart_record_"):
            families.add("foundation")
        if record_id.startswith("tianxia.subpath."):
            families.add("subpath")
        if record_id.startswith("insight."):
            families.add("insight")
        if record_id.startswith(_PACKET_PATH_RECORD_PREFIXES):
            families.add("path")

    if len(families) > 1:
        return "ambiguous"
    return next(iter(families), None)


def _bridge_modern_packet_source(
    packet: Mapping[str, Any],
    *,
    corpus: Path,
    active: set[str],
    corpus_texts: Mapping[str, str],
) -> tuple[bool, dict[str, Any] | None]:
    """Prove a Method/Foundation/Subpath/Path packet against fixed records and corpus.

    The boolean distinguishes a recognized modern family from legacy packet
    records.  A recognized family with no proof must not fall through to the
    old hash/substring compatibility path.
    """

    family = _modern_packet_authority_family(packet)
    if family is None:
        return False, None
    if family not in {"method", "foundation", "insight", "subpath", "path"}:
        return True, None
    evidence = packet.get("source_evidence")
    evidence_row = evidence[0] if isinstance(evidence, list) and len(evidence) == 1 and isinstance(evidence[0], Mapping) else None
    if evidence_row is None:
        return True, None
    source_path = evidence_row.get("source_path")
    source_hash = evidence_row.get("source_hash")
    anchor = evidence_row.get("source_anchor")
    record_id = packet.get("record_id")
    display_name = packet.get("display_name")
    if not isinstance(record_id, str) or not record_id.strip() or not isinstance(display_name, str) or not display_name.strip():
        return True, None

    if family == "method":
        if source_path != _PACKET_METHOD_SOURCE_PATH or source_hash != _PACKET_METHOD_SOURCE_SHA256 or anchor != f"method:{record_id}":
            return True, None
        registry = _bridge_fixed_json(_PACKET_METHOD_SOURCE_PATH, _PACKET_METHOD_SOURCE_SHA256)
        rows = registry.get("methods") if isinstance(registry, Mapping) else None
        matches = [row for row in rows if isinstance(row, Mapping) and row.get("method_id") == record_id] if isinstance(rows, list) else []
        if len(matches) != 1 or matches[0].get("name") != display_name:
            return True, None
        if "Needed/Tianxia_Methods_Master_v0_1.md" not in active or "Needed/Tianxia_Methods_Master_v0_1.md" not in corpus_texts:
            return True, None
        # Reuse the compiler-selection helper's exact heading semantics.  The
        # helper reads only the pinned corpus member named by the active set.
        try:
            with zipfile.ZipFile(corpus) as corpus_zip:
                source = _compiler_method_excerpt(corpus_zip, display_name, active)
        except (OSError, zipfile.BadZipFile):
            return True, None
        if not isinstance(source, Mapping) or source.get("source_path") not in ({"Needed/Tianxia_Methods_Master_v0_1.md", _method_release.SOURCE_MEMBER} & active):
            return True, None
        source_text = source.get("source_text")
        if not isinstance(source_text, str) or not source_text.strip():
            return True, None
        return True, {
            "source_path": source["source_path"],
            "source_text": source_text,
            "source_file_sha256": source.get("source_file_sha256"),
            "source_evidence_verified": True,
        }

    if family == "foundation":
        if source_path != _PACKET_FOUNDATION_SOURCE_PATH or source_hash != _PACKET_FOUNDATION_SOURCE_SHA256 or anchor != f"foundation:{record_id}":
            return True, None
        registry = _bridge_fixed_factory_json(_PACKET_FOUNDATION_SOURCE_PATH, _PACKET_FOUNDATION_SOURCE_SHA256)
        rows = registry.get("foundations") if isinstance(registry, Mapping) else None
        matches = [row for row in rows if isinstance(row, Mapping) and row.get("foundation_id") == record_id] if isinstance(rows, list) else []
        if len(matches) != 1 or matches[0].get("name") != display_name:
            return True, None
        try:
            with zipfile.ZipFile(corpus) as corpus_zip:
                source = _compiler_foundation_excerpt(corpus_zip, display_name, active)
        except (OSError, zipfile.BadZipFile):
            return True, None
        if not isinstance(source, Mapping):
            return True, None
        source_path = source.get("source_path")
        source_text = source.get("source_text")
        if not isinstance(source_path, str) or source_path not in active or not isinstance(source_text, str) or not source_text.strip():
            return True, None
        return True, {
            "source_path": source_path,
            "source_text": source_text,
            "source_file_sha256": source.get("source_file_sha256"),
            "source_evidence_verified": True,
        }

    if family == "insight":
        # The Stage-2 Insight packet points at an APP-side CAT3 occurrence
        # registry.  That registry is evidence for the canonical identity,
        # not compiler authority: the emitted excerpt must still come from
        # the exact active corpus member named by the sealed record's source
        # file.  Resolve the occurrence ID from the fixed canonical record so
        # a packet cannot pair a known canonical ID with another record's
        # legacy evidence tuple.
        if source_path != _PACKET_INSIGHT_SOURCE_PATH or source_hash != _PACKET_INSIGHT_SOURCE_SHA256:
            return True, None
        registry = _bridge_fixed_json(_PACKET_INSIGHT_SOURCE_PATH, _PACKET_INSIGHT_SOURCE_SHA256)
        rows = registry.get("records") if isinstance(registry, Mapping) else None
        matches = [
            row
            for row in rows
            if isinstance(row, Mapping) and row.get("canonical_id") == record_id
        ] if isinstance(rows, list) else []
        if len(matches) != 1:
            # Duplicate canonical occurrences are deliberately not guessed;
            # the exact occurrence anchor must identify one fixed record.
            return True, None
        record = matches[0]
        occurrence_id = record.get("record_id")
        if (
            not isinstance(occurrence_id, str)
            or not occurrence_id.strip()
            or anchor != f"record:{occurrence_id}"
            or record.get("display_name") != display_name
            or record.get("name") != display_name
            or record.get("source_family") != "Sphere Compendium"
            or record.get("source_file") != "Tianxia_Sphere_Compendium_Latest_R0I_85Spheres.md"
            or record.get("selectable") is not True
            or record.get("nonselectable_reason") not in (None, "")
        ):
            return True, None
        minimum_cl = record.get("minimum_cl")
        selection_cl = record.get("minimum_cl_level_selection")
        target_cl = packet.get("target_cl")
        if (
            isinstance(minimum_cl, bool)
            or not isinstance(minimum_cl, int)
            or isinstance(selection_cl, bool)
            or not isinstance(selection_cl, int)
            or isinstance(target_cl, bool)
            or not isinstance(target_cl, int)
            or minimum_cl < 1
            or selection_cl != minimum_cl
            or target_cl != minimum_cl
        ):
            return True, None
        if _PACKET_INSIGHT_CORPUS_PATH not in active or _PACKET_INSIGHT_CORPUS_PATH not in corpus_texts:
            return True, None
        corpus_text = corpus_texts[_PACKET_INSIGHT_CORPUS_PATH]
        if _sha256_text(corpus_text) != _PACKET_INSIGHT_CORPUS_SHA256:
            return True, None
        # The fixed CAT3 occurrence maps to the exact active sphere
        # compendium file.  Require one complete heading match so a caller's
        # display name cannot authorize an arbitrary same-named line.
        headings = [
            line.strip()
            for line in corpus_text.splitlines()
            if re.match(r"^###\s+\S", line.strip())
            and _bridge_heading_name(line) == _bridge_heading_name(display_name)
        ]
        if len(headings) != 1:
            return True, None
        return True, {
            "source_path": _PACKET_INSIGHT_CORPUS_PATH,
            "source_text": headings[0],
            "source_file_sha256": _PACKET_INSIGHT_CORPUS_SHA256,
            "source_evidence_verified": True,
        }

    if family == "subpath":
        if not isinstance(anchor, str) or not anchor.startswith("subpath:") or anchor != f"subpath:{record_id}":
            return True, None
        master = _bridge_fixed_json(_PACKET_SUBPATH_MASTER_PATH, _PACKET_SUBPATH_MASTER_SHA256)
        entries = master.get("entries") if isinstance(master, Mapping) else None
        matches = [row for row in entries if isinstance(row, Mapping) and row.get("canonical_id") == record_id] if isinstance(entries, list) else []
        if len(matches) != 1:
            return True, None
        entry = matches[0]
        if entry.get("display_name") != display_name or entry.get("option_type") != "subpath" or entry.get("status") != "PASS":
            return True, None
        owning_path_id = entry.get("owning_path_id")
        path_proof = _PACKET_PATH_PROOFS.get(owning_path_id)
        if path_proof is None:
            return True, None
        path_master = _bridge_fixed_json(_PACKET_PATH_MASTER_PATH, _PACKET_PATH_MASTER_SHA256)
        path_rows = path_master.get("paths") if isinstance(path_master, Mapping) else None
        owning_matches = [row for row in path_rows if isinstance(row, Mapping) and row.get("canonical_id") == owning_path_id] if isinstance(path_rows, list) else []
        if len(owning_matches) != 1 or owning_matches[0].get("display_name") != entry.get("owning_path_name"):
            return True, None
        prerequisites = entry.get("prerequisites")
        if not isinstance(prerequisites, Mapping):
            return True, None
        minimum_cl = prerequisites.get("minimum_cl")
        selection_level = prerequisites.get("selection_level")
        target_cl = packet.get("target_cl")
        if (
            isinstance(minimum_cl, bool)
            or not isinstance(minimum_cl, int)
            or isinstance(selection_level, bool)
            or not isinstance(selection_level, int)
            or isinstance(target_cl, bool)
            or not isinstance(target_cl, int)
            or minimum_cl < 1
            or selection_level < 1
            or minimum_cl != selection_level
            or target_cl != selection_level
        ):
            return True, None
        source = entry.get("source")
        if not isinstance(source, Mapping):
            return True, None
        source_corpus_path = source.get("corpus_path")
        source_factory_path = source.get("factory_source_path")
        source_file_hash = source.get("source_file_sha256")
        line_start = source.get("line_start")
        line_end = source.get("line_end")
        if (
            not isinstance(source_corpus_path, str)
            or not isinstance(source_factory_path, str)
            or not isinstance(source_file_hash, str)
            or not _is_hash(source_file_hash)
            or not isinstance(line_start, int)
            or isinstance(line_start, bool)
            or not isinstance(line_end, int)
            or isinstance(line_end, bool)
            or line_start < 1
            or line_end < line_start
            or source_factory_path != "09_RULES/Source_Text/" + source_corpus_path.removeprefix("Canonical/")
            or (source.get("section_sha256") is not None and not _is_hash(source.get("section_sha256")))
            or source_path != source_factory_path
            or source_hash != source_file_hash
        ):
            return True, None
        if source_corpus_path not in active or source_corpus_path not in corpus_texts:
            return True, None
        corpus_text = corpus_texts[source_corpus_path]
        corpus_lines = corpus_text.splitlines(keepends=True)
        if line_end > len(corpus_lines) or _sha256_text(corpus_text) != source_file_hash:
            return True, None
        header = corpus_lines[line_start - 1].strip()
        if not header.startswith("#") or _bridge_heading_name(header) != _bridge_heading_name(display_name):
            return True, None
        return True, {
            "source_path": source_corpus_path,
            "source_text": header,
            "source_file_sha256": source_file_hash,
            "source_evidence_verified": True,
        }

    # Path/feature packets are authenticated by one of the three exact APP
    # index files, then mapped to only that index's active Player Path chapter.
    path_id: str | None = None
    feature_id: str | None = None
    if isinstance(anchor, str) and anchor.startswith("path-feature:"):
        pieces = anchor.split(":")
        if len(pieces) != 3 or not pieces[1] or not pieces[2]:
            return True, None
        path_id, feature_id = pieces[1], pieces[2]
    elif isinstance(anchor, str) and anchor.startswith("path:"):
        pieces = anchor.split(":")
        if len(pieces) != 2 or not pieces[1]:
            return True, None
        path_id = pieces[1]
    else:
        return True, None
    proof = _PACKET_PATH_PROOFS.get(path_id)
    if proof is None or source_path != proof["index_path"] or source_hash != proof["index_sha256"]:
        return True, None
    if feature_id is None and record_id != path_id:
        return True, None
    if feature_id is not None and (record_id != feature_id or not feature_id.startswith(path_id + ".feature.")):
        return True, None
    index = _bridge_fixed_json(proof["index_path"], proof["index_sha256"])
    master = _bridge_fixed_json(_PACKET_PATH_MASTER_PATH, _PACKET_PATH_MASTER_SHA256)
    if not isinstance(index, Mapping) or not isinstance(master, Mapping):
        return True, None
    if (
        index.get("canonical_id") != path_id
        or index.get("publication_status") != "current_canonical_player_path"
        or (feature_id is None and index.get("display_name") != display_name)
    ):
        return True, None
    index_source = index.get("source")
    if (
        not isinstance(index_source, Mapping)
        or index_source.get("corpus_path") != proof["corpus_path"]
        or index_source.get("sha256") != proof["corpus_sha256"]
    ):
        return True, None
    master_rows = master.get("paths")
    master_matches = [row for row in master_rows if isinstance(row, Mapping) and row.get("canonical_id") == path_id] if isinstance(master_rows, list) else []
    if len(master_matches) != 1:
        return True, None
    master_row = master_matches[0]
    master_source = master_row.get("source")
    if (
        master_row.get("display_name") != index.get("display_name")
        or master_row.get("index_file") != proof["index_file"]
        or not isinstance(master_source, Mapping)
        or master_source.get("corpus_path") != proof["corpus_path"]
        or master_source.get("sha256") != proof["corpus_sha256"]
    ):
        return True, None
    corpus_text = corpus_texts.get(proof["corpus_path"])
    if not isinstance(corpus_text, str) or _sha256_text(corpus_text) != proof["corpus_sha256"]:
        return True, None
    feature: Mapping[str, Any] | None = None
    if feature_id is not None:
        features = index.get("features")
        matches = [row for row in features if isinstance(row, Mapping) and row.get("canonical_id") == feature_id] if isinstance(features, list) else []
        if len(matches) != 1 or matches[0].get("display_name") != display_name:
            return True, None
        grants = matches[0].get("granted_at_cl")
        target_cl = packet.get("target_cl")
        if not isinstance(grants, list) or not isinstance(target_cl, int) or isinstance(target_cl, bool) or target_cl not in grants:
            return True, None
        feature = matches[0]
    excerpt = _bridge_exact_path_excerpt(corpus_text, path_record=index, packet=packet, feature_record=feature)
    if excerpt is None:
        return True, None
    return True, {
        "source_path": proof["corpus_path"],
        "source_text": excerpt,
        "source_file_sha256": proof["corpus_sha256"],
        "source_evidence_verified": True,
    }


def _source_excerpt(text: str, packet: Mapping[str, Any]) -> str | None:
    """Derive a small exact source excerpt from a trusted source anchor.

    Modern Stage-2 records carry line/heading anchors but not the compiler's
    ``source_text`` field.  The excerpt is selected from bytes read directly
    from the pinned corpus; no modern description is promoted to authority.
    """

    evidence = packet.get("source_evidence")
    if not isinstance(evidence, list) or len(evidence) != 1 or not isinstance(evidence[0], Mapping):
        return None
    anchor = evidence[0].get("source_anchor")
    if not isinstance(anchor, str):
        return None
    lines = text.splitlines(keepends=True)
    if anchor.startswith("line:"):
        try:
            line_number = int(anchor.split(":", 2)[1])
        except (TypeError, ValueError):
            return None
        if line_number < 1 or line_number > len(lines):
            return None
        return lines[line_number - 1].strip()
    if anchor.startswith("heading:"):
        target = " ".join(anchor.split(":", 1)[1].replace("_", " ").replace("-", " ").replace(".", " ").strip().lower().split())
        for index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith("#"):
                continue
            heading = " ".join(stripped.lstrip("#").strip().lower().replace("_", " ").replace("-", " ").replace(".", " ").split())
            if target and target in heading:
                # Born Under Suspicion supplies several compiler effect claims
                # from one fixed source section.  Keep the legacy heading-only
                # excerpt for all other compatibility packets, but retain this
                # exact section so every emitted claim remains source-backed.
                if packet.get("record_id") == _ORIGIN_INSIGHT_ID:
                    end = next(
                        (
                            candidate
                            for candidate in range(index + 1, len(lines))
                            if lines[candidate].strip().startswith("## ")
                        ),
                        len(lines),
                    )
                    return "".join(lines[index:end]).strip()
                return stripped
        return None
    return None


def _path_compatibility_excerpt(text: str, packet: Mapping[str, Any]) -> str | None:
    """Select a name-bearing exact line for a non-sphere path record."""

    name = packet.get("display_name") or packet.get("record_id")
    if not isinstance(name, str) or not name.strip():
        return None
    target = name.strip().lower()
    target_cl = packet.get("target_cl")
    lines = text.splitlines(keepends=True)
    for line in lines:
        if target in line.lower() and (target_cl is None or f"**{target_cl}**" in line or f"cl{target_cl}" in line.lower()):
            return line.strip()
    for line in lines:
        if target in line.lower():
            return line.strip()
    return None


def _modern_packet_reference_contexts(
    workspace: Path,
) -> tuple[
    set[str],
    dict[str, list[str]],
    dict[str, list[tuple[Mapping[str, Any], str, tuple[str, ...], bool]]],
]:
    """Collect executable packet references and their containing rows.

    The row context is deliberately captured at the packet-reference field,
    rather than inferred from packet identity.  User-directive authority is
    only legal when every mechanical row that names it opts into
    ``custom_design`` explicitly; a packet cannot supply that flag itself.
    """

    refs: set[str] = set()
    locations: dict[str, list[str]] = {}
    reference_contexts: dict[
        str,
        list[tuple[Mapping[str, Any], str, tuple[str, ...], bool]],
    ] = {}
    files = (
        workspace / "Build/Character_Master_Ledger.json",
        workspace / "Build/Complete_Action_Surface.json",
        workspace / "Command_4/Complete_Action_Surface.json",
    )

    def walk(value: Any, location: str, *, file_relative: str) -> None:
        if isinstance(value, Mapping):
            # Flat packet fields retain the original row-level duplicate
            # guard.  A skill provenance map is different: one canonical
            # packet may lawfully explain more than one skill, so map entries
            # must not be compared against one another.  Structured refs do
            # still conflict with any flat sibling field in the same row.
            flat_row_packet_ids: list[str] = []
            structured_row_packet_ids: set[str] = set()
            is_core_stats = (
                file_relative == "Build/Character_Master_Ledger.json"
                and location == f"{file_relative}.core_stats"
            )
            for key, child in value.items():
                if not isinstance(key, str):
                    raise _error(
                        "FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID",
                        "A packet-reference surface contains a non-string object key.",
                        details={"location": location},
                    )
                child_location = f"{location}.{key}"
                if key in {
                    "saving_throw_adjustment_source_packet_ids",
                    "skill_source_packet_ids",
                }:
                    if not is_core_stats:
                        raise _error(
                            "FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID",
                            "A structured packet-reference field is only legal in core_stats.",
                            details={"location": child_location, "field": key},
                        )
                    if key == "saving_throw_adjustment_source_packet_ids":
                        # The current compiler projection has no saving
                        # proficiencies.  Its authenticated shape is exactly
                        # an empty object; any attempted nonempty source map
                        # would be an invented proficiency binding.
                        if not isinstance(child, Mapping) or child:
                            raise _error(
                                "FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID",
                                "The no-proficiency saving-adjustment packet map must be empty.",
                                details={"location": child_location, "field": key},
                            )
                        continue

                    # skill_source_packet_ids is a compiler provenance map,
                    # not a generic object-valued *_source_packet_ids field.
                    if not isinstance(child, Mapping):
                        raise _error(
                            "FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID",
                            "The core skill packet map must be an object keyed by skill.",
                            details={"location": child_location, "field": key},
                        )
                    skills = value.get("skills")
                    if not isinstance(skills, Mapping):
                        raise _error(
                            "FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID",
                            "The core skill packet map requires a skills object.",
                            details={"location": child_location, "field": key},
                        )
                    skill_names: list[str] = []
                    for skill_name in skills:
                        if (
                            not isinstance(skill_name, str)
                            or not skill_name
                            or skill_name != skill_name.strip()
                        ):
                            raise _error(
                                "FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID",
                                "A core skill name must be a clean nonempty string.",
                                details={"location": f"{location}.skills"},
                            )
                        skill_names.append(skill_name)
                    map_names = list(child)
                    if (
                        any(
                            not isinstance(skill_name, str)
                            or not skill_name
                            or skill_name != skill_name.strip()
                            for skill_name in map_names
                        )
                        or set(map_names) != set(skill_names)
                    ):
                        raise _error(
                            "FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID",
                            "The core skill packet map keys must exactly match core_stats.skills.",
                            details={
                                "location": child_location,
                                "field": key,
                                "expected_skills": skill_names,
                                "actual_skills": map_names,
                            },
                        )
                    for skill_name, skill_packet_ids in child.items():
                        if not isinstance(skill_packet_ids, list):
                            raise _error(
                                "FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID",
                                "Each core skill packet-map value must be a list.",
                                details={
                                    "location": f"{child_location}.{skill_name}",
                                    "field": key,
                                },
                            )
                        if any(
                            not isinstance(packet_id, str)
                            or not packet_id
                            or packet_id != packet_id.strip()
                            for packet_id in skill_packet_ids
                        ):
                            raise _error(
                                "FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID",
                                "A core skill packet-map value must contain clean nonempty strings.",
                                details={
                                    "location": f"{child_location}.{skill_name}",
                                    "field": key,
                                },
                            )
                        if len(skill_packet_ids) != len(set(skill_packet_ids)):
                            raise _error(
                                "FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID",
                                "A core skill packet-map value contains duplicate packet references.",
                                details={
                                    "location": f"{child_location}.{skill_name}",
                                    "field": key,
                                },
                            )
                        normalized_values = tuple(skill_packet_ids)
                        if any(packet_id in flat_row_packet_ids for packet_id in normalized_values):
                            raise _error(
                                "FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID",
                                "A mechanical row contains duplicate packet references.",
                                details={"location": f"{child_location}.{skill_name}", "field": key},
                            )
                        # Distinct skill entries may intentionally share one
                        # canonical packet.  Keep the set only to reject a
                        # later flat sibling field and to make that exception
                        # explicit in the scanner's state.
                        structured_row_packet_ids.update(normalized_values)
                        skill_location = f"{child_location}.{skill_name}"
                        for packet_id in normalized_values:
                            refs.add(packet_id)
                            locations.setdefault(packet_id, []).append(skill_location)
                            reference_contexts.setdefault(packet_id, []).append(
                                (value, skill_location, normalized_values, True)
                            )
                    # Do not recurse into this sanctioned map: a skill name
                    # ending in *_source_packet_ids is data, not another
                    # packet-reference field.
                    continue
                if key == "source_packet_ids" or key == "source_packet_id" or key.endswith("_source_packet_ids"):
                    plural_field = key != "source_packet_id"
                    if plural_field:
                        if not isinstance(child, list):
                            raise _error(
                                "FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID",
                                "A plural packet-reference field must be a list.",
                                details={"location": child_location, "field": key},
                            )
                        values = child
                    else:
                        if not isinstance(child, str):
                            raise _error(
                                "FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID",
                                "A singular packet-reference field must be a string.",
                                details={"location": child_location, "field": key},
                            )
                        values = [child]
                    if any(
                        not isinstance(packet_id, str)
                        or not packet_id
                        or packet_id != packet_id.strip()
                        for packet_id in values
                    ):
                        raise _error(
                            "FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID",
                            "A packet-reference value must be a clean nonempty string.",
                            details={"location": child_location, "field": key},
                        )
                    if (
                        len(values) != len(set(values))
                        or any(packet_id in flat_row_packet_ids for packet_id in values)
                        or any(packet_id in structured_row_packet_ids for packet_id in values)
                    ):
                        raise _error(
                            "FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID",
                            "A mechanical row contains duplicate packet references.",
                            details={"location": child_location, "field": key},
                        )
                    normalized_values = tuple(values)
                    flat_row_packet_ids.extend(normalized_values)
                    for packet_id in normalized_values:
                        refs.add(packet_id)
                        locations.setdefault(packet_id, []).append(child_location)
                        reference_contexts.setdefault(packet_id, []).append(
                            (value, child_location, normalized_values, False)
                        )
                walk(child, child_location, file_relative=file_relative)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{location}[{index}]", file_relative=file_relative)

    for path in files:
        if not path.is_file() or path.is_symlink():
            raise _error("FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID", "The executable packet-reference surface is missing or unsafe.", details={"path": str(path)})
        file_relative = path.relative_to(workspace).as_posix()
        walk(
            _read_json(path, code="FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID"),
            file_relative,
            file_relative=file_relative,
        )
    return refs, locations, reference_contexts


def _modern_packet_refs(workspace: Path) -> tuple[set[str], dict[str, list[str]]]:
    """Collect only executable packet references from the canonical ledger/surfaces."""

    refs, locations, _contexts = _modern_packet_reference_contexts(workspace)
    return refs, locations


def _bridge_user_directive_packet(
    packet: Mapping[str, Any],
    *,
    packet_id: str,
    reference_contexts: Mapping[
        str,
        list[tuple[Mapping[str, Any], str, tuple[str, ...], bool]],
    ],
) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
    """Validate one explicit user-directive packet without corpus fallback.

    User directives are not a source-backed corpus family.  They may enter the
    compiler only as a bounded, owner-directed custom row and must retain that
    authority verbatim.  Every rejection is returned to the bridge as data so
    no partially projected native packet can be emitted.
    """

    family = _modern_packet_authority_family(packet)
    if family is not None:
        return None, "user_directive packet conflicts with a recognized canonical record family", {
            "family": family,
        }
    if "source_evidence" in packet and packet.get("source_evidence") is not None:
        return None, "user_directive packet contains conflicting corpus source evidence", {
            "field": "source_evidence",
        }

    source_path = packet.get("source_path")
    source_anchor = packet.get("source_anchor")
    source_text = packet.get("source_text")
    source_text_sha256 = packet.get("source_text_sha256")
    if source_path != _USER_DIRECTIVE_SOURCE_PATH:
        return None, "user_directive packet source path is unsupported", {
            "source_path": source_path,
            "expected_source_path": _USER_DIRECTIVE_SOURCE_PATH,
        }
    if (
        not isinstance(source_anchor, str)
        or not source_anchor.strip()
        or source_anchor != source_anchor.strip()
        or len(source_anchor) > _USER_DIRECTIVE_SOURCE_ANCHOR_MAX_LENGTH
        or any(ord(char) < 32 for char in source_anchor)
    ):
        return None, "user_directive packet source anchor is missing or malformed", {
            "source_anchor": source_anchor,
        }
    if (
        not isinstance(source_text, str)
        or not source_text.strip()
        or source_text != source_text.strip()
        or len(source_text.encode("utf-8")) > _USER_DIRECTIVE_SOURCE_TEXT_MAX_BYTES
        or any(ord(char) < 32 and char not in "\n\r\t" for char in source_text)
    ):
        return None, "user_directive packet source text is missing or exceeds the bounded contract", {
            "source_text_bytes": len(source_text.encode("utf-8")) if isinstance(source_text, str) else None,
            "max_source_text_bytes": _USER_DIRECTIVE_SOURCE_TEXT_MAX_BYTES,
        }
    if not _is_hash(source_text_sha256) or source_text_sha256 != _sha256_text(source_text):
        return None, "user_directive packet source text hash is missing or forged", {
            "source_text_sha256": source_text_sha256,
        }

    name = packet.get("name")
    if not isinstance(name, str) or not name.strip():
        name = packet.get("display_name")
    if not isinstance(name, str) or not name.strip():
        return None, "user_directive packet has no stable name", {}

    contexts = reference_contexts.get(packet_id, [])
    if not contexts:
        return None, "user_directive packet is not bound to an executable row", {}
    invalid_rows: list[dict[str, Any]] = []
    for row, location, direct_packet_ids, structured_provenance in contexts:
        if structured_provenance:
            invalid_rows.append({
                "location": location,
                "reason": "user_directive packet cannot authorize compiler provenance maps",
            })
        if row.get("custom_design") is not True:
            invalid_rows.append({"location": location, "reason": "custom_design must be true"})
        # A custom directive must be the sole direct authority on its row.  A
        # corpus packet beside it would let the compiler's canonical branch
        # silently ignore the directive, while another directive would make
        # the source choice ambiguous.
        if direct_packet_ids != (packet_id,):
            invalid_rows.append({
                "location": location,
                "reason": "user_directive packet cannot share a mechanical row with another packet authority",
                "packet_ids": list(direct_packet_ids),
            })
    if invalid_rows:
        return None, "user_directive packet requires an unambiguous custom-design mechanical row", {
            "invalid_rows": invalid_rows,
        }

    native_packet = {
        "packet_id": packet_id,
        "name": name.strip(),
        "authority": "user_directive",
        "source_path": source_path,
        "source_text": source_text,
        "source_text_sha256": source_text_sha256,
        "source_section": source_anchor,
        "source_classification": "user_directive",
        "modern_record_id": packet.get("record_id"),
        "modern_source_path": source_path,
        "modern_source_sha256": source_text_sha256,
        "source_evidence_verified": False,
    }
    return native_packet, "", {}


def _project_modern_path_fields_for_compiler(workspace: Path) -> dict[str, Any]:
    """Project the modern Path grant ledger into the pinned compiler shape.

    Stage 2 records each Path feature acquisition event.  The pinned compiler
    consumes the permanent feature set instead: a repeated canonical feature
    (for example an advancement choice or a Subpath Feature slot) is one
    feature grant whose later rows are milestone events.  This boundary
    therefore validates every event against the fixed Path authority, retains
    the earliest occurrence, and records every later occurrence as provenance
    before adding the compiler-only flat fields.

    No Path feature is invented here.  In particular, automatic CL1 features
    which are absent from the modern event ledger are deliberately left for a
    separate source-backed bridge.
    """

    def invalid(message: str, *, details: Any = None) -> FoundryError:
        return _error("FINAL_CHARACTER_PATH_PROJECTION_INVALID", message, details=details)

    root = Path(workspace)
    ledger_path = root / "Build/Character_Master_Ledger.json"
    registry_path = root / "Command_2/Rules_Selection_Packets.json"
    if ledger_path.is_symlink() or not ledger_path.is_file() or registry_path.is_symlink() or not registry_path.is_file():
        raise invalid("The copied Path projection inputs are missing or unsafe.")
    raw_ledger_bytes = ledger_path.read_bytes()
    ledger = _read_json(ledger_path, code="FINAL_CHARACTER_PATH_PROJECTION_INVALID")
    if not isinstance(ledger, Mapping):
        raise invalid("The copied master ledger is not a mapping.")
    character = ledger.get("character")
    if not isinstance(character, Mapping):
        raise invalid("The copied master ledger has no character Path authority.")

    character_path_id = character.get("path_id")
    character_path_name = character.get("path")
    character_key_ability = character.get("key_ability")
    character_cl = character.get("cl")
    if (
        not isinstance(character_path_id, str)
        or not character_path_id.strip()
        or not isinstance(character_path_name, str)
        or not character_path_name.strip()
        or not isinstance(character_key_ability, str)
        or not character_key_ability.strip()
        or type(character_cl) is not int
        or not 1 <= character_cl <= 20
    ):
        raise invalid(
            "The copied character has incomplete active Path identity.",
            details={"path_id": character_path_id, "path": character_path_name, "key_ability": character_key_ability, "cl": character_cl},
        )
    path_rows = character.get("paths")
    selection_rows = ledger.get("path_selections")
    binding_fields = ("path_id", "display_name", "key_ability", "effective_cl", "source_packet_ids")
    if (
        not isinstance(path_rows, list)
        or not path_rows
        or not isinstance(selection_rows, list)
        or len(path_rows) != len(selection_rows)
        or any(not isinstance(row, Mapping) for row in [*path_rows, *selection_rows])
    ):
        raise invalid("The character Paths and Path selections must contain matching rows.")
    if any(
        any(path_row.get(field) != selection_row.get(field) for field in binding_fields)
        for path_row, selection_row in zip(path_rows, selection_rows)
    ):
        raise invalid("The character Path and top-level Path selection rows diverge.", details={"fields": list(binding_fields)})
    primary_path = path_rows[0]
    if any(
        character.get(character_field) != primary_path.get(path_field)
        for character_field, path_field in (
            ("path_id", "path_id"),
            ("path", "display_name"),
            ("key_ability", "key_ability"),
        )
    ):
        raise invalid("The primary Path identity diverges from character scalar fields.")
    path_id = primary_path["path_id"]
    path_name = primary_path["display_name"]
    key_ability = primary_path["key_ability"]
    path_by_id: dict[str, Mapping[str, Any]] = {}
    path_target_cls: dict[str, int] = {}
    path_packet_ids: list[str] = []
    for path_row in path_rows:
        selected_path_id = path_row.get("path_id")
        effective_cl = path_row.get("effective_cl")
        source_packet_ids = path_row.get("source_packet_ids")
        if (
            not isinstance(selected_path_id, str)
            or not selected_path_id.strip()
            or selected_path_id in path_by_id
            or not isinstance(path_row.get("display_name"), str)
            or not path_row["display_name"].strip()
            or not isinstance(path_row.get("key_ability"), str)
            or not path_row["key_ability"].strip()
            or type(effective_cl) is not int
            or not 1 <= effective_cl <= character_cl
            or not isinstance(source_packet_ids, list)
            or len(source_packet_ids) != 1
            or not isinstance(source_packet_ids[0], str)
            or not source_packet_ids[0].strip()
            or source_packet_ids[0] in path_packet_ids
        ):
            raise invalid("A selected Path row is incomplete, duplicated, or malformed.", details={"path_id": selected_path_id})
        path_by_id[selected_path_id] = path_row
        path_target_cls[selected_path_id] = effective_cl
        path_packet_ids.append(source_packet_ids[0])
    if character_cl != max(path_target_cls.values()):
        raise invalid("The character CL must equal the maximum selected Path target CL.", details={"character_cl": character_cl, "path_target_cls": path_target_cls})

    path_master = _bridge_fixed_json(_PACKET_PATH_MASTER_PATH, _PACKET_PATH_MASTER_SHA256)
    if not isinstance(path_master, Mapping):
        raise invalid("The fixed Path master is unavailable or unsafe.")
    master_rows = path_master.get("paths")
    if not isinstance(master_rows, list):
        raise invalid("The fixed Path master has no canonical path list.")
    master_ids = [row.get("canonical_id") for row in master_rows if isinstance(row, Mapping)]
    if len(master_ids) != len(master_rows) or any(not isinstance(value, str) or not value for value in master_ids) or len(set(master_ids)) != len(master_ids):
        raise invalid("The fixed Path master has malformed or duplicate canonical IDs.")
    master_by_id = {row["canonical_id"]: row for row in master_rows}
    key_ability_names = {
        "STR": "Strength",
        "DEX": "Dexterity",
        "CON": "Constitution",
        "INT": "Intelligence",
        "WIS": "Wisdom",
        "CHA": "Charisma",
    }
    path_context: dict[str, dict[str, Any]] = {}
    for selected_path_id, path_row in path_by_id.items():
        selected_path_name = path_row["display_name"]
        selected_key_ability = path_row["key_ability"]
        proof = _PACKET_PATH_PROOFS.get(selected_path_id)
        path_index = _bridge_fixed_json(proof["index_path"], proof["index_sha256"]) if proof else None
        master_row = master_by_id.get(selected_path_id)
        if not isinstance(proof, Mapping) or not isinstance(path_index, Mapping) or not isinstance(master_row, Mapping):
            raise invalid("A selected Path is not one fixed canonical Path.", details={"path_id": selected_path_id})
        if (
            path_index.get("canonical_id") != selected_path_id
            or path_index.get("display_name") != selected_path_name
            or path_index.get("publication_status") != "current_canonical_player_path"
            or master_row.get("display_name") != selected_path_name
            or master_row.get("index_file") != proof["index_file"]
        ):
            raise invalid("A selected Path identity diverges from the fixed Path master/index.", details={"path_id": selected_path_id})
        index_source = path_index.get("source")
        master_source = master_row.get("source")
        if (
            not isinstance(index_source, Mapping)
            or not isinstance(master_source, Mapping)
            or index_source.get("corpus_path") != proof["corpus_path"]
            or index_source.get("sha256") != proof["corpus_sha256"]
            or master_source.get("corpus_path") != proof["corpus_path"]
            or master_source.get("sha256") != proof["corpus_sha256"]
        ):
            raise invalid("A selected Path source does not match fixed hash-pinned authority.", details={"path_id": selected_path_id})
        path_profile = path_index.get("path_profile")
        master_key_ability = master_row.get("key_ability")
        index_key_ability = path_profile.get("key_ability") if isinstance(path_profile, Mapping) else None
        fixed_options: list[str] = []
        for source in (master_key_ability, index_key_ability):
            options = source.get("options") if isinstance(source, Mapping) else None
            if not isinstance(options, list) or any(not isinstance(option, str) or not option for option in options):
                raise invalid("The fixed Path key-ability authority is malformed.", details={"path_id": selected_path_id})
            if not fixed_options:
                fixed_options = list(options)
            elif options != fixed_options:
                raise invalid("The fixed Path key-ability authorities diverge.", details={"path_id": selected_path_id})
        if key_ability_names.get(selected_key_ability, selected_key_ability) not in fixed_options:
            raise invalid("A selected Path key ability is not legal under fixed authority.", details={"path_id": selected_path_id, "key_ability": selected_key_ability})
        path_context[selected_path_id] = {"proof": proof, "index": path_index, "master": master_row}

    registry = _read_json(registry_path, code="FINAL_CHARACTER_PATH_PROJECTION_INVALID")
    packets = registry.get("packets") if isinstance(registry, Mapping) else None
    if not isinstance(packets, list):
        raise invalid("The modern packet registry has no packet list.")
    packet_by_id: dict[str, Mapping[str, Any]] = {}
    for index, packet in enumerate(packets):
        if not isinstance(packet, Mapping) or not isinstance(packet.get("packet_id"), str) or not packet.get("packet_id").strip():
            raise invalid("A modern packet has no stable packet ID.", details={"index": index})
        packet_id = packet["packet_id"]
        if packet_id in packet_by_id:
            raise invalid("The modern packet registry contains duplicate packet IDs.", details={"packet_id": packet_id})
        packet_by_id[packet_id] = packet

    def packet_evidence(
        packet_id: str,
        *,
        record_id: str,
        display_name: str,
        target_cl: int,
        anchor: str,
        proof: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        packet = packet_by_id.get(packet_id)
        evidence = packet.get("source_evidence") if isinstance(packet, Mapping) else None
        evidence_row = evidence[0] if isinstance(evidence, list) and len(evidence) == 1 and isinstance(evidence[0], Mapping) else None
        if (
            packet is None
            or packet.get("record_id") != record_id
            or packet.get("display_name") != display_name
            or type(packet.get("target_cl")) is not int
            or packet.get("target_cl") != target_cl
            or evidence_row is None
            or evidence_row.get("source_path") != proof["index_path"]
            or evidence_row.get("source_hash") != proof["index_sha256"]
            or evidence_row.get("source_anchor") != anchor
        ):
            raise invalid(
                "A Path source packet is not the exact fixed Path event binding.",
                details={"packet_id": packet_id, "record_id": record_id, "target_cl": target_cl},
            )
        return packet

    for selected_path_id, path_row in path_by_id.items():
        packet_evidence(
            path_row["source_packet_ids"][0],
            record_id=selected_path_id,
            display_name=path_row["display_name"],
            target_cl=1,
            anchor=f"path:{selected_path_id}",
            proof=path_context[selected_path_id]["proof"],
        )

    feature_by_id: dict[str, tuple[str, Mapping[str, Any]]] = {}
    feature_ids_by_path: dict[str, list[str]] = {}
    for selected_path_id, context in path_context.items():
        feature_rows = context["index"].get("features")
        if not isinstance(feature_rows, list):
            raise invalid("The fixed Path index has no feature authority list.", details={"path_id": selected_path_id})
        feature_ids = [row.get("canonical_id") for row in feature_rows if isinstance(row, Mapping)]
        if len(feature_ids) != len(feature_rows) or any(not isinstance(value, str) or not value for value in feature_ids) or len(set(feature_ids)) != len(feature_ids):
            raise invalid("The fixed Path feature authority is malformed or duplicated.", details={"path_id": selected_path_id})
        feature_ids_by_path[selected_path_id] = feature_ids
        for feature in feature_rows:
            feature_id = feature["canonical_id"]
            if not feature_id.startswith(selected_path_id + ".feature.") or feature_id in feature_by_id:
                raise invalid("A fixed Path feature has ambiguous Path ownership.", details={"feature_id": feature_id})
            feature_by_id[feature_id] = (selected_path_id, feature)
    # A packet registry may contain non-Path and non-feature records, so only
    # packets that are the canonical level/path-feature event shape for a
    # selected Path participate in this reverse-direction check.  The
    # historical public bridge omitted ``advancement_kind``; retain that
    # compatibility while still treating explicit level/path-feature packets
    # as sealed event records.
    feature_packet_candidates: set[str] = set()
    accepted_feature_packet_kinds = {None, "level_advance", "path_feature_acquisition"}
    for packet_id, packet in packet_by_id.items():
        packet_record_id = packet.get("record_id")
        feature_binding = feature_by_id.get(packet_record_id) if isinstance(packet_record_id, str) else None
        if feature_binding is None or packet.get("advancement_kind") not in accepted_feature_packet_kinds:
            continue
        selected_path_id, fixed_feature = feature_binding
        target_cl = packet.get("target_cl")
        grants = fixed_feature.get("granted_at_cl")
        if (
            not isinstance(grants, list)
            or any(type(grant) is not int for grant in grants)
            or type(target_cl) is not int
        ):
            raise invalid(
                "A selected Path feature packet has malformed grant metadata.",
                details={"packet_id": packet_id, "feature_id": packet.get("record_id")},
            )
        if target_cl > path_target_cls[selected_path_id]:
            continue
        if target_cl not in grants:
            raise invalid(
                "A selected Path feature packet targets a non-grant level.",
                details={"packet_id": packet_id, "feature_id": packet.get("record_id"), "target_cl": target_cl},
            )
        packet_evidence(
            packet_id,
            record_id=packet_record_id,
            display_name=fixed_feature["display_name"],
            target_cl=target_cl,
            anchor=f"path-feature:{selected_path_id}:{packet_record_id}",
            proof=path_context[selected_path_id]["proof"],
        )
        feature_packet_candidates.add(packet_id)
    ledger_features = ledger.get("features")
    if not isinstance(ledger_features, list):
        raise invalid("The modern ledger has no feature event list.")

    seen_allocations: set[str] = set()
    seen_event_ids: set[tuple[str, int, str]] = set()
    seen_feature_cl: set[tuple[str, int]] = set()
    seen_packet_ids: set[str] = set(path_packet_ids)
    path_occurrences: list[tuple[int, str, dict[str, Any]]] = []
    seen_level_events: dict[str, tuple[str, int, str]] = {}
    for index, row in enumerate(ledger_features):
        if not isinstance(row, Mapping) or row.get("category") != "path_feature":
            continue
        value = dict(row)
        feature_id = value.get("feature_id")
        feature_name = value.get("name")
        gained_at_cl = value.get("gained_at_cl")
        allocation_id = value.get("allocation_id")
        event_packet_ids = value.get("source_packet_ids")
        if (
            not isinstance(feature_id, str)
            or not feature_id.strip()
            or not isinstance(feature_name, str)
            or not feature_name.strip()
            or type(gained_at_cl) is not int
            or not isinstance(allocation_id, str)
            or not allocation_id.strip()
            or not isinstance(event_packet_ids, list)
            or len(event_packet_ids) != 1
            or not isinstance(event_packet_ids[0], str)
            or not event_packet_ids[0].strip()
        ):
            raise invalid("A modern Path feature event is incomplete, malformed, or cross-Path.", details={"index": index, "feature_id": feature_id})
        feature_binding = feature_by_id.get(feature_id)
        selected_path_id, fixed_feature = feature_binding if feature_binding is not None else (None, None)
        target_cl = path_target_cls.get(selected_path_id) if selected_path_id is not None else None
        grants = fixed_feature.get("granted_at_cl") if isinstance(fixed_feature, Mapping) else None
        if (
            not isinstance(fixed_feature, Mapping)
            or fixed_feature.get("display_name") != feature_name
            or not isinstance(grants, list)
            or any(type(grant) is not int for grant in grants)
            or target_cl is None
            or not 1 <= gained_at_cl <= target_cl
            or gained_at_cl not in grants
        ):
            raise invalid(
                "A modern Path feature event does not match the fixed feature authority.",
                details={"feature_id": feature_id, "gained_at_cl": gained_at_cl, "path_id": selected_path_id, "target_cl": target_cl},
            )
        packet_id = event_packet_ids[0]
        packet = packet_by_id.get(packet_id)
        packet_record_id = packet.get("record_id") if isinstance(packet, Mapping) else None
        if packet_record_id == feature_id:
            packet_evidence(
                packet_id,
                record_id=feature_id,
                display_name=feature_name,
                target_cl=gained_at_cl,
                anchor=f"path-feature:{selected_path_id}:{feature_id}",
                proof=path_context[selected_path_id]["proof"],
            )
        else:
            # A Path level that grants several features is one level event:
            # every feature it grants cites that level's own packet, which
            # names one of the features granted at exactly this CL.
            level_binding = feature_by_id.get(packet_record_id) if isinstance(packet_record_id, str) else None
            level_feature = level_binding[1] if level_binding is not None and level_binding[0] == selected_path_id else None
            level_grants = level_feature.get("granted_at_cl") if isinstance(level_feature, Mapping) else None
            if not isinstance(level_grants, list) or gained_at_cl not in level_grants:
                raise invalid(
                    "A Path source packet is not the exact fixed Path event binding.",
                    details={"packet_id": packet_id, "record_id": feature_id, "target_cl": gained_at_cl},
                )
            packet_evidence(
                packet_id,
                record_id=packet_record_id,
                display_name=level_feature["display_name"],
                target_cl=gained_at_cl,
                anchor=f"path-feature:{selected_path_id}:{packet_record_id}",
                proof=path_context[selected_path_id]["proof"],
            )
        event_id = (feature_id, gained_at_cl, packet_id)
        feature_cl = (feature_id, gained_at_cl)
        level_event = (selected_path_id, gained_at_cl, packet_id)
        if (
            event_id in seen_event_ids
            or feature_cl in seen_feature_cl
            or allocation_id in seen_allocations
            or (packet_id in seen_packet_ids and seen_level_events.get(packet_id) != level_event)
        ):
            raise invalid("The modern Path feature event identity is duplicated.", details={"feature_id": feature_id, "gained_at_cl": gained_at_cl, "packet_id": packet_id})
        seen_level_events[packet_id] = level_event
        seen_allocations.add(allocation_id)
        seen_event_ids.add(event_id)
        seen_feature_cl.add(feature_cl)
        seen_packet_ids.add(packet_id)
        path_occurrences.append((index, selected_path_id, value))

    referenced_feature_packet_ids = seen_packet_ids - set(path_packet_ids)
    unreferenced_feature_packet_ids = sorted(feature_packet_candidates - referenced_feature_packet_ids)
    if unreferenced_feature_packet_ids:
        raise invalid(
            "The selected Path feature packet registry is not fully represented by ledger events.",
            details={"unreferenced_packet_ids": unreferenced_feature_packet_ids},
        )
    paths_with_features = {selected_path_id for _index, selected_path_id, _row in path_occurrences}
    missing_path_ids = [selected_path_id for selected_path_id in path_by_id if selected_path_id not in paths_with_features]
    if missing_path_ids:
        raise invalid(
            "The modern ledger is missing source-backed Path feature events.",
            details={"path_ids": missing_path_ids},
        )

    earliest_by_feature: dict[str, tuple[int, dict[str, Any]]] = {}
    for index, _selected_path_id, row in path_occurrences:
        feature_id = row["feature_id"]
        prior = earliest_by_feature.get(feature_id)
        candidate = (row["gained_at_cl"], index)
        if prior is None or candidate < (prior[1]["gained_at_cl"], prior[0]):
            earliest_by_feature[feature_id] = (index, row)
    retained_indexes = {index for index, _row in earliest_by_feature.values()}
    retained_rows = [deepcopy(row) for index, _selected_path_id, row in path_occurrences if index in retained_indexes]
    removed_rows = [deepcopy(row) for index, _selected_path_id, row in path_occurrences if index not in retained_indexes]
    removed_indexes = {index for index, _selected_path_id, _row in path_occurrences if index not in retained_indexes}
    projected_features = [
        deepcopy(row)
        for index, row in enumerate(ledger_features)
        if index not in removed_indexes
    ]
    projected_feature_ids = [row["feature_id"] for row in retained_rows]
    projected_feature_ids_by_path: dict[str, list[str]] = {selected_path_id: [] for selected_path_id in path_by_id}
    for index, selected_path_id, row in path_occurrences:
        if index in retained_indexes:
            projected_feature_ids_by_path[selected_path_id].append(row["feature_id"])
    existing_packet_ids = character.get("path_source_packet_ids")
    if "path_source_packet_ids" in character and existing_packet_ids != path_packet_ids:
        raise invalid("The existing flat Path packet projection disagrees with the sealed Path row.")
    existing_feature_ids = character.get("path_feature_ids_expected")
    if "path_feature_ids_expected" in character and existing_feature_ids != projected_feature_ids:
        raise invalid("The existing flat Path feature projection disagrees with source-backed events.")

    projected_ledger = deepcopy(dict(ledger))
    projected_character = deepcopy(dict(character))
    projected_character["path_source_packet_ids"] = path_packet_ids
    projected_character["path_feature_ids_expected"] = projected_feature_ids
    projected_ledger["character"] = projected_character
    projected_ledger["features"] = projected_features
    provenance = {
        "schema_version": "TianxiaFoundry.FinalCharacterPathProjectionProvenance.v1",
        "source_ledger_path": "Build/Character_Master_Ledger.json",
        "source_ledger_sha256": hashlib.sha256(raw_ledger_bytes).hexdigest(),
        "original_ledger_sha256": hashlib.sha256(raw_ledger_bytes).hexdigest(),
        "path_id": path_id,
        "path_name": path_name,
        "effective_cl": path_target_cls[path_id],
        "path_source_packet_ids": path_packet_ids,
        "projected_path_feature_ids": projected_feature_ids,
        "retained_occurrences": retained_rows,
        "deduplicated_occurrences": removed_rows,
        "removed_occurrences": removed_rows,
    }
    if len(path_by_id) > 1:
        provenance.update(
            {
                "path_ids": list(path_by_id),
                "path_target_cls": dict(path_target_cls),
                "path_source_packet_bindings": [
                    {
                        "path_id": selected_path_id,
                        "packet_id": path_row["source_packet_ids"][0],
                        "target_cl": 1,
                    }
                    for selected_path_id, path_row in path_by_id.items()
                ],
                "path_feature_ids_by_path": projected_feature_ids_by_path,
                "path_feature_occurrences": [
                    {
                        "path_id": selected_path_id,
                        "row": deepcopy(row),
                    }
                    for _index, selected_path_id, row in path_occurrences
                ],
            }
        )
    raw_provenance_path = root / _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    details_path = root / _PATH_PROJECTION_DETAILS_RELATIVE
    if raw_provenance_path.exists() or details_path.exists():
        raise invalid("The copied workspace already contains Path projection provenance.")
    _atomic_write_bytes(raw_provenance_path, raw_ledger_bytes)
    _write_json(details_path, provenance)
    _write_json(ledger_path, projected_ledger)
    reread = _read_json(ledger_path, code="FINAL_CHARACTER_PATH_PROJECTION_INVALID")
    if reread != projected_ledger or raw_provenance_path.read_bytes() != raw_ledger_bytes:
        raise invalid("The compiler Path projection could not be read back exactly.")
    projection = {
        "schema_version": provenance["schema_version"],
        "source_ledger_path": "Build/Character_Master_Ledger.json",
        "source_ledger_sha256": provenance["source_ledger_sha256"],
        "original_ledger_sha256": provenance["original_ledger_sha256"],
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": sha256_file(raw_provenance_path),
        "details_path": _PATH_PROJECTION_DETAILS_RELATIVE,
        "details_sha256": sha256_file(details_path),
        "path_id": path_id,
        "path_source_packet_ids": path_packet_ids,
        "path_feature_ids_expected": projected_feature_ids,
        "retained_occurrence_count": len(retained_rows),
        "deduplicated_occurrence_count": len(removed_rows),
    }
    if len(path_by_id) > 1:
        projection.update(
            {
                "path_ids": list(path_by_id),
                "path_target_cls": dict(path_target_cls),
                "path_source_packet_bindings": provenance["path_source_packet_bindings"],
                "path_feature_ids_by_path": projected_feature_ids_by_path,
                "path_feature_occurrence_count": len(path_occurrences),
            }
        )
    return projection


def _selected_path_rows_for_compiler_consumer(
    *,
    raw_ledger: Mapping[str, Any],
    ledger: Mapping[str, Any],
    path_projection: Mapping[str, Any] | None,
    path_details: Mapping[str, Any],
    primary_path_id: str,
    primary_path_name: str,
    character_cl: int,
    invalid: Any,
) -> tuple[list[Mapping[str, Any]], list[str]]:
    """Bind a downstream stat consumer to the complete authenticated Path set.

    The pinned compiler still has one flat primary Path field.  Modern source
    rows may contain several independently targeted Paths, however, so each
    consumer must carry the complete selected set through its seam instead of
    reinterpreting it as a one-row ledger.  Path/index/packet authority is
    established by :func:`_project_modern_path_fields_for_compiler`; this
    helper rechecks the row/projection identity before a consumer derives its
    own statistic.
    """

    raw_character = raw_ledger.get("character")
    character = ledger.get("character")
    raw_path_rows = raw_character.get("paths") if isinstance(raw_character, Mapping) else None
    raw_selection_rows = raw_ledger.get("path_selections")
    current_path_rows = character.get("paths") if isinstance(character, Mapping) else None
    current_selection_rows = ledger.get("path_selections")
    binding_fields = ("path_id", "display_name", "key_ability", "effective_cl", "source_packet_ids")
    if (
        not isinstance(raw_path_rows, list)
        or not raw_path_rows
        or not isinstance(raw_selection_rows, list)
        or len(raw_path_rows) != len(raw_selection_rows)
        or any(not isinstance(row, Mapping) for row in [*raw_path_rows, *raw_selection_rows])
        or not isinstance(current_path_rows, list)
        or not isinstance(current_selection_rows, list)
        or current_path_rows != raw_path_rows
        or current_selection_rows != raw_selection_rows
    ):
        raise invalid("The selected Path rows are missing or diverge from raw provenance.")
    if any(
        any(path_row.get(field) != selection_row.get(field) for field in binding_fields)
        for path_row, selection_row in zip(raw_path_rows, raw_selection_rows)
    ):
        raise invalid("The selected Path and Path-selection rows diverge.")

    selected_ids: list[str] = []
    selected_packet_ids: list[str] = []
    for row in raw_path_rows:
        path_id = row.get("path_id")
        packet_ids = row.get("source_packet_ids")
        if (
            not isinstance(path_id, str)
            or not path_id.strip()
            or path_id in selected_ids
            or not isinstance(row.get("display_name"), str)
            or not row.get("display_name").strip()
            or not isinstance(row.get("key_ability"), str)
            or not row.get("key_ability").strip()
            or type(row.get("effective_cl")) is not int
            or not 1 <= row.get("effective_cl") <= character_cl
            or not isinstance(packet_ids, list)
            or len(packet_ids) != 1
            or not isinstance(packet_ids[0], str)
            or not packet_ids[0].strip()
            or packet_ids[0] in selected_packet_ids
        ):
            raise invalid("A selected Path row is incomplete, duplicated, or malformed.", details={"path_id": path_id})
        selected_ids.append(path_id)
        selected_packet_ids.append(packet_ids[0])

    primary = raw_path_rows[0]
    if (
        primary.get("path_id") != primary_path_id
        or primary.get("display_name") != primary_path_name
        or character_cl != max(row.get("effective_cl") for row in raw_path_rows)
    ):
        raise invalid("The primary Path or character CL is not bound to the selected Path set.")

    projected_ids: Any
    projected_packets: Any
    if isinstance(path_projection, Mapping):
        projected_ids = path_projection.get("path_ids")
        if not isinstance(projected_ids, list):
            projected_ids = [path_projection.get("path_id")]
        projected_packets = path_projection.get("path_source_packet_ids")
    else:
        projected_ids = path_details.get("path_ids")
        if not isinstance(projected_ids, list):
            projected_ids = [path_details.get("path_id")]
        projected_packets = path_details.get("path_source_packet_ids")
    detail_ids = path_details.get("path_ids")
    if not isinstance(detail_ids, list):
        detail_ids = [path_details.get("path_id")]
    if (
        projected_ids != selected_ids
        or detail_ids != selected_ids
        or projected_packets != selected_packet_ids
    ):
        raise invalid("The downstream consumer is not bound to every authenticated Path packet.")
    return [row for row in raw_path_rows if isinstance(row, Mapping)], selected_packet_ids

def _project_method_for_compiler_fixed(
    workspace: Path,
    *,
    path_projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project the selected Method into the pinned compiler's legacy shape.

    The Stage-2 Method row is intentionally a source-selection record.  The
    compiler still requires the older, richer Method surface, so this bridge
    derives that surface only from the fixed METHOD-001 registry record, its
    hash-pinned source section, the fixed active Path authority, and one exact
    modern selection packet.  The modern row is retained byte-for-byte in its
    provenance file and the Method profile is updated with the same projected
    row as the compiler ledger.
    """

    def invalid(message: str, *, details: Any = None) -> FoundryError:
        return _error("FINAL_CHARACTER_METHOD_PROJECTION_INVALID", message, details=details)

    root = Path(workspace)
    ledger_path = root / "Build/Character_Master_Ledger.json"
    raw_provenance_path = root / _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    profile_path = root / "Build/Cultivation_Method_Profile.json"
    registry_path = root / "Command_2/Rules_Selection_Packets.json"
    build_registry_path = root / "Build/Rules_Selection_Packets.json"
    details_path = root / _METHOD_PROJECTION_DETAILS_RELATIVE
    for path in (ledger_path, raw_provenance_path, profile_path, registry_path):
        if path.is_symlink() or not path.is_file():
            raise invalid("The copied Method projection inputs are missing or unsafe.", details={"path": str(path)})
    if details_path.is_symlink() or details_path.exists():
        raise invalid("The copied workspace already contains Method projection provenance.")
    if build_registry_path.is_symlink() or (build_registry_path.exists() and not build_registry_path.is_file()):
        raise invalid("The copied Build packet registry is unsafe.", details={"path": str(build_registry_path)})

    try:
        raw_provenance_bytes = raw_provenance_path.read_bytes()
        raw_provenance_sha256 = hashlib.sha256(raw_provenance_bytes).hexdigest()
        raw_ledger = _read_json(raw_provenance_path, code="FINAL_CHARACTER_METHOD_PROJECTION_INVALID")
        ledger = _read_json(ledger_path, code="FINAL_CHARACTER_METHOD_PROJECTION_INVALID")
        profile = _read_json(profile_path, code="FINAL_CHARACTER_METHOD_PROJECTION_INVALID")
        registry = _read_json(registry_path, code="FINAL_CHARACTER_METHOD_PROJECTION_INVALID")
        build_registry = (
            _read_json(build_registry_path, code="FINAL_CHARACTER_METHOD_PROJECTION_INVALID")
            if build_registry_path.exists()
            else None
        )
    except (OSError, FoundryError) as exc:
        if isinstance(exc, FoundryError):
            raise invalid("The copied Method projection inputs could not be read.", details={"cause": exc.code}) from exc
        raise invalid("The copied Method projection inputs could not be read.") from exc
    if not all(isinstance(value, Mapping) for value in (raw_ledger, ledger, profile, registry)):
        raise invalid("The copied Method projection inputs must be mappings.")
    if profile.get("schema_version") != "TianxiaFoundry.CharacterGMMethod.v1":
        raise invalid("The copied Method profile has an unsupported schema.")
    if build_registry is not None and build_registry != registry:
        raise invalid("The Build and Command 2 packet registries diverge.")
    packets = registry.get("packets")
    if registry.get("schema_version") != "TianxiaFoundry.RulesSelectionPackets.v2" or not isinstance(packets, list):
        raise invalid("The copied packet registry is not the sealed modern schema.")
    packet_by_id: dict[str, Mapping[str, Any]] = {}
    for index, packet in enumerate(packets):
        if not isinstance(packet, Mapping) or not isinstance(packet.get("packet_id"), str) or not packet.get("packet_id").strip():
            raise invalid("A Method packet has no stable packet ID.", details={"index": index})
        packet_id = packet["packet_id"]
        if packet_id in packet_by_id:
            raise invalid("The Method packet registry contains duplicate packet IDs.", details={"packet_id": packet_id})
        packet_by_id[packet_id] = packet

    raw_method = raw_ledger.get("method")
    current_method = ledger.get("method")
    profile_method = profile.get("method")
    if not all(isinstance(value, Mapping) for value in (raw_method, current_method, profile_method)):
        raise invalid("The copied Method rows are missing or not mappings.")
    raw_character = raw_ledger.get("character")
    current_character = ledger.get("character")
    if not isinstance(raw_character, Mapping) or not isinstance(current_character, Mapping):
        raise invalid("The copied Method has no active character Path binding.")
    path_id = raw_character.get("path_id")
    path_name = raw_character.get("path")
    character_cl = raw_character.get("cl")
    if (
        not isinstance(path_id, str)
        or not path_id.strip()
        or not isinstance(path_name, str)
        or not path_name.strip()
        or type(character_cl) is not int
        or not 1 <= character_cl <= 20
        or current_character.get("path_id") != path_id
        or current_character.get("path") != path_name
        or current_character.get("cl") != character_cl
    ):
        raise invalid("The active Method Path binding is incomplete or divergent.")
    if path_projection is not None:
        if not isinstance(path_projection, Mapping) or path_projection.get("path_id") != path_id:
            raise invalid("The Method is not bound to the authenticated Path projection.")

    source_packet_ids = raw_method.get("source_packet_ids")
    if (
        not isinstance(source_packet_ids, list)
        or len(source_packet_ids) != 1
        or not isinstance(source_packet_ids[0], str)
        or not source_packet_ids[0].strip()
    ):
        raise invalid("The selected Method does not bind one exact source packet.")
    method_packet_id = source_packet_ids[0]
    for label, row in (("copied", current_method), ("profile", profile_method)):
        if row.get("source_packet_ids") != source_packet_ids:
            raise invalid("The copied Method source packet binding diverges.", details={"label": label})
    if current_method.get("event_id") != raw_method.get("event_id") or profile_method.get("event_id") != raw_method.get("event_id"):
        raise invalid("The copied Method event binding diverges from modern provenance.")
    if current_method.get("record_id") != raw_method.get("record_id") or profile_method.get("record_id") != raw_method.get("record_id"):
        raise invalid("The copied Method identity diverges from modern provenance.")
    if current_method.get("display_name") != raw_method.get("display_name") or profile_method.get("display_name") != raw_method.get("display_name"):
        raise invalid("The copied Method display name diverges from modern provenance.")
    if any(
        not isinstance(raw_method.get(field), str) or not raw_method.get(field).strip()
        for field in ("record_id", "display_name", "event_id", "record_hash")
    ):
        raise invalid("The selected Method identity is incomplete.")

    fixed_registry = _bridge_fixed_json(_PACKET_METHOD_SOURCE_PATH, _PACKET_METHOD_SOURCE_SHA256)
    fixed_rows = fixed_registry.get("methods") if isinstance(fixed_registry, Mapping) else None
    if not isinstance(fixed_rows, list):
        raise invalid("The fixed Method authority is unavailable or malformed.")
    fixed_ids = [row.get("method_id") for row in fixed_rows if isinstance(row, Mapping)]
    if (
        len(fixed_ids) != len(fixed_rows)
        or any(not isinstance(value, str) or not value.strip() for value in fixed_ids)
        or len(set(fixed_ids)) != len(fixed_ids)
    ):
        raise invalid("The fixed Method authority has malformed or duplicate IDs.")
    fixed_matches = [row for row in fixed_rows if isinstance(row, Mapping) and row.get("method_id") == _METHOD_ID]
    if len(fixed_matches) != 1 or fixed_matches[0].get("name") != _METHOD_NAME:
        raise invalid("The selected Method is not the unique fixed METHOD-001 authority.")
    fixed_method = fixed_matches[0]
    if raw_method.get("record_id") != _METHOD_ID or raw_method.get("display_name") != _METHOD_NAME:
        raise invalid("The selected Method identity is not the fixed METHOD-001 record.")

    method_packet = packet_by_id.get(method_packet_id)
    evidence = method_packet.get("source_evidence") if isinstance(method_packet, Mapping) else None
    evidence_row = evidence[0] if isinstance(evidence, list) and len(evidence) == 1 and isinstance(evidence[0], Mapping) else None
    content_binding = method_packet.get("content_binding") if isinstance(method_packet, Mapping) else None
    if (
        method_packet is None
        or method_packet.get("record_id") != _METHOD_ID
        or method_packet.get("display_name") != _METHOD_NAME
        or method_packet.get("advancement_kind") != "method_acquisition"
        or type(method_packet.get("target_cl")) is not int
        or method_packet.get("target_cl") != 1
        or method_packet.get("event_id") != raw_method.get("event_id")
        or method_packet.get("record_hash") != raw_method.get("record_hash")
        or not isinstance(content_binding, Mapping)
        or content_binding.get("record_hash") != raw_method.get("record_hash")
        or not isinstance(evidence_row, Mapping)
        or evidence_row.get("source_path") != _PACKET_METHOD_SOURCE_PATH
        or evidence_row.get("source_hash") != _PACKET_METHOD_SOURCE_SHA256
        or evidence_row.get("source_anchor") != f"method:{_METHOD_ID}"
    ):
        raise invalid("The selected Method packet is not the exact hash-pinned event binding.", details={"packet_id": method_packet_id})
    fixed_source_text = fixed_method.get("source_text")
    fixed_owner_readable = fixed_method.get("owner_readable")
    fixed_resources = fixed_method.get("per_path_resource_profiles")
    fixed_breakthroughs = fixed_method.get("per_path_breakthrough_profiles")
    fixed_grants = fixed_method.get("explicit_ap_grants")
    risks = fixed_method.get("risks_limitations")
    secondary_tags = fixed_method.get("secondary_form_tags")
    if (
        not isinstance(fixed_source_text, Mapping)
        or not isinstance(fixed_owner_readable, Mapping)
        or not isinstance(fixed_resources, list)
        or not isinstance(fixed_breakthroughs, list)
        or not isinstance(fixed_grants, list)
        or not isinstance(risks, list)
        or not risks
        or not isinstance(secondary_tags, list)
        or not secondary_tags
    ):
        raise invalid("The fixed Method compiler inputs are incomplete.")

    proof = _PACKET_PATH_PROOFS.get(path_id)
    path_index = _bridge_fixed_json(proof["index_path"], proof["index_sha256"]) if proof else None
    path_master = _bridge_fixed_json(_PACKET_PATH_MASTER_PATH, _PACKET_PATH_MASTER_SHA256) if proof else None
    master_rows = path_master.get("paths") if isinstance(path_master, Mapping) else None
    master_matches = [row for row in master_rows if isinstance(row, Mapping) and row.get("canonical_id") == path_id] if isinstance(master_rows, list) else []
    resource_rules = path_index.get("resource_rules") if isinstance(path_index, Mapping) else None
    if (
        proof is None
        or not isinstance(path_index, Mapping)
        or not isinstance(path_master, Mapping)
        or path_index.get("canonical_id") != path_id
        or path_index.get("display_name") != path_name
        or len(master_matches) != 1
        or master_matches[0].get("display_name") != path_name
        or not isinstance(resource_rules, Mapping)
        or not isinstance(resource_rules.get("name"), str)
        or not resource_rules.get("name").strip()
        or not isinstance(resource_rules.get("maximum_formula"), str)
        or not resource_rules.get("maximum_formula").strip()
    ):
        raise invalid("The active Method Path is not bound to fixed Path authority.", details={"path_id": path_id})
    resource_profile_matches = [
        row for row in fixed_resources
        if isinstance(row, Mapping) and row.get("path_id") == "QI_CULTIVATION"
    ]
    breakthrough_matches = [
        row for row in fixed_breakthroughs
        if isinstance(row, Mapping) and row.get("path_id") == "QI_CULTIVATION"
    ]
    grant_matches = [
        row for row in fixed_grants
        if isinstance(row, Mapping) and row.get("path_id") == "QI_CULTIVATION" and row.get("grants_attainment_points") is True
    ]
    if (
        path_id != "tianxia.path.qi_cultivation"
        or len(resource_profile_matches) != 1
        or len(breakthrough_matches) != 1
        or len(grant_matches) != 1
        or resource_profile_matches[0].get("resource_id") != resource_rules.get("canonical_id")
        or resource_profile_matches[0].get("resource_name") != resource_rules.get("name")
        or resource_profile_matches[0].get("source_text") != fixed_source_text.get("resource_shape")
        or breakthrough_matches[0].get("source_text") != fixed_source_text.get("breakthrough_shape")
        or grant_matches[0].get("routing_mode") != "EXCLUSIVE"
    ):
        raise invalid("The selected Method has no exact active-Path resource/AP authority.")

    source_master_path = _FINAL_CHARACTER_BASE_FACTORY_ROOT / _METHOD_SOURCE_MASTER_PATH
    try:
        if source_master_path.is_symlink() or not source_master_path.is_file() or sha256_file(source_master_path) != _METHOD_SOURCE_MASTER_SHA256:
            raise invalid("The fixed Method source master is unavailable or changed.", details={"path": str(source_master_path)})
        source_master_text = source_master_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise invalid("The fixed Method source master could not be read.", details={"path": str(source_master_path)}) from exc
    source_lines = source_master_text.splitlines()
    heading_matches = [
        index for index, line in enumerate(source_lines)
        if line.strip() == "## 1. Outer Gate Root Method"
    ]
    if len(heading_matches) != 1:
        raise invalid("The fixed Method source heading is missing or ambiguous.")
    heading_index = heading_matches[0]
    section_end = next(
        (index for index in range(heading_index + 1, len(source_lines)) if re.match(r"^##\s+\S", source_lines[index].strip())),
        len(source_lines),
    )
    section = "\n".join(source_lines[heading_index:section_end])

    def source_label(label: str) -> str | None:
        prefix = f"**{label}:**"
        matches = [line.strip()[len(prefix):].strip() for line in section.splitlines() if line.strip().startswith(prefix)]
        return matches[0] if len(matches) == 1 and matches[0] else None

    source_common_users = source_label("Common Users")
    source_themes = source_label("Compatible Themes")
    source_resource = source_label("Resource Shape")
    source_breakthrough = source_label("Breakthrough Shape")
    source_foundation = source_label("Foundation Shape")
    source_type = source_label("Type")
    use_as_prefix = "**Use As:**"
    use_as_matches = [line.strip()[len(use_as_prefix):].strip() for line in section.splitlines() if line.strip().startswith(use_as_prefix)]
    description = fixed_source_text.get("description")
    compatible_themes = fixed_source_text.get("compatible_themes")
    if (
        source_type != fixed_source_text.get("type")
        or source_common_users != fixed_source_text.get("common_users")
        or source_themes != fixed_source_text.get("compatible_themes_text")
        or source_resource != fixed_source_text.get("resource_shape")
        or source_breakthrough != fixed_source_text.get("breakthrough_shape")
        or source_foundation != fixed_source_text.get("foundation_shape")
        or not isinstance(description, str)
        or section.count(description) != 1
        or len(use_as_matches) != 1
        or use_as_matches[0] != fixed_source_text.get("use_as")
        or not isinstance(compatible_themes, list)
        or ", ".join(compatible_themes) != source_themes
    ):
        raise invalid("The Method source master does not match the fixed typed authority.")
    packet_short_description = method_packet.get("short_description")
    if (
        method_packet.get("full_description") != description
        or not isinstance(packet_short_description, str)
        or packet_short_description not in {description, fixed_source_text.get("short_description")}
    ):
        raise invalid("The selected Method packet description conflicts with fixed source authority.")
    stacking_matches = [
        line.strip().removeprefix("- ").replace("**", "")
        for line in source_lines
        if line.strip().startswith("- A character may know multiple Methods, but only one Method is the character's")
    ]
    if len(stacking_matches) != 1:
        raise invalid("The fixed Method source has no unique stacking rule.")

    expected_generated = {
        "method_id": _METHOD_ID,
        "allocation_id": f"allocation.method.{method_packet_id}",
        "name": _METHOD_NAME,
        "role": f"Primary {resource_rules['name']} cultivation method",
        "resource_name": resource_rules["name"],
        "resource_formula": resource_rules["maximum_formula"],
        "gained_at_cl": method_packet["target_cl"],
        "benefits": [
            fixed_owner_readable.get("resource_summary"),
            fixed_owner_readable.get("ap_route_summary"),
        ],
        "drawbacks": deepcopy(list(risks)),
        "mechanical_hooks": deepcopy(list(secondary_tags)),
        "source_packet_ids": deepcopy(source_packet_ids),
        "applied_math": [
            resource_rules["maximum_formula"],
            resource_profile_matches[0]["source_text"],
        ],
        "stacking_statement": stacking_matches[0],
        "resource_modifiers": [],
        "breakthrough_shape": fixed_source_text["breakthrough_shape"],
        "foundation_compatibility": [fixed_source_text["foundation_shape"]],
        "incompatibilities": deepcopy(list(risks)),
    }
    if any(not isinstance(value, str) or not value.strip() for value in expected_generated["benefits"]):
        raise invalid("The fixed Method benefit authority is incomplete.")
    # ``source_packet_ids`` is already part of the modern selection row; it
    # is required for compiler packet references but is not itself a
    # compiler-only projection field.  A source row carrying only that field
    # is therefore complete, while any partial set of the remaining fields is
    # rejected below.
    compiler_fields = set(expected_generated) - {"source_packet_ids"}

    def validate_existing_projection(row: Mapping[str, Any], *, label: str) -> None:
        present = compiler_fields.intersection(row)
        if present and present != compiler_fields:
            raise invalid("An existing Method compiler projection is partial.", details={"label": label, "fields": sorted(present)})
        for field in present:
            if row.get(field) != expected_generated[field]:
                raise invalid("An existing Method compiler projection conflicts with fixed authority.", details={"label": label, "field": field})

    for label, row in (("raw", raw_method), ("copied", current_method), ("profile", profile_method)):
        validate_existing_projection(row, label=label)
    raw_binding = deepcopy(dict(raw_method))
    current_binding = deepcopy(dict(current_method))
    profile_binding = deepcopy(dict(profile_method))
    for value in (raw_binding, current_binding, profile_binding):
        for field in compiler_fields:
            value.pop(field, None)
    if current_binding != raw_binding or profile_binding != raw_binding:
        raise invalid("The copied Method master/profile surfaces diverge from raw modern provenance.")

    projected_method = deepcopy(dict(current_method))
    projected_method.update(deepcopy(expected_generated))
    projected_ledger = deepcopy(dict(ledger))
    projected_ledger["method"] = projected_method
    projected_profile = deepcopy(dict(profile))
    projected_profile["method"] = deepcopy(projected_method)
    provenance = {
        "schema_version": "TianxiaFoundry.FinalCharacterMethodProjectionProvenance.v1",
        "source_ledger_path": "Build/Character_Master_Ledger.json",
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_provenance_sha256,
        "packet_registry_path": "Command_2/Rules_Selection_Packets.json",
        "packet_registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
        "method_id": _METHOD_ID,
        "method_name": _METHOD_NAME,
        "method_packet_id": method_packet_id,
        "method_authority_path": _PACKET_METHOD_SOURCE_PATH,
        "method_authority_sha256": _PACKET_METHOD_SOURCE_SHA256,
        "method_authority_anchor": f"method:{_METHOD_ID}",
        "method_source_master_path": _METHOD_SOURCE_MASTER_PATH,
        "method_source_master_sha256": _METHOD_SOURCE_MASTER_SHA256,
        "method_source_master_anchor": _METHOD_SOURCE_MASTER_ANCHOR,
        "path_id": path_id,
        "path_name": path_name,
        "path_index_path": proof["index_path"],
        "path_index_sha256": proof["index_sha256"],
        "resource_name": resource_rules["name"],
        "resource_formula": resource_rules["maximum_formula"],
        "projected_method": deepcopy(projected_method),
    }
    _write_json(details_path, provenance)
    _write_json(ledger_path, projected_ledger)
    _write_json(profile_path, projected_profile)
    reread = _read_json(ledger_path, code="FINAL_CHARACTER_METHOD_PROJECTION_INVALID")
    profile_reread = _read_json(profile_path, code="FINAL_CHARACTER_METHOD_PROJECTION_INVALID")
    if (
        reread != projected_ledger
        or profile_reread != projected_profile
        or raw_provenance_path.read_bytes() != raw_provenance_bytes
    ):
        raise invalid("The Method projection could not be read back exactly or altered raw provenance.")
    return {
        "schema_version": provenance["schema_version"],
        "source_ledger_path": provenance["source_ledger_path"],
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_provenance_sha256,
        "details_path": _METHOD_PROJECTION_DETAILS_RELATIVE,
        "details_sha256": sha256_file(details_path),
        "method_id": _METHOD_ID,
        "method_name": _METHOD_NAME,
        "method_packet_id": method_packet_id,
        "method_authority_path": _PACKET_METHOD_SOURCE_PATH,
        "method_authority_sha256": _PACKET_METHOD_SOURCE_SHA256,
        "method_authority_anchor": f"method:{_METHOD_ID}",
        "method_source_master_path": _METHOD_SOURCE_MASTER_PATH,
        "method_source_master_sha256": _METHOD_SOURCE_MASTER_SHA256,
        "method_source_master_anchor": _METHOD_SOURCE_MASTER_ANCHOR,
        "path_id": path_id,
        "resource_name": resource_rules["name"],
        "resource_formula": resource_rules["maximum_formula"],
        "projected_method": deepcopy(projected_method),
    }


def _project_method_for_compiler(
    workspace: Path,
    *,
    path_projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project any source-bound Method while retaining the old one-packet path.

    The pinned compiler has a flat Method surface, but the selected Method is
    owned by the modern record and its causal packets.  This bridge therefore
    keeps the historical acquisition-only contract intact and expands the
    mechanical contract only when both acquisition and activation packets are
    present.  No resource totals are calculated here; the causal Stage 2 rows
    remain the sole source of current and maximum values.
    """

    def invalid(message: str, *, details: Any = None) -> FoundryError:
        return _error("FINAL_CHARACTER_METHOD_PROJECTION_INVALID", message, details=details)

    root = Path(workspace)
    ledger_path = root / "Build/Character_Master_Ledger.json"
    raw_provenance_path = root / _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    profile_path = root / "Build/Cultivation_Method_Profile.json"
    registry_path = root / "Command_2/Rules_Selection_Packets.json"
    build_registry_path = root / "Build/Rules_Selection_Packets.json"
    details_path = root / _METHOD_PROJECTION_DETAILS_RELATIVE
    for path in (ledger_path, raw_provenance_path, profile_path, registry_path):
        if path.is_symlink() or not path.is_file():
            raise invalid("The copied Method projection inputs are missing or unsafe.", details={"path": str(path)})
    if details_path.is_symlink() or details_path.exists():
        raise invalid("The copied workspace already contains Method projection provenance.")
    if build_registry_path.is_symlink() or (build_registry_path.exists() and not build_registry_path.is_file()):
        raise invalid("The copied Build packet registry is unsafe.", details={"path": str(build_registry_path)})

    try:
        raw_provenance_bytes = raw_provenance_path.read_bytes()
        raw_provenance_sha256 = hashlib.sha256(raw_provenance_bytes).hexdigest()
        raw_ledger = _read_json(raw_provenance_path, code="FINAL_CHARACTER_METHOD_PROJECTION_INVALID")
        ledger = _read_json(ledger_path, code="FINAL_CHARACTER_METHOD_PROJECTION_INVALID")
        profile = _read_json(profile_path, code="FINAL_CHARACTER_METHOD_PROJECTION_INVALID")
        registry = _read_json(registry_path, code="FINAL_CHARACTER_METHOD_PROJECTION_INVALID")
        build_registry = (
            _read_json(build_registry_path, code="FINAL_CHARACTER_METHOD_PROJECTION_INVALID")
            if build_registry_path.exists()
            else None
        )
    except (OSError, FoundryError) as exc:
        if isinstance(exc, FoundryError):
            raise invalid("The copied Method projection inputs could not be read.", details={"cause": exc.code}) from exc
        raise invalid("The copied Method projection inputs could not be read.") from exc
    if not all(isinstance(value, Mapping) for value in (raw_ledger, ledger, profile, registry)):
        raise invalid("The copied Method projection inputs must be mappings.")
    if profile.get("schema_version") != "TianxiaFoundry.CharacterGMMethod.v1":
        raise invalid("The copied Method profile has an unsupported schema.")
    if build_registry is not None and build_registry != registry:
        raise invalid("The Build and Command 2 packet registries diverge.")
    packets = registry.get("packets")
    if registry.get("schema_version") != "TianxiaFoundry.RulesSelectionPackets.v2" or not isinstance(packets, list):
        raise invalid("The copied packet registry is not the sealed modern schema.")
    packet_by_id: dict[str, Mapping[str, Any]] = {}
    for index, packet in enumerate(packets):
        if not isinstance(packet, Mapping) or not isinstance(packet.get("packet_id"), str) or not packet.get("packet_id").strip():
            raise invalid("A Method packet has no stable packet ID.", details={"index": index})
        packet_id = packet["packet_id"]
        if packet_id in packet_by_id:
            raise invalid("The Method packet registry contains duplicate packet IDs.", details={"packet_id": packet_id})
        packet_by_id[packet_id] = packet

    raw_method = raw_ledger.get("method")
    current_method = ledger.get("method")
    profile_method = profile.get("method")
    if not all(isinstance(value, Mapping) for value in (raw_method, current_method, profile_method)):
        raise invalid("The copied Method rows are missing or not mappings.")
    for label, row in (("copied", current_method), ("profile", profile_method)):
        if row != raw_method:
            # The source row is allowed to gain the compiler overlay only in
            # the copied ledger/profile; before projection it must be exact.
            compiler_keys = {
                "method_id", "allocation_id", "name", "role", "resource_name", "resource_formula",
                "gained_at_cl", "benefits", "drawbacks", "mechanical_hooks", "applied_math",
                "stacking_statement", "resource_modifiers", "breakthrough_shape", "foundation_compatibility",
                "incompatibilities", "path_ids", "path_resource_profiles", "breakthrough_profiles", "ap_grants",
                "mechanics_version",
            }
            stripped = {key: value for key, value in row.items() if key not in compiler_keys}
            raw_stripped = {key: value for key, value in raw_method.items() if key not in compiler_keys}
            if stripped != raw_stripped:
                raise invalid("The copied Method source surface diverges from modern provenance.", details={"label": label})
    raw_character = raw_ledger.get("character")
    current_character = ledger.get("character")
    if not isinstance(raw_character, Mapping) or not isinstance(current_character, Mapping):
        raise invalid("The copied Method has no active character Path binding.")
    identity_fields = ("path_id", "path", "key_ability", "cl")
    if any(current_character.get(field) != raw_character.get(field) for field in identity_fields):
        raise invalid("The copied active Method Path identity diverges from raw provenance.")
    primary_path_id = raw_character.get("path_id")
    primary_path_name = raw_character.get("path")
    character_cl = raw_character.get("cl")
    if (
        not isinstance(primary_path_id, str)
        or not primary_path_id.strip()
        or not isinstance(primary_path_name, str)
        or not primary_path_name.strip()
        or type(character_cl) is not int
        or not 1 <= character_cl <= 20
    ):
        raise invalid("The active Method Path binding is incomplete.")

    source_packet_ids = raw_method.get("source_packet_ids")
    if (
        not isinstance(source_packet_ids, list)
        or not source_packet_ids
        or any(not isinstance(value, str) or not value.strip() for value in source_packet_ids)
        or len(source_packet_ids) != len(set(source_packet_ids))
    ):
        raise invalid("The selected Method has incomplete or duplicate source packet bindings.")
    for label, row in (("copied", current_method), ("profile", profile_method)):
        if row.get("source_packet_ids") != source_packet_ids:
            raise invalid("The copied Method source packet binding diverges.", details={"label": label})
        if any(row.get(field) != raw_method.get(field) for field in ("record_id", "display_name", "event_id", "record_hash")):
            raise invalid("The copied Method identity diverges from modern provenance.", details={"label": label})
    if any(
        not isinstance(raw_method.get(field), str) or not raw_method.get(field).strip()
        for field in ("record_id", "display_name", "event_id", "record_hash")
    ):
        raise invalid("The selected Method identity is incomplete.")

    fixed_registry = _bridge_fixed_json(_PACKET_METHOD_SOURCE_PATH, _PACKET_METHOD_SOURCE_SHA256)
    fixed_rows = fixed_registry.get("methods") if isinstance(fixed_registry, Mapping) else None
    if not isinstance(fixed_rows, list):
        raise invalid("The fixed Method authority is unavailable or malformed.")
    fixed_ids = [row.get("method_id") for row in fixed_rows if isinstance(row, Mapping)]
    if (
        len(fixed_ids) != len(fixed_rows)
        or any(not isinstance(value, str) or not value.strip() for value in fixed_ids)
        or len(set(fixed_ids)) != len(fixed_ids)
    ):
        raise invalid("The fixed Method authority has malformed or duplicate IDs.")
    method_id = raw_method["record_id"]
    fixed_matches = [row for row in fixed_rows if isinstance(row, Mapping) and row.get("method_id") == method_id]
    if len(fixed_matches) != 1 or fixed_matches[0].get("name") != raw_method["display_name"]:
        raise invalid("The selected Method is not the unique hash-pinned canonical authority.", details={"method_id": method_id})
    fixed_method = fixed_matches[0]

    first_packet = packet_by_id.get(source_packet_ids[0])
    first_binding = first_packet.get("content_binding") if isinstance(first_packet, Mapping) else None
    first_version = first_binding.get("pack_version") if isinstance(first_binding, Mapping) else None
    mechanics_version = "0.6.0-mechanics.1"
    mechanical_method = (
        raw_method.get("mechanical_projection") is True
        or isinstance(raw_method.get("mechanics"), Mapping)
        or first_version == mechanics_version
    )
    if mechanical_method:
        if len(source_packet_ids) != 2 or raw_method.get("state") != "active" or raw_method.get("status") != "active" or raw_method.get("mechanical_projection") is not True:
            raise invalid("The mechanical Method requires active state and acquisition plus activation packets.")
        mechanics = raw_method.get("mechanics")
        if not isinstance(mechanics, Mapping) or mechanics.get("schema") != "TianxiaFoundry.MethodMechanicalAuthority.v1":
            raise invalid("The selected Method mechanics are missing or use an unsupported schema.")
        from non_sphere_authority.method_mechanics import compile_method_mechanics

        try:
            expected_mechanics = compile_method_mechanics(dict(fixed_method), _PACKET_METHOD_SOURCE_SHA256)
        except FoundryError as exc:
            raise invalid("The pinned Method authority has malformed mechanical inputs.", details={"cause": exc.code}) from exc
        if canonical_json(mechanics) != canonical_json(expected_mechanics):
            raise invalid("The selected Method mechanics do not match the pinned source record.")
    else:
        if len(source_packet_ids) != 1:
            raise invalid("A historical acquisition-only Method cannot carry activation packets.")

    def validate_method_packet(packet_id: str, *, kind: str, event_id: str, version_required: bool) -> Mapping[str, Any]:
        packet = packet_by_id.get(packet_id)
        evidence = packet.get("source_evidence") if isinstance(packet, Mapping) else None
        evidence_row = evidence[0] if isinstance(evidence, list) and len(evidence) == 1 and isinstance(evidence[0], Mapping) else None
        binding = packet.get("content_binding") if isinstance(packet, Mapping) else None
        if (
            packet is None
            or packet.get("record_id") != method_id
            or packet.get("display_name") != raw_method["display_name"]
            or packet.get("advancement_kind") != kind
            or type(packet.get("target_cl")) is not int
            or packet.get("target_cl") != 1
            or packet.get("event_id") != event_id
            or packet.get("record_hash") != raw_method["record_hash"]
            or not isinstance(binding, Mapping)
            or binding.get("record_hash") != raw_method["record_hash"]
            or not isinstance(evidence_row, Mapping)
            or evidence_row.get("source_path") != _PACKET_METHOD_SOURCE_PATH
            or evidence_row.get("source_hash") != _PACKET_METHOD_SOURCE_SHA256
            or evidence_row.get("source_anchor") != f"method:{method_id}"
            or (
                version_required
                and evidence_row.get("source_id") != f"source.{_PACKET_METHOD_SOURCE_SHA256[:24]}"
            )
            or (
                not version_required
                and evidence_row.get("source_id") not in (None, f"source.{_PACKET_METHOD_SOURCE_SHA256[:24]}")
            )
        ):
            raise invalid("A selected Method packet is not the exact hash-pinned event binding.", details={"packet_id": packet_id})
        if version_required and (
            binding.get("pack_id") != "tianxia.non_sphere.authority"
            or binding.get("pack_version") != mechanics_version
        ):
            raise invalid("A mechanical Method packet has an unsupported source version.", details={"packet_id": packet_id})
        if not version_required and binding.get("pack_version") not in (None, "0.6"):
            raise invalid("A historical Method packet has an unsupported source version.", details={"packet_id": packet_id})
        if not version_required and binding.get("pack_id") not in (None, "tianxia.non_sphere.authority"):
            raise invalid("A historical Method packet has an unsupported source pack.", details={"packet_id": packet_id})
        return packet

    validate_method_packet(source_packet_ids[0], kind="method_acquisition", event_id=raw_method["event_id"], version_required=mechanical_method)
    if mechanical_method:
        activation_event_id = raw_method.get("activation_event_id")
        if not isinstance(activation_event_id, str) or not activation_event_id.strip():
            raise invalid("The mechanical Method has no activation event identity.")
        validate_method_packet(source_packet_ids[1], kind="method_activation", event_id=activation_event_id, version_required=True)

    # Derive all active Path bindings from the source row.  The flat
    # character identity remains the primary Path for compiler compatibility;
    # every independently selected Path is retained in the extra source-bound
    # maps below.
    raw_path_rows = raw_character.get("paths")
    current_path_rows = current_character.get("paths")
    if raw_path_rows is None:
        raw_path_rows = [{
            "path_id": primary_path_id,
            "display_name": primary_path_name,
            "key_ability": raw_character.get("key_ability"),
            "effective_cl": character_cl,
            "source_packet_ids": (path_projection or {}).get("path_source_packet_ids", []),
        }]
    if not isinstance(raw_path_rows, list) or not raw_path_rows or not isinstance(current_path_rows, list) or current_path_rows != raw_path_rows:
        raise invalid("The selected Method Paths are missing or diverge from raw provenance.")
    if any(not isinstance(row, Mapping) for row in raw_path_rows):
        raise invalid("The selected Method Path rows are malformed.")
    if character_cl != max((row.get("effective_cl") for row in raw_path_rows), default=None):
        raise invalid("The character CL is not the maximum selected Path target CL.")
    selected_path_ids = [row.get("path_id") for row in raw_path_rows]
    if (
        any(not isinstance(path_id, str) or not path_id.strip() for path_id in selected_path_ids)
        or len(selected_path_ids) != len(set(selected_path_ids))
        or primary_path_id != selected_path_ids[0]
    ):
        raise invalid("The selected Method Path identities are incomplete or duplicated.")
    if path_projection is not None:
        projected_path_ids = path_projection.get("path_ids")
        if not isinstance(projected_path_ids, list):
            projected_path_ids = [path_projection.get("path_id")]
        if projected_path_ids != selected_path_ids:
            raise invalid("The Method is not bound to the authenticated Path projection.")
        projected_packets = path_projection.get("path_source_packet_ids")
        if isinstance(projected_packets, list):
            actual_packets = [row.get("source_packet_ids", [None])[0] for row in raw_path_rows]
            if projected_packets != actual_packets:
                raise invalid("The Method Path packet binding diverges from the authenticated Path projection.")

    path_master = _bridge_fixed_json(_PACKET_PATH_MASTER_PATH, _PACKET_PATH_MASTER_SHA256)
    master_rows = path_master.get("paths") if isinstance(path_master, Mapping) else None
    if not isinstance(master_rows, list):
        raise invalid("The fixed Path master has no canonical path list.")
    master_by_id = {row.get("canonical_id"): row for row in master_rows if isinstance(row, Mapping)}
    compact_by_path = {
        "tianxia.path.body_refining": "BODY_REFINING",
        "tianxia.path.qi_cultivation": "QI_CULTIVATION",
        "tianxia.path.spirit_awakening": "SPIRIT_AWAKENING",
    }
    path_bindings: list[dict[str, Any]] = []
    for row in raw_path_rows:
        selected_path_id = row.get("path_id")
        selected_path_name = row.get("display_name")
        proof = _PACKET_PATH_PROOFS.get(selected_path_id)
        path_index = _bridge_fixed_json(proof["index_path"], proof["index_sha256"]) if proof else None
        master_row = master_by_id.get(selected_path_id)
        path_packet_ids = row.get("source_packet_ids")
        if (
            proof is None
            or not isinstance(path_index, Mapping)
            or not isinstance(master_row, Mapping)
            or path_index.get("canonical_id") != selected_path_id
            or path_index.get("display_name") != selected_path_name
            or master_row.get("display_name") != selected_path_name
            or not isinstance(path_packet_ids, list)
            or len(path_packet_ids) != 1
            or not isinstance(path_packet_ids[0], str)
            or not path_packet_ids[0].strip()
            or type(row.get("effective_cl")) is not int
            or not 1 <= row["effective_cl"] <= 20
        ):
            raise invalid("A selected Method Path is not bound to its fixed source authority.", details={"path_id": selected_path_id})
        packet = packet_by_id.get(path_packet_ids[0])
        evidence = packet.get("source_evidence") if isinstance(packet, Mapping) else None
        evidence_row = evidence[0] if isinstance(evidence, list) and len(evidence) == 1 and isinstance(evidence[0], Mapping) else None
        if (
            packet is None
            or packet.get("record_id") != selected_path_id
            or packet.get("display_name") != selected_path_name
            or packet.get("advancement_kind") != "path_acquisition"
            or packet.get("target_cl") != 1
            or not isinstance(evidence_row, Mapping)
            or evidence_row.get("source_path") != proof["index_path"]
            or evidence_row.get("source_hash") != proof["index_sha256"]
            or evidence_row.get("source_anchor") != f"path:{selected_path_id}"
        ):
            raise invalid("A selected Method Path packet is not the exact source binding.", details={"path_id": selected_path_id})
        resource_rules = path_index.get("resource_rules")
        if not isinstance(resource_rules, Mapping) or not isinstance(resource_rules.get("name"), str) or not resource_rules.get("name").strip() or not isinstance(resource_rules.get("maximum_formula"), str) or not resource_rules.get("maximum_formula").strip():
            raise invalid("A selected Method Path lacks a complete resource authority.", details={"path_id": selected_path_id})
        path_bindings.append({
            "path_id": selected_path_id,
            "compact_path_id": compact_by_path.get(selected_path_id),
            "display_name": selected_path_name,
            "key_ability": row.get("key_ability"),
            "effective_cl": row["effective_cl"],
            "packet_id": path_packet_ids[0],
            "proof": proof,
            "index": path_index,
            "resource_rules": resource_rules,
        })
    if any(row["compact_path_id"] is None for row in path_bindings):
        raise invalid("A selected Method Path has no supported typed resource mapping.")

    fixed_source_text = fixed_method.get("source_text")
    fixed_owner_readable = fixed_method.get("owner_readable")
    fixed_resources = fixed_method.get("per_path_resource_profiles")
    fixed_breakthroughs = fixed_method.get("per_path_breakthrough_profiles")
    fixed_grants = fixed_method.get("explicit_ap_grants")
    risks = fixed_method.get("risks_limitations")
    secondary_tags = fixed_method.get("secondary_form_tags")
    if (
        not isinstance(fixed_source_text, Mapping)
        or not isinstance(fixed_owner_readable, Mapping)
        or not isinstance(fixed_resources, list)
        or not isinstance(fixed_breakthroughs, list)
        or not isinstance(fixed_grants, list)
        or not isinstance(risks, list)
        or not risks
        or not isinstance(secondary_tags, list)
        or not secondary_tags
    ):
        raise invalid("The fixed Method compiler inputs are incomplete.")
    resource_by_compact: dict[str, Mapping[str, Any]] = {}
    for row in fixed_resources:
        if not isinstance(row, Mapping) or row.get("path_id") in resource_by_compact:
            raise invalid("The selected Method resource authority is malformed or duplicated.")
        resource_by_compact[row.get("path_id")] = row
    breakthrough_by_compact: dict[str, Mapping[str, Any]] = {}
    for row in fixed_breakthroughs:
        if not isinstance(row, Mapping) or row.get("path_id") in breakthrough_by_compact:
            raise invalid("The selected Method breakthrough authority is malformed or duplicated.")
        breakthrough_by_compact[row.get("path_id")] = row
    grant_by_compact: dict[str, Mapping[str, Any]] = {}
    for row in fixed_grants:
        if not isinstance(row, Mapping):
            raise invalid("The selected Method AP authority is malformed.")
        compact = row.get("path_id")
        if row.get("grants_attainment_points") is True:
            if compact in grant_by_compact:
                raise invalid("The selected Method AP authority is duplicated.")
            grant_by_compact[compact] = row
    selected_profiles: list[dict[str, Any]] = []
    selected_breakthroughs: list[dict[str, Any]] = []
    selected_grants: list[dict[str, Any]] = []
    for binding in path_bindings:
        compact = binding["compact_path_id"]
        resource_profile = resource_by_compact.get(compact)
        breakthrough = breakthrough_by_compact.get(compact)
        grant = grant_by_compact.get(compact)
        resource_rules = binding["resource_rules"]
        if (
            not isinstance(resource_profile, Mapping)
            or not isinstance(breakthrough, Mapping)
            or not isinstance(grant, Mapping)
            or resource_profile.get("resource_id") != resource_rules.get("canonical_id")
            or resource_profile.get("resource_name") != resource_rules.get("name")
            or not isinstance(resource_profile.get("source_text"), str)
            or not resource_profile.get("source_text").strip()
            or not isinstance(breakthrough.get("source_text"), str)
            or not breakthrough.get("source_text").strip()
        ):
            raise invalid("The selected Method lacks complete per-Path resource, breakthrough, or AP authority.", details={"path_id": binding["path_id"]})
        selected_profiles.append({"path_id": binding["path_id"], **deepcopy(dict(resource_profile))})
        selected_breakthroughs.append({"path_id": binding["path_id"], **deepcopy(dict(breakthrough))})
        selected_grants.append({"path_id": binding["path_id"], **deepcopy(dict(grant))})

    source_master_path = _FINAL_CHARACTER_BASE_FACTORY_ROOT / _METHOD_SOURCE_MASTER_PATH
    try:
        if source_master_path.is_symlink() or not source_master_path.is_file() or sha256_file(source_master_path) != _METHOD_SOURCE_MASTER_SHA256:
            raise invalid("The fixed Method source master is unavailable or changed.", details={"path": str(source_master_path)})
        source_master_text = source_master_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise invalid("The fixed Method source master could not be read.", details={"path": str(source_master_path)}) from exc
    source_lines = source_master_text.splitlines()
    method_number = fixed_method.get("number")
    section = ""
    source_master_anchor = f"method:{method_id}"
    if type(method_number) is int:
        heading = f"## {method_number}. {fixed_method['name']}"
        heading_matches = [index for index, line in enumerate(source_lines) if line.strip() == heading]
        if len(heading_matches) == 1:
            heading_index = heading_matches[0]
            section_end = next(
                (index for index in range(heading_index + 1, len(source_lines)) if re.match(r"^##\s+\S", source_lines[index].strip())),
                len(source_lines),
            )
            section = "\n".join(source_lines[heading_index:section_end])
            source_master_anchor = f"heading:{method_number}-{str(fixed_method['name']).lower().replace(' ', '-') }"
    if section:
        def source_label(label: str) -> str | None:
            prefix = f"**{label}:**"
            matches = [line.strip()[len(prefix):].strip() for line in section.splitlines() if line.strip().startswith(prefix)]
            return matches[0] if len(matches) == 1 and matches[0] else None

        label_map = {
            "Type": "type",
            "Common Users": "common_users",
            "Compatible Themes": "compatible_themes_text",
            "Resource Shape": "resource_shape",
            "Breakthrough Shape": "breakthrough_shape",
            "Foundation Shape": "foundation_shape",
        }
        if any(source_label(label) != fixed_source_text.get(field) for label, field in label_map.items()):
            raise invalid("The Method source master does not match the fixed typed authority.")
        description = fixed_source_text.get("description")
        use_as_prefix = "**Use As:**"
        use_as_matches = [line.strip()[len(use_as_prefix):].strip() for line in section.splitlines() if line.strip().startswith(use_as_prefix)]
        if not isinstance(description, str) or section.count(description) != 1 or len(use_as_matches) != 1 or use_as_matches[0] != fixed_source_text.get("use_as"):
            raise invalid("The Method source master description is incomplete or changed.")
    else:
        description = fixed_source_text.get("description")
    if not isinstance(description, str) or not description.strip():
        raise invalid("The selected Method has no source-backed description.")
    for packet_id in source_packet_ids:
        packet_description = packet_by_id[packet_id].get("full_description")
        if packet_description != description:
            raise invalid("The selected Method packet description conflicts with fixed source authority.", details={"packet_id": packet_id})
    stacking_matches = [
        line.strip().removeprefix("- ").replace("**", "")
        for line in source_lines
        if line.strip().startswith("- A character may know multiple Methods, but only one Method is the character's")
    ]
    if len(stacking_matches) != 1:
        raise invalid("The fixed Method source has no unique stacking rule.")

    primary_binding = path_bindings[0]
    primary_profile = selected_profiles[0]
    primary_resource_rules = primary_binding["resource_rules"]

    def pb_at(cl: int) -> int:
        return 2 + (cl - 1) // 4

    compiler_resource_modifiers: list[dict[str, Any]] = []
    if mechanical_method:
        for modifier in expected_mechanics["resource_modifiers"]:
            formula = modifier.get("formula") if isinstance(modifier, Mapping) else None
            terms = ((formula or {}).get("root") or {}).get("terms") if isinstance(formula, Mapping) else None
            units = terms[0].get("value") if isinstance(terms, list) and terms and isinstance(terms[0], Mapping) else None
            resource_id = modifier.get("resource_id")
            resource_name = next((row.get("resource_name") for row in selected_profiles if row.get("resource_id") == resource_id), None)
            if not isinstance(units, int) or not isinstance(resource_name, str) or not resource_name.strip():
                raise invalid("The selected Method mechanical resource modifier is incomplete.")
            amount = abs(units * pb_at(character_cl))
            compiler_resource_modifiers.append({
                "resource_id": resource_id,
                "resource_name": resource_name,
                "operation": "subtract" if units < 0 else "add",
                "amount": amount,
                "expression": f"{units:+d} × current PB at CL{character_cl}",
                "formula": deepcopy(formula),
                "source_packet_ids": deepcopy(source_packet_ids),
            })

    expected_generated = {
        "method_id": method_id,
        "allocation_id": f"allocation.method.{source_packet_ids[0]}",
        "name": raw_method["display_name"],
        "role": f"Primary {primary_resource_rules['name']} cultivation method",
        "resource_name": primary_resource_rules["name"],
        "resource_formula": primary_resource_rules["maximum_formula"],
        "gained_at_cl": packet_by_id[source_packet_ids[0]]["target_cl"],
        "benefits": [fixed_owner_readable.get("resource_summary"), fixed_owner_readable.get("ap_route_summary")],
        "drawbacks": deepcopy(list(risks)),
        "mechanical_hooks": deepcopy(list(secondary_tags)),
        "source_packet_ids": deepcopy(source_packet_ids),
        "applied_math": [
            binding["resource_rules"]["maximum_formula"]
            for binding in path_bindings
        ] + [profile_row["source_text"] for profile_row in selected_profiles],
        "stacking_statement": stacking_matches[0],
        "resource_modifiers": compiler_resource_modifiers,
        "breakthrough_shape": fixed_source_text["breakthrough_shape"],
        "foundation_compatibility": [fixed_source_text["foundation_shape"]],
        "incompatibilities": deepcopy(list(risks)),
        "path_ids": [binding["path_id"] for binding in path_bindings],
        "path_resource_profiles": deepcopy(selected_profiles),
        "breakthrough_profiles": deepcopy(selected_breakthroughs),
        "ap_grants": deepcopy(selected_grants),
        "mechanics_version": mechanics_version if mechanical_method else (first_version or "0.6"),
    }
    if any(not isinstance(value, str) or not value.strip() for value in expected_generated["benefits"]):
        raise invalid("The selected Method benefit authority is incomplete.")
    compiler_fields = set(expected_generated) - {"source_packet_ids"}

    def validate_existing_projection(row: Mapping[str, Any], *, label: str) -> None:
        present = compiler_fields.intersection(row)
        if present and present != compiler_fields:
            raise invalid("An existing Method compiler projection is partial.", details={"label": label, "fields": sorted(present)})
        for field in present:
            if row.get(field) != expected_generated[field]:
                raise invalid("An existing Method compiler projection conflicts with fixed authority.", details={"label": label, "field": field})

    for label, row in (("raw", raw_method), ("copied", current_method), ("profile", profile_method)):
        validate_existing_projection(row, label=label)
    raw_binding = deepcopy(dict(raw_method))
    current_binding = deepcopy(dict(current_method))
    profile_binding = deepcopy(dict(profile_method))
    for value in (raw_binding, current_binding, profile_binding):
        for field in compiler_fields:
            value.pop(field, None)
    if current_binding != raw_binding or profile_binding != raw_binding:
        raise invalid("The copied Method master/profile surfaces diverge from raw modern provenance.")
    projected_method = deepcopy(dict(current_method))
    projected_method.update(deepcopy(expected_generated))
    projected_ledger = deepcopy(dict(ledger))
    projected_ledger["method"] = projected_method
    projected_profile = deepcopy(dict(profile))
    projected_profile["method"] = deepcopy(projected_method)
    provenance = {
        "schema_version": "TianxiaFoundry.FinalCharacterMethodProjectionProvenance.v1",
        "source_ledger_path": "Build/Character_Master_Ledger.json",
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_provenance_sha256,
        "packet_registry_path": "Command_2/Rules_Selection_Packets.json",
        "packet_registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
        "method_id": method_id,
        "method_name": raw_method["display_name"],
        "method_packet_ids": deepcopy(source_packet_ids),
        "method_packet_id": source_packet_ids[0],
        "method_authority_path": _PACKET_METHOD_SOURCE_PATH,
        "method_authority_sha256": _PACKET_METHOD_SOURCE_SHA256,
        "method_authority_anchor": f"method:{method_id}",
        "method_source_master_path": _METHOD_SOURCE_MASTER_PATH,
        "method_source_master_sha256": _METHOD_SOURCE_MASTER_SHA256,
        "method_source_master_anchor": source_master_anchor,
        "path_ids": [binding["path_id"] for binding in path_bindings],
        "path_bindings": deepcopy(path_bindings),
        "resource_names": [row["resource_name"] for row in selected_profiles],
        "resource_formulas": [binding["resource_rules"]["maximum_formula"] for binding in path_bindings],
        "projected_method": deepcopy(projected_method),
    }
    _write_json(details_path, provenance)
    _write_json(ledger_path, projected_ledger)
    _write_json(profile_path, projected_profile)
    reread = _read_json(ledger_path, code="FINAL_CHARACTER_METHOD_PROJECTION_INVALID")
    profile_reread = _read_json(profile_path, code="FINAL_CHARACTER_METHOD_PROJECTION_INVALID")
    if reread != projected_ledger or profile_reread != projected_profile or raw_provenance_path.read_bytes() != raw_provenance_bytes:
        raise invalid("The Method projection could not be read back exactly or altered raw provenance.")
    return {
        "schema_version": provenance["schema_version"],
        "source_ledger_path": provenance["source_ledger_path"],
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_provenance_sha256,
        "details_path": _METHOD_PROJECTION_DETAILS_RELATIVE,
        "details_sha256": sha256_file(details_path),
        "method_id": method_id,
        "method_name": raw_method["display_name"],
        "method_packet_id": source_packet_ids[0],
        "method_packet_ids": deepcopy(source_packet_ids),
        "method_authority_path": _PACKET_METHOD_SOURCE_PATH,
        "method_authority_sha256": _PACKET_METHOD_SOURCE_SHA256,
        "method_authority_anchor": f"method:{method_id}",
        "method_source_master_path": _METHOD_SOURCE_MASTER_PATH,
        "method_source_master_sha256": _METHOD_SOURCE_MASTER_SHA256,
        "method_source_master_anchor": source_master_anchor,
        "path_id": primary_path_id,
        "path_ids": [binding["path_id"] for binding in path_bindings],
        "resource_name": primary_resource_rules["name"],
        "resource_formula": primary_resource_rules["maximum_formula"],
        "projected_method": deepcopy(projected_method),
    }


def _project_foundation_for_compiler_fixed(workspace: Path) -> dict[str, Any]:
    """Project the selected Foundation into the pinned compiler shape.

    Stage 2 records a Foundation acquisition event and keeps the richer
    Foundation authority in the fixed Factory registry.  The pinned compiler
    requires the older expanded Foundation row, so this bridge renders that
    row only from the exact sealed packet and the hash-pinned Furnace Heart
    authority.  The modern ledger and Foundation detail mirror are updated
    together; the raw modern provenance remains byte-for-byte untouched.
    """

    def invalid(message: str, *, details: Any = None) -> FoundryError:
        return _error("FINAL_CHARACTER_FOUNDATION_PROJECTION_INVALID", message, details=details)

    root = Path(workspace)
    ledger_path = root / "Build/Character_Master_Ledger.json"
    raw_provenance_path = root / _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    mirror_path = root / "Build/Foundation_Detail_Ledger.json"
    registry_path = root / "Command_2/Rules_Selection_Packets.json"
    build_registry_path = root / "Build/Rules_Selection_Packets.json"
    details_path = root / _FOUNDATION_PROJECTION_DETAILS_RELATIVE
    for path in (ledger_path, raw_provenance_path, mirror_path, registry_path):
        if path.is_symlink() or not path.is_file():
            raise invalid("The copied Foundation projection inputs are missing or unsafe.", details={"path": str(path)})
    if details_path.is_symlink() or details_path.exists():
        raise invalid("The copied workspace already contains Foundation projection provenance.")
    if build_registry_path.is_symlink() or (build_registry_path.exists() and not build_registry_path.is_file()):
        raise invalid("The copied Build packet registry is unsafe.", details={"path": str(build_registry_path)})

    try:
        raw_provenance_bytes = raw_provenance_path.read_bytes()
        raw_provenance_sha256 = hashlib.sha256(raw_provenance_bytes).hexdigest()
        raw_ledger = _read_json(raw_provenance_path, code="FINAL_CHARACTER_FOUNDATION_PROJECTION_INVALID")
        ledger = _read_json(ledger_path, code="FINAL_CHARACTER_FOUNDATION_PROJECTION_INVALID")
        mirror = _read_json(mirror_path, code="FINAL_CHARACTER_FOUNDATION_PROJECTION_INVALID")
        registry = _read_json(registry_path, code="FINAL_CHARACTER_FOUNDATION_PROJECTION_INVALID")
        build_registry = (
            _read_json(build_registry_path, code="FINAL_CHARACTER_FOUNDATION_PROJECTION_INVALID")
            if build_registry_path.exists()
            else None
        )
    except (OSError, FoundryError) as exc:
        if isinstance(exc, FoundryError):
            raise invalid("The copied Foundation projection inputs could not be read.", details={"cause": exc.code}) from exc
        raise invalid("The copied Foundation projection inputs could not be read.") from exc
    if not all(isinstance(value, Mapping) for value in (raw_ledger, ledger, mirror, registry)):
        raise invalid("The copied Foundation projection inputs must be mappings.")
    if mirror.get("schema_version") != "TianxiaFoundry.CharacterGMFoundation.v1":
        raise invalid("The copied Foundation detail mirror has an unsupported schema.")
    if build_registry is not None and build_registry != registry:
        raise invalid("The Build and Command 2 packet registries diverge.")
    packets = registry.get("packets")
    if registry.get("schema_version") != "TianxiaFoundry.RulesSelectionPackets.v2" or not isinstance(packets, list):
        raise invalid("The copied packet registry is not the sealed modern schema.")
    packet_by_id: dict[str, Mapping[str, Any]] = {}
    for index, packet in enumerate(packets):
        if not isinstance(packet, Mapping) or not isinstance(packet.get("packet_id"), str) or not packet.get("packet_id").strip():
            raise invalid("A Foundation packet has no stable packet ID.", details={"index": index})
        packet_id = packet["packet_id"]
        if packet_id in packet_by_id:
            raise invalid("The Foundation packet registry contains duplicate packet IDs.", details={"packet_id": packet_id})
        packet_by_id[packet_id] = packet

    raw_foundation = raw_ledger.get("foundation")
    current_foundation = ledger.get("foundation")
    mirror_foundation = mirror.get("foundation")
    if not all(isinstance(value, Mapping) for value in (raw_foundation, current_foundation, mirror_foundation)):
        raise invalid("The copied Foundation rows are missing or not mappings.")

    source_packet_ids = raw_foundation.get("source_packet_ids")
    if (
        not isinstance(source_packet_ids, list)
        or len(source_packet_ids) != 1
        or not isinstance(source_packet_ids[0], str)
        or not source_packet_ids[0].strip()
    ):
        raise invalid("The selected Foundation does not bind one exact source packet.")
    if source_packet_ids != [_FOUNDATION_PACKET_ID]:
        raise invalid(
            "The selected Foundation is not bound to the accepted sealed source packet.",
            details={"expected": [_FOUNDATION_PACKET_ID], "actual": source_packet_ids},
        )
    foundation_packet_id = source_packet_ids[0]
    for label, row in (("copied", current_foundation), ("mirror", mirror_foundation)):
        if row.get("source_packet_ids") != source_packet_ids:
            raise invalid("The copied Foundation source packet binding diverges.", details={"label": label})

    if (
        raw_foundation.get("record_id") != current_foundation.get("record_id")
        or raw_foundation.get("record_id") != mirror_foundation.get("record_id")
        or raw_foundation.get("display_name") != current_foundation.get("display_name")
        or raw_foundation.get("display_name") != mirror_foundation.get("display_name")
        or raw_foundation.get("event_id") != current_foundation.get("event_id")
        or raw_foundation.get("event_id") != mirror_foundation.get("event_id")
        or raw_foundation.get("record_hash") != current_foundation.get("record_hash")
        or raw_foundation.get("record_hash") != mirror_foundation.get("record_hash")
    ):
        raise invalid("The copied Foundation identity diverges from modern provenance.")
    if any(
        not isinstance(raw_foundation.get(field), str) or not raw_foundation.get(field).strip()
        for field in ("record_id", "display_name", "event_id", "record_hash")
    ):
        raise invalid("The selected Foundation identity is incomplete.")
    if raw_foundation.get("state") != "acquired" or raw_foundation.get("status") != "acquired" or raw_foundation.get("mechanical_projection") is not False:
        raise invalid("The selected Foundation is not the sealed acquired source row.")

    fixed_registry = _bridge_fixed_factory_json(
        _PACKET_FOUNDATION_SOURCE_PATH,
        _PACKET_FOUNDATION_SOURCE_SHA256,
    )
    fixed_rows = fixed_registry.get("foundations") if isinstance(fixed_registry, Mapping) else None
    if (
        not isinstance(fixed_registry, Mapping)
        or fixed_registry.get("schema") != "HF05ZVK-R1F.AuthoritativeFoundationRuntimeCatalog.v1"
        or fixed_registry.get("status") != "AUTHORITATIVE_30_ONLY"
        or not isinstance(fixed_rows, list)
    ):
        raise invalid("The fixed Foundation authority is unavailable or malformed.")
    fixed_ids = [row.get("foundation_id") for row in fixed_rows if isinstance(row, Mapping)]
    if (
        len(fixed_ids) != len(fixed_rows)
        or any(not isinstance(value, str) or not value.strip() for value in fixed_ids)
        or len(set(fixed_ids)) != len(fixed_ids)
    ):
        raise invalid("The fixed Foundation authority has malformed or duplicate IDs.")
    foundation_id = raw_foundation.get("record_id")
    foundation_name = raw_foundation.get("display_name")
    fixed_matches = [row for row in fixed_rows if isinstance(row, Mapping) and row.get("foundation_id") == foundation_id]
    if len(fixed_matches) != 1 or fixed_matches[0].get("name") != foundation_name:
        raise invalid("The selected Foundation is not the unique fixed canonical authority.", details={"foundation_id": foundation_id})
    fixed_foundation = fixed_matches[0]

    packet = packet_by_id.get(foundation_packet_id)
    evidence = packet.get("source_evidence") if isinstance(packet, Mapping) else None
    evidence_row = evidence[0] if isinstance(evidence, list) and len(evidence) == 1 and isinstance(evidence[0], Mapping) else None
    content_binding = packet.get("content_binding") if isinstance(packet, Mapping) else None
    expected_overview_text = canonical_json(fixed_foundation.get("overview")) if isinstance(fixed_foundation.get("overview"), Mapping) else None
    if (
        packet is None
        or packet.get("record_id") != foundation_id
        or packet.get("display_name") != foundation_name
        or packet.get("advancement_kind") != "foundation_acquisition"
        or type(packet.get("target_cl")) is not int
        or packet.get("target_cl") != 1
        or packet.get("event_id") != raw_foundation.get("event_id")
        or packet.get("record_hash") != raw_foundation.get("record_hash")
        or not isinstance(content_binding, Mapping)
        or content_binding.get("record_hash") != raw_foundation.get("record_hash")
        or not isinstance(evidence_row, Mapping)
        or evidence_row.get("source_path") != _PACKET_FOUNDATION_SOURCE_PATH
        or evidence_row.get("source_hash") != _PACKET_FOUNDATION_SOURCE_SHA256
        or evidence_row.get("source_anchor") != f"foundation:{foundation_id}"
        or evidence_row.get("source_id") != f"source.{_PACKET_FOUNDATION_SOURCE_SHA256[:24]}"
        or not isinstance(expected_overview_text, str)
        or packet.get("full_description") != expected_overview_text
        or packet.get("short_description") != expected_overview_text[:500]
    ):
        raise invalid("The selected Foundation packet is not the exact hash-pinned event binding.", details={"packet_id": foundation_packet_id})

    profile = fixed_foundation.get("profile")
    overview = fixed_foundation.get("overview")
    resource = fixed_foundation.get("resource")
    features = fixed_foundation.get("features")
    compatibility = fixed_foundation.get("compatibility")
    risks = fixed_foundation.get("risks")
    repair_practices = fixed_foundation.get("repair_practices")
    challenges = fixed_foundation.get("foundation_challenges")
    if (
        not isinstance(profile, Mapping)
        or not isinstance(overview, Mapping)
        or not isinstance(resource, Mapping)
        or not isinstance(features, Mapping)
        or not isinstance(compatibility, Mapping)
        or not isinstance(risks, Mapping)
        or not isinstance(repair_practices, list)
        or not isinstance(challenges, list)
        or not isinstance(profile.get("grade"), str)
        or not profile.get("grade").strip()
        or not isinstance(profile.get("default_stage"), str)
        or not profile.get("default_stage").strip()
        or not isinstance(resource.get("name"), str)
        or not resource.get("name").strip()
        or not isinstance(resource.get("gain"), str)
        or not resource.get("gain").strip()
    ):
        raise invalid("The fixed Foundation compiler inputs are incomplete.")
    stage = profile["default_stage"]
    grade = profile["grade"]
    stage_names = ("Awakened", "Refined", "Perfected", "Integrated")
    if stage not in stage_names:
        raise invalid("The fixed Foundation stage is not one of the compiler stages.", details={"stage": stage})
    stage_rows: dict[str, list[Mapping[str, Any]]] = {}
    for stage_name in stage_names:
        source_rows = features.get(stage_name.casefold())
        if not isinstance(source_rows, list) or any(
            not isinstance(row, Mapping)
            or not isinstance(row.get("name"), str)
            or not row.get("name").strip()
            or not isinstance(row.get("effect"), str)
            or not row.get("effect").strip()
            for row in source_rows
        ):
            raise invalid("The fixed Foundation feature authority is incomplete.", details={"stage": stage_name})
        stage_rows[stage_name] = list(source_rows)
    if not stage_rows[stage]:
        raise invalid("The selected Foundation stage has no fixed benefits.", details={"stage": stage})
    if (
        not isinstance(compatibility.get("legal_spheres"), list)
        or any(not isinstance(value, str) or not value.strip() for value in compatibility.get("legal_spheres", []))
        or not isinstance(compatibility.get("does_not_grant"), list)
        or any(not isinstance(value, str) or not value.strip() for value in compatibility.get("does_not_grant", []))
        or not isinstance(risks.get("burdens"), list)
        or not isinstance(risks.get("hidden_injuries"), list)
        or not isinstance(risks.get("strains"), list)
        or not isinstance(risks.get("deviations"), list)
    ):
        raise invalid("The fixed Foundation scope/risk authority is malformed.")

    def integer_text(value: Any, *, label: str) -> int:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value):
            raise invalid("The fixed Foundation resource counter is not a sealed non-negative integer.", details={"label": label, "value": value})
        return int(value)

    resource_current = integer_text(resource.get("starting"), label="starting")
    resource_max = integer_text(resource.get("maximum"), label="maximum")
    if resource_current > resource_max:
        raise invalid("The fixed Foundation resource counters are inconsistent.")

    benefits = [row["effect"] for row in stage_rows[stage]]
    actions = [
        row["name"]
        for row in stage_rows[stage]
        if row.get("type") != "No Action / Triggered"
    ]
    burden_rows = risks["burdens"]
    hidden_injury_rows = risks["hidden_injuries"]
    strain_rows = risks["strains"]
    deviation_rows = risks["deviations"]
    if any(not isinstance(row, Mapping) for row in (*burden_rows, *hidden_injury_rows, *strain_rows, *deviation_rows)):
        raise invalid("The fixed Foundation risk authority is malformed.")
    integration_entries = [
        deepcopy(row)
        for row in challenges
        if isinstance(row, Mapping) and row.get("name") == "Integrate Furnace Heart"
    ]
    if not integration_entries:
        raise invalid("The fixed Foundation has no exact integration challenge authority.")
    repair_entries = [deepcopy(row) for row in repair_practices if isinstance(row, Mapping)]
    if len(repair_entries) != len(repair_practices):
        raise invalid("The fixed Foundation repair authority is malformed.")

    source_note = overview.get("summary")
    if not isinstance(source_note, str) or not source_note.strip():
        raise invalid("The fixed Foundation overview has no source-backed summary.")
    generated_fields = {
        "foundation_id",
        "allocation_id",
        "name",
        "chosen_foundation",
        "grade",
        "stage",
        "gained_at_cl",
        "mortal_exception_source_packet_id",
        "benefits",
        "foundation_resource",
        "actions",
        "burdens",
        "stage_benefit_map",
        "primary_resource_modifiers",
        "lifecycle_coverage",
        "suppressed_or_excluded_benefits",
        "fixed_scope",
        "ai_notes",
    }
    expected_allocation_id = f"allocation.foundation.{foundation_packet_id}"
    expected_stage_map = [
        {
            "stage": stage_name,
            "available": stage_name == stage,
            "benefits": deepcopy(benefits if stage_name == stage else []),
            "source_packet_ids": [foundation_packet_id],
        }
        for stage_name in stage_names
    ]

    def lifecycle_row(
        status: str,
        entries: list[Any],
        *,
        note: Any,
    ) -> dict[str, Any]:
        if not isinstance(note, str) or not note.strip():
            raise invalid("The fixed Foundation lifecycle note is empty.")
        refs = [foundation_packet_id] if status in {"present", "suppressed_by_specific_rule"} else []
        return {"status": status, "entries": deepcopy(entries), "note": note, "source_packet_ids": refs}

    lifecycle = {
        "passive_chassis": lifecycle_row(
            "present",
            [row["effect"] for row in stage_rows[stage] if row.get("type") == "No Action / Triggered"],
            note=profile.get("typical_role") or source_note,
        ),
        "resources": lifecycle_row("present", [deepcopy(resource)], note=resource["gain"]),
        "actions_reactions": lifecycle_row(
            "present",
            [deepcopy(row) for row in stage_rows[stage] if row.get("type") != "No Action / Triggered"],
            note=overview.get("warning") or source_note,
        ),
        "states": lifecycle_row("none_in_source", [], note=overview.get("visible_sign") or source_note),
        "burdens": lifecycle_row("present", [deepcopy(row) for row in burden_rows], note=source_note),
        "hidden_injuries": lifecycle_row("present", [deepcopy(row) for row in hidden_injury_rows], note=source_note),
        "strains": lifecycle_row("present", [deepcopy(row) for row in strain_rows], note=source_note),
        "deviations": lifecycle_row("present", [deepcopy(row) for row in deviation_rows], note=source_note),
        "integration": lifecycle_row("present", integration_entries, note=integration_entries[0].get("effect") or source_note),
        "repair": lifecycle_row("present", repair_entries, note=repair_entries[0].get("effect") if repair_entries else source_note),
        "treatment": lifecycle_row(
            "present",
            [row["treatment"] for row in burden_rows if isinstance(row.get("treatment"), str) and row.get("treatment").strip()],
            note=source_note,
        ),
        "temptations": lifecycle_row(
            "present",
            [row["temptation"] for row in deviation_rows if isinstance(row.get("temptation"), str) and row.get("temptation").strip()],
            note=source_note,
        ),
        "failure_consequences": lifecycle_row(
            "present",
            [
                value
                for row in (*burden_rows, *hidden_injury_rows)
                for value in (row.get("stress_failure"),)
                if isinstance(value, str) and value.strip()
            ],
            note=overview.get("warning") or source_note,
        ),
    }
    expected_generated = {
        "foundation_id": foundation_id,
        "allocation_id": expected_allocation_id,
        "name": foundation_name,
        "chosen_foundation": foundation_name,
        "grade": grade,
        "stage": stage,
        "gained_at_cl": 1,
        "mortal_exception_source_packet_id": foundation_packet_id,
        "benefits": deepcopy(benefits),
        "foundation_resource": {
            "name": resource["name"],
            "current": resource_current,
            "max": resource_max,
            "generation": resource["gain"],
        },
        "actions": deepcopy(actions),
        "burdens": [row.get("name") for row in burden_rows if isinstance(row.get("name"), str) and row.get("name").strip()],
        "source_packet_ids": deepcopy(source_packet_ids),
        "fixed_scope": deepcopy(compatibility["legal_spheres"]) + deepcopy(compatibility["does_not_grant"]),
        "ai_notes": [
            value
            for value in (
                overview.get("summary"),
                overview.get("visible_sign"),
                overview.get("warning"),
                overview.get("dao_principle"),
            )
            if isinstance(value, str) and value.strip()
        ],
        "stage_benefit_map": expected_stage_map,
        "primary_resource_modifiers": [],
        "lifecycle_coverage": lifecycle,
        "suppressed_or_excluded_benefits": [],
    }
    compiler_fields = set(expected_generated) - {"source_packet_ids"}

    def validate_existing_projection(row: Mapping[str, Any], *, label: str) -> None:
        present = compiler_fields.intersection(row)
        if present and present != compiler_fields:
            raise invalid("An existing Foundation compiler projection is partial.", details={"label": label, "fields": sorted(present)})
        for field in present:
            if row.get(field) != expected_generated[field]:
                raise invalid("An existing Foundation compiler projection conflicts with fixed authority.", details={"label": label, "field": field})

    for label, row in (("raw", raw_foundation), ("copied", current_foundation), ("mirror", mirror_foundation)):
        validate_existing_projection(row, label=label)
    raw_binding = deepcopy(dict(raw_foundation))
    current_binding = deepcopy(dict(current_foundation))
    mirror_binding = deepcopy(dict(mirror_foundation))
    for value in (raw_binding, current_binding, mirror_binding):
        for field in compiler_fields:
            value.pop(field, None)
    mirror_binding = _foundation_mirror_authority_fields(mirror_binding, raw_binding)
    if current_binding != raw_binding or mirror_binding != raw_binding:
        raise invalid("The copied Foundation master/mirror surfaces diverge from raw modern provenance.")

    projected_foundation = deepcopy(dict(current_foundation))
    projected_foundation.update(deepcopy(expected_generated))
    projected_ledger = deepcopy(dict(ledger))
    projected_ledger["foundation"] = projected_foundation
    projected_mirror = deepcopy(dict(mirror))
    projected_mirror["foundation"] = deepcopy(projected_foundation)
    provenance = {
        "schema_version": "TianxiaFoundry.FinalCharacterFoundationProjectionProvenance.v1",
        "source_ledger_path": "Build/Character_Master_Ledger.json",
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_provenance_sha256,
        "packet_registry_path": "Command_2/Rules_Selection_Packets.json",
        "packet_registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
        "foundation_id": foundation_id,
        "foundation_name": foundation_name,
        "foundation_packet_id": foundation_packet_id,
        "foundation_authority_path": _PACKET_FOUNDATION_SOURCE_PATH,
        "foundation_authority_sha256": _PACKET_FOUNDATION_SOURCE_SHA256,
        "foundation_authority_anchor": f"foundation:{foundation_id}",
        "selected_grade": grade,
        "selected_stage": stage,
        "projected_foundation": deepcopy(projected_foundation),
    }
    _write_json(details_path, provenance)
    _write_json(ledger_path, projected_ledger)
    _write_json(mirror_path, projected_mirror)
    reread = _read_json(ledger_path, code="FINAL_CHARACTER_FOUNDATION_PROJECTION_INVALID")
    mirror_reread = _read_json(mirror_path, code="FINAL_CHARACTER_FOUNDATION_PROJECTION_INVALID")
    if reread != projected_ledger or mirror_reread != projected_mirror or raw_provenance_path.read_bytes() != raw_provenance_bytes:
        raise invalid("The Foundation projection could not be read back exactly or altered raw provenance.")
    return {
        "schema_version": provenance["schema_version"],
        "source_ledger_path": provenance["source_ledger_path"],
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_provenance_sha256,
        "details_path": _FOUNDATION_PROJECTION_DETAILS_RELATIVE,
        "details_sha256": sha256_file(details_path),
        "foundation_id": foundation_id,
        "foundation_name": foundation_name,
        "foundation_packet_id": foundation_packet_id,
        "foundation_authority_path": _PACKET_FOUNDATION_SOURCE_PATH,
        "foundation_authority_sha256": _PACKET_FOUNDATION_SOURCE_SHA256,
        "foundation_authority_anchor": f"foundation:{foundation_id}",
        "selected_grade": grade,
        "selected_stage": stage,
        "projected_foundation": deepcopy(projected_foundation),
    }


_FOUNDATION_MIRROR_DISPLAY_FIELDS = frozenset({
    "display_only_not_execution_authority",
    "full_description",
    "full_description_source",
    "source_anchor",
    "source_hash",
    "source_path",
})


def _foundation_mirror_authority_fields(mirror: Mapping[str, Any], raw: Mapping[str, Any]) -> dict[str, Any]:
    """Reduce the GM Foundation display mirror to the ledger's authority fields.

    The detail mirror is a display projection: it may add the explicit
    display-only fields above (only when it declares itself display-only) and
    it spells the source as ``{anchor, path, sha256}``.  That source form is
    accepted only when it names exactly the ledger's artifact and hash.
    """

    value = dict(mirror)
    extras = set(value) & _FOUNDATION_MIRROR_DISPLAY_FIELDS
    if extras and value.get("display_only_not_execution_authority") is not True:
        return value
    for key in extras:
        value.pop(key)
    raw_source = raw.get("source")
    mirror_source = value.get("source")
    if (
        isinstance(raw_source, Mapping)
        and isinstance(mirror_source, Mapping)
        and set(mirror_source) == {"anchor", "path", "sha256"}
        and mirror_source.get("path") == raw_source.get("artifact")
        and mirror_source.get("sha256") == raw_source.get("artifact_sha256")
        and isinstance(mirror_source.get("anchor"), str)
        and mirror_source["anchor"].strip()
    ):
        value["source"] = deepcopy(dict(raw_source))
    return value


def _project_foundation_for_compiler(workspace: Path) -> dict[str, Any]:
    """Project a selected Foundation from its source row and causal packet.

    Furnace Heart's historical acquisition-only bytes continue through the
    frozen bridge above.  Every other row uses the same packet/source checks,
    and a mechanical row additionally has to carry the installed initial-state
    proof produced by the Foundation authority.  This adapter renders the
    compiler fields only; it never promotes a stage or changes a current pool.
    """

    root = Path(workspace)
    raw_path = root / _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    try:
        raw_value = _read_json(raw_path, code="FINAL_CHARACTER_FOUNDATION_PROJECTION_INVALID")
    except FoundryError:
        raw_value = None
    raw_foundation = raw_value.get("foundation") if isinstance(raw_value, Mapping) else None
    if (
        isinstance(raw_foundation, Mapping)
        and raw_foundation.get("record_id") == "furnace_heart_record_v0_2B"
        and raw_foundation.get("mechanical_projection") is not True
        and not isinstance(raw_foundation.get("mechanics"), Mapping)
    ):
        return _project_foundation_for_compiler_fixed(workspace)

    def invalid(message: str, *, details: Any = None) -> FoundryError:
        return _error("FINAL_CHARACTER_FOUNDATION_PROJECTION_INVALID", message, details=details)

    ledger_path = root / "Build/Character_Master_Ledger.json"
    mirror_path = root / "Build/Foundation_Detail_Ledger.json"
    registry_path = root / "Command_2/Rules_Selection_Packets.json"
    build_registry_path = root / "Build/Rules_Selection_Packets.json"
    details_path = root / _FOUNDATION_PROJECTION_DETAILS_RELATIVE
    for path in (ledger_path, raw_path, mirror_path, registry_path):
        if path.is_symlink() or not path.is_file():
            raise invalid("The copied Foundation projection inputs are missing or unsafe.", details={"path": str(path)})
    if details_path.is_symlink() or details_path.exists():
        raise invalid("The copied workspace already contains Foundation projection provenance.")
    if build_registry_path.is_symlink() or (build_registry_path.exists() and not build_registry_path.is_file()):
        raise invalid("The copied Build packet registry is unsafe.", details={"path": str(build_registry_path)})
    try:
        raw_bytes = raw_path.read_bytes()
        raw_sha = hashlib.sha256(raw_bytes).hexdigest()
        raw_ledger = _read_json(raw_path, code="FINAL_CHARACTER_FOUNDATION_PROJECTION_INVALID")
        ledger = _read_json(ledger_path, code="FINAL_CHARACTER_FOUNDATION_PROJECTION_INVALID")
        mirror = _read_json(mirror_path, code="FINAL_CHARACTER_FOUNDATION_PROJECTION_INVALID")
        registry = _read_json(registry_path, code="FINAL_CHARACTER_FOUNDATION_PROJECTION_INVALID")
        build_registry = _read_json(build_registry_path, code="FINAL_CHARACTER_FOUNDATION_PROJECTION_INVALID") if build_registry_path.exists() else None
    except (OSError, FoundryError) as exc:
        if isinstance(exc, FoundryError):
            raise invalid("The copied Foundation projection inputs could not be read.", details={"cause": exc.code}) from exc
        raise invalid("The copied Foundation projection inputs could not be read.") from exc
    if not all(isinstance(value, Mapping) for value in (raw_ledger, ledger, mirror, registry)):
        raise invalid("The copied Foundation projection inputs must be mappings.")
    if mirror.get("schema_version") != "TianxiaFoundry.CharacterGMFoundation.v1":
        raise invalid("The copied Foundation detail mirror has an unsupported schema.")
    if build_registry is not None and build_registry != registry:
        raise invalid("The Build and Command 2 packet registries diverge.")
    packets = registry.get("packets")
    if registry.get("schema_version") != "TianxiaFoundry.RulesSelectionPackets.v2" or not isinstance(packets, list):
        raise invalid("The copied packet registry is not the sealed modern schema.")
    packet_by_id: dict[str, Mapping[str, Any]] = {}
    for index, packet in enumerate(packets):
        if not isinstance(packet, Mapping) or not isinstance(packet.get("packet_id"), str) or not packet.get("packet_id").strip():
            raise invalid("A Foundation packet has no stable packet ID.", details={"index": index})
        if packet["packet_id"] in packet_by_id:
            raise invalid("The Foundation packet registry contains duplicate packet IDs.")
        packet_by_id[packet["packet_id"]] = packet
    raw_foundation = raw_ledger.get("foundation")
    current_foundation = ledger.get("foundation")
    mirror_foundation = mirror.get("foundation")
    if not all(isinstance(value, Mapping) for value in (raw_foundation, current_foundation, mirror_foundation)):
        raise invalid("The copied Foundation rows are missing or not mappings.")
    compiler_fields = {
        "foundation_id", "allocation_id", "name", "chosen_foundation", "grade", "stage", "gained_at_cl",
        "mortal_exception_source_packet_id", "benefits", "foundation_resource", "actions", "burdens",
        "stage_benefit_map", "primary_resource_modifiers", "lifecycle_coverage", "suppressed_or_excluded_benefits",
        "fixed_scope", "ai_notes",
    }
    raw_stripped = {key: value for key, value in raw_foundation.items() if key not in compiler_fields}
    for label, row in (("copied", current_foundation), ("mirror", mirror_foundation)):
        stripped = {key: value for key, value in row.items() if key not in compiler_fields}
        if label == "mirror":
            stripped = _foundation_mirror_authority_fields(stripped, raw_stripped)
        if stripped != raw_stripped:
            raise invalid("The copied Foundation surface diverges from raw provenance.", details={"label": label})
    source_packet_ids = raw_foundation.get("source_packet_ids")
    if (
        not isinstance(source_packet_ids, list)
        or len(source_packet_ids) != 1
        or not isinstance(source_packet_ids[0], str)
        or not source_packet_ids[0].strip()
    ):
        raise invalid("The selected Foundation must bind exactly one acquisition packet.")
    foundation_packet_id = source_packet_ids[0]
    for label, row in (("copied", current_foundation), ("mirror", mirror_foundation)):
        if row.get("source_packet_ids") != source_packet_ids:
            raise invalid("The copied Foundation source packet binding diverges.", details={"label": label})
        for field in ("record_id", "display_name", "event_id", "record_hash"):
            if row.get(field) != raw_foundation.get(field):
                raise invalid("The copied Foundation identity diverges from raw provenance.", details={"label": label, "field": field})
    if any(not isinstance(raw_foundation.get(field), str) or not raw_foundation.get(field).strip() for field in ("record_id", "display_name", "event_id", "record_hash")):
        raise invalid("The selected Foundation identity is incomplete.")
    foundation_id = raw_foundation["record_id"]
    foundation_name = raw_foundation["display_name"]
    fixed_registry = _bridge_fixed_factory_json(_PACKET_FOUNDATION_SOURCE_PATH, _PACKET_FOUNDATION_SOURCE_SHA256)
    fixed_rows = fixed_registry.get("foundations") if isinstance(fixed_registry, Mapping) else None
    if (
        not isinstance(fixed_registry, Mapping)
        or fixed_registry.get("schema") != "HF05ZVK-R1F.AuthoritativeFoundationRuntimeCatalog.v1"
        or fixed_registry.get("status") != "AUTHORITATIVE_30_ONLY"
        or not isinstance(fixed_rows, list)
    ):
        raise invalid("The fixed Foundation authority is unavailable or malformed.")
    fixed_ids = [row.get("foundation_id") for row in fixed_rows if isinstance(row, Mapping)]
    if len(fixed_ids) != len(fixed_rows) or any(not isinstance(value, str) or not value.strip() for value in fixed_ids) or len(set(fixed_ids)) != len(fixed_ids):
        raise invalid("The fixed Foundation authority has malformed or duplicate IDs.")
    fixed_matches = [row for row in fixed_rows if isinstance(row, Mapping) and row.get("foundation_id") == foundation_id]
    if len(fixed_matches) != 1 or fixed_matches[0].get("name") != foundation_name:
        raise invalid("The selected Foundation is not the unique hash-pinned canonical authority.", details={"foundation_id": foundation_id})
    fixed_foundation = fixed_matches[0]
    packet = packet_by_id.get(foundation_packet_id)
    binding = packet.get("content_binding") if isinstance(packet, Mapping) else None
    evidence = packet.get("source_evidence") if isinstance(packet, Mapping) else None
    evidence_row = evidence[0] if isinstance(evidence, list) and len(evidence) == 1 and isinstance(evidence[0], Mapping) else None
    packet_version = binding.get("pack_version") if isinstance(binding, Mapping) else None
    mechanics_version = "0.4C-mechanics.1"
    mechanical_foundation = raw_foundation.get("mechanical_projection") is True or isinstance(raw_foundation.get("mechanics"), Mapping) or packet_version == mechanics_version
    modern_source_path = None
    modern_source_hash = None
    modern_source_summary = None
    if mechanical_foundation:
        try:
            from non_sphere_authority.foundation_mechanics import verified_foundation_records

            modern_source_record = verified_foundation_records().get(foundation_id)
        except FoundryError as exc:
            raise invalid("The installed Foundation source release could not be verified.", details={"cause": exc.code}) from exc
        modern_source = modern_source_record.get("source") if isinstance(modern_source_record, Mapping) else None
        if (
            not isinstance(modern_source_record, Mapping)
            or modern_source_record.get("display_name") != foundation_name
            or not isinstance(modern_source, Mapping)
            or not isinstance(modern_source.get("artifact"), str)
            or not modern_source.get("artifact").strip()
            or not isinstance(modern_source.get("artifact_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", modern_source.get("artifact_sha256"))
            or not isinstance(modern_source_record.get("summary"), str)
            or not modern_source_record.get("summary").strip()
        ):
            raise invalid("The installed Foundation source release has incomplete packet bindings.", details={"foundation_id": foundation_id})
        modern_source_path = modern_source["artifact"]
        modern_source_hash = modern_source["artifact_sha256"]
        modern_source_summary = modern_source_record["summary"]
    expected_packet_source_path = modern_source_path if mechanical_foundation else _PACKET_FOUNDATION_SOURCE_PATH
    expected_packet_source_hash = modern_source_hash if mechanical_foundation else _PACKET_FOUNDATION_SOURCE_SHA256
    expected_overview = canonical_json(fixed_foundation.get("overview")) if isinstance(fixed_foundation.get("overview"), Mapping) else None
    expected_packet_description = modern_source_summary if mechanical_foundation else expected_overview
    expected_target_cl = 5 if mechanical_foundation else 1
    if (
        packet is None
        or packet.get("record_id") != foundation_id
        or packet.get("display_name") != foundation_name
        or packet.get("advancement_kind") != "foundation_acquisition"
        or packet.get("target_cl") != expected_target_cl
        or packet.get("event_id") != raw_foundation["event_id"]
        or packet.get("record_hash") != raw_foundation["record_hash"]
        or not isinstance(binding, Mapping)
        or binding.get("record_hash") != raw_foundation["record_hash"]
        or not isinstance(evidence_row, Mapping)
        or evidence_row.get("source_path") != expected_packet_source_path
        or evidence_row.get("source_hash") != expected_packet_source_hash
        or evidence_row.get("source_anchor") != f"foundation:{foundation_id}"
        or evidence_row.get("source_id") != f"source.{expected_packet_source_hash[:24]}"
        or packet.get("full_description") != expected_packet_description
        or packet.get("short_description") != expected_packet_description[:500]
    ):
        raise invalid("The selected Foundation packet is not the exact hash-pinned event binding.", details={"packet_id": foundation_packet_id})
    if mechanical_foundation:
        if (
            binding.get("pack_id") != "tianxia.non_sphere.authority"
            or packet_version != mechanics_version
            or raw_foundation.get("mechanical_projection") is not True
            or raw_foundation.get("mechanics_schema") != "TianxiaFoundry.InitialFoundationMechanics.v1"
            or raw_foundation.get("state") not in {"active", "acquired"}
            or not isinstance(raw_foundation.get("mechanics"), Mapping)
        ):
            raise invalid("The selected Foundation lacks an installed initial-mechanics source/version binding.")
    elif (
        binding.get("pack_id") not in (None, "tianxia.non_sphere.authority")
        or binding.get("pack_version") not in (None, "P2A")
    ):
        raise invalid("A historical Foundation packet has an unsupported source/version binding.", details={"packet_id": foundation_packet_id})

    profile = fixed_foundation.get("profile")
    overview = fixed_foundation.get("overview")
    resource = fixed_foundation.get("resource")
    features = fixed_foundation.get("features")
    compatibility = fixed_foundation.get("compatibility")
    risks = fixed_foundation.get("risks")
    repair_practices = fixed_foundation.get("repair_practices")
    challenges = fixed_foundation.get("foundation_challenges")
    if not all(isinstance(value, Mapping) for value in (profile, overview, resource, features, compatibility, risks)) or not isinstance(repair_practices, list) or not isinstance(challenges, list):
        raise invalid("The fixed Foundation compiler inputs are incomplete.")
    if not isinstance(profile.get("grade"), str) or not profile["grade"].strip() or not isinstance(profile.get("default_stage"), str) or not profile["default_stage"].strip() or not isinstance(resource.get("name"), str) or not resource["name"].strip() or not isinstance(resource.get("gain"), str) or not resource["gain"].strip():
        raise invalid("The fixed Foundation compiler inputs have incomplete profile/resource fields.")
    grade = profile["grade"]
    selected_stage = raw_foundation.get("stage") if mechanical_foundation else profile["default_stage"]
    if not isinstance(selected_stage, str) or not selected_stage.strip():
        raise invalid("The selected Foundation has no explicit initial stage.")

    # The character Path rows provide the set used to authenticate an
    # installed Foundation's supported expressions.  A legacy fixture can
    # omit them; modern mechanics cannot.
    raw_character = raw_ledger.get("character")
    raw_path_rows = raw_character.get("paths") if isinstance(raw_character, Mapping) else None
    selected_path_ids = [row.get("path_id") for row in raw_path_rows] if isinstance(raw_path_rows, list) else []
    if mechanical_foundation:
        if not selected_path_ids or any(not isinstance(value, str) or not value.strip() for value in selected_path_ids) or len(selected_path_ids) != len(set(selected_path_ids)):
            raise invalid("The installed Foundation has no complete selected Path authority.")
        mechanics = raw_foundation.get("mechanics")
        initial_state = mechanics.get("initial_state") if isinstance(mechanics, Mapping) else None
        if not isinstance(initial_state, Mapping) or initial_state.get("foundation_id") != foundation_id or initial_state.get("stage") != selected_stage or initial_state.get("refill_current") is not False or initial_state.get("awards_stage_advancement") is not False:
            raise invalid("The installed Foundation initial state is incomplete or has been promoted.")
        try:
            from non_sphere_authority.foundation_mechanics import resolve_initial_foundation_mechanics, verified_foundation_records

            source_record = verified_foundation_records().get(foundation_id)
            if source_record is None:
                raise invalid("The installed Foundation source record is unavailable.")
            expected_mechanics = resolve_initial_foundation_mechanics(source_record, selected_path_ids, stage=selected_stage)
        except FoundryError as exc:
            raise invalid("The installed Foundation mechanics could not be independently derived.", details={"cause": exc.code}) from exc
        if canonical_json(mechanics) != canonical_json(expected_mechanics):
            raise invalid("The installed Foundation mechanics do not match the pinned source record.")
        active_paths = initial_state.get("active_expression_path_ids")
        if not isinstance(active_paths, list) or any(path_id not in selected_path_ids for path_id in active_paths) or len(active_paths) != len(set(active_paths)):
            raise invalid("The installed Foundation active-expression bindings are incomplete.")

    stage_rows: dict[str, list[Mapping[str, Any]]] = {}
    canonical_stage_names = ("Awakened", "Refined", "Perfected", "Integrated")
    for stage_name in canonical_stage_names:
        source_rows = features.get(stage_name.casefold())
        if not isinstance(source_rows, list) or any(not isinstance(row, Mapping) or not isinstance(row.get("name"), str) or not row["name"].strip() or not isinstance(row.get("effect"), str) or not row["effect"].strip() for row in source_rows):
            raise invalid("The fixed Foundation feature authority is incomplete.", details={"stage": stage_name})
        stage_rows[stage_name] = list(source_rows)
    selected_benefits: list[str]
    selected_source_rows: list[Mapping[str, Any]]
    if selected_stage in stage_rows:
        selected_source_rows = stage_rows[selected_stage]
        selected_benefits = [row["effect"] for row in selected_source_rows]
    elif mechanical_foundation:
        # Unstable/Latent are explicit initial states.  Keep their published
        # conditional source definitions, but never borrow a later stage's
        # benefits.  A compiler requiring three benefits will fail closed if
        # this state has fewer than three source-backed available definitions.
        available = [
            passive.get("source_fields", {}).get("Effect")
            for passive in (raw_foundation.get("mechanics") or {}).get("source_passives", [])
            if isinstance(passive, Mapping) and isinstance(passive.get("source_fields"), Mapping) and isinstance(passive.get("source_fields", {}).get("Effect"), str) and passive.get("source_fields", {}).get("Effect").strip()
        ]
        selected_source_rows = []
        selected_benefits = list(dict.fromkeys(available))
    else:
        selected_source_rows = []
        selected_benefits = []
    if not selected_benefits:
        raise invalid("The selected initial Foundation stage has no source-backed compiler benefits.", details={"stage": selected_stage})
    if not isinstance(compatibility.get("legal_spheres"), list) or not isinstance(compatibility.get("does_not_grant"), list) or any(not isinstance(value, str) or not value.strip() for value in (*compatibility["legal_spheres"], *compatibility["does_not_grant"])):
        raise invalid("The fixed Foundation scope authority is malformed.")
    for key in ("burdens", "hidden_injuries", "strains", "deviations"):
        if not isinstance(risks.get(key), list) or any(not isinstance(row, Mapping) for row in risks[key]):
            raise invalid("The fixed Foundation risk authority is malformed.", details={"field": key})
    def integer_text(value: Any, *, label: str) -> int:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value):
            raise invalid("The fixed Foundation resource counter is not a sealed non-negative integer.", details={"label": label, "value": value})
        return int(value)
    source_resource_current = integer_text(resource.get("starting"), label="starting")
    source_resource_max = integer_text(resource.get("maximum"), label="maximum")
    if source_resource_current > source_resource_max:
        raise invalid("The fixed Foundation resource counters are inconsistent.")
    raw_resource = raw_foundation.get("resource")
    if mechanical_foundation:
        if not isinstance(raw_resource, Mapping) or any(key not in raw_resource for key in ("current", "maximum")):
            raise invalid("The installed Foundation resource state is incomplete.")
        mechanics_resource = initial_state.get("resource") if isinstance(initial_state, Mapping) else None
        authenticated_maximum = mechanics_resource.get("maximum") if isinstance(mechanics_resource, Mapping) else None
        if type(authenticated_maximum) is not int:
            raise invalid("The installed Foundation initial mechanics have no authenticated resource maximum.")
        current_resource = raw_resource
    else:
        current_resource = raw_resource if isinstance(raw_resource, Mapping) else {}
    resource_current = current_resource.get("current", source_resource_current)
    resource_max = current_resource.get("maximum", source_resource_max)
    if type(resource_current) is not int or type(resource_max) is not int or resource_current < 0 or resource_max < 0 or resource_current > resource_max:
        raise invalid("The selected Foundation resource counters are malformed or out of bounds.")
    if mechanical_foundation and resource_max != authenticated_maximum:
        raise invalid("The installed Foundation resource maximum does not match its authenticated initial mechanics.")
    actions = [row["name"] for row in selected_source_rows if row.get("type") != "No Action / Triggered"]
    burden_rows = risks["burdens"]
    hidden_rows = risks["hidden_injuries"]
    strain_rows = risks["strains"]
    deviation_rows = risks["deviations"]
    repair_entries = [deepcopy(row) for row in repair_practices if isinstance(row, Mapping)]
    if len(repair_entries) != len(repair_practices):
        raise invalid("The fixed Foundation repair authority is malformed.")
    integration_entries = [deepcopy(row) for row in challenges if isinstance(row, Mapping)]

    def lifecycle_row(status: str, entries: list[Any], *, note: Any) -> dict[str, Any]:
        if not isinstance(note, str) or not note.strip():
            raise invalid("The fixed Foundation lifecycle note is empty.")
        refs = deepcopy(source_packet_ids) if status in {"present", "suppressed_by_specific_rule"} else []
        return {"status": status, "entries": deepcopy(entries), "note": note, "source_packet_ids": refs}

    source_note = overview.get("summary")
    if not isinstance(source_note, str) or not source_note.strip():
        raise invalid("The fixed Foundation overview has no source-backed summary.")
    lifecycle = {
        "passive_chassis": lifecycle_row("present", selected_benefits, note=profile.get("typical_role") or source_note),
        "resources": lifecycle_row("present", [deepcopy(resource)], note=resource["gain"]),
        "actions_reactions": lifecycle_row("present", [deepcopy(row) for row in selected_source_rows if row.get("type") != "No Action / Triggered"], note=overview.get("warning") or source_note) if actions else lifecycle_row("none_in_source", [], note=overview.get("warning") or source_note),
        "states": lifecycle_row("none_in_source", [], note=overview.get("visible_sign") or source_note),
        "burdens": lifecycle_row("present", [deepcopy(row) for row in burden_rows], note=source_note),
        "hidden_injuries": lifecycle_row("present", [deepcopy(row) for row in hidden_rows], note=source_note),
        "strains": lifecycle_row("present", [deepcopy(row) for row in strain_rows], note=source_note),
        "deviations": lifecycle_row("present", [deepcopy(row) for row in deviation_rows], note=source_note),
        "integration": lifecycle_row("present", integration_entries, note=(integration_entries[0].get("effect") if integration_entries and isinstance(integration_entries[0].get("effect"), str) else source_note)) if integration_entries else lifecycle_row("none_in_source", [], note=source_note),
        "repair": lifecycle_row("present", repair_entries, note=(repair_entries[0].get("effect") if repair_entries and isinstance(repair_entries[0].get("effect"), str) else source_note)) if repair_entries else lifecycle_row("none_in_source", [], note=source_note),
        "treatment": lifecycle_row("present", [row["treatment"] for row in burden_rows if isinstance(row.get("treatment"), str) and row["treatment"].strip()], note=source_note) if any(isinstance(row.get("treatment"), str) and row["treatment"].strip() for row in burden_rows) else lifecycle_row("none_in_source", [], note=source_note),
        "temptations": lifecycle_row("present", [row["temptation"] for row in deviation_rows if isinstance(row.get("temptation"), str) and row["temptation"].strip()], note=source_note) if any(isinstance(row.get("temptation"), str) and row["temptation"].strip() for row in deviation_rows) else lifecycle_row("none_in_source", [], note=source_note),
        "failure_consequences": lifecycle_row("present", [value for row in (*burden_rows, *hidden_rows) for value in (row.get("stress_failure"),) if isinstance(value, str) and value.strip()], note=overview.get("warning") or source_note),
    }
    stage_benefit_map = [
        {"stage": stage_name, "available": stage_name == selected_stage, "benefits": deepcopy(selected_benefits if stage_name == selected_stage else []), "source_packet_ids": deepcopy(source_packet_ids)}
        for stage_name in canonical_stage_names
    ]
    if selected_stage not in canonical_stage_names:
        stage_benefit_map.append({"stage": selected_stage, "available": True, "benefits": deepcopy(selected_benefits), "source_packet_ids": deepcopy(source_packet_ids)})

    def pb_at(cl: int) -> int:
        return 2 + (cl - 1) // 4
    primary_resource_modifiers: list[dict[str, Any]] = []
    if mechanical_foundation:
        resource_names = {"tianxia.resource.stamina": "Stamina", "tianxia.resource.qi": "Qi", "tianxia.resource.resonance": "Resonance"}
        for modifier in (raw_foundation.get("mechanics") or {}).get("resource_modifiers", []):
            if not isinstance(modifier, Mapping):
                raise invalid("The installed Foundation resource modifier is malformed.")
            formula = modifier.get("formula")
            terms = ((formula or {}).get("root") or {}).get("terms") if isinstance(formula, Mapping) else None
            units = terms[0].get("value") if isinstance(terms, list) and terms and isinstance(terms[0], Mapping) else None
            resource_id = modifier.get("resource_id")
            if not isinstance(units, int) or resource_id not in resource_names:
                raise invalid("The installed Foundation resource modifier lacks typed source authority.")
            primary_resource_modifiers.append({
                "resource_id": resource_id,
                "resource_name": resource_names[resource_id],
                "operation": "subtract" if units < 0 else "add",
                "amount": abs(units * pb_at(max((row.get("effective_cl") for row in raw_path_rows if isinstance(row, Mapping) and type(row.get("effective_cl")) is int), default=5))),
                "applies_from_cl": 5,
                "expression": f"{units:+d} × current PB from initial Foundation mechanics",
                "formula": deepcopy(formula),
                "source_packet_ids": deepcopy(source_packet_ids),
            })
    suppressed = []
    if mechanical_foundation:
        for passive in (raw_foundation.get("mechanics") or {}).get("conditional_modifiers", []):
            if isinstance(passive, Mapping):
                suppressed.append({"benefit": passive.get("feature_name") or passive.get("statistic"), "reason": passive.get("availability") or "condition_required", "source_packet_ids": deepcopy(source_packet_ids)})
    expected_generated = {
        "foundation_id": foundation_id,
        "allocation_id": f"allocation.foundation.{foundation_packet_id}",
        "name": foundation_name,
        "chosen_foundation": foundation_name,
        "grade": grade,
        "stage": selected_stage,
        "gained_at_cl": packet["target_cl"],
        "benefits": deepcopy(selected_benefits),
        "foundation_resource": {"name": resource["name"], "current": resource_current, "max": resource_max, "generation": resource["gain"]},
        "actions": deepcopy(actions),
        "burdens": [row.get("name") for row in burden_rows if isinstance(row.get("name"), str) and row["name"].strip()],
        "source_packet_ids": deepcopy(source_packet_ids),
        "fixed_scope": deepcopy(compatibility["legal_spheres"]) + deepcopy(compatibility["does_not_grant"]),
        "ai_notes": [value for value in (overview.get("summary"), overview.get("visible_sign"), overview.get("warning"), overview.get("dao_principle")) if isinstance(value, str) and value.strip()],
        "stage_benefit_map": stage_benefit_map,
        "primary_resource_modifiers": primary_resource_modifiers,
        "lifecycle_coverage": lifecycle,
        "suppressed_or_excluded_benefits": suppressed,
    }
    if packet["target_cl"] < 5:
        expected_generated["mortal_exception_source_packet_id"] = foundation_packet_id
    # The installed modern state already carries these two identities as
    # provenance.  They are also compiler fields, but their presence alone
    # is not evidence of a partial compiler overlay.
    compiler_projection_fields = set(expected_generated) - {"source_packet_ids", "foundation_id", "stage"}
    def validate_existing_projection(row: Mapping[str, Any], *, label: str) -> None:
        present = compiler_projection_fields.intersection(row)
        if present and present != compiler_projection_fields:
            raise invalid("An existing Foundation compiler projection is partial.", details={"label": label, "fields": sorted(present)})
        for field in present:
            if row.get(field) != expected_generated[field]:
                raise invalid("An existing Foundation compiler projection conflicts with fixed authority.", details={"label": label, "field": field})
    for label, row in (("raw", raw_foundation), ("copied", current_foundation), ("mirror", mirror_foundation)):
        validate_existing_projection(row, label=label)
    raw_binding = deepcopy(dict(raw_foundation))
    current_binding = deepcopy(dict(current_foundation))
    mirror_binding = deepcopy(dict(mirror_foundation))
    for value in (raw_binding, current_binding, mirror_binding):
        for field in compiler_projection_fields:
            value.pop(field, None)
    mirror_binding = _foundation_mirror_authority_fields(mirror_binding, raw_binding)
    if current_binding != raw_binding or mirror_binding != raw_binding:
        raise invalid("The copied Foundation master/mirror surfaces diverge from raw modern provenance.")
    projected_foundation = deepcopy(dict(current_foundation))
    projected_foundation.update(deepcopy(expected_generated))
    projected_ledger = deepcopy(dict(ledger)); projected_ledger["foundation"] = projected_foundation
    projected_mirror = deepcopy(dict(mirror)); projected_mirror["foundation"] = deepcopy(projected_foundation)
    provenance = {
        "schema_version": "TianxiaFoundry.FinalCharacterFoundationProjectionProvenance.v1",
        "source_ledger_path": "Build/Character_Master_Ledger.json",
        "source_ledger_sha256": raw_sha,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_sha,
        "packet_registry_path": "Command_2/Rules_Selection_Packets.json",
        "packet_registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
        "foundation_id": foundation_id,
        "foundation_name": foundation_name,
        "foundation_packet_id": foundation_packet_id,
        "foundation_authority_path": _PACKET_FOUNDATION_SOURCE_PATH,
        "foundation_authority_sha256": _PACKET_FOUNDATION_SOURCE_SHA256,
        "foundation_authority_anchor": f"foundation:{foundation_id}",
        "selected_grade": grade,
        "selected_stage": selected_stage,
        "mechanics_version": mechanics_version if mechanical_foundation else (packet_version or "P2A"),
        "projected_foundation": deepcopy(projected_foundation),
    }
    _write_json(details_path, provenance)
    _write_json(ledger_path, projected_ledger)
    _write_json(mirror_path, projected_mirror)
    reread = _read_json(ledger_path, code="FINAL_CHARACTER_FOUNDATION_PROJECTION_INVALID")
    mirror_reread = _read_json(mirror_path, code="FINAL_CHARACTER_FOUNDATION_PROJECTION_INVALID")
    if reread != projected_ledger or mirror_reread != projected_mirror or raw_path.read_bytes() != raw_bytes:
        raise invalid("The Foundation projection could not be read back exactly or altered raw provenance.")
    return {
        "schema_version": provenance["schema_version"],
        "source_ledger_path": provenance["source_ledger_path"],
        "source_ledger_sha256": raw_sha,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_sha,
        "details_path": _FOUNDATION_PROJECTION_DETAILS_RELATIVE,
        "details_sha256": sha256_file(details_path),
        "foundation_id": foundation_id,
        "foundation_name": foundation_name,
        "foundation_packet_id": foundation_packet_id,
        "foundation_authority_path": _PACKET_FOUNDATION_SOURCE_PATH,
        "foundation_authority_sha256": _PACKET_FOUNDATION_SOURCE_SHA256,
        "foundation_authority_anchor": f"foundation:{foundation_id}",
        "selected_grade": grade,
        "selected_stage": selected_stage,
        "mechanics_version": mechanics_version if mechanical_foundation else (packet_version or "P2A"),
        "projected_foundation": deepcopy(projected_foundation),
    }


def _project_modern_hp_for_compiler(
    workspace: Path,
    *,
    path_projection: Mapping[str, Any] | None = None,
    foundation_projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project authenticated modern HP progression into compiler fields.

    The modern ledger stores per-level ``gain``/``max_after_level`` values,
    while the pinned compiler requires the die, fixed-average mode, and an
    explicit decomposition of each increase.  This boundary derives only
    from the sealed level arithmetic and the fixed active Path hit die.  An
    authenticated initial Foundation may contribute a typed, one-character
    maximum modifier at its published acquisition CL; the resulting change is
    applied only at acquisition and proficiency-bonus thresholds.  The one
    observed retroactive Constitution increase is accepted only when the exact
    CL8 ASI event and its separate ability-score-change packet prove it; every
    other non-zero ``other_delta`` is rejected.
    """

    def invalid(message: str, *, details: Any = None) -> FoundryError:
        return _error("FINAL_CHARACTER_HP_PROJECTION_INVALID", message, details=details)

    root = Path(workspace)
    ledger_path = root / "Build/Character_Master_Ledger.json"
    raw_provenance_path = root / _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    path_details_path = root / _PATH_PROJECTION_DETAILS_RELATIVE
    details_path = root / _HP_PROJECTION_DETAILS_RELATIVE
    for path in (ledger_path, raw_provenance_path, path_details_path):
        if path.is_symlink() or not path.is_file():
            raise invalid("The copied Path projection provenance is missing or unsafe.", details={"path": str(path)})
    if details_path.exists():
        raise invalid("The copied workspace already contains HP projection provenance.")

    try:
        raw_provenance_bytes = raw_provenance_path.read_bytes()
        raw_provenance_sha256 = hashlib.sha256(raw_provenance_bytes).hexdigest()
        raw_ledger = _read_json(raw_provenance_path, code="FINAL_CHARACTER_HP_PROJECTION_INVALID")
        path_details = _read_json(path_details_path, code="FINAL_CHARACTER_HP_PROJECTION_INVALID")
        ledger = _read_json(ledger_path, code="FINAL_CHARACTER_HP_PROJECTION_INVALID")
    except (OSError, FoundryError) as exc:
        if isinstance(exc, FoundryError):
            raise invalid("The copied HP projection provenance could not be read.", details={"cause": exc.code}) from exc
        raise invalid("The copied HP projection provenance could not be read.") from exc
    if not isinstance(raw_ledger, Mapping) or not isinstance(path_details, Mapping) or not isinstance(ledger, Mapping):
        raise invalid("The copied HP projection inputs must be mappings.")
    if path_projection is not None:
        if not isinstance(path_projection, Mapping):
            raise invalid("The Path projection result is not a mapping.")
        if (
            path_projection.get("source_ledger_sha256") != raw_provenance_sha256
            or path_projection.get("modern_provenance_sha256") != raw_provenance_sha256
            or path_projection.get("details_sha256") != sha256_file(path_details_path)
            or path_details.get("source_ledger_sha256") != raw_provenance_sha256
        ):
            raise invalid("The HP projection is not bound to the original modern ledger bytes.")
    elif path_details.get("source_ledger_sha256") != raw_provenance_sha256:
        raise invalid("The copied Path projection details are not bound to their raw ledger provenance.")

    raw_character = raw_ledger.get("character")
    character = ledger.get("character")
    raw_core_stats = raw_ledger.get("core_stats")
    core_stats = ledger.get("core_stats")
    if (
        not isinstance(raw_character, Mapping)
        or not isinstance(character, Mapping)
        or not isinstance(raw_core_stats, Mapping)
        or not isinstance(core_stats, Mapping)
    ):
        raise invalid("The copied ledger has no character/core-stat HP authority.")
    path_id = raw_character.get("path_id")
    path_name = raw_character.get("path")
    target_cl = raw_character.get("cl")
    if (
        not isinstance(path_id, str)
        or not path_id.strip()
        or not isinstance(path_name, str)
        or not path_name.strip()
        or type(target_cl) is not int
        or not 1 <= target_cl <= 20
        or character.get("path_id") != path_id
        or character.get("path") != path_name
        or character.get("cl") != target_cl
        or path_details.get("path_id") != path_id
        or path_details.get("path_name") != path_name
        or (path_projection is not None and path_projection.get("path_id") != path_id)
    ):
        raise invalid("The copied active Path identity diverges from HP provenance.", details={"path_id": path_id})
    proof = _PACKET_PATH_PROOFS.get(path_id)
    if proof is None:
        raise invalid("The active Path is not one fixed canonical Path.", details={"path_id": path_id})

    # Re-prove the small fixed Path identity needed for HP.  The full Path
    # event projection has already authenticated this data, but this helper
    # must not allow an unrelated caller-supplied result to establish a hit
    # die or active Path.
    path_index = _bridge_fixed_json(proof["index_path"], proof["index_sha256"])
    path_master = _bridge_fixed_json(_PACKET_PATH_MASTER_PATH, _PACKET_PATH_MASTER_SHA256)
    if not isinstance(path_index, Mapping) or not isinstance(path_master, Mapping):
        raise invalid("The fixed active Path authority is unavailable or unsafe.", details={"path_id": path_id})
    master_rows = path_master.get("paths")
    master_matches = [
        row for row in master_rows
        if isinstance(row, Mapping) and row.get("canonical_id") == path_id
    ] if isinstance(master_rows, list) else []
    path_profile = path_index.get("path_profile")
    master_row = master_matches[0] if len(master_matches) == 1 else None
    index_source = path_index.get("source")
    master_source = master_row.get("source") if isinstance(master_row, Mapping) else None
    if (
        len(master_matches) != 1
        or path_index.get("canonical_id") != path_id
        or path_index.get("display_name") != path_name
        or path_index.get("publication_status") != "current_canonical_player_path"
        or master_row.get("display_name") != path_name
        or master_row.get("index_file") != proof["index_file"]
        or not isinstance(path_profile, Mapping)
        or not isinstance(index_source, Mapping)
        or not isinstance(master_source, Mapping)
        or index_source.get("corpus_path") != proof["corpus_path"]
        or index_source.get("sha256") != proof["corpus_sha256"]
        or master_source.get("corpus_path") != proof["corpus_path"]
        or master_source.get("sha256") != proof["corpus_sha256"]
        or path_profile.get("hit_die") != master_row.get("hit_die")
    ):
        raise invalid("The fixed active Path hit-die authority is malformed or diverges from the Path projection.", details={"path_id": path_id})
    hit_die = path_profile.get("hit_die")
    die_match = re.fullmatch(r"d([1-9][0-9]*)", hit_die) if isinstance(hit_die, str) else None
    if die_match is None:
        raise invalid("The fixed active Path hit die is malformed.", details={"path_id": path_id})
    die_size = int(die_match.group(1))
    fixed_average = max(1, die_size // 2 + 1)

    # Foundation mechanics are an independent source/event input.  Consume
    # only the already-authenticated Foundation projection and bind it to the
    # same raw ledger bytes before deriving any HP maximum contribution.  A
    # modern installed Foundation without that projection must fail closed;
    # falling back to a copied numeric row would make the HP adapter a second
    # authority.
    raw_foundation = raw_ledger.get("foundation")
    current_foundation = ledger.get("foundation")
    modern_foundation = (
        isinstance(raw_foundation, Mapping)
        and (
            raw_foundation.get("mechanical_projection") is True
            or isinstance(raw_foundation.get("mechanics"), Mapping)
        )
    )
    if modern_foundation and foundation_projection is None:
        raise invalid("The modern Foundation HP mechanics are missing their authenticated projection.")
    foundation_adjustment_by_cl: dict[int, int] = {}
    foundation_total_by_cl: dict[int, int] = {}
    foundation_packet_ids: list[str] = []
    foundation_gained_at_cl: int | None = None
    foundation_modifier_units = 0
    foundation_details: Mapping[str, Any] | None = None
    if foundation_projection is not None:
        if not isinstance(foundation_projection, Mapping):
            raise invalid("The Foundation projection result is not a mapping.")
        foundation_details_path = root / _FOUNDATION_PROJECTION_DETAILS_RELATIVE
        if foundation_details_path.is_symlink() or not foundation_details_path.is_file():
            raise invalid("The Foundation projection provenance is missing or unsafe.")
        try:
            foundation_details_value = _read_json(
                foundation_details_path,
                code="FINAL_CHARACTER_HP_PROJECTION_INVALID",
            )
        except FoundryError as exc:
            raise invalid("The Foundation projection provenance could not be read.", details={"cause": exc.code}) from exc
        if not isinstance(foundation_details_value, Mapping):
            raise invalid("The Foundation projection provenance must be a mapping.")
        foundation_details = foundation_details_value
        projected_foundation = foundation_projection.get("projected_foundation")
        details_foundation = foundation_details.get("projected_foundation")
        if (
            foundation_projection.get("source_ledger_sha256") != raw_provenance_sha256
            or foundation_projection.get("modern_provenance_sha256") != raw_provenance_sha256
            or foundation_projection.get("details_path") != _FOUNDATION_PROJECTION_DETAILS_RELATIVE
            or foundation_projection.get("details_sha256") != sha256_file(foundation_details_path)
            or foundation_details.get("source_ledger_sha256") != raw_provenance_sha256
            or foundation_details.get("modern_provenance_sha256") != raw_provenance_sha256
            or not isinstance(projected_foundation, Mapping)
            or details_foundation != projected_foundation
            or not isinstance(current_foundation, Mapping)
            or dict(current_foundation) != dict(projected_foundation)
        ):
            raise invalid("The HP projection is not bound to the authenticated Foundation projection.")
        if modern_foundation and projected_foundation.get("record_id") != raw_foundation.get("record_id"):
            raise invalid("The projected Foundation identity diverges from raw modern provenance.")
        if not modern_foundation:
            if isinstance(raw_foundation, Mapping) and projected_foundation.get("record_id") != raw_foundation.get("record_id"):
                raise invalid("The projected historical Foundation identity diverges from raw provenance.")
        elif not isinstance(raw_foundation, Mapping) or projected_foundation.get("mechanics") != raw_foundation.get("mechanics"):
            raise invalid("The projected Foundation mechanics diverge from raw modern provenance.")

        if modern_foundation:
            source_packet_ids = raw_foundation.get("source_packet_ids") if isinstance(raw_foundation, Mapping) else None
            if (
                not isinstance(source_packet_ids, list)
                or len(source_packet_ids) != 1
                or not isinstance(source_packet_ids[0], str)
                or not source_packet_ids[0].strip()
            ):
                raise invalid("The modern Foundation lacks one authenticated acquisition packet for HP mechanics.")
            foundation_packet_ids = list(source_packet_ids)
            gained_at_cl = projected_foundation.get("gained_at_cl")
            if type(gained_at_cl) is not int or not 1 <= gained_at_cl <= target_cl:
                raise invalid("The modern Foundation acquisition CL is missing or outside the HP progression.")
            registry_path = root / "Command_2/Rules_Selection_Packets.json"
            if registry_path.is_symlink() or not registry_path.is_file():
                raise invalid("The modern Foundation packet registry is missing or unsafe.")
            try:
                foundation_registry = _read_json(
                    registry_path,
                    code="FINAL_CHARACTER_HP_PROJECTION_INVALID",
                )
            except FoundryError as exc:
                raise invalid("The modern Foundation packet registry could not be read.", details={"cause": exc.code}) from exc
            packet_rows = foundation_registry.get("packets") if isinstance(foundation_registry, Mapping) else None
            packet_matches = [
                row for row in packet_rows
                if isinstance(row, Mapping) and row.get("packet_id") == foundation_packet_ids[0]
            ] if isinstance(packet_rows, list) else []
            if len(packet_matches) != 1 or packet_matches[0].get("target_cl") != gained_at_cl or packet_matches[0].get("advancement_kind") != "foundation_acquisition":
                raise invalid("The modern Foundation acquisition packet is not bound to its projected CL.")
            mechanics = raw_foundation.get("mechanics")
            modifiers = mechanics.get("hp_maximum_modifiers") if isinstance(mechanics, Mapping) else None
            if not isinstance(modifiers, list):
                raise invalid("The modern Foundation HP mechanics have no typed modifier list.")
            seen_formula_ids: set[str] = set()
            for modifier in modifiers:
                if not isinstance(modifier, Mapping):
                    raise invalid("The modern Foundation HP modifier is malformed.")
                if modifier.get("statistic") != "hp_maximum" or modifier.get("scope") != "one_character_maximum" or modifier.get("availability") not in (None, "available"):
                    raise invalid("The modern Foundation HP modifier has unsupported scope or availability.")
                formula = modifier.get("formula")
                root_formula = formula.get("root") if isinstance(formula, Mapping) else None
                terms = root_formula.get("terms") if isinstance(root_formula, Mapping) else None
                formula_id = formula.get("formula_id") if isinstance(formula, Mapping) else None
                if (
                    not isinstance(formula, Mapping)
                    or formula.get("schema_version") != "TianxiaFoundry.SafeFormula.v1"
                    or not isinstance(formula_id, str)
                    or not formula_id.strip()
                    or formula_id in seen_formula_ids
                    or not isinstance(root_formula, Mapping)
                    or root_formula.get("op") != "multiply"
                    or not isinstance(terms, list)
                    or len(terms) != 2
                ):
                    raise invalid("The modern Foundation HP formula is not a typed constant-times-PB rule.")
                constants = [
                    term.get("value")
                    for term in terms
                    if isinstance(term, Mapping) and term.get("op") == "constant"
                ]
                pb_terms = [term for term in terms if isinstance(term, Mapping) and term.get("op") == "pb"]
                if len(constants) != 1 or len(pb_terms) != 1 or type(constants[0]) is not int:
                    raise invalid("The modern Foundation HP formula has no unique integer/PB terms.")
                seen_formula_ids.add(formula_id)
                foundation_modifier_units += constants[0]
            for cl in range(1, target_cl + 1):
                total = foundation_modifier_units * (2 + (cl - 1) // 4) if cl >= gained_at_cl else 0
                foundation_total_by_cl[cl] = total
                prior = foundation_total_by_cl.get(cl - 1, 0)
                if total != prior:
                    foundation_adjustment_by_cl[cl] = total - prior
        else:
            foundation_total_by_cl = {cl: 0 for cl in range(1, target_cl + 1)}

    raw_generation = raw_core_stats.get("hp_generation")
    current_generation = core_stats.get("hp_generation")
    if not isinstance(raw_generation, Mapping) or not isinstance(current_generation, Mapping):
        raise invalid("The copied HP generation trace is missing or malformed.")
    generation_allowed = {"levels", "hit_die", "mode"}
    if any(key not in generation_allowed for key in raw_generation):
        raise invalid("The raw HP generation trace has unsupported fields.")
    raw_generation_levels = raw_generation.get("levels")
    if not isinstance(raw_generation_levels, list) or len(raw_generation_levels) != target_cl:
        raise invalid("The raw HP generation trace does not cover the exact CL progression.")
    raw_generation_has_compiler = ("hit_die" in raw_generation or "mode" in raw_generation)
    if raw_generation_has_compiler and (
        raw_generation.get("hit_die") != hit_die
        or raw_generation.get("mode") != "fixed_average"
        or "hit_die" not in raw_generation
        or "mode" not in raw_generation
    ):
        raise invalid("The raw HP generation compiler fields conflict with fixed Path authority.")

    current_generation_allowed = set(raw_generation) | {"hit_die", "mode", "hp_generation_provenance"}
    if any(key not in current_generation_allowed for key in current_generation):
        raise invalid("The copied HP generation has unsupported unbound fields.", details={"fields": sorted(set(current_generation) - current_generation_allowed)})
    if "levels" in current_generation and current_generation.get("levels") != raw_generation_levels:
        raise invalid("The copied HP generation levels diverge from raw modern provenance.")
    if "hp_generation_provenance" in current_generation and current_generation.get("hp_generation_provenance") != dict(raw_generation):
        raise invalid("The retained HP generation provenance diverges from raw modern provenance.")
    current_generation_has_compiler = ("hit_die" in current_generation or "mode" in current_generation)
    if current_generation_has_compiler and (
        "hit_die" not in current_generation
        or "mode" not in current_generation
        or current_generation.get("hit_die") != hit_die
        or current_generation.get("mode") != "fixed_average"
    ):
        raise invalid("The copied HP generation compiler fields conflict with fixed Path authority.")

    raw_advancement = raw_ledger.get("advancement")
    current_advancement = ledger.get("advancement")
    raw_levels = raw_advancement.get("levels") if isinstance(raw_advancement, Mapping) else None
    current_levels = current_advancement.get("levels") if isinstance(current_advancement, Mapping) else None
    if (
        not isinstance(raw_levels, list)
        or len(raw_levels) != target_cl
        or not isinstance(current_levels, list)
        or len(current_levels) != target_cl
    ):
        raise invalid("The copied HP advancement is not an exact CL1-to-current sequence.")
    if [row.get("cl") if isinstance(row, Mapping) else None for row in raw_levels] != list(range(1, target_cl + 1)):
        raise invalid("The copied HP advancement has a gap or out-of-order CL row.")

    # Ability scores after each level are the sealed source of the active
    # Constitution modifier.  Do not infer a retroactive increase from the
    # resulting HP total alone.
    score_keys = set(_CORE_SAVE_ABILITIES)
    raw_scores = raw_core_stats.get("ability_scores")
    current_scores = core_stats.get("ability_scores")
    if not isinstance(raw_scores, Mapping) or set(raw_scores) != score_keys or current_scores != raw_scores:
        raise invalid("The copied HP ability-score authority is incomplete or diverges from raw provenance.")
    if any(type(value) is not int for value in raw_scores.values()):
        raise invalid("The copied HP ability scores must be integers.")
    timeline: list[Mapping[str, Any]] = []
    for index, row in enumerate(raw_levels):
        if not isinstance(row, Mapping):
            raise invalid("The raw HP advancement has a malformed row.", details={"index": index})
        scores_after = row.get("ability_scores_after")
        if not isinstance(scores_after, Mapping) or set(scores_after) != score_keys or any(type(value) is not int for value in scores_after.values()):
            raise invalid("The raw HP advancement ability timeline is incomplete.", details={"cl": row.get("cl")})
        timeline.append(scores_after)
    if timeline[-1] != raw_scores:
        raise invalid("The final HP ability timeline does not match sealed core scores.")
    # Timeline maps do not carry their own CL; derive it from position.
    con_transitions: list[tuple[int, int, int]] = []
    for index, (prior, following) in enumerate(zip(timeline, timeline[1:]), start=2):
        if prior.get("CON") != following.get("CON"):
            con_transitions.append((index, prior["CON"], following["CON"]))

    source_hp_keys = {"formula_id", "gain", "max_after_level", "formula", "source_packet_ids"}
    compiler_hp_keys = {"base_gain", "constitution_delta", "other_delta"}
    allowed_hp_keys = source_hp_keys | compiler_hp_keys
    source_rows: list[dict[str, Any]] = []
    expected_rows: list[dict[str, Any]] = []
    previous_maximum = 0
    for index, (generation_row, raw_level, current_level, scores_after) in enumerate(
        zip(raw_generation_levels, raw_levels, current_levels, timeline),
        start=1,
    ):
        if not isinstance(generation_row, Mapping) or not isinstance(raw_level, Mapping) or not isinstance(current_level, Mapping):
            raise invalid("The copied HP level contains a malformed row.", details={"cl": index})
        if any(key not in {"cl", "formula_id", "gain", "maximum"} for key in generation_row):
            raise invalid("The raw HP generation row contains unsupported fields.", details={"cl": index})
        if {key: value for key, value in current_level.items() if key not in {"hp", "resource", "allocations"}} != {key: value for key, value in raw_level.items() if key not in {"hp", "resource", "allocations"}}:
            raise invalid("The copied HP level diverges from raw modern provenance.", details={"cl": index})
        raw_hp = raw_level.get("hp")
        current_hp = current_level.get("hp")
        if not isinstance(raw_hp, Mapping) or not isinstance(current_hp, Mapping):
            raise invalid("The copied HP level has no structured source arithmetic.", details={"cl": index})
        if any(key not in allowed_hp_keys for key in raw_hp) or any(key not in allowed_hp_keys for key in current_hp):
            raise invalid("The copied HP level contains unsupported fields.", details={"cl": index})
        formula_id = raw_hp.get("formula_id")
        expected_formula_id = f"ns1r.{path_id}.hp.cl1" if index == 1 else f"ns1r.{path_id}.hp.later"
        if (
            formula_id != expected_formula_id
            or generation_row.get("cl") != index
            or generation_row.get("formula_id") != formula_id
            or generation_row.get("gain") != raw_hp.get("gain")
            or generation_row.get("maximum") != raw_hp.get("max_after_level")
            or type(raw_hp.get("gain")) is not int
            or type(raw_hp.get("max_after_level")) is not int
            or raw_hp.get("gain") <= 0
            or raw_hp.get("max_after_level") <= 0
        ):
            raise invalid("The raw HP arithmetic is missing or diverges from the sealed generation trace.", details={"cl": index})
        if "formula" in raw_hp:
            expected_formula = f"{hit_die} maximum at CL1; fixed {fixed_average} thereafter; use the Constitution modifier active at each CL."
            if raw_hp.get("formula") != expected_formula:
                raise invalid("The raw HP formula text is not the fixed Path formula.", details={"cl": index})
        previous_con = timeline[index - 1].get("CON")
        if type(previous_con) is not int:
            raise invalid("The raw HP Constitution timeline is malformed.", details={"cl": index})
        constitution_delta = (previous_con - 10) // 2
        base_gain = die_size if index == 1 else fixed_average
        if raw_hp.get("gain") != base_gain + constitution_delta:
            raise invalid("The raw HP gain does not match fixed die/Constitution arithmetic.", details={"cl": index})
        maximum = raw_hp.get("max_after_level")
        other_delta = maximum - previous_maximum - base_gain - constitution_delta
        foundation_adjustment = foundation_adjustment_by_cl.get(index, 0)
        expected_rows.append({
            "base_gain": base_gain,
            "constitution_delta": constitution_delta,
            "other_delta": other_delta,
            "foundation_adjustment": foundation_adjustment,
            "unattributed_other_delta": other_delta - foundation_adjustment,
            "max_after_level": maximum,
        })
        source_rows.append({"raw": dict(raw_hp), "current": dict(current_hp), "cl": index})
        previous_maximum = maximum
    if not isinstance(raw_core_stats.get("hp_max"), int) or not isinstance(core_stats.get("hp_max"), int) or raw_core_stats.get("hp_max") != core_stats.get("hp_max") or raw_core_stats.get("hp_max") != previous_maximum:
        raise invalid("The sealed HP maximum does not match the progression.")
    raw_hp_current = raw_core_stats.get("hp_current")
    copied_hp_current = core_stats.get("hp_current")
    if (
        type(raw_hp_current) is not int
        or type(copied_hp_current) is not int
        or raw_hp_current != copied_hp_current
        or not 0 <= raw_hp_current <= previous_maximum
    ):
        raise invalid("The copied HP current value diverges from raw provenance.")

    nonzero = [
        (row["cl"], expected["unattributed_other_delta"])
        for row, expected in zip(source_rows, expected_rows)
        if expected["unattributed_other_delta"] != 0
    ]
    retroactive_packet_id: str | None = None
    retroactive_allocation_id: str | None = None
    if nonzero:
        if nonzero != [(9, 8)] or target_cl < 9 or con_transitions != [(9, 13, 15)]:
            raise invalid("The HP progression contains an unauthenticated retroactive Constitution delta.", details={"nonzero_other_delta": nonzero, "con_transitions": con_transitions})
        registry_path = root / "Command_2/Rules_Selection_Packets.json"
        if registry_path.is_symlink() or not registry_path.is_file():
            raise invalid("The HP retroactive-delta packet registry is missing or unsafe.")
        registry = _read_json(registry_path, code="FINAL_CHARACTER_HP_PROJECTION_INVALID")
        packet_rows = registry.get("packets") if isinstance(registry, Mapping) else None
        if not isinstance(packet_rows, list):
            raise invalid("The HP retroactive-delta packet registry has no packet list.")
        packet_by_id: dict[str, Mapping[str, Any]] = {}
        for row in packet_rows:
            if not isinstance(row, Mapping) or not isinstance(row.get("packet_id"), str) or not row.get("packet_id") or row["packet_id"] in packet_by_id:
                raise invalid("The HP packet registry has malformed or duplicate packet IDs.")
            packet_by_id[row["packet_id"]] = row
        feature_id = f"{path_id}.feature.ability_score_improvement_or_cultivation_insight"
        fixed_features = path_index.get("features")
        fixed_feature_matches = [row for row in fixed_features if isinstance(row, Mapping) and row.get("canonical_id") == feature_id] if isinstance(fixed_features, list) else []
        if len(fixed_feature_matches) != 1 or fixed_feature_matches[0].get("display_name") != "Ability Score Improvement or Cultivation Insight" or 8 not in fixed_feature_matches[0].get("granted_at_cl", []):
            raise invalid("The fixed Path ASI authority is unavailable for the retroactive HP delta.")
        feature_events = [
            row for row in raw_ledger.get("features", [])
            if isinstance(row, Mapping) and row.get("category") == "path_feature" and row.get("feature_id") == feature_id and row.get("gained_at_cl") == 8
        ] if isinstance(raw_ledger.get("features"), list) else []
        if len(feature_events) != 1:
            raise invalid("The raw CL8 ASI feature allocation is missing or ambiguous.")
        feature_event = feature_events[0]
        level8 = raw_levels[7]
        allocation_id = feature_event.get("allocation_id")
        level8_packet_ids = feature_event.get("source_packet_ids")
        if (
            not isinstance(allocation_id, str)
            or not allocation_id.strip()
            or not isinstance(level8_packet_ids, list)
            or len(level8_packet_ids) != 1
            or not isinstance(level8_packet_ids[0], str)
            or not level8_packet_ids[0].strip()
        ):
            raise invalid("The raw CL8 ASI allocation is incomplete.")
        level8_packet = packet_by_id.get(level8_packet_ids[0])
        def exact_path_evidence(packet: Mapping[str, Any], *, target: int, kind: str, event_id: str | None = None) -> bool:
            evidence = packet.get("source_evidence")
            evidence_row = evidence[0] if isinstance(evidence, list) and len(evidence) == 1 and isinstance(evidence[0], Mapping) else None
            return (
                packet.get("record_id") == feature_id
                and packet.get("display_name") == fixed_feature_matches[0].get("display_name")
                and type(packet.get("target_cl")) is int
                and packet.get("target_cl") == target
                and packet.get("advancement_kind") == kind
                and (event_id is None or packet.get("event_id") == event_id)
                and isinstance(evidence_row, Mapping)
                and evidence_row.get("source_path") == proof["index_path"]
                and evidence_row.get("source_hash") == proof["index_sha256"]
                and evidence_row.get("source_anchor") == f"path-feature:{path_id}:{feature_id}"
            )
        if not isinstance(level8_packet, Mapping) or not exact_path_evidence(level8_packet, target=8, kind="level_advance", event_id=level8.get("event_id")):
            raise invalid("The raw CL8 ASI feature packet is not the exact Path allocation proof.")
        change_packets = [row for row in packet_rows if isinstance(row, Mapping) and exact_path_evidence(row, target=8, kind="ability_score_change")]
        if len(change_packets) != 1:
            raise invalid("The CL8 ASI ability-score-change packet is missing or ambiguous.")
        retroactive_packet_id = str(change_packets[0]["packet_id"])
        retroactive_allocation_id = allocation_id

    projected_levels = deepcopy(current_levels)
    compiler_rows: list[dict[str, Any]] = []
    for source_row, expected in zip(source_rows, expected_rows):
        raw_hp = source_row["raw"]
        current_hp = source_row["current"]
        if any(key not in allowed_hp_keys for key in current_hp):
            raise invalid("The copied HP row has an unsupported field.", details={"cl": source_row["cl"]})
        if any(current_hp.get(key) != raw_hp.get(key) for key in raw_hp if key != "source_packet_ids"):
            raise invalid("The copied HP row diverges from raw modern provenance.", details={"cl": source_row["cl"]})
        raw_refs = raw_hp.get("source_packet_ids", _MISSING)
        current_refs = current_hp.get("source_packet_ids", _MISSING)
        desired_refs: list[str] = []
        if expected["foundation_adjustment"] != 0:
            desired_refs.extend(foundation_packet_ids)
        if expected["unattributed_other_delta"] != 0 and retroactive_packet_id is not None:
            desired_refs.append(retroactive_packet_id)
        for refs in (raw_refs, current_refs):
            if refs is _MISSING:
                continue
            if not isinstance(refs, list) or any(type(ref) is not str or not ref.strip() or ref != ref.strip() for ref in refs) or len(refs) != len(set(refs)) or refs != desired_refs:
                raise invalid("The copied HP packet references do not match authenticated retroactive authority.", details={"cl": source_row["cl"]})
        current_presence = [key in current_hp for key in compiler_hp_keys]
        if any(current_presence) and not all(current_presence):
            raise invalid("The copied HP compiler component map is partial.", details={"cl": source_row["cl"]})
        expected_compiler = {key: expected[key] for key in compiler_hp_keys}
        if all(current_presence) and any(current_hp.get(key) != expected_compiler[key] or type(current_hp.get(key)) is not int for key in compiler_hp_keys):
            raise invalid("The copied HP compiler component map conflicts with source arithmetic.", details={"cl": source_row["cl"]})
        raw_presence = [key in raw_hp for key in compiler_hp_keys]
        if any(raw_presence) and not all(raw_presence):
            raise invalid("The raw HP compiler component map is partial.", details={"cl": source_row["cl"]})
        if all(raw_presence) and any(raw_hp.get(key) != expected_compiler[key] or type(raw_hp.get(key)) is not int for key in compiler_hp_keys):
            raise invalid("The raw HP compiler component map conflicts with source arithmetic.", details={"cl": source_row["cl"]})
        projected_hp = deepcopy(current_hp)
        projected_hp.update(expected_compiler)
        if desired_refs:
            projected_hp["source_packet_ids"] = desired_refs
        projected_levels[source_row["cl"] - 1]["hp"] = projected_hp
        compiler_rows.append(projected_hp)

    projected_ledger = deepcopy(dict(ledger))
    projected_core_stats = deepcopy(dict(core_stats))
    projected_core_stats["hp_generation"] = {"hit_die": hit_die, "mode": "fixed_average"}
    if not current_generation_has_compiler:
        projected_core_stats["hp_generation_provenance"] = deepcopy(dict(raw_generation))
    projected_ledger["core_stats"] = projected_core_stats
    projected_advancement = deepcopy(dict(current_advancement))
    projected_advancement["levels"] = projected_levels
    projected_ledger["advancement"] = projected_advancement
    provenance = {
        "schema_version": "TianxiaFoundry.FinalCharacterHPProjectionProvenance.v1",
        "source_ledger_path": "Build/Character_Master_Ledger.json",
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_provenance_sha256,
        "path_details_path": _PATH_PROJECTION_DETAILS_RELATIVE,
        "path_details_sha256": sha256_file(path_details_path),
        "path_id": path_id,
        "path_name": path_name,
        "path_index_path": proof["index_path"],
        "path_index_sha256": proof["index_sha256"],
        "path_source_corpus_path": proof["corpus_path"],
        "path_source_corpus_sha256": proof["corpus_sha256"],
        "hit_die": hit_die,
        "mode": "fixed_average",
        "fixed_average": fixed_average,
        "source_hp_generation": deepcopy(dict(raw_generation)),
        "compiler_levels": deepcopy(compiler_rows),
        "other_delta_by_cl": {str(row["cl"]): expected["other_delta"] for row, expected in zip(source_rows, expected_rows)},
        "foundation_adjustment_by_cl": {
            str(cl): adjustment for cl, adjustment in foundation_adjustment_by_cl.items()
        },
        "foundation_authority": {
            "foundation_id": foundation_projection.get("foundation_id") if foundation_projection is not None else None,
            "packet_ids": deepcopy(foundation_packet_ids),
            "gained_at_cl": foundation_gained_at_cl,
            "modifier_units": foundation_modifier_units,
            "details_path": _FOUNDATION_PROJECTION_DETAILS_RELATIVE if foundation_details is not None else None,
            "details_sha256": foundation_projection.get("details_sha256") if foundation_projection is not None else None,
        } if foundation_projection is not None else None,
        "retroactive_authority": {
            "allocation_id": retroactive_allocation_id,
            "packet_id": retroactive_packet_id,
            "source_target_cl": 8,
            "transition": [13, 15],
        } if retroactive_packet_id is not None else None,
    }
    _write_json(details_path, provenance)
    _write_json(ledger_path, projected_ledger)
    reread = _read_json(ledger_path, code="FINAL_CHARACTER_HP_PROJECTION_INVALID")
    if reread != projected_ledger or raw_provenance_path.read_bytes() != raw_provenance_bytes:
        raise invalid("The compiler HP projection could not be read back exactly or altered raw provenance.")
    return {
        "schema_version": provenance["schema_version"],
        "source_ledger_path": provenance["source_ledger_path"],
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_provenance_sha256,
        "path_details_path": _PATH_PROJECTION_DETAILS_RELATIVE,
        "path_details_sha256": provenance["path_details_sha256"],
        "details_path": _HP_PROJECTION_DETAILS_RELATIVE,
        "details_sha256": sha256_file(details_path),
        "path_id": path_id,
        "hit_die": hit_die,
        "mode": "fixed_average",
        "fixed_average": fixed_average,
        "compiler_levels": deepcopy(compiler_rows),
        "other_delta_by_cl": provenance["other_delta_by_cl"],
        "foundation_adjustment_by_cl": provenance["foundation_adjustment_by_cl"],
        "foundation_authority": deepcopy(provenance["foundation_authority"]),
        "retroactive_packet_id": retroactive_packet_id,
        "retroactive_allocation_id": retroactive_allocation_id,
    }


def _selected_background_authority(background: Mapping[str, Any], invalid: Any) -> dict[str, Any]:
    """Resolve the character's own Background in the pinned Background authority."""

    background_id = background.get("background_id") if isinstance(background, Mapping) else None
    name = background.get("name") if isinstance(background, Mapping) else None
    authority = _bridge_fixed_json(_ABILITY_BACKGROUND_AUTHORITY_PATH, _ABILITY_BACKGROUND_AUTHORITY_SHA256)
    rows = authority.get("backgrounds") if isinstance(authority, Mapping) else None
    if not isinstance(authority, Mapping) or authority.get("schema") != "Tianxia.BackgroundCoreCatalog.v1" or not isinstance(rows, list):
        raise invalid("The fixed Background authority is unavailable or malformed.")
    ids = [row.get("background_id") for row in rows if isinstance(row, Mapping)]
    if len(ids) != len(rows) or len(set(ids)) != len(ids):
        raise invalid("The fixed Background authority is malformed or duplicated.")
    matches = [row for row in rows if row.get("background_id") == background_id]
    fixed = matches[0] if len(matches) == 1 else None
    source = fixed.get("source") if isinstance(fixed, Mapping) else None
    anchor = source.get("anchor") if isinstance(source, Mapping) else None
    if (
        not isinstance(background_id, str)
        or not isinstance(name, str)
        or fixed is None
        or fixed.get("schema") != "Tianxia.BackgroundCoreAuthority.v1"
        or fixed.get("display_name") != name
        or fixed.get("creator_selectable") is not True
        or fixed.get("api_visible") is not True
        or fixed.get("blockers") != []
        or fixed.get("unresolved_fields") != []
        or not isinstance(source, Mapping)
        or source.get("path") != _ABILITY_BACKGROUND_SOURCE_PATH
        or not isinstance(anchor, str)
        or not anchor.startswith("heading:")
    ):
        raise invalid("The selected Background is not a resolved source-backed authority row.", details={"background_id": background_id})
    return {"background_id": background_id, "name": name, "anchor": anchor, "row": fixed}


def _background_ability_delta_is_legal(fixed_background: Mapping[str, Any], delta: Mapping[str, Any]) -> bool:
    """True when ``delta`` is exactly one printed Background ability mode."""

    grants = fixed_background.get("ability_score_grants")
    modes = grants.get("modes") if isinstance(grants, Mapping) else None
    if not isinstance(grants, Mapping) or grants.get("resolved") is not True or not isinstance(modes, list):
        return False
    if not isinstance(delta, Mapping) or any(type(value) is not int for value in delta.values()):
        return False
    for mode in modes:
        if not isinstance(mode, Mapping):
            continue
        allowed = mode.get("allowed_ability_ids")
        increases = mode.get("increases")
        if (
            isinstance(allowed, list)
            and isinstance(increases, list)
            and mode.get("choose_distinct") == len(delta) == len(increases)
            and set(delta) <= set(allowed)
            and sorted(delta.values()) == sorted(increases)
        ):
            return True
    return False


def _project_modern_ability_generation_for_compiler(
    workspace: Path,
    *,
    path_projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project the sealed modern ability timeline into compiler fields.

    Stage 2 keeps the original point-buy record and records later ability
    choices as Path feature events.  The pinned compiler consumes an explicit
    point-buy map plus event-channel allocations.  This boundary derives that
    representation only from the copied ledger, the fixed Path/background
    authorities, and the exact source packets in the copied registry.  The
    original ledger remains byte-identical in ``Modern_Provenance.json``.
    """

    def invalid(message: str, *, details: Any = None) -> FoundryError:
        return _error("FINAL_CHARACTER_ABILITY_PROJECTION_INVALID", message, details=details)

    root = Path(workspace)
    ledger_path = root / "Build/Character_Master_Ledger.json"
    raw_provenance_path = root / _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    path_details_path = root / _PATH_PROJECTION_DETAILS_RELATIVE
    details_path = root / _ABILITY_PROJECTION_DETAILS_RELATIVE
    for path in (ledger_path, raw_provenance_path, path_details_path):
        if path.is_symlink() or not path.is_file():
            raise invalid("The copied ability projection inputs are missing or unsafe.", details={"path": str(path)})
    if details_path.exists():
        raise invalid("The copied workspace already contains ability projection provenance.")

    try:
        raw_provenance_bytes = raw_provenance_path.read_bytes()
        raw_provenance_sha256 = hashlib.sha256(raw_provenance_bytes).hexdigest()
        raw_ledger = _read_json(raw_provenance_path, code="FINAL_CHARACTER_ABILITY_PROJECTION_INVALID")
        path_details = _read_json(path_details_path, code="FINAL_CHARACTER_ABILITY_PROJECTION_INVALID")
        ledger = _read_json(ledger_path, code="FINAL_CHARACTER_ABILITY_PROJECTION_INVALID")
    except (OSError, FoundryError) as exc:
        if isinstance(exc, FoundryError):
            raise invalid("The copied ability projection provenance could not be read.", details={"cause": exc.code}) from exc
        raise invalid("The copied ability projection provenance could not be read.") from exc
    if not isinstance(raw_ledger, Mapping) or not isinstance(path_details, Mapping) or not isinstance(ledger, Mapping):
        raise invalid("The copied ability projection inputs must be mappings.")
    if path_projection is not None:
        if (
            not isinstance(path_projection, Mapping)
            or path_projection.get("source_ledger_sha256") != raw_provenance_sha256
            or path_projection.get("modern_provenance_sha256") != raw_provenance_sha256
            or path_projection.get("details_sha256") != sha256_file(path_details_path)
            or path_details.get("source_ledger_sha256") != raw_provenance_sha256
        ):
            raise invalid("The ability projection is not bound to the freshly authenticated Path projection.")
    elif path_details.get("source_ledger_sha256") != raw_provenance_sha256:
        raise invalid("The copied Path projection details are not bound to their raw ledger provenance.")

    raw_character = raw_ledger.get("character")
    character = ledger.get("character")
    if not isinstance(raw_character, Mapping) or not isinstance(character, Mapping):
        raise invalid("The copied ledger has no character identity for ability projection.")
    identity_fields = ("path_id", "path", "key_ability", "cl")
    if any(character.get(field) != raw_character.get(field) for field in identity_fields):
        raise invalid("The copied character identity diverges from raw modern provenance.")
    path_id = raw_character.get("path_id")
    path_name = raw_character.get("path")
    key_ability = raw_character.get("key_ability")
    target_cl = raw_character.get("cl")
    if (
        not isinstance(path_id, str)
        or not path_id.strip()
        or not isinstance(path_name, str)
        or not path_name.strip()
        or not isinstance(key_ability, str)
        or not key_ability.strip()
        or type(target_cl) is not int
        or not 1 <= target_cl <= 20
    ):
        raise invalid("The copied active Path identity is incomplete or malformed.", details={"path_id": path_id, "cl": target_cl})
    proof = _PACKET_PATH_PROOFS.get(path_id)
    if proof is None:
        raise invalid("The active Path is not one fixed canonical Path.", details={"path_id": path_id})

    # Re-prove the active Path identity instead of allowing a caller-supplied
    # projection result to establish the source of the ability timeline.
    path_index = _bridge_fixed_json(proof["index_path"], proof["index_sha256"])
    path_master = _bridge_fixed_json(_PACKET_PATH_MASTER_PATH, _PACKET_PATH_MASTER_SHA256)
    if not isinstance(path_index, Mapping) or not isinstance(path_master, Mapping):
        raise invalid("The fixed active Path authority is unavailable or unsafe.", details={"path_id": path_id})
    master_rows = path_master.get("paths")
    if not isinstance(master_rows, list):
        raise invalid("The fixed Path master has no canonical path list.")
    master_ids = [row.get("canonical_id") for row in master_rows if isinstance(row, Mapping)]
    master_matches = [row for row in master_rows if isinstance(row, Mapping) and row.get("canonical_id") == path_id]
    index_source = path_index.get("source")
    master_source = master_matches[0].get("source") if len(master_matches) == 1 else None
    if (
        len(master_ids) != len(master_rows)
        or any(not isinstance(value, str) or not value.strip() for value in master_ids)
        or len(set(master_ids)) != len(master_ids)
        or len(master_matches) != 1
        or path_index.get("canonical_id") != path_id
        or path_index.get("display_name") != path_name
        or path_index.get("publication_status") != "current_canonical_player_path"
        or master_matches[0].get("display_name") != path_name
        or master_matches[0].get("index_file") != proof["index_file"]
        or not isinstance(index_source, Mapping)
        or not isinstance(master_source, Mapping)
        or index_source.get("corpus_path") != proof["corpus_path"]
        or index_source.get("sha256") != proof["corpus_sha256"]
        or master_source.get("corpus_path") != proof["corpus_path"]
        or master_source.get("sha256") != proof["corpus_sha256"]
    ):
        raise invalid("The active Path identity diverges from fixed Path authority.", details={"path_id": path_id})
    path_profile = path_index.get("path_profile")
    key_ability_names = {
        "STR": "Strength",
        "DEX": "Dexterity",
        "CON": "Constitution",
        "INT": "Intelligence",
        "WIS": "Wisdom",
        "CHA": "Charisma",
    }
    fixed_key_ability = path_profile.get("key_ability") if isinstance(path_profile, Mapping) else None
    master_key_ability = master_matches[0].get("key_ability")
    fixed_options = fixed_key_ability.get("options") if isinstance(fixed_key_ability, Mapping) else None
    master_options = master_key_ability.get("options") if isinstance(master_key_ability, Mapping) else None
    if (
        not isinstance(path_profile, Mapping)
        or not isinstance(fixed_options, list)
        or not isinstance(master_options, list)
        or fixed_options != master_options
        or key_ability_names.get(key_ability, key_ability) not in fixed_options
    ):
        raise invalid("The active Path key ability is not bound to fixed authority.", details={"path_id": path_id, "key_ability": key_ability})

    raw_path_rows, raw_path_packet_ids = _selected_path_rows_for_compiler_consumer(
        raw_ledger=raw_ledger,
        ledger=ledger,
        path_projection=path_projection,
        path_details=path_details,
        primary_path_id=path_id,
        primary_path_name=path_name,
        character_cl=target_cl,
        invalid=invalid,
    )
    raw_path_row = raw_path_rows[0]
    if raw_path_row.get("key_ability") != key_ability:
        raise invalid("The primary Path key ability is not bound to the authenticated Path row.")

    raw_core_stats = raw_ledger.get("core_stats")
    core_stats = ledger.get("core_stats")
    if not isinstance(raw_core_stats, Mapping) or not isinstance(core_stats, Mapping):
        raise invalid("The copied ledger has no core-stat ability authority.")
    score_keys = set(_CORE_SAVE_ABILITIES)

    def exact_int_map(value: Any, label: str, *, keys: set[str] = score_keys) -> dict[str, int]:
        if not isinstance(value, Mapping) or set(value) != keys or any(type(item) is not int for item in value.values()):
            raise invalid(f"The {label} map is incomplete or non-integer.", details={"label": label})
        return {key: int(value[key]) for key in keys}

    raw_scores = exact_int_map(raw_core_stats.get("ability_scores"), "raw ability_scores")
    raw_modifiers = exact_int_map(raw_core_stats.get("ability_modifiers"), "raw ability_modifiers")
    current_scores = exact_int_map(core_stats.get("ability_scores"), "copied ability_scores")
    current_modifiers = exact_int_map(core_stats.get("ability_modifiers"), "copied ability_modifiers")
    if current_scores != raw_scores or current_modifiers != raw_modifiers:
        raise invalid("The copied ability score/modifier maps diverge from raw modern provenance.")
    for ability in _CORE_SAVE_ABILITIES:
        if raw_modifiers[ability] != (raw_scores[ability] - 10) // 2:
            raise invalid("The sealed ability score and modifier maps fail standard modifier math.", details={"ability": ability})

    raw_generation = raw_core_stats.get("ability_generation")
    if not isinstance(raw_generation, Mapping):
        raise invalid("The sealed ability generation record is missing or malformed.")
    if set(raw_generation) != {"formula", "inputs", "outputs", "rule_id", "trace"}:
        raise invalid("The sealed ability generation record has unsupported fields.")
    raw_inputs = raw_generation.get("inputs")
    raw_outputs = raw_generation.get("outputs")
    generation_rule = raw_inputs.get("generation_rule") if isinstance(raw_inputs, Mapping) else None
    base_scores = raw_inputs.get("ability_scores") if isinstance(raw_inputs, Mapping) else None
    if (
        not isinstance(raw_inputs, Mapping)
        or set(raw_inputs) != {"ability_scores", "generation_rule"}
        or not isinstance(generation_rule, Mapping)
        or set(generation_rule) != {"budget", "maximum", "method", "minimum"}
        or generation_rule != {"budget": 27, "maximum": 15, "method": "point_buy", "minimum": 8}
    ):
        raise invalid("The sealed point-buy authority is missing or malformed.")
    base_scores = exact_int_map(base_scores, "point-buy base_scores")
    if any(score not in _ABILITY_POINT_BUY_COST for score in base_scores.values()):
        raise invalid("The sealed point-buy base score is outside the fixed range.")
    points_spent = sum(_ABILITY_POINT_BUY_COST[score] for score in base_scores.values())
    if points_spent != 27:
        raise invalid("The sealed point-buy base scores do not spend exactly 27 points.", details={"points_spent": points_spent})
    if (
        not isinstance(raw_outputs, Mapping)
        or set(raw_outputs) != {"ability_modifiers", "ability_scores", "point_buy_cost"}
        or raw_outputs.get("ability_scores") != base_scores
        or raw_outputs.get("point_buy_cost") != 27
    ):
        raise invalid("The sealed point-buy output record is missing or malformed.")
    output_modifiers = exact_int_map(raw_outputs.get("ability_modifiers"), "point-buy output modifiers")
    expected_base_modifiers = {ability: (base_scores[ability] - 10) // 2 for ability in _CORE_SAVE_ABILITIES}
    if output_modifiers != expected_base_modifiers:
        raise invalid("The sealed point-buy output modifiers are inconsistent with base scores.")
    if raw_generation.get("rule_id") != _ABILITY_GENERATION_RULE_ID or raw_generation.get("formula") is not None or raw_generation.get("trace") != {}:
        raise invalid("The sealed point-buy rule identity or trace is not the fixed authority.")

    background_origin = raw_ledger.get("background_origin")
    current_background_origin = ledger.get("background_origin")
    if not isinstance(background_origin, Mapping) or current_background_origin != background_origin:
        raise invalid("The copied background authority diverges from raw modern provenance.")
    background = background_origin.get("background")
    if not isinstance(background, Mapping):
        raise invalid("The copied ledger has no selected Background ability authority.")
    selected_background = _selected_background_authority(background, invalid)
    selected_background_id = selected_background["background_id"]
    selected_background_name = selected_background["name"]
    selected_background_anchor = selected_background["anchor"]
    background_delta = background.get("ability_score_change")
    if not _background_ability_delta_is_legal(selected_background["row"], background_delta):
        raise invalid(
            "The selected Background ability delta is not one exact printed Background mode.",
            details={"background_id": selected_background_id, "delta": background_delta},
        )
    background_packet_ids = background.get("source_packet_ids")
    if not isinstance(background_packet_ids, list) or len(background_packet_ids) != 1 or not isinstance(background_packet_ids[0], str) or not background_packet_ids[0].strip():
        raise invalid("The selected Background lacks one exact source packet.")

    registry_path = root / "Command_2/Rules_Selection_Packets.json"
    if registry_path.is_symlink() or not registry_path.is_file():
        raise invalid("The copied source packet registry is missing or unsafe.")
    registry = _read_json(registry_path, code="FINAL_CHARACTER_ABILITY_PROJECTION_INVALID")
    packet_rows = registry.get("packets") if isinstance(registry, Mapping) else None
    if not isinstance(packet_rows, list):
        raise invalid("The copied source packet registry has no packet list.")
    packet_by_id: dict[str, Mapping[str, Any]] = {}
    for row in packet_rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("packet_id"), str) or not row.get("packet_id").strip() or row["packet_id"] in packet_by_id:
            raise invalid("The copied source packet registry has malformed or duplicate packet IDs.")
        packet_by_id[row["packet_id"]] = row

    def exact_packet(
        packet_id: str,
        *,
        record_id: str,
        display_name: str,
        target: int,
        advancement_kind: str,
        anchor: str,
        event_id: str | None = None,
    ) -> Mapping[str, Any]:
        packet = packet_by_id.get(packet_id)
        evidence = packet.get("source_evidence") if isinstance(packet, Mapping) else None
        evidence_row = evidence[0] if isinstance(evidence, list) and len(evidence) == 1 and isinstance(evidence[0], Mapping) else None
        if (
            packet is None
            or packet.get("record_id") != record_id
            or packet.get("display_name") != display_name
            or type(packet.get("target_cl")) is not int
            or packet.get("target_cl") != target
            or packet.get("advancement_kind") != advancement_kind
            or (event_id is not None and packet.get("event_id") != event_id)
            or evidence_row is None
            or evidence_row.get("source_path") != proof["index_path"]
            or evidence_row.get("source_hash") != proof["index_sha256"]
            or evidence_row.get("source_anchor") != anchor
        ):
            raise invalid("A source packet is not the exact fixed ability/Path binding.", details={"packet_id": packet_id, "record_id": record_id, "target_cl": target})
        return packet

    path_packet_id = raw_path_packet_ids[0]
    exact_packet(
        path_packet_id,
        record_id=path_id,
        display_name=path_name,
        target=1,
        advancement_kind="path_acquisition",
        anchor=f"path:{path_id}",
    )
    background_packet = packet_by_id.get(background_packet_ids[0])
    background_evidence = background_packet.get("source_evidence") if isinstance(background_packet, Mapping) else None
    background_evidence_row = background_evidence[0] if isinstance(background_evidence, list) and len(background_evidence) == 1 and isinstance(background_evidence[0], Mapping) else None
    background_source_path = _FINAL_CHARACTER_BASE_FACTORY_ROOT / _ABILITY_BACKGROUND_SOURCE_PATH
    try:
        if background_source_path.is_symlink() or not background_source_path.is_file() or sha256_file(background_source_path) != _ABILITY_BACKGROUND_SOURCE_SHA256:
            raise invalid("The fixed Background source is missing, unsafe, or hash-divergent.")
        background_source_lines = background_source_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise invalid("The fixed Background source could not be read.") from exc
    heading = f"## {selected_background_name}"
    heading_indexes = [index for index, line in enumerate(background_source_lines) if line.strip() == heading]
    if len(heading_indexes) != 1:
        raise invalid("The fixed Background source heading is missing or ambiguous.")
    heading_index = heading_indexes[0]
    section_end = next((index for index in range(heading_index + 1, len(background_source_lines)) if background_source_lines[index].startswith("## ")), len(background_source_lines))
    background_source_section = "\n".join(background_source_lines[heading_index:section_end])
    if (
        not isinstance(background_packet, Mapping)
        or background_packet.get("record_id") != selected_background_id
        or background_packet.get("display_name") != selected_background_name
        or background_packet.get("advancement_kind") != "background_acquisition"
        or background_evidence_row is None
        or background_evidence_row.get("source_path") != _ABILITY_BACKGROUND_SOURCE_PATH
        or background_evidence_row.get("source_hash") != _ABILITY_BACKGROUND_SOURCE_SHA256
        or background_evidence_row.get("source_anchor") != selected_background_anchor
        or not isinstance(background_packet.get("full_description"), str)
        or background_packet.get("full_description").rstrip("\n") != background_source_section.rstrip("\n")
    ):
        raise invalid("The selected Background packet is not the exact source-backed authority.")

    fixed_features = path_index.get("features")
    asi_id = f"{path_id}.feature.ability_score_improvement_or_cultivation_insight"
    asi_matches = [row for row in fixed_features if isinstance(row, Mapping) and row.get("canonical_id") == asi_id] if isinstance(fixed_features, list) else []
    if (
        len(asi_matches) != 1
        or asi_matches[0].get("display_name") != "Ability Score Improvement or Cultivation Insight"
        or not isinstance(asi_matches[0].get("granted_at_cl"), list)
        or not asi_matches[0].get("granted_at_cl")
        or any(type(cl) is not int or cl < 1 for cl in asi_matches[0]["granted_at_cl"])
        or len(set(asi_matches[0]["granted_at_cl"])) != len(asi_matches[0]["granted_at_cl"])
    ):
        raise invalid("The fixed active Path ASI authority is missing or malformed.")
    asi_display_name = asi_matches[0]["display_name"]
    asi_targets = sorted(cl for cl in asi_matches[0]["granted_at_cl"] if cl < target_cl)

    raw_advancement = raw_ledger.get("advancement")
    current_advancement = ledger.get("advancement")
    raw_levels = raw_advancement.get("levels") if isinstance(raw_advancement, Mapping) else None
    current_levels = current_advancement.get("levels") if isinstance(current_advancement, Mapping) else None
    if (
        not isinstance(raw_levels, list)
        or len(raw_levels) != target_cl
        or not isinstance(current_levels, list)
        or len(current_levels) != target_cl
        or [row.get("cl") if isinstance(row, Mapping) else None for row in raw_levels] != list(range(1, target_cl + 1))
        or [row.get("cl") if isinstance(row, Mapping) else None for row in current_levels] != list(range(1, target_cl + 1))
    ):
        raise invalid("The copied ability timeline is not an exact gap-free CL sequence.")

    def without_compiler_fields(row: Mapping[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in row.items() if key not in {"allocations", "hp"}}

    def source_allocations(row: Mapping[str, Any], *, cl: int) -> list[dict[str, Any]]:
        value = row.get("allocations", _MISSING)
        if value is _MISSING or value is None:
            return []
        if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
            raise invalid("The source ability allocation list is malformed.", details={"cl": cl})
        result: list[dict[str, Any]] = []
        for item in value:
            if "ability_score_adjustments" in item:
                adjustments = item.get("ability_score_adjustments")
                if not isinstance(adjustments, Mapping) or any(key not in score_keys or type(amount) is not int for key, amount in adjustments.items()):
                    raise invalid("A source ability allocation has malformed adjustments.", details={"cl": cl})
                if any(adjustments.values()):
                    raise invalid("A source ability allocation would conflict with the authenticated ASI transitions.", details={"cl": cl})
            result.append(deepcopy(dict(item)))
        return result

    timeline: list[dict[str, int]] = []
    for index, (raw_level, current_level) in enumerate(zip(raw_levels, current_levels), start=1):
        if not isinstance(raw_level, Mapping) or not isinstance(current_level, Mapping):
            raise invalid("The copied ability timeline contains a malformed level row.", details={"cl": index})
        if without_compiler_fields(current_level) != without_compiler_fields(raw_level):
            raise invalid("The copied ability timeline diverges from raw modern provenance.", details={"cl": index})
        scores_after = raw_level.get("ability_scores_after")
        timeline.append(exact_int_map(scores_after, f"ability_scores_after at CL{index}"))
        # Validate the raw allocation shape now; the compiler-only event
        # allocations are appended only after all source transitions pass.
        source_allocations(raw_level, cl=index)
        source_allocations(current_level, cl=index)
        if source_allocations(current_level, cl=index) != source_allocations(raw_level, cl=index):
            raise invalid("The copied source allocation list diverges from raw modern provenance.", details={"cl": index})
    if timeline[-1] != raw_scores:
        raise invalid("The final ability timeline does not match sealed core scores.")

    transitions: dict[int, dict[str, int]] = {}
    for transition_cl, (before, after) in enumerate(zip(timeline, timeline[1:]), start=2):
        delta = {ability: after[ability] - before[ability] for ability in _CORE_SAVE_ABILITIES}
        if any(delta.values()):
            # An ASI adds +2 (one ability) or +1/+1; a level-selected Cultivation
            # Insight adds +1 to one printed ability (RAW-017 milestones).
            if any(value < 0 for value in delta.values()) or not (list(sorted(value for value in delta.values() if value)) in ([2], [1, 1], [1])):
                raise invalid("The ability timeline contains an unsupported score transition.", details={"cl": transition_cl, "delta": delta})
            transitions[transition_cl] = {ability: amount for ability, amount in delta.items() if amount}
    expected_transition_cls = {asi_target + 1 for asi_target in asi_targets}
    if set(transitions) != expected_transition_cls:
        raise invalid("The ability timeline transitions do not match the fixed ASI grants.", details={"actual": sorted(transitions), "expected": sorted(expected_transition_cls)})

    raw_features = raw_ledger.get("features")
    if not isinstance(raw_features, list):
        raise invalid("The raw modern ledger has no feature event list.")
    feature_events: dict[tuple[str, int], Mapping[str, Any]] = {}
    for row in raw_features:
        if not isinstance(row, Mapping) or row.get("category") != "path_feature":
            continue
        feature_id = row.get("feature_id")
        gained_at_cl = row.get("gained_at_cl")
        if not isinstance(feature_id, str) or not feature_id.strip() or type(gained_at_cl) is not int:
            continue
        key = (feature_id, gained_at_cl)
        if key in feature_events:
            raise invalid("The raw Path feature event identity is duplicated.", details={"feature_id": feature_id, "gained_at_cl": gained_at_cl})
        feature_events[key] = row

    transition_packet_ids: dict[str, str] = {}
    allocations_by_cl: dict[str, list[dict[str, Any]]] = {str(cl): [] for cl in range(1, target_cl + 1)}
    for asi_target in asi_targets:
        feature_event = feature_events.get((asi_id, asi_target))
        if not isinstance(feature_event, Mapping):
            raise invalid("A fixed ASI grant has no matching source feature event.", details={"target_cl": asi_target})
        feature_packet_ids = feature_event.get("source_packet_ids")
        if not isinstance(feature_packet_ids, list) or len(feature_packet_ids) != 1 or not isinstance(feature_packet_ids[0], str) or not feature_packet_ids[0].strip():
            raise invalid("A fixed ASI feature event lacks one exact source packet.", details={"target_cl": asi_target})
        level_row = raw_levels[asi_target - 1]
        if (
            level_row.get("feature_record_id") != asi_id
            or not isinstance(level_row.get("event_id"), str)
            or feature_event.get("allocation_id") not in {
                level_row.get("event_id"),
                f"allocation.{level_row.get('event_id')}",
            }
            or feature_event.get("name") != asi_display_name
            or feature_event.get("gained_at_cl") != asi_target
        ):
            raise invalid("The ASI feature event is not bound to its level event.", details={"target_cl": asi_target})
        exact_packet(
            feature_packet_ids[0],
            record_id=asi_id,
            display_name=asi_display_name,
            target=asi_target,
            advancement_kind="level_advance",
            anchor=f"path-feature:{path_id}:{asi_id}",
            event_id=level_row.get("event_id"),
        )
        change_matches = []
        for packet in packet_rows:
            if not isinstance(packet, Mapping) or packet.get("record_id") != asi_id or packet.get("advancement_kind") != "ability_score_change" or packet.get("target_cl") != asi_target:
                continue
            evidence = packet.get("source_evidence")
            evidence_row = evidence[0] if isinstance(evidence, list) and len(evidence) == 1 and isinstance(evidence[0], Mapping) else None
            if (
                packet.get("display_name") == asi_display_name
                and evidence_row is not None
                and evidence_row.get("source_path") == proof["index_path"]
                and evidence_row.get("source_hash") == proof["index_sha256"]
                and evidence_row.get("source_anchor") == f"path-feature:{path_id}:{asi_id}"
            ):
                change_matches.append(packet)
        ability_display_names = {
            "STR": "Strength",
            "DEX": "Dexterity",
            "CON": "Constitution",
            "INT": "Intelligence",
            "WIS": "Wisdom",
            "CHA": "Charisma",
        }
        milestone_insights = [
            row for row in raw_ledger.get("insights") or []
            if isinstance(row, Mapping) and row.get("gained_at_cl") == asi_target
        ]
        if len(change_matches) > 1 or (not change_matches and len(milestone_insights) != 1):
            raise invalid("A milestone has no single ASI or Cultivation Insight choice.", details={"target_cl": asi_target, "matches": len(change_matches), "insights": len(milestone_insights)})
        if change_matches:
            if sum(transitions.get(asi_target + 1, {}).values()) != 2:
                raise invalid("An ASI milestone does not add exactly two ability points.", details={"target_cl": asi_target})
            change_packet = change_matches[0]
            change_packet_id = change_packet.get("packet_id")
            change_event_id = change_packet.get("event_id")
            if not isinstance(change_packet_id, str) or not change_packet_id.strip() or not isinstance(change_event_id, str) or not change_event_id.strip():
                raise invalid("The ASI ability-score-change packet identity is incomplete.", details={"target_cl": asi_target})
            transition_cl = asi_target + 1
            delta = transitions.get(transition_cl)
            if not isinstance(delta, Mapping) or not delta:
                raise invalid("The ASI transition has no authenticated score delta.", details={"target_cl": asi_target})
            ability_display_names = {
                "STR": "Strength",
                "DEX": "Dexterity",
                "CON": "Constitution",
                "INT": "Intelligence",
                "WIS": "Wisdom",
                "CHA": "Charisma",
            }
            adjustment_description = ", ".join(
                f"{ability_display_names.get(ability, ability)} +{amount}"
                for ability, amount in sorted(delta.items())
            )
            allocation_id = f"ability-score-change.{change_packet_id}"
            allocation = {
                "allocation_id": allocation_id,
                "channel": "event",
                "grant_type": "event",
                "grant_id": allocation_id,
                "name": f"{asi_display_name}: {adjustment_description}",
                "slot_cost": 0,
                "ability_score_adjustments": dict(delta),
                "source_packet_ids": [change_packet_id],
                "source_event_id": change_event_id,
                "event_type": "ability_score_change",
                "target_cl": asi_target,
            }
            allocations_by_cl[str(transition_cl)].append(allocation)
            transition_packet_ids[str(asi_target)] = change_packet_id
        else:
            insight = milestone_insights[0]
            insight_packet_ids = insight.get("source_packet_ids")
            insight_packet = packet_by_id.get(insight_packet_ids[0]) if isinstance(insight_packet_ids, list) and len(insight_packet_ids) == 1 else None
            printed = re.search(
                r"\*\*Ability Increase \(Level Selection\):\*\*\s*Increase your (.+?) score by 1",
                str(insight.get("full_description") or ""),
            )
            printed_abilities = {
                code
                for code, display in ability_display_names.items()
                if printed and re.search(rf"\b{display}\b", printed.group(1))
            }
            chosen = insight.get("ability")
            transition_cl = asi_target + 1
            delta = transitions.get(transition_cl)
            if (
                not isinstance(insight_packet, Mapping)
                or insight_packet.get("advancement_kind") != "cultivation_insight_acquisition"
                or insight_packet.get("record_id") != insight.get("insight_id")
                or insight_packet.get("target_cl") != asi_target
                or insight.get("ability_change_applied") is not True
                or insight.get("amount") != 1
                or chosen not in printed_abilities
                or delta != {chosen: 1}
            ):
                raise invalid("A Cultivation Insight milestone is not an exact printed +1 ability increase.", details={"target_cl": asi_target, "insight_id": insight.get("insight_id")})
            change_packet_id = insight_packet_ids[0]
            allocation_id = f"insight-ability-increase.{change_packet_id}"
            allocations_by_cl[str(transition_cl)].append({
                "allocation_id": allocation_id,
                "channel": "event",
                "grant_type": "event",
                "grant_id": allocation_id,
                "name": f"{insight.get('name')}: {ability_display_names[chosen]} +1",
                "slot_cost": 0,
                "ability_score_adjustments": {chosen: 1},
                "source_packet_ids": [change_packet_id],
                "source_event_id": insight_packet.get("event_id"),
                "event_type": "cultivation_insight_ability_increase",
                "target_cl": asi_target,
            })
            transition_packet_ids[str(asi_target)] = change_packet_id

    compiler_generation = {
        "method": "27_point_buy",
        "base_scores": base_scores,
        "points_spent": points_spent,
        "background_adjustments": {ability: int(background_delta.get(ability, 0)) for ability in _CORE_SAVE_ABILITIES},
        "species_adjustments": {ability: 0 for ability in _CORE_SAVE_ABILITIES},
        "other_adjustments": {
            ability: sum(delta.get(ability, 0) for delta in transitions.values())
            for ability in _CORE_SAVE_ABILITIES
        },
    }
    computed_scores = {
        ability: compiler_generation["base_scores"][ability]
        + compiler_generation["background_adjustments"][ability]
        + compiler_generation["species_adjustments"][ability]
        + compiler_generation["other_adjustments"][ability]
        for ability in _CORE_SAVE_ABILITIES
    }
    if computed_scores != raw_scores:
        raise invalid("The source-backed ability generation components do not reconcile to final scores.", details={"computed": computed_scores})
    current_generation = core_stats.get("ability_generation")
    if current_generation == raw_generation:
        generation_mode = "source_backed_point_buy_projection"
    elif current_generation == compiler_generation:
        generation_mode = "preserved_existing"
    else:
        raise invalid("The copied ability generation map is neither raw provenance nor an exact compiler map.")
    if "ability_generation_provenance" in core_stats and core_stats.get("ability_generation_provenance") != dict(raw_generation):
        raise invalid("The copied ability generation provenance diverges from raw modern provenance.")

    projected_levels = deepcopy(current_levels)
    for index, row in enumerate(projected_levels, start=1):
        source = source_allocations(raw_levels[index - 1], cl=index)
        source.extend(deepcopy(allocations_by_cl[str(index)]))
        row["allocations"] = source
    projected_core_stats = deepcopy(dict(core_stats))
    projected_core_stats["ability_generation"] = compiler_generation
    projected_core_stats["ability_generation_provenance"] = deepcopy(dict(raw_generation))
    projected_ledger = deepcopy(dict(ledger))
    projected_ledger["core_stats"] = projected_core_stats
    projected_advancement = deepcopy(dict(current_advancement))
    projected_advancement["levels"] = projected_levels
    projected_ledger["advancement"] = projected_advancement
    provenance = {
        "schema_version": "TianxiaFoundry.FinalCharacterAbilityProjectionProvenance.v1",
        "source_ledger_path": "Build/Character_Master_Ledger.json",
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_provenance_sha256,
        "path_details_path": _PATH_PROJECTION_DETAILS_RELATIVE,
        "path_details_sha256": sha256_file(path_details_path),
        "path_id": path_id,
        "path_name": path_name,
        "path_index_path": proof["index_path"],
        "path_index_sha256": proof["index_sha256"],
        "background_id": selected_background_id,
        "background_name": selected_background_name,
        "background_authority_path": _ABILITY_BACKGROUND_AUTHORITY_PATH,
        "background_authority_sha256": _ABILITY_BACKGROUND_AUTHORITY_SHA256,
        "background_source_path": _ABILITY_BACKGROUND_SOURCE_PATH,
        "background_source_sha256": _ABILITY_BACKGROUND_SOURCE_SHA256,
        "base_scores": deepcopy(base_scores),
        "background_adjustments": deepcopy(compiler_generation["background_adjustments"]),
        "species_adjustments": deepcopy(compiler_generation["species_adjustments"]),
        "other_adjustments": deepcopy(compiler_generation["other_adjustments"]),
        "compiler_generation": deepcopy(compiler_generation),
        "source_ability_generation": deepcopy(dict(raw_generation)),
        "generation_mode": generation_mode,
        "asi_feature_id": asi_id,
        "asi_targets": asi_targets,
        "transition_packet_ids": transition_packet_ids,
        "allocations_by_cl": allocations_by_cl,
    }
    _write_json(details_path, provenance)
    _write_json(ledger_path, projected_ledger)
    reread = _read_json(ledger_path, code="FINAL_CHARACTER_ABILITY_PROJECTION_INVALID")
    if reread != projected_ledger or raw_provenance_path.read_bytes() != raw_provenance_bytes:
        raise invalid("The compiler ability projection could not be read back exactly or altered raw provenance.")
    return {
        "schema_version": provenance["schema_version"],
        "source_ledger_path": provenance["source_ledger_path"],
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_provenance_sha256,
        "path_details_path": _PATH_PROJECTION_DETAILS_RELATIVE,
        "path_details_sha256": provenance["path_details_sha256"],
        "details_path": _ABILITY_PROJECTION_DETAILS_RELATIVE,
        "details_sha256": sha256_file(details_path),
        "path_id": path_id,
        "background_id": selected_background_id,
        "compiler_generation": deepcopy(compiler_generation),
        "generation_mode": generation_mode,
        "asi_targets": asi_targets,
        "transition_packet_ids": transition_packet_ids,
        "allocations_by_cl": allocations_by_cl,
    }


def _project_background_origin_allocations_for_compiler(
    workspace: Path,
    *,
    ability_projection: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Project the CL1 Background/Origin grants and compiler grant mode.

    The modern ledger deliberately does not put compiler allocation identities
    on its Background and Origin rows.  The pinned compiler, however, needs a
    corresponding ``background`` and ``origin_insight`` allocation in CL1.
    This boundary derives those two rows from the copied ledger after the
    ability projection has authenticated the Background packet.  It also
    projects the pinned compiler's ``background.grant_mode`` only when the
    selected Background Sphere/Talent pair is present in the fixed canonical
    Background authority.  It accepts
    the sealed modern packet registry before the later native packet bridge,
    or revalidates that bridge's native records when already present.  It does not inspect or rewrite
    Spheres, Talents, Features, Methods, Foundations, or Immortal Arts.

    The original modern ledger remains byte-for-byte preserved in
    ``Modern_Provenance.json``.  The generated IDs are deterministic packet
    identities, not caller-provided labels.
    """

    def invalid(message: str, *, details: Any = None) -> FoundryError:
        return _error("FINAL_CHARACTER_GRANT_ALLOCATION_PROJECTION_INVALID", message, details=details)

    root = Path(workspace)
    ledger_path = root / "Build/Character_Master_Ledger.json"
    raw_provenance_path = root / _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    details_path = root / _GRANT_PROJECTION_DETAILS_RELATIVE
    native_registry_path = root / "Command_2/Rules_Selection_Packets.json"
    modern_registry_path = root / "Command_2/Rules_Selection_Packets.Modern_Provenance.json"
    for path in (ledger_path, raw_provenance_path, native_registry_path):
        if path.is_symlink() or not path.is_file():
            raise invalid("The copied Background/Origin allocation inputs are missing or unsafe.", details={"path": str(path)})
    if details_path.is_symlink() or details_path.exists():
        raise invalid("The copied workspace already contains grant-allocation projection provenance.")

    try:
        raw_provenance_bytes = raw_provenance_path.read_bytes()
        raw_provenance_sha256 = hashlib.sha256(raw_provenance_bytes).hexdigest()
        raw_ledger = _read_json(raw_provenance_path, code="FINAL_CHARACTER_GRANT_ALLOCATION_PROJECTION_INVALID")
        ledger = _read_json(ledger_path, code="FINAL_CHARACTER_GRANT_ALLOCATION_PROJECTION_INVALID")
        native_registry_bytes = native_registry_path.read_bytes()
        native_registry = _read_json(native_registry_path, code="FINAL_CHARACTER_GRANT_ALLOCATION_PROJECTION_INVALID")
    except (OSError, FoundryError) as exc:
        if isinstance(exc, FoundryError):
            raise invalid("The copied grant-allocation inputs could not be read.", details={"cause": exc.code}) from exc
        raise invalid("The copied grant-allocation inputs could not be read.") from exc
    if not isinstance(raw_ledger, Mapping) or not isinstance(ledger, Mapping):
        raise invalid("The copied modern and compiler ledgers must be mappings.")
    if not isinstance(native_registry, Mapping) or not isinstance(native_registry.get("packets"), list):
        raise invalid("The copied packet registry is unavailable or malformed.")
    native_mode = native_registry.get("schema_version") == "HF05ZVK-R1H.CompilerRulesSelectionPackets.v1"
    modern_registry: Mapping[str, Any]
    modern_registry_bytes: bytes
    if native_mode:
        if modern_registry_path.is_symlink() or not modern_registry_path.is_file():
            raise invalid("The exact modern packet registry provenance is unavailable.", details={"path": str(modern_registry_path)})
        try:
            modern_registry_bytes = modern_registry_path.read_bytes()
            modern_registry_value = _read_json(modern_registry_path, code="FINAL_CHARACTER_GRANT_ALLOCATION_PROJECTION_INVALID")
        except (OSError, FoundryError) as exc:
            if isinstance(exc, FoundryError):
                raise invalid("The copied modern packet registry provenance could not be read.", details={"cause": exc.code}) from exc
            raise invalid("The copied modern packet registry provenance could not be read.") from exc
        if not isinstance(modern_registry_value, Mapping):
            raise invalid("The copied modern packet registry provenance is malformed.")
        modern_registry = modern_registry_value
    elif native_registry.get("schema_version") == "TianxiaFoundry.RulesSelectionPackets.v2":
        # Before the final packet bridge runs, Command 2 contains the sealed
        # modern registry itself.  It is already copied under the source
        # workspace binding; use those bytes as the modern evidence and defer
        # native compiler projection to the later bridge boundary.
        modern_registry = native_registry
        modern_registry_bytes = native_registry_bytes
        native_registry = None
    else:
        raise invalid("The copied packet registry is neither the sealed modern nor native schema.")
    if not isinstance(modern_registry.get("packets"), list):
        raise invalid("The copied modern packet registry has no packet list.")

    def indexed_packets(value: Mapping[str, Any], *, native: bool) -> dict[str, Mapping[str, Any]]:
        result: dict[str, Mapping[str, Any]] = {}
        for index, packet in enumerate(value["packets"]):
            if not isinstance(packet, Mapping):
                raise invalid("A packet registry row is not a mapping.", details={"native": native, "index": index})
            packet_id = packet.get("packet_id")
            if not isinstance(packet_id, str) or not packet_id.strip() or packet_id in result:
                raise invalid("A packet registry contains a missing or duplicate packet ID.", details={"native": native, "index": index, "packet_id": packet_id})
            result[packet_id] = packet
        return result

    native_by_id = indexed_packets(native_registry, native=True) if native_registry is not None else None
    modern_by_id = indexed_packets(modern_registry, native=False)

    build_registry_path = root / "Build/Rules_Selection_Packets.json"
    if build_registry_path.is_symlink():
        raise invalid("The copied Build packet registry is unsafe.", details={"path": str(build_registry_path)})
    if build_registry_path.exists():
        if not build_registry_path.is_file():
            raise invalid("The copied Build packet registry is not a regular file.", details={"path": str(build_registry_path)})
        build_registry = _read_json(build_registry_path, code="FINAL_CHARACTER_GRANT_ALLOCATION_PROJECTION_INVALID")
        expected_build_registry = native_registry if native_registry is not None else modern_registry
        if build_registry != expected_build_registry:
            raise invalid("The copied Build and Command 2 packet registries diverge.")

    if not isinstance(ability_projection, Mapping):
        raise invalid("The Background/Origin projection requires an authenticated ability projection.")
    if ability_projection.get("schema_version") not in {
        "TianxiaFoundry.FinalCharacterAbilityProjectionProvenance.v1",
        "TianxiaFoundry.FinalCharacterAbilityProjection.v1",
    }:
        raise invalid("The supplied ability projection is not the authenticated compiler ability projection.")

    raw_character = raw_ledger.get("character")
    character = ledger.get("character")
    if not isinstance(raw_character, Mapping) or not isinstance(character, Mapping):
        raise invalid("The copied ledgers have no character identity.")
    if (
        character.get("cl") != raw_character.get("cl")
        or character.get("path_id") != raw_character.get("path_id")
        or character.get("path") != raw_character.get("path")
    ):
        raise invalid("The copied character identity diverges from modern provenance.")
    target_cl = raw_character.get("cl")
    if type(target_cl) is not int or not 1 <= target_cl <= 20:
        raise invalid("The copied character CL is malformed.", details={"cl": target_cl})

    raw_background_origin = raw_ledger.get("background_origin")
    current_background_origin = ledger.get("background_origin")
    if not isinstance(raw_background_origin, Mapping) or not isinstance(current_background_origin, Mapping):
        raise invalid("The copied ledger has no Background/Origin selection surface.")
    raw_background = raw_background_origin.get("background")
    current_background = current_background_origin.get("background")
    raw_origin = raw_background_origin.get("origin_insight")
    current_origin = current_background_origin.get("origin_insight")
    if not all(isinstance(value, Mapping) for value in (raw_background, current_background, raw_origin, current_origin)):
        raise invalid("The copied Background/Origin rows are incomplete.")

    def exact_packet_row(
        row: Mapping[str, Any],
        *,
        id_field: str,
        expected_kind: str,
    ) -> tuple[str, str, str, Mapping[str, Any], Mapping[str, Any]]:
        record_id = row.get(id_field)
        display_name = row.get("name")
        source_packet_ids = row.get("source_packet_ids")
        if (
            not isinstance(record_id, str)
            or not record_id.strip()
            or not isinstance(display_name, str)
            or not display_name.strip()
            or not isinstance(source_packet_ids, list)
            or len(source_packet_ids) != 1
            or not isinstance(source_packet_ids[0], str)
            or not source_packet_ids[0].strip()
            or len(set(source_packet_ids)) != 1
        ):
            raise invalid("A Background/Origin row lacks one exact source packet.", details={"field": id_field})
        packet_id = source_packet_ids[0]
        modern = modern_by_id.get(packet_id)
        native = native_by_id.get(packet_id) if native_by_id is not None else None
        evidence = modern.get("source_evidence") if isinstance(modern, Mapping) else None
        evidence_row = evidence[0] if isinstance(evidence, list) and len(evidence) == 1 and isinstance(evidence[0], Mapping) else None
        source_path = evidence_row.get("source_path") if isinstance(evidence_row, Mapping) else None
        source_hash = evidence_row.get("source_hash") if isinstance(evidence_row, Mapping) else None
        source_anchor = evidence_row.get("source_anchor") if isinstance(evidence_row, Mapping) else None
        if (
            modern is None
            or modern.get("record_id") != record_id
            or modern.get("display_name") != display_name
            or type(modern.get("target_cl")) is not int
            or modern.get("target_cl") != 1
            or modern.get("advancement_kind") != expected_kind
            or not isinstance(modern.get("event_id"), str)
            or not modern.get("event_id").strip()
            or not isinstance(source_path, str)
            or not isinstance(source_hash, str)
            or not _is_hash(source_hash)
            or not isinstance(source_anchor, str)
            or not source_anchor.strip()
            or not _verify_modern_source_evidence(source_path, source_hash)
        ):
            raise invalid(
                "A Background/Origin source packet is not the exact authenticated native record.",
                details={"record_id": record_id, "packet_id": packet_id},
            )
        if native is not None:
            if (
                native.get("packet_id") != packet_id
                or native.get("authority") != "tianxia_rules"
                or native.get("modern_record_id") != record_id
                or native.get("modern_source_path") != source_path
                or native.get("modern_source_sha256") != source_hash
                or native.get("source_evidence_verified") is not True
                or native.get("source_section") != source_anchor
            ):
                raise invalid("A native source packet is not bound to the modern record.", details={"packet_id": packet_id})
            native_source_path = native.get("source_path")
            native_source_text = native.get("source_text")
            native_source_text_sha256 = native.get("source_text_sha256")
            if (
                not isinstance(native_source_path, str)
                or not native_source_path.strip()
                or not isinstance(native_source_text, str)
                or not native_source_text.strip()
                or not _is_hash(native_source_text_sha256)
                or _sha256_text(native_source_text) != native_source_text_sha256
            ):
                raise invalid("A native source packet has incomplete source bytes.", details={"packet_id": packet_id})
        return record_id, display_name, packet_id, modern, native

    background_id, background_name, background_packet_id, background_packet, background_native = exact_packet_row(
        raw_background,
        id_field="background_id",
        expected_kind="background_acquisition",
    )
    origin_id, origin_name, origin_packet_id, origin_packet, origin_native = exact_packet_row(
        raw_origin,
        id_field="origin_insight_id",
        expected_kind="origin_insight_acquisition",
    )
    if background_packet_id == origin_packet_id or background_id == origin_id:
        raise invalid("The Background and Origin source identities are not distinct.")

    # The modern ledger records the selected Sphere and Talent, while the
    # pinned compiler requires a small compatibility discriminator.  Derive
    # that discriminator from the fixed authority rather than guessing from
    # prose or accepting a caller-provided mode.  The authority is installed
    # under APP and is hash-bound by _bridge_fixed_json; copied workspace
    # bytes cannot redefine the available routes.
    background_authority = _bridge_fixed_json(
        _ABILITY_BACKGROUND_AUTHORITY_PATH,
        _ABILITY_BACKGROUND_AUTHORITY_SHA256,
    )
    fixed_background_rows = (
        background_authority.get("backgrounds")
        if isinstance(background_authority, Mapping)
        else None
    )
    fixed_background_matches = (
        [
            row
            for row in fixed_background_rows
            if isinstance(row, Mapping) and row.get("background_id") == background_id
        ]
        if isinstance(fixed_background_rows, list)
        else []
    )
    if (
        not isinstance(background_authority, Mapping)
        or background_authority.get("schema") != "Tianxia.BackgroundCoreCatalog.v1"
        or len(fixed_background_matches) != 1
        or fixed_background_matches[0].get("schema") != "Tianxia.BackgroundCoreAuthority.v1"
        or fixed_background_matches[0].get("display_name") != background_name
        or _selected_background_authority({"background_id": background_id, "name": background_name}, invalid)["row"] != fixed_background_matches[0]
    ):
        raise invalid("The selected Background lacks the fixed canonical grant-mode authority.")
    route_authority = fixed_background_matches[0].get("background_sphere_talent_routes")
    route_bullets = route_authority.get("route_bullets") if isinstance(route_authority, Mapping) else None
    if (
        not isinstance(route_authority, Mapping)
        or route_authority.get("background_talent_separate_from_ordinary_talents") is not True
        or not isinstance(route_bullets, list)
        or not route_bullets
        or any(not isinstance(route, str) or not route.strip() for route in route_bullets)
    ):
        raise invalid("The selected Background has no resolved Sphere/Talent route authority.")

    def normalized_authority_text(value: str) -> str:
        return re.sub(r"\s+", " ", value.replace("’", "'").casefold()).strip()

    selected_sphere = current_background.get("background_sphere")
    selected_talent = current_background.get("background_talent")
    if (
        not isinstance(selected_sphere, str)
        or not selected_sphere.strip()
        or not isinstance(selected_talent, str)
        or not selected_talent.strip()
    ):
        raise invalid("The selected Background Sphere/Talent pair is missing; grant mode cannot be inferred safely.")
    sphere_marker = f"{normalized_authority_text(selected_sphere)} sphere."
    talent_marker = f"and the **{normalized_authority_text(selected_talent)}**"
    if not any(
        sphere_marker in normalized_authority_text(route)
        and talent_marker in normalized_authority_text(route)
        for route in route_bullets
    ):
        raise invalid(
            "The selected Background Sphere/Talent pair is not one fixed canonical route.",
            details={"background_sphere": selected_sphere, "background_talent": selected_talent},
        )
    background_grant_mode = "sphere_and_talent"
    if ability_projection.get("background_id") not in (None, background_id):
        raise invalid("The ability projection is bound to a different Background.", details={"background_id": background_id})
    bound_packet_id = ability_projection.get("background_packet_id")
    if bound_packet_id is None:
        bound_packet_ids = ability_projection.get("background_source_packet_ids")
        if isinstance(bound_packet_ids, list) and len(bound_packet_ids) == 1:
            bound_packet_id = bound_packet_ids[0]
    if bound_packet_id is not None and bound_packet_id != background_packet_id:
        raise invalid("The ability projection is bound to a different Background packet.", details={"packet_id": background_packet_id})
    supplied_native_hash = ability_projection.get("native_registry_sha256")
    native_registry_sha256 = hashlib.sha256(native_registry_bytes).hexdigest()
    if supplied_native_hash is not None and supplied_native_hash != native_registry_sha256:
        raise invalid("The ability projection is bound to a different native packet registry.")

    def binding_without_generated_fields(row: Mapping[str, Any]) -> dict[str, Any]:
        value = deepcopy(dict(row))
        value.pop("allocation_id", None)
        value.pop("grant_mode", None)
        return value

    for label, row in (("raw", raw_background), ("copied", current_background)):
        existing_mode = row.get("grant_mode", _MISSING)
        if existing_mode not in (_MISSING, None, background_grant_mode):
            raise invalid(
                "A Background grant mode diverges from the fixed canonical route.",
                details={"label": label, "grant_mode": existing_mode},
            )

    def deterministic_allocation_id(channel: str, packet_id: str) -> str:
        return f"allocation.{channel}.{packet_id}"

    def row_allocation_id(raw_row: Mapping[str, Any], current_row: Mapping[str, Any], *, channel: str, packet_id: str) -> str:
        raw_value = raw_row.get("allocation_id", _MISSING)
        expected = deterministic_allocation_id(channel, packet_id)
        if raw_value is not _MISSING and raw_value is not None:
            if not isinstance(raw_value, str) or not raw_value.strip():
                raise invalid("An existing Background/Origin allocation ID is malformed.", details={"channel": channel})
            expected = raw_value
        current_value = current_row.get("allocation_id", _MISSING)
        if current_value not in (_MISSING, None, expected):
            raise invalid("The copied Background/Origin allocation ID diverges from authenticated identity.", details={"channel": channel})
        return expected

    if binding_without_generated_fields(current_background) != binding_without_generated_fields(raw_background):
        raise invalid("The copied Background row diverges from modern provenance.")
    if binding_without_generated_fields(current_origin) != binding_without_generated_fields(raw_origin):
        raise invalid("The copied Origin row diverges from modern provenance.")
    background_allocation_id = row_allocation_id(
        raw_background,
        current_background,
        channel="background",
        packet_id=background_packet_id,
    )
    origin_allocation_id = row_allocation_id(
        raw_origin,
        current_origin,
        channel="origin",
        packet_id=origin_packet_id,
    )
    if background_allocation_id == origin_allocation_id:
        raise invalid("The Background and Origin allocation IDs collide.")

    background_allocation = {
        "allocation_id": background_allocation_id,
        "channel": "background",
        "grant_type": "background",
        "grant_id": background_id,
        "name": background_name,
        "slot_cost": 0,
        "source_packet_ids": [background_packet_id],
    }
    origin_allocation = {
        "allocation_id": origin_allocation_id,
        "channel": "origin",
        "grant_type": "origin_insight",
        "grant_id": origin_id,
        "name": origin_name,
        "slot_cost": 0,
        "source_packet_ids": [origin_packet_id],
    }

    raw_advancement = raw_ledger.get("advancement")
    current_advancement = ledger.get("advancement")
    raw_levels = raw_advancement.get("levels") if isinstance(raw_advancement, Mapping) else None
    current_levels = current_advancement.get("levels") if isinstance(current_advancement, Mapping) else None
    if (
        not isinstance(raw_levels, list)
        or not isinstance(current_levels, list)
        or len(raw_levels) != target_cl
        or len(current_levels) != target_cl
        or [row.get("cl") if isinstance(row, Mapping) else None for row in raw_levels] != list(range(1, target_cl + 1))
        or [row.get("cl") if isinstance(row, Mapping) else None for row in current_levels] != list(range(1, target_cl + 1))
    ):
        raise invalid("The copied level sequence is not gap-free for Background/Origin allocation projection.")

    supplied_asi = ability_projection.get("allocations_by_cl")
    if supplied_asi is None:
        supplied_asi = {str(cl): [] for cl in range(1, target_cl + 1)}
    if not isinstance(supplied_asi, Mapping):
        raise invalid("The ability projection allocation map is malformed.")
    asi_by_cl: dict[str, list[dict[str, Any]]] = {}
    seen_asi_ids: set[str] = set()
    for cl in range(1, target_cl + 1):
        key = str(cl)
        rows = supplied_asi.get(key, _MISSING)
        if rows is _MISSING or not isinstance(rows, list):
            raise invalid("The ability projection allocation map is incomplete.", details={"cl": cl})
        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise invalid("The ability projection contains a malformed allocation row.", details={"cl": cl})
            value = deepcopy(dict(row))
            allocation_id = value.get("allocation_id")
            if not isinstance(allocation_id, str) or not allocation_id.strip() or allocation_id in seen_asi_ids:
                raise invalid("The ability projection contains duplicate or missing allocation IDs.", details={"cl": cl})
            if value.get("channel") != "event" or value.get("grant_type") != "event" or value.get("event_type") not in _ABILITY_MILESTONE_EVENT_TYPES:
                raise invalid("The ability projection contains a non-ASI allocation row.", details={"cl": cl})
            source_packet_ids = value.get("source_packet_ids")
            if not isinstance(source_packet_ids, list) or not source_packet_ids or any(not isinstance(packet_id, str) or not packet_id.strip() for packet_id in source_packet_ids):
                raise invalid("The ability projection ASI allocation lacks source packets.", details={"cl": cl})
            if any(packet_id not in modern_by_id for packet_id in source_packet_ids):
                raise invalid("The ability projection ASI allocation references an unknown packet.", details={"cl": cl})
            seen_asi_ids.add(allocation_id)
            normalized_rows.append(value)
        asi_by_cl[key] = normalized_rows

    def level_allocations(row: Mapping[str, Any], *, cl: int) -> list[dict[str, Any]]:
        value = row.get("allocations", [])
        if value is None:
            return []
        if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
            raise invalid("The copied level allocation list is malformed.", details={"cl": cl})
        result: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_grants: set[tuple[Any, Any]] = set()
        for item in value:
            normalized = deepcopy(dict(item))
            allocation_id = normalized.get("allocation_id")
            if not isinstance(allocation_id, str) or not allocation_id.strip() or allocation_id in seen_ids:
                raise invalid("The copied level allocation IDs are missing or duplicated.", details={"cl": cl})
            grant_key = (normalized.get("grant_type"), normalized.get("grant_id"))
            if grant_key in seen_grants:
                raise invalid("The copied level grant identities are duplicated.", details={"cl": cl})
            seen_ids.add(allocation_id)
            seen_grants.add(grant_key)
            result.append(normalized)
        return result

    projected_levels = deepcopy(current_levels)
    preserved_asi_by_cl: dict[str, list[dict[str, Any]]] = {}
    projected_allocation_rows_by_cl: dict[str, list[dict[str, Any]]] = {}
    for index, (raw_level, current_level, projected_level) in enumerate(zip(raw_levels, current_levels, projected_levels), start=1):
        if not isinstance(raw_level, Mapping) or not isinstance(current_level, Mapping):
            raise invalid("The copied level row is malformed.", details={"cl": index})
        raw_allocations = level_allocations(raw_level, cl=index)
        current_allocations = level_allocations(current_level, cl=index)
        expected_asi = asi_by_cl[str(index)]
        raw_asi = [row for row in raw_allocations if row in expected_asi]
        if raw_asi and len(raw_asi) != len(expected_asi):
            raise invalid("The raw level contains only a partial authenticated ASI allocation set.", details={"cl": index})
        if raw_asi:
            expected_base = raw_allocations
            preserved_asi_by_cl[str(index)] = deepcopy(expected_asi)
        else:
            expected_base = raw_allocations + expected_asi
            preserved_asi_by_cl[str(index)] = deepcopy(expected_asi)
        if current_allocations != expected_base:
            raise invalid("The copied level allocations diverge from raw data plus authenticated ASI events.", details={"cl": index})
        generated = [background_allocation, origin_allocation] if index == 1 else []
        existing_generated = [row for row in current_allocations if row in generated]
        if existing_generated and existing_generated != generated:
            raise invalid("The copied CL1 Background/Origin allocation set is partial or reordered.")
        if existing_generated:
            final_allocations = current_allocations
        else:
            existing_ids = {row.get("allocation_id") for row in current_allocations}
            if any(row["allocation_id"] in existing_ids for row in generated):
                raise invalid("A generated Background/Origin allocation collides with an existing allocation.")
            final_allocations = current_allocations + generated
        final_ids: set[str] = set()
        final_grants: set[tuple[Any, Any]] = set()
        for row in final_allocations:
            allocation_id = row.get("allocation_id")
            grant_key = (row.get("grant_type"), row.get("grant_id"))
            if allocation_id in final_ids or grant_key in final_grants:
                raise invalid("The projected level allocation identities are duplicated.", details={"cl": index})
            final_ids.add(allocation_id)
            final_grants.add(grant_key)
        projected_level["allocations"] = deepcopy(final_allocations)
        projected_allocation_rows_by_cl[str(index)] = deepcopy(final_allocations)

    projected_ledger = deepcopy(dict(ledger))
    projected_background_origin = deepcopy(dict(current_background_origin))
    projected_background = deepcopy(dict(current_background))
    projected_origin = deepcopy(dict(current_origin))
    projected_background["allocation_id"] = background_allocation_id
    projected_background["grant_mode"] = background_grant_mode
    projected_origin["allocation_id"] = origin_allocation_id
    projected_background_origin["background"] = projected_background
    projected_background_origin["origin_insight"] = projected_origin
    projected_ledger["background_origin"] = projected_background_origin
    projected_advancement = deepcopy(dict(current_advancement))
    projected_advancement["levels"] = projected_levels
    projected_ledger["advancement"] = projected_advancement

    # Some accepted source workspaces retain the same selection under the
    # human-facing Build mirror.  When present, keep that copied surface in
    # lockstep with the compiler ledger.  A malformed mirror is not silently
    # ignored; otherwise the two canonical views could disagree after this
    # compatibility projection.
    mirror_path = root / "Build/Background_Origin_Ledger.json"
    projected_mirror: dict[str, Any] | None = None
    if mirror_path.is_symlink() or mirror_path.exists():
        if mirror_path.is_symlink() or not mirror_path.is_file():
            raise invalid("The copied Background/Origin mirror is missing or unsafe.", details={"path": str(mirror_path)})
        mirror_value = _read_json(mirror_path, code="FINAL_CHARACTER_GRANT_ALLOCATION_PROJECTION_INVALID")
        if not isinstance(mirror_value, Mapping):
            raise invalid("The copied Background/Origin mirror is not a mapping.")
        mirror_surface = mirror_value.get("background_origin")
        if not isinstance(mirror_surface, Mapping):
            raise invalid("The copied Background/Origin mirror has no canonical background_origin surface.")
        mirror_background = mirror_surface.get("background")
        mirror_origin = mirror_surface.get("origin_insight")
        if not isinstance(mirror_background, Mapping) or not isinstance(mirror_origin, Mapping):
            raise invalid("The copied Background/Origin mirror rows are incomplete.")
        mirror_grant_mode = mirror_background.get("grant_mode", _MISSING)
        if mirror_grant_mode not in (_MISSING, None, background_grant_mode):
            raise invalid(
                "The copied Background/Origin mirror grant mode diverges from the fixed canonical route.",
                details={"grant_mode": mirror_grant_mode},
            )
        for label, row, expected in (
            ("background", mirror_background, current_background),
            ("origin", mirror_origin, current_origin),
        ):
            if binding_without_generated_fields(row) != binding_without_generated_fields(expected):
                raise invalid("The copied Background/Origin mirror diverges from the compiler ledger.", details={"row": label})
        projected_mirror = deepcopy(dict(mirror_value))
        projected_mirror_background = deepcopy(dict(mirror_background))
        projected_mirror_origin = deepcopy(dict(mirror_origin))
        projected_mirror_background["allocation_id"] = background_allocation_id
        projected_mirror_background["grant_mode"] = background_grant_mode
        projected_mirror_origin["allocation_id"] = origin_allocation_id
        projected_mirror_surface = deepcopy(dict(mirror_surface))
        projected_mirror_surface["background"] = projected_mirror_background
        projected_mirror_surface["origin_insight"] = projected_mirror_origin
        projected_mirror["background_origin"] = projected_mirror_surface

    provenance = {
        "schema_version": "TianxiaFoundry.FinalCharacterGrantAllocationProjectionProvenance.v1",
        "source_ledger_path": "Build/Character_Master_Ledger.json",
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": hashlib.sha256(raw_provenance_bytes).hexdigest(),
        "packet_registry_path": "Command_2/Rules_Selection_Packets.json",
        "packet_registry_sha256": native_registry_sha256,
        "packet_modern_provenance_path": modern_registry_path.relative_to(root).as_posix() if native_mode else "Command_2/Rules_Selection_Packets.json",
        "packet_modern_provenance_sha256": hashlib.sha256(modern_registry_bytes).hexdigest(),
        "target_cl": target_cl,
        "background": {
            "background_id": background_id,
            "name": background_name,
            "source_packet_ids": [background_packet_id],
            "allocation_id": background_allocation_id,
            "grant_mode": background_grant_mode,
            "allocation": deepcopy(background_allocation),
        },
        "origin": {
            "origin_insight_id": origin_id,
            "name": origin_name,
            "source_packet_ids": [origin_packet_id],
            "allocation_id": origin_allocation_id,
            "allocation": deepcopy(origin_allocation),
        },
        "preserved_asi_allocations_by_cl": preserved_asi_by_cl,
        "background_origin_allocations_by_cl": {"1": [deepcopy(background_allocation), deepcopy(origin_allocation)]},
        "allocations_by_cl": projected_allocation_rows_by_cl,
    }
    _write_json(details_path, provenance)
    _write_json(ledger_path, projected_ledger)
    if projected_mirror is not None:
        _write_json(mirror_path, projected_mirror)
    reread = _read_json(ledger_path, code="FINAL_CHARACTER_GRANT_ALLOCATION_PROJECTION_INVALID")
    if reread != projected_ledger or raw_provenance_path.read_bytes() != raw_provenance_bytes:
        raise invalid("The compiler grant-allocation projection could not be read back exactly or altered raw provenance.")
    if projected_mirror is not None:
        mirror_reread = _read_json(mirror_path, code="FINAL_CHARACTER_GRANT_ALLOCATION_PROJECTION_INVALID")
        if mirror_reread != projected_mirror:
            raise invalid("The Background/Origin mirror projection could not be read back exactly.")
    return {
        "schema_version": provenance["schema_version"],
        "source_ledger_path": provenance["source_ledger_path"],
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": provenance["modern_provenance_sha256"],
        "packet_registry_path": provenance["packet_registry_path"],
        "packet_registry_sha256": native_registry_sha256,
        "packet_modern_provenance_path": provenance["packet_modern_provenance_path"],
        "packet_modern_provenance_sha256": provenance["packet_modern_provenance_sha256"],
        "details_path": _GRANT_PROJECTION_DETAILS_RELATIVE,
        "details_sha256": sha256_file(details_path),
        "target_cl": target_cl,
        "background_id": background_id,
        "background_packet_id": background_packet_id,
        "background_allocation_id": background_allocation_id,
        "background_grant_mode": background_grant_mode,
        "origin_id": origin_id,
        "origin_packet_id": origin_packet_id,
        "origin_allocation_id": origin_allocation_id,
        "background_origin_allocations_by_cl": {"1": [deepcopy(background_allocation), deepcopy(origin_allocation)]},
        "preserved_asi_allocations_by_cl": preserved_asi_by_cl,
        "allocations_by_cl": projected_allocation_rows_by_cl,
    }


def _project_background_equipment_for_compiler(workspace: Path) -> dict[str, Any]:
    """Project one fixed Background's printed starting equipment.

    Stage 2 intentionally records no optional inventory selection.  The legacy
    compiler requires a list at the top-level ``equipment`` field, so this
    boundary projects only an empty list there while retaining the exact
    explicit-none mapping under ``typed_none.equipment``.  Separately, the
    selected Background's printed equipment is rendered from its hash-pinned,
    resolved authority sentence under ``background_origin.background`` (and
    its display mirror).  It does not turn the abstract keepsake into an
    owner-selected item or manufacture ledger IDs.  Every inventory surface
    must remain the sealed explicit-none state; any other or conflicting state
    is rejected before either canonical Background surface is written.
    """

    def invalid(message: str, *, details: Any = None) -> FoundryError:
        return _error("FINAL_CHARACTER_BACKGROUND_EQUIPMENT_PROJECTION_INVALID", message, details=details)

    root = Path(workspace)
    ledger_path = root / "Build/Character_Master_Ledger.json"
    raw_provenance_path = root / _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    mirror_path = root / "Build/Background_Origin_Ledger.json"
    inventory_paths = (
        root / "Build/Equipment_Ledger.json",
        root / "Build/Equipment_Ledger_Legacy.json",
        root / "Build/Item_Execution_Coverage.json",
        root / "Build/Selected_Item_GM_Projection.json",
    )
    required_paths = (ledger_path, raw_provenance_path, *inventory_paths, mirror_path)
    for path in required_paths:
        if path.is_symlink() or not path.is_file():
            raise invalid("The copied Background/equipment inputs are missing or unsafe.", details={"path": str(path)})
    if mirror_path.is_symlink() or (mirror_path.exists() and not mirror_path.is_file()):
        raise invalid("The copied Background/Origin mirror is missing or unsafe.", details={"path": str(mirror_path)})

    try:
        raw_provenance_bytes = raw_provenance_path.read_bytes()
        raw_provenance_sha256 = hashlib.sha256(raw_provenance_bytes).hexdigest()
        raw_ledger = _read_json(raw_provenance_path, code="FINAL_CHARACTER_BACKGROUND_EQUIPMENT_PROJECTION_INVALID")
        ledger = _read_json(ledger_path, code="FINAL_CHARACTER_BACKGROUND_EQUIPMENT_PROJECTION_INVALID")
        inventory_bytes = {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in inventory_paths
        }
        inventory_values = {
            path.relative_to(root).as_posix(): _read_json(path, code="FINAL_CHARACTER_BACKGROUND_EQUIPMENT_PROJECTION_INVALID")
            for path in inventory_paths
        }
        mirror_value = _read_json(mirror_path, code="FINAL_CHARACTER_BACKGROUND_EQUIPMENT_PROJECTION_INVALID")
    except (OSError, FoundryError) as exc:
        if isinstance(exc, FoundryError):
            raise invalid("The copied Background/equipment inputs could not be read.", details={"cause": exc.code}) from exc
        raise invalid("The copied Background/equipment inputs could not be read.") from exc
    if not isinstance(raw_ledger, Mapping) or not isinstance(ledger, Mapping):
        raise invalid("The copied modern and compiler ledgers must be mappings.")
    if not isinstance(mirror_value, Mapping):
        raise invalid("The copied Background/Origin mirror must be a mapping.")

    # The selected no-equipment state is an independent sealed C1A choice.  It
    # is not the Background's mandatory printed starting equipment and must
    # not be silently converted into a guessed inventory.
    explicit_none = {
        "reason": "No equipment was selected.",
        "reason_code": "not_selected_for_c1a_proof",
        "source_backed": True,
        "state": "none",
    }
    # Either the sealed explicit-none state, or exactly one controller-built
    # starting kit that re-resolves from the pinned kit authority.
    kit_rows = raw_ledger.get("equipment") if isinstance(raw_ledger.get("equipment"), list) else None
    for label, value in (("raw ledger", raw_ledger), ("copied ledger", ledger)):
        typed_none = value.get("typed_none")
        if kit_rows is None:
            if value.get("equipment") != explicit_none:
                raise invalid("The sealed candidate equipment state is not explicit none.", details={"label": label})
            if not isinstance(typed_none, Mapping) or typed_none.get("equipment") != explicit_none:
                raise invalid("The sealed candidate typed-none equipment state is incomplete.", details={"label": label})
        elif value.get("equipment") != kit_rows or (isinstance(typed_none, Mapping) and "equipment" in typed_none):
            raise invalid("The sealed candidate starting kit is inconsistent.", details={"label": label})
    starting_kit: dict[str, Any] | None = None
    if kit_rows is not None:
        from character_creation.constructed_arts.records import construct_starting_kit

        kit = kit_rows[0].get("starting_kit") if len(kit_rows) == 1 and isinstance(kit_rows[0], Mapping) else None
        if not isinstance(kit, Mapping):
            raise invalid("The sealed equipment is not exactly one constructed starting kit.")
        try:
            rebuilt = construct_starting_kit(
                background_id=kit["background_id"],
                path_id=kit["path_id"],
                path_option=kit["path_option"],
                picks=kit["picks"],
                seed=kit["seed"],
                purchases=kit.get("purchases"),
                treasure_weapon=kit.get("treasure_weapon"),
                treasure_armor=kit.get("treasure_armor"),
                treasure_purchases=kit.get("treasure_purchases"),
            )
        except (FoundryError, KeyError, TypeError) as exc:
            raise invalid("The sealed starting kit does not re-resolve.", details={"cause": getattr(exc, "code", type(exc).__name__)}) from exc
        resolved = rebuilt["resolved"]
        if (
            rebuilt["kit_id"] != kit.get("kit_id")
            or kit_rows[0].get("record_id") != rebuilt["kit_id"]
            or resolved["items"] != kit.get("items")
            or resolved["trinkets"] != kit.get("trinkets")
            or resolved["coin_cc"] != kit.get("coin_cc")
            or resolved.get("treasure_weapon") != kit.get("resolved_treasure_weapon")
            or resolved.get("treasure_armor") != kit.get("resolved_treasure_armor")
            or resolved.get("treasure_purchases") != kit.get("resolved_treasure_purchases")
        ):
            raise invalid("The sealed starting kit differs from its re-resolution.")
        starting_kit = deepcopy(dict(kit_rows[0]))

    expected_inventory_schemas = {
        "Build/Equipment_Ledger.json": "TianxiaFoundry.CharacterGMEquipment.v1",
        "Build/Equipment_Ledger_Legacy.json": "TianxiaFoundry.CharacterGMEquipmentLegacy.v1",
        "Build/Item_Execution_Coverage.json": "TianxiaFoundry.ItemExecutionCoverage.v1",
        "Build/Selected_Item_GM_Projection.json": "TianxiaFoundry.ItemGMScreenSelectedProjection.v1",
    }
    for relative, value in inventory_values.items():
        if not isinstance(value, Mapping) or value.get("schema_version") != expected_inventory_schemas[relative]:
            raise invalid("A sealed candidate equipment surface has an unexpected schema.", details={"path": relative})
        items = value.get("equipment") if relative.startswith("Build/Equipment_Ledger") else value.get("items")
        if starting_kit is not None and relative.startswith("Build/Equipment_Ledger"):
            if items != kit_rows or value.get("none_state") is not None:
                raise invalid("A sealed equipment ledger does not mirror the starting kit.", details={"path": relative})
            continue
        if not isinstance(items, list) or items:
            raise invalid(
                "The sealed candidate inventory is non-empty or malformed; no fixed starting-item binding is available.",
                details={"path": relative},
            )
        if relative.startswith("Build/Equipment_Ledger"):
            if value.get("none_state") != explicit_none:
                raise invalid("A sealed equipment ledger lacks the exact explicit-none state.", details={"path": relative})
        elif value.get("status") != "SOURCE_EXPLICIT_NONE":
            raise invalid("A sealed item projection lacks the exact explicit-none status.", details={"path": relative})
        if relative == "Build/Item_Execution_Coverage.json" and value.get("coverage") != []:
            raise invalid("The sealed item coverage is non-empty despite explicit-none inventory.")

    raw_background_origin = raw_ledger.get("background_origin")
    current_background_origin = ledger.get("background_origin")
    if not isinstance(raw_background_origin, Mapping) or not isinstance(current_background_origin, Mapping):
        raise invalid("The copied ledgers have no Background/Origin selection surface.")
    raw_background = raw_background_origin.get("background")
    current_background = current_background_origin.get("background")
    if not isinstance(raw_background, Mapping) or not isinstance(current_background, Mapping):
        raise invalid("The copied ledgers have no Background selection row.")

    background_authority = _bridge_fixed_json(
        _ABILITY_BACKGROUND_AUTHORITY_PATH,
        _ABILITY_BACKGROUND_AUTHORITY_SHA256,
    )
    fixed_rows = background_authority.get("backgrounds") if isinstance(background_authority, Mapping) else None
    fixed_matches = (
        [row for row in fixed_rows if isinstance(row, Mapping) and row.get("background_id") == raw_background.get("background_id")]
        if isinstance(fixed_rows, list)
        else []
    )
    if (
        not isinstance(background_authority, Mapping)
        or background_authority.get("schema") != "Tianxia.BackgroundCoreCatalog.v1"
        or len(fixed_matches) != 1
    ):
        raise invalid("The selected Background lacks one fixed canonical authority row.")
    fixed_background = fixed_matches[0]
    if (
        fixed_background.get("schema") != "Tianxia.BackgroundCoreAuthority.v1"
        or fixed_background.get("display_name") != raw_background.get("name")
        or not isinstance(fixed_background.get("source"), Mapping)
        or fixed_background["source"].get("path") != _ABILITY_BACKGROUND_SOURCE_PATH
        or not str(fixed_background["source"].get("anchor", "")).startswith("heading:")
        or fixed_background.get("blockers") != []
        or fixed_background.get("unresolved_fields") != []
    ):
        raise invalid("The selected Background is not the resolved hash-pinned authority.")
    starting_equipment = fixed_background.get("starting_equipment")
    try:
        printed_kit = background_kit(str(raw_background.get("background_id")))
    except FoundryError as exc:
        raise invalid("The selected Background has no pinned printed starting kit.", details={"cause": exc.code}) from exc
    if (
        not isinstance(starting_equipment, Mapping)
        or starting_equipment.get("resolved") is not True
        or starting_equipment.get("raw_authority") != printed_kit["raw_authority"]
    ):
        raise invalid(
            "The fixed Background starting-equipment authority is unresolved or changed.",
            details={"background_id": raw_background.get("background_id")},
        )

    # The printed kit entries, verbatim; catalog binding and choices are resolved
    # by the starting-kit authority, not invented here.
    expected_equipment = [entry["printed"] for entry in printed_kit["entries"]]
    expected_reconciliation = {
        "printed_items": deepcopy(expected_equipment),
        "ledger_equipment_ids": [starting_kit["record_id"]] if starting_kit is not None else [],
        "bundled_items": [],
        "missing_items": [],
        "note": (
            "Every printed starting-equipment entry is retained from the fixed Background authority; "
            + (
                "the controller-built starting kit binds them to catalog items."
                if starting_kit is not None
                else "the candidate's optional equipment inventory is explicitly none."
            )
        ),
    }
    generated_fields = {"allocation_id", "grant_mode", "equipment", "equipment_reconciliation"}

    def source_binding(row: Mapping[str, Any]) -> dict[str, Any]:
        value = deepcopy(dict(row))
        for field in generated_fields:
            value.pop(field, None)
        return value

    if source_binding(current_background) != source_binding(raw_background):
        raise invalid("The copied Background row diverges from modern provenance.")

    def validate_projection_fields(row: Mapping[str, Any], *, label: str) -> None:
        equipment_present = "equipment" in row
        reconciliation_present = "equipment_reconciliation" in row
        if equipment_present != reconciliation_present:
            raise invalid("A Background equipment projection is partial.", details={"label": label})
        if equipment_present and (
            row.get("equipment") != expected_equipment
            or row.get("equipment_reconciliation") != expected_reconciliation
        ):
            raise invalid("A Background equipment projection diverges from fixed authority.", details={"label": label})

    validate_projection_fields(raw_background, label="raw")
    validate_projection_fields(current_background, label="copied")

    projected_ledger = deepcopy(dict(ledger))
    # The copied modern ledger keeps the explicit-none object as provenance,
    # while the legacy compiler-facing top-level field is the only equipment
    # value converted to its required list shape.  No inventory row or ID is
    # manufactured by this projection.
    projected_ledger["equipment"] = []
    if starting_kit is not None:
        # The kit stays in the final ledger; compiler-facing item rows are a
        # later translation.
        projected_ledger["starting_kit"] = deepcopy(starting_kit)
    projected_background_origin = deepcopy(dict(current_background_origin))
    projected_background = deepcopy(dict(current_background))
    projected_background["equipment"] = deepcopy(expected_equipment)
    projected_background["equipment_reconciliation"] = deepcopy(expected_reconciliation)
    projected_background_origin["background"] = projected_background
    projected_ledger["background_origin"] = projected_background_origin

    mirror_surface = mirror_value.get("background_origin")
    if not isinstance(mirror_surface, Mapping):
        raise invalid("The copied Background/Origin mirror has no canonical surface.")
    mirror_background = mirror_surface.get("background")
    mirror_origin = mirror_surface.get("origin_insight")
    current_origin = current_background_origin.get("origin_insight")
    if (
        not isinstance(mirror_background, Mapping)
        or not isinstance(mirror_origin, Mapping)
        or not isinstance(current_origin, Mapping)
        or source_binding(mirror_background) != source_binding(current_background)
        or mirror_origin != current_origin
    ):
        raise invalid("The copied Background/Origin mirror diverges from the compiler ledger.")
    validate_projection_fields(mirror_background, label="mirror")
    projected_mirror = deepcopy(dict(mirror_value))
    projected_mirror_surface = deepcopy(dict(mirror_surface))
    projected_mirror_background = deepcopy(dict(mirror_background))
    projected_mirror_background["equipment"] = deepcopy(expected_equipment)
    projected_mirror_background["equipment_reconciliation"] = deepcopy(expected_reconciliation)
    projected_mirror_surface["background"] = projected_mirror_background
    projected_mirror["background_origin"] = projected_mirror_surface

    _write_json(ledger_path, projected_ledger)
    _write_json(mirror_path, projected_mirror)
    reread = _read_json(ledger_path, code="FINAL_CHARACTER_BACKGROUND_EQUIPMENT_PROJECTION_INVALID")
    if reread != projected_ledger or raw_provenance_path.read_bytes() != raw_provenance_bytes:
        raise invalid("The Background equipment projection could not be read back exactly or altered raw provenance.")
    for path in inventory_paths:
        relative = path.relative_to(root).as_posix()
        if path.read_bytes() != inventory_bytes[relative]:
            raise invalid("The Background equipment projection altered a sealed inventory mirror.", details={"path": relative})
    mirror_reread = _read_json(mirror_path, code="FINAL_CHARACTER_BACKGROUND_EQUIPMENT_PROJECTION_INVALID")
    if mirror_reread != projected_mirror:
        raise invalid("The Background/Origin mirror equipment projection could not be read back exactly.")
    return {
        "schema_version": "TianxiaFoundry.FinalCharacterBackgroundEquipmentProjection.v1",
        "source_ledger_path": "Build/Character_Master_Ledger.json",
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_provenance_sha256,
        "background_id": raw_background.get("background_id"),
        "background_name": raw_background.get("name"),
        "authority_path": _ABILITY_BACKGROUND_AUTHORITY_PATH,
        "authority_sha256": _ABILITY_BACKGROUND_AUTHORITY_SHA256,
        "equipment": deepcopy(expected_equipment),
        "legacy_top_level_equipment": [],
        "typed_none_equipment": deepcopy(explicit_none),
        "equipment_reconciliation": deepcopy(expected_reconciliation),
        "inventory_state": "SOURCE_STARTING_KIT" if starting_kit is not None else "SOURCE_EXPLICIT_NONE",
        "starting_kit": deepcopy(starting_kit),
    }


def _project_background_origin_insight_for_compiler(workspace: Path) -> dict[str, Any]:
    """Project the fixed Born Under Suspicion source section for the compiler.

    The modern Stage-2 row intentionally carries the selected skill/result and
    a short source-backed summary, while the pinned compiler requires the
    legacy ``benefit`` and ``effect_records`` fields.  This boundary derives
    those fields only from the hash-pinned Origin Insights source section and
    the already sealed selection.  The raw modern provenance remains an
    immutable comparison input; the compiler ledger and its Background/Origin
    mirror are updated together only after every source, packet, and existing
    projection check succeeds.
    """

    def invalid(message: str, *, details: Any = None) -> FoundryError:
        return _error("FINAL_CHARACTER_ORIGIN_INSIGHT_PROJECTION_INVALID", message, details=details)

    root = Path(workspace)
    ledger_path = root / "Build/Character_Master_Ledger.json"
    raw_provenance_path = root / _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    mirror_path = root / "Build/Background_Origin_Ledger.json"
    registry_path = root / "Command_2/Rules_Selection_Packets.json"
    build_registry_path = root / "Build/Rules_Selection_Packets.json"
    details_path = root / _ORIGIN_INSIGHT_PROJECTION_DETAILS_RELATIVE
    for path in (ledger_path, raw_provenance_path, mirror_path, registry_path):
        if path.is_symlink() or not path.is_file():
            raise invalid("The copied Origin Insight projection inputs are missing or unsafe.", details={"path": str(path)})
    if details_path.is_symlink() or details_path.exists():
        raise invalid("The copied workspace already contains Origin Insight projection provenance.")
    if build_registry_path.is_symlink() or (build_registry_path.exists() and not build_registry_path.is_file()):
        raise invalid("The copied Build packet registry is missing or unsafe.", details={"path": str(build_registry_path)})

    try:
        raw_provenance_bytes = raw_provenance_path.read_bytes()
        raw_provenance_sha256 = hashlib.sha256(raw_provenance_bytes).hexdigest()
        raw_ledger = _read_json(raw_provenance_path, code="FINAL_CHARACTER_ORIGIN_INSIGHT_PROJECTION_INVALID")
        ledger = _read_json(ledger_path, code="FINAL_CHARACTER_ORIGIN_INSIGHT_PROJECTION_INVALID")
        mirror_value = _read_json(mirror_path, code="FINAL_CHARACTER_ORIGIN_INSIGHT_PROJECTION_INVALID")
        registry = _read_json(registry_path, code="FINAL_CHARACTER_ORIGIN_INSIGHT_PROJECTION_INVALID")
        build_registry = (
            _read_json(build_registry_path, code="FINAL_CHARACTER_ORIGIN_INSIGHT_PROJECTION_INVALID")
            if build_registry_path.exists()
            else None
        )
    except (OSError, FoundryError) as exc:
        if isinstance(exc, FoundryError):
            raise invalid("The copied Origin Insight projection inputs could not be read.", details={"cause": exc.code}) from exc
        raise invalid("The copied Origin Insight projection inputs could not be read.") from exc
    if not all(isinstance(value, Mapping) for value in (raw_ledger, ledger, mirror_value, registry)):
        raise invalid("The copied Origin Insight projection inputs must be mappings.")
    if build_registry is not None and build_registry != registry:
        raise invalid("The Build and Command 2 packet registries diverge.")
    packets = registry.get("packets")
    if registry.get("schema_version") != "TianxiaFoundry.RulesSelectionPackets.v2" or not isinstance(packets, list):
        raise invalid("The copied packet registry is not the sealed modern schema.")

    raw_background_origin = raw_ledger.get("background_origin")
    current_background_origin = ledger.get("background_origin")
    mirror_surface = mirror_value.get("background_origin")
    if not isinstance(raw_background_origin, Mapping) or not isinstance(current_background_origin, Mapping) or not isinstance(mirror_surface, Mapping):
        raise invalid("The copied Background/Origin surfaces are incomplete.")
    raw_origin = raw_background_origin.get("origin_insight")
    current_origin = current_background_origin.get("origin_insight")
    mirror_background = mirror_surface.get("background")
    mirror_origin = mirror_surface.get("origin_insight")
    current_background = current_background_origin.get("background")
    if not all(isinstance(value, Mapping) for value in (raw_origin, current_origin, mirror_background, mirror_origin, current_background)):
        raise invalid("The copied Background/Origin rows are incomplete.")

    origin_id = raw_origin.get("origin_insight_id")
    origin_name = raw_origin.get("name")
    if origin_id != _ORIGIN_INSIGHT_ID or origin_name != _ORIGIN_INSIGHT_NAME:
        # This projection is deliberately closed over the currently accepted
        # source.  Other Origin rows remain untouched and will be rejected by
        # the compiler if their own source-backed legacy fields are absent.
        return {
            "schema_version": "TianxiaFoundry.FinalCharacterOriginInsightProjection.v1",
            "status": "not_applicable",
            "origin_insight_id": origin_id,
            "origin_insight_name": origin_name,
            "source_ledger_path": "Build/Character_Master_Ledger.json",
            "source_ledger_sha256": raw_provenance_sha256,
        }

    generated_fields = {"allocation_id", "benefit", "restrictions", "effect_records"}

    def source_binding(row: Mapping[str, Any]) -> dict[str, Any]:
        value = deepcopy(dict(row))
        for field in generated_fields:
            value.pop(field, None)
        return value

    if source_binding(current_origin) != source_binding(raw_origin):
        raise invalid("The copied Origin Insight row diverges from modern provenance.")
    if source_binding(mirror_origin) != source_binding(current_origin):
        raise invalid("The Background/Origin mirror Origin Insight row diverges from the compiler ledger.")
    if dict(mirror_background) != dict(current_background):
        raise invalid("The Background/Origin mirror Background row diverges from the compiler ledger.")

    source_path = _FINAL_CHARACTER_BASE_FACTORY_ROOT / _ORIGIN_INSIGHT_SOURCE_PATH
    try:
        if source_path.is_symlink() or not source_path.is_file() or sha256_file(source_path) != _ORIGIN_INSIGHT_SOURCE_SHA256:
            raise invalid("The fixed Origin Insight source is unavailable or changed.", details={"path": str(source_path)})
        source_text = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise invalid("The fixed Origin Insight source could not be read.", details={"path": str(source_path)}) from exc

    source_lines = source_text.splitlines()
    heading_matches = [
        index
        for index, line in enumerate(source_lines)
        if re.match(r"^##\s+\S", line.strip())
        and _bridge_heading_name(line) == "9 born under suspicion"
    ]
    if len(heading_matches) != 1:
        raise invalid("The fixed Origin Insight source heading is missing or ambiguous.")
    heading_index = heading_matches[0]
    section_end = next(
        (
            index
            for index in range(heading_index + 1, len(source_lines))
            if re.match(r"^##\s+\S", source_lines[index].strip())
        ),
        len(source_lines),
    )
    section = "\n".join(source_lines[heading_index:section_end]).strip()
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", section) if part.strip()]
    benefit_rows = [part for part in paragraphs if part.startswith("**Benefit.**")]
    advantage_rows = [part for part in paragraphs if part.startswith("You have advantage on checks made to detect")]
    reroll_rows = [part for part in paragraphs if part.startswith("Once per long rest, when you fail a Charisma or Wisdom check made to avoid false blame")]
    if len(benefit_rows) != 1 or len(advantage_rows) != 1 or len(reroll_rows) != 1:
        raise invalid("The fixed Origin Insight source lacks one exact compiler projection claim.")
    benefit = benefit_rows[0][len("**Benefit.**") :].strip()
    advantage_claim = advantage_rows[0]
    reroll_claim = reroll_rows[0]
    if not benefit or not advantage_claim or not reroll_claim:
        raise invalid("The fixed Origin Insight source contains an empty compiler projection claim.")

    packet_ids = raw_origin.get("source_packet_ids")
    if (
        not isinstance(packet_ids, list)
        or len(packet_ids) != 1
        or not isinstance(packet_ids[0], str)
        or not packet_ids[0].strip()
        or current_origin.get("source_packet_ids") != packet_ids
        or mirror_origin.get("source_packet_ids") != packet_ids
    ):
        raise invalid("The Origin Insight does not bind one exact source packet.")
    origin_packet_id = packet_ids[0]
    packet_matches = [
        packet
        for packet in packets
        if isinstance(packet, Mapping) and packet.get("packet_id") == origin_packet_id
    ]
    if len(packet_matches) != 1:
        raise invalid("The Origin Insight source packet is missing or duplicated.", details={"packet_id": origin_packet_id})
    origin_packet = packet_matches[0]
    evidence = origin_packet.get("source_evidence")
    evidence_row = evidence[0] if isinstance(evidence, list) and len(evidence) == 1 and isinstance(evidence[0], Mapping) else None
    if (
        origin_packet.get("record_id") != _ORIGIN_INSIGHT_ID
        or origin_packet.get("display_name") != _ORIGIN_INSIGHT_NAME
        or type(origin_packet.get("target_cl")) is not int
        or origin_packet.get("target_cl") != 1
        or origin_packet.get("advancement_kind") != "origin_insight_acquisition"
        or not isinstance(origin_packet.get("event_id"), str)
        or not origin_packet.get("event_id").strip()
        or not isinstance(evidence_row, Mapping)
        or evidence_row.get("source_path") != _ORIGIN_INSIGHT_SOURCE_PATH
        or evidence_row.get("source_hash") != _ORIGIN_INSIGHT_SOURCE_SHA256
        or evidence_row.get("source_anchor") != _ORIGIN_INSIGHT_SOURCE_ANCHOR
        or not _verify_modern_source_evidence(evidence_row.get("source_path"), evidence_row.get("source_hash"))
    ):
        raise invalid("The Origin Insight source packet is not the exact hash-pinned record.", details={"packet_id": origin_packet_id})
    for field in ("full_description", "short_description"):
        supplied = origin_packet.get(field)
        if supplied is not None and supplied != benefit:
            raise invalid("The Origin Insight packet description conflicts with the fixed source benefit.", details={"field": field})

    expected_selection = {
        "selected_skill": _ORIGIN_INSIGHT_SELECTED_SKILL,
        "result": _ORIGIN_INSIGHT_RESULT,
    }
    for label, row in (("raw", raw_origin), ("copied", current_origin), ("mirror", mirror_origin)):
        if any(row.get(field) != expected for field, expected in expected_selection.items()):
            raise invalid(
                "The Origin Insight selected skill/result is missing or conflicts with the sealed choice.",
                details={"label": label, **{field: row.get(field) for field in expected_selection}},
            )
        if row.get("initiative_effect") != _ORIGIN_INSIGHT_INITIATIVE_EFFECT:
            raise invalid(
                "The Origin Insight initiative effect is missing or conflicts with the sealed source row.",
                details={"label": label},
            )
        if "summary" in row and row.get("summary") != benefit:
            raise invalid("The Origin Insight summary conflicts with the fixed source benefit.", details={"label": label})

    raw_allocation_id = raw_origin.get("allocation_id", _MISSING)
    if raw_allocation_id not in (_MISSING, None) and (not isinstance(raw_allocation_id, str) or not raw_allocation_id.strip()):
        raise invalid("The existing Origin Insight allocation ID is malformed.")
    expected_allocation_id = raw_allocation_id if raw_allocation_id not in (_MISSING, None) else f"allocation.origin.{origin_packet_id}"
    for label, row in (("copied", current_origin), ("mirror", mirror_origin)):
        existing_allocation_id = row.get("allocation_id", _MISSING)
        if existing_allocation_id not in (_MISSING, None, expected_allocation_id):
            raise invalid("The Origin Insight allocation ID diverges from authenticated identity.", details={"label": label})

    effect_records = [
        {
            "effect_id": "ORI_BORN_UNDER_SUSPICION_PROFICIENCY",
            "effect_type": "proficiency",
            "trigger": "When the Origin Insight is gained.",
            "condition": "The sealed skill selection is Deception; the printed benefit applies to the chosen skill.",
            "effect": "Apply the sealed expertise result to Deception when the source condition is met.",
            "display_surface": "Background & Origin; Statistics",
            "source_claim_text": benefit,
            "source_packet_ids": [origin_packet_id],
        },
        {
            "effect_id": "ORI_BORN_UNDER_SUSPICION_JUDGMENT_ADVANTAGE",
            "effect_type": "conditional_advantage",
            "trigger": "When detecting prior judgment, blame-seeking, or questions posed while expecting guilt.",
            "condition": "The check must detect when someone has already judged you, is looking for an excuse to blame you, or is pretending to ask questions while expecting guilt.",
            "effect": "Gain advantage on the qualifying check.",
            "display_surface": "Procedures; Background & Origin",
            "source_claim_text": advantage_claim,
            "source_packet_ids": [origin_packet_id],
        },
        {
            "effect_id": "ORI_BORN_UNDER_SUSPICION_FALSE_BLAME_REROLL",
            "effect_type": "limited_reroll",
            "trigger": "Once per long rest after failing a qualifying Charisma or Wisdom check.",
            "condition": "The failed check must avoid false blame, deflect suspicion, or prove you are not the immediate threat.",
            "effect": "Reroll the d20; the new result resolves under the printed check.",
            "display_surface": "Actions; Background & Origin",
            "source_claim_text": reroll_claim,
            "source_packet_ids": [origin_packet_id],
        },
    ]
    expected_generated = {
        "allocation_id": expected_allocation_id,
        "benefit": benefit,
        "restrictions": [],
        "effect_records": effect_records,
    }
    for label, row in (("raw", raw_origin), ("copied", current_origin), ("mirror", mirror_origin)):
        for field, expected in expected_generated.items():
            if field in row and row.get(field) != expected:
                raise invalid(
                    "An existing Origin Insight compiler projection is missing, partial, or conflicting.",
                    details={"label": label, "field": field},
                )

    projected_ledger = deepcopy(dict(ledger))
    projected_background_origin = deepcopy(dict(current_background_origin))
    projected_origin = deepcopy(dict(current_origin))
    projected_origin.update(deepcopy(expected_generated))
    projected_background_origin["origin_insight"] = projected_origin
    projected_ledger["background_origin"] = projected_background_origin

    projected_mirror = deepcopy(dict(mirror_value))
    projected_mirror_surface = deepcopy(dict(mirror_surface))
    projected_mirror_origin = deepcopy(dict(mirror_origin))
    projected_mirror_origin.update(deepcopy(expected_generated))
    projected_mirror_surface["origin_insight"] = projected_mirror_origin
    projected_mirror["background_origin"] = projected_mirror_surface

    provenance = {
        "schema_version": "TianxiaFoundry.FinalCharacterOriginInsightProjectionProvenance.v1",
        "source_ledger_path": "Build/Character_Master_Ledger.json",
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_provenance_sha256,
        "packet_registry_path": "Command_2/Rules_Selection_Packets.json",
        "packet_registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
        "origin_insight_id": _ORIGIN_INSIGHT_ID,
        "origin_insight_name": _ORIGIN_INSIGHT_NAME,
        "origin_packet_id": origin_packet_id,
        "origin_source_path": _ORIGIN_INSIGHT_SOURCE_PATH,
        "origin_source_sha256": _ORIGIN_INSIGHT_SOURCE_SHA256,
        "origin_source_anchor": _ORIGIN_INSIGHT_SOURCE_ANCHOR,
        "selected_skill": _ORIGIN_INSIGHT_SELECTED_SKILL,
        "result": _ORIGIN_INSIGHT_RESULT,
        "benefit": benefit,
        "restrictions": [],
        "effect_records": deepcopy(effect_records),
    }
    _write_json(details_path, provenance)
    _write_json(ledger_path, projected_ledger)
    _write_json(mirror_path, projected_mirror)
    reread = _read_json(ledger_path, code="FINAL_CHARACTER_ORIGIN_INSIGHT_PROJECTION_INVALID")
    mirror_reread = _read_json(mirror_path, code="FINAL_CHARACTER_ORIGIN_INSIGHT_PROJECTION_INVALID")
    if reread != projected_ledger or mirror_reread != projected_mirror or raw_provenance_path.read_bytes() != raw_provenance_bytes:
        raise invalid("The Origin Insight projection could not be read back exactly or altered raw provenance.")
    return {
        "schema_version": provenance["schema_version"],
        "source_ledger_path": provenance["source_ledger_path"],
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_provenance_sha256,
        "details_path": _ORIGIN_INSIGHT_PROJECTION_DETAILS_RELATIVE,
        "details_sha256": sha256_file(details_path),
        "origin_insight_id": _ORIGIN_INSIGHT_ID,
        "origin_insight_name": _ORIGIN_INSIGHT_NAME,
        "origin_packet_id": origin_packet_id,
        "origin_source_path": _ORIGIN_INSIGHT_SOURCE_PATH,
        "origin_source_sha256": _ORIGIN_INSIGHT_SOURCE_SHA256,
        "origin_source_anchor": _ORIGIN_INSIGHT_SOURCE_ANCHOR,
        "selected_skill": _ORIGIN_INSIGHT_SELECTED_SKILL,
        "result": _ORIGIN_INSIGHT_RESULT,
        "benefit": benefit,
        "restrictions": [],
        "effect_records": deepcopy(effect_records),
    }


def _project_modern_resource_for_compiler(
    workspace: Path,
    *,
    path_projection: Mapping[str, Any] | None = None,
    ability_projection: Mapping[str, Any] | None = None,
    method_projection: Mapping[str, Any] | None = None,
    foundation_projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project the sealed primary Path resource progression into compiler fields.

    The modern ledger carries source-rich per-level resource rows.  The
    pinned compiler consumes the same source arithmetic as an explicit
    component map.  This boundary authenticates every selected Path while
    projecting the primary Path's compiler resource, ability-score timeline,
    and source resource rows before adding the compiler component map.  The
    source rows remain intact in the dedicated projection provenance file and
    every projected row retains its source fields.
    """

    def invalid(message: str, *, details: Any = None) -> FoundryError:
        return _error("FINAL_CHARACTER_RESOURCE_PROJECTION_INVALID", message, details=details)

    root = Path(workspace)
    ledger_path = root / "Build/Character_Master_Ledger.json"
    raw_provenance_path = root / _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    path_details_path = root / _PATH_PROJECTION_DETAILS_RELATIVE
    method_details_path = root / _METHOD_PROJECTION_DETAILS_RELATIVE
    details_path = root / _RESOURCE_PROJECTION_DETAILS_RELATIVE
    if not isinstance(method_projection, Mapping):
        raise invalid("The resource projection requires an authenticated Method projection.")
    for path in (ledger_path, raw_provenance_path, path_details_path, method_details_path):
        if path.is_symlink() or not path.is_file():
            raise invalid("The copied resource projection inputs are missing or unsafe.", details={"path": str(path)})
    if details_path.exists():
        raise invalid("The copied workspace already contains resource projection provenance.")

    try:
        raw_provenance_bytes = raw_provenance_path.read_bytes()
        raw_provenance_sha256 = hashlib.sha256(raw_provenance_bytes).hexdigest()
        raw_ledger = _read_json(raw_provenance_path, code="FINAL_CHARACTER_RESOURCE_PROJECTION_INVALID")
        path_details = _read_json(path_details_path, code="FINAL_CHARACTER_RESOURCE_PROJECTION_INVALID")
        method_details = _read_json(method_details_path, code="FINAL_CHARACTER_RESOURCE_PROJECTION_INVALID")
        ledger = _read_json(ledger_path, code="FINAL_CHARACTER_RESOURCE_PROJECTION_INVALID")
    except (OSError, FoundryError) as exc:
        if isinstance(exc, FoundryError):
            raise invalid("The copied resource projection provenance could not be read.", details={"cause": exc.code}) from exc
        raise invalid("The copied resource projection provenance could not be read.") from exc
    if (
        not isinstance(raw_ledger, Mapping)
        or not isinstance(path_details, Mapping)
        or not isinstance(method_details, Mapping)
        or not isinstance(ledger, Mapping)
    ):
        raise invalid("The copied resource projection inputs are not mappings.")

    path_details_sha256 = sha256_file(path_details_path)
    if path_projection is not None:
        if (
            not isinstance(path_projection, Mapping)
            or path_projection.get("source_ledger_sha256") != raw_provenance_sha256
            or path_projection.get("modern_provenance_sha256") != raw_provenance_sha256
            or path_projection.get("details_sha256") != path_details_sha256
            or path_projection.get("path_id") != path_details.get("path_id")
            or path_details.get("source_ledger_sha256") != raw_provenance_sha256
        ):
            raise invalid("The resource projection is not bound to the authenticated Path projection.")
    elif path_details.get("source_ledger_sha256") != raw_provenance_sha256:
        raise invalid("The copied Path projection details are not bound to their raw ledger provenance.")

    raw_character = raw_ledger.get("character")
    character = ledger.get("character")
    raw_core_stats = raw_ledger.get("core_stats")
    core_stats = ledger.get("core_stats")
    if (
        not isinstance(raw_character, Mapping)
        or not isinstance(character, Mapping)
        or not isinstance(raw_core_stats, Mapping)
        or not isinstance(core_stats, Mapping)
    ):
        raise invalid("The copied ledger has no character/core-stat resource authority.")

    identity_fields = ("path_id", "path", "key_ability", "cl")
    if any(character.get(field) != raw_character.get(field) for field in identity_fields):
        raise invalid("The copied active Path identity diverges from raw resource provenance.")
    path_id = raw_character.get("path_id")
    path_name = raw_character.get("path")
    key_ability = raw_character.get("key_ability")
    target_cl = raw_character.get("cl")
    if (
        not isinstance(path_id, str)
        or not path_id.strip()
        or not isinstance(path_name, str)
        or not path_name.strip()
        or not isinstance(key_ability, str)
        or not key_ability.strip()
        or type(target_cl) is not int
        or not 1 <= target_cl <= 20
    ):
        raise invalid(
            "The copied active Path identity is incomplete.",
            details={"path_id": path_id, "path": path_name, "key_ability": key_ability, "cl": target_cl},
        )
    proof = _PACKET_PATH_PROOFS.get(path_id)
    if proof is None:
        raise invalid("The fixed Path proof is unavailable.", details={"path_id": path_id})

    # Re-prove the fixed Path identity and its resource rule.  Neither a
    # caller-supplied projection nor the modern ledger may establish this
    # authority on its own.
    path_index = _bridge_fixed_json(proof["index_path"], proof["index_sha256"])
    path_master = _bridge_fixed_json(_PACKET_PATH_MASTER_PATH, _PACKET_PATH_MASTER_SHA256)
    if not isinstance(path_index, Mapping) or not isinstance(path_master, Mapping):
        raise invalid("The fixed Path authority is unavailable or unsafe.")
    master_rows = path_master.get("paths")
    if not isinstance(master_rows, list):
        raise invalid("The fixed Path master has no canonical path list.")
    master_ids = [row.get("canonical_id") for row in master_rows if isinstance(row, Mapping)]
    if (
        len(master_ids) != len(master_rows)
        or any(not isinstance(value, str) or not value.strip() for value in master_ids)
        or len(set(master_ids)) != len(master_ids)
    ):
        raise invalid("The fixed Path master has malformed or duplicate canonical IDs.")
    master_matches = [row for row in master_rows if isinstance(row, Mapping) and row.get("canonical_id") == path_id]
    if len(master_matches) != 1:
        raise invalid("The fixed Path is missing or ambiguous in the Path master.")
    master_row = master_matches[0]
    path_profile = path_index.get("path_profile")
    index_source = path_index.get("source")
    master_source = master_row.get("source")
    if (
        path_index.get("canonical_id") != path_id
        or path_index.get("display_name") != path_name
        or path_index.get("publication_status") != "current_canonical_player_path"
        or master_row.get("display_name") != path_name
        or master_row.get("index_file") != proof["index_file"]
        or not isinstance(path_profile, Mapping)
        or not isinstance(index_source, Mapping)
        or not isinstance(master_source, Mapping)
        or index_source.get("corpus_path") != proof["corpus_path"]
        or index_source.get("sha256") != proof["corpus_sha256"]
        or master_source.get("corpus_path") != proof["corpus_path"]
        or master_source.get("sha256") != proof["corpus_sha256"]
    ):
        raise invalid("The fixed Path identity diverges from the hash-pinned source authority.")
    fixed_key_ability = path_profile.get("key_ability")
    master_key_ability = master_row.get("key_ability")
    if not isinstance(fixed_key_ability, Mapping) or fixed_key_ability != master_key_ability:
        raise invalid("The fixed Path key-ability authorities diverge.")
    key_options = fixed_key_ability.get("options")
    key_ability_names = {
        "STR": "Strength",
        "DEX": "Dexterity",
        "CON": "Constitution",
        "INT": "Intelligence",
        "WIS": "Wisdom",
        "CHA": "Charisma",
    }
    selected_key_name = key_ability_names.get(key_ability)
    if (
        not isinstance(key_options, list)
        or any(not isinstance(option, str) or not option.strip() for option in key_options)
        or selected_key_name not in key_options
    ):
        raise invalid("The selected Path key-ability option is malformed or not source-authorized.")
    resource_rules = path_index.get("resource_rules")
    if not isinstance(resource_rules, Mapping):
        raise invalid("The fixed Path has no resource rule authority.")
    resource_id = resource_rules.get("canonical_id")
    resource_name = resource_rules.get("name")
    maximum_formula = resource_rules.get("maximum_formula")
    minimum_formula = resource_rules.get("minimum_formula")
    source_section = resource_rules.get("source_section")
    expected_formula = (
        "Qi Cultivation CL × chosen key ability modifier"
        if path_id == "tianxia.path.qi_cultivation"
        else f"{path_name} CL × {selected_key_name} modifier"
    )
    if (
        not isinstance(resource_id, str)
        or not resource_id.strip()
        or not isinstance(resource_name, str)
        or not resource_name.strip()
        or maximum_formula != expected_formula
        or (minimum_formula is not None and minimum_formula != f"2 × {path_name} CL")
        or not isinstance(source_section, Mapping)
        or source_section.get("source_heading") != resource_name
        or type(source_section.get("source_line_start")) is not int
        or type(source_section.get("source_line_end")) is not int
        or source_section.get("source_line_start") < 1
        or source_section.get("source_line_end") < source_section.get("source_line_start")
        or not isinstance(source_section.get("source_markdown"), str)
        or not source_section.get("source_markdown").strip()
    ):
        raise invalid("The fixed Path resource formula authority is malformed.")

    expected_recovery_rules = {
        "short_rest": {
            "amount": resource_rules.get("short_rest", {}).get("amount"),
            "limit": resource_rules.get("short_rest", {}).get("limit"),
        },
        "long_rest": {
            "amount": resource_rules.get("long_rest", {}).get("amount"),
            "limit": resource_rules.get("long_rest", {}).get("limit"),
        },
        "full_cultivation_session": {
            "amount": resource_rules.get("full_cultivation_session", {}).get("amount"),
            "duration": resource_rules.get("full_cultivation_session", {}).get("duration"),
            "limit": resource_rules.get("full_cultivation_session", {}).get("limit"),
        },
    }
    actual_recovery_rules = {key: resource_rules.get(key) for key in expected_recovery_rules}
    if (
        actual_recovery_rules != expected_recovery_rules
        or any(
            not isinstance(value, str) or not value.strip()
            for row in actual_recovery_rules.values()
            for value in row.values()
        )
    ):
        raise invalid("The fixed Path recovery authority is malformed or unexpected.")
    recovery = (
        "Short Rest: "
        f"{actual_recovery_rules['short_rest']['amount']} "
        f"({actual_recovery_rules['short_rest']['limit']}); "
        "Long Rest: "
        f"{actual_recovery_rules['long_rest']['amount']} "
        f"({actual_recovery_rules['long_rest']['limit']}); "
        "Full Cultivation Session: "
        f"{actual_recovery_rules['full_cultivation_session']['amount']} "
        f"({actual_recovery_rules['full_cultivation_session']['duration']}; "
        f"{actual_recovery_rules['full_cultivation_session']['limit']})"
    )

    method_details_sha256 = sha256_file(method_details_path)
    method_details_projected = method_details.get("projected_method")
    method_id = method_projection.get("method_id")
    method_name = method_projection.get("method_name")
    method_path_ids = method_projection.get("path_ids")
    if not isinstance(method_path_ids, list):
        method_path_ids = [method_projection.get("path_id")]
    method_details_path_ids = method_details.get("path_ids")
    if not isinstance(method_details_path_ids, list):
        method_details_path_ids = [method_details.get("path_id")]
    if (
        method_projection.get("schema_version") != "TianxiaFoundry.FinalCharacterMethodProjectionProvenance.v1"
        or method_projection.get("source_ledger_sha256") != raw_provenance_sha256
        or method_projection.get("modern_provenance_sha256") != raw_provenance_sha256
        or method_projection.get("details_path") != _METHOD_PROJECTION_DETAILS_RELATIVE
        or method_projection.get("details_sha256") != method_details_sha256
        or not isinstance(method_id, str)
        or not method_id.strip()
        or not isinstance(method_name, str)
        or not method_name.strip()
        or method_projection.get("method_id") != method_id
        or method_projection.get("method_name") != method_name
        or method_projection.get("path_id") != path_id
        or method_projection.get("resource_name") != resource_name
        or method_projection.get("resource_formula") != maximum_formula
        or method_details.get("schema_version") != "TianxiaFoundry.FinalCharacterMethodProjectionProvenance.v1"
        or method_details.get("source_ledger_sha256") != raw_provenance_sha256
            or method_details.get("modern_provenance_sha256") != raw_provenance_sha256
            or method_details.get("method_id") != method_id
            or method_details.get("method_name") != method_name
            or method_details_path_ids != method_path_ids
        or not isinstance(method_details_projected, Mapping)
        or method_projection.get("projected_method") != method_details_projected
        or method_details_projected.get("method_id") != method_id
        or method_details_projected.get("name") != method_name
        or method_details_projected.get("resource_name") != resource_name
        or method_details_projected.get("resource_formula") != maximum_formula
    ):
        raise invalid("The resource projection is not bound to the authenticated Method projection.")

    path_rows, actual_path_packet_ids = _selected_path_rows_for_compiler_consumer(
        raw_ledger=raw_ledger,
        ledger=ledger,
        path_projection=path_projection,
        path_details=path_details,
        primary_path_id=path_id,
        primary_path_name=path_name,
        character_cl=target_cl,
        invalid=invalid,
    )
    path_row = path_rows[0]
    if path_row.get("key_ability") != key_ability:
        raise invalid("The primary Path key ability is not bound to the authenticated Path row.")
    path_packet_id = actual_path_packet_ids[0]
    if path_details.get("path_id") != path_id or path_details.get("path_name") != path_name:
        raise invalid("The Path projection details do not bind the primary Path.")
    if path_projection is not None:
        projected_path_ids = path_projection.get("path_ids") or [path_projection.get("path_id")]
        projected_packets = path_projection.get("path_source_packet_ids")
        if projected_path_ids != [row["path_id"] for row in path_rows] or projected_packets != actual_path_packet_ids:
            raise invalid("The Path projection packet binding diverges from sealed Path rows.")
        detail_path_ids = path_details.get("path_ids") or [path_details.get("path_id")]
        if detail_path_ids != projected_path_ids:
            raise invalid("The Path projection details omit a selected Path.")
    if method_path_ids != [row["path_id"] for row in path_rows]:
        raise invalid("The Method projection does not retain every selected Path.")

    # Every selected Path packet is part of the authenticated modern registry.
    # A fixed Path index alone cannot authorize a forged packet identity.
    registry_path = root / "Command_2/Rules_Selection_Packets.json"
    if registry_path.is_symlink() or not registry_path.is_file():
        raise invalid("The modern Path packet registry is missing or unsafe.")
    registry = _read_json(registry_path, code="FINAL_CHARACTER_RESOURCE_PROJECTION_INVALID")
    packet_rows = registry.get("packets") if isinstance(registry, Mapping) else None
    if not isinstance(packet_rows, list):
        raise invalid("The modern Path packet registry has no packet list.")
    for selected_path_row in path_rows:
        selected_path_id = selected_path_row["path_id"]
        selected_path_name = selected_path_row["display_name"]
        selected_proof = _PACKET_PATH_PROOFS.get(selected_path_id)
        selected_index = _bridge_fixed_json(selected_proof["index_path"], selected_proof["index_sha256"]) if selected_proof else None
        selected_packet_id = selected_path_row["source_packet_ids"][0]
        packet_matches = [row for row in packet_rows if isinstance(row, Mapping) and row.get("packet_id") == selected_packet_id]
        packet = packet_matches[0] if len(packet_matches) == 1 else None
        packet_evidence = packet.get("source_evidence") if isinstance(packet, Mapping) else None
        packet_evidence_row = packet_evidence[0] if isinstance(packet_evidence, list) and len(packet_evidence) == 1 and isinstance(packet_evidence[0], Mapping) else None
        if (
            not isinstance(selected_proof, Mapping)
            or not isinstance(selected_index, Mapping)
            or selected_index.get("canonical_id") != selected_path_id
            or selected_index.get("display_name") != selected_path_name
            or packet is None
            or packet.get("record_id") != selected_path_id
            or packet.get("display_name") != selected_path_name
            or type(packet.get("target_cl")) is not int
            or packet.get("target_cl") != 1
            or packet.get("advancement_kind") != "path_acquisition"
            or not isinstance(packet_evidence_row, Mapping)
            or packet_evidence_row.get("source_path") != selected_proof["index_path"]
            or packet_evidence_row.get("source_hash") != selected_proof["index_sha256"]
            or packet_evidence_row.get("source_anchor") != f"path:{selected_path_id}"
        ):
            raise invalid("A selected Path packet is not the exact fixed source binding.", details={"path_id": selected_path_id})

    raw_advancement = raw_ledger.get("advancement")
    current_advancement = ledger.get("advancement")
    raw_levels = raw_advancement.get("levels") if isinstance(raw_advancement, Mapping) else None
    current_levels = current_advancement.get("levels") if isinstance(current_advancement, Mapping) else None
    if (
        not isinstance(raw_levels, list)
        or len(raw_levels) != target_cl
        or not isinstance(current_levels, list)
        or len(current_levels) != target_cl
        or [row.get("cl") if isinstance(row, Mapping) else None for row in raw_levels] != list(range(1, target_cl + 1))
        or [row.get("cl") if isinstance(row, Mapping) else None for row in current_levels] != list(range(1, target_cl + 1))
    ):
        raise invalid("The copied resource timeline is not an exact gap-free CL sequence.")

    score_keys = set(_CORE_SAVE_ABILITIES)

    def exact_score_map(value: Any, label: str) -> dict[str, int]:
        if (
            not isinstance(value, Mapping)
            or set(value) != score_keys
            or any(type(amount) is not int for amount in value.values())
        ):
            raise invalid(f"The {label} ability timeline is incomplete or non-integer.")
        return {str(key): int(amount) for key, amount in value.items()}

    raw_scores = exact_score_map(raw_core_stats.get("ability_scores"), "core")
    current_scores = exact_score_map(core_stats.get("ability_scores"), "copied core")
    raw_modifiers = exact_score_map(raw_core_stats.get("ability_modifiers"), "core modifier")
    current_modifiers = exact_score_map(core_stats.get("ability_modifiers"), "copied core modifier")
    if current_scores != raw_scores or current_modifiers != raw_modifiers:
        raise invalid("The copied ability authority diverges from raw resource provenance.")
    if any(raw_modifiers[ability] != (raw_scores[ability] - 10) // 2 for ability in _CORE_SAVE_ABILITIES):
        raise invalid("The sealed ability scores and modifiers do not satisfy standard modifier math.")

    raw_timeline: list[dict[str, int]] = []
    for index, (raw_level, current_level) in enumerate(zip(raw_levels, current_levels), start=1):
        if not isinstance(raw_level, Mapping) or not isinstance(current_level, Mapping):
            raise invalid("The copied resource timeline contains a malformed level row.", details={"cl": index})
        raw_level_without_projection = {key: value for key, value in raw_level.items() if key not in {"resource", "hp", "allocations"}}
        current_level_without_projection = {key: value for key, value in current_level.items() if key not in {"resource", "hp", "allocations"}}
        if current_level_without_projection != raw_level_without_projection:
            raise invalid("The copied resource level diverges from raw modern provenance.", details={"cl": index})
        raw_timeline.append(exact_score_map(raw_level.get("ability_scores_after"), f"CL{index}"))
    if raw_timeline[-1] != raw_scores:
        raise invalid("The final resource ability timeline does not match sealed core scores.")

    # If the preceding ability projection is available, bind it to the same
    # raw ledger and Path evidence.  The raw score timeline is still checked
    # independently above; this prevents a caller from establishing resource
    # authority merely by supplying an arbitrary projection result.
    ability_details_path = root / _ABILITY_PROJECTION_DETAILS_RELATIVE
    ability_details: Mapping[str, Any] | None = None
    ability_details_sha256: str | None = None
    if ability_projection is not None or ability_details_path.exists():
        if ability_details_path.is_symlink() or not ability_details_path.is_file():
            raise invalid("The copied ability projection provenance is missing or unsafe.")
        ability_details_sha256 = sha256_file(ability_details_path)
        ability_details_value = _read_json(ability_details_path, code="FINAL_CHARACTER_RESOURCE_PROJECTION_INVALID")
        if not isinstance(ability_details_value, Mapping):
            raise invalid("The copied ability projection provenance is not a mapping.")
        ability_details = ability_details_value
        if (
            ability_details.get("schema_version") != "TianxiaFoundry.FinalCharacterAbilityProjectionProvenance.v1"
            or ability_details.get("source_ledger_sha256") != raw_provenance_sha256
            or ability_details.get("modern_provenance_sha256") != raw_provenance_sha256
            or ability_details.get("path_details_sha256") != path_details_sha256
            or ability_details.get("path_id") != path_id
            or not isinstance(ability_details.get("compiler_generation"), Mapping)
            or not isinstance(ability_details.get("source_ability_generation"), Mapping)
        ):
            raise invalid("The copied ability projection is not bound to the exact resource authority.")
        if ability_projection is not None:
            if (
                not isinstance(ability_projection, Mapping)
                or ability_projection.get("source_ledger_sha256") != raw_provenance_sha256
                or ability_projection.get("modern_provenance_sha256") != raw_provenance_sha256
                or ability_projection.get("path_details_sha256") != path_details_sha256
                or ability_projection.get("details_sha256") != ability_details_sha256
                or ability_projection.get("path_id") != path_id
                or ability_projection.get("compiler_generation") != ability_details.get("compiler_generation")
            ):
                raise invalid("The ability projection result is not bound to its authenticated details.")

    # The modern core fields are source-backed and must remain unchanged.
    primary_fields = ("primary_resource_name", "primary_resource_current", "primary_resource_max")
    if any(core_stats.get(field) != raw_core_stats.get(field) for field in primary_fields):
        raise invalid("The copied primary resource fields diverge from raw provenance.")
    if (
        raw_core_stats.get("primary_resource_name") != resource_name
        or type(raw_core_stats.get("primary_resource_current")) is not int
        or type(raw_core_stats.get("primary_resource_max")) is not int
        or raw_core_stats.get("primary_resource_current") < 0
        or raw_core_stats.get("primary_resource_max") < 1
        or raw_core_stats.get("primary_resource_current") > raw_core_stats.get("primary_resource_max")
    ):
        raise invalid("The copied primary Path resource values are missing, malformed, or out of bounds.")

    formula_id = f"ns1r.{path_id}.resource.maximum"

    def expected_base_for_level(level_cl: int, scores_after: Mapping[str, int]) -> int:
        modifier = (scores_after[key_ability] - 10) // 2
        expected = max(0, level_cl * modifier)
        if minimum_formula is not None:
            expected = max(expected, 2 * level_cl)
        return expected

    # The modern ledger has one source-shaped top-level resource row.  It is
    # authenticated independently of the per-level timeline before adding
    # the three fields required by the legacy compiler.  Any pre-existing
    # partial or conflicting legacy surface is rejected without mutation.
    raw_resources = raw_ledger.get("resources")
    current_resources = ledger.get("resources")
    if (
        not isinstance(raw_resources, list)
        or len(raw_resources) != 1
        or not isinstance(raw_resources[0], Mapping)
        or not isinstance(current_resources, list)
        or len(current_resources) != 1
        or not isinstance(current_resources[0], Mapping)
    ):
        raise invalid("The copied ledger must contain exactly one top-level resource row.")
    raw_resource_row = raw_resources[0]
    current_resource_row = current_resources[0]
    required_resource_fields = ("authority_components", "current", "formula_id", "max", "name", "resource_id")
    if any(field not in raw_resource_row for field in required_resource_fields) or any(
        field not in current_resource_row for field in required_resource_fields
    ):
        raise invalid("The copied top-level resource row is incomplete.")
    if (
        raw_resource_row.get("resource_id") != resource_id
        or raw_resource_row.get("name") != resource_name
        or raw_resource_row.get("formula_id") != formula_id
        or type(raw_resource_row.get("current")) is not int
        or type(raw_resource_row.get("max")) is not int
        or raw_resource_row.get("current") < 0
        or raw_resource_row.get("max") < 1
        or raw_resource_row.get("current") > raw_resource_row.get("max")
        or raw_resource_row.get("current") != raw_core_stats.get("primary_resource_current")
        or raw_resource_row.get("max") != raw_core_stats.get("primary_resource_max")
    ):
        raise invalid("The top-level Path resource row is not bound to authenticated source arithmetic.")
    authority_components = raw_resource_row.get("authority_components")
    if (
        not isinstance(authority_components, list)
        or len(authority_components) != 1
        or not isinstance(authority_components[0], Mapping)
    ):
        raise invalid("The top-level Path resource authority component is missing or ambiguous.")
    authority_component = authority_components[0]
    if (
        set(authority_component)
        != {"formula_id", "record_hash", "record_id", "role", "source_anchor", "value"}
        or authority_component.get("formula_id") != formula_id
        or not _is_hash(authority_component.get("record_hash"))
        or authority_component.get("record_id") != path_id
        or authority_component.get("role") != "path_base"
        or authority_component.get("source_anchor") != f"path:{path_id}"
        or authority_component.get("value") != expected_base_for_level(target_cl, raw_scores)
    ):
        raise invalid("The top-level Path authority component is not the fixed Path resource binding.")

    def modifier_units(formula: Any, *, label: str) -> int:
        terms = ((formula or {}).get("root") or {}).get("terms") if isinstance(formula, Mapping) else None
        if (
            not isinstance(terms, list)
            or len(terms) != 2
            or not isinstance(terms[0], Mapping)
            or terms[0].get("op") != "constant"
            or type(terms[0].get("value")) is not int
            or not isinstance(terms[1], Mapping)
            or terms[1].get("op") != "pb"
        ):
            raise invalid(f"The {label} resource modifier lacks a typed proficiency-bonus formula.")
        return terms[0]["value"]

    method_units = 0
    method_activation_cl = 1
    mechanics = method_details_projected.get("mechanics")
    if mechanics is not None:
        if (
            not isinstance(mechanics, Mapping)
            or mechanics.get("schema") != "TianxiaFoundry.MethodMechanicalAuthority.v1"
            or type(mechanics.get("activation_min_cl")) is not int
            or not 1 <= mechanics.get("activation_min_cl") <= target_cl
            or not isinstance(mechanics.get("resource_modifiers"), list)
        ):
            raise invalid("The Method mechanical resource authority is malformed.")
        method_activation_cl = mechanics["activation_min_cl"]
        seen_method_resources: set[str] = set()
        selected_method_resource_ids = {
            row.get("resource_id")
            for row in (method_details_projected.get("path_resource_profiles") or [])
            if isinstance(row, Mapping)
        }
        for modifier in mechanics["resource_modifiers"]:
            if not isinstance(modifier, Mapping) or not isinstance(modifier.get("resource_id"), str):
                raise invalid("The Method mechanical resource authority is incomplete.")
            modifier_resource_id = modifier["resource_id"]
            if modifier_resource_id in seen_method_resources:
                raise invalid("The Method mechanical resource authority duplicates a resource.")
            seen_method_resources.add(modifier_resource_id)
            if modifier_resource_id not in selected_method_resource_ids:
                raise invalid("The Method mechanical resource authority is not bound to selected Path resources.")
            if modifier_resource_id == resource_id:
                method_units = modifier_units(modifier.get("formula"), label="Method")

    foundation_id: str | None = None
    foundation_units = 0
    foundation_apply_cl: int | None = None
    if foundation_projection is not None:
        foundation_details_path = root / _FOUNDATION_PROJECTION_DETAILS_RELATIVE
        if foundation_details_path.is_symlink() or not foundation_details_path.is_file():
            raise invalid("The Foundation projection provenance is missing or unsafe.")
        foundation_details_sha256 = sha256_file(foundation_details_path)
        foundation_details = _read_json(foundation_details_path, code="FINAL_CHARACTER_RESOURCE_PROJECTION_INVALID")
        projected_foundation = foundation_projection.get("projected_foundation")
        if (
            not isinstance(foundation_details, Mapping)
            or foundation_details.get("schema_version") != "TianxiaFoundry.FinalCharacterFoundationProjectionProvenance.v1"
            or foundation_details.get("source_ledger_sha256") != raw_provenance_sha256
            or foundation_details.get("details_sha256", foundation_details_sha256) != foundation_details_sha256
            or not isinstance(projected_foundation, Mapping)
            or foundation_projection.get("source_ledger_sha256") != raw_provenance_sha256
            or foundation_projection.get("details_sha256") != foundation_details_sha256
            or foundation_projection.get("projected_foundation") != foundation_details.get("projected_foundation")
        ):
            raise invalid("The resource projection is not bound to the authenticated Foundation projection.")
        foundation_id = projected_foundation.get("foundation_id")
        if not isinstance(foundation_id, str) or not foundation_id.strip():
            raise invalid("The authenticated Foundation projection has no stable identity.")
        modifiers = projected_foundation.get("primary_resource_modifiers")
        if not isinstance(modifiers, list):
            raise invalid("The authenticated Foundation projection has no typed resource modifier list.")
        matching_foundation_modifiers = [
            modifier for modifier in modifiers
            if isinstance(modifier, Mapping) and modifier.get("resource_id") == resource_id
        ]
        if len(matching_foundation_modifiers) > 1:
            raise invalid("The authenticated Foundation projection duplicates the primary resource modifier.")
        if matching_foundation_modifiers:
            modifier = matching_foundation_modifiers[0]
            if type(modifier.get("applies_from_cl")) is not int or not 1 <= modifier["applies_from_cl"] <= target_cl:
                raise invalid("The authenticated Foundation resource modifier has no valid activation level.")
            foundation_units = modifier_units(modifier.get("formula"), label="Foundation")
            foundation_apply_cl = modifier["applies_from_cl"]

    legacy_resource_fields = {"formula", "recovery", "source_grant_ids"}
    expected_legacy_resource = {
        "formula": maximum_formula,
        "recovery": recovery,
        "source_grant_ids": [method_id] + ([foundation_id] if foundation_id and foundation_units else []),
    }
    for label, row in (("raw", raw_resource_row), ("copied", current_resource_row)):
        present = set(row).intersection(legacy_resource_fields)
        if present and present != legacy_resource_fields:
            raise invalid(
                "A pre-existing top-level resource compiler surface is partial.",
                details={"label": label, "fields": sorted(present)},
            )
        if present == legacy_resource_fields and any(
            row.get(field) != value for field, value in expected_legacy_resource.items()
        ):
            raise invalid(
                "A pre-existing top-level resource compiler surface conflicts with fixed authority.",
                details={"label": label},
            )
    raw_resource_binding = dict(raw_resource_row)
    current_resource_binding = dict(current_resource_row)
    for value in (raw_resource_binding, current_resource_binding):
        for field in legacy_resource_fields:
            value.pop(field, None)
    if current_resource_binding != raw_resource_binding:
        raise invalid("The copied top-level resource row diverges from raw modern provenance.")
    projected_resource_row = deepcopy(dict(current_resource_row))
    projected_resource_row.update(deepcopy(expected_legacy_resource))

    source_resource_keys = {"current_after_event", "formula_id", "maximum", "resource_id"}
    compiler_resource_keys = {"name", "base_after_level", "method_delta", "foundation_delta", "item_delta", "max_after_level"}
    allowed_resource_keys = source_resource_keys | compiler_resource_keys
    source_rows: list[dict[str, Any]] = []
    compiler_rows: list[dict[str, Any]] = []
    projected_levels = deepcopy(current_levels)
    for index, (raw_level, current_level, scores_after) in enumerate(zip(raw_levels, current_levels, raw_timeline), start=1):
        raw_resource = raw_level.get("resource")
        current_resource = current_level.get("resource")
        if not isinstance(raw_resource, Mapping) or not isinstance(current_resource, Mapping):
            raise invalid("The copied resource row is missing or malformed.", details={"cl": index})
        if (
            any(key not in allowed_resource_keys for key in raw_resource)
            or any(key not in allowed_resource_keys for key in current_resource)
            or not source_resource_keys.issubset(raw_resource)
            or not source_resource_keys.issubset(current_resource)
        ):
            raise invalid("The copied resource row contains unsupported or incomplete fields.", details={"cl": index})
        raw_resource_dict = dict(raw_resource)
        current_resource_dict = dict(current_resource)
        if any(current_resource_dict.get(key) != raw_resource_dict.get(key) for key in source_resource_keys):
            raise invalid("The copied resource source fields diverge from raw provenance.", details={"cl": index})
        expected_base = expected_base_for_level(index, scores_after)
        method_delta = method_units * (2 + (index - 1) // 4) if index >= method_activation_cl else 0
        foundation_delta = (
            foundation_units * (2 + (index - 1) // 4)
            if foundation_apply_cl is not None and index >= foundation_apply_cl
            else 0
        )
        expected_compiler = {
            "name": resource_name,
            "base_after_level": expected_base,
            "method_delta": method_delta,
            "foundation_delta": foundation_delta,
            "item_delta": 0,
            "max_after_level": expected_base + method_delta + foundation_delta,
        }
        if (
            raw_resource_dict.get("resource_id") != resource_id
            or raw_resource_dict.get("formula_id") != formula_id
            or type(raw_resource_dict.get("maximum")) is not int
            or type(raw_resource_dict.get("current_after_event")) is not int
            or raw_resource_dict.get("maximum") < 0
            or raw_resource_dict.get("current_after_event") < 0
            or raw_resource_dict.get("current_after_event") > raw_resource_dict.get("maximum")
            or raw_resource_dict.get("current_after_event") != raw_core_stats.get("primary_resource_current")
        ):
            raise invalid("The copied source Path resource row is not the exact sealed formula/current binding.", details={"cl": index})
        if raw_resource_dict.get("maximum") != expected_compiler["max_after_level"]:
            raise invalid(
                "The copied source maximum diverges from authenticated resource mechanics.",
                details={"cl": index, "actual": raw_resource_dict.get("maximum"), "expected": expected_compiler["max_after_level"]},
            )
        for source_map, label in ((raw_resource_dict, "raw"), (current_resource_dict, "copied")):
            compiler_presence = [key in source_map for key in compiler_resource_keys]
            if any(compiler_presence) and not all(compiler_presence):
                raise invalid("The resource compiler component map is partial.", details={"cl": index, "map": label})
            if all(compiler_presence) and (
                source_map.get("name") != expected_compiler["name"]
                or any(type(source_map.get(key)) is not int for key in compiler_resource_keys - {"name"})
                or any(source_map.get(key) != value for key, value in expected_compiler.items())
            ):
                raise invalid("The resource compiler component map conflicts with source arithmetic.", details={"cl": index, "map": label})
        projected_resource = deepcopy(current_resource_dict)
        projected_resource.update(expected_compiler)
        projected_levels[index - 1]["resource"] = projected_resource
        source_rows.append({"cl": index, "resource": deepcopy(raw_resource_dict)})
        compiler_rows.append(deepcopy(projected_resource))

    if raw_core_stats.get("primary_resource_max") != compiler_rows[-1]["max_after_level"]:
        raise invalid("The primary Path maximum does not match the final resource level.")

    projected_ledger = deepcopy(dict(ledger))
    projected_resources = deepcopy(list(current_resources))
    projected_resources[0] = projected_resource_row
    projected_ledger["resources"] = projected_resources
    projected_advancement = deepcopy(dict(current_advancement))
    projected_advancement["levels"] = projected_levels
    projected_ledger["advancement"] = projected_advancement
    provenance = {
        "schema_version": "TianxiaFoundry.FinalCharacterResourceProjectionProvenance.v1",
        "source_ledger_path": "Build/Character_Master_Ledger.json",
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_provenance_sha256,
        "path_details_path": _PATH_PROJECTION_DETAILS_RELATIVE,
        "path_details_sha256": path_details_sha256,
        "ability_details_path": _ABILITY_PROJECTION_DETAILS_RELATIVE if ability_details is not None else None,
        "ability_details_sha256": ability_details_sha256,
        "path_id": path_id,
        "path_name": path_name,
        "key_ability": key_ability,
        "effective_cl": target_cl,
        "resource_id": resource_id,
        "resource_name": resource_name,
        "formula_id": formula_id,
        "maximum_formula": maximum_formula,
        "minimum_formula": minimum_formula,
        "method_details_path": _METHOD_PROJECTION_DETAILS_RELATIVE,
        "method_details_sha256": method_details_sha256,
        "method_id": method_id,
        "method_name": method_name,
        "path_ids": [row["path_id"] for row in path_rows],
        "formula": expected_legacy_resource["formula"],
        "recovery": expected_legacy_resource["recovery"],
        "source_grant_ids": deepcopy(expected_legacy_resource["source_grant_ids"]),
        "compiler_resource": deepcopy(projected_resource_row),
        "primary_resource_current": raw_core_stats["primary_resource_current"],
        "primary_resource_max": raw_core_stats["primary_resource_max"],
        "ability_scores_timeline": deepcopy(raw_timeline),
        "source_resource_rows": source_rows,
        "compiler_levels": deepcopy(compiler_rows),
    }
    _write_json(details_path, provenance)
    _write_json(ledger_path, projected_ledger)
    reread = _read_json(ledger_path, code="FINAL_CHARACTER_RESOURCE_PROJECTION_INVALID")
    if reread != projected_ledger or raw_provenance_path.read_bytes() != raw_provenance_bytes:
        raise invalid("The compiler resource projection could not be read back exactly or altered raw provenance.")
    return {
        "schema_version": provenance["schema_version"],
        "source_ledger_path": provenance["source_ledger_path"],
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_provenance_sha256,
        "path_details_path": _PATH_PROJECTION_DETAILS_RELATIVE,
        "path_details_sha256": path_details_sha256,
        "ability_details_path": provenance["ability_details_path"],
        "ability_details_sha256": ability_details_sha256,
        "details_path": _RESOURCE_PROJECTION_DETAILS_RELATIVE,
        "details_sha256": sha256_file(details_path),
        "method_details_path": _METHOD_PROJECTION_DETAILS_RELATIVE,
        "method_details_sha256": method_details_sha256,
        "method_id": method_id,
        "method_name": method_name,
        "path_id": path_id,
        "path_ids": [row["path_id"] for row in path_rows],
        "resource_id": resource_id,
        "resource_name": resource_name,
        "formula": expected_legacy_resource["formula"],
        "recovery": expected_legacy_resource["recovery"],
        "source_grant_ids": deepcopy(expected_legacy_resource["source_grant_ids"]),
        "compiler_resource": deepcopy(projected_resource_row),
        "primary_resource_current": raw_core_stats["primary_resource_current"],
        "primary_resource_max": raw_core_stats["primary_resource_max"],
        "compiler_levels": deepcopy(compiler_rows),
    }


def _project_modern_realm_for_compiler(
    workspace: Path,
    *,
    path_projection: Mapping[str, Any],
    immortal_translation: Mapping[str, Any],
    hp_projection: Mapping[str, Any] | None = None,
    ability_projection: Mapping[str, Any] | None = None,
    resource_projection: Mapping[str, Any] | None = None,
    grant_projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project the compiler's realm bands onto a copied modern ledger.

    The modern authoring ledger historically records every advancement row as
    ``Mortal``.  That representation is retained byte-for-byte in the Path
    projection's raw provenance, but the pinned compiler requires the realm
    corresponding to each CL.  This boundary upgrades only an authenticated,
    gap-free progression whose Path event packets and translated Immortal Art
    acquisitions prove the transition.  No realm is inferred from display
    prose, and no source or secondary ledger is rewritten.
    """

    def invalid(message: str, *, details: Any = None) -> FoundryError:
        return _error("FINAL_CHARACTER_REALM_PROJECTION_INVALID", message, details=details)

    def realm_for_cl(cl: int) -> str | None:
        for lower, upper, realm in _COMPILER_REALM_BANDS:
            if lower <= cl <= upper:
                return realm
        return None

    root = Path(workspace)
    ledger_path = root / "Build/Character_Master_Ledger.json"
    raw_provenance_path = root / _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    path_details_path = root / _PATH_PROJECTION_DETAILS_RELATIVE
    details_path = root / _REALM_PROJECTION_DETAILS_RELATIVE
    for path in (ledger_path, raw_provenance_path, path_details_path):
        if path.is_symlink() or not path.is_file():
            raise invalid("The copied Path projection provenance is missing or unsafe.", details={"path": str(path)})
    if details_path.exists():
        raise invalid("The copied workspace already contains realm projection provenance.")

    try:
        raw_bytes = raw_provenance_path.read_bytes()
        raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        raw_ledger = _read_json(raw_provenance_path, code="FINAL_CHARACTER_REALM_PROJECTION_INVALID")
        path_details = _read_json(path_details_path, code="FINAL_CHARACTER_REALM_PROJECTION_INVALID")
        ledger = _read_json(ledger_path, code="FINAL_CHARACTER_REALM_PROJECTION_INVALID")
    except (OSError, FoundryError) as exc:
        if isinstance(exc, FoundryError):
            raise invalid("The copied Path projection provenance could not be read.", details={"cause": exc.code}) from exc
        raise invalid("The copied Path projection provenance could not be read.") from exc
    if not isinstance(raw_ledger, Mapping) or not isinstance(path_details, Mapping) or not isinstance(ledger, Mapping):
        raise invalid("The copied realm projection inputs must be mappings.")
    if (
        not isinstance(path_projection, Mapping)
        or path_projection.get("source_ledger_sha256") != raw_sha256
        or path_projection.get("modern_provenance_sha256") != raw_sha256
        or path_details.get("source_ledger_sha256") != raw_sha256
        or not _is_hash(path_projection.get("details_sha256"))
        or sha256_file(path_details_path) != path_projection.get("details_sha256")
    ):
        raise invalid("The realm projection is not bound to the freshly authenticated Path projection.")

    raw_character = raw_ledger.get("character")
    character = ledger.get("character")
    if not isinstance(raw_character, Mapping) or not isinstance(character, Mapping):
        raise invalid("The copied ledger has no character identity for realm projection.")
    identity_fields = ("path_id", "path", "key_ability", "cl")
    if any(character.get(field) != raw_character.get(field) for field in identity_fields):
        raise invalid("The copied character identity diverges from its raw modern provenance.")
    path_id = raw_character.get("path_id")
    path_name = raw_character.get("path")
    target_cl = raw_character.get("cl")
    expected_target_realm = realm_for_cl(target_cl) if type(target_cl) is int else None
    if (
        not isinstance(path_id, str)
        or not path_id.strip()
        or not isinstance(path_name, str)
        or not path_name.strip()
        or type(target_cl) is not int
        or expected_target_realm is None
        or target_cl < 15
    ):
        raise invalid(
            "The copied character CL is outside the supported realm-projection authority.",
            details={"path_id": path_id, "cl": target_cl},
        )
    proof = _PACKET_PATH_PROOFS.get(path_id)
    if proof is None or path_projection.get("path_id") != path_id:
        raise invalid("The copied active Path is not bound to one fixed realm authority.", details={"path_id": path_id})

    # The Path helper has already proven this identity, but repeat the small
    # binding here so the realm upgrade cannot be called with an unrelated
    # caller-supplied projection result.
    raw_path_rows, raw_path_packet_ids = _selected_path_rows_for_compiler_consumer(
        raw_ledger=raw_ledger,
        ledger=ledger,
        path_projection=path_projection,
        path_details=path_details,
        primary_path_id=path_id,
        primary_path_name=path_name,
        character_cl=target_cl,
        invalid=invalid,
    )
    raw_path_row = raw_path_rows[0]

    path_index = _bridge_fixed_json(proof["index_path"], proof["index_sha256"])
    path_master = _bridge_fixed_json(_PACKET_PATH_MASTER_PATH, _PACKET_PATH_MASTER_SHA256)
    if not isinstance(path_index, Mapping) or not isinstance(path_master, Mapping):
        raise invalid("The fixed active Path authority is unavailable or unsafe.", details={"path_id": path_id})
    master_rows = path_master.get("paths")
    master_matches = [
        row for row in master_rows
        if isinstance(row, Mapping) and row.get("canonical_id") == path_id
    ] if isinstance(master_rows, list) else []
    index_source = path_index.get("source")
    master_source = master_matches[0].get("source") if len(master_matches) == 1 else None
    if (
        len(master_matches) != 1
        or path_index.get("canonical_id") != path_id
        or path_index.get("display_name") != path_name
        or path_index.get("publication_status") != "current_canonical_player_path"
        or master_matches[0].get("display_name") != path_name
        or master_matches[0].get("index_file") != proof["index_file"]
        or not isinstance(index_source, Mapping)
        or not isinstance(master_source, Mapping)
        or index_source.get("corpus_path") != proof["corpus_path"]
        or index_source.get("sha256") != proof["corpus_sha256"]
        or master_source.get("corpus_path") != proof["corpus_path"]
        or master_source.get("sha256") != proof["corpus_sha256"]
    ):
        raise invalid("The active Path realm authority diverges from the fixed path/index proofs.", details={"path_id": path_id})
    fixed_feature_rows: dict[str, Mapping[str, Any]] = {}
    feature_proofs: dict[str, Mapping[str, Any]] = {}
    for selected_path_row in raw_path_rows:
        selected_path_id = selected_path_row["path_id"]
        selected_proof = _PACKET_PATH_PROOFS.get(selected_path_id)
        selected_index = path_index if selected_path_id == path_id else (
            _bridge_fixed_json(selected_proof["index_path"], selected_proof["index_sha256"])
            if isinstance(selected_proof, Mapping) else None
        )
        selected_features = selected_index.get("features") if isinstance(selected_index, Mapping) else None
        if not isinstance(selected_proof, Mapping) or not isinstance(selected_features, list):
            raise invalid("A selected Path has no fixed feature authority.", details={"path_id": selected_path_id})
        for row in selected_features:
            feature_id = row.get("canonical_id") if isinstance(row, Mapping) else None
            if (
                not isinstance(row, Mapping)
                or not isinstance(feature_id, str)
                or not feature_id
                or not feature_id.startswith(selected_path_id + ".feature.")
                or feature_id in fixed_feature_rows
            ):
                raise invalid("The selected Path feature authority is malformed or duplicated.", details={"path_id": selected_path_id})
            fixed_feature_rows[feature_id] = row
            feature_proofs[feature_id] = {"path_id": selected_path_id, **selected_proof}

    resource_details: Mapping[str, Any] | None = None
    resource_details_sha256: str | None = None
    resource_compiler_levels: list[Mapping[str, Any]] | None = None
    if resource_projection is not None:
        resource_details_path = root / _RESOURCE_PROJECTION_DETAILS_RELATIVE
        if resource_details_path.is_symlink() or not resource_details_path.is_file():
            raise invalid("The copied resource projection provenance is missing or unsafe.")
        resource_details_sha256 = sha256_file(resource_details_path)
        resource_details_value = _read_json(resource_details_path, code="FINAL_CHARACTER_REALM_PROJECTION_INVALID")
        if not isinstance(resource_details_value, Mapping):
            raise invalid("The copied resource projection provenance is not a mapping.")
        resource_details = resource_details_value
        resource_compiler_levels_value = resource_projection.get("compiler_levels")
        if not isinstance(resource_compiler_levels_value, list):
            raise invalid("The resource projection has no compiler level map.")
        resource_compiler_levels = [row for row in resource_compiler_levels_value if isinstance(row, Mapping)]
        projected_resource_id = resource_projection.get("resource_id")
        projected_resource_name = resource_projection.get("resource_name")
        projected_resource_path_ids = resource_projection.get("path_ids")
        if not isinstance(projected_resource_path_ids, list):
            projected_resource_path_ids = [resource_projection.get("path_id")]
        detail_resource_path_ids = resource_details.get("path_ids")
        if not isinstance(detail_resource_path_ids, list):
            detail_resource_path_ids = [resource_details.get("path_id")]
        expected_path_ids = path_projection.get("path_ids") or [path_projection.get("path_id")]
        if (
            len(resource_compiler_levels) != len(resource_compiler_levels_value)
            or resource_details.get("schema_version") != "TianxiaFoundry.FinalCharacterResourceProjectionProvenance.v1"
            or resource_details.get("source_ledger_sha256") != raw_sha256
            or resource_details.get("modern_provenance_sha256") != raw_sha256
            or resource_details.get("path_details_sha256") != path_projection.get("details_sha256")
            or resource_details.get("path_id") != path_projection.get("path_id")
            or not isinstance(resource_details.get("resource_id"), str)
            or resource_details.get("resource_id") != projected_resource_id
            or not isinstance(resource_details.get("resource_name"), str)
            or resource_details.get("resource_name") != projected_resource_name
            or detail_resource_path_ids != expected_path_ids
            or resource_projection.get("source_ledger_sha256") != raw_sha256
            or resource_projection.get("modern_provenance_sha256") != raw_sha256
            or resource_projection.get("path_details_sha256") != path_projection.get("details_sha256")
            or resource_projection.get("details_sha256") != resource_details_sha256
            or resource_projection.get("path_id") != path_projection.get("path_id")
            or projected_resource_path_ids != expected_path_ids
        ):
            raise invalid("The copied resource projection is not bound to the authenticated Path and raw ledger.")

    grant_allocations_by_cl: dict[str, list[dict[str, Any]]] = {}
    grant_details: Mapping[str, Any] | None = None
    grant_details_sha256: str | None = None
    if grant_projection is not None:
        if not isinstance(grant_projection, Mapping):
            raise invalid("The Background/Origin allocation projection is not a mapping.")
        grant_details_path = root / _GRANT_PROJECTION_DETAILS_RELATIVE
        if grant_details_path.is_symlink() or not grant_details_path.is_file():
            raise invalid("The copied Background/Origin allocation projection provenance is missing or unsafe.")
        grant_details_sha256 = sha256_file(grant_details_path)
        grant_details_value = _read_json(grant_details_path, code="FINAL_CHARACTER_REALM_PROJECTION_INVALID")
        if not isinstance(grant_details_value, Mapping):
            raise invalid("The Background/Origin allocation projection provenance is not a mapping.")
        grant_details = grant_details_value
        supplied_grants = grant_projection.get("background_origin_allocations_by_cl")
        if (
            grant_details.get("schema_version") != "TianxiaFoundry.FinalCharacterGrantAllocationProjectionProvenance.v1"
            or grant_details.get("source_ledger_sha256") != raw_sha256
            or grant_details.get("modern_provenance_sha256") != raw_sha256
            or grant_projection.get("source_ledger_sha256") != raw_sha256
            or grant_projection.get("modern_provenance_sha256") != raw_sha256
            or grant_projection.get("details_path") != _GRANT_PROJECTION_DETAILS_RELATIVE
            or grant_projection.get("details_sha256") != grant_details_sha256
            or not isinstance(supplied_grants, Mapping)
            or grant_details.get("background_origin_allocations_by_cl") != supplied_grants
        ):
            raise invalid("The copied Background/Origin allocation projection is not bound to raw provenance.")
        if set(supplied_grants) != {"1"}:
            raise invalid("The Background/Origin allocation projection contains unsupported CL rows.")
        for key, rows in supplied_grants.items():
            if key != "1" or not isinstance(rows, list) or len(rows) != 2 or any(not isinstance(row, Mapping) for row in rows):
                raise invalid("The Background/Origin allocation projection has an incomplete CL1 row set.")
            expected_channels = (("background", "background"), ("origin", "origin_insight"))
            normalized_rows: list[dict[str, Any]] = []
            for row, (channel, grant_type) in zip(rows, expected_channels):
                if (
                    row.get("channel") != channel
                    or row.get("grant_type") != grant_type
                    or not isinstance(row.get("allocation_id"), str)
                    or not row.get("allocation_id")
                    or not isinstance(row.get("grant_id"), str)
                    or not row.get("grant_id")
                    or not isinstance(row.get("name"), str)
                    or not row.get("name")
                    or row.get("slot_cost") != 0
                    or not isinstance(row.get("source_packet_ids"), list)
                    or len(row.get("source_packet_ids")) != 1
                    or not isinstance(row.get("source_packet_ids")[0], str)
                    or not row.get("source_packet_ids")[0]
                ):
                    raise invalid("The Background/Origin allocation projection row is malformed.")
                normalized_rows.append(dict(row))
            if normalized_rows[0]["allocation_id"] == normalized_rows[1]["allocation_id"] or normalized_rows[0]["grant_id"] == normalized_rows[1]["grant_id"]:
                raise invalid("The Background/Origin allocation projection contains colliding identities.")
            grant_allocations_by_cl[key] = normalized_rows

    raw_advancement = raw_ledger.get("advancement")
    current_advancement = ledger.get("advancement")
    raw_levels = raw_advancement.get("levels") if isinstance(raw_advancement, Mapping) else None
    current_levels = current_advancement.get("levels") if isinstance(current_advancement, Mapping) else None
    if not isinstance(raw_levels, list) or len(raw_levels) != target_cl or not isinstance(current_levels, list) or len(current_levels) != len(raw_levels):
        raise invalid("The copied advancement progression is not an exact CL1-to-current sequence.")
    if [row.get("cl") if isinstance(row, Mapping) else None for row in raw_levels] != list(range(1, target_cl + 1)):
        raise invalid("The copied advancement progression has a gap or out-of-order CL row.")

    # Translating the controller-built Immortal Arts appends exactly one
    # zero-cost allocation at each Art's creation CL (RAW-183: at most one
    # per CL).  Bind those additive rows to the translation rather than
    # treating them as source-ledger mutations.
    immortal_allocations = immortal_translation.get("allocations_by_cl") if isinstance(immortal_translation, Mapping) else None
    if not isinstance(immortal_allocations, Mapping) or any(
        not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping)
        for rows in immortal_allocations.values()
    ):
        raise invalid("The copied progression has no structured Immortal Art allocation proof.")

    def immortal_rows_at(cl_value: Any) -> list[dict[str, Any]]:
        return [dict(row) for row in immortal_allocations.get(str(cl_value), [])]

    def source_level_binding(
        row: Mapping[str, Any],
        *,
        include_hp: bool = True,
        include_resource: bool = True,
    ) -> dict[str, Any]:
        # checkpoint hashes are recomputed later in the materialization flow;
        # all other modern event identity/mechanics remain source-bound.  The
        # optional allocations field is checked separately below because the
        # reviewed overlay may append exactly its own acquisition record.
        return {
            key: value
            for key, value in row.items()
            if key not in {"realm", "state_after_hash", "allocations"}
            and (include_hp or key != "hp")
            and (include_resource or key != "resource")
        }

    for index, (raw_level, current_level) in enumerate(zip(raw_levels, current_levels), start=1):
        if not isinstance(raw_level, Mapping) or not isinstance(current_level, Mapping):
            raise invalid("The copied advancement levels contain a malformed row.", details={"index": index})
        if source_level_binding(
            raw_level,
            include_hp=hp_projection is None,
            include_resource=resource_projection is None,
        ) != source_level_binding(
            current_level,
            include_hp=hp_projection is None,
            include_resource=resource_projection is None,
        ):
            raise invalid("The copied advancement level diverges from raw modern provenance.", details={"cl": raw_level.get("cl")})
        cl = raw_level.get("cl")
        if hp_projection is not None:
            if (
                not isinstance(raw_level.get("hp"), Mapping)
                or not isinstance(current_level.get("hp"), Mapping)
                or any(current_level["hp"].get(key) != value for key, value in raw_level["hp"].items())
            ):
                raise invalid("The copied HP source row diverges from raw modern provenance.", details={"cl": raw_level.get("cl")})
            expected_hp_rows = hp_projection.get("compiler_levels")
            cl = raw_level.get("cl")
            expected_hp = expected_hp_rows[cl - 1] if isinstance(expected_hp_rows, list) and type(cl) is int and 1 <= cl <= len(expected_hp_rows) else None
            if not isinstance(expected_hp, Mapping):
                raise invalid("The copied HP projection has no matching compiler level.", details={"cl": cl})
            current_hp = current_level["hp"]
            if any(
                current_hp.get(key) != expected_hp.get(key)
                for key in ("base_gain", "constitution_delta", "other_delta")
            ):
                raise invalid("The copied HP compiler row diverges from its authenticated projection.", details={"cl": cl})
            expected_refs = expected_hp.get("source_packet_ids", _MISSING)
            current_refs = current_hp.get("source_packet_ids", _MISSING)
            if expected_refs is not _MISSING and current_refs != expected_refs:
                raise invalid("The copied HP source packet binding diverges from its authenticated projection.", details={"cl": cl})
            if expected_refs is _MISSING and current_refs is not _MISSING and current_refs != []:
                raise invalid("The copied HP row contains an unbound source packet reference.", details={"cl": cl})
            allowed_hp_keys = set(raw_level["hp"]) | {"base_gain", "constitution_delta", "other_delta", "source_packet_ids"}
            if any(key not in allowed_hp_keys for key in current_hp):
                raise invalid("The copied HP row contains an unsupported compiler field.", details={"cl": cl})
        if resource_projection is not None:
            resource = raw_level.get("resource")
            current_resource = current_level.get("resource")
            expected_resource = resource_compiler_levels[cl - 1] if isinstance(cl, int) and 1 <= cl <= len(resource_compiler_levels or []) else None
            if (
                not isinstance(resource, Mapping)
                or not isinstance(current_resource, Mapping)
                or not isinstance(expected_resource, Mapping)
                or dict(current_resource) != dict(expected_resource)
                or any(current_resource.get(key) != resource.get(key) for key in ("current_after_event", "formula_id", "maximum", "resource_id"))
            ):
                raise invalid("The copied resource compiler row diverges from its authenticated projection.", details={"cl": cl})
        raw_allocations = raw_level.get("allocations", _MISSING)
        current_allocations = current_level.get("allocations", _MISSING)
        if ability_projection is None:
            # Preserve the direct realm helper's historical contract when no
            # compiler-only ability projection is in play.  The materializer
            # path below supplies the stricter exact additive allocation set.
            if raw_allocations is _MISSING:
                if current_allocations is not _MISSING and current_allocations != immortal_rows_at(cl):
                    raise invalid(
                        "The copied advancement allocation is not the exact translated Immortal Art acquisition.",
                        details={"cl": cl},
                    )
            elif current_allocations != [*raw_allocations, *immortal_rows_at(cl)]:
                raise invalid("The copied advancement allocation diverges from raw modern provenance.", details={"cl": cl})
        else:
            def allocation_rows(value: Any, *, label: str) -> list[dict[str, Any]]:
                if value is _MISSING or value is None:
                    return []
                if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
                    raise invalid("The copied advancement allocation list is malformed.", details={"cl": cl, "label": label})
                return [dict(item) for item in value]

            raw_rows = allocation_rows(raw_allocations, label="raw")
            current_rows = allocation_rows(current_allocations, label="current")
            expected_rows = deepcopy(raw_rows)
            additions = ability_projection.get("allocations_by_cl") if isinstance(ability_projection, Mapping) else None
            if not isinstance(additions, Mapping):
                raise invalid("The ability projection has no exact allocation map.", details={"cl": cl})
            additional_rows = additions.get(str(cl), [])
            if not isinstance(additional_rows, list) or any(not isinstance(item, Mapping) for item in additional_rows):
                raise invalid("The ability projection allocation map is malformed.", details={"cl": cl})
            expected_rows.extend(deepcopy([dict(item) for item in additional_rows]))
            if grant_projection is not None:
                grant_rows = grant_allocations_by_cl.get(str(cl), [])
                if not isinstance(grant_rows, list) or any(not isinstance(item, Mapping) for item in grant_rows):
                    raise invalid("The Background/Origin allocation projection is malformed.", details={"cl": cl})
                expected_rows.extend(deepcopy([dict(item) for item in grant_rows]))
            expected_rows.extend(immortal_rows_at(cl))
            if current_rows != expected_rows:
                raise invalid(
                    "The copied advancement allocation is not the exact projected ASI/Immortal set.",
                    details={"cl": cl},
                )
        expected_realm = realm_for_cl(cl) if type(cl) is int else None
        raw_realm = raw_level.get("realm")
        current_realm = current_level.get("realm")
        if expected_realm is None or raw_realm not in {"Mortal", expected_realm} or current_realm not in {"Mortal", expected_realm}:
            raise invalid("The copied advancement realm representation is malformed or forged.", details={"cl": cl, "raw": raw_realm, "current": current_realm})
        if type(raw_level.get("cl")) is not int or not isinstance(raw_level.get("event_id"), str) or not raw_level.get("event_id") or not isinstance(raw_level.get("feature_record_id"), str) or not raw_level.get("feature_record_id"):
            raise invalid("The copied advancement event identity is incomplete.", details={"cl": cl})

    # Optional secondary projections are read-only corroboration when present;
    # the raw master ledger and source packets remain the primary evidence.
    for relative in ("Build/Leveling_Ledger.json", "Command_2/Canonical_Advancement_Ledger.json"):
        secondary_path = root / relative
        if secondary_path.exists():
            if secondary_path.is_symlink() or not secondary_path.is_file():
                raise invalid("A copied advancement corroboration file is unsafe.", details={"path": relative})
            secondary = _read_json(secondary_path, code="FINAL_CHARACTER_REALM_PROJECTION_INVALID")
            secondary_levels = secondary.get("levels") if isinstance(secondary, Mapping) else None
            if not isinstance(secondary_levels, list) or len(secondary_levels) != len(raw_levels):
                raise invalid("A copied advancement corroboration file has an incomplete level sequence.", details={"path": relative})
            if any(
                source_level_binding(a, include_hp=hp_projection is None, include_resource=resource_projection is None)
                != source_level_binding(b, include_hp=hp_projection is None, include_resource=resource_projection is None)
                for a, b in zip(raw_levels, secondary_levels)
                if isinstance(a, Mapping) and isinstance(b, Mapping)
            ):
                raise invalid("A copied advancement corroboration file diverges from raw level events.", details={"path": relative})

    registry_path = root / "Command_2/Rules_Selection_Packets.json"
    if registry_path.is_symlink() or not registry_path.is_file():
        raise invalid("The copied source packet registry is missing or unsafe.")
    registry = _read_json(registry_path, code="FINAL_CHARACTER_REALM_PROJECTION_INVALID")
    packets = registry.get("packets") if isinstance(registry, Mapping) else None
    if not isinstance(packets, list):
        raise invalid("The copied source packet registry has no packet list.")
    packet_by_id: dict[str, Mapping[str, Any]] = {}
    for row in packets:
        if not isinstance(row, Mapping) or not isinstance(row.get("packet_id"), str) or not row.get("packet_id") or row["packet_id"] in packet_by_id:
            raise invalid("The copied source packet registry has malformed or duplicate packet IDs.")
        packet_by_id[row["packet_id"]] = row

    raw_features = raw_ledger.get("features")
    if not isinstance(raw_features, list):
        raise invalid("The raw modern ledger has no feature event list.")
    feature_events: dict[tuple[str, int], Mapping[str, Any]] = {}
    for row in raw_features:
        if not isinstance(row, Mapping) or row.get("category") != "path_feature":
            continue
        feature_id = row.get("feature_id")
        gained_at_cl = row.get("gained_at_cl")
        key = (feature_id, gained_at_cl)
        if type(gained_at_cl) is not int or not isinstance(feature_id, str) or not feature_id or key in feature_events:
            raise invalid("The raw Path feature event identity is malformed or duplicated.", details={"feature_id": feature_id, "gained_at_cl": gained_at_cl})
        source_packet_ids = row.get("source_packet_ids")
        if not isinstance(source_packet_ids, list) or len(source_packet_ids) != 1 or not isinstance(source_packet_ids[0], str) or not source_packet_ids[0]:
            raise invalid("A raw Path feature event lacks one exact source packet.", details={"feature_id": feature_id, "gained_at_cl": gained_at_cl})
        feature_events[key] = row

    level_event_ids: list[str] = []
    level_packet_ids: list[str] = []
    for raw_level in raw_levels:
        feature_id = raw_level["feature_record_id"]
        cl = raw_level["cl"]
        feature_row = feature_events.get((feature_id, cl))
        fixed_feature = fixed_feature_rows.get(feature_id)
        feature_proof = feature_proofs.get(feature_id)
        if (
            feature_row is None
            or not isinstance(fixed_feature, Mapping)
            or not isinstance(feature_proof, Mapping)
            or fixed_feature.get("display_name") != feature_row.get("name")
            or not isinstance(fixed_feature.get("granted_at_cl"), list)
            or cl not in fixed_feature["granted_at_cl"]
        ):
            raise invalid("A gap-free level event is not bound to the fixed active Path feature authority.", details={"cl": cl, "feature_id": feature_id})
        packet_id = feature_row["source_packet_ids"][0]
        packet = packet_by_id.get(packet_id)
        evidence = packet.get("source_evidence") if isinstance(packet, Mapping) else None
        evidence_row = evidence[0] if isinstance(evidence, list) and len(evidence) == 1 and isinstance(evidence[0], Mapping) else None
        if (
            packet is None
            or packet.get("advancement_kind") != "level_advance"
            or packet.get("record_id") != feature_id
            or packet.get("display_name") != feature_row.get("name")
            or type(packet.get("target_cl")) is not int
            or packet.get("target_cl") != cl
            or packet.get("event_id") != raw_level.get("event_id")
            or evidence_row is None
            or evidence_row.get("source_path") != feature_proof["index_path"]
            or evidence_row.get("source_hash") != feature_proof["index_sha256"]
            or evidence_row.get("source_anchor") != f"path-feature:{feature_proof.get('path_id', path_id)}:{feature_id}"
        ):
            raise invalid("A Path advancement event packet is not the exact source-backed binding.", details={"cl": cl, "feature_id": feature_id, "packet_id": packet_id})
        level_event_ids.append(raw_level["event_id"])
        level_packet_ids.append(packet_id)
    if len(set(level_event_ids)) != len(level_event_ids) or len(set(level_packet_ids)) != len(level_packet_ids):
        raise invalid("The Path advancement event or packet identity is duplicated.")
    required_level_events = {(row["feature_record_id"], row["cl"]) for row in raw_levels}
    if not required_level_events.issubset(feature_events):
        raise invalid("The raw Path feature events do not cover the level progression.")

    translated_arts = immortal_translation.get("arts") if isinstance(immortal_translation, Mapping) else None
    if not isinstance(translated_arts, list):
        raise invalid("The copied progression has no translated Immortal Art list.")
    art_levels = [art.get("gained_at_cl") for art in translated_arts if isinstance(art, Mapping)]
    if (
        len(art_levels) != len(translated_arts)
        or any(type(level) is not int or not 15 <= level <= target_cl for level in art_levels)
        or len(set(art_levels)) != len(art_levels)
        or sorted(str(level) for level in art_levels) != sorted(immortal_allocations)
        or (target_cl >= 15 and not art_levels)
    ):
        raise invalid("The copied progression has no exact CL15+ Immortal Art acquisition proof (RAW-182, RAW-183).")
    nascent_feature_ids = {f"{row['path_id']}.feature.nascent_soul" for row in raw_path_rows}
    if target_cl >= 15 and not any(
        feature_id in nascent_feature_ids and gained_at_cl == 15
        for feature_id, gained_at_cl in feature_events
    ):
        raise invalid("The CL15 progression is not bound to a fixed Nascent Soul Path event.")

    current_character_realm = character.get("realm")
    if current_character_realm not in {"Mortal", expected_target_realm}:
        raise invalid("The copied character realm is malformed or forged.", details={"realm": current_character_realm, "expected": expected_target_realm})
    projected_ledger = deepcopy(dict(ledger))
    projected_character = deepcopy(dict(character))
    projected_character["realm"] = expected_target_realm
    projected_ledger["character"] = projected_character
    projected_advancement = deepcopy(dict(current_advancement))
    projected_levels = deepcopy(current_levels)
    for row in projected_levels:
        row["realm"] = realm_for_cl(row["cl"])
    projected_advancement["levels"] = projected_levels
    projected_ledger["advancement"] = projected_advancement
    realm_by_cl = {str(cl): realm_for_cl(cl) for cl in range(1, target_cl + 1)}
    provenance = {
        "schema_version": "TianxiaFoundry.FinalCharacterRealmProjectionProvenance.v1",
        "source_ledger_path": "Build/Character_Master_Ledger.json",
        "source_ledger_sha256": raw_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_sha256,
        "path_details_path": _PATH_PROJECTION_DETAILS_RELATIVE,
        "path_details_sha256": sha256_file(path_details_path),
        "path_id": path_id,
        "path_name": path_name,
        "target_cl": target_cl,
        "realm_by_cl": realm_by_cl,
        "level_event_ids": level_event_ids,
        "level_source_packet_ids": level_packet_ids,
        "immortal_acquisitions": [
            {"immortal_art_id": art["immortal_art_id"], "gained_at_cl": art["gained_at_cl"], "realm": art["realm"]}
            for art in translated_arts
        ],
        "ability_projection": {
            "details_path": ability_projection.get("details_path"),
            "details_sha256": ability_projection.get("details_sha256"),
            "asi_targets": ability_projection.get("asi_targets"),
            "transition_packet_ids": ability_projection.get("transition_packet_ids"),
        } if isinstance(ability_projection, Mapping) else None,
        "resource_projection": {
            "details_path": resource_projection.get("details_path"),
            "details_sha256": resource_projection.get("details_sha256"),
            "resource_id": resource_projection.get("resource_id"),
            "primary_resource_max": resource_projection.get("primary_resource_max"),
        } if isinstance(resource_projection, Mapping) else None,
        "grant_projection": {
            "details_path": grant_projection.get("details_path"),
            "details_sha256": grant_projection.get("details_sha256"),
            "background_origin_allocations_by_cl": deepcopy(grant_allocations_by_cl),
        } if isinstance(grant_projection, Mapping) else None,
    }
    _write_json(details_path, provenance)
    _write_json(ledger_path, projected_ledger)
    reread = _read_json(ledger_path, code="FINAL_CHARACTER_REALM_PROJECTION_INVALID")
    if reread != projected_ledger or raw_provenance_path.read_bytes() != raw_bytes:
        raise invalid("The compiler realm projection could not be read back exactly or altered raw provenance.")
    return {
        "schema_version": provenance["schema_version"],
        "source_ledger_path": provenance["source_ledger_path"],
        "source_ledger_sha256": raw_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_sha256,
        "path_details_path": _PATH_PROJECTION_DETAILS_RELATIVE,
        "path_details_sha256": provenance["path_details_sha256"],
        "details_path": _REALM_PROJECTION_DETAILS_RELATIVE,
        "details_sha256": sha256_file(details_path),
        "path_id": path_id,
        "target_cl": target_cl,
        "current_realm": expected_target_realm,
        "level_count": len(projected_levels),
        "level_event_ids": level_event_ids,
        "level_source_packet_ids": level_packet_ids,
        "immortal_acquired_at_cls": sorted(art_levels),
        "ability_projection_details_sha256": ability_projection.get("details_sha256") if isinstance(ability_projection, Mapping) else None,
        "resource_projection_details_sha256": resource_projection.get("details_sha256") if isinstance(resource_projection, Mapping) else None,
        "grant_projection_details_sha256": grant_projection.get("details_sha256") if isinstance(grant_projection, Mapping) else None,
        "background_origin_allocations_by_cl": deepcopy(grant_allocations_by_cl) if isinstance(grant_projection, Mapping) else None,
    }


def _project_modern_ac_for_compiler(
    workspace: Path,
    *,
    path_projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project the authenticated unarmored AC trace into compiler fields.

    The modern ledger keeps a rich ``ac_generation`` explanation, whereas
    the pinned compiler consumes a small integer component map.  This
    boundary projects only the source-proven unarmored formula: base 10 plus
    the sealed DEX modifier, with no shield, Path, method, item, or other
    adjustment and no applied source grants.  Pending conditional bonuses
    remain explanatory provenance; they are never executed here.
    """

    def invalid(message: str, *, details: Any = None) -> FoundryError:
        return _error("FINAL_CHARACTER_AC_PROJECTION_INVALID", message, details=details)

    root = Path(workspace)
    ledger_path = root / "Build/Character_Master_Ledger.json"
    raw_provenance_path = root / _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    path_details_path = root / _PATH_PROJECTION_DETAILS_RELATIVE
    details_path = root / _AC_PROJECTION_DETAILS_RELATIVE
    for path in (ledger_path, raw_provenance_path, path_details_path):
        if path.is_symlink() or not path.is_file():
            raise invalid("The copied AC projection provenance is missing or unsafe.", details={"path": str(path)})
    if details_path.exists():
        raise invalid("The copied workspace already contains AC projection provenance.")

    try:
        raw_provenance_bytes = raw_provenance_path.read_bytes()
        raw_provenance_sha256 = hashlib.sha256(raw_provenance_bytes).hexdigest()
        raw_ledger = _read_json(raw_provenance_path, code="FINAL_CHARACTER_AC_PROJECTION_INVALID")
        ledger = _read_json(ledger_path, code="FINAL_CHARACTER_AC_PROJECTION_INVALID")
        path_details = _read_json(path_details_path, code="FINAL_CHARACTER_AC_PROJECTION_INVALID")
    except (OSError, FoundryError) as exc:
        if isinstance(exc, FoundryError):
            raise invalid("The copied AC projection provenance could not be read.", details={"cause": exc.code}) from exc
        raise invalid("The copied AC projection provenance could not be read.") from exc
    if not isinstance(raw_ledger, Mapping) or not isinstance(ledger, Mapping) or not isinstance(path_details, Mapping):
        raise invalid("The copied AC projection inputs are not mappings.")
    if path_projection is not None:
        if not isinstance(path_projection, Mapping):
            raise invalid("The Path projection result is not a mapping.")
        if (
            path_projection.get("source_ledger_sha256") != raw_provenance_sha256
            or path_projection.get("modern_provenance_sha256") != raw_provenance_sha256
            or path_projection.get("details_sha256") != sha256_file(path_details_path)
            or path_details.get("source_ledger_sha256") != raw_provenance_sha256
        ):
            raise invalid("The AC projection is not bound to the original modern ledger bytes.")
    elif path_details.get("source_ledger_sha256") != raw_provenance_sha256:
        raise invalid("The copied Path projection details are not bound to their raw ledger provenance.")

    raw_character = raw_ledger.get("character")
    character = ledger.get("character")
    raw_core_stats = raw_ledger.get("core_stats")
    core_stats = ledger.get("core_stats")
    if (
        not isinstance(raw_character, Mapping)
        or not isinstance(character, Mapping)
        or not isinstance(raw_core_stats, Mapping)
        or not isinstance(core_stats, Mapping)
    ):
        raise invalid("The copied ledger has no AC character/core-stat authority.")
    path_id = character.get("path_id")
    path_name = character.get("path")
    if (
        not isinstance(path_id, str)
        or not path_id.strip()
        or not isinstance(path_name, str)
        or not path_name.strip()
        or raw_character.get("path_id") != path_id
        or raw_character.get("path") != path_name
    ):
        raise invalid("The copied active Path identity diverges from raw AC provenance.")
    proof = _PACKET_PATH_PROOFS.get(path_id)
    if proof is None:
        raise invalid("The copied active Path is not one fixed canonical Path.", details={"path_id": path_id})

    for field in ("ac_base", "ac_active"):
        source_value = raw_core_stats.get(field)
        current_value = core_stats.get(field)
        if type(source_value) is not int or type(current_value) is not int or current_value != source_value:
            raise invalid("The copied AC totals are missing, non-integer, or diverge from raw provenance.", details={"field": field})
    ac_base = raw_core_stats["ac_base"]
    ac_active = raw_core_stats["ac_active"]

    scores = raw_core_stats.get("ability_scores")
    modifiers = raw_core_stats.get("ability_modifiers")
    current_scores = core_stats.get("ability_scores")
    current_modifiers = core_stats.get("ability_modifiers")
    if (
        not isinstance(scores, Mapping)
        or not isinstance(modifiers, Mapping)
        or type(scores.get("DEX")) is not int
        or type(modifiers.get("DEX")) is not int
        or not isinstance(current_scores, Mapping)
        or not isinstance(current_modifiers, Mapping)
        or current_scores != scores
        or current_modifiers != modifiers
    ):
        raise invalid("The copied DEX score/modifier authority is missing or diverges from raw provenance.")
    dexterity_score = scores["DEX"]
    dexterity_modifier = modifiers["DEX"]
    if dexterity_modifier != (dexterity_score - 10) // 2:
        raise invalid(
            "The copied DEX score and modifier do not satisfy standard modifier math.",
            details={"score": dexterity_score, "modifier": dexterity_modifier},
        )
    if ac_base != 10 + dexterity_modifier or ac_active != ac_base:
        raise invalid(
            "The source-backed unarmored AC trace does not reconcile with DEX.",
            details={"ac_base": ac_base, "ac_active": ac_active, "dexterity_modifier": dexterity_modifier},
        )

    source_generation = raw_core_stats.get("ac_generation")
    current_generation = core_stats.get("ac_generation")
    if not isinstance(source_generation, Mapping) or not isinstance(current_generation, Mapping):
        raise invalid("The copied AC generation trace is missing or malformed.")
    if (
        source_generation.get("calculation") != "unarmored_base"
        or source_generation.get("formula_id") != _AC_FORMULA_ID
    ):
        raise invalid("The copied AC generation trace is not the authenticated unarmored formula.")
    trace = source_generation.get("trace")
    expected_trace = {
        "node_count": 3,
        "root": {
            "op": "add",
            "terms": [
                {"op": "constant", "value": 10},
                {"ability": "DEX", "op": "ability_modifier", "value": dexterity_modifier},
            ],
            "value": ac_active,
        },
        "schema_version": "TianxiaFoundry.SafeFormulaTrace.v1",
    }
    if trace != expected_trace:
        raise invalid("The copied AC generation trace does not prove the sealed unarmored formula.")

    pending = source_generation.get("conditional_bonuses_pending_execution")
    if pending is not None and (
        not isinstance(pending, list)
        or any(type(value) is not str or not value.strip() or value != value.strip() for value in pending)
        or len(pending) != len(set(pending))
    ):
        raise invalid("The copied pending AC bonuses are malformed or duplicated.")
    for field in ("conditional_bonuses_applied", "conditional_bonuses_executed"):
        if field in source_generation and source_generation[field] not in ([], None):
            raise invalid("A pending conditional AC bonus cannot be treated as executed.", details={"field": field})

    # The source trace is immutable provenance.  A prior compiler projection
    # may add only the exact fields below; all rich source fields must remain
    # byte/structure-equivalent to the authenticated raw trace.
    compiler_fields_present = [field in current_generation for field in _AC_COMPILER_FIELDS]
    if any(compiler_fields_present) and not all(compiler_fields_present):
        raise invalid("The copied AC compiler component map is partial.")
    if current_generation.get("ac_generation_provenance") != source_generation and "ac_generation_provenance" in current_generation:
        raise invalid("The retained AC generation provenance diverges from the raw trace.")
    for field, value in source_generation.items():
        if field not in _AC_COMPILER_FIELDS and current_generation.get(field) != value:
            raise invalid("The copied rich AC generation trace diverges from raw provenance.", details={"field": field})
    for field in current_generation:
        if field not in _AC_COMPILER_FIELDS and field != "ac_generation_provenance" and field not in source_generation:
            raise invalid("The copied AC generation has an unsupported unbound field.", details={"field": field})

    expected_generation = {
        "base_ac": 10,
        "dexterity_modifier_applied": dexterity_modifier,
        "shield_adjustment": 0,
        "foundation_adjustment": 0,
        "method_adjustment": 0,
        "item_adjustment": 0,
        "other_adjustment": 0,
        "total": ac_active,
        "source_grant_ids": [],
    }
    if all(compiler_fields_present):
        if any(
            type(current_generation.get(field)) is not int for field in _AC_COMPILER_COMPONENTS + ("total",)
        ):
            raise invalid("The copied AC compiler component values are not integers.")
        if current_generation.get("source_grant_ids") != [] or any(
            current_generation.get(field) != value for field, value in expected_generation.items()
        ):
            raise invalid("The copied AC compiler component map conflicts with the source-backed formula.")
        compiler_generation = deepcopy(dict(current_generation))
        generation_mode = "preserved_existing"
    else:
        compiler_generation = expected_generation
        generation_mode = "source_backed_unarmored_projection"

    projected_ledger = deepcopy(dict(ledger))
    projected_core_stats = deepcopy(dict(core_stats))
    projected_core_stats["ac_generation"] = deepcopy(compiler_generation)
    if generation_mode == "source_backed_unarmored_projection":
        projected_core_stats["ac_generation_provenance"] = deepcopy(dict(source_generation))
    projected_ledger["core_stats"] = projected_core_stats
    provenance = {
        "schema_version": "TianxiaFoundry.FinalCharacterACProjectionProvenance.v1",
        "source_ledger_path": "Build/Character_Master_Ledger.json",
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_provenance_sha256,
        "path_details_path": _PATH_PROJECTION_DETAILS_RELATIVE,
        "path_details_sha256": sha256_file(path_details_path),
        "path_id": path_id,
        "path_name": path_name,
        "formula_id": _AC_FORMULA_ID,
        "calculation": "unarmored_base",
        "dexterity_score": dexterity_score,
        "dexterity_modifier": dexterity_modifier,
        "ac_base": ac_base,
        "ac_active": ac_active,
        "source_ac_generation": deepcopy(dict(source_generation)),
        "ac_generation_provenance": deepcopy(dict(source_generation)),
        "compiler_generation": deepcopy(compiler_generation),
        "compiler_generation_mode": generation_mode,
        "source_grant_ids": [],
    }
    _write_json(details_path, provenance)
    _write_json(ledger_path, projected_ledger)
    reread = _read_json(ledger_path, code="FINAL_CHARACTER_AC_PROJECTION_INVALID")
    if reread != projected_ledger or raw_provenance_path.read_bytes() != raw_provenance_bytes:
        raise invalid("The compiler AC projection could not be read back exactly or altered raw provenance.")
    return {
        "schema_version": provenance["schema_version"],
        "source_ledger_path": provenance["source_ledger_path"],
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_provenance_sha256,
        "details_path": _AC_PROJECTION_DETAILS_RELATIVE,
        "details_sha256": sha256_file(details_path),
        "path_id": path_id,
        "ac_base": ac_base,
        "ac_active": ac_active,
        "dexterity_modifier": dexterity_modifier,
        "compiler_generation": deepcopy(compiler_generation),
        "compiler_generation_mode": generation_mode,
        "source_grant_ids": [],
    }


def _project_modern_speed_for_compiler(
    workspace: Path,
    *,
    path_projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project the authenticated baseline walking-speed trace for the compiler.

    Stage 2 records the source-backed walking speed as a compact descriptive
    pair (``mode``/``rule_id``).  The pinned compiler consumes an explicit
    integer component ledger instead.  This boundary is deliberately narrow:
    only the fixed Human walking-speed rule is accepted, all adjustments are
    zero, and an existing complete component map must reconcile exactly.  The
    modern trace remains available as a separate provenance field; it is never
    replaced by caller-supplied arithmetic.
    """

    def invalid(message: str, *, details: Any = None) -> FoundryError:
        return _error("FINAL_CHARACTER_SPEED_PROJECTION_INVALID", message, details=details)

    root = Path(workspace)
    ledger_path = root / "Build/Character_Master_Ledger.json"
    raw_provenance_path = root / _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    path_details_path = root / _PATH_PROJECTION_DETAILS_RELATIVE
    projection_map_path = root / "Build/Projection_Provenance_Map.json"
    details_path = root / _SPEED_PROJECTION_DETAILS_RELATIVE
    for path in (ledger_path, raw_provenance_path, path_details_path, projection_map_path):
        if path.is_symlink() or not path.is_file():
            raise invalid("The copied speed projection provenance is missing or unsafe.", details={"path": str(path)})
    if details_path.exists():
        raise invalid("The copied workspace already contains speed projection provenance.")

    try:
        raw_provenance_bytes = raw_provenance_path.read_bytes()
        raw_provenance_sha256 = hashlib.sha256(raw_provenance_bytes).hexdigest()
        projection_map_bytes = projection_map_path.read_bytes()
        projection_map_sha256 = hashlib.sha256(projection_map_bytes).hexdigest()
        raw_ledger = _read_json(raw_provenance_path, code="FINAL_CHARACTER_SPEED_PROJECTION_INVALID")
        ledger = _read_json(ledger_path, code="FINAL_CHARACTER_SPEED_PROJECTION_INVALID")
        path_details = _read_json(path_details_path, code="FINAL_CHARACTER_SPEED_PROJECTION_INVALID")
        projection_map = _read_json(projection_map_path, code="FINAL_CHARACTER_SPEED_PROJECTION_INVALID")
    except (OSError, FoundryError) as exc:
        if isinstance(exc, FoundryError):
            raise invalid("The copied speed projection provenance could not be read.", details={"cause": exc.code}) from exc
        raise invalid("The copied speed projection provenance could not be read.") from exc
    if (
        not isinstance(raw_ledger, Mapping)
        or not isinstance(ledger, Mapping)
        or not isinstance(path_details, Mapping)
        or not isinstance(projection_map, Mapping)
    ):
        raise invalid("The copied speed projection inputs are not mappings.")
    if path_projection is not None:
        if not isinstance(path_projection, Mapping):
            raise invalid("The Path projection result is not a mapping.")
        if (
            path_projection.get("source_ledger_sha256") != raw_provenance_sha256
            or path_projection.get("modern_provenance_sha256") != raw_provenance_sha256
            or path_projection.get("details_sha256") != sha256_file(path_details_path)
            or path_details.get("source_ledger_sha256") != raw_provenance_sha256
        ):
            raise invalid("The speed projection is not bound to the original modern ledger bytes.")
    elif path_details.get("source_ledger_sha256") != raw_provenance_sha256:
        raise invalid("The copied Path projection details are not bound to their raw ledger provenance.")

    # Prove the exact fixed baseline rule before using any value from the
    # copied projection map.  The APP authority file is hash-pinned and
    # _bridge_fixed_json rejects symlinks or malformed JSON.
    baseline_pack = _bridge_fixed_json(_SPEED_AUTHORITY_PATH, _SPEED_AUTHORITY_SHA256)
    if not isinstance(baseline_pack, Mapping):
        raise invalid("The fixed walking-speed authority is unavailable or unsafe.")
    baseline_rules = baseline_pack.get("rules")
    baseline_matches = [
        row for row in baseline_rules
        if isinstance(row, Mapping) and row.get("rule_id") == _SPEED_RULE_ID
    ] if isinstance(baseline_rules, list) else []
    expected_baseline_row = {
        "applicability": "Human",
        "authority_classification": "AUTHENTICATED_CANONICAL_SOURCE",
        "output_fields": ["/core_stats/speed_ft", "/core_stats/speed_generation/base_speed"],
        "rule_id": _SPEED_RULE_ID,
        "source": deepcopy(_SPEED_SOURCE),
        "typed_value": 30,
        "unit": "feet",
    }
    if (
        baseline_pack.get("pack_id") != "tianxia.core.character_baseline.owner_r1"
        or baseline_pack.get("version") != "1.0.0"
        or len(baseline_matches) != 1
        or dict(baseline_matches[0]) != expected_baseline_row
    ):
        raise invalid("The fixed walking-speed authority is malformed or ambiguous.")

    mappings = projection_map.get("mappings")
    mapping_key = f"baseline:{_SPEED_RULE_ID}"
    mapping = mappings.get(mapping_key) if isinstance(mappings, Mapping) else None
    if not isinstance(mapping, Mapping) or dict(mapping) != _SPEED_PROVENANCE_MAPPING:
        raise invalid(
            "The copied baseline speed provenance does not match the fixed authority.",
            details={"mapping": mapping_key},
        )

    raw_character = raw_ledger.get("character")
    character = ledger.get("character")
    raw_core_stats = raw_ledger.get("core_stats")
    core_stats = ledger.get("core_stats")
    if (
        not isinstance(raw_character, Mapping)
        or not isinstance(character, Mapping)
        or not isinstance(raw_core_stats, Mapping)
        or not isinstance(core_stats, Mapping)
    ):
        raise invalid("The copied ledger has no speed character/core-stat authority.")
    path_id = character.get("path_id")
    path_name = character.get("path")
    if (
        not isinstance(path_id, str)
        or not path_id.strip()
        or not isinstance(path_name, str)
        or not path_name.strip()
        or raw_character.get("path_id") != path_id
        or raw_character.get("path") != path_name
        or path_details.get("path_id") != path_id
        or path_details.get("path_name") != path_name
        or path_projection is not None and path_projection.get("path_id") != path_id
        or path_id not in _PACKET_PATH_PROOFS
    ):
        raise invalid("The copied active Path identity diverges from speed provenance.", details={"path_id": path_id})

    raw_speed = raw_core_stats.get("speed_ft")
    current_speed = core_stats.get("speed_ft")
    expected_speed = baseline_matches[0]["typed_value"]
    if (
        type(raw_speed) is not int
        or type(current_speed) is not int
        or raw_speed != current_speed
        or raw_speed != expected_speed
    ):
        raise invalid(
            "The copied walking speed is missing, non-integer, or diverges from fixed authority.",
            details={"raw": raw_speed, "current": current_speed, "expected": expected_speed},
        )

    source_generation = raw_core_stats.get("speed_generation")
    current_generation = core_stats.get("speed_generation")
    if not isinstance(source_generation, Mapping) or not isinstance(current_generation, Mapping):
        raise invalid("The copied speed generation trace is missing or malformed.")

    expected_source_generation = {"mode": "walking", "rule_id": _SPEED_RULE_ID}
    source_has_compiler_fields = [field in source_generation for field in _SPEED_COMPILER_FIELDS]
    if any(source_has_compiler_fields) and not all(source_has_compiler_fields):
        raise invalid("The source speed compiler component map is partial.")
    if all(source_has_compiler_fields):
        source_compiler_generation = dict(source_generation)
        if (
            any(type(source_compiler_generation.get(field)) is not int for field in _SPEED_COMPILER_COMPONENTS + ("total",))
            or source_compiler_generation.get("source_grant_ids") != []
        ):
            raise invalid("The source speed compiler component values are malformed.")
        expected_existing_generation = {
            "base_speed": expected_speed,
            "path_adjustment": 0,
            "sphere_adjustment": 0,
            "foundation_adjustment": 0,
            "method_adjustment": 0,
            "equipment_adjustment": 0,
            "other_adjustment": 0,
            "total": expected_speed,
            "source_grant_ids": [],
        }
        if source_compiler_generation != expected_existing_generation:
            raise invalid("The source speed compiler component map conflicts with fixed authority.")
        if dict(current_generation) != source_compiler_generation:
            raise invalid("The existing speed compiler component map diverges from source provenance.")
        compiler_generation = deepcopy(source_compiler_generation)
        generation_mode = "preserved_existing"
        source_trace: dict[str, Any] | None = None
    else:
        if dict(source_generation) != expected_source_generation:
            raise invalid("The copied speed generation trace is not the fixed walking-speed rule.")
        compiler_fields_present = [field in current_generation for field in _SPEED_COMPILER_FIELDS]
        if any(compiler_fields_present) and not all(compiler_fields_present):
            raise invalid("The copied speed compiler component map is partial.")
        if (
            "speed_generation_provenance" in current_generation
            and current_generation.get("speed_generation_provenance") != dict(source_generation)
        ):
            raise invalid("The retained speed generation provenance diverges from raw source.")
        for field, value in source_generation.items():
            if current_generation.get(field) != value:
                raise invalid("The copied rich speed generation trace diverges from raw provenance.", details={"field": field})
        for field in current_generation:
            if field not in _SPEED_COMPILER_FIELDS and field not in source_generation and field != "speed_generation_provenance":
                raise invalid("The copied speed generation has an unsupported unbound field.", details={"field": field})
        expected_generation = {
            "base_speed": expected_speed,
            "path_adjustment": 0,
            "sphere_adjustment": 0,
            "foundation_adjustment": 0,
            "method_adjustment": 0,
            "equipment_adjustment": 0,
            "other_adjustment": 0,
            "total": expected_speed,
            "source_grant_ids": [],
        }
        if all(compiler_fields_present):
            if (
                any(type(current_generation.get(field)) is not int for field in _SPEED_COMPILER_COMPONENTS + ("total",))
                or current_generation.get("source_grant_ids") != []
                or any(current_generation.get(field) != value for field, value in expected_generation.items())
            ):
                raise invalid("The copied speed compiler component map conflicts with fixed authority.")
            compiler_generation = deepcopy(dict(current_generation))
            generation_mode = "preserved_existing"
        else:
            compiler_generation = expected_generation
            generation_mode = "source_backed_walking_speed_projection"
        source_trace = dict(source_generation)

    projected_ledger = deepcopy(dict(ledger))
    projected_core_stats = deepcopy(dict(core_stats))
    projected_core_stats["speed_generation"] = deepcopy(compiler_generation)
    if source_trace is not None and generation_mode == "source_backed_walking_speed_projection":
        projected_core_stats["speed_generation_provenance"] = deepcopy(source_trace)
    projected_ledger["core_stats"] = projected_core_stats
    provenance = {
        "schema_version": "TianxiaFoundry.FinalCharacterSpeedProjectionProvenance.v1",
        "source_ledger_path": "Build/Character_Master_Ledger.json",
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_provenance_sha256,
        "path_details_path": _PATH_PROJECTION_DETAILS_RELATIVE,
        "path_details_sha256": sha256_file(path_details_path),
        "projection_map_path": "Build/Projection_Provenance_Map.json",
        "projection_map_sha256": projection_map_sha256,
        "authority_path": _SPEED_AUTHORITY_PATH,
        "authority_sha256": _SPEED_AUTHORITY_SHA256,
        "path_id": path_id,
        "path_name": path_name,
        "rule_id": _SPEED_RULE_ID,
        "source": deepcopy(_SPEED_SOURCE),
        "typed_value": expected_speed,
        "source_speed_generation": deepcopy(dict(source_generation)),
        "compiler_generation": deepcopy(compiler_generation),
        "compiler_generation_mode": generation_mode,
        "source_grant_ids": [],
    }
    _write_json(details_path, provenance)
    _write_json(ledger_path, projected_ledger)
    reread = _read_json(ledger_path, code="FINAL_CHARACTER_SPEED_PROJECTION_INVALID")
    if (
        reread != projected_ledger
        or raw_provenance_path.read_bytes() != raw_provenance_bytes
        or projection_map_path.read_bytes() != projection_map_bytes
    ):
        raise invalid("The compiler speed projection could not be read back exactly or altered raw provenance.")
    return {
        "schema_version": provenance["schema_version"],
        "source_ledger_path": provenance["source_ledger_path"],
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_provenance_sha256,
        "path_details_path": _PATH_PROJECTION_DETAILS_RELATIVE,
        "path_details_sha256": provenance["path_details_sha256"],
        "details_path": _SPEED_PROJECTION_DETAILS_RELATIVE,
        "details_sha256": sha256_file(details_path),
        "projection_map_path": provenance["projection_map_path"],
        "projection_map_sha256": projection_map_sha256,
        "authority_path": _SPEED_AUTHORITY_PATH,
        "authority_sha256": _SPEED_AUTHORITY_SHA256,
        "path_id": path_id,
        "speed_ft": expected_speed,
        "compiler_generation": deepcopy(compiler_generation),
        "compiler_generation_mode": generation_mode,
        "source_grant_ids": [],
    }


def _project_modern_initiative_for_compiler(
    workspace: Path,
    *,
    path_projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project the authenticated DEX initiative trace for the compiler.

    The modern ledger records the source formula and a named situational
    advantage provenance, while the pinned compiler consumes an explicit
    proficiency/adjustment map.  Situational advantage is not a numeric
    initiative bonus and is retained only in the provenance copy.  This
    boundary therefore derives the compiler map as DEX/0/0/DEX-modifier with
    no source grants, after proving the fixed owner-ratified formula and exact
    copied provenance row.
    """

    def invalid(message: str, *, details: Any = None) -> FoundryError:
        return _error("FINAL_CHARACTER_INITIATIVE_PROJECTION_INVALID", message, details=details)

    root = Path(workspace)
    ledger_path = root / "Build/Character_Master_Ledger.json"
    raw_provenance_path = root / _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    path_details_path = root / _PATH_PROJECTION_DETAILS_RELATIVE
    projection_map_path = root / "Build/Projection_Provenance_Map.json"
    details_path = root / _INITIATIVE_PROJECTION_DETAILS_RELATIVE
    for path in (ledger_path, raw_provenance_path, path_details_path, projection_map_path):
        if path.is_symlink() or not path.is_file():
            raise invalid("The copied initiative projection provenance is missing or unsafe.", details={"path": str(path)})
    if details_path.exists():
        raise invalid("The copied workspace already contains initiative projection provenance.")

    try:
        raw_provenance_bytes = raw_provenance_path.read_bytes()
        raw_provenance_sha256 = hashlib.sha256(raw_provenance_bytes).hexdigest()
        projection_map_bytes = projection_map_path.read_bytes()
        projection_map_sha256 = hashlib.sha256(projection_map_bytes).hexdigest()
        raw_ledger = _read_json(raw_provenance_path, code="FINAL_CHARACTER_INITIATIVE_PROJECTION_INVALID")
        ledger = _read_json(ledger_path, code="FINAL_CHARACTER_INITIATIVE_PROJECTION_INVALID")
        path_details = _read_json(path_details_path, code="FINAL_CHARACTER_INITIATIVE_PROJECTION_INVALID")
        projection_map = _read_json(projection_map_path, code="FINAL_CHARACTER_INITIATIVE_PROJECTION_INVALID")
    except (OSError, FoundryError) as exc:
        if isinstance(exc, FoundryError):
            raise invalid("The copied initiative projection provenance could not be read.", details={"cause": exc.code}) from exc
        raise invalid("The copied initiative projection provenance could not be read.") from exc
    if (
        not isinstance(raw_ledger, Mapping)
        or not isinstance(ledger, Mapping)
        or not isinstance(path_details, Mapping)
        or not isinstance(projection_map, Mapping)
    ):
        raise invalid("The copied initiative projection inputs are not mappings.")
    if path_projection is not None:
        if not isinstance(path_projection, Mapping):
            raise invalid("The Path projection result is not a mapping.")
        if (
            path_projection.get("source_ledger_sha256") != raw_provenance_sha256
            or path_projection.get("modern_provenance_sha256") != raw_provenance_sha256
            or path_projection.get("details_sha256") != sha256_file(path_details_path)
            or path_details.get("source_ledger_sha256") != raw_provenance_sha256
        ):
            raise invalid("The initiative projection is not bound to the original modern ledger bytes.")
    elif path_details.get("source_ledger_sha256") != raw_provenance_sha256:
        raise invalid("The copied Path projection details are not bound to their raw ledger provenance.")

    authority = _bridge_fixed_json(_INITIATIVE_AUTHORITY_PATH, _INITIATIVE_AUTHORITY_SHA256)
    if not isinstance(authority, Mapping):
        raise invalid("The fixed initiative authority is unavailable or unsafe.")
    authority_rules = authority.get("rules")
    authority_matches = [
        row for row in authority_rules
        if isinstance(row, Mapping) and row.get("rule_id") == _INITIATIVE_AUTHORITY_RULE_ID
    ] if isinstance(authority_rules, list) else []
    expected_authority_row = {
        "anchor": "/rules/1",
        "applicability": "All creatures using the ordinary initiative check",
        "check": {
            "ability": "DEX",
            "bonus_formula_id": _INITIATIVE_FORMULA_ID,
            "die": "1d20",
        },
        "formula": {
            "formula_id": _INITIATIVE_FORMULA_ID,
            "root": {"ability": "DEX", "op": "ability_modifier"},
            "schema_version": "TianxiaFoundry.SafeFormula.v1",
        },
        "output_fields": ["/core_stats/initiative_bonus", "/core_stats/initiative_generation"],
        "rule_id": _INITIATIVE_AUTHORITY_RULE_ID,
        "rules": [
            "Add only explicit initiative modifiers.",
            "Advantage and Disadvantage use the ordinary check mechanism.",
            "Street-Hardened grants situational Advantage under its authenticated trigger.",
        ],
    }
    if (
        authority.get("amendment_id") != "Tianxia_Core_Character_Baseline_Owner_Amendment_R1"
        or authority.get("version") != "1.0.0"
        or len(authority_matches) != 1
        or dict(authority_matches[0]) != expected_authority_row
    ):
        raise invalid("The fixed initiative authority is malformed or ambiguous.")

    raw_character = raw_ledger.get("character")
    character = ledger.get("character")
    raw_core_stats = raw_ledger.get("core_stats")
    core_stats = ledger.get("core_stats")
    if (
        not isinstance(raw_character, Mapping)
        or not isinstance(character, Mapping)
        or not isinstance(raw_core_stats, Mapping)
        or not isinstance(core_stats, Mapping)
    ):
        raise invalid("The copied ledger has no initiative character/core-stat authority.")
    path_id = character.get("path_id")
    path_name = character.get("path")
    if (
        not isinstance(path_id, str)
        or not path_id.strip()
        or not isinstance(path_name, str)
        or not path_name.strip()
        or raw_character.get("path_id") != path_id
        or raw_character.get("path") != path_name
        or path_details.get("path_id") != path_id
        or path_details.get("path_name") != path_name
        or (path_projection is not None and path_projection.get("path_id") != path_id)
        or path_id not in _PACKET_PATH_PROOFS
    ):
        raise invalid("The copied active Path identity diverges from initiative provenance.", details={"path_id": path_id})

    scores = raw_core_stats.get("ability_scores")
    modifiers = raw_core_stats.get("ability_modifiers")
    current_scores = core_stats.get("ability_scores")
    current_modifiers = core_stats.get("ability_modifiers")
    if (
        not isinstance(scores, Mapping)
        or not isinstance(modifiers, Mapping)
        or type(scores.get("DEX")) is not int
        or type(modifiers.get("DEX")) is not int
        or not isinstance(current_scores, Mapping)
        or not isinstance(current_modifiers, Mapping)
        or current_scores != scores
        or current_modifiers != modifiers
    ):
        raise invalid("The copied DEX score/modifier authority is missing or diverges from raw provenance.")
    dexterity_score = scores["DEX"]
    dexterity_modifier = modifiers["DEX"]
    if dexterity_modifier != (dexterity_score - 10) // 2:
        raise invalid(
            "The copied DEX score and modifier do not satisfy standard modifier math.",
            details={"score": dexterity_score, "modifier": dexterity_modifier},
        )

    raw_bonus = raw_core_stats.get("initiative_bonus")
    current_bonus = core_stats.get("initiative_bonus")
    if (
        type(raw_bonus) is not int
        or type(current_bonus) is not int
        or raw_bonus != current_bonus
        or raw_bonus != dexterity_modifier
    ):
        raise invalid("The copied initiative total is missing, non-integer, or diverges from DEX.")

    raw_generation = raw_core_stats.get("initiative_generation")
    current_generation = core_stats.get("initiative_generation")
    if not isinstance(raw_generation, Mapping) or not isinstance(current_generation, Mapping):
        raise invalid("The copied initiative generation trace is missing or malformed.")

    expected_trace = {
        "node_count": 1,
        "root": {"ability": "DEX", "op": "ability_modifier", "value": dexterity_modifier},
        "schema_version": "TianxiaFoundry.SafeFormulaTrace.v1",
    }
    expected_source_generation = {
        "ability": "DEX",
        "check": "1d20",
        "formula_id": _INITIATIVE_FORMULA_ID,
        "situational_advantage_sources": [_INITIATIVE_ADVANTAGE_SOURCE],
        "trace": expected_trace,
    }
    source_extra_presence = [field in raw_generation for field in _INITIATIVE_COMPILER_EXTRA_FIELDS]
    if any(source_extra_presence) and not all(source_extra_presence):
        raise invalid("The source initiative compiler component map is partial.")
    expected_generation = {
        "ability": "DEX",
        "proficiency_multiplier": 0,
        "adjustment": 0,
        "total": dexterity_modifier,
        "source_grant_ids": [],
    }
    source_trace: dict[str, Any] | None
    if all(source_extra_presence):
        if dict(raw_generation) != expected_generation or dict(current_generation) != expected_generation:
            raise invalid("The existing source initiative compiler map conflicts with fixed authority.")
        compiler_generation = deepcopy(expected_generation)
        generation_mode = "preserved_existing"
        source_trace = None
    else:
        if dict(raw_generation) != expected_source_generation:
            raise invalid("The copied initiative trace is not the fixed DEX formula/provenance.")
        current_extra_presence = [field in current_generation for field in _INITIATIVE_COMPILER_EXTRA_FIELDS]
        if any(current_extra_presence) and not all(current_extra_presence):
            raise invalid("The copied initiative compiler component map is partial.")
        if "initiative_generation_provenance" in current_generation and current_generation.get("initiative_generation_provenance") != expected_source_generation:
            raise invalid("The retained initiative generation provenance diverges from raw source.")
        rich_fields = tuple(field for field in expected_source_generation if field != "ability")
        has_current_rich = any(field in current_generation for field in rich_fields)
        if has_current_rich:
            if any(current_generation.get(field) != expected_source_generation[field] for field in rich_fields):
                raise invalid("The copied rich initiative trace diverges from raw provenance.")
        elif not all(current_extra_presence):
            raise invalid("The copied initiative trace is missing its source-backed fields.")
        allowed_current_fields = set(_INITIATIVE_COMPILER_FIELDS) | set(expected_source_generation) | {"initiative_generation_provenance"}
        if any(field not in allowed_current_fields for field in current_generation):
            raise invalid("The copied initiative generation has an unsupported unbound field.")
        if all(current_extra_presence):
            if (
                current_generation.get("ability") != "DEX"
                or type(current_generation.get("proficiency_multiplier")) is not int
                or type(current_generation.get("adjustment")) is not int
                or type(current_generation.get("total")) is not int
                or current_generation.get("source_grant_ids") != []
                or dict(current_generation) != expected_generation
            ):
                raise invalid("The copied initiative compiler component map conflicts with fixed authority.")
            compiler_generation = deepcopy(dict(current_generation))
            generation_mode = "preserved_existing"
        else:
            compiler_generation = expected_generation
            generation_mode = "source_backed_dex_projection"
        source_trace = deepcopy(expected_source_generation)

    expected_mapping = deepcopy(_INITIATIVE_PROVENANCE_MAPPING)
    expected_mapping["formula_trace"]["root"]["value"] = dexterity_modifier
    mappings = projection_map.get("mappings")
    mapping = mappings.get(f"baseline:{_INITIATIVE_RULE_ID}") if isinstance(mappings, Mapping) else None
    if not isinstance(mapping, Mapping) or dict(mapping) != expected_mapping:
        raise invalid("The copied initiative provenance does not match the fixed formula authority.")

    projected_ledger = deepcopy(dict(ledger))
    projected_core_stats = deepcopy(dict(core_stats))
    projected_core_stats["initiative_generation"] = deepcopy(compiler_generation)
    if source_trace is not None and generation_mode == "source_backed_dex_projection":
        projected_core_stats["initiative_generation_provenance"] = deepcopy(source_trace)
    projected_ledger["core_stats"] = projected_core_stats
    provenance = {
        "schema_version": "TianxiaFoundry.FinalCharacterInitiativeProjectionProvenance.v1",
        "source_ledger_path": "Build/Character_Master_Ledger.json",
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_provenance_sha256,
        "path_details_path": _PATH_PROJECTION_DETAILS_RELATIVE,
        "path_details_sha256": sha256_file(path_details_path),
        "projection_map_path": "Build/Projection_Provenance_Map.json",
        "projection_map_sha256": projection_map_sha256,
        "authority_path": _INITIATIVE_AUTHORITY_PATH,
        "authority_sha256": _INITIATIVE_AUTHORITY_SHA256,
        "path_id": path_id,
        "path_name": path_name,
        "rule_id": _INITIATIVE_RULE_ID,
        "formula_id": _INITIATIVE_FORMULA_ID,
        "ability": "DEX",
        "dexterity_score": dexterity_score,
        "dexterity_modifier": dexterity_modifier,
        "initiative_bonus": dexterity_modifier,
        "source_initiative_generation": deepcopy(dict(raw_generation)),
        "initiative_generation_provenance": deepcopy(dict(raw_generation)),
        "compiler_generation": deepcopy(compiler_generation),
        "compiler_generation_mode": generation_mode,
        "source_grant_ids": [],
    }
    _write_json(details_path, provenance)
    _write_json(ledger_path, projected_ledger)
    reread = _read_json(ledger_path, code="FINAL_CHARACTER_INITIATIVE_PROJECTION_INVALID")
    if (
        reread != projected_ledger
        or raw_provenance_path.read_bytes() != raw_provenance_bytes
        or projection_map_path.read_bytes() != projection_map_bytes
    ):
        raise invalid("The compiler initiative projection could not be read back exactly or altered raw provenance.")
    return {
        "schema_version": provenance["schema_version"],
        "source_ledger_path": provenance["source_ledger_path"],
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_provenance_sha256,
        "path_details_path": _PATH_PROJECTION_DETAILS_RELATIVE,
        "path_details_sha256": provenance["path_details_sha256"],
        "details_path": _INITIATIVE_PROJECTION_DETAILS_RELATIVE,
        "details_sha256": sha256_file(details_path),
        "projection_map_path": "Build/Projection_Provenance_Map.json",
        "projection_map_sha256": projection_map_sha256,
        "authority_path": _INITIATIVE_AUTHORITY_PATH,
        "authority_sha256": _INITIATIVE_AUTHORITY_SHA256,
        "path_id": path_id,
        "initiative_bonus": dexterity_modifier,
        "compiler_generation": deepcopy(compiler_generation),
        "compiler_generation_mode": generation_mode,
        "source_grant_ids": [],
    }


def _project_modern_core_saves_for_compiler(
    workspace: Path,
    *,
    path_projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive the compiler's core saving-throw maps from fixed Path authority.

    Modern Stage-2 ledgers may omit the compiler-required save maps even when
    their sealed ability scores and modifiers are complete.  This projection is
    deliberately limited to the no-proficiency case: the authenticated Path
    index must say exactly ``"None"`` before the six saves are copied from the
    already sealed modifiers.  When the modern ledger includes its complete
    skill projection but omits the compiler's explicit adjustment map, zero
    adjustments are added only when the sealed skill arithmetic proves them.
    No skill bonuses, combat, resource, or other missing compiler field is
    inferred here.
    """

    def invalid(message: str, *, details: Any = None) -> FoundryError:
        return _error("FINAL_CHARACTER_CORE_SAVE_PROJECTION_INVALID", message, details=details)

    root = Path(workspace)
    ledger_path = root / "Build/Character_Master_Ledger.json"
    raw_provenance_path = root / _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE
    path_details_path = root / _PATH_PROJECTION_DETAILS_RELATIVE
    details_path = root / _CORE_SAVE_PROJECTION_DETAILS_RELATIVE
    for path in (ledger_path, raw_provenance_path, path_details_path):
        if path.is_symlink() or not path.is_file():
            raise invalid("The copied Path projection provenance is missing or unsafe.", details={"path": str(path)})
    if details_path.exists():
        raise invalid("The copied workspace already contains core save projection provenance.")

    try:
        raw_provenance_bytes = raw_provenance_path.read_bytes()
        raw_ledger = _read_json(raw_provenance_path, code="FINAL_CHARACTER_CORE_SAVE_PROJECTION_INVALID")
        raw_provenance_sha256 = hashlib.sha256(raw_provenance_bytes).hexdigest()
        path_details = _read_json(path_details_path, code="FINAL_CHARACTER_CORE_SAVE_PROJECTION_INVALID")
        ledger = _read_json(ledger_path, code="FINAL_CHARACTER_CORE_SAVE_PROJECTION_INVALID")
    except (OSError, FoundryError) as exc:
        if isinstance(exc, FoundryError):
            raise invalid("The copied Path projection provenance could not be read.", details={"cause": exc.code}) from exc
        raise invalid("The copied Path projection provenance could not be read.") from exc
    if not isinstance(raw_ledger, Mapping) or not isinstance(path_details, Mapping) or not isinstance(ledger, Mapping):
        raise invalid("The copied Path projection provenance or ledger is not a mapping.")
    if path_projection is not None:
        if not isinstance(path_projection, Mapping):
            raise invalid("The Path projection result is not a mapping.")
        expected_raw_sha256 = path_projection.get("modern_provenance_sha256")
        expected_details_sha256 = path_projection.get("details_sha256")
        if (
            expected_raw_sha256 != raw_provenance_sha256
            or path_projection.get("source_ledger_sha256") != raw_provenance_sha256
            or not _is_hash(expected_details_sha256)
            or sha256_file(path_details_path) != expected_details_sha256
            or path_details.get("source_ledger_sha256") != raw_provenance_sha256
        ):
            raise invalid("The core save projection is not bound to the original modern ledger bytes.")
    elif path_details.get("source_ledger_sha256") != raw_provenance_sha256:
        raise invalid("The copied Path projection details are not bound to their raw ledger provenance.")

    character = ledger.get("character")
    core_stats = ledger.get("core_stats")
    if not isinstance(character, Mapping) or not isinstance(core_stats, Mapping):
        raise invalid("The copied ledger has no character/core-stat authority.")
    path_id = character.get("path_id")
    path_name = character.get("path")
    if not isinstance(path_id, str) or not path_id.strip() or not isinstance(path_name, str) or not path_name.strip():
        raise invalid("The copied character has no concrete active Path identity.")
    if path_projection is not None and path_projection.get("path_id") != path_id:
        raise invalid("The core save projection Path differs from the authenticated Path projection.")
    if path_details.get("path_id") != path_id or path_details.get("path_name") != path_name:
        raise invalid("The copied Path details do not match the active character Path.")
    proof = _PACKET_PATH_PROOFS.get(path_id)
    if proof is None:
        raise invalid("The active Path is not one fixed canonical Path.", details={"path_id": path_id})

    path_index = _bridge_fixed_json(proof["index_path"], proof["index_sha256"])
    path_master = _bridge_fixed_json(_PACKET_PATH_MASTER_PATH, _PACKET_PATH_MASTER_SHA256)
    if not isinstance(path_index, Mapping) or not isinstance(path_master, Mapping):
        raise invalid("The fixed active Path authority is unavailable or unsafe.", details={"path_id": path_id})
    master_rows = path_master.get("paths")
    master_matches = [
        row for row in master_rows
        if isinstance(row, Mapping) and row.get("canonical_id") == path_id
    ] if isinstance(master_rows, list) else []
    if (
        len(master_matches) != 1
        or path_index.get("canonical_id") != path_id
        or path_index.get("display_name") != path_name
        or path_index.get("publication_status") != "current_canonical_player_path"
        or master_matches[0].get("display_name") != path_name
        or master_matches[0].get("index_file") != proof["index_file"]
    ):
        raise invalid("The fixed active Path identity diverges from the copied character.", details={"path_id": path_id})
    index_source = path_index.get("source")
    master_source = master_matches[0].get("source")
    if (
        not isinstance(index_source, Mapping)
        or not isinstance(master_source, Mapping)
        or index_source.get("corpus_path") != proof["corpus_path"]
        or index_source.get("sha256") != proof["corpus_sha256"]
        or master_source.get("corpus_path") != proof["corpus_path"]
        or master_source.get("sha256") != proof["corpus_sha256"]
    ):
        raise invalid("The fixed active Path source hash does not match the pinned authority.", details={"path_id": path_id})

    path_rows, projected_packet_ids = _selected_path_rows_for_compiler_consumer(
        raw_ledger=raw_ledger,
        ledger=ledger,
        path_projection=path_projection,
        path_details=path_details,
        primary_path_id=path_id,
        primary_path_name=path_name,
        character_cl=character.get("cl") if type(character.get("cl")) is int else 0,
        invalid=invalid,
    )

    path_profile = path_index.get("path_profile")
    for selected_path_row in path_rows:
        selected_path_id = selected_path_row["path_id"]
        selected_proof = _PACKET_PATH_PROOFS.get(selected_path_id)
        selected_index = path_index if selected_path_id == path_id else (
            _bridge_fixed_json(selected_proof["index_path"], selected_proof["index_sha256"])
            if isinstance(selected_proof, Mapping) else None
        )
        selected_profile = selected_index.get("path_profile") if isinstance(selected_index, Mapping) else None
        if not isinstance(selected_profile, Mapping) or selected_profile.get("saving_throw_proficiencies") != "None":
            raise invalid(
                "Every selected Path must prove the exact no-proficiency save rule.",
                details={"path_id": selected_path_id, "saving_throw_proficiencies": selected_profile.get("saving_throw_proficiencies") if isinstance(selected_profile, Mapping) else None},
            )
    key_ability = character.get("key_ability")
    key_ability_names = {
        "STR": "Strength",
        "DEX": "Dexterity",
        "CON": "Constitution",
        "INT": "Intelligence",
        "WIS": "Wisdom",
        "CHA": "Charisma",
    }
    fixed_key_ability = path_profile.get("key_ability")
    master_key_ability = master_matches[0].get("key_ability")
    fixed_options = fixed_key_ability.get("options") if isinstance(fixed_key_ability, Mapping) else None
    master_options = master_key_ability.get("options") if isinstance(master_key_ability, Mapping) else None
    if (
        path_rows[0].get("key_ability") != key_ability
        or not isinstance(fixed_options, list)
        or not isinstance(master_options, list)
        or fixed_options != master_options
        or key_ability_names.get(key_ability, key_ability) not in fixed_options
    ):
        raise invalid("The active Path key ability is not bound to fixed authority.", details={"path_id": path_id, "key_ability": key_ability})

    scores = core_stats.get("ability_scores")
    modifiers = core_stats.get("ability_modifiers")
    if (
        not isinstance(scores, Mapping)
        or not isinstance(modifiers, Mapping)
        or set(scores) != set(_CORE_SAVE_ABILITIES)
        or set(modifiers) != set(_CORE_SAVE_ABILITIES)
    ):
        raise invalid("The sealed ability score/modifier maps are incomplete or contain unknown abilities.")
    for ability in _CORE_SAVE_ABILITIES:
        score = scores.get(ability)
        modifier = modifiers.get(ability)
        if type(score) is not int or type(modifier) is not int or modifier != (score - 10) // 2:
            raise invalid(
                "The sealed ability score and modifier do not satisfy standard modifier math.",
                details={"ability": ability, "score": score, "modifier": modifier},
            )

    # The modern ledger already carries the complete skill projection, but
    # older Stage-2 writers omitted the compiler's explicit adjustment map.
    # Only project that missing map when the sealed skill arithmetic proves
    # that every adjustment is exactly zero.  A partial skill projection is
    # not a basis for inference and therefore fails closed.
    skill_projection_fields = (
        "skills",
        "skill_ability_map",
        "skill_proficiency_multipliers",
        "skill_adjustments",
        "skill_sources",
    )
    skill_projection_present = any(field in core_stats for field in skill_projection_fields)
    projected_skill_adjustments: dict[str, int] | None = None
    skill_adjustments_mode: str | None = None
    projected_skill_sources: dict[str, str] | None = None
    skill_source_provenance: dict[str, Any] | None = None
    skill_sources_mode: str | None = None
    projected_skill_source_packet_ids: dict[str, list[str]] | None = None
    skill_source_packet_ids_mode: str | None = None
    if skill_projection_present:
        skills = core_stats.get("skills")
        skill_ability_map = core_stats.get("skill_ability_map")
        skill_multipliers = core_stats.get("skill_proficiency_multipliers")
        if not isinstance(skills, Mapping) or not isinstance(skill_ability_map, Mapping) or not isinstance(skill_multipliers, Mapping):
            raise invalid("The sealed skill projection is incomplete.")
        skill_names = set(skills)
        if skill_names != set(skill_ability_map) or skill_names != set(skill_multipliers):
            raise invalid("The sealed skill projection maps do not share one exact keyset.")
        if any(not isinstance(name, str) or not name.strip() for name in skill_names):
            raise invalid("The sealed skill projection contains an invalid skill name.")
        if any(type(value) is not int for value in skills.values()):
            raise invalid("The sealed skill values must be integers.")
        if any(ability not in _CORE_SAVE_ABILITIES for ability in skill_ability_map.values()):
            raise invalid("The sealed skill ability map contains an unknown ability.")
        if any(type(multiplier) is not int or multiplier not in {0, 1, 2} for multiplier in skill_multipliers.values()):
            raise invalid("The sealed skill proficiency multipliers are invalid.")
        pb = character.get("pb")
        if type(pb) is not int:
            raise invalid("The sealed character proficiency bonus is required for skill adjustment projection.")
        if "skill_adjustments" in core_stats:
            existing_skill_adjustments = core_stats.get("skill_adjustments")
            if not isinstance(existing_skill_adjustments, Mapping) or set(existing_skill_adjustments) != skill_names:
                raise invalid("The existing skill adjustment map does not match the sealed skill keyset.")
            if any(type(value) is not int for value in existing_skill_adjustments.values()):
                raise invalid("The existing skill adjustment values must be integers.")
            projected_skill_adjustments = {name: int(existing_skill_adjustments[name]) for name in skill_names}
            skill_adjustments_mode = "preserved_existing"
        else:
            projected_skill_adjustments = {name: 0 for name in skill_names}
            skill_adjustments_mode = "source_backed_explicit_none"
        for name in skill_names:
            ability = skill_ability_map[name]
            base_value = modifiers[ability] + pb * skill_multipliers[name]
            expected_value = base_value + projected_skill_adjustments[name]
            if skills[name] != expected_value:
                raise invalid(
                    "The sealed skill value is inconsistent with its source-backed adjustment map.",
                    details={"skill": name},
                )
        if skill_adjustments_mode == "source_backed_explicit_none" and any(projected_skill_adjustments.values()):
            raise invalid("A missing skill adjustment map may only be projected when sealed arithmetic proves zero.")

        skill_sources = core_stats.get("skill_sources")
        if not isinstance(skill_sources, Mapping) or set(skill_sources) != skill_names:
            raise invalid("The sealed skill source map does not match the sealed skill keyset.")
        raw_ledger = _read_json(raw_provenance_path, code="FINAL_CHARACTER_CORE_SAVE_PROJECTION_INVALID")
        raw_core_stats = raw_ledger.get("core_stats") if isinstance(raw_ledger, Mapping) else None
        if not isinstance(raw_core_stats, Mapping) or raw_core_stats.get("skill_sources") != skill_sources:
            raise invalid("The sealed skill source map diverges from raw modern provenance.")
        projected_skill_sources = {}
        source_values_are_structured = False
        for name in skill_names:
            source_value = skill_sources[name]
            if isinstance(source_value, str):
                if not source_value.strip():
                    raise invalid("The sealed skill source text must be nonblank.")
                projected_skill_sources[name] = source_value
            elif isinstance(source_value, list):
                if not source_value or any(type(item) is not str or not item.strip() or item != item.strip() for item in source_value):
                    raise invalid("The sealed structured skill source must be a nonempty list of clean source identifiers.")
                projected_skill_sources[name] = "; ".join(source_value)
                source_values_are_structured = True
            else:
                raise invalid("The sealed skill source must be text or a source-identifier list.")
        if source_values_are_structured:
            skill_source_provenance = deepcopy(dict(skill_sources))
            skill_sources_mode = "source_backed_identifier_projection"
        else:
            skill_sources_mode = "preserved_text"
            if "skill_source_provenance" in core_stats:
                skill_source_provenance = deepcopy(dict(skill_sources))
                skill_sources_mode = "preserved_text_with_provenance"
        if "skill_source_provenance" in core_stats and core_stats.get("skill_source_provenance") != dict(skill_sources):
            raise invalid("The retained skill source provenance diverges from the sealed source map.")

        source_packet_input = core_stats.get("skill_source_packet_ids")
        if source_packet_input is not None:
            if not isinstance(source_packet_input, Mapping) or set(source_packet_input) != skill_names:
                raise invalid("The sealed skill packet-source map does not match the sealed skill keyset.")
            for skill_name, refs in source_packet_input.items():
                if (
                    not isinstance(refs, list)
                    or any(not isinstance(ref, str) or not ref.strip() or ref != ref.strip() for ref in refs)
                    or len(refs) != len(set(refs))
                ):
                    raise invalid("The sealed skill packet-source values are malformed.", details={"skill": skill_name})

        registry_path = root / "Command_2/Rules_Selection_Packets.json"
        if registry_path.is_symlink() or not registry_path.is_file():
            raise invalid("The sealed skill packet-source registry is missing or unsafe.")
        registry = _read_json(registry_path, code="FINAL_CHARACTER_CORE_SAVE_PROJECTION_INVALID")
        packet_rows = registry.get("packets") if isinstance(registry, Mapping) else None
        if not isinstance(packet_rows, list):
            raise invalid("The sealed skill packet-source registry has no packet list.")
        packet_by_id: dict[str, Mapping[str, Any]] = {}
        packets_by_record: dict[str, list[Mapping[str, Any]]] = {}
        for packet in packet_rows:
            if not isinstance(packet, Mapping) or not isinstance(packet.get("packet_id"), str) or not packet.get("packet_id"):
                raise invalid("A sealed skill packet-source row has no stable packet ID.")
            packet_id = packet["packet_id"]
            if packet_id in packet_by_id:
                raise invalid("The sealed skill packet-source registry contains duplicate packet IDs.", details={"packet_id": packet_id})
            record_id = packet.get("record_id")
            if isinstance(record_id, str) and record_id.strip():
                packets_by_record.setdefault(record_id, []).append(packet)
            packet_by_id[packet_id] = packet

        def validated_packet_ref(packet: Mapping[str, Any], *, record_id: str) -> str:
            packet_id = packet.get("packet_id")
            evidence = packet.get("source_evidence")
            evidence_row = evidence[0] if isinstance(evidence, list) and len(evidence) == 1 and isinstance(evidence[0], Mapping) else None
            if (
                packet.get("record_id") != record_id
                or not isinstance(packet_id, str)
                or not packet_id.strip()
                or not isinstance(packet.get("advancement_kind"), str)
                or not packet.get("advancement_kind").strip()
                or evidence_row is None
                or not isinstance(evidence_row.get("source_path"), str)
                or not evidence_row.get("source_path").strip()
                or not _is_hash(evidence_row.get("source_hash"))
                or not isinstance(evidence_row.get("source_anchor"), str)
                or not evidence_row.get("source_anchor").strip()
            ):
                raise invalid("A skill source record has incomplete packet evidence.", details={"record_id": record_id})
            return packet_id

        projected_skill_source_packet_ids = {}
        for skill_name in sorted(skill_names):
            source_value = skill_sources[skill_name]
            refs: list[str]
            if isinstance(source_value, list):
                if any(not isinstance(record_id, str) or not record_id.strip() or record_id != record_id.strip() for record_id in source_value):
                    raise invalid("A skill source record ID is malformed.", details={"skill": skill_name})
                if len(source_value) != len(set(source_value)):
                    raise invalid("A skill source record list contains duplicates.", details={"skill": skill_name})
                refs = []
                for record_id in source_value:
                    candidates = packets_by_record.get(record_id, [])
                    if len(candidates) != 1:
                        raise invalid("A skill source record does not bind one unique sealed packet.", details={"skill": skill_name, "record_id": record_id, "matches": len(candidates)})
                    refs.append(validated_packet_ref(candidates[0], record_id=record_id))
                skill_source_packet_ids_mode = "derived_from_source_record_ids"
            else:
                supplied_refs = source_packet_input.get(skill_name) if isinstance(source_packet_input, Mapping) else None
                refs = list(supplied_refs) if isinstance(supplied_refs, list) else []
                for packet_id in refs:
                    packet = packet_by_id.get(packet_id)
                    if packet is None:
                        raise invalid("A supplied skill packet source is not present in the sealed registry.", details={"skill": skill_name})
                    record_id = packet.get("record_id")
                    if not isinstance(record_id, str) or not record_id.strip():
                        raise invalid("A supplied skill packet source has no authenticated record ID.", details={"skill": skill_name})
                    validated_packet_ref(packet, record_id=record_id)
                if not refs and skill_multipliers[skill_name] > 0:
                    raise invalid("A proficient skill has no source-backed packet reference.", details={"skill": skill_name})
                skill_source_packet_ids_mode = "preserved_existing_packet_ids"
            if isinstance(source_packet_input, Mapping) and source_packet_input.get(skill_name) != refs:
                raise invalid("The supplied skill packet sources diverge from sealed source records.", details={"skill": skill_name})
            projected_skill_source_packet_ids[skill_name] = refs

    expected_saves = {ability: modifiers[ability] for ability in _CORE_SAVE_ABILITIES}
    expected_adjustments = {ability: 0 for ability in _CORE_SAVE_ABILITIES}
    expected_sources: dict[str, Any] = {}
    existing_fields = {
        "saving_throws": expected_saves,
        "saving_throw_adjustments": expected_adjustments,
        "saving_throw_adjustment_source_packet_ids": expected_sources,
    }
    if projected_skill_adjustments is not None:
        existing_fields["skill_adjustments"] = projected_skill_adjustments
    if projected_skill_source_packet_ids is not None:
        existing_fields["skill_source_packet_ids"] = projected_skill_source_packet_ids
    for field, expected in existing_fields.items():
        if field in core_stats and core_stats.get(field) != expected:
            raise invalid(
                "An existing core save projection conflicts with the source-backed no-proficiency rule.",
                details={"field": field},
            )

    projected_ledger = deepcopy(dict(ledger))
    projected_core_stats = deepcopy(dict(core_stats))
    projected_core_stats.update({field: deepcopy(value) for field, value in existing_fields.items()})
    if projected_skill_sources is not None:
        projected_core_stats["skill_sources"] = projected_skill_sources
    if skill_source_provenance is not None:
        projected_core_stats["skill_source_provenance"] = skill_source_provenance
    projected_ledger["core_stats"] = projected_core_stats
    provenance = {
        "schema_version": "TianxiaFoundry.FinalCharacterCoreSaveProjectionProvenance.v1",
        "source_ledger_path": "Build/Character_Master_Ledger.json",
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_provenance_sha256,
        "path_details_path": _PATH_PROJECTION_DETAILS_RELATIVE,
        "path_details_sha256": sha256_file(path_details_path),
        "path_id": path_id,
        "path_name": path_name,
        "path_index_path": proof["index_path"],
        "path_index_sha256": proof["index_sha256"],
        "path_source_corpus_path": proof["corpus_path"],
        "path_source_corpus_sha256": proof["corpus_sha256"],
        "saving_throw_proficiencies": "None",
        "ability_scores_sha256": sha256_json(dict(scores)),
        "ability_modifiers_sha256": sha256_json(dict(modifiers)),
        "saving_throws": expected_saves,
        "saving_throw_adjustments": expected_adjustments,
        "saving_throw_adjustment_source_packet_ids": expected_sources,
    }
    if projected_skill_adjustments is not None:
        provenance["skill_adjustments"] = projected_skill_adjustments
        provenance["skill_adjustments_sha256"] = sha256_json(projected_skill_adjustments)
        provenance["skill_adjustments_mode"] = skill_adjustments_mode
    if projected_skill_sources is not None:
        provenance["skill_sources"] = projected_skill_sources
        provenance["skill_sources_sha256"] = sha256_json(projected_skill_sources)
        provenance["skill_sources_mode"] = skill_sources_mode
    if projected_skill_source_packet_ids is not None:
        provenance["skill_source_packet_ids"] = projected_skill_source_packet_ids
        provenance["skill_source_packet_ids_sha256"] = sha256_json(projected_skill_source_packet_ids)
        provenance["skill_source_packet_ids_mode"] = skill_source_packet_ids_mode
    if skill_source_provenance is not None:
        provenance["skill_source_provenance"] = skill_source_provenance
        provenance["skill_source_provenance_sha256"] = sha256_json(skill_source_provenance)
    _write_json(details_path, provenance)
    _write_json(ledger_path, projected_ledger)
    reread = _read_json(ledger_path, code="FINAL_CHARACTER_CORE_SAVE_PROJECTION_INVALID")
    if reread != projected_ledger or raw_provenance_path.read_bytes() != raw_provenance_bytes:
        raise invalid("The compiler core save projection could not be read back exactly.")
    result = {
        "schema_version": provenance["schema_version"],
        "source_ledger_path": provenance["source_ledger_path"],
        "source_ledger_sha256": raw_provenance_sha256,
        "modern_provenance_path": _PATH_PROJECTION_RAW_PROVENANCE_RELATIVE,
        "modern_provenance_sha256": raw_provenance_sha256,
        "details_path": _CORE_SAVE_PROJECTION_DETAILS_RELATIVE,
        "details_sha256": sha256_file(details_path),
        "path_id": path_id,
        "saving_throw_proficiencies": "None",
        "saving_throws": expected_saves,
        "saving_throw_adjustments": expected_adjustments,
        "saving_throw_adjustment_source_packet_ids": expected_sources,
    }
    if projected_skill_adjustments is not None:
        result["skill_adjustments"] = projected_skill_adjustments
        result["skill_adjustments_mode"] = skill_adjustments_mode
    if projected_skill_sources is not None:
        result["skill_sources"] = projected_skill_sources
        result["skill_sources_mode"] = skill_sources_mode
    if projected_skill_source_packet_ids is not None:
        result["skill_source_packet_ids"] = projected_skill_source_packet_ids
        result["skill_source_packet_ids_mode"] = skill_source_packet_ids_mode
    if skill_source_provenance is not None:
        result["skill_source_provenance"] = skill_source_provenance
    return result


def _bridge_rules_packet_registry(workspace: Path, corpus: Path) -> dict[str, Any]:
    """Snapshot the modern registry and emit a compiler-native projection.

    The modern registry is retained byte-for-byte as provenance.  The file
    consumed by the compiler is a strictly smaller projection of referenced
    packets whose authority and excerpt are proven by the pinned corpus.  A
    non-corpus packet is never silently relabelled; it is reported as a typed
    blocker instead.
    """

    registry_path = workspace / "Command_2/Rules_Selection_Packets.json"
    if registry_path.is_symlink() or not registry_path.is_file():
        raise _error("FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID", "The modern Stage-2 packet registry is missing or unsafe.", details={"path": str(registry_path)})
    raw_bytes = registry_path.read_bytes()
    raw_registry = _read_json(registry_path, code="FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID")
    if not isinstance(raw_registry, Mapping) or not isinstance(raw_registry.get("packets"), list):
        raise _error("FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID", "The modern Stage-2 packet registry has no packet list.")

    # The copied workspace carries the same modern packet projection under
    # Build for downstream display/package consumers.  It is a second input
    # authority, not a free-standing source of compiler rules: when present,
    # authenticate its complete parsed value against Command_2 before either
    # copy is replaced.  The raw bytes of both locations are retained below as
    # separate provenance, so a formatting difference cannot hide a semantic
    # divergence or discard the modern record set.
    build_registry_path = workspace / "Build/Rules_Selection_Packets.json"
    build_raw_bytes: bytes | None = None
    build_registry: Mapping[str, Any] | None = None
    if build_registry_path.is_symlink() or build_registry_path.exists():
        if build_registry_path.is_symlink() or not build_registry_path.is_file():
            raise _error(
                "FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID",
                "The Build packet registry is missing or unsafe.",
                details={"path": str(build_registry_path)},
            )
        build_raw_bytes = build_registry_path.read_bytes()
        parsed_build_registry = _read_json(build_registry_path, code="FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID")
        if not isinstance(parsed_build_registry, Mapping) or not isinstance(parsed_build_registry.get("packets"), list):
            raise _error("FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID", "The Build packet registry has no packet list.")
        build_registry = parsed_build_registry
        if build_registry != raw_registry:
            raise _error(
                "FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID",
                "The Build and Command_2 modern packet registries diverge.",
                details={
                    "command2_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                    "build_sha256": hashlib.sha256(build_raw_bytes).hexdigest(),
                },
            )
    provenance_path = workspace / "Command_2/Rules_Selection_Packets.Modern_Provenance.json"
    _atomic_write_bytes(provenance_path, raw_bytes)
    modern_sha256 = sha256_file(provenance_path)
    build_provenance_path: Path | None = None
    build_modern_sha256: str | None = None
    if build_raw_bytes is not None:
        build_provenance_path = workspace / "Build/Rules_Selection_Packets.Modern_Provenance.json"
        _atomic_write_bytes(build_provenance_path, build_raw_bytes)
        build_modern_sha256 = sha256_file(build_provenance_path)
    refs, locations, reference_contexts = _modern_packet_reference_contexts(workspace)
    by_id: dict[str, Mapping[str, Any]] = {}
    for index, packet in enumerate(raw_registry["packets"]):
        if not isinstance(packet, Mapping) or not isinstance(packet.get("packet_id"), str) or not packet["packet_id"].strip():
            raise _error("FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID", "A modern Stage-2 packet has no stable packet ID.", details={"index": index})
        packet_id = packet["packet_id"].strip()
        if packet_id in by_id:
            raise _error("FINAL_CHARACTER_PACKET_BRIDGE_INPUT_INVALID", "The modern Stage-2 packet registry contains duplicate packet IDs.", details={"packet_id": packet_id})
        by_id[packet_id] = packet
    missing = sorted(refs - set(by_id))
    if missing:
        raise _error("FINAL_CHARACTER_PACKET_BRIDGE_UNRESOLVED", "The executable ledger references packet IDs absent from the modern registry.", details={"missing_packet_ids": missing, "references": locations})
    active, corpus_texts = _corpus_active_texts(corpus)
    native: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for packet_id in sorted(refs):
        packet = by_id[packet_id]
        supplied_authority = packet.get("authority")
        if supplied_authority == "user_directive":
            native_packet, reason, reason_details = _bridge_user_directive_packet(
                packet,
                packet_id=packet_id,
                reference_contexts=reference_contexts,
            )
            if native_packet is None:
                unresolved.append({
                    "packet_id": packet_id,
                    "record_id": packet.get("record_id"),
                    "reason": reason,
                    **reason_details,
                    "referenced_at": locations.get(packet_id, []),
                })
                break
            native.append(native_packet)
            continue
        evidence = packet.get("source_evidence")
        evidence_row = evidence[0] if isinstance(evidence, list) and len(evidence) == 1 and isinstance(evidence[0], Mapping) else {}
        source_hash = evidence_row.get("source_hash")
        original_path = evidence_row.get("source_path")
        source_path: str | None = None
        source_text: str | None = None
        anchor = evidence_row.get("source_anchor")
        evidence_verified = False
        modern_family, modern_proof = _bridge_modern_packet_source(packet, corpus=corpus, active=active, corpus_texts=corpus_texts)
        if modern_family:
            # Recognized modern authority families never fall through to the
            # legacy hash/substring compatibility path.  A missing proof is a
            # typed unresolved compiler bridge, not a reason to guess.
            if modern_proof is not None:
                source_path = modern_proof.get("source_path")
                source_text = modern_proof.get("source_text")
                evidence_verified = modern_proof.get("source_evidence_verified") is True
        else:
            evidence_verified = _verify_modern_source_evidence(original_path, source_hash)
            # Source hashes from modern records identify complete vendor files.
            # A hash match to an active corpus member is stronger than trusting
            # the caller-provided legacy path spelling.
            if isinstance(source_hash, str) and _is_hash(source_hash):
                matches = [path for path, text in corpus_texts.items() if _sha256_text(text) == source_hash]
                if len(matches) == 1:
                    source_path = matches[0]
                    source_text = _source_excerpt(corpus_texts[source_path], packet)
                    evidence_verified = True
            # A few modern records point at a retired vendor path whose bytes
            # were incorporated into a differently named active corpus member.
            # The stable heading/record anchor is the compatibility proof; we
            # still bind the emitted packet to the active member's exact bytes.
            if source_text is None and isinstance(original_path, str) and original_path.endswith("Origin_Insights_v0_4_READABILITY_SELF_CONTAINED.md"):
                candidate = "Needed/Tianxia_PHB_Origin_Insights_v0_4_READABILITY_SELF_CONTAINED.md"
                if evidence_verified and candidate in active and candidate in corpus_texts:
                    source_path = candidate
                    source_text = _source_excerpt(corpus_texts[candidate], packet)
            # Retain the established bounded subpath compatibility projection.
            if source_text is None and isinstance(anchor, str) and anchor.startswith("subpath:"):
                candidate = "Canonical/Paths/Body/Tianxia_Body_Refining_Subpath_Compendium_R8.md"
                if evidence_verified and candidate in active and candidate in corpus_texts:
                    source_path = candidate
                    source_text = _path_compatibility_excerpt(corpus_texts[candidate], packet)
        if source_path is None or source_text is None:
            unresolved.append({
                "packet_id": packet_id,
                "record_id": packet.get("record_id"),
                "source_path": original_path,
                "source_hash": source_hash,
                "source_anchor": evidence_row.get("source_anchor"),
                "reason": "no exact active corpus excerpt or proven compatible canonical packet",
                "referenced_at": locations.get(packet_id, []),
            })
            break
        # Compiler text() strips before hashing; store the exact stripped
        # excerpt and its corresponding digest.
        source_text = source_text.strip()
        derived_source_sha256 = _sha256_text(source_text)
        supplied_source_path = packet.get("source_path")
        supplied_source_text = packet.get("source_text")
        supplied_source_text_sha256 = packet.get("source_text_sha256")
        if supplied_authority not in (None, "tianxia_rules"):
            unresolved.append({"packet_id": packet_id, "record_id": packet.get("record_id"), "reason": "modern authority conflicts with the source-backed canonical classification", "supplied_authority": supplied_authority})
            break
        if supplied_source_path not in (None, source_path) or supplied_source_text not in (None, source_text) or supplied_source_text_sha256 not in (None, derived_source_sha256):
            unresolved.append({
                "packet_id": packet_id,
                "record_id": packet.get("record_id"),
                "reason": "modern registry contains a forged compiler source path, excerpt, or digest",
                "source_path": supplied_source_path,
                "source_text_sha256": supplied_source_text_sha256,
            })
            break
        name = packet.get("display_name") or packet.get("record_id")
        if not isinstance(name, str) or not name.strip():
            unresolved.append({"packet_id": packet_id, "record_id": packet.get("record_id"), "reason": "missing display name"})
            break
        native_packet = {
            "packet_id": packet_id,
            "name": name.strip(),
            "authority": "tianxia_rules",
            "source_path": source_path,
            "source_text": source_text,
            "source_text_sha256": derived_source_sha256,
            "source_section": evidence_row.get("source_anchor", ""),
            # Preserve source classification for consumers without promoting
            # modern registry prose to executable authority.
            "source_classification": "Background-Origin Insight" if str(packet.get("record_id", "")).startswith("tianxia.origin_insight.") else packet.get("advancement_kind"),
            "modern_record_id": packet.get("record_id"),
            "modern_source_path": original_path,
            "modern_source_sha256": source_hash,
            "source_evidence_verified": evidence_verified,
        }
        native.append(native_packet)
    if unresolved:
        raise _error(
            "FINAL_CHARACTER_PACKET_BRIDGE_UNRESOLVED",
            "At least one executable packet lacks a source-backed compiler-native authority projection.",
            details={
                "unresolved": unresolved,
                "referenced_packet_ids": sorted(refs),
                "modern_registry_sha256": modern_sha256,
                "corpus_path": str(corpus),
                "corpus_sha256": _corpus_pin(corpus),
                "compiler_allowed_authorities": ["tianxia_rules", "user_directive"],
                "policy": "No original_design or inspiration_source authority may authorize production mechanics without a source-backed user directive.",
            },
        )
    native_registry = {"schema_version": "HF05ZVK-R1H.CompilerRulesSelectionPackets.v1", "packets": native}
    _write_json(registry_path, native_registry)
    native_sha256 = sha256_file(registry_path)
    build_native_sha256: str | None = None
    if build_registry_path.is_file() and not build_registry_path.is_symlink():
        # Build and Command_2 receive the identical compiler-native bytes.  A
        # compiler/package consumer cannot accidentally validate the raw
        # modern rows (including an unproven starting-state packet) after this
        # boundary, while the corresponding Modern_Provenance file preserves
        # the complete source registry for audit.
        _write_json(build_registry_path, native_registry)
        build_native_sha256 = sha256_file(build_registry_path)
    result = {
        "modern_provenance_path": provenance_path.relative_to(workspace).as_posix(),
        "modern_provenance_sha256": modern_sha256,
        "native_registry_sha256": native_sha256,
        "native_registry_packet_ids": sorted(refs),
        "native_registry_packet_count": len(native),
        "pruned_packet_count": len(by_id) - len(native),
        "pruned_packet_ids": sorted(set(by_id) - refs),
        "source_backed": True,
    }
    if build_provenance_path is not None and build_modern_sha256 is not None and build_native_sha256 is not None:
        result.update({
            "build_modern_provenance_path": build_provenance_path.relative_to(workspace).as_posix(),
            "build_modern_provenance_sha256": build_modern_sha256,
            "build_native_registry_path": build_registry_path.relative_to(workspace).as_posix(),
            "build_native_registry_sha256": build_native_sha256,
        })
    return result


def _receipt_path(output_root: Path, materialization_id: str) -> Path:
    return output_root / materialization_id / FINAL_CHARACTER_RECEIPT_NAME


def _review_record_id(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"final-review\.[0-9a-f]{64}", value)
    ):
        raise _error(
            "FINAL_CHARACTER_REVIEW_RECORD_INVALID",
            "The final-character review record ID is not a valid content address.",
            details={"field": "review_record_id"},
        )
    return value


def _review_record_integrity_projection(
    *,
    record_id: str,
    binding: Mapping[str, Any],
    binding_sha256: str,
    approval: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": FINAL_CHARACTER_REVIEW_RECORD_SCHEMA,
        "record_id": record_id,
        "binding": deepcopy(dict(binding)),
        "binding_sha256": binding_sha256,
        "approval": deepcopy(dict(approval)),
    }


def _review_record_core(
    *,
    record_id: str,
    binding: Mapping[str, Any],
    binding_sha256: str,
    approval: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": FINAL_CHARACTER_REVIEW_RECORD_SCHEMA,
        "record_id": record_id,
        "binding": deepcopy(dict(binding)),
        "binding_sha256": binding_sha256,
        "approval": deepcopy(dict(approval)),
    }


def _validate_review_approval(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _REVIEW_APPROVAL_KEYS or value.get("decision") != "approved":
        raise _error(
            "FINAL_CHARACTER_REVIEW_RECORD_INVALID",
            "The final-character review decision is not an explicit approval record.",
        )
    reviewer_id = _reviewed_binding_identifier(value.get("reviewer_id"), field="approval.reviewer_id")
    evidence_id = _reviewed_binding_identifier(value.get("evidence_id"), field="approval.evidence_id")
    return {"decision": "approved", "reviewer_id": reviewer_id, "evidence_id": evidence_id}


def _validate_review_record(value: Any, *, requested_record_id: str | None = None) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _REVIEW_RECORD_KEYS:
        raise _error(
            "FINAL_CHARACTER_REVIEW_RECORD_INVALID",
            "The final-character review record is incomplete or contains unsupported fields.",
        )
    record_id = _review_record_id(value.get("record_id"))
    if requested_record_id is not None and record_id != requested_record_id:
        raise _error(
            "FINAL_CHARACTER_REVIEW_RECORD_INVALID",
            "The final-character review record ID does not match its requested path.",
        )
    binding = _validate_reviewed_binding_envelope(value.get("binding"))
    if value.get("binding_sha256") != binding.get("binding_sha256"):
        raise _error(
            "FINAL_CHARACTER_REVIEW_RECORD_INVALID",
            "The final-character review record binding hash is inconsistent.",
        )
    approval = _validate_review_approval(value.get("approval"))
    expected_record_id = FINAL_CHARACTER_REVIEW_RECORD_PREFIX + sha256_json({
        "schema_version": FINAL_CHARACTER_REVIEW_RECORD_SCHEMA,
        "binding": binding,
        "binding_sha256": binding["binding_sha256"],
        "approval": approval,
    })
    if record_id != expected_record_id:
        raise _error(
            "FINAL_CHARACTER_REVIEW_RECORD_INVALID",
            "The final-character review record ID is not the content address of its approval payload.",
            details={"expected": expected_record_id, "actual": record_id},
        )
    core = _review_record_core(
        record_id=record_id,
        binding=binding,
        binding_sha256=str(value.get("binding_sha256")),
        approval=approval,
    )
    integrity = value.get("integrity")
    if not isinstance(integrity, Mapping) or set(integrity) != _INTEGRITY_ENVELOPE_KEYS:
        raise _error(
            "FINAL_CHARACTER_REVIEW_RECORD_INVALID",
            "The final-character review record integrity envelope is incomplete.",
        )
    body = {**core, "integrity": deepcopy(dict(integrity))}
    if value.get("record_sha256") != sha256_json(body):
        raise _error(
            "FINAL_CHARACTER_REVIEW_RECORD_INVALID",
            "The final-character review record content hash is invalid.",
        )
    return {
        **core,
        "integrity": deepcopy(dict(integrity)),
        "record_sha256": value.get("record_sha256"),
    }


def _ensure_review_root(
    path: Path,
    *,
    create: bool = True,
    expected_identity: tuple[int, int] | None = None,
    expected_present: bool | None = None,
) -> Path:
    """Resolve one fixed, owner-controlled review-store root without links."""

    path = Path(path)
    open_create = create if expected_present is None else False
    try:
        authority = _open_fixed_directory(path, create=open_create, mode=0o700)
    except FileNotFoundError as exc:
        if expected_present is True or expected_present is False:
            raise _error(
                "FINAL_CHARACTER_REVIEW_STORE_CHANGED",
                "The configured review store changed before it could be bound.",
                details={"path": str(path)},
                status_code=409,
            ) from exc
        raise _error(
            "FINAL_CHARACTER_REVIEW_RECORD_NOT_FOUND",
            "The configured final-character review record store does not exist.",
            details={"path": str(path)},
            status_code=409,
        ) from exc
    except OSError as exc:
        raise _error(
            "FINAL_CHARACTER_REVIEW_STORE_INVALID",
            "The configured review store cannot be created or inspected safely.",
            details={"path": str(path)},
        ) from exc
    try:
        if expected_present is False or (expected_identity is not None and authority.identity != expected_identity):
            raise _error(
                "FINAL_CHARACTER_REVIEW_STORE_CHANGED",
                "The configured review store changed before it could be bound.",
                details={"path": str(path)},
                status_code=409,
            )
        info = os.fstat(authority.fd)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise _error(
                "FINAL_CHARACTER_REVIEW_STORE_INVALID",
                "The configured review store must be a private owner-controlled regular directory.",
                details={"path": str(path), "mode": oct(stat.S_IMODE(info.st_mode))},
            )
        authority.assert_current()
        return authority.path
    except FoundryError:
        raise
    except OSError as exc:
        raise _error(
            "FINAL_CHARACTER_REVIEW_STORE_INVALID",
            "The configured review store changed during validation.",
            details={"path": str(path)},
        ) from exc
    finally:
        authority.close()


class FinalCharacterReviewAuthority:
    """Read-only loader for explicit server-controlled finalization approvals.

    Issuance is intentionally implemented by ``FinalCharacterReviewIssuer``
    below.  Keeping this object load-only means a materializer-facing caller
    cannot turn a path and a self-consistent HMAC projection into approval.
    """

    def __init__(
        self,
        review_root: Path | str,
        integrity: IntegrityService,
        *,
        expected_identity: tuple[int, int] | None = None,
        expected_present: bool | None = None,
    ):
        if not isinstance(integrity, IntegrityService):
            raise _error(
                "FINAL_CHARACTER_REVIEW_AUTHORITY_INVALID",
                "A final-character review authority requires the server IntegrityService.",
                status_code=500,
            )
        review_root_path = Path(review_root)
        if not review_root_path.is_absolute():
            raise _error(
                "FINAL_CHARACTER_REVIEW_AUTHORITY_INVALID",
                "A final-character review authority requires an absolute fixed review-store root.",
                status_code=500,
            )
        self._review_root = review_root_path
        self._integrity = integrity
        self._review_root_identity: tuple[int, int] | None = None
        self._expected_review_root_identity = expected_identity
        self._expected_review_root_present = expected_present
        try:
            probe = _open_fixed_directory(review_root_path, create=False)
        except FileNotFoundError as exc:
            if expected_present is True:
                raise _error(
                    "FINAL_CHARACTER_REVIEW_STORE_CHANGED",
                    "The configured review store changed before its authority was established.",
                    details={"path": str(review_root_path)},
                    status_code=409,
                ) from exc
            pass
        except OSError:
            # Defer the typed error until the operation which needs the
            # authority; construction itself must stay read-only.
            pass
        else:
            try:
                self._assert_expected_root(probe)
                self._review_root_identity = probe.identity
            finally:
                probe.close()

    @property
    def review_root(self) -> Path:
        return self._review_root

    def _assert_expected_root(self, authority: _FixedDirectoryAuthority) -> None:
        if self._expected_review_root_present is False or (
            self._expected_review_root_identity is not None
            and authority.identity != self._expected_review_root_identity
        ):
            raise _error(
                "FINAL_CHARACTER_REVIEW_STORE_CHANGED",
                "The configured review store changed after its workflow binding was established.",
                details={"path": str(self._review_root)},
                status_code=409,
            )

    def _open_root(self, *, create: bool) -> tuple[Path, int]:
        open_create = create if self._expected_review_root_present is None else False
        try:
            authority = _open_fixed_directory(self._review_root, create=open_create, mode=0o700)
        except FileNotFoundError as exc:
            if self._expected_review_root_present is True:
                raise _error(
                    "FINAL_CHARACTER_REVIEW_STORE_CHANGED",
                    "The configured review store changed before its workflow binding was opened.",
                    details={"path": str(self._review_root)},
                    status_code=409,
                ) from exc
            raise _error(
                "FINAL_CHARACTER_REVIEW_RECORD_NOT_FOUND",
                "The configured final-character review record store does not exist.",
                details={"path": str(self._review_root)},
                status_code=409,
            ) from exc
        except OSError as exc:
            raise _error(
                "FINAL_CHARACTER_REVIEW_STORE_INVALID",
                "The configured review store cannot be opened safely.",
                details={"path": str(self._review_root)},
            ) from exc
        root = authority.path
        descriptor = authority.fd
        try:
            self._assert_expected_root(authority)
            actual = os.fstat(descriptor)
            if (
                not stat.S_ISDIR(actual.st_mode)
                or actual.st_uid != os.getuid()
                or stat.S_IMODE(actual.st_mode) & 0o077
            ):
                raise _error(
                    "FINAL_CHARACTER_REVIEW_STORE_INVALID",
                    "The configured review store is not private and owner-controlled.",
                    details={"path": str(root)},
                )
            if self._review_root_identity is None:
                self._review_root_identity = (actual.st_dev, actual.st_ino)
            elif self._review_root_identity != (actual.st_dev, actual.st_ino):
                raise _error(
                    "FINAL_CHARACTER_REVIEW_STORE_CHANGED",
                    "The configured review store changed after its authority was established.",
                    details={"path": str(root)},
                )
            authority.assert_current()
        except FoundryError:
            authority.close()
            raise
        except OSError as exc:
            authority.close()
            raise _error(
                "FINAL_CHARACTER_REVIEW_STORE_INVALID",
                "The configured review store could not be bound to its no-follow descriptor.",
                details={"path": str(root)},
            ) from exc
        return root, descriptor

    def load_record(self, record_id: str) -> dict[str, Any]:
        record_id = _review_record_id(record_id)
        root, descriptor = self._open_root(create=False)
        try:
            try:
                fd = os.open(record_id + ".json", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=descriptor)
            except FileNotFoundError as exc:
                raise _error(
                    "FINAL_CHARACTER_REVIEW_RECORD_NOT_FOUND",
                    "The requested final-character review record does not exist.",
                    details={"record_id": record_id},
                    status_code=409,
                ) from exc
            except OSError as exc:
                raise _error(
                    "FINAL_CHARACTER_REVIEW_RECORD_INVALID",
                    "The requested final-character review record cannot be opened safely.",
                    details={"record_id": record_id},
                    status_code=409,
                ) from exc
            record_fd = fd
            try:
                info = os.fstat(record_fd)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) & 0o077
                ):
                    raise _error(
                        "FINAL_CHARACTER_REVIEW_RECORD_INVALID",
                        "The requested final-character review record is not a private owner-controlled regular file.",
                        details={"record_id": record_id, "mode": oct(stat.S_IMODE(info.st_mode))},
                        status_code=409,
                    )
                with os.fdopen(record_fd, "rb") as handle:
                    record_fd = -1
                    raw = handle.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise _error(
                        "FINAL_CHARACTER_REVIEW_RECORD_INVALID",
                        "The requested final-character review record exceeds the bounded size limit.",
                        details={"record_id": record_id},
                        status_code=409,
                    )
            except FoundryError:
                raise
            except (OSError, UnicodeError) as exc:
                raise _error(
                    "FINAL_CHARACTER_REVIEW_RECORD_INVALID",
                    "The requested final-character review record cannot be read safely.",
                    details={"record_id": record_id},
                    status_code=409,
                ) from exc
            finally:
                if record_fd >= 0:
                    os.close(record_fd)
        finally:
            os.close(descriptor)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise _error(
                "FINAL_CHARACTER_REVIEW_RECORD_INVALID",
                "The requested final-character review record is malformed JSON.",
                details={"record_id": record_id},
                status_code=409,
            ) from exc
        try:
            normalized = _validate_review_record(value, requested_record_id=record_id)
        except FoundryError as exc:
            raise _error(
                "FINAL_CHARACTER_REVIEW_RECORD_INVALID",
                "The requested final-character review record failed structural validation.",
                details={"cause": exc.code, "record_id": record_id},
                status_code=409,
            ) from exc
        try:
            self._integrity.verify(
                FINAL_CHARACTER_REVIEW_RECORD_DOMAIN,
                _review_record_integrity_projection(
                    record_id=normalized["record_id"],
                    binding=normalized["binding"],
                    binding_sha256=normalized["binding_sha256"],
                    approval=normalized["approval"],
                ),
                normalized["integrity"],
            )
        except FoundryError as exc:
            raise _error(
                "FINAL_CHARACTER_REVIEW_RECORD_INVALID",
                "The final-character review record integrity envelope is not valid.",
                details={"cause": exc.code, "record_id": record_id},
                status_code=409,
            ) from exc
        return normalized


def _persist_review_record(
    review_root: Path | str,
    integrity: IntegrityService,
    binding: Mapping[str, Any],
    approval: Mapping[str, Any],
    *,
    expected_review_root_identity: tuple[int, int] | None = None,
    expected_review_root_present: bool | None = None,
) -> dict[str, Any]:
    """Write one already-verified approval through the fixed review store.

    This private writer is deliberately not a method on the read-only loader.
    It is reachable only from the concrete issuer after approval evidence has
    been verified against the server database and the same integrity service.
    """

    normalized_binding = _validate_reviewed_binding_envelope(binding)
    normalized_approval = _validate_review_approval(approval)
    id_payload = {
        "schema_version": FINAL_CHARACTER_REVIEW_RECORD_SCHEMA,
        "binding": normalized_binding,
        "binding_sha256": normalized_binding["binding_sha256"],
        "approval": normalized_approval,
    }
    record_id = FINAL_CHARACTER_REVIEW_RECORD_PREFIX + sha256_json(id_payload)
    core = _review_record_core(
        record_id=record_id,
        binding=normalized_binding,
        binding_sha256=normalized_binding["binding_sha256"],
        approval=normalized_approval,
    )
    integrity_projection = _review_record_integrity_projection(
        record_id=record_id,
        binding=normalized_binding,
        binding_sha256=normalized_binding["binding_sha256"],
        approval=normalized_approval,
    )
    integrity_envelope = integrity.sign(FINAL_CHARACTER_REVIEW_RECORD_DOMAIN, integrity_projection).as_dict()
    record_body = {**core, "integrity": integrity_envelope}
    record = {**record_body, "record_sha256": sha256_json(record_body)}
    normalized_record = _validate_review_record(record, requested_record_id=record_id)

    loader = FinalCharacterReviewAuthority(
        review_root,
        integrity,
        expected_identity=expected_review_root_identity,
        expected_present=expected_review_root_present,
    )
    record_name = f"{record_id}.json"
    _ensure_review_root(
        loader.review_root,
        expected_identity=expected_review_root_identity,
        expected_present=expected_review_root_present,
    )
    _root, descriptor = loader._open_root(create=True)
    try:
        try:
            fd = os.open(
                record_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=descriptor,
            )
        except FileExistsError as exc:
            try:
                existing = loader.load_record(record_id)
            except FoundryError as existing_error:
                raise _error(
                    "FINAL_CHARACTER_REVIEW_RECORD_COLLISION",
                    "The content-addressed review record path is occupied by invalid content.",
                    details={"cause": existing_error.code, "record_id": record_id},
                    status_code=409,
                ) from exc
            if existing != normalized_record:
                raise _error(
                    "FINAL_CHARACTER_REVIEW_RECORD_COLLISION",
                    "The content-addressed review record path contains different content.",
                    details={"record_id": record_id},
                    status_code=409,
                )
            return existing
        except OSError as exc:
            raise _error(
                "FINAL_CHARACTER_REVIEW_RECORD_WRITE_FAILED",
                "The final-character review record could not be created safely.",
                details={"record_id": record_id, "error": type(exc).__name__},
                status_code=409,
            ) from exc
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write((canonical_json(normalized_record) + "\n").encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
        except Exception as exc:
            try:
                os.unlink(record_name, dir_fd=descriptor)
            except OSError:
                pass
            if isinstance(exc, FoundryError):
                raise
            raise _error(
                "FINAL_CHARACTER_REVIEW_RECORD_WRITE_FAILED",
                "The final-character review record could not be written atomically.",
                details={"record_id": record_id, "error": type(exc).__name__},
                status_code=409,
            ) from exc
    finally:
        os.close(descriptor)
    return normalized_record


class FinalCharacterReviewIssuer:
    """Issue a review record only from one verified ApprovalChallenge evidence ID.

    The reviewed binding is fixed when this issuer is constructed from
    server-owned validated evidence.  The public issuance operation accepts
    only the persisted evidence ID; reviewer text, paths, callbacks, and
    arbitrary provider objects are not authority inputs.
    """

    def __init__(
        self,
        review_root: Path | str,
        db: Database,
        integrity: IntegrityService,
        binding: Mapping[str, Any],
        *,
        expected_identity: tuple[int, int] | None = None,
        expected_present: bool | None = None,
    ) -> None:
        if not isinstance(db, Database) or not isinstance(integrity, IntegrityService):
            raise _error(
                "FINAL_CHARACTER_REVIEW_ISSUER_INVALID",
                "A final-character review issuer requires the concrete server Database and IntegrityService.",
                status_code=500,
            )
        self._authority = FinalCharacterReviewAuthority(
            review_root,
            integrity,
            expected_identity=expected_identity,
            expected_present=expected_present,
        )
        self._expected_review_root_identity = expected_identity
        self._expected_review_root_present = expected_present
        self._db = db
        self._integrity = integrity
        self._binding = _validate_reviewed_binding_envelope(binding)
        self._approval_challenges = ApprovalChallengeService(db, integrity=integrity)

    @property
    def review_authority(self) -> FinalCharacterReviewAuthority:
        return self._authority

    @property
    def review_root(self) -> Path:
        return self._authority.review_root

    @property
    def binding(self) -> dict[str, Any]:
        return deepcopy(self._binding)

    def issue_from_evidence(self, evidence_id: str) -> dict[str, Any]:
        """Consume no new authority; verify one exact persisted evidence row."""

        if not isinstance(evidence_id, str) or not evidence_id or len(evidence_id) > 256 or any(
            character in evidence_id for character in ("\x00", "\n", "\r", "/", "\\")
        ):
            raise _error(
                "FINAL_CHARACTER_REVIEW_APPROVAL_INVALID",
                "The approval evidence ID is not a safe bounded identity.",
                details={"field": "evidence_id"},
                status_code=409,
            )
        parameters = _review_approval_parameters(self._binding)
        try:
            with self._db.transaction() as conn:
                verified = self._approval_challenges.verify_evidence(
                    conn,
                    evidence_id,
                    **parameters,
                )
        except FoundryError:
            raise
        if (
            not isinstance(verified, Mapping)
            or verified.get("evidence_id") != evidence_id
            or verified.get("binding") != parameters["binding"]
            or verified.get("binding_hash") != sha256_json(parameters["binding"])
            or verified.get("project_lock_hash") != parameters["project_lock_hash"]
            or verified.get("approval_context") != parameters["evidence_context"]
        ):
            raise _error(
                "FINAL_CHARACTER_REVIEW_APPROVAL_INVALID",
                "The approval evidence did not reproduce the exact reviewed-pair binding.",
                details={"evidence_id": evidence_id},
                status_code=409,
            )
        principal = verified.get("principal")
        if not isinstance(principal, Mapping):
            raise _error(
                "FINAL_CHARACTER_REVIEW_APPROVAL_INVALID",
                "Verified approval evidence has no authoritative principal.",
                details={"evidence_id": evidence_id},
                status_code=409,
            )
        reviewer_id = principal.get("principal_id")
        if not isinstance(reviewer_id, str) or not reviewer_id:
            raise _error(
                "FINAL_CHARACTER_REVIEW_APPROVAL_INVALID",
                "Verified approval evidence has no safe principal identity.",
                details={"evidence_id": evidence_id},
                status_code=409,
            )
        approval = {
            "decision": "approved",
            "reviewer_id": reviewer_id,
            "evidence_id": str(verified["evidence_id"]),
        }
        return _persist_review_record(
            self.review_root,
            self._integrity,
            self._binding,
            approval,
            expected_review_root_identity=self._expected_review_root_identity,
            expected_review_root_present=self._expected_review_root_present,
        )


class FinalCharacterMaterializer:
    """Consume two accepted detached overlays into a compiler-gated copy."""

    def __init__(self, review_authority: "FinalCharacterReviewAuthority | None" = None) -> None:
        if review_authority is not None and not isinstance(review_authority, FinalCharacterReviewAuthority):
            raise _error(
                "FINAL_CHARACTER_REVIEW_AUTHORITY_INVALID",
                "The materializer review authority must be a FinalCharacterReviewAuthority instance.",
                status_code=500,
            )
        self._compiler_path = FINAL_CHARACTER_DEFAULT_COMPILER
        self._corpus_path = _method_release.release_path(FINAL_CHARACTER_DEFAULT_STATE_ROOT / "vendor")
        self._review_authority = review_authority

    @staticmethod
    def _existing(
        bundle: Path,
        expected: Mapping[str, Any],
        *,
        display_bundle: Path | None = None,
    ) -> dict[str, Any]:
        if bundle.is_symlink() or not bundle.is_dir():
            raise _error("FINAL_CHARACTER_COLLISION", "The content-addressed materialization bundle is occupied by a non-directory.")
        display_bundle = Path(display_bundle) if display_bundle is not None else Path(bundle)
        _ensure_regular_tree(bundle, code="FINAL_CHARACTER_COLLISION", message="The existing materialization bundle contains a symlink or path escape.")
        expected_names = {"workspace", FINAL_CHARACTER_RECEIPT_NAME}
        actual_names = {path.name for path in bundle.iterdir()}
        if actual_names != expected_names:
            raise _error("FINAL_CHARACTER_COLLISION", "The existing materialization bundle is incomplete or contains unowned files.", details={"expected": sorted(expected_names), "actual": sorted(actual_names)})
        workspace = bundle / "workspace"
        receipt = bundle / FINAL_CHARACTER_RECEIPT_NAME
        if workspace.is_symlink() or not workspace.is_dir() or receipt.is_symlink() or not receipt.is_file():
            raise _error("FINAL_CHARACTER_COLLISION", "An existing materialization bundle has no regular workspace and receipt.")
        _ensure_regular_tree(workspace, code="FINAL_CHARACTER_COLLISION", message="The existing materialized workspace contains a symlink or path escape.")
        try:
            _verify_workspace_checksums(workspace)
        except FoundryError as exc:
            raise _error("FINAL_CHARACTER_COLLISION", "The existing materialization checksum ledgers are invalid.", details={"cause": exc.code}) from exc
        receipt_value = _read_json(receipt, code="FINAL_CHARACTER_COLLISION")
        if not isinstance(receipt_value, Mapping) or any(receipt_value.get(key) != value for key, value in expected.items()):
            raise _error("FINAL_CHARACTER_COLLISION", "The existing content-addressed materialization receipt does not match.")
        review_receipt_keys = {
            "reviewed_binding",
            "reviewed_binding_sha256",
            "review_record_id",
            "review_record_sha256",
            "review_record_integrity",
        }
        if "reviewed_binding" in expected:
            try:
                receipt_binding = _validate_reviewed_binding_envelope(receipt_value.get("reviewed_binding"))
            except FoundryError as exc:
                raise _error("FINAL_CHARACTER_COLLISION", "The existing receipt has an invalid reviewed binding envelope.", details={"cause": exc.code}) from exc
            if receipt_binding != expected.get("reviewed_binding") or receipt_value.get("reviewed_binding_sha256") != receipt_binding.get("binding_sha256"):
                raise _error("FINAL_CHARACTER_COLLISION", "The existing receipt reviewed binding commitment is inconsistent.")
            if (
                _review_record_id(receipt_value.get("review_record_id")) != expected.get("review_record_id")
                or receipt_value.get("review_record_sha256") != expected.get("review_record_sha256")
                or receipt_value.get("review_record_integrity") != expected.get("review_record_integrity")
            ):
                raise _error("FINAL_CHARACTER_COLLISION", "The existing receipt review-record commitment is inconsistent.")
        elif review_receipt_keys.intersection(receipt_value):
            raise _error("FINAL_CHARACTER_COLLISION", "A legacy receipt contains reviewed-only provenance markers.")
        display_workspace = display_bundle / "workspace"
        display_receipt = display_bundle / FINAL_CHARACTER_RECEIPT_NAME
        if receipt_value.get("output_path") != str(display_workspace) or receipt_value.get("bundle_path") != str(display_bundle) or receipt_value.get("receipt_path") != str(display_receipt):
            raise _error("FINAL_CHARACTER_COLLISION", "The existing materialization receipt is bound to a different publication path.")
        if receipt_value.get("materialization_id") != bundle.name or receipt_value.get("output_tree_sha256") != _tree_hash(workspace):
            raise _error("FINAL_CHARACTER_COLLISION", "The existing materialization tree differs from its receipt.")
        compiler = receipt_value.get("compiler")
        if not isinstance(compiler, Mapping) or compiler.get("path") != str(FINAL_CHARACTER_DEFAULT_COMPILER) or compiler.get("sha256") != FINAL_CHARACTER_COMPILER_SHA256 or compiler.get("result") != "PASS" or compiler.get("execution_mode") != "pinned_subprocess":
            raise _error("FINAL_CHARACTER_COLLISION", "The existing materialization receipt is not bound to the production compiler trust pin.")
        corpus_digest = receipt_value.get("corpus_sha256")
        if corpus_digest not in {FINAL_CHARACTER_CORPUS_SHA256, _method_release.CORPUS_SHA256} or compiler.get("corpus_sha256") != corpus_digest:
            raise _error("FINAL_CHARACTER_COLLISION", "The existing materialization receipt is not bound to the production corpus trust pin.")
        if (corpus_digest == _method_release.CORPUS_SHA256 and receipt_value.get("method_corpus_release") != _method_release.binding()) or (corpus_digest == FINAL_CHARACTER_CORPUS_SHA256 and "method_corpus_release" in receipt_value):
            raise _error("FINAL_CHARACTER_COLLISION", "The existing receipt does not preserve its exact corpus release identity.")
        release_artifact = workspace / "Method_Corpus_Release.json"
        if corpus_digest == _method_release.CORPUS_SHA256:
            if release_artifact.is_symlink() or not release_artifact.is_file() or _read_json(release_artifact, code="FINAL_CHARACTER_COLLISION") != _method_release.binding():
                raise _error("FINAL_CHARACTER_COLLISION", "The checksummed workspace does not bind the released Method corpus.")
        elif release_artifact.exists() or release_artifact.is_symlink():
            raise _error("FINAL_CHARACTER_COLLISION", "A legacy receipt cannot attest a released corpus workspace.")
        if receipt_value.get("compiler_dependency_root") != str(FINAL_CHARACTER_DEFAULT_FACTORY_ROOT) or receipt_value.get("compiler_dependency_root_sha256") != FINAL_CHARACTER_FACTORY_ROOT_SHA256 or compiler.get("dependency_root") != str(FINAL_CHARACTER_DEFAULT_FACTORY_ROOT) or compiler.get("dependency_root_sha256") != FINAL_CHARACTER_FACTORY_ROOT_SHA256:
            raise _error("FINAL_CHARACTER_COLLISION", "The existing materialization receipt is not bound to the complete production compiler dependency tree.")
        if compiler.get("returncode") != 0 or receipt_value.get("source_workspace_immutable") is not True or receipt_value.get("provider_calls") != 0:
            raise _error("FINAL_CHARACTER_COLLISION", "The existing materialization receipt does not attest a successful immutable provider-free publication.")
        bridge = receipt_value.get("packet_bridge")
        provenance_relative = receipt_value.get("modern_packet_registry_provenance_path")
        if not isinstance(bridge, Mapping) or bridge.get("source_backed") is not True or bridge.get("modern_provenance_sha256") != receipt_value.get("modern_packet_registry_sha256") or bridge.get("native_registry_sha256") != receipt_value.get("compiler_packet_registry_sha256") or bridge.get("native_registry_packet_ids") != receipt_value.get("compiler_packet_registry_packet_ids") or bridge.get("pruned_packet_ids") != receipt_value.get("compiler_packet_registry_pruned_packet_ids") or not isinstance(provenance_relative, str):
            raise _error("FINAL_CHARACTER_COLLISION", "The existing materialization receipt omits or diverges from the packet bridge attestation.")
        try:
            provenance = _safe_workspace_path(workspace, provenance_relative, field="modern packet provenance")
        except FoundryError as exc:
            raise _error("FINAL_CHARACTER_COLLISION", "The existing packet provenance path escapes the materialized workspace.") from exc
        native_registry = workspace / "Command_2/Rules_Selection_Packets.json"
        if provenance.is_symlink() or native_registry.is_symlink() or not provenance.is_file() or not native_registry.is_file() or sha256_file(provenance) != receipt_value.get("modern_packet_registry_sha256") or sha256_file(native_registry) != receipt_value.get("compiler_packet_registry_sha256"):
            raise _error("FINAL_CHARACTER_COLLISION", "The existing packet bridge files differ from their receipt hashes.")
        if corpus_digest == FINAL_CHARACTER_CORPUS_SHA256 and any(row.get("source_path") == _method_release.SOURCE_MEMBER for row in _read_json(native_registry, code="FINAL_CHARACTER_COLLISION").get("packets", [])):
            raise _error("FINAL_CHARACTER_COLLISION", "A legacy receipt cannot attest released Method packets.")
        # New materializations also carry a Build copy of the compiler-native
        # packet registry.  Validate its paired raw provenance and exact bytes
        # when the bridge emitted those fields; legacy receipts intentionally
        # omit them and retain their historical Command_2-only contract.
        build_provenance_relative = bridge.get("build_modern_provenance_path")
        build_provenance_sha256 = bridge.get("build_modern_provenance_sha256")
        build_native_relative = bridge.get("build_native_registry_path")
        build_native_sha256 = bridge.get("build_native_registry_sha256")
        build_markers = (
            build_provenance_relative,
            build_provenance_sha256,
            build_native_relative,
            build_native_sha256,
        )
        if any(marker is not None for marker in build_markers):
            if (
                not all(isinstance(marker, str) and marker for marker in build_markers)
                or not _is_hash(build_provenance_sha256)
                or not _is_hash(build_native_sha256)
                or build_provenance_relative != "Build/Rules_Selection_Packets.Modern_Provenance.json"
                or build_native_relative != "Build/Rules_Selection_Packets.json"
                or bridge.get("build_modern_provenance_sha256") != receipt_value.get("build_modern_provenance_sha256")
                or bridge.get("build_native_registry_sha256") != receipt_value.get("build_native_registry_sha256")
            ):
                raise _error("FINAL_CHARACTER_COLLISION", "The existing receipt omits or diverges from the Build packet bridge attestation.")
            try:
                build_provenance = _safe_workspace_path(workspace, build_provenance_relative, field="Build packet provenance")
                build_native = _safe_workspace_path(workspace, build_native_relative, field="Build native packet registry")
            except FoundryError as exc:
                raise _error("FINAL_CHARACTER_COLLISION", "The existing Build packet bridge path escapes the materialized workspace.") from exc
            if (
                build_provenance.is_symlink()
                or build_native.is_symlink()
                or not build_provenance.is_file()
                or not build_native.is_file()
                or sha256_file(build_provenance) != build_provenance_sha256
                or sha256_file(build_native) != build_native_sha256
                or build_native.read_bytes() != native_registry.read_bytes()
            ):
                raise _error("FINAL_CHARACTER_COLLISION", "The existing Build packet bridge files differ from their receipt hashes or compiler-native bytes.")
        action_surface = receipt_value.get("action_surface_equality")
        recomputations = receipt_value.get("recomputations")
        if not isinstance(action_surface, Mapping) or action_surface.get("equal") is not True or not isinstance(recomputations, Mapping) or any(recomputations.get(key) is not True for key in ("state_after_hash_recomputed", "action_surfaces_reprojected", "action_surface_hashes_recomputed", "workspace_manifests_recomputed", "workspace_checksums_recomputed")):
            raise _error("FINAL_CHARACTER_COLLISION", "The existing materialization receipt omits required recomputation attestations.")
        return {
            "output_path": str(display_workspace),
            "bundle_path": str(display_bundle),
            "receipt_path": str(display_receipt),
            "materialization_id": bundle.name,
            "receipt": deepcopy(dict(receipt_value)),
            "idempotent": True,
        }

    def _materialize_legacy(
        self,
        source_workspace: Path | str,
        composite_overlay: Path | str,
        output_root: Path | str,
        *,
        project_id: str | None = None,
        candidate_sha256: str | None = None,
        projection_id: str | None = None,
        expected_composite_overlay_id: str | None = None,
        expected_composite_artifact_sha256: str | None = None,
        expected_composite_overlay_tree_sha256: str | None = None,
        review_record: Mapping[str, Any] | None = None,
        output_binding: _BoundOutputRoot | None = None,
        composite_binding: _BoundChildDirectory | None = None,
    ) -> dict[str, Any]:
        source = Path(source_workspace)
        composite = Path(composite_overlay)
        output_parent = Path(output_root)
        owned_output_binding = False
        if output_binding is None:
            output_binding = _ensure_private_output_root(output_parent)
            owned_output_binding = True
        output_binding.assert_current_path()
        output_display_root = output_binding.display_path
        normalized_review_record = _validate_review_record(review_record) if review_record is not None else None
        reviewed = normalized_review_record["binding"] if normalized_review_record is not None else None
        if reviewed is not None:
            for field, supplied in (
                ("project_id", project_id),
                ("candidate_sha256", candidate_sha256),
                ("projection_id", projection_id),
            ):
                if supplied is not None and supplied != reviewed[field]:
                    raise _error(
                        "FINAL_CHARACTER_OVERLAY_BINDING_MISMATCH",
                        f"The supplied {field} does not match the reviewed binding envelope.",
                        details={"field": field},
                    )
            for label, bound, supplied in (
                ("composite overlay ID", reviewed["composite_overlay"]["overlay_id"], expected_composite_overlay_id),
                ("composite artifact hash", reviewed["composite_overlay"]["artifact_sha256"], expected_composite_artifact_sha256),
                ("composite overlay tree hash", reviewed["composite_overlay"]["overlay_tree_sha256"], expected_composite_overlay_tree_sha256),
            ):
                if supplied is not None and supplied != bound:
                    raise _error(
                        "FINAL_CHARACTER_OVERLAY_BINDING_MISMATCH",
                        f"The supplied {label} does not match the persisted review record.",
                        details={"expected": bound, "requested": supplied},
                    )
            project_id = reviewed["project_id"]
            candidate_sha256 = reviewed["candidate_sha256"]
            projection_id = reviewed["projection_id"]
        _ensure_regular_tree(source, code="FINAL_CHARACTER_SOURCE_INVALID", message="The accepted source workspace must be a regular tree.")
        try:
            source_resolved = source.resolve()
            output_resolved = output_display_root
            output_resolved.relative_to(source_resolved)
        except ValueError:
            pass
        except OSError as exc:
            raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", "The materialization output root cannot be resolved.") from exc
        else:
            raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", "Materialization output cannot be written inside the source workspace.")
        for immutable_root, label in ((composite, "Composite overlay"),):
            try:
                output_resolved.relative_to(immutable_root.resolve())
            except ValueError:
                continue
            except OSError as exc:
                raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", f"The materialization output root cannot be compared with the {label.lower()}.") from exc
            raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", f"Materialization output cannot be written inside the {label.lower()}.")
        _ensure_regular_tree(composite, code="FINAL_CHARACTER_COMPOSITE_OVERLAY_INVALID", message="The Composite overlay must be a regular tree.")
        try:
            source_hash = _workspace_sha256(source)
            _verify_workspace_checksums(source)
        except FoundryError as exc:
            raise _error("FINAL_CHARACTER_SOURCE_INVALID", "The accepted source workspace checksum binding is invalid.", details={"cause": exc.code, "message": exc.message}) from exc
        if self._compiler_path == FINAL_CHARACTER_DEFAULT_COMPILER:
            _final_compiler_release.ensure_release(FINAL_CHARACTER_DEFAULT_STATE_ROOT)
        if self._corpus_path == _method_release.release_path(FINAL_CHARACTER_DEFAULT_STATE_ROOT / "vendor"):
            _method_release.ensure_release(FINAL_CHARACTER_DEFAULT_STATE_ROOT / "vendor", FINAL_CHARACTER_DEFAULT_CORPUS)
        _assert_production_pins(self._compiler_path, self._corpus_path)
        corpus_hash = _corpus_pin(self._corpus_path)
        compiler_hash = FINAL_CHARACTER_COMPILER_SHA256
        compiler_module = _load_compiler_module(self._compiler_path)

        # The Composite validator re-checks its exact overlay file set,
        # detached checksums, source hash, and artifact/manifest bindings
        # before any destination is allocated.  The controller-built Immortal
        # Arts belong to the sealed source and are re-checked against the
        # compiled rules here; nothing new is authored at this stage.
        try:
            composite_validated = CompositeControllerAuthoring.validate_overlay(composite, project_id=project_id, candidate_sha256=candidate_sha256, projection_id=projection_id, source_workspace=source)
        except FoundryError as exc:
            raise _error("FINAL_CHARACTER_OVERLAY_REJECTED", "The accepted Composite overlay failed revalidation.", details={"cause": exc.code, "message": exc.message}) from exc
        immortal_binding_value = constructed_immortal_art_binding(source)
        composite_artifact = composite_validated["artifact"]
        project_value = composite_artifact.get("project_id")
        if not isinstance(project_value, str) or not project_value or (project_id is not None and project_value != project_id):
            raise _error("FINAL_CHARACTER_PROJECT_BINDING_MISMATCH", "The Composite overlay does not bind one exact project.")
        project_values = {project_value}
        candidate_value = composite_artifact.get("base_candidate_sha256")
        if not isinstance(candidate_value, str) or not candidate_value or (candidate_sha256 is not None and candidate_value != candidate_sha256):
            raise _error("FINAL_CHARACTER_CANDIDATE_BINDING_MISMATCH", "The Composite overlay does not bind one exact candidate.")
        candidate_values = {candidate_value}
        if source_hash != composite_artifact.get("source_workspace_sha256"):
            raise _error("FINAL_CHARACTER_SOURCE_BINDING_MISMATCH", "The Composite overlay is not bound to the observed source workspace.", details={"actual": source_hash})
        # The snapshot names are compatibility paths for the existing
        # validators, but hashes must be taken from the held child inodes so a
        # raced component name cannot redirect the binding between checks.
        if composite_binding is not None:
            composite_binding.assert_current()
        composite_hash_root = composite_binding.fd_path if composite_binding is not None else composite
        composite_tree_hash = _tree_hash(composite_hash_root)
        if reviewed is not None:
            composite_internal_tree_hash = _validated_overlay_internal_tree_hash(composite_hash_root, composite_validated, label="Composite")
            requested_reviewed_values = (
                ("composite overlay ID", reviewed["composite_overlay"]["overlay_id"], expected_composite_overlay_id),
                ("composite artifact hash", reviewed["composite_overlay"]["artifact_sha256"], expected_composite_artifact_sha256),
                ("composite overlay tree hash", reviewed["composite_overlay"]["overlay_tree_sha256"], expected_composite_overlay_tree_sha256),
            )
            for label, bound, requested in requested_reviewed_values:
                if requested is not None and requested != bound:
                    raise _error(
                        "FINAL_CHARACTER_OVERLAY_BINDING_MISMATCH",
                        f"The supplied {label} does not match the reviewed binding envelope.",
                        details={"expected": bound, "requested": requested},
                    )
            _validate_reviewed_binding_against_evidence(
                reviewed,
                project_id=next(iter(project_values)),
                candidate_sha256=next(iter(candidate_values)),
                projection_id=str(composite_artifact.get("projection_id")),
                source_workspace_sha256=source_hash,
                composite_validated=composite_validated,
                composite_overlay_files_tree_sha256=composite_tree_hash,
                composite_overlay_root=composite_hash_root,
                constructed_immortal_arts=immortal_binding_value,
            )
        else:
            # The pinned Luna fixture pair is retired; every final character
            # now materializes only from its persisted review record.
            raise _error(
                "FINAL_CHARACTER_REVIEW_RECORD_REQUIRED",
                "Materialization requires a persisted final-character review record.",
                status_code=409,
            )
        stage_child = output_binding.create_bound_temp_dir(".final-character-materializer-")
        stage = stage_child.fd_path
        workspace = stage / "workspace"
        workspace_binding: _BoundChildDirectory | None = None
        published = False
        published_final: Path | None = None
        published_final_name: str | None = None
        published_binding: _BoundChildDirectory | None = None
        try:
            workspace_binding = stage_child.create_bound_child("workspace")
            workspace = workspace_binding.fd_path
            output_binding.assert_current_path()
            stage_child.assert_current()
            workspace_binding.assert_current()
            # The private stage is a sibling of the eventual bundle; source
            # bytes remain untouched even when a later operation fails.
            _copy_tree_no_symlinks(source, workspace_binding)
            workspace_binding.assert_current()
            _verify_copied_workspace(workspace, source_hash)
            # Preserve and project the sealed modern ledger before any
            # detached overlay adds Command 4 rows.  The compiler-only flat
            # fields are therefore traceable to the original copied ledger,
            # while later overlay/runtime projections remain separate.
            path_projection = _project_modern_path_fields_for_compiler(workspace)
            method_projection = _project_method_for_compiler(
                workspace,
                path_projection=path_projection,
            )
            foundation_projection = _project_foundation_for_compiler(workspace)
            ability_projection = _project_modern_ability_generation_for_compiler(
                workspace,
                path_projection=path_projection,
            )
            grant_projection = _project_background_origin_allocations_for_compiler(
                workspace,
                ability_projection=ability_projection,
            )
            origin_insight_projection = _project_background_origin_insight_for_compiler(workspace)
            background_equipment_projection = _project_background_equipment_for_compiler(workspace)
            resource_projection = _project_modern_resource_for_compiler(
                workspace,
                path_projection=path_projection,
                ability_projection=ability_projection,
                method_projection=method_projection,
                foundation_projection=foundation_projection,
            )
            hp_projection = _project_modern_hp_for_compiler(
                workspace,
                path_projection=path_projection,
                foundation_projection=foundation_projection,
            )
            core_save_projection = _project_modern_core_saves_for_compiler(
                workspace,
                path_projection=path_projection,
            )
            ac_projection = _project_modern_ac_for_compiler(
                workspace,
                path_projection=path_projection,
            )
            speed_projection = _project_modern_speed_for_compiler(
                workspace,
                path_projection=path_projection,
            )
            initiative_projection = _project_modern_initiative_for_compiler(
                workspace,
                path_projection=path_projection,
            )
            # Translate the controller-built Immortal Arts into the pinned
            # compiler's ledger shape in this private copy only.
            immortal_translation = translate_constructed_immortal_arts(workspace)
            if immortal_translation["binding"] != immortal_binding_value:
                raise _error("FINAL_CHARACTER_IMMORTAL_ART_INVALID", "The copied workspace Immortal Arts diverge from the checked source.")
            action_projection = _verify_immortal_action_projection(workspace, immortal_translation)
            checkpoints = _recompute_checkpoints(workspace, compiler_module)

            runtime_controller = _build_runtime_controller(
                workspace,
                composite_artifact,
                composite_validated["manifest"],
                overlay_id=str(composite_validated["overlay_id"]),
                overlay_tree_sha256=composite_internal_tree_hash,
            )
            # Runtime files are separate from the old display-only playbook
            # surface.  The accepted raw artifact/manifest remain provenance;
            # no provider-supplied nested packet becomes runtime authority.
            _write_json(workspace / "Command_4/Composite_Controller.json", runtime_controller)
            _write_json(workspace / "Build/Composite_Controller.json", runtime_controller)
            _write_json(workspace / "Command_4/Composite_Controller_Artifact.json", composite_artifact)
            _write_json(workspace / "Composite_Controller_Overlay_Manifest.json", composite_validated["manifest"])
            _write_json(workspace / "Validation/Composite_Controller.validation.json", {
                "schema_version": "TianxiaFoundry.CompositeControllerValidation.v1",
                "valid": True,
                "execution_authority": True,
                "controller_policy_registered": True,
                "artifact_sha256": composite_validated["artifact_sha256"],
                "project_id": composite_artifact.get("project_id"),
                "projection_id": composite_artifact.get("projection_id"),
                "base_candidate_sha256": composite_artifact.get("base_candidate_sha256"),
            })
            realm_projection = _project_modern_realm_for_compiler(
                workspace,
                path_projection=path_projection,
                immortal_translation=immortal_translation,
                hp_projection=hp_projection,
                ability_projection=ability_projection,
                resource_projection=resource_projection,
                grant_projection=grant_projection,
            )
            packet_projection = _bridge_rules_packet_registry(workspace, self._corpus_path)
            promotion = _promote_materialized_command4_ledger(
                workspace,
                runtime_controller=runtime_controller,
                action_projection=action_projection,
                immortal_translation=immortal_translation,
            )
            if corpus_hash == _method_release.CORPUS_SHA256:
                release_artifact = workspace / "Method_Corpus_Release.json"
                if release_artifact.exists() or release_artifact.is_symlink():
                    raise _error("FINAL_CHARACTER_COLLISION", "The input workspace already contains a Method corpus release artifact.")
                _write_json(release_artifact, _method_release.binding())
            _recompute_workspace_receipts(workspace)
            compiler_result = _run_pinned_compiler_after_manual_lineage_gate(
                compiler_path=self._compiler_path,
                corpus=self._corpus_path,
                workspace=workspace,
            )
            if not isinstance(compiler_result, Mapping) or compiler_result.get("execution_mode") != "pinned_subprocess" or compiler_result.get("returncode") != 0 or compiler_result.get("corpus_sha256") != corpus_hash:
                raise _error(
                    "FINAL_CHARACTER_COMPILER_REJECTED",
                    "Materialization acceptance requires a successful pinned subprocess compiler execution.",
                    details={"execution_mode": compiler_result.get("execution_mode") if isinstance(compiler_result, Mapping) else None, "returncode": compiler_result.get("returncode") if isinstance(compiler_result, Mapping) else None},
                )
            _validate_compiler_output(workspace)
            # Compiler output is a new root subtree, so regenerate the root
            # checksum ledger after the acceptance gate has passed.
            _recompute_workspace_receipts(workspace)
            _ensure_regular_tree(workspace, code="FINAL_CHARACTER_OUTPUT_INVALID", message="The materialized tree contains a symlink or path escape.")
            _ensure_regular_tree(source, code="FINAL_CHARACTER_SOURCE_CHANGED", message="The accepted source workspace changed to include a symlink or path escape.")
            source_after_hash = _workspace_sha256(source)
            if source_after_hash != source_hash:
                raise _error(
                    "FINAL_CHARACTER_SOURCE_CHANGED",
                    "The accepted source workspace changed while materialization was in progress.",
                    details={"before": source_hash, "after": source_after_hash},
                )
            output_tree_hash = _tree_hash(workspace)
            # The published bundle directory name is the hash of its
            # complete checksummed workspace content.  The receipt is inside
            # the bundle but outside that hashed workspace to avoid a cycle.
            materialization_id = output_tree_hash
            output_binding.assert_current_path()
            final = output_binding.child_path(materialization_id)
            final_display = output_display_root / materialization_id
            final_workspace = final / "workspace"
            receipt_path = _receipt_path(output_display_root, materialization_id)
            published_final = final
            published_final_name = materialization_id
            expected_existing = {
                "materialization_id": materialization_id,
                "output_tree_sha256": output_tree_hash,
                "source_workspace_sha256": source_hash,
                "compiler_sha256": compiler_hash,
                "compiler_dependency_root": str(FINAL_CHARACTER_DEFAULT_FACTORY_ROOT),
                "compiler_dependency_root_sha256": FINAL_CHARACTER_FACTORY_ROOT_SHA256,
                "corpus_sha256": corpus_hash,
                **({"method_corpus_release": _method_release.binding()} if corpus_hash == _method_release.CORPUS_SHA256 else {}),
                "composite_overlay_id": composite_validated["overlay_id"],
                "composite_overlay_artifact_sha256": composite_validated["artifact_sha256"],
                "composite_overlay_tree_sha256": composite_internal_tree_hash,
                "constructed_immortal_arts": immortal_binding_value,
                "project_id": next(iter(project_values)),
                "candidate_sha256": next(iter(candidate_values)),
                "candidate_id": next(iter(candidate_values)),
                "controller_id": FINAL_CHARACTER_CONTROLLER_ID,
                # Packet bridge fields are part of the idempotence binding;
                # a pre-existing bundle with a different compiler registry
                # projection is not an acceptable content-addressed match.
                "modern_packet_registry_sha256": packet_projection["modern_provenance_sha256"],
                "modern_packet_registry_provenance_path": packet_projection["modern_provenance_path"],
                "compiler_packet_registry_sha256": packet_projection["native_registry_sha256"],
                "compiler_packet_registry_packet_ids": packet_projection["native_registry_packet_ids"],
                "compiler_packet_registry_packet_count": packet_projection["native_registry_packet_count"],
                "compiler_packet_registry_pruned_packet_ids": packet_projection["pruned_packet_ids"],
                "build_modern_provenance_path": packet_projection.get("build_modern_provenance_path"),
                "build_modern_provenance_sha256": packet_projection.get("build_modern_provenance_sha256"),
                "build_native_registry_path": packet_projection.get("build_native_registry_path"),
                "build_native_registry_sha256": packet_projection.get("build_native_registry_sha256"),
                "path_projection": path_projection,
                "method_projection": method_projection,
                "foundation_projection": foundation_projection,
                "hp_projection": hp_projection,
                "ability_projection": ability_projection,
                "grant_projection": grant_projection,
                "origin_insight_projection": origin_insight_projection,
                "background_equipment_projection": background_equipment_projection,
                "resource_projection": resource_projection,
                "core_save_projection": core_save_projection,
                "ac_projection": ac_projection,
                "speed_projection": speed_projection,
                "initiative_projection": initiative_projection,
                "realm_projection": realm_projection,
                "command4_promotion": promotion,
            }
            if reviewed is not None:
                expected_existing.update({
                    "composite_overlay_files_tree_sha256": composite_tree_hash,
                        "reviewed_binding": reviewed,
                    "reviewed_binding_sha256": reviewed["binding_sha256"],
                    "review_record_id": normalized_review_record["record_id"],
                    "review_record_sha256": normalized_review_record["record_sha256"],
                    "review_record_integrity": normalized_review_record["integrity"],
                })
            legacy_receipt_name = f"{materialization_id}.{FINAL_CHARACTER_RECEIPT_NAME}"
            if output_binding.child_exists(legacy_receipt_name):
                raise _error("FINAL_CHARACTER_COLLISION", "A legacy external receipt path is occupied and cannot be replaced.")
            if output_binding.child_exists(materialization_id):
                if final.is_dir() and not final.is_symlink():
                    result = self._existing(final, expected_existing, display_bundle=final_display)
                    output_binding.assert_current_path()
                    stage_child.cleanup()
                    return result
                raise _error("FINAL_CHARACTER_COLLISION", "An existing final bundle path is incomplete and cannot be replaced.")
            receipt = {
                "schema_version": FINAL_CHARACTER_RECEIPT_SCHEMA,
                "materialization_id": materialization_id,
                "bundle_path": str(final_display),
                "output_path": str(final_display / "workspace"),
                "receipt_path": str(receipt_path),
                "source_workspace_sha256": source_hash,
                "source_workspace_before_sha256": source_hash,
                "source_workspace_after_sha256": source_after_hash,
                "source_workspace_immutable": source_after_hash == source_hash,
                "project_id": next(iter(project_values)),
                "candidate_sha256": next(iter(candidate_values)),
                "candidate_id": next(iter(candidate_values)),
                "composite_overlay_id": composite_validated["overlay_id"],
                "composite_overlay_artifact_sha256": composite_validated["artifact_sha256"],
                "composite_overlay_tree_sha256": composite_internal_tree_hash,
                "constructed_immortal_arts": immortal_binding_value,
                "output_tree_sha256": output_tree_hash,
                "compiler_sha256": compiler_hash,
                "compiler_dependency_root": str(FINAL_CHARACTER_DEFAULT_FACTORY_ROOT),
                "compiler_dependency_root_sha256": FINAL_CHARACTER_FACTORY_ROOT_SHA256,
                "corpus_sha256": corpus_hash,
                **({"method_corpus_release": _method_release.binding()} if corpus_hash == _method_release.CORPUS_SHA256 else {}),
                "compiler": {"path": str(self._compiler_path), "sha256": compiler_hash, "dependency_root": str(FINAL_CHARACTER_DEFAULT_FACTORY_ROOT), "dependency_root_sha256": FINAL_CHARACTER_FACTORY_ROOT_SHA256, "corpus_sha256": compiler_result["corpus_sha256"], "result": "PASS", "execution_mode": "pinned_subprocess", "returncode": compiler_result.get("returncode"), "output": str(final_display / "workspace" / FINAL_CHARACTER_COMPILER_OUTPUT_DIRNAME)},
                "controller_id": FINAL_CHARACTER_CONTROLLER_ID,
                "modern_packet_registry_sha256": packet_projection["modern_provenance_sha256"],
                "modern_packet_registry_provenance_path": packet_projection["modern_provenance_path"],
                "compiler_packet_registry_sha256": packet_projection["native_registry_sha256"],
                "compiler_packet_registry_packet_ids": packet_projection["native_registry_packet_ids"],
                "compiler_packet_registry_packet_count": packet_projection["native_registry_packet_count"],
                "compiler_packet_registry_pruned_packet_ids": packet_projection["pruned_packet_ids"],
                "build_modern_provenance_path": packet_projection.get("build_modern_provenance_path"),
                "build_modern_provenance_sha256": packet_projection.get("build_modern_provenance_sha256"),
                "build_native_registry_path": packet_projection.get("build_native_registry_path"),
                "build_native_registry_sha256": packet_projection.get("build_native_registry_sha256"),
                "path_projection": path_projection,
                "method_projection": method_projection,
                "foundation_projection": foundation_projection,
                "hp_projection": hp_projection,
                "ability_projection": ability_projection,
                "grant_projection": grant_projection,
                "origin_insight_projection": origin_insight_projection,
                "background_equipment_projection": background_equipment_projection,
                "resource_projection": resource_projection,
                "core_save_projection": core_save_projection,
                "ac_projection": ac_projection,
                "speed_projection": speed_projection,
                "initiative_projection": initiative_projection,
                "realm_projection": realm_projection,
                "command4_promotion": promotion,
                "action_surface_equality": action_projection,
                "recomputations": {
                    "advancement_state_after_hash_count": checkpoints,
                    "state_after_hash_recomputed": True,
                    "action_surfaces_reprojected": True,
                    "action_surface_hashes_recomputed": True,
                    "workspace_manifests_recomputed": True,
                    "workspace_checksums_recomputed": True,
                },
                "source_lineage_preserved": True,
                "provider_calls": 0,
                "compiler_stdout_tail": compiler_result.get("stdout", ""),
                "packet_bridge": packet_projection,
            }
            if reviewed is not None:
                receipt.update({
                    "composite_overlay_files_tree_sha256": composite_tree_hash,
                        "reviewed_binding": reviewed,
                    "reviewed_binding_sha256": reviewed["binding_sha256"],
                    "review_record_id": normalized_review_record["record_id"],
                    "review_record_sha256": normalized_review_record["record_sha256"],
                    "review_record_integrity": normalized_review_record["integrity"],
                })
            # Build the complete receipt inside the stage before publication.
            # A single directory rename then makes workspace and receipt
            # visible together; no final workspace exists without its receipt.
            try:
                _exclusive_write_json(stage / FINAL_CHARACTER_RECEIPT_NAME, receipt)
                _ensure_regular_tree(stage, code="FINAL_CHARACTER_OUTPUT_INVALID", message="The staged bundle contains a symlink or path escape.")
            except Exception:
                raise
            output_binding.assert_current_path()
            if output_binding.child_exists(legacy_receipt_name):
                raise _error("FINAL_CHARACTER_COLLISION", "A legacy external receipt path was claimed before atomic publication.")
            if output_binding.child_exists(materialization_id):
                if final.is_dir() and not final.is_symlink():
                    result = self._existing(final, expected_existing, display_bundle=final_display)
                    output_binding.assert_current_path()
                    stage_child.cleanup()
                    return result
                raise _error("FINAL_CHARACTER_COLLISION", "The content-addressed bundle path was claimed before atomic publication.")
            try:
                output_binding.assert_current_path()
                _atomic_publish_noreplace(stage, final, root_fd=output_binding.fd, stage_binding=stage_child)
            except FoundryError:
                raise
            except (OSError, FileExistsError) as exc:
                    raise _error("FINAL_CHARACTER_COLLISION", "The content-addressed bundle path was claimed concurrently or could not be atomically published.") from exc
            published = True
            # The stage descriptor now refers to the published bundle inode.
            # Bind that same inode before any later cleanup can be needed; a
            # pathname-only cleanup could otherwise delete a raced replacement.
            published_binding = stage_child.duplicate_for_name(output_binding, published_final_name or materialization_id)
            output_binding.assert_current_path()
            _ensure_regular_tree(source, code="FINAL_CHARACTER_SOURCE_CHANGED", message="The accepted source workspace changed to include a symlink or path escape.")
            final_source_hash = _workspace_sha256(source)
            if final_source_hash != source_hash:
                # The bundle is ours and was just published; remove it rather
                # than claiming immutability when the source changed.
                if published_binding is not None:
                    published_binding.cleanup()
                published = False
                raise _error(
                    "FINAL_CHARACTER_SOURCE_CHANGED",
                    "The accepted source workspace changed before the receipt was sealed.",
                    details={"before": source_hash, "after": final_source_hash},
                )
            stage_child.close()
            # Keep the held published inode alive until the outer materialize
            # call has completed its final snapshot-integrity check.  The
            # private key is consumed immediately and never crosses the
            # public return boundary; retaining it here makes a later failure
            # able to clear only this invocation's published inode.
            return {"output_path": str(final_display / "workspace"), "bundle_path": str(final_display), "receipt_path": str(receipt_path), "materialization_id": materialization_id, "receipt": receipt, "idempotent": False, "_published_binding": published_binding}
        except Exception:
            if not published:
                stage_child.cleanup()
            else:
                # Any unexpected post-publication exception removes the
                # complete owned bundle, including its receipt.
                stage_child.close()
                if published_binding is not None:
                    published_binding.cleanup()
            if owned_output_binding:
                output_binding.close()
            raise
        else:
            if owned_output_binding:
                output_binding.close()
        finally:
            if workspace_binding is not None:
                workspace_binding.close()

    def materialize(
        self,
        source_workspace: Path | str,
        composite_overlay: Path | str,
        output_root: Path | str,
        *,
        project_id: str | None = None,
        candidate_sha256: str | None = None,
        projection_id: str | None = None,
        expected_composite_overlay_id: str | None = None,
        expected_composite_artifact_sha256: str | None = None,
        expected_composite_overlay_tree_sha256: str | None = None,
        review_record_id: str | None = None,
        expected_output_root_identity: tuple[int, int] | None = None,
        expected_output_root_present: bool | None = None,
        # Kept as a typed rejection for callers compiled against the earlier
        # envelope-only draft.  A caller-supplied binding is never an
        # authority surface; only a record loaded through the configured
        # FinalCharacterReviewAuthority can authorize a non-legacy pair.
        reviewed_binding: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Snapshot the detached Composite overlay, then consume only the snapshot."""

        if reviewed_binding is not None:
            raise _error(
                "FINAL_CHARACTER_REVIEW_RECORD_REQUIRED",
                "A caller-supplied reviewed binding cannot authorize materialization; provide a persisted review record ID.",
                status_code=409,
            )
        review_record: dict[str, Any] | None = None
        reviewed: dict[str, Any] | None = None
        if review_record_id is None:
            raise _error(
                "FINAL_CHARACTER_REVIEW_RECORD_REQUIRED",
                "Materialization requires a persisted final-character review record.",
                status_code=409,
            )
        if review_record_id is not None:
            if self._review_authority is None:
                raise _error(
                    "FINAL_CHARACTER_REVIEW_AUTHORITY_REQUIRED",
                    "A persisted review record authority is required for reviewed overlay pairs.",
                    status_code=409,
                )
            review_record = self._review_authority.load_record(review_record_id)
            reviewed = deepcopy(review_record["binding"])
            for field, supplied in (
                ("project_id", project_id),
                ("candidate_sha256", candidate_sha256),
                ("projection_id", projection_id),
            ):
                if supplied is not None and supplied != reviewed[field]:
                    raise _error(
                        "FINAL_CHARACTER_OVERLAY_BINDING_MISMATCH",
                        f"The supplied {field} does not match the reviewed binding envelope.",
                        details={"field": field},
                    )
            project_id = reviewed["project_id"]
            candidate_sha256 = reviewed["candidate_sha256"]
            projection_id = reviewed["projection_id"]
        source = Path(source_workspace)
        composite = Path(composite_overlay)
        output_parent = Path(output_root)
        _ensure_regular_tree(source, code="FINAL_CHARACTER_SOURCE_INVALID", message="The accepted source workspace must be a regular tree.")
        try:
            source_resolved = source.resolve()
            output_resolved = output_parent.resolve(strict=False)
            output_resolved.relative_to(source_resolved)
        except ValueError:
            pass
        except OSError as exc:
            raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", "The materialization output root cannot be resolved.") from exc
        else:
            raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", "Materialization output cannot be written inside the source workspace.")
        for immutable_root, label in ((composite, "Composite overlay"),):
            try:
                output_resolved.relative_to(immutable_root.resolve())
            except ValueError:
                continue
            except OSError as exc:
                raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", f"The materialization output root cannot be compared with the {label.lower()}.") from exc
            raise _error("FINAL_CHARACTER_OUTPUT_ROOT_INVALID", f"Materialization output cannot be written inside the {label.lower()}.")

        # A reviewed pair must be rederived from its private snapshots before
        # the caller's output root is created.  This prevents an unreviewed or
        # changed source/overlay pair from even creating a publication
        # boundary.  Once the boundary is needed, retain its no-follow fd for
        # every stage/final operation; never reopen the caller pathname.
        output_binding: _BoundOutputRoot | None = None
        snapshot_root: Path | None = None
        snapshot_child: _BoundChildDirectory | None = None
        snapshot_composite_binding: _BoundChildDirectory | None = None
        published_result_binding: _BoundChildDirectory | None = None

        def bind_output_root() -> _BoundOutputRoot:
            if expected_output_root_identity is None and expected_output_root_present is None:
                # Preserve the compatibility call shape for direct callers and
                # injected test doubles that do not use workflow handoff data.
                return _ensure_private_output_root(output_parent)
            return _ensure_private_output_root(
                output_parent,
                expected_identity=expected_output_root_identity,
                expected_present=expected_output_root_present,
            )

        if reviewed is not None:
            try:
                source_binding_hash = _workspace_sha256(source)
                _verify_workspace_checksums(source)
            except FoundryError as exc:
                raise _error(
                    "FINAL_CHARACTER_SOURCE_INVALID",
                    "The reviewed source workspace checksum binding is invalid.",
                    details={"cause": exc.code, "message": exc.message},
                ) from exc
            if source_binding_hash != reviewed["source_workspace_sha256"]:
                raise _error(
                    "FINAL_CHARACTER_SOURCE_BINDING_MISMATCH",
                    "The reviewed record does not match the observed source workspace.",
                    details={"expected": reviewed["source_workspace_sha256"], "actual": source_binding_hash},
                )
            output_binding = bind_output_root()
        else:
            # The boundary is private before snapshot allocation; reserve the
            # snapshot directory by descriptor so a raced root pathname cannot
            # redirect even this early write.
            output_binding = bind_output_root()
        snapshot_child = output_binding.create_bound_temp_dir(".final-character-overlay-snapshot-")
        snapshot_root = snapshot_child.fd_path
        try:
            snapshot_child.assert_current()
            snapshot_composite_binding = snapshot_child.create_bound_child("composite")
            # Existing controller validators normalize their argument through
            # ``Path`` and reject a bare procfs fd symlink.  These
            # descriptor-relative child paths retain a final real directory
            # component while the held child FDs remain the copy authority.
            snapshot_composite = snapshot_composite_binding.bound_path
            snapshot_composite_binding.assert_current()
            _copy_overlay_snapshot(composite, snapshot_composite_binding, code="FINAL_CHARACTER_COMPOSITE_OVERLAY_INVALID", label="Composite")
            snapshot_child.assert_current()
            snapshot_child.assert_current()
            snapshot_composite_binding.assert_current()
            composite_snapshot_hash = _tree_hash(snapshot_composite_binding.fd_path)
            expected_composite_files_tree = reviewed["composite_overlay"]["files_tree_sha256"]
            if composite_snapshot_hash != expected_composite_files_tree:
                raise _error("FINAL_CHARACTER_OVERLAY_BINDING_MISMATCH", "The detached Composite snapshot does not match its reviewed tree binding.", details={"composite": composite_snapshot_hash})
            if reviewed is not None:
                try:
                    snapshot_composite_binding.assert_current()
                    preflight_composite = CompositeControllerAuthoring.validate_overlay(
                        snapshot_composite,
                        project_id=project_id,
                        candidate_sha256=candidate_sha256,
                        projection_id=projection_id,
                        source_workspace=source,
                    )
                    _validate_reviewed_binding_against_evidence(
                        reviewed,
                        project_id=str(project_id),
                        candidate_sha256=str(candidate_sha256),
                        projection_id=str(projection_id),
                        source_workspace_sha256=source_binding_hash,
                        composite_validated=preflight_composite,
                        composite_overlay_files_tree_sha256=composite_snapshot_hash,
                        composite_overlay_root=snapshot_composite_binding.fd_path,
                        constructed_immortal_arts=constructed_immortal_art_binding(source),
                    )
                except FoundryError as exc:
                    if exc.code == "FINAL_CHARACTER_OVERLAY_BINDING_MISMATCH":
                        raise
                    raise _error(
                        "FINAL_CHARACTER_OVERLAY_REJECTED",
                        "The persisted reviewed pair failed fresh source-bound validation.",
                        details={"cause": exc.code, "message": exc.message},
                    ) from exc
                except Exception as exc:
                    raise _error(
                        "FINAL_CHARACTER_OVERLAY_REJECTED",
                        "The persisted reviewed pair produced malformed validation evidence.",
                        details={"error": type(exc).__name__},
                    ) from exc
                if _tree_hash(snapshot_composite_binding.fd_path) != composite_snapshot_hash:
                    raise _error(
                        "FINAL_CHARACTER_OVERLAY_SNAPSHOT_CHANGED",
                        "A reviewed overlay snapshot changed during source-bound validation.",
                    )
                snapshot_composite_binding.assert_current()
                snapshot_child.assert_current()
            snapshot_composite_binding.assert_current()
            result = self._materialize_legacy(
                source,
                snapshot_composite,
                output_binding.display_path if output_binding is not None else output_parent,
                project_id=project_id,
                candidate_sha256=candidate_sha256,
                projection_id=projection_id,
                expected_composite_overlay_id=expected_composite_overlay_id,
                expected_composite_artifact_sha256=expected_composite_artifact_sha256,
                expected_composite_overlay_tree_sha256=expected_composite_overlay_tree_sha256,
                review_record=review_record,
                output_binding=output_binding,
                composite_binding=snapshot_composite_binding,
            )
            if isinstance(result, dict):
                candidate_binding = result.pop("_published_binding", None)
                if candidate_binding is not None and not isinstance(candidate_binding, _BoundChildDirectory):
                    raise _error("FINAL_CHARACTER_OUTPUT_INVALID", "The materializer returned an invalid published-directory binding.")
                published_result_binding = candidate_binding
            # A validator or injected observer must not be able to mutate a
            # snapshot after validation and before the caller receives a
            # result.  Any such mutation invalidates the newly built bundle.
            snapshot_child.assert_current()
            snapshot_composite_binding.assert_current()
            if _tree_hash(snapshot_composite_binding.fd_path) != composite_snapshot_hash:
                if output_binding is not None and isinstance(result, Mapping) and result.get("idempotent") is not True:
                    materialization_id = result.get("materialization_id")
                    if isinstance(materialization_id, str) and published_result_binding is not None:
                        published_result_binding.cleanup()
                        published_result_binding = None
                raise _error("FINAL_CHARACTER_OVERLAY_SNAPSHOT_CHANGED", "A validated overlay snapshot changed during materialization.")
            if output_binding is not None:
                output_binding.assert_current_path()
            if published_result_binding is not None:
                published_result_binding.close()
                published_result_binding = None
            return result
        finally:
            if published_result_binding is not None:
                published_result_binding.cleanup()
            if snapshot_composite_binding is not None:
                snapshot_composite_binding.close()
            if snapshot_child is not None:
                snapshot_child.cleanup()
            if output_binding is not None:
                output_binding.close()

    apply = materialize


def materialize_final_character(
    source_workspace: Path | str,
    composite_overlay: Path | str,
    output_root: Path | str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Functional facade for callers that do not need a configured instance."""

    return FinalCharacterMaterializer().materialize(source_workspace, composite_overlay, output_root, **kwargs)


__all__ = [
    "FINAL_CHARACTER_COMPILER_OUTPUT_DIRNAME",
    "FINAL_CHARACTER_COMPILER_SHA256",
    "FINAL_CHARACTER_CORPUS_SHA256",
    "FINAL_CHARACTER_STATE_ROOT_ENV",
    "FINAL_CHARACTER_DEFAULT_STATE_ROOT",
    "FINAL_CHARACTER_DEFAULT_FACTORY_ROOT",
    "FINAL_CHARACTER_FACTORY_ROOT_SHA256",
    "FINAL_CHARACTER_DEFAULT_COMPILER",
    "FINAL_CHARACTER_DEFAULT_CORPUS",
    "FINAL_CHARACTER_REVIEWED_BINDING_SCHEMA",
    "FINAL_CHARACTER_REVIEW_RECORD_SCHEMA",
    "FINAL_CHARACTER_REVIEW_RECORD_DOMAIN",
    "FINAL_CHARACTER_REVIEW_RECORD_PREFIX",
    "FINAL_CHARACTER_REVIEW_APPROVAL_OPERATION",
    "FINAL_CHARACTER_REVIEW_APPROVAL_SUBJECT_TYPE",
    "FINAL_CHARACTER_REVIEW_APPROVAL_CONTEXT_SCHEMA",
    "FINAL_CHARACTER_MATERIALIZER_SCHEMA",
    "FINAL_CHARACTER_RECEIPT_NAME",
    "FINAL_CHARACTER_RECEIPT_SCHEMA",
    "FINAL_CHARACTER_RUNTIME_CONTROLLER_SCHEMA",
    "FinalCharacterReviewAuthority",
    "FinalCharacterReviewIssuer",
    "FinalCharacterMaterializer",
    "materialize_final_character",
]
