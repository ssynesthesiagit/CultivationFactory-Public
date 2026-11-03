"""One Vessel quote/settlement shared by Guard, Strike and Rejection.

Consumers pay their existing Integrity conversion once. A quote is pure; only
the selected same-spend improvement claims the persisted round clock. Replaces
the obsolete save-rescue observer after Rejection moved to phased saves.
No resource producer or second payment lives here.
"""
from .passive_rows import row_of
from ..feature_availability import available

FEATURE = 'foundation.heavenly_body_v0_2F.heaven_recognized_vessel'
FLAG = 'foundation_round_vessel'


def vessel_ready(engine, actor):
    return bool(available(engine, actor, FEATURE)
        and row_of(engine, actor.entity_id, 'foundation_spend', 'heaven_recognized_vessel')
        and actor.turn_flags.get(FLAG) != engine.state.round_number)


def settle_vessel_bonus(engine, actor, pb):
    if not vessel_ready(engine, actor):
        return 0
    actor.turn_flags[FLAG] = engine.state.round_number
    return int(pb)


def choose_vessel_bonus(engine, actor, pb, conversion, source_id, target):
    """Optional improvement after the conversion's original payment, no new cost."""
    if not vessel_ready(engine, actor):
        return 0
    from .needle import ask, checkpoint_id, CHOICE
    action = engine.action_catalog.get(source_id)
    action_name = action.display_name if action else conversion
    chosen = ask(engine, getattr(engine, '_active_intent', None),
        checkpoint_id(engine, 'HEAVEN_RECOGNIZED_VESSEL', actor.entity_id, conversion, target.entity_id),
        actor, CHOICE + 'heavenly_vessel', ['use', 'keep'],
        name='Heaven-Recognized Vessel', feature_id=FEATURE, target_id=target.entity_id,
        labels={'use': f'Add {pb} to {conversion} using the same Heavenly Integrity spend',
                'keep': 'Keep Heaven-Recognized Vessel for another spend this round'},
        preferred=['use'], automatic=True, default='first',
        prompt_context={'cost': 'No additional cost; uses the Heavenly Integrity already spent'},
        prompt=f'Heaven-Recognized Vessel: {actor.display_name} uses {conversion} against {action_name} '
               f'affecting {target.display_name}. Add {pb} to this conversion only? '
               'This uses the same Heavenly Integrity spend, costs no additional resource, Action or Reaction, '
               'and uses the bonus for this round.')
    return settle_vessel_bonus(engine, actor, pb) if chosen and chosen[0] == 'use' else 0
