"""Unmaking Channels, Crack and the sphere's printed "choose one cost" (rider lane C5, owner 2026-09-30: "i want everything we
can automated"). Shared by combat/unmaking.py and the Unmaking talents' typed rows; public API below, no private use elsewhere.

The printed rules (Tianxia Sphere Compendium, Sphere of Unmaking, "Core Unmaking Terms"):

  External Channel   a weapon, talisman, tool or object used to carry Unmaking qi. Here: a weapon the character holds
                     (combat/ext/weapon_hits.available_weapons), each by its own compiled weapon action.
  Crack              damage to an External Channel. An ordinary weapon holds 2 Crack safely; at 3 it breaks after the
                     current attack or technique resolves. The table's kits carry no rarity tiers, so every weapon is ordinary
                     (2 + rarity tier is the GM's for a refined weapon); an artifact never gains Crack here (its owner does not
                     allow it; the printed 1d6-per-Crack alternative is the GM's).
                     Stored as one condition per weapon, "condition:typed.unmaking_crack.<weapon slug>", data {"weapon": the
                     weapon action id, "count": int} (strings and integers only; replaced, never mutated in place). A broken
                     weapon is "condition:typed.unmaking_broken.<slug>" with data {"disables_action": weapon id}: the engine no
                     longer offers that weapon (Gate2's disabled-action gate), and nothing picks it back up.

  pay(ctx, options, name=...)  "choose one: gain 1 Black Vein Strain; take 1d6 + PB Ruin self-damage; one External Channel gains
                     1 Crack" and the like. ``options`` is the printed list, in order, of dicts:
                         {"strain": n}                                  gain n Black Vein Strain (Last Inch Control applies)
                         {"self": {"count", "sides", "bonus": int | "pb" | "cl"}}   Ruin self-damage
                         {"crack": n}                                   n Crack on one held weapon (one option per weapon)
                         {"destroy": 1}                                 destroy one held non-artifact weapon
                         {"max_hp_loss": n}                             reduce your current and maximum HP by n until you
                                                                        finish a Long Rest (combat/maximum_hp.py; in a fight
                                                                        that is the rest of the fight)
                         {"gm": "text"}                                 a printed cost the table cannot apply: choosing it
                                                                        leaves a GM line
                     The owner chooses (a player is asked, on its own turn or an AI's; the built-in AI prefers Strain short of
                     a Ruin Backlash, then a Crack short of breaking the weapon, then self-damage -- _ai_rank). Weapon Pays First (its own
                     row, block "unmaking", kind "weapon_pays_first") offers twice-PB self-damage instead of each Crack, once
                     per turn.
  crack / cracks / remove_crack / destroy / is_broken   the Crack bookkeeping itself.
  channel_name                a Channel's name on the table. Shared with combat/ext/unmaking_forms.py.
  delay_or_crack / settle_delayed_crack / delayed_crack     First Ruin Form: External Vessel Mandate -- "when the chosen
                     Channel would gain Crack, roll a d6. On a 5 or 6, the Crack is delayed until the form ends; when the
                     form ends, all delayed Crack applies at once". The held-back Crack lives on its own
                     condition:typed.unmaking_delayed_crack (one integer count and the weapon's action id), because the
                     form's own keys are already gone by the time its expiry event reaches a hook. settle_delayed_crack
                     returns that weapon id and whether applying the Crack broke it.
  chosen_channel         the held weapon the active form chose ("Choose one held weapon or implement"); another weapon's
                     Crack is never delayed. combat/ext/unmaking_forms.py records the choice and settles the Crack.

Effect type "unmaking_cost": {"type": "unmaking_cost", "options": [...], "name": "..."} runs pay() once for the activation
(after its other effects, where the text says "After resolving the technique, choose one").
Default-inert: nothing here runs unless an Unmaking talent's own typed row or combat/unmaking.py calls it.
candidate_allowed and opportunity_allowed follow delivery provenance only while the actor carries a saved
unmaking_broken condition; a broken Channel cannot deliver another technique or opportunity attack.
"""

from __future__ import annotations

import re
from typing import Any

from . import effect, hook

CRACK = "condition:typed.unmaking_crack."
BROKEN = "condition:typed.unmaking_broken."
SAFE_CRACK = 2  # "An ordinary weapon, tool, or object can hold 2 Crack safely. At 3 Crack, it breaks"
STRAIN = "resource:named.black_vein_strain"


def channel_weapon_identity(ctx: Any) -> str | None:
    """External Channel used by direct, delivered or opportunity attacks; None for bodily/unarmed delivery.

    Shared by Ruin Channel's price and Devouring Dregs' recovery. Use compiler delivery provenance,
    never the technique's source or display name, to identify the equipment that carries Crack.
    """
    from .weapon_hits import weapon_identity
    from ..weapon_delivery import delivery_kind

    # Grip variants may retain a weapon parent for equipment bookkeeping. The
    # initiating packet still decides whether this is bodily delivery.
    attacks = [row for row in ctx.typed.get('effects') or [] if row.get('type') == 'attack']
    if ctx.typed.get('unarmed_option') or any(
            delivery_kind(ctx.typed, row, ctx.action.parameters) == 'unarmed' for row in attacks):
        return None

    source = weapon_identity(ctx)
    action = ctx.engine.action_catalog.get(source)
    typed = ((action.parameters or {}).get("typed") or {}) if action else ctx.typed
    attack = next((row for row in typed.get("effects") or [] if row.get("type") == "attack"), {})
    if (not typed.get("weapon") or typed.get("unarmed_option") or typed.get("source") == "unarmed_strike"
            or ".natural." in source or ".unarmed." in source or attack.get("attack_kind") == "unarmed"):
        return None
    return source


def _uses_broken_channel(engine: Any, actor: Any, action: Any) -> bool:
    """Follow delivery for saved Crack breaks as well as basic weapon actions."""
    from types import SimpleNamespace
    from .weapon_hits import weapon_identity

    broken = {c.data.get("disables_action") for c in actor.conditions.values() if c.condition_id.startswith(BROKEN)}
    if not broken or action is None:
        return False
    typed = (action.parameters or {}).get("typed") or {}
    return weapon_identity(SimpleNamespace(engine=engine, action=action, typed=typed)) in broken


@hook("candidate_allowed")
def broken_delivery(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    return False if _uses_broken_channel(engine, actor, action) else None


@hook("opportunity_allowed")
def broken_opportunity(engine: Any, reactor: Any, mover: Any) -> bool | None:
    for action in engine.action_catalog.values():
        if action.owner_id == reactor.entity_id and ((action.parameters or {}).get("typed") or {}).get("opportunity_of"):
            if _uses_broken_channel(engine, reactor, action):
                return False
    return None


def _slug(weapon_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(weapon_id).lower()).strip("_")


def held_forms(engine: Any, actor: Any) -> dict[str, Any]:
    """The held weapons and implements a form may bind its qi to: {weapon action id: action}.

    "Choose one held weapon or implement" (First Ruin Form) puts no condition on the implement, so an artifact weapon
    is in here: not being able to take Crack is what :func:`channels` leaves out, not being choosable. The body's own
    strikes are not implements and stay out of both -- Unarmed Strike options, natural weapons and improvised attacks.
    Shared with combat/ext/unmaking_forms.py, which asks which one is the Channel."""
    from .weapon_hits import available_weapons

    def implement(key: str, typed: dict[str, Any]) -> bool:
        attack = next((row for row in typed.get("effects") or [] if isinstance(row, dict) and row.get("type") == "attack"), {})
        return not (typed.get("unarmed_option") or ".natural." in key or ".unarmed." in key or ".improvised." in key
                    or attack.get("attack_kind") == "unarmed" or typed.get("source") == "unarmed_strike")

    return {key: action for key, action in sorted(available_weapons(engine, actor).items())
            if implement(key, (action.parameters or {}).get("typed") or {})}


def channels(engine: Any, actor: Any) -> dict[str, Any]:
    """The held weapons that can take Crack now: {weapon action id: action}, artifacts left out.

    Every implement :func:`held_forms` can bind, minus the artifacts, because Crack is the printed price and
    :func:`crack` never puts it on an artifact."""
    return {key: action for key, action in held_forms(engine, actor).items()
            if not ((action.parameters or {}).get("typed") or {}).get("artifact")}


def cracks(actor: Any, weapon_id: str) -> int:
    found = actor.conditions.values()
    return sum(int((c.data or {}).get("count") or 0) for c in found if c.condition_id == CRACK + _slug(weapon_id))


def _name(engine: Any, weapon_id: str) -> str:
    action = engine.action_catalog.get(weapon_id)
    name = str(getattr(action, "display_name", "") or weapon_id)
    return re.sub(r"\s+attack$", "", name)


def channel_name(engine: Any, weapon_id: str) -> str:
    """The Channel's own name on the table ("Ironwood Spear", not "Ironwood Spear attack"). Shared with
    combat/ext/unmaking_forms.py, which prints the broken weapon when the form ends."""
    return _name(engine, weapon_id)


def _set(engine: Any, actor: Any, weapon_id: str, count: int, source: str) -> None:
    engine._remove_condition(actor, CRACK + _slug(weapon_id), source)
    if count > 0:
        engine._apply_condition(actor, CRACK + _slug(weapon_id), source, actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"weapon": weapon_id, "count": int(count),
                                      "label": f"{_name(engine, weapon_id)}: {count} Crack (it breaks at {SAFE_CRACK + 1})"})


def crack(engine: Any, actor: Any, weapon_id: str, amount: int, source: str) -> None:
    """``amount`` Crack on this weapon; at 3 it breaks (the rest of the current attack or technique still resolves)."""
    action = engine.action_catalog.get(weapon_id)
    if amount <= 0 or action is None or action.owner_id != actor.entity_id or ((action.parameters or {}).get("typed") or {}).get("artifact"):
        return
    count = cracks(actor, weapon_id) + int(amount)
    _set(engine, actor, weapon_id, count, source)
    engine._append_event("PASSIVE_TRIGGERED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"trigger": f"{_name(engine, weapon_id)} gains {amount} Crack ({count} in all)."})
    if count > SAFE_CRACK:
        destroy(engine, actor, weapon_id, source, why=f"it breaks at {count} Crack")


def remove_crack(engine: Any, actor: Any, weapon_id: str, amount: int, source: str) -> None:
    _set(engine, actor, weapon_id, max(0, cracks(actor, weapon_id) - int(amount)), source)


def destroy(engine: Any, actor: Any, weapon_id: str, source: str, why: str = "destroyed") -> None:
    from . import run_strict
    if False in run_strict('weapon_impairment_allowed', engine, actor, weapon_id, 'break', source):
        return
    engine._remove_condition(actor, CRACK + _slug(weapon_id), source)
    engine._apply_condition(actor, BROKEN + _slug(weapon_id), source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"disables_action": weapon_id, "label": f"{_name(engine, weapon_id)} is broken ({why})"})
    engine._append_event("PASSIVE_TRIGGERED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"trigger": f"{_name(engine, weapon_id)} breaks ({why}); it can't be used again this fight."})


def cracked_channels(actor: Any) -> dict[str, int]:
    """{weapon id: Crack} for this actor's weapons carrying Crack."""
    return {str((c.data or {}).get("weapon")): int((c.data or {}).get("count") or 0)
            for c in actor.conditions.values() if c.condition_id.startswith(CRACK)}


VESSEL_FORM = "condition:typed.stance.first_ruin_form"
DELAYED_CRACK = "condition:typed.unmaking_delayed_crack"


def vessel_form(actor: Any) -> Any:
    """The active First Ruin Form: External Vessel Mandate on this actor, if any."""
    return next((c for c in actor.conditions.values() if c.condition_id == VESSEL_FORM), None)


def delayed_crack(actor: Any) -> Any:
    """The held-back Crack condition of the First Ruin Form, if the actor has one. Shared with
    combat/ext/unmaking_forms.py, which settles it when the form ends."""
    return next((c for c in actor.conditions.values() if c.condition_id == DELAYED_CRACK), None)


def chosen_channel(actor: Any) -> str | None:
    """The held weapon the active First Ruin Form bound its qi to ("Choose one held weapon or implement"), or None.

    First Ruin Form: External Vessel Mandate delays the Crack of the CHOSEN Channel only, so the delay d6 and the settling
    Black Trace have to know which weapon that is. combat/ext/unmaking_forms.unmaking_form_channel records the choice on the
    form's own condition (one action id, a string, so a saved fight keeps it). A form taken before that effect existed (an
    older saved fight) has no recorded channel: the first Crack it holds back becomes the channel then, and any other
    weapon's Crack lands at once.
    """
    form = vessel_form(actor)
    weapon = str(((form.data if form is not None else None) or {}).get("channel") or "")
    if weapon:
        return weapon
    held = delayed_crack(actor)
    return str(((held.data if held is not None else None) or {}).get("weapon") or "") or None


def delay_or_crack(ctx: Any, weapon_id: str, amount: int) -> bool:
    """First Ruin Form: External Vessel Mandate -- a Crack the chosen Channel would gain is delayed on a 5 or 6.

    True when the Crack was delayed, False when it lands now. No form on this actor, or a weapon that is not the Channel the
    form chose: the Crack lands, as printed everywhere else ("when the chosen Channel would gain Crack"). The held-back
    Crack lives on its own condition, not on the form's: the form is gone by the time its expiry event reaches a hook, so
    its stored keys would already have been dropped. One integer and one action id, so a saved fight keeps them. Shared
    with combat/ext/unmaking_forms.py, which settles it when the form ends.
    """
    engine, actor = ctx.engine, ctx.actor
    channel = chosen_channel(actor)
    if vessel_form(actor) is None or amount <= 0 or (channel and str(weapon_id) != channel):
        return False
    from ..gate2_runtime_models import DiceSpec

    roll = engine.roller.roll(DiceSpec(count=1, sides=6, modifier=0), actor_id=actor.entity_id,
                              reason=f"VESSEL_DELAY:{ctx.source}")
    engine._record_roll(roll)
    if int(roll.total) < 5:
        return False
    held = delayed_crack(actor)
    data = dict((held.data if held is not None else None) or {})
    count = int(data.get("count") or 0) + int(amount)
    engine._remove_condition(actor, DELAYED_CRACK, ctx.source)
    engine._apply_condition(actor, DELAYED_CRACK, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"weapon": str(weapon_id), "count": int(count),
                                  "label": f"First Ruin Form: {_name(engine, weapon_id)} has {count} Crack waiting for the form to end"})
    ctx.rider(f"First Ruin Form: External Vessel Mandate delays {_name(engine, weapon_id)}'s {amount} Crack until the form ends.")
    return True


def is_broken(actor: Any, weapon_id: str) -> bool:
    """Whether this weapon is already a broken Channel (combat/gate2_engine.py stops offering a broken weapon)."""
    slug = _slug(weapon_id)
    return any(c.condition_id == BROKEN + slug for c in actor.conditions.values())


def settle_delayed_crack(engine: Any, actor: Any, source: str) -> tuple[str | None, bool]:
    """"when the form ends, all delayed Crack applies at once": the weapon id whose Crack was held back, and whether applying
    it broke that Channel ("If the Channel breaks when the form ends"). An old weapon that was already broken does not count:
    the Black Trace is printed for a Channel that dies as the form ends."""
    held = delayed_crack(actor)
    data = dict((held.data if held is not None else None) or {})
    count, weapon_id = int(data.get("count") or 0), data.get("weapon")
    if not count or not weapon_id:
        return None, False
    engine._remove_condition(actor, DELAYED_CRACK, source)
    weapon_id = str(weapon_id)
    broken_before = is_broken(actor, weapon_id)
    crack(engine, actor, weapon_id, count, f"{source}.delayed_crack")
    return weapon_id, not broken_before and is_broken(actor, weapon_id)


def _bonus(value: Any, numbers: dict[str, Any]) -> int:
    if value == "pb":
        return int(numbers.get("pb") or 2)
    if value == "cl":
        return int(numbers.get("cl") or 1)
    return int(value or 0)


def _self_text(spec: dict[str, Any], numbers: dict[str, Any]) -> str:
    bonus = _bonus(spec.get("bonus"), numbers)
    dice = f"{int(spec.get('count') or 0)}d{int(spec.get('sides') or 6)}" if spec.get("count") else ""
    return f"{dice}{' + ' if dice and bonus else ''}{bonus if bonus or not dice else ''}"


def _owns(engine: Any, actor: Any, kind: str) -> bool:
    from ..typed_reactions import _rows

    return any(row.get("kind") == kind for row in _rows(engine, actor.entity_id, "unmaking"))


def choices(engine: Any, actor: Any, options: list[dict[str, Any]], numbers: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    """The option ids offered for a printed cost list and their plain labels."""
    ids: list[str] = []
    labels: dict[str, str] = {}
    held = channels(engine, actor)
    for index, option in enumerate(options):
        if "strain" in option and STRAIN in actor.resources:
            key = f"{index}:strain"
            ids.append(key)
            labels[key] = f"Gain {int(option['strain'])} Black Vein Strain"
        elif "self" in option:
            key = f"{index}:self"
            ids.append(key)
            labels[key] = f"Take {_self_text(option['self'], numbers)} Ruin damage yourself"
        elif "crack" in option:
            for weapon_id in ([option["weapon"]] if option.get("weapon") else held):
                if option.get("weapon") and (engine.action_catalog.get(weapon_id) is None
                                             or ((engine.action_catalog[weapon_id].parameters or {}).get("typed") or {}).get("artifact")):
                    continue
                key = f"{index}:crack:{weapon_id}"
                ids.append(key)
                labels[key] = f"{_name(engine, weapon_id)} gains {int(option['crack'])} Crack ({cracks(actor, weapon_id)} now; it breaks at {SAFE_CRACK + 1})"
        elif "max_hp_loss" in option:
            key = f"{index}:max_hp_loss"
            ids.append(key)
            labels[key] = f"Lose {int(option['max_hp_loss'])} of your current and maximum Hit Points until you finish a Long Rest"
        elif "destroy" in option:
            for weapon_id in held:
                key = f"{index}:destroy:{weapon_id}"
                ids.append(key)
                labels[key] = f"Destroy {_name(engine, weapon_id)}"
        elif "gm" in option:
            key = f"{index}:gm"
            ids.append(key)
            labels[key] = f"{option['gm']} (the GM applies it)"
    return ids, labels


def _ai_rank(actor: Any, options: list[dict[str, Any]], key: str) -> tuple[int, int]:
    """The built-in AI's order among printed prices (never a rule): Strain short of a Ruin Backlash, a Crack short of breaking the
    weapon, then self-damage, then Strain that sets off a Backlash, a breaking Crack, destroying a weapon, and a GM-applied cost."""
    index, _, rest = key.partition(":")
    kind, _, weapon_id = rest.partition(":")
    option = options[int(index)]
    if kind == "strain":
        rank = 0 if int(actor.resources.get(STRAIN, 0)) + int(option["strain"]) < 6 else 3
    elif kind == "crack":
        rank = 1 if cracks(actor, weapon_id) + int(option["crack"]) <= SAFE_CRACK else 4
    else:
        rank = {"self": 2, "destroy": 5, "gm": 6, "max_hp_loss": 6}.get(kind, 7)
    return rank, int(index)


def pay(ctx: Any, options: list[dict[str, Any]], *, name: str, target: Any = None) -> str | None:
    """Ask the owner which printed cost to pay and pay it; returns the chosen option id (None when none could be paid)."""
    from .. import unmaking
    from .choice_prompt import action_context
    from .needle import CHOICE, ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    ids, labels = choices(engine, actor, options, ctx.numbers)
    if not ids or not actor.active:
        return None
    preferred = sorted(ids, key=lambda key: _ai_rank(actor, options, key))
    picked = ids if len(ids) == 1 else ask(engine, ctx.intent, checkpoint_id(engine, "UNMAKING_COST", ctx.source, actor.entity_id), actor, CHOICE + "unmaking_cost", ids,
                 labels=labels, name=name, preferred=preferred, prompt=f"{name}: {ctx.action.display_name} is resolved. Choose the price you pay.",
                 prompt_context=action_context(engine, actor, ctx.source, target or actor))
    choice = (picked or preferred[:1])[0]
    index, _, rest = choice.partition(":")
    option = options[int(index)]
    kind, _, weapon_id = rest.partition(":")
    if kind == "strain":
        unmaking.gain_strain_checked(ctx, int(option["strain"]), f"{ctx.source}.cost")
    elif kind == "self":
        spec = option["self"]
        amount = _bonus(spec.get("bonus"), ctx.numbers)
        if spec.get("count"):
            from ..gate2_runtime_models import DiceSpec

            roll = engine.roller.roll(DiceSpec(count=int(spec["count"]), sides=int(spec.get("sides") or 6), modifier=amount),
                                      actor_id=actor.entity_id, reason=f"RUIN_SELF_DAMAGE:{ctx.source}")
            engine._record_roll(roll)
            amount = int(roll.total)
        unmaking.self_damage(engine, actor, amount, f"{ctx.source}.cost")
    elif kind == "crack":
        crack_or_pay(ctx, weapon_id, int(option["crack"]))
    elif kind == "destroy":
        destroy(engine, actor, weapon_id, f"{ctx.source}.cost", why=f"{name} destroys it")
    elif kind == "max_hp_loss":
        from .maximum_hp_riders import max_hp_loss

        max_hp_loss(engine, actor, int(option["max_hp_loss"]), f"{ctx.source}.cost", name=name)
    elif kind == "gm":
        ctx.rider(f"GM: {name}: {option['gm']}.")
    if kind == "crack":
        ctx.rider(f"{name}: selected price before safeguards — {labels.get(choice, choice)}.")
    else:
        ctx.rider(f"{name}: {labels.get(choice, choice)}.")
    return choice


def crack_or_pay(ctx: Any, weapon_id: str, amount: int) -> None:
    """A Crack an Unmaking talent puts on one of your External Channels; Weapon Pays First may take its place."""
    engine, actor = ctx.engine, ctx.actor
    from . import transform_reduction

    action = engine.action_catalog.get(weapon_id)
    if amount <= 0 or action is None or action.owner_id != actor.entity_id or ((action.parameters or {}).get("typed") or {}).get("artifact"):
        return
    amount = transform_reduction("channel_crack_amount", amount, ctx, weapon_id)
    if amount == 0:
        return
    if _owns(engine, actor, "weapon_pays_first") and not actor.turn_flags.get("weapon_pays_first_used"):
        from .choice_prompt import action_context
        from .needle import CHOICE, ask, checkpoint_id

        pb = int(ctx.numbers.get("pb") or 2)
        breaking = cracks(actor, weapon_id) + amount > SAFE_CRACK
        labels = {"pay": f"Take {2 * pb} Ruin damage yourself instead (Weapon Pays First, once per turn)",
                  "crack": f"{_name(engine, weapon_id)} gains the Crack"}
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "WEAPON_PAYS_FIRST", ctx.source, weapon_id), actor, CHOICE + "weapon_pays_first",
                     ["pay", "crack"], labels=labels, preferred=["pay"] if breaking else ["crack"], name="Weapon Pays First",
                     prompt=f"Weapon Pays First: {_name(engine, weapon_id)} would gain {amount} Crack from {ctx.action.display_name}.",
                     prompt_context=action_context(engine, actor, ctx.source, actor))
        if (picked or ["pay" if breaking else "crack"])[0] == "pay":
            from .. import unmaking

            actor.turn_flags["weapon_pays_first_used"] = True
            unmaking.self_damage(engine, actor, 2 * pb, f"{ctx.source}.weapon_pays_first")
            ctx.rider(f"Weapon Pays First: {2 * pb} Ruin self-damage instead of the Crack.")
            return
    if delay_or_crack(ctx, weapon_id, amount):
        return
    crack(engine, actor, weapon_id, amount, f"{ctx.source}.crack")


@effect("unmaking_cost")
def unmaking_cost(ctx: Any, eff: dict[str, Any]) -> None:
    pay(ctx, list(eff.get("options") or []), name=str(eff.get("name") or ctx.action.display_name), target=ctx.target)
