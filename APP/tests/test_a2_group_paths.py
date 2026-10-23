"""A2GPAT printed Path choices through service/table transactions and cold replay."""
import pytest
from combat.ext import qi_path
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, ALLY, FOE

Q = 'tianxia.path.qi_cultivation.feature.'
S = 'tianxia.path.spirit_awakening.feature.'
QI = 'resource:core.qi'


def use(combat, table, mid, name, **kw):
    row = candidate(combat, mid, name, target=kw.pop('target', None), at=kw.pop('at', None))
    return settle(table, mid, row.candidate_id, **kw)


@pytest.mark.parametrize('cl,count,amount', [(10,1,4),(17,2,8)])
def test_circulating_selects_printed_number_and_cold_reloads(tmp_path, cl, count, amount):
    combat, table, mid = fixture(tmp_path, [Q+'golden_core_form', Q+'domain_armament']+([Q+'nine_heavens_gaze'] if cl >= 17 else []), cl=cl, seed=f'GPAT-{cl}', owner_golden=('circulating',))
    before = combat._load_session(mid).engine.state.actors[OWNER]
    movement, qi, before_position = before.movement_remaining_ft, before.resources[QI], before.position
    picks = ['temp_hp'] if count == 1 else ['temp_hp','move']
    prompts = use(combat, table, mid, 'Domain Armament: Manifest', at=(2,6), choices={'choice:needle.golden_benefits':picks,
        'choice:needle.golden_step':'first'})
    asked = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.golden_benefits']
    assert len(asked) == 1
    assert asked[0]['choice']['minimum'] == count and asked[0]['choice']['maximum'] == count
    engine = reload(tmp_path, mid); owner = engine.state.actors[OWNER]
    assert owner.temporary_hp == amount
    assert owner.resources[QI] < qi
    assert owner.movement_remaining_ft == movement
    if cl >= 17:
        assert owner.position != before_position
        assert any(e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == OWNER for e in engine.events)
    # A second paid technique in the same turn cannot generate another benefit.
    if cl >= 17:
        prompts = use(combat, table, mid, 'Nine Heavens Gaze', choices={'choice:needle.golden_benefits':picks})
        assert not any(p['context']['reaction_source_id'] == 'choice:needle.golden_benefits' for p in prompts)
        reload(tmp_path, mid)


def test_circulating_can_choose_movement_instead_of_temp_hp(tmp_path):
    combat, table, mid = fixture(tmp_path, [Q+'golden_core_form', Q+'domain_armament'], cl=10, owner_golden=('circulating',))
    before = combat._load_session(mid).engine.state.actors[OWNER].position
    use(combat, table, mid, 'Domain Armament: Manifest', at=(2,6), choices={'choice:needle.golden_benefits':['move'],
                                               'choice:needle.golden_step':'first'})
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert owner.position != before
    assert owner.temporary_hp == 0


def test_circulating_immobilized_owner_can_still_take_temp_hp_through_reload(tmp_path):
    def setup(bundles):
        add_trigger(bundles[0], [{'type':'condition','condition':'grappled','applies_to':'target',
                                 'expires_on':'UNTIL_REMOVED'}], name='Test immobilization')
        row = bundles[0]['action_catalog'][-1]
        row['economy'] = 'BONUS_ACTION'
        from combat.canonical import canonical_sha256
        bundles[0].pop('bundle_sha256',None)
        bundles[0]['bundle_sha256'] = canonical_sha256(bundles[0])
    combat, table, mid = fixture(tmp_path, [Q+'golden_core_form', Q+'domain_armament', Q+'nine_heavens_gaze'], cl=17,
                                bundle_transform=setup, owner_golden=('circulating',))
    use(combat, table, mid, 'Test immobilization', target=OWNER)
    prompts = use(combat, table, mid, 'Nine Heavens Gaze', choices={
        'choice:needle.golden_benefits':['temp_hp','armament'],
        'choice:needle.golden_armament':'cell:2,2'})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.golden_benefits')
    assert [row['id'] for row in prompt['choice']['options']] == ['temp_hp']
    assert reload(tmp_path, mid).state.actors[OWNER].temporary_hp == 8


def test_perfected_circulating_moves_armament_twenty_feet(tmp_path):
    combat, table, mid = fixture(tmp_path, [Q+'golden_core_form',Q+'domain_armament',Q+'domain_armament_link'], cl=17, owner_golden=('circulating',))
    # Explicit manifestation and 20-foot destination are answered through ordinary player transport.
    use(combat, table, mid, 'Domain Armament: Manifest', at=(2,6), choices={
        'choice:needle.golden_benefits':['temp_hp','armament'],
        'choice:needle.golden_armament':['cell:2,2']})
    engine = reload(tmp_path, mid)
    assert qi_path.armament_point(engine.state.actors[OWNER]) == (2,2)
    assert engine.state.actors[OWNER].temporary_hp == 8


def test_perfected_circulating_rebuilds_armament_destinations_after_owner_moves(tmp_path):
    combat, table, mid = fixture(tmp_path, [Q+'golden_core_form',Q+'domain_armament'], cl=17,
        owner_speed=30, positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':7},FOE:{'x':6,'y':7}}, owner_golden=('circulating',))
    # Move away from the edge destination at (9,6): it starts 30 feet from the
    # owner, then is out of the 30-foot control radius after the 10-foot shift.
    prompts = use(combat, table, mid, 'Domain Armament: Manifest', at=(6,6), choices={
        'choice:needle.golden_benefits':['move','armament'],
        'choice:needle.golden_step':'step:1,6,0',
        'choice:needle.golden_armament':'cell:7,6'})
    engine = reload(tmp_path, mid); owner = engine.state.actors[OWNER]
    assert (owner.position.x, owner.position.y) == (1,6)
    assert qi_path.armament_point(owner) == (7,6)
    menu = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.golden_armament')
    ids = {row['id'] for row in menu['choice']['options']}
    assert 'cell:9,6' not in ids


def test_circulating_armament_hidden_occupant_fails_without_revealing_it(tmp_path):
    def setup(bundles):
        add_trigger(bundles[0], [{'type':'condition','condition':'invisible','applies_to':'target',
                                  'expires_on':'UNTIL_REMOVED'}], name='Test invisibility', economy='NONE')
    combat, table, mid = fixture(tmp_path, [Q+'golden_core_form', Q+'domain_armament'], cl=17,
        bundle_transform=setup,
        positions={OWNER:{'x':3,'y':6}, ALLY:{'x':8,'y':7}, FOE:{'x':2,'y':2}}, owner_golden=('circulating',))
    use(combat, table, mid, 'Test invisibility', target=FOE)
    prompts = use(combat, table, mid, 'Domain Armament: Manifest', at=(4,2), choices={
        'choice:needle.golden_benefits':['temp_hp','armament'],
        'choice:needle.golden_armament':'cell:2,2'})
    menu = next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.golden_armament')
    assert 'cell:2,2' in {row['id'] for row in menu['choice']['options']}
    engine = reload(tmp_path, mid)
    assert qi_path.armament_point(engine.state.actors[OWNER]) == (4,2)
    outcomes = [e.payload.get('trigger','') for e in engine.events if e.event_type=='PASSIVE_TRIGGERED'
                and 'could not move your Domain Armament' in e.payload.get('trigger','')]
    assert outcomes and 'invisible' not in outcomes[-1].lower() and FOE not in outcomes[-1]


def test_armament_automatic_guard_never_shields_an_enemy(tmp_path):
    combat, table, mid = fixture(tmp_path, [Q+'domain_armament'], cl=9, ask=False)
    use(combat, table, mid, 'Domain Armament: Manifest', at=(7,6))
    use(combat, table, mid, 'Domain Armament: Guard Mode')
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    for _ in range(8):
        settle(table, mid, None, auto=True)
        if combat._load_session(mid).engine.state.current_actor_id != OWNER:
            break
    else:
        raise AssertionError('Automatic owner did not finish its turn')
    engine = reload(tmp_path, mid)
    assert not any(m.source_definition_id == qi_path.GUARD for m in engine.state.actors[FOE].modifiers.values())


def test_armament_automatic_guard_chooses_nearby_ally(tmp_path):
    combat, table, mid = fixture(tmp_path, [Q+'domain_armament'], cl=9, ask=False)
    use(combat, table, mid, 'Domain Armament: Manifest', at=(4,7))
    use(combat, table, mid, 'Domain Armament: Guard Mode')
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    for _ in range(8):
        settle(table, mid, None, auto=True)
        if combat._load_session(mid).engine.state.current_actor_id != OWNER:
            break
    else:
        raise AssertionError('Automatic owner did not finish its turn')
    engine = reload(tmp_path, mid)
    allies = [engine.state.actors[key] for key in (OWNER,ALLY)]
    assert sum(m.source_definition_id == qi_path.GUARD for a in allies for m in a.modifiers.values()) == 1


def test_repelled_heart_enforces_paths_then_expires(tmp_path):
    combat, table, mid = fixture(tmp_path, [S+'mind_spike'], cl=5, owner_dc=40,
                               primary='Resonance', owner_path='Spirit Awakening')
    use(combat, table, mid, 'Spiritual Pressure: Repelled Heart (cannot willingly move closer to you)')
    use(combat, table, mid, 'Mind Spike', target=FOE)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    use(combat, table, mid, 'Mind Spike', target=FOE)
    engine = reload(tmp_path, mid); foe = engine.state.actors[FOE]
    assert any(c.condition_id == 'condition:typed.no_approach' for c in foe.conditions.values())
    marker = next(c for c in foe.conditions.values() if c.condition_id == 'condition:typed.no_approach')
    owner_name = engine.state.actors[OWNER].display_name
    assert owner_name in (marker.data or {}).get('label', '')
    assert f"until the start of {owner_name}'s next turn" in (marker.data or {}).get('label', '')
    from combat.voluntary_movement import path_allowed
    from combat.gate2_runtime_models import Position
    assert not path_allowed(engine, foe, [foe.position, Position(x=foe.position.x-1,y=foe.position.y)])
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    foe = reload(tmp_path, mid).state.actors[FOE]
    assert not any(c.condition_id == 'condition:typed.no_approach' for c in foe.conditions.values())


def test_nine_heavens_gaze_pays_and_seals_its_senses(tmp_path):
    from combat import senses
    combat, table, mid = fixture(tmp_path, [Q+'nine_heavens_gaze'], cl=17)
    qi = combat._load_session(mid).engine.state.actors[OWNER].resources[QI]
    use(combat, table, mid, 'Nine Heavens Gaze')
    engine = reload(tmp_path, mid); owner = engine.state.actors[OWNER]
    assert owner.resources[QI] == qi-8
    assert not owner.action_available
    actual = senses.of(engine, owner)
    assert actual['truesight']['range_ft'] == 60
    assert actual['qi_sensing']['range_ft'] == 120
    assert len([c for c in owner.conditions.values() if c.condition_id == senses.SENSE]) == 2
    grants = [e for e in engine.events if e.event_type == 'CONDITION_APPLIED'
              and e.source_definition_id.endswith('nine_heavens_gaze') and (e.payload or {}).get('condition_id') == senses.SENSE]
    removals = [e for e in engine.events if e.event_type == 'CONDITION_REMOVED'
                and e.source_definition_id.endswith('nine_heavens_gaze') and (e.payload or {}).get('condition_id') == senses.SENSE]
    assert len(grants) == 2 and not removals


def test_immortal_qi_has_gaze_without_action_or_qi_spend(tmp_path):
    from combat import senses
    combat, table, mid = fixture(tmp_path, [Q+'immortal_of_qi'], cl=20)
    engine = reload(tmp_path, mid); owner = engine.state.actors[OWNER]
    assert senses.of(engine,owner)['truesight']['range_ft'] == 60
    assert senses.of(engine,owner)['qi_sensing']['range_ft'] == 120
    assert owner.action_available
    assert not any(e.event_type == 'RESOURCE_SPENT' and e.actor_id == OWNER for e in engine.events)


def add_trigger(bundle, effects, *, name='Test bodily trigger', economy='ACTION'):
    """Seal an external test hazard; feature resolution still uses the real interpreter."""
    from combat.canonical import canonical_sha256
    source = 'action:test.gpat.'+bundle['actor_id'].rsplit('.',1)[-1]
    parameters = {'typed':{'source':'test:gpat','effects':effects,
                'numbers':{'cl':10,'pb':4,'key_mod':2,'save_dc':40},'duration':{'kind':'instant'},'riders':[]}}
    if economy == 'NONE':
        # A free test hazard must declare itself a free primary action; an
        # economy of NONE without that marker is not an activation permission.
        parameters['free_primary'] = True
    row = {'source_definition_id':source,'display_name':name,'owner_id':bundle['actor_id'],
           'economy':economy,'resolution_kind':'TYPED','target_kind':'ANY_CREATURE','range_ft':60,'costs':[],
           'parameters':parameters}
    bundle['action_catalog'].append(row); bundle['actor_template']['action_ids'].append(source)
    bundle.pop('bundle_sha256',None); bundle['bundle_sha256'] = canonical_sha256(bundle)


def test_perfected_blood_furnace_ends_one_bleeding_after_healing(tmp_path):
    B = 'tianxia.path.body_refining.feature.'
    def setup(bundles):
        add_trigger(bundles[2], [{'type':'damage','applies_to':'target','flat':12,'damage_types':['force']},
            {'type':'condition','condition':'bleeding','applies_to':'target','expires_on':'UNTIL_REMOVED'}])
    combat, table, mid = fixture(tmp_path,[B+'core_tempering_expression',B+'iron_voice'],cl=17,
        primary='Stamina', owner_path='Body Refining', bundle_transform=setup)
    use(combat,table,mid,'Core Tempering Expression: Blood-Furnace Circulation')
    settle(table,mid,table.state(mid)['menu']['end_turn']); turn(table,mid,FOE)
    use(combat,table,mid,'Test bodily trigger',target=OWNER)
    settle(table,mid,table.state(mid)['menu']['end_turn']); turn(table,mid,OWNER)
    before = reload(tmp_path,mid).state.actors[OWNER].current_hp
    prompts = use(combat,table,mid,'Iron Voice',target=FOE,
        choices={'choice:needle.blood_furnace_bleeding':'first'})
    prompt = next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.blood_furnace_bleeding')
    label = prompt['choice']['options'][0]['label']
    assert 'Test bodily trigger' in label and 'Source cultivation level 10' in label and 'continues until ended' in label
    owner = reload(tmp_path,mid).state.actors[OWNER]
    assert owner.current_hp == before+8
    assert not any(c.condition_id=='condition:typed.bleeding' for c in owner.conditions.values())


@pytest.mark.parametrize('bypass', [False,True])
def test_perfected_bell_blocks_lower_cl_push_unless_explicit_bypass(tmp_path,bypass):
    B = 'tianxia.path.body_refining.feature.'
    def setup(bundles):
        add_trigger(bundles[2],[{'type':'forced_movement','applies_to':'target','distance_ft':10,
                                'ignores_bodily_anchoring':bypass}])
    combat,table,mid = fixture(tmp_path,[B+'core_tempering_expression'],cl=17,primary='Stamina',
        owner_path='Body Refining',bundle_transform=setup,positions={OWNER:{'x':5,'y':6},ALLY:{'x':4,'y':5},FOE:{'x':7,'y':6}})
    use(combat,table,mid,'Core Tempering Expression: Golden Bell Circulation')
    use(combat,table,mid,'Golden Bell Circulation')
    before = reload(tmp_path,mid).state.actors[OWNER].position
    settle(table,mid,table.state(mid)['menu']['end_turn']); turn(table,mid,FOE)
    use(combat,table,mid,'Test bodily trigger',target=OWNER)
    owner = reload(tmp_path,mid).state.actors[OWNER]
    assert (owner.position != before) == bypass


def test_domain_pressure_automatic_multi_recipients_are_enemies(tmp_path):
    from combat.gate4_adapters import ManualControllerAdapter
    from combat.typed_executor import bears_mark
    combat,table,mid = fixture(tmp_path,[S+'domain_pressure'],cl=5,owner_dc=40,
        primary='Resonance',owner_path='Spirit Awakening',foe_position={'x':6,'y':6})
    row = candidate(combat,mid,'Domain Pressure',at=(6,6))
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    real = combat.controller
    class Controller:
        def choose_primary_action(self,context):
            # The automatic menu represents an area action by its lazy placement
            # root ("choose a square"); the exact-cell candidate is bound by the
            # persisted square choice that settle() answers below.
            offered = next((c for c in context.legal_candidates
                            if c.source_definition_id == row.source_definition_id), None)
            assert offered is not None, 'Domain Pressure was not offered to the automatic seat'
            return ManualControllerAdapter(lambda _: (offered.candidate_id, ())).choose_primary_action(context)
        def choose_reaction(self,context):
            return real.choose_reaction(context)
    combat.controller = Controller()
    settle(table,mid,None,auto=True,choices={'choice:placement_menu.square':'first'})
    engine = reload(tmp_path,mid)
    assert bears_mark(engine.state.actors[FOE],OWNER,'Resonance')
    assert not bears_mark(engine.state.actors[ALLY],OWNER,'Resonance')
    assert not any(c.condition_id=='condition:typed.frightened' for c in engine.state.actors[ALLY].conditions.values())
    assert not any(e.event_type=='SAVE_ROLLED' and e.actor_id==ALLY and 'domain_pressure' in e.source_definition_id
                   for e in engine.events)


def test_perfected_circulating_shift_uses_native_route_and_exempts_named_foe(tmp_path):
    other_foe = 'actor:factory.worker2-foe1'
    long_reach = {'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.ge',
        'name':'Ge (Dagger-Axe)','quantity':1}]}}
    combat,table,mid = fixture(tmp_path,[Q+'golden_core_form',Q+'domain_armament'],cl=17,
        owner_kit=long_reach,extra_foes=1,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':2,'y':6},FOE:{'x':4,'y':6},other_foe:{'x':3,'y':7}}, owner_golden=('circulating',))
    before = reload(tmp_path,mid).state.actors[OWNER].movement_remaining_ft
    prompts = use(combat,table,mid,'Domain Armament: Manifest',at=(2,5),choices={
        'choice:needle.golden_benefits':['temp_hp','shift'],
        'choice:needle.golden_shift':[FOE], 'choice:needle.golden_step':['step:2,5,0'],
        'reaction:typed.opportunity_attack':'first'})
    engine = reload(tmp_path,mid); owner = engine.state.actors[OWNER]
    assert (owner.position.x,owner.position.y) == (2,5)
    assert owner.temporary_hp == 8 and owner.movement_remaining_ft == before
    assert not any(e.event_type=='ATTACK_ROLLED' and e.actor_id==FOE
                   and 'opportunity' in e.source_definition_id for e in engine.events)
    from combat.typed_reactions import opportunity_reach
    assert engine.grid.distance_ft(owner.position, engine.state.actors[FOE].position) > opportunity_reach(engine, engine.state.actors[FOE])
    # The endpoint is 10 feet from the selected foe, outside its 5-foot reach.
    # Another enemy was also adjacent and receives its normal Opportunity Attack.
    assert any(e.event_type=='ATTACK_ROLLED' and e.actor_id==other_foe
               and 'opportunity' in e.source_definition_id for e in engine.events)


def test_perfected_circulating_refreshes_shift_targets_after_first_benefit(tmp_path):
    new_foe = 'actor:factory.worker2-foe1'
    combat, table, mid = fixture(tmp_path, [Q+'golden_core_form', Q+'domain_armament'], cl=17,
        extra_foes=1, positions={OWNER:{'x':3,'y':6}, ALLY:{'x':8,'y':7},
                                 FOE:{'x':4,'y':6}, new_foe:{'x':1,'y':5}}, owner_golden=('circulating',))
    prompts = use(combat, table, mid, 'Domain Armament: Manifest', at=(2,5), choices={
        'choice:needle.golden_benefits':['move','shift'],
        'choice:needle.golden_step':('first','first'),
        'choice:needle.golden_shift':new_foe,
        })
    shift_menu = next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.golden_shift')
    assert new_foe in {row['id'] for row in shift_menu['choice']['options']}
    assert FOE not in {row['id'] for row in shift_menu['choice']['options']}
    engine = reload(tmp_path, mid)
    assert (engine.state.actors[OWNER].position.x, engine.state.actors[OWNER].position.y) != (3,6)


def test_second_core_tempering_expression_slot_is_available_and_persists(tmp_path):
    B = 'tianxia.path.body_refining.feature.'
    def two_slots(bundles):
        from combat.canonical import canonical_sha256
        for row in bundles[0]['action_catalog']:
            if (row.get('parameters') or {}).get('cte_choice'):
                row['parameters']['cte_expression_slots'] = 2
        bundles[0].pop('bundle_sha256',None)
        bundles[0]['bundle_sha256'] = canonical_sha256(bundles[0])
    combat,table,mid = fixture(tmp_path,[B+'core_tempering_expression'],cl=17,
        primary='Stamina',owner_path='Body Refining',bundle_transform=two_slots)
    use(combat,table,mid,'Core Tempering Expression: Blood-Furnace Circulation')
    use(combat,table,mid,'Core Tempering Expression: Golden Bell Circulation')
    use(combat,table,mid,'Golden Bell Circulation')
    owner = reload(tmp_path,mid).state.actors[OWNER]
    assert {str((c.data or {}).get('expression')) for c in owner.conditions.values()
            if c.condition_id == 'condition:typed.core_tempering_expression'} == {'golden_bell','blood_furnace'}
    from combat.ext.bodya_body_refining import perfected_golden_bell_dice
    from combat.gate2_rolls import DiceSpec
    d12 = perfected_golden_bell_dice(reload(tmp_path,mid), owner, {}, 1, DiceSpec(count=1,sides=10,modifier=0))
    assert d12 is not None and d12.sides == 12


def test_mountain_rending_survives_intervening_turns_and_expires_at_next_owner_end(tmp_path):
    B = 'tianxia.path.body_refining.feature.'
    combat,table,mid = fixture(tmp_path,[B+'core_tempering_expression',B+'iron_voice'],cl=17,
        primary='Stamina',owner_path='Body Refining')
    use(combat,table,mid,'Core Tempering Expression: Mountain-Rending Pulse')
    use(combat,table,mid,'Iron Voice',target=FOE)
    ready = 'condition:typed.mountain_rending_ready'
    assert any(c.condition_id==ready for c in reload(tmp_path,mid).state.actors[OWNER].conditions.values())
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert any(c.condition_id==ready for c in reload(tmp_path,mid).state.actors[OWNER].conditions.values())
    turn(table,mid,OWNER)
    assert any(c.condition_id==ready for c in reload(tmp_path,mid).state.actors[OWNER].conditions.values())
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert not any(c.condition_id==ready for c in reload(tmp_path,mid).state.actors[OWNER].conditions.values())
