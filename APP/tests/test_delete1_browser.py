"""Opt-in rendered DELETE1 checks; lead must run outside the worker sandbox.

DELETE1_BROWSER_TESTS=1 pytest -p no:cacheprovider \
  --basetemp=/var/tmp/delete1-pytest tests/test_delete1_browser.py
Uses a local static server and mocked API responses, never live character data.
"""
import json
import os
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.getenv("DELETE1_BROWSER_TESTS") != "1", reason="Lead must opt in outside the sandbox; no GUI in worker runs.")


def test_draft_and_archived_delete_dialog_and_confirmation():
    from playwright.sync_api import sync_playwright, expect

    static = Path(__file__).resolve().parents[1] / "static"
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def translate_path(self, path):
            # index.html uses the application's /static/ asset URLs, while this
            # probe server's document root is already the static directory.
            if path.startswith("/static/"):
                path = path[len("/static"):]
            return super().translate_path(path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(static)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    draft_id = "00000000-0000-4000-8000-000000000001"
    archived_id = "00000000-0000-4000-8000-000000000002"
    draft = {"project_id": draft_id, "name": "Unwanted Draft", "lifecycle": {"persistence_state": "saved_draft"}, "workflow": {}}
    archived = {"project_id": archived_id, "working_name": "Archived Test", "archived_at": "2026-10-01T00:00:00Z", "builder_lifecycle": {"persistence_state": "completed"}}
    requests = []
    deleted = set()
    def route_api(route):
        path = route.request.url.split("/api/", 1)[1]
        if path.endswith("/delete-permanently"):
            pid = path.split("/")[1]
            requests.append((pid, route.request.post_data_json, route.request.headers.get("x-foundry-token")))
            deleted.add(pid)
            payload = {"queued": True}
        elif path.endswith("/undo-delete"):
            deleted.discard(path.split("/")[1])
            payload = {"queued": False}
        elif path == "session":
            payload = {"token": "scratch-token"}
        elif path == "character-library":
            payload = [] if draft_id in deleted else [draft]
        elif path == "character-library/archived":
            payload = ([] if archived_id in deleted else [archived]) + [
                {**(draft if pid == draft_id else archived), "deletion_status": "queued"}
                for pid in sorted(deleted)
            ]
        elif path in {"projects", "characters", "character-builder/recovery"}:
            payload = []
        else:
            payload = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"], headless=True)
            try:
                page = browser.new_page()
                page.route("**/api/**", route_api)
                page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
                page.evaluate("async () => { token = 'scratch-token'; await renderCharacterLibrary(); document.getElementById('screen-projects').hidden = false; document.getElementById('screen-projects').classList.add('active'); }")
                draft_card = page.locator(f'[data-character-project-id="{draft_id}"]')
                expect(draft_card.get_by_role("button", name="Delete permanently", exact=True)).to_have_count(1)
                dialogs = []
                def reject(dialog):
                    dialogs.append(dialog.message)
                    dialog.dismiss()
                page.on("dialog", reject)
                draft_card.get_by_role("button", name="Delete permanently", exact=True).click()
                assert "Unwanted Draft" in dialogs[0] and "backups/deleted-characters" in dialogs[0]
                assert requests == []
                page.remove_listener("dialog", reject)
                page.on("dialog", lambda dialog: dialog.accept())
                draft_card.get_by_role("button", name="Delete permanently", exact=True).click()
                expect(draft_card).to_have_count(0)
                page.get_by_role("button", name="Show archived and hidden characters", exact=True).click()
                expect(draft_card).to_contain_text("Will be deleted when the Factory next restarts")
                expect(draft_card.get_by_role("button", name="Undo delete", exact=True)).to_have_count(1)
                archived_card = page.locator(f'[data-character-project-id="{archived_id}"]')
                expect(archived_card).to_contain_text("Archived Test")
                expect(archived_card).to_contain_text("Archived character")
                archived_card.get_by_role("button", name="Delete permanently", exact=True).click()
                expect(archived_card).to_contain_text("Will be deleted when the Factory next restarts")
                assert requests == [(draft_id, {"confirm_project_id": draft_id}, "scratch-token"), (archived_id, {"confirm_project_id": archived_id}, "scratch-token")]
                archived_card.get_by_role("button", name="Undo delete", exact=True).click()
                expect(archived_card).to_contain_text("Archived character")
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
