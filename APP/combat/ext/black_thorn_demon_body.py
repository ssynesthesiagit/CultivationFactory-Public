"""Black Thorn Demon Body Subpath (subpaths worker 2026-09-28: "make sure all the talents and class abilities ...
is applied").

Thorn-Flesh Armory  once per turn, on an unarmed-strike hit, spend 1 Demon Spine: add 2d6 Piercing or Slashing (a
                    free player choice on each hit), then a Constitution save; on a
                    failure, Bleeding until the start of your next turn. Source-bound delayed Bleeding is handled by
                    combat/ext/thorn_bleeding.py when the owned typing carries its opt-in marker. The Spine is optional:
                    a player is asked on every eligible hit (AI owners use it); declining spends nothing.
Crown of Black Thorns (rider lane C7)  "your Demon Spine damage ignores Resistance to Piercing and Slashing": damage from a
                    feature that spends Demon Spines (Thorn-Flesh Armory's 2d6, the Crown's own thorns, Forest of
                    Impalement, and any Black Thorn action whose cost includes a Spine) ignores those two Resistances.
Calamity Briar Incarnation (rider lane C7)  while its state "calamity_briar_incarnation" is on: unarmed strikes use a d12
                    base die (attack_damage), once per turn a hit adds 4d8 Piercing or Slashing, the owner gains 1 Spine
                    at the start of each of its turns, and the Forest of Impalement Action (4 Spines) is offered.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

SUBPATH = "tianxia.subpath.body.black_thorn_demon_body.feature."
THORN_FLESH_ARMORY = SUBPATH + "thorn_flesh_armory"
CROWN = SUBPATH + "crown_of_black_thorns"
BRIAR = SUBPATH + "calamity_briar_incarnation"
BRIAR_STATE = "calamity_briar_incarnation"
FOREST = BRIAR + "#forest_of_impalement"
SPINE = "resource:named.demon_spine"
CHOICE = "condition:typed.thorn_flesh_armory_choice"
OPTIONS = {"piercing": "Piercing", "slashing": "Slashing"}
PROFILE = "black_thorn_profile"
BODY = "tianxia.path.body_refining"


def _body_numbers(info: dict[str, Any]) -> dict[str, int]:
    """This family's owning Body track; never borrow a different Path's level.

    Explicit multi-Path exports carry paths[].effective_cl/key_ability/PB.
    Single-Path sheets carry identity.path and the ordinary compiled numbers.
    Acquisition and restricted-method access remain the native NS1R service's
    responsibility; this projection grants neither a Path nor a feature.
    """
    sheet = info.get("owner_sheet") or {}
    paths = (sheet.get("path_and_subpath") or {}).get("paths") or []
    numbers = dict(info["numbers"])
    if not paths:
        path = str((sheet.get("identity") or {}).get("path") or "")
        return numbers if path in (BODY, "Body Refining") else {}
    tracks = [p for p in paths if p.get("path_id") == BODY]
    if len(tracks) != 1:
        return {}
    track = tracks[0]
    cl = track.get("effective_cl", track.get("attainment"))
    if type(cl) is not int or not 0 <= cl <= 20:
        raise ValueError("Black Thorn needs an integer effective Body Refining level from 0 to 20")
    numbers["cl"] = cl
    numbers["pb"] = int(track.get("proficiency_bonus") or 2 + max(0, numbers["cl"] - 1) // 4)
    key = str(track.get("key_ability") or "CON").upper()[:3]
    ability = next((a for a in sheet["ability_scores_and_statistics"]["abilities"]
                    if str(a["ability"]).upper()[:3] == key), None)
    if ability is not None:
        numbers["key_mod"] = int(ability["modifier"]) if "modifier" in ability else (int(ability["score"]) - 10) // 2
        numbers["attack_bonus"] = numbers["pb"] + numbers["key_mod"]
        numbers["save_dc"] = 8 + numbers["attack_bonus"]
    return numbers


@hook("compile_actions")
def body_profile(info: dict[str, Any]) -> None:
    owned = next((mid for mid in info["owned_ids"] if mid.startswith(SUBPATH)), None)
    if owned is None:
        return
    numbers = _body_numbers(info)
    if numbers:
        info["passives"].append({"block": PROFILE, "feature_id": owned,
                                 "numbers": numbers})


@hook("compile_resource_definitions")
def spine_capacity(resources: list[Any], info: dict[str, Any]) -> list[Any] | None:
    if not any(mid.startswith(SUBPATH) for mid in info["owned_ids"]):
        return None
    numbers = _body_numbers(info)
    pb = int(numbers.get("pb", 0)) if int(numbers.get("cl", 0)) >= 3 else 0
    return [r.model_copy(update={"initial": 0, "maximum": pb}) if r.resource_id == SPINE else r
            for r in resources]


def body_numbers(engine: Any, actor: Any) -> dict[str, int]:
    """Public source profile used by this family's delayed Bleeding consumer."""
    return next((dict(row["numbers"]) for row in
                 (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
                 if row.get("block") == PROFILE), {})


def _turn_stamp(engine: Any) -> str:
    actor = engine.state.actors[engine.state.current_actor_id]
    return f"{engine.state.round_number}:{actor.entity_id}:{actor.turns_started}"


def _rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    if int(body_numbers(engine, actor).get("cl", 0)) < 3:
        return []
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "black_thorn_demon_body" and row.get("kind") == "thorn_flesh_armory"]


@hook("compile_block")
def black_thorn_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "black_thorn_demon_body":
        return None
    return [{**row, "block": "black_thorn_demon_body", "kind": spec.get("kind")}]


@hook("compile_actions")
def thorn_choices(info: dict[str, Any]) -> list[Any] | None:
    if THORN_FLESH_ARMORY not in info["owned_ids"] or int(_body_numbers(info).get("cl", 0)) < 3:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.thorn_flesh_armory.{key}", display_name=f"Thorn-Flesh Armory: prefer {label}",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"setting_only": True, "typed": {"source": THORN_FLESH_ARMORY, "min_cl": 3,
                              "effects": [{"type": "thorn_flesh_armory_choice", "choice": key}], "numbers": _body_numbers(info),
                              "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0, "player_only": True})
        for key, label in OPTIONS.items()]


@effect("thorn_flesh_armory_choice")
def thorn_flesh_armory_choice(ctx: Any, eff: dict[str, Any]) -> None:
    if not _rows(ctx.engine, ctx.actor) or eff.get("choice") not in OPTIONS:
        return
    ctx.engine._remove_condition(ctx.actor, CHOICE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, CHOICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"choice": eff.get("choice"), "label": f"Thorn-Flesh Armory: prefer {OPTIONS[str(eff['choice'])]} "
                                      "for the extra damage; choose on each paid hit"})


@hook("after_hit")
def thorn_flesh_armory(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    stamp = _turn_stamp(engine)
    if kind != "unarmed" or not target.active or actor.turn_flags.get("_round_thorn_flesh_armory") == stamp or not _rows(engine, actor):
        return
    if actor.resources.get(SPINE, 0) < 1:
        return
    from .needle import ask, checkpoint_id

    if not ask(engine, ctx.intent, checkpoint_id(engine, "thorn_flesh_armory", actor.entity_id, target.entity_id), actor,
               "choice:needle.thorn_flesh_armory", ["spend"], allow_decline=True, target_id=target.entity_id,
               name="Thorn-Flesh Armory", feature_id=THORN_FLESH_ARMORY,
               labels={"spend": "Spend 1 Demon Spine: +2d6 Piercing or Slashing, then a Constitution save against Bleeding"},
               prompt=f"Thorn-Flesh Armory: {ctx.action.display_name} hit {target.display_name}; spend 1 Demon Spine (once per turn)? "
                      "Add 2d6 Piercing or Slashing, then one Constitution save. On failure, Bleeding lasts until your next turn starts: "
                      f"after {target.display_name}'s next attack (even a miss) or 10 feet of willing movement, "
                      f"it takes {body_numbers(engine, actor)['pb']} damage of the chosen type once.",
               prompt_context={"cost": "1 Demon Spine for this hit", "paying_pool": SPINE}):
        return
    choice = next((str((c.data or {}).get("choice")) for c in actor.conditions.values() if c.condition_id == CHOICE), "piercing")
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "thorn_flesh_armory_type", actor.entity_id, target.entity_id),
                 actor, "choice:needle.thorn_flesh_armory_type", list(OPTIONS), preferred=[choice], labels=OPTIONS,
                 name="Thorn-Flesh Armory", feature_id=THORN_FLESH_ARMORY, target_id=target.entity_id,
                 prompt=f"Thorn-Flesh Armory: choose Piercing or Slashing for the extra 2d6 and delayed Bleeding "
                        f"from your {ctx.action.display_name} hit on {target.display_name}. This costs 1 Demon Spine.",
                 prompt_context={"cost": "1 Demon Spine for this hit", "paying_pool": SPINE})
    if not picked:
        return
    choice = picked[0]
    actor.turn_flags["_round_thorn_flesh_armory"] = stamp
    engine._spend_resource(actor, SPINE, 1, THORN_FLESH_ARMORY)
    damage_type = "slashing" if choice == "slashing" else "piercing"
    from .. import typed_executor

    sub = ctx.on_hit_context(target, action=ctx.action,
        typed={**ctx.typed, "numbers": body_numbers(engine, actor)}, damage_cache={}).with_source(THORN_FLESH_ARMORY)
    with spine_damage(engine, actor.entity_id):
        typed_executor.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 2, "sides": 6},
                                          "damage_types": [damage_type], "evidence": "Thorn-Flesh Armory: 2d6 Piercing or Slashing"}])
    if not target.active:
        return
    typed_executor.run_effects(sub, [{"type": "save", "ability": "con", "applies_to": "target",
                                      "on_fail": [{"type": "thorn_bleeding", "condition": "bleeding", "applies_to": "target",
                                                   "damage_type": damage_type,
                                                   "expires_on": "START_OF_SOURCE_NEXT_TURN"}],
                                      "on_success": [], "evidence": "Thorn-Flesh Armory: Constitution saving throw"}])


@hook("attack_damage_type_choice")
def strike_type(ctx: Any, attack: dict[str, Any], target: Any, kinds: list[str], attack_index: int) -> str | None:
    if not _rows(ctx.engine, ctx.actor) or target is None:
        return None
    from ..weapon_delivery import delivery_kind
    if delivery_kind(ctx.typed, attack, ctx.action.parameters) != "unarmed":
        return None
    # Iron Fist already owns the identical per-strike question for its weapon.
    if (ctx.typed.get("weapon") or {}).get("natural_source") == "tianxia.path.body_refining.feature.iron_fist":
        return None
    from .needle import ask, checkpoint_id
    from ..typed_executor import choose_damage_type
    picked = ask(ctx.engine, ctx.intent,
        checkpoint_id(ctx.engine, "thorn_strike_type", ctx.actor.entity_id, target.entity_id, attack_index),
        ctx.actor, "choice:needle.thorn_strike_type", list(kinds),
        preferred=[choose_damage_type(ctx, kinds, [target])], labels={k: k.title() for k in kinds},
        name="Thorn-Flesh Armory", feature_id=THORN_FLESH_ARMORY, target_id=target.entity_id,
        prompt=f"Thorn-Flesh Armory: choose the damage type of {ctx.action.display_name}, attack {attack_index}, "
               f"against {target.display_name}. The strike's damage and cost stay the same.")
    return picked[0] if picked else None


@hook("attack_damage_types")
def strike_types(ctx: Any, attack: dict[str, Any], kinds: list[str]) -> list[str] | None:
    if not _rows(ctx.engine, ctx.actor):
        return None
    from ..weapon_delivery import delivery_kind
    if delivery_kind(ctx.typed, attack, ctx.action.parameters) != "unarmed":
        return None
    return list(dict.fromkeys([*kinds, "BLUDGEONING", "PIERCING", "SLASHING"]))


@hook("state_event")
def spine_damage_receipt(engine: Any, event: Any) -> None:
    """Sole normal Spine producer. The shared pool helper owns cap/cadence."""
    if (event.event_type != "DAMAGE_COMMITTED" or int(event.payload.get("hp_damage", 0)) < 1
            or int(event.payload.get("hp_before", 0)) < 1 or event.payload.get("gate_damage")):
        return
    source = engine.state.actors.get(event.actor_id)
    if source is None or source.summon or source.owner_id:
        return
    from .subpath_pools import gain, maximum
    from .reach_bonus import natural_reach_ft
    for target_id in event.target_ids:
        owner = engine.state.actors[target_id]
        if (owner is source or not owner.active or int(body_numbers(engine, owner).get("cl", 0)) < 3
                or SPINE not in owner.resources or owner.resources[SPINE] >= maximum(engine, owner, SPINE)
                or owner.turn_flags.get("_round_pool_gain:" + SPINE) == int(engine.state.round_number)):
            continue
        if (str(event.payload.get("damage_type", "")).upper() not in ("PIERCING", "SLASHING")
                and engine._distance_actor_to_actor(owner, source) > natural_reach_ft(engine, owner)):
            continue
        if _hostile_damage(engine, owner, source, event):
            gain(engine, owner, SPINE, "system:black_thorn_damage")


def _hostile_damage(engine: Any, owner: Any, source: Any, event: Any) -> bool:
    """Controller-owned hostility, never a guessed damage tag or team test.

    Human sources can distinguish real hostility from consensual training even
    on the same side. Automatic sources cannot attest an unknown scene fact.
    Their ordinary hostile intent is established by the native enemy relation;
    neutral/allied automatic sources conservatively supply no declaration.
    """
    from ..relations import relation, ENEMY
    from ..fact_consent_admission import admit_choice
    from ..gate2_runtime_models import ActionDefinition
    from ..typed_executor import Context
    from .effect_durations import token
    from .ability_source import source_label
    intent = getattr(engine, "_active_intent", None)
    if intent is None:
        return False
    action = ActionDefinition(source_definition_id=THORN_FLESH_ARMORY, display_name="Demon Spines",
        owner_id=owner.entity_id, economy="NONE", resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"numbers": body_numbers(engine, owner)}})
    ctx = Context(engine, owner, action, intent, action.parameters["typed"], [source], source, {})
    current = engine.state.actors[engine.state.current_actor_id]
    triggering_action = source_label(engine, event.source_definition_id)
    record = admit_choice(ctx, source, THORN_FLESH_ARMORY, "demon_spine_hostility",
        f"{engine.state.match_id}:{event.sequence}:{owner.entity_id}", ["hostile", "excluded"],
        labels={"hostile": "Genuine hostile damage; not willing help, training, a cost, or resource farming",
                "excluded": "Willing help, training, a cost, or resource farming: no Demon Spine"},
        prompt=f"Demon Spines: {source.display_name}'s {triggering_action} damaged {owner.display_name}. "
               "Was this genuine hostile force? Qualifying Hit Point damage grants 1 Spine, at most once per round, "
               "up to Proficiency Bonus; Spines expire at scene end. Only the damaging creature's controller declares its intent.",
        expires_on=token("end", current.entity_id, current.turns_started), readers=(),
        automatic_options=["hostile"] if relation(engine, source, owner) == ENEMY else [])
    return bool(record and record["value"] == "hostile")


@hook("choice_reactors")
def spine_source_controllers(engine: Any) -> tuple[str, ...]:
    if not any(int(body_numbers(engine, actor).get("cl", 0)) >= 3 for actor in engine.state.actors.values()):
        return ()
    from ..tabletop_service import MANUAL_MODES
    return tuple(aid for aid, mode in (getattr(engine, "typed_control_modes", {}) or {}).items()
                 if mode in MANUAL_MODES)


@hook("scene_end")
def shed_spines(engine: Any) -> None:
    for actor in engine.state.actors.values():
        if body_numbers(engine, actor) and actor.resources.get(SPINE, 0) > 0:
            engine._spend_resource(actor, SPINE, actor.resources[SPINE], "system:black_thorn_scene_end")


# ------------------------------------------------------------------------------------------------ Crown of Black Thorns
from contextlib import contextmanager


@contextmanager
def spine_damage(engine: Any, source_actor_id: str):
    """Scope this actor's Spine packets, including delayed Bleeding's packet.

    Shared with thorn_bleeding. A nested counter from a different creature is
    not Spine damage. Transient only; restored on pause, failure and completion.
    """
    previous = engine.__dict__.get("_black_thorn_spine_damage")
    engine.__dict__["_black_thorn_spine_damage"] = source_actor_id
    try:
        yield
    finally:
        engine.__dict__["_black_thorn_spine_damage"] = previous


@effect("black_thorn_spine_damage")
def spine_damage_rows(ctx: Any, row: dict[str, Any]) -> None:
    """{"type": "black_thorn_spine_damage", "effects": [...]}: the nested rows' damage is Demon Spine damage."""
    from ..typed_executor import run_effects

    with spine_damage(ctx.engine, ctx.actor.entity_id):
        run_effects(ctx, row.get("effects") or [])


def _owns(engine: Any, actor: Any, feature: str) -> bool:
    return any(str(row.get("feature_id") or "") == feature for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))


def _spends_spines(engine: Any, typed: dict[str, Any]) -> bool:
    source = str((typed or {}).get("source") or "")
    if not source.startswith(SUBPATH):
        return False
    return any(resource == SPINE for action in engine.action_catalog.values()
               for resource, _amount in action.costs if ((action.parameters or {}).get("typed") or {}).get("source") == source)


@hook("resistance_ignored")
def spine_damage_pierces(engine: Any, kind: str, typed: dict[str, Any], source_actor_id: str | None, target: Any = None) -> bool | None:
    if str(kind).upper() not in ("PIERCING", "SLASHING"):
        return None
    actor = engine.state.actors.get(str(source_actor_id or ""))
    if actor is None or not _owns(engine, actor, CROWN):
        return None
    if engine.__dict__.get("_black_thorn_spine_damage") == source_actor_id or _spends_spines(engine, typed or {}):
        return True
    return None


# ------------------------------------------------------------------------------------------ Calamity Briar Incarnation
def _briar(engine: Any, actor: Any) -> Any:
    from .states import active

    return active(engine, actor, BRIAR_STATE)


def _unarmed_attack(ctx: Any) -> bool:
    return ".natural." in ctx.source or any(isinstance(e, dict) and e.get("type") == "attack" and e.get("attack_kind") == "unarmed"
                                            for e in ctx.typed.get("effects") or [])


@hook("attack_damage")
def briar_die(ctx: Any, dice: Any) -> Any:
    """"Unarmed strikes deal 1d12 before modifiers": 1d12 replaces the strike's base dice; its modifier is kept."""
    if dice is None or not _unarmed_attack(ctx) or not _briar(ctx.engine, ctx.actor):
        return None
    return dice.model_copy(update={"count": 1, "sides": 12})


@hook("after_hit")
def briar_thorns(ctx: Any, target: Any, kind: str) -> None:
    """"Once per turn on a hit, additional 4d8 Piercing or Slashing"."""
    engine, actor = ctx.engine, ctx.actor
    if target is None or not target.active or not _briar(engine, actor):
        return
    stamp = f"{engine.state.round_number}:{engine.state.current_actor_id}"
    if actor.turn_flags.get("_round_calamity_briar_hit") == stamp:
        return
    actor.turn_flags["_round_calamity_briar_hit"] = stamp
    from .. import typed_executor

    sub = ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={})
    typed_executor.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 4, "sides": 8},
                                      "damage_types": ["piercing", "slashing"],
                                      "evidence": "Calamity Briar Incarnation: once per turn on a hit, additional 4d8 Piercing or Slashing"}])


@hook("turn_start")
def briar_growth(engine: Any, actor: Any) -> None:
    """"Gain 1 Demon Spine at the start of each turn" (a direct gain)."""
    if actor.active and SPINE in actor.resources and _briar(engine, actor):
        engine._gain_resource(actor, SPINE, 1, BRIAR)


@hook("compile_actions")
def forest_of_impalement(info: dict[str, Any]) -> list[Any] | None:
    if BRIAR not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from .states import PREFIX

    typed = {
        "source": FOREST, "area": {"shape": "sphere", "size_ft": 30}, "numbers": info["numbers"],
        "duration": {"kind": "until_start_of_next_turn", "amount": None, "concentration": False},
        "effects": [{"type": "black_thorn_spine_damage", "effects": [{"type": "save", "ability": "dex", "evidence": "Forest of Impalement: Dexterity saving throw",
                     "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 8, "sides": 8}, "damage_types": ["piercing"],
                                  "evidence": "8d8 Piercing"},
                                 {"type": "condition", "applies_to": "target", "condition": "restrained", "duration": "one_minute",
                                  "repeat_save": {"ability": "DEX", "when": "end"},
                                  "condition_data": {"forest_lift": 1},
                                  "evidence": "Restrained; it repeats the Dexterity save at the end of each turn, ending it on a success"},
                                 {"type": "thorn_bleeding", "applies_to": "target", "damage_type": "piercing",
                                  "expires_on": "START_OF_SOURCE_NEXT_TURN", "evidence": "Bleeding"},
                                 {"type": "thorn_forest_lift"}],
                     "on_success": [{"type": "half_damage", "applies_to": "target", "damage_types": ["piercing"]},
                                    {"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away",
                                     "evidence": "pushed 10 feet"}]}]}],
        "zone_spec": {"name": "Forest of Impalement", "centered_on_self": True, "follows_owner": True, "shape": "sphere", "size_ft": 30,
                      "difficult": "hostile", "duration": {"kind": "until_start_of_next_turn"}, "visual": {"material": "thorns"}},
        "riders": [],
    }
    with_spine = {"typed": typed, "requires_condition": PREFIX + BRIAR_STATE, "expected_damage": 36}
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.forest_of_impalement", display_name="Forest of Impalement",
        owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="SELF", range_ft=None,
        costs=((SPINE, 4),), parameters=with_spine)]


@hook('healing_pending')
def flesh_rejects_gentleness(engine: Any, target: Any, amount: int, healer: Any, source: str, kind: str) -> int | None:
    if kind != 'hp' or target is None or healer is None or healer.entity_id == target.entity_id or SPINE not in target.resources:
        return None
    numbers = body_numbers(engine, target)
    if int(numbers.get('cl', 0)) < 3:
        return None
    threshold = 6 if _briar(engine, target) else 3
    if target.resources[SPINE] >= threshold:
        return min(max(0, amount-1), int(numbers['pb']))
    return None


@effect('thorn_forest_lift')
def forest_lift(ctx: Any, row: dict[str, Any]) -> None:
    from .. import movement_paths
    target=ctx.target
    if target is None:
        return
    # The failed-save condition and this rider share one execute_intent. Use
    # that intent's condition event to identify this activation's restraint;
    # source ownership alone is ambiguous when Forest is applied repeatedly.
    restraint_event = next((event for event in reversed(ctx.engine.events)
        if event.event_type == 'CONDITION_APPLIED'
        and event.trigger_or_intent_id == ctx.intent.intent_id
        and event.actor_id == ctx.actor.entity_id
        and target.entity_id in event.target_ids
        and event.payload.get('condition_id') == 'condition:typed.restrained'), None)
    restraint = target.conditions.get((restraint_event.payload.get('instance_id')
        if restraint_event is not None else ''))
    if restraint is not None and not restraint.data.get('forest_lift'):
        restraint = None
    if restraint is None:
        return
    before = set(target.conditions)
    ctx.engine._apply_condition(target,'condition:typed.forest_lift',ctx.source,ctx.actor.entity_id,
        expires_on='UNTIL_REMOVED',data={'restraint':restraint.instance_id,'flight_suspended':1,
                                       'label':'Forest of Impalement: held aloft; land safely when released'})
    # _apply_condition intentionally returns None. Resolve the receipt from the
    # condition state it just changed, and stop if a general immunity prevented
    # the suspension from being applied.
    held = next((condition for iid, condition in target.conditions.items()
                 if iid not in before and condition.condition_id == 'condition:typed.forest_lift'
                 and condition.source_actor_id == ctx.actor.entity_id
                 and condition.data.get('restraint') == restraint.instance_id), None)
    if held is None:
        return
    start = target.position
    path = [start]
    for step in range(1, 3):
        path.append(start.model_copy(update={'z': start.z + step}))
    moved = movement_paths.resolve(ctx.engine, target, path, ctx.source, kind='forced',
        intent=ctx.intent, provokes=False, source_actor_id=ctx.actor.entity_id, ctx=ctx)
    if moved == 0:
        # Suspension is needed while the path resolves so an already-airborne
        # target cannot fall mid-lift. Keep the linked receipt only when this
        # Forest actually displaced the target.
        from .condition_ownership import remove_instance
        remove_instance(ctx.engine, target, held.instance_id, ctx.source)


@hook('state_event')
def forest_release(engine: Any, event: Any) -> None:
    if event.event_type!='CONDITION_REMOVED':
        return
    removed=event.payload.get('instance_id')
    from ..falling import landing
    from ..flight import profile
    from .condition_ownership import remove_instance
    for aid in event.target_ids:
        target=engine.state.actors[aid]
        for held in list(target.conditions.values()):
            if held.condition_id!='condition:typed.forest_lift' or held.data['restraint']!=removed:
                continue
            # Query independent support before emitting removal: native condition
            # removal settles unsupported falls immediately. Keep this receipt
            # through the final safe landing, then remove only this linked hold.
            if profile(engine,target,excluding_conditions=(held.instance_id,)).suspended:
                remove_instance(engine,target,held.instance_id,held.source_definition_id)
                continue
            end=landing(engine,target)
            if end is not None and target.position!=end:
                start=target.position;target.position=end
                engine._append_event('MOVEMENT_COMMITTED',held.source_definition_id,actor_id=aid,
                    payload={'destination':end.model_dump(mode='json'),'path':[start.model_dump(mode='json'),end.model_dump(mode='json')],
                             'cost_ft':0,'forced':True,'safe_landing':True})
            remove_instance(engine,target,held.instance_id,held.source_definition_id)
