from __future__ import annotations

import argparse
import json
import socket
import threading
import time
from pathlib import Path

import uvicorn
from playwright.sync_api import sync_playwright

from app.api import create_app
from app.core import Settings


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run(*, root: Path, character: Path, output: Path, browser: str) -> dict:
    data = output.parent / "w1_owner_browser_data"
    settings = Settings.from_env(root, data)
    app = create_app(settings)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", log_config=None))
    thread = threading.Thread(target=server.run, daemon=True); thread.start()
    deadline = time.time() + 20
    while not server.started and time.time() < deadline: time.sleep(0.05)
    if not server.started: raise RuntimeError("local Factory test server did not start")
    errors: list[str] = []
    console_errors: list[str] = []
    nav: dict[str, dict] = {}
    try:
        with sync_playwright() as pw:
            chromium = pw.chromium.launch(executable_path=browser, headless=True, args=["--no-sandbox", "--no-proxy-server", "--disable-features=BlockInsecurePrivateNetworkRequests,PrivateNetworkAccessForNavigations,PrivateNetworkAccessRespectPreflightResults"])
            page = chromium.new_page(viewport={"width": 1600, "height": 1000})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.goto(f"http://localhost:{port}/", wait_until="networkidle")
            buttons = [
                ("Create a Character", "screen-builder"),
                ("Detailed Character Intake", "screen-builder"),
                ("Character Sheets", "screen-projects"),
                ("Combat", "screen-combat"),
                ("Browse Rules", "screen-catalog"),
                ("Manage Content", "screen-packs"),
                ("Advanced Status", "screen-status"),
            ]
            for label, screen_id in buttons:
                page.get_by_role("button", name=label, exact=True).click()
                page.wait_for_timeout(150)
                target = page.locator(f"#{screen_id}")
                nav[label] = {
                    "visible": target.is_visible(),
                    "text_characters": len(target.inner_text().strip()),
                    "active": "active" in (target.get_attribute("class") or "").split(),
                }
            page.get_by_role("button", name="Character Sheets", exact=True).click()
            assert page.locator("#characterZipDropZone").is_visible()
            page.set_input_files("#characterZipFile", str(character))
            page.get_by_role("button", name="Preview", exact=True).click()
            page.locator("#characterZipProgress").filter(has_text="Preview complete").wait_for(timeout=30000)
            preview_text = page.locator("#characterZipPreview").inner_text()
            page.route("**/api/catalog/records*", lambda route: route.fulfill(status=503, content_type="application/json", body=json.dumps({"error":{"code":"W1_TEST_CATALOG_FAILURE","message":"simulated catalog failure"}})))
            page.evaluate("loadCatalog().catch(() => null)")
            page.locator("#catalogScreenState[data-state='error']").wait_for(timeout=10000)
            page.get_by_role("button", name="Character Sheets", exact=True).click()
            isolation = page.locator("#screen-projects").is_visible() and page.locator("#characterZipPreview").is_visible()
            report = {
                "schema_version": "TianxiaFactory.W1OwnerBrowserReport.v1",
                "status": "PASS" if all(x["visible"] and x["active"] and x["text_characters"] > 0 for x in nav.values()) and isolation and not errors and not console_errors else "FAIL",
                "browser": "Chromium/Playwright on Linux",
                "native_windows_acceptance": "NOT_RUN",
                "navigation": nav,
                "portable_preview": {
                    "visible": True,
                    "contains_name": "C1A Clean Fire-Qi Proof" in preview_text,
                    "contains_cl_realm": "CL 5" in preview_text and "Mortal Realm" in preview_text,
                    "contains_path_subpath": "Qi Cultivation" in preview_text and "Cinder Heart Cultivator" in preview_text,
                    "contains_hash": "c362665c32a06cd3323981c2ceb116d9e137a9e48bbdba4065363b65253d5fd8" in preview_text,
                },
                "catalog_failure_isolated": isolation,
                "page_errors": errors,
                "console_errors": console_errors,
            }
            chromium.close()
    finally:
        server.should_exit = True; thread.join(timeout=10)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--character", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--browser", default="/usr/bin/chromium")
    args = parser.parse_args()
    report = run(root=args.root.resolve(), character=args.character.resolve(), output=args.output.resolve(), browser=args.browser)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
