"""Passage contact, terrain exemptions and interrupted-zone cleanup persist."""
import json
import zipfile
import pytest
from combat import ext
from combat.gate2_runtime_models import Position
from combat.gate2_runtime_content import ACTIONS, BAI
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.history_feed import format_history_feed
from tests.h1_support import ROOT, sheet
from tests.test_hidden_targeting import turn
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import cast_sender, commit
from tests.test_lock8_passage import CLOUD, LIQUID

OWNER, FOE='actor:factory.aaaaaaaa','actor:factory.ffffffff'


def hook(monkeypatch,point,fn):
    ext.effects();monkeypatch.setitem(ext._HOOKS,point,[*ext._HOOKS.get(point,[]),fn])


def table(tmp_path,feature,*,legacy_zone=False,extra_features=(),start=(3,6)):
    for pid,owned,name in [('aaaaaaaa',feature,'Traveler'),('ffffffff','SAND_BASE_SCOURING_HAND','Sentinel')]:
        doc=sheet([owned,*extra_features] if pid=='aaaaaaaa' else [owned],cl=20)
        doc['identity']['display_name']=name
        doc['ability_scores_and_statistics']['hit_points']['maximum']=500
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    service=CombatService(ROOT,tmp_path)
    service.tabletop_maps.save({'display_name':'Review passage hall','width_squares':12,'height_squares':14,
        'walls':[{'shape':'rect','points':[[0,0],[12,6]]},{'shape':'rect','points':[[0,7],[12,14]]}],
        'starts':{'team1':[list(start)],'team2':[[4,6],[10,6]]}})
    opponents=[FOE,BAI] if legacy_zone else [FOE]
    mid=service.create_factory_match(project_ids=['aaaaaaaa'],opponent_actor_ids=opponents,
        control_modes={a:'MANUAL' for a in [OWNER,*opponents]},arena_id='battlefield:map.review-passage-hall',
        match_seed='L9-PASSAGE')['match_id']
    ui=TabletopService(service,tmp_path);turn(ui,mid,OWNER)
    engine=service._load_session(mid).engine
    c=next(c for c in engine.legal_candidates() if engine.action_catalog.get(c.source_definition_id)
        and engine.action_catalog[c.source_definition_id].parameters.get('typed',{}).get('source')==feature)
    assert send(service,ui,mid,c)['status']=='COMMITTED'
    return service,ui,mid


def send(service,ui,mid,c):
    state=ui.state(mid)
    return ui.act(mid,c.candidate_id,c.decision_id,c.state_version,state['last_sequence'])


def checked(tmp_path,mid):
    s=CombatService(ROOT,tmp_path)._load_session(mid)
    assert s.verify()['status']==s.mechanical.replay()['status']=='PASS'
    return s.engine


def history(engine):
    return format_history_feed([ev.model_dump(mode='json') for ev in engine.events],
        [r.model_dump(mode='json') for r in engine.rolls],pre_state=None,
        post_state=engine.state.model_dump(mode='json'),
        actor_names={k:v.display_name for k,v in engine.state.actors.items()},
        definition_names={k:v.display_name for k,v in engine.action_catalog.items()})


@pytest.mark.parametrize('feature',[CLOUD,LIQUID])
@pytest.mark.parametrize('budget',[10,30])
def test_unseen_occupant_stops_on_contact_without_extra_charge(monkeypatch,tmp_path,feature,budget):
    service,ui,mid=table(tmp_path,feature)
    def hide(engine,event,kwargs):
        if event=='HOLD_POSITION_COMMITTED' and kwargs.get('actor_id')==OWNER:
            a=engine.state.actors[OWNER];before=a.movement_remaining_ft
            a.movement_remaining_ft=budget
            engine._append_event('MOVEMENT_GRANTED','test:budget',actor_id=OWNER,payload={'distance_ft':budget-before})
            engine._apply_condition(engine.state.actors[FOE],'condition:typed.invisible','test:hide',FOE,expires_on='UNTIL_REMOVED')
    hook(monkeypatch,'event',hide)
    assert act(ui,mid,'system:combat.hold_position')['status']=='COMMITTED'
    engine=service._load_session(mid).engine
    c=next(c for c in engine.legal_candidates() if c.kind.value=='MOVE' and c.destination==Position(x=5,y=6))
    assert c.movement_cost_ft==10
    assert FOE not in c.metadata.get('creature_passage',{})
    assert send(service,ui,mid,c)['status']=='COMMITTED'
    engine=checked(tmp_path,mid);a=engine.state.actors[OWNER]
    assert a.position==Position(x=3,y=6) and a.movement_remaining_ft==budget
    assert a.turn_flags['unseen_contact_cells']==[{'x':4,'y':6}]
    moves=[ev for ev in engine.events if ev.event_type=='MOVEMENT_COMMITTED' and ev.actor_id==OWNER]
    assert moves[-1].payload['interrupted'] and moves[-1].payload['cost_ft']==0
    assert not any(c.kind.value=='MOVE' and c.destination==Position(x=5,y=6) for c in engine.legal_candidates())


@pytest.mark.parametrize('feature',[CLOUD,LIQUID])
def test_recovery_leaves_blackwater_and_records_readable_history(monkeypatch,tmp_path,feature):
    # Legacy Blackwater's resource callbacks expect the legacy roster member.
    service,ui,mid=table(tmp_path,feature,legacy_zone=True)
    # Use native Blackwater entry and its real leave-zone condition.
    source=next(a for a in ACTIONS.values() if 'blackwater' in a.source_definition_id.lower() and a.damage is not None)
    def zone(engine,event,kwargs):
        if event=='HOLD_POSITION_COMMITTED' and kwargs.get('actor_id')==OWNER:
            engine._resolve_zone_action(engine.state.actors[FOE],source.model_copy(update={'radius_ft':0}),
                Position(x=4,y=6),engine._active_intent,zone_kind='BLACKWATER')
    def stop(engine,mover,occupant,intent):
        if mover.entity_id==OWNER:
            engine._apply_condition(mover,'condition:typed.pinned','test:pin',FOE,expires_on='UNTIL_REMOVED')
    hook(monkeypatch,'event',zone);hook(monkeypatch,'pass_through_entered',stop)
    hook(monkeypatch,'d20_result',lambda *args:{'source_id':'test:roll','operation':'replace','natural_result':1})
    assert act(ui,mid,'system:combat.hold_position')['status']=='COMMITTED'
    engine=service._load_session(mid).engine
    c=next(c for c in engine.legal_candidates() if c.kind.value=='MOVE' and c.destination==Position(x=5,y=6))
    assert send(service,ui,mid,c)['status']=='COMMITTED'
    engine=checked(tmp_path,mid);a=engine.state.actors[OWNER]
    assert a.position==Position(x=3,y=6)
    assert any(ev.event_type=='CONDITION_APPLIED' and ev.payload.get('condition_id')=='condition:core.reaction_denied' for ev in engine.events)
    assert not any(c.expires_on in {'LEAVE_ZONE_OR_START_OF_NEXT_TURN','LEAVE_ZONE_OR_CONCENTRATION_END'} for c in a.conditions.values())
    assert any(ev.event_type=='CONDITION_REMOVED' and ev.payload.get('reason')=='LEFT_ZONE' for ev in engine.events)
    lines=[row['summary'] for row in history(engine)]
    recoveries=[line for line in lines if 'returns to the last free space' in line]
    assert recoveries and all('Not automated' not in line and 'skipped' not in line for line in recoveries)
    for token in ['rider lane','riders/c6','provenance-qualified','isolated branch','terrain metadata']:
        assert not any(token in line for line in lines)
