"""Post-roll Foundation bonuses; scope comes from explicit roll metadata.

Reuse the shared d20 transport with the original natural face and a signed
bonus, rather than rolling again. An unknown hazard never qualifies. Sword
Bones uses the same paid conversion provider as its Cut and Guard values.
"""
from .d20_rewrite import Rule, register, pool_id
from ..typed_reactions import _holds
from . import hook

SCOPES = {
    'severing_clarity': frozenset({'disarmed', 'weapon_binding', 'restrained', 'prone'}),
    'blackblood_refusal': frozenset({'blood_loss', 'poisoned', 'damage:poison', 'disease', 'corruption',
                                   'forced_body_alteration', 'internal_body_disruption'}),
    'reed_recovery': frozenset({'falling', 'grappled', 'restrained', 'prone', 'forced_movement', 'difficult_terrain'}),
}
POOLS = {'severing_clarity': 'severance_edge', 'blackblood_refusal': 'blackblood_pressure', 'reed_recovery': 'reed_flex'}
NAMES = {'severing_clarity': 'Severing Clarity', 'blackblood_refusal': 'Blackblood Refusal', 'reed_recovery': 'Reed Recovery'}


def guard(kind):
    def applicable(engine, holder, rc):
        resource = pool_id(holder.actor, POOLS[kind])
        scope = bool(set(rc.named) & SCOPES[kind]) or (kind == 'blackblood_refusal' and rc.kind == 'save' and rc.ability == 'CON')
        return scope and resource is not None and _holds(engine, holder.actor, resource, 1)
    return applicable


def worthwhile(engine, holder, rc):
    return rc.dc is not None and rc.total < rc.dc <= rc.total + roll_bonus(engine, holder, rc)


def roll_bonus(engine, holder, rc):
    from .foundation_conversion_bonus import conversion_bonus
    extra = (conversion_bonus(engine, holder.actor, 'severing_clarity', receipt_id=rc.roll.roll_id)
             if holder.feature_id.endswith('.severing_clarity') else 0)
    return int(holder.numbers['pb']) + extra


def settle_roll_bonus(engine, holder, rc):
    if holder.feature_id.endswith('.severing_clarity'):
        from .foundation_conversion_bonus import settle_conversion_bonus
        settle_conversion_bonus(engine, holder.actor, 'severing_clarity', rc.roll.roll_id, holder.feature_id)


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
        say=lambda engine, holder, rc, new, name=name, kind=kind: f"{holder.actor.display_name} uses {name}, spending 1 {POOLS[kind].replace('_', ' ')} to add {roll_bonus(engine, holder, rc)} to the same roll."))
