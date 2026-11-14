"""Bounded loopback discovery and managed Lemonade lifecycle.

This module deliberately owns transport discovery and the bundled ``lemond``
process only.  It does not validate or materialize character data; callers
continue to use the existing provider and two-isolated-build pipeline.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import secrets
import socket
import subprocess
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

import httpx

from app.core import FoundryError, utcnow


DEFAULT_LOCAL_MODEL = "Qwen3-4B-GGUF"
DEFAULT_RECIPE = "llamacpp"
KNOWN_LOCAL_PORTS: tuple[int, ...] = (1234, 13305, 8080, *range(11434, 11451))
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
LOCAL_HTTP_TIMEOUT_SECONDS = 120
SETUP_DOWNLOAD_TIMEOUT_SECONDS = 1800
HEALTH_TIMEOUT_SECONDS = 90
MAX_DETECTION_RESPONSE_BYTES = 512 * 1024
LOGGER = logging.getLogger(__name__)

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _set_job_object_kill_on_close(kernel32: Any, job: Any) -> bool:
    """Apply the Windows kill-on-close limit before assigning a child."""

    limits = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    return bool(
        kernel32.SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        )
    )


def validate_local_endpoint(endpoint: str) -> str:
    """Validate a local OpenAI-compatible completion endpoint.

    Local profiles may only connect to an explicit loopback HTTP(S) URL.  No
    credentials, query strings, or fragments are accepted, which keeps the
    persisted selection safe to display and prevents accidental token leaks.
    """

    value = str(endpoint or "").strip()
    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").rstrip(".").lower()
    try:
        port = parsed.port
    except ValueError as exc:
        raise FoundryError(
            "LOCAL_AI_ENDPOINT_INVALID",
            "Local AI endpoints must use a valid loopback HTTP(S) port.",
        ) from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or hostname not in LOOPBACK_HOSTS
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise FoundryError(
            "LOCAL_AI_ENDPOINT_INVALID",
            "Local AI endpoints must be HTTP(S) loopback URLs without credentials, queries, or fragments.",
        )
    return value


def _endpoint_for(port: int, *, lemonade: bool) -> str:
    prefix = "/api/v1" if lemonade else "/v1"
    return f"http://127.0.0.1:{port}{prefix}/chat/completions"


def _bounded_json(response: httpx.Response) -> dict[str, Any] | list[Any] | None:
    try:
        body = response.content
    except Exception:
        return None
    if len(body) > MAX_DETECTION_RESPONSE_BYTES:
        return None
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, (dict, list)) else None


def _model_rows(value: Any) -> list[dict[str, Any]]:
    """Normalize common OpenAI and Lemonade model-list shapes."""

    if not isinstance(value, dict):
        return []
    rows = value.get("data")
    if rows is None:
        rows = value.get("models")
    if rows is None:
        rows = value.get("items")
    if not isinstance(rows, list):
        return []
    result: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, str):
            result.append({"id": row})
        elif isinstance(row, dict):
            model_id = row.get("id") or row.get("model") or row.get("name")
            if model_id is not None:
                result.append({**row, "id": str(model_id)})
    return result


def _health_is_ready(value: Any, status_code: int | None) -> bool:
    if status_code != 200:
        return False
    if not isinstance(value, dict):
        return True
    state = str(value.get("status") or value.get("state") or "").strip().lower()
    return state not in {"loading", "starting", "initializing", "unready", "not_ready", "error"}


def _human_runtime(*, lemonade: bool, health: Any, model: dict[str, Any] | None = None) -> str:
    if isinstance(model, dict):
        for key in ("runtime", "backend", "owned_by"):
            value = model.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(health, dict):
        for key in ("runtime", "backend", "server"):
            value = health.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "Lemonade" if lemonade else "llama.cpp / OpenAI-compatible"


def detect_local_models(
    *,
    transport: httpx.BaseTransport | None = None,
    ports: Iterable[int] | None = None,
    timeout_seconds: float = 0.35,
) -> list[dict[str, Any]]:
    """Probe only the documented local ports and return model-centric rows.

    ``ports`` is an injection point for tests, but values outside
    ``KNOWN_LOCAL_PORTS`` are ignored.  The function never scans arbitrary
    networks or consults process names.
    """

    selected = [int(port) for port in (ports if ports is not None else KNOWN_LOCAL_PORTS) if int(port) in KNOWN_LOCAL_PORTS]
    candidates: dict[tuple[str, str | None], dict[str, Any]] = {}
    timeout = httpx.Timeout(max(0.05, float(timeout_seconds)))
    try:
        client = httpx.Client(transport=transport, timeout=timeout, follow_redirects=False, trust_env=False)
    except TypeError:
        client = httpx.Client(transport=transport, timeout=timeout, follow_redirects=False)
    with client:
        for port in selected:
            health_results: list[tuple[str, httpx.Response, Any]] = []
            model_results: list[tuple[str, httpx.Response, Any]] = []
            for path in ("/health", "/v1/health", "/api/v1/health"):
                try:
                    response = client.get(f"http://127.0.0.1:{port}{path}")
                except httpx.HTTPError:
                    continue
                if 100 <= response.status_code < 600:
                    health_results.append((path, response, _bounded_json(response)))
            for path in ("/v1/models", "/api/v1/models"):
                try:
                    response = client.get(f"http://127.0.0.1:{port}{path}")
                except httpx.HTTPError:
                    continue
                if 100 <= response.status_code < 600:
                    model_results.append((path, response, _bounded_json(response)))

            if not health_results and not model_results:
                continue
            lemonade = port == 13305 or any(path.startswith("/api/v1/") for path, _, _ in model_results)
            health_value = next((value for _, _, value in health_results if value is not None), None)
            health_ready = any(_health_is_ready(value, response.status_code) for _, response, value in health_results)
            model_rows: list[dict[str, Any]] = []
            model_path = "/api/v1/models" if lemonade else "/v1/models"
            for path, response, value in model_results:
                if path == model_path and response.status_code == 200:
                    model_rows.extend(_model_rows(value))
            # If an implementation answered only the alternate route, retain
            # its models while still labeling the endpoint correctly.
            if not model_rows:
                for _, response, value in model_results:
                    if response.status_code == 200:
                        model_rows.extend(_model_rows(value))
            # Health/model aliases identify the server, but externally
            # detected selections use the standard OpenAI-compatible route.
            # The managed Lemonade process is the only caller that uses the
            # /api/v1 completion endpoint (see _prepare_once).
            endpoint = _endpoint_for(port, lemonade=False)
            for model in model_rows:
                model_id = str(model.get("id") or "").strip()
                if not model_id:
                    continue
                ready = health_ready and bool(model.get("ready", model.get("loaded", True)))
                state = "READY" if ready else "LOADING"
                row = {
                    "candidate_id": f"{'lemonade' if lemonade else 'local'}:{port}:{model_id}",
                    "display_name": model_id,
                    "model": model_id,
                    "endpoint": endpoint,
                    "base_url": endpoint.rsplit("/chat/completions", 1)[0],
                    "port": port,
                    "runtime": _human_runtime(lemonade=lemonade, health=health_value, model=model),
                    # A running external Lemonade server is still a detected
                    # local endpoint.  Reserve ``lemonade`` for the bundled
                    # manager-owned profile so it cannot be mistaken for the
                    # process this application supervises.
                    "provider_id": "local",
                    "ready": ready,
                    "status": state,
                    "loading": not ready,
                    "server_reachable": True,
                    "health_path": next((path for path, _, _ in health_results if path.startswith("/api/v1/") == lemonade), health_results[0][0] if health_results else None),
                    "model_path": next((path for path, _, _ in model_results if path.startswith("/api/v1/") == lemonade), model_results[0][0] if model_results else None),
                }
                candidates[(endpoint, model_id)] = row
            if not model_rows or not health_ready:
                # A live but still-loading server is useful to the UI even
                # before it publishes a model list. Keep that server row in
                # addition to model rows whose loading state is explicit.
                state = "READY" if health_ready else "LOADING"
                row = {
                    "candidate_id": f"{'lemonade' if lemonade else 'local'}:{port}:server",
                    "display_name": "Loading available models" if not health_ready else "Local server (no model list)",
                    "model": None,
                    "endpoint": endpoint,
                    "base_url": endpoint.rsplit("/chat/completions", 1)[0],
                    "port": port,
                    "runtime": _human_runtime(lemonade=lemonade, health=health_value),
                    "provider_id": "local",
                    "ready": False,
                    "status": state,
                    "loading": True,
                    "server_reachable": True,
                    "health_path": health_results[0][0] if health_results else None,
                    "model_path": model_results[0][0] if model_results else None,
                }
                candidates[(endpoint, None)] = row
    return sorted(candidates.values(), key=lambda row: (not row["ready"], row["provider_id"], row["port"], row["display_name"]))


class _WindowsJob:
    """Best-effort kill-on-close Job Object for a managed Windows child."""

    def __init__(self, process: subprocess.Popen[Any]):
        self.handle: int | None = None
        if os.name != "nt":
            return
        job = None
        process_handle = None
        kernel32 = None
        success = False
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            kernel32.CreateJobObjectW.restype = wintypes.HANDLE
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            kernel32.SetInformationJobObject.argtypes = [
                wintypes.HANDLE,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.DWORD,
            ]
            kernel32.SetInformationJobObject.restype = wintypes.BOOL
            kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
            job = kernel32.CreateJobObjectW(None, None)
            if not job:
                return
            if not _set_job_object_kill_on_close(kernel32, job):
                return
            process_handle = kernel32.OpenProcess(
                _PROCESS_SET_QUOTA | _PROCESS_TERMINATE,
                False,
                process.pid,
            )
            if not process_handle or not kernel32.AssignProcessToJobObject(job, process_handle):
                return
            self.handle = int(job)
            self._kernel32 = kernel32
            success = True
        except (AttributeError, OSError, TypeError, ctypes.ArgumentError):
            self.handle = None
        finally:
            if process_handle and kernel32 is not None:
                try:
                    kernel32.CloseHandle(process_handle)
                except Exception:
                    pass
            if not success and job and kernel32 is not None:
                try:
                    kernel32.CloseHandle(job)
                except Exception:
                    pass

    def close(self) -> None:
        if self.handle:
            try:
                self._kernel32.CloseHandle(wintypes.HANDLE(self.handle))
            except Exception:
                pass
            self.handle = None


class ManagedLemonadeRuntime:
    """Supervisor for the bundled Lemonade process."""

    def __init__(
        self,
        vendor_dir: Path,
        *,
        transport: httpx.BaseTransport | None = None,
        on_ready: Callable[[str, str, str], None] | None = None,
    ):
        self.vendor_dir = Path(vendor_dir).resolve()
        self.transport = transport
        self.on_ready = on_ready
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._process: subprocess.Popen[Any] | None = None
        self._job: _WindowsJob | None = None
        self._key: str | None = None
        self._port: int | None = None
        self._model = DEFAULT_LOCAL_MODEL
        self._endpoint: str | None = None
        self._state = "IDLE"
        self._error: str | None = None
        self._stages: list[dict[str, Any]] = []

    @property
    def auth_key(self) -> str | None:
        with self._lock:
            return self._key

    @property
    def endpoint(self) -> str | None:
        with self._lock:
            return self._endpoint

    @property
    def model(self) -> str:
        with self._lock:
            return self._model

    def _stage(self, name: str, state: str, message: str) -> None:
        row = {"stage": name, "state": state, "message": message, "at": utcnow()}
        with self._lock:
            self._stages.append(row)
        LOGGER.info("[local-ai] %s %s: %s", name, state, message)

    def status(self) -> dict[str, Any]:
        with self._lock:
            process_live = bool(self._process and self._process.poll() is None)
            return {
                "runtime": "Lemonade",
                "provider_id": "lemonade",
                "state": self._state,
                "ready": self._state == "READY" and process_live,
                "loading": self._state == "PREPARING",
                "model": self._model,
                "endpoint": self._endpoint,
                "port": self._port,
                "process_live": process_live,
                "stages": [dict(row) for row in self._stages],
                "error": self._error,
                "default_model": DEFAULT_LOCAL_MODEL,
                "recipe": DEFAULT_RECIPE,
            }

    def select(self, model: str | None = None) -> dict[str, Any]:
        model_value = self._validated_model(model)
        with self._lock:
            self._model = model_value
        return self.status()

    @staticmethod
    def _validated_model(model: str | None) -> str:
        model_value = str(model or DEFAULT_LOCAL_MODEL).strip()
        if not model_value or len(model_value) > 100:
            raise FoundryError("LOCAL_AI_MODEL_INVALID", "The managed Local AI model must be 1-100 characters.")
        return model_value

    def prepare(self, model: str | None = None) -> dict[str, Any]:
        model_value = self._validated_model(model)
        with self._lock:
            process_live = bool(self._process and self._process.poll() is None)
            if process_live and self._state == "READY":
                return self.status()
            if process_live or (self._thread and self._thread.is_alive()):
                return self.status()
            self._model = model_value
            self._stop_event.clear()
            self._state = "PREPARING"
            self._error = None
            self._endpoint = None
            self._stages = []
            self._thread = threading.Thread(target=self._prepare_worker, name="tianxia-lemonade-setup", daemon=True)
            self._thread.start()
            return self.status()

    def _executable(self) -> Path:
        names = ("lemond.exe", "lemond") if os.name == "nt" else ("lemond", "lemond.exe")
        for name in names:
            path = self.vendor_dir / name
            if path.is_file():
                return path
        raise FoundryError("LOCAL_AI_LEMONDADE_MISSING", "The bundled Lemonade runtime (lemond) is not present.")

    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _client(self, *, timeout: float) -> httpx.Client:
        headers = {"Accept": "application/json"}
        if self.auth_key:
            headers["Authorization"] = "Bearer " + self.auth_key
        try:
            return httpx.Client(
                transport=self.transport,
                timeout=httpx.Timeout(timeout),
                follow_redirects=False,
                trust_env=False,
                headers=headers,
            )
        except TypeError:
            return httpx.Client(transport=self.transport, timeout=httpx.Timeout(timeout), follow_redirects=False, headers=headers)

    def _request(self, method: str, path: str, *, timeout: float, json_body: dict[str, Any] | None = None) -> tuple[int, Any]:
        port = self._port
        if port is None:
            raise RuntimeError("managed Lemonade port is not assigned")
        with self._client(timeout=timeout) as client:
            try:
                response = client.request(method, f"http://127.0.0.1:{port}{path}", json=json_body)
            except httpx.HTTPError as exc:
                raise RuntimeError(f"HTTP probe failed: {type(exc).__name__}") from exc
            return response.status_code, _bounded_json(response)

    def _ensure_config(self, port: int) -> None:
        """Keep the mutable runtime config on the supported Lemonade v2 shape."""

        config_path = self.vendor_dir / "config.json"
        config: dict[str, Any] = {}
        if config_path.is_file():
            try:
                value = json.loads(config_path.read_text(encoding="utf-8"))
                if isinstance(value, dict):
                    config = value
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                config = {}
        config["config_version"] = 2
        config["broadcast"] = False
        config["host"] = "127.0.0.1"
        config["port"] = port
        existing_timeout = config.get("global_timeout")
        try:
            config["global_timeout"] = max(600, int(existing_timeout))
        except (TypeError, ValueError):
            config["global_timeout"] = 600
        config["max_loaded_models"] = 2
        config["ctx_size"] = 8192
        config["log_level"] = "warning"
        telemetry = config.get("telemetry") if isinstance(config.get("telemetry"), dict) else {}
        telemetry["enabled"] = False
        config["telemetry"] = telemetry
        config["models_dir"] = str(self.vendor_dir / "models")
        llamacpp = config.get("llamacpp") if isinstance(config.get("llamacpp"), dict) else {}
        llamacpp["backend"] = "auto"
        llamacpp["prefer_system"] = False
        config["llamacpp"] = llamacpp
        config.pop("no_broadcast", None)
        config.pop("llamacpp_backend", None)
        config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @staticmethod
    def _state_for_backend(info: Any, backend: str) -> str:
        if not isinstance(info, dict):
            return "unknown"
        pending: list[Any] = [info]
        while pending:
            value = pending.pop()
            if not isinstance(value, dict):
                continue
            entry = value.get(backend)
            if isinstance(entry, dict):
                state = entry.get("status") or entry.get("state")
                if state:
                    return str(state).lower()
                if entry.get("installed") is True:
                    return "installed"
                if entry.get("installable") is True:
                    return "installable"
            elif isinstance(entry, str):
                return entry.lower()
            pending.extend(child for child in value.values() if isinstance(child, dict))
        return "unknown"

    def _install_backend(self) -> str:
        self._stage("backend", "STARTED", "checking Lemonade system-info for an installable backend")
        try:
            info_status, info = self._request("GET", "/api/v1/system-info", timeout=5)
        except Exception as exc:
            self._stage("backend", "WARN", f"system-info unavailable; using Vulkan fallback ({type(exc).__name__})")
            self._stage("backend", "READY", "llamacpp:vulkan selected after system-info fallback")
            return "vulkan"
        rocm_state = self._state_for_backend(info, "rocm")
        if info_status == 200 and rocm_state in {"installed", "available"}:
            self._stage("backend", "READY", "llamacpp:rocm is already installed")
            return "rocm"
        if info_status == 200 and rocm_state in {"installable", "missing", "not_installed"}:
            try:
                status, _ = self._request(
                    "POST", "/api/v1/install", timeout=SETUP_DOWNLOAD_TIMEOUT_SECONDS,
                    json_body={"recipe": DEFAULT_RECIPE, "backend": "rocm"},
                )
                if status in {200, 201, 202, 204}:
                    self._stage("backend", "READY", "llamacpp:rocm installed or already available")
                    return "rocm"
            except Exception as exc:
                self._stage("backend", "WARN", f"rocm install failed; falling back to Vulkan ({type(exc).__name__})")
        vulkan_state = self._state_for_backend(info, "vulkan")
        if vulkan_state in {"installed", "available"}:
            self._stage("backend", "READY", "llamacpp:vulkan is already installed")
            return "vulkan"
        if vulkan_state in {"unknown", "installable", "missing", "not_installed"}:
            try:
                status, _ = self._request(
                    "POST", "/api/v1/install", timeout=SETUP_DOWNLOAD_TIMEOUT_SECONDS,
                    json_body={"recipe": DEFAULT_RECIPE, "backend": "vulkan"},
                )
                if status not in {200, 201, 202, 204}:
                    self._stage("backend", "WARN", f"Vulkan install returned HTTP {status}; continuing with bundled fallback")
            except Exception as exc:
                self._stage("backend", "WARN", f"Vulkan install probe failed; using bundled fallback ({type(exc).__name__})")
        self._stage("backend", "READY", "llamacpp:vulkan selected as the universal fallback")
        return "vulkan"

    def _prepare_once(self) -> None:
        with self._lock:
            if self._stop_event.is_set():
                raise RuntimeError("managed Local AI setup was stopped")
            if self._process and self._process.poll() is None:
                if self._state == "READY":
                    return
                raise RuntimeError("managed Lemonade already has a live process")
        executable = self._executable()
        port = self._free_port()
        key = secrets.token_urlsafe(32)
        self._ensure_config(port)
        with self._lock:
            if self._stop_event.is_set():
                raise RuntimeError("managed Local AI setup was stopped")
            self._port = port
            self._key = key
        environment = os.environ.copy()
        environment["LEMONADE_API_KEY"] = key
        self._stage("spawn", "STARTED", f"starting bundled lemond on loopback port {port}")
        process = subprocess.Popen(
            [str(executable), str(self.vendor_dir), "--port", str(port)],
            cwd=str(self.vendor_dir),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        try:
            job = _WindowsJob(process)
        except Exception:
            self._terminate_process(process, None)
            raise
        with self._lock:
            process_rejected = self._stop_event.is_set() or bool(self._process and self._process.poll() is None)
            if not process_rejected:
                self._process = process
                self._job = job
        if process_rejected:
            self._terminate_process(process, job)
            raise RuntimeError("managed Local AI setup was stopped or another process became live")
        self._stage("spawn", "READY", f"lemond process started (pid {process.pid})")
        deadline = time.monotonic() + HEALTH_TIMEOUT_SECONDS
        while time.monotonic() < deadline and not self._stop_event.is_set():
            if process.poll() is not None:
                raise RuntimeError(f"lemond exited with code {process.returncode}")
            try:
                status, _ = self._request("GET", "/api/v1/health", timeout=2)
                if status == 200:
                    self._stage("health", "READY", f"lemond health passed on port {port}")
                    break
            except Exception:
                pass
            time.sleep(0.25)
        else:
            raise RuntimeError("lemond health did not become ready within 90 seconds")
        if self._stop_event.is_set():
            raise RuntimeError("managed Local AI setup was stopped")
        self._install_backend()
        if self._stop_event.is_set():
            raise RuntimeError("managed Local AI setup was stopped")
        model = self.model
        self._stage("model", "STARTED", f"pulling {model}")
        status, _ = self._request(
            "POST", "/api/v1/pull", timeout=SETUP_DOWNLOAD_TIMEOUT_SECONDS,
            json_body={"model_name": model, "stream": False},
        )
        if status not in {200, 201, 202, 204}:
            raise RuntimeError(f"model pull returned HTTP {status}")
        if self._stop_event.is_set():
            raise RuntimeError("managed Local AI setup was stopped")
        self._stage("model", "READY", f"model {model} is available")
        endpoint = _endpoint_for(port, lemonade=True)
        with self._lock:
            self._endpoint = endpoint
            self._state = "READY"
        self._stage("ready", "READY", f"managed Local AI ready at {endpoint}")
        if self.on_ready:
            self.on_ready(endpoint, model, key)

    @staticmethod
    def _terminate_process(process: subprocess.Popen[Any] | None, job: _WindowsJob | None) -> None:
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=10)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    process.kill()
                    process.wait(timeout=10)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        if job:
            job.close()

    def _cleanup_process(self) -> None:
        with self._lock:
            process, job = self._process, self._job
            self._process = None
            self._job = None
        self._terminate_process(process, job)

    def _prepare_worker(self) -> None:
        for attempt in range(1, 4):
            try:
                self._prepare_once()
                return
            except Exception as exc:
                if self._stop_event.is_set():
                    with self._lock:
                        self._state = "STOPPED"
                        self._error = None
                    return
                self._stage("error", "FAILED", f"setup attempt {attempt} failed: {exc}")
                self._cleanup_process()
                if attempt < 3 and not self._stop_event.is_set():
                    continue
                with self._lock:
                    self._state = "ERROR"
                    self._error = str(exc)
                return

    def stop(self) -> None:
        self._stop_event.set()
        self._cleanup_process()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=10)
        with self._lock:
            self._state = "STOPPED"
            self._endpoint = None
            self._port = None
            self._key = None
        self._stage("shutdown", "READY", "managed Lemonade process stopped")


class LocalAIManager:
    """Combined detector and managed-runtime facade used by FastAPI."""

    def __init__(
        self,
        vendor_dir: Path,
        *,
        transport: httpx.BaseTransport | None = None,
        detector_ports: Iterable[int] | None = None,
        on_managed_ready: Callable[[str, str, str], None] | None = None,
    ):
        self.transport = transport
        self.detector_ports = tuple(detector_ports) if detector_ports is not None else None
        self.last_detection: list[dict[str, Any]] = []
        self.managed = ManagedLemonadeRuntime(vendor_dir, transport=transport, on_ready=on_managed_ready)

    def detect(self, *, ports: Iterable[int] | None = None) -> dict[str, Any]:
        probe_ports = self.detector_ports if ports is None else tuple(ports)
        self.last_detection = detect_local_models(transport=self.transport, ports=probe_ports)
        bundled = {
            "candidate_id": "lemonade:bundled",
            "display_name": "Built-in Local AI (Lemonade)",
            "model": DEFAULT_LOCAL_MODEL,
            "endpoint": self.managed.endpoint,
            "base_url": self.managed.endpoint.rsplit("/chat/completions", 1)[0] if self.managed.endpoint else None,
            "port": self.managed.status().get("port"),
            "runtime": "Lemonade 11.x bundled",
            "provider_id": "lemonade",
            "ready": bool(self.managed.status().get("ready")),
            "status": "READY" if self.managed.status().get("ready") else "NOT_STARTED",
            "loading": bool(self.managed.status().get("loading")),
            "server_reachable": bool(self.managed.status().get("process_live")),
            "managed": True,
        }
        return {"candidates": [bundled, *self.last_detection], "known_ports": list(KNOWN_LOCAL_PORTS), "managed": self.managed.status()}

    def status(self) -> dict[str, Any]:
        return {
            "candidates": [dict(row) for row in self.last_detection],
            "known_ports": list(KNOWN_LOCAL_PORTS),
            "managed": self.managed.status(),
        }

    def stop(self) -> None:
        self.managed.stop()
