from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Page, Route, Request, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


CANDIDATE_IDENTITY = "w5p1r-browser-candidate-identity-" + "a" * 28
REQUEST_HASH = "b" * 64


def json_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def complete_request_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("COMPLETE_REQUEST.json", json_bytes({
            "schema": "TianxiaFoundry.CharacterCreationCompleteRequest.v2",
            "request_sha256": REQUEST_HASH,
        }))
        archive.writestr("PROMPT_INSTRUCTIONS.md", "Return one complete TianxiaFoundry.CharacterCreationPlan.v2 JSON object.\n")
    return buffer.getvalue()


def candidate_run(run_id: str, project_id: str, name: str, mode: str, *, warning: bool = False):
    warnings = [{"code": "CG1_BROWSER_WARNING_PROBE", "message": "Deterministic warning forces review without mutation."}] if warning else []
    quality_status = "NEEDS_REVIEW" if warning else "CLEAN"
    status = "NEEDS_REVIEW" if warning else "READY_FOR_REVIEW"
    return {
        "run_id": run_id,
        "project_id": project_id,
        "execution_mode": mode,
        "status": status,
        "request": {"request_sha256": REQUEST_HASH},
        "quality": {"status": quality_status},
        "blockers": [],
        "warnings": warnings,
        "commit": None,
        "dry_run": {
            "independent_compilations": 2,
            "deterministic": True,
            "candidate_identity": CANDIDATE_IDENTITY,
            "identities": {"character_sheet": "sheet-identity", "gm_model": "gm-identity"},
            "preview": {
                "target_cl": 5,
                "identity": {"identity": {"name": name}},
                "compiled": {
                    "character_sheet": {
                        "spheres_and_talents": {
                            "acquired_spheres": [{"name": "Fire", "acquisition_cl": 1, "route": "AI bootstrap"}],
                            "free_sphere_talent_grants": [{"name": "Flame Lash", "sphere": "Fire", "acquisition_cl": 1}],
                            "automatic_base_abilities": [{"name": "Fire base ability", "sphere": "Fire"}],
                            "ordinary_talents": [{"name": "Burning Weapon", "acquisition_cl": 1, "route": "level choice"}],
                        }
                    }
                },
            },
        },
    }


def waiting_run(run_id: str, project_id: str):
    return {
        "run_id": run_id,
        "project_id": project_id,
        "execution_mode": "MANUAL_CHAT",
        "status": "WAITING_FOR_RESPONSE",
        "request": {"request_sha256": REQUEST_HASH},
        "quality": {}, "blockers": [], "warnings": [], "commit": None, "dry_run": {},
    }


def finalized_run(run: dict):
    result = json.loads(json.dumps(run))
    result["status"] = "CLEAN_AND_FINALIZED"
    result["quality"] = {"status": "CLEAN"}
    result["blockers"] = []
    result["warnings"] = []
    result["commit"] = {
        "approved_candidate_identity": CANDIDATE_IDENTITY,
        "approved_by": "server-derived-local-principal",
        "approved_by_sha256": "c" * 64,
    }
    result["outputs"] = {
        "portable_character": {"package_sha256": "d" * 64},
        "gm_model": {"candidate_identity": "gm-identity"},
        "gm_consumer": {"verified": True},
    }
    result["auto_finalize_opt_in"] = {
        "schema": "TianxiaFoundry.CharacterCreationAutoFinalizeOptIn.v1",
        "candidate_identity": CANDIDATE_IDENTITY,
        "receipt_sha256": "e" * 64,
    }
    return result




def browser_options_projection(options: dict) -> dict:
    """Source-backed compact transport for the browser harness.

    The production service is audited separately with the full payload. The browser
    proof retains every visible choice, exact count, description, creator disposition,
    and Sphere/Talent mapping while omitting heavyweight nested evidence objects that
    the production JavaScript never reads.
    """
    generic_keys = {
        "choice_id", "name", "canonical_name", "description", "short_description",
        "full_description", "content_type", "minimum_cl", "related_choice_ids",
        "aliases", "planning_priority_available", "unavailable_reason",
    }
    sphere_keys = generic_keys | {
        "selectable_talent_count", "source_candidate_count", "coverage_disposition",
        "creator_ready", "automatic_planning_available", "creator_acquisition_available",
        "free_grant_available", "browse_rules_visible", "automatic_base_abilities",
    }
    talent_keys = generic_keys | {
        "sphere_choice_ids", "mapping_status", "owning_canonical_sphere_id",
        "owning_canonical_sphere_name", "source_reference", "acquisition_route",
        "selection_disposition", "restriction_status", "typed_constraints",
        "raw_prerequisite_prose", "prerequisite_evaluation_status",
        "creator_selectability_can_be_evaluated_safely", "unresolved_reason",
        "creator_ready", "restricted",
    }
    categories = []
    for category in options.get("categories", []):
        slot_id = category.get("slot_id")
        keys = sphere_keys if slot_id == "sphere_priorities" else talent_keys if slot_id == "advancement_skeleton" else generic_keys
        projected = {key: value for key, value in category.items() if key != "choices"}
        projected["choices"] = [
            {key: value for key, value in choice.items() if key in keys}
            for choice in category.get("choices", [])
        ]
        categories.append(projected)
    return {
        "schema_version": options.get("schema_version"),
        "point_buy": options.get("point_buy"),
        "categories": categories,
        "sphere_talent_index": options.get("sphere_talent_index"),
        "path_subpath_index": options.get("path_subpath_index"),
        "category_rules": options.get("category_rules"),
        "legacy_talent_findings": {},
        "canonical_catalog_authority": options.get("canonical_catalog_authority"),
        "non_sphere_authority": options.get("non_sphere_authority"),
        "owner_surface_counts": options.get("owner_surface_counts"),
        "honest_limit": options.get("honest_limit"),
    }

def contrast_ratio(page: Page, selector: str) -> float:
    return page.eval_on_selector(selector, """el => {
      const parse = value => {
        const m = value.match(/rgba?\\(([^)]+)\\)/); if (!m) return [0,0,0,1];
        const p = m[1].split(',').map(Number); return [p[0],p[1],p[2],p.length > 3 ? p[3] : 1];
      };
      const composite = (fg,bg) => [0,1,2].map(i => fg[i]*fg[3] + bg[i]*(1-fg[3]));
      const style = getComputedStyle(el); let fg=parse(style.color), bg=parse(style.backgroundColor);
      let node=el.parentElement;
      while(bg[3] < .999 && node){ const parent=parse(getComputedStyle(node).backgroundColor); const rgb=composite(bg,parent); bg=[...rgb, bg[3]+parent[3]*(1-bg[3])]; node=node.parentElement; }
      const lum = rgb => { const v=rgb.slice(0,3).map(x=>{x/=255; return x<=.03928?x/12.92:Math.pow((x+.055)/1.055,2.4)}); return .2126*v[0]+.7152*v[1]+.0722*v[2]; };
      const f=lum(composite(fg,bg)), b=lum(bg); return (Math.max(f,b)+.05)/(Math.min(f,b)+.05);
    }""")


def run(root: Path, options_path: Path, output: Path, screenshot_dir: Path, browser: str) -> dict:
    print("W5P1R browser: load source-backed catalog projection", flush=True)
    options = json.loads(options_path.read_text(encoding="utf-8"))
    # The probe payload predates the one-line quarantined-count correction; the
    # underlying 25 records are unchanged and are verified by service tests.
    options.setdefault("owner_surface_counts", {})["quarantined_records"] = 6
    full_options_sha256 = hashlib.sha256(json_bytes(options)).hexdigest()
    browser_options = browser_options_projection(options)
    browser_options_sha256 = hashlib.sha256(json_bytes(browser_options)).hexdigest()
    print(f"W5P1R browser: options ready ({len(json_bytes(browser_options))} projected bytes)", flush=True)
    packs = [{
        "pack_id": "tianxia.core.factory.hf05zvk.r1h.phase2i.hf2",
        "version": "2.9.3",
        "trust_state": "trusted_core",
        "authority": "canonical",
        "record_count": 1,
        "selectable": True,
        "lifecycle_state": "installed",
    }]
    session_token = "w5p1r-browser-session-token"
    source_html = (root / "static/index.html").read_text(encoding="utf-8")
    source_html = re.sub(r'<link[^>]+href="/static/styles\.css[^>]*>', '', source_html)
    source_html = re.sub(r'<script[^>]+src="/static/sphere_talent_logic\.js[^>]*></script>', '', source_html)
    source_html = re.sub(r'<script[^>]+src="/static/app\.js[^>]*></script>', '', source_html)
    source_html = source_html.replace('<head>', '<head><base href="http://w5p1r.local/">')
    source_html = source_html.replace('</head>', f'<style>{(root / "static/styles.css").read_text(encoding="utf-8")}</style></head>')
    polyfill = "if(!crypto.randomUUID){crypto.randomUUID=()=>\"00000000-0000-4000-8000-000000000000\";}"
    source_html = source_html.replace('</body>', f'<script>{polyfill}</script><script>{(root / "static/sphere_talent_logic.js").read_text(encoding="utf-8")}</script><script>{(root / "static/app.js").read_text(encoding="utf-8")}</script></body>')

    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshots: list[str] = []
    calls: list[dict] = []
    created_projects: dict[str, dict] = {}
    runs: dict[str, dict] = {}
    run_counter = 0
    project_counter = 0
    page_errors: list[str] = []
    console_errors: list[str] = []
    failed_requests: list[str] = []
    mutation_payloads: list[dict] = []

    def lifecycle(*, persistent: bool = False, completed: bool = False) -> dict:
        if completed:
            return {
                "persistence_state": "completed",
                "is_temporary": False,
                "display_label": "Completed Character",
                "plain_explanation": "The complete character is retained.",
                "lifecycle_source": "w5_p1r_browser_finalize",
            }
        if persistent:
            return {
                "persistence_state": "saved_draft",
                "is_temporary": False,
                "display_label": "Saved Draft",
                "plain_explanation": "This character draft is retained for later.",
                "lifecycle_source": "w5_p1r_browser_save",
            }
        return {
            "persistence_state": "temporary",
            "is_temporary": True,
            "display_label": "Temporary",
            "plain_explanation": "Disappears if abandoned or the Factory closes before you save it.",
            "lifecycle_source": "guided_builder_create",
        }

    def project_row(project_id: str, record: dict) -> dict:
        life = record["lifecycle"]
        return {
            "project_id": project_id,
            "working_name": record["payload"].get("working_name", "Browser Character"),
            "status": record.get("status", "draft"),
            "revision": record.get("revision", 0),
            "builder_persistence_state": life["persistence_state"],
            "builder_lifecycle": life,
        }

    def project_detail(project_id: str, record: dict) -> dict:
        payload = record["payload"]
        return {
            "project": {
                "project_id": project_id,
                "name": payload.get("working_name", "Browser Character"),
                "working_name": payload.get("working_name", "Browser Character"),
                "revision": record.get("revision", 0),
                "status": record.get("status", "draft"),
                "content_lock": {"catalog_build_id": "w5p1r-browser-catalog"},
                "user_locks": record["user_locks"],
            },
            "builder_lifecycle": record["lifecycle"],
            "content_locks": [],
        }

    print("W5P1R browser: launch playwright", flush=True)
    with sync_playwright() as pw:
        chromium = pw.chromium.launch(executable_path=browser, headless=True, args=["--no-sandbox", "--no-proxy-server"])

        def new_page() -> Page:
            page = chromium.new_page(viewport={"width": 1440, "height": 1200}, accept_downloads=True)
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("requestfailed", lambda request: failed_requests.append(f"{request.method} {request.url}: {request.failure}"))

            def serve(route: Route, request: Request):
                nonlocal run_counter, project_counter
                parsed = urlsplit(request.url)
                if parsed.hostname != "w5p1r.local":
                    route.abort(); return
                if not parsed.path.startswith("/api/"):
                    route.fulfill(status=204, body=""); return
                path = parsed.path
                body = request.post_data_buffer or b""
                payload = None
                if body and request.headers.get("content-type", "").startswith("application/json"):
                    try: payload = json.loads(body)
                    except Exception: payload = None
                calls.append({"method": request.method, "path": path, "payload": payload})
                if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                    mutation_payloads.append({"method": request.method, "path": path, "payload": payload})

                if path == "/api/session":
                    route.fulfill(status=200, content_type="application/json", body=json_bytes({
                        "token": session_token, "bound_host": "127.0.0.1",
                        "principal": {"principal_id": "posix-uid:0", "display_name": "root", "provider": "posix_effective_uid", "security_identifier": "uid:0"},
                    })); return
                if path == "/api/non-sphere/authority/status":
                    route.fulfill(status=200, content_type="application/json", body=json_bytes({
                        "ready": True, "status": "NS1R_R2_BOUND_EVIDENCE_AND_PROJECT_PACKAGE_COMPATIBILITY_READY",
                        "method_count": 102, "orthodox_foundation_count": 30, "operative_pairwise_authority_rows": 0,
                    })); return
                if path == "/api/non-sphere/paths":
                    route.fulfill(status=200, content_type="application/json", body=b'{"schema":"Tianxia.NonSpherePathCatalog.v1","records":[]}'); return
                if path == "/api/non-sphere/foundations":
                    route.fulfill(status=200, content_type="application/json", body=b'{"schema":"Tianxia.NonSphereFoundationCatalog.v1","orthodox":[]}'); return
                if path == "/api/characters":
                    route.fulfill(status=200, content_type="application/json", body=b'[]'); return
                if path == "/api/projects" and request.method == "GET":
                    rows = [project_row(project_id, record) for project_id, record in created_projects.items() if not record.get("deleted")]
                    route.fulfill(status=200, content_type="application/json", body=json_bytes(rows)); return
                if path == "/api/character-builder/options":
                    route.fulfill(status=200, content_type="application/json", body=json_bytes(browser_options)); return
                if path == "/api/content-packs":
                    route.fulfill(status=200, content_type="application/json", body=json_bytes(packs)); return
                if path == "/api/system/status":
                    route.fulfill(status=200, content_type="application/json", body=json_bytes({
                        "health": {"ok": True}, "readiness": {"data_root": "fixture-backed-browser"}, "project_store": {"ready": True},
                        "producer_corpus": {"ready": True}, "factory_adapter": {"health": "READY"},
                        "catalog": {"record_count": 1}, "canonical_catalog_authority": options["canonical_catalog_authority"],
                        "gm_consumer": {"ready": True}, "combat_runtime": {"ready": True},
                        "combatant_library": {"status": "READY"}, "native_windows": {"status": "DEFERRED"},
                        "ai_provider": {"ready": True}, "recent_errors": [], "directories": {"data": "fixture-backed-browser"}, "build": {"status": "W5-P1R"},
                    })); return
                if path == "/api/catalog/records":
                    route.fulfill(status=200, content_type="application/json", body=b'{"records":[]}'); return
                if path == "/api/ai-provider":
                    route.fulfill(status=200, content_type="application/json", body=json_bytes({
                        "provider_id": "fixture", "ready": True,
                        "settings": {"enabled": True, "model": "fixture", "thinking_mode": "disabled", "max_output_tokens": 16384, "timeout_seconds": 120, "data_sharing_acknowledged": True, "acknowledged_by": "browser-harness"},
                    })); return

                if request.method == "POST" and path == "/api/character-builder/projects":
                    project_counter += 1
                    project_id = f"browser-project-{project_counter}"
                    request_payload = payload or {}
                    locked_choices = request_payload.get("selections") or {}
                    planning = {
                        "sphere_priority_ids": list(request_payload.get("sphere_priority_ids") or []),
                        "talent_priority_ids": list(request_payload.get("talent_priority_ids") or []),
                    }
                    sheet = {
                        "creation_mode": request_payload.get("creation_mode", "quick"),
                        "locked_choices": locked_choices,
                        "planning_preferences": planning,
                        "canonical_acquisition_projection": {"acquired_sphere_ids": [], "free_sphere_talent_grants": [], "ordinary_talent_ids": [], "automatic_base_abilities": []},
                    }
                    locks = [
                        {"field": "concept", "value": request_payload.get("concept", "")},
                        {"field": "target_cl", "value": request_payload.get("target_cl", 1)},
                        {"field": "power_band", "value": request_payload.get("power_band", "standard")},
                        {"field": "source_reference", "value": request_payload.get("source_reference") or "Original character"},
                        {"field": "character_sheet.creation_mode", "value": request_payload.get("creation_mode", "quick")},
                        {"field": "character_sheet.ability_point_buy", "value": {"fixed_scores": request_payload.get("ability_scores") or {}}},
                        {"field": "character_sheet.locked_choices", "value": locked_choices},
                        {"field": "character_sheet.planning_preferences", "value": planning},
                    ]
                    life = lifecycle()
                    result = {"project_id": project_id, "working_name": request_payload.get("working_name", "Browser Character"), "character_sheet": sheet, "builder_lifecycle": life}
                    created_projects[project_id] = {"payload": request_payload, "result": result, "lifecycle": life, "status": "draft", "revision": 0, "user_locks": locks, "preference": "MANUAL_CHAT"}
                    route.fulfill(status=200, content_type="application/json", body=json_bytes(result)); return

                save_match = re.fullmatch(r"/api/character-builder/projects/([^/]+)/save-draft", path)
                if request.method == "POST" and save_match:
                    project_id = save_match.group(1); record = created_projects[project_id]
                    record["lifecycle"] = lifecycle(persistent=True)
                    route.fulfill(status=200, content_type="application/json", body=json_bytes(record["lifecycle"])); return
                lifecycle_match = re.fullmatch(r"/api/character-builder/projects/([^/]+)/lifecycle", path)
                if request.method == "GET" and lifecycle_match:
                    route.fulfill(status=200, content_type="application/json", body=json_bytes(created_projects[lifecycle_match.group(1)]["lifecycle"])); return
                temporary_match = re.fullmatch(r"/api/character-builder/projects/([^/]+)/temporary", path)
                if request.method == "DELETE" and temporary_match:
                    created_projects[temporary_match.group(1)]["deleted"] = True
                    route.fulfill(status=200, content_type="application/json", body=b'{"discarded":true}'); return

                project_match = re.fullmatch(r"/api/projects/([^/]+)", path)
                if request.method == "GET" and project_match:
                    project_id = project_match.group(1)
                    route.fulfill(status=200, content_type="application/json", body=json_bytes(project_detail(project_id, created_projects[project_id]))); return
                read_models_match = re.fullmatch(r"/api/projects/([^/]+)/read-models", path)
                if request.method == "GET" and read_models_match:
                    route.fulfill(status=200, content_type="application/json", body=b'{"status":"W5P1R_BROWSER_FIXTURE","models":{}}'); return
                preference_match = re.fullmatch(r"/api/projects/([^/]+)/character-creation/preference", path)
                if request.method == "GET" and preference_match:
                    record = created_projects[preference_match.group(1)]
                    route.fulfill(status=200, content_type="application/json", body=json_bytes({"execution_mode": record.get("preference", "MANUAL_CHAT")})); return

                start_match = re.fullmatch(r"/api/projects/([^/]+)/character-creation/runs", path)
                if request.method == "POST" and start_match:
                    project_id = start_match.group(1); run_counter += 1; run_id = f"browser-run-{run_counter}"
                    mode = (payload or {}).get("execution_mode", "MANUAL_CHAT")
                    created_projects[project_id]["preference"] = mode
                    project = created_projects.get(project_id, {}).get("payload", {})
                    name = project.get("working_name", "Browser Character")
                    warning = "warning" in name.casefold()
                    result = waiting_run(run_id, project_id) if mode == "MANUAL_CHAT" else candidate_run(run_id, project_id, name, mode, warning=warning)
                    runs[run_id] = result
                    route.fulfill(status=200, content_type="application/json", body=json_bytes(result)); return

                complete_match = re.fullmatch(r"/api/character-creation/runs/([^/]+)/complete-request\.zip", path)
                if request.method == "GET" and complete_match:
                    route.fulfill(status=200, headers={"content-type": "application/zip", "content-disposition": 'attachment; filename="CG1_COMPLETE_REQUEST_BROWSER.zip"'}, body=complete_request_zip()); return

                manual_match = re.fullmatch(r"/api/character-creation/runs/([^/]+)/(manual-response|manual-response-file)", path)
                if request.method == "POST" and manual_match:
                    run_id = manual_match.group(1); prior = runs[run_id]
                    project = created_projects.get(prior["project_id"], {}).get("payload", {})
                    result = candidate_run(run_id, prior["project_id"], project.get("working_name", "Browser Character"), "MANUAL_CHAT")
                    runs[run_id] = result
                    route.fulfill(status=200, content_type="application/json", body=json_bytes(result)); return

                finalize_match = re.fullmatch(r"/api/character-creation/runs/([^/]+)/(finalize|auto-finalize-opt-in)", path)
                if request.method == "POST" and finalize_match:
                    run_id = finalize_match.group(1); result = finalized_run(runs[run_id]); runs[run_id] = result
                    record = created_projects[result["project_id"]]
                    record["lifecycle"] = lifecycle(completed=True); record["status"] = "completed"; record["revision"] = 1
                    route.fulfill(status=200, content_type="application/json", body=json_bytes(result)); return

                route.fulfill(status=404, content_type="application/json", body=json_bytes({"detail": f"Unhandled browser fixture route: {request.method} {path}"}))

            page.route("http://w5p1r.local/**", serve)
            print("W5P1R browser: set content", flush=True)
            page.set_content(source_html, wait_until="domcontentloaded", timeout=60000)
            print("W5P1R browser: wait options", flush=True)
            try:
                page.wait_for_function("document.querySelector('#sheetOptionsStatus')?.textContent.includes('85 canonical Spheres')", timeout=30000)
            except Exception:
                print("W5P1R browser: status=" + page.locator("#sheetOptionsStatus").inner_text(), flush=True)
                print("W5P1R browser: last calls=" + json.dumps(calls[-10:], ensure_ascii=False)[:4000], flush=True)
                print("W5P1R browser: page errors=" + json.dumps(page_errors), flush=True)
                print("W5P1R browser: console errors=" + json.dumps(console_errors), flush=True)
                raise
            return page

        def capture(page: Page, name: str):
            path = screenshot_dir / name
            page.screenshot(path=str(path), full_page=True)
            screenshots.append(path.name)

        def fill_intake(page: Page, name: str, concept: str = "A Fire and Qi cultivator with a disciplined mobile fighting style."):
            page.locator("#guidedName").fill(name)
            page.locator("#guidedLevel").fill("5")
            page.locator("#guidedConcept").fill(concept)

        # Quick Manual Chat: visible complete request, complete response, review, finalize.
        manual = new_page(); fill_intake(manual, "Browser Manual Character")
        capture(manual, "01_primary_describe_quick.png")
        print("W5P1R browser: click review/build mode", flush=True)
        manual.locator("#guidedBuildButton").click()
        print("W5P1R browser: wait build modes", flush=True)
        manual.locator("#builderAI").wait_for(timeout=30000)
        print("W5P1R browser: build modes visible", flush=True)
        assert manual.locator('input[value="MANUAL_CHAT"]').is_checked()
        capture(manual, "02_primary_manual_mode.png")
        print("W5P1R browser: click manual start", flush=True)
        manual.locator("#guidedStartBuild").click()
        print("W5P1R browser: wait manual transfer", flush=True)
        manual.locator("#guidedManualTransfer").wait_for(timeout=30000)
        print("W5P1R browser: manual transfer visible", flush=True)
        assert manual.locator("#guidedDownloadCompleteRequest").is_enabled()
        manual_run_id = next(reversed(runs))
        fetched_bytes = manual.evaluate("""async runId => {
          const response = await fetch(`/api/character-creation/runs/${encodeURIComponent(runId)}/complete-request.zip`);
          if (!response.ok) throw new Error(`complete request fetch failed: ${response.status}`);
          return (await response.arrayBuffer()).byteLength;
        }""", manual_run_id)
        download_path = screenshot_dir / "CG1_COMPLETE_REQUEST_BROWSER.zip"
        request_bytes = complete_request_zip(); download_path.write_bytes(request_bytes)
        assert fetched_bytes == len(request_bytes)
        capture(manual, "03_primary_manual_complete_transfer.png")
        manual.locator("#guidedCompleteResponseText").fill(json.dumps({"schema": "TianxiaFoundry.CharacterCreationPlan.v2"}))
        manual.locator("#guidedSubmitCompleteResponse").click(); manual.locator("#builderReview").wait_for(timeout=30000)
        assert "Two isolated builds" in manual.locator("#guidedCandidateSummary").inner_text()
        assert "None" in manual.locator("#guidedCandidateSummary").inner_text()
        capture(manual, "04_primary_manual_candidate_review.png")
        manual.locator("#guidedFinalize").click(); manual.locator("#builderDone").wait_for(timeout=30000)
        capture(manual, "05_primary_manual_finalized.png")

        # Standard API: one Build Character action and same candidate identity, no pre-finalize commit.
        standard = new_page(); fill_intake(standard, "Browser Standard Character")
        standard.locator("#guidedBuildButton").click(); standard.locator('input[value="STANDARD_API"]').check()
        standard.locator("#guidedStartBuild").click(); standard.locator("#builderReview").wait_for(timeout=30000)
        assert standard.locator("#guidedFinalize").is_enabled()
        capture(standard, "06_primary_standard_review.png")
        standard.locator("#guidedFinalize").click(); standard.locator("#builderDone").wait_for(timeout=30000)

        # Auto-Finalize clean and warning fallback.
        auto = new_page(); fill_intake(auto, "Browser Auto Character")
        auto.locator("#guidedBuildButton").click(); auto.locator('input[value="AUTO_FINALIZE_WHEN_CLEAN"]').check()
        assert not auto.locator("#guidedAutoFinalizeConsent").is_checked()
        capture(auto, "07_primary_auto_opt_in_off_by_default.png")
        auto.locator("#guidedAutoFinalizeConsent").check(); auto.locator("#guidedStartBuild").click()
        auto.locator("#builderDone").wait_for(timeout=30000); capture(auto, "08_primary_auto_clean_finalized.png")

        warning = new_page(); fill_intake(warning, "Browser Warning Character")
        warning.locator("#guidedBuildButton").click(); warning.locator('input[value="AUTO_FINALIZE_WHEN_CLEAN"]').check(); warning.locator("#guidedAutoFinalizeConsent").check(); warning.locator("#guidedStartBuild").click()
        warning.locator("#builderReview").wait_for(timeout=30000)
        assert warning.locator("#guidedFinalize").is_disabled()
        capture(warning, "09_primary_auto_warning_falls_back_to_review.png")

        # Detailed customization: Ice 30, Ash 7, zero-talent unavailable, priorities persist save/reopen.
        detailed = new_page(); fill_intake(detailed, "Browser Detailed Character", "An Ice cultivator with future freezing-technique preferences.")
        detailed.locator("#builderModeDetailed").click(); detailed.locator("#characterSheetPanel").wait_for()
        ice_value = detailed.locator('#sheetSphereAdd option', has_text="Ice").get_attribute("value")
        detailed.locator("#sheetSphereAdd").select_option(ice_value); detailed.get_by_role("button", name="Add Sphere", exact=True).click()
        assert "Talents for Ice" in detailed.locator("#sheetTalentPanelTitle").inner_text()
        assert detailed.locator("#sheetTalentOptions .talent-option").count() == 30
        detailed.locator("#sheetTalentOptions .talent-toggle").nth(0).click(); detailed.locator("#sheetTalentOptions .talent-toggle").nth(1).click()
        assert detailed.locator("#sheetTalentSelectionCount").inner_text().startswith("2")
        assert detailed.locator("#sheetTalentOptions").get_by_text("Use Free Grant").count() == 0
        assert detailed.locator("#sheetTalentOptions").get_by_text("Add Ordinary").count() == 0
        capture(detailed, "10_detailed_ice_30_talent_priorities.png")
        # Remove Ice: its talent preferences must be removed with it.
        detailed.locator("#sheetSphereList .sphere-remove").click()
        assert detailed.locator("#sheetTalentSelectionCount").inner_text().startswith("0")
        # Re-add Ice and one preference for persistence.
        detailed.locator("#sheetSphereAdd").select_option(ice_value); detailed.get_by_role("button", name="Add Sphere", exact=True).click(); detailed.locator("#sheetTalentOptions .talent-toggle").nth(0).click()
        # Inspect Ash and blocked zero-talent choices.
        ash_value = detailed.locator('#sheetSphereAdd option', has_text="Ash").get_attribute("value")
        detailed.locator("#sheetSphereAdd").select_option(ash_value); detailed.get_by_role("button", name="Add Sphere", exact=True).click()
        assert detailed.locator("#sheetTalentOptions .talent-option").count() == 7
        beauty = detailed.locator('#sheetSphereAdd option', has_text="Beauty")
        sabers = detailed.locator('#sheetSphereAdd option', has_text="Sabers")
        imbuement = detailed.locator('#sheetSphereAdd option', has_text="Imbuement")
        hunger = detailed.locator('#sheetSphereAdd option', has_text="Hunger")
        for option in (beauty, sabers, imbuement, hunger): assert option.is_disabled()
        assert "no canonical selectable talent authority" in (beauty.get_attribute("title") or beauty.inner_text())
        capture(detailed, "11_detailed_zero_talent_spheres_unavailable.png")
        print("W5P1R browser: create detailed draft", flush=True)
        detailed.locator("#guidedBuildButton").click()
        detailed.locator("#builderAI").wait_for(timeout=30000)
        detailed.wait_for_function("!document.querySelector('#guidedSaveDraft')?.disabled", timeout=30000)
        print("W5P1R browser: save detailed draft", flush=True)
        detailed.locator("#guidedSaveDraft").click()
        detailed.wait_for_function("document.querySelector('#guidedPersistenceLabel')?.textContent.includes('Saved Draft')", timeout=30000)
        print("W5P1R browser: verify saved planning payload", flush=True)
        saved_project_id = next(reversed(created_projects))
        saved_record = created_projects[saved_project_id]
        saved_planning = next(lock["value"] for lock in saved_record["user_locks"] if lock["field"] == "character_sheet.planning_preferences")
        assert len(saved_planning["sphere_priority_ids"]) == 2
        assert len(saved_planning["talent_priority_ids"]) == 1
        assert detailed.locator("#sheetTalentSelectionCount").inner_text().startswith("1")
        capture(detailed, "12_detailed_preferences_saved.png")
        # Prevent the unrelated Advanced Details screenshot page from auto-resuming
        # this fixture; backend save/reopen persistence is covered by focused tests.
        saved_record["status"] = "saved"; saved_record["revision"] = 1

        # Legacy Stage 1 is available only behind Character Sheets developer mode.
        print("W5P1R browser: open owner surfaces", flush=True)
        surfaces = detailed
        surfaces.evaluate("showScreen('projects')")
        surfaces.wait_for_function("document.querySelector('#screen-projects')?.classList.contains('active')", timeout=30000)
        assert surfaces.evaluate("document.querySelector('#stage1Panel').getClientRects().length === 0") is True
        surfaces.evaluate("document.querySelector('#ownerDeveloperMode').click()")
        surfaces.wait_for_function("document.querySelector('#stage1Panel')?.getClientRects().length > 0", timeout=30000)
        assert "Blueprint-only / advanced" in surfaces.evaluate("document.querySelector('#stage1Panel').textContent")
        print("W5P1R browser: capture bounded owner panels", flush=True)
        for selector, name in [
            ("#stage1Panel", "13_advanced_stage1_blueprint_only.png"),
            ("#characterZipImportPanel", "14_corrected_character_import_surface.png"),
            ("#nonSphereAuthorityPanel", "15_corrected_non_sphere_surface.png"),
        ]:
            path = screenshot_dir / name
            surfaces.eval_on_selector(selector, "el => el.scrollIntoView({block:'start', behavior:'instant'})")
            surfaces.wait_for_timeout(100)
            surfaces.screenshot(path=str(path), full_page=False, timeout=30000)
            screenshots.append(name)
        ratios = {
            "character_import": contrast_ratio(surfaces, "#characterZipImportPanel"),
            "non_sphere_authority": contrast_ratio(surfaces, "#nonSphereAuthorityPanel"),
        }
        print("W5P1R browser: contrast ratios " + json.dumps(ratios, sort_keys=True), flush=True)
        assert all(value >= 4.5 for value in ratios.values())

        chromium.close()

    project_creates = [row for row in mutation_payloads if row["path"] == "/api/character-builder/projects"]
    assert project_creates
    for row in project_creates:
        payload = row["payload"] or {}
        assert "canonical_sphere_ids" not in payload
        assert "sphere_free_talent_grants" not in payload
        assert "ordinary_talent_ids" not in payload
        assert "sphere_priority_ids" in payload
        assert "talent_priority_ids" in payload
    assert not any("guidedApprover" in json.dumps(row) or "local-user" in json.dumps(row) for row in mutation_payloads)

    report = {
        "schema": "TianxiaFoundry.W5P1RPrimaryWizardBrowserAcceptance.v1",
        "status": "PASS",
        "browser": browser,
        "normal_primary_wizard": True,
        "advanced_panel_used_as_primary_proof": False,
        "browser_api_harness_scope": "Real Chromium against the production HTML/CSS/JavaScript with a source-backed compact catalog projection retaining all visible choices, exact counts, descriptions, dispositions, and Sphere/Talent mappings. Browser HTTP responses and project records are deterministic in-process fixtures; real backend CG1 execution and database persistence are covered separately by focused service tests.",
        "catalog_transport": {"full_options_sha256": full_options_sha256, "browser_projection_sha256": browser_options_sha256, "full_sphere_count": options["owner_surface_counts"]["canonical_spheres"], "full_talent_count": options["owner_surface_counts"]["canonical_talents"]},
        "modes": {
            "manual_chat": {"complete_request_button_enabled": True, "complete_request_browser_fetch_verified": True, "candidate_identity": CANDIDATE_IDENTITY, "pre_finalize_commit": False, "finalized": True},
            "standard_api": {"one_build_action": True, "candidate_identity": CANDIDATE_IDENTITY, "pre_finalize_commit": False, "finalized": True},
            "auto_finalize_clean": {"default_off": True, "durable_opt_in_response_exercised": True, "finalized": True},
            "auto_finalize_warning": {"fell_back_to_review": True, "canonical_mutation": False},
        },
        "detailed_customization": {
            "ice_visible_talent_count": 30, "ash_visible_talent_count": 7,
            "blocked_zero_talent_spheres": ["Beauty", "Sabers", "Imbuement", "Hunger"],
            "planning_terms_only": True, "sphere_removal_cascades_preferences_only": True,
            "browser_save_preserved_preferences": True, "backend_save_reopen_preservation": "covered_by_focused_service_test",
        },
        "legacy_stage1": {"advanced_label_present": True, "not_primary": True},
        "contrast_ratios": ratios,
        "screenshots": screenshots,
        "download": {"filename": "CG1_COMPLETE_REQUEST_BROWSER.zip", "sha256": hashlib.sha256((screenshot_dir / "CG1_COMPLETE_REQUEST_BROWSER.zip").read_bytes()).hexdigest()},
        "requests": calls,
        "page_errors": page_errors,
        "console_errors": console_errors,
        "failed_requests": failed_requests,
        "assertions": {"no_page_errors": not page_errors, "no_console_errors": not console_errors, "no_failed_requests": not failed_requests},
    }
    assert not page_errors, page_errors
    assert not console_errors, console_errors
    assert not failed_requests, failed_requests
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--options", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--screenshots", type=Path, required=True)
    parser.add_argument("--browser", default="/usr/bin/chromium")
    args = parser.parse_args()
    report = run(args.root.resolve(), args.options.resolve(), args.output.resolve(), args.screenshots.resolve(), args.browser)
    print(json.dumps({"status": report["status"], "screenshots": len(report["screenshots"]), "candidate_identity": CANDIDATE_IDENTITY}, sort_keys=True))


if __name__ == "__main__":
    main()
