"""Foundation spends/generation through real table commits and cold replay."""
import json
import pytest
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
BOON = 'condition:typed.foundations3_boon.'

GROUPS = {
 'mirror': ('moon_mirror_still_water_v0_2B', 'Mirror Stillness', 'still_lake_breath', 'Still Lake Breath'),
 'lotus': ('mud_lotus_dantian_v0_2A', 'Lotus Dew', 'lotus_root_recovery', 'Lotus-Root Recovery'),
 'bitter': ('nine_bitter_heartfire_v0_2B', 'Bitter Heartfire', 'heartfire_surge', 'Heartfire Surge'),
 'ash': ('red_lotus_ash_returning_v0_2B', 'Funeral Ash', 'ash_veil_mercy', 'Ash-Veil Mercy'),
 'spirit': ('origin_spirit_body_v0_2B', 'Spirit-Source Dew', 'generate_spirit_source_dew', 'Generate Spirit-Source Dew'),
}

def owner_bundle(kind, initial=1, stage='Awakened', actor_id=OWNER):
    g, resource, slug, _ = GROUPS[kind]
    doc = sheet(['foundation.' + g + '.' + slug], foundation={
        'foundation_id': g, 'stage': stage, 'resource': {
            'name': resource, 'resource_id': 'tianxia.resource.test', 'maximum': 1, 'current': initial}})
    return compile_character(doc, actor_id=actor_id, reaction_plan={'ask': True})

def add_action(bundle, name, effects, *, target_kind='HOSTILE_ENTITY', economy='ACTION', bonus=8, dc=30):
    source = 'action:test.foundations3.' + bundle['actor_id'].split('.')[-1] + '.' + name.lower().replace(' ', '_')
    row = {'source_definition_id':source, 'display_name':name, 'owner_id':bundle['actor_id'],
        'economy':economy, 'resolution_kind':'TYPED', 'target_kind':target_kind, 'range_ft':60,
        'parameters':{'typed':{'source':source, 'range_ft':60, 'numbers':{'pb':4, 'key_mod':2, 'save_dc':dc, 'attack_bonus':bonus},
            'effects':effects, 'duration':{'kind':'instant'}, 'riders':[]},'expected_damage':1}}
    if economy == 'NONE':
        # These synthetic pressure/setup actions intentionally repeat without
        # spending turn economy; NONE alone no longer declares a primary action.
        row['parameters']['free_primary'] = True
    bundle['action_catalog'].append(row);bundle['actor_template']['action_ids'].append(source)
    bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)

def setup(tmp_path,kind,initial=1,stage='Awakened',opposing_foundation=False, extra=None):
    def delivery(bundles):
        if kind == 'spirit':
            # The enemy's attack provokes this ordinary manual reaction. Its
            # event actor must receive the Foundation trigger even though the
            # enemy's action is the activation that later completes.
            bundles[0]['typed_reactions'].append({'block':'generic','kind':'ally_damaged',
                'feature_id':'test:foundations3.support_reaction','name':'Support on a reaction',
                'range_ft':60,'costs':[], 'effects':[{'type':'temp_hp','flat':3,'applies_to':'ally'}]})
            add_action(bundles[2], 'Enemy strike ally', [{'type':'attack','attack_kind':'weapon',
                'on_hit':[{'type':'damage','flat':1,'damage_types':['force'],'applies_to':'target'}]}],
                bonus=100)
        for damage_type in ('fire', 'necrotic', 'poison'):
            add_action(bundles[1], 'Friendly ' + damage_type.title() + ' pressure', [
                {'type':'save','ability':'WIS','dc':30,'save_categories':['damage:'+damage_type],
                 'on_fail':[{'type':'damage','flat':1,'damage_types':[damage_type],'applies_to':'target'}],
                 'on_success':[]}], target_kind='ANY_CREATURE', economy='NONE', dc=30)
        if opposing_foundation:
            bundles[2] = owner_bundle(kind, initial=0, actor_id=FOE)
        for name,tag in [('Fear test','frightened'),('Poison test','poisoned'),('Curse test','curse'),
                         ('Disease test','disease'),('Force test','force'),('Fire test','fire')]:
            add_action(bundles[2],name,[{'type':'save','ability':'WIS','dc':15,'save_categories':[tag],
                'on_fail':[{'type':'damage','flat':1,'damage_types':['force'],'applies_to':'target'}], 'on_success':[]}],economy='NONE')
        from tests.worker2_support import sealed_native_attack
        sealed_native_attack(bundles[0], 'Native attack', damage_type='FORCE', modifier=1)
        add_action(bundles[2], 'Successful poison save', [{'type':'save','ability':'CON','save_categories':['poisoned'],'on_fail':[{'type':'condition','condition':'poisoned','applies_to':'target'}], 'on_success':[]}], economy='NONE', dc=6)
        add_action(bundles[2], 'Successful poison damage save', [{'type':'save','ability':'CON','save_categories':['damage:poison'],
            'on_fail':[{'type':'damage','flat':1,'damage_types':['poison'],'applies_to':'target'}], 'on_success':[]}], economy='NONE', dc=6)
        add_action(bundles[2], 'Fire damage', [{'type':'damage','flat':5,'damage_types':['fire'],'applies_to':'target'}], economy='NONE')
        add_action(bundles[0],'Support ally',[{'type':'temp_hp','flat':7,'applies_to':'target'}],target_kind='ALLY_OR_SELF')
        add_action(bundles[0],'Test attack',[{'type':'attack','attack_kind':'weapon', 'on_hit':[{'type':'damage','flat':1,'damage_types':['force']}]}])
        add_action(bundles[2],'Test miss',[{'type':'attack','attack_kind':'weapon','on_hit':[{'type':'damage','flat':1,'damage_types':['force'],'applies_to':'target'}]}],bonus=-50)
        add_action(bundles[2], 'Harmless miss', [{'type':'attack','attack_kind':'weapon','on_hit':[]}], bonus=-50, economy='NONE')
        add_action(bundles[2], 'Harmless poison save', [{'type':'save','ability':'CON','save_categories':['poisoned'],'on_fail':[], 'on_success':[]}], economy='NONE', dc=1)
        if extra:
            extra(bundles)
    return fixture(tmp_path,[],seed='A2GFOU3-'+kind,owner_bundle=owner_bundle(kind,initial,stage),bundle_transform=delivery)

def use(combat,table,mid,name,target=None, *, picks=None):
    return settle(table,mid,candidate(combat,mid,name,target=target).candidate_id, picks=picks)

def pool(kind):
    return 'resource:foundation.'+GROUPS[kind][1].lower().replace('-','_').replace(' ','_')

def test_fixture_free_pressure_repeats_after_reload_without_exposing_parent_packet(tmp_path):
    """Scenario pressure is explicitly free; an undeclared rider stays unavailable."""
    def delivery(bundles):
        add_action(bundles[2], 'Parent-only pressure', [
            {'type':'damage','flat':1,'damage_types':['force'],'applies_to':'target'}],
            economy='NONE')
        row = bundles[2]['action_catalog'][-1]
        row['parameters'].pop('free_primary', None)
        bundles[2].pop('bundle_sha256')
        bundles[2]['bundle_sha256'] = canonical_sha256(bundles[2])

    combat,table,mid=setup(tmp_path,'bitter',initial=0,extra=delivery)
    turn(table,mid,FOE)
    for _ in range(2):
        engine=reload(tmp_path,mid)
        actions={a.display_name:a for a in engine.action_catalog.values()}
        free=actions['Force test']
        assert free.parameters.get('free_primary') is True
        assert 'free_primary' not in actions['Test miss'].parameters
        assert not any(c.source_definition_id == actions['Parent-only pressure'].source_definition_id
                       for c in engine.legal_candidates())
        before=engine.state.actors[FOE]
        economy=(before.action_available,before.bonus_action_available,before.reaction_available)
        use(combat,table,mid,'Force test',OWNER)
        after=reload(tmp_path,mid).state.actors[FOE]
        assert (after.action_available,after.bonus_action_available,after.reaction_available) == economy
    engine=reload(tmp_path,mid)
    assert len([e for e in engine.events if e.event_type == 'SAVE_ROLLED'
                and e.source_definition_id == free.source_definition_id]) == 2
    assert not any(e.source_definition_id == actions['Parent-only pressure'].source_definition_id
                   for e in engine.events)

@pytest.mark.parametrize('kind,tag', [('mirror','Curse test'),('lotus','Disease test'),('ash','Fire test')])
def test_boon_pays_once_combines_amount_and_consumes_only_eligible_save(tmp_path,kind,tag):
    combat,table,mid=setup(tmp_path,kind)
    target=ALLY if kind in ('mirror','lotus') else OWNER
    use(combat,table,mid,GROUPS[kind][3],target)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources[pool(kind)] == 0
    assert engine.state.actors[target].temporary_hp == 6
    boon = next(c for c in engine.state.actors[target].conditions.values() if c.condition_id == BOON+kind)
    assert 'qualifying roll' not in boon.data['label']
    label = boon.data['label'].lower()
    assert 'save' in label and 'expires' in label
    if kind == 'mirror':
        assert all(term in label for term in ('fear', 'charm', 'illusion', 'dream', 'curse', 'forced spiritual movement'))
    elif kind == 'lotus':
        assert all(term in label for term in ('poison', 'disease', 'rot', 'polluted water', 'sickness exhaustion', 'failed medicine backlash', 'terrain contamination'))
    else:
        assert all(term in label for term in ('fear', 'poison', 'disease', 'fire', 'necrotic', 'blood-loss', 'despair', 'corpse/battlefield contamination'))
    assert "factory character's next turn" in label
    turn(table,mid,FOE);use(combat,table,mid,'Force test',target)
    engine=reload(tmp_path,mid)
    assert any(c.condition_id == BOON+kind for c in engine.state.actors[target].conditions.values())
    assert [e.payload['mode'] for e in engine.events if e.event_type=='SAVE_ROLLED'][-1]=='NORMAL'
    use(combat,table,mid,tag,target);engine=reload(tmp_path,mid)
    assert [e.payload['mode'] for e in engine.events if e.event_type=='SAVE_ROLLED'][-1]=='ADVANTAGE'
    assert not any(c.condition_id == BOON+kind for c in engine.state.actors[target].conditions.values())
    use(combat,table,mid,tag,target);engine=reload(tmp_path,mid)
    assert [e.payload['mode'] for e in engine.events if e.event_type=='SAVE_ROLLED'][-1]=='NORMAL'

def test_heartfire_surge_attack_consumes_shared_window(tmp_path):
    combat,table,mid=setup(tmp_path,'bitter')
    use(combat,table,mid,'Heartfire Surge',OWNER)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].temporary_hp == 10
    boon=next(c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id==BOON+'bitter')
    assert all(word in boon.data['label'] for word in ('attack','save','ability check','hostile','turn'))
    use(combat,table,mid,'Test attack',FOE);engine=reload(tmp_path,mid)
    assert [e.payload.get('mode') or (e.payload.get('roll') or {}).get('mode') for e in engine.events if e.event_type=='ATTACK_ROLLED'][-1]=='ADVANTAGE'
    assert not any(c.condition_id == BOON+'bitter' for c in engine.state.actors[OWNER].conditions.values())

def test_pain_becomes_method_both_resistances_and_expiry(tmp_path):
    combat,table,mid=setup(tmp_path,'bitter',stage='Refined')
    use(combat,table,mid,'Heartfire Surge',OWNER);engine=reload(tmp_path,mid)
    kinds={m.value for m in engine.state.actors[OWNER].modifiers.values() if m.target_field=='damage_resistance'}
    assert {'FIRE','PSYCHIC'} <= kinds
    turn(table,mid,ALLY);turn(table,mid,OWNER);engine=reload(tmp_path,mid)
    assert not [m for m in engine.state.actors[OWNER].modifiers.values() if m.target_field=='damage_resistance']

def test_spirit_dew_generates_only_positive_outward_support_and_expires(tmp_path):
    combat,table,mid=setup(tmp_path,'spirit',initial=0)
    use(combat,table,mid,'Support ally',OWNER)
    assert reload(tmp_path,mid).state.actors[OWNER].resources[pool('spirit')]==0


def test_spirit_dew_credits_positive_outward_reaction_support_on_enemy_turn(tmp_path):
    combat,table,mid=setup(tmp_path,'spirit',initial=0)
    turn(table,mid,FOE)
    candidate_id=candidate(combat,mid,'Enemy strike ally',target=ALLY).candidate_id
    settle(table,mid,candidate_id,picks={'reaction:test:foundations3.support_reaction':'first'})
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources[pool('spirit')]==1
    grants=[e for e in engine.events if e.event_type=='TEMP_HP_GRANTED'
            and e.source_definition_id=='test:foundations3.support_reaction']
    assert grants and grants[-1].actor_id==OWNER and ALLY in grants[-1].target_ids
    turn(table,mid,ALLY);turn(table,mid,OWNER);use(combat,table,mid,'Support ally',ALLY)
    assert reload(tmp_path,mid).state.actors[OWNER].resources[pool('spirit')]==1
    turn(table,mid,ALLY);turn(table,mid,OWNER)
    assert reload(tmp_path,mid).state.actors[OWNER].resources[pool('spirit')]==1
    turn(table,mid,ALLY)
    assert reload(tmp_path,mid).state.actors[OWNER].resources[pool('spirit')]==0

def test_mirror_stillness_after_final_hostile_miss_against_ally(tmp_path):
    combat,table,mid=setup(tmp_path,'mirror',initial=0)
    turn(table,mid,FOE);use(combat,table,mid,'Test miss',ALLY)
    assert reload(tmp_path,mid).state.actors[OWNER].resources[pool('mirror')]==1

def test_bitter_heartfire_after_failed_hostile_save(tmp_path):
    combat,table,mid=setup(tmp_path,'bitter',initial=0)
    turn(table,mid,FOE);use(combat,table,mid,'Force test',OWNER);engine=reload(tmp_path,mid)
    save=[e for e in engine.events if e.event_type=='SAVE_ROLLED'][-1]
    assert not save.payload['success']
    assert engine.state.actors[OWNER].resources[pool('bitter')]==1


@pytest.mark.parametrize('kind,related', [('mirror','Fear test'),('lotus','Poison test'),('bitter','Fear test')])
def test_vessel_saves_are_scoped_and_survive_service_reload(tmp_path,kind,related):
    combat,table,mid=setup(tmp_path,kind,initial=0)
    turn(table,mid,FOE);use(combat,table,mid,'Force test',OWNER)
    assert [e.payload['mode'] for e in reload(tmp_path,mid).events if e.event_type=='SAVE_ROLLED'][-1]=='NORMAL'
    use(combat,table,mid,related,OWNER)
    assert [e.payload['mode'] for e in reload(tmp_path,mid).events if e.event_type=='SAVE_ROLLED'][-1]=='ADVANTAGE'


def test_lotus_dew_after_successful_hostile_poison_save_for_ally(tmp_path):
    combat,table,mid=setup(tmp_path,'lotus',initial=0)
    turn(table,mid,FOE);use(combat,table,mid,'Successful poison save',ALLY)
    engine=reload(tmp_path,mid)
    assert [e.payload['success'] for e in engine.events if e.event_type=='SAVE_ROLLED'][-1]
    assert engine.state.actors[OWNER].resources[pool('lotus')]==1


def test_lotus_dew_after_successful_hostile_poison_damage_save_for_ally(tmp_path):
    combat,table,mid=setup(tmp_path,'lotus',initial=0)
    turn(table,mid,FOE);use(combat,table,mid,'Successful poison damage save',ALLY)
    engine=reload(tmp_path,mid)
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED']
    assert saves[-1].payload['success']
    assert engine.state.actors[OWNER].resources[pool('lotus')]==1


def test_lotus_reserve_matches_hostile_poison_damage_save_tag(tmp_path):
    combat,table,mid=setup(tmp_path,'lotus',initial=0)
    turn(table,mid,FOE);use(combat,table,mid,'Successful poison damage save',OWNER)
    engine=reload(tmp_path,mid)
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED']
    assert saves[-1].payload['mode']=='ADVANTAGE'


def test_funeral_ash_after_hostile_attrition_once_per_round(tmp_path):
    combat,table,mid=setup(tmp_path,'ash',initial=0)
    turn(table,mid,FOE);use(combat,table,mid,'Fire damage',OWNER)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources[pool('ash')]==1
    assert engine.state.actors[OWNER].current_hp==55
    use(combat,table,mid,'Fire damage',ALLY)
    assert reload(tmp_path,mid).state.actors[OWNER].resources[pool('ash')]==1
    # Two positive hostile packets do not stack or refresh the no-refresh pool.
    use(combat,table,mid,'Fire damage',OWNER)
    engine=reload(tmp_path,mid)
    gains=[e for e in engine.events if e.event_type=='RESOURCE_GAINED' and e.payload.get('resource_id')==pool('ash')]
    assert len(gains)==1


def test_surge_applies_to_native_attack_and_expires_if_unused(tmp_path):
    combat,table,mid=setup(tmp_path,'bitter')
    use(combat,table,mid,'Heartfire Surge',OWNER)
    use(combat,table,mid,'Native attack',FOE);engine=reload(tmp_path,mid)
    attacks=[e.payload for e in engine.events if e.event_type=='ATTACK_ROLLED']
    assert (attacks[-1].get('mode') or attacks[-1]['roll']['mode'])=='ADVANTAGE'
    assert not any(c.condition_id==BOON+'bitter' for c in engine.state.actors[OWNER].conditions.values())


def test_unused_surge_expires_at_end_of_turn_after_reload(tmp_path):
    combat,table,mid=setup(tmp_path,'bitter')
    use(combat,table,mid,'Heartfire Surge',OWNER)
    assert any(c.condition_id==BOON+'bitter' for c in reload(tmp_path,mid).state.actors[OWNER].conditions.values())
    turn(table,mid,ALLY)
    engine=reload(tmp_path,mid)
    assert not any(c.condition_id==BOON+'bitter' for c in engine.state.actors[OWNER].conditions.values())


@pytest.mark.parametrize('kind,damage_type', [('lotus', 'poison'), ('ash', 'fire'),
                                              ('ash', 'necrotic'), ('ash', 'poison')])
def test_boon_matches_canonical_damage_save_tag_from_friendly_source(tmp_path, kind, damage_type):
    combat,table,mid=setup(tmp_path,kind)
    # This is an actual typed save whose failed consequence deals the tagged
    # damage type. The source is friendly to the boon holder.
    use(combat,table,mid,GROUPS[kind][3],OWNER)
    turn(table,mid,ALLY)
    use(combat,table,mid,'Friendly ' + damage_type.title() + ' pressure',OWNER)
    engine=reload(tmp_path,mid)
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED']
    assert saves[-1].payload['mode']=='ADVANTAGE'
    assert not any(c.condition_id==BOON+kind for c in engine.state.actors[OWNER].conditions.values())


@pytest.mark.parametrize('kind,name,target', [('mirror','Harmless miss',ALLY),('lotus','Harmless poison save',ALLY)])
def test_harmless_rolls_do_not_generate_resources(tmp_path,kind,name,target):
    combat,table,mid=setup(tmp_path,kind,initial=0)
    turn(table,mid,FOE);use(combat,table,mid,name,target)
    assert reload(tmp_path,mid).state.actors[OWNER].resources[pool(kind)]==0


def test_mirror_generation_uses_ally_side_not_the_attacking_foundation_owner(tmp_path):
    combat,table,mid=setup(tmp_path,'mirror',initial=0,opposing_foundation=True)
    turn(table,mid,FOE);use(combat,table,mid,'Test miss',ALLY)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources[pool('mirror')]==1
    assert engine.state.actors[FOE].resources[pool('mirror')]==0


@pytest.mark.parametrize('native', [False, True])
@pytest.mark.parametrize('chosen,cancelled', [(False,False),(True,False),(True,True)])
def test_heartfire_miss_uses_choice_provenance_after_reload(tmp_path,native,chosen,cancelled):
    def extra(bundles):
        from tests.worker2_support import sealed_native_attack
        if native:
            source=sealed_native_attack(bundles[0], 'Provenance miss', attack_bonus=-50)
            row=next(r for r in bundles[0]['action_catalog'] if r['source_definition_id']==source)
            if chosen:
                row['parameters']['chosen_attack_modes']=['DISADVANTAGE']
            else:
                # An imposed penalty needs no provenance marker.
                row['parameters']['unused']=True
        else:
            effect={'type':'attack','attack_kind':'weapon','on_hit':[{'type':'damage','flat':1,'damage_types':['force']} ]}
            if chosen:
                effect['chosen_attack_modes']=['DISADVANTAGE']
            add_action(bundles[0],'Provenance miss',[effect],bonus=-50)
        add_action(bundles[2],'Impose penalty',[{'type':'condition','condition':'poisoned','applies_to':'target',
            'duration':{'kind':'minute'}}],economy='NONE')
        if cancelled:
            add_action(bundles[0],'Countervailing advantage',[{'type':'advantage','on':'next attack roll','applies_to':'self'}],
                target_kind='SELF',economy='NONE')
        for b in bundles:
            b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=setup(tmp_path,'bitter',initial=0,extra=extra)
    if not chosen:
        turn(table,mid,FOE);use(combat,table,mid,'Impose penalty',OWNER)
        assert any(c.condition_id=='condition:typed.poisoned' for c in reload(tmp_path,mid).state.actors[OWNER].conditions.values())
        turn(table,mid,OWNER)
    if cancelled:
        use(combat,table,mid,'Countervailing advantage',OWNER);reload(tmp_path,mid)
    use(combat,table,mid,'Provenance miss',FOE)
    engine=reload(tmp_path,mid)
    event=next(e for e in reversed(engine.events) if e.event_type=='ATTACK_ROLLED' and e.actor_id==OWNER)
    assert not event.payload['provisional_hit']
    assert event.payload['mode']==('NORMAL' if cancelled else 'DISADVANTAGE')
    assert event.payload.get('chosen_attack_modes',[])==(['DISADVANTAGE'] if chosen else [])
    assert engine.state.actors[OWNER].resources[pool('bitter')]==(0 if chosen else 1)


@pytest.mark.parametrize('cancelled', [False,True])
def test_surge_check_friendly_then_hostile_consumes_shared_roll(tmp_path,cancelled):
    def extra(bundles):
        check={'kind':'ability','ability':'STR',**({'mode':'DISADVANTAGE'} if cancelled else {})}
        add_action(bundles[0],'Measured check',[{'type':'contest_against','actor_check':check,
            'target_check':{'kind':'dc','basis':'save_dc'},'on_success':[],'on_fail':[]}],
            target_kind='ANY_CREATURE',economy='NONE')
        add_action(bundles[0],'Follow-up attack',[{'type':'attack','on_hit':[]}],economy='NONE')
    combat,table,mid=setup(tmp_path,'bitter',extra=extra)
    use(combat,table,mid,'Heartfire Surge',OWNER);reload(tmp_path,mid)
    use(combat,table,mid,'Measured check',ALLY)
    engine=reload(tmp_path,mid)
    assert [e.payload['actor']['mode'] for e in engine.events if e.event_type=='CHECK_ROLLED'][-1]==('DISADVANTAGE' if cancelled else 'NORMAL')
    assert any(c.condition_id==BOON+'bitter' for c in engine.state.actors[OWNER].conditions.values())
    use(combat,table,mid,'Measured check',FOE)
    engine=reload(tmp_path,mid)
    assert [e.payload['actor']['mode'] for e in engine.events if e.event_type=='CHECK_ROLLED'][-1]==('NORMAL' if cancelled else 'ADVANTAGE')
    assert not any(c.condition_id==BOON+'bitter' for c in engine.state.actors[OWNER].conditions.values())
    use(combat,table,mid,'Measured check',FOE)
    engine=reload(tmp_path,mid)
    assert [e.payload['actor']['mode'] for e in engine.events if e.event_type=='CHECK_ROLLED'][-1]==('DISADVANTAGE' if cancelled else 'NORMAL')
    use(combat,table,mid,'Follow-up attack',FOE)
    assert [e.payload['mode'] for e in reload(tmp_path,mid).events if e.event_type=='ATTACK_ROLLED'][-1]=='NORMAL'


@pytest.mark.parametrize('cancelled', [False,True])
def test_surge_save_friendly_then_hostile_consumes_shared_roll(tmp_path,cancelled):
    def extra(bundles):
        # The defender's accepted reaction resolves saves on the attacker's own
        # turn, before its attack roll. Two saves prove the single shared grant.
        for b in bundles[1:]:
            b['typed_reactions'].append({'block':'generic','kind':'attacked','feature_id':'test:surge.saves',
                'name':'Test saving throw response','ask':True,'free':True,'range_ft':60,'costs':[],
                'effects':[{'type':'save','ability':'DEX','applies_to':'attacker','dc':15,
                            'on_fail':[],'on_success':[]} for _ in range(2)]})
        add_action(bundles[0],'Probe response',[{'type':'attack','on_hit':[]}],target_kind='ANY_CREATURE',economy='NONE')
        if cancelled:
            add_action(bundles[0],'Save penalty',[{'type':'condition','condition':'bound_balance','applies_to':'self',
                'duration':{'kind':'minute'}}],target_kind='SELF',economy='NONE')
    combat,table,mid=setup(tmp_path,'bitter',extra=extra)
    if cancelled:
        use(combat,table,mid,'Save penalty',OWNER);reload(tmp_path,mid)
    use(combat,table,mid,'Heartfire Surge',OWNER);reload(tmp_path,mid)
    settle(table,mid,candidate(combat,mid,'Probe response',target=ALLY).candidate_id,
        picks={'reaction:test:surge.saves':'first'})
    engine=reload(tmp_path,mid)
    saves=[e.payload['mode'] for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==OWNER]
    assert saves[-2:]==[('DISADVANTAGE' if cancelled else 'NORMAL')]*2
    assert any(c.condition_id==BOON+'bitter' for c in engine.state.actors[OWNER].conditions.values())
    settle(table,mid,candidate(combat,mid,'Probe response',target=FOE).candidate_id,
        picks={'reaction:test:surge.saves':'first'})
    engine=reload(tmp_path,mid)
    saves=[e.payload['mode'] for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==OWNER]
    assert saves[-2:]==[('NORMAL' if cancelled else 'ADVANTAGE'),('DISADVANTAGE' if cancelled else 'NORMAL')]
    assert not any(c.condition_id==BOON+'bitter' for c in engine.state.actors[OWNER].conditions.values())
    assert [e.payload['mode'] for e in engine.events if e.event_type=='ATTACK_ROLLED'][-1]=='NORMAL'


@pytest.mark.parametrize('surge,chosen_penalty,expected', [
    (False, False, 'NORMAL'), (False, True, 'DISADVANTAGE'),
    (True, False, 'ADVANTAGE'), (True, True, 'NORMAL'),
])
def test_portable_attack_hook_composes_before_cancellation_and_is_inert_without_boon(
        tmp_path, monkeypatch, surge, chosen_penalty, expected):
    """Real portable primitive, sealed choice, service commit and cold replay."""
    name = 'Portable strike'
    # Factory actors use typed actions. A test-only effect adapter invokes the
    # actual portable primitive without changing/replacing any engine method.
    # It stays installed for the cold mechanical replay of the sealed action.
    from combat import ext
    from combat.character_runtime_adapter import CharacterCombatRuntimeEngine

    def portable_strike(ctx, effect):
        CharacterCombatRuntimeEngine._resolve_character_attack(
            ctx.engine, ctx.actor, ctx.target, source_id=ctx.source,
            attack_bonus=2, damage=None, damage_type='BLUDGEONING',
            intent=ctx.intent, fixed_damage=2, ranged=False)

    ext.effects()
    monkeypatch.setitem(ext._EFFECTS, 'test_foundations3_portable_strike', portable_strike)

    def delivery(bundles):
        bundle = bundles[0]
        add_action(bundle, name, [{'type': 'test_foundations3_portable_strike'}])
        action = bundle['action_catalog'][-1]
        action['range_ft'] = 5
        if chosen_penalty:
            action['parameters']['chosen_attack_modes'] = ['DISADVANTAGE']
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)

    combat, table, mid = fixture(tmp_path, [], seed='A2GFOU3-portable',
        owner_bundle=owner_bundle('bitter'), bundle_transform=delivery,
        foe_position={'x': 3, 'y': 5})
    if surge:
        use(combat, table, mid, 'Heartfire Surge', OWNER)
        assert any(c.condition_id == BOON+'bitter'
                   for c in reload(tmp_path, mid).state.actors[OWNER].conditions.values())
    use(combat, table, mid, name, FOE)
    engine = reload(tmp_path, mid)
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED'
               and e.source_definition_id == 'action:test.foundations3.worker2-owner.portable_strike']
    assert len(attacks) == 1
    assert attacks[0].payload['mode'] == expected
    assert attacks[0].payload.get('chosen_attack_modes', []) == (
        ['DISADVANTAGE'] if chosen_penalty else [])
    assert not any(c.condition_id == BOON+'bitter'
                   for c in engine.state.actors[OWNER].conditions.values())


# ------------------------------------------------------------------ MGR-T12-lake-temp-hp-1
def lake_bundle(initial=1, stage='Perfected', actor_id=OWNER, cl=5, key_score=14):
    """The Moon-Mirror Still Water owner at a chosen stage, Cultivation Level and Path key ability score."""
    g, resource, slug, _ = GROUPS['mirror']
    doc = sheet(['foundation.' + g + '.' + slug], cl=cl, foundation={
        'foundation_id': g, 'stage': stage, 'resource': {
            'name': resource, 'resource_id': 'tianxia.resource.test', 'maximum': 1, 'current': initial}})
    key = doc['identity']['key_ability']
    for ability in doc['ability_scores_and_statistics']['abilities']:
        if ability['ability'] == key:
            ability['score'] = key_score
            ability['modifier'] = (key_score - 10) // 2
    return compile_character(doc, actor_id=actor_id, reaction_plan={'ask': True})


def lake_setup(tmp_path, *, cl=5, key_score=14, initial=1, bigger_grant=None):
    """A real table match whose owner owns the Perfected Moon-Mirror Lake."""
    def delivery(bundles):
        if bigger_grant is not None:
            add_action(bundles[0], 'Bigger lake grant',
                       [{'type': 'temp_hp', 'flat': bigger_grant, 'applies_to': 'target'}],
                       target_kind='ALLY_OR_SELF')
    return fixture(tmp_path, [], seed='MGR-T12-LAKE-%d-%d-%d' % (cl, key_score, bigger_grant or 0),
                   owner_bundle=lake_bundle(cl=cl, key_score=key_score, initial=initial),
                   bundle_transform=delivery)


def lake_action(engine):
    return next(a for a in engine.action_catalog.values()
                if getattr(a, 'display_name', '') == 'Perfected: Moon-Mirror Lake')


@pytest.mark.parametrize('key_score,key_mod,expected', [(14, 2, 7), (8, -1, 4)])
def test_lake_temp_hp_is_cultivation_level_plus_key_modifier(tmp_path, key_score, key_mod, expected):
    """"Temporary Hit Points equal to your Cultivation Level + your Path key ability modifier"
    is one signed sum of the SOURCE actor's own numbers (CL5 +2 => 7, CL5 -1 => 4), granted
    through the real table service and kept by a current-format cold reload."""
    combat, table, mid = lake_setup(tmp_path, key_score=key_score)
    use(combat, table, mid, 'Perfected: Moon-Mirror Lake', OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp == expected
    grant = [e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED'][-1]
    assert grant.payload['offered'] == expected and grant.target_ids == (OWNER,)
    assert grant.source_definition_id == lake_action(engine).source_definition_id
    # The compiled action carries the owner's own CL and key modifier -- not the ally's (CL15/+2).
    numbers = lake_action(engine).parameters['typed']['numbers']
    assert numbers['cl'] == 5 and numbers['key_mod'] == key_mod


def test_lake_temp_hp_floors_at_zero_when_the_signed_sum_is_not_positive(tmp_path):
    """CL1 with a -2 key modifier sums to -1: one signed sum, so the grant is zero --
    not the per-term clamp (which would keep the 1) and not a negative grant."""
    combat, table, mid = lake_setup(tmp_path, cl=1, key_score=6)
    use(combat, table, mid, 'Perfected: Moon-Mirror Lake', OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp == 0
    grant = [e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED'][-1]
    assert grant.payload['offered'] == 0


def test_lake_temp_hp_replaces_a_smaller_existing_grant(tmp_path):
    """A 6-HP grant is replaced by the lake's printed 7 (CL5/+2): the replacement the
    native temp-HP grant performs, which the old CL-only read (5) would have left at 6."""
    combat, table, mid = lake_setup(tmp_path, key_score=14, bigger_grant=6)
    use(combat, table, mid, 'Bigger lake grant', OWNER)
    use(combat, table, mid, 'Perfected: Moon-Mirror Lake', OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp == 7


def test_lake_temp_hp_keeps_a_larger_existing_grant(tmp_path):
    """A 10-HP grant already held is not reduced by the lake's printed 7."""
    combat, table, mid = lake_setup(tmp_path, key_score=14, bigger_grant=10)
    use(combat, table, mid, 'Bigger lake grant', OWNER)
    use(combat, table, mid, 'Perfected: Moon-Mirror Lake', OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp == 10


# ---------------------------------------------------------------- MGR-T14-ling-open-channels-range-1
def open_channels_setup(tmp_path, *, stage='Refined', ally_position, foe_position=None,
                        arena_transform=None, ally_support=False, reaction=False,
                        support_range=60):
    """A real table whose Origin-Spirit owner at ``stage`` supports an ally
    at a fixed distance. The arena's centre pillar is dropped from the
    straight support ray; a variant puts a wall back on it. ``support_range``
    widens only the test's own support source, never the Foundation's reach."""
    def delivery(bundles):
        add_action(bundles[0], 'Support ally', [{'type': 'temp_hp', 'flat': 7, 'applies_to': 'target'}],
                   target_kind='ALLY_OR_SELF')
        support = bundles[0]['action_catalog'][-1]
        support['range_ft'] = support_range
        support['parameters']['typed']['range_ft'] = support_range
        bundles[0].pop('bundle_sha256', None)
        bundles[0]['bundle_sha256'] = canonical_sha256(bundles[0])
        if ally_support:
            add_action(bundles[1], 'Ally support', [{'type': 'temp_hp', 'flat': 5, 'applies_to': 'target'}],
                       target_kind='ALLY_OR_SELF')
        if reaction:
            bundles[0]['typed_reactions'].append({'block': 'generic', 'kind': 'ally_damaged',
                'feature_id': 'test:foundations3.support_reaction', 'name': 'Support on a reaction',
                'range_ft': 60, 'costs': [], 'effects': [{'type': 'temp_hp', 'flat': 3, 'applies_to': 'ally'}]})
            add_action(bundles[2], 'Enemy strike ally', [{'type': 'attack', 'attack_kind': 'weapon',
                'on_hit': [{'type': 'damage', 'flat': 1, 'damage_types': ['force'], 'applies_to': 'target'}]}],
                bonus=100)
    def battlefield(arena):
        arena['terrain_regions'] = [r for r in arena['terrain_regions'] if r['region_id'] != 'pillar.centre']
        if arena_transform:
            arena_transform(arena)
    return fixture(tmp_path, [], seed='MGR-T14-OCC-' + stage,
                   owner_bundle=owner_bundle('spirit', 0, stage), bundle_transform=delivery,
                   ally_position=ally_position, foe_position=foe_position or {'x': 12, 'y': 8},
                   battlefield_transform=battlefield)


def wall_on_support_ray(arena):
    arena['terrain_regions'].append({'region_id': 'probe.support_wall', 'terrain_type': 'BLOCKED',
        'movement_cost': 0, 'description': 'Stone wall: cannot be entered and blocks line of sight.',
        'cells': [{'x': 7, 'y': 6}, {'x': 8, 'y': 6}]})


def dew_support_grants(engine):
    return [e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED']


def test_spirit_dew_open_channels_reaches_45_feet_with_clear_line(tmp_path):
    """Refined Open Channels: a 45-foot outward temp-HP grant generates
    Spirit-Source Dew through the real table -- the printed 30 feet
    would not reach an ally that far."""
    combat, table, mid = open_channels_setup(tmp_path, ally_position={'x': 12, 'y': 6})
    use(combat, table, mid, 'Support ally', ALLY)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('spirit')] == 1
    grant = dew_support_grants(engine)[-1]
    assert grant.actor_id == OWNER and ALLY in grant.target_ids


@pytest.mark.parametrize('ally_x,expected', [(12, 0), (9, 1)])
def test_spirit_dew_without_open_channels_keeps_30_feet(tmp_path, ally_x, expected):
    """Awakened (no rider): the same 45-foot grant generates nothing,
    and the 30-foot boundary still generates -- unchanged."""
    combat, table, mid = open_channels_setup(tmp_path, stage='Awakened',
                                             ally_position={'x': ally_x, 'y': 6})
    use(combat, table, mid, 'Support ally', ALLY)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('spirit')] == expected


@pytest.mark.parametrize('walled', [False, True])
def test_spirit_dew_open_channels_reaction_needs_clear_line(tmp_path, walled):
    """The enemy-turn reaction grant at 45 feet generates Dew with a clear
    path; a wall on that path -- which still lets the temp HP land --
    blocks it: the rider's 60 feet is clear-line-of-effect only."""
    combat, table, mid = open_channels_setup(tmp_path, ally_position={'x': 12, 'y': 6},
                                             arena_transform=wall_on_support_ray if walled else None,
                                             reaction=True)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Enemy strike ally', target=ALLY).candidate_id,
           picks={'reaction:test:foundations3.support_reaction': 'first'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('spirit')] == (0 if walled else 1)
    grants = [e for e in dew_support_grants(engine)
              if e.source_definition_id == 'test:foundations3.support_reaction']
    assert grants and grants[-1].actor_id == OWNER and ALLY in grants[-1].target_ids


def test_spirit_dew_open_channels_stops_beyond_60_feet(tmp_path):
    """A 120-foot support source still lands at 65 feet, but the rider's
    generation range stops at 60: no Dew past it."""
    combat, table, mid = open_channels_setup(tmp_path, ally_position={'x': 16, 'y': 6},
                                             support_range=120)
    use(combat, table, mid, 'Support ally', ALLY)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('spirit')] == 0
    assert dew_support_grants(engine)


def test_spirit_dew_open_channels_self_only_support_never_generates(tmp_path):
    """Self-only sustain never generates Dew, rider or not."""
    combat, table, mid = open_channels_setup(tmp_path, ally_position={'x': 12, 'y': 6})
    use(combat, table, mid, 'Support ally', OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('spirit')] == 0


def test_spirit_dew_open_channels_nonowner_support_generates_nothing(tmp_path):
    """A supporter without the Foundation generates no Dew at 45 feet:
    only the owner's own outward support credits the resource."""
    combat, table, mid = open_channels_setup(tmp_path, ally_support=True,
                                             ally_position={'x': 12, 'y': 6})
    turn(table, mid, ALLY)
    use(combat, table, mid, 'Ally support', OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('spirit')] == 0
# ------------------------------------------------------------------ MGR-T14-ling-pulse-sum-1
def pulse_bundle(initial=1, stage='Awakened', actor_id=OWNER, pb=2, key_score=14):
    """The Origin-Spirit Body owner at a chosen Proficiency Bonus and Path key ability score."""
    g, resource, slug, _ = GROUPS['spirit']
    doc = sheet(['foundation.' + g + '.' + slug], foundation={
        'foundation_id': g, 'stage': stage, 'resource': {
            'name': resource, 'resource_id': 'tianxia.resource.test', 'maximum': 1, 'current': initial}})
    doc['identity']['proficiency_bonus'] = pb
    key = doc['identity']['key_ability']
    for ability in doc['ability_scores_and_statistics']['abilities']:
        if ability['ability'] == key:
            ability['score'] = key_score
            ability['modifier'] = (key_score - 10) // 2
    return compile_character(doc, actor_id=actor_id, reaction_plan={'ask': True})


def pulse_setup(tmp_path, *, pb=2, key_score=14, initial=1, bigger_grant=None):
    """A real table match whose owner owns Gentle Source Pulse."""
    def delivery(bundles):
        if bigger_grant is not None:
            add_action(bundles[0], 'Bigger pulse grant',
                       [{'type': 'temp_hp', 'flat': bigger_grant, 'applies_to': 'target'}],
                       target_kind='ALLY_OR_SELF')
    return fixture(tmp_path, [], seed='MGR-T14-PULSE-%d-%d-%d' % (pb, key_score, bigger_grant or 0),
                   owner_bundle=pulse_bundle(pb=pb, key_score=key_score, initial=initial),
                   bundle_transform=delivery)


def pulse_action(engine):
    return next(a for a in engine.action_catalog.values()
                if getattr(a, 'display_name', '') == 'Gentle Source Pulse')


@pytest.mark.parametrize('key_score,key_mod,expected,target', [
    (14, 2, 4, OWNER), (8, -1, 1, OWNER), (8, -1, 1, ALLY)])
def test_gentle_source_pulse_temp_hp_is_pb_plus_key_modifier(tmp_path, key_score, key_mod, expected, target):
    """"Temporary Hit Points equal to your Proficiency Bonus + your Path key ability modifier"
    is one signed sum of the SOURCE actor's own numbers (PB2 +2 => 4, PB2 -1 => 1), granted
    through the real table service, paid in Spirit-Source Dew and kept by a cold reload."""
    combat, table, mid = pulse_setup(tmp_path, key_score=key_score)
    # Measure Pulse's printed amount separately from Origin-Spirit Vessel's
    # optional outward-support bonus. The shared driver's default accepts it.
    use(combat, table, mid, 'Gentle Source Pulse', target,
        picks={'choice:needle.origin_spirit_support_value': None})
    engine = reload(tmp_path, mid)
    assert not any(e.payload.get('receipt_kind') == 'origin_spirit_support_value'
                   for e in engine.events)
    assert engine.state.actors[target].temporary_hp == expected
    grants = [e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED']
    assert len(grants) == 1
    grant = grants[0]
    assert grant.payload['offered'] == expected and grant.target_ids == (target,)
    assert grant.source_definition_id == pulse_action(engine).source_definition_id
    effects = pulse_action(engine).parameters['typed']['effects']
    # Pulse's willing-recipient container preserves the single signed grant.
    from combat.effect_harm import rows
    amounts = [effect for effect in rows(effects) if effect['type'] == 'temp_hp']
    assert len(amounts) == 1
    assert amounts[0]['formula'] == 'text:your proficiency bonus + your path key ability modifier'
    if target != OWNER:
        assert engine.state.actors[OWNER].temporary_hp == 0
    # Payment precedes the grant. Outward support then regenerates Dew under
    # Generate Spirit-Source Dew; the final balance alone cannot prove payment.
    payments = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
                and e.actor_id == OWNER and e.source_definition_id == grant.source_definition_id
                and e.payload.get('resource_id') == pool('spirit')]
    assert len(payments) == 1
    assert payments[0].payload['amount'] == 1 and payments[0].payload['remaining'] == 0
    assert payments[0].sequence < grant.sequence
    generation = [e for e in engine.events if e.event_type == 'RESOURCE_GAINED'
                  and e.actor_id == OWNER and e.payload.get('resource_id') == pool('spirit')]
    if target == ALLY:
        assert len(generation) == 1
        assert generation[0].source_definition_id == (
            'passive:foundation.origin_spirit_body_v0_2B.generate_spirit_source_dew')
        assert generation[0].payload['gained'] == 1
        assert grant.sequence < generation[0].sequence
    else:
        assert generation == []
    assert engine.state.actors[OWNER].resources[pool('spirit')] == (1 if target == ALLY else 0)
    assert engine.state.actors[OWNER].bonus_action_available is False
    # The compiled action carries the owner's own PB and key modifier.
    numbers = pulse_action(engine).parameters['typed']['numbers']
    assert numbers['pb'] == 2 and numbers['key_mod'] == key_mod


@pytest.mark.parametrize('accept,expected', [(False, 20), (True, 24)])
def test_foundation_amount_driver_preserves_optional_support_choice(tmp_path, accept, expected):
    """An amount test can decline Vessel without suppressing the legal bonus.

    Use the native Life producer supported on main as well as integration:
    Pulse's own Vessel support is introduced by the sibling parent lane.
    """
    # This native ownership row is loaded from a runtime directory, beyond
    # the base feature map. Retain it in reduced snapshots of this fixture.
    from tests.h1_support import ROOT
    value_rows = json.loads((ROOT / 'combat/rules/feature_blocks.d/mgr_t14_spirit_vessel_value.json').read_text())['features']
    assert value_rows['foundation.origin_spirit_body_v0_2B.origin_spirit_vessel']['block'] == 'foundations3_spirit_value'

    combat, table, mid = fixture(tmp_path, [
        'tianxia.talent.life.greater_invigorate',
        'foundation.origin_spirit_body_v0_2B.origin_spirit_vessel'],
        seed='MGR-T14-PULSE-OPTIONAL-SUPPORT')
    choice = 'choice:needle.origin_spirit_support_value'
    prompts = use(combat, table, mid, 'Borrowed Breath + Greater Invigorate', ALLY,
                  picks={choice: 'increase' if accept else None})
    engine = reload(tmp_path, mid)
    assert any(p['context']['reaction_source_id'] == choice for p in prompts)
    assert engine.state.actors[ALLY].temporary_hp == expected
    receipts = [e for e in engine.events
                if e.payload.get('receipt_kind') == 'origin_spirit_support_value']
    assert len(receipts) == int(accept)
    if accept:
        assert receipts[0].payload['bonus'] == 4
        assert receipts[0].target_ids == (ALLY,)
    else:
        assert 'foundation_round_origin_spirit_support_value' not in engine.state.actors[OWNER].turn_flags


def test_gentle_source_pulse_temp_hp_floors_at_zero_when_the_signed_sum_is_not_positive(tmp_path):
    """PB2 with a -3 key modifier sums to -1: one signed sum, so the grant is zero --
    not the per-term clamp (which would keep the 2) and not a negative grant."""
    combat, table, mid = pulse_setup(tmp_path, key_score=4)
    use(combat, table, mid, 'Gentle Source Pulse', OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp == 0
    grant = [e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED'][-1]
    assert grant.payload['offered'] == 0


def test_gentle_source_pulse_temp_hp_replaces_a_smaller_existing_grant(tmp_path):
    """Replacement-contract guard: the native grant replaces 3 HP with 4 (PB2/+2).
    The old folded positive terms also granted 4; negative-key cases catch the bug."""
    combat, table, mid = pulse_setup(tmp_path, key_score=14, bigger_grant=3)
    use(combat, table, mid, 'Bigger pulse grant', OWNER)
    use(combat, table, mid, 'Gentle Source Pulse', OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp == 4


def test_gentle_source_pulse_temp_hp_keeps_a_larger_existing_grant(tmp_path):
    """A 10-HP grant already held is not reduced or raised by the pulse's printed 4 (PB2/+2):
    an independent higher grant survives the pulse untouched."""
    combat, table, mid = pulse_setup(tmp_path, key_score=14, bigger_grant=10)
    use(combat, table, mid, 'Bigger pulse grant', OWNER)
    use(combat, table, mid, 'Gentle Source Pulse', OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp == 10
