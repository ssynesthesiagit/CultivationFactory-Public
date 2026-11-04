"""Garden alignment and Funeral Ash generation retain distinct scene gates."""
import pytest

from combat.ext.foundation_context import CONTEXT, public_scene_context
from combat.gate5_service import CombatService
from tests.worker2_support import OWNER, ALLY, FOE, candidate, reload, settle
from tests.test_mgr_t14_ash_parent import controlled_settle
from tests.test_mgr_t14_garden_actions import (
    native_garden, cast, turn_unknown, garden_packets,
)
from tests.test_mgr_t14_garden_sum import GARDEN_NAME


@pytest.mark.parametrize('circumstances,expected_ash', [(1, 1), (2, 0)],
                         ids=['real-danger', 'staged'])
def test_automatic_garden_hit_uses_setup_residue_without_bypassing_generation_exclusions(
        tmp_path, circumstances, expected_ash):
    def declare(bundles):
        bundles[0] = CombatService._with_prefight(object.__new__(CombatService), bundles[0], {
            OWNER: [f'setup-choice:ash_public_circumstances:{circumstances}',
                    'setup-choice:ash_public_residue:1']})

    combat, table, mid = native_garden(tmp_path, hp=200, bundle_transform=declare,
                                     seed='ASH-GARDEN-fire')
    cast(combat, table, mid, 'Flame Lash')
    cast(combat, table, mid, GARDEN_NAME)
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={CONTEXT: 'unknown'})
    turn_unknown(table, mid, OWNER)
    before = reload(tmp_path, mid)
    assert before.state.actors[OWNER].resources['resource:foundation.funeral_ash'] == 0
    first_sequence = before.state.event_sequence
    for aid in (OWNER, ALLY, FOE):
        combat.set_controller_mode(mid, actor_id=aid, controller_mode='LOCAL_AUTO')
    prompts = controlled_settle(combat, table, mid,
        candidate(combat, mid, 'Flame Lash', target=FOE), choices={})
    engine = reload(tmp_path, mid)
    packets = [e for e in garden_packets(engine) if e.sequence > first_sequence]
    assert len(packets) == 1
    assert packets[0].payload['rolled_or_pending_damage'] == engine.state.actors[OWNER].proficiency_bonus
    assert engine.state.actors[OWNER].resources['resource:foundation.funeral_ash'] == expected_ash
    assert not any(p['context']['reaction_source_id'].startswith(CONTEXT) for p in prompts)
    scene = public_scene_context(engine, engine.state.actors[OWNER])
    facts = [e for e in engine.events if e.sequence > first_sequence
             and e.payload.get('fact_kind') == 'foundation_event_context'
             and e.payload.get('route') == 'outgoing']
    assert facts and facts[0].payload['setup_sequence'] == scene['setup_sequence']
    assert facts[0].payload['circumstances'] == ('real' if circumstances == 1 else 'staged')
