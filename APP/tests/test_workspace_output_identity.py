from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from factory_authoring.service import FactoryAuthoringWorkspaceService


def test_repaired_workspace_documents_create_successor_and_preserve_old_version(tmp_path: Path) -> None:
    service = FactoryAuthoringWorkspaceService.__new__(FactoryAuthoringWorkspaceService)
    service.db = SimpleNamespace(settings=SimpleNamespace(data_dir=tmp_path))
    service.projects = SimpleNamespace(get_project=lambda _: {"project": {"project_id": "project.test", "revision": 3}})
    service.sheets = SimpleNamespace(sheet=lambda _: {
        "build_status": "CHARACTER_SHEET_READY", "owner_character_sheet": {},
        "sheet_artifact": {"sha256": "s" * 64},
    })
    source = tmp_path / "projection.json"
    source.write_text("{}", encoding="utf-8")
    service.projections = SimpleNamespace(artifact=lambda *_: source)
    profile = {"profile_id": "test"}
    workspace_profile = {"semantics": {}, "legacy_boundaries": {}}
    service._authoring_profile = lambda: (profile, "p" * 64)
    service._workspace_profile = lambda: (workspace_profile, "w" * 64)
    service._project_authoring_profile = lambda _snapshot, *values: values
    service._validate_profile = lambda *_: None
    service._validate_documents = lambda *_: None
    documents = {
        "Workspace_Manifest.json": {"event_head_hash": "e" * 64},
        "Command_4/Recorded_Art_Audit.json": {"result": []},
    }
    service._documents = lambda **_: deepcopy(documents)

    old = service.build("project.test")
    old_root = Path(old["workspace_path"])
    old_bytes = {str(p.relative_to(old_root)): p.read_bytes() for p in old_root.rglob("*") if p.is_file()}
    assert service.build("project.test")["workspace_id"] == old["workspace_id"]

    documents["Command_4/Recorded_Art_Audit.json"]["immortal_arts"] = [{"record_id": "art.test", "state": "known"}]
    successor = service.build("project.test")
    assert successor["workspace_id"] != old["workspace_id"]
    assert successor["workspace_sha256"] != old["workspace_sha256"]
    assert {str(p.relative_to(old_root)): p.read_bytes() for p in old_root.rglob("*") if p.is_file()} == old_bytes
    assert json.loads(service._pointer("project.test").read_text())["workspace_id"] == successor["workspace_id"]
    assert service.build("project.test")["workspace_id"] == successor["workspace_id"]
