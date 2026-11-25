"""Calamity Form blast previews count the allies a sealed destruction_shape_save covers.

The sealed wrapper has no dice of its own (its harm is the nested on_fail payload),
so the area_effect_risk answer from destruction_blast.shape_save_risk is what makes
the placement preview see the covered ally. Execution is unchanged by that answer.
"""
import pytest
from tests.test_auto62_destruction import triple_fight, P


def _line_candidate(tmp_path):
    combat, _, mid = triple_fight(tmp_path, [P + 'calamity_form'], third_ally=True)
    engine = combat._load_session(mid).engine
    return next(c for c in engine.legal_candidates()
                if c.display_name.startswith('Calamity Form: Line')
                and c.destination is not None and (c.destination.x, c.destination.y) == (5, 0))


def test_blast_preview_counts_the_ally_its_sealed_save_covers(tmp_path):
    candidate = _line_candidate(tmp_path)
    assert candidate.metadata['allies_in_area'] == 1
    assert candidate.metadata['unavoidable_allies_in_area'] == 1
    assert 'Hits allies too: Second visitor' in candidate.display_name


def test_blast_preview_answers_the_documented_risk_query_only_for_its_own_effect(tmp_path):
    from combat.ext import destruction_blast
    assert destruction_blast.shape_save_risk(None, {'type': 'destruction_shape_save'}) == 'harmful'
    assert destruction_blast.shape_save_risk(None, {'type': 'save'}) is None
    assert destruction_blast.shape_save_risk(None, {'type': 'damage'}) is None
