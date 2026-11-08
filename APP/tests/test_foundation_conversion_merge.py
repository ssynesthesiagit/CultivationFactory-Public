"""Reed's shared provider extensions preserve main's Foundation controls."""
from types import SimpleNamespace

import pytest

from combat.ext import foundation_conversion_bonus as bonus
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import OWNER, candidate, fixture, reload, settle


@pytest.mark.parametrize('excluded', [False, True])
def test_table_recovery_retains_source_specific_exclusion_after_reload(tmp_path, excluded):
    source = 'foundation.sword_bones_v0_2B.perfected_bone_deep_severance'
    doc = sheet([])
    doc['foundation'] = {'foundation_id': 'sword_bones_v0_2B',
                         'stage': 'Perfected', 'status': 'Suppressed'}
    if excluded:
        doc['foundation']['suppressed_or_excluded_benefits'] = [{
            'benefit': source, 'reason': 'This benefit remains excluded after recovery.',
            'source_packet_ids': ['test:source-exclusion']}]
    bundle = compile_character(doc, actor_id=OWNER)
    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle)
    engine = reload(tmp_path, mid)
    assert bonus.conversion_bonus(engine, engine.state.actors[OWNER], 'cut') == 0
    settle(table, mid, candidate(combat, mid, 'Foundation: record recovery').candidate_id)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert bonus.conversion_bonus(engine, actor, 'cut') == (0 if excluded else 4)
    assert bonus.conversion_available(engine, actor, source) is not excluded
    status = next(c for c in actor.conditions.values() if c.condition_id == bonus.SOURCE_STATUS)
    assert status.data['status'] == 'available'
    assert status.data['provenance'] == 'accepted table setting: Game Master ruling'
    assert combat._load_session(mid).verify()['status'] == 'PASS'


def test_flat_scoped_bonus_preserves_consent_without_claiming_round():
    feature = 'test:evolution'
    row, = bonus.compile_bonus(bonus.BLOCK, {
        'conversions': ['reed_slip'], 'once_round': True, 'scope': ['escape'],
        'conversion_values': {'reed_slip': {'flat': 5}}},
        {'feature_id': feature, 'block': bonus.BLOCK},
        {'pb': 4, 'record': {'name': 'Test evolution'}})
    actor = SimpleNamespace(entity_id=OWNER, active=True, current_hp=20,
                            conditions={}, turn_flags={})
    engine = SimpleNamespace(typed_passive_rows={OWNER: [row]}, typed_bundle_documents=[],
                             state=SimpleNamespace(round_number=1))
    assert bonus.conversion_bonus(engine, actor, 'reed_slip') == 0
    assert bonus.conversion_consent_note(engine, actor, 'reed_slip') == ''
    assert bonus.conversion_bonus(engine, actor, 'reed_slip', named=['escape']) == 5
    assert 'shared once-per-round benefit' in bonus.conversion_consent_note(
        engine, actor, 'reed_slip', named=['escape'])
    assert row['name'] == 'Test evolution'
    assert actor.turn_flags == {}
