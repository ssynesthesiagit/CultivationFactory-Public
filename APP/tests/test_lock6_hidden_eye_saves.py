"""Identify Rhythms shares native, typed and Concentration save modifiers."""
import pytest

from combat.ext.mind_hidden_eye import ANALYZED, FOCUS
from combat.gate5_service import CombatService
from tests.test_auto_lane4 import _duel, ME, SUBJ
from tests.test_hidden_targeting import LEFT, RIGHT, ROOT, table_fight, turn
from tests.test_lock2_persistence import act
from tests.test_lock_choices import install

TALENT = 'TAL_THE_HIDDEN_EYE_IDENTIFY_RHYTHMS'


@pytest.mark.parametrize('owns,analyzed,focus,known', [
    (True, True, 1, True), (False, True, 1, True), (True, False, 1, True),
    (True, True, 0, True), (True, True, 1, False)])
def test_native_save_has_owned_source_bound_bonus_without_changing_dc(owns, analyzed, focus, known):
    engine = _duel([TALENT] if owns else [])
    subject, source = engine.state.actors[SUBJ], engine.state.actors[ME]
    if analyzed:
        engine._apply_condition(source, ANALYZED, 'test:analyze', SUBJ, expires_on='UNTIL_REMOVED')
    subject.resources[FOCUS] = focus
    roll = engine._roll_save(subject, 'CON', 17, 'test:native-effect',
        roll_context={'source_actor_id': ME} if known else None)
    expected = subject.proficiency_bonus // 2 if owns and analyzed and focus and known else 0
    assert roll.modifier == subject.saving_throws['CON'] + expected
    event = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED')
    assert event.payload['dc'] == 17


def test_legacy_action_owner_supplies_known_source_without_current_turn_guess():
    engine = _duel([TALENT])
    subject = engine.state.actors[SUBJ]
    engine._apply_condition(engine.state.actors[ME], ANALYZED, 'test:analyze', SUBJ, expires_on='UNTIL_REMOVED')
    subject.resources[FOCUS] = 1
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME)
    engine.state.current_actor_id = SUBJ
    roll = engine._roll_save(subject, 'CON', 17, action.source_definition_id)
    assert roll.modifier == subject.saving_throws['CON'] + subject.proficiency_bonus // 2


def test_identify_rhythms_concentration_source_survives_table_commit_reload_and_replay(monkeypatch, tmp_path):
    def prepare_and_damage(engine, kind, kwargs):
        if kind != 'HOLD_POSITION_COMMITTED' or kwargs['actor_id'] != LEFT:
            return
        defender, attacker = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        engine._apply_condition(attacker, ANALYZED, 'test:analyze', LEFT, expires_on='UNTIL_REMOVED')
        engine._start_concentration(defender, 'test:concentration')
        # Non-attack damage on the defender's own turn: the source is the other
        # creature, not the current actor or a guessed most-recent attack.
        engine._commit_damage(defender, 1, 'UNTYPED', 'test:hazard', RIGHT, None, reaction_depth=0)
    install(monkeypatch, 'event', prepare_and_damage)
    combat, table, mid = table_fight(tmp_path, left_abilities=(TALENT,))
    turn(table, mid, LEFT)
    assert combat._load_session(mid).engine.state.actors[LEFT].resources[FOCUS] == 1
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    subject = loaded.engine.state.actors[LEFT]
    event = next(e for e in loaded.engine.events if e.event_type == 'SAVE_ROLLED'
                 and e.source_definition_id == 'system:combat.concentration')
    assert event.payload['dc'] == 10
    assert event.payload['modifier'] == subject.saving_throws['CON'] + subject.proficiency_bonus // 2
    assert subject.resources[FOCUS] == 1
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
