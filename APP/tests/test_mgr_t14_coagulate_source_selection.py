"""Coagulate ends the chosen ordinary wound through real consent and table use."""
from tests.test_mgr_t14_clinical_native import (
    A, B, game, anatomy, exposure, start, engine, use, clinical,
    final_native_mechanical_replay,
)


def test_coagulate_ends_the_selected_wound_and_preserves_another_source(tmp_path, monkeypatch):
    cold, table, jid, command, world = game(tmp_path, monkeypatch, spheres=('blood',))
    anatomy(world)
    first = exposure(world, label='First cut')
    second = exposure(world, label='Second cut')
    mid = start(cold, jid)
    use(cold, table, mid, 'Blood Thread: willing creature (any creature)')
    loaded = engine(cold, mid)
    selected = next(c.instance_id for c in clinical(loaded.state.actors[B], 'ordinary_bleeding')
                    if c.data['clinical']['source_instance'] == second)
    before = loaded.state.actors[A].resources['resource:core.qi']
    offered = []
    def choose(prompt, ids):
        if selected in ids:
            offered.extend(ids)
            return [selected]
        return ids[:1]
    use(cold, table, mid, 'Coagulate: End Bleeding (any creature)', choose=choose)
    loaded = engine(cold, mid)
    remaining = clinical(loaded.state.actors[B], 'ordinary_bleeding')
    assert selected in offered
    assert [c.data['clinical']['source_instance'] for c in remaining] == [first]
    assert loaded.state.actors[A].resources['resource:core.qi'] == before - 1
