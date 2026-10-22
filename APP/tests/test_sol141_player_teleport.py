"""Real menu candidate -> table act -> bounded map choice -> commit and reload."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from combat.ext.teleport_steps import destinations
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from tests.test_mmx86_paid_teleport_variant import (
    ROOT, OWNER, EMPTY_STEP, PAY, _table, _owners_turn, _group, _send, _act)


@pytest.mark.skipif(not os.environ.get('SOL141_AI_BASE_CAPTURES'),
                    reason='opt in with the directory of captures from main 80c11f11')
@pytest.mark.parametrize('scenario', ['stock', 'shadow'])
def test_existing_ai_fight_matches_base_capture(tmp_path, scenario):
    """Compare full persistent state/events/rolls, not two modes of one head."""
    actual = subprocess.check_output([sys.executable, str(ROOT / 'tests/sol141_ai_capture.py'),
        str(ROOT), str(tmp_path), scenario], env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    expected = (Path(os.environ['SOL141_AI_BASE_CAPTURES']) / f'base-{scenario}.json').read_bytes()
    assert actual == expected


@pytest.mark.parametrize('paid', [False, True])
def test_bound_empty_step_asks_exact_legal_map_then_reload(tmp_path, paid):
    combat, table, mid = _table(tmp_path)
    state = _owners_turn(table, mid)
    group = _group(state, f'Empty Step {PAY}' if paid else 'Empty Step')
    assert group['destination_choice'] is True
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[OWNER]
    legal = {(c.x, c.y) for c in destinations(engine, actor, 20)}
    expected = set()
    for y in range(engine.grid.height):
        for x in range(engine.grid.width):
            cell = Position(x=x, y=y)
            if (cell != actor.position and engine.grid.distance_ft(actor.position, cell) <= 20
                    and engine.grid.placement_legal(cell, footprint=engine._footprint(actor),
                        occupied_cells=engine._occupied_cells_except(actor.entity_id))
                    and engine._line_of_sight_actor_to_cell(actor, cell)):
                expected.add((x, y))
    assert legal == expected
    chosen = group['options'][0]
    wanted = next(c for c in sorted(legal) if c != tuple(chosen['destination'].values()))
    before = dict(actor.resources)
    result = _send(table, mid, chosen['candidate_id'])
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    assert {(c['x'], c['y']) for c in prompt['choice']['map_pick']['cells']} == legal
    assert {(o['cell']['x'], o['cell']['y']) for o in prompt['choice']['options']} == legal
    assert CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[OWNER].resources == before
    # Continue the same pending candidate through a new table/service after reload.
    from combat.tabletop_service import TabletopService
    fresh = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    answer = {**prompt['context'], 'selection': 'USE', 'option_ids': [f'cell:{wanted[0]},{wanted[1]}']}
    assert _send(fresh, mid, chosen['candidate_id'], [answer])['status'] == 'COMMITTED'
    actor = CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[OWNER]
    assert actor.position == Position(x=wanted[0], y=wanted[1])
    pool = 'resource:core.stamina' if paid else 'resource:core.qi'
    assert actor.resources == {k: v - (k == pool) for k, v in before.items()}
    assert not actor.bonus_action_available and actor.action_available


@pytest.mark.parametrize('full_speed', [False, True])
def test_bound_dark_step_and_full_speed_offer_exact_legal_squares(tmp_path, full_speed):
    from combat import motion
    suffix = 'granted.tal_dark_step_through_darkness' + ('+full' if full_speed else '')
    combat, table, mid = _table(tmp_path, owner_talents=(
        'TAL_DARK_STEP_THROUGH_DARKNESS', 'tianxia.subpath.qi.ninpo_adept.feature.smoke_veil'))
    state = _owners_turn(table, mid)
    smoke = _group(state, 'Smoke Veil')
    candidate = next(o for o in smoke['options'] if o.get('destination') == {'x': 4, 'y': 6})
    _act(table, mid, candidate['candidate_id'], lambda prompt: None)
    _send(table, mid, table.state(mid)['menu']['end_turn'])
    state = _owners_turn(table, mid)
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[OWNER]
    action = next(a for a in engine.action_catalog.values() if a.source_definition_id.endswith(suffix))
    reach = engine._effective_speed(actor) // (1 if full_speed else 2)
    legal = {(c.x, c.y) for c in destinations(engine, actor, reach, where='darkness')}
    assert legal and motion.obscured(engine, actor)
    assert legal != {(c.x, c.y) for c in destinations(engine, actor, reach)}
    group = next(g for g in state['menu']['actions'] if g['label'] == action.display_name)
    assert group['destination_choice'] is True
    assert {(o['destination']['x'], o['destination']['y']) for o in group['options']} == legal
    wanted = sorted(legal)[-1]
    qi = actor.resources['resource:core.qi']
    prompts = _act(table, mid, group['options'][0]['candidate_id'], lambda prompt: [f'cell:{wanted[0]},{wanted[1]}'])
    assert len(prompts) == 1
    assert {(c['x'], c['y']) for c in prompts[0]['choice']['map_pick']['cells']} == legal
    actor = CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[OWNER]
    assert actor.position == Position(x=wanted[0], y=wanted[1])
    assert actor.resources['resource:core.qi'] == qi - int(full_speed)


def test_reaction_hop_offers_all_cells_not_sixteen_and_asks_once():
    from combat.ext.teleport_steps import reaction_teleport
    from combat.gate2_runtime_models import ReactionDecision
    from combat.typed_executor import Context
    from tests.test_mmx86_teleport_destination import _engine, _unbound_teleport, _intent, ME
    engine = _engine()
    actor = engine.state.actors[ME]
    action = _unbound_teleport(engine)
    legal = {f'cell:{c.x},{c.y}' for c in destinations(engine, actor, 20)}
    assert len(legal) > 16
    wanted = sorted(legal)[-1]
    prompts = []
    def choose(request):
        prompts.append(request)
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=ME,
            reaction_source_id=request['reaction_source_id'], selection='USE', option_ids=(wanted,)), None
    engine.set_reaction_provider(choose)
    ctx = Context(engine, actor, action, _intent(engine), action.parameters['typed'], [])
    reaction_teleport(ctx, {'distance_ft': 20, 'name': 'Reaction hop'})
    assert len(prompts) == 1
    assert set(prompts[0]['legal_option_ids']) == legal
    assert f'cell:{actor.position.x},{actor.position.y}' == wanted


def test_teleport_catalogue_requires_an_explicit_player_choice_audit():
    """Guard all native teleport rows, including nested responses/options/augments.

    This is a source/dispatch guard, not a claim every printed conditional has
    received an end-to-end scenario. New records require updating this audit.
    Plug-in fixed endpoints and Shadow Walker's scatter are separately reported.
    """
    import json
    from combat.typed_executor import BLOCKS, block_movement
    def walk(value):
        if isinstance(value, dict):
            if (value.get('type') in ('teleport', 'reaction_teleport') or
                    (value.get('type') == 'movement' and value.get('mode') == 'teleport')):
                yield {'type': value.get('type'), 'scope': value.get('applies_to') or 'self',
                       'distance_ft': value.get('distance_ft'),
                       'player_chooses': value.get('applies_to') in (None, 'self')}
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)
    actual = {}
    for path, key in [('authority/Tianxia_Typed_Mechanics_Authority_R1.json', 'mechanics'),
                      ('combat/rules/feature_blocks.json', None)]:
        records = json.loads((ROOT / path).read_text())
        if key:
            records = records[key]
        for record, value in records.items():
            rows = list(walk(value))
            if rows:
                actual[record] = rows
    expected = json.loads((ROOT / 'tests/fixtures/sol141_teleport_catalogue.json').read_text())
    assert actual == expected
    assert BLOCKS['teleport'] is BLOCKS['movement'] is block_movement


def test_nonteleport_placement_keeps_its_player_menu():
    from combat.ext.teleport_steps import action_destination_choice, player_candidate
    from tests.test_mmx86_teleport_destination import _engine, ME
    from combat.gate2_runtime_models import ActionDefinition, CandidateKind
    engine = _engine()
    action = ActionDefinition(source_definition_id='action:test.armament-placement', display_name='Place armament',
        owner_id=ME, economy='BONUS_ACTION', resolution_kind='TYPED', target_kind='SELF', range_ft=30,
        parameters={'typed': {'effects': [{'type': 'domain_armament', 'applies_to': 'self',
            'picks_destination': True, 'distance_ft': 30}]}})
    assert action_destination_choice(engine, action) is None
    actor = engine.state.actors[ME]
    candidate = engine._candidate(CandidateKind.BONUS_ACTION, actor, action.source_definition_id, action.display_name,
        target_ids=(ME,), destination=Position(x=4, y=6), metadata={'teleport': True})
    assert player_candidate(engine, actor, candidate, action) is None


def test_bound_ai_step_has_byte_identical_headless_replay():
    """The new player hooks contribute no state/events to a recorded AI hop."""
    import json
    from combat.gate2_runtime_models import ActionIntent
    from tests.test_mmx86_paid_teleport_variant import _engine as paid_engine
    traces = []
    for mode in ('LOCAL_AUTO', None):
        engine = paid_engine(mode=mode)
        candidate = next(c for c in engine.legal_candidates()
            if c.source_definition_id.endswith(EMPTY_STEP + '#pay1') and c.destination == Position(x=4, y=6))
        engine.execute_intent(ActionIntent(intent_id='sol141-ai-replay', decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=OWNER,
            target_ids=candidate.target_ids, destination=candidate.destination, option_ids=candidate.option_ids))
        assert engine.state.actors[OWNER].position == Position(x=4, y=6)
        traces.append(json.dumps({'state': engine.state.model_dump(mode='json'),
            'events': [e.model_dump(mode='json') for e in engine.events],
            'rolls': [r.model_dump(mode='json') for r in engine.rolls]}, sort_keys=True))
    assert traces[0] == traces[1]


@pytest.mark.parametrize('cancel', [False, True])
@pytest.mark.parametrize('restricted_first', [False, True])
def test_shadowless_self_reaction_chooses_legal_escape_at_table(tmp_path, cancel, restricted_first):
    from tests.r1i_service_support import fixture, candidate, OWNER as defender, FOE as attacker
    def prepare(bundles):
        if not restricted_first:
            return
        from combat.canonical import canonical_sha256
        from combat.gate2_runtime_models import ActionDefinition
        owner = next(b for b in bundles if b['actor_id'] == defender)
        # A genuine unrelated SELF restriction: retracting a non-existent lurk
        # is vetoed by shadow_candidates, regardless of destination.
        action = ActionDefinition(source_definition_id='test:restricted-self', display_name='Retract Shadow Lurk',
            owner_id=defender, economy='BONUS_ACTION', resolution_kind='TYPED', target_kind='SELF',
            parameters={'shadow_retract': True, 'typed': {'effects': [], 'numbers': {}}})
        owner['action_catalog'].insert(0, action.model_dump(mode='json'))
        owner['actor_template']['action_ids'].insert(0, action.source_definition_id)
        owner.pop('bundle_sha256', None)
        owner['bundle_sha256'] = canonical_sha256(owner)
    combat, table, mid, send, commit = fixture(tmp_path, ['TAL_SHADOW_SHADOWLESS_REVERSAL'],
        owner_ac=1, foe_score=30, seed='SOL141-SHADOW', bundle_transform=prepare)
    while table.state(mid)['menu']['actor_id'] != attacker:
        commit(table.state(mid)['menu']['end_turn'])
    cid = candidate(table, mid, 'Unarmed', defender)
    engine = combat._load_session(mid).engine
    actor, foe = engine.state.actors[defender], engine.state.actors[attacker]
    legal = {(c.x, c.y) for c in destinations(engine, actor, engine._effective_speed(actor) // 2)
             if engine.grid.distance_ft(c, foe.position) > 5}
    before = actor.resources['resource:core.qi']
    start, hp, round_number = actor.position, actor.current_hp, engine.state.round_number
    if restricted_first:
        from combat.ext.teleport_steps import destination_allowed
        assert actor.action_ids[0] == 'test:restricted-self'
        assert not destination_allowed(engine, actor, Position(x=2, y=6), 15,
            action=engine.action_catalog[actor.action_ids[0]])
    answers, choices = [], []
    for _ in range(6):
        result = send(cid, answers)
        if result['status'] == 'COMMITTED':
            break
        prompt = result['reaction']
        source = prompt['context']['reaction_source_id']
        assert source in ('choice:needle.shadow_slip', 'choice:needle.teleport_destination')
        if source.endswith('shadow_slip'):
            option = 'use'
        else:
            choices.append(prompt)
            assert {(c['x'], c['y']) for c in prompt['choice']['map_pick']['cells']} == legal
            wanted = sorted(legal)[-1]
            option = f'cell:{wanted[0]},{wanted[1]}'
        declining = cancel and source.endswith('teleport_destination')
        # Pending landing is rolled back, including silhouette and payment.
        if source.endswith('teleport_destination'):
            pending = CombatService(ROOT, tmp_path)._load_session(mid).engine
            assert pending.state.actors[defender].position == start
            assert pending.state.actors[defender].resources['resource:core.qi'] == before
            from combat.ext import placed
            assert not placed.of(pending, 'shadow_silhouette')
        answers.append({**prompt['context'], 'selection': 'DECLINE' if declining else 'USE',
                        'option_ids': [] if declining else [option]})
    assert result['status'] == 'COMMITTED'
    assert len(choices) == 1
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid).engine
    actor = reloaded.state.actors[defender]
    assert actor.position == (start if cancel else Position(x=wanted[0], y=wanted[1]))
    assert actor.resources['resource:core.qi'] == before - 5
    assert not actor.reaction_available
    assert actor.turn_flags[f'shadow_round_reversal:{round_number}'] is True
    assert actor.current_hp < hp if cancel else actor.current_hp == hp
    silhouettes = placed.of(reloaded, 'shadow_silhouette')
    assert len(silhouettes) == (0 if cancel else 1)
    if not cancel:
        assert silhouettes[0].affected_cells == (start,)
