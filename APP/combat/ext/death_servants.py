"""Death servant combat rules from the printed stat blocks and Deathless Guard.

Fresh individual summon bundles opt in through compile_summon. Runtime hooks
read their sealed records, never current character ownership or live authority.
Ritual creation/permission stays outside combat; represented corpses are real
recorded dead actors or explicitly typed objects, never nonlethal defeats.
"""
from typing import Any
from . import effect, hook

GUARD = "TAL_DEATH_DEATHLESS_GUARD"
FORMATION = "TAL_DEATH_GRAVE_FORMATION"
STAT = "TAL_DEATH_GRAVE_FORMATION_STAT_BLOCK"
COMMANDER = "insight.black-lantern-commander"
LAST_ASSAULT = "condition:typed.black_lantern_last_assault_spent"
RULES = "death_servant_rules"


@hook("compile_summon")
def servant_bundle(bundle: dict[str, Any], info: dict[str, Any]) -> dict[str, Any] | None:
    key = info["creature_key"]
    if key not in {"corpse_servant", "grave_formation", "lesser_corpse_servant"}:
        return None
    bundle["summon"][RULES] = {"kind": key, "pb": info["pb"], "cl": info["cl"]}
    bundle["actor_template"]["creature_types"] = ["Undead"]
    sizes = info["plan"].get("death_sizes") or {}
    if key != "grave_formation":
        size = sizes.get(bundle["actor_id"], sizes.get(info["group"], "medium"))
        if size not in {"medium", "small"}:
            raise ValueError("Corpse Servants require Small or Medium remains")
        bundle["summon"]["size"] = size
        bundle["actor_template"]["size_category"] = size.title()
    # A formation's chosen size represents the remains supplied before combat.
    if key == "grave_formation":
        size = (info["plan"].get("death_sizes") or {}).get(bundle["actor_id"],
                (info["plan"].get("death_sizes") or {}).get(info["group"], "large"))
        if size not in {"large", "huge"}:
            raise ValueError("Grave Formation requires Large or Huge remains")
        bundle["summon"].update(size=size, footprint=size)
        bundle["actor_template"]["size_category"] = size.title()
        if COMMANDER in info["owned_ids"]:
            bundle["summon"][RULES]["black_lantern"] = True
            bundle["actor_template"]["speed_ft"] += 10
            bundle["actor_template"]["maximum_hp"] += info["cl"]
    for action in bundle["action_catalog"]:
        typed = action.get("parameters", {}).get("typed", {})
        # Preserve the historical Necrotic tie preference (including Grave Mark)
        # while allowing the printed physical alternatives against defenses.
        if typed.get("weapon") and any(e.get("type") == "attack" for e in typed.get("effects") or []):
            typed["weapon"]["damage_types"] = ["NECROTIC", "BLUDGEONING", "SLASHING"]
        if typed.get("source") == GUARD:
            typed["effects"] = [{"type": "death_guard_stance"}]
            # Public own-action trait consumed by summon_instinct for a Guard order.
            action["parameters"]["summon_guard_action"] = True
    for row in bundle["typed_reactions"]:
        if row.get("feature_id") == GUARD:
            row["death_guard_attack_only"] = True
            row["effects"].append({"type": "death_guard_step", "only_if_zero": True})
    return bundle


def corpses_near(engine, actor):
    from .life_state import is_deceased
    from ..object_geometry import target_cells
    return (any(not other.summon and is_deceased(other)
                and not any(c.condition_id == "condition:typed.corpse_consumed" for c in other.conditions.values())
                and engine._distance_actor_to_actor(actor, other) <= 10
                for other in engine.state.actors.values())
            or any(not obj.destroyed and str(obj.object_kind).lower() in {"corpse", "remains"}
                   and engine.grid.distance_between_cell_sets_ft(engine._actor_volume(actor), target_cells(engine, obj)) <= 10
                   for obj in engine.state.objects.values()))


@hook("turn_boundary_start")
def corpse_engine(engine, actor):
    rules = (actor.summon or {}).get(RULES) or {}
    if (not actor.active or rules.get("kind") != "grave_formation"
            or actor.current_hp <= 0 or actor.current_hp >= actor.maximum_hp // 2
            or not corpses_near(engine, actor)):
        return
    from ..typed_executor import stored_healing_reductions
    # Apply healing restrictions to the full printed PB offer first. The half-HP
    # limit caps what the formation actually restores, after Sickened and other
    # reductions have resolved.
    offered = int(rules["pb"])
    amount = stored_healing_reductions(engine, actor, offered)
    # Healing bonuses may not exceed this stat block's explicit half-HP ceiling.
    amount = min(amount, actor.maximum_hp // 2 - actor.current_hp)
    engine._heal(actor, amount, STAT, actor.entity_id, notify_healed=True)


@effect("death_guard_stance", harmful=False)
def guard_stance(ctx, row):
    from .effect_durations import token
    owner = ctx.engine.state.actors.get((ctx.actor.summon or {}).get("owner"))
    if owner is None:
        return
    ctx.engine._apply_condition(ctx.actor, "condition:typed.guarding", ctx.source, owner.entity_id,
        expires_on=token("start", owner.entity_id, owner.turns_started + 1),
        data={"label": "Deathless Guard until your summoner's next turn"})


@hook("damage_context_pending_reaction_rank")
def guard_attack_only(engine, reactor, row, packet, intent):
    if not row.get("death_guard_attack_only"):
        return None
    attack = engine.damage_context()
    return {"allowed": bool(attack and (attack.source_id, attack.attacker_id, attack.target_id)
                            == (packet.source_id, packet.source_actor_id, packet.target_id))}


def damage_choice_context(engine, affected, source_id):
    """Read the current packet, never the outer intent or recent event history."""
    from ..pending_damage import current
    from .choice_prompt import action_context
    packet = current(engine)
    attacker = None
    if packet is not None and packet.target_id == affected.entity_id:
        source_id = packet.source_id
        attacker = engine.state.actors.get(packet.source_actor_id)
    return action_context(engine, attacker, source_id, affected)


@effect("death_guard_step", harmful=False)
def guard_step(ctx, row):
    from . import granted_moves
    from .needle import ask, cell_id
    protected = ctx.engine.state.actors.get(ctx.typed.get("protects"))
    if protected is None:
        return
    context = damage_choice_context(ctx.engine, protected, ctx.source)
    choices = granted_moves.destinations(ctx.engine, ctx.actor, 5, lambda pos: pos != ctx.actor.position)
    routes = {cell_id(pos): path for pos, path, cost in choices if 0 < cost <= 5}
    chosen = ask(ctx.engine, ctx.intent, "DEATH_GUARD_STEP", ctx.actor,
        "choice:needle.death_guard_step", list(routes), allow_decline=True,
        labels={key: "Move to " + key.split(":", 1)[1] for key in routes},
        name="Deathless Guard", prompt=f"Deathless Guard stopped all damage to {protected.display_name}. Move up to 5 feet without provoking Opportunity Attacks?",
        target_id=protected.entity_id, prompt_context=context, feature_id=GUARD) if routes else []
    if chosen:
        granted_moves.commit(ctx.engine, ctx.actor, routes[chosen[0]], ctx.source,
                             budget_ft=5, provokes=False, intent=ctx.intent)


@hook("compile_actions")
def dismissal_actions(info):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    owned = set(info["owned_ids"])
    sources = owned & {FORMATION, "TAL_DEATH_CORPSE_SERVANT", "TAL_DEATH_ROUSE_LESSER_DEAD",
                       "TAL_DEATH_LEGION_OF_THE_RESTLESS_DEAD"}
    if not sources:
        return None
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.dismiss_death_servant",
        display_name="Dismiss a Death servant", owner_id=info["actor_id"], economy=EconomyKind.NONE,
        resolution_kind="TYPED", target_kind="SELF",
        parameters={"player_only": True, "expected_damage": 0,
                    "description": "On your turn, dismiss one Death servant you created without spending an Action.",
                    "typed": {"source": FORMATION if FORMATION in sources else sorted(sources)[0],
                              "effects": [{"type": "death_servant_dismiss"}], "riders": [],
                              "numbers": info["numbers"], "duration": {"kind": "instant"}}})]


def dismissible(engine, owner):
    return [a for a in engine.state.actors.values() if a.active and a.summon
            and a.summon.get("owner") == owner.entity_id and a.summon.get(RULES)
            and a.summon.get("status") == "present"]


@hook("candidate_allowed")
def dismissal_allowed(engine, actor, candidate, action):
    if not any(e.get("type") == "death_servant_dismiss" for e in
               ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("effects") or []):
        return None
    return engine.state.current_actor_id == actor.entity_id and bool(dismissible(engine, actor))


@effect("death_servant_dismiss", harmful=False)
def dismiss_servant(ctx, row):
    from .needle import ask
    from .. import summons
    choices = {a.entity_id: a for a in dismissible(ctx.engine, ctx.actor)}
    chosen = ask(ctx.engine, ctx.intent, "DEATH_SERVANT_DISMISS", ctx.actor,
        "choice:needle.death_servant_dismiss", list(choices), allow_decline=True,
        labels={key: a.display_name for key, a in choices.items()},
        name="Dismiss a Death servant", prompt="Choose the Death servant you created to dismiss, or cancel. This uses no Action.",
        feature_id=ctx.typed["source"]) if choices else []
    if chosen:
        summons.dismiss(ctx.engine, choices[chosen[0]], "OWNER_DISMISSED")


def servant_sense(engine, actor):
    rules = (actor.summon or {}).get(RULES) or {}
    if rules.get("kind") in {"corpse_servant", "grave_formation"}:
        engine._apply_condition(actor, "condition:typed.sense", actor.summon["source"],
            actor.entity_id, expires_on="UNTIL_REMOVED", data={"sense": "darkvision", "range_ft": 60,
            "label": "Death servant Darkvision 60 feet"})


@hook("match_start")
def servant_senses(engine):
    for actor in engine.state.actors.values():
        servant_sense(engine, actor)


@hook("summon_appeared")
def servant_appeared(engine, owner, actor, source_id):
    # Generic arrival clears conditions; restore this printed intrinsic sense.
    servant_sense(engine, actor)


@hook("passive_perception_override")
def servant_perception(engine, creature, observed, baseline):
    rules = (creature.summon or {}).get(RULES) or {}
    if rules.get("kind") in {"corpse_servant", "grave_formation", "lesser_corpse_servant"}:
        return 8 + int(rules["pb"])
    return None


@hook("save_mode")
def grave_body(engine, target, ability, dc, source_id, roll_context):
    rules = (target.summon or {}).get(RULES) or {}
    if rules.get("kind") != "corpse_servant":
        return None
    named = set((roll_context or {}).get("named") or [])
    if named & {"exhaustion", "exhausted", "poisoned", "frightened"}:
        return "ADVANTAGE"
    return None


@hook("zero_hp")
def commander_last_assault(engine, formation, damage_source_id, intent):
    """One optional Grave Assault after 0 HP, then the normal collapse follows."""
    rules = (formation.summon or {}).get(RULES) or {}
    if (rules.get("kind") != "grave_formation" or not rules.get("black_lantern")
            or formation.current_hp != 0):
        return None
    owner = engine.state.actors.get(formation.summon.get("owner"))
    if owner is None or any(c.condition_id == LAST_ASSAULT for c in owner.conditions.values()):
        return None
    from ..attack_notifications import can_strike
    if not can_strike(formation):
        return None
    from .. import senses
    from ..targeting import attack_line_of_effect
    from ..relations import relation, ENEMY
    action = next((engine.action_catalog[aid] for aid in formation.action_ids
                   if aid in engine.action_catalog
                   and engine.action_catalog[aid].display_name == "Grave Assault"
                   and engine.action_catalog[aid].parameters.get("hp_band") == "half_or_less"), None)
    if action is None:
        return None
    choices = {other.entity_id: other for other in engine.state.actors.values()
               if other.active and relation(engine, formation, other) == ENEMY
               and senses.perceives(engine, formation, other)
               and engine._target_in_range(formation, other, action)
               and attack_line_of_effect(engine, formation, other, action.source_definition_id)}
    if not choices:
        return None
    from .needle import ask
    chosen = ask(engine, intent, "BLACK_LANTERN_LAST_ASSAULT", formation,
        "choice:needle.black_lantern_last_assault", sorted(choices), allow_decline=True,
        labels={key: other.display_name for key, other in choices.items()},
        preferred=[min(choices)], name="Black-Lantern Commander",
        prompt=f"{formation.display_name} has reached 0 Hit Points. Once this scene, it may make one Grave Assault against an enemy in reach before collapsing. Choose an enemy or decline.",
        target_id=formation.entity_id,
        prompt_context=damage_choice_context(engine, formation, damage_source_id),
        feature_id=COMMANDER)
    if not chosen:
        return None
    engine._apply_condition(owner, LAST_ASSAULT, COMMANDER, owner.entity_id,
                           expires_on="UNTIL_REMOVED", data={"label":"Black-Lantern Commander's last assault used this scene"})
    from ..typed_executor import Context, run_effects
    target = choices[chosen[0]]
    data = dict(action.parameters["typed"])
    run_effects(Context(engine, formation, action, intent, data, [target], target), data["effects"])
    return None  # Never retain life state: default destruction must still happen.
