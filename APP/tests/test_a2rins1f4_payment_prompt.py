"""Menu discovery must expose optional payments without canceling the technique."""
import pytest

from combat.gate5_service import CombatServiceError
from tests.test_a2r_battle_musician import _owner_bundle, HEALING_HYMN, STAMINA, QI
from tests.test_r9i_karma_persistence import act
from tests.worker2_support import OWNER, candidate, fixture, reload, settle


@pytest.mark.parametrize('accept', [True, False])
def test_optional_stamina_payment_waits_for_player_before_any_commit(tmp_path, accept):
    combat, table, mid = fixture(tmp_path, [HEALING_HYMN],
                                owner_bundle=_owner_bundle([HEALING_HYMN], qi=1, stamina=10))
    before = reload(tmp_path, mid)
    source = candidate(combat, mid, 'Healing Hymn').candidate_id
    result = act(table, mid, source)
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    assert prompt['context']['reaction_source_id'] == 'choice:alternative_payment'
    text = str(prompt)
    assert 'Battle Musician' in text and 'Healing Hymn' in text and 'Stamina' in text
    assert prompt['choice']['options']
    pending = reload(tmp_path, mid)
    assert pending.state.actors[OWNER].resources == before.state.actors[OWNER].resources
    assert len(pending.events) == len(before.events)
    if accept:
        settle(table, mid, source, picks={'choice:alternative_payment': 'first'})
        after = reload(tmp_path, mid)
        owner = after.state.actors[OWNER]
        assert owner.resources[QI] == 1 and owner.resources[STAMINA] == 6
        paid = [e for e in after.events if e.event_type == 'ALTERNATIVE_PAYMENT_COMMITTED']
        assert len(paid) == 1
        assert paid[0].payload['resources_paid'][STAMINA] == 4
    else:
        answer = {**prompt['context'], 'selection': 'DECLINE'}
        with pytest.raises(CombatServiceError, match='canceled; no payment') as rejected:
            act(table, mid, source, [answer])
        assert rejected.value.diagnostic.details['underlying_code'] == 'GATE2_PAYMENT_DECLINED'
        after = reload(tmp_path, mid)
        assert after.state.actors[OWNER].resources == before.state.actors[OWNER].resources
        assert len(after.events) == len(before.events)
