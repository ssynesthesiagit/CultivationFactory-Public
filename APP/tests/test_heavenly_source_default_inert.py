"""Narrow diagnostics/regressions for the shared default-inert Foundation seam."""
from combat import ext
from combat.feature_availability import available
from combat.ext import foundation_combat as foundation
from combat.relations import relation, ENEMY
from tests import test_a2_foundations_two as prior
from tests.worker2_support import OWNER, FOE, turn, reload


def test_unowned_source_preserves_existing_compiled_foundation_rows(tmp_path):
    combat, table, mid = prior.table_fixture(tmp_path, 'tyrant')
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[OWNER]
    feature = foundation.feature('tyrant', 'imperial_shoulder_gate')
    replies = ext.run_strict('feature_available', engine, actor, feature)
    assert available(engine, actor, feature), {'availability_replies': replies}
    rows = [(r.get('block'), r.get('kind'), r.get('feature_id'))
            for r in engine.typed_passive_rows.get(OWNER, [])]
    assert foundation.row(engine, actor, 'tyrant', 'imperial_shoulder_gate') is not None, rows
    assert foundation.row(engine, actor, 'tyrant', 'refined_tyrant_momentum') is not None, rows


def test_unowned_source_preserves_hostile_generation(tmp_path):
    combat, table, mid = prior.table_fixture(tmp_path, 'tyrant', current=0)
    turn(table, mid, FOE)
    engine = combat._load_session(mid).engine
    assert relation(engine, engine.state.actors[FOE], engine.state.actors[OWNER]) == ENEMY
    rows = [r for r in engine.typed_passive_rows.get(OWNER, []) if r.get('block') == 'generate']
    assert rows, [(r.get('block'), r.get('kind'), r.get('feature_id'))
                  for r in engine.typed_passive_rows.get(OWNER, [])]
    prior.use(combat, table, mid, 'Hostile blow', OWNER)
    after = reload(tmp_path, mid)
    assert after.state.actors[OWNER].resources[foundation.pool('tyrant')] == 1
