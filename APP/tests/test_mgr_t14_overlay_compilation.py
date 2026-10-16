"""Acquired combat features must survive the public native-test snapshot."""
import pytest

from tests.worker2_support import fixture, reload, OWNER


@pytest.mark.parametrize('source,block', [
    ('EARTH_BASE_SPENDING_A_BURDEN_MARK', 'lane9_earth'),
    ('TAL_WRESTLING_HAMMERLOCK', 'wrestling_slam'),
])
def test_acquired_source_reaches_its_existing_native_provider(tmp_path, source, block):
    _, _, mid = fixture(tmp_path, [source], cl=18)
    engine = reload(tmp_path, mid)
    assert any(row.get('feature_id') == source and row.get('block') == block
               for row in engine.typed_passive_rows.get(OWNER, [])), {
        'source': source,
        'compiled_sources': [(row.get('feature_id'), row.get('block'))
                             for row in engine.typed_passive_rows.get(OWNER, [])]}
    if block == 'wrestling_slam':
        assert any(action.owner_id == OWNER and
                   (action.parameters.get('typed') or {}).get('source') == source and
                   '.granted.slam.' in action.source_definition_id
                   for action in engine.action_catalog.values())
