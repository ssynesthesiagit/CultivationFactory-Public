"""Talents that attack with the character's own weapon (owner 2026-09-27 playtest: Hewing Strike "did nothing" -- it
compiled as a damageless Cultivation Attack aimed at its user): "Make a melee weapon attack with an axe weapon. On a
hit, the attack deals its normal weapon damage. Then choose one Hewing rider."""

import pytest

from combat.factory_compiler import compile_character
from factory_authoring.typed_structure import options_ride_the_hit, weapon_delivery
from tests.test_factory_combat_compiler import SHEET

ACTOR = "actor:factory.delivery"


@pytest.mark.parametrize('extra_staff', [False, True])
def test_independent_triggered_weapon_context_keeps_physical_delivery_identity(extra_staff):
    from combat.typed_reactions import triggered_context
    from combat.ext.equipment_hands import attack_equipment_action
    from combat.ext.hand_occupancy import weapon_allowed
    from combat.ext.weapon_hits import weapon_identity
    from tests.test_riders_c2 import _sheet, _fight, ME, WS
    sheet = _sheet([WS])
    if extra_staff:
        sheet['equipment'][0]['starting_kit']['items'].append({'item_id': 'tianxia.mortal.weapon.gun'})
    engine = _fight(compile_character(sheet, actor_id=ME))
    actor = engine.state.actors[ME]
    attack = {"type": "attack", "attack_kind": "weapon", "strike_with": "weapon", "count": 1}
    ctx = triggered_context(engine, actor, None, {"feature_id": "test:independent_counter",
                                                "effects": [attack]})
    source = ctx.typed["weapon_source_id"]
    assert source.endswith(".weapon.fu") and engine.action_catalog[source].owner_id == ME
    assert weapon_identity(ctx) == source
    assert weapon_allowed(engine, actor, attack_equipment_action(ctx)) is True


def _axe_fighter(items: list[str]) -> dict:
    return {**SHEET, "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.axes"],
                                             "learned_talent_record_ids": ["TAL_AXES_HEWING_STRIKE", "TAL_AXES_CAST_AXE"]},
            "equipment": [{"starting_kit": {"items": [{"item_id": item} for item in items]}}]}


def test_the_printed_delivery_is_read_from_the_text():
    assert weapon_delivery("Parent Action: Attack\nMake a melee weapon attack with an axe weapon. On a hit") == \
        {"kind": "melee", "family": "axe", "special_attack": True}
    assert weapon_delivery("Make one ranged weapon attack against a creature.") == {"kind": "ranged", "family": None, "special_attack": False}
    # Another creature's command, not the user's attack (Dance of Borrowed Limbs).
    assert weapon_delivery("choose one command:\n- make one weapon attack at Disadvantage against a legal target") is None


def test_every_rider_rides_the_hit():
    attack = {"type": "attack", "attack_kind": "cultivation_melee", "count": 1, "on_hit": [], "on_miss": []}
    options = [{"label": "Drive", "effects": [{**attack, "on_hit": [{"type": "forced_movement"}]}]},
               {"label": "Hamper", "effects": [{"type": "speed", "flat": -5, "applies_to": "target"}]}]
    text = "Make a melee weapon attack with an axe weapon. On a hit, the attack deals its normal weapon damage. Then choose one Hewing rider."
    hamper = options_ride_the_hit([attack], options, text)[1]["effects"][0]
    assert hamper["type"] == "attack" and hamper["on_hit"] == [{"type": "speed", "flat": -5, "applies_to": "target"}]


def test_hewing_strike_is_the_axe_attack_with_its_rider_on_the_first_hit():
    bundle = compile_character(_axe_fighter(["tianxia.mortal.weapon.fu"]), actor_id=ACTOR)
    hamper = next(row for row in bundle["action_catalog"] if row["display_name"].endswith("Hewing Strike: Hamper"))
    typed = hamper["parameters"]["typed"]
    assert hamper["target_kind"] == "HOSTILE_ENTITY" and hamper["display_name"].startswith("Fu (Short Axe) attack")
    attack = typed["effects"][0]
    assert typed["weapon"]["damage"]["sides"] == 6 and attack["attack_kind"] == "weapon"
    plain = next(row for row in bundle["action_catalog"] if row["display_name"] == "Fu (Short Axe) attack")
    assert attack["count"] == plain["parameters"]["typed"]["effects"][0]["count"]  # every attack of the Attack action
    assert attack["on_hit"][0] == {"type": "damage", "weapon_damage": True}
    assert any(hit.get("type") == "speed" and hit.get("first_hit_only") for hit in attack["on_hit"])
    cast = next(row for row in bundle["action_catalog"] if row["display_name"].endswith("Cast Axe: Shock Cast"))
    assert cast["parameters"]["typed"]["range_ft"] == 20 and cast["range_ft"] == 60  # thrown, 20/60


def test_without_an_axe_the_axe_talents_are_not_offered():
    bundle = compile_character(_axe_fighter(["tianxia.mortal.weapon.dao"]), actor_id=ACTOR)
    assert not any("Hewing Strike" in row["display_name"] for row in bundle["action_catalog"])
    assert any("Hewing Strike" in note and "needs an axe" in note for note in bundle["diagnostics"]["notes"])
