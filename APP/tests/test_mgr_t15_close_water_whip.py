"""Water Whip: native learning -> table -> cold continuation/replay.

Only opponent defenses/skills are extreme to make dice-independent boundaries.
No mechanic, resource receipt, or successful hold is installed by the fixture.
"""
import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]
WHIP = 'TAL_WATER_WATER_WHIP'
SPHERE = 'tianxia.sphere.water'
OWNER_PID = '00000000-0000-0000-0000-000000000001'
TARGET_PID = '00000000-0000-0000-0000-000000000002'
OWNER = 'actor:factory.ww-owner'
FOE = 'actor:factory.ww-target'
CP = 'resource:core.qi'
# Literal dynamic authority/registry dependencies for public source export.
DEPENDENCIES = ('authority/typed_mechanics/rules_text.json',
                'authority/Tianxia_Typed_Mechanics_Authority_R1.json',
                'authority/Tianxia_Forged_Technique_Authority_R1.json',
                'catalog_authority/cat1/data/canonical_talents.v1.json',
                'combat/rules/feature_blocks.d/auto38_water.json',
                'combat/rules/feature_blocks.d/a2_water.json')


def document(name, *, cp=3, dc=9, save=-100, skill=100, ac=1, cl=1):
    pb = 6 if cl >= 17 else 3 if cl >= 5 else 2
    return {'identity': {'name': name, 'cultivation_level': cl,
                'proficiency_bonus': pb, 'path': 'Qi Cultivation',
                'path_ids': ['tianxia.path.qi_cultivation'], 'key_ability': 'CON'},
        'ability_scores_and_statistics': {
            'abilities': [{'ability': a, 'score': 8 if a == 'CON' else 14,
                           'modifier': -1 if a == 'CON' else 2}
                          for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
            'primary_resource': {'name': 'Qi', 'maximum': cp},
            'armor_class': {'base_value': ac}, 'hit_points': {'maximum': 1000},
            'speed': {'walking_ft': 30}, 'technique_save_dc': dc,
            'technique_attack_bonus': pb - 1, 'saving_throws': {'STR': save},
            'skills': [{'skill': s, 'bonus': skill} for s in ('Athletics', 'Acrobatics')]}}


def setup(tmp_path, *, own=True, cp=3, dc=9, save=-100, skill=100, miss=False, cl=5):
    for pid, doc in [(OWNER_PID, document('Wren', cp=cp, dc=dc, cl=cl)),
                     (TARGET_PID, document('Mara', save=save, skill=skill, ac=100 if miss else 1))]:
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    table.add_advancement(OWNER_PID, 'sphere', SPHERE)
    if own:
        option = next(x for x in table.advancement(OWNER_PID)['talents'] if x['id'] == WHIP)
        assert option['legal'], option
        table.add_advancement(OWNER_PID, 'talent', WHIP)
    combat, table = cold(tmp_path)
    source = combat._factory_owner_sheet(OWNER_PID)
    assert (WHIP in source['spheres_and_talents']['learned_talent_record_ids']) is own
    assert 'WATER_BASE_WATER_LASH' in source['spheres_and_talents']['automatic_sphere_component_record_ids']
    bundles = [compile_character(combat._factory_owner_sheet(pid), actor_id=aid,
                                reaction_plan={'ask': True})
               for pid, aid in [(OWNER_PID, OWNER), (TARGET_PID, FOE)]]
    mid = combat._finish_factory_match(bundles, [OWNER, FOE],
        {OWNER: 'team:a', FOE: 'team:b'},
        {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 6, 'y': 6}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        [OWNER], [FOE], control_modes={OWNER: 'MANUAL', FOE: 'MANUAL'},
        match_seed='MGR-T15-WATER-WHIP', display_name='Water Whip', maximum_rounds=12)['match_id']
    advance(tmp_path, mid, OWNER)
    return mid


def cold(path):
    combat = CombatService(ROOT, path)
    return combat, TabletopService(combat, path)


def load(path, mid):
    session = cold(path)[0]._load_session(mid)
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def candidate(path, mid, name, target):
    e = load(path, mid)
    return next(c for c in e.legal_candidates()
                if e.action_catalog.get(c.source_definition_id)
                and e.action_catalog[c.source_definition_id].display_name == name
                and c.target_ids == (target,)).candidate_id


def commit(path, mid, cid, picks=None, *, automatic=False):
    answers, prompts = [], []
    before = load(path, mid).state.model_dump(mode='json')
    for _ in range(10):
        combat, table = cold(path)
        menu = table.state(mid)['menu']
        if automatic:
            # Fake only primary-action selection; native automatic rider/skill
            # decisions still run, with no model or embedding transport.
            from combat.gate4_adapters import ManualControllerAdapter
            native = combat.controller
            combat.controller = ManualControllerAdapter(lambda context: (cid, ()),
                reaction_chooser=lambda context: native.choose_reaction(context).decision)
            result = table.auto_step(mid, 0, answers)
        else:
            result = table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, answers)
        if result['status'] == 'COMMITTED':
            load(path, mid)
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        assert load(path, mid).state.model_dump(mode='json') == before
        p = result['reaction']
        prompts.append(p)
        rid = p['context']['reaction_source_id']
        pick = (picks or {}).get(rid, (p.get('choice', {}).get('options') or [{'id': None}])[0]['id'])
        answers.append({**p['context'], 'selection': 'USE' if pick else 'DECLINE',
                        **({'option_ids': [pick]} if pick else {})})
    raise AssertionError('Choice did not settle')


def advance(path, mid, aid):
    for _ in range(8):
        _, table = cold(path)
        menu = table.state(mid)['menu']
        if menu['actor_id'] == aid:
            return
        if menu.get('control_mode') == 'LOCAL_AUTO':
            table.auto_step(mid, 0)
        else:
            commit(path, mid, menu['end_turn'])
    raise AssertionError('No native turn')


def holds(e):
    return [c for c in e.state.actors[FOE].conditions.values()
            if c.condition_id == 'condition:typed.grappled']


def soaked(e):
    return [c for c in e.state.actors[FOE].conditions.values()
            if c.condition_id.startswith('condition:typed.mark.soaked.')]


def whip_soaked(e):
    return [c for c in soaked(e) if c.data.get('parent_hold')]


def test_source_pin():
    text = json.loads((ROOT / DEPENDENCIES[0]).read_text())[WHIP]
    assert hashlib.sha256(text.encode()).hexdigest() == '5b49859e8020594ad772929e2126db24d2384ccc3e6e5385bee6287a7e3d78d5'


@pytest.mark.parametrize('case', ['hold', 'decline', 'empty', 'save', 'miss', 'unowned'])
def test_real_lash_payment_save_and_owner_deadline(tmp_path, case):
    mid = setup(tmp_path, own=case != 'unowned',
                save=100 if case in ('save', 'empty') else -100, miss=case == 'miss')
    if case == 'empty':
        # Deplete through real paid hits and ordinary turns, never by editing
        # a fight resource, receipt, budget, or the character's CP maximum.
        for _ in range(8):
            if load(tmp_path, mid).state.actors[OWNER].resources[CP] == 0:
                break
            commit(tmp_path, mid, candidate(tmp_path, mid, 'Water Lash', FOE),
                   {'choice:needle.water_whip': 'use', 'choice:needle.water_lash_shift': None})
            advance(tmp_path, mid, FOE)
            advance(tmp_path, mid, OWNER)
        assert load(tmp_path, mid).state.actors[OWNER].resources[CP] == 0
    before_cp = load(tmp_path, mid).state.actors[OWNER].resources[CP]
    start = len(load(tmp_path, mid).events)
    prompts = commit(tmp_path, mid, candidate(tmp_path, mid, 'Water Lash', FOE),
                     {'choice:needle.water_whip': None if case == 'decline' else 'use',
                      'choice:needle.water_lash_shift': None})
    e = load(tmp_path, mid)
    attack = next(v for v in e.events[start:] if v.event_type == 'ATTACK_ROLLED' and v.actor_id == OWNER)
    assert attack.payload['provisional_hit'] is (case != 'miss')
    saves = [v for v in e.events[start:] if v.event_type == 'SAVE_ROLLED' and v.actor_id == FOE]
    assert len(saves) == int(case in ('hold', 'save'))
    if saves:
        assert saves[0].payload['reason'].endswith(':STR') and saves[0].payload['dc'] == 9
        assert saves[0].payload['success'] is (case == 'save')
    paid = case in ('hold', 'save')
    assert e.state.actors[OWNER].resources[CP] == before_cp - int(paid)
    assert bool(holds(e)) is (case == 'hold')
    # Lash independently Soaks on every hit, including decline/save/no CP.
    assert bool(soaked(e)) is (case != 'miss')
    assert bool(whip_soaked(e)) is (case == 'hold')
    whip_prompts = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.water_whip']
    assert bool(whip_prompts) is (case in ('hold', 'decline', 'save'))
    if whip_prompts:
        assert whip_prompts[0]['context']['reactor_id'] == OWNER
        assert 'Water Whip' in str(whip_prompts[0]) and 'Mara' in str(whip_prompts[0])
    if case != 'hold':
        return
    grip = holds(e)[0]
    assert grip.data['escape_dc'] == 9 and 'reach_ft' not in grip.data
    assert grip.expires_on == 'END_OF_SOURCE_TURN_AT:2'
    assert whip_soaked(e)[0].data['parent_hold'] == grip.instance_id
    assert len(soaked(e)) == 2  # independent Lash mark and hold-dependent Whip
    advance(tmp_path, mid, FOE)
    assert holds(load(tmp_path, mid))
    advance(tmp_path, mid, OWNER)
    assert holds(load(tmp_path, mid)) and soaked(load(tmp_path, mid))
    commit(tmp_path, mid, cold(tmp_path)[1].state(mid)['menu']['end_turn'])
    assert not holds(load(tmp_path, mid)) and not soaked(load(tmp_path, mid))


@pytest.mark.parametrize('ability', ['STR', 'DEX'])
@pytest.mark.parametrize('success', [False, True])
@pytest.mark.parametrize('dc,cl', [(9, 5), (13, 17)])
def test_target_owned_escape_action_raw_dc_and_linked_soaked(tmp_path, ability, success, dc, cl):
    mid = setup(tmp_path, skill=100 if success else -100, dc=dc, cl=cl)
    commit(tmp_path, mid, candidate(tmp_path, mid, 'Water Lash', FOE))
    damage = next(v for v in reversed(load(tmp_path, mid).events)
                  if v.event_type == 'DAMAGE_ROLLED' and v.actor_id == OWNER)
    base_count = 4 if cl >= 17 else 2 if cl >= 5 else 1
    count = base_count * (2 if damage.payload.get('critical') else 1)
    assert damage.payload['expression'] == f'{count}d8-1'
    advance(tmp_path, mid, FOE)
    prompts = commit(tmp_path, mid, candidate(tmp_path, mid, 'Escape grapple', FOE),
                     {'choice:needle.physical_escape_skill': ability})
    e = load(tmp_path, mid)
    assert prompts and prompts[0]['context']['reactor_id'] == FOE
    assert {o['id'] for o in prompts[0]['choice']['options']} == {'STR', 'DEX'}
    assert 'Water Whip' in str(prompts[0]) and 'Mara' in str(prompts[0])
    assert not e.state.actors[FOE].action_available
    check = next(v for v in reversed(e.events) if v.event_type == 'CHECK_ROLLED' and v.actor_id == FOE)
    assert check.payload['dc'] == dc and check.payload['success'] is success
    assert check.payload['ability'] == ability
    assert check.payload['skill'] == ('Athletics' if ability == 'STR' else 'Acrobatics')
    assert bool(holds(e)) is (not success)
    assert bool(whip_soaked(e)) is (not success)
    assert len(soaked(e)) == (1 if success else 2)  # preserve Lash's own mark


@pytest.mark.parametrize('automatic', [False, True])
def test_automatic_seats_keep_paid_rider_and_target_escape_reachable(tmp_path, automatic):
    mid = setup(tmp_path)
    for aid in (OWNER, FOE):
        cold(tmp_path)[0].set_controller_mode(mid, actor_id=aid,
            controller_mode='LOCAL_AUTO' if automatic else 'MANUAL')
    cid = candidate(tmp_path, mid, 'Water Lash', FOE)
    prompts = commit(tmp_path, mid, cid, automatic=automatic)
    assert bool(prompts) is (not automatic)
    e = load(tmp_path, mid)
    assert holds(e) and whip_soaked(e) and e.state.actors[OWNER].resources[CP] == 2
    advance(tmp_path, mid, FOE)
    cid = candidate(tmp_path, mid, 'Escape grapple', FOE)
    prompts = commit(tmp_path, mid, cid, automatic=automatic)
    assert bool(prompts) is (not automatic)
    e = load(tmp_path, mid)
    assert not holds(e) and not whip_soaked(e) and soaked(e)
    assert not e.state.actors[FOE].action_available
