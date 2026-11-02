from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class FormulaError(ValueError):
    pass


@dataclass(frozen=True)
class FormulaResult:
    value: int
    trace: dict[str, Any]


def _number(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FormulaError(f"{label} must be an integer")
    return value


def evaluate_formula(formula: dict[str, Any], context: dict[str, Any], *, max_depth: int = 32, max_nodes: int = 256) -> FormulaResult:
    """Evaluate the Foundry's bounded, non-executable integer formula AST.

    No dynamic language, expression string, eval, import, callable, or attribute
    access is accepted. The output trace is deterministic and suitable for
    calculation provenance.
    """
    nodes = 0

    def walk(node: Any, depth: int) -> tuple[int, dict[str, Any]]:
        nonlocal nodes
        nodes += 1
        if nodes > max_nodes:
            raise FormulaError("formula exceeds node limit")
        if depth > max_depth:
            raise FormulaError("formula exceeds depth limit")
        if not isinstance(node, dict):
            raise FormulaError("formula node must be an object")
        op = node.get("op")
        if op == "constant":
            value = _number(node.get("value"), "constant.value")
            return value, {"op": op, "value": value}
        if op == "cl":
            value = _number(context.get("cl"), "context.cl")
            return value, {"op": op, "value": value}
        if op == "pb":
            value = _number(context.get("pb"), "context.pb")
            return value, {"op": op, "value": value}
        if op in {"ability_score", "ability_modifier"}:
            ability = node.get("ability")
            if ability not in {"STR", "DEX", "CON", "INT", "WIS", "CHA"}:
                raise FormulaError(f"invalid ability: {ability}")
            table_name = "ability_scores" if op == "ability_score" else "ability_modifiers"
            table = context.get(table_name)
            if not isinstance(table, dict) or ability not in table:
                raise FormulaError(f"missing {table_name}.{ability}")
            value = _number(table[ability], f"{table_name}.{ability}")
            return value, {"op": op, "ability": ability, "value": value}
        if op == "selected_path_base":
            key = node.get("key")
            table = context.get("selected_path_base")
            if not isinstance(key, str) or not isinstance(table, dict) or key not in table:
                raise FormulaError(f"missing selected path base: {key}")
            value = _number(table[key], f"selected_path_base.{key}")
            return value, {"op": op, "key": key, "value": value}
        if op in {"add", "multiply", "minimum", "maximum"}:
            terms = node.get("terms")
            if not isinstance(terms, list) or len(terms) < 1:
                raise FormulaError(f"{op}.terms must be a non-empty array")
            resolved = [walk(term, depth + 1) for term in terms]
            values = [value for value, _ in resolved]
            if op == "add":
                value = sum(values)
            elif op == "multiply":
                value = 1
                for term in values:
                    value *= term
            elif op == "minimum":
                value = min(values)
            else:
                value = max(values)
            return value, {"op": op, "terms": [trace for _, trace in resolved], "value": value}
        if op == "subtract":
            left, left_trace = walk(node.get("left"), depth + 1)
            right, right_trace = walk(node.get("right"), depth + 1)
            value = left - right
            return value, {"op": op, "left": left_trace, "right": right_trace, "value": value}
        if op == "clamp":
            raw, raw_trace = walk(node.get("value"), depth + 1)
            minimum = node.get("minimum")
            maximum = node.get("maximum")
            if minimum is not None:
                minimum = _number(minimum, "clamp.minimum")
            if maximum is not None:
                maximum = _number(maximum, "clamp.maximum")
            if minimum is not None and maximum is not None and minimum > maximum:
                raise FormulaError("clamp minimum exceeds maximum")
            value = raw
            if minimum is not None:
                value = max(value, minimum)
            if maximum is not None:
                value = min(value, maximum)
            return value, {"op": op, "value_node": raw_trace, "minimum": minimum, "maximum": maximum, "value": value}
        raise FormulaError(f"unsupported formula operation: {op}")

    value, trace = walk(formula, 0)
    return FormulaResult(value=value, trace={"schema_version": "TianxiaFoundry.SafeFormulaTrace.v1", "node_count": nodes, "root": trace})
