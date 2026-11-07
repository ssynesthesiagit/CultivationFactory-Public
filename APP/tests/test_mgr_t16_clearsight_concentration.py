"""Clearsight consent never separates its protection from the caster's Meld."""
import copy

from combat import concentration, senses, zones
from combat.ext.tabik_dark import CLEARSIGHT_PERMISSION
from tests.test_a2_dark_melds import darkness_affects_everyone
from tests.worker2_support import OWNER, ALLY, fixture, candidate, reload, settle, turn


def test_allied_creator_permission_ends_with_replaced_caster_concentration(tmp_path):
    def setup(bundles):
        darkness_affects_everyone(bundles)
        owner = bundles[0]
        owner['concentration_rules'] = {'capacity': 'cultivation_level', 'limits_by_cl': [[1, 1]]}
        for bundle in bundles[:2]:
            bundle.setdefault('senses', {})['rows'] = [
                {'feature_id': 'test:ordinary', 'sense': 'blindsight', 'range_ft': 60, 'when': 'always'}]
            for action in bundle['action_catalog']:
                if action['display_name'] == 'Darkness':
                    action['concentration'] = False
                    action['parameters']['typed']['duration']['concentration'] = False
        control = copy.deepcopy(next(a for a in owner['action_catalog']
                                     if a['display_name'] == 'Meld: Clearsight'))
        control.update(source_definition_id='test:replace-clearsight',
                       display_name='Control: Concentration', target_kind='SELF')
        control['parameters'] = {'typed': {'effects': [], 'numbers': {},
            'duration': {'kind': 'hours', 'amount': 1, 'concentration': True}, 'riders': []}}
        owner['action_catalog'].append(control)
        owner['actor_template']['action_ids'].append(control['source_definition_id'])

    combat, table, mid = fixture(tmp_path, ['TAL_DARK_CLEARSIGHT'],
        ally_talents=['TAL_DARK_PURE_DARKNESS'], bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, 'Meld: Clearsight', target=ALLY).candidate_id,
           picks={'choice:needle.clearsight_creator_consent': 'allow'})
    engine = reload(tmp_path, mid)
    marker = next(c for c in engine.state.actors[ALLY].conditions.values()
                  if c.condition_id == senses.MELD and c.data.get('talent') == 'TAL_DARK_CLEARSIGHT')
    source = marker.source_definition_id
    assert concentration.concentrating_on(engine.state.actors[OWNER], source)
    assert any(c.condition_id == CLEARSIGHT_PERMISSION for c in engine.state.actors[ALLY].conditions.values())
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Shape Darkness: Pure Darkness').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Darkness', at=(4, 6)).candidate_id)
    engine = reload(tmp_path, mid)
    area = next(z for z in zones.typed_zones(engine) if z.owner_id == ALLY)
    assert zones.clear_sighted(engine, area, engine.state.actors[ALLY])
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Control: Concentration', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert not concentration.concentrating_on(engine.state.actors[OWNER], source), concentration.sources(engine.state.actors[OWNER])
    assert any(e.event_type == 'CONCENTRATION_ENDED' and e.source_definition_id == source for e in engine.events)
    assert marker.instance_id not in engine.state.actors[ALLY].conditions
    area = next(z for z in zones.typed_zones(engine) if z.owner_id == ALLY)
    assert not zones.clear_sighted(engine, area, engine.state.actors[ALLY])
    assert any(c.condition_id == zones.ZONE_EFFECT and c.data.get('zone_id') == area.zone_id
               for c in engine.state.actors[ALLY].conditions.values())
