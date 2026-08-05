from __future__ import annotations

import io
import json
import os
import re
import stat
import unicodedata
import zipfile
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any

from app.core import Database, FoundryError, canonical_json, sha256_bytes, sha256_json, utcnow
from catalog.coverage import Stage1CatalogCoverageService
from catalog.service import CatalogService
from contracts.canonical import ZERO_HASH, canonical_project_document, canonical_project_hash
from contracts.registry import SchemaRegistry
from project_store.service import ProjectStore

STAGE_ID = "stage_1_source_blueprint"
PROMPT_SCHEMA = "TianxiaFoundry.Stage1PromptEnvelope.v2"
RESPONSE_SCHEMA = "TianxiaFoundry.AIClipboard.Stage1.v2"
EXCHANGE_SCHEMA = "TianxiaFoundry.Stage1ClipboardExchange.v2"
BATCH_SCHEMA = "TianxiaFoundry.BlueprintDecisionBatch.v1"
DECISION_SCHEMA = "TianxiaFoundry.BlueprintDecision.v1"
INTENT_STATE_SCHEMA = "TianxiaFoundry.BlueprintIntentState.v1"

# These are advisory quality warnings only. Planner prose can never create mechanics.
PLACEHOLDERS = {"not recorded", "not itemized", "unnamed talent", "unknown", "tbd", "placeholder", "sheet"}
QUALITY_PATTERNS = (
    ("PLANNER_TEXT_CONTAINS_DAMAGE_DICE", re.compile(r"\b\d+d\d+\b", re.I)),
    ("PLANNER_TEXT_CONTAINS_STAT_LIKE_TEXT", re.compile(r"\b(?:hp|hit points?|armor class|save dc)\s*[:=]?\s*\d+\b", re.I)),
    ("PLANNER_TEXT_CONTAINS_NETWORK_INSTRUCTION", re.compile(r"(?:https?://|\bcurl\b|\bwget\b|\bfetch\s*\(|\brequests\.)", re.I)),
)

SLOT_SPECS: tuple[dict[str, Any], ...] = (
    {"slot_id": "path_choice", "label": "Primary Path", "types": ("path",), "max": 1, "limit": 12, "allow_none": False},
    {"slot_id": "subpath_choice", "label": "Subpath or Tradition", "types": ("subpath", "tradition"), "max": 1, "limit": 8, "allow_none": True},
    {"slot_id": "background_choice", "label": "Background", "types": ("background",), "max": 1, "limit": 8, "allow_none": True},
    {"slot_id": "background_sphere_choice", "label": "Background Sphere", "types": ("background_sphere",), "max": 1, "limit": 8, "allow_none": True},
    {"slot_id": "background_talent_choice", "label": "Background Talent", "types": ("background_talent",), "max": 1, "limit": 8, "allow_none": True},
    {"slot_id": "origin_insight_choice", "label": "Origin Insight", "types": ("cultivation_insight", "origin_insight", "insight"), "max": 1, "limit": 8, "allow_none": True},
    {"slot_id": "method_choice", "label": "Proposed Cultivation Method", "types": ("cultivation_method",), "max": 1, "limit": 8, "allow_none": True},
    # Foundation packs can contain more than one hundred Path-bound expressions.
    # Truncating this slot silently changes legality, so the full bounded catalog
    # set is offered and cross-slot Path compatibility is checked below.
    {"slot_id": "foundation_choice", "label": "Proposed Foundation Expression", "types": ("foundation_expression", "foundation"), "max": 1, "limit": None, "allow_none": True},
    {"slot_id": "sphere_priorities", "label": "Additional Sphere Priorities", "types": ("sphere",), "max": 8, "limit": 50, "allow_none": True},
    {"slot_id": "advancement_skeleton", "label": "Published Talent Priorities", "types": ("talent",), "max": None, "limit": None, "allow_none": True},
    {"slot_id": "insight_priorities", "label": "Additional Insight Priorities", "types": ("cultivation_insight", "origin_insight", "insight"), "max": 8, "limit": 50, "allow_none": True},
    {"slot_id": "item_priorities", "label": "Preferred Items and Equipment", "types": ("item", "equipment", "weapon", "armor", "treasure", "treasure_set", "consumable", "growth_treasure"), "max": 8, "limit": 50, "allow_none": True},
)

AUTHORED_FIELDS: tuple[dict[str, Any], ...] = (
    {"field_id": "character_identity", "label": "Character identity and naming notes", "max_length": 800, "required": False},
    {"field_id": "source_interpretation", "label": "Source interpretation", "max_length": 2400, "required": False},
    {"field_id": "role", "label": "Intended narrative/combat role without mechanics", "max_length": 1200, "required": False},
    {"field_id": "tactics", "label": "High-level tactical behavior", "max_length": 1800, "required": False},
    {"field_id": "presentation", "label": "Presentation and visual identity", "max_length": 1600, "required": False},
    {"field_id": "source_fidelity", "label": "Source-fidelity priorities and uncertainties", "max_length": 1600, "required": False},
    {"field_id": "ability_plan_intent", "label": "Ability-generation plan intent", "max_length": 500, "required": False},
    {"field_id": "manual_forged_classification_intent", "label": "Manual-versus-forged classification intent", "max_length": 800, "required": False},
)

FORBIDDEN_RULES = (
    "Return one JSON object only; do not add Markdown outside it.",
    "Resolve every decision slot exactly once using selected, explicit_none, blocked_missing_authority, or deferred_with_reason.",
    "Select only choice IDs offered under the same decision slot.",
    "Do not invent IDs or mechanics. Planner prose is display-only and can never create rules or advancement.",
    "Stage 1 choices are blueprint intent. They do not acquire Spheres, talents, Methods, Foundations, or other mechanics.",
    "Every required_choice_id is locked by the owner. Include every required choice in that slot and never replace it.",
    "Do not request or perform network calls.",
)

INTENT_OPTION_SLOTS = {
    "subpath_choice",
    "sphere_priorities",
    "advancement_skeleton",
    "insight_priorities",
}


class Stage1ClipboardService:
    def __init__(self, db: Database):
        self.db = db
        self.projects = ProjectStore(db)
        self.registry = SchemaRegistry(db.settings.root_dir)
        self.coverage = Stage1CatalogCoverageService(db)
        self.catalog = CatalogService(db)

    def _project(self, project_id: str) -> dict[str, Any]:
        return self.projects.get_project(project_id)["project"]

    @staticmethod
    def _preferred_ids(project: dict[str, Any]) -> list[str]:
        result: list[str] = []
        for lock in project.get("user_locks", []):
            if lock.get("field") in {"preferred_record_ids", "stage1.preferred_record_ids", "source.preferred_record_ids"}:
                values = lock.get("value") if isinstance(lock.get("value"), list) else [lock.get("value")]
                for value in values:
                    if isinstance(value, str) and value not in result:
                        result.append(value)
        return result

    @staticmethod
    def _required_choice_map(project: dict[str, Any]) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for lock in project.get("user_locks", []):
            if lock.get("field") != "character_sheet.locked_choices" or not isinstance(lock.get("value"), dict):
                continue
            for slot_id, values in lock["value"].items():
                if not isinstance(slot_id, str) or not isinstance(values, list):
                    continue
                cleaned = []
                for value in values:
                    if isinstance(value, str) and value and value not in cleaned:
                        cleaned.append(value)
                if cleaned:
                    result[slot_id] = cleaned
        return result

    def _records_for_ids(self, project: dict[str, Any], record_ids: set[str]) -> list[dict[str, Any]]:
        if not record_ids:
            return []
        effective = self.catalog.effective_catalog(project["project_id"])
        return [record for record in effective["records"] if record["record_id"] in record_ids]

    @staticmethod
    def _validated_intent_reference_allowed(slot_id: str, record: dict[str, Any]) -> bool:
        """A validated Sphere index may name intent but never grant mechanics."""
        factory = record.get("compatibility", {}).get("factory", {})
        return (
            slot_id == "sphere_priorities"
            and record.get("content_type") == "sphere"
            and record.get("publication", {}).get("status") == "validated"
            and factory.get("authority_classification") == "reference-only"
            and bool(factory.get("selected_authority"))
        )

    @staticmethod
    def _choice(record: dict[str, Any]) -> dict[str, Any]:
        source = record["source"]
        binding = record["content_binding"]
        legality = record.get("legality", {})
        dependencies = [x for x in record.get("dependencies", []) if isinstance(x, str)]
        parent_relationships = [{"relation": "dependency", "record_id": x} for x in dependencies]
        return {
            "choice_id": record["record_id"],
            "name": record["display_name"],
            "description": str(record.get("display_projection", {}).get("short_description") or record.get("summary") or record["display_name"])[:1000],
            "content_type": record["content_type"],
            "authority": str(record.get("compatibility", {}).get("factory", {}).get("authority_classification") or "canonical"),
            "publication_state": str(record.get("publication", {}).get("status") or "draft"),
            "source": {"path": str(source.get("path") or ""), "anchor": str(source.get("anchor") or ""), "source_hash": source["source_hash"]},
            "content_binding": {"pack_id": binding["pack_id"], "pack_version": binding["pack_version"], "pack_hash": binding["pack_hash"], "record_hash": record["record_hash"]},
            "prerequisites": deepcopy(legality.get("prerequisites") or []),
            "acquisition_channels": sorted(set(legality.get("acquisition_channels") or [])),
            "parent_relationships": parent_relationships,
            "availability": {
                "minimum_cl": legality.get("minimum_cl"),
                "realm_rules": deepcopy(legality.get("realm_rules") or {}),
                "source_cl": deepcopy(legality.get("source_cl") or {}),
                "suppression": deepcopy(legality.get("suppression") or {}),
            },
            "incompatibilities": deepcopy(legality.get("incompatibilities") or []),
        }

    def build_envelope(self, project_id: str) -> dict[str, Any]:
        project = self._project(project_id)
        # Recompute project-scoped authority for every prompt. Catalog rows can be
        # published, superseded, or repaired without changing an old project's
        # immutable lock tuple; a process-local cache keyed only by that tuple could
        # therefore offer stale authority. Correctness takes priority here. A later
        # optimization must key on a deterministic scoped-record fingerprint.
        coverage = self.coverage.build(project_id=project_id)
        coverage_by_slot = {x["slot_id"]: x for x in coverage["categories"]}
        effective_records = self.catalog.effective_catalog(project_id)["records"]
        effective_by_id = {record["record_id"]: record for record in effective_records}
        preferred = self._preferred_ids(project)
        preferred_rank = {record_id: index for index, record_id in enumerate(preferred)}
        required_by_slot = self._required_choice_map(project)
        slots: list[dict[str, Any]] = []
        for spec in SLOT_SPECS:
            category = coverage_by_slot[spec["slot_id"]]
            choice_key = "intent_selectable_record_ids" if spec["slot_id"] in INTENT_OPTION_SLOTS else "selectable_record_ids"
            selectable_ids = set(category.get(choice_key) or [])
            records = [effective_by_id[record_id] for record_id in selectable_ids if record_id in effective_by_id]
            records = [x for x in records if x.get("content_type") in spec["types"]]
            records.sort(key=lambda x: (0 if x["record_id"] in preferred_rank else 1, preferred_rank.get(x["record_id"], 10**9), x["record_id"]))
            choices = [self._choice(x) for x in records[: spec["limit"]]]
            slot: dict[str, Any] = {
                "slot_id": spec["slot_id"], "label": spec["label"], "min_selections": 1,
                "max_selections": spec["max"], "allow_none": spec["allow_none"],
                "coverage_state": "offered" if choices else "blocked_missing_authority", "choices": choices,
            }
            required = required_by_slot.get(spec["slot_id"], [])
            if required:
                offered_ids = {choice["choice_id"] for choice in choices}
                unavailable = [choice_id for choice_id in required if choice_id not in offered_ids]
                if unavailable:
                    raise FoundryError(
                        "CHARACTER_SHEET_LOCK_UNAVAILABLE",
                        "An owner-locked character-sheet choice is unavailable in this project's exact rules lock.",
                        details={"slot_id": spec["slot_id"], "choice_ids": unavailable},
                    )
                slot["required_choice_ids"] = required
            if not choices:
                reasons = category.get("blocked_reasons") or []
                slot["blocked_reason_code"] = str(reasons[0].get("code") if reasons else "CATEGORY_SELECTABLE_AUTHORITY_MISSING")
                slot["blocked_reason"] = str(reasons[0].get("message") if reasons else "No complete published authority is selectable for this slot.")
            slots.append(slot)
        seed = {
            "project_id": project_id, "project_revision": project["revision"],
            "catalog_build_id": project["content_lock"]["catalog_build_id"], "content_lock_hash": project["content_lock"]["lock_hash"],
            "user_locks": project["user_locks"], "decision_slots": slots, "coverage_report_hash": coverage["report_hash"],
            "authored_fields": list(AUTHORED_FIELDS), "forbidden_authority_rules": list(FORBIDDEN_RULES),
        }
        prompt_id = "stage1.prompt." + sha256_json(seed)[:40]
        envelope = {
            "schema_version": PROMPT_SCHEMA, "prompt_id": prompt_id, "project_id": project_id,
            "project_revision": project["revision"], "catalog_build_id": project["content_lock"]["catalog_build_id"],
            "content_lock_hash": project["content_lock"]["lock_hash"], "stage_id": STAGE_ID,
            "user_locks": deepcopy(project["user_locks"]), "decision_slots": slots,
            "decision_state_contract": ["selected", "explicit_none", "blocked_missing_authority", "deferred_with_reason"],
            "authored_fields": list(AUTHORED_FIELDS), "forbidden_authority_rules": list(FORBIDDEN_RULES),
            "response_schema_version": RESPONSE_SCHEMA,
        }
        self._validate_contract(envelope, PROMPT_SCHEMA, "STAGE1_ENVELOPE_SCHEMA_INVALID")
        return envelope

    def _prompt_text(self, envelope: dict[str, Any]) -> str:
        return (
            "TIANXIA CHARACTER FOUNDRY - STAGE 1 BLUEPRINT INTENT\n"
            "You are an untrusted planning assistant. The local Foundry is the sole mechanical authority.\n"
            "Return exactly one JSON object validating against RESPONSE_SCHEMA. Resolve every slot exactly once.\n"
            "The application calculates all authoritative hashes. response_payload_sha256 is optional and ignored for authority.\n"
            "Selections express future blueprint intent only and create no advancement or CL0 mechanics.\n\n"
            "PROMPT_ENVELOPE\n" + canonical_json(envelope) + "\n\n"
            "RESPONSE_SCHEMA\n" + canonical_json(self.registry.schema(RESPONSE_SCHEMA)) + "\n"
        )

    def generate_prompt(self, project_id: str) -> dict[str, Any]:
        envelope = self.build_envelope(project_id)
        prompt_bytes = self._prompt_text(envelope).encode("utf-8")
        prompt_hash = sha256_bytes(prompt_bytes)
        now = utcnow()
        with self.db.transaction() as conn:
            old = conn.execute("SELECT prompt_sha256,prompt_bytes,created_at FROM stage1_prompt_exchanges WHERE prompt_id=?", (envelope["prompt_id"],)).fetchone()
            if old:
                if old["prompt_sha256"] != prompt_hash or bytes(old["prompt_bytes"]) != prompt_bytes:
                    raise FoundryError("STAGE1_PROMPT_ID_COLLISION", "A deterministic prompt ID is bound to different bytes.")
                created_at = old["created_at"]
            else:
                conn.execute(
                    """INSERT INTO stage1_prompt_exchanges(prompt_id,project_id,project_revision,catalog_build_id,content_lock_hash,envelope_schema_version,envelope_json,prompt_bytes,prompt_sha256,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (envelope["prompt_id"], project_id, envelope["project_revision"], envelope["catalog_build_id"], envelope["content_lock_hash"], envelope["schema_version"], canonical_json(envelope), prompt_bytes, prompt_hash, now),
                )
                created_at = now
        return {"prompt_id": envelope["prompt_id"], "project_id": project_id, "project_revision": envelope["project_revision"], "prompt_sha256": prompt_hash, "prompt_text": prompt_bytes.decode("utf-8"), "envelope": envelope, "created_at": created_at, "deterministic": True}

    def get_prompt(self, prompt_id: str) -> dict[str, Any]:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM stage1_prompt_exchanges WHERE prompt_id=?", (prompt_id,)).fetchone()
        if not row:
            raise FoundryError("STAGE1_PROMPT_NOT_FOUND", "No Stage 1 prompt has that ID.", status_code=404)
        return {"prompt_id": prompt_id, "project_id": row["project_id"], "project_revision": row["project_revision"], "prompt_sha256": row["prompt_sha256"], "prompt_text": bytes(row["prompt_bytes"]).decode("utf-8"), "envelope": json.loads(row["envelope_json"]), "created_at": row["created_at"]}

    def prepare_prompt(self, project_id: str) -> dict[str, Any]:
        """Resolve one current-revision request for the selected canonical project."""
        project = self._project(project_id)
        revision = int(project["revision"])
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT prompt_id FROM stage1_prompt_exchanges WHERE project_id=? AND project_revision=? "
                "ORDER BY created_at DESC,prompt_id DESC LIMIT 1",
                (project_id, revision),
            ).fetchone()
        result = self.get_prompt(row["prompt_id"]) if row else self.generate_prompt(project_id)
        result["reused"] = bool(row)
        return result

    @staticmethod
    def _safe_export_stem(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "character").strip()).strip("._-")
        return cleaned[:96] or "character"

    def _prompt_row(self, prompt_id: str):
        with self.db.connection() as conn:
            row = conn.execute(
                """SELECT p.*,j.working_name FROM stage1_prompt_exchanges p
                   JOIN projects j ON j.project_id=p.project_id WHERE p.prompt_id=?""",
                (prompt_id,),
            ).fetchone()
        if not row:
            raise FoundryError("STAGE1_PROMPT_NOT_FOUND", "No Stage 1 prompt has that ID.", status_code=404)
        prompt_bytes = bytes(row["prompt_bytes"])
        if sha256_bytes(prompt_bytes) != row["prompt_sha256"]:
            raise FoundryError("STAGE1_PROMPT_BYTES_MISMATCH", "The saved Stage 1 request no longer matches its sealed hash.", status_code=500)
        return row, prompt_bytes

    def save_prompt_file(self, prompt_id: str, *, zipped: bool, reuse_existing: bool = False) -> dict[str, Any]:
        row, prompt_bytes = self._prompt_row(prompt_id)
        export_dir = self.db.settings.exports_dir / "CharacterBuilder"
        export_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{self._safe_export_stem(row['working_name'])}_{self._safe_export_stem(prompt_id)}"
        prompt_name = stem + ".md"
        target = export_dir / (stem + (".zip" if zipped else ".md"))
        if target.exists() and reuse_existing:
            if not target.is_file():
                raise FoundryError("CHARACTER_BUILDER_EXPORT_EXISTS", "The expected export path is not a file.", details={"path": str(target)}, status_code=409)
            if zipped:
                try:
                    with zipfile.ZipFile(target) as existing:
                        if existing.testzip() is not None or existing.read(prompt_name) != prompt_bytes:
                            raise ValueError("existing prompt ZIP differs")
                except (OSError, KeyError, zipfile.BadZipFile, ValueError) as exc:
                    raise FoundryError("CHARACTER_BUILDER_EXPORT_EXISTS", "The existing request ZIP does not match this sealed Stage 1 request.", details={"path": str(target)}, status_code=409) from exc
            elif target.read_bytes() != prompt_bytes:
                raise FoundryError("CHARACTER_BUILDER_EXPORT_EXISTS", "The existing request file does not match this sealed Stage 1 request.", details={"path": str(target)}, status_code=409)
            return {
                "saved": True, "reused": True, "kind": "zip" if zipped else "markdown",
                "path": str(target.resolve()), "filename": target.name, "prompt_id": prompt_id,
                "prompt_sha256": row["prompt_sha256"], "saved_file_sha256": sha256_bytes(target.read_bytes()),
                "prompt_bytes_preserved": True, "recommended": bool(zipped),
            }
        if target.exists():
            raise FoundryError(
                "CHARACTER_BUILDER_EXPORT_EXISTS",
                "That export already exists. Rename or move the existing file before saving another copy.",
                details={"path": str(target)},
                status_code=409,
            )
        if not zipped:
            target.write_bytes(prompt_bytes)
        else:
            readme = (
                "# Send this ZIP to ChatGPT\n\n"
                f"Open `{prompt_name}` and use the complete request exactly as written.\n"
                f"Prompt ID: `{prompt_id}`\n"
                f"Prompt SHA-256: `{row['prompt_sha256']}`\n"
                "Return a reply ZIP containing exactly one `Factory_Character_Plan_Response.json` file. The Factory also accepts a single UTF-8 `.json`, `.md`, or `.txt` reply file. Do not edit or shorten the request.\n"
            ).encode("utf-8")
            sums = (
                f"{sha256_bytes(prompt_bytes)}  {prompt_name}\n"
                f"{sha256_bytes(readme)}  README_SEND_TO_CHATGPT.md\n"
            ).encode("utf-8")
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for name, data in ((prompt_name, prompt_bytes), ("README_SEND_TO_CHATGPT.md", readme), ("SHA256SUMS.txt", sums)):
                    info = zipfile.ZipInfo(name)
                    info.date_time = (1980, 1, 1, 0, 0, 0)
                    info.external_attr = 0o100644 << 16
                    zf.writestr(info, data)
            with zipfile.ZipFile(target) as zf:
                if zf.testzip() is not None:
                    target.unlink(missing_ok=True)
                    raise FoundryError("CHARACTER_BUILDER_PROMPT_ZIP_INVALID", "The saved request ZIP failed its integrity check.", status_code=500)
        return {
            "saved": True,
            "reused": False,
            "kind": "zip" if zipped else "markdown",
            "path": str(target.resolve()),
            "filename": target.name,
            "prompt_id": prompt_id,
            "prompt_sha256": row["prompt_sha256"],
            "saved_file_sha256": sha256_bytes(target.read_bytes()),
            "prompt_bytes_preserved": (not zipped and target.read_bytes() == prompt_bytes) or zipped,
            "recommended": bool(zipped),
        }

    @staticmethod
    def _decode_reply_file(filename: str, data: bytes) -> dict[str, Any]:
        suffix = Path(filename).suffix.casefold()
        if suffix not in {".txt", ".md", ".json"}:
            raise FoundryError("STAGE1_REPLY_FILE_TYPE_INVALID", "Choose a UTF-8 .txt, .md, or .json reply file.")
        if not data or len(data) > 2_000_000:
            raise FoundryError("STAGE1_REPLY_FILE_SIZE_INVALID", "The reply file is empty or larger than 2 MB.")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FoundryError("STAGE1_REPLY_NOT_UTF8", "The reply file must be UTF-8 text.", details={"offset": exc.start}) from exc
        if not text.strip():
            raise FoundryError("STAGE1_REPLY_FILE_EMPTY", "The reply file contains no response text.")
        return {"response_text": text, "source_filename": Path(filename).name, "response_sha256": sha256_bytes(data)}

    def load_reply_file(self, filename: str, data: bytes) -> dict[str, Any]:
        result = self._decode_reply_file(filename, data)
        return {**result, "source_kind": "file", "uses_stage1_validator": True}

    def load_reply_zip(self, filename: str, data: bytes) -> dict[str, Any]:
        if Path(filename).suffix.casefold() != ".zip":
            raise FoundryError("STAGE1_REPLY_ZIP_TYPE_INVALID", "Choose a .zip reply package.")
        if not data or len(data) > 4_000_000:
            raise FoundryError("STAGE1_REPLY_ZIP_SIZE_INVALID", "The reply ZIP is empty or larger than 4 MB.")
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise FoundryError("STAGE1_REPLY_ZIP_INVALID", "The reply ZIP is not a valid ZIP archive.") from exc
        with zf:
            infos = zf.infolist()
            if len(infos) > 12:
                raise FoundryError("STAGE1_REPLY_ZIP_TOO_MANY_ENTRIES", "The reply ZIP contains too many files.")
            seen: set[str] = set()
            folded: set[str] = set()
            normalized: set[str] = set()
            eligible = []
            expanded = 0
            compressed = 0
            for info in infos:
                name = info.filename.replace("\\", "/")
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", name):
                    raise FoundryError("STAGE1_REPLY_ZIP_UNSAFE_PATH", "The reply ZIP contains an unsafe path.", details={"entry": name})
                if name in seen or name.casefold() in folded or unicodedata.normalize("NFC", name) in normalized:
                    raise FoundryError("STAGE1_REPLY_ZIP_COLLISION", "The reply ZIP contains duplicate or colliding paths.", details={"entry": name})
                seen.add(name); folded.add(name.casefold()); normalized.add(unicodedata.normalize("NFC", name))
                mode = (info.external_attr >> 16) & 0xFFFF
                file_type = stat.S_IFMT(mode)
                if file_type not in (0, stat.S_IFREG, stat.S_IFDIR) or file_type == stat.S_IFLNK:
                    raise FoundryError("STAGE1_REPLY_ZIP_SPECIAL_FILE", "The reply ZIP may contain ordinary files only.", details={"entry": name})
                if info.flag_bits & 1:
                    raise FoundryError("STAGE1_REPLY_ZIP_ENCRYPTED", "Encrypted reply ZIPs are not supported.")
                if info.is_dir():
                    continue
                expanded += info.file_size
                compressed += info.compress_size
                if expanded > 2_000_000 or compressed > 4_000_000:
                    raise FoundryError("STAGE1_REPLY_ZIP_EXPANSION_LIMIT", "The reply ZIP exceeds the safe size limit.")
                if Path(name).suffix.casefold() in {".txt", ".md", ".json"}:
                    eligible.append(info)
            if len(eligible) != 1:
                raise FoundryError(
                    "STAGE1_REPLY_ZIP_AMBIGUOUS",
                    "The reply ZIP must contain exactly one .txt, .md, or .json reply file.",
                    details={"eligible_files": [item.filename for item in eligible]},
                )
            info = eligible[0]
            payload = zf.read(info)
            if zf.testzip() is not None:
                raise FoundryError("STAGE1_REPLY_ZIP_CRC_FAILED", "The reply ZIP failed its integrity check.")
        result = self._decode_reply_file(info.filename, payload)
        return {**result, "source_kind": "zip", "archive_filename": Path(filename).name, "archive_sha256": sha256_bytes(data), "uses_stage1_validator": True}

    def _validate_contract(self, obj: dict[str, Any], version: str, code: str) -> None:
        report = self.registry.report(obj, version)
        if not report["valid"]:
            raise FoundryError(code, f"Object failed {version}.", details=report["diagnostics"])

    @staticmethod
    def _quality_warnings(payload: dict[str, Any]) -> list[dict[str, Any]]:
        fields = [(f"/response_payload/authored_notes/{i}/value", str(x.get("value", ""))) for i, x in enumerate(payload.get("authored_notes", []))]
        fields.append(("/response_payload/planner_rationale", str(payload.get("planner_rationale", ""))))
        warnings: list[dict[str, Any]] = []
        for pointer, text in fields:
            normalized = " ".join(text.strip().lower().split())
            if normalized in PLACEHOLDERS or "placeholder" in normalized:
                warnings.append({"code": "PLANNER_PLACEHOLDER_TEXT", "pointer": pointer})
            for code, pattern in QUALITY_PATTERNS:
                match = pattern.search(text)
                if match:
                    warnings.append({"code": code, "pointer": pointer, "match": match.group(0)})
        return warnings

    @staticmethod
    def _decision_diagnostics(payload: dict[str, Any], envelope: dict[str, Any]) -> list[dict[str, Any]]:
        diagnostics: list[dict[str, Any]] = []
        slots = {x["slot_id"]: x for x in envelope["decision_slots"]}
        all_offered = {x["choice_id"] for slot in slots.values() for x in slot["choices"]}
        seen: set[str] = set()
        for index, decision in enumerate(payload.get("decisions", [])):
            pointer = f"/response_payload/decisions/{index}"
            slot_id = decision.get("slot_id")
            if slot_id not in slots:
                diagnostics.append({"code": "WRONG_DECISION_SLOT", "pointer": pointer + "/slot_id", "slot_id": slot_id})
                continue
            if slot_id in seen:
                diagnostics.append({"code": "DUPLICATE_DECISION_SLOT", "pointer": pointer + "/slot_id", "slot_id": slot_id})
                continue
            seen.add(slot_id)
            slot = slots[slot_id]
            state = decision.get("state")
            ids = decision.get("choice_ids") or []
            required_ids = slot.get("required_choice_ids") or []
            reason_code = decision.get("reason_code")
            if required_ids and state != "selected":
                diagnostics.append({"code": "OWNER_LOCKED_SELECTION_REQUIRED", "pointer": pointer + "/state", "required_choice_ids": required_ids})
            missing_required = [choice_id for choice_id in required_ids if choice_id not in ids]
            if missing_required:
                diagnostics.append({"code": "OWNER_LOCKED_CHOICE_OMITTED", "pointer": pointer + "/choice_ids", "choice_ids": missing_required})
            reason = str(decision.get("reason") or "").strip()
            if slot["coverage_state"] == "blocked_missing_authority" and state != "blocked_missing_authority":
                diagnostics.append({"code": "BLOCKED_AUTHORITY_STATE_REQUIRED", "pointer": pointer + "/state", "expected": "blocked_missing_authority", "actual": state})
            if state == "selected":
                if slot["coverage_state"] != "offered":
                    diagnostics.append({"code": "SELECTION_BLOCKED_MISSING_AUTHORITY", "pointer": pointer + "/state"})
                maximum = slot.get("max_selections")
                if len(ids) < slot["min_selections"] or (maximum is not None and len(ids) > maximum):
                    diagnostics.append({"code": "SLOT_CARDINALITY_INVALID", "pointer": pointer + "/choice_ids", "minimum": slot["min_selections"], "maximum": maximum, "actual": len(ids)})
                offered = {x["choice_id"] for x in slot["choices"]}
                for offset, record_id in enumerate(ids):
                    if record_id not in offered:
                        diagnostics.append({"code": "UNKNOWN_ID" if record_id not in all_offered else "ID_NOT_OFFERED_IN_SLOT", "pointer": f"{pointer}/choice_ids/{offset}", "choice_id": record_id})
            elif state == "explicit_none":
                if not slot["allow_none"]:
                    diagnostics.append({"code": "EXPLICIT_NONE_NOT_ALLOWED", "pointer": pointer + "/state"})
                if ids:
                    diagnostics.append({"code": "NON_SELECTION_HAS_IDS", "pointer": pointer + "/choice_ids"})
                if reason_code not in {"legal_none", "not_applicable"} or not reason:
                    diagnostics.append({"code": "EXPLICIT_NONE_REASON_REQUIRED", "pointer": pointer + "/reason"})
            elif state == "blocked_missing_authority":
                if ids:
                    diagnostics.append({"code": "NON_SELECTION_HAS_IDS", "pointer": pointer + "/choice_ids"})
                if slot["coverage_state"] != "blocked_missing_authority":
                    diagnostics.append({"code": "FALSE_BLOCKED_AUTHORITY_STATE", "pointer": pointer + "/state"})
                if reason_code != slot.get("blocked_reason_code") or reason != slot.get("blocked_reason"):
                    diagnostics.append({"code": "BLOCKED_REASON_MISMATCH", "pointer": pointer + "/reason_code", "expected": {"reason_code": slot.get("blocked_reason_code"), "reason": slot.get("blocked_reason")}})
            elif state == "deferred_with_reason":
                if ids:
                    diagnostics.append({"code": "NON_SELECTION_HAS_IDS", "pointer": pointer + "/choice_ids"})
                if reason_code != "deferred_future_decision" or not reason:
                    diagnostics.append({"code": "DEFERRED_REASON_REQUIRED", "pointer": pointer + "/reason"})
        for slot_id in slots:
            if slot_id not in seen:
                diagnostics.append({"code": "DECISION_SLOT_OMITTED", "pointer": "/response_payload/decisions", "slot_id": slot_id})

        # Foundation Expressions are Path-specific published mechanics. Stage 1
        # chooses Path and Foundation in one response, so the relation cannot be
        # pre-filtered safely without hiding choices. Validate the pair after both
        # decisions are known and repeat this check at persisted-batch commit.
        by_slot = {item.get("slot_id"): item for item in payload.get("decisions", []) if isinstance(item, dict)}
        path_decision = by_slot.get("path_choice") or {}
        foundation_decision = by_slot.get("foundation_choice") or {}
        if path_decision.get("state") == "selected" and foundation_decision.get("state") == "selected":
            selected_paths = set(path_decision.get("choice_ids") or [])
            foundation_choices = {choice["choice_id"]: choice for choice in slots.get("foundation_choice", {}).get("choices", [])}
            offered_path_ids = {choice["choice_id"] for choice in slots.get("path_choice", {}).get("choices", [])}
            for offset, foundation_id in enumerate(foundation_decision.get("choice_ids") or []):
                choice = foundation_choices.get(foundation_id)
                if not choice or choice.get("content_type") != "foundation_expression":
                    continue
                prerequisite_targets = {
                    item.get("target_id")
                    for item in choice.get("prerequisites", [])
                    if isinstance(item, dict) and item.get("operator") in {"requires", "one_of", "all_of"}
                }
                declared_path_targets = prerequisite_targets & offered_path_ids
                pointer = f"/response_payload/decisions/foundation_choice/choice_ids/{offset}"
                if not declared_path_targets:
                    diagnostics.append({
                        "code": "FOUNDATION_PATH_PREREQUISITE_MISSING",
                        "pointer": pointer,
                        "foundation_expression_id": foundation_id,
                        "selected_path_ids": sorted(selected_paths),
                    })
                elif not selected_paths.issubset(declared_path_targets):
                    diagnostics.append({
                        "code": "FOUNDATION_PATH_MISMATCH",
                        "pointer": pointer,
                        "foundation_expression_id": foundation_id,
                        "selected_path_ids": sorted(selected_paths),
                        "allowed_path_ids": sorted(declared_path_targets),
                    })

        return diagnostics

    def _response_diagnostics(self, response: dict[str, Any], prompt: dict[str, Any]) -> list[dict[str, Any]]:
        envelope = prompt["envelope"]
        diagnostics: list[dict[str, Any]] = []
        for field, code in (
            ("prompt_id", "PROMPT_ID_MISMATCH"), ("project_id", "PROJECT_ID_MISMATCH"),
            ("catalog_build_id", "CATALOG_BUILD_MISMATCH"), ("content_lock_hash", "CONTENT_LOCK_MISMATCH"),
            ("stage_id", "STAGE_ID_MISMATCH"),
        ):
            if response.get(field) != envelope.get(field):
                diagnostics.append({"code": code, "pointer": f"/{field}", "expected": envelope.get(field), "actual": response.get(field)})
        if response.get("prompt_sha256") != prompt["prompt_sha256"]:
            diagnostics.append({"code": "PROMPT_HASH_MISMATCH", "pointer": "/prompt_sha256"})
        if response.get("expected_project_revision") != envelope["project_revision"]:
            diagnostics.append({"code": "EXPECTED_REVISION_MISMATCH", "pointer": "/expected_project_revision"})
        current = self._project(envelope["project_id"])
        if current["revision"] != envelope["project_revision"]:
            diagnostics.append({"code": "STALE_PROJECT_REVISION", "pointer": "/expected_project_revision", "expected": current["revision"], "actual": envelope["project_revision"]})
        if current["content_lock"]["catalog_build_id"] != envelope["catalog_build_id"]:
            diagnostics.append({"code": "CATALOG_BUILD_CHANGED", "pointer": "/catalog_build_id"})
        if current["content_lock"]["lock_hash"] != envelope["content_lock_hash"]:
            diagnostics.append({"code": "CONTENT_LOCK_CHANGED", "pointer": "/content_lock_hash"})
        payload = response.get("response_payload") or {}
        diagnostics.extend(self._decision_diagnostics(payload, envelope))

        field_specs = {x["field_id"]: x for x in envelope["authored_fields"]}
        seen_fields: set[str] = set()
        for index, note in enumerate(payload.get("authored_notes", [])):
            field_id = note.get("field_id")
            pointer = f"/response_payload/authored_notes/{index}"
            if field_id not in field_specs:
                diagnostics.append({"code": "AUTHORED_FIELD_NOT_OFFERED", "pointer": pointer + "/field_id"})
                continue
            if field_id in seen_fields:
                diagnostics.append({"code": "AUTHORED_FIELD_DUPLICATE", "pointer": pointer + "/field_id"})
            seen_fields.add(field_id)
            if len(str(note.get("value", ""))) > field_specs[field_id]["max_length"]:
                diagnostics.append({"code": "AUTHORED_FIELD_TOO_LONG", "pointer": pointer + "/value"})
        return diagnostics

    @staticmethod
    def _transition(conn, batch_id: str, from_state: str | None, to_state: str, actor_type: str, actor_identifier: str | None = None, details: dict[str, Any] | None = None) -> None:
        ordinal = conn.execute("SELECT COALESCE(MAX(ordinal),0)+1 FROM stage1_batch_transitions WHERE batch_id=?", (batch_id,)).fetchone()[0]
        transition_id = "stage1.transition." + sha256_json({"batch_id": batch_id, "ordinal": ordinal, "to_state": to_state})[:40]
        conn.execute(
            "INSERT INTO stage1_batch_transitions(transition_id,batch_id,ordinal,from_state,to_state,actor_type,actor_identifier,details_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (transition_id, batch_id, ordinal, from_state, to_state, actor_type, actor_identifier, canonical_json(details or {}), utcnow()),
        )

    def _decision_objects(self, batch_id: str, response: dict[str, Any], prompt: dict[str, Any]) -> list[dict[str, Any]]:
        by_slot = {x["slot_id"]: x for x in response["response_payload"]["decisions"]}
        result: list[dict[str, Any]] = []
        for ordinal, slot in enumerate(prompt["envelope"]["decision_slots"], start=1):
            submitted = by_slot[slot["slot_id"]]
            offered = {x["choice_id"]: x for x in slot["choices"]}
            snapshots = []
            for record_id in submitted.get("choice_ids") or []:
                choice = deepcopy(offered[record_id])
                binding = choice["content_binding"]
                snapshots.append({
                    "record_id": record_id, "record_hash": binding["record_hash"], "pack_id": binding["pack_id"],
                    "pack_version": binding["pack_version"], "pack_hash": binding["pack_hash"],
                    "choice_snapshot_hash": sha256_json(choice), "choice_snapshot": choice,
                })
            core = {
                "schema_version": DECISION_SCHEMA, "decision_id": "", "batch_id": batch_id, "ordinal": ordinal,
                "slot_id": slot["slot_id"], "state": submitted["state"], "selected_record_ids": list(submitted.get("choice_ids") or []),
                "record_snapshots": snapshots, "reason_code": submitted.get("reason_code"), "reason": submitted.get("reason"),
            }
            core["decision_id"] = "stage1.decision." + sha256_json({k: v for k, v in core.items() if k != "decision_id"})[:40]
            self._validate_contract(core, DECISION_SCHEMA, "BLUEPRINT_DECISION_SCHEMA_INVALID")
            result.append(core)
        return result

    @staticmethod
    def _batch_seed(*, batch_id: str, attempt_id: str, prompt: dict[str, Any], response: dict[str, Any], exact_hash: str, payload_hash: str, submitted_hash: str | None, decisions: list[dict[str, Any]]) -> dict[str, Any]:
        payload = response["response_payload"]
        return {
            "schema_version": BATCH_SCHEMA, "batch_id": batch_id, "attempt_id": attempt_id,
            "project_id": prompt["project_id"], "prompt_id": prompt["prompt_id"], "response_id": response["response_id"],
            "expected_project_revision": prompt["project_revision"], "catalog_build_id": prompt["envelope"]["catalog_build_id"],
            "content_lock_hash": prompt["envelope"]["content_lock_hash"], "exact_response_sha256": exact_hash,
            "computed_payload_sha256": payload_hash, "submitted_payload_sha256": submitted_hash,
            "decisions": decisions, "authored_notes": payload.get("authored_notes", []),
            "planner_rationale": str(payload.get("planner_rationale", "")),
        }

    def _persist_batch(self, *, attempt_id: str, prompt: dict[str, Any], response: dict[str, Any] | None, exact_hash: str, payload_hash: str | None, submitted_hash: str | None, validation: dict[str, Any], decisions: list[dict[str, Any]]) -> None:
        batch_id = "stage1.batch." + sha256_json({"attempt_id": attempt_id, "prompt_id": prompt["prompt_id"]})[:40]
        now = utcnow()
        valid = bool(validation["valid"])
        payload = response.get("response_payload") if response else None
        state = "approval_pending" if valid else "validation_failed"
        batch_seed = self._batch_seed(
            batch_id=batch_id, attempt_id=attempt_id, prompt=prompt, response=response,
            exact_hash=exact_hash, payload_hash=payload_hash, submitted_hash=submitted_hash, decisions=decisions,
        ) if valid and response and payload_hash else {
            "response_id": response.get("response_id") if response else None,
            "authored_notes": (payload or {}).get("authored_notes", []),
            "planner_rationale": str((payload or {}).get("planner_rationale", "")),
        }
        batch_hash = sha256_json(batch_seed) if valid else None
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO stage1_decision_batches(batch_id,attempt_id,project_id,prompt_id,response_id,schema_version,state,expected_project_revision,catalog_build_id,content_lock_hash,exact_response_sha256,computed_payload_sha256,submitted_payload_sha256,response_payload_json,authored_notes_json,planner_rationale,validation_json,batch_hash,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (batch_id, attempt_id, prompt["project_id"], prompt["prompt_id"], batch_seed["response_id"], BATCH_SCHEMA, state, prompt["project_revision"], prompt["envelope"]["catalog_build_id"], prompt["envelope"]["content_lock_hash"], exact_hash, payload_hash, submitted_hash, canonical_json(payload) if payload is not None else None, canonical_json(batch_seed["authored_notes"]), batch_seed["planner_rationale"], canonical_json(validation), batch_hash, now, now),
            )
            self._transition(conn, batch_id, None, "response_received", "system")
            if valid:
                for item in decisions:
                    decision_hash = sha256_json(item)
                    conn.execute(
                        """INSERT INTO stage1_blueprint_decisions(decision_id,batch_id,ordinal,slot_id,decision_state,selected_record_ids_json,record_snapshots_json,reason_code,reason,decision_json,decision_hash,created_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (item["decision_id"], batch_id, item["ordinal"], item["slot_id"], item["state"], canonical_json(item["selected_record_ids"]), canonical_json(item["record_snapshots"]), item["reason_code"], item["reason"], canonical_json(item), decision_hash, now),
                    )
                self._transition(conn, batch_id, "response_received", "validated", "system")
                self._transition(conn, batch_id, "validated", "approval_pending", "system")
                if response:
                    existing = conn.execute("SELECT response_hash FROM ai_stage_responses WHERE response_id=?", (response["response_id"],)).fetchone()
                    if existing and existing["response_hash"] != exact_hash:
                        raise FoundryError("RESPONSE_ID_CONFLICT", "The response ID is already bound to different exact bytes.")
                    if not existing:
                        conn.execute(
                            "INSERT INTO ai_stage_responses(response_id,project_id,project_revision,protocol_version,response_json,response_hash,validation_json,accepted_at) VALUES(?,?,?,?,?,?,?,?)",
                            (response["response_id"], prompt["project_id"], prompt["project_revision"], response["protocol_version"], canonical_json(response), exact_hash, canonical_json({"valid": True, "attempt_id": attempt_id, "batch_id": batch_id}), now),
                        )
            else:
                self._transition(conn, batch_id, "response_received", "validation_failed", "system", details={"diagnostic_count": len(validation.get("diagnostics", []))})

    def _resume_orphan_attempt(self, prompt: dict[str, Any], response_text: str, orphan: Any) -> dict[str, Any]:
        """Finish a v2 attempt preserved before a process interruption.

        Response-attempt evidence is append-only: recovery updates the incomplete row
        in place and creates the missing typed batch; it never deletes or replaces the
        exact submitted bytes.
        """
        raw = response_text.encode("utf-8")
        exact_hash = sha256_bytes(raw)
        if bytes(orphan["exact_response_bytes"]) != raw or orphan["exact_response_sha256"] != exact_hash:
            raise FoundryError("STAGE1_ORPHAN_RESPONSE_MISMATCH", "Recovery text differs from the preserved orphan attempt bytes.")
        response: dict[str, Any] | None = None
        parsing_status = "parsed"
        diagnostics: list[dict[str, Any]] = []
        payload_hash: str | None = None
        submitted_hash: str | None = None
        response_id: str | None = None
        try:
            parsed = json.loads(response_text)
            if not isinstance(parsed, dict):
                raise ValueError("Top-level response must be a JSON object.")
            response = parsed
            response_id = response.get("response_id") if isinstance(response.get("response_id"), str) else None
            if isinstance(response.get("response_payload"), dict):
                payload_hash = sha256_json(response["response_payload"])
            submitted_hash = response.get("response_payload_sha256") if isinstance(response.get("response_payload_sha256"), str) else None
        except Exception as exc:
            parsing_status = "malformed_json"
            diagnostics.append({"code": "MALFORMED_JSON", "pointer": "", "message": str(exc)})
        if response_id:
            with self.db.connection() as conn:
                conflict = conn.execute("SELECT exact_response_sha256 FROM stage1_response_attempts WHERE response_id=? AND attempt_id<>?", (response_id, orphan["attempt_id"])).fetchone()
            if conflict and conflict["exact_response_sha256"] != exact_hash:
                diagnostics.append({"code": "RESPONSE_ID_CONFLICT", "pointer": "/response_id"})
        if response is not None:
            schema_report = self.registry.report(response, RESPONSE_SCHEMA)
            diagnostics.extend({"code": "RESPONSE_SCHEMA_INVALID", **item} for item in schema_report["diagnostics"])
            diagnostics.extend(self._response_diagnostics(response, prompt))
        warnings = self._quality_warnings((response or {}).get("response_payload") or {})
        valid = not diagnostics
        batch_id = "stage1.batch." + sha256_json({"attempt_id": orphan["attempt_id"], "prompt_id": prompt["prompt_id"]})[:40]
        decisions = self._decision_objects(batch_id, response, prompt) if valid and response else []
        validation = {
            "valid": valid, "diagnostics": diagnostics, "warnings": warnings,
            "computed_payload_sha256": payload_hash, "submitted_payload_sha256": submitted_hash,
            "submitted_hash_matches": None if submitted_hash is None else submitted_hash == payload_hash,
            "mechanical_authority": False, "advancement_event_count": 0,
            "proposed_blueprint_diff": [{"slot_id": item["slot_id"], "state": item["state"], "selected_record_ids": item["selected_record_ids"]} for item in decisions],
        }
        with self.db.transaction() as conn:
            conn.execute(
                """UPDATE stage1_response_attempts SET response_id=?,response_payload_sha256=?,parsing_status=?,response_json=?,validation_json=?
                   WHERE attempt_id=? AND NOT EXISTS(SELECT 1 FROM stage1_decision_batches WHERE attempt_id=?)""",
                (response_id, payload_hash, parsing_status, canonical_json(response) if response is not None else None, canonical_json(validation), orphan["attempt_id"], orphan["attempt_id"]),
            )
        self._persist_batch(attempt_id=orphan["attempt_id"], prompt=prompt, response=response, exact_hash=exact_hash, payload_hash=payload_hash, submitted_hash=submitted_hash, validation=validation, decisions=decisions)
        result = self._attempt_result(orphan["attempt_id"])
        result["idempotent"] = True
        return result

    def validate_response(self, prompt_id: str, response_text: str, *, prior_attempt_id: str | None = None) -> dict[str, Any]:
        prompt = self.get_prompt(prompt_id)
        raw = response_text.encode("utf-8")
        exact_hash = sha256_bytes(raw)
        attempt_id = "stage1.attempt." + sha256_json({"prompt_id": prompt_id, "exact_response_sha256": exact_hash})[:40]
        with self.db.connection() as conn:
            existing = conn.execute(
                """SELECT a.*,EXISTS(SELECT 1 FROM stage1_decision_batches b WHERE b.attempt_id=a.attempt_id) AS has_batch
                   FROM stage1_response_attempts a WHERE a.prompt_id=? AND a.exact_response_sha256=?""",
                (prompt_id, exact_hash),
            ).fetchone()
        if existing:
            if existing["has_batch"]:
                result = self._attempt_result(existing["attempt_id"])
                result["idempotent"] = True
                return result
            return self._resume_orphan_attempt(prompt, response_text, existing)

        response: dict[str, Any] | None = None
        parsing_status = "parsed"
        diagnostics: list[dict[str, Any]] = []
        payload_hash: str | None = None
        submitted_hash: str | None = None
        response_id: str | None = None
        try:
            parsed = json.loads(response_text)
            if not isinstance(parsed, dict):
                raise ValueError("Top-level response must be a JSON object.")
            response = parsed
            response_id = response.get("response_id") if isinstance(response.get("response_id"), str) else None
            if isinstance(response.get("response_payload"), dict):
                payload_hash = sha256_json(response["response_payload"])
            submitted_hash = response.get("response_payload_sha256") if isinstance(response.get("response_payload_sha256"), str) else None
        except Exception as exc:
            parsing_status = "malformed_json"
            diagnostics.append({"code": "MALFORMED_JSON", "pointer": "", "message": str(exc)})

        with self.db.transaction() as conn:
            if response_id:
                prior = conn.execute("SELECT exact_response_sha256 FROM stage1_response_attempts WHERE response_id=?", (response_id,)).fetchone()
                if prior and prior["exact_response_sha256"] != exact_hash:
                    diagnostics.append({"code": "RESPONSE_ID_CONFLICT", "pointer": "/response_id"})
            conn.execute(
                """INSERT INTO stage1_response_attempts(attempt_id,prompt_id,prior_attempt_id,response_id,exact_response_bytes,exact_response_sha256,response_payload_sha256,parsing_status,response_json,validation_json,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (attempt_id, prompt_id, prior_attempt_id, response_id, raw, exact_hash, payload_hash, parsing_status, canonical_json(response) if response is not None else None, canonical_json({"valid": False, "diagnostics": diagnostics}), utcnow()),
            )

        if response is not None:
            schema_report = self.registry.report(response, RESPONSE_SCHEMA)
            diagnostics.extend({"code": "RESPONSE_SCHEMA_INVALID", **x} for x in schema_report["diagnostics"])
            diagnostics.extend(self._response_diagnostics(response, prompt))
        warnings = self._quality_warnings((response or {}).get("response_payload") or {})
        valid = not diagnostics
        decisions = self._decision_objects("stage1.batch." + sha256_json({"attempt_id": attempt_id, "prompt_id": prompt_id})[:40], response, prompt) if valid and response else []
        validation = {
            "valid": valid, "diagnostics": diagnostics, "warnings": warnings,
            "computed_payload_sha256": payload_hash, "submitted_payload_sha256": submitted_hash,
            "submitted_hash_matches": None if submitted_hash is None else submitted_hash == payload_hash,
            "mechanical_authority": False, "advancement_event_count": 0,
            "proposed_blueprint_diff": [{"slot_id": x["slot_id"], "state": x["state"], "selected_record_ids": x["selected_record_ids"]} for x in decisions],
        }
        with self.db.transaction() as conn:
            conn.execute("UPDATE stage1_response_attempts SET validation_json=? WHERE attempt_id=?", (canonical_json(validation), attempt_id))
        self._persist_batch(attempt_id=attempt_id, prompt=prompt, response=response, exact_hash=exact_hash, payload_hash=payload_hash, submitted_hash=submitted_hash, validation=validation, decisions=decisions)
        result = self._attempt_result(attempt_id)
        result["idempotent"] = False
        return result

    def _load_decisions(self, conn, batch_id: str) -> list[dict[str, Any]]:
        return [json.loads(row["decision_json"]) for row in conn.execute("SELECT decision_json FROM stage1_blueprint_decisions WHERE batch_id=? ORDER BY ordinal", (batch_id,))]

    def _verify_persisted_batch(self, conn, batch: Any, prompt: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        attempt = conn.execute("SELECT * FROM stage1_response_attempts WHERE attempt_id=?", (batch["attempt_id"],)).fetchone()
        if not attempt or not attempt["response_json"]:
            raise FoundryError("STAGE1_BATCH_INTEGRITY_FAILED", "The batch has no exact parsed response authority.")
        response = json.loads(attempt["response_json"])
        try:
            exact_parsed = json.loads(bytes(attempt["exact_response_bytes"]).decode("utf-8"))
        except Exception as exc:
            raise FoundryError("STAGE1_BATCH_INTEGRITY_FAILED", "The preserved exact response bytes no longer parse.", details=str(exc)) from exc
        if not isinstance(exact_parsed, dict) or canonical_json(exact_parsed) != attempt["response_json"]:
            raise FoundryError("STAGE1_BATCH_INTEGRITY_FAILED", "Parsed response storage differs from the preserved exact submitted text.")
        self._validate_contract(response, RESPONSE_SCHEMA, "STAGE1_RESPONSE_SCHEMA_CHANGED")
        payload = response.get("response_payload")
        computed_payload_hash = sha256_json(payload) if isinstance(payload, dict) else None
        checks = {
            "project_id": prompt["project_id"], "prompt_id": prompt["prompt_id"], "response_id": response.get("response_id"),
            "expected_project_revision": prompt["project_revision"], "catalog_build_id": prompt["envelope"]["catalog_build_id"],
            "content_lock_hash": prompt["envelope"]["content_lock_hash"], "exact_response_sha256": attempt["exact_response_sha256"],
            "computed_payload_sha256": computed_payload_hash,
        }
        mismatches = {key: {"expected": expected, "actual": batch[key]} for key, expected in checks.items() if batch[key] != expected}
        if sha256_bytes(bytes(attempt["exact_response_bytes"])) != attempt["exact_response_sha256"]:
            mismatches["exact_response_bytes"] = {"expected": attempt["exact_response_sha256"], "actual": "hash_mismatch"}
        if attempt["response_payload_sha256"] != computed_payload_hash:
            mismatches["attempt_payload_hash"] = {"expected": computed_payload_hash, "actual": attempt["response_payload_sha256"]}
        if batch["response_payload_json"] != canonical_json(payload):
            mismatches["response_payload_json"] = {"expected": computed_payload_hash, "actual": sha256_json(json.loads(batch["response_payload_json"])) if batch["response_payload_json"] else None}
        attempt_validation = json.loads(attempt["validation_json"])
        batch_validation = json.loads(batch["validation_json"])
        if not attempt_validation.get("valid") or attempt_validation != batch_validation:
            mismatches["validation_json"] = {"expected": "identical valid validation records", "actual": {"attempt_valid": attempt_validation.get("valid"), "equal": attempt_validation == batch_validation}}
        if mismatches:
            raise FoundryError("STAGE1_BATCH_INTEGRITY_FAILED", "Persisted batch columns do not match the immutable response and prompt.", details=mismatches)

        decisions: list[dict[str, Any]] = []
        rows = conn.execute("SELECT * FROM stage1_blueprint_decisions WHERE batch_id=? ORDER BY ordinal", (batch["batch_id"],)).fetchall()
        for row in rows:
            item = json.loads(row["decision_json"])
            self._validate_contract(item, DECISION_SCHEMA, "BLUEPRINT_DECISION_SCHEMA_INVALID")
            expected_id = "stage1.decision." + sha256_json({key: value for key, value in item.items() if key != "decision_id"})[:40]
            expected_columns = {
                "decision_id": item["decision_id"], "batch_id": item["batch_id"], "ordinal": item["ordinal"],
                "slot_id": item["slot_id"], "decision_state": item["state"],
                "selected_record_ids_json": canonical_json(item["selected_record_ids"]),
                "record_snapshots_json": canonical_json(item["record_snapshots"]),
                "reason_code": item["reason_code"], "reason": item["reason"],
                "decision_hash": sha256_json(item),
            }
            column_mismatch = {key: {"expected": expected, "actual": row[key]} for key, expected in expected_columns.items() if row[key] != expected}
            if item["decision_id"] != expected_id:
                column_mismatch["deterministic_decision_id"] = {"expected": expected_id, "actual": item["decision_id"]}
            if column_mismatch:
                raise FoundryError("STAGE1_DECISION_INTEGRITY_FAILED", "A persisted decision row or hash was modified.", details={"slot_id": item.get("slot_id"), "mismatches": column_mismatch})
            decisions.append(item)

        semantic_payload = {
            "decisions": [{"slot_id": item["slot_id"], "state": item["state"], "choice_ids": item["selected_record_ids"], "reason_code": item["reason_code"], "reason": item["reason"]} for item in decisions],
            "authored_notes": json.loads(batch["authored_notes_json"]), "planner_rationale": batch["planner_rationale"],
        }
        semantic_issues = self._decision_diagnostics(semantic_payload, prompt["envelope"])
        if semantic_issues:
            raise FoundryError("STAGE1_DECISION_SEMANTICS_CHANGED", "Persisted decisions no longer satisfy the exact offered envelope.", details=semantic_issues)
        if canonical_json(semantic_payload["authored_notes"]) != batch["authored_notes_json"] or semantic_payload["planner_rationale"] != str(payload.get("planner_rationale", "")):
            raise FoundryError("STAGE1_BATCH_INTEGRITY_FAILED", "Persisted authored metadata differs from the exact response.")
        normalized_submitted = [{
            "slot_id": item.get("slot_id"), "state": item.get("state"), "choice_ids": item.get("choice_ids") or [],
            "reason_code": item.get("reason_code"), "reason": item.get("reason"),
        } for item in payload.get("decisions", [])]
        if semantic_payload["decisions"] != normalized_submitted:
            raise FoundryError("STAGE1_BATCH_INTEGRITY_FAILED", "Persisted decisions differ from the exact submitted response.")

        seed = self._batch_seed(
            batch_id=batch["batch_id"], attempt_id=batch["attempt_id"], prompt=prompt, response=response,
            exact_hash=attempt["exact_response_sha256"], payload_hash=computed_payload_hash,
            submitted_hash=batch["submitted_payload_sha256"], decisions=decisions,
        )
        if batch["batch_hash"] != sha256_json(seed):
            raise FoundryError("STAGE1_BATCH_HASH_MISMATCH", "The decision batch hash does not match its immutable contents.")
        self._validate_contract({**seed, "state": batch["state"], "batch_hash": batch["batch_hash"]}, BATCH_SCHEMA, "BLUEPRINT_DECISION_BATCH_SCHEMA_INVALID")
        return decisions, response

    def _attempt_result(self, attempt_id: str) -> dict[str, Any]:
        with self.db.connection() as conn:
            row = conn.execute(
                """SELECT a.*,p.project_id,p.project_revision,p.prompt_sha256 FROM stage1_response_attempts a
                   JOIN stage1_prompt_exchanges p ON p.prompt_id=a.prompt_id WHERE a.attempt_id=?""", (attempt_id,),
            ).fetchone()
            if not row:
                raise FoundryError("STAGE1_RESPONSE_ATTEMPT_NOT_FOUND", "No Stage 1 response attempt has that ID.", status_code=404)
            batch = conn.execute("SELECT * FROM stage1_decision_batches WHERE attempt_id=?", (attempt_id,)).fetchone()
            decisions = self._load_decisions(conn, batch["batch_id"]) if batch else []
            approval = conn.execute("SELECT * FROM stage1_approvals WHERE attempt_id=?", (attempt_id,)).fetchone()
            commit = conn.execute("SELECT * FROM stage1_blueprint_commit_results WHERE attempt_id=?", (attempt_id,)).fetchone()
        result: dict[str, Any] = {
            "schema_version": EXCHANGE_SCHEMA, "attempt_id": row["attempt_id"], "prompt_id": row["prompt_id"],
            "project_id": row["project_id"], "project_revision": row["project_revision"], "prompt_sha256": row["prompt_sha256"],
            "exact_response_sha256": row["exact_response_sha256"], "parsing_status": row["parsing_status"],
            "validation": json.loads(row["validation_json"]), "decisions": decisions,
        }
        if row["response_id"]:
            result["response_id"] = row["response_id"]
        if row["response_payload_sha256"]:
            result["computed_payload_sha256"] = row["response_payload_sha256"]
        if batch:
            batch_data = dict(batch)
            for key in ("response_payload_json", "authored_notes_json", "validation_json"):
                if batch_data.get(key) is not None:
                    batch_data[key[:-5] if key.endswith("_json") else key] = json.loads(batch_data.pop(key))
            result["decision_batch"] = batch_data
            if batch["submitted_payload_sha256"]:
                result["submitted_payload_sha256"] = batch["submitted_payload_sha256"]
        if approval:
            result["approval"] = dict(approval)
        if commit:
            result["commit"] = dict(commit)
        self._validate_contract(result, EXCHANGE_SCHEMA, "STAGE1_EXCHANGE_SCHEMA_INVALID")
        return result

    def _quarantine_legacy_stage1_mechanics(self, project_id: str) -> list[str]:
        blocked: list[str] = []
        # This transaction commits the quarantine evidence before the caller raises.
        # It therefore survives the blocked approval transaction.
        with self.db.transaction() as conn:
            rows = conn.execute(
                """SELECT event_id,sequence_no,event_hash,event_json FROM events WHERE project_id=?
                   AND json_extract(event_json,'$.effective_point.character_cl')=0""", (project_id,),
            ).fetchall()
            for row in rows:
                event = json.loads(row["event_json"])
                label = (event.get("effective_point") or {}).get("label")
                if label in {"stage_1_blueprint", "stage_1_blueprint_metadata"} or event.get("planner_response_id") or (event.get("payload") or {}).get("stage_id") == STAGE_ID:
                    blocked.append(row["event_id"])
                    conn.execute(
                        "INSERT OR IGNORE INTO stage1_legacy_event_quarantine(event_id,project_id,sequence_no,event_hash,reason_code,detected_at) VALUES(?,?,?,?,?,?)",
                        (row["event_id"], project_id, row["sequence_no"], row["event_hash"], "LEGACY_STAGE1_CL0_ADVANCEMENT_EVENT", utcnow()),
                    )
        if blocked:
            raise FoundryError(
                "LEGACY_STAGE1_PROJECT_NON_UPGRADABLE_IN_PLACE",
                "Legacy Stage 1 CL0 mechanics are durably quarantined. This immutable chain cannot be reinterpreted in place; export the source evidence and recreate the project under the v2 blueprint-intent model.",
                details={"classification": "NON_UPGRADABLE_IN_PLACE_EXPORT_AND_RECREATE_REQUIRED", "event_ids": blocked},
            )
        return blocked

    def _revalidate_snapshots(self, conn, project_id: str, decisions: list[dict[str, Any]]) -> None:
        locks = {(row["pack_id"], row["version"], row["pack_hash"]) for row in conn.execute("SELECT pack_id,version,pack_hash FROM project_content_locks WHERE project_id=?", (project_id,))}
        for decision in decisions:
            for snapshot in decision["record_snapshots"]:
                lock = (snapshot["pack_id"], snapshot["pack_version"], snapshot["pack_hash"])
                if lock not in locks:
                    raise FoundryError("STAGE1_PACK_LOCK_CHANGED", "A selected blueprint record no longer belongs to the exact project content lock.", details=snapshot)
                row = conn.execute(
                    """SELECT data_json,record_hash,publication_state,selected_authority FROM catalog_records
                       WHERE record_id=? AND pack_id=? AND pack_version=? AND record_hash=? ORDER BY row_id LIMIT 1""",
                    (snapshot["record_id"], snapshot["pack_id"], snapshot["pack_version"], snapshot["record_hash"]),
                ).fetchone()
                if not row or not row["selected_authority"]:
                    raise FoundryError("STAGE1_RECORD_SNAPSHOT_CHANGED", "A selected record is absent, unpublished, or no longer the selected authority.", details=snapshot)
                current_record = json.loads(row["data_json"])
                publication_allowed = (
                    row["publication_state"] == "published"
                    or self._validated_intent_reference_allowed(decision["slot_id"], current_record)
                )
                if not publication_allowed:
                    raise FoundryError("STAGE1_RECORD_SNAPSHOT_CHANGED", "A selected record is absent, unpublished, or no longer the selected authority.", details=snapshot)
                current_choice = self._choice(current_record)
                if row["record_hash"] != snapshot["record_hash"] or sha256_json(current_choice) != snapshot["choice_snapshot_hash"]:
                    raise FoundryError("STAGE1_RECORD_SNAPSHOT_CHANGED", "A selected record no longer matches its exact prompt snapshot.", details={"record_id": snapshot["record_id"]})

    def _project_locks(self, conn, project_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in conn.execute("SELECT pack_id,version,pack_hash FROM project_content_locks WHERE project_id=? ORDER BY pack_id", (project_id,))]

    def _failure_point(self, _name: str) -> None:
        """Test seam for proving transactional rollback at internal boundaries."""

    def _after_atomic_commit(self, _attempt_id: str) -> None:
        """Test seam for simulating process death before projection resume."""

    def approve_and_commit(self, attempt_id: str, approved_by: str) -> dict[str, Any]:
        actor = approved_by.strip()
        if not actor:
            raise FoundryError("APPROVAL_ACTOR_REQUIRED", "An explicit human approval actor is required.")
        attempt = self._attempt_result(attempt_id)
        if not attempt["validation"].get("valid"):
            raise FoundryError("STAGE1_RESPONSE_NOT_VALID", "Only a valid Stage 1 response can be approved.")
        if attempt.get("commit"):
            if attempt["commit"]["projection_status"] != "projected":
                self.resume_projection(attempt_id)
            result = self._attempt_result(attempt_id)
            result["idempotent"] = True
            return result

        batch_id = attempt["decision_batch"]["batch_id"]
        prompt = self.get_prompt(attempt["prompt_id"])
        self._quarantine_legacy_stage1_mechanics(attempt["project_id"])
        with self.db.transaction() as conn:
            batch = conn.execute("SELECT * FROM stage1_decision_batches WHERE batch_id=?", (batch_id,)).fetchone()
            if not batch:
                raise FoundryError("STAGE1_DECISION_BATCH_NOT_FOUND", "No decision batch is bound to this response.")
            existing = conn.execute("SELECT commit_id FROM stage1_blueprint_commit_results WHERE batch_id=?", (batch_id,)).fetchone()
            if existing:
                pass
            else:
                if batch["state"] != "approval_pending":
                    raise FoundryError("STAGE1_BATCH_STATE_INVALID", "Only an approval-pending batch may enter the atomic commit.", details={"state": batch["state"]})
                project_row = conn.execute("SELECT * FROM projects WHERE project_id=?", (batch["project_id"],)).fetchone()
                if not project_row:
                    raise FoundryError("PROJECT_NOT_FOUND", "No character project has that ID.", status_code=404)
                if project_row["revision"] != batch["expected_project_revision"]:
                    raise FoundryError("STALE_PROJECT_REVISION", "The project changed after validation; generate a new prompt.", details={"expected": batch["expected_project_revision"], "actual": project_row["revision"]})
                project = json.loads(project_row["project_json"])
                if project["content_lock"]["catalog_build_id"] != batch["catalog_build_id"] or project["content_lock"]["lock_hash"] != batch["content_lock_hash"]:
                    raise FoundryError("CONTENT_LOCK_CHANGED", "The exact content lock changed before approval.")
                actual_locks = self._project_locks(conn, batch["project_id"])
                actual_lock_hash = sha256_json({
                    "catalog_build_id": project["content_lock"]["catalog_build_id"],
                    "packs": [{"pack_id": item["pack_id"], "version": item["version"], "content_hash": item["pack_hash"]} for item in actual_locks],
                })
                if actual_lock_hash != batch["content_lock_hash"]:
                    raise FoundryError("STAGE1_PACK_LOCK_CHANGED", "The persisted project pack lock no longer matches the exact prompt lock.", details={"expected": batch["content_lock_hash"], "actual": actual_lock_hash})
                decisions, _response = self._verify_persisted_batch(conn, batch, prompt)
                if len(decisions) != len(prompt["envelope"]["decision_slots"]):
                    raise FoundryError("STAGE1_BATCH_INCOMPLETE", "The persisted decision batch does not resolve every prompt slot.")
                self._revalidate_snapshots(conn, batch["project_id"], decisions)
                before_events = conn.execute("SELECT COUNT(*) FROM events WHERE project_id=?", (batch["project_id"],)).fetchone()[0]
                approval_id = "stage1.approval." + sha256_json({"batch_id": batch_id, "approved_by": actor})[:40]
                now = utcnow()
                conn.execute("INSERT INTO stage1_approvals(approval_id,attempt_id,approved_by,approved_at,project_revision_at_approval) VALUES(?,?,?,?,?)", (approval_id, attempt_id, actor, now, project_row["revision"]))
                conn.execute("UPDATE stage1_decision_batches SET state='approved',approved_by=?,approved_at=?,updated_at=? WHERE batch_id=?", (actor, now, now, batch_id))
                self._transition(conn, batch_id, "approval_pending", "approved", "human", actor)
                self._failure_point("after_approval_before_commit")

                intent_state = {
                    "schema_version": INTENT_STATE_SCHEMA, "project_id": batch["project_id"], "batch_id": batch_id,
                    "source_project_revision": project_row["revision"], "decisions": decisions,
                    "authored_notes": json.loads(batch["authored_notes_json"]), "planner_rationale": batch["planner_rationale"],
                    "mechanical_authority": False,
                }
                self._validate_contract(intent_state, INTENT_STATE_SCHEMA, "BLUEPRINT_INTENT_STATE_SCHEMA_INVALID")
                intent_hash = sha256_json(intent_state)
                head = conn.execute("SELECT * FROM stage1_blueprint_heads WHERE project_id=?", (batch["project_id"],)).fetchone()
                sequence = (head["sequence_no"] if head else 0) + 1
                previous_hash = head["commit_hash"] if head else ZERO_HASH
                new_revision = project_row["revision"] + 1
                commit_seed = {"project_id": batch["project_id"], "sequence_no": sequence, "batch_id": batch_id, "previous_commit_hash": previous_hash, "intent_state_hash": intent_hash, "project_revision_before": project_row["revision"], "project_revision_after": new_revision, "approved_by": actor}
                commit_hash = sha256_json(commit_seed)
                commit_id = "stage1.commit." + commit_hash[:40]
                conn.execute(
                    """INSERT INTO stage1_blueprint_commits(project_id,sequence_no,commit_id,batch_id,previous_commit_hash,commit_hash,intent_state_json,intent_state_hash,project_revision_before,project_revision_after,approved_by,committed_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (batch["project_id"], sequence, commit_id, batch_id, previous_hash, commit_hash, canonical_json(intent_state), intent_hash, project_row["revision"], new_revision, actor, now),
                )
                conn.execute(
                    """INSERT INTO stage1_blueprint_heads(project_id,sequence_no,commit_id,commit_hash,intent_state_hash,updated_at) VALUES(?,?,?,?,?,?)
                       ON CONFLICT(project_id) DO UPDATE SET sequence_no=excluded.sequence_no,commit_id=excluded.commit_id,commit_hash=excluded.commit_hash,intent_state_hash=excluded.intent_state_hash,updated_at=excluded.updated_at""",
                    (batch["project_id"], sequence, commit_id, commit_hash, intent_hash, now),
                )
                commits = list(project.get("stage_commits") or [])
                commits.append({"stage": 1, "revision": new_revision, "status": "sealed", "state_hash": intent_hash, "prompt_packet_ids": [batch["prompt_id"]], "response_ids": [batch["response_id"]], "event_ids": []})
                updated = canonical_project_document(
                    project_id=batch["project_id"], name=project["name"], revision=new_revision, status="stage_1",
                    created_at=project["created_at"], updated_at=now, catalog_build_id=project["content_lock"]["catalog_build_id"],
                    pack_locks=self._project_locks(conn, batch["project_id"]), user_locks=project["user_locks"], source_inputs=project["source_inputs"],
                    event_count=project["event_stream"]["count"], head_hash=project["event_stream"].get("head_hash"), active_stage=1,
                    stage_commits=commits, generated_artifacts=project["generated_artifacts"], candidates=project["candidates"], acceptance=project["acceptance"],
                )
                self._validate_contract(updated, "TianxiaFoundry.CharacterProject.v1", "CHARACTER_PROJECT_SCHEMA_INVALID")
                conn.execute(
                    "UPDATE projects SET status='stage_1',revision=?,updated_at=?,project_json=?,canonical_project_hash=?,canonical_schema_version=?,contract_status='valid' WHERE project_id=?",
                    (new_revision, now, canonical_json(updated), canonical_project_hash(updated), updated["schema_version"], batch["project_id"]),
                )
                if self.projects._builder_lifecycle_row(conn, batch["project_id"]) is not None:
                    self.projects._set_builder_lifecycle(
                        conn, batch["project_id"], "completed", source="stage1_blueprint_completed"
                    )
                after_events = conn.execute("SELECT COUNT(*) FROM events WHERE project_id=?", (batch["project_id"],)).fetchone()[0]
                if after_events != before_events:
                    raise FoundryError("STAGE1_ADVANCEMENT_EVENT_LEAK", "Stage 1 changed the advancement event count.")
                conn.execute("UPDATE stage1_decision_batches SET state='projection_pending',committed_at=?,updated_at=? WHERE batch_id=?", (now, now, batch_id))
                self._transition(conn, batch_id, "approved", "committed", "system", actor)
                self._transition(conn, batch_id, "committed", "projection_pending", "system", actor)
                conn.execute(
                    """INSERT INTO stage1_blueprint_commit_results(commit_id,batch_id,attempt_id,project_id,project_revision_before,project_revision_after,intent_state_hash,blueprint_commit_hash,advancement_event_count_before,advancement_event_count_after,projection_status,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (commit_id, batch_id, attempt_id, batch["project_id"], project_row["revision"], new_revision, intent_hash, commit_hash, before_events, after_events, "projection_pending", now, now),
                )
        self._after_atomic_commit(attempt_id)
        self.resume_projection(attempt_id)
        return self._attempt_result(attempt_id)

    def resume_projection(self, attempt_id: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            result = conn.execute("SELECT * FROM stage1_blueprint_commit_results WHERE attempt_id=?", (attempt_id,)).fetchone()
            if not result:
                raise FoundryError("STAGE1_COMMIT_NOT_FOUND", "The decision batch is not canonically committed.")
            if result["projection_status"] == "projected":
                return {"projection_id": result["projection_id"], "projection_hash": result["projection_hash"], "idempotent": True}
            commit = conn.execute("SELECT * FROM stage1_blueprint_commits WHERE commit_id=?", (result["commit_id"],)).fetchone()
            projection = {
                "schema_version": "TianxiaFoundry.BlueprintIntentProjection.v1", "projection_id": "",
                "project_id": result["project_id"], "commit_id": result["commit_id"], "batch_id": result["batch_id"],
                "intent_state_hash": commit["intent_state_hash"], "intent_state": json.loads(commit["intent_state_json"]),
                "mechanical_authority": False, "advancement_event_delta": 0,
            }
            projection_hash = sha256_json({k: v for k, v in projection.items() if k != "projection_id"})
            projection_id = "stage1.projection." + projection_hash[:40]
            projection["projection_id"] = projection_id
            existing = conn.execute("SELECT projection_hash,projection_json FROM stage1_blueprint_projections WHERE commit_id=?", (result["commit_id"],)).fetchone()
            if existing and (existing["projection_hash"] != projection_hash or existing["projection_json"] != canonical_json(projection)):
                raise FoundryError("STAGE1_PROJECTION_NONDETERMINISTIC", "The same commit produced different blueprint projection bytes.")
            if not existing:
                conn.execute("INSERT INTO stage1_blueprint_projections(projection_id,project_id,commit_id,projection_json,projection_hash,created_at) VALUES(?,?,?,?,?,?)", (projection_id, result["project_id"], result["commit_id"], canonical_json(projection), projection_hash, utcnow()))
            batch = conn.execute("SELECT state FROM stage1_decision_batches WHERE batch_id=?", (result["batch_id"],)).fetchone()
            conn.execute("UPDATE stage1_blueprint_commit_results SET projection_status='projected',projection_id=?,projection_hash=?,last_projection_error_json=NULL,updated_at=? WHERE commit_id=?", (projection_id, projection_hash, utcnow(), result["commit_id"]))
            conn.execute("UPDATE stage1_decision_batches SET state='projected',updated_at=? WHERE batch_id=?", (utcnow(), result["batch_id"]))
            if batch["state"] != "projected":
                self._transition(conn, result["batch_id"], batch["state"], "projected", "system")
            return {"projection_id": projection_id, "projection_hash": projection_hash, "idempotent": bool(existing)}

    def project_status(self, project_id: str) -> dict[str, Any]:
        self._project(project_id)
        with self.db.connection() as conn:
            prompts = [dict(x) for x in conn.execute("SELECT prompt_id,project_revision,prompt_sha256,created_at FROM stage1_prompt_exchanges WHERE project_id=? ORDER BY created_at", (project_id,))]
            attempts = [dict(x) for x in conn.execute("""SELECT a.attempt_id,a.prompt_id,a.response_id,a.exact_response_sha256,a.parsing_status,a.validation_json,a.created_at,b.batch_id,b.state
                                                         FROM stage1_response_attempts a JOIN stage1_prompt_exchanges p ON p.prompt_id=a.prompt_id
                                                         LEFT JOIN stage1_decision_batches b ON b.attempt_id=a.attempt_id WHERE p.project_id=? ORDER BY a.created_at""", (project_id,))]
            head = conn.execute("SELECT * FROM stage1_blueprint_heads WHERE project_id=?", (project_id,)).fetchone()
            advancement_count = conn.execute("SELECT COUNT(*) FROM events WHERE project_id=?", (project_id,)).fetchone()[0]
            network_calls = conn.execute(
                "SELECT COUNT(*) FROM ai_provider_runs WHERE project_id=?",
                (project_id,),
            ).fetchone()[0]
        for item in attempts:
            item["validation"] = json.loads(item.pop("validation_json"))
        current_revision = int(self._project(project_id)["revision"])
        current_prompts = [row for row in prompts if int(row["project_revision"]) == current_revision]
        state = "SEALED" if head else ("REQUEST_PREPARED" if current_prompts else "ELIGIBLE_TO_PREPARE")
        return {
            "project_id": project_id, "project_revision": current_revision, "stage_id": STAGE_ID,
            "state": state, "stage1_sealed": bool(head), "request_prepared": bool(current_prompts),
            "current_prompt_id": current_prompts[-1]["prompt_id"] if current_prompts else None,
            "prompts": prompts, "attempts": attempts, "blueprint_head": dict(head) if head else None,
            "advancement_event_count": advancement_count, "network_calls": network_calls,
        }
