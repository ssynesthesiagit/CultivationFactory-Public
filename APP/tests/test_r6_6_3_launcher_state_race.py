from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER_PATH = ROOT / "packaging/windows_portable/portable_launcher.py"
_SPEC = importlib.util.spec_from_file_location("tianxia_r663_windows_portable_launcher", _LAUNCHER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
launcher = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = launcher
_SPEC.loader.exec_module(launcher)


def _windows_permission_error(code: int) -> PermissionError:
    error = PermissionError(f"simulated WinError {code}")
    error.winerror = code
    return error


def test_transient_windows_replace_race_retries_then_publishes_complete_json(tmp_path):
    target = tmp_path / "launcher_state.json"
    original_replace = os.replace
    attempts: list[Path] = []
    observed_payloads: list[dict[str, object]] = []

    def replace(source, destination):
        source_path = Path(source)
        attempts.append(source_path)
        observed_payloads.append(json.loads(source_path.read_text(encoding="utf-8")))
        if len(attempts) == 1:
            raise _windows_permission_error(5)
        original_replace(source, destination)

    payload = {"state": "STARTING_SERVICE", "sequence": 1}
    launcher._publish_json_atomically(
        target,
        payload,
        replace_func=replace,
        sleep_func=lambda _seconds: None,
        retry_seconds=0.25,
    )

    assert len(attempts) == 2
    assert attempts[0] == attempts[1]
    assert observed_payloads == [payload, payload]
    assert json.loads(target.read_text(encoding="utf-8")) == payload


def test_each_state_publication_reaches_replace_as_complete_valid_json(tmp_path):
    target = tmp_path / "launcher_state.json"
    original_replace = os.replace
    observed: list[dict[str, object]] = []

    def replace(source, destination):
        observed.append(json.loads(Path(source).read_text(encoding="utf-8")))
        original_replace(source, destination)

    payloads = [
        {"state": "STARTING_WINDOW", "sequence": 1},
        {"state": "STARTING_SERVICE", "sequence": 2},
        {"state": "RUNNING", "sequence": 3, "url": "http://127.0.0.1:43123/"},
    ]
    for payload in payloads:
        launcher._publish_json_atomically(target, payload, replace_func=replace)
        assert json.loads(target.read_text(encoding="utf-8")) == payload

    assert observed == payloads


def test_persistent_transient_replace_failure_surfaces_after_bounded_deadline(tmp_path):
    target = tmp_path / "launcher_state.json"
    clock = [0.0]
    attempts = 0

    def monotonic() -> float:
        return clock[0]

    def sleep(seconds: float) -> None:
        clock[0] += seconds

    def replace(_source, _destination):
        nonlocal attempts
        attempts += 1
        raise _windows_permission_error(32)

    with pytest.raises(PermissionError, match="WinError 32"):
        launcher._publish_json_atomically(
            target,
            {"state": "FAILED"},
            replace_func=replace,
            monotonic_func=monotonic,
            sleep_func=sleep,
            retry_seconds=0.05,
        )

    assert attempts >= 2
    assert clock[0] == pytest.approx(0.05)
    assert not target.exists()


def test_failed_publication_cleans_only_owned_temporary_file(tmp_path):
    target = tmp_path / "launcher_state.json"
    unrelated = tmp_path / ".launcher_state.json.owner-unrelated.tmp"
    unrelated.write_text("owner file", encoding="utf-8")

    def replace(_source, _destination):
        raise _windows_permission_error(5)

    with pytest.raises(PermissionError):
        launcher._publish_json_atomically(
            target,
            {"state": "FAILED"},
            replace_func=replace,
            monotonic_func=lambda: 0.0,
            sleep_func=lambda _seconds: None,
            retry_seconds=0.0,
        )

    assert unrelated.read_text(encoding="utf-8") == "owner file"
    assert list(tmp_path.glob(".launcher_state.json.*.tmp")) == [unrelated]


def test_closely_spaced_publications_use_unique_temporary_names(tmp_path):
    target = tmp_path / "launcher_state.json"
    original_replace = os.replace
    barrier = threading.Barrier(8)
    temporary_names: list[str] = []
    capture_lock = threading.Lock()
    errors: list[BaseException] = []

    def replace(source, destination):
        with capture_lock:
            temporary_names.append(Path(source).name)
        original_replace(source, destination)

    def worker(sequence: int) -> None:
        try:
            barrier.wait()
            launcher._publish_json_atomically(
                target,
                {"state": "RUNNING", "sequence": sequence},
                replace_func=replace,
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    # Replacement attempts may exceed publication count when bounded Windows
    # sharing/access retries reuse a publication-owned temporary path.
    assert len(temporary_names) >= 8
    assert len(set(temporary_names)) == 8
    final_payload = json.loads(target.read_text(encoding="utf-8"))
    assert final_payload["state"] == "RUNNING"
    assert final_payload["sequence"] in range(8)
    assert not list(tmp_path.glob(".launcher_state.json.*.tmp"))


def test_unrelated_filesystem_error_is_not_retried(tmp_path):
    attempts = 0

    def replace(_source, _destination):
        nonlocal attempts
        attempts += 1
        raise FileNotFoundError("unrelated path failure")

    with pytest.raises(FileNotFoundError, match="unrelated path failure"):
        launcher._publish_json_atomically(
            tmp_path / "launcher_state.json",
            {"state": "FAILED"},
            replace_func=replace,
        )

    assert attempts == 1


def test_startup_failure_report_write_cannot_mask_original_diagnostic(caplog):
    instance = launcher.DedicatedWindowLauncher.__new__(launcher.DedicatedWindowLauncher)
    instance.window = SimpleNamespace(events=SimpleNamespace(loaded=SimpleNamespace(wait=lambda _seconds: False)))
    instance._startup_finished = threading.Event()
    instance._close_requested = threading.Event()
    instance.state_file = lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("secondary state write failure"))
    shown: list[str] = []
    instance._show_failure_in_window = shown.append

    instance._start_worker()

    original = "The dedicated WebView2 window did not initialize correctly."
    assert shown == [original]
    assert instance._startup_finished.is_set()
    assert "preserving original error" in caplog.text
    assert original in caplog.text


def test_native_acceptance_reader_remains_tolerant_of_unavailable_or_partial_state_file():
    script = (ROOT / "packaging/windows_portable/Verify-WindowsPortable.ps1").read_text(encoding="utf-8")
    assert 'try { $state = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json } catch { $state = $null }' in script
