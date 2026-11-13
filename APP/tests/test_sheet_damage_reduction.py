"""DEFRED: a flat damage Reduction shows on the character sheet's Defences card, as fight resolution applies it.

Body Conditioning is a "when you take Bludgeoning damage, reduce that damage by your Proficiency Bonus" row.  Combat
subtracts it, but the card used to drop it (combat/typed_reactions.py defense_display read only resistance, immunity
and vulnerability rows).  The card now lists it in its own "Damage reduction" group, read through the table's state endpoint
the sheet uses, and the number on it is the one defend() applies.
"""

from combat import typed_reactions
from tests.auto8f1_table_support import FOE, OWNER, fixture


def test_body_conditioning_reduction_is_listed_on_the_card_and_matches_the_damage_taken(tmp_path):
    fight = fixture(tmp_path, ["TAL_IRON_FIST_BODY_CONDITIONING"], seed="DEFRED-SHEET")
    engine = fight["stored_engine"]()
    owner = engine.state.actors[OWNER]

    assert typed_reactions.defend(engine, owner, 20, "BLUDGEONING", None, FOE) == 16  # Proficiency Bonus 4 off the hit

    table, match_id = fight["table"], fight["match_id"]
    row = next(r for r in table.state(match_id)["presentation"]["actors"] if r["entity_id"] == OWNER)
    assert row["damage_defenses"]["reductions"] == [
        {"damage_type": "Bludgeoning damage reduced by 4", "source": "Body Conditioning", "until": None, "note": None}]
    assert row["damage_defenses"]["resistances"] == [] and row["damage_defenses"]["vulnerabilities"] == []
    assert row["damage_defenses"]["immunities"] == []
