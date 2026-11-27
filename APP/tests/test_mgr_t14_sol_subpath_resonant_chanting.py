"""Native acquisition/table/reload evidence for a withdrawn unchecked modifier.

This is a partial safety repair, not certification of the Foundation Mantra loop.
The cases compile the current authority, without injecting ownership, a selected
mantra, fake trigger receipts, or effect metadata.
"""
import pytest

from combat.ext.force import IMPACT
from tests import worker2_support as native

PREFIX = 'tianxia.subpath.qi.mantra_cultivator.feature.'
FEATURE = PREFIX + 'resonant_chanting'
PARENT = PREFIX + 'three_foundation_mantras'


@pytest.mark.parametrize('parent_owned', [False, True], ids=['no-parent', 'parent-unstarted'])
def test_no_independent_push_without_an_active_mantra(tmp_path, parent_owned):
    talents = [IMPACT, FEATURE] + ([PARENT] if parent_owned else [])
    combat, table, mid = native.fixture(tmp_path, talents, cl=6, seed='MGR-T14-CHANT-NO-PUSH')
    engine = native.reload(tmp_path, mid)
    # The catalog retains the real Qi technique and its ordinary optional push.
    native.candidate(combat, mid, 'Impact', target=native.FOE)
    modified = [c for c in engine.legal_candidates()
                if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '') == 'Impact + Resonant Chanting'
                and c.target_ids == (native.FOE,)]
    assert not modified, 'No maintained Attraction exists to authorize an extra push'
    before = engine.state.actors[native.FOE].position
    choice = native.candidate(combat, mid, 'Impact', target=native.FOE)
    native.settle(table, mid, choice.candidate_id,
                  choices={'choice:needle.force_impact_push': ['stay']})
    loaded = native.reload(tmp_path, mid)
    after = loaded.state.actors[native.FOE].position
    # An unchecked variant would create a separate five-foot push even when the
    # player declines Impact's own push (or the Impact misses). The fixed
    # catalog never offers that unauthorized variant; its ordinary action stays.
    assert after == before
    assert not any('mantra' in c.condition_id for c in loaded.state.actors[native.OWNER].conditions.values())


@pytest.mark.parametrize('owner_talents,ally_talents,cl', [
    ([IMPACT], [FEATURE], 6),
    ([IMPACT, FEATURE], [], 5),
])
def test_wrong_owner_and_below_cl_do_not_add_a_push(tmp_path, owner_talents, ally_talents, cl):
    combat, table, mid = native.fixture(tmp_path, owner_talents, ally_talents=ally_talents,
                                      cl=cl, seed='MGR-T14-CHANT-BOUNDARY')
    engine = native.reload(tmp_path, mid)
    assert not any('Resonant Chanting' in getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '')
                   for c in engine.legal_candidates())
    before = engine.state.actors[native.FOE].position
    native.settle(table, mid, native.candidate(combat, mid, 'Impact', target=native.FOE).candidate_id,
                  choices={'choice:needle.force_impact_push': ['stay']})
    assert native.reload(tmp_path, mid).state.actors[native.FOE].position == before
