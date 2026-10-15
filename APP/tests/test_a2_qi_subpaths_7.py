"""Printed Qi subpath combat effects through service transactions and reload."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import pytest
from combat.canonical import canonical_sha256
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload

BASE = 'tianxia.subpath.qi.hearthfire_cultivator.feature.'
HEARTH = BASE + 'kindled_hearth'
RECOVERY = BASE + 'homefire_recovery'
CARRY = BASE + 'carry_the_hearth'


def controls(bundles):
    for bundle in bundles:
        aid=bundle['actor_id']
        bundle['actor_template']['maximum_hp']=500
        for name, effects in [
            ('Force damage', [{'type':'damage','applies_to':'target','flat':40,'damage_types':['force']}]),
            ('Lethal damage', [{'type':'damage','applies_to':'target','flat':1200,'damage_types':['force']}]),
            ('Poison damage', [{'type':'damage','applies_to':'target','flat':40,'damage_types':['poison']}]),
            ('Frightened save', [{'type':'save','applies_to':'target','ability':'wis','on_fail':[
                {'type':'condition','condition':'frightened','applies_to':'target','duration':'until_start_of_next_turn'}], 'on_success':[]}]),
            ('Fire save', [{'type':'save','applies_to':'target','ability':'dex','on_fail':[
                {'type':'damage','applies_to':'target','flat':1,'damage_types':['fire']}], 'on_success':[]}]),
            ('Poison resistance', [{'type':'resistance','applies_to':'self','damage_types':['poison'], 'duration':'one_minute'}]),
            ('Destroy Hearth', [{'type':'object_damage','flat':1000,'damage_types':['force'],'threshold_zero':True}]),
        ]:
            sid='action:test.'+aid+'.'+name.replace(' ','_')
            action=ActionDefinition(source_definition_id=sid,owner_id=aid,display_name=name,
                economy=EconomyKind.BONUS_ACTION,
                resolution_kind='TYPED',target_kind='SELF' if name=='Poison resistance' else 'OBJECT' if name=='Destroy Hearth' else 'HOSTILE_ENTITY',
                range_ft=60,parameters={'typed':{'source':sid,'numbers':{'cl':18,'pb':6,'key_mod':4,'save_dc':18},
                                              'effects':deepcopy(effects),'duration':{'kind':'instant'},'riders':[]}})
            bundle['action_catalog'].append(action.model_dump(mode='json'))
            bundle['actor_template']['action_ids'].append(sid)
        if aid == OWNER:
            for row in bundle['action_catalog']:
                if row.get('display_name') == 'Kindled Hearth':
                    row['parameters']['typed']['numbers']['potency'] = 4
        bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)


def controls_ally_foe_owner(bundles):
    """Give the round-stamp regression deterministic Ally -> foe -> owner order."""
    controls(bundles)
    bonuses = {ALLY: 100, FOE: 50, OWNER: -100}
    for bundle in bundles:
        bundle['actor_template']['initiative_bonus'] = bonuses[bundle['actor_id']]
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)


def test_qi_subpath_descriptions_name_the_mechanics_and_rest_choices():
    path=Path(__file__).resolve().parents[1]/'authority/typed_mechanics/reviewed_final.d/zz_a2_qi_subpaths_7.json'
    records=json.loads(path.read_text())['mechanics']
    hearth=' '.join(records[HEARTH]['description'])
    recovery=' '.join(records[RECOVERY]['riders']+records[RECOVERY]['description'])
    carry=' '.join(records[CARRY]['description'])
    assert 'Advantage on saving throws' in hearth and '8 hours' in hearth
    assert 'twice your Proficiency Bonus' in recovery
    assert 'end one level of Exhaustion' in recovery
    assert 'your next save against being Frightened' in recovery
    assert 'end one ordinary environmental penalty' in recovery
    assert 'once per long rest' in recovery
    assert 'Temporary Hit Points equal to your Proficiency Bonus' in carry
    assert 'half damage on a success' in carry
    assert 'Shield the Flame reduces damage by 2d8' in carry
    assert not any('PB' in text for text in (hearth, recovery, carry))


def fight(tmp_path, *, cl=18, carry=False, dc=18, ask=True, recipients=None, foe_position=None,
          bundle_transform=controls):
    features=[HEARTH,RECOVERY]+([CARRY] if carry else [])
    combat,table,mid=fixture(tmp_path,[],cl=cl,owner_features=features,owner_pb=6,
        owner_dc=dc,seed='HEARTH-'+str(cl),ask=ask,foe_position=foe_position,bundle_transform=bundle_transform)
    selection = {'choice:needle.kindled_hearth_recipients': recipients} if recipients is not None else None
    settle(table,mid,candidate(combat,mid,'Kindled Hearth',at=(5,6)).candidate_id, choices=selection)
    engine=reload(tmp_path,mid)
    obj=next(o for o in engine.state.objects.values() if (o.component or {}).get('name')=='Kindled Hearth')
    assert obj.ac==13 and obj.maximum_hp==3*cl
    assert set(obj.damage_immunities)=={'FIRE','POISON','PSYCHIC'}
    assert engine.state.actors[OWNER].resources['resource:core.qi']==99
    return combat,table,mid


@pytest.mark.parametrize('cl,count',[(6,1),(14,2),(18,3)])
def test_shield_paid_reaction_scales_and_reloads(tmp_path,cl,count):
    combat,table,mid=fight(tmp_path,cl=cl)
    turn(table,mid,FOE)
    prompts=settle(table,mid,candidate(combat,mid,'Force damage',target=ALLY).candidate_id,
        choices={'choice:needle.hearth_shield':'shield'})
    engine=reload(tmp_path,mid)
    owner=engine.state.actors[OWNER]
    roll=next(r for r in engine.rolls if r.reason=='HEARTH_SHIELD_REDUCTION')
    assert roll.expression.startswith(str(count)+'d8')
    resolved=next(e for e in engine.events if e.event_type=='REACTION_RESOLVED' and e.source_definition_id==RECOVERY)
    assert engine.state.actors[ALLY].current_hp==500-40+resolved.payload['reduction']
    assert owner.resources['resource:core.qi']==98 and not owner.reaction_available
    assert owner.turn_flags['hearth_shield_round_use']==engine.state.round_number
    assert any(p['context']['reactor_id']==OWNER for p in prompts)


def test_declining_shield_preserves_qi_reaction_and_rolls(tmp_path):
    combat,table,mid=fight(tmp_path)
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Force damage',target=ALLY).candidate_id,
        choices={'choice:needle.hearth_shield':None})
    engine=reload(tmp_path,mid)
    assert engine.state.actors[ALLY].current_hp==460
    assert engine.state.actors[OWNER].reaction_available
    assert engine.state.actors[OWNER].resources['resource:core.qi']==99
    assert not any(r.reason=='HEARTH_SHIELD_REDUCTION' for r in engine.rolls)


def test_shield_round_stamp_survives_owner_turn_start_and_cold_reload(tmp_path):
    """The turn-start retained-key rule must not erase a live round limit."""
    combat,table,mid=fight(tmp_path,bundle_transform=controls_ally_foe_owner)
    assert reload(tmp_path,mid).state.initiative_order == [ALLY, FOE, OWNER]
    turn(table,mid,ALLY)
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Force damage',target=ALLY).candidate_id,
        choices={'choice:needle.hearth_shield':'shield'})
    first=reload(tmp_path,mid)
    stamp=first.state.actors[OWNER].turn_flags['hearth_shield_round_use']
    turn(table,mid,OWNER)
    after_start=reload(tmp_path,mid)
    assert after_start.state.round_number == stamp, 'the owner starts later in the same round'
    assert after_start.state.actors[OWNER].turn_flags['hearth_shield_round_use']==stamp


def test_shield_is_after_resistance_and_before_temporary_hp(tmp_path):
    combat,table,mid=fight(tmp_path,carry=True)
    settle(table,mid,candidate(combat,mid,'Carry the Hearth').candidate_id,
           choices={'choice:needle.carry_hearth':OWNER})
    turn(table,mid,ALLY)
    settle(table,mid,candidate(combat,mid,'Poison resistance').candidate_id)
    assert reload(tmp_path,mid).state.actors[ALLY].temporary_hp == 6
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Poison damage',target=ALLY).candidate_id,
        choices={'choice:needle.hearth_shield':'shield'})
    engine=reload(tmp_path,mid)
    receipt=next(e for e in engine.events if e.event_type=='REACTION_RESOLVED' and e.source_definition_id==RECOVERY)
    assert 0<receipt.payload['reduction']<=20
    assert engine.state.actors[ALLY].current_hp==500
    assert engine.state.actors[ALLY].temporary_hp==6-(20-receipt.payload['reduction'])


def test_hearth_save_aura_affects_only_chosen_allies_after_reload(tmp_path):
    combat,table,mid=fight(tmp_path,recipients=[OWNER])
    zone=next(z for z in reload(tmp_path,mid).state.zones.values()
              if z.trigger_profile.get('profile',{}).get('hearth_object'))
    assert zone.trigger_profile['profile']['chosen_recipients']==[OWNER]
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Frightened save',target=ALLY).candidate_id)
    engine=reload(tmp_path,mid)
    assert [e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==ALLY][-1].payload['mode']=='NORMAL'
    turn(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Frightened save',target=FOE).candidate_id)
    engine=reload(tmp_path,mid)
    assert [e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==FOE][-1].payload['mode']=='NORMAL'
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Frightened save',target=OWNER).candidate_id)
    engine=reload(tmp_path,mid)
    assert [e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==OWNER][-1].payload['mode']=='ADVANTAGE'


def test_automatic_shield_never_protects_enemy(tmp_path):
    combat,table,mid=fight(tmp_path,ask=False)
    turn(table,mid,ALLY)
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    settle(table,mid,candidate(combat,mid,'Force damage',target=FOE).candidate_id)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[FOE].current_hp==460
    assert engine.state.actors[OWNER].resources['resource:core.qi']==99
    assert not any(e.event_type=='REACTION_RESOLVED' and e.source_definition_id==RECOVERY for e in engine.events)


@pytest.mark.parametrize('dc,success',[(1,True),(100,False)])
def test_carried_hearth_recurrent_fire_enemy_only_and_bloom_allies(tmp_path,dc,success):
    combat,table,mid=fight(tmp_path,carry=True,dc=dc)
    settle(table,mid,candidate(combat,mid,'Carry the Hearth').candidate_id,
           choices={'choice:needle.carry_hearth':OWNER})
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources['resource:core.qi']==95
    active_zone=next(z for z in engine.state.zones.values() if z.active
                     and z.trigger_profile.get('profile',{}).get('hearth_carrier'))
    assert active_zone.trigger_profile['numbers']['potency'] > 0
    turn(table,mid,FOE)
    engine=reload(tmp_path,mid)
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and 'kindled_hearth' in e.source_definition_id]
    assert len(saves)==1 and saves[0].actor_id==FOE and saves[0].payload['success']==success
    assert engine.state.actors[FOE].current_hp<500
    packet=next(e for e in reversed(engine.events) if e.event_type=='DAMAGE_COMMITTED' and FOE in e.target_ids
                and e.payload.get('damage_type') in ('FIRE','RADIANT'))
    fire_roll=next(r for r in reversed(engine.rolls) if r.expression.startswith('2d8') and r.actor_id==OWNER)
    assert fire_roll.expression=='2d8+0'
    expected=fire_roll.total//2 if success else fire_roll.total
    assert packet.payload['rolled_or_pending_damage']==expected
    assert packet.payload['hp_damage']==expected
    assert engine.state.actors[ALLY].current_hp==500
    assert engine.state.actors[OWNER].current_hp==500
    turn(table,mid,ALLY)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[ALLY].temporary_hp==6
    assert engine.state.actors[FOE].temporary_hp==0


def test_replacement_retires_old_asset_and_aura(tmp_path):
    combat,table,mid=fight(tmp_path)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Kindled Hearth').candidate_id)
    engine=reload(tmp_path,mid)
    objs=[o for o in engine.state.objects.values() if (o.component or {}).get('name')=='Kindled Hearth']
    assert len(objs)==2 and sum(not o.destroyed for o in objs)==1
    zs=[z for z in engine.state.zones.values() if z.trigger_profile.get('profile',{}).get('hearth_object')]
    assert sum(z.active for z in zs)==1


def test_carry_requires_active_hearth_before_payment(tmp_path):
    combat,table,mid=fixture(tmp_path,[],cl=18,owner_features=[CARRY],bundle_transform=controls)
    engine=reload(tmp_path,mid)
    assert not any(engine.action_catalog[c.source_definition_id].display_name=='Carry the Hearth' for c in engine.legal_candidates()
                   if c.source_definition_id in engine.action_catalog)
    assert engine.state.actors[OWNER].resources['resource:core.qi']==100

PAPER_HEAVEN='tianxia.subpath.qi.paper_cultivator.feature.paper_heaven'

@pytest.mark.parametrize('dc,success',[(1,True),(100,False)])
def test_paperstorm_uses_enemy_start_timing_half_damage_and_reload(tmp_path,dc,success):
    combat,table,mid=fixture(tmp_path,[],cl=18,owner_features=[PAPER_HEAVEN],owner_dc=dc,bundle_transform=controls)
    settle(table,mid,candidate(combat,mid,'Paper Heaven',at=(6,6)).candidate_id)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[FOE].current_hp==500
    zone=next(z for z in engine.state.zones.values() if 'paper_heaven' in z.source_definition_id)
    assert zone.trigger_profile['height_ft']==60
    turn(table,mid,FOE)
    engine=reload(tmp_path,mid)
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and 'paper_heaven' in e.source_definition_id]
    assert len(saves)==1 and saves[0].actor_id==FOE and saves[0].payload['success']==success
    assert engine.state.actors[FOE].current_hp<500
    assert engine.state.actors[OWNER].current_hp==500
    assert engine.state.actors[ALLY].current_hp==500
    assert bool([c for c in engine.state.actors[FOE].conditions.values() if c.condition_id.endswith('blinded')])==(not success)
    from combat import zones
    assert zones.zone_is_difficult(engine,zone,engine.state.actors[FOE])
    assert not zones.zone_is_difficult(engine,zone,engine.state.actors[ALLY])
    if not success:
        settle(table,mid,table.state(mid)['menu']['end_turn'])
        turn(table,mid,OWNER)
        turn(table,mid,ALLY)
        turn(table,mid,FOE)
        engine=reload(tmp_path,mid)
        removed=[e for e in engine.events if e.event_type=='CONDITION_REMOVED'
                 and e.payload.get('condition_id','').endswith('blinded')]
        assert removed, 'Blinded must expire at the start of the target\'s next turn, before a new field save'


def test_paper_heaven_damage_half_and_scene_limit(tmp_path):
    amounts=[]
    for dc in (1,100):
        combat,table,mid=fixture(tmp_path/str(dc),[],cl=18,owner_features=[PAPER_HEAVEN],owner_dc=dc,bundle_transform=controls,seed='PAPER-HALF')
        settle(table,mid,candidate(combat,mid,'Paper Heaven',at=(6,6)).candidate_id)
        turn(table,mid,FOE)
        engine=reload(tmp_path/str(dc),mid)
        amounts.append(500-engine.state.actors[FOE].current_hp)
        turn(table,mid,OWNER)
        engine=reload(tmp_path/str(dc),mid)
        assert not any(engine.action_catalog[c.source_definition_id].display_name=='Paper Heaven' for c in engine.legal_candidates()
                       if c.source_definition_id in engine.action_catalog)
    assert amounts[0]==amounts[1]//2


def test_destroyed_hearth_ends_aura_and_damage_response(tmp_path):
    combat,table,mid=fight(tmp_path)
    engine=reload(tmp_path,mid)
    obj=next(o for o in engine.state.objects.values() if (o.component or {}).get('name')=='Kindled Hearth')
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Destroy Hearth',target=obj.object_id).candidate_id)
    engine=reload(tmp_path,mid)
    assert engine.state.objects[obj.object_id].destroyed
    assert not any(z.active and z.trigger_profile.get('profile',{}).get('hearth_object')==obj.object_id for z in engine.state.zones.values())
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,FOE)
    prompts=settle(table,mid,candidate(combat,mid,'Force damage',target=ALLY).candidate_id,
        choices={'choice:needle.hearth_shield':'shield'})
    engine=reload(tmp_path,mid)
    assert engine.state.actors[ALLY].current_hp==460
    assert not any(p['context']['reaction_source_id']=='choice:needle.hearth_shield' for p in prompts)


def test_carried_hearth_moves_real_asset_without_duplication(tmp_path):
    combat,table,mid=fight(tmp_path,carry=True)
    settle(table,mid,candidate(combat,mid,'Carry the Hearth').candidate_id,
           choices={'choice:needle.carry_hearth':OWNER})
    before=reload(tmp_path,mid)
    obj=next(o for o in before.state.objects.values() if (o.component or {}).get('name')=='Kindled Hearth')
    engine=combat._load_session(mid).engine
    moves=[c for c in engine.legal_candidates() if str(c.kind.value)=='MOVE' and c.destination and (c.destination.x,c.destination.y)==(3,5)]
    assert moves
    settle(table,mid,moves[0].candidate_id)
    after=reload(tmp_path,mid)
    assert after.state.objects[obj.object_id].position==after.state.actors[OWNER].position
    zone=next(z for z in after.state.zones.values() if z.active and z.trigger_profile.get('profile',{}).get('hearth_object')==obj.object_id)
    assert zone.center==after.state.actors[OWNER].position
    assert len([o for o in after.state.objects.values() if (o.component or {}).get('name')=='Kindled Hearth'])==1


def test_carried_hearth_entry_reentry_fires_once_per_turn_and_again_next_turn(tmp_path):
    combat,table,mid=fight(tmp_path,carry=True,foe_position={'x':8,'y':6})
    settle(table,mid,candidate(combat,mid,'Carry the Hearth').candidate_id,
           choices={'choice:needle.carry_hearth': OWNER})
    turn(table,mid,FOE)
    for destination in ((7,6),(8,6),(7,6)):
        engine=combat._load_session(mid).engine
        moves=[c for c in engine.legal_candidates() if str(c.kind.value)=='MOVE' and c.destination
               and (c.destination.x,c.destination.y)==destination]
        assert moves, destination
        settle(table,mid,moves[0].candidate_id)
        engine=reload(tmp_path,mid)
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and 'kindled_hearth' in e.source_definition_id]
    assert len(saves)==1
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,OWNER)
    turn(table,mid,ALLY)
    turn(table,mid,FOE)
    engine=reload(tmp_path,mid)
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and 'kindled_hearth' in e.source_definition_id]
    assert len(saves)==2


def test_ally_carrier_decline_leaves_hearth_stationary(tmp_path):
    combat,table,mid=fight(tmp_path,carry=True)
    settle(table,mid,candidate(combat,mid,'Carry the Hearth').candidate_id,
           choices={'choice:needle.carry_hearth': ALLY, 'choice:needle.carry_hearth_consent': None})
    engine=reload(tmp_path,mid)
    zone=next(z for z in engine.state.zones.values() if z.active and z.trigger_profile.get('profile',{}).get('hearth_object'))
    assert not zone.trigger_profile['profile'].get('hearth_carrier')
    assert engine.state.actors[OWNER].resources['resource:core.qi']==95


def test_cl18_carry_replaces_shield_dice_with_two_d8(tmp_path):
    combat,table,mid=fight(tmp_path,carry=True)
    settle(table,mid,candidate(combat,mid,'Carry the Hearth').candidate_id,
           choices={'choice:needle.carry_hearth': OWNER})
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Force damage',target=ALLY).candidate_id,
           choices={'choice:needle.hearth_shield':'shield'})
    engine=reload(tmp_path,mid)
    roll=next(r for r in engine.rolls if r.reason=='HEARTH_SHIELD_REDUCTION')
    assert roll.expression.startswith('2d8')


@pytest.mark.parametrize('inactive_owner',[False,True])
def test_carry_minute_expires_after_real_or_omitted_source_turns(tmp_path,inactive_owner):
    combat,table,mid=fight(tmp_path,carry=True)
    settle(table,mid,candidate(combat,mid,'Carry the Hearth').candidate_id,
           choices={'choice:needle.carry_hearth':OWNER})
    engine=reload(tmp_path,mid)
    zone=next(z for z in engine.state.zones.values() if z.active and z.trigger_profile.get('profile',{}).get('hearth_carrier'))
    zone_id=zone.zone_id
    start_turns=engine.state.actors[OWNER].turns_started
    boundary_actor=OWNER
    if inactive_owner:
        turn(table,mid,FOE)
        settle(table,mid,candidate(combat,mid,'Lethal damage',target=OWNER).candidate_id,
               choices={'choice:needle.hearth_shield':None})
        engine=reload(tmp_path,mid)
        from combat.turn_decisions import omits_turn
        assert engine.state.actors[OWNER].current_hp==0
        assert omits_turn(engine,OWNER)
        boundary_actor=FOE
    for n in range(1,11):
        settle(table,mid,table.state(mid)['menu']['end_turn'])
        turn(table,mid,boundary_actor)
        engine=reload(tmp_path,mid)
        profile=engine.state.zones[zone_id].trigger_profile.get('profile',{})
        assert bool(profile.get('hearth_carrier'))==(n<10)
    zone=engine.state.zones[zone_id]
    assert zone.active and zone.radius_cells==3
    assert engine.state.actors[OWNER].turns_started==start_turns+(0 if inactive_owner else 10)


@contextmanager
def hour_round():
    """One hour is one round while this block runs, so eight printed hours end at a table.

    The owner-editable duration_rounds table already maps one hour to 600 rounds;
    this narrows only that entry for the test. Nothing about the Hearth itself
    changes: it still creates the printed eight-hour duration.
    """
    from combat import typed_executor as te
    base = te.rules()
    token = te._REQUEST_RULES.set(
        {**base, 'duration_rounds': {**base['duration_rounds'], 'hours': 1, 'one_hour': 1}})
    try:
        yield
    finally:
        te._REQUEST_RULES.reset(token)


def _run_to_expiry(table, tmp_path, mid, zone_id, limit=14):
    """Advance real turns until the stored eight hours end, then return the fight."""
    for _ in range(limit):
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        turn(table, mid, OWNER)
        engine = reload(tmp_path, mid)
        if not engine.state.zones[zone_id].active:
            return engine
    raise AssertionError('the eight-hour Hearth never ended')


def test_expired_hearth_retires_its_asset_and_leaves_one_live_hearth(tmp_path):
    """The eight-hour Hearth's object ends with the Hearth (review finding 1).

    Expiry must not leave a live, positive-HP cultivated flame carrying the
    Hearth's immunities, and a later Hearth must not find it still there.
    """
    with hour_round():
        combat, table, mid = fight(tmp_path)
        before = reload(tmp_path, mid)
        zone_id = next(z.zone_id for z in before.state.zones.values()
                       if z.active and z.trigger_profile.get('profile', {}).get('hearth_object'))
        old_object = before.state.zones[zone_id].trigger_profile['profile']['hearth_object']
        assert before.state.zones[zone_id].duration_rounds == 8, 'eight hours, one round each'
        assert before.state.objects[old_object].current_hp == 54

        engine = _run_to_expiry(table, tmp_path, mid, zone_id)
        assert not engine.state.zones[zone_id].active, 'the eight hours must end the area'
        retired = engine.state.objects[old_object]
        assert retired.destroyed and retired.current_hp == 0, \
            'the empowered flame must not outlive its eight-hour area'

        # A fresh Hearth is the only live one, and leaves no second empowered asset.
        settle(table, mid, candidate(combat, mid, 'Kindled Hearth', at=(5, 6)).candidate_id)
        engine = reload(tmp_path, mid)
        objects = [o for o in engine.state.objects.values()
                   if (o.component or {}).get('name') == 'Kindled Hearth']
        assert len([o for o in objects if not o.destroyed]) == 1
        live = [z for z in engine.state.zones.values()
                if z.active and z.trigger_profile.get('profile', {}).get('hearth_object')]
        assert len(live) == 1 and live[0].zone_id != zone_id


def test_destroyed_hearth_zone_expiry_leaves_it_retired(tmp_path):
    """Retirement on ZONE_REMOVED stays idempotent for the destruction path."""
    with hour_round():
        combat, table, mid = fight(tmp_path)
        engine = reload(tmp_path, mid)
        obj = next(o for o in engine.state.objects.values()
                   if (o.component or {}).get('name') == 'Kindled Hearth')
        turn(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, 'Destroy Hearth', target=obj.object_id).candidate_id)
        engine = reload(tmp_path, mid)
        zone_id = next(z.zone_id for z in engine.state.zones.values()
                       if not z.active
                       and z.trigger_profile.get('profile', {}).get('hearth_object') == obj.object_id)
        assert engine.state.objects[obj.object_id].destroyed
        engine = _run_to_expiry(table, tmp_path, mid, zone_id)
        assert engine.state.objects[obj.object_id].destroyed
        assert engine.state.objects[obj.object_id].current_hp == 0


def test_accepted_ally_carrier_moves_the_flame_and_survives_reload(tmp_path, monkeypatch):
    """An ally who accepts the invitation really carries the flame (review finding 2)."""
    combat, table, mid = fight(tmp_path, carry=True)
    settle(table, mid, candidate(combat, mid, 'Carry the Hearth').candidate_id,
           choices={'choice:needle.carry_hearth': ALLY, 'choice:needle.carry_hearth_consent': 'carry'})
    before = reload(tmp_path, mid)
    zone = next(z for z in before.state.zones.values()
                if z.active and z.trigger_profile.get('profile', {}).get('hearth_carrier'))
    obj_id = zone.trigger_profile['profile']['hearth_object']
    origin = zone.center
    assert zone.trigger_profile['profile']['hearth_carrier'] == ALLY
    assert zone.center == before.state.actors[ALLY].position
    assert before.state.objects[obj_id].position == before.state.actors[ALLY].position

    # Carry is a Bonus Action. Advance to the invited ally's actual turn before
    # taking a movement candidate, otherwise this silently moves the creator.
    turn(table, mid, ALLY)
    engine = combat._load_session(mid).engine
    ally_pos = before.state.actors[ALLY].position
    moves = [c for c in engine.legal_candidates() if str(c.kind.value) == 'MOVE' and c.destination
             and c.actor_id == ALLY
             and (c.destination.x, c.destination.y) != (ally_pos.x, ally_pos.y)]
    assert moves
    move = max(moves, key=lambda c: len(c.canonical_path))
    path = move.canonical_path
    event_start = max(e.sequence for e in engine.events)
    # A test-only native movement-step response deals damage once the carrier
    # has travelled outside the Hearth's old 15-foot centre. The real Shield
    # choice must be offered at that intermediate step, before the move ends.
    from combat import ext
    fired = {'value': False}

    def damage_after_leaving_origin(engine, mover, previous, nxt, intent):
        if (mover.entity_id == ALLY and not fired['value']
                and engine.grid.distance_ft(origin, mover.position) > 15):
            fired['value'] = True
            engine._commit_damage(mover, 10, 'FORCE', 'test:movement-step-damage', FOE,
                                  intent, reaction_depth=0)

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'movement_step',
                        [*ext.subscribers('movement_step'), damage_after_leaving_origin])
    prompts = settle(table, mid, move.candidate_id,
                     choices={'choice:needle.hearth_shield': 'shield'})
    assert fired['value'], 'the movement must cross beyond the original aura centre'
    assert any(p['context']['reaction_source_id'] == 'choice:needle.hearth_shield'
               for p in prompts), 'the moving carrier must still receive the paid player choice'
    after = reload(tmp_path, mid)
    moved = after.state.actors[ALLY].position
    assert moved != ally_pos, 'the invited ally, not the creator, must move'
    assert after.state.objects[obj_id].position == moved, 'the real flame follows the accepted ally'
    carried = next(z for z in after.state.zones.values() if z.active
                   and z.trigger_profile.get('profile', {}).get('hearth_object') == obj_id)
    assert carried.center == moved
    assert len([o for o in after.state.objects.values()
                if (o.component or {}).get('name') == 'Kindled Hearth']) == 1
    step_updates = [e for e in after.events if e.sequence > event_start
                    and e.event_type == 'OBJECT_UPDATED' and obj_id in e.target_ids]
    assert [e.payload['object']['position'] for e in step_updates] == [
        p.model_dump(mode='json') for p in path[1:]], (
            'the owned flame must follow each committed movement step before later step effects')


def move_to(table, mid, cell):
    """The candidate id that moves the creature whose turn it is onto ``cell``."""
    engine = table.combat._load_session(mid).engine
    rows = [c for c in engine.legal_candidates() if str(c.kind.value) == 'MOVE' and c.destination
            and (c.destination.x, c.destination.y) == cell]
    assert rows, cell
    return rows[0].candidate_id


def test_paper_heaven_entry_reentry_fires_once_per_entry_and_again_next_turn(tmp_path):
    """Paper Heaven enter/re-entry deduplicates across commits and a later turn (review finding 2)."""
    # The field is centred well off the hostile's corner so its own Speed reaches
    # both covered and uncovered ground, making entry and re-entry real crossings.
    combat, table, mid = fixture(tmp_path, [], cl=18, owner_features=[PAPER_HEAVEN], owner_dc=18,
                                 bundle_transform=controls, seed='PAPER-ENTRY')
    settle(table, mid, candidate(combat, mid, 'Paper Heaven', at=(9, 9)).candidate_id)
    engine = reload(tmp_path, mid)
    zone = next(z for z in engine.state.zones.values() if 'paper_heaven' in z.source_definition_id)
    from combat.spatial_areas import zone_contains

    def saves():
        return [e for e in reload(tmp_path, mid).events
                if e.event_type == 'SAVE_ROLLED' and 'paper_heaven' in e.source_definition_id]

    def on_side(want_inside):
        """Whether the hostile currently stands on that side of the field."""
        engine = combat._load_session(mid).engine
        zone_now = next(z for z in engine.state.zones.values() if 'paper_heaven' in z.source_definition_id)
        return zone_contains(engine, engine.state.actors[FOE], zone_now) == want_inside

    saves = lambda: len([e for e in reload(tmp_path, mid).events
                         if e.event_type == 'SAVE_ROLLED' and 'paper_heaven' in e.source_definition_id])

    def cross(want_inside):
        """Commit a reachable crossing without changing the current turn."""
        assert on_side(not want_inside), 'a crossing must start on the other side'
        settle(table, mid, move_to(table, mid, nearest(want_inside)))
        reload(tmp_path, mid)
        assert on_side(want_inside), 'the committed move did not change sides'
        return saves()

    def nearest(want_inside):
        """The closest cell of that side this turn's Speed really reaches."""
        engine = combat._load_session(mid).engine
        zone_now = next(z for z in engine.state.zones.values() if 'paper_heaven' in z.source_definition_id)
        foe = engine.state.actors[FOE]
        here = (foe.position.x, foe.position.y)
        cells = []
        for row in engine.legal_candidates():
            if str(row.kind.value) != 'MOVE' or row.destination is None:
                continue
            cell = (row.destination.x, row.destination.y)
            if cell == here or zone_contains(engine, foe, zone_now, at=row.destination) != want_inside:
                continue
            cells.append((abs(cell[0] - here[0]) + abs(cell[1] - here[1]), cell))
        assert cells, 'no reachable cell on the %s side' % ('covered' if want_inside else 'open')
        return min(cells)[1]

    # Entry, exit and re-entry on one turn prove native first-entry deduplication
    # survives separate service commits and cold reloads.
    if on_side(True):
        turn(table, mid, FOE)
        cross(False)
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, FOE)
    before = saves()
    cross(True)
    assert saves() == before + 1, 'first entry fires once'
    cross(False)
    assert saves() == before + 1, 'leaving does not fire'
    cross(True)
    assert saves() == before + 1, 'same-turn re-entry is deduplicated'
    settle(table, mid, table.state(mid)['menu']['end_turn'])

    # Starting inside fires once; leaving and re-entering on that same turn must
    # remain deduplicated, and delivery resumes on the following turn.
    turn(table, mid, OWNER)
    turn(table, mid, ALLY)
    mark = saves()
    turn(table, mid, FOE)
    assert saves() == mark + 1, 'starting inside fires once'
    mark = saves()
    cross(False)
    assert saves() == mark, 'leaving after start delivery adds nothing'
    cross(True)
    assert saves() == mark, 'same-turn re-entry after start delivery is deduplicated'
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    turn(table, mid, ALLY)
    mark = saves()
    turn(table, mid, FOE)
    assert saves() == mark + 1, 'each later turn fires the field once, never twice'


def test_shield_prompt_names_the_damage_source_action(tmp_path):
    """Shield the Flame names the action causing the damage (review finding 3)."""
    combat, table, mid = fight(tmp_path)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Force damage', target=ALLY).candidate_id,
                     choices={'choice:needle.hearth_shield': 'shield'})
    shield = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.hearth_shield']
    assert shield, 'the paid Reaction must still be offered'
    reaction = shield[0]
    assert reaction['action'] == 'Force damage', 'the prompt names the damage\'s own action'
    assert 'Force damage' in reaction['trigger']
    assert 'Force damage' in reaction['moment']
    assert 'Reaction and 1 Qi' in reaction['trigger']


def landing_controls(bundles):
    """Real native entry terrain and typed push, sealed before the fight."""
    controls(bundles)
    for bundle in bundles:
        if bundle['actor_id'] != FOE:
            continue
        specs = [
            ('Entry field', 'CELL', [{'type':'zone'}], {'zone_spec': {
                'name':'Entry field', 'shape':'cube', 'size_ft':5,
                'duration':{'kind':'minutes','amount':1},
                'triggers':[{'id':'entry','name':'Entry field','on':['enter'],'who':'hostile',
                    'effects':[{'type':'damage','applies_to':'target','flat':40,'damage_types':['force']}]}]}}),
            ('Push thirty', 'HOSTILE_ENTITY', [{'type':'forced_movement','applies_to':'target',
                'distance_ft':30,'direction':'away'}], {}),
        ]
        for name, target, effects, extra in specs:
            sid = 'action:test.landing.' + name.replace(' ', '_')
            row = ActionDefinition(source_definition_id=sid, owner_id=FOE, display_name=name,
                economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind=target, range_ft=60,
                parameters={'typed':{'source':sid,'numbers':{'cl':18,'pb':6,'save_dc':18},
                    'effects':effects,'duration':{'kind':'instant'},'riders':[],**extra}})
            bundle['action_catalog'].append(row.model_dump(mode='json'))
            bundle['actor_template']['action_ids'].append(sid)
        bundle.pop('bundle_sha256',None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)


@pytest.mark.parametrize('forced', [False, True], ids=['willing-entry','push-beyond-twenty'])
def test_carried_hearth_precedes_native_landing_damage(tmp_path, forced):
    combat,table,mid = fight(tmp_path,carry=True,foe_position={'x':4,'y':5},bundle_transform=landing_controls)
    settle(table,mid,candidate(combat,mid,'Carry the Hearth').candidate_id,
        choices={'choice:needle.carry_hearth':ALLY,'choice:needle.carry_hearth_consent':'carry'})
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Entry field',at=(4,11)).candidate_id)
    before = reload(tmp_path,mid)
    zone = next(z for z in before.state.zones.values() if z.active
        and z.trigger_profile.get('profile',{}).get('hearth_carrier') == ALLY)
    obj_id,origin = zone.trigger_profile['profile']['hearth_object'],zone.center
    qi = before.state.actors[OWNER].resources['resource:core.qi']
    if forced:
        turn(table,mid,ALLY)
        turn(table,mid,FOE)
        chosen = candidate(combat,mid,'Push thirty',target=ALLY)
    else:
        turn(table,mid,ALLY)
        engine = combat._load_session(mid).engine
        chosen = next(c for c in engine.legal_candidates() if str(c.kind.value)=='MOVE'
            and c.destination and (c.destination.x,c.destination.y)==(4,11))
    before_move = reload(tmp_path,mid)
    start = max(e.sequence for e in before_move.events)
    hp,temp = before_move.state.actors[ALLY].current_hp,before_move.state.actors[ALLY].temporary_hp
    prompts = settle(table,mid,chosen.candidate_id,choices={'choice:needle.hearth_shield':'shield'})
    assert any(p['context']['reaction_source_id']=='choice:needle.hearth_shield' for p in prompts), (
        'native entry damage beyond the old 20-foot aura must offer the player Shield')
    after = reload(tmp_path,mid)
    events = [e for e in after.events if e.sequence > start]
    damage = next(e for e in events if e.event_type=='DAMAGE_COMMITTED'
        and e.source_definition_id=='action:test.landing.Entry_field')
    receipt = next(e for e in events if e.event_type=='REACTION_RESOLVED' and e.source_definition_id==RECOVERY)
    move = next(e for e in events if e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==ALLY)
    updates = [e for e in events if e.event_type=='OBJECT_UPDATED' and obj_id in e.target_ids]
    assert [e.payload['object']['position'] for e in updates] == move.payload['path'][1:]
    landing = next(e for e in reversed(updates) if e.sequence < damage.sequence)
    from combat.gate2_runtime_models import Position
    assert after.grid.distance_ft(origin,Position.model_validate(landing.payload['object']['position'])) > 20
    assert after.state.actors[OWNER].resources['resource:core.qi'] == qi-1
    assert not after.state.actors[OWNER].reaction_available
    assert after.state.actors[ALLY].current_hp == hp-max(0,40-receipt.payload['reduction']-temp)
    assert after.state.zones[zone.zone_id].center == after.state.actors[ALLY].position
    assert after.state.objects[obj_id].position == after.state.actors[ALLY].position
    assert move.payload.get('forced',False) == forced
