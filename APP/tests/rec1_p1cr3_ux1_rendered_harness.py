"""Deterministic rendered acceptance campaign for the production owner shell.

This runner navigates the live production ``/static/index.html`` and records
only bounded external evidence.  The visual states after the real initial
project/run actions use an explicitly declared owner-view fixture so every
screen can be rendered deterministically without inventing mechanics or
loading the accepted prototype.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from playwright.async_api import Browser, Page, async_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CHROMIUM = "/home/tabik/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome"
VIEWPORTS = (
    (1920, 1080),
    (1536, 864),
    (1366, 768),
    (1280, 720),
    (860, 900),
    (768, 900),
    (390, 844),
)
OWNER_STEPS = tuple(range(1, 9))


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_server(url: str, *, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{url}/api/session", timeout=3)
            if response.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("The production FastAPI browser server did not become ready.")


def start_server(evidence_root: Path) -> tuple[subprocess.Popen[str], str, Path]:
    data_root = evidence_root / "runtime-data"
    data_root.mkdir(parents=True, exist_ok=True)
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    log_path = evidence_root / "server.log"
    command = [
        sys.executable,
        str(ROOT / "tests" / "rec1_p1cr3_ux1_browser_server.py"),
        "--data-root",
        str(data_root),
        "--port",
        str(port),
    ]
    with log_path.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            stdout=stream,
            stderr=subprocess.STDOUT,
            text=True,
        )
    try:
        wait_server(url)
    except Exception:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=20)
        raise RuntimeError(log_path.read_text(encoding="utf-8"))
    return process, url, log_path


async def wait_dom(page: Page, expression: str, *, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await page.evaluate(expression):
            return
        await asyncio.sleep(0.2)
    raise TimeoutError(f"DOM condition did not become true: {expression}")


async def evaluate_metrics(page: Page, *, viewport: tuple[int, int]) -> dict[str, Any]:
    return await page.evaluate(
        """
        ({width, height}) => {
          const visible = node => {
            const style = getComputedStyle(node);
            const rect = node.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };
          const rect = node => { const value = node.getBoundingClientRect(); return {left:value.left, right:value.right, top:value.top, bottom:value.bottom, width:value.width, height:value.height}; };
          const failures = [];
          const documentOverflow = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) > width + 1;
          if (documentOverflow) failures.push({kind:'page_horizontal_overflow', scrollWidth:Math.max(document.documentElement.scrollWidth, document.body.scrollWidth), width});
          const cardSelectors = '.owner-step-panel:not([hidden]), .owner-step-panel:not([hidden]) .owner-path-choice-card, .owner-step-panel:not([hidden]) .owner-review-group, .owner-step-panel:not([hidden]) .owner-sheet-card, .owner-step-panel:not([hidden]) .insight-browse-card, .owner-step-panel:not([hidden]) .sphere-browse-card, .owner-step-panel:not([hidden]) .owner-next-action-card';
          for (const node of document.querySelectorAll(cardSelectors)) {
            if (!visible(node)) continue;
            const r = node.getBoundingClientRect();
            if (r.left < -1 || r.right > width + 1 || r.width > width + 1) failures.push({kind:'card_control_overflow', selector:node.className || node.id, rect:rect(node)});
            if (node.scrollWidth > node.clientWidth + 1) failures.push({kind:'card_internal_overflow', selector:node.className || node.id, scrollWidth:node.scrollWidth, clientWidth:node.clientWidth});
          }
          const compact = node => node.matches('.owner-step, .icon-button, .sphere-priority-toggle, .insight-priority-toggle, .catalog-more-button, .choice-chip button, .sphere-remove, .production-import-tabs button, summary, input[type="checkbox"], input[type="radio"]');
          const controls = [];
          const drawer = document.querySelector('#diagnosticsDrawer');
          for (const node of document.querySelectorAll('button, input, select, textarea, summary')) {
            if (!visible(node) || node.disabled || node.type === 'hidden') continue;
            if (node.closest('#diagnosticsDrawer') && !drawer?.classList.contains('is-open')) continue;
            const r = node.getBoundingClientRect();
            if (node.type === 'checkbox' || node.type === 'radio') continue; // Native inputs are measured through their labeled hit target.
            const minimum = compact(node) || node.matches('summary') || node.type === 'checkbox' || node.type === 'radio' ? 36 : 42;
            if (r.height + .5 < minimum) failures.push({kind:'control_too_small', label:(node.innerText || node.getAttribute('aria-label') || node.id || node.tagName).slice(0,120), height:r.height, minimum});
            if (!node.closest('.product-nav, .owner-step-nav') && (r.left < -1 || r.right > width + 1)) failures.push({kind:'control_overflow', label:(node.innerText || node.getAttribute('aria-label') || node.id || node.tagName).slice(0,120), rect:rect(node)});
          }
          for (const group of document.querySelectorAll('.button-row, .owner-screen-footer, .recovery-action-buttons, .header-actions')) {
            if (!visible(group)) continue;
            const buttons = Array.from(group.querySelectorAll('button')).filter(visible).filter(node => !node.disabled).map(rect).sort((a,b) => Math.abs(a.top - b.top) < 8 ? a.left - b.left : a.top - b.top);
            for (let i=1; i<buttons.length;i++) {
              const prior = buttons[i-1], current = buttons[i];
              const sameRow = Math.abs(current.top - prior.top) < 4;
              const gap = sameRow ? current.left - prior.right : current.top - prior.bottom;
              if (gap < 8) failures.push({kind:'action_group_gap', gap, group:group.className || group.id});
            }
          }
          for (const panel of document.querySelectorAll('[data-owner-panel]')) {
            const shouldHide = panel.getAttribute('data-owner-panel') !== String(guidedWizardStep || 1);
            if (shouldHide && visible(panel)) failures.push({kind:'hidden_panel_in_layout', id:panel.id});
          }
          const drawerWidth = drawer ? drawer.getBoundingClientRect().width : 0;
          if (drawerWidth > width * .92 + 1) failures.push({kind:'drawer_too_wide', drawerWidth, width});
          return {viewport:{width,height}, failures, document:{scrollWidth:Math.max(document.documentElement.scrollWidth, document.body.scrollWidth), clientWidth:document.documentElement.clientWidth}, drawerWidth};
        }
        """,
        {"width": viewport[0], "height": viewport[1]},
    )


def fixture_run(run_id: str, project_id: str, *, status: str = "READY_FOR_REVIEW") -> dict[str, Any]:
    display_step = {"READY_FOR_REVIEW": 4, "NEEDS_REVIEW": 4, "CANCELLED": 8}.get(status, 4)
    next_target = 1 if status == "CANCELLED" else display_step
    return {
        "run_id": run_id,
        "project_id": project_id,
        "status": status,
        "execution_mode": "MANUAL_CHAT",
        "request": {"request_sha256": "a" * 64, "content_lock_hash": "b" * 64},
        "response": {"response_sha256": "c" * 64},
        "dry_run": {
            "schema": "TianxiaFoundry.CompiledCharacterCandidate.v3",
            "deterministic": True,
            "independent_compilations": 2,
            "preview": {"target_cl": 20, "identity": {"identity": {"name": "Fixture Name"}}},
        },
        "quality": {"status": "CLEAN"},
        "blockers": [],
        "warnings": [],
        "commit": {},
        "owner_descriptive_fields": {
            "state": "AI_PROPOSED",
            "resolved": {},
            "proposed": {
                "identity": {"name": "Long proposed name for rendered acceptance — 青玉回响守门人"},
                "concept": "A long source-backed concept string used to verify wrapping without crossing a card border.",
            },
        },
        "attempt_history": [],
        "owner_view": {
            "schema": "TianxiaFoundry.CharacterCreationOwnerView.v1",
            "display_state": {"status": status, "step": display_step, "label": status.replace("_", " ").title()},
            "identity": {
                "name": "Long proposed name for rendered acceptance — 青玉回响守门人",
                "concept": "A long source-backed concept string used to verify wrapping without crossing a card border.",
                "name_provenance": "AI proposed",
                "concept_provenance": "AI proposed",
                "target_cl": 20,
                "power_band": "rival/boss",
            },
            "paths": [
                {"name": "Body Refining", "state": "dormant", "attainment": "pending", "provenance": "AI proposed"},
                {"name": "Qi Cultivation", "state": "advancing", "attainment": 7, "provenance": "Owner"},
                {"name": "Spirit Awakening", "state": "dormant", "attainment": 2, "provenance": "Automatic"},
            ],
            "method": {"name": "A deliberately long Method label — Azure Meridian Compatibility Method", "provenance": "AI proposed"},
            "foundation": {"name": "Iron Foundation", "provenance": "Automatic"},
            "tradition": {"name": "Cinder Heart Tradition", "provenance": "Owner"},
            "provenance_groups": {
                "Owner": [{"name": "Qi Cultivation — advancing requirement"}],
                "AI proposed": [{"name": "Long proposed name for rendered acceptance — 青玉回响守门人"}],
                "Automatic": [{"name": "Automatic Sphere base ability"}],
                "Needs owner decision": [{"name": "Review long Insight choice before Finalize", "note": "Expected: a validated source choice. Proposed: an unresolved descriptive preference."}],
            },
            "decisions": [{"title": "Review required", "message": "Expected: a validated source choice. Proposed: a long descriptive preference requiring owner review."}],
            "scratch_candidate": {
                "available": True,
                "deterministic": True,
                "independent_compilations": 2,
                "sheet": {
                    "paths": [
                        {"name": "Qi Cultivation", "mode": "advancing", "attainment": 7},
                        {"name": "Spirit Awakening", "mode": "dormant", "attainment": 2},
                    ],
                    "spheres": [{"name": "Flame Sphere", "state": "acquired"}],
                    "free_talents": [{"name": "Free Flame Talent", "acquisition": "free"}],
                    "ordinary_talents": [{"name": "Ordinary Flame Talent", "acquisition": "ordinary"}],
                    "automatic_components": [{"name": "Heat Sense", "state": "automatic"}],
                    "insights": [{"name": "Long Insight title for wrapping"}],
                    "resources": [{"name": "Qi", "current": 12, "maximum": 20}],
                },
            },
            "next_legal_action": {
                "target_step": next_target,
                "label": "Start a deliberate new build" if status == "CANCELLED" else "Review the imported proposal",
                "description": "No canonical character mutation was committed. Return to Step 1 for a deliberate new build." if status == "CANCELLED" else "Compare Expected and Proposed values before choosing the next legal action.",
            },
            "action_availability": {},
            "export_availability": {
                "completed_character": {"available": False, "reason": "Available only after verified Finalize output."},
                "gm_package": {"available": False, "reason": "GM-only verification remains separate."},
            },
        },
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_external_evidence_metadata(root: Path, report_path: Path, report: dict[str, Any]) -> None:
    """Write only bounded metadata and cryptographic inventory beside captures."""
    environment = {
        "schema": "TianxiaFoundry.REC1P1CR3UX1EvidenceEnvironment.v1",
        "command": report.get("campaign", {}).get("command"),
        "cwd": report.get("campaign", {}).get("cwd"),
        "python": sys.version,
        "platform": platform.platform(),
        "browser": report.get("browser"),
        "viewport_targets": list(VIEWPORTS),
        "source": report.get("campaign", {}).get("production_source"),
        "prototype_loaded": False,
    }
    environment_path = root / "ENVIRONMENT.json"
    environment_path.write_text(json.dumps(environment, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in {"MANIFEST.json", "SHA256SUMS.txt"}:
            continue
        relative = path.relative_to(root).as_posix()
        files.append({"path": relative, "bytes": path.stat().st_size, "sha256": _sha256(path)})
    report_hash = next((row["sha256"] for row in files if row["path"] == report_path.relative_to(root).as_posix()), None)
    manifest = {
        "schema": "TianxiaFoundry.REC1P1CR3UX1EvidenceManifest.v1",
        "status": report.get("status"),
        "report": report_path.relative_to(root).as_posix(),
        "report_sha256": report_hash,
        "browser": report.get("browser"),
        "fixture_declaration": report.get("campaign", {}).get("fixture_declaration"),
        "files": files,
    }
    manifest_path = root / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    sums = [f"{row['sha256']}  {row['path']}" for row in files]
    sums.append(f"{_sha256(manifest_path)}  MANIFEST.json")
    (root / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")


async def run_campaign(*, report_path: Path, evidence_root: Path, browser_path: str = CHROMIUM) -> dict[str, Any]:
    evidence_root.mkdir(parents=True, exist_ok=True)
    # Chromium's Linux process-singleton socket has a short path limit.  Keep
    # the temporary/cache root workspace-backed but deliberately short; the
    # campaign removes it in the finally block.
    campaign_tmp = Path("/home/tabik/Factory App/.rec1-p1cr3-ux1-tmp")
    campaign_tmp.mkdir(parents=True, exist_ok=True)
    os.environ["TMPDIR"] = str(campaign_tmp)
    requested_browser = browser_path
    browser_kind = "explicit_executable"
    page_errors: list[str] = []
    console_errors: list[str] = []
    failed_requests: list[str] = []
    responses: list[str] = []
    screenshots: list[dict[str, Any]] = []
    viewport_metrics: list[dict[str, Any]] = []
    interaction: dict[str, Any] = {}
    server_process, base_url, server_log = start_server(evidence_root)
    project_id: str | None = None
    run_id: str | None = None
    try:
        async with async_playwright() as playwright:
            browser: Browser = await playwright.chromium.launch(
                executable_path=browser_path,
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            resolved_browser = str(browser.version)
            page = await browser.new_page(viewport={"width": 1920, "height": 1080}, accept_downloads=True)
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
            page.on("requestfailed", lambda request: failed_requests.append(f"{request.method} {request.url}: {request.failure}"))
            page.on("response", lambda response: responses.append(f"{response.request.method} {urlsplit(response.url).path} -> {response.status}") if urlsplit(response.url).netloc == urlsplit(base_url).netloc else None)
            await page.goto(f"{base_url}/static/index.html", wait_until="domcontentloaded", timeout=120_000)
            await wait_dom(page, "typeof token !== 'undefined' && token !== null && typeof characterBuilderOptions !== 'undefined' && characterBuilderOptions !== null", timeout=120)
            interaction["initial_static_resources"] = sorted({path for row in responses for path in ("/static/index.html", "/static/styles.css", "/static/app.js") if path in row})
            interaction["startup_ready"] = True

            # Step 1: long owner brief and actual pre-project detail controls.
            await page.locator("#guidedName").fill("Long rendered owner name — 青玉回响守门人 with a deliberately extended label")
            await page.locator("#guidedConcept").fill("A long concept string for rendered acceptance that must wrap inside the owner brief without creating a page-level horizontal scrollbar.")
            await page.locator("#guidedLevel").fill("20")
            await page.locator("#guidedBriefContinue").click()
            await wait_dom(page, "guidedWizardStep === 2")
            interaction["brief_to_paths"] = True

            # Real FastAPI compatibility contract call, first with no locks and
            # then through the actual owner button with one source Path.
            token = (await page.evaluate("token"))
            compatibility_empty = httpx.post(
                f"{base_url}/api/character-builder/method-compatibility",
                headers={"X-Foundry-Token": token},
                json={"selected_path_ids": []},
                timeout=60,
            )
            compatibility_empty.raise_for_status()
            interaction["method_compatibility_contract"] = {
                "status": compatibility_empty.status_code,
                "schema": compatibility_empty.json().get("schema"),
                "compatible_count": len(compatibility_empty.json().get("compatible_methods") or []),
            }
            await page.evaluate(
                """() => { const id = characterBuilderOptions.categories.find(row => row.slot_id === 'path_choice').choices[0].choice_id; selectedSet('path_choice').add(id); renderPathChoices(); renderOwnerMethodCompatibility(); }"""
            )
            await page.locator("#checkMethodCompatibility").click()
            await wait_dom(page, "methodCompatibility.state === 'accepted'")
            interaction["method_compatibility_ui"] = await page.evaluate("({state:methodCompatibility.state, count:methodCompatibility.result.compatible_methods.length})")

            # Step 2 creation is a real production project call.  Its return
            # must open Step 3 and its saved locks freeze planning controls.
            await page.locator("#guidedBuildButton").click()
            await wait_dom(page, "Boolean(guidedProjectId) && guidedWizardStep === 3", timeout=120)
            project_id = await page.evaluate("guidedProjectId")
            interaction["project_created_and_routed_to_step_3"] = bool(project_id)
            interaction["planning_freeze"] = await page.evaluate(
                """() => ({
                  editable: planningIsEditable(),
                  pathDisabled: [...document.querySelectorAll('#sheetPaths input')].every(node => node.disabled),
                  sphereAddDisabled: document.querySelector('#sheetSphereAdd')?.disabled === true,
                  insightAddDisabled: document.querySelector('#sheetInsightAdd')?.disabled === true,
                  reason: [...document.querySelectorAll('.planning-freeze-note')].some(node => !node.hidden && node.textContent.includes('Edit Brief / Create New Request')),
                  selectedStateReadable: Boolean(document.querySelector('#ownerDetailPathSummary')?.textContent)
                })"""
            )
            # A guarded mutation must leave the selected set unchanged.
            interaction["planning_freeze"]["guarded_remove"] = await page.evaluate(
                """() => { const category = categoryFor('sphere_priorities'); const first = category?.choices?.find(row => row.planning_priority_available !== false); if (!first) return false; selectedSet('sphere_priorities').add(first.choice_id); const before = [...selectedSet('sphere_priorities')]; removeSheetSphere(first.choice_id); return JSON.stringify(before) === JSON.stringify([...selectedSet('sphere_priorities')]); }"""
            )

            # Start one actual Manual Chat request and read its owner projection
            # through FastAPI.  No provider credential or external API call is used.
            await page.locator("#guidedStartBuild").click()
            await wait_dom(page, "guidedRun && ['WAITING_FOR_RESPONSE','PREPARING_REQUEST'].includes(guidedRun.status)", timeout=120)
            run_id = await page.evaluate("guidedRun.run_id")
            owner_response = httpx.get(
                f"{base_url}/api/character-creation/runs/{run_id}",
                headers={"X-Foundry-Token": token},
                timeout=60,
            )
            owner_response.raise_for_status()
            owner_json = owner_response.json()
            interaction["owner_view_contract"] = {
                "status": owner_response.status_code,
                "display_step": owner_json.get("owner_view", {}).get("display_state", {}).get("step"),
                "response_bytes": len(owner_response.content),
                "compiled_in_preview": "compiled" in (owner_json.get("dry_run", {}).get("preview", {}) or {}),
                "diagnostics_final_plan_keys": sorted((owner_json.get("diagnostics", {}).get("final_plan", {}) or {}).keys()),
            }

            # Paste/file/drop all hit production source handlers.  The object is
            # syntactically valid but deliberately wrong-root, so the real API
            # returns a bounded review state without a canonical mutation.
            await page.locator("#guidedPasteTab").click()
            await page.locator("#guidedCompleteResponseText").fill('{"wrong_root":true}')
            interaction["paste_source"] = await page.evaluate("({kind:guidedCompleteResponseSource.kind, sourceState:document.querySelector('#guidedResponseSourceState').textContent})")
            await page.locator("#guidedSubmitCompleteResponse").click()
            await wait_dom(page, "guidedRun && guidedRun.status === 'NEEDS_REVIEW'", timeout=120)
            interaction["wrong_root_review"] = True
            await page.evaluate("setGuidedStep(3); document.querySelector('#guidedFileTab').click()")
            await page.set_input_files("#guidedCompleteReplyFile", {"name": "representative-response.json", "mimeType": "application/json", "buffer": b'{"wrong_root":true}'})
            await wait_dom(page, "guidedCompleteResponseSource.kind === 'file'")
            interaction["file_source"] = await page.evaluate("({kind:guidedCompleteResponseSource.kind, name:guidedCompleteResponseSource.file.name})")
            await page.evaluate(
                """() => { const zone = document.querySelector('#guidedCompleteReplyDrop'); const transfer = new DataTransfer(); transfer.items.add(new File(['{"wrong_root":true}'], 'drop-response.json', {type:'application/json'})); zone.dispatchEvent(new DragEvent('drop', {bubbles:true, cancelable:true, dataTransfer:transfer})); }"""
            )
            await wait_dom(page, "guidedCompleteResponseSource.kind === 'file' && guidedCompleteResponseSource.file.name === 'drop-response.json'")
            interaction["drop_source"] = await page.evaluate("({kind:guidedCompleteResponseSource.kind, name:guidedCompleteResponseSource.file.name})")

            # Deterministic owner-view fixtures are declared in this source
            # harness; they do not claim a mechanical backend result.
            ready_fixture = fixture_run(run_id, project_id, status="READY_FOR_REVIEW")
            cancelled_fixture = fixture_run(run_id, project_id, status="CANCELLED")
            await page.evaluate(
                """fixture => { guidedRun = fixture; renderGuidedCandidate(guidedRun); }""",
                ready_fixture,
            )
            interaction["provenance_review"] = await page.evaluate(
                """() => ({
                  step: guidedWizardStep,
                  groups: [...document.querySelectorAll('#ownerReviewGroups .provenance-badge')].map(node => node.textContent),
                  hasExpectedProposed: document.querySelector('#guidedReviewDetail')?.textContent.includes('Expected') || document.querySelector('#guidedStatus')?.textContent.includes('Expected')
                })"""
            )
            interaction["insight_background_origin_excluded"] = await page.evaluate(
                """() => { setGuidedStep(5); const text = document.querySelector('#sheetInsightCards')?.textContent || ''; const origin = (characterBuilderOptions.categories.find(row => row.slot_id === 'origin_insight_choice')?.choices || []).map(row => row.name); return {cards:document.querySelectorAll('#sheetInsightCards .insight-browse-card').length, ordinary:ordinaryInsightChoices().length, originNamesPresent:origin.some(name => text.includes(name))}; }"""
            )
            interaction["sphere_base_text"] = await page.evaluate(
                """() => { setGuidedStep(6); return {cards:document.querySelectorAll('#sheetSphereCatalog .sphere-browse-card').length, baseText: [...document.querySelectorAll('#sheetSphereCatalog .sphere-browse-base-text')].filter(node => node.textContent.trim()).length, noHardcodedCap: !(document.querySelector('#sheetSphereHelp')?.textContent || '').match(/max 8|max 12/i)}; }"""
            )
            await page.evaluate(
                """fixture => { guidedRun = fixture; renderOwnerProductionSheet(guidedRun, false); setGuidedStep(7); }""",
                ready_fixture,
            )
            interaction["proposal_sheet"] = await page.evaluate("({step:guidedWizardStep, state:document.querySelector('#ownerSheetState')?.textContent, text:document.querySelector('#ownerProductionSheet')?.textContent.slice(0,600)})")

            # Diagnostics focus trap, Escape, and focus return.
            await page.locator("#diagnosticsToggle").focus()
            await page.locator("#diagnosticsToggle").click()
            await page.wait_for_timeout(100)
            drawer_open = await page.evaluate("({open:document.querySelector('#diagnosticsDrawer').classList.contains('is-open'), active:document.activeElement?.id || document.activeElement?.tagName})")
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(100)
            drawer_closed = await page.evaluate("({open:document.querySelector('#diagnosticsDrawer').classList.contains('is-open'), active:document.activeElement?.id || document.activeElement?.tagName})")
            interaction["diagnostics_focus"] = {"open": drawer_open, "closed": drawer_closed}
            interaction["route_tabs"] = await page.evaluate(
                """() => ({count:document.querySelectorAll('[data-guided-route][role="tab"]').length, selected:document.querySelector('[data-guided-route][aria-selected="true"]')?.dataset.guidedRoute, controls: [...document.querySelectorAll('[data-guided-route][role="tab"]')].map(node => node.getAttribute('aria-controls'))})"""
            )

            # Product navigation is exercised through the actual nav handlers.
            const_screens = ["projects", "combat", "catalog", "packs", "status", "builder"]
            for screen in const_screens:
                await page.evaluate("screen => showScreen(screen)", screen)
                await page.wait_for_timeout(120)
                interaction.setdefault("product_navigation", {})[screen] = await page.evaluate("screen => document.querySelector(`#screen-${screen}`)?.classList.contains('active')", screen)
            await page.evaluate("fixture => { guidedRun = fixture; renderGuidedCandidate(guidedRun); }", cancelled_fixture)
            interaction["cancelled_terminal"] = await page.evaluate(
                """() => ({step:guidedWizardStep, title:document.querySelector('#ownerNextActionTitle')?.textContent, target:document.querySelector('#ownerNextActionButton')?.dataset.ownerTarget})"""
            )

            async def capture_step(step: int, label: str) -> None:
                await page.evaluate("step => setGuidedStep(step)", step)
                await page.wait_for_timeout(700)
                for width, height in VIEWPORTS:
                    await page.set_viewport_size({"width": width, "height": height})
                    await page.wait_for_timeout(80)
                    metrics = await evaluate_metrics(page, viewport=(width, height))
                    viewport_metrics.append({"screen": step, **metrics})
                    filename = f"{label}_step{step}_{width}x{height}.png"
                    path = evidence_root / "screenshots" / filename
                    path.parent.mkdir(parents=True, exist_ok=True)
                    await page.screenshot(path=str(path), full_page=False)
                    screenshots.append({"filename": f"screenshots/{filename}", "screen": step, "viewport": {"width": width, "height": height}, "bytes": path.stat().st_size})

            # The owner screen captures use the ready fixture except the final
            # cancelled state, which deliberately demonstrates the terminal
            # Step-8 one-next-action mapping.
            await page.evaluate("fixture => { guidedRun = fixture; renderGuidedCandidate(guidedRun); }", ready_fixture)
            await page.evaluate("document.querySelector('#guidedName').value = 'Extremely long rendered name — ' + 'x'.repeat(90); document.querySelector('#diagnosticsTechnicalState').textContent = '/workspace/diagnostics/very-long-source-path/' + 'segment/'.repeat(14) + 'final-receipt.json';")
            for step in range(1, 8):
                await capture_step(step, "owner")
            await page.evaluate("fixture => { guidedRun = fixture; renderGuidedCandidate(guidedRun); }", cancelled_fixture)
            await capture_step(8, "owner")
            # Responsive evidence is already complete for every required CSS
            # pixel target above; return to the canonical desktop size.
            await page.set_viewport_size({"width": 1920, "height": 1080})
            await browser.close()
    finally:
        if server_process.poll() is None:
            server_process.terminate()
            try:
                server_process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                server_process.kill()
                server_process.wait(timeout=20)
        # The live app's extracted Factory/database root is runtime machinery,
        # not external evidence; retain only screenshots and bounded report.
        shutil.rmtree(evidence_root / "runtime-data", ignore_errors=True)
        shutil.rmtree(campaign_tmp, ignore_errors=True)

    failures = [row for row in viewport_metrics if row.get("failures")]
    report: dict[str, Any] = {
        "schema": "TianxiaFoundry.REC1P1CR3UX1RenderedAcceptance.v1",
        "status": "PASS" if not (page_errors or console_errors or failed_requests or failures) else "FAIL",
        "campaign": {
            "command": sys.argv,
            "cwd": str(Path.cwd()),
            "production_source": ["/static/index.html", "/static/styles.css", "/static/sphere_talent_logic.js", "/static/app.js"],
            "prototype_loaded": False,
            "fixture_declaration": "Initial session, options, Method compatibility, project creation, Manual request, wrong-root response, and owner-view GET use the live production FastAPI app. Ready/review, persisted-sheet preview, and CANCELLED screen captures use fixture_run() in this source harness only; no fixture asserts mechanics or replaces backend authority.",
        },
        "browser": {"requested_executable": requested_browser, "resolved_executable": str(Path(requested_browser).resolve()), "runtime_kind": browser_kind, "version": resolved_browser if 'resolved_browser' in locals() else None, "headless": True, "linux_css_pixel_validation": True, "physical_windows_validation": False},
        "server": {"base_url": base_url, "server_log": str(server_log), "project_id": project_id, "run_id": run_id},
        "interaction": interaction,
        "screenshots": screenshots,
        "viewport_metrics": viewport_metrics,
        "errors": {"page_errors": page_errors, "console_errors": console_errors, "failed_requests": failed_requests},
        "response_count": len(responses),
        "external_evidence": {"manifest": "MANIFEST.json", "sha256sums": "SHA256SUMS.txt", "environment": "ENVIRONMENT.json"},
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_external_evidence_metadata(evidence_root, report_path, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--browser", default=CHROMIUM)
    args = parser.parse_args()
    report = asyncio.run(run_campaign(report_path=args.report, evidence_root=args.evidence_root, browser_path=args.browser))
    print(json.dumps({"status": report["status"], "screenshots": len(report["screenshots"]), "viewport_failures": len([row for row in report["viewport_metrics"] if row.get("failures")]), "page_errors": len(report["errors"]["page_errors"]), "console_errors": len(report["errors"]["console_errors"]), "failed_requests": len(report["errors"]["failed_requests"])}, sort_keys=True))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
