"""Hundred-Breath Wait records actual observation, mark expiry and Snipe use."""
import pytest
from tests.auto_worker1_support import (LEFT, RIGHT, OTHER, act, fight, reload,
                                        action_sender, resolve, triple_fight, turn)
from tests.test_auto27_sniper import BOW

WAIT='TAL_SNIPER_HUNDRED_BREATH_WAIT'
OBS='condition:typed.sniper_observing'
MARK='condition:typed.sniper_wait'
TRAIN='TAL_SNIPER_SNIPER_TRAINING'
DEADLY='TAL_SNIPER_DEADLY_SHOT'
FOCUS='resource:core.martial_focus'


def has(e,kind):return any(c.condition_id==kind for c in e.state.actors[LEFT].conditions.values())


def begin(c,t,m,ai=False):
    _,prompts=resolve(action_sender(c,t,m,'Observe for Hundred-Breath Wait',ai=ai),
        {'choice:needle.sniper_wait_observe':[RIGHT]})
    if ai:c.set_controller_mode(m,actor_id=LEFT,controller_mode='MANUAL')
    e=reload(c,m)
    assert has(e,OBS) and not has(e,MARK)
    if not ai:assert any('No Action' in str(p) and 'Hundred-Breath Wait' in str(p) for p in prompts)
    assert not any(g['label']=='Mark with Hundred-Breath Wait' for g in t.state(m)['menu']['actions'])
    turn(t,m,RIGHT)
    if ai:c.set_controller_mode(m,actor_id=LEFT,controller_mode='LOCAL_AUTO')
    turn(t,m,LEFT)
    if ai:c.set_controller_mode(m,actor_id=LEFT,controller_mode='MANUAL')
    e=reload(c,m)
    assert has(e,MARK) and not has(e,OBS)
    assert e.state.actors[LEFT].resources['resource:core.qi']==100
    assert e.state.actors[LEFT].action_available and e.state.actors[LEFT].bonus_action_available


def shot(t,m):
    return next(g['label'] for g in t.state(m)['menu']['actions'] if g['label'].startswith('Snipe Shot:') and 'Deadly Shot' in g['label'])


@pytest.mark.parametrize('ai',[False,True])
def test_wait_observation_and_next_actual_snipe_adds_pb_once(tmp_path,ai):
    c,t,m=fight(tmp_path,[TRAIN,DEADLY,WAIT],left_kit=BOW,left_score=30,right_score=2,
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':6,'y':6}})
    begin(c,t,m,ai)
    resolve(action_sender(c,t,m,shot(t,m),ai=ai,target_id=RIGHT))
    e=reload(c,m)
    assert not has(e,MARK)
    attack=next(v for v in reversed(e.events) if v.event_type=='ATTACK_ROLLED' and v.actor_id==LEFT)
    assert e.state.actors[RIGHT].current_hp<1000
    damage=next(v for v in e.rolls if v.actor_id==LEFT and v.reason.startswith('DAMAGE:'))
    # DEX + PB + Deadly Shot's 10 all settle in one weapon damage packet.
    # The wait must add PB only once.
    assert damage.expression.endswith('+24')
    assert len([v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and v.actor_id==LEFT]) == 1
    assert e.state.actors[LEFT].resources[FOCUS]==1


@pytest.mark.parametrize('initial_focus',[0,1])
def test_wait_miss_regains_absent_focus_and_consumes_mark(tmp_path,initial_focus):
    def lose(bundle):
        if bundle['actor_template']['entity_id']==LEFT:
            for resource in bundle['actor_template']['resources']:
                if resource['resource_id']==FOCUS:resource['initial']=initial_focus
        if bundle['actor_template']['entity_id']==RIGHT:bundle['actor_template']['armor_class']=10000
    c,t,m=fight(tmp_path,[TRAIN,DEADLY,WAIT],left_kit=BOW,bundle_edit=lose,
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':6,'y':6}})
    begin(c,t,m)
    resolve(lambda answers:act(t,m,shot(t,m),answers,target_id=RIGHT))
    e=reload(c,m)
    assert not has(e,MARK) and e.state.actors[LEFT].resources[FOCUS]==1
    assert e.state.actors[RIGHT].current_hp==1000


def test_attacking_observed_target_cancels_before_a_full_round(tmp_path):
    c,t,m=fight(tmp_path,[TRAIN,DEADLY,WAIT],left_kit=BOW,left_score=30,
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':6,'y':6}})
    resolve(lambda answers:act(t,m,'Observe for Hundred-Breath Wait',answers),
        {'choice:needle.sniper_wait_observe':[RIGHT]})
    resolve(lambda answers:act(t,m,shot(t,m),answers,target_id=RIGHT))
    assert not has(reload(c,m),OBS)
    turn(t,m,RIGHT);turn(t,m,LEFT)
    assert not any(g['label']=='Mark with Hundred-Breath Wait' for g in t.state(m)['menu']['actions'])


def test_wait_marker_expires_after_real_ten_round_clock(tmp_path):
    c,t,m=fight(tmp_path,[WAIT],maximum_rounds=13,
        positions={LEFT:{'x':1,'y':1},RIGHT:{'x':10,'y':10}})
    begin(c,t,m)
    for _ in range(10):turn(t,m,RIGHT);turn(t,m,LEFT)
    assert not has(reload(c,m),MARK)


def test_old_unconditional_wait_modifier_is_not_in_new_snipe_catalog(tmp_path):
    c,t,m=fight(tmp_path,[TRAIN,DEADLY,WAIT],left_kit=BOW,left_score=30,
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':6,'y':6}})
    e=reload(c,m)
    assert not any(a.parameters.get('typed',{}).get('modifier',{}).get('id')==WAIT for a in e.action_catalog.values())
    resolve(lambda answers:act(t,m,shot(t,m),answers,target_id=RIGHT))
    e=reload(c,m)
    roll=next(v for v in e.rolls if v.actor_id==LEFT and v.reason.startswith('DAMAGE:'))
    assert roll.expression.endswith('+20')  # DEX + Deadly; no markerless PB


def test_unowned_or_markerless_wait_does_not_add_new_buttons(tmp_path):
    def old(bundle):
        bundle['typed_passives']=[r for r in bundle.get('typed_passives',[]) if r.get('block')!='sniper_wait']
        bundle['action_catalog']=[a for a in bundle['action_catalog'] if not a['display_name'].endswith('Hundred-Breath Wait')]
        ids={a['source_definition_id'] for a in bundle['action_catalog']}
        bundle['actor_template']['action_ids']=[i for i in bundle['actor_template']['action_ids'] if i in ids]
    for n,talents in enumerate([[],[WAIT]]):
        c,t,m=fight(tmp_path/str(n),talents,bundle_edit=old)
        assert not any('Hundred-Breath Wait' in g['label'] for g in t.state(m)['menu']['actions'])
        e=reload(c,m)
        assert not has(e,OBS) and not has(e,MARK)


def test_losing_sight_interrupts_observation_before_claiming_mark(tmp_path):
    c,t,m=fight(tmp_path,[WAIT],cause_target='SELF',cause=[
        {'type':'condition','condition':'invisible','applies_to':'self','duration':'until_removed'}])
    resolve(lambda answers:act(t,m,'Observe for Hundred-Breath Wait',answers),
        {'choice:needle.sniper_wait_observe':[RIGHT]})
    turn(t,m,RIGHT)
    resolve(lambda answers:act(t,m,'Cause',answers))
    assert not has(reload(c,m),OBS)
    turn(t,m,LEFT)
    assert not any(g['label']=='Mark with Hundred-Breath Wait' for g in t.state(m)['menu']['actions'])


def _typed_effects(engine, source_definition_id):
    """Typed effect rows for a menu entry; system rows have no catalog entry."""
    entry = engine.action_catalog.get(source_definition_id)
    typed = (getattr(entry, 'parameters', None) or {}).get('typed') or {}
    return typed.get('effects') or []


def test_attacking_another_target_ends_the_saved_mark(tmp_path):
    c,t,m=triple_fight(tmp_path,[WAIT])
    begin(c,t,m)
    menu=t.state(m)['menu']
    e=reload(c,m)
    label=next(g['label'] for g in menu['actions']
        if any(r.get('type')=='attack' for r in _typed_effects(e, g['source_definition_id']))
        and any(OTHER in o.get('target_ids',[]) for o in g['options']))
    resolve(lambda answers:act(t,m,label,answers,target_id=OTHER))
    e=reload(c,m)
    assert any(v.event_type=='ATTACK_ROLLED' and OTHER in v.target_ids and v.actor_id==LEFT for v in e.events)
    assert not has(e,MARK) and e.state.actors[LEFT].resources[FOCUS]==1


def test_manual_owner_can_decline_turn_start_mark_then_claim_it_free(tmp_path):
    c,t,m=fight(tmp_path,[WAIT])
    resolve(lambda answers:act(t,m,'Observe for Hundred-Breath Wait',answers),
        {'choice:needle.sniper_wait_observe':[RIGHT]})
    turn(t,m,RIGHT)
    _,prompts=resolve(lambda answers:act(t,m,'end',answers),{'choice:needle.sniper_wait_mark':[]})
    e=reload(c,m)
    assert has(e,OBS) and not has(e,MARK)
    assert any('one minute' in str(p) and 'No Action' in str(p) for p in prompts)
    resolve(lambda answers:act(t,m,'Mark with Hundred-Breath Wait',answers))
    e=reload(c,m)
    assert has(e,MARK) and not has(e,OBS)
    assert e.state.actors[LEFT].action_available and e.state.actors[LEFT].bonus_action_available
