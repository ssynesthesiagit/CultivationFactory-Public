from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import secrets
import shutil
import struct
import time
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .canonical import canonical_bytes, canonical_sha256, sha256_file
from .choice_authority import canonicalize_option_selection, validate_option_selection
from .diagnostics import CombatGate1Error
from .gate2_runtime_content import ACTORS, BAI, CUI
from .footprint_registry import resolve_actor_footprint
from .gate2_grid import SquareGrid
from .gate2_runtime_models import ActionIntent, CombatEvent, Position, ReactionDecision, RollRecord
from .gate3_reducer import canonical_state_sha256
from .gate3_storage import Gate3MatchStore
from .gate4_adapters import ManualControllerAdapter
from .gate4_context import build_decision_context, build_reaction_context
from .gate4_controller import LocalDeterministicController
from .gate4_engine import Gate4ControllerEngine
from .gate4_models import DecisionRecord, ReactionContext
from .gate4_persistence import Gate4Persistence, Gate4PersistentSession, _read_jsonl
from .gate4_policy import PolicyLibrary
from .history_feed import format_history_feed
from .presentation import CombatPresentationProjector
from .pre_encounter import CombatantLibraryService
from .historical_match_compat import (
    EXPECTED_FINAL_STATE_SHA256 as HISTORICAL_FINAL_STATE_SHA256,
    stored_historical_summary,
    validate_exact_completed_predecessor,
)
from .portable_runtime_authority import (
    PortableRuntimeAuthority, build_runtime_authority, runtime_actor_id,
    RUNTIME_AUTHORITY_FILE, SOURCE_PACKAGE_FILE,
)


CONTROL_MODES = ("MANUAL", "SUGGESTED", "LOCAL_AUTO", "API_AUTO", "MANUAL_AI_BRIDGE")
MANUAL_SUBMIT_MODES = frozenset({"MANUAL", "SUGGESTED", "MANUAL_AI_BRIDGE"})
READINESS_STATUSES = (
    "COMBAT_READY",
    "COMBAT_PROJECTION_INCOMPLETE",
    "UNSUPPORTED_MECHANICS",
    "REQUIRES_RECOMPILATION",
)
INTEGRATION_SCHEMA = "TianxiaFactoryCombatIntegration.v1"
AI_FRAME_SCHEMA = "TianxiaFactoryCombatAIDecisionFrame.v1"
AI_RESPONSE_SCHEMA = "TianxiaFactoryCombatAIIntent.v1"
MATCH_ID_RE = re.compile(r"^match:[a-f0-9]{24}$")
VISUAL_ASSET_FILE_RE = re.compile(r"^[a-f0-9]{64}\.(?:png|jpg|webp)$")
MAX_CUSTOM_VISUAL_BYTES = 12 * 1024 * 1024
VISUAL_PROFILE_SCHEMA = "TianxiaFactoryCombatVisualProfile.v1"
MATCH_VISUAL_SCHEMA = "TianxiaFactoryCombatMatchVisuals.v1"
COMBAT_PROVIDER_SYSTEM_MESSAGE = (
    "You are an untrusted Tianxia combat decision adapter. Return exactly one JSON object "
    "matching TianxiaFactoryCombatAIIntent.v1. Select only IDs and option combinations offered "
    "in the supplied Decision Frame. Do not invent mechanics, targets, destinations, IDs, rolls, "
    "statistics, tools, or instructions. The local deterministic combat runtime validates every "
    "field and remains the sole mechanical authority."
)

DIAGNOSTIC_CATALOG = {
    "COMBAT_SERVICE_UNAVAILABLE": "The in-process CombatService could not initialize or answer.",
    "COMBAT_CONTENT_NOT_READY": "Required bound combat content is absent, unsupported, or not executable.",
    "COMBAT_MATCH_NOT_FOUND": "The requested persistent match does not exist or cannot be addressed safely.",
    "COMBAT_MATCH_ALREADY_COMPLETE": "The match is terminal and cannot accept another combat decision.",
    "COMBAT_MATCH_PAUSED": "A mutating auto-control operation was requested while the match is paused.",
    "COMBAT_CONTROL_MODE_INVALID": "A participant control mode is not one of the Gate 5 supported modes.",
    "COMBAT_CONTROLLER_MODE_MISMATCH": "The requested controller path does not own the active fighter at this decision boundary.",
    "COMBAT_DECISION_STALE": "The submitted decision does not bind the current immutable decision context.",
    "COMBAT_PREVIEW_MISMATCH": "Authoritative execution did not bind or reproduce the checked deterministic preview.",
    "COMBAT_REACTION_DECISION_REQUIRED": "An actual deterministic reaction checkpoint requires manual input.",
    "COMBAT_AI_INTENT_INVALID": "A pasted AI intent or reaction contains unknown, illegal, or invented values.",
    "COMBAT_EXPORT_FAILED": "The persistent match could not be exported to a checksummed local package.",
    "COMBAT_UI_DATA_INVALID": "Factory integration metadata or setup input is invalid.",
    "COMBAT_OPERATION_SLOW": "A measured local combat operation exceeded its practical responsiveness target.",
}


@dataclass(frozen=True)
class CombatServiceDiagnostic:
    code: str
    message: str
    subsystem: str
    retry_safe: bool
    recommended_action: str
    match_id: str | None = None
    actor_id: str | None = None
    decision_id: str | None = None
    details: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "subsystem": self.subsystem,
            "retry_safe": self.retry_safe,
            "recommended_action": self.recommended_action,
            "match_id": self.match_id,
            "actor_id": self.actor_id,
            "decision_id": self.decision_id,
            "details": self.details or {},
        }


class CombatServiceError(Exception):
    def __init__(self, diagnostic: CombatServiceDiagnostic, *, status_code: int = 400):
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic
        self.status_code = status_code

    def to_dict(self) -> dict[str, Any]:
        return {"error": self.diagnostic.as_dict()}


class _ReactionRequired(RuntimeError):
    def __init__(
        self,
        context: ReactionContext,
        suggestion: dict[str, Any] | None,
        *,
        resolved_reactions: tuple[ReactionDecision, ...] = (),
        reaction_records: tuple[dict[str, Any], ...] = (),
    ):
        super().__init__("COMBAT_REACTION_DECISION_REQUIRED")
        self.context = context
        self.suggestion = suggestion
        self.resolved_reactions = resolved_reactions
        self.reaction_records = reaction_records


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    with temporary.open("wb") as handle:
        handle.write(canonical_bytes(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _write_once_exact_json(path: Path, value: dict[str, Any]) -> None:
    payload = canonical_bytes(value) + b"\n"
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f"immutable artifact mismatch: {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _safe_zip_name(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace(os.sep, "/")


class CombatService:
    """Application-facing Gate 5 integration over the accepted Gate 2–Gate 4 stack."""

    def __init__(self, source_root: Path, userdata_root: Path, *, ai_provider: Any | None = None):
        started = time.perf_counter()
        self.source_root = Path(source_root).resolve()
        self.userdata_root = Path(userdata_root).resolve()
        self.persistence = Gate4Persistence(self.source_root, self.userdata_root)
        self.combatant_library = CombatantLibraryService(self.source_root, self.userdata_root)
        self.controller = LocalDeterministicController()
        self.policies = PolicyLibrary(self.source_root)
        self.presenter = CombatPresentationProjector(self.source_root)
        self.ai_provider = ai_provider
        self.combat_root = self.userdata_root / "Combat"
        self.matches_root = self.combat_root / "Matches"
        self.exports_root = self.combat_root / "Exports"
        self.performance_path = self.combat_root / "Performance.ndjson"
        self.visual_manifest_path = self.source_root / "static" / "combat_visuals" / "manifest.json"
        self.visual_profile_root = self.combat_root / "VisualProfile"
        self.visual_profile_assets_root = self.visual_profile_root / "Assets"
        self.visual_profile_path = self.visual_profile_root / "Profile.json"
        self._visual_manifest = self._load_visual_manifest()
        self._definition_names = self._load_definition_names()
        self.matches_root.mkdir(parents=True, exist_ok=True)
        self.exports_root.mkdir(parents=True, exist_ok=True)
        self._catalog_cache = self._load_catalog()
        self.startup_us = max(1, round((time.perf_counter() - started) * 1_000_000))
        self.startup_ms = max(1, round(self.startup_us / 1000))
        self._record_metric("service_startup", self.startup_us, threshold_ms=2000)

    # ------------------------------------------------------------------
    # Diagnostics and timing
    # ------------------------------------------------------------------
    def _error(
        self,
        code: str,
        message: str,
        *,
        subsystem: str,
        retry_safe: bool,
        recommended_action: str,
        match_id: str | None = None,
        actor_id: str | None = None,
        decision_id: str | None = None,
        details: dict[str, Any] | None = None,
        status_code: int = 400,
    ) -> CombatServiceError:
        return CombatServiceError(
            CombatServiceDiagnostic(
                code=code,
                message=message,
                subsystem=subsystem,
                retry_safe=retry_safe,
                recommended_action=recommended_action,
                match_id=match_id,
                actor_id=actor_id,
                decision_id=decision_id,
                details=details,
            ),
            status_code=status_code,
        )

    def _record_metric(self, operation: str, duration_us: int, *, threshold_ms: int) -> None:
        row = {
            "schema": "TianxiaFactoryCombatPerformanceRecord.v1",
            "recorded_at": _utcnow(),
            "operation": operation,
            "duration_us": int(duration_us),
            "duration_ms": max(1, round(int(duration_us) / 1000)),
            "threshold_ms": threshold_ms,
            "slow": int(duration_us) > threshold_ms * 1000,
        }
        self.performance_path.parent.mkdir(parents=True, exist_ok=True)
        with self.performance_path.open("ab") as handle:
            handle.write(canonical_bytes(row) + b"\n")

    @contextmanager
    def _timed(self, operation: str, *, threshold_ms: int):
        started = time.perf_counter()
        box: dict[str, int] = {}
        try:
            yield box
        finally:
            box["duration_us"] = max(1, round((time.perf_counter() - started) * 1_000_000))
            box["duration_ms"] = max(1, round(box["duration_us"] / 1000))
            self._record_metric(operation, box["duration_us"], threshold_ms=threshold_ms)

    def performance(self, limit: int = 50) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        if self.performance_path.is_file():
            for line in self.performance_path.read_text(encoding="utf-8").splitlines()[-limit:]:
                if line.strip():
                    rows.append(json.loads(line))
        slow = [row for row in rows if row.get("slow")]
        return {
            "schema": "TianxiaFactoryCombatPerformanceStatus.v1",
            "service_startup_ms": self.startup_ms,
            "recent": rows,
            "slow_operations": slow,
            "diagnostic": (
                CombatServiceDiagnostic(
                    code="COMBAT_OPERATION_SLOW",
                    message="One or more measured combat operations exceeded the practical local target.",
                    subsystem="combat.gate5.performance",
                    retry_safe=True,
                    recommended_action="Inspect the named operation for repeated loading, serialization, or filesystem work before adding infrastructure.",
                    details={"count": len(slow)},
                ).as_dict()
                if slow else None
            ),
        }

    def _load_visual_manifest(self) -> dict[str, Any]:
        document = json.loads(self.visual_manifest_path.read_text(encoding="utf-8"))
        if document.get("schema") != "TianxiaFactoryBattleVisualAssets.v1":
            raise ValueError("unsupported battle visual asset manifest schema")
        visual_root = self.visual_manifest_path.parent.resolve()
        for row in [*document.get("maps", []), *document.get("tokens", [])]:
            relative = str(row.get("file") or "")
            candidate = (visual_root / relative).resolve()
            if not relative or candidate.parent != visual_root or not candidate.is_file():
                raise ValueError(f"unsafe or missing battle visual asset: {relative}")
            expected = row.get("sha256")
            actual = sha256_file(candidate)
            if expected != actual:
                raise ValueError(f"battle visual asset identity mismatch: {relative}")
        return document

    def _load_definition_names(self) -> dict[str, str]:
        path = self.source_root / "combat_gate2" / "generated" / "Gate2_Executable_Mechanics_Lock.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        names: dict[str, str] = {}

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                stable_id = value.get("source_definition_id")
                display_name = value.get("display_name")
                if isinstance(stable_id, str) and isinstance(display_name, str):
                    names.setdefault(stable_id, display_name)
                for nested in value.values():
                    visit(nested)
            elif isinstance(value, list):
                for nested in value:
                    visit(nested)

        visit(document)
        return names

    @staticmethod
    def _image_type(data: bytes) -> tuple[str, str]:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png", "png"
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg", "jpg"
        if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp", "webp"
        raise ValueError("Only PNG, JPEG, and WebP images are accepted.")

    @staticmethod
    def _image_dimensions(data: bytes, media_type: str) -> tuple[int, int]:
        """Read dimensions without decoding pixels or adding a runtime dependency."""

        if media_type == "image/png":
            if len(data) < 24 or data[12:16] != b"IHDR":
                raise ValueError("The PNG header is incomplete.")
            width, height = struct.unpack(">II", data[16:24])
        elif media_type == "image/jpeg":
            index = 2
            width = height = 0
            sof_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
            while index + 4 <= len(data):
                if data[index] != 0xFF:
                    index += 1
                    continue
                while index < len(data) and data[index] == 0xFF:
                    index += 1
                if index >= len(data):
                    break
                marker = data[index]
                index += 1
                if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
                    continue
                if index + 2 > len(data):
                    break
                segment_length = int.from_bytes(data[index:index + 2], "big")
                if segment_length < 2 or index + segment_length > len(data):
                    break
                if marker in sof_markers:
                    if segment_length < 7:
                        break
                    height = int.from_bytes(data[index + 3:index + 5], "big")
                    width = int.from_bytes(data[index + 5:index + 7], "big")
                    break
                index += segment_length
            if not width or not height:
                raise ValueError("The JPEG dimensions could not be read safely.")
        elif media_type == "image/webp":
            if len(data) < 30:
                raise ValueError("The WebP header is incomplete.")
            chunk = data[12:16]
            if chunk == b"VP8X":
                width = 1 + int.from_bytes(data[24:27], "little")
                height = 1 + int.from_bytes(data[27:30], "little")
            elif chunk == b"VP8L":
                if data[20] != 0x2F:
                    raise ValueError("The lossless WebP header is invalid.")
                bits = int.from_bytes(data[21:25], "little")
                width = (bits & 0x3FFF) + 1
                height = ((bits >> 14) & 0x3FFF) + 1
            elif chunk == b"VP8 ":
                if data[23:26] != b"\x9d\x01\x2a":
                    raise ValueError("The lossy WebP frame header is invalid.")
                width = int.from_bytes(data[26:28], "little") & 0x3FFF
                height = int.from_bytes(data[28:30], "little") & 0x3FFF
            else:
                raise ValueError("The WebP image uses an unsupported frame header.")
        else:
            raise ValueError("Unsupported image type.")
        if not (1 <= width <= 100_000 and 1 <= height <= 100_000):
            raise ValueError("The image dimensions are outside the accepted range.")
        return width, height

    def _default_visual_profile(self) -> dict[str, Any]:
        return {
            "schema": VISUAL_PROFILE_SCHEMA,
            "version": "1.0.0",
            "background": None,
            "tokens": {},
            "updated_at": None,
        }

    def _read_visual_profile(self) -> dict[str, Any]:
        if not self.visual_profile_path.is_file():
            return self._default_visual_profile()
        try:
            document = json.loads(self.visual_profile_path.read_text(encoding="utf-8"))
            if document.get("schema") != VISUAL_PROFILE_SCHEMA:
                raise ValueError("visual profile schema mismatch")
            tokens = document.get("tokens")
            if not isinstance(tokens, dict):
                raise ValueError("visual profile token assignments are invalid")
            return document
        except Exception as exc:
            raise self._error(
                "COMBAT_UI_DATA_INVALID",
                "The saved combat visual profile is invalid.",
                subsystem="combat.gate5.visual_profile",
                retry_safe=False,
                recommended_action="Restore or remove only Combat/VisualProfile/Profile.json; saved matches and mechanics remain separate.",
                details={"reason": str(exc)},
                status_code=409,
            ) from exc

    def _write_visual_profile(self, document: dict[str, Any]) -> None:
        document = {**document, "schema": VISUAL_PROFILE_SCHEMA, "version": "1.0.0", "updated_at": _utcnow()}
        _atomic_json(self.visual_profile_path, document)

    def _custom_visual_row(self, assignment: dict[str, Any], *, actor_id: str | None = None) -> dict[str, Any]:
        stored_name = str(assignment["stored_name"])
        width_px = assignment.get("width_px")
        height_px = assignment.get("height_px")
        if not width_px or not height_px:
            # Backward-compatible read of a pre-E3 visual profile. This does not
            # rewrite owner data and does not upgrade decorative status to exact.
            try:
                source = self.visual_profile_asset_path(stored_name)
                raw = source.read_bytes()
                width_px, height_px = self._image_dimensions(raw, str(assignment["media_type"]))
            except (OSError, ValueError, KeyError):
                width_px = height_px = None
        row = {
            "asset_id": assignment["asset_id"],
            "file": stored_name,
            "public_url": f"/api/combat/setup-visuals/assets/{stored_name}",
            "sha256": assignment["sha256"],
            "media_type": assignment["media_type"],
            "source": "owner_upload",
            "original_filename": assignment.get("original_filename"),
            "storage_file": stored_name,
            "width_px": width_px,
            "height_px": height_px,
        }
        if actor_id is None:
            calibration = assignment.get("calibration")
            if isinstance(calibration, dict):
                row["calibration"] = json.loads(json.dumps(calibration))
            else:
                row["calibration"] = {
                    "schema": "TianxiaBattleMapCalibration.v1",
                    "fit_mode": "cover",
                    "position_x_percent": 50,
                    "position_y_percent": 50,
                    "scale_percent": 100,
                    "note": "Legacy owner-selected decorative background. Battlefield dimensions remain mechanically authoritative.",
                }
        else:
            row["stable_actor_ids"] = [actor_id]
        return row

    def _effective_visual_manifest(self, *, include_storage: bool = False) -> dict[str, Any]:
        document = json.loads(json.dumps(self._visual_manifest))
        for row in [*document.get("maps", []), *document.get("tokens", [])]:
            row["source"] = "built_in"
        profile = self._read_visual_profile()
        background = profile.get("background")
        if isinstance(background, dict):
            custom_map = self._custom_visual_row(background)
            document["maps"] = [custom_map, *document.get("maps", [])]
            document["default_map_asset_id"] = custom_map["asset_id"]
        custom_tokens = []
        assigned_ids = set()
        for actor_id, assignment in sorted(profile.get("tokens", {}).items()):
            if isinstance(assignment, dict):
                custom_tokens.append(self._custom_visual_row(assignment, actor_id=actor_id))
                assigned_ids.add(actor_id)
        built_in_tokens = [
            row for row in document.get("tokens", [])
            if not assigned_ids.intersection(row.get("stable_actor_ids") or [])
        ]
        document["tokens"] = [*custom_tokens, *built_in_tokens]
        document["profile"] = {
            "schema": VISUAL_PROFILE_SCHEMA,
            "updated_at": profile.get("updated_at"),
            "custom_background": isinstance(background, dict),
            "custom_token_actor_ids": sorted(assigned_ids),
        }
        if not include_storage:
            for row in [*document.get("maps", []), *document.get("tokens", [])]:
                row.pop("storage_file", None)
        return document

    def visual_assets(self) -> dict[str, Any]:
        return self._effective_visual_manifest()

    def save_visual_upload(
        self,
        *,
        kind: str,
        actor_id: str | None,
        original_filename: str,
        declared_media_type: str,
        data_base64: str,
        calibration_mode: str = "COVER_DECORATIVE",
        playable_rect_pixels: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        if kind not in {"background", "token"}:
            raise self._error(
                "COMBAT_UI_DATA_INVALID",
                "The visual upload kind is invalid.",
                subsystem="combat.gate5.visual_profile",
                retry_safe=True,
                recommended_action="Upload a battlefield background or a fighter token.",
            )
        valid_actor_ids = {
            row["runtime_entity_id"]
            for row in self._catalog_cache["projections"]
            if row.get("primary_combatant")
        }
        if kind == "token" and actor_id not in valid_actor_ids:
            raise self._error(
                "COMBAT_UI_DATA_INVALID",
                "The token was not assigned to a current combat-ready fighter.",
                subsystem="combat.gate5.visual_profile",
                retry_safe=True,
                recommended_action="Choose one of the fighter cards shown in Combat Setup.",
                details={"valid_actor_ids": sorted(valid_actor_ids)},
            )
        if kind == "background":
            actor_id = None
        try:
            encoded = str(data_base64 or "").strip()
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise self._error(
                "COMBAT_UI_DATA_INVALID",
                "The uploaded image data is not valid base64.",
                subsystem="combat.gate5.visual_profile",
                retry_safe=True,
                recommended_action="Choose the image file again and retry.",
                status_code=422,
            ) from exc
        if not raw or len(raw) > MAX_CUSTOM_VISUAL_BYTES:
            raise self._error(
                "COMBAT_UI_DATA_INVALID",
                "Combat visual images must be between 1 byte and 12 MiB.",
                subsystem="combat.gate5.visual_profile",
                retry_safe=True,
                recommended_action="Use a PNG, JPEG, or WebP image no larger than 12 MiB.",
                details={"bytes": len(raw), "maximum_bytes": MAX_CUSTOM_VISUAL_BYTES},
                status_code=422,
            )
        try:
            media_type, extension = self._image_type(raw)
        except ValueError as exc:
            raise self._error(
                "COMBAT_UI_DATA_INVALID",
                str(exc),
                subsystem="combat.gate5.visual_profile",
                retry_safe=True,
                recommended_action="Use a PNG, JPEG, or WebP file.",
                status_code=422,
            ) from exc
        if declared_media_type and declared_media_type.lower() not in {media_type, "image/jpg" if media_type == "image/jpeg" else media_type}:
            raise self._error(
                "COMBAT_UI_DATA_INVALID",
                "The image content does not match its declared media type.",
                subsystem="combat.gate5.visual_profile",
                retry_safe=True,
                recommended_action="Re-export the image as PNG, JPEG, or WebP and upload it again.",
                details={"declared": declared_media_type, "detected": media_type},
                status_code=422,
            )
        try:
            width_px, height_px = self._image_dimensions(raw, media_type)
        except ValueError as exc:
            raise self._error(
                "COMBAT_UI_DATA_INVALID",
                str(exc),
                subsystem="combat.gate5.visual_profile",
                retry_safe=True,
                recommended_action="Re-export the image as a standard PNG, JPEG, or WebP file.",
                status_code=422,
            ) from exc
        digest = hashlib.sha256(raw).hexdigest()
        stored_name = f"{digest}.{extension}"
        assignment = {
            "asset_id": f"{kind}:owner:{(actor_id or 'battlefield')}:{digest[:16]}",
            "stored_name": stored_name,
            "sha256": digest,
            "media_type": media_type,
            "original_filename": Path(original_filename or stored_name).name[:240],
            "width_px": width_px,
            "height_px": height_px,
        }
        if kind == "background":
            if calibration_mode not in {"EXACT_PLAYABLE_RECT", "COVER_DECORATIVE", "CONTAIN_DECORATIVE"}:
                raise self._error(
                    "COMBAT_UI_DATA_INVALID",
                    "The requested battlefield-map calibration mode is unsupported.",
                    subsystem="combat.gate5.visual_profile",
                    retry_safe=True,
                    recommended_action="Choose Exact gridless map, Decorative cover, or Decorative contain.",
                    status_code=422,
                )
            rect = dict(playable_rect_pixels or {"x": 0, "y": 0, "width": width_px, "height": height_px})
            try:
                rect = {key: int(rect[key]) for key in ("x", "y", "width", "height")}
            except (KeyError, TypeError, ValueError) as exc:
                raise self._error(
                    "COMBAT_UI_DATA_INVALID",
                    "The battlefield playable rectangle is incomplete.",
                    subsystem="combat.gate5.visual_profile",
                    retry_safe=True,
                    recommended_action="Use the full image or supply x, y, width, and height in source pixels.",
                    status_code=422,
                ) from exc
            if rect["x"] < 0 or rect["y"] < 0 or rect["width"] < 1 or rect["height"] < 1 or rect["x"] + rect["width"] > width_px or rect["y"] + rect["height"] > height_px:
                raise self._error(
                    "COMBAT_UI_DATA_INVALID",
                    "The battlefield playable rectangle extends outside the uploaded image.",
                    subsystem="combat.gate5.visual_profile",
                    retry_safe=True,
                    recommended_action="Use a playable rectangle fully contained by the source image.",
                    status_code=422,
                )
            battlefield = self._catalog_cache["battlefields"][0]
            grid_width = int(battlefield["width_squares"])
            grid_height = int(battlefield["height_squares"])
            if calibration_mode == "EXACT_PLAYABLE_RECT":
                lhs = rect["width"] * grid_height
                rhs = rect["height"] * grid_width
                if abs(lhs - rhs) > max(lhs, rhs) * 0.001:
                    raise self._error(
                        "COMBAT_UI_DATA_INVALID",
                        "The exact gridless-map playable rectangle does not match the battlefield aspect ratio.",
                        subsystem="combat.gate5.visual_profile",
                        retry_safe=True,
                        recommended_action=f"Crop or export the playable map at the {grid_width}:{grid_height} battlefield ratio, then upload it as Exact.",
                        details={
                            "battlefield_ratio": f"{grid_width}:{grid_height}",
                            "playable_rect": rect,
                            "source_dimensions": {"width": width_px, "height": height_px},
                        },
                        status_code=422,
                    )
            assignment["calibration"] = {
                "schema": "TianxiaBattleMapCalibration.v2",
                "authority": "PRESENTATION_ONLY",
                "grid_width_squares": grid_width,
                "grid_height_squares": grid_height,
                "source_pixel_width": width_px,
                "source_pixel_height": height_px,
                "playable_rect_pixels": rect,
                "fit_mode": calibration_mode,
                "position_x_percent": 50,
                "position_y_percent": 50,
                "asset_sha256": digest,
            }
        self.visual_profile_assets_root.mkdir(parents=True, exist_ok=True)
        destination = self.visual_profile_assets_root / stored_name
        if not destination.exists():
            temporary = destination.with_name(destination.name + f".tmp.{os.getpid()}.{secrets.token_hex(4)}")
            with temporary.open("xb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        elif sha256_file(destination) != digest:
            raise self._error(
                "COMBAT_UI_DATA_INVALID",
                "A saved visual asset failed its content identity check.",
                subsystem="combat.gate5.visual_profile",
                retry_safe=False,
                recommended_action="Inspect only the Combat/VisualProfile asset directory before retrying.",
                status_code=409,
            )
        profile = self._read_visual_profile()
        if kind == "background":
            profile["background"] = assignment
        else:
            tokens = dict(profile.get("tokens") or {})
            tokens[str(actor_id)] = assignment
            profile["tokens"] = tokens
        self._write_visual_profile(profile)
        return self._effective_visual_manifest()

    def reset_visual_upload(self, *, kind: str, actor_id: str | None = None) -> dict[str, Any]:
        profile = self._read_visual_profile()
        if kind == "background":
            profile["background"] = None
        elif kind == "token":
            tokens = dict(profile.get("tokens") or {})
            tokens.pop(str(actor_id or ""), None)
            profile["tokens"] = tokens
        else:
            raise self._error(
                "COMBAT_UI_DATA_INVALID",
                "The visual reset kind is invalid.",
                subsystem="combat.gate5.visual_profile",
                retry_safe=True,
                recommended_action="Reset the battlefield background or one fighter token.",
            )
        self._write_visual_profile(profile)
        return self._effective_visual_manifest()

    def visual_profile_asset_path(self, stored_name: str) -> Path:
        if not VISUAL_ASSET_FILE_RE.fullmatch(stored_name):
            raise self._error(
                "COMBAT_MATCH_NOT_FOUND",
                "The requested combat visual asset is unavailable.",
                subsystem="combat.gate5.visual_profile",
                retry_safe=False,
                recommended_action="Use the image URL returned by the combat visual profile.",
                status_code=404,
            )
        path = self.visual_profile_assets_root / stored_name
        if not path.is_file() or path.parent.resolve() != self.visual_profile_assets_root.resolve():
            raise self._error(
                "COMBAT_MATCH_NOT_FOUND",
                "The requested combat visual asset is unavailable.",
                subsystem="combat.gate5.visual_profile",
                retry_safe=False,
                recommended_action="Upload the image again from Combat Setup.",
                status_code=404,
            )
        return path

    def _snapshot_match_visuals(self, match_id: str) -> dict[str, Any]:
        manifest = self._effective_visual_manifest(include_storage=True)
        match_dir = self._match_dir(match_id)
        visual_dir = match_dir / "VisualAssets"

        def snapshot_row(row: dict[str, Any], *, prefix: str) -> dict[str, Any]:
            result = json.loads(json.dumps(row))
            stored_name = result.pop("storage_file", None)
            if result.get("source") != "owner_upload" or not stored_name:
                return result
            source = self.visual_profile_asset_path(stored_name)
            visual_dir.mkdir(parents=True, exist_ok=True)
            destination_name = f"{prefix}_{stored_name}"
            destination = visual_dir / destination_name
            if not destination.exists():
                shutil.copyfile(source, destination)
            if sha256_file(destination) != result["sha256"]:
                raise ValueError(f"match visual snapshot identity mismatch: {destination_name}")
            result["file"] = destination_name
            result["public_url"] = f"/api/combat/matches/{match_id}/visual-assets/{destination_name}"
            result["source"] = "match_snapshot"
            return result

        maps = manifest.get("maps") or []
        selected_map = next(
            (row for row in maps if row.get("asset_id") == manifest.get("default_map_asset_id")),
            maps[0] if maps else None,
        )
        map_row = snapshot_row(selected_map, prefix="background") if selected_map else None
        tokens = {}
        for projection in self._catalog_cache["projections"]:
            if not projection.get("primary_combatant"):
                continue
            actor_id = projection["runtime_entity_id"]
            row = next((item for item in manifest.get("tokens", []) if actor_id in (item.get("stable_actor_ids") or [])), None)
            if row:
                tokens[actor_id] = snapshot_row(row, prefix=f"token_{actor_id}")
        return {
            "schema": MATCH_VISUAL_SCHEMA,
            "map": map_row,
            "tokens": tokens,
            "profile_updated_at": manifest.get("profile", {}).get("updated_at"),
            "mechanical_authority": False,
        }

    def match_visual_asset_path(self, match_id: str, filename: str) -> Path:
        if not re.fullmatch(r"(?:background|token_[A-Za-z0-9_.-]+)_[a-f0-9]{64}\.(?:png|jpg|webp)", filename):
            raise self._error(
                "COMBAT_MATCH_NOT_FOUND",
                "The requested match visual asset is unavailable.",
                subsystem="combat.gate5.visual_profile",
                retry_safe=False,
                recommended_action="Use the visual URL returned with the match.",
                match_id=match_id,
                status_code=404,
            )
        root = self._match_dir(match_id) / "VisualAssets"
        path = root / filename
        if not path.is_file() or path.parent.resolve() != root.resolve():
            raise self._error(
                "COMBAT_MATCH_NOT_FOUND",
                "The requested match visual asset is unavailable.",
                subsystem="combat.gate5.visual_profile",
                retry_safe=False,
                recommended_action="Use the visual URL returned with the match.",
                match_id=match_id,
                status_code=404,
            )
        return path

    # ------------------------------------------------------------------
    # Catalog and readiness
    # ------------------------------------------------------------------
    def _load_catalog(self) -> dict[str, Any]:
        with self._timed("catalog_load", threshold_ms=2000):
            battlefield = json.loads((self.source_root / "combat_gate1/generated/Battlefield.json").read_text(encoding="utf-8"))
            encounter = json.loads((self.source_root / "combat_gate1/generated/Encounter.json").read_text(encoding="utf-8"))
            team_by_registry_id: dict[str, dict[str, Any]] = {}
            teams = []
            for index, team in enumerate(encounter.get("teams") or []):
                team_id = str(team["team_id"])
                display_name = team_id.split(":", 1)[-1].replace("_", " ").title()
                team_row = {
                    "team_id": team_id,
                    "display_name": display_name,
                    "team_index": index,
                    "participant_ids": list(team.get("participant_ids") or []),
                }
                teams.append(team_row)
                for registry_id in team_row["participant_ids"]:
                    team_by_registry_id[registry_id] = team_row
            projections = []
            for path in sorted((self.source_root / "combat_gate1/generated/projections").glob("*.json")):
                wrapper = json.loads(path.read_text(encoding="utf-8"))
                projection = wrapper["projection"]
                registry_id = f"character_mapping:{projection['character_id']}"
                team = team_by_registry_id.get(registry_id) or {"team_id": "team:unassigned", "display_name": "Unassigned", "team_index": 99}
                projections.append({
                    "registry_id": registry_id,
                    "runtime_entity_id": projection["character_id"],
                    "display_name": projection["display_name"],
                    "cultivation_level": projection.get("cultivation_level"),
                    "realm": projection.get("realm"),
                    "projection_sha256": wrapper["projection_sha256"],
                    "readiness_status": "COMBAT_READY",
                    "readiness_reason": "Exact accepted Gate 1/Gate 2 runtime projection.",
                    "primary_combatant": True,
                    "team_id": team["team_id"],
                    "team_display_name": team["display_name"],
                    "team_index": team["team_index"],
                    "character_sheet_identity": registry_id,
                })
            projections.append({
                "registry_id": "creature:bai_cui",
                "runtime_entity_id": "bai_cui",
                "display_name": "Cui",
                "readiness_status": "COMBAT_READY",
                "readiness_reason": "First-class accepted companion controlled through Bai Meizhen's encounter projection.",
                "primary_combatant": False,
                "owner_registry_id": "character_mapping:bai_meizhen_early_outer_sect_cl5",
                "team_id": team_by_registry_id.get("character_mapping:bai_meizhen_early_outer_sect_cl5", {}).get("team_id", "team:unassigned"),
                "team_display_name": team_by_registry_id.get("character_mapping:bai_meizhen_early_outer_sect_cl5", {}).get("display_name", "Unassigned"),
                "team_index": team_by_registry_id.get("character_mapping:bai_meizhen_early_outer_sect_cl5", {}).get("team_index", 99),
            })
            return {
                "schema": "TianxiaFactoryCombatCatalog.v1",
                "readiness_statuses": list(READINESS_STATUSES),
                "projections": projections,
                "battlefields": [{**battlefield, "readiness_status": "COMBAT_READY"}],
                "encounters": [{**encounter, "readiness_status": "COMBAT_READY"}],
                "teams": teams,
                "supported_control_modes": list(CONTROL_MODES),
                "known_limitations": [
                    "Only the accepted CL5 2v2 encounter and Sect Training Court are executable in Gate 5.",
                    "Arbitrary Factory character compilation, roster construction, additional battlefields, tournaments, and direct AI provider transport are deferred.",
                    "The local controller is deterministic one-step heuristic control and does not search future turns.",
                ],
            }

    def status(self) -> dict[str, Any]:
        return {
            "schema": "TianxiaFactoryCombatServiceStatus.v1",
            "available": True,
            "service": "CombatService",
            "integration_gate": 5,
            "mechanical_authority": "GATE2_ENGINE",
            "persistence_authority": "GATE3_JOURNAL_AND_REDUCER",
            "controller_authority": "GATE4_CONTROLLER",
            "matches_directory": str(self.matches_root),
            "catalog_ready": bool(self._catalog_cache["encounters"]),
            "combat_ready_projection_count": sum(1 for p in self.catalog()["projections"] if p["readiness_status"] == "COMBAT_READY"),
            "api_auto": self.ai_provider.status() if self.ai_provider is not None else {"ready": False, "provider_id": None},
            "diagnostic_catalog": DIAGNOSTIC_CATALOG,
            "performance": self.performance(limit=20),
        }

    def _portable_catalog_rows(self) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
        inventory = self.combatant_library.inventory()
        projections: list[dict[str, Any]] = []
        authority: dict[str, dict[str, Any]] = {}
        seen_runtime_ids: dict[str, str] = {}
        for entry in inventory.accepted_candidates:
            actor_id = runtime_actor_id(entry.character_project_id, entry.source_package_sha256)
            prior = seen_runtime_ids.get(actor_id)
            if prior is not None and prior != entry.source_package_sha256:
                raise self._error(
                    "C3D_RUNTIME_ACTOR_ID_COLLISION",
                    "Two different installed packages claim the same portable combat actor identity.",
                    subsystem="combat.c3d.catalog", retry_safe=False,
                    recommended_action="Remove the conflicting installed package and refresh the combat catalog.",
                    details={"runtime_actor_id": actor_id, "first": prior, "second": entry.source_package_sha256},
                    status_code=409,
                )
            seen_runtime_ids[actor_id] = entry.source_package_sha256
            projections.append({
                "registry_id": entry.entry_id,
                "runtime_entity_id": actor_id,
                "display_name": entry.display_name,
                "cultivation_level": None,
                "realm": None,
                "projection_sha256": entry.actor_template_commitment_sha256,
                "team_id": "team:unassigned",
                "team_display_name": "Owner Assigned",
                "team_index": 99,
                "primary_combatant": True,
                "owner_id": entry.character_project_id,
                "character_sheet_identity": entry.combat_sheet_id,
                "readiness_status": "COMBAT_READY",
                "owner_status": "Combat Ready",
                "installed_character": True,
                "candidate_entry_id": entry.entry_id,
                "source_package_sha256": entry.source_package_sha256,
                "project_id": entry.character_project_id,
                "project_revision": entry.project_revision,
                "event_head_hash": entry.event_head_hash,
                "replay_state_hash": entry.replay_state_hash,
                "content_lock_hash": entry.content_lock_hash,
                "combat_sheet_commitment_sha256": entry.combat_sheet_commitment_sha256,
                "mechanics_lock_sha256": entry.mechanics_lock_sha256,
                "primitive_registry_sha256": entry.primitive_registry_sha256,
                "runtime_adapter_id": entry.runtime_adapter_id,
                "runtime_adapter_version": entry.runtime_adapter_version,
                "runtime_engine_version": entry.runtime_engine_version,
                "actor_template_commitment_sha256": entry.actor_template_commitment_sha256,
            })
            authority[actor_id] = {
                "resources": {
                    "qi": {"resource_id": "resource:core.qi", "current": None, "maximum": entry.resource_maxima["resource:core.qi"], "required": True},
                    "martial_focus": {"resource_id": "resource:core.martial_focus", "current": None, "maximum": entry.resource_maxima["resource:core.martial_focus"], "required": True},
                },
                "placement": {"x": 2, "y": 12},
                "footprint": {**entry.footprint_contract, "editable": False},
                "token_asset_id": entry.combat_sheet_id,
                "supported_control_modes": list(CONTROL_MODES),
                "installed_character": True,
                "candidate_entry_id": entry.entry_id,
                "source_package_sha256": entry.source_package_sha256,
                "project_id": entry.character_project_id,
            }
        blocks = [row.model_dump(mode="json") for row in inventory.blocked_candidates]
        return projections, authority, blocks

    def catalog(self) -> dict[str, Any]:
        with self._timed("catalog_request", threshold_ms=2000):
            payload = json.loads(json.dumps(self._catalog_cache))
            battlefield = payload["battlefields"][0]
            authority: dict[str, dict[str, Any]] = {}
            for actor_id, template in ACTORS.items():
                if not template.primary_combatant:
                    continue
                definition, _ = resolve_actor_footprint(actor_id)
                resources = {}
                for resource in template.resources:
                    for owner_name in ("stamina", "qi", "resonance"):
                        if resource.resource_id.endswith(f".{owner_name}"):
                            resources[owner_name] = {"resource_id": resource.resource_id, "current": resource.initial, "maximum": resource.maximum}
                projection = next(row for row in payload["projections"] if row["runtime_entity_id"] == actor_id)
                projection["installed_character"] = False
                projection["owner_status"] = "Combat Ready"
                authority[actor_id] = {
                    "resources": resources,
                    "placement": battlefield["starting_positions"][actor_id],
                    "footprint": {"footprint_id": definition.footprint_id, "width": definition.width_cells, "height": definition.height_cells, "editable": False},
                    "token_asset_id": projection["character_sheet_identity"],
                    "supported_control_modes": list(CONTROL_MODES),
                    "installed_character": False,
                }
            portable_rows, portable_authority, blocks = self._portable_catalog_rows()
            existing_ids = {row["runtime_entity_id"] for row in payload["projections"]}
            for row in portable_rows:
                if row["runtime_entity_id"] in existing_ids:
                    raise self._error(
                        "C3D_RUNTIME_ACTOR_ID_COLLISION",
                        "An installed Character collides with an existing combat actor identity.",
                        subsystem="combat.c3d.catalog", retry_safe=False,
                        recommended_action="Remove the conflicting installed package; built-in actor identities cannot be replaced.",
                        details={"runtime_actor_id": row["runtime_entity_id"]}, status_code=409,
                    )
                payload["projections"].append(row)
                existing_ids.add(row["runtime_entity_id"])
            payload["projections"] = sorted(payload["projections"], key=lambda row: row["runtime_entity_id"])
            authority.update(portable_authority)
            payload["c3c_p1_setup_authority"] = authority
            payload["c3c_p1_scope"] = "DYNAMIC_COMBAT_READY_TWO_TEAM_ROSTER"
            payload["installed_candidate_blocks"] = blocks
            payload["portable_candidate_count"] = len(portable_rows)
            return payload

    # ------------------------------------------------------------------
    # Integration metadata
    # ------------------------------------------------------------------
    def _match_dir(self, match_id: str) -> Path:
        if not MATCH_ID_RE.fullmatch(match_id):
            raise self._error(
                "COMBAT_MATCH_NOT_FOUND",
                "The requested combat match identifier is invalid or unavailable.",
                subsystem="combat.gate5.storage",
                retry_safe=False,
                recommended_action="Select a match returned by the combat match list.",
                match_id=match_id,
                status_code=404,
            )
        return Gate3MatchStore(self.userdata_root, match_id).match_dir

    def _metadata_path(self, match_id: str) -> Path:
        return self._match_dir(match_id) / "FactoryIntegration.json"

    def _write_metadata(self, match_id: str, metadata: dict[str, Any]) -> None:
        metadata = {**metadata, "updated_at": _utcnow()}
        _atomic_json(self._metadata_path(match_id), metadata)

    def _read_metadata(self, match_id: str, session: Gate4PersistentSession | None = None) -> dict[str, Any]:
        path = self._metadata_path(match_id)
        if path.is_file():
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
                if doc.get("schema") != INTEGRATION_SCHEMA or doc.get("match_id") != match_id:
                    raise ValueError("metadata identity mismatch")
                return doc
            except Exception as exc:
                raise self._error(
                    "COMBAT_UI_DATA_INVALID",
                    "The match integration metadata is invalid.",
                    subsystem="combat.gate5.metadata",
                    retry_safe=False,
                    recommended_action="Restore or regenerate only FactoryIntegration.json; the mechanical journal remains authoritative.",
                    match_id=match_id,
                    details={"reason": str(exc)},
                    status_code=409,
                ) from exc
        if session is None:
            session = self._load_session(match_id)
        primary = [actor for actor in session.engine.state.actors.values() if actor.primary_combatant]
        doc = {
            "schema": INTEGRATION_SCHEMA,
            "integration_schema_version": "1.0.0",
            "match_id": match_id,
            "display_name": self._catalog_cache["encounters"][0]["display_name"],
            "encounter_id": self._catalog_cache["encounters"][0]["stable_id"],
            "battlefield_id": self._catalog_cache["battlefields"][0]["stable_id"],
            "participant_control_modes": {actor.entity_id: "MANUAL" for actor in primary},
            "paused": False,
            "local_auto_running": False,
            "ui_preferences": {},
            "visual_assets": {
                "schema": MATCH_VISUAL_SCHEMA,
                "map": next((row for row in self._effective_visual_manifest().get("maps", []) if row.get("asset_id") == self._effective_visual_manifest().get("default_map_asset_id")), None),
                "tokens": {
                    row["runtime_entity_id"]: next((item for item in self._effective_visual_manifest().get("tokens", []) if row["runtime_entity_id"] in (item.get("stable_actor_ids") or [])), None)
                    for row in self._catalog_cache["projections"] if row.get("primary_combatant")
                },
                "mechanical_authority": False,
            },
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
        }
        self._write_metadata(match_id, doc)
        return doc

    def _mode_for_actor(self, metadata: dict[str, Any], session: Gate4PersistentSession, actor_id: str) -> str:
        actor = session.engine.state.actors[actor_id]
        owner = actor.owner_id if not actor.primary_combatant else None
        mode = metadata["participant_control_modes"].get(owner or actor_id, "MANUAL")
        if mode not in CONTROL_MODES:
            raise self._error(
                "COMBAT_CONTROL_MODE_INVALID",
                "A participant has an unsupported combat control mode.",
                subsystem="combat.gate5.metadata",
                retry_safe=True,
                recommended_action="Choose Manual, Suggested, Local AI, API AI, or Manual AI Bridge.",
                match_id=session.match_id,
                actor_id=actor_id,
                details={"mode": mode},
                status_code=409,
            )
        return mode

    def _metadata_readonly(self, match_id: str, genesis_state: dict[str, Any]) -> dict[str, Any]:
        path = self._metadata_path(match_id)
        if path.is_file():
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
                if doc.get("schema") != INTEGRATION_SCHEMA or doc.get("match_id") != match_id:
                    raise ValueError("metadata identity mismatch")
                return doc
            except Exception as exc:
                raise self._error(
                    "COMBAT_UI_DATA_INVALID",
                    "The match integration metadata is invalid.",
                    subsystem="combat.gate5.metadata",
                    retry_safe=False,
                    recommended_action="Restore or regenerate only FactoryIntegration.json; the mechanical journal remains authoritative.",
                    match_id=match_id,
                    details={"reason": str(exc)},
                    status_code=409,
                ) from exc
        actors = genesis_state.get("actors") or {}
        actor_rows = actors.values() if isinstance(actors, dict) else actors
        primary_ids = [row["entity_id"] for row in actor_rows if row.get("primary_combatant")]
        return {
            "schema": INTEGRATION_SCHEMA,
            "integration_schema_version": "1.0.0",
            "match_id": match_id,
            "display_name": self._catalog_cache["encounters"][0]["display_name"],
            "encounter_id": self._catalog_cache["encounters"][0]["stable_id"],
            "battlefield_id": self._catalog_cache["battlefields"][0]["stable_id"],
            "participant_control_modes": {actor_id: "MANUAL" for actor_id in primary_ids},
            "paused": False,
            "local_auto_running": False,
            "ui_preferences": {},
            "visual_assets": {
                "schema": MATCH_VISUAL_SCHEMA,
                "map": next((row for row in self._effective_visual_manifest().get("maps", []) if row.get("asset_id") == self._effective_visual_manifest().get("default_map_asset_id")), None),
                "tokens": {
                    row["runtime_entity_id"]: next((item for item in self._effective_visual_manifest().get("tokens", []) if row["runtime_entity_id"] in (item.get("stable_actor_ids") or [])), None)
                    for row in self._catalog_cache["projections"] if row.get("primary_combatant")
                },
                "mechanical_authority": False,
            },
            "read_only_default": True,
        }

    @staticmethod
    def _history_state_view(state: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        actors_source = state.get("actors") or {}
        actor_rows = list(actors_source.values()) if isinstance(actors_source, dict) else list(actors_source)
        initiative = list(state.get("initiative_order") or [])
        initiative_index = {actor_id: index for index, actor_id in enumerate(initiative)}
        actors = []
        for actor in sorted(actor_rows, key=lambda row: (initiative_index.get(row["entity_id"], len(initiative_index)), row["entity_id"])):
            owner = actor.get("owner_id") if not actor.get("primary_combatant") else None
            mode = metadata.get("participant_control_modes", {}).get(owner or actor["entity_id"], "MANUAL")
            conditions = actor.get("conditions") or {}
            actors.append({
                **actor,
                "control_mode": mode if mode in CONTROL_MODES else "MANUAL",
                "condition_ids": sorted(
                    row.get("condition_id", key) for key, row in conditions.items()
                ) if isinstance(conditions, dict) else [],
            })
        zones_source = state.get("zones") or {}
        zones = list(zones_source.values()) if isinstance(zones_source, dict) else list(zones_source)
        return {
            "match_seed": state.get("match_seed"),
            "round_number": state.get("round_number"),
            "current_slot_index": state.get("current_slot_index"),
            "current_actor_id": state.get("current_actor_id"),
            "initiative_order": initiative,
            "state_version": state.get("state_version"),
            "event_sequence": state.get("event_sequence"),
            "roll_counter": state.get("roll_counter"),
            "terminal_result": state.get("terminal_result"),
            "actors": actors,
            "zones": sorted(zones, key=lambda row: row.get("zone_id", "")),
            "pending_resolution": state.get("pending_resolution"),
        }

    def history(self, match_id: str) -> dict[str, Any]:
        try:
            history = self.persistence.history_boundaries(match_id)
        except CombatServiceError:
            raise
        except Exception as exc:
            if not self._match_dir(match_id).is_dir():
                raise self._error(
                    "COMBAT_MATCH_NOT_FOUND",
                    "The requested persistent match does not exist or cannot be addressed safely.",
                    subsystem="combat.gate5.history",
                    retry_safe=False,
                    recommended_action="Select a match returned by the combat match list.",
                    match_id=match_id,
                    status_code=404,
                ) from exc
            diagnostic = getattr(exc, "diagnostic", None)
            raise self._error(
                "COMBAT_CONTENT_NOT_READY",
                "The authoritative battle history could not be reconstructed read-only.",
                subsystem="combat.gate5.history",
                retry_safe=False,
                recommended_action="Verify the exact match journal and reducer before viewing history.",
                match_id=match_id,
                details={"diagnostic": diagnostic.model_dump(mode="json") if diagnostic else str(exc)},
                status_code=409,
            ) from exc

        raw_boundaries = history["boundaries"]
        metadata = self._metadata_readonly(match_id, raw_boundaries[0]["state"])
        actor_names = {
            row["runtime_entity_id"]: row["display_name"]
            for row in self._catalog_cache["projections"]
        }
        boundaries = []
        for index, boundary in enumerate(raw_boundaries):
            raw_state = boundary["state"]
            actor_source = raw_state.get("actors") or {}
            current_actor_id = raw_state.get("current_actor_id")
            if isinstance(actor_source, dict):
                actor_names.update({key: row.get("display_name", key) for key, row in actor_source.items()})
            state_view = self._history_state_view(raw_state, metadata)
            events = boundary["events"]
            source_id = next((
                event.get("source_definition_id")
                for event in events
                if event.get("source_definition_id") and not str(event.get("source_definition_id")).startswith("system:")
            ), None)
            action_label = (
                self._definition_names.get(source_id)
                if source_id else ("Match created" if index == 0 else "Committed decision")
            ) or str(source_id).split(":")[-1].replace("_", " ").title()
            pre_state = raw_boundaries[index - 1]["state"] if index else None
            feed = format_history_feed(
                events,
                boundary["rolls"],
                pre_state=pre_state,
                post_state=raw_state,
                actor_names=actor_names,
                definition_names=self._definition_names,
            )
            boundaries.append({
                **{key: value for key, value in boundary.items() if key not in {"state", "events", "rolls"}},
                "state": state_view,
                "events": events,
                "rolls": boundary["rolls"],
                "feed": feed,
                "round_number": raw_state.get("round_number"),
                "current_actor_id": current_actor_id,
                "current_actor_name": actor_names.get(current_actor_id, current_actor_id),
                "action_label": action_label,
                "step_label": f"Step {index} · Round {raw_state.get('round_number', '?')} · {actor_names.get(current_actor_id, current_actor_id or 'System')} · {action_label}",
            })
        return {
            "schema": "TianxiaFactoryCombatHistoryView.v1",
            "match_id": match_id,
            "metadata": metadata,
            "reducer_version": history["reducer_version"],
            "journal_record_count": history["journal_record_count"],
            "commit_count": history["commit_count"],
            "boundaries": boundaries,
            "canonical_final_state_sha256": history["canonical_final_state_sha256"],
            "canonical_event_log_sha256": history["canonical_event_log_sha256"],
            "canonical_roll_log_sha256": history["canonical_roll_log_sha256"],
            "read_only": True,
            "diagnostics": history["diagnostics"],
        }

    def character_authority(self, character_sheet_identity: str) -> dict[str, Any]:
        """Return the exact accepted pre-combat authority projection for one stable identity."""
        projection = self.presenter.character_authority(character_sheet_identity)
        if projection is None:
            raise self._error(
                "COMBAT_CONTENT_NOT_READY",
                "The requested character authority projection is unavailable for that exact identity.",
                subsystem="combat.presentation.character_authority",
                retry_safe=False,
                recommended_action="Open a character identity supplied by the current match Combat Sheet; no display-name fallback is permitted.",
                details={"character_sheet_identity": character_sheet_identity},
                status_code=404,
            )
        return projection.model_dump(mode="json", by_alias=True)

    def presentation(self, match_id: str, boundary_index: int | None = None) -> dict[str, Any]:
        """Project one exact live or historical boundary without mutating match storage."""
        session = self._load_session(match_id)
        live_raw = session.engine.state.model_dump(mode="json")
        metadata = self._metadata_readonly(match_id, live_raw)
        history = self.history(match_id)

        if boundary_index is None:
            state = self._history_state_view(live_raw, metadata)
            candidates = tuple(session.engine.legal_candidates()) if state.get("terminal_result") is None else ()
            feed = tuple(history["boundaries"][-1].get("feed") or []) if history.get("boundaries") else ()
            mode = "LIVE"
            boundary = None
        else:
            boundaries = history.get("boundaries") or []
            if boundary_index < 0 or boundary_index >= len(boundaries):
                raise self._error(
                    "COMBAT_UI_DATA_INVALID",
                    "The requested battle-history boundary is outside the authoritative replay range.",
                    subsystem="combat.presentation.history",
                    retry_safe=True,
                    recommended_action="Select a boundary returned by the battle-history endpoint.",
                    match_id=match_id,
                    details={"boundary_index": boundary_index, "boundary_count": len(boundaries)},
                    status_code=404,
                )
            selected = boundaries[boundary_index]
            state = selected["state"]
            candidates = ()
            feed = tuple(selected.get("feed") or [])
            mode = "HISTORY"
            boundary = {**selected, "boundary_index": boundary_index}

        try:
            projection = self.presenter.project(
                match_id=match_id,
                metadata=metadata,
                state=state,
                catalog=self._catalog_cache,
                mode=mode,
                candidates=candidates,
                feed=feed,
                boundary=boundary,
            )
        except CombatServiceError:
            raise
        except Exception as exc:
            raise self._error(
                "COMBAT_UI_DATA_INVALID",
                "The authoritative combat presentation projection could not be constructed.",
                subsystem="combat.presentation",
                retry_safe=False,
                recommended_action="Inspect the exact catalog, match lock, battlefield definition, and projection findings; do not substitute display-name joins.",
                match_id=match_id,
                details={"reason": str(exc), "boundary_index": boundary_index},
                status_code=409,
            ) from exc
        return projection.model_dump(mode="json", by_alias=True)

    # ------------------------------------------------------------------
    # Match lifecycle and views
    # ------------------------------------------------------------------
    def _load_session(self, match_id: str) -> Gate4PersistentSession:
        try:
            return self.persistence.load_match(match_id, recover=True)
        except CombatServiceError:
            raise
        except (FileNotFoundError, CombatGate1Error, ValueError) as exc:
            code = "COMBAT_MATCH_NOT_FOUND" if not self._match_dir(match_id).is_dir() else "COMBAT_CONTENT_NOT_READY"
            raise self._error(
                code,
                "The combat match could not be loaded with its exact bound content.",
                subsystem="combat.gate5.persistence",
                retry_safe=False,
                recommended_action="Use a listed match and the exact Gate 5 source/content checkpoint; inspect recovery diagnostics before retrying.",
                match_id=match_id,
                details={"reason": str(exc)},
                status_code=404 if code == "COMBAT_MATCH_NOT_FOUND" else 409,
            ) from exc


    def preflight_new_fight(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Read-only C3D-P1 preflight over built-in and verified installed combatants."""
        catalog = self.catalog()
        accepted = catalog["encounters"][0]
        battlefield = next((b for b in catalog["battlefields"] if b.get("stable_id") == payload.get("battlefield_id") and b.get("readiness_status", "COMBAT_READY") == "COMBAT_READY"), None)
        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        if payload.get("encounter_id") != accepted["stable_id"]:
            blockers.append({"code": "C3C_ENCOUNTER_NOT_EXECUTABLE", "actual": payload.get("encounter_id")})
        if battlefield is None:
            blockers.append({"code": "C3C_BATTLEFIELD_NOT_EXECUTABLE", "actual": payload.get("battlefield_id")})
            battlefield = catalog["battlefields"][0]
        if payload.get("initiative_method") != "DETERMINISTIC_ACCEPTED":
            blockers.append({"code": "C3C_INITIATIVE_METHOD_UNSUPPORTED", "actual": payload.get("initiative_method")})
        seed = str(payload.get("match_seed") or "").strip()
        if not seed:
            warnings.append({"code": "C3C_SEED_WILL_BE_GENERATED", "message": "A deterministic seed will be generated only after owner confirmation."})
        elif len(seed) > 200:
            blockers.append({"code": "C3C_SEED_INVALID"})
        ready_rows = {r["runtime_entity_id"]: r for r in catalog["projections"] if r.get("primary_combatant") and r.get("readiness_status") == "COMBAT_READY"}
        companion_rows = {r["runtime_entity_id"]: r for r in catalog["projections"] if not r.get("primary_combatant")}
        participants = payload.get("participants") or []
        supplied_ids = [str(r.get("actor_id") or "") for r in participants]
        if len(supplied_ids) < 2:
            blockers.append({"code": "C3C_ROSTER_REQUIRES_TWO_PRIMARY_COMBATANTS"})
        if len(set(supplied_ids)) != len(supplied_ids):
            blockers.append({"code": "C3C_DUPLICATE_PRIMARY_COMBATANT", "actors": supplied_ids})
        for actor_id in supplied_ids:
            if actor_id in companion_rows:
                blockers.append({"code": "C3C_COMPANION_NOT_INDEPENDENTLY_SELECTABLE", "actor_id": actor_id})
            elif actor_id not in ready_rows:
                blockers.append({"code": "C3C_COMBATANT_NOT_READY", "actor_id": actor_id})
        team_ids = sorted({str(r.get("team_id") or "") for r in participants if str(r.get("team_id") or "")})
        if len(team_ids) != 2:
            blockers.append({"code": "C3C_EXACTLY_TWO_NONEMPTY_TEAMS_REQUIRED", "team_ids": team_ids})
        team_names = {tid: str((payload.get("team_names") or {}).get(tid) or tid)[:120] for tid in team_ids}
        grid = SquareGrid(battlefield)
        occupied: set[tuple[int, int]] = set()
        normalized: list[dict[str, Any]] = []
        portable_authorities: list[dict[str, Any]] = []
        control_modes: dict[str, str] = {}
        suffixes = {"stamina": ".stamina", "qi": ".qi", "resonance": ".resonance"}
        for index, row in enumerate(participants):
            actor_id = str(row.get("actor_id") or "")
            expected = ready_rows.get(actor_id)
            installed = bool(expected and expected.get("installed_character"))
            template = ACTORS.get(actor_id)
            mode = str(row.get("controller_mode") or "MANUAL")
            if mode not in CONTROL_MODES:
                blockers.append({"code": "C3C_CONTROLLER_MODE_UNSUPPORTED", "actor_id": actor_id, "actual": mode})
            control_modes[actor_id] = mode
            placement = row.get("placement")
            position = None
            if not isinstance(placement, dict) or not isinstance(placement.get("x"), int) or not isinstance(placement.get("y"), int):
                blockers.append({"code": "C3C_PLACEMENT_REQUIRED", "actor_id": actor_id})
            else:
                position = Position.model_validate(placement)
            if installed:
                from .footprints import standard_actor_footprint
                definition = standard_actor_footprint().model_copy(update={
                    "footprint_id": f"footprint:{actor_id}.1x1",
                    "source_definition_id": f"system:combat.actor_footprint:{actor_id}",
                })
            else:
                definition, _ = resolve_actor_footprint(actor_id if actor_id in ACTORS else "an_eui")
            if int(row.get("footprint_width") or 1) != definition.width_cells or int(row.get("footprint_height") or 1) != definition.height_cells:
                blockers.append({"code": "C3C_FOOTPRINT_UNSUPPORTED", "actor_id": actor_id})
            if position is not None:
                if not grid.placement_legal(position, footprint=definition, occupied_cells=occupied):
                    blockers.append({"code": "C3C_PLACEMENT_ILLEGAL", "actor_id": actor_id, "placement": placement})
                else:
                    occupied.update(grid.footprint_cells(position, definition))
            allowed_token = expected.get("character_sheet_identity") if expected else None
            token_id = row.get("token_asset_id") or allowed_token
            if expected and token_id != allowed_token:
                blockers.append({"code": "C3C_TOKEN_BINDING_UNSUPPORTED", "actor_id": actor_id})
            actual_resources: dict[str, int] = {}
            owner_resources: dict[str, int | None] = {}
            source_authority = None
            if installed and expected:
                qi_present = "qi_current" in row and row.get("qi_current") is not None
                mf_present = "martial_focus_current" in row and row.get("martial_focus_current") is not None
                if not qi_present or not mf_present:
                    blockers.append({"code": "C3D_CURRENT_RESOURCE_INITIALIZATION_REQUIRED", "actor_id": actor_id, "required": ["qi_current", "martial_focus_current"]})
                qi = row.get("qi_current")
                mf = row.get("martial_focus_current")
                try:
                    validation = self.combatant_library.validate_resource_initialization(
                        expected["candidate_entry_id"],
                        qi_current=int(qi) if qi_present else None,
                        martial_focus_current=int(mf) if mf_present else None,
                        provenance_kind="ENCOUNTER_AUTHORITY",
                        provenance_id=f"c3d-preflight:{seed or 'pending'}:{index}",
                    )
                except Exception as exc:
                    validation = None
                    blockers.append({"code": "C3D_RESOURCE_INITIALIZATION_INVALID", "actor_id": actor_id, "reason": str(exc)})
                if validation is not None and not validation.valid:
                    blockers.append({"code": "C3D_RESOURCE_INITIALIZATION_INVALID", "actor_id": actor_id, "details": list(validation.unresolved_requirements)})
                if validation is not None and validation.valid:
                    entry = self.combatant_library.candidate(expected["candidate_entry_id"])
                    package = self.combatant_library._package_for_entry(entry)
                    authority = build_runtime_authority(
                        entry, package, qi_current=int(qi), martial_focus_current=int(mf),
                        provenance_id=f"c3d-preflight:{seed or 'pending'}:{index}",
                    )
                    if authority.runtime_actor_id != actor_id:
                        blockers.append({"code": "C3D_RUNTIME_ACTOR_ID_MISMATCH", "actor_id": actor_id})
                    else:
                        portable_authorities.append(authority.model_dump(mode="json", by_alias=True))
                        actual_resources = {"resource:core.qi": int(qi), "resource:core.martial_focus": int(mf)}
                        owner_resources = {"qi": int(qi), "martial_focus": int(mf), "stamina": None, "resonance": None}
                        source_authority = {
                            "candidate_entry_id": entry.entry_id, "project_id": entry.character_project_id,
                            "package_sha256": entry.source_package_sha256, "project_revision": entry.project_revision,
                            "event_head_hash": entry.event_head_hash, "replay_state_hash": entry.replay_state_hash,
                            "content_lock_hash": entry.content_lock_hash, "combat_sheet_id": entry.combat_sheet_id,
                            "combat_sheet_commitment_sha256": entry.combat_sheet_commitment_sha256,
                            "mechanics_lock_sha256": entry.mechanics_lock_sha256,
                            "primitive_registry_sha256": entry.primitive_registry_sha256,
                            "runtime_adapter_id": entry.runtime_adapter_id,
                            "runtime_adapter_version": entry.runtime_adapter_version,
                            "runtime_engine_version": entry.runtime_engine_version,
                            "actor_template_commitment_sha256": entry.actor_template_commitment_sha256,
                        }
            else:
                template_resources = {r.resource_id: r for r in template.resources} if template else {}
                for owner_name, suffix in suffixes.items():
                    resource_id = next((rid for rid in template_resources if rid.endswith(suffix)), None)
                    requested = int(row.get(f"{owner_name}_current") or 0)
                    if resource_id is None:
                        if requested != 0:
                            blockers.append({"code": "C3C_RESOURCE_NOT_POSSESSED", "actor_id": actor_id, "resource": owner_name})
                        owner_resources[owner_name] = None
                    else:
                        maximum = int(template_resources[resource_id].maximum)
                        if requested < 0 or requested > maximum:
                            blockers.append({"code": "C3C_RESOURCE_OUT_OF_RANGE", "actor_id": actor_id, "resource": owner_name, "maximum": maximum, "actual": requested})
                        actual_resources[resource_id] = requested
                        owner_resources[owner_name] = requested
            normalized.append({
                "actor_id": actor_id, "participant_kind": "PRIMARY_COMBATANT",
                "display_name": expected.get("display_name") if expected else actor_id,
                "character_sheet_identity": allowed_token,
                "projection_sha256": expected.get("projection_sha256") if expected else None,
                "team_id": row.get("team_id"), "team_display_name": team_names.get(str(row.get("team_id")), str(row.get("team_id"))),
                "starting_resources": owner_resources, "actual_resources": {k: actual_resources[k] for k in sorted(actual_resources)},
                "controller_mode": mode, "token_asset_id": token_id,
                "footprint": {"footprint_id": definition.footprint_id, "width": definition.width_cells, "height": definition.height_cells},
                "placement": placement, "installed_character": installed, "source_authority": source_authority,
            })
        if len(portable_authorities) > 1:
            blockers.append({"code": "C3D_P1_SINGLE_PORTABLE_RUNTIME_CANDIDATE_ONLY"})
        if BAI in supplied_ids:
            owner = next(r for r in normalized if r["actor_id"] == BAI)
            actor_id = CUI; definition, _ = resolve_actor_footprint(actor_id)
            placement = battlefield["starting_positions"][actor_id]; pos = Position.model_validate(placement)
            if not grid.placement_legal(pos, footprint=definition, occupied_cells=occupied): blockers.append({"code": "C3C_COMPANION_PLACEMENT_ILLEGAL", "actor_id": actor_id})
            else: occupied.update(grid.footprint_cells(pos, definition))
            template = ACTORS[actor_id]
            normalized.append({"actor_id": actor_id, "participant_kind": "INCLUDED_COMPANION", "owner_actor_id": BAI, "display_name": "Cui", "character_sheet_identity": "creature:bai_cui", "projection_sha256": template.projection_sha256, "team_id": owner["team_id"], "team_display_name": owner["team_display_name"], "starting_resources": {}, "actual_resources": {r.resource_id:r.initial for r in template.resources}, "controller_mode": owner["controller_mode"], "token_asset_id": "creature:bai_cui", "footprint": {"footprint_id": definition.footprint_id, "width": definition.width_cells, "height": definition.height_cells}, "placement": placement, "installed_character": False, "source_authority": None})
        calibration = payload.get("grid_calibration") or {}
        expected_calibration = {"mode":"AUTHORITATIVE_GATE2_GRID","width":battlefield["width_squares"],"height":battlefield["height_squares"],"square_size_ft":battlefield["square_size_ft"],"centered_tokens":True}
        if calibration != expected_calibration: blockers.append({"code":"C3C_GRID_CALIBRATION_MISMATCH","expected":expected_calibration,"actual":calibration})
        # C3D fields are package-contract authority and therefore appear only when
        # at least one verified portable runtime participant is present.  Built-in
        # C3C-P3 fights retain their exact accepted preflight and setup surface.
        has_portable_runtime = bool(portable_authorities)
        if not has_portable_runtime:
            for participant in normalized:
                participant.pop("installed_character", None)
                participant.pop("source_authority", None)
        report = {
            "schema": "TianxiaFactory.C3DPreflight.v1" if has_portable_runtime else "TianxiaFactory.C3CPreflight.v3",
            "scope": "PORTABLE_CHARACTER_TO_DYNAMIC_LIVE_COMBAT" if has_portable_runtime else "DYNAMIC_COMBAT_READY_TWO_TEAM_ROSTER",
            "read_only":True,"writes_performed":0,"match_created":False,"controller_lock_created":False,"snapshot_created":False,"dice_rolls":0,"persisted_combat_events":0,
            "encounter":{"stable_id":accepted["stable_id"],"display_name":accepted["display_name"]},
            "battlefield":{"stable_id":battlefield["stable_id"],"content_sha256":canonical_sha256(battlefield)},
            "primary_actor_ids":sorted(supplied_ids),
            "included_companion_ids":sorted([r["actor_id"] for r in normalized if r["participant_kind"]=="INCLUDED_COMPANION"]),
            "teams":[{"team_id":tid,"display_name":team_names[tid]} for tid in team_ids],
            "participants":sorted(normalized,key=lambda x:x["actor_id"]),
            "grid_calibration":calibration,"initiative_method":payload.get("initiative_method"),"match_seed":seed or None,
            "maximum_rounds":int(payload.get("maximum_rounds") or 20),
            "control_modes":{k:control_modes[k] for k in sorted(control_modes)},
            "blockers":blockers,"warnings":warnings,"ready":not blockers,
        }
        if has_portable_runtime:
            report["portable_runtime_authorities"] = sorted(portable_authorities, key=lambda x:x["runtime_actor_id"])
        source={k:v for k,v in report.items() if k not in {"warnings","blockers","ready"}}
        report["preflight_commitment"]=canonical_sha256(source)
        return report

    def create_confirmed_fight(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("owner_confirmed") is not True:
            raise self._error(
                "C3C_OWNER_CONFIRMATION_REQUIRED",
                "Confirm Create Fight before persistent match records are written.",
                subsystem="combat.c3c.creation",
                retry_safe=True,
                recommended_action="Review the no-write preflight and explicitly confirm Create Fight.",
                status_code=409,
            )
        preflight = self.preflight_new_fight(payload)
        if not preflight["ready"]:
            raise self._error(
                "C3C_PREFLIGHT_BLOCKED",
                "The fight cannot be created until every preflight blocker is resolved.",
                subsystem="combat.c3c.preflight",
                retry_safe=True,
                recommended_action="Correct the listed team, placement, resource, battlefield, grid, or controller fields.",
                details={"blockers": preflight["blockers"]},
                status_code=409,
            )
        if payload.get("preflight_commitment") != preflight["preflight_commitment"]:
            raise self._error(
                "C3C_PREFLIGHT_STALE",
                "The confirmed setup no longer matches the reviewed preflight.",
                subsystem="combat.c3c.creation",
                retry_safe=True,
                recommended_action="Run the preflight again and confirm the unchanged setup.",
                status_code=409,
            )
        seed = str(payload.get("match_seed") or f"C3C-{secrets.token_hex(16)}").strip()
        setup_binding = {
            "schema": "TianxiaFactory.C3CMatchSetupBinding.v1",
            "preflight_commitment": preflight["preflight_commitment"],
            "participants": preflight["participants"],
            "primary_actor_ids": preflight["primary_actor_ids"],
            "included_companion_ids": preflight["included_companion_ids"],
            "teams": preflight["teams"],
            "battlefield": preflight["battlefield"],
            "grid_calibration": preflight["grid_calibration"],
            "initiative_method": preflight["initiative_method"],
            "maximum_rounds": preflight["maximum_rounds"],
        }
        if preflight.get("portable_runtime_authorities"):
            setup_binding["portable_runtime_authorities"] = preflight["portable_runtime_authorities"]
        try:
            return self.create_match(
                encounter_id=payload["encounter_id"],
                display_name=payload.get("display_name"),
                match_seed=seed,
                control_modes=preflight["control_modes"],
                maximum_rounds=preflight["maximum_rounds"],
                creation_key=str(payload["idempotency_key"]),
                setup_binding=setup_binding,
            )
        except CombatServiceError:
            raise
        except Exception as exc:
            raise self._error(
                "C3C_ATOMIC_CREATION_FAILED",
                "The fight could not be created; no partial match was retained.",
                subsystem="combat.c3c.creation",
                retry_safe=True,
                recommended_action="Review the setup and retry the same confirmed request.",
                details={"reason": str(exc)},
                status_code=409,
            ) from exc

    def create_match(
        self,
        *,
        encounter_id: str,
        display_name: str | None,
        match_seed: str | None,
        control_modes: dict[str, str],
        maximum_rounds: int = 20,
        creation_key: str | None = None,
        setup_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        accepted = self._catalog_cache["encounters"][0]
        if encounter_id != accepted["stable_id"]:
            raise self._error(
                "COMBAT_CONTENT_NOT_READY",
                "The requested encounter is not executable in Gate 5.",
                subsystem="combat.gate5.catalog",
                retry_safe=False,
                recommended_action="Select the accepted CL5 2v2 encounter from the combat catalog.",
                details={"requested": encounter_id, "accepted": accepted["stable_id"]},
                status_code=409,
            )
        seed = (match_seed or f"GATE5-{secrets.token_hex(16)}").strip()
        if not seed or len(seed) > 200:
            raise self._error(
                "COMBAT_UI_DATA_INVALID",
                "The match seed must contain 1–200 characters.",
                subsystem="combat.gate5.setup",
                retry_safe=True,
                recommended_action="Use the generated seed or enter a shorter explicit seed.",
            )
        valid_actor_ids = {p["runtime_entity_id"] for p in self.catalog()["projections"] if p.get("primary_combatant")}
        supplied = set(control_modes)
        if not supplied.issubset(valid_actor_ids) or any(mode not in CONTROL_MODES for mode in control_modes.values()):
            raise self._error(
                "COMBAT_CONTROL_MODE_INVALID",
                "One or more participant control-mode assignments are invalid.",
                subsystem="combat.gate5.setup",
                retry_safe=True,
                recommended_action="Assign only catalog primary combatants to supported control modes.",
                details={"valid_actor_ids": sorted(valid_actor_ids), "supported_modes": list(CONTROL_MODES)},
            )
        setup_sha = canonical_sha256(setup_binding or {})
        if creation_key:
            for existing in self.list_matches():
                try:
                    existing_metadata = self._read_metadata(existing["match_id"])
                except Exception:
                    continue
                if existing_metadata.get("c3c_creation_key") != creation_key:
                    continue
                if existing_metadata.get("c3c_setup_binding_sha256") != setup_sha:
                    raise self._error(
                        "C3C_IDEMPOTENCY_CONFLICT",
                        "That creation key was already used for a different fight setup.",
                        subsystem="combat.c3c.creation", retry_safe=False,
                        recommended_action="Use the existing match or a new idempotency key.", status_code=409,
                    )
                return self.get_match(existing["match_id"])
        with self._timed("match_creation", threshold_ms=3000):
            try:
                participants = (setup_binding or {}).get("participants", [])
                genesis_setup = {row["actor_id"]: {"placement": row["placement"], "resources": row.get("actual_resources") or {}} for row in participants}
                roster_setup = {
                    "primary_actor_ids": [row["actor_id"] for row in participants if row.get("participant_kind") == "PRIMARY_COMBATANT"],
                    "team_by_actor": {row["actor_id"]: row["team_id"] for row in participants},
                    "starting_positions": {row["actor_id"]: row["placement"] for row in participants},
                }
                runtime_docs = list((setup_binding or {}).get("portable_runtime_authorities") or [])
                if len(runtime_docs) > 1:
                    raise ValueError("C3D_P1_SINGLE_PORTABLE_RUNTIME_CANDIDATE_ONLY")
                runtime_doc = runtime_docs[0] if runtime_docs else None
                source_package = None
                if runtime_doc is not None:
                    authority = PortableRuntimeAuthority.model_validate(runtime_doc)
                    entry = self.combatant_library.candidate(authority.candidate_entry_id)
                    if entry.source_package_sha256 != authority.package_sha256 or entry.character_project_id != authority.project_id:
                        raise ValueError("C3D_INSTALLED_PACKAGE_AUTHORITY_CHANGED")
                    source_package = self.combatant_library._package_for_entry(entry)
                    rebuilt = build_runtime_authority(
                        entry, source_package,
                        qi_current=authority.bundle.resource_initialization.qi_current,
                        martial_focus_current=authority.bundle.resource_initialization.martial_focus_current,
                        provenance_id=authority.bundle.resource_initialization.provenance_id,
                    )
                    if rebuilt.authority_sha256 != authority.authority_sha256:
                        raise ValueError("C3D_PREFLIGHT_RUNTIME_AUTHORITY_STALE")
                session = self.persistence.create_match(
                    match_seed=seed, maximum_rounds=maximum_rounds,
                    genesis_setup=genesis_setup or None, roster_setup=roster_setup,
                    runtime_authority=runtime_doc, source_package=source_package,
                )
            except (FileExistsError, CombatGate1Error, ValueError) as exc:
                diagnostic = getattr(exc, "diagnostic", None)
                diagnostic_code = getattr(diagnostic, "code", None)
                duplicate = isinstance(exc, FileExistsError) or diagnostic_code in {
                    "MATCH_LOCK_HASH_MISMATCH",
                    "MATCH_GENESIS_HASH_MISMATCH",
                }
                if duplicate and creation_key:
                    for existing in self.list_matches():
                        try:
                            metadata = self._read_metadata(existing["match_id"])
                        except Exception:
                            continue
                        if metadata.get("c3c_creation_key") == creation_key:
                            if metadata.get("c3c_setup_binding_sha256") != canonical_sha256(setup_binding or {}):
                                raise self._error(
                                    "C3C_IDEMPOTENCY_CONFLICT",
                                    "That creation key was already used for a different fight setup.",
                                    subsystem="combat.c3c.creation",
                                    retry_safe=False,
                                    recommended_action="Use the existing match or a new idempotency key.",
                                    status_code=409,
                                )
                            return self.get_match(existing["match_id"])
                raise self._error(
                    "COMBAT_UI_DATA_INVALID" if duplicate else "COMBAT_CONTENT_NOT_READY",
                    (
                        "That deterministic seed already identifies an existing match directory."
                        if duplicate
                        else "The accepted combat match could not be created from the exact bound content."
                    ),
                    subsystem="combat.gate5.setup" if duplicate else "combat.gate5.persistence",
                    retry_safe=duplicate,
                    recommended_action=(
                        "Resume the existing match from the match list or generate a new seed."
                        if duplicate
                        else "Restore the exact Gate 5 source/content checkpoint and inspect the bound-content diagnostic."
                    ),
                    details={"seed": seed, "underlying_code": diagnostic_code, "reason": str(exc)},
                    status_code=409,
                ) from exc
            modes = {actor_id: control_modes.get(actor_id, "MANUAL") for actor_id in sorted(control_modes)}
            match_visuals = self._snapshot_match_visuals(session.match_id)
            metadata = {
                "schema": INTEGRATION_SCHEMA,
                "integration_schema_version": "1.0.0",
                "match_id": session.match_id,
                "display_name": (display_name or accepted["display_name"]).strip()[:240],
                "encounter_id": accepted["stable_id"],
                "battlefield_id": accepted["battlefield_id"],
                "participant_control_modes": modes,
                "paused": False,
                "local_auto_running": False,
                "ui_preferences": {},
                "visual_assets": match_visuals,
                "c3c_creation_key": creation_key,
                "c3c_setup_binding": setup_binding,
                "c3c_setup_binding_sha256": canonical_sha256(setup_binding or {}) if setup_binding is not None else None,
                "created_at": _utcnow(),
                "updated_at": _utcnow(),
            }
            if (setup_binding or {}).get("portable_runtime_authorities"):
                metadata["c3c_preflight_commitment"] = (setup_binding or {}).get("preflight_commitment")
            try:
                self._write_metadata(session.match_id, metadata)
                if setup_binding is not None:
                    self._verify_committed_setup(session, setup_binding)
            except Exception:
                shutil.rmtree(session.store.match_dir, ignore_errors=True)
                raise
        return self._match_view(session, metadata)

    def _verify_committed_setup(self, session: Gate4PersistentSession, setup_binding: dict[str, Any]) -> None:
        for row in setup_binding.get("participants", []):
            actor = session.engine.state.actors[row["actor_id"]]
            if actor.position.model_dump(mode="json") != row["placement"]:
                raise ValueError(f"C3C_GENESIS_COMMITMENT_MISMATCH:{actor.entity_id}:placement")
            for resource_id, expected in (row.get("actual_resources") or {}).items():
                if actor.resources.get(resource_id) != expected:
                    raise ValueError(f"C3C_GENESIS_COMMITMENT_MISMATCH:{actor.entity_id}:{resource_id}")
        battlefield = self._catalog_cache["battlefields"][0]
        if setup_binding.get("battlefield", {}).get("stable_id") != battlefield["stable_id"]:
            raise ValueError("C3C_GENESIS_COMMITMENT_MISMATCH:battlefield")
        expected_calibration = {"mode": "AUTHORITATIVE_GATE2_GRID", "width": battlefield["width_squares"], "height": battlefield["height_squares"], "square_size_ft": battlefield["square_size_ft"], "centered_tokens": True}
        if setup_binding.get("grid_calibration") != expected_calibration:
            raise ValueError("C3C_GENESIS_COMMITMENT_MISMATCH:grid_calibration")
        for row in setup_binding.get("participants", []):
            if row.get("installed_character"):
                from .footprints import standard_actor_footprint
                definition = standard_actor_footprint().model_copy(update={
                    "footprint_id": f"footprint:{row['actor_id']}.1x1",
                    "source_definition_id": f"system:combat.actor_footprint:{row['actor_id']}",
                })
            else:
                definition, _ = resolve_actor_footprint(row["actor_id"])
            expected_fp = {"footprint_id": definition.footprint_id, "width": definition.width_cells, "height": definition.height_cells}
            if row.get("footprint") != expected_fp:
                raise ValueError(f"C3C_GENESIS_COMMITMENT_MISMATCH:{row['actor_id']}:footprint")
            if row.get("token_asset_id") != row.get("character_sheet_identity"):
                raise ValueError(f"C3C_GENESIS_COMMITMENT_MISMATCH:{row['actor_id']}:token")
        metadata = self._read_metadata(session.match_id, session)
        if metadata.get("c3c_setup_binding_sha256") != canonical_sha256(setup_binding):
            raise ValueError("C3C_GENESIS_COMMITMENT_MISMATCH:metadata")

    def list_matches(self) -> list[dict[str, Any]]:
        rows = []
        for row in self.persistence.list_matches():
            try:
                metadata = self._read_metadata(row["match_id"])
            except CombatServiceError as exc:
                metadata = {"display_name": row["match_id"], "paused": False, "diagnostic": exc.diagnostic.as_dict()}
            rows.append({**row, **{k: metadata.get(k) for k in ("display_name", "encounter_id", "paused", "participant_control_modes")}})
        return rows

    def get_match(self, match_id: str) -> dict[str, Any]:
        session = self._load_session(match_id)
        metadata = self._read_metadata(match_id, session)
        return self._match_view(session, metadata)

    def _controller_rows(self, session: Gate4PersistentSession, limit: int = 12) -> list[dict[str, Any]]:
        return _read_jsonl(session.controller_journal_path)[-limit:]

    def _match_view(self, session: Gate4PersistentSession, metadata: dict[str, Any]) -> dict[str, Any]:
        state = session.engine.state
        actors = []
        initiative_index = {actor_id: index for index, actor_id in enumerate(state.initiative_order)}
        for actor in sorted(
            state.actors.values(),
            key=lambda row: (initiative_index.get(row.entity_id, len(initiative_index)), row.entity_id),
        ):
            actors.append({
                **actor.model_dump(mode="json"),
                "control_mode": self._mode_for_actor(metadata, session, actor.entity_id),
                "condition_ids": sorted(condition.condition_id for condition in actor.conditions.values()),
            })
        return {
            "schema": "TianxiaFactoryCombatMatchView.v1",
            "match_id": session.match_id,
            "metadata": metadata,
            "state": {
                "match_seed": state.match_seed,
                "round_number": state.round_number,
                "current_slot_index": state.current_slot_index,
                "current_actor_id": state.current_actor_id,
                "initiative_order": list(state.initiative_order),
                "state_version": state.state_version,
                "event_sequence": state.event_sequence,
                "roll_counter": state.roll_counter,
                "terminal_result": state.terminal_result.model_dump(mode="json") if state.terminal_result else None,
                "actors": actors,
                "zones": [zone.model_dump(mode="json") for zone in sorted(state.zones.values(), key=lambda z: z.zone_id)],
                "pending_resolution": state.pending_resolution.model_dump(mode="json") if state.pending_resolution else None,
            },
            "recent_events": [event.model_dump(mode="json") for event in session.engine.events[-40:]],
            "controller_records": self._controller_rows(session),
            "final_summary": self.final_summary(session.match_id) if state.terminal_result is not None else None,
            "diagnostics": session.diagnostics,
        }

    def set_controller_mode(self, match_id: str, *, actor_id: str, controller_mode: str) -> dict[str, Any]:
        if controller_mode not in CONTROL_MODES:
            raise self._error("COMBAT_CONTROL_MODE_INVALID", "The requested controller mode is unsupported.", subsystem="combat.gate5.controller", retry_safe=True, recommended_action="Choose a supported controller mode.")
        session = self._load_session(match_id)
        if session.engine.state.terminal_result is not None:
            raise self._error("COMBAT_MATCH_ALREADY_COMPLETE", "Controller modes cannot be changed after the fight is complete.", subsystem="combat.gate5.controller", retry_safe=False, recommended_action="Inspect the final summary, verify, replay, or export.", match_id=match_id, status_code=409)
        if actor_id not in session.engine.state.actors or not session.engine.state.actors[actor_id].primary_combatant:
            raise self._error("COMBAT_CONTROL_MODE_INVALID", "The requested fighter cannot receive an owner controller assignment.", subsystem="combat.gate5.controller", retry_safe=True, recommended_action="Choose one of the four primary combatants.")
        metadata = self._read_metadata(match_id, session)
        modes = dict(metadata.get("participant_control_modes") or {})
        modes[actor_id] = controller_mode
        metadata["participant_control_modes"] = modes
        metadata["updated_at"] = _utcnow()
        self._write_metadata(match_id, metadata)
        return self._match_view(session, metadata)

    def pause(self, match_id: str) -> dict[str, Any]:
        session = self._load_session(match_id)
        if session.engine.state.terminal_result is not None:
            raise self._error("COMBAT_MATCH_ALREADY_COMPLETE", "A completed fight is read-only and cannot be paused.", subsystem="combat.gate5.persistence", retry_safe=False, recommended_action="Inspect the final summary, verify, replay, or export.", match_id=match_id, status_code=409)
        metadata = self._read_metadata(match_id, session)
        metadata.update({"paused": True, "local_auto_running": False})
        self._write_metadata(match_id, metadata)
        return self._match_view(session, metadata)

    def resume(self, match_id: str) -> dict[str, Any]:
        session = self._load_session(match_id)
        if session.engine.state.terminal_result is not None:
            raise self._error("COMBAT_MATCH_ALREADY_COMPLETE", "A completed fight is read-only and cannot be resumed.", subsystem="combat.gate5.persistence", retry_safe=False, recommended_action="Inspect the final summary, verify, replay, snapshot, or export.", match_id=match_id, status_code=409)
        metadata = self._read_metadata(match_id, session)
        metadata.update({"paused": False, "local_auto_running": False})
        self._write_metadata(match_id, metadata)
        return self._match_view(session, metadata)

    # ------------------------------------------------------------------
    # Decision and validation
    # ------------------------------------------------------------------
    def decision(self, match_id: str) -> dict[str, Any]:
        with self._timed("decision_context", threshold_ms=2000):
            session = self._load_session(match_id)
            if session.engine.state.terminal_result is not None:
                raise self._error(
                    "COMBAT_MATCH_ALREADY_COMPLETE",
                    "The combat match is complete and has no further decision context.",
                    subsystem="combat.gate5.decision",
                    retry_safe=False,
                    recommended_action="Use verify, replay, or export for the completed match.",
                    match_id=match_id,
                    status_code=409,
                )
            candidates = session.engine.legal_candidates()
            if not candidates:
                raise self._error(
                    "COMBAT_CONTENT_NOT_READY",
                    "The engine produced no legal decision candidates.",
                    subsystem="combat.gate5.decision",
                    retry_safe=False,
                    recommended_action="Inspect the exact match state and Gate 2 legality diagnostics.",
                    match_id=match_id,
                    status_code=409,
                )
            actor_id = candidates[0].actor_id
            policy, fallback = self.policies.for_actor(actor_id)
            context = build_decision_context(session.engine, policy)
            metadata = self._read_metadata(match_id, session)
            control_mode = self._mode_for_actor(metadata, session, actor_id)
            return {
                "context": context.model_dump(mode="json", by_alias=True),
                "control_mode": control_mode,
                "manual_submit_allowed": control_mode in MANUAL_SUBMIT_MODES,
                "manual_submit_reason": (
                    "ACTIVE_ACTOR_ACCEPTS_OWNER_INTENT"
                    if control_mode in MANUAL_SUBMIT_MODES
                    else f"ACTIVE_ACTOR_CONTROLLED_BY_{control_mode}"
                ),
                "fallback_policy_used": fallback,
            }

    def _intent_from_payload(self, context, payload: dict[str, Any], *, reactions: Iterable[ReactionDecision] = ()) -> ActionIntent:
        candidate = next((row for row in context.legal_candidates if row.candidate_id == payload.get("candidate_id")), None)
        if candidate is None:
            raise self._error(
                "COMBAT_DECISION_STALE",
                "The selected candidate is not legal in the current decision context.",
                subsystem="combat.gate5.intent",
                retry_safe=True,
                recommended_action="Refresh the decision context and choose one of its current candidate IDs.",
                match_id=context.match_id,
                actor_id=context.active_actor_id,
                decision_id=context.decision_id,
                status_code=409,
            )
        if payload.get("decision_id") != context.decision_id or int(payload.get("state_version", -1)) != context.state_version:
            raise self._error(
                "COMBAT_DECISION_STALE",
                "The submitted decision ID or state version is stale.",
                subsystem="combat.gate5.intent",
                retry_safe=True,
                recommended_action="Refresh the match and submit against the newest immutable DecisionContext.",
                match_id=context.match_id,
                actor_id=context.active_actor_id,
                decision_id=payload.get("decision_id"),
                details={"current_decision_id": context.decision_id, "current_state_version": context.state_version},
                status_code=409,
            )
        supplied_actor = payload.get("actor_id")
        supplied_targets = tuple(payload.get("target_ids") or ())
        supplied_destination = Position.model_validate(payload["destination"]) if payload.get("destination") is not None else None
        option_ids = tuple(payload.get("option_ids") or ())
        choice_findings = validate_option_selection(candidate, option_ids)
        if not choice_findings:
            option_ids = canonicalize_option_selection(candidate, option_ids)
        if (
            supplied_actor != candidate.actor_id
            or supplied_targets != candidate.target_ids
            or supplied_destination != candidate.destination
            or choice_findings
        ):
            raise self._error(
                "COMBAT_AI_INTENT_INVALID",
                "The intent does not exactly match the selected engine-issued candidate and legal options.",
                subsystem="combat.gate5.intent",
                retry_safe=True,
                recommended_action="Use the actor, targets, destination, and option IDs exactly as listed in the current DecisionContext.",
                match_id=context.match_id,
                actor_id=context.active_actor_id,
                decision_id=context.decision_id,
                details={"candidate": candidate.model_dump(mode="json"), "choice_findings": list(choice_findings)},
                status_code=422,
            )
        identity = {
            "match_id": context.match_id,
            "decision_id": context.decision_id,
            "candidate_id": candidate.candidate_id,
            "options": option_ids,
            "reactions": [row.model_dump(mode="json") for row in reactions],
        }
        return ActionIntent(
            intent_id=f"intent:gate5:{canonical_sha256(identity)[:24]}",
            decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id,
            state_version=candidate.state_version,
            actor_id=candidate.actor_id,
            target_ids=candidate.target_ids,
            destination=candidate.destination,
            option_ids=option_ids,
            reaction_decisions=tuple(reactions),
        )

    def _manual_record(self, context, intent: ActionIntent) -> DecisionRecord:
        adapter = ManualControllerAdapter(lambda _context: (intent.candidate_id, intent.option_ids))
        choice = adapter.choose_primary_action(context)
        return choice.record

    def _require_manual_submit_mode(
        self,
        match_id: str,
        session: Gate4PersistentSession,
        metadata: dict[str, Any],
    ) -> str:
        if session.engine.state.terminal_result is not None:
            raise self._error(
                "COMBAT_MATCH_ALREADY_COMPLETE",
                "The completed match is read-only and cannot accept an owner-submitted intent or reaction.",
                subsystem="combat.gate5.manual_control",
                retry_safe=False,
                recommended_action="Inspect the final summary, verify, replay, or export.",
                match_id=match_id,
                status_code=409,
            )
        candidates = session.engine.legal_candidates()
        actor_id = candidates[0].actor_id
        mode = self._mode_for_actor(metadata, session, actor_id)
        if mode not in MANUAL_SUBMIT_MODES:
            raise self._error(
                "COMBAT_CONTROLLER_MODE_MISMATCH",
                "The active fighter is assigned to an automatic controller and cannot accept an owner-submitted intent.",
                subsystem="combat.gate5.manual_control",
                retry_safe=True,
                recommended_action="Use the assigned automatic controller, or create a new match with Manual, Suggested, or Manual AI Bridge control for this fighter.",
                match_id=match_id,
                actor_id=actor_id,
                details={"control_mode": mode, "allowed_manual_modes": sorted(MANUAL_SUBMIT_MODES)},
                status_code=409,
            )
        return mode

    @staticmethod
    def _clone_engine(source_root: Path, engine: Gate4ControllerEngine) -> Gate4ControllerEngine:
        runtime_authority = (
            engine.runtime_authority.model_dump(mode="json")
            if getattr(engine, "runtime_authority", None) is not None
            else None
        )
        clone = Gate4ControllerEngine(
            source_root,
            match_seed=engine.state.match_seed,
            maximum_rounds=engine.state.maximum_rounds,
            runtime_authority=runtime_authority,
        )
        clone.state = engine.state.model_copy(deep=True)
        clone.events = [CombatEvent.model_validate(row.model_dump(mode="json")) for row in engine.events]
        clone.rolls = [RollRecord.model_validate(row.model_dump(mode="json")) for row in engine.rolls]
        clone.roller.counter = engine.state.roll_counter
        clone._transaction_id = None
        clone._transaction_result_version = engine.state.state_version
        clone._active_intent_id = "system:gate5-preview"
        clone._active_intent = None
        clone._commanded_cui_this_turn = bool(engine._commanded_cui_this_turn)
        return clone

    def _validate_reaction(self, context: ReactionContext, decision: ReactionDecision) -> None:
        if (
            decision.checkpoint != context.checkpoint
            or decision.reactor_id != context.reactor_id
            or decision.reaction_source_id not in context.legal_reaction_ids
        ):
            raise self._error(
                "COMBAT_AI_INTENT_INVALID",
                "The reaction decision belongs to another checkpoint, reactor, or reaction.",
                subsystem="combat.gate5.reaction",
                retry_safe=True,
                recommended_action="Use the exact IDs in the current ReactionContext.",
                match_id=context.match_id,
                actor_id=context.reactor_id,
                decision_id=context.decision_id,
                status_code=422,
            )
        if decision.selection == "DECLINE":
            if decision.spend != 0 or decision.option_ids:
                raise self._error(
                    "COMBAT_AI_INTENT_INVALID",
                    "A declined reaction cannot spend resources or select options.",
                    subsystem="combat.gate5.reaction",
                    retry_safe=True,
                    recommended_action="Return DECLINE with spend 0 and no option IDs.",
                    match_id=context.match_id,
                    actor_id=context.reactor_id,
                    decision_id=context.decision_id,
                    status_code=422,
                )
            return
        if context.reaction_source_id == "reaction:core.stamina_guard":
            if decision.spend not in context.spend_options:
                raise self._error(
                    "COMBAT_AI_INTENT_INVALID",
                    "The Stamina Guard spend is not legal at this actual damage checkpoint.",
                    subsystem="combat.gate5.reaction",
                    retry_safe=True,
                    recommended_action="Choose one of the spend values in the ReactionContext.",
                    match_id=context.match_id,
                    actor_id=context.reactor_id,
                    decision_id=context.decision_id,
                    details={"spend_options": list(context.spend_options)},
                    status_code=422,
                )
        elif decision.spend != 0:
            raise self._error(
                "COMBAT_AI_INTENT_INVALID",
                "This reaction does not accept a variable spend.",
                subsystem="combat.gate5.reaction",
                retry_safe=True,
                recommended_action="Use spend 0 for this reaction.",
                match_id=context.match_id,
                actor_id=context.reactor_id,
                decision_id=context.decision_id,
                status_code=422,
            )
        legal_options = set(context.legal_option_ids)
        if any(option not in legal_options for option in decision.option_ids):
            raise self._error(
                "COMBAT_AI_INTENT_INVALID",
                "The reaction contains an option not supported by its exact mechanic.",
                subsystem="combat.gate5.reaction",
                retry_safe=True,
                recommended_action="Use only option IDs exposed for this reaction, or no options.",
                match_id=context.match_id,
                actor_id=context.reactor_id,
                decision_id=context.decision_id,
                status_code=422,
            )

    def _run_preview(
        self,
        session: Gate4PersistentSession,
        metadata: dict[str, Any],
        base_intent: ActionIntent,
        supplied_reactions: tuple[ReactionDecision, ...],
    ) -> dict[str, Any]:
        probe = self._clone_engine(self.source_root, session.engine)
        supplied: dict[tuple[str, str, str], ReactionDecision] = {}
        for decision in supplied_reactions:
            key = (decision.checkpoint, decision.reactor_id, decision.reaction_source_id)
            if key in supplied:
                raise self._error(
                    "COMBAT_AI_INTENT_INVALID",
                    "A reaction decision was supplied more than once.",
                    subsystem="combat.gate5.reaction",
                    retry_safe=True,
                    recommended_action="Provide at most one decision for each checkpoint/reactor/reaction tuple.",
                    match_id=session.match_id,
                    status_code=422,
                )
            supplied[key] = decision
        resolved: list[ReactionDecision] = []
        records: list[dict[str, Any]] = []

        def provider(request: dict[str, Any]):
            policy, _ = self.policies.for_actor(str(request["reactor_id"]))
            context = build_reaction_context(probe, policy, request)
            key = (context.checkpoint, context.reactor_id, context.reaction_source_id)
            mode = self._mode_for_actor(metadata, session, context.reactor_id)
            if key in supplied:
                decision = supplied[key]
                self._validate_reaction(context, decision)
                resolved.append(decision)
                record = ManualControllerAdapter(lambda _ctx: ("", ()), reaction_chooser=lambda _ctx: decision).choose_reaction(context).record
                record_doc = record.model_dump(mode="json", by_alias=True)
                records.append(record_doc)
                return decision, record_doc
            if mode in {"LOCAL_AUTO", "API_AUTO"}:
                choice = self.controller.choose_reaction(context)
                self._validate_reaction(context, choice.decision)
                resolved.append(choice.decision)
                record_doc = choice.record.model_dump(mode="json", by_alias=True)
                records.append(record_doc)
                return choice.decision, record_doc
            suggestion = self.controller.choose_reaction(context)
            raise _ReactionRequired(
                context,
                {
                    "decision": suggestion.decision.model_dump(mode="json"),
                    "record": suggestion.record.model_dump(mode="json", by_alias=True),
                },
                resolved_reactions=tuple(resolved),
                reaction_records=tuple(records),
            )

        probe.set_reaction_provider(provider)
        event_start = len(probe.events)
        roll_start = len(probe.rolls)
        try:
            probe.execute_intent(base_intent.model_copy(update={"reaction_decisions": ()}))
        finally:
            probe.set_reaction_provider(None)
        final_intent = base_intent.model_copy(update={"reaction_decisions": tuple(resolved)})
        result = {
            "match_id": session.match_id,
            "pre_state_version": session.engine.state.state_version,
            "pre_state_sha256": canonical_state_sha256(session.engine.state),
            "intent": final_intent.model_dump(mode="json"),
            "resolved_reactions": [row.model_dump(mode="json") for row in resolved],
            "reaction_records": records,
            "post_state_version": probe.state.state_version,
            "post_state_sha256": canonical_state_sha256(probe.state),
            "roll_counter_end": probe.state.roll_counter,
            "events": [row.model_dump(mode="json") for row in probe.events[event_start:]],
            "rolls": [row.model_dump(mode="json") for row in probe.rolls[roll_start:]],
        }
        result["preview_id"] = f"preview:{canonical_sha256(result)[:32]}"
        return result

    def preview(self, match_id: str, payload: dict[str, Any], reaction_rows: list[dict[str, Any]]) -> dict[str, Any]:
        with self._timed("manual_preview", threshold_ms=3000):
            session = self._load_session(match_id)
            metadata = self._read_metadata(match_id, session)
            self._require_manual_submit_mode(match_id, session, metadata)
            context_payload = self.decision(match_id)["context"]
            from .gate4_models import DecisionContext
            context = DecisionContext.model_validate(context_payload)
            reactions = tuple(ReactionDecision.model_validate(row) for row in reaction_rows)
            base_intent = self._intent_from_payload(context, payload)
            try:
                result = self._run_preview(session, metadata, base_intent, reactions)
            except _ReactionRequired as needed:
                return {
                    "schema": "TianxiaFactoryCombatPreview.v1",
                    "status": "REACTION_REQUIRED",
                    "diagnostic": CombatServiceDiagnostic(
                        code="COMBAT_REACTION_DECISION_REQUIRED",
                        message="An actual deterministic reaction checkpoint requires a manual decision.",
                        subsystem="combat.gate5.preview",
                        retry_safe=True,
                        recommended_action="Choose Use or Decline using only the exact ReactionContext values, then preview again.",
                        match_id=match_id,
                        actor_id=needed.context.reactor_id,
                        decision_id=needed.context.decision_id,
                    ).as_dict(),
                    "reaction_context": needed.context.model_dump(mode="json", by_alias=True),
                    "reaction_context_fingerprint": f"reaction-context:{canonical_sha256(needed.context.model_dump(mode='json', by_alias=True))[:32]}",
                    "reaction_step_number": len(needed.resolved_reactions) + 1,
                    "resolved_reactions_before_prompt": [row.model_dump(mode="json") for row in needed.resolved_reactions],
                    "reaction_records_before_prompt": list(needed.reaction_records),
                    "reaction_controller_mode": self._mode_for_actor(metadata, session, needed.context.reactor_id),
                    "manual_response_required": True,
                    "local_suggestion": needed.suggestion,
                    "authoritative_state_unchanged": True,
                }
            except (CombatGate1Error, ValueError) as exc:
                diagnostic = getattr(exc, "diagnostic", None)
                raise self._error(
                    "COMBAT_AI_INTENT_INVALID",
                    "The selected action or option combination was rejected by the exact combat runtime.",
                    subsystem="combat.gate5.preview",
                    retry_safe=True,
                    recommended_action="Refresh the legal candidates and choose only the target, destination, and option combination exposed by the current decision.",
                    match_id=match_id,
                    actor_id=context.active_actor_id,
                    decision_id=context.decision_id,
                    details={
                        "underlying_code": getattr(diagnostic, "code", None),
                        "reason": str(exc),
                    },
                    status_code=422,
                ) from exc
            return {
                "schema": "TianxiaFactoryCombatPreview.v1",
                "status": "PREVIEW_COMPLETE",
                **result,
                "authoritative_state_unchanged": True,
            }

    def _commit_previewed(
        self,
        match_id: str,
        payload: dict[str, Any],
        reaction_rows: list[dict[str, Any]],
        preview_id: str | None,
        *,
        primary_record: DecisionRecord | None = None,
    ) -> dict[str, Any]:
        with self._timed("authoritative_action_commit", threshold_ms=3000):
            session = self._load_session(match_id)
            metadata = self._read_metadata(match_id, session)
            from .gate4_models import DecisionContext
            context = DecisionContext.model_validate(self.decision(match_id)["context"])
            reactions = tuple(ReactionDecision.model_validate(row) for row in reaction_rows)
            base_intent = self._intent_from_payload(context, payload)
            try:
                preview = self._run_preview(session, metadata, base_intent, reactions)
            except _ReactionRequired as needed:
                raise self._error(
                    "COMBAT_REACTION_DECISION_REQUIRED",
                    "The action reached an unresolved manual reaction checkpoint.",
                    subsystem="combat.gate5.commit",
                    retry_safe=True,
                    recommended_action="Use the preview endpoint, resolve the returned ReactionContext, and submit the exact completed preview.",
                    match_id=match_id,
                    actor_id=needed.context.reactor_id,
                    decision_id=needed.context.decision_id,
                    details={"reaction_context": needed.context.model_dump(mode="json", by_alias=True)},
                    status_code=409,
                ) from needed
            except (CombatGate1Error, ValueError) as exc:
                diagnostic = getattr(exc, "diagnostic", None)
                raise self._error(
                    "COMBAT_AI_INTENT_INVALID",
                    "The completed intent was rejected by the exact combat runtime.",
                    subsystem="combat.gate5.commit",
                    retry_safe=True,
                    recommended_action="Refresh the match and preview a currently legal option combination before committing.",
                    match_id=match_id,
                    actor_id=context.active_actor_id,
                    decision_id=context.decision_id,
                    details={
                        "underlying_code": getattr(diagnostic, "code", None),
                        "reason": str(exc),
                    },
                    status_code=422,
                ) from exc
            if preview_id is not None and preview_id != preview["preview_id"]:
                raise self._error(
                    "COMBAT_PREVIEW_MISMATCH",
                    "The authoritative pre-state or completed preview no longer matches the checked preview.",
                    subsystem="combat.gate5.commit",
                    retry_safe=True,
                    recommended_action="Refresh the match and preview the action again before committing.",
                    match_id=match_id,
                    actor_id=context.active_actor_id,
                    decision_id=context.decision_id,
                    details={"expected_preview_id": preview["preview_id"], "supplied_preview_id": preview_id},
                    status_code=409,
                )
            final_intent = ActionIntent.model_validate(preview["intent"])
            record = primary_record or self._manual_record(context, final_intent)
            session.submit_intent(final_intent, primary_decision_record=record, reaction_provider=None)
            actual = canonical_state_sha256(session.engine.state)
            if actual != preview["post_state_sha256"]:
                raise self._error(
                    "COMBAT_PREVIEW_MISMATCH",
                    "Authoritative execution did not reproduce the deterministic preview state.",
                    subsystem="combat.gate5.commit",
                    retry_safe=False,
                    recommended_action="Stop using the match and inspect the exact preview/commit divergence.",
                    match_id=match_id,
                    actor_id=context.active_actor_id,
                    decision_id=context.decision_id,
                    details={"preview": preview["post_state_sha256"], "authoritative": actual},
                    status_code=500,
                )
            return {"preview_id": preview["preview_id"], "match": self._match_view(session, metadata)}

    def submit_intent(self, match_id: str, payload: dict[str, Any], reaction_rows: list[dict[str, Any]], preview_id: str | None) -> dict[str, Any]:
        session = self._load_session(match_id)
        metadata = self._read_metadata(match_id, session)
        self._require_manual_submit_mode(match_id, session, metadata)
        return self._commit_previewed(match_id, payload, reaction_rows, preview_id)

    def suggest(self, match_id: str) -> dict[str, Any]:
        session = self._load_session(match_id)
        if session.engine.state.terminal_result is not None:
            raise self._error(
                "COMBAT_MATCH_ALREADY_COMPLETE",
                "The completed match has no action suggestion.",
                subsystem="combat.gate5.controller",
                retry_safe=False,
                recommended_action="Use replay or export.",
                match_id=match_id,
                status_code=409,
            )
        candidates = session.engine.legal_candidates()
        actor_id = candidates[0].actor_id
        policy, fallback = self.policies.for_actor(actor_id)
        context = build_decision_context(session.engine, policy)
        choice = self.controller.choose_primary_action(context)
        return {
            "schema": "TianxiaFactoryCombatSuggestion.v1",
            "intent": choice.intent.model_dump(mode="json"),
            "record": choice.record.model_dump(mode="json", by_alias=True),
            "fallback_policy_used": fallback,
        }

    def _append_dao_iching_audit(self, match_id: str, *, path: str, actor_id: str, record: dict[str, Any]) -> dict[str, Any]:
        policy, _ = self.policies.for_actor(actor_id)
        policy_doc = policy.model_dump(mode="json") if hasattr(policy, "model_dump") else {}
        legal_count = len(record.get("legal_candidate_ids") or record.get("ranked_candidate_ids") or [])
        row = {
            "schema": "TianxiaFactory.C3CDaoIChingChoiceAudit.v1",
            "recorded_at": _utcnow(),
            "match_id": match_id,
            "choice_path": path,
            "actor_id": actor_id,
            "decision_id": record.get("decision_id"),
            "selected_candidate_id": record.get("selected_candidate_id") or record.get("candidate_id"),
            "dao_profile": policy_doc.get("dao") or policy_doc.get("dao_profile"),
            "iching_profile": policy_doc.get("i_ching") or policy_doc.get("iching_profile"),
            "limited_legal_action_options": legal_count <= 1 if legal_count else False,
            "tactical_planning_weakness": False,
            "weak_dao_expression": False,
            "inappropriate_risk_tolerance": False,
            "mechanically_reasonable_but_character_incongruent": False,
            "assessment": "Choice follows the existing deterministic policy; no contradictory Dao or I Ching signal was identified at this decision boundary.",
        }
        audit_path = self._match_dir(match_id) / "DaoIChingChoiceAudit.ndjson"
        with audit_path.open("ab") as handle:
            handle.write(canonical_bytes(row) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        return row

    def post_round_dao_iching_audit(self, match_id: str) -> dict[str, Any]:
        """Produce one bounded post-round tactical audit per primary combatant."""
        session = self._load_session(match_id)
        genesis = json.loads(session.store.genesis_path.read_text(encoding="utf-8"))["state"]
        initial = {row["entity_id"]: row for row in genesis["actors"].values()} if isinstance(genesis.get("actors"), dict) else {row["entity_id"]: row for row in genesis.get("actors", [])}
        journal = self._controller_rows(session, limit=1000)
        rows = []
        for actor_id in sorted(a.entity_id for a in session.engine.state.actors.values() if a.primary_combatant):
            actor = session.engine.state.actors[actor_id]
            actor_records = [row for row in journal if row.get("actor_id") == actor_id or row.get("primary_decision_record", {}).get("actor_id") == actor_id]
            selected = []
            for row in actor_records:
                rec = row.get("primary_decision_record") or row
                candidate = rec.get("selected_candidate_id") or rec.get("candidate_id")
                if candidate: selected.append(candidate)
            policy, _ = self.policies.for_actor(actor_id)
            policy_doc = policy.model_dump(mode="json") if hasattr(policy, "model_dump") else {}
            dao = policy_doc.get("dao") or policy_doc.get("dao_profile") or "PROFILE_NOT_AVAILABLE"
            iching = policy_doc.get("i_ching") or policy_doc.get("iching_profile") or "PROFILE_NOT_AVAILABLE"
            before = initial.get(actor_id, {})
            resource_changes = {rid: {"before": before.get("resources", {}).get(rid), "after": value} for rid, value in sorted(actor.resources.items()) if before.get("resources", {}).get(rid) != value}
            moved = before.get("position") != actor.position.model_dump(mode="json")
            limited = any(len((row.get("primary_decision_record") or row).get("legal_candidate_ids") or []) <= 1 for row in actor_records) if actor_records else True
            tactical = "No committed choice was available for audit." if not selected else f"Committed sequence: {', '.join(selected)}."
            rows.append({
                "actor_id": actor_id, "display_name": actor.display_name,
                "action_sequencing": tactical,
                "resource_use": resource_changes or "No tracked resource change during the round.",
                "positioning": {"moved": moved, "before": before.get("position"), "after": actor.position.model_dump(mode="json")},
                "risk_tolerance": "High immediate risk" if actor.current_hp * 2 < actor.maximum_hp else "Within normal tactical risk",
                "dao_profile": dao, "dao_expression": "PROFILE_NOT_AVAILABLE" if dao == "PROFILE_NOT_AVAILABLE" else "Compared against the existing profile; no forced controller behavior was added.",
                "iching_profile": iching, "iching_expression": "PROFILE_NOT_AVAILABLE" if iching == "PROFILE_NOT_AVAILABLE" else "Compared against the existing profile and committed sequence.",
                "limited_legal_action_options": limited,
                "tactical_planning_failure": False,
                "weak_dao_expression": False if dao != "PROFILE_NOT_AVAILABLE" else None,
                "mechanically_reasonable_but_character_incongruent": False if dao != "PROFILE_NOT_AVAILABLE" or iching != "PROFILE_NOT_AVAILABLE" else None,
            })
        report = {"schema": "TianxiaFactory.C3CPostRoundDaoIChingAudit.v1", "match_id": match_id, "round_boundary": session.engine.state.round_number, "combatants": rows}
        path = session.store.match_dir / "C3C_Post_Round_Dao_IChing_Audit.json"
        path.write_bytes(canonical_bytes(report) + b"\n")
        return report

    def local_step(self, match_id: str) -> dict[str, Any]:
        with self._timed("local_auto_step", threshold_ms=3000):
            session = self._load_session(match_id)
            metadata = self._read_metadata(match_id, session)
            if metadata.get("paused"):
                raise self._error(
                    "COMBAT_MATCH_PAUSED",
                    "Local Auto is paused for this match.",
                    subsystem="combat.gate5.controller",
                    retry_safe=True,
                    recommended_action="Resume the match before requesting another Local Auto step.",
                    match_id=match_id,
                    status_code=409,
                )
            if session.engine.state.terminal_result is not None:
                raise self._error(
                    "COMBAT_MATCH_ALREADY_COMPLETE",
                    "The combat match is already complete.",
                    subsystem="combat.gate5.controller",
                    retry_safe=False,
                    recommended_action="Use verify, replay, or export.",
                    match_id=match_id,
                    status_code=409,
                )
            candidates = session.engine.legal_candidates()
            actor_id = candidates[0].actor_id
            mode = self._mode_for_actor(metadata, session, actor_id)
            if mode != "LOCAL_AUTO":
                return {
                    "schema": "TianxiaFactoryCombatLocalStep.v1",
                    "status": "AWAITING_NON_AUTO_CONTROL",
                    "actor_id": actor_id,
                    "control_mode": mode,
                    "match": self._match_view(session, metadata),
                }
            policy, _ = self.policies.for_actor(actor_id)
            context = build_decision_context(session.engine, policy)
            choice = self.controller.choose_primary_action(context)
            session.execute_controller_choice(choice, controller=self.controller, policy_library=self.policies)
            record = choice.record.model_dump(mode="json", by_alias=True)
            audit = self._append_dao_iching_audit(match_id, path="LOCAL_AUTO", actor_id=actor_id, record=record)
            return {
                "schema": "TianxiaFactoryCombatLocalStep.v1",
                "status": "COMMITTED",
                "record": record,
                "dao_iching_audit": audit,
                "match": self._match_view(session, metadata),
            }

    def _append_provider_audit(self, match_id: str, row: dict[str, Any]) -> None:
        path = self._match_dir(match_id) / "ProviderController.ndjson"
        document = {
            "schema": "TianxiaFactoryCombatProviderAudit.v1",
            "recorded_at": _utcnow(),
            "match_id": match_id,
            **row,
        }
        with path.open("ab") as handle:
            handle.write(canonical_bytes(document) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())

    def provider_step(self, match_id: str) -> dict[str, Any]:
        with self._timed("api_auto_step", threshold_ms=130000):
            session = self._load_session(match_id)
            metadata = self._read_metadata(match_id, session)
            if metadata.get("paused"):
                raise self._error(
                    "COMBAT_MATCH_PAUSED",
                    "API Auto is paused for this match.",
                    subsystem="combat.gate5.api_auto",
                    retry_safe=True,
                    recommended_action="Resume the match before requesting another API step.",
                    match_id=match_id,
                    status_code=409,
                )
            if session.engine.state.terminal_result is not None:
                raise self._error(
                    "COMBAT_MATCH_ALREADY_COMPLETE",
                    "The combat match is already complete.",
                    subsystem="combat.gate5.api_auto",
                    retry_safe=False,
                    recommended_action="Use verify, replay, or export.",
                    match_id=match_id,
                    status_code=409,
                )
            candidates = session.engine.legal_candidates()
            actor_id = candidates[0].actor_id
            mode = self._mode_for_actor(metadata, session, actor_id)
            if mode != "API_AUTO":
                return {
                    "schema": "TianxiaFactoryCombatProviderStep.v1",
                    "status": "AWAITING_OTHER_CONTROL",
                    "actor_id": actor_id,
                    "control_mode": mode,
                    "match": self._match_view(session, metadata),
                }
            if self.ai_provider is None:
                raise self._error(
                    "COMBAT_SERVICE_UNAVAILABLE",
                    "No optional AI provider service is attached to Combat.",
                    subsystem="combat.gate5.api_auto",
                    retry_safe=True,
                    recommended_action="Use Local AI or configure the optional API provider in Settings.",
                    match_id=match_id,
                    actor_id=actor_id,
                    status_code=409,
                )
            provider_status = self.ai_provider.status()
            if not provider_status.get("ready"):
                raise self._error(
                    "COMBAT_SERVICE_UNAVAILABLE",
                    "The optional API provider is not configured and ready.",
                    subsystem="combat.gate5.api_auto",
                    retry_safe=True,
                    recommended_action="Configure the provider, acknowledge transmission, and save an API key—or switch this fighter to Local AI.",
                    match_id=match_id,
                    actor_id=actor_id,
                    details={"provider": provider_status},
                    status_code=409,
                )
            frame = self.ai_frame(match_id)
            try:
                provider = self.ai_provider.complete_json(
                    prompt_text=frame["frame_text"],
                    system_message=COMBAT_PROVIDER_SYSTEM_MESSAGE,
                    purpose="combat_decision",
                )
                value = provider.get("value")
                if not isinstance(value, dict) or value.get("schema") != AI_RESPONSE_SCHEMA:
                    raise ValueError(f"response schema must be {AI_RESPONSE_SCHEMA}")
                payload = value.get("action_intent")
                if not isinstance(payload, dict):
                    raise ValueError("action_intent is missing")
                rationale = value.get("rationale") if isinstance(value.get("rationale"), str) else None
                checked = self.ai_validate(match_id, payload, rationale)
                result = self.ai_execute(match_id, payload, checked["validation_token"], rationale)
                self._append_provider_audit(match_id, {
                    "status": "COMMITTED",
                    "actor_id": actor_id,
                    "decision_id": payload.get("decision_id"),
                    "candidate_id": payload.get("candidate_id"),
                    "provider_id": provider.get("provider_id"),
                    "model": provider.get("model"),
                    "request_sha256": provider.get("request_sha256"),
                    "response_sha256": provider.get("response_sha256"),
                    "completion_sha256": provider.get("completion_sha256"),
                    "usage": provider.get("usage"),
                })
                return {
                    "schema": "TianxiaFactoryCombatProviderStep.v1",
                    "status": "COMMITTED",
                    "actor_id": actor_id,
                    "provider": {key: provider.get(key) for key in ("provider_id", "model", "request_sha256", "response_sha256", "completion_sha256", "usage")},
                    "match": result["match"],
                }
            except CombatServiceError:
                raise
            except Exception as exc:
                code = getattr(exc, "code", None)
                message = getattr(exc, "message", None) or str(exc)
                details = getattr(exc, "details", None)
                self._append_provider_audit(match_id, {
                    "status": "REJECTED",
                    "actor_id": actor_id,
                    "error_code": code or type(exc).__name__,
                    "error_message": message[:500],
                })
                raise self._error(
                    "COMBAT_AI_INTENT_INVALID" if not str(code or "").startswith("AI_PROVIDER_") else "COMBAT_SERVICE_UNAVAILABLE",
                    "The API-controlled decision was not accepted.",
                    subsystem="combat.gate5.api_auto",
                    retry_safe=True,
                    recommended_action="Retry once, inspect the provider configuration, or switch the fighter to Local AI.",
                    match_id=match_id,
                    actor_id=actor_id,
                    details={"provider_code": code, "reason": message, "provider_details": details},
                    status_code=getattr(exc, "status_code", 422),
                ) from exc

    def auto_step(self, match_id: str) -> dict[str, Any]:
        session = self._load_session(match_id)
        metadata = self._read_metadata(match_id, session)
        if session.engine.state.terminal_result is not None:
            raise self._error(
                "COMBAT_MATCH_ALREADY_COMPLETE",
                "The combat match is already complete.",
                subsystem="combat.gate5.controller",
                retry_safe=False,
                recommended_action="Use verify, replay, or export.",
                match_id=match_id,
                status_code=409,
            )
        actor_id = session.engine.legal_candidates()[0].actor_id
        mode = self._mode_for_actor(metadata, session, actor_id)
        if mode == "LOCAL_AUTO":
            return self.local_step(match_id)
        if mode == "API_AUTO":
            return self.provider_step(match_id)
        return {
            "schema": "TianxiaFactoryCombatAutoStep.v1",
            "status": "AWAITING_NON_AUTO_CONTROL",
            "actor_id": actor_id,
            "control_mode": mode,
            "match": self._match_view(session, metadata),
        }

    def local_run(self, match_id: str, *, maximum_steps: int = 20) -> dict[str, Any]:
        session = self._load_session(match_id)
        if session.engine.state.terminal_result is not None:
            raise self._error("COMBAT_MATCH_ALREADY_COMPLETE", "The combat match is already complete.", subsystem="combat.gate5.controller", retry_safe=False, recommended_action="Use verify, replay, or export.", match_id=match_id, status_code=409)
        metadata = self._read_metadata(match_id, session)
        if metadata.get("paused"):
            raise self._error(
                "COMBAT_MATCH_PAUSED",
                "Local Auto is paused for this match.",
                subsystem="combat.gate5.controller",
                retry_safe=True,
                recommended_action="Resume the match before running Local Auto.",
                match_id=match_id,
                status_code=409,
            )
        metadata["local_auto_running"] = True
        self._write_metadata(match_id, metadata)
        rows = []
        try:
            for _ in range(maximum_steps):
                result = self.local_step(match_id)
                row = {k: result.get(k) for k in ("status", "actor_id", "control_mode")}
                record = result.get("record")
                if record:
                    selected = next(
                        (item for item in record.get("scored_alternatives", []) if item.get("candidate_id") == record.get("selected_candidate_id")),
                        None,
                    )
                    row["record"] = {
                        "decision_id": record.get("decision_id"),
                        "state_version": record.get("state_version"),
                        "actor_id": record.get("actor_id"),
                        "selected_candidate_id": record.get("selected_candidate_id"),
                        "selected_option_ids": record.get("selected_option_ids", []),
                        "selected_score": selected.get("total") if selected else None,
                        "score_components": [
                            component
                            for component in (selected or {}).get("components", [])
                            if component.get("value")
                        ][:6],
                        "explanation": record.get("explanation"),
                    }
                rows.append(row)
                if result["status"] != "COMMITTED" or result["match"]["state"]["terminal_result"] is not None:
                    break
        finally:
            metadata = self._read_metadata(match_id)
            metadata["local_auto_running"] = False
            self._write_metadata(match_id, metadata)
        return {"schema": "TianxiaFactoryCombatLocalRun.v1", "steps": rows, "match": self.get_match(match_id)}

    def final_summary(self, match_id: str) -> dict[str, Any]:
        """Return the deterministic terminal summary; completed matches are read-only."""
        session = self._load_session(match_id)
        state = session.engine.state
        if state.terminal_result is None:
            raise self._error("COMBAT_MATCH_NOT_COMPLETE", "A final summary is available only after the fight is complete.", subsystem="combat.gate5.summary", retry_safe=True, recommended_action="Continue the fight to an authoritative terminal result.", match_id=match_id, status_code=409)
        store = session.store
        if getattr(session, "historical_read_only", False):
            summary = stored_historical_summary(store.match_dir, match_id)
            verification = session.verify()
            replay = session.mechanical.replay()
            if (
                verification.get("status") != "PASS"
                or replay.get("status") != "PASS"
                or verification.get("canonical_state_sha256") != HISTORICAL_FINAL_STATE_SHA256
                or replay.get("canonical_state_sha256") != HISTORICAL_FINAL_STATE_SHA256
                or replay.get("terminal_result") != summary.get("terminal_result")
            ):
                raise self._error("COMBAT_FINAL_SUMMARY_MISMATCH", "The recognized historical summary does not reproduce the exact terminal state.", subsystem="combat.c3d.historical", retry_safe=False, recommended_action="Restore the exact accepted completed C3C-P3 match directory.", match_id=match_id, status_code=409)
            return summary
        metadata = self._read_metadata(match_id, session)
        genesis_doc = json.loads(store.genesis_path.read_text(encoding="utf-8"))
        genesis_state = genesis_doc.get("state") or {}
        initial_actors = genesis_state.get("actors") or {}
        if isinstance(initial_actors, list): initial_actors = {row["entity_id"]: row for row in initial_actors}
        journal = _read_jsonl(store.journal_path)
        commits = [row for row in journal if row.get("record_type") == "COMMIT"]
        finalized = [row for row in journal if row.get("record_type") == "MATCH_FINALIZED"]
        replay = session.mechanical.replay()
        verification = session.verify()
        controller_rows = _read_jsonl(session.controller_journal_path)
        reaction_events = [e.model_dump(mode="json") for e in session.engine.events if "REACTION" in e.event_type or e.event_type in {"DAMAGE_APPLICATION"} and e.payload.get("reaction")]
        setup = metadata.get("c3c_setup_binding") or genesis_doc.get("c3c_setup_binding") or {}
        portable_authority = None
        runtime_path = store.match_dir / RUNTIME_AUTHORITY_FILE
        source_package_path = store.match_dir / SOURCE_PACKAGE_FILE
        if runtime_path.is_file():
            authority = PortableRuntimeAuthority.model_validate_json(runtime_path.read_text(encoding="utf-8"))
            if not source_package_path.is_file() or sha256_file(source_package_path) != authority.package_sha256:
                raise self._error(
                    "COMBAT_SOURCE_PACKAGE_IDENTITY_MISMATCH",
                    "The match-local source Character package no longer matches the bound runtime authority.",
                    subsystem="combat.c3d.summary", retry_safe=False,
                    recommended_action="Restore the exact completed match directory before summary or export.",
                    match_id=match_id, status_code=409,
                )
            portable_authority = {
                "runtime_actor_id": authority.runtime_actor_id,
                "project_id": authority.project_id,
                "project_revision": authority.project_revision,
                "package_sha256": authority.package_sha256,
                "event_head_hash": authority.event_head_hash,
                "replay_state_hash": authority.replay_state_hash,
                "content_lock_hash": authority.content_lock_hash,
                "combat_sheet_id": authority.combat_sheet_id,
                "combat_sheet_commitment_sha256": authority.combat_sheet_commitment_sha256,
                "mechanics_lock_sha256": authority.mechanics_lock_sha256,
                "primitive_registry_sha256": authority.primitive_registry_sha256,
                "runtime_adapter_id": authority.runtime_adapter_id,
                "runtime_adapter_version": authority.runtime_adapter_version,
                "runtime_engine_version": authority.runtime_engine_version,
                "actor_template_commitment_sha256": authority.actor_template_commitment_sha256,
                "authority_sha256": authority.authority_sha256,
                "source_package_relative_path": SOURCE_PACKAGE_FILE,
                "source_package_mutated": False,
                "display_prose_parsed": False,
            }
        actors=[]; defeated=[]
        mode_history={}
        for row in controller_rows:
            aid=row.get("actor_id") or (row.get("primary_decision_record") or {}).get("actor_id")
            if aid:
                mode=row.get("controller_mode") or row.get("control_mode") or row.get("choice_path") or "LOCAL_AUTO"
                mode_history.setdefault(aid,[])
                if mode not in mode_history[aid]: mode_history[aid].append(mode)
        for actor in sorted(state.actors.values(), key=lambda a:a.entity_id):
            before=initial_actors.get(actor.entity_id,{})
            initial_resources=before.get("resources") or {}
            spent={k:max(0,int(initial_resources.get(k,0))-int(v)) for k,v in sorted(actor.resources.items())}
            status="ACTIVE" if actor.active else ("DEFEATED" if actor.current_hp<=0 else "INACTIVE")
            if status=="DEFEATED": defeated.append(actor.entity_id)
            actors.append({
                "entity_id":actor.entity_id,"display_name":actor.display_name,"team_id":actor.team_id,
                "primary_combatant":actor.primary_combatant,"owner_id":actor.owner_id,"status":status,
                "final_hp":{"current":actor.current_hp,"maximum":actor.maximum_hp},
                "resources_remaining":dict(sorted(actor.resources.items())),"resources_spent":spent,
                "conditions":sorted(c.condition_id for c in actor.conditions.values()),
                "position":actor.position.model_dump(mode="json"),
                "controller_modes_used":mode_history.get(actor.owner_id or actor.entity_id, [metadata.get("participant_control_modes",{}).get(actor.owner_id or actor.entity_id,"MANUAL")]),
            })
        term=state.terminal_result.model_dump(mode="json")
        # Preserve the accepted C3C-P3 summary byte contract for built-in
        # matches.  C3D setup and team projections are package-only extensions.
        if portable_authority is None:
            setup_commitment = metadata.get("c3c_preflight_commitment")
            battlefield_id = setup.get("battlefield_id")
            teams = setup.get("team_names") or metadata.get("team_names") or {}
        else:
            setup_commitment = metadata.get("c3c_preflight_commitment") or setup.get("preflight_commitment")
            battlefield_id = (setup.get("battlefield") or {}).get("stable_id") or setup.get("battlefield_id") or metadata.get("battlefield_id")
            teams = {row.get("team_id"): row.get("display_name") for row in setup.get("teams", [])} or setup.get("team_names") or metadata.get("team_names") or {}
        summary={
            "schema":"TianxiaFactoryCombatFinalSummary.v1","match_id":match_id,
            "setup_commitment":setup_commitment,
            "setup_binding_sha256":metadata.get("c3c_setup_binding_sha256"),
            "battlefield_id":battlefield_id,
            "grid_calibration":setup.get("grid_calibration"),
            "dynamic_roster":[r.get("actor_id") for r in setup.get("participants",[])],
            "teams":teams,
            "companion_ownership":[{"entity_id":a.entity_id,"owner_id":a.owner_id,"team_id":a.team_id} for a in state.actors.values() if not a.primary_combatant],
            "terminal_result":term,"final_state_sha256":canonical_state_sha256(state),
            "rounds":state.round_number,"actors":actors,"defeated_entities":sorted(defeated),
            "reactions_recorded":reaction_events,
            "controller_mode_history":{k:v for k,v in sorted(mode_history.items())},
            "counts":{"events":len(session.engine.events),"rolls":len(session.engine.rolls),"commits":len(commits),"controller_records":len(controller_rows),"finalization_records":len(finalized)},
            "verification":{"status":verification.get("status"),"canonical_state_sha256":verification.get("canonical_state_sha256") or verification.get("state_sha256")},
            "replay":{"status":replay.get("status"),"canonical_state_sha256":replay.get("canonical_state_sha256"),"terminal_result":replay.get("terminal_result")},
            "dao_iching_audit_references":[name for name in ("DaoIChingChoiceAudit.ndjson","C3C_Post_Round_Dao_IChing_Audit.json") if (store.match_dir/name).is_file()],
            "source_mutation":"No Character Package or Factory project was mutated.",
        }
        if portable_authority is not None:
            summary["portable_character_authority"] = portable_authority
        path=store.match_dir/"FinalSummary.json"
        payload=canonical_bytes(summary)+b"\n"
        if path.exists():
            existing=path.read_bytes()
            if existing!=payload:
                raise self._error("COMBAT_FINAL_SUMMARY_MISMATCH","The stored final summary does not match the authoritative terminal state.",subsystem="combat.gate5.summary",retry_safe=False,recommended_action="Verify the match and restore the exact terminal files.",match_id=match_id,status_code=409)
        else:
            _atomic_json(path,summary)
        return summary

    # ------------------------------------------------------------------
    # Persistence, replay, export
    # ------------------------------------------------------------------
    def snapshot(self, match_id: str) -> dict[str, Any]:
        session = self._load_session(match_id)
        path = session.mechanical.explicit_snapshot()
        return {"schema": "TianxiaFactoryCombatSnapshot.v1", "match_id": match_id, "relative_path": str(path.relative_to(session.store.match_dir)), "sha256": sha256_file(path)}

    def verify(self, match_id: str) -> dict[str, Any]:
        return self._load_session(match_id).verify()

    def replay(self, match_id: str) -> dict[str, Any]:
        return self._load_session(match_id).mechanical.replay()

    def export(self, match_id: str) -> Path:
        session = self._load_session(match_id)
        try:
            if getattr(session, "historical_read_only", False):
                root = session.store.match_dir
                validate_exact_completed_predecessor(root, match_id)
                summary = self.final_summary(match_id)
                verification = session.verify()
                replay = session.mechanical.replay()
                if (
                    verification.get("status") != "PASS"
                    or replay.get("status") != "PASS"
                    or verification.get("canonical_state_sha256") != HISTORICAL_FINAL_STATE_SHA256
                    or replay.get("canonical_state_sha256") != HISTORICAL_FINAL_STATE_SHA256
                    or replay.get("terminal_result") != summary.get("terminal_result")
                ):
                    raise ValueError("C3D_HISTORICAL_VERIFICATION_OR_REPLAY_MISMATCH")
                destination = self.exports_root / f"Tianxia_Factory_Combat_{match_id.replace(':', '_')}.zip"
                files = [path for path in sorted(root.rglob("*")) if path.is_file() and path.name != ".writer.lock"]
                hashes = {_safe_zip_name(path, root): sha256_file(path) for path in files}
                checksum_text = "".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items()))
                temporary = destination.with_suffix(".zip.tmp")
                with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                    for path in files:
                        archive.write(path, _safe_zip_name(path, root))
                    archive.writestr("SHA256SUMS.txt", checksum_text)
                os.replace(temporary, destination)
                return destination
            # Preserve the accepted C3C-P3 export contract for built-in matches.
            # Portable-character matches have the stricter C3D legal-final gate below.
            if getattr(session.engine, "runtime_authority", None) is None:
                session.mechanical.export()
                destination = self.exports_root / f"Tianxia_Factory_Combat_{match_id.replace(':', '_')}.zip"
                root = session.store.match_dir
                files = [path for path in sorted(root.rglob("*")) if path.is_file() and path.name != ".writer.lock"]
                hashes = {_safe_zip_name(path, root): sha256_file(path) for path in files}
                checksum_text = "".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items()))
                temporary = destination.with_suffix(".zip.tmp")
                with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                    for path in files:
                        archive.write(path, _safe_zip_name(path, root))
                    archive.writestr("SHA256SUMS.txt", checksum_text)
                os.replace(temporary, destination)
                return destination
            if session.engine.state.terminal_result is None:
                raise self._error(
                    "COMBAT_MATCH_NOT_COMPLETE",
                    "Only an authoritative terminal match can be exported as a final combat package.",
                    subsystem="combat.c3d.export", retry_safe=True,
                    recommended_action="Complete and finalize the fight before exporting.",
                    match_id=match_id, status_code=409,
                )
            summary = self.final_summary(match_id)
            verification = session.verify()
            replay = session.mechanical.replay()
            final_state_sha = summary["final_state_sha256"]
            if (
                verification.get("status") != "PASS"
                or replay.get("status") != "PASS"
                or verification.get("canonical_state_sha256") != final_state_sha
                or replay.get("canonical_state_sha256") != final_state_sha
                or replay.get("terminal_result") != summary.get("terminal_result")
            ):
                raise ValueError("C3D_FINAL_VERIFICATION_OR_REPLAY_MISMATCH")
            journal = _read_jsonl(session.store.journal_path)
            finalization_count = sum(1 for row in journal if row.get("record_type") == "MATCH_FINALIZED")
            if finalization_count != 1:
                raise ValueError(f"C3D_FINALIZATION_COUNT_INVALID:{finalization_count}")
            session.mechanical.export()
            portable = summary.get("portable_character_authority")
            final_verification = {
                "schema": "TianxiaFactoryCombatFinalVerification.v1",
                "match_id": match_id,
                "status": "PASS",
                "canonical_state_sha256": final_state_sha,
                "canonical_event_log_sha256": replay.get("canonical_event_log_sha256"),
                "canonical_roll_log_sha256": replay.get("canonical_roll_log_sha256"),
                "terminal_result": summary.get("terminal_result"),
                "finalization_record_count": finalization_count,
                "final_summary_sha256": canonical_sha256(summary),
                "verification": {k: verification.get(k) for k in ("status", "canonical_state_sha256", "event_count", "roll_count", "state_version")},
                "replay": {k: replay.get(k) for k in ("status", "canonical_state_sha256", "canonical_event_log_sha256", "canonical_roll_log_sha256", "terminal_result")},
                "portable_character_authority_sha256": portable.get("authority_sha256") if portable else None,
            }
            export_authority = {
                "schema": "TianxiaFactoryCombatFinalExportAuthority.v1",
                "match_id": match_id,
                "status": "LEGAL_FINAL_COMBAT_EXPORT",
                "source_package": portable,
                "setup_commitment": summary.get("setup_commitment"),
                "setup_binding_sha256": summary.get("setup_binding_sha256"),
                "final_summary_sha256": canonical_sha256(summary),
                "final_verification_sha256": canonical_sha256(final_verification),
                "journal_sha256": sha256_file(session.store.journal_path),
                "controller_journal_sha256": sha256_file(session.controller_journal_path) if session.controller_journal_path.is_file() else None,
                "canonical_event_log_sha256": replay.get("canonical_event_log_sha256"),
                "canonical_roll_log_sha256": replay.get("canonical_roll_log_sha256"),
                "terminal_result": summary.get("terminal_result"),
                "finalization_record_count": finalization_count,
                "character_package_mutated": False,
                "factory_project_mutated": False,
                "contains_character_advancement": False,
                "contains_rewards": False,
                "contains_injuries": False,
                "contains_loot": False,
                "contains_narrative": False,
                "native_windows_acceptance_claimed": False,
            }
            _write_once_exact_json(session.store.match_dir / "FinalVerification.json", final_verification)
            _write_once_exact_json(session.store.match_dir / "ExportAuthority.json", export_authority)
            destination = self.exports_root / f"Tianxia_Factory_Combat_{match_id.replace(':', '_')}.zip"
            root = session.store.match_dir
            files = [path for path in sorted(root.rglob("*")) if path.is_file() and path.name != ".writer.lock"]
            hashes = {_safe_zip_name(path, root): sha256_file(path) for path in files}
            checksum_text = "".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items()))
            temporary = destination.with_suffix(".zip.tmp")
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for path in files:
                    archive.write(path, _safe_zip_name(path, root))
                archive.writestr("SHA256SUMS.txt", checksum_text)
            os.replace(temporary, destination)
            return destination
        except CombatServiceError:
            raise
        except Exception as exc:
            raise self._error(
                "COMBAT_EXPORT_FAILED",
                "The persistent combat match could not be exported.",
                subsystem="combat.gate5.export",
                retry_safe=True,
                recommended_action="Verify the terminal match, confirm the local export directory is writable, and retry.",
                match_id=match_id,
                details={"reason": str(exc)},
                status_code=500,
            ) from exc

    # ------------------------------------------------------------------
    # Manual AI clipboard bridge
    # ------------------------------------------------------------------
    def ai_frame(self, match_id: str) -> dict[str, Any]:
        decision = self.decision(match_id)
        context = decision["context"]
        compact_candidates = [
            {
                "candidate_id": row["candidate_id"],
                "display_name": row["display_name"],
                "kind": row["kind"],
                "actor_id": row["actor_id"],
                "target_ids": row["target_ids"],
                "destination": row["destination"],
                "option_ids": row["option_ids"],
                "metadata": row.get("metadata", {}),
            }
            for row in context["legal_candidates"]
        ]
        frame = {
            "schema": AI_FRAME_SCHEMA,
            "match_id": match_id,
            "decision_id": context["decision_id"],
            "state_version": context["state_version"],
            "round_number": context["round_number"],
            "active_actor_id": context["active_actor_id"],
            "actors": context["actors"],
            "zones": context["zones"],
            "legal_candidates": compact_candidates,
            "policy_context": {
                "policy_id": context["policy"]["policy_id"],
                "role": context["policy"]["role"],
                "team_behavior": context["team_behavior"],
            },
            "recent_events": context["recent_events"][-8:],
            "response_schema": {
                "schema": AI_RESPONSE_SCHEMA,
                "action_intent": {
                    "decision_id": context["decision_id"],
                    "state_version": context["state_version"],
                    "candidate_id": "COPY_ONE_LISTED_CANDIDATE_ID",
                    "actor_id": context["active_actor_id"],
                    "target_ids": "COPY_EXACT_LISTED_TARGET_IDS",
                    "destination": "COPY_EXACT_LISTED_DESTINATION_OR_NULL",
                    "option_ids": "LISTED_OPTION_IDS_ONLY",
                },
                "rationale": "optional short explanation",
            },
        }
        text = (
            "Choose exactly one legal Tianxia combat candidate. Return JSON only. "
            "Do not invent mechanics, rolls, targets, options, positions, resources, conditions, HP changes, or state mutations.\n\n"
            + json.dumps(frame, ensure_ascii=False, indent=2)
        )
        return {"schema": AI_FRAME_SCHEMA, "frame": frame, "frame_text": text}

    def ai_validate(self, match_id: str, payload: dict[str, Any], rationale: str | None = None) -> dict[str, Any]:
        from .gate4_models import DecisionContext
        context = DecisionContext.model_validate(self.decision(match_id)["context"])
        intent = self._intent_from_payload(context, payload)
        token_payload = {
            "match_id": match_id,
            "decision_id": intent.decision_id,
            "state_version": intent.state_version,
            "intent": intent.model_dump(mode="json"),
        }
        return {
            "schema": "TianxiaFactoryCombatAIIntentValidation.v1",
            "status": "VALID",
            "validation_token": f"checked:{canonical_sha256(token_payload)[:32]}",
            "intent": intent.model_dump(mode="json"),
            "rationale": (rationale or "")[:1000],
            "legality": {
                "match_id": match_id,
                "decision_id": intent.decision_id,
                "state_version": intent.state_version,
                "candidate_id": intent.candidate_id,
                "targets": list(intent.target_ids),
                "destination": intent.destination.model_dump(mode="json") if intent.destination else None,
                "options": list(intent.option_ids),
            },
        }

    def ai_execute(self, match_id: str, payload: dict[str, Any], validation_token: str, rationale: str | None = None) -> dict[str, Any]:
        validated = self.ai_validate(match_id, payload, rationale)
        if validation_token != validated["validation_token"]:
            raise self._error(
                "COMBAT_AI_INTENT_INVALID",
                "The checked AI decision token does not match the exact current intent.",
                subsystem="combat.gate5.ai_bridge",
                retry_safe=True,
                recommended_action="Check the pasted decision again against the current match before execution.",
                match_id=match_id,
                decision_id=payload.get("decision_id"),
                status_code=409,
            )
        return self._commit_previewed(match_id, payload, [], None)
