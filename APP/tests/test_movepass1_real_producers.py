"""MOVEPASS1 review fix (finding 1): the Incapacitated effects that the real Factory producers apply open a route through a hostile.

Before this fix, Sleep Beneath the Roots (Hallucinogenic Bloom, its sleep pick) and the Reflection Cell (World Behind the Glass)
were labelled "Incapacitated" but their rule rows had no Incapacitated marker and no named condition, so a hostile under them still
blocked a corridor. These tests drive the real abilities (not a synthetic condition) and then check that the route opens while the
effect lasts and closes again when it ends.

Public-CI harness: built only from tests/thrum_grave_support.py (synthetic fights, no owner data, no repository-history reads).
The few helpers used here are copied in below (they were previously imported from tests/test_riders_c8.py, which loads a
base-commit authority through git history and so could not run on public CI).
"""

from combat import typed_executor
from combat import movement_passage
from combat.gate2_runtime_models import RollRecord
from tests.thrum_grave_support import ME, FOE, MIND_SPIKE, answers, fight, held, turn, use

MW = "tianxia.tradition.spirit.mushroom_dreamwalker.feature."
MS = "tianxia.tradition.spirit.mirror_speaker.feature."
MS_ALL = [MIND_SPIKE] + [MS + k for k in ("reflection_listener", "inverted_glance", "borrowed_reflection", "mirror_confession", "world_behind_the_glass")]
MW_ALL = [MIND_SPIKE] + [MW + k for k in ("mycelial_dream", "spore_murmur", "under_root_memory", "hallucinogenic_bloom", "fruiting_body_of_the_dream")]
TRACE = "Reflection Trace"
SPORE = "Dream-Spore Mark"


def trace(engine, subject_id, owner=ME):
    engine._apply_condition(engine.state.actors[subject_id], typed_executor.mark_condition_id(TRACE, owner), "test", owner, expires_on="UNTIL_REMOVED")


def give_spores(engine, subject_id, n, owner=ME):
    from combat.ext.stacking_marks import add

    add(engine, engine.state.actors[owner], engine.state.actors[subject_id], SPORE, n, "test")


def use_at(engine, name, x, y, actor_id=ME):
    candidate = next(c for c in engine.legal_candidates() if c.display_name.split(" at ")[0] == name and c.destination is not None
                     and (c.destination.x, c.destination.y) == (x, y))
    before = len(engine.events)
    from combat.gate2_runtime_models import ActionIntent

    engine.execute_intent(ActionIntent(intent_id=f"mp1-{name}-{before}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor_id, target_ids=candidate.target_ids or (), destination=candidate.destination))
    return engine.events[before:]


def raw_d20s(engine, pick):
    """Fix the raw d20 (so the table's d20 rewrite and bonus seams still run): ``pick(kw)`` gives the natural result."""
    def raw(**kw):
        natural, mode = int(pick(kw)), kw.get("mode") or "NORMAL"
        return RollRecord(roll_id=f"mp1-raw-{kw['reason']}", counter_start=1, counter_end=2, expression="1d20", actor_id=kw["actor_id"], reason=kw["reason"],
                          dice=(natural,) if mode == "NORMAL" else (natural, natural), modifier=kw["modifier"], total=natural + kw["modifier"],
                          natural_result=natural, mode=mode, discarded=() if mode == "NORMAL" else (natural,))
    engine.roller.raw_d20 = raw
    engine.roller.d20 = type(engine.roller).d20.__get__(engine.roller)  # undo a fixed_d20 earlier in the test


ROOT_SLEEP = "condition:typed.sleep_beneath_the_roots"
CELL = "condition:typed.reflection_cell"



def test_sleep_beneath_the_roots_from_the_real_bloom_opens_the_hostile_space_until_damage():
    engine = fight(MW_ALL, dc=40, foe_at=(8, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    give_spores(engine, FOE, 3)
    use_at(engine, "Hallucinogenic Bloom", 8, 6)
    answers(engine, {"dreamwalker.bloom": ("sleep",), "dreamwalker.bloom_spread": None})
    turn(engine, FOE)  # the bloom's sleep is applied on the foe's turn
    assert held(foe, ROOT_SLEEP)
    assert movement_passage.incapacitated(foe) and movement_passage.passable(engine, me, foe)
    engine._commit_damage(foe, 3, "SLASHING", "test", ME, None, reaction_depth=1)
    assert not held(foe, ROOT_SLEEP)
    assert not movement_passage.incapacitated(foe)
    assert not movement_passage.passable(engine, me, foe)  # awake again: the hostile blocks passage


def test_reflection_cell_from_the_real_world_behind_the_glass_is_incapacitated_for_passage():
    engine = fight(MS_ALL, dc=40, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "World Behind the Glass")
    trace(engine, FOE)
    turn(engine, FOE)
    me.reaction_available = False
    raw_d20s(engine, lambda kw: 15)
    answers(engine, {})
    use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    turn(engine, ME)
    raw_d20s(engine, lambda kw: 2)
    use(engine, "Mirror Confession: Emotional Confession", FOE)
    assert held(foe, CELL, ME)
    assert movement_passage.incapacitated(foe) and movement_passage.passable(engine, me, foe)
