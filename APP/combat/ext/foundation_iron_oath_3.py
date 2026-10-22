"""Stand-Fast Witness player choice, used by the existing foundation_combat provider.

The source permits adding PB after a qualifying roll; it does not require that
PB change failure to success. Keep that decision with a manual player. The
original provider still owns qualification, consent, payment and the bonus;
automatic seats retain its outcome-aware policy. No scene facts are inferred.
"""
from .needle import answerable


def manual_roll_offer(engine, owner, group, leaf):
    """Permit the owned Stand-Fast option even when it cannot change success."""
    from .foundation_combat import row

    return (group == 'oath' and leaf == 'stand_fast_witness'
            and row(engine, owner, group, leaf) is not None
            and answerable(engine, owner))
