"""Source-preserving Forge action profiles for published Air attacks.

These profiles introduce no damage dice, areas, conditions or action upgrades.
They retain a complete published effect and apply the printed Ignore Resistance
augment to its damage. Other designs require their own complete source profile.
"""
from __future__ import annotations

from typing import Any, Mapping

from app.core import Database, FoundryError, sha256_bytes, sha256_json
from character_creation.constructed_arts.sources import installed_factory_root, published_block
from project_store.service import ProjectStore

_AIR_SHA = "67f67275889467d43605debaa0c05dc5ddde9ba079222819aabea27c66167775"
_AIR_PATH = "09_RULES/Source_Text/Tianxia_Sphere_Compendium_Latest_R0I_85Spheres.md"
_PROFILES = {
    "TAL_AIR_DOWNBURST_SEAL": ("burst", "Downburst Seal", 5),
    "TAL_AIR_HEAVEN_SPLITTING_GALE": ("line", "Heaven-Splitting Gale", 15),
}
_RESOURCE = {"tianxia.path.body_refining": "Stamina", "tianxia.path.qi_cultivation": "Qi", "tianxia.path.spirit_awakening": "Resonance"}


def _unresolved(message: str) -> FoundryError:
    return FoundryError("COMMAND4_FORGED_MECHANICS_UNRESOLVED", message)


def forged_action_projection(technique: Mapping[str, Any], factory_root) -> dict[str, Any]:
    primary = technique.get("primary_sphere_effect") or {}
    profile = _PROFILES.get(primary.get("talent_id"))
    if profile is None or technique.get("construction", {}).get("generator_version") != 3:
        raise _unresolved("This Forge design has no supported, explicit source-preserving action profile.")
    form, name, minimum_cl = profile
    cl = technique.get("cl_created")
    if type(cl) is not int or cl < minimum_cl or technique.get("base_form", {}).get("form_id") != form or technique.get("action_type") != "action":
        raise _unresolved("The Forge design must preserve the source's shape, activation and level requirement.")
    if technique.get("secondary_sphere_effects") or technique.get("drawbacks") or [r.get("augment_id") for r in technique.get("augments", [])] != ["ignore_resistance"]:
        raise _unresolved("This profile supports only the printed Ignore Resistance augment, with no secondary effects or Drawbacks.")
    source = primary.get("source") or {}
    printed = published_block(factory_root, source).strip()
    if primary.get("sphere_id") != "tianxia.sphere.air" or primary.get("talent_name") != name or source.get("path") != _AIR_PATH or source.get("source_hash") != _AIR_SHA or not printed.startswith(f"#### {name} - ") or primary.get("published_text") != printed:
        raise _unresolved("The primary effect is not the exact hash-verified published Air source.")
    resource = _RESOURCE.get(technique.get("powering_path_id"))
    cost = technique.get("cp_cost", {}).get("final")
    if resource is None or type(cost) is not int or cost != 4:
        raise _unresolved("The preserved Burst/Line plus Ignore Resistance profile requires its sealed four-point native resource cost.")
    dependencies = [{"source": dict(source), "text_sha256": sha256_bytes(printed.encode("utf-8"))}]
    immunity = "Damage from this technique ignores Resistance through the printed Ignore Resistance augment. Immunity and explicit Source Rule limits remain in force."
    if primary["talent_id"] == "TAL_AIR_HEAVEN_SPLITTING_GALE":
        fields = {
            "Range": "300 feet",
            "Target": "Creatures in the 300-foot line, 10 feet wide",
            "Area": "300-foot line, 10 feet wide",
            "Roll/Save/Check": "Dexterity saving throw against your Cultivation Save DC",
            "Effect": "On a failed save, a creature takes 8d8 slashing damage, is pushed 30 feet in a direction perpendicular to the line, and cannot take Reactions until the start of your next turn. " + immunity,
            "Failure": "On a successful save, a creature takes half damage and is pushed 10 feet. The damage still ignores Resistance, but not Immunity.",
            "Duration": "Damage and pushing resolve immediately; the failed-save Reaction restriction lasts until the start of your next turn.",
            "Limit": "The printed source defines no separate use limit for Heaven-Splitting Gale.",
            "Counterplay": "The printed Dexterity save reduces damage and pushing. Objects and exposed mechanisms in the line may be severed or damaged only at the GM's discretion. " + immunity,
        }
    else:
        # Downburst cites Wind Lash's damage, not its attack roll or Vectors.
        dependency = {"path": _AIR_PATH, "anchor": "line:804:column:1", "source_hash": _AIR_SHA}
        wind_lash = published_block(factory_root, dependency).strip()
        if not wind_lash.startswith("#### Wind Lash") or "The damage increases by 1d8 at CL 5, CL 11, and CL 17." not in wind_lash:
            raise _unresolved("Downburst Seal needs the exact published Wind Lash damage progression.")
        dependencies.append({"source": dependency, "text_sha256": sha256_bytes(wind_lash.encode("utf-8"))})
        dice = 1 + sum(cl >= threshold for threshold in (5, 11, 17))
        damage = f"{dice}d8 + your {technique['key_ability']} modifier, as bludgeoning or slashing damage"
        fields = {
            "Range": "60 feet",
            "Target": "Creatures in the 10-foot-radius, 30-foot-high cylinder, centered on yourself or a visible point within range",
            "Area": "10-foot-radius, 30-foot-high cylinder",
            "Roll/Save/Check": "Strength saving throw against your Cultivation Save DC",
            "Effect": f"On a failed save, a creature takes Wind Lash damage ({damage}), is pushed to the ground, and falls Prone if it is on a surface. If it is flying and does not hover, it descends up to 30 feet before falling Prone if it lands. This uses Wind Lash's damage only, not its attack roll or Vector riders. " + immunity,
            "Failure": "On a successful save, a creature takes half damage and does not fall Prone. The damage still ignores Resistance, but not Immunity.",
            "Duration": "Damage and forced movement resolve immediately. Prone follows its ordinary condition rules.",
            "Limit": "The printed source defines no separate use limit for Downburst Seal.",
            "Counterplay": "The printed Strength save reduces damage and prevents Prone. The descent clause applies only to a flying creature that does not hover. " + immunity,
        }
    dc_source = {"path": _AIR_PATH, "anchor": "line:722:column:1", "source_hash": _AIR_SHA}
    dc_text = published_block(factory_root, dc_source).strip()
    if "When an Air talent calls for a saving throw, use your Cultivation Save DC." not in dc_text:
        raise _unresolved("The source's Cultivation Save DC rule is missing.")
    dependencies.append({"source": dc_source, "text_sha256": sha256_bytes(dc_text.encode("utf-8"))})
    lines = [f"# {technique['name']}", "Action Type: Action", "Factory Combat Bucket: action", "Factory Routing: combat_action_row", "Timing: Action", f"Cost: {cost} {resource}"]
    lines.extend(f"{key}: {value}" for key, value in fields.items())
    return {"profile_id": "source-preserving-air-ignore-resistance.v1", "full_description": "\n".join(lines), "published_source_dependencies": dependencies}


def load_forged_action_binding(db: Database, project_id: str, record_id: str) -> dict[str, Any] | None:
    if not record_id.startswith("tianxia.constructed.forged_technique."):
        return None
    projects = ProjectStore(db)
    with db.connection() as conn:
        record = projects._resolve_locked_record(conn, project_id, record_id)
        if not isinstance(record, dict):
            raise _unresolved("The Forge design has no immutable record in this project.")
        projects._assert_constructed_art_snapshot_record(conn, project_id, record)
    technique = record["compatibility"]["factory"]["constructed_art"]["technique"]
    if technique.get("owner_project_id") != project_id:
        raise _unresolved("The Forge design belongs to a different project.")
    if technique.get("construction", {}).get("generator_version") != 3:
        return None
    if (technique.get("primary_sphere_effect") or {}).get("talent_id") not in _PROFILES:
        # No automated source-preserving profile for this design (only two Air profiles exist): the card stays
        # display-only like an older design instead of stopping finalize (2026-10-17: a seeded CL5 build forging a
        # non-Air technique stopped at NEEDS_REVIEW). A design claiming a known profile still fails closed below,
        # and a supplied binding for an unprofiled design still fails validation.
        return None
    projection = forged_action_projection(technique, installed_factory_root(db.settings.vendor_dir))
    source = record["source"]
    return {
        "authority": "rederived_project_locked_forged_technique",
        "project_id": project_id,
        "record_id": record_id,
        "record_hash": record["record_hash"],
        "record_sha256": sha256_json(record),
        "name": record["display_name"],
        "source": {"path": source["path"], "anchor": source["anchor"], "sha256": source["source_hash"]},
        **projection,
        "source_text_sha256": sha256_bytes(projection["full_description"].encode("utf-8")),
        "grants_acquisition": False,
    }


def validate_forged_action_candidate(db: Database, project_id: str, candidate: Mapping[str, Any]) -> dict[str, Any] | None:
    supplied = candidate.get("constructed_forged_source_binding")
    if supplied is None:
        return None
    record_id = candidate.get("record_id")
    if not isinstance(record_id, str):
        raise _unresolved("The Forge candidate has no exact record identity.")
    expected = load_forged_action_binding(db, project_id, record_id)
    if expected is None or supplied != expected or any(candidate.get(key) != expected[key] for key in ("record_hash", "source", "name", "full_description")):
        raise _unresolved("The Forge candidate differs from its independently recompiled project record and installed source profile.")
    return expected
