from __future__ import annotations

from types import SimpleNamespace

from projector.service import ProjectionService


def test_projection_artifact_rebases_foreign_absolute_path_to_current_data_root(tmp_path) -> None:
    service = object.__new__(ProjectionService)
    service.db = SimpleNamespace(settings=SimpleNamespace(data_dir=tmp_path))
    project_id = "project-one"
    projection_id = "projection-one"
    artifact_name = "Character_Master_Ledger.json"
    expected = (
        tmp_path
        / "projects"
        / project_id
        / "projections"
        / projection_id
        / "generated"
        / artifact_name
    )
    expected.parent.mkdir(parents=True)
    expected.write_text("{}", encoding="utf-8")

    foreign_path = (
        "F:\\old-root\\projects\\project-one\\projections\\projection-one"
        "\\generated\\Character_Master_Ledger.json"
    )
    assert service._resolved_artifact_path(
        project_id, projection_id, artifact_name, foreign_path
    ) == expected.resolve()
