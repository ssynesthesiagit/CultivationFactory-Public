"""Ryūjin Subpath riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Ryūjin (Dragon's Breath, Storm Step, Dragon's Roar, Ryūjin Ascendant Form and their
Normalized Procedures). Storm Step's action runs ``storm_step``; the form is the named state "ryujin_ascendant_form".

Storm Step       teleport to the chosen legal visible space within 30 feet, then each selected, perceived hostile creature
                 within 5 feet of where you arrive makes a Dexterity save: 2d6 Lightning or
                 Thunder and no Reactions until the start of its next turn, or half. A blocked teleport has no burst.
Ascendant Form   Lightning Immunity and Thunder Resistance (typed), +5 ft unarmed reach (reach_bonus), once per turn + 3d6
                 Lightning or Thunder on an unarmed hit, a hostile creature starting its turn within 10 feet makes a Constitution
                 save or is pushed 5 feet and loses its Reactions (a zone following you, typed); while it lasts Dragon's Breath is
                 its "(Ascendant)" profile (30-foot cone, 8d6) and Storm Step costs 1 Stamina once per turn ("(Ascendant)").
The form also grants native Fly Speed 60 feet and Hover; optional Large size uses the recorded growth procedure only when the current anchor fits. Storm Step uses the shared visible landing picker, then chooses only perceived hostile recipients. Every hook returns early without its owned state or effect.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.ryujin.feature."
FORM = "ryujin_ascendant_form"


@hook("compile_action")
def classify_storm_step_movement(action: Any, info: dict[str, Any]) -> Any | None:
    """Ryūjin-owned classification consumed by the shared movement policy."""
    parameters = copy.deepcopy(action.parameters or {})
    typed = parameters.get("typed") or {}
    if typed.get("source") != PREFIX + "storm_step":
        return None
    changed = False
    for row in typed.get("effects") or []:
        if isinstance(row, dict) and row.get("type") == "storm_step" and row.get("self_movement") is not True:
            row["self_movement"] = True
            changed = True
    if not changed:
        return None
    parameters["typed"] = typed
    return action.model_copy(update={"parameters": parameters})


def _form(engine: Any, actor: Any) -> bool:
    from .states import active

    if actor is None:
        return False
    native = next((r for r in engine.typed_passive_rows.get(actor.entity_id, []) if r.get('block') == 'ryujin_native'), None)
    return (native is None or native['effective_cl'] >= 18) and bool(active(engine, actor, FORM))


def _stamp(engine: Any) -> str:
    current = engine.state.actors[engine.state.current_actor_id]
    return f"{engine.state.round_number}:{engine.state.current_slot_index}:{current.entity_id}:{current.turns_started}"


@effect("ryujin_choose_damage")
def choose_damage(ctx: Any, row: dict[str, Any]) -> None:
    damage_choice(ctx, ["LIGHTNING", "THUNDER"], ctx.targets)


@hook("damage_type_choice")
def damage_choice(ctx: Any, kinds: list[str], targets: list[Any]) -> str | None:
    source = str(ctx.typed.get("source") or "")
    if source not in {PREFIX + "dragon_s_breath", PREFIX + "storm_step", PREFIX + FORM}:
        return None
    if "ryujin_damage_type" in ctx.damage_cache:
        return ctx.damage_cache["ryujin_damage_type"]
    from .needle import ask, checkpoint_id
    # Seeing a creature does not reveal its defenses. A deterministic neutral
    # preference uses no hidden sheet information; every legal type remains in
    # the human choice, including an off-turn hit on an automatic actor's turn.
    preferred = kinds[0]
    label = "Ryūjin Ascendant Form" if source == PREFIX + FORM else ctx.action.display_name
    recipients = ", ".join(target.display_name for target in targets) or "creatures in the area"
    cost = sum(amount for resource, amount in ctx.action.costs if resource == "resource:core.stamina")
    prompt = (f"{label}: {ctx.actor.display_name} chooses Lightning or Thunder damage for this use ({cost} Stamina)."
              if source != PREFIX + FORM else
              f"Ryūjin Ascendant Form: choose Lightning or Thunder for {ctx.actor.display_name}'s additional 3d6 damage "
              f"on this unarmed hit against {recipients}, once per turn while the form lasts.")
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "ryujin_damage", ctx.actor.entity_id), ctx.actor,
                 "choice:needle.ryujin_damage", kinds, labels={kind:kind.title() + " damage" for kind in kinds},
                 preferred=[preferred], prompt=prompt)
    ctx.damage_cache["ryujin_damage_type"] = chosen[0] if chosen else preferred
    return ctx.damage_cache["ryujin_damage_type"]


# Dragon's Breath commits its damage type before any recipient's save. The
# same cached activation choice is reused by every save outcome and object.


@hook("flight")
def ascendant_flight(engine: Any, actor: Any) -> dict[str, int] | None:
    return {"fly_speed_ft": 60, "flight_hover": 1} if _form(engine, actor) else None


@effect("ryujin_form_size")
def form_size(ctx: Any, row: dict[str, Any]) -> None:
    from .. import dynamic_size
    from .needle import ask, checkpoint_id
    from ..typed_executor import effect_expiry

    engine, actor = ctx.engine, ctx.actor
    ctx.damage_cache['ryujin_prior_size'] = dynamic_size.current_category(engine, actor)
    if dynamic_size.CATEGORIES.index(dynamic_size.current_category(engine, actor)) >= 3:
        return
    footprint = dynamic_size.shape(engine.actor_footprints[actor.entity_id], "Large")
    if not engine.grid.volume_legal(actor.position, footprint=footprint,
                                    occupied_cells=engine._occupied_volumes_except(actor.entity_id)):
        return
    chosen = ask(engine, ctx.intent, checkpoint_id(engine, "ryujin_size", actor.entity_id), actor,
                 "choice:needle.ryujin_size", ["large"], allow_decline=True,
                 labels={"large": "Become Large until the form ends"},
                 prompt=f"Ryūjin Ascendant Form: {actor.display_name} may become Large, or keep its current size.",
                 target_id=actor.entity_id)
    if chosen:
        dynamic_size.apply_growth(engine, actor, "Large", ctx.source, source_actor_id=actor.entity_id,
                                  expires_on=effect_expiry(ctx, row, actor, condition=True))


@effect("storm_step")
def storm_step(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from ..gate2_runtime_models import Position

    engine, actor = ctx.engine, ctx.actor
    if row.get("once_per_turn"):
        # This is a paid activation. Failed spatial movement or a declined
        # landing cannot refund the form's once-per-turn Storm Step use.
        actor.turn_flags["_round_storm_step"] = _stamp(engine)
    aim = ctx.damage_cache.get("_checkpoint_aim") or ctx.destination
    if aim is None:
        return
    from .teleport_steps import destinations
    from .needle import ask, checkpoint_id
    from .. import senses

    choose_damage(ctx, {})
    start = actor.position
    legal = destinations(engine, actor, int(row.get("range_ft") or 30), action=ctx.action)
    if not legal:
        return
    if aim not in legal:
        ctx.rider(f"Storm Step: {actor.display_name}'s chosen destination is no longer a legal visible space; "
                  "the paid teleport fails and there is no arrival burst.")
        return
    destination = aim
    sub = te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [], None, ctx.damage_cache, destination=destination)
    te.run_effects(sub, [{"type": "teleport", "applies_to": "self", "distance_ft": int(row.get("range_ft") or 30)}])
    if actor.position == start:
        return  # the teleport failed: no arrival burst
    foes = [c for c in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if c.active and c.team_id != actor.team_id
            and engine._distance_actor_to_actor(actor, c) <= 5 and senses.perceives(engine, actor, c)]
    if not foes:
        return
    selected = ask(engine, ctx.intent, checkpoint_id(engine, "storm_recipients", actor.entity_id), actor,
                   "choice:needle.storm_recipients", [c.entity_id for c in foes], maximum=len(foes),
                   allow_decline=True, default="all", preferred=[c.entity_id for c in foes],
                   labels={c.entity_id: c.display_name for c in foes},
                   prompt=f"Storm Step: choose the hostile creatures within 5 feet of {actor.display_name}'s arrival to affect.")
    foes = [c for c in foes if c.entity_id in selected]
    if not foes:
        return
    burst = te.Context(engine, actor, ctx.action, ctx.intent, {**ctx.typed, "_area_centre": (actor.position.x, actor.position.y)},
                       foes, foes[0] if len(foes) == 1 else None,
                       {"ryujin_damage_type": ctx.damage_cache.get("ryujin_damage_type", "LIGHTNING")})
    te.run_effects(burst, [{"type": "save", "ability": "dex", "evidence": "Storm Step: Dexterity saving throw",
                            "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 6}, "damage_types": ["lightning", "thunder"]},
                                        {"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"}],
                            "on_success": [{"type": "half_damage", "applies_to": "target", "damage_types": ["lightning", "thunder"]}]}])


@hook("compile_actions")
def ascendant_profiles(info: dict[str, Any]) -> list[Any] | None:
    """The form's Dragon's Breath (30-foot cone, 8d6) and Storm Step (1 Stamina, once per turn), offered while it lasts."""
    if PREFIX + FORM not in info["owned_ids"]:
        return None
    out = []
    for base in info["actions"]:
        typed = (base.parameters or {}).get("typed") or {}
        source = str(typed.get("source") or "")
        if source == PREFIX + "dragon_s_breath" and "#" not in base.source_definition_id:
            variant = copy.deepcopy(typed)
            for row in variant.get("effects") or []:
                for fail in (row.get("on_fail") or []) if isinstance(row, dict) else []:
                    if isinstance(fail, dict) and fail.get("type") == "damage":
                        fail.pop("dice_by_cl", None)
                        fail["dice"] = {"count": 8, "sides": 6}
            variant["area"] = {**(variant.get("area") or {}), "size_ft": 30}
            out.append(base.model_copy(update={"source_definition_id": base.source_definition_id + "#ascendant", "display_name": base.display_name + " (Ascendant)",
                                               "range_ft": 30, "radius_ft": 30,
                                               "parameters": {**base.parameters, "ryujin_ascendant": True, "typed": variant}}))
        elif source == PREFIX + "storm_step" and "#" not in base.source_definition_id:
            variant = copy.deepcopy(typed)
            for row in variant.get("effects") or []:
                if isinstance(row, dict) and row.get("type") == "storm_step":
                    row["once_per_turn"] = True
            out.append(base.model_copy(update={"source_definition_id": base.source_definition_id + "#ascendant", "display_name": base.display_name + " (Ascendant)",
                                               "costs": tuple((r, 1 if r == "resource:core.stamina" else a) for r, a in base.costs),
                                               "parameters": {**base.parameters, "ryujin_ascendant": True, "ryujin_step": True, "typed": variant}}))
    return out or None


@hook("candidate_allowed")
def ascendant_offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    params = getattr(action, "parameters", None) or {}
    source = str((params.get("typed") or {}).get("source") or "")
    if source.startswith(PREFIX) and 'ryujin_effective_cl' in params:
        minimum = next((level for level, name in PROGRESSION if PREFIX + name == source), 99)
        if params['ryujin_effective_cl'] < minimum:
            return False
    if params.get("ryujin_ascendant"):
        if not _form(engine, actor):
            return False
        if params.get("ryujin_step") and actor.turn_flags.get("_round_storm_step") == _stamp(engine):
            return False
        return None
    if source == PREFIX + "dragon_s_breath" and _form(engine, actor):
        return False  # the form replaces the breath's profile
    if source == PREFIX + "storm_step" and _form(engine, actor):
        return False  # the form replaces the step's price and turn limit
    return None


@hook("compile_passives")
def ryujin_owned_features(passives, info):
    owned = set(info.get('owned_ids') or [])
    rows = [{'block': 'ryujin_feature', 'feature_id': PREFIX + name,
             'level': level, 'pb': int(info['numbers'].get('pb') or 2)}
            for level, name in ((3, 'dragon_scales'), (18, FORM)) if PREFIX + name in owned]
    return [*passives, *rows] if rows else None


@hook("damage_packet_selection")
def ryujin_hit_damage(ctx, target, packet_kinds):
    """Attached confirmed-hit damage, before the primary packet can defeat it.

    One enclosing attack reports the total: neither inheritance damage nor the
    form rider is another hit or an independently triggering damage event.
    The flat scales amount never gains critical dice. Form dice are part of the
    original hit and use its normal critical rule.
    """
    if (ctx.attack_effect or {}).get('attack_kind') != 'unarmed' or target is None:
        return
    from dataclasses import replace
    from .. import typed_executor as te
    features = {r['feature_id']: r for r in ctx.engine.typed_passive_rows.get(ctx.actor.entity_id, [])
                if r.get('block') == 'ryujin_feature'}
    scales = features.get(PREFIX + 'dragon_scales')
    native = next((r for r in ctx.engine.typed_passive_rows.get(ctx.actor.entity_id, []) if r.get('block') == 'ryujin_native'), None)
    if native is not None and native['effective_cl'] < 3:
        scales = None
    form = _form(ctx.engine, ctx.actor)
    stamp = _stamp(ctx.engine)
    flat = 0
    if scales and ctx.actor.turn_flags.get('_round_ryujin_scales') != stamp:
        flat = scales['pb']
    ascendant = form and ctx.actor.turn_flags.get('_round_ryujin_hit') != stamp
    if not flat and not ascendant:
        return
    local = replace(ctx, targets=[target], target=target, damage_cache={'_bonus': True, '_potency_used': True},
                    defer_damage_notifications=True, continue_after_defeat=True)
    selected = 'LIGHTNING'
    if ascendant:
        local = replace(local, typed={**ctx.typed, 'source': PREFIX + FORM})
        selected = damage_choice(local, ['LIGHTNING', 'THUNDER'], [target])
    # Choice pauses happen before consuming either gate. Same-type components
    # share one delivery so Resistance rounding and packet defenses happen once.
    # A critical doubles the form's dice, never the Scales flat modifier.
    from . import effect_permitted
    scales_ctx = replace(local, effect_source=PREFIX + 'dragon_scales', critical_hit=False,
                         damage_cache={'_bonus': True, '_potency_used': True})
    form_ctx = replace(local, effect_source=PREFIX + FORM,
                       damage_cache={'_bonus': True, '_potency_used': True})
    scales_row = {'type': 'damage', 'flat': flat, 'damage_types': ['lightning'],
                  'applies_to': 'target', 'damage_label': 'Dragon Scales'}
    form_row = {'type': 'damage', 'dice': {'count': 3, 'sides': 6},
                'damage_types': [selected.lower()], 'applies_to': 'target',
                'damage_label': 'Ryūjin Ascendant Form'}
    flat = flat if flat and effect_permitted(scales_ctx, scales_row, [target]) else 0
    ascendant = ascendant and effect_permitted(form_ctx, form_row, [target])
    if flat:
        ctx.actor.turn_flags['_round_ryujin_scales'] = stamp
    if ascendant:
        ctx.actor.turn_flags['_round_ryujin_hit'] = stamp
    if flat and ascendant and selected == 'LIGHTNING':
        te.run_effects(form_ctx, [{**form_row, 'flat': flat,
            'damage_label': 'Dragon Scales and Ryūjin Ascendant Form'}])
    else:
        if flat:
            te.run_effects(scales_ctx, [scales_row])
        if ascendant:
            te.run_effects(form_ctx, [form_row])


# Native family acquisition. Shared admission/acquisition transports are the
# committed public contracts owned by the Soul-Collateral contract lane.
PARENT = PREFIX.removesuffix('.feature.')
BODY = 'tianxia.path.body_refining'
PROGRESSION = ((3, 'dragon_scales'), (6, 'dragon_s_breath'), (10, 'storm_step'),
               (14, 'dragon_s_roar'), (18, FORM))


def source_record(session, actor_id):
    """Public acquired-source reader shared with the family's journey clock adapter."""
    return session.state['actors'][actor_id].get('source_states', {}).get(PARENT)


def _body_level(sheet):
    """Actual recorded Body attainment bounded by the installed total CL."""
    paths = sheet.get('path_and_subpath') or {}
    attained = [row.get('effective_cl', row.get('attainment')) for row in paths.get('paths', [])
                if row.get('path_id') == BODY and type(row.get('effective_cl', row.get('attainment'))) is int]
    return min(int((sheet.get('identity') or {}).get('cultivation_level') or 0), max(attained, default=0))


@hook('fact_admission_schema')
def ryujin_declarations(session, source, subject, kind):
    if source != PARENT or subject not in session.state['actors']:
        return None
    if kind == 'source_access':
        return {'value_type': 'document', 'maximum_seconds': 2592000,
                'authority': 'table_owner', 'description': 'GM establishes access to the Rare Inheritance Ryūjin.'}
    if kind == 'anatomy':
        return {'value_type': 'document', 'maximum_seconds': 2592000,
                'description': 'Record your breath organ and whether your inherited scales can be concealed.'}
    return None


def _acquired_sheet(sheet, record):
    updated = copy.deepcopy(sheet)
    paths = updated.setdefault('path_and_subpath', {})
    ids = paths.setdefault('path_feature_record_ids', [])
    # The committed source record owns only this family's progression. Preserve
    # all independent native build choices and never grant unearned milestones.
    ids[:] = [mid for mid in ids if not mid.startswith(PREFIX)]
    available = {PREFIX + name for level, name in PROGRESSION if level <= _body_level(sheet)}
    ids.extend(feature for feature in record['features'] if feature in available)
    subpaths = paths.setdefault('subpath_record_ids', [])
    if PARENT not in subpaths:
        subpaths.append(PARENT)
    paths['ryujin_native'] = copy.deepcopy(record)
    return updated


@hook('journey_source_sheet')
def ryujin_source_sheet(sheet, session, actor_id):
    record = source_record(session, actor_id)
    return _acquired_sheet(sheet, record) if record else None


@hook('journey_acquisition')
def acquire_ryujin(session, actor_id, source, payload, sheet):
    if source != PARENT:
        return None
    from ..fact_consent_admission import read, digest
    from ..journey import require
    require(set(payload) == {'access_scope', 'anatomy_scope'}, 'Choose the recorded inheritance access and anatomy.')
    level = _body_level(sheet)
    require(level >= 3, 'Ryūjin requires effective Body Refining CL3 or higher.')
    access = read(session, PARENT, actor_id, 'source_access', payload['access_scope'], actor_id)
    anatomy = read(session, PARENT, actor_id, 'anatomy', payload['anatomy_scope'], actor_id)
    require(access is not None and access['authority'] == 'table_owner', 'The GM must establish Rare Inheritance access.')
    value = access['value']
    require(isinstance(value, dict) and set(value) == {'category', 'source_rule'}
            and value['category'] == 'Rare Inheritance' and isinstance(value['source_rule'], str)
            and bool(value['source_rule'].strip()), 'Record the source rule establishing Ryūjin inheritance access.')
    require(anatomy is not None and anatomy['authority'] == actor_id, 'Record your own inherited anatomy first.')
    body = anatomy['value']
    require(isinstance(body, dict) and set(body) == {'breath_organ', 'scales'}
            and type(body['breath_organ']) is str and 0 < len(body['breath_organ'].strip()) <= 200
            and body['scales'] in ('visible', 'concealable'), 'Name a recorded breath organ and visible or concealable scales.')
    previous = source_record(session, actor_id)
    require(not previous or level > previous['source_cl'], 'Ryūjin is already acquired at this Body attainment.')
    features = [PREFIX + name for minimum, name in PROGRESSION if minimum <= level]
    record = {'source_cl': level, 'features': features, 'anatomy': copy.deepcopy(body),
              'access_receipt': access['receipt_id'], 'anatomy_receipt': anatomy['receipt_id'],
              'acquired_at': int(session.clock()), 'scene': session.state.get('scene_id', session.state['journey_id'])}
    record['acquisition_id'] = digest(record)
    session.state['actors'][actor_id].setdefault('source_states', {})[PARENT] = record
    session.emit('RYUJIN_ACQUIRED', actor_id, source=PARENT, acquisition_id=record['acquisition_id'],
                 features=features, source_cl=level)
    return {'sheet': _acquired_sheet(sheet, record), 'acquisition_id': record['acquisition_id']}


@hook('compile_bundle')
def ryujin_native_record(bundle, info):
    record = (info['owner_sheet'].get('path_and_subpath') or {}).get('ryujin_native')
    if not record:
        return None
    result = copy.deepcopy(bundle)
    result.setdefault('typed_passives', []).append({'block': 'ryujin_native', 'feature_id': PREFIX + 'dragon_scales',
                                                  'record': copy.deepcopy(record), 'effective_cl': _body_level(info['owner_sheet'])})
    return result


@hook('journey_scene_end')
def ryujin_new_scene(session, previous, current):
    """Only explicit native scene endings restore the family's scene uses."""
    for aid, actor in session.state['actors'].items():
        record = source_record(session, aid)
        if not record:
            continue
        sources = {PREFIX + 'dragon_s_roar', PREFIX + FORM}
        uses = {pool for action in actor['bundle']['action_catalog']
                if action.get('parameters', {}).get('typed', {}).get('source') in sources
                for pool, _ in action.get('costs', []) if pool.startswith('resource:uses.')}
        definitions = {r['resource_id']: r for r in actor['bundle']['actor_template']['resources']}
        for pool in uses:
            if pool in definitions:
                actor['resources'][pool] = definitions[pool]['initial']
        record['scene'] = current
        session.emit('RYUJIN_SCENE_REFRESHED', aid, source=PARENT, scene=current, pools=sorted(uses))


@hook('compile_action')
def ryujin_native_action_profile(action, info):
    """Bind a native family's techniques to its owning Body attainment.

    Legacy sealed fighters keep their original numbers. The source's record
    does not turn total multiclass CL into additional Body attainment.
    """
    owned = set(info.get('owned_ids') or [])
    if not any(mid.startswith(PREFIX) for mid in owned):
        return None
    parameters = copy.deepcopy(action.parameters or {})
    typed = parameters.get('typed') or {}
    source = typed.get('source') or ''
    changed = False
    record = (info['owner_sheet'].get('path_and_subpath') or {}).get('ryujin_native')
    if record and source.startswith(PREFIX):
        typed['numbers'] = {**typed.get('numbers', {}), 'cl': _body_level(info['owner_sheet'])}
        parameters['ryujin_native_source_cl'] = record['source_cl']
        parameters['ryujin_effective_cl'] = _body_level(info['owner_sheet'])
        changed = True
    if PREFIX + FORM in owned and (source == PREFIX + FORM or any(
            row.get('attack_kind') == 'unarmed' for row in typed.get('effects', []))):
        typed['manual_inline_choice'] = True
        changed = True
    if not changed:
        return None
    parameters['typed'] = typed
    return action.model_copy(update={'parameters': parameters})


@hook('reaction_rows')
def ryujin_dormant_defenses(engine, actor_id, block, rows):
    if block != 'defense':
        return None
    record = next((r for r in engine.typed_passive_rows.get(actor_id, []) if r.get('block') == 'ryujin_native'), None)
    if record is None or record['effective_cl'] >= 3:
        return None
    return [row for row in rows if row.get('feature_id') != PREFIX + 'dragon_scales']


@hook('technique_used')
def record_ascendant_transformation(ctx):
    if ctx.typed.get('source') != PREFIX + FORM:
        return
    from .states import active
    from .retained_updates import record_instance_update
    from .. import dynamic_size
    state = active(ctx.engine, ctx.actor, FORM)
    if state is None:
        return
    footprint = ctx.engine._footprint(ctx.actor)
    record = {'prior_size': ctx.damage_cache.get('ryujin_prior_size', dynamic_size.current_category(ctx.engine, ctx.actor)),
              'chosen_size': dynamic_size.current_category(ctx.engine, ctx.actor),
              'width_cells': footprint.width_cells, 'height_cells': footprint.height_cells,
              'equipment_fit': 'Retain carried equipment; the form grants no new item or equipment permission.',
              'fly_speed_ft': 60, 'hover': 1, 'unarmed_reach_bonus_ft': 5,
              'immunities': ['LIGHTNING'], 'resistances': ['THUNDER'],
              'breath': {'cone_ft': 30, 'dice_count': 8, 'dice_sides': 6, 'stamina': 2, 'economy': 'Action'},
              'source_cl': int(ctx.numbers.get('cl') or 0), 'duration_seconds': 60,
              'activated_turn': _stamp(ctx.engine)}
    updated = state.model_copy(update={'data': {**state.data, 'transformation': record}})
    ctx.actor.conditions[state.instance_id] = updated
    record_instance_update(ctx.engine, ctx.actor, 'condition', state.instance_id, updated)
