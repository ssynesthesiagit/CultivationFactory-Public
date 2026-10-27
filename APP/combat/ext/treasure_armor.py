"""Combat benefits of equipped treasure armor, sealed at character compilation.

Enhancements are inventory properties, not talents. Effective kit records have
already passed attunement/leave-behind; the worn key is chosen by the compiler.
Persisted primitive rows carry their numbers and choices through cold reload.
No runtime authority lookup or mutation of another ability's catalog is used.
"""
from copy import deepcopy
from . import hook, note
from .needle import CHOICE, ask, checkpoint_id, incapacitated

PREFIX = 'tianxia.treasure.armor_enhancement.'
BLOCK = 'treasure_armor'
ELEMENTS = {'ACID', 'COLD', 'FIRE', 'LIGHTNING', 'POISON', 'THUNDER'}
SOVEREIGN = ELEMENTS | {'PSYCHIC', 'RADIANT', 'NECROTIC'}

IMPLEMENTED = {
    'silent_lacing', 'weightless_harness', 'helmet_seal_inscription',
    'padded_impact_layers', 'fire_shedding_lining', 'frost_shedding_lining',
    'lightning_grounding_mesh', 'poison_filtering_collar', 'featherfall_skirt',
    'dark_sight_visor', 'meridian_clear_underlayer', 'anti_corrosion_temper',
    'grasp_breaking_plates', 'elemental_resistance_weave', 'force_dispersal_circuit',
    'spirit_guarding_hood', 'blood_sealing_inner_layer', 'law_resisting_seal_plates',
    'thorn_retaliation_plates', 'shield_link_inscription',
    'sovereign_resistance_matrix', 'mountain_pattern_fortress',
    'heaven_veil_imperial_robe', 'immovable_mountain_grand_shell', 'iron_rain_deflection', 'deflecting_shield_face',
}


def rows(engine, actor, kind=None):
    from ..carry import carrying_of, item_of, lost_to_another_hand
    out = []
    for row in engine.typed_passive_rows.get(actor.entity_id, ()):
        if row.get('block') != BLOCK or (kind and row['kind'] != kind):
            continue
        item = item_of(carrying_of(engine, actor.entity_id), key=row['item_key'])
        if not item or not (item.get('worn') or (item.get('shield') and not lost_to_another_hand(actor, row['item_key']))):
            continue
        if any(c.condition_id == 'condition:typed.treasure_armor_folded' and c.data.get('item_key') == row['item_key'] for c in actor.conditions.values()):
            continue
        out.append(row)
    return out


def owned(engine, actor, kind):
    return next(iter(rows(engine, actor, kind)), None)


@hook('compile_bundle')
def compile_armor(bundle, info):
    records = [('treasure_armor', info['kit'].get('resolved_treasure_armor'))]
    records += [(f'given.{i}', r.get('record')) for i, r in enumerate(info['owner_items'])]
    additions = []
    for key, record in records:
        item = next((r for r in bundle['carrying']['items'] if r['key'] == key), None)
        if not isinstance(record, dict) or not item:
            continue
        for enhancement in record.get('enhancements') or []:
            if not isinstance(enhancement, dict):
                continue
            fid = str(enhancement.get('enhancement_id') or '')
            if not fid.startswith(PREFIX) or fid[len(PREFIX):] not in IMPLEMENTED:
                continue
            if not (item.get('worn') or item.get('shield')) and fid != PREFIX + 'weightless_harness':
                continue
            additions.append({'block': BLOCK, 'feature_id': fid, 'kind': fid[len(PREFIX):],
                              'name': enhancement['name'], 'item_key': key,
                              'choice_owner': fid[len(PREFIX):] in {'helmet_seal_inscription', 'blood_sealing_inner_layer', 'deflecting_shield_face'},
                              'numbers': dict(info['numbers']),
                              'damage_types': [str(t).upper() for t in enhancement.get('damage_types', [])]})
    if not additions:
        return None
    result = deepcopy(bundle)
    result['typed_passives'].extend(additions)
    kinds = {r['kind'] for r in additions}
    if 'silent_lacing' in kinds:
        result['carrying'].pop('stealth_disadvantage', None)
        for action in result['action_catalog']:
            parameters = action.get('parameters') or {}
            if parameters.get('basic') and parameters.get('stealth') == 'hide':
                for effect in (parameters.get('typed') or {}).get('effects', []):
                    if effect.get('type') == 'hide' and effect.get('mode') == 'DISADVANTAGE':
                        effect.pop('mode')

    if 'immovable_mountain_grand_shell' in kinds:
        result['carrying']['capacity_lb'] *= 2
        result['carrying']['over'] = float(result['carrying']['weight_lb']) > result['carrying']['capacity_lb']
    # Weight and the Strength requirement belong to this equipped physical item.
    for key, record in records:
        if not isinstance(record, dict) or not any(r['kind'] == 'weightless_harness' and r['item_key'] == key for r in additions):
            continue
        item = next(r for r in result['carrying']['items'] if r['key'] == key)
        before_weight = float(item['weight_lb'])
        item['weight_lb'] = f'{before_weight / 2:g}'
        result['carrying']['weight_lb'] = f"{float(result['carrying']['weight_lb']) - before_weight / 2:g}"
        if item.get('worn'):
            import re
            requirement = re.search(r'\d+', str(record['chassis'].get('strength') or ''))
            stats = info['owner_sheet']['ability_scores_and_statistics']
            strength = next((int(r['score']) for r in stats['abilities'] if r['ability'] == 'STR'), 10)
            if requirement and strength < int(requirement[0]):
                recovered = min(10, int((stats.get('speed') or {}).get('walking_ft') or 30))
                result['carrying']['speed_ft'] += recovered
                result['diagnostics']['notes'] = [n for n in result['diagnostics']['notes']
                                                  if not n.startswith('Armour needs more Strength than this character has:')]
    result['carrying']['over'] = float(result['carrying']['weight_lb']) > result['carrying']['capacity_lb']
    unburdened = result['carrying']['speed_ft']
    result['actor_template']['speed_ft'] = min(5, unburdened) if result['carrying']['over'] else unburdened
    result['carrying']['template_speed_ft'] = result['actor_template']['speed_ft']
    result['diagnostics']['notes'] = [n for n in result['diagnostics']['notes']
                                      if not (n.startswith('Carrying ') and ' lb, over the ' in n)]
    if result['carrying']['over']:
        result['diagnostics']['notes'].append(
            f"Carrying {result['carrying']['weight_lb']} lb, over the {result['carrying']['capacity_lb']} lb capacity: "
            f"Speed {result['actor_template']['speed_ft']} ft")
    for row in additions:
        if row['kind'] == 'dark_sight_visor':
            senses = result.setdefault('senses', {'rows': [], 'melds': [], 'meld_start': None})
            senses['rows'].append({'sense': 'darkvision', 'range_ft': 60, 'or_add_ft': 30,
                                   'when': 'always', 'feature_id': row['feature_id']})
    return result


@hook('damage_defenses')
def resistances(engine, target, damage_type, typed, source_actor_id):
    found = []
    for row in rows(engine, target):
        kind = row['kind']
        types = (['FORCE'] if kind in {'force_dispersal_circuit', 'heaven_veil_imperial_robe'} else
                 choice_types(engine, target, row) if kind in {'elemental_resistance_weave', 'sovereign_resistance_matrix'} else [])
        legal = SOVEREIGN if kind == 'sovereign_resistance_matrix' else ELEMENTS
        if kind in {'elemental_resistance_weave', 'sovereign_resistance_matrix'}:
            types = [t for t in types if t in legal][:2 if kind == 'sovereign_resistance_matrix' else 1]
        if types:
            found.append({'kind': 'resistance', 'damage_types': types, 'feature_id': row['feature_id']})
    return found or None


@hook('damage_reduction')
def elemental_linings(engine, target, damage_type, typed, source_actor_id, applied=False):
    names = {'FIRE': 'fire_shedding_lining', 'COLD': 'frost_shedding_lining', 'LIGHTNING': 'lightning_grounding_mesh'}
    row = owned(engine, target, names.get(str(damage_type).upper(), '')) if str(damage_type).upper() in names else None
    return int(row['numbers']['pb']) if row else None


@hook('final_damage')
def fortress_and_survival(engine, target, amount, damage_type, source_id, source_actor_id, intent):
    result = {}
    fortress = owned(engine, target, 'mountain_pattern_fortress')
    if fortress and amount > 0:
        result['amount'] = max(1, amount - int(fortress['numbers']['pb']))
    force = owned(engine, target, 'force_dispersal_circuit')
    if force and str(damage_type).upper() == 'FORCE':
        from ..typed_reactions import resistance_profile
        action = engine.action_catalog.get(source_id)
        profile = (action.parameters.get('typed') or {}) if action else {}
        if resistance_profile(engine, target, 'FORCE', profile, source_id=source_id, source_actor_id=source_actor_id, excluded_feature_ids=(force['feature_id'],))['resist']:
            result['reduction'] = min(amount, int(force['numbers']['pb']))
    row = owned(engine, target, 'blood_sealing_inner_layer')
    defended = max(0, result.get('amount', amount) - result.get('reduction', 0))
    remaining = max(0, defended - target.temporary_hp)
    if row and target.current_hp > 0 and remaining >= target.current_hp and remaining - target.current_hp < target.maximum_hp:
        used = 'condition:typed.treasure_blood_seal_spent'
        if not any(c.condition_id == used and c.data.get('item_key') == row['item_key'] for c in target.conditions.values()):
            picked = ask(engine, intent, checkpoint_id(engine, 'treasure_blood_seal', target.entity_id, len(engine.events)),
                         target, CHOICE + 'treasure_blood_seal', ['use'], preferred=['use'], allow_decline=True,
                         automatic=True, name=row['name'], feature_id=row['feature_id'], target_id=target.entity_id,
                         prompt=f"{row['name']}: stay at 1 Hit Point instead of falling to 0? You can use this once per Long Rest.")
            if picked:
                engine._apply_condition(target, used, row['feature_id'], target.entity_id, expires_on='UNTIL_REMOVED', data={'item_key': row['item_key']})
                result['hp_floor'] = 1
    return result or None


@hook('critical_cancel')
def helmet(engine, attacker, target, spec, roll, intent):
    row = owned(engine, target, 'helmet_seal_inscription')
    used = 'condition:typed.treasure_helmet_seal_spent'
    if not row or any(c.condition_id == used and c.data.get('item_key') == row['item_key'] for c in target.conditions.values()):
        return None
    picked = ask(engine, intent, checkpoint_id(engine, 'treasure_helmet', target.entity_id, roll.roll_id),
                 target, CHOICE + 'treasure_helmet', ['use'], preferred=['use'], allow_decline=True, automatic=True,
                 name=row['name'], feature_id=row['feature_id'], target_id=target.entity_id,
                 prompt=f"{row['name']}: turn this critical hit into a normal hit? You can use this once per Long Rest.")
    if picked:
        engine._apply_condition(target, used, row['feature_id'], target.entity_id, expires_on='UNTIL_REMOVED', data={'item_key': row['item_key']})
        return True


@hook('condition_immune')
def immovable_condition(engine, actor, name):
    if conscious(actor) and owned(engine, actor, 'immovable_mountain_grand_shell') and str(name).rsplit('.', 1)[-1].lower() == 'prone':
        return True



@hook('forced_movement_restriction')
def immovable_distance(ctx, subject, effect, maximum_ft):
    if conscious(subject) and owned(ctx.engine, subject, 'immovable_mountain_grand_shell'):
        return 0


@hook('size_steps')
def immovable_size(engine, actor, role, purposes):
    if role == 'resist' and set(purposes or ()) & {'grapple', 'shove'} and owned(engine, actor, 'immovable_mountain_grand_shell'):
        return 1


@hook('escape_mode')
def escape_checks(engine, actor, grips):
    return 'ADVANTAGE' if owned(engine, actor, 'grasp_breaking_plates') else None


@hook('escape_save_mode')
def escape_saves(engine, actor, grips):
    return 'ADVANTAGE' if owned(engine, actor, 'grasp_breaking_plates') else None


@hook('save')
def scoped_saves(ctx, subject, ability, named):
    tags = {str(x).lower() for x in named or ()}
    advantage = False
    for row in rows(ctx.engine, subject):
        kind = row['kind']
        if kind == 'spirit_guarding_hood' and tags & {'charmed', 'frightened', 'possessed', 'possession', 'category:possession'}:
            advantage = True
        if kind == 'poison_filtering_collar' and 'category:inhalation' in tags and tags & {'poisoned', 'poison', 'category:poison'}:
            advantage = True
        if kind == 'meridian_clear_underlayer' and tags & {'category:resource_suppression'}:
            advantage = True
        if kind == 'anti_corrosion_temper' and tags & {'category:armor_corrosion', 'category:armor_destruction'}:
            advantage = True
        if kind == 'law_resisting_seal_plates' and (ctx.typed.get('supernatural') is True or ctx.typed.get('qi_powered') is True):
            advantage = True
    return {'bonus': 0, 'modes': ['ADVANTAGE']} if advantage else None


@hook('save_mode')
def native_scoped_saves(engine, subject, ability, dc, source_id, context):
    """Read the same explicit provenance on initial, native and repeated saves."""
    from types import SimpleNamespace
    action = engine.action_catalog.get(source_id)
    typed = (action.parameters.get('typed') or {}) if action else {}
    reply = scoped_saves(SimpleNamespace(engine=engine, typed=typed), subject,
                         ability, context.get('named') or ())
    return 'ADVANTAGE' if reply else None


@hook('before_attack')
def iron_rain(engine, attacker, defender, intent, context):
    if not owned(engine, defender, 'iron_rain_deflection'):
        return None
    frame = engine.d20_context() or {}
    source = context['source_id']
    action = context.get('action') or engine.action_catalog.get(source)
    from ..attack_provenance import describe
    descriptor = describe(engine, attacker, {
        **(frame.get('spec') or {}),
        'parameters': action.parameters if action else {},
        'typed': context.get('typed') or ((action.parameters.get('typed') or {}) if action else {}),
        'checkpoint_context': {'effect': context.get('effect')}}, source)
    if not descriptor or not descriptor['ranged'] or descriptor['delivery'] != 'weapon':
        return None
    typed, parameters, effect = descriptor['typed'], descriptor['parameters'], descriptor['effect'] or {}
    # Explicit packet metadata, never guessed from a name or range.
    if any(row.get('siege_weapon') or row.get('ignore_cover') for row in (typed, parameters, effect)):
        return None
    from ..shot_geometry import reduce_cover
    if reduce_cover(engine, attacker, defender, 5) == 0:
        return None  # Native cover-ignoring routes count even without a marker.
    if engine._distance_actor_to_actor(attacker, defender) >= 30:
        return {'mode': 'DISADVANTAGE'}


@hook('hit_snapshot')
def thorn_hit_receipt(engine, attacker, target, attack_context, intent):
    row = owned(engine, target, 'thorn_retaliation_plates')
    spec = (engine.d20_context() or {}).get('spec') or {}
    action = engine.action_catalog.get(attack_context.source_id)
    melee = (spec.get('reach_ft') is not None or spec.get('range_ft') is None) if spec else (
        action is not None and (action.reach_ft is not None or action.range_ft is None))
    if row and melee and engine._distance_actor_to_actor(target, attacker) <= 5:
        return {'treasure_armor_thorns': {'source': row['feature_id'], 'name': row['name'],
                                        'amount': int(row['numbers']['pb']),
                                        'defender': target.entity_id, 'attacker': attacker.entity_id}}


@hook('hit_final')
def thorns(ctx, target, kind):
    receipt = ctx.hit_snapshots.get('treasure_armor_thorns')
    if (receipt and receipt['defender'] == target.entity_id and receipt['attacker'] == ctx.actor.entity_id):
        ctx.engine._commit_damage(ctx.actor, receipt['amount'], 'PIERCING', receipt['source'],
                                  target.entity_id, ctx.intent, reaction_depth=0)
        note(ctx.engine, receipt['source'], target,
             f"{receipt['name']}: {ctx.actor.display_name} takes {receipt['amount']} piercing damage.")


@hook('teleport_context_check')
def immovable_teleport(engine, actor, start, destination, movement_context):
    if str(movement_context).upper() == 'FORCED' and conscious(actor) and owned(engine, actor, 'immovable_mountain_grand_shell'):
        return False


def conscious(actor):
    return actor.active and actor.current_hp > 0 and not any(
        c.condition_id.rsplit('.', 1)[-1] == 'unconscious' for c in actor.conditions.values())


@hook('sense_grant_allowed')
def armor_sight(engine, actor, grant, seen):
    if str(grant.get('feature_id') or '') == PREFIX + 'dark_sight_visor':
        return False if not owned(engine, actor, 'dark_sight_visor') else None


def choice_types(engine, actor, row):
    selected = next((c.data.get('damage_types', []) for c in actor.conditions.values()
                     if c.condition_id == 'condition:typed.treasure_armor_element_choice'
                     and c.data.get('feature_id') == row['feature_id'] and c.data.get('item_key') == row['item_key']), None)
    return row['damage_types'] if selected is None else selected


@hook('prefight_setup_choices')
def armor_creation_choices(bundle):
    out = []
    for row in bundle.get('typed_passives', []):
        if row.get('block') != BLOCK or row['kind'] not in {'elemental_resistance_weave', 'sovereign_resistance_matrix'}:
            continue
        options = sorted(SOVEREIGN if row['kind'] == 'sovereign_resistance_matrix' else ELEMENTS)
        count = 2 if row['kind'] == 'sovereign_resistance_matrix' else 1
        indexes = [options.index(t) + 1 for t in row['damage_types'] if t in options][:count]
        out.append({'id': 'armor_element_' + row['item_key'] + '_' + row['kind'],
                    'label': row['name'] + ': damage types chosen when created',
                    'help': 'Record the types chosen when this enhancement was made: 0 = no recorded choice; '
                            + '; '.join(f'{i} = {t.title()}' for i, t in enumerate(options, 1))
                            + '. This records your earlier choice and does not remake the item.',
                    'kind': 'integer_range_list', 'count': count, 'item_label': 'Damage type',
                    'minimum': 0, 'maximum': len(options), 'default': indexes + [0] * (count - len(indexes))})
    return out or None


@hook('match_start')
def record_creation_choices(engine):
    for bundle in engine.typed_bundle_documents:
        actor = engine.state.actors.get(bundle['actor_id'])
        if actor is None:
            continue
        picks = (bundle.get('prefight') or {}).get('setup_choices') or {}
        for row in bundle.get('typed_passives', []):
            if row.get('block') != BLOCK or row['kind'] not in {'elemental_resistance_weave', 'sovereign_resistance_matrix'}:
                continue
            key = 'armor_element_' + row['item_key'] + '_' + row['kind']
            if key not in picks:
                continue
            options = sorted(SOVEREIGN if row['kind'] == 'sovereign_resistance_matrix' else ELEMENTS)
            count = 2 if row['kind'] == 'sovereign_resistance_matrix' else 1
            selected = list(dict.fromkeys(options[i - 1] for i in picks[key][:count] if type(i) is int and 1 <= i <= len(options)))
            engine._apply_condition(actor, 'condition:typed.treasure_armor_element_choice', row['feature_id'], actor.entity_id,
                                    expires_on='UNTIL_REMOVED', data={'feature_id': row['feature_id'], 'item_key': row['item_key'], 'damage_types': selected})


@hook('falling_damage_distance')
def skirt_distance(engine, actor, distance_ft, fall, intent):
    return max(0, distance_ft - 30) if owned(engine, actor, 'featherfall_skirt') else None


@hook('falling_damage')
def skirt_landing(engine, target, amount, fall, intent):
    row = owned(engine, target, 'padded_impact_layers')
    result = {'amount': max(0, amount - int(row['numbers']['pb']))} if row else {}
    if owned(engine, target, 'featherfall_skirt') and not incapacitated(target):
        result['land_prone'] = False
    return result or None


@hook('effect_cover')
def linked_shield_cover(engine, source, target, ray):
    from ..read_queries import shared_query
    from ..relations import relation, ALLY
    from ..effect_cover import rays
    # Who bears the inscription is fixed for one unchanged fight state, while a
    # cover query asks this hook for every ray of every prospective square.
    # Share that ownership read inside one read-only frame; an empty answer
    # makes the hook inert without touching the other creatures at all.
    owners = shared_query(engine, ('treasure_armor.linked_shield_owners',), lambda: tuple(
        actor.entity_id for actor in engine.state.actors.values()
        if owned(engine, actor, 'shield_link_inscription')))
    for actor_id in owners:
        actor = engine.state.actors.get(actor_id)
        if actor is None or actor.entity_id == target.entity_id or incapacitated(actor):
            continue
        if relation(engine, actor, target) != ALLY:
            continue
        if (engine._distance_actor_to_actor(actor, target) <= 5
                and next(rays(engine, engine._actor_volume(actor), engine._actor_volume(target), purpose='effect'), None) is not None):
            return 2


@hook('save_bonus_details')
def linked_shield_save(engine, target, ability, dc, source_id, intent):
    if ability != 'DEX' or linked_shield_cover(engine, None, target, {}) is None:
        return None
    context = engine.d20_context() or {}
    origins = context.get('effect_origin_cells') or []
    if origins:
        bonus = engine.cover_from(origins, context.get('source_actor_id'), target)['bonus']
        return {'bonus': bonus, 'contributions': {'cover': bonus}} if bonus else None


def has_mandatory_aftermath(engine):
    return any(owned(engine, actor, 'thorn_retaliation_plates') for actor in engine.state.actors.values())


@hook('attack_resolution_scope')
def native_mandatory_aftermath(engine, actor, target, spec, intent):
    # A declaration may redirect its defender. Hold this whole strike if any
    # equipped bearer can supply a mandatory hit rider; hit_snapshot still
    # qualifies the actual resolved defender, delivery and trigger distance.
    return engine.victory_deferred() if has_mandatory_aftermath(engine) else None


@hook('effect_resolution_scope')
def typed_mandatory_aftermath(ctx, effect):
    if effect.get('type') == 'attack' and has_mandatory_aftermath(ctx.engine):
        return ctx.engine.victory_deferred()


@hook('final_damage')
def deflecting_shield(engine, target, amount, damage_type, source_id, source_actor_id, intent):
    from .. import typed_reactions
    from ..gate2_runtime_models import DiceSpec
    from ..paid_relocation import activation
    from ..relations import relation, ALLY
    from ..target_knowledge import located
    from . import ai_controlled, run_strict
    from .choice_costs import payable
    from .choice_prompt import action_context
    from .cp_pools import of
    packet = engine.damage_context()
    if amount <= 0 or intent is None or packet is None or packet.target_id != target.entity_id:
        return None
    remaining = amount
    for owner in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        row = owned(engine, owner, 'deflecting_shield_face')
        if (not row or relation(engine, owner, target) != ALLY
                or engine._distance_actor_to_actor(owner, target) > 5
                or not typed_reactions.can_use_reaction(engine, owner, target, row)):
            continue
        if ai_controlled(engine, owner) and owner is not target and not located(engine, owner, target):
            continue
        payment = payable(owner, of(owner, at_least=1) or '', 1)
        if payment is None or any(v is False for v in run_strict('cost_available', engine, owner, payment.pool, 1, {})):
            continue
        picked = ask(engine, intent, checkpoint_id(engine, 'armor_deflect', owner.entity_id, packet.roll_id, target.entity_id),
            owner, CHOICE + 'armor_deflect', ['use'], allow_decline=True, name=row['name'], feature_id=row['feature_id'],
            target_id=target.entity_id, payment=payment,
            prompt_context=action_context(engine, engine.state.actors.get(source_actor_id), source_id, target),
            labels={'use': 'Spend your Reaction and 1 CP to reduce damage by 2d8 + your Proficiency Bonus'},
            prompt=f"{row['name']}: {target.display_name} takes {remaining} {damage_type.lower()} damage from an attack. "
                   'Spend your Reaction and 1 CP to reduce this damage by 2d8 + your Proficiency Bonus?')
        if not picked:
            continue
        with activation(engine, owner, row['feature_id']):
            payment.pay(engine, owner, row['feature_id'])
            typed_reactions.open_reaction(engine, row, owner, (target.entity_id,), 'FINAL_DAMAGE')
            typed_reactions.spend_reaction(engine, owner, row)
            roll = engine.roller.roll(DiceSpec(count=2, sides=8, modifier=int(row['numbers']['pb'])),
                                      actor_id=owner.entity_id, reason='TREASURE_SHIELD_REDUCTION')
            engine._record_roll(roll)
            reduction = min(remaining, max(0, roll.total))
            remaining -= reduction
            engine._append_event('REACTION_RESOLVED', row['feature_id'], actor_id=owner.entity_id,
                target_ids=(target.entity_id,), payload={'ability': row['name'], 'reduction': reduction, 'roll_id': roll.roll_id})
        if remaining == 0:
            break
    return {'reduction': amount - remaining} if remaining < amount else None
