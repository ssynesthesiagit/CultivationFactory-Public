import pytest
from tests.h1_support import sheet
from tests.worker2_support import fixture,candidate,settle,reload,turn,OWNER,ALLY,FOE
P='tianxia.subpath.qi.bell_tower_cultivator.feature.'

def cast(combat,table,mid,name,choices):
    c=candidate(combat,mid,name)
    return settle(table,mid,c.candidate_id,picks=choices)

@pytest.mark.parametrize('source_cl',[6,20])
def test_purifying_peal_collects_actual_charm_and_resolves_source_cl(tmp_path,source_cl):
    tears='tianxia.talent.beauty.tears_like_pearls'
    exercised=0
    for index in range(4):
        root=tmp_path/str(index)
        combat,table,mid=fixture(root,[],owner_features=[P+'purifying_peal'],cl=18,owner_pb=6,
            foe_sheet=sheet([tears],cl=source_cl,name='Mara'),named=True,
            seed='BELL-PURIFICATION-'+str(source_cl)+'-'+str(index))
        turn(table,mid,FOE)
        c=candidate(combat,mid,'Tears Like Pearls',target=OWNER)
        settle(table,mid,c.candidate_id)
        engine=reload(root,mid)
        conditions=[c for c in engine.state.actors[OWNER].conditions.values()
            if c.condition_id=='condition:typed.charmed']
        if not conditions:continue
        original=conditions[0]
        turn(table,mid,OWNER)
        before=combat._load_session(mid).engine.state.event_sequence
        cast(combat,table,mid,'Purifying Peal',{
            'choice:needle.bell_allies_to_purify':[OWNER],
            'choice:needle.bell_purify_'+OWNER:original.instance_id})
        engine=reload(root,mid)
        assert engine.state.actors[OWNER].resources['resource:core.qi']==96
        if source_cl<=18:
            assert original.instance_id not in engine.state.actors[OWNER].conditions
        else:
            saves=[e for e in engine.events if e.sequence>before and e.event_type=='SAVE_ROLLED'
                and e.actor_id==OWNER and e.source_definition_id==original.source_definition_id]
            assert len(saves)==1 and saves[0].payload['mode']=='ADVANTAGE'
            assert (original.instance_id not in engine.state.actors[OWNER].conditions)==saves[0].payload['success']
        exercised+=1
    assert exercised, 'Fixed native seeds must exercise an actual failed Charmed save before purification'
