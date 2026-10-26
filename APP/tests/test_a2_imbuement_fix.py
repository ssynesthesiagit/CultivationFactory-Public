"""Review regressions through table/session transactions, cold reload and replay."""
import pytest
from tests.test_a2_imbuement import fixture, cold, turn, cast, IMB, QI, M, P, S

@pytest.mark.parametrize('ai,use',[(False,False),(False,True),(True,True)])
def test_mass_additional_recipient_gets_target_reaction(monkeypatch,tmp_path,ai,use):
    from combat.canonical import canonical_sha256
    reaction='test:a2imb.brace'
    real=S.compile_character
    def compile_with_reactions(*args,**kwargs):
        if kwargs['actor_id'] in (S.SECOND,S.THIRD):kwargs['reaction_plan']={'ask':True}
        bundle=real(*args,**kwargs)
        if kwargs['actor_id'] in (S.SECOND,S.THIRD):
            bundle['typed_reactions'].append({'feature_id':reaction,'name':'Brace for the Mandate',
                'block':'generic','kind':'technique_targets','range_ft':60,'ask':True,
                'costs':[[QI,1]],'effects':[]})
            bundle.pop('bundle_sha256',None)
            bundle['bundle_sha256']=canonical_sha256(bundle)
        return bundle
    monkeypatch.setattr(S,'compile_character',compile_with_reactions)
    combat,table,mid,send,commit=fixture(monkeypatch,tmp_path,talents=['mass_mandate','layered_mandate'],extra=True)
    cid=S.candidate(table,mid,'Mass Place Mandate: Quicken',S.THIRD if not ai else S.OWNER)
    if ai:S.force_ai_candidate(combat,mid,S.OWNER,cid)
    before=cold(tmp_path,mid).state.actors[S.SECOND].resources[QI]
    answers=[];seen=[]
    for _ in range(12):
        result=send(cid,answers,auto=ai)
        if result['status']=='COMMITTED':break
        assert result['status']=='REACTION_REQUIRED',result
        prompt=result['reaction'];context=prompt['context'];key=context['reaction_source_id']
        answer={**context,'selection':'DECLINE'}
        if key=='choice:needle.mass_mandate':
            answer.update(selection='USE',option_ids=[S.OWNER,S.SECOND])
        elif key=='reaction:typed.'+reaction:
            seen.append(context['reactor_id'])
            assert context['reactor_id'] in ((S.SECOND,S.THIRD) if ai else (S.SECOND,))
            answer['selection']='USE' if use else 'DECLINE'
            assert cold(tmp_path,mid).state.actors[S.SECOND].resources[QI]==before
        elif prompt.get('choice'):
            answer.update(selection='USE',option_ids=[prompt['choice']['options'][0]['id']])
        answers.append(answer)
    else:raise AssertionError('too many prompts')
    assert seen==([S.SECOND,S.THIRD] if ai else [S.SECOND])
    engine=cold(tmp_path,mid)
    assert engine.state.actors[S.SECOND].resources[QI]==before-int(use)
    assert any('.mass' in m.source_definition_id for m in engine.state.actors[S.SECOND].modifiers.values())
    if not ai:assert not any('.mass' in m.source_definition_id for m in engine.state.actors[S.THIRD].modifiers.values())


def test_same_mass_option_persisted_copy_does_not_charge_new_copy(monkeypatch,tmp_path):
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    fourth=FACTORY_ACTOR_PREFIX+'r1i-fourth'
    finish=CombatService._finish_factory_match
    def with_fourth(self,*args,**kwargs):
        args=list(args)
        doc=S.sheet([],cl=17);doc['identity']['display_name']='Fourth'
        doc['ability_scores_and_statistics']['hit_points']['maximum']=500
        args[0].append(S.compile_character(doc,actor_id=fourth))
        args[1].append(fourth);args[2][fourth]='team:a';args[3][fourth]={'x':6,'y':6}
        args[6].append(fourth);kwargs['control_modes'][fourth]='MANUAL'
        return finish(self,*args,**kwargs)
    monkeypatch.setattr(CombatService,'_finish_factory_match',with_fourth)
    combat,table,mid,send,commit=fixture(monkeypatch,tmp_path,insights=['insight.dual-mandate-adept'],talents=['mass_mandate','layered_mandate'],extra=True)
    def selected_cast(ids,target):
        cid=S.candidate(table,mid,'Mass Place Mandate: Quicken',target)
        answers=[]
        for _ in range(12):
            result=send(cid,answers)
            if result['status']=='COMMITTED':return result
            assert result['status']=='REACTION_REQUIRED',result
            p=result['reaction'];a={**p['context'],'selection':'DECLINE'}
            if p.get('choice'):
                a.update(selection='USE',option_ids=ids if p['context']['reaction_source_id']=='choice:needle.mass_mandate' else [p['choice']['options'][0]['id']])
            answers.append(a)
        raise AssertionError('too many prompts')
    selected_cast([S.OWNER,S.SECOND,S.THIRD],S.SECOND)
    commit(S.candidate(table,mid,'Set Mandate:'))
    engine=cold(tmp_path,mid);owner=engine.state.actors[S.OWNER]
    kept=P.persisted(engine,owner,P.MANDATE)
    assert len(kept)==1 and M._mandate_weight(engine,owner,kept[0][1].source_definition_id,kept[0][1].data['started'])==2
    turn(table,mid,commit)
    selected_cast([fourth],fourth)
    engine=cold(tmp_path,mid);owner=engine.state.actors[S.OWNER]
    kept=P.persisted(engine,owner,P.MANDATE)
    assert len(kept)==1
    assert M.load(engine,owner,4)==3
    source=owner.concentration.source_definition_id
    assert M._mandate_weight(engine,owner,source,owner.concentration.started_sequence)==1
    assert M._mandate_weight(engine,owner,source,kept[0][1].data['started'])==2
    for aid in (S.OWNER,S.SECOND,S.THIRD,fourth):
        assert any('.mass' in m.source_definition_id for m in engine.state.actors[aid].modifiers.values())


def test_setting_evidence_names_duration_from_setting(monkeypatch,tmp_path):
    combat,table,mid,send,commit=fixture(monkeypatch,tmp_path,talents=['qi_written_mandate','sovereign_of_the_true_name_of_things'])
    cast(table,mid,commit,'Place Mandate: Quicken')
    engine=cold(tmp_path,mid)
    for minutes in (1,10):
        action=next(a for a in engine.action_catalog.values() if a.owner_id==S.OWNER and a.display_name.startswith(f'Set Mandate: {minutes} minute'))
        evidence=action.parameters['typed']['effects'][0]['evidence']
        assert f'{minutes} minute' in evidence and 'from setting' in evidence
        assert 'remaining duration' not in evidence

@pytest.mark.parametrize('natural,ai',[(1,False),(20,False),(1,True),(20,True)])
def test_breaker_context_and_cross_encounter_limit_is_explicit_rider(monkeypatch,tmp_path,natural,ai):
    from combat.gate5_service import CombatService
    from combat.gate2_rolls import DeterministicRollAuthority
    import copy
    starts=[]
    finish=CombatService._finish_factory_match
    def capture(self,*args,**kwargs):
        starts.append((copy.deepcopy(args),copy.deepcopy(kwargs)))
        return finish(self,*args,**kwargs)
    monkeypatch.setattr(CombatService,'_finish_factory_match',capture)
    combat,table,mid,send,commit=fixture(monkeypatch,tmp_path,insights=['insight.mandate-breaker'],foe_talents=['quicken_and_slow'])
    def fixed(self,sides):
        count=self.counter;self.counter+=1
        return min(natural,sides),count
    monkeypatch.setattr(DeterministicRollAuthority,'_die',fixed)
    for encounter in range(2 if natural==20 and not ai else 1):
        if encounter:
            args,kwargs=starts[0];kwargs['match_seed']='A2IMB-SECOND'
            mid=finish(combat,*args,**kwargs)['match_id']
            def send(cid,answers=(),auto=False):
                if auto:return table.auto_step(mid,0,list(answers))
                menu=table.state(mid)['menu']
                return table.act(mid,cid,menu['decision_id'],menu['state_version'],0,list(answers))
            def commit(cid):
                answers=[]
                for _ in range(16):
                    result=send(cid,answers)
                    if result['status']=='COMMITTED':return result
                    p=result['reaction'];a={**p['context'],'selection':'DECLINE'}
                    if p.get('choice'):
                        a.update(selection='USE',option_ids=[p['choice']['options'][0]['id']])
                    answers.append(a)
                raise AssertionError('too many prompts')
        while table.state(mid)['menu']['actor_id']!=S.FOE:
            commit(table.state(mid)['menu']['end_turn'])
        cast(table,mid,commit,'Place Mandate: Quicken',S.FOE)
        while table.state(mid)['menu']['actor_id']!=S.OWNER:
            commit(table.state(mid)['menu']['end_turn'])
        cid=S.candidate(table,mid,'Counter-Mandate: strip a foe',S.FOE)
        if ai:S.force_ai_candidate(combat,mid,S.OWNER,cid)
        answers=[];seen=[]
        for _ in range(12):
            result=send(cid,answers,auto=ai)
            if result['status']=='COMMITTED':break
            assert result['status']=='REACTION_REQUIRED',result
            p=result['reaction'];key=p['context']['reaction_source_id']
            a={**p['context'],'selection':'DECLINE'}
            if key.startswith('choice:needle.mandate_breaker_'):
                seen.append(key)
                assert p['affected']=='Foe' and p['by']=='Foe'
                assert p['trigger_actor']=='Owner' and 'Counter-Mandate' in p['action']
                assert 'Foe' in p['moment'] and 'Quicken' in p['moment']
                if natural==20:
                    assert 'GM' in p['moment'] and 'between fights' in p['moment'] and 'Full Cultivation Session' in p['moment']
                if encounter==0:a.update(selection='USE',option_ids=[p['choice']['options'][0]['id']])
            elif p.get('choice'):
                a.update(selection='USE',option_ids=[p['choice']['options'][0]['id']])
            answers.append(a)
        else:raise AssertionError('too many prompts')
        assert seen==([] if ai else ['choice:needle.mandate_breaker_'+('opposite' if natural==20 else 'suppress')])
        engine=cold(tmp_path,mid)
        owner=engine.state.actors[S.OWNER]
        if natural==20:
            assert any(c.condition_id==M.BREAKER_USED for c in owner.conditions.values())==(encounter==0 and not ai)
            assert bool(owner.concentration)==(encounter==0 and not ai)

        else:
            assert any(m.target_field.startswith('suppressed:') for m in engine.state.actors[S.FOE].modifiers.values())


def test_one_minute_set_actually_expires_through_turn_transactions(monkeypatch,tmp_path):
    from combat.gate5_service import CombatService
    real=CombatService._finish_factory_match
    def longer(self,*args,**kwargs):
        return real(self,*args,**{**kwargs,'maximum_rounds':20})
    monkeypatch.setattr(CombatService,'_finish_factory_match',longer)
    combat,table,mid,send,commit=fixture(monkeypatch,tmp_path,talents=['qi_written_mandate'])
    cast(table,mid,commit,'Place Mandate: Quicken')
    commit(S.candidate(table,mid,'Set Mandate: 1 minute'))
    engine=cold(tmp_path,mid);start=engine.state.round_number
    for _ in range(9):turn(table,mid,commit)
    engine=cold(tmp_path,mid)
    assert engine.state.round_number==start+9
    assert P.persisted(engine,engine.state.actors[S.OWNER],P.MANDATE)
    assert any('quicken' in m.source_definition_id for m in engine.state.actors[S.SECOND].modifiers.values())
    turn(table,mid,commit)
    engine=cold(tmp_path,mid)
    assert engine.state.round_number==start+10
    assert not P.persisted(engine,engine.state.actors[S.OWNER],P.MANDATE)
    assert not any('quicken' in m.source_definition_id for m in engine.state.actors[S.SECOND].modifiers.values())


def test_sovereign_two_successes_one_round_then_next_round(monkeypatch,tmp_path):
    import copy
    from combat.canonical import canonical_sha256
    from combat.gate2_rolls import DeterministicRollAuthority
    real=S.compile_character
    def prepare(doc,*args,**kwargs):
        if kwargs['actor_id']==S.THIRD:
            doc=S.sheet([IMB+'quicken_and_slow'],cl=17)
            doc['identity']['display_name']='Third'
            doc['ability_scores_and_statistics']['hit_points']['maximum']=500
        bundle=real(doc,*args,**kwargs)
        if kwargs['actor_id']==S.OWNER:
            action=copy.deepcopy(next(a for a in bundle['action_catalog'] if a['display_name'].startswith('Counter-Mandate: strip a foe')))
            action.update(source_definition_id='test:a2imb.reward_check',display_name='Counter-Mandate reward probe',economy='NONE')
            bundle['action_catalog'].append(action)
            bundle['actor_template']['action_ids'].append(action['source_definition_id'])
            bundle.pop('bundle_sha256',None)
            bundle['bundle_sha256']=canonical_sha256(bundle)
        return bundle
    monkeypatch.setattr(S,'compile_character',prepare)
    combat,table,mid,send,commit=fixture(monkeypatch,tmp_path,talents=['sovereign_of_the_true_name_of_things'],extra=True,third_ally=False,foe_talents=['quicken_and_slow'])
    def fixed(self,sides):
        count=self.counter;self.counter+=1
        return min(20,sides),count
    monkeypatch.setattr(DeterministicRollAuthority,'_die',fixed)
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=S.OWNER:
        actor=table.state(mid)['menu']['actor_id']
        if actor in (S.FOE,S.THIRD):cast(table,mid,commit,'Place Mandate: Quicken',actor)
        commit(table.state(mid)['menu']['end_turn'])
    before=cold(tmp_path,mid).state.actors[S.OWNER].resources[QI]
    for target in (S.FOE,S.THIRD):cast(table,mid,commit,'Counter-Mandate reward probe',target)
    engine=cold(tmp_path,mid)
    assert engine.state.actors[S.OWNER].resources[QI]==before-1
    gains=[e for e in engine.events if e.event_type=='RESOURCE_GAINED' and e.actor_id==S.OWNER and e.payload.get('resource_id')==QI]
    assert len(gains)==1
    checks=[e for e in engine.events if e.event_type=='CHECK_ROLLED' and e.actor_id==S.OWNER]
    assert len(checks)==2 and all(e.payload['success'] for e in checks)
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=S.OWNER:
        actor=table.state(mid)['menu']['actor_id']
        if actor==S.FOE:cast(table,mid,commit,'Place Mandate: Quicken',actor)
        commit(table.state(mid)['menu']['end_turn'])
    cast(table,mid,commit,'Counter-Mandate reward probe',S.FOE)
    engine=cold(tmp_path,mid)
    assert engine.state.actors[S.OWNER].resources[QI]==before-1
    assert len([e for e in engine.events if e.event_type=='RESOURCE_GAINED' and e.actor_id==S.OWNER and e.payload.get('resource_id')==QI])==2
