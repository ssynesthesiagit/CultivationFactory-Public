"""Sol 1F4R regressions through cold native travel menus and persistence."""
import pytest

from combat.ext import mgr_reserve_raincaller_cultivator_call_rain as rain
from combat.gate5_service import CombatService
from tests.test_mgr_t14_raincaller_native import (
    installed, civil, scene, command, rainstate, site_profile, ROOT,
)
from tests.test_mgr_t14_raincaller_review_fixes import review_journey


@pytest.mark.parametrize('ending',['explicit','incapacitated','expiry'])
@pytest.mark.parametrize('overlap',[False,True])
def test_claim_identity_and_deadlines_survive_finish_new_journey(civil,ending,overlap):
    combat,aid,jid=civil;scene(civil)
    if overlap:
        command(civil,'rain_rite',{'effects':['clearing']})
        command(civil,'wait',{'seconds':600})
    command(civil,'rain_call',{'form':'mist','allies':[aid]})
    before=command(civil,'wait',{'seconds':6})
    identities={k:rain.site_claim_id(v) for k,v in rainstate(before,aid)['rains'].items()}
    remaining={k:v['expires_at']-before['seconds'] for k,v in rainstate(before,aid)['rains'].items()}
    command(civil,'finish',{})
    reopened=combat.create_journey(project_ids=[aid.removeprefix('actor:factory.')],
        arena_id='battlefield:factory_pillar_arena',positions={aid:{'x':3,'y':6}},base_paces={aid:3000})
    jid=reopened['journey_id'];civil=(combat,aid,jid)
    cold=CombatService(ROOT,combat.userdata_root)
    assert cold.journey_state(jid)==reopened
    current=rainstate(reopened,aid)
    assert {k:rain.site_claim_id(v) for k,v in current['rains'].items()}==identities
    smoke=next(f for f in current['site']['features'] if f['id']=='smoke')
    assert smoke['rain_claims']['suppressed_until']=={identities[k]:v for k,v in remaining.items()}
    if ending=='explicit':result=command(civil,'rain_end',{'kind':'call'})
    elif ending=='incapacitated':result=command(civil,'incapacitated',{'value':True})
    else:result=command(civil,'wait',{'seconds':remaining['call']})
    current=rainstate(result,aid);smoke=next(f for f in current['site']['features'] if f['id']=='smoke')
    assert 'call' not in current['rains']
    if overlap:
        assert smoke['rain_claims']['suppressed_until']=={identities['rite']:remaining['rite']}
        assert smoke['suppressed_until']==remaining['rite']
        if ending=='incapacitated':command(civil,'incapacitated',{'value':False})
        result=command(civil,'rain_end',{'kind':'rite'})
        smoke=next(f for f in rainstate(result,aid)['site']['features'] if f['id']=='smoke')
    assert 'rain_claims' not in smoke and 'suppressed_until' not in smoke


def pick(civil,option_id,automatic):
    combat,aid,jid=civil
    state=combat.journey_state(jid)
    offered=next(o for o in combat.journey_menu(jid,aid)['options'] if o['id']==option_id)
    if automatic:result=combat.journey_auto_step(jid,state['revision'],aid,option_id)
    else:result=combat.journey_act(jid,state['revision'],aid,offered['kind'],offered['payload'])
    assert CombatService(ROOT,combat.userdata_root).journey_state(jid)==result
    assert combat.journey_verify(jid)['status']=='PASS'
    return result


def with_seat_mode(review_journey,automatic):
    """Use actual native Manual/Local Auto configuration, not API aliases."""
    combat,aid,jid,guest=review_journey
    if not automatic:
        state=command((combat,aid,jid),'finish',{})
        actors=state['actors']
        state=combat.journeys.create([a['bundle'] for a in actors.values()],state['battlefield'],
            {a:v['position'] for a,v in actors.items()},
            {a:v['base_pace_ft_hour'] for a,v in actors.items()},
            {a:'MANUAL' for a in actors})
        jid=state['journey_id']
    assert combat.journey_state(jid)['actors'][aid]['control_mode']==('LOCAL_AUTO' if automatic else 'MANUAL')
    return combat,aid,jid,guest


@pytest.mark.parametrize('automatic',[False,True])
@pytest.mark.parametrize('kind',['call','wall','sovereign'])
def test_manual_and_auto_seats_choose_origin_allies_and_full_wall(review_journey,automatic,kind):
    combat,aid,jid,guest=with_seat_mode(review_journey,automatic);civil=(combat,aid,jid)
    site=site_profile();site['allies']=[aid,guest];scene(civil,site)
    before=combat.journey_state(jid)
    option='rain_call:heavy' if kind=='call' else 'rain_'+kind
    pick(civil,option+':configure',automatic)
    pick(civil,'rain_select:height:1',automatic)
    pick(civil,'rain_select:center:4,6,1',automatic)
    pick(civil,'rain_select:ally:'+guest,automatic)
    if kind=='wall':
        for x,y in [(5,6),(6,6),(7,7),(8,8),(9,8)]:
            pick(civil,f'rain_select:wall:{x},{y}',automatic)
    draft=combat.journey_state(jid)
    assert draft['seconds']==before['seconds']
    assert draft['actors'][aid]['resources']==before['actors'][aid]['resources']
    result=pick(civil,'rain_select:confirm',automatic)
    area=next(v for v in rainstate(result,aid)['rains'].values() if v['kind']==kind)
    assert area['center']=={'x':4,'y':6,'z':1}
    assert area['allies']==[aid,guest]
    if kind=='wall':assert area['wall_cells']==[[4,6],[5,6],[6,6],[7,7],[8,8],[9,8]]
    if kind=='call':assert area['form']=='heavy'
    assert result['actors'][aid]['resources']['resource:core.qi']==before['actors'][aid]['resources']['resource:core.qi']-{'call':1,'wall':4,'sovereign':8}[kind]
    assert 'selection' not in rainstate(result,aid)


@pytest.mark.parametrize('automatic',[False,True])
def test_rite_menu_reaches_arbitrary_recorded_clear_zone_subset(review_journey,automatic):
    combat,aid,jid,guest=with_seat_mode(review_journey,automatic);civil=(combat,aid,jid);site=site_profile()
    site['clear_zones']=[{'kind':kind,'center':{'x':x,'y':6},'radius_ft':5}
        for x,kind in enumerate(('road','building','agricultural_zone'),3)]
    scene(civil,site)
    pick(civil,'rain_rite:agriculture,mist:configure',automatic)
    # The Rite is performed at the surveyed site, not at a ranged origin.
    pick(civil,'rain_select:center:3,6,0',automatic)
    for index in (0,1,2,1):pick(civil,'rain_select:clear:'+str(index),automatic)
    result=pick(civil,'rain_select:confirm',automatic)
    assert result['actors'][aid]['source_states']['journey:activity']['worked_seconds']==0
    result=command(civil,'activity_work',{'seconds':600})
    area=rainstate(result,aid)['rains']['rite']
    assert area['effects']==['agriculture','mist']
    assert area['clear_zones']==[site['clear_zones'][0],site['clear_zones'][2]]
    assert area['center']=={'x':3,'y':6,'z':0}


def test_cancel_and_stale_selection_do_not_spend_or_hide_actions(civil):
    combat,aid,jid=civil;scene(civil)
    before=combat.journey_menu(jid,aid)['options']
    pick(civil,'rain_wall:configure',False)
    pick(civil,'rain_select:cancel',False)
    assert combat.journey_menu(jid,aid)['options']==before
    state=combat.journey_state(jid)
    with pytest.raises(ValueError,match='currently offered'):
        command(civil,'rain_select',{'step':'confirm','value':0})
    assert combat.journey_state(jid)==state


def test_out_of_range_surveyed_height_cannot_trap_placement_picker(civil):
    combat,aid,jid=civil;site=site_profile();site['center']['z']=13
    scene(civil,site)
    pick(civil,'rain_call:heavy:configure',False)
    # The survey's 65-foot altitude is outside Call Rain's 60-foot range.
    # Configuration still starts on a reachable slice and exposes legal origins.
    pick(civil,'rain_select:center:4,6,0',False)
    result=pick(civil,'rain_select:confirm',False)
    assert rainstate(result,aid)['rains']['call']['center']=={'x':4,'y':6,'z':0}


def test_central_extension_contract_documents_continuation_and_activity_hooks():
    from combat import ext
    contract=ext.__doc__
    for point in ('condition_metadata','journey_combat_bundle','journey_snapshot_actor',
                  'journey_encounter_settled','journey_initialize','journey_before_command',
                  'journey_scene_end','activity_spec','activity_started','activity_validate',
                  'activity_finished','activity_interrupted','activity_command_interrupts',
                  'fact_admission_validate','journey_world_fact_committed','combat_world_fact_committed'):
        assert point+'(' in contract
    for phrase in ('None','transaction','Primitive','ordered transforms','default-inert'):
        assert phrase in contract


@pytest.mark.parametrize('effect,clauses',[
    ('steady',['one inch','8 hours','cisterns','no flash flood']),
    ('drought',['one normal day','dead crops','permanent']),
    ('firebreak',['cannot spread','10-foot section per minute','Cultivation Check','save DC']),
    ('clearing',['10 minutes','smoke','pollution','Cultivation Check']),
    ('cooling',['tolerable','Fire techniques','lava']),
    ('agriculture',['Advantage','minor pests','seven days','viable']),
    ('mist',['300 feet','Lightly Obscured','roads','clear']),
])
def test_provincial_menu_explains_each_effect_and_exceptional_duration(civil,effect,clauses):
    combat,aid,jid=civil;scene(civil)
    label=next(o['label'] for o in combat.journey_menu(jid,aid)['options'] if o['id']=='rain_rite:'+effect)
    assert all(clause in label for clause in clauses)
    assert '5 Qi' in label and '10 minutes' in label and 'one-mile radius' in label
