from __future__ import annotations

import ipaddress
import json
import math
import re
import socket
import sqlite3
import time
import uuid
from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit

import httpx
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from ai_provider.agent_bridge import (
    AGENT_DEFAULT_MAX_OUTPUT_TOKENS,
    AGENT_MAX_OUTPUT_TOKENS,
    AGENT_OPEN_STATES,
    AGENT_STATE_ANSWERED,
    AGENT_STATE_REJECTED,
    DEFAULT_AGENT_WAIT_SECONDS,
    MAX_AGENT_WAIT_SECONDS,
    MIN_AGENT_WAIT_SECONDS,
    AgentRequestBridge,
)
from ai_provider.identity import derive_provider_identity
from ai_provider.secrets import APIProviderSecretStore, SecretStore
from ai_provider.local_runtime import DEFAULT_LOCAL_MODEL, LOCAL_HTTP_TIMEOUT_SECONDS, LocalAIManager, validate_local_endpoint
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
    "local": {
        "display_name": "Detected Local AI",
        "kind": "local",
        "endpoint": "",
        "default_model": DEFAULT_LOCAL_MODEL,
        "supports_thinking": False,
        "preset": False,
        "local": True,
        "managed": False,
    },
    "lemonade": {
        "display_name": "Built-in Local AI (Lemonade)",
        "kind": "lemonade",
        "endpoint": "",
        "default_model": DEFAULT_LOCAL_MODEL,
        "supports_thinking": False,
        "preset": False,
        "local": True,
        "managed": True,
    },
    "agent": {
        "display_name": "Agent bridge",
        "kind": "agent",
        "endpoint": "",
        "default_model": "agent-authored",
        "supports_thinking": False,
        "preset": False,
        "agent": True,
    },
}
AGENT_PROVIDER_ID = "agent"
LOCAL_PROVIDER_IDS = {"local", "lemonade"}
# The agent bridge is not a network endpoint: the application hands each
# request to a harness-held agent through the durable mailbox in
# ``ai_provider/agent_bridge.py`` and validates the answer exactly as it
# validates a configured provider answer.  The agent's own harness owns the
# model credential, so no key, token, or session material enters the app.
AGENT_POLL_INTERVAL_SECONDS = 1.0
# Cold local models can spend several minutes loading weights before the first
# response byte.  Keep one upstream attempt, but do not mistake that startup
# delay for a network failure.
LOCAL_FIRST_RESPONSE_TIMEOUT_SECONDS = 2400
LOCAL_PROBE_MAX_OUTPUT_TOKENS = 128
LOCAL_SCHEMA_MAX_OUTPUT_TOKENS = 128
LOCAL_SUBSTANTIVE_MAX_OUTPUT_TOKENS = 6144
LOCAL_COMMAND4_MAX_OUTPUT_TOKENS = 16384
LOCAL_GM_AUTHORING_MAX_OUTPUT_TOKENS = 16384
COMMAND4_ACTION_AUTHORING_PURPOSE = "factory_command4_action_authoring"
GM_TACTICAL_AUTHORING_PURPOSE = "factory_gm_tactical_authoring"
COMPOSITE_CONTROLLER_AUTHORING_PURPOSE = "factory_composite_controller"
DCC_LINEAR_STEP_PURPOSE = "dcc_linear_step"
LOCAL_RESTART_READINESS_TIMEOUT_SECONDS = 5.0
MAX_LOCAL_MODEL_LIST_RESPONSE_BYTES = 512 * 1024
LOCAL_CORRECTION_SCHEMA_NAME = "TianxiaFoundry_LocalMethodPathCorrection_v1"
BUILD_DEBRIEF_SCHEMA_NAME = "TianxiaFoundry_BuildDebrief_v1"
BUILD_DEBRIEF_SCHEMA_MAX_OUTPUT_TOKENS = 768
BUILD_DEBRIEF_RESPONSE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "friction_redundancy",
        "choice_bias_flavor_context",
        "helpful_deterministic_tools",
        "creativity_within_rules",
        "modular_future_content",
        "summary",
    ],
    "properties": {
        "friction_redundancy": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 240}, "maxItems": 3},
        "choice_bias_flavor_context": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 240}, "maxItems": 3},
        "helpful_deterministic_tools": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 240}, "maxItems": 3},
        "creativity_within_rules": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 240}, "maxItems": 3},
        "modular_future_content": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 240}, "maxItems": 3},
        "summary": {"type": "string", "minLength": 1, "maxLength": 320},
    },
}
MAX_LOCAL_RESPONSE_SCHEMA_BYTES = 64 * 1024
MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
SHA256_LOWERHEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_PROVIDER_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_STAGE1_RESPONSE_BYTES = 2_000_000
_CARRIER_GRADE_NAT = ipaddress.ip_network("100.64.0.0/10")
_CLOUD_METADATA_HOSTNAMES = {
    "metadata",
    "metadata.google.internal",
    "metadata.google.com",
    "instance-data.ec2.internal",
    "instance-data.ec2.amazonaws.com",
    "metadata.azure.com",
    "metadata.azure.internal",
    "100.100.100.200",
}
SYSTEM_MESSAGE = (
    "You are an untrusted Tianxia Stage 1 planning adapter. Return exactly one JSON object "
    "that follows the response schema inside the user prompt. Select only offered IDs. "
    "Do not invent mechanics, IDs, hashes, actions, statistics, tools, or network instructions. "
    "The local Foundry validates everything and a human must approve any valid result."
)

# Provider/model timing receipts are an optional performance aid only.  Keep
# the allowlist deliberately small so a provider cannot smuggle prompt,
# response, credential, or arbitrary diagnostic data into the receipt.
AI_PROVIDER_TIMING_SCHEMA = "TianxiaFoundry.AIProviderTimingReceipt.v1"
_PROVIDER_TIMING_ALLOWLIST = frozenset({
    "cache_hits",
    "cache_misses",
    "completion_tokens_per_second",
    "eval_count",
    "eval_duration",
    "load_duration",
    "predicted_ms",
    "predicted_n",
    "predicted_per_second",
    "predicted_per_token_ms",
    "prompt_eval_count",
    "prompt_eval_duration",
    "prompt_ms",
    "prompt_n",
    "prompt_per_second",
    "prompt_per_token_ms",
    "sample_count",
    "sample_duration",
    "total_duration",
})
_CONTRACT_FAILURE_REASON_CODES = frozenset({
    "invalid_json",
    "missing_content",
    "finish_reason_not_stop",
    "tool_calls_present",
    "response_not_object",
    "response_shape_invalid",
    "response_schema_validation_failed",
    "other",
})
_SAFE_FINISH_REASONS = frozenset({
    "stop",
    "length",
    "max_tokens",
    "max_output_tokens",
    "content_filter",
    "tool_calls",
    "function_call",
    "error",
    "end_turn",
})


def _safe_provider_timing_value(value: Any) -> int | float | None:
    """Return one bounded, finite, non-negative provider timing number."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= 1_000_000_000_000 else None
    number = float(value)
    if not math.isfinite(number) or number < 0 or number > 1_000_000_000_000:
        return None
    if isinstance(value, int) or number.is_integer():
        return int(number)
    return round(number, 6)


def _safe_provider_timings(value: Any) -> dict[str, int | float]:
    """Copy only allowlisted numeric timing fields from a provider receipt."""

    if not isinstance(value, dict):
        return {}
    result: dict[str, int | float] = {}
    for key in sorted(_PROVIDER_TIMING_ALLOWLIST):
        safe_value = _safe_provider_timing_value(value.get(key))
        if safe_value is not None:
            result[key] = safe_value
    return result


def _safe_finish_reason(value: Any) -> str | None:
    """Keep provider finish metadata closed and non-reflective."""

    if value is None:
        return None
    if isinstance(value, str) and value in _SAFE_FINISH_REASONS:
        return value
    return "other"


def _safe_connection_usage(value: Any) -> dict[str, int | None]:
    """Project complete-json usage into the bounded connection-test receipt."""

    source = deepcopy(value) if isinstance(value, dict) else {}
    result: dict[str, int | None] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        token_count = source.get(key)
        result[key] = (
            token_count
            if type(token_count) is int and 0 <= token_count <= 1_000_000_000_000
            else None
        )
    return result


def _safe_connection_performance(value: Any) -> dict[str, int | float | None]:
    """Project only bounded numeric performance fields for the probe result."""

    source = deepcopy(value) if isinstance(value, dict) else {}
    return {
        key: _safe_provider_timing_value(source.get(key))
        for key in (
            "duration_ms",
            "duration_seconds",
            "completion_tokens_per_second",
        )
    }


def _safe_connection_timings(value: Any) -> dict[str, Any]:
    """Project the private timing receipt without provider payload fields."""

    source = deepcopy(value) if isinstance(value, dict) else {}
    raw_phases = source.get("phases_ms")
    phases: dict[str, int | float] = {}
    if isinstance(raw_phases, dict):
        for key in ("request_preparation", "provider_transport", "response_body_parse"):
            safe_value = _safe_provider_timing_value(raw_phases.get(key))
            if safe_value is not None:
                phases[key] = safe_value
    return {
        "schema": AI_PROVIDER_TIMING_SCHEMA,
        "phases_ms": phases,
        "provider_reported": _safe_provider_timings(source.get("provider_reported")),
    }


def _elapsed_ms(start: float, end: float) -> int:
    """Convert a monotonic interval to a non-negative integer millisecond count."""

    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return 0
    elapsed = (float(end) - float(start)) * 1000
    if not math.isfinite(elapsed) or elapsed <= 0:
        return 0
    return round(elapsed)


def _provider_timeout_seconds(settings: dict[str, Any], *, substantive: bool) -> int:
    """Give loopback models one bounded cold-start window without retrying.

    The explicit connection test is commonly the model's first completion, so
    it needs the same grace as a substantive build.  Remote providers continue
    to use the owner's saved timeout unchanged.
    """

    saved = int(settings.get("timeout_seconds") or 0)
    if settings.get("provider_id") in LOCAL_PROVIDER_IDS:
        return max(saved, LOCAL_FIRST_RESPONSE_TIMEOUT_SECONDS)
    return saved


def _local_models_endpoint(endpoint: Any) -> str:
    """Derive the read-only model-list route from a saved local endpoint."""

    checked = validate_local_endpoint(str(endpoint or ""))
    parsed = urlsplit(checked)
    if parsed.scheme.lower() != "http":
        raise FoundryError(
            "LOCAL_AI_ENDPOINT_INVALID",
            "Automatic local readiness requires an HTTP loopback endpoint.",
        )
    model_paths = {
        "/v1/chat/completions": "/v1/models",
        "/api/v1/chat/completions": "/api/v1/models",
    }
    try:
        model_path = model_paths[parsed.path]
    except KeyError as exc:
        raise FoundryError(
            "LOCAL_AI_ENDPOINT_INVALID",
            "The saved local endpoint must be a documented OpenAI-compatible chat-completions route.",
        ) from exc
    return parsed._replace(path=model_path).geturl()


def _local_model_ids(value: Any) -> list[str] | None:
    """Extract exact model IDs from bounded OpenAI-compatible list shapes."""

    if isinstance(value, list):
        rows = value
    elif isinstance(value, dict):
        rows = None
        for key in ("data", "models", "items"):
            if key in value:
                rows = value.get(key)
                break
        if not isinstance(rows, list):
            return None
    else:
        return None
    model_ids: list[str] = []
    for row in rows:
        if isinstance(row, str):
            model_id = row
        elif isinstance(row, dict):
            model_id = None
            for key in ("id", "model", "name"):
                if key in row:
                    model_id = row.get(key)
                    break
            if not isinstance(model_id, str):
                return None
        else:
            return None
        if not model_id or model_id != model_id.strip():
            return None
        model_ids.append(model_id)
    return model_ids


def provider_profile(provider_id: str) -> dict[str, Any]:
    try:
        return PROVIDER_PROFILES[provider_id]
    except KeyError as exc:
        raise FoundryError("AI_PROVIDER_PROFILE_INVALID", "Choose Local AI, the Agent bridge, OpenAI, DeepSeek, or a custom OpenAI-compatible profile.") from exc


def validate_endpoint(endpoint: str, *, provider_id: str) -> str:
    value = str(endpoint or "").strip()
    profile = provider_profile(provider_id)
    if provider_id in LOCAL_PROVIDER_IDS or profile.get("local"):
        return validate_local_endpoint(value)
    if profile.get("agent"):
        # The agent bridge posts no network request of its own; the waiting
        # caller polls the durable mailbox instead of an endpoint.
        return ""
    if profile["preset"]:
        if value != profile["endpoint"]:
            raise FoundryError("AI_PROVIDER_ENDPOINT_INVALID", "A preset API Provider uses its published safe endpoint.")
        return value
    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").rstrip(".").lower()
    try:
        _ = parsed.port
    except ValueError as exc:
        raise FoundryError("AI_PROVIDER_ENDPOINT_INVALID", "Custom API endpoints must use a valid HTTPS port.") from exc
    if parsed.scheme.lower() != "https" or not hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise FoundryError("AI_PROVIDER_ENDPOINT_INVALID", "Custom API endpoints must be HTTPS URLs without credentials, queries, or fragments.")
    if hostname in _CLOUD_METADATA_HOSTNAMES or hostname == "localhost" or hostname.endswith(".local") or hostname.endswith(".localhost"):
        raise FoundryError("AI_PROVIDER_ENDPOINT_BLOCKED", "Custom API endpoints on local or link-local hostnames are not allowed.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or address in _CARRIER_GRADE_NAT
    ):
        raise FoundryError("AI_PROVIDER_ENDPOINT_BLOCKED", "Custom API endpoints on private, loopback, link-local, or reserved addresses are not allowed.")
    return value


def _project_reference(value: Any) -> str | None:
    """Return a real project_id, or None for project-free probe calls."""

    text = str(value or "").strip()
    return text or None


def _agent_wait_seconds(value: Any) -> int:
    """Clamp the saved agent wait to its documented 10-3600 second range."""

    if type(value) is not int or not MIN_AGENT_WAIT_SECONDS <= value <= MAX_AGENT_WAIT_SECONDS:
        return DEFAULT_AGENT_WAIT_SECONDS
    return value


class AIProviderService:
    def __init__(
        self,
        db: Database,
        *,
        transport: httpx.BaseTransport | None = None,
        secret_store: SecretStore | None = None,
        resolver: Any | None = None,
        local_runtime: LocalAIManager | None = None,
        agent_bridge: AgentRequestBridge | None = None,
    ):
        self.db = db
        self.stage1 = Stage1ClipboardService(db)
        self.transport = transport
        self.secrets = secret_store or APIProviderSecretStore(db.settings.data_dir)
        self.agent_bridge = agent_bridge or AgentRequestBridge(db)
        self.agent_bridge.ensure_schema()
        # The documented agent polling cadence is one second; the seams exist
        # so deterministic timeout tests do not have to sleep through it.
        self.agent_poll_interval = AGENT_POLL_INTERVAL_SECONDS
        self.agent_wait_override: int | None = None
        self.resolver = resolver or self._resolve_hostname
        self.local_runtime = local_runtime or LocalAIManager(
            db.settings.root_dir / "vendor" / "lemonade",
            transport=transport,
            on_managed_ready=self._managed_runtime_ready,
        )
        self._connection_test = {"status": "NOT_TESTED", "message": "Save settings and key, then run the explicit connection test."}
        self._restart_probe_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
        # A fresh service instance may restore local readiness once from the
        # persisted selection.  Explicit configure/test actions retain their
        # existing owner-triggered behavior and disable this startup path.
        self._restart_probe_eligible = True

    def _managed_runtime_ready(self, endpoint: str, model: str, _key: str) -> None:
        """Persist the private managed endpoint once the background setup is ready."""
        now = utcnow()
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """INSERT INTO ai_provider_settings(
                       provider_id,enabled,endpoint,model,thinking_mode,max_output_tokens,
                       timeout_seconds,data_sharing_acknowledged,acknowledged_by,
                       acknowledged_at,updated_at)
                       VALUES('lemonade',1,?,?,?,?,0,NULL,NULL,?)
                       ON CONFLICT(provider_id) DO UPDATE SET
                         enabled=1,endpoint=excluded.endpoint,model=excluded.model,
                         data_sharing_acknowledged=0,acknowledged_by=NULL,
                         acknowledged_at=NULL,updated_at=excluded.updated_at""",
                    (endpoint, model, "disabled", 16384, 120, now),
                )
                conn.execute(
                    "INSERT INTO ai_provider_selection(singleton,provider_id,updated_at) VALUES(1,'lemonade',?) ON CONFLICT(singleton) DO UPDATE SET provider_id='lemonade',updated_at=excluded.updated_at",
                    (now,),
                )
            self._connection_test = {"status": "PASS", "message": "The managed Lemonade health and setup test passed."}
        except sqlite3.Error as exc:
            self._connection_test = {"status": "FAILED", "message": f"Managed Lemonade settings could not be saved: {type(exc).__name__}."}

    @staticmethod
    def _resolve_hostname(hostname: str, port: int) -> list[Any]:
        return socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)

    @staticmethod
    def _resolved_address(value: Any) -> str | None:
        if isinstance(value, str):
            return value
        if isinstance(value, tuple) and value:
            sockaddr = value[-1]
            if isinstance(sockaddr, tuple) and sockaddr:
                return str(sockaddr[0])
        return None

    @staticmethod
    def _blocked_resolved_address(address: str) -> bool:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            return True
        return bool(
            parsed.is_private
            or parsed.is_loopback
            or parsed.is_link_local
            or parsed.is_multicast
            or parsed.is_reserved
            or parsed.is_unspecified
            or parsed in _CARRIER_GRADE_NAT
        )

    def _revalidate_custom_destination(self, endpoint: str) -> None:
        checked = validate_endpoint(endpoint, provider_id="custom")
        parsed = urlsplit(checked)
        hostname = (parsed.hostname or "").rstrip(".").lower()
        if hostname in _CLOUD_METADATA_HOSTNAMES:
            raise FoundryError("AI_PROVIDER_ENDPOINT_BLOCKED", "Custom API endpoints on cloud-metadata hostnames are not allowed.")
        port = parsed.port or 443
        try:
            answers = self.resolver(hostname, port)
            addresses = [self._resolved_address(value) for value in (answers or [])]
            addresses = sorted({value for value in addresses if value})
        except Exception as exc:
            raise FoundryError(
                "AI_PROVIDER_ENDPOINT_RESOLUTION_FAILED",
                "The Custom API endpoint hostname could not be resolved safely; the request was not sent.",
                details={"hostname": hostname, "exception_type": type(exc).__name__},
                status_code=502,
            ) from exc
        if not addresses:
            raise FoundryError(
                "AI_PROVIDER_ENDPOINT_RESOLUTION_FAILED",
                "The Custom API endpoint returned no usable addresses; the request was not sent.",
                details={"hostname": hostname},
                status_code=502,
            )
        blocked = [address for address in addresses if self._blocked_resolved_address(address)]
        if blocked:
            raise FoundryError(
                "AI_PROVIDER_ENDPOINT_BLOCKED",
                "The Custom API endpoint resolved to a private, local, reserved, or metadata destination; the request was not sent.",
                details={"hostname": hostname, "resolved_addresses": addresses, "blocked_addresses": blocked},
                status_code=409,
            )

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
            "agent_wait_seconds": DEFAULT_AGENT_WAIT_SECONDS,
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
        value["agent_wait_seconds"] = _agent_wait_seconds(value.get("agent_wait_seconds"))
        return value

    def agent_bridge_status(self) -> dict[str, Any]:
        """Report the agent mailbox counts without reading any request body."""

        counts = self.agent_bridge.counts()
        settings = self._settings()
        return {
            "provider_id": settings["provider_id"],
            "enabled": bool(settings["enabled"]),
            "wait_seconds": _agent_wait_seconds(settings.get("agent_wait_seconds")),
            "selected": settings["provider_id"] == AGENT_PROVIDER_ID,
            **counts,
        }

    def agent_request_schema_errors(self, request_id: str, parsed: Any) -> list[dict[str, Any]]:
        """Validate one agent answer against its own stored request schema.

        This is the same Draft 2020-12 gate ``complete_json`` applies to a
        configured provider answer, so an agent answer never gets a weaker
        review than a model answer.
        """

        document = self.agent_bridge.get(request_id)
        schema = document.get("schema") if isinstance(document.get("schema"), dict) else None
        return self._agent_schema_errors(schema, parsed)

    def selected_ai_identity(self) -> dict[str, Any]:
        """Read the saved AI selection without status, transport, or generation.

        The DCC route uses this narrow seam to freeze provider/model identity at
        run creation.  Hosted identities bind only the saved service label;
        local identities bind the exact serving artifacts behind the saved
        loopback listener.  This seam deliberately excludes endpoints, keys,
        readiness probes, and provider transport.
        """

        settings = self._settings()
        provider_id = settings.get("provider_id")
        model = settings.get("model")
        if (
            not bool(settings.get("enabled"))
            or not isinstance(provider_id, str)
            or provider_id not in PROVIDER_PROFILES
            or not isinstance(model, str)
            or MODEL_PATTERN.fullmatch(model) is None
        ):
            return {
                "selected_ai_identity_sha256": None,
                "selected_ai_identity_state": "UNAVAILABLE_WITHOUT_PROVIDER_INVOCATION",
            }
        try:
            identity = derive_provider_identity(
                provider_id,
                model,
                endpoint=settings.get("endpoint"),
            )
        except Exception:
            # Identity is an admission gate.  Any unreadable, unsupported, or
            # otherwise unproven local state must remain unavailable.
            return {
                "selected_ai_identity_sha256": None,
                "selected_ai_identity_state": "UNAVAILABLE_WITHOUT_PROVIDER_INVOCATION",
            }
        identity_sha256 = identity.get("identity_sha256") if isinstance(identity, dict) else None
        if not isinstance(identity_sha256, str) or SHA256_LOWERHEX_PATTERN.fullmatch(identity_sha256) is None:
            return {
                "selected_ai_identity_sha256": None,
                "selected_ai_identity_state": "UNAVAILABLE_WITHOUT_PROVIDER_INVOCATION",
            }
        result: dict[str, Any] = {
            "selected_ai_identity_sha256": identity_sha256,
            "selected_ai_identity_state": "AVAILABLE_STATIC",
        }
        assurance = identity.get("identity_assurance") if isinstance(identity, dict) else None
        if isinstance(assurance, str) and assurance:
            result["identity_assurance"] = assurance
        return result

    @staticmethod
    def _restart_probe_result(
        *,
        settings: dict[str, Any],
        status: str,
        reason_code: str,
        message: str,
        started_at: float,
        models_endpoint: str | None = None,
        response_sha256: str | None = None,
        response_bytes: int = 0,
        http_status: int | None = None,
    ) -> dict[str, Any]:
        model = settings.get("model")
        safe_model = model if isinstance(model, str) and MODEL_PATTERN.fullmatch(model) else None
        endpoint = settings.get("endpoint")
        safe_endpoint = endpoint if isinstance(endpoint, str) and models_endpoint else None
        return {
            "status": status,
            "message": message,
            "probe_kind": "non_generative_model_list",
            "reason_code": reason_code,
            "provider_id": settings.get("provider_id"),
            "endpoint": safe_endpoint,
            "models_endpoint": models_endpoint,
            "model": safe_model,
            "http_status": http_status if isinstance(http_status, int) and 100 <= http_status <= 599 else None,
            "response_sha256": response_sha256 if isinstance(response_sha256, str) and SHA256_LOWERHEX_PATTERN.fullmatch(response_sha256) else None,
            "response_bytes": response_bytes if type(response_bytes) is int and 0 <= response_bytes <= MAX_LOCAL_MODEL_LIST_RESPONSE_BYTES else 0,
            "duration_ms": _elapsed_ms(started_at, time.perf_counter()),
        }

    @staticmethod
    def _read_bounded_model_list_response(
        response: httpx.Response,
        *,
        deadline: float | None = None,
    ) -> bytes:
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except (TypeError, ValueError) as exc:
                raise FoundryError(
                    "LOCAL_AI_RESTART_PROBE_RESPONSE_INVALID",
                    "The local model-list response declared an invalid size.",
                ) from exc
            if declared_length < 0 or declared_length > MAX_LOCAL_MODEL_LIST_RESPONSE_BYTES:
                raise FoundryError(
                    "LOCAL_AI_RESTART_PROBE_RESPONSE_TOO_LARGE",
                    "The local model-list response exceeded the bounded readiness-probe limit.",
                )
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            if deadline is not None and time.perf_counter() > deadline:
                raise FoundryError(
                    "LOCAL_AI_RESTART_PROBE_TIMEOUT",
                    "The local model-list readiness probe exceeded its bounded time limit.",
                )
            total += len(chunk)
            if total > MAX_LOCAL_MODEL_LIST_RESPONSE_BYTES:
                raise FoundryError(
                    "LOCAL_AI_RESTART_PROBE_RESPONSE_TOO_LARGE",
                    "The local model-list response exceeded the bounded readiness-probe limit.",
                )
            chunks.append(chunk)
        return b"".join(chunks)

    def _automatic_local_restart_probe(
        self,
        settings: dict[str, Any],
        local_status: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Restore saved local readiness without issuing a completion."""

        provider_id = settings.get("provider_id")
        if provider_id not in LOCAL_PROVIDER_IDS or not settings.get("enabled"):
            return None
        if not settings.get("endpoint") or not settings.get("model"):
            return None
        if provider_id == "lemonade":
            managed = local_status.get("managed") if isinstance(local_status, dict) else None
            managed = managed if isinstance(managed, dict) else {}
            managed_endpoint = self.local_runtime.managed.endpoint
            managed_key = self.local_runtime.managed.auth_key
            if (
                managed.get("ready") is not True
                or managed.get("process_live") is not True
                or not managed_endpoint
                or managed_endpoint != settings.get("endpoint")
                or managed.get("model") != settings.get("model")
                or not managed_key
            ):
                return None
        cache_key = (
            str(provider_id),
            str(settings.get("endpoint")),
            str(settings.get("model")),
        )
        cached = self._restart_probe_cache.get(cache_key)
        if cached is not None:
            self._connection_test = deepcopy(cached)
            return cached
        started_at = time.perf_counter()

        def finish(
            *,
            status: str,
            reason_code: str,
            message: str,
            models_endpoint: str | None = None,
            response_sha256: str | None = None,
            response_bytes: int = 0,
            http_status: int | None = None,
        ) -> dict[str, Any]:
            result = self._restart_probe_result(
                settings=settings,
                status=status,
                reason_code=reason_code,
                message=message,
                started_at=started_at,
                models_endpoint=models_endpoint,
                response_sha256=response_sha256,
                response_bytes=response_bytes,
                http_status=http_status,
            )
            self._restart_probe_cache[cache_key] = deepcopy(result)
            self._connection_test = result
            return result

        if not isinstance(settings.get("model"), str) or MODEL_PATTERN.fullmatch(settings["model"]) is None:
            return finish(
                status="FAILED",
                reason_code="model_invalid",
                message="Automatic local readiness could not validate the saved model ID.",
            )

        models_endpoint: str | None = None
        try:
            models_endpoint = _local_models_endpoint(settings.get("endpoint"))
        except FoundryError:
            return finish(
                status="FAILED",
                reason_code="endpoint_invalid",
                message="Automatic local readiness could not validate the saved loopback endpoint.",
            )

        headers = {
            "Accept": "application/json",
            "User-Agent": "TianxiaCharacterFoundry/LocalReadinessProbe",
        }
        if provider_id == "lemonade":
            headers["Authorization"] = "Bearer " + str(self.local_runtime.managed.auth_key)
        response_hash: str | None = None
        response_bytes = 0
        http_status: int | None = None
        try:
            timeout = httpx.Timeout(LOCAL_RESTART_READINESS_TIMEOUT_SECONDS)
            try:
                client = httpx.Client(
                    transport=self.transport,
                    timeout=timeout,
                    follow_redirects=False,
                    trust_env=False,
                )
            except TypeError:
                client = httpx.Client(
                    transport=self.transport,
                    timeout=timeout,
                    follow_redirects=False,
                )
            with client:
                with client.stream("GET", models_endpoint, headers=headers) as response:
                    http_status = response.status_code
                    if 300 <= response.status_code < 400:
                        return finish(
                            status="FAILED",
                            reason_code="redirect_rejected",
                            message="Automatic local readiness rejected a redirect from the loopback model-list endpoint.",
                            models_endpoint=models_endpoint,
                            http_status=http_status,
                        )
                    if response.status_code != 200:
                        return finish(
                            status="FAILED",
                            reason_code="http_status_rejected",
                            message="Automatic local readiness did not receive a successful model-list response.",
                            models_endpoint=models_endpoint,
                            http_status=http_status,
                        )
                    body = self._read_bounded_model_list_response(
                        response,
                        deadline=started_at + LOCAL_RESTART_READINESS_TIMEOUT_SECONDS,
                    )
                    response_bytes = len(body)
                    response_hash = sha256_bytes(body)
        except FoundryError as exc:
            reason_code = (
                "response_too_large"
                if exc.code == "LOCAL_AI_RESTART_PROBE_RESPONSE_TOO_LARGE"
                else "timeout"
                if exc.code == "LOCAL_AI_RESTART_PROBE_TIMEOUT"
                else "response_invalid"
            )
            message = (
                "Automatic local readiness rejected an oversized model-list response."
                if reason_code == "response_too_large"
                else "Automatic local readiness timed out its bounded model-list probe."
                if reason_code == "timeout"
                else "Automatic local readiness received an invalid model-list response."
            )
            return finish(
                status="FAILED",
                reason_code=reason_code,
                message=message,
                models_endpoint=models_endpoint,
                response_sha256=response_hash,
                response_bytes=response_bytes,
                http_status=http_status,
            )
        except httpx.HTTPError:
            return finish(
                status="FAILED",
                reason_code="network_error",
                message="Automatic local readiness could not complete the bounded model-list request.",
                models_endpoint=models_endpoint,
                response_sha256=response_hash,
                response_bytes=response_bytes,
                http_status=http_status,
            )
        except Exception:
            return finish(
                status="FAILED",
                reason_code="probe_error",
                message="Automatic local readiness failed its bounded model-list probe.",
                models_endpoint=models_endpoint,
                response_sha256=response_hash,
                response_bytes=response_bytes,
                http_status=http_status,
            )

        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return finish(
                status="FAILED",
                reason_code="response_invalid",
                message="Automatic local readiness received invalid JSON from the model-list endpoint.",
                models_endpoint=models_endpoint,
                response_sha256=response_hash,
                response_bytes=response_bytes,
                http_status=http_status,
            )
        model_ids = _local_model_ids(value)
        configured_model = settings.get("model")
        if model_ids is None:
            reason_code = "response_invalid"
            message = "Automatic local readiness received an invalid model-list shape."
            result_status = "FAILED"
        elif configured_model not in model_ids:
            reason_code = "model_not_found"
            message = "Automatic local readiness did not find the configured model in the model list."
            result_status = "FAILED"
        else:
            reason_code = "model_list_match"
            message = "Automatic local model-list readiness probe passed."
            result_status = "PASS"
        return finish(
            status=result_status,
            reason_code=reason_code,
            message=message,
            models_endpoint=models_endpoint,
            response_sha256=response_hash,
            response_bytes=response_bytes,
            http_status=http_status,
        )

    def status(self) -> dict[str, Any]:
        settings = self._settings()
        profile = provider_profile(settings["provider_id"])
        is_local = settings["provider_id"] in LOCAL_PROVIDER_IDS
        is_agent = settings["provider_id"] == AGENT_PROVIDER_ID
        agent_bridge_status = self.agent_bridge_status()
        secret = (
            {"present": True, "source": "agent_no_key", "persistent": False, "environment_variable": None, "provider_id": settings["provider_id"]}
            if is_agent
            else {"present": True, "source": "loopback_no_key", "persistent": False, "environment_variable": None, "provider_id": settings["provider_id"]}
            if is_local
            else self.secrets.status(settings["provider_id"])
        )
        local_status = self.local_runtime.status() if is_local else None
        if (
            self._restart_probe_eligible
            and is_local
            and self._connection_test.get("status") == "NOT_TESTED"
        ):
            self._automatic_local_restart_probe(settings, local_status)
        local_ready = bool(
            is_local
            and settings["enabled"]
            and settings.get("endpoint")
            and settings.get("model")
            and (settings["provider_id"] != "lemonade" or local_status.get("managed", {}).get("ready"))
            and self._connection_test["status"] == "PASS"
        )
        prerequisites_ready = local_ready if is_local else bool(
            settings["enabled"]
            and settings["data_sharing_acknowledged"]
            and settings.get("acknowledged_by")
            and secret["present"]
        )
        if not settings["enabled"]:
            readiness_state, readiness_reason = "DISABLED_BY_OWNER", f"{profile['display_name']} is disabled in the saved settings."
        elif is_agent:
            # The bridge has no endpoint to probe and no key to hold: readiness
            # is the named acknowledgement plus the enabled setting.  The
            # mailbox counters below are the real operational evidence.
            if not settings["data_sharing_acknowledged"] or not settings.get("acknowledged_by"):
                readiness_state, readiness_reason = "ACKNOWLEDGEMENT_MISSING", "A named data-sharing acknowledgement is required."
            else:
                readiness_state, readiness_reason = (
                    "AGENT_BRIDGE_READY",
                    f"The agent bridge is waiting for agent answers ({agent_bridge_status['pending']} pending).",
                )
        elif is_local and settings["provider_id"] == "lemonade" and not local_status.get("managed", {}).get("ready"):
            readiness_state, readiness_reason = "LOCAL_AI_NOT_READY", "Built-in Local AI is selected but has not finished setup."
        elif is_local and self._connection_test["status"] == "FAILED":
            readiness_state, readiness_reason = "CONNECTION_FAILED", self._connection_test["message"]
        elif is_local and self._connection_test["status"] != "PASS":
            readiness_state, readiness_reason = "CONNECTION_NOT_TESTED", "Select a detected model or finish built-in Local AI setup, then run the explicit connection test."
        elif not is_local and (not settings["data_sharing_acknowledged"] or not settings.get("acknowledged_by")):
            readiness_state, readiness_reason = "ACKNOWLEDGEMENT_MISSING", "A named data-sharing acknowledgement is required."
        elif not is_local and not secret["present"]:
            readiness_state, readiness_reason = "KEY_MISSING", "No protected API Provider key is stored."
        elif self._connection_test["status"] == "FAILED":
            readiness_state, readiness_reason = "CONNECTION_FAILED", self._connection_test["message"]
        elif self._connection_test["status"] != "PASS":
            readiness_state, readiness_reason = "CONNECTION_NOT_TESTED", "Settings and key are saved; run Test Connection once."
        else:
            readiness_state, readiness_reason = (
                (
                    "READY",
                    "Selected local endpoint and model-list readiness probe passed."
                    if self._connection_test.get("probe_kind") == "non_generative_model_list"
                    else "Selected local endpoint, model, and explicit connection test passed.",
                )
                if is_local
                else ("READY", "Saved settings, protected key, acknowledgement, and connection test passed.")
            )
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
                "local": bool(profile.get("local")),
                "managed": bool(profile.get("managed")),
                "agent": bool(profile.get("agent")),
            },
            "profiles": [
                {
                    "provider_id": profile_id,
                    "display_name": row["display_name"],
                    "endpoint": row["endpoint"],
                    "default_model": row["default_model"],
                    "supports_thinking": row["supports_thinking"],
                    "preset": row["preset"],
                    "local": bool(row.get("local")),
                    "managed": bool(row.get("managed")),
                    "agent": bool(row.get("agent")),
                }
                for profile_id, row in PROVIDER_PROFILES.items()
            ],
            "secret": secret,
            "ready": bool(
                settings["enabled"]
                and settings["data_sharing_acknowledged"]
                and settings.get("acknowledged_by")
                if is_agent
                else prerequisites_ready and self._connection_test["status"] == "PASS"
            ),
            "readiness_state": readiness_state,
            "readiness_reason": readiness_reason,
            "connection_test": dict(self._connection_test),
            "agent_bridge": agent_bridge_status,
            "manual_clipboard_available": True,
            "combat_transport_available": True,
            "direct_commit_allowed": False,
            "mechanical_authority": False,
            "automatic_retries": 0,
            "usage_totals": dict(totals),
            "local_ai": local_status if is_local else self.local_runtime.status(),
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
        agent_wait_seconds: int | None = None,
    ) -> dict[str, Any]:
        provider_id = str(provider_id or PROVIDER_ID).strip()
        profile = provider_profile(provider_id)
        if provider_id in LOCAL_PROVIDER_IDS:
            endpoint = validate_endpoint(endpoint or "", provider_id=provider_id)
        else:
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
        if provider_id in LOCAL_PROVIDER_IDS:
            timeout_seconds = max(timeout_seconds, LOCAL_HTTP_TIMEOUT_SECONDS)
        if provider_id == AGENT_PROVIDER_ID:
            # The bridge has no HTTP call, so the provider timeout does not
            # apply; the saved agent wait is the bounded wait for one answer.
            if agent_wait_seconds is None:
                agent_wait_seconds = DEFAULT_AGENT_WAIT_SECONDS
            if type(agent_wait_seconds) is not int or not MIN_AGENT_WAIT_SECONDS <= agent_wait_seconds <= MAX_AGENT_WAIT_SECONDS:
                raise FoundryError(
                    "AI_AGENT_WAIT_INVALID",
                    f"agent_wait_seconds must be an integer between {MIN_AGENT_WAIT_SECONDS} and {MAX_AGENT_WAIT_SECONDS}.",
                    details={"agent_wait_seconds": agent_wait_seconds},
                )
        else:
            agent_wait_seconds = _agent_wait_seconds(self._settings().get("agent_wait_seconds"))
        actor = str(acknowledged_by or "").strip()
        if enabled and provider_id not in LOCAL_PROVIDER_IDS and (not data_sharing_acknowledged or not actor):
            raise FoundryError(
                "AI_PROVIDER_DATA_SHARING_ACKNOWLEDGEMENT_REQUIRED",
                "Enabling the API Provider requires a named acknowledgement that prompt data will be sent to the selected service.",
            )
        if len(actor) > 200:
            raise FoundryError("AI_PROVIDER_ACKNOWLEDGEMENT_ACTOR_INVALID", "The acknowledgement actor is too long.")
        now = utcnow()
        if provider_id in LOCAL_PROVIDER_IDS:
            data_sharing_acknowledged = False
            actor = ""
        acknowledged_at = now if data_sharing_acknowledged and actor else None
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO ai_provider_settings(
                   provider_id,enabled,endpoint,model,thinking_mode,max_output_tokens,
                   timeout_seconds,data_sharing_acknowledged,acknowledged_by,
                   acknowledged_at,updated_at,agent_wait_seconds)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
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
                     updated_at=excluded.updated_at,
                     agent_wait_seconds=excluded.agent_wait_seconds""",
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
                    agent_wait_seconds,
                ),
            )
            conn.execute(
                "INSERT INTO ai_provider_selection(singleton,provider_id,updated_at) VALUES(1,?,?) ON CONFLICT(singleton) DO UPDATE SET provider_id=excluded.provider_id,updated_at=excluded.updated_at",
                (provider_id, now),
            )
        self._restart_probe_eligible = False
        self._restart_probe_cache.clear()
        self._connection_test = {"status": "NOT_TESTED", "message": "Saved provider settings changed; run the explicit connection test."}
        return self.status()

    def local_ai_status(self) -> dict[str, Any]:
        """Return runtime discovery plus the selected provider readiness."""
        result = self.local_runtime.status()
        result["provider"] = self.status() if self._selected_provider_id() in LOCAL_PROVIDER_IDS else None
        return result

    def detect_local_ai(self, *, ports: list[int] | None = None) -> dict[str, Any]:
        result = self.local_runtime.detect(ports=ports)
        result["provider"] = self.status() if self._selected_provider_id() in LOCAL_PROVIDER_IDS else None
        return result

    def select_local_ai(self, *, endpoint: str, model: str, provider_id: str = "local") -> dict[str, Any]:
        provider_id = str(provider_id or "local").strip().lower()
        if provider_id not in LOCAL_PROVIDER_IDS:
            raise FoundryError("LOCAL_AI_PROFILE_INVALID", "Local AI selection must use the detected local or built-in Lemonade profile.")
        if provider_id == "lemonade" and endpoint != self.local_runtime.managed.endpoint:
            raise FoundryError("LOCAL_AI_MANAGED_SELECTION_INVALID", "Built-in Local AI selections must use the managed loopback endpoint currently owned by Lemonade.")
        if provider_id == "local":
            # A DCC run binds the frozen request to a model identity it can
            # prove belongs to this user.  Detection lists anything answering on
            # the loopback ports, so a model served by another user (for example
            # from inside a container running as root) appears here and passes a
            # plain connection test, then fails the run with
            # DCC_SELECTED_AI_UNAVAILABLE.  Refuse it at the point of choosing so
            # the owner is not offered a model that cannot build.
            try:
                derive_provider_identity(provider_id, model, endpoint=endpoint)
            except Exception as exc:
                raise FoundryError(
                    "DCC_SELECTED_AI_UNAVAILABLE",
                    "The selected AI is unavailable without invoking provider status or transport.",
                    details={"endpoint": endpoint, "model": model, "reason": str(exc)},
                    status_code=409,
                ) from exc
        result = self.configure(
            enabled=True,
            provider_id=provider_id,
            endpoint=endpoint,
            model=model,
            thinking_mode="disabled",
            max_output_tokens=16384,
            timeout_seconds=LOCAL_HTTP_TIMEOUT_SECONDS,
            data_sharing_acknowledged=False,
            acknowledged_by=None,
        )
        try:
            test = self.test_connection()
        except FoundryError as exc:
            result = self.status()
            result["selection_test"] = {"status": "FAILED", "message": exc.message, "code": exc.code}
            return result
        result = self.status()
        result["selection_test"] = test
        return result

    def select_managed_local_ai(self, *, model: str = DEFAULT_LOCAL_MODEL) -> dict[str, Any]:
        selected = self.local_runtime.managed.select(model)
        endpoint = self.local_runtime.managed.endpoint or "http://127.0.0.1:13305/api/v1/chat/completions"
        result = self.configure(
            enabled=True,
            provider_id="lemonade",
            endpoint=endpoint,
            model=selected["model"],
            thinking_mode="disabled",
            max_output_tokens=16384,
            timeout_seconds=LOCAL_HTTP_TIMEOUT_SECONDS,
            data_sharing_acknowledged=False,
            acknowledged_by=None,
        )
        return {"selection": result, "managed": self.local_runtime.managed.status()}

    def prepare_managed_local_ai(self, *, model: str = DEFAULT_LOCAL_MODEL) -> dict[str, Any]:
        self.select_managed_local_ai(model=model)
        managed = self.local_runtime.managed.prepare(model)
        return {"managed": managed, "provider": self.status()}

    def stop_local_runtime(self) -> None:
        self.local_runtime.stop()

    def set_api_key(self, api_key: str) -> dict[str, Any]:
        selected = self._selected_provider_id()
        if selected in LOCAL_PROVIDER_IDS:
            raise FoundryError("LOCAL_AI_API_KEY_NOT_REQUIRED", "Local AI uses loopback transport and does not accept a cloud API key.")
        if selected == AGENT_PROVIDER_ID:
            # The agent's own harness holds the model credential; the app never
            # receives it, so there is nothing to store here.
            raise FoundryError(
                "AI_AGENT_API_KEY_NOT_REQUIRED",
                "The Agent bridge holds no key: the agent's own harness owns its model session.",
            )
        self.secrets.set(api_key, selected)
        self._connection_test = {"status": "NOT_TESTED", "message": "The protected key changed; run the explicit connection test."}
        return self.status()

    def delete_api_key(self) -> dict[str, Any]:
        if self._selected_provider_id() == AGENT_PROVIDER_ID:
            raise FoundryError(
                "AI_AGENT_API_KEY_NOT_REQUIRED",
                "The Agent bridge holds no key: the agent's own harness owns its model session.",
            )
        removed = self.secrets.delete(self._selected_provider_id())
        self._connection_test = {"status": "NOT_TESTED", "message": "No protected key is stored."}
        return {"removed": removed, **self.status()}

    def test_connection(self) -> dict[str, Any]:
        """Run one explicit, owner-triggered, non-authoritative API Provider probe."""
        settings = self._settings()
        profile = provider_profile(settings["provider_id"])
        if settings["provider_id"] == AGENT_PROVIDER_ID:
            # There is no endpoint to probe.  The bridge is exercised by the
            # explicit agent routes, never by a network connection test.
            self._connection_test = {
                "status": "PASS",
                "message": "The Agent bridge has no endpoint; readiness is the named acknowledgement and the mailbox counters.",
            }
            bridge = self.agent_bridge_status()
            return {
                "provider_id": settings["provider_id"],
                "status": "PASS",
                "model": settings["model"],
                "agent_bridge": bridge,
                "network_request_made": False,
                "secret_returned": False,
            }
        try:
            result = self.complete_json(
                prompt_text='Return exactly {"connection":"ok"}.',
                system_message="Return one JSON object for a local connection test. No tools and no mechanical authority.",
                purpose="owner_connection_test",
                substantive=False,
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
            "usage": _safe_connection_usage(result.get("usage")),
            "performance": _safe_connection_performance(result.get("performance")),
            "timings": _safe_connection_timings(result.get("timings")),
        }

    @staticmethod
    def _max_output_tokens(
        settings: dict[str, Any],
        *,
        substantive: bool,
        purpose: str | None = None,
    ) -> int:
        # The agent bridge shares the bounded ceilings: its request must carry
        # exactly the wire bytes the caller authorized, and every answer body is
        # bounded again by the request's own max_tokens.
        if settings["provider_id"] == AGENT_PROVIDER_ID:
            ceiling = AGENT_MAX_OUTPUT_TOKENS
        elif settings["provider_id"] not in LOCAL_PROVIDER_IDS:
            ceiling = 8192
        elif not substantive:
            ceiling = LOCAL_PROBE_MAX_OUTPUT_TOKENS
        elif purpose == COMMAND4_ACTION_AUTHORING_PURPOSE:
            ceiling = LOCAL_COMMAND4_MAX_OUTPUT_TOKENS
        elif purpose == GM_TACTICAL_AUTHORING_PURPOSE:
            ceiling = LOCAL_GM_AUTHORING_MAX_OUTPUT_TOKENS
        else:
            ceiling = LOCAL_SUBSTANTIVE_MAX_OUTPUT_TOKENS
        return min(int(settings["max_output_tokens"]), ceiling)

    @staticmethod
    def _request_payload(
        prompt_text: str,
        settings: dict[str, Any],
        *,
        substantive: bool = True,
    ) -> dict[str, Any]:
        is_local = settings["provider_id"] in LOCAL_PROVIDER_IDS
        payload = {
            "model": settings["model"],
            "messages": [
                {"role": "system", "content": SYSTEM_MESSAGE},
                {"role": "user", "content": prompt_text},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": AIProviderService._max_output_tokens(settings, substantive=substantive),
            "stream": False,
        }
        if is_local:
            # llama.cpp-compatible local servers expose this nested knob for
            # Qwen/Gemma; keep the provider in direct JSON mode and avoid
            # spending the bounded completion budget on hidden reasoning.
            payload["chat_template_kwargs"] = {"enable_thinking": False}
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
            # Only the agent bridge writes this: it records the answering
            # agent/model in the audit row (Job 1 A5).  The canonical request
            # bytes and the configured selection are never touched by it.
            "model",
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
            result.append(
                token_count
                if type(token_count) is int and 0 <= token_count <= 1_000_000_000_000
                else None
            )
        return result[0], result[1], result[2]

    def _contract_failure_details(
        self,
        *,
        purpose: str,
        reason_code: str,
        response_sha256: str,
        provider_value: Any,
        content: Any,
        finish_reason: Any,
        duration_ms: int,
        request_preparation_started: float,
        request_prepared_at: float,
        response_parse_started: float,
    ) -> dict[str, Any]:
        """Return bounded diagnostics without retaining provider payload text."""

        envelope = provider_value if isinstance(provider_value, dict) else {}
        prompt_tokens, completion_tokens, total_tokens = self._usage(envelope.get("usage"))
        completion_hash = sha256_bytes(content.encode("utf-8")) if isinstance(content, str) else None
        completion_bytes = len(content.encode("utf-8")) if isinstance(content, str) else 0
        rate = (
            round(completion_tokens / (duration_ms / 1000), 2)
            if isinstance(completion_tokens, int) and completion_tokens >= 0 and duration_ms > 0
            else None
        )
        failed_at = time.perf_counter()
        phases = {
            "request_preparation": _elapsed_ms(request_preparation_started, request_prepared_at),
            "provider_transport": duration_ms,
            "response_body_parse": _elapsed_ms(response_parse_started, failed_at),
        }
        details: dict[str, Any] = {
            "purpose": purpose,
            "reason": reason_code if reason_code in _CONTRACT_FAILURE_REASON_CODES else "other",
            "response_sha256": response_sha256,
            "completion_sha256": completion_hash,
            "completion_bytes": completion_bytes,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
            "performance": {
                "duration_ms": duration_ms,
                "duration_seconds": round(duration_ms / 1000, 3),
                "completion_tokens_per_second": rate,
            },
            "timings": {
                "schema": AI_PROVIDER_TIMING_SCHEMA,
                "phases_ms": phases,
                "provider_reported": _safe_provider_timings(envelope.get("timings")),
            },
        }
        safe_finish_reason = _safe_finish_reason(finish_reason)
        if safe_finish_reason is not None:
            details["finish_reason"] = safe_finish_reason
        return details

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

    def _provider_call(self, *, endpoint: str, key: str | None, request_bytes: bytes, timeout_seconds: int) -> tuple[int, bytes]:
        provider_id = self._selected_provider_id()
        if provider_id == "custom":
            # Re-resolve after all settings/key checks and immediately before
            # opening the client. No redirect or proxy environment is allowed
            # to turn the reviewed destination into a different one.
            self._revalidate_custom_destination(endpoint)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "TianxiaCharacterFoundry/Stage1",
        }
        if key:
            headers["Authorization"] = "Bearer " + key
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

    def complete_json(
        self,
        *,
        prompt_text: str,
        system_message: str,
        purpose: str,
        substantive: bool = True,
        response_schema: dict[str, Any] | None = None,
        response_schema_name: str = LOCAL_CORRECTION_SCHEMA_NAME,
        response_schema_max_output_tokens: int | None = None,
        max_request_bytes: int | None = None,
        temperature: float | int | None = None,
        expected_request_sha256: str | None = None,
        timeout_seconds: int | None = None,
        idempotency_key: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Return one provider JSON object without granting it mechanical authority.

        The caller remains responsible for exact schema/ID validation and for recording any
        domain-specific audit evidence. This transport never retries automatically.

        ``idempotency_key`` is optional and additive: the in-app callers that
        must survive a re-drive pass the deterministic fingerprint of their
        exact request, and this transport then returns the recorded receipt for
        a step that already reached a terminal outcome instead of prompting
        again.
        """
        if max_request_bytes is not None and (
            type(max_request_bytes) is not int or max_request_bytes <= 0
        ):
            raise FoundryError(
                "AI_PROVIDER_REQUEST_SIZE_INVALID",
                "The optional provider request byte limit must be a positive integer.",
            )
        if expected_request_sha256 is not None and (
            type(expected_request_sha256) is not str
            or SHA256_LOWERHEX_PATTERN.fullmatch(expected_request_sha256) is None
        ):
            raise FoundryError(
                "AI_PROVIDER_REQUEST_HASH_INVALID",
                "The optional expected provider request hash must be 64 lowercase hexadecimal characters.",
            )
        if timeout_seconds is not None and (
            type(timeout_seconds) is not int or not 10 <= timeout_seconds <= 300
        ):
            raise FoundryError("AI_PROVIDER_TIMEOUT_INVALID", "timeout_seconds must be between 10 and 300.")
        invalid_temperature = False
        if temperature is not None:
            if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
                invalid_temperature = True
            else:
                try:
                    normalized_temperature = float(temperature)
                except (OverflowError, TypeError, ValueError):
                    invalid_temperature = True
                else:
                    invalid_temperature = not math.isfinite(normalized_temperature) or not 0 <= normalized_temperature <= 2
        if invalid_temperature:
            raise FoundryError(
                "AI_PROVIDER_TEMPERATURE_INVALID",
                "The optional generation temperature must be a finite number between 0 and 2.",
            )
        settings = self._settings()
        profile = provider_profile(settings["provider_id"])
        is_local = settings["provider_id"] in LOCAL_PROVIDER_IDS
        is_agent = settings["provider_id"] == AGENT_PROVIDER_ID
        if not settings["enabled"]:
            raise FoundryError("AI_PROVIDER_DISABLED", "The optional API Provider is disabled.")
        if not is_local and not settings["data_sharing_acknowledged"]:
            raise FoundryError(
                "AI_PROVIDER_DATA_SHARING_ACKNOWLEDGEMENT_REQUIRED",
                "Prompt transmission has not been acknowledged by a named user.",
            )
        key = self.local_runtime.managed.auth_key if settings["provider_id"] == "lemonade" else None if is_local else None if is_agent else self.secrets.get(settings["provider_id"])
        if not is_local and not is_agent and key is None:
            raise FoundryError("AI_PROVIDER_API_KEY_MISSING", "No API Provider key is available.")
        if is_local and (not settings.get("endpoint") or not settings.get("model")):
            raise FoundryError("LOCAL_AI_NOT_SELECTED", "Select a detected local model or prepare built-in Local AI before building.")
        if settings["provider_id"] == "lemonade" and not key:
            raise FoundryError("LOCAL_AI_NOT_READY", "Built-in Local AI is still preparing; wait for the ready status before building.")
        response_format: dict[str, Any] = {"type": "json_object"}
        schema_copy: dict[str, Any] | None = None
        if not isinstance(response_schema_name, str) or not re.fullmatch(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$", response_schema_name):
            raise FoundryError(
                "AI_PROVIDER_RESPONSE_SCHEMA_INVALID",
                "The Local AI response schema name is invalid.",
            )
        # The agent bridge follows the same local runtime-token ceilings: a
        # request carries the settings max_output_tokens and the schema cap
        # further bounds it, exactly as it does for a local model.
        # The agent bridge mirrors the local purpose-scoped budgets, because its
        # callers size the wire with these same ceilings.
        bounded_provider = is_local or is_agent
        response_schema_token_ceiling = (
            LOCAL_COMMAND4_MAX_OUTPUT_TOKENS
            if bounded_provider and purpose == COMMAND4_ACTION_AUTHORING_PURPOSE
            else LOCAL_GM_AUTHORING_MAX_OUTPUT_TOKENS
            if bounded_provider and purpose == GM_TACTICAL_AUTHORING_PURPOSE
            else LOCAL_SUBSTANTIVE_MAX_OUTPUT_TOKENS
            if bounded_provider and purpose == COMPOSITE_CONTROLLER_AUTHORING_PURPOSE
            else 256
            if bounded_provider and purpose == DCC_LINEAR_STEP_PURPOSE
            else 1024
        )
        if response_schema_max_output_tokens is not None and (
            response_schema is None
            or type(response_schema_max_output_tokens) is not int
            or not 1 <= response_schema_max_output_tokens <= response_schema_token_ceiling
        ):
            raise FoundryError(
                "AI_PROVIDER_RESPONSE_SCHEMA_INVALID",
                "The bounded response schema token limit is invalid.",
                details={"max_tokens": response_schema_token_ceiling},
            )
        if response_schema is not None:
            if not is_local and not is_agent:
                raise FoundryError(
                    "AI_PROVIDER_RESPONSE_SCHEMA_UNSUPPORTED",
                    "A strict response schema is supported only for Local AI correction calls.",
                )
            if not isinstance(response_schema, dict):
                raise FoundryError(
                    "AI_PROVIDER_RESPONSE_SCHEMA_INVALID",
                    "The Local AI response schema must be a JSON object.",
                )
            schema_copy = deepcopy(response_schema)
            try:
                schema_bytes = canonical_json(schema_copy).encode("utf-8")
            except (TypeError, ValueError) as exc:
                raise FoundryError(
                    "AI_PROVIDER_RESPONSE_SCHEMA_INVALID",
                    "The Local AI response schema must contain only JSON values.",
                ) from exc
            if len(schema_bytes) > MAX_LOCAL_RESPONSE_SCHEMA_BYTES:
                raise FoundryError(
                    "AI_PROVIDER_RESPONSE_SCHEMA_INVALID",
                    "The Local AI response schema exceeded the bounded schema limit.",
                    details={"max_bytes": MAX_LOCAL_RESPONSE_SCHEMA_BYTES},
                )
            try:
                Draft202012Validator.check_schema(schema_copy)
            except SchemaError as exc:
                raise FoundryError(
                    "AI_PROVIDER_RESPONSE_SCHEMA_INVALID",
                    "The Local AI response schema is not a valid JSON Schema.",
                    details={"reason": str(exc)},
                ) from exc
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": response_schema_name,
                    "strict": True,
                    "schema": schema_copy,
                },
            }
        if is_agent:
            # Exact wire parity with each caller's canonical helper: composite
            # and GM authoring authorize the 6144 bounded wire, while Command 4
            # authoring authorizes its own 16384 ceiling.  The answer body is
            # bounded from this same value.
            max_output_tokens = (
                LOCAL_COMMAND4_MAX_OUTPUT_TOKENS
                if purpose == COMMAND4_ACTION_AUTHORING_PURPOSE
                else LOCAL_SUBSTANTIVE_MAX_OUTPUT_TOKENS
            )
        else:
            max_output_tokens = self._max_output_tokens(settings, substantive=substantive, purpose=purpose)
            if schema_copy is not None:
                max_output_tokens = min(
                    max_output_tokens,
                    response_schema_max_output_tokens or LOCAL_SCHEMA_MAX_OUTPUT_TOKENS,
                )
        request_preparation_started = time.perf_counter()
        request_payload = {
            "model": settings["model"],
            "messages": [
                {"role": "system", "content": str(system_message)},
                {"role": "user", "content": str(prompt_text)},
            ],
            "response_format": response_format,
            "max_tokens": max_output_tokens,
            "stream": False,
        }
        if temperature is not None:
            request_payload["temperature"] = temperature
        if is_local:
            request_payload["chat_template_kwargs"] = {"enable_thinking": False}
            request_payload["cache_prompt"] = True
        if settings["provider_id"] == "deepseek":
            request_payload["thinking"] = {"type": settings["thinking_mode"]}
        request_bytes = canonical_json(request_payload).encode("utf-8")
        request_sha256 = sha256_bytes(request_bytes)
        request_prepared_at = time.perf_counter()
        idempotency_key = str(idempotency_key or "").strip()
        if idempotency_key:
            # ``idempotency_key`` is the caller's step key.  A finished run for
            # the same step returns its recorded receipt without prompting a
            # provider or an agent again, and the recorded request bytes are
            # re-checked first so changed settings can never silently reuse a
            # receipt for a different request.
            step_key = idempotency_key
            existing = self._existing_idempotent_run(
                purpose,
                step_key,
                provider_id=settings["provider_id"],
            )
            if existing is not None:
                self._require_same_request_bytes(existing, prompt_id=purpose, idempotency_key=step_key, request_sha256=request_sha256)
                return self._resume_existing_run(
                    existing,
                    purpose=purpose,
                    idempotency_key=step_key,
                    project_id=project_id,
                )
        if expected_request_sha256 is not None and expected_request_sha256 != request_sha256:
            raise FoundryError(
                "AI_PROVIDER_REQUEST_CHANGED",
                "The provider settings changed after the request was authorized; no network request was made.",
                details={
                    "expected_request_sha256": expected_request_sha256,
                    "actual_request_sha256": request_sha256,
                    "provider_called": False,
                },
                status_code=409,
            )
        if max_request_bytes is not None and len(request_bytes) > max_request_bytes:
            raise FoundryError(
                "AI_PROVIDER_REQUEST_TOO_LARGE",
                "The canonical provider request exceeded its exact byte limit; no network request was made.",
                details={
                    "request_bytes": len(request_bytes),
                    "max_request_bytes": max_request_bytes,
                    "provider_called": False,
                },
                status_code=413,
            )
        request_started = request_prepared_at
        if is_agent:
            return self._complete_json_via_agent(
                purpose=purpose,
                prompt=prompt_text,
                profile=profile,
                settings=settings,
                response_schema_name=response_schema_name,
                schema_copy=schema_copy,
                request_payload=request_payload,
                request_bytes=request_bytes,
                request_sha256=request_sha256,
                max_output_tokens=max_output_tokens,
                request_preparation_started=request_preparation_started,
                request_prepared_at=request_prepared_at,
                project_id=project_id,
                caller_key=idempotency_key,
            )
        http_status, response_bytes = self._provider_call(
            endpoint=settings["endpoint"],
            key=key,
            request_bytes=request_bytes,
            timeout_seconds=(
                timeout_seconds
                if timeout_seconds is not None
                else _provider_timeout_seconds(settings, substantive=substantive)
            ),
        )
        provider_transport_finished = time.perf_counter()
        duration_ms = max(1, round((provider_transport_finished - request_started) * 1000))
        response_hash = sha256_bytes(response_bytes)
        if http_status != 200:
            raise FoundryError(
                "AI_PROVIDER_HTTP_ERROR",
                f"{profile['display_name']} rejected the request.",
                details={"http_status": http_status, "response_sha256": response_hash, "purpose": purpose},
                status_code=502,
            )
        response_parse_started = provider_transport_finished
        provider_value: Any = None
        content: Any = None
        finish_reason: Any = None
        contract_reason = "invalid_json"
        try:
            provider_value = json.loads(response_bytes.decode("utf-8"))
            if not isinstance(provider_value, dict):
                contract_reason = "response_not_object"
                raise ValueError("Provider response is not one JSON object.")
            choices = provider_value.get("choices")
            if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
                contract_reason = "response_shape_invalid"
                raise ValueError("Provider response choices are not one object.")
            choice = choices[0]
            message = choice.get("message") if isinstance(choice, dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
            if not isinstance(content, str) or not content.strip():
                contract_reason = "missing_content"
                raise ValueError("Provider completion content is empty or missing.")
            if isinstance(message.get("tool_calls"), list) and message["tool_calls"]:
                contract_reason = "tool_calls_present"
                raise ValueError("Provider returned tool calls even though tools were not offered.")
            if finish_reason != "stop":
                contract_reason = "finish_reason_not_stop"
                raise ValueError("Provider finish reason is not stop.")
            try:
                parsed = json.loads(content)
            except (TypeError, ValueError):
                contract_reason = "invalid_json"
                raise
            if not isinstance(parsed, dict):
                contract_reason = "response_not_object"
                raise ValueError("Provider completion is not one JSON object.")
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, IndexError, ValueError):
            raise FoundryError(
                "AI_PROVIDER_RESPONSE_CONTRACT_INVALID",
                f"{profile['display_name']} returned a response that cannot enter the local JSON validator.",
                details=self._contract_failure_details(
                    purpose=purpose,
                    reason_code=contract_reason,
                    response_sha256=response_hash,
                    provider_value=provider_value,
                    content=content,
                    finish_reason=finish_reason,
                    duration_ms=duration_ms,
                    request_preparation_started=request_preparation_started,
                    request_prepared_at=request_prepared_at,
                    response_parse_started=response_parse_started,
                ),
                status_code=502,
            ) from None
        if schema_copy is not None:
            try:
                Draft202012Validator(schema_copy).validate(parsed)
            except ValidationError as exc:
                details = self._contract_failure_details(
                    purpose=purpose,
                    reason_code="response_schema_validation_failed",
                    response_sha256=response_hash,
                    provider_value=provider_value,
                    content=content,
                    finish_reason=finish_reason,
                    duration_ms=duration_ms,
                    request_preparation_started=request_preparation_started,
                    request_prepared_at=request_prepared_at,
                    response_parse_started=response_parse_started,
                )
                details.update(
                    self._schema_failure_locators(
                        schema_copy,
                        parsed,
                        schema_name=response_schema_name,
                        schema_error=exc,
                    )
                )
                raise FoundryError(
                    "AI_PROVIDER_RESPONSE_CONTRACT_INVALID",
                    f"{profile['display_name']} returned JSON that failed the requested response schema.",
                    details=details,
                    status_code=502,
                ) from exc
        response_parse_finished = time.perf_counter()
        provider_reported_timings = _safe_provider_timings(provider_value.get("timings"))
        prompt_tokens, completion_tokens, total_tokens = self._usage(provider_value.get("usage"))
        completion_tokens_per_second = (
            round(completion_tokens / (duration_ms / 1000), 2)
            if isinstance(completion_tokens, int) and completion_tokens >= 0
            else None
        )
        return {
            "provider_id": settings["provider_id"],
            "purpose": purpose,
            "model": settings["model"],
            "request_sha256": request_sha256,
            "response_sha256": response_hash,
            "completion_sha256": sha256_bytes(content.encode("utf-8")),
            "response_text": content,
            "finish_reason": finish_reason,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
            "performance": {
                "duration_ms": duration_ms,
                "duration_seconds": round(duration_ms / 1000, 3),
                "completion_tokens_per_second": completion_tokens_per_second,
            },
            "timings": {
                "schema": AI_PROVIDER_TIMING_SCHEMA,
                "phases_ms": {
                    "request_preparation": _elapsed_ms(request_preparation_started, request_prepared_at),
                    "provider_transport": duration_ms,
                    "response_body_parse": _elapsed_ms(response_parse_started, response_parse_finished),
                },
                "provider_reported": provider_reported_timings,
            },
            "value": parsed,
        }

    @staticmethod
    def _schema_failure_locators(
        schema: dict[str, Any] | None,
        parsed: Any,
        *,
        schema_name: str,
        schema_error: Any = None,
    ) -> dict[str, Any]:
        """Return bounded schema locators, never the offending answer text."""

        validator: Any = None
        instance_path: list[Any] = []
        schema_path: list[Any] = []
        try:
            if schema is not None:
                best = Draft202012Validator(schema).iter_errors(parsed)
                match = next(best, None)
                if match is not None:
                    validator = match.validator if isinstance(match.validator, str) else None
                    instance_path = list(match.absolute_path)[:12]
                    schema_path = list(match.absolute_schema_path)[:12]
        except Exception:
            validator, instance_path, schema_path = None, [], []
        if schema_error is not None:
            validator = schema_error.validator if isinstance(getattr(schema_error, "validator", None), str) else validator
            if not instance_path:
                instance_path = list(getattr(schema_error, "absolute_path", []))[:12]
            if not schema_path:
                schema_path = list(getattr(schema_error, "absolute_schema_path", []))[:12]
        return {
            "schema_name": schema_name,
            "validator": validator,
            "instance_path": [str(part)[:80] for part in instance_path],
            "schema_path": [str(part)[:80] for part in schema_path],
        }

    @classmethod
    def _agent_schema_errors(cls, schema: dict[str, Any] | None, parsed: Any) -> list[dict[str, Any]]:
        """Validate one agent answer through the exact provider answer gate."""

        if schema is None:
            return []
        errors: list[dict[str, Any]] = []
        try:
            validator = Draft202012Validator(schema)
            for error in validator.iter_errors(parsed):
                errors.append(
                    {
                        "validator": error.validator if isinstance(error.validator, str) else None,
                        "message": str(error.message)[:400],
                        "instance_path": [str(part)[:80] for part in list(error.absolute_path)[:12]],
                        "schema_path": [str(part)[:80] for part in list(error.absolute_schema_path)[:12]],
                    }
                )
                if len(errors) >= 20:
                    break
        except SchemaError as exc:
            raise FoundryError(
                "AI_PROVIDER_RESPONSE_SCHEMA_INVALID",
                "The stored agent request schema is not a valid JSON Schema.",
                details={"reason": str(exc)[:400]},
                status_code=500,
            ) from exc
        return errors

    @staticmethod
    def _agent_model_label(agent_id: str, agent_model: str) -> str:
        """One bounded identity label naming the agent and its reported model."""

        label = f"agent:{agent_id}:{agent_model}"
        return label if len(label) <= 100 else label[:100]

    def _insert_json_run(
        self,
        *,
        prompt_id: str,
        idempotency_key: str,
        settings: dict[str, Any],
        request_bytes: bytes,
        started_at: str,
        project_id: str | None = None,
    ) -> str:
        """Insert the pending ``ai_provider_runs`` row for one JSON request.

        Factory authoring steps are not Stage 1 prompts, so their step identity
        lives in the additive ``call_key`` column and ``prompt_id`` stays NULL
        instead of pointing at an unrelated Stage 1 prompt exchange.
        """

        run_id = "ai.run." + uuid.uuid4().hex
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """INSERT INTO ai_provider_runs(
                       run_id,provider_id,project_id,prompt_id,idempotency_key,prompt_sha256,
                       model,endpoint,request_bytes,request_sha256,started_at,status,call_key)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        run_id,
                        settings["provider_id"],
                        _project_reference(project_id),
                        None,
                        idempotency_key,
                        sha256_bytes(request_bytes),
                        settings["model"],
                        settings["endpoint"],
                        request_bytes,
                        sha256_bytes(request_bytes),
                        started_at,
                        "started",
                        f"{settings['provider_id']}:{prompt_id}:{idempotency_key}",
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise FoundryError(
                "AI_PROVIDER_IDEMPOTENCY_CONFLICT",
                "That provider request key is already bound to another run.",
            ) from exc
        return run_id

    def _complete_json_via_agent(
        self,
        *,
        purpose: str,
        prompt: str,
        profile: dict[str, Any],
        settings: dict[str, Any],
        response_schema_name: str,
        schema_copy: dict[str, Any] | None,
        request_payload: dict[str, Any],
        request_bytes: bytes,
        request_sha256: str,
        max_output_tokens: int,
        request_preparation_started: float,
        request_prepared_at: float,
        project_id: str | None = None,
        caller_key: str | None = None,
    ) -> dict[str, Any]:
        """Hand one request to the agent mailbox and wait for its validated answer.

        The mailbox/run key is the caller's explicit step key when one is
        supplied, and only falls back to the request fingerprint otherwise.
        Two distinct creation runs whose prompts happen to be byte-identical
        therefore still own separate runs and separate mailbox rows.
        """

        idempotency_key = str(caller_key or "").strip() or ("fpr." + request_sha256)
        wait_seconds = self.agent_wait_override if self.agent_wait_override is not None else _agent_wait_seconds(settings.get("agent_wait_seconds"))
        started_at = utcnow()
        try:
            run_id = self._insert_json_run(
                prompt_id=purpose,
                idempotency_key=idempotency_key,
                settings=settings,
                request_bytes=request_bytes,
                started_at=started_at,
                project_id=project_id,
            )
        except FoundryError as exc:
            if exc.code != "AI_PROVIDER_IDEMPOTENCY_CONFLICT":
                raise
            # A concurrent or earlier re-drive already recorded this exact
            # step.  Continue on that recorded run instead of prompting twice.
            existing = self._existing_idempotent_run(
                purpose,
                idempotency_key,
                provider_id=AGENT_PROVIDER_ID,
            )
            if existing is None:
                raise
            return self._resume_existing_run(
                existing,
                purpose=purpose,
                idempotency_key=idempotency_key,
                project_id=project_id,
            )
        request = self.agent_bridge.enqueue(
            request_payload=request_payload,
            purpose=purpose,
            schema_name=response_schema_name,
            run_id=run_id,
            provider_id=AGENT_PROVIDER_ID,
            project_id=str(project_id or ""),
            prompt_id=purpose,
            idempotency_key=idempotency_key,
        )
        request_id = request["request_id"]
        # The stored request is the authority for the effective completion
        # budget, so the answer ceiling always matches the agent's own request.
        requested_max = request.get("max_output_tokens")
        if type(requested_max) is int and requested_max > 0:
            max_output_tokens = requested_max
        wait_started = time.perf_counter()
        answered = self.agent_bridge.wait_for_answer(
            request_id,
            wait_seconds=wait_seconds,
            poll_interval=self.agent_poll_interval,
        )
        if answered is None:
            # Not an error: the request stays pending and the same step can be
            # re-driven with the same request bytes once an agent answers.
            raise FoundryError(
                "AI_AGENT_AWAITING_RESPONSE",
                f"The Agent bridge is still waiting for an agent answer ({wait_seconds}s elapsed); re-drive this step to collect it.",
                details={
                    "request_id": request_id,
                    "run_id": run_id,
                    "prompt_id": purpose,
                    "idempotency_key": idempotency_key,
                    "wait_seconds": wait_seconds,
                    "state": "PENDING",
                },
                status_code=409,
            )
        return self._complete_answered_request(
            request=answered,
            run_id=run_id,
            request_sha256=request_sha256,
            request_payload=request_payload,
            response_schema_name=response_schema_name,
            schema_copy=schema_copy,
            purpose=purpose,
            profile=profile,
            settings=settings,
            wait_started=wait_started,
            request_preparation_started=request_preparation_started,
            request_prepared_at=request_prepared_at,
            max_output_tokens=max_output_tokens,
        )

    def _complete_answered_request(
        self,
        *,
        request: dict[str, Any],
        run_id: str,
        request_sha256: str,
        request_payload: dict[str, Any],
        response_schema_name: str,
        schema_copy: dict[str, Any] | None,
        purpose: str,
        profile: dict[str, Any],
        settings: dict[str, Any],
        wait_started: float,
        request_preparation_started: float,
        request_prepared_at: float,
        max_output_tokens: int,
    ) -> dict[str, Any]:
        """Consume one answered request and finish its run like a provider success."""

        request_id = request["request_id"]
        agent_id = str(request.get("agent_id") or "")
        agent_model = str(request.get("agent_model") or "")
        content = request.get("response_text")
        if not isinstance(content, str) or not content.strip():
            raise FoundryError(
                "AI_AGENT_RESPONSE_EMPTY",
                "The stored agent answer has no response_text.",
                details={"request_id": request_id},
                status_code=422,
            )
        parsed = request.get("value")
        if not isinstance(parsed, dict):
            try:
                parsed = json.loads(content)
            except (TypeError, ValueError) as exc:
                raise FoundryError(
                    "AI_PROVIDER_RESPONSE_CONTRACT_INVALID",
                    "The stored agent answer is not one JSON object.",
                    details={"request_id": request_id, "purpose": purpose},
                    status_code=502,
                ) from exc
        schema_errors = self._agent_schema_errors(schema_copy, parsed)
        if schema_errors:
            raise FoundryError(
                "AI_PROVIDER_RESPONSE_CONTRACT_INVALID",
                "The stored agent answer failed the requested response schema.",
                details={
                    "request_id": request_id,
                    "purpose": purpose,
                    "errors": schema_errors,
                    **self._schema_failure_locators(schema_copy, parsed, schema_name=response_schema_name),
                },
                status_code=502,
            )
        content_bytes = content.encode("utf-8")
        if len(content_bytes) > MAX_PROVIDER_RESPONSE_BYTES:
            raise FoundryError(
                "AI_PROVIDER_RESPONSE_TOO_LARGE",
                "The agent answer exceeded the 4 MiB audit limit.",
                details={"request_id": request_id},
            )
        self.agent_bridge.consume(request_id, run_id=run_id)
        now = utcnow()
        provider_value = {
            "id": "agent-bridge:" + request_id,
            "model": self._agent_model_label(agent_id, agent_model),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "agent_bridge": {
                "request_id": request_id,
                "agent_id": agent_id,
                "agent_model": agent_model,
                "answered_at": request.get("answered_at"),
            },
        }
        response_bytes = canonical_json(provider_value).encode("utf-8")
        response_hash = sha256_bytes(response_bytes)
        completion_hash = sha256_bytes(content_bytes)
        duration_ms = max(1, round((time.perf_counter() - wait_started) * 1000))
        model_label = self._agent_model_label(agent_id, agent_model)
        self._update_run(
            run_id,
            completed_at=now,
            status="validated",
            http_status=200,
            # Job 1 A5: the audit row names the agent and the model that
            # actually answered, exactly as the returned receipt does.
            model=model_label,
            provider_response_bytes=response_bytes,
            provider_response_sha256=response_hash,
            provider_response_bytes_count=len(response_bytes),
            completion_content_sha256=completion_hash,
            finish_reason="stop",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            error_code=None,
            error_message=None,
        )
        response_parse_finished = time.perf_counter()
        return {
            "provider_id": AGENT_PROVIDER_ID,
            "purpose": purpose,
            "model": model_label,
            "run_id": run_id,
            "request_sha256": request_sha256,
            "response_sha256": response_hash,
            "completion_sha256": completion_hash,
            "response_text": content,
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "performance": {
                "duration_ms": duration_ms,
                "duration_seconds": round(duration_ms / 1000, 3),
                "completion_tokens_per_second": None,
            },
            "timings": {
                "schema": AI_PROVIDER_TIMING_SCHEMA,
                "phases_ms": {
                    "request_preparation": _elapsed_ms(request_preparation_started, request_prepared_at),
                    "agent_wait": duration_ms,
                    "response_body_parse": _elapsed_ms(wait_started, response_parse_finished),
                },
                "provider_reported": {},
            },
            "agent_bridge": {
                "request_id": request_id,
                "agent_id": agent_id,
                "agent_model": agent_model,
                "state": "CONSUMED",
                "model_label": model_label,
                "max_output_tokens": max_output_tokens,
                "secret_present": False,
                "network_request_made": False,
            },
            "value": parsed,
        }

    def _resume_existing_run(
        self,
        existing: dict[str, Any],
        *,
        purpose: str,
        idempotency_key: str,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Finish or replay one step that already has a recorded run.

        A run with a terminal outcome is replayed from its recorded receipt and
        never prompts again.  A run whose agent answer already landed is
        consumed and completed now, which is exactly the re-drive contract for
        every caller family.
        """

        run_id = str(existing.get("run_id") or "")
        if str(existing.get("status") or "") in {"validated", "response_rejected", "provider_error"}:
            return existing
        latest = self.agent_bridge.find_latest(
            provider_id=AGENT_PROVIDER_ID,
            prompt_id=purpose,
            idempotency_key=idempotency_key,
        )
        if latest is None:
            return existing
        if latest.get("state") == AGENT_STATE_REJECTED:
            # A declined step stays declined: the waiting caller receives the
            # agent's own reason instead of a silent re-prompt.
            rejection = latest.get("rejection") if isinstance(latest.get("rejection"), dict) else {}
            reason = rejection.get("reason")
            raise FoundryError(
                "AI_AGENT_REQUEST_REJECTED",
                f"The agent declined this step: {reason}" if reason else "The agent declined this step.",
                details={
                    "request_id": latest.get("request_id"),
                    "run_id": existing.get("run_id"),
                    "agent_id": rejection.get("agent_id"),
                    "reason": reason,
                },
                status_code=409,
            )
        if latest.get("state") not in {AGENT_STATE_ANSWERED, *AGENT_OPEN_STATES}:
            return existing
        settings = self._settings()
        profile = provider_profile(settings["provider_id"])
        settled = self.agent_bridge.wait_for_answer(
            latest["request_id"],
            wait_seconds=(
                self.agent_wait_override
                if self.agent_wait_override is not None
                else _agent_wait_seconds(settings.get("agent_wait_seconds"))
            ),
            poll_interval=self.agent_poll_interval,
        )
        if settled is None:
            raise FoundryError(
                "AI_AGENT_AWAITING_RESPONSE",
                "The Agent bridge is still waiting for an agent answer; re-drive this step to collect it.",
                details={
                    "request_id": latest["request_id"],
                    "run_id": run_id,
                    "prompt_id": purpose,
                    "idempotency_key": idempotency_key,
                    "state": latest["state"],
                },
                status_code=409,
            )
        request_payload = latest.get("request_json") if isinstance(latest.get("request_json"), dict) else {}
        schema_copy = latest.get("schema") if isinstance(latest.get("schema"), dict) else None
        request_prepared_at = time.perf_counter()
        return self._complete_answered_request(
            request=settled,
            run_id=run_id,
            request_sha256=str(existing.get("request_sha256") or latest["request_sha256"]),
            request_payload=request_payload,
            response_schema_name=latest.get("schema_name") or "",
            schema_copy=schema_copy,
            purpose=purpose,
            profile=profile,
            settings=settings,
            wait_started=request_prepared_at,
            request_preparation_started=request_prepared_at,
            request_prepared_at=request_prepared_at,
            max_output_tokens=int(request_payload.get("max_tokens") or AGENT_DEFAULT_MAX_OUTPUT_TOKENS),
        )

    def build_debrief(
        self,
        *,
        prompt_text: str,
        system_message: str | None = None,
    ) -> dict[str, Any]:
        """Request an optional structured, non-authoritative build debrief.

        This is deliberately an explicit caller action; no build path invokes
        it automatically.  ``complete_json`` remains the single transport
        call and enforces visible ``message.content`` plus the bounded schema.
        In particular, a provider's ``reasoning_content`` can never stand in
        for the visible answer.
        """
        if not isinstance(prompt_text, str) or not prompt_text.strip():
            raise FoundryError(
                "AI_PROVIDER_DEBRIEF_PROMPT_INVALID",
                "A non-empty debrief prompt is required.",
            )
        if len(prompt_text.encode("utf-8")) > 64 * 1024:
            raise FoundryError(
                "AI_PROVIDER_DEBRIEF_PROMPT_INVALID",
                "The debrief prompt exceeded the bounded size limit.",
                details={"max_bytes": 64 * 1024},
            )
        return self.complete_json(
            prompt_text=prompt_text,
            system_message=system_message
            or (
                "Return exactly one visible JSON object following the supplied debrief schema. "
                "Keep feedback concise, descriptive, and non-authoritative. Do not place the answer in reasoning_content."
            ),
            purpose="build_debrief",
            substantive=True,
            response_schema=deepcopy(BUILD_DEBRIEF_RESPONSE_SCHEMA),
            response_schema_name=BUILD_DEBRIEF_SCHEMA_NAME,
            response_schema_max_output_tokens=BUILD_DEBRIEF_SCHEMA_MAX_OUTPUT_TOKENS,
        )

    # Keep a descriptive alias for callers that name explicit provider
    # completion actions rather than the resulting debrief artifact.
    def complete_build_debrief(self, **kwargs: Any) -> dict[str, Any]:
        return self.build_debrief(**kwargs)

    def _existing_idempotent_run(
        self,
        prompt_id: str,
        idempotency_key: str,
        *,
        provider_id: str | None = None,
    ) -> dict[str, Any] | None:
        provider = provider_id or self._selected_provider_id()
        with self.db.connection() as conn:
            row = conn.execute(
                """SELECT run_id FROM ai_provider_runs
                   WHERE provider_id=? AND prompt_id=? AND idempotency_key=?""",
                (provider, prompt_id, idempotency_key),
            ).fetchone()
            if row is None:
                # Factory authoring steps record their identity in ``call_key``
                # because they are not Stage 1 prompts.
                row = conn.execute(
                    "SELECT run_id FROM ai_provider_runs WHERE call_key=?",
                    (f"{provider}:{prompt_id}:{idempotency_key}",),
                ).fetchone()
        if row is None:
            return None
        result = self.get_run(row["run_id"])
        result["idempotent"] = True
        return result

    def _require_same_request_bytes(
        self,
        existing: dict[str, Any],
        *,
        prompt_id: str,
        idempotency_key: str,
        request_sha256: str,
    ) -> None:
        """Refuse to reuse a receipt whose exact request bytes changed."""

        if existing.get("request_sha256") == request_sha256:
            return
        raise FoundryError(
            "AI_PROVIDER_REQUEST_CHANGED",
            "The saved provider settings produced different request bytes for an already-recorded step; no request was made.",
            details={
                "run_id": existing.get("run_id"),
                "prompt_id": prompt_id,
                "idempotency_key": idempotency_key,
                "recorded_request_sha256": existing.get("request_sha256"),
                "actual_request_sha256": request_sha256,
                "provider_called": False,
            },
            status_code=409,
        )

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
        is_local = settings["provider_id"] in LOCAL_PROVIDER_IDS
        if not settings["enabled"]:
            raise FoundryError("AI_PROVIDER_DISABLED", "The optional API Provider is disabled.")
        if not is_local and not settings["data_sharing_acknowledged"]:
            raise FoundryError(
                "AI_PROVIDER_DATA_SHARING_ACKNOWLEDGEMENT_REQUIRED",
                "Prompt transmission has not been acknowledged by a named user.",
            )
        key = self.local_runtime.managed.auth_key if settings["provider_id"] == "lemonade" else None if is_local else self.secrets.get(settings["provider_id"])
        if not is_local and key is None:
            raise FoundryError("AI_PROVIDER_API_KEY_MISSING", "No API Provider key is available.")
        if is_local and (not settings.get("endpoint") or not settings.get("model")):
            raise FoundryError("LOCAL_AI_NOT_SELECTED", "Select a detected local model or prepare built-in Local AI before building.")
        if settings["provider_id"] == "lemonade" and not key:
            raise FoundryError("LOCAL_AI_NOT_READY", "Built-in Local AI is still preparing; wait for the ready status before building.")
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
                timeout_seconds=_provider_timeout_seconds(settings, substantive=True),
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
