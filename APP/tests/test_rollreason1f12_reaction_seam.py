"""ROLLREASON1F12: Spirit Intercession's roll receipt comes from its plug-in hook, not from core.

Synthetic engine only: no saved fight, no live server, public-CI safe.
"""
from types import SimpleNamespace

from combat import ext
from combat.roll_reasons import remember_reaction

REACTION = 'reaction:bai_meizhen.spirit_intercession'


def _engine():
    bai = SimpleNamespace(entity_id='bai', display_name='Bai Meizhen')
    frame = {}
    engine = SimpleNamespace(state=SimpleNamespace(actors={'bai': bai}), action_catalog={},
                             _d20_scopes=[frame])
    return engine, frame


def test_intercession_hook_answers_only_its_own_reaction():
    engine, _ = _engine()
    target = SimpleNamespace(entity_id='cui')
    rows = ext.run_strict('reaction_roll_reasons', engine, 'bai', REACTION, target)
    assert len(rows) == 1 and rows[0] == [{
        'effect': 'Spirit Intercession', 'owner': 'Bai Meizhen', 'kind': 'disadvantage',
        'why': 'the defender spends their Reaction on this attack'}]
    other = ext.run_strict('reaction_roll_reasons', engine, 'bai', 'reaction:bai_meizhen.other', target)
    assert other == []


def test_remember_reaction_records_receipt_in_current_frame():
    engine, frame = _engine()
    remember_reaction(engine, 'bai', REACTION, SimpleNamespace(entity_id='cui'))
    receipts = frame['mode_sources']
    assert [row['effect'] for row in receipts] == ['Spirit Intercession']
    assert receipts[0]['kind'] == 'disadvantage'
    remember_reaction(engine, 'bai', 'reaction:bai_meizhen.other', SimpleNamespace(entity_id='cui'))
    assert len(frame['mode_sources']) == 1

def test_resolved_reaction_hook_only_records_spirit_intercession():
    engine, frame = _engine()
    engine.state.actors['cui'] = SimpleNamespace(entity_id='cui', display_name='Cui')
    unrelated = SimpleNamespace(source_definition_id='reaction:other', actor_id='bai',
                                target_ids=('cui',))
    ext.run('reaction_resolved', engine, unrelated)
    assert frame.get('mode_sources', []) == []

    accepted = SimpleNamespace(source_definition_id=REACTION, actor_id='bai',
                               target_ids=('cui',))
    ext.run('reaction_resolved', engine, accepted)
    receipts = frame['mode_sources']
    assert len(receipts) == 1
    assert receipts[0]['effect'] == 'Spirit Intercession'
    assert receipts[0]['why'] == 'the defender spends their Reaction on this attack'
