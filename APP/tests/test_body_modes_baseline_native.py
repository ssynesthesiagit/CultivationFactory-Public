import pytest
from tests import test_body_modes_native as n
@pytest.mark.parametrize('parent,cl',[(n.NINE,18),(n.FURNACE,3)])
def test_actual_base_lacks_source_scene_contract(tmp_path,monkeypatch,parent,cl):
    n.test_acquired_progression_has_native_scene_and_mode_contract({},monkeypatch,tmp_path,parent,cl)
