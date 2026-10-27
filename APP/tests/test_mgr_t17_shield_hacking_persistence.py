"""Shield-Hacking Rhythm persists through real table commits and cold reloads."""
import pytest

from combat.factory_compiler import compile_character
from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn
from tests.test_mgr_t17_shield_hacking_rhythm import t, FORWARD, TALENT, DAO_KIT, SHIELD_KIT, EDGE, CONDITION, RHYTHM


@pytest.mark.parametrize("consume", [True, False])
def test_denial_survives_table_reload_and_consumes_or_expires(tmp_path, consume):
    sheet = t._sheet("tianxia.sphere.sabers", [FORWARD, TALENT], DAO_KIT, dc=50)
    sheet["spheres_and_talents"]["automatic_sphere_component_record_ids"] = []
    owner = compile_character(sheet, actor_id=OWNER)
    foe = t._sheet("", (), SHIELD_KIT)
    foe["proficiencies"] = {"armor": ["Shield"]}

    def prepare(bundles):
        for i, bundle in enumerate(bundles):
            bundle["actor_template"]["initiative_bonus"] = (100, 0, -100)[i]
            bundle["actor_template"]["maximum_hp"] = 500
        bundles[2]["actor_template"]["armor_class"] = -50
        pool = next(r for r in bundles[0]["actor_template"]["resources"] if r["resource_id"] == EDGE)
        pool["initial"] = 1
        add_action(bundles[1], "Test strike", [{"type": "attack", "attack_kind": "cultivation", "no_damage": True}],
                   target="HOSTILE_ENTITY", typed={"numbers": {"attack_bonus": 100, "pb": 4, "key_mod": 2, "save_dc": 16, "cl": 15}})
        for bundle in bundles:
            seal(bundle)

    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner, foe_sheet=foe, bundle_transform=prepare,
                                positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 5}, FOE: {"x": 4, "y": 6}})
    settle(table, mid, candidate(combat, mid, RHYTHM, target=FOE).candidate_id)
    loaded = reload(tmp_path, mid)
    assert any(c.condition_id == CONDITION for c in loaded.state.actors[FOE].conditions.values())
    turn(table, mid, ALLY)
    if consume:
        settle(table, mid, candidate(combat, mid, "Test strike", target=FOE).candidate_id)
        loaded = reload(tmp_path, mid)
        assert not any(c.condition_id == CONDITION for c in loaded.state.actors[FOE].conditions.values())
        roll = [e for e in loaded.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == ALLY][-1]
        assert roll.payload["target_ac"] == -52
    else:
        turn(table, mid, OWNER)
        loaded = reload(tmp_path, mid)
        assert not any(c.condition_id == CONDITION for c in loaded.state.actors[FOE].conditions.values())
