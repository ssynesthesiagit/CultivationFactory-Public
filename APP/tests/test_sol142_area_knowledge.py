"""Area origins and scoring use perception, with real table casts and reloads."""
import pytest

from combat import senses, target_knowledge
from combat.gate4_context import build_decision_context
from combat.gate4_policy import PolicyLibrary
from combat.gate5_service import CombatService
from combat.gate2_runtime_models import Position
from tests.h1_support import ROOT
from tests.test_hidden_targeting import hidden_fight, LEFT, RIGHT


def area_context(engine, ability):
    policy, _ = PolicyLibrary(ROOT).for_actor(LEFT)
    return [candidate for candidate in build_decision_context(engine, policy, for_ai=True).legal_candidates
            if ability in candidate.source_definition_id]


@pytest.mark.parametrize('ability', ['FIRE_TAL_FIREBALL_ART', 'TAL_SOUND_RESONANT_SHATTER'])
def test_hidden_movement_cannot_change_ai_area_offers_or_scores(tmp_path, monkeypatch, ability):
    combat, _, mid = hidden_fight(tmp_path, monkeypatch, move=True, left_abilities=(ability,), left_primary='Stamina', greater_darkness=False)
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    remembered = target_knowledge.knowledge(engine, actor, target)
    assert remembered.mode == 'LAST_OBSERVED'
    assert remembered.position != target.position
    def signature():
        return [(c.destination.model_dump(mode='json'), c.metadata) for c in area_context(engine, ability)]
    before = signature()
    assert before
    # Counterfactual unknown movement, not an observation or persisted mutation.
    target.position = Position(x=17, y=12)
    assert not target_knowledge.located(engine, actor, target)
    assert target_knowledge.knowledge(engine, actor, target) == remembered
    assert signature() == before, 'AI area menu/scoring followed hidden movement'


def test_ai_area_aim_is_visible_square(tmp_path, monkeypatch):
    ability = 'FIRE_TAL_FIREBALL_ART'
    combat, _, mid = hidden_fight(tmp_path, monkeypatch, move=True, left_abilities=(ability,), left_primary='Stamina', greater_darkness=False)
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    actor = engine.state.actors[LEFT]
    candidates = area_context(engine, ability)
    assert candidates
    assert all(senses.perceives_cell(engine, actor, c.destination) for c in candidates), \
        'AI chose an unseen square nobody had located'
