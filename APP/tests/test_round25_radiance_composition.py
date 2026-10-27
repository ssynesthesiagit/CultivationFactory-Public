"""One Scripture bonus across native/typed delivery and legacy spent-state shapes."""
import pytest

from combat import typed_executor
from combat.ext.radiance_unclean import SCRIPTURE, SCRIPTURE_TURN_FLAG
from tests import lock8_support as S
from tests.test_lock8_radiance import kind_bundle


@pytest.mark.parametrize('legacy_spent', [False, True])
def test_scripture_has_one_shared_native_and_typed_damage_gate(legacy_spent):
    engine = S.fight(S.bundle(SCRIPTURE, cl=20),
                     foe=kind_bundle(['SAND_BASE_SCOURING_HAND'], S.FOE, 'Undead', cl=20))
    owner, target = engine.state.actors[S.ME], engine.state.actors[S.FOE]
    ctx = S.ctx_of(engine, S.ME, S.FOE, S.action_id(engine, S.ME, 'Radiance Strike'))
    typed_executor.block_mark(ctx, {'mark': 'Dawnmark', 'applies_to': 'target'})
    if legacy_spent:
        current = engine.state.actors[engine.state.current_actor_id]
        owner.turn_flags['radiance_scripture_damage_turn'] = [engine.state.round_number, current.entity_id,
                                                            current.turns_started]
    before = target.current_hp
    engine._commit_damage(target, 1, 'FIRE', 'test:native', S.ME, None, reaction_depth=0)
    typed_executor.run_effects(ctx, [{'type': 'damage', 'applies_to': 'target', 'flat': 1,
                                     'damage_types': ['fire']}])
    bonuses = [e for e in engine.events if e.event_type == 'DAMAGE_ROLLED' and e.source_definition_id == SCRIPTURE]
    assert len(bonuses) == (0 if legacy_spent else 1)
    assert before - target.current_hp == 2 + (0 if legacy_spent else bonuses[0].payload['total'])
    if not legacy_spent:
        assert isinstance(owner.turn_flags[SCRIPTURE_TURN_FLAG], str)
