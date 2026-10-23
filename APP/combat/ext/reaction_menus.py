"""Expose each compiled mode to the normal manual reaction eligibility checks.

Auto/AI use the compiled preset. Manual mode rows are transient: costs, limits,
effects and source receipts still belong to the original ability.
"""
from copy import deepcopy
from . import hook


def _mode_description(effects):
    """Describe selected compiled evidence, retaining save branches and GM riders."""
    lines, manual = [], False
    def visit(value, prefix=""):
        nonlocal manual
        if isinstance(value, list):
            for child in value:
                visit(child, prefix)
        elif isinstance(value, dict):
            manual |= value.get("type") in ("rider", "recorded_modifier")
            evidence = value.get("evidence")
            if evidence:
                line = prefix + str(evidence)
                if line not in lines:
                    lines.append(line)
            for key, child in value.items():
                if isinstance(child, (list, dict)):
                    visit(child, {"on_fail": "On a failed save: ", "on_success": "On a successful save: "}.get(key, prefix))
    visit(effects)
    return "\n".join(lines), manual


@hook("reaction_rows")
def manual_modes(engine, actor_id, block, rows):
    if actor_id not in (getattr(engine, "typed_ask_reactors", ()) or ()):
        return None
    expanded = []
    for row in rows:
        modes = row.get("reaction_modes") or []
        if not row.get("ask") or not modes:
            expanded.append(row)
            continue
        for mode in modes:
            # ``base_name`` keeps the ability's own name: a follow-up printed as "when you activate X"
            # (combat/typed_reactions.py own_ability) matches it, not the mode's label.
            expanded.append({**row, "effects": deepcopy(mode["effects"]), "option": mode["index"],
                "name": f"{row['name']} — {mode['label']}", "base_name": row["name"],
                "consent_source_id": f"reaction:typed.{row['feature_id']}:mode:{mode['index']}"})
    return expanded


@hook("decision_text")
def mode_text(engine, context, rules):
    source = str(context.get("reaction_source_id") or "")
    base, separator, index = source.removeprefix("reaction:typed.").rpartition(":mode:")
    if not separator or not index.isdigit():
        return None
    for row in (getattr(engine, "typed_reaction_rows", {}) or {}).get(context.get("reactor_id"), []):
        if row.get("feature_id") != base:
            continue
        mode = next((m for m in row.get("reaction_modes") or [] if m["index"] == int(index)), None)
        if mode:
            summary, manual = _mode_description(mode["effects"])
            return {"feature_id": base, "name": f"{row['name']} — {mode['label']}",
                    "selected_mode": mode["label"],
                    "summary": summary or f"{mode['label']}: no automatic effect is applied by the table.",
                    "table_note": ("Some effects in this mode require the GM; the table does not apply them automatically."
                                   if manual else "This choice runs the selected mode.")}
    return None
