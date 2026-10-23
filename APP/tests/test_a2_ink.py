"""Ink second pass through committed table actions, sessions and cold replay."""
import copy
import pytest
from combat import typed_executor as te
from combat.canonical import canonical_sha256
from combat.gate2_runtime_models import ActionIntent
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r1i_service_support import fixture, candidate, OWNER, FOE, SECOND, THIRD
from tests.test_r1i_round3 import resolve, reload
from tests.test_auto138_ink import owner_turn
INK='tianxia.talent.ink.'
MASTER='insight.master-calligrapher'
GUARD='insight.brush-armed-guard'
CORRECTION=INK+'vermilion_correction'
SHIELD=INK+'brushstroke_shield'


def setup(bundles):
    """Test-only costless setup/checks; tested compiled rows stay untouched."""
    for bundle in bundles:
        actions=bundle['action_catalog']
        template=next((a for a in actions if a['display_name']=='Ink Lash'),None)
        if template:
            attack=copy.deepcopy(template)
            attack.update(source_definition_id=bundle['actor_id']+'.test.small_hit',display_name='Small hit',economy='NONE')
            attack['parameters']['typed']['effects']=[{'type':'attack','attack_kind':'cultivation_ranged',
                'on_hit':[{'type':'damage','flat':1,'dice':{'count':0,'sides':0},'damage_types':['force']}],'on_miss':[]}]
            check=copy.deepcopy(template)
            check.update(source_definition_id=bundle['actor_id']+'.test.check',display_name='Test ability check',economy='NONE')
            check['parameters']['typed']['effects']=[{'type':'contest_against',
                'actor_check':{'kind':'check','ability':'STR'},'target_check':{'kind':'dc','dc':15},'on_success':[],'on_fail':[]}]
            short=copy.deepcopy(template)
            short.update(source_definition_id=bundle['actor_id']+'.test.short_mark',display_name='Short mark',economy='NONE')
            short['parameters']['typed']['effects']=[{'type':'mark','mark':'ink_mark','applies_to':'target',
                'duration':{'kind':'minutes','amount':1}}]
            long=copy.deepcopy(short)
            long.update(source_definition_id=bundle['actor_id']+'.test.long_mark',display_name='Long mark')
            long['parameters']['typed']['effects'][0]['duration']={'kind':'hours','amount':24}
            contest=copy.deepcopy(check)
            contest.update(source_definition_id=bundle['actor_id']+'.test.contest',display_name='Test opposed checks')
            contest['parameters']['typed']['effects'][0]['target_check']={'kind':'check','ability':'STR'}
            for action in (attack,check,short,long,contest):
                actions.append(action);bundle['actor_template']['action_ids'].append(action['source_definition_id'])
        for action in actions:
            if action['display_name']=='Press Mark':action['economy']='NONE'
        bundle['actor_template']['saving_throws']['DEX']=-100
        bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)


def execute_session(tmp_path,mid,label,target):
    session=CombatService(ROOT,tmp_path)._load_session(mid)
    c=next(c for c in session.engine.legal_candidates() if c.display_name==label and target in c.target_ids)
    session.mechanical.execute_intent(ActionIntent(intent_id=f'a2ink-{session.engine.state.event_sequence}',
        actor_id=c.actor_id,decision_id=c.decision_id,candidate_id=c.candidate_id,state_version=c.state_version,target_ids=c.target_ids))
    return reload(tmp_path,mid)


@pytest.mark.parametrize('master',[False,True])
def test_master_cap_lifetime_oldest_replacement_and_reload(tmp_path,master):
    combat,table,mid,send,commit=fixture(tmp_path,[MASTER] if master else ['INK_BASE_PRESS_MARK'],
        owner_pb=1,extra_foe=True,allies=[SECOND],bundle_transform=setup,
        positions={OWNER:{'x':3,'y':6},FOE:{'x':4,'y':6},SECOND:{'x':3,'y':7},THIRD:{'x':2,'y':6}})
    for target in (FOE,SECOND,THIRD,OWNER):
        resolve(combat,mid,send,candidate(table,mid,'Press Mark',target),{'choice:needle.ink_accept':'accept'})
    engine=reload(tmp_path,mid)
    held=[a for a in engine.state.actors.values() if te.bears_mark(a,OWNER,'ink_mark')]
    assert len(held)==(4 if master else 3)
    assert te.bears_mark(engine.state.actors[FOE],OWNER,'ink_mark')==master
    for actor in held:
        mark=next(c for c in actor.conditions.values() if c.condition_id==te.mark_condition_id('ink_mark',OWNER))
        assert mark.expires_on.startswith('START_OF_SLOT_AT:')
        assert int(mark.expires_on.split(':')[1])-engine.state.round_number==(4800 if master else 600)
    execute_session(tmp_path,mid,'Small hit',FOE)


@pytest.mark.parametrize('protected',[OWNER,SECOND])
@pytest.mark.parametrize('ai',[False,True])
@pytest.mark.parametrize('master',[False,True])
def test_guard_zero_shield_marks_attacker_only_and_replays(tmp_path,protected,ai,master):
    combat,table,mid,send,commit=fixture(tmp_path,[SHIELD,GUARD]+([MASTER] if master else []),foe_talents=[INK+'binding_script'],
        allies=[SECOND],extra_foe=True,bundle_transform=setup,
        positions={OWNER:{'x':3,'y':0},FOE:{'x':4,'y':0},SECOND:{'x':3,'y':1},THIRD:{'x':5,'y':1}})
    commit(table.state(mid)['menu']['end_turn']);owner_turn(table,mid,commit,FOE)
    if ai:combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    before=reload(tmp_path,mid).state.model_dump(mode='json')
    cid=candidate(table,mid,'Small hit',protected);answers=[];prompts=[]
    for _ in range(16):
        result=send(cid,answers)
        if result['status']=='COMMITTED':break
        p=result['reaction'];prompts.append(p);answer={**p['context'],'selection':'DECLINE'}
        src=p['context']['reaction_source_id']
        if src=='reaction:typed.'+SHIELD:answer['selection']='USE'
        elif src=='choice:needle.ink_guard':answer.update(selection='USE',option_ids=['mark'])
        answers.append(answer)
    assert result['status']=='COMMITTED'
    engine=reload(tmp_path,mid)
    assert any(e.event_type=='REACTION_RESOLVED' and e.source_definition_id==SHIELD for e in engine.events)
    assert engine.state.actors[protected].current_hp==before['actors'][protected]['current_hp']
    assert te.bears_mark(engine.state.actors[FOE],OWNER,'ink_mark')
    assert not te.bears_mark(engine.state.actors[SECOND],OWNER,'ink_mark')
    assert not te.bears_mark(engine.state.actors[THIRD],OWNER,'ink_mark')
    assert not engine.state.actors[OWNER].reaction_available
    assert sum(before['actors'][OWNER]['resources'].values())-sum(engine.state.actors[OWNER].resources.values())==1
    assert bool([p for p in prompts if p['context']['reaction_source_id']=='choice:needle.ink_guard'])==(not ai)
    if not ai:
        guard_prompt=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.ink_guard')
        for phrase in ('Small hit', 'Ink Mark', 'Ink abilities', '8 hours' if master else '1 hour'):
            assert phrase in str(guard_prompt)
        assert guard_prompt['action']=='Small hit'
        assert guard_prompt['affected']=='Foe'
    execute_session(tmp_path,mid,'Small hit',SECOND if protected==OWNER else OWNER)


@pytest.mark.parametrize('accept',[False,True])
def test_ai_guard_recipient_consent_names_triggering_attack_and_replays(tmp_path,accept):
    from combat.canonical import canonical_sha256

    def ask_foe(bundles):
        target=next(b for b in bundles if b['actor_id']==FOE)
        target['reaction_plan']={**target['reaction_plan'],'ask':True,'mode':'ask'}
        target['actor_template']['saving_throws']['DEX']=100
        target.pop('bundle_sha256',None);target['bundle_sha256']=canonical_sha256(target)

    combat,table,mid,send,commit=fixture(tmp_path,[SHIELD,GUARD],foe_talents=[INK+'binding_script'],extra_foe=True,
        bundle_transform=lambda bundles:(setup(bundles),ask_foe(bundles)),
        positions={OWNER:{'x':3,'y':0},FOE:{'x':4,'y':0}})
    commit(table.state(mid)['menu']['end_turn']);owner_turn(table,mid,commit,FOE)
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    before=reload(tmp_path,mid).state.model_dump(mode='json')
    cid=candidate(table,mid,'Small hit',OWNER)
    _,prompts=resolve(combat,mid,send,cid,{'choice:needle.ink_accept':'accept' if accept else None})
    consent=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.ink_accept')
    assert consent['context']['reactor_id']==FOE
    assert consent['action']=='Small hit'
    assert consent['affected']=='Foe'
    for phrase in ('Brush-Armed Guard','Small hit','Foe','Ink abilities','1 hour'):
        assert phrase in str(consent)
    engine=reload(tmp_path,mid)
    assert te.bears_mark(engine.state.actors[FOE],OWNER,'ink_mark')==accept
    assert bool([e for e in engine.events if e.event_type=='SAVE_ROLLED'])==(not accept)
    if accept:
        mark=next(c for c in engine.state.actors[FOE].conditions.values()
                  if c.condition_id==te.mark_condition_id('ink_mark',OWNER))
        assert int(mark.expires_on.split(':')[1])-engine.state.round_number==600
    assert engine.state.actors[OWNER].current_hp==before['actors'][OWNER]['current_hp']
    execute_session(tmp_path,mid,'Small hit', OWNER if engine.state.current_actor_id==FOE else FOE)


@pytest.mark.parametrize('sign',['add','subtract',None])
def test_correction_signed_d4_decline_and_recipient_limit(tmp_path,sign):
    combat,table,mid,send,commit=fixture(tmp_path,[CORRECTION],bundle_transform=setup)
    resolve(combat,mid,send,candidate(table,mid,'Press Mark',OWNER),{})
    before,prompts=resolve(combat,mid,send,candidate(table,mid,'Test ability check',FOE),{'choice:needle.ink_correction':sign})
    correction_prompt=next((p for p in prompts if p['context']['reaction_source_id']=='choice:needle.ink_correction'),None)
    if sign is not None:
        assert correction_prompt is not None
        assert 'Test ability check' in str(correction_prompt)
        assert 'Owner' in str(correction_prompt)
        assert correction_prompt['action']=='Test ability check'
        assert correction_prompt['affected']=='Owner'
    engine=reload(tmp_path,mid)
    corrections=[e for e in engine.events if e.event_type=='D20_REWRITTEN' and e.source_definition_id==CORRECTION]
    assert len(corrections)==int(sign is not None)
    if sign:
        bonus=corrections[0].payload['bonus']
        assert 1<=abs(bonus)<=4 and (bonus>0)==(sign=='add')
        assert corrections[0].sequence<next(e.sequence for e in engine.events if e.event_type=='CHECK_ROLLED')
        assert engine.state.actors[OWNER].turn_flags['_round_ink_correction']==engine.state.round_number
    assert sum(before['actors'][OWNER]['resources'].values())-sum(engine.state.actors[OWNER].resources.values())==int(sign is not None)
    assert engine.state.actors[OWNER].reaction_available==(sign is None)
    if sign is None:
        resolve(combat,mid,send,candidate(table,mid,'Test ability check',FOE),{})
    else:
        execute_session(tmp_path,mid,'Test ability check',FOE)
    engine=reload(tmp_path,mid)
    assert len([e for e in engine.events if e.event_type=='D20_REWRITTEN' and e.source_definition_id==CORRECTION])==int(sign is not None)


def test_correction_resolves_suffixed_check_source_to_readable_action(tmp_path,monkeypatch):
    """Service prompt follows the production CHECK:<action>:<skill> contract."""
    from combat.gate2_engine import Gate2Engine
    original=Gate2Engine.d20_context
    def suffixed_context(engine,roll=None):
        context=original(engine,roll)
        if context and context.get('kind')=='check' and context.get('source_id','').endswith('.test.check'):
            context={**context,'source_id':context['source_id']+':Medicine'}
        return context
    monkeypatch.setattr(Gate2Engine,'d20_context',suffixed_context)
    combat,table,mid,send,commit=fixture(tmp_path,[CORRECTION],bundle_transform=setup)
    resolve(combat,mid,send,candidate(table,mid,'Press Mark',OWNER),{})
    _,prompts=resolve(combat,mid,send,candidate(table,mid,'Test ability check',FOE),
                      {'choice:needle.ink_correction':'subtract'})
    prompt=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.ink_correction')
    assert prompt['action']=='Test ability check'
    assert 'Test ability check' in str(prompt)
    assert '.test.check:Medicine' not in str(prompt)
    engine=reload(tmp_path,mid)
    assert any(e.event_type=='D20_REWRITTEN' and e.source_definition_id==CORRECTION for e in engine.events)
    session=CombatService(ROOT,tmp_path)._load_session(mid)
    assert session.verify()['status']==session.mechanical.replay()['status']=='PASS'


def test_correction_reaction_is_reserved_before_resource_payment(tmp_path,monkeypatch):
    from combat.ext.choice_costs import Payment
    original=Payment.pay
    availability=[]
    def inspect_reserved(payment,engine,actor,source):
        if source==CORRECTION:availability.append(actor.reaction_available)
        return original(payment,engine,actor,source)
    monkeypatch.setattr(Payment,'pay',inspect_reserved)
    combat,table,mid,send,commit=fixture(tmp_path,[CORRECTION],bundle_transform=setup)
    resolve(combat,mid,send,candidate(table,mid,'Press Mark',OWNER),{})
    _,prompts=resolve(combat,mid,send,candidate(table,mid,'Test ability check',FOE),
                      {'choice:needle.ink_correction':'subtract'})
    assert any(p['context']['reaction_source_id']=='choice:needle.ink_correction' for p in prompts)
    assert availability and all(value is False for value in availability)
    session=CombatService(ROOT,tmp_path)._load_session(mid)
    assert session.verify()['status']==session.mechanical.replay()['status']=='PASS'


def test_correction_payment_interruption_keeps_cost_but_skips_bonus(tmp_path,monkeypatch):
    from combat.ext.choice_costs import Payment
    original=Payment.pay
    def interrupt_after_payment(payment,engine,actor,source):
        original(payment,engine,actor,source)
        if source==CORRECTION:
            engine._apply_condition(actor,'condition:typed.incapacitated',CORRECTION,actor.entity_id,
                                    expires_on='END_OF_TURN')
    monkeypatch.setattr(Payment,'pay',interrupt_after_payment)
    combat,table,mid,send,commit=fixture(tmp_path,[CORRECTION],bundle_transform=setup)
    resolve(combat,mid,send,candidate(table,mid,'Press Mark',OWNER),{})
    before=reload(tmp_path,mid).state.actors[OWNER].resources.copy()
    resolve(combat,mid,send,candidate(table,mid,'Test ability check',FOE),
            {'choice:needle.ink_correction':'subtract'})
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources!=before
    assert not engine.state.actors[OWNER].reaction_available
    assert not any(e.event_type=='D20_REWRITTEN' and e.source_definition_id==CORRECTION for e in engine.events)
    session=CombatService(ROOT,tmp_path)._load_session(mid)
    assert session.verify()['status']==session.mechanical.replay()['status']=='PASS'


def test_correction_black_sun_payment_reserves_defensive_reaction_first(tmp_path):
    from combat.ext.daemonic_riders import BLACK_SUN_STATE
    from tests.test_riders_lane1 import BLACK_SUN
    def failed_save(bundles):
        setup(bundles)
        owner_bundle=next(b for b in bundles if b['actor_id']==OWNER)
        foe_bundle=next(b for b in bundles if b['actor_id']==FOE)
        check=copy.deepcopy(next(a for a in owner_bundle['action_catalog']
                                 if a['display_name']=='Test ability check'))
        check['source_definition_id']=FOE+'.test.check'
        foe_bundle['action_catalog'].append(check)
        foe_bundle['actor_template']['action_ids'].append(check['source_definition_id'])
        for bundle in bundles:
            if bundle['actor_id']==OWNER:
                bundle['actor_template']['saving_throws']['WIS']=-100
            bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)
    combat,table,mid,send,commit=fixture(tmp_path,[CORRECTION,SHIELD],foe_talents=[BLACK_SUN],
        bundle_transform=failed_save)
    resolve(combat,mid,send,candidate(table,mid,'Press Mark',OWNER),{})
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=FOE:
        commit(table.state(mid)['menu']['end_turn'])
    commit(candidate(table,mid,'Black Sun Over the Dantian',OWNER))
    engine=reload(tmp_path,mid)
    assert any(c.condition_id==BLACK_SUN_STATE for c in engine.state.actors[OWNER].conditions.values())
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=OWNER:
        commit(table.state(mid)['menu']['end_turn'])
    cid=candidate(table,mid,'Test ability check',FOE)
    answers=[];prompts=[]
    for _ in range(16):
        result=send(cid,answers)
        if result['status']=='COMMITTED':break
        assert result['status']=='REACTION_REQUIRED',result
        prompt=result['reaction'];prompts.append(prompt)
        source=prompt['context']['reaction_source_id']
        answer={**prompt['context'],'selection':'DECLINE'}
        if source=='choice:needle.ink_correction':answer.update(selection='USE',option_ids=['subtract'])
        elif source=='reaction:typed.'+SHIELD:answer['selection']='USE'
        answers.append(answer)
    assert result['status']=='COMMITTED'
    engine=reload(tmp_path,mid)
    assert not any(p['context']['reaction_source_id']=='reaction:typed.'+SHIELD for p in prompts)
    black_sun_packets=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED'
                       and BLACK_SUN in e.source_definition_id and OWNER in (e.target_ids or ())]
    assert len(black_sun_packets)>=1
    correction_window=next(e for e in engine.events if e.event_type=='REACTION_WINDOW_OPENED'
                           and e.source_definition_id==CORRECTION and e.actor_id==OWNER)
    assert correction_window.sequence<black_sun_packets[-1].sequence
    assert not engine.state.actors[OWNER].reaction_available
    assert any(e.event_type=='D20_REWRITTEN' and e.source_definition_id==CORRECTION for e in engine.events)
    assert not any(e.event_type=='REACTION_RESOLVED' and e.source_definition_id==SHIELD for e in engine.events)
    session=CombatService(ROOT,tmp_path)._load_session(mid)
    assert session.verify()['status']==session.mechanical.replay()['status']=='PASS'


@pytest.mark.parametrize('ally',[False,True])
def test_ai_correction_helps_allies_hinders_enemies_with_both_in_range(tmp_path,ally):
    combat,table,mid,send,commit=fixture(tmp_path,[CORRECTION],foe_talents=[INK+'binding_script'],
        allies=[SECOND]+([FOE] if ally else []),extra_foe=True,bundle_transform=setup)
    resolve(combat,mid,send,candidate(table,mid,'Press Mark',FOE),{'choice:needle.ink_accept':'accept'})
    commit(table.state(mid)['menu']['end_turn']);owner_turn(table,mid,commit,FOE)
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    engine=execute_session(tmp_path,mid,'Test ability check',SECOND if not ally else THIRD)
    corrections=[e for e in engine.events if e.event_type=='D20_REWRITTEN' and e.source_definition_id==CORRECTION]
    assert len(corrections)==1
    assert (corrections[0].payload['bonus']>0)==ally
    assert engine.state.actors[FOE].turn_flags['_round_ink_correction']==engine.state.round_number
    assert '_round_ink_correction' not in engine.state.actors[SECOND].turn_flags


@pytest.mark.parametrize('label,rounds',[('Short mark',10),('Long mark',14400)])
def test_master_preserves_shorter_and_longer_marks(tmp_path,label,rounds):
    combat,table,mid,send,commit=fixture(tmp_path,[MASTER],bundle_transform=setup)
    engine=execute_session(tmp_path,mid,label,FOE)
    mark=next(c for c in engine.state.actors[FOE].conditions.values()
              if c.condition_id==te.mark_condition_id('ink_mark',OWNER))
    assert int(mark.expires_on.split(':')[1])-engine.state.round_number==rounds


@pytest.mark.parametrize('case',['decline','nonzero','absent','save'])
def test_guard_only_after_zero_with_insight_consent_and_failed_save(tmp_path,case):
    def prepare(bundles):
        setup(bundles)
        for bundle in bundles:
            if bundle['actor_id']==FOE:
                if case=='save':bundle['actor_template']['saving_throws']['DEX']=100
                if case=='nonzero':
                    next(a for a in bundle['action_catalog'] if a['display_name']=='Small hit')['parameters']['typed']['effects'][0]['on_hit'][0]['flat']=100
                bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)
    combat,table,mid,send,commit=fixture(tmp_path,[SHIELD]+([] if case=='absent' else [GUARD]),
        foe_talents=[INK+'binding_script'],allies=[SECOND],bundle_transform=prepare)
    commit(table.state(mid)['menu']['end_turn']);owner_turn(table,mid,commit,FOE)
    cid=candidate(table,mid,'Small hit',SECOND);answers=[];guard_prompts=[]
    for _ in range(16):
        result=send(cid,answers)
        if result['status']=='COMMITTED':break
        p=result['reaction'];src=p['context']['reaction_source_id'];answer={**p['context'],'selection':'DECLINE'}
        if src=='reaction:typed.'+SHIELD:answer['selection']='USE'
        if src=='choice:needle.ink_guard':
            guard_prompts.append(p)
            if case!='decline':answer.update(selection='USE',option_ids=['mark'])
        answers.append(answer)
    assert result['status']=='COMMITTED'
    engine=reload(tmp_path,mid)
    assert not te.bears_mark(engine.state.actors[FOE],OWNER,'ink_mark')
    assert bool(guard_prompts)==(case in ('decline','save'))
    assert (engine.state.actors[SECOND].current_hp<500)==(case=='nonzero')
    assert not engine.state.actors[OWNER].reaction_available
    execute_session(tmp_path,mid,'Small hit',OWNER)


def test_correction_recipient_limit_is_shared_across_writers(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,[CORRECTION],foe_talents=[INK+'binding_script'],
        second_talents=[CORRECTION],allies=[SECOND],bundle_transform=setup,
        positions={OWNER:{'x':3,'y':6},FOE:{'x':4,'y':6},SECOND:{'x':4,'y':7}})
    resolve(combat,mid,send,candidate(table,mid,'Press Mark',FOE),{})
    commit(table.state(mid)['menu']['end_turn']);owner_turn(table,mid,commit,FOE)
    resolve(combat,mid,send,candidate(table,mid,'Test ability check',OWNER),{'choice:needle.ink_correction':'subtract'})
    commit(table.state(mid)['menu']['end_turn']);owner_turn(table,mid,commit,SECOND)
    resolve(combat,mid,send,candidate(table,mid,'Press Mark',FOE),{})
    before=reload(tmp_path,mid).state.model_dump(mode='json')
    engine=execute_session(tmp_path,mid,'Test opposed checks',FOE)
    assert len([e for e in engine.events if e.event_type=='D20_REWRITTEN' and e.source_definition_id==CORRECTION])==1
    assert engine.state.actors[SECOND].reaction_available
    assert engine.state.actors[SECOND].resources==before['actors'][SECOND]['resources']
