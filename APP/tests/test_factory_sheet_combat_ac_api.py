"""Real Factory GETs on retained Hunt 50 input, never live data.

Private evidence is not committed: L37_AC_CSV / L37_PORTABLE_ROOT override its
location; cases skip when absent. The fixture seeds archived projections and
the unaltered sealed snapshot, not a fabricated route response. Sheet loading,
endpoint enrichment and compilation are real. SOL37_TEST_UVLOOP=1 optionally
selects uvloop for sandboxes with broken asyncio cross-thread wakeups.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import shutil
import sqlite3
import statistics
import time
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.core import CORE_PACK_ID, CORE_PACK_VERSION, Settings, sha256_file
from combat.tabletop import ButtonStore
from factory_authoring.owner_items import OwnerItemStore, armour_choices

ROOT = Path(__file__).resolve().parents[1]
AC_CSV = Path(os.environ.get("L37_AC_CSV", "/var/tmp/auto-audit/fix/LUNA37-ac.csv"))
PORTABLE_ROOT = Path(os.environ.get(
    "L37_PORTABLE_ROOT", "/var/tmp/auto-audit/astra/lock3-inputs/portable_characters"))
CLIENT_OPTIONS = {"backend_options": {"use_uvloop": True}} if os.environ.get("SOL37_TEST_UVLOOP") == "1" else {}
OWNER_SHEET = "Tianxia_Owner_Character_Sheet_v1.json"


@pytest.fixture(autouse=True)
def isolated_display_state(monkeypatch):
    import app.api as api
    import combat.display_values as display

    monkeypatch.setattr(display, "_AC_CACHE", {})
    monkeypatch.setattr(api, "_COMBAT_AC_FAILURES", set(), raising=False)


def _app_with_character(tmp_path: Path, catalog_environment, row=None):
    if not AC_CSV.is_file():
        pytest.skip("Retained L37 CSV is required (L37_AC_CSV).")
    if row is None:
        with AC_CSV.open(newline="", encoding="utf-8") as stream:
            row = next(row for row in csv.DictReader(stream) if int(row["compiled_ac"]) > int(row["sheet_ac"]))
    project_id = row["portable_package"]
    source = PORTABLE_ROOT / project_id / "current.zip"
    if not source.is_file():
        pytest.skip(f"Retained L37 portable package is required: {source}")
    settings = Settings.from_env(ROOT, tmp_path / "data")
    settings.ensure_dirs()
    with sqlite3.connect(catalog_environment["settings"].db_path) as source_db:
        with sqlite3.connect(settings.db_path) as target_db:
            source_db.backup(target_db)
    shutil.copytree(catalog_environment["settings"].data_dir / "security",
                    settings.data_dir / "security", dirs_exist_ok=True)
    app = create_app(settings)
    with app.state.db.connection() as conn:
        pack = conn.execute("SELECT pack_hash FROM content_packs WHERE pack_id=? AND version=?",
                            (CORE_PACK_ID, CORE_PACK_VERSION)).fetchone()
    assert pack is not None
    app.state.projects.create_project(
        working_name=row["character"],
        pack_locks=[{"pack_id": CORE_PACK_ID, "version": CORE_PACK_VERSION, "pack_hash": pack["pack_hash"]}],
        user_locks=[], project_id_override=project_id,
    )
    installed = app.state.combat.combatant_library.install_root / project_id
    installed.mkdir(parents=True)
    shutil.copy2(source, installed / "current.zip")
    with zipfile.ZipFile(source) as archive:
        sealed_bytes = archive.read(OWNER_SHEET)
        sealed = json.loads(sealed_bytes)
        authority = sealed["authority_and_artifact_identity"]
        projection_id = authority["projection_id"]
        generated = settings.data_dir / "projects" / project_id / "projections" / projection_id / "generated"
        generated.mkdir(parents=True)
        for name, digest in authority["advancement_artifact_hashes"].items():
            path = generated / name
            path.write_bytes(archive.read("source/advancement_projection/" + name))
            assert sha256_file(path) == digest
    # Saved-sheet fixture, not project-import/creation coverage. Match its
    # revision in the disposable project; never alter sealed snapshot bytes.
    with app.state.db.transaction() as conn:
        project = json.loads(conn.execute("SELECT project_json FROM projects WHERE project_id=?", (project_id,)).fetchone()[0])
        project["revision"] = authority["project_revision"]
        conn.execute("UPDATE projects SET project_json=? WHERE project_id=?", (json.dumps(project), project_id))
        conn.execute(
            """INSERT INTO projection_runs(projection_id,project_id,project_revision,content_lock_hash,
            event_head_hash,status,generated_dir,created_at) VALUES(?,?,?,?,?,?,?,?)""",
            (projection_id, project_id, authority["project_revision"], authority["content_lock_hash"],
             authority["event_head_hash"], "READY", str(generated), "2026-01-01T00:00:00Z"),
        )
        for name, digest in authority["advancement_artifact_hashes"].items():
            path = generated / name
            conn.execute("INSERT INTO projection_artifacts VALUES(?,?,?,?,?,?)",
                         (projection_id, name, str(path), digest, path.stat().st_size, "application/json"))
    sealed_path = settings.data_dir / "character_sheets" / project_id / sealed["sheet_id"] / OWNER_SHEET
    sealed_path.parent.mkdir(parents=True)
    sealed_path.write_bytes(sealed_bytes)
    sealed_path.with_suffix(".json.sha256").write_text(f"{sha256_file(sealed_path)}  {OWNER_SHEET}\n")
    return app, row, project_id, sealed, sealed_path


def _sheet_get(client, project_id: str):
    response = client.get(f"/api/characters/{project_id}/sheet")
    assert response.status_code == 200, response.text
    return response.json()


def _assert_preserved(result, baseline, sealed):
    assert result["owner_character_sheet"] == sealed == baseline["owner_character_sheet"]
    actual = deepcopy(result["sections"]["abilities_statistics"]["data"])
    actual.pop("combat_armor_class")
    assert actual == baseline["sections"]["abilities_statistics"]["data"]
    assert actual["armor_class"]["value"] == sealed["ability_scores_and_statistics"]["armor_class"]["value"]
    assert len(actual) > 1  # populated statistics, not the empty JS fixture


def test_factory_sheet_get_exposes_compiled_ac_and_preserves_snapshot(tmp_path, catalog_environment):
    app, row, project_id, sealed, path = _app_with_character(tmp_path, catalog_environment)
    sealed_bytes = path.read_bytes()
    baseline = app.state.character_sheets.sheet(project_id)
    with TestClient(app, **CLIENT_OPTIONS) as client:
        result = _sheet_get(client, project_id)
    assert result["sections"]["abilities_statistics"]["data"]["combat_armor_class"]["value"] == int(row["compiled_ac"])
    assert int(row["compiled_ac"]) > int(row["sheet_ac"])
    _assert_preserved(result, baseline, sealed)
    assert path.read_bytes() == sealed_bytes


def test_factory_sheet_get_keeps_sheet_available_when_combat_ac_compile_fails(
    tmp_path, catalog_environment, monkeypatch, caplog
):
    app, _row, project_id, sealed, path = _app_with_character(tmp_path, catalog_environment)
    sealed_bytes = path.read_bytes()
    baseline = app.state.character_sheets.sheet(project_id)
    calls = 0

    def fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("fixture compilation failure")

    import combat.factory_compiler as compiler

    monkeypatch.setattr(compiler, "compile_character", fail)
    with caplog.at_level(logging.WARNING), TestClient(app, **CLIENT_OPTIONS) as client:
        for _ in range(3):
            result = _sheet_get(client, project_id)
            assert result["sections"]["abilities_statistics"]["data"]["combat_armor_class"] == {
                "value": None, "tooltip": "AC from combat unavailable."}
            _assert_preserved(result, baseline, sealed)
    assert calls == 3  # actual compiler failure, not a patched display helper
    warnings = [r for r in caplog.records if "Compiled AC unavailable for character" in r.message]
    assert len(warnings) == 1
    assert warnings[0].levelno == logging.WARNING
    assert "fixture compilation failure" in warnings[0].message
    assert path.read_bytes() == sealed_bytes


def test_factory_sheet_get_cache_tracks_worn_equipment_and_saved_settings(
    tmp_path, catalog_environment, monkeypatch
):
    app, row, project_id, sealed, _path = _app_with_character(tmp_path, catalog_environment)
    baseline = app.state.character_sheets.sheet(project_id)
    calls = 0
    import combat.factory_compiler as compiler

    original = compiler.compile_character

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(compiler, "compile_character", counted)
    store = OwnerItemStore(app.state.combat.userdata_root / "owner_items")
    buttons = ButtonStore(app.state.settings.data_dir / "tabletop_buttons")
    buttons.save_left_behind(project_id, [])  # normalize default saved settings before counting
    chassis = "tianxia.mortal.armor.beast_hide_harness"
    material = armour_choices(chassis, "Saint", None, [])["material_id"]
    with TestClient(app, **CLIENT_OPTIONS) as client:
        def expect(value, compiles):
            for _ in range(2):
                result = _sheet_get(client, project_id)
                assert result["sections"]["abilities_statistics"]["data"]["combat_armor_class"]["value"] == value
                _assert_preserved(result, baseline, sealed)
                assert calls == compiles

        expect(int(row["compiled_ac"]), 1)
        armor = store.give(project_id, {"kind": "armour", "chassis_id": chassis,
                                       "grade": "Saint", "material_id": material})
        assert armor["record"]["refinement_bonus"] == 2
        expect(int(row["compiled_ac"]), 2)  # Worse armour remains carried; refinement grants no AC.
        buttons.save_left_behind(project_id, ["given.0"])
        expect(int(row["compiled_ac"]), 3)
        buttons.save_left_behind(project_id, [])
        expect(int(row["compiled_ac"]), 3)  # previously cached exact revision
        store.remove(project_id, armor["item_uid"])
        expect(int(row["compiled_ac"]), 3)
        buttons.save_attunement(project_id, [])
        expect(int(row["compiled_ac"]), 4)  # Carried armour grants no refinement, even when attuned.
        buttons.save_attunement(project_id, None)
        expect(int(row["compiled_ac"]), 4)


@pytest.mark.skipif(os.environ.get("L37_SHEET_BENCHMARK") != "1", reason="opt-in real GET benchmark")
def test_factory_sheet_get_timings(tmp_path, catalog_environment, monkeypatch):
    """First-request cold and five warm GETs, including HTTP JSON serialization."""
    if not PORTABLE_ROOT.is_dir() or not AC_CSV.is_file():
        pytest.skip("Retained L37 benchmark inputs are required.")
    sizes = []
    for path in PORTABLE_ROOT.glob("*/current.zip"):
        with zipfile.ZipFile(path) as archive:
            sizes.append((archive.getinfo(OWNER_SHEET).file_size, path.parent.name,
                          sum(item.file_size for item in archive.infolist())))
    sheet_bytes, project_id, package_bytes = max(sizes)
    with AC_CSV.open(newline="", encoding="utf-8") as stream:
        row = next(row for row in csv.DictReader(stream) if row["portable_package"] == project_id)
    app, row, project_id, sealed, path = _app_with_character(tmp_path, catalog_environment, row)
    calls = 0
    import combat.factory_compiler as compiler

    original = compiler.compile_character

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(compiler, "compile_character", counted)
    samples = []
    response_bytes = 0
    with TestClient(app, **CLIENT_OPTIONS) as client:
        for _ in range(6):
            started = time.perf_counter()
            response = client.get(f"/api/characters/{project_id}/sheet")
            samples.append((time.perf_counter() - started) * 1000)
            assert response.status_code == 200, response.text
            result = response.json()  # outside timer; serialization remains inside
            assert result["owner_character_sheet"] == sealed
            response_bytes = len(response.content)
    assert json.loads(path.read_bytes()) == sealed
    stats = result["sections"]["abilities_statistics"]["data"]
    print("L37_TIMING " + json.dumps({
        "ref": os.environ.get("L37_BENCHMARK_REF", "HEAD"),
        "character": row["character"], "level": sealed["identity"]["cultivation_level"],
        "available_characters": len(sizes), "sealed_sheet_bytes": sheet_bytes,
        "expanded_package_bytes": package_bytes, "response_bytes": response_bytes,
        "display_ac": stats.get("combat_armor_class", stats["armor_class"])["value"],
        "cold_ms": samples[0], "warm_ms": samples[1:],
        "warm_median_ms": statistics.median(samples[1:]), "compiles": calls,
    }, sort_keys=True))
