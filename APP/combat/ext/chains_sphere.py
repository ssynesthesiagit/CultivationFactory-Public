"""The Chains sphere's chassis at the table: Bound, Tethers, Chain Objects and Prisoner's Bell (rider lane C15, 2026-09-30;
BLOCKED_CENSUS.md row 31: "escaped" event, Chain Objects/Tethers).

Printed chassis (Sphere Compendium, Chains: Tethers, Chain Objects, Bound):

Bound      "Bound is a sphere-specific state, not a standard condition. A Bound creature: has its Speed reduced by 10 feet;
           cannot Dash; has Disadvantage on checks made to escape Grappled, Restrained, shackled, tied, or physically bound
           states; cannot willingly increase the distance from the Tether beyond the Tether's maximum length."
           The typed condition ``bound`` (combat/rules/typed_conditions.json: no_dash, read by combat/ext/no_dash.py). Here:
           Speed -10 (``speed``; several Bound instances do not stack), Disadvantage on its own escape checks against a grip,
           restraint, pin or Bound (``escape_mode``).
Tethers    "a Tether breaks if its endpoints exceed that maximum length through movement the talent cannot prevent; a Tether
           does not automatically prevent teleportation". A Bound row with ``"condition_data": {"tether_ft": 30}`` (Set the
           Tether) is tied to the creature that applied it: its Move squares beyond that are not offered (shared tether limit in
           combat/ext/move_limits.py). When a teleport, a push/pull or the anchor's own move leaves the two farther apart than
           that, the tether breaks: that Bound ends (CONDITION_REMOVED, reason TETHER_BROKEN). If the Bound creature itself
           was moved, that is an escape -- teleportation or forced movement -- reported to combat/ext/hold_escapes.py.
Chain Objects  "Unless a talent lists different statistics, a Chain Object has: AC 15 + half your Proficiency Bonus, rounded
           down; Hit Points equal to 5 x your CL; Resistance to Bludgeoning, Piercing, and Slashing damage; Immunity to Poison
           and Psychic damage. If a Chain Object is destroyed, the effect creating it ends." Typed as ``bound_object`` rows
           (combat/ext/bound_objects.py; "ac": "15+half_pb", "hp": "5*cl", "kind": "chain"). Destroying one reports an escape
           (the prisoner breaking out: physical; anyone else: outside assistance).
Prisoner's Bell  "When a creature escapes one of your Chains talents, destroys one of your Chain Objects, teleports away from one
           of your Tethers ... you may immediately learn the direction of its escape and whether it used physical movement,
           teleportation, spiritual escape, forced movement, or outside assistance. If the creature is within 300 feet, you
           also hear a chain-bell sound that no one else hears unless you permit it. Once per short rest, when Prisoner's Bell
           triggers, you may use Restraining Hook against that creature without spending CP if it is within range."
           A feature block ``prisoners_bell`` (combat/rules/feature_blocks.d/riders_c15.json) marks the owner; the
           ``hold_escaped`` hook answers when the hold came from one of the owner's own Chains-sphere abilities: one log line
           says who escaped, how and where it is; then, once a fight (a short rest never falls inside one), the owner may use
           Restraining Hook on that creature -- or on the creature that destroyed the Chain Object -- if it is within 30 feet
           and the owner has its Reaction: Restraining Hook's own rows (a Strength save; movement 0 or 10 feet less), its
           Reaction spent, no CP. A player is asked; an AI owner uses it.
Every hook returns at once for a creature without a Bound condition, a tether or the feature block.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note

SPHERE = "tianxia.sphere.chains"
BOUND = "condition:typed.bound"
BELL = "prisoners_bell"
BELL_SOURCE = "tianxia.talent.chains.prisoner_s_bell"
HOOK = "tianxia.talent.chains.restraining_hook"
USED = "_round_prisoners_bell_free_hook"  # once a fight ("_round_" keys outlive the turn)
_HOLDS = ("grappled", "restrained", "pinned", "bound")
ANCHOR = "condition:typed.chains_anchor"
ARMOR = "tianxia.talent.chains.chain_armor"
INCARNATION = "tianxia.talent.chains.chain_sovereign_incarnation"
LASH = "TAL_CHAINS_CHAIN_LASH_BASE"
SOVEREIGN_BLOCK = "chains_sovereign"
PRISON = "tianxia.talent.chains.chain_prison"
SCRIPT = "tianxia.talent.chains.chain_script_seal"
SPATIAL = "condition:typed.chains_spatial_lock"


@effect("chains_spatial_lock")
def spatial_lock(ctx: Any, row: dict[str, Any]) -> None:
    """A prison or seal's Charisma-save gate; primitives survive cold reload.

    Script seals test only the first attempt each round. Prisons test every
    teleport. Other spiritual transitions remain explicit manual riders.
    """
    from .ability_source import mechanic_of
    from .condition_ownership import remove_instance
    from ..typed_executor import effect_expiry

    ability = mechanic_of(ctx.action)
    if ability not in (PRISON, SCRIPT) or ctx.target is None or not ctx.target.active:
        return
    for iid, held in list(ctx.target.conditions.items()):
        if held.condition_id == SPATIAL and held.source_actor_id == ctx.actor.entity_id \
                and held.data.get("ability") == ability:
            remove_instance(ctx.engine, ctx.target, iid, ctx.source)
    ctx.engine._apply_condition(ctx.target, SPATIAL, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, row, ctx.target, condition=True), data={
            "ability": ability,
            "dc": int(ctx.numbers.get("save_dc", 10)),
            "once_per_round": int(ability == SCRIPT), "attempt_round": -1,
            "label": f"{ctx.action.display_name}: teleporting requires a Charisma save"
                     + (" on the first attempt each round" if ability == SCRIPT else ""),
        })


@hook("teleport_gate")
def spatial_teleport(ctx: Any, start: Any, destination: Any) -> bool | None:
    """Resolve all eligible locks before vetoing; each seal consumes the attempt.

    A failed prison or another caster's seal must not defer a seal's printed
    first-attempt trigger to a later teleport in the same round.
    """
    from .condition_ownership import remove_instance

    blocked = False
    for held in list(ctx.actor.conditions.values()):
        if held.condition_id != SPATIAL:
            continue
        data = dict(held.data)
        if data.get("once_per_round") and data.get("attempt_round") == ctx.engine.state.round_number:
            continue
        if data.get("once_per_round"):
            data["attempt_round"] = int(ctx.engine.state.round_number)
            remove_instance(ctx.engine, ctx.actor, held.instance_id, held.source_definition_id)
            ctx.engine._apply_condition(ctx.actor, SPATIAL, held.source_definition_id,
                held.source_actor_id, expires_on=held.expires_on, data=data)
        dc = int(data["dc"])
        roll = ctx.engine._roll_save(ctx.actor, "CHA", dc, held.source_definition_id)
        if roll is not None and int(roll.total) < dc:
            owner = ctx.engine.state.actors.get(held.source_actor_id)
            note(ctx.engine, held.source_definition_id, owner or ctx.actor,
                 f"{data['label']}. {ctx.actor.display_name} fails the save and stays in place; "
                 "the teleport's cost is spent.", targets=[ctx.actor])
            blocked = True
    return False if blocked else None


@effect("chains_anchor")
def anchor_protection(ctx: Any, eff: dict[str, Any]) -> None:
    """Owned armor/incarnation protection, using ordinary condition expiry."""
    from .ability_source import mechanic_of
    from .condition_ownership import remove_instance
    from .rider_choices import pick
    from ..typed_executor import effect_expiry

    ability = mechanic_of(ctx.action)
    if ability not in (ARMOR, INCARNATION):
        return
    actor = ctx.actor
    damage_type = ""
    if ability == ARMOR:
        chosen = pick(ctx.engine, actor, "chain_armor_damage", "Chain Armor",
            ["BLUDGEONING", "SLASHING"], subject=actor, optional=False,
            preferred=["BLUDGEONING"], labels={
                "BLUDGEONING": "Deal bludgeoning damage to a creature grappling you at the start of its turn",
                "SLASHING": "Deal slashing damage to a creature grappling you at the start of its turn",
            }, trigger="Chain Armor: costs 3 cultivation points and a Bonus Action; "
               "while you concentrate, up to 1 minute, a grappler takes your Proficiency Bonus in damage")
        damage_type = (chosen or ["BLUDGEONING"])[0]
    for iid, held in list(actor.conditions.items()):
        if held.condition_id == ANCHOR and held.source_definition_id == ctx.source:
            remove_instance(ctx.engine, actor, iid, ctx.source)
    reduction = 10 if ability == ARMOR else 20
    native = {"fly_speed_ft": 40, "flight_hover": 1, "sovereign_lash": 1} if ability == INCARNATION and eff.get("native_sovereign") else {}
    ctx.engine._apply_condition(actor, ANCHOR, ctx.source, actor.entity_id,
        expires_on=effect_expiry(ctx, eff, actor, condition=True), data={
            "reduction_ft": reduction, "damage_type": damage_type,
            "grapple_damage": int(ctx.numbers.get("pb") or actor.proficiency_bonus) if damage_type else 0,
            "label": f"{ctx.action.display_name}: forced movement reduced by {reduction} feet",
            **native,
        })


@hook("compile_block")
def sovereign_row(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    return [{**row, "block": block, "native_sovereign": 1, "keeps_compiling": True}] if block == SOVEREIGN_BLOCK else None


def _sovereign(actor: Any) -> bool:
    return any(c.condition_id == ANCHOR and c.data.get("sovereign_lash") == 1 for c in actor.conditions.values())


def _lash(typed: dict[str, Any]) -> bool:
    return (typed.get("option_of") or typed.get("source")) == LASH


@hook("compile_actions")
def sovereign_lashes(info: dict[str, Any]) -> list[Any] | None:
    import copy
    if not any(r.get("block") == SOVEREIGN_BLOCK and r.get("native_sovereign") == 1 for r in info.get("passives", [])):
        return None
    out = []
    for action in info.get("actions", []):
        if not _lash((action.parameters or {}).get("typed", {})):
            continue
        out.append(action.model_copy(update={"source_definition_id": action.source_definition_id + "#sovereign",
            "display_name": action.display_name + " (Sovereign)", "range_ft": 60,
            "parameters": {**copy.deepcopy(action.parameters), "chains_sovereign_lash": 1,
                "description": "While Chain-Sovereign Incarnation lasts: Chain Lash reaches 60 feet and its dice become 6d10; "
                               "one hit each turn offers a Strength save and your chosen binding."}}))
    return out or None


@hook("candidate_allowed")
def sovereign_lash_available(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not _lash((action.parameters or {}).get("typed", {})):
        return None
    from .ability_source import compiled_feature_rows
    if not any(r.get("block") == SOVEREIGN_BLOCK and r.get("native_sovereign") == 1
               for r in compiled_feature_rows(engine, actor.entity_id, INCARNATION)):
        return None
    return False if bool(action.parameters.get("chains_sovereign_lash")) != _sovereign(actor) else None


@hook("attack_damage")
def sovereign_lash_dice(ctx: Any, dice: Any) -> Any:
    if dice is None or not _lash(ctx.typed) or not _sovereign(ctx.actor):
        return None
    from ..gate2_runtime_models import DiceSpec
    return DiceSpec(count=6, sides=10, modifier=int(dice.modifier or 0))


@hook("after_hit_choice")
def sovereign_binding(ctx: Any, target: Any, kind: str) -> None:
    if not _lash(ctx.typed) or not _sovereign(ctx.actor) or target is None or not target.active:
        return
    stamp = next((e.sequence for e in reversed(ctx.engine.events) if e.event_type == "TURN_STARTED"), 0)
    key = "_round_chains_sovereign_binding"
    if ctx.actor.turn_flags.get(key) == stamp:
        return
    ctx.actor.turn_flags[key] = stamp
    from ..typed_executor import run_effects
    run_effects(ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={}),
        [{"type": "save", "ability": "str", "on_fail": [{"type": "chains_sovereign_binding"}],
          "on_success": [{"type": "forced_movement", "direction": "toward", "distance_ft": 5}]}])


@effect("chains_sovereign_binding")
def choose_sovereign_binding(ctx: Any, row: dict[str, Any]) -> None:
    if ctx.target is None or not _sovereign(ctx.actor):
        return
    from .rider_choices import pick
    from ..typed_executor import run_effects
    end = {"expires_on": "START_OF_TARGET_NEXT_TURN"}
    outcomes = {
        "pull": {"type": "forced_movement", "direction": "toward", "distance_ft": 20},
        "prone": {"type": "condition", "condition": "prone", "duration": "until_removed"},
        "bound": {"type": "condition", "condition": "bound", **end},
        "zero": {"type": "speed", "becomes": 0, **end},
        "reaction": {"type": "reaction_denied", **end},
    }
    chosen = pick(ctx.engine, ctx.actor, "chains_sovereign_binding", "Sovereign Binding", list(outcomes),
        subject=ctx.target, optional=False, trigger=f"{ctx.action.display_name} hits and {ctx.target.display_name} fails its Strength save",
        labels={"pull": "Pull it up to 20 feet toward you", "prone": "Knock it Prone", "bound": "Bind it until its next turn starts",
                "zero": "Its Speed is 0 until its next turn starts", "reaction": "It cannot take Reactions until its next turn starts"},
        prompt_context={"cost": "No additional Action, Reaction or cultivation point cost"})
    if chosen:
        run_effects(ctx, [{**outcomes[chosen[0]], "applies_to": "target"}])


@effect("chains_counter_success")
def counter_success(ctx: Any, row: dict[str, Any]) -> None:
    """Chain Counter's printed successful save, offered as the choice the text prints.

    "Successful Save: Pull the target 5 feet or reduce its remaining movement by 5 feet"
    (rules_text.json, tianxia.talent.chains.chain_counter). The table asks which of the two
    printed outcomes the owner wants; a creature that does not save is unaffected. The rows
    that reference this effect belong to Chain Counter alone, so a character without that
    talent never reaches it. Pulling is the first printed outcome, so an automatic chooser
    (an AI owner, or a saved fight that answers by itself) keeps the old pull-5-feet result.

    The printed trigger covers four ways a creature can set it off, two of them a melee attack
    and two of them movement ("enters your reach ... moves into a space adjacent to one of your
    Chain Objects"), so the prompt names the act that actually happened rather than always
    describing an attack. The movement outcome is priced against the movement the creature can
    actually spend, whichever way it would move (combat/flight.py ``budget``): a flyer slower
    than it walks can lose walking feet even once its flight is exhausted, and a flyer holds the
    feet beyond its walking Speed in a separate allowance. When it has nothing it can move there
    is nothing to take, and the option is not offered.
    """
    target = ctx.target
    if target is None or not target.active:
        return
    from ..flight import budget, restrict
    from .rider_choices import pick, trigger
    movement = budget(ctx.engine, target)
    kind, action = trigger(ctx.engine)
    if kind == "MOVE":
        how = f"goes off as {target.display_name} moves into your reach; "
    elif action:
        how = f"interrupts the incoming {action}; "
    else:
        how = f"reacts to what {target.display_name} is doing; "
    exhausted = ("has already spent its movement this turn" if movement.spent
                 else "cannot move right now")
    why = how + (f"{target.display_name} makes its Strength save" if movement.available_ft > 0
                 else f"{target.display_name} makes its Strength save, but it {exhausted}")
    outcomes = {"pull": {"type": "forced_movement", "direction": "toward", "distance_ft": 5}}
    labels = {"pull": "Pull it 5 feet toward you"}
    if movement.available_ft > 0:
        outcomes["withhold"] = {"type": "remaining_movement", "flat": -5}
        labels["withhold"] = "Take 5 feet off the movement it has left this turn"
    chosen = pick(ctx.engine, ctx.actor, "chains_counter_success", "Chain Counter", list(outcomes),
        subject=target, optional=False, trigger=why, labels=labels,
        prompt_context={"cost": "No additional Action, Reaction or cultivation point cost"})
    if not chosen:
        return
    if chosen[0] == "withhold":
        taken = restrict(ctx.engine, target, 5)
        ctx.engine._append_event("MOVEMENT_GRANTED", ctx.source, actor_id=target.entity_id,
                                 payload={"distance_ft": -taken})
        note(ctx.engine, ctx.source, ctx.actor,
             f"Chain Counter: {target.display_name} has {budget(ctx.engine, target).available_ft} "
             f"feet of movement left this turn.")
        return
    from ..typed_executor import run_effects
    run_effects(ctx, [{**outcomes[chosen[0]], "applies_to": "target"}])


@hook("forced_movement_reduction")
def anchored_movement(ctx: Any, subject: Any) -> int | None:
    if subject is None:
        return None
    reductions = [int(c.data.get("reduction_ft") or 0) for c in subject.conditions.values() if c.condition_id == ANCHOR]
    return sum(reductions) if reductions else None


@hook("turn_start")
def armor_grappler_damage(engine: Any, grappler: Any) -> None:
    """Once for each armored wearer this creature is actually grappling."""
    for wearer in engine.state.actors.values():
        if not wearer.active or wearer.entity_id == grappler.entity_id:
            continue
        if not any(c.condition_id.rsplit(".", 1)[-1] == "grappled" and c.source_actor_id == grappler.entity_id
                   for c in wearer.conditions.values()):
            continue
        for armor in list(wearer.conditions.values()):
            if armor.condition_id != ANCHOR or not armor.data.get("damage_type"):
                continue
            amount = int(armor.data.get("grapple_damage") or 0)
            if amount and grappler.active:
                note(engine, ARMOR, wearer,
                     f"Chain Armor: {grappler.display_name} is grappling {wearer.display_name} and takes "
                     f"{amount} {armor.data['damage_type'].lower()} damage.", targets=[grappler])
                engine._commit_damage(grappler, amount, armor.data["damage_type"], ARMOR,
                                      wearer.entity_id, None, reaction_depth=1)


def bound(actor: Any) -> list[Any]:
    return [c for c in actor.conditions.values() if c.condition_id == BOUND]


# ------------------------------------------------------------------------------------------------------------- Bound
@hook("speed")
def bound_speed(engine: Any, actor: Any) -> int | None:
    return -10 if bound(actor) else None


@hook("escape_mode")
def bound_escapes(engine: Any, actor: Any, grips: Any) -> str | None:
    """Disadvantage on its own checks to escape a grip, restraint, pin or Bound."""
    if not bound(actor):
        return None
    mine = [g for g in grips or () if getattr(g, "target_id", actor.entity_id) == actor.entity_id]
    return "DISADVANTAGE" if any(str(g.condition_id).rsplit(".", 1)[-1] in _HOLDS for g in mine) else None


# ------------------------------------------------------------------------------------------------------------ Tethers
def _tethered(engine: Any) -> list[tuple[Any, Any]]:
    return [(actor, c) for actor in engine.state.actors.values() for c in bound(actor) if "tether_ft" in (c.data or {})]


@hook("event", nested=True)
def tether_breaks(engine: Any, event_type: str, kwargs: Any) -> None:
    if event_type != "MOVEMENT_COMMITTED":
        return
    moved = kwargs.get("actor_id")
    for holder, held in _tethered(engine):
        if moved not in (holder.entity_id, held.source_actor_id) or held.instance_id not in holder.conditions:
            continue
        anchor = engine.state.actors.get(held.source_actor_id or "")
        length = int((held.data or {}).get("tether_ft") or 0)
        if anchor is None or engine._distance_actor_to_actor(anchor, holder) <= length:
            continue
        from .hold_escapes import escaped, movement_how

        holder.conditions.pop(held.instance_id)
        engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=held.source_actor_id,
                             target_ids=(holder.entity_id,),
                             payload={"condition_id": BOUND, "instance_id": held.instance_id, "reason": "TETHER_BROKEN"})
        note(engine, held.source_definition_id, anchor, f"The tether between {anchor.display_name} and {holder.display_name} "
             f"breaks: they are more than {length} feet apart, so {holder.display_name} is no longer Bound.", targets=[holder])
        if moved == holder.entity_id:
            escaped(engine, holder, [held], movement_how(kwargs.get("payload")), source=held.source_definition_id, way="movement")


# ---------------------------------------------------------------------------------------------------- Prisoner's Bell
@hook("compile_block")
def _compile(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BELL:
        return None
    return [{**row, "keeps_compiling": True}]


def _bell_owners(engine: Any) -> list[Any]:
    from ..typed_reactions import _rows

    return [actor for actor in engine.state.actors.values() if actor.active and _rows(engine, actor.entity_id, BELL)]


def _chains(engine: Any, source: str) -> bool:
    action = engine.action_catalog.get(str(source or "").split("#")[0])
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    return typed.get("sphere") == SPHERE


def _compass(dx: int, dy: int) -> str:
    """Map squares: x grows to the east, y to the south."""
    ns = "north" if dy < 0 else "south" if dy > 0 else ""
    ew = "east" if dx > 0 else "west" if dx < 0 else ""
    if ns and ew and min(abs(dx), abs(dy)) * 2 >= max(abs(dx), abs(dy)):
        return f"{ns}-{ew}"
    return (ns if abs(dy) >= abs(dx) else ew) or "here"


def _hook_row(engine: Any, owner: Any) -> dict[str, Any] | None:
    """The owner's compiled Restraining Hook (a generic reaction row, typed_reactions)."""
    from ..typed_reactions import _rows

    return next((row for row in _rows(engine, owner.entity_id, "generic") if row.get("feature_id") == HOOK), None)


@hook("hold_escaped")
def prisoners_bell(engine: Any, record: dict[str, Any]) -> None:
    holder = engine.state.actors.get(record.get("holder") or "")
    if holder is None:
        return
    for owner in _bell_owners(engine):
        mine = [h for h in record.get("holds") or [] if h.get("owner") == owner.entity_id and _chains(engine, h.get("source"))]
        if not mine:
            continue
        _ring(engine, owner, holder, record, mine[0])


def _ring(engine: Any, owner: Any, holder: Any, record: dict[str, Any], hold: dict[str, str]) -> None:
    from .hold_escapes import WORDS

    action = engine.action_catalog.get(str(hold.get("source") or "").split("#")[0])
    ability = getattr(action, "display_name", None) or "a Chains technique"
    distance = engine._distance_actor_to_actor(owner, holder)
    where = _compass(holder.position.x - owner.position.x, holder.position.y - owner.position.y)
    breaker = engine.state.actors.get(record.get("by") or "") if record.get("way") == "object" else None
    text = f"Prisoner's Bell: {holder.display_name} escaped {owner.display_name}'s {ability} {WORDS.get(record.get('how'), '')}"
    if breaker is not None and breaker is not holder:
        text += f" ({breaker.display_name} destroyed the Chain Object)"
    text += f"; it is {distance} feet to the {where} of {owner.display_name}." if where != "here" else "."
    if distance <= 300:
        text += f" Only {owner.display_name} hears the chain-bell."
    note(engine, BELL_SOURCE, owner, text, targets=[holder])
    _free_hook(engine, owner, [c for c in (holder, breaker) if c is not None])


def _free_hook(engine: Any, owner: Any, creatures: list[Any]) -> None:
    """Once a fight: Restraining Hook against that creature, within its 30 feet, Reaction spent, no CP."""
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id, incapacitated

    if owner.turn_flags.get(USED) or not owner.reaction_available or incapacitated(owner) \
            or any(rule.get("no_reactions") for rule in te.condition_rules(owner)):
        return
    row = _hook_row(engine, owner)
    if row is None:
        return
    reach = int(row.get("range_ft") or 30)
    unique = list({c.entity_id: c for c in creatures}.values())
    targets = [c for c in unique if c.active and c.team_id != owner.team_id and engine._distance_actor_to_actor(owner, c) <= reach]
    if not targets:
        return
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "prisoners_bell", owner.entity_id),
                 owner, "choice:needle.prisoners_bell", [c.entity_id for c in targets], allow_decline=True,
                 labels={c.entity_id: f"Restraining Hook on {c.display_name} (your Reaction, no CP)" for c in targets},
                 prompt=f"Prisoner's Bell: {targets[0].display_name} got out of your chains. Use Restraining Hook against it now "
                        f"without spending CP (once per short rest; uses your Reaction): it makes a Strength save or its "
                        f"remaining movement becomes 0 (10 feet less on a success).", name="Prisoner's Bell",
                 feature_id=BELL_SOURCE)
    target = engine.state.actors.get(picked[0]) if picked else None
    if target is None:
        return
    with activation(engine, owner, BELL_SOURCE):
        owner.turn_flags[USED] = 1
        owner.reaction_available = False
        note(engine, BELL_SOURCE, owner, f"Prisoner's Bell: {owner.display_name} uses Restraining Hook on {target.display_name} "
             f"without spending CP (it uses {owner.display_name}'s Reaction).", targets=[target])
        from ..typed_reactions import triggered_context

        ctx = triggered_context(engine, owner, target, row, getattr(engine, "_active_intent", None))
        te.run_effects(ctx, list(row.get("effects") or []))
