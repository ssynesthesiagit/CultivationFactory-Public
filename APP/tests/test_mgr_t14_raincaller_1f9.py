"""Sol 1F8R regressions: source metadata stays with Sovereign-purifiable conditions; journey revisions are strict."""
from types import SimpleNamespace

import pydantic
import pytest

from app.models import JourneyWorldFactRequest, JourneySceneEndRequest
from combat.ext import mgr_reserve_raincaller_cultivator_call_rain as rain

PLAYER = SimpleNamespace(entity_id='actor:player', team_id='team:player')
FOE = SimpleNamespace(entity_id='actor:foe', team_id='team:foe')


def fight(*owned):
    """Stub engine: each actor holds the raincaller rows for the features in `owned`."""
    rows = {PLAYER.entity_id: [{'block': 'raincaller_acquired', 'feature_id': f} for f in owned]}
    return SimpleNamespace(state=SimpleNamespace(actors={PLAYER.entity_id: PLAYER, FOE.entity_id: FOE}),
                           typed_passive_rows=rows)


def hook(engine, subject, condition):
    ctx = SimpleNamespace(engine=engine, numbers={'cl': 3, 'save_dc': 12}, typed={})
    return rain.remember_native_condition_source(ctx, subject, {'condition': condition}, {})


def test_call_rain_alone_does_not_stamp_unrelated_or_foreign_conditions():
    # A CL3 Raincaller who owns only Call Rain cannot yet Purify, so no creature's condition gets Sovereign-source metadata.
    engine = fight(rain.CALL)
    assert hook(engine, PLAYER, 'poisoned') is None
    assert hook(engine, FOE, 'poisoned') is None
    assert hook(engine, PLAYER, 'burning') is None


def test_sovereign_metadata_is_limited_to_purifiable_conditions_on_allies():
    engine = fight(rain.CALL, rain.WALL, rain.SOVEREIGN)
    # Unrelated condition on an ally, and a purifiable condition on a creature that is not the Sovereign's ally.
    assert hook(engine, PLAYER, 'burning') is None
    assert hook(engine, FOE, 'poisoned') is None
    # The purifiable case still records the source facts a later Purification needs.
    assert hook(engine, PLAYER, 'poisoned') == {'information_profile': {'source_cl': 3, 'save_dc': 12}}


@pytest.mark.parametrize('bad', [-1, '3'])
def test_journey_world_fact_revision_is_a_nonnegative_integer(bad):
    with pytest.raises(pydantic.ValidationError):
        JourneyWorldFactRequest(revision=bad, payload={})
    with pytest.raises(pydantic.ValidationError):
        JourneySceneEndRequest(revision=bad, reason='scene')
    assert JourneyWorldFactRequest(revision=0, payload={}).revision == 0
