"""Review gates: current-format continuation and current-tree native producers."""
import ast
from pathlib import Path

from combat.ext.soul_warden import DRAIN
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.guard_spirit_support import spirit_sheet
from tests.h1_support import ROOT
from tests.test_mgr_t14_guard_parent import setup, hit
from tests.worker2_support import ALLY, reload, settle


def test_fresh_guard_fight_commits_and_continues_in_a_cold_service(tmp_path):
    combat, table, mid = setup(tmp_path)
    engine, _ = hit(tmp_path, combat, table, mid)
    assert any(event.event_type == 'SAVE_ROLLED' and event.actor_id == ALLY
               and event.source_definition_id == 'system:combat.concentration'
               and event.payload['mode'] == 'ADVANTAGE' for event in engine.events)
    saved_sequence = reload(tmp_path, mid).state.event_sequence
    assert saved_sequence == engine.state.event_sequence
    # Fresh services built from the reloaded journal only: submit one legal action and cold-replay it.
    cold_table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    settle(cold_table, mid, cold_table.state(mid)['menu']['end_turn'])
    continued = reload(tmp_path, mid)
    assert continued.state.event_sequence > saved_sequence


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
