"""Build the sealed Forged Technique authority from the published forging rules.

Every number here is transcribed from Core Rules §11 (Forged Techniques) and
the PHB chapter 18 tables, which agree.  The file is sealed with the same
canonical seal the Path feature statistic formulas use, so the constructor and
the Stage 2 compiler can refuse a drifted table.  Re-run this tool only when
the cited sources change; the seal makes any edit visible.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from app.core import sha256_json  # noqa: E402

CORE = {
    "source_id": "source.core_rules_reference.v0_2c",
    "path": "Tianxia_Core_Rules_Reference_v0_2C.md",
    "source_hash": "07dc678e2c686e191f7da34b959964cfe535c6368019ffaf37227eb39d87ad10",
    "anchor": "section:11:lines:3085-3343",
}
PHB = {
    "source_id": "source.phb_manuscript.v0_7",
    "path": "09_RULES/Source_Text/PHB/Tianxia_PHB_Manuscript_v0_7_Subpaths_Inserted.md",
    "source_hash": "f2bb2eeba55a4b8b8630e02fbcb35d21ac80d2efb7ad4a9e91642522f82d7fe7",
    "anchor": "chapter:18:lines:10613-10943",
}
GM_GUIDE = {
    "source_id": "source.gm_guide.v0_1",
    "path": "Tianxia_GM_Guide_v0_1_Polished_Manuscript.md",
    "source_hash": "ab83a99b1d516db26af87ee997cec45efa482ac52c3e627042eacc3ee25f6713",
    "anchor": "section:2.8:lines:1021-1068",
}


def _form(form_id, name, cp, complexity, use):
    return {"form_id": form_id, "display_name": name, "starting_cp": cp, "complexity": complexity, "use": use}


def _augment(aid, name, tier, complexity, cp, minimum_realm):
    return {"augment_id": aid, "display_name": name, "tier": tier, "complexity": complexity, "cp": cp, "minimum_realm": minimum_realm}


def _drawback(did, name, reduction, restriction):
    return {"drawback_id": did, "display_name": name, "cp_reduction": reduction, "restriction": restriction}


unsigned = {
    "schema_version": "TianxiaFoundry.ForgedTechniqueAuthority.v1",
    "pack_id": "tianxia.forged_technique_authority.r1",
    "authority_classification": "AUTHENTICATED_CANONICAL_SOURCE",
    "sources": {"core_rules": CORE, "phb_chapter_18": PHB, "gm_guide_record_format": GM_GUIDE},
    "access": {
        "rule_id": "tianxia.forging.access.r1",
        "minimum_cl": 5,
        "note": "Technique Forging normally becomes available at Foundation, CL 5. Mortal-Realm forging needs GM permission and is not a normal character option; the Factory never constructs it.",
    },
    "realm_complexity_limits": [
        {"realm": "Mortal", "cl_min": 1, "cl_max": 4, "maximum_complexity": 2, "exceptional_only": True},
        {"realm": "Foundation", "cl_min": 5, "cl_max": 9, "maximum_complexity": 4, "exceptional_only": False},
        {"realm": "Core Formation", "cl_min": 10, "cl_max": 14, "maximum_complexity": 6, "exceptional_only": False},
        {"realm": "Nascent Soul", "cl_min": 15, "cl_max": 19, "maximum_complexity": 8, "exceptional_only": False},
        {"realm": "Immortal", "cl_min": 20, "cl_max": 20, "maximum_complexity": 10, "exceptional_only": False},
    ],
    "recommended_maximum_spheres": [
        {"realm": "Mortal", "maximum_spheres": 1},
        {"realm": "Foundation", "maximum_spheres": 2},
        {"realm": "Core Formation", "maximum_spheres": 3},
        {"realm": "Nascent Soul", "maximum_spheres": 4},
        {"realm": "Immortal", "maximum_spheres": 4, "note": "GM discretion; the Factory holds the Nascent Soul figure."},
    ],
    "base_forms": [
        _form("strike", "Strike", 1, 1, "weapon or unarmed delivery"),
        _form("projection", "Projection", 1, 1, "beam, bolt, slash, psychic attack, elemental blast, or similar projection"),
        _form("movement", "Movement", 1, 1, "leap, teleport, dash, brief flight, or repositioning"),
        _form("burst", "Burst", 2, 2, "area centered on self or visible point"),
        _form("cone", "Cone", 2, 2, "cone from self"),
        _form("line", "Line", 2, 2, "straight line"),
        _form("ward", "Ward", 2, 2, "defensive effect on self or ally"),
        _form("aura", "Aura", 3, 3, "persistent self-centered effect"),
        _form("zone", "Zone", 3, 3, "persistent battlefield area"),
        _form("counter", "Counter", 3, 3, "reaction against a trigger"),
        _form("ritual", "Ritual", None, 1, "slow noncombat or preparation effect"),
    ],
    "secondary_sphere_effect": {"complexity_per_additional_sphere": 1, "note": "may increase CP cost; the Factory adds no CP for a secondary effect"},
    "augments": [
        _augment("increased_damage", "Increased Damage", "basic", 1, 1, "Mortal"),
        _augment("extended_range", "Extended Range", "basic", 1, 1, "Mortal"),
        _augment("expanded_area", "Expanded Area", "basic", 1, 1, "Mortal"),
        _augment("additional_target", "Additional Target", "basic", 1, 1, "Mortal"),
        _augment("forced_movement", "Forced Movement", "basic", 1, 1, "Mortal"),
        _augment("minor_hindrance", "Minor Hindrance", "basic", 1, 1, "Mortal"),
        _augment("lingering_effect", "Lingering Effect", "basic", 1, 1, "Mortal"),
        _augment("mobility_rider", "Mobility Rider", "basic", 1, 1, "Mortal"),
        _augment("major_condition", "Major Condition", "advanced", 2, 2, "Foundation"),
        _augment("persistent_zone", "Persistent Zone", "advanced", 2, 2, "Foundation"),
        _augment("ignore_resistance", "Ignore Resistance", "advanced", 2, 2, "Core Formation"),
        _augment("reaction_activation", "Reaction Activation", "advanced", 2, 2, "Core Formation"),
        _augment("bonus_action_activation", "Bonus-Action Activation", "advanced", 2, 3, "Core Formation"),
        _augment("severe_hindrance", "Severe Hindrance", "advanced", 2, 2, "Core Formation"),
        _augment("domain_effect", "Domain Effect", "advanced", 3, 3, "Nascent Soul"),
        _augment("conceptual_effect", "Conceptual Effect", "advanced", 3, 4, "Nascent Soul"),
    ],
    "augment_rules": {
        "hostile_conditions_require_saves": "Hostile conditions require saving throws against the Cultivation Save DC.",
        "repeat_saves": "Conditions lasting longer than one round normally allow repeat saves at the end of the affected creature's turns.",
        "action_economy": "Action-economy upgrades are expensive, usually require Core Formation or higher, and require GM approval.",
    },
    "drawbacks": [
        _drawback("concentration", "Concentration", 1, "requires Concentration"),
        _drawback("preparation", "Preparation", 1, "requires preparation before use"),
        _drawback("long_invocation", "Long Invocation", 1, "requires a long invocation"),
        _drawback("self_damage", "Self-Damage", 1, "damages the user"),
        _drawback("restricted_environment", "Restricted Environment", 1, "usable only in a named environment"),
        _drawback("material_focus", "Material Focus", 1, "requires a carried material focus"),
        _drawback("once_per_short_rest", "Once per Short Rest", 1, "usable once per Short Rest"),
        _drawback("once_per_long_rest", "Once per Long Rest", 2, "usable once per Long Rest"),
        _drawback("exhausting", "Exhausting", 2, "gives 1 level of Exhaustion after the technique resolves"),
        _drawback("backlash", "Backlash", 1, "a defined trigger causes a defined consequence"),
    ],
    "drawback_rules": {
        "reduce_cp_not_complexity": True,
        "minimum_final_cp": 1,
        "maximum_reduction": "pb",
        "reject_meaningless": "Reject Drawbacks that do not meaningfully restrict the technique.",
    },
    "backlash": {
        "default_triggers": [
            "user fails the technique's attack roll or check by 5 or more",
            "target succeeds on its save by 5 or more",
            "technique is countered, interrupted, or disrupted",
            "technique is used in an unstable condition named when created",
        ],
        "default_effects": [
            "lose 1 CP after the technique resolves",
            "take damage equal to Complexity + PB",
            "brief CP strain",
            "fall prone",
            "lose focus",
            "reveal position",
        ],
        "not_exhaustion_by_default": True,
    },
    "hard_limits": [
        "create or multiply CP",
        "bypass full cultivation-session limits",
        "convert temporary CP into permanent CP",
        "grant additional full turns",
        "create permanent effects by default",
        "impose hostile conditions without saves",
        "replace talents the character does not know",
        "ignore Realm requirements",
        "ignore Path restrictions",
        "ignore action economy without paying for that power",
        "ignore Source Rule limits",
    ],
    "forging_check": {
        "rule_id": "tianxia.forging.check.r1",
        "dc_formula": "10 + final Complexity + number of Spheres used",
        "dc": {"base": 10, "per_complexity": 1, "per_sphere": 1},
        "research_days": {"per_complexity": 3, "minimum": 3},
        "material_cost_gp": {"per_complexity_squared": 100},
        "check": "Cultivation Check: d20 + Proficiency Bonus + the key ability modifier of the Path powering the feature",
    },
    "known_limit": {"rule_id": "tianxia.forging.known_limit.r1", "maximum_known": "pb", "recorded_arts_count": False},
    "no_retraining": "A learned Forged Technique cannot be freely replaced, refunded, swapped, or retrained.",
    "evolution_states": ["base", "evolved", "unstable", "sealed", "suppressed", "transformed"],
    "record_fields": [
        "name", "owner", "cl_and_realm_at_creation", "base_form", "primary_sphere_effect", "secondary_sphere_effects",
        "augments", "drawbacks", "action_type", "cp_cost", "target_range_area", "attack_save_check", "effect",
        "duration", "limits", "complexity", "spheres_used", "technique_forging_dc", "research_time", "material_cost", "source_notes",
    ],
}
sealed = dict(unsigned)
sealed["seal_sha256"] = sha256_json(unsigned)
if __name__ == "__main__":
    out = HERE / "authority" / "Tianxia_Forged_Technique_Authority_R1.json"
    out.write_text(json.dumps(sealed, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(out, sealed["seal_sha256"])
