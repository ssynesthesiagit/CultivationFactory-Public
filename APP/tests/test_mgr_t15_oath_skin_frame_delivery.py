"""Native journal delivery across cold services, legacy grants and two matches."""
from copy import deepcopy
import json

import pytest

from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat import table_advance
from combat.ext import oath_skin_frame as frame
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop import TabletopError
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_mgr_t15_oath_skin_frame import table_fixture, record
from tests.worker2_support import FOE, turn
from tests.test_mgr_t15_oath_skin_frame import OWNER, ALLY, _hex_owner  # noqa: F401  (hex owners for source-event routing)

PROJECT = OWNER.removeprefix('actor:factory.')


@pytest.fixture(scope='module')
def catalog():
    return CanonicalCatalogAuthorityService(ROOT)


def cold_table(root):
    return TabletopService(CombatService(ROOT, root), root)


def another_match(table, document):
    ids = [OWNER, ALLY, FOE]
    bundles = [compile_character(doc, actor_id=actor) for doc, actor in
               zip([document, sheet([]), sheet([])], ids)]
    combat = table.combat
    arena = combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    mid = combat._finish_factory_match(bundles, ids,
        {OWNER: 'team:factory', ALLY: 'team:factory', FOE: 'team:opponents'},
        {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 6, 'y': 6}},
        arena, [OWNER, ALLY], [FOE], control_modes={aid: 'MANUAL' for aid in ids},
        match_seed='FRAME-SECOND-MATCH', display_name='Another scene', maximum_rounds=15)['match_id']
    turn(table, mid, OWNER)
    return mid


def receipts(table):
    return table.buttons.get(PROJECT)['advancement']['source_events']


def test_delivery_preserves_all_table_grants_and_receipts_on_repeated_cold_sync(tmp_path, catalog):
    _, _, table, mid = table_fixture(tmp_path)
    table.canonical_catalog = catalog
    table.add_advancement(PROJECT, 'sphere', 'tianxia.sphere.magma', gm=True)
    table.add_advancement(PROJECT, 'talent', 'TAL_MAGMA_MANTLE_BREACH', gm=True)
    table.forge(PROJECT, {'name': 'Retained Mantle', 'base_form': 'burst',
        'primary_talent_id': 'TAL_MAGMA_MANTLE_BREACH', 'secondary_talent_ids': [],
        'augment_ids': [], 'drawback_ids': []}, gm=True, save=True)
    before = table.buttons.get(PROJECT)['advancement']
    before['manuals'].append({'id': 'table.manual.mantle', 'name': 'Mantle Manual',
                              'talents': ['TAL_MAGMA_MANTLE_BREACH'], 'gm': True})
    table.buttons.save_advancement(PROJECT, before)
    record(table, mid, 'integrated')
    for _ in range(3):
        table = cold_table(tmp_path)
        table.synchronize_source_events(mid)
        saved = table.buttons.get(PROJECT)['advancement']
        assert len(saved['source_events']) == 1
        for key in ('spheres', 'talents', 'forged', 'manuals'):
            assert saved[key] == before[key]
        updated = table.combat._factory_owner_sheet(PROJECT)
        assert updated['foundation']['stage'] == 'Integrated'
        assert 'TAL_MAGMA_MANTLE_BREACH' in updated['spheres_and_talents']['learned_talent_record_ids']
        assert updated['forged_techniques'][0]['name'] == 'Retained Mantle'
        bundle = compile_character(updated, actor_id=OWNER)
        actions = bundle['action_catalog']
        rows = actions.values() if isinstance(actions, dict) else actions
        assert any(row['display_name'] == 'Retained Mantle' for row in rows)


def test_legacy_advancement_without_source_events_normalizes_before_delivery(tmp_path, catalog):
    _, _, table, mid = table_fixture(tmp_path)
    table.canonical_catalog = catalog
    table.add_advancement(PROJECT, 'sphere', 'tianxia.sphere.magma', gm=True)
    # A valid pre-source-event button document, not an obsolete saved fight.
    path = table.buttons._path(PROJECT)
    old = json.loads(path.read_text())
    del old['advancement']['source_events']
    path.write_text(json.dumps(old))
    record(table, mid, 'suppressed')
    table = cold_table(tmp_path)
    table.synchronize_source_events(mid)
    assert len(receipts(table)) == 1
    assert table.buttons.get(PROJECT)['advancement']['spheres'] == old['advancement']['spheres']
    updated = table.combat._factory_owner_sheet(PROJECT)
    assert updated['foundation']['frame_available'] == 0
    assert 'tianxia.sphere.magma' in updated['spheres_and_talents']['sphere_record_ids']
    assert table.combat.verify(mid)['status'] == table.combat.replay(mid)['status'] == 'PASS'


def test_delayed_suppression_never_reverses_later_other_match_restoration(tmp_path, monkeypatch):
    document, _, table, older = table_fixture(tmp_path)
    newer = another_match(table, document)
    def interrupted(*args, **kwargs):
        raise OSError('simulated receipt write interruption after combat commit')
    with monkeypatch.context() as patch:
        patch.setattr(table.buttons, 'save_advancement', interrupted)
        with pytest.raises(OSError, match='receipt write interruption'):
            record(table, older, 'suppressed')
    table = cold_table(tmp_path)
    record(table, newer, 'available')
    already_projected = table.combat._factory_owner_sheet(PROJECT)
    assert already_projected['foundation']['frame_available'] == 1
    for _ in range(2):
        table = cold_table(tmp_path)
        table.synchronize_source_events(older)
        table.synchronize_source_events(newer)
        rows = receipts(table)
        assert [r['event']['kind'] for r in rows] == ['suppressed', 'available']
        assert 0 < rows[0]['event']['commit_order'] < rows[1]['event']['commit_order']
        updated = table.combat._factory_owner_sheet(PROJECT)
        assert updated['foundation']['frame_available'] == 1
        assert updated['ability_scores_and_statistics']['hit_points']['maximum'] == document['ability_scores_and_statistics']['hit_points']['maximum']
        assert table_advance.apply(already_projected, table.buttons.get(PROJECT)['advancement']) == updated
    for mid in (older, newer):
        assert table.combat.verify(mid)['status'] == table.combat.replay(mid)['status'] == 'PASS'


@pytest.mark.parametrize('withdrawal', ['fully_severed', 'replaced'])
def test_same_event_id_in_other_match_never_overwrites_irreversible_receipt(tmp_path, withdrawal):
    document, _, table, first = table_fixture(tmp_path)
    second = another_match(table, document)
    record(table, first, withdrawal, event_id='same-local-event-id')
    committed = deepcopy(receipts(table)[0])
    record(table, second, 'ordinary_dispel', event_id='same-local-event-id')
    for _ in range(3):
        table = cold_table(tmp_path)
        table.synchronize_source_events(second)
        table.synchronize_source_events(first)
        rows = receipts(table)
        assert len(rows) == 2
        assert rows[0] == committed
        assert {r['match_id'] for r in rows} == {first, second}
        updated = table.combat._factory_owner_sheet(PROJECT)
        assert updated['foundation']['frame_severed'] == 1
        assert len(updated['foundation']['frame_source_event_ids']) == 2
        assert updated['ability_scores_and_statistics']['hit_points']['maximum'] == document['ability_scores_and_statistics']['hit_points']['maximum'] - 4
        assert table_advance.apply(updated, table.buttons.get(PROJECT)['advancement']) == updated
    for mid in (first, second):
        assert table.combat.verify(mid)['status'] == table.combat.replay(mid)['status'] == 'PASS'


def test_receipt_conflict_is_rejected_without_replacing_committed_fact(tmp_path):
    _, _, table, mid = table_fixture(tmp_path)
    record(table, mid, 'ordinary_dispel')
    saved = table.buttons.get(PROJECT)['advancement']
    saved['source_events'][0]['journal_sha256'] = '0' * 64
    table.buttons.save_advancement(PROJECT, saved)
    with pytest.raises(ValueError, match='cannot be overwritten'):
        cold_table(tmp_path).synchronize_source_events(mid)
    assert receipts(table) == saved['source_events']


def test_source_event_order_cannot_be_supplied_by_a_caller(tmp_path):
    from tests.test_mgr_t15_oath_skin_frame import evidence
    _, _, table, mid = table_fixture(tmp_path)
    engine = table.combat._load_session(mid).engine
    with pytest.raises(TabletopError, match='assigned by the service'):
        table.record_source_event(mid, {'event_id': 'spoofed-order', 'actor_id': OWNER,
            'source_id': frame.FRAME, 'acquisition_id': frame.owned_row(engine, OWNER)['acquisition_id'],
            'kind': 'suppressed', 'data': {'source_sha256': frame.HASH}, 'commit_order': 999},
            evidence('suppressed'), engine.state.state_version)
    assert not any(e.event_type == 'SOURCE_EVENT_RECORDED'
                   for e in table.combat._load_session(mid).engine.events)


@pytest.mark.parametrize('tail_kind', ['ordinary_dispel', 'integrated'])
def test_projected_sheet_transport_keeps_new_service_transitions_newer_than_known_state(tmp_path, tail_kind):
    _, _, table, mid = table_fixture(tmp_path / 'origin')
    record(table, mid, 'suppressed')
    record(table, mid, 'available')
    record(table, mid, tail_kind)
    projected = table.combat._factory_owner_sheet(PROJECT)
    observed = receipts(table)[-1]['event']['commit_order']
    assert observed > projected['foundation']['frame_availability_order']
    document, _, transported, next_mid = table_fixture(
        tmp_path / 'destination', projected, seed='OATH-FRAME-DESTINATION')
    assert next_mid != mid
    amount = frame.owned_row(transported.combat._load_session(next_mid).engine, OWNER)['amount']
    record(transported, next_mid, 'suppressed')
    transported = cold_table(tmp_path / 'destination')
    transported.synchronize_source_events(next_mid)
    assert receipts(transported)[0]['event']['commit_order'] > observed
    updated = transported.combat._factory_owner_sheet(PROJECT)
    assert updated['foundation']['frame_available'] == 0
    maximum = document['ability_scores_and_statistics']['hit_points']['maximum']
    assert updated['ability_scores_and_statistics']['hit_points']['maximum'] == maximum - amount
    assert transported.combat._load_session(next_mid).engine.state.actors[OWNER].maximum_hp == maximum
    assert transported.combat.verify(next_mid)['status'] == transported.combat.replay(next_mid)['status'] == 'PASS'
