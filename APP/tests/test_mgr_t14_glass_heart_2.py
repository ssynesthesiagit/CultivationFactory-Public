"""Source/admission checks and existing resource delivery; not spend completion.

Neither assigned printed row specifies its positive numeric benefit. These
checks preserve provenance and demonstrate the existing production resource
producer without fabricating a Rebuke falsehood or a Witness roll bonus.
"""
import hashlib
import json
from pathlib import Path

import pytest

from non_sphere_authority.foundation_features import features_for_stage
from non_sphere_authority.foundation_mechanics import verified_foundation_records
from tests.test_a2_foundations_two import table_fixture, use
from tests.worker2_support import ALLY, OWNER, reload


FOUNDATION = 'glass_heart_meridian_v0_2A'
PREFIX = 'foundation.' + FOUNDATION + '.'
PINS = {
    'clear_heart_rebuke': '5ed4d4f5779851f7b8c42611d380bbd7d9b170ad79e466ad37154239045f9eb3',
    'transparent_witness': '0329b48d4b7d5e3fe095c25e4e5469748fe377554d3275efd236b2e8f7f44ed6',
}
APP = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('leaf', PINS)
def test_full_source_pin_and_verified_builder_projection(leaf):
    rules = json.loads((APP / 'authority/typed_mechanics/rules_text.json').read_text())
    text = rules[PREFIX + leaf]
    assert hashlib.sha256(text.encode()).hexdigest() == PINS[leaf]
    record = verified_foundation_records()[FOUNDATION]
    artifact = APP / 'non_sphere_authority/authority' / record['source']['artifact']
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == record['source']['artifact_sha256']
    row = next(r for r in features_for_stage(FOUNDATION, 'Awakened') if r['id'] == PREFIX + leaf)
    projected = '#### ' + row['name'] + '\n\n' + '\n'.join(
        f'**{key}:** {value}' for key, value in row['fields'].items()) + '\n'
    # build_typed_mechanics_authority.build strips published rules_text at
    # its final export, after constructing the source row with a newline.
    assert projected.strip() == text
    assert row['fields']['Cost'] == 'Spend 1 Glass Reflection'


@pytest.mark.parametrize('stage,admitted', [
    ('Latent', False), ('Awakened', True), ('Refined', True), ('Perfected', True),
])
def test_both_rows_follow_cumulative_source_stage_admission(stage, admitted):
    owned = {r['id'] for r in features_for_stage(FOUNDATION, stage)}
    assert all((PREFIX + leaf in owned) == admitted for leaf in PINS)
    other = {r['id'] for r in features_for_stage('jade_furnace_meridian_v0_2B', stage)}
    assert not other.intersection(PREFIX + leaf for leaf in PINS)


@pytest.mark.parametrize('ask', [True, False])
def test_existing_paid_technique_producer_commits_and_cold_reloads(tmp_path, ask):
    combat, table, mid = table_fixture(
        tmp_path, 'glass', current=0, stage='Awakened',
        talents=('TAL_ILLUSION_CONTROL_FIGMENT',), ask=ask)
    pool = 'resource:foundation.glass_reflection'
    before = reload(tmp_path, mid)
    assert before.state.actors[OWNER].resources[pool] == 0
    qi = before.state.actors[OWNER].resources['resource:core.qi']
    use(combat, table, mid, 'Figment: larger cube (1 CP)')
    use(combat, table, mid, 'Create Figment', at=(7, 6))
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources['resource:core.qi'] == qi - 1
    assert owner.resources[pool] == owner.resource_maximums[pool] == 1
    assert engine.state.actors[ALLY].resources.get(pool, 0) == 0
    gains = [e for e in engine.events if e.event_type == 'RESOURCE_GAINED'
             and e.actor_id == OWNER and e.payload.get('resource_id') == pool]
    assert len(gains) == 1
    payments = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
                and e.actor_id == OWNER and e.payload.get('resource_id') == 'resource:core.qi']
    assert len(payments) == 1 and payments[0].sequence < gains[0].sequence
