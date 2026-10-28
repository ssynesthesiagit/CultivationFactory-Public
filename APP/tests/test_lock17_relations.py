"""Neutral setup, current allegiance and owner changes at the real Table boundary."""
from pathlib import Path

import pytest

from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN, LEE, LING, BAI
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate3_reducer import canonical_state_sha256
from combat.gate3_storage import Gate3InjectedCrash
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_persistence import Gate4Persistence
from combat.gate4_policy import PolicyLibrary
from combat.gate5_service import CombatService, CombatServiceError, FACTORY_ACTOR_PREFIX
from combat.relation_models import Relations
from combat.relations import relation, ALLY, ENEMY, NEUTRAL, NEUTRAL_TEAM, command_intent
from combat.tabletop_service import TabletopService, TabletopError
from tests.test_factory_live_match import _install

ROOT = Path(__file__).resolve().parents[1]


def _native(tmp_path):
    session = Gate4Persistence(ROOT, tmp_path).create_match(match_seed='LOCK17-RELATIONS', roster_setup={
        'primary_actor_ids': [AN, LEE, LING, BAI],
        'team_by_actor': {AN: 'team:a', LEE: 'team:a', LING: 'team:b', BAI: NEUTRAL_TEAM},
        'starting_positions': {AN: {'x': 2, 'y': 6}, LEE: {'x': 3, 'y': 6},
                               LING: {'x': 6, 'y': 6}, BAI: {'x': 10, 'y': 6}},
    })
    return CombatService(ROOT, tmp_path), session.match_id


def _change(service, mid, kind, subject, other, value=None):
    session = service._load_session(mid)
    change = {'kind': kind, 'subject': subject, 'other': other}
    if value is not None:
        change['relation'] = value
    service.change_relations(mid, change=change, expected_state_version=session.engine.state.state_version)
    return service._load_session(mid)


def _context(engine):
    policy, _ = PolicyLibrary(ROOT).for_actor(engine.state.current_actor_id)
    return build_decision_context(engine, policy, for_ai=True)


def test_legacy_serialization_and_symmetric_precedence():
    e = Gate2Engine(ROOT, match_seed='LOCK17-LEGACY')
    a, friend, enemy = (e.state.actors[x] for x in (AN, LEE, LING))
    assert relation(e, a, friend) == ALLY and relation(e, a, enemy) == ENEMY
    assert 'relations' not in e.state.model_dump(mode='json')
    assert 'relations' not in _context(e).model_dump(mode='json')
    neutral = enemy.model_copy(update={'team_id': NEUTRAL_TEAM})
    other = friend.model_copy(update={'team_id': NEUTRAL_TEAM})
    assert relation(e, neutral, a) == relation(e, neutral, other) == NEUTRAL
    assert relation(e, neutral, neutral) == ALLY
    left, right = sorted((a.entity_id, neutral.entity_id))
    e.state.relations = Relations(actors={left: {right: ENEMY}})
    assert relation(e, neutral, a) == relation(e, a, neutral) == ENEMY
    assert relation(e, neutral, other) == NEUTRAL


def test_table_side_changes_stale_choices_and_replay(tmp_path):
    service, mid = _native(tmp_path)
    table = TabletopService(service, tmp_path)
    before = service._load_session(mid)
    choices = before.engine.legal_candidates()
    old = next(c for c in choices if c.kind == 'END_TURN')
    old_rolls = before.engine.state.roll_counter
    session = _change(service, mid, 'ACTOR_SIDE', BAI, 'team:a')
    assert relation(session.engine, session.engine.state.actors[BAI], session.engine.state.actors[AN]) == ALLY
    assert session.engine.state.roll_counter == old_rolls
    with pytest.raises(TabletopError, match='moved on'):
        table.act(mid, old.candidate_id, old.decision_id, old.state_version, 0)
    session = _change(service, mid, 'ACTOR_SIDE', AN, 'team:b')
    a, b = session.engine.state.actors[AN], session.engine.state.actors[LEE]
    assert relation(session.engine, a, b) == ENEMY
    # The next Table commit uses the new decision; fresh load and reducer replay agree.
    end = next(c for c in session.engine.legal_candidates() if c.kind == 'END_TURN')
    result = table.act(mid, end.candidate_id, end.decision_id, end.state_version, 0)
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[AN].team_id == 'team:b'
    assert loaded.verify()['status'] == 'PASS'
    assert canonical_state_sha256(loaded.engine.state) == loaded.mechanical.replay()['canonical_state_sha256']
    assert any('joins' in row['summary'] for row in table.events(mid, 0)['events'])
    # Old command cannot silently be applied to a later decision.
    with pytest.raises(CombatServiceError):
        service.change_relations(mid, change={'kind': 'ACTOR_SIDE', 'subject': AN, 'other': 'team:a'}, expected_state_version=0)


def test_actor_and_team_relations_commit_and_recover(tmp_path):
    service, mid = _native(tmp_path)
    session = _change(service, mid, 'ACTOR_RELATION', BAI, AN, ENEMY)
    assert relation(session.engine, session.engine.state.actors[BAI], session.engine.state.actors[AN]) == ENEMY
    assert relation(session.engine, session.engine.state.actors[BAI], session.engine.state.actors[LEE]) == NEUTRAL
    intent = command_intent(session.engine, {'kind': 'TEAM_RELATION', 'subject': NEUTRAL_TEAM,
        'other': 'team:b', 'relation': ALLY}, expected_state_version=session.engine.state.state_version)
    def crash(stage, _):
        if stage == 'after_prepare_flush':
            raise Gate3InjectedCrash(stage)
    with pytest.raises(Gate3InjectedCrash):
        session.submit_intent(intent, primary_decision_record=None, reaction_provider=None, failure_injector=crash)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert relation(loaded.engine, loaded.engine.state.actors[BAI], loaded.engine.state.actors[LING]) == ALLY
    assert loaded.verify()['status'] == 'PASS'
    assert [e.event_type for e in loaded.engine.events].count('RELATION_CHANGED') == 2


def test_relation_logs_name_fighters_instead_of_opaque_team_codes(tmp_path):
    service, mid = _native(tmp_path)
    opaque = 'team:opaque.database47'
    session = _change(service, mid, 'ACTOR_SIDE', BAI, opaque)
    first = next(e for e in reversed(session.engine.events) if e.event_type == 'ACTOR_SIDE_CHANGED')
    assert 'joins a new side' in first.payload['log']
    session = _change(service, mid, 'ACTOR_SIDE', LEE, opaque)
    second = next(e for e in reversed(session.engine.events) if e.event_type == 'ACTOR_SIDE_CHANGED')
    assert session.engine.state.actors[BAI].display_name in second.payload['log']
    session = _change(service, mid, 'TEAM_RELATION', opaque, 'team:a', NEUTRAL)
    log = next(e.payload['log'] for e in reversed(session.engine.events) if e.event_type == 'RELATION_CHANGED')
    assert session.engine.state.actors[AN].display_name in log and 'neutral toward each other' in log
    assert not any('opaque' in e.payload.get('log','').lower() for e in session.engine.events)
    loaded = CombatService(ROOT,tmp_path)._load_session(mid)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_factory_neutral_group_and_bystander_ai(tmp_path):
    for pid in ('left', 'right', 'witness'):
        _install(tmp_path, pid)
    ids = {p: FACTORY_ACTOR_PREFIX+p for p in ('left', 'right', 'witness')}
    service = CombatService(ROOT, tmp_path)
    mid = service.create_factory_match(project_ids=['left'], opponent_actor_ids=[ids['right']],
        neutral_actor_ids=[ids['witness']], match_seed='LOCK17-NEUTRAL-FACTORY')['match_id']
    session = service._load_session(mid)
    assert session.engine.state.actors[ids['witness']].team_id == NEUTRAL_TEAM
    assert len({(a.position.x, a.position.y) for a in session.engine.state.actors.values()}) == 3
    # Advance complete turns without attacking to the neutral's real turn.
    for _ in range(3):
        if session.engine.state.current_actor_id == ids['witness']:
            break
        end = next(c for c in session.engine.legal_candidates() if c.kind == 'END_TURN')
        session.submit_intent(ActionIntent(intent_id=end.candidate_id, **{k: getattr(end, k)
            for k in ('candidate_id', 'decision_id', 'state_version', 'actor_id')}),
            primary_decision_record=None, reaction_provider=None)
    context = _context(session.engine)
    assert context.bystander
    controller = LocalDeterministicController()
    observed = []
    for _ in range(6):
        context = _context(session.engine)
        choice = controller.choose_primary_action(context)
        candidate = next(c for c in context.legal_candidates if c.candidate_id == choice.intent.candidate_id)
        observed.append(candidate.source_definition_id)
        session.submit_intent(choice.intent, primary_decision_record=choice.record, reaction_provider=None)
        if candidate.kind == 'END_TURN':
            break
    assert 'system:combat.dodge' in observed
    assert all(source in {'system:combat.movement', 'system:combat.dodge', 'system:combat.turn'} for source in observed)
    assert session.verify()['status'] == 'PASS'
    _change(service, mid, 'ACTOR_SIDE', ids['witness'], 'team:opponents')
    reloaded = service._load_session(mid)
    assert relation(reloaded.engine, reloaded.engine.state.actors[ids['witness']], reloaded.engine.state.actors[ids['left']]) == ENEMY


def test_hostile_menus_and_ai_never_target_neutrals(tmp_path):
    service, mid = _native(tmp_path)
    e = service._load_session(mid).engine
    e.state.current_actor_id = AN
    neutral = e.state.actors[BAI]
    neutral.position = Position(x=3, y=7)
    assert all(BAI not in c.target_ids for c in e.legal_candidates()
               if e.action_catalog.get(c.source_definition_id) and e.action_catalog[c.source_definition_id].target_kind == 'HOSTILE_ENTITY')
    context = _context(e)
    assert all(BAI not in c.target_ids for c in context.legal_candidates)
    before = e.state.model_dump(mode='json')
    LocalDeterministicController().choose_primary_action(context)
    assert e.state.model_dump(mode='json') == before


def test_manual_attack_does_not_make_neutral_hostile_and_buffs_survive(tmp_path, monkeypatch):
    from combat.gate2_runtime_models import ActionDefinition, DiceSpec, EconomyKind
    from tests.test_lock_choices import install
    from tests.test_hidden_targeting import turn
    from tests.test_lock2_persistence import act
    left, right, witness = [FACTORY_ACTOR_PREFIX+p for p in ('left', 'right', 'witness')]
    for pid in ('left', 'right', 'witness'):
        _install(tmp_path, pid)
    def actions(info):
        return [ActionDefinition(source_definition_id='test:creature-strike:'+info['actor_id'],
            owner_id=info['actor_id'], display_name='Practice strike', economy=EconomyKind.ACTION,
            resolution_kind='ATTACK', target_kind='ANY_CREATURE', range_ft=120, attack_bonus=100,
            damage=DiceSpec(count=1, sides=4, modifier=0), damage_type='BLUDGEONING')]
    install(monkeypatch, 'compile_actions', actions)
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({'display_name': 'Neutral yard', 'width_squares': 12, 'height_squares': 12,
        'walls': [], 'starts': {'team1': [[3, 4]], 'team2': [[7, 4]]}})
    mid = service.create_factory_match(project_ids=['left'], opponent_actor_ids=[right], neutral_actor_ids=[witness],
        control_modes={x: 'MANUAL' for x in (left, right, witness)},
        arena_id='battlefield:map.neutral-yard', match_seed='LOCK17-ATTACK')['match_id']
    table = TabletopService(service, tmp_path)
    turn(table, mid, left)
    e = service._load_session(mid).engine
    hp = e.state.actors[witness].current_hp
    candidate = next(c for c in e.legal_candidates() if c.source_definition_id == 'test:creature-strike:'+left
                     and c.target_ids == (witness,))
    context = _context(e)
    assert candidate.candidate_id not in {c.candidate_id for c in context.legal_candidates}
    result = table.act(mid, candidate.candidate_id, candidate.decision_id, candidate.state_version, 0)
    assert result['status'] == 'COMMITTED'
    e = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert e.state.actors[witness].current_hp < hp
    assert relation(e, e.state.actors[left], e.state.actors[witness]) == NEUTRAL
    turn(table, mid, witness)
    act(table, mid, 'system:combat.dodge')
    e = service._load_session(mid).engine
    effects = e.state.actors[witness].conditions.copy()
    assert effects
    session = _change(service, mid, 'ACTOR_SIDE', witness, 'team:factory')
    assert session.engine.state.actors[witness].conditions == effects
    assert session.verify()['status'] == 'PASS'
    # Joining an opposing side restores combat policy immediately.
    assert not _context(session.engine).bystander


def test_neutral_bystanders_do_not_prevent_truce_or_victory(tmp_path):
    service, mid = _native(tmp_path)
    session = _change(service, mid, 'TEAM_RELATION', 'team:a', 'team:b', ALLY)
    assert session.engine.state.terminal_result is not None
    assert session.engine.state.actors[BAI].active
    assert session.verify()['status'] == 'PASS'


def test_harmful_area_penalizes_neutrals_like_allies(tmp_path):
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    service, mid = _native(tmp_path)
    e = service._load_session(mid).engine
    e.state.current_actor_id = AN
    # Keep the caster and ally outside both bursts: this isolates the neutral
    # penalty from the separately tested friendly-fire penalty on allies.
    e.state.actors[AN].position = Position(x=1, y=6)
    e.state.actors[LEE].position = Position(x=1, y=7)
    e.state.actors[BAI].position = Position(x=7, y=6)
    source = 'test:each-creature-area'
    e.action_catalog[source] = ActionDefinition(source_definition_id=source, owner_id=AN,
        display_name='Practice burst', economy=EconomyKind.ACTION, resolution_kind='TYPED',
        target_kind='CELL', range_ft=60, radius_ft=10,
        parameters={'expected_damage': 8, 'typed': {'area': {'shape': 'sphere', 'size_ft': 10},
                    'effects': [{'type': 'damage', 'dice': {'count': 1, 'sides': 6}}]}})
    e.state.actors[AN].action_ids += (source,)
    context = _context(e)
    areas = [c for c in context.legal_candidates if c.source_definition_id == source]
    safe = next(c for c in areas if c.destination == Position(x=4, y=6))
    unsafe = next(c for c in areas if c.destination == Position(x=6, y=6))
    # Damaging a neutral is collateral, never additional enemy-damage value.
    assert unsafe.metadata['expected_damage'] == safe.metadata['expected_damage']
    assert unsafe.metadata['nonenemy_area_count'] == 1
    assert 'nonenemy_area_count' not in safe.metadata
    controller = LocalDeterministicController()
    assert controller._score_candidate(context, unsafe, ()).total < controller._score_candidate(context, safe, ()).total


def test_factory_request_accepts_neutral_group():
    from app.models import CombatFactoryMatchRequest
    body = CombatFactoryMatchRequest(project_ids=['left'], neutral_actor_ids=[AN])
    assert body.model_dump()['neutral_actor_ids'] == [AN]
