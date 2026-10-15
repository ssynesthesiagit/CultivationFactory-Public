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
    result = subprocess.run(["node", "--test", "--test-reporter=tap", str(APP / script)], cwd=APP, capture_output=True, text=True)
    # The public CI collector retains the first error line. Keep the failed
    # Node case there as well as the full TAP context below it.
    failure = next((line.strip() for line in result.stdout.splitlines() if line.startswith("not ok ")),
                   result.stderr.strip().splitlines()[0] if result.stderr.strip() else "no TAP failure reported")
    assert result.returncode == 0, f"{script} failed: {failure}\n{result.stdout[-6000:]}\n{result.stderr[-2000:]}"


def test_hover_card_scrolls_stays_put_and_owns_its_own_id():
    _node_test("static/tabletop/hovercard.test.mjs")


def test_map_card_dismissal_and_two_cards_in_one_document():
    _node_test("tests/hovercard_board_dom.test.mjs")


def test_node_wrapper_supports_runners_without_the_isolation_flag(monkeypatch):
    # The private CI runner's Node rejects --test-isolation=none before loading
    # any test. These invocations already select one file; default isolation is
    # sufficient. Model the observed rejection without requiring a second Node.
    def legacy_node(command, **kwargs):
        rejected = "--test-isolation=none" in command
        return subprocess.CompletedProcess(command, 9 if rejected else 0, stdout="",
                                           stderr="node: bad option: --test-isolation=none" if rejected else "")

    monkeypatch.setattr(subprocess, "run", legacy_node)
    _node_test("tests/hovercard_board_dom.test.mjs")
