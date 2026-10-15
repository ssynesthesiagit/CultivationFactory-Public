"""The shared hover card, run on the real client modules.

Owner, 2026-10-03: "there needs to be a way to hover over the tooltip to scroll down with middle mouse roll
button. wait for it to pop up, then move over to the box and select things or scroll down etc."

These are client-only modules, so they are exercised with `node --test` in a DOM double rather than in a browser
(no browser may be launched here). They are wired into pytest because a client regression that nothing runs is a
regression that comes back: the pre-merge review of MMX100 found the wheel test asserting only that the wheel was
cancelled, and nothing in the suite ever noticed.

  static/tabletop/hovercard.test.mjs    the card itself: scrolling, placement, the hover bridge, ids, closing
  tests/hovercard_board_dom.test.mjs     the map's use of it: a dismissed card stays dismissed, two cards, two ids
"""
import subprocess
from pathlib import Path

APP = Path(__file__).resolve().parents[1]


def _node_test(script: str) -> None:
    result = subprocess.run(["node", "--test", str(APP / script)], cwd=APP, capture_output=True, text=True)
    assert result.returncode == 0, f"{script} failed:\n{result.stdout[-6000:]}\n{result.stderr[-2000:]}"


def test_hover_card_scrolls_stays_put_and_owns_its_own_id():
    _node_test("static/tabletop/hovercard.test.mjs")


def test_map_card_dismissal_and_two_cards_in_one_document():
    _node_test("tests/hovercard_board_dom.test.mjs")
