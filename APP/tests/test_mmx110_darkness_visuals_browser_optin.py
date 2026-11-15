"""Lead-only Chromium screenshots; never run a GUI in the worker sandbox."""
import os
from pathlib import Path

import pytest


@pytest.mark.skipif(os.getenv("SOLFMMX110R2_BROWSER") != "1",
                    reason="Lead must run outside sandbox with SOLFMMX110R2_BROWSER=1")
def test_five_darkness_visuals_in_chromium(tmp_path):
    """Capture the real board/CSS for the lead's by-eye check of contrast and waving."""
    playwright = pytest.importorskip("playwright.sync_api")
    static = Path(__file__).resolve().parents[1] / "static" / "tabletop"
    html = """<!doctype html><link rel="stylesheet" href="/tabletop.css">
      <style>body{margin:0;background:#ddd;color:#111} .case{display:inline-block;width:460px}
      .viewport{width:460px;height:360px;position:relative;overflow:hidden}</style>
      <script type="module">
      import {createBoard} from '/board.js';
      const cases = [ ['Ordinary', 'veil', false], ['Pure', 'pitch', false],
        ['Snagging', 'tentacles', true], ['Clinging', 'tentacles', true],
        ['Pure + Clinging', 'pitch', true] ];
      for (const [name, look, tentacles] of cases) {
        const panel = document.createElement('section'); panel.className = 'case';
        const heading = document.createElement('h2'); heading.textContent = name; panel.append(heading);
        const viewport = document.createElement('div'); viewport.className = 'viewport';
        panel.append(viewport); document.body.append(panel);
        const board = createBoard(viewport);
        board.setMap({width:7, height:5, background:{style:'tiles'}});
        board.setZones([{zone_id:`dark:${name}`, active:true, center:{x:3,y:2}, radius_cells:1,
          affected_cells:[{x:2,y:2},{x:3,y:2},{x:4,y:2},{x:3,y:1},{x:3,y:3}],
          trigger_profile:{kind:'TYPED',name,visual:{material:'darkness',darkness:true,
            darkness_look:look,darkness_tentacles:tentacles}}}], {round:1});
      }
      window.ready = true;
      </script>"""

    def serve(route):
        from urllib.parse import urlparse

        path = urlparse(route.request.url).path
        if path == "/":
            route.fulfill(body=html, content_type="text/html")
        elif path.count("/") == 1 and (static / path[1:]).is_file():
            content_type = "text/css" if path.endswith(".css") else "text/javascript"
            route.fulfill(body=(static / path[1:]).read_bytes(), content_type=content_type)
        else:
            route.abort()

    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        try:
            page = browser.new_page(viewport={"width": 1400, "height": 900}, device_scale_factor=1)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/*", serve)
            page.goto("http://darkness.test/")
            page.wait_for_function("window.ready === true")
            assert page.locator(".tt-zone-air").count() == 5
            assert page.locator(".tt-zone-air .tt-zone-fx").count() == 8
            page.wait_for_timeout(1000)
            page.screenshot(path=str(tmp_path / "darkness-five-looks.png"), full_page=True)
            page.wait_for_timeout(3000)
            page.screenshot(path=str(tmp_path / "darkness-five-looks-later.png"), full_page=True)
            # Seek the real CSS animations across both ends of the out-and-back cycle.
            # No 72-second wait: paused Web Animations still drive computed style and screenshots.
            page.evaluate("""() => {
              window.strandAnimations = [...document.querySelectorAll('.tt-anim-sway')]
                .map(node => ({node, animation: node.getAnimations()[0]}));
              for (const {animation} of window.strandAnimations) animation.pause();
            }""")
            assert page.evaluate("window.strandAnimations.length") == 6
            for boundary in (27000, 36000, 54000, 72000):
                frames = []
                for side, offset in (("before", -16), ("after", 16)):
                    frames.append(page.evaluate("""time => {
                      return window.strandAnimations.map(({node, animation}) => {
                        animation.currentTime = time;
                        const style = getComputedStyle(node);
                        const matrix = new DOMMatrixReadOnly(style.transform);
                        return {x: matrix.m41, y: matrix.m42, direction: style.animationDirection,
                          easing: style.animationTimingFunction};
                      });
                    }""", boundary + offset))
                    page.screenshot(path=str(tmp_path / f"darkness-loop-{boundary}-{side}.png"),
                                    full_page=True)
                for before, after in zip(*frames):
                    assert before["direction"] == after["direction"] == "alternate"
                    assert before["easing"] == after["easing"] == "ease-in-out"
                    assert abs(before["x"] - after["x"]) < 0.5
                    assert abs(before["y"] - after["y"]) < 0.5
            assert not errors
        finally:
            browser.close()
