"""Source-bound passive riders for Path, Subpath and Tradition features.

An owned mechanic's ``path_passive`` effect carries ``kind`` and its printed
parameters. compile_actions copies these into passive rows; absent typing is
inert. ``unarmed_types`` changes only unarmed attacks' weapon damage choices;
the executor already chooses a type separately for each strike.
``paid_hit`` offers a paid result after an unarmed hit, including save-result
menus. Legacy ``gm_miss_charge`` and ``miss_charge`` rows retain the named pool;
Unbroken Bolt's native miss notification and shared round limit now live in
``unbroken_bolt.py``. Those old row kinds need no separate execution or GM notice.
Other defensive benefits remain automated. All resource and limit changes use
evented methods.
``path_results`` rows may carry ``name`` (the feature named in the prompt; Heaven-Breaking Knuckle when absent) and
``prompt`` (a whole prompt, "{target}" replaced by the creature's name, for results chosen outside a hit).
``path_next_unarmed_damage`` (rider lane C7) records "your next unarmed strike
before the end of your next turn deals an additional <dice> <type>": the next
unarmed strike the owner resolves uses it up, and on a hit the target takes the
extra dice as its own packet right after the strike (the post-hit/pre-damage
packet seam is a lock-round item). Row: {"type": "path_next_unarmed_damage",
"dice": {"count": 4, "sides": 8}, "damage_type": "force"}; one record per
source, refreshed on reuse; it ends at the end of the owner's next turn.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook

BLOCK = "path_rider"
RECORD = "condition:typed.path_rider_round"
NEXT_SAVE = "condition:typed.path_next_save"
NEXT_UNARMED = "condition:typed.path_next_unarmed"
NEXT_UNARMED_DAMAGE = "condition:typed.path_next_unarmed_damage"


def _walk(rows):
    for row in rows or []:
        if isinstance(row, dict):
            yield row
            for branch in ("on_hit", "on_miss", "on_fail", "on_success", "effects"):
                yield from _walk(row.get(branch))


def _rows(engine, actor, kind):
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == BLOCK and row.get("kind") == kind]


def _unarmed(typed):
    return any(row.get("type") == "attack" and row.get("attack_kind") == "unarmed"
               for row in _walk(typed.get("effects")))


@effect("path_passive")
def passive_marker(ctx: Any, row: dict[str, Any]) -> None:
    """Compile-time marker; it does not grant the passive again on activation."""


@effect("path_reaction_step")
def reaction_step(ctx, row):
    """The reactor chooses its printed free movement, including staying put."""
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step
    paths = routes(ctx.engine, ctx.actor, int(row["distance_ft"]))
    if not paths:
        return
    incoming = next((ctx.engine.action_catalog[e.source_definition_id].display_name
        for e in reversed(ctx.engine.events) if e.event_type == "ATTACK_ROLLED"
        and ctx.target is not None and e.actor_id == ctx.target.entity_id
        and e.source_definition_id in ctx.engine.action_catalog), "incoming damage")
    intent = ctx.intent or getattr(ctx.engine, "_active_intent", None)
    chosen = ask(ctx.engine, intent, checkpoint_id(ctx.engine, "path_reaction_step", ctx.actor.entity_id),
        ctx.actor, "choice:needle.path_reaction_step", [*sorted(paths), "Stay put"], allow_decline=True,
        labels={key: "Move to " + key.removeprefix("cell:") for key in paths},
        prompt=f"Thunder Runs Through Bone: after {incoming} damages {ctx.actor.display_name}, choose up to 10 feet of movement.",
        target_id=ctx.actor.entity_id)
    if chosen and chosen[0] != "Stay put":
        step(ctx.engine, ctx.actor, paths[chosen[0]], ctx.source)


@hook("compile_actions")
def compile_passives(info: dict[str, Any]) -> None:
    for mid in info["owned_ids"]:
        mech = info["mechanics"].get(mid) or {}
        for spec in mech.get("effects") or []:
            if spec.get("type") != "path_passive":
                continue
            row = {**copy.deepcopy(spec), "block": BLOCK, "feature_id": mid, "name": mech.get("name"),
                   "pb": info["pb"], "cl": info["numbers"].get("cl"), "save_dc": info["numbers"].get("save_dc")}
            if spec.get("kind") == "paid_hit":
                row["choice_owner"] = True
            info["passives"].append(row)
            if spec.get("kind") == "unarmed_types":
                for action in info.get("actions") or []:
                    typed = (action.parameters or {}).get("typed") or {}
                    if not _unarmed(typed) or not typed.get("weapon"):
                        continue
                    # ``add``: the strike may also deal these types (Venom Furnace: "may deal Poison damage"), else they replace.
                    kinds = [str(kind).upper() for kind in spec["damage_types"]]
                    if spec.get("add"):
                        weapon = typed["weapon"]
                        kinds = list(dict.fromkeys([*(weapon.get("damage_types") or [weapon.get("damage_type") or "BLUDGEONING"]), *kinds]))
                    # Do not mutate a weapon or number dictionary shared by other actions.
                    action.parameters["typed"] = {**typed, "weapon": {**typed["weapon"], "damage_types": kinds}}


@hook("after_hit")
def paid_hit(ctx, target, kind):
    if kind != "unarmed":
        return
    from .. import typed_executor
    from .needle import ask, checkpoint_id

    for row in _rows(ctx.engine, ctx.actor, "paid_hit"):
        # "limit": "fight" (Soul Severance's "Once per scene"): one use a fight; otherwise once per turn.
        stamp = "fight" if row.get("limit") == "fight" else f"{ctx.engine.state.round_number}:{ctx.engine.state.current_actor_id}"
        flag = f"condition:typed.path_hit_limit.{row['feature_id']}"
        if any(c.condition_id == flag and (c.data or {}).get("stamp") == stamp for c in ctx.actor.conditions.values()):
            continue
        costs = row.get("costs") or []
        if any(ctx.actor.resources.get(resource, 0) < amount for resource, amount in costs):
            continue
        options = row.get("options") or []
        chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "path_hit", row["feature_id"], target.entity_id),
                     ctx.actor, f"choice:needle.path_hit.{row['feature_id']}", [option["label"] for option in options],
                     allow_decline=True, target_id=target.entity_id,
                     prompt=f"{row['name']}: {ctx.action.display_name} hit {target.display_name}; use it"
                            f"{' (' + ', '.join(f'{amount} ' + resource.rsplit('.', 1)[-1].replace('_', ' ').title() for resource, amount in costs) + ')' if costs else ''}?")
        if not chosen:
            continue
        for resource, amount in costs:
            ctx.engine._spend_resource(ctx.actor, resource, amount, row["feature_id"])
        ctx.engine._remove_condition(ctx.actor, flag, row["feature_id"])
        ctx.engine._apply_condition(ctx.actor, flag, row["feature_id"], ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"stamp": stamp, "label": f"{row['name']}: used this turn"})
        sub = ctx.on_hit_context(target, action=ctx.action, typed={**ctx.typed, 'numbers': {**ctx.numbers, 'cl': row['cl'], 'pb': row['pb']}}, damage_cache={})
        typed_executor.run_effects(sub, [*(row.get("effects") or []),
            *next(option["effects"] for option in options if option["label"] == chosen[0])])


@hook("condition_immune")
def immune(engine, actor, name):
    return True if any(str(name).lower() in row.get("conditions", [])
                       for row in _rows(engine, actor, "condition_immunity")) else None


@hook("defense_description")
def condition_immunity_description(engine, target):
    """The condition immunities this character compiled from its own Path/Subpath/Tradition riders, as the
    Defences card names them.

    The same compiled rows condition_immune reads, read once and pure: the card has no condition to test, and
    these rows live under this plug-in's own ``path_rider`` block, so the sheet's condition-rule projection
    never sees them. A creature that compiled no such rider lists nothing."""
    described = []
    for row in _rows(engine, target, "condition_immunity"):
        conditions = [str(named) for named in row.get("conditions") or ()]
        if conditions:
            described.append({"feature_id": row.get("feature_id"), "conditions": conditions})
    return described or None


@hook("save")
def save_mode(ctx, actor, ability, named):
    if ctx is not None and any(set(row.get("against") or []) & set(named or [])
                               for row in _rows(ctx.engine, actor, "save_advantage")):
        return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return None


@effect("path_next_save")
def next_save(ctx, row):
    ctx.engine._remove_condition(ctx.actor, NEXT_SAVE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, NEXT_SAVE, ctx.source, ctx.actor.entity_id,
                               expires_on=row["expires_on"], data={"bonus": int(ctx.numbers["pb"]),
                               "abilities": row["abilities"], "label": "Next STR/CON save: +Proficiency Bonus"})


@hook("save")
def consume_next_save(ctx, actor, ability, named):
    if ctx is None:
        return None
    held = next((c for c in actor.conditions.values() if c.condition_id == NEXT_SAVE
                 and str(ability).upper() in (c.data or {}).get("abilities", [])), None)
    if held is None:
        return None
    remove_held(ctx.engine, actor, held)
    return {"bonus": int(held.data["bonus"]), "modes": []}


@effect("path_results")
def choose_results(ctx, row):
    """A save-result menu is asked after the save, with the printed count."""
    from .needle import ask, checkpoint_id
    from .. import typed_executor

    options = copy.deepcopy(row["options"])
    if row.get("end_defense"):
        options.append({"label": "End Defense", "effects": [{"type": "path_end_defense"}]})
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "path_results", row["family"], ctx.target.entity_id),
                   ctx.actor, f"choice:needle.path_results.{row['family']}", [o["label"] for o in options],
                   minimum=int(row["count"]), maximum=int(row["count"]), target_id=ctx.target.entity_id,
                   prompt=str(row.get("prompt") or "").format(target=ctx.target.display_name) or
                          f"{row.get('name') or 'Heaven-Breaking Knuckle'}: {ctx.action.display_name} hit {ctx.target.display_name}; "
                          f"choose {row['count']} {'save results' if int(row['count']) != 1 else 'failed-save result'}.")
    for option in options:
        if option["label"] in selected:
            typed_executor.run_effects(ctx, option["effects"])


@effect("path_ac")
def ac_penalty(ctx, row):
    condition = "condition:typed.path_ac." + str(row["family"])
    for held in list(ctx.target.conditions.values()):
        if held.condition_id == condition and held.source_actor_id == ctx.actor.entity_id:
            remove_held(ctx.engine, ctx.target, held)
    ctx.engine._apply_condition(ctx.target, condition, ctx.source, ctx.actor.entity_id,
                               expires_on=row["expires_on"], data={"amount": int(row["amount"]), "label": "Heaven-Breaking Knuckle: AC -2"})


@hook("ac")
def ac(engine, target):
    families = {}
    for condition in target.conditions.values():
        if condition.condition_id.startswith("condition:typed.path_ac."):
            family = condition.condition_id
            families[family] = min(families.get(family, 0), int(condition.data["amount"]))
    return sum(families.values())


@effect("path_unarmed_advantage")
def unarmed_advantage(ctx, row):
    ctx.engine._remove_condition(ctx.actor, NEXT_UNARMED, ctx.source)
    ctx.engine._apply_condition(ctx.actor, NEXT_UNARMED, ctx.source, ctx.actor.entity_id,
                               expires_on=f"END_OF_SOURCE_TURN_AT:{int(ctx.actor.turns_started) + 1}",
                               data={"label": "Next unarmed strike: Advantage"})


@hook("attack_mode")
def consume_unarmed_advantage(ctx, target):
    held = next((c for c in ctx.actor.conditions.values() if c.condition_id == NEXT_UNARMED), None)
    if _unarmed(ctx.typed) and held is not None:
        remove_held(ctx.engine, ctx.actor, held)
        return "ADVANTAGE"
    return None


def _defenses_to_end(ctx):
    from . import end_effect
    found = end_effect.found(ctx.engine, ctx.target, {"select": "beneficial"})
    eligible = []
    for kind, key, item in found:
        action = end_effect.source_action(ctx, item)
        typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action else {}
        # A persistent source must be represented; permanent sheet properties and
        # anonymous beneficial conditions are expressly excluded by the source text.
        if not typed or (typed.get("duration") or {}).get("kind") in (None, "instant"):
            continue
        if end_effect.source_cl(ctx, item) > int(ctx.numbers.get("cl") or 1):
            continue
        if kind == "modifier" and item.target_field not in ("armor_class", "armor_class_vs_melee", "armor_class_vs_ranged",
                                                           "damage_resistance", "damage_reduction", "attack_mode"):
            continue
        if kind == "condition":
            rule = end_effect.condition_rule(item, item.condition_id.removeprefix("condition:typed."))
            if not any(rule.get(field) for field in ("resistance", "damage_reduction", "ac_bonus", "cover", "stance")):
                continue
        eligible.append((kind, key, item))
    return eligible


@effect("path_end_defense")
def end_defense(ctx, row):
    from . import end_effect
    from .needle import ask, checkpoint_id
    found = _defenses_to_end(ctx)
    ids = [f"{kind}:{key}" for kind, key, _item in found]
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "path_defense", ctx.target.entity_id), ctx.actor,
                 "choice:needle.path_defense", ids, target_id=ctx.target.entity_id,
                 labels={f"{kind}:{key}": str((getattr(item, 'data', None) or {}).get('label') or
                     getattr(end_effect.source_action(ctx, item), 'display_name', 'Temporary defense'))
                     for kind, key, item in found},
                 prompt=f"Heaven-Breaking Knuckle: {ctx.action.display_name} hit {ctx.target.display_name}; choose the temporary defense to end.")
    if not found:
        ctx.rider("End one temporary barrier, ward, or defensive stance whose Source CL is no higher than yours: the GM resolves defenses without a represented persistent source.")
    for kind, key, item in found:
        if f"{kind}:{key}" in chosen:
            end_effect.remove_instance(ctx, ctx.target, kind, key, item)
            break


def remove_held(engine, actor, condition):
    """Consume exactly the selected stored bonus, regardless of the triggering source."""
    del actor.conditions[condition.instance_id]
    engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=actor.entity_id,
        target_ids=(actor.entity_id,), payload={"condition_id": condition.condition_id, "instance_id": condition.instance_id})
@effect("path_next_unarmed_damage")
def next_unarmed_damage(ctx, row):
    for held in [c for c in ctx.actor.conditions.values() if c.condition_id == NEXT_UNARMED_DAMAGE and c.source_definition_id == ctx.source]:
        remove_held(ctx.engine, ctx.actor, held)
    dice = {"count": int(row["dice"]["count"]), "sides": int(row["dice"]["sides"])}
    kind = str(row["damage_type"]).lower()
    ctx.engine._apply_condition(ctx.actor, NEXT_UNARMED_DAMAGE, ctx.source, ctx.actor.entity_id,
                               expires_on=f"END_OF_SOURCE_TURN_AT:{int(ctx.actor.turns_started) + 1}",
                               data={"dice": dice, "damage_type": kind,
                                     "label": f"Next unarmed strike: +{dice['count']}d{dice['sides']} {kind.title()} on a hit"})


@hook("attack_resolved")
def consume_unarmed_damage(ctx, target, hit, attack_effect):
    held = next((c for c in ctx.actor.conditions.values() if c.condition_id == NEXT_UNARMED_DAMAGE), None)
    if held is None or not ((attack_effect or {}).get("attack_kind") == "unarmed" or ".natural." in ctx.source):
        return
    from .. import typed_executor

    remove_held(ctx.engine, ctx.actor, held)
    if not hit or target is None or not target.active:
        return
    data = held.data or {}
    sub = ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={})
    typed_executor.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": dict(data["dice"]),
                                      "damage_types": [data["damage_type"]], "evidence": data.get("label", "")}])


@hook("save_mode")
def native_passive_save_mode(engine, actor, ability, dc, source_id, roll_context):
    """Retained hazard scopes also apply to native/repeat saves.

    Explicit consequence tags count; source names and existing conditions do not.
    """
    named = set((roll_context or {}).get("named") or ())
    return "ADVANTAGE" if any(named.intersection(row.get("against") or ())
                               for row in _rows(engine, actor, "save_advantage")) else None
