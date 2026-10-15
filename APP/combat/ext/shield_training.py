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
    items = [item for item in info['carrying']['items'] if item.get('shield')]
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.shield.{mode}" +
                             (f'.{index}' if len(items) > 1 else ''),
        display_name=f'{"Don" if mode == "don" else "Doff"} ' +
                     (f"{item['name']} {index + 1}" if len(items) > 1 else 'Shield') + ' (Utilize Action)',
        owner_id=info['actor_id'], economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='SELF',
        parameters={'expected_damage': 0, 'typed': {
            'source': TRAINING, 'numbers': info['numbers'], 'duration': {'kind': 'instant'},
            'riders': [], 'effects': [{'type': 'shield_equip', 'mode': mode, 'item_key': item['key']}]}})
        for index, item in enumerate(items) for mode in ('don', 'doff')]


@hook('equipped_item_key')
def active_shield(default, engine, actor, category, items):
    """Shared identity for AC and Shield talents; carrying a spare is not wielding it."""
    if category != 'shield' or actor is None or len(items) < 2:
        return None
    from .. import carry
    return next((str(item['key']) for item in items
                 if carry.holds(engine, actor, item['key'])
                 and not carry.lost_to_another_hand(actor, item['key'])), default)


@hook('match_initialize')
def carry_spare_shields(engine):
    """One default wielded Shield; spare owned Shields remain carried, with their weight intact."""
    from .. import carry
    for actor in engine.state.actors.values():
        items = [item for item in (carry.carrying_of(engine, actor.entity_id) or {}).get('items', [])
                 if item.get('shield')]
        for item in items[1:]:
            # Explicit scene locations already say whether an item is carried or wielded.
            if carry.owned_item_location(actor, item['key']) is None:
                engine._apply_condition(actor, LOCATION, TRAINING, actor.entity_id, expires_on='UNTIL_REMOVED',
                    data={'item_key': item['key'], 'held_by': actor.entity_id,
                          'object_location': 'carried', 'label': 'Spare Shield carried (no Shield Bonus)'})


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
    row = next(row for row in action.parameters['typed']['effects'] if row.get('type') == 'shield_equip')
    key = row.get('item_key') or armour.shield_item_key(engine, actor)
    if key is None or not carry.holds(engine, actor, key) or orbiting(engine, actor):
        return False
    equipped = not carry.lost_to_another_hand(actor, key)
    active = armour.shield_item_key(engine, actor)
    another_wielded = active != key and active is not None and not carry.lost_to_another_hand(actor, active)
    return equipped if mode == 'doff' else not equipped and not another_wielded and bool(free_hands(engine, actor))


@effect('shield_equip')
def equip(ctx, row):
    from .. import armour, carry
    from .hand_occupancy import free_hands
    engine, actor = ctx.engine, ctx.actor
    if equip_allowed(engine, actor, None, ctx.action) is not True:
        return
    key = row.get('item_key') or armour.shield_item_key(engine, actor)
    location = 'carried' if row['mode'] == 'doff' else 'hand:' + free_hands(engine, actor)[0]
    carry.clear_owned_item_location(engine, actor, key, ctx.source)
    engine._apply_condition(actor, LOCATION, ctx.source, actor.entity_id, expires_on='UNTIL_REMOVED',
        data={'item_key': key, 'held_by': actor.entity_id, 'object_location': location,
              'label': 'Shield equipped' if row['mode'] == 'don' else 'Shield carried (no Shield Bonus)'})
