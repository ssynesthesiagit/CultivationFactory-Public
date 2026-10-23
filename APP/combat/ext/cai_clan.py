"""Cai Clan / Empyreal Administrator: fixed retainer layers and shared Censure.

Original owner-authored rules: non_sphere_authority/authority/owner_subpaths.d/
cai_clan.json, through owner_text_edits and reviewed_final.d/cai_clan.json.
Only owned features compile actions. Runtime hooks require their sealed action
metadata or their own conditions; old/unrelated fights are inert. No core patch.
Uses existing compile_block, compile_action(s), candidate_allowed, ac, save_bonus,
damage_reduction, final_damage, event and button_description hooks. Censure's
strict component delivery shares life_state's public HP accounting helper.
Effects cai_investiture / cai_censure / cai_flare_protection use ordinary typed
damage, saves, concentration, relation, perception and owner choice transport.
"""
from __future__ import annotations

from copy import deepcopy

from . import effect, hook
from .needle import ask, checkpoint_id, incapacitated, say
from .end_effect import remove_instance
from .. import concentration
from ..senses import perceives_cell
from ..gate2_runtime_models import ActionDefinition, DiceSpec, EconomyKind
from ..relations import relation
from ..target_knowledge import can_see
from ..targeting import line_of_effect

BASE = "tianxia.subpath.qi.cai_clan_empyreal_administrator.feature."
INVEST, EDICT, DUTY, FLARE, COURT = [BASE + name for name in (
    "empyreal_investiture", "edict_of_shared_purpose", "court_of_duty",
    "white_sun_judgment", "court_beneath_the_colorless_star")]
LAYER = "condition:typed.cai_empyreal_layer"
CENSURE = "condition:typed.cai_censure"
COURT_ACTIVE = "condition:typed.cai_colorless_court"
COURT_USED = "condition:typed.cai_colorless_court_used"
SPENT = "condition:typed.cai_layer_reduction_spent"
RECEIPT = "cai_censure_hit:"
CLAIMED_HIT = "cai_censure_claimed_hit:"
PASSIVE_BLOCK = "cai_clan_passive"


def _meta(action):
    if action is None:
        return {}
    return (action.parameters or {}).get("cai_clan") or {}


def _condition(actor, cid):
    return next((c for c in actor.conditions.values() if c.condition_id == cid), None)


def _rolled(engine, actor, source, dice, reason, target_ids=()):
    roll = engine.roller.roll(dice, actor_id=actor.entity_id, reason=reason)
    engine._record_roll(roll)
    engine._append_event("DAMAGE_ROLLED", source, actor_id=actor.entity_id, target_ids=tuple(target_ids),
                         payload=roll.model_dump(mode="json"))
    return roll.total


def _court(actor):
    return _condition(actor, COURT_ACTIVE) is not None


def _active_layers(engine, target, owner_id=None):
    for condition in target.conditions.values():
        if condition.condition_id != LAYER or (owner_id and condition.source_actor_id != owner_id):
            continue
        owner = engine.state.actors.get(condition.source_actor_id)
        if owner and owner.active and not incapacitated(owner):
            yield condition


def _owned_kit(info):
    owned = set(info["owned_ids"])
    numbers = _qi_numbers(info)
    return {"edict": int(EDICT in owned), "duty": int(DUTY in owned),
            "court": int(COURT in owned), "pb": int(numbers["pb"]),
            "key_mod": int(numbers["key_mod"])}


def _qi_numbers(info):
    """Use an explicit owning-Path row when a sheet supplies multi-Path numbers.

    Legacy single-Path sheets retain their ordinary compiled numbers. An
    explicit secondary Qi row can never inherit another Path's level or key.
    """
    numbers = deepcopy(info["numbers"])
    paths = (info["owner_sheet"].get("path_and_subpath") or {}).get("paths") or []
    qi = next((p for p in paths if isinstance(p, dict) and p.get("path_id") == "tianxia.path.qi_cultivation"), None)
    if qi is not None:
        numbers["cl"] = int(qi["effective_cl"])
        key = str(qi.get("key_ability") or "INT").upper()[:3]
        numbers["key_mod"] = int(info["mods"].get(key, 0))
        numbers["attack_bonus"] = numbers["pb"] + numbers["key_mod"]
        numbers["save_dc"] = 8 + numbers["attack_bonus"]
    return numbers


@hook("compile_block")
def passive_features(block, spec, row, numbers):
    """Publish the two owned upgrades, whose consumers are the sealed kit below.

    The compiler marks these rows automated and the connected sheet lists them
    as automatic. They grant no independent action or additional payment.
    """
    if block != PASSIVE_BLOCK or row["feature_id"] not in {EDICT, DUTY}:
        return None
    outcomes = {
        EDICT: "A Judgment Saber hit marks one enemy until the start of your next turn. A different ally's next damaging attack hit adds 2d8 Radiant damage (3d8 if marked during your Colorless Court), then consumes one mark. Critical Hits double these dice.",
        DUTY: "Empyreal Layer still costs 2 Qi and now protects up to two willing allies within 30 feet: +2 AC, +2 on Wisdom saves, and Proficiency Bonus + your Qi key ability modifier Temporary Hit Points (minimum 1). Both share one Concentration; reduction remains once per round.",
    }
    return [{**row, "trigger_owner": "cai_clan", "player_outcome": outcomes[row["feature_id"]]}]


@hook("compile_action")
def seal_action(action, info):
    if _meta(action):
        return None
    source = ((action.parameters or {}).get("typed") or {}).get("source")
    roles = {INVEST: "investiture", FLARE: "flare", COURT: "court"}
    if source not in roles or source not in info["owned_ids"]:
        return None
    parameters = deepcopy(action.parameters)
    parameters["typed"]["numbers"] = _qi_numbers(info)
    parameters["cai_clan"] = {**_owned_kit(info), "role": roles[source]}
    return action.model_copy(update={"parameters": parameters,
                             **({"display_name": "Empyreal Layer"} if source == INVEST else {})})


@hook("compile_actions")
def judgment_saber(info):
    if INVEST not in info["owned_ids"]:
        return []
    numbers = _qi_numbers(info)
    cl = int(numbers["cl"])
    dice = 6 if cl >= 18 else 5 if cl >= 14 else 4 if cl >= 10 else 3 if cl >= 6 else 2
    actions = [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.cai_judgment_saber",
        display_name="Judgment Saber", owner_id=info["actor_id"], economy=EconomyKind.ACTION,
        costs=(("resource:core.qi", 1),), resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=5,
        parameters={"cai_clan": {**_owned_kit(info), "role": "saber", "dice": dice},
                    "expected_damage": dice * 9 // 2 + numbers["key_mod"], "melee": True,
                    "requires_seen_target": True,
                    "typed": {"source": INVEST, "numbers": numbers, "duration": {"kind": "instant"},
                              "range_ft": None, "riders": [], "effects": [{
                                  "type": "attack", "attack_kind": "cultivation_melee", "count": 1,
                                  "on_hit": [{"type": "damage", "applies_to": "target", "dice": {"count": dice, "sides": 8},
                                              "formula": "key_ability_modifier", "damage_types": ["radiant"]},
                                             {"type": "cai_censure"}], "on_miss": []}]}})]
    if COURT in info["owned_ids"]:
        parameters = deepcopy(actions[0].parameters)
        parameters["cai_clan"]["court_only"] = 1
        parameters["melee"] = False
        parameters["typed"]["range_ft"] = 30
        parameters["typed"]["effects"][0]["attack_kind"] = "cultivation_ranged"
        actions.append(actions[0].model_copy(update={"source_definition_id": actions[0].source_definition_id + ".court",
                        "display_name": "Judgment Saber — Colorless Court", "range_ft": 30, "parameters": parameters}))
    actions.append(ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.cai_end_layers", display_name="End Empyreal Layers",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"cai_clan": {"role": "dismiss"}, "expected_damage": 0,
                    "typed": {"source": INVEST, "numbers": numbers, "duration": {"kind": "instant"},
                              "effects": [{"type": "cai_end_investiture"}], "riders": []}}))
    return actions


@hook("candidate_allowed")
def activation_allowed(engine, actor, candidate, action):
    role = _meta(action).get("role")
    if role == "flare" and (candidate.destination is None
                            or not perceives_cell(engine, actor, candidate.destination)):
        return False
    if role == "court" and _condition(actor, COURT_USED):
        return False
    if role == "investiture" and _court(actor):
        return False
    if role == "dismiss" and not _investment_copies(engine, actor):
        return False
    if role == "saber" and _meta(action).get("court_only"):
        if not _court(actor):
            return False
        if any(engine._distance_actor_to_actor(actor, engine.state.actors[t]) <= 5 for t in candidate.target_ids):
            return False
    return None


def _investment_copies(engine, actor):
    return [state for state in [actor.concentration, *(c for _, c in concentration.held(actor))]
            if state is not None and (action := engine.action_catalog.get(state.source_definition_id)) is not None
            and _meta(action).get("role") in {"investiture", "court"}]


@effect("cai_end_investiture")
def end_investiture(ctx, row):
    if _meta(ctx.action).get("role") != "dismiss":
        return
    for state in _investment_copies(ctx.engine, ctx.actor):
        concentration.end_copy(ctx.engine, ctx.actor, state.started_sequence, "ENDED_BY_OWNER")


@effect("cai_investiture", harmful=False)
def investiture(ctx, row):
    meta = _meta(ctx.action)
    if meta.get("role") not in {"court", "investiture"}:
        return
    court = meta["role"] == "court"
    count = meta["pb"] if court else 2 if meta["duty"] else 1
    audience = [a for a in ctx.engine.state.actors.values() if a.active
                and relation(ctx.engine, ctx.actor, a) == "ALLY"
                and ctx.engine._distance_actor_to_actor(ctx.actor, a) <= 30
                and (a.entity_id == ctx.actor.entity_id or (can_see(ctx.engine, ctx.actor, a)
                     and line_of_effect(ctx.engine, ctx.actor, target=a)))]
    audience.sort(key=lambda a: (a.current_hp / max(1, a.maximum_hp), a.entity_id))
    label = "Court Beneath the Colorless Star" if court else "Empyreal Layer"
    ac = 2 if court or meta["duty"] else 1
    reduction = max(1, meta["pb"] + meta["key_mod"]) if court else meta["pb"]
    picks = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "CAI_INVEST"), ctx.actor,
                "choice:needle.cai_investiture", [a.entity_id for a in audience],
                labels={a.entity_id: a.display_name for a in audience}, minimum=1, maximum=count,
                default="all", name=label, feature_id=COURT if court else INVEST,
                prompt=f"{ctx.actor.display_name} uses {label}. Choose up to {count} willing allies you can see within 30 feet "
                       f"(including yourself): +{ac} AC; the first time each ally would take damage each round, reduce it by {reduction}"
                       + (", +2 on Wisdom saves" if court or meta["duty"] else "")
                       + ("; each also gains 2d8 + your Qi key ability modifier Temporary Hit Points" if court else
                          "; each also gains your Proficiency Bonus + your Qi key ability modifier Temporary Hit Points" if meta["duty"] else "")
                       + ". Concentration, up to 1 minute. This replaces your previous layers.",
                prompt_context={"cost": str(8 if court else 2), "paying_pool": "resource:core.qi"})
    # The typed executor has already started this activation's Concentration.
    # End older copies of either ability only; never unrelated held techniques.
    current = ctx.actor.concentration
    copies = [(None, current), *concentration.held(ctx.actor)]
    for _, state in copies:
        action = ctx.engine.action_catalog.get(state.source_definition_id) if state else None
        if state and state is not current and action and _meta(action).get("role") in {"investiture", "court"}:
            concentration.end_copy(ctx.engine, ctx.actor, state.started_sequence, "REPLACED")
    temp_hp = 0
    if court:
        temp_hp = max(1, _rolled(ctx.engine, ctx.actor, ctx.source,
                      DiceSpec(count=2, sides=8, modifier=meta["key_mod"]), label, picks))
        ctx.engine._apply_condition(ctx.actor, COURT_ACTIVE, ctx.source, ctx.actor.entity_id,
                                    expires_on="CONCENTRATION_END", data={"name": label,
                                        "description": "You maintain your chosen allies' Colorless Court layers (8 Qi paid when activated). "
                                        "Concentration, up to 1 minute. Judgment Saber reaches 30 feet; a different ally's "
                                        "next damaging attack hit can claim its Censure for 3d8 additional Radiant damage."})
        ctx.engine._apply_condition(ctx.actor, COURT_USED, ctx.source, ctx.actor.entity_id,
                                    expires_on="UNTIL_REMOVED", data={"name": "Colorless Court used this combat",
                                        "description": "You already used Court Beneath the Colorless Star this combat "
                                        "(8 Qi when activated). You cannot use it again until a new fight. "
                                        "Ending your Concentration does not restore this use."})
    elif meta["duty"]:
        temp_hp = max(1, meta["pb"] + meta["key_mod"])
    for target_id in picks:
        target = ctx.engine.state.actors[target_id]
        ctx.engine._apply_condition(target, LAYER, ctx.source, ctx.actor.entity_id,
            expires_on="CONCENTRATION_END", data={"name": "Empyreal Layer", "ac": ac,
                "reduction": reduction, "wisdom_save": 2 if court or meta["duty"] else 0,
                "description": f"+{ac} AC; the first time you would take damage each round, reduce it by {reduction}. "
                               + ("+2 on Wisdom saves. " if court or meta["duty"] else "")
                               + "Ends with the Administrator's Concentration, at most 1 minute."})
        if temp_hp:
            ctx.engine._grant_temp_hp(target, temp_hp, ctx.source, ctx.actor.entity_id)
    say(ctx.engine, ctx.source, ctx.actor, f"{label} invests {', '.join(ctx.engine.state.actors[i].display_name for i in picks)}.", tuple(picks))


@hook("ac")
def layer_ac(engine, target):
    return max((int(c.data["ac"]) for c in _active_layers(engine, target)), default=0) or None


@hook("save_bonus")
def layer_wisdom(engine, target, ability, dc, source_id, intent):
    if str(ability).upper() not in {"WIS", "WISDOM"}:
        return None
    return max((int(c.data["wisdom_save"]) for c in _active_layers(engine, target)), default=0) or None


@hook("damage_reduction")
def layer_reduction(engine, target, damage_type, typed, source_actor_id, applied=False):
    spent = _condition(target, SPENT)
    if spent and int(spent.data["round"]) == engine.state.round_number:
        return None
    layers = list(_active_layers(engine, target))
    if not layers:
        return None
    amount = max(int(c.data["reduction"]) for c in layers)
    if applied:
        engine._apply_condition(target, SPENT, INVEST, target.entity_id,
            expires_on=f"START_OF_SLOT_AT:{engine.state.round_number + 1}:0",
            data={"round": engine.state.round_number, "name": "Empyreal Layer reduction used this round",
                  "description": "Empyreal Layer already reduced damage to you this round. "
                                 "It can reduce damage again next round if a layer still protects you. "
                                 "Another Administrator's layer cannot refresh this allowance."})
    return amount


@hook("final_damage")
def native_layer_reduction(engine, target, amount, damage_type, source_id, source_actor_id, intent):
    # Typed defenses already called damage_reduction. Native/legacy recipients
    # still get the same first-packet protection through the universal checkpoint.
    if amount <= 0 or target.entity_id in getattr(engine, "typed_actor_ids", set()):
        return None
    reduction = layer_reduction(engine, target, damage_type, None, source_actor_id)
    if not reduction:
        return None
    layer_reduction(engine, target, damage_type, None, source_actor_id, applied=True)
    return {"amount": max(0, amount - reduction)}


@effect("cai_censure")
def place_censure(ctx, row):
    meta = _meta(ctx.action)
    if meta.get("role") != "saber" or not meta.get("edict") or ctx.target is None:
        return
    for creature in ctx.engine.state.actors.values():
        for condition in list(creature.conditions.values()):
            if condition.condition_id == CENSURE and condition.source_actor_id == ctx.actor.entity_id:
                remove_instance(ctx, creature, "condition", condition.instance_id, condition)
    dice = 3 if _court(ctx.actor) else 2
    ctx.engine._apply_condition(ctx.target, CENSURE, ctx.source, ctx.actor.entity_id,
        expires_on="START_OF_SOURCE_NEXT_TURN", data={"dice": dice, "name": "Censure",
            "description": f"The next damaging attack hit by a different ally of the Administrator adds {dice}d8 Radiant damage, then ends this mark. "
                           "Ends at the start of the Administrator's next turn."})


def _claimable(engine, attacker, target):
    for condition in target.conditions.values():
        if condition.condition_id != CENSURE or condition.source_actor_id == attacker.entity_id:
            continue
        owner = engine.state.actors.get(condition.source_actor_id)
        if owner and relation(engine, owner, attacker) == "ALLY" and relation(engine, owner, target) == "ENEMY":
            yield condition


@hook("event", nested=True, priority=100)
def remember_damaging_hit(engine, event_type, kwargs):
    if event_type != "DAMAGE_COMMITTED":
        return
    provenance = engine.damage_context()
    payload = kwargs.get("payload") or {}
    if provenance is None or int(payload.get("hp_damage", 0)) + int(payload.get("temporary_hp_absorbed", 0)) <= 0:
        return
    attacker, target = engine.state.actors.get(provenance.attacker_id), engine.state.actors.get(provenance.target_id)
    if (attacker and target and target.turn_flags.get(CLAIMED_HIT + attacker.entity_id) != provenance.roll_id
            and any(_claimable(engine, attacker, target))):
        target.turn_flags[RECEIPT + attacker.entity_id] = provenance.roll_id
        from ..pending_damage import current
        from .life_state import additional_hit_component
        from . import run_checkpoint
        packet = current(engine)
        with additional_hit_component(engine, target, packet.hp_before, int(payload.get("hp_damage", 0))):
            run_checkpoint("censure_damage_component", engine, attacker, target, provenance, engine._active_intent)


@hook("censure_damage_component")
def claim_censure(engine, attacker, target, provenance, intent):
    key = RECEIPT + attacker.entity_id
    if target.turn_flags.get(key) != provenance.roll_id:
        return
    target.turn_flags.pop(key, None)
    marks = sorted(_claimable(engine, attacker, target), key=lambda c: (-int(c.data["dice"]), c.applied_sequence, c.instance_id))
    if not marks:
        return
    chosen = marks[0]
    # One attack roll may commit several damage components. Claim once for the
    # whole hit, rather than once for each positive component. The last claimed
    # roll is a bounded, replayed turn flag; a fresh attack can claim another mark.
    target.turn_flags[CLAIMED_HIT + attacker.entity_id] = provenance.roll_id
    from types import SimpleNamespace
    remove_instance(SimpleNamespace(engine=engine, actor=attacker, source=EDICT),
                    target, "condition", chosen.instance_id, chosen)
    dice = int(chosen.data["dice"]) * (2 if provenance.critical and not provenance.critical_cancelled else 1)
    amount = _rolled(engine, attacker, EDICT, DiceSpec(count=dice, sides=8), "Censure radiant opening", (target.entity_id,))
    from .life_state import HIT_COMPONENT_FLAG
    engine._commit_damage(target, amount, "RADIANT", provenance.source_id, attacker.entity_id, intent,
                          reaction_depth=0, source_flags=("magical", HIT_COMPONENT_FLAG))
    say(engine, EDICT, attacker, f"{attacker.display_name} claims Censure on {target.display_name}: "
                                f"{amount} additional Radiant damage before defenses.", (target.entity_id,))


@effect("cai_flare_protection", harmful=False)
def protect_after_flare(ctx, row):
    if _meta(ctx.action).get("role") != "flare":
        return
    recipients = [a for a in ctx.targets if relation(ctx.engine, ctx.actor, a) == "ALLY"
                  and any(_active_layers(ctx.engine, a, ctx.actor.entity_id))]
    if not recipients:
        return
    amount = max(1, _rolled(ctx.engine, ctx.actor, ctx.source,
                  DiceSpec(count=2, sides=8, modifier=ctx.numbers["key_mod"]),
                  "White Sun Judgment protects invested allies", (a.entity_id for a in recipients)))
    for target in recipients:
        ctx.engine._grant_temp_hp(target, amount, ctx.source, ctx.actor.entity_id)


@hook("button_description")
def button_help(action):
    meta = (action.get("parameters") or {}).get("cai_clan") or {}
    role = meta.get("role")
    if role == "saber":
        reach = "30 feet. Ranged Cultivation Attack beyond 5 feet" if meta.get("court_only") else "5 feet. Melee Cultivation Attack"
        return (f"Action; 1 Qi; one visible enemy within {reach}: {meta['dice']}d8 + your Qi key ability modifier "
                "Radiant damage on a hit. A projected saber, with no physical weapon properties or Extra Attack. "
                + ("On a hit, Censure gives a different ally's next damaging attack hit +2d8 Radiant damage before your next turn. " if meta["edict"] else "")
                + ("While your Colorless Court is active: range 30 feet (ranged beyond 5 feet), and Censure grants 3d8 instead." if meta["court"] else ""))
    if role == "investiture":
        return (f"Bonus Action; 2 Qi; choose up to {2 if meta['duty'] else 1} willing allies you can see within 30 feet, including yourself. "
                f"Concentration, up to 1 minute: +{2 if meta['duty'] else 1} AC; the first time each recipient would take damage each round, reduce it by {meta['pb']}. "
                + ("Also +2 on Wisdom saves and your Proficiency Bonus + your Qi key ability modifier Temporary Hit Points (minimum 1). " if meta["duty"] else "")
                + "Replaces your previous layers; does not stack with another Administrator. Unavailable while your Colorless Court persists.")
    if role == "court":
        return (f"Bonus Action; 8 Qi; once per combat. Choose up to {meta['pb']} willing allies you can see within 30 feet, including yourself. "
                "Concentration, up to 1 minute: +2 AC, +2 on Wisdom saves, 2d8 + your Qi key ability modifier Temporary Hit Points, "
                "and the first time each recipient would take damage each round, reduce it by your Proficiency Bonus + your Qi key ability modifier (minimum 1). "
                "Replaces your previous layers. Your Judgment Saber reaches 30 feet. After it hits, a different ally's next damaging attack hit "
                "before your next turn adds 3d8 Radiant damage, then ends that opening. All layers end together.")
    if role == "dismiss":
        return "No action or Qi cost on your turn: end your Empyreal Layer or Colorless Court and all its layers. Unrelated Concentration continues."
    return None
