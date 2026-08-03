from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import socket
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable

from common import (
    APP_ROOT,
    BASELINE_PATH,
    REPOSITORY_ROOT,
    StageRecorder,
    read_json,
    runtime_versions,
    utc_now,
    write_json,
)
from verify_source import verify as verify_source


class Tee:
    def __init__(self, *streams: Any) -> None:
        self.streams = streams

    def write(self, value: str) -> int:
        for stream in self.streams:
            stream.write(value)
            stream.flush()
        return len(value)

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()

    def isatty(self) -> bool:
        return any(bool(getattr(stream, "isatty", lambda: False)()) for stream in self.streams)

    @property
    def encoding(self) -> str:
        return str(getattr(self.streams[0], "encoding", None) or "utf-8")

    def fileno(self) -> int:
        return int(self.streams[0].fileno())


class ProductFailure(RuntimeError):
    pass


def iso_from_epoch(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def locate_browser(configured: str | None) -> str:
    if configured:
        candidate = Path(configured).expanduser().resolve()
        if not candidate.is_file():
            raise FileNotFoundError(f"Configured Chromium executable does not exist: {candidate}")
        return str(candidate)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        candidate = Path(playwright.chromium.executable_path).resolve()
    if not candidate.is_file():
        raise FileNotFoundError(
            f"Playwright Chromium is not installed at {candidate}; run the official Playwright browser installation step."
        )
    return str(candidate)


def browser_preflight(browser_path: str) -> None:
    from playwright.sync_api import sync_playwright

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=browser_path,
            headless=True,
            args=["--no-sandbox"],
        )
        page = browser.new_page()
        page.goto("data:text/html,<title>CI1-P1 browser preflight</title>")
        if page.title() != "CI1-P1 browser preflight":
            raise RuntimeError("Chromium preflight did not reach its non-product page.")
        browser.close()


def install_instrumentation(recorder: StageRecorder) -> tuple[Callable[[str], None], dict[str, Any]]:
    if str(APP_ROOT) not in sys.path:
        sys.path.insert(0, str(APP_ROOT))

    from catalog.service import CatalogService
    from character_creation.production_release import CharacterProductionReleaseAdapter
    from character_creation.service import CharacterCreationExecutionService
    from gm_export.service import GMCharacterExportService
    from portable_character.service import PortableCharacterPackageService
    from projector import verification as projector_verification
    from vendor_adapter.service import FactoryAdapter

    state: dict[str, Any] = {
        "phase": "browser_chain",
        "product_started": False,
        "review_started_epoch": None,
    }
    state_lock = threading.Lock()

    def phase() -> str:
        with state_lock:
            return str(state["phase"])

    def set_phase(value: str) -> str:
        with state_lock:
            previous = str(state["phase"])
            state["phase"] = value
            return previous

    def wrap_method(cls: type[Any], name: str, stage: str) -> None:
        original = getattr(cls, name)

        def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
            with recorder.measure(
                stage,
                f"{cls.__module__}.{cls.__name__}.{name}",
                details={"phase": phase()},
            ):
                return original(self, *args, **kwargs)

        setattr(cls, name, wrapped)

    wrap_method(FactoryAdapter, "configure", "factory_extraction")
    wrap_method(CatalogService, "rebuild_core", "catalog_core_build")
    wrap_method(CharacterProductionReleaseAdapter, "_clean_import_proof", "clean_import")
    wrap_method(GMCharacterExportService, "export", "gm_export")

    original_build = PortableCharacterPackageService.build

    def timed_build(*args: Any, **kwargs: Any) -> Any:
        with recorder.measure(
            "portable_export",
            "portable_character.service.PortableCharacterPackageService.build",
            details={"phase": phase()},
        ):
            return original_build(*args, **kwargs)

    PortableCharacterPackageService.build = staticmethod(timed_build)

    original_run = projector_verification._run

    def timed_projector_run(command: list[str], *args: Any, **kwargs: Any) -> Any:
        if any("exact_consumer_harness.py" in str(part) for part in command):
            with recorder.measure(
                "gm_consumer",
                "gm_export/exact_consumer_harness.py",
                details={"phase": phase()},
            ):
                return original_run(command, *args, **kwargs)
        return original_run(command, *args, **kwargs)

    projector_verification._run = timed_projector_run

    original_compile_once = CharacterCreationExecutionService._compile_once

    def timed_compile_once(self: Any, run: dict[str, Any], plan: dict[str, Any], index: int, **kwargs: Any) -> Any:
        current = f"scratch_{'a' if index == 1 else 'b'}"
        previous = set_phase(current)
        try:
            with recorder.measure(
                current,
                "character_creation.service.CharacterCreationExecutionService._compile_once",
                details={"scratch_index": index},
            ):
                return original_compile_once(self, run, plan, index, **kwargs)
        finally:
            set_phase(previous)

    CharacterCreationExecutionService._compile_once = timed_compile_once

    original_compile_twice = CharacterCreationExecutionService._compile_twice

    def timed_compile_twice(self: Any, *args: Any, **kwargs: Any) -> Any:
        started_wall = time.time()
        started = time.perf_counter()
        before = recorder.total_for(("scratch_a", "scratch_b"))
        result = original_compile_twice(self, *args, **kwargs)
        elapsed = time.perf_counter() - started
        scratch_elapsed = recorder.total_for(("scratch_a", "scratch_b")) - before
        comparison_elapsed = max(0.0, elapsed - scratch_elapsed)
        ended_wall = time.time()
        recorder.record(
            stage="determinism_comparison",
            command="compare scratch candidate and artifact identities",
            started_at_utc=iso_from_epoch(max(started_wall, ended_wall - comparison_elapsed)),
            ended_at_utc=iso_from_epoch(ended_wall),
            elapsed_seconds=comparison_elapsed,
            status="PASS",
            exit_code=0,
        )
        return result

    CharacterCreationExecutionService._compile_twice = timed_compile_twice

    original_finalize = CharacterCreationExecutionService.finalize

    def timed_finalize(self: Any, *args: Any, **kwargs: Any) -> Any:
        previous = set_phase("finalization")
        try:
            with recorder.measure(
                "finalization",
                "character_creation.service.CharacterCreationExecutionService.finalize",
            ):
                return original_finalize(self, *args, **kwargs)
        finally:
            set_phase(previous)

    CharacterCreationExecutionService.finalize = timed_finalize

    def stage_hook(message: str) -> None:
        now = time.time()
        print(f"[CI1-P1 full product] {utc_now()} {message}", flush=True)
        with state_lock:
            if message.startswith("creating real FastAPI application"):
                state["product_started"] = True
            if message.startswith("production compilation reached ready-for-review"):
                state["review_started_epoch"] = now
            if message.startswith("finalizing through live backend") and state.get("review_started_epoch"):
                started = float(state["review_started_epoch"])
                recorder.record(
                    stage="review",
                    command="owner-facing review and exact typed-choice snapshot download",
                    started_at_utc=iso_from_epoch(started),
                    ended_at_utc=iso_from_epoch(now),
                    elapsed_seconds=now - started,
                    status="PASS",
                    exit_code=0,
                )
                state["review_started_epoch"] = None

    return stage_hook, state


def classify_exception(exc: BaseException, state: dict[str, Any]) -> str:
    if isinstance(exc, ProductFailure):
        return "PRODUCT_FAILURE"
    if isinstance(exc, (FileNotFoundError, TimeoutError, ConnectionError, socket.error)):
        return "INFRASTRUCTURE_BLOCKER"
    text = f"{type(exc).__name__}: {exc}".casefold()
    harness_tokens = (
        "tee' object has no attribute",
        "unable to configure formatter",
    )
    if any(token in text for token in harness_tokens):
        return "HARNESS_FAILURE"
    infrastructure_tokens = (
        "browser has been closed",
        "executable doesn't exist",
        "failed to launch",
        "target page, context or browser has been closed",
        "err_blocked_by_client",
        "err_connection_refused",
        "address already in use",
    )
    if any(token in text for token in infrastructure_tokens):
        return "INFRASTRUCTURE_BLOCKER"
    if state.get("product_started"):
        return "PRODUCT_FAILURE"
    return "HARNESS_FAILURE"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser")
    parser.add_argument("--seed-timings", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "logs").mkdir(exist_ok=True)
    (output / "screenshots").mkdir(exist_ok=True)
    recorder = StageRecorder(output / "stage-timings.json", seed_ndjson=args.seed_timings)
    classification = "PASS"
    failing_stage = None
    failure_excerpt = None
    product_state: dict[str, Any] = {"product_started": False}
    browser_path = args.browser
    raw_report_path = output / "raw-product-report.json"
    temporary_product_root = TemporaryDirectory(prefix="tianxia-ci1-p1-", ignore_cleanup_errors=True)
    data_root = Path(temporary_product_root.name) / "ephemeral-product-data"
    pycache_root = Path(temporary_product_root.name) / "pycache"
    sys.pycache_prefix = str(pycache_root)
    os.environ["PYTHONPYCACHEPREFIX"] = str(pycache_root)
    log_path = output / "logs" / "full-product.log"
    raw_report: dict[str, Any] | None = None
    try:
        with recorder.measure("source_verification", "ci/verify_source.py"):
            source_report = verify_source()
            write_json(output / "source-verification.json", source_report)
            if source_report["status"] != "PASS":
                raise ProductFailure("The checked-out APP tree does not match the accepted source baseline.")
        with recorder.measure("browser_preflight", "Playwright Chromium launch and loopback bind"):
            browser_path = locate_browser(browser_path)
            os.environ["TIANXIA_BROWSER_EXECUTABLE"] = browser_path
            browser_preflight(browser_path)
        stage_hook, product_state = install_instrumentation(recorder)
        from tests import cat3_p1r_browser_harness as harness

        harness.stage = stage_hook
        with log_path.open("w", encoding="utf-8", errors="replace") as log:
            tee = Tee(sys.stdout, log)
            with contextlib.redirect_stdout(tee), contextlib.redirect_stderr(tee):
                with recorder.measure(
                    "full_product_chain",
                    "tests/cat3_p1r_browser_harness.py real FastAPI + real Chromium chain",
                ):
                    raw_report = harness.run(
                        root=APP_ROOT,
                        data=data_root,
                        output=raw_report_path,
                        browser=str(browser_path),
                        screenshot_dir=output / "screenshots",
                    )
        if raw_report.get("status") != "PASS":
            raise ProductFailure("The real product harness completed with a failing product report.")
    except BaseException as exc:
        classification = classify_exception(exc, product_state)
        failing_stage = next(
            (row["stage"] for row in reversed(recorder.records) if row.get("status") == "FAIL"),
            "full_product_chain",
        )
        failure_excerpt = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-12000:]
        with log_path.open("a", encoding="utf-8", errors="replace") as log:
            log.write("\n===== CLASSIFIED FAILURE =====\n")
            log.write(failure_excerpt)
    finally:
        temporary_product_root.cleanup()
    runner_system = platform.system()
    acceptance_identity = {
        "Linux": "REAL_LINUX_CHROMIUM_OWNER_PRODUCT_CHAIN",
        "Windows": "REAL_WINDOWS_CHROMIUM_OWNER_PRODUCT_CHAIN",
    }.get(runner_system, f"REAL_{runner_system.upper()}_CHROMIUM_OWNER_PRODUCT_CHAIN")
    baseline = read_json(BASELINE_PATH)
    write_json(
        output / "commitments.json",
        {
            "schema": "Tianxia.CI1P1.Commitments.v1",
            "source_tree_sha256": baseline["application_source"]["source_tree_commitment_sha256"],
            "catalog_registry_sha256": baseline["catalog"]["registry_commitment_sha256"],
        },
    )
    classification_report = {
        "schema": "Tianxia.CI1P1.FailureClassification.v1",
        "tier": "full-product",
        "classified_at_utc": utc_now(),
        "classification": classification,
        "failing_stage": failing_stage,
        "exit_code": None if classification == "PASS" else 1,
        "runner_os": os.environ.get("RUNNER_OS") or runner_system,
        "browser_executable": browser_path,
        "product_assertion_reached": bool(product_state.get("product_started")),
        "failure_log_excerpt": failure_excerpt,
    }
    write_json(output / "classification.json", classification_report)
    write_json(output / "runtime-versions.json", runtime_versions())
    normalized = {
        "schema": "Tianxia.CI1P1.FullProductSummary.v1",
        "status": classification,
        "acceptance_identity": acceptance_identity,
        "actual_runner_platform": platform.platform(),
        "actual_runner_os": runner_system,
        "browser_executable": browser_path,
        "application": "real app.api.create_app over loopback HTTP",
        "external_model_provider": "deterministic MockTransport behind the production AIProviderService",
        "raw_harness_report": raw_report_path.name if raw_report_path.is_file() else None,
        "legacy_harness_label_note": (
            "The preserved raw harness has historical Windows-named fields. The actual runner OS and acceptance identity above are authoritative for CI; a Windows result is never represented as Linux acceptance."
        ),
        "checks": (raw_report or {}).get("checks"),
        "identities": {
            "project_id": (raw_report or {}).get("wizard_project_id"),
            "run_id": ((raw_report or {}).get("finalization") or {}).get("run_id"),
            "candidate_identity": ((raw_report or {}).get("finalization") or {}).get("candidate_identity"),
            "typed_choice_snapshot": ((raw_report or {}).get("finalization") or {}).get("typed_choice_snapshot"),
            "character_zip": ((raw_report or {}).get("finalization") or {}).get("character_zip"),
        },
        "classification": classification_report,
        "stage_timings": "stage-timings.json",
        "completed_at_utc": utc_now(),
    }
    write_json(output / "summary.json", normalized)
    print(json.dumps(classification_report, sort_keys=True))
    return 0 if classification == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
