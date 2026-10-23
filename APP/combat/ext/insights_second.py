"""Source-bound combat clauses for the second alphabetical Insight group.

Only sealed feature rows confer ownership. Choices use the ordinary transaction
transport, so previews, table answers, saved journals and replay agree.
"""
from . import hook, note, effect
from .passive_rows import row_of

BLOCK = "insights_second"
DEBT = "insight.debt-collector"
DAO = "insight.dao-guard-veteran"
PEARL = "insight.dragon-pearl-heart"
PARRY = "tianxia.talent.sabers.guard_cutting_parry"
PEARL_FLIGHT = "condition:typed.dragon_pearl_flight"
SNARE = "insight.cut-the-snare"
DUAL = "insight.dual-mandate-adept"


@hook("compile_action")
def dual_mandate(action, info):
    from .cp_pools import path_pool_ids
    if (DUAL not in info["owned_ids"] or
            (action.parameters.get("typed") or {}).get("source") != "tianxia.talent.imbuement.layered_mandate"):
        return None
    costs = tuple((pool, max(0, amount - 1) if pool in path_pool_ids() else amount)
                  for pool, amount in action.costs)
    name = action.display_name.replace("1 CP", "0 CP")
    params = {**action.parameters, "description": str(action.parameters.get("description") or "").replace("1 CP", "0 CP")}
    return action.model_copy(update={"costs": tuple((p, n) for p, n in costs if n),
                                     "display_name": name, "parameters": params})


def bindings(engine, actor):
    from .physical_holds import source
    return {iid: c for iid, c in actor.conditions.items()
            if source(engine, c)[0] and int(c.data.get("escape_dc") or 0) > 0}


@hook("compile_action")
def snare_action(action, info):
    typed = action.parameters.get("typed") or {}
    if typed.get("source") == SNARE:
        key = str((info["owner_sheet"].get("identity") or {}).get("key_ability") or "INT").upper()[:3]
        return action.model_copy(update={"parameters": {**action.parameters, "insight_snare": 1,
                                     "typed": {**typed, "cut_snare_key_ability": key}}})
    return None


@hook("candidate_allowed")
def snare_candidate(engine, actor, candidate, action):
    if (getattr(action, "parameters", None) or {}).get("insight_snare"):
        return bool(bindings(engine, actor)) and not used(actor, SNARE)
    return None


def binding_labels(engine, holds):
    """One distinguishable button per binding, naming what holds the creature and who holds it.

    Cut the Snare ends exactly one grip, so the table must be able to tell two grips apart
    before it chooses. Two grips of the same Difficulty Class otherwise print the same
    button while their instance ids select different holds, and a player can free the
    wrong grip and stay bound by the one they meant.
    The name and Difficulty Class come from the catalog action and the holding actor; the
    instance id stays in the transport and is never printed. Bindings whose names would
    still repeat are numbered in a stable order, so no two offered buttons are identical.
    """
    described = {}
    for iid, condition in holds.items():
        kind = condition.condition_id.removeprefix("condition:typed.").replace("_", " ").capitalize() or "Binding"
        action = engine.action_catalog.get(condition.source_definition_id)
        effect_name = str(getattr(action, "display_name", None) or "").strip() or f"an unnamed {kind.lower()}"
        holder = engine.state.actors.get(condition.source_actor_id)
        holder_name = str(getattr(holder, "display_name", None) or "").strip() or "an unknown creature"
        described[iid] = (f"{effect_name} from {holder_name} ({kind}, "
                          f"DC {int(condition.data.get('escape_dc') or 0)})")
    repeats = {}
    for text in described.values():
        repeats[text] = repeats.get(text, 0) + 1
    counted, ordered = {}, {}
    for iid in sorted(described):
        text = described[iid]
        if repeats[text] > 1:
            counted[text] = counted.get(text, 0) + 1
            text = f"{text}, grip {counted[text]}"
        ordered[iid] = text
    return ordered


@effect("insight_cut_snare")
def cut_snare(ctx, row):
    from .needle import ask, checkpoint_id
    from .physical_holds import end_hold
    from .escape_checks import resolve_escape_check
    from .contests import printed_modifier
    holds = bindings(ctx.engine, ctx.actor)
    if not holds or used(ctx.actor, SNARE):
        return
    labels = binding_labels(ctx.engine, holds)
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "Cut the Snare", ctx.actor.entity_id),
                 ctx.actor, "choice:needle.cut_snare_hold", list(holds), allow_decline=False,
                 name="Cut the Snare", feature_id=SNARE, labels=labels,
                 prompt=f"Cut the Snare: {ctx.actor.display_name} is held by {len(holds)} physical "
                        f"{'binding' if len(holds) == 1 else 'bindings'}. Choose one to try to end. "
                        "Bonus Action; no resource cost.")
    if not chosen:
        return
    checks = {"STR": {"ability": "STR"}, "DEX": {"ability": "DEX"}, "cultivation": {"kind": "cultivation"}}
    bonuses = {key: printed_modifier(ctx.engine, ctx.actor, spec, numbers=ctx.numbers)
               for key, spec in checks.items()}
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "Cut the Snare check", chosen[0]),
                   ctx.actor, "choice:needle.cut_snare_check", list(checks), allow_decline=False,
                   preferred=sorted(checks, key=lambda k: -bonuses[k]), name="Cut the Snare", feature_id=SNARE,
                   labels={key: f"{ {'STR': 'Strength', 'DEX': 'Dexterity', 'cultivation': 'Cultivation'}[key]} check ({bonuses[key]:+d})" for key in checks},
                   prompt=f"Cut the Snare: {labels[chosen[0]]} holds {ctx.actor.display_name}. "
                          "Choose Strength, Dexterity, or a Cultivation Check. A success ends this binding; "
                          "then a 10-minute recovery is required before using Cut the Snare again.")
    if not selected:
        return
    held = holds[chosen[0]]
    key = selected[0]
    ability = key if key in {"STR", "DEX"} else str(ctx.typed.get("cut_snare_key_ability") or "INT")
    if resolve_escape_check(ctx, {"bonus": bonuses[key]}, int(held.data["escape_dc"]), [held],
                            ("grappled", "restrained"), check_name="Cut the Snare",
                            check_ability=ability, check_skill="Cultivation" if key == "cultivation" else None):
        end_hold(ctx, chosen[0])
        mark_used(ctx.engine, ctx.actor, SNARE)
        note(ctx.engine, SNARE, ctx.actor,
             f"Cut the Snare: {labels[chosen[0]]} ended. Recover for 10 minutes before using it again.")


def used(actor, feature):
    if feature == DEBT:
        from .karma_insights import debt_collection_used
        return debt_collection_used(actor)
    return any(c.condition_id == "condition:typed.insight_used" and c.source_definition_id == feature
               for c in actor.conditions.values())


def mark_used(engine, actor, feature):
    engine._apply_condition(actor, "condition:typed.insight_used", feature, actor.entity_id,
                            expires_on="UNTIL_REMOVED", data={"label": "Used for this scene"})


@hook("compile_block")
def compile_row(block, spec, row, numbers):
    if block != BLOCK:
        return None
    return [{**row, "kind": row["feature_id"], "pb": int(numbers["pb"]),
             "choice_owner": 1, "player_outcome": spec["outcome"]}]


def owned(engine, actor, feature):
    return row_of(engine, actor.entity_id, BLOCK, feature) if actor is not None else None


@hook("damage_reduction_bonus")
def dao_parry(engine, owner, protected, attacker, row):
    if row.get("feature_id") == PARRY and owned(engine, owner, DAO):
        return 2
    return None


def lightning_damage(engine, action, first_event):
    """Every creature this use's own damage packets actually hurt, in packet order.

    Native DAMAGE_COMMITTED is one packet per creature, so an area that hurts several
    creatures publishes several events; the printed Release names the creatures the
    triggering effect damaged, not whichever packet the journal happened to record
    first. Reading the journal over this use's whole event window keeps the choice
    independent of recipient order.
    """
    hurt = []
    for event in engine.events[first_event:]:
        payload = event.payload or {}
        if (event.event_type != "DAMAGE_COMMITTED" or event.actor_id != action.owner_id
                or event.source_definition_id != action.source_definition_id
                or str(payload.get("damage_type") or "").upper() not in {"LIGHTNING", "THUNDER"}
                or int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0) <= 0):
            continue
        for target_id in event.target_ids:
            if target_id not in hurt:
                hurt.append(target_id)
    return [aid for aid in hurt if (engine.state.actors.get(aid) or None) is not None
            and engine.state.actors[aid].entity_id != action.owner_id]


@hook("technique_used")
def dragon_pearl(ctx):
    """Dragon-Pearl Release, offered once per use at the technique's completion.

    ``technique_used`` runs after the whole effect resolved, so a cone that damaged
    two creatures offers one Release naming both, rather than a dialog per recipient
    whose first answer spent the scene's single use.
    """
    from .needle import ask, checkpoint_id
    from ..typed_executor import run_effects
    engine, actor, action = ctx.engine, ctx.actor, ctx.action
    row = owned(engine, actor, PEARL)
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    source = str(typed.get("option_of") or typed.get("source") or "")
    if (not row or not actor.active or used(actor, PEARL)
            or not source.startswith(("tianxia.subpath.body.", "tianxia.path.body_refining.feature."))):
        return
    recipients = lightning_damage(engine, action, ctx.technique_event_start if ctx.technique_event_start is not None
                                  else len(engine.events))
    if not recipients:
        return
    options = ["flight"]
    labels = {"flight": "Gain Fly Speed 30 feet until this turn ends"}
    stamina = "resource:core.stamina"
    if stamina in actor.resources:
        options.insert(0, "stamina")
        labels["stamina"] = "Regain 2 Stamina, up to your maximum"
    from ..senses import perceives
    automatic = []
    for aid in recipients:
        target = engine.state.actors[aid]
        key = f"push:{aid}"
        if not target.active:
            continue
        options.append(key)
        labels[key] = f"Push {target.display_name} 5 feet directly away from you"
        if target.team_id != actor.team_id and perceives(engine, actor, target):
            automatic.append(key)
    picked = ask(engine, getattr(ctx, "intent", None), checkpoint_id(engine, "Dragon-Pearl Release", actor.entity_id),
                 actor, "choice:needle.dragon_pearl", options, labels=labels, allow_decline=True,
                 name="Dragon-Pearl Release", feature_id=PEARL, target_id=actor.entity_id,
                 automatic_options=automatic or ["flight"] + (["stamina"] if stamina in actor.resources else []),
                 prompt=f"Dragon-Pearl Release: your {action.display_name} dealt Lightning or Thunder damage to "
                        + ", ".join(engine.state.actors[aid].display_name for aid in recipients)
                        + ". Choose one benefit, at no extra cost. Once per scene.")
    if not picked:
        return
    mark_used(engine, actor, PEARL)
    if picked[0] == "stamina":
        engine._gain_resource(actor, stamina, 2, PEARL)
    elif picked[0].startswith("push:"):
        target = engine.state.actors[picked[0].removeprefix("push:")]
        run_effects(ctx.on_hit_context(target).with_source(PEARL), [
            {"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away"}])
    else:
        engine._apply_condition(actor, PEARL_FLIGHT, PEARL, actor.entity_id,
                                expires_on="END_OF_CURRENT_TURN",
                                data={"label": "Dragon-Pearl Release: Fly Speed 30 feet until this turn ends"})
    note(engine, PEARL, actor, "Dragon-Pearl Release used for this scene.")


@hook("flight")
def pearl_flight(engine, actor):
    if any(c.condition_id == PEARL_FLIGHT for c in actor.conditions.values()):
        return {"fly_speed_ft": 30}
    return None
