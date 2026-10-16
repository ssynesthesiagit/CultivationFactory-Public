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
    for name, data in [(x, {}) for x in WASH] + [
            ('covered_in_smoke', {}), ('mundane_contamination', {}),
            ('dust', {'magical': True}), ('ash', {'contested': True}),
            ('poisoned', {}), ('disease', {'magical': True}), ('curse', {}), ('injury', {})]:
        ctx.engine._apply_condition(subject, 'condition:typed.' + name, ctx.source,
                                    ctx.actor.entity_id, expires_on='UNTIL_REMOVED', data=data)
    for oid, obj in ctx.engine.state.objects.items():
        n = int(oid.rsplit('.', 1)[-1]) - 80
        if 0 <= n < len(WASH):
            obj.component['mundane_residue'] = WASH[n]
            if n == 0:
                obj.component['magical'] = True
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
                'learned_talent_record_ids': talents,
                'automatic_sphere_component_record_ids': ['WATER_BASE_SHAPE_CURRENT'] if talents else []}}


def fixture(path, owned=True):
    docs = [document([OWN] if owned else ['WATER_BASE_SHAPE_CURRENT'], 'Wren'),
            document([], 'Tobin'), document([], 'Mara')]
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
    b.pop('bundle_sha256', None)
    b['bundle_sha256'] = canonical_sha256(b)
    combat = CombatService(ROOT, path)
    table = TabletopService(combat, path)
    arena = dict(combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'])
    arena['map_objects'] = [{'id': 80 + n, 'kind': 'crate', 'x': 4, 'y': 5} for n in range(5)]
    mid = combat._finish_factory_match(bundles, [ME, ALLY, FOE],
        {ME: 'team:a', ALLY: 'team:a', FOE: 'team:b'},
        {ME: {'x': 1, 'y': 6}, ALLY: {'x': 2, 'y': 6}, FOE: {'x': 8, 'y': 6}},
        arena, [ME, ALLY], [FOE], control_modes={x: 'MANUAL' for x in (ME, ALLY, FOE)},
        match_seed='CLOSE-CLEANSING', display_name='Cleansing Water', maximum_rounds=15)['match_id']
    turn(table, mid, ME)
    return combat, table, mid


def settle(table, mid, cid, picks=None):
    answers, prompts = [], []
    for _ in range(20):
        menu = table.state(mid)['menu']
        result = table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, answers)
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


def action(combat, mid, name, at=None):
    e = combat._load_session(mid).engine
    rows = [c for c in e.legal_candidates()
            if getattr(e.action_catalog.get(c.source_definition_id), 'display_name', None) == name
            and (at is None or c.destination and (c.destination.x, c.destination.y) == at)]
    assert rows, name
    return rows[0].candidate_id


def move(combat, table, mid, at, picks=None):
    e = combat._load_session(mid).engine
    rows = [c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination
            and (c.destination.x, c.destination.y) == at]
    assert rows, ('move', at)
    return settle(table, mid, rows[0].candidate_id, picks)


def setup(path, owned=True):
    combat, table, mid = fixture(path, owned)
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
    assert any(c.data.get('magical') for c in ally.conditions.values() if c.condition_id == 'condition:typed.dust')
    assert any(c.data.get('contested') for c in ally.conditions.values() if c.condition_id == 'condition:typed.ash')
    zone = next(z for z in e.state.zones.values() if z.active)
    first_round = e.state.round_number
    assert zone.per_turn_triggered['cleansing_water_round'] == first_round
    # Real turns advance the clock; a committed producer records fresh smoke.
    turn(table, mid, ME)
    settle(table, mid, action(combat, mid, 'Scenario: contamination'))
    prompts = turn(table, mid, ALLY, {'choice:needle.water_cleansing': 'cleanse'})
    e = cold(tmp_path, mid)
    assert e.state.round_number > first_round
    assert not any(c.condition_id == 'condition:typed.covered_in_smoke' for c in e.state.actors[ALLY].conditions.values())
    assert any(o['id'] == 'cleanse' for p in prompts for o in (p.get('choice') or {}).get('options', []))


def test_washing_five_residues_and_protected_states(tmp_path):
    combat, table, mid = setup(tmp_path)
    settle(table, mid, action(combat, mid, 'Cleansing Water: Wash Residue'),
           {'choice:needle.water_wash_residue': ALLY})
    e = cold(tmp_path, mid)
    # Ally begins outside the Basin: selection must not be offered yet.
    assert any(c.condition_id == 'condition:typed.filth' for c in e.state.actors[ALLY].conditions.values())
