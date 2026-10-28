"""Ash second pass: authority -> CombatService -> session intents -> cold replay."""
import pytest
from combat import zones, flight, stealth, senses, concentration
from combat.typed_executor import condition_rules, stored_healing_reductions, check_mode
from tests.auto_worker1_support import fight, act, reload, action_sender, settle, turn, LEFT, RIGHT, ALLY
from tests.test_auto62_destruction import cell_sender

P='tianxia.talent.ash.'
COURT=P+'court_of_the_last_ember'
WORLD=P+'world_after_the_fire'
CLONE=P+'ash_clone'


def cast(c,t,m,kind,ai=False):
    if kind==COURT:
        return settle(action_sender(c,t,m,'Court of the Last Ember',ai=ai))
    return settle(cell_sender(c,t,m,'World After the Fire',(4,6),ai))


@pytest.mark.parametrize('kind',[COURT,WORLD])
@pytest.mark.parametrize('ai',[False,True])
def test_fields_side_correct_and_continuous_after_reload(tmp_path,kind,ai):
    c,t,m=fight(tmp_path,[kind],spheres=['tianxia.sphere.ash'],ally=[],cl=17)
    cast(c,t,m,kind,ai)
    e=reload(c,m)
    for aid in ((LEFT,ALLY) if kind==COURT else (ALLY,)):
        a=e.state.actors[aid];r=condition_rules(a)
        assert any(x.get('damage_resistances')==['FIRE','NECROTIC'] for x in r)
        assert check_mode(a,'DEX','Stealth',engine=e)=='ADVANTAGE'
        assert (a.position.x,a.position.y) not in zones.difficult_cells(e,a)
        assert not any(x.get('temp_hp_denied') for x in r)
    r=condition_rules(e.state.actors[RIGHT])
    assert any(x.get('temp_hp_denied') for x in r)
    assert not any(x.get('damage_resistances') for x in r)
    assert not any(v.event_type=='SAVE_ROLLED' for v in e.events)
    if kind==WORLD:
        assert not any(x.get('damage_resistances') for x in condition_rules(e.state.actors[LEFT]))
        assert check_mode(e.state.actors[LEFT],'DEX','Stealth',engine=e)=='NORMAL'
        assert any(x.get('no_dash') for x in r)
        assert stored_healing_reductions(e,e.state.actors[RIGHT],20)==16
        assert stealth.can_hide(e,e.state.actors[ALLY])
    if ai:c.set_controller_mode(m,actor_id=LEFT,controller_mode='MANUAL')
    turn(t,m,RIGHT)
    e=reload(c,m)
    damage=[v for v in e.events if v.event_type=='DAMAGE_COMMITTED']
    assert damage and all(v.target_ids==(RIGHT,) for v in damage)
    assert e.state.actors[ALLY].current_hp==1000
    assert e.state.actors[LEFT].current_hp==1000
    assert not any(v.event_type=='GM_RIDER' for v in e.events)


@pytest.mark.parametrize('choice',['smothered','reactions','healing','speed'])
def test_court_fresh_failed_save_choice_and_target_next_start(tmp_path,choice):
    c,t,m=fight(tmp_path,[COURT],cl=17)
    cast(c,t,m,COURT)
    _,prompts=settle(lambda a:act(t,m,'end',a),lambda p:[choice])
    e=reload(c,m);foe=e.state.actors[RIGHT]
    assert len(prompts)==1 and 'ash_court_outcome' in str(prompts)
    if choice=='speed':assert e._effective_speed(foe)==20
    elif choice=='healing':assert stored_healing_reductions(e,foe,20)==10
    else:assert any(x.condition_id.endswith('.smothered' if choice=='smothered' else '.reaction_denied') for x in foe.conditions.values())
    turn(t,m,LEFT)
    _,prompts=settle(lambda a:act(t,m,'end',a),lambda p:['damage'])
    e=reload(c,m);foe=e.state.actors[RIGHT]
    assert len(prompts)==1 and foe.current_hp<1000
    assert e._effective_speed(foe)==30
    assert not any(x.condition_id.endswith(('.smothered','.reaction_denied')) for x in foe.conditions.values())
    assert stored_healing_reductions(e,foe,20)==20


def test_world_benefits_end_when_zone_ends(tmp_path):
    c,t,m=fight(tmp_path,[WORLD],cl=17,ally=[],
        cause=[{'type':'damage','flat':1000,'damage_types':['force'],'applies_to':'target'}])
    cast(c,t,m,WORLD)
    assert stealth.can_hide(reload(c,m),reload(c,m).state.actors[ALLY])
    turn(t,m,RIGHT)
    settle(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    e=reload(c,m)
    assert not any(x.get('damage_resistances') for x in condition_rules(e.state.actors[ALLY]))
    assert not any(x.get('no_dash') for x in condition_rules(e.state.actors[RIGHT]))
    assert not stealth.can_hide(e,e.state.actors[ALLY])


def test_clone_flight_destruction_patch_cold_reload_and_expiry(tmp_path):
    c,t,m=fight(tmp_path,[CLONE],cl=17,
        cause=[{'type':'damage','flat':1000,'damage_types':['force'],'applies_to':'target'}])
    settle(cell_sender(c,t,m,'Ash Clone',(3,5),False))
    e=reload(c,m);clone=next(a for a in e.state.actors.values() if a.summon)
    assert (clone.position.x,clone.position.y)==(3,5)
    assert flight.profile(e,clone).speed_ft==30 and flight.profile(e,clone).hover
    turn(t,m,RIGHT)
    settle(lambda a:act(t,m,'Cause',a,target_id=clone.entity_id))
    e=reload(c,m)
    patches=[z for z in zones.typed_zones(e) if z.trigger_profile.get('name')=='Ash Terrain']
    assert len(patches)==1
    assert (patches[0].center.x,patches[0].center.y)==(3,5)
    assert patches[0].trigger_profile.get('size_ft')==10
    turn(t,m,LEFT)
    assert not [z for z in zones.typed_zones(reload(c,m)) if z.trigger_profile.get('name')=='Ash Terrain']


def test_clone_patch_expires_at_omitted_owner_start_after_cold_reload(tmp_path):
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from combat.turn_decisions import omits_turn

    c,t,m=fight(tmp_path,[CLONE],cl=17,ally=[],positions={LEFT:{'x':3,'y':6},RIGHT:{'x':4,'y':6},ALLY:{'x':2,'y':6}},
        cause=[{'type':'damage','flat':10000,'damage_types':['force'],'applies_to':'target'}])

    def cold():
        nonlocal c,t
        e=reload(c,m)  # Exact persisted-state equality and mechanical replay PASS.
        c=CombatService(c.source_root,c.userdata_root)
        t=TabletopService(c,c.userdata_root)
        return e

    def patches(e):
        return [z for z in zones.typed_zones(e) if z.trigger_profile.get('name')=='Ash Terrain']

    settle(cell_sender(c,t,m,'Ash Clone',(3,5),False))
    clone=next(a for a in cold().state.actors.values() if a.summon)
    turn(t,m,RIGHT)
    settle(lambda a:act(t,m,'Cause',a,target_id=clone.entity_id))
    e=cold()
    assert len(patches(e))==1
    patch=patches(e)[0]
    assert patch.owner_id==LEFT and patch.trigger_profile['until_owner_next_start']
    assert (patch.center.x,patch.center.y)==(3,5)
    assert patch.trigger_profile['size_ft']==10
    assert patch.trigger_profile['difficult']

    # A living ally prevents defeat from ending the fight. This committed damage
    # makes the owner's next initiative slot omitted, rather than a dying turn.
    settle(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    e=cold()
    assert e.state.terminal_result is None and e.state.actors[ALLY].active
    assert omits_turn(e,LEFT) and not e.state.actors[LEFT].active
    assert len(patches(e))==1 and patches(e)[0].zone_id==patch.zone_id
    owner=e.state.actors[LEFT].model_dump(mode='json')
    owner_slot=e.state.initiative_order.index(LEFT)
    deadline=(e.state.round_number+int(owner_slot<=e.state.current_slot_index),owner_slot)

    # Cross the nominal owner START via supported End Turn transport. Cold-load
    # before every subsequent intent; other actors' boundaries must keep it.
    for _ in range(len(e.state.initiative_order)):
        assert len(patches(e))==1
        before=e.state.event_sequence
        settle(lambda a:act(t,m,'end',a))
        e=cold()
        if (e.state.round_number,e.state.current_slot_index)>deadline:
            break
    else:
        raise AssertionError('initiative did not cross the omitted owner slot')

    assert not patches(e)
    assert not e.state.zones[patch.zone_id].active
    boundary=[v for v in e.events if v.sequence>before]
    ended=[v for v in boundary if v.event_type=='ZONE_REMOVED' and v.payload.get('zone_id')==patch.zone_id]
    assert len(ended)==1 and ended[0].payload['reason']=='OWNER_NEXT_TURN'
    assert not any(v.actor_id==LEFT and v.event_type in ('TURN_STARTED','TURN_ENDED') for v in boundary)
    assert not any(v.event_type in ('SAVE_ROLLED','DAMAGE_COMMITTED') and
                   (v.actor_id==LEFT or LEFT in v.target_ids) for v in boundary)
    now=e.state.actors[LEFT].model_dump(mode='json')
    for key in ('turns_started','current_hp','resources','action_available','bonus_action_available','reaction_available','movement_remaining_ft'):
        assert now[key]==owner[key]
    assert e.state.current_actor_id!=LEFT and t.state(m)['menu']['actor_id']!=LEFT
    assert not patches(cold())  # Removal itself survives another cold replay.


def test_court_missed_attack_offers_ally_step_and_masks_only_hide(tmp_path):
    def armored(bundle):
        if bundle['actor_template']['entity_id']==ALLY:bundle['actor_template']['armor_class']=100
    c,t,m=fight(tmp_path,[COURT],cl=17,ally=[],bundle_edit=armored,
        cause=[{'type':'attack','attack_kind':'cultivation_ranged','on_hit':[]}],
        prepare=[{'type':'condition','condition':'hidden','applies_to':'target'},
                 {'type':'condition','condition':'invisible','applies_to':'target'}])
    cast(c,t,m,COURT)
    turn(t,m,RIGHT)
    _,prompts=settle(lambda a:act(t,m,'Cause',a,target_id=ALLY),
        lambda p:[o['id'] for o in p['choice']['options'] if o['id']!='cell:3,5'][:1])
    e=reload(c,m)
    assert any('field_miss_step' in str(p) for p in prompts)
    assert (e.state.actors[ALLY].position.x,e.state.actors[ALLY].position.y)!=(3,5)
    turn(t,m,LEFT)
    settle(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    e=reload(c,m);foe=e.state.actors[RIGHT]
    masks=senses.plugin_condition_masks(e,e.state.actors[LEFT],foe).get(RIGHT,set())
    assert any(foe.conditions[i].condition_id=='condition:typed.hidden' for i in masks)
    assert not any(foe.conditions[i].condition_id=='condition:typed.invisible' for i in masks)


@pytest.mark.parametrize('legacy',[False,True])
def test_clone_dismissal_never_creates_a_destruction_patch(tmp_path,legacy):
    def seal(bundle):
        if legacy:
            for summon in bundle.get('summons',[]):summon.get('summon',{}).pop('appearance_traits',None)
    c,t,m=fight(tmp_path,[CLONE],cl=17,bundle_edit=seal,
        cause=[{'type':'damage','flat':1000,'damage_types':['force'],'applies_to':'target'}])
    settle(cell_sender(c,t,m,'Ash Clone',(3,5),False))
    e=reload(c,m);clone=next(a for a in e.state.actors.values() if a.summon)
    assert flight.profile(e,clone).speed_ft==(0 if legacy else 30)
    turn(t,m,RIGHT)
    settle(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    e=reload(c,m)
    assert not e.state.actors[clone.entity_id].active
    assert not [z for z in zones.typed_zones(e) if z.trigger_profile.get('name')=='Ash Terrain']


@pytest.mark.parametrize('kind,feet,label',[(P+'ash_form',30,'Ash Form'),(P+'ash_sovereign_incarnation',60,'Ash-Sovereign Incarnation')])
@pytest.mark.parametrize('damage,expected',[('cold',10),('force',20),('radiant',20),('fire',0)])
def test_cinder_forms_native_flight_and_resistance(tmp_path,kind,feet,label,damage,expected):
    c,t,m=fight(tmp_path,[kind],cl=17,
        cause=[{'type':'damage','flat':20,'damage_types':[damage],'applies_to':'target'}])
    settle(lambda a:act(t,m,label,a))
    e=reload(c,m);owner=e.state.actors[LEFT]
    assert e._effective_speed(owner)==30
    assert flight.profile(e,owner).speed_ft==feet and flight.profile(e,owner).hover
    assert owner.position.x==3 and owner.position.y==6
    turn(t,m,RIGHT)
    hp=reload(c,m).state.actors[LEFT].current_hp
    settle(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    e=reload(c,m)
    if feet==30:expected=10 if damage=='fire' else 20
    assert hp-e.state.actors[LEFT].current_hp==expected


@pytest.mark.parametrize('mundane',[True,False])
def test_ash_form_physical_resistance_requires_actual_mundane_provenance(tmp_path,mundane):
    def seal(bundle):
        if bundle['actor_template']['entity_id']==RIGHT:
            for a in bundle['action_catalog']:
                if a['display_name']=='Cause':a['parameters']['typed']['mundane']=mundane
    c,t,m=fight(tmp_path,[P+'ash_form'],cl=17,bundle_edit=seal,
        cause=[{'type':'damage','flat':20,'damage_types':['bludgeoning'],'applies_to':'target'}])
    settle(lambda a:act(t,m,'Ash Form',a))
    turn(t,m,RIGHT)
    hp=reload(c,m).state.actors[LEFT].current_hp
    settle(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    assert hp-reload(c,m).state.actors[LEFT].current_hp==(10 if mundane else 20)


@pytest.mark.parametrize('legacy',[False,True])
def test_rolling_ashfall_ai_cannot_score_an_unperceived_enemy(tmp_path,legacy):
    def seal(bundle):
        if legacy:
            for action in bundle['action_catalog']:
                for effect in action.get('parameters',{}).get('typed',{}).get('effects',[]):
                    if effect.get('type')=='move_typed_area':effect.pop('perceived_aim',None)
    c,t,m=fight(tmp_path,['ASH_BASE_ASHFALL',P+'rolling_ashfall'],cl=17,spheres=['tianxia.sphere.ash'],bundle_edit=seal,
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':8,'y':6}},
        prepare=[{'type':'condition','condition':'invisible','applies_to':'target'}])
    settle(cell_sender(c,t,m,'Ashfall',(3,6),False))
    settle(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    e=reload(c,m)
    assert not senses.perceives(e,e.state.actors[LEFT],e.state.actors[RIGHT])
    settle(action_sender(c,t,m,'Rolling Ashfall',ai=True))
    e=reload(c,m);zone=next(z for z in zones.typed_zones(e) if z.owner_id==LEFT)
    assert (zone.center.x,zone.center.y)!=(3,6)
    assert zones._inside(e,e.state.actors[RIGHT],zone)==legacy
    assert e.state.actors[LEFT].resources['resource:core.qi']==99


def test_automatic_miss_step_uses_defenders_perception(tmp_path):
    def armored(bundle):
        if bundle['actor_template']['entity_id']==ALLY:bundle['actor_template']['armor_class']=100
    c,t,m=fight(tmp_path,[COURT],cl=17,ally=[],bundle_edit=armored,
        cause=[{'type':'condition','condition':'invisible','applies_to':'self'},
               {'type':'attack','attack_kind':'cultivation_ranged','on_hit':[]}])
    cast(c,t,m,COURT)
    turn(t,m,RIGHT)
    c.set_controller_mode(m,actor_id=ALLY,controller_mode='LOCAL_AUTO')
    settle(lambda a:act(t,m,'Cause',a,target_id=ALLY))
    e=reload(c,m)
    assert not senses.perceives(e,e.state.actors[ALLY],e.state.actors[RIGHT])
    assert (e.state.actors[ALLY].position.x,e.state.actors[ALLY].position.y)==(3,5)
