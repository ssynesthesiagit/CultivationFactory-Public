"""Authenticated Method/Foundation releases, shared by creation and materialization.

The generated descriptor is data, not its own trust root: its commitment lives
in release_trust.py, deployed with the server code. Fixtures supply a separate
TrustRoot under tmp_path. Requests never choose a trust root or descriptor.
All paths, bindings, members and projections have one owner here; compatibility
modules expose derived aliases only. No mtime-only authentication cache is used.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from types import MappingProxyType
from typing import Mapping
import zipfile

from app.core import FoundryError, sha256_json
from . import release_projection as projection
from .release_trust import DESCRIPTOR_SHA256

APP_ROOT = Path(__file__).resolve().parents[1]


def freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(freeze(v) for v in value)
    return value


def thaw(value):
    if isinstance(value, Mapping):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [thaw(v) for v in value]
    return value


def invalid(message, *, kind="methods"):
    return FoundryError("FOUNDATION_CORPUS_RELEASE_INVALID" if kind == "foundations"
                       else "METHOD_CORPUS_RELEASE_INVALID", message, status_code=503)


def regular_path(path):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise invalid("Method release paths must not contain symbolic links.")
    if ".." in path.parts:
        raise invalid("Method release paths must not contain traversal.")


def read_pinned(path, digest):
    path = Path(path)
    regular_path(path)
    if not path.is_file():
        raise invalid("A fixed Method release source is missing.")
    value = path.read_bytes()
    if sha256(value).hexdigest() != digest:
        raise invalid("A fixed Method release source has changed.")
    return value


def relative_path(root, value):
    path = PurePosixPath(value)
    if not value or "\\" in value or path.is_absolute() or ".." in path.parts:
        raise invalid("A release locator must be a safe relative POSIX path.")
    result = Path(root) / value
    regular_path(result)
    return result


@dataclass(frozen=True)
class TrustRoot:
    """Server-owned application root and out-of-band descriptor commitment."""
    app_root: Path
    descriptor_path: Path
    descriptor_sha256: str


@dataclass(frozen=True)
class Descriptor:
    trust: TrustRoot
    data: Mapping

    def release(self, key):
        return Release(self, key, self.data["releases"][key])


def load_descriptor(trust):
    data = json.loads(read_pinned(trust.descriptor_path, trust.descriptor_sha256))
    if data.get("format") != 1 or set(data.get("releases", {})) != {"base", "methods", "foundations"}:
        raise invalid("The Method/Foundation release descriptor has an unknown format.")
    for key, row in data["releases"].items():
        if key != "base":
            for field in ("source_path", "registry_path"):
                relative_path(trust.app_root, row[field])
            for value in [row.get("source_member", row.get("member_prefix"))]:
                relative_path(trust.app_root, value)
        for member in row.get("members", {}):
            for nested in member.split("::"):
                relative_path(trust.app_root, nested)
    for field in ("compiler_relative_path", "corpus_relative_path"):
        relative_path(trust.app_root, data["compiler"][field])
    return Descriptor(trust, freeze(data))


PRODUCTION_TRUST = TrustRoot(APP_ROOT, APP_ROOT / "character_creation/method_foundation_release.json", DESCRIPTOR_SHA256)
DESCRIPTOR = load_descriptor(PRODUCTION_TRUST)


@dataclass(frozen=True)
class Release:
    descriptor: Descriptor
    key: str
    data: Mapping

    def provenance(self):
        if self.key == "base":
            return {}
        row = self.data
        result = {
            "release_id": row["release_id"],
            "parent_corpus_sha256": self.descriptor.release(row["parent"]).data["corpus_sha256"],
            "source_sha256": row["source_sha256"],
            "typed_registry_sha256": row["registry_sha256"],
        }
        if self.key == "methods":
            result.update(source_member=row["source_member"],
                          source_kind="owner_authorized_complete_readable_derived_export")
        else:
            result.update(source_kind="exact_published_playable_foundation_sections",
                          excluded_authority="theoretical_chakra")
        return result

    def bindings(self):
        if self.key == "base":
            return {}
        return {"method_corpus_release": self.descriptor.release("methods").binding(),
                **({"foundation_corpus_release": self.binding()} if self.key == "foundations" else {})}

    def binding(self):
        return {**self.provenance(), **{k: self.data[k] for k in (
            "corpus_sha256", "manifest_sha256", "active_source_index_sha256")}}

    def path(self, vendor_dir, base_corpus=None):
        if self.key == "base":
            if base_corpus is None:
                raise invalid("The base release requires its server-owned corpus location.")
            return Path(base_corpus).absolute()
        return Path(vendor_dir).absolute() / "releases" / self.data["release_id"] / (self.data["corpus_sha256"] + ".zip")

    def source_path(self, field):
        return relative_path(self.descriptor.trust.app_root, self.data[field])


def select_release(*, key=None, schema=None, corpus_sha256=None, corpus_path=None,
                   vendor_dir=None, base_corpus=None, descriptor=None, consumer=None):
    """One closed-world selector for snapshot, receipt and production path identities.

    Multiple supplied identities must agree. This does not authenticate corpus
    bytes: verify_release does that before exposing any record or projection.
    """
    descriptor = descriptor or DESCRIPTOR
    accepted = descriptor.data["consumers"][consumer] if consumer else None
    if accepted and all(v is None for v in (key, schema, corpus_sha256, corpus_path)):
        key = accepted["default"]
    matches = []
    for candidate in descriptor.data["releases"]:
        if accepted and candidate not in accepted["accepted"]:
            continue
        release = descriptor.release(candidate)
        row = release.data
        if key is not None and key != candidate:
            continue
        if schema is not None and schema != row["schema"]:
            continue
        if corpus_sha256 is not None and corpus_sha256 != row["corpus_sha256"]:
            continue
        if corpus_path is not None and Path(corpus_path).absolute() != release.path(vendor_dir, base_corpus):
            continue
        matches.append(release)
    if len(matches) != 1:
        raise invalid("The rules corpus is not an exact accepted release identity.")
    return matches[0]


def verified_sources(release, *, source_path=None, registry_path=None):
    """Authenticate source and registry, then prove their exact record/section binding."""
    row = release.data
    raw = read_pinned(source_path or release.source_path("source_path"), row["source_sha256"])
    registry = read_pinned(registry_path or release.source_path("registry_path"), row["registry_sha256"])
    return _parse_sources(release.key, row.get("source_member"), row.get("member_prefix"),
                          row["source_sha256"], raw, registry)


@lru_cache(maxsize=4)
def _parse_sources(key, source_member, member_prefix, source_sha256, raw, registry_bytes):
    """Content-keyed parsing only: callers authenticate bytes on EVERY read."""
    row = {"source_member": source_member, "member_prefix": member_prefix, "source_sha256": source_sha256}
    registry = json.loads(registry_bytes)
    text = raw.decode("utf-8")
    if key == "methods":
        blocks = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", text, re.S)]
        records = [r for r in blocks if isinstance(r, dict) and "method_id" in r and "explicit_ap_grants" in r]
        expected = registry["methods"]
        if len(records) != 102 or records != expected:
            raise invalid("The complete Method export does not exactly reproduce all 102 accepted records.")
        if re.findall(r"^## (METHOD-\d{3}) — (.+)$", text, re.M) != [(r["method_id"], r["name"]) for r in expected]:
            raise invalid("The complete Method source headings do not match the exact accepted IDs and names.")
        return freeze({"members": {row["source_member"]: raw}, "records": {r["method_id"]: r for r in expected}})
    headings = list(re.finditer(r"^# (\d+)\. (.+)$", text, re.M))
    rows = registry.get("orthodox")
    if (registry.get("schema") != "Tianxia.FoundationCatalogRuntime.v0.4C"
            or not isinstance(rows, list) or len(rows) != 30 or len(headings) != 62):
        raise invalid("The complete playable Foundation source inventory changed.", kind="foundations")
    sections = {}
    for number, record in enumerate(rows, 1):
        heading, following = headings[number - 1:number + 1]
        section = (text[heading.start():following.start()].rstrip() + "\n").encode()
        source = record.get("source") or {}
        if (record.get("catalog_number") != number or record.get("authority_class") != "ORTHODOX"
                or record.get("selectable") is not True or record.get("tournament_legal") is not True
                or not isinstance(record.get("stage"), str) or not record["stage"]
                or heading.group(1) != str(number) or heading.group(2) != record.get("display_name")
                or source.get("section_number") != number
                or source.get("artifact_sha256") != row["source_sha256"]
                or source.get("section_sha256") != sha256(section).hexdigest()):
            raise invalid("A playable Foundation does not match its complete published section.", kind="foundations")
        identity = record.get("foundation_id")
        if not isinstance(identity, str) or not re.fullmatch(r"[a-zA-Z0-9_]+", identity):
            raise invalid("A Foundation source has an invalid stable identity.", kind="foundations")
        member = row["member_prefix"] + identity + ".md"
        if member in sections:
            raise invalid("The playable Foundation source repeats an identity.", kind="foundations")
        sections[member] = section
    return freeze({"members": sections, "records": {r["foundation_id"]: r for r in rows}})


def zip_members(payload):
    with zipfile.ZipFile(BytesIO(payload)) as corpus:
        names = corpus.namelist()
        if len(names) != len(set(names)):
            raise invalid("The parent corpus has duplicate or conflicting release members.")
        for info in corpus.infolist():
            relative_path(Path("."), info.filename)
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise invalid("A corpus member is a symbolic link.")
        return {name: corpus.read(name) for name in names}


def write_corpus(members):
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as released:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (0o40755 if name.endswith("/") else 0o100644) << 16
            released.writestr(info, members[name])
    return output.getvalue()


def derive_corpus_bytes(release, base, **source_paths):
    parent = release.descriptor.release(release.data["parent"])
    if sha256(base).hexdigest() != parent.data["corpus_sha256"]:
        raise invalid("The Method release requires the exact pinned parent corpus." if release.key == "methods"
                      else "The Foundation release requires the exact Method corpus parent.", kind=release.key)
    sources = verified_sources(release, **source_paths)["members"]
    members = zip_members(base)
    if set(members) & set(sources):
        raise invalid("The parent corpus has duplicate or conflicting release members.", kind=release.key)
    manifest_member = release.descriptor.data["manifest_member"]
    manifest = json.loads(members[manifest_member])
    if release.key == "foundations" and manifest.get("method_corpus_release") != parent.provenance():
        raise invalid("The Foundation parent lacks its exact Method source provenance.", kind=release.key)
    added = sorted(sources)
    manifest["active_packet_sources"] = [*manifest["active_packet_sources"], *added]
    subject = ({"subject": "complete_cultivation_methods", "precedence": added,
                "status": "complete accepted typed Method authority; legacy source retained for historical packets"}
               if release.key == "methods" else
               {"subject": "complete_playable_foundations", "precedence": added,
                "status": "complete published mechanics at recorded stage; theoretical Chakra excluded"})
    manifest["subject_authority"] = [subject, *manifest["subject_authority"]]
    manifest[release.key.rstrip("s") + "_corpus_release"] = release.provenance()
    members[manifest_member] = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    members.update(sources)
    return write_corpus(members)


def project(release, payload, method_records, foundation_records):
    """Historical projection over authenticated corpus bytes; no second name model."""
    compiler = {**thaw(release.descriptor.data["compiler"]), "corpus_sha256": release.data["corpus_sha256"]}
    methods = release.descriptor.release("methods").data
    foundations = release.descriptor.release("foundations").data
    with zipfile.ZipFile(BytesIO(payload)) as corpus:
        manifest_raw = projection._safe_member(corpus, release.descriptor.data["manifest_member"],
                                                source_path=release.descriptor.data["manifest_member"])
        manifest = json.loads(manifest_raw)
        active_rows = manifest.get("active_packet_sources")
        if not isinstance(active_rows, list) or not all(isinstance(r, str) for r in active_rows):
            raise projection._error("CG1_COMPILER_AUTHORITY_MANIFEST_INVALID", "The active corpus authority manifest is malformed.")
        active = set(active_rows)
        index = [{"source_path": p, "source_file_sha256": sha256(projection._read_source(corpus, p)[0]).hexdigest()} for p in sorted(active)]
        slots = {}
        for slot, records, id_key, name_key in (
            ("method_choice", method_records, "method_id", "name"),
            ("foundation_choice", foundation_records, "foundation_id", "display_name"),
        ):
            evidence = {}
            for identity, name in projection._records_by_id(records, id_key=id_key, name_key=name_key):
                source = (projection._method_excerpt(corpus, name, active,
                          method_member=release.descriptor.data["legacy_method_member"],
                          source_member=methods["source_member"], source_sha256=methods["source_sha256"])
                          if slot == "method_choice" else
                          projection._foundation_excerpt(corpus, name, active, member_prefix=foundations["member_prefix"]))
                evidence[identity] = projection._evidence(choice_id=identity, canonical_name=name, source=source, corpus=compiler)
            slots[slot] = {"records": evidence, "compiler_backed_ids": sorted(k for k, v in evidence.items() if v["selectable"])}
    return {"source_authority": {"manifest_sha256": sha256(manifest_raw).hexdigest(),
            "active_source_index": index, "active_source_index_sha256": sha256_json(index)}, **slots,
            "projection": {"method_records_sha256": sha256_json(slots["method_choice"]["records"]),
            "foundation_records_sha256": sha256_json(slots["foundation_choice"]["records"]),
            "compiler_backed_method_ids_sha256": sha256_json(slots["method_choice"]["compiler_backed_ids"]),
            "compiler_backed_foundation_ids_sha256": sha256_json(slots["foundation_choice"]["compiler_backed_ids"])}}


@dataclass(frozen=True)
class VerifiedRelease:
    release: Release
    corpus_bytes: bytes
    members: Mapping
    sources: Mapping
    projected: Mapping

    def record(self, slot, identity):
        return self.projected[slot]["records"][identity]

    def project_catalog(self, method_records, foundation_records):
        method_records, foundation_records = list(method_records), list(foundation_records)
        for slot, records, id_key, name_key in (
            ("method_choice", method_records, "method_id", "name"),
            ("foundation_choice", foundation_records, "foundation_id", "display_name"),
        ):
            requested = projection._records_by_id(records, id_key=id_key, name_key=name_key)
            expected = sorted((identity, row["canonical_name"]) for identity, row in self.projected[slot]["records"].items())
            if requested != expected:
                # Preserve the established rejection diagnostics for altered catalogs.
                return project(self.release, self.corpus_bytes, method_records, foundation_records)
        return thaw(self.projected)


def record_commitments(records):
    # Artifact identity is provenance, not the semantic identity of every section.
    return {identity: sha256_json({k: thaw(v) for k, v in row.items() if k != "source"})
            for identity, row in records.items()}


def verify_release(release, payload, **source_paths):
    """The authenticated boundary: return only immutable verified bytes/records."""
    row = release.data
    if sha256(payload).hexdigest() != row["corpus_sha256"]:
        raise invalid("A fixed Method release source has changed.")
    members = zip_members(payload)
    sources = {}
    for key in ("methods", "foundations"):
        spec = release.descriptor.release(key)
        sources[key] = verified_sources(spec, **(source_paths if key == release.key else {}))
        if "records" in spec.data and record_commitments(sources[key]["records"]) != thaw(spec.data["records"]):
            raise invalid("A release record commitment does not match its accepted registry.", kind=key)
        if key == "methods" and release.key == "base" or key == "foundations" and release.key != "foundations":
            continue
        if any(members.get(k) != v for k, v in sources[key]["members"].items()):
            raise invalid("A corpus member differs from its accepted source.", kind=key)
    projected = project(release, payload, list(thaw(sources["methods"]["records"]).values()),
                        list(thaw(sources["foundations"]["records"]).values()))
    source = projected["source_authority"]
    if source["manifest_sha256"] != row["manifest_sha256"] or source["active_source_index_sha256"] != row["active_source_index_sha256"]:
        raise invalid("The corpus manifest or active member commitments changed.", kind=release.key)
    if projected["projection"] != thaw(row["projection"]):
        raise invalid("The complete Method/Foundation projection changed.", kind=release.key)
    if "members" in row and {k: sha256(v).hexdigest() for k, v in members.items()} != thaw(row["members"]):
        raise invalid("The corpus member inventory changed.", kind=release.key)
    return VerifiedRelease(release, payload, freeze(members), freeze(sources), freeze(projected))


def ensure_release(release, vendor_dir, base_corpus, **source_paths):
    """Publish without overwriting evidence; cache hits reauthenticate all inputs."""
    target = release.path(vendor_dir, base_corpus)
    regular_path(target)
    if release.key == "base":
        return target, verify_release(release, read_pinned(target, release.data["corpus_sha256"]))
    parent = release.descriptor.release(release.data["parent"])
    if parent.key == "base":
        base = read_pinned(base_corpus, parent.data["corpus_sha256"])
    else:
        _, verified_parent = ensure_release(parent, vendor_dir, base_corpus)
        base = verified_parent.corpus_bytes
    verified_sources(release, **source_paths)
    payload = read_pinned(target, release.data["corpus_sha256"]) if target.exists() else derive_corpus_bytes(release, base, **source_paths)
    view = verify_release(release, payload, **source_paths)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        regular_path(target)
        fd, temporary_name = tempfile.mkstemp(prefix=".corpus-release-", dir=target.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            regular_path(target)
            try:
                os.link(temporary, target)
            except FileExistsError:
                pass
            read_pinned(target, release.data["corpus_sha256"])
        finally:
            temporary.unlink(missing_ok=True)
    return target, view
