"""Bind printed references once, before applying display labels.

Shared by the typed builder and the compiler's explicit authoring-input API.
Production authority carries these links: gameplay selects owned IDs, never
searches labels. Unlinked caller-authored records are normalized at admission,
before compiling actions (including the public apply_modifiers authoring API).
An explicit target_links contract is never reinterpreted from a name.
"""
from __future__ import annotations

import copy
import re


def normalized(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower().replace("’", "'")).strip()


def bind_modifier(modifier, mechanics, home):
    if not modifier or "target_links" in modifier:
        return modifier
    links = []
    # A short printed reference can designate a choose-one option ("Mist
    # Basin" -> "Basin: Mist"), not only a whole parent record.
    candidates = {rid: (row.get("name"), row.get("sphere_id")) for rid, row in mechanics.items()}
    candidates.update({f"{rid}#opt{index}": (f"{row.get('name')}: {option.get('label') or ''}", row.get("sphere_id"))
                       for rid, row in mechanics.items() for index, option in enumerate(row.get("options") or [])})
    for target in modifier.get("targets") or []:
        exact = [rid for rid, row in mechanics.items() if normalized(row.get("name")) == normalized(target)]
        words = set(normalized(target).split())
        near = [rid for rid, (name, sphere) in candidates.items() if home and sphere == home
                and words and words <= set(normalized(name).split())]
        links.append({"ids": exact, "fallback_ids": near})
    result = {**modifier, "target_links": links}
    if modifier.get("options"):
        result["options"] = [{**option, **({"modifier": {**option["modifier"], "target_links": bind_modifier(
            {**modifier, **option["modifier"], "options": None}, mechanics, home)["target_links"]}}
            if option.get("modifier") else {})} for option in modifier["options"]]
    return result


def source_evidence(mechanic):
    """Source clauses shared by reference binding and compiler terrain reading."""
    def walk(effects):
        for effect in effects or []:
            if isinstance(effect, dict):
                yield effect
                for branch in ("on_hit", "on_miss", "on_fail", "on_success", "effects"):
                    yield from walk(effect.get(branch) or [])
    parts = [str((mechanic.get("activation") or {}).get("trigger") or "")]
    description = mechanic.get("description")
    parts += list(description) if isinstance(description, list) else [str(description or "")]
    parts += [str(row) for row in mechanic.get("riders") or []]
    parts += [str(effect.get("evidence") or "") for tree in [mechanic, *(mechanic.get("options") or [])]
              for effect in walk(tree.get("effects") or [])]
    return " ".join(part for part in parts if part)


def project_authority(authority, texts, names):
    """Export verified source rules with ID links and current presentation.

    Exact-input converters/reviewers consume the unprojected source authority;
    the builder and its full-output property guard share this final projection.
    No source digest or original executable field is filtered out.
    """
    mechanics = bind_records(authority["mechanics"], texts)
    for rid, name in names.items():
        if rid in mechanics:
            mechanics[rid]["name"] = name
    return {**authority, "mechanics": mechanics}


def bind_records(mechanics, texts=None):
    """Return independent records with typed modifier/area/Hide relationships.

    Printed headings/tags are source evidence, not the editable naming table.
    Same-Sphere preference and the unique-owned short-reference rule are retained
    as ID selection policies, so existing acquired sets keep their capabilities.
    """
    result = copy.deepcopy(mechanics)
    texts = texts or {}
    families = {rid: row for rid, row in mechanics.items()
                if row.get("area") or (row.get("activation") or {}).get("economy") in ("action", "bonus_action")}
    family_patterns = {fid: re.compile(rf"\b{re.escape(str(row.get('name') or ''))}\b", re.I)
                       for fid, row in families.items()}
    for rid, row in result.items():
        if row.get("modifier"):
            row["modifier"] = bind_modifier(row["modifier"], mechanics, row.get("sphere_id"))
        if "record_links" in row:
            continue
        text = texts.get(rid) or ""
        head = text.split("\n", 1)[0]
        match = re.match(r"#+\s*(.+?)\s+-\s+(.+)$", head.strip())
        tags = [tag.strip().lower() for tag in match.group(2).split(",")] if match else []
        trigger = " ".join([str((row.get("activation") or {}).get("trigger") or ""),
                            *([str(line) for line in row.get("description") or []]
                              if isinstance(row.get("description"), list) else [])])
        evidence = source_evidence(row)
        areas = {}
        if (row.get("activation") or {}).get("economy") not in ("action", "bonus_action", "reaction"):
            pair = re.search(r"Apply (.+?) in addition to one other (.+?) talent", text, re.I)
            pair_any = re.search(r"Apply two (.+?) talents to one (.+?) instead of one", text, re.I)
            for fid, family in families.items():
                name = str(family.get("name") or "")
                if not name or fid == rid:
                    continue
                pattern = family_patterns[fid]
                tagged = name.lower() in tags or f"{name.lower()} talent" in tags
                triggered = bool(pattern.search(trigger))
                mentioned = bool(pattern.search(evidence))
                policy = {}
                if pair and pair.group(2).strip().lower() == name.lower():
                    partners = [key for key, candidate in mechanics.items()
                                if str(candidate.get("name") or "").lower() == pair.group(1).strip().lower()]
                    policy = {"pair_ids": partners}
                elif pair_any and pair_any.group(1).strip().lower() == name.lower():
                    printed = re.search(r"\bCost:\s*\+?(\d+)\s*CP\b", text, re.I)
                    policy = {"pair_any": True, "printed_cp": int(printed.group(1)) if printed else 0}
                if tagged or triggered or mentioned or policy:
                    areas[fid] = {"tagged": tagged, "triggered": triggered, "mentioned": mentioned, **policy}
        hide = re.search(r"inside an area of your ([\w' -]+?), it may take the Hide action", text, re.I)
        links = {"areas": areas}
        if hide:
            candidates = [key for key, family in families.items()
                          if normalized(family.get("name")) == normalized(hide.group(1))]
            if len(candidates) != 1:
                raise ValueError(f"Ambiguous Hide area reference in {rid}: use explicit record_links")
            links["hide_area_id"] = candidates[0]
        row["record_links"] = links
    return result
