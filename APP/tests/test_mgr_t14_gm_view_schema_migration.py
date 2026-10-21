"""Preserve vendor/schema authority while completing the composite removal."""
import hashlib
import json
import zipfile

import pytest
from jsonschema import Draft202012Validator

from app.core import FoundryError
from factory_authoring.gm_view_schema import load, PINNED_SHA, EFFECTIVE_SHA, MIGRATION
from tests.h1_support import ROOT


def source(tmp_path):
    with zipfile.ZipFile(ROOT / 'BundledContent/Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip') as archive:
        name = next(n for n in archive.namelist()
            if n.endswith('/04_SCHEMAS/gm_character_view_model.schema.json'))
        raw = archive.read(name)
    path = tmp_path / 'gm_character_view_model.schema.json'
    path.write_bytes(raw)
    return path, raw


def test_pinned_migration_removes_only_the_two_obsolete_composite_entries(tmp_path):
    path, raw = source(tmp_path)
    assert hashlib.sha256(raw).hexdigest() == PINNED_SHA
    schema, provenance = load(path)
    restored = json.loads(json.dumps(schema))
    original = json.loads(raw)
    restored['properties']['composites'] = original['properties']['composites']
    restored['required'].insert(original['required'].index('composites'), 'composites')
    assert restored == original
    assert path.read_bytes() == raw
    assert provenance == {'pinned_view_model_schema_sha256': PINNED_SHA,
        'view_model_schema_sha256': EFFECTIVE_SHA, 'view_model_schema_migration': MIGRATION}


def test_migrated_schema_retains_every_remaining_required_field_and_type(tmp_path):
    path, _ = source(tmp_path)
    schema, _ = load(path)
    validator = Draft202012Validator(schema)
    for field in schema['required']:
        assert any(error.validator == 'required' and field in error.message
            for error in validator.iter_errors({}))
    assert not any(error.validator == 'required' and 'composites' in error.message
        for error in validator.iter_errors({}))
    assert any(error.validator == 'type' for error in validator.iter_errors({'actions': 'not an array'}))


def test_unknown_vendor_schema_is_rejected_instead_of_silently_relaxed(tmp_path):
    path, raw = source(tmp_path)
    path.write_bytes(raw + b'\n')
    with pytest.raises(FoundryError) as caught:
        load(path)
    assert caught.value.code == 'GM_VIEW_MODEL_SCHEMA_MIGRATION_SOURCE_MISMATCH'
