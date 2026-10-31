"""Exact readied-pair damage; new reviewed rows opt in, historical rows stay inert."""
from __future__ import annotations

import json
import re
from . import effect, hook
from .qualifying_pairs import qualifying_pairs

CYCLONE = 'TAL_DUAL_WIELDING_CYCLONE_CUT'
ASYNC = 'TAL_DUAL_WIELDING_ASYNCHRONOUS_SWING'
FOCUS = 'resource:core.martial_focus'


def readied_pairs(engine, actor):
    """Enrich shared eligible physical pairs with ordinary printed dice and types."""
    rows = {}
    pairs = qualifying_pairs(engine, actor)
    for identity in dict.fromkeys(identity for pair in pairs for identity in pair):
        action = engine.action_catalog[identity]
        typed = action.parameters.get('typed') or {}
        weapon = typed.get('weapon') or {}
        sides = int(typed.get('normal_weapon_die_sides') or (weapon.get('damage') or {}).get('sides') or 0)
        if sides > 0:
            rows[identity] = {'id': identity, 'sides': sides,
                'types': [str(t).upper() for t in weapon.get('damage_types') or [weapon.get('damage_type') or 'UNTYPED']],
                'name': action.display_name.removesuffix(' attack')}
    return [(rows[a], rows[b]) for a, b in pairs if a in rows and b in rows]


@hook('candidate_allowed')
def cyclone_ready(engine, actor, candidate, action):
    if action is not None and any(row.get('type') == 'readied_pair_roll' for row in (action.parameters.get('typed') or {}).get('effects') or []):
        return bool(readied_pairs(engine, actor))
    return None


@effect('readied_pair_roll')
def pair_roll(ctx, row):
    """Seed the native damage cache once; saves, halving and defenses remain native."""
    from ..typed_executor import _roll, _walk_rows
    from ..gate2_runtime_models import DiceSpec
    from .needle import ask, checkpoint_id
    pairs = readied_pairs(ctx.engine, ctx.actor)
    if not pairs:
        raise ValueError('A readied qualifying weapon pair is required')
    options = [str(i) for i in range(len(pairs))]
    pick = options[0] if len(options) == 1 else ask(ctx.engine, ctx.intent,
        checkpoint_id(ctx.engine, 'READIED_PAIR'), ctx.actor, 'choice:needle.readied_pair', options,
        labels={str(i): f'{a["name"]} and {b["name"]}' for i, (a, b) in enumerate(pairs)},
        name=ctx.action.display_name, prompt='Choose the two readied weapons to use.')[0]
    pair = pairs[int(pick)]
    total = sum(_roll(ctx, DiceSpec(count=1, sides=w['sides'], modifier=0), 'DAMAGE',
                      damage_label=f'{ctx.action.display_name}: {w["name"]}') for w in pair)
    for damage in _walk_rows(ctx.typed.get('effects') or []):
        if damage.get('readied_pair_total'):
            ctx.damage_cache[id(damage)] = (total, str(row.get('damage_type') or 'BLUDGEONING').upper())


@hook('compile_block')
def async_marker(block, spec, row, numbers):
    if block == 'dw_asynchronous_exact':
        return [{**row, 'block': block}]
    return None


def _owns(ctx):
    return any(r.get('block') == 'dw_asynchronous_exact' for r in
               getattr(ctx.engine, 'typed_passive_rows', {}).get(ctx.actor.entity_id, []))


def _identity(ctx):
    from ..weapon_delivery import physical_weapon_id
    return physical_weapon_id(ctx.action.source_definition_id, ctx.action.parameters)


@hook('attack_sequence_start')
def swing_choice(ctx):
    if (not _owns(ctx) or ctx.engine.state.current_actor_id != ctx.actor.entity_id
            or not any(e.get('type') == 'attack' and e.get('attack_kind') == 'weapon'
                       for e in ctx.typed.get('effects') or [])):
        return
    identity = _identity(ctx)
    pairs = [pair for pair in readied_pairs(ctx.engine, ctx.actor) if identity in {w['id'] for w in pair}]
    if not pairs:
        return
    seen = json.loads(str(ctx.actor.turn_flags.get('dw_async_seen') or '[]'))
    if identity not in seen:
        seen.append(identity)
    ctx.actor.turn_flags['dw_async_seen'] = json.dumps(seen)
    if ctx.actor.resources.get(FOCUS, 0) < 1:
        return
    eligible = [pair for pair in pairs if all(w['id'] in seen for w in pair)
                and (pair[0]['id'] != pair[1]['id'] or ctx.typed.get('pair_role') == 'answer')]
    if not eligible:
        return
    from .needle import ask, checkpoint_id
    options = [str(i) for i in range(len(eligible))]
    pick = options[0] if len(options) == 1 else ask(ctx.engine, ctx.intent,
        checkpoint_id(ctx.engine, 'ASYNC_PAIR'), ctx.actor, 'choice:needle.async_pair', options,
        labels={str(i): f'{a["name"]} and {b["name"]}' for i, (a, b) in enumerate(eligible)},
        name='Asynchronous Swing', prompt='Choose the qualifying pair whose attacks you made.')[0]
    pair = eligible[int(pick)]
    sides = sorted({w['sides'] for w in pair})
    kinds = list(dict.fromkeys(t for w in pair for t in w['types']))
    die = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'ASYNC_DIE'), ctx.actor,
              'choice:needle.async_die', [str(n) for n in sides], labels={str(n): f'd{n}' for n in sides},
              name='Asynchronous Swing', prompt='Choose the normal weapon die both weapons use until this turn ends.',
              preferred=[str(max(sides))])[0]
    kind = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'ASYNC_TYPE'), ctx.actor,
               'choice:needle.async_type', kinds, labels={t: t.title() for t in kinds},
               name='Asynchronous Swing', prompt='Choose a damage type normally dealt by either weapon.')[0]
    choices = json.loads(str(ctx.actor.turn_flags.get('dw_async_choice') or '{}'))
    for weapon in pair:
        choices[weapon['id']] = {'sides': int(die), 'type': kind}
    ctx.actor.turn_flags['dw_async_choice'] = json.dumps(choices)


def _choice(ctx):
    if (not _owns(ctx) or ctx.engine.state.current_actor_id != ctx.actor.entity_id
            or not any(e.get('type') == 'attack' and e.get('attack_kind') == 'weapon'
                       for e in ctx.typed.get('effects') or [])):
        return None
    choices = json.loads(str(ctx.actor.turn_flags.get('dw_async_choice') or '{}'))
    return choices.get(_identity(ctx))


@hook('attack_damage')
def swing_die(ctx, dice):
    choice = _choice(ctx)
    if choice and dice is not None and ctx.weapon_damage_dice:
        return dice.model_copy(update={'sides': choice['sides']})
    return None


@hook('attack_damage_types')
def swing_type(ctx, attack, kinds):
    choice = _choice(ctx)
    if choice and ctx.weapon_damage_dice:
        return [choice['type']]
    return None

HIGHLOW = 'TAL_DUAL_WIELDING_HIGH_LOW_COMBINATION'


@hook('compile_block')
def highlow_marker(block, spec, row, numbers):
    if block == 'dw_highlow_exact':
        return [{**row, 'block': block}]
    return None


@hook('choice_reactors')
def highlow_defenders(engine):
    if any(r.get('block') == 'dw_highlow_exact' for rows in
           getattr(engine, 'typed_passive_rows', {}).values() for r in rows):
        return tuple(engine.state.actors)
    return ()


@hook('after_hit_effects')
def highlow_shove(ctx, target, kind):
    if (kind != 'weapon' or not target.active or ctx.engine.state.current_actor_id != ctx.actor.entity_id
            or ctx.typed.get('pair_role') not in {'lead', 'answer'}
            or not any(r.get('block') == 'dw_highlow_exact' for r in
                       getattr(ctx.engine, 'typed_passive_rows', {}).get(ctx.actor.entity_id, []))):
        return
    from .needle import ask, checkpoint_id
    from . import ai_controlled
    from .choice_costs import payable
    from ..typed_executor import run_effects
    from ..catalog_queries import owned_actions
    from ..targeting import attack_line_of_effect
    from dataclasses import replace
    import copy
    pairs = [p for p in readied_pairs(ctx.engine, ctx.actor) if _identity(ctx) in {w['id'] for w in p}]
    if not pairs:
        return
    # Role provenance is the compiler's Lead/Answering Weapon identity, not damage or ownership guesses.
    hits = json.loads(str(ctx.actor.turn_flags.get('dw_highlow_hits') or '{}'))
    roles = hits.get(target.entity_id, {'lead': [], 'answer': []})
    identity = _identity(ctx)
    role = ctx.typed['pair_role']
    opposite = 'answer' if role == 'lead' else 'lead'
    # Keep cumulative provenance, but each fresh actual hit is a new opportunity
    # until a Shove is used; lack of Focus or declining does not consume the use.
    if identity not in roles[role]:
        roles[role].append(identity)
    hits[target.entity_id] = roles
    ctx.actor.turn_flags['dw_highlow_hits'] = json.dumps(hits)
    if (not any(a['id'] in roles[role] and b['id'] in roles[opposite]
                or b['id'] in roles[role] and a['id'] in roles[opposite] for a, b in pairs)
            or ctx.actor.turn_flags.get('dw_highlow_used')):
        return
    if ai_controlled(ctx.engine, ctx.actor):
        from ..target_knowledge import located
        if target.team_id == ctx.actor.team_id or not located(ctx.engine, ctx.actor, target):
            return
    payment = payable(ctx.actor, FOCUS, 1)
    if payment is None:
        return
    options = {a.parameters['typed']['unarmed_option']: a for a in owned_actions(ctx.engine, ctx.actor.entity_id)
               if (a.parameters.get('typed') or {}).get('unarmed_option') in {'shove_push', 'shove_prone'}
               and ctx.engine._target_in_range(ctx.actor, target, a)
               and attack_line_of_effect(ctx.engine, ctx.actor, target, a.source_definition_id)
               and shove_size_ready(ctx.engine, ctx.actor, target, a.parameters['typed']['effects'][0])}
    if not options:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'HIGH_LOW', target.entity_id), ctx.actor,
                 'choice:needle.highlow_shove', list(options),
                 labels={k: a.display_name for k, a in options.items()}, allow_decline=True,
                 name='High-Low Combination', target_id=target.entity_id, payment=payment,
                 automatic=ai_controlled(ctx.engine, ctx.actor),
                 prompt=f'Both weapons hit {target.display_name}. Expend Martial Focus to Shove them now, '
                        'with no additional action, or decline. Choose Push 5 feet or Prone.')
    if not picked:
        return
    action = options[picked[0]]
    typed = copy.deepcopy(action.parameters['typed'])
    typed['source'] = HIGHLOW
    typed['effects'] = typed['effects'][:1]  # exactly one Shove; never the Attack action's extra attacks
    typed['effects'][0]['target_choice'] = True
    typed['effects'][0]['name'] = 'High-Low Combination'
    ctx.actor.turn_flags['dw_highlow_used'] = 1
    payment.pay(ctx.engine, ctx.actor, HIGHLOW)
    inner = replace(ctx, action=action, typed=typed, targets=[target], target=target,
                    effect_source=HIGHLOW, damage_cache={})
    run_effects(inner, typed['effects'])


def shove_size_ready(engine, actor, target, attempt):
    """Ordinary 5.5e category limit plus existing purpose/role-specific functional sizes.

    A saved actor's category can exceed its arena footprint; neither category
    nor a printed effective-size benefit is inferred from width alone.
    """
    from ..dynamic_size import current_category, CATEGORIES
    from .effective_size import steps, purposes_of
    purposes = purposes_of(attempt)
    acting = CATEGORIES.index(current_category(engine, actor)) + steps(engine, actor, 'act', purposes)
    resisting = CATEGORIES.index(current_category(engine, target)) + steps(engine, target, 'resist', purposes)
    return resisting <= acting + int(attempt.get('max_size_larger') or 0)


@hook('compile_weapon_traits')
def seal_normal_weapon_die(info):
    """Seal the ordinary printed die before grip resizing, bonuses and attack riders."""
    if not {CYCLONE, ASYNC, HIGHLOW}.intersection(info['owned_ids']):
        return None
    from ..factory_compiler import weapon_specials
    weapon = info['weapon']
    normal = (weapon_specials().get(weapon['item_id']) or {}).get('damage') or weapon['damage']
    printed = re.search(r'(\d+)d(\d+)', str(normal))
    return {'normal_weapon_die_sides': int(printed.group(2))} if printed else None
