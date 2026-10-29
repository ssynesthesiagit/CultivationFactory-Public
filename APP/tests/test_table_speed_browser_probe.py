"""Opt-in Slice A network + screenshot gate. Lead runs OUTSIDE sandbox via heavyq."""
import json
import os
import socket
import threading
import time

import pytest

from tools.table_speed_probe import ROOT, fixture


@pytest.mark.skipif(os.environ.get("CF_TABLE_SPEED_BROWSER") != "1",
                    reason="Lead only: Chromium must run outside the worker sandbox")
def test_automatic_turn_network_and_screenshots(tmp_path, monkeypatch):
    from app.api import create_app
    from app.core import Settings
    from playwright.sync_api import sync_playwright
    import uvicorn

    monkeypatch.setenv("CF_EMBED_MENU", "0")
    app = create_app(Settings.from_env(ROOT, tmp_path))
    combat, table = app.state.combat, app.state.agent_seats.table
    mid = fixture(combat, tmp_path, 2, "TABLESPEEDA-BROWSER")
    human = table.state(mid)["menu"]["actor_id"]
    for actor in table.state(mid)["presentation"]["actors"]:
        if actor["entity_id"] != human:
            combat.set_controller_mode(mid, actor_id=actor["entity_id"], controller_mode="LOCAL_AUTO")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    assert port != 8765
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 30
        while not server.started:
            assert thread.is_alive() and time.monotonic() < deadline
            time.sleep(.02)
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
            try:
                page = browser.new_page(viewport={"width": 1400, "height": 900})
                key = "tt-viewer:v1:" + json.dumps(["speed-probe", mid, "binding"], separators=(",", ":"))
                page.add_init_script("sessionStorage.setItem(" + json.dumps(key) + "," +
                    json.dumps(json.dumps({"version": 1, "role": "gm", "actor_ids": []})) + ");")
                page.goto(f"http://127.0.0.1:{port}/tabletop?match={mid}&view=speed-probe")
                page.wait_for_function("window.tabletop?.app.menu?.manual", timeout=180000)
                page.screenshot(path=str(tmp_path / "desktop-before.png"), full_page=True)
                paths, interior, ended = [], [], []
                def requested(request):
                    path = request.url.split("?")[0].rsplit("/", 1)[-1]
                    paths.append(path)
                    if "automatic-run" in paths and not ended:
                        interior.append(path)
                def received(response):
                    if response.url.split("?")[0].endswith("/seat-status") and "automatic-run" in paths:
                        if not response.json().get("running"):
                            ended.append(True)
                page.on("request", requested)
                page.on("response", received)
                with page.expect_response(lambda response: response.url.endswith("/automatic-run"), timeout=180000):
                    page.evaluate("async () => {const t=window.tabletop; await t.act(t.app.menu.end_turn);}")
                page.screenshot(path=str(tmp_path / "desktop-running.png"), full_page=True)
                page.wait_for_function(
                    "window.tabletop.app.menu?.manual && !window.tabletop.app.playing && !window.tabletop.app.automaticRun",
                    timeout=180000)
                assert paths.count("automatic-run") == 1
                assert "auto-step" not in interior and "state" not in interior
                page.screenshot(path=str(tmp_path / "desktop-after.png"), full_page=True)
                phone = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
                phone.goto(f"http://127.0.0.1:{port}/play?match={mid}&actor={human}")
                phone.wait_for_function("document.querySelector('#mapCover').hidden", timeout=180000)
                phone.screenshot(path=str(tmp_path / "phone-human-menu.png"), full_page=True)
                (tmp_path / "network.json").write_text(json.dumps({"paths": paths, "interior": interior}, indent=2))
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(15)
        sock.close()
    assert not thread.is_alive()
