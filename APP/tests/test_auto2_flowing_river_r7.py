"""Native declaration consent names the resolving attack, through saved service turns."""
import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN, BAI
from combat.gate2_runtime_models import Position
from combat import ext
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, ME, sheet
from tests.test_hidden_targeting import turn
from tests.test_auto2_flowing_river import RESPONSE

OA = 'system:combat.opportunity_attack'
CONSENT = 'reaction:typed.' + RESPONSE


@pytest.mark.parametrize('ai_turn', [False, True], ids=['manual-turn', 'ai-turn'])
@pytest.mark.parametrize('use', [False, True], ids=['decline', 'use'])
def test_native_opportunity_consent_names_actual_attacker_action_recipient(tmp_path, monkeypatch, ai_turn, use):
    doc = sheet([RESPONSE], cl=15, score=50)
    doc['identity']['display_name'] = 'River Keeper'
    bundle = compile_character(doc, actor_id=ME, reaction_plan={'ask': True})
    # The historical native roster's system OA has no catalogue descriptor.
    # Supply a synthetic descriptor before sealing; the real native OA resolver,
    # eligibility, player consent and Reaction payment remain in production code.
    bundle['action_catalog'].append({'source_definition_id': OA, 'display_name': 'Opportunity Attack',
        'owner_id': AN, 'economy': 'REACTION', 'resolution_kind': 'ATTACK',
        'target_kind': 'HOSTILE_ENTITY', 'reach_ft': 5, 'range_ft': None, 'costs': [],
        'parameters': {'attack_kind': 'weapon'}})
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)
    svc = CombatService(ROOT, tmp_path)
    mid = svc.persistence.create_match(match_seed='RIVER-R7-NATIVE-OA', typed_bundles=(bundle,),
        roster_setup={'primary_actor_ids': [ME, AN, BAI] if ai_turn else [ME, AN],
            'team_by_actor': {ME: 'a', AN: 'b', BAI: 'a'},
            'starting_positions': {ME: {'x': 4, 'y': 6}, AN: {'x': 5, 'y': 6}, BAI: {'x': 2, 'y': 6}}}).match_id
    for aid in ((ME, AN, BAI) if ai_turn else (ME, AN)):
        svc.set_controller_mode(mid, actor_id=aid, controller_mode='MANUAL')
    table = TabletopService(svc, tmp_path)
    turn(table, mid, BAI if ai_turn else ME)
    state = table.state(mid)
    move = next(c for c in svc._load_session(mid).engine.legal_candidates()
                if (c.source_definition_id == 'system:combat.hold_position' if ai_turn else
                    c.kind == 'MOVE' and c.destination.x == 4 and c.destination.y == 4))
    if ai_turn:
        production = svc.controller
        class MoveController:
            def choose_primary_action(self, context):
                # Choose only from the legal menu the actor actually receives.
                selected = next(c for c in context.legal_candidates if c.candidate_id == move.candidate_id)
                return ManualControllerAdapter(lambda _: (selected.candidate_id, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(production, name)
        svc.controller = MoveController()
        svc.set_controller_mode(mid, actor_id=BAI, controller_mode='LOCAL_AUTO')
        # Synthetic ally movement grant at an existing hook, within execution.
        # Its real native steps provoke the OA; no resolver is patched and the
        # manual River owner remains separate from the AI outer actor.
        def ally_step(engine, event_type, kwargs):
            if event_type == 'HOLD_POSITION_COMMITTED' and kwargs.get('actor_id') == BAI:
                mover = engine.state.actors[ME]
                engine.grant_movement(mover, (mover.position, Position(x=4, y=5), Position(x=4, y=4)),
                    'test:ally-movement-grant', feet=10, intent=engine._active_intent, provokes=True)
        ext.effects()
        monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS.get('event', []), ally_step])
    before = svc._load_session(mid).engine.state.model_dump(mode='json')
    answers, prompts = [], []
    for _ in range(12):
        result = (table.auto_step(mid, state['last_sequence'], answers) if ai_turn else
                  table.act(mid, move.candidate_id, move.decision_id, move.state_version, state['last_sequence'], answers))
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            break
        assert svc._load_session(mid).engine.state.model_dump(mode='json') == before
        prompt = result['reaction']; prompts.append(prompt)
        is_response = prompt['context']['reaction_source_id'] == CONSENT
        answers.append({**prompt['context'], 'selection': 'USE' if not is_response or use else 'DECLINE'})
    else:
        pytest.fail('Native attack consent never committed')
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert fresh.engine.state.model_dump(mode='json') == svc._load_session(mid).engine.state.model_dump(mode='json')
    assert fresh.verify()['status'] == fresh.mechanical.replay()['status'] == 'PASS'
    e = fresh.engine
    response = [p for p in prompts if p['context']['reaction_source_id'] == CONSENT]
    assert len(response) == 1, prompts
    p = response[0]
    assert p['context']['reactor_id'] == ME
    assert p['by'] == p['trigger_actor'] == 'An Eui'
    assert p['affected'] == 'River Keeper'
    assert p['action'] == 'Opportunity Attack'
    assert "An Eui attacks River Keeper with Opportunity Attack." == p['moment']
    assert 'Move' not in p['moment']
    assert p['context']['checkpoint'].startswith('TYPED:ATTACK_DECLARED@')
    assert e.state.actors[ME].reaction_available is (not use)
    assert not e.state.actors[AN].reaction_available
    assert e.state.actors[ME].position.x == 4 and e.state.actors[ME].position.y == 4
    attacks = [x for x in e.events if x.event_type == 'ATTACK_ROLLED' and x.source_definition_id == OA]
    assert len(attacks) == 1 and attacks[0].actor_id == AN and attacks[0].target_ids == (ME,)
    assert bool([x for x in e.events if x.event_type == 'REACTION_WINDOW_OPENED' and x.source_definition_id == RESPONSE]) is use
    assert not any(m.source_definition_id.startswith('flowing_response:') for m in e.state.actors[ME].modifiers.values())
    assert getattr(e, '_reaction_trigger', None) is None
