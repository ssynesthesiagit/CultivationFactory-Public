"""One attack packet with several damage types.

The confirmed_hit seam may append {amount: int, damage_type: str} components
onto an attack spec. Same-type amounts combine before defenses. Percentage
protections resolve by type, then the aggregate enters one reaction/HP commit.
The existing single-type path is unchanged. Gather and Return and Rebounding
Assault supply components; the helper is independent of their identities.
"""
from collections import defaultdict


def defend_components(engine, target, components, source_id, source_actor_id):
    from . import typed_reactions
    totals = defaultdict(int)
    for part in components:
        totals[str(part['damage_type']).upper()] += int(part['amount'])
    budget = {}
    settlements = []
    remaining={kind:typed_reactions.defend(engine,target,amount,kind,source_id,source_actor_id,
                native=target.entity_id not in getattr(engine,'typed_actor_ids',set()),component_budget=budget,component_settlement=settlements)
                for kind,amount in totals.items()}
    # Type-specific flat protection cannot reduce another surviving portion.
    for entry in budget.values():
        available=entry['amount']
        for kind in entry['types']:
            used=min(available,remaining.get(kind,0))
            remaining[kind]-=used
            available-=used
    for settle in settlements:settle()
    from .pending_damage import defended_components
    defended_components(engine,remaining)
    return sum(remaining.values())
