"""Unaffected menus do not load source classification for Hollow suppression.

These controls exercise the same providers with active recipient conditions:
the optimization must not infer immunity from a recipient lacking the talent.
"""
from types import SimpleNamespace

import pytest

from combat.ext import void_touched_hollow_field as hollow


SOURCE = "test.sphere.talent"
SPHERE = "tianxia.sphere.fire"


def _condition(condition_id, **data):
    return SimpleNamespace(condition_id=condition_id, data=data)


def _actor(*conditions):
    return SimpleNamespace(conditions={str(i): row for i, row in enumerate(conditions)})


def _action(source=SOURCE, **typed):
    return SimpleNamespace(parameters={"typed": {"source": source, **typed}})


@pytest.mark.parametrize("conditions", [(), (_condition("condition:unrelated"),)])
def test_unaffected_recipient_needs_no_authority_classification(monkeypatch, conditions):
    def unexpected(_source):
        raise AssertionError("An unaffected recipient must not load the authority")

    monkeypatch.setattr(hollow, "sphere_of_mechanic", unexpected)
    actor = _actor(*conditions)
    assert hollow.gate_candidates(None, actor, None, _action()) is None
    assert hollow.gate_rows(None, actor, {"feature_id": SOURCE}) is None


@pytest.mark.parametrize("inside,active,expected", [(True, True, False), (False, True, None), (True, False, None)])
def test_recipient_system_suppression_still_checks_classification_and_location(
        monkeypatch, inside, active, expected):
    classified = []

    def classify(source):
        classified.append(source)
        return SPHERE

    monkeypatch.setattr(hollow, "sphere_of_mechanic", classify)
    monkeypatch.setattr(hollow, "_zones_module", lambda: SimpleNamespace(
        actor_inside_zone=lambda engine, actor, zone: inside))
    actor = _actor(_condition(hollow.SYSTEM, zone="field", kind="sphere", value=SPHERE))
    engine = SimpleNamespace(state=SimpleNamespace(zones={"field": SimpleNamespace(active=active)}))
    assert hollow.gate_candidates(engine, actor, None, _action()) is expected
    assert hollow.gate_rows(engine, actor, {"feature_id": SOURCE}) is expected
    assert classified == [SOURCE, SOURCE]


def test_no_concentration_and_armament_vetoes_remain(monkeypatch):
    monkeypatch.setattr(hollow, "sphere_of_mechanic", lambda source: "")
    concentrating = _actor(_condition(hollow.NO_CONCENTRATION))
    action = _action(duration={"concentration": True})
    assert hollow.gate_candidates(None, concentrating, None, action) is False
    assert hollow.gate_candidates(None, concentrating, None, _action()) is None
    armament = _actor(_condition(hollow.ARMAMENT))
    assert hollow.gate_candidates(None, armament, None, _action(source="armament.test")) is False
    assert hollow.gate_candidates(None, armament, None, _action()) is None


def test_unknown_sources_keep_the_existing_neutral_contract(monkeypatch):
    monkeypatch.setattr(hollow, "sphere_of_mechanic", lambda source: "")
    actor = _actor(_condition(hollow.NO_CONCENTRATION))
    assert hollow.gate_candidates(None, actor, None, _action(source="", duration={"concentration": True})) is None
    assert hollow.gate_candidates(None, actor, None, None) is None


def test_explicit_sphere_needs_no_authority_fallback(monkeypatch):
    monkeypatch.setattr(hollow, "sphere_of_mechanic", lambda source: pytest.fail("Explicit sphere was already supplied"))
    monkeypatch.setattr(hollow, "_zones_module", lambda: SimpleNamespace(
        actor_inside_zone=lambda engine, actor, zone: True))
    actor = _actor(_condition(hollow.SYSTEM, zone="field", kind="sphere", value=SPHERE))
    engine = SimpleNamespace(state=SimpleNamespace(zones={"field": SimpleNamespace(active=True)}))
    assert hollow.gate_candidates(engine, actor, None, _action(sphere=SPHERE)) is False
    assert hollow.gate_rows(engine, actor, {"feature_id": SOURCE, "sphere": SPHERE}) is False
