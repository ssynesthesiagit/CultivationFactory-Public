"""Shared Listen Through Tension fixture helpers (fight, cold replay, choose, menus).

Not collected by pytest; imported by the test_mgr_t15_listen_tension* modules."""
import json
import zipfile
import pytest
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import normalize_map, to_battlefield
from tests.h1_support import ROOT, sheet
from tests.test_r4_integration import reach, send, candidate
from tests.test_a2_thread import cold as replayed_cold

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


def cold(tmp_path, mid):
    """Retain compact actual cold-service/replay receipts for packet review."""
    engine = replayed_cold(tmp_path, mid)
    record = {'match_id': mid, 'sequence': engine.state.event_sequence, 'replay': 'PASS',
        'actors': {aid: {'position': a.position.model_dump(mode='json'),
            'conditions': [c.model_dump(mode='json') for c in a.conditions.values()
                           if c.condition_id in ('condition:typed.thread_listen',
                              'condition:typed.invisible') or 'thread' in c.condition_id]}
                   for aid, a in engine.state.actors.items()},
        'objects': [o.model_dump(mode='json') for o in engine.state.objects.values()
                    if (o.component or {}).get('thread_line') == 1],
        'checks': [e.model_dump(mode='json') for e in engine.events if e.event_type == 'CHECK_ROLLED']}
    with (tmp_path/'listen-native.jsonl').open('a') as stream:
        stream.write(json.dumps(record, sort_keys=True) + '\n')
    return engine


def fight(tmp_path, *, foe_mids=(), objects=(), peer=False, owner_talents=(), owner_spheres=('tianxia.sphere.thread',),
          foe_x=7, arm_foe=False, foe_score=14, owner_dc=16, ask_reactions=False):
    """P owns the Thread sphere plus ``owner_spheres``/``owner_talents``; S may peer-own Thread."""
    for aid in (P, F, S):
        doc = sheet(foe_mids if aid == F else [], cl=20, name=aid[-8:],
                    score=foe_score if aid == F else 14, dc=owner_dc if aid == P else 16)
        doc['identity'].update(display_name=aid[-8:], path_ids=['tianxia.path.qi_cultivation'])
        doc['path_and_subpath'] = {'path_record_ids': ['tianxia.path.qi_cultivation']}
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 2000
        doc['ability_scores_and_statistics']['technique_attack_bonus'] = 1000
        if arm_foe and aid == F:
            doc['equipment'] = [{'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.jian', 'quantity': 1}]}}]
        folder = tmp_path/'portable_characters'/aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    from canonical_catalog.service import CanonicalCatalogAuthorityService
    table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    for sphere in owner_spheres:
        table.add_advancement(P.removeprefix('actor:factory.'), 'sphere', sphere)
    if peer:
        table.add_advancement(S.removeprefix('actor:factory.'), 'sphere', 'tianxia.sphere.thread')
    for talent in owner_talents:
        table.add_advancement(P.removeprefix('actor:factory.'), 'talent', talent)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    doc = combat._factory_owner_sheet(P.removeprefix('actor:factory.'))
    assert LISTEN in doc['spheres_and_talents']['automatic_sphere_component_record_ids']
    assert doc['spheres_and_talents']['learned_talent_record_ids'] == list(owner_talents)
    ids = [P, F, S]
    bundles = [compile_character(combat._factory_owner_sheet(a.removeprefix('actor:factory.')), actor_id=a,
               **({'reaction_plan': {'ask': True}} if ask_reactions else {})) for a in ids]
    arena = to_battlefield(normalize_map({'display_name': 'Listen arena', 'width_squares': 10, 'height_squares': 10, 'objects': list(objects)}))
    mid = combat._finish_factory_match(bundles, ids, {P: 'team:a', F: 'team:b', S: 'team:a'},
        {P: {'x': 2, 'y': 6}, F: {'x': foe_x, 'y': 6}, S: {'x': 2, 'y': 7}}, arena, ids, [],
        control_modes={a: 'MANUAL' for a in ids}, match_seed='LISTEN-TENSION', display_name='Listen', maximum_rounds=12)['match_id']
    reach(table, mid, P)
    return combat, table, mid


def choose(table, mid, cid, values=(), *, decline=False):
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
        benefits = {'motion', 'handling', 'check', 'space'}
        offered = benefits & set(opts)
        missing = [v for v in values if v in benefits and offered and v not in opts]
        assert not missing, f'requested benefit {missing} not offered in {opts}'
        wanted = next((v for v in values if v in opts), opts[0] if opts else None)
        answers.append({**p['context'], 'selection': 'DECLINE' if decline else 'USE', 'option_ids': [] if decline else [wanted] if wanted else []})
    raise AssertionError('unsettled choices')


def draw(table, mid):
    choose(table, mid, candidate(table, mid, 'Draw the Line: Guide (Qi Thread)', F))


def names(engine):
    return [c.display_name for c in engine.legal_candidates()]


def grants(engine):
    return [c for c in engine.state.actors[P].conditions.values() if c.condition_id == 'condition:typed.thread_listen']


def checks(engine):
    """Unspent printed check benefits (Advantage still available)."""
    return [c for c in grants(engine) if c.data.get('benefit') == 'check']


def receipts(engine):
    """Spent check kept only as line-bound eligibility for the Invisible clause."""
    return [c for c in grants(engine) if c.data.get('benefit') == 'space_eligible']



def private(table, mid, viewer=P):
    result = table.state(mid, fog=True, fog_view='own', fog_actor_ids=(viewer,))
    return result['private_information'].get(viewer, [])


HUNDRED = 'tianxia.talent.thread.hundred_line_weaving'


def advance(table, mid, actor, *, keep=False):
    for _ in range(8):
        menu = table.state(mid)['menu']
        if menu['actor_id'] == actor:
            return
        choose(table, mid, menu['end_turn'], decline=not keep)
    raise AssertionError('turn not reached')


def mundane(table, mid):
    """Choose the plain single-target Guide option, not a printed twin.

    The menu is ranked, so a substring search can return '(two targets)' or
    '(Qi Thread)' when one is ranked above the plain option. Those are different
    printed choices; this helper draws the ordinary twenty-foot line when it is
    legal and falls back to the Qi twin only where that is the one offered.
    """
    labels = [(o.get('label') or g['label'], o['candidate_id'])
              for g in table.state(mid)['menu']['actions'] for o in g['options']]
    plain = [cid for label, cid in labels if label == 'Draw the Line: Guide']
    choose(table, mid, plain[0] if plain else candidate(table, mid, 'Draw the Line: Guide', F))


def physical_line(engine):
    return next(o for o in engine.state.objects.values()
                if (o.component or {}).get('thread_line') == 1 and not o.destroyed)
