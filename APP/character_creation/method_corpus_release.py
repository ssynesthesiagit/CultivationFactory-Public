"""Exact, additive MET1R4 Method source release for the unchanged compiler.

The readable export is owner-controlled derived source. Its embedded records
must equal the accepted typed registry; it is not the lost legacy manuscript.
The original Factory dependency tree and corpus are never modified.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import tempfile
import zipfile

from app.core import FoundryError, sha256_json

APP_ROOT = Path(__file__).resolve().parents[1]
RELEASE_ID = "methods-complete-met1r4-r1"
SOURCE_MEMBER = "Canonical/Methods/Tianxia_Methods_Complete_Readable_MET1R4.md"
SOURCE_PATH = APP_ROOT / "non_sphere_authority/sources/Tianxia_Methods_Complete_Readable_MET1R4.md"
SOURCE_SHA256 = "6bb2cf6a162fcf83480e9d60a21ec7d1c691c8a6bbc745a4a8943ba9aaee4dd9"
REGISTRY_PATH = APP_ROOT / "non_sphere_authority/authority/Tianxia_Methods_Typed_Registry_v0_6.json"
REGISTRY_SHA256 = "42dcf28fceff3f18120940f4f427be36bdcfaab0d40415e098899a313c2df503"
BASE_CORPUS_SHA256 = "12ffcacf2dbf955c24c56eb711634c7c1ebe4f639e1c51681f5aaef1b1388c19"
MANIFEST_MEMBER = "_CANON_AUTHORITY_MANIFEST.json"
# Generated from the exact parent and source by derive_corpus_bytes; fixed release pins.
CORPUS_SHA256 = "bda74cc7b715849270a44f5d0d49c354912e9724f690de0519bdf44712a57331"
MANIFEST_SHA256 = "be1a660703efe12a261365488168e7bf843ad190736170c7bfc3e63c33f5769d"
ACTIVE_SOURCE_INDEX_SHA256 = "602f7b1e244684a92414711851cd4568784b8898098da38ad91b949941fef25c"
METHOD_PROJECTION_SHA256 = "b78229b1b9282239d1ff5306339ea1cf3413097d11ac5a0124e2f131e3d660d6"
FOUNDATION_PROJECTION_SHA256 = "183976f49eaedb7520efbdcbf760706a8db0d635c67ccda1c6f48e173b8a2490"
BACKED_METHOD_IDS_SHA256 = "f1fe7b3b5469fbd2c744729291989825eda007082d34f1344a612abbf3c9d7cb"


def _invalid(message: str) -> FoundryError:
    return FoundryError("METHOD_CORPUS_RELEASE_INVALID", message, status_code=503)


def _regular_path(path: Path) -> None:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise _invalid("Method release paths must not contain symbolic links.")


def _read_pinned(path: Path, digest: str) -> bytes:
    _regular_path(path)
    if not path.is_file():
        raise _invalid("A fixed Method release source is missing.")
    value = path.read_bytes()
    if sha256(value).hexdigest() != digest:
        raise _invalid("A fixed Method release source has changed.")
    return value


def verified_source() -> bytes:
    raw = _read_pinned(SOURCE_PATH, SOURCE_SHA256)
    registry = json.loads(_read_pinned(REGISTRY_PATH, REGISTRY_SHA256))
    text = raw.decode("utf-8")
    blocks = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", text, re.S)]
    records = [row for row in blocks if isinstance(row, dict) and "method_id" in row and "explicit_ap_grants" in row]
    expected = registry["methods"]
    if len(records) != 102 or records != expected:
        raise _invalid("The complete Method export does not exactly reproduce all 102 accepted records.")
    headings = re.findall(r"^## (METHOD-\d{3}) — (.+)$", text, re.M)
    if headings != [(row["method_id"], row["name"]) for row in expected]:
        raise _invalid("The complete Method source headings do not match the exact accepted IDs and names.")
    return raw


def provenance() -> dict[str, str]:
    return {
        "release_id": RELEASE_ID,
        "parent_corpus_sha256": BASE_CORPUS_SHA256,
        "source_member": SOURCE_MEMBER,
        "source_sha256": SOURCE_SHA256,
        "typed_registry_sha256": REGISTRY_SHA256,
        "source_kind": "owner_authorized_complete_readable_derived_export",
    }


def binding() -> dict[str, str]:
    return {**provenance(), "corpus_sha256": CORPUS_SHA256,
            "manifest_sha256": MANIFEST_SHA256,
            "active_source_index_sha256": ACTIVE_SOURCE_INDEX_SHA256}


def derive_corpus_bytes(base: bytes) -> bytes:
    """Pure deterministic assembly; callers cannot substitute source records."""
    if sha256(base).hexdigest() != BASE_CORPUS_SHA256:
        raise _invalid("The Method release requires the exact pinned parent corpus.")
    source = verified_source()
    with zipfile.ZipFile(BytesIO(base)) as original:
        names = original.namelist()
        if len(names) != len(set(names)) or SOURCE_MEMBER in names:
            raise _invalid("The parent corpus has duplicate or conflicting release members.")
        members = {name: original.read(name) for name in names}
    manifest = json.loads(members[MANIFEST_MEMBER])
    manifest["active_packet_sources"] = [*manifest["active_packet_sources"], SOURCE_MEMBER]
    manifest["subject_authority"] = [
        {"subject": "complete_cultivation_methods", "precedence": [SOURCE_MEMBER],
         "status": "complete accepted typed Method authority; legacy source retained for historical packets"},
        *manifest["subject_authority"],
    ]
    manifest["method_corpus_release"] = provenance()
    members[MANIFEST_MEMBER] = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    members[SOURCE_MEMBER] = source
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
    """Publish only exact release bytes under the caller's server-owned vendor root."""
    target = release_path(vendor_dir)
    _regular_path(target)
    # Always reauthenticate inputs, including on a cache hit.
    base = _read_pinned(Path(base_corpus), BASE_CORPUS_SHA256)
    verified_source()
    if target.exists():
        _read_pinned(target, CORPUS_SHA256)
        return target
    payload = derive_corpus_bytes(base)
    if sha256(payload).hexdigest() != CORPUS_SHA256:
        raise _invalid("Derived Method corpus bytes do not match the fixed release pin.")
    target.parent.mkdir(parents=True, exist_ok=True)
    _regular_path(target)
    fd, temporary_name = tempfile.mkstemp(prefix=".method-release-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        _regular_path(target)
        try:
            os.link(temporary, target)
        except FileExistsError:
            pass
        _read_pinned(target, CORPUS_SHA256)
    finally:
        temporary.unlink(missing_ok=True)
    return target
