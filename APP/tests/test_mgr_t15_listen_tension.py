"""Native acquisition, table choices, cold reload and mechanical replay for Listen.

Runtime inputs: authority/typed_mechanics/rules_text.json,
authority/Tianxia_Typed_Mechanics_Authority_R1.json,
authority/typed_mechanics/reviewed_final.d/review_sw-thread.json.
"""
import json
import zipfile
import pytest
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import normalize_map, to_battlefield
from tests.h1_support import ROOT, sheet
from tests.test_r4_integration import reach, send, candidate
from tests.test_a2_thread import cold

LISTEN = 'THREAD_BASE_LISTEN_THROUGH_TENSION'
P, F, S = ['actor:factory.' + p for p in ('a1150001', 'a1150002', 'a1150003')]
QI = 'resource:core.qi'
RUNTIME_INPUTS = ('authority/Tianxia_Forged_Technique_Authority_R1.json',
    'authority/Tianxia_Immortal_Art_Authority_R1.json',
    'catalog_authority/cat3/generated/catalog_authority.v1.json',
    'authority/typed_mechanics/rules_text.json',
    'authority/Tianxia_Typed_Mechanics_Authority_R1.json',
    'authority/typed_mechanics/reviewed_final.d/review_sw-thread.json',
    'authority/Tianxia_Sphere_Path_Access_R1.json',
    'catalog_authority/cat1/data/prerequisite_projection.v1.json')


def fight(tmp_path, *, foe_mids=(), objects=(), peer=False):
    for aid in (P, F, S):
        doc = sheet(foe_mids if aid == F else [], cl=20, name=aid[-8:])
        doc['identity'].update(display_name=aid[-8:], path_ids=['tianxia.path.qi_cultivation'])
        doc['path_and_subpath'] = {'path_record_ids': ['tianxia.path.qi_cultivation']}
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 2000
        doc['ability_scores_and_statistics']['technique_attack_bonus'] = 1000
        folder = tmp_path/'portable_characters'/aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    from canonical_catalog.service import CanonicalCatalogAuthorityService
    table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    table.add_advancement(P.removeprefix('actor:factory.'), 'sphere', 'tianxia.sphere.thread')
    if peer:
        table.add_advancement(S.removeprefix('actor:factory.'), 'sphere', 'tianxia.sphere.thread')
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    doc = combat._factory_owner_sheet(P.removeprefix('actor:factory.'))
    assert LISTEN in doc['spheres_and_talents']['automatic_sphere_component_record_ids']
    assert not doc['spheres_and_talents']['learned_talent_record_ids']
    ids = [P, F, S]
    bundles = [compile_character(combat._factory_owner_sheet(a.removeprefix('actor:factory.')), actor_id=a) for a in ids]
    arena = to_battlefield(normalize_map({'display_name': 'Listen arena', 'width_squares': 10, 'height_squares': 10, 'objects': list(objects)}))
    mid = combat._finish_factory_match(bundles, ids, {P: 'team:a', F: 'team:b', S: 'team:a'},
        {P: {'x': 2, 'y': 6}, F: {'x': 7, 'y': 6}, S: {'x': 2, 'y': 7}}, arena, ids, [],
        control_modes={a: 'MANUAL' for a in ids}, match_seed='LISTEN-TENSION', display_name='Listen', maximum_rounds=12)['match_id']
    reach(table, mid, P)
    return combat, table, mid


def choose(table, mid, cid, values=()):
    answers = []
    seen = []
    for _ in range(12):
        root = table.combat.userdata_root
        table = TabletopService(CombatService(ROOT, root), root)
        result = send(table, mid, cid, answers)
        if result['status'] == 'COMMITTED':
            return seen
        assert result['status'] == 'REACTION_REQUIRED', result
        p = result['reaction']
        opts = [o['id'] for o in p.get('choice', {}).get('options', [])]
        seen.append(opts)
        wanted = next((v for v in values if v in opts), opts[0] if opts else None)
        answers.append({**p['context'], 'selection': 'USE', 'option_ids': [wanted] if wanted else []})
    raise AssertionError('unsettled choices')


def draw(table, mid):
    choose(table, mid, candidate(table, mid, 'Draw the Line: Guide (Qi Thread)', F))


def names(engine):
    return [c.display_name for c in engine.legal_candidates()]


def grants(engine):
    return [c for c in engine.state.actors[P].conditions.values() if c.condition_id == 'condition:typed.thread_listen']


def test_listen_requires_actual_owned_line(tmp_path):
    _, table, mid = fight(tmp_path)
    assert 'Listen Through Tension' not in names(cold(tmp_path, mid))


@pytest.mark.parametrize('skill', ['Insight', 'Perception', 'Sleight of Hand'])
def test_one_chosen_check_consumes_only_after_eligible_roll(tmp_path, skill):
    _, table, mid = fight(tmp_path)
    draw(table, mid)
    before = cold(tmp_path, mid).state.actors[P].resources[QI]
    prompts = choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('check', F))
    assert any(set(('motion', 'handling', 'check', 'space')) == set(opts) for opts in prompts)
    e = cold(tmp_path, mid)
    assert len(grants(e)) == 1
    assert e.state.actors[P].resources[QI] == before
    assert not e.state.actors[P].bonus_action_available
    assert grants(e)[0].expires_on == 'END_OF_MARKER_NEXT_TURN'
    from combat.typed_executor import check_modes
    assert 'ADVANTAGE' not in check_modes(e.state.actors[P], 'WIS', 'Perception', engine=e)
    reach(table, mid, F)
    reach(table, mid, P)
    assert grants(cold(tmp_path, mid))
    choose(table, mid, candidate(table, mid, 'Check involving your Thread Line'), (skill, F))
    e = cold(tmp_path, mid)
    rows = [x for x in e.events if x.event_type == 'CHECK_ROLLED' and x.actor_id == P]
    assert rows[-1].payload['actor']['mode'] == 'ADVANTAGE'
    assert rows[-1].payload['skill'] == skill
    assert not grants(e)
    from combat.typed_executor import check_modes
    assert 'ADVANTAGE' not in check_modes(e.state.actors[P], 'WIS', 'Perception', engine=e)


def test_unused_grant_expires_at_next_end(tmp_path):
    _, table, mid = fight(tmp_path)
    draw(table, mid)
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('check', F))
    reach(table, mid, F)
    reach(table, mid, P)
    assert grants(cold(tmp_path, mid))
    send(table, mid, table.state(mid)['menu']['end_turn'])
    assert not grants(cold(tmp_path, mid))


def private(table, mid, viewer=P):
    result = table.state(mid, fog=True, fog_view='own', fog_actor_ids=(viewer,))
    return result['private_information'].get(viewer, [])


def test_native_movement_facts_are_private_and_reset_on_stopping(tmp_path):
    combat, table, mid = fight(tmp_path)
    draw(table, mid)
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('motion',))
    assert private(table, mid)[0]['motion'] == 'still'
    assert table.state(mid)['private_information'] == {}
    assert private(table, mid, S) == []
    reach(table, mid, F)
    assert not combat.decision(mid)['context'].get('private_information')
    for x, expected in ((6, 'closer'), (7, 'farther')):
        e = cold(tmp_path, mid)
        step = next(c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination
                    and (c.destination.x, c.destination.y, c.destination.z) == (x, 6, 0))
        choose(table, mid, step.candidate_id)
        assert private(table, mid)[0]['motion'] == expected
        assert private(table, mid, S) == []
    send(table, mid, table.state(mid)['menu']['end_turn'])
    assert private(table, mid)[0]['motion'] == 'still'
    cold(tmp_path, mid)


def test_real_holding_and_ignoring_have_no_inferred_default(tmp_path):
    _, table, mid = fight(tmp_path)
    draw(table, mid)
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('handling',))
    assert private(table, mid)[0]['handling'] == 'unknown'
    reach(table, mid, F)
    e = cold(tmp_path, mid)
    before = (e.state.actors[F].action_available, dict(e.state.actors[F].resources))
    choose(table, mid, candidate(table, mid, 'Thread Line: holding'))
    assert private(table, mid)[0]['handling'] == 'holding'
    e = cold(tmp_path, mid)
    assert (e.state.actors[F].action_available, dict(e.state.actors[F].resources)) == before
    from combat.ext.hand_occupancy import occupancy
    assert any(any('condition:' in occupant for occupant in owners) for owners in occupancy(e, e.state.actors[F]).values())
    choose(table, mid, candidate(table, mid, 'Thread Line: ignoring'))
    assert private(table, mid)[0]['handling'] == 'ignoring'
    assert private(table, mid, S) == []
    cold(tmp_path, mid)


def test_invisible_connection_gives_only_listener_current_space_and_ends_with_line(tmp_path):
    combat, table, mid = fight(tmp_path, foe_mids=['tianxia.talent.illusion.greater_invisibility'])
    draw(table, mid)
    reach(table, mid, F)
    choose(table, mid, candidate(table, mid, 'Greater Invisibility', F))
    reach(table, mid, P)
    e = cold(tmp_path, mid)
    from combat.target_knowledge import located, can_see
    assert not can_see(e, e.state.actors[P], e.state.actors[F])
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('space',))
    e = cold(tmp_path, mid)
    assert located(e, e.state.actors[P], e.state.actors[F])
    assert not can_see(e, e.state.actors[P], e.state.actors[F])
    assert not located(e, e.state.actors[S], e.state.actors[F])
    assert private(table, mid)[0]['position'] == e.state.actors[F].position.model_dump(mode='json')
    assert private(table, mid, S) == []
    context = combat.decision(mid)['context']
    assert context['private_information'][0]['position'] == private(table, mid)[0]['position']
    assert grants(e)[0].expires_on == 'UNTIL_REMOVED'
    send(table, mid, table.state(mid)['menu']['end_turn'])
    e = cold(tmp_path, mid)
    assert not grants(e)
    assert not located(e, e.state.actors[P], e.state.actors[F])


def test_object_connection_is_created_by_actual_non_damaging_thread_hit(tmp_path):
    _, table, mid = fight(tmp_path, objects=[{'id': 1, 'kind': 'custom', 'name': 'Bell',
        'x': 7, 'y': 5, 'blocks': False, 'ac': 10, 'hp': 30}])
    before = cold(tmp_path, mid).state.objects['object:map.1'].current_hp
    choose(table, mid, candidate(table, mid, 'Draw the Line: Guide (Qi Thread) (at an object)', 'object:map.1'))
    e = cold(tmp_path, mid)
    assert e.state.objects['object:map.1'].current_hp == before
    from combat.ext.thread_base_line import maintained_lines
    assert maintained_lines(e, e.state.actors[P])[0][1].object_id == 'object:map.1'
    from combat.ext.thread_common import thread_line_cells
    assert (7, 5, 0) in thread_line_cells(e, e.state.actors[P])
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('motion',))
    assert private(table, mid)[0]['motion'] == 'still'
    e = cold(tmp_path, mid)
    assert len(grants(e)) == 1


def test_automatic_owner_can_choose_a_source_reading_without_other_seats_facts(tmp_path):
    combat, table, mid = fight(tmp_path)
    draw(table, mid)
    cid = candidate(table, mid, 'Listen Through Tension')
    from tests.test_r4_integration import auto_candidate
    auto_candidate(combat, mid, P, cid)
    assert table.auto_step(mid, 0)['status'] == 'COMMITTED'
    e = cold(tmp_path, mid)
    assert len(grants(e)) == 1
    assert grants(e)[0].data['benefit'] == 'motion'
    assert private(table, mid)[0]['motion'] == 'still'
    assert private(table, mid, S) == []


_SOURCE_RECEIPT = False


@pytest.fixture(autouse=True)
def exact_native_source_receipt(capsys):
    """Print source bytes once, including on locally routed delayed execution."""
    global _SOURCE_RECEIPT
    if not _SOURCE_RECEIPT:
        import hashlib
        paths = ('combat/ext/thread_base_line.py', 'combat/ext/thread_common.py', 'combat/ext/thread_weaving.py',
                 'combat/ext/scoped_checks.py', 'combat/ext/objects.py',
                 'combat/target_knowledge.py', 'combat/private_information.py',
                 'combat/gate4_models.py', 'combat/gate4_context.py', 'combat/tabletop_service.py')
        with capsys.disabled():
            print('LISTEN_NATIVE_SOURCE_SHA256=' + json.dumps({p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() if (ROOT/p).is_file() else 'ABSENT' for p in paths}, sort_keys=True), flush=True)
        _SOURCE_RECEIPT = True


def test_foreign_line_never_satisfies_your_listen_range(tmp_path):
    _, table, mid = fight(tmp_path, peer=True)
    reach(table, mid, S)
    draw(table, mid)
    reach(table, mid, P)
    e = cold(tmp_path, mid)
    from combat.ext.thread_common import maintained_lines
    assert maintained_lines(e, e.state.actors[S])
    assert not maintained_lines(e, e.state.actors[P])
    assert 'Listen Through Tension' not in names(e)
