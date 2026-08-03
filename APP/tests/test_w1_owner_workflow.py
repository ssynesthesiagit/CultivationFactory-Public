from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app.api import create_app
from app.core import Database, FoundryError, Settings, canonical_json, sha256_file
from contracts.canonical import canonical_project_hash
from portable_character.service import PortableCharacterPackageService

ROOT = Path(__file__).resolve().parents[1]
CHARACTER = ROOT / "tests/fixtures/W1/INSTALL_THIS_C1A_Clean_Fire_Qi_Proof_Character.zip"
GM_ZIP = ROOT / "gm_screen/HF05ZUI_R2K3_HF3_W1_CoreStats_GMScreen.zip"
CHARACTER_SHA = "c362665c32a06cd3323981c2ceb116d9e137a9e48bbdba4065363b65253d5fd8"
GM_SHA = "c281c80e96c718a2c629b65c762b1c053a82eff7201d018a6acca1110c1c0f8f"


def _counts(db: Database) -> dict[str, int]:
    with db.connection() as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {name: int(conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]) for name in names}


def _raw_project() -> dict:
    with zipfile.ZipFile(CHARACTER) as outer:
        nested = outer.read("source/Character_Project.tianxia-project.zip")
    with zipfile.ZipFile(io.BytesIO(nested)) as project_zip:
        return json.loads(project_zip.read("project.json"))


def _insert_project(db: Database, project: dict) -> None:
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO projects(project_id,working_name,status,revision,created_at,updated_at,target_factory_version,
               target_candidate_schema_version,target_gm_screen_version,catalog_build_hash,quality_target,project_json,
               compatibility_projection_status,compile_status,consumer_verification_status,canonical_project_hash,
               canonical_schema_version,contract_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                project["project_id"], project.get("name") or "Imported Character", project.get("status") or "stage_2",
                project["revision"], project["created_at"], project["updated_at"], "HF05ZVK-R1H", "HF05ZVK-R1F",
                "HF05ZUI-R2K.3-HF3-W1", None, "owner", canonical_json(project), "READY", "READY",
                "GM_SCREEN_SOURCE_CONSUMER_VERIFIED", canonical_project_hash(project), project.get("schema_version"), "verified",
            ),
        )


def test_exact_character_preview_is_non_mutating_and_owner_readable(fresh_db):
    assert sha256_file(CHARACTER) == CHARACTER_SHA
    service = PortableCharacterPackageService(fresh_db)
    before = _counts(fresh_db)
    preview = service.preview_for_factory(CHARACTER)
    assert _counts(fresh_db) == before
    assert preview["disposition"] == "NEW"
    assert preview["character"] == {
        "name": "C1A Clean Fire-Qi Proof", "cultivation_level": 5, "realm": "Mortal Realm",
        "path": "Qi Cultivation", "subpath": "Cinder Heart Cultivator",
        "project_id": "6a64af8e-7b8f-447b-bd81-fe4432b048c2",
    }
    assert preview["package"]["sha256"] == CHARACTER_SHA
    assert {key: preview["readiness"].get(key) for key in ("advancement", "character_sheet", "gm_screen", "combat")} == {
        "advancement": "ADVANCEMENT_READY", "character_sheet": "CHARACTER_SHEET_READY",
        "gm_screen": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED", "combat": "NOT_ATTEMPTED_OR_CAPABILITY_BLOCKED",
    }
    assert preview["readiness"]["encounter_setup_required"] is True
    assert preview["readiness"]["battlefield_owner_choice_committed"] is False
    assert preview["readiness"]["token_placement_committed"] is False
    assert preview["readiness"]["initiative_attempted"] is False


def test_preview_identical_and_conflict_are_fail_closed(fresh_db):
    project = _raw_project(); _insert_project(fresh_db, project)
    service = PortableCharacterPackageService(fresh_db)
    assert service.preview_for_factory(CHARACTER)["disposition"] == "IDENTICAL"
    with fresh_db.transaction() as conn:
        changed = dict(project); changed["revision"] = project["revision"] + 1
        conn.execute("UPDATE projects SET revision=?,project_json=? WHERE project_id=?", (changed["revision"], canonical_json(changed), project["project_id"]))
    before = _counts(fresh_db)
    preview = service.preview_for_factory(CHARACTER)
    assert preview["disposition"] == "CONFLICT" and preview["can_import"] is False
    assert _counts(fresh_db) == before


def test_first_import_and_identical_reimport_use_existing_persistence(monkeypatch, fresh_db, tmp_path):
    from character_sheet.service import CharacterSheetService
    from projector.service import ProjectionService
    from vendor_adapter.service import FactoryAdapter
    from product_bootstrap.service import ProductReadinessService

    service = PortableCharacterPackageService(fresh_db)
    monkeypatch.setattr(ProductReadinessService, "report", lambda _self: {"portable_import": {"ready": True}, "blocking_reasons": []})
    project = _raw_project()
    with zipfile.ZipFile(CHARACTER) as zf:
        manifest = json.loads(zf.read("PACKAGE_MANIFEST.json"))
        expected_sheet_sha = hashlib.sha256(zf.read("Tianxia_Owner_Character_Sheet_v1.json")).hexdigest()

    def fake_project_import(_nested: Path) -> dict:
        _insert_project(fresh_db, project)
        return {"status": "IMPORTED", "project_id": project["project_id"], "revision": project["revision"]}

    monkeypatch.setattr(service.projects, "import_project", fake_project_import)
    monkeypatch.setattr(FactoryAdapter, "status", lambda _self: {"configured": True, "health": "READY", "factory_root": str(tmp_path / "Factory Root")})
    monkeypatch.setattr(
        ProjectionService,
        "build",
        lambda _self, project_id, force=True: {
            "status": "READY", "projection_id": "w1-test-projection",
            "artifacts": [{"artifact_name": name, "sha256": digest} for name, digest in manifest["advancement_projection_references"].items()],
        },
    )
    monkeypatch.setattr(CharacterSheetService, "sheet", lambda _self, project_id, compact=False: {"build_status": "CHARACTER_SHEET_READY", "sheet_artifact": {"sha256": expected_sheet_sha}})

    first = service.import_into_factory(CHARACTER)
    assert first["status"] == "IMPORTED" and first["project_id"] == project["project_id"]
    installed = fresh_db.settings.data_dir / "portable_characters" / project["project_id"] / "current.zip"
    assert sha256_file(installed) == CHARACTER_SHA
    before = _counts(fresh_db)
    second = service.import_into_factory(CHARACTER)
    assert second["status"] == "ALREADY_INSTALLED_IDENTICAL"
    assert _counts(fresh_db) == before


def test_same_id_different_project_import_rejects_before_mutation(monkeypatch, fresh_db):
    from product_bootstrap.service import ProductReadinessService

    monkeypatch.setattr(ProductReadinessService, "report", lambda _self: {"portable_import": {"ready": True}, "blocking_reasons": []})
    project = _raw_project(); changed = dict(project); changed["revision"] += 1
    _insert_project(fresh_db, changed)
    before = _counts(fresh_db)
    with pytest.raises(FoundryError, match="different character already uses this project ID") as exc:
        PortableCharacterPackageService(fresh_db).import_into_factory(CHARACTER)
    assert exc.value.code == "PORTABLE_CHARACTER_PROJECT_ID_CONFLICT"
    assert _counts(fresh_db) == before


def test_upload_preview_requires_no_inbox_copy_and_cleans_staging(tmp_path):
    settings = Settings.from_env(ROOT, tmp_path / "data with spaces" / "用户")
    app = create_app(settings)
    with TestClient(app) as client:
        token = client.get("/api/session").json()["token"]
        response = client.post(
            "/api/characters/portable-preview",
            content=CHARACTER.read_bytes(),
            headers={"X-Foundry-Token": token, "X-Tianxia-Filename": "C1A proof.zip", "Content-Type": "application/zip"},
        )
    assert response.status_code == 200
    assert response.json()["package"]["sha256"] == CHARACTER_SHA
    assert list(settings.inbox_dir.iterdir()) == []
    staging = settings.data_dir / "upload_staging"
    assert not staging.exists() or list(staging.iterdir()) == []


def test_upload_rejects_unsafe_zip_and_cleans_staging(tmp_path):
    settings = Settings.from_env(ROOT, tmp_path / "data")
    app = create_app(settings)
    unsafe = io.BytesIO()
    with zipfile.ZipFile(unsafe, "w") as zf:
        zf.writestr("../escape.txt", "no")
    with TestClient(app) as client:
        token = client.get("/api/session").json()["token"]
        response = client.post("/api/characters/portable-preview", content=unsafe.getvalue(), headers={"X-Foundry-Token": token, "X-Tianxia-Filename": "unsafe.zip", "Content-Type": "application/zip"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PORTABLE_CHARACTER_UNSAFE_PATH"
    staging = settings.data_dir / "upload_staging"
    assert not staging.exists() or list(staging.iterdir()) == []


def test_owner_navigation_sections_are_siblings_and_have_visible_states():
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    screens = {node.get("id") for node in soup.select("main > section.screen")}
    assert {"screen-builder","screen-projects","screen-combat","screen-catalog","screen-packs","screen-status"}.issubset(screens)
    combat = soup.find(id="screen-combat")
    assert combat.find(id="screen-status") is None
    assert soup.find(id="characterZipDropZone").get("tabindex") == "0"
    assert soup.find(id="characterZipFile").get("accept")
    assert soup.find(id="catalogScreenState") and soup.find(id="packsScreenState") and soup.find(id="statusScreenState")
    javascript = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert "Promise.allSettled([loadStatus(), loadCatalog(), loadPacks(), loadAIProviderStatus()])" in javascript
    assert "/api/characters/portable-preview" in javascript and "/api/characters/portable-import-upload" in javascript
    assert "Already installed — identical package" in javascript


def test_gm_screen_exact_core_stats_v2_and_v1_fallback(tmp_path):
    assert sha256_file(GM_ZIP) == GM_SHA
    gm_root = tmp_path / "gm"; character_root = tmp_path / "character"
    with zipfile.ZipFile(GM_ZIP) as zf: zf.extractall(gm_root)
    with zipfile.ZipFile(CHARACTER) as zf: zf.extractall(character_root)
    result = subprocess.run(
        ["node", str(ROOT / "tests/w1_gm_core_stats_check.js"), str(gm_root / "app.js"), str(character_root / "Tianxia_GM_Character_View_Model_v2.json"), str(character_root / "Tianxia_GM_Character_Model_v1.json")],
        text=True, capture_output=True, check=True,
    )
    report = json.loads(result.stdout)
    assert report["status"] == "PASS"
    manifest = json.loads((gm_root / "GM_SCREEN_BUILD_MANIFEST.json").read_text())
    assert manifest["viewer_tabs"] == 18 and len(manifest["required_tabs"]) == 18
    assert "[object Object]" not in result.stdout


def test_windows_default_data_root_and_non_destructive_legacy_migration(tmp_path):
    import importlib.util, sys
    launcher_path = ROOT / "packaging/windows_portable/portable_launcher.py"
    spec = importlib.util.spec_from_file_location("w1_launcher", launcher_path); module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module; spec.loader.exec_module(module)
    package = tmp_path / "Program Files" / "Tianxia Factory"
    local = tmp_path / "用户 Name" / "AppData" / "Local"
    assert module.PortablePaths.default_user_data(package, platform_name="nt", environ={"LOCALAPPDATA": str(local)}) == (local / "Tianxia Factory").resolve()
    legacy = package / "UserData"; legacy.mkdir(parents=True); (legacy / "owner.txt").write_text("legacy")
    target = local / "Tianxia Factory"; target.mkdir(parents=True); (target / "keep.txt").write_text("keep")
    paths = module.PortablePaths(package, package / "Runtime", package / "BundledContent", target, package / "Runtime/PrivatePython/python.exe", legacy)
    settings = module.ensure_owner_layout(paths)
    assert (settings.data_dir / "owner.txt").read_text() == "legacy"
    assert (settings.data_dir / "keep.txt").read_text() == "keep"
    assert (legacy / "owner.txt").exists()
