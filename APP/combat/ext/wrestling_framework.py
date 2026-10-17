"""Wrestling's framework lines (rider lane C13, 2026-09-30; owner: "i want everything we can automated, keep going until its only the
non-combat ones left"). Printed: Sphere Compendium, Wrestling -- Applying a Slam, Grappling Reminder, Wrestling Save DC and Escape DC.
Apply a Slam's buttons are combat/ext/gu_wrestling.py; the holds they leave are combat/ext/wrestling.py.

  Punish the Escape Attempt  "When a creature fails an Action check to escape one of your grapples, use your Reaction to apply one Slam
                             talent to it." A failed Escape grapple check by a creature you hold offers your Slams (the Apply a Slam
                             buttons you could afford) for your Reaction, asked (you may decline; the built-in AI takes the first). The
                             Slam runs exactly as its button does -- its effects, its Martial Focus cost -- against the escaper.
  The Slam ends with the grip "the Slam lasts until the start of your next turn or until the grapple ends, whichever happens first": when
                             your grapple on a creature ends, what your Slams left on it until the start of your next turn ends too (a
                             Slam whose own text gives another duration keeps it). Choke Hold's breathing is combat/ext/wrestling.py's.
  Grappler Incapacitated     Grappling Reminder: "A grapple also ends if: the grappler becomes Incapacitated". The moment a creature
                             becomes Incapacitated, Paralyzed, Petrified, Stunned or Unconscious, or drops to 0 HP, every grapple and pin
                             it physically holds ends. Magical conditions named Grappled keep their own lifetimes;
                             hand_occupancy and physical_holds provide the shared source-qualified classifiers.
                             (The engine already ends a grapple at a turn start once the creature is out of reach.)
  Wrestling Save DC          "Your default Wrestling Save DC and grapple escape DC are: 8 + Strength modifier + Proficiency Bonus": a
                             Wrestling talent's save DC (and so the escape DC of a grapple it makes) uses Strength, unless its action
                             already carries its own DC.

Hooks: compile_action (Wrestling actions only), event (failed escape checks; a grapple ending; a grappler incapacitated), turn_start (a
grapple that ended at a turn start). Inert for creatures without a grapple or a Wrestling action.
"""

from __future__ import annotations

from typing import Any

from . import hook, note

WRESTLING = "tianxia.sphere.wrestling"
GRAPPLED, PINNED = "condition:typed.grappled", "condition:typed.pinned"
SLAM_MARK = ".granted.slam."
REMINDER = "WRESTLING_BASE_GRAPPLING_REMINDER"
APPLYING = "WRESTLING_BASE_APPLYING_A_SLAM"
INCAPACITATING = {"condition:typed." + name for name in ("incapacitated", "paralyzed", "petrified", "stunned", "unconscious")}
SYSTEM_EXPIRATION = "system:combat.expiration"


# ------------------------------------------------------------------------------------------------ Wrestling Save DC
def _wrestling(typed: dict[str, Any]) -> bool:
    return typed.get("sphere") == WRESTLING or str(typed.get("source") or "").startswith(("TAL_WRESTLING_", "WRESTLING_BASE_"))


@hook("compile_action")
def wrestling_save_dc(action: Any, info: dict[str, Any]) -> Any:
    typed = (action.parameters or {}).get("typed") or {}
    numbers = typed.get("numbers") or {}
    general = (info.get("numbers") or {}).get("save_dc")
    if not _wrestling(typed) or numbers.get("save_dc") is None or numbers.get("save_dc") != general:
        return None  # not a Wrestling action, or its own DC already
    dc = 8 + int(info.get("pb") or 2) + int((info.get("mods") or {}).get("STR", 0))
    if dc == general:
        return None
    import copy

    params = copy.deepcopy(action.parameters)
    params["typed"]["numbers"]["save_dc"] = dc
    return action.model_copy(update={"parameters": params})


# ------------------------------------------------------------------------------------------------ Punish the Escape Attempt
def _slams(engine: Any, grappler: Any, escaper: Any) -> list[Any]:
    from .gu_wrestling import slam_eligible
    out = []
    for action in engine.action_catalog.values():
        if action.owner_id != grappler.entity_id or SLAM_MARK not in action.source_definition_id:
            continue
        if slam_eligible(engine, grappler, escaper, action, reaction=True):
            out.append(action)
    return sorted(out, key=lambda a: (bool(a.costs), a.display_name))


def _holds(engine: Any, grappler: Any, creature: Any) -> bool:
    return any(c.condition_id == GRAPPLED and c.source_actor_id == grappler.entity_id for c in creature.conditions.values())


def punish(engine: Any, grappler: Any, escaper: Any) -> None:
    from ..typed_executor import condition_rules
    from .rider_choices import pick

    if not grappler.active or not grappler.reaction_available or any(r.get("no_reactions") for r in condition_rules(grappler)):
        return
    slams = _slams(engine, grappler, escaper)
    if not slams or not escaper.active or not _holds(engine, grappler, escaper):
        return
    labels = {a.source_definition_id: f"{a.display_name} (your Reaction)" for a in slams}
    chosen = pick(engine, grappler, "wrestling_punish", "Punish the Escape Attempt", list(labels), subject=escaper, labels=labels,
                  preferred=[slams[0].source_definition_id], trigger=f"{escaper.display_name} fails to escape your grapple")
    if not chosen:
        return
    action = engine.action_catalog[chosen[0]]
    from .gu_wrestling import slam_eligible
    if not slam_eligible(engine, grappler, escaper, action, reaction=True):
        return
    from ..typed_executor import Context, run_effects

    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, grappler, action.source_definition_id, independent=True):
        grappler.reaction_available = False
        engine._spend_costs(grappler, action.costs, action.source_definition_id)
        note(engine, APPLYING, grappler, f"Punish the Escape Attempt (Reaction): {grappler.display_name} uses {action.display_name} on "
                                         f"{escaper.display_name}.", (escaper,))
        typed = action.parameters["typed"]
        ctx = Context(engine, grappler, action, getattr(engine, "_active_intent", None), typed, [escaper], escaper, {})
        run_effects(ctx, list(typed.get("effects") or []))


@hook("event")
def escape_failed(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CHECK_ROLLED" or (kwargs.get("payload") or {}).get("success") is not False or not engine.events:
        return
    if not str(engine.events[-1].source_definition_id or "").endswith(".escape_grapple"):  # the Escape grapple Action's check
        return
    escaper = engine.state.actors.get(kwargs.get("actor_id") or "")
    if escaper is None:
        return
    grapplers = sorted({c.source_actor_id for c in escaper.conditions.values() if c.condition_id in (GRAPPLED, PINNED)})
    for grappler_id in grapplers:
        grappler = engine.state.actors.get(grappler_id)
        if grappler is not None and grappler is not escaper:
            punish(engine, grappler, escaper)


# ------------------------------------------------------------------------------------------------ the Slam ends with the grip
def release_slams(engine: Any, creature: Any, source: str) -> None:
    """End what a Slam left on ``creature`` until the start of its slammer's next turn, once that slammer no longer grapples it."""
    from .condition_ownership import remove_instance

    for iid, row in list(creature.conditions.items()):
        if SLAM_MARK in row.source_definition_id and row.expires_on == "START_OF_SOURCE_NEXT_TURN" and row.condition_id != GRAPPLED \
                and not row.condition_id.startswith("condition:typed.chok") and not _holds(engine, engine.state.actors.get(row.source_actor_id) or creature, creature):
            remove_instance(engine, creature, iid, source)
    for mid, mod in list(creature.modifiers.items()):
        if SLAM_MARK in mod.source_definition_id and mod.expires_on == "START_OF_SOURCE_NEXT_TURN" \
                and not _holds(engine, engine.state.actors.get(mod.source_actor_id) or creature, creature):
            engine._remove_modifier_instance(creature, mid, source,
                payload={"modifier_id": mid, "reason": "GRAPPLE_ENDED"}, expected=mod)


@hook("event")
def grapple_ended(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CONDITION_REMOVED" or (kwargs.get("payload") or {}).get("condition_id") != GRAPPLED:
        return
    for target_id in kwargs.get("target_ids") or ():
        creature = engine.state.actors.get(target_id)
        if creature is not None:
            release_slams(engine, creature, APPLYING)


@hook("turn_start")
def sweep(engine: Any, actor: Any) -> None:
    for creature in engine.state.actors.values():
        if any(SLAM_MARK in row.source_definition_id for row in creature.conditions.values()) or \
                any(SLAM_MARK in mod.source_definition_id for mod in creature.modifiers.values()):
            release_slams(engine, creature, APPLYING)


# ------------------------------------------------------------------------------------------------ Grappler Incapacitated
def _down(creature: Any) -> bool:
    return not creature.active or creature.life_state is not None or any(c.condition_id in INCAPACITATING for c in creature.conditions.values())


def _physical_hold(engine: Any, row: Any) -> bool:
    from .hand_occupancy import physical_row
    from .physical_holds import source

    return physical_row(engine, row) or source(engine, row)[0]


def let_go(engine: Any, grappler: Any) -> None:
    from .condition_ownership import remove_instance
    from .grapple_parts import maintains_on_incapacity

    if maintains_on_incapacity(engine, grappler):
        return

    for creature in engine.state.actors.values():
        held = [iid for iid, row in creature.conditions.items() if row.condition_id in (GRAPPLED, PINNED)
                and row.source_actor_id == grappler.entity_id and _physical_hold(engine, row)]
        for iid in held:
            remove_instance(engine, creature, iid, REMINDER)
        if held:
            note(engine, REMINDER, grappler, f"{grappler.display_name} is Incapacitated: its grapple on {creature.display_name} ends.", (creature,))
            release_slams(engine, creature, REMINDER)


@hook("event", nested=True)
def grappler_incapacitated(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type not in ("CONDITION_APPLIED", "DAMAGE_COMMITTED", "LIFE_STATE_CHANGED"):
        return
    for target_id in kwargs.get("target_ids") or ((kwargs.get("actor_id"),) if event_type == "LIFE_STATE_CHANGED" else ()):
        grappler = engine.state.actors.get(target_id or "")
        if grappler is None or not _down(grappler):
            continue
        if any(row.condition_id in (GRAPPLED, PINNED) and row.source_actor_id == grappler.entity_id and _physical_hold(engine, row)
               for creature in engine.state.actors.values() for row in creature.conditions.values()):
            let_go(engine, grappler)
