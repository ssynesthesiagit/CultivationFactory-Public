"""Continuation must be inert on persistence's temporary stock-only roster."""
from types import SimpleNamespace
import pytest
from combat.ext.stone_fist_journey import restore


@pytest.mark.parametrize('rows',[[],[{'block':'stone_fist_continuation',
    'state':{'scene_used':1,'guards':[],'conditions':[]}}]])
def test_missing_factory_actor_does_not_restore_into_temporary_roster(rows):
    engine=SimpleNamespace(typed_bundle_documents=[{'actor_id':'actor:factory.absent','typed_passives':rows}],
                           state=SimpleNamespace(actors={}))
    restore(engine)
    assert engine.state.actors=={}
