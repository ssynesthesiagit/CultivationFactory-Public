"""Temporal gates retain their route; later-option settings survive Table reload."""
import copy

import pytest

from combat.ext.attack_modifiers import capture, chosen, settings
from combat.gate4_engine import Gate4ControllerEngine
from tests.h1_support import script
from tests.hunt36_support import LEFT, RIGHT, act, fight, reload, send, turn

CHAINS = 'TAL_LIGHTNING_LIGHTNING_CHAINS'
IMPACT = 'TAL_FORCE_BODY_CONDUCTED_IMPACT'
SECONDARY = 'actor:factory.36000003'


@pytest.mark.parametrize('nested', [False, True])
def test_temporal_mark_gate_keeps_original_variant(nested):
    gate = {'type': 'if_marked', 'at': 'hit', 'mark': 'Future mark', 'effects': []}
    rows = [{'type': 'save', 'on_fail': [gate]}] if nested else [gate]
    variant = {'typed': {}, 'costs': [], '_compose': {'when': 'hit', 'added': rows,
               'key': 'future.temporal', 'name': 'Temporal rider', 'modifier': {}}}
    base = {'action_id': 'future.attack', 'costs': [], 'typed': {'weapon': True}, 'variants': [variant]}
    capture(base)
    assert 'attack_modifier_loadout' not in base['typed']
    assert 'attack_modifier_variant' not in variant['typed']
    gate.pop('at')
    capture(base)
    assert base['typed']['attack_modifier_loadout']


def guaranteed_hits(monkeypatch):
    original = Gate4ControllerEngine._resolve_attack_spec
    def hit(engine, *args, **kwargs):
        script(engine, [19, 19, *([1] * 100)])
        return original(engine, *args, **kwargs)
    monkeypatch.setattr(Gate4ControllerEngine, '_resolve_attack_spec', hit)


@pytest.mark.parametrize('already_charged', [True, False])
def test_lightning_original_route_hit_snapshot_table_reload(tmp_path, monkeypatch, already_charged):
    from tests import hunt36_support
    from combat.typed_executor import bears_mark
    original = hunt36_support.compile_character
    def compile_with_setup(*args, **kwargs):
        bundle = original(*args, **kwargs)
        if kwargs['actor_id'] == LEFT:
            action = copy.deepcopy(next(a for a in bundle['action_catalog'] if a['resolution_kind'] == 'TYPED'))
            action.update(source_definition_id='action:test.r4.charge', display_name='Test Charge',
                          economy='NONE', target_kind='HOSTILE_ENTITY', costs=[], range_ft=60)
            action['parameters'] = {'typed': {'effects': [{'type': 'mark', 'mark': 'Charged',
                'applies_to': 'target', 'duration': {'kind': 'until_removed'}}], 'numbers': {}, 'riders': []}}
            bundle['action_catalog'].append(action)
            bundle['actor_template']['action_ids'].append(action['source_definition_id'])
        return bundle
    monkeypatch.setattr(hunt36_support, 'compile_character', compile_with_setup)
    from combat.gate5_service import CombatService
    finish = CombatService._finish_factory_match
    def three_creatures(service, bundles, actor_ids, teams, positions, arena, left, right, **kwargs):
        doc = hunt36_support.sheet([], cl=5)
        doc['identity']['display_name'] = 'Second Fighter'
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 1000
        bundle = original(doc, actor_id=SECONDARY, reaction_plan={'ask': False})
        return finish(service, [*bundles, bundle], [*actor_ids, SECONDARY],
                      {**teams, SECONDARY: 'team:opponents'}, {**positions, SECONDARY: {'x': 5, 'y': 6}},
                      arena, left, [*right, SECONDARY], **kwargs)
    monkeypatch.setattr(CombatService, '_finish_factory_match', three_creatures)
    guaranteed_hits(monkeypatch)
    original_save = Gate4ControllerEngine._roll_save
    def fail(engine, *args, **kwargs):
        script(engine, [1, *([1] * 100)])
        return original_save(engine, *args, **kwargs)
    monkeypatch.setattr(Gate4ControllerEngine, '_roll_save', fail)
    combat, table, mid = fight(tmp_path, [CHAINS], cl=5, seed='SOLFSOL117R4-CHAINS')
    turn(combat, table, mid)
    if already_charged:
        act(combat, table, mid, 'Test Charge')
    name = 'Lightning Lash: Jolt + Lightning Chains' if already_charged else 'Lightning Lash: Charge + Lightning Chains'
    engine = reload(combat, mid)
    assert bears_mark(engine.state.actors[RIGHT], LEFT, 'Charged') == already_charged
    assert any(g['label'] == name for g in table.state(mid)['menu']['actions'])
    assert not [a for a in engine.action_catalog.values()
                if (a.parameters.get('attack_modifier_setting') or {}).get('modifier') == CHAINS]
    action = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT and a.display_name == name)
    assert not action.parameters['typed'].get('attack_modifier_variant')
    sequence = engine.state.event_sequence
    cid = next(c.candidate_id for c in engine.legal_candidates()
               if c.source_definition_id == action.source_definition_id and c.target_ids == (RIGHT,))
    prompts = send(combat, table, mid, cid)
    engine = reload(combat, mid)
    events = [e for e in engine.events if e.sequence > sequence]
    assert len([e for e in events if e.event_type == 'ATTACK_ROLLED']) == 1
    assert bears_mark(engine.state.actors[RIGHT], LEFT, 'Charged')
    saves = [e for e in events if e.event_type == 'SAVE_ROLLED']
    assert len(saves) == int(already_charged)
    assert bool(prompts) == already_charged
    links = [c for actor in engine.state.actors.values() for c in actor.conditions.values()
             if c.condition_id == 'condition:typed.link.lightning']
    assert len(links) == 2 * int(already_charged)
    assert bool([e for e in events if e.event_type == 'DAMAGE_COMMITTED' and SECONDARY in e.target_ids]) == already_charged


def configure(combat, table, mid, parent, field, value):
    engine = reload(combat, mid)
    action = next(a for a in engine.action_catalog.values()
                  if (a.parameters.get('attack_modifier_setting') or {}).get('family') == parent
                  and a.parameters['attack_modifier_setting']['modifier'] == IMPACT
                  and a.parameters['attack_modifier_setting']['field'] == field
                  and a.parameters['attack_modifier_setting']['value'] == value)
    send(combat, table, mid, next(c.candidate_id for c in engine.legal_candidates()
                               if c.source_definition_id == action.source_definition_id))


@pytest.mark.parametrize('damage', ['force', 'bludgeoning'])
def test_later_option_fixed_damage_table_reload(tmp_path, monkeypatch, damage):
    guaranteed_hits(monkeypatch)
    combat, table, mid = fight(tmp_path, [IMPACT], cl=5, seed='SOLFSOL117R4-IMPACT')
    turn(combat, table, mid)
    engine = reload(combat, mid)
    parent = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == LEFT and a.display_name == 'Impact')
    before = dict(engine.state.actors[LEFT].resources)
    sequence = engine.state.event_sequence
    for field, value in [('on', 'toggle'), ('option', '1'), ('payment', '0'), ('damage', damage)]:
        configure(combat, table, mid, parent, field, value)
    engine = reload(combat, mid)
    saved = chosen(engine.state.actors[LEFT], parent, IMPACT)
    assert saved['option'] == '1' and saved['damage'] == damage and saved['payment'] == '0'
    assert engine.state.actors[LEFT].resources == before
    assert not [e for e in engine.events if e.sequence > sequence
                and e.event_type in ('ATTACK_ROLLED', 'DAMAGE_ROLLED', 'RESOURCE_SPENT')]
    row = next(e for e in table.state(mid)['shapes'][LEFT] if e['base'] == parent)['modifiers'][0]
    selector = next(s for s in row['selectors'] if s['field'] == 'damage')
    assert selector['current'] == damage
    assert {o['value'] for o in selector['options']} == {'ask', 'force', 'bludgeoning'}
    sequence = engine.state.event_sequence
    cid = next(c.candidate_id for c in engine.legal_candidates()
               if c.source_definition_id == parent and c.target_ids == (RIGHT,))
    assert send(combat, table, mid, cid) == []
    engine = reload(combat, mid)
    events = [e for e in engine.events if e.sequence > sequence]
    assert len([e for e in events if e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == IMPACT]) == 1
    assert engine.state.actors[LEFT].resources['resource:core.qi'] == before['resource:core.qi'] - 1
    assert any(e.event_type == 'DAMAGE_COMMITTED' and e.payload.get('damage_type') == damage.upper()
               and e.payload.get('reduced_to') == 4 for e in events)
    configure(combat, table, mid, parent, 'option', '0')
    row = next(e for e in table.state(mid)['shapes'][LEFT] if e['base'] == parent)['modifiers'][0]
    assert not [s for s in row['selectors'] if s['field'] == 'damage']


@pytest.mark.parametrize('preferred_payment', ['1', '0'])
def test_later_option_distinct_payments_and_damage_are_option_validated(tmp_path, monkeypatch, preferred_payment):
    # Synthetic sealed options exercise different costs; no printed ability's
    # rules are altered. Rebuild settings before the fixture seals the bundle.
    from tests import hunt36_support
    from combat.gate2_runtime_models import ActionDefinition
    original = hunt36_support.compile_character
    def different_options(*args, **kwargs):
        bundle = original(*args, **kwargs)
        if kwargs['actor_id'] != LEFT:
            return bundle
        actions = [ActionDefinition.model_validate(a) for a in bundle['action_catalog']
                   if not a['parameters'].get('attack_modifier_setting')]
        for action in actions:
            for group in action.parameters.get('typed', {}).get('attack_modifier_loadout', []):
                if group['id'] == IMPACT:
                    group['options'][1]['payments'] = [[['resource:core.qi', 3]]]
        actions = settings(actions)
        bundle['action_catalog'] = [a.model_dump(mode='json') for a in actions]
        bundle['actor_template']['action_ids'] = [a.source_definition_id for a in actions]
        return bundle
    monkeypatch.setattr(hunt36_support, 'compile_character', different_options)
    guaranteed_hits(monkeypatch)
    combat, table, mid = fight(tmp_path, [IMPACT], cl=5, seed='SOLFSOL117R4-COSTS')
    turn(combat, table, mid)
    engine = reload(combat, mid)
    parent = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == LEFT and a.display_name == 'Impact')
    for field, value in [('on', 'toggle'), ('option', '1'), ('payment', preferred_payment), ('damage', 'force')]:
        configure(combat, table, mid, parent, field, value)
    row = next(e for e in table.state(mid)['shapes'][LEFT] if e['base'] == parent)['modifiers'][0]
    pay = next(s for s in row['selectors'] if s['field'] == 'payment')
    assert pay['current'] == ('1' if preferred_payment == '1' else 'ask')
    assert {o['value'] for o in pay['options']} == {'ask', '1'}
    engine = reload(combat, mid)
    before = engine.state.actors[LEFT].resources['resource:core.qi']
    cid = next(c.candidate_id for c in engine.legal_candidates()
               if c.source_definition_id == parent and c.target_ids == (RIGHT,))
    prompts = send(combat, table, mid, cid)
    assert len(prompts) == int(preferred_payment == '0')
    assert all('Choose payment' in p['moment']
               and any('3 CP' in o['label'] for o in p['choice']['options']) for p in prompts)
    assert reload(combat, mid).state.actors[LEFT].resources['resource:core.qi'] == before - 3
