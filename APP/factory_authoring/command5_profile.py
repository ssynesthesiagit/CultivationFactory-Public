from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from app.core import Database, FoundryError, canonical_json, sha256_file, sha256_json
from app.runtime import helper_python_executable
from non_sphere_authority.foundation_mechanics import has_acquired_foundation
from non_sphere_authority.method_mechanics import has_acquired_method
from character_sheet.service import CharacterSheetService
from factory_authoring.service import FactoryAuthoringWorkspaceService
from projector.service import ProjectionService
from project_store.service import ProjectStore

BUILD_PROFILE_CONTRACT = "Tianxia_C2B3_Factory_Build_Profiles_R1.json"
GM_MODEL_PROFILE_SCHEMA = "Tianxia_C2B3_GM_Character_Model_Profile_R1.schema.json"
LEGACY_PROFILE = "LEGACY_FULL_EXECUTION"
CHARACTER_GM_PROFILE = "CHARACTER_GM_MODEL"
CHARACTER_GM_COMMAND4_PASS = "CHARACTER_GM_COMMAND_4_PROFILE_PASS"
_SERVER_COMPOSITE_GUIDANCE_SCHEMA = "TianxiaFoundry.ServerDerivedCompositeGuidance.v1"
GM_CANDIDATE_READY = "GM_MODEL_CANDIDATE_READY"

_REVIEWED_OVERLAY_SCHEMA = "TianxiaFoundry.Command4ProviderOverlayManifest.v1"
_REVIEWED_OVERLAY_SCOPE = "Command 4 action-authoring execution surface only; no global combat readiness claim."
_REVIEWED_OVERLAY_AUDIT_SCHEMA = "TianxiaFoundry.Command4ProviderAudit.v1"
_REVIEWED_OVERLAY_VALIDATION_SCHEMA = "TianxiaFoundry.Command4ProviderAuthoringEvidence.v1"
_REVIEWED_OVERLAY_SURFACE_SCHEMA = "TianxiaFoundry.Command4ProviderCompleteActionSurface.v1"
_REVIEWED_OVERLAY_PROVIDER_IDS = frozenset({"local", "lemonade", "agent"})
_REVIEWED_DETERMINISTIC_PROVENANCE = {
    "provider_id": "server_deterministic",
    "purpose": "factory_command4_action_authoring",
    "finish_reason": "stop",
    "resolution_mode": "deterministic_closed_world",
    "provider_calls": 0,
    "model": None,
    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
}
_REVIEWED_DETERMINISTIC_ONLY_KEYS = frozenset({
    "finish_reason",
    "resolution_mode",
    "provider_calls",
    "model",
    "usage",
})
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_R1F_SEMANTIC_SCHEMA = "HF05ZVK-R1F.SemanticValidationReport.v1"
_R1F_SIGNATURE_SCHEMA = "HF05ZVK-R1F.SignatureLoadout.v1"
_R2K_EXPECTED_COUNT_KEYS = (
    "level_rows",
    "spheres",
    "talents",
    "actions",
    "training_sources",
    "forged_techniques",
    "preserved_forged_expressions",
    "emergency_technique_seeds",
    "recorded_arts",
    "immortal_arts",
    "equipment",
    "states",
)

# This ordered tuple is the single server-side declaration of the standalone
# sidecars consumed by the bundled R2K renderer.  Keep names and order aligned
# with its SIDECARE_NAMES list; the projection code below derives the values,
# but never invents a second sidecar contract.
R2K_REQUIRED_SIDECAR_NAMES = (
    "Character_Master_Ledger.json",
    "Tianxia_GM_Character_Model_v1.json",
    "Tianxia_GM_Character_View_Model_v2.json",
    "Equipment_Ledger.json",
    "Equipment_Ledger_Legacy.json",
    "Selected_Item_GM_Projection.json",
    "Item_Execution_Coverage.json",
    "Selected_Rule_Execution_Coverage.json",
    "Feature_Coverage_Manifest.json",
    "Path_Feature_Coverage.json",
    "Subpath_Feature_Coverage.json",
    "Insight_Execution_Coverage.json",
    "Companion_Execution_Coverage.json",
    "Source_CL_and_Realm_Suppression.json",
    "Modifier_Ledger.json",
    "Procedure_Ledger.json",
    "Passive_Statistic_Ledger.json",
    "Permission_Record_Ledger.json",
    "Complete_Action_Surface.json",
    "State_Effect_Registry.json",
    "Leveling_Ledger.json",
    "Rules_Selection_Packets.json",
    "GM_Screen_Display_Rows.json",
    "GM_Screen_Projection_Rows.json",
    "Semantic_Validation_Report.json",
    "Signature_Loadout.json",
)

# The bundled HF05Z GM Screen is a fixed consumer contract.  Keep the
# machine-facing IDs here (rather than deriving them from display labels) so
# a source projection cannot silently collapse the separate Insights and
# Dao/I-Ching surfaces.
GM_SCREEN_TAB_CONTRACT = (
    ("overview-core-stats", "Overview / Core Stats"),
    ("leveling-ledger", "Leveling Ledger"),
    ("background-origin", "Background and Origin"),
    ("paths-subpaths", "Paths and Subpaths"),
    ("spheres-talents", "Spheres and Talents"),
    ("insights", "Insights"),
    ("actions", "Actions and Reactions"),
    ("forged-techniques", "Forged Techniques"),
    ("martial-manuals-recorded-arts", "Martial Manuals / Recorded Arts"),
    ("immortal-arts", "Immortal Arts"),
    ("foundation", "Foundation"),
    ("method", "Method"),
    ("companions-spirits", "Companions and Spirits"),
    ("equipment", "Equipment"),
    ("resources-states-suppression", "Resources, States, and Suppression"),
    ("dao-i-ching", "Dao / I-Ching"),
    ("diagnostics", "Diagnostics"),
)


def _advanced_surface(snapshot: dict[str, Any], surface: str) -> tuple[list[Any], dict[str, Any]]:
    """Read one source-backed advanced-art container without inventing rows."""

    aliases = {
        "recorded_arts": ("recorded_arts", "martial_manuals", "manuals"),
        "forged_techniques": ("forged_techniques", "forged"),
        "immortal_arts": ("immortal_arts", "immortal"),
    }[surface]
    containers: list[dict[str, Any]] = [snapshot]
    for key in ("advanced_systems", "advanced_arts", "source_containers", "source_records"):
        value = snapshot.get(key)
        if isinstance(value, dict):
            containers.append(value)
    none_state: dict[str, Any] | None = None
    for container in containers:
        for alias in aliases:
            if alias not in container:
                continue
            raw = container.get(alias)
            if isinstance(raw, list):
                if raw:
                    return deepcopy(raw), {}
                continue
            if not isinstance(raw, dict):
                continue
            for entry_key in ("entries", "records", "items", "arts", "manuals", "techniques"):
                entries = raw.get(entry_key)
                if isinstance(entries, list):
                    if entries:
                        return deepcopy(entries), {}
                    if isinstance(raw.get("state"), str):
                        none_state = deepcopy(raw)
                    break
            if isinstance(raw.get("state"), str):
                none_state = deepcopy(raw)
    explicit = snapshot.get("explicit_none_systems")
    if isinstance(explicit, dict):
        explicit_key = "manuals" if surface == "recorded_arts" else surface
        value = explicit.get(explicit_key)
        if isinstance(value, dict):
            none_state = deepcopy(value)
    if none_state is None:
        none_state = {
            "state": "not_projected" if surface == "immortal_arts" else "none",
            "source_backed": False if surface == "immortal_arts" else True,
        }
    return [], none_state


def _snapshot_current_cl(snapshot: dict[str, Any]) -> int:
    """Return the attained CL without treating a target/readiness CL as attained."""

    candidates: list[int] = []

    def add(value: Any) -> None:
        if type(value) is int and value >= 0:
            candidates.append(value)

    def explicitly_attained(row: dict[str, Any]) -> bool:
        """Accept only unambiguous completion markers on history rows."""
        if any(row.get(key) is True for key in ("attained", "is_attained", "completed", "is_completed")):
            return True
        return row.get("status") in {"attained", "completed", "complete"} or row.get("state") in {
            "attained",
            "completed",
            "complete",
        }

    for container in (
        snapshot,
        snapshot.get("identity"),
        snapshot.get("advancement_history"),
        snapshot.get("cultivation"),
    ):
        if not isinstance(container, dict):
            continue
        for key in ("current_cl", "cultivation_level", "attained_cl", "attained_cultivation_level"):
            add(container.get(key))
        for key in ("levels", "milestones", "attainment"):
            rows = container.get(key)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if not explicitly_attained(row):
                    continue
                for key in ("current_cl", "cultivation_level", "attained_cl", "effective_cl", "cl", "level"):
                    add(row.get(key))
    return max(candidates, default=0)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value), encoding="utf-8", newline="\n")


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise FoundryError("PINNED_FACTORY_MODULE_UNAVAILABLE", f"Unable to load pinned Factory module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class CharacterGMCommand5Profile:
    @staticmethod
    def _canonicalize_candidate_zip(candidate: Path) -> None:
        """Remove host filesystem timestamps from the pinned sealer's ZIP."""
        canonical = candidate.with_suffix(".canonical.zip")
        with zipfile.ZipFile(candidate, "r") as source, zipfile.ZipFile(
            canonical, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as destination:
            for original in sorted(source.infolist(), key=lambda item: item.filename):
                info = zipfile.ZipInfo(original.filename, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = original.external_attr
                info.flag_bits = original.flag_bits & 0x800
                destination.writestr(info, source.read(original.filename))
        canonical.replace(candidate)

    """Character/GM branch of the existing Command 5 lifecycle.

    Legacy omission remains routed by ProjectionVerifier through the historical
    pinned Command 5 path. This class only assembles and audits the explicit
    CHARACTER_GM_MODEL profile; it never performs Command 6 or GM export.
    """

    def __init__(self, db: Database, *, factory_root: Path):
        self.db = db
        self.factory_root = factory_root.resolve()
        self.projects = ProjectStore(db)
        self.projections = ProjectionService(db, factory_root=self.factory_root)
        self.sheets = CharacterSheetService(db)
        self.workspaces = FactoryAuthoringWorkspaceService(db)

    @property
    def _contracts_dir(self) -> Path:
        return Path(__file__).resolve().parent / "contracts"

    def build_profiles(self) -> tuple[dict[str, Any], str]:
        return self.workspaces._verify_sealed_json(
            self._contracts_dir / BUILD_PROFILE_CONTRACT,
            expected_schema="TianxiaFoundry.FactoryBuildProfiles.v1",
            error_prefix="FACTORY_BUILD_PROFILE",
        )

    def select_profile(self, profile_id: str | None) -> tuple[dict[str, Any], str]:
        contract, contract_sha = self.build_profiles()
        selected = profile_id or contract.get("default_profile_id")
        profile = (contract.get("profiles") or {}).get(selected)
        if not isinstance(profile, dict):
            raise FoundryError(
                "FACTORY_BUILD_PROFILE_UNKNOWN",
                "The requested Factory build profile is not supported.",
                details={"requested": selected, "supported": sorted((contract.get("profiles") or {}).keys())},
            )
        return deepcopy(profile), contract_sha

    def _model_schema(self) -> tuple[dict[str, Any], str]:
        path = self._contracts_dir / GM_MODEL_PROFILE_SCHEMA
        sidecar = path.with_suffix(path.suffix + ".sha256")
        if not path.is_file() or not sidecar.is_file():
            raise FoundryError("GM_MODEL_PROFILE_SCHEMA_MISSING", "The Character/GM model profile schema is missing.")
        digest, declared = sidecar.read_text(encoding="utf-8").strip().split(None, 1)
        actual = sha256_file(path)
        if digest.lower() != actual or declared.strip().lstrip("*") != path.name:
            raise FoundryError("GM_MODEL_PROFILE_SCHEMA_STALE", "The Character/GM model profile schema checksum is stale.")
        return json.loads(path.read_text(encoding="utf-8")), actual

    @staticmethod
    def _is_sha256(value: Any) -> bool:
        return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None

    @staticmethod
    def _tree_hashes(root: Path, *, include_checksum_ledger: bool = False) -> dict[str, str]:
        """Return the canonical file hash map used by sealed workspaces.

        Overlay validation deliberately keeps this local to the Command 5
        profile.  It avoids trusting the provider-authoring module's internal
        helpers and lets the profile verify the base workspace again at the
        exact handoff where the reviewed surface is consumed.
        """

        return {
            path.relative_to(root).as_posix(): sha256_file(path)
            for path in sorted(root.rglob("*"))
            if path.is_file()
            and (include_checksum_ledger or path.name != "SHA256SUMS.txt")
        }

    @staticmethod
    def _snapshot_stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
        """Return the mutation-relevant part of a descriptor's stat result."""

        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_nlink,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    @classmethod
    def _snapshot_tree_no_follow(
        cls,
        source_root: Path,
        destination_root: Path,
        *,
        code_prefix: str,
    ) -> Path:
        """Copy a workspace using directory descriptors and no-follow opens.

        Path-based ``copytree`` has a check/use gap: an entry can be replaced
        by a symlink after the preflight walk and before the copy opens it.
        This helper anchors every child operation to its already-open parent
        descriptor, rejects links/special files at the descriptor boundary,
        and compares each source descriptor before and after reading it.  The
        destination is created by the caller in a private staging directory;
        a failed copy is removed here so no partial snapshot can be consumed.
        """

        if not isinstance(source_root, Path) or not isinstance(destination_root, Path):
            raise FoundryError(f"{code_prefix}_INVALID", "Snapshot roots must be Path values.")
        source_path = Path(os.path.abspath(os.fspath(source_root)))
        destination_path = Path(os.path.abspath(os.fspath(destination_root)))
        nofollow = getattr(os, "O_NOFOLLOW", None)
        directory_flag = getattr(os, "O_DIRECTORY", 0)
        if nofollow is None or not directory_flag:
            raise FoundryError(f"{code_prefix}_INVALID", "The platform cannot provide no-follow directory snapshots.")
        common_flags = os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_BINARY", 0)
        directory_flags = common_flags | directory_flag
        file_flags = common_flags
        destination_file_flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | nofollow
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_BINARY", 0)
        )

        def fail(kind: str, message: str, *, path: str | None = None) -> None:
            details = {"path": path} if path is not None else None
            raise FoundryError(f"{code_prefix}_{kind}", message, details=details)

        def same(before: os.stat_result, after: os.stat_result) -> bool:
            return cls._snapshot_stat_identity(before) == cls._snapshot_stat_identity(after)

        def same_destination_object(before: os.stat_result, after: os.stat_result) -> bool:
            """Compare destination identity without treating writes as replacement."""

            return (
                before.st_dev,
                before.st_ino,
                stat.S_IFMT(before.st_mode),
            ) == (
                after.st_dev,
                after.st_ino,
                stat.S_IFMT(after.st_mode),
            )

        def entry_name(value: str) -> str:
            if (
                not isinstance(value, str)
                or not value
                or value in {".", ".."}
                or "/" in value
                or "\\" in value
                or "\x00" in value
            ):
                fail("INVALID", "The snapshot contains an unsafe directory entry.", path=value if isinstance(value, str) else None)
            return value

        def copy_file(
            source_parent_fd: int,
            destination_parent_fd: int,
            name: str,
            relative: str,
            expected: os.stat_result,
        ) -> None:
            try:
                source_fd = os.open(name, file_flags, dir_fd=source_parent_fd)
            except OSError:
                fail("SOURCE_CHANGED", "A snapshot file could not be opened without following links.", path=relative)
            try:
                opened = os.fstat(source_fd)
                if not same(expected, opened) or not stat.S_ISREG(opened.st_mode):
                    fail("SOURCE_CHANGED", "A snapshot file changed before it was read.", path=relative)
                try:
                    destination_fd = os.open(
                        name,
                        destination_file_flags,
                        stat.S_IMODE(opened.st_mode),
                        dir_fd=destination_parent_fd,
                    )
                except OSError:
                    fail("DESTINATION_CHANGED", "A snapshot destination file could not be opened without following links.", path=relative)
                try:
                    destination_opened = os.fstat(destination_fd)
                    if not stat.S_ISREG(destination_opened.st_mode):
                        fail("DESTINATION_CHANGED", "A snapshot destination file is not regular.", path=relative)
                    while True:
                        chunk = os.read(source_fd, 1024 * 1024)
                        if not chunk:
                            break
                        view = memoryview(chunk)
                        while view:
                            written = os.write(destination_fd, view)
                            if written <= 0:
                                fail("INVALID", "The snapshot destination could not be written.", path=relative)
                            view = view[written:]
                    after = os.fstat(source_fd)
                    if not same(opened, after):
                        fail("SOURCE_CHANGED", "A snapshot file changed while it was read.", path=relative)
                    os.fchmod(destination_fd, stat.S_IMODE(opened.st_mode))
                finally:
                    os.close(destination_fd)
                try:
                    destination_after = os.lstat(name, dir_fd=destination_parent_fd)
                except OSError:
                    fail("DESTINATION_CHANGED", "A snapshot destination file was replaced while it was copied.", path=relative)
                if not same_destination_object(destination_opened, destination_after):
                    fail("DESTINATION_CHANGED", "A snapshot destination file was replaced while it was copied.", path=relative)
            except FoundryError:
                raise
            except OSError:
                fail("SOURCE_CHANGED", "A snapshot file could not be read safely.", path=relative)
            finally:
                os.close(source_fd)

        def copy_directory(source_fd: int, destination_fd: int, relative_parent: str) -> None:
            before_directory = os.fstat(source_fd)
            try:
                names = sorted(os.listdir(source_fd))
            except OSError:
                fail("SOURCE_CHANGED", "A snapshot directory could not be enumerated.", path=relative_parent or ".")
            for raw_name in names:
                name = entry_name(raw_name)
                relative = f"{relative_parent}/{name}" if relative_parent else name
                try:
                    expected = os.lstat(name, dir_fd=source_fd)
                except OSError:
                    fail("SOURCE_CHANGED", "A snapshot entry changed during enumeration.", path=relative)
                mode = expected.st_mode
                if stat.S_ISLNK(mode):
                    fail("SYMLINK", "Symbolic links are not allowed in a detached snapshot.", path=relative)
                if not stat.S_ISREG(mode) and not stat.S_ISDIR(mode):
                    fail("SPECIAL_FILE", "Special files are not allowed in a detached snapshot.", path=relative)
                if stat.S_ISDIR(mode):
                    try:
                        child_fd = os.open(name, directory_flags, dir_fd=source_fd)
                    except OSError:
                        fail("SOURCE_CHANGED", "A snapshot directory changed before it was opened.", path=relative)
                    try:
                        opened = os.fstat(child_fd)
                        if not same(expected, opened) or not stat.S_ISDIR(opened.st_mode):
                            fail("SOURCE_CHANGED", "A snapshot directory changed before it was read.", path=relative)
                        try:
                            os.mkdir(name, stat.S_IMODE(opened.st_mode), dir_fd=destination_fd)
                        except OSError:
                            fail("DESTINATION_CHANGED", "A snapshot destination directory could not be created safely.", path=relative)
                        try:
                            destination_child_fd = os.open(name, directory_flags, dir_fd=destination_fd)
                        except OSError:
                            fail("DESTINATION_CHANGED", "A snapshot destination directory could not be opened without following links.", path=relative)
                        try:
                            destination_opened = os.fstat(destination_child_fd)
                            if not stat.S_ISDIR(destination_opened.st_mode):
                                fail("DESTINATION_CHANGED", "A snapshot destination entry is not a directory.", path=relative)
                            copy_directory(child_fd, destination_child_fd, relative)
                        finally:
                            os.close(destination_child_fd)
                        try:
                            destination_after = os.lstat(name, dir_fd=destination_fd)
                        except OSError:
                            fail("DESTINATION_CHANGED", "A snapshot destination directory was replaced while it was copied.", path=relative)
                        if not same_destination_object(destination_opened, destination_after):
                            fail("DESTINATION_CHANGED", "A snapshot destination directory was replaced while it was copied.", path=relative)
                        after = os.fstat(child_fd)
                        if not same(opened, after):
                            fail("SOURCE_CHANGED", "A snapshot directory changed while it was read.", path=relative)
                    finally:
                        os.close(child_fd)
                else:
                    copy_file(source_fd, destination_fd, name, relative, expected)
            after_directory = os.fstat(source_fd)
            if not same(before_directory, after_directory):
                fail("SOURCE_CHANGED", "A snapshot directory changed while it was read.", path=relative_parent or ".")

        destination_created = False
        try:
            try:
                root_lstat = os.lstat(source_path)
            except OSError:
                fail("MISSING", "The snapshot source directory is missing.")
            if stat.S_ISLNK(root_lstat.st_mode):
                fail("SYMLINK", "The snapshot source root must not be a symbolic link.")
            if not stat.S_ISDIR(root_lstat.st_mode):
                fail("INVALID", "The snapshot source root is not a directory.")
            source_fd = os.open(source_path, directory_flags)
            try:
                opened_root = os.fstat(source_fd)
                if not same(root_lstat, opened_root) or not stat.S_ISDIR(opened_root.st_mode):
                    fail("SOURCE_CHANGED", "The snapshot source root changed before it was opened.")
                try:
                    destination_parent_fd = os.open(destination_path.parent, directory_flags)
                except OSError:
                    fail("DESTINATION_INVALID", "The snapshot destination parent is not a safe directory.")
                try:
                    try:
                        os.mkdir(destination_path.name, 0o700, dir_fd=destination_parent_fd)
                    except FileExistsError:
                        fail("DESTINATION_INVALID", "The snapshot destination already exists.", path=destination_path.name)
                    except OSError:
                        fail("DESTINATION_INVALID", "The snapshot destination directory could not be created.", path=destination_path.name)
                    destination_created = True
                    try:
                        destination_fd = os.open(destination_path.name, directory_flags, dir_fd=destination_parent_fd)
                    except OSError:
                        fail("DESTINATION_CHANGED", "The snapshot destination root could not be opened without following links.")
                    try:
                        destination_root_opened = os.fstat(destination_fd)
                        if not stat.S_ISDIR(destination_root_opened.st_mode):
                            fail("DESTINATION_CHANGED", "The snapshot destination root is not a directory.")
                        copy_directory(source_fd, destination_fd, "")
                    finally:
                        os.close(destination_fd)
                    try:
                        destination_root_after = os.lstat(destination_path.name, dir_fd=destination_parent_fd)
                    except OSError:
                        fail("DESTINATION_CHANGED", "The snapshot destination root was replaced while it was copied.")
                    if not same_destination_object(destination_root_opened, destination_root_after):
                        fail("DESTINATION_CHANGED", "The snapshot destination root was replaced while it was copied.")
                finally:
                    os.close(destination_parent_fd)
                after_root = os.fstat(source_fd)
                if not same(opened_root, after_root):
                    fail("SOURCE_CHANGED", "The snapshot source root changed while it was read.")
            finally:
                os.close(source_fd)
        except BaseException:
            if destination_created:
                shutil.rmtree(destination_path, ignore_errors=True)
            raise
        return destination_path

    @classmethod
    def _verify_checksum_ledger(cls, root: Path, *, code_prefix: str) -> None:
        ledger_path = root / "SHA256SUMS.txt"
        if not ledger_path.is_file():
            raise FoundryError(f"{code_prefix}_MISSING", "The sealed checksum ledger is missing.")
        if any(path.is_symlink() for path in root.rglob("*")):
            raise FoundryError(f"{code_prefix}_INVALID", "The sealed workspace contains a symbolic link.")
        declared: dict[str, str] = {}
        try:
            lines = ledger_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise FoundryError(f"{code_prefix}_INVALID", "The sealed checksum ledger cannot be read.") from exc
        for line in lines:
            if not line.strip():
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                raise FoundryError(f"{code_prefix}_INVALID", "The sealed checksum ledger is malformed.")
            digest, relative = parts
            relative = relative.lstrip("*").strip()
            relative_path = Path(relative)
            if (
                not cls._is_sha256(digest)
                or not relative
                or relative in declared
                or relative_path.is_absolute()
                or ".." in relative_path.parts
                or relative_path.as_posix() != relative
            ):
                raise FoundryError(f"{code_prefix}_INVALID", "The sealed checksum ledger contains an unsafe entry.")
            declared[relative] = digest
        actual = cls._tree_hashes(root)
        if declared != actual:
            raise FoundryError(
                f"{code_prefix}_STALE",
                "The sealed checksum ledger does not match its files.",
                details={
                    "missing": sorted(set(actual) - set(declared)),
                    "extra": sorted(set(declared) - set(actual)),
                },
            )

    @classmethod
    def _verify_reviewed_surface(
        cls,
        surface: Any,
        *,
        project_id: str,
        source_workspace_sha256: str,
        request_sha256: str,
        response_sha256: str,
        deterministic: bool = False,
    ) -> dict[str, Any]:
        """Validate a provider or deterministic surface before Command 5 consumes it."""

        if not isinstance(surface, Mapping):
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID", "The reviewed Command 4 surface is not an object.")
        required = {
            "schema_version",
            "status",
            "candidate_status",
            "mechanical_authority",
            "execution_authority",
            "global_combat_readiness",
            "workspace_authority",
            "project_id",
            "source_workspace_sha256",
            "request_sha256",
            "response_sha256",
            "source_text_sha256_by_record_id",
            "actions",
            "procedures",
            "ledger_order",
            "signature_loadout_record_ids",
            "unresolved",
            "provenance",
        }
        if not required.issubset(surface):
            raise FoundryError(
                "CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID",
                "The reviewed Command 4 surface is missing required authority fields.",
                details={"missing": sorted(required - set(surface))},
            )
        if (
            surface.get("schema_version") != _REVIEWED_OVERLAY_SURFACE_SCHEMA
            or surface.get("status") != "COMMAND4_ACTION_AUTHORITY_READY"
            or surface.get("candidate_status") != "CANDIDATE_NON_AUTHORITATIVE"
            or surface.get("mechanical_authority") is not True
            or surface.get("execution_authority") is not True
            or surface.get("global_combat_readiness") is not False
            or surface.get("workspace_authority") != "C2B2_INPUT_ONLY"
            or surface.get("project_id") != project_id
            or surface.get("source_workspace_sha256") != source_workspace_sha256
            or surface.get("request_sha256") != request_sha256
            or surface.get("response_sha256") != response_sha256
            or surface.get("unresolved") != []
        ):
            raise FoundryError(
                "CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID",
                "The reviewed Command 4 surface makes an invalid authority or provenance claim.",
            )
        if not all(cls._is_sha256(value) for value in (source_workspace_sha256, request_sha256, response_sha256)):
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID", "The reviewed surface hash bindings are malformed.")

        actions = surface.get("actions")
        procedures = surface.get("procedures")
        ledger = surface.get("ledger_order")
        source_hashes = surface.get("source_text_sha256_by_record_id")
        provenance = surface.get("provenance")
        loadout = surface.get("signature_loadout_record_ids")
        if not all(isinstance(value, list) for value in (actions, procedures, ledger, loadout)) or not isinstance(source_hashes, Mapping) or not isinstance(provenance, Mapping):
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID", "The reviewed surface ledger fields have invalid types.")
        if (
            provenance.get("workspace_sha256") != source_workspace_sha256
            or provenance.get("request_sha256") != request_sha256
            or provenance.get("response_sha256") != response_sha256
            or provenance.get("source_text_sha256_by_record_id") != dict(source_hashes)
        ):
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID", "The reviewed surface provenance is not bound to its root hashes.")

        rows = [*(('action', row) for row in actions), *(('procedure', row) for row in procedures)]
        record_ids: list[str] = []
        action_ids: list[str] = []
        row_by_record_id: dict[str, Mapping[str, Any]] = {}
        for expected_kind, row in rows:
            if not isinstance(row, Mapping):
                raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID", "A reviewed surface record is not an object.")
            record_id = row.get("record_id")
            action_id = row.get("action_id")
            runtime_kind = row.get("runtime_kind")
            if not isinstance(record_id, str) or not record_id.strip() or record_id in row_by_record_id:
                raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID", "Reviewed surface record IDs must be unique nonblank strings.")
            if not isinstance(action_id, str) or not action_id.strip() or action_id in action_ids:
                raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID", "Reviewed surface action IDs must be unique nonblank strings.")
            if runtime_kind != expected_kind or not isinstance(row.get("authoring_field_packets"), Mapping):
                raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID", "Reviewed surface records have inconsistent runtime kinds or packets.")
            row_by_record_id[record_id] = row
            record_ids.append(record_id)
            action_ids.append(action_id)
            if row.get("source_text_sha256") != source_hashes.get(record_id) or not cls._is_sha256(row.get("source_text_sha256")):
                raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID", "Reviewed surface source hashes are inconsistent.")

        if set(source_hashes) != set(record_ids) or len(source_hashes) != len(record_ids):
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID", "Reviewed surface source hash coverage is inconsistent.")
        if len(loadout) != len(set(loadout)) or any(value not in {row.get("record_id") for row in actions} for value in loadout):
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID", "Reviewed surface signature loadout is invalid.")
        if len(ledger) != len(rows):
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID", "Reviewed surface ledger coverage is inconsistent.")
        seen_ordinals: list[int] = []
        seen_records: set[str] = set()
        for entry in ledger:
            if not isinstance(entry, Mapping):
                raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID", "A reviewed surface ledger entry is not an object.")
            ordinal = entry.get("ledger_ordinal")
            record_id = entry.get("record_id")
            row = row_by_record_id.get(record_id)
            if (
                type(ordinal) is not int
                or ordinal <= 0
                or record_id in seen_records
                or row is None
                or entry.get("runtime_kind") != row.get("runtime_kind")
                or entry.get("action_id") != row.get("action_id")
            ):
                raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID", "Reviewed surface ledger order is inconsistent.")
            seen_ordinals.append(ordinal)
            seen_records.add(record_id)
        if seen_ordinals != list(range(1, len(rows) + 1)) or seen_records != set(record_ids):
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID", "Reviewed surface ledger ordinals are not contiguous.")
        return {
            "record_count": len(rows),
            "action_count": len(actions),
            "procedure_count": len(procedures),
            "source_record_count": len(source_hashes),
        }

    def _command4_source_root(self) -> Path | None:
        """Return the server-owned extracted-source root for detached prepares."""

        workspace_service = getattr(self, "workspaces", None)
        database = getattr(workspace_service, "db", None)
        settings = getattr(database, "settings", None)
        data_dir = getattr(settings, "data_dir", None)
        if not isinstance(data_dir, (str, Path)) or not str(data_dir).strip():
            return None
        root = Path(os.path.abspath(os.fspath(data_dir))) / "vendor" / "extracted"
        try:
            if root.is_symlink() or not root.is_dir():
                return None
        except OSError:
            return None
        return root

    @classmethod
    def _verify_source_bound_command4_contract(
        cls,
        project_id: str,
        *,
        base_workspace: Path,
        source_workspace_sha256: str,
        request_sha256: str,
        surface: Mapping[str, Any],
        source_root: Path | None = None,
        deterministic: bool = False,
        allow_legacy_request: bool = False,
        authority_db: Any = None,
    ) -> None:
        """Re-derive Command 4 authority from the sealed base workspace.

        The overlay is a reviewed receipt, not an authority root.  Its surface
        is accepted only when the current deterministic Command 4 preparer
        produces the same request/source identity, candidate ledger, source
        hashes, server-derived fields, and one of the freshly derived field
        option packets for every authorable slot.
        """

        # Keep this import local: Command 4 and the Character/GM profile are
        # sibling lifecycle layers and must not introduce an import cycle.
        from factory_authoring.command4_provider import (
            COMMAND4_EXECUTION_FIELDS,
            Command4ProviderAuthoring,
            _candidate_action_type,
            _candidate_runtime_kind,
            _candidate_value,
            _provider_authorable_fields,
            _provider_field_domain,
        )

        try:
            prepared = Command4ProviderAuthoring(
                workspace_root=base_workspace,
                # A descriptor-detached workspace no longer has the original
                # data-root ancestry used to locate the sealed extracted
                # source.  The caller supplies this only from the server-owned
                # workspace settings; it is never taken from the overlay path.
                source_root=source_root,
                authority_db=authority_db,
            ).prepare(project_id)
        except FoundryError as exc:
            raise FoundryError(
                "CHARACTER_GM_REVIEWED_OVERLAY_SOURCE_INVALID",
                "The sealed base cannot reproduce the deterministic Command 4 authority contract.",
                details={"cause": exc.code},
            ) from None

        current_request_sha256 = prepared.get("request_sha256") if isinstance(prepared, Mapping) else None
        legacy_request_sha256 = prepared.get("legacy_provider_request_sha256") if isinstance(prepared, Mapping) else None
        request_matches_current = request_sha256 == current_request_sha256
        request_matches_legacy = allow_legacy_request and request_sha256 == legacy_request_sha256
        if (
            not isinstance(prepared, Mapping)
            or prepared.get("source_workspace_sha256") != source_workspace_sha256
            or not (request_matches_current or request_matches_legacy)
        ):
            raise FoundryError(
                "CHARACTER_GM_REVIEWED_OVERLAY_SOURCE_MISMATCH",
                "The reviewed overlay request/source identity does not match a fresh sealed Command 4 preparation.",
                details={
                    "prepared_source_workspace_sha256": prepared.get("source_workspace_sha256") if isinstance(prepared, Mapping) else None,
                    "prepared_request_sha256": current_request_sha256,
                },
            )

        candidates = prepared.get("candidates")
        candidate_ids = prepared.get("candidate_ids")
        source_hashes = prepared.get("source_text_sha256_by_record_id")
        provider_fields_by_id = prepared.get("provider_authorable_fields_by_record_id")
        domains_by_id = prepared.get("provider_field_domains_by_record_id")
        bindings_by_id = prepared.get("provider_field_domain_bindings_by_record_id")
        if (
            not isinstance(candidates, list)
            or not isinstance(candidate_ids, list)
            or candidate_ids != [row.get("record_id") for row in candidates if isinstance(row, Mapping)]
            or len(candidate_ids) != len(candidates)
            or len(candidate_ids) != len(set(candidate_ids))
            or not isinstance(source_hashes, Mapping)
            or not isinstance(provider_fields_by_id, Mapping)
            or not isinstance(domains_by_id, Mapping)
            or not isinstance(bindings_by_id, Mapping)
            or set(source_hashes) != set(candidate_ids)
            or set(provider_fields_by_id) != set(candidate_ids)
            or set(domains_by_id) != set(candidate_ids)
            or set(bindings_by_id) != set(candidate_ids)
        ):
            raise FoundryError(
                "CHARACTER_GM_REVIEWED_OVERLAY_SOURCE_INVALID",
                "The freshly prepared Command 4 candidate authority is malformed.",
            )

        surface_actions = surface.get("actions")
        surface_procedures = surface.get("procedures")
        surface_ledger = surface.get("ledger_order")
        surface_source_hashes = surface.get("source_text_sha256_by_record_id")
        if (
            not isinstance(surface_actions, list)
            or not isinstance(surface_procedures, list)
            or not isinstance(surface_ledger, list)
            or not isinstance(surface_source_hashes, Mapping)
            or surface_source_hashes != dict(source_hashes)
        ):
            raise FoundryError(
                "CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID",
                "The reviewed surface does not preserve the freshly sealed Command 4 source ledger.",
            )
        surface_rows = [*surface_actions, *surface_procedures]
        rows_by_id: dict[str, Mapping[str, Any]] = {}
        for row in surface_rows:
            if not isinstance(row, Mapping) or not isinstance(row.get("record_id"), str) or row["record_id"] in rows_by_id:
                raise FoundryError(
                    "CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID",
                    "The reviewed surface contains duplicate or malformed candidate rows.",
                )
            rows_by_id[row["record_id"]] = row
        if (
            [entry.get("record_id") for entry in surface_ledger if isinstance(entry, Mapping)] != candidate_ids
            or len(surface_ledger) != len(candidate_ids)
            or set(rows_by_id) != set(candidate_ids)
        ):
            raise FoundryError(
                "CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID",
                "The reviewed surface ledger does not retain the sealed candidate order.",
            )

        for ledger_ordinal, candidate in enumerate(candidates, start=1):
            record_id = str(candidate["record_id"])
            row = rows_by_id[record_id]
            runtime_kind = _candidate_runtime_kind(candidate)
            action_type = _candidate_action_type(candidate)
            expected_action_id = _candidate_value(candidate, "action_id")
            entry = surface_ledger[ledger_ordinal - 1]
            if (
                row.get("runtime_kind") != runtime_kind
                or row.get("action_type") != action_type
                or row.get("action_id") != expected_action_id
                or row.get("record_id") != record_id
                or row.get("source_text_sha256") != source_hashes.get(record_id)
                or row.get("bucket") != _candidate_value(candidate, "bucket")
                or entry.get("ledger_ordinal") != ledger_ordinal
                or entry.get("record_id") != record_id
                or entry.get("runtime_kind") != runtime_kind
                or entry.get("action_id") != expected_action_id
            ):
                raise FoundryError(
                    "CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID",
                    "A reviewed surface row is not bound to its sealed Command 4 candidate identity.",
                    details={"record_id": record_id, "ledger_ordinal": ledger_ordinal},
                )

            expected_packet_ids = candidate.get("source_packet_ids")
            if (
                not isinstance(expected_packet_ids, list)
                or row.get("source_rule_ids") != expected_packet_ids
                or row.get("source_packet_ids") != expected_packet_ids
                or row.get("state_arrays") != []
            ):
                raise FoundryError(
                    "CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID",
                    "A reviewed surface row is not bound to its sealed source packets or state projection.",
                    details={"record_id": record_id},
                )

            provider_fields = list(_provider_authorable_fields(candidate))
            if provider_fields_by_id.get(record_id) != provider_fields:
                raise FoundryError(
                    "CHARACTER_GM_REVIEWED_OVERLAY_SOURCE_INVALID",
                    "The prepared provider-field projection is not the freshly derived candidate projection.",
                    details={"record_id": record_id},
                )
            domains = domains_by_id.get(record_id)
            binding = bindings_by_id.get(record_id)
            if not isinstance(domains, Mapping) or not isinstance(binding, Mapping):
                raise FoundryError(
                    "CHARACTER_GM_REVIEWED_OVERLAY_SOURCE_INVALID",
                    "The prepared provider-field domain authority is incomplete.",
                    details={"record_id": record_id},
                )
            packets = row.get("authoring_field_packets")
            if not isinstance(packets, Mapping) or set(packets) != set(provider_fields):
                raise FoundryError(
                    "CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID",
                    "A reviewed surface row does not cover exactly its sealed provider fields.",
                    details={"record_id": record_id},
                )

            for field in provider_fields:
                fresh_domain = _provider_field_domain(candidate, field)
                fresh_tokens = fresh_domain.get("selection_tokens") if isinstance(fresh_domain, Mapping) else None
                fresh_options = fresh_domain.get("options") if isinstance(fresh_domain, Mapping) else None
                fresh_option_records = fresh_domain.get("option_records") if isinstance(fresh_domain, Mapping) else None
                fresh_token_map = fresh_domain.get("token_to_option") if isinstance(fresh_domain, Mapping) else None
                if deterministic and (
                    not isinstance(fresh_options, list)
                    or len(fresh_options) != 1
                    or not isinstance(fresh_option_records, list)
                    or len(fresh_option_records) != 1
                    or not isinstance(fresh_tokens, list)
                    or len(fresh_tokens) != 1
                    or not isinstance(fresh_tokens[0], str)
                    or not isinstance(fresh_token_map, Mapping)
                    or set(fresh_token_map) != {fresh_tokens[0]}
                ):
                    raise FoundryError(
                        "CHARACTER_GM_REVIEWED_OVERLAY_SOURCE_INVALID",
                        "A deterministic overlay claims authority for a non-singleton sealed field domain.",
                        details={"record_id": record_id, "field": field},
                    )
                expected_binding = {
                    "record_id": record_id,
                    "source_text_sha256": source_hashes[record_id],
                    "fields": {field_name: list(domain["options"]) for field_name, domain in domains.items()},
                    "option_records": {field_name: deepcopy(domain["option_records"]) for field_name, domain in domains.items()},
                    "selection_tokens": {field_name: list(domain["selection_tokens"]) for field_name, domain in domains.items()},
                    "token_to_option": {field_name: deepcopy(domain["token_to_option"]) for field_name, domain in domains.items()},
                }
                if (
                    domains.get(field) != fresh_domain
                    or binding != expected_binding
                    or binding.get("fields", {}).get(field) != fresh_domain.get("options")
                    or binding.get("option_records", {}).get(field) != fresh_domain.get("option_records")
                    or binding.get("selection_tokens", {}).get(field) != fresh_domain.get("selection_tokens")
                    or binding.get("token_to_option", {}).get(field) != fresh_domain.get("token_to_option")
                ):
                    raise FoundryError(
                        "CHARACTER_GM_REVIEWED_OVERLAY_SOURCE_INVALID",
                        "A reviewed surface field is not bound to the freshly derived Command 4 domain.",
                        details={"record_id": record_id, "field": field},
                    )
                option_packets = []
                for option in fresh_domain.get("option_records", []):
                    if option.get("authority") == "not_applicable":
                        option_packets.append({"value": None, "authority": "not_applicable", "evidence": None})
                    else:
                        option_packets.append({
                            "value": option.get("provider_value"),
                            "authority": option.get("authority"),
                            "evidence": option.get("evidence"),
                        })
                if packets.get(field) not in option_packets:
                    raise FoundryError(
                        "CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID",
                        "A reviewed surface field packet is not one of the freshly sealed options.",
                        details={"record_id": record_id, "field": field},
                    )

            for field in COMMAND4_EXECUTION_FIELDS:
                expected_value = packets[field]["value"] if field in provider_fields else _candidate_value(candidate, field)
                if row.get(field) != expected_value:
                    raise FoundryError(
                        "CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID",
                        "A reviewed surface execution field is not bound to sealed candidate authority.",
                        details={"record_id": record_id, "field": field},
                    )

            expected_mechanics_source = (
                prepared.get("locked_source_proof_by_record_id", {}).get(record_id)
                or candidate.get("source")
                or candidate.get("mechanics_source")
            )
            if row.get("mechanics_source") != expected_mechanics_source:
                raise FoundryError(
                    "CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID",
                    "A reviewed surface mechanics source is not bound to sealed source authority.",
                    details={"record_id": record_id},
                )

        loadout = surface.get("signature_loadout_record_ids")
        eligible = {
            str(candidate["record_id"])
            for candidate in candidates
            if _candidate_runtime_kind(candidate) == "action"
            and _candidate_action_type(candidate) not in {"passive", "basic"}
        }
        eligible_order = [
            str(candidate["record_id"])
            for candidate in candidates
            if _candidate_runtime_kind(candidate) == "action"
            and _candidate_action_type(candidate) not in {"passive", "basic"}
        ]
        if deterministic:
            prepared_eligible = prepared.get("signature_loadout_eligible_record_ids")
            prepared_min = prepared.get("signature_loadout_min_items")
            prepared_max = prepared.get("signature_loadout_max_items")
            if (
                not isinstance(prepared_eligible, list)
                or prepared_eligible != [str(value) for value in prepared_eligible]
                or prepared_eligible != eligible_order
                or type(prepared_min) is not int
                or type(prepared_max) is not int
                or prepared_min != prepared_max
                or prepared_min != len(prepared_eligible)
                or not isinstance(loadout, list)
                or loadout != prepared_eligible
            ):
                raise FoundryError(
                    "CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID",
                    "The deterministic overlay loadout is not the complete singleton-forced sealed action set.",
                )
        else:
            prepared_eligible = prepared.get("signature_loadout_eligible_record_ids")
            prepared_min = prepared.get("signature_loadout_min_items")
            prepared_max = prepared.get("signature_loadout_max_items")
            if (
                not isinstance(prepared_eligible, list)
                or prepared_eligible != [str(value) for value in prepared_eligible]
                or prepared_eligible != eligible_order
                or type(prepared_min) is not int
                or type(prepared_max) is not int
                or not isinstance(loadout, list)
                or not prepared_min <= len(loadout) <= prepared_max
                or len(loadout) != len(set(loadout))
                or any(record_id not in eligible for record_id in loadout)
            ):
                raise FoundryError(
                    "CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID",
                    "The reviewed surface signature loadout is not drawn from sealed action authority.",
                )

            if request_matches_legacy and not request_matches_current:
                legacy_max_items = min(14, len(eligible_order))
                if (
                    len(eligible_order) < 10
                    or not isinstance(loadout, list)
                    or not 10 <= len(loadout) <= legacy_max_items
                    or len(loadout) != len(set(loadout))
                    or any(record_id not in set(eligible_order) for record_id in loadout)
                ):
                    raise FoundryError(
                        "CHARACTER_GM_REVIEWED_OVERLAY_SOURCE_MISMATCH",
                        "The legacy Command 4 request identity requires the legacy 10–14 action loadout domain.",
                        details={
                            "eligible_action_count": len(eligible_order),
                            "loadout_count": len(loadout) if isinstance(loadout, list) else None,
                            "legacy_min_items": 10,
                            "legacy_max_items": legacy_max_items,
                        },
                    )

    def _validate_reviewed_overlay(
        self,
        project_id: str,
        *,
        project: Mapping[str, Any],
        workspace_status: Mapping[str, Any],
        base_workspace: Path,
        base_manifest: Mapping[str, Any],
        reviewed_overlay_root: Path,
    ) -> tuple[Path, dict[str, Any]]:
        """Fail closed on anything except the exact reviewed C2B.4 overlay."""

        if not isinstance(reviewed_overlay_root, Path):
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_INVALID", "The reviewed overlay path is internal-only and must be a Path.")
        if not isinstance(base_workspace, Path) or base_workspace.is_symlink():
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_BASE_SYMLINK", "The sealed base workspace root must not be a symbolic link.")
        if reviewed_overlay_root.is_symlink():
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_SYMLINK", "The reviewed overlay root must not be a symbolic link.")
        try:
            overlay_stat = os.lstat(reviewed_overlay_root)
        except OSError as exc:
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_MISSING", "The reviewed Command 4 overlay directory is missing.") from exc
        if stat.S_ISLNK(overlay_stat.st_mode):
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_SYMLINK", "The reviewed overlay root must not be a symbolic link.")
        overlay = Path(os.path.abspath(os.fspath(reviewed_overlay_root)))
        if not stat.S_ISDIR(overlay_stat.st_mode) or overlay == base_workspace:
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_INVALID", "The reviewed overlay is not a detached directory.")
        self._verify_checksum_ledger(base_workspace, code_prefix="CHARACTER_GM_WORKSPACE_CHECKSUMS")
        base_hash = sha256_json(self._tree_hashes(base_workspace, include_checksum_ledger=True))
        if workspace_status.get("workspace_sha256") != base_hash:
            raise FoundryError(
                "CHARACTER_GM_WORKSPACE_STALE",
                "The current sealed Factory workspace no longer matches its pointer identity.",
                details={"expected": workspace_status.get("workspace_sha256"), "actual": base_hash},
            )
        if (
            base_manifest.get("project_id") != project_id
            or base_manifest.get("project_revision") != project.get("revision")
            or base_manifest.get("workspace_status") != "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE"
        ):
            raise FoundryError("CHARACTER_GM_WORKSPACE_PROJECT_IDENTITY_MISMATCH", "The current sealed Factory workspace is not bound to this project revision.")

        self._verify_checksum_ledger(overlay, code_prefix="CHARACTER_GM_REVIEWED_OVERLAY_CHECKSUMS")
        overlay_files = set(self._tree_hashes(overlay))
        base_files = set(self._tree_hashes(base_workspace))
        expected_extra = {
            "Command4_Provider_Overlay_Manifest.json",
            "Command_4/Provider_Action_Authoring_Audit.json",
            "Validation/Command4_Provider.validation.json",
        }
        if overlay_files != base_files | expected_extra:
            raise FoundryError(
                "CHARACTER_GM_REVIEWED_OVERLAY_FILES_INVALID",
                "The reviewed overlay contains an unexpected or missing file.",
                details={"missing": sorted((base_files | expected_extra) - overlay_files), "extra": sorted(overlay_files - (base_files | expected_extra))},
            )
        for relative in sorted(base_files - {"Command_4/Complete_Action_Surface.json"}):
            if (overlay / relative).read_bytes() != (base_workspace / relative).read_bytes():
                raise FoundryError(
                    "CHARACTER_GM_REVIEWED_OVERLAY_BASE_CHANGED",
                    "The reviewed overlay changed a sealed base file outside the Command 4 surface.",
                    details={"path": relative},
                )
        try:
            overlay_workspace_manifest = json.loads((overlay / "Workspace_Manifest.json").read_text(encoding="utf-8"))
            overlay_manifest = json.loads((overlay / "Command4_Provider_Overlay_Manifest.json").read_text(encoding="utf-8"))
            audit = json.loads((overlay / "Command_4/Provider_Action_Authoring_Audit.json").read_text(encoding="utf-8"))
            validation = json.loads((overlay / "Validation/Command4_Provider.validation.json").read_text(encoding="utf-8"))
            surface = json.loads((overlay / "Command_4/Complete_Action_Surface.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_MANIFEST_INVALID", "The reviewed overlay contains invalid JSON artifacts.") from exc
        if overlay_workspace_manifest != dict(base_manifest):
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_BASE_CHANGED", "The reviewed overlay workspace manifest is not byte-equivalent to the sealed base manifest.")
        surface_provenance = surface.get("provenance") if isinstance(surface, Mapping) else None
        deterministic_hint = any(
            isinstance(payload, Mapping)
            and (
                payload.get("provider_id") == _REVIEWED_DETERMINISTIC_PROVENANCE["provider_id"]
                or any(key in payload for key in _REVIEWED_DETERMINISTIC_ONLY_KEYS)
            )
            for payload in (overlay_manifest, audit, validation, surface_provenance)
        )
        deterministic = bool(deterministic_hint)
        deterministic_keys = set(_REVIEWED_DETERMINISTIC_PROVENANCE)
        expected_manifest_keys = {"overlay_id", "request_sha256", "response_sha256", "schema", "scope", "source_workspace_sha256"}
        if deterministic:
            expected_manifest_keys |= deterministic_keys
        if set(overlay_manifest) != expected_manifest_keys or overlay_manifest.get("schema") != _REVIEWED_OVERLAY_SCHEMA or overlay_manifest.get("scope") != _REVIEWED_OVERLAY_SCOPE:
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_MANIFEST_INVALID", "The reviewed overlay manifest is not the expected provider-authoring manifest.")
        request_sha256 = overlay_manifest.get("request_sha256")
        response_sha256 = overlay_manifest.get("response_sha256")
        source_workspace_sha256 = overlay_manifest.get("source_workspace_sha256")
        if not all(self._is_sha256(value) for value in (request_sha256, response_sha256, source_workspace_sha256)):
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_MANIFEST_INVALID", "The reviewed overlay hash bindings are malformed.")
        overlay_identity = {
            "source_workspace_sha256": source_workspace_sha256,
            "request_sha256": request_sha256,
            "response_sha256": response_sha256,
        }
        if deterministic:
            overlay_identity["resolution_mode"] = _REVIEWED_DETERMINISTIC_PROVENANCE["resolution_mode"]
        if source_workspace_sha256 != base_hash or overlay_manifest.get("overlay_id") != sha256_json(overlay_identity):
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_SOURCE_MISMATCH", "The reviewed overlay is not bound to the current sealed workspace and hashes.")
        if deterministic and any(
            type(overlay_manifest.get(key)) is not type(value) or overlay_manifest.get(key) != value
            for key, value in _REVIEWED_DETERMINISTIC_PROVENANCE.items()
        ):
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_MANIFEST_INVALID", "The deterministic overlay provenance is not the server-owned marker.")
        audit_legacy_keys = {"execution_authority", "global_combat_readiness", "provider_id", "purpose", "request_sha256", "response_sha256", "schema", "source_workspace_sha256"}
        validation_legacy_keys = {"execution_authority", "request_sha256", "response_sha256", "schema", "valid"}
        expected_audit_keys = audit_legacy_keys | deterministic_keys if deterministic else audit_legacy_keys
        expected_validation_keys = validation_legacy_keys | deterministic_keys if deterministic else validation_legacy_keys
        if set(audit) != expected_audit_keys or audit.get("schema") != _REVIEWED_OVERLAY_AUDIT_SCHEMA or audit.get("execution_authority") is not True or audit.get("global_combat_readiness") is not False:
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_AUDIT_INVALID", "The reviewed overlay audit is not an accepted authoring receipt.")
        if deterministic:
            if any(
                type(audit.get(key)) is not type(value) or audit.get(key) != value
                for key, value in _REVIEWED_DETERMINISTIC_PROVENANCE.items()
            ):
                raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_AUDIT_INVALID", "The deterministic overlay audit provenance is not the server-owned marker.")
        elif audit.get("purpose") != "factory_command4_action_authoring" or audit.get("provider_id") not in _REVIEWED_OVERLAY_PROVIDER_IDS:
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_AUDIT_INVALID", "The reviewed overlay audit is not an accepted local authoring receipt.")
        if (
            audit.get("request_sha256") != request_sha256
            or audit.get("response_sha256") != response_sha256
            or audit.get("source_workspace_sha256") != source_workspace_sha256
        ):
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_HASH_BINDING_INVALID", "The reviewed overlay audit hash bindings do not agree.")
        if set(validation) != expected_validation_keys or validation.get("schema") != _REVIEWED_OVERLAY_VALIDATION_SCHEMA or validation.get("valid") is not True or validation.get("execution_authority") is not True or validation.get("request_sha256") != request_sha256 or validation.get("response_sha256") != response_sha256:
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_VALIDATION_INVALID", "The reviewed overlay validation receipt is not bound to its manifest.")
        if deterministic and any(
            type(validation.get(key)) is not type(value) or validation.get(key) != value
            for key, value in _REVIEWED_DETERMINISTIC_PROVENANCE.items()
        ):
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_VALIDATION_INVALID", "The deterministic validation provenance is not the server-owned marker.")
        if deterministic:
            expected_surface_provenance_keys = {
                "workspace_sha256",
                "request_sha256",
                "response_sha256",
                "source_text_sha256_by_record_id",
            } | deterministic_keys
            if (
                not isinstance(surface_provenance, Mapping)
                or set(surface_provenance) != expected_surface_provenance_keys
                or any(
                    type(surface_provenance.get(key)) is not type(value)
                    or surface_provenance.get(key) != value
                    for key, value in _REVIEWED_DETERMINISTIC_PROVENANCE.items()
                )
            ):
                raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_SURFACE_INVALID", "The deterministic surface provenance is not the server-owned marker.")
        surface_summary = self._verify_reviewed_surface(
            surface,
            project_id=project_id,
            source_workspace_sha256=source_workspace_sha256,
            request_sha256=request_sha256,
            response_sha256=response_sha256,
            deterministic=deterministic,
        )
        self._verify_source_bound_command4_contract(
            project_id,
            base_workspace=base_workspace,
            source_workspace_sha256=source_workspace_sha256,
            request_sha256=request_sha256,
            surface=surface,
            source_root=self._command4_source_root(),
            deterministic=deterministic,
            allow_legacy_request=not deterministic,
            authority_db=getattr(getattr(self, "workspaces", None), "db", None),
        )
        return overlay, {
            "overlay_id": overlay_manifest["overlay_id"],
            "overlay_tree_sha256": sha256_json(self._tree_hashes(overlay, include_checksum_ledger=True)),
            "manifest_sha256": sha256_file(overlay / "Command4_Provider_Overlay_Manifest.json"),
            "surface_sha256": sha256_file(overlay / "Command_4/Complete_Action_Surface.json"),
            "audit_sha256": sha256_file(overlay / "Command_4/Provider_Action_Authoring_Audit.json"),
            "validation_sha256": sha256_file(overlay / "Validation/Command4_Provider.validation.json"),
            "source_workspace_sha256": source_workspace_sha256,
            "request_sha256": request_sha256,
            "response_sha256": response_sha256,
            "provider_id": audit["provider_id"],
            **surface_summary,
        }

    def _workspace_identity(self, project_id: str) -> tuple[dict[str, Any], Path, dict[str, Any]]:
        status = self.workspaces.status(project_id)
        if status.get("workspace_status") != "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE" or not status.get("available"):
            raise FoundryError("CHARACTER_GM_WORKSPACE_NOT_READY", "The deterministic C2B.2 Command 1-4 workspace is required.", details=status)
        root = Path(str(status.get("workspace_path") or ""))
        if root.is_symlink():
            raise FoundryError("CHARACTER_GM_WORKSPACE_SYMLINK", "The sealed Factory workspace root must not be a symbolic link.")
        manifest = json.loads((root / "Workspace_Manifest.json").read_text(encoding="utf-8"))
        if manifest.get("workspace_status") != "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE":
            raise FoundryError("CHARACTER_GM_WORKSPACE_STATUS_INVALID", "The Factory workspace status is not complete.")
        return status, root, manifest

    @staticmethod
    def _all_cards(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        cards = [row for rows in (snapshot.get("selected_record_sections") or {}).values() for row in (rows or []) if isinstance(row, dict)]
        cards.sort(key=lambda row: (int(row.get("acquisition_cl") or 0), str(row.get("section") or ""), str(row.get("record_id") or "")))
        return cards

    @staticmethod
    def _display_actions(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        by_id = {str(row.get("record_id")): row for row in CharacterGMCommand5Profile._all_cards(snapshot)}
        rows = []
        for index in snapshot.get("owner_facing_action_feature_index") or []:
            card = by_id.get(str(index.get("record_id")))
            if not card:
                continue
            execution = (card.get("capabilities") or {}).get("combat_execution") or "UNSUPPORTED"
            rows.append({
                "record_id": card.get("record_id"),
                "display_name": card.get("display_name"),
                "category": card.get("timing_or_category") or index.get("timing_or_category") or "Feature",
                "acquisition_cl": card.get("acquisition_cl"),
                "acquisition_route": card.get("acquisition_route"),
                "one_line_description": card.get("one_line_description"),
                "full_description": card.get("full_description"),
                "source": deepcopy(card.get("source")),
                "source_packet_ids": deepcopy(card.get("source_packet_ids") or []),
                "capabilities": deepcopy(card.get("capabilities") or {}),
                "combat_execution_status": execution,
                "display_only_not_execution_authority": True,
                "stable_id": card.get("record_id"),
            })
        return rows

    @staticmethod
    def _action_surface(workspace_root: Path, display_actions: list[dict[str, Any]]) -> dict[str, Any]:
        action_surface_path = workspace_root / "Command_4/Complete_Action_Surface.json"
        if action_surface_path.is_file():
            action_surface = json.loads(action_surface_path.read_text(encoding="utf-8"))
            if not isinstance(action_surface, dict) or not isinstance(action_surface.get("actions"), list):
                raise FoundryError(
                    "CHARACTER_GM_ACTION_SURFACE_INVALID",
                    "The post-workspace Command 4 action surface is not a JSON object with an actions array.",
                )
            return action_surface
        # Historical C2B.2 workspaces predate the post-workspace producer.
        # Preserve their display-only surface without granting authority.
        return {
            "schema_version":"TianxiaFoundry.CharacterGMDisplayActionSurface.v1",
            "status":"LEGACY_DISPLAY_ONLY_FALLBACK",
            "actions":deepcopy(display_actions),
            "execution_authority":False,
            "global_combat_readiness":False,
            "unresolved":[],
        }

    @staticmethod
    def _display_actions_from_surface(action_surface: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Project reviewed action records into the GM display action shape.

        The reviewed surface is the only source of executable action mechanics
        for an explicit overlay.  Keep its complete fields intact, while
        adding the small display-only envelope required by the Command 5
        model contract.  Procedures remain in their separate surface ledger.
        """

        actions = action_surface.get("actions")
        if not isinstance(actions, list):
            raise FoundryError(
                "CHARACTER_GM_ACTION_SURFACE_INVALID",
                "The reviewed action surface actions value must be a list.",
            )
        projected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in actions:
            if not isinstance(raw, Mapping):
                raise FoundryError(
                    "CHARACTER_GM_ACTION_SURFACE_INVALID",
                    "A reviewed action surface row is not an object.",
                )
            record_id = raw.get("record_id")
            name = raw.get("name") or raw.get("display_name")
            if not isinstance(record_id, str) or not record_id.strip() or record_id in seen:
                raise FoundryError(
                    "CHARACTER_GM_ACTION_SURFACE_INVALID",
                    "Reviewed action surface rows require unique nonblank record IDs.",
                )
            if not isinstance(name, str) or not name.strip():
                raise FoundryError(
                    "CHARACTER_GM_ACTION_SURFACE_INVALID",
                    "Reviewed action surface rows require a nonblank name.",
                )
            seen.add(record_id)
            row = deepcopy(dict(raw))
            row.update(
                {
                    "display_name": name,
                    "category": row.get("bucket") or row.get("action_type") or "Action",
                    "one_line_description": row.get("effect") or name,
                    "full_description": row.get("effect") or row.get("full_description") or name,
                    "source": deepcopy(row.get("mechanics_source") or row.get("source_packet_ids") or []),
                    "capabilities": {
                        "combat_execution": "SUPPORTED",
                        "gm_display": "SUPPORTED",
                        "ai_policy": "BLOCKED_BY_DEPENDENCY",
                    },
                    "combat_execution_status": "SUPPORTED",
                    "display_only_not_execution_authority": True,
                    "stable_id": record_id,
                }
            )
            projected.append(row)
        return projected

    @staticmethod
    def _reviewed_consumer_context(readiness: Any, gm_export: Any) -> str | None:
        """Classify the only historical consumer states an overlay may reuse."""

        if not isinstance(readiness, Mapping) or not isinstance(gm_export, Mapping):
            return None
        if (
            readiness.get("gm_screen") == "NOT_ATTEMPTED"
            and gm_export.get("available") is False
            and gm_export.get("readiness") == "NOT_ATTEMPTED"
            and gm_export.get("source_consumer_verified") is False
            and isinstance(gm_export.get("blockers"), list)
        ):
            return "legacy_not_attempted"
        if (
            readiness.get("gm_screen") == "GM_READY_SOURCE_VERIFIED"
            and gm_export.get("available") is True
            and gm_export.get("readiness") == "GM_READY_SOURCE_VERIFIED"
            and gm_export.get("source_consumer_verified") is True
            and gm_export.get("blockers") == []
        ):
            return "prior_source_verified"
        return None

    def validate_command4(
        self,
        project_id: str,
        *,
        profile_id: str = CHARACTER_GM_PROFILE,
        reviewed_overlay_root: Path | None = None,
        _workspace_snapshot: Path | None = None,
        _workspace_status_snapshot: Mapping[str, Any] | None = None,
        _workspace_manifest_snapshot: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        profile, profile_contract_sha = self.select_profile(profile_id)
        if profile.get("profile_id") != CHARACTER_GM_PROFILE:
            raise FoundryError("CHARACTER_GM_PROFILE_REQUIRED", "Character/GM Command 4 validation requires the explicit CHARACTER_GM_MODEL profile.")
        project = self.projects.get_project(project_id)["project"]
        sheet_response = self.sheets.sheet(project_id)
        snapshot = sheet_response.get("owner_character_sheet") or {}
        if _workspace_snapshot is not None:
            if reviewed_overlay_root is None or not isinstance(_workspace_snapshot, Path) or _workspace_snapshot.is_symlink():
                raise FoundryError(
                    "CHARACTER_GM_REVIEWED_OVERLAY_BASE_SYMLINK",
                    "The private sealed workspace snapshot is required only for explicit reviewed overlays and must not be a symbolic link.",
                )
            if not isinstance(_workspace_status_snapshot, Mapping) or not isinstance(_workspace_manifest_snapshot, Mapping):
                raise FoundryError(
                    "CHARACTER_GM_REVIEWED_OVERLAY_BASE_INVALID",
                    "The private sealed workspace snapshot context is incomplete.",
                )
            workspace_status = dict(_workspace_status_snapshot)
            workspace_root = _workspace_snapshot
            manifest = dict(_workspace_manifest_snapshot)
        else:
            workspace_status, workspace_root, manifest = self._workspace_identity(project_id)
        content_root = workspace_root
        reviewed_overlay: dict[str, Any] | None = None
        if reviewed_overlay_root is not None:
            verified_overlay_root, reviewed_overlay = self._validate_reviewed_overlay(
                project_id,
                project=project,
                workspace_status=workspace_status,
                base_workspace=workspace_root,
                base_manifest=manifest,
                reviewed_overlay_root=reviewed_overlay_root,
            )
            # The sealed base remains the identity/source binding, while all
            # post-validation Command 4 content reads come from the exact
            # detached root that passed overlay validation.
            content_root = verified_overlay_root
        diagnostics: list[dict[str, Any]] = []
        readiness = sheet_response.get("readiness") or {}
        if readiness.get("advancement") != "ADVANCEMENT_READY": diagnostics.append({"code":"CHARACTER_GM_ADVANCEMENT_NOT_READY"})
        if readiness.get("character_sheet") != "CHARACTER_SHEET_READY": diagnostics.append({"code":"CHARACTER_GM_SHEET_NOT_READY"})
        gm_export = sheet_response.get("gm_export")
        if reviewed_overlay_root is None:
            if readiness.get("gm_screen") != "NOT_ATTEMPTED": diagnostics.append({"code":"CHARACTER_GM_FALSE_CONSUMER_READINESS"})
            if not isinstance(gm_export, Mapping) or gm_export.get("available") is not False:
                diagnostics.append({"code":"CHARACTER_GM_EXPORT_MUST_REMAIN_BLOCKED"})
        else:
            # An explicit reviewed overlay may be released from a workspace
            # that has already completed the historical GM consumer check.
            # That check is context only: this validation still publishes the
            # new candidate as NOT_ATTEMPTED below.  Require the complete
            # prior-state shape so a partial or forged combination cannot
            # bypass the default fail-closed consumer boundary.
            if self._reviewed_consumer_context(readiness, gm_export) is None:
                diagnostics.append({"code":"CHARACTER_GM_REVIEWED_OVERLAY_CONSUMER_STATE_INVALID"})
        if manifest.get("project_id") != project_id or manifest.get("project_revision") != project.get("revision"):
            diagnostics.append({"code":"CHARACTER_GM_WORKSPACE_PROJECT_IDENTITY_MISMATCH"})
        if manifest.get("character_sheet_sha256") != sheet_response.get("sheet_artifact", {}).get("sha256"):
            diagnostics.append({"code":"CHARACTER_GM_WORKSPACE_SHEET_STALE"})
        required = [
            "Command_4/Training_Sources.json",
            "Command_4/Dao_I_Ching_GM_Authoring.json", "Command_4/Descriptive_AI_Behavior.json",
            "Validation/C2B2_Workspace.validation.json",
        ]
        for rel in required:
            if not (content_root / rel).is_file(): diagnostics.append({"code":"CHARACTER_GM_AUTHORING_ARTIFACT_MISSING","path":rel})
        training = json.loads((content_root / "Command_4/Training_Sources.json").read_text(encoding="utf-8")) if (content_root / "Command_4/Training_Sources.json").is_file() else {}
        dao = json.loads((content_root / "Command_4/Dao_I_Ching_GM_Authoring.json").read_text(encoding="utf-8")) if (content_root / "Command_4/Dao_I_Ching_GM_Authoring.json").is_file() else {}
        ai = json.loads((content_root / "Command_4/Descriptive_AI_Behavior.json").read_text(encoding="utf-8")) if (content_root / "Command_4/Descriptive_AI_Behavior.json").is_file() else {}
        selected_ids = {str(row.get("record_id")) for row in self._all_cards(snapshot)}
        required_training_ids = set(manifest.get("required_training_source_coverage") or [])
        if not required_training_ids:
            workspace_profile, _workspace_profile_sha = self.workspaces._workspace_profile()
            required_training_ids = set(workspace_profile.get("required_training_source_coverage") or [])
        covered = [str(record) for row in training.get("training_sources") or [] for record in row.get("record_ids") or []]
        if set(covered) != required_training_ids or len(covered) != len(set(covered)):
            diagnostics.append({"code":"CHARACTER_GM_TRAINING_COVERAGE_INVALID","missing":sorted(required_training_ids-set(covered)),"extra":sorted(set(covered)-required_training_ids)})
        gm_profile = manifest.get("gm_authoring_profile") or {}
        gm_classification = gm_profile.get("classification")
        gm_authorship = manifest.get("gm_authorship") or gm_profile.get("authorship")
        gm_binding = None
        if gm_classification == "ACTUAL_GM_AUTHORING" or manifest.get("gm_artifact_binding") is not None:
            try:
                verified_gm = self.workspaces._load_gm_authoring(
                    project_id,
                    project_revision=int(project.get("revision")),
                    snapshot=snapshot,
                )
                gm_binding = verified_gm.get("binding") if isinstance(verified_gm, Mapping) else None
                if gm_classification == "ACTUAL_GM_AUTHORING" and not isinstance(gm_binding, Mapping):
                    diagnostics.append({"code": "CHARACTER_GM_ACTUAL_ARTIFACT_UNVERIFIED"})
            except FoundryError as exc:
                diagnostics.append({"code": "CHARACTER_GM_ACTUAL_ARTIFACT_UNVERIFIED", "cause": exc.code})
        actual_gm_ready = (
            gm_classification == "ACTUAL_GM_AUTHORING"
            and isinstance(gm_binding, Mapping)
            and gm_binding.get("verified") is True
            and gm_binding.get("owner_ratified") is True
            and gm_binding.get("source_record_ids") == sorted(selected_ids)
            and isinstance(manifest.get("gm_artifact_binding"), Mapping)
            and all(manifest["gm_artifact_binding"].get(field) == gm_binding.get(field) for field in (
                "receipt_id", "receipt_sha256", "artifact_sha256", "profile_sha256",
                "source_snapshot_sha256", "selected_record_content_sha256", "owner_decision_id",
            ))
        )
        provisional_gm = gm_classification == "PROVISIONAL_GM_GUIDANCE" or (
            isinstance(gm_authorship, Mapping) and gm_authorship.get("status") == "PROVISIONAL"
        )
        if provisional_gm:
            # Owner ruling 2026-09-13: project-derived (provisional) GM
            # guidance does not gate the character.  A build that passes the
            # inner gates proceeds; model-authored guidance and owner
            # ratification remain an optional later step (Characters →
            # Factory and GM readiness) and still gate the GM export.
            gm_guidance_status = "PROVISIONAL"
        elif gm_classification == "ACTUAL_GM_AUTHORING" and not actual_gm_ready:
            diagnostics.append({"code":"CHARACTER_GM_ACTUAL_AUTHORING_NOT_RATIFIED"})
        elif gm_classification == "OWNER_RATIFIED_GM_AUTHORING" and gm_authorship is not None and not actual_gm_ready:
            diagnostics.append({"code":"CHARACTER_GM_AUTHORED_BINDING_NOT_RATIFIED"})
        elif gm_classification not in {"OWNER_RATIFIED_GM_AUTHORING", "ACTUAL_GM_AUTHORING"}:
            diagnostics.append({"code":"CHARACTER_GM_AUTHORING_CLASSIFICATION_INVALID"})
        if not provisional_gm:
            gm_guidance_status = "ACTUAL" if actual_gm_ready else "OWNER_RATIFIED" if gm_classification == "OWNER_RATIFIED_GM_AUTHORING" else "UNRATIFIED"
        allowed_dao_classifications = {"OWNER_RATIFIED_GM_AUTHORING"}
        if actual_gm_ready:
            allowed_dao_classifications.add("ACTUAL_GM_AUTHORING")
        if provisional_gm:
            allowed_dao_classifications.add("PROVISIONAL_GM_GUIDANCE")
        if dao.get("classification") not in allowed_dao_classifications or (dao.get("dao") or {}).get("mechanical_effects") != [] or (dao.get("i_ching") or {}).get("mechanical_effects") != []:
            diagnostics.append({"code":"CHARACTER_GM_DAO_ICHING_CLASSIFICATION_INVALID"})
        if ai.get("not_executable_controller_policy") is not True or ai.get("controller_policy_registered") is True:
            diagnostics.append({"code":"CHARACTER_GM_AI_POLICY_EXECUTABLE_CLAIM"})
        if any((row.get("capabilities") or {}).get("combat_execution") not in {"SUPPORTED","NOT_APPLICABLE"} and not row.get("display_only_not_execution_authority") for row in self._all_cards(snapshot)):
            diagnostics.append({"code":"CHARACTER_GM_DISPLAY_PROMOTED_TO_EXECUTION"})
        result = {
            "schema_version":"TianxiaFoundry.CharacterGMCommand4ProfileValidation.v1",
            "project_id":project_id,"project_revision":project.get("revision"),"build_profile":profile,
            "build_profile_contract_sha256":profile_contract_sha,
            "character_gm_command4_status":CHARACTER_GM_COMMAND4_PASS if not diagnostics else "CHARACTER_GM_COMMAND_4_PROFILE_FAIL",
            "legacy_full_command4_status":"BLOCKED_NOT_RUN_COMBAT_EXECUTION_INCOMPLETE",
            "workspace_id":workspace_status.get("workspace_id"),"workspace_sha256":workspace_status.get("workspace_sha256"),
            "character_sheet_sha256":sheet_response.get("sheet_artifact",{}).get("sha256"),
            "selected_record_count":len(selected_ids),"training_coverage_count":len(set(covered)),
            "gm_guidance_status":gm_guidance_status,
            "command5_invoked":False,"command6_invoked":False,"gm_export_available":False,
            "diagnostics":diagnostics,"valid":not diagnostics,
        }
        if reviewed_overlay is not None:
            result["reviewed_command4_overlay"] = reviewed_overlay
        if diagnostics:
            raise FoundryError("CHARACTER_GM_COMMAND4_BLOCKED", "The Character/GM Command 4 profile failed validation.", details=result)
        return result

    @staticmethod
    def _typed_none(snapshot: dict[str, Any], name: str) -> dict[str, Any]:
        if name == "equipment" and isinstance(snapshot.get("equipment"), list) and snapshot["equipment"]:
            return deepcopy(snapshot["equipment"])
        selected_method = snapshot.get("method") or {}
        if name == "method" and has_acquired_method(selected_method):
            return deepcopy(selected_method)
        selected_foundation = snapshot.get("foundation") or {}
        if name == "foundation" and has_acquired_foundation(selected_foundation):
            return deepcopy(selected_foundation)
        return deepcopy((snapshot.get("explicit_none_systems") or {}).get(name) or {"state":"none","source_backed":True})

    @staticmethod
    def _master_surface(master: Mapping[str, Any] | None, name: str, fallback: Any) -> Any:
        """Use a non-empty Command 2 surface when it is explicitly present.

        The owner sheet remains the fallback for legacy/incomplete projections,
        but a Command 2 record (including a typed-none record) is the
        authoritative mechanical value for Command 5.  Empty or absent master
        fields do not create a new claim and therefore retain the fallback.
        """

        if isinstance(master, Mapping) and name in master:
            value = master.get(name)
            if isinstance(value, Mapping) and value:
                return deepcopy(dict(value))
            if isinstance(value, list):
                return deepcopy(value)
        return deepcopy(fallback)

    @staticmethod
    def _merge_snapshot_display_fields(
        master_value: Any,
        snapshot_value: Any,
        *,
        name: str,
    ) -> Any:
        """Carry validated owner-sheet display details onto master mechanics.

        The Character Master Ledger remains authoritative for the selected
        Method/Foundation state and mechanics.  Its rows intentionally contain
        acquisition identity but may omit the long display description and
        exact source aliases that were already authenticated while building the
        owner sheet.  Merge those display-only fields only after checking the
        shared record identity and source locator.
        """

        if not isinstance(master_value, Mapping) or not master_value:
            return deepcopy(master_value)
        result = deepcopy(dict(master_value))
        if name == "foundation":
            snapshot_acquired = has_acquired_foundation(snapshot_value)
            master_acquired = has_acquired_foundation(result)
        elif name == "method":
            snapshot_acquired = has_acquired_method(snapshot_value)
            master_acquired = has_acquired_method(result)
        else:
            snapshot_acquired = (
                isinstance(snapshot_value, Mapping)
                and snapshot_value.get("state") == "acquired"
                and bool(snapshot_value.get("record_id"))
            )
            master_acquired = (
                result.get("state") == "acquired"
                and bool(result.get("record_id"))
            )
        if not snapshot_acquired:
            return result
        if not master_acquired:
            return result

        display_payload_fields = (
            "full_description",
            "full_description_source",
            "source",
            "source_path",
            "source_anchor",
            "source_hash",
        )
        has_display_enrichment = any(
            field in snapshot_value
            and snapshot_value.get(field) not in (None, "", {}, [])
            for field in display_payload_fields
        )
        if not has_display_enrichment:
            # Older acquired snapshots contain only the selected record's
            # identity and state.  They do not authenticate a new display
            # claim, so preserve the canonical master row unchanged.
            return result
        if (
            not isinstance(result.get("record_id"), str)
            or not isinstance(snapshot_value.get("record_id"), str)
            or result.get("record_id") != snapshot_value.get("record_id")
        ):
            raise FoundryError(
                "CHARACTER_GM_SELECTED_RECORD_DISPLAY_INVALID",
                f"The master {name} record identity differs from the authenticated owner-sheet selection.",
                details={"surface": name, "master_record_id": result.get("record_id"), "snapshot_record_id": snapshot_value.get("record_id")},
            )

        master_record_hash = result.get("record_hash")
        snapshot_record_hash = snapshot_value.get("record_hash")
        if (
            not isinstance(master_record_hash, str)
            or not master_record_hash.strip()
            or not isinstance(snapshot_record_hash, str)
            or not snapshot_record_hash.strip()
            or master_record_hash != snapshot_record_hash
        ):
            raise FoundryError(
                "CHARACTER_GM_SELECTED_RECORD_DISPLAY_INVALID",
                f"The master {name} record hash is not exactly bound to the authenticated owner-sheet selection.",
                details={
                    "surface": name,
                    "master_record_id": result.get("record_id"),
                    "master_record_hash": master_record_hash,
                    "snapshot_record_hash": snapshot_record_hash,
                },
            )

        identity_fields = ("record_id", "display_name")
        for field in identity_fields:
            master_identity = result.get(field)
            snapshot_identity = snapshot_value.get(field)
            if master_identity is not None and snapshot_identity is not None and master_identity != snapshot_identity:
                raise FoundryError(
                    "CHARACTER_GM_SELECTED_RECORD_DISPLAY_INVALID",
                    f"The master {name} identity differs from the authenticated owner-sheet selection.",
                    details={"surface": name, "field": field, "master": master_identity, "snapshot": snapshot_identity},
                )

        def source_identity(row: Mapping[str, Any]) -> dict[str, str]:
            source = row.get("source")
            if isinstance(source, Mapping):
                # The Foundation mechanics registry seals its locator as
                # ``artifact``/``artifact_sha256`` and the projector carries
                # that object onto the master row.  The owner-sheet card maps
                # the same locator to ``path``/``sha256`` with the canonical
                # ``foundation:<id>`` anchor (non_sphere_authority.service), so
                # read both shapes and compare one identity.
                path = source.get("path")
                if path is None:
                    path = source.get("artifact")
                sha256 = source.get("sha256")
                if sha256 is None:
                    sha256 = source.get("source_hash")
                if sha256 is None:
                    sha256 = source.get("file_sha256")
                if sha256 is None:
                    sha256 = source.get("artifact_sha256")
                anchor = source.get("anchor")
                record_id = row.get("record_id")
                if (
                    anchor is None
                    and name == "foundation"
                    and source.get("artifact") is not None
                    and isinstance(record_id, str)
                    and record_id.strip()
                ):
                    anchor = f"foundation:{record_id}"
                identity = {
                    "path": str(path) if path is not None else "",
                    "anchor": str(anchor) if anchor is not None else "",
                    "sha256": str(sha256) if sha256 is not None else "",
                }
            else:
                identity = {
                    "path": str(row.get("source_path")) if row.get("source_path") is not None else "",
                    "anchor": str(row.get("source_anchor")) if row.get("source_anchor") is not None else "",
                    "sha256": str(row.get("source_hash")) if row.get("source_hash") is not None else "",
                }
            aliases = {"source_path": "path", "source_anchor": "anchor", "source_hash": "sha256"}
            for alias, key in aliases.items():
                if alias in row and row.get(alias) is not None and str(row.get(alias)) != identity[key]:
                    raise FoundryError(
                        "CHARACTER_GM_SELECTED_RECORD_DISPLAY_INVALID",
                        f"The selected {name} source aliases disagree with its source identity.",
                        details={"surface": name, "field": alias, "record_id": row.get("record_id")},
                    )
            return identity

        snapshot_source = source_identity(snapshot_value)
        if any(not snapshot_source[key].strip() for key in ("path", "anchor", "sha256")):
            raise FoundryError(
                "CHARACTER_GM_SELECTED_RECORD_DISPLAY_INVALID",
                f"The selected owner-sheet {name} lacks complete source identity.",
                details={"surface": name, "record_id": snapshot_value.get("record_id")},
            )
        master_source = source_identity(result)
        master_source_present = isinstance(result.get("source"), Mapping) or any(
            field in result for field in ("source_path", "source_anchor", "source_hash")
        )
        if master_source_present and any(not master_source[key].strip() for key in ("path", "anchor", "sha256")):
            raise FoundryError(
                "CHARACTER_GM_SELECTED_RECORD_DISPLAY_INVALID",
                f"The master {name} source identity is incomplete.",
                details={"surface": name, "record_id": result.get("record_id")},
            )
        if any(master_source[key] and master_source[key] != snapshot_source[key] for key in master_source):
            raise FoundryError(
                "CHARACTER_GM_SELECTED_RECORD_DISPLAY_INVALID",
                f"The master {name} source identity differs from the authenticated owner-sheet selection.",
                details={"surface": name, "record_id": result.get("record_id")},
            )

        snapshot_display_only = snapshot_value.get("display_only_not_execution_authority", None)
        if "display_only_not_execution_authority" in snapshot_value:
            if not isinstance(snapshot_display_only, bool):
                raise FoundryError(
                    "CHARACTER_GM_SELECTED_RECORD_DISPLAY_INVALID",
                    f"The selected {name} display authority flag is not boolean.",
                    details={"surface": name, "record_id": result.get("record_id")},
                )
            if "display_only_not_execution_authority" in result:
                master_display_only = result.get("display_only_not_execution_authority")
                if not isinstance(master_display_only, bool) or master_display_only != snapshot_display_only:
                    raise FoundryError(
                        "CHARACTER_GM_SELECTED_RECORD_DISPLAY_INVALID",
                        f"The master {name} display authority boundary conflicts with the authenticated owner-sheet selection.",
                        details={
                            "surface": name,
                            "record_id": result.get("record_id"),
                            "master_display_only_not_execution_authority": master_display_only,
                            "snapshot_display_only_not_execution_authority": snapshot_display_only,
                        },
                    )
            elif snapshot_display_only:
                # A true display-only marker is safe to add when the legacy
                # master omitted the optional marker.  Never copy false into
                # an unmarked master, since that could imply execution
                # authority that the canonical row did not establish.
                result["display_only_not_execution_authority"] = True

        display_fields = (
            "full_description",
            "full_description_source",
            "source",
            "source_path",
            "source_anchor",
            "source_hash",
        )
        for field in display_fields:
            if field in snapshot_value:
                result[field] = deepcopy(snapshot_value[field])
        return result

    @staticmethod
    def _display_resource_container(snapshot: Mapping[str, Any]) -> dict[str, Any]:
        """Return a consumer-safe derived equipment/resources/states shape."""

        equipment = CharacterGMCommand5Profile._typed_none(dict(snapshot), "equipment")
        resources_raw = (snapshot.get("ability_scores_and_statistics") or {}).get("primary_resource")
        resources: list[Any] = []
        if isinstance(resources_raw, list):
            resources = deepcopy(resources_raw)
        elif isinstance(resources_raw, Mapping):
            resources = [deepcopy(resources_raw)]
        elif resources_raw not in (None, ""):
            resources = [resources_raw]
        states_raw = snapshot.get("states")
        states: list[Any] = deepcopy(states_raw) if isinstance(states_raw, list) else []
        result: dict[str, Any] = {
            "equipment": deepcopy(equipment if isinstance(equipment, list) else []),
            "resources": resources,
            "states": states,
            "states_status": "PENDING_COMBAT_EXECUTION",
        }
        if isinstance(equipment, Mapping) and equipment.get("state") in {"none", "not_applicable", "not_selected"}:
            result["equipment_none_state"] = deepcopy(dict(equipment))
        if isinstance(resources_raw, Mapping):
            result["resource_source_map"] = deepcopy(dict(resources_raw))
        return result

    def _models(self, *, project: dict[str, Any], sheet_response: dict[str, Any], workspace_root: Path, workspace_status: dict[str, Any], profile: dict[str, Any], profile_contract_sha: str, command4: dict[str, Any], master: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        snapshot = deepcopy(sheet_response["owner_character_sheet"])
        actions = self._display_actions(snapshot)
        training = json.loads((workspace_root / "Command_4/Training_Sources.json").read_text(encoding="utf-8"))
        dao = json.loads((workspace_root / "Command_4/Dao_I_Ching_GM_Authoring.json").read_text(encoding="utf-8"))
        ai = json.loads((workspace_root / "Command_4/Descriptive_AI_Behavior.json").read_text(encoding="utf-8"))
        recorded_arts, recorded_none_state = _advanced_surface(snapshot, "recorded_arts")
        forged_techniques, forged_none_state = _advanced_surface(snapshot, "forged_techniques")
        immortal_arts, immortal_none_state = _advanced_surface(snapshot, "immortal_arts")
        current_cl = _snapshot_current_cl(snapshot)
        if current_cl < 15:
            # Immortal Arts are not an available surface before their sealed
            # minimum CL.  Keep the source rows out of every consumer-facing
            # array and publish the typed lock state instead.
            immortal_arts = []
            immortal_none_state = {
                "state": "locked_by_minimum_cl",
                "source_backed": True,
                "minimum_cl": 15,
                "current_cl": current_cl,
            }
        elif not immortal_arts:
            # At/above the unlock point, an absent source entry is an
            # explicit none/not-acquired result, never an implicit omission.
            if not isinstance(immortal_none_state, dict) or immortal_none_state.get("state") in {
                None,
                "not_projected",
                "missing",
                "locked_by_minimum_cl",
            }:
                immortal_none_state = {
                    "state": "none",
                    "source_backed": True,
                    "minimum_cl": 15,
                    "current_cl": current_cl,
                }
        paths_subpaths = deepcopy(snapshot.get("path_and_subpath") or {})
        insights = {
            "cultivation_insight_record_ids": deepcopy((snapshot.get("spheres_and_talents") or {}).get("cultivation_insight_record_ids") or []),
            "cultivation_insight_occurrences": deepcopy((snapshot.get("spheres_and_talents") or {}).get("cultivation_insight_occurrences") or []),
        }
        auth = snapshot.get("authority_and_artifact_identity") or {}
        metadata = {
            "build_profile":CHARACTER_GM_PROFILE,"build_profile_version":profile.get("profile_version"),"build_profile_contract_sha256":profile_contract_sha,
            "candidate_status":GM_CANDIDATE_READY,"project_id":project["project_id"],"project_revision":project["revision"],
            "event_count":auth.get("event_count"),"event_head_hash":auth.get("event_head_hash"),"content_lock_hash":auth.get("content_lock_hash"),
            "typed_choice_snapshot_sha256":auth.get("typed_choice_snapshot_sha256"),
             "projection_id":auth.get("projection_id"),"character_sheet_sha256":sheet_response["sheet_artifact"]["sha256"],
             "workspace_id":workspace_status.get("workspace_id"),"workspace_sha256":workspace_status.get("workspace_sha256"),
             "consumer_verification":"NOT_ATTEMPTED","gm_export_available":False,"command6_status":"NOT_RUN",
             "combat":"NOT_ATTEMPTED","combat_execution":"NOT_ATTEMPTED",
             "combat_runtime":"NOT_CLAIMED","combat_sheet":"NOT_CLAIMED",
             "combat_ready_semantics":"NOT_CLAIMED","encounter":"NOT_ATTEMPTED",
             "controller_selection":"NOT_ATTEMPTED","encounter_setup_required":True,
             "current_resource_requirements":{"current_qi_required":False,"current_martial_focus_required":False},
             "current_qi_required":False,"current_martial_focus_required":False,
             "opponent_team_completion_required":True,"battlefield_choice":"NOT_ATTEMPTED",
             "battlefield_owner_choice_committed":False,"token_placement":"NOT_ATTEMPTED",
             "token_placement_committed":False,"initiative":"NOT_ATTEMPTED",
             "initiative_attempted":False,"cpk1_schemas_registered":False,
        }
        authoritative_foundation = self._merge_snapshot_display_fields(
            self._master_surface(master, "foundation", self._typed_none(snapshot, "foundation")),
            snapshot.get("foundation"),
            name="foundation",
        )
        authoritative_method = self._merge_snapshot_display_fields(
            self._master_surface(master, "method", self._typed_none(snapshot, "method")),
            snapshot.get("method"),
            name="method",
        )
        gm_model = {
            "schema_version":"Tianxia_GM_Character_Model_v1","metadata":metadata,
            "identity":deepcopy(snapshot.get("identity")),"stats":deepcopy(snapshot.get("ability_scores_and_statistics")),
            "leveling_ledger":deepcopy((snapshot.get("advancement_history") or {}).get("levels") or []),
            "background_origin":deepcopy(snapshot.get("background_and_origin")),
            # Keep the historical combined projection for older consumers, but
            # publish independent path and insight surfaces below and in tabs.
            "paths_subpaths_insights": {**deepcopy(paths_subpaths), **deepcopy(insights)},
            "paths_subpaths": deepcopy(paths_subpaths),
            "insights": deepcopy(insights),
            "spheres_talents":deepcopy(snapshot.get("spheres_and_talents")),
            "actions":actions,
            "recorded_arts":deepcopy(recorded_arts),
            "recorded_arts_none_state":deepcopy(recorded_none_state or {"state":"not_applicable","source_backed":True}),
            "foundation":authoritative_foundation,"method":authoritative_method,
            "dao_i_ching":{"dao":deepcopy(dao.get("dao")),"i_ching":deepcopy(dao.get("i_ching"))},
            # Preserve the source-shaped C2B.3 container in the Command 5 v1
            # model.  R2K consumer normalization is derived later in
            # ``_surfaces`` (and in the portable package's v2/view roots); the
            # source model must retain typed-none/resource/state authority.
            "equipment_resources_states":{"equipment":self._typed_none(snapshot,"equipment"),"resources":{"qi_maximum":(snapshot.get("ability_scores_and_statistics") or {}).get("primary_resource")},"states":{"status":"PENDING_COMBAT_EXECUTION","typed_definitions":[]}},
            "spirit_companions":{"state":"none","source_backed":True,"entries":[]},
            "forged_techniques":deepcopy(forged_techniques),
            "forged_techniques_none_state":deepcopy(forged_none_state or {"state":"not_applicable","source_backed":True}),
            "immortal_arts":deepcopy(immortal_arts),
            "immortal_arts_none_state":deepcopy(immortal_none_state or {"state":"not_applicable","source_backed":True}),
            "training_sources":deepcopy(training.get("training_sources") or []),"ai_behavior":deepcopy(ai),
            "diagnostics":{"valid":True,"gm_screen_consumer_verification":"NOT_ATTEMPTED","combat_execution_pending":True,"display_only_record_count":sum(1 for row in actions if row["display_only_not_execution_authority"]),"no_false_combat_claim":True},
             "capability_readiness":{"advancement":"ADVANCEMENT_READY","character_sheet":"CHARACTER_SHEET_READY","gm_tactical_authoring":"COMPLETE","character_gm_command4":CHARACTER_GM_COMMAND4_PASS,"gm_model_candidate":GM_CANDIDATE_READY,"gm_screen_consumer":"NOT_ATTEMPTED","combat":"NOT_ATTEMPTED","combat_execution":"NOT_ATTEMPTED","combat_runtime":"NOT_CLAIMED","combat_sheet":"NOT_CLAIMED","combat_ready_semantics":"NOT_CLAIMED","encounter":"NOT_ATTEMPTED","controller_selection":"NOT_ATTEMPTED","encounter_setup_required":True,"current_resource_requirements":{"current_qi_required":False,"current_martial_focus_required":False},"current_qi_required":False,"current_martial_focus_required":False,"opponent_team_completion_required":True,"battlefield_choice":"NOT_ATTEMPTED","battlefield_owner_choice_committed":False,"token_placement":"NOT_ATTEMPTED","token_placement_committed":False,"initiative":"NOT_ATTEMPTED","initiative_attempted":False},
            "provenance":{"character_sheet":deepcopy(snapshot.get("section_provenance")),"command4_profile_validation_sha256":sha256_json(command4),"workspace_manifest_sha256":workspace_status.get("manifest_sha256"),"selected_record_identity_index":deepcopy(snapshot.get("selected_record_identity_index"))},
        }
        # The pinned vendor view schema (04_SCHEMAS/gm_character_view_model.schema.json) requires "composites"; composite
        # playbooks were removed 2026-10-13, so it is always an empty list.
        view = {
            "composites": [],
            "schema_version":"Tianxia_GM_Character_View_Model_v2","identity":deepcopy(gm_model["identity"]),"core_stats":deepcopy(gm_model["stats"]),
            "leveling_ledger":deepcopy(gm_model["leveling_ledger"]),"background_origin":deepcopy(gm_model["background_origin"]),"spheres_talents":deepcopy(gm_model["spheres_talents"]),
            "paths_subpaths":deepcopy(gm_model["paths_subpaths"]),"insights":deepcopy(gm_model["insights"]),
            "actions":deepcopy(actions),"composites":[],"forged_techniques":deepcopy(gm_model["forged_techniques"]),"forged_techniques_none_state":deepcopy(gm_model["forged_techniques_none_state"]),"preserved_forged_expressions":[],"emergency_technique_seeds":[],"martial_manuals":deepcopy(gm_model["recorded_arts"]),"recorded_arts_none_state":deepcopy(gm_model["recorded_arts_none_state"]),"immortal_arts":deepcopy(gm_model["immortal_arts"]),"immortal_arts_none_state":deepcopy(gm_model["immortal_arts_none_state"]),"spirit_companions":deepcopy(gm_model["spirit_companions"]),
            "foundation":deepcopy(gm_model["foundation"]),"method":deepcopy(gm_model["method"]),"dao_i_ching":deepcopy(gm_model["dao_i_ching"]),"equipment_resources_states":deepcopy(gm_model["equipment_resources_states"]),
            "diagnostics":[{"code":"GM_SCREEN_CONSUMER_VERIFICATION_PENDING","severity":"notice"},{"code":"COMBAT_EXECUTION_PENDING","severity":"notice","display_only_records":sum(1 for row in actions if row["display_only_not_execution_authority"])}],
            "validation":{"status":GM_CANDIDATE_READY,"build_profile":CHARACTER_GM_PROFILE,"schema_valid":True,"consumer_verification":"NOT_ATTEMPTED","gm_export_available":False},
            "metadata":deepcopy(metadata),"paths_subpaths_insights":deepcopy(gm_model["paths_subpaths_insights"]),"training_sources":deepcopy(gm_model["training_sources"]),"ai_behavior":deepcopy(ai),"capability_readiness":deepcopy(gm_model["capability_readiness"]),"provenance":deepcopy(gm_model["provenance"]),
        }
        display_rows = []
        tab_values = {
            "overview-core-stats": {"identity":gm_model["identity"],"stats":gm_model["stats"]},
            "leveling-ledger": gm_model["leveling_ledger"],
            "background-origin": gm_model["background_origin"],
            "paths-subpaths": gm_model["paths_subpaths"],
            "spheres-talents": gm_model["spheres_talents"],
            "insights": gm_model["insights"],
            "actions": gm_model["actions"],
            "forged-techniques": gm_model["forged_techniques"],
            "martial-manuals-recorded-arts": gm_model["recorded_arts"],
            "immortal-arts": gm_model["immortal_arts"],
            "foundation": gm_model["foundation"],
            "method": gm_model["method"],
            "companions-spirits": gm_model["spirit_companions"],
            "equipment": gm_model["equipment_resources_states"].get("equipment"),
            "resources-states-suppression": gm_model["equipment_resources_states"],
            "dao-i-ching": gm_model["dao_i_ching"],
            "diagnostics": gm_model["diagnostics"],
        }
        for tab_id, label in GM_SCREEN_TAB_CONTRACT:
            display_rows.append({"tab_id":tab_id,"tab":tab_id,"label":label,"value":deepcopy(tab_values[tab_id]),"structured":True,"source_model":"Tianxia_GM_Character_Model_v1"})
        tabs = {"schema_version":"TianxiaFoundry.CharacterGMTabCoverage.v1","status":"COMPLETE_CHARACTER_GM_PROFILE","rows":display_rows,"required_tabs":[tab_id for tab_id, _label in GM_SCREEN_TAB_CONTRACT]}
        return gm_model, view, tabs

    def _validate_models(self, gm_model: dict[str, Any], view: dict[str, Any], tabs: dict[str, Any]) -> dict[str, Any]:
        model_schema, model_schema_sha = self._model_schema()
        model_errors = sorted(error.message for error in Draft202012Validator(model_schema).iter_errors(gm_model))
        pinned_schema_path = self.factory_root / "04_SCHEMAS" / "gm_character_view_model.schema.json"
        pinned_schema = json.loads(pinned_schema_path.read_text(encoding="utf-8"))
        view_errors = sorted(error.message for error in Draft202012Validator(pinned_schema).iter_errors(view))
        diagnostics: list[dict[str, Any]] = []
        for message in model_errors: diagnostics.append({"code":"GM_MODEL_PROFILE_SCHEMA_ERROR","message":message})
        for message in view_errors: diagnostics.append({"code":"GM_VIEW_MODEL_PINNED_SCHEMA_ERROR","message":message})
        serialized = canonical_json({"gm_model":gm_model,"view":view,"tabs":tabs})
        for token in ("[object Object]","TBD","TODO","placeholder"):
            if token.casefold() in serialized.casefold(): diagnostics.append({"code":"GM_CANDIDATE_FORBIDDEN_PLACEHOLDER","token":token})
        action_ids = [row.get("record_id") for row in gm_model.get("actions") or []]
        if len(action_ids) != len(set(action_ids)): diagnostics.append({"code":"GM_CANDIDATE_ACTION_ARRAY_DUPLICATE"})
        if any(row.get("display_only_not_execution_authority") is not True and row.get("combat_execution_status") not in {"SUPPORTED","NOT_APPLICABLE"} for row in gm_model.get("actions") or []):
            diagnostics.append({"code":"GM_CANDIDATE_FALSE_EXECUTION_CLAIM"})
        expected_tabs = [tab_id for tab_id, _label in GM_SCREEN_TAB_CONTRACT]
        actual_tabs = [row.get("tab_id") for row in tabs.get("rows") or [] if isinstance(row, dict)]
        if actual_tabs != expected_tabs or tabs.get("required_tabs") != expected_tabs:
            diagnostics.append({"code":"GM_CANDIDATE_TAB_CONTRACT_INVALID","expected":expected_tabs,"actual":actual_tabs})
        if diagnostics:
            raise FoundryError("CHARACTER_GM_COMMAND5_AUDIT_FAILED", "The Character/GM model candidate failed schema or deep-audit validation.", details={"diagnostics":diagnostics})
        return {"schema_version":"TianxiaFoundry.CharacterGMCommand5DeepAudit.v1","valid":True,"status":"PASS_CHARACTER_GM_COMMAND_5_AUDIT","gm_model_profile_schema_sha256":model_schema_sha,"pinned_view_model_schema_sha256":sha256_file(pinned_schema_path),"tab_count":len(tabs.get("rows") or []),"action_display_count":len(action_ids),"array_preservation":True,"placeholder_leakage":False,"false_combat_claim":False,"consumer_verification":"NOT_ATTEMPTED"}

    @staticmethod
    def _feature_coverage_projection(master: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """Project feature coverage from the sealed master ledger only.

        Path and Subpath features are allocated in ``features``; a Cultivation
        Insight the character took at CL4/CL8/CL12/CL16/CL19 is allocated in
        ``cultivation_insight_occurrences`` (mirrored by ``insights``), so the
        Insights tab is projected from those rows.  Without them the tab read
        "no coverage" for every character who did take an Insight.
        """

        if not isinstance(master, Mapping):
            return [], [], [], []
        path_rows: list[dict[str, Any]] = []
        subpath_rows: list[dict[str, Any]] = []
        features = master.get("features")
        for feature in features if isinstance(features, list) else []:
            if not isinstance(feature, Mapping):
                continue
            feature_id = feature.get("feature_id") or feature.get("canonical_index_id") or feature.get("id")
            if not isinstance(feature_id, str) or not feature_id:
                continue
            category = str(feature.get("category") or "").casefold()
            row = CharacterGMCommand5Profile._coverage_row(
                feature_id,
                feature,
                display_name=feature.get("display_name") or feature.get("name"),
                acquisition_cl=feature.get("gained_at_cl") or feature.get("acquired_at_character_cl"),
            )
            (subpath_rows if "subpath" in category else path_rows).append(row)
        # A Cultivation Insight the character took at CL4/CL8/CL12/CL16/CL19 is
        # allocated in ``cultivation_insight_occurrences`` (mirrored by
        # ``insights``), never in ``features``, so the Insights coverage needs its
        # own source.  It used to be projected as a hard-coded empty list, which
        # reported "no coverage" even for a character who really had an Insight.
        occurrences = master.get("cultivation_insight_occurrences")
        if not isinstance(occurrences, list):
            occurrences = master.get("insights")
        insight_rows: list[dict[str, Any]] = []
        for insight in occurrences if isinstance(occurrences, list) else []:
            if not isinstance(insight, Mapping):
                continue
            insight_id = insight.get("insight_id") or insight.get("canonical_insight_id") or insight.get("id")
            if not isinstance(insight_id, str) or not insight_id:
                continue
            insight_rows.append(
                CharacterGMCommand5Profile._coverage_row(
                    insight_id,
                    insight,
                    display_name=insight.get("name") or insight.get("display_name"),
                    acquisition_cl=insight.get("gained_at_cl") or insight.get("acquisition_cl"),
                )
            )
        return path_rows, subpath_rows, insight_rows, []

    @staticmethod
    def _coverage_row(
        group_id: str,
        ledger_row: Mapping[str, Any],
        *,
        display_name: Any = None,
        acquisition_cl: Any = None,
    ) -> dict[str, Any]:
        """One source-backed coverage row, shared by every coverage section.

        ``group_id`` names the printed Path feature, Subpath feature or Insight
        the row covers.  The ledger's own display fields are carried through so
        the row still reads as plain text after the character sheet projects the
        coverage document; only the printed source ids are added.
        """
        packet_ids = ledger_row.get("source_packet_ids")
        if not isinstance(packet_ids, list):
            packet_ids = []
        row: dict[str, Any] = {
            "feature_group_id": group_id,
            "expected_feature_ids": [group_id],
            "covered_feature_ids": [group_id],
            "coverage_status": "source_backed",
            "source_packet_ids": deepcopy(packet_ids),
            "source": "Character_Master_Ledger.json",
        }
        if isinstance(display_name, str) and display_name:
            row["display_name"] = display_name
        if isinstance(acquisition_cl, int):
            row["acquisition_cl"] = acquisition_cl
        return row

    @staticmethod
    def _signature_loadout_projection(action_surface: Any) -> tuple[dict[str, Any], bool]:
        """Derive Signature_Loadout solely from the reviewed action surface."""

        if not isinstance(action_surface, Mapping) or action_surface.get("execution_authority") is not True:
            return {"schema": _R1F_SIGNATURE_SCHEMA, "actions": [], "status": "NOT_PROVEN"}, False
        actions = action_surface.get("actions")
        loadout_ids = action_surface.get("signature_loadout_record_ids")
        if not isinstance(actions, list) or not isinstance(loadout_ids, list) or not 10 <= len(loadout_ids) <= 14 or len(loadout_ids) != len(set(loadout_ids)):
            return {"schema": _R1F_SIGNATURE_SCHEMA, "actions": [], "status": "INVALID"}, False
        by_record = {row.get("record_id"): row for row in actions if isinstance(row, Mapping) and isinstance(row.get("record_id"), str)}
        if len(by_record) != len(actions) or any(record_id not in by_record for record_id in loadout_ids):
            return {"schema": _R1F_SIGNATURE_SCHEMA, "actions": [], "status": "INVALID"}, False
        rows = []
        for priority, record_id in enumerate(loadout_ids, 1):
            row = by_record[record_id]
            rows.append({
                "action_id": row.get("action_id"),
                "record_id": record_id,
                "priority": priority,
                "name": row.get("name"),
                "source_packet_ids": deepcopy(row.get("source_packet_ids") or []),
            })
        if any(not isinstance(row.get("action_id"), str) or not row["action_id"] for row in rows):
            return {"schema": _R1F_SIGNATURE_SCHEMA, "actions": [], "status": "INVALID"}, False
        return {
            "schema": _R1F_SIGNATURE_SCHEMA,
            "character_id": action_surface.get("project_id"),
            "actions": rows,
            "status": "SOURCE_BOUND",
            "execution_authority": False,
        }, True

    @staticmethod
    def _expected_counts(
        gm_model: Mapping[str, Any],
        master: Mapping[str, Any],
        action_surface: Mapping[str, Any],
        *,
        display_ers: Mapping[str, Any] | None = None,
    ) -> dict[str, int]:
        def count_list(value: Any) -> int:
            return len(value) if isinstance(value, list) else 0

        advancement = master.get("advancement") if isinstance(master.get("advancement"), Mapping) else {}
        levels = gm_model.get("leveling_ledger")
        if not isinstance(levels, list):
            levels = advancement.get("levels") if isinstance(advancement, Mapping) else []
        spheres = master.get("spheres")
        talents = master.get("talents")
        if not isinstance(spheres, list):
            spheres = []
        if not isinstance(talents, list):
            talents = []
        ers = display_ers if isinstance(display_ers, Mapping) else gm_model.get("equipment_resources_states")
        equipment = ers.get("equipment") if isinstance(ers, Mapping) else []
        states = ers.get("states") if isinstance(ers, Mapping) else []
        return {
            "level_rows": count_list(levels),
            "spheres": count_list(spheres),
            "talents": count_list(talents),
            "actions": count_list(action_surface.get("actions")),
            "training_sources": count_list(gm_model.get("training_sources")),
            "forged_techniques": count_list(gm_model.get("forged_techniques")),
            "preserved_forged_expressions": count_list(gm_model.get("preserved_forged_expressions")),
            "emergency_technique_seeds": count_list(gm_model.get("emergency_technique_seeds")),
            "recorded_arts": count_list(gm_model.get("recorded_arts")),
            "immortal_arts": count_list(gm_model.get("immortal_arts")),
            "equipment": count_list(equipment),
            "states": count_list(states),
        }

    @staticmethod
    def _semantic_report(
        master: Any,
        packets: Any,
        coverage: Any,
        diagnostics: Any,
        action_surface: Any,
        signature: Mapping[str, Any],
        signature_proven: bool,
    ) -> dict[str, Any]:
        ledger_sha = sha256_json(master)
        packets_sha = sha256_json(packets)
        proven = (
            isinstance(master, Mapping)
            and isinstance(packets, Mapping)
            and isinstance(coverage, Mapping)
            and coverage.get("required_provenance_complete") is True
            and coverage.get("unproven_required_nodes") == []
            and coverage.get("blocked_required_sections") == []
            and isinstance(diagnostics, Mapping)
            and diagnostics.get("valid") is True
            and diagnostics.get("diagnostics") == []
            and isinstance(action_surface, Mapping)
            and action_surface.get("execution_authority") is True
            and action_surface.get("global_combat_readiness") is False
            and action_surface.get("unresolved") == []
            and signature_proven
        )
        if not proven:
            return {
                "schema": _R1F_SEMANTIC_SCHEMA,
                "schema_version": _R1F_SEMANTIC_SCHEMA,
                "verdict": "BLOCKED_NOT_PROVEN",
                "release_ready": False,
                "counts": {"critical": 1, "high": 0, "warning": 0},
                "issues": [{"severity": "critical", "code": "SEMANTIC_AUTHORITY_NOT_PROVEN", "message": "The complete source-bound Command 4 action surface is not available."}],
                "ledger_sha256": ledger_sha,
                "rules_packets_sha256": packets_sha,
                "signature_loadout": deepcopy(signature.get("actions") or []),
            }
        return {
            "schema": _R1F_SEMANTIC_SCHEMA,
            "schema_version": _R1F_SEMANTIC_SCHEMA,
            "verdict": "PASS_HF05ZVK_R1F_SEMANTIC_VALIDATION",
            "release_ready": True,
            "counts": {"critical": 0, "high": 0, "warning": 0},
            "issues": [],
            "ledger_sha256": ledger_sha,
            "rules_packets_sha256": packets_sha,
            "signature_loadout": deepcopy(signature.get("actions") or []),
            "build_mode": "production",
        }

    def _surfaces(self, *, project: dict[str, Any], sheet_response: dict[str, Any], workspace_root: Path, workspace_status: dict[str, Any], profile: dict[str, Any], profile_contract_sha: str, command4: dict[str, Any]) -> dict[str, Any]:
        master = json.loads(self.projections.artifact(project["project_id"], "Character_Master_Ledger.json").read_text(encoding="utf-8"))
        gm_model, view, tabs = self._models(project=project,sheet_response=sheet_response,workspace_root=workspace_root,workspace_status=workspace_status,profile=profile,profile_contract_sha=profile_contract_sha,command4=command4,master=master)
        action_surface = self._action_surface(workspace_root, gm_model["actions"])
        if action_surface.get("execution_authority") is True:
            # An explicit reviewed overlay owns the complete action records;
            # the owner-sheet index is only a display fallback for the default
            # non-authoritative path.  Project reviewed actions into the
            # consumer envelope before every model/tab audit and count is
            # derived, while procedures stay in Procedure_Ledger.json.
            surface_actions = self._display_actions_from_surface(action_surface)
            gm_model["actions"] = deepcopy(surface_actions)
            view["actions"] = deepcopy(surface_actions)
            gm_model["diagnostics"]["display_only_record_count"] = len(surface_actions)
            for diagnostic in view.get("diagnostics") or []:
                if isinstance(diagnostic, Mapping) and "display_only_records" in diagnostic:
                    diagnostic["display_only_records"] = len(surface_actions)
            for tab in tabs.get("rows") or []:
                if isinstance(tab, dict) and tab.get("tab_id") == "actions":
                    tab["value"] = deepcopy(surface_actions)
        audit = self._validate_models(gm_model, view, tabs)
        snapshot = sheet_response["owner_character_sheet"]
        projections = {name:json.loads(self.projections.artifact(project["project_id"],name).read_text(encoding="utf-8")) for name in ("Rules_Selection_Packets.json","Projection_Provenance_Map.json","Projection_Coverage_Report.json","Projection_Diagnostics.json")}
        projections["Character_Master_Ledger.json"] = master
        packets = projections["Rules_Selection_Packets.json"]
        coverage = projections["Projection_Coverage_Report.json"]
        projection_diagnostics = projections["Projection_Diagnostics.json"]
        signature, signature_proven = self._signature_loadout_projection(action_surface)
        path_coverage, subpath_coverage, insight_coverage, companion_coverage = self._feature_coverage_projection(master)
        # Keep the v1 source model's typed container intact.  Only the
        # consumer-facing sidecars and their count projection receive the
        # array-safe derived representation.
        display_ers = self._display_resource_container(snapshot)
        expected_counts = self._expected_counts(
            gm_model,
            master,
            action_surface,
            display_ers=display_ers,
        )
        semantic = self._semantic_report(master, packets, coverage, projection_diagnostics, action_surface, signature, signature_proven)
        surfaces: dict[str, Any] = {
            "C2B3_Build_Profile.json":{"schema_version":"TianxiaFoundry.FactoryBuildProfileSelection.v1","profile":profile,"profile_contract_sha256":profile_contract_sha,"default_legacy_behavior_preserved":True},
            "C2B3_Character_GM_Command_4_Validation.json":command4,
            "Tianxia_GM_Character_Model_v1.json":gm_model,
            "Tianxia_GM_Character_View_Model_v2.json":view,
            "GM_Screen_Tab_Expectation_Manifest.json":{**tabs,"expected_counts":expected_counts},
            "GM_Screen_Display_Rows.json":{"schema_version":"TianxiaFoundry.CharacterGMDisplayRows.v1","rows":deepcopy(tabs["rows"])},
            "GM_Screen_Projection_Rows.json":{"schema_version":"TianxiaFoundry.CharacterGMProjectionRows.v1","rows":deepcopy(tabs["rows"]),"source":"C2B3 CHARACTER_GM_MODEL deterministic profile"},
            "Character_Master_Ledger.json":projections["Character_Master_Ledger.json"],
            "Rules_Selection_Packets.json":projections["Rules_Selection_Packets.json"],
            "Projection_Provenance_Map.json":projections["Projection_Provenance_Map.json"],
            "Projection_Coverage_Report.json":projections["Projection_Coverage_Report.json"],
            "Projection_Diagnostics.json":projections["Projection_Diagnostics.json"],
            "Tianxia_Owner_Character_Sheet_v1.json":snapshot,
            "Leveling_Ledger.json":{"schema_version":"TianxiaFoundry.CharacterGMLevelingLedger.v1","levels":deepcopy(gm_model["leveling_ledger"])},
            "Background_Origin_Ledger.json":{"schema_version":"TianxiaFoundry.CharacterGMBackgroundOrigin.v1","background_origin":deepcopy(gm_model["background_origin"])},
            "Selected_Spheres.json":{"schema_version":"TianxiaFoundry.CharacterGMSelectedSpheres.v1","spheres":deepcopy((snapshot.get("selected_record_sections") or {}).get("spheres") or [])},
            "Talent_Source_Ledger.json":{"schema_version":"TianxiaFoundry.CharacterGMTalentSources.v1","background_talents":deepcopy((snapshot.get("selected_record_sections") or {}).get("background_talent") or []),"learned_talents":deepcopy((snapshot.get("selected_record_sections") or {}).get("talents") or [])},
            "Complete_Action_Surface.json":deepcopy(action_surface),
            "Manual_Lineage_Record.json":{"schema_version":"TianxiaFoundry.CharacterGMTrainingSources.v1","training_sources":deepcopy(gm_model["training_sources"])},
            "Martial_Arts_and_Manuals.json":{"schema_version":"TianxiaFoundry.CharacterGMManuals.v1","none_state":deepcopy(gm_model["recorded_arts_none_state"]),"manuals":deepcopy(gm_model["recorded_arts"])},
            "Foundation_Detail_Ledger.json":{"schema_version":"TianxiaFoundry.CharacterGMFoundation.v1","foundation":deepcopy(gm_model["foundation"])},
            "Cultivation_Method_Profile.json":{"schema_version":"TianxiaFoundry.CharacterGMMethod.v1","method":deepcopy(gm_model["method"])},
            "Dao_IChing_Combat_Profile.json":{"schema_version":"TianxiaFoundry.CharacterGMDaoIChing.v1","dao":deepcopy(gm_model["dao_i_ching"].get("dao")),"i_ching":deepcopy(gm_model["dao_i_ching"].get("i_ching")),"dao_i_ching":deepcopy(gm_model["dao_i_ching"]),"classification":"GM_GUIDANCE_ONLY","execution_authority":False},
            "Equipment_Ledger.json":{"schema_version":"TianxiaFoundry.CharacterGMEquipment.v1","equipment":deepcopy(display_ers.get("equipment") or []),"none_state":deepcopy(display_ers.get("equipment_none_state")),"source":"Character_Master_Ledger.json"},
            "Equipment_Ledger_Legacy.json":{"schema_version":"TianxiaFoundry.CharacterGMEquipmentLegacy.v1","equipment":deepcopy(display_ers.get("equipment") or []),"none_state":deepcopy(display_ers.get("equipment_none_state")),"source":"Character_Master_Ledger.json"},
            "Selected_Item_GM_Projection.json":{"schema_version":"TianxiaFoundry.ItemGMScreenSelectedProjection.v1","items":[] ,"status":"SOURCE_EXPLICIT_NONE"},
            "Item_Execution_Coverage.json":{"schema_version":"TianxiaFoundry.ItemExecutionCoverage.v1","coverage":[],"items":[],"status":"SOURCE_EXPLICIT_NONE"},
            "Selected_Rule_Execution_Coverage.json":{"schema_version":"TianxiaFoundry.SelectedRuleExecutionCoverage.v1","coverage":deepcopy(master.get("selected_rule_execution_coverage") or []),"status":"SOURCE_PROJECTED" if master.get("selected_rule_execution_coverage") else "SOURCE_EXPLICIT_NONE"},
            "Feature_Coverage_Manifest.json":{"schema_version":"TianxiaFoundry.FeatureCoverageManifest.v1","source_of_truth":"Character_Master_Ledger.json","path_feature_coverage":deepcopy(path_coverage),"subpath_feature_coverage":deepcopy(subpath_coverage),"insight_coverage":deepcopy(insight_coverage),"companion_coverage":deepcopy(companion_coverage),"item_coverage":[]},
            "Path_Feature_Coverage.json":{"schema_version":"TianxiaFoundry.PathFeatureCoverage.v1","coverage":deepcopy(path_coverage),"source":"Character_Master_Ledger.json"},
            "Subpath_Feature_Coverage.json":{"schema_version":"TianxiaFoundry.SubpathFeatureCoverage.v1","coverage":deepcopy(subpath_coverage),"source":"Character_Master_Ledger.json"},
            "Insight_Execution_Coverage.json":{"schema_version":"TianxiaFoundry.InsightExecutionCoverage.v1","coverage":deepcopy(insight_coverage),"source":"Character_Master_Ledger.json"},
            "Companion_Execution_Coverage.json":{"schema_version":"TianxiaFoundry.CompanionExecutionCoverage.v1","coverage":deepcopy(companion_coverage),"companions":[],"source":"Character_Master_Ledger.json"},
            "Source_CL_and_Realm_Suppression.json":{"schema_version":"TianxiaFoundry.SourceCLRealmSuppression.v1","character_cl":(master.get("character") or {}).get("cl") if isinstance(master.get("character"), Mapping) else None,"status":"SOURCE_EXPLICIT_NONE","rule_exports":[],"source":"Character_Master_Ledger.json"},
            "Modifier_Ledger.json":{"schema_version":"TianxiaFoundry.ModifierLedger.v1","modifiers":deepcopy(master.get("modifiers") or []),"status":"SOURCE_PROJECTED" if master.get("modifiers") else "SOURCE_EXPLICIT_NONE","source":"Character_Master_Ledger.json"},
            "Procedure_Ledger.json":{"schema_version":"TianxiaFoundry.ProcedureLedger.v1","procedures":deepcopy(action_surface.get("procedures") or []),"source":"Complete_Action_Surface.json"},
            "Passive_Statistic_Ledger.json":{"schema_version":"TianxiaFoundry.PassiveStatisticLedger.v1","passive_statistics":deepcopy(master.get("passive_statistics") or []),"status":"SOURCE_PROJECTED" if master.get("passive_statistics") else "SOURCE_EXPLICIT_NONE","source":"Character_Master_Ledger.json"},
            "Permission_Record_Ledger.json":{"schema_version":"TianxiaFoundry.PermissionRecordLedger.v1","permission_records":deepcopy(master.get("permission_records") or []),"status":"SOURCE_PROJECTED" if master.get("permission_records") else "SOURCE_EXPLICIT_NONE","source":"Character_Master_Ledger.json"},
            "State_Effect_Registry.json":{"schema_version":"TianxiaFoundry.StateEffectRegistry.v1","states":deepcopy(display_ers.get("states") or []),"status":"SOURCE_EXPLICIT_NONE" if not display_ers.get("states") else "SOURCE_PROJECTED","source":"Character_Master_Ledger.json"},
            "Forged_Techniques.json":{"schema_version":"TianxiaFoundry.CharacterGMForgedTechniques.v1","none_state":deepcopy(gm_model["forged_techniques_none_state"]),"forged_techniques":deepcopy(gm_model["forged_techniques"])},
            "Immortal_Arts.json":{"schema_version":"TianxiaFoundry.CharacterGMImmortalArts.v1","none_state":deepcopy(gm_model["immortal_arts_none_state"]),"immortal_arts":deepcopy(gm_model["immortal_arts"])},
            "AI_Combat_Behavior_Profile.json":{"schema_version":"TianxiaFoundry.CharacterGMDescriptiveAI.v1","profile":deepcopy(gm_model["ai_behavior"]),"not_executable_controller_policy":True},
            "Semantic_Validation_Report.json":semantic,
            "Signature_Loadout.json":signature,
            "C2B3_Character_GM_Live_Render_Seal.json":{"schema_version":"TianxiaFoundry.CharacterGMLiveRenderSeal.v1","status":"PASS_STATIC_CHARACTER_GM_RENDER_SEAL","evidence_boundary":"static_character_gm_candidate","consumer_verification":"NOT_ATTEMPTED","tab_manifest_sha256":sha256_json(tabs),"gm_model_sha256":sha256_json(gm_model),"view_model_sha256":sha256_json(view),"array_preservation":True,"readable_structured_values":True},
            "C2B3_Character_GM_Deep_Audit.json":audit,
            "Build_Reconciliation.json":{"schema_version":"TianxiaFoundry.CharacterGMBuildReconciliation.v1","status":GM_CANDIDATE_READY,"build_profile":CHARACTER_GM_PROFILE,"all_derived_from_canonical_or_sealed_authoring":True,"manual_derived_file_edits_allowed":False,"legacy_full_execution_status":"BLOCKED_NOT_RUN_COMBAT_EXECUTION_INCOMPLETE","command6_status":"NOT_RUN","gm_export_available":False},
        }
        missing_r2k_sidecars = set(R2K_REQUIRED_SIDECAR_NAMES) - set(surfaces)
        if missing_r2k_sidecars:
            raise FoundryError(
                "CHARACTER_GM_R2K_SIDECAR_CONTRACT_INVALID",
                "The Character/GM projection did not produce every bundled R2K sidecar.",
                details={"missing": sorted(missing_r2k_sidecars)},
            )
        return surfaces

    @classmethod
    def _snapshot_reviewed_overlay(
        cls,
        reviewed_overlay_root: Path,
        *,
        output_root: Path,
    ) -> tuple[Path, Path]:
        """Copy an explicit overlay into a private, descriptor-detached root."""

        if not isinstance(reviewed_overlay_root, Path):
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_INVALID", "The reviewed overlay path is internal-only and must be a Path.")
        output_root = Path(output_root)
        output_root.parent.mkdir(parents=True, exist_ok=True)
        staging_parent = Path(tempfile.mkdtemp(prefix=".reviewed-command4-", dir=str(output_root.parent)))
        snapshot = staging_parent / "overlay"
        try:
            cls._snapshot_tree_no_follow(
                reviewed_overlay_root,
                snapshot,
                code_prefix="CHARACTER_GM_REVIEWED_OVERLAY",
            )
            return snapshot, staging_parent
        except BaseException:
            shutil.rmtree(staging_parent, ignore_errors=True)
            raise

    @classmethod
    def _snapshot_reviewed_inputs(
        cls,
        base_workspace: Path,
        reviewed_overlay_root: Path,
        *,
        output_root: Path,
    ) -> tuple[Path, Path, Path]:
        """Snapshot both explicit inputs under one private staging parent."""

        if not isinstance(base_workspace, Path) or not isinstance(reviewed_overlay_root, Path):
            raise FoundryError("CHARACTER_GM_REVIEWED_OVERLAY_INVALID", "Reviewed Command 5 inputs must be Path values.")
        output_root = Path(output_root)
        output_root.parent.mkdir(parents=True, exist_ok=True)
        staging_parent = Path(tempfile.mkdtemp(prefix=".reviewed-command4-", dir=str(output_root.parent)))
        base_snapshot = staging_parent / "base"
        overlay_snapshot = staging_parent / "overlay"
        try:
            cls._snapshot_tree_no_follow(
                base_workspace,
                base_snapshot,
                code_prefix="CHARACTER_GM_REVIEWED_OVERLAY_BASE",
            )
            cls._snapshot_tree_no_follow(
                reviewed_overlay_root,
                overlay_snapshot,
                code_prefix="CHARACTER_GM_REVIEWED_OVERLAY",
            )
            return base_snapshot, overlay_snapshot, staging_parent
        except BaseException:
            shutil.rmtree(staging_parent, ignore_errors=True)
            raise

    @classmethod
    def _verify_workspace_snapshot(
        cls,
        snapshot: Path,
        *,
        workspace_status: Mapping[str, Any],
        expected_manifest: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Verify a detached base snapshot before it becomes Command 4 input."""

        cls._verify_checksum_ledger(snapshot, code_prefix="CHARACTER_GM_WORKSPACE_SNAPSHOT_CHECKSUMS")
        actual = sha256_json(cls._tree_hashes(snapshot, include_checksum_ledger=True))
        expected = workspace_status.get("workspace_sha256")
        if actual != expected:
            raise FoundryError(
                "CHARACTER_GM_WORKSPACE_SNAPSHOT_MISMATCH",
                "The detached sealed workspace snapshot does not match its pointer identity.",
                details={"expected": expected, "actual": actual},
            )
        try:
            manifest = json.loads((snapshot / "Workspace_Manifest.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise FoundryError(
                "CHARACTER_GM_WORKSPACE_SNAPSHOT_MANIFEST_INVALID",
                "The detached sealed workspace snapshot manifest cannot be read.",
            ) from exc
        if not isinstance(manifest, Mapping) or dict(manifest) != dict(expected_manifest):
            raise FoundryError(
                "CHARACTER_GM_WORKSPACE_SNAPSHOT_MISMATCH",
                "The detached sealed workspace snapshot manifest changed during handoff.",
            )
        return dict(manifest)

    def _command5_build_from_source(
        self,
        project_id: str,
        *,
        output_root: Path,
        profile: dict[str, Any],
        profile_contract_sha: str,
        command4: dict[str, Any],
        project: dict[str, Any],
        sheet_response: dict[str, Any],
        workspace_status: dict[str, Any],
        base_workspace: Path,
        source_workspace: Path,
        reviewed_overlay: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if output_root.exists():
            if output_root.is_symlink():
                raise FoundryError("CHARACTER_GM_COMMAND5_OUTPUT_INVALID", "The Command 5 output root must not be a symbolic link.")
            shutil.rmtree(output_root)
        workspace = output_root / "workspace"
        shutil.copytree(source_workspace, workspace)
        if reviewed_overlay is not None:
            self._verify_checksum_ledger(
                source_workspace,
                code_prefix="CHARACTER_GM_REVIEWED_OVERLAY_SNAPSHOT_CHECKSUMS",
            )
            source_snapshot_hash = sha256_json(self._tree_hashes(source_workspace, include_checksum_ledger=True))
            if source_snapshot_hash != reviewed_overlay.get("overlay_tree_sha256"):
                raise FoundryError(
                    "CHARACTER_GM_REVIEWED_OVERLAY_SNAPSHOT_CHANGED",
                    "The trusted reviewed overlay snapshot changed after verification.",
                )
            self._verify_checksum_ledger(
                workspace,
                code_prefix="CHARACTER_GM_REVIEWED_OVERLAY_COPY_CHECKSUMS",
            )
            copied_snapshot_hash = sha256_json(self._tree_hashes(workspace, include_checksum_ledger=True))
            if copied_snapshot_hash != source_snapshot_hash:
                raise FoundryError(
                    "CHARACTER_GM_REVIEWED_OVERLAY_COPY_MISMATCH",
                    "The Command 5 workspace copy is not byte-equivalent to the verified overlay snapshot.",
                )
            self._verify_checksum_ledger(
                base_workspace,
                code_prefix="CHARACTER_GM_WORKSPACE_CHECKSUMS",
            )
            current_base_hash = sha256_json(self._tree_hashes(base_workspace, include_checksum_ledger=True))
            if (
                current_base_hash != reviewed_overlay.get("source_workspace_sha256")
                or current_base_hash != workspace_status.get("workspace_sha256")
            ):
                raise FoundryError(
                    "CHARACTER_GM_WORKSPACE_STALE",
                    "The sealed Factory workspace changed before Command 5 consumed the reviewed overlay.",
                )
        build = workspace / "Build"
        surfaces = self._surfaces(
            project=project,
            sheet_response=sheet_response,
            workspace_root=source_workspace,
            workspace_status=workspace_status,
            profile=profile,
            profile_contract_sha=profile_contract_sha,
            command4=command4,
        )
        compiler = _load_module(self.factory_root / "05_COMPILER" / "compile_character.py", "tianxia_pinned_compile_character_c2b3")
        compiler.write_build(build, surfaces)
        candidate = output_root / "candidate.zip"
        seal_tool = self.factory_root / "07_TOOLS" / "seal_character_zip.py"
        # The copied Factory root can exceed the legacy Windows MAX_PATH limit.
        # The sealer receives absolute inputs and does not require that long path
        # as its process working directory, so launch it from the stable source
        # root while retaining the exact pinned tool and build identities.
        completed = subprocess.run(
            [
                str(helper_python_executable()),
                str(seal_tool),
                "--build",
                str(build),
                "--output",
                str(candidate),
                "--classification",
                "COMMAND_5_GM_SCREEN_CANDIDATE_READY",
            ],
            cwd=self.db.settings.root_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        if completed.returncode != 0 or not candidate.is_file():
            raise FoundryError(
                "CHARACTER_GM_COMMAND5_SEAL_FAILED",
                "The pinned deterministic candidate sealer failed.",
                details={"exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr},
            )
        self._canonicalize_candidate_zip(candidate)
        model_path = build / "Tianxia_GM_Character_Model_v1.json"
        view_path = build / "Tianxia_GM_Character_View_Model_v2.json"
        audit_path = build / "C2B3_Character_GM_Deep_Audit.json"
        manifest_path = build / "PACKAGE_MANIFEST.json"
        report = {
            "schema_version": "TianxiaFoundry.CharacterGMCommand5Verification.v1",
            "project_id": project_id,
            "projection_id": self.projections.status(project_id).get("projection_id"),
            "status": GM_CANDIDATE_READY,
            "build_profile": profile,
            "build_profile_contract_sha256": profile_contract_sha,
            "character_gm_command4": command4,
            "legacy_full_command4_status": "BLOCKED_NOT_RUN_COMBAT_EXECUTION_INCOMPLETE",
            "workspace": str(workspace),
            "build": str(build),
            "candidate_zip": str(candidate),
            "candidate_sha256": sha256_file(candidate),
            "gm_model_path": str(model_path),
            "gm_model_sha256": sha256_file(model_path),
            "gm_view_model_sha256": sha256_file(view_path),
            "deep_audit_sha256": sha256_file(audit_path),
            "build_manifest_sha256": sha256_file(manifest_path),
            "command6_status": "NOT_RUN",
            "gm_screen_consumer_verification": "NOT_ATTEMPTED",
            "gm_export_available": False,
            "combat_execution": "NOT_ATTEMPTED",
            "seal_run": {"exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr},
        }
        if reviewed_overlay is not None:
            report["reviewed_command4_overlay"] = deepcopy(reviewed_overlay)
        candidate_root = self.db.settings.data_dir / "factory_candidates" / project_id
        candidate_root.mkdir(parents=True, exist_ok=True)
        durable = candidate_root / report["candidate_sha256"]
        if durable.exists():
            if durable.is_symlink():
                raise FoundryError("CHARACTER_GM_COMMAND5_OUTPUT_INVALID", "The durable Command 5 candidate path must not be a symbolic link.")
            shutil.rmtree(durable)
        shutil.copytree(output_root, durable)
        durable_build = durable / "workspace" / "Build"
        pointer = {
            **report,
            "workspace": str(durable / "workspace"),
            "build": str(durable_build),
            "candidate_zip": str(durable / "candidate.zip"),
            "gm_model_path": str(durable_build / "Tianxia_GM_Character_Model_v1.json"),
            "gm_view_model_path": str(durable_build / "Tianxia_GM_Character_View_Model_v2.json"),
            "deep_audit_path": str(durable_build / "C2B3_Character_GM_Deep_Audit.json"),
            "build_manifest_path": str(durable_build / "PACKAGE_MANIFEST.json"),
        }
        _write_json(candidate_root / "current.json", pointer)
        with self.db.transaction() as conn:
            projection_id = report["projection_id"]
            conn.execute(
                "UPDATE projection_runs SET command5_status=?,candidate_sha256=?,diagnostics_json=? WHERE projection_id=?",
                (GM_CANDIDATE_READY, report["candidate_sha256"], canonical_json([]), projection_id),
            )
            conn.execute("UPDATE projects SET compile_status=? WHERE project_id=?", (GM_CANDIDATE_READY, project_id))
        return pointer

    def command5(
        self,
        project_id: str,
        *,
        output_root: Path,
        reviewed_overlay_root: Path | None = None,
    ) -> dict[str, Any]:
        profile, profile_contract_sha = self.select_profile(CHARACTER_GM_PROFILE)
        if reviewed_overlay_root is None:
            # Preserve the established default path byte-for-byte: Command 4
            # validates the sealed base, then Command 5 consumes that base.
            command4 = self.validate_command4(project_id, profile_id=CHARACTER_GM_PROFILE)
            project = self.projects.get_project(project_id)["project"]
            sheet_response = self.sheets.sheet(project_id)
            workspace_status, base_workspace, base_manifest = self._workspace_identity(project_id)
            return self._command5_build_from_source(
                project_id,
                output_root=output_root,
                profile=profile,
                profile_contract_sha=profile_contract_sha,
                command4=command4,
                project=project,
                sheet_response=sheet_response,
                workspace_status=workspace_status,
                base_workspace=base_workspace,
                source_workspace=base_workspace,
                reviewed_overlay=None,
            )

        staging_parent: Path | None = None
        try:
            # Read the pointer once, then detach both the sealed base and the
            # caller-supplied overlay before any Command 4 content validation.
            # All later reads use these descriptor-verified snapshots; the
            # mutable caller path and live base are never consumed.
            workspace_status, base_workspace, base_manifest = self._workspace_identity(project_id)
            base_snapshot, source_workspace, staging_parent = self._snapshot_reviewed_inputs(
                base_workspace,
                reviewed_overlay_root,
                output_root=output_root,
            )
            base_snapshot_manifest = self._verify_workspace_snapshot(
                base_snapshot,
                workspace_status=workspace_status,
                expected_manifest=base_manifest,
            )
            project = self.projects.get_project(project_id)["project"]
            sheet_response = self.sheets.sheet(project_id)
            command4 = self.validate_command4(
                project_id,
                profile_id=CHARACTER_GM_PROFILE,
                reviewed_overlay_root=source_workspace,
                _workspace_snapshot=base_snapshot,
                _workspace_status_snapshot=workspace_status,
                _workspace_manifest_snapshot=base_snapshot_manifest,
            )
            # The returned receipt is the only overlay authority passed into
            # the builder.  The caller's mutable path is never consumed.
            reviewed_overlay = deepcopy(command4.get("reviewed_command4_overlay") or {})
            if not reviewed_overlay:
                raise FoundryError(
                    "CHARACTER_GM_REVIEWED_OVERLAY_VALIDATION_INVALID",
                    "The explicit reviewed overlay validation did not return its immutable receipt.",
                )
            return self._command5_build_from_source(
                project_id,
                output_root=output_root,
                profile=profile,
                profile_contract_sha=profile_contract_sha,
                command4=command4,
                project=project,
                sheet_response=sheet_response,
                workspace_status=workspace_status,
                base_workspace=base_snapshot,
                source_workspace=source_workspace,
                reviewed_overlay=reviewed_overlay,
            )
        finally:
            if staging_parent is not None:
                shutil.rmtree(staging_parent, ignore_errors=True)

    def status(self, project_id: str) -> dict[str, Any]:
        path = self.db.settings.data_dir / "factory_candidates" / project_id / "current.json"
        if not path.is_file():
            return {"project_id":project_id,"status":"NOT_ATTEMPTED","build_profile":None,"gm_export_available":False,"command6_status":"NOT_RUN"}
        payload = json.loads(path.read_text(encoding="utf-8"))
        candidate = Path(str(payload.get("candidate_zip") or ""))
        model = Path(str(payload.get("gm_model_path") or ""))
        stale = not candidate.is_file() or sha256_file(candidate) != payload.get("candidate_sha256") or not model.is_file() or sha256_file(model) != payload.get("gm_model_sha256")
        if stale:
            return {**payload,"status":"STALE","gm_export_available":False,"blockers":["The Character/GM candidate or model hash is stale."]}
        return {**payload,"blockers":[],"gm_export_available":False}
