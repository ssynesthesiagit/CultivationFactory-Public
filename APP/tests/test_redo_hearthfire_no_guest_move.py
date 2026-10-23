"""No Guest Dies Alone's printed 5-foot step is usable by the Stable creature it protects."""
from tests.test_redo_homefire_sources import fight, cast
from tests.worker2_support import FOE, ALLY, turn, candidate, settle, reload
from combat import granted_movement as gm


def test_protected_zero_hp_ally_takes_offered_five_foot_step(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path)
    cast(combat, table, mid)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[ALLY].position
    seen = []
    real = gm.candidates

    def recording(engine, actor, feet, intent, source):
        out = real(engine, actor, feet, intent, source)
        if actor.entity_id == ALLY:
            seen.append((feet, engine._effective_speed(actor), actor.active, actor.life_state,
                         len(gm.routes(engine, actor, feet)), len(out), intent is not None))
        return out

    monkeypatch.setattr(gm, 'candidates', recording)
    prompts = settle(table, mid, candidate(combat, mid, 'Drop to zero', target=ALLY).candidate_id,
                     picks={'choice:needle.hearth_shield': None, 'choice:needle.rider_step': lambda c: next(o['id'] for o in c['options'] if o['id'] != c['preferred'][0])})
    raised = [p['context']['reaction_source_id'] for p in prompts]
    step = next((p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.rider_step'), None)
    assert step is not None, f'the printed step was never offered; prompts raised: {raised}; candidate probes (feet, speed, active, life, routes, candidates, intent): {seen}'
    offered = [o['id'] for o in step['choice']['options']]
    assert len(offered) > 1, 'a Stable creature with 5 feet of movement must be offered a move, not only Stay'
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    assert ally.position != before, 'the chosen printed step must move the protected ally'
    assert ally.position.z == 0 and f"cell:{ally.position.x},{ally.position.y}" in offered
    assert ally.current_hp == 0 and ally.life_state == 'STABLE' and ally.temporary_hp == 12
    assert ally.active
