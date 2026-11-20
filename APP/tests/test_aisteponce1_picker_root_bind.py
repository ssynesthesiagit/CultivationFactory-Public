"""A square-picker root binds through its source, not through the whole menu (AISTEPONCE1).

candidates_for_intent used to regenerate the complete query() menu to find one picker root (206 s on a 125k-row
turn in DEPLOYPLAY1 draw a16ada36ac). A root's identity hash names its source, so the bind now regenerates only the
sources whose identity matches. For every picker root a query() menu offers, that must return exactly the row the
full-menu filter returns, and must never fall back to a whole-menu generation.
"""
import pytest

from combat.placement_menu import query
from tests.cw2_service_support import add_action, seal
from tests.test_combat_gate2b_kernel import intent_for
from tests.worker2_support import fixture


def _air(tmp_path):  # area placement (typed area, CELL target)
    return fixture(tmp_path, ['TAL_AIR_COURT_OF_THE_FOUR_WINDS'])


def _any_cell(tmp_path):  # any-cell placement (Gate4 _any_cell_candidates)
    def prepare(bundles):
        add_action(bundles[0], 'Mark a square', [{'type': 'damage', 'flat': 1, 'damage_types': ['force'],
                                                  'applies_to': 'target'}], target='CELL')
        params = bundles[0]['action_catalog'][-1]['parameters']
        params['any_cell'] = True
        params.pop('player_only')  # an ordinary action, offered to every controller
        seal(bundles[0])
    return fixture(tmp_path, [], bundle_transform=prepare)


def _row(candidate):
    return candidate.candidate_id, candidate.metadata, tuple(candidate.option_ids)


@pytest.mark.parametrize('make,kind', [(_air, 'area'), (_any_cell, 'any_cell')])
def test_every_picker_root_binds_through_its_source(tmp_path, monkeypatch, make, kind):
    combat, _, mid = make(tmp_path)
    engine = combat._load_session(mid).engine
    with query():
        menu = engine.legal_candidates()
    roots = [c for c in menu if c.metadata.get('placement_picker')]
    assert roots, f'fixture must offer a {kind} picker root'
    whole = []
    real = type(engine)._generate_legal_candidates

    def generate(self, intent=None, **kwargs):
        if intent is None and kwargs.get('sources') is None:
            whole.append(True)
        return real(self, intent, **kwargs)
    for root in roots:
        expected = [_row(c) for c in menu if c.candidate_id == root.candidate_id and c.metadata.get('placement_picker')]
        with monkeypatch.context() as patch:
            patch.setattr(type(engine), '_generate_legal_candidates', generate)
            bound = [_row(c) for c in engine.candidates_for_intent(intent_for(root))]
        assert bound == expected, f'{kind} root {root.display_name!r} lost its row when bound through its source'
        assert not whole, f'{kind} root {root.display_name!r} fell back to a whole-menu generation'
