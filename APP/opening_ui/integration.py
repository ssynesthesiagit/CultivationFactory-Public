"""Namespaced bridge from the Factory FastAPI app to the opening controller.

The existing Character Foundry routes remain authoritative for creation and
project state.  This module only exposes the accepted opening gameplay service
under ``/opening`` and ``/api/opening/*``.  Package and producer selection are
server-owned configuration; request bodies contain gameplay actions only.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Mapping
import zipfile

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core import Settings

from .server import CampaignService, UiError


_STATIC_ROOT = Path(__file__).resolve().parent / "static"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


class OpeningRuntime:
    """Own one server-selected package and one serialized opening campaign."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.data_root = (settings.data_dir / "opening_campaign").resolve()
        self._service: CampaignService | None = None
        self._selected: tuple[Path, Path] | None = None
        self._lock = RLock()

    @property
    def service(self) -> CampaignService | None:
        return self._service

    @staticmethod
    def _regular_file(path: Path) -> bool:
        try:
            return path.is_file() and not path.is_symlink()
        except OSError:
            return False

    @staticmethod
    def _regular_directory(path: Path) -> bool:
        try:
            return path.is_dir() and not path.is_symlink()
        except OSError:
            return False

    def _validate_selection(self, package: Path, producer_root: Path) -> tuple[Path, Path]:
        package_input = package.expanduser()
        producer_input = producer_root.expanduser()
        if package_input.is_symlink():
            raise UiError("OPENING_PACKAGE_UNAVAILABLE", "The validated mortal record is unavailable", status=503)
        if producer_input.is_symlink():
            raise UiError("OPENING_PRODUCER_UNAVAILABLE", "The current creator binding is unavailable", status=503)
        package = package_input.resolve()
        producer_root = producer_input.resolve()
        if not self._regular_file(package):
            raise UiError("OPENING_PACKAGE_UNAVAILABLE", "The validated mortal record is unavailable", status=503)
        app_root = producer_root / "APP"
        if producer_root.name == "APP":
            app_root = producer_root
        if not self._regular_directory(producer_root) or not self._regular_directory(app_root):
            raise UiError("OPENING_PRODUCER_UNAVAILABLE", "The current creator binding is unavailable", status=503)
        return package, producer_root

    def _configured_from_environment(self) -> tuple[Path, Path] | None:
        package_value = os.environ.get("TIANXIA_OPENING_PACKAGE") or os.environ.get("FACTORY_OPENING_UI_PACKAGE")
        producer_value = os.environ.get("TIANXIA_OPENING_PRODUCER_ROOT") or os.environ.get("FACTORY_OPENING_UI_PRODUCER_ROOT")
        if bool(package_value) != bool(producer_value):
            raise UiError("OPENING_CONFIGURATION_INVALID", "Opening package and producer must be configured together", status=503)
        if not package_value:
            return None
        return self._validate_selection(Path(package_value), Path(producer_value))

    def _discovered_package(self) -> tuple[Path, Path] | None:
        """Select an installed source-validated mortal package by server state."""

        root = self.settings.data_dir / "portable_characters"
        if not self._regular_directory(root):
            return None
        for pointer in sorted(root.glob("*/current.json")):
            if pointer.is_symlink() or not pointer.is_file():
                continue
            install_root = pointer.parent
            package = install_root / "current.zip"
            if not self._regular_file(package):
                continue
            try:
                pointer_value = json.loads(pointer.read_text(encoding="utf-8"))
                expected = pointer_value.get("package_sha256")
                actual = hashlib.sha256(package.read_bytes()).hexdigest()
                if not isinstance(expected, str) or expected != actual:
                    continue
                with zipfile.ZipFile(package) as archive:
                    manifest = json.loads(archive.read("PACKAGE_MANIFEST.json"))
                if manifest.get("build_profile") != "MORTAL_LEVEL0_SOURCE_VALIDATED":
                    continue
                if manifest.get("level0_authority", {}).get("authoritative") is not True:
                    continue
            except (OSError, ValueError, KeyError, TypeError, UnicodeError, json.JSONDecodeError, zipfile.BadZipFile):
                continue
            return self._validate_selection(package, self.settings.root_dir)
        return None

    def _selection(self) -> tuple[Path, Path] | None:
        if self._selected is not None:
            return self._selected
        selected = self._configured_from_environment()
        if selected is None:
            selected = self._discovered_package()
        if selected is not None:
            self._selected = selected
        return selected

    def configured(self) -> bool:
        with self._lock:
            return self._selection() is not None

    def _allow_local_tests(self) -> bool:
        value = os.environ.get("TIANXIA_OPENING_ALLOW_LOCAL_TESTS")
        if value is None:
            value = os.environ.get("FACTORY_OPENING_UI_ALLOW_LOCAL_TESTS", "")
        return value.strip().lower() in _TRUTHY

    def _require_service(self) -> CampaignService:
        with self._lock:
            if self._service is not None:
                return self._service
            selection = self._selection()
            if selection is None:
                raise UiError("OPENING_PACKAGE_NOT_CONFIGURED", "A server-selected mortal record is required", status=503)
            package, producer_root = selection
            try:
                service = CampaignService(
                    data_root=self.data_root,
                    package_path=package,
                    producer_root=producer_root,
                    allow_local_tests=self._allow_local_tests(),
                )
            except UiError:
                raise
            except Exception as exc:
                raise UiError("OPENING_CAMPAIGN_UNAVAILABLE", "The saved opening campaign is unavailable", status=500) from exc
            self._service = service
            return service

    def session(self, session_token: str) -> dict[str, Any]:
        with self._lock:
            result: dict[str, Any] = {
                "ok": True,
                "token": session_token,
                "configured": self.configured(),
                "started": False,
            }
            if self.configured():
                service = self._require_service()
                result["started"] = service.started
                if service.started:
                    result["state"] = service.player_projection()
            return result

    def call(self, operation: str, body: Mapping[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            service = self._require_service()
            if operation in {"launch", "reopen"}:
                if body:
                    raise UiError("INVALID_REQUEST_FIELDS", status=400)
                result = getattr(service, operation)()
            elif operation in {"action", "local_test"}:
                if body is None:
                    raise UiError("REQUEST_BODY_INVALID", status=400)
                result = getattr(service, operation)(body)
            else:
                raise UiError("OPENING_OPERATION_UNSUPPORTED", status=500)
            return {"ok": True, **result}


def _error_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, UiError):
        return JSONResponse(
            status_code=exc.status,
            content={"ok": False, "error": {"code": exc.code, "message": str(exc)}},
        )
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "error": {
                "code": "OPENING_REQUEST_FAILED",
                "message": "The opening service failed to complete the request",
            },
        },
    )


async def _json_object(request: Request) -> dict[str, Any]:
    try:
        value = await request.json()
    except (ValueError, UnicodeDecodeError) as exc:
        raise UiError("REQUEST_BODY_INVALID", status=400) from exc
    if not isinstance(value, dict):
        raise UiError("REQUEST_BODY_INVALID", status=400)
    return value


def register_opening_routes(
    app: FastAPI,
    *,
    settings: Settings,
    session_token: Callable[[], str],
) -> OpeningRuntime:
    """Register the isolated opening UI routes on the existing Factory app."""

    runtime = OpeningRuntime(settings)
    app.state.opening_runtime = runtime
    app.mount("/opening/static", StaticFiles(directory=_STATIC_ROOT), name="opening-static")

    @app.get("/opening", include_in_schema=False)
    def opening_index() -> FileResponse:
        return FileResponse(_STATIC_ROOT / "index.html")

    @app.get("/api/opening/session", include_in_schema=False)
    def opening_session() -> JSONResponse:
        try:
            return JSONResponse(runtime.session(session_token()))
        except Exception as exc:
            return _error_response(exc)

    @app.post("/api/opening/launch", include_in_schema=False)
    async def opening_launch(request: Request) -> JSONResponse:
        try:
            return JSONResponse(runtime.call("launch", await _json_object(request)))
        except Exception as exc:
            return _error_response(exc)

    @app.post("/api/opening/reopen", include_in_schema=False)
    async def opening_reopen(request: Request) -> JSONResponse:
        try:
            return JSONResponse(runtime.call("reopen", await _json_object(request)))
        except Exception as exc:
            return _error_response(exc)

    @app.post("/api/opening/action", include_in_schema=False)
    async def opening_action(request: Request) -> JSONResponse:
        try:
            return JSONResponse(runtime.call("action", await _json_object(request)))
        except Exception as exc:
            return _error_response(exc)

    @app.post("/api/opening/local-test", include_in_schema=False)
    async def opening_local_test(request: Request) -> JSONResponse:
        try:
            return JSONResponse(runtime.call("local_test", await _json_object(request)))
        except Exception as exc:
            return _error_response(exc)

    return runtime
