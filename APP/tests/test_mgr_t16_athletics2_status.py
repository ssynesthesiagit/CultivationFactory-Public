"""The three Athletics records this lane automated are published as applied, not as table-only.

Their status rows were removed from ``feature_status.d/bodyb.json`` while the plug-ins
were implemented, so the sheet fell back to heuristic labels and could list a working
record as needing table adjudication.  Each row must be present, say it runs on the
table, and keep its name out of the compiled "needs the table" list.
"""
from combat.factory_compiler import feature_status
from tests.h1_support import bundle, mechanics

APPLIED = {
    "TAL_ATHLETICS_SPARROW_S_PATH": "Fly Speed",
    "TAL_ATHLETICS_SHARK_SWIM": "Swim Speed",
    "TAL_ATHLETICS_POWERFUL_WINGS": "Hover",
}


def test_each_automated_athletics_record_has_an_applied_status():
    published = feature_status()
    mods = mechanics()
    for mid, capability in APPLIED.items():
        entry = published.get(mid)
        assert entry is not None, f"{mid} has no published feature status"
        assert entry["status"] == "applied", f"{mid} is published as {entry['status']!r}: {entry['why']}"
        # The old rows claimed the table had no flight, swimming or falling model.
        assert "not model yet" not in entry["why"] and "no elevation" not in entry["why"]
        assert capability in entry["why"], f"{mid} status does not name its capability: {entry['why']}"
        name = mods[mid]["name"]
        compiled = bundle([mid])
        assert name not in compiled["diagnostics"]["skipped"]["table"], (
            f"{mid} is published as applied but {name!r} is still listed as needing the table")
