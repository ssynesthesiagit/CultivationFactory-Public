"""Non-Reaction save benefits survive reaction-only denial through Table/reload."""
import pytest

from combat.activation_payments import reaction_completed
from combat.gate5_service import CombatService
from tests import test_tabletop_hunt6 as H
from tests.h1_support import ROOT, sheet, script, duel, ME
from tests.r10_fixup_support import cast_sender

TEMPERED = 'tianxia.path.body_refining.feature.tempered_response'
CP = 'resource:core.stamina'


def test_tempered_response_under_flustered_pays_once_and_rescues_save(monkeypatch, tmp_path):
    monkeypatch.setattr(H, 'sheet', lambda owned, **kw: sheet(owned, primary='Stamina', **kw))
    service, table, mid = H.table_fight(tmp_path, [TEMPERED], ask=True)
    def save(engine):
        actor = engine.state.actors[H.LEFT]
        engine._apply_condition(actor, 'condition:typed.flustered', 'test:fluster', H.RIGHT,
                                expires_on='UNTIL_REMOVED')
        row = next(r for r in engine.typed_reaction_rows[H.LEFT] if r['feature_id'] == TEMPERED)
        ability = row['abilities'][0]
        script(engine, [10])
        dc = 11 + actor.saving_throws.get(ability, 0)
        passed = engine._roll_save(actor, ability, dc, 'test:tempered_save').total >= dc
        engine._append_event('PASSIVE_TRIGGERED', 'test:save_result', actor_id=H.LEFT,
                             payload={'passed': passed})
    H.on_hold(monkeypatch, save)
    before = service._load_session(mid).engine.state.model_dump(mode='json')
    send = cast_sender(service, table, mid, 'Hold')
    # This native non-Reaction rescue uses the existing automatic benefit path.
    assert send()['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    e, actor = loaded.engine, loaded.engine.state.actors[H.LEFT]
    assert actor.resources[CP] == before['actors'][H.LEFT]['resources'][CP] - 1
    assert actor.reaction_available
    assert actor.turn_flags['typed_rescue_round:' + TEMPERED] == e.state.round_number
    assert any(ev.source_definition_id == 'test:save_result' and ev.payload['passed'] for ev in e.events)
    assert not any('cannot finish' in ev.payload.get('log', '') for ev in e.events)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('condition,consumes,allowed', [
    ('flustered', False, True), ('flustered', True, False),
    ('incapacitated', False, False), ('incapacitated', True, False)])
def test_payment_guard_distinguishes_reaction_denial_from_incapacitation(condition, consumes, allowed):
    e = duel([])
    actor = e.state.actors[ME]
    e._apply_condition(actor, 'condition:typed.' + condition, 'test:condition', ME,
                       expires_on='UNTIL_REMOVED')
    assert reaction_completed(e, actor, 'test:payment', consumes_reaction=consumes) is allowed
    if not allowed:
        assert ('reaction' if consumes else 'benefit') in e.events[-1].payload['log']
