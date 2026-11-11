"""Knowledge-projected area previews own a fresh, read-only query frame."""
from collections import Counter

from combat import area_safety, read_queries
from tests.h1_support import ROOT


def test_service_menu_reuses_geometry_inside_each_projected_preview(tmp_path, monkeypatch):
    from combat.gate5_service import CombatService
    from tests.worker2_support import fixture, settle

    combat, table, mid = fixture(tmp_path, ['DARK_BASE_DARKNESS'])
    session = combat._load_session(mid)
    preview, memo = area_safety.preview, read_queries.memo
    active = None
    samples = []

    def counted(engine, key, compute):
        def evaluate():
            if active is not None and key[0] == 'volume_positions':
                active[(id(engine), key)] += 1
            return compute()
        return memo(engine, key, evaluate)

    def measured(*args, **kwargs):
        nonlocal active
        previous = active
        active = Counter()
        try:
            result = preview(*args, **kwargs)
            if active:
                samples.append(active)
            return result
        finally:
            active = previous

    monkeypatch.setattr(read_queries, 'memo', counted)
    monkeypatch.setattr(area_safety, 'preview', measured)
    first = CombatService(ROOT, tmp_path)._legal_candidates(session)
    # Service menus defer square enumeration to the placement picker. Expand
    # its current public path instead of requiring eager destination rows.
    from combat.placement_menu import cells
    roots = [c for c in first if c.metadata.get('placement_picker')]
    assert roots and all(c.destination is None for c in roots)
    placements = list(cells(session.engine, roots[0]))
    assert samples and placements
    assert all(c.destination is not None and c.kind.value != 'MOVE' for c in placements)
    assert max(max(sample.values()) for sample in samples) == 1, 'projected preview recomputed identical membership'
    # A separate menu gets a fresh projection and produces the exact same choices.
    before = [c.model_dump(mode='json') for c in first]
    again = CombatService(ROOT, tmp_path)._legal_candidates(combat._load_session(mid))
    assert [c.model_dump(mode='json') for c in again] == before
    hold = next(c.candidate_id for c in first if c.source_definition_id == 'system:combat.hold_position')
    settle(table, mid, hold)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    assert table.state(mid)['menu']


def test_preview_frame_restores_outer_queries_after_errors(monkeypatch):
    import pytest
    from combat import ext
    from tests.h1_support import duel, ME

    engine = duel(['DARK_BASE_DARKNESS'])
    actor = engine.state.actors[ME]
    action = next(a for a in engine.action_catalog.values()
                  if (a.parameters.get('typed') or {}).get('area'))
    risk = area_safety._risk

    @read_queries.pure
    def outer(engine):
        marker = read_queries.memo(engine, ('speed3_outer',), object)
        def broken(*args, **kwargs):
            raise ext.CheckpointError('preview probe')
        with monkeypatch.context() as patch:
            patch.setattr(area_safety, '_risk', broken)
            with pytest.raises(ext.CheckpointError, match='preview probe'):
                area_safety.preview(engine, actor, action, actor.position)
        assert read_queries.memo(engine, ('speed3_outer',), object) is marker
        return area_safety.preview(engine, actor, action, actor.position)

    assert outer(engine) == area_safety.preview(engine, actor, action, actor.position)
    assert area_safety._risk is risk


def test_menu_derives_each_actions_recipient_scope_once_and_lists_the_same_candidates(monkeypatch):
    from combat import area_recipients, typed_executor
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    from tests.h1_support import duel, ME

    engine = duel([], ally_mids=[])
    # A burst on "other creatures": the squares beside the foe also catch the ally standing next to the caster.
    source = 'test:speed3-burst'
    area = {'shape': 'sphere', 'size_ft': 10, 'explicit_harmful_recipients': 'other_creatures'}
    engine.action_catalog[source] = ActionDefinition(source_definition_id=source, owner_id=ME,
        display_name='Practice burst', economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='CELL',
        range_ft=60, radius_ft=10, parameters={'expected_damage': 8, 'typed': {'area': area,
                                               'effects': [{'type': 'damage', 'dice': {'count': 1, 'sides': 6}}]}})
    engine.state.actors[ME].action_ids += (source,)
    derived, previews = [], []
    scoped, preview = area_recipients.scoped_area, area_safety.preview
    monkeypatch.setattr(area_recipients, 'scoped_area', lambda *a, **k: derived.append(1) or scoped(*a, **k))
    monkeypatch.setattr(area_safety, 'preview', lambda *a, **k: previews.append(1) or preview(*a, **k))
    shared = [c.model_dump(mode='json') for c in engine.legal_candidates()]
    assert len(previews) > 20 and any(c['metadata'].get('allies_in_area') for c in shared)
    assert len(derived) * 4 < len(previews), 'the scope was re-derived for every previewed square'
    # Deriving it afresh each time is only slower: the menu lists exactly the same candidates.
    derived.clear()
    monkeypatch.setattr(typed_executor, '_scoped_area',
                        lambda engine, area, effects, typed: area_recipients.scoped_area(area, effects, typed=typed))
    assert [c.model_dump(mode='json') for c in engine.legal_candidates()] == shared
    assert len(derived) >= len(previews)


def test_shared_recipient_scope_never_outlives_its_pass_or_a_recorded_change(monkeypatch):
    from combat import area_recipients, typed_executor
    from tests.h1_support import duel

    engine = duel([])
    effects = [{'type': 'damage', 'dice': {'count': 1, 'sides': 6}}]
    area = {'shape': 'sphere', 'size_ft': 10, 'explicit_harmful_recipients': 'other_creatures'}
    typed = {'area': area, 'effects': effects}
    derived = []
    scoped = area_recipients.scoped_area
    monkeypatch.setattr(area_recipients, 'scoped_area', lambda *a, **k: derived.append(1) or scoped(*a, **k))
    def ask():
        return typed_executor._scoped_area(engine, area, effects, typed)

    with read_queries.candidate_pass(engine):
        first = ask()
        assert ask() is first and len(derived) == 1
        # A recorded change inside the pass is derived afresh, never served from the earlier answer.
        engine.state.event_sequence += 1
        assert ask() == first and len(derived) == 2
    # Nothing survives the pass: the next one derives once more, and outside a pass every ask derives.
    with read_queries.candidate_pass(engine):
        ask()
        ask()
        assert len(derived) == 3
    ask()
    ask()
    assert len(derived) == 5


def test_saved_area_binding_refreshes_on_revision_and_next_pass(monkeypatch):
    from combat import area_knowledge
    from tests.h1_support import duel

    engine = duel([])
    native = area_knowledge.saved_policy
    scans = []
    def counted(events):
        scans.append(events)
        return native(events)
    monkeypatch.setattr(area_knowledge, 'saved_policy', counted)
    with read_queries.candidate_pass(engine):
        expected = area_knowledge.enabled(engine)
        assert area_knowledge.enabled(engine) == expected
        assert len(scans) == 1
        engine.state.event_sequence += 1
        assert area_knowledge.enabled(engine) == expected
        assert len(scans) == 2
    assert area_knowledge.enabled(engine) == expected
    assert len(scans) == 3
    with read_queries.candidate_pass(engine):
        assert area_knowledge.enabled(engine) == expected
        assert len(scans) == 4
        engine.events = [*engine.events, {'event_type': 'SAVED_FIGHT_CONTINUED',
                                         'payload': {area_knowledge.STAMP: int(not expected)}}]
        # Continuation cannot change a sealed creation policy. Replacing the
        # list still invalidates the memo and re-reads the authoritative stamp.
        assert area_knowledge.enabled(engine) == expected
        assert len(scans) == 5
        engine.events = [{'event_type': 'MATCH_CREATED',
                          'payload': {area_knowledge.STAMP: int(not expected)}}]
        assert area_knowledge.enabled(engine) != expected
        assert len(scans) == 6


def test_origin_binding_reuses_only_successful_reads(monkeypatch):
    import pytest
    from combat import area_knowledge
    from tests.h1_support import duel

    engine = duel(['DARK_BASE_DARKNESS'])
    action = next(a for a in engine.action_catalog.values()
                  if (a.parameters.get('typed') or {}).get('area'))
    # Exercise the saved source permission route, rather than an explicit override.
    typed = dict(action.parameters['typed'])
    typed.pop('requires_seen_origin', None)
    typed.pop('requires_seen_target', None)
    action = action.model_copy(update={'parameters': {'typed': typed}})
    native = area_knowledge.saved_origin_permissions
    scans = []
    def counted(events):
        scans.append(1)
        return native(events)
    monkeypatch.setattr(area_knowledge, 'saved_origin_permissions', counted)
    with read_queries.candidate_pass(engine):
        expected = area_knowledge.requires_seen_origin(engine, action)
        assert area_knowledge.requires_seen_origin(engine, action) == expected
        assert len(scans) == 1
        engine.events = [{'event_type': 'MATCH_CREATED', 'payload': {}}]
        for _ in range(2):
            with pytest.raises(ValueError, match='no saved area origin permissions'):
                area_knowledge.requires_seen_origin(engine, action)
        assert len(scans) == 3
