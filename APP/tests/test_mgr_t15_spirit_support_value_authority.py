"""Regression: the Origin-Spirit Vessel support-value authority check (private-only).

Synthetic engine, actors and proposal only, but this file imports combat.ext.foundations3,
which the public export does not include (ci_route flags any `from combat.ext` import as
LOCAL), so it runs only in private CI. spirit_support_value must read the native
(method, authority) pair and apply the sphere / Foundation check before offering a bonus.
Before the fix the function raised NameError on any eligible value because `authority`
was never bound; this file fails on that code and passes after it.
"""
from types import SimpleNamespace

import pytest

from combat import support_values
from combat.ext import foundations3 as f3

OWNER = 'synthetic:owner'
SUBJECT = 'synthetic:subject'
SOURCE = 'synthetic:support_action'


def engine_with(pb=3):
    owner = SimpleNamespace(entity_id=OWNER, active=True, current_hp=10, turn_flags={})
    subject = SimpleNamespace(entity_id=SUBJECT, active=True, current_hp=10, turn_flags={}, display_name='Subject')
    state = SimpleNamespace(actors={OWNER: owner, SUBJECT: subject}, round_number=1)
    row = {'block': f3.SPIRIT_VALUE_BLOCK, 'kind': 'temporary_hp', 'feature_id': f3.SPIRIT_VESSEL, 'pb': pb}
    engine = SimpleNamespace(state=state, action_catalog={}, typed_passive_rows={OWNER: [row]},
                             _active_intent=None)
    proposal = SimpleNamespace(actor_id=OWNER, beneficiary_id=SUBJECT, kind='temporary_hp',
                               source_id=SOURCE, value=5, value_id='value:1')
    return engine, proposal


def native(sphere_id=None, foundation_id=None):
    authority = {'name': 'Synthetic support action', 'sphere_id': sphere_id,
                 'source': {'text_sha256': 'synthetic'}}
    if foundation_id is not None:
        authority['foundation_id'] = foundation_id
    return ('synthetic-method', authority)


@pytest.fixture
def use_native(monkeypatch):
    def install(value):
        monkeypatch.setattr(support_values, 'method_of', lambda engine, actor, source_id: value)
    return install


def test_eligible_support_value_offers_bonus_when_sphere_is_recognised(use_native):
    engine, proposal = engine_with(pb=3)
    use_native(native(sphere_id=sorted(f3.SPIRIT_SUPPORT_SPHERES)[0]))
    assert f3.spirit_support_value(engine, proposal, consume=False) == 3


def test_eligible_support_value_offers_bonus_for_origin_spirit_foundation(use_native):
    engine, proposal = engine_with(pb=2)
    use_native(native(sphere_id='tianxia.sphere.unrelated', foundation_id='origin_spirit_body_v0_2B'))
    assert f3.spirit_support_value(engine, proposal, consume=False) == 2


def test_unrelated_native_source_is_not_offered_the_bonus(use_native):
    engine, proposal = engine_with(pb=3)
    use_native(native(sphere_id='tianxia.sphere.unrelated', foundation_id='other_foundation'))
    assert f3.spirit_support_value(engine, proposal, consume=False) is None
