"""Pair recipient parity and actual generic-reaction profile queries at the table."""
from copy import deepcopy

import pytest

from combat import ext
from combat.attack_declaration import can_target
from combat.gate2_runtime_models import ActionDefinition, EconomyKind, Position
from combat.gate5_service import CombatService
from combat.recipients import allowed
from tests.test_auto_tabik import _engine, ME, AN
from tests.test_lock_choices import install
from tests.test_lock2_persistence import ROOT, table_match, act


def pair_engine():
    engine, _ = _engine([], foe_at=(4, 6))
    actor = engine.state.actors[ME]
    for name, pos in [('paired', (4, 7)), ('third', (3, 7))]:
        engine.state.actors[name] = engine.state.actors[AN].model_copy(deep=True,
            update={'entity_id': name, 'position': Position(x=pos[0], y=pos[1])})
        engine.actor_footprints[name] = engine.actor_footprints[AN]
    action = ActionDefinition(source_definition_id='test:following', display_name='Following Strike', owner_id=ME,
        economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='HOSTILE_ENTITY', range_ft=5,
        parameters={'following_strike': True, 'requires_turn_flag': 'pair:paired_strike_done',
                    'typed': {'effects': [{'type': 'attack', 'no_damage': True}], 'numbers': {}}})
    engine.action_catalog[action.source_definition_id] = action
    actor.action_ids += (action.source_definition_id,)
    actor.turn_flags.update({'pair:paired_strike_done': True, 'pair:paired_target': 'paired', 'pair:lead_targets': ['third']})
    return engine, actor, action


@pytest.mark.parametrize('leads,expected', [(['third'], {AN}), ([AN], {'third'}), (['paired'], set()),
                                          ([AN, 'third'], {AN, 'third'}), ([], set())])
def test_pair_menu_and_recipient_query_use_one_predicate(leads, expected):
    engine, actor, action = pair_engine()
    actor.turn_flags['pair:lead_targets'] = leads
    queried = {tid for tid, target in engine.state.actors.items()
               if can_target(engine, actor, target, action.source_definition_id)}
    menu = {c.target_ids[0] for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id}
    assert queried == menu == expected
    before = engine.state.model_dump(mode='json'), list(engine.events), list(engine.rolls)
    for target in engine.state.actors.values():
        assert allowed(engine, actor, target, action) == can_target(engine, actor, target, action.source_definition_id)
    assert (engine.state.model_dump(mode='json'), engine.events, engine.rolls) == before


def test_recipient_legality_is_independent_of_activation_and_nonpair_actions():
    engine, actor, action = pair_engine()
    target = engine.state.actors[AN]
    actor.action_available = False
    actor.turn_flags.pop('pair:paired_strike_done')
    expensive = action.model_copy(update={'costs': (('resource:core.cp', 9999),)})
    assert allowed(engine, actor, target, expensive)
    assert not engine._action_candidates(actor, expensive)
    ordinary = action.model_copy(update={'parameters': {}})
    assert allowed(engine, actor, engine.state.actors['paired'], ordinary)


def test_unknown_reaction_requires_actual_profile_and_explicit_range():
    engine, actor, _ = pair_engine()
    target = engine.state.actors[AN]
    assert not can_target(engine, actor, target, 'unknown:reaction')
    profile = {'effects': [{'type': 'attack'}]}
    with pytest.raises(ValueError, match='actual range'):
        can_target(engine, actor, target, 'unknown:reaction', typed_profile=profile)
    assert can_target(engine, actor, target, 'unknown:reaction', typed_profile=profile, range_ft=5)
    assert not can_target(engine, actor, target, 'unknown:reaction', typed_profile=profile, range_ft=0)


@pytest.mark.parametrize('restriction', ['charmed', 'range', 'inactive', 'hearing', 'condition'])
def test_shared_recipient_query_keeps_native_restrictions(restriction):
    engine, actor, action = pair_engine()
    target = engine.state.actors[AN]
    if restriction == 'charmed':
        engine._apply_condition(actor, 'condition:typed.charmed', 'test:charm', target.entity_id, expires_on='START_OF_SELF_NEXT_TURN')
    elif restriction == 'range':
        target.position = Position(x=15, y=6)
    elif restriction == 'inactive':
        target.active = False
    elif restriction == 'hearing':
        action = action.model_copy(update={'parameters': {'typed': {'requires_hearing': True}}})
        engine._apply_condition(target, 'condition:typed.deafened', 'test:deaf', actor.entity_id, expires_on='START_OF_SELF_NEXT_TURN')
    else:
        action = action.model_copy(update={'parameters': {'target_requires_condition': 'condition:test.required'}})
    assert not allowed(engine, actor, target, action)
    assert not engine._action_candidates(actor, action) or all(AN not in c.target_ids for c in engine._action_candidates(actor, action))


def test_generic_reaction_query_uses_actual_profile_for_owned_bar_at_table(monkeypatch, tmp_path):
    """The C2c mismatch: catalog SELF activation has no attack effects, the real reaction does."""
    source = 'test:generic-reaction'
    profile = {'effects': [{'type': 'attack', 'attack_kind': 'weapon', 'no_damage': True}], 'numbers': {}}
    def actions(info):
        return [ActionDefinition(source_definition_id=source + ':' + info['actor_id'], display_name='Counterattack',
            owner_id=info['actor_id'], economy=EconomyKind.REACTION, resolution_kind='TYPED', target_kind='SELF',
            parameters={'typed': {'effects': [], 'numbers': info['numbers']}})]
    install(monkeypatch, 'compile_actions', actions)
    def bar(e, actor, target, action):
        barred = any(c.condition_id == 'condition:test.creature_bar' and c.source_actor_id == target.entity_id
                     for c in actor.conditions.values())
        if barred and any(effect.get('type') == 'attack' for effect in (action.parameters.get('typed') or {}).get('effects', [])):
            return False
    # Preserve Pair's real provider while adding this representative owned restriction.
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'recipient_allowed', [*ext._HOOKS.get('recipient_allowed', []), bar])
    service, table, mid = table_match(tmp_path)
    results = []
    def query(e, event_type, kwargs):
        if event_type != 'HOLD_POSITION_COMMITTED':
            return
        actor = e.state.actors[e.state.current_actor_id]
        target = next(a for a in e.state.actors.values() if a.team_id != actor.team_id)
        sid = source + ':' + actor.entity_id
        action_before, profile_before = e.action_catalog[sid].model_dump(mode='json'), deepcopy(profile)
        e._apply_condition(actor, 'condition:test.creature_bar', 'test:beauty', target.entity_id,
                           expires_on='START_OF_SELF_NEXT_TURN')
        eligible = can_target(e, actor, target, sid, typed_profile=profile, range_ft=5)
        results.append(eligible)
        assert not eligible
        assert e.action_catalog[sid].model_dump(mode='json') == action_before and profile == profile_before
        if eligible:
            e._commit_damage(actor, 3, 'PSYCHIC', 'test:challenge', target.entity_id, e._active_intent, reaction_depth=1)
        e._append_event('PASSIVE_TRIGGERED', 'test:query', actor_id=actor.entity_id,
                        payload={'eligible': eligible, 'log': 'The protected creature cannot be chosen for this counterattack.'})
    install(monkeypatch, 'event', query)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert results and not any(results)
    assert any(e.event_type == 'PASSIVE_TRIGGERED' and e.source_definition_id == 'test:query' for e in loaded.engine.events)
    assert not any(e.event_type == 'DAMAGE_COMMITTED' and e.source_definition_id == 'test:challenge' for e in loaded.engine.events)
    assert loaded.verify()['status'] == 'PASS'
    actor = loaded.engine.state.actors[loaded.engine.state.current_actor_id]
    target = next(a for a in loaded.engine.state.actors.values() if a.team_id != actor.team_id)
    assert not can_target(loaded.engine, actor, target, source + ':' + actor.entity_id, typed_profile=profile, range_ft=5)


def test_recipient_veto_is_shared_by_real_table_menu(monkeypatch, tmp_path):
    service, table, mid = table_match(tmp_path)
    def barred(e, actor, target, action):
        if any(c.condition_id == 'condition:test.creature_bar' and c.source_actor_id == target.entity_id
               for c in actor.conditions.values()):
            return False
    install(monkeypatch, 'recipient_allowed', barred)
    def mark(e, event_type, kwargs):
        if event_type == 'HOLD_POSITION_COMMITTED':
            actor = e.state.actors[e.state.current_actor_id]
            target = next(a for a in e.state.actors.values() if a.team_id != actor.team_id)
            e._apply_condition(actor, 'condition:test.creature_bar', 'test:bar', target.entity_id,
                               expires_on='START_OF_SELF_NEXT_TURN')
    install(monkeypatch, 'event', mark)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[loaded.engine.state.current_actor_id]
    target = next(a for a in loaded.engine.state.actors.values() if a.team_id != actor.team_id)
    assert not any(target.entity_id in c.target_ids for c in loaded.engine.legal_candidates())
    assert loaded.verify()['status'] == 'PASS'
