"""Printed Imbuement benefits through table transactions, cold reload and replay."""
import pytest
from combat.gate5_service import CombatService
from combat.ext import imbuement_mandates as M, persist_augment as P
from tests import r1i_service_support as S
from tests.h1_support import ROOT
IMB='tianxia.talent.imbuement.'
QI='resource:core.qi'

def fixture(monkeypatch,tmp_path,insights=(),talents=(),cl=17,extra=False,foe_talents=(),third_ally=True,foe_score=14,bundle_transform=None):
    real=S.sheet
    def sheet(*args,**kwargs):
        doc=real(*args,**{**kwargs,'cl':cl})
        if args[0] and IMB+'quicken_and_slow' in args[0]:
            doc['spheres_and_talents']['cultivation_insight_record_ids']=list(insights)
        return doc
    monkeypatch.setattr(S,'sheet',sheet)
    result = S.fixture(tmp_path,[IMB+'quicken_and_slow',IMB+'physique_and_weakness',*[IMB+t for t in talents]],allies=[S.SECOND,S.THIRD] if extra and third_ally else [S.SECOND],extra_foe=extra,wide=True,foe_talents=[IMB+t for t in foe_talents],foe_score=foe_score,bundle_transform=bundle_transform)
    combat, table, mid, send, _ = result
    def commit(cid):
        answers=[]
        for _ in range(16):
            response=send(cid,answers)
            if response['status']=='COMMITTED':return response
            assert response['status']=='REACTION_REQUIRED',response
            p=response['reaction']; answer={**p['context'],'selection':'DECLINE'}
            if p.get('choice'):
                n=p['choice'].get('maximum',1) if p['context']['reaction_source_id']=='choice:needle.mass_mandate' else p['choice'].get('minimum',1)
                answer.update(selection='USE',option_ids=[o['id'] for o in p['choice']['options']][:n])
            answers.append(answer)
        raise AssertionError('too many prompts')
    return combat,table,mid,send,commit

def cold(tmp_path,mid):
    s=CombatService(ROOT,tmp_path)._load_session(mid)
    assert s.mechanical.replay()['status']=='PASS'
    return s.engine

def turn(table,mid,commit):
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=S.OWNER:
        commit(table.state(mid)['menu']['end_turn'])

def cast(table,mid,commit,label,target=S.SECOND):
    commit(S.candidate(table,mid,label,target))

@pytest.mark.parametrize('owns',[False,True])
def test_dual_adept_cost_and_load(monkeypatch,tmp_path,owns):
    combat,table,mid,send,commit=fixture(monkeypatch,tmp_path,['insight.dual-mandate-adept'] if owns else [],['layered_mandate'])
    before=cold(tmp_path,mid).state.actors[S.OWNER].resources[QI]
    cast(table,mid,commit,f'Place Mandate: Layered Mandate ({0 if owns else 1} CP)')
    engine=cold(tmp_path,mid);actor=engine.state.actors[S.OWNER]
    assert actor.resources[QI]==before-(0 if owns else 1)
    assert M.load(engine,actor,4)==(3 if owns else 2)
    assert engine.state.actors[S.SECOND].modifiers
    commit(S.candidate(table,mid,'Set Mandate:'))
    for _ in range(2):
        turn(table,mid,commit);cast(table,mid,commit,'Place Mandate: Quicken')
        commit(S.candidate(table,mid,'Set Mandate:'))
    engine=cold(tmp_path,mid)
    assert len(P.persisted(engine,engine.state.actors[S.OWNER],P.MANDATE))==(3 if owns else 2)

@pytest.mark.parametrize('cl,discounts',[(6,1),(11,2)])
def test_efficient_mandate_discount_limits(monkeypatch,tmp_path,cl,discounts):
    combat,table,mid,send,commit=fixture(monkeypatch,tmp_path,['insight.efficient-mandate'],['layered_mandate'],cl)
    for i in range(3):
        if i:turn(table,mid,commit)
        cast(table,mid,commit,'Place Mandate: Quicken')
        before=cold(tmp_path,mid).state.actors[S.OWNER].resources[QI]
        commit(S.candidate(table,mid,'Set Mandate:'))
        engine=cold(tmp_path,mid);actor=engine.state.actors[S.OWNER]
        assert actor.resources[QI]==before-(1 if i<discounts else 2)
        marker=next(c for c in actor.conditions.values() if c.condition_id==M.SET_DISCOUNT)
        assert marker.data['used']==min(i+1,discounts)
        assert actor.concentration is None

@pytest.mark.parametrize('sovereign,cp,rounds',[(False,2,10),(True,3,100)])
def test_realm_set_duration_and_detachment(monkeypatch,tmp_path,sovereign,cp,rounds):
    combat,table,mid,send,commit=fixture(monkeypatch,tmp_path,talents=['qi_written_mandate']+(['sovereign_of_the_true_name_of_things'] if sovereign else []))
    cast(table,mid,commit,'Place Mandate: Quicken')
    before=cold(tmp_path,mid).state.actors[S.OWNER].resources[QI]
    commit(S.candidate(table,mid,f'Set Mandate: {10 if sovereign else 1} minute'))
    engine=cold(tmp_path,mid);actor=engine.state.actors[S.OWNER]
    assert actor.resources[QI]==before-cp
    assert actor.concentration is None
    record=P.persisted(engine,actor,P.MANDATE)[0][1]
    from combat.ext.effect_durations import round_token
    assert record.expires_on==round_token(engine,rounds)
    assert all(m.expires_on==record.expires_on for m in engine.state.actors[S.SECOND].modifiers.values())


@pytest.mark.parametrize('side',['Place','Fray'])
def test_mass_same_option_recipients_and_load(monkeypatch,tmp_path,side):
    combat,table,mid,send,commit=fixture(monkeypatch,tmp_path,talents=['mass_mandate','layered_mandate'],extra=True,third_ally=side=='Place')
    target=S.SECOND if side=='Place' else S.FOE
    label='Quicken' if side=='Place' else 'Slow ('
    before=cold(tmp_path,mid).state.actors[S.OWNER].resources[QI]
    cast(table,mid,commit,'Mass '+side+' Mandate: '+label,target)
    engine=cold(tmp_path,mid)
    assert engine.state.actors[S.OWNER].resources[QI]==before-2
    recipients=[S.OWNER,S.SECOND,S.THIRD] if side=='Place' else [S.FOE,S.THIRD]
    for aid in recipients:
        assert any('mandate.' in m.source_definition_id for m in engine.state.actors[aid].modifiers.values())
    if side=='Fray':
        assert len([e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id in recipients])==2
    marker=next(c for c in engine.state.actors[S.OWNER].conditions.values() if c.condition_id==M.MASS_LOAD)
    assert marker.data['weight']==(2 if side=='Place' else 1)
    if side=='Place':
        commit(S.candidate(table,mid,'Set Mandate:'))
        engine=cold(tmp_path,mid)
        assert next(c for c in engine.state.actors[S.OWNER].conditions.values() if c.condition_id==M.MASS_LOAD).expires_on!='CONCENTRATION_END'
        turn(table,mid,commit);cast(table,mid,commit,'Place Mandate: Quicken')
        engine=cold(tmp_path,mid)
        assert not P.persisted(engine,engine.state.actors[S.OWNER],P.MANDATE)
        assert not any('mandate.' in m.source_definition_id for m in engine.state.actors[S.THIRD].modifiers.values())


@pytest.mark.parametrize('natural,success',[(1,False),(20,True)])
def test_sovereign_successful_check_refunds_cp(monkeypatch,tmp_path,natural,success):
    combat,table,mid,send,commit=fixture(monkeypatch,tmp_path,talents=['sovereign_of_the_true_name_of_things'],foe_talents=['quicken_and_slow'])
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=S.FOE:
        commit(table.state(mid)['menu']['end_turn'])
    cast(table,mid,commit,'Place Mandate: Quicken',S.FOE)
    while table.state(mid)['menu']['actor_id']!=S.OWNER:
        commit(table.state(mid)['menu']['end_turn'])
    from combat.gate2_rolls import DeterministicRollAuthority
    def fixed(self,sides):
        count=self.counter;self.counter+=1
        return min(natural,sides),count
    monkeypatch.setattr(DeterministicRollAuthority,'_die',fixed)
    before=cold(tmp_path,mid).state.actors[S.OWNER].resources[QI]
    cast(table,mid,commit,'Counter-Mandate: strip a foe',S.FOE)
    engine=cold(tmp_path,mid)
    assert engine.state.actors[S.OWNER].resources[QI]==before-1+int(success)
    checks=[e for e in engine.events if e.event_type=='CHECK_ROLLED' and e.actor_id==S.OWNER]
    assert checks[-1].payload['success']==success
    gains=[e for e in engine.events if e.event_type=='RESOURCE_GAINED' and e.actor_id==S.OWNER and e.payload.get('resource_id')==QI]
    assert len(gains)==int(success)
    if success:assert engine.state.actors[S.OWNER].turn_flags[f'sovereign_imbuement_round_{engine.state.round_number}']


def test_mass_hostiles_save_independently(monkeypatch,tmp_path):
    combat,table,mid,send,commit=fixture(monkeypatch,tmp_path,talents=['mass_mandate'],extra=True,third_ally=False,foe_score=100)
    from combat.gate2_rolls import DeterministicRollAuthority
    def fixed(self,sides):
        count=self.counter;self.counter+=1
        return min(20,sides),count
    monkeypatch.setattr(DeterministicRollAuthority,'_die',fixed)
    cast(table,mid,commit,'Mass Fray Mandate: Slow (',S.FOE)
    engine=cold(tmp_path,mid)
    assert not any('mandate.' in m.source_definition_id for m in engine.state.actors[S.FOE].modifiers.values())
    assert any('mandate.' in m.source_definition_id for m in engine.state.actors[S.THIRD].modifiers.values())
    assert len([e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id in (S.FOE,S.THIRD)])==2

@pytest.mark.parametrize('natural,success',[(1,False),(20,True)])
def test_mandate_breaker_suppression_or_free_opposite(monkeypatch,tmp_path,natural,success):
    combat,table,mid,send,commit=fixture(monkeypatch,tmp_path,insights=['insight.mandate-breaker'],foe_talents=['quicken_and_slow'])
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=S.FOE:
        commit(table.state(mid)['menu']['end_turn'])
    cast(table,mid,commit,'Place Mandate: Quicken',S.FOE)
    while table.state(mid)['menu']['actor_id']!=S.OWNER:
        commit(table.state(mid)['menu']['end_turn'])
    from combat.gate2_rolls import DeterministicRollAuthority
    def fixed(self,sides):
        count=self.counter;self.counter+=1
        return min(natural,sides),count
    monkeypatch.setattr(DeterministicRollAuthority,'_die',fixed)
    before=cold(tmp_path,mid).state.actors[S.OWNER].resources[QI]
    cast(table,mid,commit,'Counter-Mandate: strip a foe',S.FOE)
    engine=cold(tmp_path,mid);foe=engine.state.actors[S.FOE];owner=engine.state.actors[S.OWNER]
    assert owner.resources[QI]==before-(1 if success else 2)
    if success:
        assert foe.concentration is None
        assert any('mandate.fray.slow' in m.source_definition_id for m in foe.modifiers.values())
        assert owner.concentration.source_definition_id.endswith('mandate.fray.slow')
        assert any(c.condition_id==M.BREAKER_USED for c in owner.conditions.values())
    else:
        assert foe.concentration is not None
        assert any(m.target_field.startswith('suppressed:') for m in foe.modifiers.values())
        assert not any(c.condition_id==M.BREAKER_USED for c in owner.conditions.values())
        turn(table,mid,commit)
        engine=cold(tmp_path,mid)
        assert engine.state.actors[S.FOE].concentration is not None
        assert not any(m.target_field.startswith('suppressed:') for m in engine.state.actors[S.FOE].modifiers.values())


def test_mass_inside_court_uses_one_slot_and_grants_each_recipient_temp_hp_once(monkeypatch,tmp_path):
    combat,table,mid,send,commit=fixture(monkeypatch,tmp_path,talents=['mass_mandate','court_of_ten_thousand_mandates'],extra=True)
    commit(S.candidate(table,mid,'Court of Ten Thousand Mandates'))
    cast(table,mid,commit,'Mass Place Mandate: Quicken',S.SECOND)
    engine=cold(tmp_path,mid)
    marker=next(c for c in engine.state.actors[S.OWNER].conditions.values() if c.condition_id==M.MASS_LOAD)
    assert marker.data['weight']==1
    for aid in (S.OWNER,S.SECOND,S.THIRD):
        assert engine.state.actors[aid].temporary_hp==2
        assert len([e for e in engine.events if e.event_type=='TEMP_HP_GRANTED' and aid in e.target_ids])==1


def test_mass_load_shrinks_when_one_persisted_recipient_is_countered(monkeypatch,tmp_path):
    combat,table,mid,send,commit=fixture(monkeypatch,tmp_path,talents=['mass_mandate','layered_mandate'],extra=True,foe_talents=['quicken_and_slow'])
    cast(table,mid,commit,'Mass Place Mandate: Quicken',S.SECOND)
    commit(S.candidate(table,mid,'Set Mandate:'))
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=S.FOE:
        commit(table.state(mid)['menu']['end_turn'])
    from combat.gate2_rolls import DeterministicRollAuthority
    def fixed(self,sides):
        count=self.counter;self.counter+=1
        return min(20,sides),count
    monkeypatch.setattr(DeterministicRollAuthority,'_die',fixed)
    cast(table,mid,commit,'Counter-Mandate: strip a foe',S.SECOND)
    while table.state(mid)['menu']['actor_id']!=S.OWNER:
        commit(table.state(mid)['menu']['end_turn'])
    cast(table,mid,commit,'Place Mandate: Quicken',S.SECOND)
    engine=cold(tmp_path,mid);owner=engine.state.actors[S.OWNER]
    assert len(P.persisted(engine,owner,P.MANDATE))==1
    for aid in (S.OWNER,S.THIRD):
        assert any('.mass' in m.source_definition_id for m in engine.state.actors[aid].modifiers.values())
