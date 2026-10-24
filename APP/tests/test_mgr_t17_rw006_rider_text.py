"""MGR-T17 RW006: a rider must not tell the player to do what the fight already does.

A record's ``riders`` are the sentences the fight log prints as "the GM still handles this". When a clause
becomes typed, its rider sentence has to go (or say what the table now does), or a player reads a manual
step that is really automatic. This packet rewrote two such sentences:

* Conductive Strike -- "Decide whether to apply the imbuement and consume a Charge" was stale: the
  after-hit hook places the Conductive mark and, at CL 5 against an already-Charged target, spends the
  Charge for the extra 1d8 (combat/ext/charge_marks.py:65 ``_conductive_strike_after_hit``). Unarmed
  delivery really is the GM's (the hook returns for every kind but "weapon"), so that clause stays.
* Low River Stance -- "Standing from Prone costs you only 5 feet of movement" was residue: the native
  standing transition already asks for that price (combat/posture.py:63 ``stand_cost`` ->
  combat/ext/flowing_river.py:200 ``low_river_standing``), proven at table level by
  tests/test_auto61_flowing_river.py::test_low_river_stance_actual_standing_cost.

The other two records of the packet (Demon Emperor Incarnation, Lightning-God Body) were audited and needed
no edit: their remaining riders are genuinely manual (Corruption / Demonic Debt, the aura's Realm eligibility,
the timing of the optional Charge). The last two tests keep those clauses from being swept away later.
"""

import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1]


def _authority():
    """The build product the fight engine loads (built from authority/typed_mechanics/reviewed_final.d)."""
    path = APP / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json"
    return json.loads(path.read_text(encoding="utf-8"))["mechanics"]


def _feature_blocks():
    return json.loads((APP / "combat" / "rules" / "feature_blocks.json").read_text(encoding="utf-8"))["features"]


def test_conductive_strike_rider_no_longer_asks_for_the_imbuement_or_the_charge_spend():
    rider = " ".join(_authority()["TAL_LIGHTNING_CONDUCTIVE_STRIKE"]["riders"])
    assert "Decide whether to apply the imbuement" not in rider
    assert "The imbuement applies on the hit" in rider
    # The CL 5 spend is printed as the player's optional choice, and the table asks it on the hit (charge_marks.py).
    assert "you may consume the Charge" in rider and "you are asked on the hit" in rider
    assert "the Charge on an already-Charged target is spent" not in rider
    # Unarmed strikes are not automated (the after-hit hook is weapon-only), so the GM clause must stay.
    assert "unarmed delivery needs the charge" in rider.lower()
    # ...and it has to survive the fight log: a sentence naming "the table" is dropped whole.
    from combat.history_text import rider_text

    assert "Unarmed delivery needs the Charge" in (rider_text({"rider": rider}, "A Fighter", "Conductive Strike", "the target") or "")


def test_conductive_strike_block_no_longer_claims_its_cl5_upgrade_is_unautomated():
    why = _feature_blocks()["TAL_LIGHTNING_CONDUCTIVE_STRIKE"]["why"]
    assert "not automated" not in why
    assert "unarmed strikes need a Charge" in why
    assert "charge_marks.py" in why


def test_low_river_stance_rider_no_longer_restates_the_standing_price_the_table_charges():
    rider = " ".join(_authority()["TAL_FLOWING_RIVER_LOW_RIVER_STANCE"]["riders"])
    assert "Standing from Prone costs you only 5 feet" not in rider
    # The two clauses that are still unwired (prone outside your turn, ranged attacks) stay exactly as they were.
    assert "drop Prone at any time" in rider
    assert "ranged attacks" in rider


def test_the_built_authority_carries_the_rider_text_this_packet_reviewed():
    built = _authority()
    charge = json.loads((APP / "authority" / "typed_mechanics" / "reviewed_final.d" / "charge.json").read_text())["mechanics"]
    bodyb = json.loads((APP / "authority" / "typed_mechanics" / "reviewed_final.d" / "bodyb.json").read_text())["mechanics"]
    assert built["TAL_LIGHTNING_CONDUCTIVE_STRIKE"]["riders"] == charge["TAL_LIGHTNING_CONDUCTIVE_STRIKE"]["riders"]
    assert built["TAL_FLOWING_RIVER_LOW_RIVER_STANCE"]["riders"] == bodyb["TAL_FLOWING_RIVER_LOW_RIVER_STANCE"]["riders"]


def test_the_records_this_packet_left_alone_keep_their_genuinely_manual_clauses():
    built = _authority()
    emperor = " ".join(built["TAL_DAEMONIC_CULTIVATION_DEMON_EMPEROR_INCARNATION"]["riders"])
    assert "gain 2 Corruption" in emperor and "Demonic Debt" in emperor
    assert "Realm/ordinary-creature eligibility needs GM adjudication" in emperor
    body = " ".join(built["TAL_LIGHTNING_LIGHTNING_GOD_BODY"]["riders"])
    assert "Opportunity Attack" in body
