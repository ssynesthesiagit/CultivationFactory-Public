"""Ask-me and turn limits through the persisted table, using sealed rider data."""
import pytest

from combat.gate4_engine import Gate4ControllerEngine
from tests.h1_support import script
from tests.hunt36_support import LEFT, RIGHT, fight, turn, send, reload
from tests.test_sol117_attack_modifiers import NULL, IRON, setting


@pytest.mark.parametrize('failed', [True, False])
def test_ask_me_rolls_back_and_respects_payment_damage_and_effect(tmp_path, monkeypatch, failed):
    from tests import hunt36_support
    original_sheet = hunt36_support.sheet
    def dual(*args, **kwargs):
        doc = original_sheet(*args, **kwargs)
        doc['ability_scores_and_statistics']['primary_resource']['definitions'] = [{'name': 'Stamina', 'max': 30}]
        doc['ability_scores_and_statistics']['technique_save_dc'] = 100 if failed else -100
        return doc
    monkeypatch.setattr(hunt36_support, 'sheet', dual)
    original = Gate4ControllerEngine._resolve_attack_spec
    def roll(engine, *args, **kwargs):
        script(engine, [19, *([1] * 100)])
        return original(engine, *args, **kwargs)
    monkeypatch.setattr(Gate4ControllerEngine, '_resolve_attack_spec', roll)
    combat, table, mid = fight(tmp_path, [NULL, IRON], cl=5, seed='SOL117-ASK')
    turn(combat, table, mid)
    engine = reload(combat, mid)
    parent = next(a.source_definition_id for a in engine.action_catalog.values() if a.display_name == 'Iron Fist attack')
    setting(combat, table, mid, parent, 'on', 'toggle')
    engine = reload(combat, mid)
    before = engine.state.model_dump(mode='json')
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == parent and c.target_ids == (RIGHT,))
    state = table.state(mid)
    result = table.act(mid, candidate.candidate_id, state['menu']['decision_id'], state['menu']['state_version'], state['last_sequence'], [])
    assert result['status'] == 'REACTION_REQUIRED'
    assert reload(combat, mid).state.model_dump(mode='json') == before
    prompts = send(combat, table, mid, candidate.candidate_id,
        pick=lambda option: any(word in option['label'] for word in ('Hollowed', 'Stamina', 'Necrotic')))
    rider_prompts = [p for p in prompts if p['context'].get('reaction_source_id') == 'choice:needle.attack_modifier']
    assert len(rider_prompts) == (3 if failed else 2)
    assert all('Nullifying Strike' in p['moment'] and 'Iron Fist attack' in p['moment'] and 'Visiting Fighter' in p['moment'] for p in rider_prompts)
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources['resource:core.qi'] == before['actors'][LEFT]['resources']['resource:core.qi']
    assert engine.state.actors[LEFT].resources['resource:core.stamina'] == before['actors'][LEFT]['resources']['resource:core.stamina'] - 2
    assert any(c.condition_id.endswith('.hollowed') for c in engine.state.actors[RIGHT].conditions.values()) == failed
    assert any(e.event_type == 'DAMAGE_COMMITTED' and e.payload.get('damage_type') == 'NECROTIC' for e in engine.events)


def test_generic_rider_turn_limit_is_paid_once_across_extra_attacks(tmp_path, monkeypatch):
    from tests import hunt36_support
    original_compile = hunt36_support.compile_character
    def limited(*args, **kwargs):
        bundle = original_compile(*args, **kwargs)
        for action in bundle['action_catalog']:
            typed = action['parameters'].get('typed') or {}
            for group in typed.get('attack_modifier_loadout') or []:
                if group['id'] == NULL:
                    group['name'] = 'Test once-per-turn rider'
                    for option in group['options']:
                        for row in option['effects']:
                            row.update(modifier_once='test-rider', modifier_once_period='turn')
        # Existing settings keep their owner identity; this is deliberately a
        # different rider's sealed turn contract, not a Nullifying special case.
        return bundle
    monkeypatch.setattr(hunt36_support, 'compile_character', limited)
    original = Gate4ControllerEngine._resolve_attack_spec
    def roll(engine, *args, **kwargs):
        script(engine, [19, *([1] * 100)])
        return original(engine, *args, **kwargs)
    monkeypatch.setattr(Gate4ControllerEngine, '_resolve_attack_spec', roll)
    extra = 'tianxia.path.body_refining.feature.extra_attack'
    combat, table, mid = fight(tmp_path, [NULL, IRON, extra], primary='Stamina', cl=5, seed='SOL117-LIMIT')
    turn(combat, table, mid)
    engine = reload(combat, mid)
    parent = next(a.source_definition_id for a in engine.action_catalog.values() if a.display_name == 'Iron Fist attack')
    for field, value in (('on', 'toggle'), ('option', '1'), ('payment', '0'), ('damage', 'force')):
        setting(combat, table, mid, parent, field, value)
    engine = reload(combat, mid)
    sequence = engine.state.event_sequence
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == parent and c.target_ids == (RIGHT,))
    send(combat, table, mid, candidate.candidate_id)
    events = [e for e in reload(combat, mid).events if e.sequence > sequence]
    assert len([e for e in events if e.event_type == 'ATTACK_ROLLED']) == 2
    assert len([e for e in events if e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == NULL]) == 1
    assert len([e for e in events if e.event_type == 'DAMAGE_ROLLED' and e.payload.get('damage_label') == 'Nullifying Strike']) == 1


def test_turning_off_restores_plain_parent_attack(tmp_path):
    combat, table, mid = fight(tmp_path, [NULL, IRON], primary='Stamina', cl=5, seed='SOL117-OFF')
    turn(combat, table, mid)
    engine = reload(combat, mid)
    parent = next(a.source_definition_id for a in engine.action_catalog.values() if a.display_name == 'Iron Fist attack')
    setting(combat, table, mid, parent, 'on', 'toggle')
    setting(combat, table, mid, parent, 'on', 'toggle')
    engine = reload(combat, mid)
    before = dict(engine.state.actors[LEFT].resources)
    sequence = engine.state.event_sequence
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == parent and c.target_ids == (RIGHT,))
    send(combat, table, mid, candidate.candidate_id)
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources == before
    assert not [e for e in engine.events if e.sequence > sequence and e.event_type == 'DAMAGE_ROLLED'
                and e.payload.get('damage_label') == 'Nullifying Strike']


def test_multiple_owned_modifiers_have_independent_rows_and_payments(tmp_path, monkeypatch):
    # Two different Sphere riders share an attack without overwriting each
    # other's loadout metadata or charging either before the parent hits.
    from tests import hunt36_support
    original = Gate4ControllerEngine._resolve_attack_spec
    def roll(engine, *args, **kwargs):
        script(engine, [19, *([1] * 100)])
        return original(engine, *args, **kwargs)
    monkeypatch.setattr(Gate4ControllerEngine, '_resolve_attack_spec', roll)
    sound = 'TAL_SOUND_BODY_RESONANCE_STRIKE'
    combat, table, mid = fight(tmp_path, [NULL, IRON, sound], primary='Stamina', cl=5, seed='SOL117-MULTIPLE')
    turn(combat, table, mid)
    engine = reload(combat, mid)
    parent = next(a.source_definition_id for a in engine.action_catalog.values() if a.display_name == 'Iron Fist attack')
    for field, value in (('on', 'toggle'), ('option', '0'), ('payment', '0'), ('damage', 'force')):
        setting(combat, table, mid, parent, field, value)
    engine = reload(combat, mid)
    for field, value in (('on', 'toggle'), ('option', '0'), ('payment', '0')):
        action = next(a for a in engine.action_catalog.values() if (a.parameters.get('attack_modifier_setting') or {}).get('family') == parent
            and a.parameters['attack_modifier_setting']['modifier'] == sound and a.parameters['attack_modifier_setting']['field'] == field
            and a.parameters['attack_modifier_setting']['value'] == value)
        engine = reload(combat, mid)
        send(combat, table, mid, next(c.candidate_id for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id))
    state = table.state(mid)
    row = next(e for e in state['shapes'][LEFT] if e['base'] == parent)
    assert {m['name'] for m in row['modifiers']} == {'Nullifying Strike', 'Body Resonance Strike'}
    assert all(m['on'] for m in row['modifiers'])
    engine = reload(combat, mid)
    before = engine.state.actors[LEFT].resources['resource:core.stamina']
    sequence = engine.state.event_sequence
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == parent and c.target_ids == (RIGHT,))
    send(combat, table, mid, candidate.candidate_id)
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources['resource:core.stamina'] == before - 3
    events = [e for e in engine.events if e.sequence > sequence]
    assert len([e for e in events if e.event_type == 'DAMAGE_ROLLED' and e.payload.get('damage_label') in ('Nullifying Strike', 'Body Resonance Strike')]) == 2
