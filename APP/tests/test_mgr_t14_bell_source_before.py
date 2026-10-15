from tests.h1_support import sheet
from tests.worker2_support import fixture,candidate,settle,reload,turn,OWNER,ALLY,FOE
from combat import observer_information as information
from combat.ext import mgr_reserve_bell_tower_cultivator_watch_bell as bell
P='tianxia.subpath.qi.bell_tower_cultivator.feature.'
ALL=[]

def play(tmp_path,cl=18,features=None,**kw):
    return fixture(tmp_path,[],owner_features=ALL if features is None else features,cl=cl,named=True,**kw)

def cast(combat,table,mid,name,choices):
    c=candidate(combat,mid,name)
    return settle(table,mid,c.candidate_id,picks=choices)

def test_revealing_collects_created_minor_illusion_and_its_committed_changes(tmp_path):
    combat,table,mid=play(tmp_path,features=[bell.WATCH],ally_talents=['TAL_ILLUSION_MINOR_ILLUSION'])
    turn(table,mid,ALLY)
    c=candidate(combat,mid,'Minor Illusion',at=(5,5))
    settle(table,mid,c.candidate_id,picks={'choice:needle.minor_detail':'image'})
    engine=reload(tmp_path,mid)
    image=next(z for z in engine.state.zones.values() if bell.placed.data(z).get('tag')=='figment')
    entry=next(s for s in information.sources(engine) if s['id']==image.zone_id)
    assert entry['cl']==18 and entry['dc']==16
    assert {'illusion','visual_illusion'}<=set(entry['tags'])
    original_revision=entry['revision']
    turn(table,mid,OWNER)
    cast(combat,table,mid,'Watch Bell',{'choice:needle.bell_warning_tone':'revealing',
        'choice:needle.bell_reveal_target':bell.effect_option(engine,engine.state.actors[OWNER],entry)})
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources['resource:core.qi']==99
    assert any(e.event_type=='CHECK_ROLLED' and e.payload.get('check')=='Revealing Tone Cultivation Check'
        for e in engine.events)
    turn(table,mid,ALLY)
    c=candidate(combat,mid,'Move Minor Illusion (up to 5 feet)',at=(6,5))
    settle(table,mid,c.candidate_id)
    engine=reload(tmp_path,mid)
    moved=next(s for s in information.sources(engine) if s['id']==image.zone_id)
    assert moved['revision']!=original_revision
    assert moved['position'].x==6 and moved['position'].y==5

def test_revealing_prompt_does_not_publish_hidden_source_identifiers(tmp_path):
    from tests.test_r9i_karma_persistence import act
    combat,table,mid=fixture(tmp_path,['tianxia.talent.illusion.greater_invisibility'],
        owner_features=[P+'watch_bell'],cl=18,named=True)
    settle(table,mid,candidate(combat,mid,'Greater Invisibility',target=ALLY).candidate_id)
    cid=candidate(combat,mid,'Watch Bell').candidate_id
    first=act(table,mid,cid,[])
    assert first['status']=='REACTION_REQUIRED'
    prompt=first['reaction']
    assert prompt['context']['reaction_source_id']=='choice:needle.bell_warning_tone'
    answers=[{**prompt['context'],'selection':'USE','option_ids':['revealing']}]
    second=act(table,mid,cid,answers)
    assert second['status']=='REACTION_REQUIRED'
    prompt=second['reaction']
    effects=[o for o in prompt['choice']['options'] if o['label']=='An active supernatural effect']
    assert len(effects)==1
    assert effects[0]['id'].startswith('bell-effect:')
    assert not any(word in effects[0]['id'] for word in ('invisible','condition-instance','figment','actor:'))
    answers.append({**prompt['context'],'selection':'USE','option_ids':[effects[0]['id']]})
    assert act(table,mid,cid,answers)['status']=='COMMITTED'
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources['resource:core.qi']==99
    checks=[e for e in engine.events if e.event_type=='CHECK_ROLLED'
        and e.payload.get('check')=='Revealing Tone Cultivation Check']
    assert checks
    if not checks[-1].payload['success']:
        readings=information.readings(engine,engine.state.actors[OWNER])
        assert any(r['kind']=='concealment_exists' and r['details']=={} for r in readings)
        assert bell.private_revelation_locks(engine,engine.state.actors[OWNER])
