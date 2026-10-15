"""Real ranged rolls consume printed low-wall profiles without blanket cover."""
from tests.mason_native_support import *


@pytest.mark.parametrize('producer',['mason','gm','untagged','overlap'])
def test_native_partial_cover_roll_and_elevated_boundary(tmp_path,producer):
    declaration={'actor':'gm:review','authority':'GM','source_rule':'This stable object supplies its declared physical profile.',
        'visibility':'public','expiry':'source_rule'}
    rows=[{'id':2,'kind':'custom','x':3,'y':5,'height_ft':10,'blocks':False,'ordinary_route':'ladder',
        'asset_declaration':declaration}]
    if producer!='mason':
        wall={'id':1,'kind':'custom','x':6,'y':6,'height_ft':3,'blocks':True}
        if producer in ('gm','overlap'):wall.update(cover='half',asset_declaration=declaration)
        rows.append(wall)
        if producer=='overlap':rows.append({'id':3,'kind':'custom','x':6,'y':6,'height_ft':3,'blocks':True})
    features=[*FEATURES,'TAL_LIGHTNING_LIGHTNING_LASH'] if producer=='mason' else ['TAL_LIGHTNING_LIGHTNING_LASH']
    combat,table,mid,send,commit=fixture(tmp_path,features=features,scene_objects=rows,
        positions={s.OWNER:{'x':3,'y':6},s.FOE:{'x':9,'y':6},s.SECOND:{'x':2,'y':6}})
    if producer=='mason':
        commit(at(table,mid,'Raise Barrier: Low Wall',6,6));next_owner(table,mid,commit)
    if producer in ('untagged','overlap'):
        assert not any(s.FOE in o.get('target_ids',[]) for g in table.state(mid)['menu']['actions'] if 'Lightning Lash' in g['label'] for o in g['options'])
        cold(tmp_path,mid);return
    commit(s.candidate(table,mid,'Lightning Lash',s.FOE))
    engine=cold(tmp_path,mid)
    roll=next(e for e in reversed(engine.events) if e.event_type=='ATTACK_ROLLED' and s.FOE in e.target_ids)
    assert roll.payload['cover_bonus']==(0 if producer=='untagged' else 2)
    next_owner(table,mid,commit)
    move=next(c for c in combat._legal_candidates(combat._load_session(mid)) if c.kind=='MOVE'
        and c.destination is not None and (c.destination.x,c.destination.y,c.destination.z)==(3,5,2))
    commit(move.candidate_id)
    commit(s.candidate(table,mid,'Lightning Lash',s.FOE))
    engine=cold(tmp_path,mid)
    roll=next(e for e in reversed(engine.events) if e.event_type=='ATTACK_ROLLED' and s.FOE in e.target_ids)
    assert roll.payload['cover_bonus']==0, 'a three-foot wall cannot cover a body ray wholly above it'
