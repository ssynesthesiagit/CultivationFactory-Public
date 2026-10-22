"""Native vessel geometry/capacity/destruction survive table commits and reloads."""
import pytest
from combat.ext import placed, vessel
from combat.typed_executor import bears_mark, mark_condition_id
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload, action_sender
from tests.test_auto28_puppetry import OWNED, SPHERE, raise_at
from tests.auto28_puppetry_support import resolve, turn, cell_send
from tests.auto28_puppetry_support import OTHER, triple_fight

POOL='resource:core.qi'
INC='tianxia.talent.puppetry.thousand_puppet_incarnation'
INC_ACTIVE='condition:typed.vessel_incarnation'


def active(e):
    return [z for z in placed.of(e,'vessel') if placed.data(z).get('state')=='active']


def next_turn(t,m):
    turn(t,m,RIGHT);turn(t,m,LEFT)


def strike_sender(c,t,m,zone,*,free=False,ai=False):
    e=c._load_session(m).engine
    candidate=next(x for x in e.legal_candidates() if x.target_ids==(RIGHT,)
        and x.metadata.get('effect_origin',{}).get('id')=='vessel:'+zone.zone_id
        and bool(e.action_catalog[x.source_definition_id].parameters.get('vessel_incarnation_free'))==free)
    if ai:
        from combat.gate4_adapters import ManualControllerAdapter
        real=c.controller
        class Controller:
            def choose_primary_action(self,context):
                return ManualControllerAdapter(lambda _:(candidate.candidate_id,())).choose_primary_action(context)
            def __getattr__(self,name):return getattr(real,name)
        c.controller=Controller()
        c.set_controller_mode(m,actor_id=LEFT,controller_mode='LOCAL_AUTO')
        return lambda answers:t.auto_step(m,t.state(m)['last_sequence'],answers)
    def send(answers):
        state=t.state(m);menu=state['menu']
        return t.act(m,candidate.candidate_id,menu['decision_id'],menu['state_version'],state['last_sequence'],answers)
    return send


@pytest.mark.parametrize('ai',[False,True])
def test_strike_uses_vessel_origin_cover_and_preserves_body(tmp_path,ai):
    def cover(arena):arena['terrain_regions'].append({'region_id':'test.cover','terrain_type':'SIMPLE_COVER',
        'movement_cost':5,'cells':[{'x':4,'y':6}]})
    c,t,m=fight(tmp_path,OWNED,spheres=[SPHERE],left_attack_bonus=100,
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':6,'y':6}},arena_edit=cover)
    assert not any('Puppet Strike' in g['label'] for g in t.state(m)['menu']['actions'])
    raise_at(c,t,m,5,6);next_turn(t,m)
    e=reload(c,m);owner=e.state.actors[LEFT];before=owner.position.model_copy(),owner.movement_remaining_ft,owner.resources[POOL]
    zone=active(e)[0]
    assert e._cover_bonus_actor_to_actor(owner,e.state.actors[RIGHT])==2
    resolve(strike_sender(c,t,m,zone,ai=ai))
    if ai:c.set_controller_mode(m,actor_id=LEFT,controller_mode='MANUAL')
    e=reload(c,m);owner=e.state.actors[LEFT]
    assert (owner.position,owner.movement_remaining_ft,owner.resources[POOL])==before
    attack=next(v for v in reversed(e.events) if v.event_type=='ATTACK_ROLLED')
    assert attack.payload['cover_bonus']==0
    assert any(v.payload.get('effect_origin',{}).get('id')=='vessel:'+zone.zone_id for v in e.events)
    assert e.state.actors[RIGHT].current_hp<1000 and bears_mark(e.state.actors[RIGHT],LEFT,vessel.MARK)
    mark=next(x for x in e.state.actors[RIGHT].conditions.values() if x.condition_id==mark_condition_id(vessel.MARK,LEFT))
    assert mark.expires_on!='UNTIL_REMOVED'
    assert not getattr(e,'_effect_origin',None)
    next_turn(t,m);turn(t,m,RIGHT)
    assert not bears_mark(reload(c,m).state.actors[RIGHT],LEFT,vessel.MARK)


def test_each_vessel_retains_its_designated_damage_form(tmp_path):
    c,t,m=fight(tmp_path,[*OWNED,vessel.TWO_BODY],spheres=[SPHERE],left_attack_bonus=100,
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':6,'y':6}})
    assert act(t,m,'Vessel form: Slashing')['status']=='COMMITTED'
    raise_at(c,t,m,5,6);next_turn(t,m)
    first=active(reload(c,m))[0]
    assert act(t,m,'Vessel form: Piercing')['status']=='COMMITTED'
    raise_at(c,t,m,5,7);next_turn(t,m)
    second=next(z for z in active(reload(c,m)) if z.zone_id!=first.zone_id)
    assert act(t,m,'Vessel form: Bludgeoning')['status']=='COMMITTED'
    for zone,kind in [(first,'SLASHING'),(second,'PIERCING')]:
        resolve(strike_sender(c,t,m,zone))
        e=reload(c,m)
        assert next(v for v in reversed(e.events) if v.event_type=='DAMAGE_COMMITTED').payload['damage_type']==kind
        assert len(active(e))==2
        next_turn(t,m)
    resolve(lambda answers:act(t,m,"Tension Response: Snap the Thread (the vessel's last damage type)",answers,target_id=RIGHT),
        {'choice:needle.vessel_snap_type':[first.zone_id]})
    e=reload(c,m)
    assert next(v for v in reversed(e.events) if v.event_type=='DAMAGE_COMMITTED').payload['damage_type']=='SLASHING'


@pytest.mark.parametrize('talent,limit',[(vessel.THEATER,3),(INC,5)])
def test_active_capacity_and_native_minute_expiry(tmp_path,talent,limit):
    c,t,m=fight(tmp_path,[*OWNED,talent],spheres=[SPHERE],maximum_rounds=16)
    assert act(t,m,talent)['status']=='COMMITTED'
    e=reload(c,m)
    kind=vessel.THEATER_ACTIVE if talent==vessel.THEATER else INC_ACTIVE
    condition=next(x for x in e.state.actors[LEFT].conditions.values() if x.condition_id==kind)
    deadline=e.state.round_number+10
    assert condition.expires_on==f'START_OF_SLOT_AT:{deadline}:{e.state.current_slot_index}'
    next_turn(t,m)
    for n,(x,y) in enumerate([(4,7),(3,7),(2,7),(2,6),(2,5),(3,5)]):
        raise_at(c,t,m,x,y)
        assert len(active(reload(c,m)))==min(n+1,limit)
        if n<5:next_turn(t,m)
    while c._load_session(m).engine.state.round_number<deadline:
        resolve(lambda answers:act(t,m,'end',answers))
    e=reload(c,m)
    assert not any(x.condition_id==kind for x in e.state.actors[LEFT].conditions.values())
    assert len(active(e))==1
    assert not any('could not run' in str(v.payload) for v in e.events)


@pytest.mark.parametrize('domain,responses',[(False,2),(True,3)])
def test_incarnation_free_strike_and_two_responses_per_real_turn(tmp_path,domain,responses):
    c,t,m=fight(tmp_path,[*OWNED,INC,*([vessel.THEATER] if domain else [])],spheres=[SPHERE],
        left_attack_bonus=100,prepare=[{'type':'mark','mark':vessel.MARK,'applies_to':'target','duration':{'kind':'until_removed'}}])
    raise_at(c,t,m,4,7);next_turn(t,m)
    if domain:assert act(t,m,vessel.THEATER)['status']=='COMMITTED'
    before=reload(c,m).state.actors[LEFT].resources[POOL]
    assert act(t,m,INC)['status']=='COMMITTED'
    e=reload(c,m)
    assert e.state.actors[LEFT].resources[POOL]==before-8
    assert e.state.actors[RIGHT].current_hp==1000  # Activation never explodes.
    if domain:next_turn(t,m)
    e=reload(c,m);cp=e.state.actors[LEFT].resources[POOL]
    for repeat in range(2):
        resolve(strike_sender(c,t,m,active(e)[0],free=True))
        e=reload(c,m)
        assert e.state.actors[LEFT].action_available and e.state.actors[LEFT].resources[POOL]==cp
        assert not any('Incarnation free strike' in g['label'] for g in t.state(m)['menu']['actions'])
        for _ in range(responses):
            assert act(t,m,'Prepare',target_id=RIGHT)['status']=='COMMITTED'
            assert act(t,m,'Tension Response: Cross the Limb',target_id=RIGHT)['status']=='COMMITTED'
            assert not bears_mark(reload(c,m).state.actors[RIGHT],LEFT,vessel.MARK)
        assert act(t,m,'Prepare',target_id=RIGHT)['status']=='COMMITTED'
        assert not any(g['label'].startswith('Tension Response:') for g in t.state(m)['menu']['actions'])
        if repeat==0:next_turn(t,m);e=reload(c,m)


def broken_scene(tmp_path,*,domain=True,incarnation=True,ally=False,success=False):
    def cause(bundle):
        if bundle['actor_template']['entity_id']==RIGHT:
            sid='action:test.vessel_break'
            bundle['actor_template']['action_ids'].append(sid)
            bundle['action_catalog'].append(dict(source_definition_id=sid,display_name='Cause',owner_id=RIGHT,
                economy='NONE',resolution_kind='TYPED',target_kind='HOSTILE_ENTITY',range_ft=60,costs=[],
                parameters={'typed':{'effects':[{'type':'damage','flat':200,'damage_types':['force'],'applies_to':'target'}],
                    'numbers':{},'duration':{'kind':'instant'},'riders':[]}}))
        if success and bundle['actor_template']['entity_id']!=LEFT:
            for action in bundle['action_catalog']:
                typed=action.get('parameters',{}).get('typed')
                if typed is not None:typed.setdefault('numbers',{})['dex_save_bonus']=10000
            bundle['actor_template']['saving_throws']['DEX']=10000
    c,t,m=triple_fight(tmp_path,[*OWNED,vessel.HARM_BODY,*([vessel.THEATER] if domain else []),
        *([INC] if incarnation else [])],spheres=[SPHERE],third_ally=ally,left_score=214,bundle_edit=cause)
    raise_at(c,t,m,5,5);next_turn(t,m)
    if domain:assert act(t,m,vessel.THEATER)['status']=='COMMITTED'
    if incarnation:assert act(t,m,INC)['status']=='COMMITTED'
    assert all(a.current_hp==1000 for a in reload(c,m).state.actors.values())
    turn(t,m,RIGHT)
    return c,t,m


@pytest.mark.parametrize('ai_owner,ai_attacker',[(False,False),(False,True),(True,True)])
def test_broken_vessel_asks_manual_owner_on_enemy_ai_turn_and_explodes(tmp_path,ai_owner,ai_attacker):
    c,t,m=broken_scene(tmp_path)
    if ai_owner:c.set_controller_mode(m,actor_id=LEFT,controller_mode='LOCAL_AUTO')
    before=reload(c,m)
    _,prompts=resolve(action_sender(c,t,m,'Cause',target_id=LEFT,ai=ai_attacker),{
        'choice:needle.vessel_theater_broken':[OTHER],'choice:needle.vessel_explosion_type':['force']})
    e=reload(c,m)
    if not ai_owner:
        assert any(p['context']['reaction_source_id']=='choice:needle.vessel_theater_broken' for p in prompts)
        assert any(p['context']['reaction_source_id']=='choice:needle.vessel_explosion_type' for p in prompts)
        domain_prompt=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.vessel_theater_broken')
        explosion_prompt=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.vessel_explosion_type')
        domain_text=domain_prompt['moment']
        explosion_text=explosion_prompt['moment']
        missing=[('Domain',wording) for wording in ('within 5 feet of it', 'Dexterity saving throw', 'on a failure',
            'Restrained', "until the end of that creature's next turn") if wording not in domain_text]
        missing += [('Incarnation',wording) for wording in ('each hostile creature within 5 feet of it',
            'Dexterity saving throw', 'on a failure', 'Tension Mark', '3d8 Piercing or Force damage',
            'spend for a Tension Response') if wording not in explosion_text]
        assert not missing, missing
        assert all('Puppet' in str(p) or 'Substitute Harm Body' in str(p) for p in prompts)
    else:assert prompts==[]
    assert not active(e)
    broken=next(z for z in e.state.zones.values() if placed.data(z).get('tag')=='vessel')
    assert not broken.active and placed.data(broken)['hp']==0
    for aid in (RIGHT,OTHER):
        assert 1000-24<=e.state.actors[aid].current_hp<=1000-3
        assert bears_mark(e.state.actors[aid],LEFT,vessel.MARK)
    selected=next(a for a in (RIGHT,OTHER) if any(x.condition_id.endswith('.restrained') for x in e.state.actors[a].conditions.values()))
    if not ai_owner:assert selected==OTHER
    assert any(x.condition_id.endswith('.restrained') for x in e.state.actors[selected].conditions.values())
    assert not any(x.condition_id.endswith('.restrained') for x in e.state.actors[OTHER if selected==RIGHT else RIGHT].conditions.values())
    assert e.state.actors[LEFT].resources[POOL]==before.state.actors[LEFT].resources[POOL]-1
    assert e.state.actors[LEFT].current_hp>800
    assert len([v for v in e.events if v.event_type=='ZONE_REMOVED' and v.payload.get('reason')=='BROKEN'])==1
    assert not any('could not run' in str(v.payload) for v in e.events)


def test_incarnation_explosion_excludes_allies_and_dismissal_does_not_explode(tmp_path):
    c,t,m=broken_scene(tmp_path,domain=False,ally=True)
    resolve(action_sender(c,t,m,'Cause',target_id=LEFT),{'choice:needle.vessel_explosion_type':['piercing']})
    e=reload(c,m)
    assert e.state.actors[RIGHT].current_hp<1000 and e.state.actors[OTHER].current_hp==1000
    assert not bears_mark(e.state.actors[OTHER],LEFT,vessel.MARK)
    c,t,m=fight(tmp_path/'dismiss',[*OWNED,INC],spheres=[SPHERE])
    assert act(t,m,INC)['status']=='COMMITTED'
    raise_at(c,t,m,4,7)
    assert act(t,m,'Dismiss Vessel')['status']=='COMMITTED'
    e=reload(c,m)
    assert e.state.actors[RIGHT].current_hp==1000 and not bears_mark(e.state.actors[RIGHT],LEFT,vessel.MARK)
    assert not any(v.event_type=='SAVING_THROW_ROLLED' for v in e.events)


def test_old_sealed_catalog_retains_legacy_capacity_and_origin_behavior(tmp_path):
    def legacy(b):
        b['typed_passives']=[r for r in b.get('typed_passives',[]) if r.get('block')!='vessel_native']
        for a in b['action_catalog']:
            p=a.get('parameters',{})
            if p.get('vessel_kit'):p['vessel_native']=False
            # A real old save already sealed its legacy text. Changing flags
            # after native compilation alone cannot recreate that catalog.
            if p.get('vessel_tension')=='guard':
                p['description']=vessel.RESPONSE_TEXT['guard'] + (
                    ' While Puppet Theater Domain is active, you can use one extra basic Tension Response each turn.')
            p.pop('vessel_native_origin',None)
            if p.get('vessel_strike'):p['player_only']=True
    c,t,m=fight(tmp_path,[*OWNED,vessel.THEATER],spheres=[SPHERE],bundle_edit=legacy)
    raise_at(c,t,m,4,7);next_turn(t,m)
    assert act(t,m,vessel.THEATER)['status']=='COMMITTED'
    next_turn(t,m);raise_at(c,t,m,3,7)
    e=reload(c,m)
    assert len(active(e))==1
    assert not any(x.metadata.get('effect_origin') for x in e.legal_candidates())
    description=next(a.parameters['description'] for a in e.action_catalog.values() if a.owner_id==LEFT
        and (a.parameters or {}).get('vessel_tension')=='guard')
    assert 'whichever of your own marked creatures is nearest to you' in description


def test_raising_moves_the_new_vessel_inside_the_paid_activation(tmp_path):
    c,t,m=fight(tmp_path,OWNED,spheres=[SPHERE])
    state=t.state(m);menu=state['menu']
    e=c._load_session(m).engine
    candidate=next(x for x in e.legal_candidates() if x.display_name.startswith('Raise the Vessel (1 CP)')
        and x.destination.x==4 and x.destination.y==7)
    _,prompts=resolve(lambda answers:t.act(m,candidate.candidate_id,menu['decision_id'],menu['state_version'],
        state['last_sequence'],answers),{'choice:needle.vessel_raise_move':['cell:5,7']})
    e=reload(c,m);zone=active(e)[0]
    assert (zone.center.x,zone.center.y)==(5,7)
    assert e.state.actors[LEFT].resources[POOL]==99 and e.state.actors[LEFT].bonus_action_available
    assert any(p['context']['reaction_source_id']=='choice:needle.vessel_raise_move' for p in prompts)
    assert not any(g['label']=='Move Vessel (as you raise it)' for g in t.state(m)['menu']['actions'])


@pytest.mark.parametrize('incarnation',[False,True])
def test_one_bonus_action_moves_both_with_the_printed_budget(tmp_path,incarnation):
    c,t,m=fight(tmp_path,[*OWNED,vessel.TWO_BODY,*([INC] if incarnation else [])],spheres=[SPHERE])
    raise_at(c,t,m,4,7);next_turn(t,m)
    raise_at(c,t,m,2,6);next_turn(t,m)
    if incarnation:
        assert act(t,m,INC)['status']=='COMMITTED'
        next_turn(t,m)
    before=reload(c,m).state.actors[LEFT].resources[POOL]
    _,prompts=resolve(cell_send(t,m,'Move Vessel',(8,7)),{'choice:needle.vessel_group_move':['cell:1,6']})
    e=reload(c,m)
    assert {(z.center.x,z.center.y) for z in active(e)}=={(8,7),(1,6)}
    assert not e.state.actors[LEFT].bonus_action_available and e.state.actors[LEFT].resources[POOL]==before
    prompt=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.vessel_group_move')
    assert ('30 feet' if incarnation else '10 feet') in str(prompt)


def test_needle_rain_uses_thirty_feet_piercing_without_granting_basic_strike_range(tmp_path):
    c,t,m=fight(tmp_path,[*OWNED,'tianxia.talent.puppetry.needle_rain_marionette'],spheres=[SPHERE],
        left_attack_bonus=100,positions={LEFT:{'x':3,'y':6},RIGHT:{'x':8,'y':6}})
    raise_at(c,t,m,5,6);next_turn(t,m)
    e=reload(c,m)
    choices=[x for x in e.legal_candidates() if x.metadata.get('effect_origin') and x.target_ids==(RIGHT,)]
    assert choices and all('Needle Rain Marionette' in x.display_name for x in choices)
    resolve(strike_sender(c,t,m,active(e)[0]))
    e=reload(c,m)
    assert next(v for v in reversed(e.events) if v.event_type=='DAMAGE_COMMITTED').payload['damage_type']=='PIERCING'
    assert bears_mark(e.state.actors[RIGHT],LEFT,vessel.MARK)


def test_domain_capacity_and_geometry_follow_actual_owner_movement(tmp_path):
    c,t,m=fight(tmp_path,[*OWNED,vessel.THEATER],spheres=[SPHERE],
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':15,'y':6}},arena_edit=lambda arena:arena.update(terrain_regions=[]))
    assert act(t,m,vessel.THEATER)['status']=='COMMITTED'
    for xy in [(2,7),(3,7),(4,7)]:
        next_turn(t,m);raise_at(c,t,m,*xy)
    next_turn(t,m)
    for xy in [(9,6),(10,6)]:
        state=t.state(m);menu=state['menu']
        move=next(x for x in menu['moves'] if (x['destination']['x'],x['destination']['y'])==xy)
        resolve(lambda answers:t.act(m,move['candidate_id'],menu['decision_id'],menu['state_version'],state['last_sequence'],answers))
        e=reload(c,m)
        domain=next(z for z in e.state.zones.values() if z.active and z.trigger_profile.get('kind')=='TYPED' and z.zone_id not in {z.zone_id for z in placed.of(e,'vessel')})
        assert (domain.center.x,domain.center.y)==xy
        if xy==(9,6):next_turn(t,m)
    assert len(active(e))==2
    assert sum(e.grid.distance_ft(e.state.actors[LEFT].position,z.center)>30 for z in active(e))==1


def test_broken_vessel_successful_saves_do_not_restrain_or_deal_explosion_damage(tmp_path):
    c,t,m=broken_scene(tmp_path,success=True)
    resolve(action_sender(c,t,m,'Cause',target_id=LEFT),{
        'choice:needle.vessel_theater_broken':[OTHER],'choice:needle.vessel_explosion_type':['force']})
    e=reload(c,m)
    for aid in [RIGHT,OTHER]:
        assert e.state.actors[aid].current_hp==1000
        assert not any(x.condition_id.endswith('.restrained') for x in e.state.actors[aid].conditions.values())
    assert any(v.event_type=='SAVE_ROLLED' and v.payload.get('success') for v in e.events)


@pytest.mark.parametrize('legacy',[False,True])
def test_errand_changes_only_explicit_known_unattended_weight_limit(tmp_path,legacy):
    from combat.tabletop import normalize_map,to_battlefield
    def objects(arena):
        arena.update(to_battlefield(normalize_map({'width_squares':20,'height_squares':14,'objects':[
            {'id':1,'kind':'custom','name':'Message tray','x':4,'y':7,'weight_lb':40,'blocks':False},
            {'id':2,'kind':'custom','x':5,'y':7,'weight_lb':41,'blocks':False},
            {'id':3,'kind':'custom','x':2,'y':7,'blocks':False},
            {'id':4,'kind':'custom','x':2,'y':6,'weight_lb':2,'blocks':False,'unattended':False},
            {'id':5,'kind':'custom','x':1,'y':6,'weight_lb':10,'blocks':False}]})))
    def old(bundle):
        if legacy:
            for a in bundle['action_catalog']:a.get('parameters',{}).pop('thread_object_max_weight',None)
    c,t,m=fight(tmp_path,['PUPPETRY_BASE_THREAD_THE_OBJECT','tianxia.talent.puppetry.little_servant_s_errand'],
        spheres=[SPHERE],arena_edit=objects,bundle_edit=old)
    e=reload(c,m)
    candidates=[x for x in e.legal_candidates() if x.display_name=='Thread the Object: move object']
    assert {x.target_ids for x in candidates}==({('object:map.5',)} if legacy else {('object:map.1',),('object:map.5',)})
    if not legacy:
        resolve(action_sender(c,t,m,'Thread the Object: move object',target_id='object:map.1'),{
            'choice:needle.thread_object':['cell:4,8']})
        e=reload(c,m)
        assert e.state.objects['object:map.1'].position.y==8
        assert e.state.objects['object:map.1'].component['weight_lb']==40
        assert e.state.actors[LEFT].resources[POOL]==100


def test_guard_chooses_mark_bearer_and_expires_on_actual_owner_next_start(tmp_path):
    def setup(bundle):
        if bundle['actor_template']['entity_id']!=LEFT:return
        sid='action:test.guard_mark'
        bundle['actor_template']['action_ids'].append(sid)
        bundle['action_catalog'].append(dict(source_definition_id=sid,display_name='Prepare',owner_id=LEFT,
            economy='NONE',resolution_kind='TYPED',target_kind='HOSTILE_ENTITY',range_ft=60,
            parameters={'typed':{'effects':[{'type':'mark','mark':vessel.MARK,'applies_to':'target',
                'duration':{'kind':'until_end_of_your_next_turn'}}],'numbers':{},'riders':[],'duration':{'kind':'instant'}}}))
    c,t,m=triple_fight(tmp_path,OWNED,spheres=[SPHERE],bundle_edit=setup)
    raise_at(c,t,m,4,7);next_turn(t,m)
    for aid in [RIGHT,OTHER]:assert act(t,m,'Prepare',target_id=aid)['status']=='COMMITTED'
    _,prompts=resolve(lambda answers:act(t,m,'Tension Response: Guarding Vessel',answers,target_id=LEFT),
        {'choice:needle.vessel_guard_mark':[OTHER]})
    e=reload(c,m)
    assert bears_mark(e.state.actors[RIGHT],LEFT,vessel.MARK) and not bears_mark(e.state.actors[OTHER],LEFT,vessel.MARK)
    description=next(a.parameters['description'] for a in e.action_catalog.values() if a.owner_id==LEFT
        and (a.parameters or {}).get('vessel_tension')=='guard')
    assert 'you choose one of your marked creatures within your control range' in description
    assert 'nearest' not in description
    assert 'not on the creature you protect' in description
    assert 'No Action' in description and '+2 AC' in description
    assert 'until the start of your next turn' in description
    guard=next(x for x in e.state.actors[LEFT].conditions.values() if x.condition_id==vessel.GUARDED)
    assert guard.expires_on=='START_OF_SOURCE_NEXT_TURN'
    assert any('Protect Keeper' in str(p) for p in prompts)
    next_turn(t,m)
    assert not any(x.condition_id==vessel.GUARDED for x in reload(c,m).state.actors[LEFT].conditions.values())


def test_incarnation_activation_retains_responses_already_spent_this_turn(tmp_path):
    c,t,m=fight(tmp_path,[*OWNED,INC],spheres=[SPHERE],prepare=[{
        'type':'mark','mark':vessel.MARK,'applies_to':'target','duration':{'kind':'until_end_of_your_next_turn'}}])
    raise_at(c,t,m,4,7);next_turn(t,m)
    for activate in [False,True]:
        if activate:assert act(t,m,INC)['status']=='COMMITTED'
        assert act(t,m,'Prepare',target_id=RIGHT)['status']=='COMMITTED'
        assert act(t,m,'Tension Response: Cross the Limb',target_id=RIGHT)['status']=='COMMITTED'
        reload(c,m)
    assert act(t,m,'Prepare',target_id=RIGHT)['status']=='COMMITTED'
    assert not any(g['label'].startswith('Tension Response:') for g in t.state(m)['menu']['actions'])
    next_turn(t,m)
    for _ in range(2):
        assert act(t,m,'Prepare',target_id=RIGHT)['status']=='COMMITTED'
        assert act(t,m,'Tension Response: Cross the Limb',target_id=RIGHT)['status']=='COMMITTED'
        reload(c,m)
