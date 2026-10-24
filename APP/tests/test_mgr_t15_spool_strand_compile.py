"""MGR-T15 Spool and Strand: the factory compile path must supply the compile_bundle context the material ledger reads.

Regression: compile_bundle info lacked owned_ids/mods, so every character compile raised KeyError (service level).
"""
import json
import zipfile
from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

SOURCE = 'THREAD_BASE_SPOOL_AND_STRAND'
PID, QID = '0badc0de-1400-4000-8000-000000000011', '0badc0de-1400-4000-8000-000000000012'


def install(service, pid, base):
    base['identity'].update(proficiency_bonus=3, path_ids=['tianxia.path.qi_cultivation'])
    base['path_and_subpath'] = {'path_record_ids': ['tianxia.path.qi_cultivation']}
    path = service.combatant_library.install_root / pid / 'current.zip'
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(base))


def test_thread_character_compiles_and_seals_owned_ids_and_mods(tmp_path):
    service = CombatService(ROOT, tmp_path)
    install(service, PID, sheet([], cl=5, name='Thread compile'))
    table = TabletopService(service, tmp_path)
    table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    table.add_advancement(PID, 'sphere', 'tianxia.sphere.thread')
    bundle = service.compile_factory_actor(PID)
    sealed = bundle['material_abilities']
    assert SOURCE in sealed['owned']
    assert isinstance(sealed['ability_mods'], dict)


def test_non_thread_character_compiles_without_material_context(tmp_path):
    service = CombatService(ROOT, tmp_path)
    install(service, QID, sheet([], cl=5, name='Plain compile'))
    bundle = service.compile_factory_actor(QID)
    assert 'material_abilities' not in bundle
