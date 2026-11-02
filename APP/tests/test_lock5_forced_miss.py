"""A forced outcome beats a natural20, using native defenders and real table choices."""
import pytest

from combat.choice_checkpoints import dynamic_choice
from combat.gate2_runtime_models import DiceSpec
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.test_lock_choices import install, intent
from tests.test_lock2_persistence import ROOT, act
from tests.test_auto_tabik import _engine, ME, AN

SOURCE = 'test:sleeve-rebuke'
ATTACK = 'test:opportunity-attack'


@pytest.mark.parametrize('natural,selection', [(20, 'USE'), (20, 'DECLINE'), (10, 'USE')])
def test_manual_rebuke_forces_native_miss_without_ac_hack_and_replays(monkeypatch, tmp_path, natural, selection):
    from tests.test_lock2_persistence import _install
    from tests.test_hidden_targeting import turn
    _install(tmp_path, 'left')
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({'display_name': 'Forced miss yard', 'width_squares': 12, 'height_squares': 8,
                               'walls': [], 'starts': {'team1': [[3, 4]], 'team2': [[4, 4]]}})
    attacker_id = FACTORY_ACTOR_PREFIX + 'left'
    mid = service.create_factory_match(project_ids=['left'], opponent_actor_ids=[AN], match_seed='lock5-rebuke',
        arena_id='battlefield:map.forced-miss-yard', control_modes={attacker_id: 'MANUAL', AN: 'MANUAL'})['match_id']
    table = TabletopService(service, tmp_path)
    turn(table, mid, attacker_id)
    engine = service._load_session(mid).engine
    attacker_id = engine.state.current_actor_id
    defender_id = next(a.entity_id for a in engine.state.actors.values()
                       if a.primary_combatant and a.team_id != engine.state.actors[attacker_id].team_id)
    assert defender_id not in engine.typed_actor_ids
    before = engine.state.model_dump(mode='json')
    install(monkeypatch, 'd20_result', lambda *args: {'source_id': 'test:die', 'operation': 'replace', 'natural_result': natural})
    def rebuke(e, attacker, defender, request, context):
        if context['source_id'] != ATTACK:
            return None
        _, choice = dynamic_choice(e, request, 'REBUKE:1', defender_id, SOURCE,
            {'name': 'Sleeve-Pulling Rebuke', 'actor_id': attacker_id, 'target_id': defender_id,
             'prompt': f'{attacker.display_name} attacks {defender.display_name}. Use Sleeve-Pulling Rebuke to make this attack miss.',
             'labels': {'rebuke': 'Make this attack miss'}},
            spec_override={'option_ids': ('rebuke',), 'automatic_use': True})
        if choice and choice.selection == 'USE':
            return {'force_miss': True, 'source_id': SOURCE, 'label': 'Sleeve-Pulling Rebuke'}
    install(monkeypatch, 'before_attack', rebuke)
    def trigger(e, event_type, kwargs):
        if event_type == 'HOLD_POSITION_COMMITTED':
            e._resolve_attack_spec(e.state.actors[attacker_id], e.state.actors[defender_id],
                {'attack_bonus': 100, 'reach_ft': 1000, 'damage': DiceSpec(count=1, sides=4), 'damage_type': 'BLUDGEONING'},
                e._active_intent, source_definition_id=ATTACK, reaction_depth=1)
    install(monkeypatch, 'event', trigger)
    first = act(table, mid, 'system:combat.hold_position')
    assert first['status'] == 'REACTION_REQUIRED'
    assert first['reaction']['context']['checkpoint'] == 'REBUKE:1'
    assert service._load_session(mid).engine.state.model_dump(mode='json') == before
    answer = {**first['reaction']['context'], 'selection': selection,
              'option_ids': ['rebuke'] if selection == 'USE' else []}
    state = table.state(mid); menu = state['menu']
    cid = next(g['options'][0]['candidate_id'] for g in menu['actions'] if g['source_definition_id'] == 'system:combat.hold_position')
    result = table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], [answer])
    if selection == 'DECLINE' and result['status'] == 'REACTION_REQUIRED':
        # Declining the rebuke leaves the defender's ordinary damage defense usable.
        defense = result['reaction']['context']
        assert defense['checkpoint'] == 'DAMAGE_APPLICATION'
        result = table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'],
                           [answer, {**defense, 'selection': 'DECLINE'}])
    assert result['status'] == 'COMMITTED', result.get('reaction', {}).get('context')
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    roll = next(e for e in loaded.engine.events if e.event_type == 'ATTACK_ROLLED' and e.source_definition_id == ATTACK)
    assert roll.payload['natural_result'] == natural and roll.payload['provisional_hit']
    forced = [e for e in loaded.engine.events if e.event_type == 'ATTACK_FORCED_MISS']
    assert len(forced) == int(selection == 'USE')
    assert loaded.engine.state.actors[defender_id].armor_class == before['actors'][defender_id]['armor_class']
    assert not any(e.event_type == 'MODIFIER_APPLIED' and e.source_definition_id == SOURCE for e in loaded.engine.events)
    if selection == 'USE':
        assert loaded.engine.state.actors[defender_id].current_hp == before['actors'][defender_id]['current_hp']
        assert not any(e.event_type == 'DAMAGE_ROLLED' and e.source_definition_id == ATTACK for e in loaded.engine.events)
        assert forced[0].payload['roll_id'] == roll.payload['roll_id']
    else:
        assert any(e.event_type == 'DAMAGE_ROLLED' and e.source_definition_id == ATTACK for e in loaded.engine.events)
    assert loaded.verify()['status'] == 'PASS'


@pytest.mark.parametrize('path', ['native', 'typed', 'portable'])
def test_forced_miss_is_one_packet_and_delivers_one_miss_for_every_path(monkeypatch, path):
    from combat.character_runtime_adapter import CharacterCombatRuntimeEngine
    from combat.typed_executor import Context, block_attack
    engine, _ = _engine([], foe_at=(4, 6))
    if path == 'portable':
        runtime = CharacterCombatRuntimeEngine.__new__(CharacterCombatRuntimeEngine)
        runtime.__dict__.update(engine.__dict__)
        engine = runtime
    actor, target = engine.state.actors[ME], engine.state.actors[AN]
    seen = []
    install(monkeypatch, 'after_hit', lambda *args: seen.append('hit'))
    install(monkeypatch, 'after_miss', lambda *args: seen.append('miss'))
    install(monkeypatch, 'd20_result', lambda *args: {'source_id': 'test:20', 'operation': 'replace', 'natural_result': 20})
    install(monkeypatch, 'before_attack', lambda *args: {'force_miss': True, 'source_id': SOURCE, 'label': 'Rebuke'})
    def attack():
        if path == 'typed':
            action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and (a.parameters.get('typed') or {}).get('weapon'))
            ctx = Context(engine, actor, action, intent(engine), action.parameters['typed'], [target], target)
            block_attack(ctx, {'type': 'attack', 'attack_kind': 'weapon', 'no_damage': True})
        elif path == 'portable':
            CharacterCombatRuntimeEngine._resolve_character_attack(engine, actor, target, source_id=ATTACK,
                attack_bonus=2, damage=None, damage_type='PIERCING', intent=intent(engine), ranged=False)
        else:
            engine._resolve_attack_spec(actor, target, {'attack_bonus': 2, 'reach_ft': 5},
                                       intent(engine), source_definition_id=ATTACK)
    attack()
    assert seen == ['miss']
    assert len([e for e in engine.events if e.event_type == 'ATTACK_FORCED_MISS']) == 1
    install(monkeypatch, 'before_attack', lambda *args: None)
    attack()
    assert seen == ['miss', 'hit']  # no flags leak the override to the next attack


def test_invalid_forced_miss_reply_rolls_back_native_transaction(monkeypatch, tmp_path):
    from combat.gate2_runtime_models import ActionIntent
    from tests.test_lock2_persistence import table_match
    service, _, mid = table_match(tmp_path)
    engine = service._load_session(mid).engine
    install(monkeypatch, 'before_attack', lambda *args: {'force_miss': True})
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == 'system:combat.hold_position')
    request = ActionIntent(intent_id='bad-miss', decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, actor_id=candidate.actor_id)
    before = engine.state.model_dump(mode='json'), list(engine.events), list(engine.rolls), engine.roller.counter
    with pytest.raises(ValueError, match='source_id and readable label'):
        with engine._transaction(ATTACK, request.intent_id, request.actor_id):
            actor = engine.state.actors[request.actor_id]
            target = next(a for a in engine.state.actors.values() if a.team_id != actor.team_id)
            engine._resolve_attack_spec(actor, target, {'attack_bonus': 100, 'reach_ft': 5}, request, source_definition_id=ATTACK)
    assert (engine.state.model_dump(mode='json'), engine.events, engine.rolls, engine.roller.counter) == before
