"""Combat regressions for Gravity, Guardian, and Harvesting/Gathering typings."""

import copy
import json
from functools import lru_cache
from pathlib import Path

import pytest

from combat import typed_executor as te, typed_reactions as tr
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from tests.test_auto_support import ME, _engine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
AUTH = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
KIT = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.fu', 'name': 'Fu (Short Axe)', 'quantity': 1}]}}
GRAVITY = 'tianxia.talent.gravity.'
GUARDIAN = 'TAL_GUARDIAN_'
HARVEST = 'tianxia.talent.harvesting_gathering.'


@lru_cache(maxsize=None)
def _compiled(key, cl=20, dc=50):
    sphere = AUTH[key]['sphere_id']
    bases = [k for k, v in AUTH.items() if v.get('sphere_id') == sphere and v.get('kind') == 'base_ability']
    sheet = {**SHEET, 'equipment': [KIT],
             'identity': {**SHEET['identity'], 'cultivation_level': cl},
             'ability_scores_and_statistics': {**SHEET['ability_scores_and_statistics'],
                 'technique_save_dc': dc, 'technique_attack_bonus': 40,
                 'primary_resource': {'name': 'Qi', 'maximum': 100}},
             'spheres_and_talents': {'sphere_record_ids': [sphere],
                 'learned_talent_record_ids': list(dict.fromkeys([*bases, key]))}}
    return compile_character(sheet, actor_id=ME)


def _fight(key, cl=20, dc=50, foe_at=(4, 6)):
    bundle = copy.deepcopy(_compiled(key, cl, dc))
    engine = _engine(bundle, foe_at=foe_at)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    foe.maximum_hp = foe.current_hp = 2000
    foe.armor_class = -50
    me.resources['resource:core.martial_focus'] = 1
    return bundle, engine, me, foe


def _cast(engine, prefix, contains=''):
    candidates = [c for c in engine.legal_candidates()
                  if c.display_name.startswith(prefix) and contains in c.display_name]
    assert candidates, (prefix, contains)
    pos = engine.state.actors[AN].position
    candidate = min(candidates, key=lambda c: 0 if c.destination is None else
                    abs(c.destination.x - pos.x) + abs(c.destination.y - pos.y))
    engine.execute_intent(ActionIntent(intent_id='review', decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=ME,
        target_ids=candidate.target_ids, destination=candidate.destination))


def _events(engine, kind):
    return [event.payload for event in engine.events if event.event_type == kind]


def _damage(engine):
    return [p['expression'].removesuffix('+0') for p in _events(engine, 'DAMAGE_ROLLED')]


def _conditions(actor, name):
    return [c for c in actor.conditions.values() if c.condition_id == 'condition:typed.' + name]


@pytest.mark.parametrize('cl,dice', [(1, '3d6'), (10, '3d6'), (11, '5d6'), (16, '5d6'), (17, '7d6'), (20, '7d6')])
def test_crushing_field_waits_for_turn_start_and_scales(cl, dice):
    _, engine, me, foe = _fight('TAL_GRAVITY_CRUSHING_FIELD', cl=cl)
    _cast(engine, 'Crushing Field')
    assert foe.current_hp == 2000 and not _events(engine, 'SAVE_ROLLED')
    engine.end_turn()
    assert _damage(engine) == [dice]


def test_gravity_well_does_not_knock_every_target_prone():
    _, engine, me, foe = _fight('TAL_GRAVITY_GRAVITY_WELL')
    _cast(engine, 'Gravity Well')
    assert not _conditions(foe, 'prone')


def test_black_star_grip_does_not_deal_turn_start_damage_at_cast():
    _, engine, me, foe = _fight(GRAVITY + 'black_star_grip')
    _cast(engine, 'Black-Star Grip')
    assert _conditions(foe, 'grappled')
    assert foe.current_hp == 2000


def test_event_horizon_prison_waits_for_turn_start():
    _, engine, me, foe = _fight(GRAVITY + 'event_horizon_prison')
    _cast(engine, 'Event Horizon Prison')
    assert foe.current_hp == 2000 and not _events(engine, 'SAVE_ROLLED')
    engine.end_turn()
    assert _damage(engine) == ['6d10']


@pytest.mark.parametrize('cl,dice', [(1, '1d8'), (4, '1d8'), (5, '2d8'), (10, '2d8'), (11, '3d8'), (16, '3d8'), (17, '4d8'), (20, '4d8')])
def test_falling_line_damage_scales_with_level(cl, dice):
    _, engine, me, foe = _fight(GRAVITY + 'falling_line', cl=cl)
    _cast(engine, 'Falling Line')
    assert _damage(engine) == [dice]


def test_gravitic_armor_does_not_grant_lightening_speed_in_neutral_mode():
    _, engine, me, foe = _fight(GRAVITY + 'gravitic_armor')
    _cast(engine, 'Gravitic Armor')
    assert engine._effective_speed(me) == 30
    assert any(m.target_field == 'armor_class' and m.value == 2 for m in me.modifiers.values())


def test_heavens_weight_defers_its_turn_start_damage():
    _, engine, me, foe = _fight(GRAVITY + 'heaven_s_weight')
    _cast(engine, 'Heaven’s Weight')
    assert _conditions(foe, 'restrained') and foe.current_hp == 2000


def test_heavens_weight_success_stops_movement_until_the_targets_turn():
    _, engine, me, foe = _fight(GRAVITY + 'heaven_s_weight', dc=-40)
    _cast(engine, 'Heaven’s Weight')
    assert engine._effective_speed(foe) == 0
    engine.end_turn()
    assert engine._effective_speed(foe) == 30


def test_moon_weight_incarnation_does_not_knock_an_enemy_prone():
    _, engine, me, foe = _fight(GRAVITY + 'moon_weight_incarnation')
    _cast(engine, 'Moon-Weight Incarnation')
    assert engine._effective_speed(me) == 50 and not _conditions(foe, 'prone')


def test_orbiting_guard_does_not_grant_melee_miss_movement_at_cast():
    _, engine, me, foe = _fight(GRAVITY + 'orbiting_guard')
    _cast(engine, 'Orbiting Guard')
    assert me.movement_remaining_ft == 30
    assert any(m.target_field == 'armor_class' and m.value == 1 for m in me.modifiers.values())


@pytest.mark.parametrize('dc', [50, -40])
def test_world_crushing_pressure_waits_for_turn_start(dc):
    _, engine, me, foe = _fight(GRAVITY + 'world_crushing_pressure', dc=dc)
    _cast(engine, 'World-Crushing Pressure')
    assert foe.current_hp == 2000 and not _events(engine, 'SAVE_ROLLED')
    engine.end_turn()
    assert _damage(engine) == ['8d8']
    assert engine._effective_speed(foe) == (0 if dc == 50 else 15)


def test_challenge_has_no_effect_after_a_successful_save():
    _, engine, me, foe = _fight('GUARDIAN_BASE_CHALLENGE_PRACTICE', dc=-40)
    _cast(engine, 'Challenge Practice')
    assert not foe.modifiers and not foe.conditions


@pytest.mark.parametrize('damage_type', ['ACID', 'BLUDGEONING', 'COLD', 'FIRE', 'LIGHTNING', 'NECROTIC', 'PIERCING', 'POISON', 'RADIANT', 'SLASHING', 'THUNDER', 'FORCE', 'PSYCHIC'])
def test_adamant_incarnations_resistance_preserves_its_exceptions(damage_type):
    _, engine, me, foe = _fight(GUARDIAN + 'ADAMANT_GUARDIAN_INCARNATION')
    _cast(engine, 'Adamant Guardian Incarnation')
    me.maximum_hp = me.current_hp = 200
    engine._commit_damage(me, 20, damage_type, 'test:attack', AN, None, reaction_depth=0)
    from combat.ext.guardian_chassis import stored  # rider lane C16: after Resistance a Guardian may hold the rest in Held Harm

    assert me.current_hp - stored(me) == (180 if damage_type in ('FORCE', 'PSYCHIC') else 190)


@pytest.mark.parametrize('remaining,expected', [(30, 20), (5, 0)])
def test_fortress_denial_reduces_the_targets_remaining_movement(remaining, expected):
    key = GUARDIAN + 'FORTRESS_BREAKER_S_DENIAL'
    bundle, engine, me, foe = _fight(key, dc=-40)
    row = next(r for r in bundle['typed_reactions'] if r.get('feature_id') == key)
    foe.movement_remaining_ft = remaining
    tr._run_generic_effects(engine, me, foe, row, row['effects'])
    assert foe.movement_remaining_ft == expected
    assert me.movement_remaining_ft == 30 and engine._effective_speed(foe) == 30


@pytest.mark.parametrize('damage,granted', [(100, 0), (1, 5)])
def test_heaven_defying_bulwark_moves_only_after_zero_damage(damage, granted):
    key = GUARDIAN + 'HEAVEN_DEFYING_BULWARK'
    bundle, engine, me, foe = _fight(key)
    engine.typed_reaction_rows[ME] = [r for r in bundle['typed_reactions'] if r.get('feature_id') == key]
    pending = tr.on_damage(engine, me, damage, 0, source_definition_id='test:attack', source_actor_id=AN)
    assert (pending == 0) == (damage == 1)
    assert me.movement_remaining_ft == 30 + granted


@pytest.mark.parametrize('halves,ability,dc', [(True, 'DEX', 1), (True, 'DEX', 100),
                                              (False, 'DEX', 100), (True, 'CON', 100)])
def test_shield_companion_does_not_roll_another_save_or_move_prematurely(
        tmp_path, monkeypatch, halves, ability, dc):
    from combat import embedding_rank, menu_rank
    from tests.cw2_service_support import add_action
    from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle, turn

    monkeypatch.setattr(menu_rank, '_CLIENT', embedding_rank.EmbeddingClient(
        transport=lambda url, body, timeout: {'data': []}))

    def prepare(bundles):
        add_action(bundles[2], 'Blast', [{
            'type': 'save', 'applies_to': 'target', 'ability': ability,
            'on_fail': [{'type': 'damage', 'flat': 12, 'damage_types': ['fire'], 'applies_to': 'target'}],
            'on_success': [{'type': 'half_damage'}] if halves else [],
        }], typed={'numbers': {'save_dc': dc}})

    feature = GUARDIAN + 'SHIELD_COMPANION'
    react, move = 'reaction:typed.' + feature, 'choice:needle.shield_companion_move'
    combat, table, mid = fixture(tmp_path, [feature], bundle_transform=prepare, owner_pb=4, named=True)
    turn(table, mid, FOE)
    engine = combat._load_session(mid).engine
    before = engine.state.actors[ALLY]
    first = engine.state.event_sequence
    blast = candidate(combat, mid, 'Blast', target=ALLY)
    prompts = settle(table, mid, blast.candidate_id, {react: 'USE', move: 'first'})
    engine = reload(tmp_path, mid)
    ally, guardian = engine.state.actors[ALLY], engine.state.actors[OWNER]
    eligible = halves and ability == 'DEX'
    stepped = eligible and dc == 1
    assert [p['context']['reaction_source_id'] for p in prompts] == (
        [react, move] if stepped else [react] if eligible else [])
    assert guardian.reaction_available is not eligible

    events = [event for event in engine.events if event.sequence > first]
    saves = [event for event in events if event.event_type == 'SAVE_ROLLED']
    assert len(saves) == 1 and saves[0].actor_id == ALLY
    assert saves[0].payload['dc'] == dc - (4 if eligible else 0)
    assert ally.current_hp == before.current_hp - (6 if stepped else 12)
    assert ally.movement_remaining_ft == before.movement_remaining_ft
    if stepped:
        damage = next(event for event in events if event.event_type == 'DAMAGE_COMMITTED')
        motion = next(event for event in events if event.event_type == 'MOVEMENT_COMMITTED')
        assert saves[0].sequence < damage.sequence < motion.sequence
        assert ally.position != before.position
        assert engine._distance_actor_to_actor(ally, guardian) == 5
    else:
        assert ally.position == before.position
