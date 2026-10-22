"""Native spirit-technique contact with external spiritual assets/Anchors.

Shared by source actions declaring spiritual_contact. Internal Anchors and
ordinary objects are excluded. This grants damage delivery only, no carrying,
Grapple, manipulation, or creature-only rider. Asset profiles stay authoritative.
"""
from . import hook


@hook('turn_start')
def expire_contact_objects(engine, actor):
    sweep_contact_objects(engine)


@hook('turn_end')
def end_contact_objects(engine, actor, *, nominal=False):
    sweep_contact_objects(engine, ending_id=actor.entity_id)


def sweep_contact_objects(engine, ending_id=None):
    from ..ext.effect_durations import due
    for obj in list(engine.state.objects.values()):
        records = obj.component.get('contact_records') or []
        retained = [r for r in records if not due(engine, r['expiration'], ending_id)]
        if retained != records:
            engine._update_object(obj.model_copy(update={'component': {**obj.component, 'contact_records': retained}}),
                'system:combat.expiration')


def external_spirit(obj):
    data = obj.component or {}
    profile = data.get('spiritual_profile') or {}
    anchor = data.get('anchor')
    if (profile.get('anchor') == 'internal' or profile.get('internal_anchor')
            or data.get('internal_anchor') or (isinstance(anchor, dict) and anchor.get('internal'))):
        return False
    return bool(profile.get('identity') or profile.get('anchor') == 'external'
                or profile.get('external_anchor') or profile.get('cultivation_asset')
                or data.get('spirit_asset') or data.get('spiritual_identity') or data.get('external_anchor'))


@hook('object_targets')
def spiritual_targets(engine, actor, action):
    if not action.parameters.get('spiritual_contact') or action.parameters.get('spirit_touch'):
        return None  # Spirit-Touch objects belong to the Palm/object_subjects seam
    from ..contact_records import permitted
    return [obj.object_id for obj in engine.state.objects.values() if not obj.destroyed and external_spirit(obj)
            and permitted(engine, actor, obj, source=action.source_definition_id)]


@hook('object_action')
def spiritual_attack(engine, actor, action, obj, candidate, intent):
    if not action.parameters.get('spiritual_contact') or action.parameters.get('spirit_touch'):
        return None  # Spirit-Touch objects belong to the Palm/object_subjects seam
    from . import run_strict, needle
    from .objects import roll_technique_attack, deal, prepare_damage_dice
    from ..typed_executor import Context, resolve_attack_damage
    from ..contact_records import permitted
    if not external_spirit(obj) or not permitted(engine, actor, obj, source=action.source_definition_id):
        return True  # The paid effect cannot contact an internal/now separated profile.
    if False in run_strict('spiritual_object_allowed', engine, actor, action, obj):
        return True
    typed = action.parameters['typed']
    attack = next(e for e in typed['effects'] if e['type'] == 'attack')
    ctx = Context(engine, actor, action, intent, typed, [], None, damage_cache={'_object': obj})
    hit, natural = roll_technique_attack(ctx, obj)
    if hit:
        # Resolve the compiled/printed damage first: its resolved types (Bludgeoning
        # or Psychic for Wisdom; the Strength profile's own type) are the choices the
        # owner may pick from. Offering the raw pre-resolution row showed "Untyped"
        # and dropped every printed choice.
        dice, kinds, _, damage_row, profile = resolve_attack_damage(ctx, attack)
        chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, 'SPIRIT_OBJECT_DAMAGE', obj.object_id), actor,
            'choice:needle.spirit_object.damage', kinds, labels={k: k.title() for k in kinds}, preferred=[kinds[0]],
            prompt=f'{action.display_name} against {obj.component.get("name", "spiritual asset")}: choose its damage type.',
            name=action.display_name, target_id=obj.object_id)
        # Same shared damage-roll fold the creature path uses, once per actual damage
        # roll, so a rider like Marrow-Furnace Pulse's "+PB to one damage roll" is added
        # and spent for an object hit too instead of leaking into a later roll.
        dice = prepare_damage_dice(ctx, dice, damage_row, kinds)
        roll = engine.roller.roll(dice, actor_id=actor.entity_id,
            reason=f'DAMAGE:{action.source_definition_id}:object', critical=natural == 20,
            fixed_damage=profile.get('fixed_damage'))
        engine._record_roll(roll)
        dealt = deal(engine, actor, obj, [(max(0, int(roll.total)), (chosen or kinds)[0].upper())], action.source_definition_id)
        run_strict('spiritual_object_damaged', engine, actor, action, obj, dealt, intent)
    return True
