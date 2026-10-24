"""Map-owner Source CL -> real object option/damage -> commit and cold replay."""
import pytest
from tests import r1i_service_support as s
from tests.test_mgr_t14_dust_family import P,cold


@pytest.mark.parametrize('source_cl,artifact,crumble,bypass',[
    (0,False,True,True),(18,False,False,True),(19,False,False,False),(None,True,False,False)])
def test_native_collected_object_source_controls_dust_eligibility_and_defenses(monkeypatch,tmp_path,source_cl,artifact,crumble,bypass):
    from combat.tabletop import TabletopMapStore
    original=TabletopMapStore.save
    profile={'id':1,'kind':'wall_section','name':'Collected earth section','x':7,'y':6,
        'material':'earth','authored_material':True,'ac':10,'hp':500,'height_ft':5,
        'threshold':99,'resist':['FORCE'],'artifact':artifact}
    if source_cl is not None:profile['source_cl']=source_cl
    def save(self,doc,*args,**kw):
        if doc.get('display_name')=='R1i Wide':doc={**doc,'objects':[profile]}
        return original(self,doc,*args,**kw)
    monkeypatch.setattr(TabletopMapStore,'save',save)
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'dust_to_dust'],owner_cl=18,wide=True)
    e=cold(tmp_path,mid);obj=e.state.objects['object:map.1']
    offered=any(obj.object_id in o.get('target_ids',[]) for g in table.state(mid)['menu']['actions']
        if g['label']=='Dust to Dust: Crumble Matter' for o in g['options'])
    commit(s.candidate(table,mid,'Dust to Dust: Reduce Structure',obj.object_id))
    e=cold(tmp_path,mid)
    packets=[v for v in e.events if v.event_type=='OBJECT_UPDATED' and obj.object_id in v.target_ids and 'damage' in v.payload]
    assert len(packets)==1
    assert (packets[0].payload['damage']['taken']>0)==bypass
    assert offered==crumble
    collected=combat.tabletop_maps.get('r1i-wide')
    if source_cl is not None:
        assert collected['objects'][0]['source_cl']==source_cl
        assert e.state.objects[obj.object_id].component['source_cl']==source_cl
    else:
        assert 'source_cl' not in e.state.objects[obj.object_id].component


@pytest.mark.parametrize('cl',[-1,True,1.5,'18'])
def test_map_rejects_unvalidated_object_authority(tmp_path,cl):
    from combat.tabletop import TabletopMapStore,TabletopError
    with pytest.raises(TabletopError,match='Source CL'):
        TabletopMapStore(tmp_path).save({'display_name':'Bad source','width_squares':8,'height_squares':8,
            'walls':[],'terrain':[],'starts':{'team1':[[1,1]],'team2':[[6,6]]},
            'objects':[{'id':1,'kind':'wall_section','x':4,'y':4,'source_cl':cl}]})
