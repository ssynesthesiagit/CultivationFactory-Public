"""caused_miss / defender_of read a late Active Defense window from the whole fight, not a fixed tail of the log.

Synthetic event logs only (no fixtures, no private data). The bonus comes from the recorded AC (attack outcome receipt),
not the old hard-coded +2.
"""
from types import SimpleNamespace as NS

from combat.ext.redirect_reactions import _missed_roll
from combat.ext.shield_riders import caused_miss, defender_of

AD = "SHIELD_BASE_ACTIVE_DEFENSE"


class Log:
    def __init__(self):
        self.events = []

    def add(self, event_type, actor=None, targets=(), source="", payload=None):
        n = len(self.events) + 1
        self.events.append(NS(sequence=n, event_type=event_type, actor_id=actor, target_ids=tuple(targets),
                              source_definition_id=source, payload=payload or {}))
        return n

    def filler(self, count):
        for _ in range(count):
            self.add("FILLER")


def roll(log, *, natural, target_ac, total, provisional):
    return log.add("ATTACK_ROLLED", "A", ("T",), payload={
        "natural_result": natural, "modified_total": total, "target_ac": target_ac, "provisional_hit": provisional})


def engine_for(log, receipt_ac=None):
    engine = NS(events=log.events, state=NS(actors={}), _typed_attack_outcome=None)
    if receipt_ac is not None:
        # attempt receipt published inside the attack (recorded at the present length, as record_attack_outcome does)
        engine._typed_attack_outcome = {"actor_id": "A", "recorded": len(log.events),
                                        "armor_class": receipt_ac, "source_id": AD}
    return engine


def attacker_target():
    return NS(entity_id="A", conditions={}), NS(entity_id="T", conditions={})


def test_window_far_back_in_a_long_fight_still_counts_as_a_late_answer():
    log = Log()
    roll(log, natural=10, target_ac=13, total=16, provisional=True)  # hit before Active Defense
    log.add("REACTION_WINDOW_OPENED", "T", ("A",), AD)
    log.filler(120)  # far more than any fixed tail would keep
    attacker, target = attacker_target()
    # Active Defense raised AC to 15, so 16 still hits: it did not cause a miss.
    assert caused_miss(engine_for(log, receipt_ac=15), attacker, target) is False


def test_far_back_window_is_found_by_defender_of():
    log = Log()
    log.add("ATTACK_ROLLED", "A", ("T",), payload={"natural_result": 10})
    log.add("REACTION_WINDOW_OPENED", "T", ("A",), AD)
    log.filler(120)
    attacker, target = attacker_target()
    assert defender_of(engine_for(log), attacker, target) is target


def test_late_bonus_comes_from_recorded_ac_not_a_constant():
    log = Log()
    roll(log, natural=10, target_ac=13, total=15, provisional=False)
    log.add("REACTION_WINDOW_OPENED", "T", ("A",), AD)
    attacker, target = attacker_target()
    # Recorded AC 16 is a +3 bonus: 15 was turned aside by it.
    assert caused_miss(engine_for(log, receipt_ac=16), attacker, target) is True


def test_late_window_without_a_raised_ac_is_not_a_caused_miss():
    log = Log()
    roll(log, natural=10, target_ac=13, total=14, provisional=True)  # a hit that the declined window never changed
    log.add("REACTION_WINDOW_OPENED", "T", ("A",), AD)
    attacker, target = attacker_target()
    assert caused_miss(engine_for(log), attacker, target) is False
