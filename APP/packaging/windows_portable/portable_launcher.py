from __future__ import annotations

import ctypes
import hashlib
import html
import io
import json
import logging
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
import webbrowser
import zipfile
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote, urlparse

import uvicorn

from app.api import create_app
from app.core import Settings, canonical_json, sha256_file, sha256_json
from app.runtime import PRIVATE_PYTHON_ENV
from product_bootstrap import ProductBootstrapService

FACTORY_NAME = "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"
FACTORY_SHA256 = "4daf167cf634f27efef4dd2f1c8700bb4b7037cc6234c32be1af90aea5916385"
FOUNDATION_NAME = "Tianxia_Foundation_FactoryApp_Handoff_v1_0.zip"
FOUNDATION_SHA256 = "df80217c64c0808190c85531095e5e78aa96ff6808be369915f36fbb4189771c"
APP_LABEL = "Tianxia Factory"
WINDOW_HOST = "pywebview-edgechromium"
WEBVIEW2_CLIENT_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
BROWSER_SENTINEL_ENV = "TIANXIA_BROWSER_LAUNCH_SENTINEL"

STATE_REPLACE_RETRY_SECONDS = 1.5
STATE_REPLACE_INITIAL_BACKOFF_SECONDS = 0.02
STATE_REPLACE_MAX_BACKOFF_SECONDS = 0.20
_TRANSIENT_WINDOWS_REPLACE_ERRORS = frozenset({5, 32, 33})


def owner_window_label() -> str:
    return str(os.environ.get("TIANXIA_WINDOW_TITLE") or APP_LABEL).strip() or APP_LABEL


def _is_transient_windows_replace_error(exc: BaseException, *, platform_name: str = os.name) -> bool:
    """Return whether an atomic replace hit a brief Windows sharing/access race."""

    winerror = getattr(exc, "winerror", None)
    if winerror in _TRANSIENT_WINDOWS_REPLACE_ERRORS:
        return True
    # CPython normally supplies winerror on Windows, but retain bounded retry
    # behavior for a bare Windows PermissionError rather than failing on the
    # first transient antivirus/indexer/acceptance-reader collision.
    return isinstance(exc, PermissionError) and platform_name == "nt" and winerror is None


def _publish_json_atomically(
    target: Path,
    payload: dict[str, Any],
    *,
    replace_func: Any = os.replace,
    monotonic_func: Any = time.monotonic,
    sleep_func: Any = time.sleep,
    retry_seconds: float = STATE_REPLACE_RETRY_SECONDS,
) -> None:
    """Publish complete JSON atomically, retrying only transient Windows replaces."""

    target.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())

        deadline = monotonic_func() + max(0.0, retry_seconds)
        backoff = STATE_REPLACE_INITIAL_BACKOFF_SECONDS
        while True:
            try:
                replace_func(temporary, target)
                return
            except OSError as exc:
                if not _is_transient_windows_replace_error(exc):
                    raise
                remaining = deadline - monotonic_func()
                if remaining <= 0:
                    raise
                sleep_func(min(backoff, remaining))
                backoff = min(backoff * 2, STATE_REPLACE_MAX_BACKOFF_SECONDS)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            logging.warning("Could not remove owned launcher-state temporary file: %s", temporary, exc_info=True)

LOADING_HTML = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tianxia Factory</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; display: grid; place-items: center;
         background: radial-gradient(circle at top, #253b55 0, #111923 52%, #090d12 100%);
         color: #f2f5f7; font-family: "Segoe UI", system-ui, sans-serif; }
  main { width: min(620px, calc(100vw - 48px)); padding: 42px; border: 1px solid #526579;
         border-radius: 16px; background: rgba(10, 16, 23, .92); box-shadow: 0 24px 70px rgba(0,0,0,.45);
         text-align: center; }
  h1 { margin: 0 0 12px; font-size: 32px; font-weight: 650; letter-spacing: .02em; }
  p { margin: 8px 0; color: #c9d4de; line-height: 1.5; }
  .spinner { width: 42px; height: 42px; margin: 26px auto; border: 4px solid #34495f;
             border-top-color: #d8b46a; border-radius: 50%; animation: spin 1s linear infinite; }
  button { margin-top: 22px; padding: 9px 18px; border-radius: 8px; border: 1px solid #6d7d8d;
           background: #172433; color: #f3f5f7; font: inherit; cursor: pointer; }
  button:hover { background: #213247; }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<main>
  <h1>Tianxia Factory</h1>
  <div class="spinner" aria-label="Loading"></div>
  <p>Starting the local Factory and preparing the rules catalog.</p>
  <p>The first start can take a little longer.</p>
  <button type="button" onclick="window.pywebview?.api.request_close()">Close</button>
</main>
</body>
</html>
"""

NAVIGATION_GUARD_JS = r"""
(() => {
  if (window.__tianxiaNavigationGuardInstalled) return;
  window.__tianxiaNavigationGuardInstalled = true;
  const trustedOrigin = window.location.origin;
  const externalHttpUrl = (raw) => {
    try {
      const value = new URL(raw, window.location.href);
      if (value.protocol !== 'http:' && value.protocol !== 'https:') return null;
      return value.origin === trustedOrigin ? null : value.href;
    } catch (_) {
      return null;
    }
  };
  document.addEventListener('click', (event) => {
    const anchor = event.target && event.target.closest ? event.target.closest('a[href]') : null;
    if (!anchor) return;
    let parsed;
    try { parsed = new URL(anchor.href, window.location.href); } catch (_) {
      event.preventDefault();
      return;
    }
    if (parsed.origin === trustedOrigin && (parsed.protocol === 'http:' || parsed.protocol === 'https:')) {
      if (anchor.target) anchor.removeAttribute('target');
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const external = externalHttpUrl(parsed.href);
    if (external) window.pywebview.api.open_external(external);
  }, true);
  document.addEventListener('submit', (event) => {
    const form = event.target;
    if (!form || !form.action) return;
    const external = externalHttpUrl(form.action);
    if (external) {
      event.preventDefault();
      event.stopPropagation();
      window.pywebview.api.open_external(external);
    }
  }, true);
  window.open = (raw) => {
    const external = externalHttpUrl(raw);
    if (external) window.pywebview.api.open_external(external);
    else if (raw) window.location.assign(new URL(raw, window.location.href).href);
    return null;
  };
})();
"""


@dataclass(frozen=True)
class PortablePaths:
    package_root: Path
    runtime_root: Path
    bundled_content: Path
    user_data: Path
    private_python: Path
    legacy_user_data: Path | None = None

    @staticmethod
    def default_user_data(package_root: Path, *, platform_name: str = os.name, environ: dict[str, str] | None = None) -> Path:
        env = environ if environ is not None else os.environ
        explicit = str(env.get("TIANXIA_FOUNDRY_DATA") or "").strip()
        if explicit:
            return Path(explicit).expanduser().resolve()
        if platform_name == "nt":
            local = str(env.get("LOCALAPPDATA") or "").strip()
            base = Path(local).expanduser() if local else Path.home() / "AppData" / "Local"
            return (base / APP_LABEL).resolve()
        return (package_root / "UserData").resolve()

    @classmethod
    def discover(cls) -> "PortablePaths":
        frozen = bool(getattr(sys, "frozen", False))
        package_root = Path(sys.executable).resolve().parent if frozen else Path(__file__).resolve().parents[2]
        runtime_root = Path(getattr(sys, "_MEIPASS", package_root)).resolve()
        legacy_user_data = (package_root / "UserData").resolve()
        return cls(
            package_root=package_root,
            runtime_root=runtime_root,
            bundled_content=package_root / "BundledContent",
            user_data=cls.default_user_data(package_root),
            private_python=package_root / "Runtime" / "PrivatePython" / "python.exe",
            legacy_user_data=legacy_user_data,
        )

    @property
    def webview_data(self) -> Path:
        return self.user_data / "WebView2"

    def settings(self) -> Settings:
        data = self.user_data
        return Settings(
            root_dir=self.runtime_root,
            data_dir=data,
            db_path=data / "Database" / "foundry.sqlite3",
            inbox_dir=data / "Inbox",
            exports_dir=data / "Exports",
            packs_dir=data / "InstalledContent",
            vendor_dir=data / "Vendor",
            logs_dir=data / "Logs",
            backups_dir=data / "Backups",
            security_dir=data / "security",
            factory_zip=self.bundled_content / FACTORY_NAME,
            fixture_path=None,
        )


def verify_exact(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"{label} is missing: {path}")
    actual = sha256_file(path)
    if actual != expected:
        raise RuntimeError(f"{label} failed SHA-256 verification. Expected {expected}; got {actual}.")


def migrate_legacy_owner_data(paths: PortablePaths) -> dict[str, Any]:
    """Copy legacy package-local owner data to the writable data root without overwriting."""
    source = paths.legacy_user_data
    target = paths.user_data
    report: dict[str, Any] = {"source": str(source) if source else None, "target": str(target), "copied": [], "preserved": [], "status": "NOT_REQUIRED"}
    if source is None or source.resolve() == target.resolve() or not source.is_dir():
        return report
    target.mkdir(parents=True, exist_ok=True)
    report["status"] = "MIGRATED_NON_DESTRUCTIVELY"
    for item in sorted(source.rglob("*"), key=lambda value: value.as_posix().casefold()):
        relative = item.relative_to(source)
        destination = target / relative
        if item.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        if destination.exists():
            report["preserved"].append(relative.as_posix())
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, destination)
        report["copied"].append(relative.as_posix())
    return report


def ensure_owner_layout(paths: PortablePaths) -> Settings:
    migration = migrate_legacy_owner_data(paths)
    settings = paths.settings()
    for directory in (
        settings.db_path.parent,
        settings.inbox_dir,
        settings.exports_dir,
        settings.packs_dir,
        settings.vendor_dir,
        settings.logs_dir,
        settings.backups_dir,
        settings.security_dir,
        paths.user_data / "secrets",
        paths.webview_data,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    report_path = settings.logs_dir / "first_run_data_migration.json"
    _publish_json_atomically(report_path, migration)
    return settings


def stage_bundled_content(paths: PortablePaths, settings: Settings) -> dict[str, Any]:
    factory = paths.bundled_content / FACTORY_NAME
    foundation = paths.bundled_content / FOUNDATION_NAME
    verify_exact(factory, FACTORY_SHA256, "Bundled Factory input")
    verify_exact(foundation, FOUNDATION_SHA256, "Bundled Foundation handoff")
    target = settings.inbox_dir / FOUNDATION_NAME
    if target.exists():
        if sha256_file(target) != FOUNDATION_SHA256:
            raise RuntimeError(
                f"The existing inbox file {target.name} differs from the bundled pinned handoff. "
                "Move or rename it, then restart; it was not overwritten."
            )
    else:
        target.write_bytes(foundation.read_bytes())
    return {"factory": str(factory), "foundation_inbox": str(target)}


def bootstrap(paths: PortablePaths, settings: Settings) -> dict[str, Any]:
    """Reuse the same authenticated, idempotent product bootstrap as Linux/source execution."""
    if not paths.private_python.is_file():
        raise RuntimeError(f"Private helper runtime is missing: {paths.private_python}")
    os.environ[PRIVATE_PYTHON_ENV] = str(paths.private_python)
    private_dir = str(paths.private_python.parent)
    os.environ["PATH"] = private_dir + os.pathsep + os.environ.get("PATH", "")
    os.environ["PYTHONUTF8"] = "1"
    staged = stage_bundled_content(paths, settings)
    report = ProductBootstrapService(settings).run()
    return {**report, **staged}


def _valid_runtime_version(value: Any) -> bool:
    text = str(value or "").strip()
    if not text or text == "0.0.0.0":
        return False
    numbers = [int(piece) for piece in re.findall(r"\d+", text)]
    return bool(numbers and any(number > 0 for number in numbers))


def detect_webview2_runtime(*, platform_name: str | None = None, winreg_module: Any = None) -> str | None:
    platform_name = os.name if platform_name is None else platform_name
    if platform_name != "nt":
        return None
    if winreg_module is None:
        import winreg as winreg_module  # type: ignore[no-redef]

    locations = (
        (winreg_module.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_GUID}"),
        (winreg_module.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_GUID}"),
        (winreg_module.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_GUID}"),
    )
    for hive, key_path in locations:
        try:
            with winreg_module.OpenKey(hive, key_path, 0, winreg_module.KEY_READ) as key:
                value, _ = winreg_module.QueryValueEx(key, "pv")
        except OSError:
            continue
        if _valid_runtime_version(value):
            return str(value).strip()
    return None


def _show_owner_error(message: str) -> None:
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, message, APP_LABEL, 0x10)  # type: ignore[attr-defined]
    else:
        print(f"{APP_LABEL}: {message}", file=sys.stderr)


def _safe_external_http_url(raw: str) -> str | None:
    try:
        parsed = urlparse(raw)
    except Exception:
        return None
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return None
    return raw


def _safe_complete_request_filename(filename: str) -> bool:
    return bool(
        isinstance(filename, str)
        and re.fullmatch(r"CG1_COMPLETE_REQUEST_[A-Za-z0-9._-]+_[a-f0-9]{12}\.zip", filename)
        and Path(filename).name == filename
        and "\\" not in filename
    )


def _safe_zip_member_name(name: str) -> bool:
    if not name or "\\" in name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return False
    parts = PurePosixPath(name.rstrip("/")).parts
    return bool(parts) and all(part not in {"", ".", ".."} for part in parts)


def _validate_complete_request_zip(
    payload: bytes,
    filename: str,
    run: dict[str, Any],
) -> dict[str, Any]:
    """Validate the exact server-produced CG1 request before showing Save As."""
    if not _safe_complete_request_filename(filename):
        raise RuntimeError("The Factory returned an unsafe complete-request filename.")
    if not payload or len(payload) > 32 * 1024 * 1024:
        raise RuntimeError("The complete request ZIP is empty or exceeds the bounded desktop limit.")
    expected_names = {"BINDING.json", "COMPLETE_REQUEST.json", "PROMPT_INSTRUCTIONS.md", "RESPONSE_SCHEMA.json", "SHA256SUMS.txt"}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)) or set(names) != expected_names or any(not _safe_zip_member_name(name) for name in names):
            raise RuntimeError("The complete request ZIP contents or paths are not the accepted request contract.")
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"The complete request ZIP failed CRC validation: {bad}")
        entries = {name: archive.read(name) for name in names}

    try:
        binding = json.loads(entries["BINDING.json"].decode("utf-8"))
        request = json.loads(entries["COMPLETE_REQUEST.json"].decode("utf-8"))
        response_schema = json.loads(entries["RESPONSE_SCHEMA.json"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("The complete request ZIP contains invalid JSON authority files.") from exc
    if not all(isinstance(value, dict) for value in (binding, request, response_schema)):
        raise RuntimeError("The complete request ZIP authority files are not JSON objects.")

    run_request = run.get("request") or {}
    project_id = run.get("project_id")
    starting_revision = int(run.get("starting_revision"))
    request_sha256 = str(run_request.get("request_sha256") or "")
    snapshot = request.get("typed_choice_snapshot") or {}
    expected_filename = f"CG1_COMPLETE_REQUEST_{project_id}_{request_sha256[:12]}.zip"
    if filename != expected_filename:
        raise RuntimeError("The complete request ZIP filename is not bound to this project and request revision.")
    if (
        request.get("project_id") != project_id
        or int(request.get("project_revision")) != starting_revision
        or request.get("request_sha256") != request_sha256
        or binding.get("project_id") != project_id
        or int(binding.get("project_revision")) != starting_revision
        or binding.get("request_sha256") != request_sha256
        or binding.get("content_lock_hash") != request.get("content_lock_hash")
        or binding.get("typed_choice_snapshot_sha256") != snapshot.get("snapshot_sha256")
        or request.get("content_lock_hash") != run_request.get("content_lock_hash")
        or snapshot.get("snapshot_sha256") != (run_request.get("typed_choice_snapshot") or {}).get("snapshot_sha256")
    ):
        raise RuntimeError("The complete request ZIP is not bound to the current project, revision, or typed choice snapshot.")
    unsigned_request = dict(request)
    unsigned_request.pop("request_sha256", None)
    if sha256_json(unsigned_request) != request_sha256:
        raise RuntimeError("The complete request ZIP request hash does not match its contents.")
    if response_schema.get("request_sha256") != request_sha256 or response_schema.get("schema") != "TianxiaFoundry.CharacterCreationPlan.v2":
        raise RuntimeError("The complete request ZIP response schema is not bound to this request.")

    declared: dict[str, str] = {}
    for line in entries["SHA256SUMS.txt"].decode("ascii").splitlines():
        if not line:
            continue
        digest, name = line.split("  ", 1)
        if name in declared or name not in entries or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise RuntimeError("The complete request ZIP checksum manifest is invalid.")
        declared[name] = digest
    actual = {name: hashlib.sha256(value).hexdigest() for name, value in entries.items() if name != "SHA256SUMS.txt"}
    if declared != actual:
        raise RuntimeError("The complete request ZIP checksum manifest does not match its contents.")
    return {
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "filename": filename,
        "project_id": project_id,
        "project_revision": starting_revision,
        "zip_crc": "PASS",
        "path_safety": "PASS",
        "contents": sorted(entries),
        "manifest": "PASS",
    }


class _CompleteRequestFileSystem:
    """Small private boundary for deterministic, fail-closed publication tests."""

    def create_temporary(self, parent: Path, filename: str) -> tuple[Path, Any]:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{filename}.",
            suffix=".tmp",
            dir=parent,
        )
        return Path(temporary_name), os.fdopen(descriptor, "wb")

    def sync(self, handle: Any) -> None:
        handle.flush()
        os.fsync(handle.fileno())

    def publish_no_replace(self, temporary: Path, destination: Path) -> None:
        # A same-directory hard link is atomic and fails if destination exists.
        # Removing the temporary name afterwards leaves exactly one final file.
        os.link(temporary, destination)

    def cleanup(self, temporary: Path) -> None:
        temporary.unlink(missing_ok=True)


def _publish_complete_request_zip(
    payload: bytes,
    destination: Path,
    *,
    filesystem: Any | None = None,
) -> None:
    """Publish validated bytes atomically without ever replacing an existing file."""
    filesystem = filesystem or _CompleteRequestFileSystem()
    if destination.exists():
        raise RuntimeError("The selected file already exists. Choose a new filename or location; it was not overwritten.")
    temporary: Path | None = None
    original_error: BaseException | None = None
    try:
        temporary, handle = filesystem.create_temporary(destination.parent, destination.name)
        with handle:
            handle.write(payload)
            filesystem.sync(handle)
        try:
            filesystem.publish_no_replace(temporary, destination)
        except FileExistsError as exc:
            raise RuntimeError(
                "The selected file already exists. Choose a new filename or location; it was not overwritten."
            ) from exc
    except BaseException as exc:
        original_error = exc
    finally:
        if temporary is not None:
            try:
                filesystem.cleanup(temporary)
            except Exception as cleanup_error:
                try:
                    filesystem.cleanup(temporary)
                except Exception as final_cleanup_error:
                    if original_error is None:
                        original_error = RuntimeError(
                            f"The temporary request file could not be removed: {final_cleanup_error}"
                        )
                    else:
                        logging.warning(
                            "Temporary complete-request cleanup also failed after the original save failure: %s; %s",
                            cleanup_error,
                            final_cleanup_error,
                        )
    if original_error is not None:
        raise original_error


class DesktopBridge:
    def __init__(self, launcher: "DedicatedWindowLauncher", *, save_filesystem: Any | None = None) -> None:
        # pywebview recursively inspects public js_api attributes. Keeping the
        # launcher public exposes the native WinForms window graph (including
        # AccessibilityObject cycles) and prevents the API bridge from loading.
        self._launcher = launcher
        self._save_filesystem = save_filesystem

    def open_external(self, raw_url: str) -> bool:
        url = _safe_external_http_url(raw_url)
        if not url:
            logging.warning("Blocked non-HTTP external navigation request")
            return False
        self._launcher.external_navigation_count += 1
        logging.info("Opening intentional external link with the system handler: %s", url)
        sentinel = os.environ.get(BROWSER_SENTINEL_ENV)
        if sentinel:
            Path(sentinel).write_text(url + "\n", encoding="utf-8")
            return True
        return bool(webbrowser.open(url, new=2))

    def request_close(self) -> bool:
        window = self._launcher.window
        if window is not None:
            window.destroy()
            return True
        return False

    def save_complete_request(self, run_id: str) -> dict[str, Any]:
        """Save exactly one validated CG1 request through the native Save As dialog."""
        if not re.fullmatch(r"cg1\.run\.[a-f0-9]{32}", str(run_id or "")):
            return {"status": "error", "message": "The complete request run identity is invalid."}
        try:
            base = self._launcher.url
            if not base:
                raise RuntimeError("The local Factory service is not ready for a bounded save.")
            receipt_url = f"{base}api/character-creation/runs/{quote(run_id, safe='')}/complete-request-save-receipt"
            request = urllib.request.Request(receipt_url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=30) as response:
                receipt_payload = response.read(256 * 1024 + 1)
                if len(receipt_payload) > 256 * 1024:
                    raise RuntimeError("The Factory returned an oversized complete-request save receipt.")
                run = json.loads(receipt_payload.decode("utf-8"))
            if run.get("schema") != "TianxiaFoundry.CompleteRequestSaveReceipt.v1":
                raise RuntimeError("The Factory returned an invalid complete-request save receipt.")
            run_id_from_response = run.get("run_id")
            if run_id_from_response != run_id:
                raise RuntimeError("The server run identity changed while preparing the request ZIP.")
            zip_url = f"{base}api/character-creation/runs/{quote(run_id, safe='')}/complete-request.zip"
            zip_request = urllib.request.Request(zip_url, headers={"Accept": "application/zip"})
            with urllib.request.urlopen(zip_request, timeout=60) as response:
                if response.headers.get_content_type() != "application/zip":
                    raise RuntimeError("The Factory did not return a ZIP for the complete request.")
                disposition = str(response.headers.get("Content-Disposition") or "")
                match = re.search(r'filename="([^"]+)"', disposition)
                filename = match.group(1) if match else ""
                payload = response.read(32 * 1024 * 1024 + 1)
            validation = _validate_complete_request_zip(payload, filename, run)
            if run.get("filename") != filename:
                raise RuntimeError("The complete-request filename changed after the server issued its save receipt.")
            import webview

            window = self._launcher.window
            if window is None:
                raise RuntimeError("The native Factory window is not available for Save As.")
            selected = window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=filename,
                file_types=("ZIP archives (*.zip)",),
            )
            if isinstance(selected, (list, tuple)):
                selected = selected[0] if selected else None
            if not selected:
                logging.info("Complete request save cancelled: %s", filename)
                return {"status": "cancelled", "filename": filename, **validation}
            requested_destination = Path(str(selected)).expanduser()
            if not requested_destination.is_absolute():
                raise RuntimeError("Choose a valid absolute destination in the Save As dialog.")
            destination = requested_destination.resolve(strict=False)
            if destination.name != filename or destination.suffix.casefold() != ".zip":
                raise RuntimeError("Choose the suggested .zip filename so the request identity remains verifiable.")
            if not destination.parent.is_dir():
                raise RuntimeError("The selected destination folder does not exist or is not usable.")
            _publish_complete_request_zip(payload, destination, filesystem=self._save_filesystem)
            result = {"status": "saved", "path": str(destination), **validation}
            logging.info("Complete request saved: %s", result)
            return result
        except Exception as exc:
            logging.exception("Bounded complete request save failed")
            return {"status": "error", "message": str(exc)}


class DedicatedWindowLauncher:
    def __init__(self) -> None:
        self.paths = PortablePaths.discover()
        self.settings = ensure_owner_layout(self.paths)
        self.log_path = self.settings.logs_dir / "Tianxia_Factory_Launcher.log"
        logging.basicConfig(
            filename=self.log_path,
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            encoding="utf-8",
            force=True,
        )
        self.server: uvicorn.Server | None = None
        self.server_thread: threading.Thread | None = None
        self.socket: socket.socket | None = None
        self.url: str | None = None
        self.window: Any = None
        self.webview2_runtime_version: str | None = None
        self.external_navigation_count = 0
        self._stop_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._startup_finished = threading.Event()
        self._close_requested = threading.Event()
        self._stopped = False

    def state_file(self, state: str, **extra: Any) -> None:
        payload = {
            "state": state,
            "pid": os.getpid(),
            "url": self.url,
            "log": str(self.log_path),
            "window_title": owner_window_label(),
            "window_host": WINDOW_HOST,
            "renderer": "edgechromium",
            "webview2_runtime_version": self.webview2_runtime_version,
            "default_browser_launch_attempted": False,
            "external_navigation_count": self.external_navigation_count,
            **extra,
        }
        target = self.settings.logs_dir / "launcher_state.json"
        with self._state_lock:
            _publish_json_atomically(target, payload)

    def _publish_failed_state(self, exc: BaseException, failure_traceback: str, *, context: str) -> None:
        """Record FAILED without allowing a second filesystem error to mask the first."""

        try:
            self.state_file("FAILED", error=str(exc), traceback=failure_traceback)
        except Exception:
            logging.exception(
                "Could not publish FAILED launcher state after %s; preserving original error: %s",
                context,
                exc,
            )

    def _is_trusted_url(self, current: str | None) -> bool:
        if not self.url or not current:
            return False
        expected = urlparse(self.url)
        actual = urlparse(current)
        return actual.scheme == expected.scheme and actual.hostname == expected.hostname and actual.port == expected.port

    def _on_loaded(self) -> None:
        if self.window is None:
            return
        try:
            current = self.window.get_current_url()
        except Exception:
            current = None
        if not self._is_trusted_url(current):
            if self.url and current:
                logging.warning("Blocked an untrusted top-level navigation in the Factory window: %s", current)
                self.state_file("BLOCKED_UNTRUSTED_NAVIGATION", blocked_url=current)
                try:
                    self.window.load_url(self.url)
                except Exception:
                    logging.exception("Could not restore the trusted local Factory page")
            return
        try:
            self.window.run_js(NAVIGATION_GUARD_JS)
            self.state_file("WINDOW_READY", page=current)
        except Exception:
            logging.exception("Could not install the trusted-window navigation guard")

    def _on_closing(self) -> bool:
        if not self._startup_finished.is_set():
            self._close_requested.set()
            self._stop_event.set()
            self.state_file("CLOSE_REQUESTED_DURING_STARTUP")
            self._show_closing_in_window()
            return False
        self.stop()
        return True

    def _on_closed(self) -> None:
        self.stop()

    def _start_worker(self) -> None:
        try:
            # A brand-new WebView2 profile can take substantially longer than a
            # warm profile to initialize on an otherwise healthy Windows host.
            # Keep this below the outer four-minute acceptance deadline while
            # allowing first-run runtime/profile setup to complete.
            if self.window is None or not self.window.events.loaded.wait(90):
                raise RuntimeError("The dedicated WebView2 window did not initialize correctly.")
            self.state_file("STARTING_SERVICE")
            result = bootstrap(self.paths, self.settings)
            if self._stop_event.is_set():
                logging.info("Startup cancelled after bootstrap")
                return
            logging.info("Bootstrap complete: %s", result)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", 0))
            sock.listen(2048)
            self.socket = sock
            port = int(sock.getsockname()[1])
            self.url = f"http://127.0.0.1:{port}/"
            app = create_app(self.settings)
            config = uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                log_level="info",
                access_log=False,
                log_config=None,
            )
            self.server = uvicorn.Server(config)
            self.server_thread = threading.Thread(
                target=lambda: self.server.run(sockets=[sock]),
                name="tianxia-local-service",
                daemon=False,
            )
            self.server_thread.start()
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if self._stop_event.is_set():
                    logging.info("Startup cancelled while waiting for the local service")
                    return
                try:
                    with urllib.request.urlopen(self.url + "api/health", timeout=2) as response:
                        if response.status == 200:
                            break
                except Exception:
                    time.sleep(0.25)
            else:
                raise RuntimeError("The local service did not become ready within 90 seconds.")
            if self._stop_event.is_set():
                return
            self.state_file("RUNNING", port=port)
            self.window.load_url(self.url)
        except Exception as exc:
            failure_traceback = traceback.format_exc()
            logging.exception("Startup failed")
            self._publish_failed_state(exc, failure_traceback, context="service startup")
            if not self._close_requested.is_set():
                self._show_failure_in_window(str(exc))
        finally:
            self._startup_finished.set()
            if self._close_requested.is_set() and self.window is not None:
                try:
                    self.window.destroy()
                except Exception:
                    logging.exception("Could not finish the requested startup close")

    def _show_closing_in_window(self) -> None:
        closing_html = r"""
<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Tianxia Factory</title>
<style>:root{color-scheme:dark}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#10151c;color:#f2f4f6;font-family:'Segoe UI',sans-serif}
main{max-width:620px;padding:38px;border:1px solid #536271;border-radius:14px;background:#1a2028;text-align:center}p{line-height:1.5;color:#d9dde2}</style></head>
<body><main><h1>Closing Tianxia Factory</h1><p>Finishing the current local setup step safely. This window will close automatically.</p></main></body></html>
"""
        try:
            if self.window is not None:
                self.window.load_html(closing_html)
        except Exception:
            logging.exception("Could not display the safe-closing state")

    def _show_failure_in_window(self, message: str) -> None:
        safe_message = html.escape(message)
        safe_log = html.escape(str(self.log_path))
        failure_html = f"""
<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{APP_LABEL}</title>
<style>:root{{color-scheme:dark}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#10151c;color:#f2f4f6;font-family:'Segoe UI',sans-serif}}
main{{max-width:680px;padding:38px;border:1px solid #6f4a4a;border-radius:14px;background:#1a2028}}h1{{margin-top:0}}p{{line-height:1.5;color:#d9dde2}}code{{word-break:break-all}}button{{padding:9px 18px;background:#27313d;color:white;border:1px solid #6f7c89;border-radius:8px}}</style></head>
<body><main><h1>Tianxia Factory could not start</h1><p>{safe_message}</p><p>Diagnostic log: <code>{safe_log}</code></p>
<button onclick="window.pywebview?.api.request_close()">Close</button></main></body></html>"""
        try:
            if self.window is not None:
                self.window.load_html(failure_html)
                return
        except Exception:
            logging.exception("Could not display the startup failure in the dedicated window")
        _show_owner_error(f"Tianxia Factory could not start.\n\n{message}\n\nSee the launcher log for details.")

    def stop(self) -> None:
        with self._stop_lock:
            if self._stopped:
                return
            self._stopped = True
        self._stop_event.set()
        logging.info("Stopping Tianxia Factory")
        if self.server is not None:
            self.server.should_exit = True
        if self.server_thread is not None:
            self.server_thread.join(timeout=15)
            if self.server_thread.is_alive() and self.server is not None:
                self.server.force_exit = True
                self.server_thread.join(timeout=5)
        if self.socket is not None:
            try:
                self.socket.close()
            except OSError:
                pass
        self.state_file("STOPPED")
        logging.info("Tianxia Factory stopped")

    def run(self) -> int:
        if os.name != "nt":
            message = "The packaged Tianxia Factory desktop window can run only on Windows 10 or Windows 11."
            self.state_file("FAILED", error=message)
            _show_owner_error(message)
            return 1

        self.webview2_runtime_version = detect_webview2_runtime()
        if not self.webview2_runtime_version:
            message = (
                "Tianxia Factory needs the Microsoft Edge WebView2 Runtime. "
                "Install or repair WebView2, then reopen Tianxia Factory. "
                "The Factory will not download it or open a normal browser automatically."
            )
            self.state_file("FAILED", error="WEBVIEW2_RUNTIME_MISSING")
            _show_owner_error(message)
            return 1

        try:
            import webview

            webview.settings["ALLOW_DOWNLOADS"] = False
            webview.settings["ALLOW_FILE_URLS"] = False
            webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
            webview.settings["SHOW_DEFAULT_MENUS"] = False
            bridge = DesktopBridge(self)
            self.window = webview.create_window(
                owner_window_label(),
                html=LOADING_HTML,
                js_api=bridge,
                width=1440,
                height=920,
                min_size=(1000, 700),
                resizable=True,
                background_color="#10151c",
                text_select=True,
                zoomable=True,
            )
            if self.window is None:
                raise RuntimeError("The dedicated WebView2 window could not be created.")
            self.window.events.loaded += self._on_loaded
            self.window.events.closing += self._on_closing
            self.window.events.closed += self._on_closed
            self.state_file("STARTING_WINDOW")
            webview.start(
                func=self._start_worker,
                gui="edgechromium",
                debug=False,
                private_mode=False,
                storage_path=str(self.paths.webview_data),
            )
            return 0
        except Exception as exc:
            failure_traceback = traceback.format_exc()
            logging.exception("Dedicated window host failed")
            self._publish_failed_state(exc, failure_traceback, context="dedicated window startup")
            _show_owner_error(
                "Tianxia Factory could not open its dedicated WebView2 window. "
                "Repair the Microsoft Edge WebView2 Runtime, then reopen the Factory. "
                f"Details were written to {self.log_path}."
            )
            return 1
        finally:
            self.stop()


def main() -> None:
    raise SystemExit(DedicatedWindowLauncher().run())


if __name__ == "__main__":
    main()
