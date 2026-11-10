"""Review regressions: continuing grants retain benefits and AI can buy upgrades."""
import pytest

from combat import zones
from combat.canonical import canonical_sha256
from combat.ext.shadowed_mien import MIEN, POOL, grant
from combat.ext.tabik_dark import CLEARSIGHT_PERMISSION
from tests.test_mgr_t16_shadowed_mien import setup
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn

CLEAR = 'TAL_DARK_CLEARSIGHT'
PERSIST = 'TAL_DARK_PERSISTENT_MELD'
KEEP = 'Persistent Meld: keep Meld without Concentration (2 CP)'


@pytest.mark.parametrize('recipient', [OWNER, ALLY])
def test_after_cast_persistence_retains_mien_hp_and_original_grant(tmp_path, recipient):
    combat, table, mid = fixture(tmp_path, [MIEN, PERSIST], bundle_transform=setup())
    settle(table, mid, candidate(combat, mid, 'Meld: Shadowed Mien (1 CP: Temporary HP)', target=recipient).candidate_id)
    before = reload(tmp_path, mid)
    original = grant(before, before.state.actors[recipient])
    settle(table, mid, candidate(combat, mid, KEEP).candidate_id)
    engine = reload(tmp_path, mid)
    holder = engine.state.actors[recipient]
    kept = grant(engine, holder)
    assert holder.temporary_hp == 15
    assert kept.instance_id == original.instance_id
    assert kept.data['end_clock'] == original.data['end_clock']
    assert not kept.data['concentration'] and kept.expires_on != 'CONCENTRATION_END'
    assert engine.state.actors[OWNER].concentration is None
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 97
    assert next(c for c in holder.conditions.values() if c.condition_id == POOL).data['meld_instance'] == kept.instance_id
    # Paying to persist cannot renew the HP, and ending the kept copy must still
    # remove both the Meld and its dependent pool through the original identity.
    from combat.ext.persist_augment import RECORD
    record = next(c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == RECORD)
    assert [recipient, kept.instance_id] in record.data['kept']['conditions']
    turn(table, mid, OWNER)  # still the same turn; renew after the next round
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Meld: Shadowed Mien', target=recipient).candidate_id)
    holder = reload(tmp_path, mid).state.actors[recipient]
    assert holder.temporary_hp == 0
    assert not any(c.condition_id == POOL for c in holder.conditions.values())


def test_after_cast_persistence_retains_allied_clearsight_permission(tmp_path):
    pure = 'TAL_DARK_PURE_DARKNESS'
    combat, table, mid = fixture(tmp_path, [CLEAR, PERSIST], ally_talents=[pure])
    settle(table, mid, candidate(combat, mid, 'Meld: Clearsight', target=OWNER).candidate_id,
           picks={'choice:needle.clearsight_creator_consent': 'allow'})
    engine = reload(tmp_path, mid)
    permission = next(c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == CLEARSIGHT_PERMISSION)
    original = permission.data['meld_instance']
    settle(table, mid, candidate(combat, mid, KEEP).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].conditions[original].data['concentration'] is False
    assert engine.state.actors[OWNER].conditions[permission.instance_id].data['meld_instance'] == original
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Shape Darkness: Pure Darkness').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Darkness', at=(3, 6)).candidate_id)
    engine = reload(tmp_path, mid)
    area = next(z for z in zones.typed_zones(engine) if z.owner_id == ALLY)
    assert zones.clear_sighted(engine, area, engine.state.actors[OWNER])
    turn(table, mid, OWNER)  # passes permission retirement boundary
    engine = reload(tmp_path, mid)
    assert permission.instance_id in engine.state.actors[OWNER].conditions
    area = next(z for z in zones.typed_zones(engine) if z.owner_id == ALLY)
    assert zones.clear_sighted(engine, area, engine.state.actors[OWNER])
    # Actual renewal still requires a new allied creator decision.
    settle(table, mid, candidate(combat, mid, 'Meld: Clearsight', target=OWNER).candidate_id,
           picks={'choice:needle.clearsight_creator_consent': None})
    engine = reload(tmp_path, mid)
    area = next(z for z in zones.typed_zones(engine) if z.owner_id == ALLY)
    assert not zones.clear_sighted(engine, area, engine.state.actors[OWNER])


@pytest.mark.parametrize('variant', [' (1 CP: Temporary HP)', ' (Persistent)', ' (Persistent) (1 CP: Temporary HP)'])
@pytest.mark.parametrize('depleted', [False, True])
def test_ai_live_mien_keeps_paid_upgrades_reachable_and_committable(tmp_path, variant, depleted):
    def keep_concentration(bundles):
        setup()(bundles)
        # Isolate the depleted-pool admission from an unrelated failed save.
        bundles[0]['actor_template']['saving_throws']['CON'] = 100
        bundles[0].pop('bundle_sha256', None)
        bundles[0]['bundle_sha256'] = canonical_sha256(bundles[0])
    # Keep the empty ally outside the Meld's touch range. Otherwise auto_step
    # can cast on that ally and never exercise upgrading OWNER's live cloak.
    combat, table, mid = fixture(tmp_path, [MIEN, PERSIST], bundle_transform=keep_concentration,
                                ask=False, ally_position={'x': 1, 'y': 6})
    initial = 'Meld: Shadowed Mien' + (' (1 CP: Temporary HP)' if depleted else '')
    settle(table, mid, candidate(combat, mid, initial, target=OWNER).candidate_id)
    if depleted:
        turn(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, 'Test damage', target=OWNER).candidate_id)
    else:
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp == 0
    assert grant(engine, engine.state.actors[OWNER]) is not None
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    name = 'Meld: Shadowed Mien' + variant
    chosen = candidate(combat, mid, name, target=OWNER)
    assert {c.target_ids for c in combat._load_session(mid).engine.legal_candidates()
            if c.source_definition_id == chosen.source_definition_id} == {(OWNER,)}
    policy, _ = combat.policies.for_actor(OWNER)
    combat._dao_policies[OWNER] = policy.model_copy(update={
        'action_priorities': {chosen.source_definition_id: 100}}).model_dump(mode='json')
    settle(table, mid, chosen.candidate_id, auto=True)
    engine = reload(tmp_path, mid)
    uses = [e for e in engine.events if e.event_type == 'INTENT_ACCEPTED']
    assert uses[-1].source_definition_id == chosen.source_definition_id
    assert uses[-1].target_ids == (OWNER,)
    holder = engine.state.actors[OWNER]
    assert grant(engine, holder) is not None
    if 'Temporary HP' in variant:
        assert holder.temporary_hp == 15
    if 'Persistent' in variant:
        assert not grant(engine, holder).data['concentration']
