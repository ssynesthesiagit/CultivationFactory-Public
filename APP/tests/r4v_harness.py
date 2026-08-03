from __future__ import annotations

import hashlib
import os
from pathlib import Path

from app.core import FoundryError
from security.integrity import FileIntegrityKeyProvider

ENV_KEY_HEX = "TIANXIA_R4V_TEST_INTEGRITY_KEY_HEX"
ENV_KEY_ID = "TIANXIA_R4V_TEST_INTEGRITY_KEY_ID"
EXPECTED_FACTORY_SHA256 = "4daf167cf634f27efef4dd2f1c8700bb4b7037cc6234c32be1af90aea5916385"


def expected_key_id(key: bytes) -> str:
    return "integrity-key-v1:" + hashlib.sha256(key).hexdigest()


def configured_test_key() -> tuple[str, bytes] | None:
    raw = os.environ.get(ENV_KEY_HEX)
    if raw is None:
        return None
    try:
        key = bytes.fromhex(raw)
    except ValueError as exc:
        raise RuntimeError("R4V_TEST_INTEGRITY_KEY_HEX_INVALID") from exc
    if len(key) != 32:
        raise RuntimeError("R4V_TEST_INTEGRITY_KEY_LENGTH_INVALID")
    key_id = expected_key_id(key)
    supplied_id = os.environ.get(ENV_KEY_ID)
    if supplied_id and supplied_id != key_id:
        raise RuntimeError("R4V_TEST_INTEGRITY_KEY_ID_MISMATCH")
    return key_id, key


def provision_external_test_key(data_dir: Path) -> None:
    configured = configured_test_key()
    if configured is None:
        return
    expected_id, key = configured
    provider = FileIntegrityKeyProvider(data_dir)
    if provider.path.exists():
        actual_id, _ = provider.load_existing()
        if actual_id != expected_id:
            raise FoundryError(
                "R4V_TEST_INTEGRITY_CONTEXT_MISMATCH",
                "The disposable test data directory already contains another integrity key.",
                details={"expected_key_id": expected_id, "actual_key_id": actual_id},
                status_code=500,
            )
        return
    # TEST-only harness seam. Production code never reads these environment
    # variables and cannot request deterministic key material.
    provider._write(key)
