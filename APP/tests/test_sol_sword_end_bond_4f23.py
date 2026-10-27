"""Real sword bonds terminate through committed journey state for owner and borrower."""
import pytest

from combat.ext import ten_thousand_swords as swords
from tests.test_mgr_t14_sword_round11_table import A, B, native, _admission, _permission


@pytest.mark.parametrize('owner,actor_id', [('sword-owner', A), ('sword-lender', B)])
def test_end_real_bond_survives_reload(tmp_path, monkeypatch, owner, actor_id):
    cold, jid, uid, acquire = native(tmp_path, monkeypatch, seeds=0, real_sword_owner=owner)
    _admission(cold, jid, uid)
    if actor_id == B:
        _permission(cold, jid, uid)
    acquire(swords.SEED, {'slot': 0, 'form': 'real', 'damage_type': 'force',
                          'item_uid': uid, 'owner_id': actor_id, 'admission_scope': 'real-sword'})
    result = acquire(swords.SEED, {'end_bond': 1})
    assert result['actors'][A]['source_states'][swords.FAMILY]['swords'] == []
    assert cold().journey_state(jid)['actors'][A]['source_states'][swords.FAMILY]['swords'] == []
