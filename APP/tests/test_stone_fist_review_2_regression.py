"""Regression tests for the Stone Fist review-2 findings (P1 scalar callbacks, P2 pooled Threshold,
Heaven-Cracking shared settlement, Overwhelming Blow extended-reach step-in)."""
from dataclasses import dataclass, field, replace
from types import SimpleNamespace
import pytest


# ---------------------------------------------------------------- P1: component-free callbacks keep scalar contract
def test_component_free_callback_returns_residual_scalar(monkeypatch):
    from combat import ext, attack_components as ac

    def reduce(engine, target, amount, kind, source, actor):
        return 2
    monkeypatch.setattr(ext, 'callbacks', lambda point: (reduce,) if point == 'incoming_damage' else ())
    monkeypatch.setattr(ext, 'invoke', lambda point, fn, *a, **k: fn(*a, **k))
    assert ac.callbacks('incoming_damage', None, None, 9, 'BLUDGEONING', 'src', 'actor', []) == 7


def test_component_free_callback_without_subscribers_keeps_full_hit(monkeypatch):
    from combat import ext, attack_components as ac
    monkeypatch.setattr(ext, 'callbacks', lambda point: ())
    assert ac.callbacks('incoming_damage', None, None, 9, 'BLUDGEONING', 'src', 'actor', []) == 9


def test_scalar_counterpart_in_component_module_still_runs_without_components(monkeypatch):
    # Same-module scalar counterpart (dreamweaver pattern): it must run when there are no components.
    from combat import ext, attack_components as ac

    def scalar(engine, target, amount, kind, source, actor):
        return 3
    def component(engine, target, parts, source, actor):
        raise AssertionError('component provider must not run for component-free damage')
    scalar.__module__ = component.__module__ = 'combat.ext.fixture_provider'
    monkeypatch.setattr(ext, 'callbacks', lambda point: (scalar,) if point == 'incoming_damage' else
                        ((component,) if point == 'incoming_damage_components' else ()))
    monkeypatch.setattr(ext, 'invoke', lambda point, fn, *a, **k: fn(*a, **k))
    assert ac.callbacks('incoming_damage', None, None, 8, 'BLUDGEONING', 'src', 'actor', []) == 5


# ---------------------------------------------------------------- P2: Damage Threshold pooled across non-bypassed portions
class _Dumped:
    def __init__(self, data):
        self.data = data

    def model_dump(self, mode=None):
        return dict(self.data)


class _FakeObject:
    def __init__(self, **data):
        self.__dict__.update(data)

    def model_copy(self, update):
        return _Dumped({**self.__dict__, **update})

    def model_dump(self, mode=None):
        return dict(self.__dict__)

    @staticmethod
    def model_validate(data):
        return _FakeObject(**data)


def _object(threshold=25, hp=100):
    return _FakeObject(object_id='wall', current_hp=hp, maximum_hp=hp, destroyed=False, component={},
                       damage_threshold=threshold, damage_immunities=(), artifact=False)


@pytest.fixture
def object_seam(monkeypatch):
    from combat import ext, gate2_runtime_models
    from combat.ext import sound_objects
    monkeypatch.setattr(gate2_runtime_models, 'RuntimeObjectState', _FakeObject)
    monkeypatch.setattr(sound_objects, 'consume_exposure', lambda engine, obj, packets: (obj, ()))
    monkeypatch.setattr(ext, 'run', lambda *a, **k: [])
    monkeypatch.setattr(ext, 'run_strict', lambda *a, **k: [])
    engine = SimpleNamespace(state=SimpleNamespace(objects={}), _append_event=lambda *a, **k: None)
    actor = SimpleNamespace(entity_id='actor')
    return engine, actor


def test_fracture_portion_meets_threshold_with_combined_instance(object_seam):
    from combat.ext.objects import deal
    engine, actor = object_seam
    obj = _object(threshold=25)
    # Neither the base 8 nor the Fracture 20 reaches Threshold 25 alone; the one 28-point attack does.
    result = deal(engine, actor, obj, [(8, 'BLUDGEONING')], 'strike',
                  components=({'amount': 20, 'damage_type': 'FORCE', 'multiplier': 1},))
    assert result['total'] == 28


def test_fracture_multiplier_still_applies_after_combined_threshold(object_seam):
    from combat.ext.objects import deal
    engine, actor = object_seam
    obj = _object(threshold=25)
    result = deal(engine, actor, obj, [(8, 'BLUDGEONING')], 'strike',
                  components=({'amount': 20, 'damage_type': 'FORCE', 'multiplier': 2},))
    assert result['total'] == 48


def test_combined_instance_under_threshold_still_has_no_effect(object_seam):
    from combat.ext.objects import deal
    engine, actor = object_seam
    obj = _object(threshold=25)
    result = deal(engine, actor, obj, [(8, 'BLUDGEONING')], 'strike',
                  components=({'amount': 10, 'damage_type': 'FORCE', 'multiplier': 1},))
    assert result['total'] == 0


# ---------------------------------------------------------------- Heaven-Cracking Blow: shared settlement
@dataclass
class _Ctx:
    engine: object
    actor: object
    target: object
    typed: dict = field(default_factory=dict)
    numbers: dict = field(default_factory=dict)
    damage_cache: dict = field(default_factory=dict)
    attack_defense_spec: object = None
    damage_source: str = 'strike'
    critical_hit: bool = False
    attack_damage_context: object = None
    source: str = ''

    def on_hit_context(self, target, **kw):
        return replace(self, target=target, **kw)

    def with_source(self, feature):
        return replace(self, source=feature)


@pytest.fixture
def heaven_seam(monkeypatch):
    from combat import typed_executor as te
    from combat.ext import stone_fist, creature_kinds
    monkeypatch.setattr(stone_fist, 'body_level', lambda engine, actor: 10)
    monkeypatch.setattr(stone_fist, '_cl', lambda engine, entity_id: 0)
    monkeypatch.setattr(creature_kinds, 'matches', lambda target, kind: False)
    monkeypatch.setattr(te, '_damage_roll', lambda sub, effect: (7, 'FORCE'))
    def no_direct(*a, **k):
        raise AssertionError('Heaven-Cracking Blow must settle with its triggering attack, not as a separate packet')
    monkeypatch.setattr(te, 'run_effects', no_direct)
    monkeypatch.setattr(te, '_deal', no_direct)
    return stone_fist, te


def test_heaven_cracking_extra_joins_attack_components(heaven_seam):
    stone_fist, _te = heaven_seam
    spec = {'damage_components': []}
    engine = SimpleNamespace(rolls=[], state=SimpleNamespace(objects={}))
    ctx = _Ctx(engine=engine, actor=SimpleNamespace(entity_id='a'), target=SimpleNamespace(entity_id='t'),
               attack_defense_spec=spec)
    stone_fist._additional(ctx, {}, 10, 10, heaven=True)
    assert len(spec['damage_components']) == 1
    part = spec['damage_components'][0]
    assert part['amount'] == 7 and part['damage_type'] == 'FORCE' and part['ignore_resistance'] is True


def test_heaven_cracking_construct_doubling_settles_with_attack(heaven_seam, monkeypatch):
    stone_fist, _te = heaven_seam
    from combat.ext import creature_kinds
    monkeypatch.setattr(creature_kinds, 'matches', lambda target, kind: kind == 'construct')
    spec = {'damage_components': []}
    engine = SimpleNamespace(rolls=[], state=SimpleNamespace(objects={}))
    ctx = _Ctx(engine=engine, actor=SimpleNamespace(entity_id='a'), target=SimpleNamespace(entity_id='t'),
               attack_defense_spec=spec)
    stone_fist._additional(ctx, {}, 10, 10, heaven=True)
    assert spec['damage_components'][0]['amount'] == 14


# ---------------------------------------------------------------- Overwhelming Blow: extended-reach step-in
def test_overwhelming_step_in_routes_from_extended_reach(monkeypatch):
    from combat import typed_executor as te, movement_paths, granted_movement
    from combat.ext import stone_fist
    former = SimpleNamespace(x=5, y=0)
    start = SimpleNamespace(x=0, y=0)
    mid = SimpleNamespace(x=2, y=0)
    target = SimpleNamespace(entity_id='t', active=True, position=former)
    actor = SimpleNamespace(entity_id='a', active=True, position=start)
    moved = SimpleNamespace(x=6, y=0)

    def push(ctx, effects):
        target.position = moved
    monkeypatch.setattr(te, 'run_effects', push)
    recorded = []
    monkeypatch.setattr(movement_paths, 'resolve', lambda engine, actor_, path, source, **kw: recorded.append(list(path)))
    monkeypatch.setattr(granted_movement, 'path_cost', lambda engine, actor_, path, **kw: 10)
    grid = SimpleNamespace(placement_legal=lambda *a, **k: True,
                           distance_ft=lambda a, b: 10,  # extended reach: start is 10 ft away
                           square_size_ft=5,
                           shortest_path=lambda s, g, **k: ((s, mid, g), 10))
    engine = SimpleNamespace(grid=grid, _footprint=lambda a: None, _occupied_cells_except=lambda i: ())
    ctx = SimpleNamespace(engine=engine, actor=actor, target=target, intent=None)
    stone_fist.overwhelming_step_in(ctx, {})
    assert recorded == [[start, mid, former]]
