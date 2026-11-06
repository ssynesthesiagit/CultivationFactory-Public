"""Portable native Cleansing Water regression: real movement, choices and reload.

Only the scenario's contamination producer is synthetic. It never dispatches a
Basin trigger or supplies a completed benefit. Characters own source-shaped
Water sheets imported through the native compiler before match creation.
"""
import json
import zipfile
from hashlib import sha256
from pathlib import Path

import pytest
from combat.canonical import canonical_sha256
from combat.ext import effect
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionDefinition
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]
# Literal inputs for the safe exporter's dynamic authority/registry closure.
RESOURCES = ('authority/Tianxia_Typed_Mechanics_Authority_R1.json',
             'authority/typed_mechanics/rules_text.json',
             'catalog_authority/cat1/data/canonical_talents.v1.json',
             'catalog_authority/cat1/data/prerequisite_projection.v1.json')
OWN = 'TAL_WATER_CLEANSING_WATER'
ME, ALLY, FOE = ('actor:factory.cleansing-' + x for x in ('wren', 'tobin', 'mara'))
WASH = ('mundane_poison_residue', 'acid_residue', 'dust', 'ash', 'filth')


@effect('test_close_cleansing_material', harmful=False)
def material(ctx, row):
    """Authored scenario contamination, evented by the native state producers."""
    subject = ctx.engine.state.actors[ALLY]
    for actor in ctx.engine.state.actors.values():
        ctx.engine._apply_condition(actor, 'condition:typed.covered_in_smoke', ctx.source,
                                    ctx.actor.entity_id, expires_on='UNTIL_REMOVED')
    for name, data in [(x, {}) for x in WASH] + [
            ('burning', {}), ('covered_in_smoke', {}), ('mundane_contamination', {}),
            ('dust', {'magical': True}), ('ash', {'contested': True}),
            ('poisoned', {}), ('disease', {'magical': True}), ('curse', {}), ('injury', {})]:
        ctx.engine._apply_condition(subject, 'condition:typed.' + name, ctx.source,
                                    ctx.actor.entity_id, expires_on='UNTIL_REMOVED', data=data)
    from dataclasses import replace
    from combat.typed_executor import run_effects
    run_effects(replace(ctx, targets=[subject], target=subject),
                [{'type': 'damage', 'applies_to': 'target', 'flat': 7, 'damage_type': 'bludgeoning'}])
    for oid, obj in ctx.engine.state.objects.items():
        n = int(oid.rsplit('.', 1)[-1]) - 80
        if 0 <= n < 7:
            obj.component['mundane_residue'] = WASH[n % len(WASH)]
            if n == 5:
                obj.component['magical'] = True
            if n == 6:
                obj.component['contested'] = True
            ctx.engine._update_object(obj, ctx.source, actor_id=ctx.actor.entity_id)


def document(talents, name):
    return {'identity': {'name': name, 'cultivation_level': 15, 'proficiency_bonus': 5,
                         'path': 'Qi Cultivation', 'key_ability': 'CON'},
            'ability_scores_and_statistics': {
                'abilities': [{'ability': a, 'score': 14, 'modifier': 2}
                              for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
                'primary_resource': {'name': 'Qi', 'maximum': 30},
                'armor_class': {'base_value': 14}, 'hit_points': {'maximum': 60},
                'speed': {'walking_ft': 30}, 'technique_save_dc': 15, 'technique_attack_bonus': 7},
            'spheres_and_talents': {'sphere_record_ids': ['tianxia.sphere.water'] if talents else [],
                'learned_talent_record_ids': [x for x in talents if x.startswith('TAL_')],
                'automatic_sphere_component_record_ids': ['WATER_BASE_SHAPE_CURRENT'] if talents else []}}


def fixture(path, owned=True, second_owner=False):
    docs = [document([OWN] if owned else ['WATER_BASE_SHAPE_CURRENT'], 'Wren'),
            document([OWN] if second_owner else [], 'Tobin'), document([], 'Mara')]
    if second_owner:
        docs[1]['identity'].update(cultivation_level=5, proficiency_bonus=3)
    bundles = []
    for aid, doc in zip((ME, ALLY, FOE), docs):
        folder = path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        bundles.append(compile_character(doc, actor_id=aid, reaction_plan={'ask': True}))
    b = bundles[0]
    a = ActionDefinition(source_definition_id='action:test.close_cleansing_material',
                         display_name='Scenario: contamination', owner_id=ME, economy='NONE',
                         resolution_kind='TYPED', target_kind='SELF',
                         parameters={'free_primary': True, 'typed': {
                             'source': 'test_close_cleansing_material', 'numbers': {'pb': 5},
                             'effects': [{'type': 'test_close_cleansing_material'}], 'riders': []}})
    b['action_catalog'].append(a.model_dump(mode='json'))
    b['actor_template']['action_ids'].append(a.source_definition_id)
    for suffix, effects in (
            ('ward', [{'type': 'temp_hp', 'applies_to': 'target', 'flat': 9}]),
            ('interception', [{'type': 'intercept_healing', 'applies_to': 'target',
                               'reduce': 2, 'kinds': ['temp_hp'], 'each_from_cl': 1,
                               'duration': 'until_end_of_your_next_turn', 'name': 'Scenario wound'}])):
        other = a.model_copy(update={
            'source_definition_id': 'action:test.close_cleansing_' + suffix,
            'display_name': 'Scenario: ' + suffix, 'target_kind': 'ALLY_OR_SELF', 'range_ft': 60,
            'parameters': {'free_primary': True, 'typed': {
                'source': 'test_close_cleansing_' + suffix, 'effects': effects,
                'numbers': {'pb': 5, 'cl': 15}, 'riders': []}}})
        b['action_catalog'].append(other.model_dump(mode='json'))
        b['actor_template']['action_ids'].append(other.source_definition_id)
    b.pop('bundle_sha256', None)
    b['bundle_sha256'] = canonical_sha256(b)
    combat = CombatService(ROOT, path)
    table = TabletopService(combat, path)
    arena = dict(combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'])
    arena['map_objects'] = [{'id': 80 + n, 'kind': 'crate', 'x': 4, 'y': 5} for n in range(7)]
    mid = combat._finish_factory_match(bundles, [ME, ALLY, FOE],
        {ME: 'team:a', ALLY: 'team:a', FOE: 'team:b'},
        {ME: {'x': 1, 'y': 6}, ALLY: {'x': 2, 'y': 6}, FOE: {'x': 8, 'y': 6}},
        arena, [ME, ALLY], [FOE], control_modes={x: 'MANUAL' for x in (ME, ALLY, FOE)},
        match_seed='CLOSE-CLEANSING', display_name='Cleansing Water', maximum_rounds=15)['match_id']
    turn(table, mid, ME)
    return combat, table, mid


def settle(table, mid, cid, picks=None, *, auto=False):
    answers, prompts = [], []
    for _ in range(20):
        menu = table.state(mid)['menu']
        result = (table.auto_step(mid, 0, answers) if auto else
                  table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, answers))
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return prompts
        p = result['reaction']; prompts.append(p)
        rid = p['context']['reaction_source_id']
        options = (p.get('choice') or {}).get('options') or []
        choice = (picks or {}).get(rid, options[0]['id'] if options else None)
        answer = {**p['context'], 'selection': 'DECLINE' if choice is None else 'USE'}
        if choice is not None and options:
            answer['option_ids'] = [choice]
        answers.append(answer)
    raise AssertionError('unsettled choices')


def turn(table, mid, actor, picks=None):
    prompts = []
    for _ in range(12):
        if table.state(mid)['menu']['actor_id'] == actor:
            return prompts
        prompts.extend(settle(table, mid, table.state(mid)['menu']['end_turn'], picks))
    raise AssertionError('no turn')


def cold(path, mid):
    service = CombatService(ROOT, path)
    session = service._load_session(mid)
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def action(combat, mid, name, at=None, target=None):
    e = combat._load_session(mid).engine
    rows = [c for c in e.legal_candidates()
            if getattr(e.action_catalog.get(c.source_definition_id), 'display_name', None) == name
            and (at is None or c.destination and (c.destination.x, c.destination.y) == at)
            and (target is None or c.target_ids == (target,))]
    assert rows, name
    return rows[0].candidate_id


def move(combat, table, mid, at, picks=None):
    e = combat._load_session(mid).engine
    rows = [c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination
            and (c.destination.x, c.destination.y) == at]
    assert rows, ('move', at)
    return settle(table, mid, rows[0].candidate_id, picks)


def setup(path, owned=True, second_owner=False):
    combat, table, mid = fixture(path, owned, second_owner)
    settle(table, mid, action(combat, mid, 'Scenario: contamination'))
    settle(table, mid, action(combat, mid, 'Shape Current: Cleansing Basin', (4, 6)))
    e = cold(path, mid)
    assert e.state.actors[ME].resources['resource:core.qi'] == 29
    assert e.state.actors[ALLY].temporary_hp == 0
    return combat, table, mid


def test_actual_entry_and_natural_round_renewal(tmp_path):
    combat, table, mid = setup(tmp_path)
    turn(table, mid, ALLY)
    prompts = move(combat, table, mid, (3, 6), {'choice:needle.water_cleansing': 'cleanse'})
    e = cold(tmp_path, mid); ally = e.state.actors[ALLY]
    assert any(p['context']['reactor_id'] == ALLY for p in prompts)
    assert not any(c.condition_id == 'condition:typed.covered_in_smoke' for c in ally.conditions.values())
    assert ally.temporary_hp == 5
    assert not any(c.condition_id in ('condition:typed.burning', 'condition:typed.mundane_contamination') for c in ally.conditions.values())
    assert ally.current_hp < ally.maximum_hp
    assert any(c.data.get('magical') for c in ally.conditions.values() if c.condition_id == 'condition:typed.dust')
    assert any(c.data.get('contested') for c in ally.conditions.values() if c.condition_id == 'condition:typed.ash')
    zone = next(z for z in e.state.zones.values() if z.active)
    first_round = e.state.round_number
    assert zone.per_turn_triggered['cleansing_water_round'] == first_round
    # Continue through fresh services, then advance the actual round clock.
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    turn(table, mid, ME)
    settle(table, mid, action(combat, mid, 'Scenario: contamination'))
    prompts = turn(table, mid, ALLY, {'choice:needle.water_cleansing': 'cleanse'})
    e = cold(tmp_path, mid)
    assert e.state.round_number > first_round
    assert not any(c.condition_id == 'condition:typed.covered_in_smoke' for c in e.state.actors[ALLY].conditions.values())
    assert any(o['id'] == 'cleanse' for p in prompts for o in (p.get('choice') or {}).get('options', []))


def test_washing_five_residues_and_protected_states(tmp_path):
    combat, table, mid = setup(tmp_path)
    turn(table, mid, ALLY)
    move(combat, table, mid, (3, 6), {'choice:needle.water_cleansing': None})
    turn(table, mid, ME)
    before = cold(tmp_path, mid)
    held = before.state.actors[ALLY].model_dump(mode='json')
    settle(table, mid, action(combat, mid, 'Cleansing Water: Wash Residue'),
           {'choice:needle.water_wash_residue': None})
    assert cold(tmp_path, mid).state.actors[ALLY].model_dump(mode='json') == held
    before_hp = before.state.actors[ALLY].current_hp
    settle(table, mid, action(combat, mid, 'Cleansing Water: Wash Residue'),
           {'choice:needle.water_wash_residue': ALLY})
    e = cold(tmp_path, mid); ally = e.state.actors[ALLY]
    assert ally.temporary_hp == 5
    assert ally.current_hp == before_hp < ally.maximum_hp
    assert not any(c.condition_id.removeprefix('condition:typed.') in WASH
                   and not c.data.get('magical') and not c.data.get('contested')
                   for c in ally.conditions.values())
    for name in ('covered_in_smoke', 'mundane_contamination', 'poisoned', 'disease', 'curse', 'injury'):
        assert any(c.condition_id == 'condition:typed.' + name for c in ally.conditions.values())
    assert any(c.data.get('contested') for c in ally.conditions.values() if c.condition_id == 'condition:typed.ash')
    for n in range(5):
        settle(table, mid, action(combat, mid, 'Cleansing Water: Wash Residue'),
               {'choice:needle.water_wash_residue': f'object:map.{80+n}'})
        e = cold(tmp_path, mid)
        assert 'mundane_residue' not in e.state.objects[f'object:map.{80+n}'].component
    from combat.ext.water_basins import wash_targets
    assert 'object:map.85' not in wash_targets(e, e.state.actors[ME])
    assert e.state.objects['object:map.85'].component['mundane_residue'] == 'mundane_poison_residue'
    assert 'object:map.86' not in wash_targets(e, e.state.actors[ME])
    assert e.state.actors[ME].resources['resource:core.qi'] == 29


def test_unowned_basin_decline_and_same_round_budget(tmp_path):
    combat, table, mid = setup(tmp_path, owned=False)
    e = cold(tmp_path, mid)
    assert not any(a.display_name == 'Cleansing Water: Wash Residue' for a in e.action_catalog.values())
    turn(table, mid, ALLY)
    prompts = move(combat, table, mid, (3, 6), {'choice:needle.water_cleansing': None})
    assert not any(o['id'] == 'cleanse' for p in prompts for o in (p.get('choice') or {}).get('options', []))
    e = cold(tmp_path, mid)
    assert e.state.actors[ALLY].temporary_hp == 0
    assert any(c.condition_id == 'condition:typed.covered_in_smoke' for c in e.state.actors[ALLY].conditions.values())


def test_nonally_can_cleanse_without_receiving_ally_hp(tmp_path):
    combat, table, mid = setup(tmp_path)
    turn(table, mid, FOE)
    prompts = move(combat, table, mid, (4, 6), {'choice:needle.water_cleansing': 'cleanse'})
    e = cold(tmp_path, mid)
    assert any(p['context']['reactor_id'] == FOE for p in prompts)
    assert e.state.actors[FOE].temporary_hp == 0
    assert not any(c.condition_id == 'condition:typed.covered_in_smoke' for c in e.state.actors[FOE].conditions.values())
    assert not any(o['id'] == 'save' for p in prompts for o in (p.get('choice') or {}).get('options', []))


def test_basin_budget_is_shared_by_actual_creature_entries(tmp_path):
    combat, table, mid = setup(tmp_path)
    e = cold(tmp_path, mid)
    first, second = sorted((ME, ALLY), key=e.state.initiative_order.index)
    turn(table, mid, first)
    move(combat, table, mid, (3, 5), {'choice:needle.water_cleansing': 'cleanse'})
    e = cold(tmp_path, mid)
    spent_round = e.state.round_number
    assert e.state.actors[first].temporary_hp == 5
    turn(table, mid, second)
    assert cold(tmp_path, mid).state.round_number == spent_round
    prompts = move(combat, table, mid, (3, 6), {'choice:needle.water_cleansing': 'save'})
    assert not any(o['id'] == 'cleanse' for p in prompts for o in (p.get('choice') or {}).get('options', []))
    e = cold(tmp_path, mid)
    assert e.state.actors[second].temporary_hp == 5
    assert any(c.condition_id == 'condition:typed.covered_in_smoke' for c in e.state.actors[second].conditions.values())


@pytest.mark.parametrize('mode', ['LOCAL_AUTO', 'MANUAL'])
def test_native_auto_turn_and_beneficiary_control(tmp_path, mode):
    from combat.gate4_adapters import ManualControllerAdapter
    combat, table, mid = setup(tmp_path)
    turn(table, mid, ALLY)
    e = combat._load_session(mid).engine
    cid = next(c.candidate_id for c in e.legal_candidates() if c.kind == 'MOVE'
               and c.destination and (c.destination.x, c.destination.y) == (3, 6))
    native = combat.controller

    class ScenarioController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(native, name)

    combat.controller = ScenarioController()
    combat.set_controller_mode(mid, actor_id=ALLY, controller_mode=mode)
    prompts = settle(table, mid, cid, {'choice:needle.water_cleansing': 'cleanse'}, auto=mode == 'LOCAL_AUTO')
    e = cold(tmp_path, mid)
    assert e.state.actors[ALLY].temporary_hp == 5
    assert bool(prompts) is (mode == 'MANUAL')
    assert not any(c.condition_id == 'condition:typed.covered_in_smoke' for c in e.state.actors[ALLY].conditions.values())


@pytest.mark.parametrize('scenario,expected', [('ward', 9), ('interception', 3)])
def test_beneficiary_hp_uses_native_selection_and_interception(tmp_path, scenario, expected):
    combat, table, mid = setup(tmp_path)
    settle(table, mid, action(combat, mid, 'Scenario: ' + scenario, target=ALLY))
    turn(table, mid, ALLY)
    move(combat, table, mid, (3, 6), {'choice:needle.water_cleansing': 'cleanse'})
    e = cold(tmp_path, mid)
    assert e.state.actors[ALLY].temporary_hp == expected
    grants = [x for x in e.events if x.event_type == 'TEMP_HP_GRANTED' and x.target_ids == (ALLY,)]
    assert grants[-1].actor_id == ME
    assert grants[-1].payload['offered'] == (3 if scenario == 'interception' else 5)


def test_two_real_creators_keep_basin_sources_and_hp_separate(tmp_path):
    combat, table, mid = setup(tmp_path, second_owner=True)
    turn(table, mid, ALLY)
    e = cold(tmp_path, mid)
    assert not any(getattr(e.action_catalog.get(c.source_definition_id), 'display_name', None) == 'Cleansing Water: Wash Residue' for c in e.legal_candidates())
    settle(table, mid, action(combat, mid, 'Shape Current: Cleansing Basin', (2, 7)))
    prompts = settle(table, mid, action(combat, mid, 'Cleansing Water: Wash Residue'),
                     {'choice:needle.water_wash_residue': ALLY})
    e = cold(tmp_path, mid)
    assert e.state.actors[ALLY].temporary_hp == 3
    assert e.state.actors[ME].temporary_hp == 0
    assert not any(o['id'].startswith('object:map.') for p in prompts for o in (p.get('choice') or {}).get('options', []))
    from combat.ext.water_basins import cleansing_areas
    own = cleansing_areas(e, e.state.actors[ME])
    other = cleansing_areas(e, e.state.actors[ALLY])
    assert len(own) == len(other) == 1
    assert own[0].zone_id != other[0].zone_id
    assert own[0].trigger_profile['numbers']['pb'] == 5
    assert other[0].trigger_profile['numbers']['pb'] == 3
    move(combat, table, mid, (3, 6), {'choice:needle.water_cleansing': 'cleanse'})
    e = cold(tmp_path, mid)
    assert e.state.actors[ALLY].temporary_hp == 5
    assert any(z.per_turn_triggered.get('cleansing_water_round') == e.state.round_number
               for z in cleansing_areas(e, e.state.actors[ME]))
    assert all('cleansing_water_round' not in z.per_turn_triggered for z in cleansing_areas(e, e.state.actors[ALLY]))


def test_basin_expires_on_its_native_minute_clock(tmp_path):
    combat, table, mid = fixture(tmp_path)
    settle(table, mid, action(combat, mid, 'Shape Current: Cleansing Basin', (4, 6)))
    e = cold(tmp_path, mid)
    zone = next(z for z in e.state.zones.values() if z.active and z.owner_id == ME)
    zid = zone.zone_id
    assert zone.duration_rounds == 10
    assert e.state.actors[ME].resources['resource:core.qi'] == 29
    for _ in range(36):
        if not e.state.zones[zid].active:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        e = cold(tmp_path, mid)
    assert not e.state.zones[zid].active
    assert e.state.round_number - zone.created_round >= 10
    from combat.ext.water_basins import cleansing_areas
    assert not cleansing_areas(e, e.state.actors[ME])
