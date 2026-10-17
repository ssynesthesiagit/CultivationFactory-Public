"""Owner-controlled provider registry and bounded prompt-on-stdin transports.

Only environment variable names belong in the registry. CLI commands are argv
arrays, never shell commands; account/OAuth authentication stays with the CLI.
The runner's deadline also bounds an injected provider that ignores its timeout.
"""
from __future__ import annotations

import base64
import json
import math
import os
from pathlib import Path
import re
import subprocess
import urllib.parse
import urllib.request


def choices_settings(provider):
    """Bound per-provider shortlist size, including injected registry rows."""
    budget = provider.get("choices_bytes", 800)
    maximum = provider.get("max_options", 6)
    if type(budget) is not int or not 800 <= budget <= 4800:
        raise ValueError("choices_bytes must be an integer from 800 to 4800.")
    if type(maximum) is not int or not 3 <= maximum <= 12:
        raise ValueError("max_options must be an integer from 3 to 12.")
    return budget, maximum


def request_options(value):
    """Validate the small, credential-free HTTP tuning contract at both boundaries."""
    if not isinstance(value, dict) or set(value) - {
        "reasoning_budget", "chat_template_kwargs", "temperature", "max_tokens", "cache_prompt"
    }:
        raise ValueError("Unsupported request_options settings.")
    for key, option in value.items():
        if key == "chat_template_kwargs":
            if (not isinstance(option, dict) or set(option) - {"enable_thinking"}
                    or any(not isinstance(v, bool) for v in option.values())):
                raise ValueError("chat_template_kwargs only accepts boolean enable_thinking.")
        elif key == "cache_prompt":
            if not isinstance(option, bool):
                raise ValueError("cache_prompt must be boolean.")
        elif key == "temperature":
            if isinstance(option, bool) or not isinstance(option, (int, float)) or not math.isfinite(option) or not 0 <= option <= 2:
                raise ValueError("temperature must be finite and between 0 and 2.")
        elif isinstance(option, bool) or not isinstance(option, int) or not (0 if key == "reasoning_budget" else 1) <= option <= 32768:
            raise ValueError("Token budgets must be bounded integers.")
    return value


class ProviderRegistry:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get("FACTORY_SEAT_PROVIDERS") or Path(__file__).with_name("providers.json"))

    def load(self):
        # A configured path that does not exist means "no models set up", never a server error.
        if not self.path.exists():
            return {}
        rows = json.loads(self.path.read_text(encoding="utf-8"))["providers"]
        result = {}
        for row in rows:
            allowed = {"id", "label", "kind", "base_url", "model", "key_env", "command", "timeout_s", "vision", "max_plan_length", "prompt_profile", "request_options", "choices_bytes", "max_options", "protocol"}
            if not isinstance(row, dict) or set(row) - allowed:
                raise ValueError("Provider entries may contain settings and key_env, never API keys.")
            pid = row.get("id")
            if not isinstance(pid, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", pid) or pid in result:
                raise ValueError("Each provider needs a unique id.")
            if row.get("kind") not in {"openai_compatible", "local", "cli", "d1"}:
                raise ValueError("Choose a supported provider kind.")
            if "label" in row and not isinstance(row["label"], str):
                raise ValueError("Provider label must be text.")
            if "vision" in row and not isinstance(row["vision"], bool):
                raise ValueError("Provider vision must be true or false.")
            if row.get("key_env") and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", row["key_env"]):
                raise ValueError("key_env must name an environment variable.")
            timeout = row.get("timeout_s", 15)
            limit = row.get("max_plan_length", 32)
            profile = row.get("prompt_profile", "choices" if row["kind"] == "d1" else "full")
            if row["kind"] == "d1" and (profile != "choices" or row.get("vision") or "request_options" in row):
                raise ValueError("d1 requires text-only choices without chat request_options.")
            if "protocol" in row and (row["kind"] != "d1" or row["protocol"] != "local-app"):
                raise ValueError("protocol is only for d1 and must be local-app.")
            if not isinstance(profile, str) or profile not in {"full", "compact", "tiny", "choices"}:
                raise ValueError("prompt_profile must be full, compact, tiny or choices.")
            options = request_options(row.get("request_options", {}))
            budget, maximum = choices_settings(row)
            if row["kind"] == "cli" and "request_options" in row:
                raise ValueError("request_options requires an HTTP provider.")
            if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 32:
                raise ValueError("max_plan_length must be an integer from 1 to 32.")
            cap = 180 if row["kind"] == "local" else 60
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= cap:
                raise ValueError(f"Provider timeout must be greater than zero and at most {cap} seconds.")
            if row["kind"] == "cli":
                argv = row.get("command")
                if not isinstance(argv, list) or not argv or not all(isinstance(s, str) and s for s in argv):
                    raise ValueError("CLI command must be a nonempty argv array reading stdin.")
                if any(arg.split("=", 1)[0] in {"--api-key", "--token", "--access-token", "--password"} for arg in argv):
                    raise ValueError("CLI credentials must come from its account configuration or environment.")
            else:
                url = urllib.parse.urlsplit(row.get("base_url", ""))
                if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
                    raise ValueError("Provider base_url must be an HTTP URL without credentials or query parameters.")
                if row["kind"] != "d1" and (not isinstance(row.get("model"), str) or not row["model"]):
                    raise ValueError("HTTP providers need a model name.")
            result[pid] = dict(row, timeout_s=timeout, prompt_profile=profile, request_options=options,
                               choices_bytes=budget, max_options=maximum)
        return result

    def public(self):
        # prompt_profile lets the seat picker pre-select the provider's own play style.
        return [{k: row[k] for k in ("id", "label", "kind", "model", "vision", "prompt_profile") if k in row}
                for row in self.load().values()]


def complete(provider, prompt, png=None):
    """Return (JSON text, usage); never include credentials in errors or logs."""
    timeout = provider["timeout_s"]
    if provider["kind"] == "d1":
        from .d1 import decide
        return decide(provider, prompt)
    if provider["kind"] == "cli":
        try:
            result = subprocess.run(provider["command"], input=prompt, text=True,
                                    capture_output=True, timeout=timeout, check=True)
        except subprocess.TimeoutExpired:
            raise TimeoutError("Model CLI deadline exceeded") from None
        return result.stdout, None
    content = prompt
    if png is not None and provider.get("vision"):
        content = [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {
            "url": "data:image/png;base64," + base64.b64encode(png).decode("ascii")}}]
    headers = {"Content-Type": "application/json"}
    key_env = provider.get("key_env")
    if key_env:
        key = os.environ.get(key_env)
        if not key:
            raise ValueError("Provider credential is unavailable.")
        headers["Authorization"] = "Bearer " + key
    body = {"model": provider["model"], "messages": [{"role": "user", "content": content}], "temperature": 0.2}
    if provider["kind"] == "local":
        body["cache_prompt"] = True
    body.update(request_options(provider.get("request_options", {})))
    request = urllib.request.Request(provider["base_url"].rstrip("/") + "/chat/completions",
                                     data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("Provider reply is too large.")
    reply = json.loads(raw)
    return reply["choices"][0]["message"]["content"], reply.get("usage")
