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


def test_a_remote_origin_root_binds_cold_and_commits_through_the_table(tmp_path):
    """Shockwave from a Pressure Anchor: the root's identity is hashed inside the anchor's origin scope, so the source
    walk that binds it must enter the same scope (gate2_engine._origin_scopes) or the choice is refused as stale."""
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    from combat.placement_menu import CHOICE
    from tests.worker2_support import OWNER, ROOT, CombatService, fixture, prompt_turn, reload, settle

    combat, table, mid = fixture(tmp_path, ['TAL_FORCE_SHOCKWAVE'])
    anchor = Position(x=6, y=5)
    set_anchor = next(c for c in combat._legal_candidates(combat._load_session(mid)) if c.display_name == 'Set Anchor — choose a square')
    settle(table, mid, set_anchor.candidate_id, picks={CHOICE: cell_id(anchor, include_altitude=True)})
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    prompt_turn(table, mid, OWNER)

    with query():
        menu = combat._load_session(mid).engine.legal_candidates()
    remote = [c for c in menu if c.metadata.get('placement_picker') and (c.metadata.get('effect_origin') or {}).get('id') == 'force:6,5,0']
    assert len(remote) == 1 and 'Shockwave' in remote[0].display_name
    cold = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert [_row(c) for c in cold.candidates_for_intent(intent_for(remote[0]))] == [_row(remote[0])]

    before = len(reload(tmp_path, mid).events)
    settle(table, mid, remote[0].candidate_id, picks={CHOICE: cell_id(anchor, include_altitude=True)})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].action_available is False
    new = engine.events[before:]
    assert any((e.payload.get('effect_origin') or {}).get('id') == 'force:6,5,0' and 'Shockwave' in str(e.payload.get('log')) for e in new)
    assert any(e.event_type == 'SAVE_ROLLED' for e in new), 'the Shockwave must resolve from the anchor'
