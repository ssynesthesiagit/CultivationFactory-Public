"""Black Thorn Demon Body Subpath (subpaths worker 2026-09-28: "make sure all the talents and class abilities ...
is applied").

Thorn-Flesh Armory  once per turn, on an unarmed-strike hit, spend 1 Demon Spine: add 2d6 Piercing or Slashing (a
                    free player choice, kept until changed -- default Piercing), then a Constitution save; on a
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
from ..activation_settlement import path_numbers

SUBPATH = "tianxia.subpath.body.black_thorn_demon_body.feature."
THORN_FLESH_ARMORY = SUBPATH + "thorn_flesh_armory"
CROWN = SUBPATH + "crown_of_black_thorns"
BRIAR = SUBPATH + "calamity_briar_incarnation"
BRIAR_STATE = "calamity_briar_incarnation"
FOREST = BRIAR + "#forest_of_impalement"
SPINE = "resource:named.demon_spine"
VIOLENCE = SUBPATH + "spines_answer_violence"
GARDEN = SUBPATH + "impaling_garden"
CHOICE = "condition:typed.thorn_flesh_armory_choice"
OPTIONS = {"piercing": "Piercing", "slashing": "Slashing"}
LEVELS = {THORN_FLESH_ARMORY: 3, VIOLENCE: 6, GARDEN: 10, CROWN: 14, BRIAR: 18}
BODY_PATH = "tianxia.path.body_refining"


@hook("compile_actions")
def source_profile(info: dict[str, Any]) -> None:
    """Seal the family's owning-Path numbers through the coordinated public seam."""
    owned = [mid for mid in info['owned_ids'] if mid in LEVELS]
    if owned:
        info['passives'].append({'feature_id': owned[0], 'block':'black_thorn_profile',
            'numbers':path_numbers(info, BODY_PATH)})


@hook('compile_resource_definitions')
def spine_capacity(resources: list[Any], info: dict[str, Any]) -> list[Any] | None:
    if not any(mid in LEVELS for mid in info['owned_ids']):
        return None
    pb = int(path_numbers(info, BODY_PATH)['pb'])
    return [row.model_copy(update={'initial':0, 'maximum':pb}) if row.resource_id == SPINE else row
            for row in resources]


def _numbers(engine: Any, actor: Any, fallback: dict | None = None) -> dict:
    return next((dict(row['numbers']) for row in engine.typed_passive_rows.get(actor.entity_id, [])
                 if row.get('block') == 'black_thorn_profile'), dict(fallback or {}))


def _turn_stamp(engine: Any) -> str:
    current = engine.state.actors.get(engine.state.current_actor_id)
    return f"{engine.state.round_number}:{engine.state.current_actor_id}:{current.turns_started if current else 0}"


def _rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    if int(_numbers(engine, actor, {'cl':3}).get('cl', 3)) < 3:
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
    if THORN_FLESH_ARMORY not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.thorn_flesh_armory.{key}", display_name=f"Thorn-Flesh Armory: {label}",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"setting_only": True, "typed": {"effects": [{"type": "thorn_flesh_armory_choice", "choice": key}], "numbers": info["numbers"],
                              "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0, "player_only": True})
        for key, label in OPTIONS.items()]


@effect("thorn_flesh_armory_choice")
def thorn_flesh_armory_choice(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, CHOICE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, CHOICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"choice": eff.get("choice"), "label": f"Thorn-Flesh Armory: {OPTIONS.get(str(eff.get('choice')), '')}"})


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
               labels={"spend": "Spend 1 Demon Spine: +2d6 Piercing or Slashing, then a Constitution save against Bleeding"},
               prompt=f"Thorn-Flesh Armory: {ctx.action.display_name} hit {target.display_name}; spend 1 Demon Spine (once per turn)?"):
        return
    actor.turn_flags["_round_thorn_flesh_armory"] = stamp
    engine._spend_resource(actor, SPINE, 1, f"passive:{THORN_FLESH_ARMORY}")
    choice = next((str((c.data or {}).get("choice")) for c in actor.conditions.values() if c.condition_id == CHOICE), "piercing")
    chosen_type = ask(engine, ctx.intent, checkpoint_id(engine, "thorn_flesh_armory_type", actor.entity_id, target.entity_id),
        actor, "choice:needle.thorn_flesh_armory_type", list(OPTIONS), preferred=[choice],
        labels=OPTIONS, target_id=target.entity_id,
        prompt=f"Thorn-Flesh Armory: choose the type of the additional 2d6 damage and Bleeding against {target.display_name} (1 Demon Spine spent).")
    if chosen_type:
        choice = chosen_type[0]
    damage_type = "slashing" if choice == "slashing" else "piercing"
    from .. import typed_executor

    sub = ctx.on_hit_context(target, action=ctx.action,
        typed={**ctx.typed, 'numbers':_numbers(engine, actor, ctx.numbers)}, damage_cache={}).with_source(THORN_FLESH_ARMORY)
    with spine_damage(engine, actor.entity_id):
        typed_executor.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 2, "sides": 6},
                                          "damage_types": [damage_type], "evidence": "Thorn-Flesh Armory: 2d6 Piercing or Slashing"}])
    if not target.active:
        return
    delayed = any(row.get("block") == "path_rider" and row.get("kind") == "thorn_bleeding"
                  for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))
    typed_executor.run_effects(sub, [{"type": "save", "ability": "con", "applies_to": "target",
                                      "on_fail": [{"type": "thorn_bleeding" if delayed else "condition", "condition": "bleeding", "applies_to": "target",
                                                   "damage_type": damage_type,
                                                   "expires_on": "START_OF_SOURCE_NEXT_TURN"}],
                                      "on_success": [], "evidence": "Thorn-Flesh Armory: Constitution saving throw"}])


# ------------------------------------------------------------------------------------------------ Crown of Black Thorns
from contextlib import contextmanager


@contextmanager
def spine_damage(engine: Any, source_actor_id: str):
    """Scope this source's Spine packets; nested damage by another actor is not marked.

    Public helper shared with thorn_bleeding. Transient, restored even when a
    choice pauses; no marker is retained in saved fight state.
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
    return any(str(row.get("feature_id") or "") == feature
               for name in ("typed_passive_rows", "typed_reaction_rows")
               for row in (getattr(engine, name, {}) or {}).get(actor.entity_id, [])) or any(
                   action.owner_id == actor.entity_id and
                   ((action.parameters or {}).get("typed") or {}).get("source") == feature
                   for action in engine.action_catalog.values())


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
    stamp = _turn_stamp(engine)
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
        "source": FOREST, "area": {"shape": "sphere", "size_ft": 30}, "numbers": path_numbers(info, BODY_PATH), "min_cl":18,
        "duration": {"kind": "until_start_of_next_turn", "amount": None, "concentration": False},
        "effects": [{"type": "black_thorn_spine_damage", "effects": [{"type": "save", "ability": "dex", "evidence": "Forest of Impalement: Dexterity saving throw",
                     "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 8, "sides": 8}, "damage_types": ["piercing"],
                                  "evidence": "8d8 Piercing"},
                                 {"type": "condition", "applies_to": "target", "condition": "restrained", "expires_on": "UNTIL_REMOVED",
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
    if not any(_owns(engine, target, SUBPATH + name) for name in (
            'thorn_flesh_armory', 'spines_answer_violence', 'impaling_garden',
            'crown_of_black_thorns', 'calamity_briar_incarnation')):
        return None
    threshold = 6 if _briar(engine, target) else 3
    if target.resources[SPINE] >= threshold:
        pb = int(_numbers(engine, target, {'pb':int(target.proficiency_bonus or 2)})['pb'])
        return min(max(0, amount-1), pb)
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


def _native_bleeding(value: Any) -> Any:
    """Normalize this family's consumers to its one supernatural Bleeding provider."""
    if isinstance(value, list):
        return [_native_bleeding(item) for item in value]
    if not isinstance(value, dict):
        return value
    out = {key: _native_bleeding(item) for key, item in value.items()}
    if out.get("type") == "condition" and out.get("condition") == "bleeding":
        out.update(type="thorn_bleeding", damage_type="piercing")
    return out


@hook("compile_action")
def native_family_action(action: Any, info: dict[str, Any]) -> Any:
    typed = (action.parameters or {}).get('typed')
    if typed is not None and any(mid in LEVELS for mid in info['owned_ids']):
        # One owned action advertises that the family's native damage observer
        # can ask a different manual source creature, even on an AI turn.
        action = action.model_copy(update={'parameters':{**action.parameters,
            'typed':{**typed, 'manual_inline_choice':True}}})
    rule = (action.parameters or {}).get("reach_bonus") or {}
    if rule.get("feature_id") == CROWN:
        return action.model_copy(update={"parameters": {**action.parameters,
            "reach_bonus": {**rule, "excluded_states": [BRIAR_STATE]}}})
    typed = (action.parameters or {}).get("typed") or {}
    feature = str(typed.get('source') or '').partition('#')[0]
    if feature not in LEVELS:
        return action
    typed = _native_bleeding(typed)
    typed['numbers'] = path_numbers(info, BODY_PATH)
    typed['min_cl'] = LEVELS[feature]
    if typed.get("source") == GARDEN and typed.get("zone_spec"):
        typed["zone_spec"] = {**typed["zone_spec"], "centered_on_self": True, "follows_owner": True}
    return action.model_copy(update={"parameters": {**action.parameters, "typed": typed}})


def _qualifying_source(engine: Any, owner: Any, source: Any, event: Any) -> bool:
    if source is None or source is owner or source.summon:
        return False
    if source.team_id != owner.team_id:
        return True
    # Team membership is not willingness. Only this source creature's actual
    # controller may supply its subjective hostility/non-farming declaration.
    intent = getattr(engine, '_active_intent', None)
    if intent is None:
        return False
    from ..fact_consent_admission import admit_choice
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..typed_executor import Context
    from .effect_durations import token
    current = engine.state.actors[engine.state.current_actor_id]
    family = SUBPATH.removesuffix('.feature.')
    action = ActionDefinition(source_definition_id=family, display_name='Demon Spines',
        owner_id=owner.entity_id, economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF',
        parameters={'typed':{'numbers':_numbers(engine, owner), 'manual_inline_choice':True}})
    ctx = Context(engine, owner, action, intent, action.parameters['typed'], [source], source, {})
    record = admit_choice(ctx, source, family, 'qualifying_hostility',
        f'{engine.state.match_id}:{event.sequence}:{owner.entity_id}', ['hostile','excluded'],
        labels={'hostile':'This was genuine hostile force; not a willing ally, controlled creature, cost or farming',
                'excluded':'Exclude this damage: willing ally, controlled creature, cost or farming'},
        prompt=f'Demon Spines: {source.display_name} damaged {owner.display_name}. '
               'Declare whether this was genuine hostile force rather than willing help or resource farming. '
               'A qualifying positive Hit Point loss grants 1 Demon Spine, at most once per round and up to its maximum; '
               'the Spine lasts until this continuous scene ends. '
               f'Only {source.display_name}\'s controller may read this declaration; it grants no information to other creatures.',
        expires_on=token('end',current.entity_id,current.turns_started), readers=(), automatic_options=())
    return record is not None and record['value'] == 'hostile'


@hook('state_event')
def native_spine_gain(engine: Any, event: Any) -> None:
    """The family's sole normal producer, from committed HP damage and owned facts."""
    if event.event_type != 'DAMAGE_COMMITTED' or int(event.payload.get('hp_damage') or 0) < 1 or event.payload.get('gate_damage'):
        return
    from .subpath_pools import gain, maximum
    from .reach_bonus import natural_reach_ft
    from .damage_provenance import excluded_by_provenance
    from ..pending_damage import current
    # Farming, training, self-inflicted and cost-paid packets are not hostile harm, even from an opposing team.
    if excluded_by_provenance(current(engine)):
        return
    source = engine.state.actors.get(event.actor_id)
    kind = str(event.payload.get('damage_type') or '').upper()
    for target_id in event.target_ids:
        owner = engine.state.actors.get(target_id)
        if owner is None or not owner.active or SPINE not in owner.resources or not _numbers(engine, owner):
            continue
        if owner.turn_flags.get('_round_pool_gain:'+SPINE) == int(engine.state.round_number):
            continue
        if int(owner.resources[SPINE]) >= maximum(engine, owner, SPINE):
            continue
        if kind not in ('PIERCING','SLASHING') and (source is None or
                engine._distance_actor_to_actor(owner, source) > natural_reach_ft(engine, owner)):
            continue
        if _qualifying_source(engine, owner, source, event):
            gain(engine, owner, SPINE, 'system:black_thorn_damage')


@hook("reaction_rows")
def native_family_reactions(engine: Any, actor_id: str, block: str, rows: list[dict]) -> list[dict] | None:
    if block != "generic":
        return None
    # Crown is settled at each paid step by its sole producer below. Do not
    # also dispatch the old end-of-route enters_range/moved interpretations.
    result = []
    for row in rows:
        if row.get("feature_id") == CROWN:
            continue
        if row.get("feature_id") == VIOLENCE:
            from .reach_bonus import natural_reach_ft
            row = _native_bleeding(row)
            row['numbers'] = _numbers(engine, engine.state.actors[actor_id], row.get('numbers'))
            row['min_cl'] = 6
            row["range_ft"] = natural_reach_ft(engine, engine.state.actors[actor_id])
            row["source_within_reach"] = False
            row["effects"] = [{"type": "black_thorn_spine_damage", "effects": row["effects"]}]
        result.append(row)
    return result


@hook('reaction_reach')
def violence_body_reach(engine: Any, reactor: Any, other: Any, row: dict) -> bool | None:
    """The body's occupied volume, including Large, is the printed reach origin."""
    if row.get('feature_id') != VIOLENCE or not _owns(engine, reactor, VIOLENCE) or other is None:
        return None
    from .reach_bonus import natural_reach_ft
    return engine._distance_actor_to_actor(reactor, other) <= natural_reach_ft(engine, reactor)


def _grapple_answer(engine: Any, owner: Any, grappler: Any, checkpoint: str, source_id: str) -> None:
    from ..typed_reactions import on_own_event
    if owner is not None and grappler is not None:
        on_own_event(engine, owner, grappler, "hit", ranged=False,
                     accept=lambda row: row.get("feature_id") == VIOLENCE,
                     source_id=source_id, checkpoint=checkpoint, trigger_actor_id=grappler.entity_id,
                     action_name=(f"{grappler.display_name} begins its turn Grappling {owner.display_name}"
                                  if checkpoint == "GRAPPLER_TURN_START" else
                                  f"{grappler.display_name} Grapples {owner.display_name}"))


@hook("state_event")
def acquired_grapple(engine: Any, event: Any) -> None:
    if event.event_type != "CONDITION_APPLIED":
        return
    from .passive_traits import is_grapple
    for target_id in event.target_ids:
        owner = engine.state.actors.get(target_id)
        held = owner.conditions.get(event.payload.get("instance_id")) if owner is not None else None
        if held is not None and is_grapple(held):
            _grapple_answer(engine, owner, engine.state.actors.get(held.source_actor_id),
                            "GRAPPLE_ESTABLISHED", event.source_definition_id)


@hook("turn_start_choice")
def grappler_turn(engine: Any, actor: Any) -> None:
    from .passive_traits import is_grapple
    event = next((e for e in reversed(engine.events)
                  if e.event_type == "TURN_STARTED" and e.actor_id == actor.entity_id), None)
    if event is None:
        return
    for owner in engine.state.actors.values():
        if any(is_grapple(c) and c.source_actor_id == actor.entity_id
               for c in owner.conditions.values()):
            _grapple_answer(engine, owner, actor, "GRAPPLER_TURN_START", event.source_definition_id)


def _crown_record(engine: Any, owner: Any, mover: Any) -> Any:
    return next((c for c in owner.conditions.values()
                 if c.condition_id == "condition:typed.black_thorn_movement"
                 and c.data.get("mover") == mover.entity_id), None)


@effect("black_thorn_stop")
def crown_failed_save(ctx: Any, row: dict[str, Any]) -> None:
    """Resolution-local result of Crown's final failed-save branch, never saved."""
    if ctx.typed.get("source") == CROWN:
        ctx.damage_cache["black_thorn_stop"] = 1


@hook("state_event")
def reset_crown_turn(engine: Any, event: Any) -> None:
    if event.event_type != "TURN_STARTED":
        return
    from .condition_ownership import remove_instance
    for owner in engine.state.actors.values():
        for c in list(owner.conditions.values()):
            if c.condition_id == "condition:typed.black_thorn_movement":
                remove_instance(engine, owner, c.instance_id, CROWN)


@hook("movement_step_settled")
def crown_step(engine: Any, mover: Any, previous: Any, destination: Any, intent: Any) -> dict | None:
    """Settle Crown in the first entered qualifying space, never at a route endpoint."""
    from .. import movement_steps, typed_executor
    from ..typed_reactions import can_react
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from .needle import ask, checkpoint_id
    from .reach_bonus import natural_reach_ft

    if movement_steps.context(engine, mover).get("forced"):
        return None
    stop = None
    for owner in engine.state.actors.values():
        row = next((r for r in (getattr(engine, "typed_reaction_rows", {}) or {}).get(owner.entity_id, [])
                    if r.get("feature_id") == CROWN and not r.get("held_back")), None)
        if row is None or not owner.active or owner.team_id == mover.team_id or owner.resources.get(SPINE, 0) < 1:
            continue
        row = {**row, 'numbers':_numbers(engine, owner, row.get('numbers')), 'min_cl':14}
        if not can_react(engine, owner, row, uses_reaction=False):
            continue
        if any(c.condition_id == "condition:typed.black_thorn_movement" and c.data.get("used") == 2
               for c in owner.conditions.values()):
            continue
        record = _crown_record(engine, owner, mover)
        if record is not None and record.data.get("used"):
            continue
        reach = natural_reach_ft(engine, owner)
        before = engine._distance_actor_to_actor(owner, mover, target_position=previous)
        after = engine._distance_actor_to_actor(owner, mover, target_position=destination)
        distance = int(engine.grid.distance_ft(previous, destination)) if before <= reach and after <= reach else 0
        cumulative = int(record.data.get("distance", 0) if record else 0) + distance
        qualifies = before > reach >= after or cumulative >= 10
        data = {"mover": mover.entity_id, "distance": cumulative, "used": 0,
                "label": f"Crown of Black Thorns: tracking {mover.display_name}'s willing movement this turn"}
        if record is None:
            engine._apply_condition(owner, "condition:typed.black_thorn_movement", CROWN, owner.entity_id,
                                    expires_on="UNTIL_REMOVED", data=data)
            record = _crown_record(engine, owner, mover)
        else:
            engine._update_condition_data(owner, record, data, CROWN)
        if not qualifies:
            continue
        # A creature reaches its first qualifying space only once this turn,
        # including when the owner declines the optional expenditure.
        engine._update_condition_data(owner, record, {**data, "used": 1}, CROWN)
        if not ask(engine, intent, checkpoint_id(engine, "black_thorn_crown", owner.entity_id, mover.entity_id),
                   owner, "choice:needle.black_thorn_crown", ["spend"], allow_decline=True,
                   target_id=mover.entity_id, labels={"spend": "Spend 1 Demon Spine (no action): Dexterity save; 3d8 Piercing, half on success; failure stops movement and causes Bleeding"},
                   prompt=f"Crown of Black Thorns: {mover.display_name} entered a qualifying space; spend 1 Demon Spine?"):
            continue
        engine._spend_resource(owner, SPINE, 1, CROWN)
        engine._update_condition_data(owner, record, {**data, "used": 2}, CROWN)
        typed = {"source": CROWN, "numbers": row["numbers"], "effects": [], "riders": []}
        action = ActionDefinition(source_definition_id=CROWN, display_name="Crown of Black Thorns",
            owner_id=owner.entity_id, economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY",
            parameters={"typed": typed})
        ctx = typed_executor.Context(engine, owner, action, intent, typed, [mover], mover, {})
        effects = [_native_bleeding(e) for e in row["effects"] if e.get("type") == "black_thorn_spine_damage"]
        for wrapper in effects:
            for save in wrapper.get("effects") or []:
                if save.get("type") == "save":
                    save["on_fail"] = [*(save.get("on_fail") or []), {"type":"black_thorn_stop"}]
        typed_executor.run_effects(ctx, effects)
        if ctx.damage_cache.get("black_thorn_stop"):
            stop = {"stop": True, "source_id": CROWN,
                    "label": f"Crown of Black Thorns stops {mover.display_name} in this space"}
    return stop
