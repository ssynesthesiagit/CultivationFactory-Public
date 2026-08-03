from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPOSITORY_ROOT / "APP"
BASELINE_PATH = REPOSITORY_ROOT / "ci" / "source-baseline.json"
ACCEPTED_SOURCE_SUMS = REPOSITORY_ROOT / "ci" / "accepted-source.sha256"
CLASSIFICATIONS = (
    "PASS",
    "PRODUCT_FAILURE",
    "HARNESS_FAILURE",
    "INFRASTRUCTURE_BLOCKER",
)
TIMING_SCHEMA = "Tianxia.CI1P1.StageTimings.v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def command_identity(command: Sequence[str]) -> str:
    return json.dumps([str(part) for part in command], ensure_ascii=False)


class StageRecorder:
    def __init__(self, path: Path, *, seed_ndjson: Path | None = None) -> None:
        self.path = path.resolve()
        self._lock = threading.Lock()
        self._records: list[dict[str, Any]] = []
        if seed_ndjson and seed_ndjson.is_file():
            for line in seed_ndjson.read_text(encoding="utf-8-sig").splitlines():
                if line.strip():
                    self._records.append(json.loads(line))
        elif self.path.is_file():
            current = read_json(self.path)
            self._records.extend(current.get("stages") or [])
        self._flush()

    @property
    def records(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._records)

    def _flush(self) -> None:
        total = sum(float(row.get("elapsed_seconds") or 0.0) for row in self._records)
        write_json(
            self.path,
            {
                "schema": TIMING_SCHEMA,
                "generated_at_utc": utc_now(),
                "stage_count": len(self._records),
                "total_recorded_seconds": round(total, 6),
                "stages": self._records,
            },
        )

    def record(
        self,
        *,
        stage: str,
        command: str,
        started_at_utc: str,
        ended_at_utc: str,
        elapsed_seconds: float,
        status: str,
        exit_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row: dict[str, Any] = {
            "stage": stage,
            "command_identity": command,
            "started_at_utc": started_at_utc,
            "ended_at_utc": ended_at_utc,
            "elapsed_seconds": round(max(0.0, elapsed_seconds), 6),
            "status": status,
            "exit_code": exit_code,
        }
        if details:
            row["details"] = details
        with self._lock:
            self._records.append(row)
            self._flush()
        return row

    @contextmanager
    def measure(
        self,
        stage: str,
        command: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> Iterator[None]:
        started_at = utc_now()
        started = time.perf_counter()
        try:
            yield
        except BaseException:
            self.record(
                stage=stage,
                command=command,
                started_at_utc=started_at,
                ended_at_utc=utc_now(),
                elapsed_seconds=time.perf_counter() - started,
                status="FAIL",
                exit_code=1,
                details=details,
            )
            raise
        else:
            self.record(
                stage=stage,
                command=command,
                started_at_utc=started_at,
                ended_at_utc=utc_now(),
                elapsed_seconds=time.perf_counter() - started,
                status="PASS",
                exit_code=0,
                details=details,
            )

    def total_for(self, stages: Iterable[str]) -> float:
        wanted = set(stages)
        return sum(
            float(row.get("elapsed_seconds") or 0.0)
            for row in self.records
            if row.get("stage") in wanted
        )


def run_logged_command(
    *,
    recorder: StageRecorder,
    stage: str,
    command: Sequence[str],
    cwd: Path,
    log_path: Path,
    env: dict[str, str] | None = None,
    timeout_seconds: int | None = None,
) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started_at = utc_now()
    started = time.perf_counter()
    status = "FAIL"
    exit_code: int | None = None
    try:
        completed = subprocess.run(
            [str(part) for part in command],
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        output = completed.stdout or ""
        sys.stdout.write(output)
        sys.stdout.flush()
        with log_path.open("w", encoding="utf-8", errors="replace") as log:
            log.write(f"stage={stage}\n")
            log.write(f"command={command_identity(command)}\n")
            log.write(output)
        exit_code = completed.returncode
        status = "PASS" if exit_code == 0 else "FAIL"
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        partial = exc.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", errors="replace")
        log_path.write_text(
            f"stage={stage}\ncommand={command_identity(command)}\n{partial}\nCI timeout after {timeout_seconds} seconds.\n",
            encoding="utf-8",
        )
        if partial:
            sys.stdout.write(partial)
            sys.stdout.flush()
    except FileNotFoundError as exc:
        exit_code = 127
        log_path.write_text(f"Command unavailable: {exc}\n", encoding="utf-8")
    recorder.record(
        stage=stage,
        command=command_identity(command),
        started_at_utc=started_at,
        ended_at_utc=utc_now(),
        elapsed_seconds=time.perf_counter() - started,
        status=status,
        exit_code=exit_code,
    )
    return int(exit_code or 0)


def runtime_versions(node: str | None = None) -> dict[str, Any]:
    packages: dict[str, str | None] = {}
    try:
        from importlib.metadata import PackageNotFoundError, version

        for name in (
            "fastapi",
            "uvicorn",
            "pydantic",
            "jsonschema",
            "httpx",
            "pytest",
            "playwright",
            "cryptography",
        ):
            try:
                packages[name] = version(name)
            except PackageNotFoundError:
                packages[name] = None
    except Exception:
        packages = {}
    node_version = None
    if node:
        try:
            node_version = subprocess.run(
                [node, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            ).stdout.strip() or None
        except Exception:
            node_version = None
    return {
        "schema": "Tianxia.CI1P1.RuntimeVersions.v1",
        "captured_at_utc": utc_now(),
        "platform": platform.platform(),
        "runner_os": os.environ.get("RUNNER_OS") or platform.system(),
        "python": sys.version,
        "python_executable": sys.executable,
        "node": node_version,
        "packages": packages,
    }
