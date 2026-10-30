"""F5: Listen Through Tension stays offered to the owner after Draw the Line.

Covers the bdiff script-3 gap (owner menu lost Listen after Draw on a creature
while Hundred-Line Weaving was held) and the object-line case the lead asked
for. Each test asserts the owner's real menu, then uses Listen.

Runtime inputs: authority/typed_mechanics/rules_text.json,
authority/Tianxia_Typed_Mechanics_Authority_R1.json,
authority/Tianxia_Forged_Technique_Authority_R1.json,
authority/Tianxia_Immortal_Art_Authority_R1.json,
catalog_authority/cat3/generated/catalog_authority.v1.json,
authority/typed_mechanics/reviewed_final.d/review_sw-thread.json,
authority/Tianxia_Sphere_Path_Access_R1.json,
catalog_authority/cat1/data/prerequisite_projection.v1.json.
"""
from tests.mgr_t15_listen_fixture import P, HUNDRED, fight, cold, mundane, choose, candidate, private, grants

BELL = [{'id': 1, 'kind': 'custom', 'name': 'Bell', 'x': 7, 'y': 5, 'blocks': False, 'ac': 10, 'hp': 30}]


def owner_labels(table, mid):
    menu = table.state(mid)['menu']
    return [o.get('label', '') for group in menu.get('actions', []) for o in group.get('options', [])]


def test_listen_offered_to_owner_after_draw_on_creature_with_weaving(tmp_path):
    _, table, mid = fight(tmp_path, owner_talents=[HUNDRED])
    mundane(table, mid)
    assert any('Listen Through Tension' in label for label in owner_labels(table, mid))
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('handling',))
    assert private(table, mid)[0]['handling'] == 'unknown'
    assert len(grants(cold(tmp_path, mid))) == 1


def test_listen_offered_to_owner_after_draw_on_object_with_weaving(tmp_path):
    _, table, mid = fight(tmp_path, owner_talents=[HUNDRED], objects=BELL)
    choose(table, mid, candidate(table, mid, 'Draw the Line: Guide (Qi Thread) (at an object)', 'object:map.1'))
    assert any('Listen Through Tension' in label for label in owner_labels(table, mid))
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('motion',))
    assert private(table, mid)[0]['motion'] == 'still'
    assert len(grants(cold(tmp_path, mid))) == 1
