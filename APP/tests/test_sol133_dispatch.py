"""Integrated hook contracts: real damage and persisted table decisions."""
import json
import zipfile

import pytest

from combat import typed_reactions
from combat.ext.ironclad_blacksmith import TEMPER
from combat.gate5_service import CombatService
from combat.factory_compiler import compile_character
from combat.gate4_engine import Gate4ControllerEngine
from combat.tabletop_service import TabletopService
from tests import test_auto6_eye_patient_eye as eye
from tests import test_auto17_blacksmith as smith
from tests import test_auto70_berserker as berserk


def assert_no_resistance_failures(engine):
    assert not [e for e in engine.events if '(resistance_ignored) failed:' in str(e.payload)]


@pytest.mark.parametrize('owned', [True, False])
def test_blow_resistance_subscriber_is_dispatched_for_real_damage(owned):
    talents = ['TAL_BERSERKER_BATTER', *([berserk.THE_BLOW] if owned else [])]
    target_id = 'actor:factory.sol133_target'
    engine = Gate4ControllerEngine(eye.ROOT, match_seed='SOL133-RESISTANCE', typed_bundles=(
        compile_character(berserk._berserker_sheet(talents), actor_id=berserk.ME),
        compile_character(berserk._berserker_sheet([]), actor_id=target_id)),
        roster_setup={'primary_actor_ids': [berserk.ME, target_id],
                      'team_by_actor': {berserk.ME: 'team:a', target_id: 'team:b'},
                      'starting_positions': {berserk.ME: {'x': 3, 'y': 6}, target_id: {'x': 4, 'y': 6}}})
    foe = engine.state.actors[target_id]
    engine._add_modifier(foe, 'test:resistant', 'damage_resistance', 'SET', 'ACID', 'SELF',
                         expires_on='UNTIL_REMOVED')
    source = berserk._action(engine, berserk._me(engine),
                             berserk.THE_BLOW if owned else 'TAL_BERSERKER_BATTER').source_definition_id
    before = foe.current_hp
    # ACID has no authored ignore-resistance effect: this packet must consult the subscriber.
    engine._commit_damage(foe, 30, 'ACID', source, berserk.ME, None, reaction_depth=0)
    assert before - foe.current_hp == (30 if owned else 15)
    assert_no_resistance_failures(engine)


@pytest.mark.parametrize('owned,use', [(True, True), (True, False), (False, True)])
def test_patient_eye_dispatched_consent_and_nonowner_reload(tmp_path, monkeypatch, owned, use):
    combat, table, mid = eye.fight(tmp_path, owned=(eye.TALENT,) if owned else ())
    eye.grant(monkeypatch, 'damage_resistance', 'BLUDGEONING')
    eye.dice(monkeypatch, [20] * 80)
    if owned:
        eye.open_record(combat, table, mid)
    else:
        eye.turn(combat, table, mid)
    prompts = eye.play(combat, table, mid, eye.STRIKE, use=use)
    engine = eye.reload(combat, mid)
    damage = eye.packet(engine, actor=eye.LEFT)
    assert damage['reduced_to'] == (damage['rolled_or_pending_damage'] if owned and use
                                    else damage['rolled_or_pending_damage'] // 2)
    assert bool([p for p in prompts if eye.NAME in str(p)]) == owned
    assert bool(engine.state.actors[eye.LEFT].turn_flags.get(eye.RESIST_USED)) == (owned and use)
    assert_no_resistance_failures(engine)


def armor_table(tmp_path):
    for name in ('left', 'right'):
        doc = smith._sheet([], spheres=(smith.SPHERE,) if name == 'left' else ())
        doc['equipment'] = [{'starting_kit': {'items': [
            {'item_id': 'tianxia.mortal.armor.lacquered_lamellar'},
            {'item_id': 'tianxia.mortal.weapon.jian'}]}}]
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 1000
        folder = tmp_path / 'portable_characters' / name
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    combat = CombatService(eye.ROOT, tmp_path)
    combat.tabletop_maps.save({'display_name': 'SOL133 yard', 'width_squares': 12, 'height_squares': 8,
                              'walls': [], 'starts': {'team1': [[3, 4]], 'team2': [[4, 4]]}})
    view = combat.create_factory_match(project_ids=['left'], opponent_actor_ids=[eye.RIGHT],
                                       control_modes={eye.LEFT: 'MANUAL', eye.RIGHT: 'MANUAL'},
                                       arena_id='battlefield:map.sol133-yard', match_seed='SOL133-ARMOR')
    table, mid = TabletopService(combat, tmp_path), view['match_id']
    for label in ['Hammer the Mark', 'Hammer the Mark', 'Fit Armor: Reduce Weapon Damage']:
        assert smith._press(table, mid, eye.LEFT, label)['status'] == 'COMMITTED'
    engine = eye.reload(combat, mid)
    assert smith._condition(engine.state.actors[eye.LEFT], TEMPER)
    eye.end_turn(combat, table, mid)
    eye.turn(combat, table, mid, eye.RIGHT)
    return combat, table, mid


@pytest.mark.parametrize('hit', [False, True])
def test_fit_armor_survives_queries_and_missed_multitype_attack_consumes_only_on_hit(tmp_path, monkeypatch, hit):
    combat, table, mid = armor_table(tmp_path)
    engine = eye.reload(combat, mid)
    wearer = engine.state.actors[eye.LEFT]
    temper = smith._condition(wearer, TEMPER).model_dump(mode='json')
    weapon = next(a for a in engine.action_catalog.values()
                  if a.owner_id == eye.RIGHT and a.display_name.startswith('Jian ('))
    typed = weapon.parameters['typed']
    assert {str(k).upper() for k in typed['weapon']['damage_types']} == {'PIERCING', 'SLASHING'}
    before = engine.state.model_dump(mode='json'), len(engine.events)
    for _ in range(3):
        for kind in ('PIERCING', 'SLASHING'):
            typed_reactions.damage_factor(engine, wearer, kind, weapon.source_definition_id, eye.RIGHT)
            assert smith._condition(wearer, TEMPER).model_dump(mode='json') == temper
    assert (engine.state.model_dump(mode='json'), len(engine.events)) == before
    eye.dice(monkeypatch, [20 if hit else 1] * 80)
    eye.play(combat, table, mid, 'Jian (', actor=eye.RIGHT, target=eye.LEFT)
    engine = eye.reload(combat, mid)
    assert bool(smith._condition(engine.state.actors[eye.LEFT], TEMPER)) == (not hit)
    removals = [e for e in engine.events if e.event_type == 'CONDITION_REMOVED'
                and TEMPER in str(e.payload)]
    assert len(removals) == int(hit), 'only one applied packet consumes the temper'
    if hit:
        damage = eye.packet(engine, actor=eye.RIGHT, target=eye.LEFT)
        assert damage['reduced_to'] == damage['rolled_or_pending_damage'] - temper['data']['pb']
    else:
        assert engine.state.actors[eye.LEFT].current_hp == 1000
        # The same temper remains available for a later successful packet before its deadline.
        assert smith._condition(engine.state.actors[eye.LEFT], TEMPER).data == temper['data']


def test_nonowner_saved_ai_continuation_remains_byte_identical(monkeypatch):
    from combat import ext
    from tests.test_hunt32_inert_replay import _capture

    enabled = _capture()
    callbacks = {('combat.ext.berserker', 'the_blow_ignores_resistance'),
                 ('combat.ext.eye_patient_eye', 'suppress_resistance'),
                 ('combat.ext.ironclad_blacksmith', '_temper_reduction')}
    for point in ('resistance_ignored', 'damage_reduction'):
        monkeypatch.setitem(ext._HOOKS, point, [f for f in ext._HOOKS.get(point, [])
                                              if (f.__module__, f.__name__) not in callbacks])
    assert _capture() == enabled
