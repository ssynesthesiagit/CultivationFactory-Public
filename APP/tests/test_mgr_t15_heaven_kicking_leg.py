"""Heaven-Kicking Leg: real compiled attacks, table choices, persistence/replay.

Combat starting sheets are deterministic source-backed fixtures, not a claim to
cover the complete Stage2 -> CharacterSheet export pipeline. Acquisition uses
the native NS1R producer separately; no successful receipt/condition is seeded.
"""
import hashlib
import json
from pathlib import Path

import pytest

from combat.canonical import canonical_sha256
from tests.worker2_support import OWNER, ALLY, FOE, fixture, settle, reload, turn
from tests.cw2_service_support import add_action, seal
from tests.test_r9i_karma_persistence import act
from tests.test_ns1r_non_sphere_authority import authority, insert_project, BODY, QI
from tests.ns1r_evidence_helpers import ap_award, access_evidence

ROOT = Path(__file__).resolve().parents[1]
KICK = 'tianxia.subpath.body.sky_treading_tendon_school.feature.heaven_kicking_leg'
PARENT = 'tianxia.subpath.body.sky_treading_tendon_school'
STAMINA = 'resource:core.stamina'
PAY = 'choice:needle.heaven_kicking_leg'
DEST = 'choice:needle.heaven_kick_destination'
CONSENT = 'choice:needle.heaven_kick_accept_movement'


def test_printed_source_and_literal_runtime_dependencies():
    text = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())[KICK]
    assert hashlib.sha256(text.encode()).hexdigest() == 'e3355ab1ab3b78bc43301544da23b7e14acad853433483d50056ebd9d7b61397'
    # Literal dynamic loader inputs are part of the safe CI export closure.
    for relative in (
        'authority/Tianxia_Typed_Mechanics_Authority_R1.json',
        'combat/rules/feature_blocks.json',
        'combat/rules/feature_blocks.d/tabik.json',
        'combat/rules/feature_blocks.d/auto8-athletics.json',
        'combat/rules/weapon_specials.json',
        'combat/rules/typed_conditions.json',
    ):
        assert (ROOT / relative).is_file(), relative
    authority = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())
    assert authority['mechanics'][KICK]['riders'] == [
        "Kicking it upward, and its fall if it ends unsupported, are the GM's (the table has no altitude)."]


def test_native_open_school_acquisition_owner_attainment_and_cold_state(authority):
    from app.core import FoundryError
    from non_sphere_authority.service import NonSphereAuthorityService
    service, db = authority
    project = 'heaven-kick-native-acquisition'
    insert_project(db, project, target_cl=6)
    service.initialize_for_project(project, target_cl=6, path_ids=[BODY], method_id='METHOD-002',
        access_source_records=access_evidence(db, service, project, 'METHOD-002'))
    for path, code in ((QI, 'NS1R_PATH_SUBPATH_MISMATCH'), (BODY, 'NS1R_SUBPATH_CL3_REQUIRED')):
        with pytest.raises(FoundryError) as exc:
            service.select_subpath(project, path, PARENT)
        assert exc.value.code == code
    service.allocate_advancement(project, {BODY: 5},
        evidence_id=ap_award(db, service, project, 'METHOD-002', 6, 5), idempotency_key='kick-cl6')
    service.select_subpath(project, BODY, PARENT)
    fresh = NonSphereAuthorityService(db)
    state = fresh.get_state(project)
    path = next(p for p in state['paths'] if p['path_id'] == BODY)
    assert path['attainment'] == 6 and path['subpath_or_tradition_id'] == PARENT
    record = fresh.project_locked_subpath_catalog_record(PARENT)
    context = record['compatibility']['factory']['stage2_authority']
    row = next(r for r in context['feature_progression'] if r['canonical_id'] == KICK)
    assert row['granted_at_cl'] == 6 and row['minimum_realm_band'] == 'Foundation'
    assert context['owning_path_id'] == BODY


def setup(tmp_path, *, owns=True, saves=False, size='Medium', stamina=100, wall=False,
          foe_x=6, extra_attack=False, counter=False, shove_distance=10):
    def prepare(bundles):
        actor = bundles[0]['actor_template']
        stamina_pool = next(row for row in actor['resources'] if row['resource_id'] == STAMINA)
        stamina_pool['initial'] = stamina
        bundles[2]['actor_template']['armor_class'] = 0
        bundles[2]['actor_template']['saving_throws']['STR'] = 100 if saves else -100
        bundles[2]['actor_template']['size_category'] = size
        # Native movement preparation; results and willingness are never seeded.
        add_action(bundles[0], 'Accept a shove', [
            {'type': 'directed_forced_movement', 'applies_to': 'self', 'distance_ft': shove_distance}], target='SELF', player_only=False)
        add_action(bundles[0], 'Teleport approach', [
            {'type': 'teleport', 'applies_to': 'self', 'distance_ft': 10}], target='SELF', player_only=False)
        if counter:
            add_action(bundles[2], 'Draw Wren closer', [
                {'type': 'directed_forced_movement', 'applies_to': 'target', 'distance_ft': 10,
                 'relative_directions': ['toward']}], player_only=False)
            bundles[0]['actor_template']['armor_class'] = 100
        for bundle in bundles:
            seal(bundle)
    def arena(a):
        a['terrain_regions'] = []
        if wall:
            a['terrain_regions'] = [{'terrain_id': 'kick-wall', 'terrain_type': 'BLOCKED', 'movement_cost': 0,
                'cells': [{'x': 8, 'y': 7 if wall == 'side_shelf' else 6}],
                'height_ft': 5 if wall in ('shelf', 'side_shelf') else 30,
                'base_altitude_ft': (15 if wall == 'side_shelf' else 5 if wall == 'shelf' else 0)}]
    features = ([KICK] if owns else []) + (['tianxia.path.body_refining.feature.extra_attack'] if extra_attack else [])
    return fixture(tmp_path, ['TAL_IRON_FIST_COUNTER_PALM'] if counter else [],
        owner_features=features, owner_path='Body Refining',
        cl=6, primary='Stamina', named=True, owner_dc=50, bundle_transform=prepare,
        battlefield_transform=arena, seed='MGR-T15-KICK', positions={OWNER: {'x':3,'y':6},
            ALLY: {'x':2,'y':3}, FOE: {'x':foe_x,'y':6}})


def move(combat, table, mid, x=5, y=6):
    engine = combat._load_session(mid).engine
    c = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and
             c.destination.x == x and c.destination.y == y and c.destination.z == 0)
    settle(table, mid, c.candidate_id, choices={})


def strike(combat, mid):
    engine = combat._load_session(mid).engine
    return next(c for c in engine.legal_candidates() if c.display_name.startswith('Unarmed Strike')
                and c.target_ids == (FOE,) and '.shove' not in c.source_definition_id
                and '.grapple' not in c.source_definition_id)


def denied(engine):
    return [c for c in engine.state.actors[FOE].conditions.values() if c.condition_id.endswith('reaction_denied')]


@pytest.mark.parametrize('destination,raised', [('cell:6,9', False), ('cell:6,6,3', True), ('cell:9,6,3', True)])
def test_native_hit_chosen_3d_destination_fall_payment_and_expiry(tmp_path, destination, raised):
    combat, table, mid = setup(tmp_path)
    move(combat, table, mid)
    c = strike(combat, mid)
    before = canonical_sha256(combat._load_session(mid).engine.state.model_dump(mode='json'))
    preview = act(table, mid, c.candidate_id)
    assert preview['status'] == 'REACTION_REQUIRED'
    assert preview['reaction']['context']['reaction_source_id'] == PAY
    assert canonical_sha256(combat._load_session(mid).engine.state.model_dump(mode='json')) == before
    prompts = settle(table, mid, c.candidate_id, choices={PAY: ['use'], DEST: [destination]})
    menu = next(p for p in prompts if p['context']['reaction_source_id'] == DEST)
    assert menu['context']['reactor_id'] == OWNER
    options = {o['id'] for o in menu['choice']['options']}
    labels = [o['label'] for o in menu['choice']['options']]
    assert any('north' in label.lower() for label in labels)
    assert all('(' not in label and 'cell:' not in label for label in labels)
    assert {'cell:6,6,3', 'cell:9,6,3', 'cell:6,9'} <= options
    assert 'cell:10,6,4' not in options
    engine = reload(tmp_path, mid)
    owner, target = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert owner.resources[STAMINA] == 99
    assert not owner.action_available
    movements = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.source_definition_id == KICK]
    assert len(movements) == 1 and movements[0].payload['forced']
    assert not movements[0].payload.get('teleport')
    assert movements[0].payload['path'][-1].get('z', 0) == (3 if raised else 0)
    assert target.position.z == 0
    assert (target.position.x, target.position.y) == tuple(map(int, destination.split(':')[1].split(',')[:2]))
    assert denied(engine) and denied(engine)[0].source_definition_id == KICK
    saved = next(e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.source_definition_id == KICK)
    paid = next(e for e in engine.events if e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == KICK)
    assert paid.sequence < saved.sequence < movements[0].sequence
    falls = [e for e in engine.events if e.source_definition_id == 'system:combat.falling' and e.event_type == 'DAMAGE_COMMITTED']
    assert bool(falls) == raised
    if raised:
        assert any(c.condition_id.endswith('prone') for c in target.conditions.values())
        assert 1 <= int(falls[0].payload['reduced_to']) <= 6
        applied = next(e for e in engine.events if e.event_type == 'CONDITION_APPLIED'
                       and e.source_definition_id == KICK)
        assert movements[0].sequence < applied.sequence < falls[0].sequence
    assert all(type(v) in (str, int) for v in denied(engine)[0].data.values())
    turn(table, mid, FOE)
    assert not denied(reload(tmp_path, mid))


@pytest.mark.parametrize('saves', [False, True])
def test_native_success_or_failure_spends_once_and_success_only_pushes_horizontal(tmp_path, saves):
    combat, table, mid = setup(tmp_path, saves=saves)
    move(combat, table, mid)
    prompts = settle(table, mid, strike(combat, mid).candidate_id, choices={PAY: ['use'], DEST: None})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[STAMINA] == 99
    assert bool(denied(engine)) == (not saves)
    assert (engine.state.actors[FOE].position.x, engine.state.actors[FOE].position.z) == (7 if saves else 6, 0)
    assert sum(p['context']['reaction_source_id'] == PAY for p in prompts) == 1


@pytest.mark.parametrize('size,mode', [('Huge', 'NORMAL'), ('Gargantuan', 'ADVANTAGE')])
def test_three_size_categories_threshold_on_native_save(tmp_path, size, mode):
    combat, table, mid = setup(tmp_path, size=size, saves=True)
    move(combat, table, mid)
    settle(table, mid, strike(combat, mid).candidate_id, choices={PAY: ['use']})
    engine = reload(tmp_path, mid)
    save = next(e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.source_definition_id == KICK)
    assert save.payload['mode'] == mode


@pytest.mark.parametrize('owns,stamina,distance,declare', [(False,100,10,True), (True,0,10,True),
    (True,100,5,True), (True,100,10,False)])
def test_native_owner_distance_resource_and_decline_controls(tmp_path, owns, stamina, distance, declare):
    combat, table, mid = setup(tmp_path, owns=owns, stamina=stamina, foe_x=5 if distance == 5 else 6)
    if distance == 5:
        move(combat, table, mid, x=4)
    else:
        move(combat, table, mid)
    prompts = settle(table, mid, strike(combat, mid).candidate_id, choices={PAY: ['use'] if declare else None})
    engine = reload(tmp_path, mid)
    eligible = owns and stamina > 0 and distance >= 10
    assert any(p['context']['reaction_source_id'] == PAY for p in prompts) == eligible
    assert engine.state.actors[OWNER].resources[STAMINA] == stamina - int(eligible and declare)


def test_short_forced_displacement_does_not_prompt_for_irrelevant_consent(tmp_path):
    combat, table, mid = setup(tmp_path, counter=True, shove_distance=5)
    turn(table, mid, FOE)
    engine = combat._load_session(mid).engine
    shove = next(c for c in engine.legal_candidates() if c.display_name == 'Draw Wren closer')
    prompts = settle(table, mid, shove.candidate_id, choices={'choice:needle.directed_movement': ['toward']})
    assert not any(p['context']['reaction_source_id'] == CONSENT for p in prompts)
    engine = reload(tmp_path, mid)
    event = next(e for e in engine.events if e.actor_id == OWNER and e.event_type == 'MOVEMENT_COMMITTED'
                 and e.payload.get('forced'))
    # The unprompted movement is still resolved normally; this five-foot path
    # simply cannot qualify for the printed ten-foot hit trigger.
    assert event.payload['path'][-1]['x'] - event.payload['path'][0]['x'] == 1


@pytest.mark.parametrize('accept', [False, True])
def test_actual_accepted_forced_movement_counts_only_after_native_consent(tmp_path, accept):
    combat, table, mid = setup(tmp_path, counter=True)
    turn(table, mid, FOE)
    engine = combat._load_session(mid).engine
    shove = next(c for c in engine.legal_candidates() if c.display_name == 'Draw Wren closer')
    prompts = settle(table, mid, shove.candidate_id, choices={CONSENT: ['accept'] if accept else None,
        'choice:needle.directed_movement': ['toward']})
    assert any(p['context']['reaction_source_id'] == CONSENT for p in prompts)
    engine = reload(tmp_path, mid)
    event = next(e for e in engine.events if e.actor_id == OWNER and e.event_type == 'MOVEMENT_COMMITTED'
                 and e.payload.get('forced'))
    assert bool(event.payload.get('willingly_accepted')) == accept
    from combat.ext.sky_treading import moved_this_turn
    assert moved_this_turn(engine, engine.state.actors[OWNER], accepted_forced=True) == (10 if accept else 0)
    assert moved_this_turn(engine, engine.state.actors[OWNER]) == 0


def test_native_extra_attack_spends_once_per_turn(tmp_path):
    combat, table, mid = setup(tmp_path, extra_attack=True)
    move(combat, table, mid)
    prompts = settle(table, mid, strike(combat, mid).candidate_id, choices={PAY: ['use'], DEST: None})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[STAMINA] == 99
    assert sum(p['context']['reaction_source_id'] == PAY for p in prompts) == 1
    # Both attacks are resolved inside the one native Attack action.
    hits = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]
    assert len(hits) == 2


def test_native_success_blocked_push_stays_in_place(tmp_path):
    combat, table, mid = setup(tmp_path, saves=True, foe_x=7, wall=True)
    move(combat, table, mid, x=6)
    settle(table, mid, strike(combat, mid).candidate_id, choices={PAY: ['use']})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].position.x == 7
    assert engine.state.actors[OWNER].resources[STAMINA] == 99
    assert not denied(engine)


def test_native_teleport_does_not_count_as_travel(tmp_path):
    combat, table, mid = setup(tmp_path)
    engine = combat._load_session(mid).engine
    hop = next(c for c in engine.legal_candidates() if c.display_name.startswith('Teleport approach'))
    settle(table, mid, hop.candidate_id, choices={'choice:needle.teleport_destination': ['cell:5,6']})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].position.x == 5
    assert any(e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == OWNER and e.payload.get('teleport')
               for e in engine.events)
    prompts = settle(table, mid, strike(combat, mid).candidate_id, choices={PAY: ['use']})
    assert not any(p['context']['reaction_source_id'] == PAY for p in prompts)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[STAMINA] == 100


def test_native_visible_destination_stops_at_partial_swept_volume_obstruction_and_falls(tmp_path):
    # A floating physical shelf crosses the second swept diagonal volume.
    # The chooser's sight ray passes beside it, while the Large target's
    # footprint cannot fit through it. No three-step route can reach x=9,z=3.
    combat, table, mid = setup(tmp_path, size='Large', wall='side_shelf')
    move(combat, table, mid)
    candidate = strike(combat, mid).candidate_id
    pay_prompt = act(table, mid, candidate)
    assert pay_prompt['status'] == 'REACTION_REQUIRED'
    pay = pay_prompt['reaction']
    assert pay['context']['reaction_source_id'] == PAY
    pay_answer = {**pay['context'], 'selection': 'USE', 'option_ids': ['use']}
    destination_prompt = act(table, mid, candidate, [pay_answer])
    assert destination_prompt['status'] == 'REACTION_REQUIRED'
    destination = destination_prompt['reaction']
    assert destination['context']['reaction_source_id'] == DEST
    destination_ids = {option['id'] for option in destination['choice']['options']}
    assert 'cell:9,6,3' in destination_ids, sorted(destination_ids)
    chosen = {**destination['context'], 'selection': 'USE', 'option_ids': ['cell:9,6,3']}
    result = act(table, mid, candidate, [pay_answer, chosen])
    assert result['status'] == 'COMMITTED', result
    engine = reload(tmp_path, mid)
    event = next(e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.source_definition_id == KICK)
    assert [(cell['x'], cell['y'], cell.get('z', 0)) for cell in event.payload['path']] == [
        (6, 6, 0), (7, 6, 1)]
    target = engine.state.actors[FOE]
    assert (target.position.x, target.position.y, target.position.z) == (7,6,0)
    assert denied(engine)


def bind_primary(combat, label, target):
    """Constrain only the scenario primary; real controllers own all riders.

    No model transport or live endpoint is used. The table service still probes
    and resumes manual participants, including during an automatic actor's turn.
    """
    real = combat.controller
    class Primary:
        def choose_primary_action(self, context):
            rows = tuple(c for c in context.legal_candidates if c.display_name.startswith(label)
                         and c.target_ids == (target,))
            assert rows, label
            return real.choose_primary_action(context.model_copy(update={'legal_candidates': rows[:1]}))
        def __getattr__(self, name):
            return getattr(real, name)
    combat.controller = Primary()


def test_automatic_owner_resolves_paid_save_and_destination_without_a_player_prompt(tmp_path):
    combat, table, mid = setup(tmp_path)
    move(combat, table, mid)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    bind_primary(combat, 'Unarmed Strike', FOE)
    result = table.auto_step(mid, 0, [])
    assert result['status'] == 'COMMITTED', result
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[STAMINA] == 99
    assert denied(engine)


def test_manual_owner_chooses_accepted_travel_and_kick_during_automatic_foe_turn(tmp_path):
    combat, table, mid = setup(tmp_path, counter=True)
    turn(table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    original = combat.controller
    bind_primary(combat, 'Draw Wren closer', OWNER)
    consent = settle(table, mid, '', auto=True, choices={CONSENT: ['accept']})
    assert any(p['context']['reaction_source_id'] == CONSENT and p['context']['reactor_id'] == OWNER for p in consent)
    engine = reload(tmp_path, mid)
    assert engine.state.current_actor_id == FOE and engine.state.actors[OWNER].position.x == 5
    combat.controller = original
    bind_primary(combat, 'Unarmed Strike', OWNER)
    prompts = settle(table, mid, '', auto=True, choices={
        'reaction:typed.TAL_IRON_FIST_COUNTER_PALM': 'first', PAY: ['use'], DEST: ['cell:6,9']})
    assert any(p['context']['reaction_source_id'] == PAY and p['context']['reactor_id'] == OWNER for p in prompts)
    assert any(p['context']['reaction_source_id'] == DEST and p['context']['reactor_id'] == OWNER for p in prompts)
    engine = reload(tmp_path, mid)
    assert engine.state.current_actor_id == FOE
    assert engine.state.actors[OWNER].resources[STAMINA] == 99
    assert engine.state.actors[FOE].position.y == 9 and denied(engine)
