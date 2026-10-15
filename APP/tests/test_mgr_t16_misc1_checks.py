"""Exact owned check/save qualifiers, service commits and cold replay."""
import pytest

from combat.canonical import canonical_sha256
from combat.ext.drunken_style import NO_PATTERN
from tests.test_mgr_t16_misc1_ledger import probe, checks
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, settle, turn

WIND = 'TAL_AIR_WIND_SENSE'


def focus_payment(bundle):
    """Seal an actual Focus payment; the no-Focus cases commit it at the table."""
    source = 'action:test.spend_focus'
    bundle['action_catalog'].append({'source_definition_id': source, 'display_name': 'Spend held focus',
        'owner_id': bundle['actor_id'], 'economy': 'BONUS_ACTION', 'resolution_kind': 'TYPED',
        'target_kind': 'SELF', 'costs': [], 'parameters': {'typed': {'source': source, 'effects': [
            {'type': 'spend_resource', 'resource_id': 'resource:core.martial_focus', 'flat': 1, 'applies_to': 'self'}]}}})
    bundle['actor_template']['action_ids'].append(source)
    bundle.pop('bundle_sha256', None); bundle['bundle_sha256'] = canonical_sha256(bundle)


@pytest.mark.parametrize('tags,target,expected', [
    (('moving_creature',), FOE, 'ADVANTAGE'),
    (('moving_creature', 'motionless_creature'), FOE, 'NORMAL'),
    (('moving_creature', 'airtight_barrier'), FOE, 'NORMAL'),
    (('moving_creature', 'superior_concealment'), FOE, 'NORMAL'),
    (('moving_creature', 'superior_concealment', 'opposed_concealment'), FOE, 'ADVANTAGE'),
    (('incoming_projectile',), FOE, 'ADVANTAGE'),
    (('gas',), FOE, 'ADVANTAGE'),
    (('smoke',), FOE, 'ADVANTAGE'),
    (('pressure_change',), FOE, 'ADVANTAGE'),
    (('door_airflow',), FOE, 'ADVANTAGE'),
    (('ordinary_sight',), FOE, 'NORMAL'),
])
def test_wind_sense_pending_perception_context(tmp_path, tags, target, expected):
    labels=[]
    def seal(bundles):
        labels.append(probe(bundles[0], 'WIS', 'Perception', tags))
    combat, table, mid = fixture(tmp_path, [WIND], bundle_transform=seal, seed='T16-WIND'+'-'.join(tags))
    settle(table, mid, candidate(combat, mid, labels[0], target=target).candidate_id)
    assert checks(reload(tmp_path, mid), OWNER)[-1]['mode'] == expected


def test_wind_sense_moving_creature_has_thirty_foot_bound(tmp_path):
    labels=[]
    def seal(bundles):
        labels.append(probe(bundles[0], 'WIS', 'Perception', ('moving_creature',)))
    combat, table, mid = fixture(tmp_path, [WIND], bundle_transform=seal, seed='T16-WIND-RANGE',
        foe_position={'x': 10, 'y': 6}, battlefield_transform=lambda arena: arena.update(terrain_regions=[]))
    settle(table, mid, candidate(combat, mid, labels[0], target=FOE).candidate_id)
    assert checks(reload(tmp_path, mid), OWNER)[-1]['mode'] == 'NORMAL'


@pytest.mark.parametrize('owned,focus,tags,expected', [
    (True, True, ('predictive_movement_control',), 'ADVANTAGE'),
    (False, True, ('predictive_movement_control',), 'NORMAL'),
    (True, False, ('predictive_movement_control',), 'NORMAL'),
    (True, True, ('ordinary_sight',), 'NORMAL'),
])
def test_no_pattern_check_ownership_focus_and_source_scope(tmp_path, owned, focus, tags, expected):
    labels=[]
    def seal(bundles):
        labels.append(probe(bundles[0], 'DEX', 'Acrobatics', tags))
        focus_payment(bundles[0])
    combat, table, mid = fixture(tmp_path, [NO_PATTERN] if owned else [], bundle_transform=seal,
        seed='T16-NOPATTERN'+str(owned)+str(focus)+str(tags))
    if not focus:
        settle(table, mid, candidate(combat, mid, 'Spend held focus').candidate_id)
    settle(table, mid, candidate(combat, mid, labels[0], target=FOE).candidate_id)
    assert checks(reload(tmp_path, mid), OWNER)[-1]['mode'] == expected


@pytest.mark.parametrize('category,focus,expected', [
    ('predictive_movement_control', True, 'ADVANTAGE'),
    ('predictive_movement_control', False, 'NORMAL'),
    ('ordinary_sight', True, 'NORMAL'),
])
def test_no_pattern_save_keeps_the_actual_pending_source_scope(tmp_path, category, focus, expected):
    def seal(bundles):
        focus_payment(bundles[0])
        b=bundles[2]
        source='action:test.no_pattern_save'
        b['action_catalog'].append({'source_definition_id':source,'display_name':'Predictive save',
            'owner_id':FOE,'economy':'ACTION','resolution_kind':'TYPED','target_kind':'HOSTILE_ENTITY',
            'range_ft':60,'costs':[], 'parameters':{'typed':{'source':source,'numbers':{'save_dc':15},
                'effects':[{'type':'save','ability':'dex','applies_to':'target','save_categories':[category],
                    'on_fail':[],'on_success':[]}]}}})
        b['actor_template']['action_ids'].append(source)
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat, table, mid = fixture(tmp_path, [NO_PATTERN], bundle_transform=seal, seed='T16-PREDICTIVE-SAVE'+category+str(focus))
    if not focus:
        settle(table, mid, candidate(combat, mid, 'Spend held focus').candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Predictive save', target=OWNER).candidate_id)
    engine=reload(tmp_path,mid)
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.source_definition_id=='action:test.no_pattern_save']
    assert saves and saves[-1].payload['mode']==expected
