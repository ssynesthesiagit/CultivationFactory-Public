"""Final routed cover and defender movement through committed table actions."""
import json
import zipfile
from fractions import Fraction
import pytest
from combat import ext, shot_geometry, typed_reactions, typed_executor
from combat.gate2_runtime_models import Position, ActionDefinition, EconomyKind
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import ButtonStore
from tests.h1_support import ROOT, sheet
from tests.test_hidden_targeting import turn
from tests.test_lock2_persistence import act
from tests.test_lock8_sight import BOUNCE, WORLD, KIT
from tests.r10_fixup_support import commit

OWNER,FOE='actor:factory.aaaaaaaa','actor:factory.ffffffff'
SHIELD='TAL_SHIELD_FLEXIBLE_COVER'


def hook(monkeypatch,point,fn):
    ext.effects();monkeypatch.setitem(ext._HOOKS,point,[*ext._HOOKS.get(point,[]),fn])


def table(monkeypatch,tmp_path,*,world=False,face=False,foe_features=(),natural=10):
    for pid,features in [('aaaaaaaa',[BOUNCE,*([WORLD] if world else [])]),('ffffffff',[SHIELD,*foe_features])]:
        doc=sheet(features,cl=20,kit=KIT if pid=='aaaaaaaa' else None)
        doc['identity']['display_name']='Archer' if pid=='aaaaaaaa' else 'Shield bearer'
        doc['ability_scores_and_statistics']['hit_points']['maximum']=500
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
        ButtonStore(tmp_path/'tabletop_buttons').save_reactions(pid,{'mode':'ask'},set(features))
    def ready(e,kind,kw):
        if kind=='HOLD_POSITION_COMMITTED' and kw.get('actor_id')==OWNER:
            e._gain_resource(e.state.actors[OWNER],'resource:core.martial_focus',1,'test:ready')
            if face:
                e._apply_condition(e.state.actors[FOE],'condition:typed.shield_face',SHIELD,FOE,
                    expires_on='UNTIL_REMOVED',data={'kind':'flexible','edge':'N','width_ft':0})
    hook(monkeypatch,'event',ready)
    hook(monkeypatch,'d20_result',lambda *a:{'source_id':'test:roll','operation':'replace','natural_result':natural})
    service=CombatService(ROOT,tmp_path)
    service.tabletop_maps.save({'display_name':'Review ricochet yard','width_squares':20,'height_squares':14,
        # A separate reachable reflector permits a legal single turn around
        # the divider; reflecting off the divider cannot open its interior.
        'walls':[{'shape':'rect','points':[[5,4],[6,9]]},
                 {'shape':'rect','points':[[5,0],[6,1]]}],
        'starts':{'team1':[[3,6]],'team2':[[7,6]]}})
    mid=service.create_factory_match(project_ids=['aaaaaaaa'],opponent_actor_ids=[FOE],
        control_modes={OWNER:'MANUAL',FOE:'MANUAL'},arena_id='battlefield:map.review-ricochet-yard',match_seed='L9-SIGHT')['match_id']
    ui=TabletopService(service,tmp_path);turn(ui,mid,OWNER)
    assert act(ui,mid,'system:combat.hold_position')['status']=='COMMITTED'
    c=next(c for c in service._load_session(mid).engine.legal_candidates() if 'Bouncing Shot' in c.display_name)
    after=ui.state(mid)['last_sequence']
    def send(answers=()):
        return TabletopService(CombatService(ROOT,tmp_path),tmp_path).act(mid,c.candidate_id,c.decision_id,c.state_version,after,list(answers))
    return service,mid,c,send


def checked(tmp_path,mid):
    s=CombatService(ROOT,tmp_path)._load_session(mid)
    assert s.verify()['status']==s.mechanical.replay()['status']=='PASS'
    return s.engine


@pytest.mark.parametrize('world',[False,True])
@pytest.mark.parametrize('declaration',[0,2,5])
def test_final_attack_roll_combines_shield_and_declaration_before_world(monkeypatch,tmp_path,world,declaration):
    if declaration:
        hook(monkeypatch,'retarget_attack',lambda e,a,t,*args:{'source_id':'test:interpose','target_id':t.entity_id,'cover_bonus':declaration})
    service,mid,c,send=table(monkeypatch,tmp_path,world=world,face=True)
    e=service._load_session(mid).engine;a=e.state.actors[OWNER];target=e.state.actors[FOE]
    bound=c.metadata['shot_geometry'];action=e.action_catalog[c.source_definition_id]
    with shot_geometry.scope(e,a,action,bound):
        from combat.ext.shield_faces import rays, face_cover
        actual=rays(e,a,target)
        # This fixture reflects at the south face of wall (5,0), not the
        # centre of the adjacent waypoint (5,1). Cover follows that exact leg.
        assert actual and actual[0]['start']==[5, Fraction(1,2)]
        assert face_cover(e,a,target,actual[0])==5
        cover,ac=e._attack_defense(a,target,{'range_ft':60,'declaration_cover':declaration})
        assert cover==(0 if world else 5)
    commit(send)
    e=checked(tmp_path,mid)
    roll=next(ev for ev in e.events if ev.event_type=='ATTACK_ROLLED' and ev.actor_id==OWNER)
    assert roll.payload['cover_bonus']==cover and roll.payload['target_ac']==ac
    assert roll.payload['provisional_hit']==(roll.payload['modified_total']>=ac)


@pytest.mark.parametrize('point',['declaration','before_attack'])
@pytest.mark.parametrize('take',[False,True])
def test_defender_step_invalidates_bound_route_through_pause_and_reload(monkeypatch,tmp_path,point,take):
    if point=='declaration':
        row={'feature_id':'test:step','name':'Defender step','block':'generic','kind':'attacked',
            'ask':True,'effects':[{'type':'reaction_move','direction':'toward','distance_ft':5}]}
        original=typed_reactions._rows
        monkeypatch.setattr(typed_reactions,'_rows',lambda e,aid,block:
            ([row] if aid==FOE and block=='generic' else [])+original(e,aid,block))
        ext.effects();monkeypatch.setitem(ext._HOOKS,'before_attack',[])
    else:
        def step(e,a,t,intent,context):
            from combat.ext import needle
            picked=needle.ask(e,intent,'REVIEW_ROUTE_STEP',t,'choice:needle.route_step',['step'],
                labels={'step':'Step aside'},allow_decline=True,name='Defender step',automatic=False)
            if picked:
                old=t.position;t.position=Position(x=7,y=7)
                e._append_event('MOVEMENT_COMMITTED','test:step',actor_id=t.entity_id,
                    payload={'destination':t.position.model_dump(mode='json'),'path':[old.model_dump(mode='json'),t.position.model_dump(mode='json')],'cost_ft':0})
            return None
        hook(monkeypatch,'before_attack',step)
    service,mid,c,send=table(monkeypatch,tmp_path)
    before=service._load_session(mid).engine.state.model_dump(mode='json')
    paused=send();assert paused['status']=='REACTION_REQUIRED'
    assert service._load_session(mid).engine.state.model_dump(mode='json')==before
    answers=[];steps=0
    for _ in range(10):
        if paused['status']=='COMMITTED':break
        assert paused['status']=='REACTION_REQUIRED'
        prompt=paused['reaction'];source=prompt['context']['reaction_source_id']
        requested='test:step' in source if point=='declaration' else 'route_step' in source
        steps+=int(requested)
        answers.append({**prompt['context'],'selection':'USE' if requested and take else 'DECLINE',
            'option_ids':['step'] if requested and take and point=='before_attack' else []})
        paused=send(answers)
    assert paused['status']=='COMMITTED' and steps==1
    e=checked(tmp_path,mid)
    rolls=[ev for ev in e.events if ev.event_type=='ATTACK_ROLLED' and ev.actor_id==OWNER]
    if take:
        assert e.state.actors[FOE].position.model_dump(mode='json')!=before['actors'][FOE]['position']
        assert e.state.actors[FOE].current_hp==before['actors'][FOE]['current_hp'] and not rolls
        assert any('chosen projectile path' in ev.payload.get('log','') for ev in e.events)
        with shot_geometry.scope(e,e.state.actors[OWNER],e.action_catalog[c.source_definition_id],c.metadata['shot_geometry']):
            assert not shot_geometry.source_cells(e,e.state.actors[OWNER],e.state.actors[FOE])
    else:assert rolls
    assert e.state.actors[OWNER].resources['resource:core.martial_focus']==0


@pytest.mark.parametrize('entry',['effects','attack'])
def test_different_source_nested_attack_does_not_inherit_route(monkeypatch,tmp_path,entry):
    observed=[]
    def follow(ctx,target,kind):
        if ctx.source=='test:followup' or ctx.actor.entity_id!=OWNER:return
        action=ActionDefinition(source_definition_id='test:followup',display_name='Follow-up bolt',owner_id=OWNER,
            economy=EconomyKind.NONE,resolution_kind='TYPED',target_kind='HOSTILE_ENTITY',range_ft=120)
        inner=typed_executor.Context(ctx.engine,ctx.actor,action,ctx.intent,{'numbers':{'attack_bonus':20}},[target],target,{})
        effect={'type':'attack','attack_kind':'cultivation_ranged','on_hit':[]}
        if entry=='effects':typed_executor.run_effects(inner,[effect])
        else:typed_executor.block_attack(inner,effect)
        observed.append(shot_geometry.action(ctx.engine,ctx.actor).source_definition_id==ctx.source)
    hook(monkeypatch,'after_hit',follow)
    nested_scopes=[]
    def start(ctx):
        if ctx.source=='test:followup':nested_scopes.append(shot_geometry.action(ctx.engine,ctx.actor))
    hook(monkeypatch,'attack_sequence_start',start)
    service,mid,c,send=table(monkeypatch,tmp_path)
    commit(send)
    e=checked(tmp_path,mid)
    assert observed and all(observed) and nested_scopes and all(x is None for x in nested_scopes)
    rolls=[ev for ev in e.events if ev.event_type=='ATTACK_ROLLED' and ev.source_definition_id=='test:followup']
    # SOL132: the nested source has no ricochet path of its own, so the solid
    # wall stops it. It must neither inherit the parent path nor make a d20.
    assert not rolls
    assert any(ev.source_definition_id == 'test:followup' and
               'solid obstacle' in ev.payload.get('log', '') for ev in e.events)


def test_actual_redirection_cover_is_reduced_in_final_attack_roll(monkeypatch):
    from tests import lock8_support as S
    from tests.test_lock8_sight import ranged, use
    from tests.test_lock_choices import install
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'),
        ally=S.bundle('SAND_BASE_SCOURING_HAND',actor_id=S.ALLY),ally_at=(7,6))
    action=ranged(e)
    install(monkeypatch,'retarget_attack',lambda *args:{'source_id':'test:interpose','target_id':S.ALLY,'cover_bonus':5})
    install(monkeypatch,'cover_reduction',lambda *args:1)
    install(monkeypatch,'d20_result',lambda *args:{'source_id':'test:roll','operation':'replace','natural_result':10})
    c=next(c for c in e.legal_candidates() if c.source_definition_id==action.source_definition_id)
    use(e,c)
    roll=next(ev for ev in e.events if ev.event_type=='ATTACK_ROLLED' and ev.actor_id==S.ME)
    assert roll.target_ids==(S.ALLY,) and roll.payload['cover_bonus']==2
    assert roll.payload['target_ac']==e.state.actors[S.ALLY].armor_class+2


def test_bound_route_never_uses_physical_origin_for_another_recipient():
    from tests import lock8_support as S
    from tests.test_lock8_sight import ranged
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'),
        ally=S.bundle('SAND_BASE_SCOURING_HAND',actor_id=S.ALLY))
    action=ranged(e);a=e.state.actors[S.ME];t=e.state.actors[S.FOE]
    bound={'target_id':S.FOE,'route':{'source_id':'test:path','label':'Bound path',
        'path':[a.position.model_dump(mode='json'),t.position.model_dump(mode='json')]}}
    with shot_geometry.scope(e,a,action,bound):
        assert not shot_geometry.valid_for_attack(e,a,e.state.actors[S.ALLY])
        assert not shot_geometry.source_cells(e,a,e.state.actors[S.ALLY])
