"""Protected object choices through the actual owned Basin wash menu."""
import pytest
from tests.test_mgr_t15_close_cleansing_water import ME, setup, action, settle, cold


@pytest.mark.parametrize('protected', ['object:map.85', 'object:map.86'])
def test_protected_residue_is_not_an_offered_native_wash_target(tmp_path, protected):
    combat, table, mid = setup(tmp_path)
    before = cold(tmp_path, mid).state.objects[protected].model_dump(mode='json')
    prompts = settle(table, mid, action(combat, mid, 'Cleansing Water: Wash Residue'),
                     {'choice:needle.water_wash_residue': None})
    options = {o['id'] for p in prompts for o in (p.get('choice') or {}).get('options', [])}
    assert 'object:map.80' in options, 'Mundane poison residue must remain washable'
    assert protected not in options, 'Magical or contested residue must stay outside the native wash choices'
    e = cold(tmp_path, mid)
    assert e.state.objects[protected].model_dump(mode='json') == before
    assert e.state.actors[ME].temporary_hp == 0
