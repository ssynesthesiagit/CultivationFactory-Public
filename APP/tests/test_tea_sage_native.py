"""Native table learning -> actual preparation -> commit -> cold replay."""
import json
import zipfile
import pytest
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
SCHOOL='tianxia.subpath.qi.tea_sage_cultivator'
INF=SCHOOL+'.feature.precision_infusions'
KEY='tea_sage:preparations'
PID='0badc0de-0000-4000-8000-000000000083'
A=FACTORY_ACTOR_PREFIX+PID
FORMULAS=['cleansing_bitterleaf','still_mind_jasmine','cloud_step_green_tea']


def game(tmp_path,cl=3,acquire=True):
    doc=sheet([],cl=cl)
    doc['identity']['path_ids']=['tianxia.path.qi_cultivation']
    doc['path_and_subpath']={'path_record_ids':['tianxia.path.qi_cultivation']}
    folder=tmp_path/'portable_characters'/PID;folder.mkdir(parents=True)
    with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    def cold():return CombatService(ROOT,tmp_path)
    table=TabletopService(cold(),tmp_path)
    if acquire:table.add_advancement(PID,'subpath',SCHOOL)
    svc=cold();svc.tabletop_maps.save({'map_id':'tea-yard','display_name':'Tea yard','width_squares':12,'height_squares':12,
        'walls':[],'starts':{'team1':[[2,2]],'team2':[[8,8]]}})
    state=svc.create_journey(project_ids=[PID],arena_id='battlefield:map.tea-yard',positions={A:{'x':2,'y':2}},base_paces={A:5})
    jid=state['journey_id']
    def act(kind,payload):
        before=cold().journey_state(jid);cold().journey_act(jid,before['revision'],A,kind,payload)
        assert cold().journey_verify(jid)['status']=='PASS'
        return cold().journey_state(jid)
    def world(source,kind,scope,value):
        before=cold().journey_state(jid)
        cold().journey_world_fact(jid,before['revision'],{'source':source,'subject':A,'kind':kind,'scope':scope,'value':value,
            'expires_at':before['seconds']+(1 if source=='system:journey.admission' else 100000),'readers':[]})
        assert cold().journey_verify(jid)['status']=='PASS'
    return cold,table,jid,act,world


def prepare(cold,jid,act,world):
    state=act('tea_formulas',{'formulas':FORMULAS})
    for sid,role in [('water','potable_water'),('pot','tea_implement')]:
        world('system:journey.admission','material_source',sid,{'payload':{'id':sid,'name':sid,'kind':'raw_material','context':'scene',
            'material':'water' if sid=='water' else 'ceramic','unit':'portion','quantity':1,'known_to':[A]},'provenance':'Actual table supply '+sid})
        act('collect_material',{'source':sid,'quantity':1})
        world(INF,'preparation_material',sid+':1',{'holding':sid+':1','role':role,'description':'Actual '+role})
    pb=state['actors'][A]['bundle']['tea_sage']['numbers']['pb']
    return {'water':'water:1','implement':'pot:1','materials':[],
        'cups':[{'drinker':A,'formula':FORMULAS[i%3],'serving':'sealed leaf packet'} for i in range(pb)]}


def test_native_preparation_cost_time_identity_expiry_reload(tmp_path):
    cold,table,jid,act,world=game(tmp_path)
    assert INF in cold()._factory_owner_sheet(PID)['path_and_subpath']['path_feature_record_ids']
    params=prepare(cold,jid,act,world)
    qi=cold().journey_state(jid)['actors'][A]['resources']['resource:core.qi']
    state=act('activity_start',{'source':INF,'parameters':params})
    assert state['actors'][A]['resources']['resource:core.qi']==qi-1
    assert not state['actors'][A]['source_states'][KEY].get('cups')
    state=act('activity_work',{'seconds':599})
    assert not state['actors'][A]['source_states'][KEY].get('cups')
    state=act('activity_work',{'seconds':1});cups=state['actors'][A]['source_states'][KEY]['cups']
    assert len(cups)==len(params['cups'])
    assert all(c['maker']==A and c['carrier']==A and c['drinker']==A and c['expires_at']==29400 for c in cups.values())
    state=act('wait',{'seconds':28799});assert len(state['actors'][A]['source_states'][KEY]['cups'])==len(cups)
    state=act('wait',{'seconds':1});assert not state['actors'][A]['source_states'][KEY]['cups']


def test_native_preparation_interruption_no_cups_or_refund(tmp_path):
    cold,table,jid,act,world=game(tmp_path);params=prepare(cold,jid,act,world)
    qi=cold().journey_state(jid)['actors'][A]['resources']['resource:core.qi']
    act('activity_start',{'source':INF,'parameters':params});act('activity_work',{'seconds':300})
    state=act('wait',{'seconds':1})
    assert not state['actors'][A]['source_states'][KEY].get('cups')
    assert state['actors'][A]['resources']['resource:core.qi']==qi-1
    with pytest.raises(ValueError):act('activity_work',{'seconds':300})


def test_wrong_owner_default_inert_and_rollback(tmp_path):
    cold,table,jid,act,world=game(tmp_path,acquire=False);before=cold().journey_state(jid)
    with pytest.raises(ValueError):act('tea_formulas',{'formulas':FORMULAS})
    assert cold().journey_state(jid)==before
    with pytest.raises(ValueError):act('activity_start',{'source':INF,'parameters':{}})
    assert cold().journey_state(jid)==before


@pytest.mark.parametrize('cl,expected',[(3,1),(6,2),(10,3),(14,4),(18,5)])
def test_native_open_school_progression(tmp_path,cl,expected):
    cold,table,jid,act,world=game(tmp_path,cl=cl)
    ids=cold()._factory_owner_sheet(PID)['path_and_subpath']['path_feature_record_ids']
    assert len([f for f in ids if f.startswith(SCHOOL+'.feature.')])==expected
