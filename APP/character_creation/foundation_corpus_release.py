"""Add the thirty published playable Foundations to the immutable Method corpus.

Each added member is an exact, independently hashed section of the accepted
v0.4C catalogue. The thirty-two theoretical Chakra entries remain excluded.
Historical corpora and selection snapshots retain their original identities.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import functools
import json
import os
from pathlib import Path
import re
import tempfile
import zipfile

from app.core import FoundryError
from . import method_corpus_release as parent

RELEASE_ID = "foundations-complete-v04c-r1"
SOURCE_PATH = parent.APP_ROOT / "non_sphere_authority/authority/Tianxia_Foundations_Unified_Transparent_GM_Screen_Catalog_v0_4C.md"
SOURCE_SHA256 = "cf1efee756b36fc444e46eaefb7a015441703d8cc2efa4a96d43fcc22f03318d"
REGISTRY_PATH = parent.APP_ROOT / "non_sphere_authority/authority/Foundation_Runtime_Authority_v0_4C.json"
REGISTRY_SHA256 = "c6e5edaf064cca200a6a7ce0a2a26d17d87b95fc53f1d4d36818a55b0458cf89"
BASE_CORPUS_SHA256 = parent.CORPUS_SHA256
MANIFEST_MEMBER = parent.MANIFEST_MEMBER
MEMBER_PREFIX = "Canonical/Foundations/Playable_v0_4C/"
CORPUS_SHA256 = "1de4d9b6a5009c1f6eae1c48b936bf64d353a533126289815362db2413acf3c4"
MANIFEST_SHA256 = "0f8b5aef04b8462637ea27b45a307d3dc1e32692dbc6f24eb287a194f8ddb710"
ACTIVE_SOURCE_INDEX_SHA256 = "fd3be9d55fea36672f6285a36b7a900adc173bc37ad610fe9b85a5f1ef89f136"
METHOD_PROJECTION_SHA256 = "6470037595b87f1707c4996dc3facb9b5d88e772f6755c1ca6f5c5cab102261d"
FOUNDATION_PROJECTION_SHA256 = "b24e56961b7e2ad1b28504fa59aa3dc6348f789b6777e8c3da1a2d8d0b4554c6"
BACKED_FOUNDATION_IDS_SHA256 = "167187d57e2f59f0588048ec1051f3109131d377b77e28b87ee1050c8a787cd5"


def _invalid(message: str) -> FoundryError:
    return FoundryError("FOUNDATION_CORPUS_RELEASE_INVALID", message, status_code=503)


def verified_sections() -> dict[str, bytes]:
    """Return the verified Foundation sections, recomputed only when a pinned file changes.

    Both inputs are pinned by digest; ``_read_pinned`` still verifies the
    bytes whenever they are read.  The parsed sections are memoized on the
    files' size and mtime so a compile that resolves dozens of Foundation
    records does not re-read, re-hash and re-split the corpus each time.
    """

    try:
        source_stat = SOURCE_PATH.stat()
        registry_stat = REGISTRY_PATH.stat()
    except OSError:
        return dict(_verified_sections_uncached())
    return dict(_verified_sections_memo(
        source_stat.st_size, source_stat.st_mtime_ns, registry_stat.st_size, registry_stat.st_mtime_ns,
    ))


@functools.lru_cache(maxsize=2)
def _verified_sections_memo(source_size: int, source_mtime_ns: int, registry_size: int, registry_mtime_ns: int) -> dict[str, bytes]:
    return _verified_sections_uncached()


def _verified_sections_uncached() -> dict[str, bytes]:
    raw = parent._read_pinned(SOURCE_PATH, SOURCE_SHA256)
    registry = json.loads(parent._read_pinned(REGISTRY_PATH, REGISTRY_SHA256))
    text = raw.decode("utf-8")
    headings = list(re.finditer(r"^# (\d+)\. (.+)$", text, re.M))
    rows = registry.get("orthodox")
    if (registry.get("schema") != "Tianxia.FoundationCatalogRuntime.v0.4C"
            or not isinstance(rows, list) or len(rows) != 30 or len(headings) != 62):
        raise _invalid("The complete playable Foundation source inventory changed.")
    result = {}
    for number, row in enumerate(rows, 1):
        heading, following = headings[number - 1:number + 1]
        section = (text[heading.start():following.start()].rstrip() + "\n").encode()
        source = row.get("source") or {}
        if (row.get("catalog_number") != number or row.get("authority_class") != "ORTHODOX"
                or row.get("selectable") is not True or row.get("tournament_legal") is not True
                or not isinstance(row.get("stage"), str) or not row["stage"]
                or heading.group(1) != str(number) or heading.group(2) != row.get("display_name")
                or source.get("section_number") != number
                or source.get("artifact_sha256") != SOURCE_SHA256
                or source.get("section_sha256") != sha256(section).hexdigest()):
            raise _invalid("A playable Foundation does not match its complete published section.")
        identity = row.get("foundation_id")
        if not isinstance(identity, str) or not re.fullmatch(r"[a-zA-Z0-9_]+", identity):
            raise _invalid("A Foundation source has an invalid stable identity.")
        member = MEMBER_PREFIX + identity + ".md"
        if member in result:
            raise _invalid("The playable Foundation source repeats an identity.")
        result[member] = section
    return result


def provenance() -> dict[str, str]:
    return {"release_id": RELEASE_ID, "parent_corpus_sha256": BASE_CORPUS_SHA256,
            "source_sha256": SOURCE_SHA256, "typed_registry_sha256": REGISTRY_SHA256,
            "source_kind": "exact_published_playable_foundation_sections",
            "excluded_authority": "theoretical_chakra"}


def binding() -> dict[str, str]:
    return {**provenance(), "corpus_sha256": CORPUS_SHA256,
            "manifest_sha256": MANIFEST_SHA256,
            "active_source_index_sha256": ACTIVE_SOURCE_INDEX_SHA256}


def derive_corpus_bytes(base: bytes) -> bytes:
    if sha256(base).hexdigest() != BASE_CORPUS_SHA256:
        raise _invalid("The Foundation release requires the exact Method corpus parent.")
    sections = verified_sections()
    with zipfile.ZipFile(BytesIO(base)) as original:
        names = original.namelist()
        if len(names) != len(set(names)) or set(names) & set(sections):
            raise _invalid("The parent corpus contains duplicate or conflicting members.")
        members = {name: original.read(name) for name in names}
    manifest = json.loads(members[MANIFEST_MEMBER])
    if manifest.get("method_corpus_release") != parent.provenance():
        raise _invalid("The Foundation parent lacks its exact Method source provenance.")
    manifest["active_packet_sources"] = [*manifest["active_packet_sources"], *sorted(sections)]
    manifest["subject_authority"] = [
        {"subject": "complete_playable_foundations", "precedence": sorted(sections),
         "status": "complete published mechanics at recorded stage; theoretical Chakra excluded"},
        *manifest["subject_authority"],
    ]
    manifest["foundation_corpus_release"] = provenance()
    members[MANIFEST_MEMBER] = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    members.update(sections)
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as released:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (0o40755 if name.endswith("/") else 0o100644) << 16
            released.writestr(info, members[name])
    return output.getvalue()


def release_path(vendor_dir: Path) -> Path:
    return Path(vendor_dir).absolute() / "releases" / RELEASE_ID / f"{CORPUS_SHA256}.zip"


def ensure_release(vendor_dir: Path, base_corpus: Path) -> Path:
    target = release_path(vendor_dir)
    parent._regular_path(target)
    method_corpus = parent.ensure_release(vendor_dir, base_corpus)
    base = parent._read_pinned(method_corpus, BASE_CORPUS_SHA256)
    verified_sections()
    if target.exists():
        parent._read_pinned(target, CORPUS_SHA256)
        return target
    payload = derive_corpus_bytes(base)
    if sha256(payload).hexdigest() != CORPUS_SHA256:
        raise _invalid("Derived Foundation corpus bytes do not match the fixed release pin.")
    target.parent.mkdir(parents=True, exist_ok=True)
    parent._regular_path(target)
    fd, temporary_name = tempfile.mkstemp(prefix=".foundation-release-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        parent._regular_path(target)
        try:
            os.link(temporary, target)
        except FileExistsError:
            pass
        parent._read_pinned(target, CORPUS_SHA256)
    finally:
        temporary.unlink(missing_ok=True)
    return target
