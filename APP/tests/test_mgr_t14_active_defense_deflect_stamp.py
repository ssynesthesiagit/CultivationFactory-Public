"""Deflect's per-attack use stamp reads the attack's own roll, however many events ago it was.

Synthetic event log only (no fixtures, no private data). Before the fix the stamp was looked up in the last 80 events;
two Deflects against two attacks whose rolls were both more than 80 events back both got stamp 0, so the second
Deflect was refused as "already used" for the first attack.
"""
from types import SimpleNamespace as NS

from combat.ext.shield_riders import _deflect_ok


class Log:
    def __init__(self):
        self.events = []

    def add(self, event_type, actor=None):
        n = len(self.events) + 1
        self.events.append(NS(sequence=n, event_type=event_type, actor_id=actor, target_ids=(), source_definition_id="",
                              payload={}))
        return n

    def filler(self, count):
        for _ in range(count):
            self.add("FILLER")


def test_second_deflect_against_a_distant_attack_is_not_refused_as_already_used():
    log = Log()
    engine = NS(events=log.events, state=NS(actors={}))
    defender = NS(entity_id="D", resources={}, conditions={})
    first = NS(entity_id="A")
    second = NS(entity_id="B")

    log.add("ATTACK_ROLLED", "A")
    log.filler(90)  # more than the old 80-event tail
    assert _deflect_ok(engine, defender, first, "sacrificial") is True

    log.add("ATTACK_ROLLED", "B")
    log.filler(90)
    assert _deflect_ok(engine, defender, second, "sacrificial") is True


def test_same_attack_still_cannot_use_the_same_deflect_twice_when_the_roll_is_far_back():
    log = Log()
    engine = NS(events=log.events, state=NS(actors={}))
    defender = NS(entity_id="D", resources={}, conditions={})
    attacker = NS(entity_id="A")

    log.add("ATTACK_ROLLED", "A")
    log.filler(120)
    assert _deflect_ok(engine, defender, attacker, "sacrificial") is True
    assert _deflect_ok(engine, defender, attacker, "sacrificial") is False
