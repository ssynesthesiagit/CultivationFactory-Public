"""Printed Shove Aside legality and readable Disarm equipment at the native table."""
from combat.factory_compiler import compile_character
from combat.dynamic_size import current_category
from tests.h1_support import sheet
from tests.worker2_support import OWNER, FOE, fixture, candidate, reload, settle
from tests.cw2_service_support import seal
from tests.test_mgr_t14_brute_disarm import KIT, MANEUVERS, prepare, pick


def sized_owner(size):
    doc = sheet([MANEUVERS], kit=KIT, name="Wren")
    doc["identity"]["size"] = size
    return compile_character(doc, actor_id=OWNER, reaction_plan={"ask": True})


def test_shove_aside_rejects_a_target_two_categories_larger(tmp_path):
    combat, table, mid = fixture(tmp_path, [MANEUVERS], owner_kit=KIT, foe_kit=KIT,
        owner_bundle=sized_owner("Tiny"), foe_position={"x": 4, "y": 5})
    e = reload(tmp_path, mid)
    assert current_category(e, e.state.actors[OWNER]) == "Tiny"
    assert current_category(e, e.state.actors[FOE]) == "Medium"
    assert not any(c.display_name == "Shove Aside" and c.target_ids == (FOE,)
                   for c in e.legal_candidates())


def test_shove_aside_keeps_a_target_one_category_larger_legal(tmp_path):
    def setup(bundles):
        bundles[0]["skills"] = {"Athletics": 100}
        bundles[2]["skills"] = {"Athletics": -100, "Acrobatics": -100}
        for bundle in bundles:
            seal(bundle)
    combat, table, mid = fixture(tmp_path, [MANEUVERS], owner_kit=KIT, foe_kit=KIT,
        owner_bundle=sized_owner("Small"), foe_position={"x": 4, "y": 5},
        ally_position={"x": 1, "y": 6}, bundle_transform=setup)
    e = reload(tmp_path, mid)
    assert current_category(e, e.state.actors[OWNER]) == "Small"
    settle(table, mid, candidate(combat, mid, "Shove Aside", target=FOE).candidate_id,
           {"choice:needle.shove_aside": "cell:2,5"})
    e = reload(tmp_path, mid)
    assert (e.state.actors[FOE].position.x, e.state.actors[FOE].position.y) == (2, 5)


def test_disarm_item_id_only_import_has_readable_choice_and_drop_log(tmp_path):
    item_id = "tianxia.mortal.weapon.dao"
    unnamed = {"starting_kit": {"items": [{"item_id": item_id, "quantity": 1}]}}
    combat, table, mid = fixture(tmp_path, [MANEUVERS], owner_kit=KIT, foe_kit=unnamed,
        foe_position={"x": 4, "y": 5}, named=True, bundle_transform=prepare(True))
    prompts = settle(table, mid, pick(reload(tmp_path, mid)))
    prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.brute_disarm_item")
    labels = [o["label"] for o in prompt["choice"]["options"]]
    assert len(labels) == 1 and "Dao" in labels[0] and item_id not in labels[0]
    e = reload(tmp_path, mid)
    log = next(event.payload["log"] for event in reversed(e.events)
               if " drops " in str(event.payload.get("log", "")))
    assert "Dao" in log and item_id not in log
