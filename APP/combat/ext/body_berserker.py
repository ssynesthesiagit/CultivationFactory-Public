"""Berserker's base Adrenaline rule (body 2026-09-29): never captured as its own mechanic in the typed authority (it is
a "### Adrenaline" rules paragraph ahead of the individual talent entries, not a talent heading of its own -- the same
kind of gap gu_berserker.py already documented for Batter), so every "while Adrenaline is active" talent (Berserk,
Atavism, Executioner, Juggernaut...) was compiling as an unconditional, always-on bonus with no cost. Printed rule:

  "At the start of your turn, choose whether to enter Adrenaline until the start of your next turn. While Adrenaline
  is active: take a -2 AC penalty; gain the benefit of one Adrenaline talent you know. Unless a talent says
  otherwise, activate only one Adrenaline talent at a time."

A free toggle, kept until changed (Black-Vein-Palm style): "Adrenaline: <talent>" per owned Adrenaline talent, plus
"Adrenaline: none (no Adrenaline talent, no -2 AC penalty)" (option id "off"). Choosing one applies the -2 AC penalty (the `ac` hook) and a marker condition naming which talent
is active, read by that talent's own mechanism. The printed capacity is one talent at a time; a talent that grants a
second slot (War-God Incarnation: "activate two Adrenaline talents at once", DOUBLE_STATES) is the only exception, and
`reconcile` puts the fighter back to one talent when that state ends -- through the fighter's own persisted Adrenaline
markers, so an old saved fight reconciles on its own and no other character's Adrenaline is touched.

Only Berserk's flat damage reduction is mechanized here (combat/rules/feature_blocks.d/body.json's "defense" block,
extended with a new "reduction_before_resistance" kind and a generic "requires_condition" gate in
combat/typed_reactions.py -- both small, reusable additions, not Berserker-specific). Atavism (a creature-type
reclassification for "supernatural effects that care about creature type", which this table never tracks either way),
still has no real effect to gate; its Adrenaline choice exists so "only one Adrenaline talent at a time" stays correctly modelled, and
its own GM-only rider says plainly what the table cannot enforce. Executioner's reroll of a missed weapon attack is
combat/ext/d20_rewrite_attacks.py (the d20_result hook), which reads this module's "Adrenaline: Executioner" marker. Juggernaut's two benefits (ignore difficult terrain, a
Speed floor) are motion rows that hold while the marker condition below is on the fighter (combat/motion.py, auto-lane5;
combat/rules/feature_blocks.d/auto_lane5.json).
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

ADRENALINE_TALENTS = {
    "TAL_BERSERKER_BERSERK": ("berserk", "Berserk"),
    "TAL_BERSERKER_ATAVISM": ("atavism", "Atavism"),
    "TAL_BERSERKER_EXECUTIONER": ("executioner", "Executioner"),
    "TAL_BERSERKER_JUGGERNAUT": ("juggernaut", "Juggernaut"),
    # rider lane C2 (2026-09-30): two more Adrenaline talents; their "while active" benefits are combat/ext/berserker.py's
    "TAL_BERSERKER_MARAUDER": ("marauder", "Marauder"),
    "TAL_BERSERKER_UNYIELDING_ADVANCE": ("unyielding_advance", "Unyielding Advance"),
}
ACTIVE = "condition:typed.body_adrenaline_active"
# Printed lines that change how many Adrenaline talents run at once, and which of them the -2 AC penalty applies to.
# War-God Incarnation: "activate two Adrenaline talents at once" and "ignore the AC penalty from one active Adrenaline
# talent"; Court of the Unbroken Warpath: "activate one Adrenaline talent without taking the normal -2 AC penalty".
# Data, not code: a talent that grants a second Adrenaline slot or waives the penalty adds one line here.
DOUBLE_STATES = ("war_god_incarnation",)
AC_WAIVED_STATES = ("court_of_the_unbroken_warpath", "war_god_incarnation")
# The conditions whose end reconciles a two-talent Adrenaline back to one (see reconcile).  The state's own condition id
# spells each name, so no state is stored for the reconciliation itself.
DOUBLE_IDS = tuple(f"condition:typed.state.{name}" for name in DOUBLE_STATES)
RIDERS = {
    "atavism": "Atavism: while Adrenaline is active, count as your normal creature type or Beast for supernatural "
              "effects that care about creature type, whichever is more favorable -- GM-adjudicated (no creature-type "
              "interactions are tracked on this table).",
}


@hook("compile_actions")
def adrenaline_choices(info: dict[str, Any]) -> list[Any] | None:
    owned = [(key, label, mid) for mid, (key, label) in ADRENALINE_TALENTS.items() if mid in info["owned_ids"]]
    if not owned:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    make = lambda suffix, label, choice: ActionDefinition(  # noqa: E731
        source_definition_id=f"action:typed.{info['short']}.adrenaline.{suffix}", display_name=f"Adrenaline: {label}",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"setting_only": True, "typed": {"effects": [{"type": "body_adrenaline_choice", "choice": choice}], "numbers": info["numbers"],
                              "duration": {"kind": "instant"}, "riders": [], "adrenaline_status_receipt": 1}, "expected_damage": 0, "player_only": True})
    return [*(make(key, label, key) for key, label, _mid in owned), make("off", "none (no Adrenaline talent, no -2 AC penalty)", "off")]


@effect("body_adrenaline_choice")
def adrenaline_choice(ctx: Any, eff: dict[str, Any]) -> None:
    """Pick which Adrenaline talent(s) run, or turn Adrenaline off.

    One talent at a time, unless a printed talent grants a second slot.  Pressing the button of a talent that is already
    running turns only THAT one off and leaves the others running; turning the last one off, or choosing the
    no-talent option, ends
    Adrenaline altogether, so the ACTIVE marker (which is what the -2 AC penalty reads) always agrees with the set of
    talent markers actually on the fighter.  Ending or expiring the talent that granted the second slot reconciles the
    same way (see :func:`reconcile`).
    """
    def status(text):
        if ctx.typed.get("adrenaline_status_receipt") == 1:
            note(ctx.engine, ctx.source, ctx.actor, text)
        else:
            ctx.rider(text)

    choice = str(eff.get("choice") or "off")
    engine, actor = ctx.engine, ctx.actor
    running = running_talents(actor)
    engine._remove_condition(actor, ACTIVE, ctx.source)
    for key, _label in ADRENALINE_TALENTS.values():
        engine._remove_condition(actor, f"condition:typed.body_adrenaline_{key}", ctx.source)
    if choice == "off":
        status("Adrenaline ended.")
        return
    if choice in running:  # pressing the running talent's own button turns that one off
        running = [key for key in running if key != choice]
    else:
        running = [choice, *[key for key in running if key != choice]][:capacity(engine, actor)]
    if not running:
        status("Adrenaline ended (no talent left running).")
        return
    engine._apply_condition(actor, ACTIVE, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Adrenaline active (-2 AC)" if not _waived(engine, actor) else "Adrenaline active",
                                  "choices": list(reversed(running))})
    labels = []
    for key, label in ADRENALINE_TALENTS.values():
        if key not in running:
            continue
        engine._apply_condition(actor, f"condition:typed.body_adrenaline_{key}", ctx.source, actor.entity_id,
                                expires_on="UNTIL_REMOVED", data={"label": f"Adrenaline: {label}"})
        labels.append(label)
    waived = _waived(engine, actor)
    status(f"Adrenaline running: {', '.join(labels)}" + (" (no AC penalty)." if waived else " (-2 AC)."))
    if choice in RIDERS:
        ctx.rider(RIDERS[choice])


def running_talents(actor: Any) -> list[str]:
    """The Adrenaline talents whose markers are on this fighter, in the printed order of ADRENALINE_TALENTS."""
    present = {c.condition_id for c in actor.conditions.values()}
    return [key for key, _label in ADRENALINE_TALENTS.values() if f"condition:typed.body_adrenaline_{key}" in present]


def marker(key: str) -> str:
    """The condition id that marks Adrenaline talent ``key`` as running."""
    return f"condition:typed.body_adrenaline_{key}"


def _selected_order(actor: Any) -> list[str]:
    """The running talents in the order the fighter SELECTED them, oldest first.

    The per-talent markers are rewritten on every selection and are always written in ADRENALINE_TALENTS' printed order,
    so their own order cannot say which talent was picked last.  The ACTIVE marker therefore carries that order as plain
    strings (integers and strings only, so a saved fight reloads it unchanged), which is what "the most recently activated
    talent keeps running" means after the second slot goes away.
    """
    present = {c.condition_id for c in actor.conditions.values()}
    for condition in actor.conditions.values():
        if condition.condition_id != ACTIVE:
            continue
        keys = [str(item) for item in (condition.data or {}).get("choices") or []]
        keys = [key for key in keys if marker(key) in present]
        if keys:
            return keys
    return []  # a saved fight written before this order was kept: fall back to the markers' own order


def capacity(engine: Any, actor: Any) -> int:
    """How many Adrenaline talents may run at once (one, unless a printed talent grants a second slot)."""
    from . import states

    return 2 if states.active(engine, actor, *DOUBLE_STATES) else 1


def _waived(engine: Any, actor: Any, *, remaining: set[str] | None = None) -> bool:
    """Whether the -2 AC penalty is waived for whoever is Adrenaline right now.

    ``remaining`` is the set of those printed states that will still be on the fighter once the condition currently
    leaving has actually gone.  :func:`reconcile` presents its result while that condition is still present (the engine
    removes it only after the callback returns), so reading the fighter as it is at that moment promises a waived
    penalty that the very next AC query no longer grants; it passes what is left instead, so the label agrees with the
    AC the fighter really has.
    """
    from . import states

    if remaining is None:
        return bool(states.active(engine, actor, *AC_WAIVED_STATES)) or capacity(engine, actor) > 1
    return bool(remaining & set(AC_WAIVED_STATES)) or len(remaining & set(DOUBLE_STATES)) > 1


@hook("effect_expiring")
def reconcile(engine: Any, holder: Any, condition: Any) -> None:
    """A talent that grants the second Adrenaline slot ending drops the set back to one talent.

    War-God Incarnation ("activate two Adrenaline talents at once") is the only printed source of a second slot today, so
    it is the one whose end has something to reconcile.  The most recently SELECTED talent keeps running (:func:`_selected_order`,
    which survives a commit and reload), the ACTIVE marker is rewritten so the -2 AC penalty and the label on it always
    agree with the set and with the states that are left, and a fighter left with no talent at all loses Adrenaline.
    Nothing extra is stored for the reconciliation itself: the Adrenaline markers and the ACTIVE marker's own choice
    order already on the fighter are the state, so a saved fight reconciles on its own.
    """
    if getattr(condition, "condition_id", "") not in DOUBLE_IDS:
        return
    on_fighter = {c.condition_id for c in holder.conditions.values()}
    leaving = condition.condition_id[len("condition:typed.state."):]
    still = [name for name in DOUBLE_STATES
             if name != leaving and f"condition:typed.state.{name}" in on_fighter]
    keep = 2 if still else 1
    names = {key: label for key, label in ADRENALINE_TALENTS.values()}
    # Read the selection order BEFORE the ACTIVE marker is rewritten: it is where that order is kept.
    order = _selected_order(holder) or [c.condition_id[len(marker("")):] for c in holder.conditions.values()
                                        if c.condition_id.startswith(marker(""))]
    engine._remove_condition(holder, ACTIVE, condition.source_definition_id)
    kept: list[str] = []
    for key in reversed(order):
        if key in kept or key not in names:
            continue
        if len(kept) >= keep:
            engine._remove_condition(holder, marker(key), condition.source_definition_id)
            continue
        kept.append(key)
    from . import note

    if not kept:
        note(engine, condition.source_definition_id, holder,
             "War-God Incarnation ended, so Adrenaline ended too: no Adrenaline talent is running.")
        return
    note(engine, condition.source_definition_id, holder,
         f"War-God Incarnation ended, so only one Adrenaline talent runs at a time again: {names[kept[0]]}.")
    remaining = {name for name in AC_WAIVED_STATES
                 if name != leaving and f"condition:typed.state.{name}" in on_fighter}
    engine._apply_condition(holder, ACTIVE, condition.source_definition_id, holder.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Adrenaline active" if _waived(engine, holder, remaining=remaining) else "Adrenaline active (-2 AC)",
                                  "choices": list(reversed(kept))})


@hook("ac")
def adrenaline_ac_penalty(engine: Any, actor: Any) -> int | None:
    """-2 AC while Adrenaline runs, unless a printed talent waives it for the fighters who have one
    (Court of the Unbroken Warpath, War-God Incarnation)."""
    from . import states

    if not any(c.condition_id == ACTIVE for c in actor.conditions.values()):
        return None
    return None if _waived(engine, actor) else -2
