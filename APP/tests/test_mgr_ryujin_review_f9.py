"""F9 review regressions: exact teardown identities and prompts using public synthetic fixtures."""
from types import SimpleNamespace

import pytest

from combat.ext import ryujin


def test_generated_scales_keeps_reviewed_single_damage_provider():
    """A main merge must not restore the replaced optional damage modifier."""
    import json
    from pathlib import Path
    app = Path(__file__).resolve().parents[1]
    mid = ryujin.PREFIX + 'dragon_scales'
    reviewed = json.loads((app / 'authority/typed_mechanics/reviewed_final.d/mgr_ryujin.json').read_text())['mechanics'][mid]
    generated = json.loads((app / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics'][mid]
    assert not generated.get('modifier')
    assert generated['effects'] == reviewed['effects']
    assert generated['typing_status'] == 'reviewed_final'


@pytest.mark.parametrize('reason', ['replacement', 'Unconsciousness'])
def test_form_teardown_keeps_replay_instance_identity(reason):
    """A reason must accompany, rather than replace, the removal identity."""
    source = 'action:test.form'
    actor = SimpleNamespace(entity_id='owner', conditions={}, modifiers={})
    actor.conditions['form'] = SimpleNamespace(
        source_actor_id='owner', source_definition_id=source,
        condition_id='condition:typed.state.' + ryujin.FORM)
    actor.modifiers['reach'] = SimpleNamespace(
        source_actor_id='owner', source_definition_id=source)
    removals = []
    def remove(holder, key, source, **kwargs):
        removals.append((key, kwargs['payload']))
    engine = SimpleNamespace(
        action_catalog={'form': SimpleNamespace(owner_id='owner',
            source_definition_id=source, parameters={'typed': {'source': ryujin.PREFIX + ryujin.FORM}})},
        state=SimpleNamespace(zones={}),
        _remove_condition_instance=remove, _remove_modifier_instance=remove)
    ryujin.end_ascendant_form(engine, actor, reason)
    assert removals == [
        ('form', {'instance_id': 'form', 'condition_id': 'condition:typed.state.' + ryujin.FORM, 'reason': reason}),
        ('reach', {'modifier_id': 'reach', 'reason': reason}),
    ]


def test_breath_damage_prompt_names_only_perceived_creatures(monkeypatch):
    from combat import senses
    from combat.ext import needle
    owner = SimpleNamespace(entity_id='owner', display_name='Dragon')
    ally = SimpleNamespace(entity_id='ally', display_name='Partner')
    foe = SimpleNamespace(entity_id='foe', display_name='Opponent')
    hidden = SimpleNamespace(entity_id='hidden', display_name='Secret Enemy')
    monkeypatch.setattr(senses, 'perceives', lambda engine, actor, target: target is not hidden)
    captured = {}
    def ask(*args, **kwargs):
        captured.update(kwargs)
        return ['THUNDER']
    monkeypatch.setattr(needle, 'ask', ask)
    monkeypatch.setattr(needle, 'checkpoint_id', lambda *args: 'checkpoint')
    ctx = SimpleNamespace(typed={'source': ryujin.PREFIX + 'dragon_s_breath'},
        damage_cache={}, engine=object(), intent=object(), actor=owner,
        action=SimpleNamespace(display_name="Dragon's Breath", costs=[('resource:core.stamina', 2)]))
    assert ryujin.damage_choice(ctx, ['LIGHTNING', 'THUNDER'], [ally, foe, hidden]) == 'THUNDER'
    assert 'Partner' in captured['prompt'] and 'Opponent' in captured['prompt']
    assert 'Secret Enemy' not in captured['prompt']
    assert '2 Stamina' in captured['prompt']


@pytest.mark.parametrize('step', [False, True])
def test_native_damage_prompt_has_recipient_or_chosen_landing_context(tmp_path, step):
    from tests.test_mgr_ryujin_native import game, fight, cold, candidate, settle
    service, jid, _ = game(tmp_path, cl=10)
    service, table, mid = fight(service, jid, tmp_path)
    action = candidate(service, mid, 'Storm Step' if step else "Dragon's Breath", at=(7, 6) if step else (5, 6))
    prompts = settle(table, mid, action.candidate_id, choices={
        'choice:needle.teleport_destination': ['cell:7,6'],
        'choice:needle.ryujin_damage': ['THUNDER'],
        'choice:needle.storm_recipients': None,
    })
    damage = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.ryujin_damage')
    text = damage['moment']
    if step:
        assert '7,6' in text and 'after arriv' in text.lower() and '5 feet' in text
        assert 'identify' in text
    else:
        assert 'Partner' in text and 'Opponent' in text
    assert ('3 Stamina' if step else '2 Stamina') in text
    cold(tmp_path, mid)
