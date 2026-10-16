"""Second-pass Drunken Style transitions persist through the real table service."""
import pytest
from combat import flight
from combat.ext.drunken_style import REELING, EMPTY_CUP, LOOSE_CUP, CHAOS, SOVEREIGN, BROKEN, FLIGHT, LOOSE_AIM
from tests.auto_worker1_support import (LEFT, RIGHT, OTHER, act, ascend, fight, reload,
    action_sender, resolve, triple_fight)
from tests.hunt15_support import turn

GOURD = 'TAL_DRUNKEN_STYLE_BROKEN_GOURD_RECOVERY'


@pytest.mark.parametrize('talents,feet', [([], 10), ([LOOSE_CUP], 15), ([CHAOS], 20), ([CHAOS, LOOSE_CUP], 25)])
def test_reeling_uses_owned_distance_and_restores_ordinary_budget(tmp_path, talents, feet):
    c,t,m = fight(tmp_path, [REELING, *talents], positions={LEFT:{'x':1,'y':1},RIGHT:{'x':10,'y':10}})
    before = reload(c,m).state.actors[LEFT].movement_remaining_ft
    _, prompts = resolve(lambda answers: act(t,m,'Reeling Step',answers),
        {'choice:needle.drunken_reeling_move':[f'cell:{1+feet//5},1']})
    e = reload(c,m); a = e.state.actors[LEFT]
    assert a.position.x == 1+feet//5 and a.position.y == 1
    assert a.movement_remaining_ft == before and not a.bonus_action_available and a.action_available
    assert any(f'up to {feet} feet' in str(p) for p in prompts)
    assert not any(x.condition_id == 'condition:typed.drunken_reeling_terrain' for x in a.conditions.values())


def test_legacy_reeling_does_not_pick_up_new_owned_distance(tmp_path):
    def old(bundle):
        for action in bundle['action_catalog']:
            for eff in action.get('parameters',{}).get('typed',{}).get('effects',[]):
                eff.pop('step_v2',None)
    c,t,m = fight(tmp_path,[REELING,CHAOS,LOOSE_CUP],bundle_edit=old,
        positions={LEFT:{'x':1,'y':1},RIGHT:{'x':10,'y':10}})
    _,prompts=resolve(lambda answers:act(t,m,'Reeling Step',answers),
        {'choice:needle.drunken_reeling_move':['cell:3,1']})
    assert reload(c,m).state.actors[LEFT].position.x == 3
    assert any('up to 10 feet' in str(p) for p in prompts)


@pytest.mark.parametrize('legacy',[False,True])
def test_reeling_printed_creature_can_be_an_ally_with_legacy_control(tmp_path,legacy):
    from combat.ext.drunken_style import off_rhythm
    def old(bundle):
        if legacy:
            for action in bundle['action_catalog']:
                for row in action.get('parameters',{}).get('typed',{}).get('effects',[]):
                    row.pop('step_v2',None)
    c,t,m=triple_fight(tmp_path,[REELING],bundle_edit=old,third_ally=True)
    resolve(lambda answers:act(t,m,'Reeling Step',answers),
        {'choice:needle.drunken_reeling_test':[RIGHT if legacy else OTHER],'choice:needle.drunken_reeling_move':[]})
    e=reload(c,m)
    saves=[v for v in e.events if v.event_type=='SAVE_ROLLED' and v.actor_id==OTHER]
    assert bool(saves)==(not legacy)
    if saves:assert off_rhythm(e.state.actors[OTHER],LEFT)==(not saves[-1].payload['success'])


@pytest.mark.parametrize('accept,ai',[(True,False),(False,False),(True,True)])
def test_dodge_can_offer_free_reeling_with_focus_and_preserve_bonus(tmp_path,accept,ai):
    c,t,m = fight(tmp_path,[REELING,EMPTY_CUP],positions={LEFT:{'x':1,'y':1},RIGHT:{'x':10,'y':10}})
    before=reload(c,m).state.actors[LEFT]
    _,prompts=resolve(action_sender(c,t,m,'Dodge',ai=ai),
        {'choice:needle.empty_cup_dodge_reeling':['step'] if accept else [],
         'choice:needle.drunken_reeling_move':['cell:3,1']})
    a=reload(c,m).state.actors[LEFT]
    assert not a.action_available and a.bonus_action_available
    assert a.resources['resource:core.martial_focus']==before.resources['resource:core.martial_focus']
    assert (a.position != before.position)==accept
    assert a.movement_remaining_ft==before.movement_remaining_ft
    if not ai:
        assert any('No additional Action' in str(p) for p in prompts)


@pytest.mark.parametrize('case',['no_focus','heavy','legacy'])
def test_dodge_requirements_and_legacy_marker_do_not_grant_free_reeling(tmp_path,case):
    def edit(bundle):
        if case=='legacy':
            for row in bundle.get('typed_passives',[]):
                row.pop('dodge_reeling',None)
    kit={'items':[{'item_id':'tianxia.mortal.armor.imperial_plate_battle_dress','name':'Imperial Plate Battle Dress','quantity':1}]}
    c,t,m=fight(tmp_path,[REELING,EMPTY_CUP],bundle_edit=edit,left_kit=kit if case=='heavy' else None,
        prepare=[{'type':'spend_resource','resource_id':'resource:core.martial_focus','flat':1,'applies_to':'self'}] if case=='no_focus' else [],prepare_target='SELF')
    if case=='no_focus':resolve(lambda answers:act(t,m,'Prepare',answers))
    _,prompts=resolve(lambda answers:act(t,m,'Dodge',answers))
    e=reload(c,m)
    assert not any('empty_cup_dodge_reeling' in str(p) for p in prompts)
    assert e.state.actors[LEFT].position.x==3


@pytest.mark.parametrize('legacy',[False,True])
def test_sovereign_native_hover_and_legacy_control(tmp_path,legacy):
    def edit(bundle):
        if legacy:
            for action in bundle['action_catalog']:
                rows=action.get('parameters',{}).get('typed',{}).get('effects',[])
                rows[:]=[r for r in rows if r.get('condition')!='drunken_sovereign_flight']
    c,t,m=fight(tmp_path,[SOVEREIGN,REELING],bundle_edit=edit,
        prepare=[{'type':'speed','applies_to':'self','flat':-10,'duration':'one_minute'}],prepare_target='SELF',
        positions={LEFT:{'x':1,'y':1},RIGHT:{'x':10,'y':10}})
    assert flight.profile(reload(c,m),reload(c,m).state.actors[LEFT]).speed_ft==0
    resolve(lambda answers:act(t,m,'Sovereign Chaos-Step Incarnation',answers))
    e=reload(c,m);a=e.state.actors[LEFT]
    assert flight.profile(e,a).speed_ft==(0 if legacy else e._effective_speed(a))
    assert flight.profile(e,a).hover == (not legacy)
    if not legacy:
        assert ascend(c,t,m,LEFT)['status']=='COMMITTED'
        assert reload(c,m).state.actors[LEFT].position.z==1
        resolve(lambda answers:act(t,m,'Prepare',answers))
        e=reload(c,m);a=e.state.actors[LEFT]
        assert e._effective_speed(a)==20 and flight.profile(e,a).speed_ft==20


def test_sovereign_flight_expires_on_actual_tenth_round(tmp_path):
    c,t,m=fight(tmp_path,[SOVEREIGN],maximum_rounds=15)
    resolve(lambda answers:act(t,m,'Sovereign Chaos-Step Incarnation',answers))
    for _ in range(10):
        turn(t,m,RIGHT);turn(t,m,LEFT)
    e=reload(c,m)
    assert not any(x.condition_id==FLIGHT for x in e.state.actors[LEFT].conditions.values())
    assert flight.profile(e,e.state.actors[LEFT]).speed_ft==0


def test_loose_cup_aim_is_target_scoped_and_consumed(tmp_path):
    c,t,m=fight(tmp_path,[REELING,LOOSE_CUP,BROKEN],left_attack_bonus=100)
    resolve(lambda answers:act(t,m,'Reeling Step',answers),{'choice:needle.drunken_reeling_move':[]})
    e=reload(c,m)
    assert any(x.condition_id==LOOSE_AIM and x.data['target_id']==RIGHT for x in e.state.actors[LEFT].conditions.values())
    label=next(g['label'] for g in t.state(m)['menu']['actions'] if g['label'].startswith('Broken-Rhythm Strike:'))
    resolve(lambda answers:act(t,m,label,answers,target_id=RIGHT))
    e=reload(c,m)
    roll=next(r for r in reversed(e.rolls) if r.actor_id==LEFT and r.reason.startswith('ATTACK:'))
    assert roll.mode=='ADVANTAGE'
    assert not any(x.condition_id==LOOSE_AIM for x in e.state.actors[LEFT].conditions.values())


def test_loose_cup_unused_aim_expires_at_actual_turn_end(tmp_path):
    c,t,m=fight(tmp_path,[REELING,LOOSE_CUP])
    resolve(lambda answers:act(t,m,'Reeling Step',answers),{'choice:needle.drunken_reeling_move':[]})
    assert any(x.condition_id==LOOSE_AIM for x in reload(c,m).state.actors[LEFT].conditions.values())
    turn(t,m,RIGHT)
    assert not any(x.condition_id==LOOSE_AIM for x in reload(c,m).state.actors[LEFT].conditions.values())


@pytest.mark.parametrize('owns',[False,True])
def test_loose_cup_ignores_map_difficult_terrain_only_during_reeling(tmp_path,owns):
    def rough(arena):
        arena['terrain_regions'].append({'region_id':'test.rough','terrain_type':'OPEN','movement_cost':2,
            'description':'Synthetic rough ground',
            'cells':[{'x':x,'y':y} for x in range(20) for y in range(12)]})
    c,t,m=fight(tmp_path,[REELING,*([LOOSE_CUP] if owns else [])],arena_edit=rough,
        positions={LEFT:{'x':1,'y':1},RIGHT:{'x':10,'y':10}})
    _,prompts=resolve(lambda answers:act(t,m,'Reeling Step',answers),
        {'choice:needle.drunken_reeling_move':['cell:4,1'] if owns else []})
    e=reload(c,m);a=e.state.actors[LEFT]
    assert a.position.x==(4 if owns else 1)
    assert not any(x.condition_id=='condition:typed.drunken_reeling_terrain' for x in a.conditions.values())
    assert e.grid.base_movement_cost[(4,1)]==2
    state=t.state(m);menu=state['menu']
    ordinary=next(o for o in menu['moves'] if o['cost_ft']==10)
    assert t.act(m,ordinary['candidate_id'],menu['decision_id'],menu['state_version'],state['last_sequence'],[])['status']=='COMMITTED'
    assert reload(c,m).state.actors[LEFT].movement_remaining_ft==a.movement_remaining_ft-10


def test_loose_cup_does_not_ignore_magical_difficult_zone(tmp_path):
    c,t,m=fight(tmp_path,[REELING,LOOSE_CUP],prepare_target='SELF',prepare=[{'type':'zone'}],
        prepare_zone_spec={'shape':'sphere','size_ft':60,'centered_on_self':True,'difficult':'all',
            'duration':{'kind':'minutes','amount':1},'name':'Magical slowing field'},
        positions={LEFT:{'x':1,'y':1},RIGHT:{'x':10,'y':10}})
    resolve(lambda answers:act(t,m,'Prepare',answers))
    _,prompts=resolve(lambda answers:act(t,m,'Reeling Step',answers),
        {'choice:needle.drunken_reeling_move':['cell:2,1']})
    e=reload(c,m)
    assert e.state.actors[LEFT].position.x==2
    move=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.drunken_reeling_move')
    assert not any(o['id']=='cell:4,1' for o in move['choice']['options'])


@pytest.mark.parametrize('loose',[False,True])
def test_sovereign_reeling_distance_after_actual_turn_reset(tmp_path,loose):
    c,t,m=fight(tmp_path,[REELING,SOVEREIGN,*([LOOSE_CUP] if loose else [])],
        positions={LEFT:{'x':1,'y':1},RIGHT:{'x':10,'y':10}})
    resolve(lambda answers:act(t,m,'Sovereign Chaos-Step Incarnation',answers))
    turn(t,m,RIGHT);turn(t,m,LEFT)
    feet=35 if loose else 30
    resolve(lambda answers:act(t,m,'Reeling Step',answers),
        {'choice:needle.drunken_reeling_move':[f'cell:{1+feet//5},1']})
    e=reload(c,m)
    assert e.state.actors[LEFT].position.x==1+feet//5
    assert e.state.actors[LEFT].movement_remaining_ft==e._effective_speed(e.state.actors[LEFT])


@pytest.mark.parametrize('legacy',[False,True])
@pytest.mark.parametrize('ai',[False,True])
def test_gourd_new_success_movement_after_enemy_save_and_reload(tmp_path,legacy,ai):
    def edit(bundle):
        for action in bundle['action_catalog']:
            if action['display_name']=='Cause':action['parameters']['typed']['numbers']['save_dc']=12
        if legacy:
            for row in bundle.get('typed_passives',[]):
                if row.get('kind')=='broken_gourd_native':row['kind']='broken_gourd'
    c,t,m=fight(tmp_path,[GOURD],bundle_edit=edit,cause=[{'type':'save','ability':'dex','applies_to':'target',
        'on_fail':[{'type':'condition','condition':'prone','applies_to':'target'}]}])
    turn(t,m,RIGHT)
    for _ in range(12):
        c.set_controller_mode(m,actor_id=RIGHT,controller_mode='MANUAL')
        _,prompts=resolve(action_sender(c,t,m,'Cause',ai=ai,target_id=LEFT),
            {'choice:needle.broken_gourd_step':['cell:2,6']})
        e=reload(c,m)
        changes=[x for x in e.events if x.event_type=='D20_REWRITTEN' and x.source_definition_id==GOURD]
        if changes:break
    assert changes and changes[0].payload['result']['total']>=12
    assert e.state.actors[LEFT].position.x==(3 if legacy else 2)
    assert e.state.actors[LEFT].resources['resource:core.martial_focus']==0
    assert e.state.actors[LEFT].reaction_available
    assert any(x.event_type=='GM_RIDER' and 'may move' in str(x.payload) for x in e.events)==legacy
