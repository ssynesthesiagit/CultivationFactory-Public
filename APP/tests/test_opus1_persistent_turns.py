"""Persistent Technique's all-creature turn clock across table commits and cold reloads.

A sealed test effect delivers a fresh activation of the owner's Sphere talent on
another creature's turn. Only the delivery is synthetic; native typed saves,
rewrite consent/payment, turn advancement, persistence and replay are real.
"""
import pytest

from combat import ext
from combat.canonical import canonical_sha256
from combat.ext import insight_rewrites as ir
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.typed_executor import Context, block_save
from tests.h1_support import ROOT
from tests.test_opus1_insight_rewrites import FRIGHTEN, _rewrites, seal
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle


@pytest.mark.parametrize('ask', [True, False], ids=['ask-owner', 'automatic-owner'])
def test_persistent_allows_one_activation_each_creature_turn_after_cold_reload(tmp_path, monkeypatch, ask):
    sphere_action = None

    def setup(bundles):
        nonlocal sphere_action
        sphere_action = seal(bundles[0], 'Fear Palm', FRIGHTEN, save_dc=1, sphere='tianxia.sphere.test')
        # Owner and ally are the first two turns of the same round.
        for bundle, initiative in zip(bundles, [100, 50, -100]):
            bundle['actor_template']['initiative_bonus'] = initiative
            for name, economy in [('First Pulse', 'ACTION'), ('Second Pulse', 'BONUS_ACTION')]:
                seal(bundle, name, [{'type': 'test_opus1_sphere_activation'}], save_dc=1)
                bundle['action_catalog'][-1]['economy'] = economy
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)

    def deliver(ctx, effect):
        action = ctx.engine.action_catalog[sphere_action]
        target = ctx.engine.state.actors[FOE]
        native = Context(engine=ctx.engine, actor=ctx.engine.state.actors[OWNER], action=action,
                         intent=ctx.intent, typed=action.parameters['typed'], targets=[target], target=target)
        block_save(native, FRIGHTEN[0])

    monkeypatch.setitem(ext.effects(), 'test_opus1_sphere_activation', deliver)
    combat, table, mid = fixture(tmp_path, [], owner_insights=[ir.PERSISTENT], ask=ask,
                                 bundle_transform=setup, ally_position={'x': 1, 'y': 9})
    engine = reload(tmp_path, mid)
    first_round = engine.state.round_number
    assert engine.state.initiative_order[:2] == [OWNER, ALLY]
    qi = engine.state.actors[OWNER].resources['resource:core.qi']
    flag = 'once_per_turn:h1:' + ir.PERSISTENT

    def pulse(name, expected_count, offered):
        # Continue from a new service, not its warm in-memory session.
        nonlocal combat, table
        combat = CombatService(ROOT, tmp_path)
        table = TabletopService(combat, tmp_path)
        prompts = settle(table, mid, candidate(combat, mid, name, target=FOE).candidate_id,
                         picks={'reaction:typed.' + ir.PERSISTENT: 'USE'})
        asked = [p for p in prompts if 'Persistent Technique' in str(p)]
        assert bool(asked) == (ask and offered), prompts
        if asked:
            assert 'Fear Palm' in str(asked) and asked[0]['context']['reactor_id'] == OWNER
        engine = reload(tmp_path, mid)
        assert engine.state.round_number == first_round
        assert len(_rewrites(engine, ir.PERSISTENT)) == expected_count
        assert engine.state.actors[OWNER].resources['resource:core.qi'] == qi - 3 * expected_count

    pulse('First Pulse', 1, True)
    pulse('Second Pulse', 1, False)  # distinct activation, same turn: no payment or prompt
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    engine = reload(tmp_path, mid)
    assert engine.state.current_actor_id == ALLY and engine.state.round_number == first_round
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == qi - 3
    pulse('First Pulse', 2, True)  # same round, off the owner's turn
    pulse('Second Pulse', 2, False)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].turn_flags[flag] is True
    assert any(e.event_type == 'PER_TURN_USES_RESET' and e.actor_id == OWNER
               and flag in e.payload['keys'] for e in engine.events)
