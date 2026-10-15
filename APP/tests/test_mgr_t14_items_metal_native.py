"""Metal acquisition, map inputs, table choices and cold mechanical replay."""
import pytest
from combat import tabletop
from tests.test_mgr_t14_items_weapon_delivery import acquire, native
from tests.worker2_support import OWNER, FOE, reload
from tests.test_auto2_talismans import take

METAL = 'tianxia.sphere.metal'


def objects(**changes):
    def transform(arena):
        row = {'id': 1, 'x': 4, 'y': 5, 'kind': 'custom', 'size': 'tiny',
               'material': 'iron', 'unattended': True, 'blocks': False, **changes}
        doc = tabletop.normalize_map({'width': 20, 'height': 20, 'objects': [row]})
        arena['map_objects'] = doc['objects']
    return transform


@pytest.mark.parametrize('declaration', [{}, {'material': 'wood', 'metal': True}, {'material': 'steel'}])
def test_native_magnet_moves_real_object_and_spends_only_interaction(tmp_path, declaration):
    doc = acquire(tmp_path, METAL)
    combat, table, mid = native(tmp_path, doc, battlefield_transform=objects(**declaration))
    before = reload(tmp_path / 'fight', mid)
    actor = before.state.actors[OWNER]
    budget = (actor.action_available, actor.bonus_action_available, actor.reaction_available, dict(actor.resources))
    origin = before.state.objects['object:map.1'].position
    prompts = take(combat, table, mid, 'Magnet Hand')
    assert {p['context']['reaction_source_id'] for p in prompts} >= {'choice:needle.magnet_hand_object','choice:needle.magnet_hand_destination'}
    after = reload(tmp_path / 'fight', mid)
    actor = after.state.actors[OWNER]
    assert (actor.action_available, actor.bonus_action_available, actor.reaction_available, dict(actor.resources)) == budget
    assert after.state.objects['object:map.1'].position != origin
    assert after.grid.distance_ft(origin, after.state.objects['object:map.1'].position) <= 10
    assert not any(c.display_name == 'Magnet Hand' for c in after.legal_candidates())
    assert not any(e.event_type == 'DAMAGE_COMMITTED' for e in after.events)


@pytest.mark.parametrize('changes', [{'unattended': False}, {'size': 'small'}, {'material': 'wood'}, {'movable': False}, {'x': 12}])
def test_magnet_rejects_illegal_objects(tmp_path, changes):
    doc = acquire(tmp_path, METAL)
    combat, table, mid = native(tmp_path, doc, battlefield_transform=objects(**changes))
    engine = reload(tmp_path / 'fight', mid)
    assert not any(c.display_name == 'Magnet Hand' for c in engine.legal_candidates())


@pytest.mark.parametrize('kind', ['SLASHING','PIERCING'])
def test_sharpen_hit_asks_and_replays_selected_packet(tmp_path, kind):
    doc = acquire(tmp_path, METAL)
    combat, table, mid = native(tmp_path, doc, foe_position={'x': 8,'y':6})
    prompts = take(combat, table, mid, 'Needle Flick', FOE, {'choice:needle.sharpen_type': kind})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.sharpen_type' for p in prompts)
    engine = reload(tmp_path / 'fight', mid)
    packets = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
               and (e.payload or {}).get('display_source_id') == 'passive:METAL_BASE_SHARPEN']
    assert packets
    assert any(str(e.payload.get('damage_type')).upper() == kind for e in packets)
