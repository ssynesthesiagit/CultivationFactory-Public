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


def drive_auto(combat, mid, root, monkeypatch, mode, aim=None):
    """Select through the real AUTO transport, with an offline decision source."""
    from types import SimpleNamespace
    from combat.gate2_runtime_models import ActionIntent
    from combat.gate5_service import AI_RESPONSE_SCHEMA
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=mode)
    submitted = payload(root, aim)
    if mode == 'LOCAL_AUTO':
        original = combat.controller.choose_primary_action
        def choose(context):
            choice = original(context)
            intent = ActionIntent(intent_id='intent:placement-regression', **submitted)
            return choice.model_copy(update={'intent': intent, 'record': choice.record.model_copy(
                update={'selected_candidate_id': root.candidate_id, 'selected_option_ids': ()})})
        monkeypatch.setattr(combat.controller, 'choose_primary_action', choose)
    else:
        calls = []
        def complete(**kwargs):
            import json
            calls.append(kwargs)
            answer = submitted
            if kwargs['purpose'] == 'combat_placement':
                frame = json.loads(kwargs['prompt_text'].split('\n\n', 1)[1])
                from combat.candidate_knowledge import query as observed
                engine = combat._load_session(mid).engine
                with observed(engine):
                    native = list(placement_menu.cells(engine, root))
                assert frame['legal_placements']
                assert [p['placement_destination'] for p in frame['legal_placements']] == [
                    c.destination.model_dump(mode='json') for c in native]
                answer = {**submitted, 'placement_destination': native[-1].destination.model_dump(mode='json')}
            return {'value': {'schema': AI_RESPONSE_SCHEMA, 'action_intent': answer},
                    'provider_id': 'test:offline', 'model': 'fake'}
        combat.ai_provider = SimpleNamespace(status=lambda: {'ready': True}, complete_json=complete)
    result = combat.auto_step(mid)
    assert result['status'] == 'COMMITTED', result
    if mode == 'API_AUTO':
        assert len(calls) == (1 if aim is not None else 2)


@pytest.mark.parametrize('mode', ['LOCAL_AUTO', 'API_AUTO'])
def test_auto_choice_can_select_every_legal_cell_and_reload(tmp_path, monkeypatch, mode):
    combat, _, mid = setup(tmp_path)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=mode)
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
    if mode == 'LOCAL_AUTO':
        monkeypatch.setattr(needle, 'ask', choose)
    drive_auto(combat, mid, root, monkeypatch, mode)
    if mode == 'LOCAL_AUTO':
        assert calls
    assert any(z.center == aimed for z in reload(tmp_path, mid).state.zones.values())


@pytest.mark.parametrize('mode', ['LOCAL_AUTO', 'API_AUTO'])
def test_auto_exact_aim_outside_sample_commits_reload(tmp_path, monkeypatch, mode):
    combat, _, mid = setup(tmp_path)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=mode)
    session = combat._load_session(mid)
    root = root_for(combat, mid)
    native = list(placement_menu.cells(session.engine, root))
    aimed = native[-1].destination
    monkeypatch.setattr(placement_menu, 'search', lambda *args: native[0])
    drive_auto(combat, mid, root, monkeypatch, mode, aimed)
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
    # Full enumeration now uses the native bulk action query. Apply the same
    # synthetic one-cell legality there as to the exact-cell probe above.
    native = session.engine._action_candidates
    def one_cell(*args, **kwargs):
        return [row for row in native(*args, **kwargs) if row.destination == aimed]
    monkeypatch.setattr(session.engine, '_action_candidates', one_cell)
    found = placement_menu.search(session.engine, root, context)
    assert found is not None and found.destination == aimed


def test_annotation_does_not_delete_legal_ability_on_ranking_miss(tmp_path, monkeypatch):
    combat, _, mid = setup(tmp_path)
    context = combat.ai_decision_context(combat._load_session(mid))
    assert any(c.metadata.get('placement_picker') for c in context.legal_candidates)
    monkeypatch.setattr(placement_menu, 'search', lambda *args: None)
    annotated = placement_menu.annotate(combat._load_session(mid).engine, context)
    assert [c.candidate_id for c in annotated.legal_candidates] == [c.candidate_id for c in context.legal_candidates]
    assert all(c.metadata.get('placement_ai_unavailable') is True
               for c in annotated.legal_candidates if c.metadata.get('placement_picker'))


def test_context_keeps_main_knowledge_projection_and_ranked_placement_aim(tmp_path):
    combat, _, mid = setup(tmp_path)
    context = combat.ai_decision_context(combat._load_session(mid))
    roots = [c for c in context.legal_candidates if c.metadata.get('placement_picker')]
    assert roots
    assert any(c.metadata.get('placement_evaluation') for c in roots)
    # Main's optional own-knowledge field remains part of the shared context.
    assert 'own_knowledge' in type(context).model_fields


def test_second_stage_ranking_uses_own_knowledge_and_only_selected_ability(tmp_path, monkeypatch):
    from tests.worker2_support import settle
    monkeypatch.setenv('CF_COMBAT_AI_SLICES_1_2', '1')
    combat, table, mid = setup(tmp_path)
    root = root_for(combat, mid)
    real_search = placement_menu.search
    real_resolve = placement_menu.resolve
    resolving = False
    calls = []
    def resolve(*args, **kwargs):
        nonlocal resolving
        previous = resolving
        resolving = True
        try:
            return real_resolve(*args, **kwargs)
        finally:
            resolving = previous
    def rank(engine, candidate, context):
        # Table refreshes legitimately rank every ability. Inspect only the
        # selected action's second-stage recommendation, before its commit.
        if not resolving:
            return real_search(engine, candidate, context)
        assert context.own_knowledge is not None
        # The AI context may filter/expand a player's empty-area placeholder;
        # its identity is not square authority. Keep sibling tactics available.
        assert any(c.source_definition_id != root.source_definition_id for c in context.legal_candidates)
        calls.append(candidate.candidate_id)
        return real_search(engine, candidate, context)
    monkeypatch.setattr(placement_menu, 'search', rank)
    monkeypatch.setattr(placement_menu, 'resolve', resolve)
    prompts = settle(table, mid, root.candidate_id)
    assert calls and set(calls) == {root.candidate_id}
    assert any(p['context']['reaction_source_id'] == placement_menu.CHOICE for p in prompts)
    assert reload(tmp_path, mid).state.zones


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
