"""Deterministic, read-only audit of the combat authority and its static routes.

Run from APP: python -m tools.automation_truth
This imports compiler readers and the trigger classifier. It never constructs an
engine, actor, fight, model client, or runtime database. Generated reports are the
only writes. UNKNOWN is a result, not a reason to silently discard a mechanic.
"""
from __future__ import annotations

import argparse
import ast
import builtins
import copy
import hashlib
import json
import re
import sys
import symtable
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from combat import reaction_triggers, status_text, trigger_overlay, typed_reactions
from tools.automation_truth_effects import analyze_effects
from tools.automation_truth_plugins import build_plugin_index
from tools.automation_truth_plugin_proofs import verified_components

AUTHORITY = "APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json"
COMPILER = "APP/combat/factory_compiler.py"
EXECUTOR = "APP/combat/typed_executor.py"
REACTIONS = "APP/combat/typed_reactions.py"
TRIGGERS = "APP/combat/reaction_triggers.py"
STATUSES = ("REAL_FULL", "PARTIAL", "MANUAL", "UNKNOWN")
SUMMARY_PATH = ROOT / "docs/plans/AUTOMATION_TRUTH_R1.md"
JSON_PATH = ROOT / "docs/plans/AUTOMATION_TRUTH_R1.json"
AUDIT_PATH = ROOT / "docs/plans/AUTOMATION_TRUTH_AUDIT.md"


def _compiler_readers() -> SimpleNamespace:
    """Execute only the real compiler's pure readers, without its service imports.

    Function bodies and constants are taken verbatim from the current AST. A
    changed dependency or missing definition fails visibly, rather than silently
    substituting a hand-maintained copy of the GM filtering algorithm.
    """
    path = ROOT / COMPILER
    # These are the audit's entry points, not a list of their implementation dependencies.
    required = {"_typed_stat_line", "_printed_choices", "_gm_lines", "_rules_text", "_walk",
                "MAX_OPTIONS_PER_ABILITY", "HANDLED_IN_CODE"}
    namespace = {"__file__": str(path), "__name__": "combat._automation_audit_readers", "__package__": "combat",
                 "Any": Any, "Path": Path, "json": json, "re": re}
    body = ast.parse(path.read_text(encoding="utf-8"), filename=str(path)).body
    definitions = {}
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            definitions[node.name] = node
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name) and isinstance(name.ctx, ast.Store):
                        definitions[name.id] = node

    def global_references(node: ast.AST) -> set[str]:
        # Scope analysis handles nested functions, comprehensions, imports, and
        # shadowed builtins correctly; a flat walk of Name nodes cannot do that.
        table = symtable.symtable("from __future__ import annotations\n" + ast.unparse(node), str(path), "exec")

        def referenced(scope):
            names = {symbol.get_name() for symbol in scope.get_symbols()
                     if symbol.is_referenced() and symbol.is_global()}
            for child in scope.get_children():
                names |= referenced(child)
            return names

        return referenced(table)

    selected = set()
    pending = sorted(required)
    while pending:
        name = pending.pop()
        node = definitions.get(name)
        if node is None:
            if name not in required and (name in namespace or hasattr(builtins, name)):
                continue
            raise ValueError(f"Compiler reader dependency cannot be resolved: {name}")
        if node in selected:
            continue
        selected.add(node)
        pending.extend(sorted(global_references(node)))
    # Retain compiler source order for constant initializers, and execute no
    # unrelated module statements or service imports.
    nodes = [node for node in body if node in selected]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return SimpleNamespace(**namespace)


compiler = _compiler_readers()


def stable_json(value: Any) -> str:
    """No clock, absolute paths, Python hash order, or filesystem mtimes."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"


class Evidence:
    def __init__(self, root: Path):
        self.root = root
        self.lines: dict[str, list[str]] = {}
        self.key_lines: dict[str, dict[str, int]] = {}

    def read(self, path: str) -> list[str]:
        if path not in self.lines:
            self.lines[path] = (self.root / path).read_text(encoding="utf-8").splitlines()
        return self.lines[path]

    def at(self, path: str, needle: str) -> str:
        for i, line in enumerate(self.read(path), 1):
            if needle in line:
                return f"{path}:{i}"
        raise ValueError(f"Audit source anchor no longer exists: {path}: {needle}")

    def key(self, path: str, key: str) -> str:
        if path not in self.key_lines:
            index: dict[str, int] = {}
            string_token = re.compile(r'"(?:[^"\\]|\\.)*"')
            colon = re.compile(r"\s*:")
            for i, line in enumerate(self.read(path), 1):
                for match in string_token.finditer(line):
                    if colon.match(line, match.end()):
                        index.setdefault(json.loads(match.group()), i)
            self.key_lines[path] = index
        line = self.key_lines[path].get(key)
        if line is None:
            raise ValueError(f"Missing evidence key {key} in {path}")
        return f"{path}:{line}"


def _walk_all(value: Any, path: str = "effects"):
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_all(item, f"{path}[{index}]")
    elif isinstance(value, dict):
        if "type" in value:
            yield path, value
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                yield from _walk_all(item, f"{path}.{key}")


def _group(mechanic: dict, names: dict) -> tuple[str, str, str]:
    if mechanic.get("sphere_id"):
        key = str(mechanic["sphere_id"])
        return key, str(names.get(key) or key), "sphere"
    for field, kind in (("subpath_id", "subpath"), ("path_id", "path"), ("foundation_id", "foundation")):
        if mechanic.get(field):
            key = str(mechanic[field])
            label = key.rsplit(".", 1)[-1].replace("_", " ").title()
            if kind == "foundation":
                label = re.sub(r"^Foundation \d+ ", "", label)
            return key, f"{kind.title()}: {label}", kind
    return "unassigned", "Unassigned (authority has no group)", "unassigned"


class AutomationAudit:
    """A fixed input snapshot. Consumers can classify individual real records."""
    def __init__(self):
        global compiler
        compiler = _compiler_readers()
        self.evidence = Evidence(ROOT)
        self.authority = json.loads((ROOT / AUTHORITY).read_text(encoding="utf-8"))
        self.mechanics = self.authority["mechanics"]
        # Do not accept the engine readers' missing-file fallbacks as an audit.
        required = [
            ROOT / AUTHORITY,
            APP / "authority/typed_mechanics/rules_text.json",
            APP / "authority/typed_mechanics/trigger_readings.jsonl",
            trigger_overlay.OVERLAY_PATH, trigger_overlay.DEEPSEEK_PATH,
            typed_reactions.RULES_PATH, reaction_triggers.RULES_PATH,
        ]
        for path in required:
            if not path.is_file() or path.stat().st_size == 0:
                raise ValueError(f"Required audit input missing or empty: {path.relative_to(ROOT)}")
        typed_reactions._CACHE.clear()
        reaction_triggers._CACHE.clear()
        trigger_overlay._CACHE.clear()
        status_text.printed_rules.cache_clear()
        self.features = copy.deepcopy(typed_reactions.rules().get("features") or {})
        self.feature_sources: dict[str, str] = {}
        feature_files = [typed_reactions.RULES_PATH, *sorted((typed_reactions.RULES_PATH.parent / "feature_blocks.d").glob("*.json"))]
        for path in feature_files:
            rel = path.relative_to(ROOT).as_posix()
            for key in (json.loads(path.read_text(encoding="utf-8")).get("features") or {}):
                self.feature_sources[key] = self.evidence.key(rel, key)
        self.plugins = build_plugin_index(ROOT, known_mechanic_ids=sorted(self.mechanics))
        self.anchors = {
            "gm_filter": self.evidence.at(COMPILER, "def _gm_lines("),
            "covers": self.evidence.at(COMPILER, "covers = ["),
            "feature_override": self.evidence.at(REACTIONS, "def rules("),
            "feature_compile": self.evidence.at(REACTIONS, "def compile_blocks("),
            "feature_skip": self.evidence.at(COMPILER, 'if mechanic_id in blocks["automated"]:'),
            "plugin_compile": self.evidence.at(REACTIONS, 'made = [rows for rows in ext.run("compile_block"'),
            "already_applied": self.evidence.at(REACTIONS, 'elif block != "already_applied":'),
            "economy": self.evidence.at(COMPILER, 'if economy not in {"action", "bonus_action"}:'),
            "generic_reaction": self.evidence.at(COMPILER, "def _generic_reaction("),
            "trigger_gate": self.evidence.at(COMPILER, "if not matches:"),
            "reaction_effects": self.evidence.at(COMPILER, "if not base_effects:"),
            "reaction_resource": self.evidence.at(COMPILER, "if requires_resource is None:"),
            "options": self.evidence.at(COMPILER, "picked = [(index, option) for index, option in enumerate(options)"),
            "action_riders": self.evidence.at(COMPILER, '"riders": _gm_lines(mechanic.get("riders")'),
            "option_riders": self.evidence.at(COMPILER, '"riders": _gm_lines(option_riders'),
            "modifier": self.evidence.at(COMPILER, "def apply_modifiers("),
            "dispatch": self.evidence.at(EXECUTOR, 'block = BLOCKS.get(effect.get("type"))'),
        }
        self.input_manifest = self._input_manifest()

    @staticmethod
    def _input_manifest() -> dict[str, str]:
        """The exact audited sources, by repository-relative path and content hash.

        The manifest covers every combat source the audit read, not only the files a
        report quotes, and every report embeds its fingerprint. That is deliberate: a
        report cannot be trusted against code it never looked at, and a repository
        with an extra or missing combat source is a different audit.
        """
        paths = [ROOT / AUTHORITY, *sorted((APP / "combat").rglob("*.py")), *sorted((APP / "combat/rules").rglob("*.json")),
                 *[APP / f"authority/typed_mechanics/{name}" for name in ("rules_text.json", "trigger_readings.jsonl", "trigger_normalization.jsonl", "trigger_normalization_deepseek.jsonl")],
                 APP / "factory_authoring/typed_mechanics.py", *sorted((APP / "tools").glob("automation_truth*.py"))]
        return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(set(paths))}

    def _issue(self, code: str, reason: str, *evidence: str) -> dict:
        return {"code": code, "reason": reason, "evidence": sorted(set(evidence))}

    def _variants(self, mechanic: dict, route: str) -> tuple[list[dict], list[dict]]:
        options = mechanic.get("options") or []
        issues: list[dict] = []
        out = []
        if len(options) >= 2:
            for index, option in enumerate(options):
                included = route == "reaction" or index < compiler.MAX_OPTIONS_PER_ABILITY or option.get("include_in_menu") is True
                if not included:
                    issues.append(self._issue("capped_option", f"Printed option {index + 1} ({option.get('label')}) is outside the compiled action menu.", self.anchors["options"]))
                    continue
                riders = option.get("riders") if option.get("riders") is not None else mechanic.get("riders")
                out.append({"option": index, "label": str(option.get("label") or ""), "effects": option.get("effects") or [],
                            "riders": riders or [], "mechanic": {**mechanic, "effects": option.get("effects") or [],
                            "area": option.get("area") or mechanic.get("area"), "range": option.get("range") or mechanic.get("range")}})
        else:
            effects = list(mechanic.get("effects") or [])
            if route == "reaction":
                effects += [row for option in options for row in option.get("effects") or []]
            elif options:
                issues.append(self._issue("single_option_ignored", "A one-option ordinary action executes the base effects; its option effects are not merged.", self.anchors["action_riders"]))
            out.append({"option": None, "label": "", "effects": effects, "riders": mechanic.get("riders") or [], "mechanic": mechanic})
        return out, issues

    def classify(self, mechanic_id: str, *, mechanic: dict | None = None) -> dict:
        """The optional record supports regression fixtures; reports use authority records."""
        original = self.mechanics.get(mechanic_id)
        mechanic = copy.deepcopy(mechanic if mechanic is not None else original)
        if not isinstance(mechanic, dict):
            raise KeyError(mechanic_id)
        source = self.evidence.key(AUTHORITY, mechanic_id) if original is not None else "test fixture"
        group_id, group_name, group_kind = _group(mechanic, self.authority.get("sphere_names") or {})
        economy = (mechanic.get("activation") or {}).get("economy")
        feature = self.features.get(mechanic_id) or {}
        block = feature.get("block")
        kinds = sorted({str(row.get("type")) for _, row in _walk_all([mechanic.get("effects") or [], *[o.get("effects") or [] for o in mechanic.get("options") or []]])})
        claims = self.plugins.claims_for(mechanic_id, block_names=[str(block)] if block else [], effect_names=kinds)
        components = verified_components(mechanic_id, mechanic, feature, ROOT)
        issues: list[dict] = []
        trigger = None
        route = "action" if economy in {"action", "bonus_action"} else "none"
        route_known = route == "action"
        if mechanic.get("modifier"):
            route, route_known = "modifier", False
            issues.append(self._issue("modifier_context", "This modifier needs an owned destination, attachment timing, and variant selection; its standalone effects do not establish execution.", self.anchors["modifier"]))
        elif economy == "reaction" or ((economy == "no_action" or economy == "passive") and (
            mechanic.get("free") or (economy == "passive" and mechanic.get("cost") and (mechanic.get("activation") or {}).get("trigger") and mechanic.get("effects"))
            or any(row.get("type") in {"gain_resource", "spend_resource", "hold_at_1hp"} for row in compiler._walk(mechanic.get("effects") or [])))):
            route = "reaction"
            printed = (mechanic.get("activation") or {}).get("trigger")
            if not printed and economy != "reaction":
                text = next((str(row.get("evidence") or "") for row in compiler._walk(mechanic.get("effects") or []) if row.get("type") == "gain_resource" and row.get("evidence")), None)
                matches = [reaction_triggers.classify_trigger(text)]
            else:
                matches = reaction_triggers.classify_mechanic_all(mechanic)
            runnable = [m for m in matches if m.runnable]
            trigger = {"printed": printed, "kinds": sorted({m.kind for m in matches}), "runnable": bool(runnable),
                       "needs": sorted({str(m.needs) for m in matches if m.needs}),
                       "required_resources": sorted({m.requires_resource for m in matches if m.requires_resource}),
                       "evidence": [self.anchors["generic_reaction"], self.anchors["trigger_gate"]]}
            if not runnable:
                route_known = False
                issues.append(self._issue("uncompiled_reaction", "No trigger reading passes the engine's runnable gate; a generic reaction is not compiled.", self.anchors["trigger_gate"]))
            else:
                # A phrase match is necessary; recipient/effect/character-specific
                # restrictions still need the generic reaction's actual caller.
                route_known = False
                issues.append(self._issue("reaction_context", "The trigger is runnable, but character resources, recipient context, and hook-specific effect handling are not proved by this static audit.", self.anchors["generic_reaction"], self.anchors["reaction_resource"]))
        elif not route_known:
            issues.append(self._issue("no_direct_action", f"Economy {economy!r} does not produce an ordinary typed action; a feature, modifier, or hook is required.", self.anchors["economy"]))

        if block:
            route_known = False
            issues.append(self._issue("feature_block_context", f"Feature block {block!r} may replace or supplement normal compilation; declarations and covers alone do not prove its complete behavior.", self.feature_sources[mechanic_id], self.anchors["feature_compile"], self.anchors["feature_skip"]))
            if block == "already_applied":
                issues.append(self._issue("already_applied_declaration", "already_applied skips generic compilation without producing a reaction or passive row here; its external implementation requires separate proof.", self.anchors["already_applied"]))
        if mechanic_id in compiler.HANDLED_IN_CODE:
            route_known = False
            issues.append(self._issue("compiler_special_case", "The compiler lists this mechanic as handled in code; the owning build and weapon combination are required to prove its behavior.", self.evidence.at(COMPILER, "HANDLED_IN_CODE =")))

        variants, option_issues = self._variants(mechanic, route)
        issues += option_issues
        rendered_variants = []
        gm_lines: list[str] = []
        removed: list[str] = []
        raw_effect_counts = {"supported": 0, "manual": 0, "unknown": 0}
        supported = manual = unknown = 0
        for variant in variants:
            # Call the real reader, passing the original mechanic just as the
            # compiler does for option-specific riders and choice labels.
            lines = compiler._gm_lines(variant["riders"], mechanic, variant["effects"], variant["label"] if variant["option"] is not None else None)
            lines = [str(line) for line in lines]
            gm_lines += lines
            normalized_covers = {" ".join(str(line).lower().split()) for line in feature.get("covers") or []}
            for rider in variant["riders"]:
                for sentence in re.split(r"(?<=[.;])\s+", " ".join(str(rider).split())):
                    # Same rule as the compiler's _gm_lines: a covers entry is the whole sentence or a tail phrase of it.
                    if any(" ".join(sentence.lower().split()).endswith(cover) for cover in normalized_covers):
                        removed.append(sentence)
            result = analyze_effects(variant["effects"], repo_root=ROOT, route=route, mechanic=variant["mechanic"], plugin_index=self.plugins)
            if not variant["effects"]:
                manual += 1
                issues.append(self._issue("empty_variant", f"Included branch {variant['label'] or 'base'} has no effect rows; other options cannot supply its implementation.", source, self.anchors["options"]))
            supported += result["supported_count"]
            manual += result["manual_count"]
            unknown += result["unknown_count"]
            for key in raw_effect_counts:
                raw_effect_counts[key] += result[key + "_count"]
            issues += result.get("issues") or []
            rendered_variants.append({"option": variant["option"], "label": variant["label"], "gm_lines": lines,
                                      "effects": result["records"]})
        # Stored FULL is never an input into execution classification.
        gm_lines = list(dict.fromkeys(gm_lines))
        removed = list(dict.fromkeys(removed))
        if not any(v["effects"] for v in variants):
            issues.append(self._issue("empty_effects", "The selected authority branches contain no executable effect rows; stored coverage is not execution evidence.", source, self.anchors["reaction_effects"], self.anchors["action_riders"]))
        if removed:
            issues.append(self._issue("covers_without_proof", "Feature covers hide these sentences by text match. This audit records suppression separately from verified implementation.", self.feature_sources[mechanic_id], self.anchors["covers"]))
        if gm_lines:
            issues.append(self._issue("retained_gm_lines", f"The compiler's rider filter retains {len(gm_lines)} distinct reminder texts for this mechanic.", self.anchors["gm_filter"], source))
        if mechanic.get("activation", {}).get("requirement") and supported:
            unknown += 1
            issues.append(self._issue("activation_requirement", "The printed activation requirement needs a character/target-specific check before full coverage can be claimed.", source, self.anchors["economy"]))
        if supported and (mechanic.get("cost") or mechanic.get("use_limit") not in (None, "", "none", "None")):
            unknown += 1
            issues.append(self._issue("cost_or_use_limit", "The printed payment or use limit requires a character resource/reset context that this static validator does not prove.", source, self.evidence.at(COMPILER, "def _costs(")))
        if supported and (any(v["mechanic"].get("area") for v in variants) or ((mechanic.get("activation") or {}).get("trigger") and route == "action")):
            unknown += 1
            issues.append(self._issue("area_or_trigger_context", "The area or conditional activation needs compiled geometry/eligibility beyond the effect-kind proof.", source, self.evidence.at(COMPILER, "def _target_kind(")))
        if supported:
            for variant in variants:
                reach = variant["mechanic"].get("range")
                if reach and (not isinstance(reach, dict) or reach.get("kind") not in {"feet", "self"}
                              or (reach.get("kind") == "feet" and (type(reach.get("feet")) is not int or reach["feet"] <= 0))
                              or (reach.get("kind") == "self" and reach.get("feet") not in (None, 0))
                              or set(reach) - {"kind", "feet", "evidence", "source"}):
                    unknown += 1
                    issues.append(self._issue("range_context", "This range requires character-, weapon-, or level-specific resolution outside the reviewed literal range forms.", source, self.evidence.at(COMPILER, "def _target_kind(")))
                    break
        target_text = str(mechanic.get("target") or "")
        if supported and re.search(r"\b(node|eye|servant|summon|construct|companion|object|structure|formation|weapon)\b", target_text, re.I):
            unknown += 1
            issues.append(self._issue("special_target", "The printed target is a special entity or equipment; a generic effect handler does not establish that target's support.", source, self.evidence.at(COMPILER, "def _target_kind(")))
        if not route_known:
            # Even a known generic-route rejection does not disprove an exact
            # plugin or compiler replacement, hence UNKNOWN rather than MANUAL.
            has_alternative = bool(block or claims or mechanic.get("modifier") or mechanic_id in compiler.HANDLED_IN_CODE)
            status = "UNKNOWN" if has_alternative or route == "reaction" and trigger and trigger["runnable"] else "MANUAL"
        elif unknown:
            status = "PARTIAL" if supported else "UNKNOWN"
        elif manual or gm_lines or option_issues or not supported:
            status = "PARTIAL" if supported else "MANUAL"
        else:
            status = "REAL_FULL"
        if claims and status == "REAL_FULL":
            # References are retained as evidence, but cannot by themselves
            # overrule a simple proved base effect. Exact block overrides above
            # already prevent full credit; arbitrary hook applicability is open.
            status = "UNKNOWN"
            issues.append(self._issue("plugin_interaction", "An executable plug-in reference or effect handler may alter this route; its full interaction is unresolved.", source))
        if self.plugins.diagnostics or self.plugins.unresolved_block_compilers:
            status = "UNKNOWN"
            issues.append(self._issue("incomplete_plugin_index", "Missing, unparsable, or dynamically unresolved plug-in registration prevents a reliable positive or negative classification.", source))
        elif components:
            # Source-reviewed, hash-bound components earn partial credit. They
            # do not certify every word, recipient, lifecycle, or interaction.
            status = "PARTIAL"
            issues.append(self._issue("verified_plugin_component", "A reviewed plug-in component has a compiled ownership route and a source-backed runtime consumer; its full printed ability remains only partly established.",
                                      *[ref for component in components for ref in component["evidence"]]))
        distinct_issues = []
        seen = set()
        for issue in issues:
            key = stable_json(issue)
            if key not in seen:
                seen.add(key)
                distinct_issues.append(issue)
        reason = {
            "REAL_FULL": "A direct action has only statically validated effects and no retained GM riders or unresolved route requirements.",
            "PARTIAL": "A direct action or reviewed plug-in has a validated mechanical component and still has manual or unresolved components.",
            "MANUAL": "No supported execution is established on the known generic route, and no specific alternative implementation was found.",
            "UNKNOWN": "The available static evidence cannot prove the complete execution route or effect behavior.",
        }[status]
        return {"mechanic_id": mechanic_id, "name": mechanic.get("name"), "group_id": group_id, "group": group_name, "group_kind": group_kind,
                "stored_coverage": mechanic.get("coverage"), "classification": status, "reason": reason,
                "source": source, "source_pointer": "/mechanics/" + mechanic_id.replace("~", "~0").replace("/", "~1"),
                "economy": economy, "route": route, "direct_route_proved": route_known,
                "trigger": trigger, "feature_block": block, "feature_source": self.feature_sources.get(mechanic_id),
                "gm_lines": gm_lines, "gm_line_count": len(gm_lines),
                "variant_gm_line_instances": sum(len(v["gm_lines"]) for v in rendered_variants),
                "direct_action_gm_line_count": len(gm_lines) if route_known and route == "action" else 0,
                "gm_emission": "direct_action_templates" if route_known and route == "action" else "projection_only_route_unresolved_or_not_an_action",
                "sentences_suppressed_by_covers": removed, "plugin_claims": claims,
                "verified_plugin_components": components,
                "effect_counts": raw_effect_counts,
                "component_counts": {"supported": supported, "manual": manual, "unknown": unknown},
                "issues": distinct_issues, "variants": rendered_variants}

    def report(self) -> dict:
        if self._input_manifest() != self.input_manifest:
            raise ValueError("Audit inputs changed after snapshot construction; create a fresh audit.")
        records = [self.classify(mid) for mid in sorted(self.mechanics)]
        groups = defaultdict(list)
        for record in records:
            groups[record["group_id"]].append(record)

        def totals(rows):
            counts = Counter(row["classification"] for row in rows)
            return {"mechanics": len(rows), **{status: counts[status] for status in STATUSES},
                    "gm_reminder_lines": sum(row["gm_line_count"] for row in rows),
                    "direct_action_gm_lines": sum(row["direct_action_gm_line_count"] for row in rows),
                    "variant_gm_line_instances": sum(row["variant_gm_line_instances"] for row in rows),
                    "covered_sentences": sum(len(row["sentences_suppressed_by_covers"]) for row in rows)}

        group_totals = [{"id": gid, "name": rows[0]["group"], "kind": rows[0]["group_kind"], **totals(rows)} for gid, rows in sorted(groups.items())]
        false_full = defaultdict(list)
        for row in records:
            if row["stored_coverage"] == "FULL" and row["classification"] != "REAL_FULL":
                for code in sorted({issue["code"] for issue in row["issues"]}):
                    false_full[code].append(row["mechanic_id"])
        plugin_counts = Counter()
        for row in records:
            if row["stored_coverage"] != "FULL":
                if row["sentences_suppressed_by_covers"]:
                    plugin_counts["non_full_with_covers_suppression"] += 1
                if row["plugin_claims"]:
                    plugin_counts["non_full_with_plugin_evidence"] += 1
                if row["feature_block"]:
                    plugin_counts["non_full_with_feature_block"] += 1
                if row["verified_plugin_components"]:
                    plugin_counts["non_full_with_verified_plugin_component"] += 1
        inputs = self._input_manifest()
        if inputs != self.input_manifest:
            raise ValueError("Audit inputs changed during analysis; no mixed-snapshot report was produced.")
        return {"schema": "CultivationFactory.AutomationTruth.v1", "method": "static; no fights; no model calls",
                "input_sha256": hashlib.sha256(stable_json(inputs).encode()).hexdigest(), "inputs": inputs,
                "definitions": {
                    "REAL_FULL": "Verified within the audit's bounded static validators; not a proof that the typed record faithfully includes every printed rule.",
                    "PARTIAL": "A supported direct mechanical or reviewed plug-in component plus manual or unresolved parts.",
                    "MANUAL": "No supported known generic route and no specific alternative implementation evidence.",
                    "UNKNOWN": "Static analysis cannot establish applicability or completeness; never counted as full.",
                    "gm_reminder_lines": "Distinct texts retained by the real _gm_lines for every mechanic's included branches, deduplicated within each mechanic. This is a catalogue backlog of reminder templates, not a transcript count.",
                    "direct_action_gm_lines": "Subset on proven ordinary action/menu routes before character-specific modifications. One template counted once per mechanic.",
                    "variant_gm_line_instances": "Same filter before per-mechanic deduplication; shared reminders recur on menu options.",
                    "plugin_claims": "Executable reference/registration/dispatch evidence; claims do not prove complete automation.",
                    "component_counts": "Effect counts plus explicit empty-branch or unproved route/field checks; structural delivery nodes are not state-changing effects.",
                },
                "totals": totals(records), "stored_coverage": dict(sorted(Counter(r["stored_coverage"] for r in records).items())),
                "groups": group_totals, "top_20_by_gm_lines": sorted(group_totals, key=lambda g: (-g["gm_reminder_lines"], g["id"]))[:20],
                "stored_full_not_verified": sum(r["stored_coverage"] == "FULL" and r["classification"] != "REAL_FULL" for r in records),
                "false_full_categories": dict(sorted(false_full.items())), "uncounted_plugin_evidence": dict(sorted(plugin_counts.items())),
                "plugin_diagnostics": self.plugins.diagnostics,
                "plugin_gm_reminders": self.plugins.gm_emissions,
                "engine_evidence": self.anchors, "mechanics": records}


def check_drift_lines(committed: dict[str, str], current: dict[str, str]) -> list[str]:
    """Name the audited inputs a regenerated report no longer matches.

    Every report embeds ``input_sha256``, so one changed, missing, or extra audited
    source file makes all of them differ at once. ``--check`` prints these lines so
    that result names its own cause instead of only listing differing files. An empty
    list means the audited sources are byte-identical to the committed manifest.
    """
    shared = set(committed) & set(current)
    groups = (("present in this checkout but not in the committed manifest",
               sorted(set(current) - set(committed))),
              ("missing from this checkout but named by the committed manifest",
               sorted(set(committed) - set(current))),
              ("content changed since the committed report",
               sorted(key for key in shared if committed[key] != current[key])))
    lines = []
    for label, keys in groups:
        if keys:
            shown = ", ".join(keys[:12]) + (f", and {len(keys) - 12} more" if len(keys) > 12 else "")
            lines.append(f"{len(keys)} audited input file(s) {label}: {shown}")
    return lines


def _committed_manifest(path: Path) -> dict[str, str]:
    """The input manifest recorded in a checked-in report, or an empty mapping."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    inputs = data.get("inputs") if isinstance(data, dict) else None
    if not isinstance(inputs, dict):
        return {}
    return {key: value for key, value in inputs.items()
            if isinstance(key, str) and isinstance(value, str)}


def _relative_name(path: Path) -> str:
    """A repository-relative name where possible, so a diagnostic stays machine-independent."""
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


def _table(groups: list[dict]) -> list[str]:
    return ["| Sphere / Path / Foundation | Mechanics | Full | Partial | Manual | Unknown | Reminders |",
            "|---|---:|---:|---:|---:|---:|---:|", *[
                f"| {g['name'].replace('|', '/')} | {g['mechanics']} | {g['REAL_FULL']} | {g['PARTIAL']} | {g['MANUAL']} | {g['UNKNOWN']} | {g['gm_reminder_lines']} |" for g in groups]]


def render_summary(report: dict) -> str:
    t, e = report["totals"], report["engine_evidence"]
    lines = ["# Combat automation: what still needs the GM", "",
             f"**{t['gm_reminder_lines']:,} reminder texts remain across {t['mechanics']:,} mechanics after the compiler's current filtering.** "
             f"Of these, {t['direct_action_gm_lines']:,} belong to direct action/menu routes this audit can establish. "
             "The remaining texts belong to unresolved or other routes; they are retained as a visible backlog, not claimed as lines that definitely reach a fight log.", "",
             f"This uses the actual rider filter and its covers rules (`{e['gm_filter']}`, `{e['covers']}`). Shared reminders on several options count once per mechanic. "
             "It is a count of reminder templates across the catalogue. The number shown during a particular fight depends on the characters, choices, repeats, and conditional plug-in messages; this static tool does not run a fight.", "",
             "| Result | Mechanics |", "|---|---:|", *[f"| {status} | {t[status]:,} |" for status in STATUSES], "",
             "**Full** means the audit can establish a direct route and every effect it validates. **Partial** means there is a working component with manual or unresolved parts. "
             "**Manual** means no supported generic execution or specific alternative was found. **Unknown** means more evidence is needed. Unknowns are never counted as full.", "",
             "These totals measure what this bounded static audit can prove. The large Unknown group needs additional implementation contracts or runtime evidence; this report does not claim an overall automation percentage.", "",
             f"{report['stored_full_not_verified']:,} mechanics labelled FULL in the authority are not verified full by this audit. "
             "This includes proven gaps and unresolved cases, which the detailed report distinguishes. It is not a count of proven broken abilities.", "",
             f"Feature covers hide {t['covered_sentences']:,} distinct sentences. Hiding a reminder alone is not evidence that the rule runs "
             f"(`{e['covers']}`, `{e['plugin_compile']}`). Plug-in claims and conditional reminder emitters are recorded separately in the JSON.", "",
             f"The audit verifies limited plug-in components on {sum(bool(r['verified_plugin_components']) for r in report['mechanics'])} mechanics, "
             f"including {report['uncounted_plugin_evidence'].get('non_full_with_verified_plugin_component', 0)} whose stored label is below FULL. "
             "Their proofs identify the implemented component, source files, and remaining limitations in the detailed records.", "",
             "## Where the reminder backlog is largest", "", *_table(report["top_20_by_gm_lines"]), "",
             "## Read and rerun", "",
             "- Per-mechanic index and all group totals: `AUTOMATION_TRUTH_R1.json`. Its `detail_parts` link to the complete records, exact remaining text, and evidence in `AUTOMATION_TRUTH_R1.d/`.",
             "- Findings, examples, limits, and proposed automation work: `AUTOMATION_TRUTH_AUDIT.md`.",
             "- From `APP`: `python -m tools.automation_truth`. Add `--check` to verify the checked-in reports without writing them.", "",
             f"Input fingerprint: `{report['input_sha256']}`. Reports contain no clock or machine-specific paths."]
    return "\n".join(lines) + "\n"


def render_audit(report: dict) -> str:
    by_id = {row["mechanic_id"]: row for row in report["mechanics"]}
    e = report["engine_evidence"]
    lines = ["# Automation truth audit — P20261005-12", "",
             "## Scope and evidence", "",
             "This is a static audit of the committed typed authority, compile-time rider filter, trigger classifier, executor dispatch, and registered plug-in source. "
             "It does not change game behavior, data, plug-ins, saved fights, or lock files. It does not instantiate a fight or call a model.", "",
             f"The authority contains {report['totals']['mechanics']:,} mechanics. The JSON records every one and preserves UNKNOWN results. "
             f"Engine registration is necessary but not sufficient: the dispatcher falls back to a GM rider for absent handlers (`{e['dispatch']}`), "
             f"while feature compilation can replace ordinary actions (`{e['feature_skip']}`).",
             "",
             "### What the reminder count means", "",
             f"The primary count applies `_gm_lines` to each included source branch (`{e['gm_filter']}`). It respects whole-entry feature overrides "
             f"in sorted shard order (`{e['feature_override']}`), exact normalized sentence covers, option-specific riders, choice labels, and the action menu cap (`{e['options']}`). "
             "Identical text on several options counts once for its mechanic; the JSON also reports the number before this deduplication.", "",
             f"A generic reaction stores its effect tree but does not copy the mechanic's rider list (`{e['generic_reaction']}`). "
             "Skipped passives, modifiers, and feature block replacements likewise are not ordinary action rider surfaces. Their retained source reminders are labelled projection-only in each result. "
             "The direct-action subtotal excludes those unresolved routes. Conditional GM_RIDER calls inside plug-ins are inventoried separately when statically visible; no transcript frequency is inferred.", "",
             "A single exact per-fight line total cannot be obtained without a party, build, choices, and event sequence. Reporting the whole catalogue sum as an actual fight log would repeat the original metric error. "
             "The useful static owner metric is the reminder backlog, alongside its direct-action subtotal, silent/unresolved gaps, and plug-in reminder inventory.", "",
             "### Boundaries of REAL_FULL", "",
             "REAL_FULL uses conservative, parameter-aware effect validators and a proven ordinary action route. It is a bounded static result, not a semantic proof that typing preserved every sentence of the print. "
             "No registered plug-in, ID match, empty reminder list, stored coverage label, or already_applied declaration earns full credit on its own. "
             "Unknown effect parameters, contextual reactions, modifiers, activation requirements, and replacement blocks retain explicit uncertainty. This audit does not execute extension hooks.", "",
             "The input universe also contains build choices and outside-combat procedures. Their presence in the manual/unknown totals is not evidence of a broken combat action. Every record's economy and source remain visible for review; none is silently dropped from the denominator.", "",
             "The authority JSON is intentionally stored on one line. Its source references therefore correctly use `:1`; each record also includes an exact JSON pointer and mechanic ID. No artificial line numbers are assigned.", "",
             "## Stored FULL findings", "",
             f"There are {report['stored_full_not_verified']:,} stored-FULL records not verified as REAL_FULL. Categories below overlap; counts are mechanics, not effect rows. "
             "An unresolved case is not automatically a proven false claim. Each example lists its actual result, ability ID, authority location, and the relevant engine evidence.", ""]
    for code, ids in report["false_full_categories"].items():
        lines += [f"### {code.replace('_', ' ').capitalize()} — {len(ids)}", ""]
        for mid in ids[:3]:
            row = by_id[mid]
            issue = next(issue for issue in row["issues"] if issue["code"] == code)
            refs = ", ".join(f"`{ref}`" for ref in dict.fromkeys([row["source"], *issue.get("evidence", [])]))
            lines.append(f"- `{mid}` — **{row['classification']}**. {issue['reason']} Evidence: {refs}.")
        if len(ids) < 3:
            lines.append(f"Only {len(ids)} example(s) exist in this category; no additional examples are invented.")
        lines.append("")
    override_rows = [r for r in report["mechanics"] if any(i["code"] == "weapon_damage_override" for i in r["issues"])]
    if not override_rows:
        lines += ["### Weapon damage type override — 0 in this authority", "",
                  "The brief names this risk, but no current effect combines weapon_damage with a damage_types override in this snapshot. The regression is synthetic. "
                  "The auditor checks the field interaction instead of inventing three examples.", ""]
    lines += ["## Plug-in automation omitted by the stored label", "",
              "These are evidence categories, not automatic FULL promotions. A compile_block registration must still return applicable rows and have a reachable consumer; "
              f"the engine explicitly checks returned rows (`{e['plugin_compile']}`). Covers are a separate declaration (`{e['covers']}`).", "",
              "| Evidence among records not labelled FULL | Mechanics |", "|---|---:|", *[
                  f"| {name.replace('_', ' ')} | {count} |" for name, count in report["uncounted_plugin_evidence"].items()], ""]
    for label, predicate in (
        ("Covered rider sentences", lambda r: r["sentences_suppressed_by_covers"]),
        ("Registered effect, hook, or block claims", lambda r: r["plugin_claims"]),
        ("Feature blocks outside stored FULL", lambda r: r["feature_block"]),
    ):
        lines += [f"### {label}", ""]
        selected = [r for r in report["mechanics"] if r["stored_coverage"] != "FULL" and predicate(r)]
        if not selected:
            lines.append("No matching records are present in this snapshot. No examples are inferred from covers declarations alone.")
        for row in selected[:3]:
            refs = [row["source"]]
            if row["feature_source"]:
                refs.append(row["feature_source"])
            refs += [ref for claim in row["plugin_claims"][:2] for ref in claim.get("evidence", [])]
            lines.append(f"- `{row['mechanic_id']}` ({row['name']}): stored {row['stored_coverage']}; audit {row['classification']}; "
                         f"{len(row['sentences_suppressed_by_covers'])} covered sentence(s), {len(row['plugin_claims'])} claim record(s). "
                         "Evidence: " + ", ".join(f"`{ref}`" for ref in dict.fromkeys(refs)) + ".")
        lines.append("")
    components = [component for row in report["mechanics"] for component in row["verified_plugin_components"]]
    lines += ["### Source-reviewed components (partial credit)", "",
              f"{len(components)} mechanics have a component whose block shape, winning feature row, and compiler/consumer implementation have been reviewed. "
              "These proofs are bound to exact source SHA-256 values. Source changes invalidate the proof until reviewed; a matching registration by itself is insufficient. "
              "All of these remain PARTIAL because complete print fidelity and all contexts are outside the proof.", "",
              "| Component family | Mechanics | Below stored FULL |", "|---|---:|---:|", *[
                  f"| {block} | {sum(c['block'] == block for c in components)} | {sum(c['block'] == block and by_id[c['mechanic_id']]['stored_coverage'] != 'FULL' for c in components)} |"
                  for block in sorted({c["block"] for c in components})], ""]
    for mid in ("TAL_LIGHTNING_GROUNDING_BREATH", "TAL_DAEMONIC_CULTIVATION_DEMON_BONE_REGENERATION", "STARS_TAL_FALLING_STAR"):
        row = by_id.get(mid)
        if row and row["verified_plugin_components"]:
            component = row["verified_plugin_components"][0]
            lines += [f"- `{mid}`: {component['reason']} " + "Evidence: " + ", ".join(f"`{ref}`" for ref in component["evidence"]) + ". "
                      + "Limits: " + " ".join(component["limitations"])]
    emissions = report["plugin_gm_reminders"]
    lines += ["", "### Conditional plug-in reminder sources", "",
              f"There are {sum(r['status'] == 'STATIC_GM_EMISSION_SITE' for r in emissions)} explicit GM_RIDER event sites and "
              f"{sum(r['status'] == 'POSSIBLE_GM_EMISSION_SITE' for r in emissions)} possible rider-method sites. "
              f"{sum(r['template_status'] == 'UNKNOWN_DYNAMIC_TEMPLATE' for r in emissions)} messages are dynamic and cannot be rendered as one fixed static string. "
              "The complete inventory gives each site's exact source and marks uncertain method receivers and mechanic associations. These site counts are not added to the catalogue reminder count.", ""]
    for site in emissions[:3]:
        lines.append(f"- `{site['module']}.{site['function']}` — {site['status']}; {site['template_status']}. Evidence: " + ", ".join(f"`{ref}`" for ref in site["evidence"]) + ".")
    lines.append("")
    lines += ["## Top 20 spheres / Paths by remaining reminders", "", *_table(report["top_20_by_gm_lines"]), "",
              "All 85 spheres and every authority Path, subpath, and Foundation are separately totalled in the JSON. Missing sphere IDs are grouped by their actual authority IDs, not collapsed into a misleading question-mark bucket.", "",
              "## General fixes to send to the automation lanes", "",
              f"1. **Make covers conditional on an implementation contract.** Connect each retired sentence to a compiled block/effect, applicable runtime consumer, and targeted regression. "
              f"Keep a reminder when that contract cannot be established. The current filter trusts the text list directly (`{e['covers']}`); no such behavior change is made here.",
              f"2. **Preserve unresolved reaction rules visibly.** Route failures and missing effect branches need explicit diagnostics/reminders, including a reaction's source riders. "
              f"Share the current trigger classifier and check the complete compile gate, not only a phrase label (`{e['trigger_gate']}`, `{e['reaction_effects']}`, `{e['reaction_resource']}`).",
              f"3. **Publish parameter-aware effect contracts.** A dispatcher key should declare supported fields, nested branches, contexts, and fallback behavior. "
              f"Validate deferred effects and context-only handlers against that contract (`{e['dispatch']}`). A registry membership test alone is too weak.",
              f"4. **Audit modifier attachments as combinations.** Build bounded, deterministic fixtures for destination matching, optional payment, nested branches, and option caps. "
              f"A standalone modifier record cannot show whether it attaches (`{e['modifier']}`, `{e['options']}`).",
              f"5. **Retire already_applied declarations only with traceable readers.** Distinguish sheet statistics, compiler changes, and runtime hooks, with a source reference and a test for each "
              f"(`{e['already_applied']}`, `{e['feature_skip']}`).",
              "6. **Prioritize by the measured reminder backlog.** Use the top-20 table to choose a bounded set of repeated rider patterns. Track retained templates, known silent gaps, and UNKNOWN separately; a lower reminder count is progress only when the retired rules have validated implementations.", "",
              "These are proposed follow-up changes, not implemented engine changes. The per-mechanic JSON identifies exact source records for lane assignment.", "",
              "## Verification and reproducibility", "",
              "From `APP`:", "", "```sh", "python -m unittest discover -s tests -p 'test_automation_truth*.py'", "python -m tools.automation_truth --check", "```", "",
              "The tests cover real mechanics and adversarial fixtures, source evidence, option handling, covers, conservative plug-in claims, and byte-for-byte repeatability. "
              "One test reruns `--check` in a second process with a different `PYTHONHASHSEED`, so a differing report cannot be blamed on set or dictionary ordering; "
              "another asserts that no rendered report byte contains a repository path, interpreter path, or timestamp. "
              "No live-machine, saved-fight, provider, or combat simulation result is claimed by these commands. Runtime integration and printed-text fidelity remain separate reviewer work.", "",
              "Every report embeds the `input_sha256` fingerprint of all audited sources listed in `inputs`. A tree whose combat sources differ from the ones a committed report was built from therefore fails `--check` for all files at once; "
              "the failure message names the added, missing, and changed input files rather than only the reports that differ. Regenerate only from the commit whose sources the report describes.", "",
              f"Input fingerprint: `{report['input_sha256']}`. Exact source file SHA-256 values, static diagnostics, and the per-mechanic index are in `AUTOMATION_TRUTH_R1.json`; "
              "its hash-checked `detail_parts` contain every complete decision in `AUTOMATION_TRUTH_R1.d/`."]
    return "\n".join(lines) + "\n"


def report_outputs(report: dict, json_path: Path, summary_path: Path, audit_path: Path) -> list[tuple[Path, str]]:
    """Keep the JSON report reviewable and fetchable through bounded connectors.

    The index retains every classification and count. Detail parts are ordinary
    JSON, containing all evidence and literal reminders, with SHA-256/ID bounds
    in the index. No report information is discarded or sampled.
    """
    index_fields = ("mechanic_id", "name", "group_id", "classification", "reason", "stored_coverage", "source", "source_pointer",
                    "gm_line_count", "direct_action_gm_line_count")
    index = {key: value for key, value in report.items() if key != "mechanics"}
    index.update(storage="partitioned-json-v1", detail_parts=[], mechanics=[])
    directory = json_path.parent / (json_path.stem + ".d")
    outputs = []
    for start in range(0, len(report["mechanics"]), 200):
        rows = report["mechanics"][start:start + 200]
        path = directory / f"mechanics-{start // 200:03d}.json"
        content = stable_json({"schema": "CultivationFactory.AutomationTruthDetails.v1", "input_sha256": report["input_sha256"], "mechanics": rows})
        relative = path.relative_to(json_path.parent).as_posix()
        index["detail_parts"].append({"path": relative, "sha256": hashlib.sha256(content.encode()).hexdigest(), "mechanics": len(rows),
                                      "first_id": rows[0]["mechanic_id"], "last_id": rows[-1]["mechanic_id"]})
        index["mechanics"].extend({**{key: row[key] for key in index_fields}, "details": relative} for row in rows)
        outputs.append((path, content))
    return [(json_path, stable_json(index)), (summary_path, render_summary(report)), (audit_path, render_audit(report)), *outputs]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=JSON_PATH, help="JSON report destination")
    parser.add_argument("--summary", type=Path, default=SUMMARY_PATH, help="Short owner summary destination")
    parser.add_argument("--audit", type=Path, default=AUDIT_PATH, help="Detailed audit destination")
    parser.add_argument("--check", action="store_true", help="Compare all reports without writing")
    args = parser.parse_args(argv)
    report = AutomationAudit().report()
    outputs = report_outputs(report, args.json, args.summary, args.audit)
    changed = []
    for path, text in outputs:
        if args.check:
            if not path.is_file() or path.read_bytes() != text.encode("utf-8"):
                changed.append(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
    if changed:
        # Every report embeds input_sha256, so one moved audited source makes all of them
        # differ. Name the inputs that moved, and the reports, not only the count.
        committed = _committed_manifest(args.json)
        print(f"Reports differ: {len(changed)} of {len(outputs)} generated files: "
              + ", ".join(_relative_name(path) for path in changed), file=sys.stderr)
        print(f"Input fingerprint: this run {report['input_sha256']}; committed report "
              + (hashlib.sha256(stable_json(committed).encode()).hexdigest() if committed else "unknown"),
              file=sys.stderr)
        for line in check_drift_lines(committed, report["inputs"]) or [
                "Every audited input file matches the committed manifest; the difference is in the report text."]:
            print(line, file=sys.stderr)
        print("Regenerate from APP with: python -m tools.automation_truth", file=sys.stderr)
        return 1
    print(stable_json(report["totals"]).strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
