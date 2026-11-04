"""Lead runs outside sandbox: SOL115_BROWSER=1 pytest this file.

Render the actual table movement-left formatter on a static page; no live service.
The persisted table/cost/preview assertions are in test_sol115_prone_crawl.py.
"""
import os
from pathlib import Path
import re
import pytest

pytestmark=pytest.mark.skipif(os.getenv('SOL115_BROWSER')!='1',
    reason='Lead must run browser checks outside the sandbox')


def test_rendered_crawl_movement_left():
    from playwright.sync_api import sync_playwright, expect
    source=(Path(__file__).resolve().parents[1]/'static/tabletop/tabletop.js').read_text()
    formatter=re.search(r'function movementLeft\(actor\) \{.*?\n\}',source,re.S).group(0)
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        try:
            page=browser.new_page()
            page.set_content('<div id="left"></div>')
            for remaining,crawl in ((30,15),(20,10),(0,0)):
                actor={'movement_remaining_ft':remaining,'walking_distance_remaining_ft':crawl}
                page.evaluate('({formatter,actor}) => { document.querySelector("#left").textContent = new Function("return ("+formatter+")")()(actor); }',
                    {'formatter':formatter,'actor':actor})
                expect(page.locator('#left')).to_have_text(f'Crawl up to {crawl} ft ({remaining} ft movement)')
        finally:
            browser.close()
