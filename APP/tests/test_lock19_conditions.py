"""Review regressions at accepted Table and plain Gate3 journal boundaries."""
import pytest

from combat import typed_executor, unmaking
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_models import ActionIntent
from combat.gate3_storage import Gate3Persistence
from combat.gate5_service import CombatService
from combat.target_knowledge import can_see
from tests import test_tabletop_hunt6 as H
from tests.h1_support import ROOT, script
from tests.test_lock2_persistence import act


def test_last_inch_control_is_a_save_with_visible_frightened_source(monkeypatch, tmp_path):
    def trigger(engine):
        actor, source = engine.state.actors[H.LEFT], engine.state.actors[H.RIGHT]
        engine._apply_condition(actor, 'condition:typed.frightened', H.HOLD, H.RIGHT,
                                expires_on='UNTIL_REMOVED')
        assert can_see(engine, actor, source)
        assert typed_executor.check_mode(actor, 'CON', engine=engine) == 'DISADVANTAGE'
        action = next(a for a in engine.action_catalog.values() if a.owner_id == H.LEFT)
        ctx = typed_executor.Context(engine, actor, action, engine._active_intent,
                                     {'numbers': {'save_dc': 15, 'pb': 5}}, [actor], actor)
        script(engine, [19, 1])
        unmaking.gain_strain_checked(ctx, 1, H.HOLD)

    combat, table, mid = H.table_fight(tmp_path, ['TAL_UNMAKING_LAST_INCH_CONTROL'], ally_talents=[])
    H.on_hold(monkeypatch, trigger)
    pending = act(table, mid, H.HOLD)
    assert pending['status'] == 'REACTION_REQUIRED'
    prompt = pending['reaction']
    assert prompt['context']['reaction_source_id'] == 'choice:needle.last_inch_control'
    state, menu = pending['state'], pending['state']['menu']
    cid = next(g['options'][0]['candidate_id'] for g in menu['actions']
               if g['source_definition_id'] == H.HOLD)
    answer = {**prompt['context'], 'selection': 'USE', 'option_ids': ['roll']}
    assert table.act(mid, cid, menu['decision_id'], menu['state_version'],
                     state['last_sequence'], [answer])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state == combat._load_session(mid).engine.state
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    saves = [e for e in loaded.engine.events if e.event_type == 'SAVE_ROLLED'
             and e.source_definition_id == 'passive:TAL_UNMAKING_LAST_INCH_CONTROL']
    assert len(saves) == 1 and saves[0].payload['mode'] == 'NORMAL' and saves[0].payload['success']
    actor = loaded.engine.state.actors[H.LEFT]
    assert actor.resources[unmaking.STRAIN] == 0
    assert actor.current_hp == actor.maximum_hp - 5
    assert actor.turn_flags['last_inch_control_used']


@pytest.mark.parametrize('cause', ['incapacitated', 'speed_modifier'])
def test_plain_gate3_dodge_forfeiture_survives_recovery_reload_and_replay(monkeypatch, tmp_path, cause):
    persistence = Gate3Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed='L19-DODGE')
    assert type(session.engine) is Gate2Engine
    owner = session.engine.state.current_actor_id
    dodge, restriction = 'condition:core.dodge', 'condition:typed.incapacitated'
    original = Gate2Engine._append_event

    def staged(engine, event_type, *args, **kwargs):
        event = original(engine, event_type, *args, **kwargs)
        actor = engine.state.actors[owner]
        intent = getattr(engine, '_active_intent', None)
        if event_type == 'HOLD_POSITION_COMMITTED' and intent.intent_id == 'test:loss':
            engine._apply_condition(actor, dodge, 'test:dodge', owner, expires_on='START_OF_OWNER_NEXT_TURN')
            if cause == 'incapacitated':
                engine._apply_condition(actor, restriction, 'test:restriction', owner, expires_on='UNTIL_REMOVED')
            else:
                engine._add_modifier(actor, 'test:restriction', 'speed_ft', 'ADD', -100, 'SELF', expires_on='UNTIL_REMOVED')
        if event_type == 'TURN_ENDED' and intent.intent_id == 'test:recovery':
            if cause == 'incapacitated':
                engine._remove_condition(actor, restriction, 'test:recovery')
            else:
                for key, modifier in list(actor.modifiers.items()):
                    if modifier.source_definition_id == 'test:restriction':
                        del actor.modifiers[key]
                        engine._append_event('MODIFIER_REMOVED', 'test:recovery', actor_id=owner,
                                             target_ids=(owner,), payload={'modifier_id': key})
        return event

    monkeypatch.setattr(Gate2Engine, '_append_event', staged)
    for source, identity in [(H.HOLD, 'test:loss'), ('end', 'test:recovery')]:
        candidate = next(c for c in session.engine.legal_candidates()
                         if (c.kind == 'END_TURN' if source == 'end' else c.source_definition_id == source))
        session.execute_intent(ActionIntent(intent_id=identity, decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version,
            actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination))
        loaded = Gate3Persistence(ROOT, tmp_path).load_match(session.match_id)
        assert type(loaded.engine) is Gate2Engine
        assert loaded.engine.state == session.engine.state
        assert loaded.verify()['status'] == loaded.replay()['status'] == 'PASS'
        assert not any(c.condition_id == dodge for c in loaded.engine.state.actors[owner].conditions.values())
        session = loaded
    actor = session.engine.state.actors[owner]
    assert session.engine._effective_speed(actor) > 0
    assert not any(c.condition_id == restriction for c in actor.conditions.values())
    removed = [e for e in session.engine.events if e.event_type == 'CONDITION_REMOVED'
               and e.payload.get('condition_id') == dodge]
    assert len(removed) == 1


def test_native_lifecycle_recursion_is_bounded_and_transaction_rolls_back(monkeypatch):
    from tests.test_lock_choices import install
    engine = Gate2Engine(ROOT, match_seed='L19-STATE-EVENT-LIMIT')
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == H.HOLD)
    before = engine.state.model_dump(mode='json'), list(engine.events), list(engine.rolls)
    def recurse(e, event):
        e._append_event('PASSIVE_TRIGGERED', 'test:loop')
    install(monkeypatch, 'state_event', recurse)
    with pytest.raises(ValueError, match='repeated too many times'):
        engine.execute_intent(ActionIntent(intent_id='test:recursion', decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version,
            actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination))
    assert before == (engine.state.model_dump(mode='json'), engine.events, engine.rolls)
    assert engine._state_event_depth == 0
