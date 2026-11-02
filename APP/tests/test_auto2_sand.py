"""Printed Sand mechanics through table execute_intent and cold service replay."""
import pytest
from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, settle, turn, sealed_native_attack
from tests.test_auto50_sand import prepare_sand
WARD='TAL_SAND_ABRADING_WARD'
EDGE='TAL_SAND_GLASS_EDGE_SCRIPTURE'
STORM='TAL_SAND_THOUSAND_MILE_SANDSTORM_BODY'

def prepare(bundles):
    prepare_sand(bundles)
    add_action(bundles[0], 'Prepare Burial', [{'type':'sand_bury','applies_to':'target','duration':'one_minute'}])
    for b in bundles:
        source = sealed_native_attack(b, 'Native Sand Bow', range_ft=120, attack_bonus=20, count=1, sides=2, modifier=0)
        next(a for a in b['action_catalog'] if a['source_definition_id'] == source)['parameters']['attack_kind'] = 'weapon_ranged'
        seal(b)
        add_action(b, 'Sand Test Bow', [{'type':'attack','attack_kind':'weapon_ranged','on_hit':[{'type':'damage','applies_to':'target','flat':1,'damage_types':['piercing']}]}], typed={'weapon':{'kind':'ranged','ability_modifier':2},'range_ft':120,'numbers':{'pb':5,'key_mod':2,'attack_bonus':20}})

def foe_turn(table, mid, picks):
    prompts=[]
    for _ in range(12):
        if table.state(mid)['menu']['actor_id']==FOE: return prompts
        prompts+=settle(table,mid,table.state(mid)['menu']['end_turn'],picks)
    raise AssertionError('No foe turn')

@pytest.mark.parametrize('kind',['slashing','piercing'])
def test_ward_glass_type_commit_reload_next_round(tmp_path,kind):
    combat,table,mid=fixture(tmp_path,[WARD,EDGE],bundle_transform=prepare)
    settle(table,mid,candidate(combat,mid,'Prepare Sand Terrain').candidate_id)
    e=reload(tmp_path,mid);hp=e.state.actors[FOE].current_hp;cp=e.state.actors[OWNER].resources.copy()
    picks={'choice:needle.sand_ward':'use','choice:needle.glass_edge_ward_type':kind}
    prompts=foe_turn(table,mid,picks);e=reload(tmp_path,mid)
    hits=[x for x in e.events if x.event_type=='DAMAGE_COMMITTED' and x.source_definition_id==WARD]
    assert len(hits)==1 and hits[0].payload['damage_type']==kind.upper()
    assert hp-e.state.actors[FOE].current_hp==e.state.actors[OWNER].proficiency_bonus
    assert e.state.actors[OWNER].resources==cp
    assert any(p['context']['reaction_source_id']=='choice:needle.glass_edge_ward_type' for p in prompts)
    assert not any(ALLY in x.target_ids for x in hits)
    turn(table,mid,OWNER);foe_turn(table,mid,picks);e=reload(tmp_path,mid)
    assert len([x for x in e.events if x.event_type=='DAMAGE_COMMITTED' and x.source_definition_id==WARD])==2

@pytest.mark.parametrize('owned,use',[(True,False),(False,True)])
def test_ward_decline_and_nonowner(tmp_path,owned,use):
    combat,table,mid=fixture(tmp_path,[WARD,EDGE] if owned else [WARD],bundle_transform=prepare)
    settle(table,mid,candidate(combat,mid,'Prepare Sand Terrain').candidate_id)
    hp=reload(tmp_path,mid).state.actors[FOE].current_hp
    prompts=foe_turn(table,mid,{'choice:needle.sand_ward':'use' if use else None});e=reload(tmp_path,mid)
    hits=[x for x in e.events if x.event_type=='DAMAGE_COMMITTED' and x.source_definition_id==WARD]
    assert bool(hits)==use
    assert not any(p['context']['reaction_source_id']=='choice:needle.glass_edge_ward_type' for p in prompts)
    if use: assert hits[-1].payload['damage_type']=='SLASHING'
    else: assert e.state.actors[FOE].current_hp==hp

def test_ward_buried_grains_use_sealed_pb_key_and_expire(tmp_path):
    combat,table,mid=fixture(tmp_path,[WARD,EDGE],bundle_transform=prepare)
    settle(table,mid,candidate(combat,mid,'Prepare Sand Terrain').candidate_id)
    settle(table,mid,candidate(combat,mid,'Prepare Burial',target=FOE).candidate_id)
    foe_turn(table,mid,{'choice:needle.sand_ward':'use','choice:needle.glass_edge_ward_type':'piercing','choice:needle.glass_edge_cling':'cling'})
    e=reload(tmp_path,mid)
    grains=next(c for c in e.state.actors[FOE].conditions.values() if c.condition_id=='condition:typed.sand_glass_grains')
    row=next(r for r in e.typed_passive_rows[OWNER] if r.get('block')=='glass_edge')
    assert grains.data['amount']==row['pb']+row['key_mod']
    turn(table,mid,OWNER)
    assert not any(c.condition_id=='condition:typed.sand_glass_grains' for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())

@pytest.mark.parametrize('chosen,attacker,expected',[([ALLY],ALLY,'NORMAL'),([],ALLY,'DISADVANTAGE'),([FOE],FOE,'NORMAL'),([],FOE,'DISADVANTAGE')])
@pytest.mark.parametrize('native', [False, True])
def test_storm_designations_drive_real_attack_after_reload(tmp_path,chosen,attacker,expected,native):
    combat,table,mid=fixture(tmp_path,[STORM],owner_dc=-100,bundle_transform=prepare)
    prompts=settle(table,mid,candidate(combat,mid,'Thousand-Mile Sandstorm Body').candidate_id,{'choice:needle.sandstorm_designated':chosen or None})
    e=reload(tmp_path,mid)
    zone=next(z for z in e.state.zones.values() if z.active and 'THOUSAND_MILE' in z.source_definition_id)
    assert zone.trigger_profile['profile']['ranged_exempt']==chosen
    assert any(p['context']['reaction_source_id']=='choice:needle.sandstorm_designated' for p in prompts)
    turn(table,mid,attacker)
    settle(table,mid,candidate(combat,mid,'Native Sand Bow' if native else 'Sand Test Bow',target=FOE if attacker==ALLY else ALLY).candidate_id)
    e=reload(tmp_path,mid)
    roll=next(x for x in reversed(e.events) if x.event_type=='ATTACK_ROLLED' and x.actor_id==attacker)
    assert roll.payload['mode']==expected


@pytest.mark.parametrize('native', [False, True])
def test_storm_does_not_penalize_a_ranged_cultivation_attack(tmp_path, native):
    def spells(bundles):
        prepare(bundles)
        for bundle in bundles:
            for action in bundle['action_catalog']:
                if action['display_name'] == 'Native Sand Bow':
                    action['parameters']['attack_kind'] = 'cultivation'
                if action['display_name'] == 'Sand Test Bow':
                    action['parameters']['typed']['effects'][0]['attack_kind'] = 'cultivation'
            seal(bundle)
    combat,table,mid=fixture(tmp_path,[STORM],owner_dc=-100,bundle_transform=spells)
    settle(table,mid,candidate(combat,mid,'Thousand-Mile Sandstorm Body').candidate_id,
           {'choice:needle.sandstorm_designated':None})
    turn(table,mid,ALLY)
    settle(table,mid,candidate(combat,mid,'Native Sand Bow' if native else 'Sand Test Bow',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    roll=next(x for x in reversed(e.events) if x.event_type=='ATTACK_ROLLED' and x.actor_id==ALLY)
    assert roll.payload['mode']=='NORMAL'


@pytest.mark.parametrize('cl,legacy', [(4,False),(15,True)])
def test_ward_glass_choice_respects_construction_gate_and_frozen_rows(tmp_path,cl,legacy):
    def saved_rows(bundles):
        prepare(bundles)
        if legacy:
            for row in bundles[0]['typed_passives']:
                row.pop('ward_optional',None)
                row.pop('ward_choice',None)
            seal(bundles[0])
    combat,table,mid=fixture(tmp_path,[WARD,EDGE],cl=cl,bundle_transform=saved_rows)
    settle(table,mid,candidate(combat,mid,'Prepare Sand Terrain').candidate_id)
    prompts=foe_turn(table,mid,{'choice:needle.sand_ward':'use'})
    e=reload(tmp_path,mid)
    hit=next(x for x in reversed(e.events) if x.event_type=='DAMAGE_COMMITTED' and x.source_definition_id==WARD)
    assert hit.payload['damage_type']=='SLASHING'
    assert not any(p['context']['reaction_source_id']=='choice:needle.glass_edge_ward_type' for p in prompts)
    if legacy: assert not any(p['context']['reaction_source_id']=='choice:needle.sand_ward' for p in prompts)


def test_glass_grains_from_ward_deal_printed_damage_on_committed_movement(tmp_path):
    combat,table,mid=fixture(tmp_path,[WARD,EDGE],bundle_transform=prepare)
    settle(table,mid,candidate(combat,mid,'Prepare Sand Terrain').candidate_id)
    settle(table,mid,candidate(combat,mid,'Prepare Burial',target=FOE).candidate_id)
    foe_turn(table,mid,{'choice:needle.sand_ward':'use','choice:needle.glass_edge_ward_type':'piercing','choice:needle.glass_edge_cling':'cling'})
    e=reload(tmp_path,mid)
    held=next(c for c in e.state.actors[FOE].conditions.values() if c.condition_id=='condition:typed.sand_glass_grains')
    hp=e.state.actors[FOE].current_hp
    move=next(c for c in combat._load_session(mid).engine.legal_candidates() if c.actor_id==FOE and c.kind=='MOVE' and c.movement_cost_ft>=5)
    settle(table,mid,move.candidate_id)
    e=reload(tmp_path,mid)
    assert hp-e.state.actors[FOE].current_hp==held.data['amount']
    assert not any(c.condition_id=='condition:typed.sand_glass_grains' for c in e.state.actors[FOE].conditions.values())


def test_manual_player_still_decides_ward_with_auto_reaction_plan(tmp_path):
    combat,table,mid=fixture(tmp_path,[WARD,EDGE],ask=False,bundle_transform=prepare)
    settle(table,mid,candidate(combat,mid,'Prepare Sand Terrain').candidate_id)
    prompts=foe_turn(table,mid,{'choice:needle.sand_ward':'use','choice:needle.glass_edge_ward_type':'piercing'})
    e=reload(tmp_path,mid)
    assert any(x.event_type=='DAMAGE_COMMITTED' and x.source_definition_id==WARD and x.payload['damage_type']=='PIERCING' for x in e.events)
    assert {p['context']['reaction_source_id'] for p in prompts} >= {'choice:needle.sand_ward','choice:needle.glass_edge_ward_type'}


@pytest.mark.parametrize('target,relation_name,damaged',[(FOE,'NEUTRAL',False),(FOE,'ALLY',False),(ALLY,'ENEMY',True)])
def test_new_ward_obeys_current_relations(tmp_path,target,relation_name,damaged):
    combat,table,mid=fixture(tmp_path,[WARD,EDGE],bundle_transform=prepare)
    settle(table,mid,candidate(combat,mid,'Prepare Sand Terrain').candidate_id)
    for actor in (FOE,ALLY):
        state=combat._load_session(mid).engine.state
        combat.change_relations(mid,change={'kind':'ACTOR_RELATION','subject':OWNER,'other':actor,
                'relation':relation_name if actor==target else 'ALLY'},expected_state_version=state.state_version)
    for _ in range(12):
        if table.state(mid)['menu']['actor_id']==target:break
        settle(table,mid,table.state(mid)['menu']['end_turn'],{'choice:needle.sand_ward':'use','choice:needle.glass_edge_ward_type':'piercing'})
    else:raise AssertionError('No target turn')
    e=reload(tmp_path,mid)
    hits=[x for x in e.events if x.event_type=='DAMAGE_COMMITTED' and x.source_definition_id==WARD and target in x.target_ids]
    assert bool(hits)==damaged
    if damaged:assert hits[-1].payload['damage_type']=='PIERCING'


@pytest.mark.parametrize('native,ranged,weapon',[(False,True,True),(True,True,True),(False,False,True),(True,False,True),(False,True,False)])
def test_storm_uses_delivery_not_short_range_or_catalog_reach(tmp_path,native,ranged,weapon):
    def packets(bundles):
        prepare(bundles)
        for bundle in bundles:
            for action in bundle['action_catalog']:
                if action['display_name']=='Native Sand Bow':
                    action['range_ft']=5 if ranged else None
                    action['reach_ft']=None if ranged else 5
                    action['parameters']['attack_kind']='weapon_ranged' if ranged else 'weapon_melee'
                if action['display_name']=='Sand Test Bow':
                    typed=action['parameters']['typed']
                    typed['range_ft']=5 if ranged else None
                    typed['effects'][0]['attack_kind']='weapon_ranged' if ranged else 'weapon_melee'
                    if not weapon:typed.pop('weapon',None)
            seal(bundle)
    combat,table,mid=fixture(tmp_path,[STORM],owner_dc=-100,bundle_transform=packets,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':5,'y':6}})
    settle(table,mid,candidate(combat,mid,'Thousand-Mile Sandstorm Body').candidate_id,{'choice:needle.sandstorm_designated':None})
    turn(table,mid,ALLY)
    settle(table,mid,candidate(combat,mid,'Native Sand Bow' if native else 'Sand Test Bow',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    roll=next(x for x in reversed(e.events) if x.event_type=='ATTACK_ROLLED' and x.actor_id==ALLY)
    assert roll.payload['mode']==('DISADVANTAGE' if ranged else 'NORMAL')


def test_frozen_storm_preserves_legacy_team_exemption(tmp_path):
    range_ft=120
    def legacy(bundles):
        prepare(bundles)
        for bundle in bundles:
            for action in bundle['action_catalog']:
                typed=action['parameters'].get('typed') or {}
                if typed.get('zone_spec'):
                    typed['zone_spec'].get('profile',{}).pop('sand_designation',None)
                if action['display_name']=='Sand Test Bow':typed['range_ft']=range_ft
            seal(bundle)
    combat,table,mid=fixture(tmp_path,[STORM],owner_dc=-100,bundle_transform=legacy,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':6,'y':6}})
    prompts=settle(table,mid,candidate(combat,mid,'Thousand-Mile Sandstorm Body').candidate_id)
    assert not any(p['context']['reaction_source_id']=='choice:needle.sandstorm_designated' for p in prompts)
    turn(table,mid,ALLY)
    settle(table,mid,candidate(combat,mid,'Sand Test Bow',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    roll=next(x for x in reversed(e.events) if x.event_type=='ATTACK_ROLLED' and x.actor_id==ALLY)
    assert roll.payload['mode']=='NORMAL'


def test_glass_grains_respect_printed_construction_level(tmp_path):
    combat,table,mid=fixture(tmp_path,[EDGE],cl=4,owner_dc=100,bundle_transform=prepare)
    settle(table,mid,candidate(combat,mid,'Prepare Sand Terrain').candidate_id)
    settle(table,mid,candidate(combat,mid,'Prepare Burial',target=FOE).candidate_id)
    prompts=settle(table,mid,candidate(combat,mid,'Scouring Hand: Reduce Speed',target=FOE).candidate_id,
                   {'choice:needle.glass_edge_cling':'cling'})
    e=reload(tmp_path,mid)
    assert any(x.event_type=='DAMAGE_COMMITTED' and FOE in x.target_ids and x.payload['hp_damage']>0 for x in e.events)
    assert not any(p['context']['reaction_source_id']=='choice:needle.glass_edge_cling' for p in prompts)
    assert not any(c.condition_id=='condition:typed.sand_glass_grains' for c in e.state.actors[FOE].conditions.values())
