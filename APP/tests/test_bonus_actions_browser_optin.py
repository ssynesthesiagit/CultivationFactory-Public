"""Lead-only rendered checks on TWO disposable copies of the blocked match.

Run outside the lane sandbox through HeavyQ. Supply independent ready-to-act
scratch servers in BONUSFIX_RUIN_URL and BONUSFIX_CLAW_URL, and a persistent
BONUSFIX_SCREENSHOT_DIR. Never point either URL at the live service.
"""
import os
from pathlib import Path
import re
from urllib.parse import urlparse

import pytest


@pytest.mark.parametrize("variable,label,condition", [
    ("BONUSFIX_RUIN_URL", "Ruin Channel", "ruin_channel"),
    ("BONUSFIX_CLAW_URL", "Black-Claw Manifestation (1 Stamina)", "black_claw"),
])
def test_bonus_action_on_disposable_match_copy(variable, label, condition):
    url = os.environ.get(variable)
    if not url:
        pytest.skip("Lead must run this browser check outside the sandbox: set " + variable)
    parsed = urlparse(url)
    assert parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    assert parsed.port is not None and parsed.port != 8765, "Use an explicit scratch port, never the live 8765"
    screenshots = Path(os.environ["BONUSFIX_SCREENSHOT_DIR"])
    screenshots.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright, expect

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("BONUSFIX_CHROMIUM", "/usr/bin/chromium"), args=["--no-sandbox"])
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.tabletop?.app?.state?.menu", timeout=60000)
            actor_id = page.evaluate("window.tabletop.app.state.menu.actor_id")
            initial = page.evaluate("window.tabletop.app.state.menu.state_version")
            if not page.locator("#ttViewerPicker").evaluate("(dialog) => dialog.open"):
                gate = page.locator("#ttViewerGateChoose")
                (gate if gate.is_visible() else page.locator("#ttViewerChange")).click()
            page.locator(f'input[name="my-fighters"][value="{actor_id}"]').check()
            page.locator("#ttViewerApply").click()

            # The blocked copy already has Bonus Damage chosen. Verify that
            # this path really covers its augmented self-only manifestation.
            if condition == "black_claw":
                page.wait_for_function("""() => window.tabletop.app.menu.actions.some(
                    g => g.label.includes('Black-Claw') && g.label.includes('Bonus Damage'))""")
            button = page.locator("#ttActionBar .tt-btn").filter(
                has_text=re.compile("^" + re.escape(label))).first
            expect(button).to_be_enabled(timeout=60000)
            requests = []
            page.on("request", lambda request: requests.append(request.url)
                    if request.method == "POST" else None)
            button.click()

            # If the server offers multiple legal self modes, the list is a
            # valid UI outcome; choose explicitly, never click an enemy token.
            for _ in range(12):
                page.wait_for_function("""version => {
                    const app = window.tabletop.app;
                    return app.pendingChoice?.kind === 'list' ||
                        document.querySelector('#ttReaction[open]') ||
                        app.state?.presentation?.actors?.find(a => a.entity_id === app.state.menu?.actor_id)
                            ?.turn_state?.bonus_action === false ||
                        app.state?.menu?.state_version > version;
                }""", arg=initial, timeout=60000)
                if page.evaluate("window.tabletop.app.pendingChoice?.kind === 'list'"):
                    page.locator("#ttHint button").filter(has_not_text=re.compile(
                        "^(Cancel|More)")).first.click()
                elif page.locator("#ttReaction[open]").count():
                    choices = page.locator("#ttReaction [data-option]:visible")
                    if choices.count():
                        choices.first.click()
                    else:
                        page.locator('#ttReaction [data-answer="DECLINE"]:visible').click()
                else:
                    break
            page.wait_for_function("""({actor, fragment}) => {
                const app = window.tabletop.app;
                const fighter = app.state?.presentation?.actors?.find(a => a.entity_id === actor);
                return fighter?.turn_state?.bonus_action === false &&
                    fighter.conditions?.some(c => c.condition_id.includes(fragment)) &&
                    !app.targeting && !app.pendingChoice;
            }""", arg={"actor": actor_id, "fragment": condition}, timeout=60000)
            assert any(path.endswith(("/act", "/composition/commit")) for path in requests), requests
            page.screenshot(path=str(screenshots / (condition + ".png")), full_page=True)
        except Exception:
            page.screenshot(path=str(screenshots / (condition + "_failed.png")), full_page=True)
            raise
        finally:
            browser.close()
