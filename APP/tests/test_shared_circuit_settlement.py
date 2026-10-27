"""Shared Circuit must offer the protected ally one settled-protection choice."""
import json
import pytest
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import (
    OWNER, ALLY, FOE, fixture, sealed_native_attack, candidate, settle, turn, reload,
)

PREFIX = 'foundation.origin_spirit_body_v0_2B.'
GUARD = PREFIX + 'returning_source_guard'
RIDER = PREFIX + 'refined_shared_circuit_memory'
CHOICE = 'choice:needle.shared_circuit_memory'
MEMORY = 'condition:typed.foundations3_shared_memory.'
OTHER = 'actor:factory.worker2-foe1'
FEED = PREFIX + 'feed_the_living_circuit'

# The compiler discovers these split rows by directory enumeration. Public CI
# follows literal input paths, so name the exact owned mechanics used below.
# A full local checkout otherwise masks their absence in an exported snapshot.
FIXTURE_INPUTS = (
    'combat/rules/feature_blocks.d/foundations3.json',
)


def test_native_settlement_inputs_and_compiled_ownership():
    from tests.h1_support import ROOT
    for relative in FIXTURE_INPUTS:
        assert (ROOT / relative).is_file(), f'Shared Circuit fixture requires {relative}'
    owner = compile_character(sheet([GUARD, RIDER], foundation={
        'foundation_id': 'origin_spirit_body_v0_2B', 'stage': 'Refined',
        'resource': {'name': 'Spirit-Source Dew', 'resource_id': 'tianxia.resource.test',
                     'maximum': 2, 'current': 1}}), actor_id=OWNER)
    assert any(row.get('feature_id') == RIDER and row.get('block') == 'foundations3_shared_memory'
               for row in owner['typed_passives'])
    assert any(row.get('feature_id') == FEED and row.get('kind') == 'foundations3_feed'
               for row in owner['typed_passives'])


@pytest.fixture(autouse=True)
def fake_menu_embeddings(monkeypatch):
    from combat.menu_rank import default_client
    client = default_client()
    def transport(url, body, timeout):
        inputs = json.loads(body)['input']
        return json.dumps({'data': [{'index': i, 'embedding': [1.0] + [0.0] * 767}
                                    for i in range(len(inputs))]}).encode()
    monkeypatch.setattr(client, 'transport', transport)
    monkeypatch.setattr(client, 'background', False)
    monkeypatch.setattr(client, 'before_request', None)
    monkeypatch.setattr(client, 'request_result', None)


def add_action(bundle, name, effects, *, target_kind='HOSTILE_ENTITY', economy='ACTION'):
    """Seal synthetic pressure directly, without importing historical test suites."""
    source = 'action:test.foundations3.' + bundle['actor_id'].split('.')[-1] + '.' + name.lower().replace(' ', '_')
    row = {'source_definition_id': source, 'display_name': name, 'owner_id': bundle['actor_id'],
           'economy': economy, 'resolution_kind': 'TYPED', 'target_kind': target_kind, 'range_ft': 60,
           'parameters': {'typed': {'source': source, 'range_ft': 60,
               'numbers': {'pb': 4, 'key_mod': 2, 'save_dc': 30, 'attack_bonus': 8},
               'effects': effects, 'duration': {'kind': 'instant'}, 'riders': []}, 'expected_damage': 1}}
    if economy == 'NONE':
        row['parameters']['free_primary'] = True
    bundle['action_catalog'].append(row)
    bundle['actor_template']['action_ids'].append(source)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)


def _setup(tmp_path, *, stage='Refined', held=1, modes=None, movement=False, concentration=False):
    owner = compile_character(sheet([GUARD, RIDER], name='Wren', foundation={
        'foundation_id': 'origin_spirit_body_v0_2B', 'stage': stage,
        'resource': {'name': 'Spirit-Source Dew', 'resource_id': 'tianxia.resource.test',
                     'maximum': 2, 'current': held}}), actor_id=OWNER, reaction_plan={'ask': True})
    def actions(bundles):
        for i, b in enumerate(bundles):
            # Fixture scheduling only: source then other hostile act before
            # the owner's next start, so source/expiry controls are independent.
            b['actor_template']['initiative_bonus'] = 80 - 40 * i
            b.pop('bundle_sha256', None)
            b['bundle_sha256'] = canonical_sha256(b)
        sealed_native_attack(bundles[2], 'Hostile pressure', modifier=20, attack_bonus=100)
        if concentration:
            add_action(bundles[1], 'Maintain technique',
                [{'type': 'temp_hp', 'flat': 1, 'applies_to': 'self'}],
                target_kind='SELF', economy='ACTION')
            bundles[1]['action_catalog'][-1]['parameters']['typed']['duration'] = {
                'kind': 'one_minute', 'concentration': True}
            # Leave the ally standing, but set a native damage-based DC that
            # even the paid positive Feed bonus cannot rescue.
            sealed_native_attack(bundles[2], 'Concentration pressure', count=1,
                                 sides=2, modifier=54, attack_bonus=100)
        for b in bundles[2:]:
            add_action(b, 'WIS pressure', [{'type': 'save', 'ability': 'WIS', 'dc': 30,
                'save_categories': ['damage:psychic'],
                'on_fail': [{'type': 'damage', 'flat': 1, 'damage_types': ['psychic'], 'applies_to': 'target'}],
                'on_success': []}], economy='NONE')
            add_action(b, 'Feed eligible fear', [{'type': 'save', 'ability': 'WIS', 'dc': 30,
                'save_categories': ['frightened'],
                'on_fail': [{'type': 'condition', 'condition': 'frightened', 'applies_to': 'target',
                             'duration': {'kind': 'until_end_of_next_turn'}}], 'on_success': []}], economy='NONE')
            for kind, title in (('cultivation', 'Cultivation pressure'), ('ability', 'Ordinary check')):
                add_action(b, title, [{'type': 'contest_against',
                    'actor_check': {'kind': 'ability', 'ability': 'WIS'},
                    'target_check': {'kind': kind, 'ability': 'WIS'},
                    'on_success': [{'type': 'damage', 'flat': 1, 'damage_types': ['psychic'], 'applies_to': 'target'}],
                    'on_fail': []}], economy='NONE')
            # These are deliberately free fixture pressure actions, not
            # storage-only selectors or fragments of a parent activation.
            for action in b['action_catalog']:
                if action['source_definition_id'].startswith('action:test.foundations3.') and action['economy'] == 'NONE':
                    action['parameters']['free_primary'] = True
            b.pop('bundle_sha256', None)
            b['bundle_sha256'] = canonical_sha256(b)
    positions = ({OWNER: {'x': 2, 'y': 6}, ALLY: {'x': 4, 'y': 6},
                  FOE: {'x': 4, 'y': 5}, OTHER: {'x': 3, 'y': 5}} if movement else None)
    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner, bundle_transform=actions,
        named=True, seed='SHARED-CIRCUIT-CONTROLS', extra_foes=1, positions=positions,
        ally_score=2 if concentration else 14)
    if concentration:
        turn(table, mid, ALLY)
        settle(table, mid, candidate(combat, mid, 'Maintain technique').candidate_id, choices={})
    turn(table, mid, FOE)
    for actor_id, mode in (modes or {}).items():
        if mode != 'MANUAL':
            combat.set_controller_mode(mid, actor_id=actor_id, controller_mode=mode)
    return combat, table, mid


def _protect(combat, table, mid, benefit='advantage', *, target=ALLY, extra=None, auto=False):
    cid = candidate(combat, mid, 'Hostile pressure', target=target).candidate_id
    if auto:
        from combat.gate4_adapters import ManualControllerAdapter
        policy = combat.controller
        combat.controller = ManualControllerAdapter(lambda context: (cid, ()),
            reaction_chooser=lambda context: policy.choose_reaction(context).decision)
    return settle(table, mid, cid, choices={'reaction:typed.' + GUARD: 'first',
        CHOICE: benefit, **(extra or {})}, auto=auto)


def _memory(engine):
    return [c for c in engine.state.actors[ALLY].conditions.values() if c.condition_id.startswith(MEMORY)]


def _use(combat, table, mid, name):
    settle(table, mid, candidate(combat, mid, name, target=ALLY).candidate_id, choices={})


def test_real_guard_reduction_offers_one_choice_to_protected_ally(tmp_path):
    owner = compile_character(sheet([GUARD, RIDER], name='Wren', foundation={
        'foundation_id': 'origin_spirit_body_v0_2B', 'stage': 'Refined',
        'resource': {'name': 'Spirit-Source Dew', 'resource_id': 'tianxia.resource.test',
                     'maximum': 2, 'current': 1}}),
        actor_id=OWNER, reaction_plan={'ask': True})

    def attack(bundles):
        sealed_native_attack(bundles[2], 'Hostile pressure', count=1, sides=6,
                             modifier=20, attack_bonus=100)

    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner,
        bundle_transform=attack, named=True, seed='SHARED-CIRCUIT-FIRST')
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Hostile pressure', target=ALLY).candidate_id,
                     choices={'reaction:typed.' + GUARD: 'first', CHOICE: 'advantage'})
    engine = reload(tmp_path, mid)
    receipts = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == GUARD and e.payload.get('protects') == ALLY]
    assert receipts and receipts[-1].payload['reduction'] > 0, 'Native Guard did not actually protect the ally'
    choices = [p for p in prompts if p['context']['reaction_source_id'] == CHOICE]
    assert len(choices) == 1, 'Successful Guard must offer exactly one Shared Circuit choice'
    choice = choices[0]
    assert choice['context']['reactor_id'] == ALLY
    assert {o['id'] for o in choice['choice']['options']} == {'move', 'advantage'}


def test_same_source_save_once_and_owner_next_start_expiry(tmp_path):
    combat, table, mid = _setup(tmp_path)
    _protect(combat, table, mid)
    engine = reload(tmp_path, mid)
    held = _memory(engine)
    assert len(held) == 1 and held[0].source_actor_id == OWNER
    assert held[0].expires_on == 'START_OF_SOURCE_NEXT_TURN'
    assert all(type(v) in (str, int) for v in held[0].data.values())
    # Different source does not spend the grant.
    turn(table, mid, OTHER); _use(combat, table, mid, 'WIS pressure')
    engine = reload(tmp_path, mid)
    assert [e.payload['mode'] for e in engine.events if e.event_type == 'SAVE_ROLLED'][-1] == 'NORMAL'
    assert _memory(engine)
    # Native next-start clock removes unused grants after a cold reload.
    turn(table, mid, OWNER)
    assert not _memory(reload(tmp_path, mid))

    # A separate fight tests consumption, without the expiry clock intervening.
    second = tmp_path / 'second'; second.mkdir()
    combat, table, mid = _setup(second)
    _protect(combat, table, mid)
    _use(combat, table, mid, 'WIS pressure')
    engine = reload(second, mid)
    assert [e.payload['mode'] for e in engine.events if e.event_type == 'SAVE_ROLLED'][-1] == 'ADVANTAGE'
    assert not _memory(engine)
    _use(combat, table, mid, 'WIS pressure')
    assert [e.payload['mode'] for e in reload(second, mid).events if e.event_type == 'SAVE_ROLLED'][-1] == 'NORMAL'


@pytest.mark.parametrize('benefit', ['advantage', 'move'])
def test_native_opportunity_guard_paid_choice_survives_commit_reload(tmp_path, monkeypatch, benefit):
    from combat.gate2_engine import SYSTEM_OPPORTUNITY
    from combat.gate2_runtime_content import BASIC_MELEE
    from combat.gate2_runtime_content import AN
    from combat.gate2_runtime_models import DiceSpec
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT
    owner = compile_character(sheet([GUARD, RIDER], name='Wren', foundation={
        'foundation_id': 'origin_spirit_body_v0_2B', 'stage': 'Refined',
        'resource': {'name': 'Spirit-Source Dew', 'resource_id': 'tianxia.resource.test',
                     'maximum': 2, 'current': 1}}), actor_id=OWNER, reaction_plan={'ask': True})
    # Use the stock native attack-spec path, not a catalog-backed Factory OA.
    monkeypatch.setitem(BASIC_MELEE, AN, {**BASIC_MELEE[AN], 'attack_bonus': 100,
        'damage': DiceSpec(count=1, sides=6, modifier=20),
        'damage_type': 'BLUDGEONING', 'reach_ft': 5})
    ally = compile_character(sheet([], name='Tobin'), actor_id=ALLY, reaction_plan={'ask': True})
    combat = CombatService(ROOT, tmp_path)
    mid = combat.persistence.create_match(match_seed='SHARED-CIRCUIT-NATIVE-OA',
        typed_bundles=(owner, ally), roster_setup={
            'primary_actor_ids': [OWNER, ALLY, AN],
            'team_by_actor': {OWNER: 'a', ALLY: 'a', AN: 'b'},
            'starting_positions': {OWNER: {'x': 2, 'y': 6},
                ALLY: {'x': 4, 'y': 6}, AN: {'x': 4, 'y': 5}}}).match_id
    for actor_id in (OWNER, ALLY, AN):
        combat.set_controller_mode(mid, actor_id=actor_id, controller_mode='MANUAL')
    table = TabletopService(combat, tmp_path)
    turn(table, mid, OWNER)
    turn(table, mid, ALLY)
    before = reload(tmp_path, mid)
    assert AN not in before.typed_actor_ids
    assert SYSTEM_OPPORTUNITY not in before.action_catalog
    dew = next(r for r in before.state.actors[OWNER].resources if 'spirit_source_dew' in r)
    move = next(c for c in before.legal_candidates() if c.destination
                and (c.destination.x, c.destination.y) == (4, 7))
    prompts = settle(table, mid, move.candidate_id, choices={
        'reaction:typed.opportunity_attack': 'first',
        SYSTEM_OPPORTUNITY: 'first', 'reaction:typed.' + GUARD: 'first',
        CHOICE: benefit, 'choice:needle.shared_circuit_destination': 'step:5,7'})
    engine = reload(tmp_path, mid)
    guard = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
             and e.source_definition_id == GUARD and e.payload.get('protects') == ALLY]
    assert guard and guard[-1].payload['pending_before'] > guard[-1].payload['pending_after']
    paid = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
            and e.source_definition_id == GUARD and e.actor_id == OWNER
            and e.payload.get('resource_id') == dew]
    assert len(paid) == 1 and paid[0].payload['amount'] == 1
    assert paid[0].payload['remaining'] == before.state.actors[OWNER].resources[dew] - 1
    assert paid[0].sequence < guard[-1].sequence
    choices = [p for p in prompts if p['context']['reaction_source_id'] == CHOICE]
    assert len(choices) == 1 and choices[0]['context']['reactor_id'] == ALLY
    assert {o['id'] for o in choices[0]['choice']['options']} == {'move', 'advantage'}
    assert choices[0]['action'] == 'Opportunity Attack'
    assert 'Opportunity Attack' in choices[0]['moment']
    if benefit == 'advantage':
        held = _memory(engine)
        assert len(held) == 1 and held[0].data['pressure_source_id'] == AN
        assert all(type(v) in (str, int) for v in held[0].data.values())
    else:
        assert not _memory(engine)
        granted = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED'
                   and e.actor_id == ALLY and e.payload.get('granted_cost_ft') == 5]
        assert granted and granted[-1].payload['destination']['x'] == 5
        assert granted[-1].payload['destination']['y'] == 7
        assert any(e.event_type == 'PASSIVE_TRIGGERED' and e.source_definition_id == RIDER
                   and e.payload.get('benefit') == 'move' for e in engine.events)


def test_cultivation_check_source_and_kind_controls(tmp_path):
    combat, table, mid = _setup(tmp_path)
    _protect(combat, table, mid)
    _use(combat, table, mid, 'Ordinary check')
    engine = reload(tmp_path, mid)
    assert [e.payload['target']['mode'] for e in engine.events if e.event_type == 'CHECK_ROLLED'][-1] == 'NORMAL'
    assert _memory(engine)
    _use(combat, table, mid, 'Cultivation pressure')
    engine = reload(tmp_path, mid)
    assert [e.payload['target']['mode'] for e in engine.events if e.event_type == 'CHECK_ROLLED'][-1] == 'ADVANTAGE'
    assert not _memory(engine)
    _use(combat, table, mid, 'Cultivation pressure')
    assert [e.payload['target']['mode'] for e in reload(tmp_path, mid).events if e.event_type == 'CHECK_ROLLED'][-1] == 'NORMAL'


def test_movement_moves_ally_only_and_preserves_other_hostile_oa(tmp_path):
    from combat.gate2_engine import SYSTEM_OPPORTUNITY
    combat, table, mid = _setup(tmp_path, movement=True)
    before = reload(tmp_path, mid)
    owner_position = before.state.actors[OWNER].position
    ordinary = before.state.actors[ALLY].movement_remaining_ft
    _protect(combat, table, mid, 'move', extra={
        'choice:needle.shared_circuit_destination': 'step:4,7',
        'reaction:typed.opportunity_attack': 'first'})
    engine = reload(tmp_path, mid)
    assert (engine.state.actors[ALLY].position.x, engine.state.actors[ALLY].position.y) == (4, 7)
    assert engine.state.actors[OWNER].position == owner_position
    assert engine.state.actors[ALLY].movement_remaining_ft == ordinary
    assert not _memory(engine)
    attackers = {e.actor_id for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                 and e.source_definition_id == SYSTEM_OPPORTUNITY}
    assert attackers == {OTHER}
    assert engine.state.actors[FOE].reaction_available
    assert not engine.state.actors[OTHER].reaction_available


@pytest.mark.parametrize('case', ['unowned', 'self', 'decline', 'empty'])
def test_ownership_target_and_no_spend_controls(tmp_path, case):
    combat, table, mid = _setup(tmp_path, stage='Awakened' if case == 'unowned' else 'Refined',
                                 held=0 if case == 'empty' else 1)
    prompts = _protect(combat, table, mid, target=OWNER if case == 'self' else ALLY,
                       extra={'reaction:typed.' + GUARD: None} if case == 'decline' else None)
    engine = reload(tmp_path, mid)
    assert not [p for p in prompts if p['context']['reaction_source_id'] == CHOICE]
    assert not _memory(engine)


def test_paid_feed_remaining_concentration_failure_offers_nothing(tmp_path):
    from combat.gate2_engine import SYSTEM_CONCENTRATION
    combat, table, mid = _setup(tmp_path, concentration=True)
    before = reload(tmp_path, mid)
    assert before.state.actors[ALLY].concentration is not None
    prompts = settle(table, mid,
        candidate(combat, mid, 'Concentration pressure', target=ALLY).candidate_id,
        choices={'reaction:typed.' + GUARD: None,
                 'reaction:typed.' + FEED: 'first',
                 'choice:needle.foundations3_feed_accept': 'accept'})
    engine = reload(tmp_path, mid)
    paid = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
            and e.source_definition_id == FEED and e.actor_id == OWNER]
    assert len(paid) == 1 and paid[0].payload['amount'] == 1
    assert not engine.state.actors[OWNER].reaction_available
    rewrite = next(e for e in engine.events if e.event_type == 'D20_REWRITTEN'
                   and e.source_definition_id == FEED)
    save = next(e for e in engine.events if e.event_type == 'SAVE_ROLLED'
                and e.actor_id == ALLY and e.source_definition_id == SYSTEM_CONCENTRATION)
    assert rewrite.payload['bonus'] > 0
    assert save.payload['total'] == rewrite.payload['original']['total'] + rewrite.payload['bonus']
    assert save.payload['total'] < save.payload['dc']
    assert save.payload['success'] is False
    assert engine.state.actors[ALLY].concentration is None
    assert engine.state.actors[ALLY].temporary_hp == 0
    assert not any(e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id == FEED
                   for e in engine.events)
    assert not [p for p in prompts if p['context']['reaction_source_id'] == CHOICE]
    assert not _memory(engine)


def test_feed_fear_save_is_unsupported_and_spends_nothing(tmp_path):
    combat, table, mid = _setup(tmp_path)
    prompts = settle(table, mid, candidate(combat, mid, 'Feed eligible fear', target=ALLY).candidate_id,
                     choices={'reaction:typed.' + FEED: 'first'})
    engine = reload(tmp_path, mid)
    assert not any(e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == FEED
                   for e in engine.events)
    assert engine.state.actors[OWNER].reaction_available
    assert engine.state.actors[ALLY].temporary_hp == 0
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY and e.payload['total'] < 30
               for e in engine.events)
    assert any(c.condition_id == 'condition:typed.frightened'
               for c in engine.state.actors[ALLY].conditions.values())
    assert not [p for p in prompts if p['context']['reaction_source_id'] in (
        'reaction:typed.' + FEED, 'choice:needle.foundations3_feed_accept', CHOICE)]
    assert not _memory(engine)


@pytest.mark.parametrize('foe_mode,ally_mode', [('LOCAL_AUTO', 'MANUAL'), ('MANUAL', 'LOCAL_AUTO')])
def test_actual_recipient_decides_on_manual_and_ai_turns(tmp_path, foe_mode, ally_mode):
    modes = {OWNER: 'MANUAL', ALLY: ally_mode, FOE: foe_mode, OTHER: 'MANUAL'}
    combat, table, mid = _setup(tmp_path, modes=modes)
    prompts = _protect(combat, table, mid, auto=foe_mode == 'LOCAL_AUTO')
    engine = reload(tmp_path, mid)
    assert _memory(engine)
    choices = [p for p in prompts if p['context']['reaction_source_id'] == CHOICE]
    if ally_mode == 'MANUAL':
        assert len(choices) == 1 and choices[0]['context']['reactor_id'] == ALLY
        assert {o['id'] for o in choices[0]['choice']['options']} == {'move', 'advantage'}
    else:
        assert not choices


def test_repeated_native_menu_preview_is_pure(tmp_path):
    combat, table, mid = _setup(tmp_path)
    engine = reload(tmp_path, mid)
    before = canonical_sha256(engine.state.model_dump(mode='json'))
    events = len(engine.events)
    for _ in range(3):
        table.state(mid)
        candidate(combat, mid, 'Hostile pressure', target=ALLY)
    engine = reload(tmp_path, mid)
    assert canonical_sha256(engine.state.model_dump(mode='json')) == before
    assert len(engine.events) == events
    assert not _memory(engine)
