"""Tradition gaps through service intents, table commits, reload and mechanical replay."""
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
from combat.factory_compiler import compile_character
from combat.canonical import canonical_sha256
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_riders_c8 import sheet
from tests.hunt12_support import candidate, send

ME='actor:factory.fix12';FOE='actor:factory.fix12-foe';ALLY='actor:factory.tradition-ally'
CH='tianxia.tradition.spirit.choir_of_the_unopened_eye.feature.'
DE='tianxia.tradition.spirit.dream_eater.feature.'
BW='tianxia.tradition.spirit.boundary_walker.feature.'
CB='tianxia.tradition.spirit.compass_breaking_hand.feature.'
CM='tianxia.tradition.spirit.candlemaker.feature.'


def probe(bundle, suffix, effects, *, target='HOSTILE_ENTITY'):
    source='test:traditions.'+suffix+'.'+bundle['actor_id']
    action={'source_definition_id':source,'display_name':'Test: '+suffix,'owner_id':bundle['actor_id'],
            'economy':'NONE','resolution_kind':'TYPED','target_kind':target,'range_ft':60,
            'parameters':{'typed':{'effects':effects,'numbers':{'save_dc':1},'duration':{'kind':'instant'},'riders':[]},'expected_damage':0}}
    for effect in effects:
        if suffix.lower() == 'sleep' and effect.get('type') == 'condition' and effect.get('condition') == 'unconscious':
            effect.setdefault('data', {})['label'] = 'Test sleep'
    bundle['action_catalog'].append(action);bundle['actor_template']['action_ids'].append(source)


def scene(tmp_path, mids, *, dc=100, ally_ids=(), foe_ids=(), owner_auto=False, friendly_ally=False, spirit_probe=False, enemy_hit=False, relocation_probe=False, weapon_probe=False, weapon_range=60, only_probe_strike=False, enemy_strike_probe=False, paid_technique=False, proficient=False, no_improvised_throw=False, stamina_probe=False, foe_xy=(4,6)):
    docs=[sheet(mids,dc=dc),sheet(foe_ids,dc=1),sheet(ally_ids,dc=1)]
    for doc in docs:doc['ability_scores_and_statistics']['hit_points']['maximum']=1000
    bundles=[compile_character(doc,actor_id=who,reaction_plan={'ask':True}) for doc,who in zip(docs,[ME,FOE,ALLY])]
    if no_improvised_throw:
        bundles[0]['actor_template']['action_ids']=[aid for aid in bundles[0]['actor_template']['action_ids']
                                                   if not aid.endswith('.improvised.thrown')]
    if stamina_probe:
        bundles[0]['actor_template']['resources'].append({'resource_id':'resource:core.stamina','initial':30,'maximum':30})
    if paid_technique:
        aid='test:paid.weapon_technique'
        bundles[0]['action_catalog'].append({'source_definition_id':aid,'display_name':'Paid Axe Technique',
            'owner_id':ME,'economy':'ACTION','resolution_kind':'TYPED','target_kind':'HOSTILE_ENTITY','range_ft':30,
            'costs':[('resource:core.cultivation_points',3)],
            'parameters':{'expected_damage':999,'typed':{'forged_from':'compiled:forged-strike','base_form':'Strike',
                'weapon':{'name':'Test axe','damage':{'count':1,'sides':8,'modifier':0},'damage_type':'SLASHING'},
                'effects':[{'type':'attack','attack_kind':'weapon','count':1,'on_hit':[{'type':'extra_damage','dice':{'count':6,'sides':8},'damage_types':['force']}],'on_miss':[]}],
                'numbers':{'attack_bonus':100},'riders':[]}}})
        bundles[0]['actor_template']['action_ids'].append(aid)
    # Explicit test setup actions, sealed in the bundles, run and replay like any intent.
    probe(bundles[0],'sleep',[{'type':'condition','condition':'unconscious','applies_to':'target','duration':{'kind':'until_removed'}}])
    probe(bundles[0],'paralyze',[{'type':'condition','condition':'unconscious','applies_to':'target','duration':{'kind':'until_removed'}}])
    probe(bundles[0],'mark',[{'type':'mark','mark':'Resonance','applies_to':'target','duration':{'kind':'until_removed'}}])
    probe(bundles[0],'note',[{'type':'mark','mark':'Witness Note','applies_to':'target','duration':{'kind':'until_removed'}}])
    probe(bundles[1],'finish',[{'type':'damage','flat':1,'damage_types':['force'],'applies_to':'target'}])
    if enemy_strike_probe:
        probe(bundles[1],'enemy attack',[{'type':'attack','attack_kind':'unarmed','count':1,'on_hit':[],'on_miss':[]}])
        bundles[1]['action_catalog'][-1]['parameters']['typed']['numbers']['attack_bonus']=100
    probe(bundles[1],'death save',[{'type':'death_save_now','applies_to':'target'}])
    probe(bundles[1],'hurt',[{'type':'damage','flat':1001,'damage_types':['force'],'applies_to':'target'}])
    probe(bundles[2],'end lantern',[{'type':'tradition_test_end_lantern'}],target='SELF')
    probe(bundles[2],'wake damage',[{'type':'damage','flat':1,'damage_types':['force'],'applies_to':'target'}],target='ANY_CREATURE')
    probe(bundles[0],'gain orbit',[{'type':'gain_resource','resource_id':'resource:named.bearing_orbit','flat':1,'applies_to':'self'}],target='SELF')
    probe(bundles[0],'gain approach',[{'type':'gain_resource','resource_id':'resource:named.bearing_approach','flat':1,'applies_to':'self'}],target='SELF')
    probe(bundles[0],'gain depart',[{'type':'gain_resource','resource_id':'resource:named.bearing_depart','flat':1,'applies_to':'self'}],target='SELF')
    if relocation_probe:
        probe(bundles[0],'push',[{'type':'forced_movement','direction':'away','distance_ft':5,'applies_to':'target'}])
        probe(bundles[1],'teleport',[{'type':'teleport','distance_ft':5,'applies_to':'self','picks_destination':True}],target='SELF')
    if weapon_probe:
        probe(bundles[0],'weapon strike',[{'type':'attack','attack_kind':'weapon','count':1,
             'on_hit':[{'type':'damage','weapon_damage':True,'applies_to':'target'}],'on_miss':[]}])
        bundles[0]['action_catalog'][-1]['range_ft']=weapon_range
        bundles[0]['action_catalog'][-1]['parameters']['typed'].update(
             proficient=proficient,attack_bonus=100,weapon={'name':'Test blade','damage':{'count':1,'sides':4,'modifier':0},'damage_type':'SLASHING'})
        bundles[0]['action_catalog'][-1]['economy']='ACTION'
        bundles[0]['action_catalog'][-1]['parameters']['expected_damage']=4
        if only_probe_strike:
            probe_id=bundles[0]['action_catalog'][-1]['source_definition_id']
            attack_ids={a['source_definition_id'] for a in bundles[0]['action_catalog']
                        if a['source_definition_id']!=probe_id and any(e.get('type')=='attack'
                           for e in ((a.get('parameters') or {}).get('typed') or {}).get('effects') or [])}
            bundles[0]['actor_template']['action_ids']=[aid for aid in bundles[0]['actor_template']['action_ids'] if aid not in attack_ids]
    if spirit_probe:
        probe(bundles[0],'mixed spirit injury',[{'type':'damage','flat':1,'damage_types':['force'],'applies_to':'allies_in_area'},
             *([{'type':'damage','flat':1,'damage_types':['force'],'applies_to':'enemies_in_area'}] if enemy_hit else [])])
        a=bundles[0]['action_catalog'][-1]
        a['parameters']['typed'].update(source='tianxia.path.spirit_awakening.feature.test_injury',area={'shape':'radius','size_ft':30})
    for b in bundles:
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat=CombatService(ROOT,tmp_path);table=TabletopService(combat,tmp_path)
    mid=combat._finish_factory_match(bundles,[ME,FOE,ALLY],{ME:'team:factory',FOE:'team:opponents',ALLY:'team:factory' if friendly_ally else 'team:opponents'},
        {ME:{'x':3,'y':6},FOE:{'x':foe_xy[0],'y':foe_xy[1]},ALLY:{'x':4,'y':5}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],[ME],[FOE,ALLY],
        control_modes={ME:'LOCAL_AUTO' if owner_auto else 'MANUAL',FOE:'MANUAL',ALLY:'MANUAL'},
        match_seed='A2GTRA1',display_name='Tradition regression',maximum_rounds=20)['match_id']
    advance(combat,table,mid,ME)
    return combat,table,mid


def commit(combat,table,mid,chosen, picks=(), *, decline=False):
    answers=[];prompts=[]
    for _ in range(30):
        result=send(combat,table,mid,chosen,answers,auto=combat.decision(mid)['control_mode']=='LOCAL_AUTO')
        if result['status']=='COMMITTED':return {**result,'_prompts':prompts}
        assert result['status']=='REACTION_REQUIRED',result
        p=result['reaction'];prompts.append(p); answer={**p['context'],'selection':'DECLINE'}
        if p.get('choice'):
            ids=[o['id'] for o in p['choice']['options']]
            match=next((x for x in picks if (all(v in ids for v in x) if isinstance(x,tuple) else x in ids)),None)
            if match is not None:answer.update(selection='USE',option_ids=list(match) if isinstance(match,tuple) else [match])
            elif not p['choice'].get('allow_decline'):
                answer.update(selection='USE',option_ids=ids[:p['choice'].get('minimum_selections',1)])
        elif not decline:answer['selection']='USE'
        answers.append(answer)
    raise AssertionError('unresolved choices')


def use(combat,table,mid,name,target=None,picks=(),decline=False):
    c=candidate(combat,mid,lambda c:c.display_name==name and (target is None or target in c.target_ids))
    return commit(combat,table,mid,c,picks,decline=decline)


def end(combat,table,mid):
    commit(combat,table,mid,candidate(combat,mid,lambda c:c.kind.value=='END_TURN'))


def advance(combat,table,mid,who):
    for _ in range(6):
        if combat._load_session(mid).engine.state.current_actor_id==who:return
        end(combat,table,mid)
    raise AssertionError(who)


def cold(tmp_path,mid):
    session=CombatService(ROOT,tmp_path)._load_session(mid)
    assert session.verify()['status']=='PASS'
    assert session.mechanical.replay()['status']=='PASS'
    return session.engine


def held(actor,name):return [c for c in actor.conditions.values() if c.condition_id=='condition:typed.'+name]


@pytest.mark.parametrize('option',['Reduce Speed','Prevent Reactions'])
def test_hymn_success_keeps_chosen_penalty_and_expires(tmp_path,option):
    c,t,m=scene(tmp_path,[CH+'hymn_of_stillness'],dc=-100)
    use(c,t,m,'Hymn of Stillness: '+option,FOE)
    e=cold(tmp_path,m);foe=e.state.actors[FOE]
    assert e._effective_speed(foe)==(20 if option=='Reduce Speed' else 30)
    assert bool(held(foe,'reaction_denied'))==(option=='Prevent Reactions')
    assert foe.current_hp<1000
    end(c,t,m);advance(c,t,m,ME)
    e=cold(tmp_path,m);assert e._effective_speed(e.state.actors[FOE])==30
    assert not held(e.state.actors[FOE],'reaction_denied')


def test_hymn_marked_failure_has_one_extra_pressure(tmp_path):
    c,t,m=scene(tmp_path,[CH+'hymn_of_stillness'])
    use(c,t,m,'Test: mark',FOE)
    use(c,t,m,'Hymn of Stillness: Reduce Speed',FOE)
    e=cold(tmp_path,m)
    assert len([x for x in e.events if x.event_type=='CONDITION_APPLIED' and
                str(x.payload.get('condition_id','')).startswith('condition:typed.spirit_awakening_pressure.')])==1


@pytest.mark.parametrize('keep',[False,True])
def test_nightmare_touch_wakes_or_spends_morsel_to_preserve_sleep(tmp_path,keep):
    c,t,m=scene(tmp_path,[DE+'dream_walker',DE+'nightmare_touch'])
    use(c,t,m,'Test: sleep',FOE)
    use(c,t,m,'Nightmare Touch',FOE,picks=['keep'] if keep else [])
    e=cold(tmp_path,m);foe=e.state.actors[FOE]
    assert bool(held(foe,'unconscious'))==keep
    assert e.state.actors[ME].resources['resource:named.dream_morsel']==(0 if keep else 1)
    if keep:
        end(c,t,m);advance(c,t,m,ALLY)
        use(c,t,m,'Test: wake damage',FOE)
        e=cold(tmp_path,m)
        assert not held(e.state.actors[FOE],'unconscious')
        assert not held(e.state.actors[FOE],'nightmare_sleep')


def test_successful_nightmare_touch_save_preserves_cursed_and_unrelated_sleep(tmp_path,monkeypatch):
    from combat.gate2_rolls import DeterministicRollAuthority
    original=DeterministicRollAuthority.raw_d20
    def success_then_failed_repeat(self,**kw):
        roll=original(self,**kw)
        reason=str(kw.get('reason') or '').lower()
        if 'nightmare_touch' in reason:
            natural,total=20,roll.modifier+1000
        elif 'sleeping_curse' in reason:
            natural,total=1,roll.modifier-1000
        else:
            return roll
        return roll.model_copy(update={'dice':(natural,), 'discarded':(), 'natural_result':natural,
                                       'total':total})
    monkeypatch.setattr(DeterministicRollAuthority,'raw_d20',success_then_failed_repeat)
    c,t,m=scene(tmp_path,[DE+'dream_walker',DE+'nightmare_touch',DE+'sleeping_curse'],dc=1)
    use(c,t,m,'Test: mark',FOE)
    use(c,t,m,'Test: sleep',FOE)
    use(c,t,m,'Sleeping Curse',FOE)
    end(c,t,m);advance(c,t,m,ME)
    use(c,t,m,'Nightmare Touch',FOE)
    e=cold(tmp_path,m);foe=e.state.actors[FOE]
    saves=[x for x in e.events if x.event_type=='SAVE_ROLLED' and x.actor_id==FOE]
    touch=[x for x in saves if 'nightmare_touch' in (x.payload or {}).get('reason','')]
    assert len(touch)==1 and touch[0].payload['success']
    repeats=[x for x in saves if x.sequence>touch[0].sequence and 'sleeping_curse' in (x.payload or {}).get('reason','')]
    assert repeats and not repeats[-1].payload['success']
    assert held(foe,'cursed_sleep')
    assert held(foe,'unconscious')


def test_failed_nightmare_touch_only_ends_a_sleep_owned_unconscious_state(tmp_path,monkeypatch):
    force_natural(monkeypatch,1)
    c,t,m=scene(tmp_path,[DE+'dream_walker',DE+'nightmare_touch'],dc=100)
    use(c,t,m,'Test: sleep',FOE)
    use(c,t,m,'Test: paralyze',FOE)
    use(c,t,m,'Nightmare Touch',FOE)
    e=cold(tmp_path,m);conditions=e.state.actors[FOE].conditions.values()
    unconscious=[c for c in conditions if c.condition_id=='condition:typed.unconscious']
    assert len(unconscious)==1 and 'paralyze' in unconscious[0].source_definition_id


@pytest.mark.parametrize('decline',[False,True])
def test_nightmare_touch_does_not_offer_keep_sleep_for_unrelated_unconsciousness(tmp_path,monkeypatch,decline):
    force_natural(monkeypatch,1)
    c,t,m=scene(tmp_path,[DE+'dream_walker',DE+'nightmare_touch'],dc=100)
    use(c,t,m,'Test: paralyze',FOE)
    result=use(c,t,m,'Nightmare Touch',FOE,decline=decline)
    e=cold(tmp_path,m);foe=e.state.actors[FOE]
    assert not [p for p in result['_prompts'] if p.get('reaction')=='Nightmare Touch' and p.get('choice')]
    assert len(held(foe,'unconscious'))==1 and 'paralyze' in held(foe,'unconscious')[0].source_definition_id
    assert not held(foe,'nightmare_sleep')
    assert not any(x.event_type=='PASSIVE_TRIGGERED' and 'wakes after Nightmare Touch' in str((x.payload or {}).get('log','')) for x in e.events)


def test_sleeping_curse_allied_bond_intervention_uses_action_and_repeat_save(tmp_path):
    c,t,m=scene(tmp_path,[DE+'sleeping_curse'])
    use(c,t,m,'Test: mark',FOE)
    use(c,t,m,'Sleeping Curse',FOE)
    assert held(cold(tmp_path,m).state.actors[FOE],'cursed_sleep')
    end(c,t,m);advance(c,t,m,ALLY)
    before=len(cold(tmp_path,m).events)
    use(c,t,m,'Wake Cursed Sleeper: invoke their name or bond',FOE)
    e=cold(tmp_path,m)
    assert not e.state.actors[ALLY].action_available
    assert len([x for x in e.events[before:] if x.event_type=='SAVE_ROLLED' and x.actor_id==FOE])==1


def test_walk_the_border_crosses_hostile_creature_after_reload(tmp_path):
    c,t,m=scene(tmp_path,[BW+'walk_the_border'])
    use(c,t,m,'Walk the Border')
    e=cold(tmp_path,m)
    chosen=candidate(c,m,lambda c:c.kind.value=='MOVE' and c.destination and c.destination.x==5 and c.destination.y==6)
    # Require a route through the foe's square, not a path around it.
    from combat.gate2_runtime_models import ActionIntent,Position
    session=c._load_session(m)
    intent=ActionIntent(intent_id='border-crossing',decision_id=chosen.decision_id,
        candidate_id=chosen.candidate_id,state_version=chosen.state_version,actor_id=ME,destination=chosen.destination,
        movement_path=(Position(x=3,y=6),Position(x=4,y=6),Position(x=5,y=6)))
    bound=session.engine.candidates_for_intent(intent)
    assert bound
    intent=intent.model_copy(update={'candidate_id':bound[0].candidate_id})
    session.mechanical.execute_intent(intent)
    e=cold(tmp_path,m);assert e.state.actors[ME].position.x==5


def force_natural(monkeypatch, natural, *, death_only=False):
    from combat.gate2_rolls import DeterministicRollAuthority
    original=DeterministicRollAuthority.raw_d20
    def draw(self,**kw):
        roll=original(self,**kw)
        if death_only and kw['reason']!='SAVE:death':return roll
        return roll.model_copy(update={'dice':(natural,), 'discarded':(), 'natural_result':natural,
                                       'total':natural+roll.modifier})
    monkeypatch.setattr(DeterministicRollAuthority,'raw_d20',draw)


def test_ancestral_warrior_authority_adds_damage_to_a_normal_strike(tmp_path,monkeypatch):
    force_natural(monkeypatch,19)
    ac='tianxia.tradition.spirit.ancestral_channeler.feature.'
    c,t,m=scene(tmp_path,[ac+'council_of_the_remembered',ac+'ancestral_ascension'])
    use(c,t,m,'Ancestral Ascension: Warrior as Ascendant Office')
    use(c,t,m,'Ascendant Authority: Thousand Battles in One Body (Warrior)',FOE)
    e=cold(tmp_path,m)
    rolls=[x for x in e.events if x.event_type=='DAMAGE_ROLLED']
    assert len(rolls)==2
    assert any('8d8' in x.payload.get('expression','') for x in rolls)
    assert any('8d8' not in x.payload.get('expression','') for x in rolls)
    assert held(e.state.actors[FOE],'reaction_denied')
    assert any(x.target_field=='healing_reduction' for x in e.state.actors[FOE].modifiers.values())
    assert not [x for x in e.legal_candidates() if 'Thousand Battles in One Body' in x.display_name]


def test_bearing_without_name_changes_the_rider_and_spends_original_token(tmp_path):
    c,t,m=scene(tmp_path,[CB+'three_bearing_footwork',CB+'turn_the_compass',CB+'no_fixed_compass'])
    use(c,t,m,'Choose Pole',FOE)
    use(c,t,m,'Test: gain approach')
    end(c,t,m);advance(c,t,m,FOE)
    attack=candidate(c,m,lambda x:x.display_name.startswith('Unarmed Strike') and ME in x.target_ids)
    commit(c,t,m,attack,['approach','approach:orbit'])
    e=cold(tmp_path,m);actor=e.state.actors[ME]
    assert actor.resources['resource:named.bearing_approach']==0
    assert actor.turn_flags['bearing_without_name'] == f"{e.state.round_number}:{e.state.current_slot_index}:{e.state.current_actor_id}"
    assert any(x.event_type=='ATTACK_ROLLED' and x.payload.get('mode')=='DISADVANTAGE' for x in e.events)
    assert any('Turn the Compass (Orbit)'==x.payload.get('reaction_name') for x in e.events)


def test_bearing_without_name_resets_at_actual_enemy_turn_and_explains_both_choices(tmp_path):
    c,t,m=scene(tmp_path,[CB+'three_bearing_footwork',CB+'break_the_four_directions',CB+'turn_the_compass',CB+'no_fixed_compass'],foe_xy=(7,6),enemy_strike_probe=True)
    use(c,t,m,'Choose Pole',FOE)
    use(c,t,m,'Test: gain approach')
    use(c,t,m,'Test: gain orbit')
    use(c,t,m,'Test: gain depart')
    broke=use(c,t,m,'Break the Four Directions',FOE,
              picks=[('approach','orbit'),'cell:5,6','cell:7,5','approach:orbit'])
    first=cold(tmp_path,m);first_key=first.state.actors[ME].turn_flags['bearing_without_name']
    if isinstance(first_key,str):
        assert first_key.endswith(':'+ME)
        from combat.ext.compass_breaking_hand import bearing_without_name
        assert bearing_without_name(first,first.state.actors[ME],['approach'],None,context='break_four',
                                    target_name=first.state.actors[FOE].display_name,target_id=FOE)==['approach']
        assert first.state.actors[ME].turn_flags['bearing_without_name']==first_key
    else:
        assert first_key is True  # Retained pre-fix behavior; the next creature turn must expose the lost use.
    bearing=[o for p in broke['_prompts'] if p.get('choice') and p.get('reaction')=='Bearing Without Name' for o in p['choice']['options']]
    assert bearing
    end(c,t,m);advance(c,t,m,FOE)
    attack=candidate(c,m,lambda x:x.display_name=='Test: enemy attack' and ME in x.target_ids)
    reacted=commit(c,t,m,attack,['depart','depart:approach'])
    e=cold(tmp_path,m);next_key=e.state.actors[ME].turn_flags['bearing_without_name']
    reaction_choices=[o for p in reacted['_prompts'] if p.get('choice') and p.get('reaction')=='Bearing Without Name' for o in p['choice']['options']]
    assert reaction_choices and any(e.state.actors[ME].display_name in o['label'] and 'attack' in o['label'].lower() for o in reaction_choices)
    assert next_key != first_key and next_key.endswith(':'+FOE)


def test_warrior_never_offers_or_executes_a_paid_weapon_technique(tmp_path,monkeypatch):
    force_natural(monkeypatch,19)
    ac='tianxia.tradition.spirit.ancestral_channeler.feature.'
    c,t,m=scene(tmp_path,[ac+'council_of_the_remembered',ac+'ancestral_ascension'],paid_technique=True)
    use(c,t,m,'Ancestral Ascension: Warrior as Ascendant Office')
    action=candidate(c,m,lambda x:x.display_name=='Ascendant Authority: Thousand Battles in One Body (Warrior)' and FOE in x.target_ids)
    result=commit(c,t,m,action,[action.source_definition_id+'.cultivation'])
    choices=[o['id'] for p in result['_prompts'] if p.get('choice') and p.get('reaction')=='Thousand Battles in One Body'
             for o in p['choice']['options']]
    e=cold(tmp_path,m)
    rolls=[x for x in e.events if x.event_type=='DAMAGE_ROLLED']
    assert choices and all('test:paid.weapon_technique' not in x for x in choices)
    assert len(rolls)==1 and '8d8' in rolls[0].payload.get('expression','')


def test_warrior_uses_a_legal_ranged_strike_beyond_five_feet(tmp_path,monkeypatch):
    force_natural(monkeypatch,19)
    ac='tianxia.tradition.spirit.ancestral_channeler.feature.'
    c,t,m=scene(tmp_path,[ac+'council_of_the_remembered',ac+'ancestral_ascension'],foe_xy=(7,6))
    # The compiler's ordinary improvised throw is a real 20/60-foot weapon
    # action (typed range plus action range), not a synthetic melee-shaped row.
    use(c,t,m,'Grab an improvised weapon')
    use(c,t,m,'Ancestral Ascension: Warrior as Ascendant Office')
    action=candidate(c,m,lambda x:x.display_name=='Ascendant Authority: Thousand Battles in One Body (Warrior)' and FOE in x.target_ids)
    thrown=next(a.source_definition_id for a in c._load_session(m).engine.action_catalog.values()
                if a.display_name=='Improvised weapon thrown')
    result=commit(c,t,m,action,[thrown])
    e=cold(tmp_path,m)
    rolls=[x for x in e.events if x.event_type=='DAMAGE_ROLLED']
    assert len(rolls)==2
    assert any('8d8' in x.payload.get('expression','') for x in rolls)
    assert any('8d8' not in x.payload.get('expression','') for x in rolls)
    # The compiled throw's own cleanup runs: the object leaves the hand, so a further throw needs a new grab.
    assert not held(e.state.actors[ME],'improvised')


def test_warrior_cannot_strike_with_an_improvised_weapon_it_never_grabbed(tmp_path,monkeypatch):
    force_natural(monkeypatch,19)
    ac='tianxia.tradition.spirit.ancestral_channeler.feature.'
    c,t,m=scene(tmp_path,[ac+'council_of_the_remembered',ac+'ancestral_ascension'],foe_xy=(7,6))
    use(c,t,m,'Ancestral Ascension: Warrior as Ascendant Office')
    e=cold(tmp_path,m)
    assert not held(e.state.actors[ME],'improvised')
    assert not [x for x in e.legal_candidates() if x.display_name=='Ascendant Authority: Thousand Battles in One Body (Warrior)' and FOE in x.target_ids]


def test_warrior_does_not_execute_a_strike_beyond_its_range(tmp_path,monkeypatch):
    force_natural(monkeypatch,19)
    ac='tianxia.tradition.spirit.ancestral_channeler.feature.'
    c,t,m=scene(tmp_path,[ac+'council_of_the_remembered',ac+'ancestral_ascension'],foe_xy=(16,6))
    use(c,t,m,'Grab an improvised weapon')
    use(c,t,m,'Ancestral Ascension: Warrior as Ascendant Office')
    e=cold(tmp_path,m)
    assert not [x for x in e.legal_candidates() if x.display_name=='Ascendant Authority: Thousand Battles in One Body (Warrior)' and FOE in x.target_ids]


def test_warrior_uses_only_active_compiled_conditional_reach(tmp_path,monkeypatch):
    force_natural(monkeypatch,19)
    ac='tianxia.tradition.spirit.ancestral_channeler.feature.'
    thorn='tianxia.subpath.body.black_thorn_demon_body.feature.'
    c,t,m=scene(tmp_path,[ac+'council_of_the_remembered',ac+'ancestral_ascension',
                          thorn+'calamity_briar_incarnation'],no_improvised_throw=True,stamina_probe=True,foe_xy=(5,6))
    use(c,t,m,'Ancestral Ascension: Warrior as Ascendant Office')
    e=cold(tmp_path,m)
    assert not [x for x in e.legal_candidates() if x.display_name=='Ascendant Authority: Thousand Battles in One Body (Warrior)' and FOE in x.target_ids]
    # Activate the body feature on a later turn, then let its actual state and
    # the compiled reach eligibility rows govern the same authority query.
    end(c,t,m);advance(c,t,m,FOE);end(c,t,m);advance(c,t,m,ME)
    use(c,t,m,'Calamity Briar Incarnation')
    end(c,t,m);advance(c,t,m,ME)
    e=cold(tmp_path,m)
    assert [x for x in e.legal_candidates() if x.display_name=='Ascendant Authority: Thousand Battles in One Body (Warrior)' and FOE in x.target_ids]
    action_ids=e.state.actors[ME].action_ids
    strike=next(aid for aid in action_ids if e.action_catalog.get(aid) and
                ((e.action_catalog[aid].parameters or {}).get('reach_bonus') or {}).get('menu_variant') and
                'natural.unarmed_strike' in str(((e.action_catalog[aid].parameters or {}).get('reach_bonus') or {}).get('base') or ''))
    use(c,t,m,'Ascendant Authority: Thousand Battles in One Body (Warrior)',FOE,
        picks=[strike])
    e=cold(tmp_path,m)
    rolls=[x for x in e.events if x.event_type=='DAMAGE_ROLLED']
    assert len(rolls)>=2 and any('8d8' in x.payload.get('expression','') for x in rolls)
    assert any('8d8' not in x.payload.get('expression','') for x in rolls)


def test_last_flame_ignores_natural_one_death_save(tmp_path,monkeypatch):
    force_natural(monkeypatch,1,death_only=True)
    c,t,m=scene(tmp_path,[],ally_ids=[CM+'last_flame'],friendly_ally=True)
    end(c,t,m);advance(c,t,m,FOE)
    use(c,t,m,'Test: hurt',ME)
    e=cold(tmp_path,m);assert e.state.actors[ME].life_state=='DYING'
    use(c,t,m,'Test: death save',ME,picks=['flame'])
    e=cold(tmp_path,m)
    assert e.state.actors[ME].turn_flags['life_round_record']['bad']==0
    assert e.state.actors[ALLY].resources['resource:named.soul_candle']==0
    assert e.state.actors[ALLY].resources['resource:core.resonance']==54
    assert held(e.state.actors[ME],'last_flame_used')


def test_borrowed_final_breath_counts_one_failure_on_next_drop(tmp_path):
    c,t,m=scene(tmp_path,[],ally_ids=[CM+'last_flame'],friendly_ally=True)
    end(c,t,m);advance(c,t,m,FOE)
    use(c,t,m,'Test: hurt',ME,picks=['flame'])
    e=cold(tmp_path,m);assert e.state.actors[ME].current_hp==1
    use(c,t,m,'Test: finish',ME)
    e=cold(tmp_path,m)
    assert e.state.actors[ME].life_state=='DYING'
    assert e.state.actors[ME].turn_flags['life_round_record']['bad']==1
    assert not held(e.state.actors[ME],'borrowed_final_breath')


def test_all_eyes_open_field_follows_owner_after_commit(tmp_path):
    from combat import zones
    c,t,m=scene(tmp_path,[CH+'all_eyes_open'])
    use(c,t,m,'All Eyes Open')
    commit(c,t,m,candidate(c,m,lambda x:x.kind.value=='MOVE' and x.destination and x.destination.x==2 and x.destination.y==6))
    e=cold(tmp_path,m);field=next(z for z in zones.typed_zones(e) if z.owner_id==ME)
    assert field.center.x==2 and field.center.y==6


@pytest.mark.parametrize('enemy_hit',[False,True])
def test_borrowed_warrior_automatic_choice_harms_enemies_only(tmp_path,enemy_hit):
    ac='tianxia.tradition.spirit.ancestral_channeler.feature.'
    c,t,m=scene(tmp_path,[ac+'council_of_the_remembered',ac+'legacy_made_present'],owner_auto=True,friendly_ally=True,
                spirit_probe=True,enemy_hit=enemy_hit)
    use(c,t,m,'Legacy Made Present: Borrow the Warrior Office')
    use(c,t,m,'Test: mixed spirit injury',FOE)
    e=cold(tmp_path,m)
    assert not held(e.state.actors[ALLY],'no_opportunity_attacks')
    assert bool(held(e.state.actors[FOE],'no_opportunity_attacks'))==enemy_hit


@pytest.mark.parametrize('kind',['forced','teleport'])
def test_undertow_responds_to_short_relocations(tmp_path,kind):
    bc='tianxia.tradition.spirit.black_current_walker.feature.'
    c,t,m=scene(tmp_path,[bc+'enter_the_black_current',bc+'no_bank_holds_the_river'],relocation_probe=True)
    use(c,t,m,'Test: mark',FOE)
    if kind=='forced':use(c,t,m,'Test: push',FOE,picks=['pursue','pressure'])
    else:
        end(c,t,m);advance(c,t,m,FOE)
        chosen=candidate(c,m,lambda x:x.display_name.startswith('Test: teleport') and x.destination and x.destination.x==5 and x.destination.y==6)
        commit(c,t,m,chosen,['cell:5,6','pursue','pressure'])
    e=cold(tmp_path,m)
    assert e.state.actors[ME].resources['resource:core.resonance']==56
    assert not e.state.actors[ME].reaction_available
    assert any(x.event_type=='REACTION_RESOLVED' and x.payload.get('reaction_name')=='Undertow Pursuit' for x in e.events)
    assert any(x.condition_id.startswith('condition:typed.spirit_awakening_pressure.') for x in e.state.actors[FOE].conditions.values())


@pytest.mark.parametrize('proficient',[False,True])
def test_black_current_weapon_training_controls_flow_offer(tmp_path,proficient,monkeypatch):
    force_natural(monkeypatch,19)
    bc='tianxia.tradition.spirit.black_current_walker.feature.'
    c,t,m=scene(tmp_path,[bc+'enter_the_black_current'],weapon_probe=True,proficient=proficient)
    result=use(c,t,m,'Test: weapon strike',FOE)
    e=cold(tmp_path,m)
    offered=any('Flow After the Strike' in str(p) for p in result['_prompts'])
    assert offered==proficient
    assert e.state.actors[FOE].current_hp<1000


@pytest.mark.parametrize('place',[False,True])
def test_forced_confession_can_place_free_witness_note(tmp_path,place):
    c,t,m=scene(tmp_path,[CH+'forced_confession'])
    use(c,t,m,'Test: mark',FOE)
    use(c,t,m,'Forced Confession',FOE,picks=['note'] if place else [])
    e=cold(tmp_path,m)
    from combat.typed_executor import bears_mark
    assert bears_mark(e.state.actors[FOE],ME,'Witness Note')==place
    assert e.state.actors[ME].resources['resource:core.resonance']==55


from combat import ext
@ext.effect("tradition_test_end_lantern")
def end_test_lantern(ctx, row):
    from combat import zones
    for field in list(zones.typed_zones(ctx.engine)):
        if field.owner_id == ctx.actor.entity_id:
            zones.remove(ctx.engine, field, "TEST_DISPEL")


def test_lantern_restores_deferred_final_breath_at_field_end(tmp_path):
    c,t,m=scene(tmp_path,[],ally_ids=[CM+'last_flame',CM+'thousand_year_lantern'],friendly_ally=True)
    advance(c,t,m,ALLY)
    use(c,t,m,'Thousand-Year Lantern')
    end(c,t,m);advance(c,t,m,FOE)
    use(c,t,m,'Test: hurt',ME,picks=['flame'])
    e=cold(tmp_path,m)
    assert held(e.state.actors[ME],'lantern_deferred_breath')
    assert not held(e.state.actors[ME],'borrowed_final_breath')
    advance(c,t,m,ALLY)
    use(c,t,m,'Test: end lantern')
    e=cold(tmp_path,m)
    assert not held(e.state.actors[ME],'lantern_deferred_breath')
    assert held(e.state.actors[ME],'borrowed_final_breath')
    advance(c,t,m,FOE)
    use(c,t,m,'Test: finish',ME)
    e=cold(tmp_path,m)
    assert e.state.actors[ME].turn_flags['life_round_record']['bad']==1



def test_ancestral_warrior_preserves_plain_cultivation_attack_choice(tmp_path,monkeypatch):
    force_natural(monkeypatch,19)
    ac='tianxia.tradition.spirit.ancestral_channeler.feature.'
    c,t,m=scene(tmp_path,[ac+'council_of_the_remembered',ac+'ancestral_ascension'])
    use(c,t,m,'Ancestral Ascension: Warrior as Ascendant Office')
    attack=candidate(c,m,lambda x:x.display_name=='Ascendant Authority: Thousand Battles in One Body (Warrior)' and FOE in x.target_ids)
    commit(c,t,m,attack,[attack.source_definition_id+'.cultivation'])
    e=cold(tmp_path,m)
    rolls=[x for x in e.events if x.event_type=='DAMAGE_ROLLED']
    assert len(rolls)==1 and '8d8' in rolls[0].payload.get('expression','')
    assert held(e.state.actors[FOE],'reaction_denied')



def test_break_four_directions_two_paid_routes_normal_strike_and_four_bonus_dice(tmp_path,monkeypatch):
    force_natural(monkeypatch,19)
    c,t,m=scene(tmp_path,[CB+'three_bearing_footwork',CB+'break_the_four_directions',CB+'no_fixed_compass'],foe_xy=(7,6))
    use(c,t,m,'Choose Pole',FOE)
    use(c,t,m,'Test: gain approach')
    use(c,t,m,'Test: gain orbit')
    result=use(c,t,m,'Break the Four Directions',FOE,picks=[('approach','orbit'),'cell:5,6','cell:7,5'])
    e=cold(tmp_path,m);actor=e.state.actors[ME]
    assert actor.resources['resource:named.bearing_approach']==0
    assert actor.resources['resource:named.bearing_orbit']==0
    assert any('4d8' in x.payload.get('expression','') for x in e.events if x.event_type=='DAMAGE_ROLLED')
    assert held(e.state.actors[FOE],'reaction_denied')
    choices=[o for p in result['_prompts'] if p.get('choice') and p.get('reaction')=='Bearing Without Name'
             for o in p['choice']['options']]
    assert choices and all('token' in o['label'].lower() and any(word in o['label'].lower() for word in ('feet','attack','reactions','save')) for o in choices)
