"""Offline real-shell fixture; no service, saved fights, or live data.

Lead runs outside the sandbox with /usr/bin/env BARHEIGHT1_RUN_BROWSER=1
(the heavyq runner does not forward this environment variable).
BARHEIGHT1_SCREENSHOT_DIR retains captures outside pytest's temporary directory.
Optional BARHEIGHT1_BEFORE_JS supplies the pre-fix tabletop.js for a before
capture; assertions always use current code. All requests are intercepted.
"""
import os
from pathlib import Path
import re
from urllib.parse import urlparse

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("BARHEIGHT1_RUN_BROWSER") != "1",
    reason="Lead must run the layout/screenshot gate outside the sandbox",
)


@pytest.mark.parametrize("width,height", [(1600, 1000), (800, 900), (390, 844)])
def test_bar_has_only_controls_and_floating_rules_reachable_by_hover_focus_tap(width, height, tmp_path):
    from factory_authoring.player_rules import render_player_card
    from playwright.sync_api import expect, sync_playwright

    app = Path(__file__).resolve().parents[1]
    static = app / "static"
    source = (static / "tabletop/tabletop.html").read_text()
    # Use the real shell/styles without starting its service-facing controller.
    source = re.sub(r"<script\b[^>]*>.*?</script>", "", source, flags=re.S)
    source = source.replace("tt-app is-viewer-pending", "tt-app")
    last_rule = "Final rule: every choice remains available."
    rules = "\n".join(f"Rule {i}: Keep this complete instruction readable."
                      for i in range(1, 41)) + "\n" + last_rule
    title = "Broken-Rhythm Strike"
    card = {"title": title, "text": rules, "facts": [["Action", "Action"], ["Cost", "None"]]}
    card["html"] = render_player_card({
        **card, "summary": "Replace one attack with an unarmed or melee attack.",
        "groups": {"Effect": ["On a hit, deal normal damage and put the target Off-Rhythm."],
                   "Choices": ["Choose any legal target within reach."]},
        "rules": rules,
    })
    hover = {"title": title, "text": rules, "player_card": card}
    captures = Path(os.environ.get("BARHEIGHT1_SCREENSHOT_DIR", str(tmp_path)))
    captures.mkdir(parents=True, exist_ok=True)
    versions = []
    if os.environ.get("BARHEIGHT1_BEFORE_JS"):
        versions.append(("before", Path(os.environ["BARHEIGHT1_BEFORE_JS"]).read_text()))
    versions.append(("after", (static / "tabletop/tabletop.js").read_text()))

    def serve(route):
        path = urlparse(route.request.url).path
        if path == "/":
            route.fulfill(body=source, content_type="text/html")
        elif path.startswith("/static/") and path.endswith((".css", ".js")):
            asset = static / path.removeprefix("/static/")
            route.fulfill(path=str(asset), content_type="text/css" if path.endswith(".css") else "text/javascript")
        elif path == "/tests/actionbar_fixture.mjs":
            route.fulfill(path=str(app / "tests/actionbar_fixture.mjs"), content_type="text/javascript")
        else:
            route.abort()  # No network, including fonts, APIs, or model servers.

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        try:
            page = browser.new_page(viewport={"width": width, "height": height}, has_touch=True)
            page.route("**/*", serve)
            for phase, controller in versions:
                page.goto("http://barheight1.test/")
                await_fixture = """async ({controller, hover}) => {
                  const {renderBarFixture} = await import('/tests/actionbar_fixture.mjs');
                  const {createHoverCard, bindTipTargets} = await import('/static/tabletop/hovercard.js');
                  document.querySelector('#ttMatchName').textContent = 'Layout training fight';
                  window.barFixture = await renderBarFixture(document,
                    document.querySelector('#ttActionBar'), controller, hover);
                  window.barHoverCard = createHoverCard({doc: document, win: window});
                  bindTipTargets(window.barHoverCard, document);
                }"""
                page.evaluate(await_fixture, {"controller": controller, "hover": hover})
                bar = page.locator("#ttActionBar")
                if phase == "before":
                    # The old assembler is injected only for evidence, never assertions.
                    # Its inline player card is the owner's original failure.
                    bar.locator(".player-card summary").first.click()
                    page.screenshot(path=str(captures / f"before-{width}.png"))
                    continue

                def controls_only():
                    expect(bar.locator(".tt-action-rules, .player-card, .tt-tipcard, .tc, .tc-full, .lib-text")).to_have_count(0)
                    expect(bar.get_by_text(re.compile(r"^(Effect|Choices|Rules|Full rules)$"))).to_have_count(0)
                    expect(bar).not_to_contain_text(last_rule)

                controls_only()
                original_height = bar.bounding_box()["height"]
                assert original_height <= height * .4 + 1
                stage_box = page.locator(".tt-stage").bounding_box()
                assert stage_box["height"] >= height * .45, stage_box
                tip = page.locator("#tt-hovercard")
                actions = bar.locator(".tt-action-card button")
                expect(actions).to_have_count(5)
                if width == 390:
                    assert bar.locator('.tt-ab-groups').bounding_box()['width'] >= width - 30
                for index, button in enumerate(actions.all()):
                    for method in (("focus", "tap") if width == 390 else ("hover", "focus", "tap")):
                        page.keyboard.press("Escape")
                        page.mouse.move(0, 0)
                        button.evaluate("(n) => n.blur()")
                        button.scroll_into_view_if_needed()
                        if method == "tap":
                            # Verify the actual touch point, not just DOM visibility.
                            assert button.evaluate("""n => {
                              const r = n.getBoundingClientRect();
                              const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
                              return hit === n || n.contains(hit);
                            }"""), (width, index, 'button covered before tap')
                        getattr(button, method)()
                        expect(tip).to_be_visible()
                        # Focus opens help before a touch click; it must not cover its trigger.
                        boxes = button.evaluate("""n => {
                          const a = n.getBoundingClientRect(), b = document.querySelector('#tt-hovercard').getBoundingClientRect();
                          return {overlap: a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top,
                                  button: a.toJSON(), card: b.toJSON()};
                        }""")
                        assert not boxes['overlap'], (width, index, method, boxes)
                        expect(tip).to_contain_text(last_rule)
                        assert tip.evaluate("(n) => n.closest('#ttActionBar') === null")
                        assert tip.evaluate("(n) => getComputedStyle(n).position") == "fixed"
                        if index in (0, 2, 3):  # attack, sheet action, extra menu action with player_card
                            expect(tip.locator(".player-card")).to_have_count(1)
                        else:
                            expect(tip.locator(".tc-full")).to_have_count(1)
                        summary = tip.get_by_text("Rules", exact=True)
                        if not summary.evaluate("(n) => n.parentElement.open"):
                            summary.click()
                        # Expanding rules changes the card's height after its initial placement.
                        page.wait_for_function("""button => {
                          const a = button.getBoundingClientRect(), b = document.querySelector('#tt-hovercard').getBoundingClientRect();
                          return !(a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top);
                        }""", arg=button.element_handle())
                        tip.evaluate("(n) => { n.scrollTop = n.scrollHeight; }")
                        # A large viewport may fit the whole card without scrolling.
                        # In either case the final rule must actually be visible at the end.
                        visibility = tip.evaluate("""(n) => {
                          // The renderer may bold the "Final rule:" lead separately.
                          const fragment = 'every choice remains available.';
                          const walker = document.createTreeWalker(n, NodeFilter.SHOW_TEXT);
                          let node;
                          while ((node = walker.nextNode())) {
                            const i = node.textContent.indexOf(fragment);
                            if (i < 0) continue;
                            const range = document.createRange();
                            range.setStart(node, i);
                            range.setEnd(node, i + fragment.length);
                            const text = range.getBoundingClientRect(), card = n.getBoundingClientRect();
                            return {visible: text.top >= card.top - 1 && text.bottom <= card.bottom + 1,
                                    text: {top: text.top, bottom: text.bottom},
                                    card: {top: card.top, bottom: card.bottom}};
                          }
                          return {visible: false, reason: 'final rule text node not found'};
                        }""")
                        assert visibility['visible'], (width, index, method, visibility)
                        controls_only()
                        assert abs(bar.bounding_box()["height"] - original_height) <= 1
                        if index == 0 and method == ("tap" if width == 390 else "hover"):
                            page.screenshot(path=str(captures / f"after-{width}.png"))
                # Tap still presses each exact action; displaying help consumes no option.
                assert sorted(page.evaluate("window.barFixture.pressed")) == [
                    "carded", "extra-carded", "extra-plain", "plain", "sheet-carded"]
                for key in ("Enter", "Space"):
                    page.keyboard.press("Escape")
                    actions.nth(1).focus()
                    count = page.evaluate("window.barFixture.pressed.length")
                    page.keyboard.press(key)
                    assert page.evaluate("window.barFixture.pressed.length") == count + 1
                    assert page.evaluate("window.barFixture.pressed.at(-1)") == "plain"
                page.keyboard.press("Escape")
                bar.get_by_role("button", name="End turn", exact=False).click()
                assert page.evaluate("window.barFixture.pressed.at(-1)") == "end"
        finally:
            browser.close()


CROWD_VIEWPORTS = [(1600, 900), (800, 900), (390, 844)]
# Owner-like crowded menu: many no-action rows, folded variant families, attack cards, long labels.
CROWD_JS = """() => {
  const bar = document.querySelector('#ttActionBar');
  const R = n => n.getBoundingClientRect();
  const hit = (a, b) => a.left < b.right - .5 && a.right > b.left + .5 && a.top < b.bottom - .5 && a.bottom > b.top + .5;
  const label = n => (n.textContent || '').trim().slice(0, 60);
  const out = [];
  const groups = [...bar.querySelectorAll('.tt-ab-group')];
  for (let i = 0; i < groups.length; i++) for (let j = i + 1; j < groups.length; j++) {
    if (groups[i].contains(groups[j]) || groups[j].contains(groups[i])) continue;
    if (hit(R(groups[i]), R(groups[j]))) out.push({kind: 'group-over-group', a: label(groups[i].querySelector('h3')), b: label(groups[j].querySelector('h3'))});
  }
  for (const g of groups) for (const c of g.querySelectorAll('.tt-btn, .tt-ab-buttons, h3')) {
    const gr = R(g), cr = R(c);
    if (cr.left < gr.left - .5 || cr.right > gr.right + .5 || cr.top < gr.top - .5 || cr.bottom > gr.bottom + .5)
      out.push({kind: 'escapes-group', group: label(g.querySelector('h3')), child: label(c)});
  }
  const buttons = [...bar.querySelectorAll('.tt-btn')];
  for (let i = 0; i < buttons.length; i++) for (let j = i + 1; j < buttons.length; j++) {
    if (buttons[i].contains(buttons[j]) || buttons[j].contains(buttons[i])) continue;
    if (hit(R(buttons[i]), R(buttons[j]))) out.push({kind: 'button-over-button', a: label(buttons[i]), b: label(buttons[j])});
  }
  for (const el of bar.querySelectorAll('b, small, h3, summary, .arow-label')) {
    const box = el.closest('.tt-btn, .tt-ab-group, summary');
    if (!box || box === el) continue;
    const e = R(el), b = R(box);
    if (e.width && (e.left < b.left - 1 || e.right > b.right + 1 || e.top < b.top - 1 || e.bottom > b.bottom + 1))
      out.push({kind: 'text-outside-box', text: label(el)});
  }
  return out;
}"""


@pytest.mark.parametrize("width,height", CROWD_VIEWPORTS)
def test_crowded_menu_boxes_do_not_overlap_or_escape(width, height, tmp_path):
    from factory_authoring.player_rules import render_player_card
    from playwright.sync_api import sync_playwright

    app = Path(__file__).resolve().parents[1]
    static = app / "static"
    source = (static / "tabletop/tabletop.html").read_text()
    source = re.sub(r"<script\b[^>]*>.*?</script>", "", source, flags=re.S)
    source = source.replace("tt-app is-viewer-pending", "tt-app")
    plain = "Action Type: Action\nRange: 5 feet\n" + "\n".join(
        f"Rule {i}: Keep this complete instruction readable." for i in range(1, 41))
    title = "Broken-Rhythm Strike"
    card = {"title": title, "text": plain, "facts": [["Action", "Action"], ["Cost", "None"]]}
    card["html"] = render_player_card({**card, "summary": "Replace one attack.", "groups": {}, "rules": plain})
    hover = {"title": title, "text": plain, "player_card": card}
    crowd = []
    for i in range(1, 9):  # attack weapon cards with long names
        crowd.append({"id": f"weapon-{i}", "source_definition_id": f"weapon-{i}", "group": "attacks",
                      "label": f"Weapon {i} with a deliberately long display name that must not escape its box",
                      "kind": "combat", "economy": "ACTION", "combat": {"source_definition_id": f"weapon-{i}"},
                      "detail": {"to_hit": "+5", "damage": "1d8 + 3", "range": "5 ft", "attacks": 1}, "hover": hover})
    for i in range(1, 5):  # folded variant families (economy rows with options)
        crowd.append({"source_definition_id": f"family-{i}", "label": f"Family {i} with a long combined label",
                      "economy": "ACTION", "options": [{"option_id": f"family-{i}-{j}"} for j in range(3)]})
    for i in range(1, 33):  # no-action rows
        crowd.append({"source_definition_id": f"none-{i}",
                      "label": f"Free-text reaction note {i}: a long label that must wrap or ellipsize",
                      "economy": "NONE", "description": plain})

    def serve(route):
        path = urlparse(route.request.url).path
        if path == "/":
            route.fulfill(body=source, content_type="text/html")
        elif path.startswith("/static/") and path.endswith((".css", ".js")):
            asset = static / path.removeprefix("/static/")
            route.fulfill(path=str(asset), content_type="text/css" if path.endswith(".css") else "text/javascript")
        elif path == "/tests/actionbar_fixture.mjs":
            route.fulfill(path=str(app / "tests/actionbar_fixture.mjs"), content_type="text/javascript")
        else:
            route.abort()  # No network, including fonts, APIs, or model servers.

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        try:
            page = browser.new_page(viewport={"width": width, "height": height}, has_touch=True)
            page.route("**/*", serve)
            page.goto("http://barheight1.test/")
            page.evaluate("""async ({controller, hover, crowd}) => {
              const {renderBarFixture} = await import('/tests/actionbar_fixture.mjs');
              document.querySelector('#ttMatchName').textContent = 'Layout training fight';
              await renderBarFixture(document, document.querySelector('#ttActionBar'), controller, hover, crowd);
            }""", {"controller": (static / "tabletop/tabletop.js").read_text(), "hover": hover, "crowd": crowd})
            violations = page.evaluate(CROWD_JS)
            assert violations == [], f"{width}x{height}: {violations[:20]} (total {len(violations)})"
        finally:
            browser.close()
