"""Shadow choices, actual area timing and native persisted movement capabilities."""
import pytest

from combat import flight, zones
from combat.typed_executor import bears_mark, clock_expiry
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload, action_sender
from tests.test_auto42_stars import turn, cell_send, ascend
from tests.test_auto45_metal import settle
from tests.test_auto62_destruction import triple_fight, OTHER, cell_sender
from tests.b3f2_support import cell_send

P = 'tianxia.talent.shadow.'
SECOND = 'TAL_SHADOW_SECOND_SILHOUETTE'
COURT = 'TAL_SHADOW_COURT_OF_THE_SECOND_SILHOUETTE'
WORLD = 'TAL_SHADOW_WORLD_OF_LIVING_SHADOWS'
SOVEREIGN = 'TAL_SHADOW_SHADOW_SOVEREIGN_INCARNATION'


@pytest.mark.parametrize('case', ['accept', 'decline', 'ai', 'legacy'])
def test_fang_mark_is_a_real_optional_hit_choice_and_expires(tmp_path, case):
    def legacy(bundle):
        if case == 'legacy':
            for a in bundle['action_catalog']:
                for e in a.get('parameters', {}).get('typed', {}).get('effects', []):
                    for hit in e.get('on_hit', []):
                        if hit.get('type') == 'shadow_fang_mark':
                            hit.update(type='mark', mark='Shadow Mark', applies_to='target',
                                       duration={'kind':'until_removed'})
    c, t, m = fight(tmp_path, [P+'shadow_fang'], left_attack_bonus=100, bundle_edit=legacy)
    _, prompts = settle(action_sender(c,t,m,'Shadow Fang',ai=case=='ai',target_id=RIGHT),
                        lambda p: [] if case=='decline' else ['mark'])
    e = reload(c,m)
    assert e.state.actors[RIGHT].current_hp < 1000
    assert bears_mark(e.state.actors[RIGHT],LEFT,'Shadow Mark') == (case!='decline')
    assert e.state.actors[LEFT].resources['resource:core.qi'] == 100
    if case in ('accept','decline'):
        assert len(prompts) == 1 and 'Visitor' in str(prompts[0])
        assert 'No extra cost' in str(prompts[0]) and 'next turn starts' in str(prompts[0])
    if case=='legacy':assert not prompts
    if case=='ai':c.set_controller_mode(m,actor_id=LEFT,controller_mode='MANUAL')
    turn(t,m,RIGHT);turn(t,m,LEFT)
    assert not bears_mark(reload(c,m).state.actors[RIGHT],LEFT,'Shadow Mark')


def test_fang_miss_does_not_offer_the_hit_mark(tmp_path):
    c,t,m=fight(tmp_path,[P+'shadow_fang'],left_attack_bonus=-100)
    _,prompts=settle(lambda a:act(t,m,'Shadow Fang',a,target_id=RIGHT))
    e=reload(c,m)
    assert not [v for v in e.events if v.event_type=='ATTACK_ROLLED'][-1].payload['provisional_hit']
    assert not prompts and not bears_mark(e.state.actors[RIGHT],LEFT,'Shadow Mark')


@pytest.mark.parametrize('case',['hit','miss','legacy_miss'])
def test_grasping_needs_this_uses_actual_mark_not_an_old_mark(tmp_path,case):
    def legacy(bundle):
        if case=='legacy_miss':
            for a in bundle['action_catalog']:
                for e in a.get('parameters',{}).get('typed',{}).get('effects',[]):
                    if e.get('type')=='shadow_grasping':e.update(type='if_marked',mark='Shadow Mark')
    c,t,m=fight(tmp_path,[SECOND,P+'grasping_silhouette'],
        left_attack_bonus=100 if case=='hit' else -100,bundle_edit=legacy,
        prepare=[{'type':'mark','mark':'Shadow Mark','applies_to':'target','duration':{'kind':'one_minute'}}])
    settle(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    start=len(reload(c,m).events)
    settle(lambda a:act(t,m,'Second Silhouette: Unwilling Creature + Grasping Silhouette',a,target_id=RIGHT))
    e=reload(c,m)
    assert any(v.event_type=='SAVE_ROLLED' for v in e.events[start:]) == (case!='miss')
    assert any(c.condition_id.endswith('.restrained') for c in e.state.actors[RIGHT].conditions.values()) == (case!='miss')
    assert e.state.actors[LEFT].resources['resource:core.qi']==99
    if case=='hit':
        turn(t,m,RIGHT);turn(t,m,LEFT)
        assert not any(c.condition_id.endswith('.restrained') for c in reload(c,m).state.actors[RIGHT].conditions.values())


@pytest.mark.parametrize('case',['manual','ai','legacy'])
def test_sovereign_flight_is_native_hover_and_preserves_walking(tmp_path,case):
    def legacy(bundle):
        if case=='legacy':
            for a in bundle['action_catalog']:
                effects=a.get('parameters',{}).get('typed',{}).get('effects',[])
                effects[:]=[e for e in effects if e.get('condition')!='shadow_sovereign_flight']
    c,t,m=fight(tmp_path,[SOVEREIGN],bundle_edit=legacy)
    assert flight.profile(reload(c,m),reload(c,m).state.actors[LEFT]).speed_ft==0
    settle(action_sender(c,t,m,'Shadow-Sovereign Incarnation',ai=case=='ai'))
    e=reload(c,m);a=e.state.actors[LEFT]
    assert flight.profile(e,a).speed_ft==(0 if case=='legacy' else 60)
    assert flight.profile(e,a).hover==(case!='legacy')
    assert e._effective_speed(a)==30 and a.resources['resource:core.qi']==85
    if case=='manual':
        assert ascend(c,t,m,LEFT)['status']=='COMMITTED'
        assert reload(c,m).state.actors[LEFT].position.z==1


def test_sovereign_flight_really_ends_after_one_minute(tmp_path):
    c,t,m=fight(tmp_path,[SOVEREIGN],maximum_rounds=12)
    settle(lambda a:act(t,m,'Shadow-Sovereign Incarnation',a))
    e=reload(c,m)
    assert flight.profile(e,e.state.actors[LEFT]).speed_ft==60
    for _ in range(10):turn(t,m,RIGHT);turn(t,m,LEFT)
    e=reload(c,m)
    assert flight.profile(e,e.state.actors[LEFT]).speed_ft==0


@pytest.mark.parametrize('success',[False,True])
@pytest.mark.parametrize('ai',[False,True])
def test_world_only_saves_at_turn_start_and_repeats_on_later_turns(tmp_path,success,ai):
    c,t,m=fight(tmp_path,[WORLD],right_score=214 if success else 14)
    settle(cell_sender(c,t,m,'World of Living Shadows',(4,6),ai))
    e=reload(c,m)
    assert e.state.actors[RIGHT].current_hp==1000
    assert not any(v.event_type=='SAVE_ROLLED' for v in e.events)
    if ai:c.set_controller_mode(m,actor_id=LEFT,controller_mode='MANUAL')
    turn(t,m,RIGHT)
    e=reload(c,m)
    damage=[v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and RIGHT in v.target_ids]
    assert len(damage)==1 and damage[0].payload['hp_damage']>0
    roll=[v for v in e.events if v.event_type=='DAMAGE_ROLLED'][-1]
    assert len(roll.payload['dice'])==4
    assert damage[0].payload['hp_damage']==roll.payload['total']//2 if success else damage[0].payload['hp_damage']==roll.payload['total']
    assert any(c.condition_id.endswith('.restrained') for c in e.state.actors[RIGHT].conditions.values()) == (not success)
    turn(t,m,LEFT);turn(t,m,RIGHT)
    e=reload(c,m)
    assert len([v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and RIGHT in v.target_ids])==2
    assert e.state.actors[LEFT].resources['resource:core.qi']==88


@pytest.mark.parametrize('field',[COURT,WORLD])
def test_field_ally_stealth_checks_are_advantage_and_end_with_concentration(tmp_path,field):
    c,t,m=fight(tmp_path,[field],prepare_target='ALLY_OR_SELF',
        prepare=[{'type':'skill_check','ability':'dex','skill':'Stealth','dc':15,'applies_to':'self'}],
        cause=[{'type':'damage','flat':100,'damage_types':['fire'],'applies_to':'target'}])
    if field==COURT:settle(lambda a:act(t,m,'Court of the Second Silhouette',a))
    else:settle(cell_send(t,m,'World of Living Shadows',(4,6)))
    settle(lambda a:act(t,m,'Prepare',a,target_id=LEFT))
    e=reload(c,m)
    assert [v for v in e.events if v.event_type=='CHECK_ROLLED'][-1].payload['actor']['mode']=='ADVANTAGE'
    assert (3,6) not in zones.difficult_cells(e,e.state.actors[LEFT])
    turn(t,m,RIGHT)
    # Actual damage forces a DC 50 Concentration check, which this caster fails.
    settle(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    assert reload(c,m).state.actors[LEFT].concentration is None
    turn(t,m,LEFT)
    settle(lambda a:act(t,m,'Prepare',a,target_id=LEFT))
    e=reload(c,m)
    assert [v for v in e.events if v.event_type=='CHECK_ROLLED'][-1].payload['actor']['mode']=='NORMAL'


def test_court_asks_after_each_actual_failed_save_and_has_no_blanket_difficult_ground(tmp_path):
    c,t,m=fight(tmp_path,[COURT])
    settle(lambda a:act(t,m,'Court of the Second Silhouette',a))
    e=reload(c,m)
    assert not zones.difficult_cells(e,e.state.actors[LEFT])
    assert not zones.difficult_cells(e,e.state.actors[RIGHT])
    # The actual End Turn transaction carries the player's turn-start answer.
    _,prompts=settle(lambda a:act(t,m,'end',a),lambda p:['speed'])
    e=reload(c,m)
    assert any(p['context']['reaction_source_id']=='choice:needle.shadow_court_outcome' for p in prompts)
    assert e._effective_speed(e.state.actors[RIGHT])==20
    turn(t,m,LEFT)
    _,prompts=settle(lambda a:act(t,m,'end',a),lambda p:['reactions'])
    e=reload(c,m)
    assert any(p['context']['reaction_source_id']=='choice:needle.shadow_court_outcome' for p in prompts)
    assert e._effective_speed(e.state.actors[RIGHT])==30
    assert any(c.condition_id.endswith('.reaction_denied') for c in e.state.actors[RIGHT].conditions.values())


@pytest.mark.parametrize('ai',[False,True])
def test_lingering_chooses_an_older_mark_and_records_eight_hours(tmp_path,ai):
    def pb_two(bundle):
        if bundle['actor_template']['entity_id']==LEFT:
            bundle['actor_template']['proficiency_bonus']=2
            for a in bundle['action_catalog']:
                numbers=a.get('parameters',{}).get('typed',{}).get('numbers')
                if numbers:numbers['pb']=2
    c,t,m=triple_fight(tmp_path,[SECOND,P+'lingering_trace'],bundle_edit=pb_two)
    settle(lambda a:act(t,m,'Second Silhouette: Willing Creature + Lingering Trace',a,target_id=LEFT))
    turn(t,m,RIGHT);turn(t,m,LEFT)
    settle(lambda a:act(t,m,'Second Silhouette: Unwilling Creature + Lingering Trace',a,target_id=OTHER))
    turn(t,m,RIGHT);turn(t,m,LEFT)
    _,prompts=settle(action_sender(c,t,m,'Second Silhouette: Unwilling Creature + Lingering Trace',
                                  ai=ai,target_id=RIGHT),lambda p:[OTHER])
    e=reload(c,m)
    if not ai:
        assert any('older mark' in str(p) and '8 hours' in str(p) for p in prompts)
        assert bears_mark(e.state.actors[LEFT],LEFT,'Shadow Mark')
        assert not bears_mark(e.state.actors[OTHER],LEFT,'Shadow Mark')
    else:
        # Automatic selection ends the oldest; it still keeps exactly PB marks.
        assert not bears_mark(e.state.actors[LEFT],LEFT,'Shadow Mark')
        assert bears_mark(e.state.actors[OTHER],LEFT,'Shadow Mark')
    assert bears_mark(e.state.actors[RIGHT],LEFT,'Shadow Mark')
    mark=next(c for c in e.state.actors[RIGHT].conditions.values() if c.data.get('lingering'))
    assert mark.expires_on==clock_expiry(e,'hours',8)
    assert e.state.actors[LEFT].resources['resource:core.qi']==97


@pytest.mark.parametrize('talent,label',[
    ('TAL_SHADOW_SEIZE_THE_SECOND_BODY','Seize the Second Body: Reduce Speed to 0'),
    ('TAL_SHADOW_SEVER_THE_SECOND_SILHOUETTE','Sever the Second Silhouette')])
@pytest.mark.parametrize('legacy',[False,True])
def test_seize_and_sever_require_your_actual_mark_before_payment(tmp_path,talent,label,legacy):
    def old(bundle):
        if legacy:
            for action in bundle['action_catalog']:
                if action.get('parameters',{}).get('typed',{}).get('source')==talent:
                    action['parameters'].pop('target_requires_condition',None)
                    action['parameters']['typed'].pop('target_requires_mark',None)
    c,t,m=fight(tmp_path,[talent],bundle_edit=old,
        prepare=[{'type':'mark','mark':'Shadow Mark','applies_to':'target',
                  'duration':{'kind':'until_start_of_your_next_turn'}}])
    offered=lambda:any(g['label']==label for g in t.state(m)['menu']['actions'])
    assert offered()==legacy
    assert reload(c,m).state.actors[LEFT].resources['resource:core.qi']==100
    settle(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    assert offered()
    settle(lambda a:act(t,m,label,a,target_id=RIGHT))
    e=reload(c,m)
    assert e._effective_speed(e.state.actors[RIGHT])==0
    assert e.state.actors[LEFT].resources['resource:core.qi']==(88 if talent.endswith('SEVER_THE_SECOND_SILHOUETTE') else 95)


def test_world_entry_and_start_share_the_same_per_turn_damage_limit(tmp_path):
    c,t,m=fight(tmp_path,[WORLD],right_score=214,cause_target='SELF',
                cause=[{'type':'teleport','applies_to':'self','distance_ft':60}])
    settle(cell_send(t,m,'World of Living Shadows',(1,1)))
    turn(t,m,RIGHT)
    for _ in range(2):
        settle(cell_send(t,m,'Cause',(15,1)))
        settle(cell_send(t,m,'Cause',(4,6)))
        reload(c,m)
    e=reload(c,m)
    assert len([v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and RIGHT in v.target_ids])==1
    assert len([v for v in e.events if v.event_type=='MOVEMENT_COMMITTED' and v.actor_id==RIGHT])==4
    turn(t,m,LEFT);turn(t,m,RIGHT)
    e=reload(c,m)
    assert len([v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and RIGHT in v.target_ids])==2


@pytest.mark.parametrize('legacy',[False,True])
def test_lingering_does_not_extend_an_old_mark_after_a_new_miss(tmp_path,legacy):
    def old(bundle):
        if legacy:
            for a in bundle['action_catalog']:
                for e in a.get('parameters',{}).get('typed',{}).get('effects',[]):
                    if e.get('type')=='shadow_lingering_trace':e.pop('choose_older',None)
    c,t,m=fight(tmp_path,[SECOND,P+'lingering_trace'],left_attack_bonus=-100,bundle_edit=old,
        prepare=[{'type':'mark','mark':'Shadow Mark','applies_to':'target','duration':{'kind':'one_minute'}}])
    settle(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    original=next(iter(reload(c,m).state.actors[RIGHT].conditions.values())).expires_on
    settle(lambda a:act(t,m,'Second Silhouette: Unwilling Creature + Lingering Trace',a,target_id=RIGHT))
    e=reload(c,m)
    mark=next(c for c in e.state.actors[RIGHT].conditions.values() if 'shadow_mark' in c.condition_id)
    assert bool(mark.data.get('lingering'))==legacy
    assert mark.expires_on==('UNTIL_REMOVED' if legacy else original)
