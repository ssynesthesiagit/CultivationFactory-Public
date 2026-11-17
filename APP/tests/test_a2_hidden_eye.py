"""Second-pass Hidden Eye mechanics through real table commits, cold reload and replay.

Every ability executes through the service transaction (fixture -> table action -> cold reload), not the bare
engine. Shared harness: tests/worker2_support.py.
"""
import pytest

from combat.ext.riders14_research import CREATURE_TYPE, KNOWN, NOTICE, modification_options
from tests.h1_support import sheet
from combat.ext.mind_hidden_eye import FOCUS
from tests.worker2_support import OWNER, FOE, fixture, turn, candidate, settle, reload

BASE = "TAL_THE_HIDDEN_EYE_BASE_SPHERE_FEATURES"
BIOLOGICAL = "tianxia.talent.the_hidden_eye.biological_insight"
APPROACH = "choice:needle.eye_approach"


def _analyze(combat, table, mid, approach):
    chosen = candidate(combat, mid, "Analyze", target=FOE)
    return settle(table, mid, chosen.candidate_id, picks={APPROACH: approach})


def _learned(engine):
    """(counted picks, free facts) the owner holds about the foe, from its evented conditions."""
    rows = [c.data for c in engine.state.actors[OWNER].conditions.values()
            if c.condition_id == KNOWN and (c.data or {}).get("target_id") == FOE]
    return [r["name"] for r in rows if not r.get("free")], [r["value"] for r in rows if r.get("free")]


def _foe_with_type(cl):
    document = sheet([], cl=cl)
    document["identity"]["creature_type"] = "Beast"
    return document


@pytest.mark.parametrize("approach,free", [("Nature", True), ("Investigation", False)],
                         ids=["nature-learns-creature-type", "investigation-learns-no-type"])
def test_biological_insight_creature_type_is_free_only_for_nature(tmp_path, approach, free):
    combat, table, mid = fixture(tmp_path, [BASE, BIOLOGICAL], cl=5, seed="A2-BIO",
                                 foe_sheet=_foe_with_type(5))
    _analyze(combat, table, mid, approach)
    engine = reload(tmp_path, mid)
    counted, facts = _learned(engine)
    assert engine.state.actors[FOE].creature_types == ("Beast",)
    # Exactly one counted characteristic, whatever the approach; the creature type never takes its place.
    assert len(counted) == 1 and CREATURE_TYPE not in counted
    assert facts == (["Beast"] if free else [])
    # The free fact is information only: the Modify Characteristics menu offers just the counted pick.
    assert modification_options(engine.state.actors[OWNER], engine.state.actors[FOE]) == counted


NOTICE_TALENT = "TAL_THE_HIDDEN_EYE_NOTICE_PROFILING"
NOTICE_CHOICE = "choice:needle.eye_profile"


def _foe_analyzes_owner(tmp_path, *, owner_talents, owner_answer, seed):
    """The foe Analyzes the owner on its own turn; ``owner_answer`` answers the owner's Notice Profiling prompt
    (None declines). Returns the cold-reloaded engine and the owner's Martial Focus before and after."""
    combat, table, mid = fixture(tmp_path, [BASE, *owner_talents], cl=5, seed=seed,
                                 foe_sheet=sheet([BASE], cl=5))
    engine = combat._load_session(mid).engine
    focus_before = engine.state.actors[OWNER].resources.get(FOCUS, 0)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, FOE)
    chosen = candidate(combat, mid, "Analyze", target=OWNER)
    settle(table, mid, chosen.candidate_id, picks={APPROACH: "Investigation", NOTICE_CHOICE: owner_answer})
    engine = reload(tmp_path, mid)
    return engine, focus_before, engine.state.actors[OWNER].resources.get(FOCUS, 0)


def _notice(engine):
    """The owner's Notice Profiling knowledge (this round's notices and whether they were expended), or None."""
    owner = engine.state.actors[OWNER]
    rows = [c.data for c in owner.conditions.values() if c.condition_id == NOTICE]
    return rows[0] if rows else None


def test_notice_profiling_owner_is_told_and_may_expend_focus_for_the_round(tmp_path):
    engine, before, after = _foe_analyzes_owner(tmp_path, owner_talents=[NOTICE_TALENT], owner_answer="profile", seed="A2-NOTICE")
    notice = _notice(engine)
    assert notice is not None and [row["learner"] for row in notice["notices"]] == [FOE]
    assert notice["notices"][0]["characteristics"] and notice["revealed"] is True
    assert before >= 1 and after == before - 1


def test_notice_profiling_owner_may_decline_and_keeps_focus(tmp_path):
    engine, before, after = _foe_analyzes_owner(tmp_path, owner_talents=[NOTICE_TALENT], owner_answer=None, seed="A2-NOTICE")
    notice = _notice(engine)
    assert notice is not None and len(notice["notices"]) == 1
    assert notice["revealed"] is False and after == before


def test_without_notice_profiling_nothing_is_known(tmp_path):
    engine, _, _ = _foe_analyzes_owner(tmp_path, owner_talents=[], owner_answer=None, seed="A2-NOTICE")
    assert _notice(engine) is None
