"""Destruction sphere: Destructive Blast's Blast Type system (w4-destruction, 2026-09-28/29).

The owner: "make sure all the talents ... is applied." Destructive Blast's own rider used to read "If the
character applies another Blast Type or a Blast Shape talent, the GM applies it" -- every release used the
unshaped Unadorned Ruin blast (Force) no matter what the character actually owned, and the generic combinatorial
modifier pass (factory_compiler _augment_combinations) tried to cross every owned Blast Type/Shape with every
other one, producing dozens of near-duplicate "Destructive Blast + X + Y + Z" actions that all still fired the
same Force damage plus a "the GM applies it" line, and (via a Fracturing Break-style modifier scoped
"any_sphere_technique") could leak its rider onto unrelated techniques entirely.

This module makes Blast Type a sticky, free player choice (the same "condition holds a choice, a NONE-economy
button per option, a hook reads it" pattern as Saint-Body Rebuke: combat/ext/foundation_sacred_body.py), and gives
every Blast Shape (combat/ext/destruction_shapes.py) and the base Destructive Blast action one shared effect,
``destructive_blast_damage``, that rolls the CL-scaled Destruction Die of whichever Blast Type is selected (or the
Unadorned Ruin default: 1d8 Force), deals it, and then -- for a Blast Type with a rider -- rolls that type's own
secondary save and applies its real effect. authority/typed_mechanics/reviewed_final.d/destruction.json nulls out
every owned Blast Type/Shape/Refinement talent's `modifier` field so the old combinatorial pass leaves Destructive
Blast alone.

Blast Type Refinements:
  - Hammer Through the Line (requires Crushing Break): the `collision` hook (typed_executor._push) fires only when
    a push actually stops short because it hit something -- the same hook combat/ext/gu_brute.py's Hammer uses.
  - Break the Guard (requires Fracturing Break or Scouring Break): a second sticky choice ("Break the Guard:
    <option>"), applied alongside the Blast Type's own rider on the same failed save.
  - Ruinous Interruption (requires Staggering Break): adds a real reaction denial to Staggering Break's own
    (otherwise rider-only) save.

Not modeled (kept as GM-only riders, in _rider_effects and the Break the Guard "cover" option): Disadvantage on a
*single future* Concentration saving throw (Staggering Break, Ruinous Interruption) -- the table's condition rule
for a save only grants Disadvantage on every save of that ability for a duration, which would loosen the printed
"its next Concentration saving throw" into "every Constitution save until then"; and "cannot benefit from half
cover" (Break the Guard) -- the `cover` hook can only add cover, not suppress an existing source of it. Fracturing
Break's own "cracked object/structure" clause is not modeled either: this table has no generic object/structure HP
to apply "+1 Destruction Die" to.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

SPHERE = "tianxia.sphere.destruction"
BLAST = "TAL_DESTRUCTION_DESTRUCTIVE_BLAST"
TYPE_CHOICE = "condition:typed.destruction_blast_type"
GUARD_CHOICE = "condition:typed.destruction_break_the_guard"
GUARD_ACTIVE = "condition:typed.destruction_break_guard_active"

CRUSHING = "tianxia.talent.destruction.crushing_break"
FRACTURING = "tianxia.talent.destruction.fracturing_break"
STAGGERING = "tianxia.talent.destruction.staggering_break"
SCOURING = "tianxia.talent.destruction.scouring_break"
BREAK_GUARD = "tianxia.talent.destruction.break_the_guard"

WITHERING = "tianxia.talent.destruction.withering_break"
UNMAKING = "tianxia.talent.destruction.unmaking_pressure"
CHAIN = "tianxia.talent.destruction.calamity_chain_reaction"
FIELD = "tianxia.talent.destruction.destructive_domain_field_of_falling_forms"
LAST_IMPACT = "tianxia.talent.destruction.destructive_domain_court_of_the_last_impact"
NO_HALF_COVER = "condition:an_eui.break_guard.no_half_cover"  # the engine's own "cannot benefit from half cover" (gate2_engine)

UNSHAPED = {"id": None, "name": "Unadorned Ruin", "damage_type": "force", "sides": 8, "save_ability": None}
TYPES = {
    # Rider lane 10 (2026-09-29): the two Blast Types the list left out.
    WITHERING: {"id": WITHERING, "name": "Withering Break", "damage_type": "necrotic", "sides": 6, "save_ability": None, "no_save_rider": True},
    UNMAKING: {"id": UNMAKING, "name": "Unmaking Pressure", "damage_type": "force", "sides": 6, "save_ability": "con"},
    CRUSHING: {"id": CRUSHING, "name": "Crushing Break", "damage_type": "bludgeoning", "sides": 8, "save_ability": "str"},
    FRACTURING: {"id": FRACTURING, "name": "Fracturing Break", "damage_type": "force", "sides": 8, "save_ability": "con"},
    STAGGERING: {"id": STAGGERING, "name": "Staggering Break", "damage_type": "thunder", "sides": 6, "save_ability": "con"},
    SCOURING: {"id": SCOURING, "name": "Scouring Break", "damage_type": "slashing", "sides": 6, "save_ability": "dex"},
}
GUARD_OPTIONS = {"ac": "Reduce AC", "advantage": "Attack Advantage", "cover": "Ignore Half Cover", "off": "off"}

# Which Refinements each compiled actor owns is recorded on that fight's own "destruction" rows
# (combat/rules/feature_blocks.d/riders_lane10.json, compiled by destruction_block below and read by _has), so a
# fight is judged only by what it compiled and never by another fight's compile in the same process.


def _dice_by_cl(sides: int) -> list[list[int]]:
    return [[1, 4, 1, sides], [5, 10, 2, sides], [11, 16, 3, sides], [17, 20, 4, sides]]


def prepare_release(ctx: Any) -> int:
    """Freeze the paying release before its saves, shared with Destruction shapes.

    Newly declared shape saves pay Deepen even when everyone succeeds. Existing
    sealed plain saves and damage effects retain their historical payment timing.
    The existing Engine and Incarnation refunds count toward the final CP cost.
    """
    key = "destruction_final_cp"
    if key not in ctx.damage_cache:
        from .rider_support import cp_pool

        pool = cp_pool(ctx.actor)
        before = int(ctx.actor.resources.get(pool, 0)) if pool else 0
        _deepen(ctx)
        after = int(ctx.actor.resources.get(pool, 0)) if pool else 0
        listed = sum(amount for resource, amount in ctx.engine.effective_costs(ctx.actor, ctx.source, ctx.action.costs)
                     if resource == pool)
        discount = int(_sovereign(ctx.actor) and not ctx.actor.turn_flags.get("destruction_sovereign_discount")
                       and (listed > 0 or ctx.damage_cache.get("destruction_deepened")))
        ctx.damage_cache[key] = max(0, listed + before - after - discount)
    return int(ctx.damage_cache[key])


@effect("destruction_prepare_release")
def prepare_declared_release(ctx: Any, eff: dict[str, Any]) -> None:
    prepare_release(ctx)


def _self_exclusion(ctx: Any, eff: dict[str, Any]) -> bool:
    from . import needle

    if ctx.actor not in ctx.targets or not (eff.get("may_exclude_self") or _has(ctx.engine, ctx.actor, "controlled_self")):
        return False
    picked = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "blast_self", ctx.source), ctx.actor,
                        needle.CHOICE + "destruction_self", ["exclude", "include"],
                        labels={"exclude": "Exclude yourself", "include": "Affect yourself normally"}, preferred=["exclude"],
                        prompt=f"{ctx.action.display_name}: exclude {ctx.actor.display_name} from this area blast? "
                               "This costs nothing; other creatures are still affected.")
    return picked[:1] == ["exclude"]


@hook("before_target_reactions")
def blast_area_recipient(ctx: Any) -> None:
    """Choose self exclusion before any reaction can treat the caster as a target."""
    if not (ctx.typed.get("area") or {}).get("size_ft"):
        return
    save = next((row for row in ctx.typed.get("effects") or [] if row.get("type") == "destruction_shape_save"), None)
    if save is not None:
        ctx.damage_cache["destruction_self_selected"] = True
        if _self_exclusion(ctx, save):
            ctx.targets[:] = [row for row in ctx.targets if row is not ctx.actor]


@effect("destruction_shape_save")
def shape_save(ctx: Any, eff: dict[str, Any]) -> None:
    """Printed zero/paid save branches, declared only on newly sealed releases."""
    from .. import typed_executor as te
    paid = int(eff["locked_cp"]) if "locked_cp" in eff else prepare_release(ctx)
    save = {**eff, "type": "save"}
    if paid > 0:
        save["on_success"] = [{**row, "half": True} for row in eff.get("on_fail") or []
                              if row.get("type") == "destructive_blast_damage"]
    if not ctx.damage_cache.get("destruction_self_selected"):
        save["exclude_self"] = _self_exclusion(ctx, eff)
    te.run_effects(ctx, [save])


def current_type(engine: Any, actor: Any) -> dict[str, Any]:
    """The Blast Type currently selected by ``actor``'s sticky "Blast Type: <name>" choice, or the Unadorned
    Ruin default (Force) when none is selected or the character owns no Blast Type talent."""
    row = next(((c.data or {}) for c in actor.conditions.values() if c.condition_id == TYPE_CHOICE), None)
    chosen = row.get("type_id") if row else None
    return TYPES.get(chosen, UNSHAPED)


def current_type_id(engine: Any, actor: Any) -> str | None:
    """The raw ``type_id`` (``None`` for Unadorned Ruin) behind :func:`current_type`, for a Shape that locks its
    Blast Type in for as long as it remains active (Calamity Mantle, Ruin-Binding Tether: "The Blast Type and all
    other parameters are selected when [it is created] and cannot be changed while it remains active")."""
    row = next(((c.data or {}) for c in actor.conditions.values() if c.condition_id == TYPE_CHOICE), None)
    return row.get("type_id") if row else None


@hook("compile_actions")
def blast_type_buttons(info: dict[str, Any]) -> list[Any] | None:
    owned = [mid for mid in TYPES if mid in info["owned_ids"]]
    if not owned:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    options = [("off", "Unshaped Ruin (Force)"), *((mid, TYPES[mid]["name"]) for mid in owned)]
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.destruction_blast_type.{key}", display_name=f"Blast Type: {label}",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"setting_only": True, "typed": {"effects": [{"type": "destruction_blast_type_choice", "choice": key}], "numbers": info["numbers"],
                              "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0, "player_only": True})
        for key, label in options]


@effect("destruction_blast_type_choice")
def _choose_type(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, TYPE_CHOICE, ctx.source)
    choice = eff.get("choice")
    if choice and choice != "off":
        ctx.engine._apply_condition(ctx.actor, TYPE_CHOICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"type_id": choice, "label": f"Blast Type: {TYPES[choice]['name']}"})


@hook("compile_actions")
def break_guard_buttons(info: dict[str, Any]) -> list[Any] | None:
    if BREAK_GUARD not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.break_the_guard.{key}", display_name=f"Break the Guard: {label}",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"setting_only": True, "typed": {"effects": [{"type": "destruction_break_guard_choice", "choice": key}], "numbers": info["numbers"],
                              "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0, "player_only": True})
        for key, label in GUARD_OPTIONS.items()]


@effect("destruction_break_guard_choice")
def _choose_guard(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, GUARD_CHOICE, ctx.source)
    choice = eff.get("choice")
    if choice and choice != "off":
        ctx.engine._apply_condition(ctx.actor, GUARD_CHOICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"choice": choice, "label": f"Break the Guard: {GUARD_OPTIONS.get(choice, '')}"})


def _break_guard_effect(ctx: Any, type_id: str | None) -> dict[str, Any] | None:
    """The selected Break the Guard option, as one effect that ``break_guard_option`` resolves.

    The three options are separate printed outcomes (AC -1 / Advantage on the next attack roll / no half cover),
    so the choice is carried as ``option`` and the effect itself applies whichever native one it names -- that keeps
    "only one option at a time" (below) in one place instead of spread over three native effects.

    ``type_id`` is the Blast Type that actually resolved *this* release, passed down from ``_rider_effects``, and
    never re-read from the caster's sticky choice: Ruin-Binding Tether and Calamity Mantle print that the Blast Type
    is chosen at activation and cannot change while they last, so their Pulse releases a frozen Type. Reading the live
    choice instead filed a Scouring Break pulse's Advantage under Fracturing Break, and the option change then left
    that Advantage up on the strength of a Blast Type that never granted one."""
    choice = next((str((c.data or {}).get("choice")) for c in ctx.actor.conditions.values() if c.condition_id == GUARD_CHOICE), "ac")
    if choice == "off":
        return None
    return {"type": "destruction_break_guard_option", "applies_to": "target", "option": choice,
            "type_id": str(type_id or ""),
            "evidence": f"Break the Guard: {GUARD_OPTIONS.get(choice, 'Reduce AC')}"}


def _guard_native_row(option: str) -> dict[str, Any]:
    """The ordinary typed effect one printed Break the Guard option produces (nothing Destruction-specific)."""
    if option == "advantage":
        return {"type": "advantage", "applies_to": "target", "on": "the next attack roll against it",
                "expires_on": "START_OF_SOURCE_NEXT_TURN",
                "evidence": "Break the Guard: the next attack roll against it gains Advantage"}
    if option == "cover":
        return {"type": "destruction_no_half_cover", "applies_to": "target",
                "evidence": "Break the Guard: it cannot benefit from half cover until the start of your next turn"}
    return {"type": "ac_bonus", "applies_to": "target", "flat": -1, "expires_on": "START_OF_SOURCE_NEXT_TURN",
            "evidence": "Break the Guard: AC -1 until the start of your next turn"}


def _recorded_ids(raw: Any) -> list[str]:
    """The exact instance ids a guard marker recorded, read back from its comma-joined string (strings only)."""
    return [part for part in str(raw or "").split(",") if part]


def _drop_guard_instance(ctx: Any, subject: Any, prior: dict[str, Any], source_actor_id: str) -> None:
    """Take off exactly what the *earlier* Break the Guard option left on ``subject``.

    The marker records the exact condition/modifier instances that option created, plus the ``caster`` that
    created them and the ``origin`` (activation) they came from, so this removes that option and nothing else.
    Two things that a field-only or current-caster match got wrong:

    - the creature-wide "only one option at a time" rule is about the creature, not about one caster. When
      caster B changes the option over one caster A put up, the earlier instance is A's, so it is found by the
      marker A wrote -- ``origin`` and ``caster`` -- not by ``ctx.actor``;
    - Fracturing Break grants its own Advantage from the same activation that carries Break the Guard's, and the
      engine holds those as two separate modifiers. The recorded ids name the guard's one exactly, so
      Fracturing Break's printed Advantage survives without needing an exemption for it.

    A marker written before those ids were recorded (an in-flight saved fight from this branch) falls back to
    matching the marker's source actor and recorded activation by field; that older form cannot separate the Fracturing
    overlap, so there the earlier Advantage is left in place rather than risk removing the Blast Type's benefit."""
    from .rider_support import remove_instance

    option = str(prior.get("option") or "")
    origin = str(prior.get("origin") or "")
    if not origin:
        return
    caster = str(prior.get("caster") or "") or source_actor_id
    conditions = _recorded_ids(prior.get("conds"))
    modifiers = _recorded_ids(prior.get("mods"))

    def drop_modifier(mid: str) -> None:
        if mid in subject.modifiers:
            del subject.modifiers[mid]
            ctx.engine._append_event("MODIFIER_REMOVED", ctx.actor.entity_id, actor_id=ctx.actor.entity_id,
                                     target_ids=(subject.entity_id,),
                                     payload={"modifier_id": mid, "reason": "BREAK_THE_GUARD_OPTION_CHANGED"})

    if conditions:
        for iid in conditions:
            remove_instance(ctx.engine, subject, iid, origin)
    elif option == "cover":
        # an older marker with no recorded instances: "cannot benefit from half cover" is Break the Guard's own
        # condition, so every copy the *recorded* caster put on this creature goes.
        for iid, condition in list(subject.conditions.items()):
            if condition.condition_id == NO_HALF_COVER and condition.source_actor_id == caster:
                remove_instance(ctx.engine, subject, iid, origin)

    if modifiers:
        for mid in modifiers:
            drop_modifier(mid)
        return
    if option == "cover" or conditions:
        return
    if option == "advantage" and str(prior.get("type_id") or "") == FRACTURING:
        return  # older marker, no ids: Fracturing Break's Advantage shares this modifier and must survive
    fields = ("attack_mode", "incoming_attack_mode") if option == "advantage" else None
    for mid, modifier in list(subject.modifiers.items()):
        if modifier.source_definition_id != origin or modifier.source_actor_id != caster:
            continue
        if option == "advantage" and modifier.target_field not in fields:
            continue
        if option == "ac" and not modifier.target_field.startswith("armor_class"):
            continue
        drop_modifier(mid)


@effect("destruction_break_guard_option")
def break_guard_option(ctx: Any, eff: dict[str, Any]) -> None:
    """Break the Guard: "A creature can suffer only one option from Break the Guard at a time: if the chosen
    option changes while an earlier one is still on it, the GM removes one."

    The printed option is chosen once by the character and rides every Fracturing/Scouring failure, so a creature
    that fails one Fracturing save and then a Scouring save while the option is still up used to hold two options
    at once (AC -1 *and* no half cover). The active option is recorded on the creature together with the exact
    modifier/condition instances it created, the caster and activation that created them, and the Blast Type that
    actually resolved this release; applying a different option removes exactly that earlier instance and then
    applies the new one. Same-option instance lifecycle is unchanged."""
    subject = ctx.target
    option = str(eff.get("option") or "ac")
    if subject is None or not subject.active:
        return
    from .. import typed_executor as te

    marker = next((c for c in subject.conditions.values() if c.condition_id == GUARD_ACTIVE), None)
    if marker is not None:
        prior = dict(marker.data or {})
        if str(prior.get("option")) != option:
            _drop_guard_instance(ctx, subject, prior, marker.source_actor_id)
        from .rider_support import remove_instance

        remove_instance(ctx.engine, subject, marker.instance_id, ctx.source)
    # Only this option's own output is recorded. When Fracturing Break is the type its Advantage was already applied
    # by the rider that ran just before this effect, so it is inside the snapshot and is never recorded here.
    before_modifiers = set(subject.modifiers)
    before_conditions = set(subject.conditions)
    sub = te.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [subject], subject, ctx.damage_cache)
    te.run_effects(sub, [_guard_native_row(option)])
    # sorted(), so the recorded string is the same whatever order a commit and reload rebuilds these dicts in.
    created_modifiers = sorted(mid for mid in subject.modifiers if mid not in before_modifiers)
    created_conditions = sorted(iid for iid in subject.conditions if iid not in before_conditions)
    ctx.engine._apply_condition(subject, GUARD_ACTIVE, ctx.source, ctx.actor.entity_id,
                                expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"option": option, "origin": ctx.source, "caster": ctx.actor.entity_id,
                                      "type_id": str(eff.get("type_id") or ""),
                                      "mods": ",".join(created_modifiers), "conds": ",".join(created_conditions),
                                      "label": f"Break the Guard: {GUARD_OPTIONS.get(option, 'Reduce AC')}"})


def _rider_effects(ctx: Any, info: dict[str, Any]) -> list[dict[str, Any]]:
    """The Blast Type's own on-fail rider, plus any owned Refinement that adds to it (Ruinous Interruption,
    Break the Guard). Called only once the blast's damage has already landed on ``ctx``'s single subject."""
    owned = {kind: _has(ctx.engine, ctx.actor, kind) for kind in ("hammer", "ruinous", "break_guard")}
    mid = info.get("id")
    effects: list[dict[str, Any]] = []
    if mid == CRUSHING:
        effects.append({"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away",
                        "evidence": "push the creature 10 feet away from the blast's point of origin"})
    elif mid == FRACTURING:
        effects.append({"type": "advantage", "applies_to": "target", "on": "the next attack roll against it", "expires_on": "START_OF_SOURCE_NEXT_TURN",
                        "evidence": "the next attack roll made against that creature before the start of your next turn gains Advantage"})
    elif mid == SCOURING:
        effects.append({"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN",
                        "evidence": "it cannot take Reactions until the start of your next turn"})
    elif mid == STAGGERING:
        # "Disadvantage on its next Concentration saving throw before the start of your next turn": one save, used up
        # (combat/concentration.py save_mode; rider lane 10 -- the table has read "next" Concentration saves since).
        effects.append({"type": "disadvantage", "applies_to": "target", "on": "its next Concentration saving throw",
                        "expires_on": "START_OF_SOURCE_NEXT_TURN", "evidence": "Staggering Break: Disadvantage on its next Concentration saving throw"})
        if owned.get("ruinous"):
            effects.append({"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN",
                            "evidence": "Ruinous Interruption: cannot take Reactions until the start of your next turn"})
    elif mid == UNMAKING:
        effects.append({"type": "destruction_unmake_defense", "applies_to": "target",
                        "evidence": "Unmaking Pressure: one visible temporary defensive benefit affecting it is suppressed until the start of your next turn"})
    if mid in (FRACTURING, SCOURING) and owned.get("break_guard"):
        guard = _break_guard_effect(ctx, str(mid))
        if guard:
            effects.append(guard)
    return effects


@effect("destructive_blast_damage", harmful=True)
def destructive_blast_damage(ctx: Any, eff: dict[str, Any]) -> None:
    """Shared by the base Destructive Blast action and every Blast Shape (destruction_shapes.py): rolls the
    CL-scaled Destruction Die of the caster's currently selected Blast Type (or Unadorned Ruin), deals it, then
    -- unless ``half`` (Returning Calamity's successful save) -- rolls that type's own secondary save and applies
    its real rider. Placed inside a "save" or "attack" effect's on_fail/on_hit list, so ``ctx`` is already
    narrowed to the one subject that failed or was hit (typed_executor.block_save/block_attack build that inner
    Context before running it).

    ``locked_type_id`` (present, possibly None) pins the Blast Type instead of reading the live sticky choice --
    Calamity Mantle and Ruin-Binding Tether both print "the Blast Type ... cannot be changed while it remains
    active", so their Pulse re-releases must keep using whichever type was selected at activation."""
    from .. import typed_executor as te
    from factory_authoring.typed_mechanics import dice_for_cl
    from ..gate2_runtime_models import DiceSpec

    info = TYPES.get(eff["locked_type_id"], UNSHAPED) if "locked_type_id" in eff else current_type(ctx.engine, ctx.actor)
    subject = ctx.target if ctx.target is not None else (ctx.targets[0] if len(ctx.targets) == 1 else None)
    if subject is None or not subject.active:
        return
    spec = dice_for_cl(_dice_by_cl(int(info["sides"])), ctx.numbers.get("cl")) or {"count": 1, "sides": info["sides"]}
    deepened = None if "locked_dice_count" in eff else _deepen(ctx)
    if "locked_dice_count" in eff:
        spec = {"count": int(eff["locked_dice_count"]), "sides": int(info["sides"])}
    elif deepened:
        spec = {"count": deepened, "sides": int(info["sides"])}
    roll = ctx.engine.roller.roll(DiceSpec(count=int(spec["count"]), sides=int(spec["sides"]), modifier=0),
                                  actor_id=ctx.actor.entity_id, reason=f"DAMAGE:{ctx.source}")
    ctx.engine._record_roll(roll)
    ctx.engine._append_event("DAMAGE_ROLLED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(subject.entity_id,),
                             payload=roll.model_dump(mode="json"))
    half = bool(eff.get("half"))
    amount = roll.total // 2 if half else roll.total
    sub = te.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [subject], subject, ctx.damage_cache)
    if info.get("id") == WITHERING and _has(ctx.engine, ctx.actor, "ashen") and not half and int(subject.temporary_hp or 0) > 0:
        # Ashen Denial: "If the creature already has Temporary HP, remove those Temporary HP before applying damage."
        before = int(subject.temporary_hp)
        subject.temporary_hp = 0
        ctx.engine._append_event("TEMP_HP_GRANTED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(subject.entity_id,),
                                 payload={"offered": 0, "before": before, "after": 0, "removed_by": "Ashen Denial"})
    pre_saved = None
    if info.get("id") == STAGGERING and _has(ctx.engine, ctx.actor, "ruinous") and not half and subject.concentration is not None:
        # Ruinous Interruption: "If the creature is Concentrating, it also has Disadvantage on the Concentration saving throw caused by the
        # blast's damage" -- its Staggering save is rolled before that damage lands, so a failure presses the save the damage causes.
        before_events = len(ctx.engine.events)
        te.run_effects(sub, [{"type": "save", "ability": "con", "on_fail": [
            {"type": "disadvantage", "applies_to": "target", "on": "its next Concentration saving throw", "expires_on": "START_OF_SOURCE_NEXT_TURN",
             "evidence": "Ruinous Interruption: Disadvantage on the Concentration saving throw this blast's damage causes"},
            {"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN",
             "evidence": "Ruinous Interruption: cannot take Reactions until the start of your next turn"}], "on_success": []}])
        rolled = next((e for e in ctx.engine.events[before_events:] if e.event_type == "SAVE_ROLLED"), None)
        pre_saved = bool(rolled) and bool((rolled.payload or {}).get("success"))
    was_active = subject.active
    from .attack_defenses import packet_defenses

    provenance = ctx.attack_damage_context
    if provenance is not None and provenance.target_id != subject.entity_id:
        provenance = None
    damage_start = len(ctx.engine.events)
    with packet_defenses(ctx.engine, ctx.attack_defense_spec):
        ctx.engine._commit_damage(subject, amount, str(info["damage_type"]).upper(), ctx.source, ctx.actor.entity_id, ctx.intent,
                                 reaction_depth=0, attack_context=provenance)
    if eff.get("damage_required") and not any(
            event.event_type == "DAMAGE_COMMITTED" and event.source_definition_id == ctx.source
            and subject.entity_id in event.target_ids
            and int((event.payload or {}).get("hp_damage") or 0) + int((event.payload or {}).get("temporary_hp_absorbed") or 0) > 0
            for event in ctx.engine.events[damage_start:]):
        return
    _after_blast_damage(ctx, subject, info, was_active)
    if half or not subject.active:
        return
    if info.get("no_save_rider"):
        te.run_effects(sub, _no_save_rider(ctx, info))
        return
    if not info.get("save_ability"):
        return
    if pre_saved is not None:
        if not pre_saved:  # the failed Staggering save's own "next Concentration save" is still owed for a later save
            te.run_effects(sub, [{"type": "disadvantage", "applies_to": "target", "on": "its next Concentration saving throw",
                                  "expires_on": "START_OF_SOURCE_NEXT_TURN", "evidence": "Staggering Break"}])
        return
    rider = _rider_effects(ctx, info)
    if rider:
        te.run_effects(sub, [{"type": "save", "ability": info["save_ability"], "on_fail": rider, "on_success": []}])


@hook("collision")
def hammer_through_the_line(ctx: Any, target: Any, blocked_at: Any, remaining_ft: int) -> None:
    """Hammer Through the Line: when Crushing Break's own push (destructive_blast_damage's rider, above) stops
    short because it hit something, the pushed creature takes one more Destruction Die of Bludgeoning and falls
    Prone; if it collided with another creature (not a wall), that creature makes its own Dexterity save or falls
    Prone too. Same collision hook and gating pattern as Hammer (combat/ext/gu_brute.py)."""
    info = (TYPES.get(ctx.typed["destruction_frozen_type"], UNSHAPED) if "destruction_frozen_type" in ctx.typed
            else current_type(ctx.engine, ctx.actor))
    if info["id"] != CRUSHING or not _has(ctx.engine, ctx.actor, "hammer"):
        return
    gate = ("hammer_through_the_line", target.entity_id)
    if ctx.damage_cache.get(gate):
        return
    ctx.damage_cache[gate] = True
    from .. import typed_executor as te
    from factory_authoring.typed_mechanics import dice_for_cl
    from ..gate2_runtime_models import DiceSpec

    from .fight_ownership import block_rows

    spec = ({"count": 1, "sides": 8} if any(row.get("single_collision_die") for row in
            block_rows(ctx.engine, ctx.actor, "destruction", "hammer"))
            else dice_for_cl(_dice_by_cl(8), ctx.numbers.get("cl")) or {"count": 1, "sides": 8})
    roll = ctx.engine.roller.roll(DiceSpec(count=int(spec["count"]), sides=int(spec["sides"]), modifier=0),
                                  actor_id=ctx.actor.entity_id, reason=f"DAMAGE:{ctx.source}:hammer")
    ctx.engine._record_roll(roll)
    ctx.engine._commit_damage(target, roll.total, "BLUDGEONING", ctx.source, ctx.actor.entity_id, ctx.intent, reaction_depth=0)
    if not target.active:
        return
    sub = te.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, {})
    te.run_effects(sub, [{"type": "condition", "applies_to": "target", "condition": "prone", "evidence": "falls Prone"}])
    blocker = next((row for row in ctx.engine.state.actors.values() if row.active and row.entity_id != target.entity_id
                    and row.position == blocked_at), None)
    if blocker is not None:
        sub2 = te.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [blocker], blocker, {})
        te.run_effects(sub2, [{"type": "save", "ability": "dex", "on_fail": [
            {"type": "condition", "applies_to": "target", "condition": "prone", "evidence": "falls Prone"}], "on_success": []}])
    else:
        ctx.rider("Hammer Through the Line: the pushed creature struck a wall or obstacle, not another creature.")


# ------------------------------------------------------------------------------------------------ rider lane 10 (2026-09-29)
def _no_save_rider(ctx: Any, info: dict[str, Any]) -> list[dict[str, Any]]:
    """Withering Break: "A creature damaged by Withering Break cannot regain Hit Points until the start of your next turn" (no save);
    Ashen Denial: "A creature damaged by Withering Break cannot gain Temporary HP until the start of your next turn"."""
    rows: list[dict[str, Any]] = [{"type": "healing_reduction", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN",
                                   "evidence": "cannot regain Hit Points until the start of your next turn"}]
    if _has(ctx.engine, ctx.actor, "ashen"):
        rows.append({"type": "deny_temp_hp", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN",
                     "evidence": "Ashen Denial: cannot gain Temporary HP until the start of your next turn"})
    return rows


@effect("destruction_no_half_cover")
def no_half_cover(ctx: Any, eff: dict[str, Any]) -> None:
    """"Cannot benefit from half cover until the start of your next turn": the engine's own no-half-cover condition (gate2_engine)."""
    subject = ctx.target
    if subject is not None and subject.active:
        from .rider_support import remove_instance
        for iid, condition in list(subject.conditions.items()):
            if condition.condition_id == NO_HALF_COVER and condition.source_actor_id == ctx.actor.entity_id:
                remove_instance(ctx.engine, subject, iid, ctx.source)
        ctx.engine._apply_condition(subject, NO_HALF_COVER, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                    data={"label": "Cannot benefit from half cover"})


SUPPRESSED = "condition:typed.destruction_suppressed"
_DEFENSES = ("armor_class", "armor_class_vs_melee", "armor_class_vs_ranged", "damage_resistance", "damage_immunity")


@effect("destruction_unmake_defense")
def unmake_defense(ctx: Any, eff: dict[str, Any]) -> None:
    """Unmaking Pressure: "choose one visible temporary defensive benefit affecting it, such as a temporary AC bonus, temporary damage
    resistance ... That benefit is suppressed until the start of your next turn." The table's temporary benefits are its expiring
    modifiers (an AC bonus, a Resistance); the one taken off is the largest AC bonus, else the first Resistance. It comes back at the
    start of the user's next turn if its own time has not run out (a condition holds it meanwhile)."""
    subject = ctx.target
    if subject is None or not subject.active:
        return
    temporary = [(mid, m) for mid, m in subject.modifiers.items() if m.target_field in _DEFENSES and m.expires_on
                 and not (m.target_field.startswith("armor_class") and int(m.value) <= 0)]
    if not temporary:
        return
    temporary.sort(key=lambda row: (not row[1].target_field.startswith("armor_class"), -(int(row[1].value) if str(row[1].value).lstrip("-").isdigit() else 0)))
    mid, modifier = temporary[0]
    from .suppressed_effects import lifetime
    clock = lifetime(ctx.engine, subject, modifier)
    del subject.modifiers[mid]
    ctx.engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=ctx.actor.entity_id, target_ids=(subject.entity_id,),
                             payload={"modifier_id": mid, "reason": "SUPPRESSED"})
    ctx.engine._apply_condition(subject, SUPPRESSED, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": f"Unmaking Pressure: {modifier.target_field.replace('_', ' ')} {modifier.value} suppressed",
                                      "modifier": modifier.model_dump(mode="json"), "lifetime": clock})


@hook("turn_start")
def restore_suppressed(engine: Any, actor: Any) -> None:
    """"Suppressed until the start of your next turn": at the start of the user's turn each benefit it suppressed comes back, unless its
    own time has run out meanwhile."""
    from .suppressed_effects import restore

    for creature in engine.state.actors.values():
        for iid, condition in list(creature.conditions.items()):
            if condition.condition_id != SUPPRESSED or condition.source_actor_id != actor.entity_id:
                continue
            creature.conditions.pop(iid, None)
            engine._append_event("CONDITION_REMOVED", "system:destruction.unmaking_pressure", actor_id=actor.entity_id, target_ids=(creature.entity_id,),
                                 payload={"condition_id": SUPPRESSED, "instance_id": iid})
            modifier = (condition.data or {}).get("modifier") or {}
            if modifier:
                restore(engine, creature, modifier, (condition.data or {}).get("lifetime") or {"expiry": modifier.get("expires_on")}, modifier=True)


def _after_blast_damage(ctx: Any, subject: Any, info: dict[str, Any], was_active: bool) -> None:
    """What happens once a blast's damage has landed: Field of Falling Forms' half-cover denial inside it, Calamity Chain Reaction on a
    creature dropped to 0 Hit Points, Court of the Last Impact's failed-save choice is on the save (after_save below)."""
    engine, actor = ctx.engine, ctx.actor
    field = _domain(engine, actor, FIELD)
    if field is not None and subject.active and _inside(field, subject):
        no_half_cover(ctx if ctx.target is subject else _sub(ctx, subject), {})
    if was_active and not subject.active and _has(engine, actor, "chain") and not ctx.damage_cache.get("destruction_chain"):
        _chain_reaction(ctx, subject, info)
    if _has(engine, actor, "ruin_trace"):
        ruin_trace(ctx, subject, info)


def _sub(ctx: Any, subject: Any) -> Any:
    from .. import typed_executor as te

    return te.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [subject], subject, ctx.damage_cache)


def _domain(engine: Any, owner: Any, feature: str) -> Any | None:
    from .. import zones

    return next((zone for zone in zones.typed_zones(engine) if zone.active and zone.owner_id == owner.entity_id and feature in str(zone.source_definition_id)), None)


def _inside(zone: Any, creature: Any) -> bool:
    return any((c.x, c.y) == (creature.position.x, creature.position.y) for c in zone.affected_cells)


def _chain_reaction(ctx: Any, dropped: Any, info: dict[str, Any]) -> None:
    """Calamity Chain Reaction: "When your Destructive Blast ... reduces a creature to 0 Hit Points, you may spend 1 CP ... Choose one creature
    ... within 10 feet of the destroyed target. That creature ... takes one Destruction Die of the selected Blast Type's damage type. If the
    original blast used an area Blast Shape, choose only one secondary target total." (Once per release; the nearest hostile creature.)"""
    from .rider_support import cp_pool as _cp_pool
    from .needle import CHOICE, ask, checkpoint_id
    from ..gate2_runtime_models import DiceSpec
    from ..typed_executor import effect_subjects

    engine, actor = ctx.engine, ctx.actor
    # Secondary targets bypass ordinary attack targeting. Consult the same pure
    # owned subject restrictions before choices, costs and damage rolls.
    row = {"type": "damage", "applies_to": "target", "damage_type": info["damage_type"]}
    near = sorted([other for other in engine.state.actors.values() if other.active and other.team_id != actor.team_id
                   and engine.grid.distance_ft(other.position, dropped.position) <= 10
                   and effect_subjects(_sub(ctx, other), row, harmful=True)], key=lambda other: (other.current_hp, other.entity_id))
    pool = _cp_pool(actor)
    if not near or pool is None or actor.resources.get(pool, 0) < 1:
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "CHAIN", actor.entity_id, dropped.entity_id), actor, CHOICE + "destruction_chain",
                 [other.entity_id for other in near], labels={other.entity_id: other.display_name for other in near}, allow_decline=True,
                 prompt=f"Calamity Chain Reaction: {actor.display_name}'s Destructive Blast reduced {dropped.display_name} to 0 Hit Points. "
                        f"Spend 1 CP (cultivation energy), with no additional Action, to deal 1d{info['sides']} {info['damage_type']} damage "
                        "now to one creature within 10 feet of it?", target_id=dropped.entity_id, name="Calamity Chain Reaction", feature_id=CHAIN)
    victim = engine.state.actors.get(picked[0]) if picked else None
    if victim is None or victim not in near or not effect_subjects(_sub(ctx, victim), row, harmful=True):
        return
    ctx.damage_cache["destruction_chain"] = True
    engine._spend_resource(actor, pool, 1, f"passive:{CHAIN}")
    roll = engine.roller.roll(DiceSpec(count=1, sides=int(info["sides"]), modifier=0), actor_id=actor.entity_id, reason=f"DAMAGE:{ctx.source}:chain")
    engine._record_roll(roll)
    engine._commit_damage(victim, roll.total, str(info["damage_type"]).upper(), ctx.source, actor.entity_id, ctx.intent, reaction_depth=0)


LAST_IMPACT_CHOICES = {"prone": "It falls Prone", "reactions": "It cannot take Reactions until the start of your next turn",
                       "healing": "It cannot regain Hit Points until the start of your next turn"}


@hook("after_save")
def last_impact_choice(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """Court of the Last Impact: "the first time each round a creature fails a saving throw against your Destructive Blast inside the
    domain, choose one: it falls Prone, cannot take Reactions until the start of your next turn, or cannot regain Hit Points until the
    start of your next turn." (A blast's own save: a Blast Shape's Dexterity save or its Blast Type's rider save.)"""
    engine, actor = ctx.engine, ctx.actor
    if not failed or subject is None or not subject.active or subject.team_id == actor.team_id:
        return
    if "destructive_blast_damage" not in str((ctx.typed or {}).get("effects")):
        return  # not a Destructive Blast release (the base action or a Blast Shape)
    court = _domain(engine, actor, LAST_IMPACT)
    key = f"destruction_round_last_impact:{engine.state.round_number}:{subject.entity_id}"
    if court is None or not _inside(court, subject) or actor.turn_flags.get(key):
        return
    actor.turn_flags[key] = True
    from .needle import CHOICE, ask, checkpoint_id
    from .. import typed_executor as te

    picked = ask(engine, ctx.intent, checkpoint_id(engine, "LAST_IMPACT", actor.entity_id, subject.entity_id), actor, CHOICE + "destruction_last_impact",
                 list(LAST_IMPACT_CHOICES), labels=dict(LAST_IMPACT_CHOICES), preferred=["prone"],
                 prompt=f"Court of the Last Impact: {subject.display_name} failed its save -- choose one", target_id=subject.entity_id)
    row = {"prone": {"type": "condition", "applies_to": "target", "condition": "prone"},
           "reactions": {"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN"},
           "healing": {"type": "healing_reduction", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN",
                       "evidence": "cannot regain Hit Points until the start of your next turn"}}.get(picked[0] if picked else "prone")
    te.run_effects(_sub(ctx, subject), [row])


@hook("technique_used")
def scouring_splinters(ctx: Any) -> None:
    """Scouring Break: "Spaces meaningfully affected by an area Blast Shape may become littered with splinters, shards, torn stone, or
    cutting residue until the start of your next turn. Moving through such a space costs an additional 5 feet of movement." -- difficult
    ground over the blast's area until the start of the user's next turn."""
    typed = ctx.typed or {}
    area = typed.get("area") or {}
    if not area.get("size_ft") or (area.get("shape") or "sphere") == "wall" or current_type(ctx.engine, ctx.actor).get("id") != SCOURING:
        return
    if not any(isinstance(e, dict) and "destructive_blast_damage" in str(e) for e in typed.get("effects") or []):
        return
    from .. import typed_executor as te
    from . import placed
    from .effect_durations import token

    aim = ctx.damage_cache.get("_checkpoint_aim") or ctx.actor.position
    cells = te.area_cells(ctx.engine, ctx.actor.position, aim, area)
    if not cells:
        return
    zone = placed.place(ctx.engine, ctx.actor, source=ctx.source, tag="scouring_splinters", cells=list(cells), name="Scouring splinters",
                        difficult="all", material="rubble", placed={"until": token("start", ctx.actor.entity_id, int(ctx.actor.turns_started) + 1),
                                                                   "label": "Scouring Break: splinters (difficult ground)"})
    return None


@hook("event")
def splinters_clear(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "TURN_STARTED":
        return
    from . import placed
    for zone in list(placed.of(engine, "scouring_splinters")):
        until = placed.data(zone).get("until")
        if until and placed.deadline_due(engine, zone, str(until)):
            placed.drop(engine, zone, "the splinters settle")


# ------------------------------------------------------------------------------------------------ Deepen the Calamity and its talents
DEEPEN_CHOICE = "condition:typed.destruction_deepen"
CRACKING_CHOICE = "condition:typed.destruction_heaven_cracking"
ENGINE_TALENT = "tianxia.talent.destruction.catastrophe_engine"
CRACKING = "tianxia.talent.destruction.heaven_cracking_release"
RUIN_TRACE = "tianxia.talent.destruction.ruin_that_remembers"


@hook("status_description")
def deepen_status_description(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    """Reuse these legacy selectors' existing source-backed button descriptions."""
    if row.get("condition_id") not in {DEEPEN_CHOICE, CRACKING_CHOICE}:
        return None
    action = engine.action_catalog.get(row.get("source_definition_id"))
    if action is None or holder is None or action.owner_id != holder.entity_id:
        return None
    text = action.parameters.get("description")
    if not text:
        return None
    return {"text": str(text).replace("CP", "cultivation points (the blast's paying Path resource)"),
            "source_ability": action.display_name.partition(":")[0],
            "handling": "Selecting this option is free. The table applies its additional cost and effect when you release the blast."}


@hook("compile_actions")
def deepen_buttons(info: dict[str, Any]) -> list[Any] | None:
    """Deepen the Calamity (a core Destruction ability the catalog never listed: "Destructive Blast Augment. Cost: 1 CP. Instead of using the
    ordinary Destructive Blast progression, your Destructive Blast deals: 1 Destruction Die + 1 additional Destruction Die per 2 Cultivation
    Levels, rounded down."): a sticky free choice, paid by each release while it is on. Heaven-Cracking Release rides it."""
    if SPHERE not in info["spheres"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    def button(key: str, label: str, effect_type: str, value: bool, text: str) -> Any:
        return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.destruction_{key}", display_name=label, owner_id=info["actor_id"],
                                economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                                parameters={"typed": {"effects": [{"type": effect_type, "on": value}], "numbers": info["numbers"], "duration": {"kind": "instant"},
                                                      "riders": []}, "expected_damage": 0, "player_only": True, "description": text})

    out = [button("deepen.on", "Deepen the Calamity: on", "destruction_deepen_choice", True,
                  "Each Destructive Blast pays 1 CP more and deals 1 Destruction Die + 1 per 2 Cultivation Levels (stays until changed)."),
           button("deepen.off", "Deepen the Calamity: off", "destruction_deepen_choice", False, "Destructive Blast uses its ordinary dice.")]
    if CRACKING in info["owned_ids"]:
        out.append(button("cracking.on", "Heaven-Cracking Release: next Deepened blast", "destruction_cracking_choice", True,
                          "The next Deepened Destructive Blast pays 2 CP more: one creature that failed its save against it loses Reactions and has "
                          "its Speed halved until the start of your next turn (once per fight)."))
    return out


@effect("destruction_deepen_choice")
def _deepen_choice(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, DEEPEN_CHOICE, ctx.source)
    if eff.get("on"):
        ctx.engine._apply_condition(ctx.actor, DEEPEN_CHOICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"label": "Deepen the Calamity: on (1 CP a blast)"})


@effect("destruction_cracking_choice")
def _cracking_choice(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, CRACKING_CHOICE, ctx.source)
    if eff.get("on") and not ctx.actor.turn_flags.get("destruction_round_cracking_used"):
        ctx.engine._apply_condition(ctx.actor, CRACKING_CHOICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"label": "Heaven-Cracking Release: the next Deepened blast"})


def _deepen(ctx: Any) -> int | None:
    """The Deepened dice count for this release, paying its 1 CP once per activation (every target of an area shares it); None when off or
    unaffordable. Catastrophe Engine and Heaven-Cracking Release ride the payment."""
    from .rider_support import cp_pool as _cp_pool

    actor, cache = ctx.actor, ctx.damage_cache
    cl = int(ctx.numbers.get("cl") or 1)
    if cache.get("destruction_deepened"):
        return 1 + cl // 2
    if not any(c.condition_id == DEEPEN_CHOICE for c in actor.conditions.values()):
        return None
    pool = _cp_pool(actor)
    if pool is None or actor.resources.get(pool, 0) < 1:
        return None
    ctx.engine._spend_resource(actor, pool, 1, "system:destruction.deepen_the_calamity")
    cache["destruction_deepened"] = True
    costs = sum(int(amount) for _resource, amount in (getattr(ctx.action, "costs", None) or ()))
    if _has(ctx.engine, actor, "engine") and costs >= 1 and not actor.turn_flags.get("destruction_engine_refund"):
        # Catastrophe Engine: "Once per turn when you spend CP on Deepen the Calamity, reduce the CP cost of one Blast Shape augment applied to
        # that same Destructive Blast by 1" -- the augment's CP is given back.
        actor.turn_flags["destruction_engine_refund"] = True
        ctx.engine._gain_resource(actor, pool, 1, f"passive:{ENGINE_TALENT}")
    if _has(ctx.engine, actor, "cracking") and any(c.condition_id == CRACKING_CHOICE for c in actor.conditions.values()) \
            and not actor.turn_flags.get("destruction_round_cracking_used") and actor.resources.get(pool, 0) >= 2:
        ctx.engine._spend_resource(actor, pool, 2, f"passive:{CRACKING}")
        ctx.engine._remove_condition(actor, CRACKING_CHOICE, ctx.source)
        actor.turn_flags["destruction_round_cracking_used"] = True  # "once per short rest": once per fight
        cache["destruction_cracking"] = True
    return 1 + cl // 2


@hook("technique_used")
def cracking_release(ctx: Any) -> None:
    """Heaven-Cracking Release: "force one creature that failed its saving throw against the release to lose Reactions and have its Speed
    halved until the start of your next turn" (the first one that failed)."""
    if not ctx.damage_cache.get("destruction_cracking"):
        return
    engine = ctx.engine
    failed = next((engine.state.actors.get(e.actor_id) for e in engine.events if e.event_type == "SAVE_ROLLED" and e.source_definition_id == ctx.source
                   and not (e.payload or {}).get("success") and e.actor_id != ctx.actor.entity_id), None)
    if failed is None or not failed.active:
        return
    from .. import typed_executor as te

    te.run_effects(_sub(ctx, failed), [{"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN"},
                                       {"type": "speed", "applies_to": "target", "halved": True, "expires_on": "START_OF_SOURCE_NEXT_TURN"}])


def ruin_trace(ctx: Any, subject: Any, info: dict[str, Any]) -> None:
    """Ruin That Remembers: "When you damage a creature with Destructive Blast, you may spend 2 CP to leave a Ruin Trace on it for 1 minute.
    Once during that duration, when you damage the same creature again with Destructive Blast, consume the Ruin Trace to deal two additional
    Destruction Dice of the same damage type. A creature can bear only one Ruin Trace from you at a time." """
    from .. import typed_executor as te
    from .rider_support import cp_pool as _cp_pool
    from .needle import CHOICE, ask, checkpoint_id
    from ..gate2_runtime_models import DiceSpec

    engine, actor = ctx.engine, ctx.actor
    if not subject.active:
        return
    if te.bears_mark(subject, actor.entity_id, "Ruin Trace"):
        engine._remove_condition(subject, te.mark_condition_id("Ruin Trace", actor.entity_id), f"passive:{RUIN_TRACE}")
        roll = engine.roller.roll(DiceSpec(count=2, sides=int(info["sides"]), modifier=0), actor_id=actor.entity_id, reason=f"DAMAGE:{ctx.source}:ruin_trace")
        engine._record_roll(roll)
        engine._commit_damage(subject, roll.total, str(info["damage_type"]).upper(), ctx.source, actor.entity_id, ctx.intent, reaction_depth=0)
        return
    pool = _cp_pool(actor)
    if pool is None or actor.resources.get(pool, 0) < 2:
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "RUIN_TRACE", actor.entity_id, subject.entity_id), actor, CHOICE + "destruction_ruin_trace",
                 ["trace", "pass"], labels={"trace": "Ruin That Remembers: 2 CP for a Ruin Trace", "pass": "Not now"}, preferred=["trace"],
                 prompt=f"Leave a Ruin Trace on {subject.display_name}?", target_id=subject.entity_id)
    if picked[:1] != ["trace"]:
        return
    engine._spend_resource(actor, pool, 2, f"passive:{RUIN_TRACE}")
    te.run_effects(_sub(ctx, subject), [{"type": "mark", "mark": "Ruin Trace", "applies_to": "target", "duration": {"kind": "one_minute"}}])


def _has(engine: Any, actor: Any, kind: str) -> bool:
    """A lane-10 Destruction talent the actor owns: its compiled "destruction" row (combat/rules/feature_blocks.d/riders_lane10.json)
    read from the fight, so a reloaded fight still knows it and a fight that never compiled the talent cannot see it.

    A fight saved before those rows existed has no row to read, so ownership falls back to that same fight's own
    saved bundle (combat/ext/fight_ownership.py legacy_owns_block), which is where a pre-row save recorded the
    three refinements that compiled no action of their own. Nothing is read from another fight."""
    from . import fight_ownership as own

    return own.owns_block(engine, actor, "destruction", kind)


@hook("compile_block")
def destruction_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    return ([{**row, "block": "destruction", "kind": spec.get("kind"),
              **({"single_collision_die": True} if spec.get("single_collision_die") else {}),
              **({"keeps_compiling": True} if spec.get("keeps_compiling") else {})}] if block == "destruction" else None)


# ------------------------------------------------------------------------------------------------ Calamity-Sovereign Incarnation
SOVEREIGN_STATE = "condition:typed.calamity_sovereign_incarnation"


def _sovereign(actor: Any) -> bool:
    return any(c.condition_id == SOVEREIGN_STATE for c in actor.conditions.values())


@hook("technique_used")
def sovereign_augment_discount(ctx: Any) -> None:
    """Calamity-Sovereign Incarnation: "once on each of your turns, when you use Destructive Blast, reduce the CP cost of one Destruction
    augment by 1, to a minimum of 0 CP" -- 1 CP of a Destruction augment's cost comes back (an augmented release: a costed Blast Shape
    variant, or a Deepened blast)."""
    actor = ctx.actor
    if not _sovereign(actor) or actor.turn_flags.get("destruction_sovereign_discount") or "destructive_blast_damage" not in str((ctx.typed or {}).get("effects")):
        return  # a Destructive Blast release (the base action or a Blast Shape), not the Incarnation itself
    costs = sum(int(amount) for _resource, amount in (getattr(ctx.action, "costs", None) or ()))
    if costs < 1 and not ctx.damage_cache.get("destruction_deepened"):
        return
    from .rider_support import refund

    actor.turn_flags["destruction_sovereign_discount"] = True
    refund(ctx.engine, actor, "Calamity-Sovereign Incarnation: a Destruction augment costs 1 CP less", "passive:destruction")


@hook("event")
def sovereign_returning_calamity(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"when a creature within 30 feet damages you, you may use Returning Calamity without spending additional CP, but only once per round"
    -- its CP comes back, once a round."""
    if event_type != "REACTION_RESOLVED":
        return
    last = engine.events[-1] if engine.events else None
    reactor = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    if last is None or reactor is None or "returning_calamity" not in str(last.source_definition_id) or not _sovereign(reactor):
        return
    key = f"destruction_round_sovereign_return:{engine.state.round_number}"
    if reactor.turn_flags.get(key):
        return
    reactor.turn_flags[key] = True
    spent = next((e for e in reversed(engine.events) if e.event_type == "RESOURCE_SPENT" and e.actor_id == reactor.entity_id
                  and "returning_calamity" in str(e.source_definition_id)), None)
    amount = int((spent.payload or {}).get("amount") or (spent.payload or {}).get("spent") or 0) if spent is not None else 0
    resource = str((spent.payload or {}).get("resource_id") or "") if spent is not None else ""
    if amount > 0 and resource in reactor.resources:
        engine._gain_resource(reactor, resource, amount, "system:destruction.calamity_sovereign")
