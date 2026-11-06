from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api import create_app
from app.core import Settings


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def persistence_fingerprint(root: Path) -> dict[str, object]:
    files: dict[str, str] = {}
    for relative in ("Combat", "combat", "portable_characters"):
        base = root / relative
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                files[path.relative_to(root).as_posix()] = sha256_file(path)
    database = root / "foundry.sqlite3"
    tables: dict[str, dict[str, object]] = {}
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=30) as connection:
        for table in ("events", "draft_events", "projects", "snapshots", "projection_runs"):
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not exists:
                tables[table] = {"present": False}
                continue
            columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
            rows = connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            payload = json.dumps([dict(zip(columns, row)) for row in rows], sort_keys=True, default=str, separators=(",", ":"))
            tables[table] = {
                "present": True,
                "row_count": len(rows),
                "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            }
    return {"files": files, "tables": tables}


def _run_direct(*, root: Path, data: Path, output: Path, browser: str, screenshot_dir: Path | None = None, force_exit: bool = False) -> dict:
    print("[browser] settings", flush=True)
    settings = Settings.from_env(root, data)
    print("[browser] create app", flush=True)
    app = create_app(settings)
    print("[browser] app created", flush=True)
    source_html = (root / "static/index.html").read_text(encoding="utf-8")
    source_html = re.sub(r'<link[^>]+href="/static/styles\.css[^>]*>', '', source_html)
    source_html = re.sub(r'<script[^>]+src="/static/sphere_talent_logic\.js[^>]*></script>', '', source_html)
    source_html = re.sub(r'<script[^>]+src="/static/app\.js[^>]*></script>', '', source_html)
    source_html = source_html.replace('<head>', '<head><base href="http://c3br1.local/">')
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

    print("[browser] enter clients", flush=True)
    with TestClient(app) as client, sync_playwright() as pw:
        print("[browser] clients entered", flush=True)
        print("[browser] launch chromium", flush=True)
        instance = pw.chromium.launch(executable_path=browser, headless=True, args=["--no-sandbox", "--no-proxy-server"])
        page = instance.new_page(viewport={"width": 1440, "height": 1100})
        page.on("pageerror", lambda exc: (page_errors.append(str(exc)), print(f"[browser pageerror] {exc}", flush=True)))
        page.on("console", lambda msg: (console_errors.append(msg.text), print(f"[browser console] {msg.text}", flush=True)) if msg.type == "error" else None)
        page.on("requestfailed", lambda request: failed_requests.append(f"{request.method} {request.url}: {request.failure}"))

        def serve_api(route, request):
            parsed = urlsplit(request.url)
            if parsed.hostname != "c3br1.local":
                route.abort(); return
            if not parsed.path.startswith("/api/"):
                route.fulfill(status=204, body=""); return
            path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
            forwarded = {"host": "testserver"}
            for key in ("content-type", "x-foundry-token", "x-tianxia-filename"):
                value = request.headers.get(key)
                if value:
                    forwarded[key] = value
            if request.headers.get("origin"):
                forwarded["origin"] = "http://127.0.0.1"
            print(f"[browser api] {request.method} {path}", flush=True)
            response = client.request(request.method, path, headers=forwarded, content=request.post_data_buffer)
            print(f"[browser api] -> {response.status_code} {path}", flush=True)
            route.fulfill(status=response.status_code, headers={"content-type": response.headers.get("content-type", "application/json")}, body=response.content)

        page.route("http://c3br1.local/**", serve_api)
        print("[browser] set content", flush=True)
        page.set_content(source_html, wait_until="domcontentloaded", timeout=30000)
        print("[browser] content set", flush=True)

        print("[browser] character screen", flush=True)
        page.get_by_role("button", name="Character Sheets", exact=True).click()
        character_card = page.locator(".character-library-card").first
        character_card.wait_for(timeout=60000)
        print("[browser] character ready", flush=True)
        character_text = character_card.inner_text()
        character_capture = screenshot_dir / "character_library_layered_readiness.png"
        page.screenshot(path=str(character_capture), full_page=True)
        screenshots.append(str(character_capture))

        print("[browser] advanced screen", flush=True)
        page.get_by_role("button", name="Advanced Status", exact=True).click()
        page.get_by_text("Authenticated producer corpus", exact=True).wait_for(timeout=60000)
        print("[browser] advanced ready", flush=True)
        advanced_text = page.locator("#screen-status").inner_text()
        status_capture = screenshot_dir / "advanced_status_complete_identities.png"
        page.screenshot(path=str(status_capture), full_page=True)
        screenshots.append(str(status_capture))

        print("[browser] combat screen", flush=True)
        page.get_by_role("button", name="Combat", exact=True).click()
        card = page.locator(".combat-candidate-card").filter(has_text="C1A Clean Fire-Qi Proof")
        card.wait_for(timeout=60000)
        print("[browser] combat card ready", flush=True)
        candidate_text = card.inner_text()
        qi = card.locator('[data-field="qi"]')
        focus = card.locator('[data-field="focus"]')
        team = card.locator('[data-field="team"]')
        print("[browser] read initial fields", flush=True)
        initially_empty = qi.input_value(timeout=10000) == "" and focus.input_value(timeout=10000) == "" and team.input_value(timeout=10000) == ""
        print("[browser] fingerprint before", flush=True)
        baseline = persistence_fingerprint(data)
        print("[browser] fingerprint before done", flush=True)
        print("[browser] fill qi", flush=True)
        page.locator(".combat-candidate-card").filter(has_text="C1A Clean Fire-Qi Proof").locator('[data-field="qi"]').fill("11", timeout=10000)
        print("[browser] fill focus", flush=True)
        page.locator(".combat-candidate-card").filter(has_text="C1A Clean Fire-Qi Proof").locator('[data-field="focus"]').fill("1", timeout=10000)
        print("[browser] fill team", flush=True)
        page.locator(".combat-candidate-card").filter(has_text="C1A Clean Fire-Qi Proof").locator('[data-field="team"]').fill("team:c3br1.browser-proof", timeout=10000)
        print("[browser] validate click", flush=True)
        page.locator(".combat-candidate-card").filter(has_text="C1A Clean Fire-Qi Proof").get_by_role("button", name="Validate Pre-Encounter Draft", exact=True).click(timeout=10000)
        result = page.locator("#combatPreEncounterDraftResult")
        result.get_by_text("Draft validated before placement", exact=True).wait_for(timeout=60000)
        print("[browser] draft ready", flush=True)
        result_text = result.inner_text()
        technical_text = result.locator("details pre").text_content() or ""
        draft_capture = screenshot_dir / "pre_encounter_draft_nonpersistent.png"
        page.screenshot(path=str(draft_capture), full_page=True)
        screenshots.append(str(draft_capture))
        result.get_by_role("button", name="Discard Preview", exact=True).click()
        result.get_by_text("Preview discarded. It was never persisted", exact=False).wait_for(timeout=30000)
        discard_text = result.inner_text()
        print("[browser] fingerprint after", flush=True)
        after = persistence_fingerprint(data)
        print("[browser] fingerprint after done", flush=True)

        character_labels = [
            "Combat Sheet ready", "Combat runtime ready", "Pre-encounter", "Setup required",
            "current Qi", "current Martial Focus", "opponent/teams", "battlefield choice",
            "token placement", "initiative", "controllers",
        ]
        candidate_labels = [
            "Pre-Encounter Runtime Ready", "Combat runtime ready", "Encounter setup required",
            "Current Qi required", "Current Martial Focus required", "Opponent / team completion required",
            "Battlefield owner choice not committed", "Token placement not committed",
            "Initiative not attempted", "Controllers not selected",
        ]
        advanced_labels = [
            "Application / process health", "Build and version", "Writable data root", "Project store / database",
            "Authenticated producer corpus", "Factory adapter", "Core catalog", "GM consumer", "Combat runtime",
            "Combatant library", "Native Windows acceptance", "Recent errors",
        ]
        checks = {
            "character_layered_readiness": all(label.casefold() in character_text.casefold() for label in character_labels),
            "candidate_layered_readiness": all(label.casefold() in candidate_text.casefold() for label in candidate_labels),
            "advanced_status_complete": all(label.casefold() in advanced_text.casefold() for label in advanced_labels),
            "resource_fields_initially_empty": initially_empty,
            "draft_validated": "Draft validated before placement" in result_text,
            "draft_nonpersistent_contract": all(token in technical_text for token in ['"persisted_event_count": 0', '"is_match": false', '"persistent": false']),
            "discard_noop": "never persisted" in discard_text,
            "data_fingerprint_unchanged": baseline == after,
            "no_page_errors": not page_errors,
            "no_console_errors": not console_errors,
        }
        report = {
            "schema": "TianxiaFactory.C3BR1LinuxChromiumAcceptance.v1",
            "status": "PASS" if all(checks.values()) else "FAIL",
            "acceptance": "LINUX_CLEAN_ROOT_PRODUCT_ACCEPTANCE",
            "transport_mode": "IN_PROCESS_HTTP_ROUTE_ADAPTER",
            "transport_note": "Chromium exercised the real FastAPI app, JavaScript, DOM, CSRF/session flow, and imported owner data through an in-process HTTP route adapter. Native Windows behavior is not claimed.",
            "data_root": str(data),
            "checks": checks,
            "page_errors": page_errors,
            "console_errors": console_errors,
            "failed_requests": failed_requests,
            "screenshots": screenshots,
            "character_text": character_text,
            "candidate_text": candidate_text,
            "advanced_status_text": advanced_text,
            "draft_text": result_text,
            "draft_technical_text": technical_text,
            "native_windows_status": "NATIVE_WINDOWS_OWNER_ACCEPTANCE_DEFERRED",
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        instance.close()
        print("[browser] chromium closed", flush=True)
        if force_exit:
            os._exit(0 if report["status"] == "PASS" else 1)
    return report


def run(*, root: Path, data: Path, output: Path, browser: str, screenshot_dir: Path | None = None) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    worker_log = output.with_suffix(output.suffix + ".worker.log")
    command = [
        sys.executable, "-u", "-m", "tests.c3br1_browser_harness", "--worker",
        "--root", str(root), "--data", str(data), "--output", str(output),
        "--browser", browser,
    ]
    if screenshot_dir is not None:
        command.extend(["--screenshot-dir", str(screenshot_dir)])
    with worker_log.open("w", encoding="utf-8") as log_handle:
        process = subprocess.Popen(command, cwd=str(root), stdout=log_handle, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 240.0
        while time.monotonic() < deadline:
            if output.is_file():
                try:
                    report = json.loads(output.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    time.sleep(0.1)
                    continue
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=5)
                return report
            code = process.poll()
            if code is not None:
                raise RuntimeError(f"Chromium worker exited {code} before producing {output}. See {worker_log}.")
            time.sleep(0.2)
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=5)
    raise TimeoutError(f"Chromium worker did not produce evidence within 240 seconds. See {worker_log}.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser", default="/usr/bin/chromium")
    parser.add_argument("--screenshot-dir", type=Path)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    function = _run_direct if args.worker else run
    kwargs = dict(root=args.root.resolve(), data=args.data.resolve(), output=args.output.resolve(), browser=args.browser, screenshot_dir=args.screenshot_dir.resolve() if args.screenshot_dir else None)
    if args.worker:
        kwargs["force_exit"] = True
    report = function(**kwargs)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
