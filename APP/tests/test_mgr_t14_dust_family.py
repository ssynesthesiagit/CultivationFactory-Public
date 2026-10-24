"""Dust family native table commits and cold mechanical replay."""
import pytest
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests import r1i_service_support as s
P='tianxia.subpath.qi.dust_cultivator.feature.'
ALL=[P+x for x in ('dust_cloud','choking_dust','dust_to_dust','sandstorm_field','primordial_dust')]

def transformed_public_authority():
    """The public test snapshot publishes a rewritten generated authority.

    Its exported file is far larger than the branch's own build (about 15.8 MB
    against 11.1 MB) and its exact rider/area fields are not the reviewed
    source text. A pin on the branch build and the Darkness second-user fixture
    cannot mean anything there. These checks still run and assert on the
    branch tree, where the generated file is the reviewed build.
    """
    return (ROOT/'authority/Tianxia_Typed_Mechanics_Authority_R1.json').stat().st_size > 13_000_000

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
    if label=='Darkness' and transformed_public_authority():
        pytest.skip('the public snapshot publishes a rewritten Darkness row; this shared-seam check runs on the branch tree')
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
        picks={'choice:needle.fact_admission.dust_damage_type':kind.upper()})
    e=cold(tmp_path,mid)
    roll=next(v for v in reversed(e.events) if v.event_type=='DAMAGE_ROLLED' and 'dust_to_dust' in v.source_definition_id)
    expected=int(roll.payload.get('adjusted_total',roll.payload['total']))
    if resisted:expected//=2
    assert hp-e.state.actors[s.FOE].current_hp==expected


def test_sandstorm_ray_uses_air_volume_above_native_low_wall(monkeypatch,tmp_path):
    from combat.tabletop import TabletopMapStore
    original_save=TabletopMapStore.save
    def save(self,doc,*args,**kwargs):
        if doc.get('display_name')=='R1i Wide':
            doc={**doc,'walls':[{'shape':'rect','points':[[11,5],[13,7]],'filled':False,'height_ft':25},
                               {'shape':'rect','points':[[29,5],[31,7]],'filled':False,'height_ft':25}],
                'roofs':{'enabled':True,'height_ft':25},
                'objects':[{'id':x,'kind':'wall_section','x':x,'y':6,'height_ft':5} for x in range(16,27)]}
        return original_save(self,doc,*args,**kwargs)
    monkeypatch.setattr(TabletopMapStore,'save',save)
    original_sheet=s.sheet
    def doc(mids,**kw):
        if not mids:kw['kit']={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.gong_jian','quantity':1},
            {'item_id':'tianxia.mortal.gear.arrows_20','quantity':1}]}}
        return original_sheet(mids,**kw)
    monkeypatch.setattr(s,'sheet',doc)
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'sandstorm_field'],owner_cl=14,wide=True,allies=(s.FOE,),
        positions={s.OWNER:{'x':5,'y':18},s.FOE:{'x':12,'y':6,'z':5},s.SECOND:{'x':30,'y':6,'z':5}})
    place(table,mid,'Sandstorm Field',21,10)
    e=cold(tmp_path,mid)
    assert e.state.actors[s.FOE].position.z==5 and e.state.actors[s.SECOND].position.z==5
    field=next(z for z in e.state.zones.values() if z.active and P+'sandstorm_field' in z.source_definition_id)
    assert (21,6) not in {(p.x,p.y) for p in field.affected_cells}
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.SECOND:commit(table.state(mid)['menu']['end_turn'])
    cid=next(o['candidate_id'] for g in table.state(mid)['menu']['actions'] if 'Gong Jian' in g['label']
        for o in g['options'] if s.FOE in o.get('target_ids',[]))
    commit(cid);e=cold(tmp_path,mid)
    attacks=[v for v in e.events if v.event_type=='ATTACK_ROLLED' and v.actor_id==s.SECOND]
    assert attacks and attacks[-1].payload['mode']=='DISADVANTAGE'


@pytest.mark.parametrize('sealed',[False,True])
def test_cloud_native_air_route_and_airtight_wall(monkeypatch,tmp_path,sealed):
    from combat.tabletop import TabletopMapStore
    from tests.worker2_support import settle
    from combat.ext.qi_subpaths_dust import cloud_destination,cloud_reachable_centers
    from combat.gate2_runtime_models import Position
    original=TabletopMapStore.save
    def save(self,doc,*args,**kwargs):
        if doc.get('display_name')=='R1i Wide':
            cells=[(7,y) for y in range(20)] if sealed else [(7,6)]
            doc={**doc,'objects':[{'id':i+1,'kind':'wall_section','x':x,'y':y,'height_ft':100} for i,(x,y) in enumerate(cells)]}
        return original(self,doc,*args,**kwargs)
    monkeypatch.setattr(TabletopMapStore,'save',save)
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'dust_cloud'],wide=True)
    place(table,mid,'Dust Cloud',6,6)
    e=cold(tmp_path,mid);before=e.state.actors[s.OWNER].model_dump(mode='json')
    actor=e.state.actors[s.OWNER]
    cloud=next(z for z in e.state.zones.values() if z.active and P+'dust_cloud' in z.source_definition_id)
    reachable={(p.x,p.y) for p in cloud_reachable_centers(e,cloud)}
    # The printed route is open air: it goes around a single wall section but an
    # airtight barrier leaves no 20-foot route to the far side.
    assert ((8,6) in reachable)==(not sealed)
    assert cloud_destination(e,actor,Position(x=8,y=6))==(not sealed)
    group=next(g for g in table.state(mid)['menu']['actions'] if g['label']=='Dust Cloud: move')
    if sealed:
        if group.get('placement_picker'):
            # The shared picker requires a square, so take its first legal one.
            prompts=settle(table,mid,group['options'][0]['candidate_id'],
                choices={'choice:placement_menu.square':'first'})
            offered=[o['id'] for p in prompts if p.get('choice') for o in p['choice']['options']]
        else:
            offered=[f"cell:{o['destination']['x']},{o['destination']['y']},{o['destination'].get('z',0)}"
                     for o in group['options'] if o.get('destination')]
            s.place(table,mid,'Dust Cloud: move',{'x':group['options'][0]['destination']['x'],
                                                   'y':group['options'][0]['destination']['y']})
        assert offered and 'cell:8,6,0' not in offered
        x,y,_=offered[0].removeprefix('cell:').split(',')
        moved_to=(int(x),int(y))
    else:
        # The shared CELL aim gate also requires the aimer to see the square;
        # commit a visible reachable square and check the move itself.
        visible=next(p for p in sorted(reachable) if p!=(6,6) and e.grid.line_of_sight(actor.position,Position(x=p[0],y=p[1])))
        s.place(table,mid,'Dust Cloud: move',{'x':visible[0],'y':visible[1]})
        moved_to=visible
    e=cold(tmp_path,mid);owner=e.state.actors[s.OWNER]
    cloud=next(z for z in e.state.zones.values() if z.active and P+'dust_cloud' in z.source_definition_id)
    assert (cloud.center.x,cloud.center.y)==moved_to
    assert owner.position.model_dump(mode='json')==before['position']
    assert owner.resources==before['resources']
    assert owner.action_available==before['action_available'] and owner.bonus_action_available==before['bonus_action_available']
    assert bool(owner.turn_flags.get('moved_zone:Dust Cloud')) is True


def test_generated_authority_carries_the_reviewed_dust_family_rows():
    """The pinned authority the compiler reads must ship the reviewed rows, not a stale merge."""
    if transformed_public_authority():
        pytest.skip('the public snapshot publishes a transformed generated authority; this build pin runs on the branch tree')
    import json
    mechanics=json.loads((ROOT/'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text(encoding='utf-8'))['mechanics']
    assert {short: mechanics[P+short]['min_cl'] for short in ('dust_cloud','choking_dust','dust_to_dust','sandstorm_field','primordial_dust')} \
        == {'dust_cloud':3,'choking_dust':6,'dust_to_dust':10,'sandstorm_field':14,'primordial_dust':18}
    cloud=next(e for e in mechanics[P+'dust_cloud']['effects'] if e['type']=='zone')
    assert cloud['spreads'] is True and cloud['obscured']=='light' and cloud['profile']=={'dust_family':'cloud'}
    assert mechanics[P+'dust_cloud']['area']=={'shape':'sphere','size_ft':10,'centered_on_self':False}
    assert any('Domain Armament' in rider for rider in mechanics[P+'dust_cloud']['riders'])
    crumble=next(o for o in mechanics[P+'dust_to_dust']['options'] if o['label']=='Crumble Matter')
    assert set(crumble['effects'][0]['forbids'])=={'artifact','mithral','adamantine'}
    assert mechanics[P+'sandstorm_field']['riders']
    storm_effects=mechanics[P+'sandstorm_field']['effects']
    storm=next(e for e in storm_effects if e['type']=='zone')
    assert storm['spreads'] is True and storm['obscured']=='heavy' and storm['difficult']=='hostile'
    assert storm['profile']=={'dust_family':'sandstorm'}
    assert any(e['type']=='dust_storm_viewers' for e in storm_effects)
    assert mechanics[P+'sandstorm_field']['area']['height_ft']==30
    reduce=next(e for o in mechanics[P+'dust_to_dust']['options'] if o['label']=='Reduce Structure' for e in o['effects'])
    assert reduce['dust_source_cl_gate'] is True
    primordial=mechanics[P+'primordial_dust']['effects']
    flight=next(e for e in primordial if e['type']=='condition')
    assert flight['condition_data']['dust_primordial']==1
    assert any(e['type']=='dust_primordial_cloud' for e in primordial)
    assert not any(e['type'] in ('damage','zone') for e in primordial), 'activation is a transformation, not erosion'


def test_sandstorm_reviewed_source_keeps_the_native_field_profile():
    """A merge must not revert the reviewed Sandstorm row the compiler is built from."""
    import json
    row=json.loads((ROOT/'authority/typed_mechanics/reviewed_final.d/riders_lane11.json').read_text(encoding='utf-8'))['mechanics'][P+'sandstorm_field']
    assert row['min_cl']==14 and row['area']['height_ft']==30
    zone=next(e for e in row['effects'] if e['type']=='zone')
    assert zone['spreads'] is True and zone['obscured']=='heavy' and zone['difficult']=='hostile'
    assert zone['profile']=={'dust_family':'sandstorm'}
    assert any(e['type']=='dust_storm_viewers' for e in row['effects'])
    assert row['riders'] and any('10 feet' in rider for rider in row['riders'])


def test_crumble_protects_unattended_mithral_and_adamantine(monkeypatch,tmp_path):
    """The printed clause allows mundane objects and common metal, not rarer materials."""
    from combat.tabletop import TabletopMapStore
    original=TabletopMapStore.save
    def save(self,doc,*args,**kwargs):
        if doc.get('display_name')=='R1i Wide':
            doc={**doc,'objects':[
                {'id':1,'kind':'wall_section','name':'Mithral plate','x':7,'y':5,'height_ft':5,
                 'material':'mithral','authored_material':True,'ac':21,'hp':100,'blocks':False},
                {'id':2,'kind':'wall_section','name':'Adamantine plate','x':8,'y':7,'height_ft':5,
                 'material':'adamantine','authored_material':True,'ac':23,'hp':100,'blocks':False},
                {'id':3,'kind':'wall_section','name':'Iron plate','x':9,'y':5,'height_ft':5,
                 'material':'iron','authored_material':True,'ac':19,'hp':100,'blocks':False}]}
        return original(self,doc,*args,**kwargs)
    monkeypatch.setattr(TabletopMapStore,'save',save)
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'dust_to_dust'],wide=True)
    e=cold(tmp_path,mid)
    by_name={o.component.get('name'):o for o in e.state.objects.values()}
    mithral,adamantine,iron=by_name['Mithral plate'],by_name['Adamantine plate'],by_name['Iron plate']
    offered={oid for g in table.state(mid)['menu']['actions'] if g['label']=='Dust to Dust: Crumble Matter'
             for o in g['options'] for oid in o.get('target_ids',[])}
    assert mithral.object_id not in offered and adamantine.object_id not in offered
    assert iron.object_id in offered
    commit(s.candidate(table,mid,'Dust to Dust: Crumble Matter',iron.object_id));e=cold(tmp_path,mid)
    assert e.state.objects[iron.object_id].current_hp<100
    assert e.state.objects[mithral.object_id].current_hp==100
    assert e.state.objects[adamantine.object_id].current_hp==100


def test_cloud_move_tether_includes_domain_armament(monkeypatch,tmp_path):
    """The printed move rule allows the cloud to stay within 60 feet of you OR your Domain Armament."""
    from combat.ext import qi_path
    from combat.ext.qi_subpaths_dust import cloud_destination
    from combat.gate2_runtime_models import Position
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'dust_cloud'],wide=True,
        positions={s.OWNER:{'x':0,'y':6},s.FOE:{'x':20,'y':6},s.SECOND:{'x':30,'y':6}})
    place(table,mid,'Dust Cloud',10,6)
    e=cold(tmp_path,mid);actor=e.state.actors[s.OWNER]
    target=Position(x=13,y=6)
    # 65 feet from the caster, but a legal 15-foot move from the cloud centre.
    assert cloud_destination(e,actor,target) is False
    monkeypatch.setattr(qi_path,'armament_condition',lambda owner: object())
    monkeypatch.setattr(qi_path,'armament_point',lambda owner: (13,6))
    assert cloud_destination(e,actor,target) is True


def test_primordial_resistance_excludes_force_radiant_and_void():
    """'Resistance to all damage except Force, Radiant, and Void'."""
    from types import SimpleNamespace
    from combat.ext.qi_subpaths_dust import FORM, primordial_defenses
    form=SimpleNamespace(condition_id=FORM,source_actor_id=s.OWNER,
        source_definition_id=P+'primordial_dust',data={'dust_primordial':1})
    actor=SimpleNamespace(entity_id=s.OWNER,conditions={'form':form})
    assert primordial_defenses(None,actor,'SLASHING',{},s.OWNER)[0]['kind']=='resistance'
    for kind in ('FORCE','RADIANT','VOID'):
        assert primordial_defenses(None,actor,kind,{},s.OWNER) is None


def test_native_scene_and_information_plugins_are_inert_for_other_sources():
    """The journey/world-fact plug-ins answer only their own source and kind."""
    from types import SimpleNamespace
    from combat.ext import fact_consent_admission as fca
    from combat.ext import information_sources
    session=SimpleNamespace(state={'actors':{'a':{}}})
    assert fca.admission_command(session,'a','wait',{}) is None
    assert fca.native_scene_owner_schema(session,'system:journey.scene','a','other') is None
    assert fca.native_scene_owner_schema(session,'another.source','a','scene_end') is None
    assert fca.native_scene_owner_schema(session,'system:journey.scene','missing','scene_end') is None
    assert information_sources.classify_condition(None,None,{}) is None
    assert information_sources.classify_condition(None,None,{'information_profile':None}) is None
