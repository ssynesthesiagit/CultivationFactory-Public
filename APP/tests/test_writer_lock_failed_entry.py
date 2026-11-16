"""A failed lock entry must release the OS lock before the caller retries."""
from pathlib import Path

import pytest

from combat import gate3_storage


@pytest.mark.parametrize("failure", ["metadata_fsync", "stale_diagnostic"])
def test_failed_writer_lock_entry_does_not_keep_the_match_locked(tmp_path, monkeypatch, failure):
    path = tmp_path / "match" / ".writer.lock"
    path.parent.mkdir()
    if failure == "stale_diagnostic":
        path.write_text('{"pid":123,"match_id":"match:retry"}\n', encoding="utf-8")
    retained = gate3_storage.LocalMatchWriterLock(path, "match:retry")

    def io_failure(*args, **kwargs):
        raise OSError("injected lock metadata I/O failure")

    with monkeypatch.context() as patch:
        if failure == "metadata_fsync":
            patch.setattr(gate3_storage.os, "fsync", io_failure)
        else:
            patch.setattr(gate3_storage, "atomic_write_bytes", io_failure)
        with pytest.raises(OSError, match="injected lock metadata I/O failure") as caught:
            with retained:
                pytest.fail("entry must not succeed when lock metadata cannot be saved")

    # Keep both the failed context and its traceback alive. Release must be
    # deterministic, not depend on garbage collection of an exception object.
    assert caught.value.__traceback__ is not None
    try:
        with gate3_storage.LocalMatchWriterLock(path, "match:retry"):
            assert path.is_file()
        assert retained._handle is None
        assert path.read_bytes() == b""
    finally:
        if retained._handle is not None:
            retained.__exit__(None, None, None)
