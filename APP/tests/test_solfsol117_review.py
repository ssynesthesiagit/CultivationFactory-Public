"""Review regressions through real table transactions, commits and fresh replay."""
import copy
import json

import pytest

from combat.gate4_engine import Gate4ControllerEngine
from tests.h1_support import ROOT, script
from tests.hunt36_support import LEFT, RIGHT, fight, turn, send, reload
from tests.test_sol117_attack_modifiers import NULL, IRON

SOUND = 'TAL_SOUND_BODY_RESONANCE_STRIKE'


@pytest.fixture
def hits(monkeypatch):
    original = Gate4ControllerEngine._resolve_attack_spec
    def roll(engine, *args, **kwargs):
        # Two high d20 values also cover an untrained weapon's Disadvantage.
        script(engine, [19, 19, *([1] * 100)])
        return original(engine, *args, **kwargs)
    monkeypatch.setattr(Gate4ControllerEngine, '_resolve_attack_spec', roll)


def choose(combat, table, mid, parent, modifier, field, value):
    engine = reload(combat, mid)
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if (a.parameters.get('attack_modifier_setting') or {}).get('family') == parent
                  and a.parameters['attack_modifier_setting']['modifier'] == modifier
                  and a.parameters['attack_modifier_setting']['field'] == field
                  and a.parameters['attack_modifier_setting']['value'] == value)
    send(combat, table, mid, next(c.candidate_id for c in engine.legal_candidates() if c.source_definition_id == source))


@pytest.mark.parametrize('scenario', ['single-effect', 'one-payment', 'successful-save', 'deferred-fixed-payment'])
@pytest.mark.parametrize('decline', [True, False])
def test_optional_single_choices_ask_before_spending(tmp_path, monkeypatch, hits, scenario, decline):
    from tests import hunt36_support
    original_sheet = hunt36_support.sheet
    def successful(*args, **kwargs):
        doc = original_sheet(*args, **kwargs)
        doc['ability_scores_and_statistics']['technique_save_dc'] = -100
        if scenario == 'one-payment':
            doc['ability_scores_and_statistics']['primary_resource']['definitions'] = [{'name': 'Stamina', 'max': 1}]
        return doc
    monkeypatch.setattr(hunt36_support, 'sheet', successful)
    modifier = SOUND if scenario in ('single-effect', 'one-payment') else NULL
    combat, table, mid = fight(tmp_path, [modifier, IRON], primary='Qi' if scenario == 'one-payment' else 'Stamina',
                              stamina=0 if scenario == 'one-payment' else None, cl=5, seed='SOLFSOL117-ASK')
    turn(combat, table, mid)
    parent = next(a.source_definition_id for a in reload(combat, mid).action_catalog.values() if a.display_name == 'Iron Fist attack')
    choose(combat, table, mid, parent, modifier, 'on', 'toggle')
    if scenario == 'single-effect':
        choose(combat, table, mid, parent, modifier, 'payment', '0')
    elif scenario == 'one-payment':
        choose(combat, table, mid, parent, modifier, 'option', '0')
    else:
        choose(combat, table, mid, parent, modifier, 'damage', 'force')
        if scenario == 'deferred-fixed-payment':
            choose(combat, table, mid, parent, modifier, 'payment', '0')
    engine = reload(combat, mid)
    group = next(g for g in engine.action_catalog[parent].parameters['typed']['attack_modifier_loadout'] if g['id'] == modifier)
    assert len([p for p in group['options'][0]['payments'] if engine._can_pay(engine.state.actors[LEFT], p)]) == 1
    if scenario == 'one-payment':
        assert len(group['options'][0]['payments']) == 2
    before = engine.state.model_dump(mode='json')
    sequence = engine.state.event_sequence
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == parent and c.target_ids == (RIGHT,))
    state = table.state(mid)
    answers = []
    for _ in range(4):
        result = table.act(mid, candidate.candidate_id, state['menu']['decision_id'], state['menu']['state_version'], state['last_sequence'], answers)
        assert result['status'] == 'REACTION_REQUIRED'
        assert reload(combat, mid).state.model_dump(mode='json') == before
        assert not [e for e in reload(combat, mid).events if e.sequence > sequence and e.event_type in ('ATTACK_ROLLED', 'DAMAGE_ROLLED', 'RESOURCE_SPENT')]
        prompt = result['reaction']
        if prompt['context']['reaction_source_id'] == 'choice:needle.attack_modifier':
            break
        answers.append({**prompt['context'], 'selection': 'USE', 'option_ids': [prompt['choice']['options'][0]['id']]})
    else:
        pytest.fail('No optional rider prompt')
    assert group['name'] in prompt['moment'] and 'Iron Fist attack' in prompt['moment'] and 'Visiting Fighter' in prompt['moment']
    answer = {**prompt['context'], 'selection': 'DECLINE' if decline else 'USE'}
    if not decline:
        answer['option_ids'] = [prompt['choice']['options'][0]['id']]
    answers.append(answer)
    result = table.act(mid, candidate.candidate_id, state['menu']['decision_id'], state['menu']['state_version'], state['last_sequence'], answers)
    assert result['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    events = [e for e in engine.events if e.sequence > sequence]
    spent = [e for e in events if e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == modifier]
    damage = [e for e in events if e.event_type == 'DAMAGE_ROLLED' and e.payload.get('damage_label') == group['name']]
    assert len(spent) == len(damage) == int(not decline)
    cost = 1 if modifier == SOUND else 2
    pool = 'resource:core.qi' if scenario == 'one-payment' else 'resource:core.stamina'
    assert engine.state.actors[LEFT].resources[pool] == before['actors'][LEFT]['resources'][pool] - (0 if decline else cost)


@pytest.mark.parametrize('count', [1, 2])
def test_compiled_augments_keep_parent_rider_commit_reload(tmp_path, monkeypatch, hits, count):
    # Synthetic range augments exercise the real compiler's single/composed
    # variant paths, without changing or inventing production printed rules.
    from tests import hunt36_support
    original_compile = hunt36_support.compile_character
    original_sheet = hunt36_support.sheet
    authority = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())
    augment_ids = ['TEST_SOLFSOL117_REACH', 'TEST_SOLFSOL117_RANGE']
    authority['mechanics'][SOUND]['modifier']['targets'] = ['Wind Lash']
    for key in augment_ids:
        mechanic = copy.deepcopy(authority['mechanics'][SOUND])
        mechanic['name'] = key.rsplit('_', 1)[-1].title() + ' test augment'
        mechanic['modifier'] = {'targets': ['Wind Lash'], 'scope': 'named',
            'when': 'use', 'optional': True, 'group': 'augment', 'extra_cp': 1, 'add_range_ft': 5, 'effects': []}
        authority['mechanics'][key] = mechanic
    def compile_augments(*args, **kwargs):
        return original_compile(*args, typed_authority=authority, **kwargs)
    monkeypatch.setattr(hunt36_support, 'compile_character', compile_augments)
    def augmented_sheet(mids, **kwargs):
        doc = original_sheet([m for m in mids if m not in augment_ids], **kwargs)
        if SOUND in mids:
            doc['spheres_and_talents']['learned_talent_record_ids'].extend(augment_ids)
        return doc
    monkeypatch.setattr(hunt36_support, 'sheet', augmented_sheet)
    combat, table, mid = fight(tmp_path, [SOUND, 'AIR_BASE_WIND_LASH'], primary='Stamina', cl=5, seed='SOLFSOL117-AUG',
                              positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 5, 'y': 6}})
    turn(combat, table, mid)
    engine = reload(combat, mid)
    parent = next(a.source_definition_id for a in engine.action_catalog.values() if
        not a.parameters.get('typed', {}).get('variant_of') and
        a.display_name == 'Wind Lash: Cut' and
        a.parameters.get('typed', {}).get('attack_modifier_loadout'))
    for field, value in (('on', 'toggle'), ('option', '0'), ('payment', '0')):
        choose(combat, table, mid, parent, SOUND, field, value)
    for key in augment_ids[:count]:
        engine = reload(combat, mid)
        action = next(a for a in engine.action_catalog.values() if a.parameters.get('augment_toggle') == parent
                      and a.parameters.get('augment_key') == key)
        send(combat, table, mid, next(c.candidate_id for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id))
    engine = reload(combat, mid)
    variant = next(a for a in engine.action_catalog.values() if a.parameters.get('typed', {}).get('variant_of') == parent
                   and set(a.parameters['typed'].get('augments', [])) == set(augment_ids[:count]))
    before = dict(engine.state.actors[LEFT].resources)
    sequence = engine.state.event_sequence
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == variant.source_definition_id and c.target_ids == (RIGHT,))
    prompts = send(combat, table, mid, candidate.candidate_id)
    assert not [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.attack_modifier']
    engine = reload(combat, mid)
    events = [e for e in engine.events if e.sequence > sequence]
    assert len([e for e in events if e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == SOUND]) == 1
    assert len([e for e in events if e.event_type == 'DAMAGE_ROLLED' and e.payload.get('damage_label') == 'Body Resonance Strike']) == 1
    assert engine.state.actors[LEFT].resources['resource:core.stamina'] == before['resource:core.stamina'] - count - 1


def test_embedded_rider_is_excluded_from_inherited_loadout(tmp_path, hits):
    combat, table, mid = fight(tmp_path, [SOUND, IRON], primary='Stamina', cl=5, seed='SOLFSOL117-EMBEDDED')
    turn(combat, table, mid)
    engine = reload(combat, mid)
    parent = next(a.source_definition_id for a in engine.action_catalog.values() if a.display_name == 'Iron Fist attack')
    for field, value in (('on', 'toggle'), ('option', '0'), ('payment', '0')):
        choose(combat, table, mid, parent, SOUND, field, value)
    engine = reload(combat, mid)
    variant = next(a for a in engine.action_catalog.values() if a.parameters.get('typed', {}).get('variant_of') == parent
                   and a.parameters['typed'].get('modifier', {}).get('id') == SOUND and
                   any(resource == 'resource:core.stamina' for resource, _ in a.costs))
    assert not variant.parameters['typed'].get('attack_modifier_loadout')
    sequence = engine.state.event_sequence
    before = engine.state.actors[LEFT].resources['resource:core.stamina']
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == variant.source_definition_id and c.target_ids == (RIGHT,))
    assert not [p for p in send(combat, table, mid, candidate.candidate_id)
                if p['context']['reaction_source_id'] == 'choice:needle.attack_modifier']
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources['resource:core.stamina'] == before - 1
    assert len([e for e in engine.events if e.sequence > sequence and e.event_type == 'DAMAGE_ROLLED'
                and e.payload.get('damage_label') == 'Body Resonance Strike']) == 1


def test_augmented_weapon_uses_configured_family_without_legacy_prompt(tmp_path, monkeypatch, hits):
    from tests import hunt36_support
    original_compile, original_sheet = hunt36_support.compile_character, hunt36_support.sheet
    authority = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())
    key = 'TEST_SOLFSOL117_WEAPON_REACH'
    mechanic = copy.deepcopy(authority['mechanics'][NULL])
    mechanic['name'] = 'Test weapon reach'
    mechanic['modifier'] = {'targets': ['Melee weapon attack'], 'scope': 'named', 'when': 'use', 'optional': True,
                            'group': 'augment', 'extra_cp': 1, 'add_range_ft': 5, 'effects': []}
    authority['mechanics'][key] = mechanic
    def compiler(*args, **kwargs):
        return original_compile(*args, typed_authority=authority, **kwargs)
    def document(mids, **kwargs):
        doc = original_sheet(mids, **kwargs)
        if NULL in mids:
            doc['spheres_and_talents']['learned_talent_record_ids'].append(key)
        return doc
    monkeypatch.setattr(hunt36_support, 'compile_character', compiler)
    monkeypatch.setattr(hunt36_support, 'sheet', document)
    # Keep the inventory minimal; hits scripts both d20s if Disadvantage applies.
    kit = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.bi_shou', 'quantity': 1}]}}
    combat, table, mid = fight(tmp_path, [NULL], primary='Stamina', cl=5, seed='SOLFSOL117-WEAPON', kit=kit)
    turn(combat, table, mid)
    engine = reload(combat, mid)
    parent = next(a.source_definition_id for a in engine.action_catalog.values() if '.weapon.' in a.source_definition_id
                  and not a.parameters.get('typed', {}).get('variant_of') and a.parameters.get('typed', {}).get('attack_modifier_loadout'))
    # Legacy paid weapon riders start on; the first configuration toggle turns
    # that default off, so toggle twice to explicitly retain enabled behavior.
    for field, value in (('on', 'toggle'), ('on', 'toggle'), ('option', '1'), ('payment', '0'), ('damage', 'force')):
        choose(combat, table, mid, parent, NULL, field, value)
    engine = reload(combat, mid)
    variant = next(a for a in engine.action_catalog.values() if a.parameters.get('typed', {}).get('variant_of') == parent
                   and a.parameters['typed'].get('modifier', {}).get('id') == key)
    before, sequence = engine.state.actors[LEFT].resources['resource:core.stamina'], engine.state.event_sequence
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == variant.source_definition_id and c.target_ids == (RIGHT,))
    assert not send(combat, table, mid, candidate.candidate_id)
    engine = reload(combat, mid)
    events = [e for e in engine.events if e.sequence > sequence]
    assert engine.state.actors[LEFT].resources['resource:core.stamina'] == before - 3
    assert len([e for e in events if e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == NULL]) == 1
    assert len([e for e in events if e.event_type == 'DAMAGE_ROLLED' and e.payload.get('damage_label') == 'Nullifying Strike']) == 1
    assert sum(m.value for m in engine.state.actors[RIGHT].modifiers.values() if m.target_field == 'speed_ft') == -10
