"""Shared reach helper for white_heron.py and the reach variant hooks; printed Body Refining increases.

"Unarmed reach +10 feet" (Calamity Briar Incarnation, for its duration), "While you have at least 1 Spine, unarmed reach
increases by 5 feet during your turn" (Crown of Black Thorns), "Reach increases by 5 feet during your turn" (Chain-Body
Integration), ... One typed row on the owning feature:

    {"type": "path_passive", "kind": "reach_bonus", "feet": 5, "attacks": "unarmed", "own_turn": true,
     "state": "calamity_briar_incarnation", "min_resource": ["resource:named.demon_spine", 1], "label": "Crown of Black Thorns"}

``attacks``: "unarmed" (unarmed strikes and natural weapons), "melee" (any melee attack), {"group": "chain"} (a weapon
proficiency group, combat/ext/integrated_weapons.in_group), or a list of weapon words matched against the action's name. ``own_turn``: only during the owner's turn (never for
Opportunity Attacks). ``state``: only while the owner has that named state (combat/ext/states.py). ``min_resource``: only
while the owner holds at least that many.

compile_actions adds one menu variant of each matching melee attack action. Its range is the maximum possible total, and
candidate_allowed plus attack_allowed use current_reach to offer and revalidate only the active combined reach.
Opportunity Attacks use the same calculation without an own-turn limit (opportunity_action). ``melee_reach`` answers the
printed "your reach" that is about the fighter rather than one named attack. Characters without a row
get nothing; the base actions are unchanged.

natural_reach_ft(engine, actor) -> int is this module's other public reader: how far the creature reaches with its own
body, in feet. "Natural reach" is a printed requirement several talents share ("talents requiring natural reach function
only if the target ends within natural reach", Brute's Get Over Here), so it is asked about the body rather than about one
action: current_reach restricted to the creature's own unarmed/natural attacks. A printed body increase is therefore
honoured wherever it shows up, and a weapon's reach or the range of the action being resolved is never natural reach.
"""

from __future__ import annotations

from typing import Any

from . import hook

KIND = "reach_bonus"
MARK = "reach_bonus"


def _rows(mechanics: dict[str, Any], owned: list[str]) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for mid in owned:
        for row in (mechanics.get(mid) or {}).get("effects") or []:
            if isinstance(row, dict) and row.get("type") == "path_passive" and row.get("kind") == KIND:
                out.append((mid, row))
    return out


def _variants(info: dict[str, Any], actions: list[Any], owned: list[str], skip: set[str] | None = None,
              *, unarmed_only: bool = False) -> list[Any]:
    """One menu variant per matching melee attack, plus the combined-reach entry.  ``skip`` are base actions that already
    have their variant in the catalog (so a second pass never adds the same action twice).  ``unarmed_only`` keeps the late
    pass to attacks that carry no weapon, whose dice are therefore already final at that point."""
    mechanics = info.get("mechanics") or {}
    rows = _rows(mechanics, list(owned))
    if not rows:
        return []
    from .integrated_weapons import constitution_typed, integrated_bases

    # An integrated weapon's "(Constitution)" form (combat/ext/integrated_weapons.py) gets its reach variant too: this hook does not
    # see the variants that one adds, so it builds the Constitution form of each integrated base here.
    skip = skip or set()
    pool = [action for action in actions
            if not unarmed_only or ({str(row.get("attack_kind") or "") for row in _attacks(action)} & {"unarmed", "natural"}
                                    or ".natural." in action.source_definition_id)]
    integrated = {base.source_definition_id for base in integrated_bases({**info, "owned_ids": list(owned), "actions": pool})}
    made = []
    for action in pool:
        if action.source_definition_id in skip:
            continue
        matched = [(mid, row) for mid, row in rows
                   if int(row.get("feet") or 0) > 0 and _matches(action, row.get("attacks") or "unarmed")]
        if not matched:
            continue
        combined_forms = None
        for mid, row in matched:
            feet = int(row.get("feet") or 0)
            rule = {"feature_id": mid, "feet": feet, "own_turn": bool(row.get("own_turn")), "state": row.get("state"),
                    "min_resource": list(row.get("min_resource") or []), "base": action.source_definition_id}
            forms = [("", "", action.parameters)]
            if action.source_definition_id in integrated:
                typed = (action.parameters or {}).get("typed") or {}
                forms.append(("#integrated_con", " (Constitution)", {**action.parameters, "typed": constitution_typed(info, typed)}))
            if combined_forms is None:
                combined_forms = forms
            for suffix, label, parameters in forms:
                made.append(action.model_copy(update={
                    "source_definition_id": f"{action.source_definition_id}{suffix}.reach_{feet}.{mid.rsplit('.', 1)[-1]}",
                    "display_name": f"{action.display_name}{label} (reach +{feet} ft)",
                    "range_ft": int(action.range_ft or 5) + feet,
                    "parameters": {**parameters, "variant_of": action.source_definition_id, MARK: {**rule, "menu_variant": False}},
                }))
        persistent: dict[str, int] = {}
        turn_bonus = 0
        for mid, row in matched:
            feet = int(row.get("feet") or 0)
            if row.get("own_turn"):
                turn_bonus = max(turn_bonus, feet)
            else:
                persistent[mid] = max(persistent.get(mid, 0), feet)
        maximum = int(action.range_ft or 5) + turn_bonus + sum(persistent.values())
        rule = {"base": action.source_definition_id, "menu_variant": True}
        for suffix, label, parameters in combined_forms or [("", "", action.parameters)]:
            made.append(action.model_copy(update={
                "source_definition_id": f"{action.source_definition_id}{suffix}.combined_reach",
                "display_name": f"{action.display_name}{label} (extended reach)",
                "range_ft": maximum,
                "parameters": {**parameters, "variant_of": action.source_definition_id, MARK: rule},
            }))
    return made


@hook("compile_actions")
def reach_variants(info: dict[str, Any]) -> list[Any] | None:
    return _variants(info, list(info["actions"]), list(info["owned_ids"])) or None


@hook("maneuvers")
def late_reach_variants(info: dict[str, Any]) -> dict[str, Any] | None:
    """The same variants for the unarmed and natural attacks another plug-in added as actions of its own (combat/ext/
    gu_berserker.py's granted Batter): ``compile_actions`` only sees the catalog as it stood when the hooks began, and those
    actions are in the fight by the time maneuvers are built.  Weapon attacks keep the variants the earlier pass built --
    their dice are only bound after maneuvers -- so each source id still has exactly one owner, and any attack that already
    carries its variant is left alone."""
    actions = list(info.get("actions") or [])
    carried = {str((rule or {}).get("base")) for action in actions for rule in [(action.parameters or {}).get(MARK)] if rule}
    made = _variants(info, actions, list(info.get("owned") or []), skip=carried, unarmed_only=True)
    return {"actions": made, "rows": []} if made else None


def _attacks(action: Any) -> list[dict[str, Any]]:
    typed = (action.parameters or {}).get("typed") or {}
    return [e for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"]


def is_unarmed(action: Any) -> bool:
    """Shared body-attack classification for reach variants and natural reach."""
    kinds = {str(e.get("attack_kind") or "") for e in _attacks(action)}
    return "unarmed" in kinds or ".natural." in action.source_definition_id


def _matches(action: Any, attacks: Any) -> bool:
    rows = _attacks(action)
    if not rows or (action.parameters or {}).get(MARK) or int(action.range_ft or 5) > 15:
        return False
    kinds = {str(e.get("attack_kind") or "") for e in rows}
    if any("ranged" in kind or "thrown" in kind for kind in kinds):
        return False
    typed = (action.parameters or {}).get("typed") or {}
    if typed.get("reaction_attack") or typed.get("opportunity_of"):
        return False
    unarmed = is_unarmed(action)
    if attacks == "unarmed":
        return unarmed
    if attacks == "melee":
        return True
    if isinstance(attacks, dict) and attacks.get("group"):
        from .integrated_weapons import in_group

        return in_group(typed, str(attacks["group"]))
    words = [str(word).lower() for word in (attacks or [])]
    return bool(typed.get("weapon")) and any(word in action.display_name.lower() for word in words)


def current_reach(engine: Any, actor: Any, action: Any, *, opportunity: bool = False) -> int:
    """Shared by White Heron's sweeps/guard/strikes and natural_reach_ft. Resolve catalog reach once.

    Turn-only variants are alternative totals (White Wing includes Integration);
    active persistent increases add to that total. Inactive variants grant nothing.
    This helper does not change the catalog or other actors' attack menus.
    """
    rule = (action.parameters or {}).get(MARK) or {}
    base_id = rule.get("base") or action.source_definition_id
    base = next((a for a in engine.action_catalog.values()
                 if a.owner_id == actor.entity_id and a.source_definition_id == base_id), None)
    reach = int(base.range_ft or 5) if base is not None else int(action.range_ft or 5) - int(rule.get("feet") or 0)
    turn_bonus, persistent = 0, {}
    for other in engine.action_catalog.values():
        other_rule = (other.parameters or {}).get(MARK) or {}
        if other.owner_id != actor.entity_id or other_rule.get("base") != base_id or not applies(engine, actor, other_rule, opportunity=opportunity):
            continue
        feet = int(other_rule.get("feet") or 0)
        if other_rule.get("own_turn"):
            turn_bonus = max(turn_bonus, feet)
        else:
            key = str(other_rule.get("feature_id"))
            persistent[key] = max(persistent.get(key, 0), feet)
    return reach + turn_bonus + sum(persistent.values())


NATURAL_REACH_FT = 5


def natural_reach_ft(engine: Any, actor: Any) -> int:
    """How far ``actor`` reaches with its own body, in feet: 5 feet, plus whatever printed body form is on.

    "Natural reach" is a printed requirement several talents share -- Brute's Get Over Here applies Manhandle talents
    normally "but talents requiring natural reach function only if the target ends within natural reach" -- so the
    question is about the creature, not about one action being resolved. This is ``current_reach`` restricted to the
    creature's own unarmed and natural-weapon attacks, which is exactly where the printed body increases live:
    Calamity Briar Incarnation's "Unarmed reach +10 feet" while that state is on, Oni Form's +5, Crown of Black Thorns'
    +5 while it holds a Demon Spine on its own turn. Same rows, same state/turn/resource requirements, same stacking as
    the attack menus, so one printed increase is honoured everywhere it appears.

    It never reads a weapon's reach (``typed_reactions.physical_melee_reach``, the best melee weapon's reach) and never
    reads the range of the action being resolved, so a 10-foot reach spear and a 30-foot tether are not natural reach. A
    creature with no reach row on any of its own unarmed attacks reads 5 feet, which is what every creature without a
    printed body increase reads.

    Users: combat/ext/lane4_brute.py (Manhandle's Takedown).
    """
    best = NATURAL_REACH_FT
    for action in engine.action_catalog.values():
        if action.owner_id != actor.entity_id:
            continue
        rule = (action.parameters or {}).get(MARK) or {}
        # Only the per-feature records name the row that lengthens the body; the combined variant carries no feet of
        # its own, and a base action carries no rule at all.
        if rule.get("menu_variant") is not False:
            continue
        base = next((a for a in engine.action_catalog.values()
                     if a.owner_id == actor.entity_id and a.source_definition_id == str(rule.get("base") or "")), None)
        if base is None or not is_unarmed(base):
            continue
        best = max(best, current_reach(engine, actor, action))
    return best


def applies(engine: Any, actor: Any, rule: dict[str, Any], *, opportunity: bool = False) -> bool:
    if rule.get("own_turn") and (opportunity or engine.state.current_actor_id != actor.entity_id):
        return False
    if rule.get("state"):
        from .states import active

        if not active(engine, actor, str(rule["state"])):
            return False
    if rule.get("min_resource"):
        resource, amount = rule["min_resource"]
        if int(actor.resources.get(resource, 0) or 0) < int(amount):
            return False
    return True


def _is_melee(action: Any) -> bool:
    """A base (non-variant) catalog action that strikes in melee: reach, not range."""
    rows = _attacks(action)
    if not rows:
        return False
    if any("ranged" in str(row.get("attack_kind") or "") or "thrown" in str(row.get("attack_kind") or "") for row in rows):
        return False
    return not ((action.parameters or {}).get("typed") or {}).get("range_ft")


def melee_reach(engine: Any, actor: Any, *, opportunity: bool = False) -> int:
    """How far this fighter reaches in melee right now: the widest of its own base melee attacks plus the reach increases
    that are active for it (War-God Incarnation's "+5 feet" while the Incarnation is on).  For a printed "your reach" that
    is not about one named attack -- "when a hostile creature enters your reach" (Unyielding Advance).
    ``opportunity`` answers for an Opportunity Attack's reach, where a turn-only increase does not apply.  A fighter with
    no base melee attack reaches 5 feet.  Pure query: the catalog is only read and no state is written.
    """
    feet = [5]
    for action in getattr(engine, "action_catalog", {}).values():
        if action.owner_id != actor.entity_id or (action.parameters or {}).get(MARK) or not _is_melee(action):
            continue
        feet.append(current_reach(engine, actor, action, opportunity=opportunity))
    return max(feet)


@hook("candidate_allowed")
def offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    rule = (getattr(action, "parameters", None) or {}).get(MARK)
    if not rule:
        return None
    if rule.get("menu_variant"):
        base = next((a for a in engine.action_catalog.values()
                     if a.owner_id == actor.entity_id and a.source_definition_id == rule.get("base")), None)
        if base is None:
            return False
        # This extra menu choice represents only the distance beyond the base strike.
        if len(candidate.target_ids) != 1:
            return False
        target = engine.state.actors.get(candidate.target_ids[0])
        if target is None:
            return False
        distance = engine._distance_actor_to_actor(actor, target)
        return (int(base.range_ft or 5) < distance <= current_reach(engine, actor, action))
    if rule.get("menu_variant") is False:
        return False
    return None if applies(engine, actor, rule) else False


@hook("attack_allowed")
def attack_in_current_reach(ctx: Any, target: Any, effect: dict[str, Any]) -> bool | None:
    """Recheck an extended menu strike against the same active reach used to offer it."""
    rule = (ctx.action.parameters or {}).get(MARK) or {}
    if not rule.get("menu_variant"):
        return None
    return (ctx.engine._distance_actor_to_actor(ctx.actor, target)
            <= current_reach(ctx.engine, ctx.actor, ctx.action))


@hook("opportunity_action")
def opportunity(engine: Any, actor: Any, action: Any) -> Any | None:
    base = ((action.parameters or {}).get("typed") or {}).get("opportunity_of") or action.source_definition_id
    # Compilation may bind the generic Opportunity Attack to a reach-variant
    # action. Compare against that variant's original action so its active
    # reach rule is not lost at this second level of indirection.
    seen: set[str] = set()
    bound_reach_variant = False
    while base not in seen:
        seen.add(base)
        bound = engine.action_catalog.get(base)
        rule = ((bound.parameters or {}).get(MARK) or {}) if bound is not None and bound.owner_id == actor.entity_id else {}
        if not rule.get("base"):
            break
        bound_reach_variant = True
        base = str(rule["base"])
    persistent: dict[str, int] = {}
    for other in engine.action_catalog.values():
        rule = (other.parameters or {}).get(MARK)
        if not rule or other.owner_id != actor.entity_id or rule.get("base") != base:
            continue
        if applies(engine, actor, rule, opportunity=True):
            feature = str(rule.get("feature_id") or other.source_definition_id)
            persistent[feature] = max(persistent.get(feature, 0), int(rule.get("feet") or 0))
    bonus = sum(persistent.values())
    if bonus <= 0 and not bound_reach_variant:
        return None
    # The compiler may already have copied a reach variant into the generic
    # Opportunity Attack. Start from the unmodified base range so this hook
    # applies the active rows exactly once.
    original = next((candidate for candidate in engine.action_catalog.values()
                     if candidate.owner_id == actor.entity_id
                     and candidate.source_definition_id == base), None)
    base_range = int(original.range_ft or 5) if original is not None else int(action.range_ft or 5)
    return action.model_copy(update={"range_ft": base_range + bonus})
