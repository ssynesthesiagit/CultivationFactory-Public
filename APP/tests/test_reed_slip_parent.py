"""Reed Slip whole printed parent through accepted, persisted table movement."""
import pytest

from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, reload, settle
from tests.table_action_support import act

POOL = 'resource:foundation.reed_flex'
SOURCE = 'foundation.weak_reed_tendons_v0_2B.reed_slip'
DESTINATION = 'choice:reed_slip.destination'
EXEMPTION = 'choice:reed_slip.exemption'
KIT = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.jian', 'name': 'Jian', 'quantity': 1}]}}


def setup(tmp_path, *, held=1, stage='Awakened', ask=True, prepare=False, foe_miss=False, far=False, status=None, exclusions=(), hostile=True):
    doc = sheet([], kit=KIT)
    doc['foundation'] = {'foundation_id': 'weak_reed_tendons_v0_2B', 'stage': stage,
        'resource': {'name': 'Reed Flex', 'resource_id': 'tianxia.resource.foundation.weak_reed_tendons_v0_2B',
                     'maximum': 1, 'current': held}}
    if status is not None:
        doc['foundation']['status'] = status
    if exclusions:
        doc['foundation']['suppressed_or_excluded_benefits'] = list(exclusions)
    if foe_miss:
        doc['ability_scores_and_statistics']['armor_class']['base_value'] = 100
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': ask})
    def transform(bundles):
        if foe_miss:
            from combat.canonical import canonical_sha256
            for bundle in bundles[1:]:
                for action in bundle['action_catalog']:
                    if action.get('parameters', {}).get('typed', {}).get('weapon'):
                        action['attack_bonus'] = -100
                        action['parameters']['typed']['attack_bonus'] = -100
                bundle.pop('bundle_sha256', None)
                bundle['bundle_sha256'] = canonical_sha256(bundle)
        if prepare:
            from tests.cw2_service_support import add_action
            for label, condition in [('Lie down', 'prone'), ('Bind self', 'restrained')]:
                add_action(bundles[0], label, [{'type': 'condition', 'condition': condition, 'applies_to': 'self'}], target='SELF')
    return fixture(tmp_path, [], owner_bundle=bundle, ask=ask, seed='REED-SLIP-PARENT',
        foe_kit=KIT, ally_kit=KIT, bundle_transform=transform,
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 8 if far else 5, 'y': 6},
                   ALLY: {'x': 8 if far else 4, 'y': 7}},
        team_overrides={ALLY: 'team:opponents'} if hostile else {ALLY: 'team:factory', FOE: 'team:factory'})


def move_id(combat, mid, x=4, y=6):
    return next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
                if c.kind.value == 'MOVE' and c.destination.x == x and c.destination.y == y
                and c.destination.z == 0 and c.metadata.get('movement_mode', 'walk') == 'walk')


def drive(table, mid, cid, *, destination='step:3,5', exemption=FOE, decline=None):
    answers, prompts = [], []
    for _ in range(20):
        result = act(table, mid, cid, answers)
        if result['status'] == 'COMMITTED':
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']; prompts.append(prompt)
        rid = prompt['context']['reaction_source_id']
        selected = destination if rid == DESTINATION else exemption if rid == EXEMPTION else None
        if rid == decline:
            selected = None
        # Other creatures' native opportunity attacks remain active.
        answer = {**prompt['context'], 'selection': 'USE' if selected or 'opportunity' in rid else 'DECLINE'}
        if selected:
            answer['option_ids'] = [selected]
        answers.append(answer)
    raise AssertionError('choice loop')


def receipts(engine):
    return [e for e in engine.events if e.source_definition_id == SOURCE]


def test_paid_slip_selective_oa_commit_cold_reload_replay(tmp_path):
    combat, table, mid = setup(tmp_path)
    engine = combat._load_session(mid).engine
    assert not [r for r in engine.typed_reaction_rows[OWNER] if r.get('feature_id') == SOURCE]
    assert [r for r in engine.typed_passive_rows[OWNER] if r.get('block') == 'reed_slip']
    before = engine.state.actors[OWNER].movement_remaining_ft
    prompts = drive(table, mid, move_id(combat, mid))
    assert {DESTINATION, EXEMPTION} <= {p['context']['reaction_source_id'] for p in prompts}
    destinations = next(p['choice']['options'] for p in prompts
                        if p['context']['reaction_source_id'] == DESTINATION)
    assert not {'step:4,7', 'step:5,6', 'step:2,6'} & {option['id'] for option in destinations}
    engine = reload(tmp_path, mid)
    assert combat._load_session(mid).verify()['status'] == 'PASS'
    actor = engine.state.actors[OWNER]
    assert (actor.position.x, actor.position.y) == (3, 5)
    assert actor.resources[POOL] == 0
    assert actor.movement_remaining_ft == before - 5
    assert actor.action_available and actor.bonus_action_available and actor.reaction_available
    assert engine.state.actors[FOE].reaction_available
    assert not engine.state.actors[ALLY].reaction_available
    paid = [e for e in receipts(engine) if e.event_type == 'RESOURCE_SPENT']
    assert len(paid) == 1
    receipt = next(e for e in receipts(engine) if e.event_type == 'PASSIVE_TRIGGERED')
    assert receipt.payload['paid'] == 1 and receipt.payload['allowance_ft'] == 5
    assert receipt.payload['payment_event_sequence'] == paid[0].sequence
    assert receipt.payload['resource_id'] == POOL
    assert receipt.payload['exempt_actor_id'] == FOE
    assert not any('ignore_oa' in key for key in actor.turn_flags)
    # The scoped exception is gone: ordinary movement away from the chosen foe
    # on a later accepted path can provoke it again.
    drive(table, mid, move_id(combat, mid, 4, 5))
    drive(table, mid, move_id(combat, mid, 3, 4))
    engine = reload(tmp_path, mid)
    assert not engine.state.actors[FOE].reaction_available


@pytest.mark.parametrize('decline', [DESTINATION, EXEMPTION])
def test_repeated_preview_cancel_never_spends_or_moves(tmp_path, decline):
    combat, table, mid = setup(tmp_path)
    cid = move_id(combat, mid)
    engine = combat._load_session(mid).engine
    original = engine.state.model_dump(mode='json')
    for _ in range(2):
        result = act(table, mid, cid, [])
        assert result['status'] == 'REACTION_REQUIRED'
        assert combat._load_session(mid).engine.state.model_dump(mode='json') == original
    drive(table, mid, cid, decline=decline)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == 1
    assert (engine.state.actors[OWNER].position.x, engine.state.actors[OWNER].position.y) == (4, 6)
    assert not receipts(engine)


@pytest.mark.parametrize('held,stage', [(0, 'Awakened'), (1, 'Dormant')])
def test_absent_flex_or_unowned_stage_is_inert(tmp_path, held, stage):
    combat, table, mid = setup(tmp_path, held=held, stage=stage)
    prompts = drive(table, mid, move_id(combat, mid))
    assert not any(p['context']['reaction_source_id'] in {DESTINATION, EXEMPTION} for p in prompts)
    assert not receipts(reload(tmp_path, mid))


def test_foundation_without_a_resource_block_is_inert(tmp_path):
    # A sheet that owns the Foundation but carries no resource block compiles the row with no pool id.
    # Reed Slip must then offer nothing and spend nothing (this is the sheet shape behaviour-diff scripts
    # build, so a "no difference" run there means the script never held the pool, not that the hook is dead).
    doc = sheet([])
    doc['foundation'] = {'foundation_id': 'weak_reed_tendons_v0_2B', 'stage': 'Awakened'}
    owner = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner, ask=True, seed='REED-SLIP-NO-POOL',
        foe_kit=KIT, ally_kit=KIT,
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 5, 'y': 6}, ALLY: {'x': 4, 'y': 7}})
    engine = combat._load_session(mid).engine
    row = next(r for r in engine.typed_passive_rows[OWNER] if r.get('block') == 'reed_slip')
    assert row['resource_id'] == ''
    prompts = drive(table, mid, move_id(combat, mid))
    assert not any(p['context']['reaction_source_id'] in {DESTINATION, EXEMPTION} for p in prompts)
    engine = reload(tmp_path, mid)
    assert not receipts(engine)
    assert engine.state.actors[OWNER].resources.get(POOL) is None


def test_native_prone_legality(tmp_path):
    from tests.worker2_support import candidate
    combat, table, mid = setup(tmp_path, prepare=True)
    settle(table, mid, candidate(combat, mid, 'Lie down').candidate_id)
    cid = move_id(combat, mid)
    # Crawling costs 10 feet per square. A 5-foot grant has no legal destination.
    prompts = drive(table, mid, cid)
    assert not any(p['context']['reaction_source_id'] == DESTINATION for p in prompts)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 1


def test_ai_choice_transport_automatically_spends(tmp_path):
    combat, table, mid = setup(tmp_path, ask=False, far=True)
    for actor_id in [OWNER, ALLY, FOE]:
        combat.set_controller_mode(mid, actor_id=actor_id, controller_mode='LOCAL_AUTO')
    # Use the actual local AI route chooser and choice adapter, with no player
    # answers, endpoint calls or test-only candidate-selection switches.
    for _ in range(6):
        result = table.auto_step(mid, 0, [])
        assert result['status'] == 'COMMITTED', result
        if any(e.event_type == 'PASSIVE_TRIGGERED' for e in receipts(combat._load_session(mid).engine)):
            break
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == 0
    assert any(e.event_type == 'PASSIVE_TRIGGERED' for e in receipts(engine))


def test_restrained_has_no_move_or_spend(tmp_path):
    from tests.worker2_support import candidate
    combat, table, mid = setup(tmp_path, prepare=True)
    settle(table, mid, candidate(combat, mid, 'Bind self').candidate_id)
    engine = reload(tmp_path, mid)
    assert engine._effective_speed(engine.state.actors[OWNER]) == 0
    assert not [c for c in engine.legal_candidates() if c.kind.value == 'MOVE']
    assert engine.state.actors[OWNER].resources[POOL] == 1
    assert not receipts(engine)


@pytest.mark.parametrize('status,enabled', [('Suppressed', False), ('Active', True), ('Unknown', True)])
def test_actual_foundation_source_status_controls_base_conversion(tmp_path, status, enabled):
    combat, table, mid = setup(tmp_path, status=status)
    prompts = drive(table, mid, move_id(combat, mid))
    engine = reload(tmp_path, mid)
    source = next(b['foundation_source_status'] for b in engine.typed_bundle_documents
                  if b.get('actor_id') == OWNER)
    assert source['status'] == status
    assert source['provenance'] == 'owner_sheet.foundation.status'
    assert any(p['context']['reaction_source_id'] == DESTINATION for p in prompts) is enabled
    assert engine.state.actors[OWNER].resources[POOL] == (0 if enabled else 1)


@pytest.mark.parametrize('benefit,packets,enabled', [
    (SOURCE, ['packet:owner-source'], False),
    ('foundation.weak_reed_tendons_v0_2B.bend_without_breaking_guard', ['packet:owner-source'], True),
    (SOURCE, [], True),
])
def test_source_exclusion_is_specific_and_preserves_unknown(tmp_path, benefit, packets, enabled):
    exclusions = [{'benefit': benefit, 'source_packet_ids': packets, 'reason': 'Owner source exclusion.'}]
    combat, table, mid = setup(tmp_path, exclusions=exclusions)
    prompts = drive(table, mid, move_id(combat, mid))
    engine = reload(tmp_path, mid)
    source = next(b['foundation_source_status'] for b in engine.typed_bundle_documents
                  if b.get('actor_id') == OWNER)
    assert source['exclusions'] == exclusions
    assert any(p['context']['reaction_source_id'] == DESTINATION for p in prompts) is enabled
    assert engine.state.actors[OWNER].resources[POOL] == (0 if enabled else 1)


def test_whole_original_route_completes_before_optional_slip(tmp_path):
    combat, table, mid = setup(tmp_path)
    cid = move_id(combat, mid, 4, 4)
    drive(table, mid, cid, destination='step:3,3')
    engine = reload(tmp_path, mid)
    moves = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == OWNER]
    normal = next(e for e in moves if e.source_definition_id != SOURCE)
    assert normal.payload['destination'] == {'x': 4, 'y': 4}
    assert normal.payload['cost_ft'] == 10
    assert not normal.payload['interrupted']
    assert (engine.state.actors[OWNER].position.x, engine.state.actors[OWNER].position.y) == (3, 3)
    assert len([e for e in moves if e.source_definition_id == SOURCE]) == 1


def test_interrupted_willing_route_cannot_trigger_or_spend(tmp_path, monkeypatch):
    combat, table, mid = setup(tmp_path)
    from combat.gate2_engine import Gate2Engine
    original = Gate2Engine._resolve_movement_with_policy
    marked = False

    def mark_route_interrupted(engine, actor, candidate, intent, **kwargs):
        nonlocal marked
        original(engine, actor, candidate, intent, **kwargs)
        if actor.entity_id == OWNER:
            marked = True
            receipt = next(e for e in reversed(engine.events)
                           if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == OWNER
                           and e.source_definition_id != SOURCE)
            # Model the partial-route receipt produced when a movement-step
            # reaction interrupts a multi-square willing path.
            assert len(receipt.payload['path']) > 1
            receipt.payload['interrupted'] = True

    monkeypatch.setattr(Gate2Engine, '_resolve_movement_with_policy', mark_route_interrupted)
    prompts = drive(table, mid, move_id(combat, mid, 4, 4))
    engine = reload(tmp_path, mid)
    normal = next(e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED'
                  and e.actor_id == OWNER and e.source_definition_id != SOURCE)
    assert marked and normal.payload['interrupted']
    assert len(normal.payload['path']) > 1
    assert not any(p['context']['reaction_source_id'] in {DESTINATION, EXEMPTION} for p in prompts)
    assert engine.state.actors[OWNER].resources[POOL] == 1
    assert not receipts(engine)


def test_forced_move_cannot_trigger_or_spend(tmp_path):
    from tests.worker2_support import candidate, turn
    from tests.cw2_service_support import add_action
    doc = sheet([], kit=KIT)
    doc['foundation'] = {'foundation_id': 'weak_reed_tendons_v0_2B', 'stage': 'Awakened',
        'resource': {'name': 'Reed Flex', 'resource_id': 'tianxia.resource.foundation.weak_reed_tendons_v0_2B',
                     'maximum': 1, 'current': 1}}
    owner = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    def transform(bundles):
        add_action(bundles[2], 'Push owner', [{'type': 'forced_movement', 'distance_ft': 5,
            'direction': 'away', 'applies_to': 'target'}])
    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner, bundle_transform=transform,
        foe_position={'x': 5, 'y': 6}, ally_position={'x': 8, 'y': 7}, seed='REED-FORCED')
    turn(table, mid, FOE)
    before = combat._load_session(mid).engine.state.actors[OWNER].position
    prompts = settle(table, mid, candidate(combat, mid, 'Push owner', target=OWNER).candidate_id)
    assert not any(p['context']['reaction_source_id'] in {DESTINATION, EXEMPTION} for p in prompts)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].position != before
    assert engine.state.actors[OWNER].resources[POOL] == 1
    assert not receipts(engine)


def test_flex_generated_by_this_moves_missed_oa_is_not_preexisting(tmp_path):
    combat, table, mid = setup(tmp_path, held=0, foe_miss=True)
    drive(table, mid, move_id(combat, mid, 1, 6))
    drive(table, mid, move_id(combat, mid, 4, 6))
    prompts = drive(table, mid, move_id(combat, mid, 3, 5))
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'RESOURCE_GAINED' and e.payload.get('resource_id') == POOL
               for e in engine.events)
    assert engine.state.actors[OWNER].resources[POOL] == 1
    assert not any(p['context']['reaction_source_id'] in {DESTINATION, EXEMPTION} for p in prompts)
    assert not receipts(engine)


def test_exemption_menu_never_offers_the_mover(tmp_path):
    # A creature cannot make an opportunity attack against itself, so the mover is never a choice.
    combat, table, mid = setup(tmp_path)
    prompts = drive(table, mid, move_id(combat, mid))
    exemption = next(p for p in prompts if p['context']['reaction_source_id'] == EXEMPTION)
    offered = {option['id'] for option in exemption['choice']['options']}
    assert OWNER not in offered
    assert FOE in offered
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == 0


def test_automatic_seat_with_no_hostile_known_declines_exemption(tmp_path):
    # Only allies are known, so an automatic seat has no hostile to exempt: it must decline and spend nothing.
    combat, table, mid = setup(tmp_path, ask=False, far=True, hostile=False)
    for actor_id in [OWNER, ALLY, FOE]:
        combat.set_controller_mode(mid, actor_id=actor_id, controller_mode='LOCAL_AUTO')
    for _ in range(6):
        result = table.auto_step(mid, 0, [])
        assert result['status'] == 'COMMITTED', result
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == 1
    assert not any(e.event_type == 'PASSIVE_TRIGGERED' for e in receipts(engine))
