"""RW003 packet A1-P3b: TAL_MAGMA_BLACKGLASS_RAMPART prints no GM rider for its panel damage.

A1-P3 (commit 2c200bde, tests/test_rw003_blackglass_traversal.py) made the wall's own enter
trigger resolve the printed Slashing row at the moment a hostile climbs or moves across a panel,
and the compiler skips the mechanic-level deferred copy. The top-level rider that told the GM to
apply that same damage by hand therefore duplicated the automation and is deleted from the
reviewed source (authority/typed_mechanics/reviewed_final.d/elements.json) and from the generated
authority the table loads.

Read-only: JSON/strings only, no engine and no fight. The exact printed clauses are asserted, so
the public export keeps this file local (tools/public_test_redact.py prose_assertions): the
published copy publishes scrambled prose in place of the rulebook sentences.
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RECORD = "TAL_MAGMA_BLACKGLASS_RAMPART"
SOURCES = (
    "authority/typed_mechanics/reviewed_final.d/elements.json",
    "authority/Tianxia_Typed_Mechanics_Authority_R1.json",
)


def _record(source: str) -> dict:
    return json.loads((ROOT / source).read_text(encoding="utf-8"))["mechanics"][RECORD]


@pytest.mark.parametrize("source", SOURCES)
def test_the_record_prints_its_six_clauses_and_no_gm_row(source):
    riders = _record(source)["riders"]
    assert sorted(riders) == sorted([
        "Range: 60 feet",
        "Duration: 10 minutes",
        "Cost: 4 CP",
        "Each panel is 5 feet wide, 10 feet high, and 1 foot thick.",
        "Each panel has: AC 16; HP equal to 5 × your CL; Vulnerability to Thunder damage; "
        "Immunity to Poison and Psychic damage.",
        "Panels provide Cover normally.",
    ]), f"{source} changed beyond dropping the GM row: {riders}"
    for rider in riders:
        assert not rider.startswith("GM:"), f"{source} still prints a GM instruction: {rider}"
        assert "apply PB Slashing damage once per turn when a hostile creature climbs" not in rider, (
            f"{source} still asks a human for the damage the wall trigger already applies: {rider}")
        assert "once per turn when a hostile creature climbs or moves across a panel" not in rider, (
            f"{source} still repeats the enter trigger's own timing: {rider}")


def test_the_automated_row_keeps_its_printed_evidence():
    """The deleted rider was the only human statement of the row; the typed effect must still carry it."""
    row = next(effect for effect in _record(SOURCES[0])["effects"]
               if "slashing" in effect.get("damage_types", []))
    assert row["formula"] == "pb"
    assert "A akwpdrv knwvenoa lfmh sudcef or fedeu fbrpoi a vhylb ayfiw Subslsir rbdoep dvavt to uhpr Prcnumniwhd Bvtss iftd per turn." == row["evidence"]
    assert row.get("deferred") is True, "the wall enter trigger is what removes the deferral; keep the row deferred"
