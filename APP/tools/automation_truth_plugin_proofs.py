"""Reviewed component proofs for three bounded plug-in block shapes.

These are source proofs of an executable component in an eligible ordinary
context, not whole-ability fidelity or runtime tests.  Exact source hashes bind
the review to this implementation.  Missing sources, source drift, a nonwinning
feature row, and unreviewed spec shapes all fail closed with no proof.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any


# SOL158 re-reviewed merged compiler prerequisite/zone-duration metadata,
# default-inert strike/forced-movement/DC hooks, effective resistance queries,
# object aura defenses and prompt-only spend metadata against main 2ea534d8.
# Bounded object, Grounding and regeneration consumers retain their contracts.
# Regenerate existing pins with tools.build_automation_truth_pins after review.
# B3F3r1 re-reviewed the executor's explicit self speed and named-DC fixes.
# Compiler, recipient/harm policy, object, Grounding and regeneration consumers
# are byte-unchanged; their bounded forms and fail-closed checks remain intact.
_REVIEWED_REF = "24e02f0769df7119ffe21862741d3eb9035c7ae6"
# Prior SOL138r3 review, c21b1892 against first parent 179ba77f: compiler scopes final
# area delivery; executor filters harmful recipients and carries explicit self
# scope; reactions share nested harm/recipient semantics; ext adds pure harm
# metadata and documents fight-bound targeting. Ordinary compile_block dispatch,
# object doubling, Grounding and regeneration consumers retain their semantics.
# New area policy dependencies are pinned alongside the changed dispatchers.
# Whole-file drift continues to fail closed, including same-size/mtime edits.
_REVIEWED_SHA256 = {
    "APP/combat/ext/__init__.py": "917cd83c22d6bda41880f9db82ef4756fdff62fca13054131ef175f606469dab",
    "APP/combat/factory_compiler.py": "9e51bada0e4fc9ca7b97c1a27acd5d4accd28f204c0971d32b3e9f561eebc646",
    "APP/combat/typed_reactions.py": "b367702250c05cc8d55ed815badc35f3adcc7b8252e80102a598ce6c08ecfa17",
    "APP/combat/typed_executor.py": "9e5af942decd14b776be1e1e9b904f1c324bf89ad3ab186143d21484eeb4517d",
    "APP/combat/area_recipients.py": "b81f7083d8ddc7d6ae9c9faf536582325051913727a9bc719835c453989c99af",
    "APP/combat/area_recipient_rules.py": "f78adb022c5ff2a1aa4ce8a6c536e3013698f4b538592f7659a4706db9186730",
    "APP/combat/effect_harm.py": "c8cca8bae89fb8a516cb9f31993a4a7bf172ccf6f1c427dbe551be5e967c1401",
    "APP/combat/rules/area_recipient_overrides.json": "3e678aea5d424fbb3ed3de09bc3228f51d54bb21116c7b81fd9bcf0c811412dc",
    "APP/combat/ext/objects.py": "44173088a00272a7c11ae48e24e7a852117db2c63b73f7273a59d373a7b8889b",
    "APP/combat/object_rules.py": "fdcd2e3e8f0ae5269e1b5d3f7d8c790fb0e3baa50e9901632b1494d23aedab17",
    "APP/combat/ext/lightning_grounding.py": "af766f8ee8de74f6b9be84eb3a7b5b301a2319ae3ad427c18347aa5b56ec78de",
    "APP/combat/ext/ironroot_daemonic.py": "0d6108b1fb482884e0695d8acb8d21182104d88e2b7c0580014302f08c999f4e",
    "APP/combat/ext/spend_choice.py": "4f65ab13c8c013a63f78d8db6d05c0eec9bf704ca86a8d233bad8f50f4ba0a41",
}
_COMMON = (
    "APP/combat/ext/__init__.py", "APP/combat/factory_compiler.py",
    "APP/combat/typed_reactions.py", "APP/combat/typed_executor.py",
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
    """Locate reviewed top-level handlers without stale copied line numbers.

    Call only after the dependency hashes match. Parsing source never imports
    a combat module. Every requested symbol must identify one function.
    """
    functions = {}
    for node in ast.parse((root / relative).read_text()).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in functions:
                raise ValueError(f"Ambiguous reviewed function: {relative}:{node.name}")
            functions[node.name] = node.lineno
    return [f"{relative}:{functions[name]}" for name in symbols]


def verified_components(mechanic_id: str, mechanic: dict[str, Any], feature: dict[str, Any],
                        repo_root: Path) -> list[dict[str, Any]]:
    """Return reviewed component evidence, never a REAL_FULL classification.

    The caller supplies the actual mechanic and winning feature spec.  This
    function independently verifies the feature winner using the engine's
    sorted last-file-wins rule.  No ID whitelist or prose interpretation is
    used.  Source hashes are re-read on each eligible call, so even changes
    preserving a file's size and timestamp invalidate the review.
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
            actual = hashlib.sha256((root / path).read_bytes()).hexdigest()
            if actual != _REVIEWED_SHA256[path]:
                return []
            source_files[path] = actual
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
                                        "_first_damage", "_reaches", "_technique_row", "_struck", "technique_used"),
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
