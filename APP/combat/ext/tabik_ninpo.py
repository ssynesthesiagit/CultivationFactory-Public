"""Shinobi and Ninpo Adept Subpath features (owner 2026-09-28: "make sure all the talents and class abilities ... is
applied"; Tabik Damu's kit).

  Shadow Clone Array  Bonus Action, 7 Qi, once per scene, 1 minute: two Shadow Clones (visual and Qi
                     constructs, not creatures) overlap your movement and move with you, tracked as one
                     condition holding the count (combat/ext/blacksmith_forge.py's counting row). Clone
                     Interposition: once per round, an attack roll that hits you destroys one Clone and
                     misses (hit_response -> attack_outcomes.unconditional_miss; no action), unless the
                     attacker identifies your true body through the engine's own locating perception
                     (Truesight, reaching Blindsight, a Source Rule or a higher-CL duplicate-defeating
                     effect; Tremorsense models its shared-surface contact). While a Clone remains:
                     Shadow Step costs 0 Qi and its range becomes 60 feet (a "Shadow Step (Array)"
                     variant action replaces the base one while Clones remain); Hidden Strike deals 4d6
                     and qualifies when the target sees you but cannot identify the real image; you do
                     not provoke Opportunity Attacks from creatures unable to identify the true body.
                     Replace a Clone: Bonus Action, 3 Qi, once per activation. Clone Assault
                     Misdirection: once per turn after you hit while a Clone remains, one printed
                     choice (asked; AI picks by side).
  Shadow Step       Bonus Action, 1 Qi, once per turn: teleport up to 15 feet from darkness, smoke or an
                     obscured area to a visible unoccupied square in one (effect "where": "darkness",
                     combat/gate4_engine.py). After it: the first Opportunity Attack against it before
                     its next turn has Disadvantage, Hidden Strike qualifies for the rest of the turn,
                     your next Stealth check before turn end has Advantage (the existing check-mode
                     condition, consumed at the roll), and you draw or stow one item (a free choice).
  Smoke Veil        its own smoke: it sees through it; the PB creatures it chooses when it activates see
                     it as Lightly rather than Heavily Obscured (a chosen-recipient roster, not the
                     whole side); "Smoke Veil: move" moves it up to 15 feet once each turn, no action,
                     staying within 60 feet; Veil Escape asks after actually entering it or Stepping
                     into it.
  Pressure-Point    asked on each qualifying hit (1 Stamina), the failed-save effect asked after the
                     failure. Shared helper: shinobi.py's Assassination calls ``pressure_point`` to
                     apply it without Stamina.
  Shadow Afterimage The decoy is a creature of its own (combat/rules/summons.json: AC 13 + PB, 1 HP,
                     no attacks); "Shadow Exchange" (Bonus Action, 1 Stamina) swaps places with it
                     within 60 feet.
  Hidden Strike     once per turn on a hit while the target can't see it (darkness, smoke, hidden,
                     invisible) or after a Shadow Step this turn, or while a Shadow Clone remains and
                     the target cannot identify the real image: +2d6 (CL17 3d6, 4d6 while a Clone
                     remains) of the attack's damage type, then the chosen rider (all five printed
                     riders; manual owners choose after damage, AI uses its standing preference).
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

STEP_OA = "condition:typed.shadow_step_oa"
CHOICE = "condition:typed.hidden_strike_choice"
STAMINA = "resource:core.stamina"
QI = "resource:core.qi"
HIDDEN = "tianxia.subpath.qi.ninpo_adept.feature.hidden_strike"
AFTERIMAGE = "tianxia.subpath.body.shinobi.feature.shadow_afterimage"
STEALTH = "condition:typed.hidden_strike_stealth"
SMOKE_MARK = "condition:typed.hidden_strike_smoke_mark"
SCA = "tianxia.subpath.qi.ninpo_adept.feature.shadow_clone_array"
SHADOW_STEP = "tianxia.subpath.qi.ninpo_adept.feature.shadow_step"
SMOKE_VEIL = "tianxia.subpath.qi.ninpo_adept.feature.smoke_veil"
VANISHING = "tianxia.subpath.qi.ninpo_adept.feature.vanishing_technique"
CLONES = "condition:typed.shadow_clone_array"
MAX_CLONES = 2
SCENE_KEY = "_round_scene_shadow_clone_array"
INTERPOSE_KEY = "_round_clone_interposition"
MISDIRECT_KEY = "_round_clone_misdirection"
ARRAY_STEP_KEY = "typed_once_turn:shadow_step_array"
HIDDEN_RIDERS = {
    "withdraw": "Silent Withdrawal: move 5 feet without provoking Opportunity Attacks",
    "sever": "Sever Awareness: target cannot take Reactions until the start of your next turn",
    "vanish": "Vanishing Posture: Advantage on your next Stealth check before this turn ends",
    "mislead": "Misleading Impact: push or pull the target 5 feet",
    "smoke": "Smoke Mark: until the start of your next turn, the target cannot benefit from Invisible against you; know its direction inside your Smoke Veil",
}


def _rows(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "ninpo" and row.get("kind") == kind]


@hook("compile_block")
def ninpo_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "ninpo":
        return None
    compiled = {**row, "block": "ninpo", "kind": spec.get("kind"), "cl": int(numbers.get("cl") or 1)}
    if spec.get("kind") == "shadow_clone_array":
        # This row supplies passive riders; the reviewed activation must still
        # compile as the single paid Bonus Action (the shared compiler seam).
        compiled["keeps_compiling"] = True
    if spec.get("kind") in ("pressure_point", "hidden_strike", "shadow_clone_array"):
        compiled["choice_owner"] = True  # Manual owners choose even during another actor's turn.
    return [compiled]


# ------------------------------------------------------------------------------------------------ Shadow Step
@effect("shadow_step_after")
def shadow_step_after(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.actor.turn_flags["shadow_stepped"] = True
    ctx.engine._apply_condition(ctx.actor, STEP_OA, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"label": "The first Opportunity Attack against it has Disadvantage (Shadow Step)"})
    # "Gain Advantage on the next Stealth check before end of turn" (consumed
    # by the CHECK_ROLLED hook below, which removes the condition once a
    # Stealth check actually rolls).
    from .effect_durations import token

    ctx.engine._apply_condition(ctx.actor, STEALTH, ctx.source, ctx.actor.entity_id,
                                expires_on=token("end", ctx.actor.entity_id, ctx.actor.turns_started),
                                data={"rule": {"check_mode": {"Stealth": "ADVANTAGE"}},
                                      "label": "Shadow Step: Advantage on your next Stealth check before this turn ends"})


@hook("attack_mode")
def step_oa(ctx: Any, target: Any) -> str | None:
    if getattr(ctx.engine, "_typed_oa_attacker", None) != ctx.actor.entity_id:
        return None
    if any(c.condition_id == STEP_OA for c in target.conditions.values()):
        ctx.engine._remove_condition(target, STEP_OA, ctx.source)
        return "DISADVANTAGE"
    return None


# ------------------------------------------------------------------------------------------------ Smoke Veil
@effect("zone_sight")
def zone_sight(ctx: Any, eff: dict[str, Any]) -> None:
    """Its own area does not hide anything from it; the PB creatures it
    chooses when it activates see it as Lightly rather than Heavily
    Obscured (the native zone trigger_profile.lightly_obscured_viewer_ids
    roster, combat/zones.py _blocks). A veil centered on its Domain
    Armament remembers that origin, so it may move within 60 feet of the
    Armament instead of only of its owner."""
    from . import qi_path
    from .needle import ask, checkpoint_id
    from .tabik_dark import republish, zone_made_now
    from ..relations import relation
    from .. import stealth
    from . import ai_controlled

    engine, actor = ctx.engine, ctx.actor
    zone = zone_made_now(ctx)
    if zone is None:
        return
    pb = max(1, int(getattr(actor, "proficiency_bonus", 1) or 1))
    pool = [creature for creature in engine.state.actors.values()
            if creature.active and creature is not actor]
    # Its own newly created smoke must not hide recipients from its maker.
    zone.trigger_profile = {**zone.trigger_profile, "owner_sees": True}
    if ai_controlled(engine, actor):
        pool = [creature for creature in pool if stealth.sees(engine, actor, creature)]
    allies = [creature.entity_id for creature in pool if relation(engine, actor, creature) == "ALLY"]
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "smoke_veil_viewers", ctx.source), actor,
                 "choice:needle.smoke_veil_viewers", [creature.entity_id for creature in pool],
                 labels={creature.entity_id: creature.display_name for creature in pool},
                 minimum=0, maximum=pb, allow_decline=True, default_count=min(pb, len(allies)),
                 preferred=allies, default="first" if allies else "decline",
                 target_id=actor.entity_id, name="Smoke Veil", feature_id=SMOKE_VEIL,
                 prompt=f"Smoke Veil: choose up to {pb} creatures (your Proficiency Bonus) that see the smoke "
                        "as Lightly rather than Heavily Obscured. You always see through it.") if pool else []
    profile = {**zone.trigger_profile, "owner_sees": True, "lightly_obscured_viewer_ids": list(picked or [])}
    if qi_path.armament_condition(actor) is not None \
            and (zone.center.x, zone.center.y) == qi_path.armament_point(actor):
        profile["armament_origin"] = True  # the veil may stay within 60 feet of its Domain origin
    zone.trigger_profile = profile
    republish(engine, zone, ctx.source)


@hook("compile_actions")
def ninpo_actions(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    owned, short = info["owned_ids"], info["short"]
    out = []

    def make(key: str, name: str, economy: Any, effects: list[dict[str, Any]], *, target: str = "SELF", range_ft: int | None = None,
             costs: tuple = (), **parameters: Any) -> Any:
        return ActionDefinition(source_definition_id=f"action:typed.{short}.ninpo.{key}", display_name=name, owner_id=info["actor_id"],
                                economy=economy, resolution_kind="TYPED", target_kind=target, range_ft=range_ft, costs=costs,
                                parameters={"typed": {"effects": effects, "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [],
                                                      "source": key}, "expected_damage": 0, **parameters})
    if "tianxia.subpath.qi.ninpo_adept.feature.smoke_veil" in owned:
        out.append(make("smoke_veil_move", "Smoke Veil: move", EconomyKind.NONE,
                        [{"type": "move_zone", "zone_name": "Smoke Veil", "max_ft": 15, "range_ft": 60,
                          "evidence": "may move 15 feet once during each turn while remaining within 60 feet of you"}],
                        target="CELL", range_ft=60, any_cell=True, zone_mover="Smoke Veil"))
        out.append(make("veil_escape", "Veil Escape", EconomyKind.NONE,
                        [{"type": "veil_escape_move", "self_movement": True, "evidence": "move 5 feet without provoking"}],
                        target="SELF", player_only=True, veil_escape=True))
    if AFTERIMAGE in owned:
        out.append(make("shadow_exchange", "Shadow Exchange", EconomyKind.BONUS_ACTION, [{"type": "shadow_exchange", "self_movement": True}],
                        costs=((STAMINA, 1),), shadow_exchange=True))
    if SCA in owned:
        out.append(make("replace_clone", "Replace a Clone", EconomyKind.BONUS_ACTION,
                        [{"type": "shadow_clone_replace"}], costs=((QI, 3),), replace_clone=True))
        if "tianxia.subpath.qi.ninpo_adept.feature.shadow_step" in owned:
            out.append(make("shadow_step_array", "Shadow Step (Array)", EconomyKind.BONUS_ACTION,
                            [{"type": "teleport", "applies_to": "self", "distance_ft": 60, "where": "darkness"},
                             {"type": "shadow_step_after"}],
                            range_ft=60, array_step=True))
    if VANISHING in owned:
        if "tianxia.subpath.qi.ninpo_adept.feature.shadow_step" in owned:
            out.append(make("shadow_step_vanishing", "Shadow Step (Vanishing)", EconomyKind.BONUS_ACTION,
                            [{"type": "teleport", "applies_to": "self", "distance_ft": 30, "where": "darkness"},
                             {"type": "shadow_step_after"}],
                            costs=((QI, 1),), range_ft=30, vanishing_step=True))
        if "tianxia.subpath.qi.ninpo_adept.feature.smoke_veil" in owned:
            out.append(make("smoke_veil_move_vanishing", "Smoke Veil: move (Vanishing)", EconomyKind.NONE,
                            [{"type": "move_zone", "zone_name": "Smoke Veil", "max_ft": 30, "range_ft": 60,
                              "evidence": "Smoke Veil moves up to 30 feet each turn while Vanishing Technique lasts"}],
                            target="CELL", range_ft=60, any_cell=True,
                            zone_mover="Smoke Veil", vanishing_move=True))
    if HIDDEN in owned:
        for key, label in HIDDEN_RIDERS.items():
            out.append(make(f"hidden_strike.{key}", f"Hidden Strike: {label.split(':', 1)[0]}", EconomyKind.NONE,
                            [{"type": "hidden_strike_choice", "choice": key}], player_only=True, setting_only=True,
                            setting_description=f"Prefer {label} after Hidden Strike damage. No action or resource cost; manual owners still choose on each hit."))
    return out or None


def _in_own_smoke_veil(engine: Any, actor: Any) -> bool:
    """Veil Escape's trigger ("after entering your Smoke Veil or using Shadow Step into it") collapses to one
    check: the actor is now standing inside a Smoke Veil zone it owns, however it got there (walking in or
    Shadow Step's teleport both end with the actor's position inside the veil)."""
    from .. import zones
    from .tabik_dark import movable

    return any(zones._inside(engine, actor, zone) for zone in movable(engine, actor, "Smoke Veil"))


@hook("candidate_allowed")
def ninpo_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    parameters = (getattr(action, "parameters", None) or {}) if action is not None else {}
    mover = parameters.get("zone_mover")
    if mover:
        from . import qi_path
        from .tabik_dark import movable

        zones_ = movable(engine, actor, mover)
        aim = getattr(candidate, "destination", None)
        if parameters.get("vanishing_move"):
            if not _vanishing_active(engine, actor):
                return False
        elif _vanishing_active(engine, actor):
            return False  # Vanishing Technique: the veil moves 30 feet each turn
        movement_ft = 30 if parameters.get("vanishing_move") else 15
        near = [zone for zone in zones_ if aim is not None and engine.grid.distance_ft(zone.center, aim) <= movement_ft]
        held = bool(zones_) and not actor.turn_flags.get(f"moved_zone:{mover}") and aim is not None \
            and (engine.grid.distance_ft(actor.position, aim) <= 60
                 or any(zone.trigger_profile.get("armament_origin")
                        and engine.grid.distance_ft(qi_path.armament_point(actor), aim) <= 60 for zone in near))
        return held and any(engine.grid.distance_ft(zone.center, aim) <= movement_ft for zone in zones_)
    if parameters.get("shadow_exchange"):
        return _afterimage(engine, actor) is not None
    if parameters.get("veil_escape"):
        return not actor.turn_flags.get("veil_escape_used") and _in_own_smoke_veil(engine, actor)
    if parameters.get("replace_clone"):
        if not _array_rows(engine, actor) or _replaced(engine, actor):
            return False
        return clone_count(engine, actor) < MAX_CLONES
    if parameters.get("array_activation"):
        # Bonus Action, 7 Qi, once per scene (the effect re-checks it,
        # so an old save or a bare engine cannot create a third array).
        return not actor.turn_flags.get(SCENE_KEY)
    if action is not None and str(getattr(action, "source_definition_id", "")).endswith(".feature.shadow_clone_array"):
        return bool(_array_rows(engine, actor)) and not actor.turn_flags.get(SCENE_KEY)
    if parameters.get("array_step"):
        if not _rows(engine, actor, "shadow_clone_array") or clone_count(engine, actor) < 1:
            return False
        return not actor.turn_flags.get(ARRAY_STEP_KEY)
    if parameters.get("vanishing_step"):
        # Vanishing Technique's 30 feet; the Array's 60 feet takes
        # precedence while a Clone remains.
        return _vanishing_active(engine, actor) and not (
            _rows(engine, actor, "shadow_clone_array") and clone_count(engine, actor) >= 1)
    if action is not None and str(getattr(action, "source_definition_id", "")).endswith(".feature.shadow_step") \
            and (_vanishing_active(engine, actor)
                 or (_rows(engine, actor, "shadow_clone_array") and clone_count(engine, actor) >= 1)):
        return False  # the range becomes 30 (Vanishing) or 60 (Array) feet: only the matching form is offered
    return None


@effect("veil_escape_move")
def veil_escape_move(ctx: Any, eff: dict[str, Any]) -> None:
    """Once per turn after entering your Smoke Veil or using Shadow Step into it: move 5 feet without provoking
    Opportunity Attacks (a free player toggle offered only while candidate_allowed's check above holds)."""
    from ..typed_executor import block_movement

    ctx.actor.turn_flags["veil_escape_used"] = True
    block_movement(ctx, {"distance_ft": 5, "no_opportunity_attacks": True})


# ------------------------------------------------------------------------------------------------ Shadow Clone Array
def _array_rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    return _rows(engine, actor, "shadow_clone_array")


def clone_count(engine: Any, actor: Any) -> int:
    """Active Shadow Clones (the printed maximum is two)."""
    for held in actor.conditions.values():
        if held.condition_id == CLONES:
            return max(0, int((held.data or {}).get("clones") or 0))
    return 0


def _set_clones(engine: Any, actor: Any, count: int, source: str, *, replaced: bool | None = None,
                expires_on: str | None = None) -> None:
    """Exactly ``count`` Clones, retaining the activation's source, identity and expiry.

    ``replaced`` rides the counting record, so "once per activation" resets
    exactly when the array's own condition ends (a new activation starts
    un-replaced); a turn flag could not tell the two apart.
    """
    count = max(0, min(MAX_CLONES, int(count)))
    old = next((held for held in actor.conditions.values() if held.condition_id == CLONES), None)
    if replaced is None:
        replaced = bool((old.data or {}).get("replaced")) if old is not None else False
    label = (f"Shadow Clone Array: {count} Shadow Clone{'s' if count != 1 else ''} remain and overlap your movement; "
             "the clones are visual Qi doubles that do not attack, block areas, or prevent saving-throw effects")
    data = {"clones": count, "replaced": replaced, "label": label}
    if old is not None:
        # Interposition and replacement change this activation's bookkeeping,
        # not its supernatural provenance or its original duration.
        engine._update_condition_data(actor, old, data, source)
    else:
        engine._apply_condition(actor, CLONES, source, actor.entity_id,
                                expires_on=expires_on or "UNTIL_REMOVED", data=data)


def _replaced(engine: Any, actor: Any) -> bool:
    """Whether this activation of the array already replaced a Clone."""
    for held in actor.conditions.values():
        if held.condition_id == CLONES:
            return bool((held.data or {}).get("replaced"))
    return True  # no active array: nothing to replace


def identifies_true_body(engine: Any, attacker: Any, defender: Any) -> bool:
    """Whether the attacker identifies the defender's real body among its
    Shadow Clones.

    Only a sense that tells the real creature from its duplicates counts:
    Truesight and reaching Blindsight (the engine's senses that see through
    concealment and pin the real creature), and Tremorsense, which pinpoints
    the defender's vibration on its connected surface while the Clones carry
    no separate physical vibration (no feature gives them any). A creature
    that merely sees the defender also sees the overlapping Clones and cannot
    tell which is real. A Source Rule or a higher-CL effect that explicitly
    defeats duplicates would identify it too; the engine has no general
    marker for those, so they stay text.
    """
    from .. import senses

    if attacker is None or defender is None or attacker is defender or not attacker.active:
        return False
    available = senses.of(engine, attacker)
    for sense in ("truesight", "blindsight"):
        if sense in available and senses._within(engine, attacker, defender,
                                                  senses.reach(engine, attacker, sense, defender)):
            return True
    if "tremorsense" in available:
        from ..surface_contact import connected

        if connected(engine, attacker, defender) and senses._within(
                engine, attacker, defender, senses.reach(engine, attacker, "tremorsense", defender)):
            return True
    return False


@effect("shadow_clone_array")
def shadow_clone_array_create(ctx: Any, eff: dict[str, Any]) -> None:
    """Bonus Action, 7 Qi, once per scene, 1 minute: two Shadow Clones overlap your movement."""
    engine, actor = ctx.engine, ctx.actor
    if not _array_rows(engine, actor) or actor.turn_flags.get(SCENE_KEY):
        return
    actor.turn_flags[SCENE_KEY] = True
    from .effect_durations import round_token
    _set_clones(engine, actor, MAX_CLONES, ctx.source,
                expires_on=ctx.expires_on() or round_token(engine, 10))
    note(engine, SCA, actor, f"{actor.display_name} creates two Shadow Clones that overlap its movement.", (actor.entity_id,))


@effect("shadow_clone_replace")
def shadow_clone_replace(ctx: Any, eff: dict[str, Any]) -> None:
    """Replace a Clone: Bonus Action, 3 Qi, once per activation, up to the maximum of two."""
    engine, actor = ctx.engine, ctx.actor
    if not _array_rows(engine, actor) or _replaced(engine, actor):
        return
    if clone_count(engine, actor) >= MAX_CLONES:
        return
    _set_clones(engine, actor, clone_count(engine, actor) + 1, ctx.source, replaced=True)
    note(engine, SCA, actor, f"{actor.display_name} replaces a Shadow Clone.", (actor.entity_id,))


@hook("hit_response")
def clone_interposition(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> dict[str, Any] | None:
    """Clone Interposition: once per round, an attack roll that hits you destroys one Clone
    and the attack misses. This requires no action."""
    if target is None or not target.active or not _array_rows(engine, target):
        return None
    if clone_count(engine, target) < 1 or target.turn_flags.get(INTERPOSE_KEY) == engine.state.round_number:
        return None
    if identifies_true_body(engine, attacker, target):
        return None
    from .needle import ask, checkpoint_id

    picked = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, "clone_interposition", target.entity_id), target,
                 "choice:needle.clone_interposition", ["interpose"],
                 labels={"interpose": f"Destroy one Shadow Clone: {attacker.display_name}'s attack misses"},
                 preferred=["interpose"], allow_decline=True,
                 automatic_options=["interpose"], target_id=attacker.entity_id, name="Shadow Clone Array",
                 feature_id=SCA,
                 prompt=f"Shadow Clone Array: {attacker.display_name}'s attack hits {target.display_name}. "
                        "Destroy one Shadow Clone to make it miss? This requires no action.")
    if not picked:
        return None
    target.turn_flags[INTERPOSE_KEY] = engine.state.round_number
    _set_clones(engine, target, clone_count(engine, target) - 1, SCA)
    note(engine, SCA, target, f"Shadow Clone Array: {target.display_name} destroys a Shadow Clone; "
                               f"{attacker.display_name}'s attack misses.", (target.entity_id, attacker.entity_id))
    from ..attack_outcomes import unconditional_miss

    return unconditional_miss()


@hook("opportunity_allowed")
def clone_opportunity(engine: Any, reactor: Any, mover: Any) -> bool | None:
    """While a Clone remains, you do not provoke Opportunity Attacks from creatures
    unable to identify the true body."""
    if mover is None or not _array_rows(engine, mover) or clone_count(engine, mover) < 1:
        return None
    return False if not identifies_true_body(engine, reactor, mover) else None


def _clone_misdirection_options(engine: Any, actor: Any, target: Any) -> list[str]:
    out = ["move", "deny", "smoke", "hide"]
    from . import qi_path

    if qi_path.armament_condition(actor) is not None:
        out.append("armament")
    return out


_MISDIRECT_LABELS = {
    "move": "Move 10 feet without provoking Opportunity Attacks",
    "deny": "It cannot take Reactions until the start of its next turn",
    "smoke": "Move your Smoke Veil 20 feet",
    "armament": "Move your Domain Armament 20 feet",
    "hide": "Immediately attempt to Hide",
}


@hook("after_hit")
def clone_assault_misdirection(ctx: Any, target: Any, kind: str) -> None:
    """Clone Assault Misdirection: once per turn after you hit while a Clone remains, choose
    one printed benefit (asked; AI picks by side: the foe's Reactions off, else its own move)."""
    engine, actor = ctx.engine, ctx.actor
    if target is None or not target.active or not _array_rows(engine, actor) or clone_count(engine, actor) < 1:
        return
    if actor.turn_flags.get(MISDIRECT_KEY) == _stamp(engine):
        return
    options = _clone_misdirection_options(engine, actor, target)
    from .needle import ask, checkpoint_id

    picked = ask(engine, ctx.intent, checkpoint_id(engine, "clone_misdirection", target.entity_id), actor,
                 "choice:needle.clone_misdirection", options, labels=_MISDIRECT_LABELS,
                 preferred=["deny"] if target.team_id != actor.team_id else ["move"],
                 allow_decline=True, automatic_options=options,
                 target_id=target.entity_id, name="Clone Assault Misdirection", feature_id=SCA,
                 prompt=f"Clone Assault Misdirection: {ctx.action.display_name} hit {target.display_name} "
                        "while a Shadow Clone remains. Choose one (no action, no resource cost).")
    if not picked or picked[0] not in options:
        return
    actor.turn_flags[MISDIRECT_KEY] = _stamp(engine)
    choice = picked[0]
    note(engine, SCA, actor, f"Clone Assault Misdirection ({_MISDIRECT_LABELS[choice]}).", (target.entity_id,))
    import dataclasses

    from .. import typed_executor

    if choice == "deny":
        typed_executor.run_effects(dataclasses.replace(ctx, target=target),
                                         [{"type": "reaction_denied", "applies_to": "target",
                                           "expires_on": "START_OF_TARGET_NEXT_TURN",
                                           "evidence": "Clone Assault Misdirection: it cannot take Reactions until the start of its next turn."}])
    elif choice == "hide":
        from .. import stealth
        from ..ability_checks import ability_modifier

        stealth.hide(engine, actor, ability_modifier(actor, "DEX"), ctx.source,
                     mode="ADVANTAGE" if _stealth_advantage(engine, actor) else "NORMAL")
    elif choice == "armament":
        from . import qi_path
        from .needle import cell_options, position_of
        from ..stealth import sees

        origin = qi_path.armament_point(actor)
        cells = {cell: int(engine.grid.distance_ft(origin, cell))
                 for cell in qi_path.armament_destinations(engine, actor, 20, sees)}
        options_, labels = cell_options(engine, actor, cells, cap=len(cells))
        picked_cell = ask(engine, ctx.intent, checkpoint_id(engine, "clone_armament", actor.entity_id), actor,
                          "choice:needle.clone_armament", options_, labels=labels, target_id=actor.entity_id,
                          name="Clone Assault Misdirection", feature_id=SCA,
                          prompt="Clone Assault Misdirection: move your Domain Armament up to 20 feet.")
        if picked_cell and picked_cell[0] in options_:
            qi_path.move_armament(engine, actor, position_of(picked_cell[0]), SCA, distance_ft=20)
    elif choice == "smoke":
        _move_smoke_veil(ctx, 20)
    else:
        _free_move(ctx, actor, 10, "choice:needle.clone_misdirection_move", "Clone Assault Misdirection")


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _stealth_advantage(engine: Any, actor: Any) -> bool:
    return any((c.data or {}).get("rule", {}).get("check_mode", {}).get("Stealth") == "ADVANTAGE"
               or c.condition_id == STEALTH for c in actor.conditions.values())


def _free_move(ctx: Any, mover: Any, feet: int, choice_id: str, name: str) -> None:
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    paths = routes(ctx.engine, mover, feet)
    if not paths:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "clone_move", mover.entity_id), ctx.actor, choice_id,
                 sorted(paths), allow_decline=True, default="decline",
                 labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=mover.entity_id,
                 prompt=f"{name}: move up to {feet} feet without provoking Opportunity Attacks?")
    if picked and picked[0] in paths:
        step(ctx.engine, mover, paths[picked[0]], SCA)


def _move_smoke_veil(ctx: Any, feet: int) -> None:
    """Move the owner's Smoke Veil up to ``feet`` feet (asked: a square within range of it)."""
    from .needle import ask, cell_options, checkpoint_id, position_of
    from ..gate2_runtime_models import Position
    from . import qi_path
    from .tabik_dark import recenter, movable, republish

    engine, actor = ctx.engine, ctx.actor
    zones_ = movable(engine, actor, "Smoke Veil")
    if not zones_:
        return
    def in_control(zone, cell):
        origin = qi_path.armament_point(actor) if zone.trigger_profile.get("armament_origin") else actor.position
        return engine.grid.distance_ft(origin, cell) <= 60

    cells = {}
    steps = feet // engine.grid.square_size_ft
    for zone in zones_:
        for x in range(engine.grid.width):
            for y in range(engine.grid.height):
                for z in range(max(0, zone.center.z - steps), zone.center.z + steps + 1):
                    cell = Position(x=x, y=y, z=z)
                    distance = int(engine.grid.distance_ft(zone.center, cell))
                    if 0 < distance <= feet and in_control(zone, cell):
                        cells[cell] = min(cells.get(cell, distance), distance)
    options, labels = cell_options(engine, actor, cells, cap=len(cells))
    if not options:
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "clone_smoke", actor.entity_id), actor,
                 "choice:needle.clone_smoke_veil", options, labels=labels, target_id=actor.entity_id,
                 name="Clone Assault Misdirection", feature_id=SCA,
                 prompt=f"Clone Assault Misdirection: move your Smoke Veil up to {feet} feet (staying within 60 feet of you).")
    if not picked or picked[0] not in options:
        return
    aim = position_of(picked[0])
    eligible = [zone for zone in zones_ if engine.grid.distance_ft(zone.center, aim) <= feet and in_control(zone, aim)]
    if not eligible:
        return
    zone = min(eligible, key=lambda row: (engine.grid.distance_ft(row.center, aim), row.zone_id))
    actor.turn_flags["moved_zone:Smoke Veil"] = True
    recenter(engine, zone, aim)
    republish(engine, zone, ctx.source)


@hook("action_completed")
def array_step_clock(engine: Any, actor: Any, economy: Any, source_definition_id: str) -> None:
    """The once-per-turn clock of the Array-buffed Shadow Step variant."""
    if str(source_definition_id).endswith(".shadow_step_array"):
        actor.turn_flags[ARRAY_STEP_KEY] = True


# ------------------------------------------------------------------------------------------------ Vanishing Technique
INVISIBLE = "condition:typed.invisible"
VANISH_STATE = "condition:typed.vanishing_state"
VANISH_REVEAL = "_vanishing_reveal"


def _vanishing_rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    return _rows(engine, actor, "vanishing_technique")


def _vanishing_active(engine: Any, actor: Any) -> bool:
    """The feature's own 1-minute state (concentration), separate from the
    Invisible condition it grants: the Harmful Action lifecycle removes and
    restores that condition without ending the feature."""
    return any(c.condition_id == VANISH_STATE for c in actor.conditions.values())


def _vanishing_invisible(actor: Any) -> Any:
    """Find this feature's grant, never an unrelated Invisible source/copy."""
    from .. import concentration

    for state in actor.conditions.values():
        if state.condition_id != VANISH_STATE:
            continue
        starts = concentration.copies(actor, state.source_definition_id)
        for held in actor.conditions.values():
            if (held.condition_id == INVISIBLE
                    and held.source_definition_id == state.source_definition_id
                    and held.source_actor_id == state.source_actor_id
                    and concentration.owner_copy(concentration.made_at(held.instance_id, held), starts)
                    == state.data.get("concentration_started_sequence")):
                return held
    return None


def _hostile(engine: Any, actor: Any, other: Any) -> bool:
    return other is not None and other.active and other.team_id != actor.team_id


@effect("vanishing_state")
def vanishing_state(ctx: Any, eff: dict[str, Any]) -> None:
    """The feature's 1-minute state marker: the Harmful Action lifecycle's
    clock (Invisible is restored at each turn end while this lasts).  The
    effect only runs from the Vanishing Technique action itself, so the
    actor already owns the feature."""
    engine, actor = ctx.engine, ctx.actor
    current = actor.concentration
    if current is None or current.source_definition_id != ctx.source:
        return
    engine._apply_condition(actor, VANISH_STATE, ctx.source, actor.entity_id,
                                expires_on=ctx.expires_on(),
                                data={"concentration_started_sequence": int(current.started_sequence),
                                      "label": "Vanishing Technique: Invisible until a Harmful Action (visible until the end of the current turn, then Invisible again)"})


def _vanishing_reveal(engine: Any, actor: Any) -> None:
    """A Harmful Action: visible until the end of the current turn, then
    Invisible again if the feature remains active (no Hide needed)."""
    from .. import concentration

    held = _vanishing_invisible(actor)
    started = (concentration.owner_copy(concentration.made_at(held.instance_id, held),
                                       concentration.copies(actor, held.source_definition_id))
               if held is not None else None)
    state = next((c for c in actor.conditions.values() if c.condition_id == VANISH_STATE
                  and held is not None and c.source_definition_id == held.source_definition_id
                  and c.source_actor_id == held.source_actor_id
                  and c.data.get("concentration_started_sequence") == started), None)
    if held is None or state is None:
        return
    stamp = f"{engine.state.round_number}:{engine.state.current_slot_index}"
    # The state instance belongs to one Concentration copy. A subsequent
    # activation cannot inherit this copy's pending restoration.
    actor.turn_flags[VANISH_REVEAL] = f"{stamp}|{state.instance_id}"
    engine._remove_condition_instance(actor, held.instance_id, held.source_definition_id,
                                     actor_id=actor.entity_id, expected=held)
    note(engine, VANISHING, actor, f"{actor.display_name}'s Harmful Action ends its Invisible until the end of the current turn "
                                       "(it is Invisible again at turn end; it need not Hide again).", (actor.entity_id,))


@hook("attack_resolved")
def vanishing_attack(ctx: Any, target: Any, hit: bool, effect: dict[str, Any]) -> None:
    """Making an attack is a Harmful Action."""
    if _vanishing_active(ctx.engine, ctx.actor):
        _vanishing_reveal(ctx.engine, ctx.actor)


@hook("after_save")
def vanishing_save(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """Forcing a hostile save is a Harmful Action (a creature's own saves —
    Concentration, death — are not forced on a hostile creature)."""
    if subject is not None and _hostile(ctx.engine, ctx.actor, subject) and _vanishing_active(ctx.engine, ctx.actor):
        _vanishing_reveal(ctx.engine, ctx.actor)


@hook("condition_applied")
def vanishing_condition(ctx: Any, name: str, subject: Any) -> None:
    """Applying a hostile condition is a Harmful Action (a creature's own
    conditions are not)."""
    if subject is not None and _hostile(ctx.engine, ctx.actor, subject) and _vanishing_active(ctx.engine, ctx.actor):
        _vanishing_reveal(ctx.engine, ctx.actor)


def _harmful_field(profile: Any) -> bool:
    """Whether an area's triggers damage (an activated harmful field)."""
    for trigger in (profile or {}).get("triggers") or []:
        for row in trigger.get("effects") or []:
            if str(row.get("type") or "") == "damage" and (row.get("dice") or int(row.get("flat") or 0)):
                return True
    return False


@hook("event")
def vanishing_harm(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """The Harmful Action triggers that arrive as events: dealing damage to a
    hostile creature, and activating a harmful field."""
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    if actor is None or not actor.active or not _vanishing_active(engine, actor) or _vanishing_invisible(actor) is None:
        return
    if event_type == "DAMAGE_COMMITTED":
        payload = kwargs.get("payload") or {}
        # Damage absorbed by temporary HP is still damage dealt. Fully
        # prevented packets have neither receipt component and do not reveal.
        if int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0) < 1:
            return
        targets = [engine.state.actors.get(target_id) for target_id in (kwargs.get("target_ids") or ())]
        if any(_hostile(engine, actor, target) for target in targets):
            _vanishing_reveal(engine, actor)
    elif event_type == "ZONE_CREATED":
        zone = (kwargs.get("payload") or {}).get("zone") or {}
        if _harmful_field(zone.get("trigger_profile")):
            _vanishing_reveal(engine, actor)


@hook("turn_end")
def vanishing_restore(engine: Any, actor: Any) -> None:
    """At the end of the turn a Harmful Action happened on: Invisible again,
    if the feature's minute has not ended."""
    from ..ext import effect_durations
    from .. import concentration

    stamp = f"{engine.state.round_number}:{engine.state.current_slot_index}"
    for holder in engine.state.actors.values():
        if not holder.active or not _vanishing_active(engine, holder):
            continue
        recorded = holder.turn_flags.get(VANISH_REVEAL)
        if not isinstance(recorded, str) or not recorded.startswith(stamp + "|"):
            continue
        del holder.turn_flags[VANISH_REVEAL]
        state = holder.conditions.get(recorded.partition("|")[2])
        if state is None or state.condition_id != VANISH_STATE or effect_durations.due(engine, state.expires_on):
            continue
        started = state.data.get("concentration_started_sequence")
        if started not in concentration.copies(holder, state.source_definition_id):
            continue
        engine._apply_condition(holder, INVISIBLE, state.source_definition_id, state.source_actor_id, expires_on=state.expires_on,
                                    data={"concentration_started_sequence": started, "label": "Invisible (Vanishing Technique)"})
        note(engine, VANISHING, holder, f"{holder.display_name} is Invisible again (Vanishing Technique).", (holder.entity_id,))


# ------------------------------------------------------------------------------------------------ Shadow Afterimage
def _afterimage(engine: Any, actor: Any) -> Any:
    from .. import summons

    return next((row for row in summons.owned_by(engine, actor.entity_id) if row.active and "shadow_afterimage" in row.entity_id
                 and engine._distance_actor_to_actor(actor, row) <= 60), None)


@effect("shadow_exchange")
def shadow_exchange(ctx: Any, eff: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    image = _afterimage(engine, actor)
    if image is None:
        return
    mine, theirs = actor.position, image.position
    actor.position, image.position = theirs, mine
    # The same shape as a teleport's (typed_executor block_movement): the replay reducer reads "destination".
    engine._append_event("MOVEMENT_COMMITTED", ctx.source, actor_id=actor.entity_id,
                         payload={"destination": theirs.model_dump(mode="json"), "path": [mine.model_dump(mode="json"), theirs.model_dump(mode="json")],
                                  "cost_ft": 0, "teleport": True, "swap_with": image.entity_id})
    engine._append_event("MOVEMENT_COMMITTED", ctx.source, actor_id=image.entity_id,
                         payload={"destination": mine.model_dump(mode="json"), "path": [theirs.model_dump(mode="json"), mine.model_dump(mode="json")],
                                  "cost_ft": 0, "teleport": True, "swap_with": actor.entity_id})
    from .. import zones

    zones.on_moved(engine, actor, mine, theirs, forced=True)
    zones.on_moved(engine, image, theirs, mine, forced=True)


# ------------------------------------------------------------------------------------------------ Hidden Strike
def unseen_for_hidden_strike(engine: Any, actor: Any, target: Any) -> bool:
    """Concealment qualifies; senses that actually see the attacker cancel it."""
    from ..target_knowledge import can_see

    return not can_see(engine, target, actor)


@hook("event")
def hidden_strike_visibility(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Remember sight at the roll, before damage can end an invisibility glamer."""
    if event_type != "ATTACK_ROLLED":
        return
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    if actor is None or not _rows(engine, actor, "hidden_strike"):
        return
    from .attack_scope import capture_roll

    frame = capture_roll(engine, kwargs)
    if frame is not None:
        target = engine.state.actors[frame["target_id"]]
        frame["ninpo_unseen"] = unseen_for_hidden_strike(engine, actor, target)


@hook("attack_roll_finished")
def hidden_strike_finished(ctx: Any, target: Any, effect: dict[str, Any], roll_id: str) -> None:
    """Copy only this completed roll's sight reading into its own rider context."""
    if not _rows(ctx.engine, ctx.actor, "hidden_strike"):
        return
    from .attack_scope import current

    frame = current(ctx.engine)
    ctx.damage_cache["ninpo_visibility"] = (roll_id, target.entity_id, bool(frame and frame.get("ninpo_unseen")))


@effect("hidden_strike_choice")
def hidden_strike_choice(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, CHOICE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, CHOICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"choice": eff.get("choice"), "label": f"Hidden Strike preference — {HIDDEN_RIDERS.get(str(eff.get('choice')), HIDDEN_RIDERS['sever'])}; no cost, choose again on each hit"})


@hook("after_hit_choice")
def hidden_strike(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    rows = _rows(engine, actor, "hidden_strike")
    if not rows or not target.active:
        return
    current = engine.state.actors[engine.state.current_actor_id]
    turn = f"{engine.state.round_number}:{engine.state.current_slot_index}:{current.entity_id}:{current.turns_started}"
    # _round_ keys survive the owner's turn reset; the value names the actual
    # current turn, including other creatures' turns and future rounds.
    if actor.turn_flags.get("_round_hidden_strike_turn") == turn:
        return
    if actor.turn_flags.get("hidden_strike") and "_round_hidden_strike_turn" not in actor.turn_flags:
        # A retained fight may carry the old boolean. Respect a use in this
        # turn only, rather than extending it over the owner's whole round.
        for event in reversed(engine.events):
            if event.event_type == "TURN_STARTED":
                break
            if event.event_type == "PASSIVE_TRIGGERED" and event.actor_id == actor.entity_id and event.source_definition_id == f"passive:{HIDDEN}":
                return
    snapshot = ctx.damage_cache.get("ninpo_visibility")
    matching = bool(snapshot and snapshot[0] and snapshot[:2] ==
                    ((ctx.attack_result or {}).get("roll_id"), target.entity_id))
    unseen = snapshot[2] if matching else unseen_for_hidden_strike(engine, actor, target)
    # Shadow Step is a Bonus Action on the owner's turn; its qualification is
    # "during the current turn", unlike Hidden Strike's once-per-turn refresh.
    stepped_this_turn = bool(actor.turn_flags.get("shadow_stepped")) and engine.state.current_actor_id == actor.entity_id
    # Shadow Clone Array: Hidden Strike may qualify when the target sees the owner
    # but cannot identify the real image among the Clones.
    cloned = bool(_rows(engine, actor, "shadow_clone_array")) and clone_count(engine, actor) >= 1 \
        and not identifies_true_body(engine, target, actor)
    if not unseen and not stepped_this_turn and not cloned:
        return
    actor.turn_flags["_round_hidden_strike_turn"] = turn
    count = 4 if clone_count(engine, actor) >= 1 else (3 if int(rows[0].get("cl") or 1) >= 17 else 2)
    dealt = next((event for event in reversed(engine.events[-30:]) if event.event_type == "DAMAGE_COMMITTED" and event.actor_id == actor.entity_id
                  and target.entity_id in (event.target_ids or ())), None)
    kind_ = str(((dealt.payload or {}) if dealt is not None else {}).get("damage_type") or "")
    from .. import typed_executor

    sub = ctx.on_hit_context(target, damage_cache={}).with_source(f"passive:{HIDDEN}")
    engine._append_event("PASSIVE_TRIGGERED", f"passive:{HIDDEN}", actor_id=actor.entity_id, target_ids=(target.entity_id,), payload={"trigger": "Hidden Strike"})
    typed_executor.run_effects(sub, [{"type": "extra_damage", "damage_label": "Hidden Strike", "applies_to": "target", "dice": {"count": count, "sides": 6},
                                      **({"damage_types": [kind_.lower()]} if kind_ and kind_ != "UNTYPED" else {}), "evidence": "Hidden Strike"}])
    if not target.active:
        return
    from .needle import ask, checkpoint_id
    from .choice_prompt import action_context

    preferred = next((str((c.data or {}).get("choice")) for c in actor.conditions.values() if c.condition_id == CHOICE), "sever")
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "hidden_strike_rider", target.entity_id), actor,
                 "choice:needle.hidden_strike_rider", list(HIDDEN_RIDERS), labels=HIDDEN_RIDERS,
                 preferred=[preferred] if preferred in HIDDEN_RIDERS else ["sever"], target_id=target.entity_id,
                 name="Hidden Strike", feature_id=HIDDEN,
                 prompt=f"Hidden Strike: {ctx.action.display_name} hit {target.display_name}; bonus damage has been applied. "
                        "Choose one rider (no action, no resource cost).",
                 prompt_context=action_context(engine, actor, ctx.action.source_definition_id, target))
    choice = picked[0] if picked and picked[0] in HIDDEN_RIDERS else "sever"
    if choice == "mislead":
        direction = ask(engine, ctx.intent, checkpoint_id(engine, "hidden_strike_direction", target.entity_id), actor,
                        "choice:needle.hidden_strike_direction", ["away", "toward"],
                        labels={"away": f"Push {target.display_name} 5 feet away from you", "toward": f"Pull {target.display_name} 5 feet toward you"},
                        target_id=target.entity_id, name="Hidden Strike — Misleading Impact", feature_id=HIDDEN,
                        prompt=f"Hidden Strike — Misleading Impact after {ctx.action.display_name}: push or pull {target.display_name} 5 feet (no action, no resource cost).",
                        prompt_context=action_context(engine, actor, ctx.action.source_definition_id, target))
        typed_executor.run_effects(sub, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away",
                                          "evidence": "Misleading Impact: Push or pull 5 feet.",
                                          **({"direction": direction[0]} if direction else {})}])
    elif choice == "withdraw":
        from .needle import cell_options, free_cells, position_of, step_to

        cells = free_cells(engine, actor, 5) if engine._effective_speed(actor) > 0 else {actor.position: 0}
        options, labels = cell_options(engine, actor, cells)
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "hidden_strike_withdraw", target.entity_id), actor,
                     "choice:needle.hidden_strike_withdraw", options, labels=labels, target_id=actor.entity_id,
                     name="Hidden Strike — Silent Withdrawal", feature_id=HIDDEN,
                     prompt=f"Hidden Strike — Silent Withdrawal after {ctx.action.display_name} hit {target.display_name}: "
                            "choose a space within 5 feet to move without provoking Opportunity Attacks (no action, no resource cost).",
                     prompt_context=action_context(engine, actor, ctx.action.source_definition_id, target))
        if picked and picked[0] in options:
            step_to(engine, actor, position_of(picked[0]), sub.source)
    elif choice == "vanish":
        from .effect_durations import token

        engine._apply_condition(actor, STEALTH, sub.source, actor.entity_id, expires_on=token("end", current.entity_id, current.turns_started),
                                data={"rule": {"check_mode": {"Stealth": "ADVANTAGE"}},
                                      "label": "Hidden Strike — Vanishing Posture: Advantage on your next Stealth check before this turn ends; no cost"})
    elif choice == "smoke":
        engine._apply_condition(target, SMOKE_MARK, sub.source, actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"owner_id": actor.entity_id, "label": f"Hidden Strike — Smoke Mark: Invisible gives no benefit against {actor.display_name} until its next turn; direction known inside its Smoke Veil; no cost"})
    else:
        typed_executor.run_effects(sub, [{"type": "condition", "condition": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN",
                                          "evidence": "Sever Awareness: Target cannot take Reactions until next turn."}])


@hook("event")
def vanishing_posture_used(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Consume the one-check benefit only after a Stealth check actually rolls."""
    if event_type != "CHECK_ROLLED":
        return
    payload = kwargs.get("payload") or {}
    if str(payload.get("check") or payload.get("skill") or "").lower() != "stealth":
        return
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    if actor is not None and any(c.condition_id == STEALTH for c in actor.conditions.values()):
        engine._remove_condition(actor, STEALTH, f"passive:{HIDDEN}")


@hook("masked_conditions")
def smoke_mark_invisible(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    """Ignore only the marked creature's Invisible benefit against its marker."""
    out = {}
    for bearer, other in ((attacker, target), (target, attacker)):
        if bearer is None or other is None or not _rows(engine, other, "hidden_strike"):
            continue
        if any(c.condition_id == SMOKE_MARK and c.data.get("owner_id") == other.entity_id for c in bearer.conditions.values()):
            out[bearer.entity_id] = {iid for iid, c in bearer.conditions.items() if c.condition_id == "condition:typed.invisible"}
    return out or None


@hook("status_description")
def smoke_mark_direction(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    """Read-only current direction for the Smoke Mark's existing status pill."""
    if holder is None or row.get("condition_id") != SMOKE_MARK:
        return None
    owner = engine.state.actors.get(data.get("owner_id"))
    if owner is None:
        return None
    from .. import zones

    inside = any(z.owner_id == owner.entity_id and z.trigger_profile.get("name") == "Smoke Veil" and zones._inside(engine, holder, z)
                 for z in zones.typed_zones(engine))
    dx, dy = holder.position.x - owner.position.x, holder.position.y - owner.position.y
    direction = " and ".join([*(["east" if dx > 0 else "west"] if dx else []), *(["south" if dy > 0 else "north"] if dy else [])]) or "at your position"
    return {"text": f"Smoke Mark: Invisible gives no benefit against {owner.display_name} until the start of its next turn. "
                    + (f"Direction from {owner.display_name}: {direction} (inside its Smoke Veil)." if inside else "Direction is known only inside its Smoke Veil."),
            "source_ability": "Hidden Strike", "handling": "No action or resource cost."}


# ------------------------------------------------------------------------------------------------ Pressure-Point Strike
PPS = "tianxia.subpath.body.shinobi.feature.pressure_point_strike"
PPS_CHOICE = "condition:typed.pressure_point_choice"
PPS_LABELS = {
    "reactions": "No Reactions until the start of its next turn",
    "speed": "Speed reduced by 10 feet until the start of its next turn",
    "attack": "Disadvantage on its next attack roll before the start of its next turn",
    "concentration": "Disadvantage on its next Concentration save before the start of its next turn",
    "whisper": "Cannot speak above a whisper until the start of its next turn",
}
PPS_OPTIONS = {key: f"prefer {label[0].lower() + label[1:]} (1 Stamina on an unarmed hit; once per turn)"
               for key, label in PPS_LABELS.items()}
PPS_OPTIONS["off"] = "off"


@hook("match_start")
def pressure_point_owner_metadata(engine: Any) -> None:
    """Expose legacy owners' decisions during AI turns without rewriting their saved bundle.

    Copy only engine-local passive metadata: no fight state, events or input documents change.
    """
    for actor_id, rows in (getattr(engine, "typed_passive_rows", {}) or {}).items():
        if not any(row.get("block") == "ninpo" and row.get("kind") in ("pressure_point", "hidden_strike") for row in rows):
            continue
        engine.typed_passive_rows[actor_id] = [
            {**row, "choice_owner": True} if row.get("block") == "ninpo" and row.get("kind") in ("pressure_point", "hidden_strike") else row
            for row in rows]


@hook("compile_actions")
def pressure_point_choices(info: dict[str, Any]) -> list[Any] | None:
    if PPS not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.ninpo.pressure_point.{key}", display_name=f"Pressure-Point Strike: {label}",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"setting_only": True, "typed": {"effects": [{"type": "pressure_point_choice", "choice": key}], "numbers": info["numbers"], "duration": {"kind": "instant"},
                              "riders": []}, "expected_damage": 0, "player_only": True})
        for key, label in PPS_OPTIONS.items()]


@effect("pressure_point_choice")
def pressure_point_choice(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, PPS_CHOICE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, PPS_CHOICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"choice": eff.get("choice"), "label": f"Pressure-Point Strike: {PPS_OPTIONS.get(str(eff.get('choice')), '')}"})


@hook("after_hit")
def pressure_point_strike(ctx: Any, target: Any, kind: str) -> None:
    """Once per turn, 1 Stamina on an unarmed hit: choose after a failed Constitution save.

    Standing picks are AI/default preferences; "off" keeps the Stamina. Success only denies Reactions.
    """
    engine, actor = ctx.engine, ctx.actor
    if kind != "unarmed" or not target.active or actor.turn_flags.get("pressure_point_strike") or not _rows(engine, actor, "pressure_point"):
        return
    choice = next((str((c.data or {}).get("choice")) for c in actor.conditions.values() if c.condition_id == PPS_CHOICE), "reactions")
    if choice == "off" or actor.resources.get(STAMINA, 0) < 1:
        return
    from .needle import ask, checkpoint_id

    picked = ask(engine, ctx.intent, checkpoint_id(engine, "pressure_point", target.entity_id), actor, "choice:needle.pressure_point_strike", ["use"],
                 labels={"use": f"1 Stamina: {target.display_name} makes a Constitution save"}, allow_decline=True, target_id=target.entity_id,
                 name="Pressure-Point Strike", feature_id=PPS,
                 prompt=f"Pressure-Point Strike: {ctx.action.display_name} hit {target.display_name}. Spend 1 Stamina "
                        "(once per turn) for a Constitution save, then choose an effect on failure; on success it cannot "
                        "take Reactions until the start of its next turn.")
    if not picked:
        return
    engine._spend_resource(actor, STAMINA, 1, f"passive:{PPS}")
    pressure_point(ctx, target, preferred=choice)


def pressure_point(ctx: Any, target: Any, *, preferred: str = "reactions") -> None:
    """Shared helper (shinobi.py's Assassination applies it without Stamina): the once-per-turn Constitution save and its asked
    failed-save effect. Nothing happens when this turn's use is spent."""
    engine, actor = ctx.engine, ctx.actor
    if actor.turn_flags.get("pressure_point_strike") or target is None or not target.active:
        return
    actor.turn_flags["pressure_point_strike"] = True
    until = "START_OF_TARGET_NEXT_TURN"
    labels = {k: v for k, v in PPS_OPTIONS.items() if k != "off"}
    from .. import typed_executor

    sub = typed_executor.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {}).with_source(f"passive:{PPS}")
    typed_executor.run_effects(sub, [{"type": "save", "ability": "con", "applies_to": "target",
                                      "on_fail": [{"type": "pressure_point_result", "preferred": preferred if preferred in labels else "reactions"}],
                                      "on_success": [{"type": "condition", "condition": "reaction_denied", "applies_to": "target", "expires_on": until}],
                                      "evidence": "Pressure-Point Strike: Constitution saving throw"}])


def _pps_results(until: str) -> dict[str, list[dict[str, Any]]]:
    return {"reactions": [{"type": "condition", "condition": "reaction_denied", "applies_to": "target", "expires_on": until}],
            "speed": [{"type": "speed", "flat": -10, "applies_to": "target", "expires_on": until}],
            "attack": [{"type": "pressure_point_attack"}],
            # Both real since 2026-09-29 (combat/concentration.py save_mode; combat/speech.py Silenced).
            "concentration": [{"type": "disadvantage", "applies_to": "target", "on": "its next Concentration saving throw", "expires_on": until,
                               "evidence": "Pressure-Point Strike: Disadvantage on its next Concentration saving throw before the start of its next turn."}],
            "whisper": [{"type": "condition", "condition": "silenced", "applies_to": "target", "expires_on": until,
                         "evidence": "Pressure-Point Strike: it cannot speak above a whisper until the start of its next turn."}]}


@effect("pressure_point_failed_choice")  # retained saved effects share the same implementation
@effect("pressure_point_result")
def pressure_point_result(ctx: Any, eff: dict[str, Any]) -> None:
    """The failed-save effect, asked after the failure (the standing button's choice offered first)."""
    from .. import typed_executor
    from .needle import ask, checkpoint_id
    from .choice_prompt import action_context

    target = ctx.target
    if target is None or not target.active:
        return
    labels = PPS_LABELS
    preferred = str(eff.get("preferred") or "reactions")
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "pressure_point_result", target.entity_id), ctx.actor, "choice:needle.pressure_point_result",
                 list(labels), labels=labels, preferred=[preferred], target_id=target.entity_id, name="Pressure-Point Strike", feature_id=PPS,
                 prompt=f"Pressure-Point Strike: {target.display_name} failed its Constitution save after {ctx.action.display_name}. "
                        "Choose one effect until the start of its next turn. Normally this use costs 1 Stamina (once per turn); "
                        "Assassination grants it without spending Stamina.",
                 prompt_context=action_context(ctx.engine, ctx.actor, ctx.action.source_definition_id, target))
    choice = picked[0] if picked and picked[0] in labels else preferred
    typed_executor.run_effects(ctx, _pps_results("START_OF_TARGET_NEXT_TURN")[choice])


@effect("pressure_point_attack")
def pressure_point_attack(ctx: Any, eff: dict[str, Any]) -> None:
    if ctx.target is not None:
        from ..typed_executor import stated_expiry

        # Resolve "its next turn" for the target, including a hit on another creature's turn.
        expires = stated_expiry(ctx, {"expires_on": "START_OF_TARGET_NEXT_TURN"}, ctx.target)
        ctx.engine._add_modifier(ctx.target, ctx.source, "attack_mode", "SET", "DISADVANTAGE", "NEXT_ATTACK", expires_on=expires)
