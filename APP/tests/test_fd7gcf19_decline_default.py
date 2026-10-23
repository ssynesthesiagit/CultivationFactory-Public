"""The table's decline on a pick that only falls back to a decline is a legal answer (FD7GCF19 round 4).

combat/ext/defensive_disciplines.py asks which saving throw the discipline covers with
``default="decline"`` (nobody picked -> the compiled default stands), but
combat/ext/needle.ask transported that choice with ``allow_decline=False``, so the table's
DECLINE answer raised ``ValueError: invalid extension choice decline`` in
combat/choice_checkpoints.validate and the whole intent was rejected by the exact combat
runtime (CombatServiceError: "The completed intent was rejected by the exact combat runtime."
-- it broke the branch's own table-level fight for Nascent Continuity). A decline to a question
whose own fallback is a decline now resolves as "nobody answered": the compiled default stands
and the fight commits.

combat/ai_tactics._effects assumed every row inside a checked effect list is a dict; the
authority's checked save rows carry marker strings in nested ``on_fail``/``on_success`` lists
(battlefield_beheading_line records ``on_success='suppress'``), so ANY decision build for a
creature owning that talent crashed and the whole menu degraded to ``{"error": ...}`` with no
``actor_id``. Marker strings are leaves, never effects.
"""
import pytest

from combat.ext import defensive_disciplines as disciplines
from tests.h1_support import ME
from tests.test_auto3_foundations import TEMPERED
from tests.test_sph_foundations_r1 import BLAST, act, fixture, reload


def test_declining_the_discipline_pick_keeps_the_compiled_default(tmp_path, monkeypatch):
    combat, table, mid = fixture(tmp_path, monkeypatch)
    cid = next(c["candidate_id"] for c in combat.decision(mid)["context"]["legal_candidates"]
               if c["display_name"] == BLAST and ME in c["target_ids"])
    prompt = act(combat, table, mid, cid)["reaction"]
    answer = {**prompt["context"], "selection": "DECLINE"}
    result = act(combat, table, mid, cid, [answer])
    assert result["status"] == "COMMITTED", result
    _, _, engine = reload(tmp_path, mid)
    actor = engine.state.actors[ME]
    # The decline means nobody picked: no discipline record was written and the compiled
    # default (the scan time's narrowed ability) still stands for the fighter.
    assert disciplines.chosen(engine, actor, TEMPERED) is None
    row = next(r for r in engine.typed_reaction_rows[ME] if r["feature_id"] == TEMPERED)
    assert row.get("choose_one") and row.get("abilities"), row


def test_a_decline_to_an_explicitly_declinable_ask_still_transports(tmp_path, monkeypatch):
    # The USE-path answer (how test_sphb1 already records a pick) is unchanged by the same seam.
    combat, table, mid = fixture(tmp_path, monkeypatch)
    cid = next(c["candidate_id"] for c in combat.decision(mid)["context"]["legal_candidates"]
               if c["display_name"] == BLAST and ME in c["target_ids"])
    prompt = act(combat, table, mid, cid)["reaction"]
    answer = {**prompt["context"], "selection": "USE", "option_ids": ["DEX"]}
    assert act(combat, table, mid, cid, [answer])["status"] == "COMMITTED"
    _, _, engine = reload(tmp_path, mid)
    assert disciplines._recorded(engine, engine.state.actors[ME], TEMPERED) == "DEX"


def test_checked_effect_lists_hold_marker_strings_as_leaves():
    from combat.ai_tactics import _effects

    # The shape the authority data really carries (tianxia.talent.sabers.battlefield_beheading_line,
    # effects[0].on_fail[2].on_success = 'suppress'): the recursor must yield only dict rows and still
    # reach the nested rider level instead of crashing on the bare string.
    rows = [{"type": "save", "on_fail": [{"type": "a"}, {"type": "b"},
                                          {"type": "rider", "on_success": "suppress"}]}]
    out = list(_effects(rows))
    assert all(isinstance(row, dict) for row in out), out
    assert rows[0] in out and {"type": "rider", "on_success": "suppress"} in out
