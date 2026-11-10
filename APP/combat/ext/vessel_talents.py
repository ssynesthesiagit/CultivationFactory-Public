"""Sleeve-Pulling Rebuke, ported from riders/c3 (35ab41a9), using the native forced-miss seam.

Printed rule: rules_text.json, tianxia.talent.puppetry.sleeve_pulling_rebuke.
A creature bearing the owner's Tension Mark makes an Opportunity Attack. The owner may
spend that mark: failed Dexterity save against their Cultivation Save DC makes the attack
miss; success gives Disadvantage. Spending requires a live thread and control range.

This is the existing C3 consumer's canonical module, scoped to this port; unrelated C3
talents are not prerequisites. No unreachable AC, delayed hit_response flag, native-only
GM refusal, or event watcher is needed. before_attack returns a per-attack outcome.
"""
from typing import Any

from . import effect, hook, needle, placed, vessel

REBUKE = 'tianxia.talent.puppetry.sleeve_pulling_rebuke'
MARK = 'Tension Mark'
NAME = 'Sleeve-Pulling Rebuke'


@effect('vessel_save_failed')
def save_failed(ctx: Any, row: dict[str, Any]) -> None:
    """Capture the settled typed save result in its own transient Context, including outcome rewrites."""
    ctx.damage_cache['vessel_save_failed'] = True


def _fails_save(engine: Any, owner: Any, owned: dict[str, Any], subject: Any) -> bool:
    from ..typed_executor import run_effects

    action = owned['action'].model_copy(update={'source_definition_id': REBUKE, 'display_name': NAME,
                                                'range_ft': vessel.control_range(owned)})
    ctx = placed.context(engine, owner, REBUKE, owned['numbers'], [subject], action=action)
    run_effects(ctx, [{'type': 'save', 'applies_to': 'target', 'ability': 'dex', 'dc': 'technique_save_dc',
                       'on_fail': [{'type': 'vessel_save_failed'}], 'on_success': []}])
    return bool(ctx.damage_cache.get('vessel_save_failed'))


@hook('before_attack')
def vessel_attack_answers(engine: Any, attacker: Any, defender: Any, intent: Any,
                          context: dict[str, Any]) -> dict[str, Any] | None:
    from ..typed_executor import bears_mark, mark_condition_id

    if defender is None or not (context.get('source_id') == 'system:combat.opportunity_attack'
                               or getattr(engine, '_typed_oa_attacker', None) == attacker.entity_id):
        return None
    mode = None
    for owner in engine.state.actors.values():
        owned = vessel.kit(engine, owner) if owner.active and owner is not attacker else None
        if owned is None or REBUKE not in owned['owned'] or not bears_mark(attacker, owner.entity_id, MARK):
            continue
        if engine._distance_actor_to_actor(owner, attacker) > vessel.control_range(owned) or not vessel.threaded_vessels(engine, owner, owned):
            continue
        picked = needle.ask(engine, intent, needle.checkpoint_id(engine, 'SLEEVE_PULLING_REBUKE', attacker.entity_id),
            owner, 'choice:needle.sleeve_pulling_rebuke', ['SPEND'],
            labels={'SPEND': f'Spend your Tension Mark on {attacker.display_name}'},
            prompt=f'{NAME}: {attacker.display_name} makes an Opportunity Attack against {defender.display_name}. '
                   'Spend your Tension Mark (the thread attached to the attacker), with no Reaction or CP cost? '
                   'It makes a Dexterity save: failure makes this attack miss, even on a natural 20; '
                   'success gives this attack Disadvantage.',
            name=NAME, target_id=attacker.entity_id, preferred=['SPEND'], allow_decline=True)
        if not picked:
            continue
        engine._remove_condition(attacker, mark_condition_id(MARK, owner.entity_id), REBUKE)
        if _fails_save(engine, owner, owned, attacker):
            placed.note(engine, REBUKE, owner,
                f'{NAME}: {owner.display_name} spends the Tension Mark on {attacker.display_name}. '
                f'It fails its Dexterity save; its Opportunity Attack against {defender.display_name} misses.', [attacker])
            return {'force_miss': True, 'source_id': REBUKE, 'label': NAME}
        mode = 'DISADVANTAGE'
        placed.note(engine, REBUKE, owner,
            f'{NAME}: {owner.display_name} spends the Tension Mark on {attacker.display_name}. '
            f'It succeeds on its Dexterity save; its Opportunity Attack against {defender.display_name} has Disadvantage.', [attacker])
    return {'mode': mode} if mode else None
