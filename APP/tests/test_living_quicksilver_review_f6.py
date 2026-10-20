"""Execution regressions for retained-roll, route, area and granted delivery."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from combat import ext
from combat.gate2_runtime_models import ActionDefinition
from tests.test_living_quicksilver_native import (
    setup, combat, engine, use, A, B, QI, MASS, FAMILY, FEATURES,
    CombatService, TabletopService, candidate, settle, turn,
)

BLADE = 'action:test.review.qi_blade'
AREA = 'action:test.review.area'


def add_hook(monkeypatch, name, fn):
    # Synthetic source providers participate in normal compiler/table/replay
    # dispatch; no live transport, engine methods or core classes are patched.
    ext.callbacks(name)
    monkeypatch.setitem(ext._HOOKS, name, [*ext._HOOKS.get(name, ()), fn])


def synthetic_actions(monkeypatch, *, damage_sides=6, flat_rider=7):
    def compile_actions(info):
        aid=info['actor_id']
        weapon={'damage':{'count':1,'sides':damage_sides,'modifier':0},'damage_type':'FIRE'}
        base={'source':FEATURES[2],'numbers':{**info['numbers'],'attack_bonus':100},
              'qi_powered':True,'duration':{'kind':'instant'}}
        out=[ActionDefinition(source_definition_id=BLADE+aid,display_name='Review Qi blade',
            owner_id=aid,economy='ACTION',resolution_kind='TYPED',target_kind='HOSTILE_ENTITY',range_ft=15,
            costs=((QI,1),),parameters={'attack_kind':'weapon','expected_damage':4,
            'typed':{**base,'weapon':weapon,'effects':[{'type':'attack','attack_kind':'weapon','count':1,
                'on_hit':[{'type':'damage','weapon_damage':True,'applies_to':'target'},
                          {'type':'damage','flat':flat_rider,'damage_types':['FIRE'],'applies_to':'target'}]}]}})]
        if FEATURES[2] in info['owned_ids']:
            out.append(ActionDefinition(source_definition_id=AREA+aid,display_name='Review Qi area',
                owner_id=aid,economy='ACTION',resolution_kind='TYPED',target_kind='CELL',range_ft=30,
                parameters={'expected_damage':4,'any_cell':True,'typed':{**base,'weapon':None,
                    'area':{'shape':'cone','size_ft':15,'recipients':'all'},
                    'effects':[{'type':'damage','dice':{'count':1,'sides':6},'damage_types':['FIRE'],'applies_to':'all_targets'}]}}))
        # compile_actions providers see the same pre-extension action list.
        # Ask the native object compiler to derive this synthetic weapon's
        # object sibling explicitly, rather than assuming provider order.
        from combat.ext.objects import object_actions
        for obj_action in object_actions({**info,'actions':[out[0]],'passives':[]}) or []:
            if obj_action.parameters.get('object_attack'):
                params=deepcopy(obj_action.parameters)
                # The original creature profile can carry a CL-scaled full
                # attack sequence. An already-rolled object strike must not
                # acquire that extra attack when its recipient changes.
                params['typed']['object_creature_delivery']['effects'][0]['count_by_cl']=[[1,20,2]]
                obj_action=obj_action.model_copy(update={'parameters':params})
                out.append(obj_action.model_copy(update={'source_definition_id':'action:test.review.object_attack.'+aid,
                    'display_name':'Review Qi blade at an object'}))
        return out
    add_hook(monkeypatch,'compile_actions',compile_actions)


def living_bodies(e):
    return [o for o in e.state.objects.values() if o.component.get('quicksilver_body') and not o.destroyed]


def test_exchange_to_body_keeps_native_damage_hooks_and_one_roll(tmp_path,monkeypatch):
    synthetic_actions(monkeypatch)
    seen=[]; completions=[]; cancelled=[]
    def critical_range(e,a,t,s):
        return 2 if s.get('source_definition_id')==BLADE+B else None
    def cancel(e,a,t,s,r,i):
        if s.get('source_definition_id')==BLADE+B:
            cancelled.append(t.entity_id)
            return True
    add_hook(monkeypatch,'attack_critical_range',critical_range)
    add_hook(monkeypatch,'critical_cancel',cancel)
    add_hook(monkeypatch,'object_attack_completed',lambda e,a,o,s,h,i:completions.append((o.object_id,h)))
    def adjustment(e,actor,target,spec,intent,source,roll):
        if source==BLADE+B:
            seen.append((target.entity_id,len(roll.dice)))
            return 9
    add_hook(monkeypatch,'confirmed_damage_roll_adjustment',adjustment)
    cold,jid,act,world=setup(tmp_path,monkeypatch,14,positions={A:{'x':3,'y':3},B:{'x':4,'y':3}})
    table,mid=combat(cold,jid,tmp_path)
    body=living_bodies(use(cold,table,mid,'Create Quicksilver Body: 2 Qi'))[0]
    turn(table,mid,B)
    for _ in range(4):
        before=engine(cold,mid)
        c=candidate(cold(),mid,'Review Qi blade',target=A)
        settle(table,mid,c.candidate_id,picks={'choice:needle.quicksilver.exchange_substance':body.object_id})
        e=engine(cold,mid)
        if any(ev.event_type=='REACTION_RESOLVED' and ev.source_definition_id==FEATURES[1] for ev in e.events[len(before.events):]):break
        turn(table,mid,A);turn(table,mid,B)
    assert e.state.actors[A].current_hp==before.state.actors[A].current_hp
    assert e.state.objects[body.object_id].current_hp<body.current_hp
    assert (body.object_id,1) in seen
    assert body.object_id in cancelled
    assert completions[-1]==(body.object_id,True)
    packets=[ev for ev in e.events[len(before.events):] if ev.event_type=='OBJECT_UPDATED' and body.object_id in ev.target_ids and ev.payload.get('damage')]
    assert len(packets)==2, 'The redirected strike retains its additional on-hit damage.'
    attack_events=[ev for ev in e.events[len(before.events):] if ev.event_type=='ATTACK_ROLLED']
    assert len({ev.payload['roll_id'] for ev in attack_events})==1
    assert not any(ev.event_type=='DAMAGE_COMMITTED' and A in ev.target_ids for ev in e.events[len(before.events):])


def test_exchange_to_owner_keeps_native_hit_riders(tmp_path,monkeypatch):
    synthetic_actions(monkeypatch)
    def rider(ctx,target,kind):
        if ctx.source=='action:test.review.object_attack.'+B and target.entity_id==A:
            ctx.engine._gain_resource(ctx.actor,QI,2,ctx.source)
    add_hook(monkeypatch,'after_hit',rider)
    cold,jid,act,world=setup(tmp_path,monkeypatch,6,positions={A:{'x':3,'y':3},B:{'x':4,'y':3}})
    table,mid=combat(cold,jid,tmp_path)
    body=living_bodies(use(cold,table,mid,'Create Quicksilver Body: 2 Qi'))[0]
    turn(table,mid,B)
    warmup=candidate(cold(),mid,'Review Qi blade',target=A)
    settle(table,mid,warmup.candidate_id,picks={'choice:needle.quicksilver.exchange_substance':None})
    turn(table,mid,A);turn(table,mid,B)
    e=engine(cold,mid)
    assert e.state.actors[B].resources[QI]<e.state.actors[B].resource_maximums[QI]
    c=next(c for c in e.legal_candidates() if c.target_ids==(body.object_id,) and
           e.action_catalog.get(c.source_definition_id) and e.action_catalog[c.source_definition_id].parameters.get('object_attack')
           and e.action_catalog[c.source_definition_id].parameters['typed'].get('object_weapon_group')=='weapon')
    source=c.source_definition_id
    for _ in range(4):
        before=len(e.events)
        settle(table,mid,c.candidate_id,picks={'choice:needle.quicksilver.body_exchange':'exchange'})
        e=engine(cold,mid)
        if any(ev.event_type=='REACTION_RESOLVED' and ev.source_definition_id==FEATURES[1] for ev in e.events[before:]):break
        turn(table,mid,A);turn(table,mid,B)
        e=engine(cold,mid)
        c=next(c for c in e.legal_candidates() if c.target_ids==(body.object_id,) and c.source_definition_id==source)
    assert e.state.objects[body.object_id].current_hp==body.current_hp
    assert any(ev.event_type=='RESOURCE_GAINED' and ev.actor_id==B and ev.source_definition_id==c.source_definition_id and ev.payload['gained']>0 for ev in e.events[before:])
    attacks=[ev for ev in e.events[before:] if ev.event_type=='ATTACK_ROLLED']
    assert len({ev.payload['roll_id'] for ev in attacks})==1


def test_body_walk_visits_intermediate_hazard_and_stops_when_destroyed(tmp_path,monkeypatch):
    def field(engine):
        from combat.gate2_runtime_models import ZoneState,Position
        return [ZoneState(zone_id='zone:review.hot-floor',source_definition_id='source:hot-floor',owner_id=B,
            center=Position(x=3,y=5),radius_cells=0,affected_cells=tuple(Position(x=x,y=5) for x in range(12)),concentration_link=False,
            duration_rounds=None,created_round=0,trigger_profile={'kind':'TYPED','name':'Hot floor',
                'triggers':[{'id':'hot','on':['enter'],'who':'objects','effects':[
                    {'type':'object_damage','dice':{'count':1,'sides':4,'modifier':99},'damage_types':['FIRE']}]}]})]
    add_hook(monkeypatch,'zones',field)
    cold,jid,act,world=setup(tmp_path,monkeypatch,6)
    table,mid=combat(cold,jid,tmp_path)
    body=living_bodies(use(cold,table,mid,'Create Quicksilver Body: 2 Qi'))[0]
    # The selected route is straight through the hot square; neither endpoint
    # is hazardous. The actual path must stop there rather than teleport past.
    e=use(cold,table,mid,'Move Quicksilver Bodies',
          picks={'choice:needle.quicksilver.move_'+body.object_id:'3,6,0'})
    assert e.state.objects[body.object_id].destroyed
    assert e.state.objects[body.object_id].position.y==5


def test_area_expression_delivers_damage_and_rebinds_shape_metadata(tmp_path,monkeypatch):
    synthetic_actions(monkeypatch)
    # Record a real hostile area via native completion. Select the area clause,
    # not a fabricated ledger pattern.
    def enemy_area(info):
        if info['actor_id']!=B:return None
        return [ActionDefinition(source_definition_id='action:test.hostile_sphere',display_name='Review hostile sphere',
            owner_id=B,economy='ACTION',resolution_kind='TYPED',target_kind='CELL',range_ft=30,
            parameters={'expected_damage':1,'any_cell':True,'typed':{'source':'test:hostile-sphere','qi_powered':True,
                'numbers':dict(info['numbers']),'area':{'shape':'sphere','size_ft':10,'recipients':'all'},
                'effects':[{'type':'damage','dice':{'count':1,'sides':4},'damage_types':['FIRE'],'applies_to':'all_targets'}]}})]
    add_hook(monkeypatch,'compile_actions',enemy_area)
    observed=[]
    def complete(ctx):
        if ctx.source==AREA+A:observed.append(deepcopy(ctx.typed))
    add_hook(monkeypatch,'technique_used',complete)
    cold,jid,act,world=setup(tmp_path,monkeypatch,10,positions={A:{'x':3,'y':3},B:{'x':5,'y':3}})
    table,mid=combat(cold,jid,tmp_path)
    turn(table,mid,B)
    c=candidate(cold(),mid,'Review hostile sphere',at=(3,3))
    settle(table,mid,c.candidate_id,picks={'choice:needle.quicksilver.record_pattern':'1'})
    turn(table,mid,A)
    e=engine(cold,mid);before=len(e.events)
    c=candidate(cold(),mid,'Review Qi area',at=(5,3),remote=False)
    settle(table,mid,c.candidate_id,picks={'choice:needle.quicksilver.express_pattern':MASS,
        'choice:needle.quicksilver.conversion':None,'choice:needle.quicksilver.multiple_origins':None})
    e=engine(cold,mid)
    assert any(ev.event_type=='DAMAGE_COMMITTED' and B in ev.target_ids and ev.source_definition_id==c.source_definition_id for ev in e.events[before:])
    assert observed[-1]['area']['shape']=='sphere'
    assert 2*observed[-1]['area']['size_ft']<=15
    assert observed[-1]['_area_centre']==(5,3) and '_area_aim' not in observed[-1]


def prepare_sea(cold,jid,tmp_path):
    table,mid=combat(cold,jid,tmp_path)
    body=living_bodies(use(cold,table,mid,'Create Quicksilver Body: 2 Qi'))[0]
    turn(table,mid,B);turn(table,mid,A)
    use(cold,table,mid,'Undying Prima Materia')
    turn(table,mid,B)
    settle(table,mid,table.state(mid)['menu']['end_turn'],picks={
        'choice:needle.quicksilver.free_body':'3,5,0','choice:needle.quicksilver.configuration':'sea'})
    return table,mid,body.object_id


def test_weapon_sea_native_completion_and_candidate_gate(tmp_path,monkeypatch):
    synthetic_actions(monkeypatch)
    def completed(ctx):
        if ctx.source==BLADE+A:
            ctx.engine._apply_condition(ctx.actor,'condition:test.used_blade',ctx.source,A,
                expires_on='UNTIL_REMOVED',data={'label':'Used Qi blade'})
    def gate(e,a,c,action):
        if action and action.source_definition_id==BLADE+A and any(x.condition_id=='condition:test.used_blade' for x in a.conditions.values()):
            return False
    add_hook(monkeypatch,'technique_used',completed)
    add_hook(monkeypatch,'candidate_allowed',gate)
    cold,jid,act,world=setup(tmp_path,monkeypatch,18,positions={A:{'x':3,'y':3},B:{'x':4,'y':4}})
    table,mid,first=prepare_sea(cold,jid,tmp_path)
    e=engine(cold,mid);second=next(o.object_id for o in living_bodies(e) if o.object_id!=first)
    before=e.state.actors[A].resources[QI]
    use(cold,table,mid,'Weapon-Sea: weapon-delivered technique and one attack',picks={
        'choice:needle.quicksilver.sea_first':first,'choice:needle.quicksilver.sea_second':second,
        'choice:needle.quicksilver.sea_technique':BLADE+A,'choice:needle.quicksilver.sea_technique_target':B,
        'choice:needle.quicksilver.sea_target_'+second:B,'choice:needle.quicksilver.conversion':None})
    e=engine(cold,mid)
    assert any(c.condition_id=='condition:test.used_blade' for c in e.state.actors[A].conditions.values())
    assert e.state.actors[A].resources[QI]==before-1
    from combat.granted_actions import candidates
    from combat.ext.mgr_reserve_living_quicksilver_immortal_embryo_living_mercury_body import sea_origins
    origin=next(o for o in sea_origins(e,e.state.actors[A]) if o['id']==first)
    assert candidates(e,e.state.actors[A],e.action_catalog[BLADE+A],origin=origin)==[]


def test_journey_continuation_ends_perfected_body_statistics(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,18)
    state=cold().journey_state(jid)
    mid=cold().journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'},maximum_rounds=2)['match_id']
    table=TabletopService(cold(),tmp_path);turn(table,mid,A)
    use(cold,table,mid,'Undying Prima Materia')
    turn(table,mid,B)
    settle(table,mid,table.state(mid)['menu']['end_turn'],picks={
        'choice:needle.quicksilver.free_body':'3,4,0','choice:needle.quicksilver.configuration':'mirror'})
    body=living_bodies(engine(cold,mid))[0]
    assert body.maximum_hp==72 and body.component['perfected']==1
    for _ in range(12):
        if engine(cold,mid).state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    state=cold().journey_state(jid)
    resumed=cold().journey_resume(jid,state['revision'],effect_resolutions={A:'The one-minute transformation has ended.'})
    stored=resumed['runtime_objects'][body.object_id]
    assert stored['maximum_hp']==36 and stored['current_hp']<=36
    assert stored['component']['perfected']==0 and stored['component']['fly_speed_ft']==0
    assert stored['component']['allowed_reactions']==[]
    assert cold().journey_state(jid)==resumed
    new=cold().journey_start_combat(jid,resumed['revision'],{A:'team:a',B:'team:b'})['match_id']
    obj=engine(cold,new).state.objects[body.object_id]
    assert obj.maximum_hp==36 and obj.component['hover']==0


from combat.attack_continuation import same_roll, take


def test_retained_roll_is_scoped_consumed_once_and_restored_after_nesting():
    engine=object(); other_engine=object()
    actor=SimpleNamespace(entity_id='attacker')
    other=SimpleNamespace(entity_id='other')
    first=object(); nested=object()
    assert take(engine,actor,'attack') is None
    with same_roll(engine,actor,'attack',first,17):
        assert take(other_engine,actor,'attack') is None
        assert take(engine,other,'attack') is None
        assert take(engine,actor,'another-source') is None
        with same_roll(engine,actor,'reaction',nested,12):
            assert take(engine,actor,'attack') is None
            assert take(engine,actor,'reaction')==(nested,12)
            assert take(engine,actor,'reaction') is None
        assert take(engine,actor,'attack')==(first,17)
        assert take(engine,actor,'attack') is None
    assert take(engine,actor,'attack') is None
