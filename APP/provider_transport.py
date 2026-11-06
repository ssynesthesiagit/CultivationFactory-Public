"""Bounded response transport shared by creation AI and combat-seat providers.

HTTP clients stay with their callers: creation's injected httpx client forbids
redirects/proxy environment; seats retain urllib's owner-configured egress.
The shared interface consumes injectable byte chunks, accepts each caller's
limit/error, and neither retries nor interprets completion/usage envelopes.
Only the two seat protocols share the urllib JSON adapter.
"""
from collections.abc import Iterable
import json
import urllib.request


def bounded_response(chunks: Iterable[bytes], *, limit: int, too_large: Exception) -> bytes:
    """Collect at most limit bytes; stop on the first overflowing chunk."""
    parts = []
    total = 0
    for chunk in chunks:
        total += len(chunk)
        if total > limit:
            raise too_large
        parts.append(chunk)
    return b"".join(parts)


def urllib_json(request, timeout, *, too_large: str):
    """Read one seat reply, preserving urllib errors, egress and close timing."""
    limit = 1024 * 1024
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(limit + 1)
    return json.loads(bounded_response((raw,), limit=limit, too_large=ValueError(too_large)))
