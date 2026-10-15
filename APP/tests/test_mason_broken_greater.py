"""A replaced Greater source cannot be revived beside its replacement."""
from tests.mason_native_support import *


def test_table_replacement_retires_completely_broken_greater_source(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,damage=200)
    dimensions={'choice:needle.mason_length_0':'5','choice:needle.mason_width_0':'5','choice:needle.mason_height_0':'5'}
    commit(at(table,mid,'Bridge the Impossible: Great Bridge',4,5),picks=dimensions)
    old=works(cold(tmp_path,mid))[0].object_id
    next_owner(table,mid,commit)
    commit(s.candidate(table,mid,'Damage a structure',old),decline=('choice:needle.mason_intervention',))
    assert cold(tmp_path,mid).state.objects[old].destroyed
    next_owner(table,mid,commit)
    commit(at(table,mid,'Bridge the Impossible: Ascending Stair',6,8),picks=dimensions)
    next_owner(table,mid,commit)
    offered=[o for g in table.state(mid)['menu']['actions'] if 'Repair Structure with sufficient material' in g['label']
             for o in g['options'] if old in o.get('target_ids',[])]
    if offered:commit(offered[0]['candidate_id'])
    engine=cold(tmp_path,mid)
    groups={o.component['asset_anchor_runtime']['group'] for o in works(engine)
            if o.component['mason']['feature']==BASE+'bridge_the_impossible'}
    assert len(groups)==1, 'repairing a replaced source cannot create a second Greater Structure'
    assert engine.state.objects[old].destroyed and engine.state.objects[old].component['asset_anchor_runtime']['ended']
    assert engine.state.actors[s.OWNER].resources['resource:core.qi']==22


def test_journey_replacement_retires_completely_broken_greater_source(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,damage=200)
    engine=cold(tmp_path,mid)
    j=combat.journeys.create(engine.typed_bundle_documents,engine.battlefield_document,
        {aid:a.position.model_dump(mode='json') for aid,a in engine.state.actors.items()},
        {aid:3000 for aid in engine.state.actors});jid=j['journey_id']
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    def payload(form,x,y):
        return {'source':BASE+'bridge_the_impossible','form':form,'sections':[{
            'position':{'x':x,'y':y},'form':form,'length_ft':5,'width_ft':5,'height_ft':5,'rotation':0,
            'material_source':'terrain:'+cell_id(Position(x=x,y=y)),'legal_load':'ordinary'}]}
    state=combat.journey_act(jid,j['revision'],s.OWNER,'mason_build',payload('Great Bridge',4,5))
    old=next(iter(state['runtime_objects']))
    started=combat.journey_start_combat(jid,state['revision'],
        {s.OWNER:'team:a',s.FOE:'team:b',s.SECOND:'team:a'},maximum_rounds=1)
    mid=started['match_id']
    from combat.tabletop_service import TabletopService
    table=TabletopService(combat,tmp_path)
    while table.state(mid)['menu']['actor_id']!=s.OWNER:commit_other_table(table,mid,table.state(mid)['menu']['end_turn'])
    # This source owns a deterministic native object action; decline the optional response.
    answers=[];cid=s.candidate(table,mid,'Damage a structure',old)
    for _ in range(32):
        menu=table.state(mid)['menu'];r=table.act(mid,cid,menu['decision_id'],menu['state_version'],0,answers)
        if r['status']=='COMMITTED':break
        assert r['status']=='REACTION_REQUIRED',r
        p=r['reaction'];answers.append({**p['context'],'selection':'DECLINE'})
    else:raise AssertionError('damage did not commit')
    assert cold(tmp_path,mid).state.objects[old].destroyed
    for _ in range(12):
        if cold(tmp_path,mid).state.terminal_result is not None:break
        commit_other_table(table,mid,table.state(mid)['menu']['end_turn'])
    assert cold(tmp_path,mid).state.terminal_result is not None
    state=combat.journey_state(jid);state=combat.journey_resume(jid,state['revision'])
    state=combat.journey_act(jid,state['revision'],s.OWNER,'mason_build',payload('Ascending Stair',6,8))
    with pytest.raises(ValueError):
        combat.journey_act(jid,state['revision'],s.OWNER,'mason_repair',{
            'object_id':old,'material_source':'terrain:'+cell_id(Position(x=4,y=5)),'sufficient_material':True})
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state
    assert state['runtime_objects'][old]['component']['asset_anchor_runtime']['ended']
