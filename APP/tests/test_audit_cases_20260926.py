"""Astra's audit counterexamples (owner 2026-09-26: "I'll have astra do an audit of the whole thing"), kept as
regression tests: 12 findings against b98077d, each asserting the printed rule. Adapted only to find the app
directory from this file instead of PYTHONPATH; the original is /var/tmp/cfa-20260926/audit_cases.py.
"""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest
from combat import typed_executor as ex, typed_reactions as rx
from combat.factory_compiler import compile_character, apply_modifiers
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate3_reducer import Gate3EventReducer, enrich_committed_events, canonical_state_document
from combat.reaction_triggers import classify_mechanic
from tests.test_named_resources import SHEET

APP = Path(__file__).resolve().parents[1]
ACTOR = 'actor:factory.audit'
AUTH = json.loads((APP/'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())

def bundle(ids, **kw):
    sheet = deepcopy(SHEET)
    sheet['spheres_and_talents'] = {'learned_talent_record_ids': ids}
    sheet.update(kw)
    return compile_character(sheet, actor_id=ACTOR)

def engine_for(b):
    return Gate2Engine(APP, match_seed='AUDIT-20260926', typed_bundles=(b,),
                      roster_setup={'primary_actor_ids':[ACTOR,AN], 'team_by_actor':{ACTOR:'team:a',AN:'team:b'}})

def action(e, name):
    return next(a for a in e.action_catalog.values() if a.owner_id == ACTOR and a.display_name == name)

def context(e, a, target):
    return ex.Context(e, e.state.actors[ACTOR], a, None, a.parameters['typed'], [target], target)

def test_field_formula_offensive_option_can_target_hostiles():
    b = bundle(['ALCHEMY_BASE_FIELD_FORMULA'])
    a = next(a for a in b['action_catalog'] if a['display_name']=='Field Formula: Numbing Smoke')
    assert a['target_kind']=='CELL', a

def test_purify_removes_poison_instead_of_applying_it():
    e = engine_for(bundle(['LIFE_BASE_PURIFY_THE_PULSE']))
    target = e.state.actors[AN]
    target.team_id = e.state.actors[ACTOR].team_id
    e._apply_condition(target, 'condition:typed.poisoned', 'audit:existing_poison', AN, expires_on='UNTIL_REMOVED')
    a = action(e,'Purify the Pulse: Remove Poisoned')
    ex.run_effects(context(e,a,target),a.parameters['typed']['effects'])
    assert not any(c.condition_id=='condition:typed.poisoned' for c in target.conditions.values()), [c.model_dump() for c in target.conditions.values()]

# 2026-09-29 (sys-resources-states): Take the Blow left this list -- it is now a damage-sharing plug-in row, not a generic ally_damaged reaction
@pytest.mark.parametrize('key', ['TAL_GUARDIAN_HEAVEN_DEFYING_BULWARK', 'TAL_MONKEY_STYLE_MONKEY_CATCHES_THE_MOON'])
def test_compiler_preserves_normalized_reaction_kind(key):
    expected = classify_mechanic(AUTH['mechanics'][key])
    assert expected.runnable
    b = bundle([key])
    row = next((r for r in b['typed_reactions'] if r['feature_id']==key),None)
    assert row is not None and row['kind']==expected.kind, {'expected':expected.kind,'compiled':row,'skipped':b['diagnostics']['skipped']}

def test_yang_overheat_waits_until_the_attack_resolves():
    e = engine_for(bundle(['TAL_YANG_OVERKINDLED_RESPONSES']))
    actor, foe = e.state.actors[ACTOR], e.state.actors[AN]
    a = next(iter(e.action_catalog.values()))
    ex.block_mark(ex.Context(e,actor,a,None,{},[foe],foe), {'type':'mark','mark':'Overkindled Mark','applies_to':'target'})
    before=foe.current_hp
    rx.on_attacked(e,foe,actor,{'attack_bonus':5,'range_ft':None})
    assert foe.current_hp==before, {'hp_before_attack_roll':before,'hp_after_declaration':foe.current_hp}

def test_damage_soak_does_not_suppress_free_yin_response():
    e=engine_for(bundle(['TAL_YIN_MARKING_A_CREATURE','TAL_YIN_SPENDING_A_WANING_MARK']))
    actor, foe=e.state.actors[ACTOR],e.state.actors[AN]
    a=action(e,'Mark the Waning')
    ex.run_effects(context(e,a,foe),a.parameters['typed']['effects'])
    e.typed_reaction_rows[ACTOR].insert(0, {'feature_id':'audit:soak','block':'damage_soak','resource_id':'resource:core.qi','max_spend':1,'die':6,'minimum_damage':1})
    remaining=rx.on_damage(e,actor,20,0,source_actor_id=AN)
    assert remaining>0 and not actor.reaction_available
    assert not ex.bears_mark(foe,ACTOR,'Waning Mark'), 'the free Diminish Force response was suppressed by the paid soak'

def test_auto_does_not_wait_for_a_guard_whose_required_resource_is_missing():
    e=engine_for(bundle([])); actor=e.state.actors[ACTOR]; foe=e.state.actors[AN]
    base={'block':'generic','free':False,'costs':[],'numbers':{'pb':4},'range_ft':None}
    early={**base,'feature_id':'audit:early','kind':'attacked','effects':[{'type':'attack_modifier','applies_to':'attacker','flat':2}]}
    late={**base,'feature_id':'audit:late','kind':'damaged','requires_resource':'resource:named.empty','effects':[{'type':'damage_modifier','applies_to':'self','flat':4}]}
    e.typed_reaction_rows[ACTOR]=[early,late]
    assert not rx._can_trigger(e,actor,late)
    spec={'attack_bonus':5,'range_ft':None}
    rx.on_attacked(e,foe,actor,spec)
    assert spec['attack_bonus']==3, {'spec':spec,'reaction_available':actor.reaction_available}

def test_optional_variant_keeps_later_always_on_modifier():
    mechanics={
        'LASH':{'name':'Lash','sphere_id':'s','activation':{'economy':'action'}},
        'A_MENU':{'name':'Menu','sphere_id':'s','activation':{'economy':'passive'},'modifier':{'targets':['Lash'],'scope':'named','when':'hit','effects':[], 'options':[
            {'label':'One','effects':[{'type':'extra_damage','flat':1}]}, {'label':'Two','effects':[{'type':'extra_damage','flat':2}]}]}},
        'Z_ALWAYS':{'name':'Always','sphere_id':'s','activation':{'economy':'passive'},'modifier':{'targets':['Lash'],'scope':'named','when':'hit','effects':[{'type':'extra_damage','flat':3}]}}
    }
    built={'LASH':{'action_id':'action:audit.lash','name':'Lash','economy':'action','target_kind':'HOSTILE_ENTITY','range_ft':60,'costs':[],
                  'typed':{'effects':[{'type':'attack','on_hit':[{'type':'damage','flat':5}]}],'riders':[],'numbers':{'pb':4}},'mechanic':mechanics['LASH'],'modifiers':[]}}
    apply_modifiers(built,list(mechanics),mechanics,'qi',{'qi':20})
    assert 'Z_ALWAYS' in built['LASH']['modifiers']
    for variant in built['LASH']['variants']:
        assert any(e.get('source_modifier')=='Z_ALWAYS' for e in variant['typed']['effects'][0]['on_hit']),variant

def test_demon_mark_bonus_applies_to_damage_without_an_attack_roll():
    e=engine_for(bundle(['TAL_DAEMONIC_CULTIVATION_DEMON_MARK']))
    actor,foe=e.state.actors[ACTOR],e.state.actors[AN]
    a=action(e,'Demon Mark')
    # Establish the actual failed-save payload without relying on a favourable die.
    ex.run_effects(context(e,a,foe), a.parameters['typed']['effects'][0]['on_fail'])
    assert any(m.target_field=='typed_on_hit' for m in actor.modifiers.values())
    damage=ActionDefinition(source_definition_id='action:audit.damage',display_name='Save damage',owner_id=ACTOR,economy=EconomyKind.ACTION,resolution_kind='TYPED',target_kind='HOSTILE_ENTITY',parameters={'typed':{'numbers':{'pb':4},'effects':[]}})
    before=foe.current_hp
    ex.block_damage(context(e,damage,foe),{'type':'damage','flat':5,'damage_types':['force']})
    assert before-foe.current_hp==9, {'expected':9,'actual':before-foe.current_hp}

def test_existing_guard_and_mark_events_replay_exactly():
    e=engine_for(bundle(['TAL_YANG_OVERKINDLED_RESPONSES']))
    actor,foe=e.state.actors[ACTOR],e.state.actors[AN]
    before=e.state.model_copy(deep=True); offset=len(e.events)
    a=next(iter(e.action_catalog.values()))
    ex.block_mark(ex.Context(e,actor,a,None,{},[foe],foe),{'type':'mark','mark':'Overkindled Mark','applies_to':'target'})
    rx.on_attacked(e,foe,actor,{'attack_bonus':5,'range_ft':None})
    events=enrich_committed_events(e.events[offset:],post_engine=e)
    replay=Gate3EventReducer().apply_events(before,events)
    # Gate3Persistence._replay_from restores these two transaction-envelope fields
    # after reducing events. Omitting the roll cursor would test an incomplete harness.
    replay.roll_counter=e.state.roll_counter
    replay.state_version=e.state.state_version
    assert canonical_state_document(replay)==canonical_state_document(e.state)

def test_mark_the_waning_can_target_an_enemy():
    b=bundle(['TAL_YIN_MARKING_A_CREATURE'])
    a=next(a for a in b['action_catalog'] if a['display_name']=='Mark the Waning')
    assert a['target_kind'] not in ('SELF','ALLY_OR_SELF'), a['target_kind']

def test_yin_mark_retains_printed_expiry():
    e=engine_for(bundle(['TAL_YIN_MARKING_A_CREATURE']))
    a=action(e,'Mark the Waning'); foe=e.state.actors[AN]
    ex.run_effects(context(e,a,foe),a.parameters['typed']['effects'])
    mark=next(c for c in foe.conditions.values() if 'waning_mark' in c.condition_id)
    assert mark.expires_on not in (None,'UNTIL_REMOVED'), mark.model_dump()

def test_cinder_brand_retains_cl_scaling():
    from factory_authoring.typed_mechanics import dice_for_cl
    b=bundle(['ASH_BASE_CINDER_BRAND'])
    a=next(a for a in b['action_catalog'] if a['display_name']=='Cinder Brand: Reduce Healing')
    damage=a['parameters']['typed']['effects'][0]['on_hit'][0]
    dice=dice_for_cl(damage.get('dice_by_cl'),10) or damage['dice']
    assert dice['count']==2, {'cl':10,'damage':damage}

def test_named_mark_pool_and_compound_cost_are_not_dropped():
    key='tianxia.subpath.body.nine_star_meridian_body.feature.falling_star_descent'
    stats=deepcopy(SHEET['ability_scores_and_statistics'])
    stats['primary_resource']={'name':'Stamina','maximum':20}
    b=bundle([key], ability_scores_and_statistics=stats, identity={**SHEET['identity'],'path':'Body Refining'})
    a=next(a for a in b['action_catalog'] if a['display_name']=='Falling-Star Descent')
    # rider lane C7 (Nine-Star Meridian Body): the pool is the Subpath's Celestial Mark record (the old generic "mark" never compiled)
    assert ['resource:named.celestial_mark',3] in a['costs'], {'costs':a['costs'],'notes':b['diagnostics']['notes']}
    assert ['resource:core.stamina',2] in a['costs']

def test_ignite_keeps_its_mandatory_hit_damage():
    b=bundle(['FIRE_BASE_IGNITE'])
    a=next(a for a in b['action_catalog'] if a['display_name']=='Ignite: Push Target')
    on_hit=a['parameters']['typed']['effects'][0]['on_hit']
    assert any(e['type']=='damage' for e in on_hit),on_hit

def test_cinder_reduce_healing_does_not_heal_the_enemy():
    e=engine_for(bundle(['ASH_BASE_CINDER_BRAND']))
    foe=e.state.actors[AN];foe.current_hp-=10
    a=action(e,'Cinder Brand: Reduce Healing')
    rider=a.parameters['typed']['effects'][0]['on_hit'][1]
    before=foe.current_hp
    ex.run_effects(context(e,a,foe),[rider])
    assert foe.current_hp==before, {'before':before,'after':foe.current_hp,'effect':rider}

def test_demon_mark_watch_observes_an_ally_kill():
    e=engine_for(bundle(['TAL_DAEMONIC_CULTIVATION_DEMON_MARK']))
    actor,foe=e.state.actors[ACTOR],e.state.actors[AN]
    a=action(e,'Demon Mark')
    ex.run_effects(context(e,a,foe),a.parameters['typed']['effects'][0]['on_fail'])
    assert any(m.target_field=='typed_watch' for m in actor.modifiers.values())
    killer=actor.model_copy(deep=True,update={'entity_id':'actor:factory.ally','modifiers':{},'conditions':{}})
    extra_foe=foe.model_copy(deep=True,update={'entity_id':'actor:extra_foe','modifiers':{},'conditions':{}})
    e.state.actors[killer.entity_id]=killer;e.state.actors[extra_foe.entity_id]=extra_foe
    e.typed_actor_ids.add(killer.entity_id);e.typed_reaction_rows[killer.entity_id]=[]
    damage=ActionDefinition(source_definition_id='action:audit.kill',display_name='Ally damage',owner_id=killer.entity_id,economy=EconomyKind.ACTION,resolution_kind='TYPED',target_kind='HOSTILE_ENTITY')
    ex.block_damage(ex.Context(e,killer,damage,None,{'numbers':{}},[foe],foe),{'type':'damage','flat':100,'damage_types':['force']})
    assert not foe.active
    assert actor.resources['resource:named.devoured_essence']==1, actor.resources
