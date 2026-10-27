"""Pin the live preview merge: identical typed context and mode guard."""
import pytest

from combat.canonical import canonical_bytes
from combat.gate4_models import DecisionContext
from combat.gate5_service import CombatServiceError
from tests.test_tabletop_speed import _fight, _to_the_humans_turn


@pytest.mark.parametrize('mode,controller_preview', [
    ('MANUAL', False), ('MANUAL', True), ('LOCAL_AUTO', True),
])
def test_preview_native_context_matches_public_decision(tmp_path, monkeypatch, mode, controller_preview):
    combat, table, mid = _fight(tmp_path, seed='SOL177R4-PREVIEW')
    state, _ = _to_the_humans_turn(table, mid)
    combat.set_controller_mode(mid, actor_id=state['menu']['actor_id'], controller_mode=mode)
    session = combat._load_session(mid)
    expected = DecisionContext.model_validate(combat.decision(mid, session=session)['context'])
    native = combat._decision_model(session)
    assert native == expected
    chosen = next(c for c in expected.legal_candidates if c.kind.value == 'END_TURN')
    payload = dict(intent_id='sol177r4:preview', candidate_id=chosen.candidate_id,
                   decision_id=expected.decision_id, state_version=expected.state_version,
                   actor_id=chosen.actor_id, target_ids=list(chosen.target_ids),
                   destination=None, option_ids=[])
    original = combat._intent_from_payload
    seen = []
    def checked(context, *args, **kwargs):
        assert context == expected
        seen.append(context)
        return original(context, *args, **kwargs)
    monkeypatch.setattr(combat, '_intent_from_payload', checked)
    before = canonical_bytes(session.engine.state.model_dump(mode='json'))
    result = combat.preview(mid, payload, [], controller_preview=controller_preview)
    assert seen and result['status'] == 'PREVIEW_COMPLETE'
    assert result['authoritative_state_unchanged'] is True
    assert canonical_bytes(combat._load_session(mid).engine.state.model_dump(mode='json')) == before


def test_browser_preview_still_rejects_automatic_actor(tmp_path):
    combat, table, mid = _fight(tmp_path, seed='SOL177R4-GUARD')
    state, _ = _to_the_humans_turn(table, mid)
    combat.set_controller_mode(mid, actor_id=state['menu']['actor_id'], controller_mode='LOCAL_AUTO')
    with pytest.raises(CombatServiceError, match='automatic controller') as rejected:
        combat.preview(mid, {}, [])
    assert rejected.value.diagnostic.code == 'COMBAT_CONTROLLER_MODE_MISMATCH'
