"""Weapon delivery queries shared by deferred hit bonuses and martial weapon plug-ins.

``delivered_by`` is the compiler's delivering weapon action; plug-ins that attach
a weapon set ``weapon_source_id``. Both identify the base weapon across variants.
``maneuver_of`` is the older maneuver delivery field; sealed bundles using it
share the same physical weapon identity and never allocate another grip.
``opportunity_of`` names the catalog action copied into an opportunity attack;
follow that action's delivery metadata before normalizing its weapon identity.
Reach variants likewise name their original action in parameters.reach_bonus.base;
they never create another physical weapon or grip, including legacy catalogs.
An attached weapon counts only on a cultivation attack that delivers weapon damage;
an unarmed attack never becomes a weapon hit just because its Context has a weapon.

``available_weapons(engine, actor, words=())`` is the public possession query
used by Spear selection/binding, weapon-required eligibility and deferred bonuses.
It returns base weapon IDs mapped to their attack definitions, applying Gate2's
``disables_action`` and ``requires_held_weapon``/``held_by`` gates. It deliberately
ignores action economy, targets, range and attack-slot availability: possessing a
weapon does not require being able to spend an Attack action. Delivery techniques,
opportunity copies and attack variants cannot introduce another weapon identity.

``physical_weapon_id(source, parameters)`` is the shared one-object-one-identity
query used by hand_occupancy (possession, grips, hand capacity) and
equipment_hands (Draw/Stow choices). A weapon's alternative attack modes are the
same object in the character's hands, so they all resolve to the same id.

``weapon_has_family(ctx, family)`` is the shared kind query used by guard_broken.
It follows weapon_identity to the base action's typed item source, then reads the
item catalog's weapon_family. Action labels, including Opportunity Attack, have
no mechanical meaning; unknown items and unarmed actions match no family.
"""


from ..weapon_delivery import available_weapons, physical_weapon_id


def weapon_identity(ctx):
    from ..weapon_delivery import weapon_identity as identity
    return identity(getattr(ctx, 'engine', None), ctx.action.source_definition_id, ctx.typed,
                    getattr(ctx.action, 'parameters', None), owner_id=getattr(ctx.action, 'owner_id', None))


def triggered_melee_weapon(engine, actor, *, unarmed=False):
    """Shared selection for independent triggered attacks and Moon-Falling Counter.

    Choose the strongest usable, readied melee attack. Explicit Unarmed Strikes
    prefer the actor's natural attack. Historical catalogs without managed grips
    retain their existing hand policy through weapon_allowed's inert result.
    """
    from .hand_occupancy import weapon_allowed
    own = [action for action in available_weapons(engine, actor).values()
           if not action.parameters['typed'].get('range_ft')
           and weapon_allowed(engine, actor, action) is not False]
    if unarmed:
        natural = next((action for action in own if '.natural.' in action.source_definition_id), None)
        if natural is not None:
            return natural
    return max(own, key=lambda action: int(action.parameters.get('expected_damage') or 0), default=None)


def is_weapon_hit(ctx, attack):
    from ..weapon_delivery import delivery_kind
    return delivery_kind(ctx.typed, attack, ctx.action.parameters) == 'weapon'


def weapon_item(ctx):
    """Shared catalog metadata for weapon-family queries and Gravity proficiency.

    Resolve delivered attacks and opportunity attacks to their actual weapon;
    non-weapons and unknown catalog entries return an empty dictionary.
    """
    from factory_authoring.starting_kits import item_definition
    action = ctx.engine.action_catalog.get(weapon_identity(ctx))
    typed = ((action.parameters or {}).get('typed') or {}) if action is not None else {}
    if not typed.get('weapon'):
        return {}
    return item_definition(str(typed.get('source') or ''))


def weapon_has_family(ctx, family):
    """Match an authoritative weapon-family word across deliveries and OAs."""
    import re
    item = weapon_item(ctx)
    return str(family).lower() in re.findall(r'[a-z]+', str(item.get('weapon_family') or '').lower())
