"""Earth second-pass decisions committed by the service and cold-replayed."""
import pytest
from combat.gate2_runtime_models import ActionIntent
from combat.typed_executor import bears_mark
from combat.target_knowledge import can_see, located
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, act, fight as service_fight, reload, turn, settle, action_sender
from combat.ext.earth_second_pass import ADEPT, PALM, SENSE
from combat.ext import earth_responses as earth

WITNESS='actor:factory.auto111-witness'
MARK={'type':'mark','mark':'Burden Mark','applies_to':'target'}
SPEND={'type':'spend_mark','mark':'Burden Mark','applies_to':'target'}
INVISIBLE={'type':'condition','condition':'invisible','applies_to':'target','duration':'until_removed'}



def fight(tmp_path,talents=(),**kwargs):
    def insight_fields(doc,aid):
        if aid==LEFT:
            doc['spheres_and_talents']['cultivation_insight_record_ids']=[m for m in talents if m.startswith('insight.')]
    return service_fight(tmp_path,talents,sheet_edit=insight_fields,**kwargs)


def clear_arena(arena):
    # Isolate exact range/contact; the stock arena's pillars otherwise intervene.
    arena['terrain_regions']=[]
    arena['map_terrain']=[]


def direct(combat,mid,source,target=None):
    session=combat._load_session(mid)
    c=next(c for c in session.engine.legal_candidates() if c.source_definition_id.endswith(source)
           and (target is None or target in c.target_ids))
    session.mechanical.execute_intent(ActionIntent(intent_id='earth-second-pass',decision_id=c.decision_id,
        candidate_id=c.candidate_id,state_version=c.state_version,actor_id=c.actor_id,target_ids=c.target_ids,
        destination=c.destination,option_ids=c.option_ids))


@pytest.mark.parametrize('owns',[False,True])
def test_mark_limit_native_and_earth_cap_agree_after_reload(tmp_path,owns):
    combat,table,mid=fight(tmp_path,[earth.BASE,*([ADEPT] if owns else [])],left_pb=2,
                          prepare=[MARK],prepare_target='ANY_CREATURE',ally=[],extra_witness=True,
                          positions={LEFT:{'x':3,'y':6},RIGHT:{'x':4,'y':6},ALLY:{'x':3,'y':7}})
    for aid in (RIGHT,ALLY,WITNESS):
        assert act(table,mid,'Prepare',target_id=aid)['status']=='COMMITTED'
        reload(combat,mid)
    e=reload(combat,mid)
    assert sum(bears_mark(a,LEFT,earth.MARK) for a in e.state.actors.values())==(3 if owns else 2)
    assert bears_mark(e.state.actors[RIGHT],LEFT,earth.MARK)==owns
    assert act(table,mid,'Prepare',target_id=LEFT)['status']=='COMMITTED'
    e=reload(combat,mid)
    assert sum(bears_mark(a,LEFT,earth.MARK) for a in e.state.actors.values())==(3 if owns else 2)
    assert not bears_mark(e.state.actors[RIGHT],LEFT,earth.MARK)


@pytest.mark.parametrize('accept',[False,True])
def test_adept_optional_step_spends_no_reaction_and_one_round(tmp_path,accept):
    from combat.ext.needle import cell_id
    combat,table,mid=fight(tmp_path,[earth.BASE,ADEPT],prepare=[MARK],
        extra_actions=[('Spend',{'target_kind':'HOSTILE_ENTITY','effects':[SPEND]})])
    assert act(table,mid,'Prepare',target_id=RIGHT)['status']=='COMMITTED'
    before=reload(combat,mid).state.actors[LEFT]
    def choose(p):
        return [o['id'] for o in p['choice']['options'] if o['id']!=cell_id(before.position)][:1] if accept else []
    _,prompts=settle(lambda answers:act(table,mid,'Spend',answers,target_id=RIGHT),choose=choose)
    assert any('Burden Mark Adept' in str(p) for p in prompts)
    e=reload(combat,mid);owner=e.state.actors[LEFT]
    assert not bears_mark(e.state.actors[RIGHT],LEFT,earth.MARK)
    assert owner.reaction_available==before.reaction_available
    assert e.grid.distance_ft(before.position,owner.position)==(5 if accept else 0)
    assert (owner.turn_flags.get('once_per_round:earth_adept')==e.state.round_number)==accept
    if accept:
        assert act(table,mid,'Prepare',target_id=RIGHT)['status']=='COMMITTED'
        _,prompts=settle(lambda answers:act(table,mid,'Spend',answers,target_id=RIGHT))
        assert not any('Burden Mark Adept' in str(p) for p in prompts)
        reload(combat,mid)


def test_adept_accepted_earth_response_off_turn_reloads(tmp_path):
    from tests.auto_worker1_support import cell_send
    from combat.ext.needle import cell_id
    combat,table,mid=fight(tmp_path,[earth.BASE,ADEPT],prepare=[MARK],
        extra_actions=[('Spend',{'target_kind':'HOSTILE_ENTITY','effects':[SPEND]})])
    assert act(table,mid,'Prepare',target_id=RIGHT)['status']=='COMMITTED'
    settle(lambda answers:act(table,mid,'end',answers),choose=lambda p:[])
    before=reload(combat,mid).state.actors[LEFT].position
    def choose(p):
        options=p['choice']['options']
        if 'Burden Mark Adept' in str(p):
            return [o['id'] for o in options if o['id']!=cell_id(before)][:1]
        return [options[0]['id']]
    _,prompts=settle(cell_send(table,mid,'Move',(4,7)),choose=choose)
    assert any('Burden Mark Adept' in str(p) for p in prompts)
    e=reload(combat,mid)
    assert e.state.actors[LEFT].turn_flags['once_per_round:earth_adept']==e.state.round_number
    assert not bears_mark(e.state.actors[RIGHT],LEFT,earth.MARK)


def test_adept_receipt_survives_owner_turn_boundary_in_same_round(tmp_path,monkeypatch):
    from tests.auto_worker1_support import cell_send
    from combat.ext.needle import cell_id
    combat,table,mid=fight(tmp_path,[earth.BASE,ADEPT],prepare=[MARK],
        extra_actions=[('Spend',{'target_kind':'HOSTILE_ENTITY','effects':[SPEND]})])
    assert act(table,mid,'Prepare',target_id=RIGHT)['status']=='COMMITTED'
    settle(lambda answers:act(table,mid,'end',answers),choose=lambda p:[])
    before=reload(combat,mid).state.actors[LEFT].position
    def choose(p):
        return [o['id'] for o in p['choice']['options'] if o['id']!=cell_id(before)][:1]
    settle(cell_send(table,mid,'Move',(4,7)),choose=choose)
    e=reload(combat,mid)
    # This off-turn accepted step was committed by the service above. Exercise
    # the engine's owner turn-start reset while holding the same round number.
    # A round transition would legitimately make the next step available.
    e.state.current_actor_id=LEFT
    e._system_start_turn()
    assert e.state.round_number==1
    assert e.state.actors[LEFT].turn_flags['once_per_round:earth_adept']==1
    from types import SimpleNamespace
    from combat.ext import rider_choices
    from combat.ext.earth_second_pass import adept_step
    calls=[]
    monkeypatch.setattr(rider_choices,'step',lambda *args,**kwargs: calls.append(args) or True)
    adept_step(SimpleNamespace(engine=e,actor=e.state.actors[LEFT]),'Burden Mark',e.state.actors[RIGHT])
    assert calls==[], 'a second qualifying spend in this round must not reopen the step choice'


def test_adept_elevated_step_preserves_destination_z_and_cold_reloads(tmp_path):
    def platform(arena):
        clear_arena(arena)
        arena['terrain_regions']=[{'region_id':'raised-floor','terrain_type':'BLOCKED','movement_cost':0,
            'height_ft':10,'cells':[{'x':x,'y':y} for x in range(2,7) for y in range(4,9)]}]
    combat,table,mid=fight(tmp_path,[earth.BASE,ADEPT],prepare=[MARK],
        extra_actions=[('Spend',{'target_kind':'HOSTILE_ENTITY','effects':[SPEND]})],arena_edit=platform,
        positions={LEFT:{'x':3,'y':6,'z':2},RIGHT:{'x':5,'y':6,'z':2}})
    assert act(table,mid,'Prepare',target_id=RIGHT)['status']=='COMMITTED'
    before=reload(combat,mid).state.actors[LEFT].position
    combat.set_controller_mode(mid,actor_id=LEFT,controller_mode='LOCAL_AUTO')
    direct(combat,mid,'Spend',RIGHT)
    e=reload(combat,mid)
    assert e.state.actors[LEFT].position.z==2
    assert e.grid.distance_ft(before,e.state.actors[LEFT].position)==5
    assert not bears_mark(e.state.actors[RIGHT],LEFT,earth.MARK)


@pytest.mark.parametrize('cl,distance,detected',[(9,30,True),(9,35,False),(10,60,True),(10,65,False)])
def test_listening_range_locates_without_sight_and_expires(tmp_path,cl,distance,detected):
    combat,table,mid=fight(tmp_path,[PALM],cl=cl,prepare_target='SELF',
        prepare=[{'type':'condition','condition':'blinded','applies_to':'self','duration':'until_removed'}],
        arena_edit=clear_arena,positions={LEFT:{'x':1,'y':1},RIGHT:{'x':1+distance//5,'y':1}})
    assert act(table,mid,'Prepare')['status']=='COMMITTED'
    assert act(table,mid,PALM)['status']=='COMMITTED'
    e=reload(combat,mid);owner,foe=e.state.actors[LEFT],e.state.actors[RIGHT]
    sense=next(c for c in owner.conditions.values() if c.condition_id==SENSE)
    assert 'until the start of your next turn' in sense.data['label']
    assert not can_see(e,owner,foe)
    assert located(e,owner,foe)==detected
    turn(table,mid,RIGHT);turn(table,mid,LEFT)
    e=reload(combat,mid)
    assert not any(c.condition_id==SENSE for c in e.state.actors[LEFT].conditions.values())
    assert not located(e,e.state.actors[LEFT],e.state.actors[RIGHT])


def test_listening_direct_session_execute_intent_and_cold_reload(tmp_path):
    combat,table,mid=fight(tmp_path,[PALM],prepare=[INVISIBLE])
    assert act(table,mid,'Prepare',target_id=RIGHT)['status']=='COMMITTED'
    direct(combat,mid,PALM)
    e=reload(combat,mid)
    assert located(e,e.state.actors[LEFT],e.state.actors[RIGHT])
    assert not can_see(e,e.state.actors[LEFT],e.state.actors[RIGHT])


@pytest.mark.parametrize('obstruction',['sight_only','native_obscuring_zone'])
def test_palm_locates_through_visual_obscuration_without_sight(tmp_path,obstruction):
    def curtain(arena):
        clear_arena(arena)
        if obstruction=='sight_only':
            arena['terrain_regions']=[{'region_id':'curtain','terrain_type':'SIGHT_BLOCKED','movement_cost':0,
                'cells':[{'x':4,'y':1}]}]
    effects=[INVISIBLE]
    zone_spec=None
    if obstruction=='native_obscuring_zone':
        effects.append({'type':'zone'})
        zone_spec={'shape':'sphere','size_ft':60,'centered_on_self':True,'obscured':'heavy',
            'duration':{'kind':'minutes','amount':1},'name':'Heavy mist'}
    combat,table,mid=fight(tmp_path,[PALM],prepare_target='SELF',prepare=effects,
        prepare_zone_spec=zone_spec,arena_edit=curtain,
        positions={LEFT:{'x':1,'y':1},RIGHT:{'x':6,'y':1}})
    assert act(table,mid,'Prepare')['status']=='COMMITTED'
    direct(combat,mid,PALM)
    e=reload(combat,mid);owner,foe=e.state.actors[LEFT],e.state.actors[RIGHT]
    assert not can_see(e,owner,foe)
    assert located(e,owner,foe)


def test_packed_road_ai_with_both_sides_only_protects_allies(tmp_path):
    combat,table,mid=fight(tmp_path,[earth.PACKED_ROAD,'EARTH_BASE_SET_FOUNDATION'],ally=[],extra_witness=True,positions={LEFT:{'x':3,'y':6},RIGHT:{'x':4,'y':6},ALLY:{'x':3,'y':7}})
    settle(action_sender(combat,table,mid,'EARTH_BASE_SET_FOUNDATION',target_id=LEFT,ai=True))
    e=reload(combat,mid)
    chosen=set(earth._packed_data(e,e.state.actors[LEFT]).get('chosen','').split(','))
    assert chosen=={LEFT,ALLY}
    assert RIGHT not in chosen and WITNESS not in chosen


@pytest.mark.parametrize('dc,failed',[(100,True),(1,False)])
@pytest.mark.parametrize('height',[2,8])
def test_flying_thing_vertical_save_descent_hover_expiry_and_reload(tmp_path,dc,failed,height):
    from combat.flight import profile
    from combat.ext.earth_flying import FEATURE,HELD
    def fly(bundle):
        if bundle['actor_id']==RIGHT:
            bundle['actor_template'].update(fly_speed_ft=10,hover=True)
    combat,table,mid=fight(tmp_path,[earth.BASE,FEATURE],prepare=[MARK],left_save_dc=dc,
        bundle_edit=fly,arena_edit=clear_arena,positions={LEFT:{'x':3,'y':6},RIGHT:{'x':4,'y':6,'z':height}})
    assert act(table,mid,'Prepare',target_id=RIGHT)['status']=='COMMITTED'
    _,prompts=settle(lambda answers:act(table,mid,'end',answers),
        choose=lambda p:[p['choice']['options'][0]['id']] if 'Burden the Flying Thing' in str(p) else [])
    assert any('Burden the Flying Thing' in str(p) for p in prompts)
    prompt=str(prompts)
    assert 'Strength save' in prompt and 'start of its next turn' in prompt
    assert 'end of its current turn' in prompt and 'Prone if it lands' in prompt
    e=reload(combat,mid);foe=e.state.actors[RIGHT]
    assert foe.position.z==max(0,height-(6 if failed else 2))
    assert not profile(e,foe).can_ascend
    assert any(c.condition_id.endswith('.prone') for c in foe.conditions.values())==(failed and height<=6)
    held=next((c for c in foe.conditions.values() if c.condition_id==HELD),None)
    assert held and 'until the start of its next turn' in held.data['label'] if failed else held and 'until the end of its current turn' in held.data['label']
    assert not bears_mark(foe,LEFT,earth.MARK)
    assert e.state.actors[LEFT].reaction_available
    assert any(x.event_type=='SAVE_ROLLED' and x.actor_id==RIGHT for x in e.events)
    if failed:
        # Mark expenditure ends any further response; declined choices don't interfere.
        turn(table,mid,LEFT);turn(table,mid,RIGHT)
    else:
        turn(table,mid,LEFT)
    e=reload(combat,mid)
    assert not any(c.condition_id==HELD for c in e.state.actors[RIGHT].conditions.values())


def test_flying_thing_decline_keeps_the_mark_and_altitude(tmp_path):
    from combat.ext.earth_flying import FEATURE,HELD
    def fly(bundle):
        if bundle['actor_id']==RIGHT:
            bundle['actor_template'].update(fly_speed_ft=10,hover=True)
    combat,table,mid=fight(tmp_path,[earth.BASE,FEATURE],prepare=[MARK],bundle_edit=fly,arena_edit=clear_arena,
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':4,'y':6,'z':8}})
    assert act(table,mid,'Prepare',target_id=RIGHT)['status']=='COMMITTED'
    settle(lambda answers:act(table,mid,'end',answers),choose=lambda p:[])
    e=reload(combat,mid);foe=e.state.actors[RIGHT]
    assert foe.position.z==8 and bears_mark(foe,LEFT,earth.MARK)
    assert not any(c.condition_id==HELD for c in foe.conditions.values())


def test_deep_root_no_reminder_still_reduces_forced_movement_and_is_foundation(tmp_path):
    from combat.ext import earth_responses as earth
    root='TAL_EARTH_DEEP_ROOT_STANCE'
    combat,table,mid=fight(tmp_path,[root],cl=10,
        cause=[{'type':'forced_movement','distance_ft':15,'direction':'away','applies_to':'target'}])
    direct(combat,mid,root)
    e=reload(combat,mid);before=e.state.actors[LEFT].position
    assert earth._on_foundation(e,e.state.actors[LEFT],e.state.actors[LEFT])
    turn(table,mid,RIGHT)
    settle(lambda answers:act(table,mid,'Cause',answers,target_id=LEFT))
    e=reload(combat,mid)
    assert e.grid.distance_ft(before,e.state.actors[LEFT].position)==5
    assert not any('Rule reminder' in str(x.payload) or 'GM applies' in str(x.payload) for x in e.events)


@pytest.mark.parametrize('barrier',['BLOCKED','SIGHT_BLOCKED',None])
@pytest.mark.parametrize('airborne',[False,True])
def test_palm_excludes_airborne_targets_and_respects_physical_barriers(tmp_path,airborne,barrier):
    def fly(bundle):
        if bundle['actor_id']==RIGHT:
            bundle['actor_template'].update(fly_speed_ft=10,hover=True)
    def add_barrier(arena):
        clear_arena(arena)
        if not airborne and barrier:
            arena['terrain_regions']=[{'region_id':'stone','terrain_type':barrier,'movement_cost':0,
                'cells':[{'x':4,'y':1}]}]
    combat,table,mid=fight(tmp_path,[PALM],prepare_target='SELF',bundle_edit=fly,arena_edit=add_barrier,
        prepare=[{'type':'condition','condition':'blinded','applies_to':'self','duration':'until_removed'}],
        positions={LEFT:{'x':1,'y':1},RIGHT:{'x':6,'y':1,'z':1 if airborne else 0}})
    assert act(table,mid,'Prepare')['status']=='COMMITTED'
    direct(combat,mid,PALM)
    e=reload(combat,mid)
    assert located(e,e.state.actors[LEFT],e.state.actors[RIGHT]) == (not airborne and barrier != 'BLOCKED')


def test_flying_thing_preserves_mark_when_nearest_surface_needs_lateral_route(tmp_path):
    from combat.ext.earth_flying import FEATURE,HELD
    def fly(bundle):
        if bundle['actor_id']==RIGHT:
            bundle['actor_template'].update(fly_speed_ft=10,hover=True)
    def platform(arena):
        clear_arena(arena)
        arena['terrain_regions']=[{'region_id':'raised','terrain_type':'BLOCKED','movement_cost':0,
            'height_ft':20,'cells':[{'x':4,'y':5}]}]
    combat,table,mid=fight(tmp_path,[earth.BASE,FEATURE],prepare=[MARK],bundle_edit=fly,arena_edit=platform,
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':4,'y':6,'z':8}})
    assert act(table,mid,'Prepare',target_id=RIGHT)['status']=='COMMITTED'
    _,prompts=settle(lambda answers:act(table,mid,'end',answers),choose=lambda p:[])
    assert not any('Burden the Flying Thing' in str(p) for p in prompts)
    e=reload(combat,mid)
    assert e.state.actors[RIGHT].position.z==8
    assert bears_mark(e.state.actors[RIGHT],LEFT,earth.MARK)
    assert not any(c.condition_id==HELD for c in e.state.actors[RIGHT].conditions.values())


def test_adept_direct_session_execute_intent_cold_reloads_accepted_step(tmp_path):
    combat,table,mid=fight(tmp_path,[earth.BASE,ADEPT],prepare=[MARK],
        extra_actions=[('Spend',{'target_kind':'HOSTILE_ENTITY','effects':[SPEND]})])
    assert act(table,mid,'Prepare',target_id=RIGHT)['status']=='COMMITTED'
    before=reload(combat,mid).state.actors[LEFT].position
    combat.set_controller_mode(mid,actor_id=LEFT,controller_mode='LOCAL_AUTO')
    direct(combat,mid,'Spend',RIGHT)
    e=reload(combat,mid)
    assert e.grid.distance_ft(before,e.state.actors[LEFT].position)==5
    assert not bears_mark(e.state.actors[RIGHT],LEFT,earth.MARK)
