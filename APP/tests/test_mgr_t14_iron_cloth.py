"""Iron Cloth native compilation, table choice, committed state and cold replay."""
import pytest
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, ALLY, FOE
PREFIX='tianxia.subpath.qi.iron_cloth_cultivator.feature.'
SILKEN,BINDING,FLOWING,PRISON,THOUSAND=[PREFIX+x for x in ('silken_whip','binding_ribbon','flowing_silk','silken_prison','thousand_ribbons')]
CLOTH={'starting_kit':{'items':[{'item_id':'tianxia.mortal.gear.robe','name':'Robe','quantity':1}]}}
QI='resource:core.qi'
CHOICE='choice:needle.iron_cloth.'


def native_diagnostic(test):
    from functools import wraps
    @wraps(test)
    def run(*args,**kwargs):
        from combat.gate5_service import CombatServiceError
        try:
            return test(*args,**kwargs)
        except CombatServiceError as error:
            raise AssertionError('Native runtime reason: '+str(error.diagnostic.details.get('reason'))+'; '+str(error.to_dict())) from error
    return run


@pytest.fixture(scope='module',autouse=True)
def native_source_identity(request):
    from pathlib import Path
    import hashlib,json
    root=Path(__file__).resolve().parents[1]
    paths=('combat/ext/silken_whip.py','combat/fact_consent_admission.py','combat/asset_anchor_runtime.py',
           'combat/carry.py','combat/senses.py','combat/journey.py','combat/typed_executor.py',
           'combat/rules/feature_blocks.d/sysv2_objects.json','combat/rules/feature_blocks.d/shi.json')
    identity={p:hashlib.sha256((root/p).read_bytes()).hexdigest() if (root/p).exists() else 'MISSING' for p in paths}
    terminal=request.config.pluginmanager.get_plugin('terminalreporter')
    if terminal is not None:
        terminal.write_line('IRON_CLOTH_NATIVE_SOURCE '+json.dumps(identity,sort_keys=True))


def play(tmp_path,features,**kw):
    # Deterministic branch defenders use the native sheet's explicit final save
    # totals, before ZIP acquisition/compilation. The source's own DC and attack
    # stay its printed PB + Qi key formula; no roll or trigger is fabricated.
    if kw.get('owner_dc') in (1,100):
        from copy import deepcopy
        from tests.h1_support import sheet
        saves={k:(-100 if kw['owner_dc']==100 else 100) for k in ('STR','DEX','CON','INT','WIS','CHA')}
        defender=deepcopy(kw.get('foe_sheet') or sheet([],cl=kw.get('cl',18),key='CHA',kit=kw.get('foe_kit'),name='Mara'))
        defender['ability_scores_and_statistics']['saving_throws']=saves
        kw['foe_sheet']=defender
        kw['ally_saves']=saves
    from combat.gate5_service import CombatServiceError
    try:
        return fixture(tmp_path,features,owner_kit=kw.pop('owner_kit',CLOTH),cl=kw.pop('cl',18),named=True,owner_key='CHA',**kw)
    except CombatServiceError as error:
        raise AssertionError('Native runtime reason: '+str(error.diagnostic.details.get('reason'))+'; '+str(error.to_dict())) from error


def use(combat,table,mid,name,**kw):
    from combat.gate5_service import CombatServiceError
    # Explicit owner fact input when a scenario also supplies other optional choices.
    # The common settle helper intentionally defaults unknown optional facts to refusal.
    if kw.get('choices') is not None:
        kw['choices']={'choice:needle.fact_admission.iron_cloth_fabric':['flexible_fabric'],**kw['choices']}
    try:
        c=candidate(combat,mid,name,**{k:kw.pop(k) for k in list(kw) if k in ('target','at')})
        return settle(table,mid,c.candidate_id,**kw)
    except CombatServiceError as error:
        raise AssertionError('Native runtime reason: '+str(error.diagnostic.details.get('reason'))+'; '+str(error.to_dict())) from error


def whip_of(e):
    return next((c for c in e.state.actors[OWNER].conditions.values() if c.condition_id=='condition:typed.silken_whip'),None)


def test_native_infusion_names_one_real_carried_item_and_reloads(tmp_path):
    combat,table,mid=play(tmp_path,[SILKEN])
    e=reload(tmp_path,mid);before=e.state.actors[OWNER].resources[QI]
    prompts=use(combat,table,mid,'Silken Whip')
    e=reload(tmp_path,mid);w=whip_of(e)
    assert any(p['context']['reaction_source_id']==CHOICE+'fabric' for p in prompts)
    assert w.data['item_key']=='tianxia.mortal.gear.robe'
    assert w.data['declaration_authority']=='item_owner' and w.data['declaration_actor']==OWNER
    assert w.expires_on!='UNTIL_REMOVED' and e.state.actors[OWNER].resources[QI]==before-1
    assert not any(c.display_name=='Silken Whip' for c in e.legal_candidates())
    use(combat,table,mid,'Silken Whip: end infusion')
    assert whip_of(reload(tmp_path,mid)) is None


@pytest.mark.parametrize('cl,kit',[(2,CLOTH),(3,None)])
def test_infusion_requires_native_level_and_carried_item(tmp_path,cl,kit):
    combat,table,mid=fixture(tmp_path,[SILKEN],cl=cl,owner_kit=kit)
    e=reload(tmp_path,mid)
    assert not any(c.display_name in ('Silken Whip','Silken Whip Attack') for c in e.legal_candidates())


def test_wrong_owner_is_inert(tmp_path):
    combat,table,mid=fixture(tmp_path,[],owner_kit=CLOTH,cl=18)
    e=reload(tmp_path,mid)
    assert not any('iron_cloth' in a.source_definition_id for a in e.action_catalog.values())
    assert not any('iron_cloth' in c.condition_id for a in e.state.actors.values() for c in a.conditions.values())


def test_binding_real_hit_choice_payment_failed_save_and_release(tmp_path):
    combat,table,mid=play(tmp_path,[SILKEN,BINDING],seed='IRON-BIND',owner_dc=100)
    use(combat,table,mid,'Silken Whip')
    before=reload(tmp_path,mid).state.actors[OWNER].resources[QI]
    for _ in range(6):
        prompts=use(combat,table,mid,'Silken Whip Attack',target=FOE)
        e=reload(tmp_path,mid)
        if any(c.data.get('binding') for c in e.state.actors[FOE].conditions.values()):break
        settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    else:pytest.fail('No qualifying whip hit')
    assert any(p['context']['reaction_source_id']==CHOICE+'bind_hit' for p in prompts)
    assert e.state.actors[OWNER].resources[QI]==before-2
    assert e._effective_speed(e.state.actors[FOE])==0
    use(combat,table,mid,'Binding Ribbon: release')
    e=reload(tmp_path,mid)
    assert not any(c.data.get('binding') for c in e.state.actors[FOE].conditions.values())
    assert e._effective_speed(e.state.actors[FOE])>0


def test_prison_single_asset_profile_and_concentration_cleanup(tmp_path):
    combat,table,mid=play(tmp_path,[PRISON],owner_dc=100)
    use(combat,table,mid,'Silken Prison',at=(6,6))
    e=reload(tmp_path,mid)
    objects=[o for o in e.state.objects.values() if o.component.get('iron_cloth_prison') and not o.destroyed]
    assert len(objects)==1
    obj=objects[0]
    assert obj.ac==14 and obj.current_hp==90 and obj.component['source_cl']==18
    assert {'POISON','PSYCHIC'}<=set(obj.damage_immunities)
    assert any(c.data.get('iron_cloth_prison')==obj.object_id for c in e.state.actors[FOE].conditions.values())
    assert e.state.actors[OWNER].concentration is not None
    drops=[c for c in e.legal_candidates() if 'concentration' in c.display_name.lower() and ('end' in c.display_name.lower() or 'drop' in c.display_name.lower())]
    assert drops
    settle(table,mid,drops[0].candidate_id)
    e=reload(tmp_path,mid)
    assert not any(c.data.get('iron_cloth_prison') for a in e.state.actors.values() for c in a.conditions.values())
    assert not any(o.component.get('iron_cloth_prison') and not o.destroyed for o in e.state.objects.values())


def test_ribbons_starts_later_deals_damage_once_and_keeps_origins(tmp_path):
    combat,table,mid=play(tmp_path,[SILKEN,THOUSAND],owner_dc=100,seed='IRON-RIBBONS')
    use(combat,table,mid,'Silken Whip')
    hp=reload(tmp_path,mid).state.actors[FOE].current_hp
    use(combat,table,mid,'Thousand Ribbons',choices={CHOICE+'ribbons_damage':['force'],CHOICE+'ribbons_move':None})
    e=reload(tmp_path,mid)
    assert e.state.actors[FOE].current_hp==hp
    zones=[z for z in e.state.zones.values() if z.active and z.trigger_profile.get('profile',{}).get('iron_cloth_ribbons')]
    assert len(zones)==1 and zones[0].duration_rounds==10
    assert e._hostile_difficult_cells(e.state.actors[FOE])
    turn(table,mid,FOE)
    e=reload(tmp_path,mid)
    damage=[x for x in e.events if x.event_type=='DAMAGE_COMMITTED' and x.actor_id==OWNER and FOE in x.target_ids]
    assert len(damage)==1 and damage[0].payload['damage_type']=='FORCE'
    assert e._effective_speed(e.state.actors[FOE])==0
    assert e.state.actors[OWNER].resources[QI]==91


def test_binding_renewal_happens_before_expiry_and_pays_one_qi(tmp_path):
    combat,table,mid=play(tmp_path,[SILKEN,BINDING],seed='IRON-RENEW',owner_dc=100)
    use(combat,table,mid,'Silken Whip')
    for _ in range(8):
        use(combat,table,mid,'Silken Whip Attack',target=FOE)
        e=reload(tmp_path,mid)
        if any(c.data.get('binding') for c in e.state.actors[FOE].conditions.values()):break
        settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    else:pytest.fail('No actual hit')
    before=e.state.actors[OWNER].resources[QI]
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,OWNER)
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].resources[QI]==before-1
    assert any(c.data.get('binding') for c in e.state.actors[FOE].conditions.values())
    assert any(x.event_type=='SAVE_ROLLED' and x.actor_id==FOE for x in e.events)


@pytest.mark.parametrize('automatic',[False,True])
def test_flowing_silk_real_melee_hit_zero_damage_two_choices_and_offturn_prompt(tmp_path,automatic):
    combat,table,mid=play(tmp_path,[FLOWING],owner_dc=100,foe_position={'x':4,'y':6},
        ally_position={'x':3,'y':7},seed='IRON-FLOW')
    turn(table,mid,FOE)
    prompts=[]
    for _ in range(6):
        e=reload(tmp_path,mid)
        rows=[c for c in e.legal_candidates() if c.target_ids==(OWNER,) and
              (a:=e.action_catalog.get(c.source_definition_id)) and a.economy=='ACTION' and
              any(r.get('type')=='attack' for r in (a.parameters.get('typed') or {}).get('effects',[]))]
        assert rows
        c=rows[0]
        if automatic:
            from tests.r1i_service_support import force_ai_candidate
            combat.set_controller_mode(mid,actor_id=FOE,controller_mode='LOCAL_AUTO')
            force_ai_candidate(combat,mid,FOE,c.candidate_id)
        prompts+=settle(table,mid,c.candidate_id,auto=automatic,choices={
            CHOICE+'flowing':['protect'],CHOICE+'redirection':['no_reactions','push']})
        e=reload(tmp_path,mid)
        if any(p['context']['reaction_source_id']==CHOICE+'flowing' for p in prompts):break
        combat.set_controller_mode(mid,actor_id=FOE,controller_mode='MANUAL')
        settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,FOE)
    else:pytest.fail('No actual melee hit')
    assert e.state.actors[OWNER].resources[QI]==97
    assert not e.state.actors[OWNER].reaction_available
    pending=[x for x in e.events if x.event_type=='DAMAGE_COMMITTED' and OWNER in x.target_ids and x.actor_id==FOE]
    assert pending[-1].payload['reduced_to']==0
    assert any(c.condition_id=='condition:typed.reaction_denied' for c in e.state.actors[FOE].conditions.values())
    saves=[x for x in e.events if x.event_type=='SAVE_ROLLED' and x.actor_id==FOE and x.source_definition_id==FLOWING]
    assert saves and saves[-1].sequence>pending[-1].sequence
    assert any(p['context']['reaction_source_id']==CHOICE+'redirection' for p in prompts)


@pytest.mark.parametrize('bind',[False,True,'link'])
@native_diagnostic
def test_travel_infusion_expires_on_real_elapsed_hour_and_transfers_to_combat(tmp_path,monkeypatch,bind):
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from tests.h1_support import ROOT,sheet
    aid=FACTORY_ACTOR_PREFIX+'cloth';bid=FACTORY_ACTOR_PREFIX+'foe'
    monkeypatch.setattr(CombatService,'_factory_owner_sheet',lambda self,pid:
        sheet(([SILKEN]+(['tianxia.path.qi_cultivation.feature.domain_armament'] if bind else [])+(['tianxia.path.qi_cultivation.feature.domain_armament_link'] if bind=='link' else [])) if pid=='cloth' else [],cl=18,key='CHA',kit=CLOTH,name=pid))
    scene={'stable_id':'journey:cloth','display_name':'Cloth road','width_squares':12,'height_squares':12,'square_size_ft':5,
        'starting_positions':{},'terrain_regions':[]}
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self,**kw:{'scene':scene})
    service=CombatService(ROOT,tmp_path)
    state=service.create_journey(project_ids=['cloth','foe'],arena_id='scene',
        positions={aid:{'x':2,'y':2},bid:{'x':5,'y':2}},base_paces={aid:5,bid:5},control_modes={aid:'MANUAL',bid:'MANUAL'})
    jid=state['journey_id']
    def command(kind,payload):
        service=CombatService(ROOT,tmp_path)
        current=service.journey_state(jid)
        result=service.journey_act(jid,current['revision'],aid,kind,payload)
        assert CombatService(ROOT,tmp_path).journey_state(jid)==result
        return result
    state=command('iron_cloth_infuse',{'item_key':'tianxia.mortal.gear.robe','fabric_kind':'flexible_fabric'})
    assert state['actors'][aid]['resources'][QI]==29
    state=command('wait',{'seconds':3599})
    assert SILKEN in state['actors'][aid]['travel_effects']
    saved=state['actors'][aid]['source_states']['tianxia.subpath.qi.iron_cloth_cultivator']
    assert saved['remaining_num']==1 and saved['remaining_den']==1
    command('finish',{})
    state=CombatService(ROOT,tmp_path).create_journey(project_ids=['cloth','foe'],arena_id='scene',
        positions={aid:{'x':2,'y':2},bid:{'x':5,'y':2}},base_paces={aid:5,bid:5},control_modes={aid:'MANUAL',bid:'MANUAL'})
    jid=state['journey_id']
    assert SILKEN in state['actors'][aid]['travel_effects']
    assert state['actors'][aid]['resources'][QI]==29
    state=command('wait',{'seconds':1})
    assert SILKEN not in state['actors'][aid]['travel_effects']
    state=command('iron_cloth_infuse',{'item_key':'tianxia.mortal.gear.robe','fabric_kind':'flexible_fabric'})
    if bind:
        before_clock=state['seconds']
        state=command('iron_cloth_bind',{'item_key':'tianxia.mortal.gear.robe'})
        assert state['seconds']==before_clock+600
        assert state['actors'][aid]['bundle']['iron_cloth_bond']['item_key']=='tianxia.mortal.gear.robe'
    result=CombatService(ROOT,tmp_path).journey_start_combat(jid,state['revision'],{aid:'team:a',bid:'team:b'},
        **({'positions':{aid:{'x':2,'y':2},bid:{'x':11,'y':2}}} if bind=='link' else {}))
    loaded=CombatService(ROOT,tmp_path)._load_session(result['match_id'])
    assert loaded.mechanical.replay()['status']=='PASS'
    assert any(c.condition_id=='condition:typed.silken_whip' and c.data['item_key']=='tianxia.mortal.gear.robe'
        for c in loaded.engine.state.actors[aid].conditions.values())
    assert loaded.engine.state.actors[aid].resources[QI]==28
    if bind:
        from combat.tabletop_service import TabletopService
        service=CombatService(ROOT,tmp_path);table=TabletopService(service,tmp_path);mid=result['match_id']
        turn(table,mid,aid)
        use(service,table,mid,'Domain Armament: Manifest',at=(4,2))
        engine=CombatService(ROOT,tmp_path)._load_session(mid).engine
        armed=next(c for c in engine.state.actors[aid].conditions.values() if c.condition_id=='condition:typed.domain_armament')
        assert armed.data['physical_item_key']=='tianxia.mortal.gear.robe'
        assert len([o for o in engine.state.objects.values() if o.component.get('physical_cloth_key')=='tianxia.mortal.gear.robe'])==1
        assert not any(c.display_name=='Domain Armament Attack' for c in engine.legal_candidates())
        settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,aid)
        c=candidate(service,mid,'Silken Whip Domain Armament Attack',target=bid)
        settle(table,mid,c.candidate_id)
        fresh=CombatService(ROOT,tmp_path)._load_session(mid)
        assert fresh.mechanical.replay()['status']=='PASS'
        if bind=='link':
            from combat.ext.qi_path import armament_point
            assert fresh.engine.grid.distance_ft((4,2),armament_point(fresh.engine.state.actors[aid]))>20


@pytest.mark.parametrize('kind',['BLUDGEONING','SLASHING','FORCE'])
def test_whip_printed_damage_types_and_profile_through_native_hit(tmp_path,kind):
    combat,table,mid=play(tmp_path,[SILKEN],seed='IRON-TYPE')
    use(combat,table,mid,'Silken Whip')
    for _ in range(6):
        use(combat,table,mid,'Silken Whip Attack',target=FOE,choices={'choice:needle.silken_whip_type':[kind]})
        e=reload(tmp_path,mid)
        hits=[x for x in e.events if x.event_type=='DAMAGE_COMMITTED' and x.actor_id==OWNER and FOE in x.target_ids]
        if hits:break
        settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    assert hits and hits[-1].payload['damage_type']==kind
    a=next(a for a in e.action_catalog.values() if a.owner_id==OWNER and a.display_name=='Silken Whip Attack')
    assert a.range_ft==15 and a.parameters['typed']['weapon_group']=='flexible'
    assert a.parameters['typed']['weapon']['damage']['sides']==8
    assert a.parameters['typed']['qi_powered']==1
    n=a.parameters['typed']['numbers']
    assert n['attack_bonus']==n['pb']+n['key_mod']
    assert n['save_dc']==8+n['pb']+n['key_mod']
    from combat.weapon_delivery import delivery_kind
    assert delivery_kind(a.parameters['typed'],a.parameters['typed']['effects'][0],a.parameters)=='weapon'


def test_binding_success_slows_instead_of_restraining_and_expires_at_source_turn(tmp_path):
    combat,table,mid=play(tmp_path,[SILKEN,BINDING],owner_dc=1,seed='IRON-BIND')
    use(combat,table,mid,'Silken Whip')
    for _ in range(6):
        use(combat,table,mid,'Silken Whip Attack',target=FOE)
        e=reload(tmp_path,mid)
        rows=[c for c in e.state.actors[FOE].conditions.values() if c.data.get('binding')]
        if rows:break
        settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    assert rows and all(c.condition_id=='condition:typed.iron_cloth_slow' for c in rows)
    assert e._effective_speed(e.state.actors[FOE])==20
    saves=sum(x.event_type=='SAVE_ROLLED' and x.actor_id==FOE for x in e.events)
    assert any(c.display_name=='Binding Ribbon: release' for c in e.legal_candidates())
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    e=reload(tmp_path,mid)
    assert e._effective_speed(e.state.actors[FOE])==30
    assert sum(x.event_type=='SAVE_ROLLED' and x.actor_id==FOE for x in e.events)==saves


def test_prison_success_ejects_to_nearest_unoccupied_space(tmp_path):
    combat,table,mid=play(tmp_path,[PRISON],owner_dc=1)
    use(combat,table,mid,'Silken Prison',at=(6,6))
    e=reload(tmp_path,mid)
    assert not any(c.data.get('iron_cloth_prison') for c in e.state.actors[FOE].conditions.values())
    zone=next(z for z in e.state.zones.values() if z.active and z.trigger_profile.get('profile',{}).get('iron_cloth_prison'))
    from combat.zones import actor_inside_zone
    assert not actor_inside_zone(e,e.state.actors[FOE],zone)
    assert any(x.event_type=='MOVEMENT_COMMITTED' and x.actor_id==FOE and x.payload.get('cost_ft')==0 and x.payload.get('footprint_step') for x in e.events)


@pytest.mark.parametrize('option',['push','pull','drop','move_protected'])
def test_flowing_silk_each_legal_failed_save_option_is_reachable(tmp_path,option):
    kit={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.bi_shou','name':'Dagger','quantity':1}]}}
    combat,table,mid=play(tmp_path,[FLOWING],owner_dc=100,foe_position={'x':4,'y':6},
        ally_position={'x':3,'y':7},foe_kit=kit,seed='IRON-FLOW')
    turn(table,mid,FOE)
    for _ in range(6):
        e=reload(tmp_path,mid)
        rows=[c for c in e.legal_candidates() if c.target_ids==(OWNER,) and
              (a:=e.action_catalog.get(c.source_definition_id)) and a.economy=='ACTION' and
              any(r.get('type')=='attack' and r.get('attack_kind')=='unarmed' for r in (a.parameters.get('typed') or {}).get('effects',[]))]
        assert rows
        prompts=settle(table,mid,rows[0].candidate_id,choices={CHOICE+'flowing':['protect'],
            CHOICE+'redirection':[option,'no_reactions']})
        e=reload(tmp_path,mid)
        if any(p['context']['reaction_source_id']==CHOICE+'flowing' for p in prompts):break
        settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,FOE)
    assert any(p['context']['reaction_source_id']==CHOICE+'redirection' for p in prompts)
    assert e.state.actors[OWNER].resources[QI]==97
    if option=='drop':
        assert any(c.data.get('dropped_at') and c.data.get('item_key')=='tianxia.mortal.weapon.bi_shou'
            for c in e.state.actors[FOE].conditions.values())
    elif option=='move_protected':
        assert (e.state.actors[OWNER].position.x,e.state.actors[OWNER].position.y)!=(3,6)
        assert any(x.event_type=='MOVEMENT_COMMITTED' and x.actor_id==OWNER for x in e.events)
    else:
        assert e.state.actors[FOE].position.x==(6 if option=='push' else 4)
        # Pull ends against the adjacent occupied owner's square; it never
        # passes through that creature to manufacture ten feet of movement.


def test_wrong_path_cannot_use_qi_subpath_features(tmp_path):
    combat,table,mid=fixture(tmp_path,[SILKEN,PRISON,THOUSAND],cl=18,owner_kit=CLOTH,owner_path='Body Refining')
    e=reload(tmp_path,mid)
    assert not any(c.display_name in ('Silken Whip','Silken Prison','Thousand Ribbons') for c in e.legal_candidates())


def test_prison_can_be_attacked_as_one_native_object_and_destruction_frees_captives(tmp_path):
    native_source_dependency('sysv2_objects.json','TAL_AXES_GATE_SPLITTING_BLOW')
    from tests.h1_support import sheet
    from combat.gate2_runtime_models import Position
    talents=['TAL_BERSERKER_GREAT_DESTROYER','TAL_AXES_GATE_SPLITTING_BLOW',
        'tianxia.talent.weapons.arsenal_student']
    axe={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.fu','name':'Fu (Short Axe)','quantity':1}]}}
    foe=sheet(talents,cl=18,key='CHA',score=20,name='Mara',kit=axe)
    foe['ability_scores_and_statistics']['saving_throws']={'DEX':-100}
    combat,table,mid=play(tmp_path,[PRISON],cl=14,owner_dc=14,foe_sheet=foe,
        ally_talents=talents,ally_kit=axe,ally_score=20,seed='IRON-PRISON-BREAK')
    use(combat,table,mid,'Silken Prison',at=(6,6))
    e=reload(tmp_path,mid)
    obj=next(o for o in e.state.objects.values() if o.component.get('iron_cloth_prison'))
    assert any(c.data.get('iron_cloth_prison')==obj.object_id for c in e.state.actors[FOE].conditions.values())
    assert obj.current_hp==70 and obj.component['resist']==['BLUDGEONING','PIERCING']
    assert obj.component['vulnerable']==['FIRE']
    # The captive uses an ordinary acquired weapon Action, with no Prison Qi tax.
    turn(table,mid,FOE);e=reload(tmp_path,mid);qi=e.state.actors[FOE].resources[QI]
    rows=[c for c in e.legal_candidates() if c.target_ids==(obj.object_id,) and
        e.action_catalog[c.source_definition_id].parameters.get('object_attack') and
        not e.action_catalog[c.source_definition_id].costs]
    assert rows,object_attack_diagnostic(e,FOE,obj.object_id)
    settle(table,mid,rows[0].candidate_id);e=reload(tmp_path,mid)
    assert not e.state.actors[FOE].action_available and e.state.actors[FOE].resources[QI]==qi
    rolls=[x for x in e.events if x.event_type=='ATTACK_ROLLED' and x.actor_id==FOE and x.target_ids==(obj.object_id,)]
    assert rolls and rolls[-1].payload['modifier']==9, 'Real Weapons training adds PB 4 to Strength 5'
    # A separately acquired ally axe finishes the same shared pool before expiry.
    for _ in range(8):
        turn(table,mid,ALLY);e=reload(tmp_path,mid)
        if e.state.actors[ALLY].position!=Position(x=5,y=7):
            move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination==Position(x=5,y=7))
            settle(table,mid,move.candidate_id);e=reload(tmp_path,mid)
        rows=[c for c in e.legal_candidates() if c.target_ids==(obj.object_id,) and
            'Gate-Splitting Blow' in e.action_catalog[c.source_definition_id].display_name and
            any(rid==QI for rid,amount in e.action_catalog[c.source_definition_id].costs)]
        assert rows,object_attack_diagnostic(e,ALLY,obj.object_id)
        settle(table,mid,rows[0].candidate_id);e=reload(tmp_path,mid)
        if e.state.objects[obj.object_id].destroyed:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert e.state.objects[obj.object_id].destroyed
    assert any(x.event_type=='OBJECT_UPDATED' and x.payload.get('damage',{}).get('taken',0)>0 and
        x.payload['object']['object_id']==obj.object_id and x.payload['object']['destroyed'] for x in e.events)
    assert not any(c.data.get('iron_cloth_prison')==obj.object_id for a in e.state.actors.values() for c in a.conditions.values())
    assert len([o for o in e.state.objects.values() if o.component.get('iron_cloth_prison')])==1


def test_ribbons_ally_optional_step_remote_reach_and_scene_limit(tmp_path):
    combat,table,mid=play(tmp_path,[SILKEN,THOUSAND],owner_dc=1,seed='IRON-RIBBONS-ALLIES')
    use(combat,table,mid,'Silken Whip')
    use(combat,table,mid,'Thousand Ribbons')
    turn(table,mid,ALLY)
    e=reload(tmp_path,mid)
    assert any(x.event_type=='MOVEMENT_COMMITTED' and x.actor_id==ALLY and x.payload.get('cost_ft')==0 for x in e.events)
    turn(table,mid,FOE)
    e=reload(tmp_path,mid)
    assert e._effective_speed(e.state.actors[FOE])==20
    rolls=[x for x in e.events if x.event_type=='DAMAGE_ROLLED' and x.actor_id==OWNER]
    hits=[x for x in e.events if x.event_type=='DAMAGE_COMMITTED' and x.actor_id==OWNER and FOE in x.target_ids]
    assert rolls and hits and hits[-1].payload['rolled_or_pending_damage']==rolls[-1].payload['total']//2
    turn(table,mid,OWNER)
    e=reload(tmp_path,mid)
    assert not any(c.display_name=='Thousand Ribbons' for c in e.legal_candidates())
    assert any(e.action_catalog[c.source_definition_id].display_name=='Silken Whip Attack' and c.metadata.get('effect_origin') for c in e.legal_candidates() if c.source_definition_id in e.action_catalog)
    use(combat,table,mid,'Thousand Ribbons: end concentration')
    e=reload(tmp_path,mid)
    assert not any(z.active and z.trigger_profile.get('profile',{}).get('iron_cloth_ribbons') for z in e.state.zones.values())
    assert not any(c.metadata.get('effect_origin',{}).get('id','').startswith('iron_cloth:') for c in e.legal_candidates())


def test_automatic_owner_cannot_invent_unknown_fabric_identity(tmp_path):
    combat,table,mid=play(tmp_path,[SILKEN])
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    e=combat._load_session(mid).engine
    assert not any(c.display_name=='Silken Whip' for c in e.legal_candidates())
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='MANUAL')
    use(combat,table,mid,'Silken Whip')
    use(combat,table,mid,'Silken Whip: end infusion')
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    e=combat._load_session(mid).engine
    assert any(c.display_name=='Silken Whip' for c in e.legal_candidates())
    from combat.fact_consent_admission import combat_records
    assert combat_records(e,e.state.actors[OWNER],source=SILKEN,kind='iron_cloth_fabric')
    assert not combat_records(e,e.state.actors[FOE],source=SILKEN,kind='iron_cloth_fabric')


def test_infused_cloth_uses_native_object_attack_and_printed_damage_choice(tmp_path):
    kit={'starting_kit':{'items':[*CLOTH['starting_kit']['items'],*CLOTH['starting_kit']['items']]}}
    combat,table,mid=play(tmp_path,[SILKEN,PRISON],owner_kit=kit,owner_dc=14,seed='IRON-WHIP-OBJECT')
    use(combat,table,mid,'Silken Whip')
    use(combat,table,mid,'Silken Prison',at=(6,6),choices={CHOICE+'prison_fabric':[OWNER+'|tianxia.mortal.gear.robe.2'],'choice:needle.fact_admission.iron_cloth_fabric':['flexible_fabric']})
    e=reload(tmp_path,mid)
    obj=next(o for o in e.state.objects.values() if o.component.get('iron_cloth_prison'))
    hp=obj.current_hp
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    for _ in range(6):
        use(combat,table,mid,'Silken Whip: attack an object',target=obj.object_id,
            choices={CHOICE+'object_damage_type':['FORCE']})
        e=reload(tmp_path,mid)
        if e.state.objects[obj.object_id].current_hp<hp:break
        settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    assert e.state.objects[obj.object_id].current_hp<hp
    damage=[x for x in e.events if x.event_type=='OBJECT_UPDATED' and x.payload.get('damage')]
    assert damage and damage[-1].payload['damage']['kinds']=='force'
    assert not any(c.data.get('binding') for a in e.state.actors.values() for c in a.conditions.values())


def test_binding_native_tether_keeps_thirty_feet_and_ends_beyond_it(tmp_path):
    combat,table,mid=play(tmp_path,[SILKEN,BINDING],owner_dc=100,seed='IRON-BIND')
    use(combat,table,mid,'Silken Whip')
    for _ in range(6):
        use(combat,table,mid,'Silken Whip Attack',target=FOE)
        e=reload(tmp_path,mid)
        if any(c.data.get('binding') for c in e.state.actors[FOE].conditions.values()):break
        settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    else:pytest.fail('No native hit')
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    e=reload(tmp_path,mid)
    dash=next(c for c in e.legal_candidates() if c.source_definition_id=='system:combat.dash')
    settle(table,mid,dash.candidate_id)
    e=reload(tmp_path,mid);target=e.state.actors[FOE]
    far=sorted((c for c in e.legal_candidates() if c.destination and c.kind.value=='MOVE' and
        e.grid.distance_ft(c.destination,target.position)>30),key=lambda c:c.movement_cost_ft)
    assert far
    path=list(far[0].canonical_path)
    first=next(i for i,p in enumerate(path) if e.grid.distance_ft(p,target.position)>30)
    edge=path[first-1]
    assert e.grid.distance_ft(edge,target.position)==30
    near=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination==edge)
    settle(table,mid,near.candidate_id)
    e=reload(tmp_path,mid)
    assert any(c.data.get('binding') for c in e.state.actors[FOE].conditions.values())
    choices=[c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination and
        e.grid.distance_ft(c.destination,e.state.actors[FOE].position)>30]
    assert choices
    settle(table,mid,choices[0].candidate_id)
    e=reload(tmp_path,mid)
    assert not any(c.data.get('binding') for c in e.state.actors[FOE].conditions.values())
    assert e._effective_speed(e.state.actors[FOE])==30


def test_native_transfer_keeps_original_item_identity_when_infused(tmp_path):
    combat,table,mid=fixture(tmp_path,[SILKEN,'TAL_SCOUNDREL_STEAL'],cl=18,owner_key='CHA',
        owner_kit=None,foe_kit=CLOTH,foe_position={'x':4,'y':6},ally_position={'x':3,'y':7},
        named=True,seed='IRON-TRANSFER')
    for _ in range(8):
        e=reload(tmp_path,mid)
        rows=[c for c in e.legal_candidates() if c.target_ids==(FOE,) and
            e.action_catalog.get(c.source_definition_id) and
            (e.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source')=='TAL_SCOUNDREL_STEAL']
        assert rows
        settle(table,mid,rows[0].candidate_id)
        e=reload(tmp_path,mid)
        if any(c.data.get('held_by')==OWNER and c.data.get('item_key')=='tianxia.mortal.gear.robe'
               for a in e.state.actors.values() for c in a.conditions.values()):break
        settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    else:pytest.fail('The seeded native transfer never succeeded')
    assert not next(b for b in e.typed_bundle_documents if b['actor_id']==OWNER)['carrying']['items']
    use(combat,table,mid,'Silken Whip')
    e=reload(tmp_path,mid);w=whip_of(e)
    assert w.data['item_owner']==FOE
    assert w.data['item_object']==FOE+'|tianxia.mortal.gear.robe'
    assert w.data['declaration_authority']=='item_possessor'
    assert len([o for o in e.state.objects.values() if o.component.get('inventory_identity')==w.data['item_object']])==1


def test_flowing_silk_can_redirect_a_restrained_protected_creature(tmp_path):
    combat,table,mid=play(tmp_path,[FLOWING,PRISON],owner_dc=100,seed='IRON-FLOW-RESTRAINED',
        foe_position={'x':5,'y':6},ally_position={'x':4,'y':6})
    use(combat,table,mid,'Silken Prison',at=(4,6))
    e=reload(tmp_path,mid)
    assert e._effective_speed(e.state.actors[ALLY])==0, [(x.event_type,x.payload) for x in e.events if 'SAVE' in x.event_type]
    before=e.state.actors[ALLY].position
    turn(table,mid,FOE)
    for _ in range(6):
        e=reload(tmp_path,mid)
        rows=[c for c in e.legal_candidates() if c.target_ids==(ALLY,) and
            (a:=e.action_catalog.get(c.source_definition_id)) and a.economy=='ACTION' and
            any(r.get('type')=='attack' and r.get('attack_kind')=='unarmed' for r in (a.parameters.get('typed') or {}).get('effects',[]))]
        assert rows
        prompts=settle(table,mid,rows[0].candidate_id,choices={CHOICE+'flowing':['protect'],
            CHOICE+'redirection':['move_protected','no_reactions']})
        e=reload(tmp_path,mid)
        if any(p['context']['reaction_source_id']==CHOICE+'protected_move' for p in prompts):break
        settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,FOE)
    assert e.state.actors[ALLY].position!=before
    assert any(x.event_type=='MOVEMENT_COMMITTED' and x.actor_id==ALLY and x.payload.get('forced') for x in e.events)


def test_shared_declaration_bridge_rejects_tampering_and_wrong_authority(tmp_path):
    from combat.fact_consent_admission import combat_records, restore_combat_record
    combat,table,mid=play(tmp_path,[SILKEN])
    use(combat,table,mid,'Silken Whip')
    e=reload(tmp_path,mid);owner=e.state.actors[OWNER]
    record=combat_records(e,owner,source=SILKEN,kind='iron_cloth_fabric')[0]
    before=e.state.model_dump(mode='json')
    assert restore_combat_record(e,owner,SILKEN,None,expires_on='UNTIL_REMOVED') is None
    for source,subject,r in [(BINDING,owner,record),(SILKEN,e.state.actors[FOE],record),
                              (SILKEN,owner,{**record,'value':'invented material'})]:
        with pytest.raises(ValueError):restore_combat_record(e,subject,source,r,expires_on='UNTIL_REMOVED')
    from combat.observer_information import publish,readings
    assert readings(e,e.state.actors[FOE])==[]
    with pytest.raises(ValueError,match='authority'):
        publish(e,e.state.actors[FOE],SILKEN,e.state.actors[FOE],'declaration',{'fabric':'unknown'},'UNTIL_REMOVED')
    assert e.state.model_dump(mode='json')==before


def test_real_cloth_changes_to_prison_without_a_duplicate_and_survives_dismissal(tmp_path):
    combat,table,mid=play(tmp_path,[SILKEN,PRISON],owner_dc=100)
    use(combat,table,mid,'Silken Whip')
    e=reload(tmp_path,mid);oid=whip_of(e).data['object_id']
    use(combat,table,mid,'Silken Prison',at=(6,6))
    e=reload(tmp_path,mid)
    assert whip_of(e) is None
    assert e.state.objects[oid].component.get('iron_cloth_prison')
    assert len([o for o in e.state.objects.values() if o.component.get('inventory_identity')==OWNER+'|tianxia.mortal.gear.robe'])==1
    use(combat,table,mid,'Silken Prison: end concentration')
    e=reload(tmp_path,mid)
    assert not e.state.objects[oid].destroyed
    assert not e.state.objects[oid].unattended and e.state.objects[oid].flammable
    assert not e.state.objects[oid].component.get('iron_cloth_prison')
    assert not any(c.condition_id=='condition:typed.iron_cloth_broken' for c in e.state.actors[OWNER].conditions.values())


@pytest.mark.parametrize('source_cl,disarmed,infused',[(17,False,True),(18,True,True),(18,False,False)])
def test_ribbons_disarm_source_cl_boundary_through_native_acquired_grip_seal(tmp_path,source_cl,disarmed,infused):
    native_source_dependency('shi.json','tianxia.talent.pressure_points.grip_severing_point')
    from tests.h1_support import sheet
    grip='tianxia.talent.pressure_points.grip_severing_point'
    foe=sheet([grip],cl=source_cl,dc=100,primary='Stamina',name='Mara')
    foe['ability_scores_and_statistics']['hit_points']['maximum']=1000
    combat,table,mid=play(tmp_path,[SILKEN,FLOWING,THOUSAND],foe_sheet=foe,
        foe_position={'x':4,'y':6},ally_position={'x':3,'y':7},seed='IRON-DISARM-BOUNDARY')
    if infused:use(combat,table,mid,'Silken Whip')
    use(combat,table,mid,'Thousand Ribbons',choices={CHOICE+'ribbons_damage':['force'],CHOICE+'ribbons_move':None})
    def foe_turn():
        # These are real optional decisions, not forced fixture movement.
        # Keep the acquired melee delivery adjacent while exercising Disarm.
        for _ in range(12):
            if table.state(mid)['menu']['actor_id']==FOE:
                return
            settle(table,mid,table.state(mid)['menu']['end_turn'],
                choices={CHOICE+'ribbons_move':None,CHOICE+'ally_step':None})
        pytest.fail('No foe turn')
    foe_turn()
    for _ in range(8):
        use(combat,table,mid,'Touch the Point: Grip-Severing Point',target=None)
        e=reload(tmp_path,mid)
        attacks=[c for c in e.legal_candidates() if c.target_ids==(OWNER,) and
            (a:=e.action_catalog.get(c.source_definition_id)) and a.economy=='ACTION' and
            any(r.get('type')=='attack' and r.get('attack_kind')=='unarmed'
                for r in (a.parameters.get('typed') or {}).get('effects',[]))]
        assert attacks, [(a.display_name,a.economy) for a in e.action_catalog.values() if a.owner_id==FOE]
        settle(table,mid,attacks[0].candidate_id,choices={CHOICE+'ribbons_move':None,CHOICE+'ally_step':None,
            CHOICE+'flowing':['protect'],CHOICE+'redirection':['no_reactions','move_protected'],CHOICE+'protected_move':None})
        e=reload(tmp_path,mid)
        if any(x.event_type=='SAVE_ROLLED' and x.actor_id==OWNER and not x.payload['success'] for x in e.events):break
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={CHOICE+'ribbons_move':None,CHOICE+'ally_step':None});foe_turn()
    else:pytest.fail('The native Point delivery never produced a failed saving throw')
    assert e.state.actors[OWNER].concentration is not None, 'Flowing Silk kept the native hit at zero damage'
    assert any(x.event_type=='DAMAGE_COMMITTED' and OWNER in x.target_ids and x.payload.get('reduced_to')==0 for x in e.events)
    identity=OWNER+'|tianxia.mortal.gear.robe'
    drops=[c for actor in e.state.actors.values() for c in actor.conditions.values()
        if c.data.get('object_id')==identity and c.data.get('dropped_at')]
    assert bool(drops) is disarmed
    from combat.weapon_delivery import available_weapons
    assert any((a.parameters.get('typed') or {}).get('source')=='silken_whip.attack'
        for a in available_weapons(e,e.state.actors[OWNER]).values()) is (infused and not disarmed)
    if disarmed:
        for _ in range(12):
            if table.state(mid)['menu']['actor_id']==OWNER:break
            settle(table,mid,table.state(mid)['menu']['end_turn'],
                choices={CHOICE+'ribbons_move':None,CHOICE+'ally_step':None})
        e=reload(tmp_path,mid)
        pickup=next(c for c in e.legal_candidates() if (a:=e.action_catalog.get(c.source_definition_id)) and
            a.parameters.get('item_action')=='pickup' and a.parameters.get('item_key')=='tianxia.mortal.gear.robe')
        settle(table,mid,pickup.candidate_id);e=reload(tmp_path,mid)
        assert any((a.parameters.get('typed') or {}).get('source')=='silken_whip.attack'
            for a in available_weapons(e,e.state.actors[OWNER]).values())
        assert not any(c.data.get('object_id')==identity and c.data.get('dropped_at')
            for actor in e.state.actors.values() for c in actor.conditions.values())


@native_diagnostic
def test_ribbons_scene_allowance_survives_native_encounters_until_table_owner_ends_scene(tmp_path,monkeypatch):
    from combat.gate5_service import CombatService,FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT,sheet
    aid=FACTORY_ACTOR_PREFIX+'ribbon';bid=FACTORY_ACTOR_PREFIX+'guest'
    monkeypatch.setattr(CombatService,'_factory_owner_sheet',lambda self,pid:
        sheet([THOUSAND] if pid=='ribbon' else [],cl=18,key='CHA',name=pid))
    arena={'stable_id':'journey:ribbon','display_name':'Ribbon road','width_squares':12,'height_squares':12,'square_size_ft':5,
        'starting_positions':{},'terrain_regions':[]}
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self,**kw:{'scene':arena})
    cold=lambda:CombatService(ROOT,tmp_path)
    state=cold().create_journey(project_ids=['ribbon','guest'],arena_id='scene',
        positions={aid:{'x':2,'y':2},bid:{'x':5,'y':2}},base_paces={aid:5,bid:5},
        control_modes={aid:'MANUAL',bid:'MANUAL'})
    jid=state['journey_id']
    def encounter():
        state=cold().journey_state(jid)
        mid=cold().journey_start_combat(jid,state['revision'],{aid:'team:a',bid:'team:b'},maximum_rounds=1)['match_id']
        service=cold();table=TabletopService(service,tmp_path)
        turn(table,mid,aid)
        return service,table,mid
    def finish(table,mid):
        for _ in range(6):
            loaded=cold()._load_session(mid)
            if loaded.engine.state.terminal_result is not None:break
            settle(table,mid,table.state(mid)['menu']['end_turn'])
        assert loaded.engine.state.terminal_result is not None
        assert loaded.mechanical.replay()['status']=='PASS'
        state=cold().journey_state(jid)
        return cold().journey_resume(jid,state['revision'])
    service,table,mid=encounter()
    use(service,table,mid,'Thousand Ribbons')
    use(service,table,mid,'Thousand Ribbons: end concentration')
    state=finish(table,mid)
    state=cold().journey_act(jid,state['revision'],aid,'wait',{'seconds':60})
    service,table,mid=encounter()
    assert not any(c.display_name=='Thousand Ribbons' for c in cold()._load_session(mid).engine.legal_candidates())
    state=finish(table,mid)
    before_qi=state['actors'][aid]['resources'][QI]
    costs=[cost for action in state['actors'][aid]['bundle']['action_catalog'] if action.get('parameters',{}).get('typed',{}).get('source')==THOUSAND for cost in action.get('costs',[])]
    uses={rid:state['actors'][aid]['resources'][rid] for rid,amount in costs if rid.startswith('resource:uses.')}
    other_resources={rid:value for rid,value in state['actors'][aid]['resources'].items() if rid not in uses}
    assert uses and all(value==0 for value in uses.values())
    after=cold().journey_end_scene(jid,state['revision'],'The group leaves the resolved confrontation and begins a new scene.')
    assert cold().journey_state(jid)==after
    assert after['actors'][aid]['resources'][QI]==before_qi
    assert all(after['actors'][aid]['resources'][rid]==value for rid,value in other_resources.items())
    assert all(after['actors'][aid]['resources'][rid]==1 for rid in uses)
    assert after['fact_consent_admission'][-1]['authority']=='table_owner'
    service,table,mid=encounter()
    use(service,table,mid,'Thousand Ribbons')
    assert cold()._load_session(mid).mechanical.replay()['status']=='PASS'



def object_attack_diagnostic(engine, actor_id, object_id):
    actor=engine.state.actors[actor_id];obj=engine.state.objects[object_id]
    diagnostic={'current_actor':engine.state.current_actor_id,'action_available':actor.action_available,
        'distance':engine.grid.distance_ft(actor.position,obj.position),
        'line_of_sight':engine._line_of_sight_actor_to_cell(actor,obj.position),
        'object_actions':[(a.display_name,list(a.costs)) for a in engine.action_catalog.values()
            if a.owner_id==actor_id and a.parameters.get('object_attack')],
        'object_candidates':[(engine.action_catalog[c.source_definition_id].display_name,list(c.target_ids)) for c in engine.legal_candidates()
            if c.source_definition_id in engine.action_catalog and engine.action_catalog[c.source_definition_id].parameters.get('object_attack')]}

    import json
    print('OBJECT_ATTACK_DIAGNOSTIC '+json.dumps(diagnostic,sort_keys=True))
    return json.dumps(diagnostic,sort_keys=True,indent=2)


def native_source_dependency(filename, feature_id):
    """Acceptance needs the acquired source's actual delivery, not a pruned export.

    Fail explicitly when a runner omits an authority dependency. Never fabricate
    its passive/action or silently reinterpret missing acquisition as a product result.
    """
    from pathlib import Path
    import json
    data=json.loads((Path(__file__).resolve().parents[1]/'combat/rules/feature_blocks.d'/filename).read_bytes())
    assert feature_id in data['features']
