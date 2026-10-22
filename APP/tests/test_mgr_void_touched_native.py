"""Native acquired progression -> table intent -> cold replay regressions.

Authority events represent an explicit GM source-access decision. Neither
feature ownership, a hit, a mark nor a recovery-denial receipt is injected.
These tests certify only the clauses their assertions exercise.
"""
from copy import deepcopy

import pytest

from app.core import Database, Settings, FoundryError
from combat.factory_compiler import compile_character
from combat.authority_projection import compile_project_character
from non_sphere_authority import NonSphereAuthorityService
from tests.h1_support import ROOT, sheet
from tests.ns1r_evidence_helpers import install_authority_test_pack, ap_award, commit_authority_event
from tests.test_ns1r_non_sphere_authority import insert_project
from tests.worker2_support import OWNER, FOE, fixture, candidate, reload, settle, turn

QI = 'tianxia.path.qi_cultivation'
PARENT = 'tianxia.subpath.qi.void_touched_cultivator'
PREFIX = PARENT + '.feature.'
MARK = 'condition:typed.void_touched_mark'
MERIDIAN = 'condition:typed.void_touched_meridian'
SCAR = 'My reflection no longer appears.'
CP_POOLS = ('resource:core.qi', 'resource:core.stamina', 'resource:core.resonance', 'resource:core.cp')


def marks(actor, source):
    return sum(int(condition.data.get('count') or 0) for condition in actor.conditions.values()
               if condition.condition_id == MARK and condition.source_actor_id == source)


@pytest.fixture(scope='module')
def acquired(tmp_path_factory):
    settings = Settings.from_env(ROOT, tmp_path_factory.mktemp('void-acquisition'))
    settings.ensure_dirs()
    db = Database(settings)
    db.migrate()
    service = NonSphereAuthorityService(db)
    install_authority_test_pack(db, service)
    documents = {}

    def get(cl=6):
        if cl not in documents:
            project = 'void-native-' + str(cl)
            insert_project(db, project, cl)
            service.initialize_for_project(project, target_cl=cl, path_ids=[QI], method_id='METHOD-001')
            service.allocate_advancement(project, {QI: cl - 1},
                evidence_id=ap_award(db, service, project, 'METHOD-001', cl, cl - 1),
                idempotency_key=project + '-advance')
            access = commit_authority_event(db, service, project, 'subpath_access',
                {'selection_id': PARENT, 'path_id': QI})
            with pytest.raises(FoundryError, match='starting option'):
                service.select_subpath(project, QI, PARENT, [access])
            service.select_subpath(project, QI, PARENT, [access], acquisition_choices={'void_scar': SCAR})
            service.set_resource(project, QI, current=30, maximum=30)  # the Path resource must be recorded before combat
            state = NonSphereAuthorityService(db).get_state(project)
            path = next(p for p in state['paths'] if p['path_id'] == QI)
            assert path['acquisition_choices'] == {'void_scar': SCAR}
            doc = sheet([], cl=cl, name='Void cultivator', dc=50)
            doc.setdefault('spheres_and_talents', {})['sphere_record_ids'] = ['tianxia.sphere.void']
            doc['ability_scores_and_statistics']['technique_attack_bonus'] = 100
            doc['path_and_subpath'] = {'paths': state['paths']}
            documents[cl] = doc
        return deepcopy(documents[cl])

    get.service = service
    return get


@pytest.mark.parametrize('cl,expected', [(3, {'void_step'}),
    (6, {'void_step', 'empty_palm'}), (10, {'void_step', 'empty_palm', 'hollow_field'}),
    (14, {'void_step', 'empty_palm', 'hollow_field', 'erase'}),
    (18, {'void_step', 'empty_palm', 'hollow_field', 'erase', 'law_of_nonexistence'})])
def test_native_progression_and_permanent_scar(acquired, cl, expected):
    doc = acquired(cl)
    bundle = compile_project_character(acquired.service, 'void-native-' + str(cl), doc, actor_id=OWNER)
    sources = {a['parameters'].get('typed', {}).get('source', '') for a in bundle['action_catalog']}
    assert {key.removeprefix(PREFIX) for key in sources if key.startswith(PREFIX)} == expected
    for action in bundle['action_catalog']:
        typed = action['parameters'].get('typed') or {}
        if typed.get('source', '').startswith(PREFIX):
            assert typed['void_scar'] == SCAR
    with pytest.raises(FoundryError, match='already established'):
        acquired.service.select_subpath('void-native-' + str(cl), QI, PARENT,
            acquisition_choices={'void_scar': 'A different scar'})
    unchanged = acquired.service.select_subpath('void-native-' + str(cl), QI, PARENT)
    assert unchanged['permanent_acquisition_choices'][PARENT] == {'void_scar': SCAR}


def table(acquired, tmp_path, *, miss=False, cl=6, foe_no_cp=False):
    doc = acquired(cl)
    bundle = compile_project_character(acquired.service, 'void-native-' + str(cl), doc, actor_id=OWNER, reaction_plan={'ask': True})
    foe = sheet([], cl=cl, name='Cultivator foe')
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 500
    foe['ability_scores_and_statistics']['armor_class']['base_value'] = 1000 if miss else 1
    combat, tabletop, mid = fixture(tmp_path, [], cl=cl, owner_bundle=bundle,
        foe_sheet=foe, foe_zero_cp=foe_no_cp, named=True, seed='VOID-TOUCHED-NATIVE', foe_position={'x': 4, 'y': 6},
        ally_position={'x': 3, 'y': 7})
    return combat, tabletop, mid


def test_empty_palm_hit_drains_marks_and_denies_recovery_after_cold_reload(acquired, tmp_path):
    combat, tabletop, mid = table(acquired, tmp_path)
    before = reload(tmp_path, mid)
    owner_qi = before.state.actors[OWNER].resources['resource:core.qi']
    foe_qi = before.state.actors[FOE].resources['resource:core.qi']
    action = candidate(combat, mid, 'Empty Palm: Empty the Meridian', target=FOE)
    settle(tabletop, mid, action.candidate_id)
    engine = reload(tmp_path, mid)
    target = engine.state.actors[FOE]
    assert marks(target, OWNER) == 1
    mark = next(c for c in target.conditions.values() if c.condition_id == MARK)
    assert mark.data.get('ends_with_scene') == 1 and mark.expires_on is None
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == owner_qi - 3
    assert target.resources['resource:core.qi'] == foe_qi - 4
    condition = next(c for c in target.conditions.values() if c.condition_id == MERIDIAN)
    assert str(target.turns_started + 1) == condition.expires_on.rsplit(':', 1)[-1]
    assert any(e.event_type == 'DAMAGE_COMMITTED' and FOE in e.target_ids
               for e in engine.events)
    engine = reload(tmp_path, mid)
    held = engine.state.actors[FOE].resources['resource:core.qi']
    engine._gain_resource(engine.state.actors[FOE], 'resource:core.qi', 2, OWNER)
    assert engine.state.actors[FOE].resources['resource:core.qi'] == held  # real recovery denied while held
    turn(tabletop, mid, FOE)
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == MERIDIAN for c in engine.state.actors[FOE].conditions.values())
    held = engine.state.actors[FOE].resources['resource:core.qi']
    engine._gain_resource(engine.state.actors[FOE], 'resource:core.qi', 2, OWNER)
    assert engine.state.actors[FOE].resources['resource:core.qi'] > held  # and allowed once it has expired


def test_empty_palm_miss_neither_marks_nor_drains(acquired, tmp_path):
    combat, tabletop, mid = table(acquired, tmp_path, miss=True)
    before = reload(tmp_path, mid).state.actors[FOE].resources['resource:core.qi']
    settle(tabletop, mid, candidate(combat, mid, 'Empty Palm: Empty the Meridian', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    target = engine.state.actors[FOE]
    assert marks(target, OWNER) == 0
    assert target.resources['resource:core.qi'] == before
    assert not any(c.condition_id == MERIDIAN for c in target.conditions.values())


def test_void_step_trace_is_a_post_teleport_player_choice(acquired, tmp_path):
    combat, tabletop, mid = table(acquired, tmp_path, cl=3)
    before = reload(tmp_path, mid)
    departure = before.state.actors[OWNER].position
    qi = before.state.actors[OWNER].resources['resource:core.qi']
    prompts = settle(tabletop, mid, candidate(combat, mid, 'Void Step').candidate_id,
        picks={'choice:needle.void_step_trace': [FOE]})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].position != departure
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == qi - 2
    assert marks(engine.state.actors[FOE], OWNER) == 1
    assert any(prompt['context']['reaction_source_id'] == 'choice:needle.void_step_trace'
               for prompt in prompts)
    assert engine.state.actors[OWNER].turn_flags.get('_round_void_step_turn')


def test_native_palm_marks_cap_at_three_and_have_one_owner(acquired, tmp_path):
    combat, tabletop, mid = table(acquired, tmp_path)
    for _ in range(5):
        turn(tabletop, mid, OWNER)
        settle(tabletop, mid, candidate(combat, mid, 'Empty Palm: Empty the Meridian', target=FOE).candidate_id)
        settle(tabletop, mid, tabletop.state(mid)['menu']['end_turn'])
    engine = reload(tmp_path, mid)
    target = engine.state.actors[FOE]
    assert marks(target, OWNER) == 3
    assert marks(target, FOE) == 0
    assert len([condition for condition in target.conditions.values()
                if condition.condition_id == MARK and condition.source_actor_id == OWNER]) == 1


def test_wrong_parent_cannot_grant_the_progression(acquired):
    doc = acquired(6)
    selected = next(path for path in doc['path_and_subpath']['paths']
                    if path.get('subpath_or_tradition_id') == PARENT)
    selected['path_id'] = 'tianxia.path.body_refining'
    bundle = compile_character(doc, actor_id=OWNER)
    assert not any(a['parameters'].get('typed', {}).get('source', '').startswith(PREFIX)
                   for a in bundle['action_catalog'])


def test_loose_scar_cannot_admit_an_unacquired_family(tmp_path):
    doc = sheet([PREFIX + 'empty_palm'], cl=6)
    doc['path_and_subpath']['void_scar'] = SCAR
    bundle = compile_character(doc, actor_id=OWNER)
    combat, tabletop, mid = fixture(tmp_path, [], cl=6, owner_bundle=bundle)
    engine = reload(tmp_path, mid)
    assert not any(action.display_name.startswith('Empty Palm')
                   for c in engine.legal_candidates()
                   if (action := engine.action_catalog.get(c.source_definition_id)) is not None)


def test_void_marks_end_with_the_scene(acquired, tmp_path):
    from combat.ext.source_records import scene_conditions_end
    combat, tabletop, mid = table(acquired, tmp_path)
    action = candidate(combat, mid, 'Empty Palm: Empty the Meridian', target=FOE)
    settle(tabletop, mid, action.candidate_id)
    engine = reload(tmp_path, mid)
    assert marks(engine.state.actors[FOE], OWNER) == 1
    scene_conditions_end(engine)
    assert marks(engine.state.actors[FOE], OWNER) == 0


def test_void_touched_requires_the_void_sphere(acquired):
    doc = acquired(6)
    doc['spheres_and_talents'] = {'sphere_record_ids': [], 'learned_talent_record_ids': [],
                                  'automatic_sphere_component_record_ids': []}
    with pytest.raises(FoundryError, match='prerequisite'):
        compile_project_character(acquired.service, 'void-native-6', doc, actor_id=OWNER)




def test_empty_palm_no_points_save_not_skipped(acquired, tmp_path):
    """Empty the Meridian always runs its Constitution save, even when the target has no CP.

    The no-CP case is resolved by drain_meridian: a failed save applies the
    MERIDIAN condition, a successful save deals Force damage. Before the fix the
    save was skipped, so neither a save event nor either outcome appeared.
    """
    combat, tabletop, mid = table(acquired, tmp_path, cl=6, foe_no_cp=True)
    before = reload(tmp_path, mid).state.actors[FOE]
    assert not any(before.resources.get(pool, 0) for pool in CP_POOLS)  # precondition: no CP
    settle(tabletop, mid, candidate(combat, mid, 'Empty Palm: Empty the Meridian', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    target = engine.state.actors[FOE]
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE for e in engine.events), \
        'Constitution save was skipped when the target had 0 CP'
    held = any(c.condition_id == MERIDIAN for c in target.conditions.values())
    forced = any(e.event_type == 'DAMAGE_COMMITTED' and FOE in e.target_ids for e in engine.events)
    assert held or forced, 'a failed save must apply MERIDIAN and a successful save must deal Force damage'


def test_combat_factory_compile_uses_native_acquisition(acquired):
    from combat.gate5_service import CombatService
    doc = acquired(6)
    service = CombatService.__new__(CombatService)
    service.authority = acquired.service
    service._factory_owner_sheet = lambda project_id, **kwargs: deepcopy(doc)
    bundle = service._compile_factory('void-native-6', actor_id=OWNER)
    sources = {a['parameters'].get('typed', {}).get('source', '') for a in bundle['action_catalog']}
    assert {PREFIX + 'void_step', PREFIX + 'empty_palm'} <= sources
