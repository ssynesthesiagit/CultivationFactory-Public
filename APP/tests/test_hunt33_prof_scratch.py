"""SCRATCH profiling wrapper for SPEEDHUNT33. Not committed."""
import cProfile, io, os, pstats, time

from tests.test_hunt33_frightened import (
    test_moon_table_routes_filter_fear_before_movement_and_sweep as _moon,
)

OUT = '/var/tmp/hunt33-prof'


def test_prof_moon_true_true(tmp_path, monkeypatch):
    os.makedirs(OUT, exist_ok=True)
    pr = cProfile.Profile()
    t0 = time.time()
    pr.enable()
    try:
        _moon(tmp_path, monkeypatch, frightened=True, invisible=True)
    finally:
        pr.disable()
    wall = time.time() - t0
    pr.dump_stats(OUT + '/moon_tt.prof')
    buf = io.StringIO()
    buf.write('WALL %.1f s\n' % wall)
    for key in ('cumulative', 'tottime'):
        st = pstats.Stats(pr, stream=buf)
        st.sort_stats(key).print_stats(45)
    with open(OUT + '/moon_tt.txt', 'w') as fh:
        fh.write(buf.getvalue())
