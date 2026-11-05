"""Final Cremation uses native Source CL, saves, damage and point expenditure."""
import pytest
from tests.test_mgr_cremation_native import game,fight,verify,A,B
from tests.worker2_support import settle,turn


@pytest.mark.parametrize('target_cl,mode',[(20,'ADVANTAGE'),(12,'DISADVANTAGE')])
def test_native_successful_final_retains_cp_and_uses_printed_source_cl_mode(tmp_path,monkeypatch,target_cl,mode):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=18,target_cl=target_cl,target_hp=500,target_features=['FIRE_TAL_BURNING_WEAPON'],target_scores={'CON':200},owner_score=40)
    s,t,mid=fight(cold,jid,tmp_path);turn(t,mid,B)
    ward=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name=='Burning Weapon')
    settle(t,mid,ward.candidate_id);turn(t,mid,A)
    heaven=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Cremate Heaven and Earth') and c.destination and (c.destination.x,c.destination.y)==(7,4))
    settle(t,mid,heaven.candidate_id)
    burn=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Burn the Scripture — sovereign Bonus') and c.target_ids==(B,))
    settle(t,mid,burn.candidate_id)
    engine=verify(cold,mid)
    assert any(c.condition_id=='condition:typed.cremation.sentence' for c in engine.state.actors[B].conditions.values())
    assert any(r.expression.startswith('4d8') for r in engine.rolls)
    start=engine.state.event_sequence
    final=next(c for c in engine.legal_candidates() if c.display_name.startswith('Final Cremation') and c.target_ids==(B,))
    settle(t,mid,final.candidate_id)
    engine=verify(cold,mid)
    saves=[r for r in engine.rolls if r.actor_id==B and final.source_definition_id in r.reason and 'SAVE:' in r.reason]
    assert saves and str(saves[-1].mode)==mode
    assert not any(c.condition_id=='condition:typed.cremation.final' for c in engine.state.actors[B].conditions.values())
    assert not any(c.display_name.startswith('Final Cremation') for c in engine.legal_candidates())
    damage=next(e for e in engine.events if e.sequence>start and e.event_type=='DAMAGE_COMMITTED' and B in e.target_ids and e.source_definition_id==final.source_definition_id)
    roll=next(r for r in engine.rolls if r.expression.startswith('12d10'))
    assert damage.payload['hp_damage']==roll.total//2
    decline={'choice:needle.cremation.touch':None,'choice:needle.cremation.sentence':None}
    settle(t,mid,t.state(mid)['menu']['end_turn'],picks=decline);turn(t,mid,B)
    engine=verify(cold,mid);before=engine.state.actors[B].resources['resource:core.qi']
    conflag=next(c for c in engine.legal_candidates() if c.source_definition_id.endswith('.FIRE_BASE_CONFLAGRATION') and c.destination and (c.destination.x,c.destination.y)==(12,3))
    settle(t,mid,conflag.candidate_id,picks=decline)
    assert verify(cold,mid).state.actors[B].resources['resource:core.qi']==before-2
