"""Shield Training's permission and Utilize actions, using ordinary item locations.

A selected Shield sphere includes Shield Training, and so does the book's own mundane "Shield Training:
you gain shield proficiency". Equipment location is the existing public carry contract; one equipped
Shield occupies one free hand and adds its compiled bonus. Doffing keeps the Shield carried, so it is
available to don again.
"""
from . import hook, effect

TRAINING = 'SHIELD_BASE_SHIELD_TRAINING'
SPHERE = 'tianxia.sphere.shield'
#: The mundane proficiency grant printed elsewhere in the same book -- "### Shield Training ... You gain shield
#: proficiency" (``authority/typed_mechanics/reviewed_final.d/auto68_equipment.json``).  A wielder who owns it has
#: Shield training by the same printed sentence, so the +2 belongs to them exactly as it does to a Shield sphere.
PROFICIENCY = 'tianxia.talent.equipment.shield_training'
LOCATION = 'condition:typed.shield_equipped'


def trained(info):
    sheet = info['owner_sheet']
    block = sheet.get('spheres_and_talents') or {}
    ids = set(info.get('owned_ids') or ())
    ids.update(block.get('automatic_sphere_component_record_ids') or ())
    ids.update(block.get('learned_talent_record_ids') or ())
    if TRAINING in ids or PROFICIENCY in ids or SPHERE in ids or SPHERE in (block.get('sphere_record_ids') or ()):
        return True
    # Other printed proficiency grants are explicit sheet facts, never inferred
    # from carrying a Shield or from a creature's display name.
    proficiency = sheet.get('proficiencies') or {}
    return any(str(value).strip().lower() in {'shield', 'shields'}
               for value in (proficiency.get('armor') or [])) if isinstance(proficiency, dict) else False


@hook('compile_shield_bonus')
def training_bonus(bonus, info):
    return bonus if trained(info) else 0


@hook('compile_actions')
def utilize_actions(info):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from .. import armour
    if not armour.carries_shield(info['kit'], info['owner_items']):
        return None
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.shield.{mode}",
        display_name=f'{"Don" if mode == "don" else "Doff"} Shield (Utilize Action)',
        owner_id=info['actor_id'], economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='SELF',
        parameters={'player_only': True, 'expected_damage': 0, 'typed': {
            'source': TRAINING, 'numbers': info['numbers'], 'duration': {'kind': 'instant'},
            'riders': [], 'effects': [{'type': 'shield_equip', 'mode': mode}]}})
        for mode in ('don', 'doff')]


def equipment_mode(action):
    if action is None:
        return None
    effects = (action.parameters.get('typed') or {}).get('effects') or []
    return next((row['mode'] for row in effects if row.get('type') == 'shield_equip'), None)


@hook('candidate_allowed')
def equip_allowed(engine, actor, candidate, action):
    mode = equipment_mode(action)
    if mode is None:
        return None
    from .. import armour, carry
    from .hand_occupancy import free_hands
    from .shield_wielding import orbiting
    key = armour.shield_item_key(engine, actor)
    if key is None or not carry.holds(engine, actor, key) or orbiting(engine, actor):
        return False
    equipped = not carry.lost_to_another_hand(actor, key)
    return equipped if mode == 'doff' else not equipped and bool(free_hands(engine, actor))


@effect('shield_equip')
def equip(ctx, row):
    from .. import armour, carry
    from .hand_occupancy import free_hands
    engine, actor = ctx.engine, ctx.actor
    if equip_allowed(engine, actor, None, ctx.action) is not True:
        return
    key = armour.shield_item_key(engine, actor)
    location = 'carried' if row['mode'] == 'doff' else 'hand:' + free_hands(engine, actor)[0]
    carry.clear_owned_item_location(engine, actor, key, ctx.source)
    engine._apply_condition(actor, LOCATION, ctx.source, actor.entity_id, expires_on='UNTIL_REMOVED',
        data={'item_key': key, 'held_by': actor.entity_id, 'object_location': location,
              'label': 'Shield equipped' if row['mode'] == 'don' else 'Shield carried (no Shield Bonus)'})
