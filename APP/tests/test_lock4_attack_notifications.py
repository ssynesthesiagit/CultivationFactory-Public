"""Legacy and typed attack outcomes each notify once after settling the attack."""
from dataclasses import FrozenInstanceError

import pytest

from combat.gate2_runtime_content import BASIC_MELEE
from combat.typed_executor import Context, block_attack
from tests.test_auto_tabik import _engine, ME, AN
from tests.test_lock_choices import install, intent
from tests.test_c3ar_runtime_executability import (
    adapter, bundle, runtime_package, runtime_engine, req, SOURCE_ACTOR_ID,
)


@pytest.mark.parametrize('hit', [True, False])
@pytest.mark.parametrize('opportunity', [True, False])
def test_legacy_outcomes_notify_once_with_read_only_notice_and_ignore_returns(monkeypatch, hit, opportunity):
    engine, _ = _engine([], foe_at=(4, 6), seed='LOCK4-NOTICE')
    attacker, defender = engine.state.actors[AN], engine.state.actors[ME]
    defender.armor_class = 0 if hit else 1000
    seen = []

    def observe(ctx, target, *args):
        seen.append((ctx, target, args))
        with pytest.raises(FrozenInstanceError):
            ctx.attack_notice.hit = not hit
        ctx.action.parameters['notification_copy'] = True
        return not hit  # a notification does not override the settled attack

    install(monkeypatch, 'after_hit', observe)
    install(monkeypatch, 'after_miss', observe)
    action = engine.action_catalog['action:an_eui.paired_bi_shou_assault']
    request = intent(engine)
    if opportunity:
        result = engine._resolve_attack_spec(attacker, defender, dict(BASIC_MELEE[AN]), request,
            source_definition_id='system:combat.opportunity_attack', reaction_depth=1)
    else:
        result = engine._resolve_attack_action(attacker, defender, action, request)
    assert result is hit
    assert len(seen) == 1
    ctx, target, args = seen[0]
    assert target is defender and ctx.actor is attacker
    assert ctx.attack_notice.hit is hit and ctx.attack_notice.melee
    assert ctx.attack_notice.attacker_id == AN and ctx.attack_notice.target_id == ME
    assert 'notification_copy' not in action.parameters


def test_typed_attack_keeps_its_existing_single_notification(monkeypatch):
    engine, _ = _engine([], foe_at=(4, 6), seed='LOCK4-NOTICE')
    target = engine.state.actors[AN]
    target.armor_class = 0
    seen = []
    install(monkeypatch, 'after_hit', lambda *args: seen.append('hit'))
    install(monkeypatch, 'after_miss', lambda *args: seen.append('miss'))
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and (a.parameters.get('typed') or {}).get('weapon'))
    ctx = Context(engine, engine.state.actors[ME], action, intent(engine), action.parameters['typed'], [target], target)
    block_attack(ctx, {'type': 'attack', 'attack_kind': 'weapon', 'no_damage': True})
    assert seen == ['hit']


@pytest.mark.parametrize('action_id,damage_type', [
    ('action:core.unarmed_strike', 'BLUDGEONING'),
    ('action:fire.flame_lash', 'FIRE'),
    ('action:fire.ignite', 'FIRE'),
    ('reaction:core.opportunity_attack', 'BLUDGEONING'),
])
@pytest.mark.parametrize('resistant', [False, True])
def test_portable_landed_attacks_damage_notify_and_replay(monkeypatch, bundle, action_id, damage_type, resistant):
    from combat.canonical import canonical_sha256
    from combat.damage_context import AttackDamage
    from combat.gate2_runtime_models import ActionIntent, CandidateKind, LegalCandidate, Position, ReactionDecision, MatchState
    from combat.gate3_reducer import Gate3EventReducer, enrich_committed_events

    opportunity = action_id == 'reaction:core.opportunity_attack'
    attacker_id, target_id = ('dummy:target', SOURCE_ACTOR_ID) if opportunity else (SOURCE_ACTOR_ID, 'dummy:target')
    seen = []
    packets = []
    install(monkeypatch, 'after_hit', lambda ctx, target, kind: seen.append((ctx.attack_notice, target.entity_id)))
    install(monkeypatch, 'after_miss', lambda *args: pytest.fail('expected a landed attack'))
    install(monkeypatch, 'final_damage', lambda e, target, *args: packets.append(e.damage_context()))

    def run():
        engine = runtime_engine(bundle, seed='LOCK4-PORTABLE',
            target_reactions=('reaction:core.opportunity_attack',) if opportunity else ())
        target = engine.state.actors[target_id]
        target.armor_class = 0
        target.damage_resistances = (damage_type,) if resistant else ()
        genesis = engine.state.model_copy(deep=True)
        before = target.current_hp
        if opportunity:
            mover = engine.state.actors[SOURCE_ACTOR_ID]
            destination = Position(x=2, y=4)
            path, cost = engine.grid.shortest_path(mover.position, destination,
                occupied_cells=engine._occupied_cells_except(mover.entity_id), max_cost_ft=30,
                footprint=engine._footprint(mover))
            candidate = LegalCandidate(candidate_id='candidate:leave', decision_id='decision:leave',
                state_version=engine.state.state_version, kind=CandidateKind.MOVE, actor_id=mover.entity_id,
                source_definition_id='system:combat.move', display_name='Move', destination=destination,
                canonical_path=path, movement_cost_ft=cost)
            request = ActionIntent(intent_id='intent:leave', decision_id=candidate.decision_id,
                candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=mover.entity_id,
                destination=destination, reaction_decisions=(ReactionDecision(checkpoint='LEAVE_REACH',
                    reactor_id=attacker_id, reaction_source_id=action_id, selection='USE'),))
            engine._active_intent = request
            try:
                with engine._transaction('system:combat.move', request.intent_id, mover.entity_id):
                    engine._resolve_movement(mover, candidate, request)
            finally:
                engine._active_intent = None
            assert not engine.state.actors[attacker_id].reaction_available
            assert any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == action_id for e in engine.events)
        else:
            options = {'action:fire.flame_lash': ('NO_MOVEMENT',),
                'action:fire.ignite': ('INCREASE_BURN',)}.get(action_id, ())
            engine.execute_action(req(action_id, target_id=target_id, option_ids=options))
        damage = next(e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.source_definition_id == action_id)
        assert before - target.current_hp == damage.payload['hp_damage'] > 0
        if action_id in {'action:core.unarmed_strike', 'reaction:core.opportunity_attack'}:
            assert damage.payload['hp_damage'] == (1 if resistant else 2)
        if resistant:
            resistance = next(e for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED'
                and e.source_definition_id == 'passive:cinder.fire_resistance')
            assert resistance.payload['after'] == resistance.payload['before'] // 2
            assert damage.payload['hp_damage'] == resistance.payload['after']
        assert engine.damage_context() is None
        # The portable harness has no match persistence; verify its committed
        # events through the production reducer and the saved-state JSON schema.
        replayed = Gate3EventReducer().apply_events(genesis,
            enrich_committed_events(engine.events, post_engine=engine), expected_start_sequence=1)
        replayed.state_version = engine.state.state_version
        replayed.roll_counter = engine.state.roll_counter
        reloaded = MatchState.model_validate_json(replayed.model_dump_json())
        assert canonical_sha256(reloaded.model_dump(mode='json')) == canonical_sha256(engine.state.model_dump(mode='json'))
        return engine

    first, second = run(), run()
    assert [e.model_dump(mode='json') for e in first.events] == [e.model_dump(mode='json') for e in second.events]
    assert first.state == second.state
    assert len(seen) == len(packets) == 2
    roll = next(e for e in first.events if e.event_type == 'ATTACK_ROLLED')
    provenance = packets[0]
    assert isinstance(provenance, AttackDamage) and packets[1] == provenance
    assert (provenance.source_id, provenance.attacker_id, provenance.target_id, provenance.attack_index) == (action_id, attacker_id, target_id, 1)
    assert (provenance.roll_id, provenance.natural_result, provenance.total, provenance.critical) == (
        roll.payload['roll_id'], roll.payload['natural_result'], roll.payload['total'], roll.payload['natural_result'] == 20)
    for notice, notified_target in seen:
        assert notice.hit and notified_target == target_id
        assert (notice.source_id, notice.attacker_id, notice.target_id) == (action_id, attacker_id, target_id)
        assert notice.roll_id == roll.payload['roll_id']
        assert notice.melee == (action_id in {'action:core.unarmed_strike', 'reaction:core.opportunity_attack'})


def test_portable_miss_notifies_without_damage(monkeypatch, bundle):
    engine = runtime_engine(bundle, seed='LOCK4-PORTABLE')
    engine.state.actors['dummy:target'].armor_class = 1000
    seen = []
    install(monkeypatch, 'after_hit', lambda *args: pytest.fail('expected a miss'))
    install(monkeypatch, 'after_miss', lambda ctx, target: seen.append(ctx.attack_notice.hit))
    before = engine.state.actors['dummy:target'].current_hp
    engine.execute_action(req('action:core.unarmed_strike', target_id='dummy:target'))
    assert seen == [False]
    assert engine.state.actors['dummy:target'].current_hp == before
    assert not any(e.event_type == 'DAMAGE_COMMITTED' for e in engine.events)
