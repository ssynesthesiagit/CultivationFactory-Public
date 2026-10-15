"""Native map-owner environmental collection -> acquisition fixture -> play/replay."""
import pytest
from tests import r1i_service_support as s
from tests.test_mgr_t14_dust_family import P,place,cold


@pytest.mark.parametrize('scope,source_cl,size,dispersed',[
    ('both',17,30,True),('mundane',17,30,False),('both',1,30,False),('both',17,5,False)])
def test_native_map_particle_removal_scope_authority_and_whole_volume(monkeypatch,tmp_path,scope,source_cl,size,dispersed):
    from combat.tabletop import TabletopMapStore
    original=TabletopMapStore.save
    field={'id':'purifier','name':'Courtyard particle-removal field','shape':'sphere','x':4,'y':6,'z':0,
        'size_ft':size,'height_ft':30,'source_cl':source_cl,'save_dc':20,'check_bonus':60,
        'removes':['dust','smoke','airborne_particles'],'targets':scope,'duration_rounds':10,'cadence_rounds':1,
        'source_rule':'Removes the named particles in this sphere; cultivated fields contest once each round.'}
    def save(self,doc,*args,**kwargs):
        if doc.get('display_name')=='R1i Wide':doc={**doc,'world_sources':[field]}
        return original(self,doc,*args,**kwargs)
    monkeypatch.setattr(TabletopMapStore,'save',save)
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'dust_cloud'],wide=True)
    place(table,mid,'Dust Cloud',4,6);e=cold(tmp_path,mid)
    assert not any(z.active and P+'dust_cloud' in z.source_definition_id for z in e.state.zones.values())==dispersed
    from combat.observer_information import sources
    collected=[r for r in sources(e) if r['source']=='world:purifier']
    assert len(collected)==1 and collected[0]['cl']==source_cl
    checks=[v for v in e.events if v.event_type=='CHECK_ROLLED' and v.source_definition_id=='world:purifier']
    assert len(checks)==int(dispersed)


def test_world_profiles_require_native_owner_complete_input_and_expiry():
    from combat.observer_information import normalize_world_sources
    assert normalize_world_sources(None,8,8)==[]
    with pytest.raises(ValueError,match='complete'):
        normalize_world_sources([{'id':'invented','authority':'gm'}],8,8)
