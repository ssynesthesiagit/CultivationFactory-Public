"""F1-F4: table admission, automatic-seat choices, durable movement, portable audits.

Synthetic test actions use ordinary typed execution; no running-fight condition,
ownership, movement receipt or source flag is fabricated. They isolate the shared
OA and movement contracts without claiming whole-record acquisition coverage.
"""

import pytest

from combat import ext
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_policy import PolicyLibrary
from tests import test_mgr_t14_heaven_binding_chain_body_floor58 as support
from tests.test_lock2_persistence import act

OWNER, TARGET = support.OWNER, support.TARGET


def add_action(monkeypatch, actor_id, source, effects):
    ext.effects()
    previous = list(ext._HOOKS.get('compile_actions', ()))

    def compile_action(info):
        if info['actor_id'] != actor_id:
            return None
        return [ActionDefinition(source_definition_id=source, display_name='Test movement or protection',
            owner_id=actor_id, economy=EconomyKind.NONE, resolution_kind='TYPED',
            target_kind='HOSTILE_ENTITY', range_ft=60,
            parameters={'typed': {'source': source, 'numbers': info['numbers'], 'effects': effects,
                                  'duration': {'kind': 'instant'}}})]

    monkeypatch.setitem(ext._HOOKS, 'compile_actions', [*previous, compile_action])


def step(table, mid, destination, *, decline=False):
    state = table.state(mid)
    menu = state['menu']
    move = next(m for m in menu['moves'] if m['destination'] == destination)
    answers = []
    for _ in range(24):
        result = table.act(mid, move['candidate_id'], menu['decision_id'], menu['state_version'],
                           state['last_sequence'], answers)
        if result['status'] == 'COMMITTED':
            return state['last_sequence'], answers
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        answer = {**prompt['context'], 'selection': 'DECLINE' if decline else 'USE'}
        if prompt.get('choice') and not decline:
            answer['option_ids'] = [prompt['choice']['options'][0]['id']]
        answers.append(answer)
    raise AssertionError('unbounded reaction prompts')


@pytest.mark.parametrize('protection', ['no_opportunity_attacks', 'charmed', 'response', 'decline'])
def test_network_obeys_normal_oa_protection_and_response_after_table_reload(tmp_path, monkeypatch, protection):
    if protection in {'no_opportunity_attacks', 'charmed'}:
        add_action(monkeypatch, TARGET, 'test:chain-protection', [{'type': 'condition',
            'applies_to': 'target', 'condition': protection, 'duration': '1 minute',
            'condition_data': {'against': TARGET}}])
    service, table, mid = support.acquired_fight(tmp_path,
        ['chain_body_integration', 'thousand_link_meridian_network'], ask_reactions=True)
    support.native_tether(service, table, mid)
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    if protection in {'no_opportunity_attacks', 'charmed'}:
        support.commit(table, mid, 'test:chain-protection')
        owner = support.cold(service, mid).state.actors[OWNER]
        assert any(c.condition_id == 'condition:typed.' + protection for c in owner.conditions.values())
    responses = []
    if protection == 'response':
        previous = list(ext._HOOKS.get('opportunity_response', ()))

        def veto(engine, reactor, mover):
            if reactor.entity_id == OWNER and mover.entity_id == TARGET:
                responses.append((reactor.entity_id, mover.entity_id))
                return False
            return None

        monkeypatch.setitem(ext._HOOKS, 'opportunity_response', [*previous, veto])
    sequence, answers = step(table, mid, {'x': 4, 'y': 5}, decline=protection == 'decline')
    engine = support.cold(service, mid)
    assert engine.state.actors[OWNER].reaction_available
    assert not any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER and e.sequence > sequence
                   for e in engine.events)
    if protection == 'response':
        assert responses
    if protection == 'decline':
        assert any('LEAVE_REACH' in str(a.get('checkpoint', '')) for a in answers)


def test_save_result_prompt_with_unknown_braced_text_still_asks_and_commits(tmp_path, monkeypatch):
    """The shared ``path_results`` prompt is reviewed data, not a format string.

    The public export replaces prose words (including one inside a ``{placeholder}``),
    so ``str.format`` raised ``KeyError: 'guvwlr'`` for Drag the Heavens on public CI.
    Any other braced text must be shown as written and the choice must still commit.
    """
    result = {'type': 'path_results', 'family': 'chain_prompt_guard', 'name': 'Chain Prompt Guard', 'count': 1,
              'prompt': 'Chain Prompt Guard: {target} failed its save; the {guvwlr} waits; choose one result.',
              'options': [{'label': 'Take the Result',
                           'effects': [{'type': 'condition', 'applies_to': 'target', 'condition': 'prone'}]}]}
    add_action(monkeypatch, OWNER, 'test:chain-prompt-guard',
               [{'type': 'save', 'ability': 'dex', 'applies_to': 'target',
                 'on_fail': [result], 'on_success': [result]}])
    service, table, mid = support.acquired_fight(tmp_path, ['chain_body_integration'])
    support.commit(table, mid, 'test:chain-prompt-guard', choose='Take the Result')
    engine = support.cold(service, mid)
    assert any(c.condition_id == 'condition:typed.prone' for c in engine.state.actors[TARGET].conditions.values())


def test_release_is_in_automatic_context_without_discarding_a_useful_binding(tmp_path):
    service, table, mid = support.acquired_fight(tmp_path, ['chain_body_integration'])
    engine = support.native_tether(service, table, mid)
    policy = PolicyLibrary(support.ROOT).for_actor(OWNER)[0]
    context = build_decision_context(engine, policy, for_ai=True)
    release = next(c for c in context.legal_candidates if c.source_definition_id.endswith('.release_meridian_tether'))
    assert any('release_meridian_tether' in g['source_definition_id'] for g in table.state(mid)['menu']['actions'])
    controller = LocalDeterministicController()
    score = controller._score_candidate(context, release, ())
    assert any(c.component == 'keep_meridian_tether' and c.value < 0 for c in score.components)
    assert controller.choose_primary_action(context).intent.candidate_id != release.candidate_id
    # An explicit pilot choice still commits the free release, including reload/replay.
    support.commit(table, mid, 'release_meridian_tether')
    assert not any(c.condition_id == 'condition:typed.meridian_tether'
                   for c in support.cold(service, mid).state.actors[TARGET].conditions.values())


@pytest.mark.parametrize('landing_x, remains', [(10, False), (9, True)])
def test_hostile_displacement_survives_willing_spatial_approach_until_end_turn(tmp_path, monkeypatch, landing_x, remains):
    add_action(monkeypatch, OWNER, 'test:chain-push', [{'type': 'forced_movement',
        'applies_to': 'target', 'distance_ft': 35, 'direction': 'away'}])
    service, table, mid = support.acquired_fight(tmp_path, ['chain_body_integration'],
        target_talents=['TAL_SPACE_FOLD_STEP'], target_mods={'CON': 100})
    support.native_tether(service, table, mid)
    support.commit(table, mid, 'test:chain-push')
    engine = support.cold(service, mid)
    assert engine.state.actors[TARGET].position.x == 11
    held = next(c for c in engine.state.actors[TARGET].conditions.values()
                if c.condition_id == 'condition:typed.meridian_tether')
    assert held.data['hostile_forced'] == 1
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    support.commit(table, mid, 'TAL_SPACE_FOLD_STEP', choose=f'cell:{landing_x},4',
                   destination={'x': landing_x, 'y': 4})
    engine = support.cold(service, mid)
    assert engine.state.actors[TARGET].position.x == landing_x
    held = next(c for c in engine.state.actors[TARGET].conditions.values()
                if c.condition_id == 'condition:typed.meridian_tether')
    assert held.data['hostile_forced'] == 1
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    engine = support.cold(service, mid)
    held = [c for c in engine.state.actors[TARGET].conditions.values()
            if c.condition_id == 'condition:typed.meridian_tether']
    assert bool(held) is remains
    if remains:
        assert held[0].data['hostile_forced'] == 0
