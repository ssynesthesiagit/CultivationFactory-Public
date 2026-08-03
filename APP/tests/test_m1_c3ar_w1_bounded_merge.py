from __future__ import annotations

import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import create_app
from app.core import Database, Settings, canonical_json, sha256_file
from contracts.canonical import canonical_project_hash
from portable_character.service import PortableCharacterPackageService

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PACKAGE = ROOT / "tests/fixtures/M1/C1A_Clean_Fire_Qi_Proof_Character_Combat_Runtime_Ready.zip"
RUNTIME_SHA = "1bc4142ccda1c51ba9972c5938a50043ee0de0fd0b1e2cd8d62dc838e623fddd"
GM_PACKAGE = ROOT / "gm_screen/HF05ZUI_R2K3_HF3_W1_CoreStats_GMScreen.zip"
GM_SHA = "c281c80e96c718a2c629b65c762b1c053a82eff7201d018a6acca1110c1c0f8f"


def _raw_project() -> dict:
    with zipfile.ZipFile(RUNTIME_PACKAGE) as outer:
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


def test_m1_status_and_stop_boundary_are_explicit():
    status = json.loads((ROOT / "R6_6_9_2_M1_MERGE_STATUS.json").read_text())
    assert status["runtime_readiness"] == "COMBAT_RUNTIME_READY_PRE_ENCOUNTER"
    assert status["native_windows_acceptance"] == "NATIVE_WINDOWS_OWNER_ACCEPTANCE_DEFERRED"
    assert status["runtime_identities"]["mechanic_count"] == 30
    assert status["runtime_identities"]["primitive_handler_count"] == 19
    assert status["runtime_identities"]["persisted_event_count"] == 0
    assert all(value is False for value in status["stop_boundary"].values())


def test_w1_operational_inventory_and_gm_replacement_are_present():
    inventory = json.loads((ROOT / "M1_MERGE_INVENTORY.json").read_text())
    assert inventory["operational_overlap"] == []
    assert inventory["direct_overlap"] == ["SHA256SUMS.txt"]
    assert inventory["combat_files_modified_by_overlay"] is False
    for rel in inventory["operational_apply_paths"]:
        assert (ROOT / rel).is_file(), rel
    assert GM_PACKAGE.is_file() and sha256_file(GM_PACKAGE) == GM_SHA
    assert not (ROOT / "gm_screen/HF05ZUI_R2K3_HF3_Foundation34_GMScreen.zip").exists()
    assert not (ROOT / "gm_screen/HF05ZUI_R2K3_HF3_Foundation34_GMScreen.zip.sha256").exists()


def test_active_code_has_no_stale_gm_screen_reference():
    active = [
        ROOT / "app", ROOT / "gm_export", ROOT / "portable_character", ROOT / "projector",
        ROOT / "static", ROOT / "packaging/windows_portable",
    ]
    stale = "HF05ZUI_R2K3_HF3_Foundation34_GMScreen.zip"
    hits = []
    for base in active:
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.lower() not in {".zip", ".png", ".jpg", ".jpeg", ".pyc"}:
                try:
                    if stale in path.read_text(encoding="utf-8"):
                        hits.append(path.relative_to(ROOT).as_posix())
                except UnicodeDecodeError:
                    pass
    assert hits == []


def test_runtime_ready_package_preview_preserves_c3ar_readiness(fresh_db):
    assert sha256_file(RUNTIME_PACKAGE) == RUNTIME_SHA
    preview = PortableCharacterPackageService(fresh_db).preview_for_factory(RUNTIME_PACKAGE)
    assert preview["valid"] is True and preview["disposition"] == "NEW"
    expected = {
        "advancement": "ADVANCEMENT_READY",
        "character_sheet": "CHARACTER_SHEET_READY",
        "gm_screen": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED",
        "combat": "COMBAT_READY",
    }
    assert {key: preview["readiness"][key] for key in expected} == expected
    assert preview["readiness"]["combat_ready_semantics"] == "RUNTIME_READY_PRE_ENCOUNTER"
    assert preview["incoming_identity"] == {
        "project_id": "6a64af8e-7b8f-447b-bd81-fe4432b048c2",
        "revision": 27,
        "canonical_project_hash": "00972f6b5a80767362ae8b5af7effbddfbbd608c143bb0ecf99830c9fe124b28",
        "content_lock_hash": "334a7fe393e99ea12ecf6db6c1d57e0fa9c220187d8e87f13d068173ed69b0bb",
        "event_head_hash": "9f9c987cac1d3dc15e5e9911f10bbebe0382034b278ff2c10d81d9563ba41354",
    }


def test_owner_upload_endpoint_previews_runtime_ready_package_without_mutation(tmp_path):
    settings = Settings.from_env(ROOT, tmp_path / "M1 data with spaces 用户")
    app = create_app(settings)
    with TestClient(app) as client:
        token = client.get("/api/session").json()["token"]
        response = client.post(
            "/api/characters/portable-preview",
            content=RUNTIME_PACKAGE.read_bytes(),
            headers={"X-Foundry-Token": token, "X-Tianxia-Filename": RUNTIME_PACKAGE.name, "Content-Type": "application/zip"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["readiness"]["combat"] == "COMBAT_READY"
    assert payload["package"]["sha256"] == RUNTIME_SHA
    assert list(settings.inbox_dir.iterdir()) == []
    staging = settings.data_dir / "upload_staging"
    assert not staging.exists() or list(staging.iterdir()) == []


def test_runtime_ready_first_import_and_identical_reimport_use_w1_persistence(monkeypatch, fresh_db, tmp_path):
    from character_sheet.service import CharacterSheetService
    from projector.service import ProjectionService
    from vendor_adapter.service import FactoryAdapter
    from product_bootstrap.service import ProductReadinessService

    service = PortableCharacterPackageService(fresh_db)
    monkeypatch.setattr(ProductReadinessService, "report", lambda _self: {"portable_import": {"ready": True}, "blocking_reasons": []})
    project = _raw_project()
    with zipfile.ZipFile(RUNTIME_PACKAGE) as zf:
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
            "status": "READY", "projection_id": "m1-test-projection",
            "artifacts": [{"artifact_name": name, "sha256": digest} for name, digest in manifest["advancement_projection_references"].items()],
        },
    )
    monkeypatch.setattr(CharacterSheetService, "sheet", lambda _self, project_id, compact=False: {"build_status": "CHARACTER_SHEET_READY", "sheet_artifact": {"sha256": expected_sheet_sha}})

    first = service.import_into_factory(RUNTIME_PACKAGE)
    assert first["status"] == "IMPORTED"
    assert first["readiness"]["combat"] == "COMBAT_READY"
    installed = fresh_db.settings.data_dir / "portable_characters" / project["project_id"] / "current.zip"
    assert sha256_file(installed) == RUNTIME_SHA
    second = service.import_into_factory(RUNTIME_PACKAGE)
    assert second["status"] == "ALREADY_INSTALLED_IDENTICAL"


def test_runtime_package_has_no_encounter_controller_or_persisted_combat_payload():
    with zipfile.ZipFile(RUNTIME_PACKAGE) as zf:
        names = {name for name in zf.namelist() if not name.endswith("/")}
        readiness = json.loads(zf.read("READINESS.json"))
        assert readiness["combat"] == "COMBAT_READY"
        assert readiness["combat_ready_semantics"] == "RUNTIME_READY_PRE_ENCOUNTER"
        forbidden_fragments = ("encounter", "initiative", "controller", "persisted_combat", "cpk-1")
        assert not [name for name in names if any(fragment in name.casefold() for fragment in forbidden_fragments)]


def test_repaired_gm_screen_renders_runtime_package_core_stats(tmp_path):
    gm_root = tmp_path / "gm"
    char_root = tmp_path / "character"
    with zipfile.ZipFile(GM_PACKAGE) as zf:
        zf.extractall(gm_root)
    with zipfile.ZipFile(RUNTIME_PACKAGE) as zf:
        zf.extractall(char_root)
    result = subprocess.run(
        ["node", str(ROOT / "tests/w1_gm_core_stats_check.js"), str(gm_root / "app.js"), str(char_root / "Tianxia_GM_Character_View_Model_v2.json"), str(char_root / "Tianxia_GM_Character_Model_v1.json")],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "PASS"


def test_windows_packaging_targets_repaired_gm_and_merged_identity():
    build = (ROOT / "packaging/windows_portable/Build-WindowsPortable.ps1").read_text(encoding="utf-8")
    verify = (ROOT / "packaging/windows_portable/Verify-WindowsPortable.ps1").read_text(encoding="utf-8")
    version = json.loads((ROOT / "packaging/windows_portable/VERSION.json").read_text())
    assert "HF05ZUI_R2K3_HF3_W1_CoreStats_GMScreen.zip" in build
    assert "HF05ZUI_R2K3_HF3_W1_CoreStats_GMScreen.zip" in verify
    assert "Tianxia_W5_P1_Current_Windows_Portable.zip" in build
    assert "Tianxia_W5_P1_Native_Windows_Evidence.zip" in build
    assert version["checkpoint"] == "W5_P1_CURRENT_INTEGRATED_WINDOWS_OWNER_TEST"
    assert version["predecessor_checkpoint"] == "M1_C3AR_W1_BOUNDED_MERGE"
    assert version["bundled_producer_corpus_sha256"] == "4daf167cf634f27efef4dd2f1c8700bb4b7037cc6234c32be1af90aea5916385"
    assert version["runtime_readiness"] == "COMBAT_RUNTIME_READY_PRE_ENCOUNTER"
    assert version["windows_acceptance"] is False


def test_no_cpk1_schema_registration_was_added():
    candidate_readme = (ROOT / "schemas/content_pack_candidate/README.md").read_text(encoding="utf-8")
    assert "They are not registered with the Factory" in candidate_readme
    status = json.loads((ROOT / "R6_6_9_2_M1_MERGE_STATUS.json").read_text())
    assert status["stop_boundary"]["cpk1_registered"] is False
    for base in (ROOT / "app", ROOT / "portable_character"):
        for path in base.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert "register_cpk1" not in text.casefold()
