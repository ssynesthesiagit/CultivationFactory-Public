"""Blood Reversal through service session intents, table rollback and cold replay."""
import pytest
from combat.ext.blood_reversal import FEATURE, USED, CHOICE
from tests.auto_worker1_support import fight as service_fight, LEFT, RIGHT, ALLY, act, resolve, turn, reload
from tests.hunt15_support import action_sender

THREAD = 'BLOOD_BASE_BLOOD_THREAD'
SPHERE = 'tianxia.sphere.blood'
QI = 'resource:core.qi'


def fight(tmp_path, *, owns=True, balance=100, **kwargs):
    def fields(doc, aid):
        st = doc['spheres_and_talents']
        st['cultivation_insight_record_ids'] = [FEATURE] if aid == LEFT and owns else []
        if aid == LEFT:
            doc['ability_scores_and_statistics']['primary_resource']['maximum'] = balance
    def seal(bundle):
        if bundle['actor_id'] == LEFT:
            for action in bundle['action_catalog']:
                if action['display_name'] == 'Prepare':
                    action['parameters']['typed'].update(source=THREAD, sphere=SPHERE)
    return service_fight(tmp_path, [THREAD], spheres=[SPHERE], sheet_edit=fields,
                         bundle_edit=seal, left_attack_bonus=100,
                         cause=[{'type':'damage', 'flat':40, 'damage_types':['force']}],
                         cause_target='ANY_CREATURE', ally=[], **kwargs)


def wound(combat, table, mid, who=LEFT):
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=who))
    turn(table, mid, LEFT)


def heals(engine):
    return [e for e in engine.events if e.event_type == 'HEALING_APPLIED']


@pytest.mark.parametrize('recipient', [LEFT, ALLY, RIGHT])
def test_printed_creature_choice_and_exact_payment(tmp_path, recipient):
    combat, table, mid = fight(tmp_path)
    wound(combat, table, mid, recipient)
    before = reload(combat, mid)
    hp = before.state.actors[recipient].current_hp
    cp = before.state.actors[LEFT].resources[QI]
    _, prompts = resolve(lambda a: act(table, mid, 'Blood Thread', a, target_id=RIGHT), {CHOICE:[recipient]})
    engine = reload(combat, mid)
    passive = next(r for r in engine.typed_passive_rows[LEFT] if r.get('feature_id') == FEATURE)
    amount = passive['pb'] + passive['key_mod']
    assert engine.state.actors[LEFT].resources[QI] == cp - 2
    healing = heals(engine)[-1]
    assert healing.target_ids == (recipient,)
    assert healing.payload['after'] - healing.payload['before'] == amount
    if recipient != RIGHT:
        assert engine.state.actors[recipient].current_hp == hp + amount
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == CHOICE)
    assert '30 feet' in str(prompt) and 'once per turn' in str(prompt)
    assert engine.state.actors[LEFT].turn_flags[USED]


def test_decline_keeps_payment_and_allowance(tmp_path):
    combat, table, mid = fight(tmp_path)
    wound(combat, table, mid)
    cp = reload(combat, mid).state.actors[LEFT].resources[QI]
    resolve(lambda a: act(table, mid, 'Blood Thread', a, target_id=RIGHT), {CHOICE:[]})
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources[QI] == cp
    assert USED not in engine.state.actors[LEFT].turn_flags
    assert not heals(engine)


@pytest.mark.parametrize('owns,blood,zero', [(False,True,False),(True,False,False),(True,True,True)])
def test_nonqualifying_damage_does_not_offer_reversal(tmp_path, owns, blood, zero):
    def fields(doc, aid):
        doc['spheres_and_talents']['cultivation_insight_record_ids'] = [FEATURE] if aid == LEFT and owns else []
    def seal(bundle):
        for action in bundle['action_catalog']:
            if action['display_name'] == 'Prepare' and blood:
                action['parameters']['typed'].update(source=THREAD,sphere=SPHERE)
    combat, table, mid = service_fight(tmp_path, [THREAD], spheres=[SPHERE],
        sheet_edit=fields, bundle_edit=seal,
        prepare=[{'type':'damage','flat':0 if zero else 20,'damage_types':['necrotic']}])
    _, prompts = resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT))
    engine = reload(combat, mid)
    assert not any(p['context']['reaction_source_id'] == CHOICE for p in prompts)
    assert USED not in engine.state.actors[LEFT].turn_flags


def test_once_per_turn_and_next_turn_reset(tmp_path):
    combat, table, mid = fight(tmp_path, prepare=[{'type':'damage','flat':20,'damage_types':['necrotic']}])
    wound(combat, table, mid)
    for _ in range(2):
        resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT), {CHOICE:[LEFT]})
    engine = reload(combat, mid)
    assert len(heals(engine)) == 1
    assert engine.state.actors[LEFT].resources[QI] == 98
    turn(table, mid, RIGHT); turn(table, mid, LEFT)
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT), {CHOICE:[LEFT]})
    engine = reload(combat, mid)
    assert len(heals(engine)) == 2
    assert engine.state.actors[LEFT].resources[QI] == 96


def test_ai_heals_allied_recipient_with_allies_and_enemies_in_range(tmp_path):
    combat, table, mid = fight(tmp_path)
    wound(combat, table, mid, ALLY)
    before = reload(combat, mid)
    enemy_hp = before.state.actors[RIGHT].current_hp
    sender = action_sender(combat, table, mid, 'Blood Thread', ai=True, target_id=RIGHT)
    _, prompts = resolve(sender)
    engine = reload(combat, mid)
    assert not any(p['context']['reaction_source_id'] == CHOICE for p in prompts)
    assert engine.state.actors[ALLY].current_hp == 966
    assert engine.state.actors[RIGHT].current_hp < enemy_hp
    assert heals(engine)[-1].target_ids == (ALLY,)
    assert engine.state.actors[LEFT].resources[QI] == 98


def test_insufficient_cp_leaves_trigger_unspent(tmp_path):
    combat, table, mid = fight(tmp_path,balance=1)
    _, prompts = resolve(lambda a:act(table,mid,'Blood Thread',a,target_id=RIGHT))
    engine=reload(combat,mid)
    assert not any(p['context']['reaction_source_id']==CHOICE for p in prompts)
    assert engine.state.actors[LEFT].resources[QI]==1
    assert USED not in engine.state.actors[LEFT].turn_flags


def test_manual_options_exclude_out_of_range_ally(tmp_path):
    combat,table,mid=fight(tmp_path,positions={LEFT:{'x':3,'y':6},RIGHT:{'x':4,'y':6},ALLY:{'x':10,'y':5}})
    _,prompts=resolve(lambda a:act(table,mid,'Blood Thread',a,target_id=RIGHT),{CHOICE:[]})
    prompt=next(p for p in prompts if p['context']['reaction_source_id']==CHOICE)
    assert ALLY not in [o['id'] for o in prompt['choice']['options']]
    reload(combat,mid)
