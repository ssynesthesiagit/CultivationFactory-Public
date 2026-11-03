"""Separate sovereign activations retain their printed once-per-activation choice."""
from tests.test_mgr_cremation_native import game,fight,verify,A,B
from tests.worker2_support import settle,turn


def test_native_two_scenes_keep_both_live_furnaces_final_cremation_uses(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=18,target_hp=500,target_features=['FIRE_TAL_BURNING_WEAPON'],target_scores={'CON':200},owner_score=40)
    s,t,mid=fight(cold,jid,tmp_path,maximum_rounds=1)
    heaven=next(c for c in s._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Cremate Heaven and Earth') and c.destination and (c.destination.x,c.destination.y)==(7,4))
    settle(t,mid,heaven.candidate_id)
    decline={'choice:needle.cremation.touch':None,'choice:needle.cremation.sentence':None}
    for _ in range(4):
        if verify(cold,mid).state.terminal_result:break
        settle(t,mid,t.state(mid)['menu']['end_turn'],picks=decline)
    state=cold().journey_state(jid);state=cold().journey_resume(jid,state['revision'])
    state=cold().journey_end_scene(jid,state['revision'],'The first assault is over; a new assault begins while the one-minute furnace still burns.')
    s,t,mid=fight(cold,jid,tmp_path);turn(t,mid,B)
    ward=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name=='Burning Weapon')
    settle(t,mid,ward.candidate_id);turn(t,mid,A)
    heaven=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Cremate Heaven and Earth') and c.destination and (c.destination.x,c.destination.y)==(13,4))
    settle(t,mid,heaven.candidate_id)
    assert len([z for z in verify(cold,mid).state.zones.values() if z.active and z.owner_id==A])==2
    fields=[c for c in verify(cold,mid).state.actors[A].conditions.values() if c.condition_id=='condition:typed.cremation.field']
    assert len(fields)==2 and len({c.data['zone'] for c in fields})==2
    burn=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Burn the Scripture — sovereign Bonus') and c.target_ids==(B,))
    settle(t,mid,burn.candidate_id)
    for use in range(2):
        engine=verify(cold,mid)
        final=next(c for c in engine.legal_candidates() if c.display_name.startswith('Final Cremation') and c.target_ids==(B,))
        prompts=settle(t,mid,final.candidate_id)
        if use==0:
            options=next(p['choice']['options'] for p in prompts if p['context']['reaction_source_id']=='choice:needle.cremation.final_furnace')
            assert len(options)==2
        fields=[c for c in verify(cold,mid).state.actors[A].conditions.values() if c.condition_id=='condition:typed.cremation.field']
        assert sum(c.data['final_used'] for c in fields)==use+1
    engine=verify(cold,mid)
    assert len([r for r in engine.rolls if r.expression.startswith('12d10')])==2
    assert not any(c.display_name.startswith('Final Cremation') for c in engine.legal_candidates())
    # Exercise the zone-removal subscriber against the actual native zones.
    # Removing one must not erase the other activation's marker/usage.
    from combat import zones
    first,second=fields
    zones.remove(engine,engine.state.zones[first.data['zone']],'EXPIRED')
    remaining=[c for c in engine.state.actors[A].conditions.values() if c.condition_id=='condition:typed.cremation.field']
    assert len(remaining)==1 and remaining[0].data['zone']==second.data['zone']
    assert remaining[0].data['final_used']==1
