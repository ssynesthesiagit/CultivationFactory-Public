"""Embedding fit for combat menu options, with an optional tactical-tier seam.

Who uses it: combat/menu_rank.py's presentation layer and the opt-in host
timing tool in APP/tools/embedding_rank_timing.py.

Inputs are only the texts the caller built from the acting seat's perceived
state and public menu descriptions. This module never reads engine state, so
hidden enemies, locations or actions cannot reach the query, cache keys,
network payload or logs.

Ordering contract: a tactical provider's integer tier always decides first
(higher tier first). Embedding similarity only orders options inside one tier.
With no provider, every option has tier 0 and similarity alone orders them.
Ties keep the original menu order. Any service error, timeout or invalid
response returns the original order unchanged.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import threading
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

ENDPOINT = "http://127.0.0.1:11448/v1/embeddings"
MODEL = "embeddinggemma-2"
DIMENSION = 768
PREFIX = "task: sentence similarity | query: {text}"
DEADLINE_S = 0.3
CACHE_LIMIT = 4096
NAMESPACE = f"{MODEL}|{PREFIX}|{DIMENSION}|v1"

Transport = Callable[[str, bytes, float], bytes]


class EmbeddingError(RuntimeError):
    """The service could not give valid vectors for the requested texts."""


def cpu_server_pid(proc_root: Path = Path("/proc")) -> int | None:
    """Prove the fixed local listener uses llama-server with GPU offload disabled.

    Shared by production's request guard and the opt-in timing tool. Missing
    process visibility is a tier-only fallback, never permission to use a GPU.
    """
    try:
        inodes = set()
        for filename in ("net/tcp", "net/tcp6"):
            for line in (proc_root / filename).read_text().splitlines()[1:]:
                fields = line.split()
                if fields[1].endswith(":2CB8") and fields[3] == "0A":
                    inodes.add(fields[9])
        sockets = {f"socket:[{inode}]" for inode in inodes}
        for process in proc_root.iterdir():
            if not process.name.isdigit():
                continue
            try:
                args = (process / "cmdline").read_bytes().decode().strip("\0").split("\0")
                if not args or "llama-server" not in Path(args[0]).name:
                    continue
                def value(*flags):
                    return next((args[i + 1] for i, arg in enumerate(args[:-1]) if arg in flags), None)
                zero = value("-ngl", "--n-gpu-layers", "--gpu-layers") == "0" or any(
                    arg in ("--n-gpu-layers=0", "--gpu-layers=0") for arg in args)
                no_device = value("--device", "-dev") == "none" or "--device=none" in args
                no_ops = "--no-op-offload" in args
                if zero and (no_device or no_ops) and any(
                        fd.readlink().as_posix() in sockets for fd in (process / "fd").iterdir()):
                    return int(process.name)
            except (OSError, UnicodeError):
                continue
    except (OSError, IndexError):
        pass
    return None


def _post(url: str, body: bytes, timeout: float) -> bytes:
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        return reply.read()


class BoundedTransport:
    """Wall-clock wait bound with at most one outstanding HTTP request.

    urllib's socket timeout alone is per operation, so a trickling response
    can outlast a menu. An isolated daemon request may finish after fallback,
    but no second request is started until it finishes; no retry loop exists.
    Used by the shared production menu client, never by test fake embedders.
    """
    def __init__(self, transport=_post):
        self.transport = transport
        self._inflight = threading.Lock()

    def __call__(self, url: str, body: bytes, timeout: float) -> bytes:
        if not self._inflight.acquire(blocking=False):
            raise EmbeddingError("embedding request still in flight")
        completed = threading.Event()
        result = []
        def request():
            try:
                result.append(self.transport(url, body, timeout))
            except Exception as error:
                result.append(error)
            finally:
                self._inflight.release()
                completed.set()
        try:
            threading.Thread(target=request, name="menu-embedding-request", daemon=True).start()
        except Exception:
            self._inflight.release()
            raise
        if not completed.wait(max(0, timeout)):
            raise EmbeddingError("menu request budget reached")
        if isinstance(result[0], Exception):
            raise result[0]
        return result[0]


def _key(text: str) -> str:
    return hashlib.sha256(f"{NAMESPACE}\n{text}".encode("utf-8")).hexdigest()


def validate_response(texts: Sequence[str], payload: bytes) -> list[list[float]]:
    """Map each vector back to its requested text by index; reject anything malformed."""
    try:
        data = json.loads(payload)["data"]
    except (ValueError, KeyError, TypeError) as error:
        raise EmbeddingError("response is not an embeddings payload") from error
    if not isinstance(data, list) or len(data) != len(texts):
        raise EmbeddingError("response count does not match the request")
    vectors: list[list[float] | None] = [None] * len(texts)
    for item in data:
        try:
            index = item["index"]
            vector = item["embedding"]
        except (KeyError, TypeError) as error:
            raise EmbeddingError("response item lacks index or embedding") from error
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(texts):
            raise EmbeddingError("response index is out of range")
        if vectors[index] is not None:
            raise EmbeddingError("response index is repeated")
        if not isinstance(vector, list) or len(vector) != DIMENSION:
            raise EmbeddingError("vector has the wrong dimension")
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in vector):
            raise EmbeddingError("vector has a non-finite number")
        norm = math.sqrt(sum(float(x) * float(x) for x in vector))
        if not math.isfinite(norm) or norm == 0.0:
            raise EmbeddingError("vector has zero norm")
        vectors[index] = [float(x) for x in vector]
    return vectors  # type: ignore[return-value]


@dataclass
class EmbeddingClient:
    """Cached, deadline-bounded client. Vectors are kept in memory only, by text key."""

    endpoint: str = ENDPOINT
    deadline_s: float = DEADLINE_S
    transport: Transport = _post
    cache_limit: int = CACHE_LIMIT
    clock: Callable[[], float] = time.monotonic
    before_request: Callable[[], bool] | None = None
    request_result: Callable[[bool], None] | None = None
    background: bool = False

    def __post_init__(self) -> None:
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.Lock()
        self._seconds_per_input = 0.158 / 6
        self._pending_lock = threading.Lock()
        self._pending = None

    def acceptance_budget(self, count: int) -> float:
        """CPU batch allowance, independent of the blocking turn budget.

        Starts from the owner's measured six-input CPU latency with headroom;
        successful batches adapt the estimate. Hard cap bounds socket allowance.
        """
        return min(3.0, max(self.deadline_s, 0.3, count * self._seconds_per_input * 2))

    def prefetch(self, texts: Sequence[str], *, deferred=False) -> None:
        """Warm perceived texts off the caller's path; at most one worker.

        A busy client retains at most one deferred next-actor batch.
        Actual transport/validation outcomes alone update the circuit breaker.
        """
        if not self._lock.acquire(blocking=False):
            if deferred:
                with self._pending_lock:
                    self._pending = tuple(texts)
            return
        def complete():
            try:
                if deferred:
                    time.sleep(0.2)
                batch = tuple(texts)
                while batch is not None:
                    try:
                        self._embed(batch, background=True)
                    except Exception:
                        pass  # native ranking remains available
                    with self._pending_lock:
                        batch, self._pending = self._pending, None
                    # Worker-only spacing: speculative warming cannot consume
                    # another start inside the five-per-second rate window.
                    if batch is not None:
                        time.sleep(0.2)
            finally:
                self._lock.release()
        try:
            threading.Thread(target=complete, name="menu-embedding-cache", daemon=True).start()
        except Exception:
            self._lock.release()
            raise

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Vectors for texts, in order. Only cache misses use the network, in one batch."""
        if self.background:
            if self._lock.acquire(blocking=False):
                try:
                    keys = [_key(PREFIX.format(text=text)) for text in texts]
                    if all(key in self._cache for key in keys):
                        return [self._cache[key] for key in keys]
                finally:
                    self._lock.release()
            self.prefetch(texts)
            raise EmbeddingError("cache warming in background")
        # Concurrent menus fall back rather than wait for another menu's budget.
        if not self._lock.acquire(blocking=False):
            raise EmbeddingError("embedding client busy")
        try:
            return self._embed(texts)
        finally:
            self._lock.release()

    def _embed(self, texts: Sequence[str], *, background=False) -> list[list[float]]:
        started = self.clock()
        budget = self.acceptance_budget(len(texts)) if background else self.deadline_s
        prefixed = [PREFIX.format(text=text) for text in texts]
        keys = [_key(text) for text in prefixed]
        resolved = {key: self._cache[key] for key in keys if key in self._cache}
        missing = list(dict.fromkeys(text for text, key in zip(prefixed, keys) if key not in resolved))
        if missing:
            remaining = budget - (self.clock() - started)
            if remaining <= 0:
                raise EmbeddingError("deadline reached before the request")
            body = json.dumps({"model": MODEL, "input": missing}).encode("utf-8")
            if self.before_request is not None and not self.before_request():
                raise EmbeddingError("request rate limited or circuit open")
            remaining = budget - (self.clock() - started)
            if remaining <= 0:
                raise EmbeddingError("deadline reached while checking request safety")
            try:
                payload = self.transport(self.endpoint, body, remaining)
                vectors = validate_response(missing, payload)
                if not background and self.clock() - started > self.deadline_s:
                    raise EmbeddingError("deadline exceeded")
            except Exception as error:
                if self.request_result is not None:
                    self.request_result(False)
                raise EmbeddingError("embedding service unavailable") from error
            if self.request_result is not None:
                self.request_result(True)
            if background:
                measured = (self.clock() - started) / len(missing)
                self._seconds_per_input = max(0.001, self._seconds_per_input * 0.5 + measured * 0.5)
            resolved.update((_key(text), vector) for text, vector in zip(missing, vectors))
        for key in keys:
            self._cache[key] = resolved[key]
            self._cache.move_to_end(key)
        while len(self._cache) > max(0, self.cache_limit):
            self._cache.popitem(last=False)
        return [resolved[key] for key in keys]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb)


TacticalProvider = Callable[[Sequence[tuple[str, str]]], Mapping[str, int]]


def rank_options(
    query_text: str,
    options: Sequence[tuple[str, str]],
    *,
    client: EmbeddingClient,
    tactical_provider: TacticalProvider | None = None,
) -> list[str]:
    """Option ids in display order. options are (option_id, perceived_text) in menu order.

    tactical_provider(options) -> {option_id: int tier}; higher tier ranks first.
    Missing ids get tier 0. Returns the original order on any failure.
    """
    original = [option_id for option_id, _ in options]
    if len(options) < 2:
        return original
    try:
        tiers = dict(tactical_provider(options)) if tactical_provider is not None else {}
        vectors = client.embed([query_text, *(text for _, text in options)])
    except EmbeddingError:
        return original
    query, option_vectors = vectors[0], vectors[1:]
    scored = []
    for position, ((option_id, _), vector) in enumerate(zip(options, option_vectors)):
        tier = int(tiers.get(option_id, 0))
        similarity = round(cosine(query, vector), 9)
        scored.append((-tier, -similarity, position, option_id))
    return [option_id for *_, option_id in sorted(scored)]
