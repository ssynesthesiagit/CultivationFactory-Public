"""Offline unowned-fight capture used by AUTO10 and its replay-guard regressions.

The existing stock Git-tree loader isolates historical imports/resources without
copying a checkout or replacing any production engine method.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

APP = Path(__file__).resolve().parents[1]


def compare(scratch, base):
    captures = []
    for arm in ("base", "head"):
        command = [sys.executable, "-B", "-m", "tests.talisman_unowned_capture", str(scratch / arm)]
        if arm == "base":
            command.append(base)
        result = subprocess.run(command, cwd=APP, text=True, capture_output=True, timeout=600,
                                env={**os.environ, "CF_EMBED_MENU": "0"})
        assert result.returncode == 0, result.stdout[-1500:] + result.stderr[-4000:]
        capture = json.loads(result.stdout.splitlines()[-1])
        # The fight ran its eight decisions and recorded events. The event *count* is mainline data: merged
        # main actions (grapple/release) add events, so pinning it here would fail on every new main. What
        # this guard checks is base == head below; the count would only hide that behind a stale constant.
        assert capture["steps"] == 8 and capture["events"], capture
        captures.append(capture)
    # Compare all event fields, including rolls, spends, order, and wording.
    assert captures[0] == captures[1], {"base": base, "captures": captures}


def main():
    from tests.queue_guard import require_test_queue
    require_test_queue()
    # This is a native AI replay, not a semantic-ranking test. Child processes
    # do not inherit pytest's socket fixture; disable the optional live client.
    os.environ["CF_EMBED_MENU"] = "0"
    scratch = Path(sys.argv[1])
    revision = sys.argv[2] if len(sys.argv) > 2 else None
    from tests.wall_height_stock_capture import revision_sources
    root = revision_sources(revision, scratch) if revision else APP
    from tests import hunt24_support, hunt12_support
    from combat.canonical import canonical_bytes

    # These are test fixture resource roots, as in the stock capture helper.
    hunt24_support.ROOT = hunt12_support.ROOT = root
    combat, table, mid = hunt24_support.table_fight(scratch / "fight", [])
    for aid in (hunt24_support.A, hunt24_support.D):
        combat.set_controller_mode(mid, actor_id=aid, controller_mode="LOCAL_AUTO")
    steps = 0
    for _ in range(8):
        state = table.state(mid)
        if state["menu"].get("terminal"):
            break
        assert table.auto_step(mid, state["last_sequence"], [])["status"] == "COMMITTED"
        steps += 1
    engine = hunt12_support.reload(scratch / "fight", mid)
    events = [event.model_dump(mode="json") for event in engine.events]
    for event in events:
        event.pop("match_id", None)
    print(canonical_bytes({"steps": steps, "events": events}).decode())


if __name__ == "__main__":
    main()
