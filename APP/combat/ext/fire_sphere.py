"""Fire sphere: the printed fire effects the table now runs (AUTO77, 2026-10-05).

Sphere Compendium, Fire (owner's text: ``APP/authority/typed_mechanics/rules_text.json``). Every printed line quoted here is
one the table used to leave to the GM as a reminder.

  Burning Weapon, FIRE_TAL_BURNING_WEAPON
    "Imbue one weapon, unarmed strike, or natural weapon with flame. Once per turn when the bearer hits with that weapon,
     add Fire damage: 1-10: 1d6; 11-16: 2d6; 17-20: 3d6. The hit applies Burn."
    What the table did before: the compiled action charged 1 CP and put nothing on the bearer and nothing on the target, so
    the whole talent was four reminder lines. Its one typed row is a ``deferred`` Burn (the shape a passive modifier uses)
    and the ``modifier`` block the record carried never reached the compiled bundle at all.
  White-Hot Focus, tianxia.talent.fire.white_hot_focus
    "The next Fire talent you use this turn gains one: Advantage on one attack roll; one target has Disadvantage on its
     saving throw; add your Path key ability modifier to one Fire damage roll; ignore Resistance to Fire damage for one
     target. After the talent resolves, take Fire damage equal to your Proficiency Bonus. White-Hot Focus cannot ignore
     Immunity." Four reviewed options choose one printed benefit and defer its self-damage until the next talent resolves.
     A2FIRE: all four benefits now use the current engine hooks, including the scoped Resistance bypass.
  Furnace Heart, tianxia.talent.fire.furnace_heart and Fire-Sovereign Incarnation,
  tianxia.talent.fire.fire_sovereign_incarnation
    "Overheat self-damage is reduced by half" and "Overheat self-damage is reduced to 0".

Documented seams used, all inert without the talent's own compiled row (``combat/rules/feature_blocks.d/auto77_fire.json``):
``compile_actions`` for Burning Weapon's own action and for White-Hot Focus's four printed benefits, ``after_hit`` for the
imbued strike's added Fire damage and Burn, ``before_target_reactions`` for binding White-Hot Focus to one Fire activation and
asking which creature it applies to, ``save`` for White-Hot Focus's Disadvantage, ``technique_used`` for spending it,
``attack_damage_bonus`` and ``damage_roll_bonus`` for its damage clause, and
``final_damage`` for the halved (or removed) Overheat self-damage. Everything stored in fight state is an integer or a
string. No hook is added to the framework.

AUTO77f1 (2026-10-05, the pre-merge review's findings):
  * Burning Weapon lasts as the printed "Duration: Concentration, up to 1 minute" says. Its state is filed on the bearer
    under the casting action's own source and ``CONCENTRATION_END``, so the shared concentration cleanup
    (combat/concentration.end_conditions) takes it when that copy ends, and the shared one-minute deadline
    (combat/ext/concentration_duration.py) ends the copy at a minute. Before this it carried ``END_OF_CURRENT_TURN``, so
    every later turn lost the paid-for damage and Burn.
  * The printed bearer is reachable: the talent compiles as ``ALLY_OR_SELF``, so the creature the action was aimed at is the
    bearer, and its own held weapons are what is offered (display names, not item ids).
  * The weapon choice rides the ``choice:fire.imbue_weapon`` option spec this module now owns, so the table really pauses and
    a real decline imbuing nothing is honoured.
  * White-Hot Focus binds to ONE Fire activation (any Fire source, read from the compiled action's own ``typed.sphere``) and
    asks which affected creature it applies to, instead of being consumed by whatever save or damage roll happened to come
    first.
  * White-Hot Focus belongs to one *attempted* activation, not to an action definition: it is named by the activation's own
    identity (its intent, and how many events the fight had recorded when it was bound) and spent by the attempt it was bound
    to, whether that attempt resolved or was countered.

AUTO77r1f1 (2026-10-05, the AUTO77r1 review's two findings):
  * A Burning Weapon that never began its printed Concentration imbues nothing at all -- no weapon question, no state. The
    evidence is the fight's own ``CONCENTRATION_STARTED`` record stamped with this activation's own intent
    (``_established_concentration``); a countered or cancelled cast leaves none. The state used to fall back on
    ``UNTIL_REMOVED`` in that case, which turned a failed cast into a buff that never ended, so the printed
    ``CONCENTRATION_END`` is now the only deadline it is ever filed with.
  * White-Hot Focus is bound to one attempted activation, not to the action's id, and the attempt that was bound to it spends
    it even when the table counters that talent. Where an extra action or reaction allows the same Fire action again that
    turn, the second activation gets no benefit, is asked nothing, and cannot land on the creature the first one named.
"""

from __future__ import annotations

import copy
from typing import Any

from . import hook, effect
from . import states
from .needle import answered, ask, checkpoint_id
from .weapon_hits import available_weapons

BLOCK = "auto77_fire"
BURNING_WEAPON = "FIRE_TAL_BURNING_WEAPON"
WHITE_HOT_FOCUS = "tianxia.talent.fire.white_hot_focus"
FURNACE_HEART = "tianxia.talent.fire.furnace_heart"
FIRE_SOVEREIGN = "tianxia.talent.fire.fire_sovereign_incarnation"

#: The Fire sphere every Fire talent and base ability compiles under (``typed.sphere``).
SPHERE = "tianxia.sphere.fire"

#: This module's own choice namespace, owned by :func:`imbue_weapon_options` below.
CHOICE = "choice:fire."
IMBUE_CHOICE = CHOICE + "imbue_weapon"
FOCUS_CHOICE = CHOICE + "white_hot_focus_target"

#: The states this module owns, all read and written through combat/ext/states.py's shared ``condition:typed.state.`` prefix.
IMBUED = "burning_weapon"
FOCUS_SAVE_DISADVANTAGE = "white_hot_focus_save_disadvantage"
FOCUS_DAMAGE = "white_hot_focus_damage"
FOCUS_ATTACK = "white_hot_focus_attack"
FOCUS_RESISTANCE = "white_hot_focus_resistance"
FURNACE = "furnace_heart"
SOVEREIGN = "fire_sovereign_incarnation"

#: White-Hot Focus's four printed benefits, one button each: the state's name, what the button reads, and what it asks.
FOCUS_MODES = (
    (FOCUS_ATTACK, "Advantage on one attack roll", "which creature that attack targets"),
    (FOCUS_RESISTANCE, "ignore one target\'s Resistance to Fire damage", "which creature\'s Fire Resistance is ignored"),
    (FOCUS_SAVE_DISADVANTAGE, "one target's saving throw against your next Fire talent has Disadvantage",
     "which creature makes that saving throw"),
    (FOCUS_DAMAGE, "your Path key ability modifier is added to one Fire damage roll",
     "which creature that Fire damage roll hits"),
)

#: Burning Weapon's printed Fire damage by Cultivation Level.
IMBUED_DICE = ((1, 10, 1), (11, 16, 2), (17, 20, 3))

#: The Fire abilities whose printed damage White-Hot Focus's clauses may touch when their action carries no ``typed.sphere``
#: (the compiled Fire sphere id above is the normal reading; this is the id-level fallback for rows sealed before it).
FIRE_SOURCES = frozenset({"FIRE_BASE_IGNITE", "FIRE_BASE_CONFLAGRATION", "FIRE_TAL_CROWN_OF_INFERNO"})


def _rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    """The Fire block rows this actor's own compiled character carries."""
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, ())
            if row.get("block") == BLOCK]


def _owns(engine: Any, actor: Any, kind: str) -> bool:
    return _row(engine, actor, kind) is not None


def _row(engine: Any, actor: Any, kind: str) -> dict[str, Any] | None:
    """One of this actor's own Fire block rows, by kind."""
    return next((row for row in _rows(engine, actor) if row.get("kind") == kind), None)


def _dice_by_cl(cl: int) -> int:
    for low, high, count in IMBUED_DICE:
        if low <= cl <= high:
            return count
    return IMBUED_DICE[-1][2]


@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The Fire talents' own compiled markers (combat/rules/feature_blocks.d/auto77_fire.json)."""
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": str(spec.get("kind") or ""), "cl": int(numbers.get("cl") or 1),
             **({"keeps_compiling": True} if spec.get("keeps_compiling") else {})}]


def _typed_source(engine: Any, source_id: str | None) -> str:
    """The mechanic id a compiled action belongs to, read from the engine's own catalog. An id that is already a mechanic id
    (a damage packet's own ``typed.source``) is returned unchanged."""
    text = str(source_id or "")
    row = (getattr(engine, "action_catalog", {}) or {}).get(text)
    if row is None:
        return text.split("#", 1)[0]
    typed = ((getattr(row, "parameters", None) or {}).get("typed") or {})
    return str(typed.get("source") or "").split("#", 1)[0]


def _is_fire(engine: Any, source_id: str | None, typed: dict[str, Any] | None = None) -> bool:
    """"The next Fire talent you use this turn": anything this character compiles under the Fire sphere.

    The compiled action's own ``typed.sphere`` is the read: it names every Fire base ability and every Fire talent, whatever
    their id's spelling (AUTO77f1: the source test alone missed the uppercase ``FIRE_TAL_*`` ids). The source-id test stays
    as the reading for rows sealed before ``typed.sphere`` existed."""
    if str((typed or {}).get("sphere") or "") == SPHERE:
        return True
    source = _typed_source(engine, source_id)
    return source.startswith("tianxia.talent.fire.") or source in FIRE_SOURCES


def _drop(engine: Any, actor: Any, name: str, source: str) -> None:
    condition = states.active(engine, actor, name)
    if condition is not None:
        engine._remove_condition(actor, condition.condition_id, source)


def _stamp(engine: Any) -> str:
    """The engine's own turn identity for a "once per turn" limit: the round and whose turn it is. Compared against a string
    stored in the condition's own data (integers and strings only), so it survives a save and reload."""
    state = engine.state
    return f"{int(getattr(state, 'round_number', 0) or 0)}:{str(getattr(state, 'current_actor_id', '') or '')}"


# --------------------------------------------------------------------------- Burning Weapon
def _bearer_weapons(engine: Any, bearer: Any) -> dict[str, str]:
    """The weapons this bearer actually holds, as ``implement id -> the name the table shows it by``. Read through the shared
    public possession query (combat/weapon_delivery.available_weapons, re-exported by combat/ext/weapon_hits.py), so the
    bearer's own hands, not the caster's, decide what can be imbued and the menu shows weapon names, never item ids
    (AUTO77f1)."""
    found: dict[str, str] = {}
    for action in available_weapons(engine, bearer).values():
        typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
        implement = str((typed.get("weapon") or {}).get("implement_id") or "")
        if implement and implement not in found:
            found[implement] = str(getattr(action, "display_name", "") or implement).removesuffix(" attack") or implement
    return found


def _active_intent(engine: Any, actor: Any) -> Any:
    """The intent being resolved right now: the engine's own, else the last one this actor had accepted."""
    intent = getattr(engine, "_active_intent", None)
    if intent is not None and str(getattr(intent, "actor_id", "") or "") == actor.entity_id:
        return intent
    event = next((row for row in reversed(getattr(engine, "events", ()) or ())
                  if row.event_type == "INTENT_ACCEPTED" and row.actor_id == actor.entity_id), None)
    return (getattr(event, "payload", {}) or {}).get("intent") if event is not None else None


def _bearer(engine: Any, actor: Any, intent: Any) -> Any:
    """"Imbue one weapon, unarmed strike, or natural weapon ... when the bearer hits with that weapon": the printed bearer is the
    creature the action was aimed at. Burning Weapon compiles as ALLY_OR_SELF, so an ally the user touches is reachable and
    its own strikes are what burn; the user themself is the default."""
    for who in (getattr(intent, "target_ids", ()) or ()):
        bearer = engine.state.actors.get(str(who))
        if bearer is not None and bearer.active:
            return bearer
    return actor


#: The Fire talents whose printed "is this running" marker this module puts on the user itself.
_MARKERS = {FURNACE_HEART: (FURNACE, "Furnace Heart: your Overheat hurts you half as much"),
            FIRE_SOVEREIGN: (SOVEREIGN, "Fire-Sovereign Incarnation: your Overheat does not hurt you at all")}


@hook("action_completed")
def own_state_marker(engine: Any, actor: Any, economy: Any, source_definition_id: str) -> None:
    """Furnace Heart and Fire-Sovereign Incarnation each need one honest "this is running" marker so their printed Overheat
    clause can be read while it lasts. It is combat/ext/states.py's shared ``state`` effect, run with that module's own
    context helper so the printed 1-minute length is the engine's own counted clock."""
    from .. import typed_executor as te
    from . import states as state_rows

    marker = _MARKERS.get(_typed_source(engine, source_definition_id))
    if marker is None:
        return
    name, label = marker
    numbers = {"pb": int(actor.proficiency_bonus or 0)}
    te.run_effects(state_rows.context(engine, actor, source_definition_id, [], numbers),
                   [{"type": "state", "name": name, "duration": "one_minute", "label": label}])


@hook("choice_options")
def fire_options(engine: Any, intent: Any, checkpoint: Any, reactor_id: str, choice_id: str, context: Any) -> dict[str, Any] | None:
    """This module's own choice namespace (``choice:fire.*``): Burning Weapon's weapon and White-Hot Focus's affected
    creature. Without it combat/choice_checkpoints.py supplies no extension-choice specification and the engine falls back to
    legacy reaction handling, which never offers these options (AUTO77f1)."""
    if not str(choice_id).startswith(CHOICE) or not (context or {}).get("needle_options"):
        return None
    spec = {"option_ids": list(context["needle_options"]), "minimum_selections": int(context.get("minimum", 1)),
            "maximum_selections": int(context.get("maximum", 1)), "allow_decline": bool(context.get("allow_decline", False)),
            "automatic_use": bool(context.get("automatic", True))}
    if context.get("preferred"):
        spec["preferred_option_ids"] = list(context["preferred"])
    return spec


def _established_concentration(engine: Any, actor: Any, intent: Any, source_id: str) -> bool:
    """Whether THIS activation really began the printed "Duration: Concentration, up to 1 minute".

    Evidence, not assumption: the fight's own event log records one ``CONCENTRATION_STARTED`` per copy, stamped with the
    intent that started it (Gate2Engine._start_concentration -> _append_event). An activation the table read as countered
    or cancelled returns out of combat/typed_executor.py before the printed Concentration is ever started, so it leaves no
    such record and its printed flame never existed. A Concentration copy opened by an *earlier* use of the same talent
    carries that earlier intent and is not this activation's evidence either."""
    from .. import concentration

    if not concentration.concentrating_on(actor, source_id):
        return False
    intent_id = str(getattr(intent, "intent_id", "") or "")
    if not intent_id:
        return False
    return any(event.event_type == "CONCENTRATION_STARTED" and event.actor_id == actor.entity_id
               and event.source_definition_id == source_id and event.trigger_or_intent_id == intent_id
               for event in getattr(engine, "events", ()) or ())


@hook("action_completed")
def burning_weapon_action(engine: Any, actor: Any, economy: Any, source_definition_id: str) -> None:
    """Burning Weapon's own action: it puts the printed flame on one of the bearer's own strikes instead of only charging its
    Cost. The action keeps its printed Bonus Action, Touch range, 1 CP and "Duration: Concentration, up to 1 minute" -- the
    state is filed under the casting action's own source with ``CONCENTRATION_END``, so the shared concentration cleanup ends
    it with its copy and the shared one-minute deadline ends that copy at a minute.

    A cast that never began that Concentration (countered, or cancelled before it resolved) imbues nothing at all
    (AUTO77r1f1): the table is not asked which strike burns, and no state is left behind. Substituting an unlimited
    "until removed" duration for the missing Concentration is what made a failed cast a fight-long buff."""

    if _typed_source(engine, source_definition_id) != BURNING_WEAPON or not _owns(engine, actor, "burning_weapon"):
        return
    intent = _active_intent(engine, actor)
    if not _established_concentration(engine, actor, intent, source_definition_id):
        return
    bearer = _bearer(engine, actor, intent)
    weapons = _bearer_weapons(engine, bearer)
    options = [*weapons, "unarmed"]
    whose = "your" if bearer.entity_id == actor.entity_id else f"{bearer.display_name}'s"
    labels = {**{implement: f"Flame {whose} {name}" for implement, name in weapons.items()},
              "unarmed": f"Flame {whose} unarmed strike and natural weapons"}
    checkpoint = "FIRE_IMBUE:" + checkpoint_id(engine, "IMBUE", bearer.entity_id)
    picked = ask(engine, intent, checkpoint, actor, IMBUE_CHOICE, options, labels=labels,
                 prompt=f"Burning Weapon: {actor.display_name} touches {bearer.display_name}. Which of {whose} strikes burns "
                        f"with flame? The flame lasts while {actor.display_name} concentrates, up to 1 minute, and adds Fire "
                        f"damage and sets the target Burning once per turn.",
                 allow_decline=True, name="Burning Weapon", target_id=bearer.entity_id)
    if not picked and answered(engine, checkpoint, actor, IMBUE_CHOICE):
        return  # a real "no": nothing is imbued (AUTO77f1; before this a decline quietly imbued the unarmed strike)
    chosen = str(picked[0]) if picked else "unarmed"
    row = _row(engine, actor, "burning_weapon") or {}
    cl = int(row.get("cl") or 1)
    numbers = {"pb": int(actor.proficiency_bonus or 0), "cl": cl, "dice": _dice_by_cl(cl), "weapon": chosen}
    engine._remove_condition(bearer, states.PREFIX + states.slug(IMBUED), source_definition_id)
    engine._apply_condition(bearer, states.PREFIX + states.slug(IMBUED), source_definition_id, actor.entity_id,
                            expires_on="CONCENTRATION_END",   # the only deadline the printed rule has; see _established_concentration
                            data={"label": f"Burning Weapon: {bearer.display_name}'s {labels[chosen]} (blows with flame)",
                                  "name": IMBUED, "numbers": numbers, "spent": ""})


def _imbued(ctx: Any, kind: str) -> Any:
    """The bearer's own Burning Weapon state, when this very strike is the one the printed text names."""
    if kind not in ("weapon", "unarmed"):
        return None
    condition = states.active(ctx.engine, ctx.actor, IMBUED)
    if condition is None:
        return None
    numbers = (condition.data or {}).get("numbers") or {}
    used = str((ctx.typed.get("weapon") or {}).get("implement_id") or "") if kind == "weapon" else "unarmed"
    if kind == "weapon" and not used:
        return None
    return condition if str(numbers.get("weapon") or "unarmed") == used else None


@hook("after_hit")
def burning_weapon_flames(ctx: Any, target: Any, kind: str) -> None:
    """"Once per turn when the bearer hits with that weapon, add Fire damage ... The hit applies Burn." The added roll and the
    Burn ride the hit they are printed on, and that turn's one use is spent when it happens."""
    from .effect_durations import apply_condition_preserving_clock, skipped_expiry_slots
    from .. import typed_executor as te

    condition = _imbued(ctx, kind)
    engine, actor = ctx.engine, ctx.actor
    if condition is None or not target.active:
        return
    numbers = dict((condition.data or {}).get("numbers") or {})
    stamp = _stamp(engine)
    if str((condition.data or {}).get("spent") or "") == stamp:
        return  # "Once per turn"
    count = int(numbers.get("dice") or 1)
    # Re-filed under the state its own attribution (the casting action, which holds the Concentration), never under the
    # striking weapon's action: the shared concentration cleanup matches on source_definition_id.
    skipped = skipped_expiry_slots(actor, condition)
    engine._remove_condition(actor, condition.condition_id, condition.source_definition_id)
    apply_condition_preserving_clock(engine, actor, condition, condition.condition_id, condition.source_definition_id, condition.source_actor_id,
                            expires_on=condition.expires_on or "UNTIL_REMOVED",
                            data={**(condition.data or {}), "numbers": numbers, "spent": stamp}, skipped_slots=skipped)
    te.run_effects(ctx, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": count, "sides": 6},
                          "damage_types": ["fire"], "evidence": "Burning Weapon: add Fire damage"},
                         {"type": "condition", "applies_to": "target", "condition": "burning",
                          "evidence": "Burning Weapon: the hit applies Burn"}])
    ctx.rider(f"Burning Weapon: +{count}d6 Fire damage and the target is Burning.")


# --------------------------------------------------------------------------- White-Hot Focus
@hook("compile_actions")
def focus_variants(info: dict[str, Any]) -> list[Any] | None:
    """"The next Fire talent you use this turn gains one:" -- one button per printed benefit the table can run, each with the
    printed "After the talent resolves, take Fire damage equal to your Proficiency Bonus" said in the button itself."""
    out = []
    for action in info.get("actions") or []:
        typed = (action.parameters or {}).get("typed") or {}
        if str(typed.get("source") or "").split("#", 1)[0] != WHITE_HOT_FOCUS or action.owner_id != info["actor_id"]:
            continue
        if any(row.get("type") == "fire_focus_state" for row in typed.get("effects") or []):
            continue  # reviewed options already compile one button per benefit
        paid = next((amount for _resource, amount in (action.costs or ()) if amount), 0)
        pb = int((info.get("numbers") or {}).get("pb") or 0)
        backlash = (f"After that talent resolves, you take {pb} Fire damage."
                     if pb else "After that talent resolves, you take Fire damage equal to your Proficiency Bonus.")
        for name, reads, asks in FOCUS_MODES:
            out.append(action.model_copy(update={
                "source_definition_id": f"{action.source_definition_id}+{name}",
                "display_name": f"White-Hot Focus: your next Fire talent gains one: {reads}. {backlash} ({paid} CP)",
                "parameters": {**action.parameters, "typed": {**typed, "effects": [
                    {"type": "state", "name": name, "duration": "until_end_of_turn",
                     "label": f"White-Hot Focus: your next Fire talent this turn -- {reads}. {backlash}"},
                    *copy.deepcopy(typed.get("effects") or [])]}}}))
    return out or None


#: Resolution-local marker for the ONE activation a bound White-Hot Focus belongs to, like ``_DAMAGE_SLOT`` below: never
#: persisted, and shared by every nested Context of one activation.
_ACTIVATION_SLOT = "white_hot_focus_activation"


def _activation(ctx: Any) -> str:
    """This one activation's identity: the intent being resolved, plus how many events the fight had already recorded
    when the binding was made.

    "The next Fire talent you use this turn" is about one attempted activation, not about an action definition
    (AUTO77r1f1). A Fire talent the table reads as countered was still used, so it spent the Focus; and where an extra
    action, bonus action or reaction allows the *same* action again this turn, that second activation is a different
    one -- it must neither inherit the first one's benefit nor the creature it was aimed at. The intent half is what the
    save and damage hooks read back, because it is stable for the whole activation; the event count is recorded at the
    moment of binding, so two activations that somehow share an intent are still told apart."""
    cache = getattr(ctx, "damage_cache", None)
    if cache is None:
        return ""
    token = cache.get(_ACTIVATION_SLOT)
    if not token:
        token = f"{str(getattr(ctx.intent, 'intent_id', '') or '')}#{int(ctx.engine.state.event_sequence)}"
        cache[_ACTIVATION_SLOT] = token
    return str(token)


def _activation_intent(token: Any) -> str:
    """The intent half of an activation identity: the part every Context of that one activation can recompute."""
    return str(token or "").partition("#")[0]


def _armed(engine: Any, actor: Any, name: str, ctx: Any) -> Any:
    """The White-Hot Focus state, when this very activation is the Fire talent it was bound to.

    "The next Fire talent you use this turn" is a binding to one attempted activation, not to an action definition
    (AUTO77r1f1): :func:`focus_binding` names that activation, so a later activation of the very same action this turn
    can neither inherit the benefit nor the creature the first one was aimed at."""
    condition = states.active(engine, actor, name)
    if condition is None or not _is_fire(engine, ctx.source, ctx.typed):
        return None
    mine = _activation_intent(_activation(ctx))
    return condition if mine and mine == _activation_intent((condition.data or {}).get("bound")) else None


def _chosen(condition: Any) -> str:
    """The creature the bound activation's owner named; "" when they named none (the benefit then lands on nothing rather
    than on whoever happened to be processed first)."""
    return str((condition.data or {}).get("chosen") or "")


def _chosen_for(condition: Any, subject: Any) -> bool:
    """Whether this creature is the one the bound activation's answer named."""
    chosen = _chosen(condition)
    return bool(chosen) and subject is not None and str(getattr(subject, "entity_id", "")) == chosen


@hook("before_target_reactions")
def focus_binding(ctx: Any) -> None:
    """Bind White-Hot Focus to the next Fire activation, and ask which affected creature it applies to.

    Runs on the documented ``before_target_reactions`` seam, so the roster offered is the action's own final one (shape-aware
    for an area, the chosen target otherwise) and the answer rides the ordinary transactional choice transport: a player or
    Ask-me user is asked on their own turn and on an AI turn, an AI fighter answers automatically (AUTO77f1).

    The binding names ONE attempted activation (:func:`_activation`), and this hook runs on every activation, before any
    save or effect of it: an activation that finds the state already bound to a different one has been used by the attempt
    it was bound to -- resolved or countered -- and that attempt spent it (AUTO77r1f1)."""
    engine, actor = ctx.engine, ctx.actor
    if not _owns(engine, actor, "focus") or not _is_fire(engine, ctx.source, ctx.typed):
        return
    token = _activation(ctx)
    if not token:
        return
    for name, reads, asks in FOCUS_MODES:
        condition = states.active(engine, actor, name)
        if condition is None:
            continue
        data = dict(condition.data or {})
        bound = str(data.get("bound") or "")
        if bound == token:
            continue        # this very activation already asked
        if bound:
            _drop(engine, actor, name, ctx.source)  # the attempt it was bound to is over: it is spent, whatever became of it
            continue
        _rewake(engine, actor, condition, {**data, "bound": token,
                                           "chosen": _focus_subject(ctx, name, reads, asks),
                                           **({"bound_source": ctx.source} if data.get("backlash") else {})})


def _focus_subject(ctx: Any, name: str, reads: str, asks: str) -> str:
    """The creature this Fire talent affects and the benefit lands on, chosen by its owner; "" when there is none to name.

    Only creatures the talent affects as a target are offered: a Fire area may reach its own user, and the printed clauses
    are about a target, so the caster is left out of the menu rather than offered and then refused."""
    from ..target_knowledge import is_attack, knowledge
    # An accepted attack can aim at a remembered creature. Area recipients
    # remain perception-only: occupying a hidden square does not disclose them.
    remembered_attack = name == FOCUS_ATTACK and is_attack(ctx.action)
    known = {subject.entity_id for subject in ctx.targets
             if (observed := knowledge(ctx.engine, ctx.actor, subject, ctx.action)) is not None
             and (observed.mode == "DIRECT" or remembered_attack and observed.mode == "LAST_OBSERVED")}
    roster = [subject for subject in list(getattr(ctx, "targets", ()) or ())
              if getattr(subject, "active", False) and subject.entity_id != ctx.actor.entity_id
              and subject.entity_id in known]
    ids = [str(subject.entity_id) for subject in roster]
    if not ids:
        return ""
    hostiles = [subject for subject in roster if subject.team_id != ctx.actor.team_id] or roster
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "WHITE_HOT_FOCUS", name, ctx.source), ctx.actor,
                 FOCUS_CHOICE, ids, labels={str(subject.entity_id): subject.display_name for subject in roster},
                 preferred=[str(hostiles[0].entity_id)],
                 prompt=f"White-Hot Focus: {ctx.actor.display_name} uses {ctx.action.display_name}. Choose {asks}: "
                        f"{reads}. After that talent resolves {ctx.actor.display_name} takes Fire damage equal to their "
                        f"Proficiency Bonus.",
                 name="White-Hot Focus", target_id=str(hostiles[0].entity_id))
    return str(picked[0]) if picked and str(picked[0]) in ids else ""


def _rewake(engine: Any, actor: Any, condition: Any, data: dict[str, Any]) -> None:
    """Put the state back with new data under the same id, source and expiry (never edited in place)."""
    from .effect_durations import apply_condition_preserving_clock, skipped_expiry_slots
    skipped = skipped_expiry_slots(actor, condition)
    engine._remove_condition(actor, condition.condition_id, condition.source_definition_id)
    apply_condition_preserving_clock(engine, actor, condition, condition.condition_id, condition.source_definition_id, condition.source_actor_id,
                            expires_on=condition.expires_on or "UNTIL_REMOVED", data=data, skipped_slots=skipped)


@hook("technique_final")
def focus_spent(ctx: Any) -> None:
    """"The next Fire talent you use this turn": the bound benefit is spent with that talent, whether or not it had a roll to
    touch (AUTO77f1: a talent with no matching save or damage roll used to leave it for a later one). Matched on the bound
    activation, not on the action's id, so it can never be spent by a second activation of the same action (AUTO77r1f1).
    The native final-rider transaction settles mandatory payment even after a finishing blow;
    ordinary technique_used effects stop once a terminal result has been declared.
    """
    token = _activation(ctx)
    if not token:
        return
    for name, _reads, _asks in FOCUS_MODES:
        condition = states.active(ctx.engine, ctx.actor, name)
        if condition is not None and _activation_intent((condition.data or {}).get("bound")) == _activation_intent(token):
            backlash = int((condition.data or {}).get("backlash") or 0)
            _drop(ctx.engine, ctx.actor, name, ctx.source)
            if backlash:
                _focus_backlash(ctx.engine, ctx.actor, condition, ctx.intent)


@hook("save")
def focus_save_disadvantage(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """"one target has Disadvantage on its saving throw" -- the creature the bound Fire talent's owner named."""
    engine, actor = ctx.engine, ctx.actor
    condition = _armed(engine, actor, FOCUS_SAVE_DISADVANTAGE, ctx)
    if condition is None or not _chosen_for(condition, subject):
        return None
    if not subject.active or subject.entity_id == actor.entity_id:
        return None
    return {"bonus": 0, "modes": ["DISADVANTAGE"]}


def _fire_damage_row(row: dict[str, Any]) -> bool:
    """Whether this row is, or carries on its hit, a Fire damage die roll -- the printed "one Fire damage roll"."""
    if [str(kind).upper() for kind in row.get("damage_types") or []] == ["FIRE"] or \
            (row.get("type") in ("damage", "extra_damage") and "FIRE" in [str(kind).upper() for kind in row.get("damage_types") or []]):
        return True
    return any(_fire_damage_row(child) for child in (row.get("on_hit") or []) if isinstance(child, dict))


#: Resolution-local marker: the printed "one Fire damage roll" has been answered by this activation. ``Context.damage_cache`` is
#: never persisted and is shared by every nested Context of one activation, so this spends the clause exactly once.
_DAMAGE_SLOT = "white_hot_focus_fire_roll"


def _focus_roll(ctx: Any, row: Any, subject: Any) -> bool:
    """Whether this is the one Fire damage roll of the bound Fire talent that the chosen creature takes.

    An area shares one roll between all its creatures, so which creature the Context names first is the executor's order, not
    the table's: the clause is answered when the named creature is among the activation's own recipients
    (``damage_cache["_area_targets"]``, the roster typed_executor records for area saves and packets)."""
    if not isinstance(row, dict) or not _fire_damage_row(row):
        return False
    condition = _armed(ctx.engine, ctx.actor, FOCUS_DAMAGE, ctx)
    if condition is None:
        return False
    chosen = _chosen(condition)
    roster = list((getattr(ctx, "damage_cache", None) or {}).get("_area_targets") or ())
    if chosen and not any(str(getattr(row_, "entity_id", "")) == chosen for row_ in roster) and \
            not (subject is not None and str(getattr(subject, "entity_id", "")) == chosen):
        return False
    cache = getattr(ctx, "damage_cache", None)
    if cache is None or cache.get(_DAMAGE_SLOT):
        return False
    cache[_DAMAGE_SLOT] = True
    return True


@hook("attack_damage_bonus")
def focus_damage(ctx: Any, target: Any, effect: Any) -> int | None:
    """"add your Path key ability modifier to one Fire damage roll", on a typed attack's own roll."""
    return int((ctx.numbers or {}).get("key_mod") or 0) if _focus_roll(ctx, effect, target) else None


@hook("damage_roll_bonus")
def focus_damage_roll(ctx: Any, effect: Any, kinds: Any) -> int | None:
    """The same printed clause on every other typed Fire damage die roll (a saving throw, an area)."""
    return int((ctx.numbers or {}).get("key_mod") or 0) if _focus_roll(ctx, effect, getattr(ctx, "target", None)) else None


# --------------------------------------------------------------------------- Overheat self-damage
@hook("final_damage")
def overheat_reduction(engine: Any, target: Any, amount: Any, damage_type: Any, source_id: Any,
                       source_actor_id: Any, intent: Any) -> dict[str, int] | None:
    """Furnace Heart's "Overheat self-damage is reduced by half" and Fire-Sovereign Incarnation's "reduced to 0": only the
    printed self-damage of an Overheat augment on the character that carries them, and only Fire damage."""
    if str(damage_type or "").upper() != "FIRE" or target is None or not source_id:
        return None
    if target.entity_id != source_actor_id or "overheat" not in str(source_id).lower():
        return None
    actor = engine.state.actors.get(str(source_actor_id))
    if actor is None:
        return None
    if states.active(engine, actor, SOVEREIGN) is not None:
        return {"amount": 0}  # "Overheat self-damage is reduced to 0"
    if states.active(engine, actor, FURNACE) is not None:
        return {"amount": (int(amount) or 0) // 2}  # "reduced by half", rounded down, never below zero
    return None


@hook("attack_mode")
def focus_attack_advantage(ctx: Any, target: Any) -> str | None:
    """One actual attack roll in the bound activation; a miss still spends it."""
    condition = _armed(ctx.engine, ctx.actor, FOCUS_ATTACK, ctx)
    if condition is None or not _chosen(condition) or not _chosen_for(condition, target):
        return None
    if ctx.damage_cache.get("white_hot_focus_attack_spent"):
        return None
    return "ADVANTAGE"


@hook("effect_resolution_scope")
def focus_resistance_scope(ctx: Any, effect: dict[str, Any]) -> Any:
    """The chosen creature's Fire Resistance is ignored only inside this activation's packets."""
    from .activation_resistance import bypass_scope
    condition = _armed(ctx.engine, ctx.actor, FOCUS_RESISTANCE, ctx)
    if condition is not None and _chosen(condition):
        return bypass_scope(ctx, _chosen(condition), ["fire"])
    return None


@effect("fire_focus_state")
def focus_state(ctx: Any, row: dict[str, Any]) -> None:
    """New reviewed state records its unpaid backlash; old sealed states do not."""
    if not _owns(ctx.engine, ctx.actor, "focus"):
        return
    name = str(row.get("name") or "")
    if name not in {name for name, _reads, _asks in FOCUS_MODES}:
        raise ValueError("unknown White-Hot Focus benefit")
    states.state(ctx, {**row, "type": "state"})
    condition = states.active(ctx.engine, ctx.actor, name)
    if condition is not None:
        _rewake(ctx.engine, ctx.actor, condition, {**condition.data, "backlash": int(ctx.numbers.get("pb") or 0)})


@hook("attack_roll_finished")
def focus_attack_spent(ctx: Any, target: Any, row: dict[str, Any], roll_id: str) -> None:
    condition = _armed(ctx.engine, ctx.actor, FOCUS_ATTACK, ctx)
    if roll_id and condition is not None and _chosen_for(condition, target):
        ctx.damage_cache["white_hot_focus_attack_spent"] = True


@hook("action_completed")
def focus_countered_completion(engine: Any, actor: Any, economy: str, source: str) -> None:
    """A newly sealed unpaid Focus also settles when its attempted talent was countered."""
    for name, _reads, _asks in FOCUS_MODES:
        condition = states.active(engine, actor, name)
        data = (condition.data or {}) if condition is not None else {}
        if not data.get("backlash") or data.get("bound_source") != source:
            continue
        _drop(engine, actor, name, source)
        _focus_backlash(engine, actor, condition, _active_intent(engine, actor))


def _focus_backlash(engine: Any, actor: Any, condition: Any, intent: Any) -> None:
    """Both completion paths deliver unpaid self-damage as Focus's own action.

    A display-source override keeps the triggering talent's defense identity;
    this independent damage must instead use the owning Focus catalog action.
    Legacy already-paid states carry no backlash and never enter this helper.
    """
    from ..typed_executor import Context, run_effects
    action = engine.action_catalog.get(condition.source_definition_id)
    if action is None:
        raise ValueError("White-Hot Focus backlash has no owning action")
    ctx = Context(engine, actor, action, intent, (action.parameters or {}).get("typed") or {}, [], None, {})
    run_effects(ctx, [{"type": "damage", "applies_to": "self", "flat": int(condition.data["backlash"]),
                      "damage_types": ["fire"], "evidence": "White-Hot Focus: after the attempted talent"}])
