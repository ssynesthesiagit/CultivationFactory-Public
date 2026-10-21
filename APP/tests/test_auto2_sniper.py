"""Printed Sniper effects through accepted table intents and cold service replay."""
import pytest
from tests.auto_worker1_support import (LEFT, RIGHT, act, fight, reload, turn, resolve,
                                        action_sender, prefix_send)
from tests.test_auto27_sniper import BOW
from tests.hunt12_support import hit_dice
from combat.ext.sniper_precision import (HEAD, DEADLY, FAR, PERFECT, POSTURE,
                                         FOCUS, PERFECT_HELD, POSTURE_HELD)
from tests.test_auto27_second_pass import begin, WAIT, TRAIN

POSITIONS = {LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 6, 'y': 6}}


def labels(table, mid):
    return [g['label'] for g in table.state(mid)['menu']['actions']]


def select(table, mid, prefix):
    return next(label for label in labels(table, mid) if label.startswith(prefix))


def last_attack(engine):
    return next(e for e in reversed(engine.events) if e.event_type == 'ATTACK_ROLLED' and e.actor_id == LEFT)


def edit(*, short_range=False, disadvantage=False, hp=1000, extra=1):
    def prepare(bundle):
        actor = bundle['actor_id']
        if actor == RIGHT:
            bundle['actor_template']['maximum_hp'] = hp
            return
        for action in bundle['action_catalog']:
            typed = action['parameters'].get('typed') or {}
            if not typed.get('weapon') or not typed.get('range_ft'):
                continue
            if short_range:
                typed.update(range_ft=10, long_range_ft=60)
                action['range_ft'] = 60
            if disadvantage:
                typed['disadvantage'] = True
    return prepare


@pytest.mark.parametrize('owns,other_penalty,expected', [(False, False, 'DISADVANTAGE'),
                                                        (True, False, 'NORMAL'),
                                                        (True, True, 'DISADVANTAGE')])
def test_far_shot_removes_only_long_range(tmp_path, monkeypatch, owns, other_penalty, expected):
    hit_dice(monkeypatch)
    c,t,m = fight(tmp_path, [FAR] if owns else [], left_kit=BOW, positions=POSITIONS,
                  bundle_edit=edit(short_range=True, disadvantage=other_penalty))
    label = select(t,m,'Gong Jian')
    resolve(lambda answers: act(t,m,label,answers,target_id=RIGHT))
    e = reload(c,m)
    assert last_attack(e).payload['mode'] == expected
    assert bool(last_attack(e).payload.get('attack_mode_removed')) is owns
    assert not any('ignore only long-range' in str(v.payload) for v in e.events if v.event_type == 'GM_RIDER')


@pytest.mark.parametrize('ai', [False, True])
def test_wait_long_range_next_snipe_only(tmp_path, monkeypatch, ai):
    hit_dice(monkeypatch)
    c,t,m = fight(tmp_path, [TRAIN, DEADLY, WAIT], left_kit=BOW, positions=POSITIONS,
                  bundle_edit=edit(short_range=True))
    begin(c,t,m,ai)
    shot = select(t,m,'Snipe Shot:')
    resolve(action_sender(c,t,m,shot,ai=ai,target_id=RIGHT))
    e = reload(c,m)
    assert last_attack(e).payload['mode'] == 'NORMAL'
    assert last_attack(e).payload['attack_mode_removed'] == ['DISADVANTAGE:long_range']
    assert not any(c.condition_id == 'condition:typed.sniper_wait' for c in e.state.actors[LEFT].conditions.values())


@pytest.mark.parametrize('ai', [False, True])
def test_perfect_shot_payment_advantage_consumption_and_cold_reload(tmp_path, monkeypatch, ai):
    hit_dice(monkeypatch)
    c,t,m = fight(tmp_path,[PERFECT,TRAIN,DEADLY],left_kit=BOW,positions=POSITIONS)
    resolve(action_sender(c,t,m,'Perfect Shot',ai=ai))
    if ai:c.set_controller_mode(m,actor_id=LEFT,controller_mode='MANUAL')
    e = reload(c,m)
    assert e.state.actors[LEFT].resources[FOCUS] == 0
    assert any(c.condition_id == PERFECT_HELD for c in e.state.actors[LEFT].conditions.values())
    resolve(action_sender(c,t,m,select(t,m,'Snipe Shot:'),ai=ai,target_id=RIGHT))
    e = reload(c,m)
    assert last_attack(e).payload['mode'] == 'ADVANTAGE'
    assert not any(c.condition_id == PERFECT_HELD for c in e.state.actors[LEFT].conditions.values())
    assert not any('Aimed Line' in str(v.payload.get('rider','')) for v in e.events if v.event_type == 'GM_RIDER')


def test_perfect_shot_expires_at_end_of_same_turn(tmp_path):
    c,t,m = fight(tmp_path,[PERFECT],left_kit=BOW,positions=POSITIONS)
    resolve(lambda answers: act(t,m,'Perfect Shot',answers))
    turn(t,m,RIGHT)
    assert not any(c.condition_id == PERFECT_HELD for c in reload(c,m).state.actors[LEFT].conditions.values())


@pytest.mark.parametrize('extra,deadly', [(1,False),(3,False),(3,True)])
def test_head_weapon_and_surrendered_damage(tmp_path, monkeypatch, extra, deadly):
    hit_dice(monkeypatch)
    c,t,m = fight(tmp_path,[HEAD]+([DEADLY] if deadly else [])+(['tianxia.path.body_refining.feature.extra_attack'] if extra>1 else []),left_kit=BOW,positions=POSITIONS,left_score=30,right_score=2,
                  bundle_edit=edit(extra=extra))
    label = next(l for l in labels(t,m) if l.startswith('Head Shot:') and ('+ Deadly Shot' in l) is deadly)
    if deadly:label = next(l for l in labels(t,m) if l.startswith('Head Shot:') and '+ Deadly Shot' in l)
    resolve(lambda answers: act(t,m,label,answers,target_id=RIGHT))
    e = reload(c,m)
    own = [v for v in e.events if v.event_type == 'ATTACK_ROLLED' and v.actor_id == LEFT]
    assert len(own) == 1
    damage = [v for v in e.events if v.event_type == 'DAMAGE_ROLLED' and v.actor_id == LEFT]
    # Additional surrendered attacks are one independently rolled bonus packet.
    bonus = [v for v in damage if v.payload.get('bonus_component') == 'surrendered_attacks']
    if extra > 1:
        assert len(bonus)==1 and len(bonus[0].payload['dice'])==extra-1
    else:assert not bonus
    assert len([v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and v.actor_id==LEFT])==1
    assert not e.state.actors[LEFT].action_available
    assert not any('(rest of the Attack action)' in l for l in labels(t,m))
    base_bonus = e.action_catalog[own[0].source_definition_id].parameters['typed']['numbers']['attack_bonus']
    assert own[0].payload['total'] == own[0].payload['natural_result'] + base_bonus - (5 if deadly else 0)


@pytest.mark.parametrize('outcome', ['stunned','prone'])
def test_head_threshold_focus_save_and_one_outcome(tmp_path, monkeypatch, outcome):
    hit_dice(monkeypatch,save_roll=1)
    c,t,m = fight(tmp_path,[HEAD],left_kit=BOW,left_score=30,right_score=2,positions=POSITIONS,
                  bundle_edit=edit(hp=20))
    label=select(t,m,'Head Shot:')
    _,prompts=resolve(lambda answers: act(t,m,label,answers,target_id=RIGHT),
                     {'choice:needle.sniper.head_save':['focus'],'choice:needle.sniper.head_outcome':[outcome]})
    e=reload(c,m)
    assert any(p['context']['reaction_source_id']=='choice:needle.sniper.head_save' for p in prompts)
    assert e.state.actors[LEFT].resources[FOCUS]==0
    conditions={c.condition_id for c in e.state.actors[RIGHT].conditions.values()}
    assert ('condition:typed.stunned' in conditions) is (outcome=='stunned')
    assert ('condition:typed.prone' in conditions) is (outcome=='prone')
    assert any(v.event_type=='SAVE_ROLLED' for v in e.events)


def test_head_below_threshold_does_not_spend_focus_or_force_save(tmp_path, monkeypatch):
    hit_dice(monkeypatch)
    c,t,m=fight(tmp_path,[HEAD],left_kit=BOW,positions=POSITIONS)
    resolve(lambda answers:act(t,m,select(t,m,'Head Shot:'),answers,target_id=RIGHT))
    e=reload(c,m)
    assert e.state.actors[LEFT].resources[FOCUS]==1
    assert not any(v.event_type=='SAVE_ROLLED' for v in e.events)


@pytest.mark.parametrize('refund', [True,False])
def test_breath_held_miss_refund_or_decline(tmp_path, refund):
    breath='TAL_SNIPER_BREATH_HELD_SHOT'
    def prepare(bundle):
        if bundle['actor_id']==RIGHT:bundle['actor_template']['armor_class']=1000
    c,t,m=fight(tmp_path,[TRAIN,breath],left_kit=BOW,positions=POSITIONS,bundle_edit=prepare)
    label=next(l for l in labels(t,m) if 'Breath-Held Shot' in l and 'Martial Focus' in l)
    _,prompts=resolve(lambda answers:act(t,m,label,answers,target_id=RIGHT),
        {'choice:needle.breath_held_refund':['Keep payment'] if refund else []})
    e=reload(c,m)
    assert e.state.actors[LEFT].resources[FOCUS]==int(refund)
    assert any(c.condition_id=='condition:typed.still_aim' for c in e.state.actors[LEFT].conditions.values()) is refund
    assert any('Speed to 0' in str(p) for p in prompts)


@pytest.mark.parametrize('hit,move_first', [(False,False),(True,False),(True,True)])
def test_still_scope_qualifying_turn_and_actual_step_or_focus(tmp_path, monkeypatch, hit, move_first):
    hit_dice(monkeypatch)
    def setup(bundle):
        if bundle['actor_id']==RIGHT and not hit:bundle['actor_template']['armor_class']=1000
    c,t,m=fight(tmp_path,[TRAIN,DEADLY,POSTURE],left_kit=BOW,left_score=30,positions=POSITIONS,
        prepare=[{'type':'condition','condition':'prone','applies_to':'self'},
                 {'type':'spend_resource','resource_id':FOCUS,'flat':1,'applies_to':'self'}],bundle_edit=setup)
    resolve(lambda answers:act(t,m,'Prepare',answers))
    turn(t,m,RIGHT)
    turn(t,m,LEFT)
    e=reload(c,m)
    assert any(c.condition_id==POSTURE_HELD for c in e.state.actors[LEFT].conditions.values())
    if move_first:
        state=t.state(m);menu=state['menu']
        candidate=next(c for c in c._load_session(m).engine.legal_candidates()
                       if c.destination is not None and (c.destination.x,c.destination.y)==(3,5)
                       and c.source_definition_id=='system:combat.movement')
        assert t.act(m,candidate.candidate_id,menu['decision_id'],menu['state_version'],state['last_sequence'],[])['status']=='COMMITTED'
    label=select(t,m,'Snipe Shot:')
    _,prompts=resolve(lambda answers:act(t,m,label,answers,target_id=RIGHT),
        {'choice:needle.sniper.posture_focus':['focus'],'choice:needle.rider_step':['cell:3,5']})
    e=reload(c,m)
    if move_first:
        assert not any(p['context']['reaction_source_id'] in ('choice:needle.sniper.posture_focus','choice:needle.rider_step') for p in prompts)
    elif hit:
        assert (e.state.actors[LEFT].position.x,e.state.actors[LEFT].position.y)==(3,5)
        assert any('cannot make an Opportunity Attack' in str(p) for p in prompts)
    else:
        assert e.state.actors[LEFT].resources[FOCUS]==1
        assert any(p['context']['reaction_source_id']=='choice:needle.sniper.posture_focus' for p in prompts)


@pytest.mark.parametrize('critical,aimed', [(False,False),(True,False),(False,True)])
def test_head_bonus_dice_share_packet_and_aimed_line_changes_aperture(tmp_path,monkeypatch,critical,aimed):
    hit_dice(monkeypatch,critical=critical)
    extra='tianxia.path.body_refining.feature.extra_attack'
    aperture='TAL_SNIPER_KILLING_APERTURE'
    c,t,m=fight(tmp_path,[HEAD,extra,aperture]+([PERFECT] if aimed else []),left_kit=BOW,
                left_score=30,right_score=2,positions=POSITIONS)
    if aimed:resolve(lambda answers:act(t,m,'Perfect Shot',answers))
    resolve(lambda answers:act(t,m,select(t,m,'Head Shot:'),answers,target_id=RIGHT))
    e=reload(c,m)
    bonus=next(v for v in e.events if v.event_type=='DAMAGE_ROLLED' and v.payload.get('bonus_component')=='surrendered_attacks')
    assert bonus.payload['expression'].startswith(('4' if critical else '2') + ('d10' if aimed else 'd8'))
    assert len(bonus.payload['dice']) == (4 if critical else 2)
    assert len([v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and v.actor_id==LEFT])==1
    if aimed:assert not any(c.condition_id==PERFECT_HELD for c in e.state.actors[LEFT].conditions.values())


def test_head_declining_focus_keeps_payment_and_adds_no_save(tmp_path,monkeypatch):
    hit_dice(monkeypatch)
    c,t,m=fight(tmp_path,[HEAD],left_kit=BOW,left_score=30,right_score=2,positions=POSITIONS,
                bundle_edit=edit(hp=20))
    _,prompts=resolve(lambda answers:act(t,m,select(t,m,'Head Shot:'),answers,target_id=RIGHT),
                     {'choice:needle.sniper.head_save':[]})
    e=reload(c,m)
    assert prompts and e.state.actors[LEFT].resources[FOCUS]==1
    assert not any(v.event_type=='SAVE_ROLLED' for v in e.events)


def test_head_miss_rolls_no_surrendered_dice_and_spends_no_focus(tmp_path):
    def setup(bundle):
        if bundle['actor_id']==RIGHT:bundle['actor_template']['armor_class']=1000
    c,t,m=fight(tmp_path,[HEAD,'tianxia.path.body_refining.feature.extra_attack'],left_kit=BOW,positions=POSITIONS,bundle_edit=setup)
    resolve(lambda answers:act(t,m,select(t,m,'Head Shot:'),answers,target_id=RIGHT))
    e=reload(c,m)
    assert e.state.actors[LEFT].resources[FOCUS]==1
    assert not any(v.event_type in ('DAMAGE_ROLLED','SAVE_ROLLED') for v in e.events)


def test_deadly_changes_one_snipe_and_keeps_extra_attack_remainder(tmp_path,monkeypatch):
    hit_dice(monkeypatch)
    c,t,m=fight(tmp_path,[TRAIN,DEADLY,'tianxia.path.body_refining.feature.extra_attack'],left_kit=BOW,
                left_score=30,right_score=2,positions=POSITIONS)
    resolve(lambda answers:act(t,m,select(t,m,'Snipe Shot:'),answers,target_id=RIGHT))
    e=reload(c,m)
    assert len([v for v in e.events if v.event_type=='ATTACK_ROLLED' and v.actor_id==LEFT])==1
    first=next(v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and v.actor_id==LEFT)
    assert first.payload['hp_damage']==21  # bow 1 + Dex 10 + Deadly 10
    assert e.state.actors[LEFT].turn_flags['special_attack_rest']==2
    for remaining in (1,0):
        label=next(l for l in labels(t,m) if l.startswith('Gong Jian') and '(rest of the Attack action)' in l)
        resolve(lambda answers:act(t,m,label,answers,target_id=RIGHT))
        e=reload(c,m)
        assert e.state.actors[LEFT].turn_flags['special_attack_rest']==remaining
        last=next(v for v in reversed(e.events) if v.event_type=='DAMAGE_COMMITTED' and v.actor_id==LEFT)
        assert last.payload['hp_damage']==11
    assert len([v for v in e.events if v.event_type=='ATTACK_ROLLED' and v.actor_id==LEFT])==3
    assert not any('(rest of the Attack action)' in l for l in labels(t,m))


def test_head_stun_expires_at_end_of_shooters_next_turn(tmp_path,monkeypatch):
    hit_dice(monkeypatch,save_roll=1)
    c,t,m=fight(tmp_path,[HEAD],left_kit=BOW,left_score=30,right_score=2,positions=POSITIONS,
                bundle_edit=edit(hp=20))
    resolve(lambda answers:act(t,m,select(t,m,'Head Shot:'),answers,target_id=RIGHT),
            {'choice:needle.sniper.head_save':['focus'],'choice:needle.sniper.head_outcome':['stunned']})
    turn(t,m,RIGHT)
    turn(t,m,LEFT)
    assert any(c.condition_id=='condition:typed.stunned' for c in reload(c,m).state.actors[RIGHT].conditions.values())
    turn(t,m,RIGHT)
    assert not any(c.condition_id=='condition:typed.stunned' for c in reload(c,m).state.actors[RIGHT].conditions.values())


def test_still_scope_does_not_offer_benefit_without_starting_posture(tmp_path,monkeypatch):
    hit_dice(monkeypatch)
    c,t,m=fight(tmp_path,[POSTURE,TRAIN,DEADLY],left_kit=BOW,left_score=30,right_score=2,positions=POSITIONS)
    assert not any(c.condition_id==POSTURE_HELD for c in reload(c,m).state.actors[LEFT].conditions.values())
    _,prompts=resolve(lambda answers:act(t,m,select(t,m,'Snipe Shot:'),answers,target_id=RIGHT))
    assert not any(p['context']['reaction_source_id']=='choice:needle.rider_step' for p in prompts)
    assert (reload(c,m).state.actors[LEFT].position.x,reload(c,m).state.actors[LEFT].position.y)==(3,6)
