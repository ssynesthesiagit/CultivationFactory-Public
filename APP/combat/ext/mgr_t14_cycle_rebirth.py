"""Five Elements' acquired knowledge and CL6 Cycle of Rebirth.

Only common Attunement acquisition/selection is implemented for the CL3 parent;
its individual benefits and later sibling powers remain with their own owners.
"""
from . import hook
from .condition_ownership import refresh_owned
from .needle import ask, checkpoint_id
from ..technique_alignment import ELEMENTS, eligible, powering_resource
from ..turn_uses import current_turn_key
from ..cultivation_access import effective_cl, alignment_available

PARENT = "tianxia.subpath.qi.five_elements_cultivator"
FIVE = PARENT + ".feature.fivefold_attunement"
CYCLE = PARENT + ".feature.cycle_of_rebirth"
STATE = "condition:typed.five_elements_attunement"
QI = "resource:core.qi"


@hook("compile_block")
def cycle_owner(block, spec, row, numbers):
    if block == "cycle_rebirth_owner" and row["feature_id"] == CYCLE and int(numbers["cl"]) >= 6:
        return [row]
    return None


@hook("compile_action")
def seal_alignment(action, info):
    if CYCLE not in info.get("owned_ids", ()):
        return None
    typed = action.parameters.get("typed") or {}
    source = (info.get("mechanics") or {}).get(typed.get("source")) or {}
    # These are declared authority fields, never words guessed from a name or
    # from damage. Sphere identity already travels with native compiled actions.
    fields = {k: source[k] for k in ("tags", "elemental_alignments") if source.get(k)}
    if typed.get("sphere"):
        fields["power_resource"] = powering_resource(action, info.get("owner_sheet"))
    if fields:
        return action.model_copy(update={"parameters": {**action.parameters, "typed": {**typed, **fields}}})
    return None


@hook("compile_passives")
def compile_knowledge(rows, info):
    from character_creation.acquisition_choices import from_sheet
    if FIVE not in info["owned_ids"]:
        return rows
    sheet = info.get("owner_sheet") or {}
    qi = next((p for p in (sheet.get("path_and_subpath") or {}).get("paths") or []
               if p.get("path_id") == "tianxia.path.qi_cultivation"), None)
    cl = int(qi.get("effective_cl", 0)) if qi is not None else int(info["numbers"].get("cl") or 0)
    start = from_sheet(sheet).get("five_elements_start")
    if cl < 3 or start not in ELEMENTS:
        return rows  # unacquired/missing owner input never fabricates knowledge
    cycle = int(CYCLE in info["owned_ids"] and cl >= 6)
    known = [ELEMENTS[(ELEMENTS.index(start) + i) % 5] for i in range(2 + cycle)]
    primary = ((sheet.get("ability_scores_and_statistics") or {}).get("primary_resource") or {}).get("name")
    return [*rows, {"block": "five_elements_knowledge", "feature_id": FIVE,
                   "starting_element": start, "known": ",".join(known), "cycle": cycle, "cl": cl,
                   "choice_owner": True,
                   "power_resource": {"Qi": QI, "Stamina": "resource:core.stamina",
                                      "Resonance": "resource:core.resonance"}.get(primary, "")}]


def knowledge(engine, actor):
    return next((r for r in getattr(engine, "typed_passive_rows", {}).get(actor.entity_id, ())
                 if r.get("block") == "five_elements_knowledge" and r.get("feature_id") == FIVE), None)


def state(actor):
    return next((c for c in actor.conditions.values() if c.condition_id == STATE
                 and c.source_actor_id == actor.entity_id), None)


def store(engine, actor, data, source=FIVE):
    refresh_owned(engine, actor, STATE, actor.entity_id, source)
    engine._apply_condition(actor, STATE, source, actor.entity_id, expires_on="UNTIL_REMOVED", data=data)


@hook("activation_accounting")
def accounting(engine):
    return True if any((row := knowledge(engine, actor)) and row["cycle"]
                         for actor in engine.state.actors.values()) else None


@hook("fight_setup_tasks")
def setup_tasks(engine):
    return [{"actor_id": a.entity_id, "source_id": FIVE} for a in engine.state.actors.values()
            if knowledge(engine, a) and state(a) is None]


@hook("fight_setup")
def setup(engine, actor, source, intent):
    row = knowledge(engine, actor)
    if source != FIVE or row is None:
        return None
    store(engine, actor, {"active": "", "known": row["known"], "used_turn": "",
                          "label": "Fivefold Attunement: choose a known element at the start of your turn"})
    return True


@hook("turn_start_choice")
def choose_turn(engine, actor):
    row, held = knowledge(engine, actor), state(actor)
    if row is None or held is None or effective_cl(engine, actor, row["cl"]) < 3:
        return
    options = row["known"].split(",")
    chosen = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "attunement", FIVE),
        actor, "choice:needle.five_elements_attunement", options,
        labels={k: k.title() + " Attunement" for k in options}, name="Fivefold Attunement", feature_id=FIVE,
        prompt=f"Fivefold Attunement: {actor.display_name}'s turn begins. Choose a known element to be active until your next turn starts. No action or Qi cost.",
        prompt_context={"source_definition_id": "system:turn_start", "action_name": "Start of turn",
                        "action_actor_id": actor.entity_id, "affected_id": actor.entity_id, "cost": "No action or Qi"},
        preferred=[held.data["active"]] if held.data["active"] in options else options[:1])
    if chosen:
        store(engine, actor, {**held.data, "active": chosen[0],
                             "label": chosen[0].title() + " Attunement (until your next turn starts)"})


@hook("activation_prepare")
def declare(action, engine, actor, candidate, intent):
    row, held = knowledge(engine, actor), state(actor)
    if row is None or held is None or not row["cycle"] or effective_cl(engine, actor, row["cl"]) < 6:
        return None
    typed = dict(action.parameters.get("typed") or {})
    # Generic reactions have no sealed action-catalog entry. Recover only this
    # owned Source's explicit metadata from the compiled authority, using the
    # same eligibility rules as foreground techniques.
    if not typed.get("sphere"):
        from ..typed_numbers import authority_mechanics
        source = authority_mechanics().get(typed.get("source")) or {}
        for field, source_field in (("sphere", "sphere_id"), ("tags", "tags"),
                                    ("elemental_alignments", "elemental_alignments")):
            if source.get(source_field):
                typed.setdefault(field, source[source_field])
    if typed.get("sphere") and not typed.get("power_resource"):
        typed["power_resource"] = powering_resource(action) or row["power_resource"]
    options = [e for e in eligible(typed) if alignment_available(engine, actor, e)]
    if not options:
        return None
    if len(options) == 1:
        chosen = options[0]
    else:
        affected = [engine.state.actors[k].display_name for k in candidate.target_ids if k in engine.state.actors]
        recipients = ", ".join(affected) or ("the chosen area" if candidate.destination else actor.display_name)
        chosen = ask(engine, intent, checkpoint_id(engine, "elemental_alignment", action.source_definition_id),
            actor, "choice:needle.elemental_alignment", options, labels={k: k.title() for k in options},
            name="Elemental Alignment", feature_id=CYCLE,
            prompt=f"Cycle of Rebirth: {actor.display_name} is activating {action.display_name}, affecting {recipients}. Declare one eligible element before its attacks, saves or healing resolve. No extra action or Qi cost.",
            prompt_context={"source_definition_id": action.source_definition_id, "action_name": action.display_name,
                            "action_actor_id": actor.entity_id, "affected_id": candidate.target_ids[0] if affected else actor.entity_id},
            preferred=[held.data["active"]] if held.data["active"] in options else options[:1])
        if not chosen:
            return None
        chosen = chosen[0]
    # This is an activation-local copy. Neither subsequent shifts nor other
    # actions can mutate the triggering technique's declaration or effects.
    return action.model_copy(update={"parameters": {**action.parameters, "typed": {
        **typed, "declared_element": chosen, "attunement_at_declaration": held.data["active"]}}})


@hook("technique_resolved")
def rebirth(ctx, receipt):
    row, held = knowledge(ctx.engine, ctx.actor), state(ctx.actor)
    if (row is None or not row["cycle"] or held is None or receipt.actor_id != ctx.actor.entity_id
            or effective_cl(ctx.engine, ctx.actor, row["cl"]) < 6):
        return
    typed = ctx.typed
    declared = typed.get("declared_element")
    # The printed trigger is "a Qi-powered technique matching your active
    # Attunement". A technique eligible for several elements therefore shifts
    # only when the declaration chose the element that was active; picking
    # another eligible element resolves normally and leaves the Attunement alone.
    if (declared not in eligible(typed) or declared != typed.get("attunement_at_declaration")
            or declared != held.data.get("active")
            or (typed.get("power_resource") or powering_resource(ctx.action)) != QI
            or any(amount > 0 for _resource, amount in receipt.refunds)
            or held.data.get("used_turn") == current_turn_key(ctx.engine)):
        return
    if not alignment_available(ctx.engine, ctx.actor, declared):
        return
    known = set(row["known"].split(","))
    following = next(ELEMENTS[(ELEMENTS.index(declared) + i) % 5] for i in range(1, 6)
                     if ELEMENTS[(ELEMENTS.index(declared) + i) % 5] in known)
    store(ctx.engine, ctx.actor, {**held.data, "active": following,
        "used_turn": current_turn_key(ctx.engine),
        "label": following.title() + " Attunement (until your next turn starts)"}, CYCLE)
    ctx.engine._append_event("PASSIVE_TRIGGERED", CYCLE, actor_id=ctx.actor.entity_id,
        payload={"from_element": declared, "to_element": following,
                 "log": f"Cycle of Rebirth: after {ctx.action.display_name} finishes, {ctx.actor.display_name} shifts from {declared.title()} to {following.title()}. No action or Qi cost."})


@hook("technique_resolution_enabled")
def needs_completion(ctx):
    row = knowledge(ctx.engine, ctx.actor)
    return True if row and row["cycle"] else None
