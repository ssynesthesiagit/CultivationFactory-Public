"""Printed Goruden clauses exercised by genuinely acquired source characters."""
import pytest
from combat.factory_compiler import compile_character
from tests.test_mgr_t14_goruden_build import acquire,settle_acquired
from tests.test_mgr_t14_goruden import G
from tests.worker2_support import fixture, reload, turn, settle, candidate, OWNER, ALLY, FOE
from tests.cw2_service_support import add_action, seal


def use(c,t,m,name,target=None,picks=None):
    return settle_acquired(t,m,candidate(c,m,name,target=target).candidate_id,picks=picks)


def acquired_game(catalog_environment, monkeypatch, tmp_path, setup=None, **kwargs):
    bundle=compile_character(acquire(catalog_environment,monkeypatch),actor_id=OWNER,reaction_plan={'ask':True})
    def context(bs):
        for b,i in zip(bs,(100,0,-100)):
            b['actor_template']['initiative_bonus']=i
            seal(b)
        if setup:setup(bs)
    return fixture(tmp_path,[],owner_bundle=bundle,bundle_transform=context,
                   positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':3,'y':7}},
                   battlefield_transform=lambda arena:arena.update(terrain_regions=[],map_objects=[],roof_surfaces=[]),**kwargs)


def test_acquired_named_bodily_saves_and_checks_keep_their_exact_scope(catalog_environment,monkeypatch,tmp_path):
    categories=('disease','poisoned','corrosion','bodily_decay','physical_deformation',
                'crushing','fracture','bone_breaking','fire')
    def setup(bs):
        for check in (False,True):
            for tag in categories:
                effect=({'type':'contest_against','applies_to':'target','actor_check':{'ability':'STR'},
                         'target_check':{'ability':'CON','hazards':[tag]}} if check else
                        {'type':'save','ability':'con','save_categories':[tag],
                         'on_fail':[{'type':'damage','flat':1,'damage_types':['force'],'applies_to':'target'}]})
                add_action(bs[2],f'Bodily {check} {tag}',[effect])
    c,t,m=acquired_game(catalog_environment,monkeypatch,tmp_path,setup)
    turn(t,m,FOE)
    for check in (False,True):
        for tag in categories:
            before=reload(tmp_path,m).state.event_sequence
            use(c,t,m,f'Bodily {check} {tag}',OWNER)
            e=reload(tmp_path,m)
            rolls=[r for r in e.rolls if r.reason.startswith('CHECK:' if check else 'SAVE:') and r.actor_id==OWNER]
            assert rolls and rolls[-1].mode==('NORMAL' if tag=='fire' else 'ADVANTAGE'),(check,tag)
            assert e.state.event_sequence>before


@pytest.mark.parametrize('height,protected',[(12,True),(13,False)])
def test_acquired_gilded_fall_uses_full_distance_beyond_sixty_feet(catalog_environment,monkeypatch,tmp_path,height,protected):
    def setup(bs):
        bs[0]['actor_template']['fly_speed_ft']=30;seal(bs[0])
        add_action(bs[0],'End natural test flight',[{'type':'condition','condition':'test_flight_end','applies_to':'self',
                    'condition_data':{'flight_disabled':1},'duration':{'kind':'minutes','amount':1}}],target='SELF')
    bundle=compile_character(acquire(catalog_environment,monkeypatch),actor_id=OWNER,reaction_plan={'ask':True})
    c,t,m=fixture(tmp_path,[],owner_bundle=bundle,bundle_transform=setup,
        positions={OWNER:{'x':3,'y':6,'z':height},ALLY:{'x':8,'y':6},FOE:{'x':4,'y':6}})
    before=reload(tmp_path,m).state.actors[OWNER].current_hp
    use(c,t,m,'End natural test flight')
    e=reload(tmp_path,m);a=e.state.actors[OWNER]
    assert a.position.z==0
    assert (a.current_hp==before)==protected
    if not protected:
        rolls=[r for r in e.rolls if 'FALL' in r.reason.upper()]
        assert any(r.expression.startswith('6d6') for r in rolls),[(r.reason,r.expression) for r in e.rolls]


@pytest.mark.parametrize('style,spend,expression',[('standard',1,'1d10'),('gilded',1,'2d8'),('standard',4,'4d10'),('gilded',4,'8d8')])
def test_acquired_guard_keeps_payment_reaction_dice_and_post_packet_timing(catalog_environment,monkeypatch,tmp_path,style,spend,expression):
    def setup(bs):add_action(bs[2],'Acquired bone packet',[{'type':'damage','flat':60,'damage_types':['force'],'applies_to':'target'}])
    c,t,m=acquired_game(catalog_environment,monkeypatch,tmp_path,setup)
    turn(t,m,FOE);before=reload(tmp_path,m).state.actors[OWNER]
    use(c,t,m,'Acquired bone packet',OWNER,{'reaction:typed.tianxia.path.body_refining.feature.stamina_guard':[str(spend)],'choice:needle.gilded_guard':[style]})
    e=reload(tmp_path,m);a=e.state.actors[OWNER]
    assert any('DAMAGE_SOAK' in r.reason and r.expression.split('+')[0]==expression for r in e.rolls)
    assert a.resources['resource:core.stamina']==before.resources['resource:core.stamina']-spend
    assert not a.reaction_available
    packet=next(x for x in reversed(e.events) if x.event_type=='DAMAGE_COMMITTED' and OWNER in x.target_ids)
    grants=[x for x in e.events if x.event_type=='TEMP_HP_GRANTED' and x.source_definition_id==G+'gilded_bones']
    assert bool(grants)==(style=='gilded' and packet.payload['hp_damage']>0)
    assert all(x.sequence>packet.sequence for x in grants)
    if grants:assert a.temporary_hp==a.proficiency_bonus


@pytest.mark.parametrize('rider,kinds',[
    ('Extra Radiant Damage',[]),('Extra Radiant Damage',['Undead']),
    ('Extra Radiant Damage',['Fiend']),('Extra Radiant Damage',['Daemonic']),
    ('Extra Radiant Damage',['Undead','Fiend','Daemonic']),
    ('Dim Light',[]),('Deny Invisible',[]),('Temporary Hit Points',[])])
def test_acquired_radiant_options_and_type_qualifications(catalog_environment,monkeypatch,tmp_path,rider,kinds):
    def setup(bs):
        bs[2]['actor_template']['creature_types']=kinds
        bs[2]['actor_template']['armor_class']=0
        bs[2]['actor_template']['maximum_hp']=1000
        seal(bs[2])
    c,t,m=acquired_game(catalog_environment,monkeypatch,tmp_path,setup)
    e=reload(tmp_path,m)
    strike=next(a.display_name for a in e.action_catalog.values() if a.owner_id==OWNER
        and any(r.get('type')=='attack' and r.get('attack_kind')=='unarmed' for r in (a.parameters.get('typed') or {}).get('effects',[])))
    prompts=use(c,t,m,strike,FOE,{'choice:needle.path_hit.'+G+'radiant_fist':[rider]})
    e=reload(tmp_path,m);a=e.state.actors[OWNER]
    assert any(p['context']['reaction_source_id']=='choice:needle.path_hit.'+G+'radiant_fist' for p in prompts)
    damage=[x for x in e.events if x.event_type=='DAMAGE_COMMITTED' and x.payload.get('damage_type')=='RADIANT']
    if rider=='Extra Radiant Damage':assert any(x.payload.get('rolled_or_pending_damage')==a.proficiency_bonus*(2 if kinds else 1) for x in damage)
    else:assert not damage
    assert bool([z for z in e.state.zones.values() if z.active and z.trigger_profile.get('name')=='Radiant Fist: Dim Light'])==(rider=='Dim Light')
    assert any(x.condition_id=='condition:typed.no_invisible_benefit' for x in e.state.actors[FOE].conditions.values())==(rider=='Deny Invisible')
    if rider=='Temporary Hit Points':assert a.temporary_hp==a.proficiency_bonus


@pytest.mark.parametrize('save,result',[(False,'Disadvantage on its next attack'),(False,'Cannot benefit from Invisible'),(False,'No Reactions'),(True,'Cannot benefit from Invisible')])
def test_acquired_aura_every_save_result_and_target_turn_expiry(catalog_environment,monkeypatch,tmp_path,save,result):
    def setup(bs):
        bs[2]['actor_template']['saving_throws']['WIS']=100 if save else -100;seal(bs[2])
    c,t,m=acquired_game(catalog_environment,monkeypatch,tmp_path,setup)
    use(c,t,m,'Golden Aura')
    settle(t,m,t.state(m)['menu']['end_turn'])
    settle(t,m,t.state(m)['menu']['end_turn'],picks={'choice:needle.path_results.golden_aura':[result]})
    e=reload(tmp_path,m);foe=e.state.actors[FOE]
    assert e.state.current_actor_id==FOE
    assert any(x.event_type=='SAVE_ROLLED' and x.actor_id==FOE for x in e.events)
    if result=='Disadvantage on its next attack':assert any(x.target_field=='attack_mode' and x.value=='DISADVANTAGE' for x in foe.modifiers.values())
    elif result=='Cannot benefit from Invisible':assert any(x.condition_id=='condition:typed.no_invisible_benefit' for x in foe.conditions.values())
    else:assert not foe.reaction_available or any(x.condition_id.endswith('reaction_denied') for x in foe.conditions.values())
    move=next(x for x in e.legal_candidates() if x.kind.value=='MOVE' and x.destination and x.destination.x==6 and x.destination.y==7)
    settle(t,m,move.candidate_id)
    settle(t,m,t.state(m)['menu']['end_turn']);turn(t,m,FOE)
    foe=reload(tmp_path,m).state.actors[FOE]
    assert not any(x.target_field=='attack_mode' and x.value=='DISADVANTAGE' for x in foe.modifiers.values())
    assert not any(x.condition_id=='condition:typed.no_invisible_benefit' or x.condition_id.endswith('reaction_denied') for x in foe.conditions.values())
    assert foe.reaction_available


def test_acquired_aura_suppression_does_not_pause_its_minute_or_refund_scene_use(catalog_environment,monkeypatch,tmp_path):
    def setup(bs):
        add_action(bs[0],'Suppress golden field',[{'type':'suppress_area','until':{'rounds':20}}],target='CELL')
        bs[0]['action_catalog'][-1]['parameters']['any_cell']=True;seal(bs[0])
    c,t,m=acquired_game(catalog_environment,monkeypatch,tmp_path,setup)
    use(c,t,m,'Golden Aura')
    e=reload(tmp_path,m);before=e.state.actors[OWNER].resources.copy()
    zone=next(z for z in e.state.zones.values() if z.active and z.owner_id==OWNER)
    zid=zone.zone_id;created=zone.created_round
    settle(t,m,candidate(c,m,'Suppress golden field',at=(3,6)).candidate_id)
    e=reload(tmp_path,m)
    assert e.state.zones[zid].active and not e.state.zones[zid].affected_cells
    assert e.state.zones[zid].created_round==created
    assert not any(x.data.get('rule',{}).get('save_against') for x in e.state.actors[OWNER].conditions.values())
    for _ in range(40):
        e=reload(tmp_path,m)
        if not e.state.zones[zid].active:break
        settle(t,m,t.state(m)['menu']['end_turn'])
    e=reload(tmp_path,m)
    assert not e.state.zones[zid].active
    assert e.state.actors[OWNER].resources==before
    assert not any(x.source_definition_id in e.action_catalog and e.action_catalog[x.source_definition_id].display_name=='Golden Aura' for x in e.legal_candidates())


def test_acquired_sheen_changes_only_visible_intimidation_ability(catalog_environment,monkeypatch,tmp_path):
    from combat.ability_checks import ability_modifier,skill_bonus
    c,t,m=acquired_game(catalog_environment,monkeypatch,tmp_path)
    e=reload(tmp_path,m);actor=e.state.actors[OWNER]
    action=next(a for a in e.action_catalog.values() if a.owner_id==OWNER and a.display_name=='Golden Sheen: Intimidation check')
    numbers=action.parameters['typed']['numbers']
    cha=ability_modifier(actor,'CHA',numbers=numbers);con=ability_modifier(actor,'CON',numbers=numbers)
    baseline=skill_bonus(e,actor,'Intimidation',cha)
    defenses=e._ac_modifier(actor)
    prompts=use(c,t,m,'Golden Sheen: Intimidation check',FOE,{'choice:needle.goruden.intimidation':['CON']})
    e=reload(tmp_path,m)
    event=next(x for x in reversed(e.events) if x.event_type=='CHECK_ROLLED' and x.payload.get('skill')=='Intimidation')
    assert event.payload['ability']=='CON' and event.payload['actor']['modifier']==baseline-cha+con
    before=e.state.actors[OWNER]
    use(c,t,m,'Golden Sheen: Suppress visible gold')
    e=reload(tmp_path,m)
    assert e._ac_modifier(e.state.actors[OWNER])==defenses
    assert e.state.actors[OWNER].action_available==before.action_available
    assert e.state.actors[OWNER].resources==before.resources
    prompts=use(c,t,m,'Golden Sheen: Intimidation check',FOE)
    assert all(o['id']!='CON' for p in prompts if p.get('choice') for o in p['choice']['options'])
    e=reload(tmp_path,m)
    event=next(x for x in reversed(e.events) if x.event_type=='CHECK_ROLLED' and x.payload.get('skill')=='Intimidation')
    assert event.payload['ability']=='CHA' and event.payload['actor']['modifier']==baseline


@pytest.mark.parametrize('decision,outright',[('survive',False),(None,False),('survive',True)])
def test_acquired_immortal_trigger_decline_and_exact_outright_boundary(catalog_environment,monkeypatch,tmp_path,decision,outright):
    def setup(bs):
        hp=bs[0]['actor_template']['maximum_hp']
        add_action(bs[2],'Printed lethal boundary',[{'type':'damage','flat':2*hp if outright else hp+hp//2,
                                                    'damage_types':['force'],'applies_to':'target'}])
    c,t,m=acquired_game(catalog_environment,monkeypatch,tmp_path,setup)
    turn(t,m,FOE);before=reload(tmp_path,m).state.actors[OWNER]
    prompts=use(c,t,m,'Printed lethal boundary',OWNER,{'choice:needle.goruden.immortal_gold':[decision] if decision else None})
    e=reload(tmp_path,m);a=e.state.actors[OWNER]
    assert any(p['context']['reaction_source_id']=='choice:needle.goruden.immortal_gold' for p in prompts)==(not outright)
    survived=decision=='survive' and not outright
    assert (a.current_hp==1)==survived
    assert any(x.condition_id=='condition:typed.golden_statue' for x in a.conditions.values())==survived
    assert a.resources['resource:core.stamina']==before.resources['resource:core.stamina']-(6 if survived else 0)
    if survived:
        assert a.reaction_available
        spent=a.resources.copy();turn(t,m,OWNER);e=reload(tmp_path,m);a=e.state.actors[OWNER]
        assert a.current_hp==1+5*a.proficiency_bonus
        assert a.action_available and a.bonus_action_available and a.reaction_available
        assert a.resources==spent
        assert any(z.active and z.owner_id==OWNER and z.source_definition_id.endswith('golden_aura') for z in e.state.zones.values())
