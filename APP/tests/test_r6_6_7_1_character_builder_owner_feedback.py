from __future__ import annotations

import io
import json
import shutil
import sqlite3
import stat
import uuid
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.core import Database, FoundryError, Settings, sha256_bytes, sha256_file
from catalog.service import CatalogService
from character_builder.service import CharacterBuilderService
from character_sheet.service import CharacterSheetService
from gm_export.service import GMCharacterExportService
from projector.golden_fixture import build_authority_pack, reconstruct_project
from projector.service import ProjectionService
from stage1.service import Stage1ClipboardService
from vendor_adapter.service import FactoryAdapter

ROOT = Path(__file__).resolve().parents[1]
QI_PATH = "tianxia.path.qi_cultivation"
TEA_SAGE = "tianxia.subpath.qi.tea_sage_cultivator"
BODY_PATH = "tianxia.path.body_refining"


def _clone_catalog_db(catalog_environment: dict, data_dir: Path) -> tuple[Settings, Database]:
    settings = Settings.from_env(ROOT, data_dir)
    settings.ensure_dirs()
    source = sqlite3.connect(catalog_environment["settings"].db_path)
    target = sqlite3.connect(settings.db_path)
    source.backup(target)
    target.close(); source.close()
    source_security = catalog_environment["settings"].data_dir / "security"
    target_security = settings.data_dir / "security"
    if source_security.is_dir():
        shutil.copytree(source_security, target_security, dirs_exist_ok=True, copy_function=shutil.copy2)
    db = Database(settings); db.migrate()
    return settings, db


def _create_project(db: Database, *, name: str = "Owner Feedback Test", selections=None) -> dict:
    return CharacterBuilderService(db).create_project(
        working_name=name,
        concept="A focused owner-feedback regression character.",
        target_cl=5,
        power_band="rival/boss",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections=selections or {},
    )


def _valid_response(prompt: dict) -> tuple[str, dict]:
    envelope = prompt["envelope"]
    decisions = []
    for slot in envelope["decision_slots"]:
        required = list(slot.get("required_choice_ids") or [])
        if required:
            row = {"slot_id": slot["slot_id"], "state": "selected", "choice_ids": required}
        elif slot["coverage_state"] == "blocked_missing_authority":
            row = {
                "slot_id": slot["slot_id"], "state": "blocked_missing_authority", "choice_ids": [],
                "reason_code": slot["blocked_reason_code"], "reason": slot["blocked_reason"],
            }
        else:
            row = {
                "slot_id": slot["slot_id"], "state": "deferred_with_reason", "choice_ids": [],
                "reason_code": "deferred_future_decision",
                "reason": "Leave this choice open for later deterministic Factory compilation.",
            }
        decisions.append(row)
    response = {
        "protocol_version": "TianxiaFoundry.AIClipboard.Stage1.v2",
        "response_id": "owner.feedback." + uuid.uuid4().hex,
        "prompt_id": prompt["prompt_id"],
        "prompt_sha256": prompt["prompt_sha256"],
        "project_id": envelope["project_id"],
        "expected_project_revision": envelope["project_revision"],
        "catalog_build_id": envelope["catalog_build_id"],
        "content_lock_hash": envelope["content_lock_hash"],
        "stage_id": envelope["stage_id"],
        "response_payload": {
            "decisions": decisions,
            "authored_notes": [],
            "planner_rationale": "A conservative blueprint that leaves unlocked choices to later Factory compilation.",
        },
    }
    return json.dumps(response, sort_keys=True, separators=(",", ":")), response


def _zip_bytes(entries: list[tuple[str, bytes, int | None]]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data, mode in entries:
            info = zipfile.ZipInfo(name)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.external_attr = ((mode if mode is not None else 0o100644) & 0xFFFF) << 16
            zf.writestr(info, data)
    return out.getvalue()


def test_path_subpath_relationship_is_exact_filtered_and_fail_closed(catalog_environment):
    service = CharacterBuilderService(catalog_environment["db"])
    options = service.options()
    categories = {row["slot_id"]: row for row in options["categories"]}
    all_subpaths = {row["choice_id"]: row for row in categories["subpath_choice"]["choices"]}
    index = options["path_subpath_index"]

    assert set(index) == {"tianxia.path.body_refining", QI_PATH, "tianxia.path.spirit_awakening"}
    assert sum(len(rows) for rows in index.values()) == 156
    assert TEA_SAGE in index[QI_PATH]
    assert TEA_SAGE not in index[BODY_PATH]
    for path_id, subpath_ids in index.items():
        for subpath_id in subpath_ids:
            assert path_id in all_subpaths[subpath_id]["related_choice_ids"]
            assert all_subpaths[subpath_id]["owning_path_choice_ids"] == [path_id]
    normalized, _ = service._validated_selections({"path_choice": [QI_PATH], "subpath_choice": [TEA_SAGE]})
    assert normalized["subpath_choice"] == [TEA_SAGE]
    with pytest.raises(FoundryError) as exc:
        service._validated_selections({"path_choice": [BODY_PATH], "subpath_choice": [TEA_SAGE]})
    assert exc.value.code == "CHARACTER_SHEET_PATH_SUBPATH_MISMATCH"
    with pytest.raises(FoundryError) as exc:
        service._validated_selections({"subpath_choice": [TEA_SAGE]})
    assert exc.value.code == "CHARACTER_SHEET_SUBPATH_REQUIRES_PATH"


def test_cl_labels_use_only_authoritative_minimum_cl(catalog_environment):
    with catalog_environment["db"].connection() as conn:
        rows = conn.execute(
            """SELECT display_name,data_json FROM catalog_records
               WHERE selected_authority=1 AND display_name IN
               ('Golden Core Form','Featherfall','Meridian Reinforcement','Astral Projection')"""
        ).fetchall()
    values = {row["display_name"]: json.loads(row["data_json"])["legality"]["minimum_cl"] for row in rows}
    assert values == {
        "Golden Core Form": 10,
        "Featherfall": 7,
        "Meridian Reinforcement": 7,
        "Astral Projection": 7,
    }
    options = CharacterBuilderService(catalog_environment["db"]).options()
    subpaths = next(row for row in options["categories"] if row["slot_id"] == "subpath_choice")["choices"]
    # NS1R integrates the exact P2B selection gate: every Subpath/Tradition begins at CL3.
    assert subpaths and all(row["minimum_cl"] == 3 for row in subpaths)
    javascript = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert "Available at CL ${choice.minimum_cl}" in javascript
    assert "CL 7+" not in javascript


def test_prompt_files_preserve_exact_bytes_and_reply_paths_share_validator(catalog_environment, tmp_path):
    settings, db = _clone_catalog_db(catalog_environment, tmp_path / "file transfer")
    project = _create_project(db, selections={"path_choice": [QI_PATH], "subpath_choice": [TEA_SAGE]})
    stage1 = Stage1ClipboardService(db)
    prompt = stage1.generate_prompt(project["project_id"])
    md = stage1.save_prompt_file(prompt["prompt_id"], zipped=False)
    assert Path(md["path"]).read_bytes() == prompt["prompt_text"].encode("utf-8")
    assert sha256_file(Path(md["path"])) == prompt["prompt_sha256"]
    zipped = stage1.save_prompt_file(prompt["prompt_id"], zipped=True)
    with zipfile.ZipFile(zipped["path"]) as zf:
        assert zf.testzip() is None
        names = set(zf.namelist())
        prompt_name = next(name for name in names if name.endswith(".md") and name != "README_SEND_TO_CHATGPT.md")
        assert zf.read(prompt_name) == prompt["prompt_text"].encode("utf-8")
        assert b"reply ZIP" in zf.read("README_SEND_TO_CHATGPT.md")
        sums = zf.read("SHA256SUMS.txt").decode("utf-8")
        assert f"{prompt['prompt_sha256']}  {prompt_name}" in sums

    response_text, _ = _valid_response(prompt)
    direct = stage1.validate_response(prompt["prompt_id"], response_text)
    loaded_json = stage1.load_reply_file("Factory_Character_Plan_Response.json", response_text.encode("utf-8"))
    loaded_md = stage1.load_reply_file("reply.md", response_text.encode("utf-8"))
    loaded_zip = stage1.load_reply_zip(
        "reply.zip",
        _zip_bytes([("Factory_Character_Plan_Response.json", response_text.encode("utf-8"), None)]),
    )
    assert loaded_json["response_text"] == loaded_md["response_text"] == loaded_zip["response_text"] == response_text
    repeat = stage1.validate_response(prompt["prompt_id"], loaded_zip["response_text"])
    assert direct["validation"]["valid"] is True
    assert repeat["validation"]["valid"] is True
    assert repeat["attempt_id"] == direct["attempt_id"]
    assert repeat["idempotent"] is True


def test_reply_zip_rejects_traversal_collisions_links_and_ambiguity(catalog_environment, tmp_path):
    _settings, db = _clone_catalog_db(catalog_environment, tmp_path / "zip attacks")
    stage1 = Stage1ClipboardService(db)
    cases = [
        _zip_bytes([("../reply.json", b"{}", None)]),
        _zip_bytes([("Reply.json", b"{}", None), ("reply.JSON", b"{}", None)]),
        _zip_bytes([("one.json", b"{}", None), ("two.md", b"{}", None)]),
        _zip_bytes([("reply.json", b"{}", stat.S_IFLNK | 0o777)]),
    ]
    for payload in cases:
        with pytest.raises(FoundryError):
            stage1.load_reply_zip("unsafe.zip", payload)


def test_stage1_commit_is_plainly_a_blueprint_and_survives_restart(catalog_environment, tmp_path):
    _settings, db = _clone_catalog_db(catalog_environment, tmp_path / "blueprint sheet")
    created = _create_project(db, name="Readable Blueprint", selections={"path_choice": [QI_PATH], "subpath_choice": [TEA_SAGE]})
    stage1 = Stage1ClipboardService(db)
    prompt = stage1.generate_prompt(created["project_id"])
    response_text, _ = _valid_response(prompt)
    checked = stage1.validate_response(prompt["prompt_id"], response_text)
    assert checked["validation"]["valid"] is True
    committed = stage1.approve_and_commit(checked["attempt_id"], "owner")
    assert committed.get("commit") and committed["commit"]["projection_status"] == "projected"

    first = CharacterSheetService(db).sheet(created["project_id"])
    second = CharacterSheetService(Database(db.settings)).sheet(created["project_id"])
    assert first == second
    assert first["build_status"] == "BLUEPRINT"
    assert first["identity"]["path"] == "Qi Cultivation"
    assert first["identity"]["subpath"] == "Tea-Sage Cultivator"
    assert first["provenance"]["ai_blueprint"]["label"] == "Accepted character plan"
    assert first["provenance"]["mechanical_projection"]["label"] == "Not compiled yet"
    assert all(section["label"] == "Not compiled yet" for section in first["sections"].values())
    assert first["gm_export"]["available"] is False
    status = GMCharacterExportService(db).status(created["project_id"])
    assert status["available"] is False
    assert any("mechanical projection" in item for item in status["blockers"])


def test_owner_ui_is_nontechnical_and_packaging_includes_gm_authority():
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    css = (ROOT / "static/styles.css").read_text(encoding="utf-8")
    spec = (ROOT / "packaging/windows_portable/TianxiaFactory.spec").read_text(encoding="utf-8")
    assert "Character Sheets" in html
    assert "My Characters" not in html
    assert '<div id="sheetPaths" class="path-choice-list"></div>' in html
    assert "Choose a Starting Path first." in js
    assert "The selected Method must support every selected Path." in js
    assert "Download Complete Request ZIP" in html
    assert "Attach it to a new ChatGPT conversation." in html
    assert "return one complete response ZIP or JSON" in html
    assert 'id="guidedDownloadCompleteRequest"' in html
    assert 'id="guidedCompleteReplyFile"' in html
    assert 'id="guidedCompleteResponseText"' in html
    assert 'id="guidedSubmitCompleteResponse"' in html
    assert "Build Complete Candidate" in html
    assert "Finalizing through the accepted atomic pipeline" in js
    assert "The accepted server-derived local principal approved the canonical commit" in html
    assert "Not compiled yet" in js
    assert "Not present for this stage" in js
    assert "Export Character ZIP for GM Screen" in html
    assert "advanced-project-tools" in html and "Advanced project tools" in html
    assert "@media (max-width: 950px)" in css
    assert '(str(ROOT / "gm_screen"), "gm_screen")' in spec
    assert (ROOT / "gm_screen/HF05ZUI_R2K3_HF3_W1_CoreStats_GMScreen.zip").is_file()
    # Static guard: every HTML ID is unique.
    import re
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids))


def test_complete_fixture_exports_exact_gm_zip_and_passes_bundled_importer(factory_zip, tmp_path):
    settings = Settings.from_env(ROOT, tmp_path / "gm export complete fixture")
    db = Database(settings); db.migrate()
    configured = FactoryAdapter(db).configure(factory_zip)
    CatalogService(db).rebuild_core(Path(configured["factory_root"]))
    fixture_root = Path(configured["fixture_path"])
    authority = tmp_path / "golden_authority.zip"
    build_authority_pack(fixture_root=fixture_root, output_zip=authority, work_dir=tmp_path / "authority_work")
    project = reconstruct_project(
        db=db,
        fixture_root=fixture_root,
        authority_pack_zip=authority,
        working_name="Owner Feedback GM Export Fixture",
    )
    built = ProjectionService(db).build(project["project_id"])
    assert built["status"] == "READY" and built["eligible_for_command5"] is True
    sheet = CharacterSheetService(db).sheet(project["project_id"])
    assert sheet["build_status"] == "GM_READY"
    result = GMCharacterExportService(db).export(project["project_id"])
    assert result["gm_screen_import_validation"]["status"] == "SIMULATED_CONSUMER_PASS_REAL_GMSCREEN_ACCEPTANCE_REQUIRED"
    assert result["real_installed_gm_screen_acceptance"] is False
    assert result["identity"] == {
        "name": sheet["name"], "ledger_name": sheet["name"], "gm_model_name": sheet["name"]
    }
    path = Path(result["path"])
    assert path.is_file() and sha256_file(path) == result["sha256"]
    with zipfile.ZipFile(path) as zf:
        assert zf.testzip() is None
        names = [name for name in zf.namelist() if not name.endswith("/")]
        declared = {}
        for line in zf.read("SHA256SUMS.txt").decode("utf-8").splitlines():
            digest, name = line.split("  ", 1); declared[name] = digest
        assert set(declared) == set(names) - {"SHA256SUMS.txt"}
        assert all(sha256_bytes(zf.read(name)) == digest for name, digest in declared.items())
