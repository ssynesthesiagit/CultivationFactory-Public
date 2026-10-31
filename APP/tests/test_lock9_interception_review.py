"""Complete reaction activations and all supported movement honor interception."""
import json
import zipfile
import pytest
from combat import ext, typed_executor
from combat.gate5_service import CombatService, AI_RESPONSE_SCHEMA
from combat.tabletop_service import TabletopService
from combat.tabletop import ButtonStore
from combat.technique_interception import named_ability
from tests.h1_support import ROOT, sheet
from tests.test_hidden_targeting import turn
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import cast_sender, commit
from tests import lock8_support as S
from tests.test_lock8_interception import use

ICE = 'TAL_ICE_HEAVEN_SEALING_ICE_SCRIPT'
SPIKE = 'tianxia.path.spirit_awakening.feature.mind_spike'
DAWN = 'RADIANCE_TAL_DAWNLIT_REBUKE'
BLOODY = 'TAL_BERSERKER_BLOODY_COUNTER'
DAO = {'starting_kit': {'items': [{'item_id':'tianxia.mortal.weapon.dao'}]}}
PLAYER, ATTACKER, REACTOR, PROTECTED = ['actor:factory.'+p for p in ('aaaaaaaa','bbbbbbbb','ffffffff','eeeeeeee')]


def hook(monkeypatch, point, fn):
    ext.effects(); monkeypatch.setitem(ext._HOOKS, point, [*ext._HOOKS.get(point, []), fn])


def fixed(monkeypatch):
    hook(monkeypatch, 'd20_result', lambda *args: {'source_id':'test:roll','operation':'replace','natural_result':10})


def checked(tmp_path, mid):
    s = CombatService(ROOT, tmp_path)._load_session(mid)
    assert s.verify()['status'] == s.mechanical.replay()['status'] == 'PASS'
    return s.engine


def choose_ice(prompt):
    if prompt['context']['reaction_source_id'] == 'choice:needle.fracture_response':
        return None, False  # Decline the unrelated optional Fracture rider.
    ids = {x['id'] for x in prompt.get('choice',{}).get('options',[])}
    return ('damage' if 'damage' in ids else 'resource:core.qi' if 'resource:core.qi' in ids else None, True)


class Provider:
    def __init__(self, attack, target):
        self.calls, self.attack, self.target = 0, attack, target
    def status(self):
        return {'ready':True}
    def complete_json(self, *, prompt_text, **kwargs):
        self.calls += 1
        frame = json.loads(prompt_text.split('\n\n',1)[1])
        c = next(c for c in frame['legal_candidates'] if self.attack in c['display_name'] and self.target in c['target_ids'])
        payload = {k:c[k] for k in ('candidate_id','actor_id','target_ids','destination','option_ids')}
        payload.update(decision_id=frame['decision_id'], state_version=frame['state_version'])
        return {'value':{'schema':AI_RESPONSE_SCHEMA,'action_intent':payload,'rationale':'Use the selected test attack.'},
                'provider_id':'test:offline','model':'fake','request_sha256':'fixture'}


def build(tmp_path, people, *, team1, team2, starts, provider=None):
    for aid, features, name, mode, kit in people:
        doc = sheet(features, cl=15, dc=50, kit=kit)
        doc['identity']['display_name'] = name
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 500
        pid = aid.split('.')[-1]
        folder = tmp_path/'portable_characters'/pid; folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
        ButtonStore(tmp_path/'tabletop_buttons').save_reactions(pid, {'mode':mode}, set(features))
    s = CombatService(ROOT,tmp_path,ai_provider=provider)
    s.tabletop_maps.save({'display_name':'Review ice yard','width_squares':20,'height_squares':14,
        'walls':[], 'starts':starts})
    mid=s.create_factory_match(project_ids=[a.split('.')[-1] for a in team1], opponent_actor_ids=team2,
        control_modes={a:'MANUAL' for a,*_ in people},arena_id='battlefield:map.review-ice-yard',match_seed='L9-ICE')['match_id']
    return s,TabletopService(s,tmp_path),mid


def mark_event(monkeypatch, actor, marks):
    def mark(engine,event,kwargs):
        if event=='HOLD_POSITION_COMMITTED' and kwargs.get('actor_id')==actor:
            for recipient, source, name in marks:
                engine._apply_condition(engine.state.actors[recipient], typed_executor.mark_condition_id(name,source),
                    'test:prior_mark',source,expires_on='UNTIL_REMOVED',data={'mark':name})
    hook(monkeypatch,'event',mark)


@pytest.mark.parametrize('feature,kind', [(DAWN,'nonattack'),(BLOODY,'attack')])
def test_real_reaction_intercepted_once_during_api_turn_and_reloaded(monkeypatch,tmp_path,feature,kind):
    fixed(monkeypatch)
    target = PROTECTED if kind=='nonattack' else REACTOR
    provider=Provider('Scouring Hand' if kind=='nonattack' else 'Dao', target)
    people=[(PLAYER,[ICE],'Frost Warden','ask',None),
            (ATTACKER,['SAND_BASE_SCOURING_HAND'],'Ally','auto',DAO),
            (REACTOR,[feature],'Countering adept','ask',DAO),
            (PROTECTED,['SAND_BASE_SCOURING_HAND'],'Protected ally','auto',None)]
    mark_event(monkeypatch,ATTACKER,[(REACTOR,PLAYER,'Fracture Mark'),(ATTACKER,REACTOR,'Dawnmark')])
    s,ui,mid=build(tmp_path,people,team1=[PLAYER,ATTACKER],team2=[REACTOR,PROTECTED],
        starts={'team1':[[3,6],[7,6]],'team2':[[8,6],[9,6]]},provider=provider)
    turn(ui,mid,ATTACKER); assert act(ui,mid,'system:combat.hold_position')['status']=='COMMITTED'
    s.set_controller_mode(mid,actor_id=ATTACKER,controller_mode='API_AUTO')
    before=s._load_session(mid).engine.state.model_dump(mode='json')
    first=ui.auto_step(mid,0)
    assert first['status']=='REACTION_REQUIRED' and provider.calls==1
    assert s._load_session(mid).engine.state.model_dump(mode='json')==before
    # The accepted AI intent and all pending player choices survive service reload.
    s=CombatService(ROOT,tmp_path);ui=TabletopService(s,tmp_path)
    answers=[]; prompts=[]
    for _ in range(15):
        result=ui.auto_step(mid,0,reactions=answers)
        if result['status']=='COMMITTED':break
        assert result['status']=='REACTION_REQUIRED',result
        p=result['reaction'];prompts.append(p)
        option,use=choose_ice(p)
        answers.append({**p['context'],'selection':'USE' if use else 'DECLINE',
                        'option_ids':[option] if use and option else []})
    else:raise AssertionError('too many reaction choices')
    e=checked(tmp_path,mid)
    assert provider.calls==1
    ice_prompts=[p for p in prompts if 'ice_script' in str(p)]
    assert ice_prompts and any(p['context']['reactor_id']==PLAYER for p in ice_prompts)
    rows=[ev for ev in e.events if ev.source_definition_id==feature and ev.payload.get('interceptions')]
    assert len(rows)==1
    assert e.state.actors[PLAYER].resources['resource:core.qi']==before['actors'][PLAYER]['resources']['resource:core.qi']-3
    costs=[ev for ev in e.events if ev.source_definition_id==feature and ev.event_type=='RESOURCE_SPENT']
    assert sum(ev.payload.get('amount',0) for ev in costs)==(1 if kind=='nonattack' else 0)
    assert not e.state.actors[REACTOR].reaction_available
    assert not getattr(e,'_interception_frame',None)


def test_free_mind_spike_is_named_but_ordinary_weapon_is_not(monkeypatch):
    fixed(monkeypatch)
    e=S.fight(S.bundle(SPIKE,kit=DAO),foe=S.bundle(ICE,actor_id=S.FOE,dc=50),foe_at=(12,6))
    owner=e.state.actors[S.ME];ice=e.state.actors[S.FOE]
    e._apply_condition(owner,typed_executor.mark_condition_id('Fracture Mark',S.FOE),'test:mark',S.FOE,
        expires_on='UNTIL_REMOVED',data={'mark':'Fracture Mark'})
    action=next(a for a in e.action_catalog.values() if a.owner_id==S.ME and a.display_name=='Mind Spike')
    weapon=next(a for a in e.action_catalog.values() if a.owner_id==S.ME and a.display_name.startswith('Dao'))
    assert not action.costs and not action.parameters['typed'].get('sphere')
    assert named_ability(action) and not named_ability(weapon)
    before=ice.resources['resource:core.qi']
    c=next(c for c in e.legal_candidates() if c.source_definition_id==action.source_definition_id)
    use(e,c)
    assert ice.resources['resource:core.qi']==before-3
    assert ice.current_hp==ice.maximum_hp  # the 60-foot power was shortened to 30 feet


def test_marked_ordinary_weapon_attack_does_not_trigger_ice(monkeypatch):
    fixed(monkeypatch)
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND',kit=DAO),foe=S.bundle(ICE,actor_id=S.FOE,dc=50),foe_at=(4,6))
    actor,ice=e.state.actors[S.ME],e.state.actors[S.FOE]
    e._apply_condition(actor,typed_executor.mark_condition_id('Fracture Mark',S.FOE),'test:mark',S.FOE,
        expires_on='UNTIL_REMOVED',data={'mark':'Fracture Mark'})
    before=ice.resources['resource:core.qi']
    use(e,next(c for c in e.legal_candidates() if c.display_name.startswith('Dao')))
    assert ice.resources['resource:core.qi']==before and ice.reaction_available
    assert not any(ev.payload.get('interceptions') for ev in e.events)


@pytest.mark.parametrize('feature,name,destination,expected',[
    ('tianxia.path.body_refining.feature.stomping_step','Stomping Step',None,10),
    ('TAL_ATHLETICS_ONE_BREATH_TEN_THOUSAND_STEPS','One Breath, Ten Thousand Steps',None,10),
    ('TAL_SPACE_FOLD_STEP','Fold Step',(5,6),10),
    ('TAL_SPACE_FOLD_STEP','Fold Step',(7,6),0)])
def test_grants_and_teleports_share_per_creature_movement_cap(monkeypatch,tmp_path,feature,name,destination,expected):
    fixed(monkeypatch)
    mark_event(monkeypatch,ATTACKER,[(ATTACKER,PLAYER,'Fracture Mark')])
    people=[(PLAYER,[ICE],'Frost Warden','ask',None),(ATTACKER,[feature],'Traveler','ask',None)]
    s,ui,mid=build(tmp_path,people,team1=[ATTACKER],team2=[PLAYER],
        starts={'team1':[[3,6]],'team2':[[4,6]] if 'ATHLETICS' in feature else [[10,6]]})
    turn(ui,mid,ATTACKER);assert act(ui,mid,'system:combat.hold_position')['status']=='COMMITTED'
    before=s._load_session(mid).engine.state.model_dump(mode='json')
    def answer(prompt):
        ids = {o['id'] for o in prompt.get('choice', {}).get('options', [])}
        for wanted in ('movement', 'resource:core.qi', 'dash'):
            if wanted in ids:
                return wanted, True
        if prompt['context']['reaction_source_id'] == 'choice:needle.teleport_destination':
            # Answer the newer manual picker with the originally requested
            # square; delivery still checks the intercepted movement cap below.
            wanted = f"cell:{destination[0]},{destination[1]}"
            assert wanted in ids
            return wanted, True
        if prompt['context']['reaction_source_id'] == 'choice:needle.fracture_response':
            return None, False  # This test measures movement, not the optional attack penalty.
        raise AssertionError(prompt)
    prompts=commit(cast_sender(s,ui,mid,name,at=destination), answer)
    e=checked(tmp_path,mid);actor=e.state.actors[ATTACKER]
    assert any('movement'==o['id'] for p in prompts for o in p.get('choice',{}).get('options',[]))
    if destination:
        assert e.grid.distance_ft(actor.position, type(actor.position)(**before['actors'][ATTACKER]['position']))==expected
    else:
        assert actor.movement_remaining_ft-before['actors'][ATTACKER]['movement_remaining_ft']==expected
    assert e.state.actors[PLAYER].resources['resource:core.qi']==before['actors'][PLAYER]['resources']['resource:core.qi']-3


@pytest.mark.parametrize('spend', [False, True])
def test_canceled_complete_reaction_keeps_caller_payment_ownership(monkeypatch, spend):
    from combat import typed_reactions
    fixed(monkeypatch)
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND',kit=DAO),foe_at=(4,6))
    actor=e.state.actors[S.FOE]
    row={'feature_id':DAWN,'name':'Dawnlit Rebuke','block':'generic','kind':'attacked','range_ft':60,
         'costs':[{'resource_id':'resource:core.qi','amount':3}],
         'effects':[{'type':'damage','applies_to':'target','dice':{'count':1,'sides':8},'damage_types':['RADIANT']}]}
    e.typed_reaction_rows[S.FOE].append(row)
    def stop(engine,user,action,*args):
        if action.source_definition_id==DAWN:
            return {'source_id':'test:stop','label':'Reaction interrupted','cancel':True,'spend_activation':spend}
    hook(monkeypatch,'technique_declared',stop)
    c=next(c for c in e.legal_candidates() if c.display_name.startswith('Dao') and c.target_ids==(S.FOE,))
    expected=actor.resources['resource:core.qi']-(3 if spend else 0)
    use(e,c)
    assert actor.resources['resource:core.qi']==expected
    assert actor.reaction_available is not spend
    assert not [ev for ev in e.events if ev.source_definition_id==DAWN and ev.event_type=='DAMAGE_COMMITTED']
    assert len([ev for ev in e.events if ev.source_definition_id==DAWN and ev.payload.get('interceptions')])==1


def test_malformed_reaction_interception_rolls_back_outer_action(monkeypatch):
    from combat import typed_reactions
    from combat.technique_interception import InterceptionError
    fixed(monkeypatch)
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND',kit=DAO),foe_at=(4,6))
    e.typed_reaction_rows[S.FOE].append({'feature_id':DAWN,'name':'Dawnlit Rebuke','block':'generic','kind':'attacked',
        'effects':[{'type':'damage','applies_to':'target','dice':{'count':1,'sides':8},'damage_types':['RADIANT']}]})
    def bad(engine,user,action,*args):
        if action.source_definition_id==DAWN:
            engine._spend_resource(user,'resource:core.qi',1,'test:early')
            return {'source_id':'test:bad','label':'Invalid reply','movement_cap_ft':True}
    hook(monkeypatch,'technique_declared',bad)
    c=next(c for c in e.legal_candidates() if c.display_name.startswith('Dao') and c.target_ids==(S.FOE,))
    before=e.state.model_dump(mode='json')
    with pytest.raises(InterceptionError):
        use(e,c)
    assert e.state.model_dump(mode='json')==before
    assert not getattr(e,'_interception_frame',None)


@pytest.mark.parametrize('interruption', ['reaction', 'resource', 'condition'])
def test_intervening_choice_cannot_spend_an_unavailable_reaction(monkeypatch, interruption):
    fixed(monkeypatch)
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND',kit=DAO),foe_at=(4,6))
    reactor=e.state.actors[S.FOE]
    e.typed_reaction_rows[S.FOE].append({'feature_id':DAWN,'name':'Dawnlit Rebuke','block':'generic','kind':'attacked',
        'costs':[{'resource_id':'resource:core.qi','amount':3}],
        'effects':[{'type':'damage','applies_to':'target','dice':{'count':1,'sides':8},'damage_types':['RADIANT']}]})
    def interrupt(engine, user, action, *args):
        if action.source_definition_id != DAWN:
            return None
        if interruption == 'reaction':
            user.reaction_available=False
            engine._append_event('REACTION_RESOLVED','test:intervening_choice',actor_id=user.entity_id,payload={})
        elif interruption == 'resource':
            engine._spend_resource(user,'resource:core.qi',user.resources['resource:core.qi'],'test:intervening_choice')
        else:
            engine._apply_condition(user,'condition:typed.test_interruption','test:intervening_choice',S.ME,
                expires_on='UNTIL_REMOVED',data={'rule':{'no_reactions':True}})
        return None
    hook(monkeypatch,'technique_declared',interrupt)
    use(e,next(c for c in e.legal_candidates() if c.display_name.startswith('Dao') and c.target_ids==(S.FOE,)))
    assert not [ev for ev in e.events if ev.source_definition_id==DAWN and ev.event_type in {'RESOURCE_SPENT','DAMAGE_COMMITTED'}]
    assert any('cannot continue' in ev.payload.get('log','') for ev in e.events)
