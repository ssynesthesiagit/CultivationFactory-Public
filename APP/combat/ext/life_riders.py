"""Life lines that were left to the GM (rider lane 9, 2026-09-29; owner: "i want everything we can automated").  Sphere Compendium,
Life (owner's text: authority/typed_mechanics/rules_text.json); nothing here is invented.  The Pulse abilities themselves are typed
(Mend the Pulse, Borrowed Breath, Purify the Pulse and their augments compile as variants: combat/factory_compiler.py); these are the
effects the augments' modifiers now carry (authority/typed_mechanics/reviewed_final.d/riders_lane9.json).

  life_take_affliction  Empathic Transfer: "you gain the condition or disease you removed as though you had been the original target".
  life_contagion        Contagion Reversal: "cast the rejected affliction into another living creature" within Purify's range (touch):
                        Constitution save, failure -> that condition for 1 round.
  life_purify_extra     Mind-Cooling Pulse (Charmed, Frightened, Stunned, Unconscious), Meridian Unbinding (a Speed reduction, Prone
                        held down, a Reaction lock from restraint), Greater Purification (one level of Exhaustion, once per creature
                        per long rest -- a fight is inside one).
  life_physician_step   Physician's Step: the target "may immediately use its Reaction": stand from Prone, or escape a grapple with
                        Advantage (Athletics or Acrobatics).
  life_fount_store      Fount of Life: "store the healing instead of applying it": the rolled healing goes into
                        ``resource:named.fount_of_life`` (10 x CL, 20 x CL with Hundred-Medicine Core; empty when a fight begins);
                        "Release Fount of Life" (an Action, touch) heals up to what the creature is missing from it.
  life_latent           Latent Healing (Mend the Pulse): the healing is carried as a ``latent_healing`` condition; when the carrier
                        is injured it may use its Reaction to have it (it is asked; the AI does when hurt).
  life_thread           Revitalizing Thread: Concentration up to 1 minute; the target regains 1/2/3/4 HP (Mortal/Foundation/Core
                        Formation/Nascent Soul) at the start of each of its turns; at 0 HP it is stabilized instead.
  life_more_targets     Pulse Array Treatment (every willing Pulse Seal bearer within 30/60/120 feet) and Shared Infirmary Hand (1 more
                        creature you can touch; 2 at Foundation; PB at Core Formation): the same Pulse ability on each of them.
  life_adrenaline       Adrenaline Surge: the ally "may immediately use its Reaction": one weapon attack, move up to its Speed,
                        escape a grapple, or stand up (it chooses; drawing a weapon is not on the table).
  life_read_pulse       Read the Pulse: what the reader learns is logged; "Read the Pulse (Pulse Seal)" reaches a creature bearing your
                        Pulse Seal at any distance (not for Body Refiners) and gives its direction and distance.
Vital Court Field: once per round, when a chosen creature regains HP from your Life ability inside the aura, another chosen creature there
gains PB Temporary HP.
Life-Seal Reach: the remote-range variant is withheld from a Body Refiner unless the GM recorded that permission on the character
sheet (``path_and_subpath.life_seal_reach_permission``, a record naming this talent; ``_reach_permission``) -- one reviewed field,
read at compile time and sealed into the bundle, never a guess from a learned feature's name.
Meridian Unbinding's "gives the target a chance to escape them" is the patient's own printed escape check, asked of the patient
(``_escape_skill``) and resolved by the shared escape resolver with the patient's own skill bonus, so a proficient patient is
no worse off than with the restraint's own Escape the net action.
"""

from __future__ import annotations

from ..paid_relocation import activation

import dataclasses
from typing import Any

from . import effect, hook, note
from .needle import CHOICE, ask, checkpoint_id

T = "tianxia.talent.life."
FOUNT = "resource:named.fount_of_life"
LATENT = "condition:typed.latent_healing"
THREAD = "condition:typed.revitalizing_thread"
PULSE_SEAL = "Pulse Seal"
CONDITIONS = {"blinded", "deafened", "paralyzed", "poisoned", "charmed", "frightened", "stunned", "unconscious", "restrained", "petrified"}


def _cl(ctx: Any) -> int:
    return int(ctx.numbers.get("cl") or 1)


def _band(cl: int) -> int:
    """Realm bands: Mortal (CL 1-4), Foundation (5-9), Core Formation (10-14), Nascent Soul (15+)."""
    return 1 if cl < 5 else 2 if cl < 10 else 3 if cl < 15 else 4


def _removed(ctx: Any) -> str | None:
    """The condition this Purify use takes away (its chosen option's remove_condition row)."""
    for row in ctx.typed.get("effects") or []:
        if isinstance(row, dict) and row.get("type") == "remove_condition" and str(row.get("condition") or "") in CONDITIONS:
            return str(row["condition"])
    return None


def _target(ctx: Any) -> Any:
    return ctx.target or (ctx.targets[0] if ctx.targets else None)


def _trap_bond(engine: Any, target: Any, row: Any) -> int | None:
    """The escape DC of the Trap plug-in's own marker for this restraint, or None if it has none.

    The Trap plug-in records a net or noose as a public ``condition:typed.netted`` companion marker
    beside the Restrained row (combat/ext/trap.py trap_netted), naming the physical bond and storing
    its DC.  That marker is the printed record of "you are caught in rope", so Life reads it through
    the plug-in's public constant rather than guessing from the condition name.  A tracked net is
    already classified by physical_holds.source; this also covers the plain, untracked snare.
    """
    from . import trap  # Trap's public NETTED constant; no private state is read.

    for marker in target.conditions.values():
        if (marker.condition_id == trap.NETTED and marker.source_actor_id == row.source_actor_id
                and marker.source_definition_id == row.source_definition_id):
            return int((marker.data or {}).get("dc") or 10)
    return None


def _mundane_holds(engine: Any, target: Any, name: str) -> list[tuple[str, Any, int]]:
    """The instances of ``name`` on ``target`` that are ordinary physical bonds, with their escape DC.

    Meridian Unbinding: "This does not remove mundane restraints unless your treatment gives the
    target a chance to escape them."  Two public records say a restraint is rope rather than
    treatment: physical_holds.source classifies an ordinary physical hold from its own source row
    (and the Trap Net/Noose link), and the Trap plug-in's own ``netted`` marker names a physical
    snare.  Anything else -- a magical, Formation or spiritual hold -- is treatment the Life talents
    really do remove, exactly as before.
    """
    from . import physical_holds

    prefix = "condition:typed."
    out = []
    for iid, row in target.conditions.items():
        if row.condition_id != prefix + name:
            continue
        dc = _trap_bond(engine, target, row)
        if physical_holds.source(engine, row)[0] or dc is not None:
            out.append((iid, row, dc if dc is not None else _hold_dc(row)))
    return out


def _hold_dc(row: Any) -> int:
    """The escape DC this hold itself printed, in its own stored order of preference.

    A grapple records ``escape_dc``, a net its ``dc``, and a snare its save ``dc``; 10 is the
    table's default DC.  Nothing is invented: an unlabelled bond falls back to the table default.
    """
    data = row.data or {}
    return int(data.get("escape_dc") or data.get("dc") or (data.get("origin_save") or {}).get("dc") or 10)


ESCAPE_SKILLS = (("STR", "Athletics"), ("DEX", "Acrobatics"))


def _escape_skill(ctx: Any, target: Any, name: str, dc: int) -> tuple[str, str, int]:
    """The ability, skill and bonus the patient uses for the chance to escape its ``name``.

    "This does not remove mundane restraints unless your treatment gives the target a chance to escape
    them" gives the *patient* the check, so the patient chooses the check ("Strength (Athletics) or
    Dexterity (Acrobatics)", better of the two) and its own sheet bonus answers it -- proficiency included,
    exactly as the restraint's own Escape the net action uses it (combat/ext/trap.py).  The choice is
    asked of the patient whoever is acting: a player answers it at the table even during another
    creature's turn, and an AI picks its better skill by itself.  No decline is offered, because the
    treatment already granted the chance and only the check is open.
    """
    from ..ability_checks import ability_modifier, skill_bonus

    engine = ctx.engine
    bonus = {ability: int(skill_bonus(engine, target, skill, ability_modifier(target, ability) or 0))
             for ability, skill in ESCAPE_SKILLS}
    labels = {ability: f"Strength ({skill})" if ability == "STR" else f"Dexterity ({skill})" for ability, skill in ESCAPE_SKILLS}
    better = max(ESCAPE_SKILLS, key=lambda pair: bonus[pair[0]])[0]
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "LIFE_ESCAPE", target.entity_id), target,
                 CHOICE + "life_escape_skill", [ability for ability, _skill in ESCAPE_SKILLS], labels=labels,
                 preferred=[better], target_id=target.entity_id,
                 prompt=f"{ctx.action.display_name}: {ctx.actor.display_name}'s treatment gives "
                        f"{target.display_name} a chance to work free of being {name}. "
                        f"Make a Strength (Athletics) or a Dexterity (Acrobatics) check against DC {dc}, using your "
                        "own bonus for that skill. It costs you nothing: a success ends the restraint, and a failure "
                        "leaves you held.")
    ability = (picked or [better])[0]
    skill = next(name for key, name in ESCAPE_SKILLS if key == ability)
    return ability, skill, bonus[ability]


def _release_or_escape(ctx: Any, target: Any, name: str) -> bool:
    """End ``name`` on ``target``, or give it its printed chance to escape when it is a mundane bond.

    Meridian Unbinding only reaches a mundane restraint through "your treatment gives the target a
    chance to escape them", so a physical net/noose is resolved by the target's own printed escape
    check against the hold's DC -- never deleted outright.  The shared escape resolver rolls it, so the
    target's own skill proficiency, its scoped check benefits and every published escape mode apply
    exactly as they do for the restraint's own Escape the net action.  A restraint that is not a mundane
    bond (a magical, Formation or spiritual hold) is treatment the Life talents actually remove.

    Returns True when the condition is gone afterwards.
    """
    engine = ctx.engine
    prefix = "condition:typed."
    mundane = _mundane_holds(engine, target, name)
    if not mundane:
        if any(row.condition_id == prefix + name for row in target.conditions.values()):
            engine._remove_condition(target, prefix + name, ctx.source)
            ctx.rider(f"{target.display_name} is no longer {name}.")
        return True
    # "a chance to escape them": the target makes its own printed escape check at the hold's DC.
    from ..typed_executor import Context
    from . import physical_holds
    from .escape_checks import resolve_escape_check

    dc = max(dc for _iid, _row, dc in mundane)
    held = [row for _iid, row, _dc in mundane]
    sub = Context(engine, target, ctx.action, ctx.intent, {"numbers": {}}, [target], target, {})
    ability, skill, bonus = _escape_skill(ctx, target, name, dc)
    freed = resolve_escape_check(sub, {"type": "escape_grapple", "bonus": bonus}, dc, held, ("restrained",),
                                 check_name="Escape", source_id=ctx.source, check_ability=ability, check_skill=skill)
    if freed:
        for iid, _row, _dc in mundane:
            # end_hold also ends the restraint's own bookkeeping markers (Trap's netted: a net or noose
            # frees its marker with it, so "Caught in a net" and the Escape the net action go too).
            physical_holds.end_hold(sub, iid)
        from . import hold_escapes

        hold_escapes.escaped(engine, target, held, "physical", by=ctx.actor, source=ctx.source, way="check")
        ctx.rider(f"{target.display_name} escapes being {name}.")
    else:
        ctx.rider(f"{target.display_name} tries to escape being {name}, but remains held.")
    return freed


# ------------------------------------------------------------------------------------------------ Purify the Pulse augments
@effect("life_take_affliction")
def life_take_affliction(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import run_effects

    name = _removed(ctx)
    target = _target(ctx)
    if name is None or target is None or target is ctx.actor:
        return
    if any(row.condition_id == f"condition:typed.{name}" for row in ctx.actor.conditions.values()):
        ctx.rider(f"Empathic Transfer: {ctx.actor.display_name} already bears {name}; it cannot take it again.")
        return
    run_effects(dataclasses.replace(ctx, target=ctx.actor, targets=[ctx.actor]),
                [{"type": "condition", "condition": name, "applies_to": "self", "duration": "until_removed",
                  "evidence": "you gain the condition or disease you removed as though you had been the original target"}])


@effect("life_contagion")
def life_contagion(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import run_effects

    name = _removed(ctx)
    target = _target(ctx)
    if name is None:
        return
    others = [row for row in ctx.engine.state.actors.values() if row.active and row is not ctx.actor and row is not target
              and row.team_id != ctx.actor.team_id and ctx.engine._distance_actor_to_actor(ctx.actor, row) <= 5]
    if not others:
        ctx.rider("Contagion Reversal: no other living creature within reach to take the affliction.")
        return
    labels = {row.entity_id: f"Contagion Reversal: cast the {name} into {row.display_name}" for row in others}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "CONTAGION", ctx.actor.entity_id), ctx.actor, CHOICE + "contagion_reversal",
                 list(labels), labels=labels, preferred=[others[0].entity_id], allow_decline=True, target_id=ctx.actor.entity_id,
                 prompt="Contagion Reversal: cast the rejected affliction into another creature?")
    victim = next((row for row in others if picked and row.entity_id == picked[0]), None)
    if victim is None:
        return
    run_effects(dataclasses.replace(ctx, target=victim, targets=[victim]),
                [{"type": "save", "ability": "con", "applies_to": "target", "evidence": "Contagion Reversal: a Constitution saving throw",
                  "on_fail": [{"type": "condition", "condition": name, "applies_to": "target", "duration": "rounds", "amount": 1,
                               "expires_on": "END_OF_HOLDER_NEXT_TURN", "evidence": "The transferred effect lasts for 1 round"}]}])


@effect("life_purify_extra")
def life_purify_extra(ctx: Any, eff: dict[str, Any]) -> None:
    """One more thing a Purify use may take away: ``remove`` (a condition), ``speed`` (a Speed reduction put on by the other side),
    ``exhaustion`` (one level, once per creature)."""
    from . import end_effect, forged_exhaustion

    engine, target = ctx.engine, _target(ctx)
    if target is None:
        return
    what = str(eff.get("what") or "")
    if what in ("mind", "meridian"):
        # One of the printed kinds (Mind-Cooling Pulse: Charmed, Frightened, Stunned, Unconscious; Meridian Unbinding: a Speed reduction or
        # a Reaction lock): the user picks among those the target bears (one augment, not one per kind: options of one augment collide).
        held = {row.condition_id.rsplit(".", 1)[-1] for row in target.conditions.values()}
        if what == "mind":
            choices = {name: f"Remove {name.title()}" for name in ("charmed", "frightened", "stunned", "unconscious") if name in held}
        else:
            choices = {}
            if eff.get("auto49_conditions"):
                choices.update({name: f"Remove {name.title()}" for name in ("petrified", "restrained") if name in held})
            if end_effect.found(engine, target, {"categories": ["speed"], "select": "hostile"}):
                choices["speed"] = "Remove a Speed reduction"
            if "reaction_denied" in held:
                choices["reaction"] = "Remove a Reaction lock"
        if not choices:
            ctx.rider("Nothing of that kind to remove.")
            return
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "PURIFY_EXTRA", target.entity_id), ctx.actor, CHOICE + "purify_extra", list(choices),
                     labels=choices, preferred=list(choices)[:1], target_id=target.entity_id, prompt="Which does Purify the Pulse also remove?")
        pick = picked[0] if picked else list(choices)[0]
        if pick == "speed":
            return life_purify_extra(ctx, {"what": "speed"})
        if pick == "reaction":
            from ..typed_executor import run_effects

            run_effects(ctx, [{"type": "end_effect", "applies_to": "target", "conditions": ["reaction_denied"], "select": "hostile",
                               "evidence": "one effect preventing the target from using Reactions due to bodily restraint"}])
            return
        return life_purify_extra(ctx, {"what": "remove", "condition": pick})
    if what == "remove":
        name = str(eff.get("condition") or "")
        if any(row.condition_id == f"condition:typed.{name}" for row in target.conditions.values()):
            _release_or_escape(ctx, target, name)
        return
    if what == "speed":
        from ..typed_executor import run_effects

        run_effects(ctx, [{"type": "end_effect", "applies_to": "target", "categories": ["speed"],
                           "select": "hostile", "choose_instance": True, "evidence": "one effect reducing the target's Speed below its normal value"}])
        return
    if what == "exhaustion":
        key = f"life_round_greater_purification:{ctx.actor.entity_id}"
        if target.turn_flags.get(key):
            ctx.rider(f"Greater Purification: {target.display_name} has already benefited this long rest.")
            return
        level = forged_exhaustion.level(target)
        if level > 0 and level <= forged_exhaustion.locked_level(engine, target):
            ctx.rider(f"Greater Purification: {target.display_name}'s remaining Exhaustion cannot be removed before the scene ends.")
            return
        if level > 0:
            target.turn_flags[key] = True
            forged_exhaustion.set_level(engine, target, level - 1, ctx.source)
            ctx.rider(f"Greater Purification: {target.display_name} loses one level of Exhaustion ({level - 1} left).")
        _ = end_effect


@effect("life_purify_all")
def life_purify_all(ctx: Any, eff: dict[str, Any]) -> None:
    """Deep Root: choose any of the recorded conditions this healer can treat.

    Eligibility is sealed typed data, including owned-talent additions. Unknown
    curse/wound/spirit provenance is never guessed or indiscriminately removed.
    """
    from ..alternative_payments import owned
    from ..typed_executor import effect_subjects
    allowed = set(eff.get("conditions") or ())
    for feature, names in (eff.get("conditions_if_owned") or {}).items():
        if owned(ctx.engine, ctx.actor, feature):
            allowed.update(names)
    for target in effect_subjects(ctx, eff, harmful=False):
        choices = sorted({c.condition_id.removeprefix("condition:typed.") for c in target.conditions.values()
                          if c.condition_id.removeprefix("condition:typed.") in allowed})
        if not choices:
            continue
        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "deep_root", target.entity_id),
            ctx.actor, CHOICE + "deep_root", choices, maximum=len(choices), allow_decline=True,
            preferred=choices, default="all", labels={n: f"End {n.title()} on {target.display_name}" for n in choices},
            name="Deep Root Restoration", feature_id=T + "deep_root_restoration", target_id=target.entity_id,
            prompt=f"Deep Root Restoration: choose any remaining conditions your Life talents can remove from {target.display_name}; "
                   "the selected Purify action already includes the additional 2 CP cost.")
        for name in picked:
            _release_or_escape(ctx, target, name)


_BODY_REFINER = "life_seal_reach_body_refiner"
REACH = T + "life_seal_reach"
REACH_PERMISSION = "life_seal_reach_permission"


def _reach_permission(sheet: dict[str, Any]) -> dict[str, Any] | None:
    """The GM-recorded Life-Seal Reach permission on the owner sheet, or None.

    "Body Refiners cannot use Life-Seal Reach unless they have a forged technique, subpath feature,
    variant scripture, or GM permission that explains how their bodily Life cultivation remains physically
    connected."

    The table cannot tell *which* technique qualifies, so it never guesses from names -- and it never
    reads the sheet's ordinary inventory of learned path and subpath features either, because any learned
    feature would then hand a Body Refiner the reach their Path forbids.  The GM records the ruling once,
    on the character sheet, as ``path_and_subpath.life_seal_reach_permission``: a record naming the talent
    it grants (``talent_id``) and, in plain words, what keeps that character's cultivation physically joined
    to the Pulse Seal wearer. The record must name its source ruling (``record_id``), this talent
    (``talent_id``), and the connection (``note``). Incomplete or unrelated records do not grant reach.
    Absent the record the reach stays withheld, exactly as before.
    """
    record = (sheet.get("path_and_subpath") or {}).get(REACH_PERMISSION)
    if (isinstance(record, dict) and record.get("talent_id") == REACH
            and all(isinstance(record.get(key), str) and record[key].strip() for key in ("record_id", "note"))):
        return {key: record[key] for key in ("talent_id", "record_id", "note")}
    return None


@hook("compile_action")
def life_seal_reach_body_refiner(action: Any, info: dict[str, Any]) -> Any:
    """Life-Seal Reach: "Body Refiners cannot use Life-Seal Reach unless they have a forged technique,
    subpath feature, variant scripture, or GM permission that explains how their bodily Life cultivation
    remains physically connected."

    The typed modifier compiles its remote-range variant for everyone, so a Body Refiner was offered a
    printed reach their Path forbids. Stamp the variant at compile time (the Path is known here and
    nowhere at the table) and let ``life_allowed`` withhold it. Read the Pulse's remote reading already
    keeps the same restriction this way. A Body Refiner whose GM has recorded that permission keeps the
    reach: withholding it from an explicitly authorised character would take away a cast their printed
    text grants, and the decision is sealed into the compiled bundle, so it survives a table reload.
    """
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    modifier = typed.get("modifier") or {}
    if str(modifier.get("id") or "") != REACH:
        return None
    path = str(((info.get("owner_sheet") or {}).get("identity") or {}).get("path") or "")
    if not path.casefold().startswith("body"):
        return None
    import copy

    parameters = copy.deepcopy(action.parameters)
    permission = _reach_permission(info.get("owner_sheet") or {})
    if permission:
        # Keep the ruling's source and connection explanation in the sealed action bundle,
        # rather than persisting only the absence of the restriction flag.
        parameters[REACH_PERMISSION] = permission
    else:
        parameters[_BODY_REFINER] = True
    return action.model_copy(update={"parameters": parameters})


@hook("compile_action")
def deep_root_owned_conditions(action: Any, info: dict[str, Any]) -> Any:
    """Seal owned treatment additions into every composed Deep Root variant."""
    if T + "deep_root_restoration" not in info["owned_ids"]:
        return None
    import copy
    parameters = copy.deepcopy(action.parameters)
    pending = [parameters.get("typed", {}).get("effects") or []]
    changed = False
    while pending:
        value = pending.pop()
        if isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, dict):
            if value.get("type") == "life_purify_all" and value.get("conditions_if_owned"):
                allowed = set(value.get("conditions") or ())
                for feature, names in value.pop("conditions_if_owned").items():
                    if feature in info["owned_ids"]:
                        allowed.update(names)
                value["conditions"] = sorted(allowed)
                changed = True
            pending.extend(v for v in value.values() if isinstance(v, (dict, list)))
    return action.model_copy(update={"parameters": parameters}) if changed else None


@effect("life_physician_step")
def life_physician_step(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import Context, block_escape_grapple

    engine, target = ctx.engine, _target(ctx)
    if target is None or not target.reaction_available:
        return
    held = {row.condition_id for row in target.conditions.values()}
    options = {}
    if "condition:typed.prone" in held:
        options["stand"] = "Physician's Step: stand from Prone"
    if held & {"condition:typed.grappled", "condition:typed.pinned"}:
        options["escape"] = "Physician's Step: escape the grapple with Advantage"
    if not options:
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "PHYSICIAN_STEP", target.entity_id), target, CHOICE + "physician_s_step", list(options),
                 labels=options, preferred=["escape"] if "escape" in options else ["stand"], allow_decline=True, target_id=target.entity_id,
                 prompt="Physician's Step: use your Reaction?")
    if not picked:
        return
    with activation(engine, target, ctx.source):
        target.reaction_available = False
        if picked[0] == "stand":
            engine._remove_condition(target, "condition:typed.prone", ctx.source)
            ctx.rider(f"{target.display_name} stands up.")
            return
        engine.__dict__["_life_escape_advantage"] = target.entity_id
        try:
            block_escape_grapple(Context(engine, target, ctx.action, ctx.intent, {"numbers": {}}, [target], target, {}), {"type": "escape_grapple"})
        finally:
            engine.__dict__.pop("_life_escape_advantage", None)


@hook("escape_mode")
def physician_escape_mode(engine: Any, escaper: Any, grips: Any) -> str | None:
    return "ADVANTAGE" if engine.__dict__.get("_life_escape_advantage") == escaper.entity_id else None


# ------------------------------------------------------------------------------------------------ Mend the Pulse augments
def _healing_rows(ctx: Any) -> list[dict[str, Any]]:
    """Mend the Pulse's own healing row (the one a replace_healing augment took out), rebuilt from the compiled action."""
    base = ctx.engine.action_catalog.get(str(ctx.source).split("+", 1)[0]) or ctx.action
    rows = [row for row in (((base.parameters or {}).get("typed") or {}).get("effects") or []) if isinstance(row, dict) and row.get("type") == "healing"]
    return rows or [{"type": "healing", "dice": {"count": 1, "sides": 8}, "formula": "key_ability_modifier"}]


@hook("compile_resources")
def fount_pool(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ResourceDefinition

    owned = set(info.get("owned_ids") or [])
    if T + "fount_of_life" not in owned:
        return None
    cl = int((info.get("numbers") or {}).get("cl") or 1)
    most = (20 if T + "hundred_medicine_core" in owned else 10) * cl
    return [ResourceDefinition(resource_id=FOUNT, initial=0, maximum=most)]


@effect("life_fount_store")
def life_fount_store(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import _effect_dice, _roll

    row = _healing_rows(ctx)[0]
    amount = _roll(ctx, ctx.dice(_effect_dice(ctx, row), flat=int(row.get("flat") or 0), formula=row.get("formula")), "HEALING")
    before = int(ctx.actor.resources.get(FOUNT, 0))
    if FOUNT in ctx.actor.resources and amount > 0:
        ctx.engine._gain_resource(ctx.actor, FOUNT, int(amount), ctx.source)
    ctx.rider(f"Fount of Life: {int(ctx.actor.resources.get(FOUNT, 0)) - before} healing stored ({ctx.actor.resources.get(FOUNT, 0)} in all).")


@effect("life_fount_release")
def life_fount_release(ctx: Any, eff: dict[str, Any]) -> None:
    from . import life_state

    target = _target(ctx)
    if target is None:
        return
    amount = min(int(ctx.actor.resources.get(FOUNT, 0)), max(0, target.maximum_hp - target.current_hp))
    if amount <= 0:
        ctx.rider("Fount of Life: nothing to release (no stored healing, or no injury).")
        return
    ctx.engine._spend_resource(ctx.actor, FOUNT, amount, ctx.source)
    life_state.heal_to(ctx.engine, target, amount, ctx.source, ctx.actor.entity_id)
    ctx.rider(f"Fount of Life: {target.display_name} regains {amount} Hit Points from the stored healing.")


@hook("compile_actions")
def fount_release_action(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    owned = set(info.get("owned_ids") or [])
    out = []
    if T + "fount_of_life" in owned:
        typed = {"effects": [{"type": "life_fount_release", "evidence": "As an Action, you may touch one creature and release any amount of stored healing"}],
                 "numbers": dict(info["numbers"]), "duration": {"kind": "instant"}, "riders": [], "source": T + "fount_of_life", "coverage": "FULL"}
        out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.life.fount_release", display_name="Release Fount of Life",
                                    owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="ALLY_OR_SELF", range_ft=5,
                                    parameters={"typed": typed, "expected_damage": 0, "life_extra": "fount"}))
    path = str(((info.get("owner_sheet") or {}).get("identity") or {}).get("path") or "")
    if "LIFE_BASE_READ_THE_PULSE" in owned or "tianxia.sphere.life" in (info.get("spheres") or []):
        if not path.lower().startswith("body"):  # "Body Refiners cannot use this remote reading"
            from ..typed_executor import mark_condition_id

            typed = {"effects": [{"type": "life_read_pulse", "remote": True, "evidence": "You may use Read the Pulse on a creature bearing your Pulse Seal regardless of distance"}],
                     "numbers": dict(info["numbers"]), "duration": {"kind": "instant"}, "riders": [], "source": "LIFE_BASE_READ_THE_PULSE", "coverage": "FULL"}
            out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.life.read_remote", display_name="Read the Pulse (Pulse Seal)",
                                        owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="ALLY_OR_SELF", range_ft=None,
                                        parameters={"typed": typed, "expected_damage": 0, "player_only": True,
                                                    "target_requires_condition": mark_condition_id(PULSE_SEAL, info["actor_id"])}))
    return out or None


@hook("candidate_allowed")
def life_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    params = action.parameters or {}
    if params.get(_BODY_REFINER):
        return False  # Life-Seal Reach: "Body Refiners cannot use Life-Seal Reach" (stamped at compile time).
    if params.get("life_extra") == "fount":
        return None if actor.resources.get(FOUNT, 0) >= 1 else False
    source = str(action.source_definition_id)
    if "LIFE_BASE_BORROWED_BREATH" in source and candidate.target_ids and "Greater Invigorate" not in str(action.display_name):
        typed = params.get("typed") or {}
        if any(row.get("type") == "life_latent" and row.get("auto49_vitality") for row in typed.get("effects") or []):
            return None  # Latent Healing explicitly allows an uninjured carrier.
        target = engine.state.actors.get(candidate.target_ids[0])
        # "Borrowed Breath can only be used on an injured target" (Greater Invigorate: "may be used on a creature at full Hit Points")
        return None if target is not None and target.current_hp < target.maximum_hp else False
    return None


@effect("life_latent")
def life_latent(ctx: Any, eff: dict[str, Any]) -> None:
    target = _target(ctx)
    if target is None:
        return
    for iid, row in list(target.conditions.items()):
        if row.condition_id == LATENT and row.source_actor_id == ctx.actor.entity_id:
            ctx.engine._remove_condition(target, LATENT, ctx.source)  # "only one Latent Healing from you at a time"
            break
    data = {"rows": _healing_rows(ctx), "numbers": dict(ctx.numbers), "label": "Latent Healing: its Reaction when injured releases it"}
    if eff.get("auto49_vitality"):
        base = ctx.engine.action_catalog.get(str(ctx.source).split("+", 1)[0]) or ctx.action
        original = base.parameters.get("typed") or {}
        data["rows"] = [dict(row) for row in original.get("effects") or [] if row.get("effect_slot") == "life_delayed_vitality"]
        data["duration"] = dict(original.get("duration") or {})
        data["label"] = "Latent Healing: when injured, spend your Reaction to release the stored healing or Borrowed Breath; ends at your next rest"
    ctx.engine._apply_condition(target, LATENT, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED", data=data)
    ctx.rider(f"{target.display_name} carries Latent Healing; when injured it may use its Reaction to trigger it.")


def trigger_latent(engine: Any, carrier: Any, intent: Any = None) -> bool:
    """Run the carrier's Latent Healing now (Life-Preserving Diagnosis may trigger it too)."""
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..typed_executor import Context, run_effects

    iid = next((iid for iid, row in carrier.conditions.items() if row.condition_id == LATENT), None)
    if iid is None:
        return False
    row = carrier.conditions[iid]
    healer = engine.state.actors.get(row.source_actor_id or "") or carrier
    data = row.data or {}
    engine._remove_condition(carrier, LATENT, row.source_definition_id)
    action = ActionDefinition(source_definition_id=row.source_definition_id, display_name="Latent Healing", owner_id=healer.entity_id,
                              economy=EconomyKind.REACTION, resolution_kind="TYPED", target_kind="ALLY_OR_SELF")
    run_effects(Context(engine, healer, action, intent, {"numbers": data.get("numbers") or {}, "effects": [],
                                                     "duration": data.get("duration") or {}}, [carrier], carrier, {}),
                [{**r, "applies_to": "target"} for r in data.get("rows") or []])
    return True


@hook("event")
def latent_on_injury(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "DAMAGE_COMMITTED":
        return
    for target_id in kwargs.get("target_ids") or ():
        carrier = engine.state.actors.get(target_id)
        if carrier is None or not carrier.active or carrier.current_hp >= carrier.maximum_hp or not carrier.reaction_available:
            continue
        if int((kwargs.get("payload") or {}).get("hp_damage") or 0) <= 0 or not any(row.condition_id == LATENT for row in carrier.conditions.values()):
            continue
        packet = next(row for row in carrier.conditions.values() if row.condition_id == LATENT)
        benefit = "receive delayed Borrowed Breath (Temporary HP)" if any(
            row.get("type") == "temp_hp" for row in packet.data.get("rows") or []) else "regain the delayed healing"
        picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "LATENT", carrier.entity_id), carrier, CHOICE + "latent_healing",
                     ["use"], labels={"use": f"Latent Healing: use your Reaction to {benefit}"}, allow_decline=True,
                     target_id=carrier.entity_id, prompt=f"{carrier.display_name} is injured: spend its Reaction to trigger Latent Healing?")
        if picked:
            with activation(engine, carrier, packet.source_definition_id):
                carrier.reaction_available = False
                trigger_latent(engine, carrier)


@effect("life_thread")
def life_thread(ctx: Any, eff: dict[str, Any]) -> None:
    target = _target(ctx)
    if target is None:
        return
    sustained = bool(eff.get("sustained"))
    if not sustained:
        ctx.engine._start_concentration(ctx.actor, ctx.source)
    ctx.engine._apply_condition(target, THREAD, ctx.source, ctx.actor.entity_id,
                                expires_on="UNTIL_REMOVED" if sustained else "CONCENTRATION_END",
                                data={"amount": _band(_cl(ctx)), "ends_round": int(ctx.engine.state.round_number) + 10,
                                      "label": f"Revitalizing Thread: regains {_band(_cl(ctx))} HP at the start of each of its turns"})
    ctx.rider(f"Revitalizing Thread on {target.display_name}: {_band(_cl(ctx))} HP at the start of each of its turns for up to 1 minute.")


@hook("turn_start")
def thread_turn(engine: Any, actor: Any) -> None:
    from . import life_state

    iid = next((iid for iid, row in actor.conditions.items() if row.condition_id == THREAD), None)
    if iid is None:
        return
    row = actor.conditions[iid]
    data = row.data or {}
    if int(engine.state.round_number) > int(data.get("ends_round") or 0):
        engine._remove_condition(actor, THREAD, row.source_definition_id)
        return
    if actor.current_hp <= 0:
        life_state.stabilize(engine, actor, row.source_definition_id)  # "A creature at 0 Hit Points is stabilized"
        return
    life_state.heal_to(engine, actor, int(data.get("amount") or 1), row.source_definition_id, row.source_actor_id)


# ------------------------------------------------------------------------------------------------ more targets, Adrenaline Surge
@effect("life_more_targets")
def life_more_targets(ctx: Any, eff: dict[str, Any]) -> None:
    """Run this Pulse ability's own effects (not the augments') on more willing creatures."""
    if eff.get("choose_patients"):
        from .life_treatment import treat_additional

        return treat_additional(ctx, eff)
    from ..typed_executor import bears_mark, run_effects

    engine, actor, first = ctx.engine, ctx.actor, _target(ctx)
    kind = str(eff.get("kind") or "")
    cl = _cl(ctx)
    if kind == "array":
        reach = {1: 30, 2: 30, 3: 60, 4: 120}[_band(cl)]
        extra = [row for row in engine.state.actors.values() if row.active and row is not first and row.team_id == actor.team_id
                 and bears_mark(row, actor.entity_id, PULSE_SEAL) and engine._distance_actor_to_actor(actor, row) <= reach]
    else:
        count = {1: 1, 2: 2, 3: int(ctx.numbers.get("pb") or 2), 4: int(ctx.numbers.get("pb") or 2)}[_band(cl)]
        near = [row for row in engine.state.actors.values() if row.active and row is not first and row.team_id == actor.team_id
                and (engine._distance_actor_to_actor(actor, row) <= 5
                     or (_band(cl) == 4 and bears_mark(row, actor.entity_id, PULSE_SEAL) and engine._distance_actor_to_actor(actor, row) <= 30))]
        near.sort(key=lambda row: (row.current_hp - row.maximum_hp, row.entity_id))
        extra = near[:count]
    rows = [row for row in (ctx.typed.get("effects") or []) if isinstance(row, dict) and not row.get("source_modifier")
            and row.get("type") not in ("life_more_targets", "mark")]
    for other in extra:
        run_effects(dataclasses.replace(ctx, target=other, targets=[other]), rows)
    if extra:
        ctx.rider(f"{eff.get('name') or 'Life'}: also {', '.join(row.display_name for row in extra)}.")


@effect("life_adrenaline")
def life_adrenaline(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_reactions
    from ..typed_executor import Context, block_escape_grapple, run_effects

    engine, ally = ctx.engine, _target(ctx)
    if ally is None or ally is ctx.actor or ally.team_id != ctx.actor.team_id or not ally.reaction_available or not ally.active:
        return
    foes = sorted((row for row in engine.state.actors.values() if row.active and row.team_id != ally.team_id),
                  key=lambda row: engine._distance_actor_to_actor(ally, row))
    held = {row.condition_id for row in ally.conditions.values()}
    options = {}
    if foes and engine._distance_actor_to_actor(ally, foes[0]) <= 5:
        options["attack"] = f"Adrenaline Surge: make one weapon attack against {foes[0].display_name}"
    if foes:
        options["move"] = "Adrenaline Surge: move up to your Speed (away from the nearest foe)"
    if held & {"condition:typed.grappled", "condition:typed.pinned"}:
        options["escape"] = "Adrenaline Surge: try to escape the grapple"
    if "condition:typed.prone" in held:
        options["stand"] = "Adrenaline Surge: stand up from Prone"
    if not options:
        return
    preferred = next(key for key in ("escape", "stand", "attack", "move") if key in options)
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "ADRENALINE", ally.entity_id), ally, CHOICE + "adrenaline_surge", list(options),
                 labels=options, preferred=[preferred], allow_decline=True, target_id=ally.entity_id, prompt="Adrenaline Surge: use your Reaction?")
    if not picked:
        return
    with activation(engine, ally, T + "adrenaline_surge"):
        ally.reaction_available = False
        choice = picked[0]
        if choice == "stand":
            engine._remove_condition(ally, "condition:typed.prone", ctx.source)
        elif choice == "escape":
            block_escape_grapple(Context(engine, ally, ctx.action, ctx.intent, {"numbers": {}}, [ally], ally, {}), {"type": "escape_grapple"})
        elif choice == "move":
            run_effects(typed_reactions._generic_context(engine, ally, foes[0], {"feature_id": T + "adrenaline_surge", "name": "Adrenaline Surge", "effects": []}),
                        [{"type": "reaction_move", "direction": "away", "distance_ft": "speed"}])
        else:
            row = {"feature_id": T + "adrenaline_surge", "name": "Adrenaline Surge", "numbers": {},
                   "effects": [{"type": "attack", "attack_kind": "weapon", "count": 1, "on_hit": []}]}
            sub = typed_reactions._generic_context(engine, ally, foes[0], row)
            run_effects(sub, row["effects"])


# ------------------------------------------------------------------------------------------------ Read the Pulse, Vital Court Field
@effect("life_read_pulse")
def life_read_pulse(ctx: Any, eff: dict[str, Any]) -> None:
    from . import life_state

    target = _target(ctx)
    if target is None:
        return
    held = {row.condition_id.rsplit(".", 1)[-1] for row in target.conditions.values() if row.condition_id.startswith("condition:typed.")}
    state = "dead (its soul lingers)" if life_state.is_dead(target) else "dying" if target.life_state == "DYING" else \
        "stable at 0 Hit Points" if target.life_state == "STABLE" else "living"
    found = [name.title() for name in ("poisoned", "blinded", "deafened", "paralyzed") if name in held]
    words = f"Read the Pulse: {target.display_name} is {state}" + (f"; {', '.join(found)}" if found else "") + \
        ("; it has 0 Hit Points" if target.current_hp <= 0 else "") + "."
    if eff.get("remote"):
        dx, dy = target.position.x - ctx.actor.position.x, target.position.y - ctx.actor.position.y
        way = ("north" if dy < 0 else "south" if dy > 0 else "") + ("east" if dx > 0 else "west" if dx < 0 else "")
        words += f" It is {ctx.engine._distance_actor_to_actor(ctx.actor, target)} feet away" + (f", to the {way}." if way else ".")
    note(ctx.engine, ctx.source, ctx.actor, words, targets=(target,))
    from . import run_strict
    run_strict("pulse_read", ctx, target)


@hook("event")
def vital_court(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Vital Court Field: "Once per round, when a chosen creature in the aura regains Hit Points from one of your Life abilities, another
    chosen creature in the aura may gain Temporary HP equal to your Proficiency Bonus" (chosen: the Pulse Seals it gave)."""
    if event_type not in ("HEALING_APPLIED", "HP_RESTORED", "HEALED"):
        return
    source = str(engine.events[-1].source_definition_id if engine.events else "")
    if ".life." not in source.lower() and "LIFE_BASE" not in source:
        return
    from ..typed_executor import bears_mark

    healer = engine.state.actors.get(kwargs.get("actor_id") or "")
    for zone in list(engine.state.zones.values()):
        if not zone.active or healer is None or zone.owner_id != healer.entity_id or not str(zone.source_definition_id).endswith(T + "vital_court_field"):
            continue
        if healer.turn_flags.get("life_round_vital_court") == engine.state.round_number:
            return
        chosen = [row for row in engine.state.actors.values() if row.active and bears_mark(row, healer.entity_id, PULSE_SEAL)
                  and engine._footprint_intersects(row, zone.affected_cells)]
        healed = set(kwargs.get("target_ids") or ())
        if not healed & {row.entity_id for row in chosen}:
            return
        others = sorted((row for row in chosen if row.entity_id not in healed), key=lambda row: (row.temporary_hp, row.current_hp - row.maximum_hp))
        if others:
            from .needle import CHOICE, ask, checkpoint_id

            pb = next((int((((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("pb") or 2) for a in engine.action_catalog.values()
                       if a.owner_id == healer.entity_id and (a.parameters or {}).get("typed")), 2)
            healed_names = ", ".join(engine.state.actors[i].display_name for i in healed if i in engine.state.actors)
            picked = ask(engine, getattr(engine, "_active_intent", None),
                         checkpoint_id(engine, "VITAL_COURT", healer.entity_id), healer,
                         CHOICE + "vital_court", [row.entity_id for row in others],
                         labels={row.entity_id: row.display_name for row in others},
                         preferred=[others[0].entity_id], allow_decline=True,
                         prompt=f"Vital Court Field: {healed_names} regained Hit Points from your Life ability. "
                                f"Choose another creature in the aura that you marked with a Pulse Seal when creating the field. "
                                f"It gains {pb} Temporary HP (your Proficiency Bonus) to absorb damage until used up or replaced. "
                                "This costs no additional CP and can happen once per round while the field lasts "
                                "(Concentration, up to 1 minute).")
            if not picked:
                return
            healer.turn_flags["life_round_vital_court"] = engine.state.round_number
            engine._grant_temp_hp(engine.state.actors[picked[0]], pb, T + "vital_court_field", healer.entity_id)
        return


# ------------------------------------------------------------------------------------------------ Hall of Returning Breath, Diagnosis
DELAYED = "condition:typed.death_delayed"
HALL = T + "life_domain_hall_of_returning_breath"
DIAGNOSIS = T + "life_preserving_diagnosis"


def _in_hall(engine: Any, owner: Any, creature: Any) -> Any:
    from ..typed_executor import bears_mark

    for zone in engine.state.zones.values():
        if zone.active and zone.owner_id == owner.entity_id and str(zone.source_definition_id).endswith(HALL) \
                and bears_mark(creature, owner.entity_id, PULSE_SEAL) and engine._footprint_intersects(creature, zone.affected_cells):
            return zone
    return None


def _pool_of(actor: Any) -> str | None:
    return next((pool for pool in ("resource:core.qi", "resource:core.stamina", "resource:core.resonance") if actor.resources.get(pool, 0) > 0), None)


def _delay(engine: Any, owner: Any, target: Any, cost: int, source: str, name: str) -> None:
    pool = _pool_of(owner)
    owner.reaction_available = False
    if pool is not None and cost:
        engine._spend_resource(owner, pool, cost, source)
    engine._apply_condition(target, DELAYED, source, owner.entity_id, expires_on="UNTIL_REMOVED",
                            data={"turns": int(target.turns_started or 0) + 1, "label": f"{name}: its death waits until the end of its next turn"})
    note(engine, source, owner, f"{name}: {owner.display_name} holds back {target.display_name}'s death until the end of its next turn.", targets=(target,))


def _hold_death(engine: Any, target: Any, cause: str, source_id: str) -> bool:
    """A creature that would die: already delayed (it stays at 0 until its turn ends), or a Life user delays it now -- the Hall of
    Returning Breath (Reaction and 2 CP, once per Hall, a chosen creature in the aura) or Life-Preserving Diagnosis (Reaction and 1 CP, a
    Pulse Seal bearer dying of failed death saves)."""
    from .. import typed_reactions
    from ..typed_executor import bears_mark

    if any(row.condition_id == DELAYED for row in target.conditions.values()):
        return True
    for owner in engine.state.actors.values():
        if not owner.active or owner is target or owner.team_id != target.team_id or not typed_reactions._can_react(engine, owner):
            continue
        owned = {row.get("feature_id") for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(owner.entity_id, [])}
        hall = _in_hall(engine, owner, target)
        options = {}
        if hall is not None and not (hall.trigger_profile or {}).get("hall_delay_used") and owner.resources.get(_pool_of(owner) or "", 0) >= 2:
            options["hall"] = f"Hall of Returning Breath (Reaction, 2 CP): delay {target.display_name}'s death"
        if DIAGNOSIS in owned and bears_mark(target, owner.entity_id, PULSE_SEAL) and "death saving" in cause and owner.resources.get(_pool_of(owner) or "", 0) >= 1:
            options["diagnosis"] = f"Life-Preserving Diagnosis (Reaction, 1 CP): delay {target.display_name}'s death"
            if any(row.condition_id == LATENT and row.source_actor_id == owner.entity_id for row in target.conditions.values()):
                options["latent"] = f"Life-Preserving Diagnosis (Reaction): trigger {target.display_name}'s Latent Healing"
        if not options:
            continue
        preferred = ["latent"] if "latent" in options else ["diagnosis"] if "diagnosis" in options else ["hall"]
        picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "HOLD_DEATH", owner.entity_id, target.entity_id), owner,
                     CHOICE + "hold_death", list(options), labels=options, preferred=preferred, allow_decline=True, target_id=target.entity_id,
                     prompt=f"{target.display_name} is about to die.")
        if not picked:
            continue
        with activation(engine, owner, HALL if picked[0] == "hall" else DIAGNOSIS):
            if picked[0] == "latent":
                owner.reaction_available = False
                trigger_latent(engine, target)
                return target.current_hp > 0
            if picked[0] == "hall":
                hall.trigger_profile = {**hall.trigger_profile, "hall_delay_used": True}
                engine._append_event("ZONE_CREATED", HALL, actor_id=owner.entity_id, payload={"zone": hall.model_dump(mode="json")})
                _delay(engine, owner, target, 2, HALL, "Hall of Returning Breath")
            else:
                _delay(engine, owner, target, 1, DIAGNOSIS, "Life-Preserving Diagnosis")
            return True
    return False


def _register() -> None:
    from . import life_state

    life_state.handler(_hold_death, priority=-100)  # delay before soul preservation


_register()


@hook("turn_end")
def delayed_death_ends(engine: Any, actor: Any) -> None:
    from . import life_state

    row = next((row for row in actor.conditions.values() if row.condition_id == DELAYED), None)
    if row is None or int(actor.turns_started or 0) < int((row.data or {}).get("turns") or 0):
        return
    engine._remove_condition(actor, DELAYED, row.source_definition_id)
    if actor.current_hp <= 0 and actor.active:
        life_state.die(engine, actor, "the delayed death", row.source_definition_id)


@hook("row_allowed")
def diagnosis_row(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    """The compiled Life-Preserving Diagnosis row (an ally dropping to 0) is not its trigger: the death handler above plays it."""
    return False if row.get("feature_id") == DIAGNOSIS else None


@hook("event")
def hall_extra_healing(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Hall of Returning Breath: "the first time each round it regains Hit Points from one of your Life abilities, it regains additional
    Hit Points equal to your key ability modifier"."""
    from . import life_state

    if event_type != "HEALING_APPLIED":
        return
    source = str(engine.events[-1].source_definition_id if engine.events else "")
    if (".life." not in source.lower() and "LIFE_BASE" not in source) or source == HALL:
        return
    healer = engine.state.actors.get(kwargs.get("actor_id") or "")
    if healer is None:
        return
    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        if target is None or _in_hall(engine, healer, target) is None or target.turn_flags.get("life_round_hall_heal") == engine.state.round_number:
            continue
        target.turn_flags["life_round_hall_heal"] = engine.state.round_number
        key = next((int((((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("key_mod") or 0) for a in engine.action_catalog.values()
                    if a.owner_id == healer.entity_id and (a.parameters or {}).get("typed")), 0)
        if key > 0:
            life_state.heal_to(engine, target, key, HALL, healer.entity_id)


@hook("turn_start")
def hall_stable_recovery(engine: Any, actor: Any) -> None:
    """"if it has 0 Hit Points and is stable, it may regain 1 Hit Point at the start of its turn"."""
    from . import life_state

    if actor.life_state != "STABLE" or actor.current_hp > 0:
        return
    for owner in engine.state.actors.values():
        if owner.team_id == actor.team_id and _in_hall(engine, owner, actor) is not None:
            life_state.heal_to(engine, actor, 1, HALL, owner.entity_id)
            return


@hook("compile_actions")
def sustained_thread_action(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..factory_compiler import RESOURCE_IDS

    if T + "revitalizing_thread" not in (info.get("owned_ids") or []):
        return None
    pool = RESOURCE_IDS.get(str(info.get("primary") or "qi"), "resource:core.qi")
    typed = {"effects": [{"type": "life_sustain_thread", "evidence": "Augment - Sustained Thread, 2 CP: Revitalizing Thread persists for its remaining duration without Concentration."}],
             "numbers": dict(info["numbers"]), "duration": {"kind": "instant"}, "riders": [], "source": T + "revitalizing_thread", "coverage": "FULL"}
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.life.sustained_thread", display_name="Sustained Thread (2 CP)",
                             owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF", costs=((pool, 2),),
                             parameters={"typed": typed, "expected_damage": 0, "player_only": True, "life_extra": "sustain"})]


def _my_threads(engine: Any, actor: Any) -> list[tuple[Any, str, Any]]:
    return [(other, iid, row) for other in engine.state.actors.values() for iid, row in other.conditions.items()
            if row.condition_id == THREAD and row.source_actor_id == actor.entity_id and row.expires_on == "CONCENTRATION_END"]


@hook("candidate_allowed")
def sustain_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or (action.parameters or {}).get("life_extra") != "sustain":
        return None
    return None if engine.state.current_actor_id == actor.entity_id and _my_threads(engine, actor) else False


@effect("life_sustain_thread")
def life_sustain_thread(ctx: Any, eff: dict[str, Any]) -> None:
    for other, iid, row in _my_threads(ctx.engine, ctx.actor):
        data = dict(row.data or {})
        del other.conditions[iid]
        ctx.engine._append_event("CONDITION_REMOVED", row.source_definition_id, actor_id=ctx.actor.entity_id, target_ids=(other.entity_id,),
                                 payload={"condition_id": THREAD, "instance_id": iid, "reason": "SUSTAINED"})
        ctx.engine._apply_condition(other, THREAD, "sustained:" + row.source_definition_id, ctx.actor.entity_id, expires_on="UNTIL_REMOVED", data=data)
        conc = ctx.actor.concentration
        if conc is not None and conc.source_definition_id == row.source_definition_id:
            ctx.engine._end_concentration(ctx.actor, "SUSTAINED")
        ctx.rider(f"Sustained Thread: the Revitalizing Thread on {other.display_name} no longer needs Concentration.")
