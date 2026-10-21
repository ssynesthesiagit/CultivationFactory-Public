"""Hundred-Hand native table regressions.

Lead scope ruling 2026-10-18 (F9R blocking 1): this lane owns combat only; the
source acquisition, world-fact authority and journey continuation producers
(journey_acquire_source/journey_world_fact/end-scene, non-Sphere authority) are
carried by their separately reviewed lanes, so this file no longer exercises
them; those tests moved with that scope. Fights still use portable sheets, real
table intents, journal verification, cold reload and mechanical replay; helper
C7 engine probes cover roll boundaries. No model or GUI transport.
"""
from pathlib import Path
import json
import zipfile
import pytest

from tests import test_riders_c7 as C7
from tests.h48_table_support import assert_reload_verify_replay, candidate
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]
BODY = 'tianxia.path.body_refining'
PARENT = 'tianxia.subpath.body.hundred_hand_battle_mandala'
PREFIX = PARENT + '.feature.'
HANDS = 'resource:named.battle_hand'
OWNER, FOE, THIRD = [FACTORY_ACTOR_PREFIX + 'mandala-' + key for key in ('owner', 'foe', 'third')]
FEATURES = {'four_hand_sequence': 3, 'weapon_wheel_body': 6, 'eight_limb_battle_pattern': 10,
            'circle_of_uncounted_arms': 14, 'thousand_hand_incarnation': 18}


def table_fixture(tmp_path, cl=18, seed='MANDALA-NATIVE', third=False, items=(C7.JIAN, C7.GUN), align_owner=True, overall_cl=None, body_attacks=False, foe_at=(4, 6), maximum_rounds=15, global_key='CON', ability_mods=None, owner_features=()):
    """A real native fight compiled from the owner's portable sheet.

    The printed Body attainment is declared on the committed sheet
    (path_and_subpath.paths), exactly as C7._mandala does in-process; no journey
    source acquisition is involved after the scope ruling.
    """
    actual_cl = overall_cl or cl
    ids = [PREFIX + slug for slug, level in FEATURES.items() if level <= cl]
    base = []
    if body_attacks:
        index = json.loads((ROOT / 'non_sphere_authority/authority/body_refining.path_index.p2a.json').read_text())
        base = [row['canonical_id'] for row in index['features'] if row['feature_kind'] == 'attack_chassis' and row.get('minimum_cl', 99) <= cl]
    sheets = [C7.sheet([*base, *ids, *owner_features], cl=actual_cl, items=items, mods=ability_mods), C7.sheet([], cl=actual_cl)]
    ids_in_fight = [OWNER, FOE] + ([THIRD] if third else [])
    if third:
        sheets.append(C7.sheet([], cl=actual_cl))
    for aid, document in zip(ids_in_fight, sheets):
        document['identity']['display_name'] = 'Mandala' if aid == OWNER else 'Opponent'
        if aid == OWNER:
            document['identity']['key_ability'] = global_key
        document['path_and_subpath']['path_record_ids'] = [BODY]
        document['path_and_subpath']['paths'] = [{'path_id': BODY, 'attained_cl': cl, 'effective_cl': cl}]
        document['ability_scores_and_statistics']['hit_points']['maximum'] = 1000
        document['ability_scores_and_statistics']['technique_attack_bonus'] = 100
        folder = tmp_path / 'portable_characters' / aid.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    combat.tabletop_maps.save({'map_id': 'mandala-native', 'display_name': 'Mandala native hall',
        'width_squares': 20, 'height_squares': 14, 'walls': [], 'terrain': [],
        'starts': {'team1': [[3, 6]], 'team2': [[4, 6]]}})
    positions = {OWNER: {'x': 3, 'y': 6}, FOE: {'x': foe_at[0], 'y': foe_at[1]}}
    if third:
        positions[THIRD] = {'x': 3, 'y': 7}
    state = combat.create_journey(project_ids=[aid.removeprefix(FACTORY_ACTOR_PREFIX) for aid in ids_in_fight],
        arena_id='battlefield:map.mandala-native', positions=positions,
        base_paces={aid: 100 for aid in ids_in_fight}, control_modes={aid: 'MANUAL' for aid in ids_in_fight})
    jid = state['journey_id']
    match = combat.journey_start_combat(jid, state['revision'],
        {aid: 'team:a' if aid == OWNER else 'team:b' for aid in ids_in_fight}, positions=positions,
        maximum_rounds=maximum_rounds)['match_id']

    def commit(cid, picks=None):
        commit.prompts = []
        answers = []
        counts = {}
        for _ in range(100):
            menu = table.state(match)['menu']
            result = table.act(match, cid, menu['decision_id'], menu['state_version'], 0, answers)
            if result['status'] == 'COMMITTED':
                assert_reload_verify_replay(combat, match, tmp_path)
                return result
            assert result['status'] == 'REACTION_REQUIRED', result
            prompt = result['reaction']
            commit.prompts.append(prompt)
            answer = {**prompt['context'], 'selection': 'DECLINE'}
            choice = prompt.get('choice')
            if choice:
                options = [option['id'] for option in choice['options']]
                desired = None
                for key, value in (picks or {}).items():
                    if key not in str(prompt):
                        continue
                    if isinstance(value, list):
                        index = counts.get(key, 0)
                        counts[key] = index + 1
                        value = value[index] if index < len(value) else None
                    if value in options:
                        desired = value
                        break
                if desired:
                    answer.update(selection='USE', option_ids=[desired])
                elif not choice.get('allow_decline', True):
                    answer.update(selection='USE', option_ids=options[:1])
            elif any(key in str(prompt) and value == 'USE' for key, value in (picks or {}).items() if not isinstance(value, list)):
                answer.update(selection='USE')
            answers.append(answer)
        raise AssertionError('choice did not settle')
    for _ in range(8 if align_owner else 0):
        menu = table.state(match)['menu']
        if menu['actor_id'] == OWNER:
            break
        commit(menu['end_turn'])
    return combat, table, match, commit


def test_native_four_hand_guard_commits_and_expires_on_owner_turn(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, cl=3)
    commit(candidate(table, match, 'Unarmed', FOE), {'four_hand_opening': 'ac'})
    state = CombatService(ROOT, tmp_path)._load_session(match).engine.state
    me = state.actors[OWNER]
    assert me.resources[HANDS] == me.proficiency_bonus - 1
    assert any(m.value == 1 and m.target_field == 'armor_class' for m in me.modifiers.values())
    for _ in range(2):
        commit(table.state(match)['menu']['end_turn'])
    me = CombatService(ROOT, tmp_path)._load_session(match).engine.state.actors[OWNER]
    assert not any(m.value == 1 and m.target_field == 'armor_class' for m in me.modifiers.values())
    assert me.resources[HANDS] == me.proficiency_bonus


def test_native_incarnation_cost_and_actual_maximum_survive_reload(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path)
    commit(candidate(table, match, 'Thousand-Hand Incarnation'))
    me = CombatService(ROOT, tmp_path)._load_session(match).engine.state.actors[OWNER]
    assert me.resources[C7.STAMINA] == 53
    assert me.resources[HANDS] == me.resource_maximums[HANDS] == 2 * me.proficiency_bonus
    assert not any('Thousand-Hand Incarnation' in action['label'] for action in table.state(match)['menu']['actions'])


def test_miss_addition_preserves_the_natural_die_and_is_not_a_reroll():
    engine, me, foe = C7._mandala(['four_hand_sequence'], picks={'four_hand_opening': None})
    C7._force_next_d20(engine, 18)
    attack = next(a for a in engine.action_catalog.values() if a.display_name == C7.unarmed(engine))
    foe.armor_class = 18 + attack.parameters['typed']['numbers']['attack_bonus'] + 4
    events = C7.use(engine, C7.unarmed(engine), target=foe.entity_id)
    roll = C7.payloads(events, 'ATTACK_ROLLED')[0]
    assert roll['natural_result'] == 18
    assert roll['modified_total'] >= foe.armor_class
    rewrites = C7.payloads(events, 'D20_REWRITTEN')
    assert rewrites and all(event['operation'] == 'bonus' and event['original']['natural_result'] == event['result']['natural_result']
                            and event['original']['dice'] == event['result']['dice'] for event in rewrites)
    assert me.resources[HANDS] == 5


def test_four_hand_damage_is_in_the_triggering_packet():
    engine, me, foe = C7._mandala(['four_hand_sequence'], picks={'four_hand_opening': None, 'four_hand_sequence': ['damage']})
    foe.armor_class = -50
    events = C7.use(engine, C7.unarmed(engine), target=foe.entity_id)
    packets = [e for e in events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == me.entity_id and foe.entity_id in e.target_ids]
    baseline, _, other = C7._mandala(['four_hand_sequence'], picks={'four_hand_opening': None, 'four_hand_sequence': None})
    other.armor_class = -50
    before = C7.use(baseline, C7.unarmed(baseline), target=other.entity_id)
    original = [e for e in before if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == me.entity_id and other.entity_id in e.target_ids]
    assert len(packets) == len(original), [(e.source_definition_id, e.payload) for e in packets]
    assert me.resources[HANDS] == 5


def test_resource_maximum_is_normal_without_incarnation():
    engine, me, _ = C7._mandala(['four_hand_sequence', 'thousand_hand_incarnation'], picks={'four_hand_opening': None})
    assert me.resource_maximums[HANDS] == me.resources[HANDS] == 6


def test_default_inert_wrong_owner_has_no_family_choices():
    engine = C7.fight(C7.bundle([]))
    events = C7.use(engine, C7.unarmed(engine), target=C7.foe_id(engine))
    assert HANDS not in engine.state.actors[C7.ME].resources
    assert not any(e.source_definition_id.startswith(PREFIX) for e in events)


def test_wheel_stowed_weapon_is_not_a_second_form():
    engine, me, _ = C7._mandala(['weapon_wheel_body'])
    C7.use(engine, 'Stow Jian (Straight Sword) (frees 1 hand; no Action)')
    C7.use(engine, 'Stow Gun (Staff) (frees 1 hand; no Action)')
    assert not any('(Constitution)' in name for name in C7.legal(engine))


def test_additional_reaction_refreshes_at_owner_turn_not_round():
    from combat.ext.reaction_economy import waive
    engine, me, _ = C7._mandala(['circle_of_uncounted_arms', 'thousand_hand_incarnation'])
    C7.use(engine, 'Thousand-Hand Incarnation')
    me.reaction_available = False
    row = {'feature_id': PREFIX + 'circle_of_uncounted_arms', 'native_checkpoint': 'CIRCLE_DECLARED'}
    assert waive(engine, me, row, False) == 'free'  # earned on the activation turn itself
    assert waive(engine, me, row, True) == 'free'
    engine.state.round_number += 1
    assert waive(engine, me, row, False) is None  # the round tick alone does not refresh it
    C7.turn(engine, C7.ME)
    me.reaction_available = False
    assert waive(engine, me, row, False) == 'free', ('owner_refresh', me.turns_started, me.turn_flags)


def test_four_hand_critical_packet_adds_pb_only_once():
    engine, me, foe = C7._mandala(['four_hand_sequence'], picks={'four_hand_opening': None, 'four_hand_sequence': ['damage']})
    action = next(a for a in engine.action_catalog.values() if a.owner_id == me.entity_id and a.display_name == C7.unarmed(engine))
    base = action.parameters['typed']['weapon']['damage']['modifier']
    C7._force_next_d20(engine, 20)
    events = C7.use(engine, C7.unarmed(engine), target=foe.entity_id)
    damage = next(e.payload for e in events if e.event_type == 'DAMAGE_ROLLED' and e.source_definition_id == action.source_definition_id)
    assert damage['critical'] and damage['modifier'] == base + me.proficiency_bonus


def test_native_circle_deflect_commits_on_the_other_creatures_turn(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, cl=14, seed='MANDALA-CIRCLE')
    commit(table.state(match)['menu']['end_turn'])
    assert table.state(match)['menu']['actor_id'] == FOE
    commit(candidate(table, match, 'Unarmed', OWNER), {'circle_of_uncounted_arms': 'deflect'})
    me = CombatService(ROOT, tmp_path)._load_session(match).engine.state.actors[OWNER]
    assert me.resources[HANDS] == me.proficiency_bonus - 2
    assert not me.reaction_available
    assert len(me.turn_flags['_round_circle_uses']['turns']) == 1


def test_native_eight_limb_uses_real_hands_and_different_form(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, cl=10, seed='MANDALA-EIGHT')
    engine = combat._load_session(match).engine
    different = next(a.source_definition_id + '|' + FOE for a in engine.action_catalog.values()
                     if a.owner_id == OWNER and a.source_definition_id.endswith('#mandala_con') and '.weapon.jian' in a.source_definition_id)
    commit(candidate(table, match, 'Unarmed', FOE), {'eight_limb_attack': different})
    engine = CombatService(ROOT, tmp_path)._load_session(match).engine
    assert engine.state.actors[OWNER].resources[HANDS] == engine.state.actors[OWNER].proficiency_bonus - 2
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]
    assert len(attacks) >= 2
    assert 'weapon.jian' in attacks[-1].source_definition_id


def test_native_weapon_wheel_selects_each_weapon_and_granted_form(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, cl=10, seed='MANDALA-WHEEL')
    engine = combat._load_session(match).engine
    blade = next(a.source_definition_id + '|' + FOE for a in engine.action_catalog.values()
                 if a.owner_id == OWNER and a.source_definition_id.endswith('#mandala_con') and '.weapon.jian' in a.source_definition_id)
    unarmed = next(a.source_definition_id + '|' + FOE for a in engine.action_catalog.values()
                   if a.owner_id == OWNER and a.display_name == C7.unarmed(engine, OWNER))
    commit(candidate(table, match, 'Weapon-Wheel Body: Attack with weapon choices'),
           {'weapon_wheel_gear': 'keep', 'weapon_wheel_attack': blade, 'eight_limb_attack': unarmed})
    engine = CombatService(ROOT, tmp_path)._load_session(match).engine
    rolls = [e.payload for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]
    assert len(rolls) == 2
    assert len(rolls[-1]['dice']) == 2
    assert engine.state.actors[OWNER].resources[HANDS] == 2


def test_native_incarnation_circle_twice_on_distinct_creature_turns(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, third=True, seed='MANDALA-TWO-CIRCLES')
    commit(candidate(table, match, 'Thousand-Hand Incarnation'))
    # The extra Reaction is first granted at the start of the next owner turn.
    commit(table.state(match)['menu']['end_turn'])
    while table.state(match)['menu']['actor_id'] != OWNER:
        commit(table.state(match)['menu']['end_turn'])
    commit(table.state(match)['menu']['end_turn'])
    seen = []
    for _ in range(2):
        menu = table.state(match)['menu']
        assert menu['actor_id'] in (FOE, THIRD)
        seen.append(menu['actor_id'])
        commit(candidate(table, match, 'Unarmed', OWNER), {'circle_of_uncounted_arms': 'deflect'})
        commit(table.state(match)['menu']['end_turn'])
    assert len(set(seen)) == 2
    engine = CombatService(ROOT, tmp_path)._load_session(match).engine
    # At the owner's next turn the Hands refresh, but the round's reaction
    # receipts still prove both independently paid uses during distinct turns.
    uses = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == PREFIX + 'circle_of_uncounted_arms']
    assert len(uses) == 2
    spent = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == PREFIX + 'circle_of_uncounted_arms']
    assert sum(e.payload['amount'] for e in spent) == 4


def test_native_ambiguous_weapon_form_is_private_fixed_and_replayed(tmp_path):
    from combat.fact_consent_admission import combat_records
    from combat.ext.hundred_hands import form_for, FORM_SOURCE
    combat, table, match, commit = table_fixture(tmp_path, cl=6, items=(C7.JIAN, 'tianxia.mortal.weapon.gong_jian'), seed='MANDALA-FORM')
    commit(candidate(table, match, 'Record Weapon Form:'), {'weapon_form': 'Hafted'})
    engine = CombatService(ROOT, tmp_path)._load_session(match).engine
    me, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    records = combat_records(engine, me, source=FORM_SOURCE, kind='weapon_form')
    assert len(records) == 1 and records[0]['value'] == 'Hafted'
    assert records[0]['authority'] == OWNER and records[0]['expires_on'] == 'UNTIL_REMOVED'
    assert combat_records(engine, foe, source=FORM_SOURCE, kind='weapon_form') == []
    weapon = next(a for a in engine.action_catalog.values() if a.owner_id == OWNER and '.weapon.gong_jian' in a.source_definition_id and '#' not in a.source_definition_id)
    assert form_for(engine, me, weapon) == 'Hafted'
    assert not any('Record Weapon Form:' in action['label'] for action in table.state(match)['menu']['actions'])


def test_native_pool_is_capped_before_the_first_owner_turn(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, align_owner=False)
    engine = CombatService(ROOT, tmp_path)._load_session(match).engine
    me = engine.state.actors[OWNER]
    assert me.resources[HANDS] == me.resource_maximums[HANDS] == me.proficiency_bonus
    commit(table.state(match)['menu']['end_turn'])


def test_native_four_hand_movement_pays_the_attack_action(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, cl=3)
    commit(candidate(table, match, 'Unarmed', FOE), {'four_hand_opening': 'move', 'four_hand_move': 'cell:2,6'})
    me = CombatService(ROOT, tmp_path)._load_session(match).engine.state.actors[OWNER]
    assert (me.position.x, me.position.y) == (2, 6)
    assert not me.action_available
    assert me.resources[HANDS] == me.proficiency_bonus - 1


def test_native_wheel_replaces_ordinary_physical_modifier(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, cl=6)
    engine = CombatService(ROOT, tmp_path)._load_session(match).engine
    legal = {c.source_definition_id for c in engine.legal_candidates()}
    base = next(a for a in engine.action_catalog.values() if a.owner_id == OWNER and a.display_name == 'Jian (Straight Sword) attack')
    assert base.source_definition_id not in legal
    con = engine.action_catalog[base.source_definition_id + '#mandala_con']
    assert con.source_definition_id in legal
    commit(candidate(table, match, 'Jian (Straight Sword) attack (Constitution and weapon proficiency)', FOE))


def test_native_body_attainment_does_not_replace_actual_proficiency(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, cl=6, overall_cl=18)
    me = CombatService(ROOT, tmp_path)._load_session(match).engine.state.actors[OWNER]
    assert me.proficiency_bonus == 6
    assert me.resources[HANDS] == me.resource_maximums[HANDS] == 6
    assert not any('Eight-Limb' in action['label'] for action in table.state(match)['menu']['actions'])


def test_native_circle_intercepts_the_committed_roll_without_a_reroll(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, cl=14, items=())
    for _ in range(12):
        commit(table.state(match)['menu']['end_turn'])
        engine = combat._load_session(match).engine
        attack = next(a.source_definition_id + '|' + FOE for a in engine.action_catalog.values()
                      if a.owner_id == OWNER and a.display_name == C7.unarmed(engine, OWNER))
        start = len(engine.events)
        commit(candidate(table, match, 'Unarmed', OWNER), {'circle_of_uncounted_arms': 'intercept', 'circle_strike': attack})
        engine = CombatService(ROOT, tmp_path)._load_session(match).engine
        rewrites = [e for e in engine.events[start:] if e.event_type == 'D20_REWRITTEN' and e.actor_id == FOE and e.source_definition_id == PREFIX + 'circle_of_uncounted_arms']
        if rewrites:
            value = rewrites[0].payload
            assert value['operation'] == 'bonus'
            assert value['result']['natural_result'] == value['original']['natural_result']
            assert value['result']['total'] == value['original']['total'] - 5
            return
        commit(table.state(match)['menu']['end_turn'])
    pytest.fail('No successful native Intercepting Hand in twelve paid attempts')


def test_native_circle_silencing_expires_at_the_targets_next_turn(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, cl=14, items=())
    for _ in range(12):
        commit(table.state(match)['menu']['end_turn'])
        commit(candidate(table, match, 'Unarmed', OWNER), {'circle_of_uncounted_arms': 'silence'})
        engine = CombatService(ROOT, tmp_path)._load_session(match).engine
        denied = [c for c in engine.state.actors[FOE].conditions.values() if c.condition_id.endswith('reaction_denied')]
        if denied:
            assert denied[0].source_definition_id == PREFIX + 'circle_of_uncounted_arms'
            commit(table.state(match)['menu']['end_turn'])
            assert any(c.condition_id.endswith('reaction_denied') for c in combat._load_session(match).engine.state.actors[FOE].conditions.values())
            commit(table.state(match)['menu']['end_turn'])
            assert not any(c.condition_id.endswith('reaction_denied') for c in combat._load_session(match).engine.state.actors[FOE].conditions.values())
            return
        commit(table.state(match)['menu']['end_turn'])
    pytest.fail('No successful native Silencing Hand in twelve paid attempts')


def test_native_circle_seizes_before_the_willing_step_commits(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, cl=14, items=())
    for index in range(12):
        commit(table.state(match)['menu']['end_turn'])
        engine = combat._load_session(match).engine
        before = engine.state.actors[FOE].position
        destination = 7 if before.y == 6 else 6
        commit(move_candidate(table, match, 4, destination), {'circle_of_uncounted_arms': 'seize'})
        engine = CombatService(ROOT, tmp_path)._load_session(match).engine
        foe = engine.state.actors[FOE]
        if any(c.condition_id.endswith('grappled') and c.source_actor_id == OWNER for c in foe.conditions.values()):
            assert foe.position == before
            return
        commit(table.state(match)['menu']['end_turn'])
    pytest.fail('No successful native Seizing Hand in twelve paid attempts')


def test_native_circle_reaches_an_incarnation_hostile_ten_feet_away(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path)
    commit(candidate(table, match, 'Thousand-Hand Incarnation'))
    commit(move_candidate(table, match, 2, 6))
    commit(table.state(match)['menu']['end_turn'])
    commit(candidate(table, match, 'Dash'), {'circle_of_uncounted_arms': 'intercept'})
    engine = CombatService(ROOT, tmp_path)._load_session(match).engine
    me = engine.state.actors[OWNER]
    assert me.resources[HANDS] == 10
    assert any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == PREFIX + 'circle_of_uncounted_arms' for e in engine.events)
    # The Intercepting Hand's hit still deals damage; with no triggering roll
    # (Dash) there is no roll penalty to carry into a later attack.
    assert engine.state.actors[FOE].current_hp < 1000
    assert '_circle_roll_penalty' not in engine.state.actors[FOE].turn_flags


def move_candidate(table, match, x, y):
    return next(row['candidate_id'] for row in table.state(match)['menu']['moves']
                if row['destination']['x'] == x and row['destination']['y'] == y and not row['destination'].get('z'))


def profile_option(engine, weapon, target=FOE):
    return next(action.source_definition_id + '|' + target for action in engine.action_catalog.values()
                if action.owner_id == OWNER and '.weapon.' + weapon in action.source_definition_id
                and action.source_definition_id.endswith('#integrated_con'))


@pytest.mark.parametrize('effect', ['push', 'prone', 'no_reactions', 'temp_hp', 'move'])
def test_native_eight_limb_all_completion_effects(tmp_path, effect):
    combat, table, match, commit = table_fixture(tmp_path, body_attacks=True,
        items=(C7.JIAN, 'tianxia.mortal.weapon.chui'))
    for _ in range(12):
        engine = combat._load_session(match).engine
        unarmed = next(action.source_definition_id + '|' + FOE for action in engine.action_catalog.values()
                       if action.owner_id == OWNER and action.display_name == C7.unarmed(engine, OWNER))
        picks = {'weapon_wheel_gear': 'keep', 'weapon_wheel_attack': [profile_option(engine, 'jian'), profile_option(engine, 'chui'), unarmed, unarmed],
                 'eight_limb_completion': effect + '|' + (FOE if effect in ('push', 'prone', 'no_reactions') else ''),
                 'eight_limb_move': 'cell:0,6'}
        start = len(engine.events)
        commit(candidate(table, match, 'Weapon-Wheel Body: Attack with weapon choices'), picks)
        engine = CombatService(ROOT, tmp_path)._load_session(match).engine
        me, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
        if me.turn_flags.get('_round_hundred_forms', {}).get('completion_used'):
            assert len(me.turn_flags['_round_hundred_forms']['hit_forms']) >= 3
            if effect == 'push':
                assert (foe.position.x, foe.position.y) == (6, 6)
            elif effect == 'prone':
                assert any(c.condition_id.endswith('prone') for c in foe.conditions.values())
            elif effect == 'no_reactions':
                assert any(c.condition_id.endswith('reaction_denied') for c in foe.conditions.values())
                commit(table.state(match)['menu']['end_turn'])
                assert not any(c.condition_id.endswith('reaction_denied') for c in combat._load_session(match).engine.state.actors[FOE].conditions.values())
            elif effect == 'temp_hp':
                assert me.temporary_hp == 2 * me.proficiency_bonus
            else:
                assert (me.position.x, me.position.y) == (0, 6)
                assert me.movement_remaining_ft == 30
                oa = {row['feature_id'] for row in engine.typed_reaction_rows[FOE] if row.get('block') == 'opportunity'}
                assert not any(e.event_type == 'REACTION_RESOLVED' and e.actor_id == FOE and e.source_definition_id in oa for e in engine.events[start:])
            return
        commit(table.state(match)['menu']['end_turn'])
        commit(table.state(match)['menu']['end_turn'])
    pytest.fail('No three distinct native hit Forms in twelve ordinary Attack actions')


@pytest.mark.parametrize('effect', ['guard', 'move', 'strike', 'double'])
def test_native_mandala_completion_comes_from_four_actual_hand_debits(tmp_path, effect):
    combat, table, match, commit = table_fixture(tmp_path, body_attacks=True)
    commit(candidate(table, match, 'Thousand-Hand Incarnation'))
    engine = combat._load_session(match).engine
    blade = profile_option(engine, 'jian')
    unarmed = next(action.source_definition_id + '|' + FOE for action in engine.action_catalog.values()
                   if action.owner_id == OWNER and action.display_name == C7.unarmed(engine, OWNER))
    commit(candidate(table, match, 'Weapon-Wheel Body: Attack with weapon choices'),
           {'weapon_wheel_gear': 'keep', 'weapon_wheel_attack': [blade, blade, blade, blade],
            'four_hand_opening': 'ac', 'eight_limb_attack': unarmed})
    engine = combat._load_session(match).engine
    assert engine.state.actors[OWNER].resources[HANDS] == 10
    start = len(engine.events)
    commit(move_candidate(table, match, 2, 6), {'Opportunity Attack': 'USE', 'circle_of_uncounted_arms': 'deflect',
        'mandala_completion': effect, 'mandala_move': 'cell:0,6', 'mandala_strike': unarmed,
        'eight_limb_completion': 'pair:0'})
    engine = CombatService(ROOT, tmp_path)._load_session(match).engine
    me, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert me.resources[HANDS] == 8
    assert me.turn_flags['_round_hands_spent']['spent'] == 4
    assert me.turn_flags['_round_hands_spent']['mandala_used']
    if effect == 'guard':
        assert any(mod.value == 3 and mod.source_definition_id == PREFIX + 'thousand_hand_incarnation' for mod in me.modifiers.values())
    elif effect == 'move':
        assert (me.position.x, me.position.y) == (0, 6)
    elif effect == 'strike':
        assert any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER for e in engine.events[start:])
    else:
        assert (foe.position.x, foe.position.y) == (6, 6)
        assert any(c.condition_id.endswith('prone') for c in foe.conditions.values())


def test_native_four_hand_moves_before_selecting_the_attack_target(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, cl=3, foe_at=(5, 6))
    engine = combat._load_session(match).engine
    strike = next(a.source_definition_id + '|' + FOE for a in engine.action_catalog.values()
                  if a.owner_id == OWNER and a.display_name == C7.unarmed(engine, OWNER))
    commit(candidate(table, match, 'Attack: Battle Hand sequence'),
           {'four_hand_opening': 'move', 'four_hand_move': 'cell:4,6', 'weapon_wheel_attack': strike})
    engine = CombatService(ROOT, tmp_path)._load_session(match).engine
    me = engine.state.actors[OWNER]
    assert (me.position.x, me.position.y) == (4, 6)
    assert not me.action_available and me.resources[HANDS] == me.proficiency_bonus - 1
    assert any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER and FOE in e.target_ids for e in engine.events)


def test_native_four_hand_guard_is_legal_during_a_grapple_attack(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, cl=3, items=())
    commit(candidate(table, match, 'Grapple', FOE), {'four_hand_opening': 'ac'})
    me = CombatService(ROOT, tmp_path)._load_session(match).engine.state.actors[OWNER]
    assert me.resources[HANDS] == me.proficiency_bonus - 1
    assert any(mod.value == 1 and mod.target_field == 'armor_class' for mod in me.modifiers.values())


def test_native_eight_limb_can_grant_one_grapple_without_the_remaining_attacks(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, cl=10, body_attacks=True)
    # A one-handed Blade leaves the other actual hand available for Grapple.
    commit(candidate(table, match, 'Stow Gun'))
    engine = combat._load_session(match).engine
    grapple = next(action.source_definition_id + '|' + FOE for action in engine.action_catalog.values()
                   if action.owner_id == OWNER and (action.parameters.get('typed') or {}).get('unarmed_option') == 'grapple')
    # The readied Jian is Blade; the granted Grapple is Unarmed.
    commit(candidate(table, match, 'Jian (Straight Sword) attack (Constitution and weapon proficiency)', FOE), {'eight_limb_attack': grapple})
    engine = CombatService(ROOT, tmp_path)._load_session(match).engine
    rolls = [event for event in engine.events if event.event_type == 'ATTACK_ROLLED' and event.actor_id == OWNER]
    saves = [event for event in engine.events if event.event_type == 'SAVE_ROLLED' and event.actor_id == FOE and event.source_definition_id.endswith('.unarmed.grapple')]
    assert len(saves) == 1
    held = any(c.condition_id.endswith('grappled') and c.source_actor_id == OWNER for c in engine.state.actors[FOE].conditions.values())
    assert len(rolls) == 2  # One granted save never copies the remaining normal attacks.
    assert engine.state.actors[OWNER].resources[HANDS] == 2


def test_native_four_hand_miss_adds_pb_without_redrawing(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, cl=3)
    for _ in range(12):
        engine = combat._load_session(match).engine
        start = len(engine.events)
        commit(candidate(table, match, 'Jian (Straight Sword) attack', FOE), {'Four-Hand Sequence (+ Proficiency Bonus': 'USE'})
        engine = CombatService(ROOT, tmp_path)._load_session(match).engine
        rewrites = [e for e in engine.events[start:] if e.event_type == 'D20_REWRITTEN' and e.source_definition_id == PREFIX + 'four_hand_sequence']
        if rewrites:
            rewrite = rewrites[0].payload
            assert rewrite['operation'] == 'bonus'
            assert rewrite['original']['dice'] == rewrite['result']['dice']
            assert rewrite['result']['total'] - rewrite['original']['total'] == engine.state.actors[OWNER].proficiency_bonus
            assert engine.state.actors[OWNER].resources[HANDS] == 1
            return
        commit(table.state(match)['menu']['end_turn'])
        commit(table.state(match)['menu']['end_turn'])
    pytest.fail('No native missed Jian roll in twelve ordinary Attack actions')


def test_native_four_hand_damage_joins_the_primary_hit_packet(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, cl=3)
    for _ in range(12):
        engine = combat._load_session(match).engine
        name = C7.unarmed(engine, OWNER)
        action = next(a for a in engine.action_catalog.values() if a.owner_id == OWNER and a.display_name == name)
        base = action.parameters['typed']['weapon']['damage']['modifier']
        start = len(engine.events)
        commit(candidate(table, match, name, FOE), {'four_hand_sequence': 'damage'})
        engine = CombatService(ROOT, tmp_path)._load_session(match).engine
        if engine.state.actors[OWNER].resources[HANDS] == 1:
            rolls = [e for e in engine.events[start:] if e.event_type == 'DAMAGE_ROLLED' and e.source_definition_id == action.source_definition_id and e.actor_id == OWNER]
            assert rolls[0].payload['modifier'] == base + engine.state.actors[OWNER].proficiency_bonus
            assert not any(e.event_type == 'DAMAGE_ROLLED' and e.source_definition_id == PREFIX + 'four_hand_sequence' for e in engine.events[start:])
            return
        commit(table.state(match)['menu']['end_turn'])
        commit(table.state(match)['menu']['end_turn'])
    pytest.fail('No native unarmed hit in twelve ordinary Attack actions')


@pytest.mark.parametrize('trigger', ['Dash', 'Disengage', 'Grapple', 'Shove: Prone'])
def test_native_circle_nonattack_triggers_pay_and_continue(tmp_path, trigger):
    combat, table, match, commit = table_fixture(tmp_path, cl=14, items=())
    commit(table.state(match)['menu']['end_turn'])
    commit(candidate(table, match, trigger, OWNER if trigger in ('Grapple', 'Shove: Prone') else None),
           {'circle_of_uncounted_arms': 'intercept'})
    circle = [p for p in commit.prompts if 'circle_of_uncounted_arms' in str(p)]
    assert circle
    options = circle[0]['choice']['options']
    assert 'deflect' not in [o['id'] for o in options]
    engine = CombatService(ROOT, tmp_path)._load_session(match).engine
    me, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert me.resources[HANDS] == me.proficiency_bonus - 2
    assert not foe.action_available
    if trigger in ('Grapple', 'Shove: Prone'):
        assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER for e in engine.events)


def test_native_four_hand_two_items_changes_no_object_allowance(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, cl=3)
    from combat.ext.hundred_hands import equipment_pairs
    from combat.ext.hand_occupancy import weapon_grips
    engine = combat._load_session(match).engine
    me = engine.state.actors[OWNER]
    pair = next(iter(equipment_pairs(engine, me)))
    before = dict(weapon_grips(engine, me))
    flag = me.turn_flags.get('object_interaction_used')
    commit(candidate(table, match, 'Unarmed', FOE), {'four_hand_opening': pair})
    engine = CombatService(ROOT, tmp_path)._load_session(match).engine
    me = engine.state.actors[OWNER]
    assert len(before) == 2 and not weapon_grips(engine, me)
    assert me.turn_flags.get('object_interaction_used') == flag
    assert me.resources[HANDS] == 1


def test_native_incarnation_force_uses_three_confirmed_hits_and_one_unmultiplied_packet(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, body_attacks=True)
    commit(candidate(table, match, 'Thousand-Hand Incarnation'))
    for _ in range(12):
        engine = combat._load_session(match).engine
        blade = profile_option(engine, 'jian')
        start = len(engine.events)
        commit(candidate(table, match, 'Weapon-Wheel Body: Attack with weapon choices'),
               {'weapon_wheel_gear': 'keep', 'weapon_wheel_attack': [blade] * 4, 'incarnation_force': 'damage'})
        engine = CombatService(ROOT, tmp_path)._load_session(match).engine
        extra = [e for e in engine.events[start:] if e.event_type == 'DAMAGE_ROLLED'
                 and e.source_definition_id == PREFIX + 'thousand_hand_incarnation']
        if extra:
            assert len(extra) == 1
            assert len(extra[0].payload['dice']) == 5 and extra[0].payload['expression'].startswith('5d8')
            assert not extra[0].payload.get('critical', False)
            record = engine.state.actors[OWNER].turn_flags['_round_hundred_forms']
            assert record['struck'][FOE] >= 3 and record['force_used']
            return
        commit(table.state(match)['menu']['end_turn'])
        commit(table.state(match)['menu']['end_turn'])
    pytest.fail('No three confirmed same-creature hits in twelve ordinary native Attack actions')


def test_native_weapon_wheel_does_not_prime_while_only_unarmed_is_ready(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, cl=6, body_attacks=True)
    commit(candidate(table, match, 'Stow Gun'))
    commit(candidate(table, match, 'Stow Jian'))
    engine = combat._load_session(match).engine
    unarmed = next(a.source_definition_id + '|' + FOE for a in engine.action_catalog.values()
                   if a.owner_id == OWNER and a.display_name == C7.unarmed(engine, OWNER))
    draw = next(a.source_definition_id for a in engine.action_catalog.values()
                if a.owner_id == OWNER and a.display_name.startswith('Draw Jian'))
    blade = next(a.source_definition_id + '|' + FOE for a in engine.action_catalog.values()
                 if a.owner_id == OWNER and a.source_definition_id.endswith('.weapon.jian#mandala_con'))
    start = len(engine.events)
    commit(candidate(table, match, 'Weapon-Wheel Body: Attack with weapon choices'),
           {'weapon_wheel_gear': ['keep', draw, 'keep'], 'weapon_wheel_attack': [unarmed, blade]})
    engine = CombatService(ROOT, tmp_path)._load_session(match).engine
    rolls = [e for e in engine.events[start:] if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]
    assert len(rolls) == 2
    assert rolls[-1].payload['mode'] == 'NORMAL'
    assert not engine.state.actors[OWNER].turn_flags['_round_hundred_forms'].get('wheel_used')


@pytest.mark.parametrize('different', [False, True])
def test_native_eight_limb_decline_reopens_only_on_a_later_different_form_hit(tmp_path, different):
    combat, table, match, commit = table_fixture(tmp_path, body_attacks=True,
        items=(C7.JIAN, 'tianxia.mortal.weapon.chui'))
    for _ in range(12):
        engine = combat._load_session(match).engine
        unarmed = next(a.source_definition_id + '|' + FOE for a in engine.action_catalog.values()
                       if a.owner_id == OWNER and a.display_name == C7.unarmed(engine, OWNER))
        blade, hafted = profile_option(engine, 'jian'), profile_option(engine, 'chui')
        commit(candidate(table, match, 'Weapon-Wheel Body: Attack with weapon choices'),
               {'weapon_wheel_gear': 'keep', 'weapon_wheel_attack': [blade, hafted, unarmed, blade if different else unarmed],
                'eight_limb_completion': [None, 'temp_hp|']})
        engine = CombatService(ROOT, tmp_path)._load_session(match).engine
        me = engine.state.actors[OWNER]
        if me.turn_flags['_round_hundred_forms'].get('struck', {}).get(FOE) == 4:
            prompts = [p for p in commit.prompts if p.get('context', {}).get('reaction_source_id') == 'choice:needle.eight_limb_completion']
            assert len(prompts) == (2 if different else 1)
            assert me.temporary_hp == (2 * me.proficiency_bonus if different else 0)
            return
        commit(table.state(match)['menu']['end_turn'])
        commit(table.state(match)['menu']['end_turn'])
    pytest.fail('No four native hits for the completion-window boundary in twelve Attack actions')


def test_native_weapon_wheel_uses_body_constitution_in_the_cultivation_profile(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, cl=6, overall_cl=18,
        global_key='WIS', ability_mods={'WIS': 5, 'CON': 2})
    engine = combat._load_session(match).engine
    action = next(a for a in engine.action_catalog.values() if a.owner_id == OWNER
                  and a.source_definition_id.endswith('.weapon.jian#integrated_con'))
    start = len(engine.events)
    commit(candidate(table, match, action.display_name, FOE))
    engine = CombatService(ROOT, tmp_path)._load_session(match).engine
    roll = next(e for e in engine.events[start:] if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER)
    assert roll.payload['modifier'] == 97  # Preserve the declared bonus; replace WIS +5 with Body CON +2.
    assert action.parameters['typed']['weapon']['ability'] == 'CON'
    assert action.parameters['typed']['numbers']['key_mod'] == 2


@pytest.mark.parametrize('pool', ['extra', 'ordinary'])
def test_native_circle_can_choose_the_reaction_pool_without_losing_the_other(tmp_path, pool):
    # In-combat Thousand-Hand activation; the choice pool ask happens when the
    # owner pays a Circle on another creature's turn with both payments legal.
    combat, table, match, commit = table_fixture(tmp_path, cl=18)
    commit(candidate(table, match, 'Thousand-Hand Incarnation'))
    commit(table.state(match)['menu']['end_turn'])
    commit(candidate(table, match, 'Unarmed', OWNER), {'circle_of_uncounted_arms': 'deflect',
        'reaction_pool': 'grant:0' if pool == 'extra' else 'ordinary'})
    engine = CombatService(ROOT, tmp_path)._load_session(match).engine
    me = engine.state.actors[OWNER]
    assert me.reaction_available == (pool == 'extra')
    from combat.ext.reaction_economy import grant_unused
    grant = next(r for r in engine.typed_passive_rows[OWNER] if r.get('block') == 'reaction_economy'
                 and r.get('feature_id') == PREFIX + 'thousand_hand_incarnation' and r.get('grant') == 'extra')
    assert grant_unused(engine, me, grant) == (pool == 'ordinary')
    assert me.resources[HANDS] == 2 * me.proficiency_bonus - 2


def test_native_circle_ask_remains_reachable_during_a_local_auto_turn(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, cl=14, items=())
    commit(table.state(match)['menu']['end_turn'])
    combat.set_controller_mode(match, actor_id=FOE, controller_mode='LOCAL_AUTO')
    saw_circle = False
    for _ in range(8):
        answers = []
        for _ in range(30):
            result = table.auto_step(match, table.state(match)['last_sequence'], answers)
            if result['status'] == 'COMMITTED':
                assert_reload_verify_replay(combat, match, tmp_path)
                break
            assert result['status'] == 'REACTION_REQUIRED', result
            prompt = result['reaction']
            answer = {**prompt['context'], 'selection': 'DECLINE'}
            if 'circle_of_uncounted_arms' in str(prompt):
                assert prompt['context']['reactor_id'] == OWNER
                options = [o['id'] for o in prompt['choice']['options']]
                assert 'intercept' in options and 'seize' in options and 'silence' in options
                selected = 'deflect' if 'deflect' in options else 'seize'
                answer.update(selection='USE', option_ids=[selected])
                saw_circle = True
            answers.append(answer)
        else:
            pytest.fail('Local Auto choice did not settle')
        if saw_circle:
            me = CombatService(ROOT, tmp_path)._load_session(match).engine.state.actors[OWNER]
            assert me.resources[HANDS] == me.proficiency_bonus - 2
            assert not me.reaction_available
            return
        if table.state(match)['menu']['actor_id'] == OWNER:
            commit(table.state(match)['menu']['end_turn'])
    pytest.fail('Local Auto did not produce a listed Circle trigger')
