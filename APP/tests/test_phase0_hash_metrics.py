from __future__ import annotations

import hashlib
import threading

from app.core import (
    SHA256_BYTE_COUNTERS_ENV,
    canonical_json,
    reset_sha256_byte_counters,
    sha256_file,
    sha256_json,
    snapshot_sha256_byte_counters,
)


def test_hash_digests_are_unchanged_and_disabled_path_has_no_counts(tmp_path, monkeypatch):
    payload = {"greeting": "你好, Li Wei", "values": [1, True, None]}
    source = tmp_path / "payload.bin"
    source.write_bytes("chunk-你好".encode("utf-8"))
    expected_json = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    expected_file = hashlib.sha256(source.read_bytes()).hexdigest()

    monkeypatch.delenv(SHA256_BYTE_COUNTERS_ENV, raising=False)
    reset_sha256_byte_counters()
    assert sha256_json(payload) == expected_json
    assert sha256_file(source) == expected_file
    assert snapshot_sha256_byte_counters() == {
        "sha256_file_bytes": 0,
        "sha256_json_bytes": 0,
        "total_bytes": 0,
    }


def test_enabled_counters_measure_exact_unicode_json_and_file_bytes(tmp_path, monkeypatch):
    payload = {"greeting": "你好, Li Wei", "values": [1, True, None]}
    source = tmp_path / "payload.bin"
    source.write_bytes(b"abc\x00" * 3)
    expected_json_bytes = len(canonical_json(payload).encode("utf-8"))
    expected_file_bytes = source.stat().st_size

    monkeypatch.setenv(SHA256_BYTE_COUNTERS_ENV, "1")
    reset_sha256_byte_counters()
    assert sha256_json(payload) == hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    assert sha256_file(source) == hashlib.sha256(source.read_bytes()).hexdigest()
    assert snapshot_sha256_byte_counters() == {
        "sha256_file_bytes": expected_file_bytes,
        "sha256_json_bytes": expected_json_bytes,
        "total_bytes": expected_file_bytes + expected_json_bytes,
    }

    reset_sha256_byte_counters()
    assert snapshot_sha256_byte_counters() == {
        "sha256_file_bytes": 0,
        "sha256_json_bytes": 0,
        "total_bytes": 0,
    }


def test_enabled_counters_are_accurate_for_concurrent_calls(tmp_path, monkeypatch):
    payload = {"text": "并发计数", "values": list(range(20))}
    source = tmp_path / "payload.bin"
    source.write_bytes(b"x" * (1024 * 1024 + 17))
    json_bytes = len(canonical_json(payload).encode("utf-8"))
    file_bytes = source.stat().st_size
    calls = 4
    errors: list[BaseException] = []

    monkeypatch.setenv(SHA256_BYTE_COUNTERS_ENV, "true")
    reset_sha256_byte_counters()

    def worker() -> None:
        try:
            sha256_json(payload)
            sha256_file(source)
        except BaseException as exc:  # pragma: no cover - assertion below reports it
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert snapshot_sha256_byte_counters() == {
        "sha256_file_bytes": calls * file_bytes,
        "sha256_json_bytes": calls * json_bytes,
        "total_bytes": calls * (file_bytes + json_bytes),
    }
