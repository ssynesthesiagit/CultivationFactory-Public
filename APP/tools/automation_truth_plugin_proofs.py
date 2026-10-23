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
# A2SPIRITr2 reviewed the general source-reduction/admission seams and the
# packet-bound transfer helper. Default packets remain eligible; recipient
# defense and commit suppress recursion without suppressing fresh damage.
# Pin the new helper dependency. Existing component validators are unchanged.
# P20261010-09 adds the read-only authority helper as a compiler dependency.
# After merging main, regenerate pins against the merged dependency bytes.
# This refresh does not certify action availability or expand proof shapes.
_REVIEWED_REF = "53a1e4095f95d038206cfb72efa40855e7f51c91"
# Prior SOL138r3 review, c21b1892 against first parent 179ba77f: compiler scopes final
# area delivery; executor filters harmful recipients and carries explicit self
# scope; reactions share nested harm/recipient semantics; ext adds pure harm
# metadata and documents fight-bound targeting. Ordinary compile_block dispatch,
# object doubling, Grounding and regeneration consumers retain their semantics.
# New area policy dependencies are pinned alongside the changed dispatchers.
# Whole-file drift continues to fail closed, including same-size/mtime edits.
_REVIEWED_SHA256 = {
    "APP/combat/ext/__init__.py": "2d8f6d8abd1cd3ef9a8e817987ce138ab4af9328b522e7415170881872b5073a",
    "APP/combat/factory_compiler.py": "72d77160eca15b9723112b1d0db226f357ed1ad08002f9e81a23a6915ac810cd",
    "APP/combat/authority_cache.py": "c680f761b410e027b45cd1d26d66b7d98d02f88e565bbfde1562e8a166c12f3f",
    "APP/combat/typed_reactions.py": "8589bea1a0c29f6bba8da74432fd3f0d37e56ce1419d6f6cc874dc4b5f941ba9",
    "APP/combat/ext/damage_transfer_scope.py": "d90bc10db23eecaa683d31da4e7839aa22c99a32ea20755aa6171d0d45a7e1d6",
    "APP/combat/typed_executor.py": "aa359870c279c45b7f98cef8231b26ca8d01cfb19c69d0e0aed2f38675d40098",
    "APP/combat/area_recipients.py": "80e8576fd7f18f5910544c6ba10a01e16fd74b05cd9ac590c888149c7a210b61",
    "APP/combat/area_recipient_rules.py": "e9024b0933c7ec13b3552eab889dababdd349ddb2a554839f211759041b275b5",
    "APP/combat/effect_harm.py": "30b7e947a9f34e12c53243d5b835b50dfbcaefa5965996e2432b87049f02858c",
    "APP/combat/rules/area_recipient_overrides.json": "faefb22fb5ae2f7ca5dcb8bd973e33d3dd7829e6fbaa2ff0e1ed07aba784601d",
    "APP/combat/ext/objects.py": "475e0196f9a9027e2a6f41740446e4ad1dba16f89da25672582589584fb577b1",
    "APP/combat/object_rules.py": "7d266587d8bf44e912843e33da97db3ce1fc12434e37a09c2ee66abed4654053",
    "APP/combat/ext/lightning_grounding.py": "5ef015ccf14913c6045e6b68fc6c420cb84d42fa88b8a1697d72d51886a1b6fb",
    "APP/combat/ext/ironroot_daemonic.py": "23d40fdfb5a0ea1c20bb4dfaaa1d7cae668a3279900653d494aea17ad7205633",
    "APP/combat/ext/spend_choice.py": "be385a9f74aacb1e015babaf4b5896eb0cd0b1fbbccabde4718f52485e85f677",
}
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
