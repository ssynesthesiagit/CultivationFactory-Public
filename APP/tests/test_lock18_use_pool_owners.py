"""Forged limit text survives compilation, table persistence and reload."""
import copy
import pytest
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from tests.h1_support import sheet, ROOT
from tests import test_tabletop_hunt6 as helpers
from tests.test_tabletop_hunt6 import LEFT, HOLD
from tests.test_lock2_persistence import act

TECHNIQUE = {'technique_id': 'forged:test.music_aura', 'name': 'Music Aura',
    'primary_sphere_effect': {'talent_id': 'SOURCE_BASE_SOURCE_PULSE'},
    'base_form': {'form_id': 'aura'}, 'drawbacks': [], 'augments': [],
    'cp_cost': {'final': 1}, 'action_type': 'action'}


def document(limits):
    result = sheet(['SOURCE_BASE_SOURCE_PULSE'])
    result['forged_techniques'] = [{**TECHNIQUE, 'limits': limits}]
    return result


@pytest.mark.parametrize('limits,expected', [([], None), (['Once per long rest'], 'Once per long rest'),
    (['Once per short rest', 'Only while conscious'], 'Once per short rest; Only while conscious')])
def test_printed_limits_are_preserved_without_guessing_from_hash(limits, expected):
    original = document(limits)
    before = copy.deepcopy(original)
    bundle = compile_character(original, actor_id=LEFT)
    action = next(a for a in bundle['action_catalog'] if a['display_name'] == 'Music Aura')
    typed = action['parameters']['typed']
    assert typed['source'] == TECHNIQUE['technique_id']
    assert 'music_aura' not in action['source_definition_id']
    assert typed.get('use_limit') == expected
    assert ('use_limit' in typed) == (expected is not None)
    assert original == before


def test_opaque_action_limit_survives_table_commit_reload(monkeypatch, tmp_path):
    original = helpers.sheet
    def forged(mids, **kwargs):
        result = original(mids, **kwargs)
        if mids:
            result['forged_techniques'] = [{**TECHNIQUE, 'limits': ['Once per long rest']}]
        return result
    monkeypatch.setattr(helpers, 'sheet', forged)
    service, table, mid = helpers.table_fight(tmp_path, ['SOURCE_BASE_SOURCE_PULSE'], ally_talents=[])
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    action = next(a for a in loaded.engine.action_catalog.values() if a.owner_id == LEFT and a.display_name == 'Music Aura')
    assert action.parameters['typed']['use_limit'] == 'Once per long rest'
    assert any(rid.startswith('resource:uses.') and amount == 1 for rid, amount in action.costs)
    assert loaded.verify()['status'] == 'PASS'
