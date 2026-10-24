"""Printed Insight outcomes through table/session commits and cold replay."""
from copy import deepcopy
import json
import pytest
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload

PREFIX = 'insight.legacy-'


def owner_bundle(features, primary='Stamina', talents=()):
    doc = sheet(talents, cl=16, primary=primary)
    doc.setdefault('spheres_and_talents', {})['cultivation_insight_record_ids'] = list(features)
    doc['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
    return compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})


def reseal(b):
    b.pop('bundle_sha256', None)
    b['bundle_sha256'] = canonical_sha256(b)


def add_action(b, name, effects, *, economy='NONE', target='ANY_CREATURE', costs=()):
    base = deepcopy(next(a for a in b['action_catalog'] if a['display_name'] == 'Grapple'))
    base.update(source_definition_id='action:test.insights.' + b['actor_id'].split('.')[-1] + '.' + name.replace(' ', '_'),
                display_name=name, economy=economy, target_kind=target, range_ft=60, costs=list(costs))
    numbers = base['parameters']['typed']['numbers']
    base['parameters'] = {'typed': {'source':base['source_definition_id'], 'effects':effects, 'numbers':numbers,
                                     'duration':{'kind':'instant'}, 'riders':[]}, 'expected_damage':0}
    b['action_catalog'].append(base)
    b['actor_template']['action_ids'].append(base['source_definition_id'])
    return base


def prepare(bundles, *, hp=60, held=100, duplicate=None, save=100):
    for b in bundles:
        if b['actor_id'] == OWNER:
            if hp < 60:
                add_action(b, 'Fixture wound', [{'type':'damage','applies_to':'self','flat':60-hp,'damage_types':['untyped']}], target='SELF')
            for resource in b['actor_template']['resources']:
                if resource['resource_id'] in ('resource:core.stamina','resource:core.qi','resource:core.resonance'):
                    resource['initial'] = held
            if duplicate:
                b['typed_passives'].append({'block':'defense','feature_id':'test:independent_resistance',
                                      'kind':'resistance','damage_types':[duplicate]})
            for ability in ('STR','CON','WIS'):
                b['actor_template']['saving_throws'][ability] = save
        if b['actor_id'] == FOE:
            b['actor_template']['saving_throws']['WIS'] = save
            b['actor_template']['saving_throws']['STR'] = -100
        add_action(b, 'Damage', [{'type':'damage','applies_to':'target','flat':12,'damage_types':['bludgeoning']}])
        add_action(b, 'Lightning', [{'type':'damage','applies_to':'target','flat':12,'damage_types':['lightning']}])
        add_action(b, 'Save', [{'type':'save','applies_to':'target','ability':'con','dc':'technique_save_dc',
                              'on_fail':[{'type':'condition','applies_to':'target','condition':'poisoned','duration':{'kind':'minutes','amount':1}}]}])
        add_action(b, 'Strength save', [{'type':'save','applies_to':'target','ability':'str','dc':'technique_save_dc',
                                       'on_fail':[{'type':'condition','applies_to':'target','condition':'prone','duration':'until_removed'}]}])
        add_action(b, 'Holds', [{'type':'condition','applies_to':'target','condition':c,'duration':'until_removed'} for c in ('prone','grappled','restrained')])
        add_action(b, 'Drain', [{'type':'spend_resource','resource':'stamina','amount':1,'applies_to':'self'}])
        reseal(b)


def fight(tmp_path, slug, primary='Stamina', **kwargs):
    c,t,m = fixture(tmp_path, [], owner_bundle=owner_bundle([PREFIX+slug], primary), primary=primary,
                    bundle_transform=lambda b: prepare(b, **kwargs))
    if kwargs.get('hp', 60) < 60:
        settle(t,m,candidate(c,m,'Fixture wound').candidate_id)
    return c,t,m


def act(combat, table, mid, name, target, choices=None):
    return settle(table, mid, candidate(combat, mid, name, target=target).candidate_id, choices)


def test_flesh_regenerator_paid_start_and_limit_survive_reload(tmp_path):
    def setup(bundles):
        prepare(bundles, hp=20, held=10)
        add_action(bundles[0], 'Flesh test wound', [
            {'type':'damage','applies_to':'self','flat':5,'damage_types':['untyped']}
        ], target='SELF')
        reseal(bundles[0])

    c,t,m=fixture(tmp_path, [], owner_bundle=owner_bundle([PREFIX+'flesh-regenerator']),
                  bundle_transform=setup)
    settle(t,m,candidate(c,m,'Fixture wound').candidate_id)
    # Keep the owner below half HP after each eligible start so five starts
    # exercise the PB=4 use cap, rather than stopping at the HP threshold.
    for _ in range(5):
        turn(t,m,FOE); turn(t,m,OWNER)
        act(c,t,m,'Flesh test wound',OWNER)
    e=reload(tmp_path,m); a=e.state.actors[OWNER]
    assert a.turn_flags['insights_flesh_round_uses'] == 4  # compiled proficiency bonus
    assert a.current_hp < a.maximum_hp / 2
    assert a.resources['resource:core.stamina'] == 6


def test_flesh_regenerator_does_not_heal_at_half_or_spend(tmp_path):
    c,t,m = fight(tmp_path,'flesh-regenerator',hp=30,held=10)
    turn(t,m,FOE);turn(t,m,OWNER)
    a=reload(tmp_path,m).state.actors[OWNER]
    assert a.current_hp == 30 and a.resources['resource:core.stamina'] == 10


def test_heavenly_circulation_automatic_once(tmp_path):
    c,t,m = fight(tmp_path,'heavenly-circulation',primary='Qi',held=10)
    turn(t,m,FOE);turn(t,m,OWNER)
    a=reload(tmp_path,m).state.actors[OWNER]
    assert a.resources['resource:core.qi'] == 28
    assert a.turn_flags['insights_circulation_round_used'] == 1
    turn(t,m,FOE);turn(t,m,OWNER)
    assert reload(tmp_path,m).state.actors[OWNER].resources['resource:core.qi'] == 28


def test_hidden_reserves_damage_threshold_and_once(tmp_path):
    c,t,m = fight(tmp_path,'hidden-reserves',hp=40,held=10)
    turn(t,m,FOE);act(c,t,m,'Damage',OWNER)
    a=reload(tmp_path,m).state.actors[OWNER]
    assert a.current_hp == 28 and a.resources['resource:core.stamina'] == 18
    act(c,t,m,'Damage',OWNER)
    assert reload(tmp_path,m).state.actors[OWNER].resources['resource:core.stamina'] == 18


@pytest.mark.parametrize('duplicate,expected',[(None,6),('BLUDGEONING',2)])
def test_iron_bones_resistance_and_independent_reduction(tmp_path,duplicate,expected):
    c,t,m=fight(tmp_path,'iron-bones',duplicate=duplicate)
    turn(t,m,FOE);act(c,t,m,'Damage',OWNER)
    a=reload(tmp_path,m).state.actors[OWNER]
    assert a.current_hp == 60-expected


@pytest.mark.parametrize('duplicate,qi,damage',[(None,11,12),('LIGHTNING',10,8)])
def test_lightning_scars_distinct_round_branches(tmp_path,duplicate,qi,damage):
    b=owner_bundle(['insight.lightning-scarred-meridians'],'Qi')
    c,t,m=fixture(tmp_path,[],owner_bundle=b,primary='Qi',bundle_transform=lambda bs:prepare(bs,held=10,duplicate=duplicate))
    turn(t,m,FOE);act(c,t,m,'Lightning',OWNER);act(c,t,m,'Lightning',OWNER)
    a=reload(tmp_path,m).state.actors[OWNER]
    assert a.resources['resource:core.qi'] == qi and a.current_hp == 60-damage


@pytest.mark.parametrize('slug,ability', [('will-manifestation','con'),('unbroken-frame','con'),('heavens-luck','con')])
def test_save_rewrites_commit_with_cold_reload(tmp_path,slug,ability):
    c,t,m=fight(tmp_path,slug,save=-100)
    turn(t,m,FOE)
    if slug=='unbroken-frame':act(c,t,m,'Holds',OWNER)
    # Explicit Use on a real d20 prompt, and the nested hold-selection choice.
    source='reaction:typed.'+PREFIX+slug
    prompts=act(c,t,m,'Save',OWNER,{source:'first'})
    e=reload(tmp_path,m); a=e.state.actors[OWNER]
    rewrites=[v for v in e.events if v.event_type=='D20_REWRITTEN']
    assert len(rewrites)==1
    assert any(p['context']['reaction_source_id']==source for p in prompts)
    if slug=='heavens-luck':
        assert any(c.condition_id=='condition:typed.poisoned' for c in a.conditions.values()) # new result required
    else:
        assert not any(c.condition_id=='condition:typed.poisoned' for c in a.conditions.values())
    if slug=='unbroken-frame':
        assert not any(c.condition_id in ('condition:typed.prone','condition:typed.grappled','condition:typed.restrained') for c in a.conditions.values())
    act(c,t,m,'Save',OWNER,{source:'first'})
    assert len([v for v in reload(tmp_path,m).events if v.event_type=='D20_REWRITTEN'])==1


def test_unbroken_frame_ends_native_pin_companions_with_identifiable_choice(tmp_path):
    def setup(bs):
        prepare(bs,save=-100)
        add_action(bs[0],'Fixture Pin',[
            {'type':'condition','applies_to':'target','condition':'grappled','duration':'until_escape'},
            {'type':'condition','applies_to':'target','condition':'pinned','duration':'until_escape'},
        ])
        reseal(bs[0])
    c,t,m=fixture(tmp_path,[],owner_bundle=owner_bundle([PREFIX+'unbroken-frame']),bundle_transform=setup)
    act(c,t,m,'Fixture Pin',OWNER)
    e=reload(tmp_path,m)
    assert {x.condition_id for x in e.state.actors[OWNER].conditions.values()} >= {
        'condition:typed.grappled','condition:typed.pinned'}
    source='reaction:typed.'+PREFIX+'unbroken-frame'
    prompts=act(c,t,m,'Save',OWNER,{source:'first'})
    release=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.legacy-unbroken-frame')
    labels=[o.get('label','') for o in release['choice']['options']]
    assert any('Pinned' in label and ' by ' in label and '(Fixture Pin)' in label for label in labels), labels
    assert release['action']=='Save'
    assert release['by']==e.state.actors[OWNER].display_name
    e=reload(tmp_path,m);a=e.state.actors[OWNER]
    assert not any(x.condition_id in ('condition:typed.grappled','condition:typed.pinned') for x in a.conditions.values())


def test_immortals_sinews_strength_save_advantage(tmp_path):
    c,t,m=fight(tmp_path,'immortals-sinews')
    turn(t,m,FOE);act(c,t,m,'Strength save',OWNER)
    e=reload(tmp_path,m)
    saves=[r for r in e.rolls if r.actor_id==OWNER and r.reason.startswith('SAVE:')]
    assert saves[-1].mode=='ADVANTAGE'


def test_heart_demon_failure_periodic_and_repeat(tmp_path):
    b=owner_bundle([PREFIX+'heart-demon-manifestation'],'Resonance')
    c,t,m=fixture(tmp_path,[],owner_bundle=b,primary='Resonance',bundle_transform=lambda bs:prepare(bs,save=-100))
    act(c,t,m,'Heart Demon Manifestation',FOE)
    e=reload(tmp_path,m); target=e.state.actors[FOE]
    assert any(c.condition_id=='condition:typed.frightened' for c in target.conditions.values())
    hp=target.current_hp
    turn(t,m,FOE)
    e=reload(tmp_path,m)
    assert hp-6 <= e.state.actors[FOE].current_hp < hp
    turn(t,m,OWNER)
    assert len([v for v in reload(tmp_path,m).events if v.event_type=='SAVE_ROLLED' and v.actor_id==FOE])==2


def test_heart_demon_recast_refreshes_one_curse_and_repeat_save_clears_it(tmp_path):
    def setup(bs):
        prepare(bs,save=-100)
    foe=sheet([],cl=16)
    foe.setdefault('spheres_and_talents',{})['cultivation_insight_record_ids']=[PREFIX+'will-manifestation']
    b=owner_bundle([PREFIX+'heart-demon-manifestation'],'Resonance')
    c,t,m=fixture(tmp_path,[],owner_bundle=b,primary='Resonance',seed='HEART-DEMON-STACK',
                  foe_sheet=foe,bundle_transform=setup)
    act(c,t,m,'Heart Demon Manifestation',FOE)
    turn(t,m,FOE);turn(t,m,OWNER)
    act(c,t,m,'Heart Demon Manifestation',FOE)
    e=reload(tmp_path,m);target=e.state.actors[FOE]
    curses=[x for x in target.conditions.values() if x.condition_id=='condition:typed.frightened']
    assert len(curses)==1
    before=target.current_hp
    prior_events=len(e.events)
    turn(t,m,FOE)
    end_turn=t.state(m)['menu']['end_turn']
    settle(t,m,end_turn,{'reaction:typed.'+PREFIX+'will-manifestation':'first'})
    turn(t,m,OWNER)
    e=reload(tmp_path,m);target=e.state.actors[FOE]
    ticks=[v for v in e.events[prior_events:] if v.event_type=='DAMAGE_COMMITTED' and FOE in v.target_ids]
    assert len(ticks)==1 and 0 < before-target.current_hp <= 6
    assert any(v.event_type=='CONDITION_REMOVED' and (v.payload or {}).get('repeat_save') for v in e.events)
    assert not any(x.condition_id=='condition:typed.frightened' for x in target.conditions.values())
    assert any(x.condition_id=='condition:typed.resist_ability' and x.source_actor_id==OWNER for x in target.conditions.values())


def test_heart_demon_success_gives_source_owned_immunity(tmp_path):
    b=owner_bundle([PREFIX+'heart-demon-manifestation'],'Resonance')
    c,t,m=fixture(tmp_path,[],owner_bundle=b,primary='Resonance',bundle_transform=prepare)
    act(c,t,m,'Heart Demon Manifestation',FOE)
    a=reload(tmp_path,m).state.actors[FOE]
    assert any(c.condition_id=='condition:typed.resist_ability' and c.source_actor_id==OWNER for c in a.conditions.values())
    assert not any(c.condition_id=='condition:typed.frightened' for c in a.conditions.values())


def test_mountain_crushing_fist_hit_cost_push_and_once_per_turn(tmp_path):
    def setup(bs):
        prepare(bs, held=10)
        b=bs[0]
        a=add_action(b,'Unarmed hit',[{'type':'attack','attack_kind':'unarmed','count':1,
                                     'on_hit':[{'type':'damage','applies_to':'target','flat':1,'damage_types':['bludgeoning']}]}])
        a['parameters']['typed']['numbers']['attack_bonus']=100
        reseal(b)
    c,t,m=fixture(tmp_path,[],owner_bundle=owner_bundle([PREFIX+'mountain-crushing-fist']),primary='Stamina',
                  foe_position={'x':4,'y':6},ally_position={'x':3,'y':7},bundle_transform=setup)
    act(c,t,m,'Unarmed hit',FOE)
    e=reload(tmp_path,m)
    assert e.state.actors[OWNER].resources['resource:core.stamina']==8
    assert e.state.actors[FOE].current_hp <= 57
    assert (e.state.actors[FOE].position.x,e.state.actors[FOE].position.y)!=(4,6)
    act(c,t,m,'Unarmed hit',FOE)
    assert reload(tmp_path,m).state.actors[OWNER].resources['resource:core.stamina']==8


@pytest.mark.parametrize('automatic',[False,True])
def test_musical_resonance_ally_only_and_recipient_round_limit(tmp_path,automatic):
    talent='tianxia.talent.music.dissonant_note'
    def setup(bs):
        prepare(bs)
        for b in bs:
            if b['actor_id']==OWNER:
                for a in b['action_catalog']:
                    if (a.get('parameters',{}).get('typed') or {}).get('source')==talent:
                        a['parameters']['expected_damage']=1000
                        a['economy']='NONE' # repeat the paid activation to test recipient round cap
                reseal(b)
    c,t,m=fixture(tmp_path,[talent],owner_bundle=owner_bundle([PREFIX+'musical-resonance'],'Qi',[talent]),
                  primary='Qi',bundle_transform=setup,ask=not automatic,
                  modes={OWNER:'LOCAL_AUTO' if automatic else 'MANUAL',ALLY:'MANUAL',FOE:'MANUAL'})
    name='Dissonant Note'
    prompts=settle(t,m,candidate(c,m,name,target=FOE).candidate_id,
                   {'choice:needle.music_resonance':ALLY} if not automatic else None,auto=automatic)
    e=reload(tmp_path,m)
    assert e.state.actors[FOE].temporary_hp==0
    granted=[a for a in e.state.actors.values() if a.temporary_hp==4]
    assert len(granted)==1 and granted[0].team_id==e.state.actors[OWNER].team_id
    if prompts:
        prompt=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.music_resonance')
        assert FOE not in [o['id'] for o in prompt['choice']['options']]
    recipient=granted[0].entity_id
    from combat.ext.music_insights import RESONANCE_USED
    assert e.state.actors[recipient].turn_flags[RESONANCE_USED]==e.state.round_number


def test_musical_resonance_repeat_cap_resets_after_round_and_reload(tmp_path):
    talent='tianxia.talent.music.dissonant_note'
    def setup(bs):
        prepare(bs)
        for b in bs:
            if b['actor_id']==OWNER:
                for a in b['action_catalog']:
                    if (a.get('parameters',{}).get('typed') or {}).get('source')==talent:
                        a['economy']='NONE'
                reseal(b)
    c,t,m=fixture(tmp_path,[talent],owner_bundle=owner_bundle([PREFIX+'musical-resonance'],'Qi',[talent]),
                  primary='Qi',bundle_transform=setup)
    name='Dissonant Note'; key='choice:needle.music_resonance'
    act(c,t,m,name,FOE,{key:ALLY})
    first_round=reload(tmp_path,m).state.round_number
    prompts=act(c,t,m,name,FOE,{key:None})
    # The only ally has already benefited; the owner cannot choose themself.
    assert not [p for p in prompts if p['context']['reaction_source_id']==key]
    e=reload(tmp_path,m)
    grants=[v for v in e.events if v.event_type=='TEMP_HP_GRANTED' and v.source_definition_id==PREFIX+'musical-resonance' and ALLY in v.target_ids]
    assert len(grants)==1 and e.state.actors[ALLY].temporary_hp==4
    turn(t,m,ALLY);turn(t,m,FOE);turn(t,m,OWNER)
    e=reload(tmp_path,m)
    assert e.state.round_number>first_round
    act(c,t,m,name,FOE,{key:ALLY})
    e=reload(tmp_path,m)
    grants=[v for v in e.events if v.event_type=='TEMP_HP_GRANTED' and v.source_definition_id==PREFIX+'musical-resonance' and ALLY in v.target_ids]
    from combat.ext.music_insights import RESONANCE_USED
    assert len(grants)==2 and e.state.actors[ALLY].turn_flags[RESONANCE_USED]==e.state.round_number


def test_musical_resonance_requires_actual_cp_payment(tmp_path):
    talent='tianxia.talent.music.dissonant_note'
    def setup(bs):
        prepare(bs)
        b=bs[0]
        for name,cost in [('Free Music',()),('Paid Music',(('resource:core.qi',1),))]:
            a=add_action(b,name,[],costs=cost)
            a['parameters']['typed']['sphere']='tianxia.sphere.music'
            a['parameters']['typed']['source']=talent
        reseal(b)
    c,t,m=fixture(tmp_path,[talent],owner_bundle=owner_bundle([PREFIX+'musical-resonance'],'Qi',[talent]),
                  primary='Qi',bundle_transform=setup)
    act(c,t,m,'Free Music',FOE)
    assert all(a.temporary_hp==0 for a in reload(tmp_path,m).state.actors.values())
    act(c,t,m,'Paid Music',FOE,{'choice:needle.music_resonance':ALLY})
    assert reload(tmp_path,m).state.actors[ALLY].temporary_hp==4


@pytest.mark.parametrize('insights,multiplier',[
    (['insight.legacy-immortals-sinews'],2),
    (['insight.legacy-titans-grip'],2),
    (['insight.legacy-immortals-sinews','insight.legacy-titans-grip'],4),
])
def test_carrying_capacity_scales_before_speed_and_survives_pickup(tmp_path,insights,multiplier):
    from tests.test_carry import _sheet
    doc=deepcopy(_sheet())
    doc['identity']['cultivation_level']=16
    doc.setdefault('spheres_and_talents',{})['cultivation_insight_record_ids']=insights
    b=compile_character(doc,actor_id=OWNER,reaction_plan={'ask':True})
    assert b['carrying']['capacity_lb']==90*multiplier
    assert not b['carrying']['over'] and b['carrying']['template_speed_ft']==30
    c,t,m=fixture(tmp_path,[],owner_bundle=b)
    settle(t,m,candidate(c,m,"Drop Explorer's Pack").candidate_id)
    e=reload(tmp_path,m)
    assert e._effective_speed(e.state.actors[OWNER])==30
    pick=next(x for x in e.legal_candidates() if 'Pick up' in x.display_name and "Explorer's Pack" in x.display_name)
    settle(t,m,pick.candidate_id)
    e=reload(tmp_path,m)
    assert e._effective_speed(e.state.actors[OWNER])==30


def test_immortals_sinews_strength_checks_use_normal_check_pipeline(tmp_path):
    def setup(bs):
        prepare(bs)
        for b in bs:
            add_action(b,'Strength check',[{'type':'skill_check','ability':'STR','skill':'athletics'}])
            reseal(b)
    c,t,m=fixture(tmp_path,[],owner_bundle=owner_bundle([PREFIX+'immortals-sinews']),bundle_transform=setup)
    turn(t,m,FOE);act(c,t,m,'Strength check',OWNER)
    e=reload(tmp_path,m)
    rolls=[r for r in e.rolls if r.actor_id==OWNER and r.reason.startswith('CHECK:')]
    assert rolls[-1].mode=='ADVANTAGE'


def test_hidden_reserves_decline_keeps_the_allowance(tmp_path):
    c,t,m=fight(tmp_path,'hidden-reserves',hp=40,held=10)
    turn(t,m,FOE);act(c,t,m,'Damage',OWNER,{'choice:needle.legacy-hidden-reserves':None})
    a=reload(tmp_path,m).state.actors[OWNER]
    assert a.resources['resource:core.stamina']==10 and not a.turn_flags.get('insights_reserves_round_used')
    act(c,t,m,'Damage',OWNER)
    assert reload(tmp_path,m).state.actors[OWNER].resources['resource:core.stamina']==18


def test_lightning_scars_friendly_damage_does_not_restore_qi(tmp_path):
    b=owner_bundle(['insight.lightning-scarred-meridians'],'Qi')
    c,t,m=fixture(tmp_path,[],owner_bundle=b,primary='Qi',bundle_transform=lambda bs:prepare(bs,held=10))
    turn(t,m,ALLY);act(c,t,m,'Lightning',OWNER)
    a=reload(tmp_path,m).state.actors[OWNER]
    assert a.current_hp==54 and a.resources['resource:core.qi']==10


def test_no_insight_keeps_ordinary_damage_and_save(tmp_path):
    c,t,m=fixture(tmp_path,[],bundle_transform=prepare)
    turn(t,m,FOE);act(c,t,m,'Damage',OWNER);act(c,t,m,'Strength save',OWNER)
    e=reload(tmp_path,m)
    assert e.state.actors[OWNER].current_hp==48
    assert [r for r in e.rolls if r.actor_id==OWNER and r.reason.startswith('SAVE:')][-1].mode=='NORMAL'
    assert not [v for v in e.events if v.source_definition_id.startswith('insight.')]


@pytest.mark.parametrize('size,capacity,speed',[('Small',90,5),('Medium',180,30)])
def test_titans_grip_virtual_size_uses_actual_capacity_table(tmp_path,size,capacity,speed):
    from tests.test_carry import _sheet
    doc=deepcopy(_sheet());doc['identity'].update(size=size,cultivation_level=16)
    doc.setdefault('spheres_and_talents',{})['cultivation_insight_record_ids']=[PREFIX+'titans-grip']
    b=compile_character(doc,actor_id=OWNER,reaction_plan={'ask':True})
    assert b['carrying']['capacity_lb']==capacity
    c,t,m=fixture(tmp_path,[],owner_bundle=b)
    turn(t,m,FOE)
    e=reload(tmp_path,m)
    assert e._effective_speed(e.state.actors[OWNER])==speed


def test_heart_demon_manual_retains_any_creature_domain(tmp_path):
    b=owner_bundle([PREFIX+'heart-demon-manifestation'],'Resonance')
    c,t,m=fixture(tmp_path,[],owner_bundle=b,primary='Resonance',bundle_transform=prepare)
    candidate(c,m,'Heart Demon Manifestation',target=OWNER)
    act(c,t,m,'Heart Demon Manifestation',ALLY)
    e=reload(tmp_path,m)
    assert e.state.actors[OWNER].resources['resource:core.resonance']==97
    assert any(v.event_type=='SAVE_ROLLED' and v.actor_id==ALLY for v in e.events)


def test_heart_demon_automatic_targets_enemies_only(tmp_path):
    def setup(bs):
        prepare(bs,save=-100)
        for b in bs:
            if b['actor_id']==OWNER:
                for a in b['action_catalog']:
                    if (a['parameters'].get('typed') or {}).get('source')==PREFIX+'heart-demon-manifestation':
                        a['parameters']['expected_damage']=1000
                reseal(b)
    b=owner_bundle([PREFIX+'heart-demon-manifestation'],'Resonance')
    c,t,m=fixture(tmp_path,[],owner_bundle=b,primary='Resonance',bundle_transform=setup,
                  modes={OWNER:'LOCAL_AUTO',ALLY:'MANUAL',FOE:'MANUAL'})
    e=reload(tmp_path,m)
    choices=[x for x in e.legal_candidates() if getattr(e.action_catalog.get(x.source_definition_id),'display_name',None)=='Heart Demon Manifestation']
    assert choices and all(x.target_ids==(FOE,) for x in choices)
    settle(t,m,choices[0].candidate_id,auto=True)
    e=reload(tmp_path,m)
    casts=[v for v in e.events if v.event_type=='INTENT_ACCEPTED'
           and v.source_definition_id in [x.source_definition_id for x in choices]]
    assert casts and casts[-1].target_ids==(FOE,)
    assert not any(c.condition_id=='condition:typed.frightened' for a in (OWNER,ALLY) for c in e.state.actors[a].conditions.values())


def test_hidden_reserves_requires_real_hp_reduction_not_temporary_hp(tmp_path):
    def setup(bs):
        prepare(bs,hp=24,held=10)
        add_action(bs[0],'Fixture protection',[{'type':'temp_hp','applies_to':'self','flat':20}],target='SELF')
        reseal(bs[0])
    c,t,m=fixture(tmp_path,[],owner_bundle=owner_bundle([PREFIX+'hidden-reserves']),primary='Stamina',bundle_transform=setup)
    settle(t,m,candidate(c,m,'Fixture wound').candidate_id,{'choice:needle.legacy-hidden-reserves':None})
    settle(t,m,candidate(c,m,'Fixture protection').candidate_id)
    turn(t,m,FOE)
    prompts=act(c,t,m,'Damage',OWNER)
    a=reload(tmp_path,m).state.actors[OWNER]
    assert a.current_hp==24 and a.temporary_hp==8
    assert a.resources['resource:core.stamina']==10
    assert not a.turn_flags.get('insights_reserves_round_used')
    assert not [p for p in prompts if p['context']['reaction_source_id']=='choice:needle.legacy-hidden-reserves']


@pytest.mark.parametrize('feature,primary,kind,name',[
    (PREFIX+'iron-bones','Stamina','bludgeoning','Damage'),
    ('insight.lightning-scarred-meridians','Qi','lightning','Lightning'),
])
def test_independent_next_packet_resistance_qualifies_without_reusing_it(tmp_path,feature,primary,kind,name):
    def setup(bs):
        prepare(bs,held=10)
        add_action(bs[0],'Fixture next ward',[{'type':'resistance_next','applies_to':'self',
                   'damage_types':[kind],'duration':{'kind':'minutes','amount':1}}],target='SELF')
        reseal(bs[0])
    c,t,m=fixture(tmp_path,[],owner_bundle=owner_bundle([feature],primary),primary=primary,bundle_transform=setup)
    settle(t,m,candidate(c,m,'Fixture next ward').candidate_id)
    e=reload(tmp_path,m)
    assert any(v.target_field=='damage_resistance_next' for v in e.state.actors[OWNER].modifiers.values())
    turn(t,m,FOE);act(c,t,m,name,OWNER)
    e=reload(tmp_path,m)
    assert e.state.actors[OWNER].current_hp==58 # Resistance, then the extra PB=4 reduction
    assert not any(v.target_field=='damage_resistance_next' for v in e.state.actors[OWNER].modifiers.values())
    act(c,t,m,name,OWNER)
    a=reload(tmp_path,m).state.actors[OWNER]
    assert a.current_hp==52
    if primary=='Qi':
        assert a.resources['resource:core.qi']==10 # duplicate-Resistance variant replaces recovery this round


def test_lightning_scars_cannot_add_a_late_resistance_bonus_after_recovery(tmp_path):
    def setup(bs):
        prepare(bs,held=10)
        add_action(bs[2],'Fixture ward target',[{'type':'resistance','applies_to':'target',
                   'damage_types':['lightning'],'duration':{'kind':'minutes','amount':1}}])
        reseal(bs[2])
    c,t,m=fixture(tmp_path,[],owner_bundle=owner_bundle(['insight.lightning-scarred-meridians'],'Qi'),primary='Qi',bundle_transform=setup)
    turn(t,m,FOE);act(c,t,m,'Lightning',OWNER)
    act(c,t,m,'Fixture ward target',OWNER);act(c,t,m,'Lightning',OWNER)
    a=reload(tmp_path,m).state.actors[OWNER]
    assert a.current_hp==48 and a.resources['resource:core.qi']==11


def test_lightning_scars_zero_damage_first_attempt_keeps_first_damage_reduction(tmp_path):
    def setup(bs):
        prepare(bs,held=10,duplicate='LIGHTNING')
        for b in bs:
            add_action(b,'Small Lightning',[{'type':'damage','applies_to':'target','flat':8,'damage_types':['lightning']}])
            reseal(b)
    c,t,m=fixture(tmp_path,[],owner_bundle=owner_bundle(['insight.lightning-scarred-meridians'],'Qi'),
                  primary='Qi',bundle_transform=setup)
    turn(t,m,FOE)
    act(c,t,m,'Small Lightning',OWNER)
    assert reload(tmp_path,m).state.actors[OWNER].current_hp==60  # resistance and PB reduce the whole first attempt
    act(c,t,m,'Lightning',OWNER)
    a=reload(tmp_path,m).state.actors[OWNER]
    assert a.current_hp==58  # the first damage that lands keeps the PB reduction
    assert a.turn_flags['insights_scars_round_reduction']==a.turn_flags['insights_scars_round_first']


def test_will_manifestation_forced_success_preserves_native_concentration(tmp_path):
    def setup(bs):
        prepare(bs,save=-100)
        a=add_action(bs[0],'Fixture focus',[{'type':'mark','mark':'Fixture focus','applies_to':'self','duration':{'kind':'concentration'}}],target='SELF')
        a['concentration']=True
        a['parameters']['typed']['duration']={'kind':'minutes','amount':1,'concentration':True}
        reseal(bs[0])
    c,t,m=fixture(tmp_path,[],owner_bundle=owner_bundle([PREFIX+'will-manifestation']),bundle_transform=setup)
    settle(t,m,candidate(c,m,'Fixture focus').candidate_id)
    assert reload(tmp_path,m).state.actors[OWNER].concentration is not None
    turn(t,m,FOE)
    act(c,t,m,'Damage',OWNER,{'reaction:typed.'+PREFIX+'will-manifestation':'first'})
    e=reload(tmp_path,m)
    assert [v for v in e.events if v.event_type=='D20_REWRITTEN']
    assert e.state.actors[OWNER].concentration is not None
