"""AUTO130r3 review fixes: the chosen Star-Drawn Projectile benefit belongs to the attack that is actually made.

Every case plays the real CombatService + TabletopService table and commits, reloads and looks at the reloaded fight.

* F1: an attack that is cancelled before its roll (an attacked reaction answers it first) must not leave Half Cover
  suppressed on the creature it was aimed at; the next attack on that creature still finds its cover.
* F2: Starbolt's printed "Aligned Benefit: ... range increases by 30 feet" and Star-Drawn Projectile's printed "increase range
  by 60 feet" compose, so a marked target beyond either bonus alone is reachable -- and an unmarked target is not.
* F3: when the engine re-aims the attack, the Half Cover exception and the marked-target push follow the creature the attack
  really strikes, and neither the creature it was aimed at nor the one it struck keeps anything afterwards.

Fixtures. The two-creature table is tests.auto_worker1_support.fight, as the other Stars regressions use. The three-creature
table adds the caster's own ally, because a redirection needs a second recipient. The one stand-in is the redirection itself:
the test registers a provider on the engine's own attack-redirection bus (combat/ext/redirection.py, the single owner of the
retarget_attack hook) in place of a printed redirection such as Defensive Rider or Misdirected Attack. It answers exactly one
tested attack (including service previews and transactional retries), and is removed when the test finishes. F1's cancelling reaction is a real
compiled "attacked" row (the Illusion talent False Double) whose printed d20 answer and price are fixed in the fixture, so the
cancellation is certain and happens once.
"""
import json
import zipfile
from contextlib import contextmanager
import pytest

from combat.canonical import canonical_sha256
from combat.ext import redirection, stars
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.hunt15_support import LEFT, RIGHT, act, reload, turn
from tests.auto_worker1_support import fight
from tests.test_auto130_stars import BOLT, COVER, DRAWN, PUSH, RANGE, resolve
from tests.test_carry import KIT

ALLY = "actor:factory.auto130r3f1.ally"
FALSE_DOUBLE = "TAL_ILLUSION_FALSE_DOUBLE"
NO_HALF_COVER = "condition:an_eui.break_guard.no_half_cover"
BOULDERS = {"terrain_type": "SIMPLE_COVER", "movement_cost": 1,
            "cells": [{"x": 5, "y": 6}, {"x": 6, "y": 6}]}
PLACES = {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 9, "y": 6}}
TRIO_PLACES = {LEFT: {"x": 3, "y": 6}, ALLY: {"x": 7, "y": 6}, RIGHT: {"x": 12, "y": 6}}


def boulders(arena):
    arena["terrain_regions"] = [BOULDERS]


def mark_row(subject="target"):
    return {"type": "mark", "mark": stars.MARK, "applies_to": subject, "duration": {"kind": "until_removed"}}


def covers(engine, who):
    return engine._raw_cover_bonus_actor_to_actor(engine.state.actors[LEFT], engine.state.actors[who])


def rolled(engine, source=None, target=None):
    """The attack rolls this fight recorded, most recent first."""
    out = [event for event in engine.events if event.event_type == "ATTACK_ROLLED" and event.actor_id == LEFT]
    if source:
        out = [event for event in out if source in str(event.source_definition_id)]
    if target:
        out = [event for event in out if tuple(event.target_ids) == (target,)]
    return out


def no_cover_left(engine):
    return {who: [c.condition_id for c in engine.state.actors[who].conditions.values() if c.condition_id == NO_HALF_COVER]
            for who in (LEFT, RIGHT, ALLY) if who in engine.state.actors}


# ---------------------------------------------------------------------------- F1: a cancelled attack leaves no cover behind
def negates_one_attack(bundle):
    """RIGHT answers an attack on it before the roll, exactly once.

    The row is the talent's own compiled "attacked" reaction; the fixture fixes its rolled answer (any d20) and charges its
    whole pool, so the attack under test is cancelled with certainty and no later attack is.
    """
    if bundle["actor_id"] != RIGHT:
        return
    row = next(r for r in bundle["typed_reactions"] if r["feature_id"] == FALSE_DOUBLE)
    row["name"] = "Test: Negate This Attack"
    row["effects"] = [{"type": "negate_attack", "chance_d20": 1,
                       "evidence": "the attack on this creature is negated (test fixture)"}]
    row["costs"] = [{"resource_id": "resource:core.qi", "amount": 100}]


def test_a_cancelled_attack_leaves_no_cover_suppressed_for_the_next_attack(tmp_path):
    """F1: the Half Cover exception lasts the attack that took it, even when that attack never rolls."""
    combat, table, mid = fight(tmp_path, [DRAWN, BOLT], right_talents=[FALSE_DOUBLE], bundle_edit=negates_one_attack,
                               arena_edit=boulders, positions=PLACES, cl=17)
    bolt = next(a for a in reload(combat, mid).action_catalog.values() if a.source_definition_id.endswith(BOLT))
    assert covers(reload(combat, mid), RIGHT) == 2, "the fixture must give the target real Half Cover"
    assert act(table, mid, COVER)['status'] == 'COMMITTED'

    resolve(lambda answers: act(table, mid, 'Starbolt', answers, target_id=RIGHT))
    engine = reload(combat, mid)
    assert not rolled(engine, source=BOLT), "the fixture's reaction must cancel the attack before its roll"
    applied = [e for e in engine.events if e.event_type == 'CONDITION_APPLIED' and e.payload.get('condition_id') == NO_HALF_COVER]
    released = [e for e in engine.events if e.event_type == 'CONDITION_REMOVED' and e.payload.get('condition_id') == NO_HALF_COVER]
    assert applied and released, "the cancelled attack took the exception and gave it back"
    assert not any(no_cover_left(engine).values()), no_cover_left(engine)

    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    resolve(lambda answers: act(table, mid, 'Starbolt', answers, target_id=RIGHT))
    engine = reload(combat, mid)
    later = rolled(engine, source=BOLT, target=RIGHT)
    assert later, "the next attack on that creature must still be rolled"
    assert later[-1].payload['cover_bonus'] == 2, later[-1].payload
    assert later[-1].payload['target_ac'] == engine.state.actors[RIGHT].armor_class + 2, later[-1].payload
    assert bolt.display_name == 'Starbolt'


# ---------------------------------------------------------------------------- F2: the two printed range bonuses compose
def yard(arena):
    arena.update(width_squares=50, height_squares=20, terrain_regions=[])


def distant_prepare(bundle):
    """Only the synthetic prerequisite action needs to place a mark at the range boundary."""
    for action in bundle['action_catalog']:
        if action['display_name'] == 'Prepare':
            action['range_ft'] = 180


def test_cancelled_first_strike_does_not_lend_cover_benefit_to_second(tmp_path):
    from tests.test_solfauto130r2_stars import repeated_bolt

    def setup(bundle):
        negates_one_attack(bundle)
        repeated_bolt(bundle)

    combat, table, mid = fight(tmp_path, [DRAWN, BOLT], right_talents=[FALSE_DOUBLE], bundle_edit=setup,
                               arena_edit=boulders, positions=PLACES, cl=17)
    assert act(table, mid, COVER)['status'] == 'COMMITTED'
    resolve(lambda answers: act(table, mid, 'Starbolt', answers, target_id=RIGHT))
    engine = reload(combat, mid)
    assert len(rolled(engine, source=BOLT)) == 1
    assert rolled(engine, source=BOLT)[0].payload['cover_bonus'] == 2
    assert not any(no_cover_left(engine).values())


def test_composed_clone_preserves_standing_aligned_range_for_later_strikes(tmp_path):
    combat, _, mid = fight(tmp_path, [DRAWN, BOLT])
    composed = _bolt_variants(reload(combat, mid))['aligned#drawn_range']
    assert composed.parameters['stars_drawn_original_range']['normal'] == 120
    assert all(eff.get('later_reach_ft') == 120 for eff in composed.parameters['typed']['effects']
               if eff.get('type') == 'attack')


def test_cover_cleanup_preserves_a_preexisting_exception(tmp_path):
    combat, table, mid = fight(tmp_path, [DRAWN, BOLT], arena_edit=boulders, positions=PLACES,
        prepare=[{'type': 'destruction_no_half_cover', 'applies_to': 'target'}])
    assert act(table, mid, 'Prepare', target_id=RIGHT)['status'] == 'COMMITTED'
    before = {iid: c.model_dump(mode='json') for iid, c in reload(combat, mid).state.actors[RIGHT].conditions.items()
              if c.condition_id == NO_HALF_COVER}
    assert before
    assert act(table, mid, COVER)['status'] == 'COMMITTED'
    resolve(lambda answers: act(table, mid, 'Starbolt', answers, target_id=RIGHT))
    after = {iid: c.model_dump(mode='json') for iid, c in reload(combat, mid).state.actors[RIGHT].conditions.items()
             if c.condition_id == NO_HALF_COVER}
    assert after == before


def _bolt_variants(engine):
    return {a.source_definition_id.split('#', 1)[-1] if '#' in a.source_definition_id else 'plain': a
            for a in engine.action_catalog.values()
            if a.owner_id == LEFT and a.source_definition_id.split('.')[-1].split('#')[0] == BOLT}


def _labels(table, mid):
    return [g['label'] for g in table.state(mid)['menu']['actions']]


def test_aligned_and_drawn_ranges_compose_for_a_marked_target(tmp_path):
    """F2: +30 feet and +60 feet compose at the marked-target 180-foot boundary."""
    combat, table, mid = fight(tmp_path, [DRAWN, BOLT], prepare=[mark_row()], prepare_target='ANY_CREATURE',
                               arena_edit=yard, bundle_edit=distant_prepare, cl=17, left_attack_bonus=100,
                               positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 39, 'y': 6}})
    assert act(table, mid, 'Prepare', target_id=RIGHT)['status'] == 'COMMITTED'
    assert act(table, mid, RANGE)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    bolt = _bolt_variants(engine)['plain']
    composed = _bolt_variants(engine)['aligned#drawn_range']
    assert bolt.range_ft == 90, bolt.range_ft
    assert composed.range_ft == 180 and composed.parameters['typed']['range_ft'] == 180, composed.parameters['typed']
    assert any('+30 ft' in label and '+60 ft' in label for label in _labels(table, mid)), _labels(table, mid)

    resolve(lambda answers: act(table, mid, composed.display_name, answers, target_id=RIGHT))
    engine = reload(combat, mid)
    assert rolled(engine, target=RIGHT), "the composed sibling must be a legal attack at 180 feet"
    assert not any(c.condition_id == stars.DRAWN_RANGE for c in engine.state.actors[LEFT].conditions.values())


def test_the_composed_range_is_refused_for_an_unmarked_target(tmp_path):
    """F2: the +30 feet requires alignment; an unmarked target at 180 feet is ineligible."""
    combat, table, mid = fight(tmp_path, [DRAWN, BOLT], arena_edit=yard, cl=17, left_attack_bonus=100,
                               positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 39, 'y': 6}})
    assert act(table, mid, RANGE)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert any(c.condition_id == stars.DRAWN_RANGE for c in engine.state.actors[LEFT].conditions.values())
    assert not [label for label in _labels(table, mid) if '+30 ft' in label and '+60 ft' in label], _labels(table, mid)
    assert not rolled(reload(combat, mid), target=RIGHT)


# ---------------------------------------------------------------------------- F3: the benefits follow the attack's real recipient
def trio(tmp_path, *, left=(), right=(), ally=(), prepare=(), prepare_target='ANY_CREATURE', positions=None, cl=17,
         left_attack_bonus=100, arena_edit=None, bundle_edit=None):
    """The worker-1 table plus the caster's own ally, so a redirection has a second recipient that is not the attacker."""
    bundles = []
    for aid, owned in ((LEFT, left), (RIGHT, right), (ALLY, ally)):
        doc = sheet(list(owned), cl=cl, dc=100, kit={"starting_kit": KIT}, score=14)
        stats = doc["ability_scores_and_statistics"]
        stats["primary_resource"]["maximum"] = 100
        stats["hit_points"]["maximum"] = 1000
        stats["armor_class"]["base_value"] = 1
        stats["technique_attack_bonus"] = left_attack_bonus
        doc["identity"]["display_name"] = {LEFT: "Keeper", RIGHT: "Visitor", ALLY: "Comrade"}[aid]
        folder = tmp_path / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
        bundle = compile_character(doc, actor_id=aid, reaction_plan={"ask": True})
        if prepare and aid == LEFT:
            action_id = "action:test.auto130r3f1.prepare"
            bundle["actor_template"]["action_ids"].append(action_id)
            bundle["action_catalog"].append({
                "source_definition_id": action_id, "display_name": "Prepare", "owner_id": aid,
                "economy": "NONE", "resolution_kind": "TYPED", "target_kind": prepare_target,
                "range_ft": 60, "costs": [],
                "parameters": {"typed": {"effects": list(prepare),
                                         "numbers": {"cl": cl, "pb": 4, "key_mod": 3, "save_dc": 100},
                                         "duration": {"kind": "instant"}, "riders": []}}})
        if bundle_edit is not None:
            bundle_edit(bundle, aid)
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
        bundles.append(bundle)
    combat = CombatService(ROOT, tmp_path)
    arena = combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    arena['terrain_regions'] = []
    if arena_edit is not None:
        arena_edit(arena)
    roster = [LEFT, RIGHT, ALLY]
    mid = combat._finish_factory_match(
        bundles, roster, {LEFT: "team:factory", ALLY: "team:factory", RIGHT: "team:opponents"},
        positions or TRIO_PLACES, arena, [LEFT, ALLY], [RIGHT],
        control_modes={aid: "MANUAL" for aid in roster}, match_seed="auto130r3f1",
        display_name="AUTO130r3f1 regression", maximum_rounds=10)["match_id"]
    table = TabletopService(combat, tmp_path)
    turn(table, mid, LEFT)
    return combat, table, mid


@contextmanager
def redirected_attack(onto, source_id="ability:test.auto130r3f1.redirect"):
    """One of the caster's attacks is re-aimed, through the engine's own redirection seam.

    combat/ext/redirection.py owns the retarget_attack hook for every printed redirection; this registers a provider in its
    place so the test can ask for the re-aim itself. It answers only this fixture's attack, including previews and retries.
    """
    armed = {}

    def provider(engine, attacker, defender, intent, context):
        # Service previews and transactional choice retries must see the same redirect.
        if not armed.get("pending") or attacker.entity_id != LEFT or defender.entity_id != RIGHT:
            return None
        return {"source_id": source_id, "target_id": onto, "cover_bonus": 0}

    redirection._PROVIDERS.append((5, "test.auto130r3f1.redirect", provider))
    redirection._PROVIDERS.sort(key=lambda row: (row[0], row[1]))
    try:
        yield lambda: armed.update(pending=True)
    finally:
        redirection._PROVIDERS[:] = [row for row in redirection._PROVIDERS if row[1] != "test.auto130r3f1.redirect"]


@pytest.mark.parametrize('recipient_marked', [True, False])
def test_the_push_follows_the_marked_creature_a_redirected_attack_hits(tmp_path, recipient_marked):
    """F3: the attack was aimed at an unmarked creature and re-aimed onto a marked one: the printed push moves the one it hits."""
    combat, table, mid = trio(tmp_path, left=[DRAWN, BOLT], prepare=[mark_row()])
    assert act(table, mid, 'Prepare', target_id=ALLY if recipient_marked else RIGHT)['status'] == 'COMMITTED'
    assert act(table, mid, PUSH)['status'] == 'COMMITTED'
    before = reload(combat, mid).state.actors[ALLY].position
    original_before = reload(combat, mid).state.actors[RIGHT].position
    with redirected_attack(ALLY) as on_next_attack:
        on_next_attack()
        resolve(lambda answers: act(table, mid, 'Starbolt', answers, target_id=RIGHT))
    engine = reload(combat, mid)
    retargeted = [e for e in engine.events if e.event_type == 'ATTACK_RETARGETED']
    assert retargeted and retargeted[-1].payload['original_target_id'] == RIGHT, [e.payload for e in retargeted]
    assert tuple(retargeted[-1].target_ids) == (ALLY,), retargeted[-1].target_ids
    assert rolled(engine, target=ALLY), "the re-aimed attack is rolled against its new target"
    assert not rolled(engine, target=RIGHT)
    after = engine.state.actors[ALLY].position
    assert engine.grid.distance_ft(before, after) == (10 if recipient_marked else 0), (before, after)
    assert engine.state.actors[RIGHT].position == original_before
    assert not any(no_cover_left(engine).values()), no_cover_left(engine)


def test_a_redirected_attack_gives_its_cover_only_to_the_creature_it_hits(tmp_path):
    """F3: aimed at a marked creature, re-aimed onto an unmarked one: Half Cover is ignored for the creature actually hit."""
    combat, table, mid = trio(tmp_path, left=[DRAWN, BOLT], prepare=[mark_row()], arena_edit=boulders)
    assert act(table, mid, 'Prepare', target_id=RIGHT)['status'] == 'COMMITTED'
    assert act(table, mid, COVER)['status'] == 'COMMITTED'
    assert covers(reload(combat, mid), ALLY) == 2, "the fixture must give the re-aimed target real Half Cover"
    with redirected_attack(ALLY) as on_next_attack:
        on_next_attack()
        resolve(lambda answers: act(table, mid, 'Starbolt', answers, target_id=RIGHT))
    engine = reload(combat, mid)
    assert rolled(engine, target=ALLY)
    assert rolled(engine, target=ALLY)[-1].payload['cover_bonus'] == 0, rolled(engine, target=ALLY)[-1].payload
    assert covers(engine, ALLY) == 2, "the exception must not outlive the attack"
    assert not any(no_cover_left(engine).values()), no_cover_left(engine)
    assert not [event for event in engine.events if event.event_type == 'FORCED_MOVED'], "an unmarked target is not pushed"
