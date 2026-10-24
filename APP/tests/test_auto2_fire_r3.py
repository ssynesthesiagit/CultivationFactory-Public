"""Focus must pay its own backlash after an accepted terminal Fire talent."""
import pytest

from combat.canonical import canonical_sha256
from tests.r1i_service_support import OWNER, FOE, SECOND, fixture, candidate
from tests.test_auto2_fire import FOCUS, WARD, cold, damage
from tests.test_auto77f1_fire_service import _run, _candidate


@pytest.mark.parametrize('hp,resistant', [(10, False), (1, False), (10, True)])
def test_focus_terminal_backlash_commits_and_replays(tmp_path, hp, resistant):
    def prepare(bundles):
        for bundle in bundles:
            bundle['actor_template']['maximum_hp'] = hp if bundle['actor_id'] == OWNER else 1
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
    combat, table, mid, send, commit = fixture(tmp_path, [FOCUS, 'FIRE_TAL_FIREBALL_ART', WARD],
        bundle_transform=prepare, wide=True, seed='A2FIREr3-TERMINAL',
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 10, 'y': 6}, SECOND: {'x': 11, 'y': 6}})
    if resistant:
        commit(candidate(table, mid, 'Blazing Armor'))
        commit(table.state(mid)['menu']['end_turn'])
        while table.state(mid)['menu']['actor_id'] != OWNER:
            commit(table.state(mid)['menu']['end_turn'])
    commit(candidate(table, mid, 'Advantage on one attack roll'))
    armed = cold(combat, mid, tmp_path)
    assert not damage(armed, OWNER)
    assert armed.state.actors[OWNER].current_hp == hp
    assert any('white_hot_focus' in c.condition_id for c in armed.state.actors[OWNER].conditions.values())
    _run(table, mid, _candidate(combat, table, mid, 'Fireball', FOE), lambda prompt, choice, ids: ids[:1])
    engine = cold(combat, mid, tmp_path)
    assert engine.state.terminal_result is not None
    assert all(not engine.state.actors[who].active for who in (FOE, SECOND))
    packets = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids
               and 'white_hot_focus' in str(e.source_definition_id)]
    assert len(packets) == 1, 'A finishing blow still owes exactly one Focus damage packet'
    assert packets[0].payload['rolled_or_pending_damage'] == 4
    assert packets[0].payload['reduced_to'] == (2 if resistant else 4)
    assert engine.state.actors[OWNER].current_hp == max(0, hp - (2 if resistant else 4))
    assert not any('white_hot_focus' in c.condition_id for c in engine.state.actors[OWNER].conditions.values())
    foe_damage = [i for i, e in enumerate(engine.events) if e.event_type == 'DAMAGE_COMMITTED'
                  and any(who in e.target_ids for who in (FOE, SECOND))]
    assert engine.events.index(packets[0]) > max(foe_damage), 'Payment follows the talent resolution'
