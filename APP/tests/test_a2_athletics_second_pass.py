"""Second pass: actual service/table actions, embedded choices and cold reload."""
import pytest
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from tests.auto8f1_table_support import fixture, candidate_id, move_candidate_id, reload_identical, OWNER, FOE, SECOND, AXE_KIT
from combat.ext.needle import cell_id
POOL='condition:typed.athletics_momentum'
SOURCE='TAL_ATHLETICS_UNWILLING_BOOST'
GRIP='TAL_ATHLETICS_SURE_GRIP'
LUNGS='TAL_ATHLETICS_STRONG_LUNGS'
CM='TAL_LIGHTNING_CHARGED_COUNTERMEASURE'


def seal_actions(bundles):
    for b in bundles:
        who=b['actor_id']
        if who != OWNER:
            b['actor_template']['strength_score']=18
            continue
        b['actor_template']['armor_class']=1
        for name,effects in [
            ('Become incapacitated',[{'type':'condition','condition':'incapacitated','applies_to':'self'}]),
            ('Become frightened',[{'type':'condition','condition':'frightened','applies_to':'self'}]),
            ('Become stunned',[{'type':'condition','condition':'stunned','applies_to':'self'}]),
            ('Become unconscious',[{'type':'condition','condition':'unconscious','applies_to':'self'}]),
            ('Climb check',[{'type':'contest_against','actor_check':{'ability':'STR','skill':'Athletics','hazards':['climb']},
                             'target_check':{'kind':'dc','basis':'save_dc'}}]),
        ]:
            add_action(b,name,effects)
        for category in ('inhalation','suffocation','forced_march_exhaustion','poison','ordinary'):
            for ability in ('con','dex'):
                add_action(b,f'{ability} {category}',[{'type':'save','ability':ability,'dc':12,'applies_to':'self',
                    'save_categories':[category], 'on_fail':[], 'on_success':[]}])


def add_action(bundle,name,effects):
    source='action:test.ath2.'+name.replace(' ','_')
    a=ActionDefinition(source_definition_id=source,display_name=name,owner_id=bundle['actor_id'],
        economy=EconomyKind.NONE,resolution_kind='TYPED',target_kind='HOSTILE_ENTITY' if name=='Climb check' else 'SELF',range_ft=5 if name=='Climb check' else None,
        parameters={'free_primary':True,'typed':{'effects':effects,'numbers':{'save_dc':12},'riders':[],'duration':{'kind':'instant'}}})
    bundle['action_catalog'].append(a.model_dump(mode='json'))
    bundle['actor_template']['action_ids'].append(source)


def game_for(tmp_path,talents,*,hit=True,ally=True):
    def transform(bs):
        seal_actions(bs)
        for b in bs:
            if b['actor_id']==OWNER:
                b['actor_template']['armor_class']=1 if hit else 80
            else:
                b['actor_template']['strength_score']=18
                b['actor_template']['dexterity_score']=1
    return fixture(tmp_path,talents,seed='ATH2-'+tmp_path.name,bundle_transform=transform,
        places={OWNER:{'x':3,'y':6},FOE:{'x':4,'y':6},SECOND:{'x':2,'y':6}},
        allies=(FOE,) if ally else ())


def commit(g,label,chooser=None):
    return g['commit'](candidate_id(g['menu'](),label),chooser)


def finish(g):
    reload_identical(g['combat'],g['match_id'],g['userdata'])


def momentum(g):
    return [c for c in g['reload_owner']().conditions.values() if c.condition_id==POOL]


@pytest.mark.parametrize('hit,bonus',[(True,True),(False,False)])
def test_assisting_real_oa_scales_from_ally_and_miss_costs_bonus_action(tmp_path,hit,bonus):
    g=game_for(tmp_path,[SOURCE],hit=hit)
    # Allies and enemies are simultaneously in reach. Only the printed ally can assist.
    opts=[o for group in g['menu']()['actions'] for o in group['options']
          if 'ask an ally to assist' in o['label']]
    assert opts and all(o['target_ids']==[FOE] for o in opts)
    commit(g,'ask an ally to assist')
    assert sum(c.data['half_feet']/2 for c in momentum(g))==20
    assert g['reload_owner']().bonus_action_available is bonus
    assert not g['stored_engine']().state.actors[FOE].reaction_available
    assert g['stored_engine']().state.actors[SECOND].reaction_available
    assert any(e.event_type=='ATTACK_ROLLED' and e.actor_id==FOE for e in g['stored_engine']().events)
    finish(g)


def test_momentum_direction_and_native_horizontal_movement_reloads(tmp_path):
    g=game_for(tmp_path,[SOURCE])
    commit(g,'ask an ally to assist')
    finish(g)
    before=g['reload_owner']().movement_remaining_ft
    def choose(_p,c):
        return [next(o['id'] for o in c['options'] if o['id']=='cell:3,8')] if any(o['id'].startswith('cell:') for o in c['options']) else []
    commit(g,'use horizontal momentum',choose)
    assert (g['reload_owner']().position.x,g['reload_owner']().position.y)==(3,8)
    assert g['reload_owner']().movement_remaining_ft==before
    assert sum(c.data['half_feet']/2 for c in momentum(g))==10
    finish(g)
    with pytest.raises(AssertionError):candidate_id(g['menu'](),'use vertical momentum')


def test_horizontal_momentum_works_after_ordinary_movement_is_exhausted(tmp_path):
    g=game_for(tmp_path,[SOURCE])
    commit(g,'ask an ally to assist')
    # Spend all ordinary Speed through the table's native movement intent.
    g['commit'](move_candidate_id(g['menu'](),3,0))
    assert g['reload_owner']().movement_remaining_ft==0
    available=sum(c.data['half_feet']/2 for c in momentum(g))
    assert available>=20
    finish(g)

    def choose(_p,c):
        return [next(o['id'] for o in c['options'] if o['id'].startswith('cell:'))]
    commit(g,'use horizontal momentum',choose)
    owner=g['reload_owner']()
    assert owner.movement_remaining_ft==0
    assert sum(c.data['half_feet']/2 for c in momentum(g)) < available
    finish(g)


def test_vertical_momentum_is_half_grant_and_never_ordinary_movement(tmp_path):
    g=game_for(tmp_path,[SOURCE])
    def vertical(_p,c):
        return ['vertical'] if any(o['id']=='vertical' for o in c['options']) else [c['options'][0]['id']]
    commit(g,'ask an ally to assist',vertical)
    assert sum(c.data['half_feet']/2 for c in momentum(g))==10
    before=g['reload_owner']().movement_remaining_ft
    finish(g)
    def up(_p,c):return [next(o['id'] for o in c['options'] if o['id'].endswith(',1'))]
    commit(g,'use vertical momentum',up)
    # Native falling may return the non-flyer to ground; movement and fall are both real.
    events=g['stored_engine']().events
    assert any(e.event_type=='MOVEMENT_COMMITTED' and e.source_definition_id==SOURCE
               and e.payload['destination'].get('z')==1 for e in events)
    assert g['reload_owner']().movement_remaining_ft==before
    assert sum(c.data['half_feet']/2 for c in momentum(g))==5
    finish(g)


def test_declined_miss_conversion_grants_nothing(tmp_path):
    g=game_for(tmp_path,[SOURCE],hit=False)
    commit(g,'ask an ally to assist',lambda _p,c: [] if any(o['id']=='horizontal' for o in c['options']) else [c['options'][0]['id']])
    assert not momentum(g)
    assert g['reload_owner']().bonus_action_available
    finish(g)


def test_round_end_removes_unused_momentum_without_reusing_it(tmp_path):
    g=game_for(tmp_path,[SOURCE])
    commit(g,'ask an ally to assist')
    g['commit'](g['menu']()['end_turn']);g['to_owner']()
    assert not momentum(g)
    with pytest.raises(AssertionError):candidate_id(g['menu'](),'use horizontal momentum')
    finish(g)


@pytest.mark.parametrize('talents,retained',[( [GRIP],True),([],False)])
def test_sure_grip_keeps_actual_physical_grapple_when_incapacitated(tmp_path,talents,retained):
    def transform(bs):
        seal_actions(bs)
        for b in bs:
            if b['actor_id']!=OWNER:
                b['actor_template']['saving_throws']={'STR':-60,'DEX':-60}
    g=fixture(tmp_path,talents,seed='GRIP-'+tmp_path.name,bundle_transform=transform)
    commit(g,'Grapple')
    assert any(c.condition_id=='condition:typed.grappled' and c.source_actor_id==OWNER
               for c in g['stored_engine']().state.actors[FOE].conditions.values())
    finish(g)
    commit(g,'Become incapacitated')
    assert any(c.condition_id=='condition:typed.grappled' and c.source_actor_id==OWNER
               for c in g['stored_engine']().state.actors[FOE].conditions.values()) is retained
    finish(g)


def test_sure_grip_one_owned_row_keeps_roof_and_grapple_benefits(tmp_path):
    from combat.roof_movement import profile
    def transform(bs):
        seal_actions(bs)
        for b in bs:
            if b['actor_id'] != OWNER:
                b['actor_template']['saving_throws'] = {'STR': -60, 'DEX': -60}
    g = fixture(tmp_path, [GRIP], seed='A2R01G-GRIP', bundle_transform=transform)
    engine = g['stored_engine']()
    assert 'ADVANTAGE' in profile(engine, engine.state.actors[OWNER]).check_modes
    commit(g, 'Grapple')
    commit(g, 'Become incapacitated')
    finish(g)
    engine = g['stored_engine']()
    assert any(c.condition_id == 'condition:typed.grappled' and c.source_actor_id == OWNER
               for c in engine.state.actors[FOE].conditions.values())


@pytest.mark.parametrize('owned,category,ability,expected',[
    (True,'inhalation','con','ADVANTAGE'),(True,'suffocation','dex','ADVANTAGE'),
    (True,'forced_march_exhaustion','con','ADVANTAGE'),(True,'forced_march_exhaustion','dex','NORMAL'),
    (True,'poison','con','NORMAL'),(False,'inhalation','con','NORMAL')])
def test_strong_lungs_scopes_actual_save_rolls(tmp_path,owned,category,ability,expected):
    g=game_for(tmp_path,[LUNGS] if owned else [])
    commit(g,ability+' '+category)
    rolls=[e for e in g['stored_engine']().events if e.event_type=='SAVE_ROLLED' and e.actor_id==OWNER]
    assert rolls[-1].payload['mode']==expected
    finish(g)


@pytest.mark.parametrize('owned,hazard,expected',[(True,'climb','ADVANTAGE'),
    (True,'prevent_falling','ADVANTAGE'),(True,'ordinary','NORMAL'),(False,'climb','NORMAL')])
def test_sure_grip_advantage_is_scoped_to_real_athletics_checks(tmp_path,owned,hazard,expected):
    def transform(bundles):
        seal_actions(bundles)
        b=next(b for b in bundles if b['actor_id']==OWNER)
        add_action(b,'Hazard check',[{'type':'contest_against','actor_check':{'ability':'STR','skill':'Athletics',
            'hazards':[hazard]},'target_check':{'kind':'dc','basis':'save_dc'}}])
        b['action_catalog'][-1]['target_kind']='HOSTILE_ENTITY'
        b['action_catalog'][-1]['range_ft']=5
    g=fixture(tmp_path,[GRIP] if owned else [],seed='ATH-GRIP-CHECK-'+tmp_path.name,bundle_transform=transform)
    commit(g,'Hazard check')
    rolls=[e for e in g['stored_engine']().events if e.event_type=='CHECK_ROLLED' and e.actor_id==OWNER]
    assert rolls[-1].payload['actor']['mode']==expected
    finish(g)


def test_ai_assistance_uses_only_an_ally_with_enemies_simultaneously_in_reach(tmp_path):
    from tests.worker2_support import settle
    from combat.gate4_adapters import ManualControllerAdapter
    g=game_for(tmp_path,[SOURCE])
    combat,table,mid=g['combat'],g['table'],g['match_id']
    cid=candidate_id(g['menu'](),'ask an ally to assist')
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    combat.set_controller_mode(mid,actor_id=FOE,controller_mode='LOCAL_AUTO')
    real=combat.controller
    combat.controller=ManualControllerAdapter(lambda context:(cid,()),
        reaction_chooser=lambda context:real.choose_reaction(context).decision)
    settle(table,mid,cid,auto=True)
    fresh=g['stored_engine']()
    assert any(e.event_type=='ATTACK_ROLLED' and e.actor_id==FOE and e.target_ids==(OWNER,)
               for e in fresh.events)
    assert not any(e.event_type=='ATTACK_ROLLED' and e.actor_id==SECOND for e in fresh.events)
    assert not fresh.state.actors[FOE].reaction_available
    assert fresh.state.actors[SECOND].reaction_available
    assert momentum(g)
    finish(g)


def test_native_ally_can_assist_through_real_oa_profile_and_cold_reload(tmp_path, monkeypatch):
    from combat import typed_reactions
    from combat.gate2_runtime_content import AN
    publications = []
    publish = typed_reactions.publish_reaction_used
    def observe(engine, actor, row):
        if actor.entity_id == AN and row.get('feature_id') == 'system:combat.opportunity_attack':
            import traceback
            caller = traceback.extract_stack(limit=2)[0]
            publications.append((caller.name, dict(row)))
        return publish(engine, actor, row)
    monkeypatch.setattr(typed_reactions, 'publish_reaction_used', observe)

    def prepare(bundles):
        seal_actions(bundles)
        owner=next(b for b in bundles if b['actor_id']==OWNER)
        owner['actor_template']['saving_throws']['CON']=-100
        add_action(owner,'Mark charged helper',[{'type':'mark','mark':'Charged','applies_to':'target',
            'duration':{'kind':'until_removed'}}])
        owner['action_catalog'][-1]['target_kind']='ANY_CREATURE'
        owner['action_catalog'][-1]['range_ft']=60

    g=fixture(tmp_path,[SOURCE],seed='ATH-NATIVE-ALLY',dc=30,talents_by_actor={SECOND:[CM]},
        ask_actors=(SECOND,),bundle_transform=prepare,
        places={OWNER:{'x':3,'y':6},FOE:{'x':4,'y':6},SECOND:{'x':8,'y':8},AN:{'x':2,'y':6}},
        legacy_foes={AN:{'x':2,'y':6}},legacy_allies=(AN,),allies=(FOE,))
    # The Factory owner asks the stock fighter. Its profile is the same native
    # basic melee attack used by movement OAs, not a Factory reaction row.
    menu=g['menu']()
    mark_id=next(o['candidate_id'] for group in menu['actions'] for o in group['options']
                 if o['label']=='Mark charged helper' and AN in o.get('target_ids',()))
    g['commit'](mark_id)
    from combat.typed_executor import mark_condition_id
    assert any(c.condition_id==mark_condition_id('Charged',OWNER)
               for c in g['stored_engine']().state.actors[AN].conditions.values())
    menu=g['menu']()
    cid=next((o['candidate_id'] for group in menu['actions'] for o in group['options']
             if 'ask an ally to assist' in o['label'] and AN in o.get('target_ids',())),None)
    assert cid, [(group.get('label'),[(o.get('label'),o.get('display_name'),o.get('target_ids'))
                                     for o in group['options']]) for group in menu['actions']]
    def choose(_p,c):
        for wanted in ('assist','horizontal'):
            if any(o['id']==wanted for o in c['options']):
                return [next(o['id'] for o in c['options'] if o['id']==wanted)]
        return c.get('preferred') or [c['options'][0]['id']]
    # Keep the spy scoped to the final TabletopService execution attempt;
    # table Ask-me pauses replay the intent from its saved answers.
    answers=[]
    counter_prompts=[]
    for _ in range(30):
        publications.clear()
        result=g['send'](cid,answers)
        if result['status']=='COMMITTED':
            break
        assert result['status']=='REACTION_REQUIRED', result
        prompt=result['reaction']
        if prompt.get('reaction')=='Charged Countermeasure':
            counter_prompts.append(prompt)
        answer={**prompt['context'],'selection':'DECLINE'}
        if prompt.get('reaction')=='Charged Countermeasure':
            answer['selection']='USE'
        choice=prompt.get('choice')
        if choice:
            options=choose(prompt,choice)
            if options:
                answer['selection']='USE'
                answer['option_ids']=options
        answers.append(answer)
    else:
        raise AssertionError('the table never committed native assistance')
    fresh=g['stored_engine']()
    assert any(e.event_type=='ATTACK_ROLLED' and e.actor_id==AN and e.target_ids==(OWNER,)
               for e in fresh.events)
    assert sum(e.event_type=='REACTION_WINDOW_OPENED' and e.source_definition_id=='system:combat.opportunity_attack'
               and e.payload.get('checkpoint','').startswith('NEEDLE:momentum_assist_paid:')
               and e.actor_id==AN and e.target_ids==(OWNER,) for e in fresh.events)==1
    counter_windows=[e for e in fresh.events if e.event_type=='REACTION_WINDOW_OPENED'
                     and e.source_definition_id==CM and e.actor_id==SECOND]
    counter_uses=[e for e in fresh.events if e.event_type=='REACTION_RESOLVED'
                  and e.source_definition_id==CM and e.actor_id==SECOND]
    assert len(counter_windows)==1 and len(counter_uses)==1
    assert len(counter_prompts)==1, counter_prompts
    attacks=[e for e in fresh.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==AN
             and e.target_ids==(OWNER,) and e.source_definition_id=='system:combat.opportunity_attack']
    assert len(attacks)==1 and attacks[0].payload['mode']=='DISADVANTAGE'
    # Every retry of a paused table intent may revisit its owning reaction
    # window. The attack scope itself must never publish that paid Reaction a
    # second time, and the owning publication must carry real attack metadata.
    assert publications
    assert not any(caller=='_attack_scope' for caller, _row in publications)
    assert all(row['effects']==[{'type':'attack','attack_kind':'weapon_melee','count':1}]
               for _caller,row in publications)
    assert not fresh.state.actors[AN].reaction_available
    assert momentum(g)
    finish(g)


def test_factory_ally_assistance_publishes_resolved_oa_for_countermeasure(tmp_path, monkeypatch):
    from combat import typed_reactions
    publications=[]
    publish=typed_reactions.publish_reaction_used
    def observe(engine,actor,row):
        if actor.entity_id==FOE:
            import traceback
            publications.append((traceback.extract_stack(limit=2)[0].name,dict(row)))
        return publish(engine,actor,row)
    monkeypatch.setattr(typed_reactions,'publish_reaction_used',observe)

    def prepare(bundles):
        seal_actions(bundles)
        owner=next(b for b in bundles if b['actor_id']==OWNER)
        owner['actor_template']['saving_throws']['CON']=-100
        add_action(owner,'Mark charged helper',[{'type':'mark','mark':'Charged','applies_to':'target',
            'duration':{'kind':'until_removed'}}])
        owner['action_catalog'][-1]['target_kind']='ANY_CREATURE'
        owner['action_catalog'][-1]['range_ft']=60

    g=fixture(tmp_path,[SOURCE],seed='ATH-FACTORY-ALLY-CM',dc=30,
        talents_by_actor={SECOND:[CM]},ask_actors=(SECOND,),bundle_transform=prepare,
        places={OWNER:{'x':3,'y':6},FOE:{'x':2,'y':6},SECOND:{'x':8,'y':8}},allies=(FOE,))
    menu=g['menu']()
    mark_id=next(o['candidate_id'] for group in menu['actions'] for o in group['options']
                 if o['label']=='Mark charged helper' and FOE in o.get('target_ids',()))
    g['commit'](mark_id)
    from combat.typed_executor import mark_condition_id
    assert any(c.condition_id==mark_condition_id('Charged',OWNER)
               for c in g['stored_engine']().state.actors[FOE].conditions.values())
    menu=g['menu']()
    cid=next(o['candidate_id'] for group in menu['actions'] for o in group['options']
             if 'ask an ally to assist' in o['label'] and FOE in o.get('target_ids',()))
    answers=[]
    counter_prompts=[]
    for _ in range(30):
        publications.clear()
        result=g['send'](cid,answers)
        if result['status']=='COMMITTED':
            break
        assert result['status']=='REACTION_REQUIRED',result
        prompt=result['reaction']
        if prompt.get('reaction')=='Charged Countermeasure':
            counter_prompts.append(prompt)
        answer={**prompt['context'],'selection':'DECLINE'}
        if prompt.get('reaction')=='Charged Countermeasure':
            answer['selection']='USE'
        choice=prompt.get('choice')
        if choice:
            options=[next(o['id'] for o in choice['options'] if o['id']==wanted)
                     for wanted in ('assist','horizontal') if any(o['id']==wanted for o in choice['options'])]
            if options:
                answer['selection']='USE'
                answer['option_ids']=options
        answers.append(answer)
    else:
        raise AssertionError('the table never committed Factory assistance')

    fresh=g['stored_engine']()
    attacks=[e for e in fresh.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==FOE
             and e.target_ids==(OWNER,)]
    assert len(attacks)==1 and attacks[0].payload['mode']=='DISADVANTAGE'
    assert len(counter_prompts)==1
    counter_windows=[e for e in fresh.events if e.event_type=='REACTION_WINDOW_OPENED'
                     and e.source_definition_id==CM and e.actor_id==SECOND]
    counter_uses=[e for e in fresh.events if e.event_type=='REACTION_RESOLVED'
                  and e.source_definition_id==CM and e.actor_id==SECOND]
    assert len(counter_windows)==1 and len(counter_uses)==1
    oa_action=next(a for a in fresh.action_catalog.values() if a.display_name=='Opportunity Attack'
                   and a.owner_id==FOE)
    oa_publications=[(caller,row) for caller,row in publications
                     if row.get('feature_id')==oa_action.source_definition_id]
    # Table Ask-me retries replay and roll back the transaction, so _open may
    # publish once per attempt. Only the committed Reaction window/response
    # is persisted; every attempt must publish the complete profile exactly
    # once from the paid open path, never again from attack execution.
    assert oa_publications and all(caller=='_open' for caller,_row in oa_publications), publications
    assert all(row['effects']==oa_action.parameters['typed']['effects']
               and row['target_ids']==(OWNER,) for _caller,row in oa_publications)
    assert not fresh.state.actors[FOE].reaction_available
    assert momentum(g)
    finish(g)


def test_movement_native_oa_uses_shared_resolver_through_table_and_cold_reload(tmp_path, monkeypatch):
    from combat import typed_reactions
    from combat.gate2_runtime_content import AN
    from tests.test_lock13_native_opportunity import ME, checked, fight, move

    service, table, match_id = fight(tmp_path)
    calls=[]
    resolve=typed_reactions.opportunity_attack
    def observe(engine, reactor, mover, intent, **kwargs):
        if reactor.entity_id==AN:
            calls.append((reactor.entity_id,mover.entity_id))
        return resolve(engine,reactor,mover,intent,**kwargs)
    monkeypatch.setattr(typed_reactions,'opportunity_attack',observe)
    act=table.act
    def reset_each_table_attempt(*args,**kwargs):
        calls.clear()
        return act(*args,**kwargs)
    monkeypatch.setattr(table,'act',reset_each_table_attempt)
    move(service,table,match_id)
    assert calls and all(pair==(AN,ME) for pair in calls)
    engine=checked(service,tmp_path,match_id)
    assert len([e for e in engine.events if e.event_type=='ATTACK_ROLLED'
                and e.actor_id==AN and e.source_definition_id=='system:combat.opportunity_attack'])==1


@pytest.mark.parametrize('fly_speed',[10,60])
def test_horizontal_momentum_uses_its_grant_with_unequal_fly_speed(tmp_path,fly_speed):
    def transform(bs):
        seal_actions(bs)
        owner=next(b for b in bs if b['actor_id']==OWNER)
        owner['actor_template']['fly_speed_ft']=fly_speed
        owner['actor_template']['speed_ft']=30
    g=fixture(tmp_path,[SOURCE],seed='ATH-FLY-GRANT',bundle_transform=transform,
        places={OWNER:{'x':3,'y':2,'z':1},FOE:{'x':2,'y':2,'z':1},SECOND:{'x':17,'y':12}})
    # Twenty feet of momentum must enumerate only routes within the independent
    # grant and commit the farthest.
    menu=g['menu']()
    step=next(m for m in menu['moves'] if m['destination']=={'x':4,'y':2,'z':1})
    def direction(_p,c):
        return ['horizontal'] if any(o['id']=='horizontal' for o in c['options']) else (c.get('preferred') or [c['options'][0]['id']])
    g['commit'](step['candidate_id'],direction)
    assert momentum(g)
    from combat.ext.athletics_momentum import routes as momentum_routes
    engine=g['stored_engine']()
    offered=momentum_routes(engine,engine.state.actors[OWNER],'horizontal',20)
    assert offered and max(c.movement_cost_ft for c in offered)<=20
    import re
    def farthest(_p,c):
        routes=[o for o in c['options'] if o['id'].startswith('cell:')]
        if not routes:
            return c.get('preferred') or [c['options'][0]['id']]
        def cost(option):
            match=re.search(r'\((\d+(?:\.\d+)?) feet of movement\)',option.get('label',''))
            return float(match.group(1)) if match else 0
        costs=[cost(o) for o in routes]
        assert costs and max(costs)>0
        assert max(costs)<=20, costs
        return [routes[costs.index(max(costs))]['id']]
    commit(g,'use horizontal momentum',farthest)
    moved=[e for e in g['stored_engine']().events if e.event_type=='MOVEMENT_COMMITTED'
           and e.source_definition_id==SOURCE]
    assert moved and moved[-1].payload['planned_cost_ft']<=20
    finish(g)


def test_horizontal_flight_momentum_survives_previously_spent_flight_overrun(tmp_path):
    def transform(bs):
        seal_actions(bs)
        owner=next(b for b in bs if b['actor_id']==OWNER)
        owner['actor_template']['fly_speed_ft']=60
        owner['actor_template']['speed_ft']=30
        owner['actor_template']['armor_class']=1
    g=fixture(tmp_path,[SOURCE],seed='ATH-FLY-OVERRUN',bundle_transform=transform,
        places={OWNER:{'x':14,'y':2,'z':1},FOE:{'x':15,'y':2,'z':1},SECOND:{'x':17,'y':12}})
    menu=g['menu']()
    route=next(m for m in menu['moves'] if m['destination']=={'x':5,'y':2,'z':1})
    import re
    def answers(_p,c):
        return ['horizontal'] if any(o['id']=='horizontal' for o in c['options']) else (c.get('preferred') or [c['options'][0]['id']])
    g['commit'](route['candidate_id'],answers)
    fresh=g['stored_engine']()
    assert fresh.state.actors[OWNER].turn_flags.get('flight_movement_overrun_ft',0)>=15
    assert momentum(g)
    from combat.ext.athletics_momentum import routes as momentum_routes
    offered=momentum_routes(fresh,fresh.state.actors[OWNER],'horizontal',20)
    assert offered and max(c.movement_cost_ft for c in offered)<=20
    def farthest(_p,c):
        routes=[o for o in c['options'] if o['id'].startswith('cell:')]
        if not routes:
            return c.get('preferred') or [c['options'][0]['id']]
        def cost(option):
            match=re.search(r'\((\d+(?:\.\d+)?) feet of movement\)',option.get('label',''))
            return float(match.group(1)) if match else 0
        costs=[cost(o) for o in routes]
        assert costs and max(costs)>0
        assert max(costs)<=20, costs
        return [routes[costs.index(max(costs))]['id']]
    commit(g,'use horizontal momentum',farthest)
    spent=[e for e in g['stored_engine']().events if e.event_type=='MOVEMENT_COMMITTED'
           and e.source_definition_id==SOURCE]
    assert spent and spent[-1].payload['planned_cost_ft']<=20
    finish(g)


@pytest.mark.parametrize('strength,expected',[(10,5),(4,5),(20,25)])
def test_boost_uses_actual_source_strength_and_printed_floor(tmp_path,strength,expected):
    def transform(bs):
        seal_actions(bs)
        for b in bs:
            if b['actor_id']==FOE:b['actor_template']['strength_score']=strength
    g=fixture(tmp_path,[SOURCE],seed='MOMENTUM-FLOOR-'+tmp_path.name,bundle_transform=transform,allies=(FOE,))
    commit(g,'ask an ally to assist')
    assert sum(c.data['half_feet']/2 for c in momentum(g))==expected
    finish(g)


def test_smaller_creature_cannot_supply_boost_and_assistance_can_be_declined(tmp_path):
    def transform(bs):
        seal_actions(bs)
        for b in bs:
            if b['actor_id']==FOE:b['actor_template']['size_category']='Small'
    g=fixture(tmp_path,[SOURCE],seed='MOMENTUM-SMALL',bundle_transform=transform,allies=(FOE,))
    with pytest.raises(AssertionError):candidate_id(g['menu'](),'ask an ally to assist')
    finish(g)
    h=game_for(tmp_path/'decline',[SOURCE])
    commit(h,'ask an ally to assist',lambda _p,c: [])
    assert not momentum(h)
    assert h['stored_engine']().state.actors[FOE].reaction_available
    finish(h)


def test_enemy_opportunity_attack_gives_momentum_during_native_movement(tmp_path):
    g=game_for(tmp_path,[SOURCE],ally=False)
    menu=g['menu']()
    path=[{'x':3,'y':6},{'x':3,'y':7},{'x':3,'y':8}]
    table,mid=g['table'],g['match_id']
    quote=table.preview_move_path(mid,menu['decision_id'],menu['state_version'],OWNER,path)
    answers=[]
    for _ in range(30):
        response=table.commit_move_path(mid,quote['candidate']['candidate_id'],menu['decision_id'],
            menu['state_version'],OWNER,path,reactions=answers)
        if response['status']=='COMMITTED':break
        assert response['status']=='REACTION_REQUIRED'
        prompt=response['reaction'];choice=prompt.get('choice')
        answer={**prompt['context'],'selection':'USE'}
        if choice:answer['option_ids']=list(choice.get('preferred') or [choice['options'][0]['id']])
        answers.append(answer)
    else:raise AssertionError('movement did not finish')
    assert momentum(g)
    assert any(e.event_type=='ATTACK_ROLLED' and e.actor_id in (FOE,SECOND) for e in g['stored_engine']().events)
    finish(g)



def test_missed_attack_cannot_convert_after_bonus_action_is_spent(tmp_path):
    def transform(bs):
        seal_actions(bs)
        owner=next(b for b in bs if b['actor_id']==OWNER)
        owner['actor_template']['armor_class']=80
        add_action(owner,'Spend Bonus Action',[{'type':'temp_hp','amount':1,'applies_to':'self'}])
        owner['action_catalog'][-1]['economy']='BONUS_ACTION'
    g=fixture(tmp_path,[SOURCE],seed='MOMENTUM-NO-BONUS',bundle_transform=transform,allies=(FOE,))
    commit(g,'Spend Bonus Action')
    assert not g['reload_owner']().bonus_action_available
    commit(g,'ask an ally to assist')
    assert not momentum(g)
    finish(g)


@pytest.mark.parametrize('owned,expected',[(True,'ADVANTAGE'),(False,'NORMAL')])
def test_strong_lungs_resists_actual_black_lung_cloud_through_table(tmp_path,owned,expected):
    from tests import worker2_support as W
    from tests.h1_support import sheet
    veil='SMOKE_BASE_SMOKE_VEIL'
    cloud='TAL_SMOKE_BLACK_LUNG_CLOUD'
    combat,table,mid=W.fixture(tmp_path,[veil,cloud],
        foe_sheet=sheet([LUNGS] if owned else [],cl=15,primary='Stamina'),seed='ATH-LUNGS-SMOKE',
        positions={W.OWNER:{'x':3,'y':6},W.ALLY:{'x':4,'y':6},W.FOE:{'x':5,'y':6}})
    W.settle(table,mid,W.candidate(combat,mid,'Smoke Veil + Black-Lung Cloud',at=(5,6)).candidate_id)
    W.turn(table,mid,W.FOE)
    engine=W.reload(tmp_path,mid)
    saves=[r for r in engine.rolls if r.actor_id==W.FOE and r.reason.startswith('SAVE:')]
    assert saves and saves[-1].mode==expected
    assert not any('failed:' in str(e.payload) for e in engine.events if e.event_type=='GM_RIDER')


@pytest.mark.parametrize('condition',['frightened','stunned','unconscious'])
def test_sure_grip_held_weapon_is_not_dropped_by_named_condition(tmp_path,condition):
    from combat.ext.hand_occupancy import occupancy
    g=fixture(tmp_path,[GRIP],seed='ATH-GRIP-ITEM-'+condition,kit=AXE_KIT,bundle_transform=seal_actions)
    before=g['stored_engine']();items=occupancy(before,before.state.actors[OWNER])
    assert items
    commit(g,'Become '+condition)
    after=g['stored_engine']()
    assert occupancy(after,after.state.actors[OWNER])==items
    finish(g)


@pytest.mark.parametrize('strength,each',[(12,2.5),(16,7.5)])
def test_fractional_vertical_grants_combine_exactly_across_cold_reload(tmp_path,strength,each):
    from combat.gate2_runtime_content import AN
    def transform(bs):
        seal_actions(bs)
        for b in bs:
            if b['actor_id']!=OWNER:b['actor_template']['strength_score']=strength
    g=fixture(tmp_path,[SOURCE],seed='ATH-HALF-POOLS',bundle_transform=transform,allies=(FOE,SECOND),
        places={OWNER:{'x':3,'y':6},FOE:{'x':4,'y':6},SECOND:{'x':2,'y':6}},
        legacy_foes={AN:{'x':7,'y':6}})
    def vertical(_p,c):
        return ['vertical'] if any(o['id']=='vertical' for o in c['options']) else [c['options'][0]['id']]
    commit(g,'ask an ally to assist',vertical)
    assert sum(c.data['half_feet']/2 for c in momentum(g))==each
    finish(g)
    commit(g,'ask an ally to assist',vertical)
    assert sum(c.data['half_feet']/2 for c in momentum(g))==each*2
    finish(g)
    before=g['reload_owner']().movement_remaining_ft
    commit(g,'use vertical momentum',lambda _p,c:[next(o['id'] for o in c['options'] if o['id'].endswith(',1'))])
    assert sum(c.data['half_feet']/2 for c in momentum(g))==each*2-5
    assert g['reload_owner']().movement_remaining_ft==before
    assert any(e.event_type=='MOVEMENT_COMMITTED' and e.source_definition_id==SOURCE
               and e.payload['destination'].get('z')==1 for e in g['stored_engine']().events)
    finish(g)
