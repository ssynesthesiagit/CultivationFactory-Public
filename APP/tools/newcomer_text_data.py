"""Build presentation-only resource references from owner rules, never mechanics.

The UI uses these references for named counters. Each paragraph keeps its ability
name: mentioning a rule does not grant that ability. No proposal is used as rule
authority; resource proposals supply search terms only, printed text supplies help.
Regenerate newcomer-data.js by importing build_data(); tests check exact equality.
"""
from pathlib import Path
import json
import re
import sys

APP = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(APP))

from combat.player_text import clean  # noqa: E402


def plain(text):
    """The one player-facing cleaner, shared with the in-fight hovers.

    This builder and combat/status_text used to carry two cleaners for the same
    printed records, and only this one removed the internal factory fields, so
    the in-fight button hover printed "Split Review Decision: ..." to the player.
    """
    lines = []
    for line in clean(text).splitlines():
        if line.strip().startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r"[:\-\s]+", cell) for cell in cells):
                continue
            line = cells[0] + ": " + "; ".join(cells[1:])
        lines.append(line)
    return "\n".join(lines)


def build_data():
    rules = json.loads((APP / "authority/typed_mechanics/rules_text.json").read_text())
    authority = json.loads((APP / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    display_names = {key: row.get("name") for key, row in authority["mechanics"].items()}
    names = {"Qi", "Stamina", "Resonance", "Martial Focus"}
    foundation_source = "non_sphere_authority/authority/Foundation_Runtime_Authority_v0_4C.json"
    foundation_document = json.loads((APP / foundation_source).read_text())
    foundation_rules = {}
    for group in ("orthodox", "theoretical_chakra"):
        for row in foundation_document.get(group, []):
            match = re.match(r"(.+?)\s+\d+\s*/\s*\d+", str(row.get("foundation_resource", "")))
            text = (row.get("semantic_surfaces") or {}).get("resource")
            if match and isinstance(text, str) and text.strip():
                name = match[1].strip()
                names.add(name)
                foundation_rules.setdefault(name, []).append({"source": foundation_source + "#" + row["foundation_id"],
                    "name": name, "text": plain(text)})
    for line in (APP / "authority/typed_mechanics/resource_definitions.jsonl").read_text().splitlines():
        names.update(row["name"] for row in json.loads(line).get("resources", []))
    result = {}
    for name in sorted(names):
        pattern = re.compile(r"(?<!\w)" + re.escape(name).replace("'", "['’]") + r"(?!\w)", re.I)
        references = []
        for key, text in sorted(rules.items()):
            if not pattern.search(text):
                continue
            # Include the whole printed rule, preserving prerequisites, limits and
            # counterplay. Extracting only a 'regain' sentence loses its trigger.
            references.append({"source": key, "name": plain(display_names.get(key) or text.splitlines()[0]), "text": plain(text)})
        # A counter definition is useful on every surface. Ability-specific
        # references are already supplied by sheet buttons; do not ship the
        # whole catalogue for a generic word such as 'Mark' or 'CP'.
        exact = [row for row in references if row["name"].casefold() == name.casefold()]
        examples = sorted(references, key=lambda row: (name.casefold() not in row["name"].casefold(), len(row["text"]), row["source"]))[:2]
        if name in foundation_rules:
            spending = [row for row in references if re.search(r"^Cost:.*" + pattern.pattern, row["text"], re.I | re.M)]
            spending.sort(key=lambda row: (len(row["text"]), row["source"]))
            for definition in foundation_rules[name]:
                if spending:
                    definition["text"] += "\n\nPrinted spending examples (require the named feature):\n\n" + "\n\n".join(row["text"] for row in spending[:2])
        result[name] = foundation_rules.get(name) or exact or (examples if name not in {"CP", "Mark", "Trace", "Charge", "Bearing"} else [])
    for path, name in (("body_refining", "Stamina"), ("qi_cultivation", "Qi"), ("spirit_awakening", "Resonance")):
        source = f"non_sphere_authority/authority/{path}.path_index.p2a.json"
        document = json.loads((APP / source).read_text())
        def find(value):
            if isinstance(value, dict):
                text = value.get("source_markdown", "")
                if re.match(r"^#+ " + name + r"\s*\n", text):
                    return text
                for item in value.values():
                    found = find(item)
                    if found:
                        return found
            elif isinstance(value, list):
                for item in value:
                    found = find(item)
                    if found:
                        return found
            return None
        text = find(document)
        if not text:
            raise ValueError(f"Missing printed resource rule: {name}")
        result[name] = [{"source": source, "name": name, "text": plain(text)}]
    return result


def build_mark_durations():
    """Presentation copy of the compiled mark defaults used by block_mark."""
    document = json.loads((APP / "combat/rules/typed_conditions.json").read_text())
    return {key: value for key, value in document["mark_durations"].items() if not key.startswith("_")}


def build_condition_readings():
    """Presentation copy of every condition's plain reading, for a surface that cannot ask the API.

    The area reader answers while a player hovers, so it cannot fetch /api/tabletop/conditions. Its
    copy is generated from combat.condition_text.zone_readings() -- the same readings and the same
    engine mechanics the sheet's condition hover shows -- so the two surfaces cannot disagree.
    Regenerate with `python -m tools.newcomer_text_data`; tests check exact equality."""
    from combat.condition_text import zone_readings
    return zone_readings()


def build_gm_resolves():
    """The line the area reader shows for a condition nothing else can explain. From the same place
    as the readings, so the two languages cannot say it differently."""
    from combat.condition_text import GM_FALLBACK
    return GM_FALLBACK


def write_resource_text_data(path: Path | None = None) -> Path:
    """Rebuild the sheet's resource help from build_data(), alongside zone help."""
    target = path or (APP / "static/tabletop/newcomer-data.js")
    target.write_text(
        "// Generated from owner printed rules by tools/newcomer_text_data.py.\n"
        "export const RESOURCE_RULES = {};\nObject.assign(RESOURCE_RULES, "
        + json.dumps(build_data(), indent=2, ensure_ascii=False) + ");\n", encoding="utf-8")
    return target


def write_zone_text_data(path: Path | None = None) -> Path:
    """Write static/tabletop/zone-text-data.js. Presentation data only; never hand-edited."""
    target = path or (APP / "static/tabletop/zone-text-data.js")
    parts = [("MARK_DURATIONS", build_mark_durations()), ("CONDITION_READINGS", build_condition_readings()),
             ("GM_RESOLVES", build_gm_resolves())]
    body = [f"export const {name} = {json.dumps(value, indent=2, ensure_ascii=False)};" for name, value in parts]
    target.write_text(
        "// Generated presentation data by tools/newcomer_text_data.py (build_mark_durations and\n"
        "// build_condition_readings). From combat/rules/typed_conditions.json and\n"
        "// combat/condition_text.py; never mechanics of its own. Regenerate, never hand-edit.\n"
        + "\n\n".join(body) + "\n", encoding="utf-8")
    return target


if __name__ == "__main__":  # pragma: no cover - the regeneration path
    import sys
    sys.path.insert(0, str(APP))
    print(write_resource_text_data())
    print(write_zone_text_data())
