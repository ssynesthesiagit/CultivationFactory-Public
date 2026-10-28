"""Berserker riders (rider lane C2, 2026-09-30: "i want everything we can automated").  Rules text: the owner's Sphere Compendium,
"Berserker" (authority/typed_mechanics/rules_text.json).  Batter is combat/ext/gu_berserker.py, Adrenaline's toggle combat/ext/body_berserker.py
(Marauder and Unyielding Advance are now among its talents; their "while active" benefits live here).

  berserker_if_battered_before  effect: run nested effects on a creature that was already Battered before this Batter attack (sampled when
                        the attack sequence starts, before Batter's own hit Batters it), or on any creature while War-God Incarnation is on
                        ("the target counts as already Battered") or while this attack is The Blow Heaven Refused to Receive
                        ("treat the target as already Battered") -- Heavy Swing's Stun, Leg-Smasher's Strength save.
Owned rows (combat/rules/feature_blocks.d/riders_c2.json, block "berserker"; inert without the row or its Adrenaline/state marker):
  marauder              while Adrenaline: Marauder is active, land Speed +5 / +10 / +15 / +20 by CL.
  unyielding_advance    while Adrenaline: Unyielding Advance is active, a creature moving you against your will must succeed on a Strength
                        check against your Berserker Save DC or you do not move.
  war_god               while War-God Incarnation is on: Batter damage +2d10; reducing a creature to 0 HP regains Martial Focus; once per
                        turn after you take damage, move 10 feet without Opportunity Attacks.
  warpath               while Court of the Unbroken Warpath is on: after a melee hit that drops a creature or a critical hit, move 10
                        feet without Opportunity Attacks; once per turn, Batter hitting an already Battered creature regains Martial Focus;
                        Resistance to being forced to move; double damage to unattended objects and temporary Barriers.
  meridian_rending_blow a critical hit with a melee weapon: expend Martial Focus, Constitution save or a chosen arm/leg/wing/tail is disabled.
  sanguine              reducing an eligible creature to 0 HP with a melee or thrown weapon attack: Temporary HP equal to your CL until
                        the start of your next turn.
  beat_down             Battered lasts to the end of your second turn, and this fighter's own Exertion talents' "until the start of
                        your next turn" lasts to the start of your second turn.

The three printed abilities that apply more than one Exertion talent at a time -- Extended Exertion, Heaven-Crushing Exertion
and The Blow Heaven Refused to Receive -- go through combat/ext/exertion_talents.py, the shared registry/chooser/applier.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from . import effect, hook
from ..gate2_runtime_models import Position

BLOCK = "berserker"
BATTERED = "condition:typed.battered"
BATTER_SOURCE = "TAL_BERSERKER_BATTER"
BEFORE = "berserker_battered_before"
FOCUS = "resource:core.martial_focus"
WAR_GOD = "condition:typed.state.war_god_incarnation"
WARPATH = "condition:typed.state.court_of_the_unbroken_warpath"
SANGUINE_HP = "condition:typed.sanguine_temporary_hp"
# Printed attacks that say the target counts as already Battered, whatever it is carrying.
TREATS_AS_BATTERED = ("tianxia.talent.berserker.the_blow_heaven_refused_to_receive",)
HEAVEN_CRUSHING = "TAL_BERSERKER_HEAVEN_CRUSHING_EXERTION"
EXTENDED_EXERTION = "TAL_BERSERKER_EXTENDED_EXERTION"
THE_BLOW = "tianxia.talent.berserker.the_blow_heaven_refused_to_receive"
# "choose three Exertion talents" / "choose up to four Exertion talents" / Extended Exertion's second slot.
EXERTION_CAP = {HEAVEN_CRUSHING: 3, THE_BLOW: 4}
STEP_AFTER_DAMAGE = "berserker_step_after_damage"
# Transient engine scratch naming the attack resolution currently being rolled as this fighter's own
# "Batter: <talent>" variant (see exertion_variant_scope).  A nested stack, not a turn flag: the marker lives only while the
# attack that earned it resolves, so a later unrelated attack and an attack granted inside it both start from "not a variant".
# Never part of fight state, so a saved fight carries nothing to reload.
VARIANT_STACK = "berserker_exertion_variant_stack"
UNYIELDING_CHECK = "berserker_unyielding_athletics"
UNYIELDING_STEP = "berserker_unyielding_step"


def row(engine: Any, actor: Any, kind: str) -> dict[str, Any] | None:
    from .passive_rows import row_of

    return row_of(engine, actor.entity_id, BLOCK, kind)


def _has(actor: Any, condition_id: str) -> bool:
    return any(c.condition_id == condition_id for c in actor.conditions.values())


def _turn(engine: Any) -> int:
    return int(engine.state.round_number) * 1000 + int(engine.state.current_slot_index)


@hook("compile_block")
def berserker_block(block: str, spec: dict[str, Any], row_: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    # The row's own extra keys are carried through (like combat/ext/objects.py's object_damage rows), so one feature_blocks
    # entry can state everything a Berserker rider needs about itself instead of hard-coding it here.
    return [{**row_, "block": BLOCK, "kind": spec.get("kind"), "cl": int(numbers.get("cl") or 1), "pb": int(numbers.get("pb") or 2),
             **{name: value for name, value in spec.items() if name not in {"block", "why", "kind"}},
             **({"choice_owner": True} if spec.get("kind") == "sanguine" else {}),
             **({"keeps_compiling": True} if spec.get("keeps_compiling") else {})}]


# ------------------------------------------------------------------------------------------------ already Battered
@hook("attack_sequence_start")
def battered_before(ctx: Any) -> None:
    """Sample which creatures are Battered as a Batter attack starts (Batter's own hit Batters its target).

    The three printed attacks that apply their own Exertion set are asked here too -- "before rolling, choose three /
    up to four Exertion talents you know" -- and the answer is held on the fighter's turn flags for this attack's hit.
    The menu names the creature it will be applied to, because the affected creature is known here.
    """
    from . import exertion_talents

    source = str(ctx.typed.get("source") or "")
    if source != BATTER_SOURCE:
        cap = EXERTION_CAP.get(source)
        if cap is None:
            return
        if not exertion_talents.owned(ctx.engine, ctx.actor.entity_id):
            # No post-roll Exertion talent to put in a menu, so there is no menu.  The two talents that change the
            # attack roll are used through their own "Batter + <talent>" attack variant (combat/ext/pre_roll_attack.py),
            # so nothing here needs a by-hand instruction.
            return
        exertion_talents.ask(
            ctx.engine, ctx.actor, ctx.intent, cap=cap, purpose=source, feature_id=source,
            name=ctx.action.display_name, target=ctx.target, include_standing=False,
            prompt=f"{ctx.action.display_name}: before you roll, choose up to {cap} Exertion talents you know to apply on a hit.")
        return
    marked = sorted(a.entity_id for a in ctx.engine.state.actors.values() if _has(a, BATTERED))
    ctx.actor.turn_flags[BEFORE] = f"{ctx.engine.state.event_sequence}|{','.join(marked)}"


def was_battered(ctx: Any, subject: Any) -> bool:
    if _has(ctx.actor, WAR_GOD):
        return True  # War-God Incarnation: "the target counts as already Battered for that attack's Exertion"
    if str(ctx.typed.get("source") or "") in TREATS_AS_BATTERED:
        return True  # The Blow Heaven Refused to Receive: "treat the target as already Battered"
    _, _, ids = str(ctx.actor.turn_flags.get(BEFORE) or "").partition("|")
    return subject.entity_id in set(ids.split(",")) - {""}


@effect("berserker_if_battered_before")
def if_battered_before(ctx: Any, eff: dict[str, Any]) -> None:
    from dataclasses import replace

    from .. import typed_executor as te

    for subject in ctx.targets or ([ctx.target] if ctx.target else []):
        if subject is not None and subject.active and was_battered(ctx, subject):
            te.run_effects(replace(ctx, targets=[subject], target=subject), list(eff.get("effects") or []))


# ------------------------------------------------------------------------------------------------ Court of the Unbroken Warpath / War-God
@hook("condition_choice_owner")
def war_god_choice_owner(engine: Any, actor: Any, condition: Any) -> bool | None:
    """Enroll the active owner's damage-triggered step in the service's enemy-turn choice preview.

    Read the owned row and existing state marker, including saved bundles. The service keeps AI owners automatic;
    no other fighter/condition owns a choice here, and no persisted field or compiled row is changed.
    """
    if condition.condition_id == WAR_GOD and row(engine, actor, "war_god") is not None:
        return True
    return None


@hook("forced_movement_reduction")
def warpath_holds_ground(ctx: Any, subject: Any) -> int | None:
    """"gain Resistance to forced movement\": nothing moves this fighter while the Court is on.

    Same shape as Unyielding Advance's Strength check below: ``ctx.actor`` is whatever is trying to move ``subject``.
    """
    engine = ctx.engine
    if not _has(subject, WARPATH):
        return None
    feet = 10000  # more feet than any grid; the same "you do not move" answer Unyielding Advance gives
    from . import note

    note(engine, "TAL_BERSERKER_COURT_OF_THE_UNBROKEN_WARPATH", subject,
         f"Court of the Unbroken Warpath: {subject.display_name} cannot be forced to move.")
    return feet


@hook("object_packets")
def warpath_doubles_object_damage(engine: Any, actor: Any, obj: Any, packets: Any, source: str) -> dict[str, Any] | None:
    """"deal double damage to unattended objects and temporary Barriers" while the Court is on.

    Doubling the packets (rather than the total) is deliberate: object_rules.work_out adds a packet list up before the
    Damage Threshold is compared, so an unattended object or a Barrier inside a Court's reach really takes twice the
    damage the attack rolled.
    """
    from .. import object_rules

    if not _has(actor, WARPATH) or not packets or not any(int(amount) > 0 for amount, _kind in packets):
        return None
    if not (getattr(obj, "unattended", False) or object_rules.has_tag(obj, "barrier")):
        return None
    from . import note

    note(engine, "TAL_BERSERKER_COURT_OF_THE_UNBROKEN_WARPATH", actor,
         f"Court of the Unbroken Warpath: this hit deals double damage to the unattended {object_rules.label(obj).lower()}.")
    return {"object": obj, "packets": [*packets, *packets]}


@hook("event")
def war_god_step_after_damage(engine: Any, event_type: str, kwargs: Any) -> None:
    """"once per turn after taking damage, move 10 feet without provoking Opportunity Attacks".

    Read off the fight's own damage events, so it answers an enemy attack, a native (non-typed) packet and an
    environmental one alike -- ``damage_dealt`` only ever reports damage this same typed action dealt, and its actor is
    the dealer, not the injured creature.  The step belongs to the creature that was hurt, which is the one holding
    War-God Incarnation; the turn flag is that creature's own, so the promise lasts this turn and no longer.
    """
    if event_type != "DAMAGE_COMMITTED":
        return
    payload = kwargs.get("payload") or {}
    if int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0) <= 0:
        return
    intent = getattr(engine, "_active_intent", None)
    if intent is None:
        return  # nothing is resolving that could carry a movement choice; the promise is this turn's, not stored
    from . import note
    from .. import typed_executor as te

    hurting = engine.action_catalog.get(str(kwargs.get("source_definition_id") or ""))
    for entity_id in kwargs.get("target_ids") or ():
        owner = engine.state.actors.get(entity_id)
        if owner is None or not owner.active or not _has(owner, WAR_GOD):
            continue
        if owner.turn_flags.get(STEP_AFTER_DAMAGE) == _turn(engine):
            continue
        owner.turn_flags[STEP_AFTER_DAMAGE] = _turn(engine)
        note(engine, "TAL_BERSERKER_WAR_GOD_INCARNATION", owner,
             f"War-God Incarnation: {owner.display_name} took damage, so it may move 10 feet without Opportunity Attacks.")
        te.run_effects(te.Context(engine, owner, hurting or _any_action(engine, owner), intent,
                                  {"numbers": {}}, [owner], owner, {}),
                       [{"type": "rider_step", "distance_ft": 10, "no_oa": True, "label": "War-God Incarnation"}])


# ------------------------------------------------------------------------------------------------ Beat Down
# "Battered lasts until the end of your second turn" (the ``batter`` effect's own printed length) and "your Exertion
# effects that normally last until the start of your next turn instead last until the start of your second turn after
# the attack".  The second half is the general ``effect_turns`` hook, so it reaches every nested row of an Exertion
# talent's effects (Heavy Swing's denied Reactions and Stun, Leg-Smasher's halved Speed, Bell-Ringer, Bone-Breaker) and
# the fighter's own compiled "Batter: <talent>" variants alike, not only the three talents with custom code.  Which rows
# those are is :func:`_exertion_row`'s question, so an ability's OWN effects keep the length it printed.
def _exertion_row(ctx: Any, effect: Any) -> bool:
    """Whether THIS effect row is one of the actor's own Exertion talents' rows, so its printed "until the start of your
    next turn" is one of "your Exertion effects".

    Beat Down lengthens Exertion TALENTS, not everything the attack happens to do.  The Blow Heaven Refused to Receive
    prints its own "cannot take Reactions until the start of your next turn" on itself, not on any Exertion talent, so
    that keeps the printed length even though the blow applies three or four talents beside it.

    Two paths carry that provenance, and both are the compiler's own stamp rather than an ability id:

      the applied rows   combat/ext/exertion_talents.py copies a talent's rows out of this fighter's own compiled
                         bundle and carries ``source_modifier`` (the talent id) down over the copies, so the stamp
                         survives the standing toggle, Extended Exertion's paid second slot and the pre-roll sets of
                         Heaven-Crushing Exertion and The Blow alike.
      the variant attack  the fighter's own "Batter: <talent>" action runs that talent's rows straight out of the
                         catalog, and :func:`exertion_variant_scope` marks that one resolution while it runs.  Every row on
                         such an attack's hit IS that talent's own row (combat/ext/docket_maneuvers.py moves nothing
                         else onto it), so the marker answers for the whole of them -- and only for them: a later attack
                         this turn, or one granted inside this one, is its own resolution and keeps its printed lengths.

    A fighter who does not own the talent that wrote the row is not lengthening it, either.
    """
    from . import exertion_talents

    row = effect if isinstance(effect, dict) else {}
    key = exertion_talents.key_for(str(row.get("source_modifier") or ""))
    if key:
        return exertion_talents.owns(ctx.engine, ctx.actor.entity_id, key)
    if not _resolving_own_variant(ctx):
        return False
    # On a variant the target-side rows are the talent's; the attacker's own rows are not.
    return str(row.get("applies_to") or "target") == "target"


@hook("effect_resolution_scope")
def exertion_variant_scope(ctx: Any, effect: dict[str, Any]) -> Any:
    """Mark exactly the resolution in which this fighter's own "Batter: <talent>" attack runs, for :func:`_exertion_row`.

    The compiled attack row cannot be changed while a fight runs -- editing it would rewrite the character's bundle for
    the rest of the session -- so the provenance is carried beside the fight, by a stack this scope pushes and pops.

    A stack rather than a turn flag, which is what the printed rule asks for: Beat Down lengthens "your Exertion effects"
    of THAT attack, so the marker may only answer while that attack resolves.  Pushed by the ``effect_resolution_scope``
    around every attack block and popped by its ExitStack, so it also restores the enclosing value when an attack is
    granted or triggered inside another one (a nested attack resolves as itself, not as its host's variant).  The engine
    clears a turn flag only at this fighter's next turn, which let the marker outlive its attack and reach a later attack.

    Transient engine scratch, never fight state, so a saved fight carries nothing to reload and an old save is unaffected.
    Inert unless this fighter owns Beat Down, the only reader, so no other character and no other sphere changes.
    """
    from . import exertion_talents

    if str(effect.get("type") or "") != "attack" or row(ctx.engine, ctx.actor, "beat_down") is None:
        return None
    modifier = str((((ctx.typed or {}).get("modifier") or {}) or {}).get("id") or "")
    key = exertion_talents.key_for(modifier)
    mine = bool(key) and exertion_talents.owns(ctx.engine, ctx.actor.entity_id, key)
    return _variant_resolution(ctx.engine, ctx.actor.entity_id, mine)


@contextmanager
def _variant_resolution(engine: Any, actor_id: str, mine: bool) -> Any:
    """Push this resolution's answer and put the enclosing one back on the way out.

    Every attack this fighter resolves pushes a frame, not only the variants: returning nothing for an ordinary attack
    would leave an enclosing variant's marker standing through it, which is the nested leak a turn-wide flag could not
    avoid.  The frame is popped whatever happens, so a pause, a refusal or an error restores the host's answer.
    """
    stack = engine.__dict__.setdefault(VARIANT_STACK, [])
    stack.append(actor_id if mine else "")
    try:
        yield
    finally:
        stack.pop()
        if not stack:
            engine.__dict__.pop(VARIANT_STACK, None)


def _resolving_own_variant(ctx: Any) -> bool:
    """Whether the row being timed was written while THIS fighter's own Exertion variant attack was resolving.

    Only the innermost attack frame counts: it is the attack currently resolving, not any attack this fighter may have
    resolved earlier in the same breath.  An ordinary or granted attack of this fighter pushes its own empty frame, and
    another fighter's attack pushes its own, so neither answers for this fighter's talents.
    """
    stack = ctx.engine.__dict__.get(VARIANT_STACK) or ()
    return bool(stack) and stack[-1] == ctx.actor.entity_id


@hook("effect_turns")
def beat_down_exertion_turns(ctx: Any, effect: dict[str, Any]) -> int | None:
    """How many of the applier's turns an Exertion talent's own lasting effects run for, while Beat Down is on.  The
    replacement expiry itself is :func:`exertion_expiry`, the one place this fighter's longer Exertion lifetime is
    written down."""
    if not _exertion_row(ctx, effect) or exertion_expiry(ctx.engine, ctx.actor, "START_OF_SOURCE_NEXT_TURN") is None:
        return None
    return 2


def exertion_expiry(engine: Any, actor: Any, printed: str) -> str | None:
    """"Your Exertion effects that normally last until the start of your next turn instead last until the start of your
    second turn after the attack": the replacement expiry name for this fighter's own Exertion talents, or None."""
    if row(engine, actor, "beat_down") is None or printed != "START_OF_SOURCE_NEXT_TURN":
        return None
    from .effect_durations import token

    return token("start", actor.entity_id, int(actor.turns_started) + 2)


@hook("condition_turns")
def beat_down_battered_turns(engine: Any, actor: Any, name: str) -> int | None:
    """"Battered lasts until the end of your second turn": read by the ``batter`` effect that places it (combat/ext/
    docket_maneuvers.py), so no other fighter's Battered and no other condition changes."""
    if str(name) == "battered" and row(engine, actor, "beat_down") is not None:
        return 2
    return None


# ------------------------------------------------------------------------------------------------ more than one Exertion talent
@hook("compile_actions")
def extended_exertion(info: dict[str, Any]) -> list[Any] | None:
    """"Apply two Exertion talents to one Batter attack by: spending a Bonus Action; or expending Martial Focus."

    The printed text prices the ability two ways and both are the whole cost: one button spends a Bonus Action and the
    other spends Martial Focus, and neither spends an Action (the Action is the Batter's).  Either opens the printed menu
    of this fighter's own Exertion talents and holds the second one for the rest of this turn, so the next damaging
    Batter applies it together with the standing toggle's choice.
    """
    from . import exertion_talents
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    if EXTENDED_EXERTION not in (info.get("owned_ids") or ()) or not exertion_talents.owned_probe(info):
        return None
    out = []
    for suffix, label, economy, costs in (("bonus", "Bonus Action", EconomyKind.BONUS_ACTION, ()),
                                          ("focus", "Martial Focus", EconomyKind.NONE, ((FOCUS, 1),))):
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.extended_exertion.{suffix}",
            display_name=f"Extended Exertion: a second Exertion talent ({label})", owner_id=info["actor_id"],
            economy=economy, resolution_kind="TYPED",
            target_kind="SELF", costs=costs,
            parameters={"setting_only": True, "typed": {"effects": [{"type": "berserker_arm_exertion", "purpose": BATTER_SOURCE}],
                                      "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []},
                        "expected_damage": 0, "player_only": True}))
    return out


@effect("berserker_arm_exertion")
def arm_exertion(ctx: Any, eff: dict[str, Any]) -> None:
    """Hold a second Exertion talent for this turn's next Batter.  Heaven-Crushing Exertion's printed "cannot be combined
    with Extended Exertion" is enforced by candidate_allowed on this button and on that ability."""
    from . import exertion_talents

    picked = exertion_talents.ask(
        ctx.engine, ctx.actor, ctx.intent, cap=1, purpose=f"extended:{eff.get('purpose') or BATTER_SOURCE}",
        feature_id=EXTENDED_EXERTION, name="Extended Exertion",
        prompt="Extended Exertion: choose the second Exertion talent to apply to your next Batter this turn "
               "(your standing Exertion choice applies to that attack too).")
    if not picked:
        ctx.rider("Extended Exertion: no second Exertion talent chosen; the next Batter applies your standing choice only.")
        return
    ctx.rider(f"Extended Exertion: {exertion_talents.label(picked[0])} will apply to your next Batter this turn, and only to that one.")


@hook("candidate_allowed")
def extended_exertion_not_with_heaven_crushing(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """"Heaven-Crushing Exertion cannot be combined with Extended Exertion": one of the two is refused for this turn once
    the other is used."""
    from . import exertion_talents

    source = str(((getattr(action, "parameters", None) or {}).get("typed") or {}).get("source") or "")
    if str(getattr(action, "source_definition_id", "")).endswith(".extended_exertion.bonus") or \
            str(getattr(action, "source_definition_id", "")).endswith(".extended_exertion.focus"):
        return False if exertion_talents.pick_up(engine, actor, HEAVEN_CRUSHING) else None
    if source == HEAVEN_CRUSHING:
        return False if exertion_talents.pick_up(engine, actor, f"extended:{BATTER_SOURCE}") else None
    return None


@hook("technique_used")
def own_exertions_on_own_attack(ctx: Any) -> None:
    """Heaven-Crushing Exertion and The Blow Heaven Refused to Receive: "apply all three / up to four Exertion talents on a
    hit".  Their choices were taken before the roll (attack_sequence_start) and are held on this fighter's turn flags.

    Applied once the action's own effects have all run, which is what "on a hit" means: after_hit fires while the hit's
    damage rows are still pending, and both of these abilities' damage is a deferred on-hit row, so a talent applied
    there would never see the hit it belongs to.
    """
    from . import exertion_talents

    source = str(ctx.typed.get("source") or "")
    if source not in EXERTION_CAP:
        return
    target = ctx.target or next((subject for subject in (ctx.targets or ()) if subject is not None and subject.active), None)
    if target is None or not exertion_talents.dealt_damage(ctx, target):
        return
    picked = exertion_talents.pick_up(ctx.engine, ctx.actor, source)
    if not picked:
        return
    exertion_talents.apply(ctx, target, picked, more_if_battered=was_battered(ctx, target))
    exertion_talents.pick_down(ctx.engine, ctx.actor, source)


@hook("resistance_ignored")
def the_blow_ignores_resistance(engine: Any, kind: str, typed: Any, source_actor_id: str | None, target: Any) -> bool | None:
    """The Blow Heaven Refused to Receive: "ignore Resistance to the attack's damage"."""
    if str((typed or {}).get("source") or "") == THE_BLOW and engine.state.actors.get(str(source_actor_id or "")):
        return True
    return None


# ------------------------------------------------------------------------------------------------ Adrenaline talents
ATHLETICS = "athletics"


def _is_athletics(ability: Any, skill: Any) -> bool:
    """"Strength (Athletics) check": the printed check names the skill, so an unspecified Strength check is a different
    check and never qualifies."""
    return str(ability or "").upper() == "STR" and str(skill or "").strip().lower() == ATHLETICS


@hook("ability_check_mode")
def unyielding_athletics_advantage(engine: Any, actor: Any, ability: str, skill: Any, against: Any) -> str | None:
    """"when you take damage, gain Advantage on your next Strength (Athletics) check before the start of your next turn".

    The turn flag is set by the same module's damage_taken hook and spent by its ``roll_context_end`` hook, so exactly one
    qualifying check is rolled with it; it is the fighter's own turn flag, so it is cleared with the rest of them at the
    start of their next turn and never outlives the printed "before the start of your next turn".
    """
    if row(engine, actor, "unyielding_advance") is None or not _has(actor, "condition:typed.body_adrenaline_unyielding_advance"):
        return None
    if not _is_athletics(ability, skill):
        return None
    return "ADVANTAGE" if actor.turn_flags.get(UNYIELDING_CHECK) else None


@hook("roll_context_end")
def unyielding_advantage_spent(engine: Any, context: Any) -> None:
    """Spend that Advantage on the first Strength (Athletics) check this fighter actually rolls (the roll scope names the
    ability and the skill); every later one this turn is ordinary."""
    if str((context or {}).get("kind") or "") != "check" or not _is_athletics(context.get("ability"), context.get("skill")):
        return
    actor = engine.state.actors.get(str(context.get("actor_id") or ""))
    if actor is None or not actor.turn_flags.pop(UNYIELDING_CHECK, None):
        return
    from . import note

    note(engine, "TAL_BERSERKER_UNYIELDING_ADVANCE", actor,
         f"Unyielding Advance: that Strength (Athletics) check used the Advantage; the next one is an ordinary check.")


@hook("event")
def unyielding_taken_damage(engine: Any, event_type: str, kwargs: Any) -> None:
    """Arm that Advantage the moment this fighter takes damage."""
    if event_type != "DAMAGE_COMMITTED":
        return
    payload = kwargs.get("payload") or {}
    if int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0) <= 0:
        return
    for entity_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(entity_id)
        if target is None or row(engine, target, "unyielding_advance") is None:
            continue
        if _has(target, "condition:typed.body_adrenaline_unyielding_advance"):
            target.turn_flags[UNYIELDING_CHECK] = True
            from . import note

            note(engine, "TAL_BERSERKER_UNYIELDING_ADVANCE", target,
                 f"Unyielding Advance: {target.display_name} has Advantage on its next Strength (Athletics) check this turn.")


@hook("event")
def unyielding_steps_toward_a_closer_foe(engine: Any, event_type: str, kwargs: Any) -> None:
    """"when a hostile creature enters your reach, move 5 feet toward it without provoking opportunity attacks".

    Entering is read off the committed path against this fighter's own reach: a creature that stood outside it, walked
    through one of the squares inside it (its path counts, so a creature that came in and then walked on still entered)
    and is now inside it.  Once per entering creature and turn, so the step this module grants cannot ask for itself.
    The step is "toward it", so rider_step offers only squares that close the distance to that creature.
    """
    if event_type != "MOVEMENT_COMMITTED" or engine.__dict__.get("unyielding_stepping"):
        return
    mover = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    payload = kwargs.get("payload") or {}
    path = [Position(x=int(cell["x"]), y=int(cell["y"]), z=int(cell.get("z") or 0)) for cell in payload.get("path") or []
            if isinstance(cell, dict)]
    if mover is None or not path or mover.team_id is None or not mover.active:
        return
    start = path[0]
    from . import reach_bonus

    engine.__dict__["unyielding_stepping"] = True
    try:
        for owner in sorted(engine.state.actors.values(), key=lambda row: row.entity_id):
            if not owner.active or owner is mover or owner.team_id == mover.team_id:
                continue
            if row(engine, owner, "unyielding_advance") is None or not _has(owner, "condition:typed.body_adrenaline_unyielding_advance"):
                continue
            reach_ft = reach_bonus.melee_reach(engine, owner)
            if engine._distance_actor_to_cell(owner, start) <= reach_ft:
                continue  # it was already inside: it never entered
            if not any(engine._distance_actor_to_cell(owner, cell) <= reach_ft for cell in path):
                continue  # its path never came inside this fighter's reach
            flag = f"{UNYIELDING_STEP}:{mover.entity_id}"
            if owner.turn_flags.get(flag) == _turn(engine):
                continue
            owner.turn_flags[flag] = _turn(engine)
            from .. import typed_executor as te

            te.run_effects(te.Context(engine, owner, _any_action(engine, owner), getattr(engine, "_active_intent", None),
                                      {"numbers": {}}, [mover], mover, {}),
                           [{"type": "rider_step", "distance_ft": 5, "no_oa": True, "toward_id": mover.entity_id,
                             "label": "Unyielding Advance"}])
    finally:
        engine.__dict__["unyielding_stepping"] = False


def _any_action(engine: Any, actor: Any) -> Any:
    """Any catalog action of this fighter: the granted step needs an action only to name itself in the log."""
    return next((row for row in engine.action_catalog.values() if row.owner_id == actor.entity_id), None)


@hook("speed")
def marauder(engine: Any, actor: Any) -> int | None:
    owned = row(engine, actor, "marauder")
    if owned is None or not _has(actor, "condition:typed.body_adrenaline_marauder"):
        return None
    cl = int(owned.get("cl") or 1)
    return 20 if cl >= 17 else 15 if cl >= 11 else 10 if cl >= 5 else 5


@hook("forced_movement_reduction")
def unyielding(ctx: Any, subject: Any) -> int | None:
    """"cannot be moved unwillingly unless the source succeeds on a Strength check against your Berserker Save DC\"."""
    engine, source = ctx.engine, ctx.actor
    if source is subject or row(engine, subject, "unyielding_advance") is None or not _has(subject, "condition:typed.body_adrenaline_unyielding_advance"):
        return None
    from ..ability_checks import ability_modifier
    from .needle import save_dc

    dc = save_dc(engine, subject)
    roll = engine.roll_check(
        modifier=int(ability_modifier(source, 'STR')),
        actor_id=source.entity_id,
        reason='CHECK:TAL_BERSERKER_UNYIELDING_ADVANCE',
        ability='STR',
    )
    engine._record_roll(roll)
    success = int(roll.total) >= dc
    engine._append_event("CHECK_ROLLED", "TAL_BERSERKER_UNYIELDING_ADVANCE", actor_id=source.entity_id, target_ids=(subject.entity_id,),
                         payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": success, "check": "Strength"})
    return None if success else 10000


# ------------------------------------------------------------------------------------------------ War-God, the Warpath, kills and crits
def _dropped(target: Any) -> bool:
    return not target.active or int(target.current_hp or 0) <= 0


def _melee_weapon(ctx: Any, kind: str) -> bool:
    from .passive_rows import melee_or_thrown

    return kind in ("weapon", "unarmed") and melee_or_thrown(ctx)


def _regain_focus(engine: Any, actor: Any, why: str, source: str) -> None:
    if FOCUS in actor.resources and int(actor.resources.get(FOCUS) or 0) < 1:
        engine._gain_resource(actor, FOCUS, 1, source)
        from . import note

        note(engine, source, actor, f"{actor.display_name} regains Martial Focus ({why}).")


@hook("after_hit")
def war_god_and_warpath(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    from .. import typed_executor as te

    batter = ctx.typed.get("source") == BATTER_SOURCE
    if batter and target.active and row(engine, actor, "war_god") is not None and _has(actor, WAR_GOD):
        te.run_effects(te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {}),
                       [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 2, "sides": 10},
                         "damage_types": [str((ctx.typed.get("weapon") or {}).get("damage_type") or "bludgeoning").lower()],
                         "evidence": "War-God Incarnation: Batter damage gains +2d10"}])
    dropped = _dropped(target)
    if dropped and row(engine, actor, "war_god") is not None and _has(actor, WAR_GOD):
        _regain_focus(engine, actor, f"War-God Incarnation: {target.display_name} fell", "TAL_BERSERKER_WAR_GOD_INCARNATION")
    if row(engine, actor, "warpath") is None or not _has(actor, WARPATH):
        return
    if batter and was_battered(ctx, target) and actor.turn_flags.get("berserker_round_warpath_focus") != _turn(engine):
        actor.turn_flags["berserker_round_warpath_focus"] = _turn(engine)
        _regain_focus(engine, actor, "Court of the Unbroken Warpath: Batter hit a Battered creature", "TAL_BERSERKER_COURT_OF_THE_UNBROKEN_WARPATH")
    critical = int(((getattr(ctx, "attack_result", None) or {}).get("natural_result")) or 0) == 20
    if (dropped or critical) and _melee_weapon(ctx, kind) and actor.active:
        te.run_effects(te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {}),
                       [{"type": "rider_step", "distance_ft": 10, "no_oa": True, "label": "Court of the Unbroken Warpath"}])


@hook("after_hit")
def sanguine(ctx: Any, target: Any, kind: str) -> None:
    """Sanguine Invigoration requires printed CR, not Cultivation Level. This
    runtime has no authoritative target CR; require explicit GM confirmation.
    AI/no-answer unknown eligibility declines, never silently grants a benefit.
    """
    engine, actor = ctx.engine, ctx.actor
    owned = row(engine, actor, "sanguine")
    if owned is None or not _dropped(target) or kind != "weapon" or not ctx.typed.get("weapon") or not _melee_weapon(ctx, kind):
        return
    cl = int(owned.get("cl") or 1)
    threshold = str(cl // 2) if cl >= 2 else "1/2"
    from .needle import ask, checkpoint_id
    from .choice_prompt import action_context

    if not ask(engine, ctx.intent, checkpoint_id(engine, "Sanguine Invigoration", actor.entity_id, target.entity_id), actor,
               "choice:needle.berserker_sanguine_eligibility", ["eligible"], allow_decline=True, automatic=False, default="decline",
               name="Sanguine Invigoration", target_id=target.entity_id,
               labels={"eligible": f"GM confirms CR at least {threshold}: gain {cl} Temporary HP until your next turn"},
               prompt_context=action_context(engine, actor, ctx.source, target),
               prompt=f"Sanguine Invigoration: {actor.display_name}'s {ctx.action.display_name} reduced {target.display_name} to 0 HP. "
                      f"Its Challenge Rating (CR) is not recorded. The GM must confirm CR at least {threshold}; cultivation level is not CR. "
                      f"If confirmed, gain {cl} Temporary HP until the start of your next turn, with no action or resource cost. Otherwise decline."):
        from . import note

        note(engine, str(owned.get("feature_id")), actor,
             f"Sanguine Invigoration: no Temporary HP granted for {target.display_name}; the GM has not confirmed CR at least {threshold}.", (target,))
        return
    from .. import typed_executor as te

    before = int(actor.temporary_hp)
    te.run_effects(te.Context(engine, actor, ctx.action, ctx.intent, {**ctx.typed, "numbers": {**ctx.numbers, "cl": cl}}, [actor], actor, {}),
                   [{"type": "temp_hp", "applies_to": "self", "formula": "cl", "duration": "until_start_of_next_turn",
                     "evidence": "Sanguine Invigoration: Temporary HP equal to your Cultivation Level until the start of your next turn"}])
    if int(actor.temporary_hp) > before:
        from .effect_durations import token

        source = str(owned.get("feature_id"))
        engine._remove_condition(actor, SANGUINE_HP, source)
        engine._apply_condition(actor, SANGUINE_HP, source, actor.entity_id,
                                expires_on=token("start", actor.entity_id, int(actor.turns_started) + 1),
                                data={"amount": cl, "label": f"Sanguine Invigoration: up to {cl} Temporary HP; remaining points vanish at the start of your next turn"})


@hook("event")
def sanguine_hp_replaced(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """A larger replacement pool has its own duration; never clear it with ours."""
    payload = kwargs.get("payload") or {}
    if event_type != "TEMP_HP_GRANTED" or int(payload.get("after") or 0) <= int(payload.get("before") or 0):
        return
    for tid in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(tid)
        if actor is not None:
            for marker in list(actor.conditions.values()):
                if marker.condition_id == SANGUINE_HP:
                    engine._remove_condition(actor, SANGUINE_HP, marker.source_definition_id)


@hook("effect_expiring")
def sanguine_hp_expires(engine: Any, holder: Any, condition: Any) -> None:
    """Expire only the remaining points from this stored, source-specific pool."""
    if getattr(condition, "condition_id", None) != SANGUINE_HP or not 0 < holder.temporary_hp <= int(condition.data.get("amount") or 0):
        return
    before, holder.temporary_hp = int(holder.temporary_hp), 0
    engine._append_event("TEMP_HP_GRANTED", condition.source_definition_id, actor_id=holder.entity_id, target_ids=(holder.entity_id,),
                         payload={"offered": 0, "before": before, "after": 0})
    from . import note

    note(engine, condition.source_definition_id, holder, f"Sanguine Invigoration: {holder.display_name}'s remaining Temporary HP expire.")


@hook("attack_result")
def meridian_rending(ctx: Any, target: Any, hit: bool, critical: bool) -> None:
    """Meridian-Rending Blow: "You score a critical hit with a melee weapon. Cost: Expend Martial Focus"."""
    engine, actor = ctx.engine, ctx.actor
    owned = row(engine, actor, "meridian_rending_blow")
    if owned is None or not hit or not critical or not target.active or int(actor.resources.get(FOCUS) or 0) < 1:
        return
    attack = getattr(ctx, "attack_effect", None) or {}
    if not ctx.typed.get("weapon") or "ranged" in str(attack.get("attack_kind") or "") or ctx.typed.get("range_ft"):
        return
    from . import note
    from .needle import ask, checkpoint_id

    # Only the two structures the table can enforce are on the menu, because only those two are worked out below (a
    # disabled arm's attacks and two-handed weapons, a disabled leg's Speed and Dexterity saves).  A wing and a tail
    # depend on abilities this table does not track -- "lose ordinary flight dependent on that wing", "lose attacks or
    # movement features primarily dependent on it" -- and a creature without recognizable anatomy is immune outright,
    # so all three stay the GM's and are said so here and in the printed record, rather than being offered as a choice
    # that spends Martial Focus and records nothing.
    structures = {"arm": "An arm: Disadvantage on attacks made with it, and it cannot use a two-handed weapon",
                  "leg": "A leg: Speed -10 feet and Disadvantage on Dexterity saving throws"}
    manual = ("Meridian-Rending Blow, by hand: a wing that loses ordinary flight dependent on it; a tail or similar "
              "appendage that loses the attacks and movement primarily dependent on it; and a creature without "
              "recognizable anatomy, which is immune to this blow altogether.")
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "Meridian-Rending Blow", actor.entity_id, target.entity_id), actor,
                 "choice:needle.berserker_meridian_rending", list(structures), allow_decline=True, default="first",
                 labels=structures, name="Meridian-Rending Blow", target_id=target.entity_id,
                 prompt=f"Meridian-Rending Blow: {actor.display_name}'s {ctx.action.display_name} critically hit {target.display_name}. "
                        "Spend your Martial Focus readiness point (you cannot spend it again until you regain it), with no extra action; it makes a "
                        f"Constitution save or the chosen structure is disabled for the rest of the fight. {manual}")
    note(engine, str(owned.get("feature_id")), actor, manual, (target,))
    if not picked:
        return
    source = str(owned.get("feature_id"))
    engine._spend_resource(actor, FOCUS, 1, f"passive:{source}")
    rule = {"arm": ({"attacks_have": "DISADVANTAGE"}, 0, structures["arm"]),
            "leg": ({"save_mode": {"DEX": "DISADVANTAGE"}}, -10, structures["leg"])}[picked[0]]
    from .. import typed_executor as te

    te.run_effects(te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {}),
                   [{"type": "save", "ability": "con", "dc": "technique_save_dc", "applies_to": "target",
                     "on_fail": [{"type": "ongoing", "condition": f"rended_{picked[0]}", "applies_to": "target", "rule": rule[0], "speed_delta": rule[1],
                                  "turn_start_effects": [], "duration": "instant", "expires_on": "UNTIL_REMOVED", "evidence": rule[2]}],
                     "evidence": "Meridian-Rending Blow: Constitution saving throw"}])
