"""One saved session and one square choice per table action (SPEEDSEAM1)."""
import inspect

from combat import placement_menu
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from tests.test_tabletop_speed import _Counter
from tests.worker2_support import ALLY, FOE, OWNER, ROOT, fixture


class TraceCounter(_Counter):
    """The tabletop counter plus the caller of each expensive operation."""
    def __init__(self, monkeypatch):
        self.load_sites, self.build_sites, self.slow_sites = [], [], []
        super().__init__(monkeypatch)
        counted = Gate4ControllerEngine.legal_candidates

        def generate(engine):
            self.build_sites.append(self.site())
            return counted(engine)

        monkeypatch.setattr(Gate4ControllerEngine, 'legal_candidates', generate)
        resolve = placement_menu.resolve

        def binding(engine, actor, action, root, intent):
            if root.metadata.get('placement_picker') and intent.placement_destination is None:
                self.slow_sites.append(self.site())
            return resolve(engine, actor, action, root, intent)

        monkeypatch.setattr(placement_menu, 'resolve', binding)

    @staticmethod
    def site():
        return ' <- '.join(f'{f.function}:{f.lineno}' for f in inspect.stack()[2:8])

    def watch(self, combat):
        load = combat.persistence.load_match

        def loading(*args, **kwargs):
            self.load_sites.append(self.site())
            return load(*args, **kwargs)

        self.monkeypatch.setattr(combat.persistence, 'load_match', loading)
        return self

    def reset(self):
        self.load_sites.clear()
        self.build_sites.clear()
        self.slow_sites.clear()

    def counts(self):
        return (f'loads={len(self.load_sites)} {self.load_sites}; '
                f'builds={len(self.build_sites)} {self.build_sites}; '
                f'slow={len(self.slow_sites)} {self.slow_sites}')


def test_area_picker_answer_then_commit_does_not_rechoose(tmp_path, monkeypatch):
    monkeypatch.setenv('CF_EMBED_MENU', '0')
    combat, table, mid = fixture(tmp_path, ['TAL_AIR_COURT_OF_THE_FOUR_WINDS'])
    menu = table.state(mid)['menu']
    root = next(c for c in combat._legal_candidates(table.fights.session(mid))
                if c.metadata.get('placement_picker') and 'Gather Current: Press' in c.display_name)
    first = table.act(mid, root.candidate_id, menu['decision_id'], menu['state_version'], 0)
    assert first['status'] == 'REACTION_REQUIRED'
    prompt = first['reaction']
    assert prompt['context']['reaction_source_id'] == placement_menu.CHOICE
    # Choose a real offered square, not necessarily the recommendation.
    option = prompt['choice']['options'][-1]['id']
    answer = {**prompt['context'], 'selection': 'USE', 'option_ids': [option]}
    counts = TraceCounter(monkeypatch).watch(combat)
    # The picker has already paused. Count the continuation, its preview and commit.
    result = table.act(mid, root.candidate_id, menu['decision_id'], menu['state_version'], 0, [answer])
    assert result['status'] == 'COMMITTED'
    assert len(counts.slow_sites) <= 1, counts.counts()
    assert len(counts.load_sites) <= 1, counts.counts()
    assert len(counts.build_sites) <= 2, counts.counts()
    assert any(z.center is not None for z in table.fights.session(mid).engine.state.zones.values())


def test_local_run_uses_one_load_for_several_steps(tmp_path, monkeypatch):
    monkeypatch.setenv('CF_EMBED_MENU', '0')
    combat, _, mid = fixture(tmp_path, [], ask=False,
        modes={OWNER: 'LOCAL_AUTO', ALLY: 'LOCAL_AUTO', FOE: 'LOCAL_AUTO'})
    combat = CombatService(ROOT, tmp_path)
    counts = TraceCounter(monkeypatch).watch(combat)
    result = combat.local_run(mid, maximum_steps=3)
    assert len(result['steps']) >= 2, result
    assert len(counts.load_sites) == 1, counts.counts()


def test_readers_reuse_warm_session_without_changing_it(tmp_path, monkeypatch):
    monkeypatch.setenv('CF_EMBED_MENU', '0')
    combat, table, mid = fixture(tmp_path, [], ask=False)
    table.prewarm_menus = False
    menu = table.state(mid)['menu']
    session = table.fights.session(mid)
    before = session.engine.state.model_dump(mode='json')
    grid = session.engine.grid
    geometry = (set(grid.blocked), set(grid.opaque), set(grid.cover), dict(grid.base_movement_cost))
    counts = TraceCounter(monkeypatch).watch(combat)
    source = menu['actions'][0]['source_definition_id']
    move = next(m for m in menu['moves'] if m['movement_mode'] == 'walk')
    calls = [
        ('expand_action', lambda: table.expand_action(mid, source, menu['decision_id'], menu['state_version'])),
        ('preview_destination', lambda: table.preview_destination(mid, menu['decision_id'], menu['state_version'],
                                                                   menu['actor_id'], move['destination'])),
        ('preview_move_path', lambda: table.preview_move_path(mid, menu['decision_id'], menu['state_version'],
                                                               menu['actor_id'], move['path'])),
        ('summary', lambda: table.summary(mid)),
        ('state with menu', lambda: table.state(mid, fog=True)),
    ]
    for name, call in calls:
        counts.reset()
        call()
        assert not counts.load_sites, f'{name}: {counts.counts()}'
        assert session.engine.state.model_dump(mode='json') == before, name
        assert (grid.blocked, grid.opaque, grid.cover, grid.base_movement_cost) == geometry, name

    # Exercise the worker synchronously; no background test jobs.
    counts.reset()
    table._warm_requests[mid] = menu['state_version']
    table._warm_menus()
    assert not counts.load_sites, f'warm_menus: {counts.counts()}'
    assert session.engine.state.model_dump(mode='json') == before


def test_standalone_steps_and_table_share_the_host(tmp_path, monkeypatch):
    monkeypatch.setenv('CF_EMBED_MENU', '0')
    combat, table, mid = fixture(tmp_path, [], ask=False,
        modes={OWNER: 'LOCAL_AUTO', ALLY: 'LOCAL_AUTO', FOE: 'LOCAL_AUTO'})
    assert table.fights is combat.fight_host()
    counts = TraceCounter(monkeypatch).watch(combat)
    for _ in range(2):
        result = combat.local_step(mid)
        assert result['status'] == 'COMMITTED', result
    assert len(counts.load_sites) <= 1, counts.counts()
    assert table.fights is combat.fight_host()


def test_auto_step_does_not_build_a_player_menu_for_an_ai_turn(tmp_path, monkeypatch):
    monkeypatch.setenv('CF_EMBED_MENU', '0')
    combat, _, mid = fixture(tmp_path, [], ask=False,
        modes={OWNER: 'LOCAL_AUTO', ALLY: 'LOCAL_AUTO', FOE: 'LOCAL_AUTO'})
    fresh = CombatService(ROOT, tmp_path)
    from combat.tabletop_service import TabletopService
    table = TabletopService(fresh, tmp_path)
    counts = TraceCounter(monkeypatch).watch(fresh)
    result = table.auto_step(mid, 0, defer_menu=True)
    assert result['status'] == 'COMMITTED', result
    assert len(counts.build_sites) <= 1, counts.counts()
