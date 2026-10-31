"""Native scene-author save statistics persist without an inferred creator."""
import pytest

from combat.tabletop import TabletopMapStore, TabletopError
from combat.asset_anchor_runtime import saving_throw_bonus
from tests.test_mgr_t14_object_packet_geometry import start


@pytest.mark.parametrize('value', [True, '0', 1.5, 1001, -1001])
def test_native_object_save_profile_rejects_noninteger_or_out_of_bound_statistics(tmp_path, value):
    with pytest.raises((ValueError, TabletopError)):
        TabletopMapStore(tmp_path / 'maps').save({'display_name': 'Invalid save profile',
            'width_squares': 20, 'height_squares': 18,
            'objects': [{'kind': 'custom', 'x': 5, 'y': 6, 'saving_throw_bonus': value,
                'asset_declaration': {'actor': 'table-owner', 'authority': 'GM',
                    'source_rule': 'Scene object statistics', 'visibility': 'gm', 'expiry': 'source_rule'}}]})


def test_unknown_cultivated_profile_does_not_invent_a_saving_throw_modifier(tmp_path):
    # This uses real admitted map data and cold state, not a fabricated object.
    # It certifies only profile admission/query, not ability-created acquisition.
    combat, _, mid = start(tmp_path)
    session = combat._load_session(mid)
    assert saving_throw_bonus(session.engine, session.engine.state.objects['object:map.1']) is None
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
