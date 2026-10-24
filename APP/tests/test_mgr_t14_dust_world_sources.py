"""Native map-owner environmental collection -> acquisition fixture -> play/replay."""
import pytest
from tests import r1i_service_support as s
from tests.test_mgr_t14_dust_family import P,place,cold


@pytest.mark.parametrize('scope,source_cl,size,particles,dispersed',[
    ('both',17,30,['dust'],True),('mundane',17,30,['dust'],False),
    ('both',1,30,['dust'],False),('both',17,5,['dust'],False),('both',17,30,['smoke'],True)])
def test_native_map_particle_removal_scope_authority_and_whole_volume(monkeypatch,tmp_path,scope,source_cl,size,particles,dispersed):
    from combat.tabletop import TabletopMapStore
    original=TabletopMapStore.save
    field={'id':'purifier','name':'Courtyard particle-removal field','shape':'sphere','x':4,'y':6,'z':0,
        'size_ft':size,'height_ft':30,'source_cl':source_cl,'save_dc':20,'check_bonus':60,
        'removes':particles,'targets':scope,'duration_rounds':10,'cadence_rounds':1,
        'source_rule':'Removes the named particles in this sphere; cultivated fields contest once each round.'}
    def save(self,doc,*args,**kwargs):
        if doc.get('display_name')=='R1i Wide':doc={**doc,'world_sources':[field]}
        return original(self,doc,*args,**kwargs)
    monkeypatch.setattr(TabletopMapStore,'save',save)
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'dust_cloud'],wide=True)
    place(table,mid,'Dust Cloud',4,6);e=cold(tmp_path,mid)
    assert (not any(z.active and P+'dust_cloud' in z.source_definition_id for z in e.state.zones.values()))==dispersed
    from combat.observer_information import sources
    collected=[r for r in sources(e) if r['source']=='world:purifier']
    assert len(collected)==1 and collected[0]['cl']==source_cl
    checks=[v for v in e.events if v.event_type=='CHECK_ROLLED' and v.source_definition_id=='world:purifier']
    assert len(checks)==int(dispersed)
    if dispersed:
        from combat.concentration import sources as concentrations
        assert not any(P+'dust_cloud' in src for src in concentrations(e.state.actors[s.OWNER]))


def test_world_profiles_require_native_owner_complete_input():
    from combat.observer_information import normalize_world_sources
    assert normalize_world_sources(None,8,8)==[]
    with pytest.raises(ValueError,match='complete'):
        normalize_world_sources([{'id':'invented','authority':'gm'}],8,8)


def test_sandstorm_selects_known_ally_without_locating_them(monkeypatch,tmp_path):
    from combat.tabletop import TabletopMapStore
    from combat.target_knowledge import located
    from combat.ext.needle import CHOICE,cell_id
    from tests.worker2_support import settle
    from combat.placement_menu import CHOICE as PLACE
    from combat.gate2_runtime_models import Position
    original=TabletopMapStore.save
    def save(self,doc,*args,**kwargs):
        if doc.get('display_name')=='R1i Wide':
            doc={**doc,'objects':[{'id':1,'kind':'wall_section','x':8,'y':6,'height_ft':100}]}
        return original(self,doc,*args,**kwargs)
    monkeypatch.setattr(TabletopMapStore,'save',save)
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'sandstorm_field'],owner_cl=14,wide=True,allies=(s.SECOND,),
        positions={s.OWNER:{'x':3,'y':6},s.FOE:{'x':4,'y':6},s.SECOND:{'x':15,'y':6}})
    e=cold(tmp_path,mid)
    assert not located(e,e.state.actors[s.OWNER],e.state.actors[s.SECOND])
    cid=next(g['options'][0]['candidate_id'] for g in table.state(mid)['menu']['actions'] if g['label']=='Sandstorm Field')
    prompts=settle(table,mid,cid,picks={PLACE:cell_id(Position(x=3,y=6),include_altitude=True),CHOICE+'dust_storm_allies':[s.SECOND]})
    choice=next(p['choice'] for p in prompts if p.get('choice') and any(o['id']==s.SECOND for o in p['choice']['options']))
    option=next(o for o in choice['options'] if o['id']==s.SECOND)
    assert not any(k in option for k in ('position','x','y','z'))
    e=cold(tmp_path,mid)
    field=next(z for z in e.state.zones.values() if z.active and 'sandstorm_field' in z.source_definition_id)
    assert s.SECOND in field.trigger_profile['dust_viewers']
    from combat import zones
    assert zones.obscurement_ignored(e,field,e.state.actors[s.SECOND],e.state.actors[s.FOE])
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.SECOND:commit(table.state(mid)['menu']['end_turn'])
    commit(s.candidate(table,mid,'Dash'))
    e=combat._load_session(mid).engine
    move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination
        and (c.destination.x,c.destination.y,c.destination.z)==(8,7,0))
    commit(move.candidate_id);e=cold(tmp_path,mid)
    field=next(z for z in e.state.zones.values() if z.active and 'sandstorm_field' in z.source_definition_id)
    assert zones._inside(e,e.state.actors[s.SECOND],field)
    assert not zones.hidden_from(e,e.state.actors[s.SECOND],e.state.actors[s.FOE])
