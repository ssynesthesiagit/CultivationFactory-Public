"""Conservative, read-only proof of the typed executor's effect paths.

This module reads Python AST and JSON. It never imports combat modules, builds a
fighter, loads extensions, or executes an effect. A handler registration is
evidence of routing only. SUPPORTED below means the small, explicitly validated
form is consumed by a reviewed core path; it is not a runtime test result.
The positive validators are pinned to the reviewed source snapshot. Any change
to a pinned dependency requires a fresh semantic review before its hash can be
updated; changing the hashes automatically would discard the proof boundary.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


_EXECUTOR = "APP/combat/typed_executor.py"
_AMOUNTS = "APP/combat/typed_amounts.py"
_MECHANICS = "APP/factory_authoring/typed_mechanics.py"
_RULES = "APP/combat/rules/typed_conditions.json"
# SOL158 re-reviewed the merged dispatchers against main 2ea534d8, including
# strike scratch/roll-benefit phases, optional forced-movement queries and DC
# providers. Atomic amount/mark operations keep their bounded semantics;
# new condition rules remain subject to the existing condition validator.
# Regenerate existing pins with tools.build_automation_truth_pins only after review.
# Prior review: SOL138r3 at c21b1892 against first parent 179ba77f.
# Recipient selection now shares area policy and preserves explicit self scope
# through nested save/attack contexts. Atomic operations and mark clocks retain
# their bounded semantics; amounts and condition rules are unchanged. Pin the
# new recipient/harm dependencies as well, so policy drift also fails closed.
# Whole-file hashes deliberately fail closed even on harmless edits. This small
# static tool does not claim to reconstruct a transitive runtime proof. The
# rules pin also protects the clock/condition meanings used by atomic forms.
# B3F3r1 semantic review: the only executor changes preserve explicit self
# recipients in speed-becomes and distinguish printed DCs from defending dice.
# Amount calculation, ADD/refresh clocks, handler bindings and validated effect
# forms are unchanged. The existing atomic validators retain their contracts;
# named DC sidecars keep their saved shape without gaining d20 reactions.
_REVIEWED_REF = "6fa939e6cb25f864b0eb584c1947e55334d60d4d"
_REVIEWED_SHA256 = {
    _EXECUTOR: "9d15b74239417e02708f3a0017d9b576fc40fa4b90643e0cde5ed2069485d718",
    "APP/combat/area_recipients.py": "6b74c903e8d3df602065eadbec4f1242cb4ccd2abddce78bc63cb8d6eccc188a",
    "APP/combat/area_recipient_rules.py": "a4ab221f85ba5d6e996141799702db386c5f5103e45c279d3a6be3e9f37493e6",
    "APP/combat/effect_harm.py": "30b7e947a9f34e12c53243d5b835b50dfbcaefa5965996e2432b87049f02858c",
    "APP/combat/ext/__init__.py": "8d0fc10e85dbc134f0c6098f8ec0a723ff64725fe2ee55fc800ac63d423836d7",
    "APP/combat/rules/area_recipient_overrides.json": "faefb22fb5ae2f7ca5dcb8bd973e33d3dd7829e6fbaa2ff0e1ed07aba784601d",
    _AMOUNTS: "d76b2c2d925944f9752a16270b74ade1024fbf6cbbb53cfb8e3b44103d4c482c",
    _MECHANICS: "5cc7e12a7741e0de0621d3ab1e7fa9133d475f05570e08f90aa37a731423beb4",
    _RULES: "8b851b86096d64882eca0ef26760bbf773378d1e2893541bc51d62b8aaded42b",
}
_BRANCHES = ("on_hit", "on_miss", "on_fail", "on_success", "effects", "then", "else")
_METADATA = {"type", "evidence", "origin", "damage_label", "label"}
_SCOPES = {"self", "target", "ally", "attacker", "enemies_in_area", "creatures_in_area"}
_NEUTRAL = {"flat": (None, 0), "formula": (None, "none", ""), "damage_types": (None, []),
            "ability": (None, "none", ""), "condition": (None, "none", ""),
            "distance_ft": (None, 0), "on": (None, ""), "deferred": (None, False)}
_DAMAGE_TYPES = {"acid", "bludgeoning", "cold", "fire", "force", "lightning", "necrotic",
                 "piercing", "poison", "psychic", "radiant", "slashing", "thunder"}
_FORMULAS = {None, "", "none", "pb", "cl", "half_pb", "double_pb", "triple_pb", "cl_x5",
             "key_ability_modifier"}
_CONTEXT_ONLY = {"ignore_resistance", "hold_at_1hp", "redirect_damage_to_self", "roll_die",
                 "on_success", "negate_attack", "set_outcome", "counter_technique",
                 "reaction_move", "attack_modifier", "damage_modifier"}
_EXPECTED_HANDLERS = {
    "damage": "block_damage", "extra_damage": "block_damage", "healing": "block_healing",
    "temp_hp": "block_temp_hp", "mark": "block_mark", "condition": "block_condition",
    "remove_condition": "block_remove_condition", "speed": "block_speed", "ac_bonus": "block_ac_bonus",
    "resistance": "block_resistance", "immunity": "block_resistance", "vulnerability": "block_vulnerability",
    "suppress_resistance": "block_suppress_resistance", "save": "block_save", "attack": "block_attack",
    "half_damage": "block_half_damage", "if_marked": "block_if_marked", "if_not_marked": "block_if_not_marked",
}


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


@lru_cache(maxsize=8)
def _source_index(snapshot: tuple[tuple[str, bytes | None], ...]) -> dict[str, Any]:
    """Cache by exact file contents, including same-size/same-mtime edits.

    Hashing and AST/JSON parsing use these same captured bytes, never a second
    filesystem read that could associate one version's proof with another's AST.
    """
    blobs = dict(snapshot)
    proof_files = [{"path": path, "expected_sha256": expected,
                    "actual_sha256": hashlib.sha256(blobs[path]).hexdigest() if blobs[path] is not None else None}
                   for path, expected in _REVIEWED_SHA256.items()]
    drift = [row["path"] for row in proof_files if row["expected_sha256"] != row["actual_sha256"]]
    result: dict[str, Any] = {"blocks": {}, "functions": {}, "rules": {}, "errors": [],
                              "source_drift": drift,
                              "source_proof": {"status": "mismatch" if drift else "verified",
                                               "reviewed_ref": _REVIEWED_REF, "files": proof_files}}
    try:
        if blobs[_EXECUTOR] is None:
            raise OSError("Executor source is unavailable")
        tree = ast.parse(blobs[_EXECUTOR].decode("utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                result["functions"][node.name] = f"{_EXECUTOR}:{node.lineno}"
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "BLOCKS":
                if not isinstance(node.value, ast.Dict):
                    continue
                for key, value in zip(node.value.keys, node.value.values):
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        result["blocks"][key.value] = {
                            "handler": value.id if isinstance(value, ast.Name) else ast.unparse(value),
                            "evidence": f"{_EXECUTOR}:{key.lineno}",
                        }
        if not result["blocks"]:
            result["errors"].append("No literal BLOCKS mapping was found in the executor source.")
    except (OSError, UnicodeError, SyntaxError) as exc:
        result["errors"].append(f"Cannot inspect executor source ({type(exc).__name__}).")
    try:
        rules = json.loads(blobs[_RULES]) if blobs[_RULES] is not None else None
        if isinstance(rules, dict):
            result["rules"] = rules
    except (ValueError, UnicodeError):
        # The proof guard below already prevents any positive inference.
        pass
    return result


def _integer(value: Any, minimum: int | None = None) -> bool:
    return type(value) is int and (minimum is None or value >= minimum)


def _formula_problem(value: Any) -> str | None:
    if isinstance(value, (str, type(None))) and value in _FORMULAS:
        return None
    # Named ability modifiers in the executor resolve to key_mod; contextual
    # formulas and partial text parsing require more proof than their spelling.
    return f"Formula {value!r} needs contextual or textual proof; it is outside the exact amount subset."


def _amount_problem(effect: dict[str, Any]) -> str | None:
    for key in ("formula",):
        problem = _formula_problem(effect.get(key))
        if problem:
            return problem
    if not _integer(effect.get("flat") or 0, 0):
        return "The flat amount is not a nonnegative literal integer."
    spec = effect.get("dice")
    if isinstance(spec, str):
        match = re.fullmatch(r"(\d+|PB)d(\d+)", spec, re.I)
        if not match:
            return "The dice string is outside the exact NdS/PBdS subset."
        spec = {"count": int(match[1]) if match[1].isdigit() else None,
                "count_formula": "pb" if not match[1].isdigit() else None, "sides": int(match[2])}
    if spec is not None:
        if not isinstance(spec, dict):
            return "Dice must be a dictionary or an exact NdS/PBdS string."
        if set(spec) - {"count", "count_formula", "sides", "bonus", "bonus_formula"}:
            return "The dice object contains an unreviewed field."
        count = spec.get("count")
        if count is None:
            if spec.get("count_formula") not in {"pb", "cl"}:
                return "The dice count has no supported literal or actor-number formula."
        elif not _integer(count, 0):
            return "The dice count is not a nonnegative integer."
        if count is not None and spec.get("count_formula"):
            return "A literal count shadows a second count formula."
        if not _integer(spec.get("sides"), 0) or (count != 0 and spec["sides"] < 2):
            return "The dice sides do not describe a supported roll."
        if not _integer(spec.get("bonus") or 0):
            return "The dice bonus is not an integer."
        problem = _formula_problem(spec.get("bonus_formula"))
        if problem:
            return problem
    for key, width in (("dice_by_cl", 4), ("flat_by_cl", 3)):
        table = effect.get(key)
        if not table:
            continue
        if key == "flat_by_cl" and effect.get("type") != "temp_hp":
            return "Only temp_hp consumes flat_by_cl; this effect does not."
        if not isinstance(table, list):
            return f"{key} is not a list."
        prior = 0
        for row in table:
            if not isinstance(row, (list, tuple)) or len(row) != width or not all(_integer(v, 0) for v in row):
                return f"{key} contains a malformed range."
            if row[0] < 1 or row[0] > row[1] or row[0] <= prior:
                return f"{key} has invalid or overlapping CL intervals."
            if width == 4 and (row[2] < 1 or row[3] < 2):
                return "The CL damage/healing dice do not describe a positive roll."
            prior = row[1]
        if key == "dice_by_cl" and spec is None:
            return "CL dice have no base amount outside the listed intervals."
    if spec is None and not effect.get("flat") and effect.get("formula") in (None, "none", "") and not effect.get("flat_by_cl"):
        return "No nonzero literal, dice, or supported formula amount is represented."
    return None


def _clock_kinds(rules: dict[str, Any]) -> set[str]:
    """Every duration kind the inspected rules give a clock to, shared by both duration readers.

    The engine's own expiry names, the turn vocabulary an effect, a mark, or an ability shares,
    the counted round kinds, and the explicit scene kinds the round clock resolves all end
    something. A kind in none of them states no deadline.
    """
    known = {"instant", "until_removed", "until_end_of_turn", "end_of_turn", "this_attack"}
    known.update((rules.get("durations") or {}).keys())
    known.update((rules.get("duration_turns") or {}).keys())
    rounds = rules.get("duration_rounds") or {}
    known.update(k for k, v in rounds.items() if type(v) is int and v >= 1)
    known.update(k for k in (rounds.get("lasts_the_fight") or ()) if isinstance(k, str))
    return known


def _mark_clocks(rules: dict[str, Any]) -> set[str]:
    """The kinds ``block_mark`` can turn into a real deadline, which is not the effect set.

    ``block_mark`` resolves one duration kind at a time and falls through to ``UNTIL_REMOVED`` for
    anything else, so a kind that only the effect reader understands -- "instant", the bare turn
    words, or a table key that carries no name -- would leave the mark for the rest of the fight.
    Concentration belongs here: ``block_mark`` ends the mark on ``CONCENTRATION_END`` itself.
    """
    durations = rules.get("durations") or {}
    rounds = rules.get("duration_rounds") or {}
    return ({kind for kind, name in durations.items() if name}
            | set(rules.get("duration_turns") or {})
            | {kind for kind, unit in rounds.items() if type(unit) is int and unit >= 1}
            | {kind for kind in (rounds.get("lasts_the_fight") or ()) if isinstance(kind, str)}
            | {"until_removed", "concentration"})


def _mark_duration_problem(duration: Any, rules: dict[str, Any]) -> str | None:
    """Whether ``block_mark`` honours this mark duration, judged only on the mark's own object.

    A mark never inherits its ability's duration: ``block_mark`` reads ``effect["duration"]["kind"]``
    and nothing else, and an absent duration is the until-removed default, or the deadline the
    mark's own rule states in ``rules.mark_durations``. Substituting another duration here would
    credit the mark with a deadline the engine never gives it.

    For the same reason a ``concentration`` flag is judged against that one kind, never on its own:
    only the kind ``concentration`` makes the executor end the mark on ``CONCENTRATION_END``, so a
    true flag beside any other kind states a lifecycle nothing reads, and a flag that contradicts
    the kind it names is unresolved rather than honoured.
    """
    if duration is None or duration == "":
        return None
    if not isinstance(duration, dict):
        return "block_mark reads a mark's duration as an object; a plain string has no kind to read."
    if set(duration) - {"kind", "amount", "concentration", "text"}:
        return "The duration contains an unreviewed field."
    if duration.get("amount") is not None and not _integer(duration["amount"], 1):
        return "The duration count is not a positive integer."
    kind = duration.get("kind") or "until_removed"
    if kind not in _mark_clocks(rules):
        return (f"block_mark gives a mark of duration {kind!r} no deadline: it falls through to until removed, "
                "so how long the mark lasts is not proved.")
    if "concentration" in duration and type(duration["concentration"]) is not bool:
        return ("The duration's concentration flag is not true or false, and block_mark reads only the "
                "duration kind, so what the flag claims about this mark is not proved.")
    if duration.get("concentration") and kind != "concentration":
        return (f"block_mark never reads this mark's concentration flag: only the duration kind 'concentration' "
                f"ends a mark with its bearer's Concentration, so this {kind!r} mark keeps that kind's deadline "
                "instead and outlives losing Concentration.")
    if kind == "concentration" and duration.get("concentration") is False:
        return ("block_mark honours the duration kind 'concentration' and ends this mark with its bearer's "
                "Concentration, while the same duration records concentration false; the engine resolves the "
                "kind and ignores the flag, so the record contradicts itself.")
    return None


def _duration_problem(effect: dict[str, Any], rules: dict[str, Any], mechanic: dict[str, Any]) -> str | None:
    if effect.get("expires_on"):
        return "Explicit expiry tokens require a separately reviewed runtime clock."
    duration = effect.get("duration")
    if effect.get("type") == "mark":
        return _mark_duration_problem(duration, rules)
    if duration in (None, "", "instant"):
        duration = mechanic.get("duration") or {"kind": "instant"}
    if isinstance(duration, str):
        kind = duration
    elif isinstance(duration, dict):
        if set(duration) - {"kind", "amount", "concentration", "text"}:
            return "The duration contains an unreviewed field."
        if duration.get("concentration") or duration.get("kind") == "concentration":
            return "Concentration requires its compiler and lifecycle route."
        if duration.get("amount") is not None and not _integer(duration["amount"], 1):
            return "The duration count is not a positive integer."
        kind = duration.get("kind") or "instant"
    else:
        return "The duration is malformed."
    if kind not in _clock_kinds(rules):
        return f"Duration {kind!r} has no demonstrated clock in the inspected rules."
    return None


def _fields_problem(effect: dict[str, Any], allowed: set[str]) -> str | None:
    extras = []
    for key, value in effect.items():
        if key in _METADATA or key in allowed:
            continue
        if key in _NEUTRAL and any(value == neutral for neutral in _NEUTRAL[key]):
            continue
        # Empty branch fields are harmless parser placeholders.
        if key in _BRANCHES and value in (None, []):
            continue
        extras.append(key)
    return "Unreviewed or unconsumed effect field(s): " + ", ".join(sorted(extras)) if extras else None


def _plugin_refs(plugin_index: Any, kind: str) -> list[str]:
    effects = (plugin_index.get("effects", {}) if isinstance(plugin_index, dict)
               else getattr(plugin_index, "effects", {})) or {}
    rows = effects.get(kind, []) if isinstance(effects, dict) else []
    if isinstance(rows, dict):
        rows = [rows]
    return sorted({ref for row in rows if isinstance(row, dict)
                   for ref in row.get("evidence", []) if isinstance(ref, str)})


def analyze_effects(effects: Any, *, repo_root: Path, route: str = "action",
                    mechanic: dict[str, Any] | None = None, plugin_index: Any = None) -> dict[str, Any]:
    """Report exact effect paths without importing or running the combat system.

    STRUCTURAL records certify delivery syntax, not a state-changing effect.
    Descendants of an unproved container remain UNKNOWN: a supported child cannot
    make its unhandled parent executable. Remaining GM lines are owned by the
    caller, which must also prove entry-point compilation and target/cost rules.
    """
    root = Path(repo_root).resolve()
    source = _source_index(tuple((path, _read_bytes(root / path)) for path in _REVIEWED_SHA256))
    mechanic = mechanic or {}
    records: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    def refs(*names: str) -> list[str]:
        return list(dict.fromkeys(source["functions"].get(n, f"{_EXECUTOR}:1") for n in names))

    def emit(path: str, kind: str, status: str, reason: str, evidence: list[str], code: str | None = None) -> None:
        record = {"path": path, "kind": kind, "status": status, "reason": reason, "evidence": evidence}
        records.append(record)
        if status in {"UNKNOWN", "MANUAL"}:
            issues.append({"code": code or f"effect_{status.lower()}", **record})

    def decide(effect: dict[str, Any], parent: dict[str, Any] | None, branch: str) -> tuple[str, str, list[str], str]:
        kind = str(effect.get("type") or "<missing>")
        block = source["blocks"].get(kind)
        registered_refs = _plugin_refs(plugin_index, kind)
        evidence = ([block["evidence"]] if block else registered_refs) or refs("_run_effects_in_chain")
        if source["errors"]:
            return "UNKNOWN", "; ".join(source["errors"]), evidence, "executor_source_unavailable"
        if source["source_drift"]:
            # Registry observations remain useful on drift, but cannot establish
            # that the old handler or fallback still has its reviewed meaning.
            if not block and kind != "rider":
                return "UNKNOWN", "No inspected core binding proves this kind, and the reviewed source snapshot has changed.", evidence, "extension_or_unknown_kind"
            changed = ", ".join(source["source_drift"])
            return ("UNKNOWN", f"Positive validators are pinned to {_REVIEWED_REF}; changed or missing source requires review: {changed}.",
                    list(dict.fromkeys([*evidence, *(f"{path}:1" for path in source["source_drift"])])), "reviewed_source_drift")
        if effect.get("deferred"):
            return ("UNKNOWN", "Deferred effects need an admitted registration/watch or compiler rewrite; ordinary dispatch skips them.",
                    refs("_run_effects_in_chain", "_register_on_hit", "_register_watch"), "deferred_route_unproven")
        if kind == "rider" and not block and not registered_refs:
            return "MANUAL", "An explicit rider is narrated through the fallback, not resolved mechanically.", refs("block_rider", "_run_effects_in_chain"), "explicit_rider"
        if kind in _CONTEXT_ONLY:
            return "UNKNOWN", "This kind requires a specific reaction/checkpoint or extension reader; its registration alone is not execution proof.", evidence, "context_only_effect"
        if not block:
            reason = ("An extension registers this kind, but its parameter semantics and admitting route are unproved."
                      if registered_refs else "No core handler proves this kind; an unregistered kind falls back to a GM rider.")
            return "UNKNOWN", reason, evidence, "extension_or_unknown_kind"
        handler = block["handler"]
        if kind in _EXPECTED_HANDLERS and handler != _EXPECTED_HANDLERS[kind]:
            return "UNKNOWN", "The current BLOCKS binding differs from the reviewed core handler.", evidence, "handler_binding_changed"
        if not handler.startswith("lambda"):
            evidence = list(dict.fromkeys([*evidence, *refs(handler)]))
        if kind == "half_damage":
            if parent and parent.get("type") == "save" and branch == "on_success" and any(
                    isinstance(row, dict) and row.get("type") == "damage" for row in parent.get("on_fail") or []):
                problem = _fields_problem(effect, set())
                if not problem:
                    return "STRUCTURAL", "A direct save-success marker halves the same save's direct failure damage rows.", refs("_save_each", "_half_save_damage"), "save_half_marker"
            return "UNKNOWN", "half_damage has no standalone effect; only a matching save-success or reaction reduction path consumes it.", refs("block_half_damage", "_half_save_damage"), "unbound_half_damage"
        scope = effect.get("applies_to")
        if scope is not None and scope not in _SCOPES:
            return "UNKNOWN", f"Recipient scope {scope!r} is outside the reviewed recipient subset.", refs("_declared_subjects"), "recipient_scope_unproven"
        if "exclude_self" in effect and type(effect["exclude_self"]) is not bool:
            return "UNKNOWN", "exclude_self is not a boolean.", refs("_declared_subjects"), "malformed_effect_field"
        shared = {"applies_to", "exclude_self", "duration"}
        amount = {"flat", "formula", "dice", "dice_by_cl"}
        problem: str | None = None
        structural = False
        instantaneous = {"damage", "extra_damage", "healing", "temp_hp", "attack", "save", "if_marked", "if_not_marked"}
        if kind in instantaneous and effect.get("duration") is not None:
            duration = effect["duration"]
            neutral_duration = duration in ("", "instant") or (
                isinstance(duration, dict) and duration.get("kind") in (None, "instant")
                and set(duration) <= {"kind", "amount", "concentration", "text"}
                and not duration.get("amount") and not duration.get("concentration") and not duration.get("text"))
            if not neutral_duration:
                return "UNKNOWN", "This handler does not itself consume a noninstant effect duration; expiry/repetition needs a separate lifecycle proof.", evidence, "instant_effect_duration_unproven"
        if kind in {"damage", "extra_damage", "healing", "temp_hp"}:
            if effect.get("weapon_damage"):
                why = ("weapon_damage reads the compiled weapon's damage types and ignores this row's damage_types override."
                       if effect.get("damage_types") else "weapon_damage needs proof of the compiler-selected weapon profile.")
                return "UNKNOWN", why, refs("_damage_roll", "_block_attack_in_chain", "damage_choices"), "weapon_damage_override" if effect.get("damage_types") else "weapon_profile_unproven"
            allowed = shared | amount
            # The first damage child is special: an attack converts a flat-only
            # damage row to weapon dice plus that amount, even for cultivation.
            if kind == "damage" and parent and parent.get("type") == "attack" and branch == "on_hit":
                first_damage = next((e for e in parent.get("on_hit") or []
                                     if isinstance(e, dict) and e.get("type") == "damage"), None)
                dice = effect.get("dice")
                if first_damage is effect and not effect.get("dice_by_cl") and not (
                        isinstance(dice, str) and re.fullmatch(r"(?:[1-9]\d*|PB)d(?:[2-9]|[1-9]\d+)", dice, re.I)
                        or isinstance(dice, dict) and (_integer(dice.get("count"), 1) or dice.get("count_formula") in {"pb", "cl"})
                        and _integer(dice.get("sides"), 2)):
                    return "UNKNOWN", "The first flat-only attack damage row adds fallback weapon dice; its exact primary damage is unproved.", refs("_block_attack_in_chain"), "attack_flat_damage_fallback"
            if kind in {"damage", "extra_damage"}:
                allowed |= {"damage_types", "weapon_damage"}
                types = effect.get("damage_types")
                if not isinstance(types, list) or len(types) != 1 or not isinstance(types[0], str) or types[0].lower() not in _DAMAGE_TYPES:
                    problem = "Exact damage support requires one known type; absent, combined or choice types need separate proof."
            if kind == "temp_hp":
                allowed |= {"flat_by_cl", "cap_at_missing_hp"}
                if "cap_at_missing_hp" in effect and type(effect["cap_at_missing_hp"]) is not bool:
                    problem = "cap_at_missing_hp is not a boolean."
            problem = problem or _amount_problem(effect) or _fields_problem(effect, allowed)
        elif kind == "mark":
            allowed = shared | {"mark"}
            if not isinstance(effect.get("mark"), str) or not effect["mark"].strip():
                problem = "A mark requires one nonempty literal name."
            problem = problem or _fields_problem(effect, allowed)
        elif kind in {"condition", "remove_condition"}:
            allowed = shared | {"condition"}
            name = effect.get("condition")
            if not isinstance(name, str) or name.lower() not in (source["rules"].get("conditions") or {}):
                problem = "The condition has no entry in the inspected rules table."
            problem = problem or _fields_problem(effect, allowed)
        elif kind in {"speed", "ac_bonus", "remaining_movement"}:
            allowed = shared | {"flat", "amount"}
            if kind == "speed":
                allowed |= {"halved", "becomes"}
            if kind == "remaining_movement":
                # Its separate set/multiply vocabulary is intentionally unproved.
                return "UNKNOWN", "Remaining movement needs its set/multiply semantics, not the Speed validator.", evidence, "unreviewed_core_form"
            values = [effect[k] for k in ("flat", "amount") if effect.get(k) is not None]
            if not all(_integer(v) for v in values):
                problem = "The stat amount is not a literal integer."
            elif len(values) == 2 and values[0] != values[1]:
                problem = "Conflicting amount and flat fields cannot both be consumed."
            elif kind == "speed" and effect.get("becomes") is not None:
                if not _integer(effect["becomes"], 0) or effect.get("halved") or any(values):
                    problem = "Speed set/half/add modes conflict or have malformed values."
            elif kind == "speed" and effect.get("halved"):
                if effect["halved"] is not True or any(values):
                    problem = "Speed halving is malformed or shadows an additive amount."
            elif not any(values):
                problem = "No nonzero stat change is represented."
            problem = problem or _fields_problem(effect, allowed)
        elif kind in {"resistance", "immunity", "vulnerability", "suppress_resistance"}:
            allowed = shared | {"damage_types"}
            types = effect.get("damage_types")
            if not isinstance(types, list) or not types or any(not isinstance(v, str) or v.lower() not in _DAMAGE_TYPES for v in types):
                problem = "Damage defenses require explicit known damage types."
            problem = problem or _fields_problem(effect, allowed)
        elif kind == "save":
            structural = True
            allowed = shared | {"ability", "on_fail", "on_success"}
            ability = effect.get("ability")
            if not isinstance(ability, str) or any(a not in {"STR", "DEX", "CON", "INT", "WIS", "CHA"} for a in ability.upper().split("_OR_")):
                problem = "The saving throw does not name a supported ability."
            elif not (effect.get("on_fail") or effect.get("on_success")):
                problem = "An empty save has no demonstrated mechanical consequence."
            problem = problem or _fields_problem(effect, allowed)
        elif kind == "attack":
            structural = True
            allowed = shared | {"attack_kind", "count", "on_hit", "on_miss", "no_damage", "reach_ft", "range_ft"}
            if not _integer(effect.get("count", 1), 1):
                problem = "Attack count is not a positive literal integer."
            if any(not _integer(effect[k], 1) for k in ("reach_ft", "range_ft") if effect.get(k) is not None):
                problem = "Attack reach/range is not a positive literal integer."
            if effect.get("attack_kind") not in {"cultivation", "cultivation_melee", "cultivation_ranged"}:
                problem = "Weapon/unarmed attack compilation and damage require a selected profile."
            damage = next((e for e in effect.get("on_hit") or [] if isinstance(e, dict) and e.get("type") == "damage"), None)
            if damage is None and not (effect.get("on_hit") or effect.get("on_miss")):
                problem = "This attack has no explicit mechanical consequence."
            problem = problem or _fields_problem(effect, allowed)
        elif kind in {"if_marked", "if_not_marked"}:
            structural = True
            allowed = shared | {"mark", "effects"}
            names = effect.get("mark")
            names = names if isinstance(names, list) else [names]
            if not names or any(not isinstance(n, str) or not n.strip() for n in names) or not effect.get("effects"):
                problem = "A mark gate needs named marks and a nonempty effects branch."
            problem = problem or _fields_problem(effect, allowed)
        elif kind in {"gain_resource", "spend_resource"}:
            return "UNKNOWN", "Resource effects require compiler resolution and an actually held recipient resource; raw effect type is insufficient.", evidence, "resource_binding_unproven"
        elif kind in {"zone", "summon", "command_summons"}:
            return "UNKNOWN", "This handler needs a compiled zone/summon specification and a matching lifecycle route.", evidence, "compiled_spec_unproven"
        else:
            return "UNKNOWN", "Core registration exists, but this effect's parameter semantics are outside the audited subset.", evidence, "unreviewed_core_form"
        if not problem and kind not in instantaneous:
            problem = _duration_problem(effect, source["rules"], mechanic)
        if problem:
            return "UNKNOWN", problem, evidence, "effect_parameters_unproven"
        return ("STRUCTURAL" if structural else "SUPPORTED", "The inspected core path consumes this validated effect form.", evidence, "core_form_supported")

    def visit(rows: Any, path: str, parent: dict[str, Any] | None = None, branch: str = "",
              blocked: str | None = None) -> None:
        if rows is None:
            return
        if not isinstance(rows, list):
            emit(path, "<malformed>", "UNKNOWN", "An effect branch is not a list.", refs("_run_effects_in_chain"), "malformed_effect_tree")
            return
        for i, effect in enumerate(rows):
            here = f"{path}[{i}]"
            if not isinstance(effect, dict):
                unproved = blocked or ("The reviewed source snapshot is unavailable or changed; fallback behavior is unproved."
                                       if source["errors"] or source["source_drift"] else None)
                emit(here, "<non_object>", "MANUAL" if not unproved else "UNKNOWN",
                     "Non-object effects become GM narration." if not unproved else unproved,
                     refs("_run_effects_in_chain"), "non_object_effect")
                continue
            kind = str(effect.get("type") or "<missing>")
            if blocked:
                status, reason, evidence, code = "UNKNOWN", blocked, refs("_run_effects_in_chain"), "parent_route_unproven"
            else:
                status, reason, evidence, code = decide(effect, parent, branch)
            emit(here, kind, status, reason, evidence, code)
            allowed = {"save": {"on_fail", "on_success"}, "attack": {"on_hit", "on_miss"},
                       "if_marked": {"effects"}, "if_not_marked": {"effects"}}.get(kind, set())
            for key in _BRANCHES:
                if effect.get(key) is None:
                    continue
                child_blocked = None if status == "STRUCTURAL" and key in allowed else f"The parent at {here} does not prove delivery of this {key} branch."
                visit(effect[key], f"{here}.{key}", effect, key, child_blocked)
            if effect.get("options"):
                options = effect["options"]
                if isinstance(options, list):
                    for j, option in enumerate(options):
                        if isinstance(option, dict):
                            visit(option.get("effects"), f"{here}.options[{j}].effects", effect, "options",
                                  f"The parent at {here} does not prove this extension menu's option delivery.")
                else:
                    emit(f"{here}.options", "<malformed>", "UNKNOWN", "Nested options are not a list.", refs("_run_effects_in_chain"), "malformed_effect_tree")

    blocked = None
    if route not in {"action", "bonus_action", "reaction", "generic_reaction"}:
        blocked = f"Raw {route!r} effects require a separately proved compiler/attachment entry point."
    visit(effects, "effects", blocked=blocked)
    counts = {status: sum(row["status"] == status for row in records) for status in ("SUPPORTED", "MANUAL", "UNKNOWN", "STRUCTURAL")}
    return {"records": records, "issues": issues,
            "supported_count": counts["SUPPORTED"], "manual_count": counts["MANUAL"],
            "unknown_count": counts["UNKNOWN"], "structural_count": counts["STRUCTURAL"],
            "all_supported": bool(counts["SUPPORTED"]) and not counts["MANUAL"] and not counts["UNKNOWN"]}
