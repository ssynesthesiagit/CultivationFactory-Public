"""Base post-roll Foundation bonuses; scope comes from explicit roll metadata.

Reuse the shared d20 transport with the original natural face and a signed
bonus, rather than rolling again. An unknown hazard never qualifies. These
rules make no claims about selected Refined/Perfected improvements.
"""
from .d20_rewrite import Rule, register, pool_id
from ..typed_reactions import _holds

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
    return rc.dc is not None and rc.total < rc.dc <= rc.total + int(holder.numbers['pb'])


for kind, name in NAMES.items():
    register(Rule('foundations4_' + kind, name, rolls=('save', 'check'), who='self', when='any',
        op='choose', costs=(((POOLS[kind], 1),),), guard=guard(kind), ai=worthwhile,
        choose=lambda engine, holder, rc: rc.natural,
        bonus=lambda engine, holder, rc: int(holder.numbers['pb']),
        say=lambda engine, holder, rc, new, name=name, kind=kind: f"{holder.actor.display_name} uses {name}, spending 1 {POOLS[kind].replace('_', ' ')} to add {holder.numbers['pb']} to the roll."))
