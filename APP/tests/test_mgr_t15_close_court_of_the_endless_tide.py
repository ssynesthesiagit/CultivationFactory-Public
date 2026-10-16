"""Portable Court imports, committed table actions and fresh-service replay.

Literal dynamic authority/registry dependencies for public export:
TAL_WATER_COURT_OF_THE_ENDLESS_TIDE WATER_BASE_WATER_LASH
WATER_BASE_SHAPE_CURRENT WATER_BASE_RETURN_THE_FLOW tianxia.sphere.water
combat.ext.water_court combat.ext.water_basins combat.ext.free_uses
combat.ext.states combat.ext.needle combat.ext.water_defenses
"""
import json
import zipfile
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext.water_court import COURT, SHAPE, LASH, ROSTER, domains, additional_control
from combat.zones import zone_is_difficult

ROOT = Path(__file__).resolve().parents[1]
OWNER, ALLY, FOE = [f'actor:factory.court-{s}' for s in ('owner', 'ally', 'foe')]
CHOICE = 'choice:needle.'
DYNAMIC_AUTHORITY_DEPENDENCIES = (
    'TAL_WATER_COURT_OF_THE_ENDLESS_TIDE', 'WATER_BASE_WATER_LASH',
    'WATER_BASE_SHAPE_CURRENT', 'WATER_BASE_RETURN_THE_FLOW', 'tianxia.sphere.water',
)


def document(name, owned=False):
    """Source-shaped CL15 Qi character; no injected receipts or runtime benefits."""
    doc = {
        'identity': {'name': name, 'proficiency_bonus': 4, 'cultivation_level': 15,
                     'path': 'Qi Cultivation', 'key_ability': 'CON'},
        'ability_scores_and_statistics': {
            'abilities': [{'ability': a, 'score': 14, 'modifier': 2}
                          for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
            'primary_resource': {'name': 'Qi', 'maximum': 30},
            'armor_class': {'base_value': 14}, 'hit_points': {'maximum': 60},
            'speed': {'walking_ft': 30}, 'technique_save_dc': 30, 'technique_attack_bonus': 8}}
    if owned:
        doc['spheres_and_talents'] = {
            'sphere_record_ids': ['tianxia.sphere.water'],
            'learned_talent_record_ids': [COURT],
            'automatic_sphere_component_record_ids': [LASH, SHAPE, 'WATER_BASE_RETURN_THE_FLOW']}
    return doc


def fixture(tmp_path, owned=True):
    ids = [OWNER, ALLY, FOE]
    docs = [document('Wren', owned), document('Tobin'), document('Mara')]
    bundles = []
    for aid, doc in zip(ids, docs):
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        bundles.append(compile_character(doc, actor_id=aid, reaction_plan={'ask': True}))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    arena = combat.tabletop_maps.save({
        'display_name': 'Court native regression', 'width_squares': 32, 'height_squares': 20,
        'walls': [], 'materials': [], 'starts': {'team1': [[3, 6], [4, 6]], 'team2': [[6, 6]]}})
    mid = combat._finish_factory_match(
        bundles, ids, {OWNER: 'team:factory', ALLY: 'team:factory', FOE: 'team:opponents'},
        {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 6, 'y': 6}},
        combat.factory_arenas()['battlefield:map.' + arena['map_id']], [OWNER, ALLY], [FOE],
        control_modes=dict.fromkeys(ids, 'MANUAL'), match_seed='ENDLESS-TIDE-NATIVE',
        display_name='Court native regression', maximum_rounds=20)['match_id']
    turn(table, mid, OWNER)
    return combat, table, mid


def cold(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def act(table, mid, cid, choices=None):
    menu = table.state(mid)['menu']
    answers, prompts = [], []
    for _ in range(30):
        result = table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return prompts
        prompt = result['reaction']
        prompts.append(prompt)
        key = prompt['context']['reaction_source_id']
        options = (prompt.get('choice') or {}).get('options') or []
        selected = (choices or {}).get(key, [options[0]['id']] if options else None)
        answer = {**prompt['context'], 'selection': 'USE' if selected is not None else 'DECLINE'}
        if selected is not None:
            answer['option_ids'] = selected
        answers.append(answer)
    raise AssertionError('Unbounded prompt sequence')


def turn(table, mid, aid):
    for _ in range(12):
        menu = table.state(mid)['menu']
        if menu['actor_id'] == aid:
            return
        act(table, mid, menu['end_turn'])
    raise AssertionError('Turn did not arrive')


def pick(combat, mid, *tokens, at=None, remote=None, target=None):
    engine = combat._load_session(mid).engine
    rows = [c for c in engine.legal_candidates()
            if all(t in engine.action_catalog[c.source_definition_id].display_name for t in tokens)
            and (at is None or c.destination and (c.destination.x, c.destination.y) == at)
            and (remote is None or bool(c.metadata.get('effect_origin')) == remote)
            and (target is None or c.target_ids == (target,))]
    assert rows, tokens
    return rows[0].candidate_id


def cast(combat, table, mid, roster=None):
    return act(table, mid, pick(combat, mid, 'Court of the Endless Tide'),
               {CHOICE + 'endless_tide_allies': [ALLY] if roster is None else roster})


def test_domain_payment_roster_geometry_and_remote_lash_cold(tmp_path):
    combat, table, mid = fixture(tmp_path)
    before = cold(tmp_path, mid).state.actors[OWNER].resources.copy()
    prompts = cast(combat, table, mid)
    engine = cold(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    domain, = domains(engine, owner)
    assert owner.resources['resource:core.qi'] == before['resource:core.qi'] - 3
    assert not owner.bonus_action_available
    assert domain.concentration_link and domain.duration_rounds == 10
    assert domain.trigger_profile[ROSTER] == [ALLY]
    assert domain.trigger_profile['follows_owner']
    assert not domain.trigger_profile['terrain'] and not domain.trigger_profile['difficult']
    assert additional_control(engine, owner) == 1
    choice = next(p for p in prompts if p['context']['reaction_source_id'] == CHOICE + 'endless_tide_allies')
    assert {o['id'] for o in choice['choice']['options']} == {OWNER, ALLY}
    from combat.ext.water_passage import water_cells
    assert water_cells(engine, owner) == (set(), set(), set())
    action = next(a for a in engine.action_catalog.values() if a.owner_id == OWNER
                  and a.display_name == 'Water Lash')
    from combat.ext.water_court import lash_origins
    origins = lash_origins(engine, owner, action)
    assert len(origins) == len(set(domain.affected_cells))
    assert all(engine.grid.distance_ft(owner.position, p) <= 60 for p in domain.affected_cells)
    cid = pick(combat, mid, 'Water Lash', target=FOE, remote=True)
    act(table, mid, cid)
    after = cold(tmp_path, mid)
    assert after.state.actors[OWNER].position == owner.position
    assert any('effect_origin' in e.payload for e in after.events)


@pytest.mark.parametrize('forms', [('Mist Basin', 'Pressure Basin'), ('Cleansing Basin', 'Flowing Current')])
def test_two_forms_have_both_native_behaviors_and_replay(tmp_path, forms):
    combat, table, mid = fixture(tmp_path)
    cast(combat, table, mid)
    act(table, mid, pick(combat, mid, 'Shape Current:', *forms, at=(6, 6)),
        {CHOICE + 'endless_tide_flow': [FOE], CHOICE + 'endless_tide_save': None})
    engine = cold(tmp_path, mid)
    basin, = [z for z in engine.state.zones.values() if z.active and z.owner_id == OWNER
              and engine.action_catalog[z.source_definition_id].parameters['typed']['source'] == SHAPE]
    assert zone_is_difficult(engine, basin, engine.state.actors[FOE])
    assert not zone_is_difficult(engine, basin, engine.state.actors[ALLY])
    if 'Mist Basin' in forms:
        assert basin.trigger_profile['obscured'] == 'light'
        turn(table, mid, FOE)
        engine = cold(tmp_path, mid)
        assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE for e in engine.events)
        assert any(m.target_field == 'speed' and m.value == -10
                   for m in engine.state.actors[FOE].modifiers.values())
    else:
        assert any(e.get('type') == 'water_cleansing' for t in basin.trigger_profile['triggers']
                   for e in t['effects'])
        assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE for e in engine.events)


@pytest.mark.parametrize('decline', [False, True])
def test_failed_water_save_optional_displacement_commits_cold(tmp_path, decline):
    combat, table, mid = fixture(tmp_path)
    cast(combat, table, mid)
    before = cold(tmp_path, mid).state.actors[FOE].position
    prompts = act(table, mid, pick(combat, mid, 'Shape Current:', 'Cleansing Basin', 'Flowing Current', at=(6, 6)),
                  {CHOICE + 'endless_tide_flow': [FOE],
                   CHOICE + 'endless_tide_save': None if decline else ['step:6,8']})
    engine = cold(tmp_path, mid)
    assert any(p['context']['reaction_source_id'] == CHOICE + 'endless_tide_save' for p in prompts)
    moves = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED'
             and e.source_definition_id == COURT]
    assert bool(moves) is not decline
    if not decline:
        assert engine.grid.distance_ft(before, engine.state.actors[FOE].position) <= 20


def test_no_owner_no_domain_no_remote_or_pairs(tmp_path):
    combat, table, mid = fixture(tmp_path, owned=False)
    engine = cold(tmp_path, mid)
    assert additional_control(engine, engine.state.actors[OWNER]) == 0
    assert not any(a.parameters.get('endless_tide_pair') for a in engine.action_catalog.values())
    assert not any(c.metadata.get('effect_origin') for c in engine.legal_candidates())


def test_free_return_usage_and_domain_expiry_are_native(tmp_path):
    combat, table, mid = fixture(tmp_path)
    cast(combat, table, mid, roster=[])
    act(table, mid, pick(combat, mid, 'Return the Flow:', 'End It Early', '(free)'))
    engine = cold(tmp_path, mid)
    assert any(k.startswith('free_use_' + COURT) and v for k, v in engine.state.actors[OWNER].turn_flags.items())
    assert not any('(free)' in engine.action_catalog[c.source_definition_id].display_name
                   and engine.action_catalog[c.source_definition_id].parameters.get('free_use')
                   for c in engine.legal_candidates())
    for _ in range(10):
        act(table, mid, table.state(mid)['menu']['end_turn'])
        turn(table, mid, OWNER)
    engine = cold(tmp_path, mid)
    assert not domains(engine, engine.state.actors[OWNER])
    assert additional_control(engine, engine.state.actors[OWNER]) == 0
