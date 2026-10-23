"""A recovery that completes inside No Guest Dies Alone survives the outer zero-HP resolver.

The printed step can carry a protected ally into another area whose entry effect
heals it. The healing is committed (Hit Points above zero, life state cleared), so
the general zero-HP resolver must keep that outcome instead of applying a second
zero-HP state to a living creature.
"""
from combat.canonical import canonical_sha256
from tests.test_redo_homefire_sources import fight, cast
from tests.worker2_support import OWNER, ALLY, FOE, turn, candidate, settle, reload


def add_healing_breeze(bundles):
    """One sealed 5-foot area that heals whoever enters it (test-only action)."""
    bundle = bundles[0]
    source = 'action:test.hearthfire.healing_breeze'
    bundle['action_catalog'].append({
        'source_definition_id': source, 'display_name': 'Healing Breeze', 'owner_id': OWNER,
        'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'CELL',
        'range_ft': 30, 'parameters': {'free_primary': True, 'typed': {
            'source': source, 'numbers': {'save_dc': 10}, 'duration': {'kind': 'instant'},
            'zone_spec': {'name': 'Healing Breeze', 'shape': 'cube', 'size_ft': 5,
                'duration': {'kind': 'rounds', 'amount': 10},
                'triggers': [{'on': ['enter'], 'who': 'any', 'effects': [
                    {'type': 'healing', 'applies_to': 'target', 'flat': 10}]}]},
            'effects': [{'type': 'zone', 'applies_to': 'self'}]}}})
    bundle['actor_template']['action_ids'].append(source)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)


def test_healing_during_the_zero_hp_step_commits_and_reloads(tmp_path):
    combat, table, mid = fight(tmp_path, extra=add_healing_breeze)
    # The 5-foot breeze sits on the ally's only inward step out of its square.
    settle(table, mid, candidate(combat, mid, 'Healing Breeze', at=(5, 6)).candidate_id)
    cast(combat, table, mid)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[ALLY].position
    prompts = settle(table, mid, candidate(combat, mid, 'Drop to zero', target=ALLY).candidate_id,
                     picks={'choice:needle.hearth_shield': None,
                            'choice:needle.rider_step': 'cell:5,6'})
    raised = [p['context']['reaction_source_id'] for p in prompts]
    assert 'choice:needle.rider_step' in raised, f'the printed step was never offered; prompts raised: {raised}'
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    assert (ally.position.x, ally.position.y) == (5, 6) and ally.position != before
    assert ally.current_hp == 10, 'the entry heal must survive the outer zero-HP resolution'
    assert ally.life_state is None, 'a living, healed creature is not Stable'
    assert ally.temporary_hp == 12
    # The heal is committed once and the fight still replays.
    assert sum(e.event_type == 'HEALING_APPLIED' and ALLY in e.target_ids for e in engine.events) == 1
    assert sum(e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == ALLY for e in engine.events) == 1
