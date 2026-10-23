"""Opt-in weapon follow-ups: choose a new enemy after every settled hit."""
from copy import deepcopy

from . import effect, hook


@effect('weapon_hit_chain')
def marker(ctx, row):
    """The completed-attack boundary owns delivery, including lethal hits."""


@hook('attack_result')
def chain_result(ctx, target, hit, critical):
    capture = getattr(ctx.engine, '_weapon_hit_chain_result', None)
    if capture is not None and ctx.typed.get('weapon_hit_chain_follow') == 1:
        capture['hit'] = bool(hit)
        damage = ctx.attack_damage_context
        capture['target'] = damage.target_id if damage is not None else target.entity_id


@hook('attack_completed')
def continue_chain(engine, notice, intent):
    from ..attack_completion import can_continue
    from ..target_knowledge import located, attack_aim
    from .. import targeting
    from ..typed_executor import Context, block_attack
    from .needle import ask, checkpoint_id
    from .rider_helpers import effect_rows
    from .choice_prompt import action_context

    action = engine.action_catalog.get(notice.source_id)
    if action is None or not notice.hit or notice.attack_index != 1:
        return
    typed = action.parameters.get('typed') or {}
    spec = next((r for r in effect_rows(typed.get('effects'))
                 if r.get('type') == 'weapon_hit_chain'), None)
    if spec is None or not typed.get('weapon'):
        return
    actor = engine.state.actors[notice.attacker_id]
    visited = {notice.target_id}
    # The question is about the hit that just landed: name that attack and the creature it struck,
    # so the table reads "Batter hit Hobgoblin" rather than a bare menu, and a chain that runs on
    # somebody else's or another turn's attack still says whose hit granted it. The struck creature
    # is the one this choice is ABOUT; the recipient is not chosen yet.
    struck = engine.state.actors.get(notice.target_id)
    origin = action_context(engine, actor, notice.source_id, struck) if struck is not None else None
    # Quote the marker's own penalty, never a number typed here, so what the table is told is
    # exactly the first_roll_bonus prepare() hands the follow-up attack.
    penalty = int(spec.get('attack_bonus') or 0)
    bonus = f"at {penalty:+d}" if penalty else "with no change to the attack roll"
    # Each follow-up is the original implement's ordinary single attack. No
    # Batter, selected Exertion, extra-attack count, or variant riders propagate.
    from .weapon_hits import available_weapons
    from .hand_occupancy import weapon_allowed
    preferred_weapon = typed.get('weapon_source_id') or typed.get('maneuver_of')

    def prepare(base):
        payload = base.parameters.get('typed') or {}
        root = next((r for r in payload.get('effects') or [] if r.get('type') == 'attack'),
                    {'attack_kind': 'unarmed' if '.natural.' in base.source_definition_id else 'weapon'})
        attack = {'type': 'attack', 'attack_kind': root.get('attack_kind', 'weapon'),
                  'count': 1, 'first_roll_bonus': int(spec.get('attack_bonus', 0)),
                  'on_hit': [], 'on_miss': []}
        bare = {key: deepcopy(value) for key, value in payload.items() if key in (
            'weapon', 'numbers', 'duration', 'mundane', 'proficient', 'magic_bonus',
            'sphere', 'weapon_source_id', 'delivered_by', 'maneuver_of', 'inventory_key', 'thrown_equipment')}
        bare.update(source=str(spec.get('source_modifier') or action.source_definition_id), effects=[attack],
                    weapon_hit_chain_follow=1, weapon_source_id=base.source_definition_id, range_ft=None, long_range_ft=None)
        follow = base.model_copy(update={'source_definition_id': action.source_definition_id,
            'parameters': {'typed': bare}, 'range_ft': base.range_ft or base.reach_ft or 5})
        return follow, bare, attack

    while can_continue(engine, actor):
        # Only possessed, readied melee implements and current perceived enemies.
        # Weapon choice remains the player's; automatic choices prefer the
        # original implement, then the strongest available ordinary attack.
        options = []
        for key, base in available_weapons(engine, actor).items():
            payload = base.parameters.get('typed') or {}
            if payload.get('range_ft') or not payload.get('weapon'):
                continue
            follow, bare, attack = prepare(base)
            if weapon_allowed(engine, actor, follow, effect=attack) is False:
                continue
            pool = [a for a in engine.state.actors.values()
                    if a.active and a.entity_id not in visited and a.team_id != actor.team_id
                    and located(engine, actor, a)
                    and targeting.reason(engine, actor, a, follow) is None
                    and targeting.in_range(engine, actor, a, follow)]
            pool.sort(key=lambda a: (a.current_hp, a.entity_id))
            if pool:
                options.append((key, base, follow, bare, attack, pool))
        options.sort(key=lambda v: (v[0] != preferred_weapon,
                                   -int(v[1].parameters.get('expected_damage') or 0), v[0]))
        if not options:
            return
        weapon = options[0][0]
        if len(options) > 1:
            chosen = ask(engine, intent, checkpoint_id(engine, 'weapon_hit_chain_weapon', notice.source_id, str(len(visited))),
                         actor, 'choice:needle.weapon_hit_chain_weapon', [v[0] for v in options],
                         labels={v[0]: v[1].display_name for v in options}, allow_decline=True,
                         name=str(spec.get('label') or 'Follow-up attack'),
                         prompt_context=origin,
                         prompt=f'Choose a readied weapon for your next follow-up. It makes one attack {bonus}, without Exertion.',
                         preferred=[weapon])
            if not chosen:
                return
            weapon = chosen[0]
        _, _, follow, bare, attack, pool = next(v for v in options if v[0] == weapon)
        picked = ask(engine, intent, checkpoint_id(engine, 'weapon_hit_chain', notice.source_id, str(len(visited))),
                     actor, 'choice:needle.weapon_hit_chain', [a.entity_id for a in pool],
                     labels={a.entity_id: a.display_name for a in pool}, allow_decline=True,
                     name=str(spec.get('label') or 'Follow-up attack'),
                     prompt_context=origin,
                     prompt=f'Choose a different enemy within this weapon’s reach. Make one weapon attack {bonus}; '
                            'a hit lets you choose another enemy. No Exertion applies to these follow-ups.',
                     preferred=[pool[0].entity_id])
        if not picked:
            return
        target = engine.state.actors[picked[0]]
        visited.add(target.entity_id)
        capture = {}
        previous = getattr(engine, '_weapon_hit_chain_result', None)
        engine._weapon_hit_chain_result = capture
        try:
            with attack_aim(engine, actor, target, follow):
                block_attack(Context(engine, actor, follow, intent, bare, [target], target, {}), attack)
        finally:
            if previous is None:
                engine.__dict__.pop('_weapon_hit_chain_result', None)
            else:
                engine._weapon_hit_chain_result = previous
        if capture.get('target'):
            visited.add(capture['target'])
        if not capture.get('hit'):
            return
