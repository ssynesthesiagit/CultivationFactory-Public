"""Every attack has one Form: the One Breath deferred strike keeps its weapon's Form.

Hundred-Hand Battle Mandala's printed Weapon Forms say "every attack has one
Form", and Weapon-Wheel Body's Advantage, Thousand-Hand's third-hit Force and
Eight-Limb's completion all read the same per-turn Form record. One Breath,
Ten Thousand Steps' deferred strike is a wrapper whose typed ``source`` names
the talent, not the weapon; without the delivering item's identity the strike
silently stopped counting as a Form.

Synthetic characters and real table commits only: no private fixtures.
"""
from __future__ import annotations

from tests.test_a2r23_athletics_map import (
    FIGHTER, FOE, LONGSWORD, ONE_BREATH, engine_of, events, find, play, table_fight,
)

MANDALA = "tianxia.subpath.body.hundred_hand_battle_mandala.feature."
TALENTS = [ONE_BREATH, MANDALA + "four_hand_sequence", MANDALA + "weapon_wheel_body",
           MANDALA + "eight_limb_battle_pattern"]
FORMS_FLAG = "_round_hundred_forms"


def test_one_breath_deferred_strike_counts_as_its_weapon_form(tmp_path):
    """The deferred Jian strike records the Blade Form and earns Weapon-Wheel's
    Advantage for the next attack with a different Form (Unarmed)."""
    combat, table, mid = table_fight(tmp_path, TALENTS, kit=LONGSWORD)
    assert play(table, mid, find(table, mid, ONE_BREATH))[0]["status"] == "COMMITTED"
    assert play(table, mid, find(table, mid, "one_breath_strike", target=FOE))[0]["status"] == "COMMITTED"

    engine = engine_of(combat, mid)  # cold reload: the record is persisted fight state
    fighter = engine.state.actors[FIGHTER]
    record = fighter.turn_flags.get(FORMS_FLAG) or {}
    assert record.get("first") == "Blade", f"the strike's Form was not recorded: {record}"
    assert record.get("last") == "Blade", record
    assert record.get("hit_forms") == ["Blade"], record
    assert (record.get("struck") or {}).get(FOE) == 1, record

    # Weapon-Wheel Body: the next attack this turn with a different Form has Advantage.
    before = len(events(engine, "ATTACK_ROLLED"))
    assert play(table, mid, find(table, mid, "natural.unarmed_strike", target=FOE))[0]["status"] == "COMMITTED"
    engine = engine_of(combat, mid)
    rolled = events(engine, "ATTACK_ROLLED")[before:]
    assert rolled and len(rolled[-1].payload.get("dice") or []) == 2, \
        f"the Unarmed attack after the Blade strike is not at Advantage: {[r.payload for r in rolled]}"
    record = warrior_forms(engine.state.actors[FIGHTER])
    assert record.get("wheel_used") is True, record
    assert record.get("last") == "Unarmed", record


def warrior_forms(fighter):
    return fighter.turn_flags.get(FORMS_FLAG) or {}
