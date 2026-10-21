"""Small guard checks for the shared native packet and admission contracts.

These are seam guards, not whole-row or in-play acceptance evidence.
"""
from types import SimpleNamespace

import pytest

from combat.damage_provenance import packet_scope, grouped_notification_pending, source_flags_of
from combat.ext.adaptations import active_records, acquire, feature_available, opposition_schema, FAMILY
from combat.ext.activation_requirements import effective_cl
from combat.ext.fact_consent_admission import native_scene_owner_schema


def test_nested_grouped_packet_identity_restores_after_pause():
    engine = SimpleNamespace()
    def context(source):
        return SimpleNamespace(engine=engine, typed={}, damage_source=source,
                               actor=SimpleNamespace(entity_id='source'), damage_packet_kind='weapon')
    assert not grouped_notification_pending(engine, 'outer', 'source')
    with packet_scope(context('outer')):
        assert grouped_notification_pending(engine, 'outer', 'source')
        with pytest.raises(RuntimeError):
            with packet_scope(context('inner')):
                assert grouped_notification_pending(engine, 'inner', 'source')
                assert not grouped_notification_pending(engine, 'outer', 'source')
                raise RuntimeError('choice pause')
        assert grouped_notification_pending(engine, 'outer', 'source')
    assert not grouped_notification_pending(engine, 'outer', 'source')


@pytest.mark.parametrize('value', ['willing_cost', [1], [''], None])
def test_damage_flags_reject_non_source_schemas(value):
    with pytest.raises(ValueError):
        source_flags_of({'source_flags': value})


def test_empty_damage_flags_are_inert_and_explicit_flags_remain_exact():
    assert source_flags_of({}) == ()
    assert source_flags_of({'source_flags': ['willing_cost', 'bars_adaptation']}) == ('willing_cost', 'bars_adaptation')


def test_both_published_suppression_caps_use_one_reader():
    actor = SimpleNamespace(conditions={'a': SimpleNamespace(condition_id='condition:typed.cultivation_suppression',
        data={'rule': {'effective_cl': 14}}, source_definition_id='source:a'),
        'b': SimpleNamespace(condition_id='condition:typed.cultivation_limit',
        data={'rule': {'cultivation_cl_cap': 9}}, source_definition_id='source:b')})
    assert effective_cl(actor, 18) == 9


def test_absent_ownership_does_not_admit_a_record_or_grant_benefits():
    actor = SimpleNamespace(entity_id='owner', conditions={})
    engine = SimpleNamespace(typed_passive_rows={})
    assert not feature_available(engine, actor, 'damage')
    assert active_records(engine, actor, 'damage') == []
    assert acquire(engine, actor, 'damage', {'type': 'FIRE', 'by': 'foe'},
                   source=FAMILY + '.feature.flesh_remembers_pain') is False
    assert actor.conditions == {}


def test_scene_authority_schema_never_grants_creature_consent():
    session = SimpleNamespace(state={'actors': {'owner': {}}})
    assert native_scene_owner_schema(session, 'system:journey.scene', 'owner', 'scene_end')['authority'] == 'table_owner'
    assert native_scene_owner_schema(session, FAMILY, 'owner', 'scene_end') is None


def test_unowned_actor_does_not_admit_family_world_declarations():
    session = SimpleNamespace(state={'actors': {'owner': {'bundle': {'typed_passives': []}}}})
    assert opposition_schema(session, FAMILY, 'owner', 'opposition') is None
