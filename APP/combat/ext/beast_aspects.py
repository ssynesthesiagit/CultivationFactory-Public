"""Hundred-Beast Scripture: Beast Aspects (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, "26. Hundred-Beast Scripture" ("Beast Aspects" and its Normalized Procedure).
The features carry one typed row each, ``{"type": "path_passive", "kind": "beast_aspects", "role": ...}`` (roles "initiate",
"paired", "chimera", "king"); Serpent's reach is a reach_bonus row (combat/ext/reach_bonus.py) gated by its Aspect state.

Known Aspects   "Choose and record three" (four with Paired Beast Body): the sheet has no place for them, so they are a standing
                choose-N record (combat/ext/menus.py, "Choose Beast Aspects: <Aspect>" free buttons, player only); a fighter who
                never set them knows the first three (four) printed. Chimera Meridian Network knows all eight.
Active Aspects  named states ``beast_aspect_<name>`` (combat/ext/states.py). At the start of each of the owner's turns it chooses
                (asked) 1 known Aspect, 2 with Paired Beast Body, 3 with Chimera Meridian Network; the previous choice is offered
                first. Chimera: before the first turn of the fight its first three Aspects are active (the table has no choice
                point before Initiative); once per round when a hostile creature ends its turn, it may replace one active Aspect
                with an inactive one (asked). Sovereign of Ten Thousand Beasts makes all eight active; when it ends the owner
                chooses three that stay active until its next turn start.
While active:
  Tiger    once per turn on a hit, +Proficiency Bonus damage (Bludgeoning, Piercing or Slashing; the type that lands hardest).
  Crane    Speed +10 feet. (Jumps and falling are not part of the table.)
  Serpent  +5 ft unarmed reach during its own turn; Advantage on checks and saves to escape Grappled or Restrained.
  Ox       one size larger for Grappling and Shoving (two during Sovereign, replacing it); Advantage on saves against
           forced movement and Prone.
  Turtle   +1 AC; the first Bludgeoning, Piercing or Slashing packet each round is reduced by Proficiency Bonus.
  Wolf     the first attack each turn against a creature within 5 feet of a conscious ally has Advantage.
  Ape      Advantage on its Grapples and Shoves (as the table runs those, the target's save has Disadvantage). Climbing,
           lifting and holding are the GM's.
  Falcon   its Thrown weapon attacks reach twice the normal and long range with no long-range Disadvantage: a
           "(Falcon range)" variant of each thrown attack, offered while Falcon is active.
Beast King's Technique  once per turn (twice during Sovereign: different attacks, different effects) after a hit with an
           unarmed strike or a weapon attack: 1 Stamina (asked) for one active Aspect's Beast King effect.
Sovereign of Ten Thousand Beasts  state "sovereign_of_ten_thousand_beasts": all Aspects, unarmed 1d12 when larger, once per
           turn +3d8 B/P/S on a hit, two Beast King uses, two sizes larger for Grapple/Shove (Darkvision: combat/rules/senses.json).
Every hook returns early for a creature without these rows.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.hundred_beast_scripture.feature."
ASPECTS = ("Tiger", "Crane", "Serpent", "Ox", "Turtle", "Wolf", "Ape", "Falcon")
SOVEREIGN = "sovereign_of_ten_thousand_beasts"
MENU_ID = "beast_aspects_known"
ASPECT_EFFECTS = {
    "Tiger": "Once per turn when you hit, add your Proficiency Bonus as Bludgeoning, Piercing or Slashing damage.",
    "Crane": "Your Speed increases by 10 feet. Tripled jumps and reduced falling damage are handled by the GM.",
    "Serpent": "On your turn, your unarmed reach increases by 5 feet. You have Advantage on checks and saves to escape Grappled or Restrained.",
    "Ox": "Count as one size larger for Grappling and Shoving; gain Advantage on saves against forced movement and being knocked Prone. Carrying and lifting are handled by the GM.",
    "Turtle": "Gain +1 Armor Class. Reduce the first Bludgeoning, Piercing or Slashing damage you take each round by your Proficiency Bonus.",
    "Wolf": "Your first attack each turn against a creature within 5 feet of a conscious ally has Advantage.",
    "Ape": "Gain Advantage on Grapples and Shoves. Climbing, lifting and holding benefits are handled by the GM.",
    "Falcon": "Double your thrown weapons' normal and long ranges; long range does not impose Disadvantage. Drawing benefits are handled by the GM.",
}
KING_LABELS = {"Tiger": "Tiger: +2d8 damage of the attack's type", "Crane": "Crane: move 15 feet without provoking",
               "Serpent": "Serpent: it cannot take Reactions and its Speed is 10 feet lower until your next turn",
               "Ox": "Ox: Strength save; pushed 15 feet or knocked Prone (5 feet on a success)",
               "Turtle": "Turtle: Temporary Hit Points twice your Proficiency Bonus and +1 AC until your next turn",
               "Wolf": "Wolf: an ally within 30 feet moves 10 feet without provoking and has Advantage on its next attack against it",
               "Ape": "Ape: Grapple or Shove it now with Advantage", "Falcon": "Falcon: move 20 feet without provoking"}


def _rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "path_rider" and row.get("kind") == "beast_aspects"]


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in _rows(engine, actor)}


def _state(aspect: str) -> str:
    return "beast_aspect_" + aspect.lower()


def _sovereign(engine: Any, actor: Any) -> bool:
    from .states import active

    return bool(active(engine, actor, SOVEREIGN))


def known(engine: Any, actor: Any) -> list[str]:
    roles = _roles(engine, actor)
    if "chimera" in roles:
        return list(ASPECTS)
    from .menus import picks

    chosen = picks(engine, actor, MENU_ID)
    return [a for a in ASPECTS if a in chosen] or list(ASPECTS[:4 if "paired" in roles else 3])


def active(engine: Any, actor: Any) -> list[str]:
    from .states import active as state_active

    return [a for a in ASPECTS if state_active(engine, actor, _state(a))]


def is_active(engine: Any, actor: Any, aspect: str) -> bool:
    from .states import active as state_active

    return actor is not None and bool(state_active(engine, actor, _state(aspect))) and bool(_rows(engine, actor))


def _count(roles: set[str]) -> int:
    return 3 if "chimera" in roles else 2 if "paired" in roles else 1 if "initiate" in roles else 0


@hook("decision_text")
def aspect_decision_text(engine: Any, context: dict[str, Any], printed_rules: dict[str, str]) -> dict[str, Any] | None:
    """Explain the existing Aspect selectors; presentation only, inert for nonowners."""
    choice = context.get("reaction_source_id")
    features = {"choice:needle.beast_aspects": "beast_scripture_initiate",
                "choice:needle.chimera_swap": "chimera_meridian_network",
                "choice:needle.sovereign_end": SOVEREIGN}
    if choice not in features:
        return None
    actor = engine.state.actors.get(context.get("reactor_id"))
    if actor is None or not _rows(engine, actor):
        return None
    swap = choice == "choice:needle.chimera_swap"
    duration = ("until your next legal Aspect selection or replacement" if swap
                else "until the start of your next turn")
    descriptions = {}
    for option in (context.get("extension_choice") or {}).get("option_ids") or []:
        old, _, aspect = option.partition(">") if swap else ("", "", option)
        if aspect in ASPECT_EFFECTS:
            replacement = f"End your {old} Aspect and activate {aspect}. " if swap else f"Activate {aspect}. "
            descriptions[option] = (f"{replacement}{ASPECT_EFFECTS[aspect]} These benefits affect you {duration}. "
                                    "No action or Stamina cost.")
    return {"feature_id": PREFIX + features[choice], "cost": "No action or Stamina cost",
            "summary": (f"Replace one active Beast Aspect for {actor.display_name}; the new benefits begin immediately {duration}."
                        if swap else f"Choose active Beast Aspects for {actor.display_name}. Their benefits last {duration}."),
            "option_descriptions": descriptions,
            "table_note": "Aspect choices do not change attacks, damage, movement or saves already resolved."}


def set_active(engine: Any, actor: Any, chosen: list[str], source: str) -> None:
    """Exactly ``chosen`` active: other Aspect states end, missing ones start (an unchanged one keeps its instance)."""
    from .states import PREFIX as STATE, slug

    want = {STATE + slug(_state(a)) for a in chosen}
    for iid, held in list(actor.conditions.items()):
        if held.condition_id.startswith(STATE + "beast_aspect_") and held.condition_id not in want:
            del actor.conditions[iid]
            engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": held.condition_id, "instance_id": iid})
    have = {c.condition_id for c in actor.conditions.values()}
    for aspect in chosen:
        if STATE + slug(_state(aspect)) not in have:
            engine._apply_condition(actor, STATE + slug(_state(aspect)), source, actor.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"label": f"{aspect} Aspect", "name": _state(aspect)})


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


@hook("compile_actions")
def known_menu(info: dict[str, Any]) -> list[Any] | None:
    """The "Choose Beast Aspects: <Aspect>" record buttons (not for Chimera, which knows them all)."""
    owned = set(info["owned_ids"])
    if PREFIX + "beast_scripture_initiate" not in owned or PREFIX + "chimera_meridian_network" in owned:
        return None
    from .menus import toggle_actions

    count = 4 if PREFIX + "paired_beast_body" in owned else 3
    row = {"type": "menu", "id": MENU_ID, "name": "Beast Aspects", "label": f"Your {count} known Beast Aspects", "count": count,
           "options": list(ASPECTS), "default": list(ASPECTS[:count])}
    return toggle_actions(info, row, carry=True)


@hook("turn_start_choice")
def choose_aspects(engine: Any, actor: Any) -> None:
    count = _count(_roles(engine, actor))
    if count <= 0 or not actor.active:
        return
    if _sovereign(engine, actor):
        set_active(engine, actor, list(ASPECTS), PREFIX + SOVEREIGN)
        return
    from .needle import ask, checkpoint_id

    options = known(engine, actor)
    count = min(count, len(options))
    current = [a for a in active(engine, actor) if a in options]
    preferred = list(dict.fromkeys(current + options))[:count]
    picked = ask(engine, _intent(engine), checkpoint_id(engine, "beast_aspects", actor.entity_id), actor, "choice:needle.beast_aspects", options,
                 minimum=count, maximum=count, preferred=preferred, target_id=actor.entity_id, name="Beast Aspects",
                 prompt=f"Beast Aspects: choose {count} active Aspect{'s' if count > 1 else ''} for {actor.display_name} until its next turn.")
    set_active(engine, actor, [a for a in options if a in (picked or preferred)][:count], PREFIX + "beast_scripture_initiate")


@hook("turn_start")
def chimera_at_initiative(engine: Any, actor: Any) -> None:
    """Chimera: "When Initiative is rolled, choose active Aspects before the first turn" -- its first three, before any turn."""
    for owner in engine.state.actors.values():
        if owner.active and int(owner.turns_started) == 0 and "chimera" in _roles(engine, owner) and not active(engine, owner):
            set_active(engine, owner, list(ASPECTS[:3]), PREFIX + "chimera_meridian_network")


@hook("turn_end")
def chimera_swap(engine: Any, actor: Any) -> None:
    """Chimera Meridian Network: once per round, when a hostile creature ends its turn, replace one active Aspect (asked)."""
    for owner in list(engine.state.actors.values()):
        if not owner.active or owner.team_id == actor.team_id or "chimera" not in _roles(engine, owner):
            continue
        if owner.turn_flags.get("_round_chimera_swap") == int(engine.state.round_number):
            continue
        current = active(engine, owner)
        options = [f"{old}>{new}" for old in current for new in ASPECTS if new not in current]
        if not options:
            continue
        from .needle import ask, checkpoint_id

        picked = ask(engine, _intent(engine), checkpoint_id(engine, "chimera_swap", owner.entity_id), owner, "choice:needle.chimera_swap", options,
                     allow_decline=True, default="decline", labels={o: "Replace {} with {}".format(*o.split(">")) for o in options},
                     prompt=f"Chimera Meridian Network: {actor.display_name} ended its turn; {owner.display_name} may replace one active Aspect.",
                     target_id=owner.entity_id, name="Chimera Meridian Network")
        if picked and picked[0] in options:
            owner.turn_flags["_round_chimera_swap"] = int(engine.state.round_number)
            old, new = picked[0].split(">")
            set_active(engine, owner, [new if a == old else a for a in current], PREFIX + "chimera_meridian_network")


@effect("beast_sovereign")
def sovereign_starts(ctx: Any, row: dict[str, Any]) -> None:
    """"All Aspects become active" (the state itself is the entry's own "state" row)."""
    set_active(ctx.engine, ctx.actor, list(ASPECTS), PREFIX + SOVEREIGN)


@hook("effect_expiring")
def sovereign_ends(engine: Any, holder: Any, row: Any) -> None:
    """"When the duration ends, choose three Aspects to remain active until the start of your next turn"."""
    from .states import PREFIX as STATE

    if getattr(row, "condition_id", None) != STATE + SOVEREIGN or not holder.active:
        return
    from .needle import ask, checkpoint_id

    picked = ask(engine, _intent(engine), checkpoint_id(engine, "sovereign_end", holder.entity_id), holder, "choice:needle.sovereign_end", list(ASPECTS),
                 minimum=3, maximum=3, preferred=list(ASPECTS[:3]), target_id=holder.entity_id, name="Sovereign of Ten Thousand Beasts",
                 prompt="Sovereign of Ten Thousand Beasts ends: choose three Aspects that stay active until your next turn.")
    set_active(engine, holder, [a for a in ASPECTS if a in (picked or ASPECTS[:3])][:3], PREFIX + SOVEREIGN)


# ------------------------------------------------------------------------------------------------------------ benefits
def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _kind(save_row: dict[str, Any]) -> str | None:
    """"grapple" or "shove" for the typed save a Grapple or Shove rolls (what its failure imposes), else None."""
    for row in (save_row or {}).get("on_fail") or []:
        if isinstance(row, dict) and row.get("type") == "condition" and row.get("condition") == "grappled":
            return "grapple"
        if isinstance(row, dict) and ((row.get("type") == "condition" and row.get("condition") == "prone") or row.get("type") == "forced_movement"):
            return "shove"
    return None


@hook("speed")
def crane_speed(engine: Any, actor: Any) -> int | None:
    return 10 if is_active(engine, actor, "Crane") else None


@hook("escape_mode")
def serpent_escape(engine: Any, escaper: Any, grips: Any) -> str | None:
    return "ADVANTAGE" if is_active(engine, escaper, "Serpent") else None


@hook("escape_save_mode")
def serpent_escape_save(engine: Any, escaper: Any, grips: Any) -> str | None:
    return "ADVANTAGE" if is_active(engine, escaper, "Serpent") else None


@hook("size_steps")
def ox_size(engine: Any, creature: Any, role: str, purposes: Any) -> int | None:
    if role != "act" or not set(purposes) & {"grapple", "shove"} or not _rows(engine, creature):
        return None
    if _sovereign(engine, creature):
        return 2  # "two additional sizes larger" replaces Ox's one
    return 1 if is_active(engine, creature, "Ox") else None


@hook("save")
def aspect_saves(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    modes = []
    if subject is not None and is_active(ctx.engine, subject, "Ox") and {"forced_movement", "prone"} & set(named or ()):
        modes.append("ADVANTAGE")
    if subject is not None and ctx.actor is not subject and is_active(ctx.engine, ctx.actor, "Ape") \
            and any(_kind(row) for row in ctx.typed.get("effects") or [] if isinstance(row, dict) and row.get("type") == "save"):
        modes.append("DISADVANTAGE")
    return {"bonus": 0, "modes": modes} if modes else None


@hook("ac")
def turtle_ac(engine: Any, target: Any) -> int | None:
    return 1 if is_active(engine, target, "Turtle") else None


@hook("damage_reduction")
def turtle_first_packet(engine: Any, target: Any, damage_type: str, typed: Any, source_actor_id: Any, applied: bool = False) -> int | None:
    if str(damage_type).upper() not in ("BLUDGEONING", "PIERCING", "SLASHING") or not is_active(engine, target, "Turtle"):
        return None
    if target.turn_flags.get("_round_turtle") == int(engine.state.round_number):
        return None
    if applied:
        target.turn_flags["_round_turtle"] = int(engine.state.round_number)
    return int(target.proficiency_bonus or 2)


def _conscious(engine: Any, creature: Any) -> bool:
    return creature.active and creature.current_hp > 0 and not any(c.condition_id.endswith(".unconscious") for c in creature.conditions.values())


@hook("attack_mode")
def wolf_advantage(ctx: Any, target: Any) -> str | None:
    engine, actor = ctx.engine, ctx.actor
    if target is None or engine.state.current_actor_id != actor.entity_id or not is_active(engine, actor, "Wolf"):
        return None
    if actor.turn_flags.get("_round_wolf_first") == _stamp(engine):
        return None
    if not any(other is not actor and other.team_id == actor.team_id and _conscious(engine, other)
               and engine._distance_actor_to_actor(other, target) <= 5 for other in engine.state.actors.values()):
        return None  # an attack that does not qualify does not use the benefit
    actor.turn_flags["_round_wolf_first"] = _stamp(engine)
    return "ADVANTAGE"


@hook("compile_actions")
def falcon_range(info: dict[str, Any]) -> list[Any] | None:
    if PREFIX + "beast_scripture_initiate" not in info["owned_ids"]:
        return None
    out = []
    for action in info["actions"]:
        typed = (action.parameters or {}).get("typed") or {}
        weapon = typed.get("weapon") or {}
        if not typed.get("long_range_ft") or "thrown" not in str(weapon.get("properties") or "").lower() or typed.get("opportunity_of") \
                or (action.parameters or {}).get("falcon_range"):
            continue
        far = int(typed["long_range_ft"]) * 2
        out.append(action.model_copy(update={
            "source_definition_id": action.source_definition_id + ".falcon", "display_name": action.display_name + " (Falcon range)",
            "range_ft": far, "parameters": {**action.parameters, "falcon_range": True,
                                            "typed": {**typed, "range_ft": far, "long_range_ft": far}}}))
    return out or None


@hook("candidate_allowed")
def falcon_offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if not (getattr(action, "parameters", None) or {}).get("falcon_range"):
        return None
    return None if is_active(engine, actor, "Falcon") else False


@hook("attack_damage")
def sovereign_die(ctx: Any, dice: Any) -> Any:
    """Sovereign: "Unarmed strikes deal 1d12 before modifiers" -- the larger die wins, never both."""
    if dice is None or not _sovereign(ctx.engine, ctx.actor) or not _rows(ctx.engine, ctx.actor):
        return None
    unarmed = ".natural." in ctx.source or any(isinstance(e, dict) and e.get("type") == "attack" and e.get("attack_kind") == "unarmed"
                                              for e in ctx.typed.get("effects") or [])
    if not unarmed or 13 <= int(dice.count) * (int(dice.sides) + 1):
        return None
    return dice.model_copy(update={"count": 1, "sides": 12})


# ------------------------------------------------------------------------------------ Tiger, Sovereign, Beast King
@hook('row_allowed')
def beast_king_activation_owner(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    """The after-hit plug-in owns the choice and payment, including old catalogs.

    Older compilers also emitted a generic paid passive for this same owned
    feature. Keep that saved row inert rather than charging a second Stamina.
    """
    if (row.get('block') == 'generic'
            and row.get('feature_id') == PREFIX + 'beast_king_s_technique'
            and 'king' in _roles(engine, actor)):
        return False
    return None


def _sub(ctx: Any, target: Any, **numbers: Any) -> Any:
    from .. import typed_executor as te

    typed = {**ctx.typed, "numbers": {**(ctx.typed.get("numbers") or {}), **numbers}}
    return te.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, typed, [target], target, {})


@hook("after_hit")
def tiger_and_beast_king(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    rows = _rows(engine, actor)
    if target is None or not target.active or not rows or target.team_id == actor.team_id:
        return
    from .. import typed_executor as te

    physical = ["bludgeoning", "piercing", "slashing"]
    if is_active(engine, actor, "Tiger") and actor.turn_flags.get("_round_tiger") != _stamp(engine):
        actor.turn_flags["_round_tiger"] = _stamp(engine)
        te.run_effects(_sub(ctx, target), [{"type": "extra_damage", "applies_to": "target", "flat": int(actor.proficiency_bonus or 2),
                                            "damage_types": physical, "evidence": "Tiger Aspect: + Proficiency Bonus"}])
    sovereign = _sovereign(engine, actor)
    if sovereign and target.active and actor.turn_flags.get("_round_sovereign_hit") != _stamp(engine):
        actor.turn_flags["_round_sovereign_hit"] = _stamp(engine)
        te.run_effects(_sub(ctx, target), [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 3, "sides": 8},
                                            "damage_types": physical, "evidence": "Sovereign of Ten Thousand Beasts: + 3d8"}])
    if "king" in _roles(engine, actor) and kind in ("unarmed", "weapon") and target.active:
        _beast_king(ctx, target, sovereign, next(row for row in rows if row.get("role") == "king"))


def _beast_king(ctx: Any, target: Any, sovereign: bool, row: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    if int(actor.resources.get("resource:core.stamina", 0) or 0) < 1:
        return
    used = [u for u in list(actor.turn_flags.get("_round_beast_king") or []) if str(u).startswith(_stamp(engine) + "|")]
    if len(used) >= (2 if sovereign else 1):
        return
    options = [a for a in active(engine, actor) if a not in {str(u).split("|")[1] for u in used}]
    if not options:
        return
    from .needle import ask, checkpoint_id

    picked = ask(engine, ctx.intent, checkpoint_id(engine, "beast_king", target.entity_id), actor, "choice:needle.beast_king", options, allow_decline=True,
                 labels={o: KING_LABELS[o] for o in options}, target_id=target.entity_id, name="Beast King's Technique",
                 prompt=f"Beast King's Technique: {ctx.action.display_name} hit {target.display_name}. Spend 1 Stamina for one active Aspect's effect?")
    if not picked or picked[0] not in options:
        return
    actor.turn_flags["_round_beast_king"] = [*used, f"{_stamp(engine)}|{picked[0]}"]
    engine._spend_resource(actor, "resource:core.stamina", 1, PREFIX + "beast_king_s_technique")
    note(engine, PREFIX + "beast_king_s_technique", actor, f"Beast King's Technique ({picked[0]}).", (target,))
    king_effect(_sub(ctx, target, save_dc=int(row.get("save_dc") or (ctx.typed.get("numbers") or {}).get("save_dc") or 10)), target, picked[0])


def king_effect(ctx: Any, target: Any, aspect: str) -> None:
    from .. import typed_executor as te

    if aspect == "Tiger":
        weapon = ctx.typed.get("weapon") or {}
        kinds = [str(k).lower() for k in (weapon.get("damage_types") or [weapon.get("damage_type") or "bludgeoning"])]
        te.run_effects(ctx, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": kinds}])
    elif aspect in ("Crane", "Falcon"):
        _move(ctx, ctx.actor, 15 if aspect == "Crane" else 20, "choice:needle.beast_king_move")
    elif aspect == "Serpent":
        te.run_effects(ctx, [{"type": "reaction_denied", "applies_to": "target", "duration": "until_start_of_your_next_turn"},
                             {"type": "speed", "applies_to": "target", "flat": -10, "duration": "until_start_of_your_next_turn"}])
    elif aspect == "Ox":
        te.run_effects(ctx, [{"type": "save", "ability": "str", "evidence": "Beast King's Technique (Ox): Strength saving throw",
                              "on_fail": [{"type": "path_results", "family": "beast_king_ox", "name": "Beast King's Technique", "count": 1,
                                           "prompt": "Beast King's Technique (Ox): {target} failed its save; push it 15 feet or knock it Prone.",
                                           "options": [{"label": "Push 15 feet", "effects": [{"type": "forced_movement", "applies_to": "target", "distance_ft": 15, "direction": "away"}]},
                                                       {"label": "Knock Prone", "effects": [{"type": "condition", "applies_to": "target", "condition": "prone"}]}]}],
                              "on_success": [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away"}]}])
    elif aspect == "Turtle":
        te.run_effects(ctx, [{"type": "temp_hp", "applies_to": "self", "formula": "double_pb"},
                             {"type": "ac_bonus", "applies_to": "self", "flat": 1, "duration": "until_start_of_your_next_turn"}])
    elif aspect == "Wolf":
        _wolf(ctx, target)
    elif aspect == "Ape":
        _ape(ctx, target)


def _move(ctx: Any, mover: Any, feet: int, choice_id: str, prompt: str = "") -> None:
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    paths = routes(ctx.engine, mover, feet)
    if not paths:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "beast_king_move", mover.entity_id), ctx.actor, choice_id, sorted(paths),
                 allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=mover.entity_id,
                 prompt=prompt or f"Beast King's Technique: {mover.display_name} may move up to {feet} feet without provoking Opportunity Attacks.")
    if picked and picked[0] in paths:
        step(ctx.engine, mover, paths[picked[0]], PREFIX + "beast_king_s_technique")


def _wolf(ctx: Any, target: Any) -> None:
    from .effect_durations import token
    from .needle import ask, checkpoint_id

    engine = ctx.engine
    allies = [a for a in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if a.active and a.team_id == ctx.actor.team_id
              and a is not ctx.actor and engine._distance_actor_to_actor(ctx.actor, a) <= 30]
    if not allies:
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "beast_wolf", ctx.actor.entity_id), ctx.actor, "choice:needle.beast_king_wolf",
                 [a.entity_id for a in allies], labels={a.entity_id: a.display_name for a in allies}, target_id=target.entity_id,
                 prompt=f"Beast King's Technique (Wolf): which ally moves 10 feet and has Advantage on its next attack against {target.display_name}?")
    ally = engine.state.actors.get(picked[0]) if picked else None
    if ally is None:
        return
    _move(ctx, ally, 10, "choice:needle.beast_king_wolf_move", f"Beast King's Technique (Wolf): {ally.display_name} may move up to 10 feet without provoking.")
    engine._add_modifier(ally, PREFIX + "beast_king_s_technique", "attack_mode_vs", "SET", f"ADVANTAGE:{target.entity_id}", "NEXT_ATTACK",
                         expires_on=token("end", ally.entity_id, int(ally.turns_started) + (0 if engine.state.current_actor_id == ally.entity_id else 1)))


def _ape(ctx: Any, target: Any) -> None:
    """"Attempt to Grapple or Shove immediately without another action", with Advantage (Ape's, via aspect_saves)."""
    from .grapple_attempts import attempt

    attempt(ctx.engine, ctx.actor, target, ctx.intent, choice_id="choice:needle.beast_king_ape",
            prompt=f"Beast King's Technique (Ape): Grapple or Shove {target.display_name}?")
