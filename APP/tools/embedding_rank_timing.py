"""HOST opt-in timing for embedding menu ranking. Not run by pytest; no model launch.

Usage (on the host, service already running):
  python APP/tools/embedding_rank_timing.py --allow-live [--runs N]
Prints cold/warm cache and failure timings for safe fixture menus. It never
starts or restarts the embedding service and sends only fixture text.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from combat import embedding_rank as er  # noqa: E402

FIXTURE_QUERY = "a fighter stands at the edge of a cliff with an enemy close by"
FIXTURE_MENU = [
    ("opt-1", "strike the nearby enemy with a sword"),
    ("opt-2", "raise a shield and brace"),
    ("opt-3", "climb down the cliff face"),
    ("opt-4", "step back one square"),
    ("opt-5", "call out to an ally"),
]


class CappedTransport:
    """Opt-in timing only: <=200 requests, <=5 starts/s, first failure stops traffic."""
    def __init__(self, cap):
        self.cap = min(cap, 200)
        self.requests = self.successes = 0
        self.last = None
        self.failed = False

    def wait_slot(self):
        if self.last is not None:
            time.sleep(max(0, 0.2 - (time.monotonic() - self.last)))

    def __call__(self, url, body, timeout):
        if self.failed or self.requests >= self.cap:
            raise er.EmbeddingError('measurement cap reached or circuit open')
        self.wait_slot()
        self.last = time.monotonic()
        self.requests += 1
        try:
            payload = er._post(url, body, min(timeout, 0.15))
            er.validate_response(json.loads(body)['input'], payload)
            self.successes += 1
            return payload
        except Exception:
            self.failed = True
            raise


def _timed(label, fn, runs, before=None):
    samples = []
    for _ in range(runs):
        if before is not None:
            before()  # rate-gate wait is outside the menu latency measurement
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    print(f"{label}: median {statistics.median(samples):.1f} ms, max {max(samples):.1f} ms over {runs} run(s)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--runs", type=int, default=1)
    args = parser.parse_args()
    if not args.allow_live or not 1 <= args.runs <= 199:
        parser.error('explicit --allow-live and 1..199 runs required; hard cap 200')
    pid = er.cpu_server_pid()
    if pid is None:
        print('BLOCKED: cannot verify CPU-only endpoint ownership; requests=0', flush=True)
        raise SystemExit(2)
    print(f'CPU-only listener verified: PID {pid}; GPU layers=0', flush=True)
    capped = CappedTransport(args.runs + 1)
    transport = er.BoundedTransport(capped)

    def cold():
        er.rank_options(FIXTURE_QUERY, FIXTURE_MENU, client=er.EmbeddingClient(transport=transport, deadline_s=0.15))

    warm_client = er.EmbeddingClient(transport=transport, deadline_s=0.15)
    er.rank_options(FIXTURE_QUERY, FIXTURE_MENU, client=warm_client)

    def warm():
        er.rank_options(FIXTURE_QUERY, FIXTURE_MENU, client=warm_client)

    down = er.EmbeddingClient(transport=lambda *a: (_ for _ in ()).throw(OSError('offline fixture')))

    def failure():
        assert er.rank_options(FIXTURE_QUERY, FIXTURE_MENU, client=down) == [o for o, _ in FIXTURE_MENU]

    _timed("cold cache (one batched request)", cold, args.runs, before=capped.wait_slot)
    _timed("warm cache (no network)" if warm_client._cache else "unprimed cache (fallback)", warm, args.runs)
    _timed("service down (fallback to menu order)", failure, args.runs)
    print(f'requests={capped.requests} valid_responses={capped.successes} cap={capped.cap} rate<=5/s batch_inputs=6', flush=True)


if __name__ == "__main__":
    main()
