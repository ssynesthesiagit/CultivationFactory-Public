"""Source-configured, owner-recorded combat feature admissions.

Independent of the Foundry's sealed display-only earned-occurrence index.
Owners explicitly record access facts; AI never infers entitlement. The native
compiler validates actor, level, source text and admission contract. The store
persists compact receipts with existing writer-lock/atomic storage primitives.
"""
import copy
import hashlib
import json
from pathlib import Path
import re

FIELD = "combat_acquisitions"
SCHEMA = "NativeFeatureAdmissions.v1"


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _sources():
    root = Path(__file__).resolve().parent.parent
    return (json.loads((root / "authority/typed_mechanics/rules_text.json").read_text()),
            json.loads((root / "combat/rules/feature_admission.json").read_text()))


def _contract(feature_id):
    if not isinstance(feature_id, str) or not feature_id:
        raise ValueError("Feature admission needs a source record identity")
    rules, contracts = _sources()
    text, contract = rules.get(feature_id), contracts.get(feature_id)
    if not text or contract is None:
        raise ValueError("Feature has no source-backed native admission contract")
    match = re.search(r"^#{1,6}\s+CL(\d+)\b", text, re.M)
    if match is None:
        raise ValueError("Feature has no explicit acquisition level")
    return int(match[1]), hashlib.sha256(text.encode()).hexdigest(), contract


def _access(contract, record):
    if not contract.get("access_kind"):
        return
    if not isinstance(record, dict) or set(record) != {"kind", "basis", "record_id"}:
        raise ValueError("Restricted feature needs an explicit owner/table access record")
    if record["kind"] != contract["access_kind"] or record["basis"] not in contract["access_bases"]:
        raise ValueError("Access record does not meet the printed feature requirement")
    if not isinstance(record["record_id"], str) or not record["record_id"].strip():
        raise ValueError("Access record must identify the owner/table's source")


def _level(sheet):
    identity = sheet.get("identity") or {}
    return int(identity.get("cultivation_level") or identity.get("cl") or 1)


def acquired_feature_ids(sheet, *, actor_id):
    """Fail closed on stale, duplicate, cross-owner or incomplete receipts."""
    if not isinstance(actor_id, str) or not actor_id.strip():
        raise ValueError("Native feature admission needs a creature identity")
    rows = sheet.get(FIELD, [])
    if not isinstance(rows, list):
        raise ValueError("Native feature admissions must be a list")
    occurrences, features = set(), []
    for row in rows:
        required = {"actor_id", "feature_id", "occurrence_id", "acquired_cl", "source_sha256", "admission_sha256"}
        if not isinstance(row, dict) or not required <= row.keys() or set(row) - required - {"access_record"}:
            raise ValueError("Incomplete native feature admission")
        if any(not isinstance(row[k], str) or not row[k] for k in ("actor_id", "feature_id", "occurrence_id", "source_sha256", "admission_sha256")):
            raise ValueError("Native feature admission identities and hashes must be text")
        if row["actor_id"] != actor_id:
            raise ValueError("Native feature admission belongs to another creature")
        if not isinstance(row["occurrence_id"], str) or not row["occurrence_id"].strip():
            raise ValueError("Native feature admission needs an occurrence identity")
        minimum, source_hash, contract = _contract(row["feature_id"])
        if type(row["acquired_cl"]) is not int or not minimum <= row["acquired_cl"] <= _level(sheet):
            raise ValueError(f"Feature requires Cultivation Level {minimum}")
        if row["source_sha256"] != source_hash or row["admission_sha256"] != _hash(contract):
            raise ValueError("Feature source or admission contract changed; record a new owner admission")
        _access(contract, row.get("access_record"))
        if row["occurrence_id"] in occurrences or row["feature_id"] in features:
            raise ValueError("Feature occurrence already acquired")
        occurrences.add(row["occurrence_id"])
        features.append(row["feature_id"])
    return features


def acquire_feature(sheet, feature_id, *, actor_id, occurrence_id, access_record=None):
    """Return a new owner sheet carrying one validated, actor-bound admission."""
    minimum, source_hash, contract = _contract(feature_id)
    if _level(sheet) < minimum:
        raise ValueError(f"Feature requires Cultivation Level {minimum}")
    _access(contract, access_record)
    out = copy.deepcopy(sheet)
    out.setdefault(FIELD, []).append({"actor_id": actor_id, "feature_id": feature_id,
        "occurrence_id": occurrence_id, "acquired_cl": _level(sheet), "source_sha256": source_hash,
        "admission_sha256": _hash(contract),
        **({"access_record": copy.deepcopy(access_record)} if access_record is not None else {})})
    acquired_feature_ids(out, actor_id=actor_id)
    return out


class SourceAcquisitionStore:
    """Durable owner/table admission API scoped to the supplied user-data root."""

    def __init__(self, userdata_root):
        self.root = Path(userdata_root) / "Combat" / "Acquisitions"

    def _path(self, actor_id):
        if not isinstance(actor_id, str) or not actor_id.strip():
            raise ValueError("Native feature admission needs a creature identity")
        return self.root / (hashlib.sha256(actor_id.encode()).hexdigest() + ".json")

    def load_into(self, sheet, *, actor_id):
        out = copy.deepcopy(sheet)
        path = self._path(actor_id)
        if path.exists():
            doc = json.loads(path.read_text())
            if doc.get("schema") != SCHEMA or doc.get("actor_id") != actor_id:
                raise ValueError("Wrong native feature admission owner or format")
            if not isinstance(doc.get("records"), list):
                raise ValueError("Native feature admission records must be a list")
            records = copy.deepcopy(doc["records"])
            for row in out.get(FIELD) or []:
                if row not in records:
                    records.append(row)
            out[FIELD] = records
        acquired_feature_ids(out, actor_id=actor_id)
        return out

    def acquire(self, sheet, feature_id, *, actor_id, occurrence_id, access_record=None):
        from .gate3_storage import LocalMatchWriterLock, atomic_write_bytes
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self._path(actor_id)
        with LocalMatchWriterLock(path.with_suffix(".lock"), "acquisition:" + actor_id):
            current = self.load_into(sheet, actor_id=actor_id)
            out = acquire_feature(current, feature_id, actor_id=actor_id,
                                  occurrence_id=occurrence_id, access_record=access_record)
            payload = {"schema": SCHEMA, "actor_id": actor_id, "records": out[FIELD]}
            atomic_write_bytes(path, json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
        return out
