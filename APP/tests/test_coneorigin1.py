"""Only explicitly placed cones offer an origin-including menu alternative."""
import pytest

from combat.cone_origin import targeting_alternatives
from combat.gate2_runtime_models import ActionDefinition
from tests import test_tabletop_hunt6 as H
from tests.test_lock_choices import install
from tests.test_playtest1014 import cold


def cone(owner, **area):
    return ActionDefinition(source_definition_id='test:coneorigin1.' + owner,
        display_name='Practice cone', owner_id=owner, economy='ACTION',
        resolution_kind='TYPED', target_kind='CELL', range_ft=60, radius_ft=30,
        parameters={'typed': {'area': {'shape': 'cone', 'size_ft': 30, **area},
                              'effects': []}})


@pytest.mark.parametrize('area,count', [
    ({}, 1),
    ({'placed': False}, 1),
    ({'centered_on_self': True}, 1),
    ({'text': '30-foot cone originating from you'}, 1),
    ({'origin': 'self', 'anchor': 'self'}, 1),
    ({'origin': 'unknown'}, 1),
    ({'placed': True}, 2),
    ({'placed': True, 'include_origin': False}, 1),
    ({'placed': True, 'include_origin': True}, 1),
])
def test_origin_metadata_preserves_original(area, count):
    action = cone(H.LEFT, **area)
    before = action.model_dump(mode='json')
    alternatives = targeting_alternatives(action)
    assert len(alternatives) == count
    assert alternatives[0] is action
    assert action.model_dump(mode='json') == before
    if count == 2:
        assert alternatives[1].parameters['typed']['area']['include_origin'] is True


@pytest.mark.parametrize('placed,count', [(False, 1), (True, 2)])
def test_one_self_origin_menu_option_two_placed_origin_options(monkeypatch, tmp_path, placed, count):
    def actions(info):
        return [cone(info['actor_id'], placed=placed)]
    install(monkeypatch, 'compile_actions', actions)
    combat, table, mid = H.table_fight(tmp_path, [], ally_talents=[])
    for state in (table.state(mid), cold(tmp_path, mid)[1].state(mid)):
        groups = [g for g in state['menu']['actions']
                  if g['source_definition_id'].startswith('test:coneorigin1.' + H.LEFT)]
        assert len(groups) == count
        assert sum('include the cone’s starting space' in g['label'] for g in groups) == count - 1
