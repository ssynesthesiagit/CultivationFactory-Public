"""Supplemental catalog actions keep their individual economy, including Ready."""
from tests.test_auto_tabik import _engine, ME
from tests.test_lock_choices import install
from tests.test_lock2_prepared import request
from combat.prepared_actions import SOURCE
from combat.gate2_runtime_models import EconomyKind


def test_spent_action_retains_free_and_bonus_supplements_but_not_action_or_ready(monkeypatch):
    engine, _ = _engine([], foe_at=(4, 6))
    actor = engine.state.actors[ME]
    sources = {economy: f'test:supplement.{economy.lower()}'
               for economy in ('NONE', 'BONUS_ACTION', 'ACTION')}
    original = engine.action_catalog['system:combat.dodge']
    for economy, source in sources.items():
        engine.action_catalog[source] = original.model_copy(update={
            'source_definition_id': source, 'owner_id': ME, 'economy': EconomyKind(economy)})
    install(monkeypatch, 'additional_actions', lambda e, a:
        [*sources.values(), sources['NONE']] if a.entity_id == ME else [])
    install(monkeypatch, 'prepare_options', lambda e, a: [{'option_id': 'example',
        'source_id': 'test:ready', 'label': 'Example reaction', 'trigger': 'HOLD_POSITION_COMMITTED'}])
    dodge = next(c for c in engine.legal_candidates() if c.source_definition_id == 'system:combat.dodge')
    engine.execute_intent(request(engine, dodge))
    assert not actor.action_available and actor.bonus_action_available
    candidates = engine.legal_candidates()
    offered = [c.source_definition_id for c in candidates]
    assert offered.count(sources['NONE']) == 1
    assert sources['BONUS_ACTION'] in offered
    assert sources['ACTION'] not in offered
    assert not any(source.startswith(SOURCE + ':') for source in offered)
    bonus = next(c for c in candidates if c.source_definition_id == sources['BONUS_ACTION'])
    engine.execute_intent(request(engine, bonus))
    offered = [c.source_definition_id for c in engine.legal_candidates()]
    assert offered.count(sources['NONE']) == 1
    assert sources['BONUS_ACTION'] not in offered
