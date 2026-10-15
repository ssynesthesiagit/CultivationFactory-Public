"""Printed Sword effects through table/session intents and cold reloads."""
import json
import shutil
import zipfile
from pathlib import Path
import pytest
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import ButtonStore
from combat.typed_executor import bears_mark
from combat.ext import resistance_bypass, regeneration
from tests import h1_support as H
from tests import test_ocf8_sword_core as S

ROOT = Path(__file__).resolve().parents[1]
FATAL = 'TAL_SWORD_FATAL_STRIKE'
HEAVEN = 'TAL_SWORD_HEAVEN_CUTTING_CRESCENT'
PROJECTS = ['a2a00001', 'a2a00002', 'a2a00003', 'a2a00004']
IDS = ['actor:factory.' + p for p in PROJECTS]


def fixture(tmp_path, seed, *, dc=100, primary='Qi', fatal=True, many=False, hp=None, resistant=False, bundle_transform=None):
    projects = PROJECTS if many else PROJECTS[:2]
    bundles = []
    for i, project in enumerate(projects):
        mids = [HEAVEN, S.LIFE_SEVERING, *S.SWORD_BASES, *([FATAL] if fatal else [])] if i == 0 else [S.MARROW, 'LIFE_BASE_MEND_THE_PULSE']
        if i == 1 and resistant:
            mids += ['TAL_SWORD_SWORD_SOVEREIGN_INCARNATION', 'TAL_SWORD_HEART_OF_THE_SWORD']
        doc = H.sheet(mids, cl=15, dc=dc if i == 0 else 16, primary=primary if i == 0 else 'Stamina', key='STR', score=18 if i == 0 else 10)
        doc['identity'].update(display_name=['Swordsman', 'First foe', 'Second foe', 'Ally'][i], proficiency_bonus=5)
        stats = doc['ability_scores_and_statistics']
        stats['initiative'] = {'bonus': 100 if i == 0 else -10 * i}
        stats['technique_attack_bonus'] = 100
        stats['hit_points']['maximum'] = hp or (400 if many else 180)
        stats['primary_resource']['maximum'] = 100
        doc['equipment'] = [{'starting_kit': {'items': [{'item_id': S.JIAN, 'name': 'Jian', 'quantity': 1}]}}]
        if i == 0:
            doc['identity']['path'] = 'Qi Cultivation'
            doc['path_and_subpath'] = {'path_record_ids': ['tianxia.path.qi_cultivation']}
        else:
            doc['identity']['path'] = 'Body Refining'
            bases = doc.get('spheres_and_talents', {}).get('automatic_sphere_component_record_ids', [])
            if S.BEYOND_HAND_ID in bases:
                bases.remove(S.BEYOND_HAND_ID)
            doc['path_and_subpath'].update(path_record_ids=['tianxia.path.body_refining'], subpath_record_ids=['tianxia.subpath.body.bone_monarch'])
        directory = tmp_path / 'portable_characters' / project
        directory.mkdir(parents=True)
        with zipfile.ZipFile(directory / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(project, {'mode': 'ask'}, set())
        bundles.append(compile_character(doc, actor_id=IDS[i], reaction_plan={'ask': True}))
    if bundle_transform:
        bundle_transform(bundles)
    combat = CombatService(ROOT, tmp_path)
    arena = combat.tabletop_maps.save({'display_name': 'Sword second pass yard', 'width_squares': 30, 'height_squares': 12,
        'walls': [], 'starts': {'team1': [[3, 4]], 'team2': [[5, 4], [7, 4], [9, 4]]}})
    ids = IDS[:len(projects)]
    mid = combat._finish_factory_match(bundles, ids,
        {aid: 'team:a' if i in (0, 3) else 'team:b' for i, aid in enumerate(ids)},
        {aid: {'x': [3, 4, 6, 8][i], 'y': 4} for i, aid in enumerate(ids)},
        combat.factory_arenas()['battlefield:map.' + arena['map_id']], [ids[0]], ids[1:3],
        control_modes={aid: 'MANUAL' for aid in ids}, match_seed=seed, maximum_rounds=30, display_name=seed)['match_id']
    table = TabletopService(combat, tmp_path)
    ready(table, mid)
    assert not any(g['label'] == 'Fatal Strike damage' for g in table.state(mid)['menu']['actions'])
    return combat, table, mid


def reload(combat, tmp_path, mid):
    old = combat._load_session(mid)
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert old.engine.state.model_dump(mode='json') == fresh.engine.state.model_dump(mode='json')
    assert fresh.verify()['status'] == 'PASS'
    assert fresh.mechanical.replay()['status'] == 'PASS'
    return fresh.engine


def end(table, mid):
    v = table.state(mid)
    assert S._press(table, mid, v['menu'], v)['status'] == 'COMMITTED'


def ready(table, mid):
    for _ in range(30):
        v = table.state(mid); menu = v['menu']
        setup = next((g for g in menu.get('actions') or [] if g['label'] == 'Finish fight setup'), None)
        if setup:
            assert S._press(table, mid, menu, v, candidate=setup['options'][0]['candidate_id'])['status'] == 'COMMITTED'
        elif menu['actor_id'] != IDS[0]:
            end(table, mid)
        else:
            return
    pytest.fail('owner turn not reached')


def next_owner(table, mid):
    end(table, mid)
    ready(table, mid)


def press(table, mid, name, *, target=IDS[1], want=None, decline_fatal=False, destination=None):
    v = table.state(mid)
    if name == 'Move':
        option = next(o for o in v['menu']['moves'] if (o['destination']['x'], o['destination']['y']) == destination)
    else:
        group = next(g for g in v['menu']['actions'] if g['label'] == name)
        option = next((o for o in group['options'] if target in o.get('target_ids', ())), group['options'][0])
        if name == 'Heaven-Cutting Crescent':
            e = table.combat._load_session(mid).engine
            c = next(c for c in e.legal_candidates() if c.display_name.startswith(name) and c.destination and c.destination.x > 3 and c.destination.y == 4)
            option = {'candidate_id': c.candidate_id}
    answers, prompts = [], []
    for _ in range(12):
        result = table.act(mid, option['candidate_id'], v['menu']['decision_id'], v['menu']['state_version'], v['last_sequence'], answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return prompts
        p = result['reaction']; prompts.append(p)
        options = (p.get('choice') or {}).get('options') or []
        choice = next((o for o in options if want and want in o['label']), options[0] if options else None)
        decline = p['reaction'] == 'Life-Severing Sword' or (decline_fatal and p['reaction'] == 'Fatal Strike')
        answers.append({**p['context'], 'selection': 'DECLINE' if decline else 'USE', 'option_ids': [] if decline or choice is None else [choice['id']]})
    pytest.fail('unbounded choices')


def bloodied(combat, table, mid):
    for _ in range(15):
        e = combat._load_session(mid).engine; t = e.state.actors[IDS[1]]
        if 0 < t.current_hp <= t.maximum_hp // 2 and bears_mark(t, IDS[0], 'Sword Intent'):
            return
        prompts = press(table, mid, 'Sword Beyond Hand', want='Slashing', decline_fatal=True)
        assert not any(p['reaction'] == 'Fatal Strike' for p in prompts), 'crossing half HP must not qualify the same hit'
        t = combat._load_session(mid).engine.state.actors[IDS[1]]
        assert t.active
        if t.current_hp <= t.maximum_hp // 2:
            return
        next_owner(table, mid)
    pytest.fail('target did not become bloodied')


def retain(combat, mid, label):
    source = combat._load_session(mid).store.match_dir
    folder = source.parent / 'test-exports' / label
    folder.parent.mkdir(exist_ok=True)
    shutil.copytree(source, folder)
    return folder


@pytest.mark.parametrize('dc,primary,payment', [(100, 'Qi', 'Qi'), (-40, 'Qi', 'Qi'), (100, 'Stamina', 'Stamina'), (100, 'Qi', 'Martial Focus')])
def test_fatal_save_branches_payment_healing_and_exact_expiry(tmp_path, dc, primary, payment):
    combat, table, mid = fixture(tmp_path, f'A2-FATAL-100-{payment}', dc=dc, primary=primary)
    bloodied(combat, table, mid)
    e = reload(combat, tmp_path, mid); before = dict(e.state.actors[IDS[0]].resources); start = len(e.events)
    end(table, mid)
    assert table.state(mid)['menu']['actor_id'] == IDS[1]
    prompts = press(table, mid, 'Move', destination=(6, 4), want=payment)
    assert any(p['reaction'] == 'Fatal Strike' for p in prompts), prompts
    e = reload(combat, tmp_path, mid); t = e.state.actors[IDS[1]]
    assert t.active
    damage_rolls = [r for r in e.rolls if r.expression.startswith(('6d10', '12d10'))]
    assert len(damage_rolls) == 1
    pool = 'resource:core.' + ('martial_focus' if payment == 'Martial Focus' else payment.lower())
    assert before[pool] - e.state.actors[IDS[0]].resources[pool] == (1 if payment == 'Martial Focus' else 8)
    saves = [event for event in e.events[start:] if event.event_type == 'SAVE_ROLLED' and event.source_definition_id == FATAL]
    assert len(saves) == 1 and saves[0].payload['success'] == (dc < 0)
    mods = [m for m in t.modifiers.values() if m.target_field == 'healing_reduction' and m.source_definition_id == FATAL]
    assert len(mods) == 1 and mods[0].value == ('half' if dc < 0 else 'none')
    assert any(c.condition_id == regeneration.RECORD for c in t.conditions.values()) == (dc > 0)
    assert any(c.condition_id == 'condition:typed.reaction_denied' for c in t.conditions.values())
    prior = reload(combat, tmp_path, mid)
    hp = prior.state.actors[IDS[1]].current_hp
    roll_start = len(prior.rolls)
    press(table, mid, 'Mend the Pulse', target=IDS[1])
    e = reload(combat, tmp_path, mid)
    healing = [r.total for r in e.rolls[roll_start:] if r.reason.startswith('HEALING:')]
    assert len(healing) == 1
    assert e.state.actors[IDS[1]].current_hp - hp == (0 if dc > 0 else healing[0] // 2)
    press(table, mid, 'Marrow Regeneration', target=IDS[1])
    e = reload(combat, tmp_path, mid)
    if dc > 0: assert e.state.actors[IDS[1]].current_hp == hp
    end(table, mid); ready(table, mid)
    e = reload(combat, tmp_path, mid); t = e.state.actors[IDS[1]]
    assert any(m.source_definition_id == FATAL and m.target_field == 'healing_reduction' for m in t.modifiers.values())
    assert not any(c.condition_id == 'condition:typed.reaction_denied' for c in t.conditions.values())
    if dc > 0: assert any(c.condition_id == regeneration.RECORD for c in t.conditions.values())
    # No second paid use is offered across the next owner-turn reset.
    assert any(c.condition_id == 'condition:typed.sword_fatal_strike_used' for c in e.state.actors[IDS[0]].conditions.values())
    end(table, mid)
    e = reload(combat, tmp_path, mid); t = e.state.actors[IDS[1]]
    assert not any(m.source_definition_id == FATAL and m.target_field == 'healing_reduction' for m in t.modifiers.values())
    assert not any(c.condition_id == regeneration.RECORD for c in t.conditions.values())
    hp = t.current_hp
    press(table, mid, 'Marrow Regeneration', target=IDS[1])
    e = reload(combat, tmp_path, mid)
    assert e.state.actors[IDS[1]].current_hp > hp
    retain(combat, mid, 'fatal-' + payment + str(dc))


@pytest.mark.parametrize('dc', [100, -40])
def test_heaven_chooses_exactly_one_failed_enemy_and_preserves_scope(tmp_path, dc):
    combat, table, mid = fixture(tmp_path, f'A2-HEAVEN-{dc}', dc=dc, many=True)
    prompts = press(table, mid, 'Heaven-Cutting Crescent', want='Second foe')
    e = reload(combat, tmp_path, mid)
    questions = [p for p in prompts if p['reaction'] == 'Heaven-Cutting Crescent']
    if dc < 0:
        assert not questions
        assert not any(resistance_bypass.records(e, a) for a in e.state.actors.values())
    else:
        assert len(questions) == 1, prompts
        assert {o['label'] for o in questions[0]['choice']['options']} == {'First foe', 'Second foe'}
        t = e.state.actors[IDS[2]]
        assert len(resistance_bypass.records(e, t)) == 1
        assert not resistance_bypass.records(e, e.state.actors[IDS[1]])
        assert not resistance_bypass.records(e, e.state.actors[IDS[3]])
        assert resistance_bypass.ignores_chosen_creature_resistance(e, 'SLASHING', {'sphere': S.SWORD_SPHERE}, IDS[0], t)
        for kind, sphere, source in [('FORCE', S.SWORD_SPHERE, IDS[0]), ('SLASHING', 'tianxia.sphere.life', IDS[0]), ('SLASHING', S.SWORD_SPHERE, IDS[3])]:
            assert not resistance_bypass.ignores_chosen_creature_resistance(e, kind, {'sphere': sphere}, source, t)
    assert e.state.actors[IDS[3]].current_hp == e.state.actors[IDS[3]].maximum_hp
    for _ in range(4): end(table, mid)
    ready(table, mid)
    e = reload(combat, tmp_path, mid)
    assert not any(resistance_bypass.records(e, a) for a in e.state.actors.values())
    retain(combat, mid, 'heaven-' + str(dc))


@pytest.mark.parametrize('own_fatal', [True, False])
def test_fatal_decline_or_nonowner_spends_nothing_and_leaves_no_use(tmp_path, own_fatal):
    combat, table, mid = fixture(tmp_path, 'A2-FATAL-100-Qi', fatal=own_fatal)
    bloodied(combat, table, mid)
    e = reload(combat, tmp_path, mid)
    resources = dict(e.state.actors[IDS[0]].resources)
    end(table, mid)
    prompts = press(table, mid, 'Move', destination=(6, 4), decline_fatal=True)
    assert any(p['reaction'] == 'Fatal Strike' for p in prompts) == own_fatal
    e = reload(combat, tmp_path, mid)
    assert e.state.actors[IDS[0]].resources == resources
    assert not any(c.condition_id == 'condition:typed.sword_fatal_strike_used' for c in e.state.actors[IDS[0]].conditions.values())
    assert not any(m.source_definition_id == FATAL for m in e.state.actors[IDS[1]].modifiers.values())
    retain(combat, mid, 'decline-' + str(own_fatal))


def test_fatal_bloodied_but_unmarked_hit_does_not_pay_for_a_new_mark(tmp_path):
    combat, table, mid = fixture(tmp_path, 'A2-FATAL-100-Qi')
    bloodied(combat, table, mid)
    next_owner(table, mid)
    e = reload(combat, tmp_path, mid)
    assert not bears_mark(e.state.actors[IDS[1]], IDS[0], 'Sword Intent')
    resources = dict(e.state.actors[IDS[0]].resources)
    prompts = press(table, mid, 'Sword Beyond Hand', want='Slashing')
    assert not any(p['reaction'] == 'Fatal Strike' for p in prompts)
    e = reload(combat, tmp_path, mid)
    assert e.state.actors[IDS[0]].resources == resources
    assert bears_mark(e.state.actors[IDS[1]], IDS[0], 'Sword Intent')
    retain(combat, mid, 'unmarked')



def test_crescent_bypass_applies_to_fatal_talent_damage_on_a_weapon_reaction(tmp_path):
    combat, table, mid = fixture(tmp_path, 'A2-FATAL-100-Qi', hp=400, resistant=True)
    bloodied(combat, table, mid)
    next_owner(table, mid)
    press(table, mid, 'Heaven-Cutting Crescent', want='First foe')
    end(table, mid)
    press(table, mid, 'Sword-Sovereign Incarnation', target=IDS[1])
    e = reload(combat, tmp_path, mid)
    assert resistance_bypass.records(e, e.state.actors[IDS[1]])
    start = len(e.events)
    prompts = press(table, mid, 'Move', destination=(6, 4), want='Qi')
    assert any(p['reaction'] == 'Fatal Strike' for p in prompts)
    e = reload(combat, tmp_path, mid)
    packets = [event for event in e.events[start:] if event.event_type == 'DAMAGE_COMMITTED'
               and event.payload.get('display_source_id') == FATAL]
    assert len(packets) == 1
    assert packets[0].payload['damage_type'] == 'SLASHING'
    assert packets[0].payload['reduced_to'] == packets[0].payload['rolled_or_pending_damage']
    retain(combat, mid, 'crescent-fatal-resistance')
