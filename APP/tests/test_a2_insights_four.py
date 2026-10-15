"""Printed Insights through committed table intents, session execution and cold replay."""
import pytest
from tests.auto_worker1_support import fight as service_fight, LEFT, RIGHT, ALLY, act, resolve, turn, reload
from tests.worker2_support import sealed_native_attack
from tests.hunt15_support import action_sender
from combat.gate2_runtime_models import ActionIntent

BOIL='insight.legacy-blood-boil'
EMPOWER='insight.legacy-empowered-technique'
DISTANT='insight.legacy-distant-technique'
MERIDIANS='insight.legacy-enhanced-meridians'
QI='resource:core.qi'
STATE='condition:typed.insights_blood_boil'
THREAD='BLOOD_BASE_BLOOD_THREAD'


def fixture(tmp_path, insights, *, occurrences=(), pb=4, primary='Qi', **kwargs):
    def fields(doc,aid):
        if aid==LEFT:
            doc['spheres_and_talents']['cultivation_insight_record_ids']=list(insights)
            doc['spheres_and_talents']['cultivation_insight_occurrences']=list(occurrences)
    return service_fight(tmp_path,sheet_edit=fields,left_pb=pb,left_resource=primary,**kwargs)


def candidates(combat,mid,name):
    return [c for c in combat._load_session(mid).engine.legal_candidates() if name in c.display_name]


def attack_rolls(engine,aid):
    return [r for r in engine.rolls if r.actor_id==aid and r.reason.startswith('ATTACK:')]


def test_blood_boil_melee_incoming_and_turn_damage(tmp_path):
    attack=[{'type':'attack','attack_kind':'melee','on_hit':[{'type':'damage','dice':'1d6','damage_types':['force']}]}]
    combat,table,mid=fixture(tmp_path,[BOIL],prepare=attack,prepare_attack_bonus=100,
        cause=attack,cause_save_dc=1,maximum_rounds=15)
    resolve(lambda a: act(table,mid,'Blood Boil',a))
    e=reload(combat,mid)
    assert any(c.condition_id==STATE for c in e.state.actors[LEFT].conditions.values())
    assert not candidates(combat,mid,'Blood Boil')
    resolve(lambda a: act(table,mid,'Prepare',a,target_id=RIGHT))
    e=reload(combat,mid)
    rolls=attack_rolls(e,LEFT)
    assert rolls and rolls[-1].mode=='ADVANTAGE'
    before=e.state.actors[LEFT].current_hp
    turn(table,mid,RIGHT)
    e=reload(combat,mid)
    damage=[v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and v.target_ids==(LEFT,) and 'legacy-blood-boil' in v.source_definition_id]
    assert len(damage)==1 and 1<=damage[0].payload['hp_damage']<=4
    assert e.state.actors[LEFT].current_hp==before-damage[0].payload['hp_damage']
    resolve(lambda a: act(table,mid,'Cause',a,target_id=LEFT))
    e=reload(combat,mid)
    assert attack_rolls(e,RIGHT)[-1].mode=='ADVANTAGE'


def test_blood_boil_ranged_no_advantage_and_expiry(tmp_path):
    def seal(bundle):
        if bundle['actor_id']==LEFT:
            sealed_native_attack(bundle,'Ranged control',attack_bonus=100)
    combat,table,mid=fixture(tmp_path,[BOIL],bundle_edit=seal,maximum_rounds=15)
    resolve(lambda a: act(table,mid,'Blood Boil',a))
    resolve(lambda a: act(table,mid,'Ranged control',a,target_id=RIGHT))
    e=reload(combat,mid)
    assert attack_rolls(e,LEFT)[-1].mode=='NORMAL'
    for _ in range(10):
        resolve(lambda a: act(table,mid,'end',a))
        turn(table,mid,LEFT)
    e=reload(combat,mid)
    assert not any(c.condition_id==STATE for c in e.state.actors[LEFT].conditions.values())
    assert not candidates(combat,mid,'Blood Boil')


@pytest.mark.parametrize('item_id,variant', [
    ('tianxia.mortal.weapon.dan_gong', 'bow'),
    ('tianxia.mortal.weapon.bi_shou', 'thrown'),
    ('improvised_weapon', 'improvised_thrown'),
])
def test_blood_boil_compiled_ranged_delivery_preserves_melee_only_penalty(tmp_path,item_id,variant):
    """Production compiled ranged variants stay ranged across commit and cold reload."""
    from combat.motion import HEX

    kit={'items':[{'item_id':'tianxia.mortal.weapon.dan_gong'},
                  {'item_id':'tianxia.mortal.weapon.bi_shou'}]}
    combat,table,mid=fixture(tmp_path,[BOIL],left_kit=kit,left_attack_bonus=100,
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':7,'y':6}},extra_actions=[
            ('Prepare melee-only penalty',{'effects':[{'type':'condition','condition':'current_between_steps',
                'applies_to':'self','expires_on':'UNTIL_REMOVED',
                'condition_data':{'against':RIGHT,'label':'Disadvantage on its next melee attack'}}]})])
    resolve(lambda a:act(table,mid,'Blood Boil',a))
    turn(table,mid,LEFT)
    if variant=='improvised_thrown':
        resolve(lambda a:act(table,mid,'Grab an improvised weapon',a))
    engine=reload(combat,mid)
    actions=[a for a in engine.action_catalog.values() if a.owner_id==LEFT
             and (a.parameters or {}).get('typed',{}).get('range_ft') is not None]
    if variant=='bow':
        action=next(a for a in actions if (a.parameters['typed'].get('weapon') or {}).get('implement_id')==item_id
                    and a.parameters['typed'].get('long_range_ft'))
    elif variant=='thrown':
        action=next(a for a in actions if (a.parameters['typed'].get('weapon') or {}).get('implement_id')==item_id
                    and a.parameters['typed'].get('long_range_ft'))
    else:
        action=next(a for a in actions if a.parameters['typed'].get('source')=='improvised_weapon'
                    and a.parameters['typed'].get('long_range_ft'))
    resolve(lambda a:act(table,mid,action.display_name,a,target_id=RIGHT))
    e=reload(combat,mid)
    assert attack_rolls(e,LEFT)[-1].mode=='NORMAL'

    # Now a melee-only penalty is pending against the same creature. A ranged
    # hit neither receives it nor consumes it; the prior attack proves Blood
    # Boil did not grant ranged Advantage when no penalty could cancel it.
    penalty_action_name=action.display_name
    if variant=='thrown':
        # A thrown weapon is expended when released, so use the still-equipped
        # bow to check that the next-melee-only penalty remains pending.
        later=reload(combat,mid)
        penalty_action_name=next(a.display_name for a in later.action_catalog.values()
            if a.owner_id==LEFT and (a.parameters or {}).get('typed',{}).get('range_ft') is not None
            and (a.parameters['typed'].get('weapon') or {}).get('implement_id')=='tianxia.mortal.weapon.dan_gong'
            and a.parameters['typed'].get('long_range_ft'))
    turn(table,mid,RIGHT)
    turn(table,mid,LEFT)
    if variant=='improvised_thrown':
        resolve(lambda a:act(table,mid,'Grab an improvised weapon',a))
    resolve(lambda a:act(table,mid,'Prepare melee-only penalty',a))
    resolve(lambda a:act(table,mid,penalty_action_name,a,target_id=RIGHT))
    e=reload(combat,mid)
    assert attack_rolls(e,LEFT)[-1].mode=='NORMAL'
    assert any(c.condition_id==HEX and (c.data or {}).get('against')==RIGHT
               for c in e.state.actors[LEFT].conditions.values())


def test_blood_boil_real_numeric_reach_melee_talent(tmp_path):
    combat,table,mid=fixture(tmp_path,[BOIL],talents=['tianxia.talent.thread.garrote_thread'],
        spheres=['tianxia.sphere.thread'],left_attack_bonus=100)
    resolve(lambda a:act(table,mid,'Blood Boil',a))
    action=next(a for a in reload(combat,mid).action_catalog.values()
        if a.owner_id==LEFT and 'Garrote Thread' == a.display_name)
    resolve(lambda a:act(table,mid,action.display_name,a,target_id=RIGHT))
    assert attack_rolls(reload(combat,mid),LEFT)[-1].mode=='ADVANTAGE'


def test_blood_boil_unarmed_numeric_reach_talent_is_melee(tmp_path):
    combat,table,mid=fixture(tmp_path,[BOIL],talents=['TAL_VOID_EMPTY_PALM_SCRIPTURE'],
        spheres=['tianxia.sphere.void'],left_attack_bonus=100)
    resolve(lambda a:act(table,mid,'Blood Boil',a))
    action=next(a for a in reload(combat,mid).action_catalog.values()
        if a.owner_id==LEFT and 'Empty Palm Scripture' in a.display_name)
    resolve(lambda a:act(table,mid,action.display_name,a,target_id=RIGHT))
    e=reload(combat,mid)
    assert attack_rolls(e,LEFT)[-1].mode=='ADVANTAGE'


@pytest.mark.parametrize('primary,pools,pb,expected',[
 ('Qi',['Qi'],4,108),('Stamina',['Stamina','Stamina'],5,120),
 ('Resonance',['Qi'],4,100),('Resonance',['Resonance','Qi'],6,112)])
def test_enhanced_meridians_recorded_occurrences(tmp_path,primary,pools,pb,expected):
    occ=[{'insight_id':MERIDIANS,'occurrence_id':str(i),'parameters':{'resource_pool':pool}}
         for i,pool in enumerate(pools)]
    combat,table,mid=fixture(tmp_path,[MERIDIANS],primary=primary,occurrences=occ,pb=pb)
    # A real service session intent persists the correctly compiled pool.
    session=combat._load_session(mid)
    c=next(c for c in session.engine.legal_candidates() if c.kind.value=='END_TURN')
    session.submit_intent(ActionIntent(intent_id='enhanced',decision_id=c.decision_id,candidate_id=c.candidate_id,
        state_version=c.state_version,actor_id=c.actor_id,target_ids=c.target_ids,destination=c.destination,option_ids=c.option_ids),primary_decision_record=None,reaction_provider=None)
    e=reload(combat,mid)
    actor=e.state.actors[LEFT];rid='resource:core.'+primary.lower()
    assert actor.resource_maximums[rid]==expected
    assert actor.resources[rid]==expected
    assert 'resource:core.qi' not in actor.resources if primary!='Qi' else True


def test_distant_technique_real_talent_range_and_cost(tmp_path):
    combat,table,mid=fixture(tmp_path,[DISTANT],talents=[THREAD],spheres=['tianxia.sphere.blood'],
        positions={LEFT:{'x':1,'y':1},RIGHT:{'x':15,'y':1}})
    e=reload(combat,mid)
    action=next(a for a in e.action_catalog.values() if a.owner_id==LEFT and 'Blood Thread + Distant Technique' in a.display_name)
    base=next(a for a in e.action_catalog.values() if a.owner_id==LEFT and a.display_name=='Blood Thread')
    assert action.range_ft==2*base.range_ft
    assert sum(v for r,v in action.costs if r==QI)==sum(v for r,v in base.costs if r==QI)+1
    assert not candidates(combat,mid,'Blood Thread') or any('Distant' in c.display_name for c in candidates(combat,mid,'Blood Thread'))
    before=e.state.actors[LEFT].resources[QI]
    resolve(lambda a: act(table,mid,action.display_name,a,target_id=RIGHT))
    e=reload(combat,mid)
    assert e.state.actors[LEFT].resources[QI]==before-sum(v for r,v in action.costs if r==QI)


@pytest.mark.parametrize('accept',[True,False])
def test_empowered_damage_payment_and_recorded_reroll(tmp_path,accept):
    combat,table,mid=fixture(tmp_path,[EMPOWER],talents=[THREAD],spheres=['tianxia.sphere.blood'],left_attack_bonus=100)
    before=reload(combat,mid).state.actors[LEFT].resources[QI]
    _,prompts=resolve(lambda a: act(table,mid,'Blood Thread',a,target_id=RIGHT),
        {'choice:needle.insights_empowered':[QI] if accept else []})
    e=reload(combat,mid)
    extra=[r for r in e.rolls if r.reason.startswith('DAMAGE_REROLL:')]
    assert bool(extra)==accept
    assert e.state.actors[LEFT].resources[QI]==before-(1 if accept else 0)
    assert any(p['context']['reaction_source_id']=='choice:needle.insights_empowered' for p in prompts)

ADAMANTINE='insight.legacy-adamantine-breath'
CUSTODIAN='insight.hollow-script-custodian'
GUARD='tianxia.path.body_refining.feature.stamina_guard'
HOOK='tianxia.talent.chains.restraining_hook'
HOOK_MASTER='insight.hook-master'


def test_hook_master_range_and_free_reaction_price(tmp_path):
    # A movement trigger commits the real Restraining Hook reaction.
    combat,table,mid=fixture(tmp_path,[HOOK_MASTER],talents=[HOOK],spheres=['tianxia.sphere.chains'],
        positions={LEFT:{'x':2,'y':1},RIGHT:{'x':14,'y':1}},left_save_dc=100,
        cause=[{'type':'rider_step','distance_ft':15,'no_oa':True}])
    e=reload(combat,mid)
    rows=[r for r in e.typed_reaction_rows[LEFT] if r.get('feature_id')==HOOK]
    assert rows and max(r['range_ft'] for r in rows)==60
    balance=e.state.actors[LEFT].resources[QI]
    turn(table,mid,RIGHT)
    for x in (13,12,11):
        def send_move(answers):
            state=table.state(mid);menu=state['menu']
            option=next(o for o in menu['moves'] if o['destination']=={'x':x,'y':1})
            return table.act(mid,option['candidate_id'],menu['decision_id'],menu['state_version'],state['last_sequence'],answers)
        resolve(send_move,{'choice:needle.hook_master_payment':['free']} if x==11 else None)
        if x!=11:
            assert reload(combat,mid).state.actors[LEFT].resources['resource:uses.insight.hook-master']==1
    e=reload(combat,mid)
    assert e.state.actors[LEFT].resources[QI]==balance
    assert e.state.actors[LEFT].resources['resource:uses.insight.hook-master']==0
    assert e.state.actors[RIGHT].movement_remaining_ft==0
    assert e.state.actors[RIGHT].position.x==10
    assert e.state.actors[LEFT].resources[QI]==balance


def test_hook_master_can_pay_and_preserve_free_use(tmp_path):
    combat,table,mid=fixture(tmp_path,[HOOK_MASTER],talents=[HOOK],spheres=['tianxia.sphere.chains'],
        positions={LEFT:{'x':2,'y':1},RIGHT:{'x':14,'y':1}},left_save_dc=100,
        cause=[{'type':'rider_step','distance_ft':15,'no_oa':True}])
    balance=reload(combat,mid).state.actors[LEFT].resources[QI]
    turn(table,mid,RIGHT)
    def send(x,answer):
        state=table.state(mid);menu=state['menu']
        option=next(o for o in menu['moves'] if o['destination']=={'x':x,'y':1})
        return table.act(mid,option['candidate_id'],menu['decision_id'],menu['state_version'],state['last_sequence'],answer)
    for x in (13,12): resolve(lambda answers:send(x,answers))
    _,prompts=resolve(lambda answers:send(11,answers),{'choice:needle.hook_master_payment':['paid']})
    e=reload(combat,mid)
    assert e.state.actors[LEFT].resources[QI]==balance-1
    assert e.state.actors[LEFT].resources['resource:uses.insight.hook-master']==1
    mover_name=e.state.actors[RIGHT].display_name
    assert any(p.get('action')=='movement' and p.get('affected')==mover_name and mover_name in p.get('moment','') for p in prompts)


@pytest.mark.parametrize('accept',[True,False])
def test_adamantine_breath_paid_guard_actual_roll(tmp_path,accept):
    combat,table,mid=fixture(tmp_path,[ADAMANTINE],talents=[GUARD],primary='Stamina',
        cause=[{'type':'damage','flat':100,'damage_types':['force']}])
    turn(table,mid,RIGHT)
    _,prompts=resolve(lambda a:act(table,mid,'Cause',a,target_id=LEFT),
        {'choice:needle.insights_adamantine':['maximize'] if accept else []})
    e=reload(combat,mid)
    rolls=[r for r in e.rolls if r.reason.startswith('DAMAGE_SOAK:')]
    assert rolls
    result=next(v for v in e.events if v.event_type=='REACTION_RESOLVED' and v.source_definition_id==GUARD)
    expected=rolls[0].total+(10-min(rolls[0].dice) if accept else 0)
    assert result.payload['reduction']==expected
    assert bool(e.state.actors[LEFT].turn_flags.get('once_per_round:insights_adamantine'))==accept
    assert any(p['context']['reaction_source_id']=='choice:needle.insights_adamantine' for p in prompts)
    choice=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.insights_adamantine')
    assert choice.get('action')=='Cause' and choice.get('affected')==e.state.actors[LEFT].display_name and 'Cause' in choice.get('moment','')


@pytest.mark.parametrize('category,mode',[('disease','ADVANTAGE'),('physical_injury_exhaustion','ADVANTAGE'),('environmental_exposure_exhaustion','NORMAL')])
def test_iron_blood_exact_save_provenance(tmp_path,category,mode):
    effect={'type':'save','ability':'con','save_categories':[category],
        'on_fail':[{'type':'condition','condition':'exhaustion','applies_to':'target','duration':'one_minute'}],'on_success':[]}
    combat,table,mid=fixture(tmp_path,['insight.iron-blood-circulation'],cause=[effect])
    turn(table,mid,RIGHT)
    resolve(lambda a:act(table,mid,'Cause',a,target_id=LEFT))
    e=reload(combat,mid)
    saves=[r for r in e.rolls if r.actor_id==LEFT and r.reason.startswith('SAVE:')]
    assert saves[-1].mode==mode


def test_hollow_script_extends_new_hollowed_and_uses_once(tmp_path):
    def seal(b):
        if b['actor_id']==LEFT:
            a=next(a for a in b['action_catalog'] if a['display_name']=='Prepare')
            a['parameters']['typed']['sphere']='tianxia.sphere.void'
    effect={'type':'save','ability':'cha','on_fail':[{'type':'condition','condition':'hollowed','applies_to':'target',
        'duration':'until_start_of_your_next_turn'}],'on_success':[]}
    combat,table,mid=fixture(tmp_path,[CUSTODIAN],prepare=[effect],bundle_edit=seal,left_save_dc=100)
    resolve(lambda a:act(table,mid,'Prepare',a,target_id=RIGHT))
    e=reload(combat,mid)
    hollow=next(c for c in e.state.actors[RIGHT].conditions.values() if c.condition_id=='condition:typed.hollowed')
    assert hollow.expires_on=='END_OF_SOURCE_TURN_AT:'+str(e.state.actors[LEFT].turns_started+1)
    resolve(lambda a:act(table,mid,'end',a));turn(table,mid,LEFT)
    e=reload(combat,mid)
    assert any(c.condition_id=='condition:typed.hollowed' for c in e.state.actors[RIGHT].conditions.values())
    assert any(c.condition_id=='condition:typed.insights_custodian_used' for c in e.state.actors[LEFT].conditions.values())
    resolve(lambda a:act(table,mid,'end',a))
    e=reload(combat,mid)
    assert not any(c.condition_id=='condition:typed.hollowed' for c in e.state.actors[RIGHT].conditions.values())
    turn(table,mid,LEFT)
    _,prompts=resolve(lambda a:act(table,mid,'Prepare',a,target_id=RIGHT))
    assert not any(p['context']['reaction_source_id']=='choice:needle.insights_custodian' for p in prompts)


def test_empowered_critical_damage_replaces_selected_count(tmp_path,monkeypatch):
    """A critical damage stimulus exercises the real damage-effect reroll route.

    The Hold fixture supplies a critical roll context, not an Empowered benefit;
    ownership, pricing, choice, damage and replacement dice come from production.
    """
    from tests.test_tabletop_hunt6 import on_hold
    from combat.typed_executor import Context,run_effects
    def stimulus(engine):
        actor,target=engine.state.actors[LEFT],engine.state.actors[RIGHT]
        action=next(a for a in engine.action_catalog.values() if a.owner_id==LEFT and a.display_name=='Blood Thread')
        ctx=Context(engine,actor,action,engine._active_intent,action.parameters['typed'],[target],target,{},critical_hit=True)
        run_effects(ctx,[{'type':'damage','applies_to':'target','dice':'3d8','damage_types':['necrotic']}])
    on_hold(monkeypatch,stimulus)
    combat,table,mid=fixture(tmp_path,[EMPOWER],talents=[THREAD],spheres=['tianxia.sphere.blood'])
    before=reload(combat,mid).state.actors[LEFT].resources[QI]
    resolve(lambda a:act(table,mid,'system:combat.hold_position',a),{'choice:needle.insights_empowered':[QI+'|1']})
    e=reload(combat,mid)
    original=next(r for r in e.rolls if r.reason.startswith('DAMAGE:'))
    replacement=next(r for r in e.rolls if r.reason.startswith('DAMAGE_REROLL:'))
    assert len(original.dice)==6
    assert len(replacement.dice)==1
    damage=next(v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and v.target_ids==(RIGHT,))
    assert damage.payload['hp_damage']==original.total-min(original.dice)+replacement.total
    assert e.state.actors[LEFT].resources[QI]==before-1


def test_empowered_decline_preserves_later_roll_and_expression_modifier(tmp_path,monkeypatch):
    from tests.test_tabletop_hunt6 import on_hold
    from tests.auto_worker1_support import settle
    from combat.typed_executor import Context,run_effects
    def seal(bundle):
        if bundle['actor_id']==LEFT:
            action=next(a for a in bundle['action_catalog'] if a['display_name']=='Blood Thread')
            # A sealed expression can have a different key than the primary Path.
            action['parameters']['typed']['numbers']['key_mod']=4
    def stimulus(engine):
        actor,target=engine.state.actors[LEFT],engine.state.actors[RIGHT]
        action=next(a for a in engine.action_catalog.values() if a.owner_id==LEFT and a.display_name=='Blood Thread')
        ctx=Context(engine,actor,action,engine._active_intent,action.parameters['typed'],[target],target,{})
        run_effects(ctx,[{'type':'damage','applies_to':'target','dice':dice,'damage_types':['necrotic']}
                        for dice in ('1d8','4d8','1d8')])
    on_hold(monkeypatch,stimulus)
    combat,table,mid=fixture(tmp_path,[EMPOWER],talents=[THREAD],spheres=['tianxia.sphere.blood'],bundle_edit=seal)
    before=reload(combat,mid).state.actors[LEFT].resources[QI]
    seen={}
    def choose(prompt):
        assert prompt['context']['reaction_source_id']=='choice:needle.insights_empowered'
        checkpoint=prompt['context']['checkpoint']
        seen.setdefault(checkpoint,len(seen))
        return [] if seen[checkpoint]==0 else [QI+'|3']
    settle(lambda a:act(table,mid,'system:combat.hold_position',a),choose=choose)
    e=reload(combat,mid)
    replacements=[r for r in e.rolls if r.reason.startswith('DAMAGE_REROLL:')]
    assert len(seen)==2
    assert len(replacements)==1 and len(replacements[0].dice)==3
    assert e.state.actors[LEFT].resources[QI]==before-1
