"""Service-level lazy placement preserves the full square-choice authority."""
import pytest
from combat.gate2_runtime_models import Position
from combat.placement_menu import CHOICE, exact, query, search
from tests.worker2_support import OWNER, fixture, reload, settle


def setup(tmp_path, *, modes=None):
    return fixture(tmp_path, ['TAL_AIR_COURT_OF_THE_FOUR_WINDS'], modes=modes)


def root_for(combat, mid):
    return next(c for c in combat._legal_candidates(combat._load_session(mid))
                if c.metadata.get('placement_picker') and 'Gather Current: Press' in c.display_name)


def test_table_menu_defers_cells_and_square_picker_commits_reload(tmp_path):
    combat, table, mid = setup(tmp_path)
    session = combat._load_session(mid)
    root = root_for(combat, mid)
    assert root.destination is None
    native = [c for c in session.engine.legal_candidates()
              if c.source_definition_id == root.source_definition_id]
    assert len(native) > 1
    deferred = [c for c in combat._legal_candidates(session)
                if c.source_definition_id == root.source_definition_id]
    assert len(deferred) == 1
    chosen = native[-1]
    from combat.ext.needle import cell_id
    prompts = settle(table, mid, root.candidate_id,
        picks={CHOICE: cell_id(chosen.destination, include_altitude=True)})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == CHOICE)
    assert prompt['choice']['map_pick']['cells']
    assert {o['id'] for o in prompt['choice']['options']} == {
        cell_id(c.destination, include_altitude=True) for c in native}
    engine = reload(tmp_path, mid)
    assert any(z.center == chosen.destination for z in engine.state.zones.values())
    assert engine.state.actors[OWNER].bonus_action_available is False


def test_ranked_search_is_deterministic_and_exact_cells_remain_legal(tmp_path):
    combat, _, mid = setup(tmp_path)
    session = combat._load_session(mid)
    root = root_for(combat, mid)
    context = combat.ai_decision_context(session)
    a, b = search(session.engine, root, context), search(session.engine, root, context)
    assert a is not None and a == b
    native = [c for c in session.engine.legal_candidates()
              if c.source_definition_id == root.source_definition_id]
    assert all(exact(session.engine, root, c.destination) is not None for c in native)


def test_explicit_second_stage_aim_commits_and_reloads(tmp_path):
    combat, _, mid = setup(tmp_path)
    session = combat._load_session(mid)
    root = root_for(combat, mid)
    policy, _ = combat.policies.for_actor(OWNER)
    assert session.engine.placement_policies[OWNER] == policy.model_dump(mode='json')
    assert combat._clone_engine(combat.source_root, session.engine).placement_policies == session.engine.placement_policies
    cell = root.metadata['placement_witness']
    payload = {k: root.model_dump(mode='json')[k] for k in (
        'candidate_id', 'decision_id', 'state_version', 'actor_id', 'target_ids', 'destination', 'option_ids')}
    payload['placement_destination'] = cell
    combat.submit_intent(mid, payload, [], None)
    engine = reload(tmp_path, mid)
    assert any(z.center == Position.model_validate(cell) for z in engine.state.zones.values())


def test_illegal_second_stage_aim_leaves_fight_unchanged(tmp_path):
    import pytest
    combat, _, mid = setup(tmp_path)
    session = combat._load_session(mid)
    root = root_for(combat, mid)
    before = session.engine.state.model_dump(mode='json')
    payload = {k: root.model_dump(mode='json')[k] for k in (
        'candidate_id', 'decision_id', 'state_version', 'actor_id', 'target_ids', 'destination', 'option_ids')}
    payload['placement_destination'] = {'x': session.engine.grid.width, 'y': 0}
    with pytest.raises(Exception) as rejected:
        combat.submit_intent(mid, payload, [], None)
    assert 'legal' in str(rejected.value).lower() or 'rejected' in str(rejected.value).lower()
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before


def test_cell_id_presentation_preserves_altitude():
    from combat.choice_presentation import option_cell
    assert option_cell('cell:2,3,4') == {'x': 2, 'y': 3, 'z': 4}
    assert option_cell('cell:2,3') == {'x': 2, 'y': 3}


def test_spread_search_rotates_through_every_cell_with_a_bounded_budget(monkeypatch):
    from types import SimpleNamespace
    from combat import placement_menu
    seen, per_phase = set(), []
    actor = SimpleNamespace(position=Position(x=0, y=0))
    engine = SimpleNamespace(state=SimpleNamespace(state_version=0, actors={'actor:test': actor}),
                             grid=SimpleNamespace(width=11, height=7))
    root = SimpleNamespace(actor_id='actor:test', candidate_id='candidate:test', metadata={'placement_witness': {'x': 0, 'y': 0}})
    def probe(engine, root, point):
        seen.add((point.x, point.y, point.z))
        per_phase.append(point)
        return None
    monkeypatch.setattr(placement_menu, 'exact', probe)
    # Isolate the bounded heuristic; exhaustive miss handling has its own
    # regression below, and this synthetic engine has no legal action catalog.
    monkeypatch.setattr(placement_menu, 'cells', lambda engine, root: iter(()))
    # The observed-query scope owns no authoritative state and needs an actual
    # engine's roster only when a candidate is returned. No server is contacted.
    from contextlib import nullcontext
    from combat import candidate_knowledge
    monkeypatch.setattr(candidate_knowledge, 'query', lambda engine: nullcontext())
    for phase in range(77):
        engine.state.state_version = phase
        per_phase.clear()
        assert placement_menu.search(engine, root, SimpleNamespace(actors=(), legal_candidates=())) is None
        assert len(per_phase) <= 33
    assert seen == {(x, y, 0) for y in range(7) for x in range(11)}


def test_model_seat_can_choose_the_ability_then_any_offered_square(tmp_path):
    import json
    from tests.test_agent_seats import runner_for
    combat, table, mid = setup(tmp_path)
    root = root_for(combat, mid)
    native = [c for c in combat._load_session(mid).engine.legal_candidates()
              if c.source_definition_id == root.source_definition_id]
    aimed = max((c.destination for c in native), key=lambda p: (p.y, p.x, p.z))
    expected = []
    def fake(provider, prompt, png):
        frame = json.loads(prompt.split('\n', 1)[1])
        legal = frame['legal_menu']
        if 'ability' in legal:
            options = legal['choice']['options']
            assert len(options) == len(native), 'the model must receive every legal square'
            expected.append(options[-1]['id'])
            return json.dumps({'selection': 'USE', 'option_ids': expected[-1:], 'spend': 0}), {}
        key = next((k for k, row in legal.items() if row['action'] == 'Gather Current: Press'), None)
        if key is None:
            # Ranked menus keep later options behind MORE. An offline model
            # must navigate those pages, rather than raise StopIteration and
            # silently fall back to the built-in controller's different action.
            return 'MORE', {}
        end = next(k for k, row in legal.items() if row['action'] == 'End turn')
        return json.dumps({'plan': [key, end]}), {}
    runner, _ = runner_for(tmp_path, table, fake, timeout=30)
    runner.set_seat(mid, OWNER, 'MODEL', 'fake')
    assert runner.drive(mid, max_steps=1) == 1
    # One driver iteration opens the persisted picker; the next answers it.
    assert runner.drive(mid, max_steps=1) == 1
    assert expected, ('the model must receive the second-stage square choice', runner.decisions(mid))
    assert all(not row.get('fallback') for row in runner.decisions(mid))
    # The model receives public option aliases; its last alias maps back to the
    # final y/x/height entry in the complete engine-owned square picker.
    engine = reload(tmp_path, mid)
    assert any(z.center == aimed for z in engine.state.zones.values())


@pytest.mark.parametrize('same_place', [False, True])
def test_lazy_origins_remain_distinct_for_humans_and_model_seats(tmp_path, monkeypatch, same_place):
    from tests.test_lock_choices import install
    from tests.test_agent_seats import runner_for, raw_state
    records = [{'id': 'test:origin:a', 'label': 'First air current', 'position': {'x': 2, 'y': 6}},
               {'id': 'test:origin:b', 'label': 'Second air current', 'position': {'x': 5, 'y': 6}}]
    if same_place:
        records[1] = {**records[0], 'id': 'test:origin:b'}
    install(monkeypatch, 'effect_origins', lambda engine, actor, action:
        records if actor.entity_id == OWNER and action.target_kind == 'CELL' else [])
    combat, table, mid = setup(tmp_path)
    runner, _ = runner_for(tmp_path, table)
    state = raw_state(runner, mid)
    group = next(g for g in state['menu']['actions'] if g['label'] == 'Gather Current: Press')
    assert group['placement_picker']
    assert len(group['options']) == 3  # physical origin plus both remote origins
    assert {o['effect_origin']['id'] for o in group['options'] if o.get('effect_origin')} == {
        'test:origin:a', 'test:origin:b'}
    session = combat._load_session(mid)
    view, known = runner.own_view(mid, state, OWNER, session)
    from agent_seats.action_options import expand_menu
    options = expand_menu(runner._menu(state, known), session.engine, view,
                          candidates=combat._legal_candidates(session))
    rows = [r for r in options.values() if r['description']['action'].startswith('Gather Current: Press')]
    assert len(rows) == 3
    assert len({r['candidate_id'] for r in rows}) == 3
    assert any('First air current' in r['description']['action'] for r in rows)
    if not same_place:
        assert any('Second air current' in r['description']['action'] for r in rows)
    chosen = next(c for c in combat._legal_candidates(session)
                  if c.source_definition_id == group['source_definition_id']
                  and c.metadata.get('effect_origin', {}).get('id') == 'test:origin:b')
    payload = {k: chosen.model_dump(mode='json')[k] for k in (
        'candidate_id', 'decision_id', 'state_version', 'actor_id', 'target_ids', 'destination', 'option_ids')}
    payload['placement_destination'] = chosen.metadata['placement_witness']
    combat.submit_intent(mid, payload, [], None)
    engine = reload(tmp_path, mid)
    assert any(e.payload.get('effect_origin') == records[1] for e in engine.events)
