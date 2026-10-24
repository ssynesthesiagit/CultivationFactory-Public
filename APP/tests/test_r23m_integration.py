"""Round-18 integration: shared hooks dispatch once through a table commit."""
import importlib

from combat import ext
from combat.gate5_service import CombatService

R = importlib.import_module('tests.test_r2i_reconcile')


def test_combined_attack_hooks_and_single_hit_choice_commit_reload(tmp_path, monkeypatch):
    combat, table, mid = R.fixture(tmp_path, [], R.R.IRON_FIST)
    ext.has('after_hit_choice')  # load the normal plug-ins before adding test observers
    seen = []

    def observe(point):
        def record(ctx, target, *args):
            seen.append((id(ctx.engine), point, target.entity_id))
            assert ctx.attack_result is not None
            assert ctx.attack_effect is not None
        return record

    for point in ('attack_result', 'after_hit_choice', 'attack_resolved'):
        monkeypatch.setitem(ext._HOOKS, point, [*ext._HOOKS[point], observe(point)])
    result = R.act(combat, table, mid, 'Fu (Short Axe) attack', R.R.FOE)
    assert result['status'] == 'COMMITTED'
    # Table actions execute a preview and then a commit, each on its own engine.
    assert seen
    for engine_id in {entry[0] for entry in seen}:
        assert [point for eid, point, target in seen if eid == engine_id] == [
            'attack_result', 'after_hit_choice', 'attack_resolved']
    loaded = CombatService(R.R.ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.model_dump(mode='json') == combat._load_session(mid).engine.state.model_dump(mode='json')
    assert loaded.mechanical.replay()['status'] == 'PASS'
