"""Exact controlling source audit, independent of rewritten presentation exports.

Public CI preserves the bundled compendium (its file hash is checked here) but
rewrites rules_text.json prose. Reconstruct the decoded controlling record from
the original source and the owner's real edits, not that presentation fixture.
"""
import hashlib
import json
import re
import zipfile

from factory_authoring.owner_text_edits import apply_edit
from tests.h1_support import ROOT


def test_controlling_text_hash_is_decoded_text_not_old_source_metadata():
    record_id = 'STARS_BASE_STARBOLT'
    source = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())[
        'mechanics'][record_id]['source']
    with zipfile.ZipFile(ROOT / 'BundledContent/Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip') as archive:
        member = next(name for name in archive.namelist() if name.endswith('/' + source['path']))
        raw = archive.read(member)
    assert hashlib.sha256(raw).hexdigest() == source['file_sha256']
    sections = re.findall(r'(?ms)^#### Starbolt\n(.*?)(?=^#### |\Z)', raw.decode('utf-8-sig'))
    assert len(sections) == 1
    bookkeeping = re.compile(r'^\s*(?:\*\*)?(?:Factory [A-Za-z ]+|Canonical Action Type|Classification)\s*:', re.I)
    text = '\n'.join(['#### Starbolt', *(line for line in sections[0].splitlines()
        if line.strip() and not bookkeeping.match(line))]).strip()
    edits = json.loads((ROOT / 'authority/typed_mechanics/owner_text_edits.json').read_text())['records'][record_id]
    _, text, problems = apply_edit(text, edits)
    assert not problems
    assert hashlib.sha256(text.encode()).hexdigest() == 'cf365810eddf0e0effda8e01bddddae4e7d8628b6ac660e899ba3a3705f7973d'
