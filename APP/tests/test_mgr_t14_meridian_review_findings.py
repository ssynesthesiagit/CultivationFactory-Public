"""Regressions for the five findings in the Meridian Physician review."""
from types import SimpleNamespace

import pytest

from app.models import CombatWorldFactRequest, JourneyWorldFactRequest


def test_world_fact_request_contracts_are_equally_strict_and_bounded():
    for model, revision_name in ((JourneyWorldFactRequest, 'revision'),
                                 (CombatWorldFactRequest, 'state_version')):
        valid = {revision_name: 0, 'payload': {'kind': 'clinical_source'}}
        model.model_validate(valid)
        with pytest.raises(Exception):
            model.model_validate({**valid, 'unexpected': True})
        with pytest.raises(Exception):
            model.model_validate({revision_name: -1, 'payload': {}})
        with pytest.raises(Exception):
            model.model_validate({revision_name: 1, 'payload': {str(i): i for i in range(65)}})


def test_veil_rechecks_only_owning_actors_and_default_is_inert():
    from combat.ext.disease import veil_choice_reactors
    engine = SimpleNamespace(
        state=SimpleNamespace(actors={'owner': object(), 'other': object()}, zones={
            'veil': SimpleNamespace(active=True, owner_id='owner',
                                    trigger_profile={'veil_recipients': ['target']}),
            'ordinary': SimpleNamespace(active=True, owner_id='other', trigger_profile={}),
        }))
    assert veil_choice_reactors(engine) == ('owner',)
    engine.state.zones['veil'].active = False
    assert veil_choice_reactors(engine) is None
