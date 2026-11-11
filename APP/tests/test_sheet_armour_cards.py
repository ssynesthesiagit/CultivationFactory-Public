"""MMX73f1: the sheet's Armor Class and Speed cards are pinned as rendered text.

The MMX73 pre-merge review found the lane's coverage stopped at the service: it never read either card
a player actually sees, so reverting the renderer left the suite green while the sheet went on showing
the wrong Armor Class.  These run the real ``APP/static/app.js`` under the repository's in-process DOM
stub (``tests/gm_sheet_dom_stub/domstub.js``) and assert the rendered text of both changed paths: the
owner sheet's overview cards and the GM build panel's Defenses card.

No browser is launched and no network call is made -- ``node --test`` executes the file directly. The
rendered evidence lives in ``tests/sheet_armour_cards.test.mjs`` so a failure names the exact card and
sentence that regressed.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

RENDERER_GATE = Path(__file__).with_name('sheet_armour_cards.test.mjs')


@pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')
def test_sheet_armour_cards_render_the_fight_numbers() -> None:
    """Both rendered cards show the Armor Class and Speed the fight uses, and the real unarmored total.

    Run directly so a failure prints the card text that regressed
    (``node --test APP/tests/sheet_armour_cards.test.mjs``).
    """
    subprocess.run(['node', '--test', str(RENDERER_GATE)], check=True)
