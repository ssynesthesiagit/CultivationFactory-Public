"""Foundation combat conversions with sealed scope, native clocks and player consent.

Scope tags are reviewed action data, never a runtime guess from a sphere/name.
Close martial hits qualify directly for the printed body Foundations. Resource
creation happens after spending opportunities and uses pressure's persisted clock.

Shared helper module: dream_mirror.py (the Dream-Mirror Soul Anchor sphere)
imports this module's ownership, hostility, naming and pressure helpers, so
every foundation combat plug-in and the Dream-Mirror plug-in consume them.
"""
from . import effect, hook, note
from .needle import ask, checkpoint_id, CHOICE, timed_condition, numbers_of
from .passive_rows import row_of

BLOCK = 'foundation_combat'
P = 'condition:typed.foundation_combat.'
GROUPS = {
    'ash': ('ash_born_remnant_core_v0_2B', 'remnant_cinder'),
    'glass': ('glass_heart_meridian_v0_2A', 'glass_reflection'),
    'tyrant': ('heaven_tyrant_body_v0_2D', 'tyrant_form_pulse'),
    'origin': ('innate_sacred_body_dao_embryo_v0_2B', 'origin_bell_tone'),
    'devour': ('heaven_devouring_shedding_womb_v0_2B', 'devoured_origin_spark'),
    'mandate': ('golden_mandate_seal_v0_2B', 'edict_seal'),
    'furnace': ('jade_furnace_meridian_v0_2B', 'furnace_heat'),
    'oath': ('iron_oath_skin_v0_2B', 'guarding_iron'),
    'integrity': ('heavenly_body_v0_2F', 'heavenly_integrity'),
    'blood': ('true_blackblood_physique_v0_2C', 'blackblood_pressure'),
}
BODY = {'forced_movement', 'prone', 'grappled', 'restrained', 'body_suppression'}
ORIGIN = BODY | {'authority_suppression', 'formation_pressure', 'gravity_pressure', 'fate_pressure', 'spatial_displacement'}
DEVOUR = {'drain', 'origin_theft', 'possession', 'source_corruption', 'healing_denied'}
# Shared harm vocabulary for the older Foundation predicates (Furnace Vent Guard,
# Jade Furnace Meridian Frame, Devour Womb). It includes generic 'disease'.
# Clean Residue Circulation does NOT use it as-is; see the next-save check below.
RESIDUE = {'poisoned', 'poison', 'miasma', 'contaminated_qi', 'furnace_backlash', 'technique_residue', 'disease'}
MANDATE = {'frightened', 'charmed', 'hostile_command', 'false_authority', 'compelled'}
OATH = {'frightened', 'charmed', 'domination', 'disarm', 'bypass'} | BODY


def feature(group, leaf):
    return 'foundation.' + GROUPS[group][0] + '.' + leaf


def pool(group):
    return 'resource:foundation.' + GROUPS[group][1]


def row(engine, actor, group, leaf):
    return row_of(engine, actor.entity_id, BLOCK, group + ':' + leaf)


def held(actor, key):
    return next((c for c in actor.conditions.values() if c.condition_id == P + key), None)


def names(values):
    return {str(v).lower().removeprefix('condition:typed.') for v in values or ()}


def roll_names(values):
    """Normalize explicit save categories for both Surge selection and spending.

    Bare check hazards and typed condition names retain their existing meaning;
    unrelated condition/generation consumers keep using ``names``.
    """
    return names(str(v).lower().removeprefix('category:') for v in values or ())


def hostile(a, b):
    return a is not None and b is not None and a.team_id != b.team_id


def aligned(typed, group):
    return group in (typed.get('foundation_alignment') or [])


def body_hit(ctx, target, kind):
    return (hostile(ctx.actor, target) and kind in ('weapon', 'unarmed')
            and not ctx.typed.get('range_ft') and ctx.engine._distance_actor_to_actor(ctx.actor, target) <= int(ctx.action.reach_ft or 5))


def next_end(engine, actor):
    from .effect_durations import token
    return token('end', actor.entity_id, actor.turns_started + 1)


def values(engine, actor):
    n = numbers_of(engine, actor)
    return int(n.get('pb') or 2), int(n.get('key_mod') or 0)


STATE_BENEFITS = {
    'tyrant_surge': 'Advantage on eligible melee attacks and Strength checks',
    'origin_surge': 'Advantage on your next close attack against an enemy or attack with a technique explicitly marked as compatible with Origin Bell Surge, or Strength or Constitution check or save against hostile body control, formation, gravity, fate, spatial displacement or authority suppression. Other technique rolls that contest control or suppression require manual resolution',
    'husk_surge': 'Advantage on checks and saves against the listed Womb effects',
    'golden_bearing': 'Advantage on saves against hostile commands and false authority',
    'tyrant_declaration': 'For one minute, each qualifying hit gains Proficiency Bonus damage; you have Advantage on qualifying Strength or Constitution physical contests and resistance to forced movement, Prone, Grappled or Restrained, and body suppression. Resolve these checks manually; control can still affect you',
    'origin_court': 'You and chosen allies within 30 feet have Advantage on Strength and Constitution checks and saves against hostile body control, formation, gravity, fate, spatial displacement or authority suppression',
    'devour_womb': 'For one minute, each qualifying hit gains Proficiency Bonus damage',
    'mandate_court': 'Chosen allies within 30 feet have Advantage on saves against hostile commands and false authority',
    'furnace_cycle': 'Reduce the first paid compatible technique cost by 1 this turn',
}


def duration_text(expiry):
    return {
        'START_OF_SOURCE_NEXT_TURN': 'until the start of your next turn',
        'END_OF_HOLDER_NEXT_TURN': 'until the end of your next turn',
        'END_OF_CURRENT_TURN': 'until the end of this turn',
        'START_OF_SELF_NEXT_TURN': 'until the start of your next turn',
        'UNTIL_REMOVED': 'until you remove this state',
        'CONCENTRATION_END': 'while you maintain Concentration',
    }.get(str(expiry), 'for the duration stated in the feature')


@hook('compile_block')
def compile_foundation(block, spec, record, numbers):
    if block != BLOCK:
        return None
    return [{**record, 'kind': spec['kind'], 'numbers': {k: int(numbers.get(k) or 0) for k in ('pb', 'key_mod', 'cl')},
             **({'keeps_compiling': True} if spec.get('action') else {})}]


def choose(engine, owner, source, name, label, target=None, *, reaction=False, payment=None):
    from ..typed_reactions import _can_react
    if not owner.active or (reaction and not _can_react(engine, owner)):
        return False
    intent = getattr(engine, '_active_intent', None)
    if intent is None:
        return False
    action = engine.action_catalog.get(getattr(intent, 'source_definition_id', '') or '')
    if action is None:
        candidate = getattr(engine, '_active_candidate', None)
        action = engine.action_catalog.get(getattr(candidate, 'source_definition_id', '') or '')
    prompt_context = None
    if action is not None:
        prompt_context = {'source_definition_id': action.source_definition_id,
                          'action_name': action.display_name, 'action_actor_id': intent.actor_id,
                          'affected_id': target.entity_id if target is not None else owner.entity_id}
    return bool(ask(engine, intent, checkpoint_id(engine, 'FOUNDATION_COMBAT', owner.entity_id, source,
                                                target.entity_id if target else owner.entity_id), owner,
                    CHOICE + 'foundation_combat', ['use'], allow_decline=True, name=name, feature_id=source,
                    target_id=target.entity_id if target else owner.entity_id,
                    labels={'use': label}, preferred=['use'], automatic=True, prompt=f'{name}: {label}?',
                    payment=payment, prompt_context=prompt_context))


def spend(engine, owner, group, leaf, label, target=None, *, reaction=False):
    r = row(engine, owner, group, leaf)
    if r is None or owner.resources.get(pool(group), 0) < 1:
        return False
    source = feature(group, leaf)
    from .choice_costs import Payment
    payment = Payment(pool(group), 1)
    if not choose(engine, owner, source, leaf.replace('_', ' ').title(), label, target, reaction=reaction,
                  payment=payment):
        return False
    payment.pay(engine, owner, source)
    if reaction:
        owner.reaction_available = False
        engine._append_event('REACTION_RESOLVED', source, actor_id=owner.entity_id,
                             target_ids=(target.entity_id if target else owner.entity_id,), payload={'checkpoint': 'FOUNDATION_COMBAT'})
    if group == 'furnace':
        furnace_residue(engine, owner, source)
    return True


def furnace_residue(engine, owner, source):
    """Apply the shared Clean Residue rider after every actual Furnace Heat spend."""
    if row(engine, owner, 'furnace', 'refined_clean_residue_circulation'):
        timed_condition(engine, owner, P + 'clean_residue', source, owner.entity_id, next_end(engine, owner),
                        {'label': 'Clean Residue Circulation: Advantage on your next eligible Constitution save'})


def boost(engine, owner, group):
    leaf = {'tyrant': 'refined_tyrant_momentum', 'origin': 'refined_origin_bell_resonance',
            'devour': 'refined_black_womb_refinement', 'mandate': 'refined_edict_bites_deeper'}.get(group)
    return values(engine, owner)[0] if leaf and row(engine, owner, group, leaf) else 0


@effect('foundation_combat_state')
def state(ctx, eff):
    from ..typed_executor import run_effects, effect_expiry
    group, key = eff['group'], eff['state']
    pb, mod = values(ctx.engine, ctx.actor)
    amount = (int(ctx.numbers.get('cl') or 1) if eff.get('perfected') else int(eff.get('pb_multiplier', 1)) * pb) + mod
    if not eff.get('perfected'):
        amount += boost(ctx.engine, ctx.actor, group) if group != 'devour' else 0
    run_effects(ctx, [{'type': 'temp_hp', 'applies_to': 'self', 'flat': max(0, amount)}])
    expiry = effect_expiry(ctx, eff, ctx.actor, condition=True)
    benefit = STATE_BENEFITS.get(key, 'The Foundation combat benefit remains active')
    timed_condition(ctx.engine, ctx.actor, P + key, ctx.source, ctx.actor.entity_id,
                    expiry, {'group': group, 'label': f'{benefit}; {duration_text(expiry)}'})
    if key == 'husk_surge' and row(ctx.engine, ctx.actor, group, 'refined_imperishable_husk'):
        run_effects(ctx, [{'type': 'resistance', 'applies_to': 'self', 'damage_types': ['necrotic', 'poison'],
                          'duration': 'until_start_of_your_next_turn', 'evidence': 'Imperishable Husk'}])


@hook('after_hit_choice')
def hits(ctx, target, kind):
    from ..typed_executor import run_effects
    from .. import pressure
    engine, owner = ctx.engine, ctx.actor
    if not hostile(owner, target):
        return
    close = body_hit(ctx, target, kind)
    for group, leaf, generated, state_key in (
        ('tyrant', 'tyrant_form_crush', 'tyrant_hit', 'tyrant_declaration'),
        ('origin', 'sacred_dao_strike', 'origin_hit', 'origin_court'),
        ('devour', 'origin_seizing_blow', 'devour_hit', 'devour_womb'),
    ):
        qualifies = close if group == 'tyrant' else close or aligned(ctx.typed, group) if group == 'origin' else aligned(ctx.typed, group)
        if not qualifies:
            continue
        pb, mod = values(engine, owner)
        # The spend sees only a resource present BEFORE this hit. Generation follows it.
        if target.active and spend(engine, owner, group, leaf, f'Spend 1 {GROUPS[group][1].replace("_", " ")} to add {pb + mod + boost(engine, owner, group)} damage', target):
            extra = pb + mod + boost(engine, owner, group)
            latest = next((e for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED'
                           and e.actor_id == owner.entity_id and target.entity_id in e.target_ids), None)
            dtype = str((latest.payload if latest else {}).get('damage_type') or 'force').lower()
            sub = ctx.on_hit_context(target)
            run_effects(sub, [{'type': 'extra_damage', 'applies_to': 'target', 'flat': max(0, extra), 'damage_types': [dtype]}])
            if group == 'devour':
                if target.current_hp * 2 < target.maximum_hp:
                    run_effects(ctx, [{'type': 'temp_hp', 'applies_to': 'self', 'flat': pb}])
            else:
                timed_condition(engine, owner, P + 'answer_' + group, feature(group, leaf), owner.entity_id,
                                'START_OF_SOURCE_NEXT_TURN', {'against': target.entity_id, 'group': group,
                                'label': 'This creature cannot move or bind your body with ordinary effects'})
        if target.active and held(owner, state_key):
            run_effects(ctx.on_hit_context(target), [{'type': 'extra_damage', 'applies_to': 'target', 'flat': pb,
                                                    'damage_types': [str(next((e.payload.get('damage_type') for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == owner.entity_id and target.entity_id in e.target_ids), 'force')).lower()], 'evidence': 'Perfected Foundation hit'}])
        if group != 'devour' or any(e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == owner.entity_id
                    and target.entity_id in e.target_ids and int(e.payload.get('hp_damage') or 0) > 0
                    for e in engine.events[-25:]):
            pressure.generate(engine, owner, generated)


@hook('save_final')
def saves(ctx, subject, ability, named, failed):
    from .. import pressure
    if failed or not hostile(ctx.actor, subject):
        return
    n = names(named)
    if str(ability).upper()[:3] in ('STR', 'CON') and n & BODY:
        pressure.generate(ctx.engine, subject, 'tyrant_save')
    if n & ORIGIN:
        pressure.generate(ctx.engine, subject, 'origin_save')
    if n & DEVOUR:
        pressure.generate(ctx.engine, subject, 'devour_save')
    if n & MANDATE:
        pressure.generate(ctx.engine, subject, 'mandate_save')


@hook('opposed_check_resolved')
def tyrant_checks(ctx, target, result, actor_check, target_check):
    """Generate Tyrant Form Pulse: you succeed on a Strength or
    Constitution check or contest against hostile body pressure.
    A contest qualifies for whichever side owns the row. A DC alone
    proves neither hostility nor body pressure: callers must seal both."""
    from .. import pressure
    engine = ctx.engine
    contested = target_check.get('kind') != 'dc'
    sides = [(ctx.actor, actor_check, bool(result.success), target)]
    if contested:
        sides.append((target, target_check, bool(not result.success and not result.tied), ctx.actor))
    for roller, check, succeeded, opponent in sides:
        if roller is None:
            continue
        if str(check.get('ability') or '').upper()[:3] not in {'STR', 'CON'}:
            continue
        if not succeeded:
            continue
        if not hostile(roller, opponent) or not names(check.get('hazards')) & BODY:
            continue
        pressure.generate(engine, roller, 'tyrant_check')


@hook('escape_roll_resolved')
def tyrant_escape_checks(engine, roller, grips, success, kind, source):
    """Generate only after a successful STR/CON escape from hostile body pressure.

    Read the resolved escape's own recorded ability, never infer Strength
    from a mixed Athletics/Acrobatics check or from an unrelated check made
    while Grappled. The existing escape seam supplies the tested holds.
    Resource generation remains after the roll's spending opportunities.
    """
    from .. import pressure
    if kind != 'check' or not success:
        return
    check = next((e for e in reversed(engine.events)
                  if e.event_type == 'CHECK_ROLLED' and e.actor_id == roller.entity_id
                  and e.source_definition_id == source), None)
    if check is None or str(check.payload.get('ability') or '').upper()[:3] not in {'STR', 'CON'}:
        return
    for condition in grips:
        if str(condition.condition_id).rsplit('.', 1)[-1].lower() not in BODY:
            continue
        holder = engine.state.actors.get(condition.source_actor_id)
        if holder is None or holder.entity_id == roller.entity_id or not hostile(roller, holder):
            continue
        pressure.generate(engine, roller, 'tyrant_check')
        break


@hook('technique_used')
def technique(ctx):
    from .. import pressure
    # Real evented net payment; list prices do not prove payment after discounts.
    events = []
    for e in reversed(ctx.engine.events):
        if e.event_type == 'INTENT_ACCEPTED' and e.actor_id == ctx.actor.entity_id:
            break
        events.append(e)
    paid = sum(int(e.payload.get('amount') or 0) for e in events if e.event_type == 'RESOURCE_SPENT'
               and e.actor_id == ctx.actor.entity_id and e.source_definition_id == ctx.source
               and str(e.payload.get('resource_id') or '') in {'resource:core.qi', 'resource:core.stamina', 'resource:core.resonance'})
    if paid > 0 and aligned(ctx.typed, 'furnace'):
        pressure.generate(ctx.engine, ctx.actor, 'furnace_paid')
    if aligned(ctx.typed, 'devour') and any(e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == ctx.actor.entity_id
            and int(e.payload.get('hp_damage') or 0) > 0 and any(hostile(ctx.actor, ctx.engine.state.actors.get(t)) for t in e.target_ids) for e in events):
        pressure.generate(ctx.engine, ctx.actor, 'devour_hit')
    if aligned(ctx.typed, 'mandate') and any(e.event_type == 'SAVE_ROLLED' and not e.payload.get('success')
                and hostile(ctx.actor, ctx.engine.state.actors.get(e.actor_id)) for e in events):
        pressure.generate(ctx.engine, ctx.actor, 'mandate_failed_save')


@hook('event', nested=True)
def damaged(engine, event_type, kw):
    from .. import pressure
    if event_type != 'DAMAGE_COMMITTED':
        return
    source = engine.state.actors.get(kw.get('actor_id'))
    p = kw.get('payload') or {}
    if int(p.get('hp_damage') or 0) + int(p.get('temporary_hp_absorbed') or 0) <= 0:
        return
    for aid in kw.get('target_ids') or ():
        owner = engine.state.actors.get(aid)
        if not hostile(source, owner):
            continue
        if engine._distance_actor_to_actor(source, owner) <= 10:
            pressure.generate(engine, owner, 'tyrant_damaged')
        from .iron_oath_generation import conscious_for_guarding_iron
        if held(owner, 'protected_subject') and conscious_for_guarding_iron(engine, owner):
            subject = engine.state.actors.get(held(owner, 'protected_subject').data.get('subject'))
            if subject is not None and subject.active and engine._distance_actor_to_actor(owner, subject) <= 5:
                if pressure.generate(engine, owner, 'oath_damaged') and selected(engine, owner, feature('oath', 'oath_skin_mantle')):
                    engine._grant_temp_hp(owner, values(engine, owner)[0], feature('oath', 'oath_skin_mantle'), owner.entity_id)


@hook('final_damage')
def guards(engine, target, amount, damage_type, source_id, source_actor_id, intent):
    from ..typed_reactions import _can_react
    source = engine.state.actors.get(source_actor_id)
    if amount <= 0:
        return None
    total = 0
    for owner in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if not _can_react(engine, owner):
            continue
        pb, mod = values(engine, owner)
        for group, leaf in [('tyrant', 'imperial_shoulder_gate'), ('origin', 'no_beginning_guard'),
                            ('devour', 'devouring_return'), ('furnace', 'furnace_vent_guard'),
                            ('integrity', 'integrity_guard'), ('oath', 'iron_oath_guard')]:
            if group not in {'integrity', 'oath'} and not hostile(source, target):
                continue
            if owner is not target and (group != 'oath' or owner.team_id != target.team_id
                                       or engine._distance_actor_to_actor(owner, target) > 5):
                continue
            if group == 'tyrant' and engine._distance_actor_to_actor(source, owner) > 10:
                continue
            if group == 'origin' and engine._distance_actor_to_actor(source, owner) > 60:
                continue
            if group == 'furnace' and str(damage_type).lower() not in {'fire', 'poison', 'acid'}:
                continue
            if group == 'oath':
                protected = held(owner, 'protected_subject')
                subject = engine.state.actors.get(protected.data.get('subject')) if protected else None
                if subject is None or not subject.active or engine._distance_actor_to_actor(owner, subject) > 5:
                    continue
            cut = (2 if group in {'tyrant', 'origin'} else 1) * pb + mod + boost(engine, owner, group)
            if group == 'devour' and source.current_hp < source.maximum_hp or group == 'furnace' and str(damage_type).lower() == 'poison':
                cut += pb
            if group == 'integrity':
                # Selected-expression support is explicit; unselected expression rows do not stack.
                if held(owner, 'expression') and held(owner, 'expression').data.get('feature') == feature('integrity', 'jade_gold_guard'):
                    cut += pb
                if row_of(engine, owner.entity_id, 'foundation_spend', 'heaven_recognized_vessel') is not None and owner.turn_flags.get('foundation_round_vessel') != engine.state.round_number:
                    cut += pb
            if spend(engine, owner, group, leaf, f'Spend your Reaction and 1 {GROUPS[group][1].replace("_", " ")} to reduce {target.display_name}\'s {damage_type} damage by {max(0, cut)}', target, reaction=True):
                total += max(0, cut)
                if group == 'integrity' and row_of(engine, owner.entity_id, 'foundation_spend', 'heaven_recognized_vessel') is not None:
                    owner.turn_flags['foundation_round_vessel'] = engine.state.round_number
                break
    return {'reduction': min(amount, total)} if total else None


@effect('foundation_protected_subject')
def protect(ctx, eff):
    from ..stealth import sees
    options = [a for a in ctx.engine.state.actors.values() if a is not ctx.actor and a.active
               and a.team_id == ctx.actor.team_id and ctx.engine._distance_actor_to_actor(ctx.actor, a) <= 5]
    if not options:
        return
    pick = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'OATH_SUBJECT', ctx.actor.entity_id), ctx.actor,
               CHOICE + 'foundation_subject', [a.entity_id for a in options], allow_decline=True,
               name='Declare Protected Subject', feature_id=feature('oath', 'declare_protected_subject'),
               labels={a.entity_id: f'Defend {a.display_name}' for a in options}, preferred=[options[0].entity_id],
               automatic_options=[a.entity_id for a in options if sees(ctx.engine, ctx.actor, a)],
               prompt='Name the adjacent ally you are defending. Guarding Iron is gained only while you remain beside that ally.')
    if pick:
        timed_condition(ctx.engine, ctx.actor, P + 'protected_subject', ctx.source, ctx.actor.entity_id, 'UNTIL_REMOVED',
                        {'subject': pick[0], 'label': 'Iron Oath: defending ' + ctx.engine.state.actors[pick[0]].display_name})


@hook('condition_attempt')
def answer_condition(ctx, subject, eff):
    condition = next(iter(names([eff.get('condition')]) & {'prone', 'grappled', 'restrained', 'body_suppression'}), None)
    if condition and blocked(ctx, subject, condition):
        return False
    return None


def blocked(ctx, subject, effect_category):
    from .passive_rows import known_level
    from .source_eligibility import protected_power, printed_text
    a, b = known_level(ctx.engine, ctx.actor), known_level(ctx.engine, subject)
    if a is not None and b is not None and (a - 1) // 5 > (b - 1) // 5:
        return False
    if protected_power(ctx.typed, printed_text(ctx.typed.get('source'))):
        return False
    protections = {
        'tyrant': {'prone', 'grappled', 'restrained', 'forced_movement'},
        'origin': {'prone', 'grappled', 'restrained', 'body_suppression', 'forced_movement', 'teleport'},
    }
    return any(effect_category in protections[group]
               and held(subject, 'answer_' + group)
               and held(subject, 'answer_' + group).data.get('against') == ctx.actor.entity_id
               for group in protections)


@hook('subject_teleport_attempt')
def answer_teleport(ctx, subject, start, destination):
    """Apply Sacred-Dao Strike's source-scoped protection to hostile teleport."""
    if hostile(ctx.actor, subject) and blocked(ctx, subject, 'teleport'):
        return False
    return None


@hook('forced_movement_restriction')
def answer_movement(ctx, subject, eff, maximum):
    return 0 if blocked(ctx, subject, 'forced_movement') else None

# This explicit reviewed roster is intentionally narrow. A new compatible method
# must carry the same sealed foundation_alignment data after its printed review.
ALIGNED = {
    'TAL_DAEMONIC_CULTIVATION_HUNGER_REFINING_BREATH': ['devour'],
    'tianxia.talent.talismans.binding_talisman': ['mandate', 'furnace'],
    'FIRE_TAL_FIREBALL_ART': ['furnace'],
    'TAL_FIRE_FIREBALL': ['furnace'],
}


@hook('compile_action')
def seal_alignment(action, info):
    typed = dict(action.parameters.get('typed') or {})
    source = typed.get('source')
    tags = (info['mechanics'].get(source) or {}).get('foundation_alignment') or ALIGNED.get(source)
    # The policy supplies reviewed expression facts, not sphere-wide affinity.
    if feature('ash', 'remnant_core_reserve') in info['owned_ids']:
        from ..source_expressions import reviewed_expression
        fact = reviewed_expression('remnant_core_reserve', source)
        if fact and source in info['owned_ids']:
            record = info['mechanics'].get(source) or {}
            if record.get('sphere_id') in fact['allowed_spheres']:
                tags = list(dict.fromkeys([*(tags or []), 'ash']))
                typed['foundation_expression_sources'] = {'ash': fact['receipt']}
    if not tags:
        return action
    typed['foundation_alignment'] = list(tags)
    return action.model_copy(update={'parameters': {**action.parameters, 'typed': typed}})


def roll_benefit(engine, owner, kind, ability, named, other=None, typed=None):
    n = roll_names(named)
    a = str(ability or '').upper()[:3]
    if kind == 'attack':
        close = other is not None and hostile(owner, other) and typed is not None and not typed.get('range_ft')
        return ('tyrant_surge' if close and held(owner, 'tyrant_surge') else
                'origin_surge' if (close or aligned(typed or {}, 'origin')) and held(owner, 'origin_surge') else None)
    if kind not in {'save', 'check'}:
        return None
    # Checks share the mode providers' opposing-creature qualification. Saves
    # retain their separately printed eligibility, including non-hostile sources.
    if kind == 'check' and not hostile(owner, other):
        return None
    if held(owner, 'husk_surge') and n & (DEVOUR | {'poisoned', 'frightened', 'grappled', 'restrained', 'body_suppression'}):
        return 'husk_surge'
    if held(owner, 'tyrant_surge') and kind == 'check' and hostile(owner, other) and (
            a == 'STR' or bool(n & BODY)):
        return 'tyrant_surge'
    if held(owner, 'origin_surge') and (
            (a in {'STR', 'CON'} and n & ORIGIN) or n & {'foundation_aligned_dao_roll'}):
        return 'origin_surge'
    # Refined: Clean Residue Circulation (rules_text.json key
    # foundation.jade_furnace_meridian_v0_2B.refined_clean_residue_circulation)
    # grants Advantage on the next CON save against "poison, miasma, furnace
    # backlash, contaminated qi, or technique-residue sickness". Generic
    # 'disease' is not in that printed list, so it is excluded here (the
    # shared RESIDUE set still contains it for the other predicates). Typed
    # damaging saves carry the explicit damage:poison tag, even when failure
    # imposes no Poisoned condition, and the printed text says "against poison".
    if held(owner, 'clean_residue') and kind == 'save' and a == 'CON' and n & ((RESIDUE - {'disease'}) | {'damage:poison'}):
        return 'clean_residue'
    return None


@hook('attack_mode')
def surge_attack(ctx, target):
    return 'ADVANTAGE' if roll_benefit(ctx.engine, ctx.actor, 'attack', None, (), target, ctx.typed) else None


@hook('save_mode')
def foundation_save_modes(engine, subject, ability, dc, source_id, rc):
    source = engine.state.actors.get((rc or {}).get('source_actor_id'))
    n = roll_names((rc or {}).get('named'))
    a = str(ability).upper()[:3]
    modes = []
    if (a == 'WIS' and row(engine, subject, 'ash', 'remnant_core_reserve')
            and (n & {'remnant_possession', 'ruin_terror', 'grief_control',
                      'grief_based_control', 'despair', 'despair_pressure', 'battlefield_horror'}
                 or hostile(source, subject) and 'destruction_as_truth' in n)):
        modes.append('ADVANTAGE')
    if roll_benefit(engine, subject, 'save', a, n, source):
        modes.append('ADVANTAGE')
    if not hostile(source, subject):
        return 'ADVANTAGE' if modes else None
    if (row(engine, subject, 'glass', 'glass_heart_reserve') and a in {'WIS', 'CHA'} and n & {'illusion', 'charmed', 'frightened', 'deception', 'gaze', 'beauty_pressure', 'emotional_manipulation', 'falsehood_pressure'}
            or row(engine, subject, 'devour', 'devouring_womb_frame') and n & DEVOUR
            or row(engine, subject, 'furnace', 'jade_furnace_meridian_frame') and a == 'CON' and n & RESIDUE
            or row(engine, subject, 'mandate', 'golden_mandate_vessel') and n & (MANDATE | {'silenced'})
            or held(subject, 'golden_bearing') and n & MANDATE
            or held(subject, 'devour_womb') and n & (DEVOUR | RESIDUE | {'body_suppression'})
            or row(engine, subject, 'origin', 'refined_body_dao_root') and a == 'CON' and maintenance_disruption(n)
            or row(engine, subject, 'tyrant', 'tyrant_blood_frame') and a in {'STR', 'CON'} and n & BODY
            or row(engine, subject, 'origin', 'sacred_dao_embryo_frame') and a in {'STR', 'CON'} and n & ORIGIN):
        modes.append('ADVANTAGE')
    # Chosen beneficiaries are stored when the court opens; side and live range
    # are checked again for each roll. Enemies can never acquire its boon.
    for owner in engine.state.actors.values():
        for key, hazards, abilities in [('origin_court', ORIGIN, {'STR', 'CON'}), ('mandate_court', MANDATE, None)]:
            c = held(owner, key)
            if c and subject.team_id == owner.team_id and subject.entity_id in c.data.get('allies', []) \
                    and engine._distance_actor_to_actor(owner, subject) <= 30 and n & hazards and (abilities is None or a in abilities):
                modes.append('ADVANTAGE')
    return 'ADVANTAGE' if modes else None


@hook('ability_check_mode')
def foundation_check_modes(engine, owner, ability, skill, other):
    a = str(ability or '').upper()[:3]
    if not hostile(owner, other):
        return None
    if roll_benefit(engine, owner, 'check', a, (), other):
        return 'ADVANTAGE'
    if a in {'STR', 'CON'} and str(skill).lower() == 'athletics' and row(engine, owner, 'tyrant', 'tyrant_blood_frame'):
        return 'ADVANTAGE'
    return None


@hook('ability_check_hazard_mode')
def foundation_hazard_check_modes(engine, actor, ability, skill, against, hazards):
    """Pure check-mode query for owned Foundation rows and hostile named hazards."""
    n, a = names(hazards), str(ability or '').upper()[:3]
    if not n or not hostile(actor, against):
        return None
    if held(actor, 'husk_surge') and n & (DEVOUR | {'poisoned', 'frightened', 'grappled', 'restrained', 'body_suppression'}):
        return 'ADVANTAGE'
    if held(actor, 'origin_surge') and (
            (a in {'STR', 'CON'} and n & ORIGIN) or n & {'foundation_aligned_dao_roll'}):
        return 'ADVANTAGE'
    if a in {'STR', 'CON'} and n & ORIGIN and row(engine, actor, 'origin', 'sacred_dao_embryo_frame'):
        return 'ADVANTAGE'
    refined = row(engine, actor, 'origin', 'refined_body_dao_root')
    if str(skill or '').lower() == 'cultivation' and refined and maintenance_disruption(n):
        return 'ADVANTAGE'
    if a in {'STR', 'CON'} and n & ORIGIN:
        for owner in engine.state.actors.values():
            court = held(owner, 'origin_court')
            if (court and actor.team_id == owner.team_id and actor.entity_id in court.data.get('allies', [])
                    and engine._distance_actor_to_actor(owner, actor) <= 30):
                return 'ADVANTAGE'
    return None


@hook('contest_check_mode')
def foundation_typed_check_modes(ctx, subject, opponent, spec):
    """Recognize canonical Cultivation kinds through the existing spec seam.

    Labeled Cultivation checks already use ability_check_hazard_mode. Kind-only
    specs use that same pure implementation without altering the spec or bonus.
    """
    if spec.get('kind') != 'cultivation' or str(spec.get('skill') or '').lower() == 'cultivation':
        return None
    return foundation_hazard_check_modes(ctx.engine, subject, spec.get('ability'),
                                         'Cultivation', opponent, spec.get('hazards') or ())


def maintenance_disruption(hazards):
    """Body-Dao Root requires both maintenance purpose and eligible disruption."""
    return bool(hazards & {'concentration', 'ongoing_technique'} and hazards & ORIGIN)


@hook('d20_bonus')
def roll_spends(engine, roll, intent):
    rc = engine.d20_context(roll) or {}
    owner = engine.state.actors.get(roll.actor_id)
    if owner is None:
        return None
    source = engine.state.actors.get(rc.get('source_actor_id'))
    target = engine.state.actors.get(rc.get('target_id'))
    action = engine.action_catalog.get(rc.get('source_id'))
    typed = action.parameters.get('typed') or {} if action else {}
    consumed = roll_benefit(engine, owner, rc.get('kind'), rc.get('ability'),
                            [*(rc.get('named') or ()), *(rc.get('hazards') or ())],
                            target if rc.get('kind') == 'attack' or
                            rc.get('kind') == 'check' and source is owner else source, typed)
    if consumed:
        engine._remove_condition(owner, P + consumed, rc.get('source_id') or 'foundation:roll')
    if rc.get('kind') not in {'save', 'check'} or not hostile(source, owner):
        return None
    # A check names its pressure in ``hazards`` (a contest's check spec), a save in ``named``; both are the roll's scope.
    n, a = names([*(rc.get('named') or ()), *(rc.get('hazards') or ())]), str(rc.get('ability') or '').upper()[:3]
    pb, mod = values(engine, owner)
    for group, leaf, qualifies, bonus, reaction in (
        ('tyrant', 'imperial_shoulder_gate', a in {'STR', 'CON'} and bool(n & BODY), 2 * pb + mod, True),
        ('origin', 'no_beginning_guard', a in {'STR', 'CON'} and bool(n & ORIGIN), 2 * pb + mod, True),
        ('furnace', 'furnace_vent_guard', rc.get('kind') == 'save' and a == 'CON' and bool(n & RESIDUE), pb + mod, True),
        ('oath', 'stand_fast_witness', rc.get('kind') == 'save' and bool(n & OATH), pb, False),
    ):
        bonus += boost(engine, owner, group)
        if not qualifies or rc.get('dc') is None or roll.total >= rc['dc'] or roll.total + bonus < rc['dc']:
            continue
        if spend(engine, owner, group, leaf, f'Spend 1 {GROUPS[group][1].replace("_", " ")} to add {bonus} to this roll', reaction=reaction):
            return {'source_id': feature(group, leaf), 'bonus': bonus}
    return None


@effect('foundation_court_recipients')
def court_recipients(ctx, eff):
    from ..stealth import sees
    allies = sorted([a for a in ctx.engine.state.actors.values() if a.active and a.team_id == ctx.actor.team_id
                     and ctx.engine._distance_actor_to_actor(ctx.actor, a) <= 30], key=lambda a: a.entity_id)
    if not allies:
        return
    pick = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'FOUNDATION_COURT', ctx.source), ctx.actor,
               CHOICE + 'foundation_court', [a.entity_id for a in allies], allow_decline=True,
               maximum=len(allies), minimum=0, preferred=[a.entity_id for a in allies],
               automatic_options=[a.entity_id for a in allies if a is ctx.actor or sees(ctx.engine, ctx.actor, a)],
               name=ctx.action.display_name, feature_id=ctx.typed['source'],
               labels={a.entity_id: a.display_name for a in allies},
               prompt=f'{ctx.action.display_name}: choose the allies who gain its saving-throw protection within 30 feet.')
    key = eff['state']
    c = held(ctx.actor, key)
    if c:
        timed_condition(ctx.engine, ctx.actor, P + key, ctx.source, ctx.actor.entity_id, c.expires_on,
                        {**c.data, 'allies': list(pick or [])})

@hook('compile_actions')
def declarations(info):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    owned = set(info['owned_ids'])
    made = []
    if feature('oath', 'declare_protected_subject') in owned:
        source = f"action:typed.{info['short']}.{feature('oath', 'declare_protected_subject')}"
        made.append(ActionDefinition(source_definition_id=source, display_name='Declare Protected Subject', owner_id=info['actor_id'],
            economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF',
            parameters={'setting_only': True, 'typed': {'source': feature('oath', 'declare_protected_subject'),
                'numbers': info['numbers'], 'effects': [{'type': 'foundation_protected_subject', 'applies_to': 'self'}],
                'riders': [], 'duration': {'kind': 'instant'}}, 'expected_damage': 0}))
    ai_expression_default_added = False
    for group, leaves in [('integrity', ['jade_gold_guard', 'heaven_rejecting_marrow', 'orthodox_answering_strike']),
                          ('oath', ['oath_skin_mantle']),
                          ('blood', ['refined_clotted_iron_blood'])]:
        for leaf in leaves:
            fid = feature(group, leaf)
            if fid not in owned:
                continue
            made.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.foundation_expression.{leaf}",
                display_name='Foundation expression: ' + info['mechanics'][fid]['name'], owner_id=info['actor_id'],
                economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF', parameters={
                    'setting_only': True,
                    'setting_description': 'Choose the Refined expression you want to use. You may choose one expression once per fight.',
                    **({'ai_setting_default': {'condition_id': P + 'expression', 'source_definition_id': fid,
                        'data': {'feature': fid, 'label': 'Selected Refined expression'}}}
                       if not ai_expression_default_added else {}),
                    'typed': {'source': fid, 'numbers': info['numbers'], 'effects': [{'type': 'foundation_expression', 'feature': fid}],
                              'riders': [], 'duration': {'kind': 'instant'}}, 'expected_damage': 0}))
            ai_expression_default_added = True
    return made or None


@effect('foundation_expression')
def expression(ctx, eff):
    if held(ctx.actor, 'expression') is None:
        timed_condition(ctx.engine, ctx.actor, P + 'expression', ctx.source, ctx.actor.entity_id, 'UNTIL_REMOVED',
                        {'feature': eff['feature'], 'label': 'Selected Refined expression'})


@hook('candidate_allowed')
def declaration_allowed(engine, actor, candidate, action):
    if action is None:
        return None
    effects = (action.parameters.get('typed') or {}).get('effects') or []
    if any(e.get('type') == 'foundation_expression' for e in effects) and held(actor, 'expression'):
        return False
    if any(e.get('type') == 'foundation_protected_subject' for e in effects) and held(actor, 'protected_subject'):
        return False
    return None


def selected(engine, actor, fid):
    c = held(actor, 'expression')
    return c is not None and c.data.get('feature') == fid


@hook('foundation_expression_selected')
def selected_query(engine, actor, fid):
    if row(engine, actor, 'integrity', 'jade_gold_guard') is not None and fid in {feature('integrity', 'jade_gold_guard'), feature('integrity', 'orthodox_answering_strike'),
               feature('integrity', 'heaven_rejecting_marrow')}:
        return selected(engine, actor, fid)
    if row_of(engine, actor.entity_id, 'foundations4', 'blackblood_guard') is not None \
            and fid == feature('blood', 'refined_clotted_iron_blood'):
        return selected(engine, actor, fid)
    return None


@hook('payment_substitution')
def banked_heat(engine, actor, source_id, total, missing):
    from ..alternative_payments import PaymentAlternative
    action = engine.action_catalog.get(source_id)
    if action is None or not aligned(action.parameters.get('typed') or {}, 'furnace') or not row(engine, actor, 'furnace', 'banked_furnace_expenditure'):
        return None
    cp = next((r for r in total if r in {'resource:core.qi', 'resource:core.stamina', 'resource:core.resonance'} and total[r] > 1), None)
    if cp is None or actor.resources.get(pool('furnace'), 0) < 1:
        return None
    cut = min(total[cp] - 1, 2 if row(engine, actor, 'furnace', 'refined_jade_furnace_core') else 1)
    if any(n > (cut if r == cp else 0) for r, n in missing.items()):
        return None
    return PaymentAlternative(feature('furnace', 'banked_furnace_expenditure'), 'Banked Furnace Expenditure',
                              ((cp, cut),), ((pool('furnace'), 1),))


@hook('payment_substitution')
def ordinary_furnace_payment(engine, actor, source_id, total, missing):
    from ..alternative_payments import PaymentAlternative
    # Keep a normal-payment option alongside the optional Heat conversion.
    if missing or banked_heat(engine, actor, source_id, total, missing) is None:
        return None
    return PaymentAlternative(feature('furnace', 'banked_furnace_expenditure'), 'Keep Furnace Heat; pay normally',
                              tuple(total.items()), tuple(total.items()))


@hook('payment_shortfall_paid')
def heat_paid(engine, actor, source_id, plan, intent):
    if plan.source_id != feature('furnace', 'banked_furnace_expenditure') or not any(r == pool('furnace') and n for r, n in plan.costs):
        return
    furnace_residue(engine, actor, plan.source_id)


@hook('technique_cost_discount')
def cycle_discount(engine, actor, source_id, total):
    action = engine.action_catalog.get(source_id)
    if (action is None or not held(actor, 'furnace_cycle') or engine.state.current_actor_id != actor.entity_id
            or actor.turn_flags.get('foundation_cycle_used') or not aligned(action.parameters.get('typed') or {}, 'furnace')):
        return None
    return {r: 1 for r, n in total.items() if r in {'resource:core.qi', 'resource:core.stamina', 'resource:core.resonance'} and n > 1} or None


@hook('event', nested=True)
def cycle_payment(engine, event_type, kw):
    if event_type != 'RESOURCE_SPENT' or int((kw.get('payload') or {}).get('amount') or 0) < 1:
        return
    actor = engine.state.actors.get(kw.get('actor_id'))
    action = engine.action_catalog.get(kw.get('source_definition_id'))
    if actor and action and held(actor, 'furnace_cycle') and engine.state.current_actor_id == actor.entity_id \
            and str(kw['payload'].get('resource_id') or '') in {'resource:core.qi', 'resource:core.stamina', 'resource:core.resonance'} \
            and aligned(action.parameters.get('typed') or {}, 'furnace'):
        actor.turn_flags['foundation_cycle_used'] = True


@hook('temp_hp_grant_bonus')
def furnace_temp_hp_value(ctx, effect, subject, amount):
    """Increase the original Temporary HP offer before its one interception."""
    owner = ctx.actor
    action = ctx.engine.action_catalog.get(ctx.source)
    active = getattr(ctx.engine, '_active_candidate', None)
    if (action is None or ctx.intent.actor_id != owner.entity_id or active is None
            or active.source_definition_id != ctx.source or not aligned(ctx.typed, 'furnace')
            or amount <= 0 or subject.team_id != owner.team_id
            or not row(ctx.engine, owner, 'furnace', 'jade_furnace_release')
            or owner.resources.get(pool('furnace'), 0) < 1
            or not any(e.event_type == 'RESOURCE_SPENT' and e.actor_id == owner.entity_id
                       and e.source_definition_id == ctx.source
                       and e.payload.get('resource_id') in {'resource:core.qi', 'resource:core.stamina', 'resource:core.resonance'}
                       and int(e.payload.get('amount') or 0) > 0
                       for e in _current_execution_events(ctx.engine, owner.entity_id))):
        return None
    from ..typed_executor import condition_rules
    if any(rule.get('temp_hp_denied') for rule in condition_rules(subject)):
        return None
    from ..stealth import sees
    if subject is not owner and not sees(ctx.engine, owner, subject):
        return None
    bonus = max(0, values(ctx.engine, owner)[0] + values(ctx.engine, owner)[1])
    if bonus <= 0:
        return None
    from .choice_costs import Payment
    payment = Payment(pool('furnace'), 1)
    selected = ask(ctx.engine, ctx.intent,
        checkpoint_id(ctx.engine, 'JADE_TEMP_HP_RELEASE', ctx.source, subject.entity_id),
        owner, CHOICE + 'foundation_release', ['increase'], allow_decline=True,
        name='Jade Furnace Release', feature_id=feature('furnace', 'jade_furnace_release'),
        labels={'increase': f'Add {bonus} Temporary Hit Points for {subject.display_name}; spend 1 Furnace Heat'},
        preferred=['increase'], prompt=f'Increase the Temporary Hit Points from {action.display_name} for {subject.display_name}?',
        payment=payment, target_id=subject.entity_id,
        prompt_context={'source_definition_id': action.source_definition_id, 'action_name': action.display_name,
                        'action_actor_id': owner.entity_id, 'affected_id': subject.entity_id})
    if not selected:
        return None
    payment.pay(ctx.engine, owner, feature('furnace', 'jade_furnace_release'))
    furnace_residue(ctx.engine, owner, feature('furnace', 'jade_furnace_release'))
    return bonus


@hook('healing_roll_bonus')
def furnace_healing_value(ctx, effect):
    """Offer Release while the original heal is being rolled, so penalties/hooks run once."""
    owner = ctx.actor
    action = ctx.engine.action_catalog.get(ctx.source)
    active = getattr(ctx.engine, '_active_candidate', None)
    if (action is None or ctx.intent.actor_id != owner.entity_id or active is None
            or active.source_definition_id != ctx.source or not aligned(ctx.typed, 'furnace')
            or not row(ctx.engine, owner, 'furnace', 'jade_furnace_release')
            or owner.resources.get(pool('furnace'), 0) < 1):
        return None
    # Payment must belong to this accepted execution; an earlier use of a recurring
    # source cannot authorize a later free or delayed damage/healing event.
    events = []
    for event in reversed(ctx.engine.events):
        if event.event_type == 'INTENT_ACCEPTED' and event.actor_id == owner.entity_id:
            break
        events.append(event)
    if not any(e.event_type == 'RESOURCE_SPENT' and e.actor_id == owner.entity_id
               and e.source_definition_id == ctx.source
               and e.payload.get('resource_id') in {'resource:core.qi', 'resource:core.stamina', 'resource:core.resonance'}
               and int(e.payload.get('amount') or 0) > 0 for e in events):
        return None
    from ..typed_executor import effect_subjects
    subjects = [s for s in effect_subjects(ctx, effect, harmful=False)
                if s.active and s.team_id == owner.team_id]
    if len(subjects) != 1:
        return None
    subject = subjects[0]
    if subject is not owner:
        from .needle import ai_controlled
        if ai_controlled(ctx.engine, owner):
            from ..stealth import sees
            if not sees(ctx.engine, owner, subject):
                return None
    bonus = max(0, sum(values(ctx.engine, owner)))
    if bonus <= 0:
        return None
    from .choice_costs import Payment
    payment = Payment(pool('furnace'), 1)
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'JADE_HEALING_RELEASE', ctx.source, subject.entity_id),
        owner, CHOICE + 'foundation_release', ['increase'], allow_decline=True,
        name='Jade Furnace Release', feature_id=feature('furnace', 'jade_furnace_release'),
        labels={'increase': f'Increase healing for {subject.display_name} by {bonus}; spend 1 Furnace Heat'},
        preferred=['increase'], prompt=f'Increase the healing from {ctx.action.display_name} for {subject.display_name}?', payment=payment,
        target_id=subject.entity_id,
        prompt_context={'source_definition_id': ctx.action.source_definition_id, 'action_name': ctx.action.display_name,
                        'action_actor_id': owner.entity_id, 'affected_id': subject.entity_id})
    if not selected:
        return None
    payment.pay(ctx.engine, owner, feature('furnace', 'jade_furnace_release'))
    furnace_residue(ctx.engine, owner, feature('furnace', 'jade_furnace_release'))
    return bonus


@hook('damage_value_adjustment')
def furnace_damage_value(engine, target, amount, damage_type, source_id, source_actor_id, intent):
    """Increase one selected damage value before shared defenses resolve it."""
    owner = engine.state.actors.get(source_actor_id)
    action = engine.action_catalog.get(source_id)
    active = getattr(engine, '_active_candidate', None)
    if (owner is None or action is None or intent is None or intent.actor_id != source_actor_id
            or active is None or active.source_definition_id != source_id or not hostile(owner, target)
            or not aligned(action.parameters.get('typed') or {}, 'furnace')
            or not row(engine, owner, 'furnace', 'jade_furnace_release')
            or owner.resources.get(pool('furnace'), 0) < 1
            or not any(e.event_type == 'RESOURCE_SPENT' and e.actor_id == owner.entity_id
                       and e.source_definition_id == source_id
                       and e.payload.get('resource_id') in {'resource:core.qi', 'resource:core.stamina', 'resource:core.resonance'}
                       and int(e.payload.get('amount') or 0) > 0
                       for e in _current_execution_events(engine, owner.entity_id))):
        return None
    from ..stealth import sees
    if not sees(engine, owner, target):
        return None
    bonus = max(0, values(engine, owner)[0] + values(engine, owner)[1])
    if bonus == 0:
        return None
    key = checkpoint_id(engine, 'JADE_DAMAGE_RELEASE', source_id, target.entity_id, len(engine.events))
    from .choice_costs import Payment
    payment = Payment(pool('furnace'), 1)
    selected = ask(engine, intent, key, owner, CHOICE + 'foundation_release', ['increase'], allow_decline=True,
                   name='Jade Furnace Release', feature_id=feature('furnace', 'jade_furnace_release'),
                   labels={'increase': f'Add {bonus} to this damage value; spend 1 Furnace Heat'},
                   preferred=['increase'], prompt=f'Increase {action.display_name} damage to {target.display_name} before resistance and other damage defenses?',
                   payment=payment, target_id=target.entity_id,
                   prompt_context={'source_definition_id': source_id, 'action_name': action.display_name,
                                   'action_actor_id': owner.entity_id, 'affected_id': target.entity_id})
    if not selected:
        return None
    payment.pay(engine, owner, feature('furnace', 'jade_furnace_release'))
    furnace_residue(engine, owner, feature('furnace', 'jade_furnace_release'))
    return bonus


def _current_execution_events(engine, actor_id):
    """Return only events since this actor's current accepted intent."""
    current = []
    for event in reversed(engine.events):
        if event.event_type == 'INTENT_ACCEPTED' and event.actor_id == actor_id:
            break
        current.append(event)
    return current


@hook('attack_magical')
def tyrant_body_magical(engine, source_actor_id, typed):
    owner = engine.state.actors.get(source_actor_id)
    if owner is None or not row(engine, owner, 'tyrant', 'tyrant_blood_frame') or typed.get('range_ft'):
        return None
    return bool(typed.get('weapon') or any(e.get('attack_kind') == 'unarmed' for e in typed.get('effects') or []))


@hook('escape_check_mode')
def foundation_escape_mode(engine, escaper, grips, ability, skill):
    holds = list(grips.values() if isinstance(grips, dict) else grips or [])
    holds = [g for g in holds if hostile(escaper, engine.state.actors.get(getattr(g, 'source_actor_id', None)))]
    if not holds:
        return None
    # Evaluate each hostile grip separately: a friendly hold must not supply
    # hazards to an unrelated hostile source. Court recipients use this too.
    if any(foundation_hazard_check_modes(
            engine, escaper, ability, skill, engine.state.actors.get(g.source_actor_id),
            [str(g.condition_id)]) == 'ADVANTAGE' for g in holds):
        return 'ADVANTAGE'
    # Tyrant Blood Surge: the escape is body-bound (it opposes a
    # Grappled, Restrained, Prone, forced-movement or body-suppression
    # hold), whatever the escape's ability; the spend is consumed when
    # the check is rolled (roll_spends), so a non-body escape keeps it.
    if any(names([str(getattr(g, 'condition_id', ''))]) & BODY and
           roll_benefit(engine, escaper, 'check', ability,
                       [str(getattr(g, 'condition_id', ''))],
                       engine.state.actors.get(getattr(g, 'source_actor_id', None))) == 'tyrant_surge'
           for g in holds):
        return 'ADVANTAGE'
    # Printed Frame benefits cover only Strength/Constitution body opposition.
    if ability not in {'STR', 'CON'}:
        return None
    if any(names([str(g.condition_id)]) & BODY for g in holds) and row(engine, escaper, 'tyrant', 'tyrant_blood_frame'):
        return 'ADVANTAGE'
    return None


@hook('escape_check_choice_required')
def foundation_escape_skill_choice(ctx, effect, dc, grips, hazards):
    """Own physical Foundation benefits need the actual chosen escape ability."""
    if not set(hazards) & BODY or not any(
            hostile(ctx.actor, ctx.engine.state.actors.get(g.source_actor_id)) for g in grips):
        return None
    for group, leaf, name in (
            ('tyrant', 'tyrant_blood_frame', 'Tyrant-Blood Frame'),
            ('origin', 'sacred_dao_embryo_frame', 'Sacred Dao Embryo Frame')):
        if row(ctx.engine, ctx.actor, group, leaf):
            return {'name': name, 'feature_id': feature(group, leaf)}
    return None


@effect('foundation_refraction_state')
def refraction_state(ctx, eff):
    from ..typed_executor import effect_expiry
    timed_condition(ctx.engine, ctx.actor, P + 'glass_refraction', ctx.source, ctx.actor.entity_id,
                    effect_expiry(ctx, eff, ctx.actor, condition=True),
                    {'label': 'Glass Heart Refraction: transparent clarity for 1 minute'})
