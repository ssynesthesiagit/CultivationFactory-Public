"""Actual production sheet modules with a minimal DOM and no private API graph."""
import json
from pathlib import Path
import subprocess
from tests.test_formula_archivist_table import install, call, discover, PID
from tests.test_formula_archivist_choices import with_paths, ready
from tests.test_formula_archivist_paid_reroll import legendary_table
from tests.test_formula_archivist_own_ink import ink_table, INK_FACT


def test_production_grow_tab_renders_and_submits_complete_procedure_forms(tmp_path):
    table = install(tmp_path)
    with_paths(table, 'tianxia.path.qi_cultivation', 'tianxia.path.spirit_awakening')
    menus = [table.procedures(PID)[0]]
    previews = {'grant': call(table, 'choose', {'formula_id': menus[0]['grants'][0]['options'][-1]['id']},
                               'grant-preview', preview=True)}
    discover(table)
    study_menu = table.procedures(PID)[0]
    previews['study'] = call(table, 'study', {'discovery_id': 'study-1', 'minutes': 120}, 'study-preview', gm=True, preview=True)
    call(table, 'study', {'discovery_id': 'study-1', 'minutes': 240}, 'elapsed', gm=True)
    menus.append(table.procedures(PID)[0])
    previews['check'] = call(table, 'check', {'discovery_id': 'study-1', 'd20': 20,
                                           'roll_provenance': 'GM die'}, 'check-preview', gm=True, preview=True)
    call(table, 'check', {'discovery_id': 'study-1', 'd20': 1, 'roll_provenance': 'GM die'}, 'first', gm=True)
    menus.append(table.procedures(PID)[0])
    previews['reroll'] = call(table, 'resolve_failure', {'discovery_id': 'study-1', 'decision': 'reroll',
                                  'd20': 1, 'roll_provenance': 'GM new die'}, 'reroll-preview', gm=True, preview=True)
    paid_table, _ = legendary_table(tmp_path / 'paid', 'available')
    paid_menu = paid_table.procedures(PID)[0]
    previews['paid'] = call(paid_table, 'resolve_failure', {'discovery_id': 'study-1', 'decision': 'paid_reroll',
                               'd20': 20, 'roll_provenance': 'GM new die', 'paid_cp': 5,
                               'payment_provenance': 'GM confirms separate 5 CP payment'}, 'paid-preview', gm=True, preview=True)
    ink_owner = ink_table(tmp_path / 'ink', qi=True, legendary=True)
    call(ink_owner, 'discover', {'formula_id': 'tianxia.talent.talismans.healing_talisman',
         'discovery_id': 'study-1', 'provenance': 'GM discovery'}, 'discovery', gm=True)
    call(ink_owner, 'study', {'discovery_id': 'study-1', 'minutes': 480}, 'study', gm=True)
    ink_check_menu = ink_owner.procedures(PID)[0]
    call(ink_owner, 'check', {'discovery_id': 'study-1', 'd20': 1, 'roll_provenance': 'GM die',
                            'own_ink_provenance': INK_FACT}, 'check', gm=True)
    ink_menu = ink_owner.procedures(PID)[0]
    previews['ink'] = call(ink_owner, 'resolve_failure', {'discovery_id': 'study-1', 'decision': 'ink_reroll',
         'd20': 20, 'roll_provenance': 'GM new die'}, 'ink-preview', gm=True, preview=True)
    result = subprocess.run(['node', str(Path(__file__).with_name('formula_archivist_ui.mjs'))],
                            input=json.dumps({'menus': menus, 'previews': previews, 'study_menu': study_menu,
                                              'paid_menu': paid_menu, 'ink_check_menu': ink_check_menu,
                                              'ink_menu': ink_menu, 'ink_fact': INK_FACT}),
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
