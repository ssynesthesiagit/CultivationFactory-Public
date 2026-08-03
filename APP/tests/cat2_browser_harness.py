from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api import create_app
from app.core import Settings
from tests.c3br1_browser_harness import persistence_fingerprint

ASH = "tianxia.sphere.ash"
AIR = "tianxia.sphere.air"
ASH_FREE = "ASH_TAL_ASHEN_BURIAL"
ASH_ORDINARY = "ASH_TAL_CINDER_BURST"
AIR_FREE = "TAL_AIR_AIRLESS_STEP"
AIR_GATED = "TAL_AIR_BREATH_OF_NO_DISTANCE"


def _run_direct(*, root: Path, data: Path, output: Path, browser: str, screenshot_dir: Path | None = None, base_url: str | None = None, force_exit: bool = False) -> dict:
    app = None
    if base_url is None:
        print("[cat2] settings", flush=True)
        settings = Settings.from_env(root, data)
        print("[cat2] create app", flush=True)
        app = create_app(settings)
        print("[cat2] app created", flush=True)
    source_html = (root / "static/index.html").read_text(encoding="utf-8")
    source_html = re.sub(r'<link[^>]+href="/static/styles\.css[^>]*>', '', source_html)
    source_html = re.sub(r'<script[^>]+src="/static/sphere_talent_logic\.js[^>]*></script>', '', source_html)
    source_html = re.sub(r'<script[^>]+src="/static/app\.js[^>]*></script>', '', source_html)
    source_html = source_html.replace('<head>', '<head><base href="http://cat2.local/">')
    styles = (root / "static/styles.css").read_text(encoding="utf-8")
    sphere_script = (root / "static/sphere_talent_logic.js").read_text(encoding="utf-8")
    app_script = (root / "static/app.js").read_text(encoding="utf-8")
    source_html = source_html.replace('</head>', f'<style>{styles}</style></head>')
    source_html = source_html.replace('</body>', f'<script>{sphere_script}</script><script>{app_script}</script></body>')

    page_errors: list[str] = []
    console_errors: list[str] = []
    failed_requests: list[str] = []
    screenshots: list[str] = []
    screenshot_dir = screenshot_dir or output.parent / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    print("[cat2] enter clients", flush=True)
    with ExitStack() as stack:
        client = stack.enter_context(TestClient(app)) if app is not None else stack.enter_context(httpx.Client(base_url=base_url, timeout=180.0))
        pw = stack.enter_context(sync_playwright())
        print("[cat2] launch browser", flush=True)
        instance = pw.chromium.launch(executable_path=browser, headless=True, args=["--no-sandbox", "--no-proxy-server"])
        page = instance.new_page(viewport={"width": 1600, "height": 1200})
        page.on("pageerror", lambda exc: (page_errors.append(str(exc)), print(f"[cat2 pageerror] {exc}", flush=True)))
        page.on("console", lambda msg: (console_errors.append(msg.text), print(f"[cat2 console] {msg.text}", flush=True)) if msg.type == "error" else None)
        page.on("requestfailed", lambda request: (failed_requests.append(f"{request.method} {request.url}: {request.failure}"), print(f"[cat2 requestfailed] {request.method} {request.url}: {request.failure}", flush=True)))

        def serve_api(route, request):
            parsed = urlsplit(request.url)
            if parsed.hostname != "cat2.local":
                route.abort(); return
            if not parsed.path.startswith("/api/"):
                route.fulfill(status=204, body=""); return
            path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
            forwarded = {"host": "testserver"} if base_url is None else {}
            for key in ("content-type", "x-foundry-token", "x-tianxia-filename"):
                value = request.headers.get(key)
                if value:
                    forwarded[key] = value
            if request.headers.get("origin"):
                forwarded["origin"] = "http://127.0.0.1"
            print(f"[cat2 api] {request.method} {path}", flush=True)
            # Playwright's synchronous route callback can deadlock when a
            # multi-megabyte TestClient response is produced inside that same
            # callback. Execute the exact Stage 1 service for this one route and
            # fulfill the same compact API projection; a separate HTTP test
            # exercises the CSRF/API transport contract directly.
            prompt_match = re.fullmatch(r"/api/projects/([^/]+)/stage1/prompt", parsed.path)
            if request.method == "POST" and prompt_match:
                # This browser proof is scoped to canonical catalog/grant UI and
                # project persistence. A dedicated TestClient regression invokes
                # the real Stage 1 endpoint and verifies its sealed bytes. Avoid
                # re-entering the database from Playwright's synchronous route
                # callback, which can deadlock in this container bridge.
                payload = json.dumps({
                    "prompt_id": "cat2.browser.transport-adapter",
                    "project_id": prompt_match.group(1),
                    "project_revision": 0,
                    "prompt_sha256": "0" * 64,
                    "prompt_text": "CAT2 browser transport adapter; exact Stage 1 API is tested separately.",
                    "created_at": "1970-01-01T00:00:00Z",
                    "deterministic": True,
                }, separators=(",", ":")).encode("utf-8")
                print(f"[cat2 api] -> 200 {len(payload)} (browser-only transport adapter)", flush=True)
                route.fulfill(status=200, headers={"content-type": "application/json"}, body=payload)
                return
            response = client.request(request.method, path, headers=forwarded, content=request.post_data_buffer)
            print(f"[cat2 api] -> {response.status_code} {len(response.content)}", flush=True)
            route.fulfill(status=response.status_code, headers={"content-type": response.headers.get("content-type", "application/json")}, body=response.content)

        page.route("http://cat2.local/**", serve_api)
        print("[cat2] set content", flush=True)
        page.set_content(source_html, wait_until="domcontentloaded", timeout=30000)
        print("[cat2] content set", flush=True)
        page.wait_for_timeout(5000)
        print(f"[cat2] option status now: {page.locator('#sheetOptionsStatus').text_content()}", flush=True)
        option_status = page.locator("#sheetOptionsStatus").text_content() or ""
        if "ready" not in option_status.casefold():
            raise AssertionError(f"Character options did not become ready: {option_status}")
        print("[cat2] options ready", flush=True)

        # Browse Rules: ordinary current view is exactly 85 canonical Spheres.
        print("[cat2] browse", flush=True)
        page.get_by_role("button", name="Browse Rules", exact=True).click()
        page.wait_for_timeout(1000)
        print(f"[cat2] catalog status: {page.locator('#catalogScreenState').text_content()} rows={page.locator('#catalogRows tr').count()}", flush=True)
        catalog_status = page.locator("#catalogScreenState").text_content() or ""
        if "85 rules loaded" not in catalog_status:
            raise AssertionError(f"Browse Rules did not load exactly 85 Spheres: {catalog_status}")
        catalog_rows = page.locator("#catalogRows tr")
        browse_count = catalog_rows.count()
        ash_row = catalog_rows.filter(has_text="Ash").first
        ash_row.click()
        page.locator("#catalogDetail").filter(has_text="tianxia.sphere.ash").wait_for(timeout=60000)
        browse_detail = page.locator("#catalogDetail").text_content() or ""
        capture = screenshot_dir / "cat2_browse_rules_85_spheres.png"
        page.screenshot(path=str(capture), full_page=False); screenshots.append(str(capture))

        # Character Creator: automatic grants + required free grants + ordinary route.
        print("[cat2] creator", flush=True)
        page.get_by_role("button", name="Detailed Character Intake", exact=True).click()
        print(f"[cat2] detailed clicked hidden={page.locator('#characterSheetPanel').get_attribute('hidden')}", flush=True)
        page.locator("#characterSheetPanel").wait_for(state="visible", timeout=60000)
        print("[cat2] detailed visible", flush=True)
        page.fill("#guidedName", "CAT2 Chromium Owner Flow")
        page.fill("#guidedConcept", "Noncanonical browser fixture proving canonical catalog integration and preservation.")
        page.fill("#guidedLevel", "20")
        for sphere_id in (ASH, AIR):
            print(f"[cat2] add sphere {sphere_id}", flush=True)
            page.select_option("#sheetSphereAdd", sphere_id)
            page.get_by_role("button", name="Add Sphere", exact=True).click()
        print("[cat2] spheres added", flush=True)
        base_grants = page.locator(".automatic-base-abilities li")
        automatic_text = "\n".join(base_grants.all_inner_texts())

        def choose(sphere_id: str, talent_id: str, button_name: str):
            print(f"[cat2] choose {sphere_id} {talent_id} {button_name}", flush=True)
            activate = page.locator('.sphere-card .sphere-activate').filter(has_text=("Ash" if sphere_id == ASH else "Air"))
            print(f"[cat2] activate count {activate.count()}", flush=True)
            activate.click(timeout=10000)
            row = page.locator(f'#sheetTalentOptions [data-talent-id="{talent_id}"]')
            print(f"[cat2] row count {row.count()}", flush=True)
            row.wait_for(timeout=30000)
            selector = "button.talent-free-grant" if button_name == "Use Free Grant" else "button.talent-toggle"
            button = row.locator(selector)
            print(f"[cat2] button count {button.count()} text={button.inner_text() if button.count() else None!r} disabled={button.is_disabled() if button.count() else None}", flush=True)
            if button.count() != 1:
                raise AssertionError(f"Expected exactly one {button_name} control for {talent_id}; found {button.count()}")
            button.click(timeout=10000)
            print("[cat2] chosen", flush=True)

        choose(ASH, ASH_FREE, "Use Free Grant")
        choose(ASH, ASH_ORDINARY, "Add Ordinary")
        choose(AIR, AIR_FREE, "Use Free Grant")
        choose(AIR, AIR_GATED, "Add Ordinary")
        free_state_before = page.evaluate("Object.fromEntries(sheetFreeTalentGrants.entries())")
        ordinary_state_before = page.evaluate("Array.from(selectedSet('advancement_skeleton'))")
        creator_capture = screenshot_dir / "cat2_creator_grant_accounting.png"
        page.screenshot(path=str(creator_capture), full_page=False); screenshots.append(str(creator_capture))

        print("[cat2] submit", flush=True)
        page.get_by_role("button", name="Start This Character", exact=True).click()
        page.locator("#guidedPrompt").wait_for(state="visible", timeout=120000)
        page.get_by_role("button", name="Save Draft", exact=True).click()
        page.locator("#guidedPersistenceLabel").filter(has_text="Saved Draft").wait_for(timeout=60000)
        project_id = page.evaluate("guidedProjectId")
        saved_detail = page.evaluate("async (projectId) => await api(`/api/projects/${encodeURIComponent(projectId)}`)", project_id)
        print("[cat2] saved detail fetched", flush=True)
        saved_locks = {row["field"]: row["value"] for row in saved_detail["project"]["user_locks"]}
        saved_plan = saved_locks["character_sheet.canonical_grant_plan"]

        # Reopen the exact saved locks through the product's browser restore
        # function. Stage 1 prompt transport is independently verified and is
        # intentionally not regenerated for this CAT2 persistence assertion.
        print("[cat2] restore saved locks", flush=True)
        page.evaluate("locks => { setGuidedStep(1); resetCharacterSheet(); setCreationMode('detailed'); restoreCharacterSheet(locks); }", saved_locks)
        page.wait_for_timeout(500)
        print("[cat2] restored", flush=True)
        free_state_reopen = page.evaluate("Object.fromEntries(sheetFreeTalentGrants.entries())")
        ordinary_state_reopen = page.evaluate("Array.from(selectedSet('advancement_skeleton'))")

        # Earlier prerequisite change removes the now-illegal CL-gated ordinary selection.
        print("[cat2] invalidate level", flush=True)
        page.fill("#guidedLevel", "1")
        page.dispatch_event("#guidedLevel", "change")
        page.wait_for_timeout(300)
        invalidation_notice = page.locator("#sheetSphereTalentNotice").text_content() or ""
        gated_still_selected = page.locator(f'[data-talent-id="{AIR_GATED}"].selected').count() > 0
        # The creator-state screenshot above is retained as visual evidence.
        # Avoid a second capture here because Chromium's container renderer can
        # stall on the post-invalidation DOM despite the state transition being
        # directly asserted below.

        # Existing Character, GM/status, combatant, and pre-encounter flow preservation.
        print("[cat2] preservation", flush=True)
        page.get_by_role("button", name="Character Sheets", exact=True).click()
        character_card = page.locator(".character-library-card").filter(has_text="C1A Clean Fire-Qi Proof")
        character_card.wait_for(timeout=120000)
        character_text = character_card.inner_text()
        page.get_by_role("button", name="Advanced Status", exact=True).click()
        page.get_by_text("Canonical catalog authority", exact=True).wait_for(timeout=120000)
        advanced_text = page.locator("#screen-status").inner_text()

        page.get_by_role("button", name="Combat", exact=True).click()
        card = page.locator(".combat-candidate-card").filter(has_text="C1A Clean Fire-Qi Proof")
        card.wait_for(timeout=120000)
        candidate_text = card.inner_text()
        initially_empty = all(card.locator(f'[data-field="{field}"]').input_value() == "" for field in ("qi", "focus", "team"))
        baseline = persistence_fingerprint(data)
        card.locator('[data-field="qi"]').fill("11")
        card.locator('[data-field="focus"]').fill("1")
        card.locator('[data-field="team"]').fill("team:cat2.browser-proof")
        card.get_by_role("button", name="Validate Pre-Encounter Draft", exact=True).click()
        result = page.locator("#combatPreEncounterDraftResult")
        result.get_by_text("Draft validated before placement", exact=True).wait_for(timeout=120000)
        result_text = result.inner_text()
        technical_text = result.locator("details pre").text_content() or ""
        result.get_by_role("button", name="Discard Preview", exact=True).click()
        result.get_by_text("Preview discarded. It was never persisted", exact=False).wait_for(timeout=60000)
        discard_text = result.inner_text()
        after = persistence_fingerprint(data)

        checks = {
            "browse_rules_exactly_85_canonical_spheres": browse_count == 85,
            "browse_rules_full_description_and_source": all(token in browse_detail for token in ("full_description", "source_reference", "tianxia.sphere.ash")),
            "automatic_base_abilities_visible_and_non_costed": base_grants.count() >= 2 and "Granted automatically" in automatic_text and "costs 0 talent" in automatic_text,
            "two_required_free_grants_selected": free_state_before == {ASH: ASH_FREE, AIR: AIR_FREE},
            "ordinary_talents_separate": set(ordinary_state_before) == {ASH_ORDINARY, AIR_GATED},
            "save_reopen_preserves_free_routes": free_state_reopen == free_state_before and len(saved_plan["grant_accounting"]["free_sphere_talent_grants"]) == 2,
            "save_reopen_preserves_ordinary_routes": set(ordinary_state_reopen) == set(ordinary_state_before) and saved_plan["grant_accounting"]["ordinary_talent_cost_count"] == 2,
            "prerequisite_change_invalidates_dependent_choice": not gated_still_selected and "no longer satisfies exact authority" in invalidation_notice,
            "canonical_status_visible": "canonical_sphere_count" in advanced_text and "2989" in advanced_text,
            "character_library_preserved": "C1A Clean Fire-Qi Proof" in character_text and "Combat runtime ready" in character_text,
            "combatant_library_preserved": "Pre-Encounter Runtime Ready" in candidate_text,
            "resource_fields_initially_empty": initially_empty,
            "draft_validated": "Draft validated before placement" in result_text,
            "draft_nonpersistent_contract": all(token in technical_text for token in ('"persisted_event_count": 0', '"is_match": false', '"persistent": false')),
            "discard_noop": "never persisted" in discard_text,
            "combat_persistence_unchanged": baseline == after,
            "no_page_errors": not page_errors,
            "no_console_errors": not console_errors,
            "no_failed_requests": not failed_requests,
        }
        report = {
            "schema": "TianxiaFactory.CAT2LinuxChromiumAcceptance.v1",
            "status": "PASS" if all(checks.values()) else "FAIL",
            "acceptance": "LINUX_CANONICAL_CATALOG_PRODUCT_ACCEPTANCE",
            "transport_mode": "LOOPBACK_UVICORN_HTTP_ROUTE_PROXY" if base_url else "IN_PROCESS_HTTP_ROUTE_ADAPTER",
            "stage1_prompt_transport_mode": "BROWSER_ONLY_COMPACT_ADAPTER_EXACT_API_TESTED_SEPARATELY",
            "data_root": str(data),
            "checks": checks,
            "page_errors": page_errors,
            "console_errors": console_errors,
            "failed_requests": failed_requests,
            "screenshots": screenshots,
            "project_id": project_id,
            "selected_free_grants_before_save": free_state_before,
            "selected_ordinary_talents_before_save": ordinary_state_before,
            "selected_free_grants_after_reopen": free_state_reopen,
            "selected_ordinary_talents_after_reopen": ordinary_state_reopen,
            "saved_grant_accounting": saved_plan["grant_accounting"],
            "invalidation_notice": invalidation_notice,
            "native_windows_status": "NATIVE_WINDOWS_OWNER_ACCEPTANCE_DEFERRED",
        }
        print(f"[cat2] checks {checks}", flush=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        instance.close()
        if force_exit:
            os._exit(0 if report["status"] == "PASS" else 1)
    return report


def run(*, root: Path, data: Path, output: Path, browser: str, screenshot_dir: Path | None = None, base_url: str | None = None) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    worker_log = output.with_suffix(output.suffix + ".worker.log")
    command = [sys.executable, "-u", "-m", "tests.cat2_browser_harness", "--worker", "--root", str(root), "--data", str(data), "--output", str(output), "--browser", browser]
    if base_url is not None:
        command.extend(["--base-url", base_url])
    if screenshot_dir is not None:
        command.extend(["--screenshot-dir", str(screenshot_dir)])
    with worker_log.open("w", encoding="utf-8") as log_handle:
        process = subprocess.Popen(command, cwd=str(root), stdout=log_handle, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 420.0
        while time.monotonic() < deadline:
            if output.is_file():
                report = json.loads(output.read_text(encoding="utf-8"))
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.terminate(); process.wait(timeout=10)
                return report
            code = process.poll()
            if code is not None:
                raise RuntimeError(f"CAT2 Chromium worker exited {code}; see {worker_log}")
            time.sleep(0.2)
        process.terminate(); process.wait(timeout=10)
    raise TimeoutError(f"CAT2 Chromium worker did not produce evidence; see {worker_log}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser", default="/usr/bin/chromium")
    parser.add_argument("--screenshot-dir", type=Path)
    parser.add_argument("--base-url")
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    kwargs = {"root": args.root.resolve(), "data": args.data.resolve(), "output": args.output.resolve(), "browser": args.browser, "screenshot_dir": args.screenshot_dir.resolve() if args.screenshot_dir else None, "base_url": args.base_url}
    if args.worker:
        report = _run_direct(**kwargs, force_exit=True)
    else:
        report = run(**kwargs)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
