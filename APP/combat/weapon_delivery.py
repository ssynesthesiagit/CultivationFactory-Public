"""Pure packet classification and identity for cover and weapon-hit riders.

attack_provenance adapts native/spec packets; ext.weapon_hits adapts typed hit
Contexts. Hand occupancy shares the physical-weapon ancestry queries. None of
these callers owns another copy of the delivery or identity rules.
"""


def weapon_variant_base(parameters):
    """Physical parent of an attack variant, including saved reach catalogs.

    Reach generation, weapon-hit provenance and hand occupancy share this
    public metadata contract. An unmarked action remains its own weapon.
    """
    parameters = parameters or {}
    parent = parameters.get('variant_of') or (parameters.get('typed') or {}).get('variant_of') or (parameters.get('reach_bonus') or {}).get('base')
    if parent:
        return parent
    from . import ext
    return next((value for value in ext.query('weapon_variant_parent', parameters)
                 if isinstance(value, str) and value), None)


def physical_weapon_id(source, parameters=None):
    """One physical id for off-hand/reach modes; used by hand occupancy and weapon-hit helpers.

    Share the existing variant-parent contract so newer and saved reach modes
    agree without duplicating ancestry rules in an ability plug-in.
    """
    return str(weapon_variant_base(parameters) or source).split('#', 1)[0]


def delivery_kind(typed, effect, parameters=None):
    """Only an actual weapon packet or weapon-damage cultivation hit is a weapon.

    Native packets without an effect may retain explicit equipment metadata.
    Unarmed/cultivation packets do not inherit that fallback from held gear.
    """
    kind = str((effect or {}).get('attack_kind') or (parameters or {}).get('attack_kind') or '')
    weapon = (kind in {'weapon', 'weapon_melee', 'weapon_ranged'}
              or (kind.startswith('cultivation') and bool(typed.get('weapon'))
                  and any(row.get('weapon_damage') for row in (effect or {}).get('on_hit') or ())))
    if effect is None and not kind:
        weapon = bool(typed.get('weapon'))
    return 'weapon' if weapon else 'unarmed' if kind == 'unarmed' else 'cultivation' if kind.startswith('cultivation') else 'unknown'


def available_weapons(engine, actor, words=(), *, include_busy=False):
    """Weapons currently in this actor's possession, optionally filtered by name.

    Own equipment is available unless disabled on its owner. Synthetic borrowed
    equipment additionally needs the engine's possession condition on any actor.
    Conditions remain the source of truth after table commit/reload and recovery.
    ``include_busy`` is for physical occupancy: a bound or otherwise unusable
    weapon still occupies its grip. Dropped, disarmed and taken weapons do not.
    Attack/delivery consumers retain the default usable-weapon query.
    """
    disabled = {c.data.get("disables_action") for c in actor.conditions.values()
                if not include_busy or c.data.get("dropped_at") or c.data.get("held_by")
                or c.condition_id == "condition:typed.disarmed"}
    held = {c.data.get("disables_action") for owner in engine.state.actors.values()
            for c in owner.conditions.values() if c.data.get("held_by") == actor.entity_id}
    weapons = {}
    from . import carry
    carrying = carry.carrying_of(engine, actor.entity_id)
    for action in engine.action_catalog.values():
        # Ownership is independent of possession and variant hooks. Skip other
        # actors before inspecting their metadata; all own-weapon checks stay live.
        if action.owner_id != actor.entity_id:
            continue
        source = action.source_definition_id
        item = carry.item_of(carrying, weapon_action=source)
        if item is not None and carry.quantity_exhausted(engine, actor, item):
            continue
        parameters = action.parameters or {}
        typed = parameters.get("typed") or {}
        if ("#" in source or source in disabled
                or not typed.get("weapon") or weapon_variant_base(parameters)
                or any(typed.get(key) for key in ("delivered_by", "weapon_source_id", "maneuver_of", "opportunity_of"))):
            continue
        required = parameters.get("requires_held_weapon")
        if required and required not in held:
            continue
        if words and not any(word in action.display_name.lower() for word in words):
            continue
        weapons[source] = action
    return weapons


def ready_weapons(engine, actor, words=()):
    """Usable weapons in drawn grips; historical unmanaged catalogs keep their policy.

    This opt-in query is for newly sealed wielded-weapon contracts. Possession
    queries and legacy saved attachments remain unchanged. Actor equipment readiness
    is authoritative after Draw/Stow, service commit and cold reload.
    """
    from .ext.hand_occupancy import supports_grips, weapon_grips
    weapons = available_weapons(engine, actor, words)
    if not supports_grips(engine, actor):
        return weapons
    grips = weapon_grips(engine, actor)
    return {key: weapon for key, weapon in weapons.items() if key in grips}


def weapon_identity(engine, source, typed, parameters=None, *, owner_id=None):
    """Follow explicit delivery, maneuvers, physical variants and opportunity ancestry once.

    A resolving packet may pass its typed metadata separately from parameters;
    its actual variant ancestry must remain available to the shared resolver.
    """
    parameters = parameters or {}
    initial = (getattr(engine, 'action_catalog', {}) or {}).get(source)
    owner_id = owner_id or getattr(initial, 'owner_id', None)
    seen = set()
    while source not in seen:
        seen.add(source)
        delivery = typed.get("weapon_source_id") or typed.get("delivered_by") or parameters.get("weapon_source_id") or parameters.get("delivered_by")
        if delivery:
            return str(delivery).split("#", 1)[0]
        maneuver = typed.get('maneuver_of') or parameters.get('maneuver_of')
        if maneuver:
            parent = (getattr(engine, 'action_catalog', {}) or {}).get(maneuver)
            parent_typed = ((parent.parameters or {}).get('typed') or {}) if parent else {}
            if not typed.get('source') or typed.get('source') == parent_typed.get('source'):
                return str(maneuver).split('#', 1)[0]
            # Legacy Mixed Barrage tracks the primary weapon in maneuver_of,
            # but its attack may use another item. Resolve an unambiguous base
            # item on the same actor; do not infer a weapon from a label.
            owner = (getattr(getattr(engine, 'state', None), 'actors', {}) or {}).get(owner_id)
            matches = [row.source_definition_id for row in available_weapons(engine, owner, include_busy=True).values()
                       if '.weapon.' in row.source_definition_id
                       and ((row.parameters or {}).get('typed') or {}).get('source') == typed.get('source')] if owner else []
            if len(matches) == 1:
                return matches[0]
        parent_id = weapon_variant_base({**parameters, "typed": typed}) or typed.get("opportunity_of") or parameters.get("opportunity_of")
        if not parent_id:
            break
        source = str(parent_id)
        action = (getattr(engine, "action_catalog", {}) or {}).get(source)
        parameters = action.parameters if action else {}
        typed = parameters.get("typed") or {}
    return str(source).split("#", 1)[0] if source else None


def attack_materials(engine, actor, action, attack_kind):
    """Rules-recognized materials for this actual delivery, never a damage type.

    Source providers gate current access, binding, possession and wielding.
    Ordinary item metadata remains independent; unarmed attacks inherit no item.
    """
    from . import ext
    typed=(action.parameters.get('typed') or {}) if action is not None else {}
    item=typed.get('weapon') or {} if attack_kind=='weapon' else {}
    return tuple(dict.fromkeys([*item.get('materials',()),*(str(m).lower() for reply in
        ext.run_strict('attack_materials',engine,actor,action,attack_kind) for m in reply)]))
