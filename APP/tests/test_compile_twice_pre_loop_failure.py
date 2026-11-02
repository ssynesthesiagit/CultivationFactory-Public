"""A failure before the compile loop must surface its own diagnostic."""
from __future__ import annotations

import pytest

from app.core import FoundryError
from character_creation.service import CharacterCreationExecutionService


import gc


class _Authoring:
    def candidate_compilation_authority(self, run, *, final_plan=None):
        # Automatic cycle collection is paused for the whole guarded compile.
        assert not gc.isenabled()
        raise FoundryError("CG1_GM_CANDIDATE_AUTHORING_POINTER_STALE", "stale pointer", status_code=409)


def test_compile_twice_reports_candidate_authority_failure_not_unbound_local(monkeypatch):
    service = CharacterCreationExecutionService.__new__(CharacterCreationExecutionService)
    service.candidate_gm_authoring = _Authoring()
    checkpoints: list[dict] = []
    service._write_compile_checkpoint = lambda run, **fields: checkpoints.append(fields)
    monkeypatch.delenv("TIANXIA_DETERMINISTIC_UTC", raising=False)
    monkeypatch.delenv("TIANXIA_DETERMINISTIC_APPROVAL_SEED", raising=False)
    run = {"created_at": "2026-09-10T18:25:07Z", "request": {"request_sha256": "a" * 64}}

    with pytest.raises(FoundryError) as caught:
        service._compile_twice(run, {"plan": True})

    assert caught.value.code == "CG1_GM_CANDIDATE_AUTHORING_POINTER_STALE"
    assert checkpoints[-1]["status"] == "failed"
    assert checkpoints[-1]["error_code"] == "CG1_GM_CANDIDATE_AUTHORING_POINTER_STALE"
    assert "TIANXIA_DETERMINISTIC_UTC" not in __import__("os").environ
    assert gc.isenabled()
