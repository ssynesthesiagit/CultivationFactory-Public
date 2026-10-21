"""Sol F8 review regressions: spent Restful Dream HP and nonjourney finish vetoes."""
from types import SimpleNamespace

import pytest

from combat.ext.restful_dream_journey import KEY as RESTFUL_KEY, combat_setup
from combat.ext.journey_native_choices import KEY as NATIVE_KEY, clear_pending
import json

RESTFUL_SOURCE = 'DREAMS_BASE_RESTFUL_DREAM'


def engine_for(bundle, hp):
    actor = SimpleNamespace(temporary_hp=hp)
    return SimpleNamespace(typed_bundle_documents=[bundle],
                           state=SimpleNamespace(actors={bundle['actor_id']: actor}))


def bundle_with_grant(temporary_hp, encounter=None):
    bundle = {'actor_id': 'actor:a', 'restful_dream_setup': {'temporary_hp': temporary_hp}}
    if encounter is not None:
        bundle['journey_setup'] = {'encounter_snapshot': {'temporary_hp': encounter}}
    return bundle


def test_spent_restful_temp_hp_is_not_restored_on_combat_entry():
    # Travel damage spent 3 of the 4 temporary HP in the encounter snapshot.
    # The grant ledger still says 4; entering combat must keep the remaining 1.
    engine = engine_for(bundle_with_grant(4, encounter=1), hp=1)
    combat_setup(engine)
    assert engine.state.actors['actor:a'].temporary_hp == 1


def test_restful_temp_hp_grant_still_applies_before_any_encounter():
    # No encounter snapshot exists yet, so the rest grant is the only source.
    engine = engine_for(bundle_with_grant(4), hp=0)
    combat_setup(engine)
    assert engine.state.actors['actor:a'].temporary_hp == 4


def native_state(actors):
    return {'actors': actors}


def finish_session(state, journey_actors):
    return SimpleNamespace(state={'phase': 'travel', 'actors': {aid: {} for aid in journey_actors},
                                  NATIVE_KEY: {'state': json.dumps(state)}})


TIMED = {'expires_on': 'END_OF_TURN'}


def test_nonjourney_summon_timed_effect_does_not_veto_finish():
    # The summon is captured in the native encounter state but is not a journey
    # member; no journey clock can ever expire its effect.
    state = native_state({
        'actor:journey': {'conditions': {}, 'modifiers': {}},
        'summon:wolf': {'conditions': {'c': TIMED}, 'modifiers': {}},
    })
    clear_pending(finish_session(state, ['actor:journey']), 'actor:journey', 'finish', {})


def test_journey_member_timed_effect_still_vetoes_finish():
    state = native_state({'actor:journey': {'conditions': {'c': TIMED}, 'modifiers': {}}})
    with pytest.raises(ValueError, match='timed ongoing effects'):
        clear_pending(finish_session(state, ['actor:journey']), 'actor:journey', 'finish', {})
