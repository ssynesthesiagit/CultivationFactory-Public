"""Exact controlling source audit, independent of rewritten presentation exports.

Public CI preserves the bundled compendium (its file hash is checked here) but
rewrites rules_text.json prose. Reconstruct the decoded controlling record from
the original source and a synthetic fixture of the approved owner edit, not
that rewritten presentation/configuration fixture. Runtime key-modifier delivery
is independently checked by the public native Starbolt behavior tests.
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
    # Public CI also rewrites the configuration's prose. This small synthetic
    # input pins the approved 2026-09-30 owner ruling (Path key modifier on the
    # free ranged attack), rather than substituting a scrambled replacement.
    approved_edit = {'replace': [{
        'old': 'choose Radiant, Force, or Cold damage and deal:',
        'new': 'choose Radiant, Force, or Cold damage and deal the damage below + your Path key ability modifier:'}]}
    _, text, problems = apply_edit(text, approved_edit)
    assert not problems
    assert hashlib.sha256(text.encode()).hexdigest() == 'cf365810eddf0e0effda8e01bddddae4e7d8628b6ac660e899ba3a3705f7973d'
