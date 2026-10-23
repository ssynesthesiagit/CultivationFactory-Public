"""No Guest Dies Alone's printed 5-foot step is usable by the Stable creature it protects,
and it does not suspend unrelated restraints."""
from combat.canonical import canonical_sha256
from tests.test_redo_homefire_sources import fight, cast
from tests.worker2_support import OWNER, ALLY, FOE, turn, candidate, settle, reload
from combat import granted_movement as gm


def add_condition(bundles, display_name, condition, rule):
    """One sealed test action on every bundle: apply a condition carrying ``rule``."""
    for bundle in bundles:
        source = 'action:test.hearthfire.' + bundle['actor_id'].rsplit('-', 1)[-1] + '.' + display_name.lower().replace(' ', '_')
        bundle['action_catalog'].append({
            'source_definition_id': source, 'display_name': display_name,
            'owner_id': bundle['actor_id'], 'economy': 'NONE', 'resolution_kind': 'TYPED',
            'target_kind': 'ANY_CREATURE', 'range_ft': 60, 'parameters': {'free_primary': True, 'typed': {
                'source': source, 'numbers': {'save_dc': 10}, 'duration': {'kind': 'instant'},
                'effects': [{'type': 'condition', 'applies_to': 'target', 'condition': condition,
                             'expires_on': 'UNTIL_REMOVED',
                             'condition_data': {'label': display_name, 'rule': dict(rule)}}]}}})
        bundle['actor_template']['action_ids'].append(source)
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)


def zero_hp_step(tmp_path, extra=None):
    combat, table, mid = fight(tmp_path, extra=extra)
    cast(combat, table, mid)
    turn(table, mid, FOE)
    return combat, table, mid


def test_protected_zero_hp_ally_takes_offered_five_foot_step(tmp_path, monkeypatch):
    combat, table, mid = zero_hp_step(tmp_path)
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


def test_prone_crawl_does_not_double_the_printed_step(tmp_path):
    """The Prone that the zero-HP state carries is the one cost the step is exempt from."""
    combat, table, mid = zero_hp_step(
        tmp_path, extra=lambda bundles: add_condition(bundles, 'Knocked Prone', 'prone', {}))
    settle(table, mid, candidate(combat, mid, 'Knocked Prone', target=ALLY).candidate_id)
    before = reload(tmp_path, mid).state.actors[ALLY].position
    prompts = settle(table, mid, candidate(combat, mid, 'Drop to zero', target=ALLY).candidate_id,
                     picks={'choice:needle.hearth_shield': None, 'choice:needle.rider_step': 'cell:5,6'})
    raised = [p['context']['reaction_source_id'] for p in prompts]
    assert 'choice:needle.rider_step' in raised, f'the printed step was never offered; prompts raised: {raised}'
    ally = reload(tmp_path, mid).state.actors[ALLY]
    assert (ally.position.x, ally.position.y) == (5, 6) and ally.position != before


def test_independent_speed_zero_condition_still_stops_the_granted_step(tmp_path):
    """An unrelated Speed 0 (here a Meridian-pin style hold) is not lifted by the exemption."""
    combat, table, mid = zero_hp_step(
        tmp_path, extra=lambda bundles: add_condition(bundles, 'Meridian Pinch', 'mark.meridian_pin', {'speed_zero': True}))
    settle(table, mid, candidate(combat, mid, 'Meridian Pinch', target=ALLY).candidate_id)
    before = reload(tmp_path, mid).state.actors[ALLY].position
    prompts = settle(table, mid, candidate(combat, mid, 'Drop to zero', target=ALLY).candidate_id,
                     picks={'choice:needle.hearth_shield': None})
    raised = [p['context']['reaction_source_id'] for p in prompts]
    assert 'choice:needle.rider_step' not in raised, f'an unrelated Speed 0 must not be lifted; prompts raised: {raised}'
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    assert ally.position == before
    assert ally.current_hp == 0 and ally.life_state == 'STABLE' and ally.temporary_hp == 12
    assert not any(e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == ALLY for e in engine.events)


def test_unrelated_walking_cost_still_prices_the_granted_step(tmp_path):
    """Only the Prone crawl surcharge is lifted; another condition's walking cost still applies."""
    combat, table, mid = zero_hp_step(
        tmp_path, extra=lambda bundles: add_condition(bundles, 'Heavy Legs', 'mark.heavy_legs', {'walking_extra_cost': 1}))
    settle(table, mid, candidate(combat, mid, 'Heavy Legs', target=ALLY).candidate_id)
    before = reload(tmp_path, mid).state.actors[ALLY].position
    prompts = settle(table, mid, candidate(combat, mid, 'Drop to zero', target=ALLY).candidate_id,
                     picks={'choice:needle.hearth_shield': None})
    raised = [p['context']['reaction_source_id'] for p in prompts]
    assert 'choice:needle.rider_step' not in raised, f'a 5-foot grant cannot pay a doubled walking cost; prompts raised: {raised}'
    assert reload(tmp_path, mid).state.actors[ALLY].position == before
