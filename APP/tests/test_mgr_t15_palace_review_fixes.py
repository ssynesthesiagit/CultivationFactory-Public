"""MGR-T15 Palace review fixes: own-counter recharge, typed aligned hit, Perfected sphere/cold gate."""
import json
import re
from types import SimpleNamespace

from combat.ext import taiyin_palace as palace
from combat.ext.taiyin_palace import SOURCE, STATE, USED, FOUNDATION, SPHERES, restore_palace, aligned_hit
from combat import typed_executor
from pathlib import Path

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
                          hit_snapshots={'taiyin_palace': damage_type} if damage_type else {})
    return ctx, target, actor


def _spy(monkeypatch):
    calls = []
    monkeypatch.setattr(typed_executor, 'run_effects', lambda ctx, effects: calls.append(effects))
    return calls


def test_untyped_aligned_hit_skips_bonus_instead_of_inventing_untyped(monkeypatch):
    calls = _spy(monkeypatch)
    ctx, target, actor = _hit_ctx('tianxia.sphere.yin')
    aligned_hit(ctx, target, 'technique')
    assert calls == []
    assert not actor.turn_flags.get(USED)


def test_aligned_hit_bonus_uses_resolved_hit_damage_type(monkeypatch):
    calls = _spy(monkeypatch)
    ctx, target, actor = _hit_ctx('tianxia.sphere.ice', 'cold')
    aligned_hit(ctx, target, 'technique')
    assert len(calls) == 1
    (effect,) = calls[0]
    assert effect['type'] == 'extra_damage' and effect['flat'] == 3
    assert effect['damage_types'] == ['cold'] and 'UNTYPED' not in json.dumps(effect)
    assert actor.turn_flags.get(USED) == 1


def test_sphere_and_cold_gate_matches_rules_text(monkeypatch):
    rules = json.loads((Path(__file__).resolve().parents[1] / 'authority' / 'typed_mechanics' / 'rules_text.json').read_text())
    text = str(rules[SOURCE])
    assert 'cold, Yin, Water, Dark, or Qiweaving technique' in text
    assert SPHERES == {'tianxia.sphere.' + s for s in ('yin', 'water', 'dark', 'qiweaving')}
    # Ice technique that is not cold is outside the printed categories: no bonus.
    calls = _spy(monkeypatch)
    ctx, target, _ = _hit_ctx('tianxia.sphere.ice', 'force')
    aligned_hit(ctx, target, 'technique')
    assert calls == []
    # A Foundation-aligned Yin technique qualifies by its printed sphere.
    calls = _spy(monkeypatch)
    ctx, target, _ = _hit_ctx('tianxia.sphere.yin', 'necrotic')
    aligned_hit(ctx, target, 'technique')
    assert calls and calls[0][0]['damage_types'] == ['necrotic']
