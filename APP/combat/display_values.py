"""Read combat display numbers from the same engine calculations used by combat.

The table and its connected character sheet share these values; presentation code
must not reconstruct modifiers from the character's unmodified sheet.
"""

from __future__ import annotations

from typing import Any
import logging
import json
import threading

_log = logging.getLogger(__name__)
_logged_display_formula_errors: set[str] = set()


def display_formula_value(name: str | None, numbers: dict[str, Any], *,
                          attack_ability_modifier: int | None = None) -> int:
    """Resolve known typed formula bonuses using only the actor's compiled numbers.

    Uses the execution context's shared, pure static formula lookup;
    it deliberately emits no combat events and rejects unknown formulas.
    ``attack_ability_modifier`` is the delivered weapon's own ability modifier -- the
    value execution uses for "attack_ability_modifier" -- so a printed chip shows the
    number combat rolls rather than the key-ability fallback.
    """
    from .typed_executor import static_formula
    value, _rest = static_formula(name, numbers, attack_ability_modifier=attack_ability_modifier)
    if value is not None:
        return value
    raise ValueError(f"unresolved display formula: {name}")


def log_display_formula_once(formula: str, error: Exception) -> None:
    """Log each unsupported display formula once per process."""
    if formula not in _logged_display_formula_errors:
        _logged_display_formula_errors.add(formula)
        _log.warning("Could not format combat damage formula %r: %s", formula, error)


def effective_defenses(engine: Any, actor: Any) -> dict[str, int]:
    """Return effective AC using the engine's attack-resolution modifier hook."""
    return {"armor_class": int(actor.armor_class) + int(engine._ac_modifier(actor))}


def effective_movement(engine: Any, actor: Any) -> int:
    """Return the engine's current walking Speed, including load and active effects."""
    return int(engine._effective_speed(actor))

_AC_CACHE: dict[tuple[str, str], dict[str, Any]] = {}
_AC_CACHE_LOCK = threading.Lock()


def armor_class_display(owner_sheet: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    """Return the compiled AC and an owner-readable explanation without changing combat state."""
    value = int((bundle.get("actor_template") or {}).get("armor_class") or 10)
    statistics = owner_sheet.get("ability_scores_and_statistics") or {}
    baseline_row = statistics.get("armor_class") or {}
    if isinstance(baseline_row, str):
        try:
            baseline_row = json.loads(baseline_row)
        except (TypeError, ValueError):
            baseline_row = {}
    baseline = baseline_row.get("value") if isinstance(baseline_row, dict) else baseline_row
    delta = value - int(baseline) if baseline is not None else 0
    explanation = "Combat Armor Class includes the armor your character wears, its refinement, and any qualifying paired-weapon bonus."
    if baseline is not None and delta:
        explanation += f" The sheet's starting value is {baseline}; those compiled equipment bonuses change it by {delta:+d}."
    return {"value": value, "tooltip": explanation,
            "breakdown": {**(baseline_row if isinstance(baseline_row, dict) else {}),
                          "worn_note": (bundle.get("carrying") or {}).get("armor_note") or (baseline_row.get("worn_note") if isinstance(baseline_row, dict) else None),
                          "effective_value": value, "combat_terms": bundle.get("armor_terms") or []}}


def compiled_armor_class(project_id: str, tabletop: Any) -> dict[str, Any]:
    """Return compiled AC for a Factory character, cached by its installed package and table inputs.

    The package digest plus owner item/button inputs form the character revision key. The
    full combat bundle is compiled only on a cache miss; this display seam is safe for sheet GETs.
    """
    from app.core import sha256_file, sha256_json

    package = tabletop.combat.combatant_library.install_root / project_id / "current.zip"
    package_hash = sha256_file(package)
    buttons = tabletop.buttons.get(project_id)
    from factory_authoring.owner_items import OwnerItemStore

    items = OwnerItemStore(tabletop.combat.userdata_root / "owner_items").items(project_id)
    revision = sha256_json({"package": package_hash, "buttons": buttons, "owner_items": items})
    cache_key = (project_id, revision)
    with _AC_CACHE_LOCK:
        cached = _AC_CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)
    owner_sheet, bundle, _summary = tabletop._bundle_and_summary(project_id)
    value = armor_class_display(owner_sheet, bundle)
    with _AC_CACHE_LOCK:
        if len(_AC_CACHE) >= 128:
            _AC_CACHE.pop(next(iter(_AC_CACHE)))
        _AC_CACHE[cache_key] = dict(value)
    return value
