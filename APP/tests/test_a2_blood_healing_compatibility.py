"""No-Court compatibility: public service/table commits and cold replay."""
import copy
import pytest
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, act, resolve, turn, reload
from tests.test_a2_blood_court import table_fight
from combat.ext.fate_riders import PURITY


def seal_purity(bundle):
    if bundle['actor_id'] != LEFT:
        return
    court = next(a for a in bundle['action_catalog'] if a['source_definition_id'].endswith('.crimson_court'))
    purity = copy.deepcopy(court)
    purity.update(source_definition_id='action:test.purity', display_name='Purity', economy='NONE', costs=[])
    typed = purity['parameters']['typed']
    typed['source'] = PURITY
    typed['effects'] = [r for r in typed['effects'] if r['type'] == 'zone']
    bundle['action_catalog'].append(purity)
    bundle['actor_template']['action_ids'].append(purity['source_definition_id'])


def seal_statue(bundle):
    if bundle['actor_id'] != ALLY:
        return
    sid = 'action:test.golden_statue'
    bundle['actor_template']['action_ids'].append(sid)
    bundle['action_catalog'].append({'source_definition_id':sid, 'display_name':'Become statue',
        'owner_id':ALLY, 'economy':'NONE', 'resolution_kind':'TYPED', 'target_kind':'SELF', 'costs':[],
        'parameters':{'typed':{'effects':[{'type':'golden_statue'}],
            'numbers':{'cl':15, 'pb':4, 'key_mod':3}, 'duration':{'kind':'instant'}, 'riders':[]}}})


def seal_stamina(bundle):
    if bundle['actor_id'] == LEFT:
        next(a for a in bundle['action_catalog'] if a['display_name'] == 'Spend Stamina')['costs'] = [
            ['resource:core.stamina', 1]]


def penalty(kind, applies_to='target'):
    if kind == 'intercept':
        return {'type':'intercept_healing', 'reduce':3, 'kinds':['hp'], 'each_from_cl':99,
            'expires_on':'UNTIL_REMOVED', 'name':'Recovery reduction', 'applies_to':applies_to}
    return {'type':'healing_reduction', 'applies_to':applies_to, 'expires_on':'UNTIL_REMOVED',
        'evidence': 'Healing received is halved.' if kind == 'half' else
                    'Healing received is reduced by your Proficiency Bonus.'}


@pytest.mark.parametrize('kind', ['half', 'minus', 'intercept'])
def test_no_court_blood_furnace_keeps_historical_preparation(tmp_path, kind):
    combat, table, mid = table_fight(tmp_path, left_resource='Stamina', bundle_edit=seal_stamina,
        prepare=[{'type':'cte_choice', 'expression':'blood_furnace'},
                 {'type':'damage', 'applies_to':'self', 'flat':100, 'damage_types':['force']},
                 penalty(kind, 'self')], extra_actions=[('Spend Stamina', {'effects':[]})])
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT))
    before = reload(combat, mid)
    assert not any(z.active for z in before.state.zones.values())
    seq, hp = before.state.event_sequence, before.state.actors[LEFT].current_hp
    resolve(lambda a: act(table, mid, 'Spend Stamina', a))
    after = reload(combat, mid)
    gain = 1 if kind == 'intercept' else 4  # native interception existed; stored penalties did not
    assert after.state.actors[LEFT].current_hp == hp + gain
    receipts = [{k:e.payload[k] for k in ('offered', 'before', 'after')} for e in after.events
                if e.sequence > seq and e.event_type == 'HEALING_APPLIED']
    assert receipts == [{'offered':gain, 'before':hp, 'after':hp + gain}]


@pytest.mark.parametrize('kind', ['half', 'minus', 'intercept'])
def test_no_court_statue_keeps_historical_direct_receipt(tmp_path, kind):
    combat, table, mid = table_fight(tmp_path, bundle_edit=seal_statue,
        cause=[{'type':'damage', 'flat':100, 'damage_types':['force']}, penalty(kind)])
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=ALLY))
    turn(table, mid, ALLY)
    resolve(lambda a: act(table, mid, 'Become statue', a))
    turn(table, mid, LEFT)
    before = reload(combat, mid)
    assert not any(z.active for z in before.state.zones.values())
    seq, hp = before.state.event_sequence, before.state.actors[ALLY].current_hp
    turn(table, mid, ALLY)
    after = reload(combat, mid)
    assert after.state.actors[ALLY].current_hp == hp + 20
    receipts = [{k:e.payload[k] for k in ('offered', 'before', 'after')} for e in after.events
                if e.sequence > seq and e.event_type == 'HEALING_APPLIED']
    assert receipts == [{'offered':20, 'before':hp, 'after':hp + 20}]
    if kind == 'intercept':
        assert any(c.condition_id == 'condition:typed.healing_intercept'
                   for c in after.state.actors[ALLY].conditions.values())


@pytest.mark.parametrize('kind', ['half', 'minus', 'intercept'])
def test_no_court_purity_keeps_historical_secondary_receipt(tmp_path, kind):
    combat, table, mid = table_fight(tmp_path, bundle_edit=seal_purity,
        cause=[{'type':'damage', 'flat':100, 'damage_types':['force']}, penalty(kind)],
        prepare=[{'type':'healing', 'applies_to':'target', 'flat':10}])
    resolve(lambda a: act(table, mid, 'Purity', a))
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=ALLY))
    turn(table, mid, LEFT)
    before = reload(combat, mid)
    seq, hp = before.state.event_sequence, before.state.actors[ALLY].current_hp
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=ALLY))
    after = reload(combat, mid)
    primary = {'half':5, 'minus':6, 'intercept':7}[kind]
    assert after.state.actors[ALLY].current_hp == hp + primary + 4
    receipts = [{k:e.payload[k] for k in ('offered', 'before', 'after')} for e in after.events
                if e.sequence > seq and e.event_type == 'HEALING_APPLIED']
    # Purity's event subscriber emits the nested receipt before the primary receipt.
    assert len(receipts) == 2
    secondary = next(p for p in receipts if p['before'] == hp + primary)
    assert secondary == {'offered':4, 'before':hp + primary, 'after':hp + primary + 4}


def test_no_court_statue_retains_capped_offer_receipt(tmp_path):
    combat, table, mid = table_fight(tmp_path, bundle_edit=seal_statue,
        cause=[{'type':'damage', 'flat':7, 'damage_types':['force']}])
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=ALLY))
    turn(table, mid, ALLY)
    resolve(lambda a: act(table, mid, 'Become statue', a))
    turn(table, mid, LEFT)
    seq = reload(combat, mid).state.event_sequence
    turn(table, mid, ALLY)
    after = reload(combat, mid)
    assert after.state.actors[ALLY].current_hp == 1000
    receipts = [{k:e.payload[k] for k in ('offered', 'before', 'after')} for e in after.events
                if e.sequence > seq and e.event_type == 'HEALING_APPLIED']
    assert receipts == [{'offered':7, 'before':993, 'after':1000}]
