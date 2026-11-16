"""Synthetic catalog edits and installed-sheet checks for saved Foundation tests."""
from copy import deepcopy
import json
import zipfile

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from non_sphere_authority import foundation_mechanics as fm
from tests.h1_support import ROOT
from tests.table_act_support import end_turn


def edit_catalog(monkeypatch):
    records = deepcopy(fm.verified_foundation_records())
    for record in records.values():
        record.setdefault('semantic_surfaces', {})['gm_and_counterplay'] = 'Revised catalog commentary.'
        record.setdefault('source', {})['artifact_sha256'] = 'e' * 64
    monkeypatch.setattr(fm, 'verified_foundation_records', lambda: records)
    return records


def assert_saved_hp_services(tmp_path, doc, expected):
    """Compile an imported creation sheet, open it, start/commit/cold-reload a match."""
    project = 'saved-foundation'
    actor = 'actor:factory.' + project
    saved = deepcopy(doc['foundation']['mechanics'])
    bundle = compile_character(doc, actor_id=actor)
    assert bundle['actor_template']['maximum_hp'] == expected
    assert compile_character(deepcopy(doc), actor_id=actor) == bundle
    folder = tmp_path / 'portable_characters' / project
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
        archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    assert table.sheet(project)['summary']['hit_points']['maximum'] == expected
    mid = combat.create_factory_match(
        project_ids=[project], opponent_actor_ids=[AN],
        control_modes={actor: 'MANUAL', AN: 'MANUAL'},
        match_seed='SAVED-FOUNDATION-CATALOG-EDIT')['match_id']
    assert combat._load_session(mid).engine.state.actors[actor].maximum_hp == expected
    end_turn(table, mid)
    cold = CombatService(ROOT, tmp_path)
    session = cold._load_session(mid)
    assert session.engine.state.actors[actor].maximum_hp == expected
    assert session.mechanical.replay()['status'] == 'PASS'
    assert TabletopService(cold, tmp_path).sheet(project)['summary']['hit_points']['maximum'] == expected
    assert cold._factory_installed_sheet(project)['foundation']['mechanics'] == saved
