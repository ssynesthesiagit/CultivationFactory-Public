from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import tempfile
from zipfile import ZipFile

import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPOSITORY_ROOT / "APP"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.core import Database, Settings  # noqa: E402
from character_builder.insight_authority import classify_insight_authority, resolve_insight_occurrences  # noqa: E402
from non_sphere_authority import NonSphereAuthorityService  # noqa: E402


BUNDLE = APP_ROOT / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"
INSIGHT_SUFFIX = "09_RULES/Source_Text/Insights/Tianxia_Central_Cultivation_Insights_AI_Reference_R4.json"


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def method_matrix() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="tianxia-win1-p1r2-") as temporary:
        settings = Settings.from_env(APP_ROOT, Path(temporary))
        database = Database(settings)
        database.migrate()
        records = NonSphereAuthorityService(database).method_catalog(initial_creation=True)["records"]
    rows = [record["method_planning"] for record in records]
    if len(rows) != 102 or {row["method_id"] for row in rows} != {f"METHOD-{index:03d}" for index in range(1, 103)}:
        raise RuntimeError("WIN1_P1R2_METHOD_MATRIX_NOT_COMPLETE")
    registry = APP_ROOT / "non_sphere_authority" / "authority" / "Tianxia_Methods_Typed_Registry_v0_6.json"
    return {
        "schema": "TianxiaFoundry.WIN1P1R2R1MethodPlanningMatrix.v2",
        "scope": "Every record in the single pinned Method authority registry; planning projection only.",
        "source": {
            "registry": "APP/non_sphere_authority/authority/Tianxia_Methods_Typed_Registry_v0_6.json",
            "registry_sha256": hashlib.sha256(registry.read_bytes()).hexdigest(),
        },
        "summary": {
            "method_count": len(rows),
            "preference_allowed_count": sum(bool(row["preference_allowed"]) for row in rows),
            "exact_selection_available_count": sum(bool(row["exact_selection_available"]) for row in rows),
            "owner_route_choice_count": sum(len(row["owner_route_options"]) for row in rows),
            "auto_allowed_count": sum(bool(row["auto_allowed"]) for row in rows),
        },
        "records": rows,
    }


def insight_matrix() -> dict[str, object]:
    with ZipFile(BUNDLE) as archive:
        name = next(name for name in archive.namelist() if name.endswith(INSIGHT_SUFFIX))
        source_bytes = archive.read(name)
    source = json.loads(source_bytes)
    grouped: dict[str, list[dict[str, object]]] = {}
    for index, raw in enumerate(source.get("records", [])):
        record_id = raw.get("canonical_id") or raw.get("record_id")
        if not isinstance(record_id, str) or not record_id:
            raise RuntimeError(f"WIN1_P1R2_INSIGHT_ID_INVALID:{index}:{record_id}")
        grouped.setdefault(record_id, []).append({
            "raw_record": raw,
            "source_reference": {
                "source_file": INSIGHT_SUFFIX,
                "source_file_sha256": hashlib.sha256(source_bytes).hexdigest(),
                "source_anchor": f"records[{index}]",
                "source_status": str(raw.get("execution_status") or ""),
            },
        })
    rows = []
    for record_id, occurrences in grouped.items():
        resolution = resolve_insight_occurrences(occurrences, record_id=record_id)
        authority = classify_insight_authority(
            resolution["raw_record"], record_id=record_id, source_reference=resolution["source_reference"]
        )
        authority["source_occurrences"] = resolution["source_occurrences"]
        authority["source_occurrence_count"] = resolution["source_occurrence_count"]
        authority["collision_disposition"] = resolution["collision_disposition"]
        if not resolution["resolved"]:
            authority.update({
                "authority_type": "Unresolved",
                "classification_code": "UNRESOLVED_DUPLICATE_INSIGHT_ID",
                "reason": "Multiple current source records use this Insight identifier; it remains unavailable until the source resolves the collision.",
            })
        raw = resolution["raw_record"]
        rows.append({
            "record_id": record_id,
            "display_name": raw.get("display_name") or raw.get("name") or record_id,
            "selectable": bool(raw.get("selectable")) and resolution["resolved"],
            "source_occurrence_count": resolution["source_occurrence_count"],
            "collision_disposition": resolution["collision_disposition"],
            "insight_authority": authority,
        })
    counts = Counter(row["insight_authority"]["authority_type"] for row in rows)
    return {
        "schema": "TianxiaFoundry.WIN1P1R2R1InsightSourceAuthorityMatrix.v2",
        "scope": "Every unique record in the pinned Central Cultivation Insights R4 JSON, including nonselectable source records.",
        "source": {
            "bundle": str(BUNDLE.relative_to(REPOSITORY_ROOT)).replace("\\", "/"),
            "bundle_sha256": hashlib.sha256(BUNDLE.read_bytes()).hexdigest(),
            "source_file": INSIGHT_SUFFIX,
            "source_file_sha256": hashlib.sha256(source_bytes).hexdigest(),
        },
        "summary": {
            "source_record_count": len(source.get("records", [])),
            "matrix_record_count": len(rows),
            "unique_record_id_count": len(grouped),
            "duplicate_source_record_count": sum(len(values) - 1 for values in grouped.values()),
            "duplicate_canonical_record_id_count": len(rows) - len({row["record_id"] for row in rows}),
            "resolved_duplicate_record_id_count": sum(len(values) > 1 and resolve_insight_occurrences(values, record_id=record_id)["resolved"] for record_id, values in grouped.items()),
            "unresolved_duplicate_record_id_count": sum(len(values) > 1 and not resolve_insight_occurrences(values, record_id=record_id)["resolved"] for record_id, values in grouped.items()),
            "selectable_count": sum(row["selectable"] for row in rows),
            "authority_type_counts": dict(sorted(counts.items())),
            "unresolved_code": "UNRESOLVED_INSIGHT_CLASSIFICATION",
        },
        "records": rows,
    }


def main() -> None:
    output = Path(__file__).resolve().parent
    method = method_matrix()
    insight = insight_matrix()
    write_json(output / "METHOD_PLANNING_MATRIX.json", method)
    write_json(output / "INSIGHT_SOURCE_AUTHORITY_MATRIX.json", insight)
    summary = {
        "schema": "TianxiaFoundry.WIN1P1R2R1AuthorityMatrixGeneration.v2",
        "method_matrix_sha256": hashlib.sha256(canonical_json(method).encode("utf-8")).hexdigest(),
        "insight_matrix_sha256": hashlib.sha256(canonical_json(insight).encode("utf-8")).hexdigest(),
        "method_count": method["summary"]["method_count"],
        "insight_count": insight["summary"]["matrix_record_count"],
    }
    write_json(output / "AUTHORITY_MATRIX_SUMMARY.json", summary)
    print(canonical_json(summary))


if __name__ == "__main__":
    main()
