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
from tests.ns1r_evidence_helpers import install_authority_test_pack, commit_authority_event, ap_award
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
OWNER, FOE = [FACTORY_ACTOR_PREFIX + 'mandala-' + key for key in ('owner', 'foe')]


def acquisition(tmp_path, cl):
    settings = Settings.from_env(ROOT, tmp_path / 'acquisition')
    settings.ensure_dirs()
    db = Database(settings)
    db.migrate()
    service = NonSphereAuthorityService(db)
    install_authority_test_pack(db, service)
    insert_project(db, 'mandala', cl)
    service.initialize_for_project('mandala', target_cl=cl, path_ids=[BODY], method_id='METHOD-001')
    service.allocate_advancement('mandala', {BODY: 2}, evidence_id=ap_award(db, service, 'mandala', 'METHOD-001', cl, 2), idempotency_key='mandala:cl3')
    with pytest.raises(FoundryError):
        service.select_subpath('mandala', BODY, PARENT)
    access = commit_authority_event(db, service, 'mandala', 'subpath_access', {'selection_id': PARENT})
    service.select_subpath('mandala', BODY, PARENT, access_source_records=[access])
    if cl > 3:
        service.allocate_advancement('mandala', {BODY: cl - 3}, evidence_id=ap_award(db, service, 'mandala', 'METHOD-001', cl, cl - 3), idempotency_key='mandala:advance')
    # Resolve the actual persisted selection and attainment; feature definitions
    # remain source authority, never a hand-authored feature ownership receipt.
    persisted = NonSphereAuthorityService(db).get_state('mandala')
    path = next(row for row in persisted['paths'] if row['path_id'] == BODY)
    assert path['subpath_or_tradition_id'] == PARENT
    assert path['attainment'] == cl
    source = service.subpaths[path['subpath_or_tradition_id']]
    ids = [row['canonical_id'] for row in source['feature_progression'] if row['granted_at_cl'] <= path['attainment']]
    return ids


def table_fixture(tmp_path, cl=18, seed='MANDALA-NATIVE'):
    ids = acquisition(tmp_path, cl)
    sheets = [C7.sheet(ids, cl=cl, items=(C7.JIAN, C7.GUN)), C7.sheet([], cl=cl)]
    bundles = []
    for aid, document in zip((OWNER, FOE), sheets):
        document['identity']['display_name'] = 'Mandala' if aid == OWNER else 'Opponent'
        document['path_and_subpath']['path_record_ids'] = [BODY]
        document['ability_scores_and_statistics']['hit_points']['maximum'] = 1000
        document['ability_scores_and_statistics']['technique_attack_bonus'] = 100
        folder = tmp_path / 'portable_characters' / aid.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
        bundles.append(compile_character(document, actor_id=aid, reaction_plan={'ask': True}))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    arena = combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    match = combat._finish_factory_match(bundles, [OWNER, FOE], {OWNER: 'team:a', FOE: 'team:b'},
        {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6}}, arena, [OWNER], [FOE],
        control_modes={OWNER: 'MANUAL', FOE: 'MANUAL'}, match_seed=seed, display_name='Hundred-Hand regression', maximum_rounds=15)['match_id']

    def commit(cid, picks=None):
        answers = []
        for _ in range(40):
            menu = table.state(match)['menu']
            result = table.act(match, cid, menu['decision_id'], menu['state_version'], 0, answers)
            if result['status'] == 'COMMITTED':
                assert_reload_verify_replay(combat, match, tmp_path)
                return result
            assert result['status'] == 'REACTION_REQUIRED', result
            prompt = result['reaction']
            answer = {**prompt['context'], 'selection': 'DECLINE'}
            choice = prompt.get('choice')
            if choice:
                options = [option['id'] for option in choice['options']]
                desired = next((value for key, value in (picks or {}).items()
                                if key in str(prompt) and value in options), None)
                if desired:
                    answer.update(selection='USE', option_ids=[desired])
                elif not choice.get('allow_decline', True):
                    answer.update(selection='USE', option_ids=options[:1])
            answers.append(answer)
        raise AssertionError('choice did not settle')
    for _ in range(8):
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
    assert not C7.payloads(events, 'D20_REWRITTEN')
    assert me.resources[HANDS] == 5


def test_four_hand_damage_is_in_the_triggering_packet():
    engine, me, foe = C7._mandala(['four_hand_sequence'], picks={'four_hand_opening': None, 'four_hand_sequence': ['damage']})
    foe.armor_class = -50
    events = C7.use(engine, C7.unarmed(engine), target=foe.entity_id)
    packets = C7.payloads(events, 'DAMAGE_COMMITTED')
    assert len(packets) == len(C7.payloads(events, 'ATTACK_ROLLED'))
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
    assert waive(engine, me, row, True) == 'free'
    engine.state.round_number += 1
    assert waive(engine, me, row, False) is None
    C7.turn(engine, C7.ME)
    me.reaction_available = False
    assert waive(engine, me, row, False) == 'free'
