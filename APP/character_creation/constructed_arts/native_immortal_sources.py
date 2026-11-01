"""Immortal Art sources shared by every Subpath of the three native Paths.

These adapters authenticate native P2A features separately from P2B Subpath
children. They grant no acquisition: callers must prove the locked Path and
its causal progression. Existing Subpath constructions retain their identities.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

from app.core import FoundryError, canonical_json, sha256_bytes, sha256_json
from .sources import published_section

NATIVE_COMMITMENT_KIND = "native_path_progression_commitment_v1"
_PREFIX = "tianxia.path."
# Pin the complete feature, including its source sections and dependencies.
# Updating an index identity alone must never silently change these mechanics.
_SPECS = {
    "body_refining.feature.stamina_guard": ("31e1bffb0eb521a977707f99649421e38505732937931f473dd49957a59f6acf", "temporary_hp_fortification", ("guard", "protect")),
    "body_refining.feature.iron_voice": ("c584cd5cf3caa083e0c6c9ad5bdd5a2cd408ca7cb891bfaeb807ccd7b87e33de", "speed_reduction", ("bind", "movement")),
    "qi_cultivation.feature.qi_armor": ("75f5de12783c3173ccda3e59b21db64b7407284f9f7e36149927c3ff79d4bb92", "temporary_hp_fortification", ("guard", "protect")),
    "qi_cultivation.feature.featherfall": ("375611c371e8f2673acde265795a22461ec18c4055624c5bad0c8b8ff712eb30", "temporary_hp_fortification", ("guard", "protect")),
    "spirit_awakening.feature.soul_gaze": ("0a2acb1b629de26fe5cd5fd83ada0089af483243b7f0dc836274b3d0adbba938", "detect_presence", ("detect", "diagnose", "identity")),
    "spirit_awakening.feature.domain_pressure": ("57bbf39ec7d7c8af35fd68703c0d52a86397c827d222942d113aba138b1cac30", "speed_reduction", ("bind", "movement", "spirit")),
}
NATIVE_SOURCE_IDS = tuple(_PREFIX + key for key in _SPECS)


def _invalid(message: str, **details: Any) -> FoundryError:
    return FoundryError("IMMORTAL_ART_NATIVE_SOURCE_INVALID", message, details=details, status_code=409)


def native_feature_hash(parent_id: str, parent_hash: str, feature: Mapping[str, Any]) -> str:
    if (not isinstance(parent_id, str) or not isinstance(parent_hash, str)
            or len(parent_hash) != 64 or any(c not in "0123456789abcdef" for c in parent_hash)
            or not isinstance(feature, Mapping)):
        raise _invalid("A native feature requires an exact parent commitment.")
    return sha256_json({"schema": NATIVE_COMMITMENT_KIND, "parent_record_id": parent_id,
                        "parent_record_hash": parent_hash, "feature": dict(feature)})


def native_placeholder_surface(source: Mapping[str, Any], action: Mapping[str, Any]) -> dict[str, Any]:
    """Exclude only byte-verified quotations from authored-placeholder checks.

    Soul Gaze expressly forbids learning an unknown feature's text. That is
    complete source language, not an unresolved action field. The entire native
    feature must match its pinned hash before either quotation is excluded.
    All authored mechanics still receive the ordinary placeholder check.
    """
    fid = source.get("record_id", "")
    spec = _SPECS.get(fid.removeprefix(_PREFIX))
    snapshot = (source.get("progression") or {}).get("feature_snapshot") or {}
    feature = snapshot.get("native_feature")
    if spec is None or not isinstance(feature, Mapping) or sha256_json(feature) != spec[0]:
        raise _invalid("The quoted native feature is not the pinned complete source.")
    quoted = feature["source_sections"][0]["source_markdown"]
    mechanics = action.get("source_mechanics") or {}
    procedure = action.get("normalized_procedure")
    if (source.get("published_text") != quoted or mechanics.get("published_section") != quoted
            or not isinstance(procedure, list) or len(procedure) != 1
            or procedure[0].strip() != quoted.strip()):
        raise _invalid("Native source quotations must retain the entire authenticated section.")
    result = deepcopy(dict(action))
    result["source_mechanics"].pop("published_section")
    result["normalized_procedure"] = []
    return result


def native_feature_snapshot(root_dir: Path, factory_root: Path | None, feature_id: str) -> dict[str, Any]:
    """Authenticate the index and original installed chapter, independently."""
    from factory_authoring.native_path_mechanics import native_path_binding

    spec = _SPECS.get(feature_id.removeprefix(_PREFIX))
    if spec is None:
        raise _invalid("No complete native source adapter is registered.", feature_id=feature_id)
    binding = native_path_binding(root_dir, feature_id)
    if not binding or binding["feature_sha256"] != spec[0]:
        raise _invalid("The native feature differs from the adapter's pinned authority.", feature_id=feature_id)
    index = json.loads((root_dir / binding["source"]["path"]).read_text())
    feature = next(row for row in index["features"] if row["canonical_id"] == feature_id)
    sections = feature.get("source_sections") or []
    grants = feature.get("granted_at_cl")
    if (len(sections) != 1 or not isinstance(grants, list) or len(grants) != 1
            or type(grants[0]) is not int
            or feature.get("effective_rules_text") != feature.get("source_rules_text")):
        raise _invalid("The adapter requires one complete, unmodified native source section.")
    section, original = sections[0], index["source"]
    # P2A stores the exact joined section, including its final blank line.
    text = section["source_markdown"]
    source = {
        "source_id": "source.native_path." + feature_id,
        "path": original["factory_path"], "factory_source_path": original["factory_path"],
        "anchor": f"line:{section['source_line_start']}",
        "source_hash": original["sha256"], "source_file_sha256": original["sha256"],
        "line_start": section["source_line_start"], "line_end": section["source_line_end"],
        "section_sha256": sha256_bytes(text.encode()),
    }
    if not text or published_section(factory_root, source) != text:
        raise _invalid("The installed chapter does not authenticate the complete native source section.", feature_id=feature_id)
    dependencies = []
    if binding["owner_path_id"] == "tianxia.path.spirit_awakening":
        chapter = (factory_root / original["factory_path"]).read_bytes()
        if sha256_bytes(chapter) != original["sha256"]:
            raise _invalid("The native dependency chapter has drifted.")
        dependency_text = "\n".join(chapter.decode().splitlines()[171:215])
        dependency_source = {**source, "anchor": "line:172", "line_start": 172, "line_end": 215,
                             "section_sha256": sha256_bytes(dependency_text.encode())}
        if published_section(factory_root, dependency_source) != dependency_text:
            raise _invalid("Native Mark and Pressure definitions are unavailable.")
        dependencies.append({"dependency_id": "native.spirit.resonance_marks_and_spiritual_pressure",
                             "source": dependency_source, "published_text": dependency_text})
    return {
        "canonical_id": feature_id, "display_name": feature["display_name"],
        "granted_at_cl": grants[0], "source_cl_basis": feature["source_cl_basis"],
        "source": source, "components": deepcopy(feature.get("components") or []),
        "native_authority": binding, "native_feature": feature, "dependencies": dependencies,
    }


def _action(feature: Mapping[str, Any], path_cl: int) -> dict[str, Any]:
    fid = feature["canonical_id"]
    short = fid.rsplit(".", 1)[1]
    text = feature["native_feature"]["source_sections"][0]["source_markdown"]
    path_kind = fid.split(".")[2]
    resource = {"body_refining": "Stamina", "qi_cultivation": "Qi", "spirit_awakening": "Resonance"}[path_kind]
    profiles = {
        "stamina_guard": dict(action_type="reaction", range="Self", target="You", duration="The triggering damage application", trigger="Damage is first applied to you, after its amount is determined and before Hit Points are reduced.", resource_cost=1,
            effect={"damage_reduction": "1d10", "refinement_choice": "Spend exactly 1 Stamina from the published up-to-PB range; this Art does not buy additional native reduction dice.", "damage_order": "Apply immunity, resistance, vulnerability and prior modifiers; subtract reduction; apply remaining damage to HP.", "riders": "Damage-dependent riders fail if damage is zero; hit-dependent and unconditional riders remain. The attack still hit."},
            limits=["Cannot reduce maximum HP loss, CP loss, willingly paid costs, irreducible damage or non-damage consequences."]),
        "iron_voice": dict(action_type="bonus action", range="30 feet", target="One creature that can hear you", duration="Until the end of your next turn", resource_cost=1,
            save_or_check="Constitution saving throw against the Body Refining save DC", dc_basis="8 + Proficiency Bonus + Constitution modifier",
            effect={"failed_save": "Frightened of you until the end of your next turn", "successful_save": "No native effect", "immunity": "A creature immune to Frightened automatically succeeds."},
            limits=["Blocked by total silence, inability to hear, total cover preventing sound, or explicit suppression of cultivation pressure or bodily sound.", "Shared language is not required."]),
        "qi_armor": dict(action_type="reaction", range="Self", target="You", duration="Until the start of your next turn", trigger="You are hit by a ranged attack roll, after learning it hit and before damage.", resource_cost=1 if path_cl >= 10 else 2,
            effect={"ac_bonus": 3, "triggering_attack": "Included; re-evaluate its hit against the increased AC", "cost_progression": "2 Qi, reduced to 1 Qi at owning Path CL10"},
            limits=["Only ranged attack rolls; not melee or melee reach attacks, saving throws, automatic damage, environmental damage or effects without attack rolls."]),
        "featherfall": dict(action_type="reaction", range="60 feet", target="One falling creature: you or a creature within range", duration="1 minute", trigger="You or a creature within 60 feet begins falling.", resource_cost=1,
            effect={"descent": "At most 60 feet per round", "falling_damage": "None while the effect lasts", "landing": "Land standing on a supporting surface", "refinement_choice": "One target from the published up-to-PB targets at 1 Qi each."},
            cleanup="Ends after 1 minute, or the target may end its effect at the start of its turn.", limits=["Does not grant flight or horizontal movement."]),
        "soul_gaze": dict(action_type="action", range="60 feet", target="One visible creature, or one creature Resonance Marked by you in range that is not behind total spiritual concealment", duration="Instantaneous information; concealed information retains the source's retry restriction", resource_cost=1,
            save_or_check="Cultivation Check against the protecting effect when protected information is contested", dc_basis="The protecting effect's DC",
            effect={"information": "Current and maximum HP; broad nature and Path; relative effective or Source CL; damage defenses; surface emotion; listed ordinary spiritual afflictions; broad category of one sustaining bond/link/anchor.", "concealment_failure": "Identify the concealed information category, not its contents; no retry until concealment changes, new evidence or a new scene."},
            limits=["No automatic protected Soul Anchor, complete Nature or Bond contract, Secret/divine identity, hidden phase, exact unspent CP, protected memories, unlearned feature text, or source-protected concealed effect."]),
        "domain_pressure": dict(action_type="action", range="Self", area=f"{60 if path_cl >= 17 else 30 if path_cl >= 11 else 15}-foot cone originating from you", target="Each creature of your choice in the cone", duration="Fear through end of your next turn; ordinary pressure through start of your next turn; Mark follows its source duration", resource_cost=2,
            save_or_check="Wisdom saving throw against the Spirit Awakening save DC", dc_basis="8 + Proficiency Bonus + Wisdom modifier",
            effect={"failed_save": "Frightened until end of your next turn and Resonance Marked by you", "successful_save": "One ordinary Spiritual Pressure of your choice until start of your next turn", "fear_immunity": "On a failed save, replace fear with two different ordinary pressures as one exceptional package; the Mark remains."},
            limits=["Not a full Domain; grants no ownership, Anchor, prison, anti-teleport effect or companion-command zone."]),
    }
    raw = profiles[short]
    return {
        "activation": raw["action_type"].title(), "trigger": "on activation", "trigger_frequency": "once per activation",
        "save_or_check": "none", "attack_roll": "none", "dc_basis": "none", "area": None,
        "success": "Resolve the complete published native procedure and its printed result bands.",
        "failure": "Apply the complete published native failure and immunity rules.",
        "success_by_5": "none", "failure_by_5": "none",
        "counterplay": "Preserve all source target, immunity, concealment and suppression restrictions.",
        "cleanup": "End the native effect at its printed duration; Factor layers track their own printed durations.",
        **raw, "resource_name": resource,
        "source_tags": sorted(_SPECS[fid.removeprefix(_PREFIX)][2]),
        "normalized_procedure": [text], "cross_references": [row["dependency_id"] for row in feature["dependencies"]],
        "source_mechanics": {"feature_id": fid, "published_section": text, "owning_path_cl": path_cl},
    }


def native_source_row(root_dir: Path, factory_root: Path | None, *, feature_id: str,
                      parent_record: Mapping[str, Any], owning_path_cl: int,
                      construction_cl: int) -> dict[str, Any]:
    feature = native_feature_snapshot(root_dir, factory_root, feature_id)
    pid = feature["native_authority"]["owner_path_id"]
    grant = feature["granted_at_cl"]
    if (parent_record.get("record_id") != pid or parent_record.get("content_type") != "path"
            or type(owning_path_cl) is not int or grant > owning_path_cl or grant > construction_cl):
        raise _invalid("The source must be attained by its exact acquired native Path.", feature_id=feature_id)
    authority = ((parent_record.get("compatibility") or {}).get("factory") or {}).get("stage2_authority") or {}
    grant_ids = (authority.get("progression_by_cl", {}).get(str(grant)) or {}).get("feature_record_ids") or []
    if feature_id not in grant_ids:
        raise _invalid("The locked Path progression does not grant this native feature.", feature_id=feature_id)
    return _source_from_feature(feature, parent_record["record_hash"], owning_path_cl)


def _source_from_feature(feature: Mapping[str, Any], parent_hash: str, path_cl: int) -> dict[str, Any]:
    fid = feature["canonical_id"]
    pid = feature["native_authority"]["owner_path_id"]
    child_hash = native_feature_hash(pid, parent_hash, feature)
    grant, source = feature["granted_at_cl"], feature["source"]
    spec = _SPECS[fid.removeprefix(_PREFIX)]
    progression = {"feature_record_id": fid, "parent_record_id": pid, "parent_record_hash": parent_hash,
        "owning_path_id": pid, "parent_path_id": pid, "granted_at_cl": grant,
        "source": deepcopy(source), "feature_snapshot": deepcopy(feature),
        "feature_record_hash_kind": NATIVE_COMMITMENT_KIND}
    action = _action(feature, path_cl)
    return {"record_id": fid, "record_hash": child_hash, "feature_record_hash_kind": NATIVE_COMMITMENT_KIND,
        "display_name": feature["display_name"], "content_type": "path_feature", "acquired": True,
        "acquired_at_cl": grant, "owning_path_id": pid, "path_id": pid,
        "source_package_id": pid, "source": {k: source[k] for k in ("source_id", "path", "anchor", "source_hash")},
        "source_tags": sorted(spec[2]), "supported_factor_ids": [spec[1]], "credible_bridges": [],
        "progression": progression, "action_surface": action, "published_text": action["source_mechanics"]["published_section"],
        "acquisition": {"kind": "native_path_feature", "parent_record_id": pid, "parent_record_hash": parent_hash,
            "feature_record_id": fid, "feature_record_hash": child_hash, "acquired_at_cl": grant},
        "factor_adapters": {spec[1]: {"source_record_id": fid, "source_record_hash": child_hash,
            "parent_record_id": pid, "parent_record_hash": parent_hash, "source_section_sha256": source["section_sha256"]}},
        "source_dependencies": deepcopy(feature["dependencies"])}


def validate_native_source(root_dir: Path, factory_root: Path | None, source: Mapping[str, Any], path_cl: int) -> None:
    """Re-derive mechanics as well as commitments; self-consistent edits fail."""
    from .immortal_art import _normalize_source

    feature = native_feature_snapshot(root_dir, factory_root, source.get("record_id", ""))
    progression = source.get("progression") or {}
    expected = _source_from_feature(feature, progression.get("parent_record_hash"), path_cl)
    normalized = _normalize_source(expected, 0, path_kind=feature["native_authority"]["owner_path_id"].split(".")[-1],
                                   target_cl=path_cl, owning_path_cl=path_cl)
    if canonical_json(source) != canonical_json(normalized):
        raise _invalid("The complete native source differs from independently re-derived authority.")


def native_factor_application(aspect: Mapping[str, Any], factor: Mapping[str, Any],
                              source: Mapping[str, Any], base: Mapping[str, Any]) -> dict[str, Any]:
    fid = source.get("record_id", "")
    spec = _SPECS.get(fid.removeprefix(_PREFIX))
    binding = (source.get("factor_adapters") or {}).get(factor["factor_id"]) or {}
    if (spec is None or factor["factor_id"] != spec[1]
            or binding.get("source_record_id") != fid or binding.get("source_record_hash") != source.get("record_hash")):
        raise _invalid("The native source does not authenticate this Factor.")
    # Include definitions and counterplay, not just a table cell referring to
    # an undefined Package or Fettered Movement. These come from sealed rules.
    ranges = {"temporary_hp_fortification": (35, 126), "speed_reduction": (35, 125), "detect_presence": (398, 437)}
    start, end = ranges[factor["factor_id"]]
    rules = "\n".join(aspect["source_text"].splitlines()[start - 1:end])
    refinements = {
        "temporary_hp_fortification": {"temporary_hp": "PBd10" if fid.endswith("stamina_guard") else "PBd6", "duration": "1 minute", "stacking": "Does not stack with the same source", "cleanup": "Ends when depleted, dispelled or expired"},
        "speed_reduction": {"binding_save": "Strength saving throw against art save DC", "failed_save": "Speed reduced by 10 feet × PB for 1 minute", "failure_by_5": "Speed becomes 0 until start of binder's next turn", "successful_save": "No additional Speed reduction", "counterplay": "Action Break Attempt against Binding DC; retain the published suppression/break result bands"},
        "detect_presence": {"category": "ordinary spiritual afflictions listed by Soul Gaze on its legal target", "check": "Revelation Check against highest relevant DC", "success": "Whether at least one legal affliction is present", "success_by_5": "Rough number or strongest presence category", "success_by_10": "Strongest source category", "duration": "Instantaneous information; no continuing tracking"},
    }
    factor_rules = {"source": deepcopy(aspect["source"]), "line_start": start, "line_end": end,
                    "text": rules, "sha256": sha256_bytes(rules.encode())}
    return {**deepcopy(dict(base)), "mode": "native_path_source_factor_v1",
        "factor_rules": factor_rules,
        "effective_effect": {"base_source_effect": deepcopy(source["action_surface"]["effect"]),
            "factor_chassis": factor["mechanical_chassis"], "factor_refinement": refinements[factor["factor_id"]],
            "factor_rules": deepcopy(factor_rules)},
        "source_specific_mechanics": deepcopy(source["action_surface"]["source_mechanics"])}
