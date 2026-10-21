"""Chosen paths use native payment, passage, reactions, geometry and receipts."""
import pytest

from combat import ext, granted_movement, movement_steps
from combat.ext import needle
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from tests import lock8_support as S
from tests import test_tabletop_hunt6 as H
from tests.h1_support import ROOT
from tests.test_lock_choices import install
from tests.test_lock9_c16_passage import OVERRUN, grant, install_contract
from tests.test_lock9_granted_paths import request
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import answer


def route(actor, *xs):
    return (actor.position, *(Position(x=x, y=actor.position.y) for x in xs))


@pytest.mark.parametrize('kind', ['willing', 'granted'])
def test_owned_overrun_path_pays_real_cost_and_consumes_only_selected_passage(monkeypatch, kind):
    install_contract(monkeypatch)
    e = S.fight(S.bundle(OVERRUN), foe_at=(4,6))
    actor, foe = e.state.actors[S.ME], e.state.actors[S.FOE]
    grant(e, actor, foe, OVERRUN)
    e.grid.base_movement_cost[(5,6)] = 2
    e._wall_base = (frozenset(e.grid.blocked),frozenset(e.grid.opaque),frozenset(e.grid.cover),dict(e.grid.base_movement_cost))
    path = route(actor,4,5)
    before = e.state.model_dump(mode='json')
    assert granted_movement.path_cost(e,actor,path) == 20
    assert e.state.model_dump(mode='json') == before
    assert e.move_path(actor,path,OVERRUN,kind=kind,
        **({'feet':20} if kind=='granted' else {}),intent=request(e)) == 20
    assert actor.position == Position(x=5,y=6)
    assert actor.movement_remaining_ft == (10 if kind=='willing' else 30)
    with pytest.raises(ValueError):
        e.move_path(actor,route(actor,4,3),OVERRUN,kind=kind,
            **({'feet':20} if kind=='granted' else {}),intent=request(e))


@pytest.mark.parametrize('failure', ['occupied_end', 'wall', 'large_footprint', 'fear'])
def test_willing_path_rejects_invalid_whole_route_without_mutation(monkeypatch, failure):
    install_contract(monkeypatch)
    e = S.fight(S.bundle(OVERRUN), foe_at=(4,6))
    actor, foe = e.state.actors[S.ME], e.state.actors[S.FOE]
    grant(e,actor,foe,OVERRUN)
    path = route(actor,4,5)
    if failure == 'occupied_end':
        path = route(actor,4)
    elif failure == 'wall':
        e.grid.blocked.add((4,6))
    elif failure == 'large_footprint':
        old = e._footprint
        foe.position = Position(x=6,y=6)
        shape = old(actor).model_copy(update={'width_cells':2,'height_cells':2,
            'occupied_relative_cells':tuple(Position(x=x,y=y) for x in range(2) for y in range(2))})
        monkeypatch.setattr(e,'_footprint',lambda a:shape if (a if isinstance(a,str) else a.entity_id)==S.ME else old(a))
        e.grid.blocked.add((5,7))
    else:
        e._apply_condition(actor,'condition:typed.frightened','test:fear',S.FOE,expires_on='UNTIL_REMOVED')
        path = route(actor,2,3)
    e._wall_base = (frozenset(e.grid.blocked),frozenset(e.grid.opaque),frozenset(e.grid.cover),dict(e.grid.base_movement_cost))
    intent = request(e)
    before = e.state.model_dump(mode='json')
    with pytest.raises(ValueError):
        e.move_path(actor,path,OVERRUN,intent=intent)
    assert e.state.model_dump(mode='json') == before


@pytest.mark.parametrize('block', ['pin', 'occupant'])
def test_reaction_during_transit_keeps_legal_endpoint_and_real_payment(monkeypatch, block):
    install_contract(monkeypatch)
    e = S.fight(S.bundle(OVERRUN),foe_at=(4,6),ally=S.bundle(actor_id=S.ALLY),ally_at=(7,6))
    actor, foe = e.state.actors[S.ME],e.state.actors[S.FOE]
    grant(e,actor,foe,OVERRUN)
    def interrupt(engine,mover,previous,nxt,intent):
        if block == 'pin':
            engine._apply_condition(mover,'condition:typed.pinned','test:stop',S.FOE,expires_on='UNTIL_REMOVED')
        else:
            other = engine.state.actors[S.ALLY]
            old = other.position
            other.position = Position(x=5,y=6)
            engine._append_event('MOVEMENT_COMMITTED','test:block',actor_id=S.ALLY,
                payload={'destination':other.position.model_dump(mode='json'),
                    'path':[old.model_dump(mode='json'),other.position.model_dump(mode='json')], 'cost_ft':0,'forced':True})
    install(monkeypatch,'movement_step',interrupt)
    assert e.move_path(actor,route(actor,4,5),OVERRUN,intent=request(e)) == 10
    assert actor.position == Position(x=3,y=6) and actor.movement_remaining_ft == 20
    receipt = next(ev for ev in reversed(e.events) if ev.event_type=='MOVEMENT_COMMITTED' and ev.actor_id==S.ME)
    assert [p['x'] for p in receipt.payload['path']] == [3,4,3]


@pytest.mark.parametrize('stop', [False, True])
def test_overrun_plugin_path_pause_rolls_back_and_reloads(monkeypatch,tmp_path,stop):
    install_contract(monkeypatch)
    combat,table,mid = H.table_fight(tmp_path,[OVERRUN],ally_talents=[])
    def decide(engine,mover,previous,nxt,intent):
        if mover.entity_id != H.LEFT or nxt.x != 4:
            return
        picked = needle.ask(engine,intent,'PATH_STEP',mover,'choice:needle.lock11_path',['stop'],
            labels={'stop':'Stop moving'},name='Overrun passage',
            prompt='Stop after entering Right’s space? You return to the last free space and keep the movement already spent.',
            target_id=H.LEFT,automatic=False,allow_decline=True)
        if picked:
            return {'stop':True,'source_id':OVERRUN,'label':'Overrun movement stops after this step.'}
    install(monkeypatch,'movement_step',decide)
    def move(engine):
        actor = engine.state.actors[H.LEFT]
        grant(engine,actor,engine.state.actors[H.RIGHT],OVERRUN)
        assert engine.move_path(actor,route(actor,4,5),OVERRUN) == (10 if stop else 15)
    H.on_hold(monkeypatch,move)
    state=table.state(mid);menu=state['menu']
    cid=next(g['options'][0]['candidate_id'] for g in menu['actions'] if g['source_definition_id']==H.HOLD)
    send=lambda replies=():table.act(mid,cid,menu['decision_id'],menu['state_version'],state['last_sequence'],list(replies))
    before=combat._load_session(mid).engine.state.model_dump(mode='json')
    paused=send();assert paused['status']=='REACTION_REQUIRED'
    assert CombatService(ROOT,tmp_path)._load_session(mid).engine.state.model_dump(mode='json')==before
    assert send([answer(paused['reaction'],use=stop)])['status']=='COMMITTED'
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    actor=loaded.engine.state.actors[H.LEFT]
    assert actor.position.x==(3 if stop else 5)
    assert actor.movement_remaining_ft==(20 if stop else 15)
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'


def test_forced_path_ignores_fear_speed_terrain_and_willing_hooks(monkeypatch):
    e=S.fight(S.bundle(OVERRUN),foe_at=(6,6));actor=e.state.actors[S.ME]
    for name in ['pinned','frightened']:
        e._apply_condition(actor,'condition:typed.'+name,'test:condition',S.FOE,expires_on='UNTIL_REMOVED')
    e.grid.base_movement_cost[(4,6)]=2
    install(monkeypatch,'movement_step',lambda *a:pytest.fail('a forced path ran a willing reaction'))
    seen=[]
    def forced(engine,mover,previous,nxt,intent):
        context=movement_steps.context(engine,mover)
        assert context['forced'] is True and context['source_id']=='test:push'
        seen.append(context['travelled_ft'])
    install(monkeypatch,'forced_movement_step',forced)
    before=actor.movement_remaining_ft
    assert e.move_path(actor,route(actor,4,5),'test:push',kind='forced',source_actor_id=S.FOE,intent=request(e))==10
    assert actor.position==Position(x=5,y=6) and actor.movement_remaining_ft==before
    assert seen==[5,10] and not movement_steps.context(e,actor)


@pytest.mark.parametrize('stop', ['collision','checkpoint'])
def test_forced_path_stops_safely_at_live_blocker_or_checkpoint(monkeypatch,stop):
    e=S.fight(S.bundle(OVERRUN),foe_at=(5,6));actor=e.state.actors[S.ME]
    if stop=='checkpoint':
        install(monkeypatch,'forced_movement_step',lambda *a:{'stop':True,'source_id':'test:stop','label':'The forced movement stops here.'})
    assert e.move_path(actor,route(actor,4,5,6),'test:push',kind='forced',source_actor_id=S.FOE,intent=request(e))==5
    assert actor.position==Position(x=4,y=6)
    receipt=next(ev for ev in reversed(e.events) if ev.event_type=='MOVEMENT_COMMITTED')
    assert receipt.payload['forced'] and receipt.payload['cost_ft']==0
    assert len(receipt.payload['path'])==2


@pytest.mark.parametrize('kind',['willing','forced'])
def test_path_failure_inside_event_hook_rolls_back_all_changes(monkeypatch,tmp_path,kind):
    from combat.gate5_service import CombatServiceError
    combat,table,mid=H.table_fight(tmp_path,[OVERRUN],ally_talents=[])
    def move(engine,event_type,kwargs):
        if event_type!='HOLD_POSITION_COMMITTED':
            return
        actor=engine.state.actors[H.LEFT]
        engine._spend_resource(actor,'resource:core.qi',1,OVERRUN)
        engine.move_path(actor,route(actor,2),OVERRUN,kind=kind,source_actor_id=H.RIGHT)
    def broken(engine,mover,*args):
        engine._apply_condition(mover,'condition:typed.pinned','test:broken',H.RIGHT,expires_on='UNTIL_REMOVED')
        return {'stop':'invalid','source_id':'test:broken','label':'Stop'}
    install(monkeypatch,'event',move)
    install(monkeypatch,'forced_movement_step' if kind=='forced' else 'movement_step',broken)
    before=combat._load_session(mid).engine.state.model_dump(mode='json')
    with pytest.raises(CombatServiceError):
        act(table,mid,H.HOLD)
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    assert loaded.engine.state.model_dump(mode='json')==before
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'


def test_forced_path_commit_reload_and_replay(monkeypatch,tmp_path):
    combat,table,mid=H.table_fight(tmp_path,[],ally_talents=[])
    def move(engine):
        actor=engine.state.actors[H.LEFT]
        engine._apply_condition(actor,'condition:typed.pinned','test:pin',H.RIGHT,expires_on='UNTIL_REMOVED')
        assert engine.move_path(actor,route(actor,2,1),'test:push',kind='forced',source_actor_id=H.RIGHT)==10
    H.on_hold(monkeypatch,move)
    before=combat._load_session(mid).engine.state.actors[H.LEFT].movement_remaining_ft
    assert act(table,mid,H.HOLD)['status']=='COMMITTED'
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    actor=loaded.engine.state.actors[H.LEFT]
    assert actor.position==Position(x=1,y=4) and actor.movement_remaining_ft==before
    receipt=next(ev for ev in reversed(loaded.engine.events) if ev.event_type=='MOVEMENT_COMMITTED')
    assert receipt.payload['forced'] and receipt.payload['cost_ft']==0
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'


def test_forced_path_uses_owned_counterpressure_once():
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet
    feature='TAL_FORCE_COUNTERPRESSURE'
    owned=compile_character(sheet([feature],cl=1),actor_id=S.ME,reaction_plan={'options':{feature:1}})
    e=S.fight(owned,foe_at=(9,6));actor=e.state.actors[S.ME]
    before=actor.resources['resource:core.qi']
    assert e.move_path(actor,route(actor,4,5,6),'test:push',kind='forced',source_actor_id=S.FOE,intent=request(e))==5
    assert actor.position==Position(x=4,y=6) and not actor.reaction_available
    assert actor.resources['resource:core.qi']==before-1
    assert len([ev for ev in e.events if ev.event_type=='REACTION_RESOLVED' and ev.source_definition_id==feature])==1


@pytest.mark.parametrize('lethal',[False,True])
def test_forced_zone_interrupts_before_later_step_response(monkeypatch,lethal):
    from tests.test_lock10_zone_paths import fight,zone
    e=fight();actor=e.state.actors[S.FOE]
    zone(e,effects=[{'type':'damage','flat':10000 if lethal else 3,'damage_types':['force'],'applies_to':'target'}])
    seen=[]
    install(monkeypatch,'forced_movement_step',lambda e,a,p,n,i:seen.append(n.x))
    # The reviewed stop-on-damage rule is for dragging. A surviving pushed
    # creature completes its distance; lethal entry still stops before callbacks.
    assert e.move_path(actor,route(actor,4,5,6),'test:push',kind='forced',source_actor_id=S.ME,intent=request(e))==(10 if lethal else 15)
    assert actor.position==Position(x=5 if lethal else 6,y=6)
    assert seen==([4] if lethal else [4,5,6])
    assert actor.active is (not lethal)


@pytest.mark.parametrize('use',[False,True])
def test_forced_path_consent_names_actual_source_and_retains_owner_binding(monkeypatch,tmp_path,use):
    from combat.tabletop import ButtonStore
    feature='TAL_FORCE_COUNTERPRESSURE'
    ButtonStore(tmp_path/'tabletop_buttons').save_reactions(H.PROJECTS['left'],
        {'mode':'ask','options':{feature:1}},{feature,'opportunity_attack'},{feature:2})
    combat,table,mid=H.table_fight(tmp_path,[feature],ally_talents=[])
    def move(engine):
        actor=engine.state.actors[H.LEFT]
        assert engine._active_intent.actor_id==H.LEFT
        assert engine.move_path(actor,route(actor,2,1),'test:push',kind='forced',source_actor_id=H.RIGHT)==(0 if use else 10)
    H.on_hold(monkeypatch,move)
    state=table.state(mid);menu=state['menu']
    cid=next(g['options'][0]['candidate_id'] for g in menu['actions'] if g['source_definition_id']==H.HOLD)
    send=lambda replies=():table.act(mid,cid,menu['decision_id'],menu['state_version'],state['last_sequence'],list(replies))
    before=combat._load_session(mid).engine.state.model_dump(mode='json')
    paused=send();assert paused['status']=='REACTION_REQUIRED'
    assert paused['reaction']['by']=='Right' and paused['reaction']['reactor']=='Left'
    assert 'Hold' not in paused['reaction']['action']
    assert CombatService(ROOT,tmp_path)._load_session(mid).engine.state.model_dump(mode='json')==before
    assert send([{**paused['reaction']['context'],'selection':'USE' if use else 'DECLINE'}])['status']=='COMMITTED'
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[H.LEFT].position.x==(3 if use else 1)
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'


@pytest.mark.parametrize('temporary_hp', [0, 20])
def test_table_push_resolves_entry_damage_and_finishes_distance_after_reload(monkeypatch, tmp_path, temporary_hp):
    from combat.gate2_runtime_models import ZoneState
    combat, table, mid = H.table_fight(tmp_path, ['SAND_BASE_SCOURING_HAND'], ally_talents=[])
    start = combat._load_session(mid).engine.state.actors[H.RIGHT].position
    source = next(a.source_definition_id for a in combat._load_session(mid).engine.action_catalog.values()
                  if a.owner_id == H.LEFT and a.parameters.get('typed', {}).get('source') == 'SAND_BASE_SCOURING_HAND')
    def push(engine):
        actor = engine.state.actors[H.RIGHT]
        if temporary_hp:
            engine._grant_temp_hp(actor, temporary_hp, H.HOLD, H.LEFT)
        center = Position(x=start.x + 1, y=start.y)
        engine.state.zones['zone:test.push-entry'] = ZoneState(
            zone_id='zone:test.push-entry', source_definition_id=source, owner_id=H.LEFT,
            center=center, radius_cells=0, affected_cells=(center,), concentration_link=False,
            created_round=engine.state.round_number,
            trigger_profile={'kind':'TYPED', 'shape':'radius', 'numbers':{},
                'triggers':[{'id':'test:push-entry', 'name':'Damaging ground', 'on':['enter'],
                    'who':'hostile', 'effects':[{'type':'damage', 'flat':3,
                        'damage_types':['force'], 'applies_to':'target'}]}]})
        engine._append_event('ZONE_CREATED', source, actor_id=H.LEFT,
            payload={'zone': engine.state.zones['zone:test.push-entry'].model_dump(mode='json')})
        assert engine.move_path(actor, route(actor, start.x+1, start.x+2, start.x+3), H.HOLD,
                                kind='forced', source_actor_id=H.LEFT) == 15
    H.on_hold(monkeypatch, push)
    assert act(table, mid, H.HOLD)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[H.RIGHT].position == Position(x=start.x+3, y=start.y)
    damage = [e for e in loaded.engine.events if e.event_type == 'DAMAGE_COMMITTED'
              and e.source_definition_id == source and H.RIGHT in e.target_ids]
    assert len(damage) == 1 and damage[0].payload['reduced_to'] == 3
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
