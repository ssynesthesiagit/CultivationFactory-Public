"""Native intents, committed placement state and cold replay."""
import pytest
from combat.ext import placed
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
DART = 'TRAP_BASE_DART_MECHANISM'
TRIP = 'TRAP_BASE_TRIPWIRE'
SET = 'FORMATIONS_BASE_SET_ARRAY'


def setup(tmp_path, row, cl=5):
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    doc = sheet([row], cl=cl, kit={'starting_kit':{'items':[
        {'item_id':'tianxia.mortal.gear.chalk','quantity':1,'name':'Chalk'},
        {'item_id':'tianxia.mortal.tool.thieves_tools','quantity':1,'name':'Thieves’ tools'}]}})
    if row == SET:
        doc['spheres_and_talents']['formation_patterns']=['locking_gate']
    owner = compile_character(doc,actor_id=OWNER)
    return fixture(tmp_path, [row], owner_bundle=owner, cl=cl, positions={OWNER: {'x': 3, 'y': 6},
        ALLY: {'x': 2, 'y': 6}, FOE: {'x': 6, 'y': 5}})


def arm(combat, table, mid, form, cells=()):
    settle(table, mid, candidate(combat, mid, 'Trap form: ' + form).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Trap aim: east').candidate_id)
    return settle(table, mid, candidate(combat, mid, 'Set Trap: choose footprint', at=(4, 7)).candidate_id,
                  {'choice:needle.trap_footprint': tuple([*cells, 'finish'])})


@pytest.mark.parametrize('cl,cap', [(1, 1), (5, 2), (10, 3), (15, 4)])
def test_connected_footprint_cap_reload(tmp_path, cl, cap):
    combat, table, mid = setup(tmp_path, TRIP, cl)
    prompts = arm(combat, table, mid, 'Tripwire', ['cell:3,7,0', 'cell:4,6,0', 'cell:4,5,0'][:cap-1])
    e = reload(tmp_path, mid)
    z = placed.of(e, 'trap')[0]
    assert len(z.affected_cells) == cap
    assert all(e._distance_actor_to_cell(e.state.actors[OWNER], p) <= 5 for p in z.affected_cells)
    for p in prompts:
        if p['context']['reaction_source_id'] == 'choice:needle.trap_footprint':
            assert 'cell:3,6,0' not in {o['id'] for o in p['choice']['options']}


@pytest.mark.parametrize('form,row', [('Dart Mechanism', DART), ('Tripwire', TRIP)])
def test_trigger_second_cell_and_reload(tmp_path, form, row):
    combat, table, mid = setup(tmp_path, row)
    arm(combat, table, mid, form, ['cell:4,6,0'])
    turn(table, mid, FOE)
    e = combat._load_session(mid).engine
    move = next(c for c in e.legal_candidates() if c.kind.value == 'MOVE' and c.destination and
                (c.destination.x, c.destination.y) == (4, 6))
    prompts = settle(table, mid, move.candidate_id, {'choice:needle.trap_dart_origin': 'cell:4,6,0'})
    e = reload(tmp_path, mid)
    if row == DART:
        origins = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.trap_dart_origin']
        assert origins
        assert {o['id'] for o in origins[0]['choice']['options']} == {'cell:4,7,0', 'cell:4,6,0'}
        assert not placed.of(e, 'trap')
    else:
        assert placed.of(e, 'trap')
        assert any(v.event_type == 'SAVE_ROLLED' and v.actor_id == FOE for v in e.events)


def test_pulse_bound_array_round_key(tmp_path):
    combat, table, mid = setup(tmp_path, SET, 15)
    settle(table, mid, candidate(combat, mid, 'Combat Array: Locking Gate', at=(5, 6)).candidate_id)
    e = reload(tmp_path, mid)
    row = candidate(combat, mid, 'Pulse: Locking Gate', target=FOE)
    z = next(z for z in e.state.zones.values() if z.active and z.trigger_profile.get('formation'))
    assert row.metadata['effect_origin']['id'] == 'formation:' + z.zone_id
    settle(table, mid, row.candidate_id)
    e = reload(tmp_path, mid)
    assert e.state.actors[FOE].turn_flags['formation_round_pulse:locking_gate'] == e.state.round_number


def test_activation_real_stock_one_per_trigger_and_unused_recovery(tmp_path):
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    from combat import carry
    acid = 'tianxia.mortal.gear.acid'
    doc = sheet(['TRAP_BASE_ACTIVATION_TRAP'], cl=5,
        kit={'starting_kit': {'items': [{'item_id': acid, 'quantity': 3, 'name': 'Acid'},
            {'item_id':'tianxia.mortal.tool.thieves_tools','quantity':1,'name':'Thieves’ tools'}]}})
    bundle = compile_character(doc, actor_id=OWNER)
    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle, cl=5,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':2,'y':6},FOE:{'x':6,'y':5}})
    settle(table,mid,candidate(combat,mid,'Trap form: Activation Trap').candidate_id)
    settle(table,mid,candidate(combat,mid,'Set Trap',at=(4,6)).candidate_id,
        {'choice:needle.trap_payload_count':'3'})
    e = reload(tmp_path,mid)
    owner = e.state.actors[OWNER]
    item = next(i for i in carry.carrying_of(e,OWNER)['items'] if i['item_id']==acid)
    assert carry.remaining_quantity(e,owner,item)==0
    turn(table,mid,FOE)
    e=combat._load_session(mid).engine
    move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination and
        (c.destination.x,c.destination.y)==(4,6))
    settle(table,mid,move.candidate_id)
    e=reload(tmp_path,mid)
    trap=placed.of(e,'trap')[0]
    assert placed.data(trap)['payload']['remaining']==2
    assert any(v.event_type=='SAVE_ROLLED' and v.actor_id==FOE for v in e.events)
    turn(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Disarm Trap',at=(4,6)).candidate_id)
    settle(table,mid,candidate(combat,mid,'Recover unused trap payload').candidate_id)
    e=reload(tmp_path,mid)
    assert not placed.of(e,'trap')
    assert carry.remaining_quantity(e,e.state.actors[OWNER],item)==2
    assert not any(e.action_catalog.get(c.source_definition_id) and
        e.action_catalog[c.source_definition_id].display_name=='Recover unused trap payload'
        for c in e.legal_candidates())


def test_unknown_learning_requires_owned_permanent_training_choice(tmp_path):
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    doc=sheet([SET],cl=5,kit={'starting_kit':{'items':[
        {'item_id':'tianxia.mortal.gear.chalk','quantity':1,'name':'Chalk'}]}})
    combat,table,mid=fixture(tmp_path,[],owner_bundle=compile_character(doc,actor_id=OWNER))
    def names():
        e=combat._load_session(mid).engine
        return {e.action_catalog[c.source_definition_id].display_name for c in e.legal_candidates()
                if c.source_definition_id in e.action_catalog}
    assert not any(n.startswith('Combat Array:') for n in names())
    assert len([n for n in names() if n.startswith('Formation Training: learn ')])==6
    prompts=settle(table,mid,candidate(combat,mid,'Formation Training: learn Locking Gate').candidate_id)
    learning=[p for p in prompts if p['context']['reaction_source_id']=='choice:needle.formation_first_pattern']
    assert learning and len(learning[0]['choice']['options'])==6
    e=reload(tmp_path,mid)
    assert any(c.condition_id=='condition:typed.formation_learned_pattern' for c in e.state.actors[OWNER].conditions.values())
    assert not any(n.startswith('Formation Training: learn ') for n in names())
    assert 'Combat Array: Locking Gate' in names()
    assert 'Combat Array: Nourishing Cycle' not in names()


@pytest.mark.parametrize('cl,dice',[(1,1),(5,2),(11,3),(17,4)])
def test_dart_uses_selected_ray_and_printed_cl_damage(tmp_path,cl,dice):
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    doc=sheet([DART],cl=cl,score=30,kit={'starting_kit':{'items':[
        {'item_id':'tianxia.mortal.tool.thieves_tools','quantity':1,'name':'Thieves’ tools'}]}})
    combat,table,mid=fixture(tmp_path,[],owner_bundle=compile_character(doc,actor_id=OWNER),cl=cl,
        seed='MGR-DART-NATIVE',positions={OWNER:{'x':3,'y':6},ALLY:{'x':2,'y':7},FOE:{'x':6,'y':6}})
    if cl==1:
        # At CL 1 the sole legal physical cell is already the selected ray.
        settle(table,mid,candidate(combat,mid,'Trap aim: east').candidate_id)
        settle(table,mid,candidate(combat,mid,'Set Trap',at=(4,6)).candidate_id)
        turn(table,mid,ALLY)
        target=(4,6)
    else:
        arm(combat,table,mid,'Dart Mechanism',['cell:4,6,0'])
        turn(table,mid,ALLY)
        target=(4,7)
    e=combat._load_session(mid).engine
    move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination and
        (c.destination.x,c.destination.y)==target)
    settle(table,mid,move.candidate_id,{'choice:needle.trap_dart_origin':'cell:4,6,0'})
    e=reload(tmp_path,mid)
    attacks=[v for v in e.events if v.event_type=='ATTACK_ROLLED' and FOE in v.target_ids]
    assert attacks
    # Native attack/damage rolls use d6s, with no Path ability modifier added.
    rolls=[r for r in e.rolls if 'DAMAGE' in r.reason and r.actor_id==OWNER]
    assert rolls, [v.payload for v in attacks]
    critical=attacks[-1].payload['natural_result']>=20
    assert len(rolls[-1].dice)==dice*(2 if critical else 1) and all(1<=v<=6 for v in rolls[-1].dice)


@pytest.mark.parametrize('item,area',[('ball_bearings',4),('caltrops',1),('alchemist_s_fire',None)])
def test_ordinary_payload_uses_own_area_or_save_and_remains_consumed(tmp_path,item,area):
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    key='tianxia.mortal.gear.'+item
    doc=sheet(['TRAP_BASE_ACTIVATION_TRAP'],cl=5,score=30,kit={'starting_kit':{'items':[
        {'item_id':key,'quantity':1,'name':item.replace('_',' ')},
        {'item_id':'tianxia.mortal.tool.thieves_tools','quantity':1,'name':'Thieves’ tools'}]}})
    combat,table,mid=fixture(tmp_path,[],owner_bundle=compile_character(doc,actor_id=OWNER),
        foe_sheet=sheet([],cl=5,score=1),
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':2,'y':6},FOE:{'x':6,'y':5}})
    settle(table,mid,candidate(combat,mid,'Trap form: Activation Trap').candidate_id)
    settle(table,mid,candidate(combat,mid,'Set Trap',at=(4,6)).candidate_id)
    turn(table,mid,FOE)
    e=combat._load_session(mid).engine
    move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination and
        (c.destination.x,c.destination.y)==(4,6))
    settle(table,mid,move.candidate_id)
    e=reload(tmp_path,mid)
    assert not placed.of(e,'trap')
    if area:
        hazards=placed.of(e,'ordinary_scatter')
        assert len(hazards)==1 and len(hazards[0].affected_cells)==area
        assert (hazards[0].center.x,hazards[0].center.y)==(4,6)
        assert hazards[0].trigger_profile['numbers']['save_dc']==(10 if item=='ball_bearings' else 15)
    else:
        saves=[v for v in e.events if v.event_type=='SAVE_ROLLED' and v.actor_id==FOE]
        assert saves
        assert any(c.condition_id=='condition:typed.ordinary_item_burning' for c in e.state.actors[FOE].conditions.values())
        before=e.state.actors[FOE].current_hp
        settle(table,mid,table.state(mid)['menu']['end_turn'])
        turn(table,mid,FOE)
        e=reload(tmp_path,mid)
        assert 1<=before-e.state.actors[FOE].current_hp<=4
        settle(table,mid,candidate(combat,mid,'Roll on the ground to extinguish ordinary fire').candidate_id)
        e=reload(tmp_path,mid)
        assert not any(c.condition_id=='condition:typed.ordinary_item_burning' for c in e.state.actors[FOE].conditions.values())
        assert any(c.condition_id=='condition:typed.prone' for c in e.state.actors[FOE].conditions.values())
    assert e.state.actors[OWNER].turn_flags['_round_payload_reserved:'+key]==1


def test_ai_sees_every_owned_legal_placement_and_pulse(tmp_path):
    from combat.gate4_context import build_decision_context
    from combat.candidate_knowledge import query as observed
    from combat.placement_menu import cells
    combat,table,mid=setup(tmp_path,SET,15)
    e=combat._load_session(mid).engine
    catalogue=e.action_catalog
    def sets(rows):
        return [c for c in rows if catalogue.get(c.source_definition_id)
            and catalogue[c.source_definition_id].parameters.get('formation')=='set']
    legal=sets(e.legal_candidates())
    assert legal
    policy,_=combat.policies.for_actor(OWNER)
    context=build_decision_context(e,policy,for_ai=True)
    # Every seat gets one lazy placement root per ability (placement_menu.cells is
    # the exhaustive second stage), never an eager row per square. So each owned
    # Combat Array must reach the AI as that root, evaluated and cell-reachable:
    # the same cells a human menu offers, with the same candidate identities.
    ai=sets(context.legal_candidates)
    roots={c.source_definition_id:c for c in ai if c.metadata.get('placement_picker')}
    for source in {c.source_definition_id for c in legal}:
        root=roots[source]
        assert root.metadata.get('placement_evaluation'), 'the AI must evaluate an owned Combat Array'
        with observed(e):
            assert {c.candidate_id for c in cells(e,root)} == {
                c.candidate_id for c in legal if c.source_definition_id==source}
    settle(table,mid,candidate(combat,mid,'Combat Array: Locking Gate',at=(5,6)).candidate_id)
    e=reload(tmp_path,mid)
    pulses={c.candidate_id for c in e.legal_candidates() if e.action_catalog.get(c.source_definition_id)
        and e.action_catalog[c.source_definition_id].parameters.get('formation')=='pulse'}
    assert pulses
    assert pulses <= {c.candidate_id for c in build_decision_context(e,policy,for_ai=True).legal_candidates}


def test_pulse_selects_one_of_two_real_controlled_arrays(tmp_path):
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    from combat.ext import formations
    sovereign='tianxia.talent.formations.sovereign_of_the_world_diagram'
    doc=sheet([SET,sovereign],cl=15,kit={'starting_kit':{'items':[
        {'item_id':'tianxia.mortal.gear.chalk','quantity':1,'name':'Chalk'}]}})
    doc['spheres_and_talents']['formation_patterns']=['locking_gate']
    combat,table,mid=fixture(tmp_path,[],cl=15,owner_bundle=compile_character(doc,actor_id=OWNER),
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':2,'y':6},FOE:{'x':6,'y':5}})
    settle(table,mid,candidate(combat,mid,'Next Domain: layer Locking Gate').candidate_id)
    settle(table,mid,candidate(combat,mid,'Sovereign of the World-Diagram').candidate_id)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Combat Array: Locking Gate',at=(5,6)).candidate_id)
    e=reload(tmp_path,mid)
    arrays=formations.arrays(e,OWNER)
    assert len(arrays)==2
    selected=next(z for z in arrays if not formations.record(z).get('domain'))
    options=[c for c in e.legal_candidates() if c.target_ids==(FOE,) and e.action_catalog.get(c.source_definition_id)
        and e.action_catalog[c.source_definition_id].display_name=='Pulse: Locking Gate']
    assert {c.metadata['effect_origin']['id'] for c in options}=={'formation:'+z.zone_id for z in arrays}
    row=next(c for c in options if c.metadata['effect_origin']['id']=='formation:'+selected.zone_id)
    settle(table,mid,row.candidate_id)
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].turn_flags['formation_pulsed']['zone']==selected.zone_id


def test_damage_only_activation_restores_focus_from_committed_payload(tmp_path):
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    from combat.ext.trap import MF

    acid='tianxia.mortal.gear.acid'
    doc=sheet(['TRAP_BASE_ACTIVATION_TRAP','TAL_TRAP_TRAPPER_S_RECOVERY'],cl=5,
        kit={'starting_kit':{'items':[{'item_id':acid,'name':'Acid','quantity':1}]}})
    bundle=compile_character(doc,actor_id=OWNER)
    bundle['ordinary_item_specs'][acid]={
        'name':'Damage-only test payload','fragile':0,
        'effects':[{'type':'temp_hp','flat':1,'applies_to':'target'},
                    {'type':'damage','flat':1,'damage_types':['fire'],'applies_to':'target'}]}
    combat,table,mid=fixture(tmp_path,[],owner_bundle=bundle,cl=5,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':2,'y':6},FOE:{'x':6,'y':5}})
    settle(table,mid,candidate(combat,mid,'Trap form: Activation Trap').candidate_id)
    settle(table,mid,candidate(combat,mid,'Set Trap',at=(4,6)).candidate_id)
    turn(table,mid,FOE)
    e=combat._load_session(mid).engine
    move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination and
              (c.destination.x,c.destination.y)==(4,6))
    settle(table,mid,move.candidate_id)
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].resources[MF]==1
    assert not any(v.event_type=='SAVE_ROLLED' and v.actor_id==FOE for v in e.events)
    damage=[v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and FOE in v.target_ids]
    assert damage and damage[-1].payload['hp_damage']==0
    assert damage[-1].payload.get('temporary_hp_absorbed')==1


def test_unrelated_activation_survives_admission_dispatch(tmp_path):
    combat, table, mid = fixture(tmp_path, [], positions={OWNER:{'x':3,'y':6}, ALLY:{'x':2,'y':6}, FOE:{'x':6,'y':5}})
    row = candidate(combat, mid, 'Dash')
    settle(table, mid, row.candidate_id)
    assert reload(tmp_path, mid).state.actors[OWNER].movement_remaining_ft == 60


@pytest.mark.parametrize('answer', ['accept', 'decline'])
def test_veiled_road_recipient_admission_uses_table_interceptor(tmp_path, answer):
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    from combat.fact_consent_admission import combat_records
    doc=sheet([SET],cl=5,kit={'starting_kit':{'items':[
        {'item_id':'tianxia.mortal.gear.chalk','quantity':1,'name':'Chalk'}]}})
    doc['spheres_and_talents']['formation_patterns']=['veiled_road']
    combat,table,mid=fixture(tmp_path,[],owner_bundle=compile_character(doc,actor_id=OWNER),
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':6,'y':5}})
    settle(table,mid,candidate(combat,mid,'Combat Array: Veiled Road',at=(5,6)).candidate_id)
    before=reload(tmp_path,mid).state.actors[FOE].position
    # The consenting mover is the pulse's own target (FOE), so its destination must lie inside this grant:
    # (6,5) -> (4,7) is two squares / 10 feet, exactly the Veiled Road Pulse's budget.
    prompts=settle(table,mid,candidate(combat,mid,'Pulse: Veiled Road (move 10 ft)',target=FOE).candidate_id,
        {'choice:needle.fact_admission.willing_formation_pulse':answer,
         'choice:needle.formation_veil_move':'step:4,7'})
    e=reload(tmp_path,mid)
    records=combat_records(e,e.state.actors[OWNER],source='FORMATIONS_BASE_PULSE_ARRAY')
    assert records and records[-1]['value']==answer
    if answer == 'decline':
        assert e.state.actors[OWNER].bonus_action_available
        assert e.state.actors[FOE].position==before
        assert 'formation_round_pulse:veiled_road' not in e.state.actors[FOE].turn_flags
    else:
        offers=[p for p in prompts if p['context']['reaction_source_id']=='choice:needle.formation_veil_move']
        assert offers and 'step:4,7' in {o['id'] for o in offers[0]['choice']['options']}
        assert not e.state.actors[OWNER].bonus_action_available
        assert (e.state.actors[FOE].position.x, e.state.actors[FOE].position.y)==(4,7)
        assert 'formation_round_pulse:veiled_road' in e.state.actors[FOE].turn_flags
    assert combat_records(e,e.state.actors[ALLY],source='FORMATIONS_BASE_PULSE_ARRAY')==[]


def test_missing_actual_tools_blocks_every_native_placement_route(tmp_path):
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    doc=sheet([TRIP],cl=5)
    doc.pop('equipment')
    combat,table,mid=fixture(tmp_path,[],owner_bundle=compile_character(doc,actor_id=OWNER))
    e=reload(tmp_path,mid)
    assert not any(e.action_catalog.get(c.source_definition_id) and
                   e.action_catalog[c.source_definition_id].parameters.get('set_trap')
                   for c in e.legal_candidates())
    assert any(a.parameters.get('set_trap') for a in e.action_catalog.values() if a.owner_id==OWNER)


@pytest.mark.parametrize('pattern',['locking_gate','sensing_eye','nourishing_cycle','suppressing_vein','killing_line'])
def test_installed_basic_layer_pulses_through_native_journey_table_and_cold_replay(tmp_path,pattern):
    from tests.h1_support import ROOT, sheet
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from combat.ext import formations
    doc=sheet([SET],cl=5,score=30,kit={'starting_kit':{'items':[
        {'item_id':'tianxia.mortal.gear.chalk','name':'Chalk','quantity':1}]}})
    doc['spheres_and_talents']['formation_patterns']=[pattern]
    service=CombatService(ROOT,tmp_path)
    bundles=[compile_character(doc,actor_id=OWNER),compile_character(sheet([],cl=5,score=1),actor_id=FOE)]
    arena={'display_name':'Basic Pattern map','stable_id':'native-basic:'+pattern,'width_squares':15,'height_squares':12,
           'square_size_ft':5,'starting_positions':{},'terrain_regions':[]}
    state=service.journeys.create(bundles,arena,{OWNER:{'x':3,'y':6},FOE:{'x':6,'y':5}},
                                 {OWNER:30,FOE:30})
    if pattern=='killing_line':
        state=service.journey_admit(state['journey_id'],state['revision'],OWNER,'formation_damage_type',
            {'damage_type':'piercing','source_logic':'An installed array of physical needle markers projects piercing needles.'},
            gm=True,reason='GM source declaration: physical needles, not an elemental sphere grant')
        assert service.journeys.replay(state['journey_id'])['status']=='PASS'
    result=service.journey_start_combat(state['journey_id'],state['revision'],{OWNER:'a',FOE:'b'})
    mid=result['match_id']; table=TabletopService(service,tmp_path)
    turn(table,mid,OWNER)
    e=service._load_session(mid).engine
    place=next(c for c in e.legal_candidates() if c.destination and (c.destination.x,c.destination.y)==(5,6)
               and e.action_catalog.get(c.source_definition_id)
               and e.action_catalog[c.source_definition_id].parameters.get('formation')=='set'
               and e.action_catalog[c.source_definition_id].parameters.get('pattern')==pattern
               and (pattern!='killing_line' or any(x.get('damage_type')=='piercing' for x in
                    e.action_catalog[c.source_definition_id].parameters['typed']['effects'])))
    settle(table,mid,place.candidate_id)
    e=reload(tmp_path,mid); z=formations.arrays(e,OWNER)[0]
    assert formations.record(z)['layers']==[pattern]
    recipient=OWNER if pattern=='nourishing_cycle' else FOE
    pulse=next(c for c in e.legal_candidates() if c.target_ids==(recipient,) and
               e.action_catalog.get(c.source_definition_id) and
               e.action_catalog[c.source_definition_id].parameters.get('formation')=='pulse' and
               e.action_catalog[c.source_definition_id].parameters.get('pattern')==pattern)
    resources=dict(e.state.actors[OWNER].resources)
    sequence=e.state.event_sequence
    settle(table,mid,pulse.candidate_id)
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].resources==resources
    assert not e.state.actors[OWNER].bonus_action_available
    assert e.state.actors[recipient].turn_flags['formation_round_pulse:'+pattern]==e.state.round_number
    assert e.state.actors[OWNER].turn_flags['formation_pulsed']['layers']==[pattern]
    new=[v for v in e.events if v.sequence>sequence]
    if pattern in ('locking_gate','suppressing_vein'):
        assert any(v.event_type=='SAVE_ROLLED' and v.actor_id==FOE for v in new)
        assert any(c.condition_id in ('condition:typed.held_fast','condition:typed.formation_cp_locked',
                   'condition:typed.formation_cp_tax') or c.data.get('speed_delta') for c in e.state.actors[FOE].conditions.values())
    elif pattern=='sensing_eye':
        assert any(c.condition_id=='condition:typed.formation_located' and c.data.get('formation_zone')==z.zone_id
                   for c in e.state.actors[FOE].conditions.values())
    elif pattern=='killing_line':
        assert any(v.event_type=='ATTACK_ROLLED' and FOE in v.target_ids for v in new)
    else:
        assert any('HEALING' in r.reason for r in e.rolls)


@pytest.mark.parametrize('item,fragile',[('acid',True),('ball_bearings',False)])
def test_native_object_destruction_keeps_only_recoverable_payload(tmp_path,item,fragile):
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    from combat import carry
    doc=sheet(['TRAP_BASE_ACTIVATION_TRAP'],cl=5,kit={'starting_kit':{'items':[
        {'item_id':'tianxia.mortal.gear.'+item,'name':item,'quantity':2}]}})
    combat,table,mid=fixture(tmp_path,[],owner_bundle=compile_character(doc,actor_id=OWNER),
        foe_sheet=sheet([],cl=5,score=30),positions={OWNER:{'x':3,'y':6},ALLY:{'x':2,'y':6},FOE:{'x':6,'y':5}})
    settle(table,mid,candidate(combat,mid,'Trap form: Activation Trap').candidate_id)
    settle(table,mid,candidate(combat,mid,'Set Trap',at=(4,6)).candidate_id,
           {'choice:needle.trap_payload_count':'2'})
    e=reload(tmp_path,mid); zone=placed.of(e,'trap')[0]
    oid='object:trap:'+zone.zone_id
    assert e.state.objects[oid].maximum_hp==10
    turn(table,mid,FOE)
    e=combat._load_session(mid).engine
    move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination and
              (c.destination.x,c.destination.y)==(4,5))
    settle(table,mid,move.candidate_id)
    for _ in range(5):
        turn(table,mid,FOE)
        e=combat._load_session(mid).engine
        if e.state.objects[oid].destroyed:break
        attack=next(c for c in e.legal_candidates() if c.target_ids==(oid,) and c.metadata.get('object_target'))
        settle(table,mid,attack.candidate_id)
        e=combat._load_session(mid).engine
        if e.state.objects[oid].destroyed:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    e=reload(tmp_path,mid)
    assert e.state.objects[oid].destroyed and not placed.of(e,'trap')
    remaining=placed.data(e.state.zones[zone.zone_id])['payload']['remaining']
    assert remaining==(0 if fragile else 2)
    turn(table,mid,OWNER)
    e=combat._load_session(mid).engine
    recovery=[c for c in e.legal_candidates() if e.action_catalog.get(c.source_definition_id) and
              e.action_catalog[c.source_definition_id].parameters.get('trap_recover_payload')]
    assert bool(recovery) is not fragile
    if recovery:
        settle(table,mid,recovery[0].candidate_id)
        e=reload(tmp_path,mid)
        stock=next(i for i in carry.carrying_of(e,OWNER)['items'] if i['item_id']=='tianxia.mortal.gear.'+item)
        assert carry.remaining_quantity(e,e.state.actors[OWNER],stock)==2


def test_pulse_requires_actual_eye_perception_from_common_rules(tmp_path):
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    from combat.ext import formations
    doc=sheet([SET],cl=5,kit={'starting_kit':{'items':[
        {'item_id':'tianxia.mortal.gear.chalk','name':'Chalk','quantity':1}]}})
    doc['spheres_and_talents']['formation_patterns']=['locking_gate']
    # The one wall sits two squares east of the Eye, so the blocked row is an
    # ordinary orthogonal block and the clear vantage never grazes a wall cap:
    # a wall beside the Eye would put the Eye on its own sight segment.
    arena={'display_name':'Array Eye sight map','stable_id':'native-pulse-sight','width_squares':15,'height_squares':12,
        'square_size_ft':5,'starting_positions':{},'terrain_regions':[
            {'region_id':'wall','terrain_type':'BLOCKED','cells':[{'x':4,'y':8}],
             'movement_cost':1,'description':'Solid wall'}]}
    combat,table,mid=fixture(tmp_path,[],owner_bundle=compile_character(doc,actor_id=OWNER),battlefield=arena,owner_speed=60,
        positions={OWNER:{'x':2,'y':8},ALLY:{'x':1,'y':3},FOE:{'x':1,'y':8}})
    settle(table,mid,candidate(combat,mid,'Combat Array: Locking Gate',at=(2,8)).candidate_id)
    e=combat._load_session(mid).engine
    move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination and
              (c.destination.x,c.destination.y)==(6,8))
    settle(table,mid,move.candidate_id)
    e=reload(tmp_path,mid); z=formations.arrays(e,OWNER)[0]
    assert not e.grid.line_of_sight(e.state.actors[OWNER].position,z.center)
    assert not formations.eye_perceived(e,e.state.actors[OWNER],z)
    assert not any(c.target_ids==(FOE,) and e.action_catalog.get(c.source_definition_id) and
        e.action_catalog[c.source_definition_id].display_name=='Pulse: Locking Gate' for c in e.legal_candidates())
    move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination and
              (c.destination.x,c.destination.y)==(6,7))
    settle(table,mid,move.candidate_id)
    e=reload(tmp_path,mid); z=formations.arrays(e,OWNER)[0]
    assert e.grid.line_of_sight(e.state.actors[OWNER].position,z.center)
    assert formations.eye_perceived(e,e.state.actors[OWNER],z)
    pulse=candidate(combat,mid,'Pulse: Locking Gate',target=FOE)
    assert pulse.metadata['effect_origin']['id']=='formation:'+z.zone_id
    settle(table,mid,pulse.candidate_id)
    assert any(v.event_type=='SAVE_ROLLED' and v.actor_id==FOE for v in reload(tmp_path,mid).events)



def test_creator_knows_tripwire_and_receives_native_save_advantage(tmp_path):
    combat,table,mid=setup(tmp_path,TRIP,5)
    settle(table,mid,candidate(combat,mid,'Trap form: Tripwire').candidate_id)
    settle(table,mid,candidate(combat,mid,'Set Trap',at=(4,6)).candidate_id)
    e=combat._load_session(mid).engine
    move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination and
              (c.destination.x,c.destination.y)==(4,6))
    settle(table,mid,move.candidate_id)
    e=reload(tmp_path,mid)
    saves=[v for v in e.events if v.event_type=='SAVE_ROLLED' and v.actor_id==OWNER]
    assert saves and 'ADVANTAGE' in str(saves[-1].payload)
    assert placed.of(e,'trap')


def test_named_pulse_recipient_cap_crosses_actual_owners_and_refreshes_next_round(tmp_path):
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    doc=sheet([SET],cl=5,kit={'starting_kit':{'items':[
        {'item_id':'tianxia.mortal.gear.chalk','name':'Chalk','quantity':1}]}})
    doc['spheres_and_talents']['formation_patterns']=['locking_gate']
    combat,table,mid=fixture(tmp_path,[],owner_bundle=compile_character(doc,actor_id=OWNER),cl=5,
        ally_talents=[SET],ally_kit={'starting_kit':{'items':[
            {'item_id':'tianxia.mortal.gear.chalk','name':'Chalk','quantity':1}]}},
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:{'x':6,'y':6}})
    settle(table,mid,candidate(combat,mid,'Combat Array: Locking Gate',at=(5,6)).candidate_id)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,ALLY)
    settle(table,mid,candidate(combat,mid,'Formation Training: learn Locking Gate').candidate_id)
    settle(table,mid,candidate(combat,mid,'Combat Array: Locking Gate',at=(5,7)).candidate_id)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    e=reload(tmp_path,mid)
    first,second=sorted((OWNER,ALLY),key=e.state.initiative_order.index)
    turn(table,mid,first)
    settle(table,mid,candidate(combat,mid,'Pulse: Locking Gate',target=FOE).candidate_id)
    round_number=reload(tmp_path,mid).state.round_number
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,second)
    e=reload(tmp_path,mid)
    assert e.state.round_number==round_number
    assert not any(c.target_ids==(FOE,) and e.action_catalog.get(c.source_definition_id) and
                   e.action_catalog[c.source_definition_id].display_name=='Pulse: Locking Gate'
                   for c in e.legal_candidates())
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,first)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,second)
    assert reload(tmp_path,mid).state.round_number==round_number+1
    settle(table,mid,candidate(combat,mid,'Pulse: Locking Gate',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    assert e.state.actors[FOE].turn_flags['formation_round_pulse:locking_gate']==round_number+1


@pytest.mark.parametrize('boundary',['cover','range90'])
def test_dart_native_attack_uses_device_geometry_without_moving_creator(tmp_path,boundary):
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    from combat import action_geometry
    doc=sheet([DART],cl=5,score=20,kit={'starting_kit':{'items':[
        {'item_id':'tianxia.mortal.tool.thieves_tools','name':'Thieves’ tools','quantity':1}]}})
    trap_at=(1,7) if boundary=='cover' else (2,6)
    foe_at=(8,7) if boundary=='cover' else (20,6)
    ally_at=(0,7) if boundary=='cover' else (1,7)
    arena={'display_name':'Dart origin map','stable_id':'dart-native-origin:'+boundary,'width_squares':30,'height_squares':12,
        'square_size_ft':5,'starting_positions':{},'terrain_regions':[
            {'region_id':'wall','terrain_type':'BLOCKED','cells':[{'x':2,'y':6}],
             'movement_cost':1,'description':'Solid wall'}] if boundary=='cover' else []}
    combat,table,mid=fixture(tmp_path,[],owner_bundle=compile_character(doc,actor_id=OWNER),battlefield=arena,
        seed='MGR-DART-ANCHOR-'+boundary,positions={OWNER:{'x':1,'y':6},ALLY:{'x':ally_at[0],'y':ally_at[1]},
            FOE:{'x':foe_at[0],'y':foe_at[1]}})
    settle(table,mid,candidate(combat,mid,'Trap aim: east').candidate_id)
    settle(table,mid,candidate(combat,mid,'Set Trap',at=trap_at).candidate_id)
    turn(table,mid,ALLY)
    e=combat._load_session(mid).engine;z=placed.of(e,'trap')[0]
    if boundary=='cover':
        assert not e.grid.line_of_sight(e.state.actors[OWNER].position,e.state.actors[FOE].position)
        assert e.grid.line_of_sight(z.affected_cells[0],e.state.actors[FOE].position)
    else:
        assert e.grid.distance_ft(e.state.actors[OWNER].position,e.state.actors[FOE].position)==95
        assert e.grid.distance_ft(z.affected_cells[0],e.state.actors[FOE].position)==90
    move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination and
              (c.destination.x,c.destination.y)==trap_at)
    settle(table,mid,move.candidate_id)
    e=reload(tmp_path,mid)
    attacks=[v for v in e.events if v.event_type=='ATTACK_ROLLED' and FOE in v.target_ids]
    assert attacks and attacks[-1].payload['cover_bonus']==0
    origins=[v.payload['effect_origin'] for v in e.events if v.event_type=='PASSIVE_TRIGGERED'
             and v.payload.get('effect_origin',{}).get('id')=='trap:'+z.zone_id]
    from combat.gate2_runtime_models import Position
    assert origins and Position.model_validate(origins[-1]['position']) == Position(x=trap_at[0], y=trap_at[1])
    assert (e.state.actors[OWNER].position.x,e.state.actors[OWNER].position.y)==(1,6)
    action=next(a for a in e.action_catalog.values() if a.owner_id==OWNER and a.parameters.get('set_trap'))
    assert not action_geometry.origins(e,e.state.actors[OWNER],action)
