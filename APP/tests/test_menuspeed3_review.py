"""Review regressions: sampling ranks placements without restricting authority."""
import pytest

from combat import placement_menu
from combat.ext import needle
from tests.test_menuspeed3_placement import setup, root_for
from tests.worker2_support import OWNER, ALLY, FOE, fixture, reload


@pytest.fixture(autouse=True)
def offline_menu_embeddings(monkeypatch):
    from types import SimpleNamespace
    from combat import menu_rank
    monkeypatch.setattr(menu_rank, '_CLIENT', SimpleNamespace(
        embed=lambda texts: [[1.0, 0.0] for _ in texts],
        prefetch=lambda *args, **kwargs: None))


def payload(root, aim=None):
    result = {key: root.model_dump(mode='json')[key] for key in (
        'candidate_id', 'decision_id', 'state_version', 'actor_id',
        'target_ids', 'destination', 'option_ids')}
    if aim is not None:
        result['placement_destination'] = aim.model_dump(mode='json')
    return result


@pytest.mark.parametrize('mode', ['LOCAL_AUTO', 'API_AUTO'])
def test_auto_choice_can_select_every_legal_cell_and_reload(tmp_path, monkeypatch, mode):
    combat, _, mid = setup(tmp_path, modes={OWNER: mode, ALLY: 'MANUAL', FOE: 'MANUAL'})
    session = combat._load_session(mid)
    root = root_for(combat, mid)
    from combat.candidate_knowledge import query as observed
    with observed(session.engine):
        native = list(placement_menu.cells(session.engine, root))
    assert len(native) > 1
    expected = {needle.cell_id(row.destination, include_altitude=True) for row in native}
    aimed = native[-1].destination
    monkeypatch.setattr(placement_menu, 'search', lambda *args: native[0])
    calls = []
    def choose(engine, intent, checkpoint, actor, choice, options, **kwargs):
        assert choice == placement_menu.CHOICE
        assert set(options) == expected
        assert kwargs['preferred'] == [needle.cell_id(native[0].destination, include_altitude=True)]
        calls.append(options)
        return [needle.cell_id(aimed, include_altitude=True)]
    monkeypatch.setattr(needle, 'ask', choose)
    combat.submit_intent(mid, payload(root), [], None)
    assert calls
    assert any(z.center == aimed for z in reload(tmp_path, mid).state.zones.values())


@pytest.mark.parametrize('mode', ['LOCAL_AUTO', 'API_AUTO'])
def test_auto_exact_aim_outside_sample_commits_reload(tmp_path, monkeypatch, mode):
    combat, _, mid = setup(tmp_path, modes={OWNER: mode, ALLY: 'MANUAL', FOE: 'MANUAL'})
    session = combat._load_session(mid)
    root = root_for(combat, mid)
    native = list(placement_menu.cells(session.engine, root))
    aimed = native[-1].destination
    monkeypatch.setattr(placement_menu, 'search', lambda *args: native[0])
    combat.submit_intent(mid, payload(root, aimed), [], None)
    assert any(z.center == aimed for z in reload(tmp_path, mid).state.zones.values())


def test_sample_miss_falls_back_to_unsampled_legal_cell(tmp_path, monkeypatch):
    combat, _, mid = setup(tmp_path)
    session = combat._load_session(mid)
    root = root_for(combat, mid)
    context = combat.ai_decision_context(session)
    native = list(placement_menu.cells(session.engine, root))
    real_exact, real_cells = placement_menu.exact, placement_menu.cells
    visited = set()
    def empty_probe(engine, root, point):
        visited.add((point.x, point.y, point.z))
        return None
    monkeypatch.setattr(placement_menu, 'exact', empty_probe)
    monkeypatch.setattr(placement_menu, 'cells', lambda *args: iter(()))
    assert placement_menu.search(session.engine, root, context) is None
    action = session.engine.action_catalog[root.source_definition_id]
    aimed = next(row.destination for row in native
                 if (row.destination.x, row.destination.y, row.destination.z) not in visited
                 and (not row.metadata.get('empty_area') or action.parameters.get('ai_allow_empty_area')))
    monkeypatch.setattr(placement_menu, 'cells', real_cells)
    monkeypatch.setattr(placement_menu, 'exact', lambda e, r, p: real_exact(e, r, p) if p == aimed else None)
    found = placement_menu.search(session.engine, root, context)
    assert found is not None and found.destination == aimed


def test_annotation_does_not_delete_legal_ability_on_ranking_miss(tmp_path, monkeypatch):
    combat, _, mid = setup(tmp_path)
    context = combat.ai_decision_context(combat._load_session(mid))
    assert any(c.metadata.get('placement_picker') for c in context.legal_candidates)
    monkeypatch.setattr(placement_menu, 'search', lambda *args: None)
    assert placement_menu.annotate(combat._load_session(mid).engine, context).legal_candidates == context.legal_candidates


def test_context_keeps_main_knowledge_projection_and_ranked_placement_aim(tmp_path):
    combat, _, mid = setup(tmp_path)
    context = combat.ai_decision_context(combat._load_session(mid))
    roots = [c for c in context.legal_candidates if c.metadata.get('placement_picker')]
    assert roots
    assert any(c.metadata.get('placement_evaluation') for c in roots)
    # Main's optional own-knowledge field remains part of the shared context.
    assert 'own_knowledge' in type(context).model_fields


def test_explicit_wall_aim_keeps_native_legality_and_tactical_score(tmp_path):
    combat, _, mid = fixture(tmp_path, ['TAL_FORCE_FORCE_WALL'],
                            positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 2, 'y': 6},
                                       FOE: {'x': 14, 'y': 6}})
    session = combat._load_session(mid)
    engine = session.engine
    actor = engine.state.actors[OWNER]
    actor.current_hp = max(1, actor.maximum_hp // 2)
    root = next(c for c in combat._legal_candidates(session)
                if c.metadata.get('placement_picker') and c.display_name.startswith('Force Wall'))
    rows = list(placement_menu.cells(engine, root))
    assert rows
    tactical = [row for row in rows if row.metadata.get('tactical_wall')]
    assert tactical, 'fixture must exercise wall screening rather than only hostile-hit squares'
    chosen = tactical[0]
    exact = placement_menu.exact(engine, root, chosen.destination)
    assert exact is not None and exact.metadata['tactical_wall']
    assert exact.metadata['expected_damage'] == chosen.metadata['expected_damage']
    # Submit through the actual table service, then inspect cold persisted state.
    combat.submit_intent(mid, payload(root, chosen.destination), [], None)
    assert any(z.trigger_profile.get('wall') for z in reload(tmp_path, mid).state.zones.values())
