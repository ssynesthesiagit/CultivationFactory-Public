"""No Guest Dies Alone's printed 5-foot step is usable by the Stable creature it protects."""
from tests.test_redo_homefire_sources import fight, cast
from tests.worker2_support import FOE, ALLY, turn, candidate, settle, reload


def test_protected_zero_hp_ally_takes_offered_five_foot_step(tmp_path):
    combat, table, mid = fight(tmp_path)
    cast(combat, table, mid)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[ALLY].position
    prompts = settle(table, mid, candidate(combat, mid, 'Drop to zero', target=ALLY).candidate_id,
                     picks={'choice:needle.hearth_shield': None, 'choice:needle.rider_step': 'first'})
    raised = [p['context']['reaction_source_id'] for p in prompts]
    step = next((p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.rider_step'), None)
    assert step is not None, f'the printed step was never offered; prompts raised: {raised}'
    offered = [o['id'] for o in step['choice']['options']]
    assert offered, 'a Stable creature with 5 feet of movement must be offered its step'
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    assert ally.position != before
    assert f"cell:{ally.position.x},{ally.position.y}" == offered[0]
    assert ally.current_hp == 0 and ally.life_state == 'STABLE' and ally.temporary_hp == 12
    assert ally.active
