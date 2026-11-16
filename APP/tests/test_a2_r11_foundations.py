"""Lane A2R01: Dragon-Wind, Dream-Mirror and Heaven-Tyrant foundation automation.

Every test drives the real TabletopService through CombatService, answers the
printed prompts, and cold-reloads the committed fight, so what runs is the
shipped ability, not a stand-in. The three foundations share one harness:
the owner's sheet names its Foundation and its own resource pool, the foe
carries a printed-style grapple (a Strength save whose failure Grapples) and
the owner carries a typed escape and a typed strike, so the table-level
triggers (a hit, a miss, a failed save, a grapple escape) are the engine's
own, not a patched one.

Printed text (authority/typed_mechanics/rules_text.json):
- Dragon-Marrow Drive: "the added damage becomes 1d4 + PB, of the attack or
  technique's damage type ... the target chooses a Strength or Dexterity
  saving throw against your Cultivation Save DC. Failed Save: It cannot take
  Reactions until the end of its next turn."
- Storm-Marrow Guard: "after the triggering damage resolves, move 5 feet (10
  feet for thunder, lightning or falling damage) to a legal space without
  provoking opportunity attacks from the triggering creature."
- Wind-Body Step: "Momentum Step's distance becomes 15 feet ... gain
  advantage on the next Athletics or Acrobatics check before the end of turn."
- Sovereign Momentum: "choose two different legal Momentum Conversion options
  instead of one. This does not cost a second Momentum."
- Reflection Cut: "add PB Psychic or Force damage to that later hit or
  damaging effect; the type is chosen when the resource is spent."
- True-Name Witness: "add PB to the roll" before the outcome is known.
- Truth Behind the Mask: "add another PB" against illusion, dream, disguise,
  memory, charm, possession or identity manipulation; on success the witness
  learns one symbolic truth about the source.
- Dream-Mirror Domain: "hostile misses or failed saves against you or an ally
  in the domain also generate your Mirror Trace ... once per round when you
  spend Mirror Trace, increase the numeric benefit by PB."
- Generate Tyrant Form Pulse: "you succeed on a Strength or Constitution
  save/check/contest against hostile forced movement, Prone, Grappled,
  Restrained, or body-suppression pressure."
- Tyrant Blood Surge: "your next qualifying close-range body-bound attack,
  shove, grapple, escape, or Strength-based physical contest has Advantage."
- Imperial Shoulder-Gate: "When you fail a Strength or Constitution
  save/check/contest against ... pressure, ... add 2xPB + your key ability
  modifier to the roll and re-evaluate."
"""
from __future__ import annotations

import json
import zipfile

import pytest
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate2_rolls import DeterministicRollAuthority
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_r9i_karma_persistence import act
from tests.worker2_support import (ALLY, FOE, OWNER, candidate, reload,
                                    settle, turn)

DRAGON = 'dragon_wind_vessel_v0_2E'
DREAM = 'dream_mirror_soul_anchor_v0_2B'
TYRANT = 'heaven_tyrant_body_v0_2D'
DRAGON_POOL = 'resource:foundation.dragon_wind_momentum'
TRACE = 'resource:foundation.mirror_trace'
PULSE = 'resource:foundation.tyrant_form_pulse'

MOMENTUM_DRIVE = 'foundation.dragon_wind_vessel_v0_2E.momentum_drive'
MOMENTUM_GUARD = 'foundation.dragon_wind_vessel_v0_2E.momentum_guard'
DRAGON_MARROW_DRIVE = 'foundation.dragon_wind_vessel_v0_2E.dragon_marrow_drive'
STORM_MARROW_GUARD = 'foundation.dragon_wind_vessel_v0_2E.storm_marrow_guard'
GENERATE_MIRROR_TRACE = 'foundation.dream_mirror_soul_anchor_v0_2B.generate_mirror_trace'
FALSE_IMAGE_GUARD = 'foundation.dream_mirror_soul_anchor_v0_2B.false_image_guard'
MIRROR_STEP_REFLEX = 'foundation.dream_mirror_soul_anchor_v0_2B.mirror_step_reflex'
TYRANT_CHECK = 'foundation.heaven_tyrant_body_v0_2D.generate_tyrant_form_pulse'
TRUE_NAME_WITNESS = 'foundation.dream_mirror_soul_anchor_v0_2B.true_name_witness'
TRUTH_BEHIND_MASK = 'foundation.dream_mirror_soul_anchor_v0_2B.truth_behind_the_mask'

#: The foe's printed-style grapple: a Strength save whose failure Grapples
#: until escape (the 2024 Unarmed Strike Grapple option's own save).
GRAPPLE_SAVE = {'type': 'save', 'ability': 'STR', 'dc': 12, 'applies_to': 'target',
                'on_fail': [{'type': 'condition', 'condition': 'grappled',
                             'applies_to': 'target', 'until_escape': True,
                             'condition_data': {'escape_dc': 14}}],
                'on_success': []}


def _document(foundation, resource_name, stage='Awakened', held=0):
    document = sheet([], cl=15)
    document['foundation'] = {
        'foundation_id': foundation, 'stage': stage,
        'resource': {'name': resource_name,
                     'resource_id': 'tianxia.resource.foundation.' + foundation,
                     'maximum': 1, 'current': held}}
    return document


def _typed_action(name, owner, effects, *, economy='NONE', target_kind='HOSTILE_ENTITY',
                  range_ft=10, source=None, numbers=None):
    source = source or 'action:test.a2r11.' + name.lower().replace(' ', '_')
    base = {'pb': 4, 'key_mod': 3, 'save_dc': 14, 'cl': 15}
    base.update(numbers or {})
    return {'source_definition_id': source, 'display_name': name, 'owner_id': owner,
            'economy': economy, 'resolution_kind': 'TYPED', 'target_kind': target_kind,
            'range_ft': range_ft, 'costs': [],
            'parameters': {'typed': {'effects': effects,
                                     'numbers': base,
                                     'duration': {'kind': 'instant'}, 'riders': []}}}


def _strike(name, owner, *, damage=6, damage_type='FIRE', attack_bonus=100,
               source=None, range_ft=10):
    return _typed_action(name, owner, [
        {'type': 'attack', 'attack_kind': 'unarmed', 'count': 1,
         'on_hit': [{'type': 'damage', 'flat': damage, 'damage_types': [damage_type]}]}],
        economy='ACTION', source=source, range_ft=range_ft,
        numbers={'pb': 4, 'key_mod': 3, 'save_dc': 14, 'cl': 15,
                  'attack_bonus': attack_bonus})


def _condition(engine, actor, condition_id):
    """The actor's held condition row (conditions key by instance)."""
    return next((condition for condition in (actor.conditions or {}).values()
                 if condition.condition_id == condition_id), None)


def _escape(name, owner, *, bonus=100, ability=None, source=None):
    effect = {'type': 'escape_grapple', 'bonus': bonus}
    if ability:
        effect['check_ability'] = ability
        effect['check_skill'] = 'Athletics' if ability == 'STR' else 'Acrobatics'
    return _typed_action(name, owner, [effect], economy='ACTION',
                         target_kind='SELF', source=source)


def _save(name, owner, *, ability='CON', dc=13, on_fail=(), on_success=(), source=None):
    return _typed_action(name, owner, [
        {'type': 'save', 'ability': ability, 'dc': dc, 'applies_to': 'target',
         'on_fail': list(on_fail), 'on_success': list(on_success)}],
        economy='ACTION', source=source)


def _fight(tmp_path, foundation, resource_name, *, stage='Awakened', held=0,
           owner_actions=(), ally_actions=(), foe_actions=(),
           owner_attack_bonus=8, foe_attack_bonus=8, owner_ac=14, foe_ac=14,
           owner_hp=60, foe_hp=60):
    """Three creatures: the Foundation's owner, an ally, and a hostile foe.

    The owner's sheet names its Foundation and its own resource pool; the foe
    carries the printed grapple save and the owner a typed escape and strike,
    both compiled into the real catalog so the table's own code resolves them.
    """
    documents = [_document(foundation, resource_name, stage, held),
                 sheet([], cl=15), sheet([], cl=15)]
    documents[0]['ability_scores_and_statistics']['technique_attack_bonus'] = owner_attack_bonus
    documents[0]['ability_scores_and_statistics']['armor_class']['base_value'] = owner_ac
    documents[0]['ability_scores_and_statistics']['hit_points']['maximum'] = owner_hp
    documents[2]['ability_scores_and_statistics']['technique_attack_bonus'] = foe_attack_bonus
    documents[2]['ability_scores_and_statistics']['armor_class']['base_value'] = foe_ac
    documents[2]['ability_scores_and_statistics']['hit_points']['maximum'] = foe_hp
    ids = [OWNER, ALLY, FOE]
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={'ask': True})
               for aid, doc in zip(ids, documents)]
    for aid, actions, bundle in ((OWNER, owner_actions, bundles[0]),
                                 (ALLY, ally_actions, bundles[1]),
                                 (FOE, foe_actions, bundles[2])):
        for action in actions:
            if action['display_name'] == 'Grapple Save':
                # Force the initial hostile hold, independently of the seeded
                # save and Tyrant-Blood Frame's Advantage. Its escape DC is 14.
                action['parameters']['typed']['numbers']['save_dc'] = 100
            bundle['action_catalog'].append(action)
            bundle['actor_template']['action_ids'].append(action['source_definition_id'])
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)
    for aid, document in zip(ids, documents):
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    places = {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 2, 'y': 6}, FOE: {'x': 4, 'y': 6}}
    arena = combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    teams = {aid: ('team:opponents' if aid == FOE else 'team:factory') for aid in ids}
    mid = combat._finish_factory_match(
        bundles, ids, teams, places, arena, [OWNER, ALLY], [FOE],
        control_modes={aid: 'MANUAL' for aid in ids}, match_seed='A2R11',
        display_name='A2R11', maximum_rounds=15)['match_id']
    turn(table, mid, OWNER)
    return combat, table, mid


def _committed(engine, target, *, damage_type=None):
    """The damage events committed against one creature."""
    return [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
            and e.target_ids == (target,)
            and (damage_type is None or e.payload.get('damage_type') == damage_type)]


def _notes(engine, actor, needle):
    """The log lines the table wrote for one actor (notes ride events)."""
    return [e.payload.get('log', '') for e in engine.events
            if e.event_type == 'PASSIVE_TRIGGERED'
            and e.actor_id == actor and needle in str(e.payload.get('log', ''))]


# ===================================================================== Dragon-Wind

def test_momentum_drive_adds_inherited_type_damage(tmp_path):
    """Momentum Drive: after a hit, spend 1 Dragon-Wind Momentum to add PB
    damage of that hit's type (the typed inherit_damage_type seam)."""
    combat, table, mid = _fight(tmp_path, DRAGON, 'Dragon-Wind Momentum', held=1,
                                 owner_actions=[_strike('Strike', OWNER)])
    settle(table, mid, candidate(combat, mid, 'Strike').candidate_id,
           picks={'reaction:typed.' + MOMENTUM_DRIVE: 'first'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[DRAGON_POOL] == 0
    rides = _committed(engine, FOE, damage_type='FIRE')
    assert any(e.payload['hp_damage'] == 4 for e in rides), \
        [e.payload for e in rides]


def test_momentum_guard_reduces_triggering_damage(tmp_path):
    """Momentum Guard: when you take damage, spend 1 Dragon-Wind Momentum to
    reduce that damage by PB + your key ability modifier."""
    combat, table, mid = _fight(tmp_path, DRAGON, 'Dragon-Wind Momentum', held=1,
                                 foe_actions=[_strike('Foe Strike', FOE, damage=20)])
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Foe Strike', target=OWNER).candidate_id,
           picks={'reaction:typed.' + MOMENTUM_GUARD: 'first'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[DRAGON_POOL] == 0
    hits = _committed(engine, OWNER)
    # The strike's own damage (weapon die + flat) is reduced by the
    # guard's PB 4 + key ability modifier 2 (the owner's compiled numbers).
    assert hits and hits[-1].payload['hp_damage'] \
        == hits[-1].payload['rolled_or_pending_damage'] - 4 - 2, \
        [e.payload for e in hits]


@pytest.mark.parametrize('natural,blocked', [(1, True), (20, False)])
def test_dragon_marrow_drive_adds_saved_damage(tmp_path, monkeypatch, natural, blocked):
    """Dragon-Marrow Drive: the hit's added damage becomes 1d4 + PB of the
    hit's type, then the target makes a Strength or Dexterity save against the
    Cultivation Save DC; failure blocks only OAs against the mover this turn."""
    original = DeterministicRollAuthority.raw_d20
    def save_roll(self, *, modifier, actor_id, reason, mode='NORMAL'):
        roll = original(self, modifier=modifier, actor_id=actor_id, reason=reason, mode=mode)
        if actor_id == FOE and reason.startswith('SAVE:'):
            return roll.model_copy(update={'dice': (natural,), 'natural_result': natural,
                                           'total': natural + modifier})
        return roll
    monkeypatch.setattr(DeterministicRollAuthority, 'raw_d20', save_roll)
    combat, table, mid = _fight(tmp_path, DRAGON, 'Dragon-Wind Momentum', stage='Refined',
                                 held=1, owner_actions=[_strike('Strike', OWNER,
                                                                  range_ft=30)])
    # The 20-foot precondition: Momentum Drive's rider only rides a
    # hit after moving at least 20 feet this turn.
    settle(table, mid, _move_20(combat, table, mid))
    settle(table, mid, candidate(combat, mid, 'Strike').candidate_id,
           picks={'reaction:typed.' + MOMENTUM_DRIVE: 'first'})
    engine = reload(tmp_path, mid)
    marrow = [e for e in _committed(engine, FOE, damage_type='FIRE')
              if 5 <= e.payload['hp_damage'] <= 8]
    assert marrow, [e.payload for e in _committed(engine, FOE)]
    no_oa = _condition(engine, engine.state.actors[FOE], 'condition:typed.no_opportunity_attacks')
    assert (no_oa is not None) == blocked
    if blocked:
        assert no_oa.source_actor_id == OWNER and no_oa.data['against'] == OWNER
    assert _condition(engine, engine.state.actors[FOE], 'condition:typed.reaction_denied') is None
    from combat.typed_reactions import opportunity_permitted_against
    assert opportunity_permitted_against(engine, engine.state.actors[FOE], engine.state.actors[OWNER]) == (not blocked)
    assert opportunity_permitted_against(engine, engine.state.actors[FOE], engine.state.actors[ALLY])


def _move_20(combat, table, mid):
    """The owner's ordinary 20-foot move, answered through the table.

    The owner starts at (3,6); four squares north (3,10) is a clear
    20-foot path (the ally at (2,6) and the pillar at (6,9)..(7,10)
    are off the path), so the move is exactly the printed 20 feet."""
    engine = combat._load_session(mid).engine
    move = next(c for c in engine.legal_candidates()
                if c.destination and (c.destination.x, c.destination.y) == (3, 10))
    return move.candidate_id


def test_storm_marrow_guard_moves_after_the_guard(tmp_path):
    """Storm-Marrow Guard: after Momentum Guard reduces the triggering damage,
    move 5 feet (10 for thunder damage) without provoking opportunity attacks."""
    for damage_type, expected in (('FIRE', 5), ('THUNDER', 10)):
        combat, table, mid = _fight(tmp_path / damage_type.lower(), DRAGON, 'Dragon-Wind Momentum', stage='Refined',
                                     held=1, foe_actions=[_strike('Foe Strike', FOE, damage=20,
                                                                   damage_type=damage_type)])
        turn(table, mid, FOE)
        base = reload(tmp_path / damage_type.lower(), mid).state.actors[OWNER].movement_remaining_ft
        settle(table, mid, candidate(combat, mid, 'Foe Strike', target=OWNER).candidate_id,
               picks={'reaction:typed.' + MOMENTUM_GUARD: 'first'})
        engine = reload(tmp_path / damage_type.lower(), mid)
        owner = engine.state.actors[OWNER]
        assert owner.movement_remaining_ft == base + expected, (damage_type, owner.movement_remaining_ft)
        # The storm-marrow move is an ordinary movement grant the
        # owner spends like any other, and it provokes no
        # opportunity attacks from the damaging creature.
        assert owner.turn_flags.get('oa_free_ft') == expected, \
            (damage_type, owner.turn_flags.get('oa_free_ft'))


def test_wind_body_step_extends_the_step_and_advantages_athletics(tmp_path):
    """Wind-Body Step: Momentum Step's walking distance becomes 15 feet, and
    the next Athletics or Acrobatics check before end of turn has Advantage
    (the condition's check_mode table, read by typed checks and escapes)."""
    combat, table, mid = _fight(tmp_path, DRAGON, 'Dragon-Wind Momentum', stage='Refined',
                                 held=1, owner_actions=[_escape('Escape the Grapple', OWNER, ability='STR')],
                                 foe_actions=[_typed_action('Grapple Save', FOE, [GRAPPLE_SAVE],
                                                                      economy='ACTION')])
    # The owner must be grappled before Momentum Step, so the next qualifying
    # escape check occurs during the same turn as the step.
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Grapple Save', target=OWNER).candidate_id)
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    _pre_step_speed = before._effective_speed(before.state.actors[OWNER])
    settle(table, mid, candidate(combat, mid, 'Momentum Step').candidate_id)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    # The step's own length is credited on top of the turn's
    # starting movement, and the walking speed reads 15 higher
    # (the Foundation's own speed expression rides along).
    assert owner.movement_remaining_ft == 15
    assert _pre_step_speed == engine._effective_speed(owner) == 0, 'Grappled still sets speed to zero'
    rule = next(row for condition, row in
                __import__('combat.typed_executor', fromlist=['condition_rule_instances'])
                .condition_rule_instances(owner)
                if condition.condition_id == 'condition:typed.foundations1_wind_body_step')
    assert rule['check_mode'] == {'Athletics': 'ADVANTAGE', 'Acrobatics': 'ADVANTAGE'}
    # The next physical escape check on this turn rolls with Advantage.
    settle(table, mid, candidate(combat, mid, 'Escape the Grapple').candidate_id)
    engine = reload(tmp_path, mid)
    escapes = [e for e in engine.events if e.event_type == 'CHECK_ROLLED'
               and 'escape' in str(e.source_definition_id)]
    assert escapes and escapes[-1].payload['actor']['mode'] == 'ADVANTAGE'
    assert _condition(engine, engine.state.actors[OWNER], 'condition:typed.foundations1_wind_body_step') is None


def test_wind_body_step_increases_ungrappled_speed_through_reload(tmp_path):
    combat, table, mid = _fight(tmp_path, DRAGON, 'Dragon-Wind Momentum', stage='Refined', held=1)
    before = reload(tmp_path, mid)
    speed = before._effective_speed(before.state.actors[OWNER])
    remaining = before.state.actors[OWNER].movement_remaining_ft
    settle(table, mid, candidate(combat, mid, 'Momentum Step').candidate_id)
    after = reload(tmp_path, mid)
    assert after._effective_speed(after.state.actors[OWNER]) == speed + 15
    assert after.state.actors[OWNER].movement_remaining_ft == remaining + 15


def test_sovereign_momentum_does_not_bank_or_repeat_step(tmp_path):
    """A standalone Step has no second legal hit/damage conversion."""
    combat, table, mid = _fight(tmp_path, DRAGON, 'Dragon-Wind Momentum', stage='Perfected',
                                 held=1)
    settle(table, mid, _move_20(combat, table, mid))
    settle(table, mid, candidate(combat, mid, 'Momentum Step').candidate_id)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[DRAGON_POOL] == 0, 'Sovereign cannot bank an unrestricted refund'
    refunds = [e for e in engine.events if e.event_type == 'RESOURCE_GAINED'
               and e.actor_id == OWNER and e.source_definition_id ==
               'foundation.dragon_wind_vessel_v0_2E.sovereign_momentum']
    assert not refunds
    assert not [c for c in engine.legal_candidates()
                if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', None) == 'Momentum Step']


# ==================================================================== Dream-Mirror

def test_generate_mirror_trace_gains_on_miss_and_fades(tmp_path):
    """Generate Mirror Trace: a hostile attack that misses you generates 1
    Mirror Trace (at most 1), and it fades at the end of your next turn."""
    combat, table, mid = _fight(tmp_path, DREAM, 'Mirror Trace', held=0,
                                 foe_actions=[_strike('Foe Strike', FOE, damage=6,
                                                        attack_bonus=-100)])
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Foe Strike', target=OWNER).candidate_id,
           picks={'reaction:typed.' + GENERATE_MIRROR_TRACE: 'first'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[TRACE] == 1
    turn(table, mid, OWNER)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[TRACE] == 0, \
        'the Trace fades at the end of the owner\'s next turn'


def test_reflection_cut_adds_chosen_damage_on_hit(tmp_path):
    """Reflection Cut: after a hit, spend 1 Mirror Trace to add PB Psychic or
    Force damage to that hit; the type is chosen when the resource is spent."""
    combat, table, mid = _fight(tmp_path, DREAM, 'Mirror Trace', held=1,
                                 owner_actions=[_strike('Strike', OWNER)])
    settle(table, mid, candidate(combat, mid, 'Strike').candidate_id,
           choices={'choice:needle.dream_mirror_round_cut': 'psychic'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[TRACE] == 0
    rides = _committed(engine, FOE, damage_type='PSYCHIC')
    assert any(e.payload['hp_damage'] == 4 for e in rides), \
        [e.payload for e in rides]


@pytest.mark.parametrize('kind', ['attack', 'Insight', 'Perception'])
def test_dream_reflection_counter_penalizes_next_attack(tmp_path, kind):
    """Dream-Reflection Counter: the creature Reflection Cut hits takes -PB on
    its next Insight, Perception or attack roll against you, before the end of
    its next turn."""
    dream_strike = _typed_action('Dream Strike', OWNER, [
        {'type': 'attack', 'attack_kind': 'unarmed', 'count': 1,
         'on_hit': [{'type': 'damage', 'flat': 6, 'damage_types': ['FIRE']},
                    {'type': 'condition', 'condition': 'blinded', 'applies_to': 'target',
                     'duration': 'instant', 'expires_on': 'END_OF_CURRENT_TURN'}]}],
        economy='ACTION', numbers={'attack_bonus': 100})
    combat, table, mid = _fight(tmp_path, DREAM, 'Mirror Trace', stage='Refined', held=1,
                                 owner_actions=[dream_strike],
                                 foe_actions=[_strike('Foe Strike', FOE, damage=6),
                                              _typed_action('Read the anchor', FOE, [{
                                                  'type': 'contest_against',
                                                  'actor_check': {'ability': 'WIS', 'skill': kind},
                                                  'target_check': {'kind': 'dc', 'basis': 'save_dc'}}],
                                                            economy='ACTION')])
    settle(table, mid, candidate(combat, mid, 'Dream Strike').candidate_id,
           choices={'choice:needle.dream_mirror_round_cut': 'force'})
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    marked = _condition(engine, foe, 'condition:typed.dream_mirror_reflection_counter')
    assert marked is not None and marked.source_actor_id == OWNER, {
        'conditions': [c.condition_id for c in foe.conditions.values()],
        'trace': engine.state.actors[OWNER].resources[TRACE],
        'notes': _notes(engine, OWNER, 'Reflection Cut')}
    # The short dream-image blindness ends with the attacker's turn. The
    # Counter persists, so the foe can legally see and check the anchor.
    turn(table, mid, FOE)
    assert _condition(reload(tmp_path, mid), reload(tmp_path, mid).state.actors[FOE], 'condition:typed.blinded') is None
    settle(table, mid, candidate(combat, mid, 'Foe Strike' if kind == 'attack' else 'Read the anchor', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    attacks = [e for e in engine.events if e.event_type == 'D20_REWRITTEN'
               and e.actor_id == FOE
               and e.source_definition_id == 'foundation.dream_mirror_soul_anchor_v0_2B.dream_reflection_counter']
    assert attacks and attacks[-1].payload['result']['total'] == \
        attacks[-1].payload['original']['total'] - 4, [e.payload for e in attacks]
    assert _condition(engine, engine.state.actors[FOE], 'condition:typed.dream_mirror_reflection_counter') is None


def test_true_name_witness_adds_pb_to_save(tmp_path):
    """True-Name Witness: after you roll a saving throw and before the outcome
    is known, spend 1 Mirror Trace to add PB to the roll."""
    def natural_ten(self, *, modifier, actor_id, reason, mode='NORMAL'):
        roll = original(self, modifier=modifier, actor_id=actor_id,
                        reason=reason, mode=mode)
        if actor_id == OWNER and reason.startswith('SAVE:'):
            return roll.model_copy(update={'dice': (10,), 'natural_result': 10,
                                            'total': 10 + modifier})
        return roll

    original = DeterministicRollAuthority.raw_d20
    DeterministicRollAuthority.raw_d20 = natural_ten
    try:
        # DC 13: a natural 10 plus the owner's +2 save fails (12), and only
        # the Witness's +PB (16) carries it -- so the save lands iff the
        # Witness spends the Trace.
        combat, table, mid = _fight(tmp_path, DREAM, 'Mirror Trace', held=1,
                                     foe_actions=[_save('Demand Save', FOE, ability='CON', dc=13,
                                                        on_success=[{'type': 'condition',
                                                                     'condition': 'core.dodge',
                                                                     'applies_to': 'target',
                                                                     'duration': 'until_end_of_next_turn'}])])
        turn(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, 'Demand Save', target=OWNER).candidate_id,
               choices={'choice:needle.dream_mirror_round_witness': 'use'})
        engine = reload(tmp_path, mid)
        assert engine.state.actors[OWNER].resources[TRACE] == 0
        rewrites = [e for e in engine.events if e.event_type == 'D20_REWRITTEN'
                    and e.source_definition_id == TRUE_NAME_WITNESS]
        assert rewrites and rewrites[-1].payload['result']['total'] == 16
    finally:
        DeterministicRollAuthority.raw_d20 = original


def test_truth_behind_the_mask_adds_pb_against_charm(tmp_path):
    """Truth Behind the Mask: a Witness spent against charm, illusion, dream,
    disguise, memory, possession or identity manipulation adds another PB, and
    on success the witness learns one symbolic truth about the source."""
    def natural_ten(self, *, modifier, actor_id, reason, mode='NORMAL'):
        roll = original(self, modifier=modifier, actor_id=actor_id,
                        reason=reason, mode=mode)
        if actor_id == OWNER and reason.startswith('SAVE:'):
            return roll.model_copy(update={'dice': (10,), 'natural_result': 10,
                                            'total': 10 + modifier})
        return roll

    original = DeterministicRollAuthority.raw_d20
    DeterministicRollAuthority.raw_d20 = natural_ten
    try:
        # DC 13: natural 10 + save 2 + Witness 4 + Mask 4 = 20, so the save
        # lands only with both riders; the failure branch names Charmed, which
        # is what makes this a save against charm manipulation.
        combat, table, mid = _fight(tmp_path, DREAM, 'Mirror Trace', stage='Refined', held=1,
                                     foe_actions=[_save('Demand Save', FOE, ability='CON', dc=13,
                                                        on_fail=[{'type': 'condition',
                                                                  'condition': 'charmed',
                                                                  'applies_to': 'target',
                                                                  'duration': 'until_end_of_next_turn'}],
                                                        on_success=[{'type': 'condition',
                                                                     'condition': 'core.dodge',
                                                                     'applies_to': 'target',
                                                                     'duration': 'until_end_of_next_turn'}])])
        turn(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, 'Demand Save', target=OWNER).candidate_id,
               choices={'choice:needle.dream_mirror_round_witness': 'use'})
        engine = reload(tmp_path, mid)
        assert engine.state.actors[OWNER].resources[TRACE] == 0
        rewrites = [e for e in engine.events if e.event_type == 'D20_REWRITTEN'
                    and e.source_definition_id == TRUE_NAME_WITNESS]
        assert rewrites and rewrites[-1].payload['result']['total'] == 20
        assert _notes(engine, OWNER, 'truth behind the mask')
    finally:
        DeterministicRollAuthority.raw_d20 = original


def test_mirror_step_reflex_moves_after_the_guard(tmp_path):
    """Mirror-Step Reflex: when Mirror Trace is spent on False-Image Guard,
    after the damage reduction resolves the anchor moves up to 10 feet
    without provoking opportunity attacks (an ordinary movement grant the
    owner spends like any other)."""
    combat, table, mid = _fight(tmp_path, DREAM, 'Mirror Trace', stage='Refined',
                                 held=1, foe_actions=[_strike('Foe Strike', FOE, damage=20)])
    turn(table, mid, FOE)
    base = reload(tmp_path, mid).state.actors[OWNER].movement_remaining_ft
    settle(table, mid, candidate(combat, mid, 'Foe Strike', target=OWNER).candidate_id,
           picks={'reaction:typed.' + FALSE_IMAGE_GUARD: 'first'})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[TRACE] == 0, 'the guard spent the Mirror Trace'
    assert owner.movement_remaining_ft == base + 10, 'the Reflex grants the 10-foot step'
    assert int(owner.turn_flags.get('oa_free_ft') or 0) == 10, \
        'the step does not provoke opportunity attacks'
    assert _committed(engine, OWNER)[-1].payload['hp_damage'] \
        == _committed(engine, OWNER)[-1].payload['rolled_or_pending_damage'] - 4 - 2, \
        'the guard reduced the damage by PB + key ability modifier'


def test_dream_mirror_domain_grows_the_guard_reduction(tmp_path):
    """Dream-Mirror Domain: once per round, a spent Mirror Trace's
    numeric benefit grows by PB -- False-Image Guard's damage
    reduction included (the domain's damage_reduction_bonus seam)."""
    combat, table, mid = _fight(tmp_path, DREAM, 'Mirror Trace', stage='Perfected',
                                 held=1,
                                 foe_actions=[_strike('Foe Miss', FOE, damage=6,
                                                        attack_bonus=-100),
                                              _typed_action('Foe Strike', FOE, _strike('Foe Strike', FOE, damage=20)['parameters']['typed']['effects'],
                                                            economy='BONUS_ACTION', numbers={'attack_bonus': 100})])
    settle(table, mid, candidate(combat, mid, 'Dream-Mirror Domain').candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[TRACE] == 0, 'the activation spent the Trace'
    turn(table, mid, FOE)
    # The hostile miss generates the Trace the guard will spend.
    settle(table, mid, candidate(combat, mid, 'Foe Miss', target=OWNER).candidate_id,
           picks={'reaction:typed.' + GENERATE_MIRROR_TRACE: 'first'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[TRACE] == 1
    # Spend the newly generated Trace before its holder's next turn ends;
    # the foe's second strike uses its still-available Bonus Action.
    settle(table, mid, candidate(combat, mid, 'Foe Strike', target=OWNER).candidate_id,
           picks={'reaction:typed.' + FALSE_IMAGE_GUARD: 'first'})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[TRACE] == 0, 'the guard spent the Trace'
    # Assert the guard's full reduction from the attack's recorded damage;
    # the unarmed strike includes its weapon die as well as the flat 20.
    hit = _committed(engine, OWNER)[-1]
    assert hit.payload['hp_damage'] == hit.payload['rolled_or_pending_damage'] - 4 - 2 - 4, \
        hit.payload


def test_dream_mirror_domain_covers_ally_misses(tmp_path):
    """Dream-Mirror Domain: a 30-foot emanation for 1 minute whose hostile
    misses against an ally in it also generate the anchor's Mirror Trace, once
    per round; the first Mirror Trace spend in a round also gains PB."""
    combat, table, mid = _fight(tmp_path, DREAM, 'Mirror Trace', stage='Perfected',
                                 held=1, ally_actions=[_strike('Ally Strike', ALLY)],
                                 foe_actions=[_strike('Foe Strike', FOE, damage=6,
                                                        attack_bonus=-100)])
    settle(table, mid, candidate(combat, mid, 'Dream-Mirror Domain').candidate_id)
    engine = reload(tmp_path, mid)
    assert _condition(engine, engine.state.actors[OWNER],
                      'condition:typed.dream_mirror_domain') is not None
    assert engine.state.actors[OWNER].resources[TRACE] == 0, 'the activation spent the Trace'
    # The foe misses the ally inside the emanation: the anchor's Trace returns.
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Foe Strike', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[TRACE] == 1, \
        'the domain covers an ally\'s miss'
    assert _notes(engine, OWNER, 'Dream-Mirror Domain covers')


# ================================================================== Heaven-Tyrant

def test_tyrant_form_pulse_generates_on_strength_escape(tmp_path):
    """Generate Tyrant Form Pulse: you succeed on a Strength check or contest
    against hostile body pressure -- here a Strength (Athletics) escape from
    the foe's Grapple -- which generates 1 Tyrant Form Pulse."""
    combat, table, mid = _fight(tmp_path, TYRANT, 'Tyrant Form Pulse', held=0,
                                 owner_actions=[_escape('Escape the Grapple', OWNER, bonus=100,
                                                          ability='STR')],
                                 foe_actions=[_typed_action('Grapple Save', FOE, [GRAPPLE_SAVE],
                                                              economy='ACTION')])
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Grapple Save', target=OWNER).candidate_id)
    grappled = reload(tmp_path, mid)
    assert _condition(grappled, grappled.state.actors[OWNER],
                      'condition:typed.grappled') is not None
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Escape the Grapple').candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[PULSE] == 1
    checks = [e for e in engine.events if e.event_type == 'CHECK_ROLLED'
              and e.payload.get('ability') == 'STR']
    assert checks and checks[-1].payload['success']


@pytest.mark.parametrize('ability', ['STR', 'DEX'])
def test_tyrant_blood_surge_advantages_escape_and_is_spent(tmp_path, ability):
    """Tyrant Blood Surge: as a bonus action, gain temporary hit points and
    hold Tyrant Blood Surge; your next qualifying escape has Advantage, and
    the surge is spent when the escape is rolled."""
    combat, table, mid = _fight(tmp_path, TYRANT, 'Tyrant Form Pulse', held=1,
                                 owner_actions=[_escape('Escape the Grapple', OWNER, ability=ability)],
                                 foe_actions=[_typed_action('Grapple Save', FOE, [GRAPPLE_SAVE],
                                                              economy='ACTION')])
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Grapple Save', target=OWNER).candidate_id)
    turn(table, mid, OWNER)
    # Generate a pulse to spend: the foe's hit lands on the owner.
    settle(table, mid, candidate(combat, mid, 'Tyrant Blood Surge').candidate_id)
    engine = reload(tmp_path, mid)
    assert _condition(engine, engine.state.actors[OWNER],
                      'condition:typed.foundation_combat.tyrant_surge') is not None
    settle(table, mid, candidate(combat, mid, 'Escape the Grapple').candidate_id)
    engine = reload(tmp_path, mid)
    escapes = [e for e in engine.events if e.event_type == 'CHECK_ROLLED'
               and 'escape' in str(e.source_definition_id)]
    assert escapes and escapes[-1].payload['actor']['mode'] == 'ADVANTAGE'
    assert _condition(engine, engine.state.actors[OWNER],
                      'condition:typed.foundation_combat.tyrant_surge') is None, \
        'the surge is spent by the escape it advantaged'


def test_tyrant_dexterity_escape_does_not_generate_strength_pulse(tmp_path):
    combat, table, mid = _fight(tmp_path, TYRANT, 'Tyrant Form Pulse', held=0,
                               owner_actions=[_escape('Escape the Grapple', OWNER, ability='DEX')],
                               foe_actions=[_typed_action('Grapple Save', FOE, [GRAPPLE_SAVE], economy='ACTION')])
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Grapple Save', target=OWNER).candidate_id)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Escape the Grapple').candidate_id)
    engine = reload(tmp_path, mid)
    assert _condition(engine, engine.state.actors[OWNER], 'condition:typed.grappled') is None
    assert engine.state.actors[OWNER].resources[PULSE] == 0


@pytest.mark.parametrize('mode,ability,expected', [
    ('MANUAL', 'STR', 1), ('MANUAL', 'DEX', 0), ('LOCAL_AUTO', None, 1)])
def test_native_tyrant_escape_keeps_both_skills_and_records_the_choice(tmp_path, monkeypatch, mode, ability, expected):
    original = DeterministicRollAuthority.raw_d20
    def succeed(self, *, modifier, actor_id, reason, mode='NORMAL'):
        roll = original(self, modifier=modifier, actor_id=actor_id, reason=reason, mode=mode)
        if actor_id == OWNER and reason.startswith('CHECK:'):
            return roll.model_copy(update={'dice': (20,), 'natural_result': 20, 'total': 20 + modifier})
        return roll
    monkeypatch.setattr(DeterministicRollAuthority, 'raw_d20', succeed)
    combat, table, mid = _fight(tmp_path, TYRANT, 'Tyrant Form Pulse', held=0,
                               foe_actions=[_typed_action('Grapple Save', FOE, [GRAPPLE_SAVE], economy='ACTION')])
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Grapple Save', target=OWNER).candidate_id)
    turn(table, mid, OWNER)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=mode)
    cid = candidate(combat, mid, 'Escape grapple').candidate_id
    if mode != 'MANUAL':
        # Drive the selected native action through the real automatic table
        # route; the injected policy selects only the action, not the skill.
        from combat.gate4_adapters import ManualControllerAdapter
        policy = combat.controller
        combat.controller = ManualControllerAdapter(lambda context: (cid, ()),
            reaction_chooser=lambda context: policy.choose_reaction(context).decision)
    prompts = settle(table, mid, cid,
                     choices={'choice:needle.physical_escape_skill': ability} if ability else None,
                     auto=mode != 'MANUAL')
    if ability:
        skill_prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.physical_escape_skill')
        assert {o['id'] for o in skill_prompt['choice']['options']} == {'STR', 'DEX'}
        text = str(skill_prompt)
        assert 'Tyrant-Blood Frame' in text and 'Escape grapple' in text and 'Factory character' in text
    else:
        assert not prompts
    engine = reload(tmp_path, mid)
    checks = [e for e in engine.events if e.event_type == 'CHECK_ROLLED' and e.actor_id == OWNER]
    assert checks[-1].payload['ability'] == (ability or 'STR')
    assert checks[-1].payload['actor']['mode'] == ('ADVANTAGE' if (ability or 'STR') == 'STR' else 'NORMAL')
    assert engine.state.actors[OWNER].resources[PULSE] == expected
    assert _condition(engine, engine.state.actors[OWNER], 'condition:typed.grappled') is None
    assert not engine.state.actors[OWNER].action_available


def test_imperial_shoulder_gate_rescues_failed_escape(tmp_path):
    """Imperial Shoulder-Gate: when you fail a Strength or Constitution check
    against hostile Grappled pressure, spend 1 Tyrant Form Pulse to add
    2xPB + your key ability modifier to the roll and re-evaluate."""
    def natural_ten(self, *, modifier, actor_id, reason, mode='NORMAL'):
        roll = original(self, modifier=modifier, actor_id=actor_id,
                        reason=reason, mode=mode)
        if actor_id == OWNER and reason.startswith('CHECK:'):
            return roll.model_copy(update={'dice': (10,), 'natural_result': 10,
                                            'total': 10 + modifier})
        return roll

    original = DeterministicRollAuthority.raw_d20
    DeterministicRollAuthority.raw_d20 = natural_ten
    try:
        # The escape's DC is the Grapple's 8 + Strength + PB = 8 + 2 + 4 = 14.
        # The escape's +1 leaves the natural 10 below DC 14; the Gate's
        # 2xPB + key modifier (11) carries the roll above the DC.
        combat, table, mid = _fight(tmp_path, TYRANT, 'Tyrant Form Pulse', held=1,
                                     owner_actions=[_escape('Escape the Grapple', OWNER, bonus=1,
                                                              ability='STR')],
                                     foe_actions=[_typed_action('Grapple Save', FOE, [GRAPPLE_SAVE],
                                                                  economy='ACTION')])
        turn(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, 'Grapple Save', target=OWNER).candidate_id)
        turn(table, mid, OWNER)
        settle(table, mid, candidate(combat, mid, 'Escape the Grapple').candidate_id,
               choices={'choice:needle.foundation_combat': 'use'})
        engine = reload(tmp_path, mid)
        spent = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
                 and e.source_definition_id == 'foundation.heaven_tyrant_body_v0_2D.imperial_shoulder_gate']
        assert len(spent) == 1 and spent[0].payload['amount'] == 1
        escapes = [e for e in engine.events if e.event_type == 'CHECK_ROLLED'
                   and 'escape' in str(e.source_definition_id)]
        assert escapes and escapes[-1].payload['success']
    finally:
        DeterministicRollAuthority.raw_d20 = original
