"""Component proofs for three bounded plug-in block shapes.

These are source proofs of an executable component in an eligible ordinary
context, not whole-ability fidelity or runtime tests. Missing sources, a
nonwinning feature row, and unsupported spec shapes fail closed with no proof.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any


_COMMON = (
    "APP/combat/ext/__init__.py", "APP/combat/factory_compiler.py",
    "APP/combat/authority_cache.py",
    "APP/combat/typed_reactions.py", "APP/combat/typed_executor.py",
    "APP/combat/ext/damage_transfer_scope.py",
    "APP/combat/area_recipients.py", "APP/combat/area_recipient_rules.py",
    "APP/combat/effect_harm.py", "APP/combat/rules/area_recipient_overrides.json",
)
_FAMILY_FILES = {
    "object_damage": ("APP/combat/ext/objects.py", "APP/combat/object_rules.py"),
    "grounding_breath": ("APP/combat/ext/lightning_grounding.py",),
    "ironroot_demon_bone_regen": ("APP/combat/ext/ironroot_daemonic.py", "APP/combat/ext/spend_choice.py"),
}
_METADATA = {"block", "why", "label", "covers"}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _winning_feature(root: Path, mechanic_id: str) -> tuple[dict[str, Any], str, str] | None:
    directory = root / "APP" / "combat" / "rules"
    winner = None
    paths = [directory / "feature_blocks.json", *sorted((directory / "feature_blocks.d").glob("*.json"))]
    try:
        for path in paths:
            content = path.read_bytes()
            data = json.loads(content)
            features = data.get("features") or {}
            if not isinstance(features, dict):
                return None
            if mechanic_id in features:
                if not isinstance(features[mechanic_id], dict):
                    return None
                text = content.decode("utf-8")
                at = text.find(json.dumps(mechanic_id, ensure_ascii=False))
                line = text.count("\n", 0, max(0, at)) + 1
                winner = (features[mechanic_id], f"{path.relative_to(root).as_posix()}:{line}",
                          hashlib.sha256(content).hexdigest())
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
        return None
    return winner


def _first_damage(effects: Any) -> dict[str, Any] | None:
    if not isinstance(effects, list):
        return None
    for effect in effects:
        if not isinstance(effect, dict):
            continue
        if effect.get("type") == "damage" and isinstance(effect.get("dice"), dict):
            return effect
        for key in ("on_fail", "on_success", "on_hit", "effects"):
            found = _first_damage(effect.get(key))
            if found is not None:
                return found
    return None


def _shape_supported(block: str, mechanic: dict[str, Any], feature: dict[str, Any]) -> bool:
    activation = mechanic.get("activation") or {}
    if not isinstance(activation, dict) or not isinstance(activation.get("economy"), str):
        return False
    if "covers" in feature and (not isinstance(feature["covers"], list) or not all(isinstance(text, str) for text in feature["covers"])):
        return False
    if block == "ironroot_demon_bone_regen" and "a2_cl_gate" in feature:
        return (set(feature) <= (_METADATA | {"a2_cl_gate"})
                and type(feature["a2_cl_gate"]) is bool
                and activation.get("economy") == "passive")
    if block in {"grounding_breath", "ironroot_demon_bone_regen"}:
        return set(feature) <= _METADATA and activation.get("economy") == "passive"
    if set(feature) - (_METADATA | {"on", "double", "double_for"}):
        return False
    if feature.get("on") != "technique" or feature.get("double") is not True:
        return False
    tags = feature.get("double_for")
    if not isinstance(tags, list) or not tags or not all(isinstance(tag, str) and tag in {"structure", "unattended"} for tag in tags):
        return False
    area = mechanic.get("area") or {}
    if not isinstance(area, dict) or area.get("shape") not in {"sphere", "cone", "line", "cube", "cylinder"}:
        return False
    if type(area.get("size_ft")) is not int or area["size_ft"] <= 0:
        return False
    if activation.get("economy") not in {"action", "bonus_action"}:
        return False
    first = _first_damage(mechanic.get("effects"))
    if first is None:
        return False
    dice = first["dice"]
    return type(dice.get("count")) is int and dice["count"] > 0 and type(dice.get("sides")) is int and dice["sides"] >= 2 \
        and isinstance(first.get("damage_types"), list) and bool(first["damage_types"]) \
        and all(isinstance(kind, str) and kind for kind in first["damage_types"])


def _source_references(root: Path, relative: str, *symbols: str) -> list[str]:
    """Locate top-level handlers without stale copied line numbers.

    Parsing source never imports a combat module. Every requested symbol must
    identify one function.
    """
    functions = {}
    for node in ast.parse((root / relative).read_text()).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in functions:
                raise ValueError(f"Ambiguous function: {relative}:{node.name}")
            functions[node.name] = node.lineno
    return [f"{relative}:{functions[name]}" for name in symbols]


def verified_components(mechanic_id: str, mechanic: dict[str, Any], feature: dict[str, Any],
                        repo_root: Path) -> list[dict[str, Any]]:
    """Return component evidence, never a REAL_FULL classification.

    The caller supplies the actual mechanic and winning feature spec.  This
    function independently verifies the feature winner using the engine's
    sorted last-file-wins rule.  No ID whitelist or prose interpretation is
    used. Source fingerprints describe the current files.
    """
    if not isinstance(mechanic, dict) or not isinstance(feature, dict) or mechanic.get("mechanic_id") != mechanic_id:
        return []
    block = feature.get("block")
    if not isinstance(block, str) or block not in _FAMILY_FILES or not _shape_supported(block, mechanic, feature):
        return []
    root = Path(repo_root).resolve()
    winner = _winning_feature(root, mechanic_id)
    if winner is None or winner[0] != feature:
        return []
    source_files = {}
    try:
        for path in (*_COMMON, *_FAMILY_FILES[block]):
            source_files[path] = hashlib.sha256((root / path).read_bytes()).hexdigest()
    except OSError:
        return []
    evidence = [winner[1],
                *_source_references(root, "APP/combat/typed_reactions.py", "rules", "compile_blocks", "_rows"),
                *_source_references(root, "APP/combat/ext/__init__.py", "hook", "run", "run_strict")]
    limitations = [
        "A component implementation is verified in eligible ordinary contexts; complete printed-rule fidelity is not established.",
        "No fight was run. Availability, all choices, all plug-in interactions, and every saved character configuration remain unverified.",
        "Covers text is not execution proof and residual reminders are not retired by this component assessment.",
    ]
    if block == "object_damage":
        name = "Area damage to qualifying map objects"
        reason = ("The matching feature compiles an object_damage passive while keeping the ordinary action. "
                  "After an eligible area technique runs, the consumer matches its exact source to that passive, "
                  "finds reachable map objects, and applies a double-damage multiplier for the declared structure/unattended tags.")
        evidence += [*_source_references(root, "APP/combat/ext/objects.py", "_compile_block", "_rows",
                                        "_first_damage", "area_reaches", "_technique_row", "_struck", "technique_used"),
                     *_source_references(root, "APP/combat/object_rules.py", "has_tag", "work_out"),
                     *_source_references(root, "APP/combat/typed_executor.py", "resolve_typed")]
        limitations += ["Limited to nonweapon area techniques and living map-object records with HP/AC in the resolved area; wall areas and abstract barriers are outside this proof.",
                        "Damage thresholds, immunities and other defenses can still reduce damage to zero; this is not unconditional HP loss.",
                        "Terrain creation, clearing, creature effects, exact damage-type choice semantics and every printed object category remain separately unverified."]
    elif block == "grounding_breath":
        name = "Conditional Grounding Breath save bonus"
        reason = ("The matching feature compiles an ownership marker. The typed-save dispatcher supplies named failed-save effects; "
                  "the registered consumer checks that marker and the usage flag, recognizes supported shock/condition cases, "
                  "and adds the subject's proficiency bonus through the save-modifier accumulator.")
        evidence += [*_source_references(root, "APP/combat/ext/lightning_grounding.py",
                                        "grounding_breath_block", "_owns", "grounding_breath"),
                     *_source_references(root, "APP/combat/typed_executor.py", "typed_save_modifiers", "_save_each")]
        limitations += ["Only named typed-save cases supported by the dispatcher are covered; damage types still awaiting a choice may not qualify.",
                        "Optional consent, prevention of an already-counted proficiency bonus and all flag-reset/lifecycle cases are not certified by this component proof."]
    else:
        name = "Demon Seed turn-start resource-funded healing"
        reason = ("The matching feature compiles an ownership marker with the character's key modifier. The strict turn-start dispatcher "
                  "reaches a consumer that checks living/injured state, one available Devoured Essence and the Demon Seed stance; "
                  "an accepted spend choice invokes one resource spend and 1d8-plus-key-modifier healing.")
        evidence += [*_source_references(root, "APP/combat/ext/ironroot_daemonic.py",
                                        "compile_demon_bone_regen", "_row", "demon_bone_regeneration"),
                     *_source_references(root, "APP/combat/ext/spend_choice.py", "choose_spend"),
                     *_source_references(root, "APP/combat/typed_reactions.py", "on_turn_start")]
        limitations += ["An eligible owned stance/resource configuration and the ordinary choice transport are prerequisites.",
                        "Out-of-combat limb regrowth, narrative consequences and interactions with other healing interceptors remain outside this proof."]
    return [{"status": "VERIFIED_COMPONENT", "component_name": name, "block": block,
             "mechanic_id": mechanic_id, "reason": reason, "evidence": sorted(set(evidence)),
             "limitations": limitations, "implementation_fingerprint": {
                 "algorithm": "sha256", "source_files": source_files,
                 "winning_feature_file_sha256": winner[2], "feature_spec_sha256": _digest(feature),
                 # Stored coverage is the label this audit is checking.  It
                 # cannot change the component proof or its input fingerprint.
                 # All remaining record content stays in this explicit digest.
                 "mechanic_without_coverage_sha256": _digest({key: value for key, value in mechanic.items() if key != "coverage"}),
             }}]
