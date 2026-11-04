"""Native Chains incarnation, active Lash and chosen binding survive table replay."""
import pytest
from combat import flight
from combat.ext.chains_sphere import INCARNATION, ANCHOR
from tests.auto_worker1_support import LEFT, RIGHT, act, fight, reload, action_sender
from tests.auto26_support import ascend, resolve, turn

LASH='TAL_CHAINS_CHAIN_LASH_BASE'


def lash_label(table,mid):
    return next(g['label'] for g in table.state(mid)['menu']['actions']
                if g['label'].startswith('Chain Lash') and 'Attach a Link' in g['label'])


@pytest.mark.parametrize('case',['manual','ai','legacy'])
def test_incarnation_native_flight_preserves_walk_and_old_rows(tmp_path,case):
    def old(bundle):
        if case!='legacy':return
        bundle['typed_passives']=[r for r in bundle.get('typed_passives',[]) if r.get('block')!='chains_sovereign']
        bundle['action_catalog']=[a for a in bundle['action_catalog'] if not a.get('parameters',{}).get('chains_sovereign_lash')]
        ids={a['source_definition_id'] for a in bundle['action_catalog']}
        bundle['actor_template']['action_ids']=[a for a in bundle['actor_template']['action_ids'] if a in ids]
        for action in bundle['action_catalog']:
            typed=action.get('parameters',{}).get('typed',{})
            for row in typed.get('effects',[]):row.pop('native_sovereign',None)
            if typed.get('source')==INCARNATION:
                typed['effects'].append({'type':'speed','applies_to':'self','becomes':40,'duration':'one_minute'})
    c,t,m=fight(tmp_path,[INCARNATION],bundle_edit=old)
    e=reload(c,m);assert flight.profile(e,e.state.actors[LEFT]).speed_ft==0
    resolve(action_sender(c,t,m,'Chain-Sovereign Incarnation',ai=case=='ai'))
    e=reload(c,m);a=e.state.actors[LEFT]
    assert e._effective_speed(a)==(40 if case=='legacy' else 30)
    assert flight.profile(e,a).speed_ft==(0 if case=='legacy' else 40)
    assert flight.profile(e,a).hover==(case!='legacy')
    assert a.resources['resource:core.qi']==85
    if case=='manual':
        assert ascend(c,t,m,LEFT)['status']=='COMMITTED'
        assert reload(c,m).state.actors[LEFT].position.z==1


@pytest.mark.parametrize('success',[False,True])
def test_incarnation_presence_follows_actual_move_and_expires_at_target_next_start(tmp_path,success):
    c,t,m=fight(tmp_path,[INCARNATION],right_score=214 if success else 14,
        positions={LEFT:{'x':1,'y':1},RIGHT:{'x':7,'y':1}})
    resolve(lambda answers:act(t,m,'Chain-Sovereign Incarnation',answers))
    e=reload(c,m)
    assert not any(v.event_type=='SAVE_ROLLED' and v.actor_id==RIGHT for v in e.events)
    state=t.state(m);menu=state['menu']
    move=next(x for x in menu['moves'] if x['destination']['x']==3 and x['destination']['y']==1
              and x['destination'].get('z',0)==0)
    assert t.act(m,move['candidate_id'],menu['decision_id'],menu['state_version'],state['last_sequence'],[])['status']=='COMMITTED'
    e=reload(c,m);zone=next(z for z in e.state.zones.values() if z.active)
    assert zone.center.x==3 and zone.trigger_profile['follows_owner']
    turn(t,m,RIGHT)
    e=reload(c,m);save=next(v for v in reversed(e.events) if v.event_type=='SAVE_ROLLED' and v.actor_id==RIGHT)
    assert save.payload['success']==success
    if not success:
        assert any(x.condition_id=='condition:typed.bound' for x in e.state.actors[RIGHT].conditions.values())
        assert e._effective_speed(e.state.actors[RIGHT])==20
    else:assert e._effective_speed(e.state.actors[RIGHT])==25
    turn(t,m,LEFT)
    e=reload(c,m)
    assert e._effective_speed(e.state.actors[RIGHT])==(25 if success else 20)


def test_active_lash_is_exactly_sixty_feet_and_not_available_before_cast(tmp_path):
    c,t,m=fight(tmp_path,[INCARNATION,LASH],positions={LEFT:{'x':1,'y':1},RIGHT:{'x':13,'y':1}},left_attack_bonus=100)
    assert not any(g['label'].startswith('Chain Lash') for g in t.state(m)['menu']['actions'])
    resolve(lambda answers:act(t,m,'Chain-Sovereign Incarnation',answers))
    e=reload(c,m)
    options=[a for a in e.action_catalog.values() if a.parameters.get('chains_sovereign_lash')]
    assert options and all(a.range_ft==60 for a in options)
    resolve(lambda answers:act(t,m,lash_label(t,m),answers,target_id=RIGHT),
        {'choice:needle.chains_sovereign_binding':['prone']})
    e=reload(c,m)
    roll=next(r for r in reversed(e.rolls) if r.reason.startswith('DAMAGE:'))
    assert roll.expression.startswith('6d10')
    assert e.state.actors[RIGHT].current_hp<1000
    assert e.state.actors[LEFT].resources['resource:core.qi']==85


@pytest.mark.parametrize('choice',['pull','prone','bound','zero','reaction'])
def test_sovereign_failed_save_asks_one_binding_and_preserves_payment(tmp_path,choice):
    c,t,m=fight(tmp_path,[INCARNATION,LASH],left_attack_bonus=100,
        positions={LEFT:{'x':1,'y':1},RIGHT:{'x':5,'y':1}})
    resolve(lambda answers:act(t,m,'Chain-Sovereign Incarnation',answers))
    _,prompts=resolve(lambda answers:act(t,m,lash_label(t,m),answers,target_id=RIGHT),
        {'choice:needle.chains_sovereign_binding':[choice]})
    e=reload(c,m);a=e.state.actors[RIGHT]
    assert any('No additional Action' in str(p) and 'Sovereign Binding' in str(p) for p in prompts)
    assert e.state.actors[LEFT].resources['resource:core.qi']==85
    if choice=='pull':assert a.position.x==2
    if choice=='prone':assert any(x.condition_id=='condition:typed.prone' for x in a.conditions.values())
    if choice=='bound':assert any(x.condition_id=='condition:typed.bound' for x in a.conditions.values())
    if choice=='zero':assert e._effective_speed(a)==0
    if choice=='reaction':assert any(x.condition_id=='condition:typed.reaction_denied' for x in a.conditions.values())
    if choice in ('bound','zero','reaction'):
        expiry=f'START_OF_TURN_AT:{RIGHT}:1'
        conditions={i for i,x in a.conditions.items() if x.source_definition_id.endswith('#sovereign') and x.expires_on==expiry}
        modifiers={i for i,x in a.modifiers.items() if x.source_definition_id.endswith('#sovereign') and x.expires_on==expiry}
        assert conditions or modifiers
        turn(t,m,RIGHT)
        a=reload(c,m).state.actors[RIGHT]
        assert not conditions.intersection(a.conditions) and not modifiers.intersection(a.modifiers)


def test_successful_sovereign_binding_save_only_pulls_five_without_choice(tmp_path):
    c,t,m=fight(tmp_path,[INCARNATION,LASH],left_attack_bonus=100,right_score=214,
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':5,'y':6}})
    resolve(lambda answers:act(t,m,'Chain-Sovereign Incarnation',answers))
    _,prompts=resolve(lambda answers:act(t,m,lash_label(t,m),answers,target_id=RIGHT))
    e=reload(c,m)
    assert e.state.actors[RIGHT].position.x==4
    assert not any('chains_sovereign_binding' in str(p) for p in prompts)
    assert not any(x.condition_id in ('condition:typed.prone','condition:typed.bound','condition:typed.reaction_denied')
                   for x in e.state.actors[RIGHT].conditions.values())


def test_inactive_incarnation_does_not_add_its_damage_or_binding(tmp_path):
    c,t,m=fight(tmp_path,[INCARNATION,LASH],left_attack_bonus=100)
    resolve(lambda answers:act(t,m,lash_label(t,m),answers,target_id=RIGHT))
    e=reload(c,m)
    damage=[r for r in e.rolls if r.actor_id==LEFT and r.reason.startswith('DAMAGE:')]
    assert len(damage)==1 and damage[0].expression.startswith('4d8')
    assert e.state.actors[LEFT].resources['resource:core.qi']==100
    assert not any(v.event_type=='SAVE_ROLLED' and v.actor_id==RIGHT for v in e.events)


@pytest.mark.parametrize('success',[False,True])
def test_shackle_object_guards_both_printed_save_branches(tmp_path,success):
    source='tianxia.talent.chains.shackling_chain'
    c,t,m=fight(tmp_path,[source],right_score=214 if success else 14)
    resolve(lambda answers:act(t,m,'Shackling Chain',answers,target_id=RIGHT))
    e=reload(c,m)
    obj=next(o for o in e.state.objects.values() if not o.destroyed and o.component.get('name')=='Shackle')
    assert obj.maximum_hp==75
    assert obj.component['bound']['holder']==RIGHT
    held={x.condition_id for x in e.state.actors[RIGHT].conditions.values()}
    assert ('condition:typed.bound' if success else 'condition:typed.restrained') in held
    if success:
        turn(t,m,RIGHT)
        e=reload(c,m)
        assert not any(x.condition_id=='condition:typed.bound' for x in e.state.actors[RIGHT].conditions.values())
        assert e.state.objects[obj.object_id].destroyed


def test_sovereign_binding_limit_survives_reload_and_resets_on_actual_turn(tmp_path):
    def opt(bundle):
        for action in bundle['action_catalog']:
            if action['display_name']=='Prepare':action['parameters']['chains_sovereign_lash']=1
    c,t,m=fight(tmp_path,[INCARNATION,LASH],bundle_edit=opt,prepare_source=LASH,prepare_attack_bonus=100,
        prepare=[{'type':'attack','attack_kind':'cultivation_ranged','on_hit':[{'type':'damage','flat':1,'damage_types':['bludgeoning']}]}])
    resolve(lambda answers:act(t,m,'Chain-Sovereign Incarnation',answers))
    def count():
        return len([v for v in reload(c,m).events if v.event_type=='SAVE_ROLLED' and v.source_definition_id.startswith('action:test.worker1.')])
    for n in [1,1]:
        resolve(lambda answers:act(t,m,'Prepare',answers),{'choice:needle.chains_sovereign_binding':['prone']})
        assert count()==n
    turn(t,m,RIGHT);turn(t,m,LEFT)
    resolve(lambda answers:act(t,m,'Prepare',answers),{'choice:needle.chains_sovereign_binding':['prone']})
    assert count()==2


def test_native_incarnation_flight_and_catalog_expire_after_ten_rounds(tmp_path):
    c,t,m=fight(tmp_path,[INCARNATION,LASH],maximum_rounds=12,
        positions={LEFT:{'x':1,'y':1},RIGHT:{'x':10,'y':10}})
    resolve(lambda answers:act(t,m,'Chain-Sovereign Incarnation',answers))
    for _ in range(10):turn(t,m,RIGHT);turn(t,m,LEFT)
    e=reload(c,m)
    assert not any(x.condition_id==ANCHOR for x in e.state.actors[LEFT].conditions.values())
    assert flight.profile(e,e.state.actors[LEFT]).speed_ft==0
    assert not any('(Sovereign)' in g['label'] for g in t.state(m)['menu']['actions'])


@pytest.mark.parametrize('case',['airborne','ground','success','obstacle'])
def test_crane_native_descent_landing_obstacle_damage_and_reload(tmp_path,case):
    source='tianxia.talent.chains.drag_down_the_flying_crane'
    def flyer(bundle):
        if bundle['actor_template']['entity_id']==RIGHT or case=='obstacle':
            bundle['actor_template'].update(fly_speed_ft=10,hover=True)
    def platform(arena):
        if case=='obstacle':
            arena['terrain_regions'].append({'terrain_type':'BLOCKED','cells':[{'x':4,'y':6}],
                'movement_cost':1,'base_altitude_ft':5,'height_ft':20})
    c,t,m=fight(tmp_path,[source],bundle_edit=flyer,arena_edit=platform,
        right_score=214 if case=='success' else 14,
        positions={LEFT:{'x':3,'y':6,'z':8 if case=='obstacle' else 0},
                   RIGHT:{'x':4,'y':6,'z':2 if case=='ground' else 8}})
    before=reload(c,m).state.actors[RIGHT].movement_remaining_ft
    resolve(lambda answers:act(t,m,'Drag Down the Flying Crane',answers,target_id=RIGHT))
    e=reload(c,m);a=e.state.actors[RIGHT]
    assert a.position.z=={'airborne':2,'ground':0,'success':6,'obstacle':5}[case]
    ids={x.condition_id for x in a.conditions.values()}
    assert ('condition:typed.prone' in ids)==(case in ('ground','obstacle'))
    assert ('condition:typed.bound' in ids)==(case!='success')
    assert a.current_hp==1000-(e.state.actors[LEFT].proficiency_bonus if case=='obstacle' else 0)
    assert e.state.actors[LEFT].resources['resource:core.qi']==97
    assert a.movement_remaining_ft==before
    assert not any(v.event_type=='OPPORTUNITY_ATTACK' for v in e.events)
    turn(t,m,RIGHT);turn(t,m,LEFT)
    a=reload(c,m).state.actors[RIGHT]
    assert not any(x.condition_id=='condition:typed.bound' for x in a.conditions.values())


def test_crane_new_row_rejects_airborne_nonflyer(tmp_path):
    source='tianxia.talent.chains.drag_down_the_flying_crane'
    def suspended(bundle):
        if bundle['actor_template']['entity_id']==RIGHT:
            bundle['actor_template'].update(hover=True)
    c,t,m=fight(tmp_path,[source],bundle_edit=suspended,
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':4,'y':6,'z':4}})
    assert not any(g['label']=='Drag Down the Flying Crane' for g in t.state(m)['menu']['actions'])
    reload(c,m)


def test_crane_markerless_catalog_keeps_its_previous_displacement(tmp_path):
    source='tianxia.talent.chains.drag_down_the_flying_crane'
    def legacy(bundle):
        if bundle['actor_template']['entity_id']==RIGHT:
            bundle['actor_template'].update(fly_speed_ft=10,hover=True)
        for action in bundle['action_catalog']:
            typed=action.get('parameters',{}).get('typed',{})
            if typed.get('source')!=source:continue
            for row in typed['effects']:
                for branch in ('on_fail','on_success'):
                    for effect in row.get(branch,[]):
                        if effect.get('type')=='chains_crane_descent':
                            effect.clear();effect.update(type='forced_movement',distance_ft=10)
    c,t,m=fight(tmp_path,[source],bundle_edit=legacy,
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':4,'y':6,'z':4}})
    resolve(lambda answers:act(t,m,'Drag Down the Flying Crane',answers,target_id=RIGHT))
    assert reload(c,m).state.actors[RIGHT].position.z==4


def test_crane_creature_occupancy_does_not_count_as_solid_obstacle_damage(tmp_path):
    source='tianxia.talent.chains.drag_down_the_flying_crane'
    def flyers(bundle):bundle['actor_template'].update(fly_speed_ft=10,hover=True)
    c,t,m=fight(tmp_path,[source],bundle_edit=flyers,
        positions={LEFT:{'x':4,'y':6,'z':3},RIGHT:{'x':4,'y':6,'z':8}})
    resolve(lambda answers:act(t,m,'Drag Down the Flying Crane',answers,target_id=RIGHT))
    e=reload(c,m)
    assert e.state.actors[RIGHT].position.z==4
    assert e.state.actors[RIGHT].current_hp==1000
