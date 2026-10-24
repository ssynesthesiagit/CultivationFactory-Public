"""RW003 packet A1-P1: Humble Wall's rider text says what the table actually does.

The rider used to read "object HP/AC are not tracked by the table yet" and to tell the
player to "track ... by hand". That is false. combat/rules/terrain.json's "humble wall"
entry carries object {ac: "12", hp: "10+cl", scope: "section", immune: [POISON, PSYCHIC]},
cover, move_cost and length_by_cl; combat/factory_compiler.py:3547 _wall_rule resolves that
entry by name and combat/zones.py:364 writes the instantiated hit points into
zone.trigger_profile["wall"]["object"]["hp"]; combat/ext/docket_walls.py:49 stats() reads the
AC, hit points and immunities and :201 wall_attack resolves "Attack a wall section" against
them (damage immunity zero, section hit points kept on the zone).

This test is read-only JSON: it reads the generated authority's rider text and the two
display sources that carry the owner's reviewed wording, and fails if the stale sentence
comes back or if the sources drift from the generated text. It imports no engine.
"""

import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
MECHANIC = "TAL_EARTH_HUMBLE_WALL"
AUTHORITY = APP / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json"
OWNER_EDITS = APP / "authority" / "typed_mechanics" / "owner_text_edits.json"
PLAYER_TEXT = APP / "authority" / "typed_mechanics" / "player_text.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def wall_rider() -> str:
    """The one rider sentence this record carries (the wall-modelling note)."""
    riders = _json(AUTHORITY)["mechanics"][MECHANIC]["riders"]
    assert len(riders) == 1, riders
    return riders[0]


def test_the_generated_rider_no_longer_denies_tracking_or_sends_the_numbers_by_hand():
    rider = wall_rider()
    lowered = rider.lower()
    for stale in ("by hand", "not tracked", "track its ac"):
        assert stale not in lowered, rider


def test_the_generated_rider_states_the_numbers_the_table_uses():
    rider = wall_rider()
    for fact in ("automatically", "AC 12", "10 + Cultivation Level", "Poison", "Psychic"):
        assert fact in rider, rider
    # The table keeps the wall's numbers and resolves attacks on a wall section with them, so the
    # player-facing note must not send that work back to the GM. Short fragments only: the public
    # mirror of this file must not carry long quoted owner prose.
    for fragment in ("wall section", "records those numbers", "resolves attacks"):
        assert fragment in rider, rider


def test_both_display_sources_agree_with_the_generated_rider():
    rider = wall_rider()
    owner_pairs = _json(OWNER_EDITS)["records"][MECHANIC]["player_evidence"]
    assert owner_pairs, "the owner's reviewed wording for this rider is missing"
    player_evidence = _json(PLAYER_TEXT)["evidence"]
    for raw, wording in owner_pairs.items():
        assert player_evidence.get(raw) == wording, raw
        assert wording == rider, wording
