"""Printed-rule regressions for Lightning, Magma, and Metal."""

import copy
import json
from functools import lru_cache
from pathlib import Path

import pytest

from combat import typed_executor as te, typed_reactions as tr, zones
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from tests.test_auto_support import ME, _engine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
AUTH = json.loads((ROOT/'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
L, M, T = 'TAL_LIGHTNING_', 'TAL_MAGMA_', 'TAL_METAL_'


@lru_cache(maxsize=None)
def _compiled(key, cl=20, dc=50, armed=False, extra=()):
    sphere = AUTH[key]['sphere_id']
    bases = [k for k,v in AUTH.items() if v.get('sphere_id') == sphere and v.get('kind') == 'base_ability']
    kit = [{'starting_kit': {'items': [{'item_id':'tianxia.mortal.weapon.fu','name':'Fu (Short Axe)','quantity':1}]}}] if armed else []
    sheet = {**SHEET, 'equipment':kit,
        'identity': {**SHEET['identity'], 'cultivation_level':cl},
        'ability_scores_and_statistics': {**SHEET['ability_scores_and_statistics'],
            'technique_save_dc':dc, 'technique_attack_bonus':40,
            'primary_resource':{'name':'Qi','maximum':100}},
        'spheres_and_talents': {'sphere_record_ids':[sphere],
            'learned_talent_record_ids':list(dict.fromkeys([*bases,key,*extra]))}}
    return compile_character(sheet, actor_id=ME)


def _fight(key, cl=20, dc=50, armed=False, foe_at=(4,6), extra=()):
    bundle = copy.deepcopy(_compiled(key,cl,dc,armed,extra))
    engine = _engine(bundle,foe_at=foe_at)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    foe.maximum_hp = foe.current_hp = 2000
    foe.armor_class = -50
    me.resources['resource:core.martial_focus'] = 1
    return bundle,engine,me,foe


def _cast(engine,prefix,contains='',target_id=None):
    candidates = [c for c in engine.legal_candidates() if c.display_name.startswith(prefix) and contains in c.display_name
                  and (target_id is None or target_id in c.target_ids)]
    assert candidates,(prefix,contains)
    pos = engine.state.actors[AN].position
    candidate = min(candidates,key=lambda c:(0 if c.destination is None else abs(c.destination.x-pos.x)+abs(c.destination.y-pos.y),len(c.display_name)))
    engine.execute_intent(ActionIntent(intent_id='review',decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id,state_version=candidate.state_version,actor_id=ME,
        target_ids=candidate.target_ids,destination=candidate.destination))


def _mark(engine,foe,name='Opened'):
    engine._apply_condition(foe,te.mark_condition_id(name,ME),'test:mark',ME,expires_on='UNTIL_REMOVED',data={'mark':name,'label':name})


def _ally(engine,me):
    ally = me.model_copy(deep=True)
    ally.entity_id = 'actor:review.ally'
    ally.position = me.position.model_copy(update={'y':me.position.y+1})
    engine.state.actors[ally.entity_id] = ally
    return ally


def _rolls(engine,kind):
    return [r for r in engine.rolls if r.reason.startswith(kind)]


def _damage(engine):
    return [r.expression.removesuffix('+0') for r in _rolls(engine,'DAMAGE:')]


def _metal_hit_this_turn(engine, me, foe, amount=5):
    """Record the DAMAGE_COMMITTED event the engine emits for a real Metal hit on the foe."""
    engine._append_event('DAMAGE_COMMITTED', T+'NEEDLE_FLICK', actor_id=me.entity_id,
                         target_ids=(foe.entity_id,),
                         payload={'rolled_or_pending_damage':amount,'reduced_to':amount,
                                  'temporary_hp_absorbed':0,'hp_damage':amount,
                                  'damage_type':'Piercing','remaining_hp':foe.current_hp})


def _conditions(actor,name):
    return [c for c in actor.conditions.values() if c.condition_id == 'condition:typed.'+name]


@pytest.mark.parametrize('key,prefix,cl,dice',[
    (L+'CHAIN_BOLT','Chain Bolt',5,'2d8+2'),
    (L+'CHAIN_BOLT','Chain Bolt',17,'4d8+2'),
    (M+'LAVA_BURST','Lava Burst',5,'6d6'),
    (M+'LAVA_BURST','Lava Burst',11,'8d6'),
    (M+'LAVA_BURST','Lava Burst',17,'10d6'),
    # owner/qi-armor-5 MOD1 (merge 5c892c64): add the Path key modifier;
    # this fixture's CON 14 contributes +2 once, at every printed level band.
    (M+'MAGMA_GLOB','Magma Glob',1,'1d10+2'),
    (M+'MAGMA_GLOB','Magma Glob',5,'2d10+2'),
    (M+'MAGMA_GLOB','Magma Glob',11,'3d10+2'),
    (M+'MAGMA_GLOB','Magma Glob',17,'4d10+2'),
    (M+'OBSIDIAN_RAIN','Obsidian Rain',10,'8d8'),
    (M+'OBSIDIAN_RAIN','Obsidian Rain',17,'10d8'),
    (T+'HEAVEN_PIERCING_NAIL','Heaven-Piercing Nail',15,'8d8'),
    (T+'IRON_FILINGS_CLOUD','Iron Filings Cloud',5,'2d8'),
    (T+'IRON_FILINGS_CLOUD','Iron Filings Cloud',10,'3d8'),
    (T+'NEEDLE_FLICK','Needle Flick',1,'1d8+2'),
    (T+'NEEDLE_FLICK','Needle Flick',5,'2d8+2'),
    (T+'NEEDLE_FLICK','Needle Flick',15,'4d8+2'),
    (T+'WHITE_TIGER_SEVERANCE','White Tiger Severance',10,'6d8'),
    (T+'WHITE_TIGER_SEVERANCE','White Tiger Severance',15,'8d8'),
    ('tianxia.talent.metal.heavenly_needle_sutra','Heavenly Needle Sutra',5,'3d8+2'),
    ('tianxia.talent.metal.heavenly_needle_sutra','Heavenly Needle Sutra',10,'4d8+2'),
])
def test_printed_damage_tables_reach_the_engine(key,prefix,cl,dice):
    _,engine,me,foe = _fight(key,cl=cl)
    _cast(engine,prefix)
    assert _damage(engine) == [dice]
    assert foe.current_hp < 2000


ZONES=[
    (L+'CONDUCTIVE_FIELD','Conductive Field',['1d8+2']),
    (M+'BLACKGLASS_RIVER','Blackglass River',['6d6','2d6']),
    (M+'BOILING_ASH_SKY','Boiling Ash Sky',['6d8']),
    (M+'COURT_OF_THE_LIVING_VOLCANO','Court of the Living Volcano',['3d8']),
    (M+'LAVA_FLOW','Lava Flow',['8d6']),
    (M+'LAVA_WALL','Lava Wall',['4d8','2d8']),
    (M+'MOLTEN_GROUND','Molten Ground',['7d6']),
    (M+'VOLCANIC_ERUPTION','Volcanic Eruption',['8d6','4d6']),
    (M+'WORLD_BREAKING_ERUPTION','World-Breaking Eruption',['8d8','5d8']),
    ('tianxia.talent.magma.sea_of_molten_heaven','Sea of Molten Heaven',['8d10','8d10']),
    (T+'DOMAIN_OF_TEN_THOUSAND_BLADES','Domain of Ten Thousand Blades',['4d8']),
]


@pytest.mark.parametrize('key,prefix,dice',ZONES)
def test_zone_damage_waits_for_turn_start(key,prefix,dice):
    _,engine,me,foe = _fight(key)
    movement=me.movement_remaining_ft
    _cast(engine,prefix)
    assert foe.current_hp == 2000 and not _rolls(engine,'SAVE:')
    assert me.movement_remaining_ft == movement
    assert not any(m.target_field=='armor_class' for m in foe.modifiers.values())
    engine.end_turn()
    assert _damage(engine)[:len(dice)] == dice
    assert foe.current_hp < 2000
    if key==L+'CONDUCTIVE_FIELD':assert te.bears_mark(foe,ME,'Charged')
    if key in (M+'BLACKGLASS_RIVER',M+'LAVA_FLOW'):
        zone=next(z for z in zones.typed_zones(engine) if z.trigger_profile.get('name')==prefix)
        assert (4,7) in {(p.x,p.y) for p in zone.affected_cells}


@pytest.mark.parametrize('key,prefix,cl,dice',[
    (M+'MOLTEN_GROUND','Molten Ground',1,'2d6'),
    (M+'MOLTEN_GROUND','Molten Ground',5,'3d6'),
    (M+'MOLTEN_GROUND','Molten Ground',11,'5d6'),
    (M+'LAVA_FLOW','Lava Flow',5,'4d6'),
    (M+'LAVA_FLOW','Lava Flow',11,'6d6'),
    (M+'BOILING_ASH_SKY','Boiling Ash Sky',10,'4d8'),
    (M+'VOLCANIC_ERUPTION','Volcanic Eruption',10,'6d6'),
])
def test_zone_damage_scales_at_lower_levels(key,prefix,cl,dice):
    _,engine,me,foe=_fight(key,cl=cl)
    _cast(engine,prefix);engine.end_turn()
    assert _damage(engine)[0]==dice


@pytest.mark.parametrize('key,prefix',[(L+'CONDUCTIVE_FIELD','Conductive Field'),(M+'BOILING_ASH_SKY','Boiling Ash Sky')])
def test_hostile_fields_do_not_damage_allies(key,prefix):
    _,engine,me,foe=_fight(key)
    ally=_ally(engine,me)
    hp=ally.current_hp
    _cast(engine,prefix)
    zones.on_turn_start(engine,ally)
    assert ally.current_hp==hp
    assert not te.bears_mark(ally,ME,'Charged')


@pytest.mark.parametrize('cl,impact,burn',[(1,'2d8','1d6'),(5,'3d8','1d6'),(11,'5d8','2d6'),(17,'7d8','3d6')])
def test_lava_spit_separates_impact_from_burning(cl,impact,burn):
    _,engine,me,foe=_fight(M+'LAVA_SPIT',cl=cl)
    _cast(engine,'Lava Spit')
    assert _damage(engine)==[impact] and _conditions(foe,'burning')
    engine.end_turn()
    assert _damage(engine)==[impact,burn]
    engine.end_turn()
    assert not _conditions(foe,'burning')


@pytest.mark.parametrize('slug,prefix,dice',[
    ('MAGMA_PRISON','Magma Prison',['2d8','2d8']),
    ('OBSIDIAN_CAGE','Obsidian Cage',['1d8']),
])
def test_prison_damage_waits_and_stops_after_its_shared_repeat_save(slug,prefix,dice):
    _,engine,me,foe=_fight(M+slug)
    _cast(engine,prefix)
    assert _conditions(foe,'restrained') and foe.current_hp==2000
    engine.end_turn()
    assert _damage(engine)==dice
    foe.saving_throws['DEX']=100
    engine.end_turn();engine.end_turn()
    assert not _conditions(foe,'restrained') and _damage(engine)==dice


def test_prison_preserves_restraint_immunity():
    _,engine,me,foe=_fight(M+'MAGMA_PRISON')
    engine.typed_reaction_rows[AN]=[{'block':'condition_immunity','conditions':['restrained']}]
    _cast(engine,'Magma Prison');engine.end_turn()
    assert not _conditions(foe,'restrained') and not _damage(engine)


def test_ending_concentration_stops_prison_damage():
    _,engine,me,foe=_fight(M+'MAGMA_PRISON')
    _cast(engine,'Magma Prison')
    engine._end_concentration(me,'test:stop')
    engine.end_turn()
    assert not _conditions(foe,'restrained') and not _damage(engine)


def test_slag_grasp_uses_the_targets_better_save():
    _,engine,me,foe=_fight(M+'SLAG_GRASP')
    foe.saving_throws.update(STR=-100,DEX=100)
    _cast(engine,'Slag Grasp')
    assert not _conditions(foe,'restrained') and foe.current_hp==2000


@pytest.mark.parametrize('slug,prefix',[
    ('LAVA_BEAST','Lava Beast'),('MANTLE_DRAGON_EMERGES','Mantle Dragon Emerges'),
])
def test_summoning_does_not_attack_or_buff_a_combatant(slug,prefix):
    _,engine,me,foe=_fight(M+slug)
    ally=_ally(engine,me)
    _cast(engine,prefix)
    assert foe.current_hp==2000 and not _damage(engine)
    assert not any(m.target_field in ('armor_class','damage_immunity','damage_resistance') for a in (me,foe,ally) for m in a.modifiers.values())


@pytest.mark.parametrize('key,prefix',[
    (M+'BLACKGLASS_RAMPART','Blackglass Rampart'),
    (M+'FURNACE_MANTLE','Furnace Mantle'),
    (L+'FORMATION_EXTINGUISHING_EDICT','Formation-Extinguishing Edict'),
])
def test_conditional_damage_does_not_fire_at_cast(key,prefix):
    _,engine,me,foe=_fight(key)
    _cast(engine,prefix)
    assert foe.current_hp==2000 and not _damage(engine)


def test_magma_armor_resists_fire_without_global_immunity():
    _,engine,me,foe=_fight(M+'MAGMA_ARMOR')
    _cast(engine,'Magma Armor')
    assert not any(m.target_field=='damage_immunity' for m in me.modifiers.values())
    assert tr.defend(engine,me,20,'FIRE','test:fire',AN)==10


def test_electric_fist_success_does_not_slow_or_deny_all_reactions():
    _,engine,me,foe=_fight(L+'ELECTRIC_FIST_METHOD',dc=-50)
    # The printed trigger is a melee hit; keep the success-branch assertions
    # while exercising the new chosen hit delivery through a real unarmed strike.
    _cast(engine,'Unarmed Strike')
    assert engine._effective_speed(foe)==foe.speed_ft
    assert not _conditions(foe,'reaction_denied')
    assert any('against' in c.condition_id for c in foe.conditions.values())


def test_fivefold_charge_does_not_require_three_failures():
    _,engine,me,foe=_fight(L+'FIVEFOLD_THUNDER_CIRCUIT')
    _cast(engine,'Fivefold Thunder Circuit')
    assert te.bears_mark(foe,ME,'Charged')
    assert not _conditions(foe,'reaction_denied')


def test_flash_step_sets_thirty_feet_of_opportunity_free_movement():
    _,engine,me,foe=_fight(L+'FLASH_STEP')
    _cast(engine,'Flash Step')
    assert me.turn_flags['oa_free_ft']==30


def test_lightning_chains_does_not_damage_the_first_target_twice():
    _,engine,me,foe=_fight(L+'LIGHTNING_CHAINS')
    _mark(engine,foe,'Charged')
    _cast(engine,'Lightning Lash','Lightning Chains')
    assert _damage(engine)==['4d8+2']
    assert not _rolls(engine,'SAVE:')


def test_spirit_circuit_success_places_charge():
    _,engine,me,foe=_fight(L+'SPIRIT_CIRCUIT_SHOCK',dc=-50)
    _cast(engine,'Lightning Lash','Spirit-Circuit Shock')
    assert te.bears_mark(foe,ME,'Charged')


@pytest.mark.parametrize('cl,deafened',[(1,False),(5,True)])
def test_thunderclap_deafens_only_from_foundation(cl,deafened):
    _,engine,me,foe=_fight(L+'THUNDERCLAP_PALM',cl=cl)
    _cast(engine,'Thunderclap Palm')
    assert bool(_conditions(foe,'deafened'))==deafened


def test_true_mantle_adds_twenty_speed_without_instant_movement():
    _,engine,me,foe=_fight(L+'TRUE_LIGHTNING_GOD_MANTLE',extra=(L+'LIGHTNING_GOD_BODY',))
    movement=me.movement_remaining_ft
    _cast(engine,'Lightning-God Body','True Lightning-God Mantle')
    assert engine._effective_speed(me)==me.speed_ft+20
    assert me.movement_remaining_ft==movement


def test_lightning_sovereign_flight_is_not_extra_land_speed_or_instant_movement():
    _,engine,me,foe=_fight(L+'LIGHTNING_SOVEREIGN_INCARNATION')
    movement=me.movement_remaining_ft
    _cast(engine,'Lightning Sovereign Incarnation')
    assert engine._effective_speed(me)==me.speed_ft
    assert me.movement_remaining_ft==movement


def test_body_becomes_thunder_does_not_damage_its_user():
    _,engine,me,foe=_fight('tianxia.talent.lightning.when_potential_becomes_judgment')
    hp=me.current_hp
    _cast(engine,'When Potential Becomes Judgment: Body Becomes Thunder')
    assert me.current_hp==hp and not _damage(engine)


@pytest.mark.parametrize('slug,cl,dice',[
    ('BELL_METAL_COUNTER',5,'2d8+2'),('IRON_SKIN_MOMENT',1,'1d8+4'),('IRON_SKIN_MOMENT',10,'2d8+4'),
])
def test_metal_reactions_reduce_incoming_damage(slug,cl,dice):
    key=T+slug;bundle,engine,me,foe=_fight(key,cl=cl)
    row=next(r for r in bundle['typed_reactions'] if r.get('feature_id')==key)
    remaining,rest=tr._generic_damage_reduction(engine,me,row,100,me)
    rolls=_rolls(engine,'GENERIC_AMOUNT:')
    assert len(rolls)==1 and rolls[0].expression==dice
    assert remaining==100-rolls[0].total
    if slug=='BELL_METAL_COUNTER':assert not any(e.get('type')=='reaction_denied' for e in rest)


def test_iron_bone_temp_hp_includes_twice_pb_and_key():
    _,engine,me,foe=_fight(T+'IRON_BONE_INTERNAL_METHOD')
    _cast(engine,'Iron-Bone Internal Method: Temporary HP')
    assert me.temporary_hp==10


@pytest.mark.parametrize('bloodied',[False,True])
def test_white_tiger_glance_disadvantage_requires_bloodied(bloodied):
    _,engine,me,foe=_fight(T+'WHITE_TIGER_GLANCE')
    if bloodied:foe.current_hp=800
    # Glance's printed prerequisite: the target must be one the owner damaged with a Metal
    # attack or technique this turn (AUTO122 gate). Record that Metal hit before casting.
    _metal_hit_this_turn(engine,me,foe)
    _cast(engine,'White Tiger Glance')
    penalties=[m for m in foe.modifiers.values() if 'attack' in m.target_field and str(m.value)=='DISADVANTAGE']
    assert bool(penalties)==bloodied


@pytest.mark.parametrize('hp,dc,fear,no_heal',[(2000,50,False,False),(800,50,True,True),(800,-50,False,True)])
def test_killing_star_saves_only_when_bloodied_after_damage(hp,dc,fear,no_heal):
    _,engine,me,foe=_fight(T+'WHITE_TIGER_KILLING_STAR',dc=dc)
    foe.current_hp=hp
    _cast(engine,'White Tiger Killing Star')
    assert bool(_conditions(foe,'frightened'))==fear
    before=foe.current_hp
    action=next(iter(engine.action_catalog.values()))
    te.block_healing(te.Context(engine,me,action,None,{'numbers':{}},[foe],foe,{}),{'type':'healing','applies_to':'target','flat':20})
    assert foe.current_hp-before==(0 if no_heal else 20)
