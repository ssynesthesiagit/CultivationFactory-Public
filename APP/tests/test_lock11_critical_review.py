"""Expanded automatic hits are successful before rewrite eligibility is decided."""
import pytest
from combat import ext
from combat.ext.d20_rewrite import RollCtx, Holder
from combat.ext.d20_rewrite_fate import good_for_us as _good_for_us
from combat.ext.mind_hidden_eye import mark_analyzed
from combat.gate5_service import CombatService
from tests import test_tabletop_hunt6 as H
from tests.h1_support import ROOT
from tests.test_auto_H1_rerolls import WAKING
from tests.test_lock9_critical_range import GAP,native,hold_sender


@pytest.mark.parametrize('mode',['MANUAL','LOCAL_AUTO'])
@pytest.mark.parametrize('natural,rewritten',[(19,False),(18,True)])
def test_table_find_gap_and_waking_dream_share_pre_rewrite_hit_policy(monkeypatch,tmp_path,mode,natural,rewritten):
    real=H.sheet
    monkeypatch.setattr(H,'sheet',lambda *a,**kw:real(*a,**kw,primary='Resonance'))
    from combat.tabletop import ButtonStore
    ButtonStore(tmp_path/'tabletop_buttons').save_reactions(H.PROJECTS['ally'],{'mode':'ask'},{'opportunity_attack'})
    combat,table,mid=H.table_fight(tmp_path,[GAP],ally_talents=[WAKING])
    combat.set_controller_mode(mid,actor_id=H.ALLY,controller_mode=mode)
    seen=[]
    def observe(engine,roll,intent):
        if roll.actor_id!=H.LEFT or not roll.reason.startswith('ATTACK:'):
            return None
        frame=engine.d20_context(roll)
        assert frame['spec']['critical_threshold']==19
        assert frame['spec']['attack_name']=='Native-Crit'
        rc=RollCtx(engine,roll,'attack',engine.state.actors[H.LEFT],
            target=engine.state.actors[H.RIGHT],spec=frame['spec'],ac=frame['ac'])
        holder=Holder(engine.state.actors[H.ALLY],WAKING,{},WAKING)
        assert _good_for_us(holder,rc,19) is True
        assert _good_for_us(holder,rc,18) is False
        assert _good_for_us(holder,rc,1) is False
        seen.append(rc.succeeded())
    ext.effects();monkeypatch.setitem(ext._HOOKS,'d20_result',[*ext._HOOKS.get('d20_result',[]),observe])
    def attack(e):
        mark_analyzed(e,e.state.actors[H.LEFT],e.state.actors[H.RIGHT],'test:analyze')
        e._add_modifier(e.state.actors[H.RIGHT],'test:armor','armor_class','ADD',100,'SELF',expires_on='UNTIL_REMOVED')
        native(e,natural,attacker=H.LEFT,target=H.RIGHT)
    H.on_hold(monkeypatch,attack)
    before=combat._load_session(mid).engine.state.model_dump(mode='json')
    resources=before['actors'][H.ALLY]['resources']
    send=hold_sender(table,mid);result=send()
    if rewritten and mode=='MANUAL':
        assert result['status']=='REACTION_REQUIRED'
        assert WAKING in str(result['reaction'])
        assert CombatService(ROOT,tmp_path)._load_session(mid).engine.state.model_dump(mode='json')==before
        result=send([{**result['reaction']['context'],'selection':'USE'}])
    assert result['status']=='COMMITTED'
    fresh=CombatService(ROOT,tmp_path)._load_session(mid); e=fresh.engine; owner=e.state.actors[H.ALLY]
    events=[ev for ev in e.events if ev.event_type=='D20_REWRITTEN' and ev.source_definition_id==WAKING]
    assert bool(events) is rewritten
    assert owner.reaction_available is (not rewritten)
    assert resources['resource:core.resonance']-owner.resources['resource:core.resonance']==(3 if rewritten else 0)
    roll=next(ev for ev in reversed(e.events) if ev.event_type=='ATTACK_ROLLED')
    assert roll.payload['critical_threshold']==19 and roll.payload['provisional_hit'] is (not rewritten)
    assert seen
    assert fresh.verify()['status']==fresh.mechanical.replay()['status']=='PASS'


def test_reused_spec_does_not_keep_an_expired_expanded_threshold(monkeypatch):
    from tests.h1_support import duel,ME,FOE,script
    from tests.test_lock_choices import install
    e=duel([]); spec={'attack_bonus':0,'reach_ft':100}; thresholds=[]
    install(monkeypatch,'d20_result',lambda engine,roll,intent:thresholds.append(engine.d20_context(roll)['spec'].get('critical_threshold',20)))
    install(monkeypatch,'attack_critical_range',lambda *args:19)
    for enabled in (True,False):
        if not enabled:
            install(monkeypatch,'attack_critical_range',lambda *args:None)
        script(e,[19])
        e._resolve_attack_spec(e.state.actors[ME],e.state.actors[FOE],spec,None,source_definition_id='test:reused')
    assert thresholds==[19,20]
