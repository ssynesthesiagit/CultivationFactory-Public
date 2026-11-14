"""Lead-only rendered blink check. Run outside the sandbox with CF_MMX94_BROWSER=1.

Serves only checkout static assets on loopback; uses no application service or live data.
"""
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import threading

import pytest


@pytest.mark.skipif(os.environ.get("CF_MMX94_BROWSER") != "1", reason="lead runs Chromium outside the sandbox")
def test_rendered_teleport_and_carried_light():
    playwright = pytest.importorskip("playwright.sync_api")

    class StaticHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            pass

    static = Path(__file__).resolve().parents[1] / "static"
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(StaticHandler, directory=str(static)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
            try:
                page = browser.new_page(reduced_motion="no-preference")
                origin = f"http://127.0.0.1:{server.server_port}"
                page.goto(origin)
                page.set_content(f'<link rel="stylesheet" href="{origin}/tabletop/tabletop.css"><div id="host"></div>')
                result = page.evaluate("""async () => {
                  await Promise.all([...document.querySelectorAll('link')].map(link =>
                    link.sheet ? Promise.resolve() : new Promise(resolve => link.onload = resolve)));
                  const {createBoard} = await import('/tabletop/board.js');
                  const board = createBoard(document.querySelector('#host'));
                  const fighter = {id:'a', x:1, y:1, name:'Torch carrier', hp:10, maxHp:10,
                    conditions:[], size:1, scale:1, light:{radius_ft:20, color:'#ffd28a', level:'bright'}};
                  board.setTokens([fighter]);
                  const token = board.tokenNode('a'), light = document.querySelector('.tt-light');
                  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
                  await wait(600); // initial fade-in has finished
                  // First pass observes native transition events only: computed-style sampling must not accidentally
                  // flush a buggy relocation and thereby prevent the very slide this check should detect.
                  const slideTransitions = [];
                  const onTransition = event => {
                    if (event.propertyName === 'transform') slideTransitions.push(event.target.className);
                  };
                  token.addEventListener('transitionrun', onTransition);
                  light.addEventListener('transitionrun', onTransition);
                  await board.animateMove('a', [{x:1,y:1},{x:9,y:9}], {teleport:true,stepMs:1});
                  await wait(250);
                  token.removeEventListener('transitionrun', onTransition);
                  light.removeEventListener('transitionrun', onTransition);
                  board.setTokens([fighter]);
                  await wait(600);
                  const samples = [];
                  const inspect = node => {
                    const css = getComputedStyle(node);
                    return {x:new DOMMatrixReadOnly(css.transform).m41, opacity:Number(css.opacity),
                      duration:css.transitionDuration, animation:css.animationName,
                      blinking:node.classList.contains('is-blinking')};
                  };
                  let sampling = true;
                  const sample = () => {
                    samples.push({token:inspect(token), light:inspect(light)});
                    if (sampling) requestAnimationFrame(sample);
                  };
                  sample();
                  await board.animateMove('a', [{x:1,y:1},{x:9,y:9}], {teleport:true,stepMs:1});
                  await wait(250); // observe restored styles and fade-in too
                  sampling = false;
                  await new Promise(requestAnimationFrame);
                  const landed = {token:inspect(token),light:inspect(light)};
                  const old = board.animateMove('a', [{x:9,y:9},{x:3,y:3}], {teleport:true});
                  await wait(25);
                  const walk = board.animateMove('a', [{x:9,y:9},{x:10,y:9}], {stepMs:10});
                  const visibleWalk = !token.classList.contains('is-blinking') && !light.classList.contains('is-blinking');
                  await Promise.all([old,walk]);
                  await wait(200);
                  const walkX = inspect(token).x;
                  const first = board.animateMove('a', [{x:10,y:9},{x:3,y:3}], {teleport:true});
                  await wait(25);
                  const second = board.animateMove('a', [{x:10,y:9},{x:2,y:2}], {teleport:true});
                  await Promise.all([first,second]);
                  await wait(200);
                  return {slideTransitions,samples,landed,visibleWalk,walkX,blinkX:inspect(token).x};
                }""")
                assert result["slideTransitions"] == [], result["slideTransitions"]
                for member, origin_x, target_x in [("token", 64, 576), ("light", 96, 608)]:
                    samples = [row[member] for row in result["samples"]]
                    assert all(min(abs(row["x"] - origin_x), abs(row["x"] - target_x)) < 0.5 for row in samples), samples
                    relocated = next(row for row in samples if abs(row["x"] - target_x) < 0.5)
                    assert relocated["blinking"] and relocated["opacity"] < 0.03, relocated
                    assert relocated["duration"].split(",")[0].strip() == "0s", relocated
                    assert result["landed"][member]["opacity"] > 0.8
                    assert not result["landed"][member]["blinking"]
                assert all(row["light"]["animation"] == "none" for row in result["samples"] if row["light"]["blinking"])
                assert result["landed"]["light"]["animation"] == "tt-light-breathe"
                assert result["visibleWalk"]
                assert abs(result["walkX"] - 640) < 0.5
                assert abs(result["blinkX"] - 128) < 0.5
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
