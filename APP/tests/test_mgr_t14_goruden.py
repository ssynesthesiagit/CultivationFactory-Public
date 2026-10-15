"""Goruden native table choices, committed state and cold mechanical replay."""
import pytest
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, ALLY, FOE
from tests.cw2_service_support import seal

G = 'tianxia.subpath.body.goruden.feature.'
FEATURES = [G+n for n in ('golden_sheen','gilded_bones','radiant_fist','golden_aura','immortal_gold')]

def prepare(bs):
    for b, initiative in zip(bs,(100,0,-100)):
        b['actor_template']['initiative_bonus'] = initiative
        b['actor_template']['maximum_hp'] = 500
        seal(b)

def game(tmp_path, features=FEATURES):
    return fixture(tmp_path, [], cl=18, primary='Stamina', owner_path='Body Refining',
                   owner_features=features, bundle_transform=prepare, named=True,
                   positions={OWNER:{'x':3,'y':6}, ALLY:{'x':4,'y':6}, FOE:{'x':3,'y':7}})

def use(c,t,m,name,target=None,picks=None):
    return settle(t,m,candidate(c,m,name,target=target).candidate_id,picks=picks)

def test_sheen_visibility_is_free_and_persisted(tmp_path):
    c,t,m=game(tmp_path)
    before_engine=reload(tmp_path,m)
    before=before_engine.state.actors[OWNER]
    use(c,t,m,'Golden Sheen: Suppress visible gold')
    e=reload(tmp_path,m); a=e.state.actors[OWNER]
    assert any(x.condition_id=='condition:typed.golden_sheen_suppressed' for x in a.conditions.values())
    assert a.action_available==before.action_available and a.bonus_action_available==before.bonus_action_available
    assert e._ac_modifier(a)==before_engine._ac_modifier(before)
    use(c,t,m,'Golden Sheen: Reveal visible gold')
    assert not any(x.condition_id=='condition:typed.golden_sheen_suppressed' for x in reload(tmp_path,m).state.actors[OWNER].conditions.values())

def test_radiant_fist_fourth_choice_creates_mobile_light(tmp_path):
    c,t,m=game(tmp_path)
    prompts=use(c,t,m,'Unarmed Strike',FOE,{'choice:needle.path_hit.'+G+'radiant_fist':['Dim Light']})
    assert any(any(o['id']=='Dim Light' for o in (p.get('choice') or {}).get('options',[])) for p in prompts)
    e=reload(tmp_path,m)
    lights=[z for z in e.state.zones.values() if z.active and z.trigger_profile.get('name')=='Radiant Fist: Dim Light']
    assert len(lights)==1
    assert lights[0].trigger_profile['anchor_id']==FOE
    assert lights[0].trigger_profile['visual']['light']=={'radius_ft':10,'level':'dim'}
    turn(t,m,FOE)
    e=reload(tmp_path,m)
    move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.movement_cost_ft==5)
    settle(t,m,move.candidate_id)
    e=reload(tmp_path,m)
    assert e.state.zones[lights[0].zone_id].active
    assert e.state.zones[lights[0].zone_id].center==e.state.actors[FOE].position
    turn(t,m,OWNER); assert not reload(tmp_path,m).state.zones[lights[0].zone_id].active

def test_aura_owner_decides_ally_inclusion_and_replays(tmp_path):
    c,t,m=game(tmp_path)
    prompts=use(c,t,m,'Golden Aura',picks={'choice:needle.goruden.aura_ally':['exclude']})
    assert any(p['context']['reaction_source_id']=='choice:needle.goruden.aura_ally' for p in prompts)
    e=reload(tmp_path,m)
    assert not any(c.target_ids==(OWNER,) and e.action_catalog[c.source_definition_id].display_name.startswith('Golden Aura:')
                   for c in e.legal_candidates() if c.source_definition_id in e.action_catalog)
    assert not any((x.data or {}).get('rule',{}).get('save_against') for x in e.state.actors[ALLY].conditions.values())
    assert any((x.data or {}).get('rule',{}).get('save_against') for x in e.state.actors[OWNER].conditions.values())
    use(c,t,m,'Golden Aura: Include ally',ALLY)
    e=reload(tmp_path,m)
    assert any((x.data or {}).get('rule',{}).get('save_against') for x in e.state.actors[ALLY].conditions.values())

@pytest.mark.parametrize('features',[[],[G+'gilded_bones']])
def test_wrong_owner_has_no_sheen_or_aura_commands(tmp_path,features):
    c,t,m=game(tmp_path,features)
    e=reload(tmp_path,m)
    assert not any(a.display_name.startswith(('Golden Sheen:','Golden Aura:')) for a in e.action_catalog.values())

@pytest.mark.parametrize('visible,ability,modifier',[(True,'CON',14),(False,'CHA',8)])
def test_intimidation_preserves_proficiency_and_adjustments(tmp_path,visible,ability,modifier):
    def setup(bs):
        prepare(bs)
        bs[0]['skills']={'Intimidation':8}
        for action in bs[0]['action_catalog']:
            numbers=(action.get('parameters') or {}).get('typed',{}).get('numbers')
            if numbers:
                numbers['ability_mods']={**numbers.get('ability_mods',{}),'CON':5,'CHA':-1}
        seal(bs[0])
    c,t,m=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',
                   owner_features=FEATURES,bundle_transform=setup,
                   positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':3,'y':7}})
    if not visible:
        use(c,t,m,'Golden Sheen: Suppress visible gold')
    use(c,t,m,'Golden Sheen: Intimidation check',FOE,{'choice:needle.goruden.intimidation':[ability]})
    e=reload(tmp_path,m)
    roll=next(x for x in reversed(e.events) if x.event_type=='CHECK_ROLLED' and x.payload.get('skill')=='Intimidation')
    assert roll.payload['actor']['modifier']==modifier
    assert roll.payload['ability']==ability

@pytest.mark.parametrize('damage,survives',[(510,True),(1000,False)])
def test_immortal_gold_final_packet_outright_boundary(tmp_path,damage,survives):
    from tests.cw2_service_support import add_action
    def setup(bs):
        prepare(bs)
        add_action(bs[2],'Lethal trial',[{'type':'damage','flat':damage,'damage_types':['force'],'applies_to':'target'}])
    c,t,m=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',
                   owner_features=FEATURES,bundle_transform=setup)
    turn(t,m,FOE)
    prompts=use(c,t,m,'Lethal trial',OWNER,{'choice:needle.goruden.immortal_gold':['survive'], 'reaction:typed.'+G+'immortal_gold':'first'})
    e=reload(tmp_path,m); a=e.state.actors[OWNER]
    assert (a.current_hp==1) is survives
    assert any(x.condition_id=='condition:typed.golden_statue' for x in a.conditions.values()) is survives
    assert any(p['context']['reaction_source_id']=='choice:needle.goruden.immortal_gold' for p in prompts) is survives
    if survives:
        assert a.resources['resource:core.stamina']==94
        assert a.reaction_available
        turn(t,m,OWNER)
        e=reload(tmp_path,m);a=e.state.actors[OWNER]
        assert a.current_hp==21
        assert not any(x.condition_id=='condition:typed.golden_statue' for x in a.conditions.values())
        assert any(z.active and z.source_definition_id.endswith('golden_aura') for z in e.state.zones.values())
        assert a.resources['resource:core.stamina']==94

@pytest.mark.parametrize('style,spend,expression',[('standard',1,'1d10'),('gilded',1,'2d8'),('standard',4,'4d10'),('gilded',4,'8d8')])
def test_gilded_guard_real_packet_choice_cost_and_after_damage_hp(tmp_path,style,spend,expression):
    from tests.cw2_service_support import add_action
    guard='tianxia.path.body_refining.feature.stamina_guard'
    def setup(bs):
        prepare(bs)
        add_action(bs[2],'Bone trial',[{'type':'damage','flat':80,'damage_types':['bludgeoning'],'applies_to':'target'}])
    c,t,m=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',
        owner_features=[*FEATURES,guard],bundle_transform=setup)
    turn(t,m,FOE)
    prompts=use(c,t,m,'Bone trial',OWNER,{'reaction:typed.'+guard:[str(spend)],'choice:needle.gilded_guard':[style]})
    offered=next(p for p in prompts if p['context']['reaction_source_id']=='reaction:typed.'+guard)
    ids={o['id'] for o in offered['choice']['options']}
    assert '4' in ids and '5' not in ids
    e=reload(tmp_path,m);a=e.state.actors[OWNER]
    roll=next(x for x in e.rolls if x.reason=='DAMAGE_SOAK:'+guard)
    assert roll.expression.split('+')[0]==expression
    assert a.resources['resource:core.stamina']==100-spend
    assert a.temporary_hp==(4 if style=='gilded' else 0)
    damage=next(x for x in e.events if x.event_type=='DAMAGE_COMMITTED' and OWNER in x.target_ids)
    assert damage.payload['temporary_hp_absorbed']==0
    if style=='gilded':
        thp=next(x for x in e.events if x.event_type=='TEMP_HP_GRANTED' and OWNER in x.target_ids)
        assert thp.sequence>damage.sequence


def test_aura_next_attack_is_consumed_on_miss_and_target_clock(tmp_path):
    def setup(bs):
        prepare(bs)
        bs[0]['actor_template']['armor_class']=1000
        bs[2]['actor_template']['saving_throws']['WIS']=-100
        seal(bs[0]);seal(bs[2])
    c,t,m=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',owner_dc=100,
        owner_features=FEATURES,bundle_transform=setup,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':3,'y':7}})
    use(c,t,m,'Golden Aura')
    turn(t,m,FOE)
    e=reload(tmp_path,m);foe=e.state.actors[FOE]
    penalty=next(x for x in foe.modifiers.values() if x.target_field=='attack_mode' and x.value=='DISADVANTAGE')
    assert (FOE in penalty.expires_on or
            penalty.expires_on=='START_OF_SOURCE_NEXT_TURN' and penalty.source_actor_id==FOE)
    use(c,t,m,'Unarmed Strike',OWNER)
    e=reload(tmp_path,m)
    assert not any(x.target_field=='attack_mode' and x.value=='DISADVANTAGE' for x in e.state.actors[FOE].modifiers.values())
    attack=next(x for x in reversed(e.events) if x.event_type=='ATTACK_ROLLED' and x.actor_id==FOE)
    assert attack.payload['mode']=='DISADVANTAGE'
    assert attack.payload['total'] < 1000 and attack.payload['natural_result'] != 20


@pytest.mark.parametrize('rider',['Extra Radiant Damage','Deny Invisible','Temporary Hit Points'])
def test_radiant_other_options_and_only_one_doubling(tmp_path,rider):
    from tests.h1_support import sheet
    foe=sheet([],cl=18)
    foe['identity']['creature_types']=['Undead','Fiend','Daemonic']
    c,t,m=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',owner_features=FEATURES,
        foe_sheet=foe,bundle_transform=prepare,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':3,'y':7}})
    use(c,t,m,'Unarmed Strike',FOE,{'choice:needle.path_hit.'+G+'radiant_fist':[rider]})
    e=reload(tmp_path,m)
    if rider=='Extra Radiant Damage':
        assert any(x.event_type=='DAMAGE_COMMITTED' and x.payload.get('damage_type')=='RADIANT'
                   and x.payload.get('rolled_or_pending_damage')==8 for x in e.events)
    elif rider=='Deny Invisible':
        assert any(x.condition_id=='condition:typed.no_invisible_benefit' for x in e.state.actors[FOE].conditions.values())
        turn(t,m,FOE)
        assert any(x.condition_id=='condition:typed.no_invisible_benefit' for x in reload(tmp_path,m).state.actors[FOE].conditions.values())
        turn(t,m,OWNER)
        assert not any(x.condition_id=='condition:typed.no_invisible_benefit' for x in reload(tmp_path,m).state.actors[FOE].conditions.values())
    else:
        assert e.state.actors[OWNER].temporary_hp==4
        assert not any(x.condition_id=='condition:typed.no_invisible_benefit' for x in e.state.actors[FOE].conditions.values())


def test_invisible_denial_preserves_another_cultivator_source(tmp_path):
    def accurate(bs):
        prepare(bs)
        for bundle in bs[:2]:
            for action in bundle['action_catalog']:
                typed=(action.get('parameters') or {}).get('typed') or {}
                if any(e.get('type')=='attack' and e.get('attack_kind')=='unarmed' for e in typed.get('effects') or []):
                    typed['numbers']['attack_bonus']=100
            seal(bundle)
    c,t,m=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',owner_features=FEATURES,
        ally_talents=[G+'radiant_fist'],bundle_transform=accurate,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':7},FOE:{'x':3,'y':7}})
    use(c,t,m,'Unarmed Strike',FOE,{'choice:needle.path_hit.'+G+'radiant_fist':['Deny Invisible']})
    turn(t,m,ALLY)
    use(c,t,m,'Unarmed Strike',FOE,{'choice:needle.path_hit.'+G+'radiant_fist':['Deny Invisible']})
    e=reload(tmp_path,m)
    assert {x.source_actor_id for x in e.state.actors[FOE].conditions.values()
            if x.condition_id=='condition:typed.no_invisible_benefit'}=={OWNER,ALLY}


def test_immortal_gold_free_aura_replaces_old_activation_without_refund(tmp_path):
    from tests.cw2_service_support import add_action
    def setup(bs):
        prepare(bs)
        add_action(bs[2],'Lethal trial',[{'type':'damage','flat':510,'damage_types':['force'],'applies_to':'target'}])
    c,t,m=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',
                   owner_features=FEATURES,bundle_transform=setup)
    use(c,t,m,'Golden Aura')
    old=next(z.zone_id for z in reload(tmp_path,m).state.zones.values() if z.active)
    turn(t,m,FOE)
    use(c,t,m,'Lethal trial',OWNER,{'choice:needle.goruden.immortal_gold':['survive'], 'reaction:typed.'+G+'immortal_gold':'first'})
    turn(t,m,OWNER)
    e=reload(tmp_path,m)
    assert not e.state.zones[old].active
    assert len([z for z in e.state.zones.values() if z.active and z.owner_id==OWNER])==1
    assert e.state.actors[OWNER].resources['resource:core.stamina']==89
    assert not any(e.action_catalog[x.source_definition_id].display_name=='Golden Aura' for x in e.legal_candidates()
                   if x.source_definition_id in e.action_catalog)


def test_immortal_gold_is_not_a_reaction(tmp_path):
    from tests.cw2_service_support import add_action
    def setup(bs):
        prepare(bs)
        add_action(bs[2],'Reactionless lethal trial',[
            {'type':'reaction_denied','applies_to':'target','duration':{'kind':'minutes','amount':1}},
            {'type':'damage','flat':510,'damage_types':['force'],'applies_to':'target'}])
    c,t,m=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',
                   owner_features=FEATURES,bundle_transform=setup)
    turn(t,m,FOE)
    use(c,t,m,'Reactionless lethal trial',OWNER,{'choice:needle.goruden.immortal_gold':['survive']})
    e=reload(tmp_path,m)
    assert e.state.actors[OWNER].current_hp==1
    assert e.state.actors[OWNER].resources['resource:core.stamina']==94


@pytest.mark.parametrize('source_cl,stopped',[(17,True),(18,False),(19,False)])
def test_statue_movement_from_actual_lethal_event_uses_source_cl(tmp_path,source_cl,stopped):
    from tests.cw2_service_support import add_action
    def setup(bs):
        prepare(bs)
        add_action(bs[2],'Lethal push',[
            {'type':'damage','flat':510,'damage_types':['force'],'applies_to':'target'},
            {'type':'forced_movement','applies_to':'target','distance_ft':10}],
            typed={'numbers':{'cl':source_cl,'pb':4,'key_mod':100,'save_dc':16}})
    c,t,m=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',owner_features=FEATURES,
        bundle_transform=setup,positions={OWNER:{'x':3,'y':6},ALLY:{'x':8,'y':6},FOE:{'x':3,'y':7}})
    initial=reload(tmp_path,m).state.actors[OWNER].position
    turn(t,m,FOE)
    use(c,t,m,'Lethal push',OWNER,{'choice:needle.goruden.immortal_gold':['survive']})
    e=reload(tmp_path,m)
    assert (e.state.actors[OWNER].position==initial) is stopped
    contests=[x for x in e.events if x.event_type=='CHECK_ROLLED' and x.payload.get('roll_kind')=='opposed_check']
    assert len(contests)==(0 if stopped else 1)


def test_statue_resistances_and_immunities_after_actual_replacement(tmp_path):
    from tests.cw2_service_support import add_action
    def setup(bs):
        prepare(bs)
        add_action(bs[2],'Statue damage trials',[
            {'type':'damage','flat':510,'damage_types':['force'],'applies_to':'target'},
            {'type':'healing','flat':40,'applies_to':'target'},
            *[{'type':'damage','flat':40,'damage_types':[kind],'applies_to':'target'} for kind in ('fire','poison','psychic')]])
    c,t,m=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',owner_features=FEATURES,bundle_transform=setup)
    turn(t,m,FOE)
    use(c,t,m,'Statue damage trials',OWNER,{'choice:needle.goruden.immortal_gold':['survive']})
    e=reload(tmp_path,m)
    damages=[x.payload for x in e.events if x.event_type=='DAMAGE_COMMITTED' and OWNER in x.target_ids]
    assert [(p['damage_type'].upper(),p['reduced_to']) for p in damages[-3:]]==[('FIRE',20),('POISON',0),('PSYCHIC',0)]
    assert e.state.actors[OWNER].current_hp==21


def test_aura_continuous_benefits_end_on_exit_but_temporary_hp_remains(tmp_path):
    from tests.cw2_service_support import add_action
    def setup(bs):
        prepare(bs)
        add_action(bs[2],'Push ally out',[{'type':'forced_movement','applies_to':'target','distance_ft':20}])
    c,t,m=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',owner_features=FEATURES,
        bundle_transform=setup,battlefield_transform=lambda arena: arena.update(terrain_regions=[],map_objects=[],roof_surfaces=[]),
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':3,'y':7}})
    use(c,t,m,'Golden Aura')
    turn(t,m,ALLY)
    a=reload(tmp_path,m).state.actors[ALLY]
    assert a.temporary_hp==4 and any(x.target_field=='damage_resistance' and x.value=='NECROTIC' for x in a.modifiers.values())
    turn(t,m,FOE)
    use(c,t,m,'Push ally out',ALLY)
    e=reload(tmp_path,m);a=e.state.actors[ALLY]
    assert e.grid.distance_ft(e.state.actors[OWNER].position,a.position)>10
    assert a.temporary_hp==4
    assert not any(x.target_field=='damage_resistance' and x.value=='NECROTIC' for x in a.modifiers.values())


def test_manual_aura_owner_keeps_failed_save_choice_on_an_ai_turn(tmp_path):
    def setup(bs):
        prepare(bs)
        bs[2]['actor_template']['saving_throws']['WIS']=-100
        seal(bs[2])
    c,t,m=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',owner_features=FEATURES,
        bundle_transform=setup,modes={OWNER:'MANUAL',ALLY:'MANUAL',FOE:'LOCAL_AUTO'},
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':3,'y':7}})
    use(c,t,m,'Golden Aura')
    turn(t,m,ALLY)
    end=t.state(m)['menu']['end_turn']
    prompts=settle(t,m,end,picks={'choice:needle.path_results.golden_aura':['No Reactions']})
    assert any(p['context']['reactor_id']==OWNER and p['context']['reaction_source_id']=='choice:needle.path_results.golden_aura' for p in prompts)
    e=reload(tmp_path,m)
    assert any(x.condition_id=='condition:typed.reaction_denied' for x in e.state.actors[FOE].conditions.values())


def test_intimidation_does_not_borrow_constitution_save_proficiency(tmp_path):
    def setup(bs):
        prepare(bs)
        bs[0]['skills']={'Intimidation':8}
        bs[0]['actor_template']['saving_throws']['CON']=8
        seal(bs[0])
    c,t,m=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',owner_features=FEATURES,
        bundle_transform=setup,positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':3,'y':7}})
    use(c,t,m,'Golden Sheen: Intimidation check',FOE,{'choice:needle.goruden.intimidation':['CON']})
    e=reload(tmp_path,m)
    event=next(x for x in reversed(e.events) if x.event_type=='CHECK_ROLLED' and x.payload.get('skill')=='Intimidation')
    assert event.payload['ability']=='CON' and event.payload['actor']['modifier']==8


def test_legacy_sealed_survival_row_keeps_its_original_choice_transport(tmp_path):
    from tests.cw2_service_support import add_action
    def setup(bs):
        prepare(bs)
        bs[0]['typed_passives']=[r for r in bs[0]['typed_passives'] if r.get('kind')!='immortal_gold_final']
        for a in bs[0]['action_catalog']:
            (a.get('parameters') or {}).get('typed',{}).pop('golden_ally_choices',None)
        seal(bs[0])
        add_action(bs[2],'Legacy lethal trial',[{'type':'damage','flat':510,'damage_types':['force'],'applies_to':'target'}])
    c,t,m=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',owner_features=FEATURES,bundle_transform=setup)
    turn(t,m,FOE)
    prompts=use(c,t,m,'Legacy lethal trial',OWNER,{'reaction:typed.'+G+'immortal_gold':'first'})
    e=reload(tmp_path,m)
    assert e.state.actors[OWNER].current_hp==1
    assert not any(p['context']['reaction_source_id']=='choice:needle.goruden.immortal_gold' for p in prompts)


@pytest.mark.parametrize('confirm,wait,expected',[(True,False,8),(False,False,4),(True,True,4)])
def test_active_corruption_is_a_confirmed_native_source_not_a_name(tmp_path,confirm,wait,expected):
    from tests.cw2_service_support import add_action
    def setup(bs):
        prepare(bs)
        bs[2]['actor_template']['display_name']='Daemonic corruption is only this creature’s name'
        add_action(bs[2],'Declare active corruption',[
            {'type':'information_source','applies_to':'self','tags':['daemonic_corruption'],
             'requires_declaration':1,'declaration_prompt':'As this creature’s native owner, confirm that this source currently bears active daemonic corruption.',
             'expires_on':'START_OF_SOURCE_NEXT_TURN'}],target='SELF')
        seal(bs[2])
    c,t,m=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',owner_features=FEATURES,
        bundle_transform=setup,positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':3,'y':7}})
    turn(t,m,FOE)
    # The declaration is a real owner-bound choice in an accepted native action;
    # no test directly inserts a source/condition or manufactures a receipt.
    prompts=use(c,t,m,'Declare active corruption',FOE,
                {'choice:needle.information_declaration':['confirm'] if confirm else None})
    e=reload(tmp_path,m)
    declarations=[x for x in e.state.actors[FOE].conditions.values() if x.condition_id=='condition:information.source']
    assert bool(declarations) is confirm
    assert prompts
    if declarations:
        assert declarations[0].data['authority_actor_id']==FOE
        assert declarations[0].source_actor_id==FOE
    turn(t,m,OWNER)
    if wait:
        turn(t,m,FOE);turn(t,m,OWNER)
    use(c,t,m,'Unarmed Strike',FOE,{'choice:needle.path_hit.'+G+'radiant_fist':['Extra Radiant Damage']})
    e=reload(tmp_path,m)
    extras=[x.payload['rolled_or_pending_damage'] for x in e.events if x.event_type=='DAMAGE_COMMITTED'
            and x.actor_id==OWNER and x.payload.get('damage_type')=='RADIANT']
    assert extras[-1]==expected


@pytest.mark.parametrize('disease,mode',[(False,'NORMAL'),(True,'ADVANTAGE')])
def test_sickened_is_not_inferred_to_be_a_disease_source(tmp_path,disease,mode):
    from tests.cw2_service_support import add_action
    def setup(bs):
        prepare(bs)
        add_action(bs[2],'Nausea trial',[{'type':'save','ability':'con',
            'save_categories':['disease'] if disease else [],
            'on_fail':[{'type':'condition','condition':'sickened','applies_to':'target'}]}])
    c,t,m=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',owner_features=FEATURES,bundle_transform=setup)
    turn(t,m,FOE)
    use(c,t,m,'Nausea trial',OWNER)
    e=reload(tmp_path,m)
    saves=[r for r in e.rolls if r.actor_id==OWNER and r.reason.startswith('SAVE:')]
    assert saves[-1].mode==mode


def test_sheen_cosmetic_setting_commits_off_turn_without_spending_a_turn(tmp_path):
    c,t,m=game(tmp_path)
    turn(t,m,FOE)
    e=reload(tmp_path,m)
    source=next(a.source_definition_id for a in e.action_catalog.values()
                if a.owner_id==OWNER and a.display_name=='Golden Sheen: Suppress visible gold')
    before=e.state.actors[OWNER].model_dump(mode='json')
    t.save_settings(m,OWNER,[source],'goruden-off-turn')
    e=reload(tmp_path,m)
    assert any(x.condition_id=='condition:typed.golden_sheen_suppressed' for x in e.state.actors[OWNER].conditions.values())
    for key in ('action_available','bonus_action_available','reaction_available','movement_remaining_ft','resources'):
        assert e.state.actors[OWNER].model_dump(mode='json')[key]==before[key]
    t.save_settings(m,OWNER,[source],'goruden-off-turn')
    assert reload(tmp_path,m).state.event_sequence==e.state.event_sequence


@pytest.mark.parametrize('selected,expected',[(None,0),('tianxia.path.body_refining.feature.unarmored_defense',1)])
def test_sheen_requires_native_selected_unarmored_defense_not_just_no_armor(tmp_path,selected,expected):
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    doc=sheet([],cl=18,primary='Stamina')
    doc.setdefault('path_and_subpath',{})['path_feature_record_ids']=[G+'golden_sheen']
    doc['ability_scores_and_statistics']['armor_class']['generation']={
        'calculation_feature_id':selected,'always_on_bonuses':[]}
    bundle=compile_character(doc,actor_id=OWNER,reaction_plan={'ask':True})
    c,t,m=fixture(tmp_path,[],cl=18,primary='Stamina',owner_bundle=bundle,bundle_transform=prepare)
    e=reload(tmp_path,m)
    passive=next(r for r in e.typed_passive_rows[OWNER] if r.get('kind')=='golden_sheen')
    assert passive['unarmored_defense_selected'] is bool(selected)
    assert e._ac_modifier(e.state.actors[OWNER])==expected


@pytest.mark.parametrize('restriction,healed,aura',[('none',0,False),('half',10,True)])
def test_immortal_restoration_uses_actual_healing_restrictions(tmp_path,restriction,healed,aura):
    from tests.cw2_service_support import add_action
    def setup(bs):
        prepare(bs)
        add_action(bs[2],'Restricted restoration trial',[
            {'type':'damage','flat':510,'damage_types':['force'],'applies_to':'target'},
            {'type':'healing_reduction','applies_to':'target',
             'evidence':('The target cannot regain Hit Points.' if restriction=='none' else 'Healing received is halved.'),
             'expires_on':'END_OF_SOURCE_NEXT_TURN'}])
    c,t,m=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',owner_features=FEATURES,bundle_transform=setup)
    turn(t,m,FOE)
    use(c,t,m,'Restricted restoration trial',OWNER,{'choice:needle.goruden.immortal_gold':['survive'],'reaction:typed.'+G+'immortal_gold':'first'})
    e=reload(tmp_path,m)
    assert any(x.target_field=='healing_reduction' for x in e.state.actors[OWNER].modifiers.values())
    turn(t,m,OWNER)
    e=reload(tmp_path,m)
    assert e.state.actors[OWNER].current_hp==1+healed
    assert not any(x.condition_id=='condition:typed.golden_statue' for x in e.state.actors[OWNER].conditions.values())
    assert any(z.active and z.source_definition_id.endswith('golden_aura') for z in e.state.zones.values()) is aura



def test_unowned_statue_effect_cannot_grant_immortal_gold(tmp_path):
    from tests.cw2_service_support import add_action
    def setup(bs):
        prepare(bs)
        add_action(bs[2],'Unowned statue claim',[{'type':'golden_statue'}],target='SELF')
    c,t,m=fixture(tmp_path,[],cl=18,bundle_transform=setup)
    turn(t,m,FOE)
    use(c,t,m,'Unowned statue claim',FOE)
    e=reload(tmp_path,m)
    assert not any(x.condition_id=='condition:typed.golden_statue' for x in e.state.actors[FOE].conditions.values())
    claim=next(a.source_definition_id for a in e.action_catalog.values() if a.display_name=='Unowned statue claim')
    assert not any(x.source_definition_id==claim for x in e.state.actors[FOE].modifiers.values())



def test_gilded_bones_thp_is_once_per_round_across_reaction_refresh(tmp_path):
    from tests.cw2_service_support import add_action
    guard='tianxia.path.body_refining.feature.stamina_guard'
    def setup(bs):
        prepare(bs)
        for b,initiative in zip(bs,(0,-100,100)):
            b['actor_template']['initiative_bonus']=initiative
            seal(b)
        for b in bs[1:]:
            add_action(b,'Guard round trial',[{'type':'damage','flat':40,'damage_types':['force'],'applies_to':'target'}])
    c,t,m=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',owner_features=FEATURES,
                   bundle_transform=setup,team_overrides={ALLY:'team:opponents'})
    turn(t,m,FOE)
    use(c,t,m,'Guard round trial',OWNER,{'reaction:typed.'+guard:['1'],'choice:needle.gilded_guard':['gilded']})
    e=reload(tmp_path,m);round_number=e.state.round_number
    assert e.state.actors[OWNER].temporary_hp==4
    turn(t,m,OWNER)
    assert reload(tmp_path,m).state.actors[OWNER].reaction_available
    turn(t,m,ALLY)
    use(c,t,m,'Guard round trial',OWNER,{'reaction:typed.'+guard:['1'],'choice:needle.gilded_guard':['gilded']})
    e=reload(tmp_path,m)
    assert e.state.round_number==round_number
    assert e.state.actors[OWNER].temporary_hp==0
    grants=[x for x in e.events if x.event_type=='TEMP_HP_GRANTED' and x.source_definition_id==G+'gilded_bones']
    assert len(grants)==1
    turn(t,m,FOE);turn(t,m,OWNER);turn(t,m,ALLY)
    use(c,t,m,'Guard round trial',OWNER,{'reaction:typed.'+guard:['1'],'choice:needle.gilded_guard':['gilded']})
    e=reload(tmp_path,m)
    assert e.state.round_number==round_number+1
    assert e.state.actors[OWNER].temporary_hp==4



def test_live_zero_hp_statue_recovers_on_its_actual_next_turn(tmp_path):
    from tests.cw2_service_support import add_action
    def setup(bs):
        prepare(bs)
        add_action(bs[2],'Survival then zero',[
            {'type':'damage','flat':510,'damage_types':['force'],'applies_to':'target'},
            {'type':'damage','flat':2,'damage_types':['force'],'applies_to':'target'}])
    c,t,m=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',owner_features=FEATURES,bundle_transform=setup)
    turn(t,m,FOE)
    use(c,t,m,'Survival then zero',OWNER,{'choice:needle.goruden.immortal_gold':['survive'],'reaction:typed.'+G+'immortal_gold':'first'})
    e=reload(tmp_path,m);a=e.state.actors[OWNER]
    assert a.current_hp==0 and a.active and a.life_state=='DYING'
    assert any(x.condition_id=='condition:typed.golden_statue' for x in a.conditions.values())
    turn(t,m,OWNER)
    e=reload(tmp_path,m);a=e.state.actors[OWNER]
    assert a.current_hp==5*a.proficiency_bonus and a.life_state=='CONSCIOUS'
    assert not any(x.condition_id=='condition:typed.golden_statue' for x in a.conditions.values())
    assert a.action_available and a.bonus_action_available and a.reaction_available
    assert a.movement_remaining_ft>0
    assert any(z.active and z.source_definition_id.endswith('golden_aura') for z in e.state.zones.values())



@pytest.mark.parametrize('benefit',['necrotic','frightened','fire','disease'])
def test_aura_inclusion_can_change_at_the_actual_benefit_not_only_turn_start(tmp_path,benefit):
    from tests.cw2_service_support import add_action
    def setup(bs):
        prepare(bs)
        effect=({'type':'damage','flat':40,'damage_types':[benefit],'applies_to':'target'}
                if benefit in ('necrotic','fire') else
                {'type':'save','ability':'wis','save_categories':[benefit],
                 'on_fail':[{'type':'condition','condition':('frightened' if benefit=='frightened' else 'sickened'),'applies_to':'target'}]})
        add_action(bs[2],'Aura benefit trial',[effect])
    c,t,m=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Refining',owner_features=FEATURES,
                   bundle_transform=setup,positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':3,'y':7}})
    use(c,t,m,'Golden Aura',picks={'choice:needle.goruden.aura_ally':['exclude']})
    # Keep the ally excluded on its turn; the later packet/save is a genuinely
    # separate benefit moment, and neither movement nor a new turn can opt it in.
    settle(t,m,t.state(m)['menu']['end_turn'],picks={'choice:needle.goruden.aura_ally':['exclude']})
    settle(t,m,t.state(m)['menu']['end_turn'])
    before=reload(tmp_path,m)
    assert not any((x.data or {}).get('rule',{}).get('save_against') for x in before.state.actors[ALLY].conditions.values())
    prompts=use(c,t,m,'Aura benefit trial',ALLY,{'choice:needle.goruden.aura_ally':['include']})
    offered=any(p['context']['reaction_source_id']=='choice:needle.goruden.aura_ally' for p in prompts)
    assert offered is (benefit in ('necrotic','frightened'))
    e=reload(tmp_path,m)
    if benefit in ('necrotic','fire'):
        packet=next(x.payload for x in reversed(e.events) if x.event_type=='DAMAGE_COMMITTED' and ALLY in x.target_ids)
        assert packet['reduced_to']==(20 if benefit=='necrotic' else 40)
        assert packet['temporary_hp_absorbed']==0
    else:
        save=next(r for r in reversed(e.rolls) if r.actor_id==ALLY and r.reason.startswith('SAVE:'))
        assert save.mode==('ADVANTAGE' if benefit=='frightened' else 'NORMAL')
