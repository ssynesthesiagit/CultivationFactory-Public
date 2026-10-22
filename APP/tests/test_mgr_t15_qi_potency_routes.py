"""Actual portable-sheet import and split-delivery Qi potency regressions."""
import json
import zipfile
from pathlib import Path
import pytest
from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import FOE, candidate, settle, reload, turn
from tests.test_r9i_karma_persistence import act

# A Factory project id doubles as the button-store file name, which accepts
# only hex ids. worker2-owner cannot hold a saved reaction plan, so this
# fixture uses a hex id for its own owner.
OWNER = 'actor:factory.9f1c2d3e4b5a6c7d'
P = 'tianxia.path.qi_cultivation.feature.qi_technique_potency'
RAY = 'FIRE_TAL_SCORCHING_RAY_ART'
VOLLEY = 'TAL_LIGHTNING_THOUSAND_SPARK_VOLLEY'
BOW = {'starting_kit': {'items': [
    {'item_id':'tianxia.mortal.weapon.gong_jian', 'quantity':1},
    {'item_id':'tianxia.mortal.gear.arrows_20', 'quantity':2}]}}
SECOND = 'actor:factory.qi-potency-second'
SUN = 'tianxia.subpath.qi.cai_clan_empyreal_administrator.feature.white_sun_judgment'
NULL = 'TAL_VOID_NULLIFYING_STRIKE'
FIELD = 'TAL_DEATH_WITHERING_FIELD'


def imported_fight(tmp_path, *, kind='volley', potency=True, primary='Qi', automatic=False, reactions=False):
    # A real sheet only attacks proficiently with a weapon its sphere or path
    # grants: Sniper Training for the bow (Thousand-Spark Volley), Spear
    # Training for the Qiang (paid-hit proof). Without one, the weapon attack
    # is +4 against AC 14 and the seeded roll misses, so no hit packet exists.
    owned = (([P] if potency else [])
             + (([VOLLEY, 'TAL_LIGHTNING_THUNDER_ARROW', 'TAL_BARRAGE_BLITZ_FOCUS',
                  'TAL_SNIPER_SNIPER_TRAINING'] if kind=='volley'
                 else [RAY] if kind in ('ray','immortal')
                 else ['tianxia.path.qi_cultivation.feature.domain_armament'] if kind=='path'
                 else [SUN] if kind=='subpath'
                 else [NULL, 'SPEAR_BASE_SPEAR_TRAINING'] if kind=='paid'
                 else [FIELD] if kind=='delayed' else [])))
    doc = sheet(owned, cl=17, primary=primary, key='INT', score=18,
        kit={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.qiang','quantity':1}]}} if kind=='paid' else BOW)
    doc['identity']['proficiency_bonus']=6
    doc['ability_scores_and_statistics'].update(technique_attack_bonus=10, technique_save_dc=18)
    doc['ability_scores_and_statistics']['primary_resource']['maximum']=68
    if kind=='recorded':
        doc['training_sources']=[{'name':'Recorded Scorching Ray Art', 'type':'manual',
            'contents':{'manual_collection':{'content_record_bindings':[{'record_id':RAY}]},
                        'recorded_art_details':[{'record_id':RAY,'minimum_cl':5}]}}]
    if kind=='immortal':
        doc['immortal_arts']=[{'art_id':'immortal.qi-potency-rays', 'name':'Immortal Ray Art',
            'source_record_id':RAY,'activation_cp':4,
            'action_surface':{'action_type':'action'},'path_id':'tianxia.path.qi_cultivation'}]
    for aid, document in [(OWNER,doc),(FOE,sheet([],cl=17)),(SECOND,sheet([],cl=17))]:
        folder=tmp_path/'portable_characters'/aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    if reactions:
        # The plan is read while the match compiles, so save it first.
        ButtonStore(tmp_path/'tabletop_buttons').save_reactions(
            OWNER.removeprefix('actor:factory.'), {'mode':'ask'}, {'opportunity_attack'})
    combat=CombatService(ROOT,tmp_path)
    combat.tabletop_maps.save({'display_name':'Qi potency yard','width_squares':12,'height_squares':8,
        'walls':[],'starts':{'team1':[[5,4] if kind=='paid' else [2,4]],'team2':[[6,4],[7,5]]}})
    modes={OWNER:'LOCAL_AUTO' if automatic else 'MANUAL',FOE:'MANUAL',SECOND:'MANUAL'}
    mid=combat.create_factory_match(project_ids=[OWNER.removeprefix('actor:factory.')],
        opponent_actor_ids=[FOE,SECOND],control_modes=modes,arena_id='battlefield:map.qi-potency-yard',
        match_seed='QI-NATIVE-IMPORT',maximum_rounds=15)['match_id']
    table=TabletopService(combat,tmp_path)
    turn(table,mid,OWNER)
    return combat,table,mid


def damage(engine):
    return [r for r in engine.rolls if r.actor_id==OWNER and r.reason.startswith('DAMAGE') and r.dice]


def receipts(engine):
    return list(engine.state.actors[OWNER].turn_flags.get('damage_activation_round_receipts',{}).values())


@pytest.mark.parametrize('choice',['weapon','technique'])
def test_real_volley_selects_one_weapon_or_technique_roll_across_arcs(tmp_path,choice):
    combat,table,mid=imported_fight(tmp_path)
    before=reload(tmp_path,mid).state.actors[OWNER].resources['resource:core.qi']
    prompts=settle(table,mid,candidate(combat,mid,'Thousand-Spark Volley',target=FOE).candidate_id,
        choices={'choice:needle.qi_potency':choice})
    assert len([p for p in prompts if p['context']['reaction_source_id']=='choice:needle.qi_potency'])==1
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources['resource:core.qi']==before-2
    assert receipts(engine)==[{'choice':choice,'used':True}]
    rolled=damage(engine)
    assert len(rolled)>=2
    assert [r.modifier for r in rolled[:2]]==([8,0] if choice=='weapon' else [4,4])
    assert all(r.modifier==0 for r in rolled[2:])


def test_pending_damage_choice_survives_fresh_service_without_payment_or_double_bonus(tmp_path):
    combat,table,mid=imported_fight(tmp_path)
    cid=candidate(combat,mid,'Thousand-Spark Volley',target=FOE).candidate_id
    before=reload(tmp_path,mid)
    result=act(table,mid,cid)
    assert result['status']=='REACTION_REQUIRED'
    assert result['reaction']['context']['reaction_source_id']=='choice:needle.qi_potency'
    pending=reload(tmp_path,mid)
    assert pending.state.actors[OWNER].resources==before.state.actors[OWNER].resources
    assert not damage(pending)
    combat=CombatService(ROOT,tmp_path);table=TabletopService(combat,tmp_path)
    settle(table,mid,cid,choices={'choice:needle.qi_potency':'weapon'})
    engine=reload(tmp_path,mid)
    assert receipts(engine)==[{'choice':'weapon','used':True}]
    assert [r.modifier for r in damage(engine)[:2]]==[8,0]


@pytest.mark.parametrize('kind,name',[('ray','Scorching Ray Art'),('recorded','Scorching Ray Art'),
                                     ('immortal','Immortal Ray Art')])
def test_imported_qi_feature_classes_apply_once_then_next_activation_resets(tmp_path,kind,name):
    combat,table,mid=imported_fight(tmp_path,kind=kind)
    settle(table,mid,candidate(combat,mid,name,target=FOE).candidate_id)
    engine=reload(tmp_path,mid)
    rolled=damage(engine)
    assert rolled and [r.modifier for r in rolled]==[4]+[0]*(len(rolled)-1)
    assert receipts(engine)==[{'choice':'technique','used':True}]
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,OWNER)
    prior=len(damage(reload(tmp_path,mid)))
    settle(table,mid,candidate(combat,mid,name,target=SECOND).candidate_id)
    engine=reload(tmp_path,mid)
    later=damage(engine)[prior:]
    assert later and [r.modifier for r in later]==[4]+[0]*(len(later)-1)


def test_real_qi_barrage_followup_uses_primary_activation_receipt_after_reload(tmp_path):
    combat,table,mid=imported_fight(tmp_path)
    name='Barrage: Thousand-Spark Volley'
    settle(table,mid,candidate(combat,mid,name,target=FOE).candidate_id,
           choices={'choice:needle.qi_potency':'weapon'})
    engine=reload(tmp_path,mid)
    assert receipts(engine)==[{'choice':'weapon','used':True}]
    combat=CombatService(ROOT,tmp_path);table=TabletopService(combat,tmp_path)
    before=len(damage(engine))
    settle(table,mid,candidate(combat,mid,'Barrage follow-up: Thousand-Spark Volley',target=SECOND).candidate_id)
    after=reload(tmp_path,mid)
    assert receipts(after)==[{'choice':'weapon','used':True}]
    assert all(r.modifier==0 for r in damage(after)[before:])


def test_native_qi_path_projected_armament_adds_key_to_its_one_real_roll(tmp_path):
    combat,table,mid=imported_fight(tmp_path,kind='path')
    settle(table,mid,candidate(combat,mid,'Domain Armament: Manifest',at=(5,4)).candidate_id)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Domain Armament Attack',target=FOE).candidate_id)
    engine=reload(tmp_path,mid)
    assert [r.modifier for r in damage(engine)]==[8]
    assert receipts(engine)==[{'choice':'technique','used':True}]


def test_native_qi_subpath_area_shares_one_damage_roll_across_recipients(tmp_path):
    combat,table,mid=imported_fight(tmp_path,kind='subpath')
    settle(table,mid,candidate(combat,mid,'White Sun Judgment',at=(6,4)).candidate_id)
    engine=reload(tmp_path,mid)
    assert [r.modifier for r in damage(engine)]==[4]
    assert receipts(engine)==[{'choice':'technique','used':True}]
    targets={tid for e in engine.events if e.event_type=='DAMAGE_COMMITTED' for tid in e.target_ids}
    assert {FOE,SECOND}<=targets and OWNER not in targets


def test_automatic_native_qi_projectiles_need_no_manual_damage_choice(tmp_path):
    combat,table,mid=imported_fight(tmp_path,kind='ray',automatic=True)
    assert table.auto_step(mid,0,[])['status']=='COMMITTED'
    engine=reload(tmp_path,mid)
    rolled=damage(engine)
    assert rolled and [r.modifier for r in rolled]==[4]+[0]*(len(rolled)-1)
    assert receipts(engine)==[{'choice':'technique','used':True}]


@pytest.mark.parametrize('configured',[False,True])
@pytest.mark.parametrize('choice',['weapon','technique'])
def test_native_paid_qi_hit_selects_before_weapon_damage(tmp_path,configured,choice):
    combat,table,mid=imported_fight(tmp_path,kind='paid')
    engine=reload(tmp_path,mid)
    parent=next(a for a in engine.action_catalog.values() if a.owner_id==OWNER
                and a.display_name=='Qiang (Spear) attack')
    if configured:
        for field,value in [('on','toggle'),('option','0'),('payment','0'),('damage','force')]:
            setting=next(a for a in engine.action_catalog.values() if a.parameters.get('attack_modifier_setting')=={
                'family':parent.source_definition_id,'modifier':NULL,'name':'Nullifying Strike',
                'field':field,'value':value})
            settle(table,mid,candidate(combat,mid,setting.display_name).candidate_id)
    before=reload(tmp_path,mid).state.actors[OWNER].resources['resource:core.qi']
    prompts=settle(table,mid,candidate(combat,mid,parent.display_name,target=FOE).candidate_id,
        choices={'choice:needle.paid_hit':'first','choice:needle.qi_potency':choice})
    assert len([p for p in prompts if p['context']['reaction_source_id']=='choice:needle.qi_potency'])==1
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources['resource:core.qi']==before-2
    assert [r.modifier for r in damage(engine)[:2]]==([8,0] if choice=='weapon' else [4,4])
    assert receipts(engine)==[{'choice':choice,'used':True}]


def test_declined_qi_hit_payment_keeps_weapon_ordinary(tmp_path):
    combat,table,mid=imported_fight(tmp_path,kind='paid')
    before=reload(tmp_path,mid).state.actors[OWNER].resources['resource:core.qi']
    settle(table,mid,candidate(combat,mid,'Qiang (Spear) attack',target=FOE).candidate_id,
           choices={'choice:needle.paid_hit':None})
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources['resource:core.qi']==before
    assert [r.modifier for r in damage(engine)]==[4]
    assert not receipts(engine)


def test_delayed_qi_field_keeps_creating_activation_receipt_across_cold_turns(tmp_path):
    combat,table,mid=imported_fight(tmp_path,kind='delayed')
    settle(table,mid,candidate(combat,mid,'Withering Field',at=(6,4)).candidate_id)
    created=reload(tmp_path,mid)
    assert not damage(created)
    zone=next(z for z in created.state.zones.values() if z.active)
    origin=zone.trigger_profile.get('qi_potency_activation')
    combat=CombatService(ROOT,tmp_path);table=TabletopService(combat,tmp_path)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,OWNER)
    engine=reload(tmp_path,mid)
    rolled=damage(engine)
    assert len(rolled)==2
    assert [r.modifier for r in rolled]==[4,0]
    assert origin['bonus']==4 and origin['id']
    assert receipts(engine)==[{'choice':'technique','used':True}]
    assert engine.state.actors[OWNER].resources['resource:core.qi']==64


@pytest.mark.parametrize('owner_ai',[False,True])
def test_paid_qi_potency_is_reachable_during_enemy_ai_movement(tmp_path,owner_ai):
    from tests.hunt36_support import send
    combat,table,mid=imported_fight(tmp_path,kind='paid',reactions=True)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,FOE)
    if owner_ai:
        combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    engine=reload(tmp_path,mid)
    assert engine.state.current_actor_id==FOE
    before=engine.state.actors[OWNER].resources['resource:core.qi']
    # The Qiang has 10-foot reach, so the foe must leave that reach to draw
    # the Opportunity Attack. Pick a legal walk whose own exposure metadata
    # names the owner (no jump/crawl), rather than one fixed square.
    move=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination
              and not c.metadata.get('movement_mode')
              and any(row['actor_id']==OWNER for row in c.metadata.get('expected_opportunity_attacks') or []))
    prompts=send(combat,table,mid,move.candidate_id,ai=True,pick=lambda o:o['id']=='technique')
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources['resource:core.qi']==before-2
    expected='weapon' if owner_ai else 'technique'
    assert receipts(engine)==[{'choice':expected,'used':True}]
    assert [r.modifier for r in damage(engine)[:2]]==([8,0] if owner_ai else [4,4])
    potency=[p for p in prompts if p['context']['reaction_source_id']=='choice:needle.qi_potency']
    assert bool(potency)==(not owner_ai)
