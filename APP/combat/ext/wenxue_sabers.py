"""Sabers sphere core mechanics (owner 2026-09-28 automation push, Wen Xue's worker): Edge Momentum / Guard
Pressured, Saber-Line Pressure's once-a-turn choice, Hard Draw Cut's next-hit bonus, and Saber Scare -- the
sphere's own base engine, which nothing in factory_compiler.py or typed_executor.py built yet (as of
2026-09-28 no module anywhere in this codebase keys off a saber weapon or a Sabers mechanic by name).

Why a plug-in instead of reviewed_final alone: Sabers' own "cultivation_melee" attacks read "Make one saber
attack ... Hit: deal normal weapon damage", the same shape build_typed_mechanics_authority.py already
recognises for a literal "make a weapon attack" (factory_authoring/typed_structure._WEAPON_ATTACK) -- but
"saber attack" does not match that regex, so these were typed as a damageless Cultivation Attack (no weapon
dice at all for Circle-Cleaving Saber/Red Trail Pursuit/Wrap the Head, or a bare 1d4 for Forward Cut, since
compile_character always sets an action's own ``typed["weapon"]`` to None unless the mechanic uses the
regex-matched "weapon_delivery" path). reviewed_final can replace an effect list but not that compiled
``weapon`` field, so ``attach_saber_weapon`` is a same-order effect placed just before the "attack" effect in
each of these mechanics' own effects list (see reviewed_final.d/wenxue.json): ``run_effects`` shares one
``Context`` across a single activation's effects, so mutating ``ctx.typed["weapon"]`` here is visible to the
"attack" effect that runs right after it.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

SABER_WORDS = ("saber", "dao")  # combat/factory_compiler.py's own _FAMILY_WORDS["saber"]
GUARD_PRESSURED = "Guard Pressured"
HARD_DRAW_READY = "condition:typed.wenxue.hard_draw_ready"
SABER_LINE_GUARD_CHOICE = "condition:typed.wenxue.saber_line_guard_choice"


def _actor_saber_weapon(ctx: Any) -> dict[str, Any] | None:
    """The character's own saber weapon-attack action, if any (its ``typed.weapon`` dict: damage dice, type)."""
    for action in getattr(ctx.engine, "action_catalog", {}).values():
        if action.owner_id != ctx.actor.entity_id:
            continue
        typed = (action.parameters or {}).get("typed") or {}
        weapon = typed.get("weapon")
        if weapon and any(word in action.display_name.lower() for word in SABER_WORDS):
            return weapon
    return None


@effect("attach_saber_weapon")
def attach_saber_weapon(ctx: Any, effect_row: dict[str, Any]) -> None:
    if ctx.typed.get("weapon"):
        return  # already resolved
    bound = ctx.typed.get("saber_weapon_source")
    linked = ctx.engine.action_catalog.get(str(bound)) if bound else None
    weapon = ((linked.parameters or {}).get("typed") or {}).get("weapon") if linked else _actor_saber_weapon(ctx)
    if weapon is None:
        ctx.rider("No saber weapon found to deliver this Sabers attack's damage (the character carries no qualifying saber).")
        return
    ctx.typed["weapon"] = weapon
    if linked is not None and effect_row.get("weapon_attack_numbers"):
        # A printed saber weapon attack uses its weapon's normal attack bonus,
        # while the talent keeps its own save DC and other cultivation numbers.
        numbers = ((linked.parameters or {}).get("typed") or {}).get("numbers") or {}
        ctx.typed["numbers"] = {**ctx.numbers, "attack_bonus": int(numbers.get("attack_bonus") or 0)}


def _is_saber_hit(ctx: Any, kind: str) -> bool:
    """A Sabers-sphere ability using its own attach_saber_weapon (Forward Cut, Circle-Cleaving Saber, Red Trail
    Pursuit, Wrap the Head Return the Edge -- their own display name never says "saber"), or the character's
    plain saber weapon-attack/Opportunity Attack action (whose display name does)."""
    if kind != "weapon":
        return False
    if ctx.typed.get("sphere") == "tianxia.sphere.sabers":
        return True
    return any(word in ctx.action.display_name.lower() for word in SABER_WORDS)


def _passive_rows(engine: Any, actor: Any, block: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []) if row.get("block") == block]


def _has_condition(actor: Any, condition_id: str) -> bool:
    return any(c.condition_id == condition_id for c in actor.conditions.values())


# ---------------------------------------------------------------- Saber-Line Pressure (SABERS_BASE_SABER_LINE_PRESSURE)
@hook("compile_block")
def compile_saber_blocks(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block in ("saber_line_pressure", "saber_scare"):
        return [row]
    return None


@hook("compile_actions")
def saber_line_pressure_toggle(info: dict[str, Any]) -> list[Any]:
    """A free, sticky choice for Saber-Line Pressure's "choose one" (owner's Exploit-style pattern): default is
    gaining Edge Momentum; this toggle switches the once-a-turn saber hit to Guard Pressure the target instead."""
    if "SABERS_BASE_SABER_LINE_PRESSURE" not in info["owned_ids"]:
        return []
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    short, actor_id, numbers = info["short"], info["actor_id"], info["numbers"]
    out = []
    for on, label in ((True, "Saber-Line Pressure: prefer Guard Pressure"), (False, "Saber-Line Pressure: prefer Edge Momentum")):
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{short}.saber_line_pressure.{'guard' if on else 'edge'}", display_name=label,
            owner_id=actor_id, economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
            parameters={"setting_only": True, "typed": {"effects": [{"type": "wenxue_saber_line_choice", "guard": on}], "numbers": numbers,
                                  "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0, "player_only": True}))
    return out


@effect("wenxue_saber_line_choice")
def saber_line_choice(ctx: Any, effect_row: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, SABER_LINE_GUARD_CHOICE, ctx.source)
    if effect_row.get("guard"):
        ctx.engine._apply_condition(ctx.actor, SABER_LINE_GUARD_CHOICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"label": "Saber-Line Pressure prefers Guard Pressure"})


@hook("after_hit")
def saber_line_pressure(ctx: Any, target: Any, kind: str) -> None:
    if not _passive_rows(ctx.engine, ctx.actor, "saber_line_pressure") or not _is_saber_hit(ctx, kind):
        return
    flag = "wenxue_saber_line_pressure_used"
    if ctx.actor.turn_flags.get(flag):
        return
    ctx.actor.turn_flags[flag] = True
    if _has_condition(ctx.actor, SABER_LINE_GUARD_CHOICE):
        from ..typed_executor import Context, run_effects

        inner = Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, ctx.damage_cache)
        run_effects(inner, [{"type": "mark", "mark": GUARD_PRESSURED, "applies_to": "target", "duration": {"kind": "until_start_of_your_next_turn"}}])
        ctx.rider("Saber-Line Pressure: made the target Guard Pressured (the player toggle preferred this over Edge Momentum).")
        return
    resource_id = "resource:named.edge_momentum"
    if resource_id in ctx.actor.resources:
        ctx.engine._gain_resource(ctx.actor, resource_id, 1, "passive:SABERS_BASE_SABER_LINE_PRESSURE")


# ---------------------------------------------------------------- Hard Draw Cut
@effect("wenxue_hard_draw_cut_activate")
def hard_draw_cut_activate(ctx: Any, effect_row: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, HARD_DRAW_READY, ctx.source)
    ctx.engine._apply_condition(ctx.actor, HARD_DRAW_READY, ctx.source, ctx.actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                                data={"label": "Hard Draw Cut: next saber hit deals +PB slashing"})


@hook("after_hit")
def hard_draw_cut_bonus(ctx: Any, target: Any, kind: str) -> None:
    if not _has_condition(ctx.actor, HARD_DRAW_READY) or not _is_saber_hit(ctx, kind) or not target.active:
        return
    ctx.engine._remove_condition(ctx.actor, HARD_DRAW_READY, ctx.source)
    pb = int(ctx.numbers.get("pb") or 2)
    ctx.engine._commit_damage(target, pb, "SLASHING", f"{ctx.source}.hard_draw_cut", ctx.actor.entity_id, ctx.intent, reaction_depth=0)
    ctx.rider(f"Hard Draw Cut: +{pb} slashing damage on this saber hit.")


# ---------------------------------------------------------------- Saber Scare
CRITICAL_STRIKE = "_wenxue_critical_strike"


@hook("attack_result")
def remember_critical_hit(ctx: Any, target: Any, hit: bool, critical: bool) -> None:
    """This strike's settled result, for Saber Scare's printed trigger ("you critically hit a creature with a
    saber"). The printed trigger is the final attack result, so it is read from attack_result rather than a damage
    event: a Critical Hit that deals no damage (resistance, Immunity, a target already at 0 HP) commits no HP damage
    and so would otherwise be missed.

    One key, written on EVERY settled result including a miss and an ordinary hit: after_hit reads it for the
    attack that just resolved, so a later ordinary blow against a creature a Critical Hit already frightened cannot
    frighten it again. Resolution-local, like the other Sabers choose_hit_target bookkeeping; the owner guard keeps
    it inert for characters without the talent."""
    if not _passive_rows(ctx.engine, ctx.actor, "saber_scare"):
        return
    ctx.damage_cache[CRITICAL_STRIKE] = target.entity_id if (hit and critical and target.active) else None


def _was_critical(ctx: Any, target: Any) -> bool:
    return ctx.damage_cache.get(CRITICAL_STRIKE) == target.entity_id


@hook("after_hit")
def saber_scare(ctx: Any, target: Any, kind: str) -> None:
    if not _passive_rows(ctx.engine, ctx.actor, "saber_scare") or not _is_saber_hit(ctx, kind):
        return
    killed = not target.active or target.current_hp <= 0
    if not (killed or _was_critical(ctx, target)):
        return
    from .. import stealth
    from ..typed_executor import Context, run_effects

    hostiles = [a for a in ctx.engine.state.actors.values() if a.active and a.entity_id != ctx.actor.entity_id
               and a.team_id != ctx.actor.team_id and ctx.engine._distance_actor_to_actor(ctx.actor, a) <= 30
               and stealth.sees(ctx.engine, a, ctx.actor)]
    if not hostiles:
        return
    # "choose one hostile creature within 30 feet that can see you" (rider lane C5): a player chooses; the AI takes the nearest.
    hostiles.sort(key=lambda a: (ctx.engine._distance_actor_to_actor(ctx.actor, a), a.entity_id))
    from .choice_prompt import action_context
    from .needle import CHOICE, ask, checkpoint_id

    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "SABER_SCARE", ctx.source, target.entity_id), ctx.actor, CHOICE + "saber_scare",
                 [a.entity_id for a in hostiles], labels={a.entity_id: a.display_name for a in hostiles}, name="Saber Scare",
                 prompt=f"Saber Scare: {ctx.action.display_name} dropped or critically hit {target.display_name}. Choose a hostile creature "
                        "within 30 feet that can see you: it makes a Wisdom save or cannot take Reactions until the start of its next turn.",
                 prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, target))
    chosen = next((a for a in hostiles if a.entity_id == (picked or [hostiles[0].entity_id])[0]), hostiles[0])
    inner = Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [chosen], chosen, ctx.damage_cache)
    run_effects(inner, [{"type": "save", "ability": "wis", "dc": "technique_save_dc",
                         "on_fail": [{"type": "reaction_denied", "applies_to": "target", "duration": "until_start_of_next_turn",
                                      "evidence": "It cannot take Reactions until the start of its next turn"}],
                         "on_success": []}])


# ---------------------------------------------------------------- Guard-Cutting Parry's Foundation Realm upgrade
# The base parry (reduce incoming weapon damage by 1d8 + PB) is not this plug-in's: it already runs through the
# engine's generic "damage_reduction" reaction block (combat/typed_reactions.py on_damage), compiled straight
# from combat/rules/feature_blocks.json's own Parry-style entry for this talent -- untouched by this file or by
# reviewed_final.d/wenxue.json, whose "effects"/"options" that block never reads. Only the printed upgrade ("At
# Foundation Realm, you may spend 1 CP or 1 Stamina to make the attacker Guard Pressured") is missing, so this
# hooks the REACTION_RESOLVED event that block already emits rather than duplicating its damage math.
GUARD_CUTTING_PARRY = "tianxia.talent.sabers.guard_cutting_parry"


@hook("event")
def guard_cutting_parry_press(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "REACTION_RESOLVED":
        return
    # The event itself, not merely the last one: an earlier event hook may already have appended its own (rider lane C5).
    event = next((e for e in reversed(engine.events) if e.event_type == "REACTION_RESOLVED"), None)
    if event is None or event.source_definition_id != GUARD_CUTTING_PARRY:
        return
    actor = engine.state.actors.get(event.actor_id or "")
    attacker = engine.state.actors.get((event.target_ids or (None,))[0] or "")
    if actor is None or attacker is None or not attacker.active:
        return
    from ..factory_compiler import RESOURCE_IDS
    from ..typed_executor import mark_condition_id
    from .. import unmaking

    # "At Foundation Realm, you may spend 1 CP or 1 Stamina" (rider lane C5): Foundation Realm is CL 5+; the owner chooses.
    if unmaking.cultivation_level(engine, actor) < 5:
        return
    resource_id = next((rid for rid in (RESOURCE_IDS["qi"], RESOURCE_IDS["stamina"], RESOURCE_IDS["resonance"]) if actor.resources.get(rid, 0) >= 1), None)
    if resource_id is None:
        return  # nothing to spend for the optional upgrade this activation
    from .needle import CHOICE, ask, checkpoint_id

    picked = ask(engine, None, checkpoint_id(engine, "GUARD_CUTTING_PARRY", actor.entity_id, attacker.entity_id), actor, CHOICE + "guard_cutting_parry",
                 ["press", "skip"], labels={"press": f"Spend 1 CP or Stamina: {attacker.display_name} is Guard Pressured until the start of your next turn",
                                            "skip": "Don't spend it"}, name="Guard-Cutting Parry",
                 prompt=f"Guard-Cutting Parry against {attacker.display_name}'s attack.")
    if (picked or ["press"])[0] != "press":
        return
    engine._spend_resource(actor, resource_id, 1, GUARD_CUTTING_PARRY)
    engine._apply_condition(attacker, mark_condition_id(GUARD_PRESSURED, actor.entity_id), GUARD_CUTTING_PARRY, actor.entity_id,
                            expires_on="START_OF_SOURCE_NEXT_TURN")
    engine._append_event("GM_RIDER", GUARD_CUTTING_PARRY, actor_id=actor.entity_id, target_ids=(attacker.entity_id,),
                         payload={"rider": f"Guard-Cutting Parry: 1 CP or Stamina spent; {attacker.display_name} is Guard Pressured until the start of your next turn."})
