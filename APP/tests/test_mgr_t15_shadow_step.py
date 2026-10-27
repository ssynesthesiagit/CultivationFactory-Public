"""Source-owned Shadow Step: portable import -> table choice -> cold reload/replay.

Initial portable sheets are source-backed CL3/CL6 Ninpo builds. No success
receipt, condition, action or plug-in call is installed by these scenarios.
"""
import hashlib
import json
import zipfile

import pytest

from combat import carry, motion
from combat.ext.hand_occupancy import weapon_grips, occupancy
from combat.ext.tabik_ninpo import SHADOW_STEP, STEP_OA, STEP_STEALTH
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService, CombatServiceError
from combat.tabletop import ButtonStore, TabletopError
from combat.tabletop_service import TabletopService
from combat.typed_executor import check_modes
from tests.h1_support import ROOT, sheet

ME, FOE = 'actor:factory.15150001', 'actor:factory.15150002'
PARENT = 'tianxia.subpath.qi.ninpo_adept'
VEIL = PARENT + '.feature.smoke_veil'
CHOICE = 'choice:needle.shadow_step_item'
SOURCE = 'non_sphere_authority/authority/Tianxia_Subpath_Tradition_Index_Master_P2B.json'
# Dynamic compiler inputs: literal declarations keep the public export honest.
INPUTS = ('authority/Tianxia_Typed_Mechanics_Authority_R1.json',
          'authority/Tianxia_Forged_Technique_Authority_R1.json',
          'authority/Tianxia_Immortal_Art_Authority_R1.json',
          'authority/Tianxia_Mundane_Equipment_Catalog_R1.json',
          'authority/Tianxia_Starting_Kit_Authority_R1.json')
GEAR = ['tianxia.mortal.weapon.bi_shou', 'tianxia.mortal.tool.calligrapher_s_supplies',
        'tianxia.mortal.focus.qi_focus_crystal']


def setup(tmp_path, *, cl=6, qi=30, owns=True, foe_features=(), owner_extra=(), foe_at=14, second_foe=False,
          gear=None, treasure=()):
    source = json.loads((ROOT / SOURCE).read_text())
    parent = next(r for r in source['entries'] if r['canonical_id'] == PARENT)
    assert parent['owning_path_id'] == 'tianxia.path.qi_cultivation'
    features = [r['canonical_id'] for r in parent['feature_progression'] if r['granted_at_cl'] <= cl]
    docs = [sheet([*(features if owns else []), *owner_extra], cl=cl, name='Ninpo traveller'),
            sheet(list(foe_features), cl=6, dc=100, name='Watchful guard')]
    if cl == 3:
        # The guard's real Smoke Veil supplies concealment; CL3 grants Step only.
        docs[1] = sheet([VEIL], cl=6, name='Smoke keeper')
        docs.append(sheet([], cl=3, name='Distant opponent'))
    elif second_foe:
        docs.append(sheet([], cl=6, name='Second guard'))
    docs[0]['equipment'] = [{'starting_kit': {'items': [
        {'item_id': key, 'quantity': 1} for key in (GEAR if gear is None else gear)],
        'resolved_treasure_purchases': {'wondrous': list(treasure)}}}]
    for doc in docs[1:]:
        doc['equipment'] = [{'starting_kit': {'items': [{'item_id': GEAR[0], 'quantity': 1}]}}]
    docs[0]['path_and_subpath'].update(path_record_ids=['tianxia.path.qi_cultivation'], subpath_record_ids=[PARENT]) if owns else None
    bundles = []
    svc = CombatService(ROOT, tmp_path)
    ids = [ME, FOE] + (['actor:factory.15150003'] if len(docs) == 3 else [])
    for i, (aid, doc) in enumerate(zip(ids, docs)):
        doc['ability_scores_and_statistics']['primary_resource']['maximum'] = qi if i == 0 else 30
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 500
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(aid.removeprefix('actor:factory.'), {'mode': 'ask'}, {'opportunity_attack'})
        bundles.append(compile_character(svc._factory_owner_sheet(aid.removeprefix('actor:factory.')), actor_id=aid,
                                         reaction_plan={'ask': True}))
    arena = svc.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    teams = {ME: 'team:a', FOE: 'team:a' if cl == 3 else 'team:b', **({ids[2]: 'team:b'} if len(docs) == 3 else {})}
    positions = {ME: {'x': 3, 'y': 6}, FOE: {'x': 5 if cl == 3 else foe_at, 'y': 6},
                 **({ids[2]: {'x': 14, 'y': 6} if cl == 3 else {'x': 5, 'y': 7}} if len(docs) == 3 else {})}
    mid = svc._finish_factory_match(bundles, ids, teams, positions, arena, [ME], ids[1:],
        control_modes={aid: 'MANUAL' for aid in ids}, match_seed='MGR-T15-SHADOW',
        display_name='Shadow Step source audit', maximum_rounds=12)['match_id']
    table = TabletopService(svc, tmp_path)
    turn(table, mid, FOE if cl == 3 else ME)
    return svc, table, mid


def press(table, mid, cid, answers=()):
    menu = table.state(mid)['menu']
    return table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, list(answers))


def turn(table, mid, actor):
    for _ in range(8):
        menu = table.state(mid)['menu']
        setup_group = next((g for g in menu['actions'] if g['label'] == 'Finish fight setup'), None)
        if not setup_group and menu['actor_id'] == actor:
            return
        cid = setup_group['options'][0]['candidate_id'] if setup_group else menu['end_turn']
        assert press(table, mid, cid)['status'] == 'COMMITTED'
    raise AssertionError('turn did not advance')


def group(table, mid, label):
    return next((g for g in table.state(mid)['menu']['actions'] if g['label'] == label), None)


def act(table, mid, cid, choose=lambda p: None):
    answers, prompts = [], []
    for _ in range(10):
        result = press(table, mid, cid, answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return prompts
        p = result['reaction']
        prompts.append(p)
        picked = choose(p)
        answers.append({**p['context'], 'selection': 'USE' if picked else 'DECLINE', 'option_ids': picked or []})
    raise AssertionError('too many choices')


def cold(tmp_path, mid):
    svc = CombatService(ROOT, tmp_path)
    session = svc._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def place(table, mid, label, x=4, y=6):
    """Select a real native square through either eager or deferred map menus."""
    row = group(table, mid, label)
    assert row
    if row.get('placement_picker'):
        return act(table, mid, row['options'][0]['candidate_id'],
                   lambda p: [f'cell:{x},{y},0']
                   if p['context']['reaction_source_id'] == 'choice:placement_menu.square' else None)
    cid = next(o['candidate_id'] for o in row['options'] if o.get('destination') == {'x': x, 'y': y})
    return act(table, mid, cid)


def veil(table, mid):
    place(table, mid, 'Smoke Veil')
    assert press(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    turn(table, mid, ME)


def step(table, mid, *, item=None, decline=False, destination='cell:4,6'):
    row = group(table, mid, 'Shadow Step')
    assert row and row['destination_choice']
    def choose(p):
        source = p['context']['reaction_source_id']
        if source == 'choice:needle.teleport_destination':
            return None if decline else [destination]
        if source == CHOICE and item is not None:
            return [next(o['id'] for o in p['choice']['options'] if item in o['id'])]
        return None
    return act(table, mid, row['options'][0]['candidate_id'], choose)


def test_source_hash_and_source_owned_initial_import(tmp_path):
    text = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())[SHADOW_STEP]
    assert hashlib.sha256(text.encode()).hexdigest() == '3f3b3e6bb8933b8d6da3c0de138393f16f9ddbbb9db654db3480751295836347'
    _, table, mid = setup(tmp_path, cl=3)
    veil(table, mid)
    # The CL3 owner uses another creature's real smoke, not an early CL6 grant.
    engine = cold(tmp_path, mid)
    assert all(a.display_name != 'Smoke Veil' for a in engine.action_catalog.values() if a.owner_id == ME)
    step(table, mid)
    actor = cold(tmp_path, mid).state.actors[ME]
    assert actor.position == Position(x=4, y=6)
    assert actor.resources['resource:core.qi'] == 29


@pytest.mark.parametrize('item', [None, GEAR[0] + '|carried', GEAR[0] + '|hand:', GEAR[1] + '|hand:', GEAR[2] + '|hand:'])
def test_one_real_optional_item_and_benefits_cold_replay(tmp_path, item):
    _, table, mid = setup(tmp_path)
    veil(table, mid)
    if item == GEAR[0] + '|hand:':
        stow = next(g for g in table.state(mid)['menu']['actions'] if g['label'].startswith('Stow '))
        act(table, mid, stow['options'][0]['candidate_id'])
    before = cold(tmp_path, mid)
    qi = before.state.actors[ME].resources['resource:core.qi']
    gear = dict(weapon_grips(before, before.state.actors[ME]))
    prompts = step(table, mid, item=item)
    assert len([p for p in prompts if p['context']['reaction_source_id'] == CHOICE]) == 1
    engine = cold(tmp_path, mid)
    actor = engine.state.actors[ME]
    assert actor.position == Position(x=4, y=6)
    assert actor.resources['resource:core.qi'] == qi - 1
    assert actor.action_available and not actor.bonus_action_available
    assert {STEP_OA, STEP_STEALTH} <= {c.condition_id for c in actor.conditions.values()}
    assert check_modes(actor, 'DEX', 'Stealth', engine=engine) == {'ADVANTAGE'}
    assert group(table, mid, 'Shadow Step') is None
    if item is None:
        assert weapon_grips(engine, actor) == gear
    elif '|carried' in item:
        assert not weapon_grips(engine, actor)
    else:
        key = item.split('|')[0]
        assert carry.owned_item_location(actor, key).startswith('hand:')
        if key == GEAR[0]:
            assert weapon_grips(engine, actor)
        else:
            assert any('object:' + key in occupants for occupants in occupancy(engine, actor).values())
    # No action is introduced; existing attack/proficiency parameters are unchanged.
    assert {key: (action.attack_bonus, action.parameters) for key, action in engine.action_catalog.items()} == {
        key: (action.attack_bonus, action.parameters) for key, action in before.action_catalog.items()}


def test_next_turn_can_stow_the_exact_previously_drawn_tool(tmp_path):
    _, table, mid = setup(tmp_path)
    veil(table, mid)
    step(table, mid, item=GEAR[1] + '|hand:')
    assert press(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    turn(table, mid, ME)
    # The second landing must differ from the first.
    cid = group(table, mid, 'Shadow Step')['options'][0]['candidate_id']
    def choose(p):
        source = p['context']['reaction_source_id']
        if source == 'choice:needle.teleport_destination':
            return ['cell:3,6']
        if source == CHOICE:
            return [next(o['id'] for o in p['choice']['options'] if GEAR[1] + '|carried' in o['id'])]
        return None
    act(table, mid, cid, choose)
    engine = cold(tmp_path, mid)
    actor = engine.state.actors[ME]
    assert carry.owned_item_location(actor, GEAR[1]) == 'carried'
    assert all('object:' + GEAR[1] not in owners for owners in occupancy(engine, actor).values())


def test_pending_item_choice_has_no_partial_commit_and_survives_fresh_service(tmp_path):
    _, table, mid = setup(tmp_path)
    veil(table, mid)
    before = cold(tmp_path, mid).state.model_dump(mode='json')
    cid = group(table, mid, 'Shadow Step')['options'][0]['candidate_id']
    p = press(table, mid, cid)['reaction']
    answer = {**p['context'], 'selection': 'USE', 'option_ids': ['cell:4,6']}
    result = press(table, mid, cid, [answer])
    assert result['status'] == 'REACTION_REQUIRED'
    p = result['reaction']
    assert p['context']['reaction_source_id'] == CHOICE
    assert cold(tmp_path, mid).state.model_dump(mode='json') == before
    answer2 = {**p['context'], 'selection': 'USE', 'option_ids': [
        next(o['id'] for o in p['choice']['options'] if GEAR[1] + '|hand:' in o['id'])]}
    fresh = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert press(fresh, mid, cid, [answer, answer2])['status'] == 'COMMITTED'
    assert carry.owned_item_location(cold(tmp_path, mid).state.actors[ME], GEAR[1]).startswith('hand:')


def test_declining_destination_never_grants_after_teleport_benefits(tmp_path):
    _, table, mid = setup(tmp_path)
    veil(table, mid)
    prompts = step(table, mid, decline=True)
    actor = cold(tmp_path, mid).state.actors[ME]
    assert actor.position == Position(x=3, y=6)
    assert not {STEP_OA, STEP_STEALTH}.intersection(c.condition_id for c in actor.conditions.values())
    assert not actor.turn_flags.get('shadow_stepped')
    assert not any(p['context']['reaction_source_id'] == CHOICE for p in prompts)


def test_next_stealth_is_consumed_by_real_hide_and_unused_benefit_expires(tmp_path):
    _, table, mid = setup(tmp_path)
    veil(table, mid)
    step(table, mid)
    row = group(table, mid, 'Hide')
    assert row
    act(table, mid, row['options'][0]['candidate_id'])
    engine = cold(tmp_path, mid)
    checks = [e for e in engine.events if e.event_type == 'CHECK_ROLLED' and e.actor_id == ME]
    assert checks[-1].payload['actor']['mode'] == 'ADVANTAGE'
    assert not any(c.condition_id == STEP_STEALTH for c in engine.state.actors[ME].conditions.values())
    assert 'ADVANTAGE' not in check_modes(engine.state.actors[ME], 'DEX', 'Stealth', engine=engine)
    assert press(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    turn(table, mid, ME)
    step(table, mid, destination='cell:3,6')
    assert press(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    engine = cold(tmp_path, mid)
    assert not any(c.condition_id == STEP_STEALTH for c in engine.state.actors[ME].conditions.values())
    assert any(c.condition_id == STEP_OA for c in engine.state.actors[ME].conditions.values())
    turn(table, mid, ME)
    assert not any(c.condition_id == STEP_OA for c in cold(tmp_path, mid).state.actors[ME].conditions.values())


def test_both_concealment_ends_range_occupied_and_unknown_destinations(tmp_path):
    _, table, mid = setup(tmp_path)
    assert group(table, mid, 'Shadow Step') is None
    veil(table, mid)
    engine = cold(tmp_path, mid)
    actor = engine.state.actors[ME]
    row = group(table, mid, 'Shadow Step')
    assert row
    for option in row['options']:
        cell = Position(**option['destination'])
        assert cell != actor.position and motion.obscured_at(engine, cell)
        assert engine.grid.distance_ft(actor.position, cell) <= 15
        assert cell not in engine._occupied_cells_except(ME)
        assert engine._line_of_sight_actor_to_cell(actor, cell)
    cid = row['options'][0]['candidate_id']
    p = press(table, mid, cid)['reaction']
    illegal = {**p['context'], 'selection': 'USE', 'option_ids': ['cell:999,999']}
    with pytest.raises((CombatServiceError, TabletopError)):
        press(table, mid, cid, [illegal])
    assert cold(tmp_path, mid).state.actors[ME].position == actor.position


def test_no_owner_is_inert(tmp_path):
    _, table, mid = setup(tmp_path, owns=False)
    assert group(table, mid, 'Shadow Step') is None
    assert not any(c.condition_id in {STEP_STEALTH, STEP_OA} for c in cold(tmp_path, mid).state.actors[ME].conditions.values())


def test_spatial_lock_from_actual_chain_prison_blocks_step_without_benefits(tmp_path):
    _, table, mid = setup(tmp_path, foe_features=('tianxia.talent.chains.chain_prison',), foe_at=6)
    # A real printed prison, cast before the smoke obscures the traveller.
    turn(table, mid, FOE)
    row = group(table, mid, 'Chain Prison')
    assert row
    option = next(o for o in row['options'] if ME in o.get('target_ids', []))
    act(table, mid, option['candidate_id'])
    engine = cold(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.chains_spatial_lock' for c in engine.state.actors[ME].conditions.values())
    turn(table, mid, ME)
    veil(table, mid)
    qi = cold(tmp_path, mid).state.actors[ME].resources['resource:core.qi']
    prompts = step(table, mid)
    engine = cold(tmp_path, mid)
    actor = engine.state.actors[ME]
    assert actor.position == Position(x=3, y=6)
    assert actor.resources['resource:core.qi'] == qi - 1 and not actor.bonus_action_available
    assert not {STEP_OA, STEP_STEALTH}.intersection(c.condition_id for c in actor.conditions.values())
    assert not actor.turn_flags.get('shadow_stepped')
    assert not any(p['context']['reaction_source_id'] == CHOICE for p in prompts)
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == ME for e in engine.events)


def test_insufficient_qi_does_not_admit_or_install_benefits(tmp_path):
    # Real Smoke Veil costs 2 Qi; the source sheet starts with exactly 2.
    _, table, mid = setup(tmp_path, qi=2)
    veil(table, mid)
    actor = cold(tmp_path, mid).state.actors[ME]
    assert actor.resources['resource:core.qi'] == 0
    assert group(table, mid, 'Shadow Step') is None
    assert not {STEP_OA, STEP_STEALTH}.intersection(c.condition_id for c in actor.conditions.values())


def test_light_concealment_step_only_first_actual_opportunity_attack_has_disadvantage(tmp_path):
    _, table, mid = setup(tmp_path, owner_extra=('ASH_BASE_ASHFALL',), foe_at=5, second_foe=True)
    row = group(table, mid, 'Ashfall')
    assert row
    place(table, mid, 'Ashfall')
    # Real light concealment leaves both creatures visible: the next movement
    # can provoke a real OA, unlike moving while concealed by heavy smoke.
    step(table, mid)
    engine = cold(tmp_path, mid)
    assert engine.state.actors[ME].position == Position(x=4, y=6)
    assert any(c.condition_id == STEP_OA for c in engine.state.actors[ME].conditions.values())
    menu = table.state(mid)['menu']
    move = next(m for m in menu['moves'] if m['destination'] == {'x': 3, 'y': 6})
    answers = []
    for _ in range(6):
        result = press(table, mid, move['candidate_id'], answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED'
        p = result['reaction']
        options = (p.get('choice') or {}).get('options') or []
        answers.append({**p['context'], 'selection': 'USE', 'option_ids': [options[0]['id']] if options else []})
    else:
        raise AssertionError('movement did not settle')
    engine = cold(tmp_path, mid)
    foes = {FOE, 'actor:factory.15150003'}
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id in foes and ME in e.target_ids]
    assert len(attacks) == 2 and {e.actor_id for e in attacks} == foes
    rolls = [r for r in engine.rolls if r.actor_id in foes and r.reason.startswith('ATTACK:')]
    assert [r.mode for r in rolls] == ['DISADVANTAGE', 'NORMAL']
    assert not any(c.condition_id == STEP_OA for c in engine.state.actors[ME].conditions.values())
