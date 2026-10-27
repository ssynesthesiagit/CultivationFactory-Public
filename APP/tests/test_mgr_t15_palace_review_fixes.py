"""MGR-T15 Palace review fixes: own-counter recharge, typed aligned hit, Perfected sphere/cold gate."""
from types import SimpleNamespace

from combat.ext import taiyin_palace as palace
from combat.ext.taiyin_palace import SOURCE, STATE, USED, FOUNDATION, SPHERES, restore_palace, aligned_hit

PALACE_ROW = {'costs': [['resource:uses.palace', 1], ['resource:uses.shared', 1]],
              'parameters': {'typed': {'source': SOURCE, 'palace_admitted': 1}}}
OTHER_ROW = {'costs': [['resource:uses.shared', 1]], 'parameters': {'typed': {'source': 'other.feature'}}}


class Session:
    def __init__(self, resources):
        self.state = {'actors': {'a': {'name': 'Owner', 'resources': dict(resources),
                                       'bundle': {'action_catalog': [PALACE_ROW, OTHER_ROW]}}}}
        self.events = []

    def emit(self, kind, actor_id, **data):
        self.events.append((kind, actor_id, data))


def test_long_rest_recharges_only_palace_own_counter_not_shared_pool():
    session = Session({'resource:uses.palace': 0, 'resource:uses.shared': 0})
    restore_palace(session, 'a')
    assert session.state['actors']['a']['resources'] == {'resource:uses.palace': 1, 'resource:uses.shared': 0}
    assert [e[2]['resource_id'] for e in session.events] == ['resource:uses.palace']


def test_long_rest_leaves_palace_counter_full_without_event():
    session = Session({'resource:uses.palace': 1, 'resource:uses.shared': 0})
    restore_palace(session, 'a')
    assert session.events == []


def _hit_ctx(sphere, damage_type=None):
    engine = SimpleNamespace(state=SimpleNamespace(current_actor_id='a'), events=[])
    field = SimpleNamespace(condition_id=STATE, source_actor_id='a', data={})
    actor = SimpleNamespace(entity_id='a', conditions={STATE: field}, turn_flags={}, proficiency_bonus=3)
    target = SimpleNamespace(entity_id='t')
    ctx = SimpleNamespace(engine=engine, actor=actor, typed={'sphere': sphere},
                          attack_defense_spec={'hit_snapshots': {'taiyin_palace': damage_type} if damage_type else {}})
    return ctx, target, actor


def test_untyped_aligned_hit_skips_bonus_instead_of_inventing_untyped():
    ctx, target, actor = _hit_ctx('tianxia.sphere.yin')
    assert aligned_hit(ctx, target, {}) is None
    assert not actor.turn_flags.get(USED)


def test_aligned_hit_bonus_joins_resolved_hit_damage():
    ctx, target, actor = _hit_ctx('tianxia.sphere.ice', 'cold')
    assert aligned_hit(ctx, target, {}) == 3
    assert actor.turn_flags.get(USED) == 1
    assert aligned_hit(ctx, target, {}) is None


def test_sphere_and_cold_gate_with_public_synthetic_hits():
    assert SPHERES == {'tianxia.sphere.' + s for s in ('yin', 'water', 'dark', 'qiweaving')}
    # Ice technique that is not cold is outside the printed categories: no bonus.
    ctx, target, _ = _hit_ctx('tianxia.sphere.ice', 'force')
    assert aligned_hit(ctx, target, {}) is None
    # A Foundation-aligned Yin technique qualifies by its printed sphere.
    ctx, target, _ = _hit_ctx('tianxia.sphere.yin', 'necrotic')
    assert aligned_hit(ctx, target, {}) == 3
