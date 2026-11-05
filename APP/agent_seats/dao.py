"""Own-character Dao metadata for seat prompts; no battlefield information.

Used by SeatRunner's view assembly. Names/trails/verbs come from the existing
sphere profile, or tenets from the policy's bound bundled doctrine. Missing
names stay explicitly unnamed; this projection does not define new Dao rules.
"""
import json
from pathlib import Path
import re


def dao_view(policy, source_root, profile=None):
    result = {"name": "Unnamed Dao", "role": list(policy.role),
              "posture": policy.posture_labels or {},
              "preferred_distance_ft": policy.preferred_range_bands_ft,
              "save_resources": policy.resource_reserves,
              "under_pressure": policy.stress_triggers or {},
              "combat_policy_weights": dict(policy.weights),
              "tenets": []}
    if profile:
        result["name"] = " / ".join(layer["name"] for layer in profile["layers"][:2])
        result["tenets"] = [layer["dao_trail"] for layer in profile["layers"]]
        result["temperament"] = {
            "spheres": [layer["name"] for layer in profile["layers"]],
            "verbs": profile["dao_verbs"],
            "fighting": ", ".join(profile["dao_verbs"]),
            **{kind: profile["posture"][kind]["meaning"]
               for kind in ("natural", "testing", "shadow")}}
    else:
        # Older installed portable actors can have a sphere-derived policy
        # without an accessible owner sheet. Its existing role names the Dao;
        # its posture label identifies the same authority's plain meaning.
        if policy.source_doctrine_id == "tianxia.sphere_dao.R1":
            from factory_authoring.sphere_dao import authority
            result["name"] = next((r.removeprefix("Dao: ") for r in policy.role
                                   if r.startswith("Dao: ")), "Unnamed Dao")
            default = (policy.posture_labels or {}).get("default")
            meaning = next((t["meaning"] for t in authority()["trigrams"].values()
                            if f"{t['name']} / {t['image']}" == default), "")
            result["temperament"] = {"fighting": meaning or ", ".join(policy.role)}
            return result
        # Only a canonical doctrine id selects a public generated artifact.
        match = re.fullmatch(r"doctrine:([a-z0-9_]+)\.gate1", policy.source_doctrine_id or "")
        if match:
            path = Path(source_root) / "combat_gate1/generated/doctrines" / (match[1] + ".json")
            try:
                doctrine = json.loads(path.read_text())["doctrine"]
                if doctrine["doctrine_id"] == policy.source_doctrine_id:
                    result["tenets"] = list(doctrine["components"].get("dao") or [])
            except (OSError, ValueError, KeyError):
                pass
        result["temperament"] = {"fighting": "; ".join(result["tenets"] or result["role"])}
    return result
