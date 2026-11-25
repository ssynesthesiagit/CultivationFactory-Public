"""CONCREALM1 repro: the Bible's Realm-scaled Concentration limit is the shipped default (owner ruling 2026-11-25).

Synthetic Factory characters are compiled through the normal path with no mode override, so these assertions read
the capacity the shipped combat/rules/concentration.json seals into each new bundle.
"""

from combat import concentration
from combat.gate2_runtime_content import AN
from tests.test_multi_concentration import _engine


def _held(actor) -> str:
    return f"held={concentration.sources(actor)}"


def test_cl1_holds_one_and_the_older_one_ends():
    engine, me = _engine(1)
    engine._start_concentration(me, "action:a")
    engine._start_concentration(me, "action:b")
    assert concentration.sources(me) == ["action:b"], _held(me)


def test_cl5_holds_two_and_a_third_start_ends_the_oldest():
    engine, me = _engine(5)
    for source in ("action:a", "action:b", "action:c"):
        engine._start_concentration(me, source)
    assert concentration.sources(me) == ["action:b", "action:c"], _held(me)


def test_cl20_holds_five():
    engine, me = _engine(20)
    for i in range(6):
        engine._start_concentration(me, f"action:{i}")
    assert concentration.sources(me) == [f"action:{i}" for i in range(1, 6)], _held(me)


def test_limit_for_cl_reads_the_mythic_rows_from_the_shipped_file():
    assert concentration.limit_for_cl(21) == 6, f"CL21 limit={concentration.limit_for_cl(21)}"
    assert concentration.limit_for_cl(40) == 10, f"CL40 limit={concentration.limit_for_cl(40)}"


def test_failed_damage_save_ends_only_the_newest():
    engine, me = _engine(5)
    engine._start_concentration(me, "action:a")
    engine._start_concentration(me, "action:b")
    me.saving_throws["CON"] = -100  # the save fails
    engine._commit_damage(me, 1, "BLUDGEONING", "test:hit", AN, None, reaction_depth=0)
    assert concentration.sources(me) == ["action:a"], _held(me)
