"""RW003 packet A1-P3b: TAL_MAGMA_BLACKGLASS_RAMPART prints no GM rider for its panel damage.

A1-P3 (commit 2c200bde, tests/test_rw003_blackglass_traversal.py) made the wall's own enter
trigger resolve the printed Slashing row at the moment a hostile climbs or moves across a panel,
and the compiler skips the mechanic-level deferred copy. The top-level rider that told the GM to
apply that same damage by hand therefore duplicated the automation and is deleted from the
reviewed source (authority/typed_mechanics/reviewed_final.d/elements.json) and from the generated
authority the table loads.

Read-only: JSON/strings only, no engine and no fight.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = "TAL_MAGMA_BLACKGLASS_RAMPART"

# The six clauses the record still prints beyond the automated damage row:
# range, duration, cost, panel size, panel object stats, cover.
KEPT = (
    "Range: 60 feet",
    "Duration: 10 minutes",
    "Cost: 4 CP",
    "Each panel is 5 feet wide, 10 feet high, and 1 foot thick.",
    "Each panel has: AC 16; HP equal to 5 \u00d7 your CL; Vulnerability to Thunder damage; "
    "Immunity to Poison and Psychic damage.",
    "Panels provide Cover normally.",
)


def _riders(path: Path) -> list[str]:
    record = json.loads(path.read_text(encoding="utf-8"))["mechanics"][RECORD]
    return record["riders"]


def _assert_no_gm_damage_rider(riders: list[str], where: str) -> None:
    for rider in riders:
        lowered = rider.lower()
        assert not rider.startswith("GM:"), f"{where} still prints a GM instruction: {rider}"
        assert "apply pb slashing" not in lowered, f"{where} still asks for the automated damage: {rider}"
        assert "once per turn when a hostile creature climbs" not in lowered, (
            f"{where} still repeats the enter trigger's timing: {rider}")
    assert sorted(riders) == sorted(KEPT), f"{where} rider list changed beyond the removed GM row: {riders}"


def test_reviewed_source_drops_the_gm_rider_and_keeps_the_printed_clauses():
    riders = _riders(ROOT / "authority/typed_mechanics/reviewed_final.d/elements.json")
    _assert_no_gm_damage_rider(riders, "the reviewed source")


def test_built_authority_drops_the_gm_rider_and_keeps_the_printed_clauses():
    riders = _riders(ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json")
    _assert_no_gm_damage_rider(riders, "the built authority")


def test_the_automated_row_keeps_its_printed_evidence():
    """The deleted rider was the only human statement of the row; the typed effect must still carry it."""
    record = json.loads(
        (ROOT / "authority/typed_mechanics/reviewed_final.d/elements.json").read_text(encoding="utf-8")
    )["mechanics"][RECORD]
    row = next(effect for effect in record["effects"] if "slashing" in effect.get("damage_types", []))
    assert row["formula"] == "pb"
    assert "once per turn" in row["evidence"]
    assert row.get("deferred") is True, "the wall enter trigger is what removes the deferral; keep the row deferred"
