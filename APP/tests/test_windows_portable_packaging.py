from __future__ import annotations

import ast
import contextlib
import hashlib
import http.server
import io
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import FoundryError
from app.runtime import PRIVATE_PYTHON_ENV, helper_python_executable
from gm_export import exact_consumer_harness

ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER_PATH = ROOT / "packaging/windows_portable/portable_launcher.py"
_SPEC = importlib.util.spec_from_file_location("tianxia_windows_portable_launcher", _LAUNCHER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
launcher = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = launcher
_SPEC.loader.exec_module(launcher)

FACTORY_NAME = launcher.FACTORY_NAME
FOUNDATION_NAME = launcher.FOUNDATION_NAME
PortablePaths = launcher.PortablePaths
ensure_owner_layout = launcher.ensure_owner_layout
stage_bundled_content = launcher.stage_bundled_content


def test_owner_test_window_title_is_process_local_and_explicit(monkeypatch):
    assert launcher.owner_window_label() == "Tianxia Factory"
    monkeypatch.setenv("TIANXIA_WINDOW_TITLE", "Tianxia Current Owner Test")
    assert launcher.owner_window_label() == "Tianxia Current Owner Test"


def test_w5_owner_test_launcher_forces_exact_isolated_data_root():
    launcher_path = ROOT / "packaging/windows_portable/START_TIANXIA_CURRENT_OWNER_TEST.cmd"
    text = launcher_path.read_text(encoding="utf-8")
    assert 'set "TIANXIA_FOUNDRY_DATA=%~dp0OwnerTestData"' in text
    assert 'set "TIANXIA_WINDOW_TITLE=Tianxia Current Owner Test"' in text
    assert '"%~dp0Tianxia Factory.exe"' in text
    assert "UserData" not in text
    first_run = (ROOT / "packaging/windows_portable/README_FIRST_RUN.txt").read_text(encoding="utf-8")
    assert 'Double-click "START_TIANXIA_CURRENT_OWNER_TEST.cmd"' in first_run
    assert 'Double-click "Tianxia Factory.exe"' not in first_run
    assert r"%LOCALAPPDATA%\Tianxia Factory" in first_run
    assert "does not use" in first_run


def test_exact_consumer_discovers_windows_browser_and_honors_override(monkeypatch, tmp_path):
    monkeypatch.delenv("TIANXIA_BROWSER_EXECUTABLE", raising=False)
    monkeypatch.setattr(exact_consumer_harness, "_is_windows", lambda: True)
    program_files = tmp_path / "Program Files"
    browser = program_files / "Microsoft/Edge/Application/msedge.exe"
    browser.parent.mkdir(parents=True)
    browser.write_bytes(b"bounded-test-browser")
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "missing-x86"))
    monkeypatch.setenv("ProgramFiles", str(program_files))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "missing-local"))
    assert exact_consumer_harness._default_browser_executable() == str(browser)
    monkeypatch.setenv("TIANXIA_BROWSER_EXECUTABLE", r"C:\Verified\chromium.exe")
    assert exact_consumer_harness._default_browser_executable() == r"C:\Verified\chromium.exe"


def test_exact_consumer_linux_browser_fallback_does_not_claim_missing_system_binary(monkeypatch):
    monkeypatch.delenv("TIANXIA_BROWSER_EXECUTABLE", raising=False)
    monkeypatch.setattr(exact_consumer_harness, "_is_windows", lambda: False)
    discovered = exact_consumer_harness._default_browser_executable()
    system_browser = Path("/usr/bin/chromium")
    assert discovered == (str(system_browser) if system_browser.is_file() else None)


def test_exact_consumer_browser_runtime_reports_invalid_explicit_override_fail_closed(monkeypatch, tmp_path):
    missing = tmp_path / "missing-chromium"
    monkeypatch.setenv("TIANXIA_BROWSER_EXECUTABLE", str(missing))
    runtime = exact_consumer_harness._browser_runtime_descriptor(str(missing))
    assert runtime["runtime_kind"] == "explicit_executable"
    assert runtime["requested_executable"] == str(missing)
    assert runtime["resolved_executable"] is None


def test_portable_settings_keep_persistent_state_outside_runtime(tmp_path):
    package = tmp_path / "Folder With Spaces" / "Tianxia Factory"
    paths = PortablePaths(
        package,
        package / "Runtime",
        package / "BundledContent",
        package / "UserData",
        package / "Runtime/PrivatePython/python.exe",
    )
    settings = ensure_owner_layout(paths)
    assert settings.db_path == package / "UserData/Database/foundry.sqlite3"
    assert settings.packs_dir == package / "UserData/InstalledContent"
    assert settings.logs_dir == package / "UserData/Logs"
    assert settings.backups_dir == package / "UserData/Backups"
    assert settings.root_dir == package / "Runtime"
    assert paths.webview_data == package / "UserData/WebView2"
    assert paths.webview_data.is_dir()


def test_bundled_content_is_exact_and_never_overwrites_changed_inbox(tmp_path, monkeypatch):
    package = tmp_path / "Tianxia Factory"
    bundled = package / "BundledContent"
    bundled.mkdir(parents=True)
    factory = bundled / FACTORY_NAME
    foundation = bundled / FOUNDATION_NAME
    factory.write_bytes(b"factory")
    foundation.write_bytes(b"foundation")
    monkeypatch.setattr(launcher, "FACTORY_SHA256", launcher.sha256_file(factory))
    monkeypatch.setattr(launcher, "FOUNDATION_SHA256", launcher.sha256_file(foundation))
    paths = PortablePaths(
        package,
        package / "Runtime",
        bundled,
        package / "UserData",
        package / "Runtime/PrivatePython/python.exe",
    )
    settings = ensure_owner_layout(paths)
    stage_bundled_content(paths, settings)
    target = settings.inbox_dir / FOUNDATION_NAME
    assert target.read_bytes() == b"foundation"
    target.write_bytes(b"owner changed")
    with pytest.raises(RuntimeError, match="was not overwritten"):
        stage_bundled_content(paths, settings)


def test_private_runtime_fails_closed_when_explicit_path_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv(PRIVATE_PYTHON_ENV, str(tmp_path / "missing python.exe"))
    with pytest.raises(FoundryError, match="private Python runtime is missing"):
        helper_python_executable()


def test_build_contract_is_dedicated_webview2_onedir_and_windowed():
    spec = (ROOT / "packaging/windows_portable/TianxiaFactory.spec").read_text(encoding="utf-8")
    assert 'name="Tianxia Factory"' in spec
    assert 'contents_directory="Runtime"' in spec
    assert "console=False" in spec
    assert '"pytest", "playwright", "tests", "tkinter"' in spec
    assert '"webview.platforms.edgechromium"' in spec
    assert '"webview.platforms.winforms"' in spec
    assert '"clr"' in spec
    assert '(str(ROOT / "combat_gate1" / "generated"), "combat_gate1/generated")' in spec
    assert '(str(ROOT / "combat_gate2" / "generated"), "combat_gate2/generated")' in spec
    assert '(str(ROOT / "combat_gate4" / "policies"), "combat_gate4/policies")' in spec
    assert '(str(ROOT / "catalog"), "catalog")' in spec
    assert '(str(ROOT / "character_sheet" / "contracts"), "character_sheet/contracts")' in spec
    assert '(str(ROOT / "factory_authoring" / "contracts"), "factory_authoring/contracts")' in spec
    assert '(str(ROOT / "combat" / "character_authority"), "combat/character_authority")' in spec
    assert '(str(ROOT / "combat" / "pre_encounter.py"), "combat")' in spec
    assert '(str(ROOT / "combat" / "character_runtime_adapter.py"), "combat")' in spec
    assert '(str(ROOT / "catalog_authority" / "cat3" / "generated"), "catalog_authority/cat3/generated")' in spec
    assert '(str(ROOT / "non_sphere_authority" / "authority"), "non_sphere_authority/authority")' in spec
    assert '(str(ROOT / "projector" / "contracts"), "projector/contracts")' in spec
    assert '(str(ROOT / "authority"), "authority")' in spec
    assert '(str(ROOT / "R6_6_9_2_C3B_STATUS.json"), ".")' in spec
    assert '(str(ROOT / "gm_export" / "exact_consumer_harness.py"), "gm_export")' in spec
    assert '(str(ROOT / "app" / "authorities.py"), "app")' in spec
    assert '(str(ROOT / "app" / "core.py"), "app")' in spec
    assert '(str(ROOT / "gm_screen"), "gm_screen")' in spec

    source = _LAUNCHER_PATH.read_text(encoding="utf-8")
    assert 'sock.bind(("127.0.0.1", 0))' in source
    assert 'gui="edgechromium"' in source
    assert 'storage_path=str(self.paths.webview_data)' in source
    assert 'webview.create_window(' in source
    assert 'APP_LABEL = "Tianxia Factory"' in source
    assert 'webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False' in source
    assert "server.should_exit = True" in source
    assert "PRIVATE_PYTHON_ENV" in source
    assert "log_config=None" in source
    assert "self.window.events.loaded.wait(90)" in source

    requirements = (ROOT / "packaging/windows_portable/requirements-build.txt").read_text(encoding="utf-8")
    assert "pywebview==6.2.1" in requirements
    assert "pythonnet==3.0.5" in requirements

    build_script = (ROOT / "packaging/windows_portable/Build-WindowsPortable.ps1").read_text(encoding="utf-8")
    assert "function New-SafeZip" in build_script
    assert ".Replace('\\','/')" in build_script
    assert "New-SafeZip $Portable $PortableZip" in build_script
    assert "New-SafeZip $EvidencePackage $EvidenceZip" in build_script
    assert '$CatalogAuthorityRuntime = Join-Path $Portable "Runtime\\catalog_authority\\cat3\\generated\\catalog_authority.v1.json"' in build_script
    assert 'Assert-Hash $CatalogAuthorityRuntime (Sha256 $CatalogAuthoritySource)' in build_script
    assert 'Assert-Hash $GmScreenRuntime (Sha256 $GmScreenSource)' in build_script
    assert 'Copy-Item -LiteralPath $Factory -Destination (Join-Path $Portable "Runtime\\BundledContent")' in build_script
    assert 'runtime-data-packaging-assertions.json' in build_script


def test_owner_ui_defaults_to_guided_character_builder_and_keeps_advanced_tools():
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "static/app.js").read_text(encoding="utf-8")
    styles = (ROOT / "static/styles.css").read_text(encoding="utf-8")

    assert 'id="screen-builder" class="screen active"' in html
    assert 'data-screen="builder" data-builder-mode="quick" class="active">Create a Character' in html
    assert 'data-screen="builder" data-builder-mode="detailed">Detailed Character Intake' in html
    assert 'data-screen="combat">Combat' in html
    assert 'id="guidedName"' in html
    assert 'id="guidedConcept"' in html
    assert 'id="guidedLevel"' in html
    assert 'id="guidedDownloadCompleteRequest"' in html
    assert 'id="guidedCompleteReplyFile"' in html
    assert 'id="guidedCompleteResponseText"' in html
    assert 'id="guidedSubmitCompleteResponse"' in html
    assert 'id="guidedCopyPrompt"' not in html
    assert 'id="guidedResponse"' not in html
    assert "You do not need to choose content packs" in html

    # The owner path uses the installed trusted core rules automatically. The
    # core pack is intentionally not exposed as a manually selectable add-on.
    assert 'pack.trust_state === "trusted_core"' in javascript
    assert "pack.record_count > 0" in javascript
    assert 'pack.selectable === true && pack.authority === "canonical"' in javascript
    assert 'api("/api/projects"' in javascript
    assert '/api/character-builder/projects' in javascript
    assert 'character_builder.create_project' in (ROOT / 'app/api.py').read_text(encoding='utf-8')
    assert 'pack.get("authority") == "canonical"' in (ROOT / 'character_builder/service.py').read_text(encoding='utf-8')
    assert 'Object.prototype.hasOwnProperty.call' in javascript
    assert 'Your saved character is safe. Resume failed while' in javascript
    assert 'Array.isArray(projectRows)' in javascript
    assert 'startNewCharacter' in javascript
    assert '/stage1/prompt' in javascript
    assert 'stage1PromptData.prompt_sha256' in javascript
    assert "FACTORY RESPONSE BINDING" in javascript
    assert "async function resumeGuidedDraft" in javascript
    assert "await resumeGuidedDraft(projectRows)" in javascript
    assert "Attach it to a compatible receiving chat." in html
    assert "Build Complete Candidate" in html
    assert '/responses/validate' in javascript
    assert '/approve-commit' in javascript

    # Long catalog IDs and detail JSON must reflow instead of overlapping at
    # ordinary non-maximized desktop widths.
    assert ".split > * { min-width: 0; max-width: 100%; }" in styles
    assert "@media (max-width: 1200px)" in styles
    assert "overflow-wrap: anywhere" in styles


def test_normal_startup_has_no_system_browser_call():
    tree = ast.parse(_LAUNCHER_PATH.read_text(encoding="utf-8"))
    parent: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node

    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if isinstance(node.func.value, ast.Name) and node.func.value.id == "webbrowser" and node.func.attr == "open":
            calls.append(node)
    assert len(calls) == 1

    current: ast.AST | None = calls[0]
    owner = None
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owner = current.name
            break
        current = parent.get(current)
    assert owner == "open_external"


def test_external_navigation_is_http_https_only():
    assert launcher._safe_external_http_url("https://example.com/path") == "https://example.com/path"
    assert launcher._safe_external_http_url("http://example.com") == "http://example.com"
    assert launcher._safe_external_http_url("file:///C:/secret.txt") is None
    assert launcher._safe_external_http_url("javascript:alert(1)") is None
    assert launcher._safe_external_http_url("mailto:owner@example.com") is None
    assert launcher._safe_external_http_url("//example.com/no-scheme") is None


def test_webview2_runtime_detection_checks_supported_registry_locations():
    class Key:
        def __init__(self, value):
            self.value = value

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    class FakeWinreg:
        HKEY_LOCAL_MACHINE = "HKLM"
        HKEY_CURRENT_USER = "HKCU"
        KEY_READ = 1

        def __init__(self):
            self.seen = []

        def OpenKey(self, hive, path, *_):
            self.seen.append((hive, path))
            if hive == self.HKEY_CURRENT_USER:
                return Key("126.0.2592.113")
            raise OSError("not found")

        @staticmethod
        def QueryValueEx(key, name):
            assert name == "pv"
            return key.value, 1

    fake = FakeWinreg()
    assert launcher.detect_webview2_runtime(platform_name="nt", winreg_module=fake) == "126.0.2592.113"
    assert fake.seen[0][0] == "HKLM"
    assert fake.seen[1][0] == "HKCU"
    assert launcher.detect_webview2_runtime(platform_name="posix", winreg_module=fake) is None
    assert launcher._valid_runtime_version("0.0.0.0") is False
    assert launcher._valid_runtime_version("126.0.2592.113") is True


def test_trusted_window_accepts_only_the_exact_loopback_origin():
    instance = launcher.DedicatedWindowLauncher.__new__(launcher.DedicatedWindowLauncher)
    instance.url = "http://127.0.0.1:43123/"
    assert instance._is_trusted_url("http://127.0.0.1:43123/projects")
    assert not instance._is_trusted_url("http://127.0.0.1:43124/")
    assert not instance._is_trusted_url("https://127.0.0.1:43123/")
    assert not instance._is_trusted_url("https://example.com/")


def test_close_during_startup_is_deferred_safely():
    instance = launcher.DedicatedWindowLauncher.__new__(launcher.DedicatedWindowLauncher)
    instance._startup_finished = threading.Event()
    instance._close_requested = threading.Event()
    instance._stop_event = threading.Event()
    calls = []
    instance.state_file = lambda state, **extra: calls.append(state)
    instance._show_closing_in_window = lambda: calls.append("SHOW_CLOSING")
    instance.stop = lambda: calls.append("STOP")

    assert instance._on_closing() is False
    assert instance._close_requested.is_set()
    assert instance._stop_event.is_set()
    assert calls == ["CLOSE_REQUESTED_DURING_STARTUP", "SHOW_CLOSING"]

    instance._startup_finished.set()
    assert instance._on_closing() is True
    assert calls[-1] == "STOP"


def test_stop_is_idempotent_and_records_one_terminal_state(tmp_path):
    instance = launcher.DedicatedWindowLauncher.__new__(launcher.DedicatedWindowLauncher)
    instance._stop_lock = threading.Lock()
    instance._stop_event = threading.Event()
    instance._stopped = False
    instance.server = None
    instance.server_thread = None
    instance.socket = None
    states = []
    instance.state_file = lambda state, **extra: states.append(state)

    instance.stop()
    instance.stop()
    assert states == ["STOPPED"]
    assert instance._stop_event.is_set()


def test_state_contract_proves_dedicated_host_and_no_startup_browser(tmp_path):
    instance = launcher.DedicatedWindowLauncher.__new__(launcher.DedicatedWindowLauncher)
    logs = tmp_path / "UserData/Logs"
    logs.mkdir(parents=True)
    instance.settings = SimpleNamespace(logs_dir=logs)
    instance.log_path = logs / "Tianxia_Factory_Launcher.log"
    instance._state_lock = threading.Lock()
    instance.url = "http://127.0.0.1:43123/"
    instance.webview2_runtime_version = "126.0.2592.113"
    instance.external_navigation_count = 0
    instance.state_file("RUNNING", port=43123)
    payload = json.loads((logs / "launcher_state.json").read_text(encoding="utf-8"))
    assert payload["window_title"] == "Tianxia Factory"
    assert payload["window_host"] == "pywebview-edgechromium"
    assert payload["renderer"] == "edgechromium"
    assert payload["default_browser_launch_attempted"] is False
    assert payload["external_navigation_count"] == 0



def test_external_bridge_uses_acceptance_sentinel_without_opening_browser(tmp_path, monkeypatch):
    sentinel = tmp_path / "browser-sentinel.txt"
    monkeypatch.setenv(launcher.BROWSER_SENTINEL_ENV, str(sentinel))
    owner = SimpleNamespace(external_navigation_count=0, window=None)
    bridge = launcher.DesktopBridge(owner)
    monkeypatch.setattr(launcher.webbrowser, "open", lambda *args, **kwargs: pytest.fail("browser must not open"))
    assert bridge.open_external("https://example.com/owner-help") is True
    assert sentinel.read_text(encoding="utf-8") == "https://example.com/owner-help\n"
    assert owner.external_navigation_count == 1


def test_desktop_bridge_does_not_publicly_expose_native_window_graph():
    owner = SimpleNamespace(external_navigation_count=0, window=None)
    bridge = launcher.DesktopBridge(owner)
    assert not hasattr(bridge, "launcher")
    assert bridge._launcher is owner


def _complete_request_fixture(*, full_size: bool = False, receipt_v2: bool = False) -> tuple[bytes, str, dict]:
    project_id = "project-native-save"
    snapshot = {"snapshot_sha256": "a" * 64}
    unsigned = {
        "schema": "TianxiaFoundry.CharacterCreationPlanRequest.v2",
        "project_id": project_id,
        "project_revision": 7,
        "content_lock_hash": "b" * 64,
        "typed_choice_snapshot": snapshot,
        "required_components": ["stage1_response"],
        "forbidden_planner_fields": [],
        "policy": {"planner_prose_is_mechanical_authority": False, "automatic_retries": False},
    }
    request = {
        **unsigned,
        "request_sha256": launcher.sha256_json(unsigned),
        "idempotency_binding_sha256": "f" * 64,
    }
    binding = {
        "schema": "TianxiaFoundry.CharacterCreationRequestBinding.v1",
        "project_id": project_id,
        "project_revision": 7,
        "content_lock_hash": unsigned["content_lock_hash"],
        "typed_choice_snapshot_sha256": snapshot["snapshot_sha256"],
        "request_sha256": request["request_sha256"],
        "owner_principal_hash": "c" * 64,
    }
    response_schema = {
        "schema": "TianxiaFoundry.CharacterCreationPlan.v2",
        "required": ["stage1_response", "request_sha256"],
        "request_sha256": request["request_sha256"],
    }
    prompt_bytes = b"Complete request instructions\n"
    if full_size:
        prompt_bytes += b"".join(hashlib.sha256(str(index).encode()).digest() for index in range(70000))
    entries = {
        "BINDING.json": launcher.canonical_json(binding).encode() + b"\n",
        "COMPLETE_REQUEST.json": launcher.canonical_json(request).encode() + b"\n",
        "PROMPT_INSTRUCTIONS.md": prompt_bytes,
        "RESPONSE_SCHEMA.json": launcher.canonical_json(response_schema).encode() + b"\n",
    }
    entries["SHA256SUMS.txt"] = "".join(
        f"{hashlib.sha256(entries[name]).hexdigest()}  {name}\n" for name in sorted(entries)
    ).encode("ascii")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(entries):
            archive.writestr(name, entries[name])
    filename = f"CG1_COMPLETE_REQUEST_{project_id}_{request['request_sha256'][:12]}.zip"
    member_inventory = [
        {"name": name, "bytes": len(entries[name]), "sha256": hashlib.sha256(entries[name]).hexdigest()}
        for name in sorted(entries)
    ]
    payload = output.getvalue()
    run = {
        "schema": "TianxiaFoundry.CompleteRequestSaveReceipt.v2" if receipt_v2 else "TianxiaFoundry.CompleteRequestSaveReceipt.v1",
        "run_id": "cg1.run." + "d" * 32,
        "project_id": project_id,
        "starting_revision": 7,
        "request": {
            "request_sha256": request["request_sha256"],
            "content_lock_hash": unsigned["content_lock_hash"],
            "typed_choice_snapshot": snapshot,
        },
        "filename": filename,
    }
    if receipt_v2:
        run.update({
            "request_payload_sha256": request["request_sha256"],
            "content_set_sha256": launcher.sha256_json(member_inventory),
            "final_zip_sha256": hashlib.sha256(payload).hexdigest(),
            "final_zip_bytes": len(payload),
            "member_inventory": member_inventory,
        })
    return payload, filename, run


class _ControlledLoopbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests.append(self.path)
        response = self.server.routes.get(self.path)
        if response == "disconnect":
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        if response is None:
            self.send_error(404)
            return
        status, headers, body = response
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


@contextlib.contextmanager
def _controlled_loopback(routes):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _ControlledLoopbackHandler)
    server.routes = routes
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/", server.requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _request_routes(payload, filename, run, *, zip_headers=None, zip_body=None):
    run_root = f"/api/character-creation/runs/{run['run_id']}"
    run_path = f"{run_root}/complete-request-save-receipt"
    zip_path = f"{run_root}/complete-request.zip"
    headers = {
        "Content-Type": "application/zip",
        "Content-Disposition": f'attachment; filename="{filename}"',
        **(zip_headers or {}),
    }
    return {
        run_path: (200, {"Content-Type": "application/json"}, json.dumps(run).encode("utf-8")),
        zip_path: (200, headers, payload if zip_body is None else zip_body),
    }, run_path, zip_path


class _ControlledWindow:
    def __init__(self, selected):
        self.selected = selected
        self.dialog_calls = []

    def create_file_dialog(self, dialog_type, **kwargs):
        self.dialog_calls.append((dialog_type, kwargs))
        return self.selected


def _invoke_public_save(monkeypatch, base, selected, *, filesystem=None):
    window = _ControlledWindow(selected)
    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(SAVE_DIALOG="SAVE_DIALOG"))
    owner = SimpleNamespace(url=base, window=window, external_navigation_count=0)
    result = launcher.DesktopBridge(owner, save_filesystem=filesystem).save_complete_request(
        "cg1.run." + "d" * 32
    )
    return result, window


def _assert_no_save_residue(root: Path):
    assert not list(root.rglob(".*.tmp"))


def _zip_with_entries(entries: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    return output.getvalue()


def _zip_entries(payload: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_public_native_save_bridge_success_uses_loopback_dialog_and_atomic_publication(tmp_path, monkeypatch):
    payload, filename, run = _complete_request_fixture()
    routes, run_path, zip_path = _request_routes(payload, filename, run)
    destination = tmp_path / "Downloads" / filename
    destination.parent.mkdir()
    production = tmp_path / "Production" / "UserData" / "sentinel.bin"
    production.parent.mkdir(parents=True)
    production.write_bytes(b"production-unchanged")
    with _controlled_loopback(routes) as (base, requests):
        result, window = _invoke_public_save(monkeypatch, base, [str(destination)])

    assert requests == [run_path, zip_path]
    assert window.dialog_calls == [("SAVE_DIALOG", {"save_filename": filename, "file_types": ("ZIP archives (*.zip)",)})]
    assert result["status"] == "saved"
    assert result["path"] == str(destination.resolve())
    assert result["sha256"] == hashlib.sha256(payload).hexdigest()
    assert result["project_id"] == run["project_id"]
    assert result["project_revision"] == run["starting_revision"]
    assert result["zip_crc"] == "PASS" and result["path_safety"] == "PASS"
    assert destination.read_bytes() == payload
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
    assert production.read_bytes() == b"production-unchanged"
    _assert_no_save_residue(tmp_path)


def test_public_native_save_bridge_saves_full_size_zip_without_fetching_large_run(tmp_path, monkeypatch):
    payload, filename, run = _complete_request_fixture(full_size=True)
    assert len(payload) > 2 * 1024 * 1024
    routes, receipt_path, zip_path = _request_routes(payload, filename, run)
    full_run_path = f"/api/character-creation/runs/{run['run_id']}"
    routes[full_run_path] = (200, {"Content-Type": "application/json"}, b'{' + b'"padding":"' + b'x' * (3 * 1024 * 1024) + b'"}')
    destination = tmp_path / filename
    with _controlled_loopback(routes) as (base, requests):
        result, _ = _invoke_public_save(monkeypatch, base, str(destination))
    assert requests == [receipt_path, zip_path]
    assert full_run_path not in requests
    assert result["status"] == "saved" and result["bytes"] > 2 * 1024 * 1024
    assert destination.read_bytes() == payload


def test_public_native_save_bridge_cancellation_creates_no_file(tmp_path, monkeypatch):
    payload, filename, run = _complete_request_fixture()
    routes, _, _ = _request_routes(payload, filename, run)
    with _controlled_loopback(routes) as (base, _):
        result, window = _invoke_public_save(monkeypatch, base, [])
    assert result["status"] == "cancelled"
    assert result["filename"] == filename
    assert result["sha256"] == hashlib.sha256(payload).hexdigest()
    assert len(window.dialog_calls) == 1
    assert list(tmp_path.rglob("*")) == []


@pytest.mark.parametrize(
    "selected_factory, expected_message",
    [
        (lambda root, name: root / f"changed-{name}", "suggested .zip filename"),
        (lambda root, name: root / name.replace(".zip", ".txt"), "suggested .zip filename"),
        (lambda root, name: root / "missing" / name, "folder does not exist"),
        (lambda _root, name: Path(name), "absolute destination"),
    ],
    ids=["changed-name", "non-zip-extension", "missing-parent", "relative-destination"],
)
def test_public_native_save_bridge_rejects_invalid_destinations(
    tmp_path, monkeypatch, selected_factory, expected_message
):
    payload, filename, run = _complete_request_fixture()
    routes, _, _ = _request_routes(payload, filename, run)
    selected = selected_factory(tmp_path, filename)
    with _controlled_loopback(routes) as (base, _):
        result, _ = _invoke_public_save(monkeypatch, base, str(selected))
    assert result["status"] == "error"
    assert expected_message in result["message"]
    assert not selected.exists()
    _assert_no_save_residue(tmp_path)


def test_public_native_save_bridge_fails_closed_without_overwriting_existing_file(tmp_path, monkeypatch):
    payload, filename, run = _complete_request_fixture()
    routes, _, _ = _request_routes(payload, filename, run)
    destination = tmp_path / filename
    destination.write_bytes(b"existing-owner-file")
    with _controlled_loopback(routes) as (base, _):
        result, _ = _invoke_public_save(monkeypatch, base, str(destination))
    assert result["status"] == "error"
    assert "already exists" in result["message"]
    assert destination.read_bytes() == b"existing-owner-file"
    _assert_no_save_residue(tmp_path)


def _failure_case_routes(case, payload, filename, run):
    routes, run_path, zip_path = _request_routes(payload, filename, run)
    if case == "run-invalid-json":
        routes[run_path] = (200, {"Content-Type": "application/json"}, b"{not-json")
    elif case == "run-identity-mismatch":
        altered = {**run, "run_id": "cg1.run." + "e" * 32}
        routes[run_path] = (200, {"Content-Type": "application/json"}, json.dumps(altered).encode())
    elif case == "zip-connection-failure":
        routes[zip_path] = "disconnect"
    elif case == "wrong-content-type":
        routes[zip_path] = (200, {"Content-Type": "text/plain", "Content-Disposition": f'attachment; filename="{filename}"'}, payload)
    elif case == "missing-filename":
        routes[zip_path] = (200, {"Content-Type": "application/zip"}, payload)
    elif case == "malformed-filename":
        routes[zip_path] = (200, {"Content-Type": "application/zip", "Content-Disposition": "attachment; filename=unquoted.zip"}, payload)
    elif case == "oversized-response":
        routes[zip_path] = (200, {"Content-Type": "application/zip", "Content-Disposition": f'attachment; filename="{filename}"'}, b"x" * (32 * 1024 * 1024 + 1))
    elif case == "invalid-zip":
        routes[zip_path] = (200, {"Content-Type": "application/zip", "Content-Disposition": f'attachment; filename="{filename}"'}, b"not-a-zip")
    elif case == "unsafe-zip-path":
        routes[zip_path] = (200, {"Content-Type": "application/zip", "Content-Disposition": f'attachment; filename="{filename}"'}, _zip_with_entries({"../COMPLETE_REQUEST.json": b"bad"}))
    elif case == "project-mismatch":
        altered = {**run, "project_id": "other-project"}
        routes[run_path] = (200, {"Content-Type": "application/json"}, json.dumps(altered).encode())
    elif case == "revision-mismatch":
        altered = {**run, "starting_revision": run["starting_revision"] + 1}
        routes[run_path] = (200, {"Content-Type": "application/json"}, json.dumps(altered).encode())
    elif case == "checksum-mismatch":
        entries = _zip_entries(payload)
        entries["PROMPT_INSTRUCTIONS.md"] += b"tampered"
        routes[zip_path] = (200, {"Content-Type": "application/zip", "Content-Disposition": f'attachment; filename="{filename}"'}, _zip_with_entries(entries))
    return routes


@pytest.mark.parametrize(
    "case",
    [
        "run-invalid-json", "run-identity-mismatch", "zip-connection-failure",
        "wrong-content-type", "missing-filename", "malformed-filename", "oversized-response", "invalid-zip",
        "unsafe-zip-path", "project-mismatch", "revision-mismatch", "checksum-mismatch",
    ],
)
def test_public_native_save_bridge_response_failures_leave_no_output(tmp_path, monkeypatch, case):
    payload, filename, run = _complete_request_fixture()
    routes = _failure_case_routes(case, payload, filename, run)
    destination = tmp_path / filename
    with _controlled_loopback(routes) as (base, _):
        result, _ = _invoke_public_save(monkeypatch, base, str(destination))
    assert result["status"] == "error"
    assert isinstance(result["message"], str) and len(result["message"].strip()) >= 8
    assert not destination.exists()
    _assert_no_save_residue(tmp_path)


def test_public_native_save_bridge_run_connection_failure_is_bounded(tmp_path, monkeypatch):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    payload, filename, _ = _complete_request_fixture()
    result, window = _invoke_public_save(monkeypatch, f"http://127.0.0.1:{port}/", str(tmp_path / filename))
    assert result["status"] == "error" and result["message"]
    assert window.dialog_calls == []
    assert not (tmp_path / filename).exists()
    _assert_no_save_residue(tmp_path)


def test_public_native_save_bridge_rejects_noncanonical_run_identity_before_network(monkeypatch):
    owner = SimpleNamespace(url="http://127.0.0.1:1/", window=_ControlledWindow(None), external_navigation_count=0)
    result = launcher.DesktopBridge(owner).save_complete_request("cg1.run." + "A" * 32)
    assert result == {"status": "error", "message": "The complete request run identity is invalid."}


class _FailingSaveFileSystem(launcher._CompleteRequestFileSystem):
    def __init__(self, stage, *, cleanup_once=False):
        self.stage = stage
        self.cleanup_once = cleanup_once
        self.cleanup_calls = 0

    def create_temporary(self, parent, filename):
        if self.stage == "create":
            raise OSError("temporary creation failed")
        path, handle = super().create_temporary(parent, filename)
        if self.stage == "write":
            raw_handle = handle
            original_write = raw_handle.write

            class PartialWriteHandle:
                def __enter__(self): return self
                def __exit__(self, *args): return raw_handle.__exit__(*args)
                def write(self, data):
                    original_write(data[:7])
                    raise OSError("payload write failed")
                def flush(self): return raw_handle.flush()
                def fileno(self): return raw_handle.fileno()
                def close(self): return raw_handle.close()

            handle = PartialWriteHandle()
        return path, handle

    def sync(self, handle):
        if self.stage == "flush":
            raise OSError("flush failed")
        handle.flush()
        if self.stage == "fsync":
            raise OSError("fsync failed")
        os.fsync(handle.fileno())

    def publish_no_replace(self, temporary, destination):
        if self.stage == "publish":
            raise OSError("final publication failed")
        super().publish_no_replace(temporary, destination)

    def cleanup(self, temporary):
        self.cleanup_calls += 1
        if self.cleanup_once and self.cleanup_calls == 1:
            raise OSError("transient cleanup failed")
        super().cleanup(temporary)


@pytest.mark.parametrize("stage", ["create", "write", "flush", "fsync", "publish"])
def test_public_native_save_bridge_filesystem_failures_leave_no_partial_file(tmp_path, monkeypatch, stage):
    payload, filename, run = _complete_request_fixture()
    routes, _, _ = _request_routes(payload, filename, run)
    destination = tmp_path / filename
    filesystem = _FailingSaveFileSystem(stage)
    with _controlled_loopback(routes) as (base, _):
        result, _ = _invoke_public_save(monkeypatch, base, str(destination), filesystem=filesystem)
    assert result["status"] == "error"
    expected_word = {"create": "creation", "publish": "publication"}.get(stage, stage)
    assert expected_word in result["message"]
    assert not destination.exists()
    _assert_no_save_residue(tmp_path)


def test_public_native_save_bridge_cleanup_failure_does_not_hide_original_failure(tmp_path, monkeypatch):
    payload, filename, run = _complete_request_fixture()
    routes, _, _ = _request_routes(payload, filename, run)
    filesystem = _FailingSaveFileSystem("write", cleanup_once=True)
    with _controlled_loopback(routes) as (base, _):
        result, _ = _invoke_public_save(monkeypatch, base, str(tmp_path / filename), filesystem=filesystem)
    assert result["status"] == "error"
    assert "payload write failed" in result["message"]
    assert filesystem.cleanup_calls == 2
    _assert_no_save_residue(tmp_path)


def test_complete_request_save_ui_states_overlap_guard_and_browser_fallback():
    node = os.environ.get("TIANXIA_VERIFIED_NODE") or shutil.which("node")
    if not node:
        pytest.fail("Verified Node.js is required for the complete-request save UI behavior test")
    module_path = ROOT / "static/complete_request_save.js"
    script = r'''
const assert = require("node:assert/strict");
const ui = require(process.argv[1]);
function surface() { return {button:{disabled:false}, status:{className:"",textContent:""}}; }
async function main() {
  let s = surface(), calls = 0, release;
  const pending = new Promise(resolve => { release = resolve; });
  const save = ui.createController({getRunId:()=>"cg1.run."+"d".repeat(32), getNativeSave:()=>async()=>{calls++; return pending;}, button:s.button, status:s.status, navigate:()=>assert.fail("native must not navigate")});
  const first = save();
  assert.equal(s.button.disabled, true); assert.match(s.status.textContent, /Saving/);
  assert.deepEqual(await save(), {status:"busy"}); assert.equal(calls, 1);
  release({status:"saved",path:"C:\\Owner\\exact.zip",bytes:42,sha256:"a".repeat(64)});
  assert.equal((await first).status,"saved"); assert.equal(s.button.disabled,false);
  assert.match(s.status.textContent,/C:\\Owner\\exact\.zip/); assert.match(s.status.className,/success/);

  s = surface();
  const cancel = ui.createController({getRunId:()=>"run",getNativeSave:()=>async()=>({status:"cancelled"}),button:s.button,status:s.status,navigate:()=>{}});
  assert.equal((await cancel()).status,"cancelled"); assert.equal(s.button.disabled,false); assert.match(s.status.textContent,/No file was written/);

  s = surface();
  const fail = ui.createController({getRunId:()=>"run",getNativeSave:()=>async()=>({status:"error",message:"Disk unavailable"}),button:s.button,status:s.status,navigate:()=>{}});
  assert.equal((await fail()).status,"error"); assert.equal(s.button.disabled,false); assert.match(s.status.className,/error/); assert.equal(s.status.textContent,"Disk unavailable");

  let navigated = ""; s = surface();
  const browser = ui.createController({getRunId:()=>"cg1.run.a/b",getNativeSave:()=>undefined,button:s.button,status:s.status,navigate:url=>{navigated=url;}});
  assert.equal((await browser()).status,"browser");
  assert.equal(navigated,"/api/character-creation/runs/cg1.run.a%2Fb/complete-request.zip"); assert.equal(s.button.disabled,false);
}
main().catch(error => { console.error(error); process.exitCode = 1; });
'''
    completed = subprocess.run([node, "-e", script, str(module_path)], text=True, capture_output=True, timeout=30)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_complete_request_native_save_validation_binds_zip_to_project_and_revision():
    payload, filename, run = _complete_request_fixture(receipt_v2=True)
    result = launcher._validate_complete_request_zip(payload, filename, run)
    assert result["bytes"] == len(payload)
    assert result["zip_crc"] == "PASS"
    assert result["path_safety"] == "PASS"
    assert result["manifest"] == "PASS"
    assert result["project_id"] == run["project_id"]
    assert result["project_revision"] == run["starting_revision"]
    assert result["request_payload_sha256"] == run["request_payload_sha256"]
    assert result["content_set_sha256"] == run["content_set_sha256"]


def test_complete_request_v2_receipt_rejects_changed_member_even_with_rebuilt_inner_sums():
    payload, filename, run = _complete_request_fixture(receipt_v2=True)
    entries = _zip_entries(payload)
    entries["PROMPT_INSTRUCTIONS.md"] += b"changed"
    entries["SHA256SUMS.txt"] = "".join(
        f"{hashlib.sha256(entries[name]).hexdigest()}  {name}\n"
        for name in sorted(entries) if name != "SHA256SUMS.txt"
    ).encode("ascii")
    with pytest.raises(RuntimeError, match="server-issued payload"):
        launcher._validate_complete_request_zip(_zip_with_entries(entries), filename, run)


def test_complete_request_native_save_rejects_cross_revision_or_unsafe_archive():
    payload, filename, run = _complete_request_fixture()
    altered = dict(run)
    altered["starting_revision"] = 8
    with pytest.raises(RuntimeError, match="bound to the current project"):
        launcher._validate_complete_request_zip(payload, filename, altered)

    unsafe = io.BytesIO()
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("../COMPLETE_REQUEST.json", b"bad")
    with pytest.raises(RuntimeError, match="contents or paths"):
        launcher._validate_complete_request_zip(unsafe.getvalue(), filename, run)


def test_untrusted_loaded_page_is_restored_to_local_factory():
    class FakeWindow:
        def __init__(self):
            self.loaded = []

        def get_current_url(self):
            return "https://example.com/escape"

        def load_url(self, url):
            self.loaded.append(url)

    instance = launcher.DedicatedWindowLauncher.__new__(launcher.DedicatedWindowLauncher)
    instance.url = "http://127.0.0.1:43123/"
    instance.window = FakeWindow()
    states = []
    instance.state_file = lambda state, **extra: states.append((state, extra))
    instance._on_loaded()
    assert instance.window.loaded == [instance.url]
    assert states[0][0] == "BLOCKED_UNTRUSTED_NAVIGATION"

def test_foundation_filename_is_prefilled_for_nontechnical_first_run():
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    assert f'id="foundationHandoffFilename" value="{FOUNDATION_NAME}"' in html


@pytest.mark.skipif(os.name != "nt", reason="Windows process-token identity gate")
def test_windows_process_principal_uses_the_current_process_token():
    from security.local_identity import ProcessPrincipalProvider

    principal = ProcessPrincipalProvider().current_principal()
    assert principal.provider == "windows_process_token"
    assert principal.security_identifier.startswith("S-1-")
    assert principal.display_name.strip()
