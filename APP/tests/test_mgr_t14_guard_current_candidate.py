"""Review gates: current-format continuation and current-tree native producers."""
import ast
from pathlib import Path

from combat.ext.soul_warden import DRAIN
from tests.guard_spirit_support import spirit_sheet
from tests.test_mgr_t14_guard_parent import setup, hit
from tests.worker2_support import ALLY, reload


def test_fresh_guard_fight_commits_and_continues_in_a_cold_service(tmp_path):
    combat, table, mid = setup(tmp_path)
    engine, _ = hit(tmp_path, combat, table, mid)
    assert any(event.event_type == 'SAVE_ROLLED' and event.actor_id == ALLY
               and event.source_definition_id == 'system:combat.concentration'
               and event.payload['mode'] == 'ADVANTAGE' for event in engine.events)
    assert reload(tmp_path, mid).state.event_sequence == engine.state.event_sequence


def test_native_guard_producers_do_not_import_a_historical_test_harness():
    """An old-typing Git selector makes this real producer unpublishable."""
    path = Path(__file__).with_name('test_mgr_t14_guard_producers.py')
    imports = [node.module for node in ast.walk(ast.parse(path.read_text()))
               if isinstance(node, ast.ImportFrom)]
    assert 'tests.guard_spirit_support' in imports
    assert 'tests.' + 'test_riders_c8' not in imports
    document = spirit_sheet([DRAIN], dc=40)
    assert document['identity']['path'] == 'Spirit Awakening'
    assert document['path_and_subpath']['path_feature_record_ids'] == [DRAIN]
    assert document['ability_scores_and_statistics']['technique_save_dc'] == 40
