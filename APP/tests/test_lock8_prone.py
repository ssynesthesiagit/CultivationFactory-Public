"""Standing vetoes, one posture event, and canonical Seal/Command clauses."""
import json
import zipfile
import pytest
from combat import ext, posture, typed_executor
from combat.ext.prone_restraints import FALLING_GATE, COMMAND, RESTRAINT
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests import lock8_support as S
from tests.h1_support import ROOT, sheet
from tests.test_hidden_targeting import turn
from tests.test_lock_choices import install
from tests.test_lock2_persistence import act


def knock(engine, actor, source='test:prone'):
    engine._apply_condition(actor, 'condition:typed.prone', source, actor.entity_id, expires_on='STAND_UP')


def prone_table(tmp_path, *, ally=False):
    left, right = 'actor:factory.left', 'actor:factory.right'
    roster = [('left', [COMMAND]), ('right', ['SAND_BASE_SCOURING_HAND'])]
    if ally:
        roster.append(('ally', ['SAND_BASE_SCOURING_HAND']))
    for pid, features in roster:
        folder = tmp_path / 'portable_characters' / pid; folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(sheet(features, cl=20, dc=16)))
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({'display_name': 'Posture yard', 'width_squares': 12, 'height_squares': 8,
        'walls': [], 'starts': {'team1': [[3,4], [3,5]], 'team2': [[4,4]]}})
    mid = service.create_factory_match(project_ids=['left', 'ally'] if ally else ['left'],
        opponent_actor_ids=[right], control_modes={left: 'MANUAL', right: 'MANUAL', 'actor:factory.ally': 'MANUAL'},
        arena_id='battlefield:map.posture-yard', match_seed='POSTURE')['match_id']
    return service, TabletopService(service, tmp_path), mid, left, right


def record_setup(ui, mid, targets):
    first = act(ui, mid, 'system:combat.fight_setup')
    assert first['status'] == 'REACTION_REQUIRED'
    state = ui.state(mid); menu = state['menu']
    group = next(g for g in menu['actions'] if g['source_definition_id'] == 'system:combat.fight_setup')
    result = ui.act(mid, group['options'][0]['candidate_id'], menu['decision_id'], menu['state_version'],
        state['last_sequence'], [{**first['reaction']['context'], 'selection': 'USE' if targets else 'DECLINE', 'option_ids': targets}])
    assert result['status'] == 'COMMITTED'


def test_two_prone_instances_cost_once_and_emit_one_readable_event():
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'));a=e.state.actors[S.ME]
    knock(e,a,'test:a');knock(e,a,'test:b');a.movement_remaining_ft=30
    assert posture.stand_up(e,a,cost=15)
    assert a.movement_remaining_ft==15 and not posture.prone_conditions(a)
    assert len(S.payloads(e.events,'STOOD_UP'))==1
    assert not posture.stand_up(e,a,cost=15)
    from combat.history_feed import format_history_feed
    rows=format_history_feed([ev.model_dump(mode='json') for ev in e.events if ev.event_type=='STOOD_UP'],[],
        pre_state=None,post_state=e.state.model_dump(mode='json'),actor_names={S.ME:'Fighter'},definition_names={})
    assert 'stands up, spending 15 feet' in rows[0]['summary']


@pytest.mark.parametrize('speed,cost,ignore,allowed',[(0,0,False,False),(0,0,True,True),(30,5,False,True)])
def test_explicit_stand_and_cost_provider(monkeypatch,speed,cost,ignore,allowed):
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'));a=e.state.actors[S.ME]
    a.speed_ft=speed;a.movement_remaining_ft=speed;knock(e,a)
    install(monkeypatch,'stand_cost',lambda *args:cost)
    assert posture.stand_up(e,a,ignore_speed=ignore)==allowed
    assert a.movement_remaining_ft==speed-(cost if allowed else 0)


@pytest.mark.parametrize('hook,answer',[('stand_allowed',1),('stand_cost',True),('stand_cost',-1)])
def test_invalid_stand_provider_is_rejected_before_changes(monkeypatch,hook,answer):
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'));a=e.state.actors[S.ME];knock(e,a)
    before=a.model_dump(mode='json');install(monkeypatch,hook,lambda *args:answer)
    with pytest.raises(ValueError):posture.stand_up(e,a)
    assert a.model_dump(mode='json')==before


def test_explicit_free_stand_cannot_ignore_restraint():
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'));a=e.state.actors[S.ME];knock(e,a)
    e._apply_condition(a,RESTRAINT,'test:held',S.FOE,expires_on='UNTIL_REMOVED',data={'cannot_stand':True})
    before=a.model_dump(mode='json')
    assert not posture.stand_up(e,a,cost=0,ignore_speed=True)
    assert a.model_dump(mode='json')==before


@pytest.mark.parametrize('failed',[False,True])
def test_falling_gate_real_touch_the_point_save_and_source_turn_expiry(monkeypatch,failed):
    kit={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.bi_shou','quantity':1}]}}
    e=S.fight(S.bundle(FALLING_GATE,kit=kit),foe_at=(4,6));a,b=e.state.actors[S.ME],e.state.actors[S.FOE]
    # Real dagger attack, with an already-recorded Point from the previous exchange.
    mark=typed_executor.mark_condition_id('Pressure Point',S.ME)
    e._apply_condition(b,mark,'test:point',S.ME,expires_on='UNTIL_REMOVED')
    install(monkeypatch,'d20_result',lambda engine,roll,context:
        {'source_id':'test:roll','operation':'replace','natural_result':1 if failed and engine.d20_context().get('kind')=='save' else 20})
    e._gain_resource(a,'resource:core.martial_focus',1,'test:focus')
    candidates=[c for c in e.legal_candidates() if '.weapon.bi_shou' in c.source_definition_id
                and '#thrown' not in c.source_definition_id and S.FOE in c.target_ids]
    assert candidates
    c=candidates[0]
    from combat.gate2_runtime_models import ActionIntent
    e.execute_intent(ActionIntent(intent_id='seal',decision_id=c.decision_id,candidate_id=c.candidate_id,
        state_version=c.state_version,actor_id=S.ME,target_ids=c.target_ids))
    assert posture.prone_conditions(b)
    assert any(c.condition_id==RESTRAINT for c in b.conditions.values())==failed
    b.movement_remaining_ft=30
    if failed:
        assert not posture.stand_up(e,b)
        e._expire_for_checkpoint('START_OF_TURN',S.FOE)
        assert posture.prone_conditions(b)  # holder's own start cannot release a source-bound seal
        e._expire_for_checkpoint('START_OF_TURN',S.ME)
        assert posture.stand_up(e,b)
    else:assert posture.stand_up(e,b)


@pytest.mark.parametrize('failed',[False,True])
def test_imperial_kneel_table_cost_holder_expiry_stood_event_and_replay(tmp_path,monkeypatch,failed):
    install(monkeypatch,'d20_result',lambda engine,roll,context:
        {'source_id':'test:roll','operation':'replace','natural_result':1 if failed and engine.d20_context().get('kind')=='save' else 20})
    service,ui,mid,left,right=prone_table(tmp_path)
    record_setup(ui,mid,[right]);turn(ui,mid,left)
    before=service._load_session(mid).engine.state.actors[left].resources['resource:core.qi']
    e=service._load_session(mid).engine
    c=next(c for c in e.legal_candidates() if c.display_name=='Imperial Command: Kneel' and c.target_ids==(right,))
    result=ui.act(mid,c.candidate_id,c.decision_id,c.state_version,ui.state(mid)['last_sequence'])
    assert result['status']=='COMMITTED'
    loaded=CombatService(ROOT,tmp_path)._load_session(mid);a,b=loaded.engine.state.actors[left],loaded.engine.state.actors[right]
    assert a.resources['resource:core.qi']==before-4
    assert bool(posture.prone_conditions(b))==failed
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'
    turn(ui,mid,right)
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    assert bool(posture.prone_conditions(loaded.engine.state.actors[right]))==failed
    if failed:
        assert not any(ev.event_type=='STOOD_UP' and ev.actor_id==right for ev in loaded.engine.events)
        act(ui,mid,'end');turn(ui,mid,right)
        loaded=CombatService(ROOT,tmp_path)._load_session(mid)
        assert not posture.prone_conditions(loaded.engine.state.actors[right])
        assert len([ev for ev in loaded.engine.events if ev.event_type=='STOOD_UP' and ev.actor_id==right])==1
        assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'
    else:
        assert not any(c.condition_id=='condition:typed.reaction_denied' for c in loaded.engine.state.actors[right].conditions.values())
