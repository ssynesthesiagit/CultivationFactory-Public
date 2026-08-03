from __future__ import annotations

import hashlib
import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from app.core import Database, canonical_json, sha256_file
from combat.canonical import canonical_sha256
from combat.gate5_service import CombatService, CombatServiceError
from contracts.canonical import canonical_project_hash
from portable_character.service import PortableCharacterPackageService

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PACKAGE = ROOT / "tests/fixtures/M1/C1A_Clean_Fire_Qi_Proof_Character_Combat_Runtime_Ready.zip"
RUNTIME_SHA = "1bc4142ccda1c51ba9972c5938a50043ee0de0fd0b1e2cd8d62dc838e623fddd"
PROJECT_ID = "6a64af8e-7b8f-447b-bd81-fe4432b048c2"
DYNAMIC_ACTOR_ID = "portable-character:1583fb60ac3442eb2c7ddd8f"
BUILTIN_OPPONENT = "lee_jia_early_book1_cl5"


def _raw_project(package: Path = RUNTIME_PACKAGE) -> dict:
    with zipfile.ZipFile(package) as outer:
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


def _import_runtime(monkeypatch, db: Database, tmp_path: Path) -> tuple[dict, dict]:
    from character_sheet.service import CharacterSheetService
    from product_bootstrap.service import ProductReadinessService
    from projector.service import ProjectionService
    from vendor_adapter.service import FactoryAdapter

    service = PortableCharacterPackageService(db)
    monkeypatch.setattr(ProductReadinessService, "report", lambda _self: {"portable_import": {"ready": True}, "blocking_reasons": []})
    project = _raw_project()
    with zipfile.ZipFile(RUNTIME_PACKAGE) as zf:
        manifest = json.loads(zf.read("PACKAGE_MANIFEST.json"))
        expected_sheet_sha = hashlib.sha256(zf.read("Tianxia_Owner_Character_Sheet_v1.json")).hexdigest()

    def fake_project_import(_nested: Path) -> dict:
        _insert_project(db, project)
        return {"status": "IMPORTED", "project_id": project["project_id"], "revision": project["revision"]}

    monkeypatch.setattr(service.projects, "import_project", fake_project_import)
    monkeypatch.setattr(FactoryAdapter, "status", lambda _self: {"configured": True, "health": "READY", "factory_root": str(tmp_path / "Factory Root")})
    monkeypatch.setattr(
        ProjectionService,
        "build",
        lambda _self, project_id, force=True: {
            "status": "READY", "projection_id": "c3d-p1-test-projection",
            "artifacts": [{"artifact_name": name, "sha256": digest} for name, digest in manifest["advancement_projection_references"].items()],
        },
    )
    monkeypatch.setattr(
        CharacterSheetService,
        "sheet",
        lambda _self, project_id, compact=False: {"build_status": "CHARACTER_SHEET_READY", "sheet_artifact": {"sha256": expected_sheet_sha}},
    )
    first = service.import_into_factory(RUNTIME_PACKAGE)
    second = service.import_into_factory(RUNTIME_PACKAGE)
    return first, second


def _catalog_payload(service: CombatService, *, include_dynamic: bool = True, dynamic_mode: str = "MANUAL", builtin_mode: str = "MANUAL", maximum_rounds: int = 2) -> dict:
    catalog = service.catalog()
    dynamic = next(row for row in catalog["projections"] if row.get("installed_character"))
    builtin = next(row for row in catalog["projections"] if row["runtime_entity_id"] == BUILTIN_OPPONENT)
    participants = [
        {
            "actor_id": BUILTIN_OPPONENT,
            "team_id": "team:opponent",
            "controller_mode": builtin_mode,
            "placement": {"x": 17, "y": 4},
            "footprint_width": 1,
            "footprint_height": 1,
            "token_asset_id": builtin["character_sheet_identity"],
            "stamina_current": 0,
            "qi_current": 0,
            "resonance_current": 0,
            "martial_focus_current": None,
        }
    ]
    if include_dynamic:
        participants.insert(0, {
            "actor_id": dynamic["runtime_entity_id"],
            "team_id": "team:owner",
            "controller_mode": dynamic_mode,
            "placement": {"x": 2, "y": 4},
            "footprint_width": 1,
            "footprint_height": 1,
            "token_asset_id": dynamic["character_sheet_identity"],
            "qi_current": 15,
            "martial_focus_current": 1,
            "stamina_current": 0,
            "resonance_current": 0,
        })
    else:
        other = next(row for row in catalog["projections"] if row["runtime_entity_id"] == "ling_qi_early_outer_sect_cl5")
        participants.append({
            "actor_id": other["runtime_entity_id"], "team_id": "team:owner", "controller_mode": "MANUAL",
            "placement": {"x": 2, "y": 4}, "footprint_width": 1, "footprint_height": 1,
            "token_asset_id": other["character_sheet_identity"], "stamina_current": 0, "qi_current": 0,
            "resonance_current": 0, "martial_focus_current": None,
        })
    battlefield = catalog["battlefields"][0]
    return {
        "encounter_id": catalog["encounters"][0]["stable_id"],
        "battlefield_id": battlefield["stable_id"],
        "display_name": "C3D-P1 portable live combat acceptance",
        "match_seed": "C3D-P1-FOCUSED-ACCEPTANCE" if include_dynamic else "C3D-P1-OMITTED-CANDIDATE",
        "initiative_method": "DETERMINISTIC_ACCEPTED",
        "maximum_rounds": maximum_rounds,
        "grid_calibration": {
            "mode": "AUTHORITATIVE_GATE2_GRID", "width": battlefield["width_squares"],
            "height": battlefield["height_squares"], "square_size_ft": battlefield["square_size_ft"],
            "centered_tokens": True,
        },
        "team_names": {"team:owner": "Owner Flame", "team:opponent": "Existing Spark"},
        "participants": participants,
    }


def _intent_from_candidate(context: dict, candidate: dict) -> dict:
    return {
        "decision_id": context["decision_id"],
        "state_version": context["state_version"],
        "candidate_id": candidate["candidate_id"],
        "actor_id": candidate["actor_id"],
        "target_ids": candidate.get("target_ids") or [],
        "destination": candidate.get("destination"),
        "option_ids": candidate.get("option_ids") or [],
    }


def _preview_commit(service: CombatService, match_id: str, intent: dict) -> dict:
    reactions: list[dict] = []
    for _ in range(12):
        preview = service.preview(match_id, intent, reactions)
        if preview["status"] == "REACTION_REQUIRED":
            context = preview["reaction_context"]
            reactions.append({
                "checkpoint": context["checkpoint"],
                "reactor_id": context["reactor_id"],
                "reaction_source_id": context["reaction_source_id"],
                "selection": "DECLINE", "spend": 0, "option_ids": [],
            })
            continue
        assert preview["status"] == "PREVIEW_COMPLETE"
        return service.submit_intent(match_id, intent, reactions, preview["preview_id"])
    raise AssertionError("reaction preview exceeded bounded checkpoints")


def _manual_end_turn(service: CombatService, match_id: str) -> None:
    decision = service.decision(match_id)
    context = decision["context"]
    candidate = next(row for row in context["legal_candidates"] if row["kind"] == "END_TURN")
    _preview_commit(service, match_id, _intent_from_candidate(context, candidate))


def _complete_local(service: CombatService, match_id: str) -> None:
    match = service.get_match(match_id)
    for actor in match["state"]["actors"]:
        if actor["primary_combatant"]:
            service.set_controller_mode(match_id, actor_id=actor["entity_id"], controller_mode="LOCAL_AUTO")
    for _ in range(100):
        if service.get_match(match_id)["state"]["terminal_result"] is not None:
            return
        service.local_step(match_id)
    raise AssertionError("the bounded encounter did not reach a terminal result")


def _install_pointer(data_root: Path, package: Path, *, pointer_project_id: str = PROJECT_ID, pointer_hash: str | None = None) -> Path:
    root = data_root / "portable_characters" / pointer_project_id
    root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(package, root / "current.zip")
    pointer = {
        "schema_version": "TianxiaFoundry.PortableCharacterVerificationPointer.v1",
        "project_id": pointer_project_id,
        "status": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED",
        "package_path": str((root / "current.zip").resolve()),
        "package_sha256": pointer_hash or sha256_file(package),
    }
    (root / "current.json").write_text(canonical_json(pointer), encoding="utf-8")
    return root


def _rewrite_package(source: Path, destination: Path, mutate) -> Path:
    with zipfile.ZipFile(source) as zf:
        files = {name: zf.read(name) for name in zf.namelist() if not name.endswith("/")}
    mutate(files)
    manifest = json.loads(files["PACKAGE_MANIFEST.json"])
    manifest["files"] = [
        {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in sorted(files.items())
        if name not in {"PACKAGE_MANIFEST.json", "SHA256SUMS.txt"}
    ]
    files["PACKAGE_MANIFEST.json"] = canonical_json(manifest).encode("utf-8")
    files["SHA256SUMS.txt"] = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n"
        for name, data in sorted(files.items()) if name != "SHA256SUMS.txt"
    ).encode("utf-8")
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name, data in sorted(files.items()):
            zf.writestr(name, data)
    return destination


def test_c3d_p1_import_install_dynamic_lifecycle_restart_and_legal_export(monkeypatch, fresh_db, tmp_path):
    assert sha256_file(RUNTIME_PACKAGE) == RUNTIME_SHA
    first, second = _import_runtime(monkeypatch, fresh_db, tmp_path)
    assert first["status"] == "IMPORTED"
    assert first["readiness"]["combat"] == "COMBAT_READY"
    assert second["status"] == "ALREADY_INSTALLED_IDENTICAL"
    installed = fresh_db.settings.data_dir / "portable_characters" / PROJECT_ID / "current.zip"
    assert sha256_file(installed) == RUNTIME_SHA
    with fresh_db.connection() as conn:
        project_before = conn.execute("SELECT project_json FROM projects WHERE project_id=?", (PROJECT_ID,)).fetchone()[0]

    service = CombatService(ROOT, fresh_db.settings.data_dir)
    catalog = service.catalog()
    installed_rows = [row for row in catalog["projections"] if row.get("installed_character")]
    assert len(installed_rows) == 1
    candidate = installed_rows[0]
    assert candidate["runtime_entity_id"] == DYNAMIC_ACTOR_ID
    assert candidate["owner_status"] == "Combat Ready"
    assert candidate["source_package_sha256"] == RUNTIME_SHA
    assert catalog["c3c_p1_setup_authority"][DYNAMIC_ACTOR_ID]["resources"]["martial_focus"]["maximum"] == 1

    payload = _catalog_payload(service)
    preflight = service.preflight_new_fight(payload)
    assert preflight["ready"] is True and preflight["blockers"] == []
    portable_setup = next(row for row in preflight["participants"] if row["actor_id"] == DYNAMIC_ACTOR_ID)
    assert portable_setup["source_authority"]["package_sha256"] == RUNTIME_SHA
    assert portable_setup["starting_resources"]["qi"] == 15
    assert portable_setup["starting_resources"]["martial_focus"] == 1
    assert preflight["read_only"] is True and preflight["persisted_combat_events"] == 0

    create = {**payload, "owner_confirmed": True, "preflight_commitment": preflight["preflight_commitment"], "idempotency_key": "c3d-p1-focused-create"}
    created = service.create_confirmed_fight(create)
    match_id = created["match_id"]
    identical = service.create_confirmed_fight(create)
    assert identical["match_id"] == match_id
    assert len(service.list_matches()) == 1
    match_dir = service._match_dir(match_id)
    assert sha256_file(match_dir / "SourceCharacterPackage.zip") == RUNTIME_SHA
    authority = json.loads((match_dir / "PortableRuntimeAuthority.json").read_text())
    assert authority["runtime_actor_id"] == DYNAMIC_ACTOR_ID
    lock = json.loads((match_dir / "MatchLock.json").read_text())
    match_content = {row["relative_path"]: row for row in lock["content_identities"] if row.get("authority_scope") == "MATCH"}
    assert match_content["SourceCharacterPackage.zip"]["sha256"] == RUNTIME_SHA
    assert "PortableRuntimeAuthority.json" in match_content
    with pytest.raises(CombatServiceError) as not_final:
        service.export(match_id)
    assert not_final.value.diagnostic.code == "COMBAT_MATCH_NOT_COMPLETE"

    # Manual is the setup default. End the built-in's first turn if it won initiative.
    if service.get_match(match_id)["state"]["current_actor_id"] != DYNAMIC_ACTOR_ID:
        _manual_end_turn(service, match_id)
    assert service.get_match(match_id)["state"]["current_actor_id"] == DYNAMIC_ACTOR_ID

    # Execute one imported package mechanic manually through Gate 2/Gate 4 persistence.
    decision = service.decision(match_id)
    context = decision["context"]
    burning = next(row for row in context["legal_candidates"] if row["source_definition_id"] == "action:fire.burning_weapon")
    _preview_commit(service, match_id, _intent_from_candidate(context, burning))
    dynamic_state = next(row for row in service.get_match(match_id)["state"]["actors"] if row["entity_id"] == DYNAMIC_ACTOR_ID)
    assert dynamic_state["resources"]["resource:core.qi"] == 14
    assert any(
        row.get("condition_id") == "condition:fire.burning_weapon"
        for row in dynamic_state["conditions"].values()
    )

    # One owner-approved Suggested decision, then Local Auto may finish.
    service.set_controller_mode(match_id, actor_id=DYNAMIC_ACTOR_ID, controller_mode="SUGGESTED")
    suggestion = service.suggest(match_id)
    _preview_commit(service, match_id, suggestion["intent"])
    _complete_local(service, match_id)

    complete = service.get_match(match_id)
    assert complete["state"]["terminal_result"]["kind"] in {"VICTORY", "DRAW_DURATION"}
    journal = [json.loads(line) for line in (match_dir / "Journal.ndjson").read_text().splitlines() if line.strip()]
    assert sum(1 for row in journal if row.get("record_type") == "MATCH_FINALIZED") == 1
    summary_before = service.final_summary(match_id)
    assert summary_before["portable_character_authority"]["package_sha256"] == RUNTIME_SHA
    assert summary_before["battlefield_id"] == "battlefield:sect_training_court"
    assert summary_before["teams"] == {"team:opponent": "Existing Spark", "team:owner": "Owner Flame"}
    assert service.verify(match_id)["status"] == "PASS"
    replay_before = service.replay(match_id)
    assert replay_before["status"] == "PASS"
    assert replay_before["canonical_state_sha256"] == summary_before["final_state_sha256"]

    restarted = CombatService(ROOT, fresh_db.settings.data_dir)
    reopened = restarted.get_match(match_id)
    assert reopened["state"]["terminal_result"] == complete["state"]["terminal_result"]
    assert restarted.final_summary(match_id) == summary_before
    assert restarted.verify(match_id)["status"] == "PASS"
    assert restarted.replay(match_id)["canonical_state_sha256"] == summary_before["final_state_sha256"]
    with pytest.raises(CombatServiceError) as read_only:
        restarted.local_step(match_id)
    assert read_only.value.diagnostic.code == "COMBAT_MATCH_ALREADY_COMPLETE"

    export_path = restarted.export(match_id)
    with zipfile.ZipFile(export_path) as zf:
        assert zf.testzip() is None
        names = {name for name in zf.namelist() if not name.endswith("/")}
        required = {
            "SourceCharacterPackage.zip", "PortableRuntimeAuthority.json", "FinalSummary.json",
            "FinalVerification.json", "ExportAuthority.json", "Journal.ndjson", "ControllerJournal.ndjson",
            "Exports/Gate3_Event_Log.json", "Exports/Gate3_Roll_Log.json", "Exports/Gate3_Replay_Result.json",
            "SHA256SUMS.txt",
        }
        assert required.issubset(names)
        sums = {
            name: digest
            for digest, name in (
                line.split("  ", 1)
                for line in zf.read("SHA256SUMS.txt").decode().splitlines()
                if line
            )
        }
        assert set(sums) == names - {"SHA256SUMS.txt"}
        assert all(hashlib.sha256(zf.read(name)).hexdigest() == digest for name, digest in sums.items())
        export_authority = json.loads(zf.read("ExportAuthority.json"))
        assert export_authority["status"] == "LEGAL_FINAL_COMBAT_EXPORT"
        assert export_authority["source_package"]["package_sha256"] == RUNTIME_SHA
        assert export_authority["finalization_record_count"] == 1
        assert all(export_authority[key] is False for key in (
            "contains_character_advancement", "contains_rewards", "contains_injuries", "contains_loot",
            "contains_narrative", "native_windows_acceptance_claimed",
        ))

    assert sha256_file(installed) == RUNTIME_SHA
    with fresh_db.connection() as conn:
        project_after = conn.execute("SELECT project_json FROM projects WHERE project_id=?", (PROJECT_ID,)).fetchone()[0]
    assert project_after == project_before


def test_c3d_p1_omitted_installed_candidate_never_enters_match(tmp_path):
    _install_pointer(tmp_path, RUNTIME_PACKAGE)
    service = CombatService(ROOT, tmp_path)
    payload = _catalog_payload(service, include_dynamic=False)
    preflight = service.preflight_new_fight(payload)
    assert preflight["ready"] is True
    created = service.create_confirmed_fight({
        **payload, "owner_confirmed": True, "preflight_commitment": preflight["preflight_commitment"],
        "idempotency_key": "c3d-p1-omitted-create",
    })
    match_dir = service._match_dir(created["match_id"])
    assert DYNAMIC_ACTOR_ID not in {row["entity_id"] for row in created["state"]["actors"]}
    assert not (match_dir / "PortableRuntimeAuthority.json").exists()
    assert not (match_dir / "SourceCharacterPackage.zip").exists()
    assert DYNAMIC_ACTOR_ID not in (match_dir / "GenesisState.json").read_text()
    assert DYNAMIC_ACTOR_ID not in (match_dir / "Journal.ndjson").read_text()


def test_c3d_p1_preflight_resources_fail_closed_and_make_no_match(tmp_path):
    _install_pointer(tmp_path, RUNTIME_PACKAGE)
    service = CombatService(ROOT, tmp_path)
    base = _catalog_payload(service)
    dynamic = next(row for row in base["participants"] if row["actor_id"] == DYNAMIC_ACTOR_ID)
    cases = [
        ({"qi_current": None, "martial_focus_current": None}, "C3D_CURRENT_RESOURCE_INITIALIZATION_REQUIRED"),
        ({"qi_current": -1, "martial_focus_current": 1}, "C3D_RESOURCE_INITIALIZATION_INVALID"),
        ({"qi_current": 16, "martial_focus_current": 1}, "C3D_RESOURCE_INITIALIZATION_INVALID"),
        ({"qi_current": 15, "martial_focus_current": -1}, "C3D_RESOURCE_INITIALIZATION_INVALID"),
        ({"qi_current": 15, "martial_focus_current": 2}, "C3D_RESOURCE_INITIALIZATION_INVALID"),
    ]
    for updates, code in cases:
        dynamic.update(updates)
        report = service.preflight_new_fight(base)
        assert report["ready"] is False
        assert code in {row["code"] for row in report["blockers"]}
        dynamic.update({"qi_current": 15, "martial_focus_current": 1})
    assert service.list_matches() == []


def test_c3d_p1_stale_or_changed_installed_source_fails_before_genesis(tmp_path):
    root = _install_pointer(tmp_path, RUNTIME_PACKAGE)
    service = CombatService(ROOT, tmp_path)
    payload = _catalog_payload(service)
    preflight = service.preflight_new_fight(payload)
    assert preflight["ready"] is True
    (root / "current.zip").write_bytes((root / "current.zip").read_bytes() + b"changed")
    with pytest.raises(CombatServiceError):
        service.create_confirmed_fight({
            **payload, "owner_confirmed": True, "preflight_commitment": preflight["preflight_commitment"],
            "idempotency_key": "c3d-p1-stale-source",
        })
    assert service.list_matches() == []
    refreshed = service.catalog()
    assert refreshed["portable_candidate_count"] == 0
    assert any(row["code"] == "C3B_INSTALLED_PACKAGE_STALE" for row in refreshed["installed_candidate_blocks"])


def test_c3d_p1_wrong_role_unsupported_runtime_project_mismatch_and_incomplete_packages_block(tmp_path):
    variants: list[tuple[str, Path]] = []
    wrong_role = _rewrite_package(RUNTIME_PACKAGE, tmp_path / "wrong-role.zip", lambda files: files.__setitem__(
        "PACKAGE_MANIFEST.json",
        canonical_json({**json.loads(files["PACKAGE_MANIFEST.json"]), "package_role": "incomplete_character"}).encode(),
    ))
    variants.append(("C3B_PACKAGE_ROLE_UNSUPPORTED", wrong_role))

    def unsupported(files):
        readiness = json.loads(files["READINESS.json"])
        readiness["combat_runtime"] = "STATIC_ONLY"
        files["READINESS.json"] = canonical_json(readiness).encode()
    variants.append(("C3B_RUNTIME_READINESS_INCOMPATIBLE", _rewrite_package(RUNTIME_PACKAGE, tmp_path / "unsupported.zip", unsupported)))

    def incomplete(files):
        files.pop("combat/Runtime_Support_Matrix.json", None)
    variants.append(("C3B_RUNTIME_CONTRACT_MISSING", _rewrite_package(RUNTIME_PACKAGE, tmp_path / "incomplete.zip", incomplete)))

    for index, (expected_code, package) in enumerate(variants):
        data = tmp_path / f"variant-{index}"
        _install_pointer(data, package)
        inventory = CombatService(ROOT, data).combatant_library.inventory()
        assert inventory.accepted_count == 0
        assert inventory.blocked_count == 1
        # Exact lower-layer diagnostics are preserved; no variant is promoted to Combat Ready.
        assert inventory.blocked_candidates[0].code == expected_code or expected_code in str(inventory.blocked_candidates[0].details)

    mismatch_data = tmp_path / "project-mismatch"
    _install_pointer(mismatch_data, RUNTIME_PACKAGE, pointer_project_id="different-project-id")
    mismatch = CombatService(ROOT, mismatch_data).combatant_library.inventory()
    assert mismatch.accepted_count == 0
    assert mismatch.blocked_candidates[0].code == "C3B_PROJECT_IDENTITY_MISMATCH"


def test_c3d_p1_same_project_different_package_install_conflict(fresh_db, tmp_path):
    service = PortableCharacterPackageService(fresh_db)
    pointer = {"schema_version": "TianxiaFoundry.PortableCharacterVerificationPointer.v1", "project_id": PROJECT_ID, "package_sha256": RUNTIME_SHA}
    assert service._install_verified_package_atomic(project_id=PROJECT_ID, package=RUNTIME_PACKAGE, pointer=pointer, expected_sha256=RUNTIME_SHA) == "INSTALLED"
    changed = tmp_path / "changed-package.zip"
    _rewrite_package(RUNTIME_PACKAGE, changed, lambda files: files.__setitem__("READINESS.json", files["READINESS.json"] + b" "))
    with pytest.raises(Exception) as exc:
        service._install_verified_package_atomic(
            project_id=PROJECT_ID, package=changed,
            pointer={**pointer, "package_sha256": sha256_file(changed)}, expected_sha256=sha256_file(changed),
        )
    assert getattr(exc.value, "code", None) == "PORTABLE_CHARACTER_INSTALLED_PACKAGE_CONFLICT"
    assert sha256_file(fresh_db.settings.data_dir / "portable_characters" / PROJECT_ID / "current.zip") == RUNTIME_SHA


def test_c3d_p1_api_ui_contract_includes_martial_focus_and_owner_labels():
    models = (ROOT / "app/models.py").read_text(encoding="utf-8")
    javascript = (ROOT / "static/app.js").read_text(encoding="utf-8")
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    assert "martial_focus_current" in models
    assert 'martial_focus_current: resourceValue("martial_focus")' in javascript
    assert '"Installed Character · Combat Ready · Primary Combatant when selected"' in javascript
    assert 'badge.textContent = "Not Combat Ready"' in javascript
    assert 'advancedSummary.textContent = "Advanced Details"' in javascript
    assert "select any installed <strong>combat ready</strong> primary combatants" in html.casefold()


def test_c3d_p1_match_local_source_package_mutation_fails_reopen(tmp_path):
    _install_pointer(tmp_path, RUNTIME_PACKAGE)
    service = CombatService(ROOT, tmp_path)
    payload = _catalog_payload(service)
    preflight = service.preflight_new_fight(payload)
    created = service.create_confirmed_fight({
        **payload,
        "owner_confirmed": True,
        "preflight_commitment": preflight["preflight_commitment"],
        "idempotency_key": "c3d-p1-match-local-tamper",
    })
    source_copy = service._match_dir(created["match_id"]) / "SourceCharacterPackage.zip"
    source_copy.write_bytes(source_copy.read_bytes() + b"tamper")
    with pytest.raises(CombatServiceError) as exc:
        CombatService(ROOT, tmp_path).get_match(created["match_id"])
    assert exc.value.diagnostic.code in {
        "COMBAT_MATCH_LOAD_FAILED",
        "COMBAT_BOUND_CONTENT_MISMATCH",
        "COMBAT_CONTENT_NOT_READY",
    }


def test_c3d_p1_conflicting_runtime_actor_identity_is_rejected(monkeypatch, tmp_path):
    _install_pointer(tmp_path, RUNTIME_PACKAGE)
    service = CombatService(ROOT, tmp_path)
    inventory = service.combatant_library.inventory()
    entry = inventory.accepted_candidates[0]
    other = entry.model_copy(update={
        "entry_id": "candidate:conflicting-runtime-identity",
        "character_project_id": "different-project-id",
    })
    conflicting_inventory = inventory.model_copy(update={
        "accepted_candidates": (entry, other),
        "accepted_count": 2,
    })
    monkeypatch.setattr(service.combatant_library, "inventory", lambda: conflicting_inventory)
    monkeypatch.setattr("combat.gate5_service.runtime_actor_id", lambda _project, _package: "portable-character:forced-collision")
    with pytest.raises(CombatServiceError) as exc:
        service.catalog()
    assert exc.value.diagnostic.code == "C3D_RUNTIME_ACTOR_ID_COLLISION"
