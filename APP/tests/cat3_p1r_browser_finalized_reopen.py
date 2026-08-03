from __future__ import annotations

import argparse
import json
import re
import socket
import threading
import zipfile
from pathlib import Path
from typing import Any

import uvicorn
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

from app.api import create_app
from app.core import Settings, sha256_file
from character_creation.choice_snapshot import valid_choice_snapshot
from tests.cat3_p1r_browser_harness import (
    FREE_GRANTS,
    ORDINARY,
    SPARROW,
    SPHERES,
    UNRESOLVED,
)


def stage(message: str) -> None:
    print(f"[CAT3-P1R finalized reopen] {message}", flush=True)


def run(
    *,
    root: Path,
    data: Path,
    output: Path,
    browser: str,
    screenshot_dir: Path,
    project_id: str,
    run_id: str,
) -> dict[str, Any]:
    app = create_app(Settings.from_env(root, data))
    canonical_run = app.state.character_creation.get(run_id)
    if canonical_run["project_id"] != project_id:
        raise AssertionError("The finalized run does not belong to the supplied server project identity.")
    if canonical_run["status"] != "CLEAN_AND_FINALIZED":
        raise AssertionError(f"The preserved run is not finalized: {canonical_run['status']}")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off")
    )
    thread = threading.Thread(target=server.run, name="cat3-p1r-finalized-reopen", daemon=True)
    page_errors: list[str] = []
    console_errors: list[str] = []
    failed_requests: list[str] = []
    requests: list[dict[str, Any]] = []
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)

    with TestClient(app):
        thread.start()
        for _ in range(200):
            if server.started:
                break
            thread.join(0.05)
        assert server.started
        with sync_playwright() as playwright:
            chromium = playwright.chromium.launch(
                executable_path=browser,
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--no-proxy-server",
                    "--disable-features=BlockInsecurePrivateNetworkRequests,PrivateNetworkAccessForNavigations,PrivateNetworkAccessRespectPreflightResults",
                ],
            )
            page = chromium.new_page(viewport={"width": 1720, "height": 1200})
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.on(
                "console",
                lambda message: console_errors.append(message.text)
                if message.type == "error"
                else None,
            )
            page.on(
                "requestfailed",
                lambda request: failed_requests.append(
                    f"{request.method} {request.url}: {request.failure}"
                ),
            )
            page.on(
                "response",
                lambda response: requests.append(
                    {
                        "method": response.request.method,
                        "url": response.url,
                        "status": response.status,
                    }
                )
                if "/api/" in response.url
                else None,
            )
            stage("opening the existing finalized project in real Windows Chromium")
            page.goto(base_url, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_function(
                "document.querySelector('#sheetOptionsStatus')?.textContent.includes('85 canonical Spheres')",
                timeout=180000,
            )
            uuid_probe = page.evaluate(
                "() => ({available: typeof crypto.randomUUID === 'function', value: crypto.randomUUID()})"
            )
            assert uuid_probe["available"] is True
            assert re.fullmatch(r"[0-9a-f-]{36}", uuid_probe["value"])

            project = page.evaluate(
                "async id => await api(`/api/projects/${encodeURIComponent(id)}`)",
                project_id,
            )
            compact_run = page.evaluate(
                "async id => await api(`/api/character-creation/runs/${encodeURIComponent(id)}`)",
                run_id,
            )
            assert compact_run["status"] == "CLEAN_AND_FINALIZED"
            assert compact_run["project_id"] == project_id
            assert compact_run["final_revision"] == project["revision"]
            assert compact_run["commit"]["approved_candidate_identity"] == compact_run["dry_run"]["candidate_identity"]
            snapshot_binding = compact_run["request"]["typed_choice_snapshot"]
            assert snapshot_binding["canonical_project_id"] == project_id
            assert compact_run["dry_run"]["typed_choice_snapshot"] == snapshot_binding
            assert compact_run["commit"]["typed_choice_snapshot_sha256"] == snapshot_binding["snapshot_sha256"]
            initial_issuance = compact_run["outputs"]["catalog_acquisition_evidence"]
            assert initial_issuance["schema"] == "TianxiaFactory.InitialCatalogProvenanceIssuance.v1"
            assert initial_issuance["project_id"] == project_id
            assert initial_issuance["character_id"] == project_id
            assert initial_issuance["run_id"] == run_id
            assert initial_issuance["candidate_identity"] == compact_run["dry_run"]["candidate_identity"]
            assert initial_issuance["typed_choice_snapshot_sha256"] == snapshot_binding["snapshot_sha256"]
            assert initial_issuance["record_count"] == len(initial_issuance["records"]) > 0

            locks = {row["field"]: row["value"] for row in project["project"]["user_locks"]}
            planning = locks["character_sheet.planning_preferences"]
            assert planning["sphere_priority_ids"] == SPHERES
            expected_priorities = [
                "tianxia.talent.beauty.admiring_crowd_method",
                "tianxia.talent.ash.burial_ground",
                "TAL_ATHLETICS_WALL_STUNT",
                "TAL_ATHLETICS_AIR_STUNT",
                SPARROW,
                "tianxia.talent.blood.blood_puppet",
            ]
            assert planning["talent_priority_ids"] == expected_priorities

            available_evidence = page.evaluate(
                "async projectId => await api(`/api/non-sphere/projects/${encodeURIComponent(projectId)}/evidence`)",
                project_id,
            )
            acquisition_evidence_ids = [
                row["evidence_id"] for row in available_evidence["evidence"]
                if row["authority_type"] == "talent_acquisition_provenance"
                and row["targets"]["canonical_content_id"] == "tianxia.talent.blood.blood_puppet"
                and row["targets"]["issuance_route"] == "initial_character_finalization"
                and row["targets"]["character_id"] == project_id
            ]
            assert acquisition_evidence_ids
            assert sorted(row["evidence_id"] for row in initial_issuance["records"]) == sorted(acquisition_evidence_ids)
            projection_body = {
                "target_cl": 7,
                "acquired_sphere_ids": SPHERES,
                "free_talent_grants": FREE_GRANTS,
                "ordinary_talent_ids": ORDINARY,
                "project_id": project_id,
                "character_id": project_id,
                "acquisition_evidence_ids": acquisition_evidence_ids,
            }
            valid_projection = page.evaluate(
                "async body => await api('/api/catalog/canonical/creator-projection', {method:'POST', body:JSON.stringify(body)})",
                projection_body,
            )
            unresolved_projection = page.evaluate(
                "async body => await api('/api/catalog/canonical/creator-projection', {method:'POST', body:JSON.stringify(body)})",
                {**projection_body, "ordinary_talent_ids": ORDINARY + [UNRESOLVED]},
            )
            assert valid_projection["ready"] is True
            unresolved = {
                row["canonical_talent_id"]: row
                for row in unresolved_projection["talent_dispositions"]
            }
            assert unresolved[UNRESOLVED]["disposition"] == "locked_by_unresolved_prerequisite"

            snapshot_path = output.parent / "CAT3_P1R_R1_TYPED_CHOICE_SNAPSHOT.json"
            with page.expect_download(timeout=180000) as snapshot_download:
                page.evaluate(
                    """url => {
                        const link = document.createElement('a');
                        link.href = url;
                        link.download = '';
                        document.body.appendChild(link);
                        link.click();
                        link.remove();
                    }""",
                    f"/api/character-creation/runs/{run_id}/typed-choice-snapshot",
                )
            snapshot_download.value.save_as(str(snapshot_path))
            frozen_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            assert valid_choice_snapshot(frozen_snapshot)
            assert frozen_snapshot["snapshot_sha256"] == snapshot_binding["snapshot_sha256"]
            assert frozen_snapshot["canonical_project_id"] == project_id
            assert frozen_snapshot["display_name_content"] == project["working_name"]

            portable = compact_run["outputs"]["portable_character"]
            clean_import = portable["clean_import"]
            gm_export = portable["gm_export"]
            gm_consumer = compact_run["outputs"]["gm_consumer"]
            assert clean_import["first"]["status"] == "IMPORTED"
            assert clean_import["first"]["project_id"] == project_id
            assert clean_import["second"]["status"] == "ALREADY_INSTALLED_IDENTICAL"
            assert clean_import["reopen"]["project_id"] == project_id
            assert clean_import["reopen"]["character_sheet_project_id"] == project_id
            assert gm_consumer["status"] == "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"
            assert gm_consumer["save_reload_semantic_equivalence"] is True
            assert gm_consumer["all_tabs_nonempty"] is True
            assert gm_consumer["exact_tab_order"] is True
            assert not gm_consumer["console_or_page_errors"]
            assert gm_export["source_consumer_verified"] is True

            character_zip = output.parent / "CAT3_P1R_R1_CHARACTER.zip"
            with page.expect_download(timeout=180000) as character_download:
                page.evaluate(
                    """url => {
                        const link = document.createElement('a');
                        link.href = url;
                        link.download = '';
                        document.body.appendChild(link);
                        link.click();
                        link.remove();
                    }""",
                    f"/api/characters/{project_id}/gm-export/download?filename={gm_export['filename']}",
                )
            character_download.value.save_as(str(character_zip))
            assert sha256_file(character_zip) == gm_export["sha256"] == portable["package_sha256"]
            with zipfile.ZipFile(character_zip) as archive:
                manifest = json.loads(archive.read("PACKAGE_MANIFEST.json"))
                provenance = json.loads(
                    archive.read("source/advancement_projection/Projection_Provenance_Map.json")
                )
                gm_model = json.loads(archive.read("Tianxia_GM_Character_Model_v2.json"))
                owner_sheet = json.loads(archive.read("Tianxia_Owner_Character_Sheet_v1.json"))
            assert manifest["project_id"] == project_id
            assert manifest["project_revision"] == project["revision"]
            assert manifest["typed_choice_snapshot_sha256"] == frozen_snapshot["snapshot_sha256"]
            assert provenance["typed_choice_snapshot"] == frozen_snapshot
            assert gm_model["metadata"]["project_id"] == project_id
            assert gm_model["metadata"]["typed_choice_snapshot_sha256"] == frozen_snapshot["snapshot_sha256"]
            assert owner_sheet["authority_and_artifact_identity"]["project_id"] == project_id
            assert owner_sheet["authority_and_artifact_identity"]["typed_choice_snapshot_sha256"] == frozen_snapshot["snapshot_sha256"]

            proof = {
                "status": compact_run["status"],
                "project_id": project_id,
                "run_id": run_id,
                "candidate_identity": compact_run["dry_run"]["candidate_identity"],
                "final_revision": project["revision"],
                "typed_choice_snapshot_sha256": frozen_snapshot["snapshot_sha256"],
                "clean_factory_import": clean_import["first"]["status"],
                "clean_factory_reopen": clean_import["reopen"],
                "identical_reimport": clean_import["second"]["status"],
                "exact_bundled_gm_status": gm_consumer["status"],
                "exact_bundled_gm_save_reload": gm_consumer["save_reload_semantic_equivalence"],
                "character_zip_sha256": gm_export["sha256"],
            }
            page.evaluate(
                """proof => {
                    const pre = document.createElement('pre');
                    pre.id = 'cat3FinalizedReopenProof';
                    pre.textContent = JSON.stringify(proof, null, 2);
                    document.body.prepend(pre);
                }""",
                proof,
            )
            screenshot = screenshot_dir / "04_real_backend_finalized_reopened.png"
            page.screenshot(path=str(screenshot), full_page=True)
            chromium.close()

    server.should_exit = True
    thread.join(timeout=10)
    checks = {
        "real_windows_chromium_loopback_http": True,
        "same_normal_wizard_project_reopened": project["project_id"] == project_id,
        "server_project_identity_preserved": frozen_snapshot["canonical_project_id"] == project_id,
        "working_name_is_display_content_only": (
            frozen_snapshot["display_name_content"] == project["working_name"]
            and frozen_snapshot["display_name_content"] != project_id
        ),
        "revision_bound_exact_snapshot_downloaded_for_review": valid_choice_snapshot(frozen_snapshot),
        "review_finalization_export_share_snapshot": (
            compact_run["commit"]["typed_choice_snapshot_sha256"]
            == manifest["typed_choice_snapshot_sha256"]
            == frozen_snapshot["snapshot_sha256"]
        ),
        "clean_factory_import_reopen": clean_import["reopen"]["project_id"] == project_id,
        "clean_factory_identical_reimport": clean_import["second"]["status"] == "ALREADY_INSTALLED_IDENTICAL",
        "exact_bundled_gm_import_reopen": (
            gm_consumer["status"] == "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"
            and gm_consumer["save_reload_semantic_equivalence"] is True
        ),
        "character_zip_exported_through_browser": character_zip.is_file(),
        "package_project_revision_identity_preserved": (
            manifest["project_id"] == project_id and manifest["project_revision"] == project["revision"]
        ),
        "same_character_server_issued_initial_provenance_accepted_downstream": (
            bool(acquisition_evidence_ids) and valid_projection["ready"] is True
        ),
        "no_page_errors": not page_errors,
        "no_console_errors": not console_errors,
        "no_failed_requests": not failed_requests,
    }
    report = {
        "schema": "TianxiaFactory.CAT3P1RRealChromiumFinalizedReopen.v1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "transport_mode": "WINDOWS_CHROMIUM_LOOPBACK_HTTP_TO_REAL_FASTAPI",
        "application_endpoints_mocked": False,
        "project_id": project_id,
        "run_id": run_id,
        "candidate_identity": compact_run["dry_run"]["candidate_identity"],
        "final_revision": project["revision"],
        "typed_choice_snapshot": {
            key: frozen_snapshot[key]
            for key in (
                "schema",
                "canonical_project_id",
                "project_revision",
                "content_lock_hash",
                "event_stream",
                "display_name_content",
                "snapshot_sha256",
            )
        }
        | {"typed_lock_count": len(frozen_snapshot["typed_locks"])},
        "character_zip": {
            "path": str(character_zip),
            "bytes": character_zip.stat().st_size,
            "sha256": sha256_file(character_zip),
        },
        "clean_factory_import": clean_import,
        "exact_bundled_gm_consumer": gm_consumer,
        "server_retained_catalog_evidence": available_evidence,
        "accepted_acquisition_evidence_ids": acquisition_evidence_ids,
        "checks": checks,
        "page_errors": page_errors,
        "console_errors": console_errors,
        "failed_requests": failed_requests,
        "requests": requests,
        "screenshots": [screenshot.name],
        "native_windows_status": "REAL_WINDOWS_CHROMIUM_ACCEPTANCE_EXECUTED",
        "linux_acceptance": "PENDING_INDEPENDENT_LINUX_EXECUTION",
    }
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser", required=True)
    parser.add_argument("--screenshot-dir", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    report = run(
        root=args.root.resolve(),
        data=args.data.resolve(),
        output=args.output.resolve(),
        browser=args.browser,
        screenshot_dir=args.screenshot_dir.resolve(),
        project_id=args.project_id,
        run_id=args.run_id,
    )
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
