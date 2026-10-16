"""Hundred-Hand native table regressions and exact source acquisition guards.

No model or GUI transport. Acquisition uses the existing persisted non-Sphere
service; fights use portable sheets and real table intents, journal verification,
cold reload and mechanical replay. Helper C7 engine probes cover roll boundaries.
"""
from pathlib import Path
import json
import zipfile
import pytest

from app.core import Database, Settings, FoundryError
from non_sphere_authority import NonSphereAuthorityService
from tests.ns1r_evidence_helpers import install_authority_test_pack, commit_authority_event, ap_award, access_evidence
from tests.test_ns1rr1_authority_enforcement import insert_project
from tests import test_riders_c7 as C7
from tests.h48_table_support import assert_reload_verify_replay, candidate
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]
BODY = 'tianxia.path.body_refining'
PARENT = 'tianxia.subpath.body.hundred_hand_battle_mandala'
PREFIX = PARENT + '.feature.'
HANDS = 'resource:named.battle_hand'
OWNER, FOE, THIRD = [FACTORY_ACTOR_PREFIX + 'mandala-' + key for key in ('owner', 'foe', 'third')]


def acquisition(tmp_path, cl, overall_cl=None):
    target = overall_cl or cl
    authority_root = ROOT / 'non_sphere_authority' / 'authority'
    identity = json.loads((authority_root / 'NS1R_AUTHORITY_IDENTITIES.json').read_text())
    for name in identity['files']:
        if not (authority_root / name).is_file():
            raise FileNotFoundError(f'Required sealed acquisition authority: {name}')
    settings = Settings.from_env(ROOT, tmp_path / 'acquisition')
    settings.ensure_dirs()
    db = Database(settings)
    db.migrate()
    service = NonSphereAuthorityService(db)
    install_authority_test_pack(db, service)
    insert_project(db, 'mandala-owner', target)
    service.initialize_for_project('mandala-owner', target_cl=target, path_ids=[BODY], method_id='METHOD-002', access_source_records=access_evidence(db, service, 'mandala-owner', 'METHOD-002'))
    service.allocate_advancement('mandala-owner', {BODY: 2}, evidence_id=ap_award(db, service, 'mandala-owner', 'METHOD-002', target, 2), idempotency_key='mandala:cl3')
    with pytest.raises(FoundryError):
        service.select_subpath('mandala-owner', BODY, PARENT)
    access = commit_authority_event(db, service, 'mandala-owner', 'subpath_access', {'selection_id': PARENT})
    service.select_subpath('mandala-owner', BODY, PARENT, access_source_records=[access])
    if cl > 3:
        service.allocate_advancement('mandala-owner', {BODY: cl - 3}, evidence_id=ap_award(db, service, 'mandala-owner', 'METHOD-002', target, cl - 3), idempotency_key='mandala:advance')
    # Resolve the actual persisted selection and attainment; feature definitions
    # remain source authority, never a hand-authored feature ownership receipt.
    persisted = NonSphereAuthorityService(db).get_state('mandala-owner')
    path = next(row for row in persisted['paths'] if row['path_id'] == BODY)
    assert path['subpath_or_tradition_id'] == PARENT
    assert path['attainment'] == cl
    source = service.subpaths[path['subpath_or_tradition_id']]
    ids = [row['canonical_id'] for row in source['feature_progression'] if row['granted_at_cl'] <= path['attainment']]
    return ids


def table_fixture(tmp_path, cl=18, seed='MANDALA-NATIVE', third=False, items=(C7.JIAN, C7.GUN), align_owner=True, overall_cl=None, body_attacks=False, prepare_journey=None, foe_at=(4, 6), give_items=(), maximum_rounds=15, acquire_owner=True):
    ids = acquisition(tmp_path, cl, overall_cl)
    actual_cl = overall_cl or cl
    base = []
    if body_attacks:
        index = json.loads((ROOT / 'non_sphere_authority/authority/body_refining.path_index.p2a.json').read_text())
        base = [row['canonical_id'] for row in index['features'] if row['feature_kind'] == 'attack_chassis' and row.get('minimum_cl', 99) <= cl]
    sheets = [C7.sheet(base, cl=actual_cl, items=items), C7.sheet([], cl=actual_cl)]
    ids_in_fight = [OWNER, FOE] + ([THIRD] if third else [])
    if third:
        sheets.append(C7.sheet([], cl=actual_cl))
    for aid, document in zip(ids_in_fight, sheets):
        document['identity']['display_name'] = 'Mandala' if aid == OWNER else 'Opponent'
        document['path_and_subpath']['path_record_ids'] = [BODY]
        document['path_and_subpath']['paths'] = [{'path_id': BODY, 'attained_cl': cl, 'effective_cl': cl}]
        document['ability_scores_and_statistics']['hit_points']['maximum'] = 1000
        document['ability_scores_and_statistics']['technique_attack_bonus'] = 100
        folder = tmp_path / 'portable_characters' / aid.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    from factory_authoring.owner_items import OwnerItemStore
    from app.models import OwnerItemSpecRequest
    for spec in give_items:
        OwnerItemStore(tmp_path / 'owner_items').give('mandala-owner', OwnerItemSpecRequest.model_validate(spec).model_dump())
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
    if acquire_owner:
        with pytest.raises(ValueError, match='Restricted Scripture access'):
            combat.journey_acquire_source(jid, state['revision'], OWNER, PARENT, {'access_scope': 'scripture'})
        state = combat.journey_world_fact(jid, state['revision'], {'source': PARENT, 'subject': OWNER,
            'kind': 'scripture_access', 'scope': 'scripture', 'value': {'scripture': PARENT,
                'instruction': 'Controlled instruction granted by the native table owner',
                'source_rule': 'Body R8 CL3: choose one Subpath for which you have legal Restricted Scripture access'},
            'expires_at': 1000, 'readers': []})
        state = combat.journey_acquire_source(jid, state['revision'], OWNER, PARENT, {'access_scope': 'scripture'})
        assert CombatService(ROOT, tmp_path).journey_state(jid) == state
        assert state['events'][-1]['features'] == ids
    if prepare_journey:
        state = prepare_journey(combat, jid, state)
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


@pytest.mark.parametrize('cl,count', [(3, 1), (6, 2), (10, 3), (14, 4), (18, 5)])
def test_native_restricted_acquisition_and_five_thresholds(tmp_path, cl, count):
    assert len(acquisition(tmp_path, cl)) == count


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
    assert waive(engine, me, row, False) is None  # granted at the next native owner-turn boundary
    C7.turn(engine, C7.ME)
    me.reaction_available = False
    assert waive(engine, me, row, True) == 'free', ('initial', me.turns_started, me.turn_flags, engine.typed_passive_rows[C7.ME])
    engine.state.round_number += 1
    assert waive(engine, me, row, False) is None
    C7.turn(engine, C7.ME)
    me.reaction_available = False
    assert waive(engine, me, row, False) == 'free', ('owner_refresh', me.turns_started, me.turn_flags)


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


def test_native_outside_incarnation_expiry_scene_and_paid_continuation(tmp_path):
    def prepare(service, jid, state):
        state = service.journey_act(jid, state['revision'], OWNER, 'mandala_incarnation')
        assert state['actors'][OWNER]['resources'][C7.STAMINA] == 53
        assert state['actors'][OWNER]['resources'][HANDS] == 12
        state = service.journey_act(jid, state['revision'], OWNER, 'wait', {'seconds': 59})
        assert service.journey_menu(jid, OWNER)['properties']['mandala_incarnation_active'] == 1
        state = service.journey_act(jid, state['revision'], OWNER, 'wait', {'seconds': 1})
        assert service.journey_menu(jid, OWNER)['properties']['mandala_incarnation_active'] == 0
        assert state['actors'][OWNER]['resources'][HANDS] == 6
        with pytest.raises(ValueError, match='unused scene'):
            service.journey_act(jid, state['revision'], OWNER, 'mandala_incarnation')
        state = service.journey_end_scene(jid, state['revision'], 'The table owner ends the completed sparring scene.')
        state = service.journey_act(jid, state['revision'], OWNER, 'mandala_incarnation')
        assert state['actors'][OWNER]['resources'][C7.STAMINA] == 46
        state = service.journey_act(jid, state['revision'], OWNER, 'wait', {'seconds': 30})
        assert CombatService(ROOT, tmp_path).journey_state(jid) == state
        return state
    combat, table, match, commit = table_fixture(tmp_path, prepare_journey=prepare)
    me = CombatService(ROOT, tmp_path)._load_session(match).engine.state.actors[OWNER]
    assert me.resources[C7.STAMINA] == 46
    assert me.resource_maximums[HANDS] == 12
    assert any(c.condition_id.endswith('state.thousand_hand_incarnation') for c in me.conditions.values())
    commit(table.state(match)['menu']['end_turn'])


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


def test_native_recorded_weapon_form_survives_inventory_and_new_journey(tmp_path):
    from factory_authoring.owner_items import OwnerItemStore, weapon_choices
    from combat.acquisition_inventory import read
    from combat.ext.hundred_hands import form_for
    bow = 'tianxia.mortal.weapon.gong_jian'
    spec = {'kind':'weapon','chassis_id':bow,'grade':'Spiritual',
        'material_id':weapon_choices(bow,'Spiritual',None,[])['material_id'],
        'runtime_profile':{'source_rule':'A real bow delivered by the owner; its ambiguous Form is chosen before use.',
            'authority':'native item owner','source_cl':6,'kind':'weapon','weight_lb':2,'cube_ft':5,
            'flags':{'prerequisites_met':1},'facts':{}}}
    combat, table, match, commit = table_fixture(tmp_path,cl=6,items=(),give_items=[spec],maximum_rounds=1)
    commit(candidate(table,match,'Record Weapon Form:'),{'weapon_form':'Flexible'})
    engine = CombatService(ROOT,tmp_path)._load_session(match).engine
    item = OwnerItemStore(tmp_path / 'owner_items').items('mandala-owner')[0]
    uid = item['item_uid']
    inventory = read(engine.state.actors[OWNER])
    assert inventory[uid]['profile']['facts']['weapon_form'] == 'Flexible'
    for _ in range(3):
        if combat._load_session(match).engine.state.terminal_result is not None:break
        commit(table.state(match)['menu']['end_turn'])
    state = next(iter(json.loads((tmp_path/'Combat/Journeys/State.json').read_text())['sessions'].values()))
    state = CombatService(ROOT,tmp_path).journey_resume(state['journey_id'],state['revision'])
    assert state['actors'][OWNER]['source_states']['system:recorded_items']['inventory'][uid]['profile']['facts']['weapon_form'] == 'Flexible'
    combat.journey_act(state['journey_id'],state['revision'],OWNER,'finish')
    state = combat.create_journey(project_ids=['mandala-owner','mandala-foe'],arena_id='battlefield:map.mandala-native',
        positions={OWNER:{'x':3,'y':6},FOE:{'x':4,'y':6}},base_paces={OWNER:100,FOE:100})
    assert state['actors'][OWNER]['bundle']['acquisition_inventory'][uid]['profile']['facts']['weapon_form'] == 'Flexible'
    match = combat.journey_start_combat(state['journey_id'],state['revision'],{OWNER:'team:a',FOE:'team:b'},maximum_rounds=1)['match_id']
    engine = CombatService(ROOT,tmp_path)._load_session(match).engine
    weapon = engine.action_catalog[read(engine.state.actors[OWNER])[uid]['weapon_actions'][0]]
    assert form_for(engine,engine.state.actors[OWNER],weapon) == 'Flexible'
    assert_reload_verify_replay(combat,match,tmp_path)

    # A real replacement gift may reuse the given.0/action slot, but it is a
    # different physical UID and must never inherit the previous item's Form.
    for _ in range(3):
        if combat._load_session(match).engine.state.terminal_result is not None:
            break
        menu = table.state(match)['menu']
        result = table.act(match, menu['end_turn'], menu['decision_id'], menu['state_version'], 0, [])
        assert result['status'] == 'COMMITTED'
        assert_reload_verify_replay(combat, match, tmp_path)
    state = CombatService(ROOT,tmp_path).journey_state(state['journey_id'])
    state = combat.journey_resume(state['journey_id'],state['revision'])
    combat.journey_act(state['journey_id'],state['revision'],OWNER,'finish')
    store = OwnerItemStore(tmp_path/'owner_items')
    store.remove('mandala-owner', uid)
    replacement = store.give('mandala-owner', spec)
    assert replacement['item_uid'] != uid
    state = combat.create_journey(project_ids=['mandala-owner','mandala-foe'],arena_id='battlefield:map.mandala-native',
        positions={OWNER:{'x':3,'y':6},FOE:{'x':4,'y':6}},base_paces={OWNER:100,FOE:100})
    match = combat.journey_start_combat(state['journey_id'],state['revision'],{OWNER:'team:a',FOE:'team:b'})['match_id']
    for _ in range(2):
        menu = table.state(match)['menu']
        if menu['actor_id'] == OWNER:
            break
        assert table.act(match,menu['end_turn'],menu['decision_id'],menu['state_version'],0,[])['status'] == 'COMMITTED'
    engine = CombatService(ROOT,tmp_path)._load_session(match).engine
    entry = read(engine.state.actors[OWNER])[replacement['item_uid']]
    weapon = engine.action_catalog[entry['weapon_actions'][0]]
    assert form_for(engine,engine.state.actors[OWNER],weapon) is None
    cid = candidate(table, match, 'Record Weapon Form:')
    menu = table.state(match)['menu']
    result = table.act(match,cid,menu['decision_id'],menu['state_version'],0,[])
    assert result['status'] == 'REACTION_REQUIRED'
    answer = {**result['reaction']['context'], 'selection':'USE', 'option_ids':['Hafted']}
    assert table.act(match,cid,menu['decision_id'],menu['state_version'],0,[answer])['status'] == 'COMMITTED'
    engine = CombatService(ROOT,tmp_path)._load_session(match).engine
    assert read(engine.state.actors[OWNER])[replacement['item_uid']]['profile']['facts']['weapon_form'] == 'Hafted'
    assert_reload_verify_replay(combat,match,tmp_path)


def test_native_item_profile_rejects_invalid_input_before_delivery(tmp_path):
    from factory_authoring.owner_items import OwnerItemStore, weapon_choices
    store = OwnerItemStore(tmp_path/'owner_items')
    with pytest.raises(ValueError,match='Source Rule'):
        store.give('mandala-owner',{'kind':'weapon','chassis_id':C7.JIAN,'grade':'Spiritual',
            'material_id':weapon_choices(C7.JIAN,'Spiritual',None,[])['material_id'],
            'runtime_profile':{'source_cl':3,'kind':'weapon','weight_lb':1,'cube_ft':1}})
    assert store.items('mandala-owner') == []


def test_native_four_hand_miss_adds_pb_without_redrawing(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path,cl=3)
    for _ in range(12):
        engine = combat._load_session(match).engine
        start = len(engine.events)
        commit(candidate(table,match,'Jian (Straight Sword) attack',FOE),{'Four-Hand Sequence (+ Proficiency Bonus':'USE'})
        engine = CombatService(ROOT,tmp_path)._load_session(match).engine
        rewrites = [e for e in engine.events[start:] if e.event_type == 'D20_REWRITTEN' and e.source_definition_id == PREFIX+'four_hand_sequence']
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
    combat, table, match, commit = table_fixture(tmp_path,cl=3)
    for _ in range(12):
        engine = combat._load_session(match).engine
        name = C7.unarmed(engine,OWNER)
        action = next(a for a in engine.action_catalog.values() if a.owner_id == OWNER and a.display_name == name)
        base = action.parameters['typed']['weapon']['damage']['modifier']
        start = len(engine.events)
        commit(candidate(table,match,name,FOE),{'four_hand_sequence':'damage'})
        engine = CombatService(ROOT,tmp_path)._load_session(match).engine
        if engine.state.actors[OWNER].resources[HANDS] == 1:
            rolls = [e for e in engine.events[start:] if e.event_type == 'DAMAGE_ROLLED' and e.source_definition_id == action.source_definition_id and e.actor_id == OWNER]
            assert rolls[0].payload['modifier'] == base + engine.state.actors[OWNER].proficiency_bonus
            assert not any(e.event_type == 'DAMAGE_ROLLED' and e.source_definition_id == PREFIX+'four_hand_sequence' for e in engine.events[start:])
            return
        commit(table.state(match)['menu']['end_turn'])
        commit(table.state(match)['menu']['end_turn'])
    pytest.fail('No native unarmed hit in twelve ordinary Attack actions')


def test_four_hand_critical_packet_adds_pb_only_once():
    engine, me, foe = C7._mandala(['four_hand_sequence'],picks={'four_hand_opening':None,'four_hand_sequence':['damage']})
    action = next(a for a in engine.action_catalog.values() if a.owner_id == me.entity_id and a.display_name == C7.unarmed(engine))
    base = action.parameters['typed']['weapon']['damage']['modifier']
    C7._force_next_d20(engine,20)
    events = C7.use(engine,C7.unarmed(engine),target=foe.entity_id)
    damage = next(e.payload for e in events if e.event_type == 'DAMAGE_ROLLED' and e.source_definition_id == action.source_definition_id)
    assert damage['critical'] and damage['modifier'] == base + me.proficiency_bonus


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


@pytest.mark.parametrize('consumer,level,pb', [('attack', 6, 3), ('grapple', 14, 5)])
def test_native_sourced_realm_ruling_clamps_pb_and_dormants_paid_incarnation(tmp_path, consumer, level, pb):
    def prepare(service, jid, state):
        state = service.journey_act(jid, state['revision'], OWNER, 'mandala_incarnation')
        reason = 'The table owner applies the recorded Realm suppression Source Rule for this scene.'
        value = {'path_id': BODY, 'effective_cl': level, 'proficiency_bonus': pb, 'reason': reason, 'scene_id': state.get('scene_id', state['journey_id'])}
        state = service.journey_world_fact(jid, state['revision'], {'source': 'system:path_authority',
            'subject': OWNER, 'kind': 'effective_cl', 'scope': BODY, 'value': value, 'expires_at': 1000, 'readers': []})
        state = service.journey_act(jid, state['revision'], OWNER, 'path_effective_cl',
            {key: value[key] for key in ('path_id', 'effective_cl', 'proficiency_bonus', 'reason')} | {'authority': 'GM'})
        assert state['actors'][OWNER]['resources'][HANDS] == pb
        return state
    combat, table, match, commit = table_fixture(tmp_path, prepare_journey=prepare)
    from combat.ext.hundred_hands import _thousand, body_level, _pb
    engine = combat._load_session(match).engine
    me = engine.state.actors[OWNER]
    assert body_level(engine, me) == level and _pb(engine, me) == pb
    assert not _thousand(engine, me)
    held = next(c for c in me.conditions.values() if c.condition_id.endswith('state.thousand_hand_incarnation'))
    assert held.data['numbers']['cl'] == 18
    assert me.resources[C7.STAMINA] == 53
    assert me.resources[HANDS] == me.resource_maximums[HANDS] == pb
    assert me.proficiency_bonus == 6
    assert not any('Thousand-Hand Incarnation' in a['label'] for a in table.state(match)['menu']['actions'])
    start = len(engine.events)
    if consumer == 'attack':
        commit(candidate(table, match, 'Jian (Straight Sword) attack (Constitution and weapon proficiency)', FOE), {'four_hand_opening': 'ac'})
        engine = CombatService(ROOT, tmp_path)._load_session(match).engine
        assert engine.state.actors[OWNER].resources[HANDS] == pb - 1
        rolls = [e for e in engine.events[start:] if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]
        assert rolls and rolls[0].payload['modifier'] == 2 + pb
    else:
        commit(candidate(table, match, 'Stow Jian'))
        commit(candidate(table, match, 'Stow Gun'))
        commit(table.state(match)['menu']['end_turn'])
        commit(candidate(table, match, 'Dash'), {'circle_of_uncounted_arms': 'seize'})
        engine = CombatService(ROOT, tmp_path)._load_session(match).engine
        saves = [e for e in engine.events[start:] if e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE]
        assert len(saves) == 1 and saves[0].payload['dc'] == 8 + 2 + pb
        assert engine.state.actors[OWNER].resources[HANDS] == pb - 2


@pytest.mark.parametrize('declared_pb', [-1, 7, True, '3'])
def test_native_realm_pb_rejects_invalid_rulings_without_mutation(tmp_path, declared_pb):
    def prepare(service, jid, state):
        before = CombatService(ROOT, tmp_path).journey_state(jid)
        with pytest.raises(ValueError):
            service.journey_act(jid, state['revision'], OWNER, 'path_effective_cl',
                {'path_id': BODY, 'effective_cl': 6, 'proficiency_bonus': declared_pb,
                 'authority': 'GM', 'reason': 'A caller claim is not table-owner authority.'})
        assert CombatService(ROOT, tmp_path).journey_state(jid) == before
        return state
    combat, table, match, commit = table_fixture(tmp_path, prepare_journey=prepare)
    commit(table.state(match)['menu']['end_turn'])



def test_native_unacquired_source_is_inert_across_commit_and_reload(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, acquire_owner=False)
    engine = combat._load_session(match).engine
    assert HANDS not in engine.state.actors[OWNER].resources
    assert not any('Weapon-Wheel' in a['label'] or 'Incarnation' in a['label'] for a in table.state(match)['menu']['actions'])
    commit(candidate(table, match, 'Unarmed', FOE))
    assert not any('four_hand' in str(p) or 'eight_limb' in str(p) or 'mandala' in str(p.get('reaction_source_id', '')) for p in commit.prompts)
    commit(table.state(match)['menu']['end_turn'])
    commit(candidate(table, match, 'Unarmed', OWNER))
    assert not any('circle_of_uncounted_arms' in str(p) for p in commit.prompts)
    assert HANDS not in CombatService(ROOT, tmp_path)._load_session(match).engine.state.actors[OWNER].resources


def test_native_incarnation_force_uses_three_confirmed_hits_and_one_unmultiplied_packet(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, body_attacks=True)
    commit(candidate(table, match, 'Thousand-Hand Incarnation'))
    for _ in range(12):
        engine = combat._load_session(match).engine
        blade = profile_option(engine, 'jian')
        start = len(engine.events)
        commit(candidate(table, match, 'Weapon-Wheel Body: Attack with weapon choices'),
               {'weapon_wheel_gear': 'keep', 'weapon_wheel_attack': [blade]*4, 'incarnation_force': 'damage'})
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



@pytest.mark.parametrize('continuation', ['wait', 'combat'])
def test_native_four_guard_survives_encounter_exit_until_its_actual_clock(tmp_path, continuation):
    combat, table, match, commit = table_fixture(tmp_path, cl=3, maximum_rounds=1)
    commit(candidate(table, match, 'Jian (Straight Sword) attack', FOE), {'four_hand_opening': 'ac'})
    for _ in range(3):
        if combat._load_session(match).engine.state.terminal_result is not None:
            break
        commit(table.state(match)['menu']['end_turn'])
    state = next(iter(json.loads((tmp_path/'Combat/Journeys/State.json').read_text())['sessions'].values()))
    state = CombatService(ROOT, tmp_path).journey_resume(state['journey_id'], state['revision'])
    records = state['actors'][OWNER]['source_states'][PARENT]['timed_results']
    previous = combat._load_session(match).engine
    from fractions import Fraction
    # The draw ends at the next round boundary. With two initiative slots,
    # the first creature is due now and the second is due three seconds later.
    expected = Fraction(0 if previous.state.initiative_order[0] == OWNER else 3)
    assert len(records) == int(bool(expected))
    if expected:
        row = next(iter(records.values()))
        left = Fraction(row['remaining_num'], row['remaining_den'])
        assert left == expected
        assert json.loads(row['model'])['value'] == 1
    if continuation == 'wait':
        state = combat.journey_act(state['journey_id'], state['revision'], OWNER, 'wait', {'seconds': 6})
        assert not state['actors'][OWNER]['source_states'][PARENT]['timed_results']
        assert CombatService(ROOT, tmp_path).journey_state(state['journey_id']) == state
    else:
        next_match = combat.journey_start_combat(state['journey_id'], state['revision'], {OWNER:'team:a', FOE:'team:b'})['match_id']
        engine = CombatService(ROOT, tmp_path)._load_session(next_match).engine
        me = engine.state.actors[OWNER]
        guards = [m for m in me.modifiers.values() if m.source_definition_id == PREFIX+'four_hand_sequence']
        assert bool(guards) == bool(expected and engine.state.current_actor_id != OWNER)
        assert_reload_verify_replay(combat, next_match, tmp_path)



def test_native_acquired_continuation_rejects_a_competing_body_progression(tmp_path):
    combat, table, match, commit = table_fixture(tmp_path, cl=3, maximum_rounds=1)
    for _ in range(3):
        if combat._load_session(match).engine.state.terminal_result is not None:
            break
        commit(table.state(match)['menu']['end_turn'])
    state = next(iter(json.loads((tmp_path/'Combat/Journeys/State.json').read_text())['sessions'].values()))
    state = combat.journey_resume(state['journey_id'], state['revision'])
    combat.journey_act(state['journey_id'], state['revision'], OWNER, 'finish')
    path = tmp_path/'portable_characters/mandala-owner/current.zip'
    with zipfile.ZipFile(path) as archive:
        document = json.loads(archive.read('Tianxia_Owner_Character_Sheet_v1.json'))
    document['path_and_subpath']['subpath_record_id'] = 'tianxia.subpath.body.sumo'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    with pytest.raises(ValueError, match='two progressions'):
        CombatService(ROOT, tmp_path).create_journey(project_ids=['mandala-owner','mandala-foe'],
            arena_id='battlefield:map.mandala-native',positions={OWNER:{'x':3,'y':6},FOE:{'x':4,'y':6}},
            base_paces={OWNER:100,FOE:100})



def test_native_mandala_form_tag_does_not_grant_an_unarmed_strike(tmp_path):
    from factory_authoring.owner_items import weapon_choices
    bow = 'tianxia.mortal.weapon.gong_jian'
    spec = {'kind':'weapon','chassis_id':bow,'grade':'Spiritual',
        'material_id':weapon_choices(bow,'Spiritual',None,[])['material_id'],
        'runtime_profile':{'source_rule':'Owner-recorded custom Form tag for sequencing only; the bow retains its ordinary ranged weapon attack.',
            'authority':'native item owner','source_cl':18,'kind':'weapon','weight_lb':2,'cube_ft':5,
            'flags':{'prerequisites_met':1},'facts':{'weapon_form':'Unarmed'}}}
    combat, table, match, commit = table_fixture(tmp_path, items=(C7.JIAN,), body_attacks=True, give_items=[spec])
    commit(candidate(table, match, 'Thousand-Hand Incarnation'))
    engine = combat._load_session(match).engine
    blade = profile_option(engine, 'jian')
    unarmed = next(a.source_definition_id+'|'+FOE for a in engine.action_catalog.values()
                   if a.owner_id == OWNER and a.display_name == C7.unarmed(engine, OWNER))
    commit(candidate(table, match, 'Weapon-Wheel Body: Attack with weapon choices'),
           {'weapon_wheel_gear':'keep','weapon_wheel_attack':[blade]*4,
            'four_hand_opening':'ac','eight_limb_attack':unarmed})
    commit(candidate(table, match, 'Stow Jian'))
    commit(move_candidate(table, match, 2, 6), {'Opportunity Attack':'USE','circle_of_uncounted_arms':'deflect',
           'mandala_completion':'strike','mandala_strike':unarmed})
    prompts = [p for p in commit.prompts if p.get('context',{}).get('reaction_source_id') == 'choice:needle.mandala_strike']
    assert prompts
    assert not any('.weapon.gong_jian' in option['id'] for option in prompts[0]['choice']['options'])
    engine = CombatService(ROOT, tmp_path)._load_session(match).engine
    assert engine.state.actors[OWNER].turn_flags['_round_hands_spent']['mandala_used']



@pytest.mark.parametrize('cl', [3, 18])
def test_native_acquisition_and_outside_turn_cycle_use_the_real_hand_capacity(tmp_path, cl):
    def prepare(service, jid, state):
        actor = state['actors'][OWNER]
        expected = actor['bundle']['actor_template']['proficiency_bonus']
        assert actor['resources'][HANDS] == expected
        assert next(r for r in actor['bundle']['actor_template']['resources'] if r['resource_id'] == HANDS)['maximum'] == expected
        return state
    combat, table, match, commit = table_fixture(tmp_path, cl=cl, maximum_rounds=1, prepare_journey=prepare)
    commit(candidate(table, match, 'Jian (Straight Sword) attack' + (' (Constitution and weapon proficiency)' if cl >= 6 else ''), FOE), {'four_hand_opening':'ac'})
    for _ in range(3):
        if combat._load_session(match).engine.state.terminal_result is not None:
            break
        commit(table.state(match)['menu']['end_turn'])
    state = next(iter(json.loads((tmp_path/'Combat/Journeys/State.json').read_text())['sessions'].values()))
    state = combat.journey_resume(state['journey_id'],state['revision'])
    state = combat.journey_act(state['journey_id'],state['revision'],OWNER,'wait',{'seconds':6})
    expected = combat._load_session(match).engine.state.actors[OWNER].proficiency_bonus
    assert state['actors'][OWNER]['resources'][HANDS] == expected
    assert any(e['kind'] == 'MANDALA_HANDS_REFRESHED' and e['actor_id'] == OWNER for e in state['events'])
    assert CombatService(ROOT,tmp_path).journey_state(state['journey_id']) == state



@pytest.mark.parametrize('seconds', [0, 6])
def test_native_outside_owner_cycle_grants_only_the_earned_circle_reaction(tmp_path, seconds):
    def prepare(service, jid, state):
        state = service.journey_act(jid, state['revision'], OWNER, 'mandala_incarnation')
        assert service.journey_menu(jid, OWNER)['properties']['circle_extra_reaction_available'] == 0
        state = service.journey_act(jid, state['revision'], OWNER, 'wait', {'seconds':seconds})
        assert service.journey_menu(jid, OWNER)['properties']['circle_extra_reaction_available'] == int(seconds == 6)
        assert CombatService(ROOT,tmp_path).journey_state(jid) == state
        return state
    combat, table, match, commit = table_fixture(tmp_path, prepare_journey=prepare, align_owner=False)
    engine = CombatService(ROOT,tmp_path)._load_session(match).engine
    me = engine.state.actors[OWNER]
    held = next(c for c in me.conditions.values() if c.condition_id.endswith('state.thousand_hand_incarnation'))
    assert held.data['hundred_hand_extra_after_turn'] == (me.turns_started if me.turns_started or seconds else 1)
    assert_reload_verify_replay(combat,match,tmp_path)


@pytest.mark.parametrize('different', [False, True])
def test_native_eight_limb_decline_reopens_only_on_a_later_different_form_hit(tmp_path, different):
    combat, table, match, commit = table_fixture(tmp_path, body_attacks=True,
        items=(C7.JIAN,'tianxia.mortal.weapon.chui'))
    for _ in range(12):
        engine = combat._load_session(match).engine
        unarmed = next(a.source_definition_id+'|'+FOE for a in engine.action_catalog.values()
                       if a.owner_id == OWNER and a.display_name == C7.unarmed(engine, OWNER))
        blade, hafted = profile_option(engine,'jian'), profile_option(engine,'chui')
        commit(candidate(table,match,'Weapon-Wheel Body: Attack with weapon choices'),
               {'weapon_wheel_gear':'keep','weapon_wheel_attack':[blade,hafted,unarmed,blade if different else unarmed],
                'eight_limb_completion':[None,'temp_hp|']})
        engine = CombatService(ROOT,tmp_path)._load_session(match).engine
        me = engine.state.actors[OWNER]
        if me.turn_flags['_round_hundred_forms'].get('struck',{}).get(FOE) == 4:
            prompts = [p for p in commit.prompts if p.get('context',{}).get('reaction_source_id') == 'choice:needle.eight_limb_completion']
            assert len(prompts) == (2 if different else 1)
            assert me.temporary_hp == (2*me.proficiency_bonus if different else 0)
            return
        commit(table.state(match)['menu']['end_turn'])
        commit(table.state(match)['menu']['end_turn'])
    pytest.fail('No four native hits for the completion-window boundary in twelve Attack actions')

