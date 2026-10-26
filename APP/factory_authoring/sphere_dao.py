"""A character's Dao, combined from the Dao profiles of the Spheres they know.

Owner doctrine (Dao-Yijing Mapping Engine): a Sphere is the truth of reality
the cultivator is sensitive to; the Yijing layer is the configuration of change
that places it under pressure; the Dao is the pattern that appears over time.
The Daos of the Spheres are the building blocks of personality and action:
each Sphere adds a layer, weighted by investment (owner ruling 2026-09-24:
sqrt(talents in the Sphere + 1); knowing the Sphere is its first mark).

From the layers this derives the character's trigram posture (where their Dao
moves naturally, what tests it, where it distorts), their hexagram (outer
trigram = the natural posture others see; inner = the testing pressure within)
and, when the shadow is a Line 6 excess, the hexagram that excess turns it into.
"""

from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from app.core import FoundryError

APP_ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_PATH = "authority/Tianxia_Sphere_Dao_Authority_R1.json"
AUTHORITY_SHA256 = "91d0cfaddb5571c1eca200a3d44ae55cacbf8120520dc3e6de3c14ccce0bb9cd"
SCHEMA = "TianxiaFoundry.CharacterDao.v1"


@lru_cache(maxsize=1)
def authority() -> dict[str, Any]:
    path = APP_ROOT / AUTHORITY_PATH
    data = path.read_bytes() if path.is_file() and not path.is_symlink() else b""
    if hashlib.sha256(data).hexdigest() != AUTHORITY_SHA256:
        raise FoundryError("SPHERE_DAO_AUTHORITY_INVALID", "The Sphere Dao authority is missing or does not match its pin.")
    return json.loads(data.decode("utf-8"))


def mark_label(marks: int) -> str:
    """The owner's scale: one mark a hint, two a tendency, three a trail, five strong resonance."""
    return "strong resonance" if marks >= 5 else "trail" if marks >= 3 else "tendency" if marks == 2 else "hint"


def _trigram_by_lines(lines: list[int]) -> str:
    return next(key for key, row in authority()["trigrams"].items() if row["lines"] == lines)


def _hexagram(upper: str, lower: str) -> dict[str, Any]:
    data = authority()
    row = data["hexagrams"][f"{upper}/{lower}"]
    trigrams = data["trigrams"]
    return {
        **row,
        "symbol": trigrams[upper]["symbol"] + trigrams[lower]["symbol"],
        "outer": f"{trigrams[upper]['name']} / {trigrams[upper]['image']}",
        "inner": f"{trigrams[lower]['name']} / {trigrams[lower]['image']}",
    }


def character_dao(sphere_talents: Mapping[str, int]) -> dict[str, Any] | None:
    """Combine the known Spheres ({sphere id: talents learned in it}) into the character's Dao.

    Spheres without a profile are reported, never guessed.  Returns None when
    the character knows no profiled Sphere.
    """
    data = authority()
    profiles = data["spheres"]
    layers = []
    unprofiled = []
    for sphere_id, talents in sphere_talents.items():
        profile = profiles.get(sphere_id)
        if profile is None:
            unprofiled.append(sphere_id)
            continue
        marks = max(0, int(talents)) + 1
        layers.append({"sphere_id": sphere_id, "profile": profile, "talents": marks - 1, "marks": marks, "weight": math.sqrt(marks)})
    if not layers:
        return None
    layers.sort(key=lambda row: (-row["weight"], row["profile"]["name"]))
    total = sum(row["weight"] for row in layers)

    # Trigram pressure.  Ties go to the trigram the stronger layer lists first.
    scores: dict[str, dict[str, float]] = {"natural": {}, "testing": {}, "shadow": {}}
    first_seen: dict[str, dict[str, int]] = {"natural": {}, "testing": {}, "shadow": {}}
    line_six: dict[str, float] = {}
    order = 0
    for row in layers:
        for kind in ("natural", "testing", "shadow"):
            for entry in row["profile"][f"{kind}_trigrams"]:
                trigram = entry["trigram"]
                scores[kind][trigram] = scores[kind].get(trigram, 0.0) + row["weight"]
                first_seen[kind].setdefault(trigram, order)
                order += 1
                if kind == "shadow" and entry["line"] == 6:
                    line_six[trigram] = line_six.get(trigram, 0.0) + row["weight"]

    def top(kind: str) -> str:
        return min(scores[kind], key=lambda trigram: (-round(scores[kind][trigram], 9), first_seen[kind][trigram]))

    natural, testing, shadow = top("natural"), top("testing"), top("shadow")
    shadow_is_excess = line_six.get(shadow, 0.0) * 2 > scores["shadow"][shadow]
    hexagram = _hexagram(natural, testing)
    excess = None
    if shadow_is_excess:
        upper_lines = list(data["trigrams"][natural]["lines"])
        upper_lines[2] = 1 - upper_lines[2]
        excess = {"line": 6, "becomes": _hexagram(_trigram_by_lines(upper_lines), testing)}

    # Six verb slots shared by weight (largest remainder), so every strong
    # layer speaks, not only the primary one.
    slots = 6
    quotas = [row["weight"] / total * slots for row in layers]
    counts = [int(quota) for quota in quotas]
    for index in sorted(range(len(layers)), key=lambda i: (-(quotas[i] - counts[i]), i))[: slots - sum(counts)]:
        counts[index] += 1
    top_verbs: list[str] = []
    for row, count in zip(layers, counts):
        for verb in [verb for verb in row["profile"]["dao_verbs"] if verb not in top_verbs][:count]:
            top_verbs.append(verb)

    trigrams = data["trigrams"]

    def trigram_view(key: str) -> dict[str, Any]:
        return {"trigram": key, **{field: trigrams[key][field] for field in ("name", "image", "symbol", "meaning")}}

    def ranked(kind: str) -> list[dict[str, Any]]:
        return [
            {**trigram_view(key), "share": round(scores[kind][key] / total, 3)}
            for key in sorted(scores[kind], key=lambda key: (-round(scores[kind][key], 9), first_seen[kind][key]))
        ]

    return {
        "schema": SCHEMA,
        "authority_sha256": AUTHORITY_SHA256,
        "weighting": data["weighting"]["formula"],
        "layers": [
            {
                "sphere_id": row["sphere_id"],
                "name": row["profile"]["name"],
                "status": row["profile"]["status"],
                "talents": row["talents"],
                "marks": row["marks"],
                "resonance": mark_label(row["marks"]),
                "weight": round(row["weight"], 3),
                "share": round(row["weight"] / total, 3),
                **{key: row["profile"][key] for key in (
                    "reality_principle", "dao_trail", "trial_signs", "shadow", "keep_distinct_from", "gm_read", "dao_verbs",
                )},
            }
            for row in layers
        ],
        "primary_sphere": layers[0]["profile"]["name"],
        "secondary_sphere": layers[1]["profile"]["name"] if len(layers) > 1 else None,
        "dao_verbs": top_verbs,
        "posture": {
            "natural": trigram_view(natural),
            "testing": trigram_view(testing),
            "shadow": {**trigram_view(shadow), "line": 6 if shadow_is_excess else None},
        },
        "trigram_pressure": {kind: ranked(kind) for kind in ("natural", "testing", "shadow")},
        "hexagram": hexagram,
        "excess": excess,
        "draft_spheres": [row["profile"]["name"] for row in layers if row["profile"]["status"] == "draft"],
        "unprofiled_sphere_ids": sorted(unprofiled),
    }


def sheet_sphere_talents(owner_sheet: Any) -> dict[str, int]:
    """{sphere id: talents learned in it} from an owner character sheet's spheres_and_talents block."""
    from canonical_catalog.service import talent_sphere_ids

    block = owner_sheet.get("spheres_and_talents") if isinstance(owner_sheet, Mapping) else None
    if not isinstance(block, Mapping):
        return {}
    counts = {value: 0 for value in block.get("sphere_record_ids") or [] if isinstance(value, str)}
    talents = {value for value in block.get("learned_talent_record_ids") or [] if isinstance(value, str)}
    if isinstance(block.get("background_talent_record_id"), str):
        talents.add(block["background_talent_record_id"])
    owners = talent_sphere_ids()
    for talent_id in talents:
        if owners.get(talent_id) in counts:
            counts[owners[talent_id]] += 1
    return counts


# ---------------------------------------------------------------- combat AI
# The Framework's NPC Dao AI profile: a Default Trigram Posture (how the
# character fights), a Stress Posture (how it fights when pressed) and a
# Shadow Trigger.  In its worked examples both postures come from the
# character's natural trigrams (Sword Elder: Heaven, then Mountain; Mist
# Assassin: Water, then Wind-Wood), so here the default posture is the whole
# natural-trigram blend and the stress posture is the strongest natural
# trigram after the first.  Each trigram's meaning (Trigram Profile Catalogue)
# moves the local controller's existing levers; nothing new is scored.
_BASE_WEIGHTS = {"ally_support": 6, "avoidable_risk": 8, "character_policy": 10, "finish": 14, "immediate_effect": 10,
                 "no_progress": 6, "position": 5, "resource_use": 4, "survival": 8, "cover": 0, "surround_avoid": 1}
# Cheap battlefield tactics per trigram: how much cover matters and how much being surrounded is avoided.
_TACTICS = {"kan": {"cover": 4, "surround_avoid": 3}, "gen": {"cover": 3, "surround_avoid": 2},
            "xun": {"cover": 2, "surround_avoid": 2}, "kun": {"cover": 2, "surround_avoid": 1},
            "dui": {"surround_avoid": 1}, "li": {"cover": 1}, "qian": {}, "zhen": {}}
# Spec §9.3 (LIGHTING_SPEC.md): how much a sphere leans toward Darkness (positive) or Brightness (negative).
_DARKNESS_AFFINITY = {
    "tianxia.sphere.dark": 6, "tianxia.sphere.shadow": 5, "tianxia.sphere.smoke": 4,
    "tianxia.sphere.the_hidden_eye": 3, "tianxia.sphere.illusion": 3,
    "tianxia.sphere.death": 3,      # Ghost Lantern's dim 20 ft is a predator's tool
    "tianxia.sphere.fire": -2, "tianxia.sphere.radiance": -4, "tianxia.sphere.yang": -3,
}
# kan (peril, hidden danger) and xun (subtle entry) also lean dark:
_DARKNESS_TRIGRAM = {"kan": 3, "xun": 2, "zhen": -1, "li": -2, "qian": -1}
# I Ching change triggers: the composite playbooks shift lines when Qi falls below 19 of 63 (about 30%).
_STRESS_TRIGGERS = {"hp_pct": 40, "resource_pct": 30}
_TRIGRAM_LEVERS: dict[str, dict[str, Any]] = {
    # force, mandate, initiative: press the strongest, finish decisively.
    "qian": {"weights": {"finish": 4, "immediate_effect": 3, "avoidable_risk": -2}, "targets": {"FOCUS_TARGET": 4},
             "actions": {"system:combat.dash": 2}, "range": (5, 15), "stress_survival": -4},
    # shock, first movement, crisis: strike first, accept exposure.
    "zhen": {"weights": {"immediate_effect": 4, "finish": 2, "avoidable_risk": -3}, "targets": {},
             "actions": {"system:combat.dash": 2, "system:combat.dodge": -2}, "range": (5, 15), "stress_survival": -4},
    # peril, hidden danger: cautious pressure, ambush, retreat into terrain (Kan's "Good for NPC AI").
    "kan": {"weights": {"avoidable_risk": 4, "survival": 3, "position": 3, "immediate_effect": -1}, "targets": {"LOW_HP_PRIMARY": 2},
            "actions": {"system:combat.disengage": 3}, "range": (15, 45), "stress_survival": 4},
    # stopping, boundary, restraint: hold ground, guard, spend little.
    "gen": {"weights": {"position": 3, "survival": 3, "avoidable_risk": 2, "resource_use": 2, "finish": -1}, "targets": {},
            "actions": {"system:combat.dodge": 3}, "range": (5, 20), "stress_survival": 4},
    # receptivity, support, bearing: cover allies before self.
    "kun": {"weights": {"ally_support": 5, "survival": 2, "finish": -2}, "targets": {},
            "actions": {"system:combat.dodge": 1}, "range": (5, 30), "stress_survival": 3},
    # subtle entry, gradual influence: position, patience, wear the weakened down.
    "xun": {"weights": {"position": 3, "resource_use": 2, "avoidable_risk": 1, "immediate_effect": -1}, "targets": {"LOW_HP_PRIMARY": 3},
            "actions": {"system:combat.disengage": 2}, "range": (10, 30), "stress_survival": 1},
    # clarity, exposure, what clings: fix on one visible target.
    "li": {"weights": {"finish": 2, "immediate_effect": 1}, "targets": {"FOCUS_TARGET": 5},
           "actions": {}, "range": (5, 30), "stress_survival": -1},
    # exchange, openness, community: fight with and for the group.
    "dui": {"weights": {"ally_support": 4, "character_policy": 1, "avoidable_risk": -1}, "targets": {},
            "actions": {}, "range": (5, 30), "stress_survival": 0},
}
# The default posture's levers are applied at this strength (natural shares sum to 1).
_POSTURE_GAIN = 2.0


def _blend(shares: Mapping[str, float]) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    weights = {key: float(value) for key, value in _BASE_WEIGHTS.items()}
    targets = {"FOCUS_TARGET": 12.0, "LOW_HP_PRIMARY": 20.0}
    actions = {"system:combat.dash": 4.0, "system:combat.disengage": 4.0, "system:combat.dodge": 6.0}
    for trigram, share in shares.items():
        levers = _TRIGRAM_LEVERS[trigram]
        for bucket, table in ((weights, levers["weights"]), (weights, _TACTICS[trigram]),
                              (targets, levers["targets"]), (actions, levers["actions"])):
            for key, delta in table.items():
                bucket[key] = bucket.get(key, 0.0) + delta * share * _POSTURE_GAIN
    return weights, targets, actions


def _rounded(weights: Mapping[str, float]) -> dict[str, int]:
    return {key: max(0 if key in {"cover", "surround_avoid"} else 1, min(30, round(value))) for key, value in sorted(weights.items())}


def _light_levers(dao: Mapping[str, Any], default: str) -> dict[str, int]:
    """Spec §9.3 darkness/unseen_ground terms, plus a brightness term for the Bright-leaning spheres.

    The spec's clamp at zero cannot express a Fire Dao that prefers Bright, so the Bright lean is its own weight.
    Zero-valued keys are omitted, so a Dao with no light lean keeps its existing policy dump.
    """
    layers = dao.get("layers") or ()
    primary = layers[0].get("sphere_id") if layers else None
    secondary = layers[1].get("sphere_id") if len(layers) > 1 else None
    sphere = _DARKNESS_AFFINITY.get(primary, 0) + _DARKNESS_AFFINITY.get(secondary, 0) / 2
    # The trigram lean applies to the darkness term only; it must not give every Dao a bright lean.
    darkness = max(0, round(sphere + _DARKNESS_TRIGRAM.get(default, 0)))
    levers = {"darkness": darkness, "unseen_ground": darkness // 2, "brightness": max(0, round(-sphere))}
    return {key: value for key, value in levers.items() if value}


def controller_policy(dao: Mapping[str, Any], actor_id: str, *, primary_resource: tuple[str, int, str] | None = None) -> dict[str, Any]:
    """A LocalControllerPolicy (TianxiaLocalControllerPolicy.v1) for the combat AI, derived from the character's Dao.

    Default posture: the natural-trigram blend.  Stress posture (the I Ching
    change): the stress trigram leads the blend; the controller switches to it
    when HP or the primary resource falls to the triggers, and back when they
    recover.  ``primary_resource`` is (resource id, maximum, label).
    """
    natural = dao["trigram_pressure"]["natural"]
    total = sum(row["share"] for row in natural) or 1.0
    shares = {row["trigram"]: row["share"] / total for row in natural}
    weights, targets, actions = _blend(shares)
    default = natural[0]["trigram"]
    stress = natural[1]["trigram"] if len(natural) > 1 else default
    stress_shares = {key: value * 0.5 for key, value in shares.items()}
    stress_shares[stress] = stress_shares.get(stress, 0.0) + 0.5
    stress_weights, _stress_targets, _stress_actions = _blend(stress_shares)
    # Under pressure the stress posture decides whether the character guards itself or fights on.
    weights["survival"] += _TRIGRAM_LEVERS[stress]["stress_survival"]
    stress_weights["survival"] += 2 * _TRIGRAM_LEVERS[stress]["stress_survival"]
    shadow = dao["posture"]["shadow"]
    unsigned = {
        "schema": "TianxiaLocalControllerPolicy.v1",
        "policy_id": f"policy:dao.{actor_id}",
        "policy_version": "1.1.0",
        "goal_description": " / ".join(dao["dao_verbs"]),
        "source_doctrine_id": "tianxia.sphere_dao.R1",
        "source_doctrine_sha256": AUTHORITY_SHA256,
        "actor_id": actor_id,
        "role": (
            f"Dao: {dao['primary_sphere']}" + (f" / {dao['secondary_sphere']}" if dao.get("secondary_sphere") else ""),
            f"default posture: {_trigram_name(default)}",
            f"stress posture: {_trigram_name(stress)}",
            f"shadow: {shadow['name']}" + (f" Line {shadow['line']}" if shadow.get("line") else ""),
        ),
        "preferred_range_bands_ft": (_TRIGRAM_LEVERS[default]["range"],),
        "target_priorities": {key: max(0, round(value)) for key, value in sorted(targets.items())},
        "action_priorities": {key: max(0, round(value)) for key, value in sorted(actions.items())},
        "resource_reserves": {},
        "reaction_rules": {},
        "ally_companion_priorities": {},
        "support_wounded_allies": True,
        "low_hp_behavior": {"critical_defense": 20, "pressured_defense": 10, "stress_posture": stress},
        "prohibited_choices": (),
        # General turn-planner levers derived from the same Dao blend, not
        # a separate personality or per-character playbook. Larger values
        # prefer control/setup and self-preservation over immediate damage.
        "tactic_weights": {"control": round(weights["position"] + weights["avoidable_risk"] / 2),
                           "setup": round(weights["resource_use"]),
                           "withdraw": round(weights["survival"]),
                           **_light_levers(dao, default)},
        "weights": _rounded(weights),
        "generic_fallback": False,
        "stress_weights": _rounded(stress_weights),
        "stress_range_bands_ft": (_TRIGRAM_LEVERS[stress]["range"],),
        "stress_triggers": dict(_STRESS_TRIGGERS),
        "stress_resource": ({"resource_id": primary_resource[0], "maximum": int(primary_resource[1]), "label": primary_resource[2]}
                            if primary_resource else None),
        "posture_labels": {"default": _trigram_name(default), "stress": _trigram_name(stress)},
        "position_relative": True,
        "guard_only_when_no_strike": True,
    }
    unsigned["source_projection_sha256"] = hashlib.sha256(
        json.dumps({"layers": [[row["sphere_id"], row["talents"]] for row in dao["layers"]]}, sort_keys=True).encode()
    ).hexdigest()
    return unsigned


def _trigram_name(key: str) -> str:
    row = authority()["trigrams"][key]
    return f"{row['name']} / {row['image']}"
