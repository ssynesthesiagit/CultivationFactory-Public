"""Shared grant and consent seams through CombatService commits and cold replay.

Fixture actions supply general typed rows rather than ability-specific engine
overrides. Table commits call session.submit_intent -> mechanical.execute_intent.
"""
import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from tests import test_riders_c13 as C
from tests.test_a2_misc_subpaths_3 import setup, mark, find, cold, ME, FOE, MARK, DOOR
from tests.worker2_support import fixture, settle, OWNER, FOE as GRANT_FOE


def add_action(bundle, name, effects, *, target_kind='SELF'):
    source = 'action:test.r9.' + name.lower().replace(' ', '_')
    action = {'source_definition_id': source, 'display_name': name,
        'owner_id': bundle['actor_id'], 'economy': 'NONE',
        'resolution_kind': 'TYPED', 'target_kind': target_kind, 'range_ft': 60,
        'parameters': {'typed': {'source': source, 'numbers': {}, 'riders': [], 'effects': effects}}}
    bundle['action_catalog'].append(action)
    bundle['actor_template']['action_ids'].append(source)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)


@pytest.mark.parametrize('extension_first', [False, True])
@pytest.mark.parametrize('reduced_speed', [False, True])
def test_native_fixed_grant_after_extension_commit_and_reload(tmp_path, extension_first, reduced_speed):
    # The unrelated creature has no Drunken Style rows at all. The other case
    # completes a real Reeling Step before the native typed rider grant.
    owner = compile_character(C._sheet(C.DRUNKEN if extension_first else 'tianxia.sphere.athletics'),
                              actor_id=OWNER, reaction_plan={'ask': True})
    def actions(bundles):
        add_action(bundles[0], 'Fixture fixed step', [
            {'type': 'rider_step', 'distance_ft': 10, 'no_oa': True}])
        add_action(bundles[0], 'Fixture reduce Speed', [
            {'type': 'speed', 'flat': -25, 'applies_to': 'self', 'duration': {'kind': 'until_removed'}},
            {'type': 'remaining_movement', 'becomes': 0, 'applies_to': 'self'}])
    service, table, mid = fixture(tmp_path, [], owner_bundle=owner, bundle_transform=actions,
                                 foe_position={'x': 4, 'y': 7})
    def choose(name):
        engine = service._load_session(mid).engine
        return next(c for c in engine.legal_candidates() if c.display_name == name)
    if reduced_speed:
        settle(table, mid, choose('Fixture reduce Speed').candidate_id)
    engine = cold(tmp_path, service, mid)
    mover = engine.state.actors[OWNER]
    assert engine._effective_speed(mover) == (5 if reduced_speed else 30)
    ordinary = mover.movement_remaining_ft
    if extension_first:
        settle(table, mid, choose('Reeling Step').candidate_id, {
            'choice:needle.drunken_reeling_oa': GRANT_FOE,
            'choice:needle.drunken_reeling_move': 'cell:1,6'})
        engine = service._load_session(mid).engine
        assert (engine.state.actors[OWNER].position.x, engine.state.actors[OWNER].position.y) == (1, 6)
        # The extension restores None; the next native grant must accept it.
        assert getattr(engine, '_granted_movement_budget', None) is None
    start = len(service._load_session(mid).engine.events)
    destination = 'cell:1,4' if extension_first else 'cell:3,4'
    prompts = settle(table, mid, choose('Fixture fixed step').candidate_id,
                     {'choice:needle.rider_step': destination})
    offered = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.rider_step')
    assert destination in {o['id'] for o in offered['choice']['options']}
    engine = cold(tmp_path, service, mid)
    mover = engine.state.actors[OWNER]
    assert (mover.position.x, mover.position.y) == ((1, 4) if extension_first else (3, 4))
    assert mover.movement_remaining_ft == ordinary
    receipts = [e for e in engine.events[start:] if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == OWNER]
    assert len(receipts) == 1
    assert receipts[0].payload['cost_ft'] == 0
    assert receipts[0].payload['granted_cost_ft'] == 10
    assert receipts[0].payload['forced'] is False
    assert getattr(engine, '_granted_movement_budget', None) is None


@pytest.mark.parametrize('forced', [False, None, True], ids=['willing', 'unknown', 'forced'])
def test_witnessing_subject_teleport_preserves_consent_after_reload(tmp_path, forced):
    effect = {'type': 'teleport', 'applies_to': 'target', 'distance_ft': 15,
              'choose_subject_destination': True}
    if forced is not None:
        effect['forced'] = forced
    service, table, mid = setup(tmp_path, [MARK], owner=(3, 6),
        bundle_transform=lambda bundles: add_action(bundles[0], 'Fixture subject teleport', [effect],
                                                   target_kind='ANY_CREATURE'))
    mark(service, table, mid, 'witnessing')
    settle(table, mid, find(service, mid, 'Fixture subject teleport', FOE).candidate_id,
           {'choice:needle.subject_destination': 'cell:4,5'})
    engine = cold(tmp_path, service, mid)
    assert (engine.state.actors[FOE].position.x, engine.state.actors[FOE].position.y) == (4, 5)
    receipt = next(e for e in reversed(engine.events) if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == FOE)
    assert receipt.payload['teleport'] and receipt.payload['forced'] is forced
    notices = [e for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED'
               and e.actor_id == ME and 'threshold_crossing' in e.payload]
    assert len(notices) == 1
    assert notices[0].payload['threshold_crossing'] == {
        'threshold_id': DOOR, 'creature_id': FOE, 'direction': 'south to north',
        **({'willing': not forced} if forced is not None else {})}
    wording = 'willingly' if forced is False else 'forced movement' if forced is True else 'consent unknown'
    assert wording in notices[0].payload['log']
