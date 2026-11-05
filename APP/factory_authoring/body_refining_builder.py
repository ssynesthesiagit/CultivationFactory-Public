"""Reusable Body Refining authority builder.

Used by the authoring CLI and public corpus-backed pin regressions. Callers
supply the source extract explicitly; no private Markdown is a module input.
The CLI alone owns the default extract path and writes generated artifacts.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re

APP = Path(__file__).resolve().parents[1]
RIDERS = APP / "authority/body_refining/variant_riders.json"
OUTPUT = APP / "authority/Tianxia_Body_Refining_Variants_R1.json"
PATH_ACCESS = APP / "authority/Tianxia_Sphere_Path_Access_R1.json"
BODY = "tianxia.path.body_refining"
DESIGN = "designed from the printed description (owner 2026-10-22)"
DESIGNS = {
    "Ice": ("Cold-Marrow Body", "Cold organs, still blood and preservation act within your own body."),
    "Life": ("Vitality-Refining Body", "Regeneration, vitality refinement and medicine-body techniques affect yourself."),
    "Unmaking": ("Black-Vein Body", "Black-vein tempering and self-damaging palms act through your body or a held weapon."),
    "Yang": ("Inner-Furnace Body", "An inner furnace refines your own vitality and body-bound blood weapons."),
    "Yin": ("Still-Marrow Body", "Cold marrow, stillness and preservation refine your own hidden vitality."),
}


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=1) + "\n").encode()


def sections(text):
    for match in re.finditer(r"<!-- (variant|insight|gloss) (.+?) -->\n(.*?)\n<!-- end -->", text, re.S):
        yield match[1], json.loads(match[2]), match[3]


def clauses(body):
    # Same paragraph/bullet census as the specification inventory.
    out = []
    for block in re.split(r"\n[ \t]*\n", body):
        block = block.strip()
        if not block or block.startswith("#"):
            continue
        if re.match(r"^[-•]\s", block):
            out.extend(re.sub(r"^[-•]\s+", "", b.strip())
                       for b in re.split(r"\n(?=[-•]\s)", block))
        else:
            out.append(block.replace("\n", " "))
    return out


def verdict(text):
    lower = text.casefold()
    if re.match(r"requires?\b|learning .*through", lower):
        return "access", "compiled"
    if re.search(r"cannot|does not (?:grant|permit)|must (?:not|use)|still require", lower):
        return "restriction", "restriction"
    if "constitution" in lower and ("key ability" in lower or "for " in lower or "and stamina" in lower):
        # A paragraph with additional effects remains a hook, not falsely "done".
        return "key_ability", "hook" if "once per" in lower else "compiled"
    if re.search(r"stamina (?:instead|in place|for .*talents|as .*resource)", lower):
        return "payment", "compiled"
    # Only out-of-combat fiction is a table clause. Combat riders remain hook work for S2.
    return "rider", "hook"


def key_rule(text):
    match = re.search(r"(?:use|uses?) (?:Strength or |Dexterity or )?Constitution (?:as|for|and Stamina|instead of Intelligence)", text, re.I)
    if not match:
        return None
    key_sentence = text[match.start():].split(".", 1)[0]
    scope = "save_dc_only" if re.search(r"Use Constitution for (?:Dual Wielding|Piercing Needle|Thread DCs)|use Dexterity or Constitution|where a talent requires a save DC|for saving throw DCs", key_sentence, re.I) else "sphere_talents"
    rule = {"ability": "CON", "scope": scope, "save_dc": True,
            "alternatives": ["STR"] if "Strength or Constitution" in text else ["DEX"] if "Dexterity or Constitution" in text else [],
            "if_higher": bool(re.search(r"if higher|when higher", key_sentence, re.I))}
    if re.search(r"higher than Strength", key_sentence, re.I):
        rule["higher_than"] = "STR"
    # Bound the compiler substitution to printed talent families, not the whole sphere.
    if "for Hand talents" in text:
        rule["tags"] = ["Hand"]
    elif "for Breath talents" in text:
        rule["tags"] = ["Breath"]
    elif "for Cadence, Phrase" in text:
        rule["tags"] = ["Cadence", "Phrase", "Battle Cadence"]
    elif "for Pratfall talents" in text:
        rule["tags"] = ["Pratfall"]
    elif "for Self-Marionette Method and Substitute" in text:
        rule["names"] = ["Self-Marionette Method"]
        rule["tags"] = ["Substitute"]
    elif "Blacksmith key ability for:" in text:
        rule["names"] = ["Hammer the Mark", "Quench in Breath", "Hammer Rebuke"]
    elif "for skin inscriptions and worn talismans only" in text:
        rule["expression"] = "worn_or_skin"
    elif "while you are adjacent" in text:
        rule["expression"] = "frontline"
    elif "Basin you occupy" in text:
        rule["expression"] = "body_vessel_or_occupied_basin"
    elif "chosen Sect Role" in text or "Gathering key ability" in text:
        rule["expression"] = "physical_work"
    return rule


def rider_data(path=RIDERS):
    """The checked-in per-clause verdicts and structured riders; data, not inference."""
    return json.loads(path.read_text())


def apply_riders(variants, riders):
    """Stamp each variant's final verdicts and its flattened automated riders.

    Fails loudly if the data names a clause the print does not have, or if a
    printed clause is not hook-classified by the parser yet has no verdict. That
    is what keeps a printed combat clause from drifting back to "later".
    """
    by_variant = riders["variants"]
    unknown = set(by_variant) - set(variants)
    if unknown:
        raise ValueError(f"riders name unknown variants: {sorted(unknown)}")
    for key, row in variants.items():
        verdicts = by_variant.get(key) or {}
        indexes = {str(clause["index"]) for clause in row["clauses"]}
        stray = set(verdicts) - indexes
        if stray:
            raise ValueError(f"riders name missing clauses for {key}: {sorted(stray)}")
        automated = []
        for clause in row["clauses"]:
            verdict = verdicts.get(str(clause["index"]))
            if clause["automation"] == "compiled":
                # Key ability, payment and access are already typed fields; a
                # verdict row must not turn one of them into prose.
                continue
            if verdict is None:
                if clause["automation"] in ("hook", "restriction"):
                    # A parser-labelled restriction is a printed prohibition; give
                    # it the honest default rather than inventing a benefit.
                    if clause["automation"] == "restriction":
                        clause["reason"] = ("printed prohibition; where it defers to a talent, item, Insight or GM "
                                           "permission the engine cannot enumerate it")
                        continue
                    raise ValueError(f"unclassified printed clause {key} #{clause['index']}")
                continue
            clause["automation"] = verdict["automation"]
            if verdict.get("reason"):
                clause["reason"] = verdict["reason"]
            elif verdict["automation"] in ("table", "flavor"):
                raise ValueError(f"{verdict['automation']} clause {key} #{clause['index']} needs a reason")
            for rider in verdict.get("riders") or []:
                automated.append({**rider, "clause": clause["index"]})
        row["riders"] = automated
    hooks = [(key, clause["index"]) for key, row in variants.items() for clause in row["clauses"]
             if clause["automation"] == "hook"]
    if hooks:
        raise ValueError(f"clauses left as deferred hook work: {hooks[:5]}")
    return variants


def build(source, rider_path=RIDERS):
    text = source.read_text()
    provenance = json.loads(re.search(r"<!-- provenance (.+) -->", text)[1])
    provenance["excerpts_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    riders = rider_data(rider_path)
    provenance["riders_sha256"] = hashlib.sha256(rider_path.read_bytes()).hexdigest()
    entries = list(sections(text))
    insights = {meta["title"]: (meta, body) for kind, meta, body in entries if kind == "insight"}
    variants, upgrades = {}, {}
    printed_clauses = 0
    for kind, meta, body in entries:
        if kind != "variant":
            continue
        sid = meta["sphere_id"]
        name = meta["variant_name"]
        key = next((k for k, v in variants.items() if v["sphere_id"] == sid), None)
        cs = clauses(body)
        printed_clauses += len(cs)
        if key is None:
            key = f"tianxia.brvariant.{sid.split('.')[-1]}.{slug(name)}"
            variants[key] = {
                "sphere_id": sid, "sphere_name": meta["sphere_name"], "variant_name": name,
                "picker_label": "", "source_lines": [], "printed_names": [],
                "access": {"kind": "insight_upgrade" if meta["insight_id"] else "variant_is_access",
                           "insight_id": meta["insight_id"], "typed_gate": meta["typed_gate"],
                           "default_minimum_cl": 0, "printed_minimum_cl": None},
                "key_ability": None, "payment": None, "restrictions": [], "clauses": [],
            }
        row = variants[key]
        row["source_lines"].append(meta["source_lines"])
        if name not in row["printed_names"]:
            row["printed_names"].append(name)
        row["variant_name"] = " / ".join(row["printed_names"])
        row["picker_label"] = f'{row["sphere_name"]} — Body Refining: {row["variant_name"]}'
        rule = key_rule("\n".join(cs))
        if rule:
            row["key_ability"] = rule
        payment = [c for c in cs if re.search(r"(?:Stamina.*(?:CP|resource|talents)|Constitution and Stamina)", c, re.I)]
        if payment:
            row["payment"] = {"replace": "cp", "with": "resource:core.stamina",
                              "scope": "sphere_talents", "printed_clauses": payment}
        for c in cs:
            ckind, automation = verdict(c)
            row["clauses"].append({"index": len(row["clauses"]), "kind": ckind,
                                   "automation": automation, "text": c, "source_lines": meta["source_lines"]})
            if automation == "restriction":
                row["restrictions"].append(c)
        row["access"]["printed_prerequisites"] = [c["text"] for c in row["clauses"]
                                                      if re.match(r"Requires?|If you have|Learning .* through", c["text"], re.I)]
        if not meta["insight_id"] and re.search(r"(?:learn.*through|requires?|unless).*scripture", "\n".join(cs), re.I):
            row["access"]["kind"] = "named_manual"
        if meta["insight_id"]:
            imeta, ibody = insights[meta["insight_title"]]
            prereq = next((l for l in ibody.splitlines() if l.startswith("Prerequisite:")), "")
            cl_match = re.search(r"CL (\d+)\+", prereq)
            row["access"]["printed_minimum_cl"] = int(cl_match[1]) if cl_match else 1
            row["access"]["insight_source_lines"] = imeta["source_lines"]
            if meta["typed_gate"] == "no_record":
                iid = meta["insight_id"]
                predicates = [{"kind": "path", "target_id": BODY, "display_name": "Body Refining"}]
                if "sphere" in prereq or meta["sphere_name"] == "Monkey Style":
                    predicates.append({"kind": "sphere", "target_id": sid, "display_name": meta["sphere_name"]})
                # Full printed record retained as evidence; the owner ruling supplies its new upgrade meaning.
                description = (f'Upgrade {meta["sphere_name"]} to its normal version instead of '
                               f'{row["variant_name"]}. Use the normal sphere key ability and options.\n\n'
                               f'Owner ruling: 2026-10-22. Printed record:\n{ibody.strip()}')
                upgrades[iid] = {
                    "canonical_insight_id": iid, "record_id": iid, "display_name": meta["insight_title"],
                    "selectable": True, "minimum_cl": row["access"]["printed_minimum_cl"],
                    "owning_canonical_sphere_ids": [sid], "owning_canonical_sphere_id": sid,
                    "insight_authority_type": "Sphere",
                    "insight_group": {"type": "Sphere", "facet_ids": ["sphere:" + sid],
                                      "hierarchy_path": ["Sphere"], "leaf_label": "Sphere"},
                    "prerequisites": predicates,
                    "raw_source_record": {"record_id": iid, "selectable": True, "repeatable": "No",
                                          "full_rules_text": description},
                    "source_provenance": {**provenance, "source_lines": imeta["source_lines"],
                                          "printed_prerequisite": prereq},
                }
    for kind, meta, body in entries:
        if kind != "gloss":
            continue
        name, purpose = DESIGNS[meta["sphere_name"]]
        sid = meta["sphere_id"]
        key = f"tianxia.brvariant.{sid.split('.')[-1]}.{slug(name)}"
        texts = [purpose, "Use Constitution as your key ability for this sphere.",
                 "You may spend Stamina instead of CP for this sphere's body-bound talents.",
                 "This version acts only on yourself or through touch, natural weapons or held weapons; it cannot project Qi beyond your body."]
        variants[key] = {
            "sphere_id": sid, "sphere_name": meta["sphere_name"], "variant_name": name,
            "picker_label": f'{meta["sphere_name"]} — Body Refining: {name}',
            "design_status": DESIGN, "printed_gloss": body.strip(), "source_lines": [meta["source_lines"]],
            "access": {"kind": "variant_is_access", "insight_id": None, "typed_gate": "no_insight",
                       "default_minimum_cl": 0, "printed_minimum_cl": None},
            "key_ability": {"ability": "CON", "scope": "sphere_talents", "save_dc": True, "alternatives": [], "if_higher": False},
            "payment": {"replace": "cp", "with": "resource:core.stamina", "scope": "body_bound"},
            "restrictions": [texts[-1]],
            "clauses": [{"index": i, "kind": verdict(t)[0], "automation": verdict(t)[1], "text": t,
                         "source_lines": meta["source_lines"]} for i, t in enumerate(texts)],
        }
    # CAT3 carries the printed talent-family tags; typed mechanics do not.
    # Resolve the scoped source IDs at build time, never fuzzy-match names in combat.
    catalogue = json.loads((APP / "catalog_authority/cat3/generated/catalog_authority.v1.json").read_text())
    for row in variants.values():
        rule = row["key_ability"]
        if not rule or not (rule.get("tags") or rule.get("names")):
            continue
        ids = set()
        for talent in catalogue["talents"]:
            if talent["owning_canonical_sphere_id"] != row["sphere_id"]:
                continue
            if set(rule.get("tags") or []).intersection(talent.get("tags") or []) or talent["display_name"] in (rule.get("names") or []):
                ids.add(talent["canonical_talent_id"])
                ids.update(talent.get("migration_aliases") or [])
        rule["source_ids"] = sorted(ids)
    apply_riders(variants, riders)
    census = Counter({kind: 0 for kind in ("compiled", "restriction", "table", "flavor")})
    census.update(c["automation"] for row in variants.values() for c in row["clauses"])
    printed = [meta for kind, meta, _ in entries if kind == "variant"]
    printed_spheres = {meta["sphere_id"] for meta in printed}
    return {"schema": "TianxiaBodyRefiningVariants.v1", "compiler_version": "BRVAR-P1-R1.0",
            "source": provenance, "counts": {"variants": len(printed), "spheres": len(printed_spheres), "clauses": printed_clauses,
            "duplicate_headings": len(printed) - len(printed_spheres), "canonical_versions": len(variants), "designed_versions": len(DESIGNS),
            "automated_riders": sum(len(row["riders"]) for row in variants.values())},
            "census": {**dict(sorted(census.items())), "unclassified": 0},
            "variants": dict(sorted(variants.items())), "authored_upgrade_insights": dict(sorted(upgrades.items()))}


def update_access(data, path=PATH_ACCESS):
    access = json.loads(path.read_text())
    for key, row in data["variants"].items():
        entry = access["spheres"][row["sphere_id"]]
        entry["conditional"].setdefault(BODY, f'Body Refining through {row["variant_name"]} (default version; owner 2026-10-22)')
        entry["evidence"]["body_refining_variant"] = {
            "path": data["source"]["path"], "markdown_sha256": data["source"]["markdown_sha256"],
            "lines": row["source_lines"], "variant_id": key,
            "heading": f'Body Refining - {row["variant_name"]}',
            **({"design_status": DESIGN, "gloss": row["printed_gloss"]} if row.get("design_status") else {}),
        }
    path.write_bytes(encoded(access))

