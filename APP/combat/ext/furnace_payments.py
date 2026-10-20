"""Printed payment eligibility shared by combat Overdraw/Core and Journey Engine.

These pure functions classify only the Qi expenditure: other prices stay intact.
Consumers retain their own ownership, source-state clocks, consent and receipts.
"""
from ..alternative_payments import PaymentAlternative, resource_payment, totals

QI = 'resource:core.qi'
DEVIL = 'resource:named.devil_qi'


def overdraw_reduction(profile, total, pb, *, emperor=False):
    """None means ineligible; zero still permits paying Corruption at a cost floor."""
    if total < 1 or not profile.get('ordinary_qi') or profile.get('cannot_further_reduce') or profile.get('another_creature'):
        return None
    protected = ('legendary', 'artifact', 'secret', 'secret_law', 'immortal', 'immortal_art',
                 'permanent', 'indefinite', 'strategic_travel', 'world_scale', 'expensive_materials', 'sacrifice')
    floor = int(any(profile.get(k) for k in protected) and not profile.get('explicit_zero'))
    return min(total - floor, pb * (2 if emperor else 1))


def core_cost_allowed(profile):
    """The same printed Core exclusions apply to every native payment surface."""
    if not profile.get('ordinary_qi') or any(profile.get(k) for k in ('sacrifice', 'another_creature')):
        return False
    if any(profile.get(k) for k in ('artifact_charges', 'secret', 'secret_law', 'immortal', 'immortal_art')):
        return bool(profile.get('accepts_devil_qi'))
    return True


def payment_amounts(costs, plan=None):
    """Shared settlement arithmetic; no resource grants or refunds during quoting."""
    return totals(resource_payment(costs, plan) if plan is not None else costs)
