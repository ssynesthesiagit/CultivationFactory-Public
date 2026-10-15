"""Dust family native table commits and cold mechanical replay."""
import pytest
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests import r1i_service_support as s
P='tianxia.subpath.qi.dust_cultivator.feature.'
ALL=[P+x for x in ('dust_cloud','choking_dust','dust_to_dust','sandstorm_field','primordial_dust')]

def cold(tmp,mid):
    session=CombatService(ROOT,tmp)._load_session(mid)
    assert session.verify()['status']=='PASS'
    assert session.mechanical.replay()['status']=='PASS'
    return session.engine

def place(table,mid,label,x,y):
    from combat.placement_menu import CHOICE
    from combat.gate2_runtime_models import Position
    from combat.ext.needle import cell_id
    from tests.worker2_support import settle
    group=next(g for g in table.state(mid)['menu']['actions'] if g['label']==label)
    root=group['options'][0]['candidate_id']
    return settle(table,mid,root,picks={CHOICE:cell_id(Position(x=x,y=y),include_altitude=True)})

def advance(table,mid,commit):
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.OWNER:commit(table.state(mid)['menu']['end_turn'])

def test_primordial_activation_is_self_transformation_not_erosion(tmp_path):
    combat,table,mid,send,commit=s.fixture(tmp_path,ALL,owner_cl=18,wide=True)
    commit(s.candidate(table,mid,'Primordial Dust'));e=cold(tmp_path,mid)
    assert all(a.current_hp==500 for a in e.state.actors.values())
    assert not any(c.condition_id=='condition:typed.blinded' for a in e.state.actors.values() for c in a.conditions.values())
    assert e.state.actors[s.OWNER].resources['resource:core.qi']==22
    assert not any(z.active and 'primordial_dust' in z.source_definition_id for z in e.state.zones.values())

def test_primordial_upgrades_existing_cloud_and_free_choking(tmp_path):
    combat,table,mid,send,commit=s.fixture(tmp_path,ALL,owner_cl=18,wide=True)
    place(table,mid,'Dust Cloud',4,6);advance(table,mid,commit)
    commit(s.candidate(table,mid,'Primordial Dust'));e=cold(tmp_path,mid)
    cloud=next(z for z in e.state.zones.values() if z.active and P+'dust_cloud' in z.source_definition_id)
    assert cloud.center==e.state.actors[s.OWNER].position
    assert cloud.trigger_profile['size_ft']==20 and not cloud.concentration_link
    advance(table,mid,commit)
    before=cold(tmp_path,mid).state.actors[s.OWNER].resources['resource:core.qi']
    commit(s.candidate(table,mid,'Primordial Dust: Choking Dust: Eroding Mode (free)',s.FOE));e=cold(tmp_path,mid)
    assert e.state.actors[s.OWNER].resources['resource:core.qi']==before
    assert e.state.actors[s.FOE].current_hp<500


def test_dust_to_dust_can_reduce_construct(monkeypatch,tmp_path):
    original=s.sheet
    def doc(mids,**kw):
        row=original(mids,**kw)
        if not mids:row['identity']['creature_type']='construct'
        return row
    monkeypatch.setattr(s,'sheet',doc)
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'dust_to_dust'],owner_cl=17)
    commit(s.candidate(table,mid,'Dust to Dust: Reduce Structure (Construct)',s.FOE));e=cold(tmp_path,mid)
    assert e.state.actors[s.FOE].current_hp<500
    roll=next(v for v in e.events if v.event_type=='DAMAGE_ROLLED' and 'dust_to_dust' in v.source_definition_id)
    assert len(roll.payload['dice'])==8
    from combat.fact_consent_admission import combat_records
    records=combat_records(e,e.state.actors[s.OWNER],source=P+'dust_to_dust',kind='dust_damage_type')
    assert len(records)==1 and records[0]['authority']==s.OWNER
    assert not combat_records(e,e.state.actors[s.FOE],kind='dust_damage_type')

@pytest.mark.parametrize('dc,penalty',[(50,-2),(1,-1)])
def test_erode_defense_source_clock(tmp_path,dc,penalty):
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'dust_to_dust'],owner_dc=dc)
    commit(s.candidate(table,mid,'Dust to Dust: Erode Defense',s.FOE));e=cold(tmp_path,mid)
    mods=[m for m in e.state.actors[s.FOE].modifiers.values() if m.target_field=='armor_class']
    assert len(mods)==1 and mods[0].value==penalty
    assert mods[0].expires_on=='START_OF_SOURCE_NEXT_TURN'
    advance(table,mid,commit)
    assert not any(m.target_field=='armor_class' for m in cold(tmp_path,mid).state.actors[s.FOE].modifiers.values())

def test_sandstorm_creation_asks_chosen_allies_without_entry_damage(tmp_path):
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'sandstorm_field'],owner_cl=14,wide=True,allies=(s.SECOND,))
    prompts=place(table,mid,'Sandstorm Field',4,6)
    assert any('see normally' in str(p) for p in prompts)
    e=cold(tmp_path,mid)
    assert all(a.current_hp==500 for a in e.state.actors.values())
    field=next(z for z in e.state.zones.values() if z.active and 'sandstorm_field' in z.source_definition_id)
    assert field.trigger_profile['shape']=='cylinder' and field.trigger_profile['height_ft']==30
    assert field.trigger_profile['obscured']=='heavy' and field.trigger_profile['difficult']=='hostile'


def test_sandstorm_ranged_ray_between_outside_endpoints(monkeypatch,tmp_path):
    original=s.sheet
    def doc(mids,**kw):
        if not mids:
            kw['kit']={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.gong_jian','quantity':1},{'item_id':'tianxia.mortal.gear.arrows_20','quantity':1}]}}
        return original(mids,**kw)
    monkeypatch.setattr(s,'sheet',doc)
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'sandstorm_field'],owner_cl=14,wide=True,
        positions={s.OWNER:{'x':3,'y':6},s.FOE:{'x':15,'y':6},s.SECOND:{'x':30,'y':6}})
    place(table,mid,'Sandstorm Field',21,6)
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.SECOND:commit(table.state(mid)['menu']['end_turn'])
    cid=next(o['candidate_id'] for g in table.state(mid)['menu']['actions'] if 'Gong Jian' in g['label']
        for o in g['options'] if s.OWNER in o.get('target_ids',[]))
    commit(cid);e=cold(tmp_path,mid)
    rolled=[v for v in e.events if v.event_type=='ATTACK_ROLLED' and v.actor_id==s.SECOND]
    assert rolled and rolled[-1].payload['mode']=='DISADVANTAGE'


def test_without_dust_ownership_default_inert(tmp_path):
    combat,table,mid,send,commit=s.fixture(tmp_path,[],owner_cl=18,wide=True)
    assert not any('Dust' in g['label'] or 'Sandstorm' in g['label'] for g in table.state(mid)['menu']['actions'])
    commit(table.state(mid)['menu']['end_turn'])
    e=cold(tmp_path,mid)
    assert not any('dust_cultivator' in c.source_definition_id for a in e.state.actors.values() for c in a.conditions.values())


@pytest.mark.parametrize('own_cloud',[True,False])
def test_cloud_save_penalty_is_activation_and_source_scoped(tmp_path,own_cloud):
    talents=[P+'choking_dust']+([P+'dust_cloud'] if own_cloud else [])
    combat,table,mid,send,commit=s.fixture(tmp_path,talents,wide=True,
        second_talents=() if own_cloud else (P+'dust_cloud',),allies=(s.SECOND,))
    if not own_cloud:
        commit(table.state(mid)['menu']['end_turn'])
        while table.state(mid)['menu']['actor_id']!=s.SECOND:commit(table.state(mid)['menu']['end_turn'])
    place(table,mid,'Dust Cloud',4,6)
    if not own_cloud:
        commit(table.state(mid)['menu']['end_turn'])
        while table.state(mid)['menu']['actor_id']!=s.OWNER:commit(table.state(mid)['menu']['end_turn'])
    commit(s.candidate(table,mid,'Choking Dust: Choking Mode',s.FOE));e=cold(tmp_path,mid)
    penalties=[v for v in e.events if v.event_type=='DAMAGE_ROLLED' and 'DUST_CLOUD_PENALTY' in str(v.payload.get('reason'))]
    assert len(penalties)==int(own_cloud)


def test_sandstorm_start_trigger_and_holder_expiry(tmp_path):
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'sandstorm_field'],owner_cl=14,wide=True)
    place(table,mid,'Sandstorm Field',10,6)
    assert cold(tmp_path,mid).state.actors[s.FOE].current_hp==500
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.FOE:commit(table.state(mid)['menu']['end_turn'])
    e=cold(tmp_path,mid);foe=e.state.actors[s.FOE]
    assert foe.current_hp<500
    blind=next(c for c in foe.conditions.values() if c.condition_id=='condition:typed.blinded')
    from combat.ext.effect_durations import parse
    assert parse(blind.expires_on)==('start',s.FOE,foe.turns_started+1)


def test_cloud_detail_cap_preserves_normal_targeting_and_effect(tmp_path):
    from combat import zones,targeting
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'dust_cloud'],wide=True,
        positions={s.OWNER:{'x':3,'y':6},s.FOE:{'x':6,'y':6},s.SECOND:{'x':9,'y':6}})
    place(table,mid,'Dust Cloud',7,6);e=cold(tmp_path,mid)
    viewer,target=e.state.actors[s.FOE],e.state.actors[s.SECOND]
    assert zones.hidden_from(e,viewer,target,sight_only=True)
    assert not zones.hidden_from(e,viewer,target)
    assert targeting.line_of_effect(e,viewer,target=target)
    assert not zones.hidden_from(e,e.state.actors[s.OWNER],target,sight_only=True)
    from combat.observer_information import sources
    profiles=[row for row in sources(e) if row.get('zone') and P+'dust_cloud' in row['source']]
    assert len(profiles)==1 and profiles[0]['cl']==17


def test_crumble_rejects_native_cultivated_glass_and_reduce_can_hit_it(tmp_path):
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'dust_to_dust'],wide=True,
        foe_talents=('TAL_GLASS_RAISED_PANE_SCRIPTURE',))
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.FOE:commit(table.state(mid)['menu']['end_turn'])
    place(table,mid,'Raised Pane Scripture',0,6)
    e=cold(tmp_path,mid)
    pane=next(o for o in e.state.objects.values() if o.object_kind=='GLASS_PANE')
    before=pane.current_hp
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.OWNER:commit(table.state(mid)['menu']['end_turn'])
    assert not any(pane.object_id in o.get('target_ids',[]) for g in table.state(mid)['menu']['actions']
        if g['label']=='Dust to Dust: Crumble Matter' for o in g['options'])
    commit(s.candidate(table,mid,'Dust to Dust: Reduce Structure',pane.object_id))
    assert cold(tmp_path,mid).state.objects[pane.object_id].current_hp<before


@pytest.mark.parametrize('foe_cl,held',[(17,False),(19,True)])
def test_primordial_native_physical_grapple_source_cl(monkeypatch,tmp_path,foe_cl,held):
    original=s.sheet
    def doc(mids,**kw):
        if not mids:kw['cl']=foe_cl
        return original(mids,**kw)
    monkeypatch.setattr(s,'sheet',doc)
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'primordial_dust'],owner_cl=18,foe_score=40)
    commit(s.candidate(table,mid,'Primordial Dust'))
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.FOE:commit(table.state(mid)['menu']['end_turn'])
    commit(s.candidate(table,mid,'Grapple',s.OWNER));e=cold(tmp_path,mid)
    assert any(v.event_type=='SAVE_ROLLED' and v.actor_id==s.OWNER for v in e.events)
    assert any(c.condition_id=='condition:typed.grappled' for c in e.state.actors[s.OWNER].conditions.values())==held


def connected_air_geometry(monkeypatch,tmp_path,sealed,source,label):
    from combat.tabletop import TabletopMapStore
    original=TabletopMapStore.save
    def save(self,doc,*args,**kwargs):
        if doc.get('display_name')=='R1i Wide':
            positions=[(7,6),(6,5),(5,6)]+([(6,7)] if sealed else [])
            objects=[{'id':i+1,'kind':'wall_section','x':x,'y':y,'height_ft':100} for i,(x,y) in enumerate(positions)]
            doc={**doc,'objects':objects}
        return original(self,doc,*args,**kwargs)
    monkeypatch.setattr(TabletopMapStore,'save',save)
    combat,table,mid,send,commit=s.fixture(tmp_path,[source],wide=True,
        positions={s.OWNER:{'x':6,'y':6},s.FOE:{'x':7,'y':7},s.SECOND:{'x':10,'y':6}})
    place(table,mid,label,6,6);e=cold(tmp_path,mid)
    cloud=next(z for z in e.state.zones.values() if z.active and source in z.source_definition_id)
    assert cloud.trigger_profile.get('spreads') is True
    assert ((7,7) in {(p.x,p.y) for p in cloud.affected_cells}) == (not sealed)
    from combat import zones
    assert zones._inside(e,e.state.actors[s.FOE],cloud)==(not sealed)


@pytest.mark.parametrize('sealed',[False,True])
def test_dust_cloud_native_connected_air_geometry(monkeypatch,tmp_path,sealed):
    connected_air_geometry(monkeypatch,tmp_path,sealed,P+'dust_cloud','Dust Cloud')


@pytest.mark.parametrize('sealed',[False,True])
def test_shared_spreading_geometry_has_native_darkness_second_user(monkeypatch,tmp_path,sealed):
    connected_air_geometry(monkeypatch,tmp_path,sealed,'DARK_BASE_DARKNESS','Darkness')


def test_primordial_transformation_releases_existing_native_grapple(tmp_path):
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'primordial_dust'],owner_cl=18,foe_score=40)
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.FOE:commit(table.state(mid)['menu']['end_turn'])
    commit(s.candidate(table,mid,'Grapple',s.OWNER))
    assert any(c.condition_id=='condition:typed.grappled' for c in cold(tmp_path,mid).state.actors[s.OWNER].conditions.values())
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.OWNER:commit(table.state(mid)['menu']['end_turn'])
    commit(s.candidate(table,mid,'Primordial Dust'));e=cold(tmp_path,mid)
    assert not any(c.condition_id=='condition:typed.grappled' for c in e.state.actors[s.OWNER].conditions.values())


def test_crumble_native_mundane_section_one_packet_and_permanent_opening(monkeypatch,tmp_path):
    from combat.tabletop import TabletopMapStore
    original=TabletopMapStore.save
    def save(self,doc,*args,**kwargs):
        if doc.get('display_name')=='R1i Wide':
            doc={**doc,'objects':[{'id':1,'kind':'wall_section','name':'Five-foot wooden section',
                'x':7,'y':6,'height_ft':5,'material':'earth','authored_material':True,'ac':10,'hp':40,'threshold':99,'resist':['FORCE']}]}
        return original(self,doc,*args,**kwargs)
    monkeypatch.setattr(TabletopMapStore,'save',save)
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'dust_to_dust'],wide=True)
    e=cold(tmp_path,mid);obj=next(o for o in e.state.objects.values() if o.component.get('name')=='Five-foot wooden section')
    assert (7,6) in e.grid.blocked
    assert obj.component['material']=='earth'
    commit(s.candidate(table,mid,'Dust to Dust: Crumble Matter',obj.object_id));e=cold(tmp_path,mid)
    records=[v for v in e.events if v.event_type=='OBJECT_UPDATED' and v.target_ids==(obj.object_id,) and 'damage' in v.payload]
    assert len(records)==1 and records[0].payload['damage']['taken']==40
    assert e.state.objects[obj.object_id].destroyed and (7,6) not in e.grid.blocked
    advance(table,mid,commit)
    assert cold(tmp_path,mid).state.objects[obj.object_id].destroyed


@pytest.mark.parametrize('material',['earth','brick'])
def test_native_authored_material_requires_durability_and_roundtrips(material):
    from combat.tabletop import _objects,TabletopError
    row={'id':1,'kind':'custom','x':1,'y':1,'material':material,'authored_material':True,'ac':10,'hp':40}
    normalized=_objects([row],8,8)
    assert normalized[0]['material']==material
    assert _objects(normalized,8,8)==normalized
    with pytest.raises(TabletopError,match='Armor Class and Hit Points'):
        _objects([{k:v for k,v in row.items() if k!='hp'}],8,8)
    legacy={k:v for k,v in row.items() if k!='authored_material'}
    assert 'material' not in _objects([legacy],8,8)[0]


def test_single_cloud_replacement_releases_its_old_concentration(tmp_path):
    from combat import concentration
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'dust_cloud'],wide=True)
    place(table,mid,'Dust Cloud',4,6);e=cold(tmp_path,mid)
    old=next(z for z in e.state.zones.values() if z.active and P+'dust_cloud' in z.source_definition_id)
    advance(table,mid,commit)
    place(table,mid,'Dust Cloud',5,6);e=cold(tmp_path,mid)
    assert not e.state.zones[old.zone_id].active
    assert len([z for z in e.state.zones.values() if z.active and P+'dust_cloud' in z.source_definition_id])==1
    assert len([source for source in concentration.sources(e.state.actors[s.OWNER]) if P+'dust_cloud' in source])==1


def test_crumble_cannot_misclassify_native_formation_eye_as_mundane(monkeypatch,tmp_path):
    from combat.ext import formations
    original=s.sheet
    def doc(mids,**kw):
        if formations.BASE_SET in mids:kw['cl']=3
        return original(mids,**kw)
    monkeypatch.setattr(s,'sheet',doc)
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'dust_to_dust'],wide=True,
        foe_talents=(formations.BASE_SET,))
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.FOE:commit(table.state(mid)['menu']['end_turn'])
    place(table,mid,'Combat Array: Locking Gate',7,6)
    e=cold(tmp_path,mid);array=next(z for z in formations.arrays(e,s.FOE))
    eye=e.state.objects[formations.record(array)['eye']]
    assert formations.record(array)['cl']==3
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.OWNER:commit(table.state(mid)['menu']['end_turn'])
    assert not any(eye.object_id in o.get('target_ids',[]) for g in table.state(mid)['menu']['actions']
                   if g['label']=='Dust to Dust: Crumble Matter' for o in g['options'])
    commit(s.candidate(table,mid,'Dust to Dust: Reduce Structure',eye.object_id));e=cold(tmp_path,mid)
    assert e.state.objects[eye.object_id].current_hp<eye.current_hp
    assert not e.state.zones[array.zone_id].active


@pytest.mark.parametrize('foe_cl,kind,resisted',[(18,'necrotic',False),(19,'necrotic',True),(19,'force',False)])
def test_reduce_construct_native_source_cl_and_primordial_defenses(monkeypatch,tmp_path,foe_cl,kind,resisted):
    from tests.worker2_support import settle
    original=s.sheet
    def doc(mids,**kw):
        if P+'primordial_dust' in mids:
            kw['cl']=foe_cl
            result=original(mids,**kw)
            result['identity']['creature_type']='construct'
            return result
        return original(mids,**kw)
    monkeypatch.setattr(s,'sheet',doc)
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'dust_to_dust'],owner_cl=18,
        foe_talents=(P+'primordial_dust',))
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.FOE:commit(table.state(mid)['menu']['end_turn'])
    commit(s.candidate(table,mid,'Primordial Dust'))
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.OWNER:commit(table.state(mid)['menu']['end_turn'])
    hp=cold(tmp_path,mid).state.actors[s.FOE].current_hp
    settle(table,mid,s.candidate(table,mid,'Dust to Dust: Reduce Structure (Construct)',s.FOE),
        picks={'choice:needle.fact_admission.dust_damage_type':kind})
    e=cold(tmp_path,mid)
    roll=next(v for v in reversed(e.events) if v.event_type=='DAMAGE_ROLLED' and 'dust_to_dust' in v.source_definition_id)
    expected=int(roll.payload.get('adjusted_total',roll.payload['total']))
    if resisted:expected//=2
    assert hp-e.state.actors[s.FOE].current_hp==expected
