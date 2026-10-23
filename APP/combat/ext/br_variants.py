"""S1: source-backed Body Refining ownership and per-sphere talent key abilities.

Uses existing compile_passives, compile_action and compile_reaction seams.
Ownership markers are sealed in the bundle, so named-sphere DC queries survive
a table commit/reload. No global sheet statistic, payment, rider or option is
rewritten here. Conditional expressions are retained as S2 hook work rather
than granting their benefits unconditionally.
"""
from __future__ import annotations

from . import hook
from .passive_rows import row_of
from factory_authoring import body_refining_variants as authority

BLOCK = "br_variant"


def _row(source, info):
    mechanic = (info.get("mechanics") or {}).get(source) or info.get("mechanic") or {}
    sid = mechanic.get("sphere_id")
    if not sid or mechanic.get("kind") not in ("talent", "base_ability"):
        return None
    return authority.selected(sid, info.get("owner_sheet") or {}, require_owned=True)


def _applies(rule, mechanic, source=None):
    if not rule or rule.get("expression"):
        return False
    tags, names = set(rule.get("tags") or []), set(rule.get("names") or [])
    if tags or names:
        return (source in (rule.get("source_ids") or [])
                or bool(tags.intersection(mechanic.get("tags") or [])) or mechanic.get("name") in names)
    return True


def _baseline(numbers, rule, sheet):
    if (rule or {}).get("higher_than"):
        from ..table_advance import current_scores
        scores = current_scores(sheet or {})
        return (int(scores.get(rule["higher_than"], 10)) - 10) // 2
    return int(numbers.get("key_mod") or 0)


def _numbers(numbers, rule, sheet=None):
    con = int(numbers.get("con_mod") or 0)
    key = int(numbers.get("key_mod") or 0)
    if rule.get("if_higher") and con <= _baseline(numbers, rule, sheet):
        return None
    new = dict(numbers)
    new["save_dc"] = 8 + int(numbers.get("pb") or 2) + con
    if rule["scope"] != "save_dc_only":
        new["key_mod"] = con
        new["attack_bonus"] = int(numbers.get("attack_bonus") or 0) - key + con
    return new if new != numbers else None


@hook("compile_passives")
def seal_versions(passives, info):
    versions = authority.owned(info.get("owner_sheet") or {})
    if not versions:
        return passives
    return [*passives, *[{"feature_id": row["id"], "block": BLOCK, "kind": row["sphere_id"], "ownership_only": True,
                         "key_ability": row["key_ability"], "numbers": dict(info.get("numbers") or {}),
                         "key_baseline": _baseline(info.get("numbers") or {}, row["key_ability"], info.get("owner_sheet"))}
                        for row in versions]]


@hook("compile_action")
def talent_key(action, info):
    typed = (action.parameters or {}).get("typed") or {}
    source = typed.get("source")
    row = _row(source, info)
    if not row:
        return None
    mechanic = (info.get("mechanics") or {}).get(source) or {}
    rule = row["key_ability"]
    if not _applies(rule, mechanic, source):
        return None
    numbers = _numbers(dict(typed.get("numbers") or info.get("numbers") or {}), rule, info.get("owner_sheet"))
    if numbers is None:
        return None
    return action.model_copy(update={"parameters": {**action.parameters, "typed": {**typed, "numbers": numbers}}})


@hook("compile_reaction")
def reaction_key(row, info):
    version = _row(row.get("feature_id"), info)
    if not version or not _applies(version["key_ability"], info.get("mechanic") or {}, row.get("feature_id")):
        return None
    numbers = _numbers(dict(row.get("numbers") or info.get("numbers") or {}), version["key_ability"], info.get("owner_sheet"))
    return {**row, "numbers": numbers} if numbers is not None else None


@hook("named_save_dc")
def sphere_dc(engine, actor, sphere_id):
    """Only an owned, unconditional named-sphere rule can replace this DC."""
    row = row_of(engine, actor.entity_id, BLOCK, sphere_id)
    if row is None:
        return None
    rule = row.get("key_ability")
    if not _applies(rule, {}) or rule.get("tags") or rule.get("names"):
        return None
    numbers = row.get("numbers") or {}
    key = int(numbers.get("key_mod") or 0)
    con = int(numbers.get("con_mod") or 0)
    if rule.get("if_higher") and con <= int(row.get("key_baseline", key)):
        con = key
    return 8 + int(numbers.get("pb") or 2) + con
