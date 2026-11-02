"""Forging design policy, shared by construction, combat assembly and offline audit.

Owner 2026-10-15: one initial resolution buys the payoff. PHB ch.18 still
requires a save for hostile conditions, so such designs replace the attack
with a save; they never grant automatic hostile conditions on a hit.
Source rows and existing character records are never edited in place.
"""
from copy import deepcopy

POLICY = "single_resolution_v1"
BRANCHES = ("on_hit", "on_fail", "on_success", "effects", "then")
SEVERE = {"stunned", "paralyzed", "incapacitated"}
GATES = {"attack", "save", "check", "ability_check", "skill_check", "contest", "contest_against",
         "check_against", "sphere_check", "scoundrel_check", "sect_check", "unmaking_object_check", "roll_die"}
# Fields an ordinary save wrapper may carry. A nested save that repeats its
# enclosing save's ability, DC and scope folds into one roll; any other field
# (e.g. requires_mark) is a source-specific contract that must be preserved, so
# such a save is kept as a separate gate rather than silently folded.
_ORDINARY_SAVE_FIELDS = {"type", "ability", "dc", "applies_to", "on_fail", "on_success", "repeat_save"}
# The engine's default save scope: a save that names no applies_to is rolled
# against the creature it was delivered to, exactly like an explicit "target".
DEFAULT_SAVE_SCOPE = "target"
# An area delivery already selected these creatures; a nested save whose scope
# is the default "target" resolves against that same selected subject.
AREA_SAVE_SCOPES = {"creatures_in_area", "enemies_in_area", "allies_in_area"}


def _same_difficulty(child_dc, enclosing_dc):
    """True when a nested save inherits its enclosing save's difficulty.

    A save that names no ``dc`` uses the action's Save DC at the table, the same
    threshold the enclosing save rolls against, so an omitted DC is inheritance
    (the Lava Spit rider), not a distinct difficulty.
    """
    return child_dc is None or child_dc == enclosing_dc


def _same_recipients(child_scope, enclosing_scope):
    """True when a nested save rolls against the creatures its parent selected.

    An omitted scope is the default single target. Under an area delivery that
    target is the subject the enclosing save already failed or saved, because
    the failure branch runs per recipient.
    """
    if child_scope is None or child_scope == enclosing_scope:
        return True
    return child_scope == DEFAULT_SAVE_SCOPE and enclosing_scope in AREA_SAVE_SCOPES


def walk(rows):
    for row in rows or []:
        yield row
        for key in BRANCHES:
            yield from walk(row.get(key, []))


def collapse_repeated_saves(rows):
    """Fold a save that repeats its enclosing save's ability into that one resolution.

    The typed-mechanics parser can emit a Lava Spit-style rider sentence ("The
    target makes a Dexterity saving throw. Failed Save: ...") as a second,
    nested save of the same ability. Printed rules have one roll there, so the
    nested failure branch joins the enclosing failure branch. Recovery saves
    (`repeat_save`), success branches and different abilities remain gates.
    """
    return _fold(rows or [], None, None, None)


def _fold(rows, enclosing, enclosing_dc, enclosing_scope):
    # An omitted enclosing scope means the engine's default target scope, so a
    # nested same-ability/same-DC save that spells out "target" is the same
    # recipient set and folds. Normalize once here; comparing raw values would
    # reject authored single-roll designs ("target" != None) that restructure
    # then combines, so validation would contradict the assembler.
    if enclosing is not None and enclosing_scope is None:
        enclosing_scope = DEFAULT_SAVE_SCOPE
    result = []
    for row in rows:
        if (row.get("type") == "save" and enclosing is not None
                and str(row.get("ability", "")).lower() == enclosing
                and _same_difficulty(row.get("dc"), enclosing_dc)
                and _same_recipients(row.get("applies_to"), enclosing_scope)
                and not _has_real_extras(row, _ORDINARY_SAVE_FIELDS)
                and not row.get("repeat_save") and not row.get("on_success")):
            result.extend(_fold(row.get("on_fail", []), enclosing, enclosing_dc, enclosing_scope))
            continue
        row = dict(row)
        if row.get("type") == "save":
            ability = str(row.get("ability", "")).lower() or None
            row["on_fail"] = _fold(row.get("on_fail", []), ability or enclosing,
                                  row.get("dc") if ability else enclosing_dc,
                                  row.get("applies_to") if ability else enclosing_scope)
            if row.get("on_success"):
                row["on_success"] = _fold(row["on_success"], None, None, None)
        else:
            for key in BRANCHES:
                if row.get(key):
                    row[key] = _fold(row[key], enclosing, enclosing_dc, enclosing_scope)
        result.append(row)
    return result


def design_issues(mechanic):
    """Return stable issue codes; repeat_save is recovery, not an initial gate."""
    issues = set()
    mechanic = dict(mechanic, effects=collapse_repeated_saves(mechanic.get("effects", [])))

    def visit(rows, depth=0):
        gates = [r for r in rows if r.get("type") in GATES]
        if len(gates) > 1:
            issues.add("independent_rider_gates")
        for row in rows:
            gate = row.get("type") in GATES
            if gate and depth:
                issues.add("stacked_gates")
            if row.get("condition") in SEVERE and not row.get("repeat_save"):
                issues.add("severe_without_recovery")
            if row.get("type") == "condition" and row.get("condition") in SEVERE and not (row.get("duration") or row.get("expires_on")):
                issues.add("severe_without_expiry")
            for key in BRANCHES:
                visit(row.get(key, []), depth + int(gate))
    visit(mechanic.get("effects", []))
    rows = list(walk(mechanic.get("effects", [])))
    meaningful = [r for r in rows if r.get("type") not in GATES | {"half_damage", "ignore_resistance"}
                  and (r.get("applies_to") != "self" or r.get("type") in {"movement", "teleport", "temp_hp", "healing", "resistance", "advantage"})]
    if not meaningful:
        issues.add("no_primary_payoff")
    cost = max((sum(int(c.get("amount") or 0) for c in option) for option in mechanic.get("cost", [])), default=0)
    if cost >= 4 and meaningful and all(
        (r.get("type") == "speed" and abs(int(r.get("flat") or 0)) <= 10)
        or (r.get("type") == "movement" and int(r.get("distance_ft") or 0) <= 10)
        for r in meaningful
    ):
        issues.add("weak_paid_payoff")
    return sorted(issues)


# Composer save rows also carry inert metadata (provenance, evidence, and default-valued fields such as
# flat 0, formula "none", no condition, instant duration). Those change nothing; a real rider does.
_INERT = {"evidence": None, "origin": None, "recipient_text": None, "flat": 0, "formula": "none", "damage_types": [],
          "condition": "none", "distance_ft": 0, "on": "", "duration": "instant"}


def _has_real_extras(row, allowed):
    return any(key not in allowed and (key not in _INERT or (_INERT[key] is not None and row[key] != _INERT[key]))
               for key in row)


def restructure(mechanic):
    """Combine ordinary composer saves into one resolution, preserving recovery.

    Distinct success branches, scoped saves, predicates and source-specific
    contracts are not flattened: validation rejects these for new designs.
    No dice, damage, conditions, costs or expiry names are invented here.
    """
    out = deepcopy(mechanic)
    out["effects"] = collapse_repeated_saves(out.get("effects", []))
    rows = out.get("effects", [])
    attacks = [r for r in rows if r.get("type") == "attack"]
    container = attacks[0].get("on_hit", []) if len(attacks) == 1 else rows
    saves = [r for r in walk(container) if r.get("type") == "save"]
    if not saves:
        return out
    # Only ordinary delivery wrappers can be combined without changing source
    # predicates. A success-only rider cannot become a failure rider.
    allowed = {"type", "ability", "dc", "applies_to", "on_fail", "on_success"}
    if any(_has_real_extras(r, allowed) or any(x.get("type") != "half_damage" for x in r.get("on_success", [])) for r in saves):
        return out
    # A carried ally benefit or attacker-specific trigger is not the enemy
    # selected by this save. Combining its branch with hostile riders would
    # change recipients or make healing contingent on an enemy failing a save.
    target_scopes = {None, "target", "creatures_in_area", "enemies_in_area"}
    if attacks and any(row.get("applies_to") not in target_scopes for row in walk(container)):
        return out
    if any(row.get("applies_to") not in target_scopes
           for saved in saves for row in walk(saved.get("on_fail", []))):
        return out
    scopes = {r.get("applies_to", "target") for r in saves}
    # A child target is the creature selected by its enclosing area save.
    # Sibling augment saves likewise share that delivery's recipients.
    if len(scopes) > 1:
        scopes.discard("target")
    if len(scopes) > 1:
        return out
    # Distinct DCs are distinct save difficulties: separate gates, not one roll.
    if len({r.get("dc") for r in saves}) > 1:
        return out

    def failure(rows):
        result = []
        for row in rows:
            if row.get("type") == "save":
                result.extend(failure(row.get("on_fail", [])))
            else:
                result.append(deepcopy(row))
        return result
    payoff = failure(container)
    # An attack containing weapon_damage depends on an attack roll's weapon
    # resolution; do not silently turn that into untyped save damage.
    if attacks and any(r.get("weapon_damage") for r in walk(payoff)):
        return out
    chosen = next((r for r in saves if any(x.get("condition") in SEVERE for x in r.get("on_fail", []))), saves[0])
    saved = {"type": "save", "ability": chosen["ability"], "dc": chosen.get("dc", "technique_save_dc"),
             "on_fail": payoff, "on_success": []}
    if scopes != {"target"}:
        saved["applies_to"] = next(iter(scopes))
    if any(r.get("type") in {"damage", "extra_damage"} for r in walk(payoff)):
        saved["on_success"] = [{"type": "half_damage", "applies_to": "target"}]
    if attacks:
        out["effects"] = [saved if r is attacks[0] else r for r in rows]
    else:
        # Preserve unconditional self costs/benefits outside the hostile save.
        own = [r for r in rows if r.get("applies_to") in {"self", "ally", "allies_in_area"}]
        saved["on_fail"] = failure([r for r in rows if r.get("applies_to") not in {"self", "ally", "allies_in_area"}])
        out["effects"] = [saved, *own]
    if attacks:
        # Only a converted attack makes the Base Form's wording ("Make a weapon
        # attack. On a hit, ...") untrue. Strike and projection forms never
        # carry aura/zone timing, so the save sentence can replace it outright.
        out["description"] = ["The target makes one saving throw against your Cultivation Save DC. On a failure, apply the technique's effects together; on a success, take half damage if any."]
    # Otherwise keep the composer's description untouched: the form's aura/zone
    # wording, "It moves with you." and Persistent Zone timing are executable
    # inputs (factory_compiler._zone_spec reads them for the area's persistence,
    # its enter/start trigger moments and whether it follows its owner), and
    # they stay true when the augment saves join the delivery save.
    return out
