"""Provider-free tests for the DCC AI identity contract."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from ai_provider import identity
from ai_provider.identity import (
    IDENTITY_DOMAIN,
    SERVICE_LABELED,
    IdentityResolutionError,
    build_hosted_identity,
    build_local_identity,
    canonical_identity_document,
    hash_identity_payload,
    make_identity_payload,
)


PORT = 12345
SOCKET_INODE = "4242"
PID = "7319"
MODEL_ID = "qwen3.5-9b"


def _tcp_row(*, inode: str = SOCKET_INODE, port: int = PORT, uid: int | None = None) -> str:
    uid = os.geteuid() if uid is None else uid
    return (
        f"  0: 0100007F:{port:04X} 00000000:0000 0A "
        f"00000000:00000000 00:00000000 00000000 {uid} 0 {inode} 1 "
        "0000000000000000 100 0 0 10 0"
    )


def _proc_tree(tmp_path: Path, *, alias: str = MODEL_ID, model_path: Path | None = None) -> dict[str, Path]:
    model = model_path or (tmp_path / "model.gguf")
    executable = tmp_path / "llama-server"
    model.write_bytes(b"GGUF-model-v1")
    executable.write_bytes(b"llama-executable-v1")
    proc = tmp_path / "proc"
    (proc / "net").mkdir(parents=True)
    (proc / "net" / "tcp").write_text("  sl local_address rem_address st\n" + _tcp_row() + "\n", encoding="ascii")
    (proc / "net" / "tcp6").write_text("  sl local_address rem_address st\n", encoding="ascii")
    pid = proc / PID
    (pid / "fd").mkdir(parents=True)
    os.symlink(f"socket:[{SOCKET_INODE}]", pid / "fd" / "7")
    os.symlink(str(executable), pid / "exe")
    uid = os.geteuid()
    (pid / "status").write_text(f"Name:\tllama-server\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n", encoding="ascii")
    command_line = f"{executable}\x00--model\x00{model}\x00--alias\x00{alias}\x00".encode("utf-8")
    (pid / "cmdline").write_bytes(command_line)
    return {"proc": proc, "model": model, "executable": executable, "pid": pid}


def _local_record(tree: dict[str, Path]) -> dict[str, object]:
    return build_local_identity(
        "local",
        MODEL_ID,
        f"http://127.0.0.1:{PORT}/v1/chat/completions",
        proc_root=tree["proc"],
    )


def test_known_local_formula_and_exact_payload(tmp_path: Path) -> None:
    tree = _proc_tree(tmp_path)
    record = _local_record(tree)
    payload = make_identity_payload(
        provider_kind="local",
        provider_id="local",
        model_id=MODEL_ID,
        model_revision_or_artifact_sha256=hashlib.sha256(tree["model"].read_bytes()).hexdigest(),
        provider_adapter_sha256=hashlib.sha256(tree["executable"].read_bytes()).hexdigest(),
    )
    expected = hashlib.sha256(
        json.dumps(
            canonical_identity_document(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert record["identity_sha256"] == expected
    assert record["domain"] == IDENTITY_DOMAIN
    assert set(record["payload"]) == {
        "provider_kind",
        "provider_id",
        "model_id",
        "model_revision_or_artifact_sha256",
        "provider_adapter_sha256",
    }
    assert record["identity_assurance"] == "LOCAL_ARTIFACTS"


def test_model_and_adapter_bytes_change_identity(tmp_path: Path) -> None:
    tree = _proc_tree(tmp_path)
    first = _local_record(tree)
    tree["model"].write_bytes(b"GGUF-model-v2")
    second = _local_record(tree)
    assert first["identity_sha256"] != second["identity_sha256"]
    assert first["payload"]["provider_adapter_sha256"] == second["payload"]["provider_adapter_sha256"]
    tree["executable"].write_bytes(b"llama-executable-v2")
    third = _local_record(tree)
    assert second["identity_sha256"] != third["identity_sha256"]
    assert second["payload"]["model_revision_or_artifact_sha256"] == third["payload"]["model_revision_or_artifact_sha256"]


@pytest.mark.parametrize("case", ["alias", "unowned", "ambiguous", "missing"])
def test_local_identity_fails_closed(tmp_path: Path, case: str) -> None:
    tree = _proc_tree(tmp_path, alias="wrong" if case == "alias" else MODEL_ID)
    if case == "unowned":
        (tree["pid"] / "fd" / "7").unlink()
    elif case == "ambiguous":
        other = tree["proc"] / "7320"
        (other / "fd").mkdir(parents=True)
        os.symlink(f"socket:[{SOCKET_INODE}]", other / "fd" / "8")
    elif case == "missing":
        tree["model"].unlink()
    with pytest.raises(IdentityResolutionError):
        _local_record(tree)


def test_unreadable_other_uid_process_trees_do_not_block(tmp_path: Path) -> None:
    tree = _proc_tree(tmp_path)
    for pid_number in ("9000", "9001", "9002"):
        system = tree["proc"] / pid_number
        (system / "fd").mkdir(parents=True)
        (system / "status").write_text("Name:\tinit\nUid:\t0\t0\t0\t0\n", encoding="ascii")
        (system / "fd").chmod(0)
    try:
        assert _local_record(tree)["identity_assurance"] == "LOCAL_ARTIFACTS"
    finally:
        for pid_number in ("9000", "9001", "9002"):
            (tree["proc"] / pid_number / "fd").chmod(0o700)


def test_unreadable_same_uid_process_trees_do_not_block(tmp_path: Path) -> None:
    """A same-UID process that hides its fd table is skipped, not fatal.

    On an ordinary desktop several of the owner's own processes are
    non-dumpable -- session launcher wrappers, ``(sd-pam)``, a transient
    ``systemctl`` -- so an abort here meant the proof could never succeed and
    every local model was refused.  The one visible socket owner still binds.
    """

    tree = _proc_tree(tmp_path)
    uid = os.geteuid()
    for pid_number, name in (("9100", "uwsm-app"), ("9101", "(sd-pam)"), ("9102", "systemctl")):
        hidden = tree["proc"] / pid_number
        (hidden / "fd").mkdir(parents=True)
        (hidden / "status").write_text(f"Name:\t{name}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n", encoding="ascii")
        (hidden / "fd").chmod(0)
    try:
        record = _local_record(tree)
        assert record["identity_assurance"] == "LOCAL_ARTIFACTS"
        assert record["payload"]["model_id"] == MODEL_ID
    finally:
        for pid_number in ("9100", "9101", "9102"):
            (tree["proc"] / pid_number / "fd").chmod(0o700)


def test_duplicate_fds_in_one_pid_remain_one_owner(tmp_path: Path) -> None:
    tree = _proc_tree(tmp_path)
    os.symlink(f"socket:[{SOCKET_INODE}]", tree["pid"] / "fd" / "8")
    assert _local_record(tree)["identity_assurance"] == "LOCAL_ARTIFACTS"


def test_two_same_uid_owning_pids_fail_closed(tmp_path: Path) -> None:
    tree = _proc_tree(tmp_path)
    other = tree["proc"] / "7320"
    (other / "fd").mkdir(parents=True)
    uid = os.geteuid()
    (other / "status").write_text(f"Name:\tllama-server\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n", encoding="ascii")
    os.symlink(f"socket:[{SOCKET_INODE}]", other / "fd" / "8")
    with pytest.raises(IdentityResolutionError):
        _local_record(tree)


def test_socket_uid_mismatch_fails_closed(tmp_path: Path) -> None:
    tree = _proc_tree(tmp_path)
    uid = os.geteuid()
    alternate_uid = uid + 1
    tree["proc"].joinpath("net", "tcp").write_text(
        "  sl local_address rem_address st\n" + _tcp_row(uid=alternate_uid) + "\n",
        encoding="ascii",
    )
    with pytest.raises(IdentityResolutionError):
        _local_record(tree)


def test_malformed_same_uid_candidate_status_fails_closed(tmp_path: Path) -> None:
    tree = _proc_tree(tmp_path)
    (tree["pid"] / "status").write_text("Name:\tllama-server\nUid:\tbroken\n", encoding="ascii")
    with pytest.raises(IdentityResolutionError):
        _local_record(tree)


def test_local_result_never_contains_endpoint_key_path_or_pid(tmp_path: Path) -> None:
    tree = _proc_tree(tmp_path)
    endpoint = f"http://127.0.0.1:{PORT}/v1/chat/completions"
    result = _local_record(tree)
    encoded = json.dumps(result, sort_keys=True)
    assert endpoint not in encoded
    assert "secret-key" not in encoded
    assert str(tree["model"]) not in encoded
    assert PID not in encoded


def test_hosted_identity_is_deterministic_service_labeled_and_endpoint_free() -> None:
    first = build_hosted_identity("openai", "gpt-4o-mini")
    second = build_hosted_identity("openai", "gpt-4o-mini")
    changed = build_hosted_identity("openai", "gpt-4o")
    assert first == second
    assert first["identity_assurance"] == SERVICE_LABELED
    assert first["payload"]["provider_kind"] == "hosted"
    assert first["identity_sha256"] != changed["identity_sha256"]
    encoded = json.dumps(first, sort_keys=True)
    assert "https://api.example.test" not in encoded
    assert "secret-key" not in encoded


def test_digest_cache_reuses_unchanged_stat_and_rehashes_on_stat_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "artifact.gguf"
    path.write_bytes(b"first")
    identity._DIGEST_CACHE.clear()
    original_open = identity.Path.open
    opens = 0

    def counted_open(self: Path, *args: object, **kwargs: object):
        nonlocal opens
        opens += 1
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(identity.Path, "open", counted_open)
    first = identity._hash_regular_file(path)
    assert identity._hash_regular_file(path) == first
    assert opens == 1
    opens = 0
    with original_open(path, "wb") as stream:
        stream.write(b"second")
    assert identity._hash_regular_file(path) != first
    assert opens == 1


def test_service_identity_integration_remains_read_only_and_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    from ai_provider import service as service_module

    calls: list[tuple[object, ...]] = []
    service = object.__new__(service_module.AIProviderService)
    service._settings = lambda: {"enabled": True, "provider_id": "openai", "model": "gpt-4o-mini", "endpoint": "https://api.example.test"}

    def derive(*args: object, **kwargs: object) -> dict[str, object]:
        calls.append((*args, kwargs))
        return build_hosted_identity("openai", "gpt-4o-mini")

    monkeypatch.setattr(service_module, "derive_provider_identity", derive)
    result = service.selected_ai_identity()
    assert result["selected_ai_identity_state"] == "AVAILABLE_STATIC"
    assert result["identity_assurance"] == SERVICE_LABELED
    assert set(result) == {"selected_ai_identity_sha256", "selected_ai_identity_state", "identity_assurance"}
    assert calls == [("openai", "gpt-4o-mini", {"endpoint": "https://api.example.test"})]
