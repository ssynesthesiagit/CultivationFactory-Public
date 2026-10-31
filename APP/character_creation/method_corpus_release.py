"""Compatibility aliases for the authenticated Method release.

All editable release identities live in method_foundation_release.json.
"""
from pathlib import Path
from . import release_descriptor as releases

APP_ROOT = releases.APP_ROOT
_RELEASE = releases.select_release(key="methods")
_DATA = _RELEASE.data
RELEASE_ID = _DATA["release_id"]
SOURCE_PATH = _RELEASE.source_path("source_path")
SOURCE_SHA256 = _DATA["source_sha256"]
REGISTRY_PATH = _RELEASE.source_path("registry_path")
REGISTRY_SHA256 = _DATA["registry_sha256"]
BASE_CORPUS_SHA256 = _RELEASE.descriptor.release(_DATA["parent"]).data["corpus_sha256"]
MANIFEST_MEMBER = _RELEASE.descriptor.data["manifest_member"]
SOURCE_MEMBER = _DATA["source_member"]
CORPUS_SHA256 = _DATA["corpus_sha256"]
MANIFEST_SHA256 = _DATA["manifest_sha256"]
ACTIVE_SOURCE_INDEX_SHA256 = _DATA["active_source_index_sha256"]
METHOD_PROJECTION_SHA256 = _DATA["projection"]["method_records_sha256"]
FOUNDATION_PROJECTION_SHA256 = _DATA["projection"]["foundation_records_sha256"]
BACKED_METHOD_IDS_SHA256 = _DATA["projection"]["compiler_backed_method_ids_sha256"]
_regular_path = releases.regular_path
_read_pinned = releases.read_pinned

def verified_source():
    sources = releases.verified_sources(_RELEASE, source_path=SOURCE_PATH, registry_path=REGISTRY_PATH)
    return sources["members"][SOURCE_MEMBER]


def provenance():
    return _RELEASE.provenance()


def binding():
    return _RELEASE.binding()


def derive_corpus_bytes(base):
    return releases.derive_corpus_bytes(_RELEASE, base, source_path=SOURCE_PATH, registry_path=REGISTRY_PATH)


def release_path(vendor_dir):
    return _RELEASE.path(vendor_dir)


def ensure_release(vendor_dir, base_corpus):
    return releases.ensure_release(_RELEASE, vendor_dir, Path(base_corpus),
                                   source_path=SOURCE_PATH, registry_path=REGISTRY_PATH)[0]
