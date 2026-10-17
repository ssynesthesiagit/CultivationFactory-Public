"""Refined Moonspring Root widens Returning-Spring Guard to 60 feet.

The named-reaction modifier transport (combat/ext/__init__.py) carries an
unconditional ``add_range_ft`` on each attached generic reaction row, so the
reviewed rider types the printed replacement ("within 60 feet instead of 30
feet") as base 30 + 30 = 60.  The base (Awakened) guard keeps its own 30 feet
and the rider's Spring Dew cost, visible-ally wording and total-cover limit stay
in the printed text unchanged.
"""
import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import (OWNER, FOE, ALLY, fixture, settle, candidate,
                                    reload, turn, sealed_native_attack)

V = 'verdant_returning_spring_v0_2B'
GUARD = f'reaction:typed.foundation.{V}.returning_spring_guard'
GUARD_ID = f'foundation.{V}.returning_spring_guard'
DEW = 'resource:foundation.spring_dew'
KIT = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.jian', 'name': 'Jian', 'quantity': 1}]}}


def setup(tmp_path, stage, *, positions):
    doc = sheet([], kit=KIT)
    doc['foundation'] = {'foundation_id': V, 'stage': stage,
        'resource': {'name': 'Spring Dew', 'resource_id': 'tianxia.resource.foundation.' + V,
                     'maximum': 1, 'current': 1}}
    owner = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    for action in owner['action_catalog']:
        if action.get('parameters', {}).get('typed', {}).get('weapon'):
            action['attack_bonus'] = 100
            action['parameters']['typed']['attack_bonus'] = 100
    sealed_native_attack(owner, 'Owner hit', attack_bonus=100, modifier=0, attacks=1)
    owner.pop('bundle_sha256', None); owner['bundle_sha256'] = canonical_sha256(owner)

    def transform(bundles):
        sealed_native_attack(bundles[2], 'Hostile hit', modifier=6, attack_bonus=100, attacks=1)

    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner, ask=True, seed='MOONSPG',
                                 bundle_transform=transform, positions=positions)
    return combat, table, mid


def attack_ally(tmp_path, combat, table, mid, *, use=True):
    """The foe strikes the ally; return the raised prompts and the reloaded engine."""
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Hostile hit', target=ALLY).candidate_id,
                     choices={GUARD: 'USE'} if use else {GUARD: None})
    return prompts, reload(tmp_path, mid)


def guard_outcome(engine, prompts):
    offered = any(p['context']['reaction_source_id'] == GUARD for p in prompts)
    resolved = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == GUARD_ID]
    spent = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
             and e.payload.get('resource_id') == DEW]
    return offered, bool(resolved), spent, engine.state.actors[ALLY].current_hp


# Chebyshev cell metric (max(dx, dy) * 5ft); the y=1 lane keeps a clear line of
# sight past every pillar.
R60 = {OWNER: {'x': 3, 'y': 1}, ALLY: {'x': 15, 'y': 1}, FOE: {'x': 14, 'y': 1}}
R65 = {OWNER: {'x': 3, 'y': 1}, ALLY: {'x': 16, 'y': 1}, FOE: {'x': 15, 'y': 1}}
R35 = {OWNER: {'x': 3, 'y': 1}, ALLY: {'x': 10, 'y': 1}, FOE: {'x': 11, 'y': 1}}
R30 = {OWNER: {'x': 3, 'y': 1}, ALLY: {'x': 9, 'y': 1}, FOE: {'x': 10, 'y': 1}}


@pytest.mark.parametrize('positions,expected', [
    (R60, True),    # Refined admits an ally at exactly 60 feet
    (R65, False),   # Refined denies an ally beyond 60 feet
])
def test_refined_guard_range_boundary(tmp_path, positions, expected):
    combat, table, mid = setup(tmp_path, 'Refined', positions=positions)
    prompts, engine = attack_ally(tmp_path, combat, table, mid)
    offered, resolved, spent, _ = guard_outcome(engine, prompts)
    assert offered == expected
    assert resolved == expected
    assert bool(spent) == expected


@pytest.mark.parametrize('positions,expected', [
    (R30, True),    # the base guard still answers its own 30 feet
    (R35, False),   # the base guard denies beyond 30 feet (no rider here)
])
def test_awakened_guard_keeps_30_feet(tmp_path, positions, expected):
    combat, table, mid = setup(tmp_path, 'Awakened', positions=positions)
    prompts, engine = attack_ally(tmp_path, combat, table, mid)
    offered, resolved, spent, _ = guard_outcome(engine, prompts)
    assert offered == expected
    assert resolved == expected
    assert bool(spent) == expected


def test_refined_guard_spends_one_dew_and_one_reaction(tmp_path):
    combat, table, mid = setup(tmp_path, 'Refined', positions=R60)
    prompts, engine = attack_ally(tmp_path, combat, table, mid)
    offered, resolved, spent, protected = guard_outcome(engine, prompts)
    assert offered and resolved
    assert len(spent) == 1 and spent[0].payload['amount'] == 1
    assert engine.state.actors[OWNER].resources[DEW] == 0
    assert not engine.state.actors[OWNER].reaction_available
    # The protected ally keeps more Hit Points than an unanswered hit would.
    declined_dir = tmp_path / 'declined'
    declined_dir.mkdir()
    combat, table, mid = setup(declined_dir, 'Refined', positions=R60)
    prompts, declined_engine = attack_ally(declined_dir, combat, table, mid, use=False)
    assert declined_engine.state.actors[ALLY].current_hp < protected


def test_refined_guard_commits_cold_reload_and_replay(tmp_path):
    combat, table, mid = setup(tmp_path, 'Refined', positions=R60)
    prompts, engine = attack_ally(tmp_path, combat, table, mid)
    offered, resolved, spent, _ = guard_outcome(engine, prompts)
    assert offered and resolved and len(spent) == 1
    # reload() cold-reloads the saved fight and asserts its mechanical replay passes.
    reload(tmp_path, mid)
