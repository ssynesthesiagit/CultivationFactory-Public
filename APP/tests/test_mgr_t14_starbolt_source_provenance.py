"""Private provenance gate; behavior tests stay in test_mgr_t14_starbolt_base.

Public CI intentionally rewrites printed book prose, so it cannot prove an
exact unredacted source digest. This source audit requires the original bundled
compendium; do not weaken its hash to the public snapshot's replacement prose.
"""
import hashlib
import json
import zipfile

from tests.h1_support import ROOT


def test_controlling_text_hash_is_decoded_text_not_old_source_metadata():
    source = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())[
        'mechanics']['STARS_BASE_STARBOLT']['source']
    with zipfile.ZipFile(ROOT / 'BundledContent/Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip') as archive:
        member = next(name for name in archive.namelist() if name.endswith('/' + source['path']))
        assert hashlib.sha256(archive.read(member)).hexdigest() == source['file_sha256']
    text = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())['STARS_BASE_STARBOLT']
    assert hashlib.sha256(text.encode()).hexdigest() == 'cf365810eddf0e0effda8e01bddddae4e7d8628b6ac660e899ba3a3705f7973d'
