"""Opt-in rendered checks for the app styles (OPUSUI1 review fixes, OPUSUI1f1); the lead runs them.

CF_UI_BROWSER=1 pytest -p no:cacheprovider --basetemp=/var/tmp/opusui1-browser tests/test_ui_themes_browser.py

Uses /usr/bin/chromium (--no-sandbox), a local static server and stubbed API answers; no live data.
- Reduce motion (the player's choice or the system setting) keeps table toasts readable until removed;
- Text size enlarges table and sheet text (condition pills, action names, costs, buttons);
- Settings > Appearance: Save / Undo, inherited text/background pairs as rendered, custom palettes;
- the active builder step's small hint stays readable on the accent fill it inherits (OPUSUI1f2).
"""
from __future__ import annotations

import json
import os
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.getenv("CF_UI_BROWSER") != "1",
                                reason="Rendered UI checks are opt-in (CF_UI_BROWSER=1); the lead runs them.")

STATIC = Path(__file__).resolve().parents[1] / "static"
KEY = "tianxia.appearance.v1"

# Effective colours as rendered: walk up to an opaque background, compositing translucent layers.
# Chromium reports color-mix() results as color(srgb r g b / a), so both forms are parsed.
CONTRAST_JS = r"""
(selectors) => {
  function parse(value) {
    let m = value.match(/^rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)$/);
    if (m) return [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]];
    m = value.match(/^color\(srgb ([\d.e-]+) ([\d.e-]+) ([\d.e-]+)(?: \/ ([\d.]+))?\)$/);
    if (m) return [m[1] * 255, m[2] * 255, m[3] * 255, m[4] === undefined ? 1 : +m[4]];
    throw new Error("unparsed colour " + value);
  }
  function over(top, bottom) {
    const a = top[3];
    return [0, 1, 2].map(i => top[i] * a + bottom[i] * (1 - a)).concat(1);
  }
  function background(el) {
    const layers = [];
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      const c = parse(getComputedStyle(node).backgroundColor);
      if (c[3] > 0) layers.push(c);
      if (c[3] >= 1) break;
    }
    let out = [255, 255, 255, 1];
    for (let i = layers.length - 1; i >= 0; i--) out = over(layers[i], out);
    return out;
  }
  function lum(c) {
    const v = c.slice(0, 3).map(x => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); });
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
  }
  const out = [];
  for (const selector of selectors) {
    for (const el of document.querySelectorAll(selector)) {
      if (!el.offsetParent || !el.textContent.trim()) continue;
      const bg = background(el);
      const fg = over(parse(getComputedStyle(el).color), bg);
      const a = lum(fg), b = lum(bg);
      out.push({ selector, text: el.textContent.trim().slice(0, 40), ratio: (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) });
    }
  }
  return out;
}
"""
SMALL_TEXT = [".settings-label", ".colour-field small", ".settings-check small", ".style-card-note", ".settings-save-state",
              ".contrast-ok", ".contrast-report li"]


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def translate_path(self, path):
        if path.startswith("/static/"):
            path = path[len("/static"):]
        return super().translate_path(path)


@pytest.fixture(scope="module")
def base_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_Quiet, directory=str(STATIC)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        chromium = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"], headless=True)
        try:
            yield chromium
        finally:
            chromium.close()


def _page(browser, base_url, prefs=None, reduced_motion="no-preference"):
    context = browser.new_context(reduced_motion=reduced_motion)
    if prefs is not None:
        context.add_init_script(f"try {{ if (localStorage.getItem({json.dumps(KEY)}) === null) localStorage.setItem({json.dumps(KEY)}, {json.dumps(json.dumps(prefs))}); }} catch (e) {{}}")  # seed once; a reload must not re-seed
    page = context.new_page()
    page.route("**/api/**", lambda route: route.fulfill(status=200, content_type="application/json", body="[]"
                                                       if route.request.url.rstrip("/").endswith(("library", "archived", "projects", "characters")) else "{}"))
    return context, page


def _fixture(page, base_url, stylesheet, body_class, body):
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<link rel="stylesheet" href="/static/themes.css"><script src="/static/appearance-boot.js"></script>
<link rel="stylesheet" href="/static/{stylesheet}"></head><body class="{body_class}">{body}</body></html>"""
    url = f"{base_url}/fixture-{stylesheet.replace('/', '-')}.html"
    page.route(url, lambda route: route.fulfill(status=200, content_type="text/html", body=html))
    page.goto(url)
    page.evaluate("() => document.fonts.ready.then(() => true)")


# ---------------------------------------------------------------- 1. reduce motion keeps toasts readable
@pytest.mark.parametrize("source", ["player", "system", "off"])
def test_table_toast_stays_readable(browser, base_url, source):
    prefs = {"style": "lacquer", "reduceMotion": source == "player"}
    context, page = _page(browser, base_url, prefs, reduced_motion="reduce" if source == "system" else "no-preference")
    try:
        _fixture(page, base_url, "tabletop/tabletop.css", "tt-app",
                 '<div style="position:relative;height:300px"><div id="ttToasts" class="tt-toasts"></div></div>')
        assert (page.evaluate("document.documentElement.getAttribute('data-motion')") == "reduce") == (source != "off")
        # Same as tabletop.js toast(): shown, then removed after 4.2 seconds.
        page.evaluate("""() => { const n = document.createElement('div'); n.className = 'tt-toast is-error'; n.id = 'probe';
                         n.textContent = 'That move is not allowed'; document.getElementById('ttToasts').appendChild(n);
                         setTimeout(() => n.remove(), 4200); }""")
        samples = []
        for wait in (600, 1500, 1200):  # 0.6 s, 2.1 s and 3.3 s after it appears
            page.wait_for_timeout(wait)
            samples.append(page.evaluate("() => { const n = document.getElementById('probe'); if (!n) return null;"
                                         " const s = getComputedStyle(n); return [s.opacity, s.animationName]; }"))
        assert all(s is not None and float(s[0]) > 0.9 for s in samples), samples
        if source != "off":
            assert all(s[1] == "none" for s in samples), samples
        page.wait_for_timeout(1300)
        assert page.evaluate("document.getElementById('probe')") is None
    finally:
        context.close()


# ---------------------------------------------------------------- 2. text size reaches table and sheet text
TABLE_TEXT = {".tt-pill": 11, ".tt-btn b": 13, ".tt-btn small": 11, ".tt-card-cond": 11.5, ".tt-sub": 12}
SHEET_TEXT = {".arow-label": 14, ".arow-sub": 11.5, ".cond": 12, ".qbtn .qsub": 12}


@pytest.mark.parametrize("size,scale", [("normal", 1), ("large", 1.125), ("xlarge", 1.25)])
def test_text_size_scales_table_and_sheet_text(browser, base_url, size, scale):
    context, page = _page(browser, base_url, {"style": "lacquer", "textSize": size})
    try:
        _fixture(page, base_url, "tabletop/tabletop.css", "tt-app",
                 '<span class="tt-sub">Round 2</span><span class="tt-pill">Prone</span>'
                 '<button class="tt-btn"><b>Strike</b><small>1 action</small></button><span class="tt-card-cond">Prone</span>')
        sizes = {sel: page.evaluate(f"parseFloat(getComputedStyle(document.querySelector({json.dumps(sel)})).fontSize)")
                 for sel in TABLE_TEXT}
        _fixture(page, base_url, "tabletop/sheet.css", "",
                 '<div class="arow"><div class="arow-label">Palm Strike</div><div class="arow-sub">1 CP · melee</div></div>'
                 '<span class="cond">Grappled</span><button class="qbtn">Dodge <span class="qsub">reaction</span></button>')
        sizes.update({sel: page.evaluate(f"parseFloat(getComputedStyle(document.querySelector({json.dumps(sel)})).fontSize)")
                      for sel in SHEET_TEXT})
        for sel, base in {**TABLE_TEXT, **SHEET_TEXT}.items():
            assert abs(sizes[sel] - base * scale) < 0.06, (size, sel, sizes[sel], base * scale)
    finally:
        context.close()


# ---------------------------------------------------------------- 3. Settings: save / undo, rendered contrast, custom palettes
def _settings(browser, base_url, prefs=None):
    context, page = _page(browser, base_url, prefs)
    page.goto(f"{base_url}/index.html")
    page.evaluate("""() => { document.querySelectorAll('.screen').forEach(x => x.classList.toggle('active', x.id === 'screen-settings'));
                    const s = document.getElementById('screen-settings'); s.hidden = false; }""")
    page.wait_for_selector("#appearanceSave", state="visible")
    return context, page


def _pick(page, key, value):
    page.evaluate("""([key, value]) => { const i = document.querySelector(`input[data-colour="${key}"]`); i.value = value;
                    i.dispatchEvent(new Event('input', { bubbles: true })); }""", [key, value])


def _weak(page):
    return [r for r in page.evaluate(CONTRAST_JS, SMALL_TEXT) if r["ratio"] < 4.5]


def test_settings_save_and_undo(browser, base_url):
    context, page = _settings(browser, base_url)
    try:
        assert page.evaluate(f"localStorage.getItem({json.dumps(KEY)})") is None
        assert page.locator("#appearanceUndo").is_disabled()
        _pick(page, "text", "#909090")
        assert page.evaluate("document.documentElement.style.getPropertyValue('--cf-text')") == "#909090"
        assert page.locator("#appearanceSaveState").inner_text().startswith("Not saved yet")
        assert page.evaluate(f"localStorage.getItem({json.dumps(KEY)})") is None
        page.locator("#appearanceUndo").click()
        assert page.evaluate("document.documentElement.style.getPropertyValue('--cf-text')") == ""
        assert page.locator("#appearanceUndo").is_disabled()
        _pick(page, "text", "#909090")
        page.locator("#appearanceSave").click()
        assert json.loads(page.evaluate(f"localStorage.getItem({json.dumps(KEY)})"))["custom"] == {"text": "#909090"}
        assert page.locator("#appearanceSaveState").inner_text() == "Saved on this device."
        page.reload()
        assert page.evaluate("document.documentElement.style.getPropertyValue('--cf-text')") == "#909090"
    finally:
        context.close()


@pytest.mark.parametrize("style", ["lacquer", "celestial", "ember", "classic"])
def test_settings_small_text_is_readable_as_rendered(browser, base_url, style):
    context, page = _settings(browser, base_url, {"style": style})
    try:
        assert _weak(page) == []
        assert page.locator("#appearanceContrast .contrast-ok").count() == 1
    finally:
        context.close()


def test_custom_text_colour_keeps_small_text_readable_and_reports_honestly(browser, base_url):
    """Review counterexample: Night Lacquer with only Text = #909090 used to give faint text 3.27:1 and an all-clear."""
    context, page = _settings(browser, base_url)
    try:
        _pick(page, "text", "#909090")
        assert _weak(page) == []
        faint = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--cf-faint').trim()")
        assert faint != "#6c6c6d"
        # A text colour too close to the background is reported, naming the text it affects.
        _pick(page, "text", "#303030")
        report = page.locator("#appearanceContrast")
        assert "Hard to read with these colours" in report.inner_text()
        assert "Small labels and hints on panels" in report.inner_text()
    finally:
        context.close()


# ---------------------------------------------------------------- 4. active builder step hints on the accent fill (OPUSUI1f2)
STEP_NAV = """<nav class="owner-step-nav"><ol><li><button class="owner-step is-active" type="button"><span>1</span>
<strong>Identity</strong><small>Identity and intent</small></button></li></ol></nav>"""


@pytest.mark.parametrize("prefs", [{"style": "lacquer"}, {"style": "celestial"}, {"style": "ember"}, {"style": "classic"},
                                   {"style": "lacquer", "custom": {"text": "#909090"}}],
                         ids=["lacquer", "celestial", "ember", "classic", "lacquer-text-909090"])
def test_active_builder_step_hint_is_readable_as_rendered(browser, base_url, prefs):
    context, page = _page(browser, base_url, prefs)
    try:
        _fixture(page, base_url, "styles.css", "", STEP_NAV)
        rendered = page.evaluate(CONTRAST_JS, [".owner-step.is-active small", ".owner-step.is-active strong"])
        assert len(rendered) == 2
        assert [r for r in rendered if r["ratio"] < 4.5] == []
    finally:
        context.close()


# ---------------------------------------------------------------- 5. review fixes (OPUSUI1f3)
HOVER_NAV = """<nav class="owner-step-nav"><ol><li><button class="owner-step" type="button" id="probeStep"><span>2</span>
<strong>Abilities</strong><small>Pick what you can do</small></button></li></ol></nav>"""


@pytest.mark.parametrize("prefs", [{"style": "lacquer"}, {"style": "celestial"}, {"style": "ember"}, {"style": "classic"},
                                   {"style": "lacquer", "custom": {"text": "#909090"}}],
                         ids=["lacquer", "celestial", "ember", "classic", "lacquer-text-909090"])
def test_hovered_builder_step_hint_is_readable_as_rendered(browser, base_url, prefs):
    context, page = _page(browser, base_url, prefs)
    try:
        _fixture(page, base_url, "styles.css", "", HOVER_NAV)
        page.hover("#probeStep")
        rendered = page.evaluate(CONTRAST_JS, ["#probeStep small"])
        assert len(rendered) == 1 and rendered[0]["ratio"] >= 4.5, rendered
    finally:
        context.close()


def test_settings_reports_a_refused_save(browser, base_url):
    context, page = _settings(browser, base_url, {"style": "lacquer", "custom": {}})
    try:
        page.evaluate("() => { Storage.prototype.setItem = function () { throw new DOMException('full', 'QuotaExceededError'); }; }")
        _pick(page, "text", "#909090")
        page.locator("#appearanceSave").click()
        assert page.locator("#appearanceSaveState").inner_text().startswith("Couldn't save on this device")
        assert not page.locator("#appearanceUndo").is_disabled()
        assert json.loads(page.evaluate(f"localStorage.getItem({json.dumps(KEY)})"))["custom"] == {}
        page.reload()
        assert page.evaluate("document.documentElement.style.getPropertyValue('--cf-text')") == ""
    finally:
        context.close()
