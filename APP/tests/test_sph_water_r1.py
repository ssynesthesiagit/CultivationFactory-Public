"""Water review regressions: table commits, cold reload and mechanical replay."""
import pytest

from combat.canonical import canonical_sha256
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.test_auto134_water_pull import PULL, CHOICE, FOE_START, prepare, soak_then
from tests.test_auto38_water import SHIELD, prepare as shield_prepare
from tests.test_carry import KIT


def rooted_prepare(bundles, reduction, *, shield=False):
    (shield_prepare if shield else prepare)(bundles)
    for bundle in bundles:
        if bundle['actor_id'] == OWNER:
            action = next(a for a in bundle['action_catalog'] if a['display_name'] == 'Fixture soak')
            action['parameters']['typed']['effects'].append({
                'type': 'condition', 'condition': 'iron_rooting', 'applies_to': 'target',
                'duration': 'until_end_of_your_next_turn', 'condition_data': {'reduction': reduction}})
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)


@pytest.mark.parametrize('reduction', [5, 10])
def test_pull_respects_rooting_and_stopped_pull_never_saves(tmp_path, reduction):
    combat, table, mid = fixture(tmp_path, [PULL], foe_position=FOE_START,
        bundle_transform=lambda b: rooted_prepare(b, reduction))
    settle(table, mid, candidate(combat, mid, 'Shape Current: Mist Basin', at=(5, 3)).candidate_id)
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    soak_then(table, combat, mid)
    settle(table, mid, candidate(combat, mid, 'Water Lash + Pull of the River', target=FOE).candidate_id,
           {CHOICE: 'cell:4,3'})
    e = reload(tmp_path, mid)
    target = e.state.actors[FOE]
    assert (target.position.x, target.position.y) == ((5, 2) if reduction == 5 else (6, 2))
    assert len([v for v in e.events if v.event_type == 'SAVE_ROLLED' and v.actor_id == FOE]) == int(reduction == 5)


@pytest.mark.parametrize('reduction', [5, 10])
def test_shield_movement_respects_recipient_rooting(tmp_path, reduction):
    combat, table, mid = fixture(tmp_path, [SHIELD], foe_position={'x': 3, 'y': 5},
        foe_kit={'starting_kit': {'items': [KIT['items'][-1]]}},
        bundle_transform=lambda b: rooted_prepare(b, reduction, shield=True))
    settle(table, mid, candidate(combat, mid, 'Fixture soak', target=ALLY).candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Bi Shou (Dagger) attack', target=ALLY).candidate_id,
           {'choice:needle.water_shield': 'use', 'choice:needle.water_shield_step': 'step:4,8'})
    e = reload(tmp_path, mid)
    assert e.state.actors[ALLY].position.y == (7 if reduction == 5 else 6)
    assert e.state.actors[OWNER].resources['resource:core.qi'] == 99
    assert not any(k.startswith('auto38_shield_pending:') for k in e.state.actors[OWNER].turn_flags)


def test_adjacent_pull_has_no_outward_fallback(tmp_path):
    combat, table, mid = fixture(tmp_path, [PULL], foe_position={'x': 3, 'y': 5}, bundle_transform=prepare)
    soak_then(table, combat, mid)
    prompts = settle(table, mid, candidate(combat, mid, 'Water Lash + Pull of the River', target=FOE).candidate_id)
    e = reload(tmp_path, mid)
    assert not any(p['context']['reaction_source_id'] == CHOICE for p in prompts)
    assert (e.state.actors[FOE].position.x, e.state.actors[FOE].position.y) == (3, 5)


def test_pull_menu_and_reduced_path_close_on_every_step(tmp_path):
    # The ally at (4,6) blocks the straight first step. The old BFS route to
    # (4,5) starts at (5,5), which moves away on the caster's north/south axis.
    combat, table, mid = fixture(tmp_path, [PULL], foe_position={'x': 5, 'y': 6},
        bundle_transform=lambda b: rooted_prepare(b, 5))
    soak_then(table, combat, mid)
    prompts = settle(table, mid, candidate(combat, mid, 'Water Lash + Pull of the River', target=FOE).candidate_id)
    e = reload(tmp_path, mid)
    for event in e.events:
        if event.event_type == 'MOVEMENT_COMMITTED' and event.source_definition_id == PULL:
            from combat.gate2_runtime_models import Position
            path = [Position(**p) for p in event.payload['path']]
            caster = e.state.actors[OWNER].position
            assert all(abs(b.x-caster.x) <= abs(a.x-caster.x)
                       and abs(b.y-caster.y) <= abs(a.y-caster.y)
                       and b != a for a, b in zip(path, path[1:]))
    # With the only toward step occupied, a detour is not offered at all.
    assert not any(p['context']['reaction_source_id'] == CHOICE for p in prompts)


def test_area_packet_can_shield_but_nested_falling_cannot(tmp_path, monkeypatch):
    from combat import falling, typed_executor

    # Test-only delivery effect creates real nested falling damage while the
    # area action is active; production hooks and packet attribution are intact.
    monkeypatch.setitem(typed_executor.BLOCKS, 'fixture_launch_owner',
        lambda ctx, eff: falling.displace(ctx.engine, ctx.engine.state.actors[OWNER], 2,
                                         ctx.source, intent=ctx.intent))

    def transform(bundles):
        shield_prepare(bundles, area=True)
        for bundle in bundles:
            for action in bundle['action_catalog']:
                if action['display_name'] == 'Fixture area damage':
                    # The first owner absorbs this entire real area packet;
                    # the second owner stays eligible for the later fall.
                    action['parameters']['typed']['effects'][1]['flat'] = 1
                    action['parameters']['typed']['effects'].append({'type': 'fixture_launch_owner'})
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)

    combat, table, mid = fixture(tmp_path, [SHIELD], ally_talents=[SHIELD],
        foe_position={'x': 3, 'y': 5}, bundle_transform=transform)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Fixture area damage', at=(3, 6)).candidate_id,
        {'choice:needle.area_recipients': [ALLY], 'choice:needle.water_shield': 'use'})
    e = reload(tmp_path, mid)
    shield_prompts = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.water_shield']
    assert len(shield_prompts) == 1
    assert shield_prompts[0]['context']['reactor_id'] == ALLY
    assert e.state.actors[ALLY].resources['resource:core.qi'] == 99
    assert e.state.actors[OWNER].reaction_available
    assert e.state.actors[OWNER].resources['resource:core.qi'] == 100
    assert any(v.event_type == 'DAMAGE_COMMITTED' and v.source_definition_id == falling.SOURCE
               and v.target_ids == (OWNER,) for v in e.events)
