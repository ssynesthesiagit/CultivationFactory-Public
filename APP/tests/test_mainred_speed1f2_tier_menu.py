"""MAINREDSPEED1F2: table scores keep the incumbent (tier-free) scorer.

452076b6 ruled that the generic read-only menu ranking keeps the incumbent
scorer, and only built-in AI turn selection uses the Tricky tier. The
production decision context carries the tier profile, so menu_rank.native_scores
must drop it for presentation scores only. Synthetic fixture; offline.
"""
from types import SimpleNamespace

import pytest

from combat import menu_rank
from tests.worker2_support import fixture


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(menu_rank, '_CLIENT', SimpleNamespace(
        embed=lambda texts: [[1.0, 0.0] for _ in texts], prefetch=lambda *a, **kw: None))


def test_table_scores_ignore_ai_tier_profile(tmp_path):
    combat, _, mid = fixture(tmp_path, ['TAL_DARK_PURE_DARKNESS'], ask=False, seed='MAINREDSPEED1F2-TIER')
    session = combat._load_session(mid)
    context = combat.menu_ranking_context(session)
    assert context.tactics.get('tier'), 'fixture must carry an AI tier profile'
    full = combat.controller.choose_primary_action(context)
    ids = {row.candidate_id for row in full.record.scored_alternatives[::2]}
    ids.add(full.record.selected_candidate_id)
    known = {row.entity_id for row in context.actors}
    scores = menu_rank.native_scores(combat, session.engine, known, session=session, candidate_ids=ids)

    def display(tactics):
        ctx = context.model_copy(update={'zones': (), 'recent_events': (), 'tactics': tactics,
            'team_behavior': context.team_behavior.model_copy(update={'focus_target_id': None})})
        pick = combat.controller.score_primary_projection(ctx, ids)
        return {row.candidate_id: row.total for row in pick.record.scored_alternatives}

    tierless = display({})
    assert scores == tierless, 'a tier profile reordered a human table menu'
    assert display(context.tactics) != tierless, 'tier must change some score, or this test proves nothing'
