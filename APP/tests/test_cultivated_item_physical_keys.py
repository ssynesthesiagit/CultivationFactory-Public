"""Equipment properties retain their identity across preparation and a cold table load."""
from combat.ext.item_cultivation import carried_properties
from combat.factory_compiler import compile_character
from tests import worker2_support as fight
from tests.h1_support import sheet


def test_empty_palm_can_find_refinement_after_an_earlier_given_item_is_left_behind(tmp_path):
    items = [
        {"kind": "wondrous", "record": {"name": "Spare compass"}},
        {"kind": "weapon", "record": {
            "name": "Refined dagger",
            "chassis": {"item_id": "tianxia.mortal.weapon.bi_shou", "name": "Dagger", "damage": "1d4 Piercing"},
            "refinement_bonus": 2,
        }},
    ]
    owner_bundle = compile_character(sheet([], cl=10), actor_id=fight.OWNER,
                                     owner_items=items, left_behind=["given.0"])
    _, _, match_id = fight.fixture(tmp_path, [], cl=10, owner_bundle=owner_bundle)
    engine = fight.reload(tmp_path, match_id)
    owner = engine.state.actors[fight.OWNER]
    properties = carried_properties(engine, owner)
    assert any(row["item_key"] == "given.1" and
               any(prop["key"] == "refinement" for prop in row["properties"]) for row in properties)
