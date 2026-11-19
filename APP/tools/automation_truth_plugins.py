"""Conservative, deterministic source index for the automation truth audit.

This module does not import plug-ins or run a game.  A decorator proves that
source declares a handler; an identifier proves only a source reference.  In
particular, neither is proof that an ability's printed rules are implemented.
The main audit must combine this index with its actual compiler results.
"""

from __future__ import annotations

import ast
import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator


_MISSING = object()
_DISPATCHERS = frozenset({
    "run", "run_strict", "run_checkpoint", "run_nested", "transform",
    "transform_last", "any_false", "vetoing_hooks",
})


def _strings(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return set().union(*(_strings(item) for pair in value.items() for item in pair), set())
    if isinstance(value, (tuple, list, set, frozenset)):
        return set().union(*(_strings(item) for item in value), set())
    return set()


def _value(node: ast.AST, assignments: dict[str, ast.AST], seen: frozenset[str] = frozenset()) -> Any:
    """Resolve only literal expressions; never evaluate calls, imports or code."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in assignments and node.id not in seen:
        return _value(assignments[node.id], assignments, seen | {node.id})
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values = [_value(item, assignments, seen) for item in node.elts]
        return values if all(item is not _MISSING for item in values) else _MISSING
    if isinstance(node, ast.Dict):
        items = [(_value(key, assignments, seen), _value(val, assignments, seen))
                 for key, val in zip(node.keys, node.values) if key is not None]
        if len(items) != len(node.keys) or any(key is _MISSING or val is _MISSING for key, val in items):
            return _MISSING
        try:
            return dict(items)
        except TypeError:
            return _MISSING
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _value(node.left, assignments, seen), _value(node.right, assignments, seen)
        if isinstance(left, str) and isinstance(right, str):
            return left + right
    if isinstance(node, ast.JoinedStr):
        pieces = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                pieces.append(part.value)
            elif isinstance(part, ast.FormattedValue) and part.format_spec is None and part.conversion in {-1, 115}:
                value = _value(part.value, assignments, seen)
                if not isinstance(value, (str, int, bool)):
                    return _MISSING
                pieces.append(str(value))
            else:
                return _MISSING
        return "".join(pieces)
    return _MISSING


def _code_nodes(statements: Iterable[ast.AST]) -> Iterator[ast.AST]:
    """Ignore docstrings and nested definitions that need their own invocation."""
    for node in statements:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        yield node
        yield from _code_nodes(ast.iter_child_nodes(node))


def _imports(tree: ast.Module, *, plugin: bool) -> tuple[dict[str, str], set[str]]:
    names: dict[str, str] = {}
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            is_ext = node.module in {"combat.ext", "APP.combat.ext"} or (
                node.module == "ext" and bool(node.level)) or (
                plugin and node.module is None and node.level == 1)
            for alias in node.names:
                if is_ext and alias.name in {"hook", "effect", *_DISPATCHERS}:
                    names[alias.asname or alias.name] = alias.name
                if alias.name == "ext" and (node.module in {None, "combat", "APP.combat"}):
                    modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"combat.ext", "APP.combat.ext"} and alias.asname:
                    modules.add(alias.asname)
    return names, modules


def _call_kind(call: ast.Call, names: dict[str, str], modules: set[str]) -> str | None:
    if isinstance(call.func, ast.Name):
        return names.get(call.func.id)
    if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and call.func.value.id in modules:
        return call.func.attr
    return None


def _unique(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    import json

    by_value = {json.dumps(record, sort_keys=True, ensure_ascii=False): record for record in records}
    return [by_value[key] for key in sorted(by_value)]


@dataclass
class PluginIndex:
    """JSON-serializable declarations and references, without automation verdicts.

    ``blocks`` contains explicit equality/membership guards on a registered
    compile_block callback's first parameter.  The compiler can still return
    nothing, reject a feature's prerequisites, or produce an incomplete row.
    ``effects`` and ``hooks`` index declared registrations, not successful
    imports or executed callbacks.  ``hook_dispatches`` records visible source
    calls, not proof that an individual mechanic reaches one.
    """

    hooks: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    effects: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    blocks: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    block_consumers: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    mechanic_claims: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    hook_dispatches: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    unresolved_block_compilers: list[dict[str, Any]] = field(default_factory=list)
    gm_emissions: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    def claims_for(self, mechanic_id: str, *, block_names: Iterable[str] = (),
                   effect_names: Iterable[str] = (), ability_id: str | None = None) -> list[dict[str, Any]]:
        """Return independent records; ability aliases must be supplied by a caller.

        We deliberately do not strip ``factory:`` or guess aliases from names.
        Supply ``ability_id`` only when an authority/compiler relationship
        establishes that it belongs to this mechanic.
        """
        claims = list(self.mechanic_claims.get(mechanic_id, ()))
        if ability_id is not None and ability_id != mechanic_id:
            for claim in self.mechanic_claims.get(ability_id, ()):
                claims.append({**claim, "authority_mechanic_id": mechanic_id,
                               "alias_basis": "caller supplied authority/compiler relationship"})
        for block in sorted(set(block_names)):
            claims.extend(self.blocks.get(block, ()))
            claims.extend(self.block_consumers.get(block, ()))
        for effect in sorted(set(effect_names)):
            claims.extend(self.effects.get(effect, ()))
        modules = {claim["module"] for claim in claims}
        for emission in self.gm_emissions:
            if emission["module"] in modules:
                claims.append({**emission, "applicability": "UNKNOWN_MODULE_ASSOCIATION",
                               "reason": "This plug-in module has a GM reminder emission site; applicability to this individual mechanic is unverified."})
        return copy.deepcopy(_unique(claims))


def _assignments(tree: ast.Module) -> tuple[dict[str, ast.AST], dict[str, int]]:
    values: dict[str, ast.AST] = {}
    lines: dict[str, int] = {}

    def bind(target: ast.AST, value: ast.AST, line: int) -> None:
        if isinstance(target, ast.Name):
            values[target.id] = value
            lines[target.id] = line
        elif isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (ast.Tuple, ast.List)) and len(target.elts) == len(value.elts):
            for child, item in zip(target.elts, value.elts):
                bind(child, item, line)

    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        for target in targets:
            bind(target, value, node.lineno)
    return values, lines


def _registered_functions(tree: ast.Module, path: str, module: str,
                          assignments: dict[str, ast.AST]) -> list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, dict[str, Any]]]:
    names, modules = _imports(tree, plugin=True)
    out = []
    for function in tree.body:
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in function.decorator_list:
            if not isinstance(decorator, ast.Call) or not decorator.args:
                continue
            kind = _call_kind(decorator, names, modules)
            name = _value(decorator.args[0], assignments)
            if kind not in {"hook", "effect"} or not isinstance(name, str):
                continue
            out.append((function, {
                "category": "plugin_" + kind + "_registration", "status": "REGISTERED_HANDLER",
                "module": module, "hook": name if kind == "hook" else None,
                "effect": name if kind == "effect" else None, "function": function.name,
                "evidence": [f"{path}:{decorator.lineno}", f"{path}:{function.lineno}"],
                "reason": "Source declares a handler; successful import, applicability and complete rule execution are unverified.",
            }))
    return out


def _references(function: ast.FunctionDef | ast.AsyncFunctionDef, functions: dict[str, Any],
                assignments: dict[str, ast.AST], assignment_lines: dict[str, int],
                known: set[str], path: str) -> dict[str, list[str]]:
    """Reach only explicitly called same-module helpers; retain call-site evidence."""
    found: dict[str, set[str]] = {}
    pending = [(function.name, ())]
    visited: set[str] = set()
    while pending:
        name, call_sites = pending.pop(0)
        if name in visited:
            continue
        visited.add(name)
        for node in _code_nodes(functions[name].body):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in functions:
                pending.append((node.func.id, (*call_sites, f"{path}:{node.lineno}")))
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                ids, declaration = {node.value} & known, ()
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in assignments:
                ids = _strings(_value(node, assignments)) & known
                declaration = (f"{path}:{assignment_lines[node.id]}",)
            elif isinstance(node, (ast.BinOp, ast.JoinedStr)):
                ids, declaration = _strings(_value(node, assignments)) & known, ()
            else:
                continue
            for identifier in ids:
                found.setdefault(identifier, set()).update((*call_sites, *declaration, f"{path}:{node.lineno}"))
    return {identifier: sorted(evidence) for identifier, evidence in sorted(found.items())}


def _block_guards(function: ast.FunctionDef | ast.AsyncFunctionDef,
                  assignments: dict[str, ast.AST]) -> dict[str, list[int]]:
    args = [*function.args.posonlyargs, *function.args.args]
    if not args:
        return {}
    parameter = args[0].arg
    blocks: dict[str, set[int]] = {}
    for node in _code_nodes(function.body):
        if not isinstance(node, ast.Compare):
            continue
        parts = [node.left, *node.comparators]
        for left, operator, right in zip(parts, node.ops, parts[1:]):
            other = None
            if isinstance(left, ast.Name) and left.id == parameter and isinstance(operator, (ast.Eq, ast.NotEq, ast.In, ast.NotIn)):
                other = right
            elif isinstance(right, ast.Name) and right.id == parameter and isinstance(operator, (ast.Eq, ast.NotEq)):
                other = left
            if other is not None:
                for block in _strings(_value(other, assignments)):
                    blocks.setdefault(block, set()).add(node.lineno)
    return {block: sorted(lines) for block, lines in sorted(blocks.items())}


def _reachable_functions(name: str, functions: dict[str, Any]) -> set[str]:
    pending, reached = [name], set()
    while pending:
        current = pending.pop(0)
        if current in reached:
            continue
        reached.add(current)
        pending.extend(node.func.id for node in _code_nodes(functions[current].body)
                       if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in functions)
    return reached


def _gm_emissions(tree: ast.Module, path: str, module: str, assignments: dict[str, ast.AST],
                  functions: dict[str, Any], registrations: list[Any], rider_dispatch_evidence: list[str]) -> list[dict[str, Any]]:
    """Count source emission sites, including dynamic messages; never fight events."""
    handlers: dict[str, list[dict[str, Any]]] = {}
    for function, record in registrations:
        for name in _reachable_functions(function.name, functions):
            handlers.setdefault(name, []).append(record)
    contexts = [("<module>", tree.body)] + [(node.name, node.body) for node in ast.walk(tree)
                                                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    sites = []
    for function_name, statements in contexts:
        for call in _code_nodes(statements):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                continue
            message, kind = None, None
            if call.func.attr == "_append_event" and call.args and _value(call.args[0], assignments) == "GM_RIDER":
                kind = "event"
                payload = next((keyword.value for keyword in call.keywords if keyword.arg == "payload"), None)
                if isinstance(payload, ast.Dict):
                    message = next((value for key, value in zip(payload.keys, payload.values)
                                    if isinstance(key, ast.Constant) and key.value == "rider"), None)
            elif call.func.attr == "rider":
                kind = "context_method"
                message = call.args[0] if call.args else next((keyword.value for keyword in call.keywords if keyword.arg == "text"), None)
            if kind is None:
                continue
            template = _value(message, assignments) if message is not None else _MISSING
            reached_by = handlers.get(function_name, [])
            evidence = [f"{path}:{call.lineno}"]
            if kind == "context_method":
                evidence.extend(rider_dispatch_evidence)
            sites.append({
                "category": "plugin_gm_emission", "status": "STATIC_GM_EMISSION_SITE" if kind == "event" else "POSSIBLE_GM_EMISSION_SITE",
                "module": module, "function": function_name,
                "hook": reached_by[0]["hook"] if len(reached_by) == 1 else None,
                "handlers": sorted({record["function"] for record in reached_by}),
                "hooks": sorted({record["hook"] for record in reached_by if record["hook"]}),
                "evidence": sorted(set(evidence)), "emission_kind": kind,
                "template": template if isinstance(template, str) else None,
                "template_status": "LITERAL" if isinstance(template, str) else "UNKNOWN_DYNAMIC_TEMPLATE",
                "reason": "A conditional source reminder site; invocation count is unknown without running a fight."
                          + (" The rider method receiver is not statically typed." if kind == "context_method" else ""),
            })
    return _unique(sites)


def build_plugin_index(repo_root: Path, known_mechanic_ids: Iterable[str] = ()) -> PluginIndex:
    """Index repository source only; no plug-in import or runtime evaluation.

    Missing or unparseable sources remain explicit diagnostics.  Only immediate
    ext/*.py modules are automatic loader candidates.  Dynamic registration,
    imported helper ownership and nonliteral compiler dispatch remain unknown.
    """
    root = Path(repo_root).resolve()
    extension_dir = root / "APP" / "combat" / "ext"
    result = PluginIndex()
    known = {identifier for identifier in known_mechanic_ids if isinstance(identifier, str) and identifier.strip()}
    if not extension_dir.is_dir():
        result.diagnostics.append({"category": "missing_plugin_source", "status": "UNKNOWN",
                                   "evidence": ["APP/combat/ext"], "reason": "Plug-in source directory is missing."})
        return result
    trees: dict[Path, ast.Module] = {}
    for source in sorted((root / "APP" / "combat").rglob("*.py")):
        relative = source.relative_to(root).as_posix()
        try:
            tree = ast.parse(source.read_text(encoding="utf-8-sig"), filename=relative)
        except (OSError, SyntaxError, UnicodeError) as exc:
            result.diagnostics.append({"category": "unreadable_source", "status": "UNKNOWN",
                                       "evidence": [f"{relative}:{getattr(exc, 'lineno', None) or 1}"],
                                       "reason": type(exc).__name__})
            continue
        trees[source] = tree
        names, modules = _imports(tree, plugin=source.parent == extension_dir)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if _call_kind(node, names, modules) not in _DISPATCHERS:
                continue
            if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                hook = node.args[0].value
                result.hook_dispatches.setdefault(hook, []).append({
                    "category": "hook_dispatch", "status": "STATIC_DISPATCH_VISIBLE", "hook": hook,
                    "module": ".".join(source.relative_to(root / "APP").with_suffix("").parts),
                    "function": None, "evidence": [f"{relative}:{node.lineno}"],
                    "reason": "Source calls this hook; this does not establish reachability for an individual mechanic.",
                })
    rider_dispatch_evidence = []
    executor_path = root / "APP" / "combat" / "typed_executor.py"
    if executor_path in trees:
        for node in ast.walk(trees[executor_path]):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "rider":
                for call in _code_nodes(node.body):
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "_append_event" \
                            and call.args and isinstance(call.args[0], ast.Constant) and call.args[0].value == "GM_RIDER":
                        rider_dispatch_evidence.extend([f"APP/combat/typed_executor.py:{node.lineno}",
                                                        f"APP/combat/typed_executor.py:{call.lineno}"])
    plugin_sources = []
    for source, tree in sorted(trees.items()):
        if source.parent != extension_dir or source.name == "__init__.py":
            continue
        path = source.relative_to(root).as_posix()
        module = "combat.ext." + source.stem
        assignments, assignment_lines = _assignments(tree)
        functions = {node.name: node for node in tree.body
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        registrations = _registered_functions(tree, path, module, assignments)
        plugin_sources.append((path, assignments, assignment_lines, functions, registrations))
        result.gm_emissions.extend(_gm_emissions(tree, path, module, assignments, functions, registrations, rider_dispatch_evidence))
        for function, record in registrations:
            registry = result.hooks if record["hook"] is not None else result.effects
            registry.setdefault(record["hook"] or record["effect"], []).append(record)
            for identifier, references in _references(function, functions, assignments, assignment_lines, known, path).items():
                result.mechanic_claims.setdefault(identifier, []).append({
                    **record, "category": "plugin_id_reference", "status": "UNVERIFIED_REFERENCE",
                    "matched_id": identifier, "evidence": sorted(set(record["evidence"] + references)),
                    "reason": "An exact ID appears in executable source reachable through same-module helper calls from this declared handler; scope and effect completeness remain unverified.",
                })
            if record["hook"] == "compile_block":
                guards = _block_guards(function, assignments)
                if not guards:
                    result.unresolved_block_compilers.append({
                        **record, "status": "UNKNOWN_BLOCK_DISPATCH",
                        "reason": "No literal equality/membership guard on the callback's block parameter was resolved.",
                    })
                for block, lines in guards.items():
                    result.blocks.setdefault(block, []).append({
                        **record, "category": "plugin_block_guard", "status": "REGISTERED_BLOCK_GUARD",
                        "block": block, "evidence": sorted(set(record["evidence"] + [f"{path}:{line}" for line in lines])),
                        "reason": "A declared compile_block handler compares its block argument with this value; returned rows and runtime consumption remain unverified.",
                    })
        for name, value in assignments.items():
            for identifier in sorted(_strings(_value(value, assignments)) & known):
                if any(claim["module"] == module for claim in result.mechanic_claims.get(identifier, ())):
                    continue
                result.mechanic_claims.setdefault(identifier, []).append({
                    "category": "plugin_module_id_reference", "status": "UNVERIFIED_REFERENCE",
                    "module": module, "hook": None, "function": None, "matched_id": identifier,
                    "evidence": [f"{path}:{assignment_lines[name]}"],
                    "reason": "An exact ID occurs in a module assignment; no connection to a declared handler was resolved.",
                })
    all_blocks = set(result.blocks)
    for path, assignments, assignment_lines, functions, registrations in plugin_sources:
        for function, record in registrations:
            if record["hook"] is None or record["hook"].startswith("compile_"):
                continue
            for block, references in _references(function, functions, assignments, assignment_lines, all_blocks, path).items():
                result.block_consumers.setdefault(block, []).append({
                    **record, "category": "plugin_block_reference", "status": "UNVERIFIED_BLOCK_REFERENCE",
                    "block": block, "evidence": sorted(set(record["evidence"] + references)),
                    "reason": "This declared runtime hook references the same literal compiler block through local calls; row eligibility and rule completeness remain unverified.",
                })
    for registry in (result.hooks, result.effects, result.blocks, result.block_consumers, result.mechanic_claims, result.hook_dispatches):
        for name in registry:
            registry[name] = _unique(registry[name])
    result.unresolved_block_compilers = _unique(result.unresolved_block_compilers)
    result.gm_emissions = _unique(result.gm_emissions)
    result.diagnostics = _unique(result.diagnostics)
    return result
