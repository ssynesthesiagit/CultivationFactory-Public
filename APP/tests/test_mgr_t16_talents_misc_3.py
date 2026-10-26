"""Assigned T16 clauses through committed table actions and cold service reload."""
import pytest

from combat.canonical import canonical_sha256
from combat.gate2_runtime_models import ActionIntent
from combat.ext.smoke_tracking import TRACK
from combat.typed_executor import bears_mark
from tests.h1_support import ROOT
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn

SOOT = 'TAL_SMOKE_SOOT_SCENT_TRAIL'
LIED = 'TAL_SMOKE_THE_SMOKE_KNOWS_WHO_LIED'
CHAOS = 'TAL_DRUNKEN_STYLE_CHAOS_STEP_AWAKENING'
BASE = ['SMOKE_BASE_SMOKE_TRACE', 'SMOKE_BASE_SMOKE_RESPONSES']


def test_chaos_step_compiler_resource_is_shipped():
    """The public test snapshot must retain this dynamically loaded rule file."""
    import json
    resource = ROOT / 'combat/rules/feature_blocks.d/auto25_second_pass.json'
    spec = json.loads(resource.read_text())['features'][CHAOS]
    assert spec['block'] == 'drunken_step_benefit'


def setup_actions(bundles):
    for bundle in bundles:
        aid = bundle['actor_id']
        mark = 'Off-Rhythm' if aid == FOE else 'Smoke Trace'
        effects = [{'type': 'mark', 'mark': mark, 'applies_to': 'target',
                    'duration': {'kind': 'rounds', 'amount': 10}}]
        bundle['action_catalog'].append({'source_definition_id': 'test:mark:' + aid,
            'owner_id': aid, 'display_name': 'Test mark', 'economy': 'NONE',
            'resolution_kind': 'TYPED', 'target_kind': 'HOSTILE_ENTITY', 'range_ft': 120,
            'parameters': {'free_primary': True, 'typed': {'source': 'test:mark:' + aid,
                'effects': effects, 'numbers': {'cl': 15, 'pb': 5, 'save_dc': 16}}}})
        bundle['actor_template']['action_ids'].append('test:mark:' + aid)
        if aid == ALLY:
            source = 'test:missing_attack'
            bundle['action_catalog'].append({'source_definition_id': source, 'owner_id': aid,
                'display_name': 'Test miss', 'economy': 'NONE', 'resolution_kind': 'TYPED',
                'target_kind': 'HOSTILE_ENTITY', 'range_ft': 60,
                'parameters': {'free_primary': True, 'typed': {'source': source,
                    'numbers': {'cl': 15, 'pb': 5, 'attack_bonus': -100},
                    'effects': [{'type': 'attack', 'attack_kind': 'cultivation_ranged',
                                 'on_hit': []}]}}})
            bundle['actor_template']['action_ids'].append(source)
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)


@pytest.mark.parametrize('extended', [False, True])
def test_follow_soot_result_duration_survives_cold_reload(tmp_path, extended):
    combat, table, mid = fixture(tmp_path, BASE + ([SOOT] if extended else []),
                                bundle_transform=setup_actions, owner_dc=50)
    assert not any(c.display_name == 'Follow the Soot' for c in combat._load_session(mid).engine.legal_candidates())
    settle(table, mid, candidate(combat, mid, 'Test mark', target=FOE).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Follow the Soot', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    target = engine.state.actors[FOE]
    assert not bears_mark(target, OWNER, 'Smoke Trace')
    held = next(c for c in target.conditions.values() if c.condition_id == TRACK)
    assert held.source_actor_id == OWNER and held.data['extended'] == int(extended)
    assert held.data['save_dc'] == 50
    assert held.expires_on.startswith('START_OF_TURN_AT:') if extended else held.expires_on == 'START_OF_SOURCE_NEXT_TURN'
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    assert any(c.condition_id == TRACK for c in reload(tmp_path, mid).state.actors[FOE].conditions.values()) == extended


@pytest.mark.parametrize('dc,accept,escaped', [(50, True, False), (-50, True, True), (-50, False, False)])
@pytest.mark.parametrize('ai', [False, True])
def test_soot_scent_end_turn_escape_is_target_owned(tmp_path, dc, accept, escaped, ai):
    if ai and not accept:
        pytest.skip('Automatic creatures attempt the free escape')
    combat, table, mid = fixture(tmp_path, BASE + [SOOT], bundle_transform=setup_actions, owner_dc=dc, named=True)
    settle(table, mid, candidate(combat, mid, 'Test mark', target=FOE).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Follow the Soot', target=FOE).candidate_id)
    turn(table, mid, FOE)
    if ai:
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
        session = combat._load_session(mid)
        c = next(c for c in session.engine.legal_candidates() if c.kind.value == 'END_TURN')
        session.mechanical.execute_intent(ActionIntent(intent_id='soot-ai-end', actor_id=FOE,
            decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version))
        prompts = []
    else:
        prompts = settle(table, mid, table.state(mid)['menu']['end_turn'],
                         picks={'choice:needle.soot_scent_escape': 'stealth' if accept else None})
    engine = reload(tmp_path, mid)
    assert bool([c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == TRACK]) == (not escaped)
    checks = [e for e in engine.events if e.event_type == 'CHECK_ROLLED' and 'follow_soot' in e.source_definition_id]
    assert len(checks) == int(accept)
    assert all(e.actor_id == FOE for e in checks)
    if not ai:
        assert any('Soot-Scent Trail' in str(p) and 'Follow the Soot' in str(p) and 'Mara' in str(p) for p in prompts)
    else:
        assert not prompts


def test_lied_requires_own_smoke_trace_and_printed_range(tmp_path):
    combat, table, mid = fixture(tmp_path, BASE + [LIED], bundle_transform=setup_actions)
    engine = reload(tmp_path, mid)
    action = next(a for a in engine.action_catalog.values() if a.display_name == 'The Smoke Knows Who Lied')
    assert action.range_ft == 120
    assert not any(c.source_definition_id == action.source_definition_id for c in engine.legal_candidates())
    settle(table, mid, candidate(combat, mid, 'Test mark', target=FOE).candidate_id)
    c = candidate(combat, mid, 'The Smoke Knows Who Lied', target=FOE)
    settle(table, mid, c.candidate_id)
    engine = reload(tmp_path, mid)
    assert bears_mark(engine.state.actors[FOE], OWNER, 'Smoke Trace')
    assert any(e.event_type == 'SAVE_ROLLED' and LIED in e.source_definition_id for e in engine.events)


@pytest.mark.parametrize('accept', [False, True])
def test_chaos_step_miss_choice_once_on_actual_attackers_turn(tmp_path, accept):
    combat, table, mid = fixture(tmp_path, [], foe_sheet=__import__('tests.h1_support', fromlist=['sheet']).sheet([CHAOS], cl=15),
                                bundle_transform=setup_actions, named=True)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Test mark', target=ALLY).candidate_id)
    turn(table, mid, ALLY)
    before = reload(tmp_path, mid).state.actors[FOE].position
    prompts = settle(table, mid, candidate(combat, mid, 'Test miss', target=FOE).candidate_id,
                     picks={'choice:needle.chaos_missed_step': 'first' if accept else None})
    engine = reload(tmp_path, mid)
    assert any('Chaos-Step Awakening' in str(p) and 'Test miss' in str(p) for p in prompts)
    assert (engine.state.actors[FOE].position != before) == accept
    again = settle(table, mid, candidate(combat, mid, 'Test miss', target=FOE).candidate_id,
                   picks={'choice:needle.chaos_missed_step': None})
    assert any('chaos_missed_step' in str(p) for p in again) == (not accept)


def test_chaos_step_ai_defender_chooses_a_real_step(tmp_path):
    from tests.h1_support import sheet
    combat, table, mid = fixture(tmp_path, [], foe_sheet=sheet([CHAOS], cl=15),
                                bundle_transform=setup_actions)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Test mark', target=ALLY).candidate_id)
    turn(table, mid, ALLY)
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    before = reload(tmp_path, mid).state.actors[FOE].position
    settle(table, mid, candidate(combat, mid, 'Test miss', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].position != before
    assert engine.state.actors[FOE].turn_flags.get('drunken_chaos_miss_turn')
