"""Lead-only: serve the test_lock16_cell_placement large fixture on scratch data."""
import os
import pytest


@pytest.mark.skipif(os.environ.get('LOCK16_RUN_BROWSER') != '1', reason='Lead runs the opt-in browser check')
def test_chosen_summon_square_is_clickable_and_survives_reload():
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        try:
            page=browser.new_page();page.goto(os.environ['LOCK16_CELL_TABLE_URL'])
            page.wait_for_selector('#ttViewport')
            name=os.environ.get('LOCK16_SUMMON_NAME','Painted Beast')
            page.get_by_role('button',name=name,exact=False).first.click()
            assert page.locator('.tt-mark-move[x="3.06"][y="6.06"]').count()==0
            page.locator('.tt-mark-move[x="7.06"][y="6.06"]').click(force=True)
            token=page.locator('.tt-token').filter(has_text=name).first
            token.wait_for(state='visible')
            expect(token).to_have_css('transform','matrix(1, 0, 0, 1, 448, 384)')
            expect(token).to_have_css('width','128px')
            expect(token).to_have_css('height','128px')
            page.reload();token.wait_for(state='visible')
            expect(token).to_have_css('transform','matrix(1, 0, 0, 1, 448, 384)')
            expect(token).to_have_css('width','128px')
            expect(token).to_have_css('height','128px')
        finally:
            browser.close()
