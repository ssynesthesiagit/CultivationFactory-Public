from __future__ import annotations

from collections import Counter
from typing import Any

from .constants import CANDIDATE_STATUS, CAPABILITY_NAMES, TOOL_SCHEMA_VERSION
from .models import Diagnostic, Severity, ValidationArtifacts, ValidationContext


def build_artifacts(context: ValidationContext, include_info: bool = True) -> ValidationArtifacts:
    diagnostics = context.ordered_diagnostics(include_info=include_info)
    verdict_text = "BLOCKED" if any(row.severity is Severity.ERROR for row in diagnostics) else "PASS"
    counts = Counter(row.severity.value for row in diagnostics)
    input_preserved = (
        context.input_identity_after is not None
        and context.input_identity_after == context.input_identity_before
    )
    validation_report = {
        **context.report_header(),
        "verdict": verdict_text,
        "input_preservation": {
            "before_identity": context.input_identity_before,
            "after_identity": context.input_identity_after,
            "byte_identical": input_preserved,
        },
        "checksum_exact": context.checksum_exact,
        "diagnostic_counts": {
            "errors": counts.get("ERROR", 0),
            "warnings": counts.get("WARNING", 0),
            "info": counts.get("INFO", 0),
        },
        "diagnostics": [row.to_dict() for row in diagnostics],
        "scope_declaration": {
            "runtime_integrated": False,
            "production_loader_created": False,
            "input_mutated": not input_preserved,
            "candidate_non_authoritative": True,
        },
    }
    capability_matrix = build_capability_matrix(context)
    dependency_graph = build_dependency_graph(context)
    unsupported_primitives = {
        **context.report_header(),
        "registry_supplied": context.primitive_registry_identity is not None,
        "registry_sha256": context.primitive_registry_identity,
        "registry_schema_version": context.primitive_registry_schema_version,
        "registry_primitive_count": len(context.primitive_ids),
        "unsupported_reference_count": len(context.unsupported_primitive_references),
        "references": context.unsupported_primitive_references,
    }
    source_binding_report = build_source_binding_report(context)
    from .checksums import checksum_inventory

    checksum_report = checksum_inventory(context)
    verdict = {
        "schema_version": "TianxiaContentPackValidatorVerdict.v1",
        "candidate_status": CANDIDATE_STATUS,
        "verdict": verdict_text,
        "blocking_diagnostic_codes": sorted(
            {row.code for row in diagnostics if row.severity is Severity.ERROR}
        ),
        "input_identity": context.input_identity_before,
        "input_preserved": input_preserved,
        "checksum_exact": context.checksum_exact,
        "runtime_integration_claim": "NONE",
    }
    human = build_human_report(context, diagnostics, verdict_text, input_preserved)
    return ValidationArtifacts(
        validation_report=validation_report,
        human_report=human,
        capability_matrix=capability_matrix,
        dependency_graph=dependency_graph,
        unsupported_primitives=unsupported_primitives,
        source_binding_report=source_binding_report,
        checksum_inventory=checksum_report,
        verdict=verdict,
    )


def build_capability_matrix(context: ValidationContext) -> dict[str, Any]:
    rows = []
    for record in sorted(
        context.records,
        key=lambda row: (str(row.get("record_id", "")), str(row.get("record_version", ""))),
    ):
        capabilities = record.get("capabilities") if isinstance(record.get("capabilities"), dict) else {}
        rows.append(
            {
                "record_id": record.get("record_id"),
                "record_version": record.get("record_version"),
                "record_type": record.get("record_type"),
                "display_name": record.get("display_name"),
                "capabilities": {name: capabilities.get(name) for name in CAPABILITY_NAMES},
                "selectable": record.get("selectable"),
                "execution_definition_ids": sorted(record.get("execution_definition_ids", []))
                if isinstance(record.get("execution_definition_ids"), list)
                else [],
                "controller_policy_id": record.get("controller_policy_id"),
            }
        )
    return {
        **context.report_header(),
        "semantic_guards": {
            "display_prose_proves_execution": False,
            "empty_execution_arrays_prove_execution": False,
            "acquisition_authority_proves_execution": False,
        },
        "record_count": len(rows),
        "records": rows,
    }


def build_dependency_graph(context: ValidationContext) -> dict[str, Any]:
    nodes: set[tuple[str, str]] = set()
    edges: set[tuple[str, str, str, str | None]] = set()
    manifest = context.manifest or {}
    pack_id = manifest.get("pack_id")
    if isinstance(pack_id, str):
        nodes.add(("pack", pack_id))
        for dependency in manifest.get("dependencies", []) if isinstance(manifest.get("dependencies"), list) else []:
            if not isinstance(dependency, dict) or not isinstance(dependency.get("pack_id"), str):
                continue
            dep_id = dependency["pack_id"]
            nodes.add(("pack", dep_id))
            edges.add((f"pack:{pack_id}", f"pack:{dep_id}", "pack_dependency", dependency.get("version_range")))
    for record in context.records:
        record_id = record.get("record_id")
        if not isinstance(record_id, str):
            continue
        nodes.add(("record", record_id))
        for dependency in record.get("record_dependencies", []) if isinstance(record.get("record_dependencies"), list) else []:
            if isinstance(dependency, dict) and isinstance(dependency.get("record_id"), str):
                target = dependency["record_id"]
                nodes.add(("record", target))
                edges.add((f"record:{record_id}", f"record:{target}", "record_capability_dependency", dependency.get("capability")))
        for blocker in record.get("capability_blockers", []) if isinstance(record.get("capability_blockers"), list) else []:
            if not isinstance(blocker, dict):
                continue
            if isinstance(blocker.get("record_id"), str):
                target = blocker["record_id"]
                nodes.add(("record", target))
                edges.add((f"record:{record_id}", f"record:{target}", "capability_blocker", blocker.get("capability")))
            elif isinstance(blocker.get("pack_id"), str):
                target = blocker["pack_id"]
                nodes.add(("pack", target))
                edges.add((f"record:{record_id}", f"pack:{target}", "capability_blocker", blocker.get("capability")))
            elif isinstance(blocker.get("primitive_id"), str):
                target = blocker["primitive_id"]
                nodes.add(("primitive", target))
                edges.add((f"record:{record_id}", f"primitive:{target}", "capability_blocker", blocker.get("capability")))
    return {
        **context.report_header(),
        "format": "deterministic-node-edge-list",
        "nodes": [
            {"node_id": f"{kind}:{identity}", "kind": kind, "identity": identity}
            for kind, identity in sorted(nodes)
        ],
        "edges": [
            {"from": source, "to": target, "kind": kind, "constraint": constraint}
            for source, target, kind, constraint in sorted(edges)
        ],
    }


def build_source_binding_report(context: ValidationContext) -> dict[str, Any]:
    inventory = {entry.logical_path: entry for entry in context.inventory}
    rows: list[dict[str, Any]] = []

    def add_row(owner_kind: str, owner_id: Any, source: Any, path: str) -> None:
        if not isinstance(source, dict):
            rows.append(
                {
                    "owner_kind": owner_kind,
                    "owner_id": owner_id,
                    "document_path": path,
                    "binding_present": False,
                    "pack_local_status": "NOT_APPLICABLE",
                }
            )
            return
        source_path = source.get("source_path")
        pack_local_status = "EXTERNAL_SOURCE"
        if source_path is not None:
            entry = inventory.get(source_path)
            if entry is None:
                pack_local_status = "MISSING"
            elif entry.sha256 == source.get("source_sha256"):
                pack_local_status = "MATCH"
            else:
                pack_local_status = "MISMATCH"
        rows.append(
            {
                "owner_kind": owner_kind,
                "owner_id": owner_id,
                "document_path": path,
                "binding_present": True,
                "source_id": source.get("source_id"),
                "source_version": source.get("source_version"),
                "source_sha256": source.get("source_sha256"),
                "anchor": source.get("anchor"),
                "source_path": source_path,
                "pack_local_status": pack_local_status,
            }
        )

    manifest = context.manifest or {}
    add_row("pack", manifest.get("pack_id"), manifest.get("source_identity"), "pack.json")
    for record in context.records:
        add_row("record", record.get("record_id"), record.get("source_binding"), "records/definitions.json")
    for definition in context.combat_definitions:
        add_row("execution_definition", definition.get("definition_id"), definition.get("source_binding"), "execution/combat_definitions.json")
    for policy in context.controller_policies:
        add_row("controller_policy", policy.get("policy_id"), policy.get("source_binding"), "policies/controller_policies.json")
    for creature in context.creatures:
        add_row("creature_or_companion", creature.get("creature_id"), creature.get("source_binding"), "creatures/creature_definitions.json")
    rows.sort(key=lambda row: (str(row.get("owner_kind")), str(row.get("owner_id")), str(row.get("document_path"))))
    return {
        **context.report_header(),
        "binding_count": len(rows),
        "bindings": rows,
    }


def build_human_report(
    context: ValidationContext,
    diagnostics: list[Diagnostic],
    verdict: str,
    input_preserved: bool,
) -> str:
    lines = [
        "Tianxia CPK-1 Content Pack Validation",
        "======================================",
        f"Verdict: {verdict}",
        f"Input kind: {context.input_kind}",
        f"Input identity: {context.input_identity_before}",
        f"Input preserved: {'YES' if input_preserved else 'NO'}",
        f"Exact checksum coverage: {'YES' if context.checksum_exact else 'NO'}",
        f"Candidate status: {CANDIDATE_STATUS}",
        "Runtime integration: NONE",
        "",
        "Diagnostics",
        "-----------",
    ]
    if not diagnostics:
        lines.append("No diagnostics.")
    else:
        for row in diagnostics:
            location = ""
            if row.path:
                location += f" [{row.path}]"
            if row.record_id:
                location += f" [record={row.record_id}]"
            if row.field_path:
                location += f" [field={row.field_path}]"
            lines.append(f"{row.severity.value} {row.code}{location}: {row.message}")
    lines.extend(
        [
            "",
            "Interpretation",
            "--------------",
            "PASS means the isolated candidate validator found no blocking contradiction under the supplied primitive registry and environment inputs.",
            "PASS does not install, activate, promote, or authorize the pack for Factory runtime use.",
        ]
    )
    return "\n".join(lines) + "\n"
