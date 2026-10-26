from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from app.core import FoundryError
from character_creation import CharacterCreationExecutionService


def test_finalize_rejects_overlap_and_releases_after_success_and_error(tmp_path) -> None:
    service = CharacterCreationExecutionService(
        SimpleNamespace(settings=SimpleNamespace(
            logs_dir=tmp_path / "logs", data_dir=tmp_path, security_dir=tmp_path / "security",
        )),
        stage1=None,
        provider=None,
        project_store=None,
    )
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def fake_finalize_locked(run_id: str, **_kwargs):
        calls.append(run_id)
        if len(calls) == 1:
            entered.set()
            release.wait(timeout=2)
            return {"run_id": run_id, "status": "READY_FOR_REVIEW"}
        if len(calls) == 2:
            raise RuntimeError("simulated finalization failure")
        return {"run_id": run_id, "status": "READY_FOR_REVIEW"}

    service._finalize_locked = fake_finalize_locked
    result: list[dict] = []
    worker = threading.Thread(target=lambda: result.append(service.finalize("first")))
    worker.start()
    assert entered.wait(timeout=2)

    with pytest.raises(FoundryError) as busy:
        service.finalize("overlap")
    assert busy.value.code == "CG1_FINALIZATION_IN_PROGRESS"
    assert busy.value.status_code == 409
    release.set()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert result == [{"run_id": "first", "status": "READY_FOR_REVIEW"}]

    with pytest.raises(RuntimeError, match="simulated finalization failure"):
        service.finalize("fails")
    assert service.finalize("after-error")["run_id"] == "after-error"
    assert calls == ["first", "fails", "after-error"]
