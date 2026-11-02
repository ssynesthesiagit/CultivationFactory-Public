"""Frost Guard's first-hit bookkeeping survives table commits and fresh reloads."""
import pytest

from combat.gate5_service import CombatService
from combat.ext.ice_fracture import GUARD, T
from tests.r1i_service_support import ROOT, OWNER, FOE, fixture, candidate, force_ai_candidate
from tests.h1_support import sheet
from tests.test_carry import KIT
from combat.factory_compiler import compile_character


@pytest.mark.parametrize('auto', [False, True])
def test_frost_guard_first_hit_replays_without_fresh_application(tmp_path, auto):
    def armed_foe(bundles):
        bundles[1] = compile_character(sheet([], cl=17, kit={'starting_kit': KIT}), actor_id=FOE)
    combat, table, mid, send, commit = fixture(tmp_path, [T + 'FROST_SHEATHED_GUARD'],
        owner_ac=1, seed='HUNT17-FROST-FIRST-HIT', bundle_transform=armed_foe)
    commit(candidate(table, mid, 'Frost-Sheathed Guard', OWNER))
    before = combat._load_session(mid).engine.state.actors[OWNER]
    key, original = next((k, c.model_dump(mode='json')) for k, c in before.conditions.items()
                         if c.condition_id == GUARD)
    assert before.temporary_hp > 0 and not original['data'].get('used')
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != FOE:
        commit(table.state(mid)['menu']['end_turn'])
    cid = candidate(table, mid, 'Bi Shou (Dagger) attack', OWNER)
    sequence = combat._load_session(mid).engine.state.event_sequence
    if auto:
        force_ai_candidate(combat, mid, FOE, cid)
        result = send(cid, auto=True)
        assert result['status'] == 'COMMITTED', result
    else:
        commit(cid)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    guard = loaded.engine.state.actors[OWNER].conditions[key]
    assert guard.data['used'] == 1
    assert guard.expires_on == original['expires_on']
    assert guard.source_actor_id == original['source_actor_id']
    updates = [e for e in loaded.engine.events if e.sequence > sequence
               and e.event_type == 'CONDITION_APPLIED' and e.payload.get('instance_id') == key]
    assert len(updates) == 1 and updates[0].payload['retained_instance_update'] == 1
    assert not any(e.sequence > sequence and e.event_type == 'TEMP_HP_GRANTED'
                   and 'FROST_SHEATHED_GUARD' in str(e.source_definition_id)
                   for e in loaded.engine.events)
