"""Source second pass through CombatService, execute_intent and cold replay."""
import pytest
from combat.canonical import canonical_sha256
from combat.tabletop import normalize_map, to_battlefield
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.h1_support import sheet

LOCK = 'tianxia.talent.source.source_lock'
NAIL = 'tianxia.talent.source.world_nail_source_seal'
SCRIPTURE = 'tianxia.talent.source.source_heaven_sealing_scripture'
PULSE = 'SOURCE_BASE_SOURCE_PULSE'
CIRCUIT = 'tianxia.talent.source.source_circuit'
THREAD = 'PUPPETRY_BASE_THREAD_THE_OBJECT'


def arena(*, mineral=True, door=False, walls=(), object_overrides=None):
    return to_battlefield(normalize_map({'display_name': 'Source checks', 'width_squares': 8, 'height_squares': 9,
        'walls': list(walls),
        'materials': [{'material': 'terrain:loose rubble', 'cells': [[x,y] for x in range(8) for y in range(9)]}] if mineral else [],
        'objects': [{'id': 1, 'kind': 'door', 'x': 4, 'y': 5, 'material': 'iron', 'size': 'medium', 'hp': 500,
                     'weight_lb': 5, 'interaction': 'simple_door', 'door_open': 0, 'door_locked': 0, 'door_jammed': 0, **(object_overrides or {})}] if door else []}))


def seal_zones(engine):
    return [z for z in engine.state.zones.values() if z.active and (z.trigger_profile.get('profile') or {}).get('source_lock')]


def checks(engine):
    return [e for e in engine.events if e.event_type == 'CHECK_ROLLED' and e.payload.get('skill') == 'Athletics']


@pytest.mark.parametrize('feature,label,cost', [(LOCK,'Source Lock',1),(NAIL,'World-Nail Source Seal',4)])
@pytest.mark.parametrize('dc,passes', [(1,True),(40,False)])
def test_section_seal_checks_physical_passage_and_persists(tmp_path,feature,label,cost,dc,passes):
    combat, table, mid = fixture(tmp_path,[feature],dc=dc,battlefield=arena(),seed=f'{label}-{dc}',
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:{'x':5,'y':6}})
    before=reload(tmp_path,mid)
    settle(table,mid,candidate(combat,mid,label+': surface',at=(4,6)).candidate_id)
    sealed=reload(tmp_path,mid)
    assert before.state.actors[OWNER].resources['resource:core.qi']-sealed.state.actors[OWNER].resources['resource:core.qi']==cost
    [zone]=seal_zones(sealed)
    assert {(p.x,p.y) for p in zone.affected_cells} == {(4,6)}
    assert zone.duration_rounds==10 and zone.trigger_profile['profile']['dc']==dc
    turn(table,mid,FOE)
    move=next(c for c in combat._load_session(mid).engine.legal_candidates() if c.kind=='MOVE' and c.destination and (c.destination.x,c.destination.y)==(4,6))
    settle(table,mid,move.candidate_id)
    after=reload(tmp_path,mid)
    assert len(checks(after))==1
    assert after.state.actors[FOE].position.x==(4 if passes else 5)
    assert seal_zones(after), 'a successful check permits one attempt, not permanent dispelling'


def test_scripture_is_optional_pays_one_extra_cp_and_records_ten_minute_duration(tmp_path):
    combat,table,mid=fixture(tmp_path,[LOCK,SCRIPTURE],battlefield=arena())
    labels={a.display_name for a in reload(tmp_path,mid).action_catalog.values()}
    assert 'Source Lock: surface' in labels and 'Source Lock + Source-Heaven Sealing Scripture: surface' in labels
    before=reload(tmp_path,mid)
    settle(table,mid,candidate(combat,mid,'Source Lock + Source-Heaven Sealing Scripture: surface',at=(4,6)).candidate_id)
    after=reload(tmp_path,mid)
    [zone]=seal_zones(after)
    assert zone.duration_rounds==100
    assert before.state.actors[OWNER].resources['resource:core.qi']-after.state.actors[OWNER].resources['resource:core.qi']==2
    assert not [e for e in after.events if e.event_type=='GM_RIDER' and SCRIPTURE in e.source_definition_id]


@pytest.mark.parametrize('feature,label',[(LOCK,'Source Lock'),(NAIL,'World-Nail Source Seal')])
@pytest.mark.parametrize('dc,passes',[(1,True),(40,False)])
def test_object_seal_gates_opening_a_real_door(tmp_path,feature,label,dc,passes):
    combat,table,mid=fixture(tmp_path,[feature],ally_talents=[THREAD],battlefield=arena(door=True),dc=dc)
    settle(table,mid,candidate(combat,mid,label+': object',target='object:map.1').candidate_id)
    sealed=reload(tmp_path,mid)
    assert seal_zones(sealed)[0].trigger_profile['profile']['object_id']=='object:map.1'
    turn(table,mid,ALLY)
    prompts=settle(table,mid,candidate(combat,mid,'Thread the Object: open/close simple door',target='object:map.1').candidate_id,
                   {'choice:needle.thread_door':'OPEN'})
    after=reload(tmp_path,mid)
    assert prompts and after.state.objects['object:map.1'].component['door_open']==int(passes)
    assert len(checks(after))==1


def test_unknown_surface_is_not_a_seal_target(tmp_path):
    combat,table,mid=fixture(tmp_path,[LOCK],battlefield=arena(mineral=False))
    engine=reload(tmp_path,mid)
    assert not [c for c in engine.legal_candidates() if 'source_lock' in c.source_definition_id]


def high_attacks(bundles):
    for bundle in bundles:
        for action in bundle['action_catalog']:
            typed=action.get('parameters',{}).get('typed') or {}
            if typed.get('source')==PULSE:
                typed['numbers']['attack_bonus']=100
        bundle.pop('bundle_sha256',None)
        bundle['bundle_sha256']=canonical_sha256(bundle)


@pytest.mark.parametrize('strong_first',[False,True])
def test_two_casters_pulse_reductions_use_strongest_live_effect(tmp_path,strong_first):
    foe=sheet([],cl=15);foe['ability_scores_and_statistics']['hit_points']['maximum']=500
    combat,table,mid=fixture(tmp_path,[PULSE,CIRCUIT],ally_talents=[PULSE],foe_sheet=foe,bundle_transform=high_attacks,seed=f'PULSE-{strong_first}')
    if strong_first:
        settle(table,mid,candidate(combat,mid,'Source Circuit',target=OWNER).candidate_id)
    settle(table,mid,candidate(combat,mid,'Source Pulse',target=FOE).candidate_id)
    first=reload(tmp_path,mid)
    assert first._effective_speed(first.state.actors[FOE])==(10 if strong_first else 20)
    turn(table,mid,ALLY)
    settle(table,mid,candidate(combat,mid,'Source Pulse',target=FOE).candidate_id)
    after=reload(tmp_path,mid)
    assert after._effective_speed(after.state.actors[FOE])==(10 if strong_first else 20)
    explanation=after.movement_explanation(FOE)
    grouped=[row for row in explanation['reasons'] if row['code']=='SPEED_PENALTY'
             and 'Source Pulse' in row['message']]
    assert len(grouped)==1 and grouped[0]['delta_ft']==(-20 if strong_first else -10), grouped
    assert len([c for c in after.state.actors[FOE].conditions.values() if c.condition_id=='condition:typed.source_pulse_slow'])==2
    turn(table,mid,OWNER)
    expired=reload(tmp_path,mid)
    assert expired._effective_speed(expired.state.actors[FOE])==20,'the second caster\'s independent expiry remains'
    turn(table,mid,ALLY)
    clean=reload(tmp_path,mid)
    assert clean._effective_speed(clean.state.actors[FOE])==30


def test_meridian_regulation_can_choose_and_suppress_source_pulse_after_commit_reload(tmp_path):
    """A real grouped Source Pulse remains a player-selectable Meridian penalty across service reloads."""
    combat,table,mid=fixture(tmp_path,[],ally_talents=['tianxia.path.qi_cultivation.feature.meridian_regulation'],
                             ally_score=18,foe_sheet=sheet([PULSE]),bundle_transform=high_attacks,seed='PULSE-MERIDIAN',
                             positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':5,'y':6}})
    turn(table,mid,FOE)
    pulse=candidate(combat,mid,'Source Pulse',target=ALLY)
    settle(table,mid,pulse.candidate_id)
    applied=reload(tmp_path,mid)
    slowed=[(key,row) for key,row in applied.state.actors[ALLY].conditions.items()
            if row.condition_id=='condition:typed.source_pulse_slow']
    assert slowed, 'the attack/save path did not apply Source Pulse'
    turn(table,mid,ALLY)
    menu_explanation=table.state(mid)['menu']['movement_explanation']['summary']
    menu_grouped=[row for row in menu_explanation['reasons'] if row['code']=='SPEED_PENALTY'
                  and 'Source Pulse' in row['message']]
    assert len(menu_grouped)==1 and menu_grouped[0]['delta_ft']==-10, menu_grouped
    regulation=candidate(combat,mid,'Meridian Regulation',target=ALLY)
    prompts=settle(table,mid,regulation.candidate_id,
                   choices={'choice:needle.meridian_regulation':f'condition:{slowed[0][0]}'})
    question=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.meridian_regulation')
    labels=[option['label'] for option in question['choice']['options']]
    assert any('Speed reduced' in label and 'Source Pulse' in label for label in labels), labels
    after=reload(tmp_path,mid)
    regulation_saves=[event for event in after.events if event.event_type=='SAVE_ROLLED'
                      and 'meridian_regulation' in event.source_definition_id]
    assert regulation_saves and regulation_saves[-1].payload.get('success') is True, regulation_saves
    assert slowed[0][0] not in after.state.actors[ALLY].conditions
    assert any(c.condition_id=='condition:typed.benefit_suppressed'
               for c in after.state.actors[ALLY].conditions.values())
    assert after._effective_speed(after.state.actors[ALLY]) == 30

SEAM='tianxia.talent.source.pulse_through_the_seam'


def test_seam_origin_binds_geometry_without_moving_caster(tmp_path):
    combat,table,mid=fixture(tmp_path,[PULSE,SEAM],battlefield=arena(),bundle_transform=high_attacks)
    action=next(c for c in combat._load_session(mid).engine.legal_candidates()
                if c.target_ids==(FOE,) and (c.metadata.get('effect_origin') or {}).get('id')=='source_seam:4,6,0')
    before=reload(tmp_path,mid)
    settle(table,mid,action.candidate_id)
    after=reload(tmp_path,mid)
    assert after.state.actors[OWNER].position==before.state.actors[OWNER].position
    assert after.state.actors[FOE].current_hp<before.state.actors[FOE].current_hp
    assert after._effective_speed(after.state.actors[FOE])==20
    assert not [e for e in after.events if e.event_type=='GM_RIDER' and SEAM in e.source_definition_id]
    assert any('effect_origin' in str(e.payload) for e in after.events)


def test_ai_pulse_with_both_sides_in_range_harms_only_enemy(tmp_path):
    combat,table,mid=fixture(tmp_path,[PULSE],battlefield=arena(),bundle_transform=high_attacks)
    before=reload(tmp_path,mid)
    choices=[c for c in before.legal_candidates() if c.source_definition_id in before.action_catalog
             and before.action_catalog[c.source_definition_id].display_name=='Source Pulse'
             and not c.metadata.get('object_target')]
    assert choices and all(c.target_ids==(FOE,) for c in choices)
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    settle(table,mid,None,auto=True)
    after=reload(tmp_path,mid)
    assert any(e.event_type=='ATTACK_ROLLED' and e.target_ids==(FOE,) and PULSE in e.source_definition_id for e in after.events)
    assert after.state.actors[ALLY].current_hp==before.state.actors[ALLY].current_hp
    assert after.state.actors[OWNER].current_hp==before.state.actors[OWNER].current_hp
    assert not any(c.condition_id=='condition:typed.source_pulse_slow'
                   for c in after.state.actors[ALLY].conditions.values())


@pytest.mark.parametrize('dc,passes',[(1,True),(40,False)])
def test_sealed_object_break_attempt_uses_check_and_pulse_object_damage_only(tmp_path,dc,passes):
    combat,table,mid=fixture(tmp_path,[LOCK],ally_talents=[PULSE],battlefield=arena(door=True),dc=dc,bundle_transform=high_attacks)
    settle(table,mid,candidate(combat,mid,'Source Lock: object',target='object:map.1').candidate_id)
    before=reload(tmp_path,mid)
    turn(table,mid,ALLY)
    settle(table,mid,candidate(combat,mid,'Source Pulse',target='object:map.1').candidate_id)
    after=reload(tmp_path,mid)
    assert len(checks(after))==1
    assert (after.state.objects['object:map.1'].current_hp<before.state.objects['object:map.1'].current_hp)==passes
    assert not any(c.condition_id=='condition:typed.source_pulse_slow' for a in after.state.actors.values() for c in a.conditions.values())


def test_pulse_cannot_make_speed_negative(tmp_path):
    foe=sheet([],cl=15);foe['ability_scores_and_statistics']['speed']['walking_ft']=5
    combat,table,mid=fixture(tmp_path,[PULSE],foe_sheet=foe,bundle_transform=high_attacks)
    settle(table,mid,candidate(combat,mid,'Source Pulse',target=FOE).candidate_id)
    after=reload(tmp_path,mid)
    assert after._effective_speed(after.state.actors[FOE])==0


@pytest.mark.parametrize('subject',[OWNER,ALLY,FOE])
def test_section_seal_affects_all_sides_as_printed(tmp_path,subject):
    combat,table,mid=fixture(tmp_path,[LOCK],battlefield=arena(),dc=40,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:{'x':5,'y':6}})
    settle(table,mid,candidate(combat,mid,'Source Lock: surface',at=(4,6)).candidate_id)
    turn(table,mid,subject)
    engine=combat._load_session(mid).engine
    action=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination and (c.destination.x,c.destination.y)==(4,6))
    before=reload(tmp_path,mid)
    settle(table,mid,action.candidate_id)
    after=reload(tmp_path,mid)
    assert (after.state.actors[subject].position.x,after.state.actors[subject].position.y)!=(4,6)
    assert len(checks(after))==1 and checks(after)[0].actor_id==subject
    assert checks(after)[0].payload['success'] is False


def test_section_seal_expires_and_no_longer_checks_passage(tmp_path):
    combat,table,mid=fixture(tmp_path,[LOCK],battlefield=arena(),dc=40,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:{'x':5,'y':6}})
    settle(table,mid,candidate(combat,mid,'Source Lock: surface',at=(4,6)).candidate_id)
    first=reload(tmp_path,mid)
    zone_id=seal_zones(first)[0].zone_id
    for _ in range(33):
        if not seal_zones(combat._load_session(mid).engine):
            break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    after=reload(tmp_path,mid)
    assert not seal_zones(after)
    assert any(e.event_type=='ZONE_REMOVED' and e.payload.get('zone_id')==zone_id for e in after.events)
    turn(table,mid,FOE)
    move=next(c for c in combat._load_session(mid).engine.legal_candidates() if c.kind=='MOVE' and c.destination and (c.destination.x,c.destination.y)==(4,6))
    settle(table,mid,move.candidate_id)
    after=reload(tmp_path,mid)
    assert (after.state.actors[FOE].position.x,after.state.actors[FOE].position.y)==(4,6)
    assert not checks(after)


def test_opened_world_nail_door_still_checks_passage(tmp_path):
    combat,table,mid=fixture(tmp_path,[NAIL],ally_talents=[THREAD],battlefield=arena(door=True),dc=1,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:{'x':5,'y':5}})
    settle(table,mid,candidate(combat,mid,'World-Nail Source Seal: object',target='object:map.1').candidate_id)
    turn(table,mid,ALLY)
    settle(table,mid,candidate(combat,mid,'Thread the Object: open/close simple door',target='object:map.1').candidate_id,
           {'choice:needle.thread_door':'OPEN'})
    before=reload(tmp_path,mid)
    assert before.state.objects['object:map.1'].component['door_open']==1
    turn(table,mid,FOE)
    move=next(c for c in combat._load_session(mid).engine.legal_candidates() if c.kind=='MOVE' and c.destination and (c.destination.x,c.destination.y)==(4,5))
    settle(table,mid,move.candidate_id)
    after=reload(tmp_path,mid)
    assert len(checks(after))==2 and checks(after)[-1].actor_id==FOE
    assert (after.state.actors[FOE].position.x,after.state.actors[FOE].position.y)==(4,5)


def test_seam_visible_origin_does_not_reveal_enemy_behind_wall_to_ai(tmp_path):
    from combat import senses
    from combat.action_geometry import origins, activate
    combat,table,mid=fixture(tmp_path,[PULSE,SEAM],battlefield=arena(walls=[
        {'shape':'rect','points':[[5,6],[6,7]],'filled':True}]),bundle_transform=high_attacks)
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    engine=reload(tmp_path,mid)
    actor=engine.state.actors[OWNER];target=engine.state.actors[FOE]
    assert not senses.perceives(engine,actor,target)
    action=next(a for a in engine.action_catalog.values() if a.display_name=='Source Pulse')
    origin=next(o for o in origins(engine,actor,action) if o['id']=='source_seam:4,4,0')
    with activate(engine,actor,action.source_definition_id,origin):
        assert senses.perceives(engine,actor,target),'the remote point has clear sight, but is not a sensor'
    assert not [c for c in engine.legal_candidates() if c.target_ids==(FOE,) and c.metadata.get('effect_origin')]
    before=target.current_hp
    settle(table,mid,None,auto=True)
    after=reload(tmp_path,mid)
    assert after.state.actors[FOE].current_hp==before


@pytest.mark.parametrize('overrides', [
    {'material': 'wood'}, {'artifact': True}, {'unattended': False}, {'size': 'large'},
])
def test_recorded_nonmineral_and_protected_objects_are_not_seal_targets(tmp_path, overrides):
    combat, table, mid = fixture(tmp_path, [LOCK, NAIL], battlefield=arena(
        mineral=False, door=True, object_overrides=overrides))
    before = reload(tmp_path, mid)
    obj = before.state.objects['object:map.1']
    assert not obj.destroyed
    assert obj.component['material'] == overrides.get('material', 'iron')
    assert obj.component['artifact'] == overrides.get('artifact', False)
    assert obj.unattended == overrides.get('unattended', True)
    assert obj.component['size'] == overrides.get('size', 'medium')
    assert not [c for c in before.legal_candidates()
                if 'source_lock' in c.source_definition_id or 'world_nail_source_seal' in c.source_definition_id]
    # Commit through execute_intent, then reopen and regenerate the menu.
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    after = reload(tmp_path, mid)
    assert not [c for c in after.legal_candidates()
                if 'source_lock' in c.source_definition_id or 'world_nail_source_seal' in c.source_definition_id]


@pytest.mark.parametrize('material,z', [('stone', 0), ('iron', 2)])
def test_seam_uses_recorded_object_origin_without_painted_terrain(tmp_path, material, z):
    combat, table, mid = fixture(tmp_path, [PULSE, SEAM], battlefield=arena(
        mineral=False, door=True, object_overrides={'material': material, 'z': z, 'blocks': False}),
        bundle_transform=high_attacks)
    before = reload(tmp_path, mid)
    assert before.state.objects['object:map.1'].position.z == z
    rows = [c for c in before.legal_candidates() if c.target_ids == (FOE,)
            and (c.metadata.get('effect_origin') or {}).get('position') == {'x': 4, 'y': 5, 'z': z}]
    assert rows, 'a visible recorded mineral object is a pulse origin'
    origin = rows[0].metadata['effect_origin']
    assert origin['id'] == f'source_seam:4,5,{z}'
    settle(table, mid, rows[0].candidate_id)
    after = reload(tmp_path, mid)
    assert after.state.actors[OWNER].position == before.state.actors[OWNER].position
    assert after.state.actors[FOE].current_hp < before.state.actors[FOE].current_hp
    assert any(e.payload.get('effect_origin') == origin for e in after.events)


def elevated_mineral_zone(bundles):
    high_attacks(bundles)
    bundle = bundles[1]
    bundle['actor_template']['fly_speed_ft'] = 30  # maintain the recorded elevated caster position
    source = 'action:test.recorded_mineral_zone'
    bundle['action_catalog'].append({
        'source_definition_id': source, 'display_name': 'Place recorded mineral terrain',
        'owner_id': ALLY, 'economy': 'ACTION', 'resolution_kind': 'TYPED',
        'target_kind': 'SELF', 'range_ft': 0, 'costs': [],
        'parameters': {'typed': {'source': source, 'numbers': {}, 'effects': [{'type': 'zone'}], 'zone_spec': {
            'name': 'Recorded mineral platform', 'shape': 'cube',
            'size_ft': 5, 'centered_on_self': True, 'terrain': ['loose rubble'],
            'visual': {'material': 'stone'}, 'duration': {'kind': 'minutes', 'amount': 1},
        }}}})
    bundle['actor_template']['action_ids'].append(source)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)


def test_seam_uses_elevated_mineral_zone_and_distinguishes_same_xy_altitudes(tmp_path):
    combat, table, mid = fixture(tmp_path, [PULSE, SEAM], battlefield=arena(),
        bundle_transform=elevated_mineral_zone,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 5, 'z': 2}, FOE: {'x': 6, 'y': 6}})
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Place recorded mineral terrain').candidate_id)
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    zone = next(z for z in before.state.zones.values() if z.trigger_profile.get('name') == 'Recorded mineral platform')
    assert zone.center.z == 2
    rows = [c for c in before.legal_candidates() if c.target_ids == (FOE,)
            and (c.metadata.get('effect_origin') or {}).get('position', {}).get('x') == 4
            and c.metadata['effect_origin']['position']['y'] == 5]
    assert {c.metadata['effect_origin']['position'].get('z', 0) for c in rows} == {0, 2}
    chosen = next(c for c in rows if c.metadata['effect_origin']['position']['z'] == 2)
    assert chosen.metadata['effect_origin']['id'] == 'source_seam:4,5,2'
    assert len({c.candidate_id for c in rows}) == len(rows)
    settle(table, mid, chosen.candidate_id)
    after = reload(tmp_path, mid)
    assert after.state.actors[OWNER].position == before.state.actors[OWNER].position
    assert after.state.actors[FOE].current_hp < before.state.actors[FOE].current_hp
    assert any(e.payload.get('effect_origin') == chosen.metadata['effect_origin'] for e in after.events)
