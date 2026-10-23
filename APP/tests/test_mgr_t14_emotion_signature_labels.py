"""Emotional Signature text uses player-facing labels, never internal condition ids.

Synthetic fixtures only (public CI): the pulse receipt is built from fake
creatures and the consent, publish and visibility seams are replaced.
"""
from types import SimpleNamespace
from combat.ext import emotion_cultivator as E


class _Cond:
    def __init__(self, condition_id, data=None, source_actor_id='actor:factory.caster'):
        self.condition_id = condition_id
        self.data = data or {}
        self.source_actor_id = source_actor_id


class _Creature:
    def __init__(self, entity_id, display_name, conditions=()):
        self.entity_id = entity_id
        self.display_name = display_name
        self.conditions = {i: c for i, c in enumerate(conditions)}


class _Engine:
    def __init__(self):
        self.applied = []

    def _apply_condition(self, actor, condition_id, source, source_actor_id, **kwargs):
        self.applied.append(condition_id)


def test_emotional_signature_names_conditions_in_plain_words(monkeypatch):
    from combat import fact_consent_admission, observer_information, target_knowledge
    published = []
    monkeypatch.setattr(fact_consent_admission, 'admit_choice',
        lambda *a, **k: {'value': 'sorrow', 'receipt_id': 'receipt-1'})
    monkeypatch.setattr(target_knowledge, 'can_see', lambda *a, **k: True)
    monkeypatch.setattr(observer_information, 'publish',
        lambda engine, viewer, source, actor, kind, payload, expires: published.append(payload))
    monkeypatch.setattr(E, 'owns', lambda engine, actor, source: False)
    subject = _Creature('actor:factory.foe', 'Foe', [
        _Cond('condition:typed.emotional_sorrow'),
        _Cond('condition:typed.charmed'),
        _Cond('condition:typed.emotional_rage', data={'secret': True}),
        _Cond('condition:typed.frightened'),
        _Cond('condition:typed.frightened'),
    ])
    actor = _Creature('actor:factory.caster', 'Caster')
    ctx = SimpleNamespace(engine=_Engine(), target=subject, actor=actor, source='source:pulse',
        action=SimpleNamespace(display_name='Emotional Pulse'))
    E.pulse_outcome(ctx, {'failed': True, 'form': 'pulse_of_sorrow'})

    assert len(published) == 1
    payload = published[0]
    assert payload['perceived_conditions'] == ['Sorrow', 'Charmed', 'Frightened']
    text = payload['text']
    assert 'Sorrow' in text and 'Charmed' in text and 'Frightened' in text
    assert 'Rage' not in text  # a secret condition is never perceived
    for internal in ('condition:typed.', 'emotional_', 'frightened, ', 'charmed'):
        assert internal not in text
