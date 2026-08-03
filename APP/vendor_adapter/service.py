from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from app.runtime import helper_python_executable

from app.core import (
    EXPECTED_FACTORY_HASH,
    FACTORY_VERSION,
    Database,
    FoundryError,
    canonical_json,
    sha256_file,
    utcnow,
)

MAX_VENDOR_ARCHIVE = 256 * 1024 * 1024
MAX_VENDOR_EXPANDED = 1024 * 1024 * 1024
REQUIRED_ENTRYPOINTS = [
    "FACTORY_MANIFEST.json",
    "05_COMPILER/compile_character.py",
    "06_VALIDATORS/validate_json_schemas.py",
    "07_TOOLS/run_command5.py",
    "07_TOOLS/run_command6.py",
]


class FactoryAdapter:
    def __init__(self, db: Database):
        self.db = db

    @property
    def config_path(self) -> Path:
        return self.db.settings.vendor_dir / "factory_adapter.json"

    def _safe_extract(self, archive: Path, destination: Path) -> None:
        if archive.stat().st_size > MAX_VENDOR_ARCHIVE:
            raise FoundryError("VENDOR_ARCHIVE_TOO_LARGE", "Factory archive exceeds the configured limit.")
        total = 0
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                p = PurePosixPath(info.filename)
                if p.is_absolute() or ".." in p.parts:
                    raise FoundryError("ZIP_TRAVERSAL", "Factory archive contains an unsafe path.", details={"entry": info.filename})
                total += info.file_size
                if total > MAX_VENDOR_EXPANDED:
                    raise FoundryError("VENDOR_EXPANSION_LIMIT", "Factory archive expands beyond the configured limit.")
            zf.extractall(destination)

    @staticmethod
    def _publish_extraction(staging: Path, destination: Path, *, attempts: int = 40, delay_seconds: float = 0.25) -> None:
        """Atomically publish an extraction despite transient Windows scans.

        Defender and indexers can briefly hold a newly extracted tree and make
        ``os.replace`` raise WinError 5. Retry only Windows access/sharing
        failures; never expose a partially copied Factory tree.
        """
        last_error: OSError | None = None
        for _ in range(max(1, attempts)):
            if destination.exists():
                shutil.rmtree(staging, ignore_errors=True)
                return
            try:
                os.replace(staging, destination)
                return
            except OSError as exc:
                if getattr(exc, "winerror", None) not in {5, 32} and not isinstance(exc, PermissionError):
                    raise
                last_error = exc
                time.sleep(max(0.0, delay_seconds))
        raise FoundryError(
            "VENDOR_EXTRACTION_PUBLISH_BLOCKED",
            "The verified Factory extraction could not be atomically published after transient-access retries.",
            details={"staging": str(staging), "destination": str(destination), "error": str(last_error)},
        )

    @staticmethod
    def _find_factory_root(extract_root: Path) -> Path:
        if (extract_root / "FACTORY_MANIFEST.json").exists():
            return extract_root
        candidates = [p for p in extract_root.iterdir() if p.is_dir() and (p / "FACTORY_MANIFEST.json").exists()]
        if len(candidates) != 1:
            raise FoundryError("FACTORY_ROOT_AMBIGUOUS", "Could not identify a unique Factory root after extraction.")
        return candidates[0]

    def configure(self, factory_zip: Path, fixture_path: Path | None = None) -> dict[str, Any]:
        factory_zip = factory_zip.resolve()
        if not factory_zip.exists():
            raise FoundryError("FACTORY_ZIP_NOT_FOUND", "The Factory ZIP does not exist.", details={"path": str(factory_zip)})
        actual_hash = sha256_file(factory_zip)
        if actual_hash != EXPECTED_FACTORY_HASH:
            raise FoundryError(
                "FACTORY_HASH_MISMATCH",
                "The Factory ZIP does not match the Phase 1 pinned hash.",
                details={"expected": EXPECTED_FACTORY_HASH, "actual": actual_hash},
            )
        package_dir = self.db.settings.vendor_dir / "packages"
        extract_dir = self.db.settings.vendor_dir / "extracted" / actual_hash
        package_dir.mkdir(parents=True, exist_ok=True)
        copied_zip = package_dir / f"{actual_hash}.zip"
        if not copied_zip.exists():
            shutil.copy2(factory_zip, copied_zip)
        if sha256_file(copied_zip) != actual_hash:
            raise FoundryError("VENDOR_COPY_HASH_MISMATCH", "The copied vendor ZIP failed hash verification.")
        if not extract_dir.exists():
            staging = extract_dir.with_name(extract_dir.name + ".staging")
            if staging.exists():
                shutil.rmtree(staging)
            staging.mkdir(parents=True)
            self._safe_extract(copied_zip, staging)
            self._publish_extraction(staging, extract_dir)
        root = self._find_factory_root(extract_dir)
        missing = [rel for rel in REQUIRED_ENTRYPOINTS if not (root / rel).exists()]
        if missing:
            raise FoundryError("FACTORY_ENTRYPOINT_MISSING", "The Factory package is missing required entrypoints.", details={"missing": missing})
        manifest = json.loads((root / "FACTORY_MANIFEST.json").read_text(encoding="utf-8"))
        factory_label = manifest.get("factory") or manifest.get("factory_version")
        if factory_label and FACTORY_VERSION not in str(factory_label):
            raise FoundryError("FACTORY_VERSION_MISMATCH", "The Factory manifest does not identify the pinned producer.", details={"manifest_factory": factory_label})
        fixture = fixture_path.resolve() if fixture_path else root / "08_FIXTURES/GOOD_Authoritative_CL13"
        if not (fixture / "Character_Master_Ledger.json").exists():
            raise FoundryError("FACTORY_FIXTURE_INVALID", "The copied GOOD Factory fixture is unavailable.", details={"fixture": str(fixture)})
        config = {
            "schema_version": "TianxiaFoundry.FactoryAdapter.v1",
            "factory_version": FACTORY_VERSION,
            "factory_zip_hash": actual_hash,
            "original_factory_zip": str(factory_zip),
            "copied_factory_zip": str(copied_zip),
            "factory_root": str(root),
            "fixture_path": str(fixture),
            "configured_at": utcnow(),
            "required_entrypoints": REQUIRED_ENTRYPOINTS,
        }
        self.config_path.write_text(canonical_json(config), encoding="utf-8")
        return config

    def status(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {
                "configured": False,
                "factory_version": FACTORY_VERSION,
                "expected_hash": EXPECTED_FACTORY_HASH,
                "health": "NOT_CONFIGURED",
            }
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        root = Path(config["factory_root"])
        copied = Path(config["copied_factory_zip"])
        issues = []
        if not root.exists():
            issues.append("factory root missing")
        if not copied.exists() or sha256_file(copied) != config["factory_zip_hash"]:
            issues.append("copied Factory ZIP missing or hash changed")
        for rel in REQUIRED_ENTRYPOINTS:
            if not (root / rel).exists():
                issues.append(f"missing entrypoint: {rel}")
        return {
            "configured": True,
            **config,
            "health": "READY" if not issues else "INVALID",
            "issues": issues,
        }

    def health_check(self, timeout_seconds: int = 90) -> dict[str, Any]:
        status = self.status()
        if not status.get("configured") or status.get("health") != "READY":
            raise FoundryError("FACTORY_ADAPTER_NOT_READY", "Configure a valid pinned Factory before running the health check.", details=status)
        root = Path(status["factory_root"])
        fixture = Path(status["fixture_path"])
        original_zip = Path(status["original_factory_zip"])
        original_hash_before = sha256_file(original_zip)
        run_id = str(uuid.uuid4())
        run_dir = self.db.settings.logs_dir / "vendor" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = run_dir / "stdout.log"
        stderr_path = run_dir / "stderr.log"
        started = utcnow()
        start_monotonic = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="tianxia_factory_health_") as tmp:
            tmp_root = Path(tmp)
            workspace = tmp_root / "workspace"
            shutil.copytree(fixture, workspace)
            ledger = workspace / "Character_Master_Ledger.json"
            packets = workspace / "Command_2/Rules_Selection_Packets.json"
            view_model = workspace / "Build/Tianxia_GM_Character_View_Model_v2.json"
            command = [
                str(helper_python_executable()),
                str(root / "06_VALIDATORS/validate_json_schemas.py"),
                "--schemas", str(root / "04_SCHEMAS"),
                "--ledger", str(ledger),
                "--packets", str(packets),
            ]
            if view_model.exists():
                command.extend(["--view-model", str(view_model)])
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    shell=False,
                    env={**os.environ, "PYTHONUTF8": "1"},
                )
                exit_code = completed.returncode
                stdout = completed.stdout
                stderr = completed.stderr
                timed_out = False
            except subprocess.TimeoutExpired as exc:
                exit_code = -1
                stdout = exc.stdout or ""
                stderr = (exc.stderr or "") + "\nFactory health check timed out."
                timed_out = True
            stdout_path.write_text(stdout, encoding="utf-8")
            stderr_path.write_text(stderr, encoding="utf-8")
            copied_fixture_unchanged = sha256_file(workspace / "Character_Master_Ledger.json") == sha256_file(fixture / "Character_Master_Ledger.json")
        duration_ms = int((time.monotonic() - start_monotonic) * 1000)
        original_hash_after = sha256_file(original_zip)
        unchanged = original_hash_before == original_hash_after == EXPECTED_FACTORY_HASH
        verdict = "PASS" if exit_code == 0 and unchanged and copied_fixture_unchanged and not timed_out else "FAIL"
        details = {
            "factory_version": FACTORY_VERSION,
            "factory_hash": status["factory_zip_hash"],
            "fixture": str(fixture),
            "fixture_schema_validation": exit_code == 0,
            "copied_fixture_unchanged": copied_fixture_unchanged,
            "original_factory_unchanged": unchanged,
            "timed_out": timed_out,
            "capability_boundary": "HEALTH_CHECK_ONLY_NEW_PROJECT_COMMAND5_COMPILATION_NOT_IMPLEMENTED",
        }
        ended = utcnow()
        with self.db.connection() as conn:
            conn.execute(
                """INSERT INTO vendor_runs(run_id,operation,started_at,ended_at,duration_ms,exit_code,command_json,
                stdout_path,stderr_path,verdict,details_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    "copied_fixture_schema_health_check",
                    started,
                    ended,
                    duration_ms,
                    exit_code,
                    canonical_json(command),
                    str(stdout_path),
                    str(stderr_path),
                    verdict,
                    canonical_json(details),
                ),
            )
        return {
            "run_id": run_id,
            "verdict": verdict,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "details": details,
        }

    def recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute("SELECT * FROM vendor_runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["command"] = json.loads(item.pop("command_json"))
                item["details"] = json.loads(item.pop("details_json"))
                result.append(item)
            return result
