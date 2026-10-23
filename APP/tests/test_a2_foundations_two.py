"""Foundation conversions through CombatService, real intent commits and cold replay."""
import pytest
from combat.factory_compiler import compile_character
from combat.canonical import canonical_sha256
from combat.ext import foundation_combat as f
from tests.h1_support import sheet
from tests.worker2_support import fixture, turn, settle, reload, candidate, OWNER, ALLY, FOE, sealed_native_attack


# Real runtime inputs loaded by the Foundation compiler's directory scan.
# Their basenames collide; explicit full paths let public export include both
# without changing qualification policy or substituting copied fixtures.
FOUNDATION_FIXTURE_INPUTS = (
    'combat/rules/feature_blocks.d/a2_foundations_2.json',
    'authority/typed_mechanics/reviewed_final.d/a2_foundations_2.json',
)


def table_fixture(tmp_path, group, *, current=1, stage='Perfected', talents=(), ask=True, transform=None, modes=None):
    from pathlib import Path
    assert all((Path(__file__).resolve().parents[1] / name).is_file() for name in FOUNDATION_FIXTURE_INPUTS)
    fid=f.GROUPS[group][0]
    resource=f.GROUPS[group][1]
    document=sheet(list(talents),cl=15,
        foundation={'foundation_id':fid,'stage':stage,'resource':{'name':resource.replace('_',' ').title(),
           'resource_id':'fixture:'+resource,'maximum':1,'current':current}})
    document['foundation']={'foundation_id':fid,'stage':stage,'resource':{'name':resource.replace('_',' ').title(),
           'resource_id':'fixture:'+resource,'maximum':1,'current':current}}
    document['ability_scores_and_statistics']['hit_points']['maximum']=500
    document['ability_scores_and_statistics']['technique_attack_bonus']=50
    document['ability_scores_and_statistics']['primary_resource']['maximum']=100
    bundle=compile_character(document,actor_id=OWNER,reaction_plan={'ask':ask})
    def seal(bundles):
        sealed_native_attack(bundles[2],'Hostile blow',damage_type='POISON',count=1,sides=4,modifier=40,attack_bonus=50,range_ft=5)
        for b in bundles:
            b['actor_template']['maximum_hp']=500
            b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
        if transform:transform(bundles)
    return fixture(tmp_path,[],owner_bundle=bundle,ask=ask,foe_position={'x':3,'y':5},bundle_transform=seal,seed='A2GFOU2',modes=modes)


def use(combat,table,mid,name,target=None,choices=None,at=None):
    c=candidate(combat,mid,name,target=target,at=at)
    return settle(table,mid,c.candidate_id,choices=choices or {})


@pytest.mark.parametrize('group,leaf,key,mult',[
 ('tyrant','tyrant_blood_surge','tyrant_surge',2),('origin','origin_bell_surge','origin_surge',2),
 ('devour','shedding_husk_surge','husk_surge',2),('mandate','golden_seal_bearing','golden_bearing',1)])
def test_surge_single_total_payment_and_reload(tmp_path,group,leaf,key,mult):
    combat,table,mid=table_fixture(tmp_path,group)
    from combat.typed_numbers import authority_mechanics
    name=authority_mechanics()[f.feature(group,leaf)]['name']
    use(combat,table,mid,name)
    engine=reload(tmp_path,mid);actor=engine.state.actors[OWNER]
    assert actor.temporary_hp==mult*4+2+(0 if group=='devour' else 4)
    assert actor.resources[f.pool(group)]==0
    assert f.held(actor,key)
    if group=='tyrant':
        assert 'Advantage' in f.held(actor,key).data['label'] and 'turn' in f.held(actor,key).data['label']
    if group in {'tyrant','origin'}:
        use(combat,table,mid,'Unarmed Strike',FOE)
        engine=reload(tmp_path,mid);actor=engine.state.actors[OWNER]
        rolls=[e for e in engine.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==OWNER]
        assert rolls and rolls[-1].payload['mode']=='ADVANTAGE'
        assert f.held(actor,key) is None
        assert actor.resources[f.pool(group)]==1
    if group=='devour':
        assert {'NECROTIC','POISON'} <= {str(m.value) for m in actor.modifiers.values() if m.target_field=='damage_resistance'}


@pytest.mark.parametrize('group,leaf,key',[
 ('tyrant','perfected_heaven_tyrant_blood_declaration','tyrant_declaration'),
 ('origin','perfected_no_beginning_origin_court','origin_court'),
 ('devour','perfected_imperishable_heaven_womb','devour_womb'),
 ('mandate','perfected_golden_mandate_court','mandate_court'),
 ('furnace','perfected_jade_furnace_meridian_cycle','furnace_cycle')])
def test_perfected_states_total_cl_and_once_rest(tmp_path,group,leaf,key):
    combat,table,mid=table_fixture(tmp_path,group)
    from combat.typed_numbers import authority_mechanics
    name=authority_mechanics()[f.feature(group,leaf)]['name']
    use(combat,table,mid,name,choices={f.CHOICE+'foundation_court':[OWNER,ALLY]})
    engine=reload(tmp_path,mid);actor=engine.state.actors[OWNER]
    assert actor.temporary_hp==17
    assert f.held(actor,key)
    label=f.held(actor,key).data['label']
    if key in {'tyrant_declaration','devour_womb'}:
        assert 'For one minute' in label and 'each qualifying hit' in label
    if key == 'tyrant_declaration':
        assert 'Advantage on qualifying Strength or Constitution physical contests' in label
        assert 'Grappled or Restrained' in label and 'body suppression' in label
        assert 'Resolve these checks manually' in label and 'control can still affect you' in label
        assert 'body control is blocked' not in label
    if 'court' in key:
        assert set(f.held(actor,key).data['allies'])=={OWNER,ALLY}
        assert FOE not in f.held(actor,key).data['allies']
    turn(table,mid,FOE);turn(table,mid,OWNER)
    engine=reload(tmp_path,mid)
    assert not [c for c in engine.legal_candidates() if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', None)==name]


@pytest.mark.parametrize('group,leaf,cut',[
 ('tyrant','imperial_shoulder_gate',14),('origin','no_beginning_guard',14),
 ('devour','devouring_return',10),('furnace','furnace_vent_guard',10),('integrity','integrity_guard',10)])
def test_guard_spends_existing_token_before_damage_generation(tmp_path,group,leaf,cut):
    combat,table,mid=table_fixture(tmp_path,group)
    turn(table,mid,FOE)
    prompts=use(combat,table,mid,'Hostile blow',OWNER)
    foundation_prompt=next(p for p in prompts if p['context'].get('reaction_source_id')==f.CHOICE+'foundation_combat')
    assert '1 ' in foundation_prompt['choice']['cost']
    engine=reload(tmp_path,mid)
    reaction=[e for e in engine.events if e.event_type=='REACTION_RESOLVED' and e.source_definition_id==f.feature(group,leaf)]
    assert len(reaction)==1
    before=next(e for e in engine.events if e.event_type=='REACTION_WINDOW_OPENED' and e.payload.get('checkpoint')=='DAMAGE_APPLICATION')
    committed=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and OWNER in e.target_ids][-1]
    assert committed.payload['hp_damage']==before.payload['pending_damage']-cut
    assert not engine.state.actors[OWNER].reaction_available
    assert engine.state.actors[OWNER].resources[f.pool(group)]== (1 if group in {'tyrant','integrity'} else 0)


@pytest.mark.parametrize('group',['tyrant','integrity'])
def test_no_same_event_guard_empty_token_generates_only_after_damage(tmp_path,group):
    def two_hits(bundles):
        foe=bundles[2]
        a=next(a for a in foe['action_catalog'] if a['display_name']=='Hostile blow')
        a['resolution_kind']='MULTI_ATTACK';a['attack_count']=2
        foe.pop('bundle_sha256',None);foe['bundle_sha256']=canonical_sha256(foe)
    combat,table,mid=table_fixture(tmp_path,group,current=0,transform=two_hits)
    turn(table,mid,FOE);use(combat,table,mid,'Hostile blow',OWNER)
    engine=reload(tmp_path,mid)
    committed=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and OWNER in e.target_ids]
    reactions=[e for e in engine.events if e.event_type=='REACTION_RESOLVED' and e.source_definition_id.startswith('foundation.')]
    assert len(committed)==2 and len(reactions)==1
    assert committed[0].sequence < reactions[0].sequence < committed[1].sequence
    assert engine.state.actors[OWNER].resources[f.pool(group)]==0


@pytest.mark.parametrize('group,leaf',[('tyrant','tyrant_form_crush'),('origin','sacred_dao_strike')])
def test_strike_paid_and_blocks_ordinary_body_control(tmp_path,group,leaf):
    combat,table,mid=table_fixture(tmp_path,group)
    prompts=use(combat,table,mid,'Unarmed Strike',FOE)
    foundation_prompt=next(p for p in prompts if p['context'].get('reaction_source_id')==f.CHOICE+'foundation_combat')
    assert '1 ' in foundation_prompt['choice']['cost']
    engine=reload(tmp_path,mid)
    spent=[e for e in engine.events if e.event_type=='RESOURCE_SPENT' and e.source_definition_id==f.feature(group,leaf)]
    assert len(spent)==1
    assert f.held(engine.state.actors[OWNER],'answer_'+group).data['against']==FOE


@pytest.mark.parametrize('higher_authority,blocked_expected',[(False,True),(True,False)])
@pytest.mark.parametrize('group,leaf',[('tyrant','tyrant_form_crush'),('origin','sacred_dao_strike')])
def test_strike_control_protection_resolves_real_hostile_effect_and_reload(tmp_path,group,leaf,higher_authority,blocked_expected):
    def hostile_control(bundles):
        pressure_action(bundles,'str','prone')
        if higher_authority:
            bundles[2]['cl']=20
            bundles[2].pop('bundle_sha256',None);bundles[2]['bundle_sha256']=canonical_sha256(bundles[2])
    combat,table,mid=table_fixture(tmp_path,group,transform=hostile_control)
    use(combat,table,mid,'Unarmed Strike',FOE)
    turn(table,mid,FOE)
    use(combat,table,mid,'Hostile pressure',OWNER)
    engine=reload(tmp_path,mid)
    prone=[c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id.endswith('.prone')]
    assert bool(prone) is (not blocked_expected)
    assert any(e.event_type=='RESOURCE_SPENT' and e.source_definition_id==f.feature(group,leaf) for e in engine.events)


@pytest.mark.parametrize('direction,end_y',[('away',8),('toward',4)],ids=['push','pull'])
@pytest.mark.parametrize('higher_authority,paid,blocked_expected',[
    (False,True,True),(True,True,False),(False,False,False)],
    ids=['paid-ordinary','paid-higher-authority','unpaid'])
@pytest.mark.parametrize('group,leaf',[('tyrant','tyrant_form_crush'),('origin','sacred_dao_strike')])
def test_strike_push_pull_protection_through_service_and_reload(
        tmp_path,group,leaf,direction,end_y,higher_authority,paid,blocked_expected):
    def hostile_movement(bundles):
        pressure_action(bundles,'str','forced_movement')
        foe=bundles[2]
        action=next(a for a in foe['action_catalog'] if a['display_name']=='Hostile pressure')
        action['parameters']['typed']['effects']=[{
            'type':'forced_movement','distance_ft':10,'direction':direction,'applies_to':'target'}]
        if higher_authority:
            foe['cl']=20
        foe.pop('bundle_sha256',None);foe['bundle_sha256']=canonical_sha256(foe)
    combat,table,mid=table_fixture(tmp_path,group,transform=hostile_movement)
    use(combat,table,mid,'Unarmed Strike',FOE,
        choices={} if paid else {f.CHOICE+'foundation_combat':None})
    engine=reload(tmp_path,mid)
    spends=[e for e in engine.events if e.event_type=='RESOURCE_SPENT'
            and e.source_definition_id==f.feature(group,leaf)]
    assert len(spends)==int(paid)
    protection=f.held(engine.state.actors[OWNER],'answer_'+group)
    assert bool(protection) is paid
    if paid:
        assert protection.data['against']==FOE
    turn(table,mid,FOE)
    # Leave space for a real pull: an adjacent caster would occupy its only landing cell.
    engine=combat._load_session(mid).engine
    move=next(c for c in engine.legal_candidates()
              if c.source_definition_id=='system:combat.movement' and c.destination
              and (c.destination.x,c.destination.y)==(3,3))
    settle(table,mid,move.candidate_id)
    engine=reload(tmp_path,mid)
    assert (engine.state.actors[FOE].position.x,engine.state.actors[FOE].position.y)==(3,3)
    before=engine.state.actors[OWNER].position
    sequence=engine.events[-1].sequence
    use(combat,table,mid,'Hostile pressure',OWNER)
    engine=reload(tmp_path,mid)
    after=engine.state.actors[OWNER].position
    assert (after.x,after.y)==((before.x,before.y) if blocked_expected else (3,end_y))
    movement=[e for e in engine.events if e.sequence>sequence
              and e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==OWNER]
    assert bool(movement) is (not blocked_expected)


@pytest.mark.parametrize('group,leaf,blocked_expected',[
    ('tyrant','tyrant_form_crush',False),('origin','sacred_dao_strike',True)])
def test_strike_body_suppression_protection_scope_through_service_and_reload(tmp_path,group,leaf,blocked_expected):
    combat,table,mid=table_fixture(tmp_path,group,transform=lambda b:pressure_action(b,'con','body_suppression'))
    use(combat,table,mid,'Unarmed Strike',FOE)
    turn(table,mid,FOE)
    use(combat,table,mid,'Hostile pressure',OWNER)
    engine=reload(tmp_path,mid)
    suppressed=[c for c in engine.state.actors[OWNER].conditions.values()
                if c.condition_id.endswith('.body_suppression')]
    assert bool(suppressed) is (not blocked_expected)
    assert any(e.event_type=='RESOURCE_SPENT' and e.source_definition_id==f.feature(group,leaf)
               for e in engine.events)


def test_oath_declaration_ally_side_generation_guard_and_selected_mantle(tmp_path):
    def two_actions(bundles):
        foe=bundles[2]
        a=next(a for a in foe['action_catalog'] if a['display_name']=='Hostile blow')
        a['economy']='BONUS_ACTION'
        sealed_native_attack(foe,'Second hostile blow',damage_type='POISON',count=1,sides=4,modifier=40,attack_bonus=50,range_ft=5)
    combat,table,mid=table_fixture(tmp_path,'oath',current=0,transform=two_actions)
    use(combat,table,mid,'Declare Protected Subject',choices={f.CHOICE+'foundation_subject':[ALLY]})
    use(combat,table,mid,'Foundation expression: Oath-Skin Mantle')
    engine=reload(tmp_path,mid)
    assert f.held(engine.state.actors[OWNER],'protected_subject').data['subject']==ALLY
    assert not any(c.target_ids==(FOE,) and engine.action_catalog[c.source_definition_id].display_name=='Declare Protected Subject' for c in engine.legal_candidates())
    turn(table,mid,FOE);use(combat,table,mid,'Hostile blow',OWNER)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources[f.pool('oath')]==1
    assert engine.state.actors[OWNER].temporary_hp==4
    use(combat,table,mid,'Second hostile blow',ALLY)
    engine=reload(tmp_path,mid)
    assert any(e.event_type=='REACTION_RESOLVED' and e.source_definition_id==f.feature('oath','iron_oath_guard') for e in engine.events)


def test_resource_expiry_end_of_next_turn(tmp_path):
    combat,table,mid=table_fixture(tmp_path,'tyrant',current=0)
    use(combat,table,mid,'Unarmed Strike',FOE)
    assert reload(tmp_path,mid).state.actors[OWNER].resources[f.pool('tyrant')]==1
    turn(table,mid,FOE);turn(table,mid,OWNER)
    use(combat,table,mid,'Dodge')
    turn(table,mid,FOE)
    assert reload(tmp_path,mid).state.actors[OWNER].resources[f.pool('tyrant')]==0


def test_jade_cycle_discount_and_heat_payment_generation(tmp_path):
    def repeatable_test_technique(bundles):
        action=next(a for a in bundles[0]['action_catalog'] if a['display_name']=='Fireball Art')
        action['economy']='NONE'
        action['parameters']['free_primary']=True
        bundles[0].pop('bundle_sha256',None);bundles[0]['bundle_sha256']=canonical_sha256(bundles[0])
    combat,table,mid=table_fixture(tmp_path,'furnace',current=1,talents=['FIRE_TAL_FIREBALL_ART'],transform=repeatable_test_technique)
    use(combat,table,mid,'Perfected: Jade Furnace Meridian Cycle')
    spent_total=0
    for expected in (4,5):
        engine=reload(tmp_path,mid)
        action=next(a for a in engine.action_catalog.values() if a.display_name=='Fireball Art')
        assert engine.effective_costs(engine.state.actors[OWNER],action.source_definition_id,action.costs)==(('resource:core.qi',expected),)
        from dataclasses import asdict
        from combat.alternative_payments import options
        effective=engine.effective_costs(engine.state.actors[OWNER],action.source_definition_id,action.costs)
        normal=next(p for p in options(engine,engine.state.actors[OWNER],action.source_definition_id,effective) if p.label=='Keep Furnace Heat; pay normally')
        choices={'choice:alternative_payment':canonical_sha256(asdict(normal))[:24],f.CHOICE+'foundation_release':None}
        use(combat,table,mid,'Fireball Art',at=(3,5),choices=choices)
        engine=reload(tmp_path,mid)
        spent_now=sum(int(e.payload.get('amount') or 0) for e in engine.events if e.event_type=='RESOURCE_SPENT' and e.source_definition_id==action.source_definition_id)
        assert spent_now-spent_total==expected
        spent_total=spent_now
    turn(table,mid,FOE);turn(table,mid,OWNER)
    engine=reload(tmp_path,mid)
    action=next(a for a in engine.action_catalog.values() if a.display_name=='Fireball Art')
    assert engine.effective_costs(engine.state.actors[OWNER],action.source_definition_id,action.costs)==(('resource:core.qi',4),)


@pytest.mark.parametrize('group,state,name',[
 ('origin','origin_court','Perfected: No-Beginning Origin Court'),
 ('mandate','mandate_court','Perfected: Golden Mandate Court')])
def test_automatic_court_recipients_are_allies(tmp_path,group,state,name):
    combat,table,mid=table_fixture(tmp_path,group,ask=False)
    from combat.typed_numbers import authority_mechanics
    leaf='perfected_no_beginning_origin_court' if group=='origin' else 'perfected_golden_mandate_court'
    name=authority_mechanics()[f.feature(group,leaf)]['name']
    use(combat,table,mid,name)
    engine=reload(tmp_path,mid)
    chosen=set(f.held(engine.state.actors[OWNER],state).data['allies'])
    assert chosen and chosen <= {OWNER,ALLY}
    assert FOE not in f.held(engine.state.actors[OWNER],state).data['allies']


def test_selected_jade_gold_guard_stacks_on_same_reaction(tmp_path):
    combat,table,mid=table_fixture(tmp_path,'integrity')
    use(combat,table,mid,'Foundation expression: Jade-Gold Guard')
    turn(table,mid,FOE);use(combat,table,mid,'Hostile blow',OWNER)
    engine=reload(tmp_path,mid)
    reactions=[e for e in engine.events if e.event_type=='REACTION_RESOLVED' and e.source_definition_id==f.feature('integrity','integrity_guard')]
    assert len(reactions)==1
    before=next(e for e in engine.events if e.event_type=='REACTION_WINDOW_OPENED' and e.payload.get('checkpoint')=='DAMAGE_APPLICATION')
    damage=next(e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and OWNER in e.target_ids)
    assert damage.payload['hp_damage']==before.payload['pending_damage']-14
    assert engine.state.actors[OWNER].turn_flags['foundation_round_vessel']==engine.state.round_number


@pytest.mark.parametrize('banked',[True,False])
def test_actual_paid_furnace_technique_spends_then_generates(tmp_path,banked):
    combat,table,mid=table_fixture(tmp_path,'furnace',talents=['FIRE_TAL_FIREBALL_ART'],
        transform=lambda bundles: pressure_action(bundles,'con','poisoned'))
    before=reload(tmp_path,mid).state.actors[OWNER].resources['resource:core.qi']
    choices={}
    if not banked:
        from dataclasses import asdict
        from combat.alternative_payments import options
        engine=reload(tmp_path,mid)
        action=next(a for a in engine.action_catalog.values() if a.display_name=='Fireball Art')
        normal=next(p for p in options(engine,engine.state.actors[OWNER],action.source_definition_id,action.costs) if p.label=='Keep Furnace Heat; pay normally')
        choices={'choice:alternative_payment':canonical_sha256(asdict(normal))[:24],f.CHOICE+'foundation_release':'first'}
    prompts=use(combat,table,mid,'Fireball Art',choices=choices,at=(3,5))
    if not banked:
        release_prompt=next(p for p in prompts if p['context'].get('reaction_source_id')==f.CHOICE+'foundation_release')
        assert 'Furnace Heat' in release_prompt['choice']['cost']
        assert 'Fireball Art' in release_prompt['moment']
        assert reload(tmp_path,mid).state.actors[FOE].display_name in release_prompt['moment']
    engine=reload(tmp_path,mid);actor=engine.state.actors[OWNER]
    spends=[e for e in engine.events if e.event_type=='RESOURCE_SPENT' and e.actor_id==OWNER]
    assert any(e.payload['resource_id']==f.pool('furnace') for e in spends)
    assert actor.resources[f.pool('furnace')]==1
    assert actor.resources['resource:core.qi']==before-(3 if banked else 5)
    assert bool(f.held(actor,'clean_residue'))
    assert bool([e for e in spends if e.source_definition_id==f.feature('furnace','jade_furnace_release')]) is (not banked)
    turn(table,mid,FOE)
    use(combat,table,mid,'Hostile pressure',OWNER)
    engine=reload(tmp_path,mid)
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==OWNER]
    assert saves and saves[-1].payload['mode']=='ADVANTAGE'
    assert not f.held(engine.state.actors[OWNER],'clean_residue')


def pressure_action(bundles,ability,named):
    foe=bundles[2];source='action:test.foundation_pressure'
    foe['action_catalog'].append({'source_definition_id':source,'display_name':'Hostile pressure',
        'owner_id':FOE,'economy':'ACTION','resolution_kind':'TYPED','target_kind':'HOSTILE_ENTITY','range_ft':60,'costs':[],
        'parameters':{'typed':{'source':'test.foundation_pressure','numbers':{'save_dc':100},
            'effects':[{'type':'save','applies_to':'target','ability':ability,
                'save_categories':[named], 'on_fail':[{'type':'condition','condition':named,
                    'applies_to':'target','duration':'one_minute'}]}],'riders':[],'duration':{'kind':'instant'}}}})
    foe['actor_template']['action_ids'].append(source)
    foe.pop('bundle_sha256',None);foe['bundle_sha256']=canonical_sha256(foe)


@pytest.mark.parametrize('group,ability,named',[
 ('glass','wis','frightened'),('glass','cha','charmed'),('mandate','wis','charmed'),
 ('mandate','cha','silenced'),
 ('tyrant','str','prone'),('origin','con','restrained'),('devour','con','source_corruption'),
 ('furnace','con','poisoned')])
def test_printed_passive_hostile_save_advantage_and_reload(tmp_path,group,ability,named):
    combat,table,mid=table_fixture(tmp_path,group,current=0,transform=lambda b:pressure_action(b,ability,named))
    turn(table,mid,FOE);use(combat,table,mid,'Hostile pressure',OWNER)
    engine=reload(tmp_path,mid)
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==OWNER]
    assert saves and saves[-1].payload['mode']=='ADVANTAGE'


def test_glass_refraction_paid_state_and_rest_limit(tmp_path):
    combat,table,mid=table_fixture(tmp_path,'glass',current=0)
    from tests.glass_refraction_support import declare
    declare(combat,table,mid)
    before=reload(tmp_path,mid).state.actors[OWNER].resources['resource:core.qi']
    use(combat,table,mid,'Perfected — Glass Heart Refraction')
    engine=reload(tmp_path,mid);actor=engine.state.actors[OWNER]
    assert f.held(actor,'glass_refraction')
    assert actor.resources['resource:core.qi']==before-2
    assert actor.resource_maximums[f.pool('glass')]==1
    assert actor.resources[f.pool('glass')]==0
    turn(table,mid,FOE);turn(table,mid,OWNER)
    declare(combat,table,mid)
    assert not [c for c in reload(tmp_path,mid).legal_candidates() if 'perfected_glass_heart_refraction' in c.source_definition_id]


def test_ai_owner_can_choose_owned_refined_expression_with_real_ai_step(tmp_path):
    combat,table,mid=table_fixture(tmp_path,'integrity')
    turn(table,mid,FOE)
    session=combat._load_session(mid)
    metadata=combat._read_metadata(mid,session)
    metadata['participant_control_modes'][OWNER]='LOCAL_AUTO'
    combat._write_metadata(mid,metadata)
    turn(table,mid,OWNER)
    engine=reload(tmp_path,mid)
    before=engine.state.event_sequence
    settle(table,mid,'ignored-for-real-ai-step',auto=True)
    engine=reload(tmp_path,mid)
    actor=engine.state.actors[OWNER]
    selected=f.held(actor,'expression')
    assert selected and selected.data.get('feature')==f.feature('integrity','jade_gold_guard')
    assert f.selected_query(engine,actor,f.feature('integrity','jade_gold_guard')) is True
    assert any(e.sequence>before and e.actor_id==OWNER and e.event_type=='INTENT_ACCEPTED' for e in engine.events)
    for _ in range(20):
        menu=table.state(mid)['menu']
        if menu['actor_id']==FOE:
            break
        if menu.get('end_turn'):
            settle(table,mid,menu['end_turn'])
        else:
            settle(table,mid,'ignored-for-real-ai-step',auto=True)
    assert table.state(mid)['menu']['actor_id']==FOE
    session=combat._load_session(mid)
    metadata=combat._read_metadata(mid,session)
    metadata['participant_control_modes'][OWNER]='MANUAL'
    combat._write_metadata(mid,metadata)
    guard_prompts=use(combat,table,mid,'Hostile blow',OWNER)
    guard_prompt=next(p for p in guard_prompts if p['context'].get('reaction_source_id')==f.CHOICE+'foundation_combat')
    assert 'Hostile blow' in guard_prompt['moment']
    assert reload(tmp_path,mid).state.actors[OWNER].display_name in guard_prompt['moment']
    engine=reload(tmp_path,mid)
    guard=next(e for e in engine.events if e.event_type=='REACTION_RESOLVED'
               and e.source_definition_id==f.feature('integrity','integrity_guard'))
    assert guard.target_ids==(OWNER,)


def test_furnace_release_increases_one_damage_packet_before_resistance(tmp_path):
    # The release choice is taken during the original damage resolution. One
    # committed packet carries the selected bonus through Resistance rounding.
    def resistant_foe(bundles):
        owner=bundles[0];source='action:test.grant_fire_resistance'
        owner['action_catalog'].append({'source_definition_id':source,'display_name':'Test Fire Ward','owner_id':OWNER,
            'economy':'NONE','resolution_kind':'TYPED','target_kind':'HOSTILE_ENTITY','range_ft':60,'costs':[],
            'parameters':{'free_primary':True,'typed':{'source':'test.fire_ward','effects':[{'type':'resistance','applies_to':'target',
                'damage_types':['FIRE'],'duration':'until_end_of_turn'}],'riders':[]}}})
        owner['actor_template']['action_ids'].append(source)
        owner.pop('bundle_sha256',None);owner['bundle_sha256']=canonical_sha256(owner)
    combat,table,mid=table_fixture(tmp_path,'furnace',current=1,talents=['FIRE_TAL_FIREBALL_ART'],transform=resistant_foe)
    from dataclasses import asdict
    from combat.alternative_payments import options
    initial=reload(tmp_path,mid)
    fireball=next(a for a in initial.action_catalog.values() if a.display_name=='Fireball Art')
    normal=next(p for p in options(initial,initial.state.actors[OWNER],fireball.source_definition_id,fireball.costs) if p.label=='Keep Furnace Heat; pay normally')
    choices={'choice:alternative_payment':canonical_sha256(asdict(normal))[:24],f.CHOICE+'foundation_release':'increase'}
    use(combat,table,mid,'Test Fire Ward',FOE)
    prompts=use(combat,table,mid,'Fireball Art',at=(3,5),choices=choices)
    release_prompt=next(p for p in prompts if p['context'].get('reaction_source_id')==f.CHOICE+'foundation_release')
    assert 'Furnace Heat' in release_prompt['choice']['cost']
    assert 'Fireball Art' in release_prompt['moment']
    assert reload(tmp_path,mid).state.actors[FOE].display_name in release_prompt['moment']
    engine=reload(tmp_path,mid)
    packets=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and e.actor_id==OWNER and FOE in e.target_ids]
    assert len(packets)==1
    # Same seed, same action and target: Release changes the one original damage value
    # by PB + the key ability modifier (rather than merely spending Heat).
    control_combat,control_table,control_mid=table_fixture(tmp_path/'control','furnace',current=1,
        talents=['FIRE_TAL_FIREBALL_ART'],transform=resistant_foe)
    control_engine=reload(tmp_path/'control',control_mid)
    control_fireball=next(a for a in control_engine.action_catalog.values() if a.display_name=='Fireball Art')
    control_normal=next(p for p in options(control_engine,control_engine.state.actors[OWNER],
        control_fireball.source_definition_id,control_fireball.costs) if p.label=='Keep Furnace Heat; pay normally')
    control_choices={'choice:alternative_payment':canonical_sha256(asdict(control_normal))[:24],
                     f.CHOICE+'foundation_release':None}
    use(control_combat,control_table,control_mid,'Test Fire Ward',FOE)
    use(control_combat,control_table,control_mid,'Fireball Art',at=(3,5),choices=control_choices)
    control_packet=next(e for e in reload(tmp_path/'control',control_mid).events
        if e.event_type=='DAMAGE_COMMITTED' and e.actor_id==OWNER and FOE in e.target_ids)
    bonus=sum(f.values(engine,engine.state.actors[OWNER]))
    assert packets[0].payload['rolled_or_pending_damage']-control_packet.payload['rolled_or_pending_damage']==bonus
    assert packets[0].payload['hp_damage']==packets[0].payload['rolled_or_pending_damage']//2
    assert len([e for e in engine.events if e.event_type=='RESOURCE_SPENT' and e.source_definition_id==f.feature('furnace','jade_furnace_release')])==1


def test_furnace_healing_release_adjusts_original_offer_once_with_penalty_and_reload(tmp_path):
    def healing_action(bundles):
        owner=bundles[0];source='action:test.furnace_mend'
        owner['action_catalog'].append({'source_definition_id':source,'display_name':'Test Furnace Mend','owner_id':OWNER,
            'economy':'ACTION','resolution_kind':'TYPED','target_kind':'SELF','costs':[['resource:core.qi',1]],
            'parameters':{'typed':{'source':'test.furnace_mend','foundation_alignment':['furnace'],
                'effects':[{'type':'healing_reduction','applies_to':'self','evidence':'Healing received is reduced by your Proficiency Bonus on the next healing.',
                            'duration':'one_minute'},
                           {'type':'healing','applies_to':'self','flat':10}], 'riders':[]}}})
        owner['actor_template']['action_ids'].append(source)
        owner.pop('bundle_sha256',None);owner['bundle_sha256']=canonical_sha256(owner)
        foe=bundles[2];wound='action:test.force_wound'
        foe['action_catalog'].append({'source_definition_id':wound,'display_name':'Test Force Wound','owner_id':FOE,
            'economy':'ACTION','resolution_kind':'TYPED','target_kind':'HOSTILE_ENTITY','range_ft':60,'costs':[],
            'parameters':{'typed':{'source':'test.force_wound',
                'effects':[{'type':'damage','applies_to':'target','flat':40,'damage_types':['force']}], 'riders':[]}}})
        foe['actor_template']['action_ids'].append(wound)
        foe.pop('bundle_sha256',None);foe['bundle_sha256']=canonical_sha256(foe)
    combat,table,mid=table_fixture(tmp_path,'furnace',current=1,transform=healing_action)
    turn(table,mid,FOE);use(combat,table,mid,'Test Force Wound',OWNER)
    turn(table,mid,OWNER)
    before=reload(tmp_path,mid).state.actors[OWNER].current_hp
    prompts=use(combat,table,mid,'Test Furnace Mend',choices={f.CHOICE+'foundation_release':'increase'})
    release_prompt=next(p for p in prompts if p['context'].get('reaction_source_id')==f.CHOICE+'foundation_release')
    assert 'Furnace Heat' in release_prompt['choice']['cost']
    engine=reload(tmp_path,mid)
    applied=[e for e in engine.events if e.event_type=='HEALING_APPLIED' and e.actor_id==OWNER
             and e.source_definition_id=='action:test.furnace_mend']
    owner=engine.state.actors[OWNER]
    release_bonus=sum(f.values(engine,owner))
    penalty_event=next(e for e in engine.events if e.event_type=='MODIFIER_APPLIED'
                       and e.payload.get('target_field')=='healing_reduction')
    penalty=int(str(penalty_event.payload['value']).split(':')[-1])
    # One original offer receives Release before one existing PB reduction.
    assert len(applied)==1
    expected=max(0,10+release_bonus-penalty)
    assert release_bonus>0 and applied[0].payload['after']-applied[0].payload['before']==expected
    assert engine.state.actors[OWNER].current_hp==before+expected
    assert not any(m.target_field=='healing_reduction' for m in owner.modifiers.values())
    assert len([e for e in engine.events if e.event_type=='RESOURCE_SPENT'
                and e.source_definition_id==f.feature('furnace','jade_furnace_release')])==1


def test_furnace_temp_hp_release_adjusts_original_offer_before_single_interception(tmp_path):
    def temp_hp_actions(bundles):
        owner=bundles[0]
        wound='action:test.temp_hp_interception'
        owner['action_catalog'].append({'source_definition_id':wound,'display_name':'Test Temporary HP Wound',
            'owner_id':OWNER,'economy':'NONE','resolution_kind':'TYPED','target_kind':'SELF','costs':[],
            'parameters':{'free_primary':True,'typed':{'source':'test.temp_hp_interception','effects':[
                {'type':'intercept_healing','applies_to':'self','reduce':4,'kinds':['temp_hp'],
                 'duration':'one_minute','name':'Test Wound'}], 'riders':[]}}})
        grant='action:test.furnace_temp_hp'
        owner['action_catalog'].append({'source_definition_id':grant,'display_name':'Test Furnace Ward',
            'owner_id':OWNER,'economy':'NONE','resolution_kind':'TYPED','target_kind':'SELF',
            'costs':[['resource:core.qi',1]],'parameters':{'free_primary':True,'typed':{'source':'test.furnace_temp_hp',
                'foundation_alignment':['furnace'],'effects':[{'type':'temp_hp','applies_to':'self','flat':10}],
                'riders':[]}}})
        owner['actor_template']['action_ids'] += [wound,grant]
        owner.pop('bundle_sha256',None);owner['bundle_sha256']=canonical_sha256(owner)
    combat,table,mid=table_fixture(tmp_path,'furnace',current=1,transform=temp_hp_actions)
    use(combat,table,mid,'Test Temporary HP Wound')
    prompts=use(combat,table,mid,'Test Furnace Ward',choices={f.CHOICE+'foundation_release':'increase'})
    release_prompt=next(p for p in prompts if p['context'].get('reaction_source_id')==f.CHOICE+'foundation_release')
    assert 'Furnace Heat' in release_prompt['choice']['cost']
    engine=reload(tmp_path,mid);owner=engine.state.actors[OWNER]
    grants=[e for e in engine.events if e.event_type=='TEMP_HP_GRANTED' and e.actor_id==OWNER
            and e.source_definition_id=='action:test.furnace_temp_hp']
    bonus=sum(f.values(engine,owner))
    assert len(grants)==1
    assert grants[0].payload['offered']==10+bonus-4
    assert grants[0].payload['after']==10+bonus-4
    assert owner.temporary_hp==10+bonus-4
    assert len([e for e in engine.events if e.event_type=='RESOURCE_SPENT'
                and e.source_definition_id==f.feature('furnace','jade_furnace_release')])==1


def test_furnace_damage_release_ignores_previous_execution_payment_same_source(tmp_path):
    def action_with_paid_or_free_branch(bundles):
        owner=bundles[0];source='action:test.furnace_paid_or_free'
        damage={'type':'damage','applies_to':'target','flat':4,'damage_types':['fire']}
        owner['action_catalog'].append({'source_definition_id':source,'display_name':'Paid or Free Flame','owner_id':OWNER,
            'economy':'ACTION','resolution_kind':'TYPED','target_kind':'HOSTILE_ENTITY','range_ft':60,'costs':[],
            'parameters':{'typed':{'source':'test.furnace_paid_or_free','foundation_alignment':['furnace'],
                'effects':[{'type':'choose_effects','options':[
                    {'label':'Paid','effects':[{'type':'spend_resource','applies_to':'self','resource_id':'resource:core.qi','flat':1},damage]},
                    {'label':'Free','effects':[damage]}]}], 'riders':[]}}})
        owner['actor_template']['action_ids'].append(source)
        owner.pop('bundle_sha256',None);owner['bundle_sha256']=canonical_sha256(owner)
    combat,table,mid=table_fixture(tmp_path,'furnace',current=1,transform=action_with_paid_or_free_branch)
    paid=use(combat,table,mid,'Paid or Free Flame',FOE,
        choices={'choice:needle.effect_choices':'Paid',f.CHOICE+'foundation_release':None})
    assert any(p['context'].get('reaction_source_id')=='choice:needle.effect_choices' for p in paid)
    engine=reload(tmp_path,mid)
    qi_after_paid=engine.state.actors[OWNER].resources['resource:core.qi']
    turn(table,mid,FOE);turn(table,mid,OWNER)
    free=use(combat,table,mid,'Paid or Free Flame',FOE,
        choices={'choice:needle.effect_choices':'Free',f.CHOICE+'foundation_release':'increase'})
    assert not any(p['context'].get('reaction_source_id')==f.CHOICE+'foundation_release' for p in free)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources['resource:core.qi']==qi_after_paid
    assert engine.state.actors[OWNER].resources[f.pool('furnace')]==1
    spends=[e for e in engine.events if e.event_type=='RESOURCE_SPENT'
        and e.source_definition_id==f.feature('furnace','jade_furnace_release')]
    assert not spends


@pytest.mark.parametrize('group', ['tyrant', 'origin'])
@pytest.mark.parametrize('ability,skill,label', [
    ('STR', 'Athletics', 'Strength'), ('DEX', 'Acrobatics', 'Dexterity')])
@pytest.mark.parametrize('hostile', [True, False], ids=['hostile', 'ally'])
def test_frame_escape_ability_scope_through_service_and_reload(
        tmp_path, group, ability, skill, label, hostile):
    from combat.ext.scoped_checks import CONDITION
    from combat.typed_executor import check_modes

    def isolated_escape(bundles):
        owner = bundles[0]
        # The real scoped-action compiler needs an owned, active check_against
        # source. Narrow only this secondary fixture buff to INT, so neither
        # Athletics nor Acrobatics receives Advantage from Iron-Bone.
        buff = next(a for a in owner['action_catalog']
                    if a['display_name'] == 'Iron-Bone Internal Method: Advantage on Checks')
        def narrow(value):
            if isinstance(value, dict):
                if value.get('type') == 'check_against':
                    value['abilities'] = ['INT']
                for child in value.values():
                    narrow(child)
            elif isinstance(value, list):
                for child in value:
                    narrow(child)
        narrow(buff['parameters']['typed'])
        pressure_action(bundles, 'str', 'grappled')
        holder = bundles[2] if hostile else bundles[1]
        action = bundles[2]['action_catalog'][-1]
        action['owner_id'] = holder['actor_id']
        action['target_kind'] = 'ANY_CREATURE'
        action['parameters']['typed']['effects'] = [{
            'type': 'condition', 'condition': 'grappled', 'applies_to': 'target',
            'until_escape': True}]
        if not hostile:
            bundles[2]['action_catalog'].remove(action)
            bundles[2]['actor_template']['action_ids'].remove(action['source_definition_id'])
            holder['action_catalog'].append(action)
            holder['actor_template']['action_ids'].append(action['source_definition_id'])
        for b in bundles:
            b.pop('bundle_sha256', None)
            b['bundle_sha256'] = canonical_sha256(b)

    combat, table, mid = table_fixture(tmp_path, group, current=0,
        talents=['TAL_METAL_IRON_BONE_INTERNAL_METHOD'], transform=isolated_escape)
    use(combat, table, mid, 'Iron-Bone Internal Method: Advantage on Checks')
    holder = FOE if hostile else ALLY
    turn(table, mid, holder)
    use(combat, table, mid, 'Hostile pressure', OWNER)
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    actor = before.state.actors[OWNER]
    grips = [c for c in actor.conditions.values() if c.condition_id == 'condition:typed.grappled']
    assert len(grips) == 1 and grips[0].source_actor_id == holder
    assert any(c.condition_id == CONDITION for c in actor.conditions.values())
    # Verify no ordinary mode or another active technique can mask the Frame.
    expected_mode = {'ADVANTAGE'} if hostile and ability == 'STR' else set()
    assert check_modes(actor, ability, skill, engine=before,
                       against_creature=before.state.actors[holder], hazards=('grappled',)) == expected_mode
    resources = dict(actor.resources)
    use(combat, table, mid, f'Escape grapple: {label} ({skill})')
    after = reload(tmp_path, mid)
    (check,) = [e for e in after.events if e.sequence > before.events[-1].sequence
               and e.event_type == 'CHECK_ROLLED' and e.actor_id == OWNER]
    assert check.payload['actor']['mode'] == ('ADVANTAGE' if hostile and ability == 'STR' else 'NORMAL')
    assert not check.payload['success']
    assert any(c.condition_id == 'condition:typed.grappled'
               and c.source_actor_id == holder for c in after.state.actors[OWNER].conditions.values())
    assert not after.state.actors[OWNER].action_available
    assert after.state.actors[OWNER].resources == resources


@pytest.mark.parametrize('group', ['origin','devour'])
def test_foundation_surge_uses_explicit_check_hazards_through_service_reload(tmp_path,group):
    def isolated_escape(bundles):
        buff = next(a for a in bundles[0]['action_catalog']
                    if a['display_name'] == 'Iron-Bone Internal Method: Advantage on Checks')
        def narrow(value):
            if isinstance(value, dict):
                if value.get('type') == 'check_against':
                    value['abilities'] = ['INT']
                for child in value.values():
                    narrow(child)
            elif isinstance(value, list):
                for child in value:
                    narrow(child)
        narrow(buff['parameters']['typed'])
        pressure_action(bundles, 'str', 'grappled')
        action = bundles[2]['action_catalog'][-1]
        action['owner_id'] = FOE
        action['target_kind'] = 'ANY_CREATURE'
        action['parameters']['typed']['effects'] = [{
            'type':'condition','condition':'grappled','applies_to':'target','until_escape':True}]
        for b in bundles:
            b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=table_fixture(tmp_path,group,current=1,
        talents=['TAL_METAL_IRON_BONE_INTERNAL_METHOD'],transform=isolated_escape)
    from combat.typed_numbers import authority_mechanics
    leaf = 'origin_bell_surge' if group == 'origin' else 'shedding_husk_surge'
    use(combat,table,mid,'Iron-Bone Internal Method: Advantage on Checks')
    turn(table,mid,FOE);use(combat,table,mid,'Hostile pressure',OWNER)
    turn(table,mid,OWNER)
    use(combat,table,mid,authority_mechanics()[f.feature(group,leaf)]['name'])
    before=reload(tmp_path,mid)
    assert f.held(before.state.actors[OWNER], 'origin_surge' if group == 'origin' else 'husk_surge')
    use(combat,table,mid,'Escape grapple: Strength (Athletics)')
    after=reload(tmp_path,mid)
    checks=[e for e in after.events if e.event_type=='CHECK_ROLLED' and e.actor_id==OWNER]
    assert checks and checks[-1].payload['actor']['mode']=='ADVANTAGE'
    assert f.held(after.state.actors[OWNER], 'origin_surge' if group == 'origin' else 'husk_surge') is None


@pytest.mark.parametrize('group,protected', [('origin', True), ('tyrant', False), ('glass', False)])
def test_sacred_dao_strike_blocks_hostile_teleport_through_service_reload(tmp_path, group, protected):
    def hostile_teleport(bundles):
        pressure_action(bundles,'str','forced_movement')
        action=bundles[2]['action_catalog'][-1]
        action['parameters']['typed']['effects']=[{'type':'teleport','applies_to':'target','distance_ft':10,
            'choose_subject_destination':True}]
        for b in bundles:
            b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=table_fixture(tmp_path,group,transform=hostile_teleport)
    use(combat,table,mid,'Unarmed Strike',FOE)
    engine=reload(tmp_path,mid)
    if group in {'origin','tyrant'}:
        assert f.held(engine.state.actors[OWNER], 'answer_'+group)
    before=engine.state.actors[OWNER].position
    turn(table,mid,FOE)
    prompts=use(combat,table,mid,'Hostile pressure',OWNER)
    assert any(p['context']['reaction_source_id']=='choice:needle.subject_destination' for p in prompts)
    after=reload(tmp_path,mid)
    assert (after.state.actors[OWNER].position==before) == protected
    landed=[e for e in after.events if e.event_type=='MOVEMENT_COMMITTED'
            and e.actor_id==OWNER and e.payload.get('teleport')]
    assert bool(landed) == (not protected)


@pytest.mark.parametrize('selected', [True, False])
def test_origin_court_grants_named_resistance_check_advantage_through_reload(tmp_path, selected):
    def hostile_grapple(bundles):
        buff=next(a for a in bundles[1]['action_catalog']
                  if a['display_name']=='Iron-Bone Internal Method: Advantage on Checks')
        def narrow(value):
            if isinstance(value,dict):
                if value.get('type')=='check_against':value['abilities']=['INT']
                for child in value.values():narrow(child)
            elif isinstance(value,list):
                for child in value:narrow(child)
        narrow(buff['parameters']['typed'])
        pressure_action(bundles,'str','grappled')
        action=bundles[2]['action_catalog'][-1]
        action['target_kind']='ANY_CREATURE'
        action['parameters']['typed']['effects']=[{
            'type':'condition','condition':'grappled','applies_to':'target','until_escape':True}]
        for b in bundles:
            b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    # Give only the ally the scoped escape action; it has no Foundation Frame.
    def with_ally(bundles):
        ally=compile_character(sheet(['TAL_METAL_IRON_BONE_INTERNAL_METHOD'],cl=15),actor_id=ALLY,
                               reaction_plan={'ask':True})
        bundles[1].clear();bundles[1].update(ally)
        hostile_grapple(bundles)
    combat,table,mid=table_fixture(tmp_path,'origin',current=0,transform=with_ally)
    from combat.typed_numbers import authority_mechanics
    name=authority_mechanics()[f.feature('origin','perfected_no_beginning_origin_court')]['name']
    recipients=[OWNER,ALLY] if selected else [OWNER]
    use(combat,table,mid,name,choices={f.CHOICE+'foundation_court':recipients})
    assert set(f.held(reload(tmp_path,mid).state.actors[OWNER],'origin_court').data['allies'])==set(recipients)
    turn(table,mid,FOE);use(combat,table,mid,'Hostile pressure',ALLY)
    turn(table,mid,ALLY);use(combat,table,mid,'Iron-Bone Internal Method: Advantage on Checks')
    use(combat,table,mid,'Escape grapple: Strength (Athletics)')
    after=reload(tmp_path,mid)
    checks=[e for e in after.events if e.event_type=='CHECK_ROLLED' and e.actor_id==ALLY]
    assert checks and checks[-1].payload['actor']['mode']==('ADVANTAGE' if selected else 'NORMAL')


@pytest.mark.parametrize('tags,expected', [
    (['concentration','body_suppression'],'ADVANTAGE'),
    (['concentration'],'NORMAL'), (['concentration','ordinary_damage'],'NORMAL')])
def test_refined_body_dao_root_qualifies_concentration_save_through_reload(tmp_path,tags,expected):
    def concentration_hazard(bundles):
        pressure_action(bundles,'con','concentration')
        action=bundles[2]['action_catalog'][-1]
        action['parameters']['typed']['effects'][0]['on_fail']=[]
        action['parameters']['typed']['effects'][0]['save_categories']=tags
        for b in bundles:
            b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=table_fixture(tmp_path,'origin',current=0,stage='Refined',transform=concentration_hazard)
    turn(table,mid,FOE);use(combat,table,mid,'Hostile pressure',OWNER)
    after=reload(tmp_path,mid)
    saves=[e for e in after.events if e.event_type=='SAVE_ROLLED' and e.actor_id==OWNER]
    assert saves and saves[-1].payload['mode']==expected


@pytest.mark.parametrize('tags,expected', [
    (['ongoing_technique','formation_pressure'],'ADVANTAGE'),
    (['concentration'],'NORMAL'), (['formation_pressure'],'NORMAL'),
    (['concentration','ordinary_damage'],'NORMAL')])
def test_body_dao_root_cultivation_maintenance_check_reload(tmp_path,tags,expected):
    def pressure(bundles):
        pressure_action(bundles,'wis','concentration')
        bundles[2]['action_catalog'][-1]['parameters']['typed']['effects']=[{
            'type':'contest_against','actor_check':{'ability':'STR'},
            'target_check':{'kind':'cultivation','ability':'WIS','skill':'Cultivation','hazards':tags},
            'on_success':[],'on_fail':[]}]
        for b in bundles:
            b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=table_fixture(tmp_path,'origin',current=0,stage='Refined',transform=pressure)
    turn(table,mid,FOE);use(combat,table,mid,'Hostile pressure',OWNER)
    engine=reload(tmp_path,mid)
    check=next(e for e in reversed(engine.events) if e.event_type=='CHECK_ROLLED')
    assert check.payload['target']['mode']==expected


def test_typed_opposed_hazard_consumes_surge_once_after_reload(tmp_path):
    def pressure(bundles):
        pressure_action(bundles,'wis','drain')
        action=bundles[2]['action_catalog'].pop()
        bundles[2]['actor_template']['action_ids'].remove(action['source_definition_id'])
        action['owner_id']=OWNER
        action['parameters']['typed']['effects']=[{
            'type':'contest_against','actor_check':{'ability':'WIS','hazards':['drain']},
            'target_check':{'ability':'STR'},
            'on_success':[],'on_fail':[]}]*2
        bundles[0]['action_catalog'].append(action)
        bundles[0]['actor_template']['action_ids'].append(action['source_definition_id'])
        for b in bundles:
            b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=table_fixture(tmp_path,'devour',transform=pressure)
    from combat.typed_numbers import authority_mechanics
    use(combat,table,mid,authority_mechanics()[f.feature('devour','shedding_husk_surge')]['name'])
    assert f.held(reload(tmp_path,mid).state.actors[OWNER],'husk_surge')
    use(combat,table,mid,'Hostile pressure',FOE)
    engine=reload(tmp_path,mid)
    checks=[e for e in engine.events if e.event_type=='CHECK_ROLLED']
    assert [e.payload['actor']['mode'] for e in checks]==['ADVANTAGE','NORMAL']
    assert not f.held(engine.state.actors[OWNER],'husk_surge')


def test_foundation_escape_qualifies_each_hostile_grip(tmp_path):
    from types import SimpleNamespace
    _,_,mid=table_fixture(tmp_path,'origin',current=0)
    engine=reload(tmp_path,mid);actor=engine.state.actors[OWNER]
    def grip(source,condition):
        return SimpleNamespace(source_actor_id=source,condition_id='condition:typed.'+condition)
    friendly=grip(ALLY,'grappled');hostile=grip(FOE,'unrelated')
    assert f.foundation_escape_mode(engine,actor,[friendly,hostile],'STR','Athletics') is None
    assert f.foundation_escape_mode(engine,actor,[friendly,grip(FOE,'grappled')],'STR','Athletics')=='ADVANTAGE'
    assert f.foundation_escape_mode(engine,actor,[friendly,hostile],'DEX','Acrobatics') is None


def test_origin_benefit_labels_and_reviewed_riders_include_checks():
    from combat.typed_numbers import authority_mechanics
    for key,leaf in [('origin_surge','origin_bell_surge'),('origin_court','perfected_no_beginning_origin_court')]:
        assert 'check' in f.STATE_BENEFITS[key]
        assert 'hostile' in f.STATE_BENEFITS[key]
        riders=authority_mechanics()[f.feature('origin',leaf)]['riders']
        assert any('check' in text and 'automatic' in text or 'checks and saves' in text for text in riders)
        assert not any('resistance checks still need' in text for text in riders)


@pytest.mark.parametrize('group,ability,category', [
    ('origin', 'STR', 'formation_pressure'),
    ('origin', 'CON', 'formation_pressure'),
    ('devour', 'WIS', 'drain')])
def test_category_only_save_consumes_surge_once_through_service_reload(tmp_path, group, ability, category):
    def response(bundles):
        # Isolate the one-use grant: a passive Frame would mask the second roll.
        bundles[0]['typed_passives'] = [r for r in bundles[0]['typed_passives']
                                       if r.get('block') != f.BLOCK]
        bundles[2]['typed_reactions'].append({
            'block': 'generic', 'kind': 'attacked', 'feature_id': 'test:foundation.category_save',
            'name': 'Hostile saving throw response', 'ask': True, 'free': True,
            'range_ft': 60, 'costs': [], 'effects': [{
                'type': 'save', 'ability': ability, 'applies_to': 'attacker', 'dc': 15,
                'save_categories': [category], 'on_fail': [], 'on_success': []}]})
        # The response saves occur on the owner's turn so Origin Surge has not
        # expired. This ranged probe cannot itself spend the close-attack grant.
        source = 'action:test.foundation_category_probe'
        bundles[0]['action_catalog'].append({
            'source_definition_id': source, 'display_name': 'Ranged response probe',
            'owner_id': OWNER, 'economy': 'NONE', 'resolution_kind': 'TYPED',
            'target_kind': 'HOSTILE_ENTITY', 'range_ft': 60, 'costs': [],
            'parameters': {'free_primary': True, 'typed': {'source': source, 'range_ft': 60,
                'numbers': {'attack_bonus': 50}, 'effects': [{'type': 'attack', 'on_hit': []}],
                'duration': {'kind': 'instant'}, 'riders': []}}})
        bundles[0]['actor_template']['action_ids'].append(source)
        for bundle in bundles:
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)

    combat, table, mid = table_fixture(tmp_path, group, transform=response)
    from combat.typed_numbers import authority_mechanics
    leaf, key = ('origin_bell_surge', 'origin_surge') if group == 'origin' else ('shedding_husk_surge', 'husk_surge')
    use(combat, table, mid, authority_mechanics()[f.feature(group, leaf)]['name'])
    before = reload(tmp_path, mid)
    assert f.held(before.state.actors[OWNER], key)
    assert not any(r.get('block') == f.BLOCK for r in before.typed_passive_rows[OWNER])
    for expected in ['ADVANTAGE', 'NORMAL']:
        use(combat, table, mid, 'Ranged response probe', FOE,
            choices={'reaction:test:foundation.category_save': 'first'})
        after = reload(tmp_path, mid)
        saves = [e for e in after.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
        assert saves[-1].payload['mode'] == expected
        assert f.held(after.state.actors[OWNER], key) is None
    assert len(saves) == 2


def test_origin_surge_label_explains_alternative_attacks_and_manual_rolls(tmp_path):
    combat, table, mid = table_fixture(tmp_path, 'origin')
    from combat.typed_numbers import authority_mechanics
    use(combat, table, mid, authority_mechanics()[f.feature('origin', 'origin_bell_surge')]['name'])
    engine = reload(tmp_path, mid)
    label = f.held(engine.state.actors[OWNER], 'origin_surge').data['label']
    assert 'close attack against an enemy or' in label
    assert 'technique explicitly marked as compatible with Origin Bell Surge' in label
    assert 'Other technique rolls that contest control or suppression require manual resolution' in label
    assert 'Foundation-aligned' not in label and 'Dao-authority' not in label
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert f.roll_benefit(engine, owner, 'attack', None, (), foe, {'range_ft': 60}) is None
    assert f.roll_benefit(engine, owner, 'attack', None, (), foe,
                          {'range_ft': 60, 'foundation_alignment': ['origin']}) == 'origin_surge'
    # An ordinary close attack really is eligible without compatibility metadata.
    use(combat, table, mid, 'Unarmed Strike', FOE)
    after = reload(tmp_path, mid)
    attacks = [e for e in after.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]
    assert attacks[-1].payload['mode'] == 'ADVANTAGE'
    assert f.held(after.state.actors[OWNER], 'origin_surge') is None
