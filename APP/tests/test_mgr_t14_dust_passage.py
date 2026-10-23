"""Native authored cracks, particle movement and turn-end settlement."""
import pytest
from tests import r1i_service_support as s
from tests.test_mgr_t14_dust_family import P,cold,transformed_public_authority


def movements(table,mid):
    return table.state(mid)['menu'].get('movement',[])


@pytest.mark.parametrize('width,form,allowed',[(1000,True,True),(999,True,False),(1000,False,False)])
def test_authored_opening_has_exact_width_and_requires_particle_form(monkeypatch,tmp_path,width,form,allowed):
    from combat.tabletop import TabletopMapStore
    original=TabletopMapStore.save
    def save(self,doc,*args,**kwargs):
        if doc.get('display_name')=='R1i Wide':
            doc={**doc,'objects':[{'id':y+1,'kind':'wall_section','x':5,'y':y,'height_ft':100,
                **({'opening_width_milliinch':width} if y==6 else {})} for y in range(20)]}
        return original(self,doc,*args,**kwargs)
    monkeypatch.setattr(TabletopMapStore,'save',save)
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'primordial_dust'] if form else [],owner_cl=18,wide=True,
        positions={s.OWNER:{'x':3,'y':6},s.FOE:{'x':12,'y':6},s.SECOND:{'x':15,'y':6}})
    if form:commit(s.candidate(table,mid,'Primordial Dust'))
    # Use native legal candidates: no invented movement receipt or patched grid.
    e=combat._load_session(mid).engine
    choices=[c for c in e.legal_candidates() if c.destination and c.destination.x==7 and c.destination.y==6 and c.destination.z==0
        and c.kind.value=='MOVE']
    assert bool(choices)==allowed
    if allowed:
        commit(choices[0].candidate_id);e=cold(tmp_path,mid)
        assert e.state.actors[s.OWNER].position.x==7
        assert any((5,6)==(p['x'],p['y']) for ev in e.events if ev.event_type=='MOVEMENT_COMMITTED' and ev.actor_id==s.OWNER for p in ev.payload['path'])
        assert (5,6) in e.grid.blocked  # The opening grants no ordinary movement or line of effect.


@pytest.mark.parametrize('cloud',[False,True])
def test_particle_may_stop_in_creature_until_turn_end_then_settles(tmp_path,cloud):
    from tests.test_mgr_t14_dust_family import place,advance
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'primordial_dust']+([P+'dust_cloud'] if cloud else []),owner_cl=18,wide=True)
    if cloud:
        place(table,mid,'Dust Cloud',3,6);advance(table,mid,commit)
    commit(s.candidate(table,mid,'Primordial Dust'))
    e=combat._load_session(mid).engine;destination=e.state.actors[s.FOE].position
    options=[c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination==destination]
    assert options
    commit(options[0].candidate_id);e=cold(tmp_path,mid)
    assert e.state.actors[s.OWNER].position==destination
    hp=e.state.actors[s.OWNER].current_hp
    commit(table.state(mid)['menu']['end_turn']);e=cold(tmp_path,mid)
    assert e.state.actors[s.OWNER].position!=e.state.actors[s.FOE].position
    rolls=[v for v in e.events if v.event_type=='DAMAGE_ROLLED' and 'PRIMORDIAL_SETTLEMENT' in str(v.payload)]
    assert len(rolls)==1 and len(rolls[0].payload['dice'])==4
    assert hp-e.state.actors[s.OWNER].current_hp==rolls[0].payload['total']
    if cloud:
        zone=next(z for z in e.state.zones.values() if z.active and 'dust_cloud' in z.source_definition_id)
        assert zone.center==e.state.actors[s.OWNER].position


@pytest.mark.parametrize('width',[0,-1,True,1000.0,60001])
def test_native_map_rejects_unvalidated_opening_width(tmp_path,width):
    from combat.tabletop import TabletopMapStore,TabletopError
    store=TabletopMapStore(tmp_path)
    with pytest.raises(TabletopError):
        store.save({'display_name':'Invalid opening','width_squares':8,'height_squares':8,
            'walls':[],'terrain':[],'starts':{'team1':[[1,1]],'team2':[[6,6]]},
            'objects':[{'id':1,'kind':'wall_section','x':4,'y':4,'opening_width_milliinch':width}]})


@pytest.mark.parametrize('trapper_cl,form,held,before',[(17,True,False,True),(18,True,False,True),
    (19,True,True,True),(17,False,True,True),(17,True,False,False),(19,True,True,False)])
def test_native_tracked_net_uses_physical_hold_owner_contract(monkeypatch,tmp_path,trapper_cl,form,held,before):
    from tests.worker2_support import candidate,settle
    from tests.test_mgr_t14_dust_family import advance
    net='tianxia.talent.trap.net'
    original=s.sheet
    def sheet(mids,**kw):
        if net in mids:kw.update(cl=trapper_cl,dc=50)
        return original(mids,**kw)
    monkeypatch.setattr(s,'sheet',sheet)
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'primordial_dust'] if form else [],
        owner_cl=18,wide=True,foe_talents=(net,),
        positions={s.OWNER:{'x':3,'y':6},s.FOE:{'x':5,'y':6},s.SECOND:{'x':10,'y':6}})
    # A trap is produced and armed by its actual source owner.
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.FOE:commit(table.state(mid)['menu']['end_turn'])
    commit(s.candidate(table,mid,'Trap form: Net (Snare use)'))
    settle(table,mid,candidate(combat,mid,'Set Trap',at=(4,6)).candidate_id)
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.OWNER:commit(table.state(mid)['menu']['end_turn'])
    if form and before:commit(s.candidate(table,mid,'Primordial Dust'))
    e=combat._load_session(mid).engine
    move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination
        and (c.destination.x,c.destination.y,c.destination.z)==(4,6,0))
    commit(move.candidate_id);e=cold(tmp_path,mid)
    if form and not before:
        assert any(c.condition_id=='condition:typed.restrained' for c in e.state.actors[s.OWNER].conditions.values())
        commit(s.candidate(table,mid,'Primordial Dust'));e=cold(tmp_path,mid)
    assert any(v.event_type=='SAVE_ROLLED' and v.actor_id==s.OWNER for v in e.events)
    holds=[c for c in e.state.actors[s.OWNER].conditions.values() if c.condition_id=='condition:typed.restrained']
    assert bool(holds)==held
    if not held:
        assert not any(c.data.get('hold_id') for c in e.state.actors[s.OWNER].conditions.values())
        if before:
            assert not any(v.event_type=='CONDITION_APPLIED' and s.OWNER in v.target_ids
                and v.payload.get('condition_id')=='condition:typed.restrained' for v in e.events)


@pytest.mark.parametrize('source,label',[(P+'dust_cloud','Dust Cloud'),(P+'sandstorm_field','Sandstorm Field'),('DARK_BASE_DARKNESS','Darkness')])
@pytest.mark.parametrize('width',[None,1])
def test_native_field_air_aperture_is_explicit_and_default_inert(monkeypatch,tmp_path,source,label,width):
    from combat.tabletop import TabletopMapStore
    from combat import zones
    from tests.test_mgr_t14_dust_family import place
    original=TabletopMapStore.save
    def save(self,doc,*args,**kwargs):
        if doc.get('display_name')=='R1i Wide':
            doc={**doc,'objects':[{'id':y+1,'kind':'wall_section','x':5,'y':y,'height_ft':100,
                **({'opening_width_milliinch':width} if y==6 and width is not None else {})} for y in range(20)]}
        return original(self,doc,*args,**kwargs)
    monkeypatch.setattr(TabletopMapStore,'save',save)
    combat,table,mid,send,commit=s.fixture(tmp_path,[source],owner_cl=18,wide=True,
        positions={s.OWNER:{'x':4,'y':6},s.FOE:{'x':6,'y':6},s.SECOND:{'x':15,'y':6}})
    if source=='DARK_BASE_DARKNESS' and transformed_public_authority() and not any(
            g['label']==label for g in table.state(mid)['menu']['actions']):
        pytest.skip('the public snapshot does not expose the Darkness base action; this shared-seam case runs on the branch tree')
    place(table,mid,label,4,6);e=cold(tmp_path,mid)
    zone=next(z for z in e.state.zones.values() if z.active and source in z.source_definition_id)
    assert zones._inside(e,e.state.actors[s.FOE],zone)==(width is not None and source!= 'DARK_BASE_DARKNESS')
    assert (5,6) in e.grid.blocked


def test_erosion_reentry_is_once_per_creature_on_each_owner_turn(tmp_path):
    from tests.test_mgr_t14_dust_family import advance
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'primordial_dust'],owner_cl=18,wide=True)
    commit(s.candidate(table,mid,'Primordial Dust'))
    def move(x,y):
        e=combat._load_session(mid).engine
        choice=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination
            and (c.destination.x,c.destination.y,c.destination.z)==(x,y,0))
        commit(choice.candidate_id)
        return cold(tmp_path,mid)
    def saves(e):return [v for v in e.events if v.event_type=='SAVE_ROLLED'
        and v.actor_id==s.FOE and 'primordial_dust' in v.source_definition_id]
    e=move(4,6);assert len(saves(e))==1
    move(3,6);e=move(4,6);assert len(saves(e))==1
    move(3,6);advance(table,mid,commit)
    e=move(4,6);assert len(saves(e))==2
    move(3,6)


def test_particle_cannot_end_turn_inside_an_authored_solid_section(monkeypatch,tmp_path):
    from combat.tabletop import TabletopMapStore
    original=TabletopMapStore.save
    def save(self,doc,*args,**kwargs):
        if doc.get('display_name')=='R1i Wide':
            doc={**doc,'objects':[{'id':1,'kind':'wall_section','x':5,'y':6,
                'height_ft':100,'opening_width_milliinch':1000}]}
        return original(self,doc,*args,**kwargs)
    monkeypatch.setattr(TabletopMapStore,'save',save)
    combat,table,mid,send,commit=s.fixture(tmp_path,[P+'primordial_dust'],owner_cl=18,wide=True,
        positions={s.OWNER:{'x':3,'y':6},s.FOE:{'x':12,'y':6},s.SECOND:{'x':15,'y':6}})
    commit(s.candidate(table,mid,'Primordial Dust'))
    e=combat._load_session(mid).engine
    choice=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination
        and (c.destination.x,c.destination.y,c.destination.z)==(5,6,0))
    commit(choice.candidate_id);e=cold(tmp_path,mid)
    assert (e.state.actors[s.OWNER].position.x,e.state.actors[s.OWNER].position.y)==(5,6)
    hp=e.state.actors[s.OWNER].current_hp
    commit(table.state(mid)['menu']['end_turn']);e=cold(tmp_path,mid)
    from combat.opening_passage import solid_grid
    assert solid_grid(e).volume_legal(e.state.actors[s.OWNER].position,
        footprint=e._footprint(e.state.actors[s.OWNER]),occupied_cells=e._occupied_volumes_except(s.OWNER))
    rolls=[v for v in e.events if v.event_type=='DAMAGE_ROLLED' and 'PRIMORDIAL_SETTLEMENT' in str(v.payload)]
    assert len(rolls)==1 and len(rolls[0].payload['dice'])==4
    assert hp-e.state.actors[s.OWNER].current_hp==rolls[0].payload['total']
