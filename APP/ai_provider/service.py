from __future__ import annotations

import ipaddress
import json
import re
import sqlite3
import uuid
from typing import Any
from urllib.parse import urlsplit

import httpx

from ai_provider.secrets import APIProviderSecretStore, SecretStore
from app.core import Database, FoundryError, canonical_json, sha256_bytes, utcnow
from stage1.service import Stage1ClipboardService


PROVIDER_ID = "deepseek"
DEEPSEEK_ENDPOINT = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-v4-flash"
PROVIDER_PROFILES: dict[str, dict[str, Any]] = {
    "openai": {
        "display_name": "OpenAI",
        "kind": "openai",
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "default_model": "gpt-4o-mini",
        "supports_thinking": False,
        "preset": True,
    },
    "deepseek": {
        "display_name": "DeepSeek",
        "kind": "deepseek",
        "endpoint": DEEPSEEK_ENDPOINT,
        "default_model": DEFAULT_MODEL,
        "supports_thinking": True,
        "preset": True,
    },
    "custom": {
        "display_name": "Custom OpenAI-compatible",
        "kind": "custom",
        "endpoint": "",
        "default_model": "compatible-model",
        "supports_thinking": False,
        "preset": False,
    },
}
MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
MAX_PROVIDER_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_STAGE1_RESPONSE_BYTES = 2_000_000
SYSTEM_MESSAGE = (
    "You are an untrusted Tianxia Stage 1 planning adapter. Return exactly one JSON object "
    "that follows the response schema inside the user prompt. Select only offered IDs. "
    "Do not invent mechanics, IDs, hashes, actions, statistics, tools, or network instructions. "
    "The local Foundry validates everything and a human must approve any valid result."
)


def provider_profile(provider_id: str) -> dict[str, Any]:
    try:
        return PROVIDER_PROFILES[provider_id]
    except KeyError as exc:
        raise FoundryError("AI_PROVIDER_PROFILE_INVALID", "Choose OpenAI, DeepSeek, or a custom OpenAI-compatible profile.") from exc


def validate_endpoint(endpoint: str, *, provider_id: str) -> str:
    value = str(endpoint or "").strip()
    profile = provider_profile(provider_id)
    if profile["preset"]:
        if value != profile["endpoint"]:
            raise FoundryError("AI_PROVIDER_ENDPOINT_INVALID", "A preset API Provider uses its published safe endpoint.")
        return value
    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme.lower() != "https" or not hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise FoundryError("AI_PROVIDER_ENDPOINT_INVALID", "Custom API endpoints must be HTTPS URLs without credentials, queries, or fragments.")
    if hostname == "localhost" or hostname.endswith(".local") or hostname.endswith(".localhost"):
        raise FoundryError("AI_PROVIDER_ENDPOINT_BLOCKED", "Custom API endpoints on local or link-local hostnames are not allowed.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (address.is_private or address.is_loopback or address.is_link_local or address.is_multicast or address.is_reserved or address.is_unspecified):
        raise FoundryError("AI_PROVIDER_ENDPOINT_BLOCKED", "Custom API endpoints on private, loopback, link-local, or reserved addresses are not allowed.")
    return value


class AIProviderService:
    def __init__(
        self,
        db: Database,
        *,
        transport: httpx.BaseTransport | None = None,
        secret_store: SecretStore | None = None,
    ):
        self.db = db
        self.stage1 = Stage1ClipboardService(db)
        self.transport = transport
        self.secrets = secret_store or APIProviderSecretStore(db.settings.data_dir)
        self._connection_test = {"status": "NOT_TESTED", "message": "Save settings and key, then run the explicit connection test."}

    @staticmethod
    def _defaults() -> dict[str, Any]:
        return {
            "provider_id": PROVIDER_ID,
            "enabled": False,
            "endpoint": DEEPSEEK_ENDPOINT,
            "model": DEFAULT_MODEL,
            "thinking_mode": "disabled",
            "max_output_tokens": 16384,
            "timeout_seconds": 120,
            "data_sharing_acknowledged": False,
            "acknowledged_by": None,
            "acknowledged_at": None,
            "updated_at": None,
        }

    def _selected_provider_id(self) -> str:
        try:
            with self.db.connection() as conn:
                row = conn.execute("SELECT provider_id FROM ai_provider_selection WHERE singleton=1").fetchone()
        except sqlite3.OperationalError:
            row = None
        selected = str(row["provider_id"] if row else PROVIDER_ID)
        return selected if selected in PROVIDER_PROFILES else PROVIDER_ID

    def _settings(self) -> dict[str, Any]:
        selected = self._selected_provider_id()
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM ai_provider_settings WHERE provider_id=?",
                (selected,),
            ).fetchone()
        if row is None:
            profile = provider_profile(selected)
            defaults = self._defaults()
            defaults.update({"provider_id": selected, "endpoint": profile["endpoint"], "model": profile["default_model"]})
            return defaults
        value = dict(row)
        for key in ("enabled", "data_sharing_acknowledged"):
            value[key] = bool(value[key])
        return value

    def status(self) -> dict[str, Any]:
        settings = self._settings()
        profile = provider_profile(settings["provider_id"])
        secret = self.secrets.status(settings["provider_id"])
        prerequisites_ready = bool(
            settings["enabled"]
            and settings["data_sharing_acknowledged"]
            and settings.get("acknowledged_by")
            and secret["present"]
        )
        if not settings["enabled"]:
            readiness_state, readiness_reason = "DISABLED_BY_OWNER", f"{profile['display_name']} is disabled in the saved settings."
        elif not settings["data_sharing_acknowledged"] or not settings.get("acknowledged_by"):
            readiness_state, readiness_reason = "ACKNOWLEDGEMENT_MISSING", "A named data-sharing acknowledgement is required."
        elif not secret["present"]:
            readiness_state, readiness_reason = "KEY_MISSING", "No protected API Provider key is stored."
        elif self._connection_test["status"] == "FAILED":
            readiness_state, readiness_reason = "CONNECTION_FAILED", self._connection_test["message"]
        elif self._connection_test["status"] != "PASS":
            readiness_state, readiness_reason = "CONNECTION_NOT_TESTED", "Settings and key are saved; run Test Connection once."
        else:
            readiness_state, readiness_reason = "READY", "Saved settings, protected key, acknowledgement, and connection test passed."
        with self.db.connection() as conn:
            totals = conn.execute(
                """SELECT COUNT(*) AS runs,
                          COALESCE(SUM(prompt_tokens),0) AS prompt_tokens,
                          COALESCE(SUM(completion_tokens),0) AS completion_tokens,
                          COALESCE(SUM(total_tokens),0) AS total_tokens
                   FROM ai_provider_runs WHERE provider_id=?""",
                (settings["provider_id"],),
            ).fetchone()
        return {
            "provider_id": settings["provider_id"],
            "mode": "optional_validated_stage1_and_combat_transport",
            "settings": settings,
            "profile": {
                "provider_id": settings["provider_id"],
                "display_name": profile["display_name"],
                "supports_thinking": profile["supports_thinking"],
                "preset": profile["preset"],
            },
            "profiles": [
                {
                    "provider_id": profile_id,
                    "display_name": row["display_name"],
                    "endpoint": row["endpoint"],
                    "default_model": row["default_model"],
                    "supports_thinking": row["supports_thinking"],
                    "preset": row["preset"],
                }
                for profile_id, row in PROVIDER_PROFILES.items()
            ],
            "secret": secret,
            "ready": bool(prerequisites_ready and self._connection_test["status"] == "PASS"),
            "readiness_state": readiness_state,
            "readiness_reason": readiness_reason,
            "connection_test": dict(self._connection_test),
            "manual_clipboard_available": True,
            "combat_transport_available": True,
            "direct_commit_allowed": False,
            "mechanical_authority": False,
            "automatic_retries": 0,
            "usage_totals": dict(totals),
        }

    def configure(
        self,
        *,
        enabled: bool,
        provider_id: str = PROVIDER_ID,
        endpoint: str | None = None,
        model: str,
        thinking_mode: str,
        max_output_tokens: int,
        timeout_seconds: int,
        data_sharing_acknowledged: bool,
        acknowledged_by: str | None,
    ) -> dict[str, Any]:
        provider_id = str(provider_id or PROVIDER_ID).strip()
        profile = provider_profile(provider_id)
        endpoint = validate_endpoint(endpoint if provider_id == "custom" else profile["endpoint"], provider_id=provider_id)
        model = str(model or "").strip()
        if not MODEL_PATTERN.fullmatch(model):
            raise FoundryError(
                "AI_PROVIDER_MODEL_INVALID",
                "The API Provider model ID must be 1-100 portable identifier characters.",
            )
        if thinking_mode not in {"enabled", "disabled"}:
            raise FoundryError("AI_PROVIDER_THINKING_MODE_INVALID", "Thinking mode must be enabled or disabled.")
        if thinking_mode == "enabled" and not profile["supports_thinking"]:
            raise FoundryError("AI_PROVIDER_THINKING_MODE_UNSUPPORTED", "Thinking mode is available only for the DeepSeek profile.")
        if not 512 <= max_output_tokens <= 32768:
            raise FoundryError("AI_PROVIDER_MAX_TOKENS_INVALID", "max_output_tokens must be between 512 and 32768.")
        if not 10 <= timeout_seconds <= 300:
            raise FoundryError("AI_PROVIDER_TIMEOUT_INVALID", "timeout_seconds must be between 10 and 300.")
        actor = str(acknowledged_by or "").strip()
        if enabled and (not data_sharing_acknowledged or not actor):
            raise FoundryError(
                "AI_PROVIDER_DATA_SHARING_ACKNOWLEDGEMENT_REQUIRED",
                "Enabling the API Provider requires a named acknowledgement that prompt data will be sent to the selected service.",
            )
        if len(actor) > 200:
            raise FoundryError("AI_PROVIDER_ACKNOWLEDGEMENT_ACTOR_INVALID", "The acknowledgement actor is too long.")
        now = utcnow()
        acknowledged_at = now if data_sharing_acknowledged and actor else None
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO ai_provider_settings(
                   provider_id,enabled,endpoint,model,thinking_mode,max_output_tokens,
                   timeout_seconds,data_sharing_acknowledged,acknowledged_by,
                   acknowledged_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(provider_id) DO UPDATE SET
                     enabled=excluded.enabled,
                     endpoint=excluded.endpoint,
                     model=excluded.model,
                     thinking_mode=excluded.thinking_mode,
                     max_output_tokens=excluded.max_output_tokens,
                     timeout_seconds=excluded.timeout_seconds,
                     data_sharing_acknowledged=excluded.data_sharing_acknowledged,
                     acknowledged_by=excluded.acknowledged_by,
                     acknowledged_at=excluded.acknowledged_at,
                     updated_at=excluded.updated_at""",
                (
                    provider_id,
                    int(enabled),
                    endpoint,
                    model,
                    thinking_mode,
                    max_output_tokens,
                    timeout_seconds,
                    int(data_sharing_acknowledged),
                    actor or None,
                    acknowledged_at,
                    now,
                ),
            )
            conn.execute(
                "INSERT INTO ai_provider_selection(singleton,provider_id,updated_at) VALUES(1,?,?) ON CONFLICT(singleton) DO UPDATE SET provider_id=excluded.provider_id,updated_at=excluded.updated_at",
                (provider_id, now),
            )
        self._connection_test = {"status": "NOT_TESTED", "message": "Saved provider settings changed; run the explicit connection test."}
        return self.status()

    def set_api_key(self, api_key: str) -> dict[str, Any]:
        self.secrets.set(api_key, self._selected_provider_id())
        self._connection_test = {"status": "NOT_TESTED", "message": "The protected key changed; run the explicit connection test."}
        return self.status()

    def delete_api_key(self) -> dict[str, Any]:
        removed = self.secrets.delete(self._selected_provider_id())
        self._connection_test = {"status": "NOT_TESTED", "message": "No protected key is stored."}
        return {"removed": removed, **self.status()}

    def test_connection(self) -> dict[str, Any]:
        """Run one explicit, owner-triggered, non-authoritative API Provider probe."""
        profile = provider_profile(self._settings()["provider_id"])
        try:
            result = self.complete_json(
                prompt_text='Return exactly {"connection":"ok"}.',
                system_message="Return one JSON object for a local connection test. No tools and no mechanical authority.",
                purpose="owner_connection_test",
            )
        except FoundryError as exc:
            self._connection_test = {"status": "FAILED", "message": exc.message}
            raise
        try:
            connection_value = json.loads(result["response_text"])
        except (KeyError, TypeError, json.JSONDecodeError):
            connection_value = None
        if connection_value != {"connection": "ok"}:
            self._connection_test = {"status": "FAILED", "message": f"{profile['display_name']} responded, but the connection-test JSON contract failed."}
            raise FoundryError("AI_PROVIDER_CONNECTION_TEST_INVALID", "The selected API Provider answered, but the connection-test contract was not satisfied.", status_code=502)
        self._connection_test = {"status": "PASS", "message": f"The explicit {profile['display_name']} connection test passed."}
        return {
            "provider_id": self._settings()["provider_id"],
            "status": "PASS",
            "model": result["model"],
            "request_sha256": result["request_sha256"],
            "response_sha256": result["response_sha256"],
            "secret_returned": False,
        }

    @staticmethod
    def _request_payload(prompt_text: str, settings: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "model": settings["model"],
            "messages": [
                {"role": "system", "content": SYSTEM_MESSAGE},
                {"role": "user", "content": prompt_text},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": settings["max_output_tokens"],
            "stream": False,
        }
        if settings["provider_id"] == "deepseek":
            payload["thinking"] = {"type": settings["thinking_mode"]}
        return payload

    def _insert_started_run(
        self,
        *,
        run_id: str,
        idempotency_key: str,
        prompt: dict[str, Any],
        settings: dict[str, Any],
        request_bytes: bytes,
        started_at: str,
    ) -> None:
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """INSERT INTO ai_provider_runs(
                       run_id,provider_id,project_id,prompt_id,idempotency_key,prompt_sha256,
                       model,endpoint,request_bytes,request_sha256,started_at,status)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        run_id,
                        settings["provider_id"],
                        prompt["project_id"],
                        prompt["prompt_id"],
                        idempotency_key,
                        prompt["prompt_sha256"],
                        settings["model"],
                        settings["endpoint"],
                        request_bytes,
                        sha256_bytes(request_bytes),
                        started_at,
                        "started",
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise FoundryError(
                "AI_PROVIDER_IDEMPOTENCY_CONFLICT",
                "That provider request key is already bound to another run.",
            ) from exc

    def _update_run(self, run_id: str, **values: Any) -> None:
        allowed = {
            "completed_at", "status", "http_status", "provider_response_bytes",
            "provider_response_sha256", "provider_response_bytes_count",
            "completion_content_sha256", "finish_reason", "prompt_tokens",
            "completion_tokens", "total_tokens", "stage1_attempt_id", "error_code",
            "error_message",
        }
        if not values or set(values) - allowed:
            raise RuntimeError("Unsupported AI provider audit update.")
        assignments = ",".join(f"{key}=?" for key in values)
        with self.db.transaction() as conn:
            conn.execute(
                f"UPDATE ai_provider_runs SET {assignments} WHERE run_id=?",
                (*values.values(), run_id),
            )

    @staticmethod
    def _usage(value: Any) -> tuple[int | None, int | None, int | None]:
        usage = value if isinstance(value, dict) else {}
        result: list[int | None] = []
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            token_count = usage.get(key)
            result.append(token_count if isinstance(token_count, int) and token_count >= 0 else None)
        return result[0], result[1], result[2]

    def _read_bounded_response(self, response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > MAX_PROVIDER_RESPONSE_BYTES:
                raise FoundryError(
                    "AI_PROVIDER_RESPONSE_TOO_LARGE",
                    "The provider response exceeded the 4 MiB audit limit.",
                )
            chunks.append(chunk)
        return b"".join(chunks)

    def _provider_call(self, *, endpoint: str, key: str, request_bytes: bytes, timeout_seconds: int) -> tuple[int, bytes]:
        headers = {
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "TianxiaCharacterFoundry/Stage1",
        }
        timeout = httpx.Timeout(timeout_seconds)
        try:
            with httpx.Client(
                transport=self.transport,
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                with client.stream(
                    "POST",
                    endpoint,
                    headers=headers,
                    content=request_bytes,
                ) as response:
                    return response.status_code, self._read_bounded_response(response)
        except FoundryError:
            raise
        except httpx.HTTPError as exc:
            raise FoundryError(
                "AI_PROVIDER_NETWORK_ERROR",
                "The API Provider request failed before a complete response was received.",
                details={"exception_type": type(exc).__name__},
                status_code=502,
            ) from exc

    def complete_json(self, *, prompt_text: str, system_message: str, purpose: str) -> dict[str, Any]:
        """Return one provider JSON object without granting it mechanical authority.

        The caller remains responsible for exact schema/ID validation and for recording any
        domain-specific audit evidence. This transport never retries automatically.
        """
        settings = self._settings()
        profile = provider_profile(settings["provider_id"])
        if not settings["enabled"]:
            raise FoundryError("AI_PROVIDER_DISABLED", "The optional API Provider is disabled.")
        if not settings["data_sharing_acknowledged"]:
            raise FoundryError(
                "AI_PROVIDER_DATA_SHARING_ACKNOWLEDGEMENT_REQUIRED",
                "Prompt transmission has not been acknowledged by a named user.",
            )
        key = self.secrets.get(settings["provider_id"])
        if key is None:
            raise FoundryError("AI_PROVIDER_API_KEY_MISSING", "No API Provider key is available.")
        request_payload = {
            "model": settings["model"],
            "messages": [
                {"role": "system", "content": str(system_message)},
                {"role": "user", "content": str(prompt_text)},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": min(settings["max_output_tokens"], 8192),
            "stream": False,
        }
        if settings["provider_id"] == "deepseek":
            request_payload["thinking"] = {"type": settings["thinking_mode"]}
        request_bytes = canonical_json(request_payload).encode("utf-8")
        http_status, response_bytes = self._provider_call(
            endpoint=settings["endpoint"],
            key=key,
            request_bytes=request_bytes,
            timeout_seconds=settings["timeout_seconds"],
        )
        response_hash = sha256_bytes(response_bytes)
        if http_status != 200:
            raise FoundryError(
                "AI_PROVIDER_HTTP_ERROR",
                f"{profile['display_name']} rejected the request.",
                details={"http_status": http_status, "response_sha256": response_hash, "purpose": purpose},
                status_code=502,
            )
        try:
            provider_value = json.loads(response_bytes.decode("utf-8"))
            choices = provider_value.get("choices")
            choice = choices[0] if isinstance(choices, list) and len(choices) == 1 else None
            message = choice.get("message") if isinstance(choice, dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Provider completion content is empty or missing.")
            if isinstance(message.get("tool_calls"), list) and message["tool_calls"]:
                raise ValueError("Provider returned tool calls even though tools were not offered.")
            if finish_reason != "stop":
                raise ValueError(f"Provider finish_reason is {finish_reason!r}, not 'stop'.")
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                raise ValueError("Provider completion is not one JSON object.")
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, IndexError, ValueError) as exc:
            raise FoundryError(
                "AI_PROVIDER_RESPONSE_CONTRACT_INVALID",
                f"{profile['display_name']} returned a response that cannot enter the local JSON validator.",
                details={"response_sha256": response_hash, "purpose": purpose, "reason": str(exc)},
                status_code=502,
            ) from exc
        prompt_tokens, completion_tokens, total_tokens = self._usage(provider_value.get("usage"))
        return {
            "provider_id": settings["provider_id"],
            "purpose": purpose,
            "model": settings["model"],
            "request_sha256": sha256_bytes(request_bytes),
            "response_sha256": response_hash,
            "completion_sha256": sha256_bytes(content.encode("utf-8")),
            "response_text": content,
            "finish_reason": finish_reason,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
            "value": parsed,
        }

    def _existing_idempotent_run(self, prompt_id: str, idempotency_key: str) -> dict[str, Any] | None:
        provider_id = self._selected_provider_id()
        with self.db.connection() as conn:
            row = conn.execute(
                """SELECT run_id FROM ai_provider_runs
                   WHERE provider_id=? AND prompt_id=? AND idempotency_key=?""",
                (provider_id, prompt_id, idempotency_key),
            ).fetchone()
        if row is None:
            return None
        result = self.get_run(row["run_id"])
        result["idempotent"] = True
        return result

    def run_stage1(self, prompt_id: str, *, idempotency_key: str) -> dict[str, Any]:
        idempotency_key = str(idempotency_key or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._:-]{8,160}", idempotency_key):
            raise FoundryError(
                "AI_PROVIDER_IDEMPOTENCY_KEY_INVALID",
                "The request key must be 8-160 portable identifier characters.",
            )
        existing = self._existing_idempotent_run(prompt_id, idempotency_key)
        if existing is not None:
            return existing

        settings = self._settings()
        profile = provider_profile(settings["provider_id"])
        if not settings["enabled"]:
            raise FoundryError("AI_PROVIDER_DISABLED", "The optional API Provider is disabled.")
        if not settings["data_sharing_acknowledged"]:
            raise FoundryError(
                "AI_PROVIDER_DATA_SHARING_ACKNOWLEDGEMENT_REQUIRED",
                "Prompt transmission has not been acknowledged by a named user.",
            )
        key = self.secrets.get(settings["provider_id"])
        if key is None:
            raise FoundryError("AI_PROVIDER_API_KEY_MISSING", "No API Provider key is available.")
        prompt = self.stage1.get_prompt(prompt_id)
        request_payload = self._request_payload(prompt["prompt_text"], settings)
        request_bytes = canonical_json(request_payload).encode("utf-8")
        run_id = "ai.run." + uuid.uuid4().hex
        started_at = utcnow()
        try:
            self._insert_started_run(
                run_id=run_id,
                idempotency_key=idempotency_key,
                prompt=prompt,
                settings=settings,
                request_bytes=request_bytes,
                started_at=started_at,
            )
        except FoundryError as exc:
            if exc.code != "AI_PROVIDER_IDEMPOTENCY_CONFLICT":
                raise
            existing = self._existing_idempotent_run(prompt_id, idempotency_key)
            if existing is not None:
                return existing
            raise

        try:
            http_status, response_bytes = self._provider_call(
                endpoint=settings["endpoint"],
                key=key,
                request_bytes=request_bytes,
                timeout_seconds=settings["timeout_seconds"],
            )
        except FoundryError as exc:
            self._update_run(
                run_id,
                completed_at=utcnow(),
                status="provider_error",
                error_code=exc.code,
                error_message=exc.message,
            )
            raise

        response_hash = sha256_bytes(response_bytes)
        response_common = {
            "completed_at": utcnow(),
            "http_status": http_status,
            "provider_response_bytes": response_bytes,
            "provider_response_sha256": response_hash,
            "provider_response_bytes_count": len(response_bytes),
        }
        if http_status != 200:
            self._update_run(
                run_id,
                **response_common,
                status="provider_error",
                error_code="AI_PROVIDER_HTTP_ERROR",
                error_message=f"{profile['display_name']} returned HTTP {http_status}.",
            )
            raise FoundryError(
                "AI_PROVIDER_HTTP_ERROR",
                f"{profile['display_name']} rejected the request.",
                details={"run_id": run_id, "http_status": http_status, "response_sha256": response_hash},
                status_code=502,
            )

        try:
            provider_value = json.loads(response_bytes.decode("utf-8"))
            choices = provider_value.get("choices")
            choice = choices[0] if isinstance(choices, list) and len(choices) == 1 else None
            message = choice.get("message") if isinstance(choice, dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Provider completion content is empty or missing.")
            if isinstance(message.get("tool_calls"), list) and message["tool_calls"]:
                raise ValueError("Provider returned tool calls even though tools were not offered.")
            content_bytes = content.encode("utf-8")
            if len(content_bytes) > MAX_STAGE1_RESPONSE_BYTES:
                raise ValueError("Provider completion exceeds the Stage 1 response size limit.")
            if finish_reason != "stop":
                raise ValueError(f"Provider finish_reason is {finish_reason!r}, not 'stop'.")
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, IndexError, ValueError) as exc:
            self._update_run(
                run_id,
                **response_common,
                status="response_rejected",
                finish_reason=(locals().get("choice") or {}).get("finish_reason") if isinstance(locals().get("choice"), dict) else None,
                error_code="AI_PROVIDER_RESPONSE_CONTRACT_INVALID",
                error_message=str(exc)[:500],
            )
            raise FoundryError(
                "AI_PROVIDER_RESPONSE_CONTRACT_INVALID",
                f"{profile['display_name']} returned a response that cannot enter the Stage 1 validator.",
                details={"run_id": run_id, "response_sha256": response_hash},
                status_code=502,
            ) from exc

        prompt_tokens, completion_tokens, total_tokens = self._usage(provider_value.get("usage"))
        try:
            attempt = self.stage1.validate_response(prompt_id, content)
        except FoundryError as exc:
            self._update_run(
                run_id,
                **response_common,
                status="response_rejected",
                completion_content_sha256=sha256_bytes(content_bytes),
                finish_reason=finish_reason,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                error_code=exc.code,
                error_message=exc.message[:500],
            )
            raise
        valid = bool(attempt["validation"]["valid"])
        self._update_run(
            run_id,
            **response_common,
            status="validated" if valid else "response_rejected",
            completion_content_sha256=sha256_bytes(content_bytes),
            finish_reason=finish_reason,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            stage1_attempt_id=attempt["attempt_id"],
            error_code=None if valid else "STAGE1_RESPONSE_REJECTED",
            error_message=None if valid else "Provider output failed the unchanged Stage 1 validation gate.",
        )
        result = self.get_run(run_id)
        result["attempt"] = attempt
        result["idempotent"] = False
        return result

    @staticmethod
    def _public_run(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "run_id": row["run_id"],
            "provider_id": row["provider_id"],
            "project_id": row["project_id"],
            "prompt_id": row["prompt_id"],
            "idempotency_key": row["idempotency_key"],
            "prompt_sha256": row["prompt_sha256"],
            "model": row["model"],
            "endpoint": row["endpoint"],
            "request_sha256": row["request_sha256"],
            "request_bytes_count": len(bytes(row["request_bytes"])),
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "status": row["status"],
            "http_status": row["http_status"],
            "provider_response_sha256": row["provider_response_sha256"],
            "provider_response_bytes_count": row["provider_response_bytes_count"],
            "completion_content_sha256": row["completion_content_sha256"],
            "finish_reason": row["finish_reason"],
            "usage": {
                "prompt_tokens": row["prompt_tokens"],
                "completion_tokens": row["completion_tokens"],
                "total_tokens": row["total_tokens"],
            },
            "stage1_attempt_id": row["stage1_attempt_id"],
            "error_code": row["error_code"],
            "error_message": row["error_message"],
            "secret_persisted_in_run": False,
            "direct_commit_performed": False,
            "mechanical_authority": False,
        }

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM ai_provider_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise FoundryError("AI_PROVIDER_RUN_NOT_FOUND", "No AI provider run has that ID.", status_code=404)
        return self._public_run(row)

    def list_runs(self, project_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        with self.db.connection() as conn:
            rows = conn.execute(
                """SELECT * FROM ai_provider_runs WHERE project_id=?
                   ORDER BY started_at DESC,run_id DESC LIMIT ?""",
                (project_id, limit),
            ).fetchall()
        return [self._public_run(row) for row in rows]
