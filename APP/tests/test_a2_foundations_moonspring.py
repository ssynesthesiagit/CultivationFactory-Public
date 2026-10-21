"""Refined Moonspring Root: 60-foot visible-ally guard and twice-PB maximum Hit Points.

Three printed clauses are exercised through real table transactions:

* the range replacement ("within 60 feet instead of 30 feet") is typed as base
  30 + ``add_range_ft`` 30 through the named-reaction modifier transport
  (combat/ext/__init__.py), so the Refined guard reaches 60 feet and the base
  (Awakened) guard keeps its own 30 feet;
* the sight/cover restriction ("an ally you can see", "does not let the guard
  protect targets through total cover") is carried as ``requires_sight_of_subject``
  on the guard row and enforced by combat/ext/reaction_sight.py: the owner must
  perceive the protected ally, so an unseen ally or one behind a sight-blocking
  pillar is refused;
* the Hit Point clause ("the Hit Point increase from Verdant Spring Vessel
  becomes twice your Proficiency Bonus") is a maximum-Hit-Point increase applied
  once while Refined (combat/ext/foundation_moonspring_root.py), not the old
  temporary-Hit-Point grant that rode the guard.
"""
import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from tests.cw2_service_support import add_action
from tests.h1_support import sheet
from tests.worker2_support import (OWNER, FOE, ALLY, fixture, settle, candidate,
                                    reload, turn, sealed_native_attack)

V = 'verdant_returning_spring_v0_2B'
GUARD = f'reaction:typed.foundation.{V}.returning_spring_guard'
GUARD_ID = f'foundation.{V}.returning_spring_guard'
RIDER_ID = f'foundation.{V}.refined_moonspring_root'
DEW = 'resource:foundation.spring_dew'
KIT = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.jian', 'name': 'Jian', 'quantity': 1}]}}


def foundation_sheet(stage):
    doc = sheet([], kit=KIT)
    doc['foundation'] = {'foundation_id': V, 'stage': stage,
        'resource': {'name': 'Spring Dew', 'resource_id': 'tianxia.resource.foundation.' + V,
                     'maximum': 1, 'current': 1}}
    return doc


def guard_row(bundle):
    return next(row for row in bundle['typed_reactions'] if row['feature_id'] == GUARD_ID)


def setup(tmp_path, stage, *, positions, barrier=None, owner_extra=None):
    owner = compile_character(foundation_sheet(stage), actor_id=OWNER, reaction_plan={'ask': True})
    for action in owner['action_catalog']:
        if action.get('parameters', {}).get('typed', {}).get('weapon'):
            action['attack_bonus'] = 100
            action['parameters']['typed']['attack_bonus'] = 100
    sealed_native_attack(owner, 'Owner hit', attack_bonus=100, modifier=0, attacks=1)
    if owner_extra:
        owner_extra(owner)
    owner.pop('bundle_sha256', None); owner['bundle_sha256'] = canonical_sha256(owner)

    def transform(bundles):
        sealed_native_attack(bundles[2], 'Hostile hit', modifier=6, attack_bonus=100, attacks=1)

    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner, ask=True, seed='MOONSPG',
                                 bundle_transform=transform, positions=positions,
                                 battlefield_transform=barrier)
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


def pillar(x, y):
    """One sight-blocking stone pillar cell in the arena the fixture builds (the engine's own terrain)."""
    def transform(arena):
        arena['terrain_regions'].append({
            'region_id': 'test.moonspring_pillar', 'terrain_type': 'BLOCKED', 'movement_cost': 0,
            'description': 'Stone pillar: cannot be entered and blocks line of sight.',
            'cells': [{'x': x, 'y': y}]})
    return transform


def conceal_ally(bundle):
    """A scenario-only synthetic action that makes the struck ally Invisible (sealed setup, not a shipped mechanic)."""
    add_action(bundle, 'Conceal ally', [{'type': 'condition', 'condition': 'invisible', 'applies_to': 'target'}],
               typed={'duration': {'kind': 'until_removed'}})


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


# --- Finding: the guard protected an ally through total cover ---------------------------

def test_refined_guard_refuses_ally_behind_total_cover(tmp_path):
    """"Does not let the guard protect targets through total cover".

    The ally stands at the same 60-foot distance as the passing case above; only a
    sight-blocking pillar differs, so range is not the reason for the refusal.
    """
    combat, table, mid = setup(tmp_path, 'Refined', positions=R60, barrier=pillar(9, 1))
    prompts, engine = attack_ally(tmp_path, combat, table, mid)
    offered, resolved, spent, _ = guard_outcome(engine, prompts)
    assert not offered
    assert not resolved
    assert not spent
    assert engine.state.actors[OWNER].resources[DEW] == 1


def test_awakened_guard_ignores_cover_since_it_names_no_sight(tmp_path):
    """The base printed trigger names no visible ally, so its ally is answered through the pillar (unchanged)."""
    combat, table, mid = setup(tmp_path, 'Awakened', positions=R30, barrier=pillar(6, 1))
    prompts, engine = attack_ally(tmp_path, combat, table, mid)
    offered, resolved, spent, _ = guard_outcome(engine, prompts)
    assert offered and resolved and len(spent) == 1


# --- Finding: the guard protected an ally the owner could not see -----------------------

def test_refined_guard_refuses_unseen_ally(tmp_path):
    """"An ally you can see": an Invisible ally, at 60 feet, is not protected."""
    combat, table, mid = setup(tmp_path, 'Refined', positions=R60, owner_extra=conceal_ally)
    settle(table, mid, candidate(combat, mid, 'Conceal ally', target=ALLY).candidate_id)
    engine = combat._load_session(mid).engine
    assert any(c.condition_id == 'condition:typed.invisible'
               for c in engine.state.actors[ALLY].conditions.values())
    prompts, engine = attack_ally(tmp_path, combat, table, mid)
    offered, resolved, spent, _ = guard_outcome(engine, prompts)
    assert not offered
    assert not resolved
    assert not spent


# --- Finding: the old temporary-Hit-Point reading of the printed HP clause ---------------

def test_refined_moonspring_root_grants_twice_pb_maximum_hp(tmp_path):
    """The Refined owner's maximum Hit Points rise by twice Proficiency Bonus; the Awakened owner is unchanged."""
    base = compile_character(foundation_sheet('Awakened'), actor_id=OWNER, reaction_plan={'ask': True})
    refined = compile_character(foundation_sheet('Refined'), actor_id=OWNER, reaction_plan={'ask': True})
    pb = int(refined['actor_template']['proficiency_bonus'])
    assert refined['actor_template']['maximum_hp'] == base['actor_template']['maximum_hp'] + 2 * pb


def test_refined_moonspring_root_actor_maximum_hp_at_the_table(tmp_path):
    """The twice-PB maximum Hit Points are real at the table, and the guard no longer grants temporary Hit Points."""
    combat, table, mid = setup(tmp_path, 'Refined', positions=R60)
    engine = combat._load_session(mid).engine
    refined_max = engine.state.actors[OWNER].maximum_hp
    awakened_dir = tmp_path / 'awakened'
    awakened_dir.mkdir()
    combat2, table2, mid2 = setup(awakened_dir, 'Awakened', positions=R60)
    awakened_max = combat2._load_session(mid2).engine.state.actors[OWNER].maximum_hp
    assert refined_max == awakened_max + 2 * int(engine.state.actors[OWNER].proficiency_bonus)
    # The old temporary-Hit-Point effect is gone: the guard row carries no temp_hp grant.
    refined_bundle = compile_character(foundation_sheet('Refined'), actor_id=OWNER, reaction_plan={'ask': True})
    assert all(e.get('type') != 'temp_hp' for e in guard_row(refined_bundle).get('effects') or [])
    assert all(e.get('type') != 'temp_hp' for e in guard_row(compile_character(
        foundation_sheet('Awakened'), actor_id=OWNER, reaction_plan={'ask': True})).get('effects') or [])
