"""Active Defense windows belong to one roll in a multiattack, not later swings."""
from types import SimpleNamespace as NS

from combat.ext.redirect_reactions import _missed_roll
from combat.ext.shield_riders import caused_miss, defender_of

AD = "SHIELD_BASE_ACTIVE_DEFENSE"


class Log:
    def __init__(self):
        self.events = []

    def add(self, event_type, actor=None, targets=(), source="", payload=None):
        n = len(self.events) + 1
        self.events.append(NS(sequence=n, event_type=event_type, actor_id=actor,
                              target_ids=tuple(targets), source_definition_id=source,
                              payload=payload or {}))
        return self.events[-1]


def swing(log, *, total=14, natural=10, provisional=True):
    return log.add("ATTACK_ROLLED", "A", ("T",), payload={
        "natural_result": natural, "modified_total": total, "target_ac": 13,
        "provisional_hit": provisional, "roll_id": f"roll-{len(log.events) + 1}"})


def window(log):
    return log.add("REACTION_WINDOW_OPENED", "T", ("A",), AD)


def engine(log, receipt_ac=15):
    return NS(events=log.events, state=NS(actors={}),
              _typed_attack_outcome={"actor_id": "A", "recorded": len(log.events),
                                     "armor_class": receipt_ac, "source_id": AD})


def actors():
    return NS(entity_id="A", conditions={}), NS(entity_id="T", conditions={})


def test_first_swing_active_defense_does_not_defend_second_multiattack():
    log = Log()
    swing(log)
    window(log)  # defender answers only the first roll
    second = swing(log, natural=1, provisional=False)
    attacker, target = actors()
    e = engine(log)

    roll, defended = _missed_roll(e, attacker, target)
    assert roll.sequence == second.sequence
    assert defended is False
    assert defender_of(e, attacker, target) is None
    assert caused_miss(e, attacker, target) is False


def test_active_defense_on_second_multiattack_remains_bound_and_effective():
    log = Log()
    swing(log)
    window(log)
    second = swing(log)
    window(log)  # this answer belongs to the second roll
    attacker, target = actors()
    e = engine(log)

    roll, defended = _missed_roll(e, attacker, target)
    assert roll.sequence == second.sequence
    assert defended is True
    assert defender_of(e, attacker, target) is target
    assert caused_miss(e, attacker, target) is True
