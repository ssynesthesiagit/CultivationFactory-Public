"""Own-knowledge and native damaging-start regressions; no live transports."""
from pathlib import Path
import json
import socket
import pytest
from combat import ext, zones
from combat.ai_observation import goal_from_sheet
from combat.ext.ai_movement import destination_details, destination_provider, movement_order
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_policy import PolicyLibrary
from combat.gate2_runtime_models import Position
from tests.test_zones import _engine, _cast, OWNER, AN, SHEET

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **k):
        raise AssertionError('Tests cannot contact a live server')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)


def context(engine, actor_id=AN):
    engine.state.current_actor_id = actor_id
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    policy, _ = PolicyLibrary(ROOT).for_actor(actor_id)
    return build_decision_context(engine, policy, for_ai=True)


def hazard_sheet():
    return {**SHEET, 'spheres_and_talents': {'sphere_record_ids': ['tianxia.sphere.fire'],
             'learned_talent_record_ids': ['FIRE_BASE_CONFLAGRATION']}}


def hazard_engine(*, battlefield=None, positions=None, seed='AI-SLICES', rounds=2):
    from combat.factory_compiler import compile_character
    from combat.gate4_engine import Gate4ControllerEngine
    sheet = hazard_sheet()
    return Gate4ControllerEngine(ROOT, match_seed=seed, maximum_rounds=rounds,
        typed_bundles=(compile_character(sheet, actor_id=OWNER),), battlefield=battlefield,
        roster_setup={'primary_actor_ids': [OWNER, AN],
            'team_by_actor': {OWNER: 'team:a', AN: 'team:b'},
            'starting_positions': positions or {OWNER: {'x': 3, 'y': 6}, AN: {'x': 13, 'y': 6}}})


def damaging_start(monkeypatch, *, invisible=False):
    monkeypatch.setenv('CF_COMBAT_AI_SLICES_1_2', '1')
    engine = hazard_engine()
    _cast(engine, 'Conflagration', Position(x=13, y=6))
    if invisible:
        for zone in zones.typed_zones(engine):
            zone.trigger_profile.setdefault('visual', {})['invisible'] = True
    # The bug is an actor STARTING inside, rather than a path entering a hazard.
    engine.state.actors[AN].position = Position(x=13, y=6)
    engine.grid.cover.add((17, 6))  # perceived nearby cover in this fixture
    engine.state.current_actor_id = AN
    engine.state.current_slot_index = engine.state.initiative_order.index(AN)
    engine._system_start_turn()
    from combat.target_knowledge import observe
    observe(engine)
    return engine


def test_native_damaging_start_preserves_escape_near_cover(monkeypatch):
    engine = damaging_start(monkeypatch)
    engine.state.actors[AN].action_available = False
    engine.state.actors[AN].bonus_action_available = False
    ctx = context(engine)
    assert ctx.own_knowledge.harms and ctx.own_knowledge.harms[0].damage > 0
    assert ctx.zones == ()
    assert not any('personal_observations' in e.get('payload', {}) for e in ctx.recent_events)
    rows = tuple(c for c in ctx.legal_candidates if c.kind == 'MOVE')
    ordered = movement_order(ctx, rows)
    assert set(ordered) == {c.candidate_id for c in rows}
    assert len(ordered) == len(rows) > 5
    details = destination_details(ctx)
    assert any(details[cid]['features']['escape'] > 0 for cid in ordered[:5])
    assert any('cover terrain' in d['description'] for d in details.values())
    provider = destination_provider(ctx)
    assert set(provider([{'candidate_id': cid} for cid in ordered])) == set(ordered)
    controller = LocalDeterministicController()
    choice = controller.choose_primary_action(ctx)
    selected = next(c for c in rows if c.candidate_id == choice.intent.candidate_id)
    boundary = {p for z in zones.typed_zones(engine) for p in z.affected_cells}
    assert selected.destination not in boundary
    staying = next(c for c in ctx.legal_candidates if c.kind == 'END_TURN')
    assert any(c.component == 'observed_area_stay' and c.value < 0
               for c in controller._score_candidate(ctx, staying, ()).components)
    escape = selected
    assert not escape.metadata.get('zone_hazard_exposure')
    assert any(c.component == 'personal_movement' and c.value > 0
               for c in controller._score_candidate(ctx, escape, ()).components)
    # Native legality/commit, not an evaluator-only call.
    from combat.gate2_runtime_models import ActionIntent
    before = engine.state.actors[AN].position
    engine.execute_intent(ActionIntent(intent_id='escape-test', decision_id=escape.decision_id,
        candidate_id=escape.candidate_id, state_version=escape.state_version, actor_id=AN,
        target_ids=escape.target_ids, destination=escape.destination))
    assert engine.state.actors[AN].position != before
    assert not any(h.position == context(engine).own_knowledge.position
                   for h in context(engine).own_knowledge.harms)


def test_hidden_truth_never_changes_personal_frame_or_choice(monkeypatch):
    monkeypatch.setenv('CF_COMBAT_AI_SLICES_1_2', '1')
    engine = _engine()
    from combat.gate2_runtime_models import ConditionInstance, ZoneState
    # Unseen from the beginning, never personally observed by this creature.
    target = engine.state.actors[OWNER]
    target.conditions['hidden'] = ConditionInstance(instance_id='hidden',
        condition_id='condition:typed.invisible', source_definition_id='test',
        source_actor_id=OWNER, target_id=OWNER, applied_sequence=0)
    engine.events = [e.model_copy(update={'payload': {k: v for k, v in e.payload.items()
                      if k != 'personal_observations'}}) for e in engine.events]
    first = context(engine)
    pick = LocalDeterministicController().choose_primary_action(first)
    target.position = Position(x=30, y=15)
    target.current_hp = 1
    target.resources = {rid: 0 for rid in target.resources}
    engine.state.zones['unseen'] = ZoneState(zone_id='unseen', source_definition_id='test', owner_id=OWNER,
        center=Position(x=30, y=15), radius_cells=0, affected_cells=(Position(x=30, y=15),),
        concentration_link=False, created_round=1, trigger_profile={})
    second = context(engine)
    assert first.own_knowledge == second.own_knowledge
    assert destination_details(first) == destination_details(second)
    assert pick.intent.candidate_id == LocalDeterministicController().choose_primary_action(second).intent.candidate_id
    assert OWNER not in {c.entity_id for c in second.own_knowledge.creatures}


def test_unseen_area_boundaries_stay_unknown_and_harm_memory_expires(monkeypatch):
    engine = damaging_start(monkeypatch, invisible=True)
    ctx = context(engine)
    assert ctx.own_knowledge.harms
    assert all(not h.cells and not h.complete_boundary for h in ctx.own_knowledge.harms)
    from combat.ext.ai_movement import attributed_harms, latest_receipt
    prior = latest_receipt(engine)[AN]
    engine.state.actors[AN].turns_started += 2
    assert attributed_harms(engine, engine.state.actors[AN], prior['harms'], prior['sequence']) == {}


def test_personal_memory_never_follows_team_or_hidden_movement(monkeypatch):
    monkeypatch.setenv('CF_COMBAT_AI_SLICES_1_2', '1')
    engine = _engine()
    from combat.target_knowledge import observe
    from combat.gate2_runtime_models import ConditionInstance
    observe(engine)
    seen = context(engine).own_knowledge
    old = next(c.position for c in seen.creatures if c.entity_id == OWNER)
    target = engine.state.actors[OWNER]
    target.conditions['hidden'] = ConditionInstance(instance_id='hidden',
        condition_id='condition:typed.invisible', source_definition_id='test',
        source_actor_id=OWNER, target_id=OWNER, applied_sequence=0)
    target.position = Position(x=30, y=15)
    engine.state.observations.setdefault(engine.state.actors[AN].team_id, {})[OWNER] = target.position
    later = context(engine).own_knowledge
    remembered = next(c for c in later.creatures if c.entity_id == OWNER)
    assert remembered.position == old and remembered.mode == 'LAST_OBSERVED'
    with pytest.raises(Exception):
        later.hp = 0
    with pytest.raises(Exception):
        later.squares[0].known = False


def test_goal_uses_existing_sheet_and_empty_fallback():
    assert goal_from_sheet({}) == ''
    sheet = {'dao_iching': {'dao': {'core_theme': 'Protect companions'},
                          'i_ching': {'change_rule': 'Retreat when pressure rises'}}}
    text = goal_from_sheet(sheet)
    assert 'Protect companions' in text and 'Retreat when pressure rises' in text
    assert 'playbook' not in text.lower()


def test_disabled_frame_and_hooks_are_inert(monkeypatch):
    monkeypatch.delenv('CF_COMBAT_AI_SLICES_1_2', raising=False)
    engine = _engine()
    before = [e.model_dump(mode='json') for e in engine.events]
    ctx = context(engine)
    assert ctx.own_knowledge is None
    assert 'own_knowledge' not in ctx.model_dump(mode='json')
    assert ext.run_strict('personal_observation_receipt', engine) == []
    assert ext.run_strict('ai_movement_order', ctx, ()) == []
    assert [e.model_dump(mode='json') for e in engine.events] == before


def test_personal_receipt_survives_service_commit_reload(tmp_path, monkeypatch):
    monkeypatch.setenv('CF_COMBAT_AI_SLICES_1_2', '1')
    from combat.gate4_persistence import Gate4Persistence
    from combat.gate5_service import CombatService
    session = Gate4Persistence(ROOT, tmp_path).create_match(match_seed='PERSONAL-RELOAD', maximum_rounds=2)
    policies = PolicyLibrary(ROOT)
    controller = LocalDeterministicController()
    policy, _ = policies.for_actor(session.engine.state.current_actor_id)
    ctx = build_decision_context(session.engine, policy, for_ai=True)
    session.execute_controller_choice(controller.choose_primary_action(ctx), controller=controller, policy_library=policies)
    aid = session.engine.state.current_actor_id
    policy, _ = policies.for_actor(aid)
    before = build_decision_context(session.engine, policy, for_ai=True).own_knowledge
    loaded = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    after = build_decision_context(loaded.engine, policy, for_ai=True).own_knowledge
    assert before == after
    assert any('personal_observations' in e.payload for e in loaded.engine.events)


def test_native_flight_height_kept_and_value_not_charged_twice(tmp_path, monkeypatch):
    monkeypatch.setenv('CF_COMBAT_AI_SLICES_1_2', '1')
    from tests.test_ai_flight_options import flyer_fight, FLYER
    from tests.test_p20261010_04_height_ai import BOW_KIT
    combat, table, mid, runner = flyer_fight(tmp_path, flyer_kit=BOW_KIT)
    engine = combat._load_session(mid).engine
    policy, _ = combat.policies.for_actor(FLYER)
    ctx = build_decision_context(engine, policy, for_ai=True)
    rows = tuple(c for c in ctx.legal_candidates if c.kind == 'MOVE')
    order = movement_order(ctx, rows)
    assert set(order) == {c.candidate_id for c in rows}
    useful = [c for c in rows if c.destination.z > 0 and
              c.metadata.get('flight_tactics', {}).get('destination', {}).get('safe_attack')]
    assert useful
    assert any(c.candidate_id in order[:5] for c in useful)
    details = destination_details(ctx)
    candidate = max(useful, key=lambda c: details[c.candidate_id]['features']['flight'])
    features = details[candidate.candidate_id]['features']
    assert features['flight'] > 0
    scores = LocalDeterministicController()._score_candidate(ctx, candidate, ()).components
    added = next(c.value for c in scores if c.component == 'personal_movement')
    assert added == sum(value for name, value in features.items() if name != 'flight')
