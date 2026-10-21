"""sw-chains: compile printed-rule corrections and exercise them in isolated fights.

The old-authority run is recorded in the external batch report. No live projects,
saved fights, services, or locked combat files are used by these tests.
"""

import copy
from functools import lru_cache

import pytest

from combat import typed_reactions, zones
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from tests.test_auto_support import ME, _engine
from tests.test_reaction_effects_r6 import _typed_action, _use
from tests.test_zones import SHEET

FAILS, PASSES = 30, 1
CHAIN = 'tianxia.talent.chains.'
DAEMON = 'TAL_DAEMONIC_CULTIVATION_'
LASH = 'TAL_CHAINS_CHAIN_LASH_BASE'
TOUGH = 2000


@lru_cache(maxsize=None)
def _compiled(sphere, talents, dc=FAILS, cl=17):
    sheet = {**SHEET, 'equipment': [],
             'identity': {**SHEET['identity'], 'cultivation_level': cl},
             'ability_scores_and_statistics': {**SHEET['ability_scores_and_statistics'],
                 'technique_save_dc': dc, 'technique_attack_bonus': 40,
                 'primary_resource': {'name': 'Qi', 'maximum': 100}},
             'spheres_and_talents': {'sphere_record_ids': ['tianxia.sphere.' + sphere],
                                    'learned_talent_record_ids': list(talents)}}
    return compile_character(sheet, actor_id=ME,
        reaction_plan={'options': {'TAL_DARK_NIGHT_THAT_SWALLOWS_THE_LANTERN': 0}})


def _fight(sphere, *talents, dc=FAILS, cl=17, foe_at=(4, 6)):
    bundle = copy.deepcopy(_compiled(sphere, talents, dc, cl))
    engine = _engine(bundle, foe_at=foe_at)
    engine.state.actors[AN].maximum_hp = engine.state.actors[AN].current_hp = TOUGH
    return bundle, engine


def _cast(engine, prefix, *contains):
    foe = engine.state.actors[AN].position
    candidates = [c for c in engine.legal_candidates()
                  if c.display_name.startswith(prefix) and all(s in c.display_name for s in contains)]
    assert candidates, f'No candidate: {prefix} {contains}'
    candidate = min(candidates, key=lambda c: 0 if c.destination is None else
                    abs(c.destination.x - foe.x) + abs(c.destination.y - foe.y))
    engine.execute_intent(ActionIntent(intent_id='review', decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=ME,
        target_ids=candidate.target_ids, destination=candidate.destination))


def _events(engine, *kinds):
    return [e for e in engine.events if e.event_type in kinds]


def _conditions(actor):
    return {c.condition_id.removeprefix('condition:typed.') for c in actor.conditions.values()}


def _foe_turn(engine):
    engine.end_turn()
    assert engine.state.current_actor_id == AN


def test_set_tether_does_not_apply_the_object_pull_to_a_creature():
    _, engine = _fight('chains', 'TAL_CHAINS_SET_TETHER_BASE')
    foe = engine.state.actors[AN]
    before = foe.position
    _cast(engine, 'Set the Tether')
    assert foe.position == before
    assert 'bound' in _conditions(foe)


def test_chain_armor_reduces_forced_movement_in_text_not_by_granting_movement():
    _, engine = _fight('chains', CHAIN + 'chain_armor')
    me = engine.state.actors[ME]
    before = me.movement_remaining_ft
    _cast(engine, 'Chain Armor')
    assert me.movement_remaining_ft == before and not _events(engine, 'MOVEMENT_GRANTED')
    assert any(m.target_field == 'armor_class' and m.value == 2 for m in me.modifiers.values())


@pytest.mark.parametrize('talent,name', [
    ('chain_clone', 'Chain Clone'), ('chain_the_door', 'Chain the Door'), ('oath_lock_chain', 'Oath-Lock Chain'),
])
def test_object_and_oath_riders_do_not_apply_their_effects_to_fighters_at_cast(talent, name):
    _, engine = _fight('chains', CHAIN + talent)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _cast(engine, name)
    assert not _events(engine, 'ATTACK_ROLLED', 'DAMAGE_COMMITTED', 'SAVE_ROLLED')
    assert not me.modifiers and not foe.modifiers and not foe.conditions
    assert me.temporary_hp == foe.temporary_hp == 0


def test_chain_gang_does_not_slow_a_target_before_another_linked_creature_falls():
    _, engine = _fight('chains', CHAIN + 'chain_gang_method')
    _cast(engine, 'Chain Gang Method')
    # Bound's own printed -10 Speed (Core Chains Rules; combat/ext/chains_core.py, rider lane C13) and nothing more: the Prone rider's
    # extra -10 waits for another linked creature to fall.
    assert engine._effective_speed(engine.state.actors[AN]) == 20


@pytest.mark.parametrize('talent,name', [('chain_prison', 'Chain Prison'), ('shackling_chain', 'Shackling Chain')])
def test_sustained_restraint_can_end_on_the_printed_turn_end_save(talent, name):
    _, engine = _fight('chains', CHAIN + talent)
    foe = engine.state.actors[AN]
    _cast(engine, name)
    assert 'restrained' in _conditions(foe)
    foe.saving_throws['STR'] = 100  # subsequent saves succeed; the initial save already failed
    _foe_turn(engine)
    engine.end_turn()
    assert 'restrained' not in _conditions(foe)


@pytest.mark.parametrize('sphere,talent,name,speed,flight', [
    ('chains', CHAIN + 'chain_sovereign_incarnation', 'Chain-Sovereign Incarnation', 40, None),
    # AUTO103: the printed text is "gain Fly Speed 60 feet and Hover" -- it grants flight and leaves the
    # walking Speed alone, so the flying numbers are checked through the flight profile, not _effective_speed.
    ('daemonic_cultivation', DAEMON + 'DEMON_EMPEROR_INCARNATION', 'Demon Emperor Incarnation', 30, (60, True)),
    ('dark', 'TAL_DARK_ONE_WITH_THE_NIGHT', 'One With The Night', 30, None),
])
def test_transformation_sets_its_printed_speed_without_damage_or_enemy_saves_at_cast(sphere, talent, name, speed, flight):
    _, engine = _fight(sphere, talent)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    hp, position = me.current_hp, foe.position
    _cast(engine, name)
    assert me.current_hp == hp and foe.current_hp == TOUGH
    if sphere == 'chains':
        from combat.flight import profile
        assert engine._effective_speed(me) == me.speed_ft
        assert profile(engine, me).speed_ft == speed and profile(engine, me).hover
    else:
        assert engine._effective_speed(me) == speed
    if flight is not None:
        from combat.flight import profile

        flown = profile(engine, me)
        assert (flown.speed_ft, bool(flown.hover)) == flight, \
            'the printed Fly Speed and Hover must be real, not folded into the walking Speed'
    assert not _events(engine, 'DAMAGE_COMMITTED', 'SAVE_ROLLED', 'MOVEMENT_GRANTED')
    assert foe.position == position and not foe.conditions and not foe.modifiers


@pytest.mark.parametrize('sphere,talent,name,option', [
    ('chains', CHAIN + 'chain_web', 'Chain Web', ''),
    ('chains', CHAIN + 'world_bound_in_chains', 'World Bound in Chains', ''),
    ('chains', CHAIN + 'chains_domain_court_of_the_ten_thousand_links', 'Chains Domain', ''),
    ('daemonic_cultivation', 'tianxia.talent.daemonic_cultivation.demon_sovereign_aura', 'Demon Sovereign Aura', ''),
    ('daemonic_cultivation', DAEMON + 'HELL_OPENS_BENEATH_THE_SECT_GATE', 'Hell Opens', 'Damage'),
])
def test_domains_resolve_saves_on_turn_start_not_on_creation(sphere, talent, name, option):
    _, engine = _fight(sphere, talent, dc=PASSES)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    resources = {k: v for k, v in me.resources.items() if 'core.qi' not in k and 'uses.' not in k}
    _cast(engine, name, option)
    assert not _events(engine, 'SAVE_ROLLED', 'DAMAGE_COMMITTED', 'MOVEMENT_GRANTED', 'FORCED_MOVEMENT')
    assert foe.current_hp == TOUGH and me.temporary_hp == 0
    assert {k: v for k, v in me.resources.items() if k in resources} == resources
    assert zones.typed_zones(engine)
    _foe_turn(engine)
    assert len(_events(engine, 'SAVE_ROLLED')) == 1


@pytest.mark.parametrize('dc,condition', [(FAILS, 'restrained'), (PASSES, 'bound')])
def test_chain_web_keeps_save_branches_distinct_and_scales_at_nascent_soul(dc, condition):
    _, engine = _fight('chains', CHAIN + 'chain_web', dc=dc)
    foe = engine.state.actors[AN]
    _cast(engine, 'Chain Web')
    _foe_turn(engine)
    roll = _events(engine, 'DAMAGE_ROLLED')[-1].payload
    assert roll['expression'].startswith('4d8')
    assert TOUGH - foe.current_hp == (roll['total'] if dc == FAILS else roll['total'] // 2)
    assert _conditions(foe) & {'restrained', 'bound'} == {condition}
    assert (foe.position.x, foe.position.y) in zones.difficult_cells(engine, foe)


def test_chain_web_also_triggers_on_entry_once_per_turn():
    _, engine = _fight('chains', CHAIN + 'chain_web', foe_at=(12, 6))
    _cast(engine, 'Chain Web')
    foe = engine.state.actors[AN]
    start = Position(x=25, y=6)
    zones.on_moved(engine, foe, start, foe.position)
    assert len(_events(engine, 'SAVE_ROLLED')) == 1
    zones.on_moved(engine, foe, start, foe.position)
    assert len(_events(engine, 'SAVE_ROLLED')) == 1


def test_chain_sovereign_presence_saves_only_when_an_enemy_starts_inside():
    _, engine = _fight('chains', CHAIN + 'chain_sovereign_incarnation', dc=PASSES)
    _cast(engine, 'Chain-Sovereign Incarnation')
    _foe_turn(engine)
    assert engine._effective_speed(engine.state.actors[AN]) == 25
    assert len(_events(engine, 'SAVE_ROLLED')) == 1


def test_drag_down_does_not_assume_a_collision_or_landing():
    _, engine = _fight('chains', CHAIN + 'drag_down_the_flying_crane')
    foe = engine.state.actors[AN]
    # Printed target is one flying creature. A grounded creature cannot be
    # selected, pushed sideways, damaged by a map hazard, or charged CP for it.
    assert not any('Drag Down' in c.display_name for c in engine.legal_candidates())
    assert foe.current_hp == TOUGH and 'prone' not in _conditions(foe)
    foe.position = foe.position.model_copy(update={'z': 2})
    foe.fly_speed_ft = 30
    assert any('Drag Down' in c.display_name for c in engine.legal_candidates())


@pytest.mark.parametrize('cl,dice', [(11, '3d6'), (17, '4d6')])
def test_grappling_chain_additional_dice_follow_realm(cl, dice):
    _, engine = _fight('chains', LASH, CHAIN + 'grappling_chain', cl=cl)
    _cast(engine, 'Chain Lash', 'Grappling Chain')
    assert any(e.payload['expression'].startswith(dice) for e in _events(engine, 'DAMAGE_ROLLED'))


def test_heavenly_anchor_does_not_deny_reactions():
    _, engine = _fight('chains', CHAIN + 'heavenly_anchor')
    _cast(engine, 'Heavenly Anchor')
    assert 'reaction_denied' not in _conditions(engine.state.actors[AN])


@pytest.mark.parametrize('dc,distance', [(PASSES, 5), (FAILS, 15)])
def test_hooked_step_grants_only_its_save_branch_movement(dc, distance):
    _, engine = _fight('chains', CHAIN + 'hooked_step', dc=dc)
    _cast(engine, 'Hooked Step')
    assert sum(e.payload['distance_ft'] for e in _events(engine, 'MOVEMENT_GRANTED')) == distance


def test_lock_weapon_hand_does_not_add_a_blanket_unsaved_debuff():
    bundle, engine = _fight('chains', LASH, CHAIN + 'lock_the_weapon_hand', dc=PASSES)
    variants = [r['display_name'] for r in bundle['action_catalog'] if 'Lock the Weapon Hand' in r['display_name']]
    _cast(engine, variants[0] if variants else 'Chain Lash')
    assert not variants  # object-specific attacks/checks require adjudication, not an unconditional variant
    assert not engine.state.actors[AN].modifiers


@pytest.mark.parametrize('dc,remaining,after', [(FAILS, 25, 0), (PASSES, 25, 15), (PASSES, 3, 0)])
def test_restraining_hook_changes_only_the_movement_still_available(dc, remaining, after):
    bundle, engine = _fight('chains', CHAIN + 'restraining_hook', dc=dc)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    row = next(r for r in bundle['typed_reactions'] if r['feature_id'] == CHAIN + 'restraining_hook')
    _foe_turn(engine)
    foe.movement_remaining_ft = remaining
    typed_reactions._run_generic_effects(engine, me, foe, row, row['effects'])
    assert foe.movement_remaining_ft == after
    assert engine._effective_speed(foe) == 30 and not foe.modifiers
    moves = [c for c in engine.legal_candidates() if c.display_name.startswith('Move to')]
    assert bool(moves) is bool(after)
    event = _events(engine, 'MOVEMENT_GRANTED')[-1]
    assert event.actor_id == AN and event.payload['distance_ft'] == after - remaining
    engine.end_turn()
    engine.end_turn()
    assert foe.movement_remaining_ft == 30
    assert engine._effective_speed(foe) == 30


def test_weighted_links_does_not_push_on_the_slow_option():
    _, engine = _fight('chains', LASH, CHAIN + 'weighted_links')
    foe = engine.state.actors[AN]
    position = foe.position
    _cast(engine, 'Chain Lash', 'Reduce Speed')
    assert foe.position == position and engine._effective_speed(foe) == 25


def test_demon_shadow_step_defers_the_bonus_to_the_next_melee_hit():
    _, engine = _fight('daemonic_cultivation', DAEMON + 'DEMON_SHADOW_STEP')
    foe = engine.state.actors[AN]
    # The printed teleport must land adjacent to a marked, Frightened, or below-half-HP creature.
    foe.current_hp = foe.maximum_hp // 2 - 1
    before = foe.current_hp
    _cast(engine, 'Demon-Shadow Step')
    assert foe.current_hp == before and not _events(engine, 'DAMAGE_COMMITTED')
    me = engine.state.actors[ME]
    assert any(m.target_field == 'typed_on_hit' for m in me.modifiers.values())
    # A deterministic melee attack follows the compiled teleport; its next hit consumes the bonus.
    foe.position = Position(x=me.position.x + 1, y=me.position.y)
    attack = _typed_action(engine, ME, [{'type': 'attack', 'attack_kind': 'cultivation_melee',
        'on_hit': [{'type': 'damage', 'flat': 1, 'damage_types': ['bludgeoning']}]}])
    attack.parameters['typed']['numbers']['attack_bonus'] = 100
    _use(engine, ME, attack, AN)
    assert any(e.payload.get('damage_type') in ('NECROTIC', 'PSYCHIC') for e in _events(engine, 'DAMAGE_COMMITTED'))
    assert not any(m.target_field == 'typed_on_hit' for m in me.modifiers.values())


def test_dread_appetite_lasts_through_the_caster_next_turn():
    _, engine = _fight('daemonic_cultivation', DAEMON + 'DREAD_APPETITE')
    foe = engine.state.actors[AN]
    _cast(engine, 'Dread Appetite: Frighten')
    assert 'frightened' in _conditions(foe)
    _foe_turn(engine)
    assert 'frightened' in _conditions(foe)
    engine.end_turn()
    assert 'frightened' in _conditions(foe)
    engine.end_turn()
    assert 'frightened' not in _conditions(foe)


def test_inner_incarnation_activates_demon_seed_without_its_extra_cost():
    _, engine = _fight('daemonic_cultivation', DAEMON + 'INNER_DEMON_INCARNATION')
    me = engine.state.actors[ME]
    before = me.resources['resource:core.qi']
    _cast(engine, 'Inner Demon Incarnation')
    assert 'stance.demon_seed' in _conditions(me)
    assert me.temporary_hp == 6
    assert me.resources['resource:core.qi'] == before - 8


def test_world_maw_mark_expires_and_nonlethal_use_does_not_award_kill_rewards():
    _, engine = _fight('daemonic_cultivation', DAEMON + 'WORLD_DEVOURING_MAW')
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    essence = me.resources['resource:named.devoured_essence']
    corruption = me.resources.get('resource:named.corruption', 0)
    _cast(engine, 'World-Devouring Maw')
    marks = [c for c in foe.conditions.values() if c.condition_id.startswith('condition:typed.mark.demon_mark')]
    assert marks and all(c.expires_on != 'UNTIL_REMOVED' for c in marks)
    assert me.resources['resource:named.devoured_essence'] == essence
    assert me.resources['resource:named.corruption'] == corruption + 1
    assert not any(m.target_field == 'healing_reduction' for m in me.modifiers.values())


def test_steal_heaven_does_not_apply_both_contested_outcomes_automatically():
    talent = 'tianxia.talent.daemonic_cultivation.steal_the_enemy_s_heaven'
    bundle, engine = _fight('daemonic_cultivation', talent)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    before = dict(me.resources)
    rows = [r for r in bundle['typed_reactions'] if r['feature_id'] == talent]
    for row in rows:
        typed_reactions._run_generic_effects(engine, me, foe, row, row['effects'])
    assert not _events(engine, 'RESOURCE_GAINED')
    assert me.resources == before
    assert not me.modifiers and not foe.modifiers


def test_night_that_swallows_the_lantern_holds_at_one_hp_once_per_fight():
    _, engine = _fight('dark', 'TAL_DARK_NIGHT_THAT_SWALLOWS_THE_LANTERN')
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    me.current_hp = 8
    pending = typed_reactions._offer_drop_to_zero_or_bloodied(engine, me, foe, 20, 0, AN)
    assert pending == 7
    me.reaction_available = True
    assert typed_reactions._offer_drop_to_zero_or_bloodied(engine, me, foe, 20, 0, AN) == 20
