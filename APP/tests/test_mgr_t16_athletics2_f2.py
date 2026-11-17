"""Explicit movement consent keeps its intent through display-only provenance.

Exercise the advertised wants_opportunity_attack seam with a real controller
engine and compiled Ask-me row, without apply_intent's global-intent scope.
"""
import pytest

from combat import typed_reactions
from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from tests.test_reaction_ask import _fight, MOVER, GUARD
from combat.gate5_service import FACTORY_ACTOR_PREFIX


@pytest.fixture(scope='module')
def consent_engine(tmp_path_factory):
    service, _, match_id = _fight(tmp_path_factory.mktemp('explicit-consent'))
    return service._load_session(match_id).engine


def setup_consent(engine, named_source):
    mover = engine.state.actors[FACTORY_ACTOR_PREFIX + MOVER]
    reactor = engine.state.actors[FACTORY_ACTOR_PREFIX + GUARD]
    row = next(r for r in engine.typed_reaction_rows[reactor.entity_id] if r['block'] == 'opportunity')
    row.pop('consent_source_id', None)
    if named_source:
        row['consent_source_id'] = 'reaction:core.opportunity_attack'
    source = row.get('consent_source_id') or f"reaction:typed.{row['feature_id']}"
    answer = ReactionDecision(checkpoint=typed_reactions.ask_key('LEAVE_REACH', engine),
        reactor_id=reactor.entity_id, reaction_source_id=source, selection='USE')
    intent = ActionIntent(intent_id='explicit-movement', decision_id='explicit-consent',
        candidate_id='explicit-movement', state_version=engine.state.state_version, actor_id=mover.entity_id)
    engine._active_intent = None
    engine._gate4_reaction_cache.clear()
    engine._gate4_reaction_provider = None
    display = {'actor_id': mover.entity_id, 'target_id': reactor.entity_id,
               'source_id': 'TAL_ATHLETICS_WALL_STUNT', 'action_name': 'Wall Stunt'}
    return mover, reactor, intent, answer, display


@pytest.mark.parametrize('named_source', [False, True])
@pytest.mark.parametrize('transport', ['embedded', 'provider'])
@pytest.mark.parametrize('selection', ['USE', 'DECLINE'])
def test_explicit_intent_without_global_preserves_answer_and_display(consent_engine, named_source, transport, selection):
    engine = consent_engine
    mover, reactor, intent, answer, display = setup_consent(engine, named_source)
    answer = answer.model_copy(update={'selection': selection})
    requests = []

    def provider(request):
        requests.append(request)
        return answer, None

    engine._gate4_reaction_provider = provider
    if transport == 'embedded':
        intent = intent.model_copy(update={'reaction_decisions': (answer,)})
    previous = {'checkpoint': 'parent'}
    engine._reaction_trigger = previous
    before = engine.state.model_dump(mode='json')
    assert typed_reactions.wants_opportunity_attack(engine, reactor, mover,
        intent=intent, consent_display=display) is (selection == 'USE')
    assert engine._active_intent is None
    assert engine._reaction_trigger is previous
    assert engine.state.model_dump(mode='json') == before
    if transport == 'embedded':
        assert not requests, 'An embedded answer must precede the provider'
    else:
        assert len(requests) == 1, 'Ask me must consult the provider, including for Decline'
        request = requests[0]
        assert request['checkpoint'] == answer.checkpoint
        assert request['reaction_source_id'] == answer.reaction_source_id
        assert request['reactor_id'] == reactor.entity_id
        assert request['attacking_actor_id'] == mover.entity_id
        assert request['protected_target_id'] == reactor.entity_id
        assert request['choice_trigger']['source_definition_id'] == 'TAL_ATHLETICS_WALL_STUNT'
        assert request['choice_trigger']['action_name'] == 'Wall Stunt'


@pytest.mark.parametrize('named_source', [False, True])
def test_explicit_intent_precedes_stale_global_intent(consent_engine, named_source):
    engine = consent_engine
    mover, reactor, intent, answer, display = setup_consent(engine, named_source)
    explicit = intent.model_copy(update={'reaction_decisions': (answer,)})
    stale = intent.model_copy(update={'reaction_decisions': (answer.model_copy(update={'selection': 'DECLINE'}),)})
    engine._active_intent = stale
    assert typed_reactions.wants_opportunity_attack(engine, reactor, mover,
        intent=explicit, consent_display=display)
    assert engine._active_intent is stale


@pytest.mark.parametrize('named_source', [False, True])
def test_missing_explicit_intent_keeps_global_fallback(consent_engine, named_source):
    engine = consent_engine
    mover, reactor, intent, answer, display = setup_consent(engine, named_source)
    engine._active_intent = intent.model_copy(update={'reaction_decisions': (answer,)})
    assert typed_reactions.wants_opportunity_attack(engine, reactor, mover, consent_display=display)
