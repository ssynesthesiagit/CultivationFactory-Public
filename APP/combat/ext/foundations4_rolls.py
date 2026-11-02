"""Post-roll Foundation bonuses; scope comes from explicit roll metadata.

Reuse the shared d20 transport with the original natural face and a signed
bonus, rather than rolling again. An unknown hazard never qualifies. Sword
Bones, Mud-Lotus Humble Medicine Witness, and Severing Clarity use the same paid
conversion provider as their Cut, Guard, and Lotus-Root values. Mud-Lotus
Guard's +PB is not wired here (its reduction is a typed damage_modifier).
A selected Refined expression of Blackblood Refusal (Venom-Dark Marrow) adds its
own PB to the same roll through foundations4.conversion_evolution_pb, with no
second roll, payment or transaction.
"""
from .d20_rewrite import Rule, register, pool_id
from ..typed_reactions import _holds
from . import hook

SCOPES = {
    'severing_clarity': frozenset({'disarmed', 'weapon_binding', 'restrained', 'prone'}),
    'blackblood_refusal': frozenset({'blood_loss', 'poisoned', 'damage:poison', 'disease', 'corruption',
                                   'forced_body_alteration', 'internal_body_disruption'}),
    'reed_recovery': frozenset({'falling', 'grappled', 'restrained', 'prone', 'forced_movement', 'difficult_terrain'}),
    # Only tags with a test here: the Medicine/Survival checks and the poisoned/disease saves. Other printed or
    # listed tags (herbalism, Water, Life, Flowers, Alchemy, Protection, Cultivation, Rot, Polluted water,
    # Sickness/exhaustion, poison, Disease-/Poison-treatment) have no authority save or test yet, so they stay out.
    'humble_medicine_witness': frozenset({'medicine', 'survival', 'poisoned', 'disease'}),
}
POOLS = {'severing_clarity': 'severance_edge', 'blackblood_refusal': 'blackblood_pressure', 'reed_recovery': 'reed_flex',
         'humble_medicine_witness': 'lotus_dew'}
# Printed pool names for player text (the resource ids are lower-case slugs).
POOL_LABELS = {'severing_clarity': 'Severance Edge', 'blackblood_refusal': 'Blackblood Pressure', 'reed_recovery': 'Reed Flex',
               'humble_medicine_witness': 'Lotus Dew'}
NAMES = {'severing_clarity': 'Severing Clarity', 'blackblood_refusal': 'Blackblood Refusal', 'reed_recovery': 'Reed Recovery',
         'humble_medicine_witness': 'Humble Medicine Witness'}


def _tag(text):
    """One vocabulary for printed trigger words: 'category:Disease-treatment' -> 'disease_treatment'."""
    return str(text).removeprefix('category:').strip().lower().replace('-', '_').replace(' ', '_')


def _tags(kind, rc):
    """The tags one roll is matched on. Only the Witness normalises: it matches a native skill and typed category names.

    Severing Clarity, Blackblood Refusal and Reed Recovery keep main's exact matching on the raw names. Typed
    'category:<tag>' saves therefore do not reach them (as on main); widening that is a separate rules change.
    """
    if kind != 'humble_medicine_witness':
        return set(rc.named)
    # A save matches its typed save_categories/named tags; a check matches its native skill name.
    return {_tag(tag) for tag in rc.named} | ({_tag(rc.skill)} if getattr(rc, 'skill', None) else set())


# A Refined expression that adds its own PB to one conversion's roll, by the
# conversion's feature leaf. The shared helper answers only an explicit True.
REFINED_EXPRESSIONS = {
    'blackblood_refusal': 'foundation.true_blackblood_physique_v0_2C.refined_venom_dark_marrow',
}


def refined_pb(engine, actor, feature_id, pb):
    expression = next((e for leaf, e in REFINED_EXPRESSIONS.items() if feature_id.endswith('.' + leaf)), None)
    if expression is None:
        return 0
    from .foundations4 import conversion_evolution_pb
    return conversion_evolution_pb(engine, actor, {'refined_expression': expression, 'pb': pb})


def guard(kind):
    """Scope test for one Foundation roll rider (see _tags for how each kind reads the roll's names)."""
    def applicable(engine, holder, rc):
        resource = pool_id(holder.actor, POOLS[kind])
        scope = bool(_tags(kind, rc) & SCOPES[kind]) or (kind == 'blackblood_refusal' and rc.kind == 'save' and rc.ability == 'CON')
        return scope and resource is not None and _holds(engine, holder.actor, resource, 1)
    return applicable


def worthwhile(engine, holder, rc):
    return rc.dc is not None and rc.total < rc.dc <= rc.total + roll_bonus(engine, holder, rc)


# The paid conversion each roll-adding feature takes from the shared provider (Refined rows name the same ids).
ROLL_CONVERSIONS = tuple(NAMES)


def _roll_conversion(holder):
    return next((c for c in ROLL_CONVERSIONS if holder.feature_id.endswith('.' + c)), None)


def roll_bonus(engine, holder, rc):
    from .foundation_conversion_bonus import conversion_bonus
    conversion = _roll_conversion(holder)
    extra = conversion_bonus(engine, holder.actor, conversion, receipt_id=rc.roll.roll_id) if conversion else 0
    return int(holder.numbers['pb']) + extra + refined_pb(engine, holder.actor, holder.feature_id, int(holder.numbers['pb']))


def settle_roll_bonus(engine, holder, rc):
    conversion = _roll_conversion(holder)
    if conversion:
        from .foundation_conversion_bonus import settle_conversion_bonus
        settle_conversion_bonus(engine, holder.actor, conversion, rc.roll.roll_id, holder.feature_id)


@hook('decision_text')
def clarity_prompt(engine, context, printed_rules):
    from .foundation_conversion_bonus import conversion_bonus, conversion_consent_note
    source = str(context.get('reaction_source_id') or '').removeprefix('reaction:typed.')
    if source != 'foundation.sword_bones_v0_2B.severing_clarity':
        return None
    actor = engine.state.actors.get(context.get('reactor_id'))
    if actor is None:
        return None
    extra = conversion_bonus(engine, actor, 'severing_clarity')
    if not extra:
        return None
    row = next((r for r in engine.typed_passive_rows.get(actor.entity_id, []) if r.get('feature_id') == source), None)
    if row is None:
        return None
    trigger = context.get('choice_trigger') or {}
    action = trigger.get('action_name') or 'this action'
    total = int(row['pb']) + extra
    return {'summary': f"{actor.display_name} rolled for {action}. Use Severing Clarity to add {total} to the same roll?",
            'table_note': f"Spend 1 pre-existing Severance Edge to add {total}, including your evolution bonus. No Reaction or new roll. Declining spends nothing." +
                conversion_consent_note(engine, actor, 'severing_clarity')}


for kind, name in NAMES.items():
    register(Rule('foundations4_' + kind, name, rolls=('save', 'check'), who='self', when='any',
        op='choose', costs=(((POOLS[kind], 1),),), guard=guard(kind), ai=worthwhile,
        choose=lambda engine, holder, rc: rc.natural,
        bonus=roll_bonus, on_use=settle_roll_bonus,
        say=lambda engine, holder, rc, new, name=name, kind=kind: f"{holder.actor.display_name} uses {name}, spending 1 {POOL_LABELS[kind]} to add {roll_bonus(engine, holder, rc)} to the same roll."))


@hook('decision_text')
def refined_prompt(engine, context, printed_rules):
    """Name a selected Refined expression's extra PB on the conversion's own prompt.

    Read-only presentation: the accepted spend already carries the whole bonus.
    """
    from .d20_rewrite import BLOCK
    source = str(context.get('reaction_source_id') or '').removeprefix('reaction:typed.')
    actor = engine.state.actors.get(context.get('reactor_id'))
    if actor is None:
        return None
    row = next((r for r in engine.typed_passive_rows.get(actor.entity_id, [])
                if r.get('block') == BLOCK and r.get('feature_id') == source), None)
    if row is None:
        return None
    # The compiled row's kind carries the rule prefix; the conversion key does not.
    kind = str(row.get('kind') or '').removeprefix('foundations4_')
    if kind not in REFINED_EXPRESSIONS:
        return None
    base = int(row['pb'])
    extra = refined_pb(engine, actor, source, base)
    if not extra:
        return None
    expression = next((c for c in actor.conditions.values()
                       if c.condition_id == 'condition:typed.foundation_combat.expression'), None)
    named = str((expression.data or {}).get('name') or 'the selected Refined expression')
    return {'table_note': f"{named} is selected: {NAMES[kind]} adds {extra} more to this same roll "
                          f"({base} base + {extra} expression), for the same 1 {POOLS[kind].replace('_', ' ')}."}
