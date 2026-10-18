"""Review regressions: acquired native table/journey callers, no model transport."""
from copy import deepcopy
import pytest

from combat.ext import mgr_reserve_raincaller_cultivator_call_rain as rain
from combat import concentration
from combat.gate2_runtime_content import AN
from tests.test_mgr_t14_raincaller_native import (
    installed, native, civil, scene, command, rainstate, Play, ROOT,
)


def zones(e, owner, kind):
    return rain.rainzones(e, owner, kind)


def test_sovereign_end_rebinds_multiple_children_before_failed_damage_check(native):
    p=native
    p.cast('Call Rain',{'choice:needle.rain_form':'heavy'})
    p.next();p.cast('Monsoon Wall')
    p.next();p.cast('Monsoon Sovereign')
    e=p.load();parent=zones(e,p.owner,'sovereign')[0]
    children=zones(e,p.owner,'call')+zones(e,p.owner,'wall')
    assert len(children)==2 and all(not z.concentration_link for z in children)
    p.cast('Raincaller: end your rain',{'choice:needle.rain_end':parent.zone_id})
    # This is a cold controller load after the real table commit and replay.
    e=p.load();owner=e.state.actors[p.owner]
    states=[s for _,s in concentration.held(owner)]+[owner.concentration]
    assert {s.zone_id for s in states if s}=={z.zone_id for z in children}
    from tests.h1_support import script
    script(e,[1]*100)
    while owner.concentration:
        zid=owner.concentration.zone_id
        e._concentration_check(owner,60)
        assert not e.state.zones[zid].active
    assert not zones(e,p.owner,'call') and not zones(e,p.owner,'wall')


def test_incapacitation_releases_only_call_claim_with_independent_rite_and_reload(civil):
    combat,aid,jid=civil;scene(civil)
    command(civil,'rain_rite',{'effects':['clearing']})
    command(civil,'wait',{'seconds':600})
    command(civil,'rain_call',{'form':'mist','allies':[aid]})
    before=rainstate(combat.journey_state(jid),aid)
    smoke=next(f for f in before['site']['features'] if f['id']=='smoke')
    assert len(smoke['rain_claims']['suppressed_until'])==2
    rite_claim=rain.site_claim_id(before['rains']['rite'])
    state=command(civil,'incapacitated',{'value':True})
    result=rainstate(state,aid)
    assert set(result['rains'])=={'rite'}
    smoke=next(f for f in result['site']['features'] if f['id']=='smoke')
    assert smoke['rain_claims']['suppressed_until']=={rite_claim:result['rains']['rite']['expires_at']}
    command(civil,'incapacitated',{'value':False})
    state=command(civil,'rain_end',{'kind':'rite'})
    assert 'suppressed_until' not in next(f for f in rainstate(state,aid)['site']['features'] if f['id']=='smoke')


@pytest.mark.parametrize('ability,expected',[('Call Rain','ADVANTAGE'),('Monsoon Wall','NORMAL'),('Monsoon Sovereign','NORMAL')])
def test_environmental_heat_save_belongs_only_to_call_rain(native,ability,expected):
    p=native;p.cast(ability);e=p.load();actor=e.state.actors[p.owner]
    assert e._roll_save(actor,'CON',12,'system:environmental_heat',roll_context={'named':['environmental_heat']}).mode==expected


@pytest.mark.parametrize('hazard',['poisoned','disease','smoke','dust','ash','inhaled_hazard'])
def test_cleansing_rain_rolls_real_advantaged_saves_without_curing(native,hazard):
    p=native;p.cast('Call Rain',{'choice:needle.rain_form':'cleansing'})
    e=p.load();actor=e.state.actors[p.owner];before=deepcopy(actor.conditions)
    assert e._roll_save(actor,'CON',12,'system:hazard',roll_context={'named':[hazard]}).mode=='ADVANTAGE'
    assert actor.conditions==before
    assert e._roll_save(actor,'CON',12,'system:unrelated',roll_context={'named':['injury']}).mode=='NORMAL'


@pytest.mark.parametrize('ability,form',[('Call Rain','driving'),('Monsoon Wall',None)])
def test_hostile_start_resolves_strength_save_and_push_once_per_turn(native,ability,form):
    p=native;p.turn();e=p.load();target=e.state.actors[AN]
    at=target.position.model_dump()
    before=target.position;start=len(e.rolls)
    c=p.candidate(ability,at=at)
    p.commit(c.candidate_id,{'choice:needle.rain_form':form} if form else {})
    p.turn(AN);e=p.load()
    saves=[r for r in e.rolls[start:] if r.actor_id==AN and r.reason.endswith(':STR')]
    assert len(saves)==1
    assert e.state.actors[AN].position!=before
    # Re-entering the native trigger dispatcher in the same turn cannot save twice.
    from combat import zones as zone_api
    z=zones(e,p.owner,'call' if form else 'wall')[0]
    zone_api.fire_trigger(e,z,e.state.actors[AN],'start')
    assert len([r for r in e.rolls[start:] if r.actor_id==AN and r.reason.endswith(':STR')])==1


@pytest.mark.parametrize('ability,kind',[('Call Rain','call'),('Monsoon Wall','wall')])
def test_hostile_actual_table_movement_into_rain_resolves_entry_save(native,ability,kind):
    p=native;p.turn();e=p.load();foe=e.state.actors[AN]
    candidates=[c for c in e.legal_candidates() if e.action_catalog.get(c.source_definition_id)
                and e.action_catalog[c.source_definition_id].display_name==ability and c.destination]
    if kind=='call':
        candidates=[c for c in candidates if e.grid.distance_ft(c.destination,foe.position)==25]
    else:
        candidates=[c for c in candidates if c.destination.x==foe.position.x+1 and c.destination.y==foe.position.y]
    assert candidates
    p.commit(candidates[0].candidate_id,{'choice:needle.rain_form':'driving'} if kind=='call' else {})
    e=p.load();z=zones(e,p.owner,kind)[0]
    assert not rain.inside(e,z,e.state.actors[AN])
    p.turn(AN);e=p.load();start=len(e.rolls)
    moves=[c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination
           and rain.point_inside(e,z,c.destination)]
    assert moves
    selected=min(moves,key=lambda c:e.grid.distance_ft(e.state.actors[AN].position,c.destination))
    p.commit(selected.candidate_id)
    e=p.load()
    assert len([r for r in e.rolls[start:] if r.actor_id==AN and r.reason.endswith(':STR')])==1


def test_driving_flood_resolves_native_strength_save_movement_and_prone(native):
    p=native;p.cast('Monsoon Sovereign');e=p.load();foe=e.state.actors[AN]
    before=foe.position;start=len(e.rolls)
    point=f'{foe.position.x},{foe.position.y},{foe.position.z}'
    p.next({'choice:needle.rain_decree':'flood','choice:needle.rain_point':point,
            'choice:needle.rain_flood_targets':[AN],'choice:needle.rain_flood_direction':'away_center'})
    e=p.load();saves=[r for r in e.rolls[start:] if r.actor_id==AN and r.reason.endswith(':STR')]
    assert len(saves)==1
    assert e.state.actors[AN].position!=before
    dc=zones(e,p.owner,'sovereign')[0].trigger_profile['numbers']['save_dc']
    assert any(c.condition_id.endswith('prone') for c in e.state.actors[AN].conditions.values())==(saves[0].total<dc)


def test_veiling_rain_has_actual_hostile_obscuration_and_next_turn_expiry(native):
    p=native;p.cast('Monsoon Sovereign');e=p.load();foe=e.state.actors[AN]
    point=f'{foe.position.x},{foe.position.y},{foe.position.z}'
    p.next({'choice:needle.rain_decree':'veiling','choice:needle.rain_point':point})
    e=p.load();veil=zones(e,p.owner,'veil')[0]
    assert rain.inside(e,veil,e.state.actors[AN])
    assert veil.trigger_profile['obscured']=='heavy'
    assert rain.clear_allies(e,veil,e.state.actors[AN],e.state.actors[p.owner]) is False
    assert rain.clear_allies(e,veil,e.state.actors[p.owner],e.state.actors[AN]) is True
    p.next({'choice:needle.rain_decree':'gentle'})
    assert not p.load().state.zones[veil.zone_id].active


@pytest.mark.parametrize('endpoint,height,expected',[(1,0,10),(0,0,20),(1,2,20)])
def test_wall_fire_packets_require_full_thickness(native,endpoint,height,expected):
    from combat.damage_context import AttackDamage
    from combat.gate2_runtime_models import Position
    from tests.h1_support import script
    p=native;p.cast('Monsoon Wall');e=p.load();wall=zones(e,p.owner,'wall')[0]
    cell=min(wall.affected_cells,key=lambda c:abs(c.y-wall.center.y));target=e.state.actors[p.owner];attacker=e.state.actors[AN]
    # A perpendicular ray crosses one complete five-foot wall section; an
    # endpoint inside crosses half, and a ray at the top crosses none.
    attacker.position=Position(x=cell.x-1,y=cell.y,z=wall.center.z+height)
    target.position=Position(x=cell.x+endpoint,y=cell.y,z=wall.center.z+height)
    script(e,[20]*50)
    packet=AttackDamage('system:ranged_fire',AN,p.owner,0,'roll:fire',20,40,False,kind='weapon')
    with e.d20_scope({'kind':'attack','attack_delivery':'weapon','spec':{'range_ft':60}}):
        dealt=e._commit_damage(target,20,'FIRE','system:ranged_fire',AN,None,reaction_depth=0,attack_context=packet)
    assert dealt==expected


def test_safe_channel_real_recipient_choice_can_decline_or_move(native):
    p=native;p.cast('Monsoon Sovereign');before=p.load().state.actors[p.owner].position
    # Returning None explicitly declines this player's movement choice.
    p.next({'choice:needle.rain_decree':'channel','choice:needle.rain_channel':[p.owner],
            'choice:needle.rain_channel_destination':None})
    assert p.load().state.actors[p.owner].position==before
    p.next({'choice:needle.rain_decree':'channel','choice:needle.rain_channel':[p.owner]})
    e=p.load();assert e.state.actors[p.owner].position!=before
    assert e.grid.distance_ft(before,e.state.actors[p.owner].position)<=15


@pytest.mark.parametrize('accept',[False,True])
def test_safe_channel_asks_actual_manual_recipient_on_automatic_caster_turn(native,monkeypatch,accept):
    from combat.factory_compiler import compile_character
    from combat.tabletop_service import TabletopService
    from tests.h1_support import sheet
    old=native;combat=old.combat;aid=old.owner;guest='actor:factory.rain-channel-guest'
    pid=aid.removeprefix('actor:factory.')
    bundles=[compile_character(sheet([],cl=18,name='Rain Guest'),actor_id=guest),
             compile_character(combat._factory_owner_sheet(pid),actor_id=aid)]
    match=combat._finish_factory_match(bundles,[guest,aid,AN],{aid:'party',guest:'party',AN:'foe'},
        {aid:{'x':3,'y':6},guest:{'x':3,'y':7},AN:{'x':8,'y':6}},
        combat.factory_arenas()['battlefield:factory_pillar_arena'],[aid,guest],[AN],
        control_modes={aid:'MANUAL',guest:'MANUAL',AN:'MANUAL'},match_seed='RAIN-AUTO-CHANNEL',
        display_name='Native rain recipient choice',maximum_rounds=6)
    p=Play(combat,TabletopService(combat,old.data),match['match_id'],aid,old.data)
    p.cast('Monsoon Sovereign',{'choice:needle.rain_allies':[aid,guest]})
    before=p.load().state.actors[guest].position
    p.commit(p.table.state(p.mid)['menu']['end_turn'])
    combat.set_controller_mode(p.mid,actor_id=aid,controller_mode='LOCAL_AUTO')
    # Select this automatic policy's decree by ordering its full choice pool;
    # the actual manual recipient transport and table answer remain untouched.
    monkeypatch.setattr(rain,'DECREES',{'channel':rain.DECREES['channel'],
                        **{k:v for k,v in rain.DECREES.items() if k!='channel'}})
    prompts=[]
    for _ in range(6):
        if p.table.state(p.mid)['menu']['actor_id']==aid:break
        prompts.extend(p.commit(p.table.state(p.mid)['menu']['end_turn'],
            {} if accept else {'choice:needle.rain_channel_destination':None}))
    asked=[x for x in prompts if x['context']['reaction_source_id']=='choice:needle.rain_channel_destination']
    assert len(asked)==1
    assert asked[0]['context']['target_id']==guest
    assert 'Safe Channel' in str(asked[0]) and 'Rain Guest' in str(asked[0])
    e=p.load();assert e.state.current_actor_id==aid
    after=e.state.actors[guest].position
    assert (after!=before)==accept
    assert e.grid.distance_ft(before,after)<=15


def test_form_and_decree_choices_explain_mechanics_at_the_table(native):
    p=native;prompts=p.cast('Call Rain')
    form=next(x for x in prompts if x['context']['reaction_source_id']=='choice:needle.rain_form')
    text=str(form['choice']['options'])
    assert 'Strength' in text and '10 feet' in text and 'Temporary Hit Points' in text
    p.next();p.cast('Monsoon Sovereign')
    prompts=p.commit(p.table.state(p.mid)['menu']['end_turn'])
    # The start-turn decree is offered when the owner next becomes current.
    if not any(x['context']['reaction_source_id']=='choice:needle.rain_decree' for x in prompts):
        prompts=p.commit(p.table.state(p.mid)['menu']['end_turn'])
    decree=next(x for x in prompts if x['context']['reaction_source_id']=='choice:needle.rain_decree')
    text=str(decree['choice']['options'])
    for detail in ('2d8','5d8','15 feet','Cultivation Level','until your next turn'):
        assert detail in text


@pytest.mark.parametrize('kind,cost',[('wall',4),('sovereign',8)])
def test_travel_has_reachable_paid_wall_and_sovereign_with_expiry_and_reload(civil,kind,cost):
    combat,aid,jid=civil;scene(civil)
    menu=combat.journey_menu(jid,aid)
    option=next(o for o in menu['options'] if o['kind']=='rain_'+kind)
    before=menu['resources']['resource:core.qi']
    state=command(civil,option['kind'],option['payload'])
    active=next(r for r in rainstate(state,aid)['rains'].values() if r['kind']==kind)
    assert active['source']==rain.RAIN_SOURCES[kind]
    assert state['actors'][aid]['resources']['resource:core.qi']==before-cost
    assert active['expires_at']-state['seconds']==60
    if kind=='sovereign':
        assert state['actors'][aid]['travel_uses'][rain.SOVEREIGN]==1
        assert not any(o['kind']=='rain_sovereign' for o in combat.journey_menu(jid,aid)['options'])
    state=command(civil,'wait',{'seconds':60})
    assert not rainstate(state,aid)['rains']


@pytest.fixture
def review_journey(tmp_path,installed):
    import shutil
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from tests.h1_support import sheet
    original,pid=installed;data=tmp_path/'roundtrip';shutil.copytree(original,data)
    combat=CombatService(ROOT,data);aid='actor:factory.'+pid;guest='actor:factory.rain-review-guest'
    bundles=[compile_character(combat._factory_owner_sheet(pid),actor_id=aid),
             compile_character(sheet([],cl=18),actor_id=guest)]
    state=combat.journeys.create(bundles,combat.factory_arenas()['battlefield:factory_pillar_arena'],
        {aid:{'x':3,'y':6},guest:{'x':8,'y':6}},{aid:3000,guest:3000},
        {aid:'LOCAL_AUTO',guest:'MANUAL'})
    return combat,aid,state['journey_id'],guest


@pytest.mark.parametrize('kind',['wall','sovereign'])
def test_automatic_travel_seat_can_select_each_acquired_rain(review_journey,kind):
    combat,aid,jid,guest=review_journey;civil=(combat,aid,jid);scene(civil)
    state=combat.journey_state(jid)
    state=combat.journey_auto_step(jid,state['revision'],aid,'rain_'+kind)
    assert any(r['kind']==kind for r in rainstate(state,aid)['rains'].values())
    assert combat.journey_verify(jid)['status']=='PASS'


def test_wall_sovereign_and_child_rain_continue_through_real_encounter(review_journey):
    from combat.tabletop_service import TabletopService
    from combat.gate5_service import CombatService
    combat,aid,jid,guest=review_journey;civil=(combat,aid,jid);scene(civil)
    command(civil,'rain_call',{'form':'heavy','allies':[aid]})
    command(civil,'rain_wall',{'allies':[aid],'wall_cells':[[3,6],[4,6],[5,6]]})
    before=command(civil,'rain_sovereign',{'allies':[aid]})
    deadlines={r['kind']:r['expires_at'] for r in rainstate(before,aid)['rains'].values()}
    # Manual combat lets the test advance only turns, with no AI/model requests.
    combat.journeys.load(jid)  # confirm persisted setup before native entry
    fight=combat.journey_start_combat(jid,before['revision'],{aid:'rain',guest:'guest'},maximum_rounds=1)
    combat.set_controller_mode(fight['match_id'],actor_id=aid,controller_mode='MANUAL')
    p=Play(combat,TabletopService(combat,combat.userdata_root),fight['match_id'],aid,combat.userdata_root)
    e=p.load()
    assert len(zones(e,aid,'wall')[0].affected_cells)==3
    assert zones(e,aid,'call')[0].trigger_profile['profile']['form']=='heavy'
    assert not zones(e,aid,'wall')[0].concentration_link
    assert not zones(e,aid,'call')[0].concentration_link
    assert e.state.actors[aid].concentration.zone_id==zones(e,aid,'sovereign')[0].zone_id
    for _ in range(6):
        if p.load().state.terminal_result:break
        p.commit(p.table.state(p.mid)['menu']['end_turn'])
    assert p.load().state.terminal_result
    state=combat.journey_state(jid)
    resumed=combat.journey_resume(jid,state['revision'])
    assert CombatService(ROOT,combat.userdata_root).journey_state(jid)==resumed
    active=rainstate(resumed,aid)['rains']
    assert {r['kind'] for r in active.values()}=={'call','wall','sovereign'}
    assert {r['kind']:r['expires_at'] for r in active.values()}==deadlines
    assert resumed['actors'][aid]['travel_uses'][rain.SOVEREIGN]==1
    assert combat.journey_verify(jid)['status']=='PASS'
    # Re-entering another encounter must not renew clocks or scene use.
    second=combat.journey_start_combat(jid,resumed['revision'],{aid:'rain',guest:'guest'},maximum_rounds=1)
    e=CombatService(ROOT,combat.userdata_root)._load_session(second['match_id']).engine
    assert len(zones(e,aid,'wall')[0].affected_cells)==3
    assert all(z.trigger_profile['profile']['civil_expires_at']==deadlines[z.trigger_profile['profile']['rain_family']]
               for z in rain.rainzones(e,aid))


@pytest.mark.parametrize('ability,kind',[('Monsoon Wall','wall'),('Monsoon Sovereign','sovereign')])
def test_combat_cast_continues_without_prior_civil_site_survey(review_journey,ability,kind):
    from combat.tabletop_service import TabletopService
    combat,aid,jid,guest=review_journey
    state=combat.journey_state(jid)
    fight=combat.journey_start_combat(jid,state['revision'],{aid:'rain',guest:'guest'},maximum_rounds=1)
    combat.set_controller_mode(fight['match_id'],actor_id=aid,controller_mode='MANUAL')
    p=Play(combat,TabletopService(combat,combat.userdata_root),fight['match_id'],aid,combat.userdata_root)
    p.cast(ability)
    for _ in range(6):
        if p.load().state.terminal_result:break
        p.commit(p.table.state(p.mid)['menu']['end_turn'])
    assert p.load().state.terminal_result
    resumed=combat.journey_resume(jid,combat.journey_state(jid)['revision'])
    active=rainstate(resumed,aid)['rains']
    assert len(active)==1
    key,area=next(iter(active.items()))
    assert area['kind']==kind and 0<area['expires_at']-resumed['seconds']<=60
    # A resumed source is not a fabricated environmental survey. It can be
    # voluntarily ended even though new civil activations still require one.
    assert not any(o['kind']=='rain_wall' for o in combat.journey_menu(jid,aid)['options'])
    state=command((combat,aid,jid),'rain_end',{'kind':key})
    assert not rainstate(state,aid)['rains']
