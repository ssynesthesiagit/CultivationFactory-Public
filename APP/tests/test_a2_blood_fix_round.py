"""Review regressions: real table intents, transaction rollback and cold replay."""
import copy

import pytest

from combat.ext.blood_reversal import CHOICE, FEATURE, USED
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, act, resolve, turn, reload
from tests.test_a2_blood_court import table_fight, cast, COURT
from tests.test_a2_blood_reversal import fight, wound


@pytest.mark.parametrize('evidence,offered,expected,next_expected', [
    ('Healing received is reduced by your Proficiency Bonus.', 10, 11, 7),
    ('Healing received is halved.', 5, 4, 2),
    ('Healing received is reduced by your Proficiency Bonus.', 2, 3, 0),
    ('The next healing received is reduced by your Proficiency Bonus.', 10, 11, 10),
])
def test_court_combines_before_one_reduction_and_one_receipt(tmp_path, evidence, offered, expected, next_expected):
    combat, table, mid = table_fight(tmp_path, right_pb=3, left_pb=3 if 'halved' in evidence else 4,
        cause=[{'type':'damage','flat':100,'damage_types':['force']},
               {'type':'healing_reduction','evidence':evidence,'expires_on':'UNTIL_REMOVED'}],
        prepare=[{'type':'healing','applies_to':'target','flat':offered}])
    cast(combat, table, mid)
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=ALLY))
    turn(table, mid, LEFT)
    for gain in (expected, next_expected):
        before = reload(combat, mid)
        seq, hp = before.state.event_sequence, before.state.actors[ALLY].current_hp
        resolve(lambda a: act(table, mid, 'Prepare', a, target_id=ALLY))
        after = reload(combat, mid)
        receipts = [e for e in after.events if e.sequence > seq and e.event_type == 'HEALING_APPLIED']
        assert after.state.actors[ALLY].current_hp == hp + gain
        assert len(receipts) == 1
        assert receipts[0].payload['offered'] == gain


def test_court_bonus_is_intercepted_as_part_of_one_heal(tmp_path):
    combat, table, mid = table_fight(tmp_path,
        cause=[{'type':'damage','flat':100,'damage_types':['force']},
               {'type':'intercept_healing','reduce':3,'kinds':['hp'],'each_from_cl':99,
                'expires_on':'UNTIL_REMOVED','name':'One recovery reduction'}],
        prepare=[{'type':'healing','applies_to':'target','flat':2}])
    cast(combat, table, mid)
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=ALLY))
    turn(table, mid, LEFT)
    seq = reload(combat, mid).state.event_sequence
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=ALLY))
    engine = reload(combat, mid)
    assert engine.state.actors[ALLY].current_hp == 903
    assert len([e for e in engine.events if e.sequence > seq and e.event_type == 'HEALING_APPLIED']) == 1
    assert not any(c.condition_id == 'condition:typed.healing_intercept' for c in engine.state.actors[ALLY].conditions.values())


@pytest.mark.parametrize('nested', [False, True])
def test_legacy_only_court_preserves_two_receipts_and_saved_flag(tmp_path, nested):
    def legacy(bundle):
        for action in bundle['action_catalog']:
            if action['source_definition_id'].endswith('.crimson_court'):
                rows = action['parameters']['typed']['effects']
                marker = {'type':'court_heal_bonus'}
                if nested:
                    marker = {'type':'if_marked','mark':'Unowned test mark','effects':[marker]}
                rows[:] = [r for r in rows if r['type'] != 'blood_court_runtime'] + [marker]
    combat, table, mid = table_fight(tmp_path, bundle_edit=legacy, right_pb=3,
        cause=[{'type':'damage','flat':100,'damage_types':['force']},
               {'type':'healing_reduction','evidence':'Healing received is reduced by your Proficiency Bonus.',
                'expires_on':'UNTIL_REMOVED'}],
        prepare=[{'type':'healing','applies_to':'target','flat':10}])
    cast(combat, table, mid)
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=ALLY))
    turn(table, mid, LEFT)
    seq = reload(combat, mid).state.event_sequence
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=ALLY))
    engine = reload(combat, mid)
    assert engine.state.actors[ALLY].current_hp == 908
    receipts = [e for e in engine.events if e.sequence > seq and e.event_type == 'HEALING_APPLIED']
    assert [e.payload['offered'] for e in receipts] == [7, 1]
    flags = engine.state.actors[ALLY].turn_flags
    assert flags[f'crimson_court_heal_round_{engine.state.round_number}_{engine.state.current_slot_index}'] is True
    assert 'blood_court_healing_turn' not in flags


def test_court_bonus_composes_with_blood_furnace_recovery(tmp_path):
    def seal(bundle):
        if bundle['actor_id'] == LEFT:
            next(a for a in bundle['action_catalog'] if a['display_name'] == 'Spend Stamina')['costs'] = [
                ['resource:core.stamina',1]]
    combat, table, mid = table_fight(tmp_path, left_resource='Stamina', bundle_edit=seal,
        prepare=[{'type':'cte_choice','expression':'blood_furnace'},
                 {'type':'damage','applies_to':'self','flat':100,'damage_types':['force']},
                 {'type':'healing_reduction','applies_to':'self','evidence':'Healing received is halved.',
                  'expires_on':'UNTIL_REMOVED'}],
        extra_actions=[('Spend Stamina', {'effects':[]})])
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT))
    # Prepare the wound before concentration starts. Court's Stamina activation
    # also triggers Blood-Furnace, so advance to a fresh actual turn afterward.
    resolve(lambda a: act(table, mid, 'Crimson Court', a))
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    before = reload(combat, mid)
    seq, hp = before.state.event_sequence, before.state.actors[LEFT].current_hp
    assert any(z.active and z.owner_id == LEFT for z in before.state.zones.values())
    resolve(lambda a: act(table, mid, 'Spend Stamina', a))
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].current_hp == hp + 4  # (PB4 + Court4) / 2
    assert len([e for e in engine.events if e.sequence > seq and e.event_type == 'HEALING_APPLIED']) == 1


def test_court_bonus_composes_with_statue_recovery(tmp_path):
    def seal(bundle):
        if bundle['actor_id'] == ALLY:
            sid = 'action:test.golden_statue'
            bundle['actor_template']['action_ids'].append(sid)
            bundle['action_catalog'].append({'source_definition_id':sid,'display_name':'Become statue',
                'owner_id':ALLY,'economy':'NONE','resolution_kind':'TYPED','target_kind':'SELF','costs':[],
                'parameters':{'typed':{'effects':[{'type':'golden_statue'}],
                    'numbers':{'cl':15,'pb':4,'key_mod':3},'duration':{'kind':'instant'},'riders':[]}}})
    combat, table, mid = table_fight(tmp_path, bundle_edit=seal,
        cause=[{'type':'damage','flat':100,'damage_types':['force']},
               {'type':'healing_reduction','evidence':'Healing received is halved.','expires_on':'UNTIL_REMOVED'}])
    cast(combat, table, mid)
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=ALLY))
    turn(table, mid, ALLY)
    resolve(lambda a: act(table, mid, 'Become statue', a))
    turn(table, mid, LEFT)
    seq = reload(combat, mid).state.event_sequence
    turn(table, mid, ALLY)
    engine = reload(combat, mid)
    assert engine.state.actors[ALLY].current_hp == 912  # (5*PB4 + Court4) / 2
    assert len([e for e in engine.events if e.sequence > seq and e.event_type == 'HEALING_APPLIED']) == 1


def test_court_allowance_precedes_purity_secondary_healing(tmp_path):
    def seal(bundle):
        if bundle['actor_id'] != LEFT:
            return
        court = next(a for a in bundle['action_catalog'] if a['source_definition_id'].endswith('.crimson_court'))
        purity = copy.deepcopy(court)
        purity.update(source_definition_id='action:test.purity', display_name='Purity', economy='NONE', costs=[])
        typed = purity['parameters']['typed']
        from combat.ext.fate_riders import PURITY
        typed['source'] = PURITY
        typed['effects'] = [r for r in typed['effects'] if r['type'] == 'zone']
        bundle['action_catalog'].append(purity)
        bundle['actor_template']['action_ids'].append(purity['source_definition_id'])
    combat, table, mid = table_fight(tmp_path, bundle_edit=seal,
        cause=[{'type':'damage','flat':100,'damage_types':['force']},
               {'type':'healing_reduction','evidence':'Healing received is halved.','expires_on':'UNTIL_REMOVED'}],
        prepare=[{'type':'healing','applies_to':'target','flat':5}])
    cast(combat, table, mid)
    resolve(lambda a: act(table, mid, 'Purity', a))
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=ALLY))
    turn(table, mid, LEFT)
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=ALLY))
    assert reload(combat, mid).state.actors[ALLY].current_hp == 906  # floor((5+4)/2) + floor(4/2)


def test_mixed_court_markers_use_one_allowance(tmp_path):
    def seal(bundle):
        if bundle['actor_id'] != LEFT:
            return
        court = next(a for a in bundle['action_catalog'] if a['source_definition_id'].endswith('.crimson_court'))
        old = copy.deepcopy(court)
        old['source_definition_id'] += '.legacy'
        old['display_name'] = 'Legacy Court'
        old['economy'] = 'NONE'
        old['costs'] = []
        effects = old['parameters']['typed']['effects']
        effects[:] = [r for r in effects if r['type'] != 'blood_court_runtime'] + [{'type':'court_heal_bonus'}]
        bundle['action_catalog'].append(old)
        bundle['actor_template']['action_ids'].append(old['source_definition_id'])
    combat, table, mid = table_fight(tmp_path, bundle_edit=seal,
        cause=[{'type':'damage','flat':100,'damage_types':['force']}],
        prepare=[{'type':'healing','applies_to':'target','flat':5}])
    cast(combat, table, mid)
    resolve(lambda a: act(table, mid, 'Legacy Court', a))
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=ALLY))
    turn(table, mid, LEFT)
    for _ in range(2):
        resolve(lambda a: act(table, mid, 'Prepare', a, target_id=ALLY))
    assert reload(combat, mid).state.actors[ALLY].current_hp == 914


def assert_reversal_prompt(prompt, engine, action):
    assert prompt['reaction'] == 'Blood Reversal'
    assert prompt['action'] == action
    assert engine.state.actors[RIGHT].display_name in prompt['moment']
    assert prompt['affected'] == ''  # the healing recipient remains unchosen
    assert '2 Qi' in prompt['cost']
    for option in prompt['choice']['options']:
        assert engine.state.actors[option['id']].display_name in option['label']
        assert 'Spend 2 cultivation points' in option['label']
        assert 'regains 6 Hit Points' in option['label']


def test_reversal_prompt_identifies_damage_and_unresolved_recipient(tmp_path):
    combat, table, mid = fight(tmp_path)
    wound(combat, table, mid)
    before = reload(combat, mid)
    send = lambda a: act(table, mid, 'Blood Thread', a, target_id=RIGHT)
    first = send([])
    assert first['status'] == 'REACTION_REQUIRED'
    assert_reversal_prompt(first['reaction'], before, 'Blood Thread')
    assert reload(combat, mid).state == before.state
    resolve(send, {CHOICE:[LEFT]})
    assert reload(combat, mid).state.actors[LEFT].current_hp == 966


@pytest.mark.parametrize('accept', [False, True])
def test_manual_reversal_owner_keeps_choice_during_ai_movement(tmp_path, accept):
    from tests.auto_worker1_support import fight as service_fight
    from tests.test_r4_integration import auto_candidate
    def fields(doc, aid):
        doc['spheres_and_talents']['cultivation_insight_record_ids'] = [FEATURE] if aid == LEFT else []
    def seal(bundle):
        if bundle['actor_id'] == LEFT:
            action = next(a for a in bundle['action_catalog'] if a['display_name'] == 'Opportunity Attack')
            action['display_name'] = 'Blood reaction'
            typed = action['parameters']['typed']
            typed.update(sphere='tianxia.sphere.blood', source='BLOOD_BASE_BLOOD_THREAD')
            typed['numbers']['attack_bonus'] = 100
            typed['effects'] = [{'type':'damage','flat':20,'damage_types':['necrotic']}]
    combat, table, mid = service_fight(tmp_path, [], sheet_edit=fields, bundle_edit=seal,
        cause=[{'type':'damage','flat':40,'damage_types':['force']}])
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
    state = table.state(mid)
    move = next(m for m in state['menu']['moves'] if m['destination'] == {'x':6,'y':6})
    auto_candidate(combat, mid, RIGHT, move['candidate_id'])
    before = reload(combat, mid)
    send = lambda answers: table.auto_step(mid, table.state(mid)['last_sequence'], answers)
    result = send([])
    answers = []
    while result['status'] == 'REACTION_REQUIRED' and result['reaction']['context']['reaction_source_id'] != CHOICE:
        prompt = result['reaction']
        answers.append({**prompt['context'],'selection':'USE','option_ids':[o['id'] for o in prompt.get('choice',{}).get('options',[])][:1]})
        result = send(answers)
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert prompt['context']['reactor_id'] == LEFT
    assert_reversal_prompt(prompt, before, 'Blood reaction')
    assert reload(combat, mid).state == before.state
    answers.append({**prompt['context'],'selection':'USE' if accept else 'DECLINE','option_ids':[LEFT] if accept else []})
    assert send(answers)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources['resource:core.qi'] == 100 - (2 if accept else 0)
    assert engine.state.actors[LEFT].current_hp == 960 + (6 if accept else 0)
    assert (USED in engine.state.actors[LEFT].turn_flags) == accept
