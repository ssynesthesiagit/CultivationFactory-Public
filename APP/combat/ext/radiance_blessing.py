"""Radiance's Blessing: saved once-scene start-turn CP recovery.

Fresh exact-text reviewed block only; old catalogs acquire no entitlement.
Ability-score selection belongs to character construction. Existing choice
transport supplies optional use on a committed turn-start; initialization with
no decision provider follows needle.ask's deterministic use-first fallback.
"""
from . import hook, note
from .cp_pools import of
from .needle import ask, checkpoint_id
from .passive_rows import row_of

FEATURE = 'insight.radiance-s-blessing'
BLOCK = 'radiance_blessing'
USED = '_round_radiance_blessing_used'


@hook('compile_block')
def compile_blessing(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, 'kind': 'recovery', 'pb': int(numbers['pb']), 'choice_owner': True,
                 'player_outcome': 'Once per scene, at the start of your turn, regain CP equal to your Proficiency Bonus while conscious and able to use Radiance'}]
    return None


@hook('turn_start')
def recover(engine, actor):
    row = row_of(engine, actor.entity_id, BLOCK, 'recovery')
    if row is None or actor.turn_flags.get(USED) or not actor.active or actor.current_hp <= 0:
        return
    # This recovery costs no action. Action denial does not prevent circulation;
    # consciousness and explicit recovery/circulation vetoes decide eligibility.
    if any(c.condition_id.endswith('unconscious') for c in actor.conditions.values()):
        return
    from ..typed_executor import condition_rules
    if any(rule.get('no_cp_regain') or rule.get('radiance_circulation_blocked') for rule in condition_rules(actor)):
        return
    pool = of(actor)
    if pool is None or actor.resources[pool] >= actor.resource_maximums[pool]:
        return
    amount = int(row['pb'])
    selected = ask(engine, engine._active_intent, checkpoint_id(engine, 'RADIANCE_BLESSING', actor.entity_id),
        actor, 'choice:needle.radiance_blessing', ['recover'],
        labels={'recover': f'Regain {amount} CP, up to your maximum; use Radiance’s Blessing for this scene'},
        allow_decline=True, name='Radiance’s Blessing', feature_id=FEATURE, target_id=actor.entity_id,
        prompt=f'Radiance’s Blessing: {actor.display_name} starts their turn. Regain {amount} Cultivation Points '
               'at no action or resource cost? This recovery can be used once this scene.',
        prompt_context={'cost': 'No action or resource cost'})
    if not selected:
        return
    before = actor.resources[pool]
    engine._gain_resource(actor, pool, amount, FEATURE)
    if actor.resources[pool] > before:
        actor.turn_flags[USED] = 1
        note(engine, FEATURE, actor, f'Radiance’s Blessing restores {actor.resources[pool] - before} Cultivation Points; '
             'its once-per-scene recovery is now used.')
