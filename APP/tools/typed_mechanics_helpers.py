"""Pure and source-loading helpers shared by typed-mechanics tests and builder.

This module deliberately excludes the builder's private model-proposal inputs.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from factory_authoring.insight_sources import catalog_insight_sources

APP = Path(__file__).resolve().parents[1]


CATALOG = APP / "catalog_authority/cat3/generated/catalog_authority.v1.json"


REVIEWED_FINAL = APP / "authority/typed_mechanics/reviewed_final.json"


BASE_ABILITY_SOURCES = APP / "authority/typed_mechanics/base_ability_sources.json"  # docket 2026-09-28: Dreamscape, Fragrance


OWNER_TEXT_EDITS = APP / "authority/typed_mechanics/owner_text_edits.json"  # owner 2026-09-29: printed lines struck


_FINAL_FIELDS = ("effects", "options", "modifier", "activation", "riders", "range", "area", "cost", "use_limit", "duration", "target", "after", "min_cp_cost",
                 "min_cl", "weapon_delivery")


_OPTIONAL_SEAMS = ("weapon_delivery", "min_cl")


def _source(provenance: dict, text: str) -> dict:
    return {
        "path": provenance.get("source_path"),
        "line": provenance.get("source_line"),
        "file_sha256": provenance.get("source_file_sha256"),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def _coverage(effects: list, riders: list) -> str:
    return "FULL" if effects and not riders else "CORE_WITH_RIDERS" if effects else "RIDERS_ONLY"


_DELIVERY_TYPES = {"attack", "save", "half_damage", "spend_resource"}


def split_reaction_menu(mechanic: dict, row: dict, text: str) -> None:
    """A reaction's printed "Choose one" menu as one option each (owner 2026-09-26, step 14): the reaction row
    runs its common effects plus the one option picked (combat/factory_compiler.py _generic_reaction) instead of
    every option at once. The options came up short of the earlier typing in about half the reactions (Flowing
    Response lost its AC bonus), so an earlier-typed top-level effect no option accounts for is kept as common,
    and a reaction whose unaccounted effect sits inside an effect the options also cover is left whole."""
    import copy

    from factory_authoring.typed_mechanics import apply_cl_scaling
    from factory_authoring.typed_structure import (_all, _substantive, build_options, drop_cost_restatement, fix_misread_effects,
                                                   graft_options, has_choose_one_menu, mandatory_core, option_area)

    if not has_choose_one_menu(text):
        return
    common, options = build_options(row.get("common_effects") or [], row["options"], text)
    if len(options) < 2:
        return
    prior = mechanic["effects"]
    core = mandatory_core(prior, options)
    if _substantive(core):
        common, options = core, graft_options(core, options, text)
    kinds = lambda effects: {r.get("type") for r in _all(effects) if isinstance(r, dict)} - _DELIVERY_TYPES  # noqa: E731
    covered = kinds(common).union(*(kinds(option["effects"]) for option in options))
    carried = [r for r in prior if isinstance(r, dict) and kinds([r]) - covered]
    if any(kinds([r]) & covered for r in carried):
        return
    # The earlier typing sometimes lists one printed line twice (Staff of One's "Gain +1 AC").
    carried = [r for index, r in enumerate(carried)
               if not r.get("evidence") or (r.get("type"), r.get("evidence")) not in {(c.get("type"), c.get("evidence")) for c in carried[:index]}]
    tidy = lambda effects: fix_misread_effects(drop_cost_restatement(effects, mechanic.get("cost")), adds_to_technique=False)  # noqa: E731
    # As for actions, each option is the whole tree that runs when it is picked (build_options/graft_options put
    # the common part in it); the kept earlier-typed effects go into every option too.
    mechanic["effects"] = tidy([*common, *copy.deepcopy(carried)])
    mechanic["options"] = [{**option, "effects": tidy([*option["effects"], *copy.deepcopy(carried)])} for option in options]
    for tree in [mechanic, *mechanic["options"]]:  # the printed CL table again (audit F4)
        apply_cl_scaling(tree, text)
    for option in mechanic["options"]:
        area = option_area(option, mechanic)
        if area:
            option["area"] = area
    mechanic["coverage"] = _coverage(mechanic["effects"] or [1], mechanic["riders"])


def split_branch_menu_record(mechanic: dict, row: dict, text: str) -> None:
    """A "Choose one" menu printed inside one save or attack outcome ("Failed Save: Choose one: ...") as one option each (fight
    audit 2026-09-28; Court of the Ninth Grave applied Speed -10 and "cannot take Reactions" together). ``has_choose_one_menu``
    leaves that menu to nobody, so no split above ever ran on it and the typing put every bullet in the one outcome. Each option is
    the whole tree that runs when it is picked, as for the top-level menus, with only its own bullet in the menu's place
    (factory_authoring/typed_structure.py split_branch_menu). Left as typed: a record the options proposals or the earlier typing
    give nothing to hang the choice on."""
    from factory_authoring.typed_mechanics import apply_cl_scaling
    from factory_authoring.typed_structure import (branch_menu, drop_cost_restatement, fix_misread_effects, has_choose_one_menu,
                                                   mark_deferred, option_area, split_branch_menu)

    menu = branch_menu(text)
    if menu is None or has_choose_one_menu(text):
        return
    split = split_branch_menu(mechanic["effects"], row, text, menu, mechanic.get("riders"))
    if split is None:
        return
    usable_now = mechanic["activation"].get("economy") in ("action", "bonus_action")
    tidy = lambda effects: fix_misread_effects((mark_deferred if usable_now else list)(  # noqa: E731
        drop_cost_restatement(effects, mechanic.get("cost"))), adds_to_technique=False)
    mechanic["effects"] = tidy(split["effects"])
    mechanic["options"] = [{"label": option["label"], "effects": tidy(option["effects"]), "riders": option["riders"]} for option in split["options"]]
    mechanic["riders"] = split["riders"]
    for tree in [mechanic, *mechanic["options"]]:  # the printed CL table again (audit F4)
        apply_cl_scaling(tree, text)
    for option in mechanic["options"]:
        area = option_area(option, mechanic)
        if area:
            option["area"] = area
    mechanic["coverage"] = _coverage(mechanic["effects"] or [1], mechanic["riders"])


def sources() -> list[dict]:
    """Every typed mechanic's printed text and identity, gathered one way for the builder,
    the MiMo tool and the review tool: Sphere talents and base abilities (canonical
    catalog), Cultivation Insights (the selected canonical source occurrence),
    Path features (path index sections) and Subpath / Tradition features (printed
    line ranges of the bundled compendia, checked against their file hashes)."""
    import zipfile

    catalog = json.loads(CATALOG.read_bytes())
    rows: list[dict] = []
    for row in catalog["talents"]:
        text = row.get("full_exact_source_text")
        if text:
            rows.append({"id": row["canonical_talent_id"], "name": row["display_name"], "kind": "talent", "text": text,
                         "sphere_id": row.get("owning_canonical_sphere_id"), "source": _source(row.get("source_provenance") or {}, text)})
    for row in catalog["sphere_base_ability_authority"]:
        text = row.get("effect") or ""
        rows.append({"id": row["candidate_record_id"], "name": row["display_name"], "kind": "base_ability", "text": text,
                     "sphere_id": row.get("mapped_canonical_sphere_id"), "source": _source(row.get("source_matrix_provenance") or {}, text)})
    rows.extend(catalog_insight_sources(catalog))
    # Base abilities the catalog read from the wrong heading or left out (docket 2026-09-28: Dreamscape, the Flower sphere's
    # Fragrance): their printed text from the compendium, with its path, line and hash.
    fixes = json.loads(BASE_ABILITY_SOURCES.read_text(encoding="utf-8")).get("abilities") or {} if BASE_ABILITY_SOURCES.is_file() else {}
    for record_id, fix in fixes.items():
        text = fix["text"]
        fixed = {"id": record_id, "name": fix["name"], "kind": "base_ability", "text": text, "sphere_id": fix.get("sphere_id"),
                 "source": {**_source({"source_path": fix["source"]["path"], "source_line": fix["source"]["line"],
                                       "source_file_sha256": fix["source"]["file_sha256"]}, text)},
                 **({"granted_with": list(fix["granted_with"])} if fix.get("granted_with") else {})}
        rows = [row for row in rows if row["id"] != record_id] + [fixed]
    for index_path in sorted((APP / "non_sphere_authority/authority").glob("*.path_index.p2a.json")):
        index = json.loads(index_path.read_text(encoding="utf-8"))
        for feature in index.get("features") or []:
            text = "\n".join(section.get("source_markdown") or "" for section in feature.get("source_sections") or [])
            if not text.strip():
                continue
            section = (feature.get("source_sections") or [{}])[0]
            rows.append({"id": feature["canonical_id"], "name": feature["display_name"], "kind": "path_feature", "text": text,
                         "sphere_id": None, "path_id": index.get("canonical_id"),
                         "source": {"path": (index.get("source") or {}).get("path") or index_path.name, "line": section.get("source_line_start"),
                                    "file_sha256": (index.get("source") or {}).get("sha256"), "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}})
    bundle = zipfile.ZipFile(APP / "BundledContent/Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip")
    files: dict[str, list[str] | None] = {}
    index = json.loads((APP / "non_sphere_authority/authority/Tianxia_Subpath_Tradition_Index_Master_P2B.json").read_text(encoding="utf-8"))
    for entry in index["entries"]:
        for feature in entry.get("feature_progression") or []:
            source = feature.get("source") or {}
            member = "HF05ZVK_R1H_Phase2I_HF2/" + str(source.get("factory_source_path") or "")
            if member not in files:
                try:
                    raw = bundle.read(member)
                    files[member] = raw.decode("utf-8").splitlines() if hashlib.sha256(raw).hexdigest() == source.get("source_file_sha256") else None
                except KeyError:
                    files[member] = None
            lines = files[member]
            if not lines or not source.get("line_start"):
                continue
            text = "\n".join(lines[int(source["line_start"]) - 1:int(source.get("line_end") or source["line_start"])])
            rows.append({"id": feature["canonical_id"], "name": feature["display_name"], "kind": "subpath_feature", "text": text,
                         "sphere_id": None, "subpath_id": entry.get("canonical_id"),
                         "source": {"path": source.get("factory_source_path"), "line": source.get("line_start"),
                                    "file_sha256": source.get("source_file_sha256"), "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}})
    # Optional owner-authored progressions share the builder's catalog source and
    # then pass through the same owner text edit/review pipeline as sealed rows.
    from non_sphere_authority.owner_subpaths import owner_feature_sources
    additions = owner_feature_sources(APP)
    if {row["id"] for row in rows} & {row["id"] for row in additions}:
        raise ValueError("Owner-authored Subpath feature collides with a sealed mechanic")
    rows.extend(additions)
    # Foundation features (owner 2026-09-25): the 30 playable Foundations' printed features,
    # by stage (non_sphere_authority/foundation_features.py reads the same verified catalog
    # records foundation_mechanics.py uses for initial/passive mechanics).
    from non_sphere_authority import foundation_features as ff

    for foundation_id, record, feature in ff.iter_all_features():
        text = "\n".join(f"**{key}:** {value}" for key, value in feature["fields"].items())
        text = f"#### {feature['name']}\n\n{text}\n"
        rows.append({"id": ff.feature_id(foundation_id, feature["name"]), "name": feature["name"], "kind": "foundation_feature",
                     "text": text, "sphere_id": None, "foundation_id": foundation_id, "stage": feature["stage"],
                     "source": {"path": "non_sphere_authority/authority/" + record["source"]["artifact"], "line": record["source"]["section_number"],
                                "file_sha256": record["source"]["artifact_sha256"], "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}})
    # The owner's own edits to printed text (factory_authoring/owner_text_edits.py): "remove" lines struck (owner 2026-09-29,
    # Meld: "remove that text"), then "replace" pairs (owner 2026-09-30, Qi Armor +3 -> +5). The sealed catalog keeps the old
    # wording until the next catalog release. A row with "replace" pairs keeps the text they were applied to (typing_text):
    # build() types that text and carries the typing onto the edited one.
    from factory_authoring.owner_text_edits import apply_edit, replacements

    edits = owner_text_edits()
    for row in rows:
        edit = edits.get(row["id"])
        if not edit:
            continue
        removed, text, problems = apply_edit(row["text"], edit)
        row["text"] = text
        row["source"] = {**row["source"], "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
        if text != removed:
            row["typing_text"], row["owner_replace"] = removed, replacements(edit)
            row["owner_retype"] = bool(edit.get("retype"))
        if problems:
            row["owner_edit_problems"] = problems
    return rows


def owner_text_edits() -> dict[str, dict]:
    return (json.loads(OWNER_TEXT_EDITS.read_text(encoding="utf-8")).get("records") or {}) if OWNER_TEXT_EDITS.is_file() else {}


def source_texts() -> dict[str, str]:
    return {row["id"]: row["text"] for row in sources()}


def load_finals() -> dict[str, dict]:
    """Every reviewed_final typing: reviewed_final.json, then one file per reviewer in reviewed_final.d/ (owner 2026-09-28)."""
    finals = json.loads(REVIEWED_FINAL.read_text(encoding="utf-8")).get("mechanics", {}) if REVIEWED_FINAL.is_file() else {}
    for extra in sorted((REVIEWED_FINAL.parent / "reviewed_final.d").glob("*.json")):
        for key, final in (json.loads(extra.read_text(encoding="utf-8")).get("mechanics") or {}).items():
            if key in finals:
                print(f"reviewed_final: {key} reviewed twice ({extra.name} wins)", file=sys.stderr)
            finals[key] = final
    return finals


def _typed_for_text(key: str, text_sha: str, finals: dict[str, dict]) -> bool:
    """Only a complete reviewed_final can replace carried typing for edited text.

    Proposals are unapproved and reviews/options passes replace only some fields.
    Selecting their new hash would exclude the earlier reviewed core, costs and
    modifier before carry runs. Keep typing the earlier text unless the final
    explicitly supplies every required override field (including None for absent
    fields). New optional delivery metadata does not invalidate older reviews.
    The final application in build() then owns the entire replacement.
    """
    final = finals.get(key) or {}
    # Weapon delivery and min_cl are default-inert optional seams. Reviews made
    # before a field was added remain complete; absence means no override.
    # Keep exact-text admission and every previously required field unchanged.
    return final.get("text_sha256") == text_sha and all(
        field in final for field in _FINAL_FIELDS if field not in _OPTIONAL_SEAMS)

