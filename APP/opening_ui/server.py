"""Small loopback player entry for the accepted mortal gameplay service.

The browser is a client of the canonical CampaignController.  It never receives
the producer root, package bytes, profile or GM projection, and it cannot choose
an actor or principal.  Campaign revisions are saved with the controller's
create-once persistence format; ``latest.json`` is only a private server
pointer to the newest revision.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Mapping
from urllib.parse import urlsplit

from services.factory_dm_v0.domain import CampaignIdentity, DeterministicClock, Faction, Location
from services.factory_dm_v0.engine import CampaignController, EngineError
from services.factory_dm_v0.gameplay.character_adapter import (
    AdmissionError,
    admission_from_trusted_portable_package,
)
from services.factory_dm_v0.gameplay.integration import effect_payload
from services.factory_dm_v0.gameplay.models import Item
from services.factory_dm_v0.gameplay.profile import identity, manifest


REQUEST_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
PLAYER_ACTIONS = frozenset({
    "short_rest",
    "spend_hit_die",
    "take_starter_item",
    "drop_starter_item",
})
LOCAL_ACTIONS = frozenset({"damage", "poison", "advance_time"})
STATIC_FILES = {
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/static/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


class UiError(RuntimeError):
    """A safe, structured HTTP boundary error."""

    def __init__(self, code: str, message: str | None = None, *, status: int = 409):
        self.code = code
        self.status = status
        super().__init__(message or code)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise UiError("CAMPAIGN_POINTER_INVALID", status=500)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UiError("CAMPAIGN_POINTER_INVALID", status=500) from exc
    if not isinstance(value, dict):
        raise UiError("CAMPAIGN_POINTER_INVALID", status=500)
    return value


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


class CampaignService:
    """One serialized controller and one fixed scratch campaign."""

    def __init__(self, *, data_root: Path, package_path: Path, producer_root: Path, allow_local_tests: bool = False):
        self.data_root = data_root.resolve()
        self.revisions_root = self.data_root / "revisions"
        self.latest_path = self.data_root / "latest.json"
        self.requests_path = self.data_root / "requests.json"
        self.package_path = package_path.resolve()
        self.producer_root = producer_root.resolve()
        self.allow_local_tests = bool(allow_local_tests)
        self.csrf_token = secrets.token_urlsafe(32)
        self.controller: CampaignController | None = None
        self.actor_id: str | None = None
        self.latest_save: Path | None = None
        self.request_log: dict[str, dict[str, Any]] = {}
        self._load_existing()

    @property
    def started(self) -> bool:
        return self.controller is not None and self.actor_id is not None

    def _load_existing(self) -> None:
        if not self.latest_path.exists():
            if self.requests_path.exists():
                raise UiError("CAMPAIGN_POINTER_INVALID", status=500)
            return
        pointer = _read_json(self.latest_path)
        relative = pointer.get("save_dir")
        actor_id = pointer.get("actor_id")
        if not isinstance(relative, str) or not isinstance(actor_id, str) or not relative:
            raise UiError("CAMPAIGN_POINTER_INVALID", status=500)
        target = (self.data_root / relative).resolve()
        try:
            target.relative_to(self.revisions_root.resolve())
        except ValueError as exc:
            raise UiError("CAMPAIGN_POINTER_INVALID", status=500) from exc
        self.controller = CampaignController.load(target)
        if actor_id not in self.controller.view().get("gameplay", {}).get("actors", {}):
            raise UiError("CAMPAIGN_POINTER_INVALID", status=500)
        self.actor_id = actor_id
        self.latest_save = target
        if self.requests_path.exists():
            value = _read_json(self.requests_path)
            if not all(isinstance(key, str) and isinstance(item, dict) for key, item in value.items()):
                raise UiError("REQUEST_LOG_INVALID", status=500)
            self.request_log = value

    def _require_started(self) -> tuple[CampaignController, str]:
        if self.controller is None or self.actor_id is None:
            raise UiError("CAMPAIGN_NOT_STARTED", "Launch the temporary campaign first", status=409)
        return self.controller, self.actor_id

    def _save_revision(self) -> dict[str, Any]:
        controller, actor_id = self._require_started()
        self.revisions_root.mkdir(parents=True, exist_ok=True)
        event_count = controller.event_count()
        # Every save attempt gets a fresh immutable directory.  If publication
        # of latest.json fails after controller.save, the orphan remains as
        # evidence and a retry can publish a new attempt without colliding.
        target = self.revisions_root / f"event-{event_count:06d}-{secrets.token_hex(6)}"
        if target.exists() or target.is_symlink():
            raise UiError("SAVE_FAILED", "The create-once revision already exists", status=500)
        try:
            saved = controller.save(target)
            pointer = {
                "schema": "factory-opening-ui-pointer-v1",
                "campaign_id": controller.campaign_id(),
                "actor_id": actor_id,
                "save_dir": str(target.relative_to(self.data_root)),
                "event_count": event_count,
                "state_digest": saved["state_digest"],
                "profile_digest": identity()["digest"],
            }
            _atomic_json(self.latest_path, pointer)
        except UiError:
            raise
        except Exception as exc:
            raise UiError("SAVE_FAILED", "The canonical state changed but its save failed", status=500) from exc
        self.latest_save = target
        return saved

    def _save_request_log(self) -> None:
        _atomic_json(self.requests_path, self.request_log)

    def launch(self) -> dict[str, Any]:
        if self.started:
            return {"started": True, "resumed": True, "state": self.player_projection()}
        if self.latest_path.exists():
            raise UiError("CAMPAIGN_POINTER_INVALID", status=500)
        try:
            admission = admission_from_trusted_portable_package(
                str(self.package_path), producer_root=str(self.producer_root)
            )
            actor_id = admission["character_id"]
            controller = CampaignController.new()
            controller.create_campaign(
                CampaignIdentity("opening-ui-scratch", "Mortal opening", 20260908, DeterministicClock())
            )
            controller.add_location(Location("mortal-start", "Porcelain gate", "rest"))
            controller.add_faction(Faction("party", "The wandering party", "Temporary opening campaign"))
            controller.bind_gameplay(
                profile=manifest(),
                admissions=[admission],
                locations={"mortal-start": {"rest_allowed": True, "cultivation_allowed": False}},
                members={"host": {"role": "gm", "actor_ids": []},
                         "player": {"role": "player", "actor_ids": [actor_id]}},
                items={"starter-token": asdict_item(Item(
                    "starter-token", "Woven gate token", "items", scene_id="mortal-start"
                ))},
            )
            self.controller = controller
            self.actor_id = actor_id
            self._save_revision()
            self.request_log = {}
            self._save_request_log()
        except UiError:
            self.controller = None
            self.actor_id = None
            raise
        except (AdmissionError, EngineError, OSError, ValueError) as exc:
            self.controller = None
            self.actor_id = None
            code = getattr(exc, "code", "CAMPAIGN_LAUNCH_FAILED")
            raise UiError(code, "The validated starter could not be admitted", status=422) from exc
        return {"started": True, "resumed": False, "state": self.player_projection()}

    def reopen(self) -> dict[str, Any]:
        if not self.latest_path.exists():
            raise UiError("CAMPAIGN_NOT_STARTED", "Launch the temporary campaign first", status=409)
        pointer = _read_json(self.latest_path)
        relative = pointer.get("save_dir")
        if not isinstance(relative, str):
            raise UiError("CAMPAIGN_POINTER_INVALID", status=500)
        target = (self.data_root / relative).resolve()
        try:
            target.relative_to(self.revisions_root.resolve())
        except ValueError as exc:
            raise UiError("CAMPAIGN_POINTER_INVALID", status=500) from exc
        controller = CampaignController.load(target)
        actor_id = pointer.get("actor_id")
        if not isinstance(actor_id, str) or actor_id not in controller.view().get("gameplay", {}).get("actors", {}):
            raise UiError("CAMPAIGN_POINTER_INVALID", status=500)
        self.controller = controller
        self.actor_id = actor_id
        self.latest_save = target
        return {"reopened": True, "state": self.player_projection()}

    def _restore_latest(self) -> None:
        if self.latest_save is None:
            self.controller = None
            return
        self.controller = CampaignController.load(self.latest_save)

    def _raw_player_view(self) -> dict[str, Any]:
        controller, actor_id = self._require_started()
        try:
            return controller.gameplay_view(principal_id="player", actor_id=actor_id)
        except (EngineError, ValueError) as exc:
            raise UiError(getattr(exc, "code", "PLAYER_VIEW_FAILED"), status=500) from exc

    def player_projection(self) -> dict[str, Any]:
        raw = self._raw_player_view()
        actor = raw["actor"]
        activity = actor.get("activity")
        safe_activity = None
        if activity is not None:
            safe_activity = {
                key: activity[key]
                for key in ("activity_id", "kind", "status", "elapsed", "segment_elapsed",
                            "sleeping", "light", "required_seconds", "short_awarded")
                if key in activity
            }
        nearby = [
            {key: item[key] for key in ("instance_id", "label", "quantity") if key in item}
            for item in raw.get("nearby_items", [])
        ]
        inventory = [
            {key: item[key] for key in ("instance_id", "label", "quantity") if key in item}
            for item in raw.get("inventory", [])
        ]
        suggestions = raw.get("suggestions", [])
        available = {
            "short_rest": any(s["kind"] == "start_activity" and s["payload"].get("kind") == "short_rest"
                               for s in suggestions),
            "spend_hit_die": any(s["kind"] == "spend_hit_die" for s in suggestions),
            "take_starter_item": any(item.get("instance_id") == "starter-token" for item in nearby),
            "drop_starter_item": any(item.get("instance_id") == "starter-token" for item in inventory),
        }
        activity_active = bool(actor.get("activity") and actor["activity"].get("status") == "active")
        return {
            "campaign_id": raw["campaign_id"],
            "revision": raw["revision"],
            "elapsed_seconds": raw["elapsed_seconds"],
            "identity": {"actor_id": actor["actor_id"], "name": actor["name"]},
            "location": raw["location"],
            "actor": {
                "actor_id": actor["actor_id"],
                "name": actor["name"],
                "hp": actor["hp"],
                "hp_max": actor["hp_max"],
                "dead": actor["dead"],
                "hit_dice": actor["hit_dice"],
                "conditions": actor["conditions"],
                "activity": safe_activity,
                "recovery_activity_id": actor["recovery_activity_id"],
                "mechanics": {
                    "exhaustion": actor["mechanics"]["exhaustion"],
                    "speed": actor["mechanics"]["speed"],
                    "disadvantage_on": actor["mechanics"]["disadvantage_on"],
                },
            },
            "inventory": inventory,
            "nearby_items": nearby,
            "actions": available,
            "local_test_controls": self.allow_local_tests,
            "local_test_actions": {
                "damage": {"enabled": True},
                "poison": {"enabled": True},
                "advance_time": {
                    "enabled": activity_active,
                    "reason": "Time advances only while a canonical activity is active.",
                },
            },
            "persistence": {"saved_event_count": self._saved_event_count()},
        }

    def _saved_event_count(self) -> int | None:
        if self.latest_save is None:
            return None
        pointer = _read_json(self.latest_path)
        value = pointer.get("event_count")
        return value if isinstance(value, int) else None

    def _check_request(self, request_id: str, action: str) -> dict[str, Any] | None:
        if not isinstance(request_id, str) or REQUEST_ID.fullmatch(request_id) is None:
            raise UiError("INVALID_REQUEST_ID", status=400)
        previous = self.request_log.get(request_id)
        if previous is None:
            return None
        if previous.get("action") != action:
            raise UiError("REQUEST_ID_REUSED", "Request id was already used for another action", status=409)
        return previous

    def _controller_receipt(self, *, principal: str, request_id: str) -> dict[str, Any] | None:
        """Recover a gameplay receipt when the ancillary request log is absent.

        The event chain is the canonical idempotency record.  The request log
        is only a convenient UI index, so a restart after its write failed must
        not execute or save an already committed command again.
        """
        controller, _ = self._require_started()
        for event in controller.events_view():
            if event.get("operation") != "gameplay_command":
                continue
            payload = event.get("payload")
            command = payload.get("command") if isinstance(payload, Mapping) else None
            if not isinstance(command, Mapping):
                continue
            if command.get("principal_id") == principal and command.get("request_id") == request_id:
                return {
                    "accepted": True,
                    "event_id": event["event_id"],
                    "event_hash": event["event_hash"],
                    "state_digest": event["post_state_digest"],
                    "event_count": event["sequence"],
                }
        return None

    def _execute(self, *, principal: str, actor_id: str | None, request_id: str,
                 expected_revision: int, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        controller, _ = self._require_started()
        try:
            return controller.execute_gameplay(
                principal_id=principal,
                request_id=request_id,
                expected_revision=expected_revision,
                actor_id=actor_id,
                kind=kind,
                payload=payload,
                profile=identity(),
            )
        except (EngineError, ValueError) as exc:
            raise UiError(getattr(exc, "code", "GAMEPLAY_REJECTED"), status=409) from exc

    def _recorded_result(self, action: str, request_id: str, receipt: Any, *, duplicate: bool = False) -> dict[str, Any]:
        result = {"accepted": True, "action": action, "request_id": request_id,
                  "duplicate": duplicate, "receipt": receipt, "state": self.player_projection()}
        if request_id not in self.request_log:
            self.request_log[request_id] = {"action": action, "receipt": receipt}
            try:
                self._save_request_log()
            except OSError:
                # The canonical revision and controller receipt are already
                # durable.  Controller request IDs still prevent a replayed
                # retry from applying the mutation twice after restart.
                result["request_log_persisted"] = False
                result["warning"] = "Canonical state saved; duplicate protection is controller-backed until the request log is writable."
            else:
                result["request_log_persisted"] = True
        return result

    def action(self, body: Mapping[str, Any]) -> dict[str, Any]:
        allowed = {"action", "request_id", "expected_revision"}
        if set(body) != allowed:
            raise UiError("INVALID_REQUEST_FIELDS", status=400)
        action = body.get("action")
        request_id = body.get("request_id")
        expected_revision = body.get("expected_revision")
        if not isinstance(action, str) or action not in PLAYER_ACTIONS:
            raise UiError("UNSUPPORTED_PLAYER_ACTION", status=400)
        if type(expected_revision) is not int or expected_revision < 0:
            raise UiError("INVALID_REVISION", status=400)
        previous = self._check_request(request_id, action)
        if previous is not None:
            return self._recorded_result(action, request_id, previous["receipt"], duplicate=True)
        controller, actor_id = self._require_started()
        before_save = self.latest_save
        controller_duplicate = False
        try:
            if action == "short_rest":
                start_duplicate = self._controller_receipt(principal="player", request_id=f"{request_id}-start")
                start_receipt = self._execute(principal="player", actor_id=actor_id,
                                              request_id=f"{request_id}-start",
                                              expected_revision=expected_revision,
                                              kind="start_activity", payload={"kind": "short_rest"})
                finish_duplicate = self._controller_receipt(principal="host", request_id=f"{request_id}-finish")
                finish_receipt = self._execute(principal="host", actor_id=None,
                                               request_id=f"{request_id}-finish",
                                               expected_revision=controller.event_count(),
                                               kind="advance_time",
                                               payload={"seconds": 3600, "modes": {actor_id: "light"}})
                receipt: Any = {"start": start_receipt, "finish": finish_receipt}
                controller_duplicate = start_duplicate is not None and finish_duplicate is not None
            elif action == "spend_hit_die":
                controller_duplicate = self._controller_receipt(principal="player", request_id=request_id) is not None
                receipt = self._execute(principal="player", actor_id=actor_id,
                                        request_id=request_id, expected_revision=expected_revision,
                                        kind="spend_hit_die", payload={"pool_id": "primary"})
            elif action == "take_starter_item":
                controller_duplicate = self._controller_receipt(principal="player", request_id=request_id) is not None
                receipt = self._execute(principal="player", actor_id=actor_id,
                                        request_id=request_id, expected_revision=expected_revision,
                                        kind="take_item", payload={"item_id": "starter-token"})
            else:
                controller_duplicate = self._controller_receipt(principal="player", request_id=request_id) is not None
                receipt = self._execute(principal="player", actor_id=actor_id,
                                        request_id=request_id, expected_revision=expected_revision,
                                        kind="drop_item", payload={"item_id": "starter-token"})
            if not controller_duplicate:
                self._save_revision()
        except UiError:
            if before_save is not None and controller.event_count() > 0:
                self._restore_latest()
            raise
        return self._recorded_result(action, request_id, receipt, duplicate=controller_duplicate)

    def local_test(self, body: Mapping[str, Any]) -> dict[str, Any]:
        if not self.allow_local_tests:
            raise UiError("LOCAL_TESTS_DISABLED", status=403)
        allowed = {"action", "request_id", "expected_revision"}
        if set(body) != allowed:
            raise UiError("INVALID_REQUEST_FIELDS", status=400)
        action = body.get("action")
        request_id = body.get("request_id")
        expected_revision = body.get("expected_revision")
        if not isinstance(action, str) or action not in LOCAL_ACTIONS:
            raise UiError("UNSUPPORTED_LOCAL_TEST_ACTION", status=400)
        if type(expected_revision) is not int or expected_revision < 0:
            raise UiError("INVALID_REVISION", status=400)
        previous = self._check_request(request_id, action)
        if previous is not None:
            return self._recorded_result(action, request_id, previous["receipt"], duplicate=True)
        controller, actor_id = self._require_started()
        raw = self._raw_player_view()["actor"]
        activity = raw.get("activity")
        controller_duplicate = False
        try:
            if action == "damage":
                controller_duplicate = self._controller_receipt(principal="host", request_id=request_id) is not None
                resume = bool(activity and activity.get("kind") == "long_rest" and raw["hp"] > 1)
                receipt = self._execute(principal="host", actor_id=actor_id,
                                        request_id=request_id, expected_revision=expected_revision,
                                        kind="damage", payload={"amount": 1, "source_id": "ui-impact",
                                                                "resume_long_rest": resume})
            elif action == "poison":
                controller_duplicate = self._controller_receipt(principal="host", request_id=request_id) is not None
                receipt = self._execute(principal="host", actor_id=actor_id,
                                        request_id=request_id, expected_revision=expected_revision,
                                        kind="apply_condition",
                                        payload=effect_payload("poison", instance_id="ui-poison",
                                                               source_id="ui-poison"))
            else:
                if activity is None or activity.get("status") != "active":
                    raise UiError("NO_ACTIVE_ACTIVITY", "Time advances only while a canonical activity is active", status=409)
                controller_duplicate = self._controller_receipt(principal="host", request_id=request_id) is not None
                mode = "sleep" if activity.get("kind") == "long_rest" else "light"
                receipt = self._execute(principal="host", actor_id=None,
                                        request_id=request_id, expected_revision=expected_revision,
                                        kind="advance_time", payload={"seconds": 3600,
                                                                      "modes": {actor_id: mode}})
            if not controller_duplicate:
                self._save_revision()
        except UiError:
            self._restore_latest()
            raise
        return self._recorded_result(action, request_id, receipt, duplicate=controller_duplicate)


def asdict_item(item: Item) -> dict[str, Any]:
    """Avoid exposing dataclass construction to the request boundary."""

    return {
        "instance_id": item.instance_id,
        "label": item.label,
        "source_id": item.source_id,
        "kind": item.kind,
        "quantity": item.quantity,
        "owner_id": item.owner_id,
        "scene_id": item.scene_id,
        "visible_to": item.visible_to,
        "equipped": item.equipped,
        "attuned": item.attuned,
        "public_ownership": item.public_ownership,
    }


class OpeningHandler(BaseHTTPRequestHandler):
    server_version = "FactoryOpeningUI/1"
    service: CampaignService

    def _origin_ok(self) -> bool:
        expected = {
            f"http://127.0.0.1:{self.server.server_port}",
            f"http://localhost:{self.server.server_port}",
        }
        host = self.headers.get("Host", "")
        if host not in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}:
            return False
        return self.headers.get("Origin") in expected

    def _csrf_ok(self) -> bool:
        cookie = self.headers.get("Cookie", "")
        expected = f"factory_ui_csrf={self.service.csrf_token}"
        token = next((part.strip() for part in cookie.split(";") if part.strip().startswith("factory_ui_csrf=")), "")
        return token == expected and self.headers.get("X-CSRF-Token") == self.service.csrf_token

    def _headers(self, content_type: str, length: int) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Set-Cookie", f"factory_ui_csrf={self.service.csrf_token}; Path=/; SameSite=Strict")
        self.send_header("Connection", "close")

    def _json(self, value: Mapping[str, Any], status: int = 200) -> None:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self._headers("application/json; charset=utf-8", len(raw))
        self.end_headers()
        self.wfile.write(raw)

    def _error(self, exc: Exception) -> None:
        if isinstance(exc, UiError):
            status = exc.status
            code = exc.code
            message = str(exc)
        else:
            status = 500
            code = "INTERNAL_ERROR"
            message = "The opening service failed to complete the request"
        self._json({"ok": False, "error": {"code": code, "message": message}}, status)

    def _body(self) -> dict[str, Any]:
        length = self.headers.get("Content-Length")
        if length is None or not length.isdigit() or int(length) > 16_384:
            raise UiError("REQUEST_BODY_INVALID", status=400)
        try:
            value = json.loads(self.rfile.read(int(length)))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise UiError("REQUEST_BODY_INVALID", status=400) from exc
        if not isinstance(value, dict):
            raise UiError("REQUEST_BODY_INVALID", status=400)
        return value

    def do_GET(self) -> None:  # noqa: N802
        try:
            path = urlsplit(self.path).path
            if path == "/":
                body = (Path(__file__).parent / "static" / "index.html").read_bytes()
                self.send_response(200)
                self._headers("text/html; charset=utf-8", len(body))
                self.end_headers()
                self.wfile.write(body)
            elif path in STATIC_FILES:
                name, content_type = STATIC_FILES[path]
                body = (Path(__file__).parent / "static" / name).read_bytes()
                self.send_response(200)
                self._headers(content_type, len(body))
                self.end_headers()
                self.wfile.write(body)
            elif path == "/api/session":
                if not self.service.started:
                    self._json({"ok": True, "started": False})
                else:
                    self._json({"ok": True, "started": True, "state": self.service.player_projection()})
            else:
                self._json({"ok": False, "error": {"code": "NOT_FOUND", "message": "Not found"}}, 404)
        except Exception as exc:  # boundary must return structured errors
            self._error(exc)

    def do_POST(self) -> None:  # noqa: N802
        try:
            if not self._origin_ok() or not self._csrf_ok():
                raise UiError("MUTATION_PROTECTION_FAILED", status=403)
            path = urlsplit(self.path).path
            if path == "/api/launch":
                body = self._body()
                if body:
                    raise UiError("INVALID_REQUEST_FIELDS", status=400)
                self._json({"ok": True, **self.service.launch()})
            elif path == "/api/reopen":
                body = self._body()
                if body:
                    raise UiError("INVALID_REQUEST_FIELDS", status=400)
                self._json({"ok": True, **self.service.reopen()})
            elif path == "/api/action":
                self._json({"ok": True, **self.service.action(self._body())})
            elif path == "/api/local-test":
                self._json({"ok": True, **self.service.local_test(self._body())})
            else:
                raise UiError("NOT_FOUND", status=404)
        except Exception as exc:  # boundary must return structured errors
            self._error(exc)

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("opening-ui " + (fmt % args) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Loopback Factory opening UI")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--producer-root", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--allow-local-tests", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("opening UI binds to loopback only")
    if not 1024 <= args.port <= 65535:
        raise SystemExit("port must be in the unprivileged range")
    service = CampaignService(data_root=args.data_root, package_path=args.package,
                              producer_root=args.producer_root,
                              allow_local_tests=args.allow_local_tests)
    OpeningHandler.service = service
    server = HTTPServer((args.host, args.port), OpeningHandler)
    print(json.dumps({"url": f"http://{args.host}:{args.port}/", "data_root": str(service.data_root),
                      "started": service.started, "allow_local_tests": service.allow_local_tests}, sort_keys=True), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
