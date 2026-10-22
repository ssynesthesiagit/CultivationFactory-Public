"""Puppet Drinks the Blow and Severed Thread Recovery, from rules_text.json.

Owned compiled rows admit these hooks. Damage protection asks the puppeteer,
spends their mark without Reaction/CP, and uses final_damage's actual reduction
receipt for the vessel's half damage. AI protects allies/self only and can spend
only a perceived damaged creature and mark bearer. Manual eligibility has no
sight prerequisite. Recovery counts thread losses, not dismissals,
capacity replacement, or ordinary minute expiry; its budget lasts the scene.
"""
from . import hook, needle, placed, vessel
from .passive_rows import row_of
from .choice_prompt import action_context

DRINKS = 'tianxia.talent.puppetry.puppet_drinks_the_blow'
RECOVERY = 'insight.severed-thread-recovery'
BLOCK = 'puppetry_defense'


@hook('compile_block')
def compile_row(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, 'block': BLOCK, 'kind': spec['kind'], 'numbers': dict(numbers)}]
    return None


@hook('final_damage')
def drinks(engine, target, amount, damage_type, source_id, source_actor_id, intent):
    from ..typed_executor import bears_mark, run_effects
    from ..gate2_runtime_models import DiceSpec
    from ..target_knowledge import located
    intent = intent or getattr(engine, '_active_intent', None)
    if amount <= 0 or intent is None:
        return None
    reductions = []
    for owner in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        row = row_of(engine, owner.entity_id, BLOCK, 'drinks')
        owned = vessel.kit(engine, owner) if row and owner.active else None
        ai = needle.ai_controlled(engine, owner)
        # Perception constrains this chooser’s automatic decision, not printed eligibility.
        if not owned or (ai and not located(engine, owner, target)):
            continue
        near = [z for z in vessel.threaded_vessels(engine, owner, owned)
                if engine._distance_actor_to_cell(target, z.center) <= 5]
        attacker = engine.state.actors.get(source_actor_id)
        bearers = [a for a in (attacker, target) if a is not None
                   and bears_mark(a, owner.entity_id, vessel.MARK)
                   and (not ai or located(engine, owner, a))]
        bearers = {a.entity_id: a for a in bearers}
        if not near or not bearers:
            continue
        prompt_context = action_context(engine, attacker, source_id, target)
        modifier = int(row['numbers'].get('key_mod') or 0)
        picked = needle.ask(engine, intent,
            needle.checkpoint_id(engine, 'PUPPET_DRINKS', owner.entity_id, target.entity_id, source_id),
            owner, 'choice:needle.puppet_drinks', list(bearers),
            labels={a.entity_id: f'Spend your attached thread (Tension Mark) on {a.display_name}' for a in bearers.values()},
            prompt=f'Puppet Drinks the Blow: {target.display_name} takes {amount} {damage_type} damage beside your vessel. '
                   f'Spend your attached thread (Tension Mark) on the attacker or damaged creature to reduce it by 3d8 + {modifier} '
                   '(your ability modifier)? The vessel takes half the damage actually prevented, rounded down. '
                   'No Reaction or cultivation points are spent.',
            name='Puppet Drinks the Blow', feature_id=DRINKS, target_id=target.entity_id,
            automatic=owner.team_id == target.team_id, allow_decline=True, prompt_context=prompt_context)
        if not picked:
            continue
        if len(near) > 1:
            from .rider_choices import pick
            chosen = pick(engine, owner, 'puppet_drinks_vessel', 'Puppet Drinks the Blow',
                [z.zone_id for z in near], subject=target, optional=False,
                labels={z.zone_id: f'Vessel at ({z.center.x}, {z.center.y})' for z in near},
                prompt=f'Puppet Drinks the Blow: choose the adjacent vessel that takes half the damage prevented to {target.display_name}, rounded down.',
                prompt_context=prompt_context)
            zone = next(z for z in near if z.zone_id == chosen[0])
        else:
            zone = near[0]
        ctx = placed.context(engine, owner, DRINKS, row['numbers'], [bearers[picked[0]]],
                             action=owned['action'].model_copy(update={'source_definition_id': DRINKS}))
        run_effects(ctx, [{'type': 'spend_mark', 'mark': vessel.MARK, 'applies_to': 'target'}])
        rolled = engine.roller.roll(DiceSpec(count=3, sides=8, modifier=int(row['numbers'].get('key_mod') or 0)),
                                    actor_id=owner.entity_id, reason='PUPPET_DRINKS_REDUCTION')
        engine._record_roll(rolled)
        engine._append_event('DAMAGE_ROLLED', DRINKS, actor_id=owner.entity_id, target_ids=(target.entity_id,),
                            payload={'expression': rolled.expression, 'total': rolled.total, 'roll_id': rolled.roll_id})
        reductions.append((owner, zone, max(0, int(rolled.total))))
    if not reductions:
        return None

    def settle(applied):
        # Allocation to these independently paid grants is stable. A preceding
        # defense can prevent the packet first; vessel damage uses actual use.
        for owner, zone, quote in reductions:
            used = min(applied, quote)
            applied -= used
            engine._append_event('PASSIVE_TRIGGERED', DRINKS, actor_id=owner.entity_id, target_ids=(target.entity_id,),
                payload={'text': f'Puppet Drinks the Blow prevents {used} damage to {target.display_name}; '
                         f'the vessel takes {used // 2} damage.', 'reduction': used, 'vessel_id': zone.zone_id})
            vessel.damage_vessel(engine, zone, used // 2, DRINKS)
    return {'reduction': min(amount, sum(r[2] for r in reductions)), 'settle': settle}


@hook('vessel_thread_ended')
def recovery(engine, owner, zone, reason):
    row = row_of(engine, owner.entity_id, BLOCK, 'recovery')
    if not row or not owner.active or reason not in ('BROKEN', 'OUT_OF_RANGE', 'SEVERED'):
        return
    key = 'puppetry_recovery_round_scene_uses'
    used = int(owner.turn_flags.get(key) or 0)
    limit = 2 if int(row['numbers'].get('cl') or 1) >= 15 else 1
    if used >= limit:
        return
    owner.turn_flags[key] = used + 1
    owned = vessel.kit(engine, owner)
    if owned:
        from ..decision_text import resource_name
        engine._gain_resource(owner, owned['pool'], 1, RECOVERY)
        placed.note(engine, RECOVERY, owner,
            f"Severed Thread Recovery: your vessel’s control thread ends; regain 1 cultivation point in your {resource_name(owned['pool'])} pool ({used + 1}/{limit} uses this scene).")
