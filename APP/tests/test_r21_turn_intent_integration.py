"""C4 riders use round20's native intent through saved table actions."""
import pytest

from combat.canonical import canonical_sha256
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, OWNER, FOE
from tests.test_r1i_round3 import reload


def burial_setup(bundles):
    """Create the prerequisite through a committed bounded test packet.

    Only the setup action changes; Glass Prison and the victim's attack retain
    their real compiled effects, ownership, costs and transaction handling.
    """
    owner = bundles[0]
    for action in owner['action_catalog']:
        if action['display_name'].startswith('Scouring Hand'):
            typed = action['parameters']['typed']
            typed['effects'] = [{'type': 'sand_bury', 'applies_to': 'target',
                                 'expires_on': 'UNTIL_REMOVED'}]
            typed['riders'] = []
    owner.pop('bundle_sha256', None)
    owner['bundle_sha256'] = canonical_sha256(owner)


@pytest.mark.parametrize('ai_attack', [False, True])
def test_glass_prison_attack_cuts_on_real_table_commit_reload(tmp_path, ai_attack):
    combat, table, mid, send, commit = fixture(
        tmp_path, ['SAND_BASE_SCOURING_HAND', 'TAL_SAND_GLASS_PRISON'],
        foe_talents=['TAL_VOID_VOID_NEEDLE'], seed='R21-GLASS-PRISON',
        bundle_transform=burial_setup)
    commit(candidate(table, mid, 'Scouring Hand', FOE))
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != OWNER:
        commit(table.state(mid)['menu']['end_turn'])
    commit(candidate(table, mid, 'Glass Prison', FOE))
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != FOE:
        commit(table.state(mid)['menu']['end_turn'])
    before = reload(tmp_path, mid)
    assert any(row.condition_id == 'condition:typed.restrained'
               for row in before.state.actors[FOE].conditions.values())
    hp = before.state.actors[FOE].current_hp
    cid = candidate(table, mid, 'Void Needle', OWNER)
    if ai_attack:
        force_ai_candidate(combat, mid, FOE, cid)
        assert send(cid, auto=True)['status'] == 'COMMITTED'
    else:
        commit(cid)
    after = reload(tmp_path, mid)
    assert after.state.actors[FOE].current_hp == hp - 17
    assert getattr(after, '_active_intent', None) is None
