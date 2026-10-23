"""Zero-HP sanctuary outcome is committed before its printed step, and the table replays after reload."""
from tests.test_redo_homefire_sources import fight, cast
from tests.worker2_support import OWNER, ALLY, FOE, turn, candidate, settle, reload


def test_no_guest_stable_is_committed_before_its_step_and_replays(tmp_path):
    combat, table, mid = fight(tmp_path)
    # One Flame, one cast by its owner: the ally is protected by a single once-per-scene field.
    cast(combat, table, mid)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Drop to zero', target=ALLY).candidate_id,
                     picks={'choice:needle.hearth_shield': None, 'choice:needle.rider_step': lambda c: next(o['id'] for o in c['options'] if o['id'] != c['preferred'][0])})
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    assert ally.current_hp == 0 and ally.life_state == 'STABLE' and ally.temporary_hp == 12
    raised = [p['context']['reaction_source_id'] for p in prompts]
    step = next((p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.rider_step'), None)
    assert step is not None, f'the printed step was never offered; prompts raised: {raised}'
    chosen = next(o['id'] for o in step['choice']['options'] if o['id'] != step['choice']['preferred'][0])
    assert (ally.position.x, ally.position.y) == tuple(int(v) for v in chosen.removeprefix('cell:').split(','))
    # The Stable outcome is evented before the printed step moves the creature.
    life = next(i for i, e in enumerate(engine.events) if e.event_type == 'LIFE_STATE_CHANGED'
                and e.actor_id == ALLY and e.payload.get('life_state') == 'STABLE')
    move = next(i for i, e in enumerate(engine.events) if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == ALLY)
    assert life < move
    assert sum(e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == ALLY for e in engine.events) == 1
