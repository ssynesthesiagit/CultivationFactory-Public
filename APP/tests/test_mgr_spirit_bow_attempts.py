"""Review regressions: committed concealment misses are attempts, canceled aims are not.

The native school is acquired normally. A test-only table action makes the
target Invisible, and the existing before_attack seam scripts percentile/d20
dice per strike. No ownership, hit or spent-use receipt is injected.
"""
from pathlib import Path

import pytest

from combat import ext, factory_compiler, targeting
from combat.canonical import canonical_sha256
from tests.h1_support import script
from tests.test_mgr_spirit_bow_native import (
    O, F, QI, setup, fight, manifest, commit, option, cold, held, next_turn,
)


def concealed_table(tmp_path, monkeypatch, *, extra=False, first_misses=True):
    original = factory_compiler.compile_character

    def compile_with_setup(*args, **kwargs):
        bundle = original(*args, **kwargs)
        if kwargs.get('actor_id') == O:
            source = 'action:test.spirit_bow_conceal_target'
            bundle['actor_template']['action_ids'].append(source)
            bundle['action_catalog'].append({
                'source_definition_id': source, 'display_name': 'Conceal test target',
                'owner_id': O, 'economy': 'ACTION', 'resolution_kind': 'TYPED',
                'target_kind': 'HOSTILE_ENTITY', 'range_ft': 120,
                'parameters': {'typed': {'source': source, 'numbers': {},
                    'duration': {'kind': 'one_minute'}, 'effects': [
                        {'type': 'condition', 'condition': 'invisible',
                         'duration': {'kind': 'one_minute'}, 'applies_to': 'target'}]}}})
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
        return bundle

    monkeypatch.setattr(factory_compiler, 'compile_character', compile_with_setup)
    monkeypatch.setattr(targeting, 'rules', lambda: dict(targeting.LEGACY_POLICY))
    c, t, j = setup(tmp_path, owner_mids=[
        'tianxia.path.body_refining.feature.extra_attack'] if extra else [])
    mid = fight(c, t, j)
    manifest(t, mid)
    commit(t, mid, option(t, mid, 'Conceal test target', F))
    next_turn(t, mid)
    assert held(cold(c, mid), F, 'condition:typed.invisible')

    def dice(engine, actor, target, intent, context):
        if actor.entity_id == O and '.spirit_bow.' in context['source_id']:
            # Each table preview/continuation starts its own deterministic script.
            miss = first_misses and context['attack_index'] == 1
            script(engine, [1] if miss else [100, 20, 20, *([8] * 30)])

    monkeypatch.setitem(ext._HOOKS, 'before_attack', [*ext._HOOKS.get('before_attack', []), dice])
    return c, t, mid


def concealment_events(engine):
    return [e for e in engine.events if e.actor_id == O and
            'miss_chance_percent' in e.payload]


def test_heaven_concealment_miss_consumes_scene_use_after_reload(tmp_path, monkeypatch):
    c, t, mid = concealed_table(tmp_path, monkeypatch)
    commit(t, mid, option(t, mid, 'Heaven-Sundering Arrow: Projected Spirit Bow', F))
    engine = cold(c, mid)
    assert concealment_events(engine)[-1].payload['missed']
    assert not any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == O for e in engine.events)
    assert engine.state.actors[O].resources[QI] == 91
    assert held(engine, O, 'condition:typed.spirit_bow_scene_use')
    next_turn(t, mid)
    assert not any(g['label'].startswith('Heaven-Sundering') for g in t.state(mid)['menu']['actions'])


def test_revealing_cannot_move_to_later_hit_after_concealment_miss(tmp_path, monkeypatch):
    c, t, mid = concealed_table(tmp_path, monkeypatch, extra=True)
    commit(t, mid, option(t, mid, 'Spirit Bow attack + Revealing Arrow', F))
    engine = cold(c, mid)
    checks = concealment_events(engine)
    assert len(checks) >= 2 and checks[0].payload['missed'] and not checks[1].payload['missed']
    assert any(e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == O and F in e.target_ids
               for e in engine.events), 'A later qualifying attack must actually hit'
    assert engine.state.actors[O].resources[QI] == 98
    assert engine.state.actors[O].turn_flags['spirit_bow_seeking'] == 1
    assert not held(engine, F, 'condition:typed.spirit_bow_revealed')


@pytest.mark.parametrize('label', [
    'Heaven-Sundering Arrow: Projected Spirit Bow', 'Spirit Bow attack + Revealing Arrow'])
def test_canceled_attack_does_not_consume_scene_or_seeking_use(tmp_path, monkeypatch, label):
    c, t, mid = concealed_table(tmp_path, monkeypatch)

    def cancel(ctx, target, effect):
        if ctx.actor.entity_id == O:
            return False

    monkeypatch.setitem(ext._HOOKS, 'attack_allowed', [*ext._HOOKS.get('attack_allowed', []), cancel])
    commit(t, mid, option(t, mid, label, F))
    engine = cold(c, mid)
    assert not concealment_events(engine)
    assert not held(engine, O, 'condition:typed.spirit_bow_scene_use')
    assert not engine.state.actors[O].turn_flags.get('spirit_bow_seeking')


def test_shared_information_and_bundle_hook_contracts_are_documented():
    registry = (Path(__file__).resolve().parents[1] / 'combat/ext/__init__.py').read_text()
    for contract in (
        'journey_combat_bundle(bundle, session, actor_id)',
        'observer_information_rows(engine, viewer)',
    ):
        assert contract in registry
