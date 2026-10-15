"""Procedural load declarations use the actual table chooser for every Greater form."""
from tests.mason_native_support import *


@pytest.mark.parametrize('form',['Great Bridge','Ascending Stair','Defensive Tower','Gatehouse'])
def test_greater_load_is_declared_before_native_construction(tmp_path,form):
    combat,table,mid,send,commit=fixture(tmp_path)
    cid=at(table,mid,'Bridge the Impossible: '+form,6,8)[0]
    from combat.placement_menu import CHOICE
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    answers=[];prompts=[]
    for _ in range(64):
        result=send(cid,answers)
        if result['status']=='COMMITTED':break
        assert result['status']=='REACTION_REQUIRED',result
        p=result['reaction'];prompts.append(p)
        answer={**p['context'],'selection':'DECLINE'}
        if p.get('choice'):
            options=p['choice'].get('preferred') or [p['choice']['options'][0]['id']]
            if p['context']['reaction_source_id']==CHOICE:options=[cell_id(Position(x=6,y=8),include_altitude=True)]
            answer.update(selection='USE',option_ids=options[:1])
        answers.append(answer)
    else:raise AssertionError('native declaration did not commit')
    assert any(p['context']['reaction_source_id']=='choice:needle.mason_load_0' for p in prompts)
    engine=cold(tmp_path,mid)
    assert engine.state.actors[s.OWNER].resources['resource:core.qi']==26
    assert all(o.component['mason']['declaration']['legal_load']=='ordinary' for o in works(engine))
    assert all('declared legal load:' in o.component['profile_description'] for o in works(engine))
