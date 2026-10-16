"""Actual production sheet modules with a minimal DOM and no private API graph."""
import json
from pathlib import Path
import subprocess
from tests.test_formula_archivist_table import install, call, PID
from tests.test_formula_archivist_choices import with_paths, ready


def test_production_grow_tab_renders_and_submits_complete_procedure_forms(tmp_path):
    table = install(tmp_path)
    with_paths(table, 'tianxia.path.qi_cultivation', 'tianxia.path.spirit_awakening')
    menus = [table.procedures(PID)[0]]
    ready(table)
    menus.append(table.procedures(PID)[0])
    call(table, 'check', {'discovery_id': 'study-1', 'd20': 1, 'roll_provenance': 'GM die'}, 'first', gm=True)
    menus.append(table.procedures(PID)[0])
    result = subprocess.run(['node', str(Path(__file__).with_name('formula_archivist_ui.mjs'))],
                            input=json.dumps(menus), text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
