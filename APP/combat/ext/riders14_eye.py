"""Hidden Eye combat riders, lane 14.

Reviewed ``eye_rider_rule`` rows opt characters into these rules. Compile-time
rows carry the actual skill/ability components; no baked weapon bonus is guessed.
Analyze attempts and rival selection use evented conditions, so reloads retain
them. Rest-spanning information, evidence and social eligibility stay with the GM.
Shared with mind_hidden_eye, riders14_awareness and riders14_research for
ownership, Analyze choices and domain qualification.
Hooks: compile_actions, candidate_allowed, event, analyzed, analyze_checked, save, attack_bonus,
attack_damage, after_hit, turn_start and before_attack. No saved-fight lock edits.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from .eye_common import FOCUS, numbers_of, skill
from .mind_hidden_eye import ANALYZED, analyzed_by
from .condition_events import drop_condition as _drop
BLOCK = "riders14_eye"
ATTEMPTS = "condition:typed.eye_attempts"
RIVAL = "condition:typed.eye_rival"
COURT = "condition:typed.eye_court"
INCARNATION = "condition:typed.eye_incarnation"
THOUGHTS = "condition:typed.eye_surface_thoughts"
POISON = "condition:typed.eye_shifty_poisoner"


def rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    return [r for r in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []) if r.get("block") == BLOCK]


def has(engine: Any, actor: Any, kind: str) -> bool:
    return any(r.get("kind") == kind for r in rows(engine, actor))


def rule(engine: Any, actor: Any, kind: str) -> dict[str, Any] | None:
    """The compiled row behind one of this rider's opt-in kinds, or None.

    A caller that spends the Reaction needs the row itself rather than the
    ``has`` boolean: the shared admission and lifecycle
    (``typed_reactions.can_use_reaction`` / ``open_reaction``) read the row's
    feature id, its saved plans and any provenance attached to it, so a
    hand-rolled flag cannot stand in for it.
    """
    return next((r for r in rows(engine, actor) if r.get("kind") == kind), None)


def held(actor: Any, condition: str) -> Any:
    return next((c for c in actor.conditions.values() if c.condition_id == condition), None)


@hook("search_mode")
def sovereign_search(engine: Any, actor: Any) -> str | None:
    return "ADVANTAGE" if held(actor, INCARNATION) else None


def analyze_range(engine: Any, actor: Any) -> int:
    return 120 if has(engine, actor, "far_sight_analysis") else 60


def attempts_left(engine: Any, actor: Any, target: Any) -> bool:
    if not has(engine, actor, "analysis_limits"):
        return True  # old saved bundles retain their previous contract
    limit = int(numbers_of(engine, actor).get("pb") or 2) if has(engine, actor, "persistent_analysis") else 1
    used = next((int((c.data or {}).get("used") or 0) for c in actor.conditions.values()
                 if c.condition_id == ATTEMPTS and (c.data or {}).get("target_id") == target.entity_id), 0)
    return used < limit


def chosen_analyze_roll(engine: Any, actor: Any, target: Any = None) -> Any:
    """Choose one permitted Approach before its d20; never roll two and take the better result."""
    from .eye_common import has as eye_has
    from .needle import CHOICE, ask, checkpoint_id
    from . import floored
    from ..typed_executor import check_mode

    mods = next(r["mods"] for r in rows(engine, actor) if r.get("kind") == "analysis_limits")
    approaches = {"Investigation": "INT", "Perception": "WIS"}
    for feature, name, ability in (("folklorist", "History", "INT"), ("biological_insight", "Nature", "INT"),
                                   ("physical_examination", "Medicine", "WIS"), ("empirical_tracker", "Survival", "WIS")):
        if has(engine, actor, feature) or eye_has(engine, actor.entity_id, feature):
            approaches[name] = ability
    if has(engine, actor, "social_engineering"):
        approaches.update({"Deception": "CHA", "Intimidation": "CHA", "Persuasion": "CHA"})
    bonuses = {name: skill(engine, actor, name, mods.get(ability, 0)) for name, ability in approaches.items()}
    best = max(approaches, key=lambda name: bonuses[name])
    from .analyze_readings import SKILLS

    pick = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "EYE_APPROACH", actor.entity_id), actor,
               CHOICE + "eye_approach", list(approaches), preferred=[best],
               labels={name: f"{SKILLS[name]} ({name})" for name in approaches},
               name="Analyze: choose a skill", feature_id="TAL_THE_HIDDEN_EYE_BASE_SPHERE_FEATURES", target_id=target.entity_id if target else None,
               prompt=f"Analyze: choose a skill for {target.display_name if target else 'the selected creatures'}")
    name = pick[0] if pick else best
    roll = engine.roller.d20(modifier=bonuses[name], actor_id=actor.entity_id, reason=f"CHECK:analyze:{name.lower()}",
                            mode=check_mode(actor, approaches[name], name, engine=engine, against_creature=target))
    engine._record_roll(roll)
    return floored(engine, actor, roll)


def _action(info: dict[str, Any], suffix: str, name: str, economy: str, effects: list, *, target="SELF", reach=None):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.riders14.{suffix}", display_name=name,
        owner_id=info["actor_id"], economy=EconomyKind(economy), resolution_kind="TYPED", target_kind=target, range_ft=reach,
        parameters={"typed": {"effects": effects, "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []},
                    "expected_damage": 0, "player_only": True})


@hook("compile_actions")
def compile_eye(info: dict[str, Any]) -> list[Any]:
    """Only hash-bound reviewed effects opt in; replacing authority with old typing removes these rules."""
    out = []
    for mid in dict.fromkeys(info["owned_ids"]):
        mech = info["mechanics"].get(mid) or {}
        for rule in mech.get("effects") or []:
            if rule.get("type") != "eye_rider_rule":
                continue
            kind = rule["kind"]
            info["passives"].append({"feature_id": mid, "block": BLOCK, "kind": kind,
                                     "mods": info["mods"], "numbers": info["numbers"],
                                     "repeated": (info["owner_sheet"].get("spheres_and_talents") or {}).get(
                                         "learned_talent_record_ids", []).count(mid) > 1})
            if kind == "discern_illusions":
                action = _action(info, "discern", "Discern Illusions: Share", "BONUS_ACTION", [{"type": "eye_share_discern"}])
                out.append(action.model_copy(update={"costs": ((FOCUS, 1),)}))
            if kind == "uncanny_stalker" and "TAL_THE_HIDDEN_EYE_RAPID_ANALYSIS" not in info["owned_ids"]:
                action = _action(info, "uncanny_analyze", "Uncanny Stalker: Analyze", "BONUS_ACTION", [{"type": "analyze_check"}],
                    target="HOSTILE_ENTITY", reach=120 if "TAL_THE_HIDDEN_EYE_FAR_SIGHT_ANALYSIS" in info["owned_ids"] else 60)
                out.append(action.model_copy(update={"costs": ((FOCUS, 1),)}))
            if kind in ("fast_stealth", "sudden_acuity"):
                key = "hide" if kind == "fast_stealth" else "search"
                bonus = compiler_skill(info, "Stealth" if key == "hide" else "Perception", "DEX" if key == "hide" else "WIS")
                action = _action(info, kind, f"{mech['name']}: {key.title()}", "BONUS_ACTION", [{"type": key, "bonus": bonus}])
                out.append(action.model_copy(update={"parameters": {**action.parameters, "stealth": key, "basic": True}}))
    if any(e.get("type") == "eye_domain" and not e.get("incarnation") for mid in info["owned_ids"]
           for e in (info["mechanics"].get(mid) or {}).get("effects") or []):
        out.append(_action(info, "court_analyze", "Court: Analyze", "BONUS_ACTION", [{"type": "analyze_check"}],
                           target="HOSTILE_ENTITY", reach=120 if "TAL_THE_HIDDEN_EYE_FAR_SIGHT_ANALYSIS" in info["owned_ids"] else 60))
        bonus = compiler_skill(info, "Perception", "WIS")
        out.append(_action(info, "court_search", "Court: Search", "BONUS_ACTION", [{"type": "search", "bonus": bonus}]))
    return out


@effect("eye_rider_rule")
def passive_rule(ctx: Any, rule: dict[str, Any]) -> None:
    """Passive rows are compiled above, never an extra activation."""


@hook("candidate_allowed")
def eye_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    effects = typed.get("effects") or []
    if str(getattr(action, "source_definition_id", "")).endswith((".court_analyze", ".court_search")) and not held(actor, COURT):
        return False
    if str(getattr(action, "source_definition_id", "")).endswith(".uncanny_analyze") and not stalker_active(engine, actor):
        return False
    if any(e.get("type") == "eye_surface_thoughts" for e in effects):
        return all(analyzed_by(engine.state.actors[t], actor.entity_id) for t in candidate.target_ids)
    if any(e.get("type") == "analyze_check" for e in effects):
        return all(attempts_left(engine, actor, engine.state.actors[t]) for t in candidate.target_ids)
    if any(e.get("type") == "eye_designate_rival" for e in effects):
        target = engine.state.actors.get(next(iter(candidate.target_ids), ""))
        rival = held(actor, RIVAL)
        previous = engine.state.actors.get((rival.data or {}).get("target_id")) if rival else None
        return bool(target and analyzed_by(target, actor.entity_id) and (previous is None or previous.current_hp <= 0))
    return None


@effect("eye_designate_rival")
def designate_rival(ctx: Any, rule: dict[str, Any]) -> None:
    old = held(ctx.actor, RIVAL)
    if old:
        previous = ctx.engine.state.actors.get((old.data or {}).get("target_id"))
        if previous:
            for iid, c in list(previous.conditions.items()):
                if c.condition_id == ANALYZED and c.source_actor_id == ctx.actor.entity_id:
                    _drop(ctx.engine, previous, iid, ctx.source)
        ctx.engine._remove_condition(ctx.actor, RIVAL, ctx.source)
    ctx.engine._apply_condition(ctx.actor, RIVAL, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"target_id": ctx.target.entity_id})


@hook("analyzed")
def rival_on_analysis(engine: Any, actor: Any, target: Any) -> None:
    intent = getattr(engine, "_active_intent", None)
    if actor is None or target is None or intent is None or not has(engine, actor, "worthy_opponent"):
        return
    rival = held(actor, RIVAL)
    previous = engine.state.actors.get((rival.data or {}).get("target_id")) if rival else None
    if previous is not None and previous.current_hp > 0:
        return
    from .needle import CHOICE, ask, checkpoint_id
    from ..typed_executor import Context

    chosen = ask(engine, intent, checkpoint_id(engine, "EYE_RIVAL", actor.entity_id, target.entity_id), actor,
                 CHOICE + "eye_rival", ["designate"], allow_decline=True, automatic=False,
                 prompt=f"Worthy Opponent after Analyze: designate {target.display_name} as your rival?")
    if chosen:
        action = next(a for a in engine.action_catalog.values() if a.owner_id == actor.entity_id)
        designate_rival(Context(engine, actor, action, intent, {"numbers": numbers_of(engine, actor)}, [target], target), {})


@hook("analyze_checked")
def count_analyze(engine: Any, actor: Any, target: Any, payload: dict[str, Any]) -> None:
    if actor is None or not has(engine, actor, "analysis_limits"):
        return
    for tid in (target.entity_id,):
        old = next(((iid, c) for iid, c in actor.conditions.items()
                    if c.condition_id == ATTEMPTS and (c.data or {}).get("target_id") == tid), None)
        used = int((old[1].data or {}).get("used") or 0) if old else 0
        if old:
            _drop(engine, actor, old[0], "passive:eye.attempts")
        engine._apply_condition(actor, ATTEMPTS, "passive:eye.attempts", actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"target_id": tid, "used": used + 1})


def stalker_active(engine: Any, actor: Any) -> bool:
    from .. import stealth, zones

    if stealth.hidden(actor):
        return True
    if not has(engine, actor, "greater_stalker"):
        return False
    if any(c.condition_id == "condition:typed.invisible" for c in actor.conditions.values()):
        return True
    for zone in zones.typed_zones(engine):
        if zones._inside(engine, actor, zone):
            obscured = str((zone.trigger_profile or {}).get("obscured") or "").lower()
            if obscured == "heavy" or (obscured == "light" and actor.resources.get(FOCUS, 0) > 0):
                return True
    return False


def _assault_delta(ctx: Any, actor: Any) -> int:
    if not has(ctx.engine, actor, "assault_analysis") or ctx.target is None or not analyzed_by(ctx.target, actor.entity_id):
        return 0
    weapon = ctx.typed.get("weapon") or {}
    if "ability_modifier" not in weapon:
        return 0
    eligible = "finesse" in str(weapon.get("properties") or "").lower() or ctx.typed.get("range_ft") is not None
    repeated = next((r.get("repeated", False) for r in rows(ctx.engine, actor) if r.get("kind") == "assault_analysis"), False)
    if not eligible and not repeated:
        return 0
    return int(ctx.numbers.get("key_mod") or 0) - int(weapon["ability_modifier"])


@hook("attack_bonus")
def assault_bonus(ctx: Any, actor: Any) -> int | None:
    # assault_damage records only an owned, eligible, accepted substitution.
    return int(ctx.damage_cache.get("eye_assault_delta") or 0) or None


@hook("attack_damage")
def assault_damage(ctx: Any, dice: Any) -> Any:
    delta = _assault_delta(ctx, ctx.actor)
    ctx.damage_cache["eye_assault_delta"] = 0
    weapon = ctx.typed.get("weapon") or {}
    if delta and dice is not None:
        from .needle import CHOICE, ask, checkpoint_id

        picked = ask(ctx.engine, ctx.intent,
                     checkpoint_id(ctx.engine, "EYE_ASSAULT", ctx.actor.entity_id, ctx.target.entity_id), ctx.actor,
                     CHOICE + "eye_assault", ["substitute"], allow_decline=True,
                     labels={"substitute": "Use sphere key ability for attack and damage"},
                     default="first" if delta > 0 else "decline",
                     prompt=f"Assault Analysis with {ctx.action.display_name} against {ctx.target.display_name}: use your sphere key ability?")
        if not picked:
            return None
        ctx.damage_cache["eye_assault_delta"] = delta
        if weapon.get("omits_ability_damage"):
            delta = min(0, int(ctx.numbers.get("key_mod") or 0)) - min(0, int(weapon["ability_modifier"]))
        return dice.model_copy(update={"modifier": dice.modifier + delta})
    return None


@hook("after_hit")
def research_on_damage(ctx: Any, target: Any, kind: str) -> None:
    if kind != "weapon" or not analyzed_by(target, ctx.actor.entity_id):
        return
    from ..typed_executor import Context, run_effects

    engine, actor = ctx.engine, ctx.actor
    # after_hit also runs for hits that were fully absorbed: both rules require damage.
    attack_index = next((i for i in range(len(engine.events) - 1, -1, -1) if engine.events[i].event_type == "ATTACK_ROLLED"
                        and engine.events[i].actor_id == actor.entity_id and target.entity_id in engine.events[i].target_ids), len(engine.events))
    damaged = any(e.event_type == "DAMAGE_COMMITTED" and e.actor_id == actor.entity_id and target.entity_id in e.target_ids
                  and int((e.payload or {}).get("hp_damage") or 0) + int((e.payload or {}).get("temporary_hp_absorbed") or 0) > 0
                  for e in engine.events[attack_index + 1:])
    if not damaged:
        return
    for feature, flag, fail in (
        ("prognosis", f"eye_prognosis_turn_round_{engine.state.round_number}:{engine.state.current_actor_id}",
         [{"type": "healing_reduction", "applies_to": "target", "kind": "none",
                                               "duration": "until_start_of_next_turn",
                                               "evidence": "The target cannot regain Hit Points until the start of your next turn."}]),
        ("sabotage_mobility", f"eye_sabotage_round_{engine.state.round_number}",
         [{"type": "speed", "applies_to": "target", "flat": -max(5, 5 * int(ctx.numbers.get("key_mod") or 0)),
           "duration": "until_start_of_next_turn"}]),
    ):
        if has(engine, actor, feature) and not actor.turn_flags.get(flag):
            numbers = next(r["numbers"] for r in rows(engine, actor) if r.get("kind") == feature)
            actor.turn_flags[flag] = True
            run_effects(Context(engine, actor, ctx.action, ctx.intent, {**ctx.typed, "numbers": numbers}, [target], target),
                        [{"type": "save", "ability": "con", "on_fail": fail, "on_success": []}])


@hook("before_attack")
def shifty_poisoner(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> None:
    from .. import stealth, senses

    eligible = stalker_active(engine, attacker) and (not stealth.hidden(attacker) or not senses.finds(engine, defender, attacker))
    if has(engine, attacker, "shifty_poisoner") and eligible \
            and engine._distance_actor_to_actor(attacker, defender) <= 120:
        for iid, old in list(defender.conditions.items()):
            if old.condition_id == POISON and old.source_actor_id == attacker.entity_id:
                _drop(engine, defender, iid, "passive:eye.shifty")
        engine._apply_condition(defender, POISON, "passive:eye.shifty", attacker.entity_id,
                                expires_on="START_OF_SOURCE_NEXT_TURN")


@hook("before_attack")
def deadly_before_roll(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> None:
    if not has(engine, attacker, "deadly_timing"):
        return
    from .eye_damage import DEADLY_STRIKE_CHOICE

    attacker.turn_flags["eye_deadly_paid"] = False
    if (context.get("effect") or {}).get("attack_kind") not in ("weapon", "unarmed") or not stalker_active(engine, attacker):
        return
    flag = f"eye_deadly_first_round_{engine.state.round_number}:{engine.state.current_actor_id}"
    if attacker.turn_flags.get(flag):
        return
    attacker.turn_flags[flag] = True
    choice = held(attacker, DEADLY_STRIKE_CHOICE)
    if choice and (choice.data or {}).get("choice") == "empowered" and attacker.resources.get(FOCUS, 0) > 0:
        engine._spend_resource(attacker, FOCUS, 1, "passive:eye.deadly_strike")
        attacker.turn_flags["eye_deadly_paid"] = True


def _uncanny_reaction(engine: Any, actor: Any, target: Any, intent: Any) -> None:
    from .. import stealth
    from .eye_common import has as eye_has
    from .needle import CHOICE, ask, checkpoint_id
    from .mind_hidden_eye import analyze_against, mark_analyzed

    if not has(engine, actor, "uncanny_stalker") or not eye_has(engine, actor.entity_id, "rapid_analysis") \
            or not stalker_active(engine, actor) or not actor.reaction_available or actor.resources.get(FOCUS, 0) < 1 \
            or not attempts_left(engine, actor, target) or engine._distance_actor_to_actor(actor, target) > analyze_range(engine, actor) \
            or not stealth.sees(engine, actor, target):
        return
    picked = ask(engine, intent, checkpoint_id(engine, "EYE_UNCANNY", actor.entity_id, target.entity_id), actor,
        CHOICE + "eye_uncanny", ["analyze"], allow_decline=True, automatic=False,
        prompt=f"Uncanny Stalker before attacking or after entering range: Analyze {target.display_name} as a Reaction (expend Martial Focus)?", default="decline")
    if picked:
        from ..paid_relocation import activation as relocation_activation
        with relocation_activation(engine, actor, "reaction:eye.uncanny", independent=True):
            actor.reaction_available = False
            engine._append_event("REACTION_RESOLVED", "reaction:eye.uncanny", actor_id=actor.entity_id,
                                 target_ids=(target.entity_id,), payload={"feature_id": "TAL_THE_HIDDEN_EYE_UNCANNY_STALKER"})
            engine._spend_resource(actor, FOCUS, 1, "reaction:eye.uncanny")
            if analyze_against(engine, actor, target, "reaction:eye.uncanny"):
                mark_analyzed(engine, actor, target, "reaction:eye.uncanny")


@hook("before_attack")
def uncanny_before_attack(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> None:
    _uncanny_reaction(engine, attacker, defender, intent)


@hook("event")
def uncanny_enter_range(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "MOVEMENT_COMMITTED":
        return
    from ..gate2_runtime_models import Position

    target = engine.state.actors.get(kwargs.get("actor_id"))
    path = (kwargs.get("payload") or {}).get("path") or []
    if target is None or not path:
        return
    start = Position.model_validate(path[0])
    for actor in engine.state.actors.values():
        if actor.entity_id != target.entity_id and actor.active \
                and engine.grid.distance_ft(actor.position, start) > analyze_range(engine, actor):
            _uncanny_reaction(engine, actor, target, getattr(engine, "_active_intent", None))


@hook("event")
def adroit_reaction(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "DAMAGE_COMMITTED":
        return
    payload = kwargs.get("payload") or {}
    if int(payload.get("remaining_hp") or 0) > 0 or int(payload.get("hp_damage") or 0) <= 0:
        return
    from .needle import CHOICE, ask, checkpoint_id

    intent = getattr(engine, "_active_intent", None)
    if intent is None:
        return
    for tid in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(tid)
        if target is None:
            continue
        for actor in engine.state.actors.values():
            if not actor.active or not actor.reaction_available or actor.resources.get(FOCUS, 0) > 0 \
                    or not has(engine, actor, "adroit_reaction") or not analyzed_by(target, actor.entity_id):
                continue
            picked = ask(engine, intent, checkpoint_id(engine, "EYE_ADROIT", actor.entity_id, tid), actor, CHOICE + "eye_adroit",
                         ["regain_focus"], allow_decline=True, automatic=False,
                         prompt=f"Adroit Focus after {target.display_name} falls to 0 Hit Points: regain Martial Focus as a Reaction?")
            if picked:
                from ..paid_relocation import activation as relocation_activation
                with relocation_activation(engine, actor, "reaction:eye.adroit_focus", independent=True):
                    actor.reaction_available = False
                    engine._append_event("REACTION_RESOLVED", "reaction:eye.adroit_focus", actor_id=actor.entity_id,
                                         target_ids=(tid,), payload={"feature_id": "TAL_THE_HIDDEN_EYE_ADROIT_FOCUS"})
                    engine._gain_resource(actor, FOCUS, 1, "reaction:eye.adroit_focus")


@effect("eye_vanish")
def vanish(ctx: Any, rule: dict[str, Any]) -> None:
    """The generic reaction owns its trigger, focus cost and Reaction; this owns the destination and Hide."""
    from .needle import CHOICE, ask, checkpoint_id, free_cells, position_of, step_to, cell_id
    from .. import stealth
    from ..ability_checks import hide_check_mode
    from . import floored

    engine, actor = ctx.engine, ctx.actor
    cells = free_cells(engine, actor, engine._effective_speed(actor) // 2)
    options = [cell_id(cell) for cell in sorted(cells, key=lambda p: (cells[p], p.y, p.x))][:64]
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "EYE_VANISH", actor.entity_id), actor, CHOICE + "eye_vanish",
                 options, labels={cell_id(p): f"Move to {p.x},{p.y} ({cells[p]} ft)" for p in cells},
                 prompt=f"Vanish Between Heartbeats after {ctx.action.display_name}: move {actor.display_name} up to half your Speed",
                 preferred=[cell_id(actor.position)])
    if picked:
        step_to(engine, actor, position_of(picked[0]), ctx.source)
    # The relaxed concealment still requires an actual feature, unlike Reflexive Stealth.
    from .. import zones

    lightly = any(zones._inside(engine, actor, z) and z.trigger_profile.get("obscured") in ("light", "heavy")
                  for z in zones.typed_zones(engine))
    feature = any(a.entity_id != actor.entity_id and a.active and engine._distance_actor_to_actor(actor, a) <= 5
                  and engine._footprint(a).width_cells >= max(1, engine._footprint(actor).width_cells - 1)
                  for a in engine.state.actors.values())
    if not stealth.can_hide(engine, actor) and not lightly and not feature:
        ctx.rider("Vanish Between Heartbeats: no eligible momentary concealment at the destination; environmental features need GM confirmation.")
        return
    bonus = skill(engine, actor, "Stealth", actor.saving_throws.get("DEX", 0))
    roll = engine.roller.d20(modifier=bonus, actor_id=actor.entity_id, reason="CHECK:vanish:stealth", mode=hide_check_mode(ctx.engine, actor))
    engine._record_roll(roll)
    roll = floored(engine, actor, roll, stealth.HIDE_DC)
    engine._append_event("CHECK_ROLLED", ctx.source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"actor": roll.model_dump(mode="json"), "dc": stealth.HIDE_DC, "success": roll.total >= stealth.HIDE_DC, "check": "Stealth"})
    if roll.total >= stealth.HIDE_DC:
        engine._remove_condition(actor, stealth.HIDDEN, ctx.source)
        engine._apply_condition(actor, stealth.HIDDEN, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
            data={"stealth_total": roll.total, "reflexive_pending": not stealth.can_hide(engine, actor),
                  "eye_hide_end_count": sum(e.event_type == "TURN_ENDED" and e.actor_id == actor.entity_id for e in engine.events)
                     + (2 if engine.state.current_actor_id == actor.entity_id else 1)})


@hook("after_save")
def vanish_after_dex_save(ctx: Any, subject: Any, ability: str, named: set[str], failed: bool) -> None:
    if failed or ability != "DEX" or not subject.reaction_available or subject.resources.get(FOCUS, 0) < 1:
        return
    own = next((r for r in (getattr(ctx.engine, "typed_reaction_rows", {}) or {}).get(subject.entity_id, [])
                if any(e.get("type") == "eye_vanish" for e in r.get("effects") or [])), None)
    if own is None:
        return
    from .needle import CHOICE, ask, checkpoint_id
    from ..typed_executor import Context

    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "EYE_VANISH_SAVE", subject.entity_id), subject,
        CHOICE + "eye_vanish_save", ["vanish"], allow_decline=True, automatic=False,
        prompt=f"Vanish Between Heartbeats after {subject.display_name}'s successful Dexterity save against {ctx.action.display_name}?")
    if picked:
        from ..paid_relocation import activation as relocation_activation
        with relocation_activation(ctx.engine, subject, "reaction:eye.vanish", independent=True):
            subject.reaction_available = False
            ctx.engine._append_event("REACTION_RESOLVED", "reaction:eye.vanish", actor_id=subject.entity_id,
                                    target_ids=(ctx.actor.entity_id,), payload={"feature_id": own["feature_id"]})
            ctx.engine._spend_resource(subject, FOCUS, 1, "reaction:eye.vanish")
            vanish(Context(ctx.engine, subject, ctx.action, ctx.intent, {"numbers": own["numbers"]}, [ctx.actor], ctx.actor), {})


def illusion(typed: dict[str, Any]) -> bool:
    return "ILLUSION" in str(typed.get("source") or "").upper() or typed.get("sphere_id") == "tianxia.sphere.illusion"


def compiler_skill(info: dict[str, Any], name: str, ability: str) -> int:
    from ..factory_compiler import _skill_bonus

    return _skill_bonus(info["owner_sheet"], name, int(info["mods"].get(ability) or 0))


@effect("eye_share_discern")
def share_discern(ctx: Any, rule: dict[str, Any]) -> None:
    from .needle import CHOICE, ask, checkpoint_id
    from .effect_durations import round_token

    allies = [a for a in ctx.engine.state.actors.values() if a.active and a.team_id == ctx.actor.team_id
              and a.entity_id != ctx.actor.entity_id and ctx.engine._distance_actor_to_actor(ctx.actor, a) <= 30]
    ids = [a.entity_id for a in allies]
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "EYE_DISCERN", ctx.actor.entity_id), ctx.actor,
                 CHOICE + "eye_discern", ids, minimum=0, maximum=len(ids), allow_decline=True,
                 preferred=ids, labels={a.entity_id: a.display_name for a in allies},
                 prompt=f"Discern Illusions: which allies receive {ctx.actor.display_name}'s shared benefit?",
                 name="Discern Illusions: share with allies", feature_id="TAL_THE_HIDDEN_EYE_DISCERN_ILLUSIONS") if ids else []
    for tid in chosen:
        for iid, old in list(ctx.engine.state.actors[tid].conditions.items()):
            if old.condition_id == "condition:typed.eye_discern_illusions" and old.source_actor_id == ctx.actor.entity_id:
                _drop(ctx.engine, ctx.engine.state.actors[tid], iid, ctx.source)
        ctx.engine._apply_condition(ctx.engine.state.actors[tid], "condition:typed.eye_discern_illusions", ctx.source,
            ctx.actor.entity_id, expires_on=round_token(ctx.engine, max(1, int(ctx.numbers.get("key_mod") or 0))),
            data={"until_round": ctx.engine.state.round_number + max(1, int(ctx.numbers.get("key_mod") or 0))})


@hook("attack_mode_removed")
def deny_analyzed_advantage(engine: Any, actor: Any, target: Any, ranged: Any) -> list[str] | None:
    # Discern Tells' compiled block is owned by attack_mode_removal. This adapter
    # covers earlier saved rider rows and the Incarnation condition only.
    if target is not None and analyzed_by(actor, target.entity_id):
        compiled = any(row.get('block') == 'attack_mode_removal' and row.get('analyzed_by_owner')
                       for row in getattr(engine, 'typed_passive_rows', {}).get(target.entity_id, ()))
        if held(target, INCARNATION) or (has(engine, target, 'discern_tells') and not compiled):
            return ['ADVANTAGE']
    return None


@hook("event")
def prognosis_healing(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "HEALING_APPLIED":
        return
    payload = kwargs.get("payload") or {}
    if int(payload.get("after") or 0) <= int(payload.get("before") or 0):
        return
    source = kwargs.get("source_definition_id") or ""
    if not source:
        # Gate4's observational hook transports kwargs only. Most event writers
        # pass source_definition_id positionally; recover it from the recorded event.
        event = next((e for e in reversed(engine.events) if e.event_type == event_type and e.payload == payload
                      and e.actor_id == kwargs.get("actor_id") and tuple(e.target_ids) == tuple(kwargs.get("target_ids") or ())), None)
        source = event.source_definition_id if event else ""
    action = engine.action_catalog.get(source)
    typed = ((action.parameters or {}).get("typed") or {}) if action else {}
    if not action or "regenerat" in str(typed).lower():
        return  # only discrete healing effects, never passive regeneration
    for tid in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(tid)
        if target is None:
            continue
        for actor in engine.state.actors.values():
            flag = f"eye_prognosis_heal_round_{engine.state.round_number}:{engine.state.current_actor_id}"
            if not has(engine, actor, "prognosis") or not analyzed_by(target, actor.entity_id):
                continue
            # Only the additional healing is once per turn. Each discrete heal
            # created by this Eye independently grants the next-save benefit.
            if not target.turn_flags.get(flag):
                target.turn_flags[flag] = True
                pb = int(next(r["numbers"]["pb"] for r in rows(engine, actor) if r.get("kind") == "prognosis"))
                from ..typed_executor import _reduced_healing

                amount = _reduced_healing(engine, target, pb, healer=actor, source="passive:eye.prognosis")
                before = target.current_hp
                target.current_hp = min(target.maximum_hp, before + amount)
                engine._append_event("HEALING_APPLIED", "passive:eye.prognosis", actor_id=actor.entity_id, target_ids=(tid,),
                                     payload={"offered": amount, "before": before, "after": target.current_hp})
            if kwargs.get("actor_id") == actor.entity_id:
                for iid, old in list(target.conditions.items()):
                    if old.condition_id == "condition:typed.save_against" and old.source_definition_id == "passive:eye.prognosis" \
                            and old.source_actor_id == actor.entity_id:
                        _drop(engine, target, iid, "passive:eye.prognosis")
                engine._apply_condition(target, "condition:typed.save_against", "passive:eye.prognosis", actor.entity_id,
                    expires_on="START_OF_SOURCE_NEXT_TURN", data={"rule": {"save_against": {
                        "mode": "ADVANTAGE", "against": [], "abilities": ["STR", "DEX", "CON", "INT", "WIS", "CHA"], "next": True}}})


@hook("save")
def eye_saves(ctx: Any, subject: Any, ability: str, named: set[str]) -> dict[str, Any] | None:
    modes = []
    if held(subject, THOUGHTS) and (held(subject, THOUGHTS).data or {}).get("target_id") == ctx.actor.entity_id:
        modes.append("ADVANTAGE")
    if illusion(ctx.typed) and ((has(ctx.engine, subject, "discern_illusions") and subject.resources.get(FOCUS, 0) > 0)
                                 or held(subject, "condition:typed.eye_discern_illusions") or held(subject, INCARNATION)):
        modes.append("ADVANTAGE")
    if any(c.condition_id == POISON and c.source_actor_id == ctx.actor.entity_id for c in subject.conditions.values()) \
            and ("poisoned" in named or "damage:poison" in named or "disease" in str(ctx.typed).lower()):
        modes.append("DISADVANTAGE")
    return {"bonus": 0, "modes": modes} if modes else None


@hook("ability_check_mode")
def qualified_eye_check(engine: Any, actor: Any, ability: str, skill: str | None, against: Any) -> str | None:
    """Eye check benefits require the explicit opposing/source creature.

    Discern Tells applies only to Wisdom (Insight) against this Eye's Analyzed
    creature; Surface Thoughts applies to checks against its recorded creature.
    The caller combines this mode with independent condition penalties.
    """
    if ability == "WIS" and skill == "Insight" and has(engine, actor, "discern_tells") \
            and analyzed_by(against, actor.entity_id):
        return "ADVANTAGE"
    reading = held(actor, THOUGHTS)
    if reading is not None and reading.data.get("target_id") == against.entity_id:
        return "ADVANTAGE"
    return None


@hook("skill_check_mode")
def illusion_investigation(ctx: Any, subject: Any, ability: str, skill: str | None) -> str | None:
    """Intelligence (Investigation) resisting an explicitly tagged Illusion effect.

    A check against the caster alone does not establish Illusion provenance.
    Reuse the same focused/shared qualification as the saving-throw benefit.
    """
    if ability != "INT" or skill != "Investigation" or not illusion(ctx.typed):
        return None
    if (has(ctx.engine, subject, "discern_illusions") and subject.resources.get(FOCUS, 0) > 0) \
            or held(subject, "condition:typed.eye_discern_illusions"):
        return "ADVANTAGE"
    return None


@effect("eye_surface_thoughts")
def surface_thoughts(ctx: Any, rule: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, THOUGHTS, ctx.source)
    ctx.engine._apply_condition(ctx.actor, THOUGHTS, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"target_id": ctx.target.entity_id})


@effect("eye_domain")
def eye_domain(ctx: Any, rule: dict[str, Any]) -> None:
    from ..senses import SENSE
    from .effect_durations import round_token

    condition = INCARNATION if rule.get("incarnation") else COURT
    ctx.engine._remove_condition(ctx.actor, condition, ctx.source)
    ctx.engine._apply_condition(ctx.actor, condition, ctx.source, ctx.actor.entity_id, expires_on=round_token(ctx.engine, 10),
        data={"until_round": ctx.engine.state.round_number + 10, "source": ctx.source})
    if condition == INCARNATION:
        ctx.engine._gain_resource(ctx.actor, FOCUS, 1, ctx.source)
        ctx.engine._apply_condition(ctx.actor, SENSE, ctx.source, ctx.actor.entity_id, expires_on=round_token(ctx.engine, 10),
            data={"sense": "blindsight", "range_ft": 30, "until_round": ctx.engine.state.round_number + 10})
    else:
        from .needle import CHOICE, ask, checkpoint_id

        allies = [a.entity_id for a in ctx.engine.state.actors.values() if a.active and a.team_id == ctx.actor.team_id
                  and a.entity_id != ctx.actor.entity_id]
        chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "EYE_COURT", ctx.actor.entity_id), ctx.actor,
                     CHOICE + "eye_court", allies, minimum=0, maximum=len(allies), allow_decline=True,
                     preferred=allies, labels={aid: ctx.engine.state.actors[aid].display_name for aid in allies},
                     prompt=f"Court of the Hidden Eye: which allies benefit from {ctx.actor.display_name}'s Passive Perception bonus?",
                     name="Court of the Hidden Eye: share perception", feature_id="TAL_THE_HIDDEN_EYE_COURT_OF_THE_HIDDEN_EYE") if allies else []
        for tid in chosen:
            ctx.engine._apply_condition(ctx.engine.state.actors[tid], "condition:typed.eye_court_ally", ctx.source, ctx.actor.entity_id,
                expires_on=round_token(ctx.engine, 10), data={"bonus": int(ctx.numbers.get("pb") or 2) // 2})


@hook("passive_perception")
def court_perception(engine: Any, actor: Any) -> int:
    bonuses = []
    for condition in actor.conditions.values():
        if condition.condition_id != "condition:typed.eye_court_ally":
            continue
        owner = engine.state.actors.get(condition.source_actor_id)
        if owner and owner.active and held(owner, COURT) and engine._distance_actor_to_actor(actor, owner) <= 60:
            bonuses.append(int((condition.data or {}).get("bonus") or 0))
    return max(bonuses, default=0)


@hook("turn_start")
def incarnation_turn(engine: Any, actor: Any) -> None:
    for other in engine.state.actors.values():
        for iid, condition in list(other.conditions.items()):
            if condition.condition_id == "condition:typed.eye_discern_illusions" and condition.source_actor_id == actor.entity_id \
                    and engine.state.round_number >= int((condition.data or {}).get("until_round") or 0):
                _drop(engine, other, iid, "passive:eye.discern_expiry")
    for cid in (COURT, INCARNATION):
        condition = held(actor, cid)
        if condition and engine.state.round_number >= int((condition.data or {}).get("until_round") or 0):
            engine._remove_condition(actor, cid, "passive:eye.domain_expiry")
    if not held(actor, INCARNATION):
        return
    from .. import stealth
    from .mind_hidden_eye import mark_analyzed
    from .needle import ask, checkpoint_id, CHOICE

    if actor.resources.get(FOCUS, 0) == 0:
        engine._gain_resource(actor, FOCUS, 1, "passive:eye.incarnation")
    seen = [t for t in engine.state.actors.values() if t.entity_id != actor.entity_id and t.active
            and engine._distance_actor_to_actor(actor, t) <= analyze_range(engine, actor) and stealth.sees(engine, actor, t)]
    if seen:
        options = [t.entity_id for t in seen]
        picked = ask(engine, getattr(engine, "_active_intent", None),
                     checkpoint_id(engine, "EYE_AUTO", actor.entity_id), actor,
                     CHOICE + "eye_auto", options, allow_decline=True, target_id=actor.entity_id,
                     labels={t.entity_id: t.display_name for t in seen},
                     prompt=f"Sovereign Hidden Eye Incarnation at the start of {actor.display_name}'s turn: choose a creature to Analyze",
                     name="Sovereign Hidden Eye Incarnation: Analyze", feature_id="TAL_THE_HIDDEN_EYE_SOVEREIGN_HIDDEN_EYE_INCARNATION")
        if picked:
            mark_analyzed(engine, actor, engine.state.actors[picked[0]], "passive:eye.incarnation")
            from .riders14_research import learn

            learn(engine, actor, engine.state.actors[picked[0]], 1 + (int(numbers_of(engine, actor).get("pb") or 2) // 2
                  if has(engine, actor, "thorough_analysis") else 0))
