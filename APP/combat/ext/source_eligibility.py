"""Shared reviewer of where a stored benefit came from, and whether a technique's own printed record
protects its effects (AUTO118r1f1).

These plug-ins ask the same underlying question and must get the same answer:

* ``combat/ext/qiweaving_unweave.py`` -- Unweave Pattern ends "an Active Qi Pattern" only. The owner's core
  rules forbid ending "Domains, secret inherited arts, long-term magical formation projects, artifact powers
  or campaign-scale magic" without explicit permission, and an effect whose source cannot be identified is not
  offered. That reader moved here unchanged in meaning; ``qiweaving_unweave._supported_source`` and
  ``_protected_classification`` are thin delegates to ``ordinary_source`` / ``protected_power`` here.
* ``combat/ext/end_effect.py`` -- Internal Hammer's printed "Choose one ongoing physical or martial effect
  affecting the target, such as a stance, guard, body enhancement, rage-like state, mobility technique, or
  temporary damage reduction", which its own rider limits to effects that "depend on the target's bodily or
  spiritual structure": "Internal Hammer does not suppress Domains, Secret Inheritances, permanent
  transformations, artifacts, or effects that do not depend on the target's bodily or spiritual structure."
  ``bodily_effect`` answers exactly that.

* ``combat/ext/yang_recovery.py`` -- Seal-Breaking Warmth repeats a save only for an ordinary
  attributed restriction; it also checks source level and its own printed exclusions.

All read the OWNER'S PRINTED RECORD (``combat/authority/typed_mechanics/rules_text.json`` by mechanic id) and
the technique's own typed source, never an ability's name or its catalogue key: a Domain, a Secret Inheritance,
a Formation project, an artifact or campaign-scale power is protected because its printed record says so, and
anything whose printed record cannot be read fails closed. Nothing here rolls, mutates a fight or is
plug-in specific; an ordinary creature that bears no stored benefit is never touched.
"""
from __future__ import annotations

import re
from typing import Any, Callable

# "Domain", "Secret Inheritance" (and the owner's "Secret Music / Formation / Unmaking Inheritance"),
# "Formation project", "artifact" / "artifact-level", "campaign-scale": the protected categories.
PROTECTED = re.compile(r"\b(?:Domain|Secret(?: \w+)? Inheritance|Formation project|artifact(?:[ -]level)?|campaign[ -]scale)\b", re.I)
DOMAIN_DECLARATION = re.compile(
    r"^(?:You\s+)?(?:establish|create)\s+a\s+(?:[\w-]+\s+){0,4}Domain"
    r"(?=[.,;]|$|\s+(?:of|in|where|centered|and|that|which)\b)", re.I)
_COST_PREFIX = re.compile(r"^Cost:\s*\d+\s+(?:CP|[\w-]+ Resource)\s+", re.I)
_CATEGORY_LINE = re.compile(r"^(?:Source Category|Effect Category|Pattern Type|Talent Type):", re.I)
# An effect with no expiry of its own never ends by itself: a permanent transformation, a class feature, a
# gift that is simply part of what the creature is. The same list the shared benefit_suppression helper
# (combat/ext/benefit_suppression.py) treats as permanent.
NO_ENDING = ("", None, "UNTIL_REMOVED")


def mechanic_of(action_id: Any) -> str:
    """The mechanic id a compiled action came from, with any "+variant" or "#mode" suffix removed."""
    parts = str(action_id or "").split(".", 2)
    return parts[2].split("+")[0].split("#")[0] if len(parts) == 3 else ""


def printed_text(mechanic_id: Any, rules: Callable[[], dict[str, str]] | None = None) -> str:
    """The owner's printed record for one mechanic id, or "" when there is none (unknown, never a licence).

    ``rules`` is the reader to use; the default is the shared ``qiweaving_common.rules_text``. A caller
    passes its own so a test can point this at a fixture record instead of the owner's file.
    """
    if not mechanic_id:
        return ""
    from .qiweaving_common import rules_text

    return (rules or rules_text)().get(str(mechanic_id), "")


def protected_power(typed: dict[str, Any], text: str, *, permanent_transformations: bool = False,
                    extra_categories: tuple[str, ...] = ()) -> bool:
    """Inspect the printed record's category lines and direct declarations of one power.

    Owner-authored headings and labelled category fields identify protected powers, as do direct
    "You establish a Weather Domain" declarations. The Spear source joins its declaration to its Cost field;
    strip only that printed cost prefix before applying the same anchored declaration grammar. Core
    Formation is a Realm, not a Formation project; mentioning a protected target, prerequisite or Domain
    Armament does not classify the source. Typed ``source_category`` / ``pattern_category`` fields may
    supply explicit categories. ``extra_categories`` lets a consumer add its own
    printed exclusions to this same category reader; absent extras retain the
    shared default. Yang Warmth adds Curse, Formation and Narrative Seal.
    """
    fields = [str(typed.get(key) or "").replace("_", " ") for key in ("source_category", "pattern_category")]
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#") or _CATEGORY_LINE.match(line):
            fields.append(line)
        elif line.startswith("**") and line.endswith("**") and ":" not in line:
            fields.append(line.strip("*"))
        if DOMAIN_DECLARATION.match(_COST_PREFIX.sub("", line)):
            return True
    extra = re.compile(r"\b(?:" + "|".join(re.escape(name) for name in extra_categories) + r")\b", re.I) if extra_categories else None
    return any(PROTECTED.search(field) or extra and extra.search(field) or permanent_transformations
               and re.search(r"\bpermanent transformations?\b", field, re.I) for field in fields)


def catalog_action(engine: Any, source_definition_id: Any) -> Any:
    """The compiled action that put an effect on a creature, following a zone or variant source suffix.

    An effect records the action id that applied it, which can carry a ":zone..." / ":own..." / "#..." suffix.
    The longest matching catalogue key is the technique, exactly as ``ability_source.source_label`` resolves a
    readable name for the same ids. None means the table cannot attribute this effect to any technique.
    """
    source = str(source_definition_id or "")
    action = engine.action_catalog.get(source)
    if action is not None:
        return action
    key = max((key for key in engine.action_catalog
               if source.startswith(key + ":") or source.startswith(key + "#")), key=len, default="")
    return engine.action_catalog.get(key) if key else None


def printed_power(action: Any, rules: Callable[[], dict[str, str]] | None = None) -> tuple[dict[str, Any], str] | None:
    """``(typed, printed record)`` for one compiled action, or None when it cannot be read.

    A basic action (an ordinary attack, a maneuver) is never a reviewed power: its printed record is the
    creature's own weapon or body, not an ability whose category the owner classified. So is an action whose
    mechanic id has no printed record at all -- that is an unknown, never a licence.
    """
    if action is None:
        return None
    parameters = getattr(action, "parameters", None) or {}
    typed = parameters.get("typed") or {}
    if not typed or parameters.get("basic"):
        return None
    text = printed_text(typed.get("source") or mechanic_of(getattr(action, "source_definition_id", "")), rules)
    return (typed, text) if text else None


def ordinary_source(action: Any, rules: Callable[[], dict[str, str]] | None = None) -> bool:
    """Whether one compiled action is an ordinary reviewed power a Qiweaver may end, failing closed.

    Protected categories (Domain, Secret Inheritance, Formation project, artifact, campaign-scale) and
    actions whose printed record cannot be read are not ordinary powers.
    """
    power = printed_power(action, rules)
    return bool(power) and not protected_power(*power)


def stored_power(engine: Any, source_definition_id: Any,
                 rules: Callable[[], dict[str, str]] | None = None) -> tuple[dict[str, Any], str] | None:
    """``printed_power`` for the technique that put a stored effect on a creature."""
    return printed_power(catalog_action(engine, source_definition_id), rules)


def ends_by_itself(item: Any) -> bool:
    """Whether a stored condition or modifier carries an expiry of its own.

    True for every represented lifetime the engine will age (``START_OF_SOURCE_NEXT_TURN``,
    ``CONCENTRATION_END``, ten rounds for "1 minute", ...); False for one that only ends when something removes
    it, which is what a permanent transformation, a class feature or an artifact's own gift looks like.
    """
    return str(getattr(item, "expires_on", "") or "") not in NO_ENDING


def bodily_effect(engine: Any, item: Any, rules: Callable[[], dict[str, str]] | None = None) -> bool | None:
    """Whether a stored benefit is one of the bearer's own temporary bodily or martial states.

    Internal Hammer's printed "Choose one ongoing physical or martial effect affecting the target, such as a
    stance, guard, body enhancement, rage-like state, mobility technique, or temporary damage reduction",
    read with its rider's limit to effects that "depend on the target's bodily or spiritual structure".

    * True -- an ordinary reviewed technique explicitly carries
      ``bodily_martial_effect: true`` on an effect row and the stored benefit
      ends by itself. This metadata classifies the source, not merely the stat
      it changes; it must be backed by the printed bodily/martial dependence.
    * False -- the printed record protects it (a Domain, a Secret Inheritance, a Formation project, an
      artifact or campaign-scale power), or it has no lifetime of its own, so it is part of what the creature
      permanently is rather than something its body is currently doing.
    * None -- the table cannot attribute the effect to a readable, explicitly classified technique, so it cannot answer. The caller
      keeps that a GM decision; the printed text never guesses.
    """
    if not ends_by_itself(item):
        return False
    power = stored_power(engine, getattr(item, "source_definition_id", ""), rules)
    if power is None:
        return None
    if protected_power(*power, permanent_transformations=True):
        return False
    # Ordinary magic is not automatically bodily/martial. Reviewed source data
    # must affirm the printed dependence; absence keeps the choice with the GM.
    return True if any(row.get("bodily_martial_effect") is True
                       for row in power[0].get("effects", ()) if isinstance(row, dict)) else None
