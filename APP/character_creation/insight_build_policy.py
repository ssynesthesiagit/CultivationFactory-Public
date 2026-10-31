"""Build advice shared by guided menus, Stage plans and seeded generation.

This is an automatic-build preference, not an acquisition rule. Menus and
Stage 2 still enforce printed prerequisites and exactly one branch per level;
owner-selected ability improvements are never replaced.
"""

from functools import lru_cache
import json
from pathlib import Path
import re


@lru_cache(maxsize=1)
def printed_insight_rules():
    """Owner rules used for advice when frozen choices carry short summaries."""
    return json.loads((Path(__file__).resolve().parents[1] / "authority/typed_mechanics/rules_text.json").read_text())


def sphere_attack_abilities(sphere_ids):
    """Explicit actor attack/DC formulas in owned base Sphere rules.

    Shared by automatic menu ranking and the portable audit. Target saving
    throw names and Dao flavor are not actor ability requirements. Only printed
    formulas count; unknown or Path-key formulas keep the Path fallback.
    """
    names = {"Strength": "STR", "Dexterity": "DEX", "Constitution": "CON",
             "Intelligence": "INT", "Wisdom": "WIS", "Charisma": "CHA"}
    prefixes = {sphere.split(".")[-1].upper() + "_BASE_" for sphere in sphere_ids
                if sphere.startswith("tianxia.sphere.")}
    if not prefixes:
        return set()
    result = set()
    for rule_id, text in printed_insight_rules().items():
        if not any(rule_id.startswith(prefix) for prefix in prefixes):
            continue
        for paragraph in text.split("\n\n"):
            if not re.search(r"(?:save dc|escape dc|attack roll|attack modifier)", paragraph, re.I):
                continue
            for line in paragraph.splitlines():
                if "+" in line:
                    result.update(names[name] for name in re.findall(
                        r"\b(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma) modifier\b", line))
    return result


AUTOMATIC_INSIGHT_ADVICE = (
    "Use 27-point buy (8–15): put 15 in the Path attack/save ability, then support "
    "owned Sphere attacks/save DCs and defenses. Honor owner locks. At CL4/8/12/16/19, "
    "when the main uncapped ability is odd or one below the Realm cap, +1 gives the "
    "same modifier as +2: take an eligible Cultivation Insight listing it whose benefit "
    "the build uses (owned Sphere/Path, its resource, or combat). Otherwise focus +2 on "
    "the main attack/save ability until capped, then used secondary abilities. Follow "
    "the recommended choice and record why. Choose one branch only. Origin Insights "
    "give no level-selection +1. Owner choices win."
)


MECHANICAL_BUILD_STEPS = frozenset({"point_buy_preset", "point_buy_assignment", "background_ability",
                                  "asi_or_insight", "asi_milestone", "insight_occurrence"})


def recommended_build_option(menu, *, model_choice=False):
    """One mechanical recommendation for seeded and model-driven auto builds.

    Menus already apply source legality, owner locks, caps and causal access.
    This chooses within that proven menu; it never rewrites an owner lock or
    an accepted plan. For model-driven starting scores and Background bonuses,
    the concept-informed legal proposal wins over the deterministic fallback.
    Seeded generation still uses the recommendation when no model is present.
    """
    if menu.step_kind not in MECHANICAL_BUILD_STEPS:
        return None
    if model_choice and menu.step_kind in {"point_buy_preset", "point_buy_assignment", "background_ability"}:
        return None
    return next((option for option in menu.options
                 if option.choice_ids and not option.is_continuation), None)


def build_choice_reason(menu, option, detail=None):
    """Plain, persistent explanation of the automatic mechanical choice.

    ``detail`` is the step-specific reason from the shared menus
    (``mechanical_choice_detail``); the option cue is the fallback.
    """
    reasons = {
        "point_buy_preset": "Spend 27 points on a score spread that fits the character's concept and abilities.",
        "point_buy_assignment": "Assign scores for the character's attacks, skills and defenses, including Path and Sphere abilities.",
        "background_ability": "Direct the background's legal bonus to an ability the character uses.",
        "asi_or_insight": "Take a useful Insight when its +1 matches the increase's modifier gain; otherwise focus the normal increase.",
        "asi_milestone": "Concentrate on the attack/save ability until its cap, then support other used abilities.",
        "insight_occurrence": "Take the Insight whose benefit the build uses and put its +1 on the next ability to raise.",
    }
    return reasons.get(menu.step_kind, "Select a legal build option.") + " " + (detail or option.cue)


# Shared, data-driven evidence that a character will use an Insight's printed
# benefit.  Tiers rank the evidence; none of them is an acquisition rule.
INSIGHT_USE_TIERS = {"synergy": 3, "path": 2, "resource": 2, "combat": 1}
PATH_RESOURCES = {
    "tianxia.path.qi_cultivation": "Qi",
    "tianxia.path.body_refining": "Stamina",
    "tianxia.path.spirit_awakening": "Resonance",
}
# Every owned Sphere talent is activated with Cultivation Points.
SPHERE_RESOURCE_PATTERN = r"\bCP\b|Cultivation Points?"
# Paragraphs about downtime, travel, training, pills, spirit stones or hours-long
# procedures are not combat or resource use. A benefit is downtime-only when
# no other paragraph shows use; mixed benefits keep their combat/resource use.
DOWNTIME_BENEFIT_PATTERN = (r"downtime|while traveling|training|\bpills?\b|spirit stones?|\bgp\b|"
                            r"Cultivation Checks? (?:made )?to\b|uninterrupted hours|session (?:immediately )?fails")
# A sentence that only forbids something ("It never functions during
# Initiative", "you cannot take Reactions") is a restriction, not a use. A
# session-based recharge or expiry ("before your next Full Cultivation Session")
# is not downtime: the benefit itself is still used in play.
RESTRICTION_PATTERN = r"\b(?:cannot|can't|never|does not|do not|fails?)\b"
COMBAT_USE_WORDS = {"attack roll": "attack rolls", "saving throw": "saving throws", "armor class": "Armor Class",
                    "ac": "Armor Class", "damage": "damage", "hit points": "Hit Points", "temporary hp": "temporary Hit Points",
                    "initiative": "initiative", "reaction": "Reactions", "bonus action": "Bonus Actions",
                    "resistance": "resistance"}
_SYNERGY_KINDS = {"sphere", "talent", "subpath", "tradition"}
_REALM_WORDS = ("mortal", "foundation", "core formation", "nascent soul", "realm")


def _words(value):
    return " ".join(re.sub(r"^tianxia\.(?:sphere|path|subpath|tradition|talent)\.|[._\-]+|\bsphere\b", " ",
                           str(value).lower()).split())


def _printed_text(row):
    text = row.get("full_rules_text") or row.get("description") or ""
    if row.get("source"):
        text = printed_insight_rules().get(row.get("choice_id") or row.get("record_id"), text)
    return text


def unverified_prerequisites(row, present_ids):
    """Printed prerequisite clauses the build cannot show it meets.

    Typed prerequisites are enforced by the menus. A printed clause that names
    nothing typed or owned (a bond, a package, a feature) is unverifiable, so an
    automatic build does not recommend the Insight; owners may still pick it.
    """
    match = re.search(r"\*\*Prerequisites?:\*\*\s*([^\n]*)", _printed_text(row))
    if not match:
        return []
    known = [_words(relation.get("target_id")) for relation in row.get("prerequisites") or []
             if isinstance(relation, dict) and relation.get("target_id")]
    known += [_words(value) for value in present_ids]
    missing = []
    for clause in re.split(r",|;|\band\b", match.group(1).rstrip(". ")):
        clause = _words(re.sub(r"\bCL\s*\d+\+?", "", clause, flags=re.I))
        if not clause or any(word in clause for word in _REALM_WORDS):
            continue
        options = [option.strip() for option in re.split(r"\bor\b", clause) if option.strip()]
        if not any(name and (option in name or name in option) for option in options for name in known):
            missing.append(clause)
    return missing


def insight_use(row, present_ids, names=None):
    """``(tier, reason)`` when the build will use the printed benefit, else None.

    Shared by the linear menus and the read-only build audit. Owned Sphere,
    Talent, Subpath or Tradition prerequisites prove synergy; a typed Path
    prerequisite proves Path synergy; a resource the build has, or a combat
    statistic, proves use. A +1 alone, an unverifiable printed prerequisite or
    a downtime-only benefit is not use.
    """
    present = set(present_ids)
    authority = row.get("stage2_authority") or {}
    relations = list(row.get("prerequisites") or []) + list(row.get("parent_relationships") or [])
    synergy = set(authority.get("owning_canonical_sphere_ids") or [])
    paths = set()
    for relation in relations:
        if isinstance(relation, dict) and isinstance(relation.get("target_id"), str):
            if relation.get("kind") in _SYNERGY_KINDS:
                synergy.add(relation["target_id"])
            elif relation.get("kind") == "path":
                paths.add(relation["target_id"])
    # Strip the score and access paragraphs: those are not cultivation benefits.
    paragraphs = [paragraph for paragraph in _printed_text(row).split("\n\n")
                  if paragraph.strip(" -*#\n") and not any(word in paragraph.lower() for word in
                                                         ("ability increase", "prerequisite", "repeatable"))]
    if not paragraphs or unverified_prerequisites(row, present):
        return None
    downtime = [paragraph for paragraph in paragraphs if re.search(DOWNTIME_BENEFIT_PATTERN, paragraph, re.I)]
    active = " ".join(sentence for paragraph in paragraphs if paragraph not in downtime
                      for sentence in re.split(r"(?<=[.;])\s+|\n", paragraph)
                      if not re.search(RESTRICTION_PATTERN, sentence, re.I))
    use = _active_use(active, present)
    if synergy:
        owned = sorted(synergy & present)
        if not owned or (downtime and use is None):
            return None  # Not owned, or a downtime-only project/training benefit.
        name = (names or {}).get(owned[0]) or _display_words(owned[0])
        return INSIGHT_USE_TIERS["synergy"], f"builds on your {name}" + (f"; {use[1]}" if use else "")
    if use is not None and paths & present:
        # Path synergy ranks above generic use, but still needs a used benefit.
        path = sorted(paths & present)[0]
        name = (names or {}).get(path) or _display_words(path)
        return INSIGHT_USE_TIERS["path"] + 0.5, f"{name} Path; {use[1]}"
    return use


def _display_words(value):
    """Readable fallback for an id with no display row (never a raw code name)."""
    return _words(re.sub(r"^TAL_", "", str(value))).title()


def _active_use(text, present):
    """``(tier, plain description)`` of a resource or combat use, else None."""
    for path, resource in PATH_RESOURCES.items():
        if path in present and re.search(r"\b" + resource + r"\b", text, re.I):
            return INSIGHT_USE_TIERS["resource"], f"uses your {resource}"
    owns_sphere = any(value.startswith("tianxia.sphere.") for value in present)
    if owns_sphere and re.search(SPHERE_RESOURCE_PATTERN, text):
        return INSIGHT_USE_TIERS["resource"], "spends or restores Cultivation Points for your Sphere talents"
    found = [label for word, label in COMBAT_USE_WORDS.items()
             if re.search(r"\b" + re.escape(word) + r"s?\b", text, re.I)]
    if found:
        return INSIGHT_USE_TIERS["combat"], "in combat: " + ", ".join(dict.fromkeys(found[:2]))
    return None


def used_insight_benefit(row, present_ids, names=None):
    """Compatibility wrapper used by the read-only audit."""
    return insight_use(row, present_ids, names) is not None


def _modifier(score):
    return (score - 10) // 2


def focused_increase(scores, priority, cap, budget=2):
    """The normal increase the ASI menu ranks first (concentrate by priority)."""
    after = dict(scores)
    for ability in priority:
        while budget and after.get(ability, cap) < cap:
            after[ability] += 1
            budget -= 1
    return after


def advancement_target(scores, priority, cap):
    """The ability a level increase should raise next: the first uncapped one."""
    return next((ability for ability in priority if scores.get(ability, cap) < cap), None)


def branch_advice(scores, priority, cap, useful_by_ability):
    """``(take_insight, reason)`` for one ASI-or-Insight level.

    ``useful_by_ability`` maps an ability to the best useful legal Insight
    listing it, as ``(tier, name, why)``. An Insight is preferred when its +1
    gives the main uncapped ability the same modifier the ASI would: the ASI's
    extra point could only reach a lower-priority ability.
    """
    target = advancement_target(scores, priority, cap)
    if target is None:
        return False, "Every used ability is at the Realm cap; take the normal increase."
    score = scores[target]
    asi_gain = _modifier(focused_increase(scores, priority, cap)[target]) - _modifier(score)
    insight_gain = _modifier(score + 1) - _modifier(score)
    best = useful_by_ability.get(target)
    if best and insight_gain >= asi_gain:
        tier, name, why = best
        # The Insight step names the exact Insight; ties may resolve differently.
        return True, (f"{target} {score}→{score + 1} gives the same modifier as +2; "
                      f"an eligible Insight listing {target} adds a used benefit ({why}).")
    if best:
        return False, f"+2 {target} {score}→{score + 2} raises its modifier; an Insight's +1 would not."
    return False, f"No eligible Insight with a used benefit lists {target}; focus the increase."
