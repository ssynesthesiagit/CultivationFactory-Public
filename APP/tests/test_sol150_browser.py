"""Lead-only checks on scratch fights outside the sandbox; never launch by default.

SOL150_PENDING_TABLE_URL must be a copied fight paused on a declinable prompt.
SOL150_DEAD_TABLE_URL must be a copied fight with a dead Tabik token.
"""
import os
import pytest

pytestmark = pytest.mark.skipif(os.getenv("SOL150_RUN_BROWSER") != "1", reason="lead runs Chromium outside sandbox")


def test_answer_on_another_client_dismisses_dialog_and_preserves_feed():
    url = os.getenv("SOL150_PENDING_TABLE_URL")
    if not url:
        pytest.skip("set SOL150_PENDING_TABLE_URL to a scratch pending fight")
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        first, second = browser.new_page(), browser.new_page()
        first.goto(url); second.goto(url)
        first.locator("#ttReaction").wait_for(state="visible")
        before_rows = second.locator('#ttFeed li').count()
        with second.expect_response(lambda r: '/api/tabletop/matches/' in r.url
                                    and r.url.endswith(('/act', '/auto-step'))) as completed:
            second.locator('#ttReaction [data-answer="DECLINE"]').click()
        committed = completed.value.json()
        assert committed['status'] == 'COMMITTED'
        assert committed['events']['events'], 'choose a scratch pause whose completion emits events'
        expect(second.locator('#ttFeed li')).not_to_have_count(before_rows, timeout=15000)
        first.locator("#ttReaction").wait_for(state="hidden", timeout=15000)
        # This detects a dismissed dialog whose state cursor skipped the log.
        expect(first.locator('#ttFeed')).to_have_text(second.locator('#ttFeed').inner_text(), timeout=15000)
        browser.close()


def test_dead_token_hover():
    url = os.getenv("SOL150_DEAD_TABLE_URL")
    if not url:
        pytest.skip("set SOL150_DEAD_TABLE_URL to a scratch fight with dead Tabik")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        page = browser.new_page(); page.goto(url)
        page.locator(".tt-token").filter(has_text="Tabik").first.hover()
        card = page.locator(".tt-card-hp").filter(has_text="Dead")
        card.wait_for(state="visible")
        assert "down" not in card.inner_text()
        browser.close()
