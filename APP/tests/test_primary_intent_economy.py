"""RIDERECON: free rider packets cannot become hand-play turn activations."""
from collections import defaultdict
from copy import deepcopy
import json

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionDefinition, CandidateKind
from combat.gate5_service import CombatService
from combat.primary_intents import allows_primary
from combat.tabletop_service import TabletopService
from tests.test_oareact_reaction_economy import ROOT, THREAD_ID, THREAD_SHEET, AN


def test_unmarked_none_rider_cannot_loop_through_hand_play(tmp_path):
    bundle = compile_character(THREAD_SHEET, actor_id=THREAD_ID)
    row = deepcopy(next(r for r in bundle['action_catalog'] if r['economy'] == 'ACTION'))
    row.update(source_definition_id='action:test.option.1', display_name='Test strike: Speed -10',
               economy='NONE', costs=[], target_kind='HOSTILE_ENTITY', range_ft=5)
    row['parameters'] = {'typed': {'effects': [{'type': 'speed', 'flat': -10,
        'applies_to': 'target'}], 'numbers': {}, 'duration': {'kind': 'instant'}, 'riders': []}}
    bundle['action_catalog'].append(row)
    bundle['actor_template']['action_ids'].append(row['source_definition_id'])
    bundle.pop('bundle_sha256')
    bundle['bundle_sha256'] = canonical_sha256(bundle)
    service = CombatService(ROOT, tmp_path)
    mid = service.persistence.create_match(match_seed='OAREACT', typed_bundles=(bundle,),
        roster_setup={'primary_actor_ids': [THREAD_ID, AN],
            'team_by_actor': {THREAD_ID: 'team:a', AN: 'team:b'},
            'starting_positions': {THREAD_ID: {'x': 5, 'y': 5}, AN: {'x': 5, 'y': 6}}}).match_id
    service.set_controller_mode(mid, actor_id=THREAD_ID, controller_mode='MANUAL')
    table = TabletopService(service, tmp_path)
    assert service._load_session(mid).engine.state.current_actor_id == THREAD_ID
    for _ in range(3):
        engine = service._load_session(mid).engine
        state = table.state(mid)
        riders = [c for c in engine.legal_candidates() if c.source_definition_id == row['source_definition_id']]
        if riders:  # Before the guard, hand play can repeatedly commit this same free effect.
            c = riders[0]
            assert table.act(mid, c.candidate_id, c.decision_id, c.state_version,
                             state['last_sequence'])['status'] == 'COMMITTED'
            after = service._load_session(mid).engine
            assert not any(c.source_definition_id == row['source_definition_id'] for c in after.legal_candidates()), (
                'rider remains offered after applying its effect without an attack or spending turn economy')
        assert not any(g['source_definition_id'] == row['source_definition_id'] for g in state['menu']['actions'])
    candidate = next(c for c in engine.legal_candidates() if c.kind == CandidateKind.END_TURN)
    assert table.act(mid, candidate.candidate_id, candidate.decision_id, candidate.state_version,
                     state['last_sequence'])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.current_actor_id != THREAD_ID
    assert loaded.verify()['status'] == 'PASS'
    assert not any(e.event_type == 'CONDITION_APPLIED' and e.source_definition_id == row['source_definition_id']
                   for e in loaded.engine.events)


@pytest.mark.parametrize('economy,parameters,allowed', [
    ('ACTION', {}, True), ('BONUS_ACTION', {}, True), ('REACTION', {'free_primary': True}, False),
    ('NONE', {}, False), ('NONE', {'free_primary': True}, True),
    ('NONE', {'setting_only': True}, True),
])
def test_general_primary_economy_contract(economy, parameters, allowed):
    action = ActionDefinition(source_definition_id='action:test', display_name='Test', owner_id='actor:test',
        economy=economy, resolution_kind='TYPED', target_kind='SELF', parameters=parameters)
    assert allows_primary(action) is allowed


def test_compiled_none_row_kind_census(tmp_path):
    """Compile every authority family; keep a compact, reproducible row-kind receipt."""
    from tests.h1_support import mechanics, sheet
    groups = defaultdict(list)
    for key, row in mechanics().items():
        groups[row.get('sphere_id') or row.get('path_id') or row.get('foundation_id')
               or row.get('tradition_id') or row.get('kind')].append(key)
    inventory = defaultdict(lambda: {'count': 0, 'routes': set(), 'examples': []})
    denied = []
    for family, owned in sorted(groups.items(), key=lambda item: str(item[0])):
        bundle = compile_character(sheet(owned, cl=20), actor_id=THREAD_ID)
        for row in bundle['action_catalog']:
            if row['economy'] != 'NONE':
                continue
            action = ActionDefinition.model_validate(row)
            params = action.parameters
            kinds = sorted({e.get('type', 'empty') for e in (params.get('typed') or {}).get('effects', [])
                            if isinstance(e, dict)}) or ['empty']
            route = 'parent/sheet storage selector' if params.get('setting_only') else 'printed free activation'
            for kind in kinds:
                receipt = inventory[kind]
                receipt['count'] += 1
                receipt['routes'].add(route)
                if len(receipt['examples']) < 2:
                    receipt['examples'].append(action.display_name)
            if not allows_primary(action):
                denied.append((family, action.display_name, kinds, params))
    target = tmp_path / 'none_row_kinds.json'
    target.write_text(json.dumps({kind: {**row, 'routes': sorted(row['routes'])}
                                 for kind, row in sorted(inventory.items())}, indent=2) + '\n')
    assert not denied, [(family, name, kinds) for family, name, kinds, _ in denied]


@pytest.mark.parametrize('ai', [False, True])
def test_nullifying_rider_still_applies_only_when_parent_hits(tmp_path, ai):
    from tests.hunt36_support import LEFT, RIGHT, fight, reload, send, turn
    from tests.test_hunt36_nullifying_weapons import NULL, seed_for
    combat, table, mid = fight(tmp_path, [NULL], primary='Stamina', seed=seed_for('melee', False))
    turn(combat, table, mid)
    engine = reload(combat, mid)
    before = len(engine.events)
    stamina = engine.state.actors[LEFT].resources['resource:core.stamina']
    candidate = next(c for c in engine.legal_candidates() if c.display_name == 'Bi Shou (Dagger) attack'
                     and c.target_ids == (RIGHT,))
    send(combat, table, mid, candidate.candidate_id, ai=ai, pick=lambda o: 'Speed -10' in o['label'])
    engine = reload(combat, mid)
    events = engine.events[before:]
    assert any(e.event_type == 'ATTACK_ROLLED' and e.payload['provisional_hit'] for e in events)
    assert any(e.event_type == 'DAMAGE_ROLLED' and e.payload.get('damage_label') == 'Nullifying Strike' for e in events)
    assert engine.state.actors[LEFT].resources['resource:core.stamina'] == stamina - 2
    assert not engine.state.actors[LEFT].action_available
