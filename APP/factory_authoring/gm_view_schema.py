"""Pinned migration of the vendor GM view after composite surfaces were removed.

Owner-authorized repository change de87f7f77b44ac4eeb48b74d3520172130d9f2ec
removed composite playbooks from authoring, compilation and character surfaces.
The immutable vendor schema predates that migration. Adapt precisely its two
obsolete composites entries, preserving all other constraints and reporting
both original and effective hashes. Unknown vendor bytes fail closed.
"""
import hashlib
import json

from app.core import FoundryError, canonical_json

PINNED_SHA = '90b398142113f8e2756b2aba7f583a16e2978a57d47d88fcf508f659ff413450'
EFFECTIVE_SHA = 'e176d75eeffed781d66135d9460c2157255a44de13b0e6f7d0d3703bcc1c0a24'
MIGRATION = 'de87f7f7-remove-composite-view'


def load(path):
    raw = path.read_bytes()
    original = hashlib.sha256(raw).hexdigest()
    if original != PINNED_SHA:
        raise FoundryError('GM_VIEW_MODEL_SCHEMA_MIGRATION_SOURCE_MISMATCH',
            'The GM view schema migration requires its exact pinned vendor source.',
            details={'expected': PINNED_SHA, 'actual': original})
    schema = json.loads(raw)
    schema['required'].remove('composites')
    del schema['properties']['composites']
    effective = hashlib.sha256(canonical_json(schema).encode()).hexdigest()
    if effective != EFFECTIVE_SHA:
        raise FoundryError('GM_VIEW_MODEL_SCHEMA_MIGRATION_RESULT_MISMATCH',
            'The GM view schema migration changed more than its declared composite entries.',
            details={'expected': EFFECTIVE_SHA, 'actual': effective})
    return schema, {'pinned_view_model_schema_sha256': original,
        'view_model_schema_sha256': effective, 'view_model_schema_migration': MIGRATION}
